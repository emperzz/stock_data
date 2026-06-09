"""
CCI — Commodity Channel Index.

    TP     = (high + low + close) / 3
    MA_TP  = SMA(TP, period)
    MD     = mean(|TP[i] - MA_TP|) for i in window  (mean deviation)
    CCI    = (TP - MA_TP) / (0.015 * MD)

Default period = 14. Needs OHLC.
"""

from __future__ import annotations
from typing import Any

from .types import OHLCV


def _sma(values: list[float], period: int) -> list[float | None]:
    """Plain SMA (we already have calcSMA in ma.py, but it works on
    list[float | None]; here we always have floats and want speed)."""
    out: list[float | None] = []
    window: list[float] = []
    for v in values:
        window.append(v)
        if len(window) > period:
            window.pop(0)
        if len(window) == period:
            out.append(sum(window) / period)
        else:
            out.append(None)
    return out


def calcCCI(
    bars: list[OHLCV],
    options: dict[str, Any] | None = None,
) -> list[dict[str, float | None]]:
    options = options or {}
    period: int = int(options.get("period", 14))
    if period <= 0:
        raise ValueError(f"period must be > 0, got {period}")

    tp: list[float] = []
    for bar in bars:
        h = bar.get("high")
        l = bar.get("low")
        c = bar.get("close")
        if h is None or l is None or c is None:
            tp.append(0.0)  # placeholder; the output for this bar will be None anyway
        else:
            tp.append((h + l + c) / 3.0)

    ma_tp = _sma(tp, period)

    out: list[dict[str, float | None]] = []
    for i, bar in enumerate(bars):
        ma = ma_tp[i]
        if ma is None or bar.get("high") is None or bar.get("low") is None:
            out.append({"cci": None})
            continue

        # Mean absolute deviation over the last `period` TPs
        window = tp[max(0, i - period + 1) : i + 1]
        if len(window) < period:
            out.append({"cci": None})
            continue
        md = sum(abs(v - ma) for v in window) / period
        if md == 0:
            out.append({"cci": None})
            continue
        cci = (tp[i] - ma) / (0.015 * md)
        out.append({"cci": round(cci, 2)})

    return out


__all__ = ["calcCCI"]
