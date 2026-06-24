"""Board endpoints (concept / industry) + ZT/DT/ZBGC pools.

``stock_board_cache`` is the SQLite persistence layer for board metadata
and stock-board mappings. The endpoints here never touch the upstream
directly; the persistence layer encapsulates refresh + fetch + fallback.
"""

from datetime import date as date_cls

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
    ZTPoolResponse,
    ZTPoolStock,
)
from ._router import router
from .errors import map_errors
from .helpers import get_manager


@router.get(
    "/boards",
    response_model=BoardListResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid board type"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["boards"],
)
@endpoint_meta(
    summary="概念 / 行业板块列表",
    markets=["csi"],
    capabilities=["STOCK_BOARD"],
)
@map_errors
def list_boards(
    type: str = Query(
        ...,
        pattern="^(concept|industry)$",
        description="Board type: concept or industry",
    ),
    source: str = Query(default="eastmoney", description="Data source"),
    include_quote: bool = Query(False, description="Include realtime quote data"),
    refresh: bool = Query(False, description="Force fetch latest from upstream"),
) -> BoardListResponse:
    """Get list of concept or industry boards."""
    manager = get_manager()
    boards, origin = stock_board_cache.get_board_list(
        type, source, refresh=refresh, include_quote=include_quote, manager=manager
    )

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
        404: {"model": ErrorResponse, "description": "Board not found"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["boards"],
)
@endpoint_meta(
    summary="板块成分股",
    markets=["csi"],
    capabilities=["STOCK_BOARD"],
    fetcher_method="get_board_stocks",          # default get_all_boards is the list variant
)
@map_errors
def get_board_stocks(
    board_code: str = Path(max_length=20, description="Board code (e.g., BK1048)"),
    source: str = Query(default="eastmoney", description="Data source"),
    include_quote: bool = Query(False, description="Include realtime quote data"),
    refresh: bool = Query(False, description="Force fetch latest from upstream"),
) -> BoardStocksResponse:
    """Get stocks belonging to a board."""
    manager = get_manager()
    stocks, origin = stock_board_cache.get_board_stocks(
        board_code, source, refresh=refresh, include_quote=include_quote, manager=manager
    )

    if not stocks:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "message": f"No stocks found for board {board_code}"},
        )

    # Get board name — try both types since "BK" prefix is shared
    board_name = board_code
    for bt in ("concept", "industry"):
        boards, _ = stock_board_cache.get_board_list(bt, source, refresh=False, manager=manager)
        match = next((b["name"] for b in boards if b["code"] == board_code), None)
        if match:
            board_name = match
            break

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
