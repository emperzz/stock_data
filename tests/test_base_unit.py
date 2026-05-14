"""
Unit tests for base classes and utilities (no network calls).
"""

import pandas as pd
import pytest

from stock_data.data_provider.base import (
    BaseFetcher,
    DataFetcherManager,
    DataFetchError,
)
from stock_data.data_provider.realtime_types import RealtimeSource, UnifiedRealtimeQuote


class MockFetcher(BaseFetcher):
    """Mock fetcher for testing."""

    name = "MockFetcher"
    priority = 10
    supported_markets = {"csi", "hk"}
    supports_historical = True
    supports_realtime = True

    def _fetch_raw_data(self, stock_code, start_date, end_date, frequency="d", adjust=None):
        dates = pd.date_range(start_date, end_date, freq="B")
        return pd.DataFrame(
            {
                "date": dates,
                "open": 100.0,
                "high": 102.0,
                "low": 99.0,
                "close": 101.0,
                "volume": 10000,
                "amount": 1000000,
                "pct_chg": 0.5,
            }
        )

    def _normalize_data(self, df, stock_code):
        return self._normalize_dataframe(df, stock_code, {})

    def get_realtime_quote(self, stock_code):
        return UnifiedRealtimeQuote(
            code=stock_code,
            name="Test Stock",
            source=RealtimeSource.FALLBACK,
            price=101.0,
        )

    def get_stock_name(self, stock_code):
        return "Test Stock"

    def get_all_stocks(self, market="csi"):
        return [{"code": "000001", "name": "Test"}]


class MockFetcherNoRealtime(BaseFetcher):
    """Mock fetcher that doesn't support realtime quotes."""

    name = "MockNoRealtime"
    priority = 5
    supported_markets = {"csi"}
    supports_historical = True
    supports_realtime = False

    def _fetch_raw_data(self, stock_code, start_date, end_date, frequency="d", adjust=None):
        raise DataFetchError("Not available")

    def _normalize_data(self, df, stock_code):
        return df


class TestDataFetcherManagerUnit:
    """Unit tests for DataFetcherManager with mock fetchers."""

    @pytest.fixture
    def manager(self):
        return DataFetcherManager([MockFetcher()])

    def test_add_fetcher(self, manager):
        assert "MockFetcher" in manager.available_fetchers

    def test_get_fetcher(self, manager):
        f = manager.get_fetcher("MockFetcher")
        assert f is not None
        assert f.name == "MockFetcher"

    def test_get_kline_data(self, manager):
        df, source = manager.get_kline_data("000001", days=5)
        assert source == "MockFetcher"
        assert len(df) > 0
        assert "close" in df.columns

    def test_get_realtime_quote(self, manager):
        quote = manager.get_realtime_quote("000001")
        assert quote is not None
        assert quote.code == "000001"
        assert quote.price == 101.0

    def test_get_stock_name(self, manager):
        name = manager.get_stock_name("000001")
        assert name == "Test Stock"

    def test_market_filtering_historical(self, manager):
        """Test that historical-only fetchers are excluded from realtime queries."""
        manager.add_fetcher(MockFetcherNoRealtime())
        # Historical should include both
        for f in manager._filter_by_market("csi", for_historical=True):
            assert f.supports_historical
        # Realtime should exclude MockNoRealtime
        for f in manager._filter_by_market("csi", for_historical=False):
            assert f.supports_realtime

    def test_reset(self, manager):
        manager.reset()
        assert manager.available_fetchers == []

    def test_get_all_stocks(self, manager):
        stocks = manager.fetchers[0].get_all_stocks("csi")
        assert len(stocks) == 1
        assert stocks[0]["code"] == "000001"


class TestKlineDataProcessing:
    """Unit tests for kline data cleaning and indicator calculation."""

    def test_clean_data_drops_nan_close(self):
        from stock_data.data_provider.baostock_fetcher import BaostockFetcher

        df = pd.DataFrame(
            {
                "date": ["2024-01-01", "2024-01-02", "2024-01-03"],
                "open": [100, 101, 102],
                "high": [102, 103, 104],
                "low": [99, 100, 101],
                "close": [float("nan"), 101, 102],
                "volume": [1000, 2000, 3000],
                "amount": [100000, 200000, 300000],
                "pct_chg": [0, 1, 2],
            }
        )
        fetcher = BaostockFetcher()
        fetcher._initialized = True  # Bypass Baostock login
        # _clean_data is public-like, test it directly
        df["date"] = pd.to_datetime(df["date"])
        cleaned = fetcher._clean_data(df)
        assert len(cleaned) == 2

    def test_calculate_indicators_no_inf(self):
        """Test that volume_ratio doesn't produce inf values."""

        from stock_data.data_provider.baostock_fetcher import BaostockFetcher

        df = pd.DataFrame(
            {
                "date": pd.date_range("2024-01-01", periods=10, freq="B"),
                "open": 100.0,
                "high": 102.0,
                "low": 99.0,
                "close": 101.0,
                "volume": [0] * 5 + [1000] * 5,  # First 5 periods have zero volume
                "amount": 100000.0,
                "pct_chg": 0.0,
            }
        )
        fetcher = BaostockFetcher()
        fetcher._initialized = True
        result = fetcher._calculate_indicators(df.copy())
        assert not result["volume_ratio"].isin([float("inf"), float("-inf")]).any()


class TestAdjustMapping:
    """Tests for unified adjust parameter mapping."""

    def test_baostock_adjust_mapping(self):
        from stock_data.data_provider.baostock_fetcher import BaostockFetcher

        f = BaostockFetcher()
        assert f._map_adjust("") == "3"  # 不复权
        assert f._map_adjust("qfq") == "2"  # 前复权
        assert f._map_adjust("hfq") == "1"  # 后复权

    def test_akshare_adjust_mapping(self):
        from stock_data.data_provider.akshare_fetcher import AkshareFetcher

        f = AkshareFetcher()
        assert f._map_adjust("") == ""  # 不复权
        assert f._map_adjust("qfq") == "qfq"  # 前复权
        assert f._map_adjust("hfq") == "hfq"  # 后复权

    def test_yfinance_adjust_mapping(self):
        from stock_data.data_provider.yfinance_fetcher import YfinanceFetcher

        f = YfinanceFetcher()
        assert f._map_adjust("") is None  # 不复权
        assert f._map_adjust("qfq") == "qfq"  # 前复权
        assert f._map_adjust("hfq") == "qfq"  # 后复权→前复权 (yfinance only has one)

    def test_tushare_adjust_mapping(self):
        from stock_data.data_provider.tushare_fetcher import TushareFetcher

        f = TushareFetcher()
        assert f._map_adjust("") is None  # 不复权
        assert f._map_adjust("qfq") == "qfq"  # 前复权
        assert f._map_adjust("hfq") == "hfq"  # 后复权


class TestMarketTag:
    """Tests for market_tag after rename from cn to csi."""

    def test_a_share_is_csi(self):
        from stock_data.data_provider.base import market_tag

        assert market_tag("600519") == "csi"
        assert market_tag("000001") == "csi"

    def test_hk_is_hk(self):
        from stock_data.data_provider.base import market_tag

        assert market_tag("HK00700") == "hk"

    def test_us_is_us(self):
        from stock_data.data_provider.base import market_tag

        assert market_tag("AAPL") == "us"
