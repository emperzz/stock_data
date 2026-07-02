"""
SQLite persistence for stock board (concept/industry) data.

Provides persistent storage for board listing data to avoid repeated
upstream API calls which are slow and may fail.
"""

import logging
import sqlite3
from datetime import datetime
from typing import Any

from . import db
from ._refresh import DailyRefreshTracker
from .db import get_connection, get_db_path

logger = logging.getLogger(__name__)

_refresh_tracker = DailyRefreshTracker()
_schema_initialized_paths: set[str] = set()

# Subtype 合法值表：source → type → {subtype 集合}
VALID_SUBTYPES_BY_SOURCE: dict[str, dict[str, set[str]]] = {
    "eastmoney": {
        "concept": {"concept"},
        "industry": {"industry"},
        "index": {"index"},
        "special": {"special"},
    },
    "zhitu": {
        "industry": {"申万行业", "申万二级", "证监会行业"},
        "concept": {"热门概念", "概念板块", "地域板块"},
        "index": {"分类", "指数成分", "大盘指数"},
        "special": {"风险警示", "次新股", "沪港通", "深港通"},
    },
    "zzshare": {  # NEW
        "industry": {"同花顺行业"},
        "concept": {"同花顺概念"},
        "special": {"同花顺题材"},
        # "index" — zzshare 不暴露大盘指数板块
    },
}

# Valid board types and sources — derived from VALID_SUBTYPES_BY_SOURCE so
# there is exactly one source of truth.  Import these instead of re-defining
# the same tuple/set elsewhere.
VALID_BOARD_TYPES: tuple[str, ...] = ("concept", "industry", "index", "special")
VALID_SOURCES: tuple[str, ...] = tuple(sorted(VALID_SUBTYPES_BY_SOURCE.keys()))


def _validate_subtype(source: str, board_type: str, subtype: str | None) -> None:
    """Validate subtype against the source's declared subtype set.

    Args:
        source: data source name (e.g. ``"zhitu"``).
        board_type: one of ``concept / industry / index / special``.
        subtype: optional subtype name; ``None`` means "all subtypes".

    Raises:
        ValueError: source unknown, type invalid for source, or subtype
            not in the source's declared subtype set. Error message lists
            the valid subtypes for the source/type pair.
    """
    if subtype is None:
        return
    source_table = VALID_SUBTYPES_BY_SOURCE.get(source)
    if source_table is None:
        raise ValueError(
            f"Unknown source '{source}'. Known sources: {sorted(VALID_SUBTYPES_BY_SOURCE.keys())}"
        )
    valid_set = source_table.get(board_type)
    if valid_set is None:
        raise ValueError(
            f"Invalid type '{board_type}' for source '{source}'. "
            f"Valid types: {sorted(source_table.keys())}"
        )
    if subtype not in valid_set:
        raise ValueError(
            f"Invalid subtype '{subtype}' for type='{board_type}' "
            f"source='{source}'. "
            f"Valid subtypes: {sorted(valid_set)}"
        )


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
            subtype TEXT,
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
    # Composite index for the common cache-hit read pattern
    # ``WHERE board_type=? AND source=? [AND subtype=?]``.
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_stock_board_type_subtype_source
        ON stock_board(board_type, subtype, source)
    """)
    # Membership table — bidirectional stock <-> board index. See
    # docs/superpowers/specs/2026-07-01-stock-board-membership-design.md §2.1.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS stock_board_membership (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            board_code  TEXT NOT NULL,
            stock_code  TEXT NOT NULL,
            source      TEXT NOT NULL,
            board_name  TEXT NOT NULL,
            stock_name  TEXT NOT NULL,
            board_type  TEXT NOT NULL,
            subtype     TEXT,
            refreshed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(board_code, source, stock_code)
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_membership_reverse
            ON stock_board_membership(stock_code, source)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_membership_forward
            ON stock_board_membership(board_code, source)
    """)
    conn.commit()
    logger.info(f"[BoardCache] Database initialized at {get_db_path()}")


