"""
SQLite persistence for stock board (concept/industry) data.

Provides persistent storage for board listing data to avoid repeated
upstream API calls which are slow and may fail.
"""

import logging
from datetime import datetime

from . import db
from ._refresh import DailyRefreshTracker
from .db import get_connection, get_db_path

logger = logging.getLogger(__name__)

_refresh_tracker = DailyRefreshTracker()
_schema_initialized_paths: set[str] = set()


def init_schema() -> None:
    """Initialize the database schema for stock boards.

    Idempotent — DDL is skipped for DB paths we've already initialized
    in this process. Tests that swap the DB path via ``db.get_db_path``
    therefore trigger a fresh init against the new path (rather than
    hitting ``no such table: stock_board``). ``reset_all()`` clears the
    set so a full reset re-runs the DDL against the current path.
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
    # Board list table — metadata only; realtime quotes come from API
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS stock_board (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL,
            name TEXT NOT NULL,
            board_type TEXT NOT NULL,
            source TEXT NOT NULL,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(code, source)
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_stock_board_type ON stock_board(board_type)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_stock_board_source ON stock_board(source)
    """)
    # Board-stock relation table — metadata only; realtime quotes come from API
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS stock_board_stock (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            board_code TEXT NOT NULL,
            source TEXT NOT NULL,
            stock_code TEXT NOT NULL,
            stock_name TEXT NOT NULL,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(board_code, source, stock_code)
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_stock_board_stock_board ON stock_board_stock(board_code, source)
    """)
    conn.commit()
    logger.info(f"[BoardCache] Database initialized at {get_db_path()}")


def get_board_list(board_type: str, source: str, refresh: bool = False, include_quote: bool = False, manager=None) -> tuple[list, str]:
    """
    Get board list with automatic refresh.

    - No local cache -> fetch from upstream and cache
    - First call of the day -> force refresh
    - refresh=True -> force refresh
    - include_quote=True -> always fetch fresh data from upstream
    - Otherwise -> return cached data

    Args:
        board_type: "concept" or "industry"
        source: Data source (e.g., "eastmoney")
        refresh: If True, force refresh from upstream
        include_quote: If True, include realtime price/change/market data and skip cache
        manager: DataFetcherManager instance. Required for fetching from upstream.

    Returns:
        Tuple of (boards, origin) where origin is:
          - the fetcher name (e.g. "akshare") when the data was freshly fetched
          - "persistence" when the data was read from the SQLite cache
        List of board dicts: [{"code": "BK1048", "name": "互联网服务", "board_type": "concept", "source": "eastmoney"}, ...]
            May include quote fields when include_quote=True.
    """
    init_schema()

    needs_refresh = refresh or include_quote or _refresh_tracker.is_first_call(f"{board_type}:{source}")

    if not needs_refresh:
        cached = _read_boards_from_db(board_type, source)
        if cached:
            return cached, "persistence"

    # Need refresh: fetch from upstream and update cache
    if manager is None:
        raise ValueError("manager is required when refresh=True or cache miss")

    # Fetch based on board_type
    if board_type == "concept":
        boards, fetcher_source = manager.get_all_concept_boards(source=source, include_quote=include_quote)
    elif board_type == "industry":
        boards, fetcher_source = manager.get_all_industry_boards(source=source, include_quote=include_quote)
    else:
        boards, fetcher_source = [], ""

    if boards:
        # Always cache the base board data (without quote if include_quote=False)
        update_cached_boards(board_type, source, boards)
        logger.info(f"[BoardCache] Refreshed {len(boards)} boards for {board_type}/{source}")

    return boards, fetcher_source


def get_board_stocks(
    board_code: str,
    source: str,
    refresh: bool = False,
    include_quote: bool = False,
    manager=None,
) -> tuple[list, str]:
    """
    Get stocks belonging to a board with automatic refresh.

    Args:
        board_code: Board code (e.g., "BK1048")
        source: Data source (e.g., "eastmoney")
        refresh: If True, force refresh from upstream
        include_quote: If True, always fetch fresh realtime data from upstream
        manager: DataFetcherManager instance. Required for fetching from upstream.

    Returns:
        Tuple of (stocks, origin) where origin is:
          - the fetcher name (e.g. "akshare") when the data was freshly fetched
          - "persistence" when the data was read from the SQLite cache
        List of stock dicts: [{"stock_code": "600519", "stock_name": "贵州茅台"}, ...]
            May include quote fields when include_quote=True.
    """
    init_schema()

    # include_quote=True means always fetch fresh data, skip cache
    needs_refresh = include_quote or refresh or _refresh_tracker.is_first_call(f"{board_code}:{source}")

    if not needs_refresh:
        cached = _read_board_stocks_from_db(board_code, source)
        if cached:
            return cached, "persistence"

    # Need refresh: fetch from upstream and update cache
    if manager is None:
        raise ValueError("manager is required when refresh=True or cache miss")

    board_type = _get_board_type(board_code, source, manager)
    if board_type is None:
        # Cache miss: try concept first, fall back to industry.
        # Both board types use "BK" prefix on EastMoney so code alone can't distinguish them.
        stocks, fetcher_source = manager.get_concept_board_stocks(board_code, source=source, include_quote=include_quote)
        if not stocks:
            stocks, fetcher_source = manager.get_industry_board_stocks(board_code, source=source, include_quote=include_quote)
        if stocks:
            update_cached_board_stocks(board_code, source, stocks)
        return stocks, fetcher_source

    if board_type == "concept":
        stocks, fetcher_source = manager.get_concept_board_stocks(board_code, source=source, include_quote=include_quote)
    elif board_type == "industry":
        stocks, fetcher_source = manager.get_industry_board_stocks(board_code, source=source, include_quote=include_quote)
    else:
        stocks, fetcher_source = [], ""

    if stocks:
        update_cached_board_stocks(board_code, source, stocks)
        logger.info(f"[BoardCache] Refreshed {len(stocks)} stocks for board {board_code}/{source}")

    return stocks, fetcher_source


def _get_board_type(board_code: str, source: str, manager) -> str | None:
    """Determine board type by checking in local cache."""
    init_schema()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT board_type FROM stock_board WHERE code = ? AND source = ?",
        (board_code, source),
    )
    row = cursor.fetchone()
    return row["board_type"] if row else None


def _read_boards_from_db(board_type: str, source: str) -> list:
    """Read board list from database (metadata only)."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """SELECT code, name, board_type, source, updated_at
           FROM stock_board WHERE board_type = ? AND source = ? ORDER BY name""",
        (board_type, source),
    )
    rows = cursor.fetchall()
    return [
        {
            "code": row["code"],
            "name": row["name"],
            "board_type": row["board_type"],
            "source": row["source"],
            "updated_at": row["updated_at"],
        }
        for row in rows
    ]


def _read_board_stocks_from_db(board_code: str, source: str) -> list:
    """Read board-stock list from database (metadata only)."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """SELECT stock_code, stock_name, updated_at
           FROM stock_board_stock WHERE board_code = ? AND source = ? ORDER BY stock_code""",
        (board_code, source),
    )
    rows = cursor.fetchall()
    return [
        {
            "stock_code": row["stock_code"],
            "stock_name": row["stock_name"],
            "updated_at": row["updated_at"],
        }
        for row in rows
    ]


def update_cached_boards(board_type: str, source: str, boards: list) -> int:
    """
    Update cached boards metadata for a board_type + source.

    Only stores metadata (code, name, type, source, timestamp).
    Realtime quote data is always fetched from the API, never cached in SQLite.

    Args:
        board_type: "concept" or "industry"
        source: Data source
        boards: List of dicts [{"code": "BK1048", "name": "互联网服务"}, ...]

    Returns:
        Number of boards inserted/updated
    """
    if not boards:
        return 0

    init_schema()

    conn = get_connection()
    try:
        with conn:
            cursor = conn.cursor()
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            cursor.executemany(
                """INSERT OR REPLACE INTO stock_board
                (code, name, board_type, source, updated_at)
                VALUES (?, ?, ?, ?, ?)""",
                [
                    (b["code"], b["name"], board_type, source, now)
                    for b in boards
                ],
            )

            logger.info(f"[BoardCache] Updated {len(boards)} boards for {board_type}/{source}")
            return len(boards)
    except Exception as e:
        logger.error(f"[BoardCache] Update boards failed: {e}")
        raise


def update_cached_board_stocks(board_code: str, source: str, stocks: list) -> int:
    """
    Update cached stocks metadata for a board.

    Only stores metadata (board_code, stock_code, stock_name, source, timestamp).
    Realtime quote data is always fetched from the API, never cached in SQLite.

    Args:
        board_code: Board code
        source: Data source
        stocks: List of dicts [{"stock_code": "600519", "stock_name": "贵州茅台"}, ...]

    Returns:
        Number of stocks inserted/updated
    """
    if not stocks:
        return 0

    init_schema()

    conn = get_connection()
    try:
        with conn:
            cursor = conn.cursor()
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            cursor.executemany(
                """INSERT OR REPLACE INTO stock_board_stock
                (board_code, source, stock_code, stock_name, updated_at)
                VALUES (?, ?, ?, ?, ?)""",
                [
                    (board_code, source, s["stock_code"], s["stock_name"], now)
                    for s in stocks
                ],
            )

            logger.info(f"[BoardCache] Updated {len(stocks)} stocks for board {board_code}/{source}")
            return len(stocks)
    except Exception as e:
        logger.error(f"[BoardCache] Update board stocks failed: {e}")
        raise
