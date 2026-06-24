"""Unit tests for ZzshareFetcher — structural + per-capability.

All tests mock the zzshare SDK (no real network/token).
"""

import importlib
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
            assert "zzshare" in reason or "SDK" in reason


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
        """Helper: return fetcher with zzshare SDK .daily mocked."""
        fetcher = ZzshareFetcher()
        fake_api = MagicMock()
        fake_api.daily = MagicMock(return_value=fake_daily)
        fetcher._api = fake_api
        return fetcher

    def test_daily_normalizes_columns(self):
        import pandas as pd

        raw = pd.DataFrame(
            {
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
            }
        )
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

        raw = pd.DataFrame(
            {
                "ts_code": ["600519.SH"],
                "trade_date": ["20260501"],
                "open": [1700.0],
                "high": [1715.0],
                "low": [1695.0],
                "close": [1710.0],
                "vol": [1e6],
                "amount": [1e9],
                "pct_chg": [0.59],
            }
        )
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

        raw = pd.DataFrame(
            {
                "ts_code": ["600519.SH"],
                "trade_date": ["20260501"],
                "open": [1700.0],
                "high": [1715.0],
                "low": [1695.0],
                "close": [1710.0],
                "vol": [1e6],
                "amount": [1e9],
                "pct_chg": [0.59],
            }
        )
        fetcher = self._fetcher_with_api(raw)
        fetcher.get_kline_data("600519", "2026-05-01", "2026-05-03", adjust="qfq")
        call = fetcher._api.daily.call_args
        assert call.kwargs.get("adj") == "qfq"

    def test_daily_no_adjust_does_not_pass_adj(self):
        import pandas as pd

        raw = pd.DataFrame(
            {
                "ts_code": ["600519.SH"],
                "trade_date": ["20260501"],
                "open": [1700.0],
                "high": [1715.0],
                "low": [1695.0],
                "close": [1710.0],
                "vol": [1e6],
                "amount": [1e9],
                "pct_chg": [0.59],
            }
        )
        fetcher = self._fetcher_with_api(raw)
        fetcher.get_kline_data("600519", "2026-05-01", "2026-05-03")
        call = fetcher._api.daily.call_args
        assert "adj" not in call.kwargs

    def test_daily_empty_df_raises(self):
        import pandas as pd

        fetcher = self._fetcher_with_api(pd.DataFrame())
        with pytest.raises(DataFetchError, match="No data"):
            fetcher.get_kline_data("600519", "2026-05-01", "2026-05-03")


# ====================================================================
# K-line (HISTORICAL_MIN) — get_intraday_data
# ====================================================================


