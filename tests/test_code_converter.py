"""
Tests for utils/code_converter.py — every source format, every edge case.
"""

import pytest

from stock_data.data_provider.utils import code_converter as cc

# ============================================================================
# Akshare
# ============================================================================

class TestToAkshareFormat:
    def test_a_share_shanghai(self):
        assert cc.to_akshare_format("600519") == "600519"

    def test_a_share_shenzhen(self):
        assert cc.to_akshare_format("000001") == "000001"
        assert cc.to_akshare_format("300750") == "300750"

    def test_a_share_with_prefix_stripped(self):
        assert cc.to_akshare_format("SH600519") == "600519"
        assert cc.to_akshare_format("SZ000001") == "000001"

    def test_a_share_with_suffix(self):
        assert cc.to_akshare_format("600519.SS") == "600519"

    def test_hk_stock(self):
        assert cc.to_akshare_format("HK00700") == "00700.hk"

    def test_hk_stock_no_prefix(self):
        assert cc.to_akshare_format("00700") == "00700.hk"

    def test_hk_stock_with_dot_hk_suffix(self):
        assert cc.to_akshare_format("00700.HK") == "00700.hk"

    def test_csi_index(self):
        assert cc.to_akshare_format("000300") == "000300"
        assert cc.to_akshare_format("399006") == "399006"

    def test_us_index_spx(self):
        assert cc.to_akshare_format("SPX") == ".INX"

    def test_us_index_ixic(self):
        assert cc.to_akshare_format("IXIC") == ".IXIC"

    def test_us_index_dji(self):
        assert cc.to_akshare_format("DJI") == ".DJI"

    def test_hk_index(self):
        assert cc.to_akshare_format("HSI") == "HSI"


# ============================================================================
# Baostock
# ============================================================================

class TestToBaostockFormat:
    def test_a_share_shanghai(self):
        assert cc.to_baostock_format("600519") == ("sh.600519", "600519")

    def test_a_share_shenzhen(self):
        # 000001 is both a stock AND an index (上证指数) — Baostock
        # treats it as index via CSI_INDEX_MAP.  Use 300750 instead.
        assert cc.to_baostock_format("300750") == ("sz.300750", "300750")
        assert cc.to_baostock_format("000002") == ("sz.000002", "000002")

    def test_shenzhen_stock_000001_is_index(self):
        """000001 is 上证指数 in CSI_INDEX_MAP — treated as index, not stock."""
        assert cc.to_baostock_format("000001") == ("sh.000001", "000001")

    def test_csi_index_shanghai(self):
        assert cc.to_baostock_format("000300") == ("sh.000300", "000300")

    def test_csi_index_shenzhen(self):
        assert cc.to_baostock_format("399006") == ("sz.399006", "399006")

    def test_csi_index_not_in_map_falls_back(self):
        # 000905 is in CSI_INDEX_MAP
        assert cc.to_baostock_format("000905") == ("sh.000905", "000905")

    def test_non_csi_index_raises(self):
        with pytest.raises(ValueError, match="Baostock does not support"):
            cc.to_baostock_format("HSI")
        with pytest.raises(ValueError, match="Baostock does not support"):
            cc.to_baostock_format("SPX")

    def test_normalizes_prefix_input(self):
        assert cc.to_baostock_format("SH600519") == ("sh.600519", "600519")
        # SZ000001 → index (上证指数), returns sh.000001
        assert cc.to_baostock_format("SZ000001") == ("sh.000001", "000001")
        # SZ300750 → real Shenzhen stock
        assert cc.to_baostock_format("SZ300750") == ("sz.300750", "300750")


# ============================================================================
# Tencent
# ============================================================================

class TestToTencentPrefix:
    def test_shanghai(self):
        assert cc.to_tencent_prefix("600519") == "sh600519"

    def test_shenzhen(self):
        assert cc.to_tencent_prefix("000001") == "sz000001"
        assert cc.to_tencent_prefix("300750") == "sz300750"

    def test_beijing(self):
        assert cc.to_tencent_prefix("832000") == "bj832000"

    def test_hk(self):
        assert cc.to_tencent_prefix("HK00700") == "hk00700"

    def test_star_market(self):
        assert cc.to_tencent_prefix("688111") == "sh688111"

    def test_chinext_301(self):
        assert cc.to_tencent_prefix("301000") == "sz301000"


# ============================================================================
# EastMoney
# ============================================================================

class TestToEastMoneySecid:
    def test_shanghai(self):
        assert cc.to_eastmoney_secid("600519") == "1.600519"

    def test_shenzhen(self):
        assert cc.to_eastmoney_secid("000001") == "0.000001"
        assert cc.to_eastmoney_secid("300750") == "0.300750"

    def test_shanghai_nine_prefix(self):
        assert cc.to_eastmoney_secid("900001") == "1.900001"


# ============================================================================
# Zhitu
# ============================================================================

class TestToZhituFormat:
    def test_shanghai(self):
        assert cc.to_zhitu_format("600519") == "600519"

    def test_shenzhen(self):
        assert cc.to_zhitu_format("000001") == "000001"

    def test_normalizes_prefix(self):
        assert cc.to_zhitu_format("SH600519") == "600519"


