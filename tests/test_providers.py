# -*- coding: utf-8 -*-
"""
Tests for individual provider fetchers - directly testing each provider's internal APIs.

Each fetcher's _fetch_raw_data, _normalize_data, get_realtime_quote, and
get_stock_name should be tested in isolation, NOT through the manager or server.

Note: These tests make real API calls to external services (yfinance, akshare, baostock, tushare).
Due to rate limiting, some tests may fail intermittently. Use --lf (last-failed) to re-run only
failed tests after a cooldown period.
"""

import pytest
import time
from datetime import datetime, timedelta


@pytest.fixture(autouse=True)
def rate_limit_delay():
    """Add delay between tests to avoid rate limiting."""
    time.sleep(0.5)
    yield


class TestBaostockFetcher:
    """Tests for BaostockFetcher."""

    @pytest.fixture
    def fetcher(self):
        from stock_data.data_provider.baostock_fetcher import BaostockFetcher
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

    def test_get_daily_data(self, fetcher):
        """Test get_daily_data returns DataFrame with indicators."""
        df = fetcher.get_daily_data("600519", days=10)
        assert df is not None
        assert len(df) > 0
        assert "ma5" in df.columns
        assert "ma10" in df.columns
        assert "ma20" in df.columns

    def test_get_realtime_quote_method_exists(self, fetcher):
        """Test get_realtime_quote method exists on fetcher."""
        # BaostockFetcher.get_realtime_quote is NOT implemented
        # (baostock has no query_realtime_quotes API)
        # This test documents that reality
        result = fetcher.get_realtime_quote("600519")
        assert result is None  # Should return None, not crash

    def test_realtime_quote_returns_none(self, fetcher):
        """Verify Baostock does NOT support realtime quotes."""
        # Even though the method exists, it should return None
        # because baostock doesn't have this API
        result = fetcher.get_realtime_quote("600519")
        assert result is None


class TestAkshareFetcher:
    """Tests for AkshareFetcher."""

    @pytest.fixture
    def fetcher(self):
        from stock_data.data_provider.akshare_fetcher import AkshareFetcher
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

    def test_get_daily_data(self, fetcher):
        """Test get_daily_data with indicators."""
        df = fetcher.get_daily_data("600519", days=10)
        assert df is not None
        assert len(df) > 0
        assert "ma5" in df.columns


class TestYfinanceFetcher:
    """Tests for YfinanceFetcher."""

    @pytest.fixture
    def fetcher(self):
        from stock_data.data_provider.yfinance_fetcher import YfinanceFetcher
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

    def test_get_daily_data(self, fetcher):
        """Test get_daily_data with indicators."""
        df = fetcher.get_daily_data("AAPL", days=10)
        assert df is not None
        assert len(df) > 0
        assert "ma5" in df.columns


class TestTushareFetcher:
    """Tests for TushareFetcher."""

    @pytest.fixture
    def fetcher(self):
        from stock_data.data_provider.tushare_fetcher import TushareFetcher
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

    def test_get_daily_data(self, fetcher):
        """Test get_daily_data returns DataFrame with indicators."""
        if not fetcher.is_available():
            pytest.skip("TUSHARE_TOKEN not set or invalid")

        df = fetcher.get_daily_data("600519", days=10)
        assert df is not None
        assert len(df) > 0
        assert "ma5" in df.columns

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


class TestDataFetcherManager:
    """Tests for DataFetcherManager - integration tests."""

    @pytest.fixture
    def manager(self):
        from stock_data.data_provider.base import DataFetcherManager
        from stock_data.data_provider.baostock_fetcher import BaostockFetcher
        from stock_data.data_provider.akshare_fetcher import AkshareFetcher
        from stock_data.data_provider.yfinance_fetcher import YfinanceFetcher

        return DataFetcherManager([
            BaostockFetcher(),
            AkshareFetcher(),
            YfinanceFetcher(),
        ])

    def test_get_daily_data_a_share(self, manager):
        """Test manager fetches A-share daily data."""
        df, source = manager.get_daily_data("600519", days=10)
        assert df is not None
        assert len(df) > 0
        assert source in ["BaostockFetcher", "AkshareFetcher"]

    def test_get_daily_data_hk(self, manager):
        """Test manager fetches HK stock daily data."""
        df, source = manager.get_daily_data("HK00700", days=10)
        assert df is not None
        assert len(df) > 0
        assert source == "AkshareFetcher"

    def test_get_daily_data_us(self, manager):
        """Test manager fetches US stock daily data."""
        df, source = manager.get_daily_data("AAPL", days=10)
        assert df is not None
        assert len(df) > 0
        assert source == "YfinanceFetcher"

    def test_get_realtime_a_share(self, manager):
        """Test manager fetches A-share realtime quote."""
        result = manager.get_realtime_quote("600519")
        assert result is not None
        assert result.price is not None

    def test_get_realtime_hk(self, manager):
        """Test manager fetches HK stock realtime quote."""
        result = manager.get_realtime_quote("HK00700")
        assert result is not None
        assert result.price is not None

    def test_get_realtime_us(self, manager):
        """Test manager fetches US stock realtime quote."""
        result = manager.get_realtime_quote("AAPL")
        assert result is not None
        assert result.price is not None
