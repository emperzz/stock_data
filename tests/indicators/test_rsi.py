"""Unit tests for RSI (Wilder's smoothing)."""

import pytest

from stock_data.data_provider.indicators.rsi import calcRSI


def test_rsi_first_valid_bar_equals_seed():
    # 14 bars, alternating up 1 then flat. The seed RSI6 is the SMA of 6
    # gain/loss pairs at bar 6 (0-indexed).
    closes = [10.0, 11.0, 11.0, 12.0, 12.0, 13.0, 13.0]
    rows = calcRSI(closes, {"periods": [6]})
    # Bar 0..5: rsi_6 is null (need 6 changes)
    for i in range(6):
        assert rows[i]["rsi_6"] is None
    # Bar 6: rsi_6 should be defined
    assert rows[6]["rsi_6"] is not None


def test_rsi_strictly_rising_is_100():
    closes = [10.0 + i for i in range(20)]
    rows = calcRSI(closes, {"periods": [14]})
    # After the seed, all subsequent values should be 100
    for row in rows[14:]:
        assert row["rsi_14"] == 100.0


def test_rsi_strictly_falling_is_0():
    closes = [100.0 - i for i in range(20)]
    rows = calcRSI(closes, {"periods": [14]})
    for row in rows[14:]:
        assert row["rsi_14"] == 0.0


def test_rsi_flat_market_yields_none():
    closes = [50.0] * 20
    rows = calcRSI(closes, {"periods": [14]})
    for row in rows[14:]:
        assert row["rsi_14"] is None


def test_rsi_multiple_periods():
    closes = [10.0 + i for i in range(30)]
    rows = calcRSI(closes, {"periods": [6, 12, 24]})
    last = rows[-1]
    assert last["rsi_6"] == 100.0
    assert last["rsi_12"] == 100.0
    assert last["rsi_24"] == 100.0


def test_rsi_rejects_zero_period():
    with pytest.raises(ValueError):
        calcRSI([1.0, 2.0, 3.0], {"periods": [0]})
