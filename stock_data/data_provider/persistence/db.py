"""Shared SQLite database path and connection utilities for persistence modules."""

import logging
import os
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

_db_path: Path | None = None
_conn: sqlite3.Connection | None = None


def get_db_path() -> Path:
    """Get database path, lazily evaluated. Respects STOCK_CACHE_DB_PATH env var."""
    global _db_path
    if _db_path is None:
        env_path = os.getenv("STOCK_CACHE_DB_PATH")
        # __file__ = .../data_provider/persistence/db.py
        # parent.parent.parent = <repo>/stock_data/
        _db_path = Path(env_path) if env_path else Path(__file__).parent.parent.parent / "stock_cache.db"
    return _db_path


def get_connection() -> sqlite3.Connection:
    """Get a shared database connection with row factory.

    Returns a module-level singleton connection (check_same_thread=False).
    Callers should NOT call conn.close() — the connection lives for the
    process lifetime.
    """
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(get_db_path(), timeout=30, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
    return _conn

