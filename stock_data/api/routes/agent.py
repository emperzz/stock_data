"""Agent batch / aggregation endpoints.

All endpoints under ``/api/v1/agent/*`` live here. They fan-out across
multiple existing ``DataFetcherManager`` calls and apply server-side
join / set-arithmetic that the agent would otherwise do by hand.

Design contract (see ``docs/agent-batch-api-proposal-2026-07-27.md``):
- Per-item error isolation: one failure never aborts the response.
- All 6 endpoints accept ``?format=json|md``; default ``json``,
  ``md`` returns ``text/markdown; charset=utf-8`` (Phase 2.4).
- No LLM judgment — only numeric filter, set-op, count statistics.
- ``@endpoint_meta(capabilities=[])`` because the endpoints don't map
  to a single capability flag.

Routes added in Phase 1 (this file):
- POST /agent/boards/stock-overlap (renamed from boards/overlap per 2026-07-27 user request)
- POST /agent/stocks/board-overlap
- POST /agent/boards/filter-stocks

Routes added in Phase 2 (this file):
- GET /agent/indices/batch-profile (renamed from indices/market-snapshot per user request)
- GET /agent/market-context
- POST /agent/stocks/batch-profile (renamed from stocks/batch/profile per user request)

MD projection (Phase 2.4):
- ``_render_markdown`` helper + 6 ``render_*_as_md`` template fns at the
  bottom of this file. Single source of truth per endpoint.
"""

import logging
import re
import time
from collections.abc import Callable
from datetime import datetime
from datetime import time as dt_time
from itertools import combinations
from zoneinfo import ZoneInfo

from fastapi import HTTPException, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, PlainTextResponse
from starlette.responses import Response

from ...data_provider.base import DataFetchError
from ...data_provider.persistence import board as stock_board_cache
from ...data_provider.persistence import trade_calendar
from ..cache import (
    cached_lookup,
    cached_store,
    get_quote_cache,  # reused as generic in-memory slot for agent results
    make_boards_overlap_cache_key,
    make_filter_stocks_cache_key,
    make_indices_batch_profile_cache_key,
    make_market_context_cache_key,
    make_market_stats_cache_key,
    make_stocks_batch_profile_cache_key,
    make_stocks_board_overlap_cache_key,
)
from ..endpoint_meta import endpoint_meta
from ..schemas import (
    BoardStats,
    BoardsOverlapPair,
    BoardsOverlapRequest,
    BoardsOverlapResponse,
    BoardsOverlapSet,
    DistributionBucket,
    ErrorResponse,
    FilterStocksMatchedStock,
    FilterStocksRequest,
    FilterStocksResponse,
    IndexKlineBlock,
    IndexProfile,
    IndicesBatchProfileResponse,
    MarketContextDragonTiger,
    MarketContextDragonTigerSummary,
    MarketContextDragonTigerSummaryTop,
    MarketContextLimitPools,
    MarketContextMessages,
    MarketContextResponse,
    MarketStatsErrorEntry,
    MarketStatsResponse,
    StockBatchAspectError,
    StockBatchProfileEntry,
    StockBatchProfileRequest,
    StockBatchProfileResponse,
    StockQuote,
    StockStats,
    StocksBoardOverlapPair,
    StocksBoardOverlapRequest,
    StocksBoardOverlapResponse,
    StocksBoardOverlapStockSet,
)
from ._router import router
from .errors import map_errors
from .helpers import (
    _build_kline_data,
    _format_date,
    _index_quote_from,
    _resolve_index_name,
    get_manager,
)
from ...data_provider.utils.stats import (
    BOARD_BUCKET_BIN_WIDTH,
    STOCK_BUCKET_BIN_WIDTH,
    build_board_buckets,
    build_stock_buckets,
    compute_aggregate,
)

logger = logging.getLogger(__name__)


# Server-local timezone for market_session classification. The
# proposal anchors pre/intra/post-market to 09:15 / 15:00 Asia/Shanghai.
_CST = ZoneInfo("Asia/Shanghai")

# YYYY-MM-DD gate for ?trade_date= on /agent/market-context. Loose regex
# (no calendar validity — Feb 30 etc. is fine; the upstream will return
# empty results and the caller can detect that). What we want to catch
# is "not a date" (e.g. "yesterday") which would otherwise silently 200.
_TRADE_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# 3 core CSI indices used when ?codes is omitted on
# /agent/indices/batch-profile. Aligned with market-recap §4 step 3
# "指数全景" default set: 上证 + 深证 + 创业板.
_DEFAULT_CORE_CSI_INDICES: tuple[str, ...] = ("000001", "399001", "399006")

# K-line frequency → bar count for /agent/indices/batch-profile. Pinning
# here (not from the request) keeps the response shape stable; clients
# that want a different bar count still go through /indices/{code}/kline.
_INDICES_KLINE_DAYS: dict[str, tuple[str, int]] = {
    "5m": ("5", 2),  # 2 trading days → 2 × 48 = 96 5-min bars
    "d": ("d", 30),  # 30 daily bars
    "w": ("w", 48),  # 48 weekly bars (~1 year)
}

# Per-stock aspects supported by /agent/stocks/batch-profile. The dict
# value is (manager method name, kwargs). Adding an aspect requires a
# new entry here AND extending the StockBatchAspect Literal in schemas.py.
# `boards` is persistence-routed (NOT manager.get_stock_boards) so the
# call goes through stock_board_membership and inherits the ZZSHARE↔THS
# fallback chain + effective_source plumbing used by /stocks/{code}/boards.
# See CLAUDE.md "Persistence-Only Routing".
_STOCK_ASPECT_DISPATCH: dict[str, tuple[str, dict]] = {
    "quote": ("get_realtime_quote", {}),
    "kline": ("get_kline_data", {"frequency": "d", "days": 60, "asset": "stock"}),
    "kline_5m": ("get_kline_data", {"frequency": "5", "days": 2, "asset": "stock"}),
    "info": ("get_stock_info", {}),
}
_PERSISTENCE_ROUTED_ASPECTS = frozenset({"boards"})