def get_board_list(
    board_type: str,
    source: str,
    refresh: bool = False,
    include_quote: bool = False,
    subtype: str | None = None,
    manager=None,
) -> tuple[list, str]:
    """
    Get board list with automatic refresh.

    - No local cache -> fetch from upstream and cache
    - First call of the day -> force refresh
    - refresh=True -> force refresh
    - include_quote=True -> always fetch fresh data from upstream
    - Otherwise -> return cached data

    Args:
        board_type: one of "concept" / "industry" / "index" / "special"
        source: Data source (e.g., "eastmoney", "zhitu", "zzshare")
        refresh: If True, force refresh from upstream
        include_quote: If True, include realtime price/change/market data and skip cache
        subtype: optional source-specific subtype filter (validated by caller).
            Cache key is always the full (board_type, source) tuple — the
            subtype filter is applied at read time, so all subtypes for a
            given (board_type, source) are stored together. This is safe
            because every production fetcher fetches the full tree and
            filters in-memory before returning (the upstream cost is the
            same regardless of the subtype filter), so we don't lose
            caching granularity by always fetching unfiltered.
        manager: DataFetcherManager instance. Required for fetching from upstream.

    Returns:
        Tuple of (boards, origin) where origin is:
          - the fetcher name (e.g. "eastmoney") when the data was freshly fetched
          - "persistence" when the data was read from the SQLite cache
        List of board dicts: [{"code": "BK1048", "name": "互联网服务", "board_type": "concept", "subtype": "热门概念", "source": "eastmoney"}, ...]
            May include quote fields when include_quote=True.
    """
    init_schema()

    needs_refresh = (
        refresh or include_quote or _refresh_tracker.is_first_call(f"{board_type}:{source}")
    )

    if not needs_refresh:
        cached = _read_boards_from_db(board_type, source, subtype)
        if cached:
            return cached, "persistence"

    # Need refresh: fetch from upstream and update cache
    if manager is None:
        raise ValueError("manager is required when refresh=True or cache miss")

    # Fetch via unified entry point (see manager.get_all_boards).
    # Always fetch the full subtype set (subtype=None) — the cache stores
    # all subtypes for a (board_type, source) so future subtype-filtered
    # reads can be served from cache. The fetcher returns rows already
    # tagged with their per-row subtype field.
    boards, fetcher_source = manager.get_all_boards(
        source=source,
        board_type=board_type,
        subtype=None,
        include_quote=include_quote,
    )

    if boards:
        # Always cache the base board data (without quote if include_quote=False)
        update_cached_boards(board_type, source, boards)
        logger.info(f"[BoardCache] Refreshed {len(boards)} boards for {board_type}/{source}")

    # On cache miss with a subtype filter, narrow the in-memory result before
    # returning. (On cache hit, the SQL WHERE clause already filtered.)
    if subtype is not None:
        boards = [b for b in boards if b.get("subtype") == subtype]

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
    needs_refresh = (
        include_quote or refresh or _refresh_tracker.is_first_call(f"{board_code}:{source}")
    )

    if not needs_refresh:
        cached = _read_board_stocks_from_db(board_code, source)
        if cached:
            return cached, "persistence"

    # Need refresh: fetch from upstream and update cache
    if manager is None:
        raise ValueError("manager is required when refresh=True or cache miss")

    # Single unified entry point — the fetcher's get_board_stocks handles
    # concept/industry disambiguation internally (EastMoney tries concept
    # then falls back to industry; Zhitu is type-agnostic). We still consult
    # the SQLite board_type cache above (in the cache-hit fast path) so a
    # known concept/industry board avoids the fetcher's fallback cost.
    _ = _get_board_type(board_code, source, manager)  # warms the board_type cache
    stocks, fetcher_source = manager.get_board_stocks(
        board_code,
        source=source,
        include_quote=include_quote,
    )

    if stocks:
        # Cold-fill: persists stocks to stock_board_membership via the
        # single-write update_cached_board_stocks helper.
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


