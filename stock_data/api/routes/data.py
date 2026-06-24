"""Cross-cutting data endpoints that don't belong to a single stock:

- /dragon-tiger (全市场龙虎榜)
- /hot-topics (热点题材)
- /north-flow/realtime (北向资金)
- /indicators (技术指标目录)

The per-stock dragon-tiger endpoint (``/stocks/{code}/dragon-tiger``) lives
in :mod:`.stocks` because it's keyed by a stock path parameter.
"""

from datetime import datetime

from fastapi import Query

from ...data_provider.indicators import available_catalog
from ..cache import (
    cache_endpoint,
    get_dragontiger_cache,
    get_hot_topics_cache,
    get_north_flow_cache,
    make_daily_dragon_tiger_cache_key,
    make_hot_topics_cache_key,
    make_north_flow_cache_key,
)
from ..endpoint_meta import endpoint_meta
from ..schemas import (
    DailyDragonTigerResponse,
    DailyDragonTigerStock,
    ErrorResponse,
    HotTopicRecord,
    HotTopicResponse,
    IndicatorCatalogEntry,
    IndicatorCatalogResponse,
    NorthFlowRecord,
    NorthFlowResponse,
)
from ._router import router
from .errors import map_errors
from .helpers import get_manager


@router.get(
    "/dragon-tiger",
    response_model=DailyDragonTigerResponse,
    responses={
        503: {"model": ErrorResponse, "description": "Data unavailable"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["dragon-tiger"],
)
@endpoint_meta(
    summary="龙虎榜（全市场）",
    markets=["csi"],
    capabilities=["DRAGON_TIGER"],
    fetcher_method="get_daily_dragon_tiger",  # default get_dragon_tiger is per-stock variant
)
@map_errors
@cache_endpoint(
    cache_fn=lambda *args, **kwargs: get_dragontiger_cache(),
    key_builder=lambda trade_date, min_net_buy: make_daily_dragon_tiger_cache_key(
        trade_date, min_net_buy
    ),
    hit_label="daily_dragon_tiger",
)
def get_daily_dragon_tiger(
    trade_date: str = Query(default="", description="Trade date (YYYY-MM-DD)"),
    min_net_buy: float | None = Query(default=None, description="Min net buy (万元)"),
) -> DailyDragonTigerResponse:
    """全市场龙虎榜（按 trade_date + min_net_buy 过滤）。"""
    manager = get_manager()
    data, source = manager.get_daily_dragon_tiger(trade_date, min_net_buy)
    return DailyDragonTigerResponse(
        date=data["date"],
        total=data["total"],
        stocks=[DailyDragonTigerStock(**s) for s in data["stocks"]],
        source=source,
    )


@router.get(
    "/hot-topics",
    response_model=HotTopicResponse,
    responses={
        503: {"model": ErrorResponse, "description": "Data unavailable"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["hot-topics"],
)
@endpoint_meta(
    summary="热点题材",
    markets=["csi"],
    capabilities=["HOT_TOPICS"],
)
@map_errors
@cache_endpoint(
    cache_fn=lambda *args, **kwargs: get_hot_topics_cache(),
    key_builder=lambda date: make_hot_topics_cache_key(date),
    hit_label="hot_topics",
)
def get_hot_topics(
    date: str = Query(default="", description="Date (YYYY-MM-DD), empty=today"),
) -> HotTopicResponse:
    """Get daily hot stocks with reason tags."""
    manager = get_manager()
    data, source = manager.get_hot_topics(date)
    topics = [HotTopicRecord(**r) for r in data]
    actual_date = date or datetime.now().strftime("%Y-%m-%d")
    return HotTopicResponse(date=actual_date, total=len(topics), topics=topics, source=source)


@router.get(
    "/north-flow/realtime",
    response_model=NorthFlowResponse,
    responses={
        503: {"model": ErrorResponse, "description": "Data unavailable"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["north-flow"],
)
@endpoint_meta(
    summary="北向资金",
    markets=["csi"],
    capabilities=["NORTH_FLOW"],
)
@map_errors
@cache_endpoint(
    cache_fn=lambda *args, **kwargs: get_north_flow_cache(),
    key_builder=lambda: make_north_flow_cache_key(),
    hit_label="north_flow",
)
def get_north_flow() -> NorthFlowResponse:
    """Get north-bound capital flow (minute-level)."""
    manager = get_manager()
    data, source = manager.get_north_flow()
    return NorthFlowResponse(records=[NorthFlowRecord(**r) for r in data], source=source)


@router.get(
    "/indicators",
    response_model=IndicatorCatalogResponse,
    tags=["indicators"],
)
@endpoint_meta(
    summary="技术指标目录",
    markets=["csi", "hk", "us"],
    capabilities=[],
)
def get_indicator_catalog() -> IndicatorCatalogResponse:
    """List all available technical indicators.

    Useful for AI agents that want to introspect what's available before
    sending ``?indicators=...`` on ``/stocks/{code}/history``.
    """
    catalog = available_catalog()
    return IndicatorCatalogResponse(
        indicators=[IndicatorCatalogEntry(**entry) for entry in catalog]
    )
