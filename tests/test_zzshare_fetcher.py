"""Unit tests for ZzshareFetcher — structural + per-capability.

All tests mock the zzshare SDK (no real network/token).
"""

from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from stock_data.data_provider.base import DataCapability, DataFetchError
from stock_data.data_provider.fetchers.zzshare_fetcher import ZzshareFetcher


@pytest.fixture(autouse=True)
def _isolate_zzshare_cls_state():
    """Reset class-level init state between tests.

    ``_api`` / ``_init_attempted`` / ``_init_ok`` live on the class now
    (once-per-process init). Each test must start from a clean slate so
    fake_api mocks injected by one test don't leak into the next.
    """
    saved = (
        ZzshareFetcher._init_attempted,
        ZzshareFetcher._init_ok,
        ZzshareFetcher._cls_token,
        ZzshareFetcher._init_error,
        ZzshareFetcher._api,
    )
    ZzshareFetcher._init_attempted = False
    ZzshareFetcher._init_ok = False
    ZzshareFetcher._cls_token = ""
    ZzshareFetcher._init_error = None
    ZzshareFetcher._api = None
    yield
    (
        ZzshareFetcher._init_attempted,
        ZzshareFetcher._init_ok,
        ZzshareFetcher._cls_token,
        ZzshareFetcher._init_error,
        ZzshareFetcher._api,
    ) = saved

# ====================================================================
# Metadata + availability
# ====================================================================


