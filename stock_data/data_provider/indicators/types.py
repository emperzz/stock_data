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

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, TypedDict


# Output of calcMA per bar: {ma5: float|None, ma10: ..., ...}
MAResult = dict[str, float | None]


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


# ---------- input shape ----------


class OHLCV(TypedDict, total=False):
    """Minimal OHLCV bundle for indicators that need more than close."""

    open: float | None
    high: float | None
    low: float | None
    close: float | None
    volume: float | None


# ---------- per-indicator options ----------


class MAOptions(TypedDict, total=False):
    """Options for calcMA."""

    periods: list[int]  # default [5, 10, 20, 30, 60, 120, 250]
    type: MAType  # default SMA


class MACDOptions(TypedDict, total=False):
    short: int  # default 12
    long: int  # default 26
    signal: int  # default 9


class BOLLOptions(TypedDict, total=False):
    period: int  # default 20
    stdDev: float  # default 2.0


class KDJOptions(TypedDict, total=False):
    period: int  # default 9
    kPeriod: int  # default 3
    dPeriod: int  # default 3


class RSIOptions(TypedDict, total=False):
    periods: list[int]  # default [6, 12, 24]


class WROptions(TypedDict, total=False):
    periods: list[int]  # default [6, 10]


class BIASOptions(TypedDict, total=False):
    periods: list[int]  # default [6, 12, 24]


class CCIOptions(TypedDict, total=False):
    period: int  # default 14


class ATROptions(TypedDict, total=False):
    period: int  # default 14


class OBVOptions(TypedDict, total=False):
    maPeriod: int  # default 0 (no MA line)


class ROCOptions(TypedDict, total=False):
    period: int  # default 12
    signalPeriod: int  # default 0 (no signal line)


class DMIOptions(TypedDict, total=False):
    period: int  # default 14
    adxPeriod: int  # default = period


class SAROptions(TypedDict, total=False):
    afStart: float  # default 0.02
    afIncrement: float  # default 0.02
    afMax: float  # default 0.20


class KCOptions(TypedDict, total=False):
    emaPeriod: int  # default 20
    atrPeriod: int  # default 10
    multiplier: float  # default 2.0


# Mapping from IndicatorKey -> options TypedDict
IndicatorOptions = dict[IndicatorKey, dict[str, Any]]


# ---------- output shape ----------


@dataclass
class IndicatorResult:
    """A single bar's worth of indicator values, flattened to {column: value}.

    The `IndicatorService` merges these dicts onto each K-line row before
    serializing to the API response. Column naming is
    `<indicator>_<subfield>`, e.g.:
        - macd_dif, macd_dea, macd_hist
        - kdj_k, kdj_d, kdj_j
        - boll_mid, boll_upper, boll_lower, boll_bandwidth
        - ma5, ma10, ma20, ma30, ma60  (one column per MA period)
        - rsi_6, rsi_12, rsi_24
        - dmi_pdi, dmi_mdi, dmi_adx, dmi_adxr
        - sar, sar_trend, sar_ep, sar_af
    """

    values: dict[str, float | None] = field(default_factory=dict)


__all__ = [
    "MAType",
    "IndicatorKey",
    "IndicatorOptions",
    "IndicatorResult",
    "OHLCV",
    "MAOptions",
    "MACDOptions",
    "BOLLOptions",
    "KDJOptions",
    "RSIOptions",
    "WROptions",
    "BIASOptions",
    "CCIOptions",
    "ATROptions",
    "OBVOptions",
    "ROCOptions",
    "DMIOptions",
    "SAROptions",
    "KCOptions",
]
