"""Shared SQLite database path and connection utilities for persistence modules."""

import contextlib
import logging
import os
import sqlite3
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

_db_path: Path | None = None

# One connection per thread. See ``get_connection`` for why a shared
# connection is not an option.
_local = threading.local()


def get_db_path() -> Path:
    """Get database path, lazily evaluated. Respects STOCK_CACHE_DB_PATH env var."""
    global _db_path
    if _db_path is None:
        env_path = os.getenv("STOCK_CACHE_DB_PATH")
        # __file__ = .../data_provider/persistence/db.py
        # parent.parent.parent = <repo>/stock_data/
        _db_path = (
            Path(env_path) if env_path else Path(__file__).parent.parent.parent / "stock_cache.db"
        )
    return _db_path


def _connect(path: str) -> sqlite3.Connection:
    """Open one configured connection. Caller owns it.

    ``check_same_thread`` is left at its default (True) on purpose: the
    connection is handed out per thread, so a cross-thread misuse is a
    bug in the caller — and we want that to raise immediately instead of
    silently corrupting rows the way a shared connection did.
    """
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    # Concurrency hardening (P2-1 of ``docs/optimization-plan-2026-07-16.md``).
    # WAL is a persistent DB-level setting so this is idempotent; the two
    # PRAGMAs below are per-connection and must be re-applied every time.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def get_connection() -> sqlite3.Connection:
    """Get this thread's database connection with row factory.

    **Per-thread, never shared** (P3, 2026-09-14). Each thread gets its
    own connection; calling this twice in the same thread returns the
    same object. Callers should NOT call ``conn.close()`` — the
    connection lives until the thread dies (thread-local storage is
    dropped with the thread, so short-lived workers clean up on their
    own).

    Why not one shared connection (the P2-1 design): a ``sqlite3``
    connection carries a statement cache, and a ``sqlite3.Row`` holds a
    *live* reference to its statement's column-name → index map. Two
    threads calling ``execute()`` on the same connection race on that
    map, so one thread's row can end up describing the other thread's
    statement. That surfaced in production as
    ``IndexError: tuple index out of range`` on a plain
    ``row["board_code"]`` lookup (``persistence/board.py``, the
    ``/stocks/{code}/boards`` route runs in the FastAPI threadpool), and
    it can also silently resolve a column to the wrong value. WAL +
    ``busy_timeout`` (P2-1) do not help: the corruption is in the
    Python-level row bookkeeping, not in SQLite's locking.

    The connection is rebuilt when ``get_db_path()`` changes, so a path
    swap (``STOCK_CACHE_DB_PATH``, test fixtures) takes effect for every
    thread without any explicit reset.
    """
    path = str(get_db_path())
    conn = getattr(_local, "conn", None)
    if conn is not None and getattr(_local, "path", None) != path:
        # Path swapped under us — drop the stale handle rather than serve
        # reads from the previous database. Closing an already-dead handle
        # is not worth propagating.
        with contextlib.suppress(sqlite3.Error):
            conn.close()
        conn = None
    if conn is None:
        conn = _connect(path)
        _local.conn = conn
        _local.path = path
    return conn
