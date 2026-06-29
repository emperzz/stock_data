"""
Unit tests for base classes and utilities (no network calls).
"""

import pandas as pd
import pytest

from stock_data.data_provider import (
    AkshareFetcher,
    BaostockFetcher,
    TushareFetcher,
    YfinanceFetcher,
    stock_cache,
)
from stock_data.data_provider.base import (
    BaseFetcher,
    DataCapability,
    DataFetcherManager,
    DataFetchError,
)
from stock_data.data_provider.core.types import RealtimeSource, UnifiedRealtimeQuote


class MockFetcher(BaseFetcher):
    """Mock fetcher for testing."""

    name = "MockFetcher"
    priority = 10
    supported_markets = {"csi", "hk"}
    supported_data_types = (
        DataCapability.HISTORICAL_DWM
        | DataCapability.HISTORICAL_MIN
        | DataCapability.REALTIME_QUOTE
        | DataCapability.STOCK_LIST
    )

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
    supported_data_types = DataCapability.HISTORICAL_DWM | DataCapability.STOCK_LIST

    def _fetch_raw_data(self, stock_code, start_date, end_date, frequency="d", adjust=None):
        raise DataFetchError("Not available")

    def _normalize_data(self, df, stock_code):
        return df


class MockFetcherNoIndex(BaseFetcher):
    """Mock that declares HISTORICAL_DWM only (no INDEX_* capability).

    Used to verify that index codes routed via manager.get_kline_data
    fall through to a clean DataFetchError when no INDEX_* fetcher is
    registered — i.e., the INDEX→HISTORICAL silent fallback is gone.
    The fetcher's get_kline_data() should never be reached for index
    codes; if it is, the mock returns trivial data so any erroneous
    fallback is visible in the test result.
    """
    name = "MockFetcherNoIndex"
    priority = 10
    supported_markets = {"csi"}
    supported_data_types = DataCapability.HISTORICAL_DWM

    def _fetch_raw_data(self, stock_code, start_date, end_date, frequency="d", adjust=None):
        raise DataFetchError("MockFetcherNoIndex: should not be called for index codes")

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
        df, source = manager.get_kline_data("600519", days=5)
        assert source == "MockFetcher"
        assert len(df) > 0
        assert "close" in df.columns

    def test_get_realtime_quote(self, manager):
        quote = manager.get_realtime_quote("000001")
        assert quote is not None
        assert quote.code == "000001"
        assert quote.price == 101.0

    def test_get_stock_name(self, manager, tmp_path, monkeypatch):
        """Verify get_stock_name falls through to the manager when DB is empty.

        Uses a tmp_path DB so the test doesn't depend on the real
        ``stock_cache.db`` state. The shared cache is mutated by other
        tests (e.g. ``test_persistence_origin.py`` writes ``"000001" →
        "测试"`` through the real DB path), which would otherwise make
        this assertion flaky. DB round-trip behavior is covered
        separately by ``test_stock_list_exchange.py``.
        """
        from stock_data.data_provider.persistence import (
            db,
            stock_list as stock_list_mod,
        )

        monkeypatch.setattr(db, "get_db_path", lambda: tmp_path / "test.db")
        monkeypatch.setattr(db, "_conn", None, raising=False)
        # Fresh refresh tracker so is_first_call returns True and the
        # call deterministically goes through the manager path.
        monkeypatch.setattr(
            stock_list_mod, "_refresh_tracker",
            type("T", (), {"is_first_call": lambda *a: True})(),
        )
        stock_list_mod.init_schema()

        name = stock_cache.get_stock_name("000001", manager=manager)
        assert name == "Test"

    def test_market_filtering_historical(self, manager):
        """Test that historical-only fetchers are excluded from realtime queries."""
        manager.add_fetcher(MockFetcherNoRealtime())
        # Historical should include both
        for f in manager._filter_by_capability("csi", DataCapability.HISTORICAL_DWM):
            assert DataCapability.HISTORICAL_DWM in f.supported_data_types
        # Realtime should exclude MockNoRealtime
        for f in manager._filter_by_capability("csi", DataCapability.REALTIME_QUOTE):
            assert DataCapability.REALTIME_QUOTE in f.supported_data_types

    def test_reset(self, manager):
        manager.reset()
        assert manager.available_fetchers == []

    def test_get_all_stocks(self, manager):
        stocks = manager.fetchers[0].get_all_stocks("csi")
        assert len(stocks) == 1
        assert stocks[0]["code"] == "000001"

    def test_get_kline_data_index_no_fallback_daily(self):
        """Index code + no INDEX_* fetcher registered: must raise DataFetchError.

        Pre-fix: silently routed through HISTORICAL_DWM and returned fake data.
        Post-fix: no INDEX_HISTORICAL declaration → DataFetchError.
        Uses MockFetcherNoIndex (declares HISTORICAL_DWM only) so neither
        INDEX_HISTORICAL nor INDEX_INTRADAY is satisfied.
        """
        mgr = DataFetcherManager([MockFetcherNoIndex()])
        with pytest.raises(DataFetchError):
            mgr.get_kline_data("000300", days=5, frequency="d")

    def test_get_kline_data_index_no_fallback_minute(self):
        """Index code + minute freq + no INDEX_INTRADAY fetcher: must raise.

        Same setup as the daily variant; only difference is frequency="5"
        which routes through INDEX_INTRADAY capability. MockFetcherNoIndex
        declares HISTORICAL_DWM only — no INDEX_INTRADAY either, so the
        strict routing surfaces DataFetchError.
        """
        mgr = DataFetcherManager([MockFetcherNoIndex()])
        with pytest.raises(DataFetchError):
            mgr.get_kline_data("000300", days=5, frequency="5")


