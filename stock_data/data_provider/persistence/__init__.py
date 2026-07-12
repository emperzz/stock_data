"""Persistence layer: cross-process SQLite storage for stock metadata.

This package replaces the old `data_provider.cache.*` modules. The naming
change is intentional: `cache` now lives in `api.cache` (in-process
`cachetools.TTLCache`), while `persistence` is the on-disk SQLite store.

Public top-level API (called by server.py lifespan):
- ``init_schema()`` — idempotently create all tables (CREATE IF NOT EXISTS)
- ``reset_all()`` — DROP + recreate all tables; full reset for dev/test

The `STOCK_DB_INIT` env var on server startup decides which one runs.
"""

from . import board, board_csv, pool_daily, stock_list, trade_calendar

# board CRUD
from .board import (
    get_board_list,
    get_board_stocks,
    update_cached_board_stocks,
    update_cached_boards,
)
from .board_csv import seed_all_from_backup_dir
from .db import get_connection, get_db_path

# pool_daily CRUD (unified table replacing cache's 3 tables)
from .pool_daily import (
    get_latest_cached_date,
    get_pool_cached,
    get_pool_count,
    save_pool,
)

# stock_list CRUD
from .stock_list import (
    get_cached_stocks,
    get_stock_list,
    get_stock_name,
    update_cached_stocks,
)

# trade_calendar CRUD + new helpers
from .trade_calendar import (
    get_cached_calendar,
    get_latest_cached_trade_date,
    get_latest_trade_date_on_or_before,
    is_trade_date,
    update_cached_calendar,
)

__all__ = [
    # Submodules
    "board",
    "board_csv",
    "pool_daily",
    "stock_list",
    "trade_calendar",
    # Db helpers
    "get_connection",
    "get_db_path",
    # Schema management
    "init_schema",
    "reset_all",
    # Stock-list CRUD
    "get_cached_stocks",
    "get_stock_list",
    "get_stock_name",
    "update_cached_stocks",
    # Trade calendar CRUD + helpers
    "get_cached_calendar",
    "get_latest_cached_trade_date",
    "is_trade_date",
    "get_latest_trade_date_on_or_before",
    "update_cached_calendar",
    # Board CRUD
    "get_board_list",
    "get_board_stocks",
    "update_cached_boards",
    "update_cached_board_stocks",
    # Board CSV seed (cold-path bootstrap from on-disk CSV files)
    "seed_all_from_backup_dir",
    # Pool daily CRUD
    "get_pool_cached",
    "save_pool",
    "get_latest_cached_date",
    "get_pool_count",
]

def init_schema() -> None:
    """Idempotently create all tables (CREATE TABLE IF NOT EXISTS). Safe to call on every startup."""
    stock_list.init_schema()
    board.init_schema()
    trade_calendar.init_schema()
    pool_daily.init_schema()


def reset_all() -> None:
    """DROP all persistence tables and recreate from scratch. Full reset for dev/test.

    Scans ``sqlite_master`` to discover every business table at call time
    (excluding SQLite's own ``sqlite_%`` internal tables), so future
    schema additions / renames / removals don't need a code change here.
    Previously a hardcoded ``_TABLES`` tuple was used; that list silently
    went stale when new tables were added (e.g. ``stock_board_membership``
    in 2026-07 — see plan "风险 3" 续).

    Notes:
    - On the first run, the SQLite file may not exist; DROP IF EXISTS
      silently no-ops in that case.
    - WAL sidecars (-wal, -shm) are left in place; on the next write the
      WAL will be rebuilt automatically. If you want a perfectly clean
      file, delete the .db (and -wal/-shm) manually after calling this.
    - Pre-refactor pool tables (zt_pool / dt_pool / zbgc_pool), if still
      present, are also dropped here — they were renamed/merged into
      ``pool_daily`` and any leftover copy is just garbage.
    """
    conn = get_connection()
    with conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        for (name,) in rows:
            conn.execute(f"DROP TABLE IF EXISTS {name}")
    # Clear each submodule's init-schema guard so init_schema() below
    # actually re-runs the DDL (otherwise the dropped tables won't be
    # recreated).
    for submodule in (stock_list, board, trade_calendar, pool_daily):
        submodule._schema_initialized_paths.clear()
    init_schema()
