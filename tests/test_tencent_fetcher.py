"""
Unit tests for TencentFetcher.
"""

from unittest.mock import MagicMock, patch

import pytest

from stock_data.data_provider.base import DataCapability
from stock_data.data_provider.fetchers.tencent_fetcher import TencentFetcher


class TestTencentFetcherBasics:
    """Basic attribute and capability tests."""

    def test_name(self):
        f = TencentFetcher()
        assert f.name == "TencentFetcher"

    def test_priority(self):
        f = TencentFetcher()
        assert f.priority == 5

    def test_supported_markets(self):
        f = TencentFetcher()
        assert "csi" in f.supported_markets
        assert "hk" in f.supported_markets

    def test_capabilities(self):
        f = TencentFetcher()
        assert DataCapability.REALTIME_QUOTE in f.supported_data_types

    def test_is_available(self):
        f = TencentFetcher()
        assert f.is_available() is True


class TestTencentPrefix:
    """Tests for _tencent_prefix() method."""

    def test_shanghai(self):
        f = TencentFetcher()
        assert f._tencent_prefix("600519") == "sh600519"
        assert f._tencent_prefix("688017") == "sh688017"
        assert f._tencent_prefix("sh600519") == "sh600519"
        assert f._tencent_prefix("SH600519") == "sh600519"

    def test_shenzhen(self):
        f = TencentFetcher()
        assert f._tencent_prefix("000001") == "sz000001"
        assert f._tencent_prefix("300476") == "sz300476"
        assert f._tencent_prefix("sz000001") == "sz000001"
        assert f._tencent_prefix("SZ000001") == "sz000001"

    def test_hk(self):
        """HK codes that start with HK prefix are recognized."""
        f = TencentFetcher()
        # Full HK code with prefix
        assert f._tencent_prefix("HK00700") == "hk00700"
        assert f._tencent_prefix("hk00700") == "hk00700"
        # Pure numeric without HK prefix falls to sz (normalize_stock_code strips HK prefix)
        assert f._tencent_prefix("00700") == "sz00700"

    def test_beijing(self):
        """Beijing codes start with 8."""
        f = TencentFetcher()
        assert f._tencent_prefix("832000") == "bj832000"
        assert f._tencent_prefix("bj832000") == "bj832000"
        # 4-prefix codes are treated as Shenzhen, not Beijing
        assert f._tencent_prefix("430001") == "sz430001"

    def test_unknown_defaults_to_sh(self):
        """9-prefix codes fall back to sh prefix."""
        f = TencentFetcher()
        result = f._tencent_prefix("999999")
        assert result == "sh999999"


class TestParseTencentResponse:
    """Tests for _parse_tencent_response() method."""

    def _build_response(self, field_overrides=None):
        """Build Tencent response string with field overrides."""
        overrides = field_overrides or {}
        defaults = {
            0: "sh600519", 1: "贵州茅台", 3: "1850.00", 4: "1830.00", 5: "1820.00",
            31: "20.00", 32: "1.09", 33: "1860.00", 34: "1810.00",
            36: "50000", 37: "150000.5", 38: "0.85",
            39: "28.5", 43: "2.75", 44: "2350.0", 45: "2340.0", 46: "8.2", 49: "1.2",
        }
        defaults.update(overrides)
        fields = [""] * 53
        for idx, val in defaults.items():
            if idx < len(fields):
                fields[idx] = val
        return f'v_sh600519="{fields[0]}~{"~".join(fields[1:])}";'

    def test_parse_basic_fields(self):
        """Test parsing of basic quote fields."""
        f = TencentFetcher()
        response = self._build_response()
        quote = f._parse_tencent_response(response, "600519")

        assert quote is not None
        assert quote.code == "600519"
        assert quote.name == "贵州茅台"
        assert quote.price == 1850.00
        assert quote.pre_close == 1830.00
        assert quote.open_price == 1820.00
        assert quote.change_amount == 20.00
        assert quote.change_pct == 1.09
        assert quote.high == 1860.00
        assert quote.low == 1810.00

    def test_parse_enhanced_fields(self):
        """Test parsing of enhanced valuation fields."""
        f = TencentFetcher()
        response = self._build_response()
        quote = f._parse_tencent_response(response, "600519")

        assert quote is not None
        assert quote.pe_ratio == 28.5
        assert quote.pb_ratio == 8.2
        # total_mv in 元 = 亿 * 1e8
        assert quote.total_mv == 2350.0 * 1e8
        # circ_mv in 元 = 亿 * 1e8
        assert quote.circ_mv == 2340.0 * 1e8
        assert quote.turnover_rate == 0.85
        assert quote.amplitude == 2.75
        assert quote.volume_ratio == 1.2

    def test_parse_volume_conversion(self):
        """Test volume is converted from 手 to shares."""
        f = TencentFetcher()
        response = self._build_response({36: "50000"})
        quote = f._parse_tencent_response(response, "600519")

        assert quote is not None
        assert quote.volume == 50000 * 100  # 手 -> shares

    def test_parse_amount_conversion(self):
        """Test amount is converted from 万元 to 元."""
        f = TencentFetcher()
        response = self._build_response({37: "150000.5"})
        quote = f._parse_tencent_response(response, "600519")

        assert quote is not None
        assert quote.amount == 150000.5 * 10000  # 万元 -> 元

    def test_parse_empty_data(self):
        """Test handling of empty response."""
        f = TencentFetcher()
        assert f._parse_tencent_response("", "600519") is None
        assert f._parse_tencent_response("noequals", "600519") is None
        assert f._parse_tencent_response('v_sh600519="";', "600519") is None

    def test_parse_insufficient_fields(self):
        """Test handling of response with too few fields."""
        f = TencentFetcher()
        # Only 10 fields
        short_response = 'v_sh600519="sh600519~贵州茅台~~1850.00~~~;'
        assert f._parse_tencent_response(short_response, "600519") is None

    def test_parse_missing_optional_fields(self):
        """Test handling of missing optional fields (empty string)."""
        f = TencentFetcher()
        # Fields 39 (PE) and 46 (PB) empty
        response = self._build_response({39: "", 46: ""})
        quote = f._parse_tencent_response(response, "600519")

        assert quote is not None
        assert quote.pe_ratio is None
        assert quote.pb_ratio is None