class TestKlineDataProcessing:
    """Unit tests for kline data cleaning and indicator calculation."""

    def test_clean_data_drops_nan_close(self):

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

    def test_no_inline_indicators_on_kline(self):
        """Fletchers no longer auto-compute MA5/MA10/MA20 in get_kline_data.

        Indicators are now the responsibility of the indicator layer
        (see stock_data.data_provider.indicators); the orchestrator is
        reached via the ?indicators= query param on /stocks/{code}/history.
        """

        df = pd.DataFrame(
            {
                "date": pd.date_range("2024-01-01", periods=10, freq="B"),
                "open": 100.0,
                "high": 102.0,
                "low": 99.0,
                "close": 101.0,
                "volume": 1000.0,
                "amount": 100000.0,
                "pct_chg": 0.0,
            }
        )
        fetcher = BaostockFetcher()
        fetcher._initialized = True
        result = fetcher._clean_data(df.copy())
        assert "ma5" not in result.columns
        assert "ma10" not in result.columns
        assert "ma20" not in result.columns
        assert "volume_ratio" not in result.columns


class TestAdjustMapping:
    """Tests for unified adjust parameter mapping."""

    def test_baostock_adjust_mapping(self):

        f = BaostockFetcher()
        assert f._map_adjust("") == "3"  # 不复权
        assert f._map_adjust("qfq") == "2"  # 前复权
        assert f._map_adjust("hfq") == "1"  # 后复权

    def test_akshare_adjust_mapping(self):

        f = AkshareFetcher()
        assert f._map_adjust("") == ""  # 不复权
        assert f._map_adjust("qfq") == "qfq"  # 前复权
        assert f._map_adjust("hfq") == "hfq"  # 后复权

    def test_yfinance_adjust_mapping(self):

        f = YfinanceFetcher()
        assert f._map_adjust("") is None  # 不复权
        assert f._map_adjust("qfq") == "qfq"  # 前复权
        assert f._map_adjust("hfq") == "qfq"  # 后复权→前复权 (yfinance only has one)

    def test_tushare_adjust_mapping(self):

        f = TushareFetcher()
        assert f._map_adjust("") is None  # 不复权
        assert f._map_adjust("qfq") == "qfq"  # 前复权
        assert f._map_adjust("hfq") == "hfq"  # 后复权
