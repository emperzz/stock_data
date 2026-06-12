"""
SQLite persistence for stock lists.

Provides persistent storage for stock listing data to avoid repeated
upstream API calls which are slow and may fail.
"""

import logging
from datetime import datetime

from ._refresh import DailyRefreshTracker
from .db import get_connection, get_db_path

logger = logging.getLogger(__name__)

_refresh_tracker = DailyRefreshTracker()


# Public → fetcher market-tag conversion. The external API (routes.py)
# exposes A-shares as ``csi``; the fetcher's ``get_all_stocks`` API uses
# the legacy ``cn`` tag. The ``csi -> cn`` translation is now applied
# inside ``manager.get_all_stocks`` at the call boundary, so this
# mapping is documented here as the single source of truth for the
# public-to-fetcher tag boundary (in case future boundary tags are
# added and need cross-referencing).
PUBLIC_TO_FETCHER_MARKET = {"csi": "cn"}


def init_schema() -> None:
    """Initialize the database schema."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
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
        logger.info(f"[StockCache] Database initialized at {get_db_path()}")
    finally:
        conn.close()


def _fetch_from_upstream(public_market: str, manager) -> tuple[list, str]:
    """Fetch stock list from upstream fetchers via the manager wrapper.

    The public_market (``csi``/``hk``/``us``) is passed to
    ``manager.get_all_stocks`` as-is, since capability-based routing
    in the manager uses the fetcher's ``supported_markets`` (which
    declares ``"csi"`` for A-shares). The fetcher itself is
    responsible for translating to its own internal tag if its
    underlying API needs it (e.g. akshare's ``ak.stock_info_a_code_name``
    treats the call as A-share without a market param).

    Returns:
        Tuple of ``(stocks, fetcher_name)``. ``fetcher_name`` is the
        name of the fetcher that returned the data (e.g. ``"akshare"``),
        or ``""`` if every fetcher returned an empty list. ``stocks``
        is always a list (never ``None``) — the manager wrapper
        returns ``None`` to signal total failure, which we normalize
        to an empty list here for the persistence layer.
    """
    stocks, fetcher_source = manager.get_all_stocks(public_market)
    if stocks is None:
        stocks = []
    return stocks, fetcher_source


def get_stock_list(market: str, refresh: bool = False, manager=None) -> tuple[list, str]:
    """
    Get stock list with automatic refresh.

    - No local cache -> fetch from upstream and cache
    - First call of the day -> force refresh
    - refresh=True -> force refresh
    - Otherwise -> return cached data

    Args:
        market: Public market tag (csi/hk/us). A-shares are ``csi`` —
            the legacy ``cn`` tag is an internal fetcher convention
            and is converted transparently at the fetcher call site.
        refresh: If True, force refresh from upstream
        manager: DataFetcherManager instance. If None, creates one lazily.

    Returns:
        Tuple of ``(stocks, origin)`` where ``origin`` is:
          - the fetcher name (e.g. ``"akshare"``) when the data was
            freshly fetched from a fetcher,
          - ``"persistence"`` when the data was read from the SQLite
            cache.
        ``stocks`` is a list of stock dicts:
        ``[{"code": "600519", "name": "贵州茅台"}, ...]``
    """
    init_schema()

    # DB cache key uses the public tag (csi) for stable on-disk layout.
    public_market = market

    needs_refresh = refresh or _refresh_tracker.is_first_call(public_market)

    if not needs_refresh:
        cached = _read_from_db(public_market)
        if cached:
            return cached, "persistence"

    # Need refresh: fetch from upstream and update cache
    if manager is None:
        from ..manager import create_default_manager

        manager = create_default_manager()

    stocks, fetcher_source = _fetch_from_upstream(public_market, manager)
    if stocks:
        update_cached_stocks(public_market, stocks)
        logger.info(f"[StockCache] Refreshed {len(stocks)} stocks for market={public_market}")

    return stocks, fetcher_source


def get_stock_name(code: str, market: str | None = None, manager=None) -> str:
    """
    Get stock name from persistence by code.

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

    # First try DB lookup (efficient for single stock)
    name = _get_stock_name_from_db(normalized, market)
    if name:
        return name

    # Fallback to full list load (for backward compat)
    stocks, _origin = get_stock_list(market, refresh=False, manager=manager)
    for s in stocks:
        if s["code"] == normalized:
            return s["name"]
    return ""


def _get_stock_name_from_db(code: str, market: str) -> str:
    """Query single stock name from DB efficiently."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM stock_list WHERE market = ? AND code = ?",
            (market, code),
        )
        row = cursor.fetchone()
        return row["name"] if row else ""
    finally:
        conn.close()


def _read_from_db(market: str) -> list:
    """Read stock list from database."""
    conn = get_connection()
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
    init_schema()

    conn = get_connection()
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

    init_schema()

    conn = get_connection()
    try:
        with conn:
            cursor = conn.cursor()
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            cursor.executemany(
                "INSERT OR REPLACE INTO stock_list (market, code, name, updated_at) VALUES (?, ?, ?, ?)",
                [(market, stock["code"], stock["name"], now) for stock in stocks],
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
    if not get_db_path().exists():
        return False

    init_schema()
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM stock_list WHERE market = ? LIMIT 1", (market,))
        return cursor.fetchone() is not None
    finally:
        conn.close()


def get_cache_info() -> dict:
    """Get cache statistics."""
    if not get_db_path().exists():
        return {"total_stocks": 0, "markets": {}}

    init_schema()
    conn = get_connection()
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

