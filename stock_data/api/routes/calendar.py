"""Calendar endpoints."""

from datetime import datetime

from fastapi import Query

from ..endpoint_meta import endpoint_meta
from ..schemas import TradeCalendarResponse
from ._router import router
from .errors import map_errors
from .helpers import get_manager


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

    Failover chain for refresh: Zzshare (P2) → Akshare (P3) → Myquant (P9).
    Baostock used to serve this (P1) but its ``query_trade_dates`` only returns
    dates through today, so it was removed from the chain on 2026-07-21 —
    without this change the cache would never extend past today.
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
