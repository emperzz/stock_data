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


class TestCacheEndpointRespectsDisable:
    """cache_endpoint wrapper must honor the global ENABLE_API_CACHE switch.

    Pre-2026-07-16 the wrapper unconditionally read/wrote the cache — the
    ``_ENABLE_CACHE`` flag only gated ``cached_lookup`` / ``cached_store``
    helpers (used by a small subset of routes). Operators toggling
    ``ENABLE_API_CACHE=false`` to debug stale data saw ~20 cache_endpoint
    routes still hit memory. This pins the contract that the wrapper
    short-circuits when caching is disabled.
    """

    def test_cache_endpoint_bypasses_when_disabled(self, monkeypatch):
        from cachetools import TTLCache

        from stock_data.api import cache as cache_mod

        # Use a fresh throwaway cache so prior tests can't pollute the key.
        isolated = TTLCache(maxsize=4, ttl=60)
        monkeypatch.setattr(cache_mod, "_ENABLE_CACHE", False)

        calls = {"n": 0}

        def underlying(*args, **kwargs):
            calls["n"] += 1
            return {"args": args, "kwargs": kwargs, "n": calls["n"]}

        @cache_mod.cache_endpoint(
            cache_fn=lambda *a, **kw: isolated,
            key_builder=lambda *a, **kw: "k",
            hit_label="unit-test",
        )
        def handler(x):
            return underlying(x)

        # First call: with disable, must invoke underlying directly (no write).
        out1 = handler(1)
        assert out1 == {"args": (1,), "kwargs": {}, "n": 1}
        assert calls["n"] == 1
        # The cache MUST be untouched when disabled.
        assert "k" not in isolated

        # Second call: still no cache hit, underlying fires again.
        out2 = handler(2)
        assert out2 == {"args": (2,), "kwargs": {}, "n": 2}
        assert calls["n"] == 2
        assert "k" not in isolated

    def test_cache_endpoint_caches_when_enabled(self, monkeypatch):
        """Companion test: when _ENABLE_CACHE is True, wrapper caches as before.

        Guards against the new guard accidentally short-circuiting the
        normal path.
        """
        from cachetools import TTLCache

        from stock_data.api import cache as cache_mod

        isolated = TTLCache(maxsize=4, ttl=60)
        monkeypatch.setattr(cache_mod, "_ENABLE_CACHE", True)

        calls = {"n": 0}

        def underlying():
            calls["n"] += 1
            return calls["n"]

        @cache_mod.cache_endpoint(
            cache_fn=lambda *a, **kw: isolated,
            key_builder=lambda *a, **kw: "k",
            hit_label="unit-test",
        )
        def handler():
            return underlying()

        assert handler() == 1
        assert handler() == 1  # cache hit, no second underlying call
        assert calls["n"] == 1
        assert isolated["k"] == 1


class TestCacheKeyBuilders:
    """Test cache key generation for each API endpoint."""

    def test_dragon_tiger_key_format(self):
        key = make_dragon_tiger_cache_key("600519", "2024-01-15")
        assert key == "dt:600519:2024-01-15"

    def test_dragon_tiger_key_empty_trade_date(self):
        key = make_dragon_tiger_cache_key("000001", "")
        assert key == "dt:000001:"

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
        assert make_dragon_tiger_cache_key("600519", "2024-01-15") != make_dragon_tiger_cache_key(
            "000001", "2024-01-15"
        )
        assert make_margin_cache_key("600519", 30) != make_margin_cache_key("000001", 30)
        assert make_reports_cache_key("600519", 3) != make_reports_cache_key("000001", 3)

    def test_different_dates_different_keys(self):
        assert make_dragon_tiger_cache_key("600519", "2024-01-15") != make_dragon_tiger_cache_key(
            "600519", "2024-01-16"
        )
        assert make_hot_topics_cache_key("2024-01-15") != make_hot_topics_cache_key("2024-01-16")
        assert make_pools_cache_key("zt", "2024-01-15") != make_pools_cache_key("zt", "2024-01-16")

    def test_different_page_sizes_different_keys(self):
        assert make_margin_cache_key("600519", 10) != make_margin_cache_key("600519", 30)
        assert make_announcements_cache_key("600519", 10) != make_announcements_cache_key("600519", 100)
