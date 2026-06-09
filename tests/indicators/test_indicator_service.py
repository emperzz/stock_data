"""Tests for the indicator orchestrator and registry."""

import pandas as pd
import pytest

from stock_data.data_provider.indicators import (
    INDICATOR_REGISTRY,
    compute,
    compute_lookback,
    estimate_lookback,
    list_indicators,
)

# ---------- registry / catalog ----------


def test_registry_has_14_indicators():
    assert len(INDICATOR_REGISTRY) == 14
    expected = {
        "ma", "macd", "boll", "kdj", "rsi", "wr", "bias",
        "cci", "atr", "obv", "roc", "dmi", "sar", "kc",
    }
    assert {k.value for k in INDICATOR_REGISTRY} == expected


def test_list_indicators_returns_catalog():
    catalog = list_indicators()
    assert len(catalog) == 14
    for entry in catalog:
        assert "key" in entry
        assert "default_options" in entry
        assert "output_columns" in entry
        assert "default_lookback" in entry
        assert "input_shape" in entry
        assert entry["input_shape"] in ("closes", "ohlcv")


def test_estimate_lookback_empty():
    assert estimate_lookback({}) == 0


def test_estimate_lookback_takes_max():
    spec = {
        "ma": {"periods": [5, 20, 60]},
        "macd": {},  # default lookback 87
        "kdj": {},
    }
    assert estimate_lookback(spec) == 87


def test_estimate_lookback_ignores_unknown_keys():
    spec = {"ma": {}, "nonsense": {}}
    assert estimate_lookback(spec) > 0


# ---------- service.compute() ----------


def _kline(n: int) -> pd.DataFrame:
    """Build a synthetic K-line DataFrame with the standard columns."""
    return pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=n, freq="B"),
            "open": [100.0 + i * 0.1 for i in range(n)],
            "high": [101.0 + i * 0.1 for i in range(n)],
            "low": [99.0 + i * 0.1 for i in range(n)],
            "close": [100.5 + i * 0.1 for i in range(n)],
            "volume": [1000.0 + i * 10 for i in range(n)],
            "amount": [1_000_000.0 + i * 1000 for i in range(n)],
        }
    )


def test_compute_no_op_when_spec_none():
    df = _kline(30)
    out = compute(df, None)
    assert "indicators" in out.columns
    # Each row's `indicators` is an empty dict
    assert all(out["indicators"].apply(lambda d: d == {}).tolist())


def test_compute_with_list_of_names():
    df = _kline(60)
    out = compute(df, ["ma", "macd", "rsi"])
    last = out.iloc[-1]["indicators"]
    assert "ma5" in last
    assert "macd_dif" in last
    assert "rsi_6" in last
    # rsi_24 needs 48 changes -> last bar should have it
    assert last["rsi_24"] is not None


def test_compute_with_full_spec():
    df = _kline(60)
    out = compute(df, {"ma": {"periods": [5, 10]}, "boll": {"period": 20, "stdDev": 1.5}})
    last = out.iloc[-1]["indicators"]
    # Only the columns we asked for
    assert "ma5" in last and "ma10" in last
    assert "ma20" not in last
    assert "boll_mid" in last


def test_compute_rejects_unknown_indicator():
    df = _kline(30)
    with pytest.raises(ValueError, match="unknown indicator"):
        compute(df, ["nope"])


def test_compute_partial_options_uses_defaults():
    df = _kline(60)
    # Only override periods, leave `type` default
    out = compute(df, {"ma": {"periods": [3, 7]}})
    last = out.iloc[-1]["indicators"]
    assert "ma3" in last
    assert "ma7" in last
    # ma5/ma10 not requested -> not present
    assert "ma5" not in last


def test_compute_nan_becomes_none():
    df = _kline(30)
    # Force a NaN in volume so OBV's leading entry is None
    df.loc[0, "volume"] = float("nan")
    out = compute(df, ["obv"])
    # Row 0 indicators dict should have obv=None, not NaN
    first = out.iloc[0]["indicators"]
    assert first["obv"] is None


def test_compute_does_not_mutate_input():
    df = _kline(30)
    before_cols = list(df.columns)
    compute(df, ["ma"])
    assert list(df.columns) == before_cols
    assert "indicators" not in df.columns


def test_estimate_lookback_for_service():
    assert compute_lookback(None) == 0
    assert compute_lookback([]) == 0
    assert compute_lookback(["ma"]) > 0
    assert compute_lookback({"macd": {}}) >= 87
