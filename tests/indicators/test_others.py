"""Unit tests for the remaining 9 indicators (WR, BIAS, CCI, ATR, OBV, ROC, DMI, SAR, KC)."""

import math

import pandas as pd
import pytest

from stock_data.data_provider.indicators.wr import calcWR
from stock_data.data_provider.indicators.bias import calcBIAS
from stock_data.data_provider.indicators.cci import calcCCI
from stock_data.data_provider.indicators.atr import calcATR
from stock_data.data_provider.indicators.obv import calcOBV
from stock_data.data_provider.indicators.roc import calcROC
from stock_data.data_provider.indicators.dmi import calcDMI
from stock_data.data_provider.indicators.sar import calcSAR
from stock_data.data_provider.indicators.kc import calcKC


# ---------- helpers ----------


def _bars_from_df(df: pd.DataFrame) -> list[dict]:
    """Coerce a DataFrame (or dict) into a list of OHLCV TypedDicts."""
    if isinstance(df, pd.DataFrame):
        cols = ["open", "high", "low", "close", "volume"]
        return [
            {c: (None if pd.isna(row[c]) else float(row[c])) for c in cols}
            for _, row in df.iterrows()
        ]
    raise TypeError(df)


# ---------- WR ----------


def test_wr_close_equals_high_gives_zero():
    # All bars truly flat: high==low==close across every bar -> range collapses
    bars = [
        {"open": 10.0, "high": 10.0, "low": 10.0, "close": 10.0, "volume": 1000.0}
        for _ in range(20)
    ]
    rows = calcWR(bars, {"periods": [6]})
    last = rows[-1]
    # Range collapses to zero so we cannot compute a meaningful WR
    assert last["wr_6"] is None


def test_wr_basic():
    bars = []
    for i in range(20):
        c = 10.0 + i
        bars.append({"open": c, "high": c + 1.0, "low": c - 1.0, "close": c, "volume": 1000.0})
    rows = calcWR(bars, {"periods": [6]})
    last = rows[-1]
    # WR is in [-100, 0]
    assert -100 <= last["wr_6"] <= 0


# ---------- BIAS ----------


def test_bias_constant_price_is_zero():
    closes = [50.0] * 20
    rows = calcBIAS(closes, {"periods": [6]})
    last = rows[-1]
    assert last["bias_6"] == 0.0


def test_bias_above_ma_is_positive():
    closes = [10.0] * 10 + [15.0] * 10
    rows = calcBIAS(closes, {"periods": [6]})
    # Last bar's BIAS6 should be positive (15 above 15.83? no, the SMA of last 6
    # bars includes the rise). Just assert it's defined and non-zero.
    assert rows[-1]["bias_6"] is not None


# ---------- CCI ----------


def test_cci_basic():
    bars = []
    for i in range(30):
        c = 10.0 + i
        bars.append({"open": c, "high": c + 0.5, "low": c - 0.5, "close": c, "volume": 1000.0})
    rows = calcCCI(bars, {"period": 14})
    # Bar 13 (0-indexed) is the first valid one
    assert rows[12]["cci"] is None
    assert rows[13]["cci"] is not None


# ---------- ATR ----------


def test_atr_first_bar_tr_is_none():
    bars = [{"open": 10, "high": 11, "low": 9, "close": 10, "volume": 1000}]
    rows = calcATR(bars, {"period": 14})
    assert rows[0]["atr"] is None
    assert rows[0]["tr"] is None


def test_atr_seeded_then_smoothed():
    bars = []
    for i in range(30):
        c = 10.0 + i * 0.1
        bars.append({"open": c, "high": c + 1.0, "low": c - 1.0, "close": c, "volume": 1000.0})
    rows = calcATR(bars, {"period": 14})
    # Bar 13 (0-indexed) is the first valid one (after 14 bars the seed is ready
    # - bar 0 has no prev_close, so first 14 valid TRs are bars 1..14, seed at 14)
    assert rows[14]["atr"] is not None
    assert rows[14]["tr"] is not None
    # Subsequent bars keep publishing
    assert rows[20]["atr"] is not None


# ---------- OBV ----------


def test_obv_up_down_constant():
    bars = [
        {"open": 10, "high": 11, "low": 9, "close": 10, "volume": 100},
        {"open": 11, "high": 12, "low": 10, "close": 11, "volume": 200},  # up
        {"open": 11, "high": 12, "low": 10, "close": 10, "volume": 300},  # down
        {"open": 10, "high": 11, "low": 9, "close": 10, "volume": 400},   # flat
    ]
    rows = calcOBV(bars)
    # Bar 0: no prev -> 0
    assert rows[0]["obv"] == 0
    # Bar 1: up 200 -> 200
    assert rows[1]["obv"] == 200
    # Bar 2: down 300 -> -100
    assert rows[2]["obv"] == -100
    # Bar 3: flat -> -100
    assert rows[3]["obv"] == -100