class TestIntradayKline:
    def _fetcher_with_api(self, fake_stk_mins):
        fetcher = ZzshareFetcher()
        fake_api = MagicMock()
        fake_api.stk_mins = MagicMock(return_value=fake_stk_mins)
        fetcher._api = fake_api
        return fetcher

    def test_intraday_normalizes_time(self):
        import pandas as pd

        raw = pd.DataFrame(
            {
                "ts_code": ["600519.SH"] * 3,
                "trade_time": ["202605200935", "202605200940", "202605200945"],
                "open": [1700.0, 1705.0, 1710.0],
                "high": [1708.0, 1712.0, 1717.0],
                "low": [1698.0, 1702.0, 1708.0],
                "close": [1705.0, 1710.0, 1715.0],
                "vol": [1e5, 1.1e5, 1.2e5],
                "amount": [1e8, 1.1e8, 1.2e8],
            }
        )
        fetcher = self._fetcher_with_api(raw)
        df = fetcher.get_intraday_data("600519", period="5")
        assert "time" in df.columns
        assert list(df["time"]) == ["09:35:00", "09:40:00", "09:45:00"]
        assert "vol" not in df.columns
        assert "volume" in df.columns

    def test_intraday_period_to_freq(self):
        import pandas as pd

        raw = pd.DataFrame(
            {
                "ts_code": ["600519.SH"],
                "trade_time": ["202605200935"],
                "open": [1700.0],
                "high": [1708.0],
                "low": [1698.0],
                "close": [1705.0],
                "vol": [1e5],
                "amount": [1e8],
            }
        )
        fetcher = self._fetcher_with_api(raw)
        fetcher.get_intraday_data("600519", period="15")
        call = fetcher._api.stk_mins.call_args
        assert call.kwargs.get("freq") == "15min"

    def test_intraday_adjust_ignored(self):
        """Minute K has no adjust — adjust param should not be passed."""
        import pandas as pd

        raw = pd.DataFrame(
            {
                "ts_code": ["600519.SH"],
                "trade_time": ["202605200935"],
                "open": [1700.0],
                "high": [1708.0],
                "low": [1698.0],
                "close": [1705.0],
                "vol": [1e5],
                "amount": [1e8],
            }
        )
        fetcher = self._fetcher_with_api(raw)
        fetcher.get_intraday_data("600519", period="5", adjust="qfq")
        call = fetcher._api.stk_mins.call_args
        assert "adj" not in call.kwargs
        assert "adjust" not in call.kwargs

    def test_intraday_date_is_yyyymmdd_format(self):
        """trade_time passed to SDK should be YYYYMMDD (no dashes)."""
        import pandas as pd

        raw = pd.DataFrame(
            {
                "ts_code": ["600519.SH"],
                "trade_time": ["202605200935"],
                "open": [1700.0],
                "high": [1708.0],
                "low": [1698.0],
                "close": [1705.0],
                "vol": [1e5],
                "amount": [1e8],
            }
        )
        fetcher = self._fetcher_with_api(raw)
        fetcher.get_intraday_data("600519", period="5")
        call = fetcher._api.stk_mins.call_args
        # trade_time is the date in YYYYMMDD format (8 digits, no dashes)
        trade_time = call.kwargs.get("trade_time", "")
        assert len(trade_time) == 8
        assert "-" not in trade_time
        assert trade_time.isdigit()

    def test_intraday_sdk_unavailable_returns_none(self, monkeypatch):
        monkeypatch.delenv("ZZSHARE_TOKEN", raising=False)
        with patch("importlib.util.find_spec", return_value=None):
            fetcher = ZzshareFetcher()
            result = fetcher.get_intraday_data("600519", period="5")
            assert result is None


# ====================================================================
# REALTIME_QUOTE
# ====================================================================


