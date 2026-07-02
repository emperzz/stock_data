"""Tests for ThsFetcher.get_board_history."""
import pytest


class TestVToken:
    def test_v_token_is_nonempty_string(self):
        from stock_data.data_provider.fetchers.ths_fetcher import _get_ths_v_token
        v = _get_ths_v_token()
        assert isinstance(v, str) and len(v) >= 8

    def test_v_token_is_cached(self):
        from stock_data.data_provider.fetchers.ths_fetcher import _get_ths_v_token
        v1 = _get_ths_v_token()
        v2 = _get_ths_v_token()
        assert v1 == v2  # cached (lru_cache)