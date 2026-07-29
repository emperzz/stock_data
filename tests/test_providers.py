"""
Tests for individual provider fetchers - directly testing each provider's internal APIs.

Each fetcher's _fetch_raw_data, _normalize_data, get_realtime_quote, and
get_stock_name should be tested in isolation, NOT through the manager or server.

Note: These tests make real API calls to external services (yfinance, akshare, baostock, tushare).
Due to rate limiting, some tests may fail intermittently. The ``@pytest.mark.live_network``
markers below let ``tests/conftest.py`` reclassify upstream/network errors as ``x`` (xfail)
rather than ``F`` (failed), so a flake is not mistaken for a regression. See
``tests/_network_guard.py`` for the full legend.
"""

import time
from datetime import datetime, timedelta

import pytest

# All tests in this module are integration tests that hit real upstream
# APIs. Mark at module level so the conftest hook converts network errors
# to xfail (see tests/_network_guard.py for details).
pytestmark = pytest.mark.live_network


@pytest.fixture(autouse=True)
def rate_limit_delay():
    """Add delay between tests to avoid rate limiting."""
    time.sleep(0.5)
    yield


class TestBaostockFetcher:
    """Tests for BaostockFetcher."""

    @pytest.fixture
    def fetcher(self):
        from stock_data.data_provider.fetchers.baostock_fetcher import BaostockFetcher

        return BaostockFetcher()

    def test_is_available(self, fetcher):
        """Test that Baostock is available (login succeeds)."""
        assert fetcher.is_available() is True

    def test_fetch_daily_data(self, fetcher):
        """Test _fetch_raw_data returns DataFrame."""
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

        df = fetcher._fetch_raw_data("600519", start_date, end_date)
        assert df is not None
        assert len(df) > 0

    def test_normalize_data(self, fetcher):
        """Test _normalize_data produces standard columns."""
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

        raw_df = fetcher._fetch_raw_data("600519", start_date, end_date)
        df = fetcher._normalize_data(raw_df, "600519")

        assert "date" in df.columns
        assert "open" in df.columns
        assert "high" in df.columns
        assert "low" in df.columns
        assert "close" in df.columns
        assert "volume" in df.columns
        assert "pct_chg" in df.columns

    def test_get_kline_data(self, fetcher):
        """Test get_daily_data returns DataFrame with the standard columns.

        Technical indicators (MA/MACD/etc.) are no longer auto-computed
        in the fetcher's K-line path. They live behind the indicator
        layer and the `?indicators=` query param.
        """
        df = fetcher.get_kline_data("600519", days=10)
        assert df is not None
        assert len(df) > 0
        # Standard K-line columns must still be present
        for col in ("date", "open", "high", "low", "close", "volume"):
            assert col in df.columns
        # Indicator columns must NOT be present
        assert "ma5" not in df.columns
        assert "ma10" not in df.columns
        assert "ma20" not in df.columns
        assert "volume_ratio" not in df.columns

    def test_realtime_quote_returns_none(self, fetcher):
        """Verify Baostock does NOT support realtime quotes.

        The base ``get_realtime_quote`` returns None (no upstream API),
        and Baostock does not override it. Documented here so a
        regression that re-introduces a stub implementation is caught.
        """
        result = fetcher.get_realtime_quote("600519")
        assert result is None


