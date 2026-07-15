"""
Tests for AkshareFetcher._normalize_zt_pool and _akshare_seal_time_to_hms.

Regression coverage for the 2026-07-15 audit findings:
- ``first_seal_time`` / ``last_seal_time`` come from upstream as 6-digit
  integers (e.g. ``141354``) and MUST be normalized to ``HH:MM:SS``.
- DT pool uses different column names (``连续跌停`` / ``开板次数`` /
  ``封单资金``) than ZT/ZBGC.
- ``seal_amount`` / ``circ_mv`` / ``total_mv`` were hardcoded to ``None``;
  the upstream actually exposes these columns.
"""

from unittest.mock import patch

import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Seal-time normalization (the user-reported bug)
# ---------------------------------------------------------------------------

class TestSealTimeToHms:
    """_akshare_seal_time_to_hms must coerce upstream's 6-digit int to HH:MM:SS."""

    def setup_method(self):
        from stock_data.data_provider.fetchers.akshare.fetcher import AkshareFetcher
        self.fetcher = AkshareFetcher()

    def test_int_141354(self):
        assert self.fetcher._akshare_seal_time_to_hms(141354) == "14:13:54"

    def test_int_150000(self):
        """The literal example the user reported."""
        assert self.fetcher._akshare_seal_time_to_hms(150000) == "15:00:00"

    def test_int_092500(self):
        assert self.fetcher._akshare_seal_time_to_hms(92500) == "09:25:00"

    def test_str_digits(self):
        """Akshare sometimes returns the time as a string of digits."""
        assert self.fetcher._akshare_seal_time_to_hms("141354") == "14:13:54"

    def test_str_already_hms_unchanged(self):
        """Defensive: if upstream ever returns the documented HH:MM:SS, keep it."""
        assert self.fetcher._akshare_seal_time_to_hms("09:25:00") == "09:25:00"

    def test_str_hm_gets_seconds_appended(self):
        assert self.fetcher._akshare_seal_time_to_hms("09:25") == "09:25:00"

    @pytest.mark.parametrize("raw", [None, "", "nan", "None", "-", "--"])
    def test_nullish_returns_none(self, raw):
        assert self.fetcher._akshare_seal_time_to_hms(raw) is None

    def test_nan_float_returns_none(self):
        # pandas reads missing cells as float('nan'); NaN != NaN
        assert self.fetcher._akshare_seal_time_to_hms(float("nan")) is None

    def test_unparseable_returns_none(self):
        assert self.fetcher._akshare_seal_time_to_hms("not-a-time") is None


# ---------------------------------------------------------------------------
# _normalize_zt_pool — ZT pool
# ---------------------------------------------------------------------------

def _make_zt_df() -> pd.DataFrame:
    """Build a fake ZT-pool DataFrame mirroring real upstream columns.

    Real upstream sample (from docs/akshare/stock/stock_zt_pool_em.md):
        序号, 代码, 名称, 涨跌幅, 最新价, 成交额, 流通市值, 总市值, 换手率,
        封板资金, 首次封板时间, 最后封板时间, 炸板次数, 涨停统计, 连板数, 所属行业
    Real ``首次封板时间``/``最后封板时间`` values are 6-digit ints (e.g. 141354).
    """
    return pd.DataFrame(
        [
            {
                "代码": "000004",
                "名称": "国华网安",
                "涨跌幅": 10.0,
                "最新价": 17.93,
                "成交额": 123456789,
                "流通市值": 5.0e9,
                "总市值": 6.0e9,
                "换手率": 5.5,
                "封板资金": 98243407,
                "首次封板时间": 141354,
                "最后封板时间": 150000,
                "炸板次数": 1,
                "涨停统计": "10/6",
                "连板数": 2,
                "所属行业": "软件开发",
            },
        ]
    )


def _make_dt_df() -> pd.DataFrame:
    """Build a fake DT-pool DataFrame mirroring real upstream columns.

    Real upstream sample (from docs/akshare/stock/stock_zt_pool_dtgc_em.md):
        序号, 代码, 名称, 涨跌幅, 最新价, 成交额, 流通市值, 总市值, 动态市盈率,
        换手率, 封单资金, 最后封板时间, 板上成交额, 连续跌停, 开板次数, 所属行业
    """
    return pd.DataFrame(
        [
            {
                "代码": "002795",
                "名称": "永和智控",
                "涨跌幅": -9.91,
                "最新价": 3.82,
                "成交额": 24222238,
                "流通市值": 1.0e9,
                "总市值": 1.2e9,
                "动态市盈率": 0.0,
                "换手率": 2.0,
                "封单资金": 5000000,
                "最后封板时间": 143233,
                "板上成交额": 1000000,
                "连续跌停": 1,
                "开板次数": 3,
                "所属行业": "通用设备",
            },
        ]
    )


