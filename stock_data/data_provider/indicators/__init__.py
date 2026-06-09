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
    compute(df, spec) / compute_lookback(spec)  ←  THIS LAYER
        ↓
    DataFetcherManager.get_kline_data(...)    ←  capability-routed
        ↓
    Fetchers (Tushare / Baostock / Akshare / ...)

Public surface:
    - calcMA, calcMACD, calcBOLL, calcKDJ, ... : per-indicator pure functions
    - INDICATOR_REGISTRY                       : metadata for introspection
    - compute, compute_lookback, available_catalog : orchestrator functions
    - IndicatorKey                             : enum of supported indicators
"""

from .atr import calcATR
from .bias import calcBIAS
from .boll import calcBOLL
from .cci import calcCCI
from .dmi import calcDMI
from .indicator_service import (
    available_catalog,
    compute,
    compute_lookback,
)
from .kc import calcKC
from .kdj import calcKDJ

# Re-export the per-indicator calc functions for advanced / one-off use
from .ma import calcEMA, calcMA, calcSMA, calcWMA
from .macd import calcMACD
from .obv import calcOBV
from .registry import INDICATOR_REGISTRY, estimate_lookback, list_indicators
from .roc import calcROC
from .rsi import calcRSI
from .sar import calcSAR
from .types import OHLCV, IndicatorKey, MAType
from .wr import calcWR

__all__ = [
    # Service functions
    "compute",
    "compute_lookback",
    "available_catalog",
    # Registry / metadata
    "INDICATOR_REGISTRY",
    "estimate_lookback",
    "list_indicators",
    # Types
    "IndicatorKey",
    "MAType",
    "OHLCV",
    # Pure calc functions
    "calcSMA",
    "calcEMA",
    "calcWMA",
    "calcMA",
    "calcMACD",
    "calcBOLL",
    "calcKDJ",
    "calcRSI",
    "calcWR",
    "calcBIAS",
    "calcCCI",
    "calcATR",
    "calcOBV",
    "calcROC",
    "calcDMI",
    "calcSAR",
    "calcKC",
]
