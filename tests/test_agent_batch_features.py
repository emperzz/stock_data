"""Tests for /api/v1/agent/* batch-profile computed K-line features."""

import contextlib
import random
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from stock_data.api.cache import (
    make_indices_batch_profile_cache_key,
    make_stocks_batch_profile_cache_key,
)
from stock_data.api.routes import agent as agent_module
from stock_data.api.routes import reset_manager
from stock_data.api.schemas import BatchFeatures, MinimalQuote
from stock_data.data_provider.base import DataFetchError
from stock_data.data_provider.core.types import RealtimeSource, UnifiedRealtimeQuote
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


class TestSchemas:
    def test_batch_features_roundtrip(self):
        m = BatchFeatures(
            trend={
                "ma": {"ma5": 1.0},
                "ma_change": {"ma5": 0.5},
                "adx": 20.0,
                "pdi": 10.0,
                "mdi": 8.0,
                "rsi": {"rsi_6": 50.0},
                "boll": {"mid": 1.0, "upper": 2.0, "lower": 0.0, "bandwidth": 1.0},
            },
            pivots={
                "window_high": {"price": 2.0, "date": "2026-08-10"},
                "window_low": {"price": 1.0, "date": "2026-07-15"},
                "max_vol_bar": None,
                "swings": [{"date": "2026-07-15", "type": "low", "price": 1.0, "confirmed": True}],
                "pending": {"side": "high", "bars": 2, "price": 2.0, "date": "2026-08-10"},
                "params": {"pivot_window": 2},
            },
            volume={
                "latest_volume": 100.0,
                "vol_ratio_5": 1.5,
                "z_anomalies": [
                    {
                        "date": "2026-08-10",
                        "open": 1.0,
                        "high": 2.0,
                        "low": 0.5,
                        "close": 1.5,
                        "volume": 100.0,
                        "z_score": 3.0,
                        "direction": "up",
                        "change_pct": 5.0,
                    }
                ],
            },
        )
        d = m.model_dump()
        assert d["pivots"]["swings"][0]["type"] == "low"
        assert d["volume"]["z_anomalies"][0]["direction"] == "up"

    def test_minimal_quote(self):
        q = MinimalQuote(price=1721.0, change_pct=1.2)
        assert q.model_dump() == {"price": 1721.0, "change_pct": 1.2}


class TestCacheKeys:
    def test_indices_key_includes_freq_and_days(self):
        a = make_indices_batch_profile_cache_key(["000001", "399001"], "d", 60)
        b = make_indices_batch_profile_cache_key(["399001", "000001"], "d", 60)  # order-immune
        c = make_indices_batch_profile_cache_key(["000001", "399001"], "d", 120)  # different days
        assert a == b
        assert a != c
        assert "d:60" in a

    def test_stocks_key_includes_freq_and_days(self):
        a = make_stocks_batch_profile_cache_key(["600519", "000858"], "5m", 5)
        assert "5m:5" in a
        assert "600519" in a and "000858" in a


_BOARD_STOCKS_PATCH = "stock_data.data_provider.persistence.board.get_stock_memberships"


def _make_unified_quote(code, price=100.0):
    return UnifiedRealtimeQuote(
        code=code, name=code, source=RealtimeSource.AKSHARE, price=price,
        change_pct=1.5, change_amount=1.5, open_price=99.0, high=101.0,
        low=98.5, pre_close=98.5, volume=1_000_000, amount=1e8,
    )


def _bind_manager(monkeypatch, mock_manager):
    monkeypatch.setattr(agent_module, "get_manager", lambda: mock_manager)
    return mock_manager


def _stock_request(codes, frequency="d", days=None):
    body = {"codes": codes, "frequency": frequency}
    if days is not None:
        body["days"] = days
    return body


