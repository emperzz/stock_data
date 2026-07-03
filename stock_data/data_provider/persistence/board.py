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
    board_type: str | None,
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

    When ``board_type`` is ``None`` every type supported by ``source`` is
    fetched (and persisted) as a single call. Subtype is rejected when
    ``board_type`` is ``None`` (subtypes are scoped per type) — the route
    layer surfaces a 400 in that case. The result rows carry their
    ``type`` field so callers can split / filter on the response side.

    Args:
        board_type: one of "concept" / "industry" / "index" / "special", or
            ``None`` to query every type the source exposes.
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
            Ignored when ``board_type`` is ``None`` (each type has its own
            subtype set; cross-type subtype filtering is undefined).
        manager: DataFetcherManager instance. Required for fetching from upstream.

    Returns:
        Tuple of (boards, origin) where origin is:
          - the fetcher name (e.g. "eastmoney") when the data was freshly fetched
          - "persistence" when the data was read from the SQLite cache
          - "mixed" when ``board_type`` is ``None`` and the response is
            composed of multiple (board_type, source) cache slots — some
            may be cache hits, some fetcher hits. Mirrors the multi-source
            summary in ``get_stock_memberships`` so the response's
            ``source`` field uses the same label across endpoints.
        List of board dicts: [{"code": "BK1048", "name": "互联网服务", "board_type": "concept", "subtype": "热门概念", "source": "eastmoney"}, ...]
            May include quote fields when include_quote=True.
    """
    init_schema()

    if board_type is None:
        return _get_all_board_types(
            source=source,
            refresh=refresh,
            include_quote=include_quote,
            subtype=subtype,
            manager=manager,
        )

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


def _get_all_board_types(
    source: str,
    refresh: bool,
    include_quote: bool,
    subtype: str | None,
    manager,
) -> tuple[list, str]:
    """All-types variant of :func:`get_board_list`.

    Iterates over every board_type the source exposes (derived from
    ``VALID_SUBTYPES_BY_SOURCE[source]`` so sources without an entry for
    a given type are simply skipped — e.g. zzshare has no ``index``).
    Delegates to :func:`get_board_list` for each type so the per-type
    daily-refresh tracker, cache-hit short-circuit, and persistence write
    behave identically to single-type calls.

    Returns:
        ``(combined_boards, origin)`` where ``origin`` is:
          - the fetcher name when *every* per-type call hit the network
            (this matches single-source ``persistence`` consumers)
          - ``"persistence"`` when *every* per-type call was a cache hit
          - ``"merged"`` otherwise (some types fresh, some cached) — a
            honest summary so the response field doesn't claim a single
            fetcher that didn't fully run.
    """
    init_schema()

    if subtype is not None:
        # Defensive guard: route layer rejects this case with 400, but if
        # some other caller passes through, fail loud rather than silently
        # mixing types in the cache.
        raise ValueError(
            "subtype filter requires a specific board_type; "
            "cross-type subtype filtering is not supported."
        )

    if manager is None:
        raise ValueError(
            "manager is required when querying all board types "
            "(cache may be partially cold and an upstream call may be needed)"
        )

    # Use the per-source subtype table as the source of truth for which
    # types this source exposes. This keeps zzshare's "no index" rule
    # honest: a missing key means the type is not supported, full stop.
    supported_types = list(VALID_SUBTYPES_BY_SOURCE.get(source, {}).keys())
    if not supported_types:
        return [], "persistence"

    combined: list[dict] = []
    seen_codes: set[str] = set()  # de-dup by (code) within a source
    origins: set[str] = set()
    for bt in supported_types:
        boards, origin = get_board_list(
            board_type=bt,
            source=source,
            refresh=refresh,
            include_quote=include_quote,
            subtype=None,
            manager=manager,
        )
        origins.add(origin)
        # H2 (review): partial-failure visibility. When the per-type
        # call hits the network (origin != "persistence") and returns
        # zero rows, the upstream almost certainly failed — log so the
        # silent partial-success doesn't mislead downstream consumers.
        if not boards and origin != "persistence":
            logger.warning(
                f"[BoardCache] all-types query for source='{source}' "
                f"board_type='{bt}' returned 0 rows from upstream "
                f"({origin}); partial result may be incomplete."
            )
        for b in boards:
            # Some upstreams return the same code under multiple types
            # (rare but possible). Keep the first occurrence so the
            # response is deterministic and the per-type cache slots
            # stay internally consistent.
            code = b.get("code")
            if not code or code in seen_codes:
                if code in seen_codes:
                    logger.debug(
                        f"[BoardCache] dropping duplicate code '{code}' "
                        f"under source='{source}' (kept first occurrence)"
                    )
                continue
            seen_codes.add(code)
            combined.append(b)

    if origins == {"persistence"}:
        summary = "persistence"
    elif "persistence" in origins:
        # Some types cache-hit, some fetcher-hit — the multi-source
        # summary in get_stock_memberships uses the same label.
        summary = "mixed"
    else:
        # All fresh from one (or more) fetchers — collapse to the single
        # fetcher name. The current Manager dispatches by source so a
        # single name is accurate; "mixed" would also be correct but
        # hides the actual fetcher identity from clients.
        summary = next(iter(origins))

    return combined, summary


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
    #
    # Phase 4 (2026-07-02): capture the cached board_type and pass it
    # through. Previously we warmed the cache but discarded the result,
    # letting EastMoneyFetcher.get_board_stocks silently fall back to
    # the OPPOSITE board kind when concept returned [] from a transient
    # upstream failure (bug). Now: known board_type → direct dispatch,
    # no fallback.
    _board_type_entry = resolve_board_types([board_code], source).get(board_code)
    board_type = _board_type_entry["type"] if _board_type_entry else None
    stocks, fetcher_source = manager.get_board_stocks(
        board_code,
        source=source,
        include_quote=include_quote,
        board_type=board_type,
    )

    if stocks:
        # Cold-fill: persists stocks to stock_board_membership via the
        # single-write update_cached_board_stocks helper.
        update_cached_board_stocks(board_code, source, stocks)
        logger.info(f"[BoardCache] Refreshed {len(stocks)} stocks for board {board_code}/{source}")

    return stocks, fetcher_source


def resolve_board_types(
    codes: list[str],
    source: str,
) -> dict[str, dict[str, str | None]]:
    """Look up authoritative ``board_type`` / ``subtype`` for a batch of codes.

    Single source of truth for cross-layer type resolution. EastMoney's
    push2.slist/get reverse endpoint (used by ``get_stock_boards``) cannot
    distinguish concept / industry / region / index — every row has
    ``f152=2`` — so the fetcher hardcodes ``"industry"`` and relies on this
    helper to recover the true classification. The persistence layer's
    cold-fill path (``upsert_membership_for_stock_boards``) calls the same
    helper so the SQL and column projection live in exactly one place.

    Args:
        codes: Board codes (e.g. ``["BK0438", "BK0615"]``). Empty list is a no-op.
        source: Data source slug (``"eastmoney"`` / ``"zhitu"`` / ``"zzshare"``).

    Returns:
        ``{code: {"type": str | None, "subtype": str | None}}`` for codes
        present in the ``stock_board`` cache. Codes absent from the table are
        simply not in the result; callers should default-fill.
    """
    if not codes:
        return {}
    init_schema()
    conn = get_connection()
    cursor = conn.cursor()
    placeholders = ",".join("?" * len(codes))
    cursor.execute(
        f"""SELECT code, board_type, subtype FROM stock_board
            WHERE code IN ({placeholders})
              AND source = ?""",
        (*codes, source),
    )
    return {
        row["code"]: {"type": row["board_type"], "subtype": row["subtype"]}
        for row in cursor.fetchall()
    }


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

    Used by the zhitu/eastmoney cold paths in `/stocks/{code}/boards` to
    write the reverse-index rows for every board returned by the fetcher
    in one executemany call. Each input board dict must have keys:
    code, name, type, subtype.

    **board_type override**: For EastMoneyFetcher specifically, the
    upstream push2.slist/get endpoint returns ``f152=2`` for every board
    (concept, industry, region, index — all the same), so the fetcher
    hardcodes ``"industry"``. To recover the true type (e.g. BK0615
    中药概念 is ``concept``, not ``industry``), we look up the
    authoritative ``board_type`` from the local ``stock_board`` table
    (which is populated by the board-list refresh path) and override
    the fetcher's value when the board_code is known there. Boards
    absent from ``stock_board`` keep the fetcher's value.

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

        # board_type/subtype override: look up authoritative values from
        # stock_board for the codes in this batch. The single-code variant
        # (zhitu fetcher returns type/subtype directly from upstream) hits
        # an empty dict here, so we skip the row-wise override below.
        board_codes = [b["code"] for b in boards if b.get("code")]
        type_overrides = resolve_board_types(board_codes, source)

        rows = [
            (
                b["code"],
                source,
                stock_code,
                stock_name,
                b.get("name", ""),
                (type_overrides.get(b["code"], {})).get("type") or b.get("type", ""),
                (type_overrides.get(b["code"], {})).get("subtype") or b.get("subtype"),
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


def _read_membership_entries(
    stock_code: str, sources: list[str], cursor
) -> tuple[list[dict], set[str]]:
    """Read membership rows for a stock from the given sources. Returns (entries, present_sources)."""
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
    entries = [
        {
            "code": r["board_code"],
            "name": r["board_name"],
            "type": r["board_type"],
            "subtype": r["subtype"] or "",
            "source": r["source"],
        }
        for r in raw_rows
    ]
    present_sources = {r["source"] for r in raw_rows}
    return entries, present_sources


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
    type/subtype filters, and (optionally) triggers zhitu / eastmoney
    cold-fill for sources with no data when cold_fill=True.

    Args:
        stock_code: 6-digit stock code (e.g. '600519').
        sources: list of normalized source names (no 'ths' alias; caller
                 must remap 'ths' → 'zzshare' before calling). May be empty.
        type: optional board type filter (concept/industry/index/special).
        subtype: optional source-specific subtype filter.
        cold_fill: if True and source='zhitu' / 'eastmoney' has no data, call
                   the corresponding fetcher to populate membership (write-through
                   upsert). Other sources never trigger cold-fill (no upstream API).
        manager: DataFetcherManager instance. Required when cold_fill=True.

    Returns:
        (entries, cold_sources, origin_summary)
        - entries: list of {code, name, type, subtype, source}, one dict per row.
        - cold_sources: subset of `sources` with no data after cold_fill attempt.
        - origin_summary:
            - "persistence" — entries from SQLite cache (no fetcher calls); also used
                              when entries is empty (cache miss, no cold-fill)
            - "zhitu" / "eastmoney" — cold-fill triggered and that source is now in the
                              result (network was hit, fresh data was written). When
                              both cold-fill sources wrote, the single-source summary
                              reflects whichever source was actually queried.
            - "mixed"       — multi-source query with entries (no cold-fill happened)
            - ""            — sources was empty (early return)

    Caller decides how to expose origin_summary in the top-level response
    source field (single-source: pass-through; multi-source: override with 'merged').
    """
    init_schema()

    if not sources:
        return [], [], ""

    conn = get_connection()
    cursor = conn.cursor()

    entries, present_sources = _read_membership_entries(stock_code, sources, cursor)

    # Cold-fill: zhitu and eastmoney have upstream reverse APIs; only when cold_fill=True.
    if cold_fill and manager is not None:
        from .stock_list import get_stock_name as _get_stock_name

        for cold_src in ("zhitu", "eastmoney"):
            if cold_src not in sources or cold_src in present_sources:
                continue
            boards, _ = manager.get_stock_boards(stock_code, source=cold_src)
            if boards:
                stock_name = _get_stock_name(stock_code) or ""
                upsert_membership_for_stock_boards(
                    stock_code=stock_code,
                    stock_name=stock_name,
                    boards=boards,
                    source=cold_src,
                )
                # Re-read to include newly written rows
                entries, present_sources = _read_membership_entries(
                    stock_code, sources, cursor
                )

    # Apply type/subtype filters (post-query, in-memory)
    if type is not None:
        entries = [e for e in entries if e["type"] == type]
    if subtype is not None:
        entries = [e for e in entries if e["subtype"] == subtype]

    # Cold sources = requested but not present
    cold_sources = [s for s in sources if s not in present_sources]

    # Origin summary
    if not entries:
        origin_summary = "persistence"
    elif cold_fill and manager is not None:
        # Cold-fill actually wrote data; signal which source(s) hit the network.
        # Single-source query takes the queried source's name; multi-source uses "mixed".
        coldfill_sources = {"zhitu", "eastmoney"} & {e["source"] for e in entries}
        if coldfill_sources and len(sources) == 1:
            origin_summary = next(iter(coldfill_sources))
        elif coldfill_sources or len(sources) > 1:
            origin_summary = "mixed"
        else:
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

    Returns:
        Each row is projected with the key ``type`` (= SQL column
        ``board_type``) so callers can use the same key for fresh fetcher
        rows and cache-hit rows. ``board_type`` is also retained as an
        alias for any caller that was using the column name directly.
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
            "type": row["board_type"],
            # Keep ``board_type`` for backwards compat with any caller that
            # was using the SQL column name directly.
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