def _reorder_by_code(cached, input_order: list[str], field: str):
    """Reorder ``cached.<field>`` (a list of items with .code) to match ``input_order``.

    The cache key is sorted (so two requests with the same set in
    different order share one entry), but the response contract is
    "items in input order". Codes missing from the cache (shouldn't
    happen but be defensive) are silently skipped.
    """
    by_code = {item.code: item for item in getattr(cached, field)}
    return cached.model_copy(update={field: [by_code[c] for c in input_order if c in by_code]})


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
def post_boards_stock_overlap(
    payload: BoardsOverlapRequest,
    format: str = Query(
        "json",
        pattern="^(json|md)$",
        description="Output format. json=application/json (default); md=text/markdown.",
    ),
) -> Response:
    """Compute pairwise stock-set overlap across 2-10 boards.

    Each board is fetched via ``stock_board_cache.get_board_stocks`` with
    ``source='ths', include_quote=False`` (consistent with the existing
    /boards/{code}/stocks path). Per-board failures surface in
    ``errors[]`` without aborting the response.
    """
    cache_key = make_boards_overlap_cache_key(payload.codes)
    hit = cached_lookup(get_quote_cache, cache_key, "agent_boards_stock_overlap")
    if hit is not None:
        return _render_agent("boards/stock-overlap", hit, format)

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
    cached_store(get_quote_cache, cache_key, result)
    return _render_agent("boards/stock-overlap", result, format)


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
def post_stocks_board_overlap(
    payload: StocksBoardOverlapRequest,
    format: str = Query(
        "json",
        pattern="^(json|md)$",
        description="Output format. json=application/json (default); md=text/markdown.",
    ),
) -> Response:
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
        return _render_agent("stocks/board-overlap", hit, format)

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
    cached_store(get_quote_cache, cache_key, result)
    return _render_agent("stocks/board-overlap", result, format)


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
        amount_yi=(amount / 1e8) if amount is not None else None,
        mcap_yi=(total_mv / 1e8) if total_mv is not None else None,
        # 2026-07-30: v2 union fillup flat-dumps 9 extra quote fields. Row
        # dict keys are server-canonical for the new 8 (change_amount/volume/
        # volume_ratio/pe_ratio/open/high/low/prev_close); amplitude keeps
        # its row dict key `amplitude` (THS upstream column name) and the
        # route-layer translation lands it into the `amplitude_pct` schema
        # field — same convention as boards.py::_build_board_stock_info.
        change_amount=s.get("change_amount"),
        volume=s.get("volume"),
        volume_ratio=s.get("volume_ratio"),
        pe_ratio=s.get("pe_ratio"),
        open=s.get("open"),
        high=s.get("high"),
        low=s.get("low"),
        prev_close=s.get("prev_close"),
        amplitude_pct=s.get("amplitude"),
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
def post_filter_stocks(
    payload: FilterStocksRequest,
    format: str = Query(
        "json",
        pattern="^(json|md)$",
        description="Output format. json=application/json (default); md=text/markdown.",
    ),
) -> Response:
    """Apply numeric filters to a board's constituent stocks server-side.

    All filters are optional; an empty ``filters`` object returns every
    constituent (subject to ``limit``). The route fetches via
    ``include_quote=True`` because ``turnover_rate`` / ``amount`` / quote
    fields are required for the spec's stock-picking §4 step 6 thresholds.

    2026-07-30: v2 union fillup in ``persistence.board`` fills
    ``open/high/prev_close/volume`` on THS top-50 rows from the /stocks
    quote cache, so ``max_gain_pct`` now applies to ALL rows (was
    suffix-only before v2 — top-50 rows were silently excluded by the
    None→exclude contract in ``_passes_range``). THS-only fields like
    ``total_mv`` remain THS-row-only (suffix rows still report
    ``mcap_yi=None`` and are excluded by any ``mcap_yi`` filter).
    """
    cache_key = make_filter_stocks_cache_key(
        payload.board_code,
        payload.source,
        payload.filters.model_dump(),
        payload.limit,
    )
    hit = cached_lookup(get_quote_cache, cache_key, "agent_filter_stocks")
    if hit is not None:
        return _render_agent("boards/filter-stocks", hit, format)

    manager = get_manager()
    try:
        stocks, _origin, _eff, _reason, _qtrunc, total_in_board = (
            stock_board_cache.get_board_stocks(
                payload.board_code,
                source=payload.source,
                include_quote=True,
                manager=manager,
                top_n=payload.limit or 50,
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
        stock_board_cache.get_board_name_with_fallback(
            payload.board_code, payload.source, manager=manager
        )
        or payload.board_code
    )

    result = FilterStocksResponse(
        code=payload.board_code,
        board_name=board_name,
        filters_applied=f,
        matched_stocks=matched,
        summary={
            "total_in_board": total_in_board or len(stocks or []),
            "matched": len(matched),
            "limit_applied": limit_applied,
        },
    )
    cached_store(get_quote_cache, cache_key, result)
    return _render_agent("boards/filter-stocks", result, format)


# ============================================================================
# Phase 2 endpoints (3.2.1 / 3.2.2 / 3.2.3 of agent-batch-api-proposal)
# ============================================================================


def _classify_market_session(is_trade_day: bool) -> str:
    """Map server-local CST time to a session label.

    Anchors from proposal §3.2.3: 09:15 / 15:00 Asia/Shanghai. Returns
    ``"closed"`` for non-trade-days. Uses ``datetime.now(CST)``; the
    proposal explicitly notes server runs in CST.
    """
    if not is_trade_day:
        return "closed"
    now = datetime.now(_CST).time()
    if now < dt_time(9, 15):
        return "pre-market"
    if now < dt_time(15, 0):
        return "intraday"
    return "post-market"


def _batch_summary(requested: int, ok: int, started: float) -> dict:
    """Build the standard {requested, ok, failed, elapsed_ms} summary block."""
    return {
        "requested": requested,
        "ok": ok,
        "failed": requested - ok,
        "elapsed_ms": int((time.monotonic() - started) * 1000),
    }


def _summarize_dragon_tiger(stocks: list[dict]) -> MarketContextDragonTigerSummary:
    """Compute the dragon-tiger summary block.

    - total_net_buy_wan = sum across ALL rows (signed: positive = 净买入, negative = 净卖出)
    - top_by_net_buy: top 10 by net_buy_wan DESC (positive-first)
    - top_by_net_sell: top 10 by net_buy_wan ASC, but only rows with
      net_buy_wan < 0 (a positive row is by definition NOT a sell-side
      candidate; surfacing it as "top sell" would be misleading on
      all-positive days).
    """
    rows = [
        MarketContextDragonTigerSummaryTop(
            code=s.get("code", ""),
            name=s.get("name", ""),
            net_buy_wan=float(s.get("net_buy_wan") or 0),
        )
        for s in (stocks or [])
    ]
    total = sum(r.net_buy_wan for r in rows)
    top_buy = sorted(rows, key=lambda r: -r.net_buy_wan)[:10]
    negative_only = [r for r in rows if r.net_buy_wan < 0]
    top_sell = sorted(negative_only, key=lambda r: r.net_buy_wan)[:10]
    return MarketContextDragonTigerSummary(
        total_net_buy_wan=total,
        top_by_net_buy=top_buy,
        top_by_net_sell=top_sell,
    )


@router.get(
    "/agent/indices/batch-profile",
    response_model=IndicesBatchProfileResponse,
    responses={
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["agent"],
)
@endpoint_meta(
    summary="指数批量画像（实时报价 + 5m/d/w 三频率 K 线，单次 fan-out）",
    markets=["csi"],
    capabilities=[],
)
@map_errors
def get_indices_batch_profile(
    codes: str | None = Query(
        default=None,
        description=(
            "Comma-separated index codes. Empty = 3 core CSI indices "
            "(上证/深证/创业板). Each code is fanned out to "
            "1 quote + 3 K-line frequencies; per-frequency failure is "
            "isolated into entry.errors[frequency]."
        ),
    ),
    format: str = Query(
        "json",
        pattern="^(json|md)$",
        description="Output format. json=application/json (default); md=text/markdown.",
    ),
) -> Response:
    """Per-index fan-out: realtime quote + 5m/d/w K-line.

    Renamed from proposal §3.2.1 ``indices/market-snapshot`` per
    2026-07-28 user request; the route now matches the stocks variant's
    ``/batch-profile`` naming.
    """
    code_list = [
        c.strip() for c in (codes.split(",") if codes else _DEFAULT_CORE_CSI_INDICES) if c.strip()
    ] or list(_DEFAULT_CORE_CSI_INDICES)

    cache_key = make_indices_batch_profile_cache_key(code_list)
    hit = cached_lookup(get_quote_cache, cache_key, "agent_indices_batch_profile")
    if hit is not None:
        # Cache key is sorted; reorder cached list to the caller's order
        # so the "indices" list mirrors the input `codes` (response contract).
        return _render_agent(
            "indices/batch-profile", _reorder_by_code(hit, code_list, "indices"), format
        )

    started = time.monotonic()
    manager = get_manager()
    profiles: list[IndexProfile] = []
    n_ok = 0

    for code in code_list:
        errors: dict[str, str | None] = {}
        klines: dict[str, IndexKlineBlock] = {}
        quote_dict: dict | None = None
        entry_ok = True

        # 1) realtime quote. get_index_realtime_quote returns None when
        # no fetcher could serve (vs DataFetchError when ALL fetchers
        # raised). We treat None as a soft failure (errors["quote"] set,
        # entry marked failed) — returning a "successful but empty" quote
        # would mask a real upstream outage.
        try:
            q = manager.get_index_realtime_quote(code)
        except (DataFetchError, ValueError) as exc:
            logger.warning(f"[agent/indices/batch-profile] quote {code} failed: {exc}")
            errors["quote"] = str(exc)
            entry_ok = False
            q = None
        if q is None:
            errors.setdefault("quote", "no fetcher could serve realtime quote")
            entry_ok = False
        else:
            errors["quote"] = None
            quote_dict = _index_quote_from(q, code).model_dump()

        # 2) per-frequency K-line. 5m/d/w ordered most-recent-first so
        # the user reads the small frame first.
        # The dict value is (manager-internal freq, days); the public
        # label (`user_freq`) keeps "5m" so the response contract is
        # stable while the manager gets the canonical "5".
        for user_freq, (mgr_freq, days) in _INDICES_KLINE_DAYS.items():
            # Per-frequency block. The broad except here is on purpose:
            # the spec requires per-frequency isolation, so a RuntimeError
            # from upstream serialization (e.g. _build_kline_data choking
            # on a malformed bar) must NOT abort the whole request — it
            # should surface as an error on that frequency and let the
            # other frequencies continue.
            try:
                df, _src = manager.get_kline_data(
                    code,
                    days=days,
                    frequency=mgr_freq,
                    asset="index",
                )
                records = df.to_dict("records") if df is not None else []
                bars = [_build_kline_data(r, _format_date) for r in records]
            except Exception as exc:
                logger.warning(
                    f"[agent/indices/batch-profile] kline {code} {mgr_freq} failed: {exc}",
                    exc_info=True,
                )
                entry_ok = False
                klines[user_freq] = IndexKlineBlock(data=[], error=f"{type(exc).__name__}: {exc}")
                continue
            klines[user_freq] = IndexKlineBlock(data=bars, error=None)

        if entry_ok:
            n_ok += 1
        profiles.append(
            IndexProfile(
                code=code,
                name=_resolve_index_name(code),
                quote=quote_dict,
                klines=klines,
                errors=errors,
            )
        )

    result = IndicesBatchProfileResponse(
        indices=profiles,
        summary=_batch_summary(len(code_list), n_ok, started),
    )
    cached_store(get_quote_cache, cache_key, result)
    return _render_agent("indices/batch-profile", result, format)


@router.get(
    "/agent/market-context",
    response_model=MarketContextResponse,
    responses={
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["agent"],
)
@endpoint_meta(
    summary="市场全景（早报 + 复盘 + 快讯 + 涨跌停 + 龙虎榜；含时段判断）",
    markets=["csi"],
    capabilities=[],
)
@map_errors
def get_market_context(
    flash_limit: int = Query(
        default=20,
        ge=1,
        le=200,
        description="快讯条数上限 1-200;默认 20;与上游 fetch_flash_news 的 pageSize 硬 cap 对齐",
    ),
    trade_date: str | None = Query(
        default=None,
        description=(
            "交易日 YYYY-MM-DD;不传默认 = get_latest_trade_date_on_or_before(today). "
            "影响早报/复盘/龙虎榜的查询日期;涨跌停与快讯不受影响(涨跌停按 today,快讯按实时)。"
        ),
    ),
    format: str = Query(
        "json",
        pattern="^(json|md)$",
        description="Output format. json=application/json (default); md=text/markdown.",
    ),
) -> Response:
    """Aggregate morning-briefing + market-recap + flash + zt + dt + dragon-tiger.

    Per spec §3.2.3:
    - zt/dt forced to null in pre-market (池子可能未成形);
    - morning/recap return null on per-source failure (NOT 503);
    - flash + dragon-tiger always attempt;
    - dragon-tiger summary is server-computed.
    """
    # trade_date format gate. The manager chain accepts arbitrary strings
    # and may return 200 with empty results; better to 400 here with a
    # clear "not a date" message than to silently produce an empty snapshot.
    if trade_date is not None and not _TRADE_DATE_RE.match(trade_date):
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_trade_date",
                "message": (
                    f"trade_date must be YYYY-MM-DD; got {trade_date!r}. "
                    "Empty = server-defaulted to most recent trade date on/before today."
                ),
            },
        )
    today_str = datetime.now(_CST).date().isoformat()
    is_trade_day = trade_calendar.is_trade_date(today_str)
    if trade_date:
        target_date = trade_date
    else:
        # Fall back to the most recent trade date on/before today.
        target_date = trade_calendar.get_latest_trade_date_on_or_before(today_str) or today_str

    session = _classify_market_session(is_trade_day)
    # Cache key MUST include the session — pre/intra/post/closed produce
    # materially different responses (pre-market forces zt/dt to null;
    # post-market returns full pool data). Without this, a 09:00 pre-market
    # cache hit would mask a 16:00 post-market refresh.
    cache_key = make_market_context_cache_key(flash_limit, target_date, session)
    hit = cached_lookup(get_quote_cache, cache_key, "agent_market_context")
    if hit is not None:
        return _render_agent("market-context", hit, format)

    started = time.monotonic()
    manager = get_manager()
    # Pre-market intentionally skips zt+dt (per spec §3.2.3 — 涨跌停池
    # may not be formed yet); don't even attempt, so requested drops.
    # Spec requires per-block isolation: a runtime error from upstream
    # serialization (e.g. CLS HTML parser crash) must NOT abort the
    # whole response. Each call below is wrapped in a per-block try.
    attempts: list[tuple[str, Callable, object]] = [
        ("morning_briefing", lambda: manager.get_morning_briefing(target_date)[0], None),
        ("market_recap", lambda: manager.get_market_recap(target_date)[0], None),
        # flash default is [] (not None) — empty list counts as a successful
        # attempt (the upstream may legitimately have no flash in quiet periods).
        ("flash_news", lambda: manager.get_flash_news(limit=flash_limit)[0], []),
    ]
    if session != "pre-market":
        attempts.extend(
            [
                (
                    "zt_pool",
                    lambda: manager.get_zt_pool(pool_type="zt", date=target_date)[0],
                    None,
                ),
                (
                    "dt_pool",
                    lambda: manager.get_zt_pool(pool_type="dt", date=target_date)[0],
                    None,
                ),
            ]
        )
    attempts.append(
        (
            "daily_dragon_tiger",
            lambda: manager.get_daily_dragon_tiger(target_date, min_net_buy=None)[0],
            None,
        ),
    )

    results: dict[str, object] = {}
    n_ok = 0
    for name, fn, default in attempts:
        try:
            results[name] = fn()
            n_ok += 1
        except Exception as exc:
            logger.warning(f"[agent/market-context] {name} failed: {exc}", exc_info=True)
            results[name] = default

    morning = results["morning_briefing"]
    recap = results["market_recap"]
    flash = results["flash_news"]
    zt = results.get("zt_pool")
    dt = results.get("dt_pool")
    data = results["daily_dragon_tiger"]
    if isinstance(data, dict):
        stocks = data.get("stocks", [])
        dtiger: MarketContextDragonTiger | None = MarketContextDragonTiger(
            stocks=stocks,
            summary=_summarize_dragon_tiger(stocks),
        )
    else:
        # daily_dragon_tiger failed; results[] holds the default (None).
        dtiger = None

    result = MarketContextResponse(
        trade_date=target_date,
        is_trade_day=is_trade_day,
        market_session=session,  # type: ignore[arg-type]
        messages=MarketContextMessages(
            morning_briefing=morning,
            market_recap=recap,
            flash_news=flash,
        ),
        limit_pools=MarketContextLimitPools(zt=zt, dt=dt),
        dragon_tiger=dtiger,
        summary=_batch_summary(len(attempts), n_ok, started),
    )
    cached_store(get_quote_cache, cache_key, result)
    return _render_agent("market-context", result, format)


def _serialize_stock_aspect_value(aspect: str, raw: object) -> object:
    """Coerce a manager-returned value into a JSON-serializable shape.

    UnifiedRealtimeQuote is a dataclass; K-line is a DataFrame (turn
    into records); info is already a dict; boards is already a dict list.
    On any failure, return the raw object (Pydantic will surface the
    error in the test, but production code should not raise here).
    """
    if raw is None:
        return None
    if aspect == "quote":
        # UnifiedRealtimeQuote dataclass — delegate to StockQuote.from_unified_quote
        # so the batch-profile quote shape is bit-for-bit identical to
        # /stocks/{code}/quote. Unit conversion (元→亿元) and field-name
        # mapping live in one place (schemas.py).
        return StockQuote.from_unified_quote(raw).model_dump()
    if aspect in ("kline", "kline_5m"):
        # (df, source) tuple
        df, source = raw  # type: ignore[misc]
        records = df.to_dict("records") if df is not None else []
        return {
            "source": source,
            "data": [_build_kline_data(r, _format_date).model_dump() for r in records],
        }
    if aspect == "info":
        # (info_dict, source) tuple
        info, source = raw  # type: ignore[misc]
        return {"source": source, "data": info}
    if aspect == "boards":
        # (boards_list, source) tuple — boards_list may be None per manager contract
        boards, source = raw  # type: ignore[misc]
        return {"source": source, "data": boards or []}
    return raw  # pragma: no cover — exhaustive above


@router.post(
    "/agent/stocks/batch-profile",
    response_model=StockBatchProfileResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid request (codes out of range)"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["agent"],
)
@endpoint_meta(
    summary="股票批量画像（quote + kline + kline_5m + info + boards，per-aspect 错误隔离）",
    markets=["csi"],
    capabilities=[],
)
@map_errors
def post_stocks_batch_profile(
    payload: StockBatchProfileRequest,
    format: str = Query(
        "json",
        pattern="^(json|md)$",
        description="Output format. json=application/json (default); md=text/markdown.",
    ),
) -> Response:
    """Per-code fan-out across the requested aspects.

    Renamed from proposal §3.2.2 ``stocks/batch/profile`` per 2026-07-28
    user request. Codes are 1-5 (hard cap matches the stock-picking
    funnel); per-aspect failures live in ``results[i].errors[]``; the
    whole entry is only marked ``ok=False`` when the code itself is
    unrecoverable (e.g. all 5 aspects raised).
    """
    cache_key = make_stocks_batch_profile_cache_key(payload.codes, payload.aspects)
    hit = cached_lookup(get_quote_cache, cache_key, "agent_stocks_batch_profile")
    if hit is not None:
        # Cache key collapses (sorted codes, sorted deduped aspects) so
        # the same (set, set) from any order shares one entry. On hit
        # we reorder the cached list back to the caller's input order
        # (response contract: results mirror input codes).
        return _render_agent(
            "stocks/batch-profile",
            _reorder_by_code(hit, payload.codes, "results"),
            format,
        )

    started = time.monotonic()
    manager = get_manager()
    results: list[StockBatchProfileEntry] = []
    n_ok = 0

    for code in payload.codes:
        data: dict = {}
        errors: list[StockBatchAspectError] = []
        any_aspect_ok = False

        for aspect in payload.aspects:
            try:
                if aspect in _PERSISTENCE_ROUTED_ASPECTS:
                    entries, _cold, _origin = stock_board_cache.get_stock_memberships(
                        stock_code=code,
                        sources=["ths"],
                        manager=manager,
                    )
                    # Match the (list, source) tuple shape
                    # _serialize_stock_aspect_value expects for the boards aspect.
                    raw = (entries, "persistence")
                else:
                    method_name, kwargs = _STOCK_ASPECT_DISPATCH[aspect]
                    raw = getattr(manager, method_name)(code, **kwargs)
            except Exception as exc:
                logger.warning(
                    f"[agent/stocks/batch-profile] {code} {aspect} failed: {exc}",
                    exc_info=True,
                )
                errors.append(
                    StockBatchAspectError(
                        aspect=aspect,
                        error=type(exc).__name__,
                        message=str(exc),
                    )
                )
                continue
            try:
                data[aspect] = _serialize_stock_aspect_value(aspect, raw)
                any_aspect_ok = True
            except Exception as exc:
                errors.append(
                    StockBatchAspectError(
                        aspect=aspect,
                        error="SerializationError",
                        message=str(exc),
                    )
                )

        entry_ok = any_aspect_ok
        if entry_ok:
            n_ok += 1
        results.append(
            StockBatchProfileEntry(
                code=code,
                ok=entry_ok,
                data=data,
                errors=errors,
            )
        )

    resp = StockBatchProfileResponse(
        results=results,
        summary=_batch_summary(len(payload.codes), n_ok, started),
    )
    cached_store(get_quote_cache, cache_key, resp)
    return _render_agent("stocks/batch-profile", resp, format)


def _stats_block_from_aggregate(
    agg: "AggregateStats", *, kind: str, source: str = ""
) -> "StockStats | BoardStats":
    """Convert an AggregateStats dataclass into the StockStats / BoardStats
    Pydantic model that matches `kind`.

    Dispatches on a literal discriminator (``"stocks"`` / ``"boards"``) rather
    than a numeric constant — easier to read at the call site and not fragile
    to future bin-width changes.

    Args:
        agg: the AggregateStats dataclass from compute_aggregate().
        kind: ``"stocks"`` → StockStats (no source field);
              ``"boards"`` → BoardStats (carries source).
        source: the source label forwarded to BoardStats.source
                (ignored when kind == "stocks").
    """
    common = {
        "sample_size": agg.sample_size,
        "mean_pct": agg.mean_pct,
        "median_pct": agg.median_pct,
        "max_pct": agg.max_pct,
        "min_pct": agg.min_pct,
        "up_count": agg.up_count,
        "down_count": agg.down_count,
        "flat_count": agg.flat_count,
        "bin_width": agg.bin_width,
        "buckets": [
            DistributionBucket(
                label=b.label,
                lower=b.lower,
                upper=b.upper,
                count=b.count,
            )
            for b in agg.buckets
        ],
    }
    if kind == "boards":
        return BoardStats(**common, source=source)
    return StockStats(**common)


@router.get(
    "/agent/market-stats",
    response_model=MarketStatsResponse,
    responses={500: {"model": ErrorResponse, "description": "Server error"}},
    tags=["agent"],
)
@endpoint_meta(
    summary="市场全量统计（个股+板块涨幅分布 + 桶形数据）",
    markets=["csi"],
    capabilities=[],                          # agent aggregation, no single capability
)
@map_errors
def get_market_stats(
    include_boards: bool = Query(
        default=True,
        description="是否包含板块块;false 时只返回个股块 (无板块上游调用)",
    ),
    format: str = Query(
        "json",
        pattern="^(json|md)$",
        description="Output format. json=application/json (default); md=text/markdown.",
    ),
) -> Response:
    """Per-block fan-out with per-block error isolation.

    stocks block:  manager.get_realtime_quotes('csi') (single upstream call)
    boards block:  stock_board_cache.get_board_list(board_type=None, source='ths', include_quote=True, manager=manager)
                   (single upstream call, persistence-routed)

    A single upstream failure sets that block to ``null`` and surfaces
    the exception in ``errors[]``; the other block continues normally.
    Cached 60s via ``get_quote_cache`` (one entry shared between json/md).
    """
    cache_key = make_market_stats_cache_key(include_boards)
    hit = cached_lookup(get_quote_cache, cache_key, "agent_market_stats")
    if hit is not None:
        return _render_agent("market-stats", hit, format)

    started = time.monotonic()
    manager = get_manager()
    errors: list[MarketStatsErrorEntry] = []
    stocks_stats: StockStats | None = None
    boards_stats: BoardStats | None = None
    requested = 1 + (1 if include_boards else 0)
    ok = 0

    # --- stocks block (always attempted) ---
    try:
        quotes, _src = manager.get_realtime_quotes("csi")
        values = [
            q.change_pct for q in (quotes or [])
            if getattr(q, "change_pct", None) is not None
        ]
        agg = compute_aggregate(
            values,
            bin_width=STOCK_BUCKET_BIN_WIDTH,
            buckets_template=build_stock_buckets(),
        )
        stocks_stats = _stats_block_from_aggregate(agg, kind="stocks")
        ok += 1
    except Exception as exc:
        logger.warning(
            f"[agent/market-stats] stocks failed: {exc}", exc_info=True
        )
        errors.append(
            MarketStatsErrorEntry(
                block="stocks",
                error=type(exc).__name__,
                message=str(exc),
            )
        )

    # --- boards block (skipped when include_boards=false) ---
    if include_boards:
        try:
            boards, src = stock_board_cache.get_board_list(
                board_type=None,
                source="ths",
                include_quote=True,
                manager=manager,
            )
            values = [
                b.get("change_pct") for b in (boards or [])
                if isinstance(b.get("change_pct"), (int, float))
                and not isinstance(b.get("change_pct"), bool)
            ]
            agg = compute_aggregate(
                values,
                bin_width=BOARD_BUCKET_BIN_WIDTH,
                buckets_template=build_board_buckets(),
            )
            boards_stats = _stats_block_from_aggregate(
                agg, kind="boards", source=src or "ths"
            )
            ok += 1
        except Exception as exc:
            logger.warning(
                f"[agent/market-stats] boards failed: {exc}", exc_info=True
            )
            errors.append(
                MarketStatsErrorEntry(
                    block="boards",
                    error=type(exc).__name__,
                    message=str(exc),
                )
            )

    result = MarketStatsResponse(
        stocks=stocks_stats,
        boards=boards_stats,
        errors=errors,
        summary=_batch_summary(requested, ok, started),
    )
    cached_store(get_quote_cache, cache_key, result)
    return _render_agent("market-stats", result, format)


# ============================================================================
# MD projection layer (Phase 2.4 — see agent-batch-api-proposal §2.2 / §8.2.4)
# ============================================================================


def _md_num(v, places: int = 2) -> str:
    """Format a number for MD table cells. None → '—'."""
    if v is None:
        return "—"
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, float):
        return f"{v:,.{places}f}"
    if isinstance(v, int):
        return f"{v:,}"
    return str(v)


