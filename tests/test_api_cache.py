"""
Unit tests for API cache key builders and cache logic.

Covers: stock_data/api/cache.py
- make_dragon_tiger_cache_key
- make_daily_dragon_tiger_cache_key
- make_margin_cache_key
- make_block_trade_cache_key
- make_holder_num_cache_key
- make_dividend_cache_key
- make_fund_flow_cache_key
- make_fund_flow_daily_cache_key
- make_hot_topics_cache_key
- make_north_flow_cache_key
- make_reports_cache_key
- make_announcements_cache_key
- make_pools_cache_key
"""

import pytest
from stock_data.api.cache import (
    make_announcements_cache_key,
    make_block_trade_cache_key,
    make_daily_dragon_tiger_cache_key,
    make_dividend_cache_key,
    make_dragon_tiger_cache_key,
    make_fund_flow_cache_key,
    make_fund_flow_daily_cache_key,
    make_holder_num_cache_key,
    make_hot_topics_cache_key,
    make_margin_cache_key,
    make_north_flow_cache_key,
    make_pools_cache_key,
    make_reports_cache_key,
)


class TestCacheKeyBuilders:
    """Test cache key generation for each API endpoint."""

    def test_dragon_tiger_key_format(self):
        key = make_dragon_tiger_cache_key("600519", "2024-01-15", 30)
        assert key == "dt:600519:2024-01-15:30"

    def test_dragon_tiger_key_look_back_variations(self):
        assert make_dragon_tiger_cache_key("000001", "2024-03-01", 7) == "dt:000001:2024-03-01:7"
        assert make_dragon_tiger_cache_key("000001", "2024-03-01", 90) == "dt:000001:2024-03-01:90"

    def test_daily_dragon_tiger_key_with_min_net_buy(self):
        key = make_daily_dragon_tiger_cache_key("2024-01-15", 1000.0)
        assert key == "dtdaily:2024-01-15:1000.0"

    def test_daily_dragon_tiger_key_without_min_net_buy(self):
        key = make_daily_dragon_tiger_cache_key("2024-01-15", None)
        assert key == "dtdaily:2024-01-15:"

    def test_daily_dragon_tiger_key_zero_min_net_buy(self):
        key = make_daily_dragon_tiger_cache_key("2024-01-15", 0.0)
        assert key == "dtdaily:2024-01-15:0.0"

    def test_margin_cache_key(self):
        key = make_margin_cache_key("600519", 30)
        assert key == "margin:600519:30"

    def test_margin_cache_key_page_sizes(self):
        assert make_margin_cache_key("600519", 10) == "margin:600519:10"
        assert make_margin_cache_key("600519", 100) == "margin:600519:100"

    def test_block_trade_cache_key(self):
        key = make_block_trade_cache_key("600519", 20)
        assert key == "block:600519:20"

    def test_holder_num_cache_key(self):
        key = make_holder_num_cache_key("600519", 10)
        assert key == "holder:600519:10"

    def test_dividend_cache_key(self):
        key = make_dividend_cache_key("600519", 20)
        assert key == "div:600519:20"

    def test_fund_flow_cache_key(self):
        key = make_fund_flow_cache_key("600519")
        assert key == "ff:600519"

    def test_fund_flow_daily_cache_key(self):
        key = make_fund_flow_daily_cache_key("600519")
        assert key == "ffd:600519"

    def test_hot_topics_cache_key(self):
        key = make_hot_topics_cache_key("2024-01-15")
        assert key == "hot:2024-01-15"

    def test_hot_topics_cache_key_empty_date(self):
        key = make_hot_topics_cache_key("")
        assert key == "hot:"

    def test_north_flow_cache_key(self):
        key = make_north_flow_cache_key()
        assert key == "north:realtime"

    def test_reports_cache_key(self):
        key = make_reports_cache_key("600519", 3)
        assert key == "rpt:600519:3"

    def test_reports_cache_key_max_pages_variations(self):
        assert make_reports_cache_key("000001", 1) == "rpt:000001:1"
        assert make_reports_cache_key("000001", 10) == "rpt:000001:10"

    def test_announcements_cache_key(self):
        key = make_announcements_cache_key("600519", 30)
        assert key == "ann:600519:30"

    def test_announcements_cache_key_page_sizes(self):
        assert make_announcements_cache_key("600519", 10) == "ann:600519:10"
        assert make_announcements_cache_key("600519", 100) == "ann:600519:100"

    def test_pools_cache_key_with_date(self):
        key = make_pools_cache_key("zt", "2024-01-15")
        assert key == "pool:zt:2024-01-15"

    def test_pools_cache_key_without_date(self):
        key = make_pools_cache_key("dt", None)
        assert key == "pool:dt:"

    def test_pools_cache_key_all_types(self):
        assert make_pools_cache_key("zt", "2024-01-15") == "pool:zt:2024-01-15"
        assert make_pools_cache_key("dt", "2024-01-15") == "pool:dt:2024-01-15"
        assert make_pools_cache_key("zbgc", "2024-01-15") == "pool:zbgc:2024-01-15"


class TestCacheKeyUniqueness:
    """Test that different parameters produce different keys."""

    def test_different_codes_different_keys(self):
        assert make_dragon_tiger_cache_key("600519", "2024-01-15", 30) != make_dragon_tiger_cache_key(
            "000001", "2024-01-15", 30
        )
        assert make_margin_cache_key("600519", 30) != make_margin_cache_key("000001", 30)
        assert make_reports_cache_key("600519", 3) != make_reports_cache_key("000001", 3)

    def test_different_dates_different_keys(self):
        assert make_dragon_tiger_cache_key("600519", "2024-01-15", 30) != make_dragon_tiger_cache_key(
            "600519", "2024-01-16", 30
        )
        assert make_hot_topics_cache_key("2024-01-15") != make_hot_topics_cache_key("2024-01-16")
        assert make_pools_cache_key("zt", "2024-01-15") != make_pools_cache_key("zt", "2024-01-16")

    def test_different_page_sizes_different_keys(self):
        assert make_margin_cache_key("600519", 10) != make_margin_cache_key("600519", 30)
        assert make_announcements_cache_key("600519", 10) != make_announcements_cache_key("600519", 100)

    def test_different_look_back_different_keys(self):
        assert make_dragon_tiger_cache_key("600519", "2024-01-15", 7) != make_dragon_tiger_cache_key(
            "600519", "2024-01-15", 30
        )
        assert make_dragon_tiger_cache_key("600519", "2024-01-15", 90) != make_dragon_tiger_cache_key(
            "600519", "2024-01-15", 30
        )