"""Unit tests for ZzshareFetcher — structural + per-capability.

All tests mock the DataApi SDK (no real network/token).
"""
import importlib
import os
from unittest.mock import MagicMock, patch

import pytest

from stock_data.data_provider.base import DataCapability, DataFetchError
from stock_data.data_provider.fetchers.zzshare_fetcher import ZzshareFetcher


# ====================================================================
# Metadata + availability
# ====================================================================

class TestZzshareFetcherMetadata:
    def test_name(self):
        assert ZzshareFetcher.name == "ZzshareFetcher"

    def test_priority_default(self, monkeypatch):
        monkeypatch.delenv("ZZSHARE_PRIORITY", raising=False)
        assert ZzshareFetcher.priority == 5

    def test_priority_env_override(self, monkeypatch):
        monkeypatch.setenv("ZZSHARE_PRIORITY", "3")
        from stock_data.data_provider.fetchers import zzshare_fetcher
        importlib.reload(zzshare_fetcher)
        try:
            assert zzshare_fetcher.ZzshareFetcher.priority == 3
        finally:
            monkeypatch.delenv("ZZSHARE_PRIORITY", raising=False)
            importlib.reload(zzshare_fetcher)

    def test_supported_markets(self):
        assert ZzshareFetcher.supported_markets == {"csi"}

    def test_supported_data_types_all_10_caps(self):
        expected = {
            DataCapability.HISTORICAL_DWM,
            DataCapability.HISTORICAL_MIN,
            DataCapability.REALTIME_QUOTE,
            DataCapability.STOCK_LIST,
            DataCapability.TRADE_CALENDAR,
            DataCapability.STOCK_BOARD,
            DataCapability.STOCK_ZT_POOL,
            DataCapability.DRAGON_TIGER,
            DataCapability.HOT_TOPICS,
            DataCapability.STOCK_INFO,
        }
        # supported_data_types is a DataCapability Flag enum value; check membership
        for cap in expected:
            assert cap in ZzshareFetcher.supported_data_types


class TestZzshareFetcherAvailability:
    def test_is_available_false_when_sdk_missing(self, monkeypatch):
        monkeypatch.delenv("ZZSHARE_TOKEN", raising=False)
        with patch("importlib.util.find_spec", return_value=None):
            fetcher = ZzshareFetcher()
            assert fetcher.is_available() is False

    def test_is_available_true_when_sdk_present_no_token(self, monkeypatch):
        monkeypatch.delenv("ZZSHARE_TOKEN", raising=False)
        with patch("importlib.util.find_spec", return_value=MagicMock()):
            fetcher = ZzshareFetcher()
            assert fetcher.is_available() is True

    def test_is_available_true_when_sdk_and_token(self, monkeypatch):
        monkeypatch.setenv("ZZSHARE_TOKEN", "test-token-123")
        with patch("importlib.util.find_spec", return_value=MagicMock()):
            fetcher = ZzshareFetcher()
            assert fetcher.is_available() is True

    def test_unavailable_reason_mentions_sdk_when_missing(self, monkeypatch):
        monkeypatch.delenv("ZZSHARE_TOKEN", raising=False)
        with patch("importlib.util.find_spec", return_value=None):
            fetcher = ZzshareFetcher()
            reason = fetcher.unavailable_reason()
            assert reason is not None
            assert "DataApi" in reason or "SDK" in reason


class TestKLineMethodsRaise:
    def test_fetch_raw_data_raises_for_unsupported_freq(self):
        fetcher = ZzshareFetcher()
        with pytest.raises(DataFetchError, match="不支持.*周.*月"):
            fetcher._fetch_raw_data("600519", "2026-05-01", "2026-05-31", frequency="w")

    def test_fetch_raw_data_raises_for_unsupported_freq_monthly(self):
        fetcher = ZzshareFetcher()
        with pytest.raises(DataFetchError, match="不支持.*周.*月"):
            fetcher._fetch_raw_data("600519", "2026-05-01", "2026-05-31", frequency="m")


# ====================================================================
# Helpers
# ====================================================================

class TestToZzshareTsCode:
    def test_shanghai_main(self):
        from stock_data.data_provider.fetchers.zzshare_fetcher import _to_zzshare_ts_code
        assert _to_zzshare_ts_code("600519") == "600519.SH"

    def test_shanghai_star(self):
        from stock_data.data_provider.fetchers.zzshare_fetcher import _to_zzshare_ts_code
        assert _to_zzshare_ts_code("688981") == "688981.SH"

    def test_shenzhen_main(self):
        from stock_data.data_provider.fetchers.zzshare_fetcher import _to_zzshare_ts_code
        assert _to_zzshare_ts_code("000001") == "000001.SZ"

    def test_chinext(self):
        from stock_data.data_provider.fetchers.zzshare_fetcher import _to_zzshare_ts_code
        assert _to_zzshare_ts_code("300750") == "300750.SZ"

    def test_beijing(self):
        from stock_data.data_provider.fetchers.zzshare_fetcher import _to_zzshare_ts_code
        assert _to_zzshare_ts_code("830799") == "830799.BJ"

    def test_passthrough_unrecognized(self):
        from stock_data.data_provider.fetchers.zzshare_fetcher import _to_zzshare_ts_code
        assert _to_zzshare_ts_code("XYZ") == "XYZ"


