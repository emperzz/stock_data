"""
Technical indicators package.

Pure-compute layer that sits on top of DataFetcherManager. Indicators are
calculated from already-fetched K-line data — no external API calls, no
fetcher involvement, no capability routing. The fetchers' job ends when
the K-line DataFrame is in hand; this layer's job is to enrich that
frame with the requested technical columns.

Architecture:
    API Layer
        ↓
    compute(df, spec) / estimate_lookback(spec)  ←  THIS LAYER
        ↓
    DataFetcherManager.get_kline_data(...)    ←  capability-routed
        ↓
    Fetchers (Tushare / Baostock / Akshare / ...)

Public surface:
    - calcMA, calcMACD, calcBOLL, calcKDJ, ... : per-indicator pure functions
    - INDICATOR_REGISTRY                       : metadata for introspection
    - compute, estimate_lookback, available_catalog : orchestrator functions
    - IndicatorKey                             : enum of supported indicators
"""

from .indicator_service import (
    available_catalog,
    compute,
)
from .registry import INDICATOR_REGISTRY, estimate_lookback, list_indicators
from .types import OHLCV, IndicatorKey, MAType

__all__ = [
    # Service functions
    "compute",
    "available_catalog",
    # Registry / metadata
    "INDICATOR_REGISTRY",
    "estimate_lookback",
    "list_indicators",
    # Types
    "IndicatorKey",
    "MAType",
    "OHLCV",
]
