"""Unit tests for KDJ."""

import pytest

from stock_data.data_provider.indicators.kdj import calcKDJ

from stock_data.data_provider.indicators.kdj import calcKDJ


def _make_bars(closes, opens=None, highs=None, lows=None):
    """Helper: synthesize OHLCV bars with close=given, high/low from a 1% wiggle."""
    bars = []
    for i, c in enumerate(closes):
        o = opens[i] if opens else c - 0.5
        h = highs[i] if highs else c + 1.0
        l = lows[i] if lows else c - 1.0
        bars.append({"open": o, "high": h, "low": l, "close": c, "volume": 1000.0})
    return bars


def test_kdj_seeded_at_50_when_window_not_full():
    closes = [10.0, 10.5, 11.0, 11.5, 12.0]
    bars = _make_bars(closes)
    rows = calcKDJ(bars, {"period": 9})
    # All nulls since we only have 5 bars
    for row in rows:
        assert row["kdj_k"] is None
        assert row["kdj_d"] is None
        assert row["kdj_j"] is None


def test_kdj_k_starts_at_rsv_with_kseed_50():
    # Build 10 bars with steadily rising closes
    closes = [10.0 + i for i in range(10)]
    bars = _make_bars(closes)
    rows = calcKDJ(bars, {"period": 9, "kPeriod": 3, "dPeriod": 3})
    # Bar 8 (the 9th bar) is the first one with a full window
    assert rows[7]["kdj_k"] is None
    assert rows[8]["kdj_k"] is not None
    # All K values should be in [-100, 100] and D in [0, 100] or so
    for row in rows[8:]:
        assert row["kdj_k"] is not None
        assert row["kdj_d"] is not None
        assert -100 <= row["kdj_k"] <= 100


def test_kdj_flat_market_yields_none():
    # All bars truly flat: high == low == close across every bar.
    bars = [
        {"open": 10.0, "high": 10.0, "low": 10.0, "close": 10.0, "volume": 1000.0}
        for _ in range(15)
    ]
    rows = calcKDJ(bars, {"period": 9})
    for row in rows[8:]:
        assert row["kdj_k"] is None
        assert row["kdj_d"] is None
        assert row["kdj_j"] is None


def test_kdj_rejects_zero_period():
    bars = _make_bars([1.0, 2.0, 3.0])
    with pytest.raises(ValueError):
        calcKDJ(bars, {"period": 0})
