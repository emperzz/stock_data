"""
SQLite persistence for stock board (concept/industry) data.

Provides persistent storage for board listing data to avoid repeated
upstream API calls which are slow and may fail.
"""

import logging
import sqlite3
from datetime import datetime
from typing import Any

from ..base import DataFetchError
from . import db
from ._refresh import DailyRefreshTracker
from .db import get_connection, get_db_path

logger = logging.getLogger(__name__)

_refresh_tracker = DailyRefreshTracker()
_schema_initialized_paths: set[str] = set()

# Canonical subtype names per source. Single source of truth so the persistence
# validator and the fetcher write path cannot drift (cold-fill writes fetcher
# output verbatim — if either side renames the literal, the validator on the
# inbound query rejects valid queries). Both `ths` and `zzshare` produce the
# same Chinese label because zzshare's plates_list upstream is itself THS.
THS_CONCEPT_SUBTYPE = "同花顺概念"
THS_INDUSTRY_SUBTYPE = "同花顺行业"
THS_SPECIAL_SUBTYPE = "同花顺题材"

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
        "industry": {THS_INDUSTRY_SUBTYPE},
        # Both plate=15 (概念) and plate=17 (题材) collapse to type=concept;
        # subtype retains the original label so callers can filter 概念 vs 题材.
        "concept": {THS_CONCEPT_SUBTYPE, THS_SPECIAL_SUBTYPE},
        # "index" — zzshare 不暴露大盘指数板块
        # "special" — zzshare 的"题材"已在 concept 下承载 (plate=17),
        #             不再有独立的 special 类型
    },
    "ths": {  # stock-boards 专用 (THS basic API 仅返回 concept); 行业 / 概念
              # 前向 board 清单由 ThsFetcher.get_all_boards 提供 (2026-07-08).
        "concept": {THS_CONCEPT_SUBTYPE},
        "industry": {THS_INDUSTRY_SUBTYPE},
        # special / index 暂不支持
    },
}

# Valid board types and sources — forward-board listings (board-list,
# board-stocks, build_membership_index). NOT derived from
# VALID_SUBTYPES_BY_SOURCE because 'ths' now lives in BOTH places:
# - stock-boards reverse lookup (basic.10jqka.com.cn stock_concept_list)
# - forward board listing (ThsFetcher.get_all_boards, 2026-07-08)
# Forward-board sources are exactly the set with a get_all_boards
# implementation.
VALID_BOARD_TYPES: tuple[str, ...] = ("concept", "industry", "index", "special")
# Forward-board sources: each must have BOTH get_all_boards AND
# get_board_stocks implementations. 'ths' satisfies both since
# ThsFetcher.get_all_boards landed (2026-07-08).
VALID_SOURCES: tuple[str, ...] = ("ths", "eastmoney", "zhitu")


# Stock-boards 专用 source 集合 + alias (仿照 _BOARD_HISTORY_VALID_SOURCES 模式).
# stock-boards 端点 alias zzshare→ths: THS basic API 是真正的 stock→boards 上游;
# zzshare SDK 没有这个端点. (board-list 端点不 alias 任何方向 — 'ths' 与
# 'zzshare' 各自独立,因为 ThsFetcher 已实现 get_all_boards — 2026-07-08.)
# 注意: 'ths' 在 VALID_SUBTYPES_BY_SOURCE 里有 concept subtype (用于 stock-boards
# 端点的 subtype 验证), 但不在 VALID_SOURCES 里 (因为它没有 get_all_boards).
_STOCK_BOARDS_VALID_SOURCES: tuple[str, ...] = ("ths", "eastmoney", "zhitu")
_STOCK_BOARDS_SOURCE_ALIAS: dict[str, str] = {"zzshare": "ths"}


# Board-stocks 专用 source 集合 (no alias map — all 4 sources are
# independently valid). Mirrors the existing _STOCK_BOARDS_VALID_SOURCES
# pattern from the stock-boards endpoint. The route layer's
# _resolve_board_stocks_source uses this to decide whether to accept
# ?source=ths as canonical (was previously aliased to zzshare).
_BOARD_STOCKS_VALID_SOURCES: tuple[str, ...] = (
    "ths", "eastmoney", "zhitu"
)


