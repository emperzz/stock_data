"""
BIAS — Bias Ratio (乖离率).

    BIAS_N = (close - SMA(close, N)) / SMA(close, N) * 100

Expressed as a percentage. Positive = price above its MA, negative = below.
"""

from __future__ import annotations

from .ma import calcSMA
from .types import BIASOptions


def calcBIAS(
    closes: list[float | None],
    options: BIASOptions | None = None,
) -> list[dict[str, float | None]]:
    options = options or {}
    periods: list[int] = sorted(options.get("periods") or [6, 12, 24])

    for p in periods:
        if p <= 0:
            raise ValueError(f"period must be > 0, got {p}")

    # Compute every requested SMA once
    sma_arrays: dict[int, list[float | None]] = {p: calcSMA(closes, p) for p in periods}

    out: list[dict[str, float | None]] = []
    for i in range(len(closes)):
        close = closes[i]
        row: dict[str, float | None] = {}
        for p in periods:
            ma = sma_arrays[p][i]
            if close is None or ma is None or ma == 0:
                row[f"bias_{p}"] = None
            else:
                row[f"bias_{p}"] = round((close - ma) / ma * 100.0, 2)
        out.append(row)

    return out


__all__ = ["calcBIAS"]
