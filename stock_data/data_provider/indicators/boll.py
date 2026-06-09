"""
BOLL — Bollinger Bands.

    mid     = SMA(close, period)
    upper   = mid + stdDev * std(close, period)
    lower   = mid - stdDev * std(close, period)
    bandwidth = (upper - lower) / mid * 100  (percent)
"""

from __future__ import annotations

import math
from typing import Any

from .ma import calcSMA


def _stddev(window: list[float], mean: float) -> float:
    """Population standard deviation (not sample). N = len(window)."""
    if not window:
        return 0.0
    variance = sum((v - mean) ** 2 for v in window) / len(window)
    return math.sqrt(variance)


def calcBOLL(  # noqa: N802
    closes: list[float | None],
    options: dict[str, Any] | None = None,
) -> list[dict[str, float | None]]:
    """Compute Bollinger Bands for each bar.

    Returns dicts with keys `boll_mid`, `boll_upper`, `boll_lower`,
    `boll_bandwidth`. Null at bars where the rolling window is not full
    or where the window contains a None.
    """
    options = options or {}
    period: int = int(options.get("period", 20))
    std_dev: float = float(options.get("stdDev", 2.0))

    if period <= 0:
        raise ValueError(f"period must be > 0, got {period}")
    if std_dev <= 0:
        raise ValueError(f"stdDev must be > 0, got {std_dev}")

    mids = calcSMA(closes, period)

    # Rolling window of raw closes for stddev calculation
    out: list[dict[str, float | None]] = []
    window: list[float | None] = []
    for value, mid in zip(closes, mids, strict=True):
        window.append(value)
        if len(window) > period:
            window.pop(0)

        if mid is None or len(window) < period or any(v is None for v in window):
            out.append(
                {
                    "boll_mid": None,
                    "boll_upper": None,
                    "boll_lower": None,
                    "boll_bandwidth": None,
                }
            )
            continue

        # All window values are non-None here
        numeric_window: list[float] = [v for v in window if v is not None]  # type: ignore[misc]
        sd = _stddev(numeric_window, mid)
        upper = mid + std_dev * sd
        lower = mid - std_dev * sd
        bandwidth = (upper - lower) / mid * 100 if mid != 0 else None

        out.append(
            {
                "boll_mid": round(mid, 2),
                "boll_upper": round(upper, 2),
                "boll_lower": round(lower, 2),
                "boll_bandwidth": round(bandwidth, 2) if bandwidth is not None else None,
            }
        )

    return out


__all__ = ["calcBOLL"]