def normalize_board_stocks_source(source: str) -> str:
    """Validate a source name for the board-stocks endpoint.

    Unlike ``normalize_stock_board_source`` (which aliases
    ``zzshare → ths``), this helper does NOT alias. All four sources
    have independent ``get_board_stocks`` implementations:

    - ``ths``: ThsFetcher (q.10jqka.com.cn AJAX — concept boards)
    - ``eastmoney``: EastMoneyFetcher (push2his)
    - ``zhitu``: ZhituFetcher
    - ``zzshare``: ZzshareFetcher (``plates_stocks``) — preserved for
      back-compat; upstream IS 同花顺 but routed through the zzshare SDK

    Args:
        source: User-supplied source name (e.g. ``"ths"``).

    Returns:
        The same string (no transformation).

    Raises:
        ValueError: ``source`` is not in the valid set. Caller (route
            layer) maps this to ``HTTPException(400)``.
    """
    if source not in _BOARD_STOCKS_VALID_SOURCES:
        raise ValueError(
            f"Unknown board-stocks source {source!r}. "
            f"Valid sources: {list(_BOARD_STOCKS_VALID_SOURCES)}"
        )
    return source


def normalize_stock_board_source(source: str) -> str:
    """Alias + validate a source name for the stock-boards endpoint.

    Applies the stock-boards alias map (zzshare → ths) and validates
    against _STOCK_BOARDS_VALID_SOURCES. The board-list endpoint
    has no aliasing in either direction (both ``ths`` and ``zzshare``
    are first-class labels as of 2026-07-08); see
    ``boards.py:_parse_source_csv``.

    Args:
        source: User-supplied source name (e.g. ``"ths"``, ``"zzshare"``).

    Returns:
        Canonical source name accepted by the persistence layer.

    Raises:
        ValueError: ``source`` is not in the valid set after aliasing.
            Caller (route layer) maps this to ``HTTPException(400)``.
    """
    s = _STOCK_BOARDS_SOURCE_ALIAS.get(source, source)
    if s not in _STOCK_BOARDS_VALID_SOURCES:
        raise ValueError(
            f"Unknown stock-boards source {source!r}. "
            f"Valid sources: {list(_STOCK_BOARDS_VALID_SOURCES)} "
            f"(alias 'zzshare' accepted)"
        )
    return s


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