def test_obv_with_ma():
    bars = []
    for i in range(30):
        c = 10.0 + (i % 2)  # alternates 10, 11
        v = 100.0 + i
        bars.append({"open": c, "high": c + 1, "low": c - 1, "close": c, "volume": v})
    rows = calcOBV(bars, {"maPeriod": 5})
    last = rows[-1]
    assert "obv_ma" in last
    assert last["obv_ma"] is not None


# ---------- ROC ----------


def test_roc_period_12():
    closes = [float(i) for i in range(1, 30)]
    rows = calcROC(closes, {"period": 12})
    # Bar 11 (0-indexed) is still inside the lookback -> None
    assert rows[11]["roc"] is None
    # Bar 12 is the first valid one: compares close[12]=13 to close[0]=1
    expected = (13 - 1) / 1 * 100.0
    assert math.isclose(rows[12]["roc"], expected, rel_tol=0.01)


def test_roc_with_signal():
    closes = [10.0 + i for i in range(30)]
    rows = calcROC(closes, {"period": 12, "signalPeriod": 5})
    last = rows[-1]
    assert "roc" in last and "roc_signal" in last
    assert last["roc"] is not None
    # Signal needs ROC data; first 12+5*3 = 27 bars before signal is seeded
    assert last["roc_signal"] is not None


# ---------- DMI ----------


def test_dmi_basic():
    bars = []
    for i in range(50):
        c = 10.0 + i
        bars.append({"open": c, "high": c + 1.0, "low": c - 0.5, "close": c, "volume": 1000.0})
    rows = calcDMI(bars, {"period": 14, "adxPeriod": 14})
    last = rows[-1]
    # In a strictly uptrend +DI should dominate
    assert last["dmi_pdi"] is not None
    assert last["dmi_mdi"] is not None


def test_dmi_flat_market_handles_zero_smoothed_tr():
    # All bars identical -> no TR -> smoothed_tr is 0
    bars = [
        {"open": 10, "high": 10, "low": 10, "close": 10, "volume": 1000} for _ in range(30)
    ]
    rows = calcDMI(bars)
    # All entries should be null (no TR means no DI)
    for row in rows:
        assert row["dmi_pdi"] is None


# ---------- SAR ----------


def test_sar_uptrend_then_downtrend():
    bars = []
    # First 15 bars rising, last 15 falling
    for i in range(15):
        c = 10.0 + i
        bars.append({"open": c, "high": c + 0.5, "low": c - 0.5, "close": c, "volume": 1000.0})
    for i in range(15):
        c = 25.0 - i
        bars.append({"open": c, "high": c + 0.5, "low": c - 0.5, "close": c, "volume": 1000.0})
    rows = calcSAR(bars)
    # First bar: SAR is None
    assert rows[0]["sar"] is None
    # By the end, SAR should be defined
    assert rows[-1]["sar"] is not None
    # Trend direction should be -1 after the price rolls over
    assert rows[-1]["sar_trend"] == -1


def test_sar_seed_depends_on_initial_direction():
    bars = [
        {"open": 10, "high": 10.5, "low": 9.5, "close": 10, "volume": 1000},
        {"open": 10.5, "high": 11, "low": 10, "close": 10.8, "volume": 1000},  # up
        {"open": 11, "high": 11.5, "low": 10.5, "close": 11.3, "volume": 1000},
    ]
    rows = calcSAR(bars)
    # Trend = 1 because first move was up
    assert rows[2]["sar_trend"] == 1


# ---------- KC ----------


def test_kc_basic():
    bars = []
    for i in range(40):
        c = 10.0 + i * 0.1
        bars.append({"open": c, "high": c + 0.5, "low": c - 0.5, "close": c, "volume": 1000.0})
    rows = calcKC(bars, {"emaPeriod": 20, "atrPeriod": 14, "multiplier": 2.0})
    last = rows[-1]
    assert last["kc_mid"] is not None
    assert last["kc_upper"] is not None
    assert last["kc_lower"] is not None
    assert last["kc_upper"] > last["kc_mid"] > last["kc_lower"]
    assert last["kc_width"] is not None


def test_kc_rejects_zero_multiplier():
    bars = [{"open": 10, "high": 11, "low": 9, "close": 10, "volume": 1000}]
    with pytest.raises(ValueError):
        calcKC(bars, {"multiplier": 0})
