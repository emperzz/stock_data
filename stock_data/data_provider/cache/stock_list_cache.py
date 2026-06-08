"""
SQLite cache for stock lists.

Provides persistent caching for stock listing data to avoid repeated
upstream API calls which are slow and may fail.
"""

import logging
import os
import sqlite3
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_db_path: Path | None = None
_last_refresh_date: dict[str, str] = {}  # market -> "YYYY-MM-DD"


def _is_first_call_of_day(market: str) -> bool:
    """Check if this is the first call of the day for the market, and update the tracker."""
    today = datetime.now().strftime("%Y-%m-%d")
    if _last_refresh_date.get(market) != today:
        _last_refresh_date[market] = today
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
    """Initialize the database schema."""
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS stock_list (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                market TEXT NOT NULL,
                code TEXT NOT NULL,
                name TEXT NOT NULL,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(market, code)
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_market ON stock_list(market)
        """)
        conn.commit()
        logger.info(f"[StockCache] Database initialized at {_get_db_path()}")
    finally:
        conn.close()


def _fetch_from_upstream(market: str, manager) -> list:
    """Fetch stock list from upstream fetchers."""
    from ..base import DataCapability

    fetchers = manager._filter_by_capability(market, DataCapability.STOCK_LIST)

    for fetcher in fetchers:
        try:
            stocks = fetcher.get_all_stocks(market)
            if stocks:
                return stocks
        except Exception as e:
            logger.warning(f"[StockCache] {fetcher.name} failed to fetch {market}: {e}")
            continue

    logger.warning(f"[StockCache] No fetcher available for market={market}")
    return []


def get_stock_list(market: str, refresh: bool = False, manager=None) -> list:
    """
    Get stock list with automatic refresh.

    - No local cache -> fetch from upstream and cache
    - First call of the day -> force refresh
    - refresh=True -> force refresh
    - Otherwise -> return cached data

    Args:
        market: Market type (csi/hk/us)
        refresh: If True, force refresh from upstream
        manager: DataFetcherManager instance. If None, creates one lazily.

    Returns:
        List of stock dicts: [{"code": "600519", "name": "贵州茅台"}, ...]
    """
    init_db()

    needs_refresh = refresh or _is_first_call_of_day(market)

    if not needs_refresh:
        cached = _read_from_db(market)
        if cached:
            return cached

    # Need refresh: fetch from upstream and update cache
    # Lazy import to avoid circular dependency
    if manager is None:
        from ..base import DataFetcherManager
        from ..fetchers.akshare_fetcher import AkshareFetcher

        manager = DataFetcherManager()
        manager.add_fetcher(AkshareFetcher())

    stocks = _fetch_from_upstream(market, manager)
    if stocks:
        update_cached_stocks(market, stocks)
        logger.info(f"[StockCache] Refreshed {len(stocks)} stocks for market={market}")

    return stocks


def get_stock_name(code: str, market: str | None = None, manager=None) -> str:
    """
    Get stock name from cache by code.

    Args:
        code: Stock code (e.g., 600519, AAPL, HK00700)
        market: Market tag (csi/hk/us). If None, inferred from code.
        manager: DataFetcherManager instance. If None and cache miss, returns "".

    Returns:
        Stock name or empty string if not found.
    """
    from ..utils.normalize import market_tag, normalize_stock_code

    normalized = normalize_stock_code(code)
    if market is None:
        market = market_tag(normalized)

    stocks = get_stock_list(market, refresh=False, manager=manager)
    for s in stocks:
        if s["code"] == normalized:
            return s["name"]
    return ""


def _read_from_db(market: str) -> list:
    """Read stock list from database."""
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT code, name, updated_at FROM stock_list WHERE market = ? ORDER BY code",
            (market,),
        )
        rows = cursor.fetchall()
        return [
            {"code": row["code"], "name": row["name"], "updated_at": row["updated_at"]}
            for row in rows
        ]
    finally:
        conn.close()


def get_cached_stocks(market: str) -> list:
    """
    Get cached stocks for a market (backward compatible).

    Returns cached data without daily-refresh logic.
    Use get_stock_list() for daily-refresh aware fetching.
    """
    init_db()

    conn = _get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT code, name, updated_at FROM stock_list WHERE market = ? ORDER BY code",
            (market,),
        )
        rows = cursor.fetchall()
        return [
            {"code": row["code"], "name": row["name"], "updated_at": row["updated_at"]}
            for row in rows
        ]
    finally:
        conn.close()


def update_cached_stocks(market: str, stocks: list) -> int:
    """
    Update cached stocks for a market.

    Args:
        market: Market type (csi/hk/us)
        stocks: List of dicts [{"code": "600519", "name": "贵州茅台"}, ...]

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

            cursor.execute("DELETE FROM stock_list WHERE market = ?", (market,))
            for stock in stocks:
                cursor.execute(
                    "INSERT INTO stock_list (market, code, name, updated_at) VALUES (?, ?, ?, ?)",
                    (market, stock["code"], stock["name"], now),
                )

            logger.info(f"[StockCache] Updated {len(stocks)} stocks for market={market}")
            return len(stocks)
    except Exception as e:
        logger.error(f"[StockCache] Update failed: {e}")
        raise
    finally:
        conn.close()


def has_cached_data(market: str) -> bool:
    """Check if there's cached data for a market."""
    if not _get_db_path().exists():
        return False

    init_db()
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM stock_list WHERE market = ? LIMIT 1", (market,))
        return cursor.fetchone() is not None
    finally:
        conn.close()


def get_cache_info() -> dict:
    """Get cache statistics."""
    if not _get_db_path().exists():
        return {"total_stocks": 0, "markets": {}}

    init_db()
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT market, COUNT(*) as cnt FROM stock_list GROUP BY market")
        rows = cursor.fetchall()
        result = {"total_stocks": 0, "markets": {}}
        for row in rows:
            result["markets"][row["market"]] = row["cnt"]
            result["total_stocks"] += row["cnt"]
        return result
    finally:
        conn.close()