class TestRealtimeQuote:
    def _fetcher_with_api(self, fake_rt_k):
        fetcher = ZzshareFetcher()
        fake_api = MagicMock()
        fake_api.rt_k = MagicMock(return_value=fake_rt_k)
        fetcher._api = fake_api
        return fetcher

    def test_realtime_basic_fields(self):
        import pandas as pd

        raw = pd.DataFrame(
            [
                {
                    "ts_code": "600519.SH",
                    "name": "贵州茅台",
                    "pre_close": 1700.0,
                    "open": 1710.0,
                    "high": 1725.0,
                    "low": 1695.0,
                    "close": 1720.0,
                    "vol": 1e6,
                    "amount": 1e9,
                    "quote_rate": 1.18,
                    "turnover_rate": 0.5,
                    "high_limit": 1870.0,
                    "low_limit": 1530.0,
                    "market_value": 2.16e12,
                    "circulation_value": 2.16e12,
                    "ttm_pe_rate": 25.5,
                }
            ]
        )
        fetcher = self._fetcher_with_api(raw)
        quote = fetcher.get_realtime_quote("600519")
        assert quote is not None
        assert quote.code == "600519"
        assert quote.name == "贵州茅台"
        assert quote.source.value == "zzshare"
        assert quote.price == 1720.0
        assert quote.change_pct == 1.18
        assert quote.pre_close == 1700.0
        assert quote.open_price == 1710.0
        assert quote.total_mv == 2.16e12
        assert quote.circ_mv == 2.16e12
        assert quote.pe_ratio == 25.5
        assert quote.turnover_rate == 0.5

    def test_realtime_uses_fields_all(self):
        import pandas as pd

        raw = pd.DataFrame(
            [
                {
                    "ts_code": "600519.SH",
                    "name": "茅台",
                    "close": 1720.0,
                    "pre_close": 1700.0,
                    "open": 1710.0,
                    "high": 1725.0,
                    "low": 1695.0,
                    "vol": 1e6,
                    "amount": 1e9,
                    "quote_rate": 1.18,
                    "turnover_rate": 0.5,
                    "market_value": 2.16e12,
                    "circulation_value": 2.16e12,
                    "ttm_pe_rate": 25.5,
                }
            ]
        )
        fetcher = self._fetcher_with_api(raw)
        fetcher.get_realtime_quote("600519")
        call = fetcher._api.rt_k.call_args
        # Enhanced fields mode requested
        assert call.kwargs.get("fields") == "all"

    def test_realtime_empty_df_returns_none(self):
        import pandas as pd

        fetcher = self._fetcher_with_api(pd.DataFrame())
        assert fetcher.get_realtime_quote("600519") is None

    def test_realtime_sdk_unavailable_returns_none(self, monkeypatch):
        monkeypatch.delenv("ZZSHARE_TOKEN", raising=False)
        with patch("importlib.util.find_spec", return_value=None):
            fetcher = ZzshareFetcher()
            assert fetcher.get_realtime_quote("600519") is None


# ====================================================================
# STOCK_LIST
# ====================================================================


class TestStockList:
    def _fetcher_with_api(self, fake_basic):
        fetcher = ZzshareFetcher()
        fake_api = MagicMock()
        fake_api.stock_basic = MagicMock(return_value=fake_basic)
        fetcher._api = fake_api
        return fetcher

    def test_get_all_stocks_normalizes_exchange(self):
        import pandas as pd

        raw = pd.DataFrame(
            {
                "ts_code": ["600519.SH", "000001.SZ", "830799.BJ"],
                "symbol": ["600519", "000001", "830799"],
                "name": ["贵州茅台", "平安银行", "殷图网联"],
                "exchange": ["SSE", "SZSE", "BSE"],
                "area": ["", "", ""],
                "industry": ["", "", ""],
                "list_date": ["", "", ""],
            }
        )
        fetcher = self._fetcher_with_api(raw)
        result = fetcher.get_all_stocks("csi")
        assert len(result) == 3
        assert result[0] == {"code": "600519", "name": "贵州茅台", "exchange": "SSE"}
        assert result[1] == {"code": "000001", "name": "平安银行", "exchange": "SZSE"}
        assert result[2] == {"code": "830799", "name": "殷图网联", "exchange": "BSE"}

    def test_get_all_stocks_non_csi_returns_empty(self):
        fetcher = ZzshareFetcher()
        with patch("importlib.util.find_spec", return_value=MagicMock()):
            assert fetcher.get_all_stocks("hk") == []
            assert fetcher.get_all_stocks("us") == []

    def test_get_all_stocks_calls_stock_basic_all(self):
        import pandas as pd

        raw = pd.DataFrame(
            {
                "ts_code": ["600519.SH"],
                "symbol": ["600519"],
                "name": ["贵州茅台"],
                "exchange": ["SSE"],
                "area": [""],
                "industry": [""],
                "list_date": [""],
            }
        )
        fetcher = self._fetcher_with_api(raw)
        fetcher.get_all_stocks("csi")
        call = fetcher._api.stock_basic.call_args
        assert call.kwargs.get("exchange") == "ALL"
        assert call.kwargs.get("list_status") == "L"

    def test_get_all_stocks_sdk_unavailable_returns_empty(self, monkeypatch):
        monkeypatch.delenv("ZZSHARE_TOKEN", raising=False)
        with patch("importlib.util.find_spec", return_value=None):
            fetcher = ZzshareFetcher()
            assert fetcher.get_all_stocks("csi") == []