def read_membership(
    board_code: str | None = None,
    stock_code: str | None = None,
    source: str | None = None,
) -> list[dict[str, Any]]:
    """Read membership rows. Exactly one of board_code / stock_code must be set.

    Args:
        board_code: forward direction — return all stocks in this board.
        stock_code: reverse direction — return all boards this stock belongs to.
        source: optional filter (e.g. 'eastmoney' / 'zhitu' / 'zzshare').

    Returns:
        List of membership rows with keys:
            board_code, stock_code, source, board_name, stock_name,
            board_type, subtype, refreshed_at
    """
    init_schema()
    if (board_code is None) == (stock_code is None):
        raise ValueError("Exactly one of board_code or stock_code must be set, not both/neither.")

    conn = get_connection()
    cursor = conn.cursor()

    if board_code is not None:
        sql = """SELECT board_code, stock_code, source, board_name, stock_name,
                        board_type, subtype, refreshed_at
                 FROM stock_board_membership
                 WHERE board_code = ?"""
        params: tuple = (board_code,)
    else:
        sql = """SELECT board_code, stock_code, source, board_name, stock_name,
                        board_type, subtype, refreshed_at
                 FROM stock_board_membership
                 WHERE stock_code = ?"""
        params = (stock_code,)

    if source is not None:
        sql += " AND source = ?"
        params = params + (source,)

    sql += " ORDER BY board_code, stock_code"

    cursor.execute(sql, params)
    rows = cursor.fetchall()
    return [
        {
            "board_code": r["board_code"],
            "stock_code": r["stock_code"],
            "source": r["source"],
            "board_name": r["board_name"],
            "stock_name": r["stock_name"],
            "board_type": r["board_type"],
            "subtype": r["subtype"],
            "refreshed_at": r["refreshed_at"],
        }
        for r in rows
    ]


