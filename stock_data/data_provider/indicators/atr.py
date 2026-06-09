"""
ATR — Average True Range (Wilder's smoothing).

    TR[i]   = max(high - low, |high - prev_close|, |low - prev_close|)
    ATR[i]  = WilderSmooth(TR, period)         (seeded with SMA of first `period` TRs)

We surface both `atr` (the smoothed value) and `tr` (the raw true range)
so callers can also see the most recent bar's TR without recomputing.
"""

from __future__ import annotations

from typing import Any

from .types import OHLCV


def calcATR(  # noqa: N802
    bars: list[OHLCV],
    options: dict[str, Any] | None = None,
) -> list[dict[str, float | None]]:
    options = options or {}
    period: int = int(options.get("period", 14))
    if period <= 0:
        raise ValueError(f"period must be > 0, got {period}")

    # Compute TR per bar (None for the first bar, which has no prev_close)
    trs: list[float | None] = []
    prev_close: float | None = None
    for bar in bars:
        h = bar.get("high")
        low = bar.get("low")
        c = bar.get("close")
        if h is None or low is None or c is None or prev_close is None:
            trs.append(None)
        else:
            tr = max(h - low, abs(h - prev_close), abs(low - prev_close))
            trs.append(tr)
        prev_close = c

    # ATR: seed = SMA of first `period` non-None TRs; then Wilder smoothing
    out: list[dict[str, float | None]] = []
    seed_buf: list[float] = []
    atr: float | None = None

    for tr in trs:
        if tr is None:
            out.append({"atr": None, "tr": None})
            continue
        if atr is None:
            seed_buf.append(tr)
            if len(seed_buf) == period:
                atr = sum(seed_buf) / period
                out.append({"atr": round(atr, 2), "tr": round(tr, 2)})
            else:
                out.append({"atr": None, "tr": round(tr, 2)})
        else:
            atr = (atr * (period - 1) + tr) / period
            out.append({"atr": round(atr, 2), "tr": round(tr, 2)})

    return out


__all__ = ["calcATR"]
