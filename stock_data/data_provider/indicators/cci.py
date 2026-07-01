"""
CCI — Commodity Channel Index.

    TP     = (high + low + close) / 3
    MA_TP  = SMA(TP, period)
    MD     = mean(|TP[i] - MA_TP|) for i in window  (mean deviation)
    CCI    = (TP - MA_TP) / (0.015 * MD)

Default period = 14. Needs OHLC.
"""

from __future__ import annotations

from typing import Any

from .ma import calcSMA
from .types import MABatch, OHLCV


def calcCCI(  # noqa: N802
    bars: list[OHLCV],
    options: dict[str, Any] | None = None,
    *,
    batch: MABatch | None = None,
) -> list[dict[str, float | None]]:
    options = options or {}
    period: int = int(options.get("period", 14))
    if period <= 0:
        raise ValueError(f"period must be > 0, got {period}")

    tp: list[float | None] = []
    for bar in bars:
        h = bar.get("high")
        low = bar.get("low")
        c = bar.get("close")
        if h is None or low is None or c is None:
            tp.append(None)
        else:
            tp.append((h + low + c) / 3.0)

    # calcSMA is the canonical indicator-layer SMA — O(n) rolling sum,
    # None-aware (None still occupies its slot in the rolling window),
    # and shared with MA / BOLL / BIAS. The optional `batch` hook lets
    # the orchestrator reuse an MA already computed by another indicator
    # in the same compute() call.
    ma_tp = batch.sma(tp, period) if batch is not None else calcSMA(tp, period)

    out: list[dict[str, float | None]] = []
    for i, bar in enumerate(bars):
        ma = ma_tp[i]
        if ma is None or bar.get("high") is None or bar.get("low") is None:
            out.append({"cci": None})
            continue

        # Mean absolute deviation over the last `period` TPs
        window = [v for v in tp[max(0, i - period + 1) : i + 1] if v is not None]
        if len(window) < period:
            out.append({"cci": None})
            continue
        md = sum(abs(v - ma) for v in window) / period
        if md == 0:
            out.append({"cci": None})
            continue
        cci = (tp[i] - ma) / (0.015 * md)
        out.append({"cci": round(cci, 2)})

    return out


__all__ = ["calcCCI"]
