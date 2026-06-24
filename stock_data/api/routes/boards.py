"""Board endpoints (concept / industry / index / special) + ZT/DT/ZBGC pools.

``source`` query parameter is REQUIRED and selects the fetcher:
- ``eastmoney``: EastMoneyFetcher (akshare EM backend)
- ``zhitu``: ZhituFetcher (zhituapi.com)

Each source has its own board classification system; failover between
sources is intentionally not supported (different code systems).
"""

import logging
from datetime import date as date_cls
from typing import Literal

from fastapi import HTTPException, Path, Query

from ...data_provider.persistence import board as stock_board_cache
from ...data_provider.persistence import trade_calendar
from ..cache import (
    cached_lookup,
    cached_store,
    get_pools_cache,
    is_cache_enabled,
    make_pools_cache_key,
)
from ..endpoint_meta import endpoint_meta
from ..schemas import (
    BoardInfo,
    BoardListResponse,
    BoardStockInfo,
    BoardStocksResponse,
    ErrorResponse,
    StockBoardInfo,
    StockBoardsResponse,
    ZTPoolResponse,
    ZTPoolStock,
)
from ._router import router
from .errors import map_errors
from .helpers import get_manager

logger = logging.getLogger(__name__)


# source 合法值集合（防止任意 source 触发 _with_source 任意调用）
_VALID_SOURCES = {"eastmoney", "zhitu"}

# type 合法值
_VALID_TYPES = {"concept", "industry", "index", "special"}


def _resolve_source(source: str) -> str:
    """Validate source parameter; raise HTTPException(400) on invalid."""
    if source not in _VALID_SOURCES:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_source",
                "message": f"Unknown source '{source}'. Valid sources: {sorted(_VALID_SOURCES)}",
            },
        )
    return source


def _resolve_type(board_type: str) -> str:
    """Validate type parameter."""
    if board_type not in _VALID_TYPES:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_type",
                "message": f"Unknown type '{board_type}'. Valid types: {sorted(_VALID_TYPES)}",
            },
        )
    return board_type


@router.get(
    "/boards",
    response_model=BoardListResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid source/type/subtype"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["boards"],
)
@endpoint_meta(
    summary="板块清单（支持实时报价、排序、截断）",
    markets=["csi"],
    capabilities=["STOCK_BOARD"],
)
@map_errors
def list_boards(
    type: Literal["concept", "industry", "index", "special"] = Query(
        ..., description="Board type"
    ),
    source: Literal["eastmoney", "zhitu"] = Query(
        ..., description="Data source (REQUIRED)"
    ),
    subtype: str | None = Query(
        None,
        description="Source-specific subtype. Validated per (source, type) pair. "
        "Omit to return all subtypes for the type.",
    ),
    include_quote: bool = Query(False, description="Include realtime quote fields"),
    sort_by: Literal["change_pct", "volume", "amount", "price"] | None = Query(
        None, description="Sort by field (requires include_quote=true)"
    ),
    sort_order: Literal["asc", "desc"] = Query("desc", description="Sort order"),
    limit: int | None = Query(
        None, ge=1, le=500, description="Max number of items (default: all)"
    ),
    refresh: bool = Query(False, description="Force fetch latest from upstream"),
) -> BoardListResponse:
    """Get list of concept / industry / index / special boards."""
    _resolve_source(source)
    _resolve_type(type)

    # subtype validation — early failure before manager invocation
    stock_board_cache._validate_subtype(source, type, subtype)

    # sort_by requires include_quote (the sort fields are quote fields)
    if sort_by is not None and not include_quote:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_combination",
                "message": "sort_by requires include_quote=true",
            },
        )

    manager = get_manager()

    # Manager.get_all_boards 通过 _with_source 路由到 source 对应的 fetcher，
    # 统一调用其 get_all_boards(board_type, subtype) 方法。
    try:
        boards, origin = manager.get_all_boards(
            source=source,
            board_type=type,
            subtype=subtype,
            include_quote=include_quote,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"error": str(e)})

    # Sort
    if sort_by is not None:
        boards = sorted(
            boards,
            key=lambda b: b.get(sort_by) or 0,
            reverse=(sort_order == "desc"),
        )

    # Truncate
    if limit is not None:
        boards = boards[:limit]

    return BoardListResponse(
        source=origin,
        data=[
            BoardInfo(
                code=b["code"],
                name=b["name"],
                price=b.get("price"),
                change_pct=b.get("change_pct"),
                change_amount=b.get("change_amount"),
                volume=b.get("volume"),
                amount=b.get("amount"),
                turnover_rate=b.get("turnover_rate"),
                total_mv=b.get("total_mv"),
                up_count=b.get("up_count"),
                down_count=b.get("down_count"),
                leading_stock=b.get("leading_stock"),
                leading_stock_pct=b.get("leading_stock_pct"),
            )
            for b in boards
        ],
    )


