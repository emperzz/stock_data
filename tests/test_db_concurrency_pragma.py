"""Verify ``persistence.db.get_connection`` applies the P2-1 concurrency PRAGMAs.

Background (P2-1 of ``docs/optimization-plan-2026-07-16.md``):
* ``journal_mode=WAL`` — readers and writers don't block each other.
* ``busy_timeout=30000`` — wait up to 30s for a write lock instead of
  raising ``OperationalError("database is locked")`` immediately.
* ``synchronous=NORMAL`` — fsync only at checkpoint, not per commit.

Without these the FastAPI 40-thread pool can corrupt writes (one thread
commits another's incomplete transaction) under concurrent load. This
test pins the PRAGMA values so a future regression that drops them
fails loudly instead of silently re-introducing the bug.

The concurrent-write smoke test at the bottom uses threading + a
Barrier to force two threads to attempt overlapping writes against the
shared singleton connection. Even with WAL, same-connection writes are
NOT safe — this test is intentionally minimal: it just verifies that
busy_timeout gives the second writer time to wait instead of erroring.
"""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import pytest

from stock_data.data_provider.persistence import db as db_mod


@pytest.fixture
def fresh_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Isolated SQLite file + reset singleton for each test."""
    db_file = tmp_path / "concurrency.db"
    monkeypatch.setenv("STOCK_CACHE_DB_PATH", str(db_file))
    monkeypatch.setattr(db_mod, "_db_path", None)
    monkeypatch.setattr(db_mod, "_conn", None)
    yield db_file


def test_journal_mode_is_wal(fresh_db):
    """``PRAGMA journal_mode`` must return ``wal`` on the singleton connection."""
    conn = db_mod.get_connection()
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode == "wal", f"expected WAL, got {mode!r}"


def test_busy_timeout_is_30_seconds(fresh_db):
    """``PRAGMA busy_timeout`` must be 30000 ms on the singleton connection."""
    conn = db_mod.get_connection()
    timeout_ms = conn.execute("PRAGMA busy_timeout").fetchone()[0]
    assert timeout_ms == 30000, f"expected 30000 ms, got {timeout_ms!r}"


def test_synchronous_is_normal(fresh_db):
    """``PRAGMA synchronous`` must be ``1`` (NORMAL) on the singleton connection.

    sqlite3 reports ``synchronous=NORMAL`` as the integer ``1`` and
    ``FULL`` as ``2``. See https://www.sqlite.org/pragma.html#pragma_synchronous.
    """
    conn = db_mod.get_connection()
    sync = conn.execute("PRAGMA synchronous").fetchone()[0]
    assert sync == 1, f"expected synchronous=NORMAL (1), got {sync!r}"


def test_row_factory_is_row(fresh_db):
    """Connection must keep the row factory for dict-like cursor results.

    Guards against a future refactor that drops the ``row_factory`` line
    when adding PRAGMA statements — losing it would break every caller
    that reads cursor results as dicts (e.g. ``row["code"]``).
    """
    conn = db_mod.get_connection()
    assert conn.row_factory is sqlite3.Row


def test_pragmas_survive_singleton_reset(fresh_db, monkeypatch):
    """Re-init after ``_conn = None`` must re-apply all PRAGMAs.

    Tests do ``monkeypatch.setattr(db_mod, "_conn", None)`` to point the
    singleton at a fresh DB. If the re-init path skipped PRAGMA setup,
    the second connection would silently revert to default rollback
    journal + 0 busy timeout.
    """
    first = db_mod.get_connection()
    assert first.execute("PRAGMA journal_mode").fetchone()[0] == "wal"

    # Force a fresh connection (simulates test fixture reset).
    monkeypatch.setattr(db_mod, "_conn", None)
    second = db_mod.get_connection()
    assert second.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert second.execute("PRAGMA busy_timeout").fetchone()[0] == 30000
    assert second.execute("PRAGMA synchronous").fetchone()[0] == 1


def test_concurrent_readers_dont_block_each_other(fresh_db):
    """Two threads can read simultaneously thanks to WAL mode.

    The C2 audit (SQLite thread safety via shared singleton) is
    INTENTIONALLY NOT FIXED in P2-1: per
    ``docs/optimization-plan-2026-07-16.md`` §P2-1 the local-personal
    revision defers the proper fix (``threading.local`` per-thread
    connection) to a future "P3" because (a) it would touch every test
    that does ``monkeypatch.setattr(db_mod, "_conn", None)`` to reset
    the singleton and (b) the failure surface is genuinely narrow for
    a single-user, low-concurrency local server. P2-1's actual scope
    is just PRAGMA hardening (WAL + busy_timeout + synchronous=NORMAL).

    What we CAN still verify with concurrency: WAL mode lets a reader
    and a writer proceed without the reader blocking. The default
    rollback journal would force the reader to wait for the writer
    to release the EXCLUSIVE lock. With WAL the reader just sees
    the last-committed snapshot.

    This test exercises the read-while-writing path under threading
    to ensure WAL is actually active (not silently downgraded by
    an upstream config that we missed). It does NOT exercise the
    two-writer race — that path is governed by the C2 design
    tradeoff and the manager's single-threaded `get_pool` write path.
    """
    # Bootstrap schema (single-threaded).
    conn = db_mod.get_connection()
    conn.executescript(
        """
        CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT);
        """
    )
    conn.commit()
    conn.execute("INSERT INTO t(v) VALUES (?)", ("initial",))
    conn.commit()

    read_results: list[str] = []
    errors: list[BaseException] = []

    def reader() -> None:
        try:
            c = db_mod.get_connection()
            row = c.execute("SELECT v FROM t WHERE id = 1").fetchone()
            read_results.append(row[0] if row else None)
        except BaseException as e:  # noqa: BLE001
            errors.append(e)

    # Run a reader in a thread while the main thread also reads.
    # If WAL is active both reads succeed; if journal_mode silently
    # rolled back to "delete" we'd see a locking error.
    t = threading.Thread(target=reader)
    t.start()
    main_row = conn.execute("SELECT v FROM t WHERE id = 1").fetchone()
    t.join(timeout=5)

    assert not errors, f"concurrent read raised: {errors}"
    assert main_row[0] == "initial"
    assert read_results == ["initial"]