# ====================================================================
# TRADE_CALENDAR
# ====================================================================


class TestTradeCalendar:
    def _fetcher_with_api(self, fake_days):
        fetcher = ZzshareFetcher()
        fake_api = MagicMock()
        fake_api.trade_days = MagicMock(return_value=fake_days)
        fetcher._api = fake_api
        return fetcher

    def test_trade_calendar_passthrough(self):
        dates = ["2026-05-20", "2026-05-21", "2026-05-22"]
        fetcher = self._fetcher_with_api(dates)
        result = fetcher.get_trade_calendar()
        assert result == dates

    def test_trade_calendar_empty_returns_none(self):
        fetcher = self._fetcher_with_api([])
        assert fetcher.get_trade_calendar() is None

    def test_trade_calendar_sdk_unavailable_returns_none(self, monkeypatch):
        monkeypatch.delenv("ZZSHARE_TOKEN", raising=False)
        with patch("importlib.util.find_spec", return_value=None):
            fetcher = ZzshareFetcher()
            assert fetcher.get_trade_calendar() is None


# ====================================================================
# STOCK_INFO
# ====================================================================


class TestStockInfo:
    def _fetcher_with_api(self, fake_info):
        fetcher = ZzshareFetcher()
        fake_api = MagicMock()
        fake_api.stock_info = MagicMock(return_value=fake_info)
        fetcher._api = fake_api
        return fetcher

    def test_stock_info_returns_normalized_dict(self):
        raw = {
            "name": "贵州茅台",
            "ename": "Kweichow Moutai Co.,Ltd.",
            "ldate": "2001-08-27",
            "totalstock": 1256197800,
            "flowstock": 1256197800,
            "idea": "白酒, 消费, 蓝筹",
            "raddr": "贵州省遵义市",
            "rcapital": "100000万人民币",
            "rname": "丁雄军",
            "bscope": "酒类生产与销售...",
            "rdate": "1999-11-20",
            "bsname": "蒋焰",
            "bsphone": "0851-22386000",
            "bsemail": "mt@maotaichina.com",
        }
        fetcher = self._fetcher_with_api(raw)
        info = fetcher.get_stock_info("600519")
        assert info is not None
        assert info["code"] == "600519"
        assert info["name"] == "贵州茅台"
        assert info["market"] == "csi"
        assert info["listed_date"] == "2001-08-27"
        assert info["total_shares"] == 1256197800
        assert "白酒" in info["concepts"]

    def test_stock_info_concepts_deduped(self):
        raw = {
            "name": "Test",
            "ename": "",
            "ldate": "",
            "totalstock": 0,
            "flowstock": 0,
            "idea": "白酒, 消费, 白酒, 消费",
            "raddr": "",
            "rcapital": "",
            "rname": "",
            "bscope": "",
            "rdate": "",
            "bsname": "",
            "bsphone": "",
            "bsemail": "",
        }
        fetcher = self._fetcher_with_api(raw)
        info = fetcher.get_stock_info("000001")
        # Duplicates removed, order preserved
        assert info["concepts"] == ["白酒", "消费"]

    def test_stock_info_no_token_returns_none(self, monkeypatch):
        """Without token, stock_info() returns None (other fetchers will cover)."""
        monkeypatch.delenv("ZZSHARE_TOKEN", raising=False)
        with patch("importlib.util.find_spec", return_value=None):
            fetcher = ZzshareFetcher()
            assert fetcher.get_stock_info("600519") is None

    def test_stock_info_empty_idea_yields_empty_concepts(self):
        raw = {
            "name": "Test",
            "ename": "",
            "ldate": "",
            "totalstock": 0,
            "flowstock": 0,
            "idea": "",
            "raddr": "",
            "rcapital": "",
            "rname": "",
            "bscope": "",
            "rdate": "",
            "bsname": "",
            "bsphone": "",
            "bsemail": "",
        }
        fetcher = self._fetcher_with_api(raw)
        info = fetcher.get_stock_info("000001")
        assert info["concepts"] == []