class TestAkshareFetcher:
    """Tests for AkshareFetcher."""

    @pytest.fixture
    def fetcher(self):
        from stock_data.data_provider.fetchers.akshare import AkshareFetcher

        return AkshareFetcher()

    def test_fetch_a_share_daily(self, fetcher):
        """Test _fetch_raw_data for A-share."""
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

        df = fetcher._fetch_raw_data("600519", start_date, end_date)
        assert df is not None
        assert len(df) > 0

    def test_fetch_hk_daily(self, fetcher):
        """Test _fetch_raw_data for HK stock."""
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

        df = fetcher._fetch_raw_data("HK00700", start_date, end_date)
        assert df is not None
        assert len(df) > 0

    def test_normalize_a_share(self, fetcher):
        """Test _normalize_data for A-share."""
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

        raw_df = fetcher._fetch_raw_data("600519", start_date, end_date)
        df = fetcher._normalize_data(raw_df, "600519")

        assert "date" in df.columns
        assert "close" in df.columns
        assert "volume" in df.columns

    def test_normalize_hk(self, fetcher):
        """Test _normalize_data for HK stock."""
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

        raw_df = fetcher._fetch_raw_data("HK00700", start_date, end_date)
        df = fetcher._normalize_data(raw_df, "HK00700")

        assert "date" in df.columns
        assert "close" in df.columns

    def test_get_realtime_a_share(self, fetcher):
        """Test get_realtime_quote for A-share."""
        result = fetcher.get_realtime_quote("600519")
        assert result is not None
        assert result.code == "600519"
        assert result.price is not None
        assert result.price > 0

    def test_get_realtime_hk(self, fetcher):
        """Test get_realtime_quote for HK stock."""
        result = fetcher.get_realtime_quote("HK00700")
        assert result is not None
        assert result.price is not None
        assert result.price > 0

    def test_get_kline_data(self, fetcher):
        """Test get_kline_data returns standard columns only (no inline indicators).

        Indicators (MA/MACD/etc.) live behind the indicator layer and
        the `?indicators=` query param — they must NOT appear in the
        raw fetcher output. Mirrors ``TestBaostockFetcher.test_get_kline_data``.
        """
        df = fetcher.get_kline_data("600519", days=10)
        assert df is not None
        assert len(df) > 0
        for col in ("date", "open", "high", "low", "close", "volume"):
            assert col in df.columns
        assert "ma5" not in df.columns
        assert "ma10" not in df.columns
        assert "ma20" not in df.columns


class TestAkshareSpotRowNormalize:
    """Unit tests for AkshareFetcher._normalize_spot_row."""

    def _fetcher(self):
        # Lazy import to avoid loading akshare at test collection time
        from stock_data.data_provider.fetchers.akshare.fetcher import AkshareFetcher
        return AkshareFetcher()

    def test_normalize_spot_row_basic_fields(self):
        fetcher = self._fetcher()
        row = {
            "代码": "600519",
            "名称": "贵州茅台",
            "最新价": 1680.5,
            "涨跌幅": 1.23,
            "涨跌额": 20.5,
            "成交量": 12345,        # 手
            "成交额": 2.07e8,
            "今开": 1680.0,
            "最高": 1685.0,
            "最低": 1678.0,
            "昨收": 1660.0,
            "振幅": 0.4,
            "换手率": 0.5,
            "量比": 1.2,
            "市盈率": 28.5,
            "市净率": 9.1,
        }
        from stock_data.data_provider.core.types import RealtimeSource
        quote = fetcher._normalize_spot_row(row, "600519")
        assert quote.code == "600519"
        assert quote.name == "贵州茅台"
        assert quote.source == RealtimeSource.AKSHARE
        assert quote.price == 1680.5
        assert quote.change_pct == 1.23
        assert quote.change_amount == 20.5
        assert quote.volume == 12345 * 100     # 手 → 股 (spec §3.4)
        assert quote.amount == 2.07e8
        assert quote.open_price == 1680.0
        assert quote.high == 1685.0
        assert quote.low == 1678.0
        assert quote.pre_close == 1660.0
        assert quote.amplitude == 0.4
        assert quote.turnover_rate == 0.5
        assert quote.volume_ratio == 1.2
        assert quote.pe_ratio == 28.5
        assert quote.pb_ratio == 9.1

    def test_normalize_spot_row_missing_fields_returns_none(self):
        """Missing optional fields → None, not crash."""
        fetcher = self._fetcher()
        row = {"代码": "000001", "名称": "平安银行"}  # minimal row
        quote = fetcher._normalize_spot_row(row, "000001")
        assert quote.code == "000001"
        assert quote.name == "平安银行"
        assert quote.price is None
        assert quote.change_pct is None
        assert quote.volume is None  # safe_int(0) * 100 = 0, not None