class TestZzshareFetcherMetadata:
    def test_name(self):
        assert ZzshareFetcher.name == "ZzshareFetcher"

    def test_priority_default(self, monkeypatch):
        monkeypatch.delenv("ZZSHARE_PRIORITY", raising=False)
        assert ZzshareFetcher.priority == 2

    def test_priority_env_override(self, monkeypatch):
        """``priority`` reads ``ZZSHARE_PRIORITY`` at module-import time.

        A reload-based test was tempting but creates class-identity churn
        (``importlib.reload`` rebinds the class object, so anything that
        did ``from … import ZzshareFetcher`` at module load keeps a stale
        reference). With class-level init state this would silently
        desync the autouse isolation fixture from production code, so we
        verify via source inspection instead. The env-var read is one
        line; if it ever changes, this test catches it.
        """
        import inspect

        from stock_data.data_provider.fetchers import zzshare_fetcher

        src = inspect.getsource(zzshare_fetcher)
        assert 'os.getenv("ZZSHARE_PRIORITY"' in src, (
            "ZzshareFetcher.priority no longer reads ZZSHARE_PRIORITY env var"
        )
        assert "priority = int(os.getenv" in src, (
            "ZzshareFetcher.priority should be int(os.getenv(...))"
        )

    def test_supported_markets(self):
        assert ZzshareFetcher.supported_markets == {"csi"}

    def test_supported_data_types_all_10_caps(self):
        expected = {
            DataCapability.STOCK_KLINE,
            DataCapability.STOCK_REALTIME_QUOTE,
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
    """``is_available()`` probes the ``zzshare`` package via ``find_spec``."""

    # find_spec(name, package=None) takes 2 positional args; we ignore the second.
    @staticmethod
    def _sdk_present(name, *args, **kwargs):
        return MagicMock() if name == "zzshare" else None

    @staticmethod
    def _sdk_absent(name, *args, **kwargs):
        return None

    def test_is_available_false_when_sdk_missing(self, monkeypatch):
        monkeypatch.delenv("ZZSHARE_TOKEN", raising=False)
        with patch("importlib.util.find_spec", side_effect=self._sdk_absent):
            fetcher = ZzshareFetcher()
            assert fetcher.is_available() is False

    def test_is_available_true_when_zzshare_package_present_no_token(self, monkeypatch):
        monkeypatch.delenv("ZZSHARE_TOKEN", raising=False)
        with patch("importlib.util.find_spec", side_effect=self._sdk_present):
            fetcher = ZzshareFetcher()
            assert fetcher.is_available() is True

    def test_is_available_true_when_zzshare_and_token(self, monkeypatch):
        monkeypatch.setenv("ZZSHARE_TOKEN", "test-token-123")
        with patch("importlib.util.find_spec", side_effect=self._sdk_present):
            fetcher = ZzshareFetcher()
            assert fetcher.is_available() is True

    def test_is_available_probes_zzshare_package_not_dataapi(self, monkeypatch):
        """Regression: ``is_available()`` must call find_spec('zzshare'),
        not find_spec('DataApi'). With only the unrelated ``DataApi``
        PyPI package installed, ``is_available()`` must return False.
        """
        monkeypatch.delenv("ZZSHARE_TOKEN", raising=False)
        # Simulate: unrelated DataApi package is present, but zzshare is NOT.

        def only_dataapi(name, *args, **kwargs):
            return MagicMock() if name == "DataApi" else None

        with patch("importlib.util.find_spec", side_effect=only_dataapi):
            fetcher = ZzshareFetcher()
            assert fetcher.is_available() is False

    def test_is_available_actually_calls_find_spec_with_zzshare(self, monkeypatch):
        """Pin the spec name so a regression that swaps back to 'DataApi'
        fails immediately rather than passing silently.
        """
        monkeypatch.delenv("ZZSHARE_TOKEN", raising=False)
        with patch("importlib.util.find_spec", return_value=MagicMock()) as mock_find_spec:
            fetcher = ZzshareFetcher()
            fetcher.is_available()
        assert mock_find_spec.called
        called_with = mock_find_spec.call_args.args[0]
        assert called_with == "zzshare", (
            f"is_available() must probe the 'zzshare' package, not {called_with!r}"
        )

    def test_unavailable_reason_mentions_zzshare_when_missing(self, monkeypatch):
        monkeypatch.delenv("ZZSHARE_TOKEN", raising=False)
        with patch("importlib.util.find_spec", side_effect=self._sdk_absent):
            fetcher = ZzshareFetcher()
            reason = fetcher.unavailable_reason()
            assert reason is not None
            assert "zzshare" in reason, f"unavailable_reason should mention 'zzshare', got: {reason!r}"


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
# K-line (STOCK_KLINE)
# ====================================================================


class TestDailyKline:
    def _fetcher_with_api(self, fake_daily):
        """Helper: return fetcher with zzshare SDK .daily mocked.

        Injects the mock at the class level (ZzshareFetcher._api) since
        init state now lives there — see _isolate_zzshare_cls_state.
        Skips actual SDK init by setting _init_attempted=True so
        _ensure_api() returns the injected mock without trying to
        ``import zzshare`` / ``DataApi()``.
        """
        fetcher = ZzshareFetcher()
        fake_api = MagicMock()
        fake_api.daily = MagicMock(return_value=fake_daily)
        ZzshareFetcher._api = fake_api
        ZzshareFetcher._init_attempted = True
        ZzshareFetcher._init_ok = True
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
        call = ZzshareFetcher._api.daily.call_args
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
        call = ZzshareFetcher._api.daily.call_args
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
        call = ZzshareFetcher._api.daily.call_args
        assert "adj" not in call.kwargs

    def test_daily_empty_df_raises(self):
        import pandas as pd

        fetcher = self._fetcher_with_api(pd.DataFrame())
        with pytest.raises(DataFetchError, match="No data"):
            fetcher.get_kline_data("600519", "2026-05-01", "2026-05-03")

    def test_fetch_raw_data_minute_single_day(self):
        """_fetch_raw_data(frequency="5") routes through api.stk_mins for a single day."""
        import pandas as pd

        fetcher = ZzshareFetcher()
        fake_api = MagicMock()
        fake_api.stk_mins = MagicMock(return_value=pd.DataFrame({
            "ts_code": ["600519.SH"] * 3,
            "trade_time": ["202605200935", "202605200940", "202605200945"],
            "open": [1700.0, 1705.0, 1710.0],
            "high": [1708.0, 1712.0, 1717.0],
            "low": [1698.0, 1702.0, 1708.0],
            "close": [1705.0, 1710.0, 1715.0],
            "vol": [1e5, 1.1e5, 1.2e5],
            "amount": [1e8, 1.1e8, 1.2e8],
        }))
        ZzshareFetcher._api = fake_api
        ZzshareFetcher._init_attempted = True

        fetcher._fetch_raw_data(
            "600519", "2026-05-20", "2026-05-20", frequency="5"
        )

        # 验证走的是 stk_mins 而不是 daily
        assert fake_api.stk_mins.called
        assert not fake_api.daily.called
        # 验证调用参数
        call = fake_api.stk_mins.call_args
        assert call.kwargs["freq"] == "5min"
        assert call.kwargs["trade_time"] == "20260520"
        assert call.kwargs["ts_code"] == "600519.SH"

    def test_fetch_raw_data_minute_adjust_ignored(self):
        """adjust='qfq' on minute frequency: must NOT be forwarded to stk_mins."""
        import pandas as pd

        fetcher = ZzshareFetcher()
        fake_api = MagicMock()
        fake_api.stk_mins = MagicMock(return_value=pd.DataFrame({
            "trade_time": ["202605200935"],
            "open": [1700.0], "high": [1708.0], "low": [1698.0], "close": [1705.0],
            "vol": [1e5], "amount": [1e8],
        }))
        ZzshareFetcher._api = fake_api
        ZzshareFetcher._init_attempted = True

        fetcher._fetch_raw_data(
            "600519", "2026-05-20", "2026-05-20", frequency="5", adjust="qfq"
        )
        call = fake_api.stk_mins.call_args
        assert "adj" not in call.kwargs
        assert "adjust" not in call.kwargs

    def test_fetch_raw_data_minute_sdk_unavailable_raises(self, monkeypatch):
        """SDK not installed → minute path raises DataFetchError with SDK-specific message.

        Regression for the diagnostic conflation identified in code review: the
        pre-fix path lumped SDK-unavailable with empty-data under a generic
        "无分钟数据" message. Post-fix, SDK-unavailable surfaces with "SDK 不可用"
        matching the daily branch's wording, so users can distinguish
        "environment problem" from "upstream returned no data".
        """
        monkeypatch.delenv("ZZSHARE_TOKEN", raising=False)
        with patch("importlib.util.find_spec", return_value=None):
            fetcher = ZzshareFetcher()
            with pytest.raises(DataFetchError, match="SDK 不可用"):
                fetcher.get_kline_data(
                    "600519", "2026-05-20", "2026-05-20", frequency="5"
                )

    def test_fetch_raw_data_minute_all_days_empty_raises(self):
        """When stk_mins returns empty for the only day, raise DataFetchError."""
        import pandas as pd

        fetcher = ZzshareFetcher()
        fake_api = MagicMock()
        fake_api.stk_mins = MagicMock(return_value=pd.DataFrame())
        ZzshareFetcher._api = fake_api
        ZzshareFetcher._init_attempted = True

        with pytest.raises(DataFetchError, match="无分钟数据"):
            fetcher.get_kline_data(
                "600519", "2026-05-20", "2026-05-20", frequency="5"
            )

    def test_fetch_raw_data_minute_three_day_loop(self):
        """3-day minute range → 3 stk_mins calls + concat."""
        import pandas as pd

        fetcher = ZzshareFetcher()
        fake_api = MagicMock()
        fake_api.stk_mins = MagicMock(side_effect=[
            pd.DataFrame({
                "trade_time": ["202605180935", "202605180940"],
                "open": [1700.0, 1705.0], "high": [1708.0, 1712.0],
                "low": [1698.0, 1702.0], "close": [1705.0, 1710.0],
                "vol": [1e5, 1.1e5], "amount": [1e8, 1.1e8],
            }),
            pd.DataFrame({
                "trade_time": ["202605190935", "202605190940"],
                "open": [1710.0, 1715.0], "high": [1718.0, 1723.0],
                "low": [1708.0, 1713.0], "close": [1715.0, 1720.0],
                "vol": [1.2e5, 1.3e5], "amount": [1.2e8, 1.3e8],
            }),
            pd.DataFrame({
                "trade_time": ["202605200935", "202605200940"],
                "open": [1720.0, 1725.0], "high": [1728.0, 1733.0],
                "low": [1718.0, 1723.0], "close": [1725.0, 1730.0],
                "vol": [1.4e5, 1.5e5], "amount": [1.4e8, 1.5e8],
            }),
        ])
        ZzshareFetcher._api = fake_api
        ZzshareFetcher._init_attempted = True

        df = fetcher._fetch_raw_data(
            "600519", "2026-05-18", "2026-05-20", frequency="5"
        )

        assert fake_api.stk_mins.call_count == 3
        # Verify trade_time argument across calls
        times = [c.kwargs["trade_time"] for c in fake_api.stk_mins.call_args_list]
        assert times == ["20260518", "20260519", "20260520"]
        # Total rows
        assert len(df) == 6

    def test_fetch_raw_data_minute_skips_empty_days(self):
        """Non-trade days returning None/empty are skipped, not raised."""
        import pandas as pd

        fetcher = ZzshareFetcher()
        fake_api = MagicMock()
        fake_api.stk_mins = MagicMock(side_effect=[
            pd.DataFrame({
                "trade_time": ["202605180935"],
                "open": [1700.0], "high": [1708.0], "low": [1698.0], "close": [1705.0],
                "vol": [1e5], "amount": [1e8],
            }),
            pd.DataFrame(),  # 19th: empty (non-trade day)
            pd.DataFrame({
                "trade_time": ["202605200935"],
                "open": [1720.0], "high": [1728.0], "low": [1718.0], "close": [1725.0],
                "vol": [1.4e5], "amount": [1.4e8],
            }),
        ])
        ZzshareFetcher._api = fake_api
        ZzshareFetcher._init_attempted = True

        df = fetcher._fetch_raw_data(
            "600519", "2026-05-18", "2026-05-20", frequency="5"
        )
        assert fake_api.stk_mins.call_count == 3
        assert len(df) == 2  # only 18 and 20 contributed

    def test_fetch_raw_data_minute_long_range_logs_warning(self, caplog):
        """Range > 14 days triggers a logger.warning."""
        import logging

        import pandas as pd

        fetcher = ZzshareFetcher()
        fake_api = MagicMock()
        fake_api.stk_mins = MagicMock(return_value=pd.DataFrame({
            "trade_time": ["202605180935"],
            "open": [1700.0], "high": [1708.0], "low": [1698.0], "close": [1705.0],
            "vol": [1e5], "amount": [1e8],
        }))
        ZzshareFetcher._api = fake_api
        ZzshareFetcher._init_attempted = True

        with caplog.at_level(logging.WARNING, logger="stock_data.data_provider.fetchers.zzshare_fetcher"):
            fetcher._fetch_raw_data(
                "600519", "2026-05-01", "2026-05-20", frequency="5"
            )

        assert any("over 20 days" in r.message for r in caplog.records)


# ====================================================================
# K-line (STOCK_KLINE) — get_intraday_data
# ====================================================================


class TestIntradayKline:
    def _fetcher_with_api(self, fake_stk_mins):
        fetcher = ZzshareFetcher()
        fake_api = MagicMock()
        fake_api.stk_mins = MagicMock(return_value=fake_stk_mins)
        ZzshareFetcher._api = fake_api
        ZzshareFetcher._init_attempted = True
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
        call = ZzshareFetcher._api.stk_mins.call_args
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
        call = ZzshareFetcher._api.stk_mins.call_args
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
        call = ZzshareFetcher._api.stk_mins.call_args
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


class TestFetchMinuteKline:
    """Tests for the private _fetch_minute_kline helper (Task 2 prep)."""

    def test_helper_dispatches_to_stk_mins(self):
        """Helper calls api.stk_mins with correct ts_code / freq / trade_time."""
        import pandas as pd

        fetcher = ZzshareFetcher()
        fake_api = MagicMock()
        fake_api.stk_mins = MagicMock(
            return_value=pd.DataFrame({"trade_time": ["202605200935"]})
        )
        ZzshareFetcher._api = fake_api
        ZzshareFetcher._init_attempted = True
        df = fetcher._fetch_minute_kline("600519", "20260520", "5min")
        call = fake_api.stk_mins.call_args
        assert call.kwargs["ts_code"] == "600519.SH"
        assert call.kwargs["freq"] == "5min"
        assert call.kwargs["trade_time"] == "20260520"
        assert df is not None

    def test_helper_sdk_unavailable_returns_none(self, monkeypatch):
        monkeypatch.delenv("ZZSHARE_TOKEN", raising=False)
        with patch("importlib.util.find_spec", return_value=None):
            fetcher = ZzshareFetcher()
            assert fetcher._fetch_minute_kline("600519", "20260520", "5min") is None

    def test_helper_sdk_exception_returns_none(self):
        fetcher = ZzshareFetcher()
        fake_api = MagicMock()
        fake_api.stk_mins = MagicMock(side_effect=RuntimeError("rate limit"))
        ZzshareFetcher._api = fake_api
        ZzshareFetcher._init_attempted = True
        assert fetcher._fetch_minute_kline("600519", "20260520", "5min") is None

    def test_helper_empty_df_returns_none(self):
        import pandas as pd

        fetcher = ZzshareFetcher()
        fake_api = MagicMock()
        fake_api.stk_mins = MagicMock(return_value=pd.DataFrame())
        ZzshareFetcher._api = fake_api
        ZzshareFetcher._init_attempted = True
        assert fetcher._fetch_minute_kline("600519", "20260520", "5min") is None


# ====================================================================
# REALTIME_QUOTE (STOCK_REALTIME_QUOTE)
# ====================================================================


class TestRealtimeQuote:
    def _fetcher_with_api(self, fake_rt_k):
        fetcher = ZzshareFetcher()
        fake_api = MagicMock()
        fake_api.rt_k = MagicMock(return_value=fake_rt_k)
        ZzshareFetcher._api = fake_api
        ZzshareFetcher._init_attempted = True
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
        call = ZzshareFetcher._api.rt_k.call_args
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
        ZzshareFetcher._api = fake_api
        ZzshareFetcher._init_attempted = True
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

    def test_get_all_stocks_accepts_cn_alias(self):
        """Manager translates 'csi' -> 'cn' before calling fetchers
        (see ``manager.get_all_stocks`` in stock_data/data_provider/manager.py
        around the ``public_to_fetcher = {"csi": "cn"}`` block).

        ZzshareFetcher must accept ``"cn"`` as a csi alias so the failover
        chain does NOT silently fall through to Akshare when its public
        ``"csi"`` check would have rejected the fetcher-internal tag.

        Regression: 2026-07-03 — Akshare (P3) was winning the
        ``/api/v1/stocks?market=csi`` failover because Zzshare (P2)
        returned ``[]`` whenever the manager called it with ``"cn"``.
        """
        import pandas as pd

        raw = pd.DataFrame(
            {
                "ts_code": ["600519.SH", "000001.SZ"],
                "symbol": ["600519", "000001"],
                "name": ["贵州茅台", "平安银行"],
                "exchange": ["SSE", "SZSE"],
                "area": ["", ""],
                "industry": ["", ""],
                "list_date": ["", ""],
            }
        )
        fetcher = self._fetcher_with_api(raw)
        result = fetcher.get_all_stocks("cn")
        assert len(result) == 2, (
            f"ZzshareFetcher must accept 'cn' as an alias for csi A-shares; "
            f"got {len(result)} rows"
        )
        assert result[0] == {"code": "600519", "name": "贵州茅台", "exchange": "SSE"}
        assert result[1] == {"code": "000001", "name": "平安银行", "exchange": "SZSE"}

    def test_get_all_stocks_unsupported_market_returns_empty(self):
        """Sanity: only csi/cn/hk/us are recognized market tags; anything
        else returns ``[]`` rather than guessing."""
        fetcher = ZzshareFetcher()
        with patch("importlib.util.find_spec", return_value=MagicMock()):
            assert fetcher.get_all_stocks("hk") == []
            assert fetcher.get_all_stocks("us") == []
            assert fetcher.get_all_stocks("garbage") == []

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
        call = ZzshareFetcher._api.stock_basic.call_args
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
        ZzshareFetcher._api = fake_api
        ZzshareFetcher._init_attempted = True
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
        ZzshareFetcher._api = fake_api
        ZzshareFetcher._init_attempted = True
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
        ZzshareFetcher._api = fake_api
        ZzshareFetcher._init_attempted = True
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
        call = ZzshareFetcher._api.uplimit_stocks.call_args
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
            # Caller can pass a list/dict to set ``return_value`` (the
            # historical behaviour) OR a callable to set ``side_effect``
            # for per-argument responses. The plates_rank side-effect form
            # matters now that plate=15 AND plate=17 both map to concept
            # (see ``_BOARD_TYPE_BY_PLATE_TYPE`` unification on 2026-07-07):
            # the upstream returns different rows per plate_type, so the
            # mock needs to as well.
            if callable(value):
                setattr(fake_api, name, MagicMock(side_effect=value))
            else:
                setattr(fake_api, name, MagicMock(return_value=value))
        ZzshareFetcher._api = fake_api
        ZzshareFetcher._init_attempted = True
        return fetcher

    def test_get_all_boards_concept_via_15(self):
        rows = [
            {"plate_code": "801001", "plate_name": "芯片", "plate_type": 15, "rate": 1.5},
            {"plate_code": "801660", "plate_name": "通信", "plate_type": 15, "rate": 0.8},
        ]
        fetcher = self._fetcher_with_api(plates_rank=rows)
        boards = fetcher.get_all_boards(
            board_type="concept", subtype="同花顺概念", source="zzshare"
        )
        assert len(boards) == 2
        assert boards[0]["code"] == "801001"
        assert boards[0]["name"] == "芯片"
        assert boards[0]["type"] == "concept"
        assert boards[0]["subtype"] == "同花顺概念"

    def test_get_all_boards_subtype_mismatch_returns_empty(self):
        # plates_rank is called per plate_type, so a non-matching subtype
        # skips the whole type — no rows fetched.
        rows = [
            {"plate_code": "801001", "plate_name": "芯片", "plate_type": 15, "rate": 1.5},
        ]
        fetcher = self._fetcher_with_api(plates_rank=rows)
        boards = fetcher.get_all_boards(
            board_type="concept", subtype="不存在的子类", source="zzshare"
        )
        assert boards == []
        ZzshareFetcher._api.plates_rank.assert_not_called()

    def test_get_all_boards_industry_via_14(self):
        rows = [
            {"plate_code": "881121", "plate_name": "半导体", "plate_type": 14, "rate": 0.5},
        ]
        fetcher = self._fetcher_with_api(plates_rank=rows)
        boards = fetcher.get_all_boards(
            board_type="industry", subtype="同花顺行业", source="zzshare"
        )
        assert len(boards) == 1
        assert boards[0]["type"] == "industry"

    def test_get_all_boards_17_unified_to_concept(self):
        # zzshare plate_type=17 (题材) is unified with plate=15 under type=concept
        # at the server boundary; subtype retains "同花顺题材" so callers can
        # tell the two upstream buckets apart. Querying board_type="special"
        # against source=zzshare now returns [] because the special type is gone.
        # Mock returns the row only for plate=17 (mirrors a day with no
        # 概念 boards in the upstream feed).
        def plates_rank_by_pt(plate_type, **_):
            if plate_type == 17:
                return [
                    {"plate_code": "881999", "plate_name": "题材", "plate_type": 17, "rate": 2.0},
                ]
            return []

        fetcher = self._fetcher_with_api(plates_rank=plates_rank_by_pt)
        # Unified path: querying concept returns plate=17 rows tagged as
        # type=concept with subtype="同花顺题材" preserved.
        boards = fetcher.get_all_boards(
            board_type="concept", subtype=None, source="zzshare"
        )
        assert len(boards) == 1
        assert boards[0]["type"] == "concept"
        assert boards[0]["subtype"] == "同花顺题材"
        # Subtype-filtered path: querying subtype="同花顺题材" still works and
        # returns the plate=17 row tagged as concept.
        boards_by_subtype = fetcher.get_all_boards(
            board_type="concept", subtype="同花顺题材", source="zzshare"
        )
        assert len(boards_by_subtype) == 1
        assert boards_by_subtype[0]["type"] == "concept"
        assert boards_by_subtype[0]["subtype"] == "同花顺题材"
        # board_type="special" is no longer a valid entry for zzshare —
        # _BOARD_TYPE_BY_PLATE_TYPE has no key that maps back to "special",
        # so the fetcher's outer loop never queries upstream and returns [].
        boards_special = fetcher.get_all_boards(
            board_type="special", subtype=None, source="zzshare"
        )
        assert boards_special == []

    def test_get_all_boards_no_subtype_returns_all_matching_type(self):
        # plate=15 → 概念 rows; plate=17 → 题材 rows. The fetcher now queries
        # both (unified under concept), so the mock has to discriminate by
        # plate_type to mirror real upstream behaviour.
        def plates_rank_by_pt(plate_type, **_):
            return {
                15: [
                    {"plate_code": "801001", "plate_name": "芯片", "plate_type": 15, "rate": 1.5},
                    {"plate_code": "801002", "plate_name": "通信", "plate_type": 15, "rate": 0.8},
                ],
                17: [
                    {"plate_code": "881999", "plate_name": "题材A", "plate_type": 17, "rate": 2.0},
                ],
            }.get(plate_type, [])

        fetcher = self._fetcher_with_api(plates_rank=plates_rank_by_pt)
        boards = fetcher.get_all_boards(board_type="concept", subtype=None, source="zzshare")
        # All 概念 + 题材 rows come back, tagged with their per-row subtype.
        # No quote fields without include_quote.
        assert len(boards) == 3
        assert {b["code"] for b in boards} == {"801001", "801002", "881999"}
        assert {b["subtype"] for b in boards} == {"同花顺概念", "同花顺题材"}
        assert set(boards[0].keys()) == {"code", "name", "type", "subtype"}

    def test_get_all_boards_without_quote_is_bare(self):
        # include_quote=False must not leak raw plates_rank columns.
        rows = [dict(self._RANK_ROW)]
        fetcher = self._fetcher_with_api(plates_rank=rows)
        boards = fetcher.get_all_boards(
            board_type="concept", source="zzshare", include_quote=False
        )
        assert boards[0].keys() == {"code", "name", "type", "subtype"}
        assert "change_pct" not in boards[0]
        assert "score" not in boards[0]

    # ---- include_quote=True -> plates_rank path ----

    # Real plates_rank row shape (probed 2026-07-06); rate/trade_money/
    # market_cap_cir overlap the schema, the rest are zzshare-specific.
    _RANK_ROW = {
        "date1": "2026-07-06",
        "plate_name": "送转填权",
        "plate_type": 15,
        "score": 817,
        "money_leader": 1150450.0,
        "trade_money": 68171800.0,
        "money_leader_sell": -6902100.0,
        "market_cap_cir": 2783750000.0,
        "plate_code": "885796",
        "id": 975682,
        "rate": 8.178,
        "speed": -0.26,
        "money_leader_buy": 8052560.0,
        "volume_ration": 2.463,
        "time": "2026-07-06 13:01:03",
    }

    def test_get_all_boards_include_quote_uses_plates_rank(self):
        # plate=17 returns [] in this mock to keep the assertion focused on
        # the plate=15 schema mapping (mirrors a day with no 题材 boards).
        def plates_rank_by_pt(plate_type, **_):
            if plate_type == 15:
                return [dict(self._RANK_ROW)]
            return []

        fetcher = self._fetcher_with_api(plates_rank=plates_rank_by_pt)
        with patch(
            "stock_data.data_provider.fetchers.zzshare_fetcher."
            "get_latest_trade_date_on_or_before",
            return_value="2026-07-06",
        ):
            boards = fetcher.get_all_boards(
                board_type="concept", source="zzshare", include_quote=True
            )
        # plates_rank used, plates_list untouched
        ZzshareFetcher._api.plates_rank.assert_called()
        ZzshareFetcher._api.plates_list.assert_not_called()
        assert len(boards) == 1
        b = boards[0]
        # schema keys
        assert b["code"] == "885796"
        assert b["name"] == "送转填权"
        assert b["type"] == "concept"
        assert b["change_pct"] == pytest.approx(8.178)
        assert b["amount"] == pytest.approx(68171800.0)
        assert b["total_mv"] == pytest.approx(2783750000.0)

    def test_get_all_boards_include_quote_preserves_raw_columns(self):
        def plates_rank_by_pt(plate_type, **_):
            if plate_type == 15:
                return [dict(self._RANK_ROW)]
            return []

        fetcher = self._fetcher_with_api(plates_rank=plates_rank_by_pt)
        with patch(
            "stock_data.data_provider.fetchers.zzshare_fetcher."
            "get_latest_trade_date_on_or_before",
            return_value="2026-07-06",
        ):
            boards = fetcher.get_all_boards(
                board_type="concept", source="zzshare", include_quote=True
            )
        b = boards[0]
        # zzshare-specific columns kept verbatim on the dict
        assert b["score"] == 817
        assert b["speed"] == pytest.approx(-0.26)
        assert b["volume_ration"] == pytest.approx(2.463)
        assert b["money_leader"] == pytest.approx(1150450.0)

    def test_get_all_boards_include_quote_requests_full_set(self):
        # Both plate=15 AND plate=17 are now queried for type=concept;
        # the test asserts the union of plate_types was used.
        def plates_rank_by_pt(plate_type, **_):
            if plate_type == 15:
                return [dict(self._RANK_ROW)]
            return []

        fetcher = self._fetcher_with_api(plates_rank=plates_rank_by_pt)
        with patch(
            "stock_data.data_provider.fetchers.zzshare_fetcher."
            "get_latest_trade_date_on_or_before",
            return_value="2026-07-06",
        ):
            fetcher.get_all_boards(
                board_type="concept", source="zzshare", include_quote=True
            )
        # Both plate_type=15 and plate_type=17 must have been requested.
        plate_types_called = {
            c.kwargs["plate_type"] for c in ZzshareFetcher._api.plates_rank.call_args_list
        }
        assert 15 in plate_types_called
        assert 17 in plate_types_called
        # Every call shared the same date + unbounded limit.
        for c in ZzshareFetcher._api.plates_rank.call_args_list:
            assert c.kwargs["date1"] == "2026-07-06"
            assert c.kwargs["limit"] >= 100000

    def test_get_all_boards_include_quote_falls_back_to_today(self):
        fetcher = self._fetcher_with_api(plates_rank=[dict(self._RANK_ROW)])
        # empty trade-calendar cache -> None -> today's date used
        with patch(
            "stock_data.data_provider.fetchers.zzshare_fetcher."
            "get_latest_trade_date_on_or_before",
            return_value=None,
        ):
            fetcher.get_all_boards(
                board_type="concept", source="zzshare", include_quote=True
            )
        call = ZzshareFetcher._api.plates_rank.call_args
        # a non-empty YYYY-MM-DD date was still passed
        assert call.kwargs["date1"]
        assert len(call.kwargs["date1"]) == 10

    def test_get_board_stocks_returns_bare_6digit_codes(self):
        """Inbound API response uses bare 6-digit code (e.g. '600519'), NOT
        tushare-style '600519.SH' — same contract as EastMoney / Zhitu /
        other Zzshare response methods. The tushare suffix is OUTBOUND only.
        """
        rows = [
            {"stock_code": "600519", "stock_name": "贵州茅台", "exchange": "sh"},
            {"stock_code": "000001", "stock_name": "平安银行", "exchange": "sz"},
        ]
        fetcher = self._fetcher_with_api(plates_stocks=rows)
        stocks = fetcher.get_board_stocks("801001", source="zzshare")
        assert stocks[0]["stock_code"] == "600519"
        assert stocks[1]["stock_code"] == "000001"
        assert stocks[0]["stock_name"] == "贵州茅台"
        # exchange field is passed through (may be empty if upstream doesn't populate)
        assert stocks[0]["exchange"] == "sh"
        assert stocks[1]["exchange"] == "sz"


# NOTE: get_board_history tests removed (2026-07-03) — ZzshareFetcher no longer
# implements get_board_history (upstream `plate_kline` only supports 883957).
# The board-history route now aliases `source=zzshare` → `source=ths`; the
# equivalent coverage lives in tests/test_boards_history_route.py (alias
# behavior) and tests/test_boards_api.py (source=ths happy path).

# ====================================================================
# DRAGON_TIGER
# ====================================================================


class TestDragonTiger:
    def _fetcher_with_api(self, **mocks):
        fetcher = ZzshareFetcher()
        fake_api = MagicMock()
        for name, value in mocks.items():
            setattr(fake_api, name, MagicMock(return_value=value))
        ZzshareFetcher._api = fake_api
        ZzshareFetcher._init_attempted = True
        return fetcher

    def test_daily_dragon_tiger_returns_bare_6digit_codes(self):
        """Inbound API response uses bare 6-digit code (e.g. '000078'), NOT
        tushare-style '000078.SZ' — same contract as EastMoney / other
        Zzshare response methods. The tushare suffix is OUTBOUND only.
        """
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
        # Bare 6-digit code (NOT '000078.SZ' — tushare suffix is outbound only)
        assert data["stocks"][0]["code"] == "000078"
        assert data["stocks"][0]["name"] == "海王生物"
        # net_buy_wan (万元) — upstream buy_in=1e8 元 → 10000.0 万元
        assert data["stocks"][0]["net_buy_wan"] == 10000.0
        # zzshare lhb_list does NOT provide close / buy_wan / sell_wan upstream
        # and they cannot be derived (circ_price/capitalization are 元 not shares;
        # turnover is full-day total, not lhb-only buy+sell). Fetcher OMITS
        # these keys; DailyDragonTigerStock schema defaults them to None.
        # We verify via the schema (Pydantic) rather than the dict directly,
        # because route layer does DailyDragonTigerStock(**s).
        from stock_data.api.schemas import DailyDragonTigerStock
        validated = DailyDragonTigerStock(**data["stocks"][0])
        assert validated.close is None
        assert validated.buy_wan is None
        assert validated.sell_wan is None
        assert validated.change_pct == 10.0
        assert validated.turnover_pct == 8.5
        assert validated.reason == "涨幅偏离值达7%"
        # change_pct (upstream quote_change=10.0)
        assert data["stocks"][0]["change_pct"] == 10.0
        # turnover_pct (NOT turnover_rate — schema name); upstream turnover_ratio=8.5
        assert data["stocks"][0]["turnover_pct"] == 8.5
        # No extraneous fields — output is a strict subset of DailyDragonTigerStock schema
        stock_keys = set(data["stocks"][0].keys())
        expected_keys = {
            "code", "name", "reason", "change_pct",
            "net_buy_wan", "turnover_pct",
        }
        assert stock_keys == expected_keys, (
            f"unexpected fields: {stock_keys - expected_keys}; "
            f"missing: {expected_keys - stock_keys}"
        )

    def test_daily_dragon_tiger_min_net_buy_filter(self):
        """min_net_buy is in 万元 (per route description at routes/data.py).
        Filter must compare against net_buy_wan, NOT raw yuan buy_in.

        buy_in=5e7 (元) = 5000.0 wan — below 10000.0 wan threshold → filtered.
        buy_in=2e8 (元) = 20000.0 wan — above threshold → kept.
        """
        rows = [
            {"stock_code": "000078", "stock_name": "A", "buy_in": 5e7},
            {"stock_code": "600519", "stock_name": "B", "buy_in": 2e8},
        ]
        fetcher = self._fetcher_with_api(lhb_list=rows)
        data = fetcher.get_daily_dragon_tiger("2026-05-20", 10000.0)
        # Only stock with net_buy_wan >= 10000.0 (i.e. raw buy_in >= 1e8) survives.
        assert data["total"] == 1
        assert data["stocks"][0]["code"] == "600519"
        assert data["stocks"][0]["net_buy_wan"] == 20000.0

    def test_daily_dragon_tiger_empty_returns_zeros(self):
        fetcher = self._fetcher_with_api(lhb_list=[])
        data = fetcher.get_daily_dragon_tiger("2026-05-20", None)
        assert data["date"] == "2026-05-20"
        assert data["total"] == 0
        assert data["stocks"] == []

    def test_dragon_tiger_uses_detail(self):
        """lhb_detail returns dict {detail: {...}, traders: [...]}.
        Per-trader rows have trader_name / buy_amount / sell_amount / type
        (real upstream field names). Real probe (000004 on 2025-05-13):
        10 trader rows for 6 unique names, type distribution {1: 5, 2: 5}.
        type=1 → 买入侧排行行, type=2 → 卖出侧排行行. Each row pushed
        ONCE to seats["buy"] or seats["sell"] by type, with the full
        buy_wan/sell_wan/net_wan triple derived from that row's
        buy_amount/sell_amount (NOT zero-padded on the unused side).
        """
        detail = {
            "detail": {
                "stock_code": "000078",
                "buy_in": 1.5e8,
                "buy_total": 2.0e8,
                "sell_total": 5.0e7,
                "join_num": 2,
                "up_reason": "日涨幅偏离值达7%",
            },
            "traders": [
                # 2 type=1 (买入侧) rows
                {
                    "trader_name": "东方证券绍兴解放南路营业部",
                    "buy_amount": 1.0e8,
                    "sell_amount": 5.0e7,
                    "rank": 1,
                    "type": 1,
                },
                {
                    "trader_name": "华泰证券深圳益田路荣超商务中心",
                    "buy_amount": 5.0e7,
                    "sell_amount": 3.0e7,
                    "rank": 2,
                    "type": 1,
                },
                # 1 type=2 (卖出侧) row — same trader as the first one
                # (in real data a top-N trader often appears on both sides)
                {
                    "trader_name": "东方证券绍兴解放南路营业部",
                    "buy_amount": 8.0e7,
                    "sell_amount": 6.0e7,
                    "rank": 1,
                    "type": 2,
                },
            ],
        }
        # lhb_stock_history stub: returns nothing so records stays empty
        # under this test (we only assert seats here).
        fetcher = self._fetcher_with_api(
            lhb_detail=detail, lhb_stock_history=[]
        )
        data = fetcher.get_dragon_tiger("000078", "2026-05-20", 30)
        assert "seats" in data
        # 2 type=1 rows → seats["buy"] has 2; 1 type=2 row → seats["sell"] has 1
        assert len(data["seats"]["buy"]) == 2
        assert len(data["seats"]["sell"]) == 1
        # First buy seat (type=1): full triple from buy_amount=1e8, sell_amount=5e7
        first_buy = data["seats"]["buy"][0]
        assert first_buy["name"] == "东方证券绍兴解放南路营业部"
        assert first_buy["buy_wan"] == 10000.0
        assert first_buy["sell_wan"] == 5000.0  # NOT 0.0 — full triple
        assert first_buy["net_wan"] == 5000.0  # buy - sell
        # Sell seat (type=2): full triple from buy_amount=8e7, sell_amount=6e7
        first_sell = data["seats"]["sell"][0]
        assert first_sell["name"] == "东方证券绍兴解放南路营业部"
        assert first_sell["buy_wan"] == 8000.0
        assert first_sell["sell_wan"] == 6000.0
        assert first_sell["net_wan"] == 2000.0  # buy - sell
        # Institution is left empty (TODO; type field is buy/sell side,
        # not institution-vs-brokerage discriminator).
        assert data["institution"] == {"buy_amt": 0, "sell_amt": 0, "net_amt": 0}

    def test_dragon_tiger_records_filtered_by_look_back(self):
        """records come from lhb_stock_history, filtered client-side to
        [trade_date - look_back, trade_date]. lhb_stock_history does NOT
        accept a date range upstream, so the filter is local.
        """
        fetcher = self._fetcher_with_api(
            lhb_detail=None,
            lhb_stock_history=[
                {"date": "2026-05-10", "buy_in": 1.0e7, "quote_change": 5.0,
                 "t_icon": None, "t_type": 0},
                {"date": "2026-05-15", "buy_in": 2.0e7, "quote_change": 5.0,
                 "t_icon": None, "t_type": 0},
                {"date": "2026-05-20", "buy_in": 3.0e7, "quote_change": 5.0,
                 "t_icon": None, "t_type": 0},
                {"date": "2026-05-25", "buy_in": 4.0e7, "quote_change": 5.0,
                 "t_icon": None, "t_type": 0},
            ],
        )
        # look_back=7 days from trade_date=2026-05-20 → window [05-13, 05-20]
        data = fetcher.get_dragon_tiger("000078", "2026-05-20", 7)
        assert len(data["records"]) == 2
        dates = {r["date"] for r in data["records"]}
        assert dates == {"2026-05-15", "2026-05-20"}
        # 2026-05-20 record net_buy_wan = 3.0e7 / 10000 = 3000.0
        rec_today = next(r for r in data["records"] if r["date"] == "2026-05-20")
        assert rec_today["net_buy_wan"] == 3000.0

    def test_dragon_tiger_records_unfiltered_when_no_trade_date(self):
        """When trade_date is empty, records return the full history list."""
        fetcher = self._fetcher_with_api(
            lhb_detail=None,
            lhb_stock_history=[
                {"date": "2026-05-10", "buy_in": 1.0e7, "quote_change": 5.0,
                 "t_icon": None, "t_type": 0},
                {"date": "2026-05-20", "buy_in": 2.0e7, "quote_change": 5.0,
                 "t_icon": None, "t_type": 0},
            ],
        )
        data = fetcher.get_dragon_tiger("000078", "", 30)
        assert len(data["records"]) == 2

    def test_dragon_tiger_falls_back_to_stock_history(self):
        """Even when lhb_detail returns empty/None, lhb_stock_history is
        still queried for records (records are NOT behind the detail branch
        anymore — they're independently populated).

        Real upstream `lhb_stock_history(stock_code=...)` returns rows keyed
        [buy_in, date, quote_change, t_icon, t_type] (NO trade_date, NO reason).
        Records must conform to DragonTigerRecord schema (date / reason /
        net_buy_wan / turnover_pct, with net_buy_wan converted from raw yuan
        to 万元). turnover_pct stays 0.0 since upstream has no turnover field
        (only quote_change, which is a different metric).
        """
        fetcher = self._fetcher_with_api(
            lhb_detail=None,  # upstream returned None / unavailable
            lhb_stock_history=[
                {
                    "date": "2026-05-15",
                    "buy_in": 5.0e7,  # 5000 万 = 5000.0 wan
                    "quote_change": 10.0,
                    "t_icon": None,
                    "t_type": 0,
                },
            ],
        )
        data = fetcher.get_dragon_tiger("000078", "2026-05-20", 30)
        assert len(data["records"]) == 1
        rec = data["records"][0]
        assert rec["date"] == "2026-05-15"
        assert rec["net_buy_wan"] == 5000.0  # yuan / 10000 → wan
        # reason not in upstream lhb_stock_history; stays empty
        assert rec["reason"] == ""
        # turnover_pct not in upstream lhb_stock_history; stays 0.0
        assert rec["turnover_pct"] == 0.0

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
        call = ZzshareFetcher._api.lhb_list.call_args
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
        ZzshareFetcher._api = fake_api
        ZzshareFetcher._init_attempted = True
        return fetcher

    def test_hot_topics_returns_bare_6digit_codes(self):
        """Inbound API response uses bare 6-digit code (e.g. '002342'), NOT
        tushare-style '002342.SZ' — same contract as ThsFetcher / other
        Zzshare response methods. The tushare suffix is OUTBOUND only.
        """
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
        # Bare 6-digit code (NOT '002342.SZ' — tushare suffix is outbound only)
        assert topics[0]["code"] == "002342"
        assert topics[0]["name"] == "巨力索具"
        assert topics[0]["change_pct"] == 10.0
        assert topics[0]["rank"] == 1
        # Bare 6-digit code (NOT '600519.SH' — tushare suffix is outbound only)
        assert topics[1]["code"] == "600519"

    def test_hot_topics_empty_returns_empty_list(self):
        fetcher = self._fetcher_with_api([])
        assert fetcher.get_hot_topics("2026-05-20") == []

    def test_hot_topics_uses_today_when_date_empty(self):
        fetcher = self._fetcher_with_api([])
        fetcher.get_hot_topics("")  # empty -> today
        call = ZzshareFetcher._api.ths_hot_top.call_args
        # date1 should be today's YYYYMMDD
        from datetime import date

        expected = date.today().strftime("%Y%m%d")
        assert call.kwargs.get("date1") == expected

    def test_hot_topics_default_top_n(self):
        fetcher = self._fetcher_with_api([])
        fetcher.get_hot_topics("2026-05-20")
        call = ZzshareFetcher._api.ths_hot_top.call_args
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

    def test_zzshare_special_subtype_collapsed_into_concept(self):
        """zzshare plate=17 (题材) no longer maps to a standalone "special" type.

        Both plate=15 (概念) and plate=17 (题材) collapse into ``concept`` at
        the server boundary; subtype carries the original label so callers
        can filter them. The persistence subtype table reflects this by
        dropping the orphan "special" key and folding "同花顺题材" into the
        "concept" set.
        """
        from stock_data.data_provider.persistence.board import VALID_SUBTYPES_BY_SOURCE

        zzshare_types = VALID_SUBTYPES_BY_SOURCE["zzshare"]
        # "special" type is gone for zzshare — only industry + concept remain.
        assert "special" not in zzshare_types
        assert set(zzshare_types.keys()) == {"industry", "concept"}
        # The two zzshare subtypes now live under "concept".
        assert "同花顺概念" in zzshare_types["concept"]
        assert "同花顺题材" in zzshare_types["concept"]

    def test_ths_concept_subtype_constant_shared_with_persistence(self):
        """THS_CONCEPT_SUBTYPE 必须等于 VALID_SUBTYPES_BY_SOURCE['ths']['concept'].

        锁定 fetcher 输出的 subtype 与 persistence 验证器的 subtype 来自同一
        常量,避免改一个不改另一个的静默漂移。
        """
        from stock_data.data_provider.persistence.board import (
            THS_CONCEPT_SUBTYPE,
            VALID_SUBTYPES_BY_SOURCE,
        )

        assert THS_CONCEPT_SUBTYPE in VALID_SUBTYPES_BY_SOURCE["ths"]["concept"]
        assert (
            THS_CONCEPT_SUBTYPE
            in VALID_SUBTYPES_BY_SOURCE["zzshare"]["concept"]
        )


# ====================================================================
# _normalize_data minute branch
# ====================================================================


class TestNormalizeMinute:
    """Tests for _normalize_data minute branch."""

    def test_normalize_minute_extracts_date_from_trade_time(self):
        """trade_time (YYYYMMDDHHMM, 12 digits) → date column (YYYY-MM-DD)."""
        import pandas as pd

        fetcher = ZzshareFetcher()
        raw = pd.DataFrame({
            "ts_code": ["600519.SH"] * 4,
            "trade_time": ["202605200935", "202605200940", "202605210935", "202605210940"],
            "open": [1700.0, 1705.0, 1710.0, 1715.0],
            "high": [1708.0, 1712.0, 1718.0, 1723.0],
            "low": [1698.0, 1702.0, 1708.0, 1713.0],
            "close": [1705.0, 1710.0, 1715.0, 1720.0],
            "vol": [1e5, 1.1e5, 1.2e5, 1.3e5],
            "amount": [1e8, 1.1e8, 1.2e8, 1.3e8],
        })
        out = fetcher._normalize_data(raw, "600519")
        assert "date" in out.columns
        # trade_time[0:8] = "20260520" → "2026-05-20"
        dates = sorted(out["date"].astype(str).unique())
        assert dates == ["2026-05-20", "2026-05-21"]
        # vol renamed to volume
        assert "volume" in out.columns
        assert "vol" not in out.columns
        # No time column (lost per spec §3.1)
        assert "time" not in out.columns
