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

# board CRUD
from .board import (
    get_board_list,
    get_board_stocks,
    update_cached_board_stocks,
    update_cached_boards,
)
from .db import get_connection, get_db_path

# pool_daily CRUD (unified table replacing cache's 3 tables)
from .pool_daily import (
    get_latest_cached_date,
    get_pool_cached,
    get_pool_count,
    save_pool,
)

# Backward-compat aliases for callers still on the per-table names.
from .pool_daily import get_pool_cached as get_zt_pool_cached
from .pool_daily import save_pool as save_zt_pool
from .stock_list import (
    get_cache_info as get_stock_list_cache_info,
)

# Re-export the CRUD surface (1:1 superset of the old data_provider.cache.api_cache).
# stock_list CRUD
from .stock_list import (
    get_cached_stocks,
    get_stock_list,
    get_stock_name,
    has_cached_data,
    update_cached_stocks,
)
from .stock_list import (
    init_schema as init_stock_list_schema,
)

# trade_calendar CRUD + new helpers
from .trade_calendar import (
    get_cached_calendar,
    get_latest_cached_trade_date,
    get_latest_trade_date_on_or_before,
    is_trade_date,
    update_cached_calendar,
)
from .trade_calendar import (
    init_schema as init_trade_calendar_schema,
)

__all__ = [
    # Submodules
    "board",
    "pool_daily",
    "stock_list",
    "trade_calendar",
    # Db helpers
    "get_connection",
    "get_db_path",
    # Schema management
    "init_schema",
    "init_stock_list_schema",
    "init_trade_calendar_schema",
    "reset_all",
    # Stock-list CRUD
    "get_cached_stocks",
    "get_stock_list",
    "get_stock_name",
    "get_stock_list_cache_info",
    "has_cached_data",
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
    # Pool daily CRUD
    "get_pool_cached",
    "save_pool",
    "get_latest_cached_date",
    "get_pool_count",
    # Backward-compat pool aliases
    "get_zt_pool_cached",
    "save_zt_pool",
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
    with conn:
        for table in _TABLES:
            conn.execute(f"DROP TABLE IF EXISTS {table}")
    init_schema()
