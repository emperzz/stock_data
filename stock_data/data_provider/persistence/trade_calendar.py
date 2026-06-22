"""
SQLite persistence for trade calendar.

Provides persistent storage for A-share trade calendar data.

NEW helpers (added during persistence refactor):
- is_trade_date(date_str) — boolean check, used by routes to determine "current trading day"
- get_latest_trade_date_on_or_before(date_str) — used as the default query_date fallback
  when the user does not pass an explicit date and today is not a trade day.
"""

import logging
from datetime import datetime

from .db import get_connection

logger = logging.getLogger(__name__)


def init_schema() -> None:
    """Initialize the trade calendar table."""
    conn = get_connection()
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


def get_cached_calendar() -> tuple[list, str]:
    """
    Get all cached trade dates.

    Returns:
        Tuple of (dates, origin) where ``origin`` is ``"persistence"``
        when the cache has any rows, and ``""`` when the cache is empty.
    """
    init_schema()

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT trade_date FROM trade_calendar ORDER BY trade_date ASC")
    dates = [row["trade_date"] for row in cursor.fetchall()]
    origin = "persistence" if dates else ""
    return dates, origin


def update_cached_calendar(dates: list) -> int:
    """Atomic full-replace of the trade calendar cache.

    Deletes all existing rows, then inserts the provided dates.
    This ensures stale dates (e.g. removed holidays) are cleaned up.

    Args:
        dates: List of trade dates as strings (YYYY-MM-DD)

    Returns:
        Number of dates inserted.
    """
    if not dates:
        return 0

    init_schema()

    conn = get_connection()
    try:
        with conn:
            cursor = conn.cursor()
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            cursor.execute("DELETE FROM trade_calendar")

            cursor.executemany(
                "INSERT INTO trade_calendar "
                "(trade_date, updated_at) VALUES (?, ?)",
                [(date, now) for date in dates],
            )

            logger.info(f"[StockCache] Replaced trade calendar with {len(dates)} dates")
            return len(dates)
    except Exception as e:
        logger.error(f"[StockCache] Calendar update failed: {e}")
        raise


def get_latest_cached_trade_date() -> str | None:
    """
    Get the latest trade date in the cache.

    Returns:
        Latest trade date as string (YYYY-MM-DD), or None if empty.
    """
    init_schema()

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT trade_date FROM trade_calendar ORDER BY trade_date DESC LIMIT 1")
    row = cursor.fetchone()
    return row["trade_date"] if row else None


# ---------------------------------------------------------------------------
# New helpers used by the /pools endpoint to support the
# "current trading day vs historical" routing decision.
# ---------------------------------------------------------------------------

def is_trade_date(date_str: str) -> bool:
    """True iff the given YYYY-MM-DD is in the cached A-share trade calendar.

    Returns False when the table is empty (no calendar data loaded yet).
    """
    init_schema()
    conn = get_connection()
    row = conn.execute(
        "SELECT 1 FROM trade_calendar WHERE trade_date = ? LIMIT 1",
        (date_str,),
    ).fetchone()
    return row is not None


def get_latest_trade_date_on_or_before(date_str: str) -> str | None:
    """Return the most recent cached trade_date <= date_str, or None.

    Used as the default query_date fallback when the user doesn't pass a date
    and today itself is not a trade day (e.g. weekend or holiday).
    """
    init_schema()
    conn = get_connection()
    row = conn.execute(
        "SELECT MAX(trade_date) FROM trade_calendar WHERE trade_date <= ?",
        (date_str,),
    ).fetchone()
    if row is None:
        return None
    return row[0] if row[0] else None

