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

from .types import wilder_smooth


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
        # Build gain / loss per-bar series. None for the first bar (no
        # prev close) and any bar where the close is None.
        gains: list[float | None] = []
        losses: list[float | None] = []
        prev_close: float | None = None
        for value in closes:
            if value is None or prev_close is None:
                gains.append(None)
                losses.append(None)
            else:
                change = value - prev_close
                gains.append(max(change, 0.0))
                losses.append(max(-change, 0.0))
            prev_close = value

        avg_gain = wilder_smooth(gains, period)
        avg_loss = wilder_smooth(losses, period)

        for i in range(n):
            out[i][f"rsi_{period}"] = _rsi_from(avg_gain[i], avg_loss[i])

    return out


def _rsi_from(avg_gain: float | None, avg_loss: float | None) -> float | None:
    if avg_gain is None or avg_loss is None:
        return None
    if avg_gain == 0 and avg_loss == 0:
        return None
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    rsi = 100.0 - 100.0 / (1.0 + rs)
    return round(rsi, 2)


__all__ = ["calcRSI"]
