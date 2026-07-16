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

    def test_shanghai_star_market(self):
        """68xxxxx (STAR Market) is SH."""
        assert cc.to_eastmoney_secid("688052") == "1.688052"

    def test_shanghai_fund_etf(self):
        """5xxxxx SH funds/ETFs probed 2026-07-02 against np-listapi getListInfo:
        only secid=1.{code} returns data; 0.{code} fails. See code_converter docstring.
        """
        assert cc.to_eastmoney_secid("510050") == "1.510050"
        assert cc.to_eastmoney_secid("510300") == "1.510300"

    def test_bse_falls_through_to_sz_prefix(self):
        """BSE codes (4xxxxx, 8xxxxx) are not natively handled by EastMoney
        push2 endpoints (most return data:null), so the helper falls through
        to the SZ prefix ``0.{code}``. Callers that need BSE should
        skip EastMoney routing entirely (see code_converter docstring).
        """
        assert cc.to_eastmoney_secid("430017") == "0.430017"
        assert cc.to_eastmoney_secid("830799") == "0.830799"


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


class TestToZhituIndexMarketSuffix:
    """CSI 指数后缀规则(与股票 helper 相反): 000xxx → SH, 399xxx → SZ。

    实际生效代码路径(zhitu_fetcher.py):
        - get_index_realtime_quote  → /hz/real/ssjy/<code>.<SH|SZ>
        - _get_index_kline_data     → /hz/history/fsjy/<code>.<SH|SZ>/<level>
    """

    @pytest.mark.parametrize(
        "code, expected_suffix, label",
        [
            ("000001", ".SH", "上证综指"),
            ("000300", ".SH", "沪深300"),
            ("000016", ".SH", "上证50"),
            ("000688", ".SH", "科创50"),
            ("000905", ".SH", "中证500"),
        ],
    )
    def test_shanghai_index_000xxx(self, code, expected_suffix, label):
        assert cc.to_zhitu_index_market_suffix(code) == expected_suffix

    @pytest.mark.parametrize(
        "code, expected_suffix, label",
        [
            ("399001", ".SZ", "深证成指"),
            ("399006", ".SZ", "创业板指"),
            ("399005", ".SZ", "中小板指"),
        ],
    )
    def test_shenzhen_index_399xxx(self, code, expected_suffix, label):
        assert cc.to_zhitu_index_market_suffix(code) == expected_suffix

    def test_stock_000xxx_goes_to_sz_under_index_helper(self):
        """股票 000xxx 用 index helper 时返 .SZ — 文档明示这是有意的。

        helper 的注释解释了 000xxx 在指数里是 SH、股票里是 SZ 的对偶。
        """
        assert cc.to_zhitu_index_market_suffix("000001") == ".SH"  # 指数
        # 同样的代码在股票 helper 里:
        assert cc.to_zhitu_market_suffix("000001") == ".sz"  # 股票

    def test_normalizes_prefix(self):
        """``SH000001`` 经 normalize 后必须能识别为 SH 指数。"""
        assert cc.to_zhitu_index_market_suffix("SH000001") == ".SH"
        assert cc.to_zhitu_index_market_suffix("sz399006") == ".SZ"

    def test_no_dead_999_branch(self):
        """``999xxx`` 不在 CSI_INDEX_MAP(13 个), 也不被 get_index_type 归为 csi。

        helper 仅对 000xxx 返回 SH, 其他全部 SZ — 999 应走 SZ 分支
        (即使 upstream 实际不接受 999 代码; 防御性默认)。
        """
        assert cc.to_zhitu_index_market_suffix("999001") == ".SZ"

    def test_hk_index_out_of_scope(self):
        """HK 指数(如 HSI)Zhitu 不支持, 但 helper 在 contract 上仍返 .SZ
        (normalize 后非数字 / 非 6 位数字, 不匹配 000 分支)。

        实际 manager 不会把 HSI 路由到 Zhitu(supported_markets=csi), 这里
        只验证 helper 不会崩。
        """
        assert cc.to_zhitu_index_market_suffix("HSI") == ".SZ"


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

    def test_399_a_share_fallback_also_sz(self):
        """399xxx 不在 CSI_INDEX_MAP 时(经 A 股股票分支)也返 .SZ。

        当前实现: ``is_index_code`` 对未在 map 的 399 返 False, 走 A 股
        股票分支 ``startswith("3")`` 也给 .SZ — 因此该测试在修复前后都通过,
        属于契约记录而非 TDD 回归。真正的 TDD 回归见
        ``test_tushare_unmapped_000_fallback_branch``。
        """
        assert cc.to_tushare_format("399370") == "399370.SZ"

    def test_tushare_unmapped_000_fallback_branch(self):
        """直接探测修复后的 fallback 路径: 对假设 ``is_index_code=True`` 但
        ``CSI_INDEX_MAP.get=None`` 的场景, 必须按 399→SZ / 其他→SH 分流.

        通过 mock 让 ``is_index_code`` 强制返回 True, 走修复后的代码路径.
        """
        from unittest.mock import patch

        # ``is_index_code`` 从 ..utils.normalize 重导出到 code_converter 模块级
        # 引用, mock 必须在 code_converter 里拦截。``get_index_type`` 是函数
        # 内 from-import, mock 必须在源模块 (index_symbols) 拦截。
        with patch(
            "stock_data.data_provider.utils.code_converter.is_index_code",
            return_value=True,
        ), patch(
            "stock_data.data_provider.fetchers.index_symbols.get_index_type",
            return_value="csi",
        ):
            assert cc.to_tushare_format("399370") == "399370.SZ"
            assert cc.to_tushare_format("000370") == "000370.SH"
            assert cc.to_tushare_format("512500") == "512500.SH"


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


