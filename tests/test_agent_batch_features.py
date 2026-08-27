"""Tests for /api/v1/agent/* batch-profile computed K-line features."""

import contextlib
import random

import pandas as pd
import pytest

from stock_data.api.routes import reset_manager
from stock_data.data_provider.features.build import build_features
from stock_data.data_provider.features.pivots import compute_pivots
from stock_data.data_provider.features.trend import compute_trend
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
            "amount": [v * c for v, c in zip(vols, closes, strict=True)],
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
        assert all(a["z_score"] >= 2.0 for a in out["z_anomalies"])
        assert all(
            out["z_anomalies"][i]["z_score"] >= out["z_anomalies"][i + 1]["z_score"]
            for i in range(len(out["z_anomalies"]) - 1)
        )

    def test_z_anomalies_capped_at_20(self):
        # 300 bars, 25 of them 100x the small-baseline volume → each big bar
        # has z≈3.3>2 (Chebyshev allows up to ~20% of a sample above mean+2σ),
        # so 25 anomalies exceed the 20 cap and the cap must truncate to 20.
        df = _make_kline_df(300, seed=3)
        df["volume"] = [1_000_000] * (300 - 25) + [100_000_000] * 25
        out = compute_volume(df, df)
        assert len(out["z_anomalies"]) == 20
        assert all(a["z_score"] > 2.0 for a in out["z_anomalies"])

    def test_anomaly_bar_fields(self):
        df = _make_kline_df(30, spike_idx=(20,), spike_mult=6.0)
        window = _window_by_last_days(df, 25)
        out = compute_volume(df, window)
        a = out["z_anomalies"][0]
        for key in (
            "date",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "z_score",
            "direction",
            "change_pct",
        ):
            assert key in a
        assert a["direction"] in ("up", "down")


class TestTrendFeatures:
    def test_ma_values_match_sma(self):
        df = _make_kline_df(80)
        out = compute_trend(df)
        closes = df["close"].tolist()
        expected_ma5 = sum(closes[-5:]) / 5
        # indicator layer rounds MA to 2 decimals (calcSMA → round2)
        assert out["ma"]["ma5"] == pytest.approx(round(expected_ma5, 2))
        assert set(out["ma"].keys()) == {"ma5", "ma10", "ma15", "ma20", "ma30", "ma60"}
        assert out["ma"]["ma60"] is not None  # warm (80 rows)

    def test_ma_change_is_vs_previous_bar(self):
        df = _make_kline_df(80)
        out = compute_trend(df)
        closes = df["close"].tolist()
        ma5_cur = round(sum(closes[-5:]) / 5, 2)
        ma5_prev = round(sum(closes[-6:-1]) / 5, 2)
        assert out["ma_change"]["ma5"] == pytest.approx((ma5_cur - ma5_prev) / ma5_prev * 100, rel=1e-6)

    def test_adx_rsi_boll_present(self):
        out = compute_trend(_make_kline_df(120))
        assert out["adx"] is not None
        assert {"pdi", "mdi"} <= set(out)
        assert set(out["rsi"].keys()) == {"rsi_6", "rsi_12", "rsi_24"}
        assert set(out["boll"].keys()) == {"mid", "upper", "lower", "bandwidth"}

    def test_empty_df_returns_empty_blocks(self):
        import pandas as pd
        out = compute_trend(pd.DataFrame())
        assert out["ma"] == {}
        assert out["ma_change"] == {}


def _make_pivot_df(prices):
    """Explicit-price K-line for deterministic swing tests."""
    n = len(prices)
    dates = pd.date_range("2026-01-01", periods=n, freq="B")
    return pd.DataFrame(
        {
            "date": [d.strftime("%Y-%m-%d") for d in dates],
            "open": [p * 0.995 for p in prices],
            "high": [p * 1.05 for p in prices],
            "low": [p * 0.95 for p in prices],
            "close": [float(p) for p in prices],
            "volume": [1_000_000 + i * 100_000 for i in range(n)],
            "amount": [0.0] * n,
            "pct_chg": [0.0] * n,
        }
    )


class TestPivotFeatures:
    def test_window_stats(self):
        df = _make_pivot_df([10, 12, 15, 14, 11, 9, 12, 16])
        window = _window_by_last_days(df, 30)
        out = compute_pivots(df, window)
        # spec §3.2: prices are the actual max high / min low in the window
        # (fixture: high = close*1.05, low = close*0.95; max close 16 → 16.8,
        # min close 9 → 8.55), not the extreme bar's close.
        # approx: fixture math (9 * 0.95) is not exactly representable as 8.55
        assert out["window_high"]["price"] == pytest.approx(16.8)
        assert out["window_low"]["price"] == pytest.approx(8.55)
        assert out["window_high"]["date"]
        assert out["window_low"]["date"]
        # max_vol_bar is the max-volume bar's close (volumes increase over time)
        assert out["max_vol_bar"]["volume"] == float(df["volume"].iloc[-1])

    def test_swings_alternate_with_loose_threshold(self):
        # 10→15→9→16→10 : majors high@15, low@9, high@16, pending low@10
        df = _make_pivot_df([10, 11, 12, 15, 13, 11, 9, 11, 13, 16, 14, 12, 10])
        window = _window_by_last_days(df, 30)
        out = compute_pivots(df, window, pivot_window=1, atr_mult=0.2)
        types = [s["type"] for s in out["swings"]]
        assert types and all(a != b for a, b in zip(types, types[1:], strict=False))  # alternates
        assert types[0] == "high"
        assert out["pending"] is not None
        assert out["pending"]["side"] in ("high", "low")

    def test_pending_is_last_unconfirmed(self):
        df = _make_pivot_df([10, 12, 15, 13, 11, 9, 10, 11])
        window = _window_by_last_days(df, 30)
        out = compute_pivots(df, window, pivot_window=1, atr_mult=0.2)
        assert out["pending"] is not None
        assert out["pending"]["bars"] >= 0

    def test_empty_df_returns_empty(self):
        out = compute_pivots(pd.DataFrame(), pd.DataFrame())
        assert out["window_high"] is None
        assert out["swings"] == []
        assert out["pending"] is None


class TestBuildFeatures:
    def test_assembles_three_blocks(self):
        df = _make_kline_df(120, spike_idx=(80,), spike_mult=5.0)
        out = build_features(df, frequency="d", days=60)
        assert set(out.keys()) == {"trend", "pivots", "volume"}
        assert out["trend"]["ma"]["ma60"] is not None
        assert out["pivots"]["swings"] is not None
        assert out["volume"]["latest_volume"] is not None
        assert len(out["volume"]["z_anomalies"]) >= 1

    def test_window_respects_days(self):
        df = _make_kline_df(120)
        out_60 = build_features(df, frequency="d", days=60)
        # window_high computed on last ~60 calendar days of bars only
        cutoff = pd.Timestamp(df["date"].iloc[-1]) - pd.Timedelta(days=60)
        mask = pd.to_datetime(df["date"]) >= cutoff
        assert out_60["pivots"]["window_high"]["price"] == float(df.loc[mask, "high"].max())
