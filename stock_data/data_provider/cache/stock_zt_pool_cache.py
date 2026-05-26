"""
SQLite cache for stock ZT (涨跌停) pool data.

Provides persistent caching for 3 pool types:
- zt_pool: 涨停股池
- dt_pool: 跌停股池
- zbgc_pool: 炸板股池

Each pool type has its own table since they have different fields.
"""

import logging
import os
import sqlite3
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_db_path: Path | None = None


def _get_db_path() -> Path:
    """Get database path, lazily evaluated."""
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


def init_db() -> None:
    """Initialize the database schema for all 3 ZT pool tables."""
    conn = _get_connection()
    try:
        cursor = conn.cursor()

        # 涨停股池表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS zt_pool (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
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
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(pool_date, code)
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_zt_pool_date ON zt_pool(pool_date)")

        # 跌停股池表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS dt_pool (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
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
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(pool_date, code)
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_dt_pool_date ON dt_pool(pool_date)")

        # 炸板股池表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS zbgc_pool (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
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
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(pool_date, code)
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_zbgc_pool_date ON zbgc_pool(pool_date)")

        conn.commit()
        logger.info(f"[ZTCache] Database initialized at {_get_db_path()}")
    finally:
        conn.close()


def _get_table_name(pool_type: str) -> str:
    """Map pool type to table name."""
    mapping = {"zt": "zt_pool", "dt": "dt_pool", "zbgc": "zbgc_pool"}
    if pool_type not in mapping:
        raise ValueError(f"Unknown pool_type: {pool_type!r}, expected one of: {list(mapping.keys())}")
    return mapping[pool_type]


def get_zt_pool_cached(pool_type: str, date: str) -> list[dict]:
    """
    Get cached ZT pool data for a specific date.

    Args:
        pool_type: Pool type - "zt", "dt", or "zbgc"
        date: Pool date in YYYY-MM-DD format

    Returns:
        List of stock dicts with all pool fields
    """
    init_db()
    table = _get_table_name(pool_type)

    conn = _get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            f"SELECT * FROM {table} WHERE pool_date = ? ORDER BY code",
            (date,),
        )
        rows = cursor.fetchall()
        return [_row_to_dict(row) for row in rows]
    finally:
        conn.close()


def save_zt_pool(pool_type: str, date: str, stocks: list[dict]) -> int:
    """
    Save ZT pool data to cache.

    Args:
        pool_type: Pool type - "zt", "dt", or "zbgc"
        date: Pool date in YYYY-MM-DD format
        stocks: List of stock dicts with normalized field names

    Returns:
        Number of stocks saved
    """
    if not stocks:
        return 0

    init_db()
    table = _get_table_name(pool_type)

    conn = _get_connection()
    try:
        with conn:
            cursor = conn.cursor()
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # Build column names based on pool type
            if pool_type == "zt":
                columns = [
                    "pool_date", "code", "name", "price", "change_pct", "amount",
                    "circ_mv", "total_mv", "turnover_rate", "lb_count",
                    "first_seal_time", "last_seal_time", "seal_amount", "seal_count", "zt_count"
                ]
            elif pool_type == "dt":
                columns = [
                    "pool_date", "code", "name", "price", "change_pct", "amount",
                    "circ_mv", "total_mv", "turnover_rate", "lb_count",
                    "first_seal_time", "last_seal_time", "seal_amount"
                ]
            else:  # zbgc
                columns = [
                    "pool_date", "code", "name", "price", "change_pct", "amount",
                    "circ_mv", "total_mv", "turnover_rate", "lb_count",
                    "first_seal_time", "last_seal_time", "seal_amount", "seal_count", "zt_count"
                ]

            placeholders = ", ".join(["?"] * (len(columns) + 1))  # +1 for created_at
            insert_sql = f"""
                INSERT OR REPLACE INTO {table}
                ({", ".join(columns)}, created_at)
                VALUES ({placeholders})
            """

            for stock in stocks:
                values = [date]
                for col in columns:
                    if col == "pool_date":
                        continue
                    values.append(stock.get(col))
                values.append(now)
                cursor.execute(insert_sql, values)

            logger.info(f"[ZTCache] Saved {len(stocks)} stocks to {table} for date={date}")
            return len(stocks)
    except Exception as e:
        logger.error(f"[ZTCache] Save failed: {e}")
        raise
    finally:
        conn.close()


def _row_to_dict(row: sqlite3.Row) -> dict:
    """Convert sqlite3.Row to dict, excluding id and created_at."""
    result = {}
    for key in row.keys():
        if key not in ("id", "created_at"):
            result[key] = row[key]
    return result


def get_latest_cached_date(pool_type: str) -> str | None:
    """Get the latest date that has cached data for the pool type."""
    init_db()
    table = _get_table_name(pool_type)

    conn = _get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(f"SELECT MAX(pool_date) FROM {table}")
        row = cursor.fetchone()
        return row[0] if row and row[0] else None
    finally:
        conn.close()


def has_cached_data(pool_type: str, date: str) -> bool:
    """Check if there's cached data for the pool type and date."""
    if not _get_db_path().exists():
        return False

    init_db()
    table = _get_table_name(pool_type)

    conn = _get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(f"SELECT 1 FROM {table} WHERE pool_date = ? LIMIT 1", (date,))
        return cursor.fetchone() is not None
    finally:
        conn.close()


def get_pool_count(pool_type: str, date: str) -> int:
    """Get the number of stocks in the pool for the given date."""
    init_db()
    table = _get_table_name(pool_type)

    conn = _get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(f"SELECT COUNT(*) FROM {table} WHERE pool_date = ?", (date,))
        row = cursor.fetchone()
        return row[0] if row else 0
    finally:
        conn.close()