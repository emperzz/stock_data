"""
Moving Average indicators (SMA / EMA / WMA).

These are the building blocks for MACD, BOLL and KC, so they are implemented
first and the higher-level indicators import from here.

Conventions:
    - Inputs are 0-indexed sequences of `float | None`. None represents
      "missing/unknown" (e.g. no data for that bar, or a placeholder).
    - Outputs are also 0-indexed sequences aligned to the input. None
      means "indicator is not yet defined at this bar" — never 0, never
      a forward-fill of the previous value.
    - All outputs are rounded to 2 decimals. We do not strip trailing
      zeros (e.g. 3.10 stays "3.1" in JSON); callers can format as they
      wish.

A note on lookback:
    - SMA / WMA need `period` valid closes before producing a value.
    - EMA also needs `period` valid closes for its seed; once seeded it
      can continue past `period` bars using its recursive formula. The
      stock-sdk convention is the same: null before the seed, then
      filled from the seed onward.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .types import MAType, round2

if TYPE_CHECKING:
    from .types import MABatch

# ---------- low-level helpers ----------


def _valid(value: float | None) -> bool:
    """A value is 'valid' if it is not None and not NaN."""
    if value is None:
        return False
    return value == value  # NaN check


# ---------- SMA ----------


def calcSMA(  # noqa: N802
    data: list[float | None],
    period: int,
) -> list[float | None]:
    """Simple Moving Average over `period` bars.

    Returns None for bars where fewer than `period` valid closes are
    available in the lookback window.
    """
    if period <= 0:
        raise ValueError(f"period must be > 0, got {period}")

    result: list[float | None] = []
    rolling_sum = 0.0
    valid_count = 0
    # We keep a sliding window of values to know how much to subtract
    # when a bar leaves the window. None slots contribute nothing.
    window: list[float | None] = []

    for value in data:
        window.append(value)
        if _valid(value):
            rolling_sum += value  # type: ignore[operator]
            valid_count += 1

        if len(window) > period:
            popped = window.pop(0)
            if _valid(popped):
                rolling_sum -= popped  # type: ignore[operator]
                valid_count -= 1

        if valid_count == period:
            result.append(round2(rolling_sum / period))
        else:
            result.append(None)

    return result


# ---------- EMA ----------


def calcEMA(  # noqa: N802
    data: list[float | None],
    period: int,
) -> list[float | None]:
    """Exponential Moving Average over `period` bars.

    Seed: the first valid EMA is the SMA of the first `period` valid
    closes. Subsequent values use the standard recursive formula:

        EMA[i] = alpha * close[i] + (1 - alpha) * EMA[i - 1]
        alpha = 2 / (period + 1)

    A bar with a None close is skipped — the previous EMA is propagated
    forward unchanged, matching stock-sdk's behavior.
    """
    if period <= 0:
        raise ValueError(f"period must be > 0, got {period}")

    alpha = 2.0 / (period + 1.0)
    result: list[float | None] = []
    ema: float | None = None
    seeded = False
    seed_window: list[float] = []

    for value in data:
        if not seeded:
            # Accumulate until we have `period` valid closes for the seed
            if _valid(value):
                seed_window.append(value)  # type: ignore[arg-type]
            if len(seed_window) == period:
                ema = sum(seed_window) / period
                seeded = True
                result.append(round2(ema))
            else:
                result.append(None)
            continue

        # Seeded — apply recursive formula
        if not _valid(value):
            result.append(round2(ema) if ema is not None else None)
            continue

        ema = alpha * value + (1.0 - alpha) * ema  # type: ignore[operator]
        result.append(round2(ema))

    return result


# ---------- WMA ----------


def calcWMA(  # noqa: N802
    data: list[float | None],
    period: int,
) -> list[float | None]:
    """Linearly-Weighted Moving Average.

    Weights increase arithmetically: bar at offset -period+1 gets weight 1,
    bar at offset 0 (the current bar) gets weight `period`. The denominator
    is the triangular number period * (period + 1) / 2.
    """
    if period <= 0:
        raise ValueError(f"period must be > 0, got {period}")

    weights = list(range(1, period + 1))  # [1, 2, ..., period]
    weight_sum = sum(weights)  # period * (period + 1) / 2
    result: list[float | None] = []
    window: list[float | None] = []

    for value in data:
        window.append(value)
        if len(window) > period:
            window.pop(0)

        if len(window) < period:
            result.append(None)
            continue

        # All `period` slots must be valid to emit a value.
        if not all(_valid(v) for v in window):
            result.append(None)
            continue

        weighted = sum(w * v for w, v in zip(weights, window, strict=True))  # type: ignore[arg-type]
        result.append(round2(weighted / weight_sum))

    return result


# ---------- bulk calcMA (per-bar dict-of-columns output) ----------


def calcMA(  # noqa: N802
    closes: list[float | None],
    options: dict[str, Any] | None = None,
    *,
    batch: MABatch | None = None,
) -> list[dict[str, float | None]]:
    """Compute one or more moving averages in a single pass.

    Returns a list of dicts aligned to `closes`. Each dict has keys
    `ma{period}` (e.g. `ma5`, `ma20`). The `type` option (sma/ema/wma)
    applies uniformly to all requested periods — mixing types in one
    call is not supported (call calcMA twice if you need to mix).

    For callers that want raw per-period arrays (e.g. to index into a
    specific period's array from another pass), use :func:`calcMA_arrays`
    instead.

    When ``batch`` is provided, each per-period MA goes through the
    batch's cache, so a sibling indicator (e.g. ``BOLL``) asking for
    the same ``SMA(20)`` in the same ``compute()`` call reuses the
    already-computed array instead of recomputing it.
    """
    options = options or {}
    periods: list[int] = list(options.get("periods") or [5, 10, 20, 30, 60, 120, 250])
    ma_type: MAType | str = options.get("type", MAType.SMA)

    if isinstance(ma_type, str):
        ma_type = MAType(ma_type)

    if ma_type == MAType.SMA:
        dispatch = batch.sma if batch is not None else calcSMA
    elif ma_type == MAType.EMA:
        dispatch = batch.ema if batch is not None else calcEMA
    elif ma_type == MAType.WMA:
        dispatch = batch.wma if batch is not None else calcWMA
    else:
        raise ValueError(f"unsupported MA type: {ma_type}")

    columns: dict[str, list[float | None]] = {}
    for period in periods:
        if period <= 0:
            raise ValueError(f"period must be > 0, got {period}")
        columns[f"ma{period}"] = dispatch(closes, period)

    n = len(closes)
    out: list[dict[str, float | None]] = []
    for i in range(n):
        row: dict[str, float | None] = {}
        for period in periods:
            row[f"ma{period}"] = columns[f"ma{period}"][i]
        out.append(row)
    return out


# ---------- bulk calcMA_arrays (per-period array output) ----------


def calcMA_arrays(  # noqa: N802
    closes: list[float | None],
    periods: list[int],
    ma_type: MAType | str = MAType.SMA,
) -> dict[int, list[float | None]]:
    """Compute one or more moving averages in a single dispatch; return arrays.

    Returns ``{period: array}`` keyed by period. Useful for callers that
    need to keep the per-period arrays around (e.g. ``calcBIAS`` indexes
    into ``sma_arrays[p][i]`` for each bar), as opposed to :func:`calcMA`
    which transposes to a per-bar dict-of-columns for direct output.

    All periods share the same ``ma_type``. Mixing types in one call is
    not supported (call twice if you need to mix).
    """
    if isinstance(ma_type, str):
        ma_type = MAType(ma_type)

    if ma_type == MAType.SMA:
        calc_fn = calcSMA
    elif ma_type == MAType.EMA:
        calc_fn = calcEMA
    elif ma_type == MAType.WMA:
        calc_fn = calcWMA
    else:
        raise ValueError(f"unsupported MA type: {ma_type}")

    for p in periods:
        if p <= 0:
            raise ValueError(f"period must be > 0, got {p}")

    return {p: calc_fn(closes, p) for p in periods}


__all__ = ["calcSMA", "calcEMA", "calcWMA", "calcMA", "calcMA_arrays"]
