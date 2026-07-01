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


def round2(value: float) -> float:
    """Round to 2 decimals. Returns 0.0 for NaN to keep JSON valid.

    None and NaN are both treated as "no value"; callers should always
    guard with `value is not None` before passing to this helper.
    """
    if value != value:  # NaN check
        return 0.0
    return round(float(value), 2)


class MABatch:
    """Per-compute-call memoizer for moving-average arrays.

    When the orchestrator computes several indicators in one pass (e.g.
    ``?indicators=ma,macd,boll,kc,bias``), many of them independently
    ask for the same SMA(20) / EMA(26) / ... arrays. Without sharing,
    each indicator recomputes its MA from scratch — pure waste.

    Usage from :func:`indicator_service.compute`:

        batch = MABatch()
        # ... per indicator:
        rows = spec_obj.compute(closes, options, batch=batch)

    And inside the indicator (e.g. ``calcBOLL``):

        mids = batch.sma(closes, period)  # cached after first call

    Cache key is ``(id(data), ma_type, period)``. ``id()`` is unique per
    list object for the lifetime of that object, and the batch is
    constructed fresh inside each ``compute()`` call and discarded at
    the end — so we never leak arrays across requests, and we never
    retain references to lists that have been garbage-collected (Python
    may reuse an ``id()`` after GC, but by then the batch is gone too).
    """

    def __init__(self) -> None:
        self._cache: dict[tuple[int, str, int], list[float | None]] = {}

    def sma(self, data: list[float | None], period: int) -> list[float | None]:
        key = (id(data), "sma", period)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        from .ma import calcSMA  # local import to avoid circular at module load

        result = calcSMA(data, period)
        self._cache[key] = result
        return result

    def ema(self, data: list[float | None], period: int) -> list[float | None]:
        key = (id(data), "ema", period)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        from .ma import calcEMA

        result = calcEMA(data, period)
        self._cache[key] = result
        return result

    def wma(self, data: list[float | None], period: int) -> list[float | None]:
        key = (id(data), "wma", period)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        from .ma import calcWMA

        result = calcWMA(data, period)
        self._cache[key] = result
        return result


__all__ = [
    "MAType",
    "IndicatorKey",
    "OHLCV",
    "round2",
    "MABatch",
]