class TestGetRealtimeQuote:
    """Tests for get_realtime_quote() method."""

    @patch("stock_data.data_provider.fetchers.tencent_fetcher.urllib.request.urlopen")
    def test_returns_quote_on_success(self, mock_urlopen):
        """Test successful quote retrieval."""
        mock_response = MagicMock()
        # Build a proper 53-field response (indices 0-52)
        fields = [""] * 53
        fields[0] = "sh600519"  # code
        fields[1] = "TestStock"  # name
        fields[3] = "1850.00"  # price
        fields[4] = "1830.00"  # pre_close
        fields[5] = "1820.00"  # open
        fields[31] = "20.00"  # change_amt
        fields[32] = "1.09"  # change_pct
        fields[33] = "1860.00"  # high
        fields[34] = "1810.00"  # low
        fields[36] = "50000"  # volume
        fields[37] = "150000.5"  # amount
        fields[38] = "0.85"  # turnover
        fields[39] = "28.5"  # PE
        fields[43] = "2.75"  # amplitude
        fields[44] = "2350.0"  # mcap
        fields[45] = "2340.0"  # float_mcap
        fields[46] = "8.2"  # PB
        fields[49] = "1.2"  # vol_ratio
        response_str = 'v_sh600519="' + "~".join(fields) + '";'
        mock_response.read.return_value = response_str.encode("utf-8")
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        f = TencentFetcher()
        quote = f.get_realtime_quote("600519")

        assert quote is not None
        assert quote.code == "600519"
        assert quote.name == "TestStock"
        assert quote.price == 1850.00
        assert quote.pe_ratio == 28.5

    @patch("stock_data.data_provider.fetchers.tencent_fetcher.urllib.request.urlopen")
    def test_returns_none_on_error(self, mock_urlopen):
        """Test graceful handling of API errors."""
        mock_urlopen.side_effect = Exception("Network error")

        f = TencentFetcher()
        quote = f.get_realtime_quote("600519")

        assert quote is None


class TestHistoricalNotSupported:
    """Tests verifying historical data is not supported."""

    def test_fetch_raw_data_raises(self):
        """Test that _fetch_raw_data raises DataFetchError."""
        from stock_data.data_provider.base import DataFetchError

        f = TencentFetcher()
        with pytest.raises(DataFetchError, match="does not support historical"):
            f._fetch_raw_data("600519", "2026-01-01", "2026-05-01")

    def test_normalize_data_raises(self):
        """Test that _normalize_data raises DataFetchError."""
        import pandas as pd

        from stock_data.data_provider.base import DataFetchError

        f = TencentFetcher()
        with pytest.raises(DataFetchError, match="does not support historical"):
            f._normalize_data(pd.DataFrame(), "600519")

    def test_get_kline_data_raises(self):
        """Test that get_kline_data raises DataFetchError."""
        from stock_data.data_provider.base import DataFetchError

        f = TencentFetcher()
        with pytest.raises(DataFetchError, match="does not support historical"):
            f.get_kline_data("600519")
