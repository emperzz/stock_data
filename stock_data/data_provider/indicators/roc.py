"""
ROC — Rate of Change.

    ROC = (close[i] - close[i - period]) / close[i - period] * 100

Optionally a signal line: `EMA(ROC, signalPeriod)`.
"""

from __future__ import annotations

from .ma import calcEMA
from .types import ROCOptions


def calcROC(
    closes: list[float | None],
    options: ROCOptions | None = None,
) -> list[dict[str, float | None]]:
    options = options or {}
    period: int = int(options.get("period", 12))
    signal_period: int = int(options.get("signalPeriod", 0))
    if period <= 0:
        raise ValueError(f"period must be > 0, got {period}")
    if signal_period < 0:
        raise ValueError(f"signalPeriod must be >= 0, got {signal_period}")

    rocs: list[float | None] = []
    for i, value in enumerate(closes):
        if i < period or value is None or closes[i - period] is None:
            rocs.append(None)
            continue
        base = closes[i - period]
        if base == 0:
            rocs.append(None)
            continue
        rocs.append(round((value - base) / base * 100.0, 2))

    out: list[dict[str, float | None]] = []
    if signal_period > 0:
        signal = calcEMA(rocs, signal_period)
        for r, s in zip(rocs, signal):
            out.append({"roc": r, "roc_signal": s})
    else:
        for r in rocs:
            out.append({"roc": r})
    return out


__all__ = ["calcROC"]
