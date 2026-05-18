"""
SQLite cache for trade calendar.

Provides persistent caching for A-share trade calendar data.
"""

import logging
from datetime import datetime

from .stock_list_cache import _get_connection

logger = logging.getLogger(__name__)


def init_calendar_db() -> None:
    """Initialize the trade calendar table."""
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS trade_calendar (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_date TEXT NOT NULL UNIQUE,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_trade_date ON trade_calendar(trade_date)")
        conn.commit()
        logger.info("[StockCache] Trade calendar table initialized")
    finally:
        conn.close()


def get_cached_calendar() -> list:
    """
    Get all cached trade dates.

    Returns:
        List of trade dates as strings (YYYY-MM-DD), sorted ascending.
    """
    init_calendar_db()

    conn = _get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT trade_date FROM trade_calendar ORDER BY trade_date ASC")
        return [row["trade_date"] for row in cursor.fetchall()]
    finally:
        conn.close()


def update_cached_calendar(dates: list) -> int:
    """
    Update cached trade calendar.

    Args:
        dates: List of trade dates as strings (YYYY-MM-DD)

    Returns:
        Number of dates inserted/updated
    """
    if not dates:
        return 0

    init_calendar_db()

    conn = _get_connection()
    try:
        with conn:
            cursor = conn.cursor()
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            cursor.execute("DELETE FROM trade_calendar")
            cursor.executemany(
                "INSERT INTO trade_calendar (trade_date, updated_at) VALUES (?, ?)",
                [(date, now) for date in dates],
            )

            logger.info(f"[StockCache] Updated {len(dates)} trade calendar dates")
            return len(dates)
    except Exception as e:
        logger.error(f"[StockCache] Calendar update failed: {e}")
        raise
    finally:
        conn.close()


def get_latest_cached_trade_date() -> str | None:
    """
    Get the latest trade date in the cache.

    Returns:
        Latest trade date as string (YYYY-MM-DD), or None if empty.
    """
    init_calendar_db()

    conn = _get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT trade_date FROM trade_calendar ORDER BY trade_date DESC LIMIT 1")
        row = cursor.fetchone()
        return row["trade_date"] if row else None
    finally:
        conn.close()