@router.get(
    "/boards/{board_code}/stocks",
    response_model=BoardStocksResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid source"},
        404: {"model": ErrorResponse, "description": "Board not found"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["boards"],
)
@endpoint_meta(
    summary="板块成分股",
    markets=["csi"],
    capabilities=["STOCK_BOARD"],
    fetcher_method="get_board_stocks",
)
@map_errors
def get_board_stocks(
    board_code: str = Path(max_length=30, description="Board code"),
    source: Literal["eastmoney", "zhitu"] = Query(
        ..., description="Data source (REQUIRED)"
    ),
    include_quote: bool = Query(False, description="Include realtime quote data"),
    refresh: bool = Query(False, description="Force fetch latest from upstream"),
) -> BoardStocksResponse:
    """Get stocks belonging to a board."""
    _resolve_source(source)

    manager = get_manager()
    try:
        stocks, origin = manager.get_board_stocks(
            board_code, source=source, include_quote=include_quote,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"error": str(e)})

    if not stocks:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "message": f"No stocks found for board {board_code}"},
        )

    # Best-effort board name resolution (try concept + industry)
    board_name = board_code
    try:
        for bt in ("concept", "industry"):
            boards, _ = manager.get_all_boards(
                source=source, board_type=bt, subtype=None,
            )
            match = next((b["name"] for b in boards if b["code"] == board_code), None)
            if match:
                board_name = match
                break
    except ValueError:
        pass

    stock_list = [
        BoardStockInfo(
            code=s.get("stock_code", ""),
            name=s.get("stock_name", ""),
            price=s.get("price"),
            change_pct=s.get("change_pct"),
            volume=s.get("volume"),
        )
        for s in stocks
    ]

    return BoardStocksResponse(
        board=BoardInfo(code=board_code, name=board_name),
        stocks=stock_list,
        query_source=source,
        data_source=origin,
    )


@router.get(
    "/stocks/{stock_code}/boards",
    response_model=StockBoardsResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid source/type/subtype"},
        404: {"model": ErrorResponse, "description": "Stock not found"},
        501: {"model": ErrorResponse, "description": "Source does not implement this endpoint"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["boards"],
)
@endpoint_meta(
    summary="股票所属板块（新增）",
    markets=["csi"],
    capabilities=["STOCK_BOARD"],
    fetcher_method="get_stock_boards",
)
@map_errors
def get_stock_boards(
    stock_code: str = Path(max_length=20, description="Stock code (e.g. 000001)"),
    source: Literal["zhitu", "eastmoney"] = Query(
        ..., description="Data source (currently only 'zhitu' supported)"
    ),
    type: Literal["concept", "industry", "index", "special"] | None = Query(
        None, description="Filter by board type"
    ),
    subtype: str | None = Query(
        None, description="Filter by source-specific subtype"
    ),
) -> StockBoardsResponse:
    """Get boards a stock belongs to.

    Currently only ``source=zhitu`` is supported. EastMoney's API does not
    expose a direct stock→boards mapping.
    """
    _resolve_source(source)

    if source != "zhitu":
        raise HTTPException(
            status_code=501,
            detail={
                "error": "not_implemented",
                "message": f"source='{source}' does not implement stock->boards lookup. "
                f"Currently supported: 'zhitu'",
            },
        )

    # Subtype validation only if provided
    if type is not None:
        _resolve_type(type)
        stock_board_cache._validate_subtype(source, type, subtype)

    manager = get_manager()
    try:
        boards, origin = manager.get_stock_boards(
            stock_code, source=source,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"error": str(e)})

    # boards may be None (fetcher signal: no data); treat as 404
    if boards is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "not_found",
                "message": f"No board data for stock {stock_code} (source={source})",
            },
        )

    # Filter by type/subtype if specified
    if type is not None:
        boards = [b for b in boards if b.get("type") == type]
    if subtype is not None:
        boards = [b for b in boards if b.get("subtype") == subtype]

    if not boards:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "not_found",
                "message": f"No boards found for stock {stock_code} "
                f"(source={source}, type={type}, subtype={subtype})",
            },
        )

    return StockBoardsResponse(
        stock_code=stock_code,
        source=origin,
        data=[
            StockBoardInfo(
                code=b["code"],
                name=b["name"],
                type=b.get("type", ""),
                subtype=b.get("subtype", ""),
            )
            for b in boards
        ],
    )


