"""
SQLite persistence for ZT/DT/ZBGC pool data.

Refactored (2026-06): merges the previous zt_pool / dt_pool / zbgc_pool three
tables into a single `pool_daily` table discriminated by `pool_type`. The
"current trading day" routing decision is now made in routes.py and the
manager; this module just provides date-keyed get/save helpers.
"""

import logging
import sqlite3
from datetime import datetime

from .db import get_connection, get_db_path

logger = logging.getLogger(__name__)

# Valid pool_type values
_VALID_POOL_TYPES = ("zt", "dt", "zbgc")


def init_schema() -> None:
    """Initialize the pool_daily table."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pool_daily (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pool_type TEXT NOT NULL,
                pool_date TEXT NOT NULL,
                code TEXT NOT NULL,
                name TEXT NOT NULL,
                price REAL,
                change_pct REAL,
                amount REAL,
                circ_mv REAL,
                total_mv REAL,
                turnover_rate REAL,
                lb_count INTEGER,
                first_seal_time TEXT,
                last_seal_time TEXT,
                seal_amount REAL,
                seal_count INTEGER,
                zt_count TEXT,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(pool_type, pool_date, code)
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_pool_daily_type_date ON pool_daily(pool_type, pool_date)")
        conn.commit()
        logger.info(f"[PoolDaily] Database initialized at {get_db_path()}")
    finally:
        conn.close()


def _validate_pool_type(pool_type: str) -> None:
    if pool_type not in _VALID_POOL_TYPES:
        raise ValueError(
            f"Unknown pool_type: {pool_type!r}, expected one of: {list(_VALID_POOL_TYPES)}"
        )


def get_pool_cached(pool_type: str, date: str) -> list[dict]:
    """
    Get cached pool data for a specific (pool_type, date).

    Args:
        pool_type: 'zt' | 'dt' | 'zbgc'
        date: Pool date in YYYY-MM-DD format

    Returns:
        List of stock dicts with all pool fields (excludes 'id' and 'updated_at').
    """
    _validate_pool_type(pool_type)
    init_schema()

    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM pool_daily WHERE pool_type = ? AND pool_date = ? ORDER BY code",
            (pool_type, date),
        )
        rows = cursor.fetchall()
        return [_row_to_dict(row) for row in rows]
    finally:
        conn.close()


def save_pool(pool_type: str, date: str, stocks: list[dict]) -> int:
    """
    Save pool data to persistence. Upserts (INSERT OR REPLACE) by
    (pool_type, pool_date, code) — same code on the same day is overwritten
    with the latest data, but a different day or different pool_type coexists.

    Args:
        pool_type: 'zt' | 'dt' | 'zbgc'
        date: Pool date in YYYY-MM-DD format
        stocks: List of stock dicts with normalized field names

    Returns:
        Number of stocks saved
    """
    # Validate pool_type BEFORE the empty-stocks short-circuit so callers
    # always see the same input-validation error regardless of payload size.
    _validate_pool_type(pool_type)
    if not stocks:
        return 0
    init_schema()

    conn = get_connection()
    try:
        with conn:
            cursor = conn.cursor()
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # Columns that actually exist in the unified schema. Per stock
            # dict, missing fields are stored as NULL (allowed for seal_count
            # and zt_count, which are not present for dt_pool).
            columns = [
                "pool_type", "pool_date", "code", "name",
                "price", "change_pct", "amount", "circ_mv", "total_mv",
                "turnover_rate", "lb_count",
                "first_seal_time", "last_seal_time", "seal_amount",
                "seal_count", "zt_count",
            ]
            placeholders = ", ".join(["?"] * len(columns))
            insert_sql = f"""
                INSERT OR REPLACE INTO pool_daily
                ({", ".join(columns)}, updated_at)
                VALUES ({placeholders}, ?)
            """

            for stock in stocks:
                values = [pool_type, date, stock.get("code"), stock.get("name")]
                for col in ("price", "change_pct", "amount", "circ_mv", "total_mv",
                            "turnover_rate", "lb_count",
                            "first_seal_time", "last_seal_time", "seal_amount",
                            "seal_count", "zt_count"):
                    values.append(stock.get(col))
                values.append(now)
                cursor.execute(insert_sql, values)

            logger.info(
                f"[PoolDaily] Saved {len(stocks)} stocks to pool_daily "
                f"for pool_type={pool_type} date={date}"
            )
            return len(stocks)
    except Exception as e:
        logger.error(f"[PoolDaily] Save failed: {e}")
        raise
    finally:
        conn.close()


def _row_to_dict(row: sqlite3.Row) -> dict:
    """Convert sqlite3.Row to dict, excluding id and updated_at."""
    result = {}
    for key in row.keys():
        if key not in ("id", "updated_at"):
            result[key] = row[key]
    return result


def get_latest_cached_date(pool_type: str) -> str | None:
    """Get the latest date that has cached data for the given pool_type."""
    _validate_pool_type(pool_type)
    init_schema()

    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT MAX(pool_date) FROM pool_daily WHERE pool_type = ?",
            (pool_type,),
        )
        row = cursor.fetchone()
        return row[0] if row and row[0] else None
    finally:
        conn.close()


def has_cached_data(pool_type: str, date: str) -> bool:
    """Check if there's cached data for the (pool_type, date) pair."""
    _validate_pool_type(pool_type)
    if not get_db_path().exists():
        return False

    init_schema()
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT 1 FROM pool_daily WHERE pool_type = ? AND pool_date = ? LIMIT 1",
            (pool_type, date),
        )
        return cursor.fetchone() is not None
    finally:
        conn.close()


def get_pool_count(pool_type: str, date: str) -> int:
    """Get the number of stocks in the pool for the given (pool_type, date)."""
    _validate_pool_type(pool_type)
    init_schema()
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM pool_daily WHERE pool_type = ? AND pool_date = ?",
            (pool_type, date),
        )
        row = cursor.fetchone()
        return row[0] if row else 0
    finally:
        conn.close()


# Backward-compat aliases for callers still using the old per-table names.
get_zt_pool_cached = get_pool_cached
save_zt_pool = save_pool