# ====================================================================
# STOCK_ZT_POOL
# ====================================================================


class TestZtPool:
    def _fetcher_with_api(self, stocks=None, hot_raises=False):
        fetcher = ZzshareFetcher()
        fake_api = MagicMock()
        if hot_raises:
            fake_api.uplimit_hot = MagicMock(side_effect=Exception("upstream error"))
        else:
            fake_api.uplimit_hot = MagicMock(return_value={})
        fake_api.uplimit_stocks = MagicMock(return_value=stocks if stocks is not None else [])
        fetcher._api = fake_api
        return fetcher

    def test_zt_pool_returns_stocks(self):
        stocks = [
            {
                "ts_code": "600519.SH",
                "name": "贵州茅台",
                "pct_chg": 10.0,
                "amount": 1e9,
                "circ_mv": 2e12,
                "total_mv": 2.2e12,
                "turnover_rate": 0.5,
                "lb_count": 1,
                "first_seal_time": "10:30",
                "last_seal_time": "14:55",
                "seal_amount": 5e8,
                "seal_count": 3,
                "zt_count": 1,
            },
        ]
        fetcher = self._fetcher_with_api(stocks=stocks)
        result = fetcher.get_zt_pool("zt", "2026-05-20")
        assert result is not None
        assert len(result) == 1
        assert result[0]["code"] == "600519"
        assert result[0]["name"] == "贵州茅台"
        assert result[0]["change_pct"] == 10.0

    def test_zt_pool_empty_stocks_returns_none(self):
        """If uplimit_stocks returns empty (no token or no data), return None."""
        fetcher = self._fetcher_with_api(stocks=[])
        result = fetcher.get_zt_pool("zt", "2026-05-20")
        assert result is None

    def test_zt_pool_dt_returns_none(self):
        """zzshare only supports zt via uplimit_* — dt/zbgc return None."""
        fetcher = self._fetcher_with_api()
        assert fetcher.get_zt_pool("dt", "2026-05-20") is None
        assert fetcher.get_zt_pool("zbgc", "2026-05-20") is None

    def test_zt_pool_sdk_unavailable_returns_none(self, monkeypatch):
        monkeypatch.delenv("ZZSHARE_TOKEN", raising=False)
        with patch("importlib.util.find_spec", return_value=None):
            fetcher = ZzshareFetcher()
            assert fetcher.get_zt_pool("zt", "2026-05-20") is None

    def test_zt_pool_date_converted_to_yyyymmdd(self):
        stocks = [{"ts_code": "600519.SH", "name": "茅台"}]
        fetcher = self._fetcher_with_api(stocks=stocks)
        fetcher.get_zt_pool("zt", "2026-05-20")
        call = fetcher._api.uplimit_stocks.call_args
        # date1 should be YYYYMMDD format
        assert call.kwargs.get("date1") == "20260520"


# ====================================================================
# STOCK_BOARD (4 methods)
# ====================================================================


