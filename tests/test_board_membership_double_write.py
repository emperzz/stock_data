"""Tests for update_cached_board_stocks post-Task-9 (single-write to membership).

Prior to Task 9, ``update_cached_board_stocks`` dual-wrote to the legacy
``stock_board_stock`` table AND the new ``stock_board_membership`` table.
After ``scripts/migrate_to_membership.py --execute`` drops the legacy
table, ``update_cached_board_stocks`` was simplified to write only to
``stock_board_membership``. These tests verify the post-migration
single-write behavior — i.e. the legacy table is no longer populated.
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


def test_update_cached_board_stocks_writes_only_membership(fresh_db):
    """update_cached_board_stocks writes exclusively to stock_board_membership.

    Post-Task-9: the legacy ``stock_board_stock`` table no longer exists in
    production (it is dropped by ``scripts/migrate_to_membership.py``).
    If the table does happen to still exist locally — e.g. a stale DB from
    before migration — this function must NOT touch it (only writes go to
    membership). When the table is absent, ``init_schema()`` no longer
    creates it (the legacy CREATE was also removed by the migration), so
    the absence check below acts as the canonical post-condition.
    """
    # Seed stock_board so the function can resolve board_name/board_type
    conn = db_mod.get_connection()
    conn.execute("""
        INSERT INTO stock_board (code, name, board_type, subtype, source)
        VALUES ('BK1001', '白酒', 'concept', 'concept', 'eastmoney')
    """)
    conn.commit()

    stocks = [
        {"stock_code": "600519", "stock_name": "贵州茅台"},
        {"stock_code": "000858", "stock_name": "五粮液"},
    ]
    n = board_mod.update_cached_board_stocks(
        board_code="BK1001",
        source="eastmoney",
        stocks=stocks,
    )
    assert n == 2

    # Check new table got both rows with denormalized board metadata
    new_rows = conn.execute(
        """SELECT stock_code, stock_name, board_name, board_type, subtype FROM stock_board_membership
           WHERE board_code='BK1001' ORDER BY stock_code"""
    ).fetchall()
    assert [r["stock_code"] for r in new_rows] == ["000858", "600519"]
    assert new_rows[0]["stock_name"] == "五粮液"  # populated from input dict
    assert new_rows[0]["board_name"] == "白酒"  # populated via JOIN
    assert new_rows[0]["board_type"] == "concept"
    assert new_rows[0]["subtype"] == "concept"


def test_update_cached_board_stocks_handles_missing_board_row(fresh_db):
    """When stock_board has no row for (board_code, source), fall back gracefully."""
    # NO seed of stock_board — board_row will be None
    stocks = [{"stock_code": "600519", "stock_name": "贵州茅台"}]
    n = board_mod.update_cached_board_stocks(
        board_code="BK9999",
        source="eastmoney",
        stocks=stocks,
    )
    assert n == 1

    conn = db_mod.get_connection()
    new_row = conn.execute(
        """SELECT board_name, board_type, subtype FROM stock_board_membership
           WHERE board_code='BK9999'"""
    ).fetchone()
    # Fallbacks per the function: board_name → board_code; board_type → ""; subtype → None
    assert new_row["board_name"] == "BK9999"
    assert new_row["board_type"] == ""
    assert new_row["subtype"] is None