class TestAkshareGetRealtimeQuotes:
    """Tests for AkshareFetcher.get_realtime_quotes (all-market)."""

    def _fetcher(self):
        from stock_data.data_provider.fetchers.akshare.fetcher import AkshareFetcher
        return AkshareFetcher()

    def test_get_realtime_quotes_csi(self, monkeypatch):
        """Single ak.stock_zh_a_spot_em() call → list of UnifiedRealtimeQuote."""
        import pandas as pd

        fake_df = pd.DataFrame([
            {"代码": "600519", "名称": "贵州茅台", "最新价": 1680.5, "涨跌幅": 1.23,
             "涨跌额": 20.5, "成交量": 12345, "成交额": 2.07e8, "今开": 1680.0,
             "最高": 1685.0, "最低": 1678.0, "昨收": 1660.0, "振幅": 0.4,
             "换手率": 0.5, "量比": 1.2, "市盈率": 28.5, "市净率": 9.1},
            {"代码": "000001", "名称": "平安银行", "最新价": 12.5, "涨跌幅": -0.5,
             "涨跌额": -0.06, "成交量": 80000, "成交额": 1.0e8, "今开": 12.6,
             "最高": 12.7, "最低": 12.4, "昨收": 12.56, "振幅": 2.4,
             "换手率": 0.3, "量比": 0.8, "市盈率": 5.2, "市净率": 0.6},
        ])

        def fake_spot_em():
            return fake_df
        import akshare
        monkeypatch.setattr(akshare, "stock_zh_a_spot_em", fake_spot_em)

        fetcher = self._fetcher()
        quotes = fetcher.get_realtime_quotes("csi")
        assert quotes is not None
        assert len(quotes) == 2
        codes = {q.code for q in quotes}
        assert codes == {"600519", "000001"}
        maotai = next(q for q in quotes if q.code == "600519")
        assert maotai.name == "贵州茅台"
        assert maotai.price == 1680.5

    def test_get_realtime_quotes_returns_none_on_failure(self, monkeypatch):
        """Upstream exception → None (not raise)."""
        def fake_spot_em():
            raise ConnectionError("akshare network down")
        import akshare
        monkeypatch.setattr(akshare, "stock_zh_a_spot_em", fake_spot_em)

        fetcher = self._fetcher()
        assert fetcher.get_realtime_quotes("csi") is None

    def test_get_realtime_quotes_returns_none_on_empty_df(self, monkeypatch):
        """Empty upstream response → None."""
        import pandas as pd
        import akshare
        monkeypatch.setattr(akshare, "stock_zh_a_spot_em", lambda: pd.DataFrame())

        fetcher = self._fetcher()
        assert fetcher.get_realtime_quotes("csi") is None

    def test_get_realtime_quotes_unsupported_market_returns_none(self):
        """market other than csi/cn → None (no all-market source)."""
        fetcher = self._fetcher()
        assert fetcher.get_realtime_quotes("hk") is None
        assert fetcher.get_realtime_quotes("us") is None


class TestYfinanceFetcher:
    """Tests for YfinanceFetcher."""

    @pytest.fixture
    def fetcher(self):
        from stock_data.data_provider.fetchers.yfinance_fetcher import YfinanceFetcher

        return YfinanceFetcher()

    def test_is_available(self, fetcher):
        """Test yfinance is installed."""
        assert fetcher.is_available() is True

    def test_fetch_us_stock(self, fetcher):
        """Test _fetch_raw_data for US stock."""
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

        df = fetcher._fetch_raw_data("AAPL", start_date, end_date)
        assert df is not None
        assert len(df) > 0

    def test_fetch_us_index(self, fetcher):
        """Test _fetch_raw_data for US index."""
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

        df = fetcher._fetch_raw_data("SPX", start_date, end_date)
        assert df is not None
        assert len(df) > 0

    def test_normalize_us_stock(self, fetcher):
        """Test _normalize_data for US stock."""
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

        raw_df = fetcher._fetch_raw_data("AAPL", start_date, end_date)
        df = fetcher._normalize_data(raw_df, "AAPL")

        assert "date" in df.columns
        assert "close" in df.columns
        assert "volume" in df.columns

    def test_get_realtime_us_stock(self, fetcher):
        """Test get_realtime_quote for US stock."""
        result = fetcher.get_realtime_quote("AAPL")
        assert result is not None
        assert result.code == "AAPL"
        assert result.price is not None
        assert result.price > 0

    def test_get_realtime_us_index(self, fetcher):
        """Test get_realtime_quote for US index."""
        result = fetcher.get_realtime_quote("SPX")
        assert result is not None
        assert result.price is not None

    def test_get_kline_data(self, fetcher):
        """Test get_kline_data returns standard columns only (no inline indicators).

        Indicators (MA/MACD/etc.) live behind the indicator layer and
        the `?indicators=` query param — they must NOT appear in the
        raw fetcher output.
        """
        df = fetcher.get_kline_data("AAPL", days=10)
        assert df is not None
        assert len(df) > 0
        for col in ("date", "open", "high", "low", "close", "volume"):
            assert col in df.columns
        assert "ma5" not in df.columns
        assert "ma10" not in df.columns
        assert "ma20" not in df.columns


