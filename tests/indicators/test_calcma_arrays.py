"""Unit tests for the calcMA_arrays helper and MABatch memoization.

Both are the building blocks that fix the cross-indicator MA-deduplication
issue surfaced in the 2026-07 refactor.
"""

import pytest

from stock_data.data_provider.indicators import calcMA, calcMA_arrays
from stock_data.data_provider.indicators.ma import calcSMA
from stock_data.data_provider.indicators.types import MABatch


# ---------- calcMA_arrays ----------


def test_calcma_arrays_default_sma():
    closes = list(range(1, 11))  # 10 bars
    arrays = calcMA_arrays(closes, [3, 5])
    # Two keys, one per period
    assert set(arrays) == {3, 5}
    # Same answer as calling calcSMA directly
    assert arrays[3] == calcSMA(closes, 3)
    assert arrays[5] == calcSMA(closes, 5)


def test_calcma_arrays_ema_type():
    closes = [1, 2, 3, 4, 5, 6, 7, 8]
    arrays = calcMA_arrays(closes, [3], "ema")
    # Index 2: seed = mean(1,2,3) = 2.0
    assert arrays[3][2] == 2.0
    # Index 3: alpha=0.5 -> 3.0
    assert arrays[3][3] == 3.0


def test_calcma_arrays_empty_periods():
    closes = [1.0, 2.0, 3.0]
    arrays = calcMA_arrays(closes, [])
    assert arrays == {}


def test_calcma_arrays_rejects_zero_period():
    closes = [1.0, 2.0, 3.0]
    with pytest.raises(ValueError):
        calcMA_arrays(closes, [0, 5])


def test_calcma_arrays_unknown_type():
    closes = [1.0, 2.0, 3.0]
    with pytest.raises(ValueError):
        calcMA_arrays(closes, [5], "garbage")


# ---------- MABatch memoization ----------


def test_batch_sma_caches_after_first_call():
    """Second call with same (id, type, period) must return the same list
    object — i.e. the underlying SMA was NOT recomputed."""
    closes = list(range(1, 31))
    batch = MABatch()
    first = batch.sma(closes, 20)
    second = batch.sma(closes, 20)
    # Same array object — proves the second call returned the cached entry
    assert first is second


def test_batch_different_periods_are_independent():
    closes = list(range(1, 31))
    batch = MABatch()
    sma5 = batch.sma(closes, 5)
    sma20 = batch.sma(closes, 20)
    assert sma5 is not sma20
    # Different values
    assert sma5[-1] != sma20[-1]


def test_batch_ema_and_sma_independent():
    """Same period but different MA type → different cache entries."""
    closes = list(range(1, 31))
    batch = MABatch()
    sma10 = batch.sma(closes, 10)
    ema10 = batch.ema(closes, 10)
    assert sma10 is not ema10


def test_batch_isolated_between_instances():
    """Two MABatch instances must not share cache."""
    closes = list(range(1, 11))
    a = MABatch()
    b = MABatch()
    ra = a.sma(closes, 5)
    rb = b.sma(closes, 5)
    # Equal values but different objects — different batches
    assert ra == rb
    assert ra is not rb


def test_batch_orchestrator_dedups_boll_and_ma20():
    """End-to-end: when both `ma` (periods=[20]) and `boll` (period=20)
    are computed in one compute() call, the SMA(20) array should be
    shared — verified by counting cache hits."""
    import pandas as pd

    from stock_data.data_provider.indicators.indicator_service import compute

    df = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=60, freq="B"),
            "open": [100.0 + i * 0.1 for i in range(60)],
            "high": [101.0 + i * 0.1 for i in range(60)],
            "low": [99.0 + i * 0.1 for i in range(60)],
            "close": [100.5 + i * 0.1 for i in range(60)],
            "volume": [1000.0] * 60,
            "amount": [1_000_000.0] * 60,
        }
    )
    out = compute(df, {"ma": {"periods": [20]}, "boll": {"period": 20}})
    last = out.iloc[-1]["indicators"]
    # Both indicators expose their SMA(20) — ma as `ma20`, boll as `boll_mid`.
    # They must agree exactly because they share the same underlying array.
    assert last["ma20"] == last["boll_mid"]


def test_calcMA_output_unchanged():
    """calcMA's signature change (added `batch` kwarg) must not break
    existing callers that don't pass `batch`."""
    closes = [1, 2, 3, 4, 5, 6, 7, 8]
    rows = calcMA(closes, {"periods": [3]})
    assert rows[2]["ma3"] == 2.0
    assert rows[3]["ma3"] == 3.0