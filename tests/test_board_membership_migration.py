"""Tests for stock_board_membership DDL + auto-migration from stock_board_stock."""

from __future__ import annotations

import sqlite3

import pytest

from stock_data.data_provider.persistence import board as board_mod
from stock_data.data_provider.persistence import db as db_mod


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """Point persistence at a fresh temp DB; close existing connection first."""
    monkeypatch.setattr(db_mod, "_db_path", None)
    monkeypatch.setattr(db_mod, "_conn", None)
    monkeypatch.setattr(board_mod, "_schema_initialized_paths", set())
    test_db = tmp_path / "test.db"
    monkeypatch.setenv("STOCK_CACHE_DB_PATH", str(test_db))
    # _db_path was reset; env var will be re-read on next get_db_path() call
    yield test_db


def test_init_schema_creates_membership_table(fresh_db):
    """Cold start: init_schema() creates stock_board_membership + 2 indexes."""
    board_mod.init_schema()
    conn = db_mod.get_connection()
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='stock_board_membership'"
    )
    assert cur.fetchone() is not None
    # Check indexes
    idx_rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='stock_board_membership'"
    ).fetchall()
    idx_names = {r["name"] for r in idx_rows}
    assert "idx_membership_reverse" in idx_names
    assert "idx_membership_forward" in idx_names


def test_init_schema_migrates_from_legacy_stock_board_stock(fresh_db):
    """If stock_board_stock exists, init_schema() migrates rows into membership."""
    # Seed legacy table with 2 rows
    conn = db_mod.get_connection()
    conn.executescript("""
        CREATE TABLE stock_board (
            code TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            board_type TEXT NOT NULL,
            subtype TEXT,
            source TEXT NOT NULL
        );
        INSERT INTO stock_board VALUES
            ('BK1001', '白酒', 'concept', 'concept', 'eastmoney'),
            ('BK1002', '银行', 'industry', 'industry', 'eastmoney');

        CREATE TABLE stock_board_stock (
            board_code TEXT NOT NULL,
            source TEXT NOT NULL,
            stock_code TEXT NOT NULL,
            stock_name TEXT NOT NULL,
            UNIQUE(board_code, source, stock_code)
        );
        INSERT INTO stock_board_stock VALUES
            ('BK1001', 'eastmoney', '600519', '贵州茅台'),
            ('BK1002', 'eastmoney', '601398', '工商银行');
    """)
    conn.commit()
    # Reset schema guard so init_schema() re-runs
    board_mod._schema_initialized_paths.clear()
    board_mod.init_schema()
    # Verify membership has the rows with joined board metadata
    rows = conn.execute(
        "SELECT board_code, stock_code, board_name, board_type FROM stock_board_membership ORDER BY board_code"
    ).fetchall()
    assert len(rows) == 2
    assert rows[0]["board_code"] == "BK1001"
    assert rows[0]["stock_code"] == "600519"
    assert rows[0]["board_name"] == "白酒"
    assert rows[0]["board_type"] == "concept"


def test_init_schema_migration_is_idempotent(fresh_db):
    """Re-running init_schema() with legacy table present must not duplicate rows."""
    conn = db_mod.get_connection()
    conn.executescript("""
        CREATE TABLE stock_board (
            code TEXT PRIMARY KEY, name TEXT NOT NULL,
            board_type TEXT NOT NULL, subtype TEXT, source TEXT NOT NULL
        );
        INSERT INTO stock_board VALUES ('BK1', 'X', 'concept', 'concept', 'eastmoney');
        CREATE TABLE stock_board_stock (
            board_code TEXT, source TEXT, stock_code TEXT, stock_name TEXT
        );
        INSERT INTO stock_board_stock VALUES ('BK1', 'eastmoney', '1', 'A');
    """)
    conn.commit()
    board_mod._schema_initialized_paths.clear()
    board_mod.init_schema()
    board_mod._schema_initialized_paths.clear()  # force re-run
    board_mod.init_schema()
    count = conn.execute("SELECT COUNT(*) FROM stock_board_membership").fetchone()[0]
    assert count == 1  # INSERT OR IGNORE prevented duplicates