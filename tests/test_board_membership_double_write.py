"""Tests for dual-write in update_cached_board_stocks."""

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


def test_update_cached_board_stocks_writes_both_tables(fresh_db):
    """update_cached_board_stocks must insert into stock_board_stock AND stock_board_membership."""
    # Seed stock_board so dual-write can join board_name/board_type
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

    # Check legacy table
    legacy = conn.execute(
        "SELECT stock_code FROM stock_board_stock WHERE board_code='BK1001' ORDER BY stock_code"
    ).fetchall()
    assert [r["stock_code"] for r in legacy] == ["000858", "600519"]

    # Check new table
    new_rows = conn.execute(
        """SELECT stock_code, stock_name, board_name, board_type, subtype FROM stock_board_membership
           WHERE board_code='BK1001' ORDER BY stock_code"""
    ).fetchall()
    assert len(new_rows) == 2
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
