"""
Shared types for the technical indicators layer.

All indicators operate on a per-bar time series. Two input shapes are used:
- `list[float | None]`: a single column (typically `close`)
- `list[OHLCV]`:       a row-aligned bundle of OHLCV per bar (for indicators
                       that need high/low/volume alongside close)

Outputs are always aligned to the input index: result[i] corresponds to
input[i]. When an indicator cannot be computed at index `i` (e.g. the
SMA-20 has not accumulated 20 closes yet), the result for that index is
None — never a NaN coerced to float, never a fill-forward of a previous
value, never a cumulative mean. This matches stock-sdk's convention and
matches the convention used by every charting library we care about.
"""

from __future__ import annotations

from enum import Enum
from typing import TypedDict


class MAType(str, Enum):
    """Moving-average flavors supported by calcMA."""

    SMA = "sma"  # simple moving average
    EMA = "ema"  # exponential moving average
    WMA = "wma"  # weighted moving average


class IndicatorKey(str, Enum):
    """Enum of all supported indicators.

    Values are the lowercase keys used on the wire (e.g. in the
    `?indicators=` query param of the /history endpoint).
    """

    MA = "ma"
    MACD = "macd"
    BOLL = "boll"
    KDJ = "kdj"
    RSI = "rsi"
    WR = "wr"
    BIAS = "bias"
    CCI = "cci"
    ATR = "atr"
    OBV = "obv"
    ROC = "roc"
    DMI = "dmi"
    SAR = "sar"
    KC = "kc"


# Minimal OHLCV bundle for indicators that need more than close.
class OHLCV(TypedDict, total=False):
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    volume: float | None


__all__ = [
    "MAType",
    "IndicatorKey",
    "OHLCV",
]
