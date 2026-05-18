"""
SQLite cache for stock board (concept/industry) data.

Provides persistent caching for board listing data to avoid repeated
upstream API calls which are slow and may fail.
"""

import logging
import os
import sqlite3
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_db_path: Path | None = None
_last_refresh_date: dict[str, str] = {}  # key: "board_type:source" -> "YYYY-MM-DD"


def _is_first_call_of_day(board_type: str, source: str) -> bool:
    """Check if this is the first call of the day for the board_type+source, and update the tracker."""
    today = datetime.now().strftime("%Y-%m-%d")
    key = f"{board_type}:{source}"
    if _last_refresh_date.get(key) != today:
        _last_refresh_date[key] = today
        return True
    return False


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
    """Initialize the database schema for stock boards."""
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        # Board list table
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
        # Board-stock relation table
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
        logger.info(f"[BoardCache] Database initialized at {_get_db_path()}")
    finally:
        conn.close()


def get_board_list(board_type: str, source: str, refresh: bool = False, manager=None) -> list:
    """
    Get board list with automatic refresh.

    - No local cache -> fetch from upstream and cache
    - First call of the day -> force refresh
    - refresh=True -> force refresh
    - Otherwise -> return cached data

    Args:
        board_type: "concept" or "industry"
        source: Data source (e.g., "eastmoney")
        refresh: If True, force refresh from upstream
        manager: DataFetcherManager instance. If None, creates one lazily.

    Returns:
        List of board dicts: [{"code": "BK1048", "name": "互联网服务", "board_type": "concept", "source": "eastmoney"}, ...]
    """
    init_db()

    needs_refresh = refresh or _is_first_call_of_day(board_type, source)

    if not needs_refresh:
        cached = _read_boards_from_db(board_type, source)
        if cached:
            return cached

    # Need refresh: fetch from upstream and update cache
    if manager is None:
        from ..fetchers.akshare_fetcher import AkshareFetcher
        from ..base import DataFetcherManager

        manager = DataFetcherManager()
        manager.add_fetcher(AkshareFetcher())

    # Fetch based on board_type
    if board_type == "concept":
        boards = manager.get_all_concept_boards(source=source)
    elif board_type == "industry":
        boards = manager.get_all_industry_boards(source=source)
    else:
        boards = []

    if boards:
        update_cached_boards(board_type, source, boards)
        logger.info(f"[BoardCache] Refreshed {len(boards)} boards for {board_type}/{source}")

    return boards


def get_board_stocks(board_code: str, source: str, refresh: bool = False, manager=None) -> list:
    """
    Get stocks belonging to a board with automatic refresh.

    Args:
        board_code: Board code (e.g., "BK1048")
        source: Data source (e.g., "eastmoney")
        refresh: If True, force refresh from upstream
        manager: DataFetcherManager instance. If None, creates one lazily.

    Returns:
        List of stock dicts: [{"stock_code": "600519", "stock_name": "贵州茅台"}, ...]
    """
    init_db()

    key = f"{board_code}:{source}"
    needs_refresh = refresh or _is_first_call_of_day(board_code, source)

    if not needs_refresh:
        cached = _read_board_stocks_from_db(board_code, source)
        if cached:
            return cached

    # Need refresh: fetch from upstream and update cache
    if manager is None:
        from ..fetchers.akshare_fetcher import AkshareFetcher
        from ..base import DataFetcherManager

        manager = DataFetcherManager()
        manager.add_fetcher(AkshareFetcher())

    # Determine board_type from board_code prefix pattern
    # For eastmoney: concept boards start with "BK", industry boards are numeric
    # We need to check which type this board_code belongs to
    board_type = _get_board_type(board_code, source, manager)
    if board_type == "concept":
        stocks = manager.get_concept_board_stocks(board_code, source=source)
    elif board_type == "industry":
        stocks = manager.get_industry_board_stocks(board_code, source=source)
    else:
        stocks = []

    if stocks:
        update_cached_board_stocks(board_code, source, stocks)
        logger.info(f"[BoardCache] Refreshed {len(stocks)} stocks for board {board_code}/{source}")

    return stocks


def _get_board_type(board_code: str, source: str, manager) -> str | None:
    """Determine board type by checking in local cache."""
    init_db()
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT board_type FROM stock_board WHERE code = ? AND source = ?",
            (board_code, source),
        )
        row = cursor.fetchone()
        return row["board_type"] if row else None
    finally:
        conn.close()