def _md_pct(v) -> str:
    """Format a percentage value. None → '—'. Always shows sign."""
    if v is None:
        return "—"
    return f"{v:+.2f}%"


def _md_kline_rows(bars) -> list[str]:
    """Render KLineData bars as MD table rows (no header).

    Accepts either KLineData instances (used by /indices/batch-profile)
    or plain dicts (used by /stocks/batch-profile, where the aspect
    payload is already JSON-serialized via model_dump).
    """
    if not bars:
        return ["（无数据）"]

    def _get(bar, key, default=None):
        if isinstance(bar, dict):
            return bar.get(key, default)
        return getattr(bar, key, default)

    out = [
        "| 日期 | 开 | 高 | 低 | 收 | 量(股) | 额 | 涨跌幅 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for b in bars:
        out.append(
            f"| {_get(b, 'date', '')} | {_md_num(_get(b, 'open'), 3)} | "
            f"{_md_num(_get(b, 'high'), 3)} | {_md_num(_get(b, 'low'), 3)} | "
            f"{_md_num(_get(b, 'close'), 3)} | {_md_num(_get(b, 'volume'), 0)} | "
            f"{_md_num(_get(b, 'amount'), 0)} | {_md_pct(_get(b, 'change_pct'))} |"
        )
    return out


def _md_errors(errors: list[dict], *, key: str = "code", header: str = "代码") -> list[str]:
    """Render the per-code errors[] block (or "(无)")."""
    if not errors:
        return ["（无）"]
    out = [f"| {header} | 错误类型 | 消息 |", "|---|---|---|"]
    for e in errors:
        out.append(f"| {e.get(key, '?')} | {e.get('error', '?')} | {e.get('message', '')} |")
    return out


def _render_markdown(payload, template_fn: Callable) -> Response:
    """Render a Pydantic payload to markdown text.

    On template failure: returns ``JSONResponse`` with the original payload
    + ``X-MD-Render-Error`` header (per proposal §9). Falling back means a
    template bug never blocks the endpoint — the user always gets data, just
    not in their preferred format.

    Returns ``PlainTextResponse(media_type='text/markdown; charset=utf-8')``
    on success. The route handlers always pre-compute / cache the Pydantic
    model and call this only when ``?format=md`` is set, so:
    - the cache stays format-agnostic (one entry serves both JSON and MD)
    - MD failure does NOT bust the cache
    """
    try:
        md = template_fn(payload)
    except Exception as exc:
        logger.warning(
            f"[agent MD] {template_fn.__name__} failed: {exc}",
            exc_info=True,
        )
        return JSONResponse(
            content=jsonable_encoder(payload),
            headers={"X-MD-Render-Error": f"{type(exc).__name__}: {str(exc)[:200]}"},
        )
    return PlainTextResponse(content=md, media_type="text/markdown; charset=utf-8")


# ── per-endpoint MD templates ──────────────────────────────────────────────


def render_boards_overlap_as_md(p: BoardsOverlapResponse) -> str:
    out = ["# 板块成分股两两重叠度", ""]
    out.append("## 板块成分股数")
    out.append("| 板块 | 成分股数 | 来源 |")
    out.append("|---|---|---|")
    for s in p.sets:
        out.append(f"| {s.code} | {s.count} | {s.source} |")
    out.append("")
    out.append("## 板块对重叠度")
    if p.pairs:
        out.append("| A | B | 交集数 | Jaccard | 交集代码 |")
        out.append("|---|---|---|---|---|")
        for pair in p.pairs:
            codes = ", ".join(pair.intersection) if pair.intersection else "—"
            out.append(
                f"| {pair.a} | {pair.b} | {pair.intersection_count} | "
                f"{_md_num(pair.jaccard, 4)} | {codes} |"
            )
    else:
        out.append("（无）")
    out.append("")
    out.append("## 失败列表")
    out.extend(_md_errors(p.errors))
    out.append("")
    s = p.summary if hasattr(p, "summary") and p.summary else {}
    if s:
        out.append(
            f"## 汇总 — requested {s.get('requested', '?')}, "
            f"ok {s.get('ok', '?')}, failed {s.get('failed', '?')}, "
            f"elapsed {s.get('elapsed_ms', '?')}ms"
        )
    return "\n".join(out)


def render_stocks_board_overlap_as_md(p: StocksBoardOverlapResponse) -> str:
    out = ["# 股票所属板块两两重叠度", ""]
    out.append("## 股票所属板块")
    for s in p.sets:
        out.append(f"### {s.code}")
        if s.boards:
            for b in s.boards:
                t = b.get("type") or "-"
                sub = b.get("subtype") or "-"
                out.append(
                    f"- {b.get('code', '?')} ({t}/{sub}) {b.get('name', '')}"
                    f" — source: {b.get('source', '?')}"
                )
        else:
            out.append("（无所属板块）")
        out.append("")
    out.append("## 股票对重叠度")
    if p.pairs:
        out.append("| A | B | 共同板块数 | Jaccard | 共同板块 |")
        out.append("|---|---|---|---|---|")
        for pair in p.pairs:
            common_repr = (
                "; ".join(f"{b.get('code', '?')}({b.get('name', '')})" for b in pair.common_boards)
                if pair.common_boards
                else "—"
            )
            out.append(
                f"| {pair.a} | {pair.b} | {pair.intersection_count} | "
                f"{_md_num(pair.jaccard, 4)} | {common_repr} |"
            )
    else:
        out.append("（无）")
    out.append("")
    out.append("## 失败列表")
    out.extend(_md_errors(p.errors))
    out.append("")
    return "\n".join(out)


def render_filter_stocks_as_md(p: FilterStocksResponse) -> str:
    out = [f"# 板块成分股过滤 — {p.code} {p.board_name or ''}", ""]
    fa = p.filters_applied
    filter_lines: list[str] = []
    for fname, label in [
        ("turnover_pct", "换手率(%)"),
        ("change_pct", "涨跌幅(%)"),
        ("amount_yi", "成交额(亿)"),
        ("mcap_yi", "市值(亿)"),
        ("max_gain_pct", "最高涨幅(%)"),
    ]:
        r = getattr(fa, fname, None)
        if r is None:
            continue
        lo = _md_num(r.min) if r.min is not None else "-∞"
        hi = _md_num(r.max) if r.max is not None else "+∞"
        filter_lines.append(f"- {label}: {lo} ~ {hi}")
    out.append("**过滤条件**:" + (" " + " / ".join(filter_lines) if filter_lines else " 无"))
    out.append("")
    s = p.summary or {}
    out.append(
        f"**汇总**: 总成分股 {s.get('total_in_board', 0)}, 匹配 {s.get('matched', 0)}"
        + (" (已截断)" if s.get("limit_applied") else "")
    )
    out.append("")
    if p.matched_stocks:
        out.append("## 匹配股票")
        out.append(
            "| 代码 | 名称 | 现价 | 涨跌额 | 涨跌幅 | 最高涨幅 | 换手率(%) | "
            "成交额(亿) | 市值(亿) | 量(股) | 量比 | PE | 振幅(%) | "
            "开 | 高 | 低 | 昨收 |"
        )
        out.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
        for r in p.matched_stocks:
            out.append(
                f"| {r.code} | {r.name} | {_md_num(r.price, 3)} | "
                f"{_md_num(r.change_amount, 3)} | {_md_pct(r.change_pct)} | "
                f"{_md_pct(r.max_gain_pct)} | {_md_num(r.turnover_pct)} | "
                f"{_md_num(r.amount_yi)} | {_md_num(r.mcap_yi)} | "
                f"{_md_num(r.volume, 0)} | {_md_num(r.volume_ratio, 2)} | "
                f"{_md_num(r.pe_ratio, 2)} | {_md_num(r.amplitude_pct, 2)} | "
                f"{_md_num(r.open, 3)} | {_md_num(r.high, 3)} | "
                f"{_md_num(r.low, 3)} | {_md_num(r.prev_close, 3)} |"
            )
    else:
        out.append("（无匹配股票）")
    out.append("")
    return "\n".join(out)


def render_indices_batch_profile_as_md(p: IndicesBatchProfileResponse) -> str:
    out = ["# 指数批量画像", ""]
    for idx in p.indices:
        ok_marker = "✓" if idx.quote else "✗"
        out.append(f"## {idx.code} {idx.name} {ok_marker}")
        if idx.quote:
            q = idx.quote
            out.append("### 实时行情")
            out.append("| 字段 | 值 |")
            out.append("|---|---|")
            for k, v in q.items():
                if isinstance(v, float):
                    out.append(f"| {k} | {_md_num(v, 4)} |")
                else:
                    out.append(f"| {k} | {v if v is not None else '—'} |")
        else:
            err = (idx.errors or {}).get("quote") or "no quote"
            out.append(f"### 实时行情 — 失败: {err}")
        out.append("")
        for freq in ("5m", "d", "w"):
            block = idx.klines.get(freq)
            if not block:
                out.append(f"### {freq} K线 — 无数据")
                out.append("")
                continue
            label = {"5m": "5 分钟", "d": "日", "w": "周"}.get(freq, freq)
            if block.error:
                out.append(f"### {label} K线 — 失败: {block.error}")
            else:
                out.append(f"### {label} K线 ({len(block.data)} 根)")
                out.extend(_md_kline_rows(block.data))
            out.append("")
    s = p.summary or {}
    out.append(
        f"## 汇总 — requested {s.get('requested', '?')}, "
        f"ok {s.get('ok', '?')}, failed {s.get('failed', '?')}, "
        f"elapsed {s.get('elapsed_ms', '?')}ms"
    )
    return "\n".join(out)


def _render_dict_block(out: list[str], title: str, d: dict) -> None:
    """Render every key/value of a flat dict (no field is dropped)."""
    out.append(f"### {title}")
    out.append("| 字段 | 值 |")
    out.append("|---|---|")
    for k, v in d.items():
        if isinstance(v, float):
            out.append(f"| {k} | {_md_num(v, 4)} |")
        elif isinstance(v, (list, dict)):
            out.append(f"| {k} | `{v!r}` |")
        else:
            out.append(f"| {k} | {v if v is not None else '—'} |")
    out.append("")


def render_market_context_as_md(p: MarketContextResponse) -> str:
    out = [
        f"# 市场全景 — {p.trade_date} {p.market_session}",
        f"**is_trade_day**: {p.is_trade_day}",
        "",
    ]
    msg = p.messages
    out.append("## 消息面")
    if msg.morning_briefing:
        _render_dict_block(out, "早报", msg.morning_briefing)
    else:
        out.append("### 早报 — （无）")
        out.append("")
    if msg.market_recap:
        _render_dict_block(out, "复盘", msg.market_recap)
    else:
        out.append("### 复盘 — （无）")
        out.append("")
    out.append(f"### 快讯 ({len(msg.flash_news)} 条)")
    if msg.flash_news:
        for f in msg.flash_news:
            title = f.get("title", "—")
            t = f.get("publish_time", "")
            src = f.get("source", "")
            url = f.get("url", "")
            content = f.get("content", "")
            line = f"- [{t}] {title}"
            if src:
                line += f" _(source: {src})_"
            if url:
                line += f" [link]({url})"
            out.append(line)
            if content:
                out.append(f"  {content}")
    else:
        out.append("（无）")
    out.append("")
    out.append("## 涨跌停")
    pools = p.limit_pools
    if pools.zt is None:
        out.append("**涨停池**: null")
    elif not pools.zt:
        out.append("**涨停池**: （空）")
    else:
        out.append(f"**涨停池**: {len(pools.zt)} 只")
        out.append("")
        out.append("| 代码 | 名称 | 涨跌幅 | 涨停时间 | 连板数 | 所属行业 |")
        out.append("|---|---|---|---|---|---|")
        for s in pools.zt:
            code = s.get("code", "")
            name = s.get("name", "")
            pct = s.get("pct_chg") or s.get("change_pct")
            t = s.get("limit_time") or s.get("first_limit_time") or ""
            lb = s.get("limit_count") or s.get("continuous_limit_count")
            industry = s.get("industry", "")
            out.append(
                f"| {code} | {name} | {_md_pct(pct)} | {t} | "
                f"{lb if lb is not None else '—'} | {industry} |"
            )
    out.append("")
    if pools.dt is None:
        out.append("**跌停池**: null")
    elif not pools.dt:
        out.append("**跌停池**: （空）")
    else:
        out.append(f"**跌停池**: {len(pools.dt)} 只")
        out.append("")
        out.append("| 代码 | 名称 | 涨跌幅 | 跌停时间 | 所属行业 |")
        out.append("|---|---|---|---|---|")
        for s in pools.dt:
            code = s.get("code", "")
            name = s.get("name", "")
            pct = s.get("pct_chg") or s.get("change_pct")
            t = s.get("limit_time") or s.get("first_limit_time") or ""
            industry = s.get("industry", "")
            out.append(f"| {code} | {name} | {_md_pct(pct)} | {t} | {industry} |")
    out.append("")
    out.append("## 龙虎榜")
    if p.dragon_tiger and p.dragon_tiger.stocks:
        s = p.dragon_tiger.summary
        if s:
            out.append(f"**全市场净买入合计**: {s.total_net_buy_wan:,.0f} 万元")
            out.append("")
            out.append("### 净买入 Top 10")
            out.append("| 代码 | 名称 | 净买入(万元) |")
            out.append("|---|---|---|")
            for r in s.top_by_net_buy:
                out.append(f"| {r.code} | {r.name} | {_md_num(r.net_buy_wan, 0)} |")
            if s.top_by_net_sell:
                out.append("")
                out.append("### 净卖出 Top 10")
                out.append("| 代码 | 名称 | 净买入(万元) |")
                out.append("|---|---|---|")
                for r in s.top_by_net_sell:
                    out.append(f"| {r.code} | {r.name} | {_md_num(r.net_buy_wan, 0)} |")
        out.append("")
        out.append(f"### 龙虎榜全表 ({len(p.dragon_tiger.stocks)} 只)")
        out.append(
            "| 代码 | 名称 | 净买入(万元) | 买入金额(万元) | 卖出金额(万元) | "
            "成交额(万元) | 涨跌幅 | 解读后涨幅 |"
        )
        out.append("|---|---|---|---|---|---|---|---|")
        for r in p.dragon_tiger.stocks:
            code = r.get("code", "")
            name = r.get("name", "")
            nb = r.get("net_buy_wan")
            bamt = r.get("buy_wan") or r.get("buy_amount_wan")
            samt = r.get("sell_wan") or r.get("sell_amount_wan")
            tamt = r.get("total_amount_wan") or r.get("amount_wan")
            pct = r.get("pct_chg") or r.get("change_pct")
            pct_after = r.get("pct_chg_after") or r.get("change_pct_after")
            out.append(
                f"| {code} | {name} | {_md_num(nb, 0)} | "
                f"{_md_num(bamt, 0)} | {_md_num(samt, 0)} | "
                f"{_md_num(tamt, 0)} | {_md_pct(pct)} | {_md_pct(pct_after)} |"
            )
    else:
        out.append("（无）")
    out.append("")
    s = p.summary or {}
    out.append(
        f"## 汇总 — requested {s.get('requested', '?')}, "
        f"ok {s.get('ok', '?')}, failed {s.get('failed', '?')}, "
        f"elapsed {s.get('elapsed_ms', '?')}ms"
    )
    return "\n".join(out)


def render_stocks_batch_profile_as_md(p: StockBatchProfileResponse) -> str:
    out = ["# 股票批量画像", ""]
    for entry in p.results:
        marker = "✓" if entry.ok and not entry.errors else ("△" if entry.ok else "✗")
        out.append(f"## {entry.code} {marker}")
        if entry.errors:
            failed_aspects = ", ".join(e.aspect for e in entry.errors)
            out.append(f"**失败 aspects**: {failed_aspects}")
        out.append("")
        for aspect in ("quote", "kline", "kline_5m", "info", "boards"):
            if aspect not in entry.data:
                continue
            block = entry.data[aspect] or {}
            src = block.get("source", "?")
            data = block.get("data")
            if aspect == "quote":
                # Quote is the only aspect whose payload is a FLAT dict
                # (the StockQuote.model_dump() shape — no {source, data}
                # wrapper, since source/code/name are inside). Render every
                # field except source (already in the header).
                out.append(f"### 实时行情 (source: {src})")
                out.append("| 字段 | 值 |")
                out.append("|---|---|")
                for k, v in block.items():
                    if k == "source":
                        continue
                    if isinstance(v, float):
                        out.append(f"| {k} | {_md_num(v, 4)} |")
                    else:
                        out.append(f"| {k} | {v if v is not None else '—'} |")
            elif aspect in ("kline", "kline_5m"):
                label = "5 分钟 K 线" if aspect == "kline_5m" else "日 K 线"
                if isinstance(data, list) and data:
                    out.append(f"### {label} (source: {src}, {len(data)} 根)")
                    out.extend(_md_kline_rows(data))
                else:
                    out.append(f"### {label} — 无数据")
            elif aspect == "info":
                out.append(f"### 公司画像 (source: {src})")
                if isinstance(data, dict):
                    for k, v in data.items():
                        out.append(f"- **{k}**: {v if v is not None else '—'}")
            elif aspect == "boards":
                out.append(f"### 所属板块 (source: {src})")
                if isinstance(data, list) and data:
                    for b in data:
                        t = b.get("type") or "-"
                        out.append(f"- {b.get('code', '?')} ({t}) {b.get('name', '')}")
                else:
                    out.append("（无）")
            out.append("")
    s = p.summary or {}
    out.append(
        f"## 汇总 — requested {s.get('requested', '?')}, "
        f"ok {s.get('ok', '?')}, failed {s.get('failed', '?')}, "
        f"elapsed {s.get('elapsed_ms', '?')}ms"
    )
    return "\n".join(out)


def _md_stats_block(
    title: str, stats, *, total_universe_label: str
) -> list[str]:
    """Render one stats block (个股 or 板块) to MD table rows."""
    out: list[str] = [f"## {title}"]
    if stats is None:
        out.append("（失败 — 详见 errors）")
        return out
    out.append(
        f"样本数: **{stats.sample_size}** ({total_universe_label}); "
        f"均值 {_md_pct(stats.mean_pct)}, 中位 {_md_pct(stats.median_pct)}, "
        f"最高 {_md_pct(stats.max_pct)}, 最低 {_md_pct(stats.min_pct)}"
    )
    out.append(
        f"上涨: **{stats.up_count}** / 下跌: **{stats.down_count}** / "
        f"平盘: **{stats.flat_count}**"
    )
    out.append("")
    out.append("| 区间 | 计数 | 占比 |")
    out.append("|---|---|---|")
    if stats.sample_size:
        for b in stats.buckets:
            pct = b.count / stats.sample_size * 100
            out.append(f"| {b.label} | {b.count} | {_md_num(pct, 2)}% |")
    else:
        for b in stats.buckets:
            out.append(f"| {b.label} | 0 | — |")
    return out


def render_market_stats_as_md(p: MarketStatsResponse) -> str:
    out: list[str] = ["# 市场全量统计", ""]
    out.extend(_md_stats_block("个股", p.stocks, total_universe_label="A 股全市场"))
    out.append("")
    out.extend(_md_stats_block("板块", p.boards, total_universe_label="ths 板块清单"))
    out.append("")
    out.append("## 失败列表")
    out.extend(
        _md_errors(
            [e.model_dump() for e in p.errors], key="block", header="块"
        )
    )
    out.append("")
    s = p.summary or {}
    out.append(
        f"## 汇总 — requested {s.get('requested', '?')}, "
        f"ok {s.get('ok', '?')}, failed {s.get('failed', '?')}, "
        f"elapsed {s.get('elapsed_ms', '?')}ms"
    )
    return "\n".join(out)


# Map route → MD template. Routes look this up in the handler.
_MD_TEMPLATES: dict[str, Callable] = {
    "boards/stock-overlap": render_boards_overlap_as_md,
    "stocks/board-overlap": render_stocks_board_overlap_as_md,
    "boards/filter-stocks": render_filter_stocks_as_md,
    "indices/batch-profile": render_indices_batch_profile_as_md,
    "market-context": render_market_context_as_md,
    "stocks/batch-profile": render_stocks_batch_profile_as_md,
    "market-stats": render_market_stats_as_md,
}


def _render_agent(route_key: str, payload, fmt: str):
    """JSON-passthrough vs MD-dispatch for an agent endpoint.

    ``fmt == "json"`` returns the Pydantic instance unchanged so FastAPI
    applies the route's ``response_model``. ``fmt == "md"`` runs the
    matching ``_MD_TEMPLATES`` entry through :func:`_render_markdown`
    (with the JSON-fallback contract).

    Returns a ``Response`` (MD branch) or the Pydantic instance (JSON branch).
    The route annotates its return type as ``Response`` to express both.
    """
    if fmt != "md":
        return payload
    return _render_markdown(payload, _MD_TEMPLATES[route_key])
