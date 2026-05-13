"""
SQLite cache for stock lists.

Provides persistent caching for stock listing data to avoid repeated
upstream API calls which are slow and may fail.
"""

import logging
import sqlite3
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# Database file location
_DB_PATH = Path(__file__).parent.parent / "stock_cache.db"


def _get_connection() -> sqlite3.Connection:
    """Get a database connection with row factory."""
    conn = sqlite3.connect(_DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Initialize the database schema."""
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS stock_list (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                market TEXT NOT NULL,
                code TEXT NOT NULL,
                name TEXT NOT NULL,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(market, code)
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_market ON stock_list(market)
        """)
        conn.commit()
        logger.info(f"[StockCache] Database initialized at {_DB_PATH}")
    finally:
        conn.close()


def get_cached_stocks(market: str) -> list:
    """
    Get cached stocks for a market.

    Args:
        market: Market type (cn/hk/us)

    Returns:
        List of dicts: [{"code": "600519", "name": "贵州茅台"}, ...]
    """
    if not _DB_PATH.exists():
        return []

    conn = _get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT code, name, updated_at FROM stock_list WHERE market = ? ORDER BY code",
            (market,),
        )
        rows = cursor.fetchall()
        return [
            {"code": row["code"], "name": row["name"], "updated_at": row["updated_at"]}
            for row in rows
        ]
    finally:
        conn.close()


def update_cached_stocks(market: str, stocks: list) -> int:
    """
    Update cached stocks for a market.

    Args:
        market: Market type (cn/hk/us)
        stocks: List of dicts [{"code": "600519", "name": "贵州茅台"}, ...]

    Returns:
        Number of stocks inserted/updated
    """
    if not stocks:
        return 0

    init_db()  # Ensure table exists

    conn = _get_connection()
    try:
        cursor = conn.cursor()
        # Use INSERT OR REPLACE to handle duplicates
        cursor.execute("BEGIN TRANSACTION")
        cursor.execute("DELETE FROM stock_list WHERE market = ?", (market,))
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for stock in stocks:
            cursor.execute(
                "INSERT INTO stock_list (market, code, name, updated_at) VALUES (?, ?, ?, ?)",
                (market, stock["code"], stock["name"], now),
            )
        cursor.execute("COMMIT")
        logger.info(f"[StockCache] Updated {len(stocks)} stocks for market={market}")
        return len(stocks)
    except Exception as e:
        cursor.execute("ROLLBACK")
        logger.error(f"[StockCache] Update failed: {e}")
        raise
    finally:
        conn.close()


def has_cached_data(market: str) -> bool:
    """Check if there's cached data for a market."""
    if not _DB_PATH.exists():
        return False

    conn = _get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM stock_list WHERE market = ? LIMIT 1", (market,))
        return cursor.fetchone() is not None
    finally:
        conn.close()


def get_cache_info() -> dict:
    """Get cache statistics."""
    if not _DB_PATH.exists():
        return {"total_stocks": 0, "markets": {}}

    conn = _get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT market, COUNT(*) as cnt FROM stock_list GROUP BY market")
        rows = cursor.fetchall()
        result = {"total_stocks": 0, "markets": {}}
        for row in rows:
            result["markets"][row["market"]] = row["cnt"]
            result["total_stocks"] += row["cnt"]
        return result
    finally:
        conn.close()
