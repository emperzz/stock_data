"""
WR — Williams %R.

    WR = (highest_high_N - close) / (highest_high_N - lowest_low_N) * -100

Range: [-100, 0]. Values near 0 = overbought, values near -100 = oversold.
Needs OHLC.
"""

from __future__ import annotations

from typing import Any

from .types import OHLCV, round2

_round2 = round2  # local alias for backward compat


def calcWR(  # noqa: N802
    bars: list[OHLCV],
    options: dict[str, Any] | None = None,
) -> list[dict[str, float | None]]:
    options = options or {}
    periods: list[int] = sorted(options.get("periods") or [6, 10])

    for p in periods:
        if p <= 0:
            raise ValueError(f"period must be > 0, got {p}")

    out: list[dict[str, float | None]] = []
    window: list[OHLCV] = []

    for bar in bars:
        window.append(bar)
        row: dict[str, float | None] = {f"wr_{p}": None for p in periods}
        out.append(row)

        if len(window) > max(periods):
            window.pop(0)

        if len(window) < max(periods):
            continue  # leave the row as all None

        for period in periods:
            if len(window) < period:
                continue
            slice_ = window[-period:]
            high_n = -float("inf")
            low_n = float("inf")
            valid = True
            for w in slice_:
                h = w.get("high")
                low = w.get("low")
                if h is None or low is None:
                    valid = False
                    break
                high_n = max(high_n, h)
                low_n = min(low_n, low)

            close = bar.get("close")
            if not valid or close is None or high_n == low_n:
                continue

            wr = (high_n - close) / (high_n - low_n) * -100.0
            row[f"wr_{period}"] = _round2(wr)

    return out


__all__ = ["calcWR"]
