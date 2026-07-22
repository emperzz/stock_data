"""Tests for stale-member purge semantics in board cache writers.

Both ``update_cached_board_stocks`` and ``upsert_membership_bulk`` claim to
"upsert all stocks for one board". Under the previous INSERT OR REPLACE
behaviour, a stock that left the board upstream was never deleted — old
rows accumulated forever, so ``/boards/{code}/stocks`` returned ghost
members weeks after they had rotated out.

The fix is a DELETE-by-(board_code, source) immediately before the
INSERT OR REPLACE, inside the same ``with conn:`` transaction so the
two operations are atomic. All four tests here exercise that path.
"""

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
    yield tmp_path / "test.db"


def _seed_stock_board(board_code: str, name: str, board_type: str = "concept") -> None:
    conn = db_mod.get_connection()
    conn.execute(
        """INSERT INTO stock_board (code, name, board_type, subtype, source)
           VALUES (?, ?, ?, ?, 'ths')""",
        (board_code, name, board_type, board_type),
    )
    conn.commit()


def _member_codes(board_code: str, source: str = "ths") -> list[str]:
    conn = db_mod.get_connection()
    rows = conn.execute(
        """SELECT stock_code FROM stock_board_membership
           WHERE board_code=? AND source=?
           ORDER BY stock_code""",
        (board_code, source),
    ).fetchall()
    return [r["stock_code"] for r in rows]


# ---------- update_cached_board_stocks ----------


def test_update_purges_members_that_left_board(fresh_db):
    """Stock A leaves, stock D joins, B stays → only B and D remain."""
    _seed_stock_board("BK1001", "白酒")

    # Initial snapshot: A, B, C
    board_mod.update_cached_board_stocks(
        board_code="BK1001",
        source="ths",
        stocks=[
            {"stock_code": "600519", "stock_name": "A"},
            {"stock_code": "000858", "stock_name": "B"},
            {"stock_code": "000001", "stock_name": "C"},
        ],
    )
    assert _member_codes("BK1001") == ["000001", "000858", "600519"]

    # Refreshed snapshot: B stays, A leaves, D joins
    board_mod.update_cached_board_stocks(
        board_code="BK1001",
        source="ths",
        stocks=[
            {"stock_code": "000858", "stock_name": "B"},
            {"stock_code": "600000", "stock_name": "D"},
        ],
    )
    assert _member_codes("BK1001") == ["000858", "600000"], (
        "Stale member 600519 (A) and 000001 (C) must be purged; "
        "new member 600000 (D) must be inserted."
    )


def test_update_purge_does_not_touch_other_boards(fresh_db):
    """DELETE is scoped by (board_code, source) — must not affect other boards."""
    _seed_stock_board("BK1001", "白酒")
    _seed_stock_board("BK1002", "新能源")

    board_mod.update_cached_board_stocks(
        "BK1001",
        "ths",
        [{"stock_code": "600519", "stock_name": "A"}],
    )
    board_mod.update_cached_board_stocks(
        "BK1002",
        "ths",
        [{"stock_code": "000858", "stock_name": "B"}],
    )

    # Refresh BK1001 — BK1002's row must survive.
    board_mod.update_cached_board_stocks(
        "BK1001",
        "ths",
        [{"stock_code": "600000", "stock_name": "C"}],
    )

    assert _member_codes("BK1001") == ["600000"]
    assert _member_codes("BK1002") == ["000858"]


def test_update_purge_does_not_touch_other_sources(fresh_db):
    """Same board_code under a different source must NOT be deleted.

    Defence-in-depth: today every call site writes ``source='ths'``
    regardless of upstream origin (per CLAUDE.md §"Board Cache
    Source-Normalization"), so this branch should not be reachable.
    The test pins the contract so future per-source isolation doesn't
    regress.
    """
    _seed_stock_board("BK1001", "白酒")

    board_mod.update_cached_board_stocks(
        "BK1001",
        "ths",
        [{"stock_code": "600519", "stock_name": "A"}],
    )
    board_mod.update_cached_board_stocks(
        "BK1001",
        "eastmoney",
        [{"stock_code": "000858", "stock_name": "B"}],
    )

    # Refresh ths row — eastmoney row must survive.
    board_mod.update_cached_board_stocks(
        "BK1001",
        "ths",
        [{"stock_code": "600000", "stock_name": "C"}],
    )

    assert _member_codes("BK1001", "ths") == ["600000"]
    assert _member_codes("BK1001", "eastmoney") == ["000858"]


# ---------- upsert_membership_bulk ----------


def test_upsert_bulk_purges_members_that_left_board(fresh_db):
    """Same purge semantics on the bulk path used by backfill tools."""
    _seed_stock_board("BK1001", "白酒")

    # Initial: A, B
    board_mod.upsert_membership_bulk(
        source="ths",
        stocks=[
            {"stock_code": "600519", "stock_name": "A"},
            {"stock_code": "000858", "stock_name": "B"},
        ],
        board_code="BK1001",
        board_name="白酒",
        board_type="concept",
        subtype="concept",
    )
    assert _member_codes("BK1001") == ["000858", "600519"]

    # Refresh: only B and D
    board_mod.upsert_membership_bulk(
        source="ths",
        stocks=[
            {"stock_code": "000858", "stock_name": "B"},
            {"stock_code": "600000", "stock_name": "D"},
        ],
        board_code="BK1001",
        board_name="白酒",
        board_type="concept",
        subtype="concept",
    )
    assert _member_codes("BK1001") == ["000858", "600000"]