class TestBoards:
    def _fetcher_with_api(self, **mocks):
        fetcher = ZzshareFetcher()
        fake_api = MagicMock()
        for name, value in mocks.items():
            setattr(fake_api, name, MagicMock(return_value=value))
        fetcher._api = fake_api
        return fetcher

    def test_get_all_boards_concept_via_15(self):
        rows = [
            {"plate_code": "801001", "plate_name": "芯片", "plate_type": 15, "rate": 1.5},
            {"plate_code": "801660", "plate_name": "通信", "plate_type": 15, "rate": 0.8},
        ]
        fetcher = self._fetcher_with_api(plates_list=rows)
        boards = fetcher.get_all_boards(
            board_type="concept", subtype="同花顺概念", source="zzshare"
        )
        assert len(boards) == 2
        assert boards[0]["code"] == "801001"
        assert boards[0]["name"] == "芯片"
        assert boards[0]["type"] == "concept"
        assert boards[0]["subtype"] == "同花顺概念"

    def test_get_all_boards_filters_by_subtype(self):
        rows = [
            {"plate_code": "801001", "plate_name": "芯片", "plate_type": 15, "rate": 1.5},
            {"plate_code": "881121", "plate_name": "半导体", "plate_type": 14, "rate": 0.5},
        ]
        fetcher = self._fetcher_with_api(plates_list=rows)
        boards = fetcher.get_all_boards(
            board_type="concept", subtype="同花顺概念", source="zzshare"
        )
        # Only plate_type=15 (concept) matches
        assert len(boards) == 1
        assert boards[0]["code"] == "801001"

    def test_get_all_boards_industry_via_14(self):
        rows = [
            {"plate_code": "881121", "plate_name": "半导体", "plate_type": 14, "rate": 0.5},
        ]
        fetcher = self._fetcher_with_api(plates_list=rows)
        boards = fetcher.get_all_boards(
            board_type="industry", subtype="同花顺行业", source="zzshare"
        )
        assert len(boards) == 1
        assert boards[0]["type"] == "industry"

    def test_get_all_boards_special_via_17(self):
        rows = [
            {"plate_code": "881999", "plate_name": "题材", "plate_type": 17, "rate": 2.0},
        ]
        fetcher = self._fetcher_with_api(plates_list=rows)
        boards = fetcher.get_all_boards(
            board_type="special", subtype="同花顺题材", source="zzshare"
        )
        assert len(boards) == 1
        assert boards[0]["type"] == "special"

    def test_get_all_boards_no_subtype_returns_all_matching_type(self):
        rows = [
            {"plate_code": "801001", "plate_name": "芯片", "plate_type": 15, "rate": 1.5},
            {"plate_code": "801002", "plate_name": "通信", "plate_type": 15, "rate": 0.8},
            {"plate_code": "881121", "plate_name": "半导体", "plate_type": 14, "rate": 0.5},
        ]
        fetcher = self._fetcher_with_api(plates_list=rows)
        boards = fetcher.get_all_boards(board_type="concept", subtype=None, source="zzshare")
        # Only concept (plate_type=15) match
        assert len(boards) == 2

    def test_get_board_stocks_adds_exchange_suffix(self):
        rows = [
            {"stock_code": "600519", "stock_name": "贵州茅台", "exchange": "sh"},
            {"stock_code": "000001", "stock_name": "平安银行", "exchange": "sz"},
        ]
        fetcher = self._fetcher_with_api(plates_stocks=rows)
        stocks = fetcher.get_board_stocks("801001", source="zzshare")
        assert stocks[0]["stock_code"] == "600519.SH"
        assert stocks[1]["stock_code"] == "000001.SZ"
        assert stocks[0]["stock_name"] == "贵州茅台"

    def test_get_stock_boards_returns_none(self):
        """SDK has no stock->boards reverse lookup; return None (route 404)."""
        fetcher = ZzshareFetcher()
        assert fetcher.get_stock_boards("600519", source="zzshare") is None

    def test_get_board_history_raises_not_implemented(self):
        fetcher = ZzshareFetcher()
        with pytest.raises(NotImplementedError, match="ZzshareFetcher does not provide"):
            fetcher.get_board_history("801001", source="zzshare", frequency="d", days=30)


# ====================================================================
# DRAGON_TIGER
# ====================================================================