def _make_zbgc_df() -> pd.DataFrame:
    """Build a fake ZBGC-pool DataFrame mirroring real upstream columns.

    Real upstream sample (from docs/akshare/stock/stock_zt_pool_zbgc_em.md):
        序号, 代码, 名称, 涨跌幅, 最新价, 涨停价, 成交额, 流通市值, 总市值,
        换手率, 涨速, 首次封板时间, 炸板次数, 涨停统计, 振幅, 所属行业
    """
    return pd.DataFrame(
        [
            {
                "代码": "002347",
                "名称": "泰尔股份",
                "涨跌幅": -0.92,
                "最新价": 5.38,
                "涨停价": 5.99,
                "成交额": 30000000,
                "流通市值": 4.0e8,
                "总市值": 5.0e8,
                "换手率": 1.2,
                "涨速": 0.5,
                "首次封板时间": 92500,
                "炸板次数": 3,
                "涨停统计": "3/2",
                "振幅": 17.31,
                "所属行业": "通用设备",
            },
        ]
    )


class TestNormalizeZtPoolZt:
    """ZT pool: 封板资金 / 流通市值 / 总市值 must be populated; time HH:MM:SS."""

    def test_seal_times_normalized(self):
        from stock_data.data_provider.fetchers.akshare.fetcher import AkshareFetcher
        fetcher = AkshareFetcher()
        result = fetcher._normalize_zt_pool(_make_zt_df(), "zt")
        stock = result[0]
        assert stock["first_seal_time"] == "14:13:54"
        assert stock["last_seal_time"] == "15:00:00"

    def test_seal_amount_populated_from_封板资金(self):
        from stock_data.data_provider.fetchers.akshare.fetcher import AkshareFetcher
        fetcher = AkshareFetcher()
        result = fetcher._normalize_zt_pool(_make_zt_df(), "zt")
        assert result[0]["seal_amount"] == 98243407

    def test_circ_mv_and_total_mv_populated(self):
        from stock_data.data_provider.fetchers.akshare.fetcher import AkshareFetcher
        fetcher = AkshareFetcher()
        result = fetcher._normalize_zt_pool(_make_zt_df(), "zt")
        stock = result[0]
        assert stock["circ_mv"] == 5.0e9
        assert stock["total_mv"] == 6.0e9

    def test_lb_count_uses_连板数(self):
        from stock_data.data_provider.fetchers.akshare.fetcher import AkshareFetcher
        fetcher = AkshareFetcher()
        result = fetcher._normalize_zt_pool(_make_zt_df(), "zt")
        assert result[0]["lb_count"] == 2

    def test_seal_count_uses_炸板次数(self):
        from stock_data.data_provider.fetchers.akshare.fetcher import AkshareFetcher
        fetcher = AkshareFetcher()
        result = fetcher._normalize_zt_pool(_make_zt_df(), "zt")
        assert result[0]["seal_count"] == 1

    def test_zt_count_uses_涨停统计(self):
        from stock_data.data_provider.fetchers.akshare.fetcher import AkshareFetcher
        fetcher = AkshareFetcher()
        result = fetcher._normalize_zt_pool(_make_zt_df(), "zt")
        assert result[0]["zt_count"] == "10/6"


