"""Agent batch / aggregation endpoints.

All endpoints under ``/api/v1/agent/*`` live here. They fan-out across
multiple existing ``DataFetcherManager`` calls and apply server-side
join / set-arithmetic that the agent would otherwise do by hand.

Design contract (see ``docs/agent-batch-api-proposal-2026-07-27.md``):
- Per-item error isolation: one failure never aborts the response.
- JSON-only output (Phase 1); ``?format=md`` lands in Phase 2.4.
- No LLM judgment — only numeric filter, set-op, count statistics.
- ``@endpoint_meta(capabilities=[])`` because the endpoints don't map
  to a single capability flag.

Routes added in Phase 1 (this file):
- POST /agent/boards/stock-overlap (renamed from boards/overlap per 2026-07-27 user request)
- POST /agent/stocks/board-overlap
- POST /agent/boards/filter-stocks
"""

import logging
from itertools import combinations

from fastapi import HTTPException

from ...data_provider.base import DataFetchError
from ...data_provider.persistence import board as stock_board_cache
from ..cache import (
    cached_lookup,
    cached_store,
    get_quote_cache,  # reused as generic in-memory slot for agent results
    is_cache_enabled,
    make_boards_overlap_cache_key,
    make_filter_stocks_cache_key,
    make_stocks_board_overlap_cache_key,
)
from ..endpoint_meta import endpoint_meta
from ..schemas import (
    BoardsOverlapPair,
    BoardsOverlapRequest,
    BoardsOverlapResponse,
    BoardsOverlapSet,
    ErrorResponse,
    FilterStocksMatchedStock,
    FilterStocksRequest,
    FilterStocksResponse,
    StocksBoardOverlapPair,
    StocksBoardOverlapRequest,
    StocksBoardOverlapResponse,
    StocksBoardOverlapStockSet,
)
from ._router import router
from .errors import map_errors
from .helpers import get_manager

logger = logging.getLogger(__name__)


@router.post(
    "/agent/boards/stock-overlap",
    response_model=BoardsOverlapResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid request"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["agent"],
)
@endpoint_meta(
    summary="板块成分股两两重叠度（set-op 服务端化，替代 LLM 手算交集）",
    markets=["csi"],
    capabilities=[],
)
@map_errors
def post_boards_stock_overlap(payload: BoardsOverlapRequest) -> BoardsOverlapResponse:
    """Compute pairwise stock-set overlap across 2-10 boards.

    Each board is fetched via ``stock_board_cache.get_board_stocks`` with
    ``source='ths', include_quote=False`` (consistent with the existing
    /boards/{code}/stocks path). Per-board failures surface in
    ``errors[]`` without aborting the response.
    """
    cache_key = make_boards_overlap_cache_key(payload.codes)
    hit = cached_lookup(get_quote_cache, cache_key, "agent_boards_stock_overlap")
    if hit is not None:
        return hit

    manager = get_manager()
    sets_out: list[BoardsOverlapSet] = []
    sets_index: dict[str, set[str]] = {}  # code -> set of stock codes
    errors: list[dict] = []

    for code in payload.codes:
        try:
            stocks, _origin, effective_source, _reason, _qtrunc, _total = (
                stock_board_cache.get_board_stocks(
                    code,
                    source="ths",
                    include_quote=False,
                    manager=manager,
                )
            )
        except (DataFetchError, ValueError) as exc:
            logger.warning(f"[agent/boards/stock-overlap] {code} failed: {exc}")
            errors.append({"code": code, "error": type(exc).__name__, "message": str(exc)})
            continue
        codes_set = {
            (s.get("stock_code") or s.get("code") or "").strip()
            for s in stocks
            if (s.get("stock_code") or s.get("code"))
        }
        sets_index[code] = codes_set
        sets_out.append(
            BoardsOverlapSet(code=code, count=len(codes_set), source=effective_source or "ths")
        )

    pairs: list[BoardsOverlapPair] = []
    for a, b in combinations(sets_index.keys(), 2):
        sa, sb = sets_index[a], sets_index[b]
        inter = sorted(sa & sb)
        union = sa | sb
        jaccard = (len(inter) / len(union)) if union else 0.0
        pairs.append(
            BoardsOverlapPair(
                a=a,
                b=b,
                intersection=inter,
                intersection_count=len(inter),
                jaccard=jaccard,
            )
        )

    result = BoardsOverlapResponse(sets=sets_out, pairs=pairs, errors=errors)
    if is_cache_enabled():
        cached_store(get_quote_cache, cache_key, result)
    return result


