"""Calendar and stock-list endpoints."""

from datetime import datetime

from fastapi import Query

from ...data_provider.persistence import stock_list
from ..endpoint_meta import endpoint_meta
from ..schemas import StockInfo, TradeCalendarResponse
from ._router import router
from .errors import map_errors
from .helpers import get_manager


@router.get(
    "/stocks",
    response_model=list[StockInfo],
    responses={
        400: {"model": "ErrorResponse", "description": "Invalid market parameter"},
    },
    tags=["stocks"],
)
@endpoint_meta(
    summary="股票列表（分页）",
    markets=["csi", "hk", "us"],
    capabilities=["STOCK_LIST"],
)
@map_errors
def list_stocks(
    market: str = Query(..., pattern="^(csi|hk|us)$", description="Market: csi/hk/us"),
    refresh: bool = Query(False, description="Force fetch latest from upstream"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    limit: int = Query(100, ge=1, le=1000, description="Pagination limit"),
) -> list[StockInfo]:
    """List all available stocks for a specified market.

    Note:
        A-shares are exposed as ``csi`` (中证). The legacy ``cn`` tag is
        an internal fetcher convention and is NOT a valid value here —
        ``csi`` is the single public-facing A-share tag.
    """
    manager = get_manager()
    stocks, _origin = stock_list.get_stock_list(market, refresh=refresh, manager=manager)
    page = stocks[offset : offset + limit]
    return [
        StockInfo(
            code=s["code"],
            name=s["name"],
            market=market,
            exchange=s.get("exchange"),
        )
        for s in page
    ]


@router.get(
    "/calendar",
    response_model=TradeCalendarResponse,
    responses={
        500: {"model": "ErrorResponse", "description": "Server error"},
    },
    tags=["calendar"],
)
@endpoint_meta(
    summary="A 股交易日历",
    markets=["csi"],
    capabilities=["TRADE_CALENDAR"],
)
@map_errors
def get_trade_calendar(
    refresh: bool = Query(False, description="Force fetch latest from upstream"),
) -> TradeCalendarResponse:
    """Get A-share trade calendar.

    Returns all available trade dates sorted ascending. Data is cached in SQLite
    and refreshed from upstream when:
    - refresh=True is requested
    - Cache is empty
    - Cached latest date is before today (data may be stale)

    Uses akshare tool_trade_date_hist_sina API.
    """
    from ...data_provider.persistence.trade_calendar import (
        get_cached_calendar,
        get_latest_cached_trade_date,
    )

    today = datetime.now().strftime("%Y-%m-%d")

    # Check if refresh is needed
    should_refresh = refresh
    if not should_refresh:
        cached_dates, _ = get_cached_calendar()
        if not cached_dates:
            should_refresh = True
        else:
            latest_cached = get_latest_cached_trade_date()
            if latest_cached is None or latest_cached < today:
                should_refresh = True

    if should_refresh:
        try:
            manager = get_manager()
            dates, _origin = manager.get_trade_calendar()
            # If the manager returned empty, fall through and try the cache
            # instead of raising — preserves the pre-refactor behaviour where
            # the calendar endpoint always returned *something* (possibly
            # stale) rather than 500ing on a transient upstream blank.
        except Exception:
            # Persisted fallback path. The route still returns whatever is in
            # SQLite, even if upstream is down. @map_errors would turn this
            # into a 500, so we swallow and rely on the cache lookup below.
            cached_dates, _ = get_cached_calendar()
            if not cached_dates:
                # Re-raise only if there's truly no cache to fall back on.
                raise

    dates, _ = get_cached_calendar()
    latest = get_latest_cached_trade_date() if dates else None

    return TradeCalendarResponse(trade_dates=dates, latest_date=latest, total=len(dates))
