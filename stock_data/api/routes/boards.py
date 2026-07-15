"""Board endpoints (concept / industry / index / special) + ZT/DT/ZBGC pools.

``source`` query parameter is REQUIRED and selects the fetcher:
- ``ths``: ThsFetcher primary, ZzshareFetcher for platecode backfill
  (internal merge, public surface tagged source='ths').
- ``eastmoney``: EastMoneyFetcher (akshare EM backend). Supports
  concept + industry only — no index/special classification upstream.
- ``zhitu``: ZhituFetcher (zhituapi.com).

Each source has its own board classification system; failover between
sources is intentionally not supported (different code systems).
"""

import logging
from datetime import date as date_cls
from datetime import datetime
from typing import Literal

from fastapi import HTTPException, Path, Query

from ...data_provider.base import DataFetchError
from ...data_provider.core.types import safe_float, safe_int
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
    BoardKlineResponse,
    BoardListResponse,
    BoardQuoteResponse,
    BoardStockInfo,
    BoardStocksResponse,
    ErrorResponse,
    KLineData,
    StockBoardInfo,
    StockBoardsResponse,
    ZTPoolResponse,
    ZTPoolStock,
)
from ._router import router
from .errors import map_errors
from .helpers import get_manager

logger = logging.getLogger(__name__)


# Canonical source/type sets — single source of truth in persistence.board
_SOURCES = stock_board_cache.VALID_SOURCES
_TYPES = stock_board_cache.VALID_BOARD_TYPES


def _resolve_source(source: str) -> str:
    """Validate the source name; raise HTTPException(400) on invalid.

    No aliasing: ``source=ths`` is now served directly by ThsFetcher
    (added 2026-07-08). The historical ``ths → zzshare`` alias that
    existed when ThsFetcher had no forward board listing has been
    removed; each source label is now a first-class citizen on this
    endpoint. zzshare remains a valid label too (ZzshareFetcher still
    owns its own upstream path).
    """
    if source not in _SOURCES:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_source",
                "message": f"Unknown source '{source}'. Valid sources: {sorted(_SOURCES)}",
            },
        )
    return source


# ──────────────────────────────────────────────────────────────────────────
# board-history source routing — aliases ``zzshare`` → ``ths``.
# Different from `_resolve_source` (board-list endpoints): THS as a
# board K-line source routes to ThsFetcher (different code system,
# different upstream from zzshare's plates_list). The board-list
# endpoint also accepts `source=ths` directly (no alias) as of
# 2026-07-08, since ThsFetcher now has a forward board listing.
# Only the board-history route still aliases `zzshare → ths`,
# because zzshare's `plate_kline` upstream only supports 883957
# 同花顺全A and therefore ZzshareFetcher has no K-line
# implementation. Both `source=zzshare` and `source=ths` are served
# by ThsFetcher here, preserving backward compat for existing
# callers.
# ──────────────────────────────────────────────────────────────────────────
_BOARD_HISTORY_VALID_SOURCES: tuple[str, ...] = ("ths", "eastmoney")


def _resolve_board_history_source(source: str) -> str:
    """Validate `source` for the board-history route — aliases ``zzshare``→``ths``.

    zzshare's ``plate_kline`` upstream only supports 883957 (同花顺全A); all
    concept / industry / special codes return empty. ZzshareFetcher therefore
    has no `get_board_history` implementation, so this route aliases the
    ``zzshare`` label to ``ths`` and dispatches to ThsFetcher.

    Raises HTTPException(400) on invalid source. The set of valid sources
    is intentionally narrower than `_SOURCES` (board-list): THS is exposed
    here because ThsFetcher has a board K-line implementation, and EastMoney
    is exposed because EastMoneyFetcher has a multi-frequency implementation.
    Zhitu does not expose a board K-line endpoint and is therefore excluded.
    """
    if source == "zzshare":
        source = "ths"
    if source not in _BOARD_HISTORY_VALID_SOURCES:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_source",
                "message": (
                    f"Unknown source '{source}'. "
                    f"Valid sources: {list(_BOARD_HISTORY_VALID_SOURCES)}"
                ),
            },
        )
    return source