class TestYfinanceCodeConversion:
    """Unit tests for YfinanceFetcher._convert_code index suffix logic."""

    @staticmethod
    def _make_fetcher():
        from stock_data.data_provider.fetchers.yfinance_fetcher import YfinanceFetcher

        return YfinanceFetcher()

    def test_shanghai_csi_index_uses_ss(self):
        """Shanghai-based CSI indices (000xxx) use .SS suffix."""
        f = self._make_fetcher()
        assert f._convert_code("000300") == "000300.SS"
        assert f._convert_code("000001") == "000001.SS"
        assert f._convert_code("000016") == "000016.SS"

    def test_shenzhen_csi_index_uses_sz(self):
        """Shenzhen-based CSI indices (399xxx) use .SZ suffix."""
        f = self._make_fetcher()
        assert f._convert_code("399001") == "399001.SZ"
        assert f._convert_code("399006") == "399006.SZ"
        assert f._convert_code("399005") == "399005.SZ"

    def test_us_stock_unchanged(self):
        """US stock codes pass through unchanged."""
        f = self._make_fetcher()
        assert f._convert_code("AAPL") == "AAPL"

    def test_a_share_shanghai_uses_ss(self):
        """Shanghai A-share (6xxxxx) use .SS suffix."""
        f = self._make_fetcher()
        assert f._convert_code("600519") == "600519.SS"

    def test_a_share_shenzhen_uses_sz(self):
        """Shenzhen A-share (00xxxx non-index, 3xxxxx) use .SZ suffix."""
        f = self._make_fetcher()
        assert f._convert_code("000651") == "000651.SZ"  # 格力电器, not an index
        assert f._convert_code("300750") == "300750.SZ"  # 宁德时代


