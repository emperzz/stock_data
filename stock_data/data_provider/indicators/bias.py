"""
BIAS — Bias Ratio (乖离率).

    BIAS_N = (close - SMA(close, N)) / SMA(close, N) * 100

Expressed as a percentage. Positive = price above its MA, negative = below.
"""

from __future__ import annotations

from typing import Any

from .ma import calcMA_arrays
from .types import MAType, MABatch


def calcBIAS(  # noqa: N802
    closes: list[float | None],
    options: dict[str, Any] | None = None,
    *,
    batch: MABatch | None = None,
) -> list[dict[str, float | None]]:
    options = options or {}
    periods: list[int] = sorted(options.get("periods") or [6, 12, 24])

    for p in periods:
        if p <= 0:
            raise ValueError(f"period must be > 0, got {p}")

    # Resolve every requested SMA once. When `batch` is provided by the
    # orchestrator, each call shares the cache with sibling indicators
    # (e.g. a user asking for `ma + bias` won't recompute SMA(6/12/24)).
    if batch is not None:
        sma_arrays: dict[int, list[float | None]] = {
            p: batch.sma(closes, p) for p in periods
        }
    else:
        sma_arrays = calcMA_arrays(closes, periods, MAType.SMA)

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
