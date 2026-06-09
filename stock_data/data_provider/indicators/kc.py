"""
KC — Keltner Channel.

    mid     = EMA(close, emaPeriod)
    atr_N   = WilderSmooth(TR, atrPeriod)        (matches ATR's seeding)
    upper   = mid + multiplier * atr_N
    lower   = mid - multiplier * atr_N
    width   = (upper - lower) / mid * 100         (percent)
"""

from __future__ import annotations

from typing import Any

from .atr import calcATR
from .ma import calcEMA
from .types import OHLCV


def calcKC(  # noqa: N802
    bars: list[OHLCV],
    options: dict[str, Any] | None = None,
) -> list[dict[str, float | None]]:
    options = options or {}
    ema_period: int = int(options.get("emaPeriod", 20))
    atr_period: int = int(options.get("atrPeriod", 10))
    multiplier: float = float(options.get("multiplier", 2.0))
    if ema_period <= 0 or atr_period <= 0 or multiplier <= 0:
        raise ValueError("emaPeriod > 0, atrPeriod > 0, multiplier > 0 required")

    closes: list[float | None] = [bar.get("close") for bar in bars]
    mids = calcEMA(closes, ema_period)
    atr_rows = calcATR(bars, {"period": atr_period})

    out: list[dict[str, float | None]] = []
    for i, _bar in enumerate(bars):
        mid = mids[i]
        atr_val = atr_rows[i].get("atr")
        if mid is None or atr_val is None or mid == 0:
            out.append({"kc_mid": None, "kc_upper": None, "kc_lower": None, "kc_width": None})
            continue
        upper = mid + multiplier * atr_val
        lower = mid - multiplier * atr_val
        width = (upper - lower) / mid * 100.0
        out.append(
            {
                "kc_mid": round(mid, 2),
                "kc_upper": round(upper, 2),
                "kc_lower": round(lower, 2),
                "kc_width": round(width, 2),
            }
        )

    return out


__all__ = ["calcKC"]
