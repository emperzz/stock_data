"""
Structural / unit tests for fetchers that previously lacked coverage:
Akshare, Baostock, Yfinance, Zhitu, Tushare.

Tests verify code-converter delegation, basic metadata, and key edge
cases without hitting upstream APIs.
"""

from unittest.mock import patch

import pytest

from stock_data.data_provider.base import DataCapability
from stock_data.data_provider.utils import code_converter as cc

# ====================================================================
# AkshareFetcher
# ====================================================================

class TestAkshareFetcher:
    @pytest.fixture
    def fetcher(self):
        from stock_data.data_provider.fetchers.akshare import AkshareFetcher
        return AkshareFetcher()

    def test_name_and_priority(self, fetcher):
        assert fetcher.name == "AkshareFetcher"
        assert fetcher.priority == 2

    def test_is_available(self, fetcher):
        assert fetcher.is_available() is True

    def test_supported_markets(self, fetcher):
        assert "csi" in fetcher.supported_markets
        assert "hk" in fetcher.supported_markets

    def test_capabilities(self, fetcher):
        caps = [
            DataCapability.HISTORICAL_DWM, DataCapability.HISTORICAL_MIN,
            DataCapability.REALTIME_QUOTE, DataCapability.STOCK_LIST,
            DataCapability.TRADE_CALENDAR, DataCapability.STOCK_BOARD,
            DataCapability.INDEX_QUOTE, DataCapability.INDEX_HISTORICAL,
            DataCapability.INDEX_INTRADAY, DataCapability.STOCK_ZT_POOL,
        ]
        for c in caps:
            assert c in fetcher.supported_data_types

    def test_convert_code_delegates_to_converter(self, fetcher):
        """_convert_code delegates to to_akshare_format."""
        code = fetcher._convert_code("600519")
        assert code == cc.to_akshare_format("600519")

    def test_convert_code_hk(self, fetcher):
        assert fetcher._convert_code("HK00700") == "00700.hk"

    def test_convert_code_us_index(self, fetcher):
        assert fetcher._convert_code("SPX") == ".INX"

    def test_map_adjust(self, fetcher):
        # Akshare maps "" to "" (not None), unlike other fetchers
        assert fetcher._map_adjust("") == ""
        assert fetcher._map_adjust("qfq") == "qfq"
        assert fetcher._map_adjust("hfq") == "hfq"

    def test_board_methods_exist(self, fetcher):
        assert hasattr(fetcher, "get_all_concept_boards")
        assert hasattr(fetcher, "get_all_industry_boards")
        assert hasattr(fetcher, "get_concept_board_stocks")
        assert hasattr(fetcher, "get_industry_board_stocks")

    def test_index_methods_exist(self, fetcher):
        assert hasattr(fetcher, "get_index_realtime_quote")
        assert hasattr(fetcher, "get_index_historical")
        assert hasattr(fetcher, "get_index_intraday")


# ====================================================================
# BaostockFetcher
# ====================================================================

class TestBaostockFetcher:
    @pytest.fixture
    def fetcher(self):
        from stock_data.data_provider.fetchers.baostock_fetcher import BaostockFetcher
        return BaostockFetcher()

    def test_name_and_priority(self, fetcher):
        assert fetcher.name == "BaostockFetcher"
        assert fetcher.priority == 1

    def test_supported_markets(self, fetcher):
        assert fetcher.supported_markets == {"csi"}

    def test_capabilities(self, fetcher):
        caps = [
            DataCapability.HISTORICAL_DWM, DataCapability.HISTORICAL_MIN,
            DataCapability.TRADE_CALENDAR, DataCapability.INDEX_HISTORICAL,
        ]
        for c in caps:
            assert c in fetcher.supported_data_types

    def test_convert_code_delegates_to_converter(self, fetcher):
        """_convert_code delegates to to_baostock_format."""
        bs_code, yw_code = fetcher._convert_code("600519")
        assert (bs_code, yw_code) == cc.to_baostock_format("600519")

    def test_convert_code_non_csi_index_raises(self, fetcher):
        from stock_data.data_provider.base import DataFetchError
        with pytest.raises(DataFetchError, match="Baostock does not support"):
            fetcher._convert_code("SPX")

    def test_convert_code_csi_index(self, fetcher):
        bs_code, yw_code = fetcher._convert_code("000300")
        assert bs_code == "sh.000300"

    def test_map_adjust(self, fetcher):
        assert fetcher._map_adjust("") == "3"
        assert fetcher._map_adjust("qfq") == "2"
        assert fetcher._map_adjust("hfq") == "1"

    def test_realtime_quote_returns_none(self, fetcher):
        """Baostock has no realtime API."""
        assert fetcher.get_realtime_quote("600519") is None


# ====================================================================
# YfinanceFetcher
# ====================================================================

