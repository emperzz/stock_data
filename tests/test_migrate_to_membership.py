"""Tests for scripts/migrate_to_membership.py."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from stock_data.data_provider.persistence import board as board_mod
from stock_data.data_provider.persistence import db as db_mod


SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "migrate_to_membership.py"


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_mod, "_db_path", None)
    monkeypatch.setattr(db_mod, "_conn", None)
    monkeypatch.setattr(board_mod, "_schema_initialized_paths", set())
    monkeypatch.setenv("STOCK_CACHE_DB_PATH", str(tmp_path / "test.db"))
    board_mod.init_schema()
    yield tmp_path / "test.db"


def _run_script(db_path: Path, *args: str) -> subprocess.CompletedProcess:
    """Run the migrate script as a subprocess pointed at ``db_path``.

    Inherits the parent's environment so Python can initialize (Windows
    needs e.g. SYSTEMROOT/PATH for hash-randomization). Only
    ``STOCK_CACHE_DB_PATH`` is overridden so the script targets the test DB.
    """
    env = os.environ.copy()
    env["STOCK_CACHE_DB_PATH"] = str(db_path)
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), *args],
        env=env, capture_output=True, text=True,
    )


def test_dry_run_does_not_drop(fresh_db, monkeypatch):
    """--dry-run (default): prints diff, does NOT drop the legacy table."""
    # Seed legacy table with rows already migrated
    conn = db_mod.get_connection()
    conn.execute("""
        INSERT INTO stock_board_stock (board_code, source, stock_code, stock_name)
        VALUES ('BK1', 'eastmoney', 'X', 'X')
    """)
    conn.commit()
    proc = _run_script(fresh_db, "--dry-run")
    assert proc.returncode == 0
    # Legacy table still exists
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='stock_board_stock'"
    ).fetchall()
    assert len(rows) == 1


def test_execute_drops_when_diff_empty(fresh_db):
    """--execute with empty diff: drops legacy table."""
    conn = db_mod.get_connection()
    # Membership has the row, legacy doesn't — diff is empty
    board_mod.upsert_membership_bulk(
        source="eastmoney",
        stocks=[{"stock_code": "X", "stock_name": "X"}],
        board_code="BK1", board_name="B", board_type="concept", subtype="concept",
    )
    proc = _run_script(fresh_db, "--execute")
    assert proc.returncode == 0
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='stock_board_stock'"
    ).fetchall()
    assert len(rows) == 0  # dropped


def test_execute_refuses_when_diff_nonempty(fresh_db):
    """--execute with non-empty diff: refuses, prints message, exit code 2."""
    conn = db_mod.get_connection()
    # Legacy has a row not in membership
    conn.execute("""
        INSERT INTO stock_board_stock (board_code, source, stock_code, stock_name)
        VALUES ('BK_LEGACY_ONLY', 'eastmoney', 'X', 'X')
    """)
    conn.commit()
    proc = _run_script(fresh_db, "--execute")
    assert proc.returncode == 2  # non-zero, not success
    assert "diff" in proc.stdout.lower() or "differ" in proc.stdout.lower()
    # Legacy still exists
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='stock_board_stock'"
    ).fetchall()
    assert len(rows) == 1


def test_force_drops_regardless(fresh_db):
    """--execute --force: drops legacy even with non-empty diff."""
    conn = db_mod.get_connection()
    conn.execute("""
        INSERT INTO stock_board_stock (board_code, source, stock_code, stock_name)
        VALUES ('BK_LEGACY_ONLY', 'eastmoney', 'X', 'X')
    """)
    conn.commit()
    proc = _run_script(fresh_db, "--execute", "--force")
    assert proc.returncode == 0
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='stock_board_stock'"
    ).fetchall()
    assert len(rows) == 0
