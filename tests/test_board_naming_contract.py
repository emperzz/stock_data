"""Naming contract for the board path (spec §5.1).

Board row dicts must use `board_code` / `ths_cid` / `board_type`.
A bare `code` key is the bug this contract exists to prevent: the same key
meant `cid` in ThsFetcher and `platecode` in update_cached_boards, which is
how the two code spaces got conflated (spec §1.2).
"""

from __future__ import annotations

import pytest

from stock_data.data_provider.persistence import board as board_mod
from stock_data.data_provider.persistence import db as db_mod

FORBIDDEN_BARE_CODE = "code"


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_mod, "_db_path", None)
    monkeypatch.setattr(db_mod, "_conn", None)
    monkeypatch.setattr(board_mod, "_schema_initialized_paths", set())
    monkeypatch.setenv("STOCK_CACHE_DB_PATH", str(tmp_path / "test.db"))
    board_mod.init_schema()
    yield


def _seed_board(board_code: str, ths_cid: str | None, board_type: str = "concept") -> None:
    conn = board_mod.get_connection()
    with conn:
        conn.execute(
            """INSERT OR REPLACE INTO stock_board
               (code, name, board_type, subtype, source, cid, updated_at)
               VALUES (?,?,?,?,?,?,CURRENT_TIMESTAMP)""",
            (board_code, "测试板块", board_type, "同花顺概念", "ths", ths_cid),
        )


class TestReadRowsUseCanonicalKeys:
    def test_read_boards_from_db_keys(self, fresh_db):
        _seed_board("885333", "300188")
        rows = board_mod._read_boards_from_db("concept", "ths")
        assert rows
        row = rows[0]
        assert row["board_code"] == "885333"
        assert row["ths_cid"] == "300188"
        assert row["board_type"] == "concept"
        assert FORBIDDEN_BARE_CODE not in row, "bare 'code' key must not exist"
        assert "type" not in row, "dual type/board_type return must be gone"
        assert "cid" not in row

    def test_get_board_metadata_keys(self, fresh_db):
        _seed_board("885333", "300188")
        md = board_mod.get_board_metadata("885333", "ths")
        assert md is not None
        assert md["board_code"] == "885333"
        assert md["ths_cid"] == "300188"
        assert md["board_type"] == "concept"
        assert FORBIDDEN_BARE_CODE not in md and "type" not in md and "cid" not in md


class TestMembershipEntriesUseCanonicalKeys:
    def test_entry_keys(self, fresh_db):
        _seed_board("885333", "300188")
        board_mod.upsert_membership_bulk(
            source="ths",
            stocks=[{"stock_code": "600519", "stock_name": "贵州茅台"}],
            board_code="885333",
            board_name="测试板块",
            board_type="concept",
            subtype="同花顺概念",
        )
        entries, _cold, _origin = board_mod.get_stock_memberships("600519", ["ths"])
        assert entries
        entry = entries[0]
        assert entry["board_code"] == "885333"
        assert entry["board_type"] == "concept"
        assert FORBIDDEN_BARE_CODE not in entry and "type" not in entry


class TestFetcherRowsUseCanonicalKeys:
    def test_ths_get_all_boards_row_keys(self):
        """ThsFetcher concept rows: board_code=platecode, ths_cid=cid, board_type."""
        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

        parsed = ThsFetcher._parse_gn_section(
            '<input id="gnSection" value=\'{"1":{"platecode":"886071",'
            '"platename":"AI PC","cid":"309121","199112":-0.84}}\'>'
        )
        assert parsed
        row = parsed[0]
        assert row["board_code"] == "886071"
        assert row["ths_cid"] == "309121"
        assert FORBIDDEN_BARE_CODE not in row
        assert "platecode" not in row

    def test_zzshare_get_all_boards_ths_cid_always_none(self, monkeypatch):
        """spec §4 hard rule 3: zzshare rows must never carry a THS cid."""
        from stock_data.data_provider.fetchers.zzshare_fetcher import ZzshareFetcher

        f = ZzshareFetcher()
        monkeypatch.setattr(
            ZzshareFetcher,
            "_api",
            type(
                "A",
                (),
                {
                    "plates_rank": lambda self, **kw: [
                        {"plate_code": "801001", "plate_name": "芯片", "rate": 1.0}
                    ]
                },
            )(),
        )
        monkeypatch.setattr(f, "_ensure_api", lambda: None)
        rows = f.get_all_boards(board_type="concept")
        assert rows
        assert rows[0]["board_code"] == "801001"
        assert rows[0]["ths_cid"] is None
        assert FORBIDDEN_BARE_CODE not in rows[0]
