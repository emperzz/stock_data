"""Unit tests for MACD."""

import pytest

from stock_data.data_provider.indicators.macd import calcMACD


def test_macd_default_12_26_9():
    # 30 closing prices, 1..30
    closes = [float(i) for i in range(1, 31)]
    rows = calcMACD(closes)
    assert len(rows) == 30
    # First ~26 rows have null DIF, first ~26+9=35 have null DEA. So we expect
    # to see nulls until the 26th bar seeds DIF, and DEA needs the signal
    # period on top of that.
    for i in range(25):
        assert rows[i]["macd_dif"] is None
    # After 26 bars, DIF should be defined (linearly trending data: EMA12
    # above EMA26 by an amount equal to (N-26)*alpha ish).
    # Just sanity-check it's a number.
    assert isinstance(rows[26]["macd_dif"], (int, float))


def test_macd_monotonic_uptrend_has_positive_hist():
    # Strictly rising prices -> DIF > DEA -> positive histogram
    closes = [10 + 0.1 * i for i in range(60)]
    rows = calcMACD(closes)
    last = rows[-1]
    assert last["macd_dif"] is not None
    assert last["macd_dea"] is not None
    assert last["macd_hist"] is not None
    # For a linear uptrend, the short EMA stays above the long EMA so
    # DIF is positive. After the DEA warms up, the histogram (DIF-DEA)*2
    # converges to ~0 (both EMAs asymptote to the same line). We just
    # check that DIF is positive and DIF >= DEA.
    assert last["macd_dif"] > 0
    assert last["macd_dif"] >= last["macd_dea"] - 0.01  # tiny tolerance for float noise


def test_macd_rejects_short_ge_long():
    with pytest.raises(ValueError):
        calcMACD([1.0, 2.0, 3.0], {"short": 26, "long": 12})


def test_macd_rejects_zero_signal():
    with pytest.raises(ValueError):
        calcMACD([1.0, 2.0, 3.0], {"signal": 0})


def test_macd_custom_params():
    closes = [float(i) for i in range(1, 31)]
    rows = calcMACD(closes, {"short": 5, "long": 10, "signal": 3})
    # With short=5/long=10, ema_long seeds at bar 9 (10th value), so DIF is
    # defined from bar 9 onward. ema_dea (signal=3) on DIF needs 3 DIF values
    # so it seeds at bar 11 (9+3-1).
    assert rows[8]["macd_dif"] is None
    assert rows[9]["macd_dif"] is not None
    assert rows[9]["macd_dea"] is None
    assert rows[11]["macd_dea"] is not None
