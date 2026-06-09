"""
Technical indicators package.

Pure-compute layer that sits on top of DataFetcherManager. Indicators are
calculated from already-fetched K-line data — no external API calls, no
fetcher involvement, no capability routing. The fetchers' job ends when
the K-line DataFrame is in hand; the indicator service's job is to enrich
that frame with the requested technical columns.

Architecture:
    API Layer
        ↓
    IndicatorService.compute(df, indicators)  ←  THIS LAYER
        ↓
    DataFetcherManager.get_kline_data(...)    ←  capability-routed
        ↓
    Fetchers (Tushare / Baostock / Akshare / ...)

Public surface:
    - calcMA, calcMACD, calcBOLL, calcKDJ, ... : per-indicator pure functions
    - INDICATOR_REGISTRY                       : metadata for introspection
    - IndicatorService                         : orchestrator
    - IndicatorKey                             : enum of supported indicators
"""

from .types import IndicatorKey, MAType, OHLCV
from .registry import INDICATOR_REGISTRY, estimate_lookback, list_indicators
from .indicator_service import (
    IndicatorService,
    available_catalog,
    compute,
    compute_lookback,
)

# Re-export the per-indicator calc functions for advanced / one-off use
from .ma import calcSMA, calcEMA, calcWMA, calcMA
from .macd import calcMACD
from .boll import calcBOLL
from .kdj import calcKDJ
from .rsi import calcRSI
from .wr import calcWR
from .bias import calcBIAS
from .cci import calcCCI
from .atr import calcATR
from .obv import calcOBV
from .roc import calcROC
from .dmi import calcDMI
from .sar import calcSAR
from .kc import calcKC

__all__ = [
    # Service
    "IndicatorService",
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
