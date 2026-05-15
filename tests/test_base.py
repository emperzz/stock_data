"""
Tests for base classes and utilities.
"""

from stock_data.data_provider.base import (
    STANDARD_COLUMNS,
    index_market_tag,
    is_hk_market,
    is_us_market,
    market_tag,
    normalize_stock_code,
)
from stock_data.data_provider.index_symbols import (
    CSI_INDEX_MAP,
    HK_INDEX_MAP,
    US_INDEX_MAP,
    get_index_type,
    is_index_code,
)


class TestNormalizeStockCode:
    """Tests for normalize_stock_code function."""

    def test_sh_prefix(self):
        assert normalize_stock_code("SH600519") == "600519"

    def test_sz_prefix(self):
        assert normalize_stock_code("SZ000001") == "000001"

    def test_hk_prefix(self):
        assert normalize_stock_code("HK00700") == "HK00700"

    def test_dot_suffix_sh(self):
        assert normalize_stock_code("600519.SS") == "600519"

    def test_dot_suffix_sz(self):
        assert normalize_stock_code("000001.SZ") == "000001"

    def test_hk_suffix(self):
        assert normalize_stock_code("0700.HK") == "HK00700"

    def test_us_uppercase(self):
        assert normalize_stock_code("AAPL") == "AAPL"

    def test_us_lowercase(self):
        assert normalize_stock_code("aapl") == "AAPL"


class TestMarketDetection:
    """Tests for market detection functions."""

    def test_us_stock(self):
        assert is_us_market("AAPL")
        assert is_us_market("TSLA")
        assert is_us_market("GOOGL")

    def test_us_not_hk(self):
        assert not is_hk_market("AAPL")

    def test_hk_stock(self):
        assert is_hk_market("HK00700")
        assert is_hk_market("00700.HK")


class TestMarketTag:
    """Tests for market_tag function."""

    def test_us(self):
        assert market_tag("AAPL") == "us"

    def test_hk(self):
        assert market_tag("HK00700") == "hk"

    def test_csi_default(self):
        assert market_tag("600519") == "csi"
        assert market_tag("000001") == "csi"


class TestStandardColumns:
    """Tests for STANDARD_COLUMNS constant."""

    def test_has_required_columns(self):
        required = ["date", "open", "high", "low", "close", "volume", "amount", "pct_chg"]
        for col in required:
            assert col in STANDARD_COLUMNS


class TestIndexSymbols:
    """Tests for index symbol detection and normalization."""

    def test_is_index_code_us(self):
        assert is_index_code("SPX")
        assert is_index_code("DJI")
        assert is_index_code("IXIC")
        assert is_index_code("VIX")

    def test_is_index_code_csi(self):
        assert is_index_code("000300")  # 沪深300
        assert is_index_code("000001")  # 上证指数
        assert is_index_code("399001")  # 深证成指

    def test_is_index_code_hk(self):
        assert is_index_code("HSI")
        assert is_index_code("HSCE")

    def test_is_not_index_code_stock(self):
        assert not is_index_code("600519")  # A-share stock
        assert not is_index_code("AAPL")  # US stock
        assert not is_index_code("HK00700")  # HK stock

    def test_get_index_type_us(self):
        assert get_index_type("SPX") == "us"
        assert get_index_type("DJI") == "us"

    def test_get_index_type_csi(self):
        assert get_index_type("000300") == "csi"
        assert get_index_type("000001") == "csi"

    def test_get_index_type_hk(self):
        assert get_index_type("HSI") == "hk"
        assert get_index_type("HSCE") == "hk"

    def test_csi_index_map(self):
        """Test CSI index mappings are correct."""
        assert CSI_INDEX_MAP.get("000300") == ("sh.000300", "沪深300")
        assert CSI_INDEX_MAP.get("000001") == ("sh.000001", "上证指数")
        assert CSI_INDEX_MAP.get("399001") == ("sz.399001", "深证成指")

    def test_us_index_map(self):
        """Test US index mappings are correct."""
        assert US_INDEX_MAP.get("SPX") == ("^GSPC", "S&P 500")
        assert US_INDEX_MAP.get("DJI") == ("^DJI", "Dow Jones Industrial Average")

    def test_hk_index_map(self):
        """Test HK index mappings are correct."""
        assert HK_INDEX_MAP.get("HSI") == ("^HSI", "恒生指数")


class TestIndexMarketTag:
    """Tests for index_market_tag function."""

    def test_us_index(self):
        assert index_market_tag("SPX") == "us"
        assert index_market_tag("DJI") == "us"

    def test_csi_index(self):
        assert index_market_tag("000300") == "csi"
        assert index_market_tag("000001") == "csi"

    def test_hk_index(self):
        assert index_market_tag("HSI") == "hk"

    def test_stock_returns_none(self):
        assert index_market_tag("600519") is None
        assert index_market_tag("AAPL") is None
        assert index_market_tag("HK00700") is None