class TestTushareFetcher:
    """Tests for TushareFetcher."""

    @pytest.fixture
    def fetcher(self):
        from stock_data.data_provider.fetchers.tushare_fetcher import TushareFetcher

        return TushareFetcher()

    def test_token_configured(self, fetcher):
        """Test Tushare token is configured."""
        import os

        token = os.getenv("TUSHARE_TOKEN", "")
        if not token:
            pytest.skip("TUSHARE_TOKEN not set")
        assert token != ""

    def test_is_available(self, fetcher):
        """Test Tushare API is available."""
        if not fetcher.is_available():
            pytest.skip("TUSHARE_TOKEN not set or invalid")

    def test_fetch_daily_data(self, fetcher):
        """Test _fetch_raw_data returns DataFrame."""
        if not fetcher.is_available():
            pytest.skip("TUSHARE_TOKEN not set or invalid")

        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

        df = fetcher._fetch_raw_data("600519", start_date, end_date)
        assert df is not None
        assert len(df) > 0

    def test_normalize_data(self, fetcher):
        """Test _normalize_data produces standard columns."""
        if not fetcher.is_available():
            pytest.skip("TUSHARE_TOKEN not set or invalid")

        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

        raw_df = fetcher._fetch_raw_data("600519", start_date, end_date)
        df = fetcher._normalize_data(raw_df, "600519")

        assert "date" in df.columns
        assert "close" in df.columns
        assert "volume" in df.columns

    def test_get_kline_data(self, fetcher):
        """Test get_kline_data returns standard columns only (no inline indicators).

        Indicators (MA/MACD/etc.) live behind the indicator layer and
        the `?indicators=` query param — they must NOT appear in the
        raw fetcher output.
        """
        if not fetcher.is_available():
            pytest.skip("TUSHARE_TOKEN not set or invalid")

        df = fetcher.get_kline_data("600519", days=10)
        assert df is not None
        assert len(df) > 0
        for col in ("date", "open", "high", "low", "close", "volume"):
            assert col in df.columns
        assert "ma5" not in df.columns
        assert "ma10" not in df.columns
        assert "ma20" not in df.columns

    def test_get_realtime_quote(self, fetcher):
        """Test get_realtime_quote."""
        if not fetcher.is_available():
            pytest.skip("TUSHARE_TOKEN not set or invalid")

        result = fetcher.get_realtime_quote("600519")
        # May return None if tick data permission not granted
        if result is not None:
            assert result.code == "600519"

    def test_get_stock_name(self, fetcher):
        """Test get_stock_name."""
        if not fetcher.is_available():
            pytest.skip("TUSHARE_TOKEN not set or invalid")

        name = fetcher.get_stock_name("600519")
        if name is not None:
            assert isinstance(name, str)
            assert len(name) > 0

    def test_fetch_csi_index(self, fetcher):
        """Test _fetch_raw_data for CSI 300 index."""
        if not fetcher.is_available():
            pytest.skip("TUSHARE_TOKEN not set or invalid")

        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

        df = fetcher._fetch_raw_data("000300", start_date, end_date)
        assert df is not None
        assert len(df) > 0

    def test_get_daily_data_csi_index(self, fetcher):
        """Test get_daily_data for CSI 300 index."""
        if not fetcher.is_available():
            pytest.skip("TUSHARE_TOKEN not set or invalid")

        df = fetcher.get_kline_data("000300", days=10)
        assert df is not None
        assert len(df) > 0