class TestStocksBatchProfile:
    def test_all_aspects_populated(self, client, monkeypatch):
        mock_manager = MagicMock()
        mock_manager.get_realtime_quote.return_value = _make_unified_quote("600519")
        mock_manager.get_kline_data.return_value = (_make_kline_df(120, spike_idx=(80,)), "zzshare")
        mock_manager.get_stock_info.return_value = ({"industry": "白酒"}, "zhitu")
        _bind_manager(monkeypatch, mock_manager)
        with patch(_BOARD_STOCKS_PATCH, return_value=([{"code": "885595", "name": "白酒"}], False, "persistence")):
            resp = client.post(
                "/api/v1/agent/stocks/batch-profile",
                json=_stock_request(["600519"], frequency="d", days=60),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["frequency"] == "d" and data["days"] == 60
        e = data["results"][0]
        assert e["quote"] == {"price": 100.0, "change_pct": 1.5}
        assert e["features"]["trend"]["ma"]["ma60"] is not None
        assert e["features"]["pivots"]["window_high"] is not None
        assert e["features"]["volume"]["latest_volume"] is not None
        assert e["info"]["data"]["industry"] == "白酒"
        assert e["boards"]["data"][0]["code"] == "885595"
        assert e["ok"] is True
        assert e["errors"] == []

    def test_kline_failure_isolated(self, client, monkeypatch):
        mock_manager = MagicMock()
        mock_manager.get_realtime_quote.return_value = _make_unified_quote("600519")
        mock_manager.get_kline_data.side_effect = DataFetchError("kline upstream down")
        mock_manager.get_stock_info.return_value = ({"industry": "白酒"}, "zhitu")
        _bind_manager(monkeypatch, mock_manager)
        with patch(_BOARD_STOCKS_PATCH, return_value=([], False, "persistence")):
            resp = client.post(
                "/api/v1/agent/stocks/batch-profile", json=_stock_request(["600519"])
            )
        data = resp.json()
        e = data["results"][0]
        assert e["features"] is None
        assert e["quote"] is not None
        assert any(err["aspect"] == "features" for err in e["errors"])

    def test_passes_adjust_qfq_and_converts_minute_freq_for_manager(self, client, monkeypatch):
        mock_manager = MagicMock()
        mock_manager.get_realtime_quote.return_value = _make_unified_quote("600519")
        mock_manager.get_kline_data.return_value = (_make_kline_df(120), "zzshare")
        mock_manager.get_stock_info.return_value = ({"industry": "白酒"}, "zhitu")
        _bind_manager(monkeypatch, mock_manager)
        with patch(_BOARD_STOCKS_PATCH, return_value=([], False, "persistence")):
            client.post(
                "/api/v1/agent/stocks/batch-profile",
                json=_stock_request(["600519"], frequency="5m", days=3),
            )
        kwargs = mock_manager.get_kline_data.call_args.kwargs
        assert kwargs["adjust"] == "qfq"
        assert kwargs["asset"] == "stock"
        assert kwargs["frequency"] == "5"  # public "5m" -> manager "5"

    def test_days_out_of_range_422(self, client, monkeypatch):
        _bind_manager(monkeypatch, MagicMock())
        resp = client.post(
            "/api/v1/agent/stocks/batch-profile",
            json=_stock_request(["600519"], frequency="5m", days=99),
        )
        assert resp.status_code == 422

    def test_cache_second_call_skips_manager(self, client, monkeypatch):
        mock_manager = MagicMock()
        mock_manager.get_realtime_quote.return_value = _make_unified_quote("600519")
        mock_manager.get_kline_data.return_value = (_make_kline_df(120), "zzshare")
        mock_manager.get_stock_info.return_value = ({"industry": "白酒"}, "zhitu")
        _bind_manager(monkeypatch, mock_manager)
        with patch(_BOARD_STOCKS_PATCH, return_value=([], False, "persistence")):
            client.post("/api/v1/agent/stocks/batch-profile", json=_stock_request(["600519"], days=60))
            client.post("/api/v1/agent/stocks/batch-profile", json=_stock_request(["600519"], days=60))
        assert mock_manager.get_kline_data.call_count == 1


class TestIndicesBatchProfile:
    def test_default_3_indices_features(self, client, monkeypatch):
        mock_manager = MagicMock()
        mock_manager.get_index_realtime_quote.return_value = _make_unified_quote("000001")
        mock_manager.get_kline_data.return_value = (_make_kline_df(120, spike_idx=(80,)), "akshare")
        _bind_manager(monkeypatch, mock_manager)

        resp = client.get("/api/v1/agent/indices/batch-profile")
        assert resp.status_code == 200
        data = resp.json()
        assert data["frequency"] == "d"
        assert data["summary"]["requested"] == 3 and data["summary"]["ok"] == 3
        first = data["indices"][0]
        assert first["quote"]["price"] == 100.0
        assert set(first["features"].keys()) == {"trend", "pivots", "volume"}
        assert first["features"]["trend"]["ma"]["ma60"] is not None

    def test_frequency_and_days_echoed(self, client, monkeypatch):
        mock_manager = MagicMock()
        mock_manager.get_index_realtime_quote.return_value = _make_unified_quote("000001")
        mock_manager.get_kline_data.return_value = (_make_kline_df(120), "akshare")
        _bind_manager(monkeypatch, mock_manager)
        resp = client.get(
            "/api/v1/agent/indices/batch-profile?codes=000001&frequency=5m&days=3"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["frequency"] == "5m" and data["days"] == 3

    def test_index_fetch_no_adjust_and_converts_minute_freq(self, client, monkeypatch):
        mock_manager = MagicMock()
        mock_manager.get_index_realtime_quote.return_value = _make_unified_quote("000001")
        mock_manager.get_kline_data.return_value = (_make_kline_df(120), "akshare")
        _bind_manager(monkeypatch, mock_manager)
        client.get("/api/v1/agent/indices/batch-profile?codes=000001&frequency=5m&days=3")
        kwargs = mock_manager.get_kline_data.call_args.kwargs
        assert kwargs["adjust"] is None
        assert kwargs["asset"] == "index"
        assert kwargs["frequency"] == "5"  # public "5m" -> manager "5"

    def test_out_of_range_days_422(self, client, monkeypatch):
        _bind_manager(monkeypatch, MagicMock())
        resp = client.get("/api/v1/agent/indices/batch-profile?frequency=d&days=9999")
        assert resp.status_code == 422

    def test_unsupported_frequency_422(self, client, monkeypatch):
        _bind_manager(monkeypatch, MagicMock())
        resp = client.get("/api/v1/agent/indices/batch-profile?frequency=xy&days=30")
        assert resp.status_code == 422

    def test_quote_failure_isolated_features_still_served(self, client, monkeypatch):
        mock_manager = MagicMock()

        def quote_side(code):
            if code == "000001":
                raise DataFetchError("quote upstream down")
            return _make_unified_quote(code)

        mock_manager.get_index_realtime_quote.side_effect = quote_side
        mock_manager.get_kline_data.return_value = (_make_kline_df(120), "akshare")
        _bind_manager(monkeypatch, mock_manager)
        resp = client.get("/api/v1/agent/indices/batch-profile?codes=000001,399001")
        data = resp.json()
        assert data["summary"]["ok"] == 1
        failed = next(p for p in data["indices"] if p["code"] == "000001")
        assert failed["quote"] is None
        assert failed["features"] is not None
        assert failed["errors"]["quote"] is not None

    def test_cache_second_call_skips_manager(self, client, monkeypatch):
        mock_manager = MagicMock()
        mock_manager.get_index_realtime_quote.return_value = _make_unified_quote("000001")
        mock_manager.get_kline_data.return_value = (_make_kline_df(120), "akshare")
        _bind_manager(monkeypatch, mock_manager)
        client.get("/api/v1/agent/indices/batch-profile?codes=000001&frequency=5m&days=3")
        client.get("/api/v1/agent/indices/batch-profile?codes=000001&frequency=5m&days=3")
        assert mock_manager.get_kline_data.call_count == 1


class TestFormatMdFeatures:
    def _stub_features_response(self):
        from stock_data.api.schemas import BatchFeatures

        features = BatchFeatures(
            trend={"ma": {"ma5": 1.0}, "ma_change": {"ma5": 0.1}, "adx": 20.0, "pdi": 10.0,
                   "mdi": 8.0, "rsi": {"rsi_6": 50.0}, "boll": {"mid": 1.0, "upper": 2.0, "lower": 0.0, "bandwidth": 1.0}},
            pivots={"window_high": {"price": 2.0, "date": "2026-08-10"}, "window_low": {"price": 1.0, "date": "2026-07-15"},
                    "max_vol_bar": None,
                    "swings": [{"date": "2026-07-15", "type": "low", "price": 1.0, "confirmed": True}],
                    "pending": {"side": "high", "bars": 2, "price": 2.0, "date": "2026-08-10"},
                    "params": {"pivot_window": 2, "reversal_atr_mult": 1.0, "atr_period": 14}},
            volume={"latest_volume": 100.0, "vol_ratio_5": 1.5,
                    "z_anomalies": [{"date": "2026-08-10", "open": 1.0, "high": 2.0, "low": 0.5,
                                     "close": 1.5, "volume": 100.0, "z_score": 3.0,
                                     "direction": "up", "change_pct": 5.0}]},
        )
        return features

    def test_indices_batch_profile_md(self, client, monkeypatch):
        mock_manager = MagicMock()
        mock_manager.get_index_realtime_quote.return_value = _make_unified_quote("000001")
        mock_manager.get_kline_data.return_value = (_make_kline_df(120), "akshare")
        _bind_manager(monkeypatch, mock_manager)
        resp = client.get("/api/v1/agent/indices/batch-profile?format=md")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/markdown")
        body = resp.text
        assert "# 指数批量画像" in body
        # The three feature blocks render under their Chinese labels (the
        # verbatim renderer emits 趋势/顶底/量价, not the English words).
        assert "趋势" in body and "顶底" in body and "量价" in body

    def test_stocks_batch_profile_md(self, client, monkeypatch):
        mock_manager = MagicMock()
        mock_manager.get_realtime_quote.return_value = _make_unified_quote("600519")
        mock_manager.get_kline_data.return_value = (_make_kline_df(120), "zzshare")
        mock_manager.get_stock_info.return_value = ({"industry": "白酒"}, "zhitu")
        _bind_manager(monkeypatch, mock_manager)
        with patch(_BOARD_STOCKS_PATCH, return_value=([], False, "persistence")):
            resp = client.post(
                "/api/v1/agent/stocks/batch-profile?format=md",
                json=_stock_request(["600519"]),
            )
        assert resp.status_code == 200
        assert "趋势" in resp.text or "trend" in resp.text