# ──────────────────────────────────────────────────────────────────────────
# board-stocks source validation — `zzshare` is no longer a valid label here.
# After the 2026-07-08 unification, zzshare is not a first-class source on
# /boards/{code}/stocks either: the Literal in get_board_stocks (boards.py:~419)
# restricts to ("ths", "eastmoney", "zhitu"), so the route returns 422 before
# _resolve_source runs. zzshare remains routable internally via manager._with_source
# (used by fetch_board_stocks_with_zzshare_fallback for include_quote fallback)
# but is never directly addressable by API clients.
# ──────────────────────────────────────────────────────────────────────────


# Inclusive day-count cap for board-history queries. Mirrors
# ``EastMoneyFetcher.get_board_history``'s hard lmt=800 ceiling —
# past that, push2his auto-escalates klt from daily→weekly→monthly.
# When start_date..end_date exceeds this, the fetcher would silently
# return only the 800 most-recent bars (post-fetch date filter
# trims the older half of the requested range), so we fail fast at
# the route layer with a clear 400 + pagination guidance instead.
_MAX_BOARD_HISTORY_DAYS = 800


def _validate_board_history_date_range(
    start_date: str | None,
    end_date: str | None,
) -> None:
    """Cap start_date..end_date at ``_MAX_BOARD_HISTORY_DAYS``.

    Raises:
        HTTPException(400): inclusive day count exceeds the cap.
            Malformed or reversed date bounds are deferred to the
            fetcher (which raises ``ValueError`` → 400 via
            ``@map_errors``); this helper only checks the width.
    """
    if not (start_date and end_date):
        return
    try:
        s = datetime.strptime(start_date, "%Y-%m-%d").date()
        e = datetime.strptime(end_date, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return  # malformed dates are the fetcher's problem (ValueError → 400)
    if s > e:
        return  # reversed dates are the fetcher's problem
    width = (e - s).days + 1
    if width > _MAX_BOARD_HISTORY_DAYS:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "date_range_too_wide",
                "message": (
                    f"Date range width ({width} days) exceeds the "
                    f"{_MAX_BOARD_HISTORY_DAYS}-day cap (mirrors push2his "
                    f"lmt=800). Narrow the range or paginate."
                ),
            },
        )


def _resolve_type(board_type: str) -> str:
    """Validate type parameter."""
    if board_type not in _TYPES:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_type",
                "message": f"Unknown type '{board_type}'. Valid types: {sorted(_TYPES)}",
            },
        )
    return board_type


def _resolve_type_optional(board_type: str | None) -> str | None:
    """Validate type parameter when provided; allow ``None`` (means: all types)."""
    if board_type is None:
        return None
    return _resolve_type(board_type)


