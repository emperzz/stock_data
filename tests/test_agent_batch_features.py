"""Tests for /api/v1/agent/* batch-profile computed K-line features."""

import contextlib
import random

import pandas as pd
import pytest

from stock_data.api.routes import reset_manager
from stock_data.data_provider.features.volume import compute_volume


@pytest.fixture(autouse=True)
def reset_before_test():
    reset_manager()
    from stock_data.api import cache as api_cache

    for getter_name in (
        "get_quote_cache",
        "get_index_quote_cache",
        "get_history_cache",
        "get_pools_cache",
        "get_stock_info_cache",
        "get_news_flash_cache",
        "get_cls_feed_cache",
        "get_dragontiger_cache",
    ):
        getter = getattr(api_cache, getter_name, None)
        if getter is None:
            continue
        with contextlib.suppress(TypeError):
            getter().clear()
    for f in ("d", "w", "m", "1", "5", "15", "30", "60"):
        with contextlib.suppress(Exception):
            api_cache.get_history_cache(f).clear()
    yield


def _make_kline_df(rows, *, seed=1, spike_idx=(), spike_mult=4.0) -> pd.DataFrame:
    """Deterministic OHLCV frame. A gentle upward drift + optional volume spikes."""
    rng = random.Random(seed)
    closes = [10.0]
    for _ in range(rows - 1):
        closes.append(closes[-1] * (1 + rng.uniform(-0.02, 0.03)))
    dates = pd.date_range("2026-01-01", periods=rows, freq="B")
    vols = [1_000_000 * (1 + abs(rng.gauss(0, 0.3))) for _ in range(rows)]
    for i in spike_idx:
        vols[i] *= spike_mult
    return pd.DataFrame(
        {
            "date": [d.strftime("%Y-%m-%d") for d in dates],
            "open": [round(c * 0.995, 3) for c in closes],
            "high": [round(c * 1.01, 3) for c in closes],
            "low": [round(c * 0.99, 3) for c in closes],
            "close": [round(c, 3) for c in closes],
            "volume": vols,
            "amount": [v * c for v, c in zip(vols, closes)],
            "pct_chg": [0.0] * rows,
        }
    )


def _window_by_last_days(df, days):
    last = pd.Timestamp(df["date"].iloc[-1])
    cutoff = last - pd.Timedelta(days=days)
    return df[pd.to_datetime(df["date"]) >= cutoff]


class TestVolumeFeatures:
    def test_latest_volume_and_ratio(self):
        df = _make_kline_df(30)
        window = _window_by_last_days(df, 20)
        out = compute_volume(df, window)
        # latest_volume is the last bar's volume
        assert out["latest_volume"] == float(df["volume"].iloc[-1])
        # vol_ratio_5 = latest / mean(previous 5) — verify against manual math
        prev5 = df["volume"].iloc[-6:-1].mean()
        assert out["vol_ratio_5"] == pytest.approx(float(df["volume"].iloc[-1]) / prev5)

    def test_z_anomalies_only_above_2(self):
        df = _make_kline_df(60, spike_idx=(30,), spike_mult=5.0)
        window = _window_by_last_days(df, 50)
        out = compute_volume(df, window)
        assert len(out["z_anomalies"]) >= 1
        # the spike bar must be present and sorted by z desc
        spike_date = df["date"].iloc[30]
        assert out["z_anomalies"][0]["date"] == spike_date
        assert all(a["z_score"] > 2.0 for a in out["z_anomalies"])
        assert all(
            out["z_anomalies"][i]["z_score"] >= out["z_anomalies"][i + 1]["z_score"]
            for i in range(len(out["z_anomalies"]) - 1)
        )

    def test_z_anomalies_capped_at_20(self):
        # every volume differs by a huge amount → many bars exceed z>2
        df = _make_kline_df(60, seed=3)
        vols = [float(v) for v in df["volume"]]
        df["volume"] = [v * (1 + i) for i, v in enumerate(vols)]  # monotone scale → all z>2
        window = _window_by_last_days(df, 50)
        out = compute_volume(df, window)
        assert len(out["z_anomalies"]) <= 20

    def test_anomaly_bar_fields(self):
        df = _make_kline_df(30, spike_idx=(20,), spike_mult=6.0)
        window = _window_by_last_days(df, 25)
        out = compute_volume(df, window)
        a = out["z_anomalies"][0]
        for key in ("date", "open", "high", "low", "close", "volume", "z_score", "direction", "change_pct"):
            assert key in a
        assert a["direction"] in ("up", "down")