@router.get(
    "/boards/{board_code}/history",
    responses={
        400: {"model": ErrorResponse, "description": "Invalid source"},
        501: {"model": ErrorResponse, "description": "Source does not yet support board K-line"},
    },
    tags=["boards"],
)
@endpoint_meta(
    summary="板块 K 线（新增, 占位 — 暂未实现）",
    markets=["csi"],
    capabilities=["STOCK_BOARD"],
    fetcher_method="get_board_history",
)
@map_errors
def get_board_history(
    board_code: str = Path(max_length=30, description="Board code"),
    source: Literal["zhitu", "eastmoney"] = Query(
        ..., description="Data source"
    ),
    frequency: Literal["d", "w", "m"] = Query("d", description="K-line frequency"),
    start_date: str | None = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: str | None = Query(None, description="End date (YYYY-MM-DD)"),
    days: int = Query(30, ge=1, le=365, description="Days (when start_date not given)"),
) -> dict:
    """Get historical K-line for a board. Currently a 501 stub."""
    _resolve_source(source)
    raise HTTPException(
        status_code=501,
        detail={
            "error": "not_implemented",
            "message": f"Board K-line for source='{source}' is not yet implemented. "
            f"Consider contributing via EastMoney's board index.",
        },
    )


@router.get(
    "/zt-pools",
    response_model=ZTPoolResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid pool type"},
        404: {"model": ErrorResponse, "description": "No data found for date"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["zt-pools"],
)
@endpoint_meta(
    summary="涨跌停股池",
    markets=["csi"],
    capabilities=["STOCK_ZT_POOL"],
)
@map_errors
def get_pools(
    type: str = Query(
        ...,
        pattern="^(zt|dt|zbgc)$",
        description="Pool type: zt (涨停) / dt (跌停) / zbgc (炸板)",
    ),
    date: str | None = Query(
        None,
        description=(
            "Pool date (YYYY-MM-DD). If not provided, the server picks the most recent "
            "trade date relative to today: today itself when today is a trade day, "
            "otherwise the latest cached trade date <= today."
        ),
    ),
    refresh: bool = Query(
        False,
        description=(
            "Force refresh from upstream. Bypasses the persistence read, but the "
            "persistence write is still skipped when the resolved date is the "
            "'current trading day' (today AND today is a trade day), to avoid "
            "persisting a partially-formed pool."
        ),
    ),
) -> ZTPoolResponse:
    """Get ZT (涨跌停) pool data for a specific type and date."""
    # Resolve query_date.
    today_str = date_cls.today().strftime("%Y-%m-%d")

    if date:
        query_date = date
    else:
        if trade_calendar.is_trade_date(today_str):
            query_date = today_str
        else:
            resolved = trade_calendar.get_latest_trade_date_on_or_before(today_str)
            # Edge case: trade_calendar table is empty. Fall back to today so
            # the caller gets a clear upstream error rather than a silent 404.
            query_date = resolved or today_str

    # `is_current_day` is the route-layer's volatile-data toggle only — it
    # drives the in-process TTLCache. The persistence layer (pool_daily.get_pool)
    # computes the same decision internally to control SQLite read/write/fallback.
    is_current_day = (query_date == today_str) and trade_calendar.is_trade_date(today_str)

    cache_key = make_pools_cache_key(type, query_date)
    if is_current_day and is_cache_enabled():
        hit = cached_lookup(get_pools_cache, cache_key, "pools")
        if hit is not None:
            return hit

    manager = get_manager()
    stocks, origin = manager.get_zt_pool(
        pool_type=type,
        date=query_date,
        refresh=refresh,
    )

    if not stocks:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "message": f"No {type} pool data found"},
        )

    actual_date = query_date or stocks[0].get("pool_date", "")

    pool_stocks = [
        ZTPoolStock(
            code=s.get("code", ""),
            name=s.get("name", ""),
            price=s.get("price"),
            change_pct=s.get("change_pct"),
            amount=s.get("amount"),
            circ_mv=s.get("circ_mv"),
            total_mv=s.get("total_mv"),
            turnover_rate=s.get("turnover_rate"),
            lb_count=s.get("lb_count"),
            first_seal_time=s.get("first_seal_time"),
            last_seal_time=s.get("last_seal_time"),
            seal_amount=s.get("seal_amount"),
            seal_count=s.get("seal_count"),
            zt_count=s.get("zt_count"),
        )
        for s in stocks
    ]

    result = ZTPoolResponse(
        date=actual_date,
        type=type,
        total=len(pool_stocks),
        stocks=pool_stocks,
        source=origin,
    )

    if is_current_day:
        cached_store(get_pools_cache, cache_key, result)
    return result
