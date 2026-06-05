"""Unit tests for Bollinger Bands."""

import math

import pytest

from stock_data.data_provider.indicators.boll import calcBOLL


def test_boll_basic():
    closes = [float(i) for i in range(1, 26)]  # 25 bars, period=20
    rows = calcBOLL(closes, {"period": 20, "stdDev": 2.0})
    assert len(rows) == 25
    # First 19 are null
    for i in range(19):
        assert rows[i]["boll_mid"] is None
    # Bar 19: SMA(1..20) = 10.5
    assert rows[19]["boll_mid"] == 10.5
    # Bar 19: std(1..20) = sqrt(33.25) ≈ 5.77, upper = 10.5 + 2*5.77 = 22.04
    expected_std = math.sqrt(sum((i - 10.5) ** 2 for i in range(1, 21)) / 20)
    assert math.isclose(rows[19]["boll_upper"], 10.5 + 2 * expected_std, rel_tol=0.01)
    # Bandwidth = (upper - lower) / mid * 100
    assert rows[19]["boll_bandwidth"] is not None


def test_boll_bandwidth_is_percent():
    # A noise-free linear series has a very large bandwidth because the std
    # relative to the mean is huge; use a bounded oscillating series instead.
    closes = [10.0 + (0.5 if i % 2 == 0 else -0.5) for i in range(40)]
    rows = calcBOLL(closes)
    last = rows[-1]
    assert last["boll_bandwidth"] is not None
    assert last["boll_bandwidth"] > 0
    assert last["boll_bandwidth"] < 200  # sanity bound; oscillates so this is loose


def test_boll_with_nones():
    closes = [float(i) for i in range(1, 21)]
    closes[5] = None
    rows = calcBOLL(closes, {"period": 20})
    # The None in the window suppresses the output for every bar at or after 5
    for i in range(5, len(rows)):
        assert rows[i]["boll_mid"] is None


def test_boll_custom_stddev():
    closes = [10.0] * 20  # constant -> std=0 -> upper==lower==mid
    rows = calcBOLL(closes, {"period": 20, "stdDev": 1.5})
    last = rows[-1]
    assert last["boll_mid"] == 10.0
    assert last["boll_upper"] == 10.0
    assert last["boll_lower"] == 10.0


def test_boll_rejects_zero_period():
    with pytest.raises(ValueError):
        calcBOLL([1.0, 2.0, 3.0], {"period": 0})