def upsert_membership_bulk(
    source: str,
    stocks: list[dict],
    board_code: str,
    board_name: str,
    board_type: str,
    subtype: str | None,
    conn: sqlite3.Connection | None = None,
) -> int:
    """Bulk upsert all stocks for one board. Returns count of rows affected.

    Args:
        source: 'eastmoney' | 'zhitu' | 'zzshare'
        stocks: list of {stock_code, stock_name}
        board_code: e.g. 'BK1001' (eastmoney) or 'sw_yx' (zhitu)
        board_name: e.g. '白酒' (denormalized for read perf)
        board_type: 'concept' | 'industry' | 'index' | 'special'
        subtype: source-specific subtype string
        conn: optional SQLite connection. When None, opens a fresh
            connection via get_connection(). Pass an existing
            connection when calling from a multi-threaded caller
            (each thread should own its own connection).

    Implementation notes:
        - Uses INSERT OR REPLACE so refreshed_at = CURRENT_TIMESTAMP.
        - One executemany call (one transaction) for the whole batch.
        - Returns the number of stock rows passed in (rows upserted).
    """
    if not stocks:
        return 0

    init_schema()
    if conn is None:
        conn = get_connection()
    with conn:
        cursor = conn.cursor()
        rows = [
            (
                board_code,
                source,
                s["stock_code"],
                s.get("stock_name", ""),
                board_name,
                board_type,
                subtype,
            )
            for s in stocks
        ]
        cursor.executemany(
            """INSERT OR REPLACE INTO stock_board_membership
               (board_code, source, stock_code, stock_name,
                board_name, board_type, subtype, refreshed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
            rows,
        )
    return len(rows)


def upsert_membership_for_stock_boards(
    stock_code: str,
    stock_name: str,
    boards: list[dict],
    source: str,
    conn: sqlite3.Connection | None = None,
) -> int:
    """Batch upsert all boards a stock belongs to (single transaction).

    Used by the zhitu cold path in `/stocks/{code}/boards` to write the
    reverse-index rows for every board returned by the fetcher in one
    executemany call. Each input board dict must have keys: code, name,
    type, subtype.

    Args:
        conn: optional SQLite connection. When None, opens a fresh
            connection via get_connection(). Pass an existing
            connection when calling from a multi-threaded caller
            (each thread should own its own connection).
    """
    if not boards:
        return 0

    init_schema()
    if conn is None:
        conn = get_connection()
    with conn:
        cursor = conn.cursor()
        rows = [
            (
                b["code"],
                source,
                stock_code,
                stock_name,
                b.get("name", ""),
                b.get("type", ""),
                b.get("subtype"),
            )
            for b in boards
        ]
        cursor.executemany(
            """INSERT OR REPLACE INTO stock_board_membership
               (board_code, source, stock_code, stock_name,
                board_name, board_type, subtype, refreshed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
            rows,
        )
    return len(rows)


def get_stock_boards_with_lazy_fill(
    stock_code: str,
    source: str,
    type: str | None = None,
    subtype: str | None = None,
    manager=None,
) -> tuple[list[dict] | None, str]:
    """Get boards a stock belongs to (with lazy fill for zhitu).

    Reads from ``stock_board_membership`` first. For ``source='zhitu'``,
    falls back to the fetcher's native reverse API on cold path and
    upserts the result to membership (consistent with the
    "persistence-only routing" rule in CLAUDE.md).

    For other sources, returns ``None`` if membership is empty
    (no upstream API to call).

    Args:
        stock_code: 6-digit stock code (e.g. '600519').
        source: 'eastmoney' | 'zhitu' | 'zzshare'.
        type: optional board type filter (concept/industry/index/special).
        subtype: optional source-specific subtype filter.
        manager: DataFetcherManager instance. Required.

    Returns:
        Tuple of (boards_list_or_None, origin). origin is 'persistence' on hit,
        fetcher name on cold-fill, or '' if cold (no upstream API).
        ``None`` means no data available.
    """
    if manager is None:
        raise ValueError("manager is required for get_stock_boards_with_lazy_fill")

    # Fast path: read from membership table
    rows = read_membership(stock_code=stock_code, source=source)
    if rows:
        if type is not None:
            rows = [r for r in rows if r["board_type"] == type]
        if subtype is not None:
            rows = [r for r in rows if r["subtype"] == subtype]
        if rows:
            # Convert to expected board dict shape: {code, name, type, subtype}
            boards = [
                {
                    "code": r["board_code"],
                    "name": r["board_name"],
                    "type": r["board_type"],
                    "subtype": r["subtype"] or "",
                }
                for r in rows
            ]
            return boards, "persistence"

    # Cold path: only zhitu has a native reverse API
    if source == "zhitu":
        boards, origin = manager.get_stock_boards(stock_code, source=source)
        if boards is not None and len(boards) > 0:
            # Resolve stock_name from stock_list
            from .stock_list import get_stock_name as _get_stock_name

            stock_name = _get_stock_name(stock_code) or ""
            upsert_membership_for_stock_boards(
                stock_code=stock_code,
                stock_name=stock_name,
                boards=boards,
                source=source,
            )
            # Apply type/subtype filters
            if type is not None:
                boards = [b for b in boards if b.get("type") == type]
            if subtype is not None:
                boards = [b for b in boards if b.get("subtype") == subtype]
            return boards, origin

    return None, ""


def get_stock_memberships(
    stock_code: str,
    sources: list[str],
    type: str | None = None,
    subtype: str | None = None,
    cold_fill: bool = False,
    manager=None,
) -> tuple[list[dict], list[str], str]:
    """Single source of truth for stock→boards reverse lookup.

    Reads stock_board_membership for each requested source, applies
    type/subtype filters, and (optionally) triggers zhitu cold-fill for
    sources with no data when cold_fill=True.

    Args:
        stock_code: 6-digit stock code (e.g. '600519').
        sources: list of normalized source names (no 'ths' alias; caller
                 must remap 'ths' → 'zzshare' before calling). May be empty.
        type: optional board type filter (concept/industry/index/special).
        subtype: optional source-specific subtype filter.
        cold_fill: if True and source='zhitu' has no data, call the zhitu
                   fetcher to populate membership (same lazy-fill as
                   get_stock_boards_with_lazy_fill). Other sources never
                   trigger cold-fill (no upstream API).
        manager: DataFetcherManager instance. Required when cold_fill=True.

    Returns:
        (entries, cold_sources, origin_summary)
        - entries: list of {code, name, type, subtype, source}, one dict per row.
        - cold_sources: subset of `sources` with no data after cold_fill attempt.
        - origin_summary:
            - "persistence" — all entries came from SQLite cache (no fetcher calls)
            - "<fetcher>"   — single source with cold-fill triggered
            - "mixed"       — multi-source case (entries span multiple sources)
            - ""            — no entries

    Caller decides how to expose origin_summary in the top-level response
    source field (single-source: pass-through; multi-source: override with 'merged').
    """
    init_schema()

    if not sources:
        return [], [], ""

    conn = get_connection()
    cursor = conn.cursor()

    # Read all rows for this stock from the requested sources in one query.
    placeholders = ",".join("?" * len(sources))
    cursor.execute(
        f"""SELECT board_code, stock_code, source, board_name, stock_name,
                   board_type, subtype
           FROM stock_board_membership
           WHERE stock_code = ? AND source IN ({placeholders})
           ORDER BY source, board_code""",
        (stock_code, *sources),
    )
    raw_rows = cursor.fetchall()

    # Group by source to compute present set
    present_sources: set[str] = set()
    entries: list[dict] = []
    for row in raw_rows:
        present_sources.add(row["source"])
        entries.append({
            "code": row["board_code"],
            "name": row["board_name"],
            "type": row["board_type"],
            "subtype": row["subtype"] or "",
            "source": row["source"],
        })

    # Cold-fill: only zhitu has upstream reverse API; only when cold_fill=True.
    cold_fill_triggered = False
    if cold_fill and manager is not None and "zhitu" in sources and "zhitu" not in present_sources:
        from .stock_list import get_stock_name as _get_stock_name

        boards, _ = manager.get_stock_boards(stock_code, source="zhitu")
        if boards:
            stock_name = _get_stock_name(stock_code) or ""
            upsert_membership_for_stock_boards(
                stock_code=stock_code,
                stock_name=stock_name,
                boards=boards,
                source="zhitu",
            )
            cold_fill_triggered = True
            # Re-query to include newly-written rows
            cursor.execute(
                f"""SELECT board_code, stock_code, source, board_name, stock_name,
                           board_type, subtype
                   FROM stock_board_membership
                   WHERE stock_code = ? AND source IN ({placeholders})
                   ORDER BY source, board_code""",
                (stock_code, *sources),
            )
            raw_rows = cursor.fetchall()
            entries = [
                {
                    "code": row["board_code"],
                    "name": row["board_name"],
                    "type": row["board_type"],
                    "subtype": row["subtype"] or "",
                    "source": row["source"],
                }
                for row in raw_rows
            ]
            present_sources = {row["source"] for row in raw_rows}

    # Apply type/subtype filters (post-query, in-memory)
    if type is not None:
        entries = [e for e in entries if e["type"] == type]
    if subtype is not None:
        entries = [e for e in entries if e["subtype"] == subtype]

    # Cold sources = requested but not present
    cold_sources = [s for s in sources if s not in present_sources]

    # Origin summary
    if cold_fill_triggered:
        origin_summary = "zhitu"  # cold-fill happened (zhitu is the only source that can)
    elif not entries:
        # No entries: either no cold-fill triggered, or cold-fill found nothing.
        # Either way we only read from SQLite; surface as 'persistence'.
        origin_summary = "persistence"
    elif len(sources) > 1:
        origin_summary = "mixed"
    else:
        origin_summary = "persistence"

    return entries, cold_sources, origin_summary


def get_board_name(board_code: str, source: str) -> str | None:
    """Look up a board's name from the SQLite cache (no upstream fallback).

    Used by ``/boards/{code}/stocks`` as a fast-path for resolving the
    board name returned in the response: if the board list cache already
    has a row for this (code, source), we read the name directly without
    triggering a full upstream board-list fetch. Returns ``None`` when
    the cache is cold — caller decides whether to fall back to a fetcher
    call or accept the raw ``board_code`` as the name.

    Args:
        board_code: Board code (e.g. ``"BK1048"``).
        source: Data source slug (``"eastmoney"``, ``"zhitu"``, ``"zzshare"``).

    Returns:
        The cached board name, or ``None`` if not found.
    """
    init_schema()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT name FROM stock_board WHERE code = ? AND source = ? LIMIT 1",
        (board_code, source),
    )
    row = cursor.fetchone()
    return row["name"] if row else None