def _read_boards_from_db(board_type: str, source: str) -> list:
    """Read board list from database."""
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT code, name, board_type, source, updated_at FROM stock_board WHERE board_type = ? AND source = ? ORDER BY name",
            (board_type, source),
        )
        rows = cursor.fetchall()
        return [
            {"code": row["code"], "name": row["name"], "board_type": row["board_type"], "source": row["source"], "updated_at": row["updated_at"]}
            for row in rows
        ]
    finally:
        conn.close()


def _read_board_stocks_from_db(board_code: str, source: str) -> list:
    """Read board-stock list from database."""
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT stock_code, stock_name, updated_at FROM stock_board_stock WHERE board_code = ? AND source = ? ORDER BY stock_code",
            (board_code, source),
        )
        rows = cursor.fetchall()
        return [
            {"stock_code": row["stock_code"], "stock_name": row["stock_name"], "updated_at": row["updated_at"]}
            for row in rows
        ]
    finally:
        conn.close()


def update_cached_boards(board_type: str, source: str, boards: list) -> int:
    """
    Update cached boards for a board_type + source.

    Args:
        board_type: "concept" or "industry"
        source: Data source
        boards: List of dicts [{"code": "BK1048", "name": "互联网服务"}, ...]

    Returns:
        Number of boards inserted/updated
    """
    if not boards:
        return 0

    init_db()

    conn = _get_connection()
    try:
        with conn:
            cursor = conn.cursor()
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            cursor.executemany(
                "INSERT OR REPLACE INTO stock_board (code, name, board_type, source, updated_at) VALUES (?, ?, ?, ?, ?)",
                [(b["code"], b["name"], board_type, source, now) for b in boards],
            )

            logger.info(f"[BoardCache] Updated {len(boards)} boards for {board_type}/{source}")
            return len(boards)
    except Exception as e:
        logger.error(f"[BoardCache] Update boards failed: {e}")
        raise
    finally:
        conn.close()


def update_cached_board_stocks(board_code: str, source: str, stocks: list) -> int:
    """
    Update cached stocks for a board.

    Args:
        board_code: Board code
        source: Data source
        stocks: List of dicts [{"stock_code": "600519", "stock_name": "贵州茅台"}, ...]

    Returns:
        Number of stocks inserted/updated
    """
    if not stocks:
        return 0

    init_db()

    conn = _get_connection()
    try:
        with conn:
            cursor = conn.cursor()
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            cursor.executemany(
                "INSERT OR REPLACE INTO stock_board_stock (board_code, source, stock_code, stock_name, updated_at) VALUES (?, ?, ?, ?, ?)",
                [(board_code, source, s["stock_code"], s["stock_name"], now) for s in stocks],
            )

            logger.info(f"[BoardCache] Updated {len(stocks)} stocks for board {board_code}/{source}")
            return len(stocks)
    except Exception as e:
        logger.error(f"[BoardCache] Update board stocks failed: {e}")
        raise
    finally:
        conn.close()


def has_cached_data(board_type: str, source: str) -> bool:
    """Check if there's cached data for a board_type + source."""
    if not _get_db_path().exists():
        return False

    init_db()
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT 1 FROM stock_board WHERE board_type = ? AND source = ? LIMIT 1",
            (board_type, source),
        )
        return cursor.fetchone() is not None
    finally:
        conn.close()


def get_cache_info() -> dict:
    """Get cache statistics."""
    if not _get_db_path().exists():
        return {"total_boards": 0, "total_board_stocks": 0, "by_type": {}}

    init_db()
    conn = _get_connection()
    try:
        cursor = conn.cursor()

        # Count boards by type
        cursor.execute("SELECT board_type, source, COUNT(*) as cnt FROM stock_board GROUP BY board_type, source")
        rows = cursor.fetchall()

        result = {"total_boards": 0, "total_board_stocks": 0, "by_type": {}}
        for row in rows:
            key = f"{row['board_type']}:{row['source']}"
            result["by_type"][key] = row["cnt"]
            result["total_boards"] += row["cnt"]

        # Count board stocks
        cursor.execute("SELECT COUNT(*) as cnt FROM stock_board_stock")
        row = cursor.fetchone()
        result["total_board_stocks"] = row["cnt"] if row else 0

        return result
    finally:
        conn.close()