def _parse_stock_boards_source_csv(raw: str | None) -> list[str]:
    """Parse ?source= for /stocks/{code}/boards — alias zzshare → ths.

    THS basic API is the stock→boards reverse-lookup upstream; zzshare
    SDK has no such endpoint (returns stub None), so we alias
    zzshare → ths here (same source data).

    The board-list endpoint does NOT alias in either direction (both
    ``ths`` and ``zzshare`` are first-class labels as of 2026-07-08).
    The two helpers' valid_set and default-when-blank differ, so we
    keep them separate rather than force a config-driven merge
    (rule-of-three not yet met).

    Args:
        raw: User-supplied ?source= value (may be None or comma-separated).

    Returns:
        List of normalized source names in user-requested order, deduplicated.

    Raises:
        HTTPException(400): any source (after aliasing) is not in the valid set.
            Error detail lists valid sources + accepted alias.
    """
    valid_set = stock_board_cache._STOCK_BOARDS_VALID_SOURCES
    alias_map = stock_board_cache._STOCK_BOARDS_SOURCE_ALIAS
    if not raw:
        return list(valid_set)
    out: list[str] = []
    for s in raw.split(","):
        s = s.strip()
        if not s:
            continue
        s = alias_map.get(s, s)
        if s not in valid_set:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "invalid_source",
                    "message": (
                        f"Unknown stock-boards source {s!r}. "
                        f"Valid sources: {list(valid_set)} "
                        f"(alias 'zzshare' accepted)"
                    ),
                },
            )
        if s not in out:
            out.append(s)
    return out


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
    summary="板块清单 (ths/eastmoney/zhitu; ths 内部合并 zzshare 补 platecode) — ?source=zzshare 已下线",
    markets=["csi"],
    capabilities=["STOCK_BOARD"],
)
@map_errors
def list_boards(
    type: Literal["concept", "industry", "index", "special"] | None = Query(
        None,
        description=(
            "Board type. Omit to return all types "
            "(concept / industry / index / special) for the given source."
        ),
    ),
    source: Literal["ths", "eastmoney", "zhitu"] = Query(
        ..., description="Data source (REQUIRED). 'zzshare' was unified under 'ths' on 2026-07-08."
    ),
    subtype: str | None = Query(
        None,
        description=(
            "Source-specific subtype. Validated per (source, type) pair. "
            "Omit to return all subtypes for the type. "
            "When ``type`` is also omitted, ``subtype`` is ignored (no type to validate against)."
        ),
    ),
    include_quote: bool = Query(False, description="Include realtime quote fields"),
    sort_by: Literal["change_pct", "volume", "amount", "price"] | None = Query(
        None, description="Sort by field (requires include_quote=true)"
    ),
    sort_order: Literal["asc", "desc"] = Query("desc", description="Sort order"),
    limit: int | None = Query(None, ge=1, le=500, description="Max number of items (default: all)"),
    refresh: bool = Query(False, description="Force fetch latest from upstream"),
) -> BoardListResponse:
    """Get list of concept / industry / index / special boards.

    When ``type`` is omitted, the response contains boards of every type
    supported by the source. Subtypes are filtered per-type internally; if
    the caller also passes ``subtype``, the validation requires a ``type``
    (subtype is source×type-scoped) — the request is rejected with 400.
    """
    source = _resolve_source(source)
    _resolve_type_optional(type)

    # subtype without type is ambiguous (each type has its own subtype set).
    if type is None and subtype is not None:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_combination",
                "message": (
                    "subtype requires a 'type' filter (subtype is scoped per "
                    "type). Either provide type= or omit subtype=."
                ),
            },
        )

    # subtype validation — early failure before manager invocation
    if type is not None:
        # Reject unsupported source×type pairs with 400 (e.g. zzshare no
        # longer exposes type=special — folded into concept on 2026-07-07).
        # Without this, the fetcher would silently return [].
        stock_board_cache._validate_type_for_source(source, type)
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

    # Route through the persistence layer so cache hits return origin="persistence"
    # (per CLAUDE.md source-tracking matrix). The persistence module owns the
    # "first call of day / refresh flag / include_quote flag" policy and only
    # delegates to manager.get_all_boards when an upstream call is actually
    # needed. sort_by / limit are still applied here in the route layer so
    # both cache-hit and cache-miss paths share a single post-processing step.
    try:
        boards, origin = stock_board_cache.get_board_list(
            board_type=type,
            source=source,
            refresh=refresh,
            include_quote=include_quote,
            subtype=subtype,
            manager=manager,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"error": str(e)}) from e

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
                # Every code path (fresh fetcher + cache hit) tags rows
                # with ``type``; see _read_boards_from_db and the
                # board_type=None fan-out in get_board_list.
                type=b.get("type"),
                price=b.get("price"),
                change_pct=b.get("change_pct"),
                change_amount=b.get("change_amount"),
                volume=b.get("volume"),
                amount=b.get("amount"),
                turnover_rate=b.get("turnover_rate"),
                total_mv=b.get("total_mv"),
                net_inflow=b.get("net_inflow"),
                up_count=b.get("up_count"),
                down_count=b.get("down_count"),
                leading_stock=b.get("leading_stock"),
                leading_stock_price=b.get("leading_stock_price"),
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
    summary="板块成分股 (ths/eastmoney/zhitu; ?source=zzshare 已下线; source=ths&include_quote=false 内部可能走 ZZSHARE primary + THS fallback, 通过 effective_source 字段暴露实际服务 fetcher)",
    markets=["csi"],
    capabilities=["STOCK_BOARD"],
    fetcher_method="get_board_stocks",
)
@map_errors
def get_board_stocks(
    board_code: str = Path(max_length=30, description="Board code"),
    source: Literal["ths", "eastmoney", "zhitu"] = Query(
        ...,
        description=(
            "Data source (REQUIRED). 'zzshare' was unified under 'ths' "
            "on 2026-07-08. Source-routing with one cross-source "
            "fallback: for `source='ths'&include_quote=False` the server "
            "may invoke ZZSHARE first and fall back to THS on empty / "
            "upstream error. The actual fetcher that served the request "
            "is exposed via `BoardStocksResponse.effective_source` — "
            "compare against this `query_source` to detect fallback. "
            "For `source='eastmoney'|'zhitu'` or when `include_quote=True`, "
            "the chosen fetcher is the only one invoked and failures "
            "propagate as 5xx."
        ),
    ),
    include_quote: bool = Query(False, description="Include realtime quote data"),
    refresh: bool = Query(False, description="Force fetch latest from upstream"),
    sort_by: Literal[
        "change_pct", "price", "turnover_rate", "volume_ratio",
        "amplitude", "change_amount", "change_speed", "amount",
        "pe_ratio", "float_market_cap", "free_float_shares",
    ] | None = Query(
        None,
        description=(
            "Sort by field. ONLY effective when include_quote=true. "
            "Defaults to 'change_pct desc' (THS upstream default). "
            "Field code mapping: change_pct=199112, price=10, "
            "turnover_rate=1968584, volume_ratio=1771976, amplitude=526792, "
            "change_amount=264648, change_speed=48, amount=19, "
            "pe_ratio=2034120, float_market_cap=3475914, free_float_shares=407."
        ),
    ),
    sort_order: Literal["asc", "desc"] = Query(
        "desc", description="Sort direction. ONLY effective when include_quote=true.",
    ),
    top_n: int = Query(
        50, ge=1, le=50,
        description=(
            "Max number of stocks to fetch live quotes for "
            "(default 50, mirrors THS upstream hard cap). "
            "When include_quote=true, the server always invokes a single "
            "ZZSHARE membership call to fill in the remaining unquoted "
            "members; the response contains quote_truncated=true iff that "
            "fill-in added rows (or ZZSHARE itself failed)."
        ),
    ),
) -> BoardStocksResponse:
    """Get stocks belonging to a board.

    Quote fields (price / change_pct / change_amount / volume / amount /
    turnover_rate) come from the upstream fetcher. THS populates them by
    default; eastmoney requires ``?include_quote=true``. Zzshare and
    Zhitu do not emit quote fields at all. When quote data is unavailable,
    affected fields are null in the response — not omitted.
    """
    try:
        source = stock_board_cache.normalize_board_stocks_source(source)
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_source", "message": str(e)},
        ) from e

    # Cross-validation: sort_by / sort_order / top_n require
    # (a) source == 'ths' and (b) include_quote == True.
    # Mirrors sibling /boards UX (api/routes/boards.py:327-335) and
    # avoids eastmoney/zhitu TypeError→5xx due to fixed signatures.
    if (sort_by is not None or top_n != 50 or sort_order != "desc"):
        if source != "ths":
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "invalid_combination",
                    "message": (
                        "sort_by / sort_order / top_n are only supported "
                        f"with source='ths'. Got source={source!r}."
                    ),
                },
            )
        if not include_quote:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "invalid_combination",
                    "message": (
                        "sort_by / sort_order / top_n require include_quote=true. "
                        "These parameters drive upstream quote fetching; "
                        "without quotes the sort has no defined ordering."
                    ),
                },
            )

    manager = get_manager()
    try:
        # Route through the persistence layer so cache hits return
        # origin="persistence" (per CLAUDE.md source-tracking matrix).
        # refresh=true now actually forces an upstream refresh instead of
        # being silently dropped. ``source`` is plumbed straight through
        # for the include_quote=True path (strict-routed). For
        # include_quote=False the helper transparently falls back to
        # ZZSHARE first when source='ths' (see
        # persistence/board::fetch_board_stocks_with_zzshare_fallback);
        # ``effective_source`` tells the client which fetcher served the
        # response. Compare against ``query_source`` to detect fallback.
        stocks, origin, effective_source, reason, quote_truncated, total_in_board = (
            stock_board_cache.get_board_stocks(
                board_code,
                source=source,
                refresh=refresh,
                include_quote=include_quote,
                manager=manager,
                sort_by=sort_by,
                sort_order=sort_order,
                top_n=top_n,
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"error": str(e)}) from e

    if not stocks:
        # F2 (2026-07-10): when the persistence helper reports
        # reason="cid_unresolved", the THS cid-index cache missed for
        # this board_code. The board may genuinely exist upstream;
        # a force-refresh can warm the index. Return 422 (not 404) so
        # clients can distinguish "board doesn't exist" from
        # "configuration missing" — the latter is fixable by an
        # operator, the former is a hard 404.
        if reason == "cid_unresolved":
            logger.warning(
                f"[boards] /boards/{board_code}/stocks: THS cid not in "
                f"cache; source={source}; returning 422 cid_unresolved"
            )
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "cid_unresolved",
                    "message": (
                        f"THS concept cid for platecode {board_code!r} "
                        f"is not in the local cid-index cache. Pass "
                        f"?refresh=true to force a cid resolution, or "
                        f"check that the board_code is a valid THS "
                        f"concept/industry platecode."
                    ),
                },
            )
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "message": f"No stocks found for board {board_code}"},
        )

    # Best-effort board name resolution. Delegates to persistence.board's
    # helper which encapsulates the cache-first + fetcher-fallback pattern
    # (review 2026-07-06 finding #10, CLAUDE.md Persistence-Only Routing).
    # The helper swallows DataFetchError / ValueError / AttributeError
    # internally; on any failure it returns None and we fall back to the
    # bare board_code as the name.
    board_name = (
        stock_board_cache.get_board_name_with_fallback(board_code, source, manager=manager)
        or board_code
    )

    stock_list = [
        BoardStockInfo(
            code=s.get("stock_code", ""),
            name=s.get("stock_name", ""),
            price=s.get("price"),
            change_pct=s.get("change_pct"),
            change_amount=s.get("change_amount"),
            volume=s.get("volume"),
            amount=s.get("amount"),
            turnover_rate=s.get("turnover_rate"),
            # 2026-07-13 新增投影 (THS 14 列 6 字段)
            change_speed=s.get("change_speed"),
            volume_ratio=s.get("volume_ratio"),
            amplitude=s.get("amplitude"),
            free_float_shares=s.get("free_float_shares"),
            float_market_cap=s.get("float_market_cap"),
            pe_ratio=s.get("pe_ratio"),
        )
        for s in stocks
    ]

    # include_quote=true → also pull the board-level realtime quote.
    # Post-2026-07-10: the quote call is no longer hardcoded to ths. The
    # route honors the user's `?source=` for the realtime block too — but
    # only when the chosen fetcher actually implements
    # `get_board_realtime`. Currently only ThsFetcher does; eastmoney /
    # zhitu will surface a clear `quote_error="unsupported"` instead of
    # silently swapping to ths (the legacy behavior that motivated A1).
    #
    # On any failure (source unsupported / board_type unresolvable /
    # upstream exception) the route fills `quote_source` + `quote_error`
    # so the client can distinguish "no quote requested" / "quote
    # succeeded" / "source doesn't support quote" / "upstream failed".
    # The BoardInfo block always carries code+name+type from the
    # stock_board cache when available; quote fields are only added on
    # success.
    quote_source: str | None = None
    quote_error: str | None = None
    quote_data: dict | None = None
    cached_type: str | None = None

    if include_quote:
        # Pre-check: does the user's chosen fetcher implement
        # get_board_realtime? Uses the new manager.get_fetcher() public
        # API (B2) + hasattr probe. Avoids hitting the fetcher just to
        # catch AttributeError.
        try:
            quote_fetcher = manager.get_fetcher(source)
        except ValueError as e:
            # Unknown source — should be unreachable because the route's
            # Literal already 422'd, but defensive.
            quote_error = f"unsupported: {e}"
        else:
            if not hasattr(quote_fetcher, "get_board_realtime"):
                quote_error = "unsupported"
            else:
                # Resolve board_type from the cache (C2). The cache is
                # the source of truth — fetcher's internal fallback is
                # reserved for callers that bypass the route (e.g. Stage 2
                # fetcher-test). On cache miss, surface a clear error.
                cached_metadata = stock_board_cache.get_board_metadata(
                    board_code, "ths"
                )
                if cached_metadata and cached_metadata.get("type"):
                    cached_type = cached_metadata["type"]
                    try:
                        quote_data, quote_source = manager.get_board_realtime(
                            board_code,
                            source=source,
                            board_type=cached_type,
                        )
                    except DataFetchError as e:
                        quote_error = f"upstream_failed: {e}"
                        logger.warning(
                            f"[boards] realtime quote upstream failed for "
                            f"board {board_code} (source={source}): {e}"
                        )
                    except ValueError as e:
                        # manager.get_board_realtime can raise ValueError
                        # when the fetcher does not implement the method
                        # (B1: pre-check in _with_source). This is a
                        # belt-and-suspenders path — the hasattr check
                        # above should already have caught it.
                        quote_error = f"unsupported: {e}"
                else:
                    quote_error = "board_type_unresolved"

    # Build BoardInfo once (D2). Quote fields are merged on success only.
    board_info_kwargs: dict = {"code": board_code, "name": board_name}
    if cached_type is not None:
        board_info_kwargs["type"] = cached_type
    if quote_data is not None:
        board_info_kwargs.update(
            {
                "price": quote_data.get("price"),
                "change_pct": quote_data.get("change_pct"),
                "change_amount": quote_data.get("change_amount"),
                "volume": quote_data.get("volume"),
                "amount": quote_data.get("amount"),
                "net_inflow": quote_data.get("net_inflow"),
                "up_count": quote_data.get("up_count"),
                "down_count": quote_data.get("down_count"),
            }
        )
    board_info = BoardInfo(**board_info_kwargs)

    return BoardStocksResponse(
        board=board_info,
        stocks=stock_list,
        query_source=source,
        data_source=origin,
        effective_source=effective_source,
        quote_source=quote_source,
        quote_error=quote_error,
        # 2026-07-13 新增 echo — only populate when sort/top_n was
        # explicitly requested, so the response shape stays the same
        # for default requests (mirrors /boards sibling UX contract).
        quote_truncated=quote_truncated,
        quote_top_n=top_n if (sort_by is not None or sort_order != "desc"
                              or top_n != 50) else None,
        quote_sort_by=sort_by,
        quote_sort_order=sort_order if (sort_by is not None or sort_order != "desc"
                                        or top_n != 50) else None,
        quote_total_in_board=total_in_board if (sort_by is not None or sort_order != "desc"
                                                or top_n != 50) and total_in_board > 0 else None,
    )


