"""Tests for stock_list exchange normalization."""
from stock_data.data_provider.persistence.stock_list import _normalize_exchange


class TestNormalizeExchange:
    def test_none_returns_none(self):
        assert _normalize_exchange(None) is None

    def test_empty_string_returns_none(self):
        assert _normalize_exchange("") is None

    def test_sh_lowercase(self):
        assert _normalize_exchange("sh") == "SH"

    def test_SH_uppercase(self):
        assert _normalize_exchange("SH") == "SH"

    def test_SHSE_full_name(self):
        assert _normalize_exchange("SHSE") == "SH"

    def test_SSE_alias(self):
        assert _normalize_exchange("SSE") == "SH"

    def test_sz_lowercase(self):
        assert _normalize_exchange("sz") == "SZ"

    def test_SZSE_full_name(self):
        assert _normalize_exchange("SZSE") == "SZ"

    def test_bj_lowercase(self):
        assert _normalize_exchange("bj") == "BJ"

    def test_BSE_alias(self):
        assert _normalize_exchange("BSE") == "BJ"

    def test_unknown_uppercased(self):
        assert _normalize_exchange("tw") == "TW"

    def test_whitespace_stripped(self):
        assert _normalize_exchange("  sh  ") == "SH"
