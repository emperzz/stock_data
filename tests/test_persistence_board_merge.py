"""Unit tests for THS / ZZSHARE merge helpers in persistence/board.py."""

from __future__ import annotations

import pytest

from stock_data.data_provider.persistence import board as board_mod
from stock_data.data_provider.persistence import db as db_mod


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_mod, "_db_path", None)
    monkeypatch.setattr(db_mod, "_conn", None)
    board_mod._schema_initialized_paths = set()
    monkeypatch.setenv("STOCK_CACHE_DB_PATH", str(tmp_path / "test.db"))
    board_mod.init_schema()
    yield


def _seed_board(
    code: str,
    platecode: str | None,
    name: str,
    board_type: str = "concept",
    source: str = "ths",
) -> None:
    """Insert a row into stock_board directly via the public upsert helper."""
    from datetime import datetime

    conn = board_mod.get_connection()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with conn:
        conn.execute(
            """INSERT OR REPLACE INTO stock_board
               (code, name, board_type, subtype, source, platecode, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                code,
                name,
                board_type,
                "同花顺概念" if board_type == "concept" else "同花顺行业",
                source,
                platecode,
                now,
            ),
        )


class TestResolveThsCidFromPlatecode:
    def test_concept_returns_different_cid(self, fresh_db):
        """Concept: platecode=885642 → cid=301558 (different value)."""
        _seed_board(
            code="301558",
            platecode="885642",
            name="跨境电商",
            board_type="concept",
            source="ths",
        )
        assert board_mod._resolve_ths_cid_from_platecode("885642") == "301558"

    def test_industry_returns_same_as_platecode(self, fresh_db):
        """Industry: platecode=881270 → code=881270 (industry has no separate cid)."""
        _seed_board(
            code="881270",
            platecode="881270",
            name="半导体",
            board_type="industry",
            source="ths",
        )
        assert board_mod._resolve_ths_cid_from_platecode("881270") == "881270"

    def test_unknown_returns_none(self, fresh_db):
        """Unknown platecode → None (caller falls back to zzshare-only)."""
        assert board_mod._resolve_ths_cid_from_platecode("999999") is None

    def test_only_matches_ths_source(self, fresh_db):
        """Platecode row under source='zzshare' must NOT match (we want ths only)."""
        _seed_board(
            code="300000",
            platecode="885000",
            name="x",
            board_type="concept",
            source="zzshare",
        )
        assert board_mod._resolve_ths_cid_from_platecode("885000") is None


class TestMergeThsZzshareByName:
    def test_ths_wins_by_default(self):
        """Same name in both: ths row kept, platecode from ths."""
        ths = [{"code": "301558", "name": "跨境电商", "platecode": "885642",
                "type": "concept", "subtype": "同花顺概念", "source": "ths"}]
        zz = [{"code": "885642", "name": "跨境电商", "platecode": "885642",
               "type": "concept", "subtype": "同花顺概念", "source": "zzshare"}]
        out = board_mod._merge_ths_zzshare_by_name(ths, zz)
        assert len(out) == 1
        assert out[0]["code"] == "301558"  # ths's cid, not zzshare's plate_code
        assert out[0]["platecode"] == "885642"  # ths's platecode
        assert out[0]["source"] == "ths"

    def test_zzshare_backfills_missing_platecode(self):
        """THS row platecode=None, zzshare has same name → platecode backfilled."""
        ths = [{"code": "301558", "name": "跨境电商", "platecode": None,
                "type": "concept", "subtype": "同花顺概念", "source": "ths"}]
        zz = [{"code": "885642", "name": "跨境电商", "platecode": "885642",
               "type": "concept", "subtype": "同花顺概念", "source": "zzshare"}]
        out = board_mod._merge_ths_zzshare_by_name(ths, zz)
        assert len(out) == 1
        assert out[0]["code"] == "301558"
        assert out[0]["platecode"] == "885642"  # ← backfilled

    def test_zzshare_only_rows_appended(self):
        """zzshare has a board ths doesn't → appended at end."""
        ths = [{"code": "301558", "name": "跨境电商", "platecode": "885642",
                "type": "concept", "subtype": "同花顺概念", "source": "ths"}]
        zz = [{"code": "885999", "name": "独此一家", "platecode": "885999",
               "type": "concept", "subtype": "同花顺概念", "source": "zzshare"}]
        out = board_mod._merge_ths_zzshare_by_name(ths, zz)
        codes = [r["code"] for r in out]
        assert "301558" in codes
        assert "885999" in codes  # zzshare-only appended
        assert out[1]["source"] == "ths"  # tagged as ths after merge

    def test_dedup_by_code_and_name(self):
        """Same (code, name) emitted twice → one row."""
        ths = [{"code": "301558", "name": "跨境电商", "platecode": "885642",
                "type": "concept", "subtype": "同花顺概念", "source": "ths"}]
        zz = [{"code": "301558", "name": "跨境电商", "platecode": "885642",
               "type": "concept", "subtype": "同花顺概念", "source": "zzshare"}]
        out = board_mod._merge_ths_zzshare_by_name(ths, zz)
        assert len(out) == 1

    def test_empty_inputs(self):
        assert board_mod._merge_ths_zzshare_by_name([], []) == []
        assert board_mod._merge_ths_zzshare_by_name(
            [], [{"code": "885999", "name": "x", "platecode": "885999",
                  "type": "concept", "subtype": "同花顺概念", "source": "zzshare"}]
        ) == [{"code": "885999", "name": "x", "platecode": "885999",
               "type": "concept", "subtype": "同花顺概念", "source": "ths"}]
        assert board_mod._merge_ths_zzshare_by_name(
            [{"code": "301558", "name": "x", "platecode": "885642",
              "type": "concept", "subtype": "同花顺概念", "source": "ths"}], []
        ) == [{"code": "301558", "name": "x", "platecode": "885642",
               "type": "concept", "subtype": "同花顺概念", "source": "ths"}]