class TestDragonTiger:
    def _fetcher_with_api(self, **mocks):
        fetcher = ZzshareFetcher()
        fake_api = MagicMock()
        for name, value in mocks.items():
            setattr(fake_api, name, MagicMock(return_value=value))
        fetcher._api = fake_api
        return fetcher

    def test_daily_dragon_tiger_normalizes_stock_code(self):
        rows = [
            {
                "stock_code": "000078",
                "stock_name": "海王生物",
                "concepts": "801723:中药,801369:医美",
                "amplitude": 5.2,
                "quote_change": 10.0,
                "turnover": 5e8,
                "turnover_ratio": 8.5,
                "capitalization": 1e9,
                "circ_price": 5e8,
                "buy_in": 1e8,
                "join_num": 5,
                "up_reason": "涨幅偏离值达7%",
                "t_type": 0,
                "d3": 12.0,
            },
        ]
        fetcher = self._fetcher_with_api(lhb_list=rows)
        data = fetcher.get_daily_dragon_tiger("2026-05-20", None)
        assert data["date"] == "2026-05-20"
        assert data["total"] == 1
        # 000078 -> 000078.SZ (ChiNext prefix 0/3 -> SZ)
        assert data["stocks"][0]["code"] == "000078.SZ"
        assert data["stocks"][0]["name"] == "海王生物"
        assert data["stocks"][0]["net_buy"] == 1e8

    def test_daily_dragon_tiger_min_net_buy_filter(self):
        rows = [
            {"stock_code": "000078", "stock_name": "A", "buy_in": 5e7},
            {"stock_code": "600519", "stock_name": "B", "buy_in": 2e8},
        ]
        fetcher = self._fetcher_with_api(lhb_list=rows)
        data = fetcher.get_daily_dragon_tiger("2026-05-20", 1e8)
        # Only stock with buy_in >= 1e8 (100M) survives; 600519 starts with 6 -> .SH
        assert data["total"] == 1
        assert data["stocks"][0]["code"] == "600519.SH"

    def test_daily_dragon_tiger_empty_returns_zeros(self):
        fetcher = self._fetcher_with_api(lhb_list=[])
        data = fetcher.get_daily_dragon_tiger("2026-05-20", None)
        assert data["date"] == "2026-05-20"
        assert data["total"] == 0
        assert data["stocks"] == []

    def test_dragon_tiger_uses_detail(self):
        detail = [
            {"trader_name": "东方证券绍兴解放南路营业部", "buy": 1e8, "sell": 5e7, "net": 5e7},
            {"trader_name": "华泰证券深圳益田路荣超商务中心", "buy": 5e7, "sell": 3e7, "net": 2e7},
        ]
        fetcher = self._fetcher_with_api(lhb_detail=detail)
        data = fetcher.get_dragon_tiger("000078", "2026-05-20", 30)
        assert "seats" in data
        # 2 buy seats and 2 sell seats
        assert len(data["seats"]["buy"]) == 2
        assert len(data["seats"]["sell"]) == 2
        assert data["seats"]["buy"][0]["name"] == "东方证券绍兴解放南路营业部"

    def test_dragon_tiger_falls_back_to_stock_history(self):
        """When lhb_detail returns empty, try lhb_stock_history."""
        fetcher = self._fetcher_with_api(
            lhb_detail=[],  # empty
            lhb_stock_history=[{"trade_date": "2026-05-15", "buy_in": 5e7, "reason": "涨幅偏离"}],
        )
        data = fetcher.get_dragon_tiger("000078", "2026-05-20", 30)
        # records should have at least 1 entry from history
        assert len(data["records"]) >= 1

    def test_daily_dragon_tiger_uses_trade_calendar_when_date_empty(self, monkeypatch):
        """When trade_date is empty, fall back to the latest trade date <= today."""
        # Mock the trade calendar helper
        import stock_data.data_provider.fetchers.zzshare_fetcher as zf
        monkeypatch.setattr(
            zf, "get_latest_trade_date_on_or_before",
            lambda d: "2026-05-22",
        )
        fetcher = self._fetcher_with_api(lhb_list=[])
        fetcher.get_daily_dragon_tiger("", None)
        call = fetcher._api.lhb_list.call_args
        # Should be 20260522 (from mocked trade calendar)
        assert call.kwargs.get("date1") == "20260522"