def _validate_type_for_source(source: str, board_type: str) -> None:
    """Validate ``board_type`` against the source's declared type set.

    Independent of :func:`_validate_subtype` (which returns early when no
    subtype is given). Without this guard, a query like
    ``?source=zzshare&type=special`` would slip through ``_validate_subtype``
    — subtype is None so the early return fires — and reach the fetcher
    where ``get_all_boards`` would iterate ``_BOARD_TYPE_BY_PLATE_TYPE``
    without matching any item, silently returning ``[]`` with HTTP 200.

    The 2026-07-07 unification removed zzshare's ``special`` slot (plate=17
    题材 folded into ``concept``); this helper makes that contract explicit
    at the route boundary so callers get a 400 with a useful error message
    instead of a silent empty response.

    Args:
        source: data source name (e.g. ``"zzshare"``).
        board_type: ``concept / industry / index / special``.

    Raises:
        ValueError: source unknown or ``board_type`` not in the source's
            declared type set. The error message lists the source's
            supported types so callers can adjust their query.
    """
    source_table = VALID_SUBTYPES_BY_SOURCE.get(source)
    if source_table is None:
        raise ValueError(
            f"Unknown source '{source}'. Known sources: {sorted(VALID_SUBTYPES_BY_SOURCE.keys())}"
        )
    if board_type not in source_table:
        raise ValueError(
            f"Invalid type '{board_type}' for source '{source}'. "
            f"Valid types for {source}: {sorted(source_table.keys())}. "
            f"Note: zzshare's plate_type=17 (题材) was unified under "
            f"type=concept with subtype='同花顺题材' on 2026-07-07; use "
            f"type=concept&subtype=同花顺题材 instead of type=special."
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
    # Board list table — metadata only; realtime quotes come from API.
    # `platecode` is the cross-source join key (THS industry `code` is itself
    # the platecode; THS concept has separate `code` (cid) + `platecode`
    # (885xxx used by d.10jqka.com.cn/v4/line/bk_{platecode}/). NULL for
    # sources that don't expose it (eastmoney / zhitu).
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS stock_board (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL,
            name TEXT NOT NULL,
            board_type TEXT NOT NULL,
            subtype TEXT,
            source TEXT NOT NULL,
            platecode TEXT,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(code, source)
        )
    """)
    # Forward-compat ALTER for pre-2026-07-08 databases (added platecode
    # column to stock_board alongside ThsFetcher.get_all_boards). Idempotent
    # — when the column already exists, the ALTER errors with
    # "duplicate column name" which we swallow. Per the user's note this is
    # a dev project; we don't run a full backfill — rows written before this
    # change keep platecode=NULL until their next daily refresh.
    _add_platecode_column_if_missing(cursor)
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

    # One-time data migration: unify zzshare plate=17 (题材) into type=concept
    # alongside plate=15 (概念). The subtype "同花顺题材" is preserved so callers
    # can still differentiate 概念 vs 题材. Idempotent — second run is a no-op
    # because the WHERE clause no longer matches any rows.
    _migrate_zzshare_special_to_concept(cursor)
    conn.commit()


def _add_platecode_column_if_missing(cursor) -> None:
    """Ensure the ``stock_board.platecode`` column exists.

    Added 2026-07-08 alongside ThsFetcher.get_all_boards. New databases get
    the column via the CREATE TABLE statement in init_schema; pre-existing
    databases get it via ALTER. Swallows the "duplicate column" error so
    re-running init_schema on a current schema is a no-op.
    """
    cursor.execute("PRAGMA table_info(stock_board)")
    cols = {row["name"] for row in cursor.fetchall()}
    if "platecode" in cols:
        return
    try:
        cursor.execute("ALTER TABLE stock_board ADD COLUMN platecode TEXT")
        logger.info("[BoardCache] added stock_board.platecode column (forward-compat migration)")
    except sqlite3.OperationalError as e:
        # "duplicate column name" — already added by a concurrent process.
        # Safe to ignore.
        if "duplicate column" not in str(e):
            raise


def _migrate_zzshare_special_to_concept(cursor) -> None:
    """Rewrite zzshare ``special`` rows to ``concept`` (2026-07-07 redesign).

    Background: zzshare's ``plate_type`` enumeration is ``14=行业 / 15=概念 /
    17=题材``. Server-side the 15 and 17 buckets are unified under ``concept``
    because their membership is the same shape (concept-style grouping) — the
    only thing the 17 bucket adds is a Chinese label distinguishing "题材" from
    "概念", which we keep on ``subtype`` (``同花顺题材`` vs ``同花顺概念``).

    The fetcher now writes the new mapping on every refresh, but rows that
    were cached BEFORE the change still sit in SQLite with the old shape.
    This migration rewrites both the ``stock_board`` metadata table and the
    ``stock_board_membership`` reverse index in a single pass per init.
    Safe to run repeatedly; the WHERE clause excludes already-migrated rows.
    """
    for table in ("stock_board", "stock_board_membership"):
        before = cursor.execute(
            f"SELECT COUNT(*) AS n FROM {table} "
            "WHERE source = 'zzshare' AND board_type = 'special' "
            "AND subtype = ?",
            (THS_SPECIAL_SUBTYPE,),
        ).fetchone()["n"]
        if before == 0:
            continue
        cursor.execute(
            f"UPDATE {table} SET board_type = 'concept' "
            "WHERE source = 'zzshare' AND board_type = 'special' "
            "AND subtype = ?",
            (THS_SPECIAL_SUBTYPE,),
        )
        logger.info(
            f"[BoardCache] migrated {cursor.rowcount} zzshare/special→concept "
            f"rows in {table} (subtype='{THS_SPECIAL_SUBTYPE}' preserved)"
        )


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

    Used by the ths / zhitu / eastmoney cold paths in `/stocks/{code}/boards` to
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
    type/subtype filters, and (optionally) triggers ths / zhitu / eastmoney
    cold-fill for sources with no data when cold_fill=True.

    Args:
        stock_code: 6-digit stock code (e.g. '600519').
        sources: list of canonical source names (route layer normalizes
                 'zzshare' → 'ths' before calling, so 'ths' appears here
                 when the caller used either label). May be empty.
        type: optional board type filter (concept/industry/index/special).
        subtype: optional source-specific subtype filter.
        cold_fill: if True and source='ths' / 'zhitu' / 'eastmoney' has no data,
                   call the corresponding fetcher to populate membership
                   (write-through upsert). Other sources never trigger cold-fill.
        manager: DataFetcherManager instance. Required when cold_fill=True.

    Returns:
        (entries, cold_sources, origin_summary)
        - entries: list of {code, name, type, subtype, source}, one dict per row.
        - cold_sources: subset of `sources` with no data after cold_fill attempt.
        - origin_summary:
            - "persistence" — entries from SQLite cache (no fetcher calls); also used
                              when entries is empty (cache miss, no cold-fill)
            - "cold_fill_empty" — cold_fill=True was attempted, fetcher was queried,
                              but returned no rows for any cold-fill source. Distinct
                              from "persistence" so the route layer doesn't mislead
                              users into thinking the network was never hit
                              (e.g. 北交所 early-return case for source=ths).
            - "ths" / "zhitu" / "eastmoney" — cold-fill triggered and that source is
                              now in the result (network was hit, fresh data was
                              written). When multiple cold-fill sources wrote, the
                              single-source summary reflects whichever source was
                              actually queried; multi-source collapses to "mixed".
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

    # Cold-fill: ths / zhitu / eastmoney have upstream reverse APIs; only when cold_fill=True.
    # Track which sources we ATTEMPTED to cold-fill, separately from which wrote rows —
    # used downstream to distinguish "fetcher returned empty" from "cache miss".
    coldfill_attempted: set[str] = set()
    if cold_fill and manager is not None:
        from .stock_list import get_stock_name as _get_stock_name

        for cold_src in ("ths", "zhitu", "eastmoney"):  # ths 加首位 (新实现)
            if cold_src not in sources or cold_src in present_sources:
                continue
            coldfill_attempted.add(cold_src)
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
        # Empty entries: distinguish "cache miss, no cold-fill" from
        # "cold-fill attempted but fetcher returned []". The latter case
        # (e.g. BSE stock queried via source=ths, where the fetcher
        # early-returns without hitting upstream) would otherwise look
        # identical to a clean cache miss.
        if coldfill_attempted:
            origin_summary = "cold_fill_empty"
        else:
            origin_summary = "persistence"
    elif cold_fill and manager is not None:
        # Cold-fill actually wrote data; signal which source(s) hit the network.
        # Single-source query takes the queried source's name; multi-source uses "mixed".
        coldfill_sources = {"ths", "zhitu", "eastmoney"} & {e["source"] for e in entries}
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


def get_board_name_with_fallback(
    board_code: str,
    source: str,
    manager: Any | None = None,
) -> str | None:
    """Resolve a board's name with cache-first, fetcher-fallback strategy.

    Fast path: read from SQLite cache (no upstream call) — see
    :func:`get_board_name` for the cold-cache behaviour.

    Slow path: when the cache is cold and ``manager`` is provided,
    ask the fetcher by calling ``manager.get_all_boards`` for each
    board type until the target board is found. This consolidates the
    loop + exception handling that previously lived in the route layer
    (review 2026-07-06 finding #10, CLAUDE.md Persistence-Only Routing).

    Non-fatal failures are swallowed silently (logged at DEBUG):

    - ``DataFetchError``: fetcher's own network/auth failure
    - ``ValueError``: manager._with_source rejected unknown source /
      market / capability
    - ``AttributeError``: fetcher doesn't implement ``get_all_boards``
      (e.g. ThsFetcher — has STOCK_BOARD capability for
      ``get_board_stocks`` but no ``get_all_boards`` method; manager
      calls the missing method directly)

    The route layer treats all three as "fall back to bare board_code"
    rather than 5xx.

    Args:
        board_code: Board code (e.g. ``"BK1048"``).
        source: Data source slug (``"eastmoney"``, ``"ths"``, etc.).
        manager: Optional :class:`DataFetcherManager` instance. When
            ``None``, the slow path is skipped entirely.

    Returns:
        The board name if found in cache or via fetcher, else ``None``.
    """
    cached = get_board_name(board_code, source)
    if cached:
        return cached
    if manager is None:
        return None
    try:
        for bt in ("concept", "industry"):
            boards, _ = manager.get_all_boards(
                source=source,
                board_type=bt,
                subtype=None,
            )
            match = next((b["name"] for b in boards if b["code"] == board_code), None)
            if match:
                return match
    except (DataFetchError, ValueError, AttributeError) as e:
        logger.debug(
            f"[BoardCache] board-name fallback for {board_code} "
            f"(source={source}): {type(e).__name__}: {e}"
        )
    return None


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
            """SELECT code, name, board_type, subtype, source, platecode, updated_at
               FROM stock_board WHERE board_type = ? AND source = ? ORDER BY name""",
            (board_type, source),
        )
    else:
        cursor.execute(
            """SELECT code, name, board_type, subtype, source, platecode, updated_at
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
            "platecode": row["platecode"],
            "updated_at": row["updated_at"],
        }
        for row in rows
    ]