@router.get(
    "/boards/{board_code}/quote",
    response_model=BoardQuoteResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid source"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["boards"],
)
@endpoint_meta(
    summary="板块实时行情 (ths 唯一实现; 开盘/涨跌幅/涨跌家数/净流入 等 — q.10jqka 概念详情页). 无需 query 参数。",
    markets=["csi"],
    capabilities=["STOCK_BOARD"],
    fetcher_method="get_board_realtime",
)
@map_errors
def get_board_quote(
    board_code: str = Path(max_length=30, description="Board platecode (e.g. 885595)"),
) -> BoardQuoteResponse:
    """Get board-level realtime quote. Source-routed to ths (only impl), no failover.

    Note: ``source`` is not a route parameter — only ``ths`` implements
    ``get_board_realtime``, so the Literal is hard-coded inside rather
    than exposed as a required ``?source=`` (clients were hitting a 422
    because the only valid value was made mandatory).

    board_type is sourced from the stock_board cache (single source of
    truth). On cache miss / missing type the route returns 422 with a
    clear ``board_type_unresolved`` error — the fetcher's own fallback
    is reserved for callers that bypass this layer (e.g. /control/fetcher-test).
    """
    manager = get_manager()
    # Look up board_type from the cache; the fetcher trusts the caller's
    # classification (post-2026-07-10: no more "881" magic string). The
    # cache is keyed on (code OR platecode, source='ths') — see
    # stock_board_cache.get_board_metadata.
    metadata = stock_board_cache.get_board_metadata(board_code, "ths")
    board_type = metadata.get("type") if metadata else None
    if not board_type:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "board_type_unresolved",
                "message": (
                    f"Cannot determine board type for platecode={board_code!r}. "
                    f"The stock_board cache has no row (or no ``type`` column "
                    f"value) for this code. Run the board-list refresh to "
                    f"populate the cache, or pass a valid board_code."
                ),
                "board_code": board_code,
            },
        )
    quote, origin = manager.get_board_realtime(
        board_code, source="ths", board_type=board_type
    )
    return BoardQuoteResponse(
        board_code=quote.get("board_code") or board_code,
        board_name=quote.get("board_name", ""),
        source=origin,
        price=quote.get("price"),
        change_pct=quote.get("change_pct"),
        change_amount=quote.get("change_amount"),
        open=quote.get("open"),
        high=quote.get("high"),
        low=quote.get("low"),
        prev_close=quote.get("prev_close"),
        volume=quote.get("volume"),
        amount=quote.get("amount"),
        net_inflow=quote.get("net_inflow"),
        up_count=quote.get("up_count"),
        down_count=quote.get("down_count"),
        rank=quote.get("rank"),
    )