# ====================================================================
# HOT_TOPICS
# ====================================================================


class TestHotTopics:
    def _fetcher_with_api(self, fake_top):
        fetcher = ZzshareFetcher()
        fake_api = MagicMock()
        fake_api.ths_hot_top = MagicMock(return_value=fake_top)
        fetcher._api = fake_api
        return fetcher

    def test_hot_topics_normalizes_symbol_code(self):
        rows = [
            {
                "rank": 1,
                "rank_diff": 1,
                "symbol_code": "002342",
                "symbol_name": "巨力索具",
                "last_price": 5.5,
                "last_pct": 10.0,
                "circulation_value": 50.0,
                "collect_date": "2026-05-20",
                "update_time": "2026-05-20 15:00:00",
                "id": 1,
            },
            {
                "rank": 2,
                "rank_diff": -2,
                "symbol_code": "600519",
                "symbol_name": "贵州茅台",
                "last_price": 1720.0,
                "last_pct": 1.18,
                "circulation_value": 21600.0,
                "collect_date": "2026-05-20",
                "update_time": "2026-05-20 15:00:00",
                "id": 2,
            },
        ]
        fetcher = self._fetcher_with_api(rows)
        topics = fetcher.get_hot_topics("2026-05-20")
        assert len(topics) == 2
        # 002342 -> 002342.SZ
        assert topics[0]["code"] == "002342.SZ"
        assert topics[0]["name"] == "巨力索具"
        assert topics[0]["change_pct"] == 10.0
        assert topics[0]["rank"] == 1
        # 600519 -> 600519.SH
        assert topics[1]["code"] == "600519.SH"

    def test_hot_topics_empty_returns_empty_list(self):
        fetcher = self._fetcher_with_api([])
        assert fetcher.get_hot_topics("2026-05-20") == []

    def test_hot_topics_uses_today_when_date_empty(self):
        fetcher = self._fetcher_with_api([])
        fetcher.get_hot_topics("")  # empty -> today
        call = fetcher._api.ths_hot_top.call_args
        # date1 should be today's YYYYMMDD
        from datetime import date

        expected = date.today().strftime("%Y%m%d")
        assert call.kwargs.get("date1") == expected

    def test_hot_topics_default_top_n(self):
        fetcher = self._fetcher_with_api([])
        fetcher.get_hot_topics("2026-05-20")
        call = fetcher._api.ths_hot_top.call_args
        assert call.kwargs.get("top_n") == 100


# ====================================================================
# Boards source-routing — persistence layer integration
# ====================================================================


class TestBoardSubtypeValidation:
    """Verify VALID_SUBTYPES_BY_SOURCE has zzshare entries."""

    def test_zzshare_industry_subtype(self):
        from stock_data.data_provider.persistence.board import VALID_SUBTYPES_BY_SOURCE

        assert "zzshare" in VALID_SUBTYPES_BY_SOURCE
        assert "industry" in VALID_SUBTYPES_BY_SOURCE["zzshare"]
        assert "同花顺行业" in VALID_SUBTYPES_BY_SOURCE["zzshare"]["industry"]

    def test_zzshare_concept_subtype(self):
        from stock_data.data_provider.persistence.board import VALID_SUBTYPES_BY_SOURCE

        assert "同花顺概念" in VALID_SUBTYPES_BY_SOURCE["zzshare"]["concept"]

    def test_zzshare_special_subtype(self):
        from stock_data.data_provider.persistence.board import VALID_SUBTYPES_BY_SOURCE

        assert "同花顺题材" in VALID_SUBTYPES_BY_SOURCE["zzshare"]["special"]