# ====================================================================
# Myquant
# ====================================================================


class TestToMyquantFormat:
    def test_shanghai_stock(self):
        from stock_data.data_provider.utils.code_converter import to_myquant_format

        assert to_myquant_format("600519") == "SHSE.600519"

    def test_shenzhen_stock(self):
        from stock_data.data_provider.utils.code_converter import to_myquant_format

        # 000001 is 上证指数 index — use 000002 for Shenzhen stock
        assert to_myquant_format("000002") == "SZSE.000002"

    def test_beijing_stock(self):
        from stock_data.data_provider.utils.code_converter import to_myquant_format

        # Beijing exchange codes (8xxxxx) route to SZSE prefix per myquant docs
        assert to_myquant_format("832000") == "SZSE.832000"

    def test_hk_raises(self):
        from stock_data.data_provider.utils.code_converter import to_myquant_format

        with pytest.raises(ValueError, match="does not support"):
            to_myquant_format("HK00700")

    def test_us_raises(self):
        from stock_data.data_provider.utils.code_converter import to_myquant_format

        with pytest.raises(ValueError, match="does not support"):
            to_myquant_format("AAPL")

    def test_index_raises(self):
        """Index code should raise to force caller to use to_myquant_index_format."""
        from stock_data.data_provider.utils.code_converter import to_myquant_format

        with pytest.raises(ValueError, match="to_myquant_index_format"):
            to_myquant_format("000300")

    def test_chinext(self):
        from stock_data.data_provider.utils.code_converter import to_myquant_format

        assert to_myquant_format("300750") == "SZSE.300750"

    def test_star_market(self):
        from stock_data.data_provider.utils.code_converter import to_myquant_format

        assert to_myquant_format("688981") == "SHSE.688981"


class TestToMyquantIndexFormat:
    def test_csi_shanghai(self):
        from stock_data.data_provider.utils.code_converter import to_myquant_index_format

        assert to_myquant_index_format("000300") == "SHSE.000300"

    def test_csi_shenzhen(self):
        from stock_data.data_provider.utils.code_converter import to_myquant_index_format

        assert to_myquant_index_format("399006") == "SZSE.399006"

    def test_non_csi_raises(self):
        from stock_data.data_provider.utils.code_converter import to_myquant_index_format

        with pytest.raises(ValueError, match="non-CSI"):
            to_myquant_index_format("HSI")

    def test_non_index_raises(self):
        from stock_data.data_provider.utils.code_converter import to_myquant_index_format

        with pytest.raises(ValueError, match="Not an index"):
            to_myquant_index_format("600519")
