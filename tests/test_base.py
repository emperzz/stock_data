# -*- coding: utf-8 -*-
"""
Tests for base classes and utilities.
"""

import pytest

from stock_data.data_provider.base import (
    normalize_stock_code,
    canonical_stock_code,
    is_us_market,
    is_hk_market,
    is_etf_code,
    is_bse_code,
    market_tag,
    STANDARD_COLUMNS,
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

    def test_etf(self):
        assert is_etf_code("512000")  # Shanghai ETF
        assert is_etf_code("159919")  # Shenzhen ETF

    def test_not_etf(self):
        assert not is_etf_code("600519")  # Regular stock
        assert not is_etf_code("AAPL")  # US stock


class TestMarketTag:
    """Tests for market_tag function."""

    def test_us(self):
        assert market_tag("AAPL") == "us"

    def test_hk(self):
        assert market_tag("HK00700") == "hk"

    def test_cn_default(self):
        assert market_tag("600519") == "cn"
        assert market_tag("000001") == "cn"


class TestStandardColumns:
    """Tests for STANDARD_COLUMNS constant."""

    def test_has_required_columns(self):
        required = ["date", "open", "high", "low", "close", "volume", "amount", "pct_chg"]
        for col in required:
            assert col in STANDARD_COLUMNS