@router.get(
    "/stocks/{stock_code}/boards",
    response_model=StockBoardsResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid source/type/subtype"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["boards"],
)
@endpoint_meta(
    summary="股票所属板块 (ths/eastmoney/zhitu; source=zzshare alias → ths)",
    markets=["csi"],
    capabilities=["STOCK_BOARD"],
    fetcher_method="get_stock_boards",
)
@map_errors
def get_stock_boards(
    stock_code: str = Path(max_length=20, description="Stock code (e.g. 000001)"),
    source: str | None = Query(
        None,
        description=(
            "Comma-separated sources (e.g. 'ths,eastmoney,zhitu'). "
            "'zzshare' is accepted as alias for 'ths' (THS upstream is shared). "
            "Omit for all valid sources."
        ),
    ),
    type: Literal["concept", "industry", "index", "special"] | None = Query(
        None, description="Filter by board type"
    ),
    subtype: str | None = Query(None, description="Filter by source-specific subtype"),
) -> StockBoardsResponse:
    """Get boards a stock belongs to.

    Unified endpoint: single source or multi-source aggregation in one call.
    Reads from stock_board_membership; cold data surfaces in cold_sources.
    Background backfill keeps the THS membership cache warm (env var
    BOARD_BACKFILL_ON_STARTUP=true).
    """
    normalized_sources = _parse_stock_boards_source_csv(source)

    # Per-source validation. When ``type`` is given we must check it against
    # every requested source — some sources don't expose the type (e.g.
    # zzshare dropped ``special`` on 2026-07-07), and ``_validate_subtype``
    # returns early when subtype is None so it can't catch that case.
    if type is not None:
        for src in normalized_sources:
            stock_board_cache._validate_type_for_source(src, type)
            if subtype is not None:
                stock_board_cache._validate_subtype(src, type, subtype)

    # Single shared helper — same code path for both single and multi source.
    entries, cold_sources, origin = stock_board_cache.get_stock_memberships(
        stock_code=stock_code,
        sources=normalized_sources,
        type=type,
        subtype=subtype,
        manager=get_manager(),
    )

    # Top-level source field:
    # - multi-source → "merged"
    # - single source → origin from helper (persistence / zhitu / "")
    top_source = "merged" if len(normalized_sources) > 1 else origin

    return StockBoardsResponse(
        stock_code=stock_code,
        source=top_source,
        data=[
            StockBoardInfo(
                code=e["code"],
                name=e["name"],
                type=e.get("type", ""),
                subtype=e.get("subtype", ""),
                source=e["source"],
            )
            for e in entries
        ],
        cold_sources=cold_sources,
    )