class TestIndexSupport:
    """Tests for index historical data fetching."""

    @pytest.fixture
    def yfinance_fetcher(self):
        from stock_data.data_provider.fetchers.yfinance_fetcher import YfinanceFetcher

        return YfinanceFetcher()

    @pytest.fixture
    def baostock_fetcher(self):
        from stock_data.data_provider.fetchers.baostock_fetcher import BaostockFetcher

        return BaostockFetcher()

    @pytest.fixture
    def akshare_fetcher(self):
        from stock_data.data_provider.fetchers.akshare import AkshareFetcher

        return AkshareFetcher()

    def test_yfinance_us_index_daily(self, yfinance_fetcher):
        """Test YfinanceFetcher for US index daily data."""
        if not yfinance_fetcher.is_available():
            pytest.skip("yfinance not installed")

        df = yfinance_fetcher.get_kline_data("SPX", days=10)
        assert df is not None
        assert len(df) > 0
        assert "close" in df.columns

    def test_yfinance_us_index_weekly(self, yfinance_fetcher):
        """Test YfinanceFetcher for US index weekly data."""
        if not yfinance_fetcher.is_available():
            pytest.skip("yfinance not installed")

        df = yfinance_fetcher.get_kline_data("SPX", days=30, frequency="w")
        assert df is not None
        assert len(df) > 0

    def test_yfinance_us_index_monthly(self, yfinance_fetcher):
        """Test YfinanceFetcher for US index monthly data."""
        if not yfinance_fetcher.is_available():
            pytest.skip("yfinance not installed")

        df = yfinance_fetcher.get_kline_data("SPX", days=365, frequency="m")
        assert df is not None
        assert len(df) > 0

    def test_yfinance_hk_index(self, yfinance_fetcher):
        """Test YfinanceFetcher for HK index."""
        if not yfinance_fetcher.is_available():
            pytest.skip("yfinance not installed")

        df = yfinance_fetcher.get_kline_data("HSI", days=10)
        assert df is not None
        assert len(df) > 0

    def test_yfinance_csi_index(self, yfinance_fetcher):
        """Test YfinanceFetcher for CSI index via .SS suffix."""
        if not yfinance_fetcher.is_available():
            pytest.skip("yfinance not installed")

        df = yfinance_fetcher.get_kline_data("000300", days=10)
        assert df is not None
        assert len(df) > 0

    def test_baostock_csi_index(self, baostock_fetcher):
        """Test BaostockFetcher for CSI 300 index."""
        if not baostock_fetcher.is_available():
            pytest.skip("baostock not available")

        df = baostock_fetcher.get_kline_data("000300", days=10)
        assert df is not None
        assert len(df) > 0
        assert "close" in df.columns

    def test_baostock_csi_index_daily(self, baostock_fetcher):
        """Test BaostockFetcher for CSI 300 index daily."""
        if not baostock_fetcher.is_available():
            pytest.skip("baostock not available")

        df = baostock_fetcher.get_kline_data("000300", days=10, frequency="d")
        assert df is not None
        assert len(df) > 0

    def test_baostock_csi_index_weekly(self, baostock_fetcher):
        """Test BaostockFetcher for CSI 300 index weekly."""
        if not baostock_fetcher.is_available():
            pytest.skip("baostock not available")

        df = baostock_fetcher.get_kline_data("000300", days=60, frequency="w")
        assert df is not None
        assert len(df) > 0

    def test_baostock_csi_index_monthly(self, baostock_fetcher):
        """Test BaostockFetcher for CSI 300 index monthly."""
        if not baostock_fetcher.is_available():
            pytest.skip("baostock not available")

        df = baostock_fetcher.get_kline_data("000300", days=365, frequency="m")
        assert df is not None
        assert len(df) > 0

    def test_akshare_csi_index(self, akshare_fetcher):
        """Test AkshareFetcher for CSI index via index_zh_a_hist."""
        df = akshare_fetcher.get_kline_data("000300", days=10)
        assert df is not None
        assert len(df) > 0


class TestDataFetcherManager:
    """Tests for DataFetcherManager - integration tests."""

    @pytest.fixture
    def manager(self):
        from stock_data.data_provider import DataFetcherManager
        from stock_data.data_provider.fetchers.akshare import AkshareFetcher
        from stock_data.data_provider.fetchers.baostock_fetcher import BaostockFetcher
        from stock_data.data_provider.fetchers.yfinance_fetcher import YfinanceFetcher

        return DataFetcherManager(
            [
                BaostockFetcher(),
                AkshareFetcher(),
                YfinanceFetcher(),
            ]
        )

    def test_get_daily_data_a_share(self, manager):
        """Test manager fetches A-share daily data."""
        df, source = manager.get_kline_data("600519", days=10)
        assert df is not None
        assert len(df) > 0
        assert source in ["BaostockFetcher", "AkshareFetcher"]

    def test_get_daily_data_hk(self, manager):
        """Test manager fetches HK stock daily data."""
        df, source = manager.get_kline_data("HK00700", days=10)
        assert df is not None
        assert len(df) > 0
        assert source == "AkshareFetcher"

    def test_get_daily_data_us(self, manager):
        """Test manager fetches US stock daily data."""
        df, source = manager.get_kline_data("AAPL", days=10)
        assert df is not None
        assert len(df) > 0
        assert source == "YfinanceFetcher"

    def test_get_realtime_a_share(self, manager):
        """Test manager fetches A-share realtime quote."""
        from tests._network_guard import assert_or_skip

        result = assert_or_skip(manager.get_realtime_quote("600519"), "realtime quote")
        assert result.price is not None

    def test_get_realtime_hk(self, manager):
        """Test manager fetches HK stock realtime quote."""
        from tests._network_guard import assert_or_skip

        result = assert_or_skip(manager.get_realtime_quote("HK00700"), "realtime quote")
        assert result.price is not None

    def test_get_realtime_us(self, manager):
        """Test manager fetches US stock realtime quote."""
        from tests._network_guard import assert_or_skip

        result = assert_or_skip(manager.get_realtime_quote("AAPL"), "realtime quote")
        assert result.price is not None

    def test_get_daily_data_csi_index_via_manager(self, manager):
        """Test manager routes CSI index to appropriate fetcher."""
        df, source = manager.get_kline_data("000300", days=10)
        assert df is not None
        assert len(df) > 0
        # Should be fetched by Baostock or Yfinance
        assert source in ["BaostockFetcher", "YfinanceFetcher"]

    def test_get_daily_data_us_index_via_manager(self, manager):
        """Test manager routes US index to YfinanceFetcher."""
        df, source = manager.get_kline_data("SPX", days=10)
        assert df is not None
        assert len(df) > 0
        assert source == "YfinanceFetcher"

    def test_get_daily_data_hk_index_via_manager(self, manager):
        """Test manager routes HK index to appropriate fetcher."""
        df, source = manager.get_kline_data("HSI", days=10)
        assert df is not None
        assert len(df) > 0


