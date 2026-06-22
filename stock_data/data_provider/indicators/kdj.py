"""
KDJ — stochastic oscillator with a J-line extrapolation.

    RSV = 100 * (close - lowest_low_N) / (highest_high_N - lowest_low_N)
    K   = (kPeriod - 1) / kPeriod * prev_K + 1 / kPeriod * RSV
    D   = (dPeriod - 1) / dPeriod * prev_D + 1 / dPeriod * K
    J   = 3 * K - 2 * D

Standard defaults: period=9, kPeriod=3, dPeriod=3. K and D are seeded at 50.

KDJ needs OHLC — specifically high and low. The function signature takes
a list of OHLCV dicts (same shape as `types.OHLCV`) so we have access to
all four prices. Close is the only one that matters for the recursion.
"""

from __future__ import annotations

from typing import Any

from .types import OHLCV, round2

_round2 = round2  # local alias for backward compat


def calcKDJ(  # noqa: N802
    bars: list[OHLCV],
    options: dict[str, Any] | None = None,
) -> list[dict[str, float | None]]:
    """Compute KDJ for each bar.

    Returns dicts with keys `kdj_k`, `kdj_d`, `kdj_j`. Null at bars where
    the lookback window is not full or the highest/lowest range collapses
    to zero.
    """
    options = options or {}
    period: int = int(options.get("period", 9))
    k_period: int = int(options.get("kPeriod", 3))
    d_period: int = int(options.get("dPeriod", 3))

    if period <= 0 or k_period <= 0 or d_period <= 0:
        raise ValueError("period, kPeriod, dPeriod must all be > 0")

    out: list[dict[str, float | None]] = []
    k = 50.0
    d = 50.0
    window: list[OHLCV] = []

    for bar in bars:
        window.append(bar)
        if len(window) > period:
            window.pop(0)

        if len(window) < period:
            out.append({"kdj_k": None, "kdj_d": None, "kdj_j": None})
            continue

        high_n = -float("inf")
        low_n = float("inf")
        valid = True
        for w in window:
            h = w.get("high")
            low = w.get("low")
            if h is None or low is None:
                valid = False
                break
            high_n = max(high_n, h)
            low_n = min(low_n, low)

        close = bar.get("close")
        if not valid or close is None or high_n == low_n:
            out.append({"kdj_k": None, "kdj_d": None, "kdj_j": None})
            continue

        rsv = ((close - low_n) / (high_n - low_n)) * 100.0
        k = (k_period - 1) / k_period * k + (1 / k_period) * rsv
        d = (d_period - 1) / d_period * d + (1 / d_period) * k
        j = 3 * k - 2 * d

        out.append({"kdj_k": _round2(k), "kdj_d": _round2(d), "kdj_j": _round2(j)})

    return out


__all__ = ["calcKDJ"]