@router.post(
    "/agent/stocks/board-overlap",
    response_model=StocksBoardOverlapResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid request"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["agent"],
)
@endpoint_meta(
    summary="股票所属板块两两重叠度（龙头 / 候选 板块重叠度服务端化）",
    markets=["csi"],
    capabilities=[],
)
@map_errors
def post_stocks_board_overlap(payload: StocksBoardOverlapRequest) -> StocksBoardOverlapResponse:
    """Pairwise board-overlap across 2-10 stocks.

    Each stock is reverse-looked-up via
    ``stock_board_cache.get_stock_memberships`` with ``source='ths'``
    (per spec §3.2.5). Boards are deduped by ``(code, name)`` to absorb
    name differences across fetchers (irrelevant here — we always use
    ths — but the dedup is a cheap defense).
    """
    cache_key = make_stocks_board_overlap_cache_key(payload.codes)
    hit = cached_lookup(get_quote_cache, cache_key, "agent_stocks_board_overlap")
    if hit is not None:
        return hit

    manager = get_manager()
    sets_out: list[StocksBoardOverlapStockSet] = []
    sets_index: dict[str, set[tuple[str, str]]] = {}
    errors: list[dict] = []

    for code in payload.codes:
        try:
            entries, _cold, _origin = stock_board_cache.get_stock_memberships(
                stock_code=code,
                sources=["ths"],
                manager=manager,
            )
        except (DataFetchError, ValueError) as exc:
            logger.warning(f"[agent/stocks/board-overlap] {code} failed: {exc}")
            errors.append({"code": code, "error": type(exc).__name__, "message": str(exc)})
            continue
        boards = [
            {
                "code": e["code"],
                "name": e.get("name", ""),
                "type": e.get("type", ""),
                "subtype": e.get("subtype", ""),
                "source": e.get("source", ""),
            }
            for e in entries
        ]
        sets_index[code] = {(b["code"], b["name"]) for b in boards}
        sets_out.append(StocksBoardOverlapStockSet(code=code, boards=boards))

    pairs: list[StocksBoardOverlapPair] = []
    for a, b in combinations(sets_index.keys(), 2):
        sa, sb = sets_index[a], sets_index[b]
        common_keys = sa & sb
        common_boards = [
            {"code": k, "name": n, "type": "", "subtype": "", "source": "ths"}
            for (k, n) in sorted(common_keys)
        ]
        union = sa | sb
        jaccard = (len(common_keys) / len(union)) if union else 0.0
        pairs.append(
            StocksBoardOverlapPair(
                a=a,
                b=b,
                common_boards=common_boards,
                intersection_count=len(common_keys),
                jaccard=jaccard,
            )
        )

    result = StocksBoardOverlapResponse(sets=sets_out, pairs=pairs, errors=errors)
    if is_cache_enabled():
        cached_store(get_quote_cache, cache_key, result)
    return result


def _safe_div(num, den):
    return (num / den) if (den not in (None, 0)) else None


