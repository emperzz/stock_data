"""Tests for the ths_board_id_map table (THS cid → platecode)."""

from __future__ import annotations

import pytest

from stock_data.data_provider.persistence import board as board_mod
from stock_data.data_provider.persistence import db as db_mod


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_mod, "_db_path", None)
    monkeypatch.setattr(db_mod, "_conn", None)
    monkeypatch.setattr(board_mod, "_schema_initialized_paths", set())
    monkeypatch.setenv("STOCK_CACHE_DB_PATH", str(tmp_path / "test.db"))
    board_mod.init_schema()
    yield


class TestIsThsCid:
    def test_concept_cid_accepted(self):
        assert board_mod._is_ths_cid("300188") is True

    def test_industry_cid_accepted(self):
        assert board_mod._is_ths_cid("881121") is True

    def test_zzshare_code_rejected(self):
        """710xxx / 803xxx are zzshare plate codes, not THS cids (spec §3.1)."""
        assert board_mod._is_ths_cid("710002") is False
        assert board_mod._is_ths_cid("803003") is False

    def test_platecode_rejected(self):
        assert board_mod._is_ths_cid("885311") is False

    def test_non_string_and_bad_length_rejected(self):
        assert board_mod._is_ths_cid(None) is False
        assert board_mod._is_ths_cid(300188) is False
        assert board_mod._is_ths_cid("30018") is False
        assert board_mod._is_ths_cid("３００１８８") is False  # fullwidth digits


class TestUpsertAndResolve:
    def test_roundtrip(self, fresh_db):
        written = board_mod.upsert_ths_board_id_map(
            [
                {"cid": "309121", "platecode": "886071", "name": "AI PC", "board_type": "concept"},
                {"cid": "881121", "platecode": "881121", "name": "半导体", "board_type": "industry"},
            ]
        )
        assert written == 2
        assert board_mod.resolve_ths_platecode("309121") == "886071"
        # industry identity row keeps resolve() heuristic-free
        assert board_mod.resolve_ths_platecode("881121") == "881121"

    def test_resolve_unknown_returns_none(self, fresh_db):
        assert board_mod.resolve_ths_platecode("999999") is None

    def test_resolve_empty_returns_none(self, fresh_db):
        assert board_mod.resolve_ths_platecode("") is None

    def test_zzshare_cid_rejected_on_write(self, fresh_db):
        """A 710xxx 'cid' from the legacy CSV must never enter the map."""
        written = board_mod.upsert_ths_board_id_map(
            [{"cid": "710002", "platecode": "710002", "name": "DeFi", "board_type": "concept"}]
        )
        assert written == 0
        assert board_mod.resolve_ths_platecode("710002") is None

    def test_row_without_platecode_skipped(self, fresh_db):
        written = board_mod.upsert_ths_board_id_map([{"cid": "309121", "platecode": ""}])
        assert written == 0

    def test_later_write_wins(self, fresh_db):
        """The tool MUST be able to overwrite a stale seed value (spec §3.2)."""
        board_mod.upsert_ths_board_id_map(
            [{"cid": "309121", "platecode": "886071", "name": "AI PC", "board_type": "concept"}]
        )
        board_mod.upsert_ths_board_id_map(
            [{"cid": "309121", "platecode": "886999", "name": "AI PC", "board_type": "concept"}]
        )
        assert board_mod.resolve_ths_platecode("309121") == "886999"

    def test_rewrite_updates_name_without_duplicating(self, fresh_db):
        board_mod.upsert_ths_board_id_map(
            [{"cid": "309121", "platecode": "886071", "name": "AI PC", "board_type": "concept"}]
        )
        board_mod.upsert_ths_board_id_map(
            [{"cid": "309121", "platecode": "886071", "name": "AI PC 概念", "board_type": "concept"}]
        )
        rows = board_mod.get_ths_board_id_map_rows()
        assert len(rows) == 1
        assert rows[0]["name"] == "AI PC 概念"

    def test_empty_input_is_noop(self, fresh_db):
        assert board_mod.upsert_ths_board_id_map([]) == 0
        assert board_mod.get_ths_board_id_map_rows() == []

    def test_get_rows_sorted_by_cid(self, fresh_db):
        board_mod.upsert_ths_board_id_map(
            [
                {"cid": "309121", "platecode": "886071", "name": "AI PC", "board_type": "concept"},
                {"cid": "300188", "platecode": "885333", "name": "移动支付", "board_type": "concept"},
            ]
        )
        assert [r["cid"] for r in board_mod.get_ths_board_id_map_rows()] == ["300188", "309121"]
