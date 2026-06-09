"""
RSI — Relative Strength Index (Wilder's smoothing).

For each `period`:
    change[i] = close[i] - close[i-1]
    gain[i]   = max(change[i], 0)
    loss[i]   = max(-change[i], 0)

Wilder smoothing (recursive, not the simple SMA variant):
    avg_gain[i] = (avg_gain[i-1] * (period - 1) + gain[i]) / period
    avg_loss[i] = (avg_loss[i-1] * (period - 1) + loss[i]) / period

    RS  = avg_gain / avg_loss
    RSI = 100 - 100 / (1 + RS)               (when avg_loss > 0)
    RSI = 100                                (when avg_loss == 0 and avg_gain > 0)
    RSI = None                               (when both are zero — flat market)
"""

from __future__ import annotations

from typing import Any


def calcRSI(  # noqa: N802
    closes: list[float | None],
    options: dict[str, Any] | None = None,
) -> list[dict[str, float | None]]:
    """Compute Wilder's RSI for one or more periods.

    Returns dicts with keys `rsi_{period}` for each requested period.
    Null for bars where insufficient data exists.
    """
    options = options or {}
    periods: list[int] = sorted(options.get("periods") or [6, 12, 24])

    for p in periods:
        if p <= 0:
            raise ValueError(f"period must be > 0, got {p}")

    n = len(closes)
    out: list[dict[str, float | None]] = []
    for _i in range(n):
        row: dict[str, float | None] = {f"rsi_{p}": None for p in periods}
        out.append(row)

    for period in periods:
        avg_gain: float | None = None
        avg_loss: float | None = None
        prev_close: float | None = None
        gains: list[float] = []
        losses: list[float] = []

        for i, value in enumerate(closes):
            if value is None or prev_close is None:
                out[i][f"rsi_{period}"] = None
                prev_close = value
                continue

            change = value - prev_close
            gain = max(change, 0.0)
            loss = max(-change, 0.0)

            if avg_gain is None:
                # Still building the seed window
                gains.append(gain)
                losses.append(loss)
                if len(gains) == period:
                    avg_gain = sum(gains) / period
                    avg_loss = sum(losses) / period
                    out[i][f"rsi_{period}"] = _rsi_from(avg_gain, avg_loss)
            else:
                # Wilder smoothing
                avg_gain = (avg_gain * (period - 1) + gain) / period
                avg_loss = (avg_loss * (period - 1) + loss) / period
                out[i][f"rsi_{period}"] = _rsi_from(avg_gain, avg_loss)

            prev_close = value

    return out


def _rsi_from(avg_gain: float, avg_loss: float) -> float | None:
    if avg_gain == 0 and avg_loss == 0:
        return None
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    rsi = 100.0 - 100.0 / (1.0 + rs)
    return round(rsi, 2)


__all__ = ["calcRSI"]