def _row_to_matched(s: dict) -> FilterStocksMatchedStock:
    open_v = s.get("open")
    high_v = s.get("high")
    max_gain = None
    if open_v not in (None, 0) and high_v is not None:
        try:
            max_gain = (float(high_v) - float(open_v)) / float(open_v) * 100.0
        except (TypeError, ValueError):
            max_gain = None
    amount = s.get("amount")
    total_mv = s.get("total_mv")
    return FilterStocksMatchedStock(
        code=s.get("stock_code", ""),
        name=s.get("stock_name", ""),
        price=s.get("price"),
        change_pct=s.get("change_pct"),
        max_gain_pct=max_gain,
        turnover_pct=s.get("turnover_rate"),
        amount_yi=_safe_div(amount, 1e8) if amount is not None else None,
        mcap_yi=_safe_div(total_mv, 1e8) if total_mv is not None else None,
    )


def _passes_range(value, range_):
    if range_ is None or value is None:
        return range_ is None  # if no range, no filter; if range but no value, exclude
    return not (
        (range_.min is not None and value < range_.min)
        or (range_.max is not None and value > range_.max)
    )


@router.post(
    "/agent/boards/filter-stocks",
    response_model=FilterStocksResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid request"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["agent"],
)
@endpoint_meta(
    summary="板块成分股数值过滤（量价/换手/市值/最高涨幅 服务端化）",
    markets=["csi"],
    capabilities=[],
)
@map_errors
def post_filter_stocks(payload: FilterStocksRequest) -> FilterStocksResponse:
    """Apply numeric filters to a board's constituent stocks server-side.

    All filters are optional; an empty ``filters`` object returns every
    constituent (subject to ``limit``). The route fetches via
    ``include_quote=True`` because ``turnover_rate`` / ``amount`` / quote
    fields are required for the spec's stock-picking §4 step 6 thresholds.
    """
    cache_key = make_filter_stocks_cache_key(
        payload.board_code, payload.source, payload.filters.model_dump()
    )
    hit = cached_lookup(get_quote_cache, cache_key, "agent_filter_stocks")
    if hit is not None:
        return hit

    manager = get_manager()
    try:
        stocks, _origin, _eff, _reason, _qtrunc, total_in_board = (
            stock_board_cache.get_board_stocks(
                payload.board_code,
                source=payload.source,
                include_quote=True,
                manager=manager,
            )
        )
    except (DataFetchError, ValueError) as exc:
        raise HTTPException(
            status_code=503 if isinstance(exc, DataFetchError) else 400,
            detail={"error": "board_unavailable", "message": str(exc)},
        ) from exc

    # Build candidate rows + apply filters
    matched: list[FilterStocksMatchedStock] = []
    f = payload.filters
    for s in stocks or []:
        row = _row_to_matched(s)
        if not _passes_range(row.turnover_pct, f.turnover_pct):
            continue
        if not _passes_range(row.change_pct, f.change_pct):
            continue
        if not _passes_range(row.amount_yi, f.amount_yi):
            continue
        if not _passes_range(row.mcap_yi, f.mcap_yi):
            continue
        if not _passes_range(row.max_gain_pct, f.max_gain_pct):
            continue
        matched.append(row)

    # Sort: matched_stocks ordered by max_gain_pct desc, then turnover_rate desc
    matched.sort(
        key=lambda r: (
            -(r.max_gain_pct or float("-inf")),
            -(r.turnover_pct or float("-inf")),
        )
    )

    limit_applied = payload.limit is not None
    if limit_applied:
        matched = matched[: payload.limit]

    # Best-effort board name
    board_name = (
        stock_board_cache.get_board_name_with_fallback(payload.board_code, payload.source, manager=manager)
        or payload.board_code
    )

    result = FilterStocksResponse(
        board_code=payload.board_code,
        board_name=board_name,
        filters_applied=f,
        matched_stocks=matched,
        summary={
            "total_in_board": total_in_board or len(stocks or []),
            "matched": len(matched),
            "limit_applied": limit_applied,
        },
    )
    if is_cache_enabled():
        cached_store(get_quote_cache, cache_key, result)
    return result