class TestNormalizeZtPoolDt:
    """DT pool: 连续跌停 / 开板次数 / 封单资金 columns; no 首次封板时间/涨停统计."""

    def test_dt_uses_连续跌停_for_lb_count(self):
        """The column is 连续跌停 (not 连续跌停次数). Regression: prior fetcher
        looked up 连续跌停次数 which doesn't exist upstream, so lb_count was
        always None for DT pool."""
        from stock_data.data_provider.fetchers.akshare.fetcher import AkshareFetcher
        fetcher = AkshareFetcher()
        result = fetcher._normalize_zt_pool(_make_dt_df(), "dt")
        assert result[0]["lb_count"] == 1

    def test_dt_uses_开板次数_for_seal_count(self):
        """The column is 开板次数 (not 炸板次数). Regression: prior fetcher
        looked up 炸板次数 which doesn't exist in the DT pool, so seal_count
        was always None for DT pool."""
        from stock_data.data_provider.fetchers.akshare.fetcher import AkshareFetcher
        fetcher = AkshareFetcher()
        result = fetcher._normalize_zt_pool(_make_dt_df(), "dt")
        assert result[0]["seal_count"] == 3

    def test_dt_uses_封单资金_for_seal_amount(self):
        """DT pool's 封单资金 == ZT pool's 封板资金 (both = money on the seal)."""
        from stock_data.data_provider.fetchers.akshare.fetcher import AkshareFetcher
        fetcher = AkshareFetcher()
        result = fetcher._normalize_zt_pool(_make_dt_df(), "dt")
        assert result[0]["seal_amount"] == 5000000

    def test_dt_has_no_first_seal_time(self):
        from stock_data.data_provider.fetchers.akshare.fetcher import AkshareFetcher
        fetcher = AkshareFetcher()
        result = fetcher._normalize_zt_pool(_make_dt_df(), "dt")
        assert result[0]["first_seal_time"] is None

    def test_dt_has_no_zt_count(self):
        from stock_data.data_provider.fetchers.akshare.fetcher import AkshareFetcher
        fetcher = AkshareFetcher()
        result = fetcher._normalize_zt_pool(_make_dt_df(), "dt")
        assert result[0]["zt_count"] is None

    def test_dt_last_seal_time_normalized(self):
        from stock_data.data_provider.fetchers.akshare.fetcher import AkshareFetcher
        fetcher = AkshareFetcher()
        result = fetcher._normalize_zt_pool(_make_dt_df(), "dt")
        assert result[0]["last_seal_time"] == "14:32:33"


class TestNormalizeZtPoolZbgc:
    """ZBGC pool: 首次封板时间 (int) + 炸板次数 + 涨停统计; no 最后封板时间/封板资金."""

    def test_zbgc_first_seal_time_normalized(self):
        from stock_data.data_provider.fetchers.akshare.fetcher import AkshareFetcher
        fetcher = AkshareFetcher()
        result = fetcher._normalize_zt_pool(_make_zbgc_df(), "zbgc")
        assert result[0]["first_seal_time"] == "09:25:00"

    def test_zbgc_no_last_seal_time(self):
        from stock_data.data_provider.fetchers.akshare.fetcher import AkshareFetcher
        fetcher = AkshareFetcher()
        result = fetcher._normalize_zt_pool(_make_zbgc_df(), "zbgc")
        assert result[0]["last_seal_time"] is None

    def test_zbgc_no_seal_amount(self):
        from stock_data.data_provider.fetchers.akshare.fetcher import AkshareFetcher
        fetcher = AkshareFetcher()
        result = fetcher._normalize_zt_pool(_make_zbgc_df(), "zbgc")
        assert result[0]["seal_amount"] is None

    def test_zbgc_no_lb_count(self):
        """ZBGC upstream has no 连板数 column."""
        from stock_data.data_provider.fetchers.akshare.fetcher import AkshareFetcher
        fetcher = AkshareFetcher()
        result = fetcher._normalize_zt_pool(_make_zbgc_df(), "zbgc")
        assert result[0]["lb_count"] is None

    def test_zbgc_seal_count_from_炸板次数(self):
        from stock_data.data_provider.fetchers.akshare.fetcher import AkshareFetcher
        fetcher = AkshareFetcher()
        result = fetcher._normalize_zt_pool(_make_zbgc_df(), "zbgc")
        assert result[0]["seal_count"] == 3

    def test_zbgc_zt_count_from_涨停统计(self):
        from stock_data.data_provider.fetchers.akshare.fetcher import AkshareFetcher
        fetcher = AkshareFetcher()
        result = fetcher._normalize_zt_pool(_make_zbgc_df(), "zbgc")
        assert result[0]["zt_count"] == "3/2"

    def test_zbgc_circ_mv_and_total_mv_populated(self):
        from stock_data.data_provider.fetchers.akshare.fetcher import AkshareFetcher
        fetcher = AkshareFetcher()
        result = fetcher._normalize_zt_pool(_make_zbgc_df(), "zbgc")
        stock = result[0]
        assert stock["circ_mv"] == 4.0e8
        assert stock["total_mv"] == 5.0e8


# ---------------------------------------------------------------------------
# End-to-end: empty DataFrame (no rows)
# ---------------------------------------------------------------------------

def test_empty_dataframe_returns_empty_list():
    from stock_data.data_provider.fetchers.akshare.fetcher import AkshareFetcher
    fetcher = AkshareFetcher()
    empty = pd.DataFrame(columns=[
        "代码", "名称", "涨跌幅", "最新价", "成交额", "流通市值", "总市值",
        "换手率", "封板资金", "首次封板时间", "最后封板时间", "炸板次数",
        "涨停统计", "连板数", "所属行业",
    ])
    assert fetcher._normalize_zt_pool(empty, "zt") == []
