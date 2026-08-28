"""Tests for /api/v1/agent/* batch-profile computed K-line features."""

import contextlib
import random
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

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

    def test_single_row_df_no_raise_ma_change_none(self):
        # 1-row frame: _at(-2) (previous bar) must not IndexError; there is
        # no previous bar, so ma_change is all None (never fabricated 0.0).
        df = pd.DataFrame(
            {
                "date": ["2026-01-05"],
                "open": [10.0],
                "high": [10.5],
                "low": [9.5],
                "close": [10.0],
                "volume": [1_000_000],
            }
        )
        out = compute_trend(df)
        assert out["ma_change"]["ma5"] is None


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
        # ...and its price is that bar's close (fixture: max volume = last row).
        assert out["max_vol_bar"]["price"] == float(df["close"].iloc[-1])

    def test_params_echo_defaults(self):
        # Default compute_pivots call echoes its effective params.
        df = _make_pivot_df([10, 12, 15, 14, 11, 9, 12, 16])
        window = _window_by_last_days(df, 30)
        out = compute_pivots(df, window)
        assert out["params"] == {"pivot_window": 2, "reversal_atr_mult": 1.0, "atr_period": 14}

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
        dumped = q.model_dump()
        # Backward-compatible: the 2-field anchor still serializes
        # the original price/change_pct values; the rest are None defaults.
        assert dumped["price"] == 1721.0
        assert dumped["change_pct"] == 1.2
        assert dumped["volume_unit"] == "share"
        # New fields are present-but-None.
        assert dumped["open"] is None
        assert dumped["amount"] is None
        assert dumped["mcap_yi"] is None
        assert dumped["rank"] is None


# The composite cache for batch-profile was removed 2026-08-28; the
# old TestCacheKeys + two test_cache_second_call_skips_manager tests were
# deleted alongside it (see CLAUDE.md "Design contract" + boards/batch-profile
# spec §5).

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
        # MinimalQuote now carries 23 fields; verify the legacy 2-field
        # anchor still serializes correctly + new fields surface upstream data.
        # _make_unified_quote fills OHLCV + volume + amount; valuation /
        # turnover / amplitude / 涨跌停 stay None on the stub.
        assert e["quote"]["price"] == 100.0
        assert e["quote"]["change_pct"] == 1.5
        assert e["quote"]["volume_unit"] == "share"
        assert e["quote"]["open"] == 99.0
        assert e["quote"]["high"] == 101.0
        assert e["quote"]["low"] == 98.5
        assert e["quote"]["prev_close"] == 98.5
        assert e["quote"]["volume"] == 1_000_000
        assert e["quote"]["amount"] == 1e8
        # valuation + turnover + 涨跌停 are None on the stub UnifiedRealtimeQuote.
        assert e["quote"]["pe_ratio"] is None
        assert e["quote"]["mcap_yi"] is None
        assert e["quote"]["turnover_pct"] is None
        assert e["quote"]["limit_up"] is None
        # board-only fields are None on stock path.
        assert e["quote"]["up_count"] is None
        assert e["quote"]["rank"] is None
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

    # ``test_cache_second_call_skips_manager`` removed 2026-08-28 alongside the
    # composite cache (see CLAUDE.md "Design contract" + boards/batch-profile
    # spec §5). The handler now invokes the manager on every call.


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

    # ``test_cache_second_call_skips_manager`` removed 2026-08-28 alongside the
    # composite cache. The handler now invokes the manager on every call.


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
        assert resp.headers["content-type"].startswith("text/markdown")
        # The three feature blocks render under their Chinese labels — pin the
        # content-type so a JSON fallback cannot slip past this assertion.
        assert "趋势" in resp.text and "顶底" in resp.text and "量价" in resp.text


class TestFormatMdFeatureCompleteness:
    """Pins the api-reference.md "No data is dropped" contract for the
    batch-profile feature blocks specifically.

    ``TestFormatMdDataCompleteness`` in test_agent_endpoints.py pins the same
    general contract, but only for boards/stock-overlap, stocks/board-overlap
    and market-context — the feature blocks fell in its coverage gap, which is
    how ``pivots.params`` and the z_anomalies OHLC columns went missing from
    the MD projection while the JSON carried them.
    """

    def _render(self):
        from stock_data.api.routes.agent import _md_feature_block

        out: list[str] = []
        _md_feature_block(out, TestFormatMdFeatures()._stub_features_response())
        return "\n".join(out)

    def test_pivots_params_rendered(self):
        """`pivots.params` pins the ZigZag settings the swings came from —
        without it the顶底 points in MD are uncalibratable."""
        body = self._render()
        assert "pivot_window=2" in body
        assert "reversal_atr_mult=1.0" in body
        assert "atr_period=14" in body

    def test_z_anomaly_ohlc_rendered(self):
        """open/high/low are computed and present in JSON, so the MD table
        must carry them: close alone cannot distinguish a 放量长上影 from a
        光头阳线, and `direction` is itself derived from open."""
        body = self._render()
        header = next(line for line in body.splitlines() if line.startswith("| 日期 | 开"))
        assert header.count("|") == 10  # 9 columns => 10 pipes
        for label in ("开", "高", "低", "收盘", "成交量", "方向", "涨跌幅"):
            assert label in header
        # The stub's OHLC values must actually appear in the data row.
        row = next(line for line in body.splitlines() if line.startswith("| 2026-08-10 |"))
        for value in ("1.00", "2.00", "0.50", "1.50"):
            assert value in row

    def test_empty_dict_block_marks_no_data(self):
        """`build_features` returns {} (not an error) for an empty DataFrame,
        so `errors` stays None. The MD must say so explicitly rather than
        emit a bare heading + empty table skeleton reading as "computed,
        but blank"."""
        from stock_data.api.routes.agent import _md_feature_block

        out: list[str] = []
        empty = build_features(pd.DataFrame(), frequency="d", days=60)
        _md_feature_block(out, BatchFeatures(**empty))
        body = "\n".join(out)
        assert "（无数据）" in body
        assert "（无确认摆动点）" in body
        # No empty table skeleton ANYWHERE: scan every markdown separator row
        # (`|---|...`) and require a data row after it. Scanning only the
        # `| 字段 |` dict tables would miss the hand-written swings table.
        lines = body.splitlines()
        for i, line in enumerate(lines):
            if set(line.replace("|", "").replace("-", "")) <= {" "} and "---" in line:
                nxt = lines[i + 1] if i + 1 < len(lines) else ""
                assert nxt.startswith("| "), f"empty table skeleton at line {i + 1}"
