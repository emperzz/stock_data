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
from datetime import date, datetime, time

from . import db
from .db import get_connection, get_db_path

logger = logging.getLogger(__name__)

# Valid pool_type values
_VALID_POOL_TYPES = ("zt", "dt", "zbgc")

_schema_initialized_paths: set[str] = set()


def init_schema() -> None:
    """Initialize the pool_daily table.

    Idempotent — DDL is skipped for DB paths we've already initialized
    in this process. ``reset_all()`` clears the set so a full reset
    re-runs the DDL against the current path.
    """
    # Call via `db.get_db_path` (module attribute) rather than the local
    # `from .db import get_db_path` binding, so monkeypatching `db.get_db_path`
    # in tests actually takes effect here.
    path = str(db.get_db_path())
    if path in _schema_initialized_paths:
        return
    _schema_initialized_paths.add(path)
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
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_pool_daily_type_date ON pool_daily(pool_type, pool_date)"
    )
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
                "pool_type",
                "pool_date",
                "code",
                "name",
                "price",
                "change_pct",
                "amount",
                "circ_mv",
                "total_mv",
                "turnover_rate",
                "lb_count",
                "first_seal_time",
                "last_seal_time",
                "seal_amount",
                "seal_count",
                "zt_count",
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
                for col in (
                    "price",
                    "change_pct",
                    "amount",
                    "circ_mv",
                    "total_mv",
                    "turnover_rate",
                    "lb_count",
                    "first_seal_time",
                    "last_seal_time",
                    "seal_amount",
                    "seal_count",
                    "zt_count",
                ):
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
    """True iff ``date_str`` is today AND today is a trade date AND
    the current time is before 16:00 (A 股收盘 15:00 + 1 小时缓冲).

    A "volatile" date is one whose pool data is still mutating (market
    open, 14:57-15:00 集合竞价, etc.). ``get_pool`` skips the cache
    *write* on volatile dates to avoid freezing an incomplete snapshot
    into the SQLite cache. Reads are NOT skipped — a previous
    ``refresh=true`` may have left volatile data in the cache, and
    that data is still meaningful to return (with a warning).

    The 16:00 cutoff means 收盘集合竞价 + 数据稳定窗口之后，
    ``is_volatile_date(today)`` becomes False and today's pool is
    considered stable enough to persist.

    Uses the cached A-share trade calendar to decide whether today is a
    trading day. If the calendar is empty (e.g. very fresh install with
    no warmup), ``is_trade_date`` returns False and the date is treated
    as non-volatile — the caller's path then becomes "read from empty
    SQLite, fetch upstream, persist", which is the safe default.
    """
    from .trade_calendar import is_trade_date

    today = date.today().strftime("%Y-%m-%d")
    if date_str != today:
        return False
    if not is_trade_date(today):
        return False
    # 16:00 = A 股收盘 15:00 + 1 小时缓冲（盘后集合竞价 + 数据稳定）
    return datetime.now().time() < time(16, 0)


def _volatile_warning(date_str: str) -> str:
    """Build the warning text emitted on volatile dates.

    Volatile = today + 交易日 + < 16:00. The data on such a date is
    still mutating (盘中封板/炸板). Any path that returns data for
    a volatile date — fresh fetch, cache hit, or upstream-failure
    fallback — must surface this warning so the caller knows the
    snapshot is not final.
    """
    return (
        f"数据涉及 {date_str}，处于交易时段，涨跌停股池可能仍在变化。"
        f"建议在收盘（16:00 后）重新查询以获取稳定快照。"
    )


def get_pool(
    pool_type: str,
    date: str,
    manager,
    *,
    refresh: bool = False,
) -> tuple[list[dict], str, str | None]:
    """Fetch a ZT/DT/ZBGC pool with the volatile-date policy baked in.

    Args:
        pool_type: "zt" | "dt" | "zbgc"
        date: Pool date in YYYY-MM-DD
        manager: DataFetcherManager — used for the upstream call.
        refresh: Force upstream fetch even when SQLite has the data
            (also forces a write-back even on volatile dates).

    Returns:
        Tuple of ``(stocks, origin, warning)`` where:
          - ``stocks``: list of stock dicts (empty when no data)
          - ``origin``: the fetcher name (e.g. ``"akshare"``) when the
            data was served from the upstream; ``"persistence"`` when
            the data was read from the SQLite cache (cache hit, write-
            back of a fresh fetch, or upstream-failure fallback).
          - ``warning``: non-None iff ``date`` is a volatile date. The
            same warning text applies to all return paths that produce
            data on a volatile date (cache hit / fresh fetch / fallback).

    Raises:
        DataFetchError: When the upstream fails AND there is no
            persisted fallback (the route layer surfaces this as 5xx).

    Notes:
        Volatile-date policy — the read path always tries the cache
        first (a previous ``refresh=true`` may have left volatile data
        in the cache, and that data is still meaningful to return with
        a warning). Only the *write* is skipped on volatile dates,
        unless ``refresh=True`` forces the write-back.
    """
    from ..base import DataFetchError

    _validate_pool_type(pool_type)
    volatile = is_volatile_date(date)
    warning = _volatile_warning(date) if volatile else None

    # Cache-first read (applies to all dates, volatile or not).
    if not refresh:
        cached = get_pool_cached(pool_type, date)
        if cached:
            logger.info(f"[PoolDaily] {pool_type} {date} hit in persistence ({len(cached)} stocks)")
            return cached, "persistence", warning

    # Upstream fetch — wraps the ZT_POOL-capability failover.
    try:
        stocks, fetcher_source = manager.get_zt_pool_raw(pool_type, date)
    except DataFetchError:
        cached = get_pool_cached(pool_type, date)
        if cached:
            logger.warning(
                f"[PoolDaily] Upstream failed for {pool_type} {date}, "
                f"falling back to {len(cached)} persisted stocks"
            )
            return cached, "persistence", warning
        raise

    # Write-back: skip on volatile dates unless the caller forced refresh.
    if stocks and (not volatile or refresh):
        save_pool(pool_type, date, stocks)
    return stocks, fetcher_source, warning


__all__ = [
    "init_schema",
    "is_volatile_date",
    "get_pool",
    "get_pool_cached",
    "save_pool",
    "get_latest_cached_date",
    "get_pool_count",
]