class TestToYyyymmdd:
    def test_with_dashes(self):
        from stock_data.data_provider.fetchers.zzshare_fetcher import _to_yyyymmdd
        assert _to_yyyymmdd("2026-05-20") == "20260520"

    def test_passthrough_yyyymmdd(self):
        from stock_data.data_provider.fetchers.zzshare_fetcher import _to_yyyymmdd
        assert _to_yyyymmdd("20260520") == "20260520"


class TestFromYyyymmdd:
    def test_eight_digits(self):
        from stock_data.data_provider.fetchers.zzshare_fetcher import _from_yyyymmdd
        assert _from_yyyymmdd("20260520") == "2026-05-20"

    def test_passthrough_with_dashes(self):
        from stock_data.data_provider.fetchers.zzshare_fetcher import _from_yyyymmdd
        assert _from_yyyymmdd("2026-05-20") == "2026-05-20"

    def test_other_format_passthrough(self):
        from stock_data.data_provider.fetchers.zzshare_fetcher import _from_yyyymmdd
        assert _from_yyyymmdd("garbage") == "garbage"


# ====================================================================
# K-line (HISTORICAL_DWM)
# ====================================================================

class TestDailyKline:
    def _fetcher_with_api(self, fake_daily):
        """Helper: return fetcher with DataApi.daily mocked."""
        fetcher = ZzshareFetcher()
        fake_api = MagicMock()
        fake_api.daily = MagicMock(return_value=fake_daily)
        fetcher._api = fake_api
        return fetcher

    def test_daily_normalizes_columns(self):
        import pandas as pd
        raw = pd.DataFrame({
            "ts_code": ["600519.SH"] * 3,
            "trade_date": ["20260501", "20260502", "20260503"],
            "open": [1700.0, 1710.0, 1720.0],
            "high": [1715.0, 1725.0, 1735.0],
            "low": [1695.0, 1705.0, 1715.0],
            "close": [1710.0, 1720.0, 1730.0],
            "pre_close": [1700.0, 1710.0, 1720.0],
            "change": [10.0, 10.0, 10.0],
            "pct_chg": [0.59, 0.58, 0.58],
            "vol": [1e6, 1.1e6, 1.2e6],
            "amount": [1e9, 1.1e9, 1.2e9],
        })
        fetcher = self._fetcher_with_api(raw)
        df = fetcher.get_kline_data("600519", "2026-05-01", "2026-05-03")
        # Required STANDARD_COLUMNS present
        for col in ["date", "open", "high", "low", "close", "volume", "amount", "pct_chg"]:
            assert col in df.columns, f"missing {col}"
        # vol -> volume rename
        assert "vol" not in df.columns
        # trade_date -> date (YYYY-MM-DD format)
        assert str(df.iloc[0]["date"])[:10] == "2026-05-01"
        # code column added
        assert "code" in df.columns
        assert df.iloc[0]["code"] == "600519"
        # pct_chg passed through
        assert abs(df.iloc[0]["pct_chg"] - 0.59) < 0.01

    def test_daily_passes_yyyymmdd_to_sdk(self):
        import pandas as pd
        raw = pd.DataFrame({"ts_code": ["600519.SH"], "trade_date": ["20260501"],
                            "open": [1700.0], "high": [1715.0], "low": [1695.0],
                            "close": [1710.0], "vol": [1e6], "amount": [1e9],
                            "pct_chg": [0.59]})
        fetcher = self._fetcher_with_api(raw)
        fetcher.get_kline_data("600519", "2026-05-01", "2026-05-03")
        call = fetcher._api.daily.call_args
        # start_date/end_date converted to YYYYMMDD
        assert call.kwargs["start_date"] == "20260501"
        assert call.kwargs["end_date"] == "20260503"
        # ts_code formatted with .SH suffix
        assert call.kwargs["ts_code"] == "600519.SH"

    def test_daily_qfq_adjust_passes_through(self):
        import pandas as pd
        raw = pd.DataFrame({"ts_code": ["600519.SH"], "trade_date": ["20260501"],
                            "open": [1700.0], "high": [1715.0], "low": [1695.0],
                            "close": [1710.0], "vol": [1e6], "amount": [1e9],
                            "pct_chg": [0.59]})
        fetcher = self._fetcher_with_api(raw)
        fetcher.get_kline_data("600519", "2026-05-01", "2026-05-03", adjust="qfq")
        call = fetcher._api.daily.call_args
        assert call.kwargs.get("adj") == "qfq"

    def test_daily_no_adjust_does_not_pass_adj(self):
        import pandas as pd
        raw = pd.DataFrame({"ts_code": ["600519.SH"], "trade_date": ["20260501"],
                            "open": [1700.0], "high": [1715.0], "low": [1695.0],
                            "close": [1710.0], "vol": [1e6], "amount": [1e9],
                            "pct_chg": [0.59]})
        fetcher = self._fetcher_with_api(raw)
        fetcher.get_kline_data("600519", "2026-05-01", "2026-05-03")
        call = fetcher._api.daily.call_args
        assert "adj" not in call.kwargs

    def test_daily_empty_df_raises(self):
        import pandas as pd
        fetcher = self._fetcher_with_api(pd.DataFrame())
        with pytest.raises(DataFetchError, match="No data"):
            fetcher.get_kline_data("600519", "2026-05-01", "2026-05-03")
