"""Tests for stock_list exchange normalization."""
from stock_data.data_provider.persistence.stock_list import (
    _normalize_exchange,
    get_cached_stocks,
    update_cached_stocks,
)


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


class TestExchangeRoundTrip:
    """Round-trip: update_cached_stocks writes _normalize_exchange'd value,
    get_cached_stocks reads it back."""

    def test_round_trip_zhitu_jys_sh(self, tmp_path, monkeypatch):
        from stock_data.data_provider.persistence import db, stock_list
        monkeypatch.setattr(db, "get_db_path", lambda: tmp_path / "test.db")
        monkeypatch.setattr(db, "_conn", None, raising=False)
        stock_list.init_schema()

        update_cached_stocks("csi", [
            {"code": "688411", "name": "N海博", "exchange": "sh"},
        ])
        rows = get_cached_stocks("csi")
        assert len(rows) == 1
        assert rows[0]["exchange"] == "SH"

    def test_round_trip_myquant_SHSE(self, tmp_path, monkeypatch):
        from stock_data.data_provider.persistence import db, stock_list
        monkeypatch.setattr(db, "get_db_path", lambda: tmp_path / "test.db")
        monkeypatch.setattr(db, "_conn", None, raising=False)
        stock_list.init_schema()

        update_cached_stocks("csi", [
            {"code": "600519", "name": "贵州茅台", "exchange": "SHSE"},
        ])
        rows = get_cached_stocks("csi")
        assert len(rows) == 1
        assert rows[0]["exchange"] == "SH"

    def test_round_trip_missing_exchange_is_none(self, tmp_path, monkeypatch):
        from stock_data.data_provider.persistence import db, stock_list
        monkeypatch.setattr(db, "get_db_path", lambda: tmp_path / "test.db")
        monkeypatch.setattr(db, "_conn", None, raising=False)
        stock_list.init_schema()

        update_cached_stocks("csi", [
            {"code": "000001", "name": "平安银行"},
        ])
        rows = get_cached_stocks("csi")
        assert len(rows) == 1
        assert rows[0]["exchange"] is None

    def test_round_trip_explicit_none_is_none(self, tmp_path, monkeypatch):
        from stock_data.data_provider.persistence import db, stock_list
        monkeypatch.setattr(db, "get_db_path", lambda: tmp_path / "test.db")
        monkeypatch.setattr(db, "_conn", None, raising=False)
        stock_list.init_schema()

        update_cached_stocks("csi", [
            {"code": "000002", "name": "万 科Ａ", "exchange": None},
        ])
        rows = get_cached_stocks("csi")
        assert rows[0]["exchange"] is None

    def test_round_trip_dict_has_exchange_key(self, tmp_path, monkeypatch):
        """Even when normalized to None, the read dict must include the key
        (so /stocks response can expose it as null)."""
        from stock_data.data_provider.persistence import db, stock_list
        monkeypatch.setattr(db, "get_db_path", lambda: tmp_path / "test.db")
        monkeypatch.setattr(db, "_conn", None, raising=False)
        stock_list.init_schema()

        update_cached_stocks("csi", [
            {"code": "000001", "name": "平安银行"},
        ])
        rows = get_cached_stocks("csi")
        assert "exchange" in rows[0]  # noqa: SIM118