class TestAkshareFetcherIntraday:
    """Tests for AkshareFetcher.get_intraday_data()."""

    @pytest.fixture
    def fetcher(self):
        from stock_data.data_provider.fetchers.akshare import AkshareFetcher

        return AkshareFetcher()

    def test_get_intraday_5m(self, fetcher):
        """Test get_intraday_data for 5-minute period."""
        df = fetcher.get_intraday_data("000001", period="5", adjust="")
        assert df is not None
        assert len(df) > 0
        assert "time" in df.columns
        assert "close" in df.columns
        assert "volume" in df.columns

    def test_get_intraday_5m_with_adjust(self, fetcher):
        """Test get_intraday_data for 5-minute period with qfq."""
        df = fetcher.get_intraday_data("000001", period="5", adjust="qfq")
        assert df is not None
        assert len(df) > 0

    def test_get_intraday_60m(self, fetcher):
        """Test get_intraday_data for 60-minute period."""
        df = fetcher.get_intraday_data("600519", period="60", adjust="")
        assert df is not None
        assert len(df) > 0

    def test_get_intraday_normalized_columns(self, fetcher):
        """Test normalized columns: time, open, high, low, close, volume, amount."""
        df = fetcher.get_intraday_data("000001", period="5", adjust="")
        expected_cols = {"time", "open", "high", "low", "close", "volume", "amount"}
        assert set(df.columns) == expected_cols

    def test_get_intraday_returns_none_for_unsupported_market(self, fetcher):
        """Test get_intraday_data returns None for US stock."""
        df = fetcher.get_intraday_data("AAPL", period="5", adjust="")
        assert df is None


class TestZhituFetcherIntraday:
    """Tests for ZhituFetcher.get_intraday_data()."""

    @pytest.fixture
    def fetcher(self):
        from stock_data.data_provider.fetchers.zhitu_fetcher import ZhituFetcher

        return ZhituFetcher()

    def test_get_intraday_5m(self, fetcher):
        """Test get_intraday_data for 5-minute period."""
        if not fetcher.is_available():
            pytest.skip("ZHITU_TOKEN not configured")
        df = fetcher.get_intraday_data("000001", period="5", adjust="")
        assert df is not None
        assert len(df) > 0
        assert "time" in df.columns
        assert "close" in df.columns

    def test_get_intraday_rejects_period_1(self, fetcher):
        """Test that period=1 raises DataFetchError."""
        if not fetcher.is_available():
            pytest.skip("ZHITU_TOKEN not configured")
        from stock_data.data_provider.base import DataFetchError

        with pytest.raises(DataFetchError):
            fetcher.get_intraday_data("000001", period="1", adjust="")

    def test_get_intraday_normalized_columns(self, fetcher):
        """Test normalized columns match expected."""
        if not fetcher.is_available():
            pytest.skip("ZHITU_TOKEN not configured")
        df = fetcher.get_intraday_data("000001", period="5", adjust="")
        expected_cols = {"time", "open", "high", "low", "close", "volume", "amount"}
        assert set(df.columns) == expected_cols
