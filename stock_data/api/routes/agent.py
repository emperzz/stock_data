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
import pandas as pd
from dataclasses import asdict, dataclass
from datetime import datetime
from datetime import time as dt_time
from itertools import combinations
from zoneinfo import ZoneInfo

from fastapi import HTTPException, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, PlainTextResponse
from starlette.responses import Response

from ...data_provider.base import DataFetchError
from ...data_provider.features.build import build_features
from ...data_provider.persistence import board as stock_board_cache
from ...data_provider.persistence import trade_calendar
from ...data_provider.utils.stats import (
    BOARD_BUCKET_BIN_WIDTH,
    STOCK_BUCKET_BIN_WIDTH,
    AggregateStats,
    build_board_buckets,
    build_stock_buckets,
    compute_aggregate,
)
from ..cache import (
    cached_lookup,
    cached_store,
    get_quote_cache,  # reused as generic in-memory slot for agent results
    make_boards_overlap_cache_key,
    make_filter_stocks_cache_key,
    make_market_context_cache_key,
    make_market_stats_cache_key,
    make_stocks_board_overlap_cache_key,
)
from ..endpoint_meta import endpoint_meta
from ..schemas import (
    BatchFeatures,
    BoardProfile,
    BoardsBatchProfileRequest,
    BoardsBatchProfileResponse,
    BoardsOverlapPair,
    BoardsOverlapRequest,
    BoardsOverlapResponse,
    BoardsOverlapSet,
    BoardStats,
    ErrorResponse,
    FilterStocksMatchedStock,
    FilterStocksRequest,
    FilterStocksResponse,
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
    MinimalQuote,
    StockBatchAspectError,
    StockBatchProfileEntry,
    StockBatchProfileRequest,
    StockBatchProfileResponse,
    StocksBoardOverlapPair,
    StocksBoardOverlapRequest,
    StocksBoardOverlapResponse,
    StocksBoardOverlapStockSet,
    StockStats,
)
from ._router import router
from .errors import map_errors
from .helpers import (
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

# 3 core CSI indices used when ?codes is omitted on
# /agent/indices/batch-profile. Aligned with market-recap §4 step 3
# "指数全景" default set: 上证 + 深证 + 创业板.
_DEFAULT_CORE_CSI_INDICES: tuple[str, ...] = ("000001", "399001", "399006")


@dataclass(frozen=True)
class FreqProfile:
    """Everything the batch-profile feature endpoints need per frequency.

    Kept as ONE dataclass rather than four parallel frequency-keyed dicts:
    adding a frequency is a single structured edit, and omitting a field is
    a construction-time TypeError instead of a silent runtime degradation
    (a missing MA60 warm-up used to fall back to `days` via `.get`, leaving
    every MA60 value None with no error anywhere).

    mgr_frequency
        Manager/fetcher-internal frequency code. Fetchers only accept bare
        minute codes ("5", not "5m") — same mapping the /kline route applies
        via helpers._period_to_freq.
    days_range / default_days
        Calendar-day (min, max) and default. Mirrors correlation/matrix with
        the minute caps enlarged per user decision (5m 3->5, 15m 5->8,
        30m 10->15, 60m 20->30).
    ma60_warmup_days
        Calendar days needed to warm MA60 (60 bars). Minute frames are
        already warm inside their bounded day windows (240+ bars), so they
        set this equal to their max range (i.e. no bump).
    """

    mgr_frequency: str
    days_range: tuple[int, int]
    default_days: int
    ma60_warmup_days: int


_FEATURE_FREQS: dict[str, FreqProfile] = {
    "d": FreqProfile(mgr_frequency="d", days_range=(2, 365), default_days=60, ma60_warmup_days=90),
    "w": FreqProfile(
        mgr_frequency="w", days_range=(14, 1095), default_days=156, ma60_warmup_days=420
    ),
    "m": FreqProfile(
        mgr_frequency="m", days_range=(60, 1825), default_days=365, ma60_warmup_days=1825
    ),
    "1m": FreqProfile(mgr_frequency="1", days_range=(2, 3), default_days=3, ma60_warmup_days=0),
    "5m": FreqProfile(mgr_frequency="5", days_range=(2, 5), default_days=5, ma60_warmup_days=0),
    "15m": FreqProfile(mgr_frequency="15", days_range=(2, 8), default_days=8, ma60_warmup_days=0),
    "30m": FreqProfile(mgr_frequency="30", days_range=(2, 15), default_days=15, ma60_warmup_days=0),
    "60m": FreqProfile(mgr_frequency="60", days_range=(2, 30), default_days=30, ma60_warmup_days=0),
}


def _resolve_and_validate_days(frequency: str, days: int | None) -> int:
    """Apply the per-frequency default then 422 if outside the range."""
    profile = _FEATURE_FREQS[frequency]
    lo, hi = profile.days_range
    resolved = days if days is not None else profile.default_days
    if not (lo <= resolved <= hi):
        raise HTTPException(
            status_code=422,
            detail={
                "error": "invalid_request",
                "message": f"days must be an int in [{lo}, {hi}] for frequency={frequency}",
            },
        )
    return resolved


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
        422: {"model": ErrorResponse, "description": "days out of range / unsupported frequency"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["agent"],
)
@endpoint_meta(
    summary="指数批量画像（trend/pivots/volume 计算指标 + 极简 quote，单 frequency）",
    markets=["csi"],
    capabilities=[],
)
@map_errors
def get_indices_batch_profile(
    codes: str | None = Query(
        default=None,
        description=(
            "Comma-separated index codes (1-5). Empty = 3 core CSI indices "
            "(上证/深证/创业板). Each code is fanned out to a minimal quote "
            "+ computed features at the requested (frequency, days)."
        ),
    ),
    frequency: str = Query("d", description="One of d/w/m/1m/5m/15m/30m/60m"),
    days: int | None = Query(
        default=None, ge=2, description="Calendar days; per-frequency max validated server-side."
    ),
    format: str = Query(
        "json",
        pattern="^(json|md)$",
        description="Output format. json=application/json (default); md=text/markdown.",
    ),
) -> Response:
    """Per-index fan-out: minimal quote + computed features at one frequency."""
    if frequency not in _FEATURE_FREQS:
        raise HTTPException(
            status_code=422,
            detail={"error": "invalid_request", "message": f"unsupported frequency: {frequency}"},
        )
    days = _resolve_and_validate_days(frequency, days)
    code_list = [
        c.strip() for c in (codes.split(",") if codes else _DEFAULT_CORE_CSI_INDICES) if c.strip()
    ] or list(_DEFAULT_CORE_CSI_INDICES)
    if len(code_list) > 5:
        raise HTTPException(
            status_code=422, detail={"error": "invalid_request", "message": "codes must be 1-5"}
        )

    started = time.monotonic()
    manager = get_manager()
    profile = _FEATURE_FREQS[frequency]
    fetch_days = max(days, profile.ma60_warmup_days)
    profiles: list[IndexProfile] = []
    n_ok = 0

    for code in code_list:
        errors: dict[str, str | None] = {"quote": None, "features": None}
        quote = None
        features = None

        try:
            q = manager.get_index_realtime_quote(code)
            if q is None:
                errors["quote"] = "no fetcher could serve realtime quote"
            else:
                quote = _build_minimal_quote_from_unified(q)
        except (DataFetchError, ValueError) as exc:
            logger.warning(f"[agent/indices/batch-profile] quote {code} failed: {exc}")
            errors["quote"] = str(exc)

        try:
            df, _src = manager.get_kline_data(
                code,
                days=fetch_days,
                frequency=profile.mgr_frequency,
                adjust=None,
                asset="index",
            )
            features = BatchFeatures(**build_features(df, frequency=frequency, days=days))
        except Exception as exc:
            logger.warning(
                f"[agent/indices/batch-profile] kline {code} {frequency} failed: {exc}",
                exc_info=True,
            )
            errors["features"] = f"{type(exc).__name__}: {exc}"

        if quote is not None and features is not None:
            n_ok += 1
        profiles.append(
            IndexProfile(
                code=code,
                name=_resolve_index_name(code),
                quote=quote,
                features=features,
                errors=errors,
            )
        )

    result = IndicesBatchProfileResponse(
        frequency=frequency,
        days=days,
        indices=profiles,
        summary=_batch_summary(len(code_list), n_ok, started),
    )
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


@router.post(
    "/agent/stocks/batch-profile",
    response_model=StockBatchProfileResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid request (codes out of range)"},
        422: {"model": ErrorResponse, "description": "days out of range / unsupported frequency"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["agent"],
)
@endpoint_meta(
    summary="股票批量画像（trend/pivots/volume 计算指标 + 极简 quote + info + boards）",
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
    """Per-code fan-out across quote / features / info / boards.

    ``features`` replaces the old raw kline / kline_5m aspects: the
    server computes trend / pivots / volume at the requested
    (frequency, days) instead of returning raw bars. Per-aspect failures
    live in ``results[i].errors[]``; the entry is only ``ok=False`` when
    every aspect failed.
    """
    days = _resolve_and_validate_days(payload.frequency, payload.days)
    started = time.monotonic()
    manager = get_manager()
    profile = _FEATURE_FREQS[payload.frequency]
    fetch_days = max(days, profile.ma60_warmup_days)
    results: list[StockBatchProfileEntry] = []
    n_ok = 0

    for code in payload.codes:
        errors: list[StockBatchAspectError] = []
        quote = None
        features = None
        info = None
        boards = None
        name = ""

        try:
            q = manager.get_realtime_quote(code)
            if q is not None:
                quote = _build_minimal_quote_from_unified(q)
                name = q.name or ""
        except Exception as exc:
            logger.warning(f"[agent/stocks/batch-profile] {code} quote failed: {exc}")
            errors.append(
                StockBatchAspectError(aspect="quote", error=type(exc).__name__, message=str(exc))
            )

        try:
            df, _src = manager.get_kline_data(
                code,
                days=fetch_days,
                frequency=profile.mgr_frequency,
                adjust="qfq",
                asset="stock",
            )
            features = BatchFeatures(**build_features(df, frequency=payload.frequency, days=days))
        except Exception as exc:
            logger.warning(
                f"[agent/stocks/batch-profile] {code} features failed: {exc}", exc_info=True
            )
            errors.append(
                StockBatchAspectError(aspect="features", error=type(exc).__name__, message=str(exc))
            )

        try:
            info_dict, info_src = manager.get_stock_info(code)
            info = {"source": info_src, "data": info_dict}
        except Exception as exc:
            logger.warning(f"[agent/stocks/batch-profile] {code} info failed: {exc}")
            errors.append(
                StockBatchAspectError(aspect="info", error=type(exc).__name__, message=str(exc))
            )

        try:
            entries, _cold, _origin = stock_board_cache.get_stock_memberships(
                stock_code=code, sources=["ths"], manager=manager
            )
            boards = {"source": "persistence", "data": entries}
        except Exception as exc:
            logger.warning(f"[agent/stocks/batch-profile] {code} boards failed: {exc}")
            errors.append(
                StockBatchAspectError(aspect="boards", error=type(exc).__name__, message=str(exc))
            )

        ok = any(v is not None for v in (quote, features, info, boards))
        if ok:
            n_ok += 1
        results.append(
            StockBatchProfileEntry(
                code=code,
                name=name,
                ok=ok,
                quote=quote,
                features=features,
                info=info,
                boards=boards,
                errors=errors,
            )
        )

    resp = StockBatchProfileResponse(
        frequency=payload.frequency,
        days=days,
        results=results,
        summary=_batch_summary(len(payload.codes), n_ok, started),
    )
    return _render_agent("stocks/batch-profile", resp, format)


def _build_minimal_quote_from_unified(q) -> MinimalQuote:
    """Map a UnifiedRealtimeQuote to the expanded MinimalQuote.

    Mirrors the field-mapping logic in StockQuote.from_unified_quote
    (schemas.py:126) — same fallback rules for amplitude, same 1e8
    division for mcap_yi / float_mcap_yi. Kept here (rather than
    reusing StockQuote.from_unified_quote) to keep the nested-flag /
    current_price-rename / _serialize semantics out of the agent
    path: MinimalQuote is always top-level, never embedded, and the
    helper returns the Pydantic instance directly.
    """
    amplitude = q.amplitude
    if amplitude is None and q.high is not None and q.low is not None and q.pre_close:
        amplitude = (q.high - q.low) / q.pre_close * 100

    def _yi(v):
        return None if v is None else v / 1e8

    return MinimalQuote(
        price=q.price,
        change_pct=q.change_pct,
        change_amount=q.change_amount,
        open=q.open_price,
        high=q.high,
        low=q.low,
        prev_close=q.pre_close,
        volume=q.volume,
        volume_unit=q.volume_unit or "share",
        amount=q.amount,  # UnifiedRealtimeQuote.amount is 元; pass-through
        turnover_pct=q.turnover_rate,
        amplitude_pct=amplitude,
        volume_ratio=q.volume_ratio,
        pe_ratio=q.pe_ratio,
        pb_ratio=q.pb_ratio,
        mcap_yi=_yi(q.total_mv),
        float_mcap_yi=_yi(q.circ_mv),
        limit_up=q.limit_up,
        limit_down=q.limit_down,
    )


def _build_minimal_quote_from_board_dict(q: dict) -> MinimalQuote:
    """Map a ThsFetcher.get_board_realtime dict to MinimalQuote.

    THS upstream returns volume in 万手 (matches ``volume_unit``) and
    amount in 亿元 — multiplied by 1e8 here to align with the rest
    of the server's API surface (see `routes/boards.py:857`, the
    /boards/{code}/quote route does the same conversion). The 8
    stock-only fields (turnover / amplitude / valuation / 涨跌停)
    stay None; the 4 board-only fields (up_count / down_count /
    net_inflow / rank) are populated.
    """
    raw_amount = q.get("amount")
    return MinimalQuote(
        price=q.get("price"),
        change_pct=q.get("change_pct"),
        change_amount=q.get("change_amount"),
        open=q.get("open"),
        high=q.get("high"),
        low=q.get("low"),
        prev_close=q.get("prev_close"),
        volume=q.get("volume"),  # THS upstream uses safe_int → int | None; pass-through
        volume_unit="wan_shou",
        amount=(raw_amount * 1e8) if raw_amount is not None else None,
        up_count=q.get("up_count"),
        down_count=q.get("down_count"),
        net_inflow=q.get("net_inflow"),  # board upstream already 亿元; pass-through
        rank=q.get("rank"),
    )


@router.post(
    "/agent/boards/batch-profile",
    response_model=BoardsBatchProfileResponse,
    responses={
        422: {"model": ErrorResponse, "description": "days out of range / unsupported frequency"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["agent"],
)
@endpoint_meta(
    summary="板块批量画像（trend/pivots/volume 计算指标 + 极简 realtime，THS 单源，单 frequency）",
    markets=["csi"],
    capabilities=[],
)
@map_errors
def post_boards_batch_profile(
    payload: BoardsBatchProfileRequest,
    format: str = Query(
        "json",
        pattern="^(json|md)$",
        description="Output format. json=application/json (default); md=text/markdown.",
    ),
) -> Response:
    """Per-board fan-out: minimal realtime quote + computed features at one frequency.

    Source is fixed to THS (only fetcher implementing ``get_board_realtime``;
    board codes are source-specific so cross-source fan-out would force
    callers to send one platecode per source anyway). ``board_type`` is
    NOT exposed to the caller — ``ThsFetcher.get_board_realtime`` resolves
    it from the stock_board cache with an internal fallback. Per-board
    failures land in ``boards[i].errors{}``; the rest of the response is
    still emitted. **No composite cache layer** (spec §5) — fetcher-level
    TTLs already cover N+1; this layer would only add a stale-risk window.
    """
    days = _resolve_and_validate_days(payload.frequency, payload.days)
    started = time.monotonic()
    manager = get_manager()
    profile = _FEATURE_FREQS[payload.frequency]
    fetch_days = max(days, profile.ma60_warmup_days)
    boards: list[BoardProfile] = []
    n_ok = 0

    for code in payload.codes:
        errors: dict[str, str | None] = {"quote": None, "features": None}
        quote = None
        features = None
        name = ""

        # --- realtime quote ---
        try:
            q, _src = manager.get_board_realtime(code, source="ths")
            if q is not None:
                quote = _build_minimal_quote_from_board_dict(q)
        except Exception as exc:
            logger.warning(
                f"[agent/boards/batch-profile] quote {code} failed: {exc}",
                exc_info=True,
            )
            errors["quote"] = f"{type(exc).__name__}: {exc}"

        # --- computed features ---
        try:
            rows, _src = manager.get_board_history(
                code,
                source="ths",
                # NOTE: pass the PUBLIC frequency string ("5m"), NOT profile.mgr_frequency ("5").
                # `manager.get_board_history` validates against BOARD_KLINE_FREQ_BY_SOURCE["ths"]
                # which contains public strings ("5m" etc.); mgr_frequency is for the stock/index
                # path (manager.get_kline_data) only. See spec §3.1 "Frequency translation note".
                frequency=payload.frequency,
                days=fetch_days,
            )
            # manager.get_board_history returns (list[dict], source) — NOT a DataFrame
            # (unlike manager.get_kline_data used by stocks/indices batch-profile).
            # Wrap the rows so build_features can call df.empty / df["date"].iloc[-1].
            # ``pd.DataFrame(rows)`` correctly produces an empty (0,0) frame for
            # ``rows=[]`` or ``rows=None`` without raising — build_features treats
            # the empty frame as a no-op and returns ``{trend:{}, pivots:{}, volume:{}}``.
            df = pd.DataFrame(rows)
            features = BatchFeatures(**build_features(df, frequency=payload.frequency, days=days))
        except Exception as exc:
            logger.warning(
                f"[agent/boards/batch-profile] features {code} {payload.frequency} failed: {exc}",
                exc_info=True,
            )
            errors["features"] = f"{type(exc).__name__}: {exc}"

        # --- name resolution (best-effort; helper swallows its own errors) ---
        name = stock_board_cache.get_board_name_with_fallback(code, "ths", manager=manager) or ""

        if quote is not None or features is not None:
            n_ok += 1
        boards.append(
            BoardProfile(
                code=code,
                name=name,
                quote=quote,
                features=features,
                errors=errors,
            )
        )

    result = BoardsBatchProfileResponse(
        frequency=payload.frequency,
        days=days,
        boards=boards,
        summary=_batch_summary(len(payload.codes), n_ok, started),
    )
    return _render_agent("boards/batch-profile", result, format)


def _stats_payload(agg: AggregateStats) -> dict:
    """Flatten an AggregateStats dataclass into a plain dict.

    ``asdict`` recursively converts the dataclass (including the nested
    bucket list) into plain dicts, so the field mapping is driven by the
    schema itself — adding a field only touches stats.py + schemas.py,
    not this helper.
    """
    return asdict(agg)


def _stock_stats_from_aggregate(agg: AggregateStats) -> "StockStats":
    """AggregateStats → StockStats (no source field)."""
    return StockStats(**_stats_payload(agg))


def _board_stats_from_aggregate(agg: AggregateStats, source: str) -> "BoardStats":
    """AggregateStats → BoardStats, carrying the serving source label."""
    return BoardStats(**_stats_payload(agg), source=source)


@router.get(
    "/agent/market-stats",
    response_model=MarketStatsResponse,
    responses={500: {"model": ErrorResponse, "description": "Server error"}},
    tags=["agent"],
)
@endpoint_meta(
    summary="市场全量统计（个股+板块涨幅分布 + 桶形数据）",
    markets=["csi"],
    capabilities=[],  # agent aggregation, no single capability
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
            q.change_pct for q in (quotes or []) if getattr(q, "change_pct", None) is not None
        ]
        agg = compute_aggregate(
            values,
            bin_width=STOCK_BUCKET_BIN_WIDTH,
            buckets_template=build_stock_buckets(),
        )
        stocks_stats = _stock_stats_from_aggregate(agg)
        ok += 1
    except Exception as exc:
        logger.warning(f"[agent/market-stats] stocks failed: {exc}", exc_info=True)
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
                b.get("change_pct")
                for b in (boards or [])
                if isinstance(b.get("change_pct"), (int, float))
                and not isinstance(b.get("change_pct"), bool)
            ]
            agg = compute_aggregate(
                values,
                bin_width=BOARD_BUCKET_BIN_WIDTH,
                buckets_template=build_board_buckets(),
            )
            boards_stats = _board_stats_from_aggregate(agg, src or "ths")
            ok += 1
        except Exception as exc:
            logger.warning(f"[agent/market-stats] boards failed: {exc}", exc_info=True)
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


def _md_quote_block(out: list[str], q) -> None:
    """Render the MinimalQuote block as four subgroup tables.

    Skips empty subgroups entirely (see spec §6.2 rationale). Renders
    None cells as "—" via the existing _md_num helper.
    """
    out.append("### 行情")
    out.append("")

    # ── 价格 ──
    price_rows = [
        ("当前", _md_num(q.price, 3)),
        ("涨跌额", _md_num(q.change_amount, 3)),
        ("涨跌幅", _md_pct(q.change_pct)),
        ("今开", _md_num(q.open, 3)),
        ("最高", _md_num(q.high, 3)),
        ("最低", _md_num(q.low, 3)),
        ("昨收", _md_num(q.prev_close, 3)),
    ]
    if q.limit_up is not None or q.limit_down is not None:
        price_rows.append(
            ("涨跌停价", f"{_md_num(q.limit_up, 3)} / {_md_num(q.limit_down, 3)}")
        )
    if any(v and v != "—" for _, v in price_rows):
        _render_dict_block(out, "价格", dict(price_rows))

    # ── 量价 ──
    volume_str = (
        _md_num(q.volume, 0) + (" 股" if q.volume_unit == "share" else " 万手")
        if q.volume is not None
        else "—"
    )
    vol_rows = [
        ("成交量", volume_str),
        ("成交额(元)", _md_num(q.amount, 0)),
    ]
    if q.turnover_pct is not None:
        vol_rows.append(("换手率", _md_pct(q.turnover_pct)))
    if q.amplitude_pct is not None:
        vol_rows.append(("振幅", _md_num(q.amplitude_pct, 2) + "%"))
    if q.volume_ratio is not None:
        vol_rows.append(("量比", _md_num(q.volume_ratio, 2)))
    if any(v and v != "—" for _, v in vol_rows):
        _render_dict_block(out, "量价", dict(vol_rows))

    # ── 估值 (stock only) ──
    val_rows = []
    if q.pe_ratio is not None:
        val_rows.append(("PE", _md_num(q.pe_ratio, 2)))
    if q.pb_ratio is not None:
        val_rows.append(("PB", _md_num(q.pb_ratio, 2)))
    if q.mcap_yi is not None:
        val_rows.append(("总市值(亿)", _md_num(q.mcap_yi)))
    if q.float_mcap_yi is not None:
        val_rows.append(("流通市值(亿)", _md_num(q.float_mcap_yi)))
    if val_rows:
        _render_dict_block(out, "估值", dict(val_rows))

    # ── 板块统计 (board only) ──
    board_rows = []
    if q.up_count is not None:
        board_rows.append(("上涨家数", _md_num(q.up_count, 0)))
    if q.down_count is not None:
        board_rows.append(("下跌家数", _md_num(q.down_count, 0)))
    if q.net_inflow is not None:
        board_rows.append(("资金净流入(亿)", _md_num(q.net_inflow)))
    if q.rank is not None:
        board_rows.append(("涨幅排名", q.rank))
    if board_rows:
        _render_dict_block(out, "板块统计", dict(board_rows))


def _md_feature_block(out: list[str], f) -> None:
    """Render the three feature blocks of a BatchFeatures instance."""
    out.append("### 指标")
    out.append("**趋势**")
    _render_dict_block(out, "MA", f.trend.ma)
    _render_dict_block(out, "MA 环比变化 (%)", f.trend.ma_change)
    out.append(
        f"- ADX: {_md_num(f.trend.adx)} / PDI: {_md_num(f.trend.pdi)} / MDI: {_md_num(f.trend.mdi)}"
    )
    out.append("")
    _render_dict_block(out, "RSI", f.trend.rsi)
    _render_dict_block(out, "BOLL", f.trend.boll)
    out.append("**顶底**")
    if f.pivots.window_high:
        out.append(
            f"- 区间最高: {_md_num(f.pivots.window_high.get('price'))} @ {f.pivots.window_high.get('date')}"
        )
    if f.pivots.window_low:
        out.append(
            f"- 区间最低: {_md_num(f.pivots.window_low.get('price'))} @ {f.pivots.window_low.get('date')}"
        )
    if f.pivots.max_vol_bar:
        out.append(
            f"- 最大量价: {_md_num(f.pivots.max_vol_bar.get('price'))} @ {f.pivots.max_vol_bar.get('date')} (量 {_md_num(f.pivots.max_vol_bar.get('volume'))})"
        )
    # Same empty-table rule as _render_dict_block: no bare header + separator
    # with zero rows (reads as "computed, but blank"). swings is [] both for an
    # empty DataFrame and for a frame with no confirmed reversal yet.
    if f.pivots.swings:
        out.append("| 日期 | 类型 | 价格 | 确认 |")
        out.append("|---|---|---|---|")
        for s in f.pivots.swings:
            out.append(
                f"| {s.date} | {s.type} | {_md_num(s.price)} | {'✓' if s.confirmed else '✗'} |"
            )
    else:
        out.append("（无确认摆动点）")
    if f.pivots.pending:
        p = f.pivots.pending
        out.append(f"- 在途({p.side}): {_md_num(p.price)} @ {p.date} (bars_since {p.bars})")
    # `params` pins which ZigZag settings produced the swings above — without
    # it the顶底 points are uncalibratable, so it MUST appear in the MD too
    # (api-reference.md "No data is dropped" contract).
    if f.pivots.params:
        out.append("- 参数: " + " / ".join(f"{k}={v}" for k, v in f.pivots.params.items()))
    out.append("")
    out.append("**量价**")
    out.append(
        f"- 最新成交量: {_md_num(f.volume.latest_volume)} / 量比(5): {_md_num(f.volume.vol_ratio_5)}"
    )
    if f.volume.z_anomalies:
        out.append("| 日期 | 开 | 高 | 低 | 收盘 | 成交量 | z | 方向 | 涨跌幅 |")
        out.append("|---|---|---|---|---|---|---|---|---|")
        for a in f.volume.z_anomalies:
            out.append(
                f"| {a.date} | {_md_num(a.open)} | {_md_num(a.high)} | {_md_num(a.low)} "
                f"| {_md_num(a.close)} | {_md_num(a.volume)} | {_md_num(a.z_score)} "
                f"| {a.direction} | {_md_pct(a.change_pct)} |"
            )
    else:
        out.append("（无 z>2 放量异动）")
    out.append("")


def render_boards_batch_profile_as_md(p: BoardsBatchProfileResponse) -> str:
    out = [f"# 板块批量画像 — {p.frequency} {p.days}d", ""]
    for board in p.boards:
        ok_marker = "✓" if (board.quote or board.features) else "✗"
        out.append(f"## {board.code} {board.name} {ok_marker}")
        if board.quote:
            _md_quote_block(out, board.quote)
        else:
            err = (board.errors or {}).get("quote") or "no quote"
            out.append(f"- 行情失败: {err}")
        out.append("")
        if board.features:
            _md_feature_block(out, board.features)
        else:
            err = (board.errors or {}).get("features") or "no features"
            out.append(f"### 指标 — 失败: {err}")
            out.append("")
    s = p.summary or {}
    out.append(
        f"## 汇总 — requested {s.get('requested', '?')}, "
        f"ok {s.get('ok', '?')}, failed {s.get('failed', '?')}, "
        f"elapsed {s.get('elapsed_ms', '?')}ms"
    )
    return "\n".join(out)


def render_indices_batch_profile_as_md(p: IndicesBatchProfileResponse) -> str:
    out = [f"# 指数批量画像 — {p.frequency} {p.days}d", ""]
    for idx in p.indices:
        ok_marker = "✓" if idx.quote or idx.features else "✗"
        out.append(f"## {idx.code} {idx.name} {ok_marker}")
        if idx.quote:
            _md_quote_block(out, idx.quote)
        else:
            out.append(f"- 行情失败: {(idx.errors or {}).get('quote') or 'no quote'}")
        out.append("")
        if idx.features:
            _md_feature_block(out, idx.features)
        else:
            out.append(f"### 指标 — 失败: {(idx.errors or {}).get('features') or 'no features'}")
            out.append("")
    s = p.summary or {}
    out.append(
        f"## 汇总 — requested {s.get('requested', '?')}, "
        f"ok {s.get('ok', '?')}, failed {s.get('failed', '?')}, "
        f"elapsed {s.get('elapsed_ms', '?')}ms"
    )
    return "\n".join(out)


def _render_dict_block(out: list[str], title: str, d: dict) -> None:
    """Render every key/value of a flat dict (no field is dropped).

    An empty dict means "no bars to compute from" (``build_features`` /
    ``compute_trend`` return ``{}`` for an empty DataFrame without raising,
    so ``errors`` stays None). Emit an explicit marker rather than a bare
    heading + empty table skeleton, which reads as "computed, but blank".
    """
    out.append(f"### {title}")
    if not d:
        out.append("（无数据）")
        out.append("")
        return
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
    out = [f"# 股票批量画像 — {p.frequency} {p.days}d", ""]
    for entry in p.results:
        marker = "✓" if entry.ok and not entry.errors else ("△" if entry.ok else "✗")
        out.append(f"## {entry.code} {entry.name} {marker}")
        if entry.errors:
            failed = ", ".join(e.aspect for e in entry.errors)
            out.append(f"**失败 aspects**: {failed}")
        out.append("")
        if entry.quote:
            _md_quote_block(out, entry.quote)
        out.append("")
        if entry.features:
            _md_feature_block(out, entry.features)
        if entry.info and entry.info.get("data"):
            out.append("### 公司画像")
            for k, v in entry.info["data"].items():
                out.append(f"- **{k}**: {v if v is not None else '—'}")
            out.append("")
        if entry.boards and entry.boards.get("data"):
            out.append("### 所属板块")
            for b in entry.boards["data"]:
                t = b.get("type") or "-"
                out.append(f"- {b.get('code', '?')} ({t}) {b.get('name', '')}")
            out.append("")
    s = p.summary or {}
    out.append(
        f"## 汇总 — requested {s.get('requested', '?')}, "
        f"ok {s.get('ok', '?')}, failed {s.get('failed', '?')}, "
        f"elapsed {s.get('elapsed_ms', '?')}ms"
    )
    return "\n".join(out)


def _md_stats_block(title: str, stats, *, total_universe_label: str) -> list[str]:
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
        f"上涨: **{stats.up_count}** / 下跌: **{stats.down_count}** / 平盘: **{stats.flat_count}**"
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
    out.extend(_md_errors([e.model_dump() for e in p.errors], key="block", header="块"))
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
    "boards/batch-profile": render_boards_batch_profile_as_md,
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