def _read_board_stocks_from_db(board_code: str, source: str) -> list[dict[str, Any]]:
    """Read board-stock list from membership table.

    Filters out stale rows whose stock_code is not a valid A-share 6-digit
    code. Stale rows can be left behind by upstream field-code reshuffles
    (e.g. review 2026-07-06 finding #2: pre-fix EastMoney stored
    stock_code=Chinese name from f14). Without this filter, cache hits
    would emit corrupt BoardStockInfo (code='贵州茅台') until the
    calendar-day boundary lets the now-correct fetcher rewrite them.

    Defence-in-depth: a regex check on read is cheap, and protects against
    future upstream bugs that may write non-canonical stock_code values.
    Rows that fail the check are skipped silently at DEBUG level — they
    remain in the table until the next fetcher pass overwrites them.
    """
    out: list[dict[str, Any]] = []
    for r in read_membership(board_code=board_code, source=source):
        code = r["stock_code"]
        if not _is_valid_stock_code(code):
            logger.debug(
                f"[BoardCache] skipping stale membership row: "
                f"board={board_code} source={source} stock_code={code!r}"
            )
            continue
        out.append(
            {
                "stock_code": code,
                "stock_name": r["stock_name"],
                "updated_at": r["refreshed_at"],
            }
        )
    return out


# A-share canonical stock_code shape: 6 ASCII digits. Matches SH (6xxxxx,
# 688xxx), SZ (0xxxxx, 300xxx), BJ (4xxxxx, 8xxxxx). HK (HK00700) and US
# (AAPL) are NOT in board-stock membership — the boards endpoint is
# A-share-only. See utils/normalize.py for the canonical normaliser.
_VALID_STOCK_CODE = __import__("re").compile(r"^\d{6}$")


def _is_valid_stock_code(code: Any) -> bool:
    """True iff ``code`` matches the A-share canonical 6-digit pattern.

    Centralised here so future board endpoints (e.g. /boards with new
    sources) can reuse the check. Non-strings and empty strings fail.
    """
    if not isinstance(code, str) or not code:
        return False
    return bool(_VALID_STOCK_CODE.match(code))


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
                (code, name, board_type, subtype, source, platecode, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        b["code"],
                        b["name"],
                        board_type,
                        b.get("subtype") or "",
                        source,
                        b.get("platecode"),
                        now,
                    )
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