class TestToZhituMarketSuffix:
    def test_shanghai(self):
        assert cc.to_zhitu_market_suffix("600519") == ".sh"

    def test_shenzhen(self):
        assert cc.to_zhitu_market_suffix("000001") == ".sz"
        assert cc.to_zhitu_market_suffix("300750") == ".sz"

    def test_beijing_as_sh(self):
        assert cc.to_zhitu_market_suffix("832000") == ".sh"

    def test_star_as_sh(self):
        assert cc.to_zhitu_market_suffix("688111") == ".sh"


# ============================================================================
# Yfinance
# ============================================================================

class TestToYfinanceFormat:
    def test_us_stock(self):
        assert cc.to_yfinance_format("AAPL") == "AAPL"
        assert cc.to_yfinance_format("TSLA") == "TSLA"

    def test_us_stock_lowercase(self):
        assert cc.to_yfinance_format("aapl") == "AAPL"

    def test_a_share_shanghai(self):
        assert cc.to_yfinance_format("600519") == "600519.SS"

    def test_a_share_shenzhen(self):
        # 000001 is 上证指数 index — use 300750 for Shenzhen stock
        assert cc.to_yfinance_format("300750") == "300750.SZ"
        assert cc.to_yfinance_format("000002") == "000002.SZ"

    def test_hk_stock(self):
        # Original yfinance _convert_code keeps all leading zeros:
        # normalize("HK00700") → "HK00700" → strip HK → "00700" → "00700.HK"
        assert cc.to_yfinance_format("HK00700") == "00700.HK"

    def test_us_index_spx(self):
        assert cc.to_yfinance_format("SPX") == "^GSPC"

    def test_us_index_dji(self):
        assert cc.to_yfinance_format("DJI") == "^DJI"

    def test_us_index_ixic(self):
        assert cc.to_yfinance_format("IXIC") == "^IXIC"

    def test_csi_index_shanghai(self):
        assert cc.to_yfinance_format("000300") == "000300.SS"

    def test_csi_index_shenzhen(self):
        assert cc.to_yfinance_format("399006") == "399006.SZ"

    def test_hk_index(self):
        assert cc.to_yfinance_format("HSI") == "^HSI"

    def test_already_in_yfinance_format(self):
        assert cc.to_yfinance_format("600519.SS") == "600519.SS"
        assert cc.to_yfinance_format("000001.SZ") == "000001.SZ"
        assert cc.to_yfinance_format("0700.HK") == "0700.HK"

    def test_bj_already_formatted(self):
        assert cc.to_yfinance_format("832000.BJ") == "832000.BJ"


# ============================================================================
# Tushare
# ============================================================================

class TestToTushareFormat:
    def test_a_share_shanghai(self):
        assert cc.to_tushare_format("600519") == "600519.SH"

    def test_a_share_shenzhen(self):
        # 000001 is 上证指数 index — use 300750, 000002 for Shenzhen stocks
        assert cc.to_tushare_format("300750") == "300750.SZ"
        assert cc.to_tushare_format("000002") == "000002.SZ"

    def test_csi_index_shanghai(self):
        assert cc.to_tushare_format("000300") == "000300.SH"

    def test_csi_index_shenzhen(self):
        assert cc.to_tushare_format("399006") == "399006.SZ"

    def test_non_csi_index_raises(self):
        with pytest.raises(ValueError, match="Tushare does not support"):
            cc.to_tushare_format("HSI")
        with pytest.raises(ValueError, match="Tushare does not support"):
            cc.to_tushare_format("SPX")

    def test_unsupported_code_raises(self):
        with pytest.raises(ValueError, match="Tushare does not support code"):
            cc.to_tushare_format("AAPL")

    def test_normalizes_prefix(self):
        assert cc.to_tushare_format("SH600519") == "600519.SH"


# ============================================================================
# Cross-function consistency
# ============================================================================

class TestCrossConsistency:
    """Verify that all converters agree on market classification."""

    def test_shanghai_stock_is_sh_in_all_formats(self):
        code = "600519"
        a = cc.to_akshare_format(code)
        b_bs, b_yw = cc.to_baostock_format(code)
        t = cc.to_tencent_prefix(code)
        e = cc.to_eastmoney_secid(code)
        zs = cc.to_zhitu_market_suffix(code)
        y = cc.to_yfinance_format(code)
        ts = cc.to_tushare_format(code)
        # All should indicate Shanghai
        assert a == "600519"
        assert b_bs.startswith("sh.")
        assert t.startswith("sh")
        assert e.startswith("1.")
        assert zs == ".sh"
        assert y.endswith(".SS")
        assert ts.endswith(".SH")

    def test_shenzhen_stock_is_sz_in_all_formats(self):
        # Use 300750 — 000001 is 上证指数 (treated as index, not stock)
        code = "300750"
        b_bs, b_yw = cc.to_baostock_format(code)
        t = cc.to_tencent_prefix(code)
        e = cc.to_eastmoney_secid(code)
        zs = cc.to_zhitu_market_suffix(code)
        y = cc.to_yfinance_format(code)
        ts = cc.to_tushare_format(code)
        assert b_bs.startswith("sz.")
        assert t.startswith("sz")
        assert e.startswith("0.")
        assert zs == ".sz"
        assert y.endswith(".SZ")
        assert ts.endswith(".SZ")

    def test_hk_stock_converts(self):
        code = "HK00700"
        assert cc.to_akshare_format(code) == "00700.hk"
        assert cc.to_tencent_prefix(code) == "hk00700"
        assert cc.to_yfinance_format(code) == "00700.HK"
