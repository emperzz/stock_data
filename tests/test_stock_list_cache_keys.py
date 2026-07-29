"""Cache key builder tests for /api/v1/stocks cache layer."""

from stock_data.api.cache import (
    make_stock_list_cache_key,
    make_stock_list_quote_cache_key,
)


class TestStockListCacheKeys:
    def test_stock_list_cache_key_format(self):
        key = make_stock_list_cache_key("csi", 0, 100)
        assert key == "stock_list:csi:0:100"

    def test_stock_list_cache_key_different_pages(self):
        a = make_stock_list_cache_key("csi", 0, 100)
        b = make_stock_list_cache_key("csi", 100, 100)
        c = make_stock_list_cache_key("csi", 0, 200)
        assert a != b
        assert a != c
        assert b != c

    def test_stock_list_quote_cache_key_format(self):
        assert make_stock_list_quote_cache_key("csi") == "stock_list_quote:csi"

    def test_stock_list_quote_cache_key_per_market(self):
        assert (
            make_stock_list_quote_cache_key("csi")
            != make_stock_list_quote_cache_key("hk")
        )
        assert (
            make_stock_list_quote_cache_key("hk")
            != make_stock_list_quote_cache_key("us")
        )
