"""财联社 早报 / 焦点复盘 endpoints (mounted under /api/v1/news/*).

Mounted by `stock_data.server` with prefix="/api/v1"; this router's own paths
are /news/morning-briefing and /news/market-recap. Both require ?date=YYYY-MM-DD
and return the single article for that date (or 404 if not published).

Tag: 'news' (merged with the existing /api/v1/news/* section in the explorer).
"""

from datetime import date as _date
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query

from ...data_provider.fetchers.cls_fetcher import (
    CLS_SUBJECT_MARKET_RECAP,
    CLS_SUBJECT_MORNING_BRIEFING,
    CLS_SUBJECT_NAMES,
)
from ...data_provider.manager import DataFetcherManager
from ..cache import cache_endpoint, get_cls_feed_cache, make_cls_feed_cache_key
from ..endpoint_meta import endpoint_meta
from ..schemas import ClsFeedResponse
from .errors import map_errors
from .helpers import get_manager

cls_router = APIRouter()

# CLS publishes in Asia/Shanghai; window + "today" checks use Shanghai date so
# a UTC-deployed server doesn't reject a Beijing user's local "today" between
# 16:00–23:59 UTC (= 00:00–07:59 next day BJT).
_CLS_TZ = timezone(timedelta(hours=8))

# Hard window limit: 28 days. CLS list page returns ~20–28 days; 28 is the
# documented upper bound so upstream regressions (window shrink) surface as
# 404 from the fetcher rather than a silent route-layer pass-through.
_DATE_WINDOW_DAYS = 28


def _today_in_cls_tz() -> _date:
    return datetime.now(_CLS_TZ).date()


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
    today = _today_in_cls_tz()
    if parsed > today:
        raise HTTPException(
            status_code=400,
            detail=f"date must not be in the future (got {date_str!r})",
        )
    if parsed < today - timedelta(days=_DATE_WINDOW_DAYS):
        raise HTTPException(
            status_code=400,
            detail=(
                f"date older than {_DATE_WINDOW_DAYS} days is outside the "
                f"CLS upstream window (got {date_str!r})"
            ),
        )
    return date_str


def _make_cls_route(
    *,
    path: str,
    subject: str,
    subject_id: int,
    manager_method_name: str,
    cache_namespace: str,
    hit_label: str,
    not_found_msg: str,
    summary: str,
    capability: str,
):
    """Build one of the two CLS feed route handlers.

    The two endpoints share the entire pipeline (validate → manager → 404/200)
    and differ only in five small variations — this factory keeps that
    contract in one place so future response-shape changes can't drift.
    """

    @cls_router.get(
        path,
        response_model=ClsFeedResponse,
        responses={
            400: {"description": "Invalid date"},
            404: {"description": "No article published for this date"},
            503: {"description": "All fetchers failed"},
        },
        tags=["news"],
    )
    @endpoint_meta(
        summary=summary,
        markets=["csi"],
        capabilities=[capability],
    )
    @map_errors
    @cache_endpoint(
        cache_fn=lambda *args, **kwargs: get_cls_feed_cache(),
        key_builder=lambda date: make_cls_feed_cache_key(cache_namespace, date),
        hit_label=hit_label,
    )
    def handler(date: str = Query(description="日期 YYYY-MM-DD")) -> ClsFeedResponse:
        """Return the CLS feed article for `date`."""
        date = _validate_date(date)
        manager = get_manager()
        article, source = getattr(manager, manager_method_name)(date)
        if article is None:
            raise HTTPException(status_code=404, detail=not_found_msg.format(date=date))
        # source is the fetcher class name (e.g. "ClsFetcher"); CLAUDE.md
        # requires the slug form ("cls") in the response.
        source_slug = DataFetcherManager._derive_slug(source)
        return ClsFeedResponse(
            subject=subject,
            subject_id=subject_id,
            date=date,
            article=article,
            source=source_slug,
        )

    return handler


# Build the two endpoints from the shared factory.
_make_cls_route(
    path="/news/morning-briefing",
    subject=CLS_SUBJECT_NAMES[CLS_SUBJECT_MORNING_BRIEFING],
    subject_id=CLS_SUBJECT_MORNING_BRIEFING,
    manager_method_name="get_morning_briefing",
    cache_namespace=CLS_SUBJECT_NAMES[CLS_SUBJECT_MORNING_BRIEFING],
    hit_label="cls_morning_briefing",
    not_found_msg="No 财联社早报 article for {date}",
    summary="财联社早报（按日取最新早报全文）",
    capability="MORNING_BRIEFING",
)

_make_cls_route(
    path="/news/market-recap",
    subject=CLS_SUBJECT_NAMES[CLS_SUBJECT_MARKET_RECAP],
    subject_id=CLS_SUBJECT_MARKET_RECAP,
    manager_method_name="get_market_recap",
    cache_namespace=CLS_SUBJECT_NAMES[CLS_SUBJECT_MARKET_RECAP],
    hit_label="cls_market_review",
    not_found_msg="No 财联社焦点复盘 article for {date}",
    summary="财联社焦点复盘（按日取最新复盘全文）",
    capability="MARKET_RECAP",
)