class TestYfinanceFetcher:
    @pytest.fixture
    def fetcher(self):
        from stock_data.data_provider.fetchers.yfinance_fetcher import YfinanceFetcher
        return YfinanceFetcher()

    def test_name_and_priority(self, fetcher):
        assert fetcher.name == "YfinanceFetcher"
        assert fetcher.priority == 3

    def test_supported_markets(self, fetcher):
        assert fetcher.supported_markets == {"csi", "hk", "us"}

    def test_capabilities(self, fetcher):
        caps = [
            DataCapability.HISTORICAL_DWM, DataCapability.HISTORICAL_MIN,
            DataCapability.REALTIME_QUOTE, DataCapability.INDEX_HISTORICAL,
            DataCapability.INDEX_QUOTE,
        ]
        for c in caps:
            assert c in fetcher.supported_data_types

    def test_convert_code_delegates_to_converter(self, fetcher):
        assert fetcher._convert_code("600519") == cc.to_yfinance_format("600519")

    def test_convert_code_a_share(self, fetcher):
        assert fetcher._convert_code("600519") == "600519.SS"

    def test_convert_code_us_stock(self, fetcher):
        assert fetcher._convert_code("AAPL") == "AAPL"

    def test_convert_code_us_index(self, fetcher):
        assert fetcher._convert_code("SPX") == "^GSPC"

    def test_convert_code_hk_stock(self, fetcher):
        assert fetcher._convert_code("HK00700") == "00700.HK"

    def test_map_adjust(self, fetcher):
        assert fetcher._map_adjust("") is None
        assert fetcher._map_adjust("qfq") == "qfq"
        assert fetcher._map_adjust("hfq") == "qfq"

    def test_index_methods_exist(self, fetcher):
        assert hasattr(fetcher, "get_index_realtime_quote")
        assert hasattr(fetcher, "get_index_historical")


# ====================================================================
# ZhituFetcher
# ====================================================================

class TestZhituFetcher:
    @pytest.fixture
    def fetcher(self):
        from stock_data.data_provider.fetchers.zhitu_fetcher import ZhituFetcher
        return ZhituFetcher()

    def test_name_and_priority(self, fetcher):
        assert fetcher.name == "ZhituFetcher"
        assert fetcher.priority == 4

    def test_supported_markets(self, fetcher):
        assert fetcher.supported_markets == {"csi"}

    def test_capabilities(self, fetcher):
        caps = [DataCapability.REALTIME_QUOTE, DataCapability.STOCK_ZT_POOL]
        for c in caps:
            assert c in fetcher.supported_data_types

    def test_convert_code_delegates_to_converter(self, fetcher):
        assert fetcher._convert_code("600519") == cc.to_zhitu_format("600519")

    def test_convert_code_normalizes(self, fetcher):
        assert fetcher._convert_code("SH600519") == "600519"

    def test_market_suffix_delegates_to_converter(self, fetcher):
        assert fetcher._market_suffix("600519") == cc.to_zhitu_market_suffix("600519")

    def test_market_suffix_sh(self, fetcher):
        assert fetcher._market_suffix("600519") == ".sh"

    def test_market_suffix_sz(self, fetcher):
        assert fetcher._market_suffix("000001") == ".sz"


# ====================================================================
# TushareFetcher
# ====================================================================

class TestTushareFetcher:
    @pytest.fixture
    def fetcher(self):
        from stock_data.data_provider.fetchers.tushare_fetcher import TushareFetcher
        return TushareFetcher()

    def test_name_and_priority(self, fetcher):
        assert fetcher.name == "TushareFetcher"
        assert fetcher.priority == 0

    def test_supported_markets(self, fetcher):
        assert fetcher.supported_markets == {"csi"}

    def test_capabilities(self, fetcher):
        caps = [
            DataCapability.HISTORICAL_DWM, DataCapability.REALTIME_QUOTE,
            DataCapability.INDEX_HISTORICAL,
        ]
        for c in caps:
            assert c in fetcher.supported_data_types

    def test_map_adjust(self, fetcher):
        assert fetcher._map_adjust("") is None
        assert fetcher._map_adjust("qfq") == "qfq"

    @patch("stock_data.data_provider.fetchers.tushare_fetcher.TushareFetcher._ensure_api")
    def test_is_available_without_token(self, mock_ensure, fetcher):
        fetcher._api = None
        fetcher._initialized = True
        assert fetcher.is_available() is False

    def test_index_methods_exist(self, fetcher):
        assert hasattr(fetcher, "get_index_historical")


# ====================================================================
# MyquantFetcher
# ====================================================================

class TestMyquantFetcher:
    @pytest.fixture
    def fetcher(self, monkeypatch):
        """Build a fetcher with token pre-set."""
        monkeypatch.setenv("MYQUANT_TOKEN", "test-token")
        from stock_data.data_provider.fetchers.myquant_fetcher import MyquantFetcher
        return MyquantFetcher()

    @pytest.fixture
    def fetcher_no_token(self, monkeypatch):
        """Build a fetcher without a token."""
        monkeypatch.delenv("MYQUANT_TOKEN", raising=False)
        from stock_data.data_provider.fetchers.myquant_fetcher import MyquantFetcher
        return MyquantFetcher()

    def test_name_and_priority(self, fetcher):
        assert fetcher.name == "MyquantFetcher"
        assert fetcher.priority == 1

    def test_supported_markets(self, fetcher):
        assert fetcher.supported_markets == {"csi"}

    def test_capabilities(self, fetcher):
        caps = [
            DataCapability.HISTORICAL_DWM, DataCapability.HISTORICAL_MIN,
            DataCapability.REALTIME_QUOTE, DataCapability.STOCK_LIST,
            DataCapability.TRADE_CALENDAR, DataCapability.INDEX_HISTORICAL,
            DataCapability.INDEX_INTRADAY,
        ]
        for c in caps:
            assert c in fetcher.supported_data_types, f"missing {c}"

    def test_is_available_with_token(self, fetcher):
        assert fetcher.is_available() is True

    def test_is_available_without_token(self, fetcher_no_token):
        assert fetcher_no_token.is_available() is False
