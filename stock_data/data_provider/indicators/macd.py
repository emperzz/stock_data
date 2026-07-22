"""
MACD — Moving Average Convergence/Divergence.

Components:
    DIF   = EMA(close, short) - EMA(close, long)
    DEA   = EMA(DIF, signal)            (also called "signal line")
    MACD  = (DIF - DEA) * 2              (also called "histogram")

Defaults match the industry standard (12/26/9).
"""

from __future__ import annotations

from typing import Any

from .ma import calcEMA


def calcMACD(  # noqa: N802
    closes: list[float | None],
    options: dict[str, Any] | None = None,
) -> list[dict[str, float | None]]:
    """Compute MACD for each bar.

    Returns a list of dicts with keys `macd_dif`, `macd_dea`, `macd_hist`,
    aligned to the input. Null at any index where the underlying EMAs
    are not yet defined.
    """
    options = options or {}
    short: int = int(options.get("short", 12))
    long: int = int(options.get("long", 26))
    signal: int = int(options.get("signal", 9))

    if short <= 0 or long <= 0 or signal <= 0:
        raise ValueError("short, long, and signal must all be > 0")
    if short >= long:
        raise ValueError("short must be < long")

    ema_short = calcEMA(closes, short)
    ema_long = calcEMA(closes, long)

    # DIF is only valid at indices where BOTH EMAs are defined
    dif: list[float | None] = []
    for s, long_ema in zip(ema_short, ema_long, strict=True):
        if s is None or long_ema is None:
            dif.append(None)
        else:
            dif.append(s - long_ema)

    # DEA = EMA(DIF, signal) — calcEMA handles None correctly
    dea = calcEMA(dif, signal)

    out: list[dict[str, float | None]] = []
    for d, e in zip(dif, dea, strict=True):
        # Publish whatever is defined. DIF becomes valid first; DEA
        # needs `signal` valid DIF values to seed and lags by that
        # many bars. hist is the difference, so it's only meaningful
        # once both are defined.
        out.append(
            {
                "macd_dif": round(d, 2) if d is not None else None,
                "macd_dea": round(e, 2) if e is not None else None,
                "macd_hist": (round((d - e) * 2.0, 2) if d is not None and e is not None else None),
            }
        )
    return out


__all__ = ["calcMACD"]