@router.get(
    "/boards/{board_code}/history",
    response_model=BoardKlineResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid source / frequency"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["boards"],
)
@endpoint_meta(
    summary="板块 K 线 (ths 概念/行业 全 7 频率 / eastmoney 全 7 频率; zzshare alias → ths; ths 输入统一 platecode)",
    markets=["csi"],
    capabilities=["STOCK_BOARD"],
    fetcher_method="get_board_history",
)
@map_errors
def get_board_history(
    board_code: str = Path(
        max_length=30,
        description=(
            "Board code (source-specific). Examples: "
            "eastmoney='BK0996'; "
            "ths concept='885595' (platecode); ths industry='881270'. "
            "`source=zzshare` is accepted as a backward-compat alias for `ths`. "
            "For THS, prefer the platecode (885xxx / 881xxx) — concept CIDs "
            "(30xxxx) are still accepted as backward-compat input."
        ),
    ),
    source: str = Query(
        ...,
        description=(
            "Data source. One of: ths, eastmoney. "
            "`source=zzshare` is also accepted and aliased to `ths` "
            "(ZzshareFetcher has no K-line implementation — upstream "
            "`plate_kline` only supports 883957 同花顺全A). "
            "Validated by _resolve_board_history_source (400 on unknown)."
        ),
    ),
    frequency: Literal["d", "w", "m", "5m", "15m", "30m", "60m"] = Query(
        "d",
        description=(
            "K-line frequency. Both `ths` and `eastmoney` accept the full "
            "7-frequency set (d / w / m / 5m / 15m / 30m / 60m). "
            "Minute-level frequencies have tighter max-span caps (see "
            "_THS_BOARD_MAX_SPAN_DAYS / EastMoney fetcher)."
        ),
    ),
    start_date: str | None = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: str | None = Query(None, description="End date (YYYY-MM-DD)"),
    days: int = Query(
        30,
        ge=1,
        le=800,
        description=(
            "Days (used when start_date not given). The 800 ceiling "
            "mirrors EastMoneyFetcher's hard `lmt` cap — past that "
            "push2his auto-escalates klt from daily→weekly→monthly. "
            "When `start_date` and `end_date` are both given, the date "
            "range width is also capped at 800 days (returns 400 with "
            "`date_range_too_wide` on overflow). Note: minute-level "
            "frequencies have a tighter per-frequency cap on the fetcher "
            "side (e.g. 5m caps at 30 days)."
        ),
    ),
    board_type: Literal["concept", "industry"] | None = Query(
        None,
        description=(
            "Board classification. Auto-detected from the stock_board cache "
            "when omitted (source='ths' only). Pass explicitly to skip "
            "the cache lookup. Ignored by other sources."
        ),
    ),
) -> BoardKlineResponse:
    """Get historical K-line for a board. Source-routed, no failover."""
    source = _resolve_board_history_source(source)
    # Cap date range width at 800 days. Without this, a request like
    # `start=2015-01-01&end=2024-12-31` would silently return only the
    # 800 most-recent bars (post-fetch filter trims the older half).
    # Fail fast at the route layer with a clear 400 + pagination
    # guidance — see _validate_board_history_date_range.
    _validate_board_history_date_range(start_date, end_date)
    manager = get_manager()
    rows, origin = manager.get_board_history(
        board_code,
        source=source,
        frequency=frequency,
        start_date=start_date,
        end_date=end_date,
        days=days,
        board_type=board_type,
    )

    # Reshape manager rows (list[dict]) into KLineData list. Defensive —
    # if a fetcher returns a partial row missing required fields, drop it
    # rather than 500ing.
    #
    # Per-row ``frequency`` tag: the fetcher sets ``row["frequency"]`` on
    # each parsed bar (verified 2026-07-14 for THS; EastMoney tags its
    # own rows too). We fall back to the request's ``frequency`` param
    # for fetchers that don't tag, so every bar carries the timeframe
    # the caller asked for — defense-in-depth against wrong-upstream-
    # segment bugs that would otherwise be invisible at the row level.
    allowed_freqs = {"d", "w", "m", "5m", "15m", "30m", "60m"}
    kline_data: list[KLineData] = []
    for row in rows or []:
        try:
            row_freq = row.get("frequency")
            if row_freq not in allowed_freqs:
                row_freq = frequency  # fallback to request's frequency
            kline_data.append(
                KLineData(
                    date=str(row.get("date", "")),
                    frequency=row_freq,  # NEW: per-bar frequency tag
                    open=safe_float(row.get("open"), 0.0),
                    high=safe_float(row.get("high"), 0.0),
                    low=safe_float(row.get("low"), 0.0),
                    close=safe_float(row.get("close"), 0.0),
                    volume=safe_int(row.get("volume"), 0),
                    amount=_safe_optional_float(row.get("amount")),
                    change_percent=_safe_optional_float(row.get("pct_chg")),
                )
            )
        except (TypeError, ValueError):
            continue

    # Best-effort board name lookup from the cached board list (no extra
    # upstream call). Empty string when not cached.
    board_name = stock_board_cache.get_board_name(board_code, source) or ""

    return BoardKlineResponse(
        board_code=board_code,
        board_name=board_name,
        period=frequency,
        data=kline_data,
        source=origin,
    )


def _safe_optional_float(v):
    """Return None for None / non-numeric, else float(v). Used by the route layer."""
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


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

    # Volatile-data toggle: drives the in-process TTLCache only.
    # The persistence layer computes the same decision internally.
    is_current_day = (query_date == today_str) and trade_calendar.is_trade_date(today_str)

    cache_key = make_pools_cache_key(type, query_date)
    if is_current_day and is_cache_enabled():
        hit = cached_lookup(get_pools_cache, cache_key, "pools")
        if hit is not None:
            return hit

    manager = get_manager()
    stocks, origin, warning = manager.get_zt_pool(
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
        warning=warning,
    )

    if is_current_day:
        cached_store(get_pools_cache, cache_key, result)
    return result
