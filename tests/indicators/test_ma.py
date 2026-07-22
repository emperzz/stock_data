"""Unit tests for the moving-average family (SMA / EMA / WMA)."""

import pytest

from stock_data.data_provider.indicators.ma import calcEMA, calcMA, calcSMA, calcWMA

# ---------- SMA ----------


def test_sma_basic():
    closes = [1, 2, 3, 4, 5, 6, 7, 8]
    result = calcSMA(closes, 5)
    # First 4 bars are null
    assert result[:4] == [None, None, None, None]
    # SMA5 of [1..5] = 3.0
    assert result[4] == 3.0
    # SMA5 of [2..6] = 4.0
    assert result[5] == 4.0
    # SMA5 of [4..8] = 6.0
    assert result[7] == 6.0


def test_sma_with_nones_in_input():
    closes = [10.0, None, 12.0, 13.0, 14.0]
    result = calcSMA(closes, 3)
    # Window moves through Nones; only emit when we have 3 valid closes.
    # Index 0: window=[10]   -> None
    # Index 1: window=[10,None] -> None
    # Index 2: window=[10,None,12] valid_count=2 != 3 -> None
    # Index 3: window=[None,12,13] valid_count=2 -> None
    # Index 4: window=[12,13,14] valid_count=3 -> (12+13+14)/3 = 13.0
    assert result == [None, None, None, None, 13.0]


def test_sma_rejects_zero_period():
    with pytest.raises(ValueError):
        calcSMA([1.0, 2.0, 3.0], 0)


# ---------- EMA ----------


def test_ema_basic():
    closes = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    result = calcEMA(closes, 3)
    # First 2 bars are null, third seeds with SMA
    assert result[0] is None
    assert result[1] is None
    # Index 2: seed = mean(1,2,3) = 2.0
    assert result[2] == 2.0
    # Index 3: alpha=2/4=0.5, EMA = 0.5*4 + 0.5*2.0 = 3.0
    assert result[3] == 3.0
    # Index 4: 0.5*5 + 0.5*3.0 = 4.0
    assert result[4] == 4.0


def test_ema_propagates_through_none():
    closes = [1.0, 2.0, 3.0, None, 5.0]
    result = calcEMA(closes, 3)
    # Index 0..1: null
    # Index 2: seed = 2.0
    assert result[2] == 2.0
    # Index 3: None close -> propagate previous EMA (2.0)
    assert result[3] == 2.0
    # Index 4: 0.5*5 + 0.5*2.0 = 3.5
    assert result[4] == 3.5


# ---------- WMA ----------


def test_wma_basic():
    closes = [1, 2, 3, 4, 5]
    result = calcWMA(closes, 3)
    # weights = [1,2,3], weight_sum = 6
    # Index 0..1: null
    # Index 2: (1*1 + 2*2 + 3*3)/6 = 14/6 = 2.33
    assert result[2] == 2.33
    # Index 3: (1*2 + 2*3 + 3*4)/6 = 20/6 = 3.33
    assert result[3] == 3.33
    # Index 4: (1*3 + 2*4 + 3*5)/6 = 26/6 = 4.33
    assert result[4] == 4.33


# ---------- bulk calcMA ----------


def test_calcma_default_periods():
    closes = list(range(1, 31))
    rows = calcMA(closes)
    # 30 bars is enough for ma5/10/20 but not ma30 (needs 30 valid bars - first is null)
    last = rows[-1]
    assert "ma5" in last and "ma10" in last and "ma20" in last
    assert "ma30" in last
    assert "ma60" in last
    # ma30 of [1..30] = 15.5
    assert last["ma30"] == 15.5
    # ma60 should still be None (only 30 bars)
    assert last["ma60"] is None


def test_calcma_ema_type():
    closes = [1, 2, 3, 4, 5, 6, 7, 8]
    rows = calcMA(closes, {"periods": [3], "type": "ema"})
    # 3-period EMA on [1..8]
    # Index 0..1: null
    # Index 2: seed = (1+2+3)/3 = 2.0
    assert rows[2]["ma3"] == 2.0
    # Index 3: alpha=0.5, 0.5*4 + 0.5*2 = 3.0
    assert rows[3]["ma3"] == 3.0


def test_calcma_wma_type():
    closes = [1, 2, 3, 4, 5]
    rows = calcMA(closes, {"periods": [3], "type": "wma"})
    # Same as the per-function WMA test
    assert rows[2]["ma3"] == 2.33
    assert rows[4]["ma3"] == 4.33
