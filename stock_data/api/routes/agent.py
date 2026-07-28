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

Routes added in Phase 2 (this file):
- GET /agent/indices/batch-profile (renamed from indices/market-snapshot per user request)
- GET /agent/market-context
- POST /agent/stocks/batch-profile (renamed from stocks/batch/profile per user request)
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
    make_stocks_batch_profile_cache_key,
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
    IndexKlineBlock,
    IndexProfile,
    IndicesBatchProfileResponse,
    MarketContextDragonTiger,
    MarketContextDragonTigerSummary,
    MarketContextDragonTigerSummaryTop,
    MarketContextLimitPools,
    MarketContextMessages,
    MarketContextResponse,
    StockBatchAspectError,
    StockBatchProfileEntry,
    StockBatchProfileRequest,
    StockBatchProfileResponse,
    StockQuote,
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

logger = logging.getLogger(__name__)


# Server-local timezone for market_session classification. The
# proposal anchors pre/intra/post-market to 09:15 / 15:00 Asia/Shanghai.
_CST = ZoneInfo("Asia/Shanghai")

# YYYY-MM-DD gate for ?trade_date= on /agent/market-context. Loose regex
# (no calendar validity — Feb 30 etc. is fine; the upstream will return
# empty results and the caller can detect that). What we want to catch
# is "not a date" (e.g. "yesterday") which would otherwise silently 200.
_TRADE_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# 4 core CSI indices used when ?codes is omitted on
# /agent/indices/batch-profile. Aligned with market-recap §4 step 3
# "指数全景" default set: 上证 + 深证 + 创业板 + 北证 50.
_DEFAULT_CORE_CSI_INDICES: tuple[str, ...] = ("000001", "399001", "399006", "899050")

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
    cached_store(get_quote_cache, cache_key, result)
    return result


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
        payload.board_code,
        payload.source,
        payload.filters.model_dump(),
        payload.limit,
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
    return result


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
            "Comma-separated index codes. Empty = 4 core CSI indices "
            "(上证/深证/创业板/北证50). Each code is fanned out to "
            "1 quote + 3 K-line frequencies; per-frequency failure is "
            "isolated into entry.errors[frequency]."
        ),
    ),
) -> IndicesBatchProfileResponse:
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
        return _reorder_by_code(hit, code_list, "indices")

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
    return result


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
) -> MarketContextResponse:
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
        return hit

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
    return result


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
) -> StockBatchProfileResponse:
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
        return _reorder_by_code(hit, payload.codes, "results")

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
    return resp
