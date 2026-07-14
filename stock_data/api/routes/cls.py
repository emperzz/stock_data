"""财联社 早报 / 焦点复盘 endpoints.

Mounted by `stock_data.server` with prefix="/api/v1"; this router's own paths
are /cls/morning-briefing and /cls/market-review. Both require ?date=YYYY-MM-DD
and return the single article for that date (or 404 if not published).
"""

from datetime import date as _date
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Query

from ..cache import cache_endpoint, get_cls_feed_cache, make_cls_feed_cache_key
from ..endpoint_meta import endpoint_meta
from ..schemas import ClsFeedResponse
from .errors import map_errors
from .helpers import get_manager

cls_router = APIRouter()

# Hard window limit: 30 days. CLS list page returns ~20-28 days; 30 is a
# safety margin that catches typos (e.g. user passes 2020-01-01) early
# without rejecting legit "yesterday" requests.
_DATE_WINDOW_DAYS = 30


def _validate_date(date_str: str) -> str:
    """Validate the ?date= query param. Raises HTTPException(400) on bad input.

    Returns the validated YYYY-MM-DD string.
    """
    if not date_str:
        raise HTTPException(status_code=400, detail="date is required (YYYY-MM-DD)")
    try:
        parsed = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"date must be YYYY-MM-DD (got {date_str!r})",
        ) from None
    if parsed > _date.today():
        raise HTTPException(
            status_code=400,
            detail=f"date must not be in the future (got {date_str!r})",
        )
    if parsed < _date.today() - timedelta(days=_DATE_WINDOW_DAYS):
        raise HTTPException(
            status_code=400,
            detail=(
                f"date older than {_DATE_WINDOW_DAYS} days is outside the "
                f"CLS upstream window (got {date_str!r})"
            ),
        )
    return date_str


@cls_router.get(
    "/cls/morning-briefing",
    response_model=ClsFeedResponse,
    responses={
        400: {"description": "Invalid date"},
        404: {"description": "No article published for this date"},
        503: {"description": "All fetchers failed"},
    },
    tags=["cls"],
)
@endpoint_meta(
    summary="财联社早报（按日取最新早报全文）",
    markets=["csi"],
    capabilities=["MORNING_BRIEFING"],
)
@map_errors
@cache_endpoint(
    cache_fn=lambda *args, **kwargs: get_cls_feed_cache(),
    key_builder=lambda date: make_cls_feed_cache_key("morning_briefing", date),
    hit_label="cls_morning_briefing",
)
def get_morning_briefing(
    date: str = Query(description="日期 YYYY-MM-DD"),
) -> ClsFeedResponse:
    """Return the 财联社早报 article for `date`."""
    date = _validate_date(date)
    manager = get_manager()
    article, source = manager.get_morning_briefing(date)
    if article is None:
        raise HTTPException(
            status_code=404,
            detail=f"No 财联社早报 article for {date}",
        )
    return ClsFeedResponse(
        subject="morning_briefing",
        subject_id=1151,
        date=date,
        article=article,
        source=source,
    )


@cls_router.get(
    "/cls/market-review",
    response_model=ClsFeedResponse,
    responses={
        400: {"description": "Invalid date"},
        404: {"description": "No article published for this date"},
        503: {"description": "All fetchers failed"},
    },
    tags=["cls"],
)
@endpoint_meta(
    summary="财联社焦点复盘（按日取最新复盘全文）",
    markets=["csi"],
    capabilities=["MARKET_RECAP"],
)
@map_errors
@cache_endpoint(
    cache_fn=lambda *args, **kwargs: get_cls_feed_cache(),
    key_builder=lambda date: make_cls_feed_cache_key("market_review", date),
    hit_label="cls_market_review",
)
def get_market_recap(
    date: str = Query(description="日期 YYYY-MM-DD"),
) -> ClsFeedResponse:
    """Return the 财联社焦点复盘 article for `date`."""
    date = _validate_date(date)
    manager = get_manager()
    article, source = manager.get_market_recap(date)
    if article is None:
        raise HTTPException(
            status_code=404,
            detail=f"No 财联社焦点复盘 article for {date}",
        )
    return ClsFeedResponse(
        subject="market_review",
        subject_id=1135,
        date=date,
        article=article,
        source=source,
    )
