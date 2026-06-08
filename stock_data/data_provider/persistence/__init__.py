"""Persistence layer: cross-process SQLite storage for stock metadata.

This package replaces the old `data_provider.cache.*` modules. The naming
change is intentional: `cache` now lives in `api.cache` (in-process
`cachetools.TTLCache`), while `persistence` is the on-disk SQLite store.

Public top-level API (called by server.py lifespan):
- ``init_schema()`` — idempotently create all tables (CREATE IF NOT EXISTS)
- ``reset_all()`` — DROP + recreate all tables; full reset for dev/test

The `STOCK_DB_INIT` env var on server startup decides which one runs.
"""

from . import board, pool_daily, stock_list, trade_calendar
from .db import get_connection, get_db_path

__all__ = [
    "board",
    "pool_daily",
    "stock_list",
    "trade_calendar",
    "get_connection",
    "get_db_path",
    "init_schema",
    "reset_all",
]


# Tables owned by the persistence layer. Used by reset_all() to know what
# to DROP. Listed in dependency-safe order (children before parents) —
# since none of the current tables have FK constraints, this is mostly
# cosmetic, but keeping it explicit makes future FK additions safer.
_TABLES = (
    "stock_board_stock",
    "stock_board",
    "stock_list",
    "trade_calendar",
    "pool_daily",
)


def init_schema() -> None:
    """Idempotently create all tables (CREATE TABLE IF NOT EXISTS). Safe to call on every startup."""
    stock_list.init_schema()
    board.init_schema()
    trade_calendar.init_schema()
    pool_daily.init_schema()


def reset_all() -> None:
    """DROP all persistence tables and recreate from scratch. Full reset for dev/test.

    Notes:
    - On the first run, the SQLite file may not exist; DROP IF EXISTS
      silently no-ops in that case.
    - WAL sidecars (-wal, -shm) are left in place; on the next write the
      WAL will be rebuilt automatically. If you want a perfectly clean
      file, delete the .db (and -wal/-shm) manually after calling this.
    - Old per-table names from the pre-refactor schema
      (zt_pool / dt_pool / zbgc_pool) are NOT dropped here — see plan
      "风险 3" for the rationale.
    """
    conn = get_connection()
    try:
        with conn:
            for table in _TABLES:
                conn.execute(f"DROP TABLE IF EXISTS {table}")
    finally:
        conn.close()
    init_schema()
