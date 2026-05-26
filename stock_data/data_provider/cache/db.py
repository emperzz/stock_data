"""Shared SQLite database path and connection utilities for cache modules."""

import logging
import os
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

_db_path: Path | None = None


def _get_db_path() -> Path:
    """Get database path, lazily evaluated. Respects STOCK_CACHE_DB_PATH env var."""
    global _db_path
    if _db_path is None:
        env_path = os.getenv("STOCK_CACHE_DB_PATH")
        _db_path = Path(env_path) if env_path else Path(__file__).parent.parent.parent / "stock_cache.db"
    return _db_path


def _get_connection() -> sqlite3.Connection:
    """Get a database connection with row factory."""
    conn = sqlite3.connect(_get_db_path(), timeout=30)
    conn.row_factory = sqlite3.Row
    return conn