def _read_boards_from_db(board_type: str, source: str, subtype: str | None = None) -> list[dict[str, Any]]:
    """Read board list from database (metadata only).

    Args:
        board_type: one of concept / industry / index / special.
        source: data source slug (eastmoney / zhitu / zzshare).
        subtype: optional subtype filter. ``None`` returns all subtypes for
            the (board_type, source) pair.
    """
    conn = get_connection()
    cursor = conn.cursor()
    if subtype is None:
        cursor.execute(
            """SELECT code, name, board_type, subtype, source, updated_at
               FROM stock_board WHERE board_type = ? AND source = ? ORDER BY name""",
            (board_type, source),
        )
    else:
        cursor.execute(
            """SELECT code, name, board_type, subtype, source, updated_at
               FROM stock_board
               WHERE board_type = ? AND source = ? AND subtype = ?
               ORDER BY name""",
            (board_type, source, subtype),
        )
    rows = cursor.fetchall()
    return [
        {
            "code": row["code"],
            "name": row["name"],
            "board_type": row["board_type"],
            "subtype": row["subtype"],
            "source": row["source"],
            "updated_at": row["updated_at"],
        }
        for row in rows
    ]


def _read_board_stocks_from_db(board_code: str, source: str) -> list[dict[str, Any]]:
    """Read board-stock list from membership table."""
    return [
        {
            "stock_code": r["stock_code"],
            "stock_name": r["stock_name"],
            "updated_at": r["refreshed_at"],
        }
        for r in read_membership(board_code=board_code, source=source)
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
                (code, name, board_type, subtype, source, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)""",
                [
                    (b["code"], b["name"], board_type, b.get("subtype") or "", source, now)
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
    Upsert stocks for a board into `stock_board_membership`.

    Args:
        board_code: Board code
        source: Data source
        stocks: List of dicts [{"stock_code": "600519", "stock_name": "贵州茅台"}, ...]

    Returns:
        Number of stocks written.
    """
    if not stocks:
        return 0

    init_schema()

    conn = get_connection()
    board_row = conn.execute(
        "SELECT name, board_type, subtype FROM stock_board WHERE code = ? AND source = ?",
        (board_code, source),
    ).fetchone()
    board_name = board_row["name"] if board_row else board_code
    board_type = board_row["board_type"] if board_row else ""
    subtype = board_row["subtype"] if board_row else None

    try:
        with conn:
            cursor = conn.cursor()
            cursor.executemany(
                """INSERT OR REPLACE INTO stock_board_membership
                   (board_code, source, stock_code, stock_name,
                    board_name, board_type, subtype, refreshed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
                [
                    (
                        board_code,
                        source,
                        s["stock_code"],
                        s["stock_name"],
                        board_name,
                        board_type,
                        subtype,
                    )
                    for s in stocks
                ],
            )
            logger.info(
                f"[BoardCache] Updated {len(stocks)} stocks for board {board_code}/{source}"
            )
            return len(stocks)
    except Exception as e:
        logger.error(f"[BoardCache] Update board stocks failed: {e}")
        raise
