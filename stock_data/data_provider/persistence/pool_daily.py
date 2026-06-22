"""
SQLite persistence for ZT/DT/ZBGC pool data.

Refactored (2026-06): merges the previous zt_pool / dt_pool / zbgc_pool three
tables into a single `pool_daily` table discriminated by `pool_type`. The
"current trading day" routing decision is now centralised in
``get_pool()`` below — this module is the single source of truth for
the volatile/historical date policy. The route layer no longer needs
to compute ``is_current_day`` and pass it down.
"""

import logging
import sqlite3
from datetime import date, datetime

from .db import get_connection, get_db_path

logger = logging.getLogger(__name__)

# Valid pool_type values
_VALID_POOL_TYPES = ("zt", "dt", "zbgc")


def init_schema() -> None:
    """Initialize the pool_daily table."""
    conn = get_connection()
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
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM pool_daily WHERE pool_type = ? AND pool_date = ? ORDER BY code",
        (pool_type, date),
    )
    rows = cursor.fetchall()
    return [_row_to_dict(row) for row in rows]


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

            # Delete stale rows for this (pool_type, date) before inserting fresh data
            cursor.execute(
                "DELETE FROM pool_daily WHERE pool_type = ? AND pool_date = ?",
                (pool_type, date),
            )

            data_rows = []
            for stock in stocks:
                values = [pool_type, date, stock.get("code"), stock.get("name")]
                for col in ("price", "change_pct", "amount", "circ_mv", "total_mv",
                            "turnover_rate", "lb_count",
                            "first_seal_time", "last_seal_time", "seal_amount",
                            "seal_count", "zt_count"):
                    values.append(stock.get(col))
                values.append(now)
                data_rows.append(values)
            cursor.executemany(insert_sql, data_rows)

            logger.info(
                f"[PoolDaily] Saved {len(stocks)} stocks to pool_daily "
                f"for pool_type={pool_type} date={date}"
            )
            return len(stocks)
    except Exception as e:
        logger.error(f"[PoolDaily] Save failed: {e}")
        raise


def _row_to_dict(row: sqlite3.Row) -> dict:
    """Convert sqlite3.Row to dict, excluding id and updated_at."""
    result = {}
    for key in row.keys():  # noqa: SIM118 — sqlite3.Row iterates values, not keys
        if key not in ("id", "updated_at"):
            result[key] = row[key]
    return result


def get_latest_cached_date(pool_type: str) -> str | None:
    """Get the latest date that has cached data for the given pool_type."""
    _validate_pool_type(pool_type)
    init_schema()

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT MAX(pool_date) FROM pool_daily WHERE pool_type = ?",
        (pool_type,),
    )
    row = cursor.fetchone()
    return row[0] if row and row[0] else None


def has_cached_data(pool_type: str, date: str) -> bool:
    """Check if there's cached data for the (pool_type, date) pair."""
    _validate_pool_type(pool_type)
    if not get_db_path().exists():
        return False

    init_schema()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT 1 FROM pool_daily WHERE pool_type = ? AND pool_date = ? LIMIT 1",
        (pool_type, date),
    )
    return cursor.fetchone() is not None


def get_pool_count(pool_type: str, date: str) -> int:
    """Get the number of stocks in the pool for the given (pool_type, date)."""
    _validate_pool_type(pool_type)
    init_schema()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT COUNT(*) FROM pool_daily WHERE pool_type = ? AND pool_date = ?",
        (pool_type, date),
    )
    row = cursor.fetchone()
    return row[0] if row else 0


# Backward-compat aliases for callers still using the old per-table names.
get_zt_pool_cached = get_pool_cached
save_zt_pool = save_pool


# ---------------------------------------------------------------------------
# Date-aware fetch policy (single source of truth)
# ---------------------------------------------------------------------------
# The previous design pushed the "is this a current trading day?" decision
# up to the route layer, which then passed ``is_current_day`` down to
# the manager as a boolean parameter. The manager used that flag to
# control four separate behaviours (read cache? write cache? fallback to
# cache on failure? document the behaviour?). All of those branches are
# derivable from the date itself + the trade calendar, so they belong
# here next to the storage layer — not in the orchestrator or the
# HTTP layer.

def is_volatile_date(date_str: str) -> bool:
    """True iff ``date_str`` is today AND today is a trade date.

    A "volatile" date is one whose pool data is still mutating (market
    open, partial seal counts, etc.). Persisting it to SQLite would
    freeze an incomplete snapshot, so we skip both reads and writes.

    Uses the cached A-share trade calendar to decide whether today is a
    trading day. If the calendar is empty (e.g. very fresh install with
    no warmup), ``is_trade_date`` returns False and the date is treated
    as non-volatile — the caller's path then becomes "read from empty
    SQLite, fetch upstream, persist", which is the safe default.
    """
    from .trade_calendar import is_trade_date

    today = date.today().strftime("%Y-%m-%d")
    return date_str == today and is_trade_date(today)


def get_pool(
    pool_type: str,
    date: str,
    manager,
    *,
    refresh: bool = False,
) -> tuple[list[dict], str]:
    """Fetch a ZT/DT/ZBGC pool with the volatile-date policy baked in.

    Args:
        pool_type: "zt" | "dt" | "zbgc"
        date: Pool date in YYYY-MM-DD
        manager: DataFetcherManager — used for the upstream call.
        refresh: Force upstream fetch even when SQLite has the data
            (only meaningful for historical dates; for volatile dates
            we always go upstream anyway).

    Returns:
        Tuple of ``(stocks, origin)`` where ``origin`` is:
          - the fetcher name (e.g. ``"akshare"``) when the data was
            served from the upstream,
          - ``"persistence"`` when the data was read from the SQLite
            cache (either the primary historical hit, the write-back
            of a fresh fetch, or the fallback after upstream failure).

    Raises:
        DataFetchError: When the upstream fails AND there is no
            persisted fallback (i.e. the volatile-date path always
            raises on upstream failure by design).
    """
    from ..base import DataFetchError

    _validate_pool_type(pool_type)

    if is_volatile_date(date):
        # Volatile: pure upstream pass-through. Never read or write SQLite.
        # On failure, raise — the route layer is responsible for
        # surfacing a clear 5xx to the caller.
        return manager.get_zt_pool_raw(pool_type, date)

    # Historical: SQLite-first, upstream on miss, write-back on success.
    # On upstream failure, fall back to whatever SQLite has.
    if not refresh:
        cached = get_pool_cached(pool_type, date)
        if cached:
            logger.info(
                f"[PoolDaily] {pool_type} {date} hit in persistence "
                f"({len(cached)} stocks)"
            )
            return cached, "persistence"

    try:
        stocks, fetcher_source = manager.get_zt_pool_raw(pool_type, date)
    except DataFetchError:
        cached = get_pool_cached(pool_type, date)
        if cached:
            logger.warning(
                f"[PoolDaily] Upstream failed for {pool_type} {date}, "
                f"falling back to {len(cached)} persisted stocks"
            )
            return cached, "persistence"
        raise

    if stocks:
        save_pool(pool_type, date, stocks)
    return stocks, fetcher_source


__all__ = [
    "init_schema",
    "is_volatile_date",
    "get_pool",
    "get_pool_cached",
    "save_pool",
    "get_latest_cached_date",
    "has_cached_data",
    "get_pool_count",
    # Backward-compat
    "get_zt_pool_cached",
    "save_zt_pool",
]
