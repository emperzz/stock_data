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
        # "index" — EastMoneyFetcher.get_all_boards returns [] for index
        #            (no upstream board-index classification). Declaring
        #            it here previously let requests through the route
        #            validator and silently return 200 with an empty list
        #            at the fetcher; the route layer now 400s instead.
        # "special" — same: EastMoneyFetcher.get_all_boards returns [].
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
# zzshare SDK 没有这个端点. (board-list 端点 2026-07-08 后 zzshare 不再合法 —
# source=zzshare 由 FastAPI Literal 校验返回 422,不再 alias;reverse-lookup
# 的 zzshare→ths alias 继续生效.)
# 注意: 'ths' 在 VALID_SUBTYPES_BY_SOURCE 里有 concept subtype (用于 stock-boards
# 端点的 subtype 验证), 但不在 VALID_SOURCES 里 (因为它没有 get_all_boards).
_STOCK_BOARDS_VALID_SOURCES: tuple[str, ...] = ("ths", "eastmoney", "zhitu")
_STOCK_BOARDS_SOURCE_ALIAS: dict[str, str] = {"zzshare": "ths"}


# Board-stocks 专用 source 集合 (3 sources — ths/eastmoney/zhitu).
# Post-2026-07-08 unification dropped `zzshare` from the public surface;
# zzshare is no longer valid here (Literal returns 422), but the
# underlying ZzshareFetcher.plates_stocks is still used internally by
# fetch_board_stocks_with_zzshare_fallback for the include_quote=False
# primary path.
_BOARD_STOCKS_VALID_SOURCES: tuple[str, ...] = ("ths", "eastmoney", "zhitu")


def normalize_board_stocks_source(source: str) -> str:
    """Validate a source name for the board-stocks endpoint.

    Unlike ``normalize_stock_board_source`` (which aliases
    ``zzshare → ths``), this helper does NOT alias. Public surface
    accepts the three source labels whose fetcher owns the route:

    - ``ths``: ThsFetcher (q.10jqka.com.cn AJAX — concept boards)
    - ``eastmoney``: EastMoneyFetcher (push2his)
    - ``zhitu``: ZhituFetcher

    ``zzshare`` is *internal only* (post-2026-07-08 unification): no
    longer a public label. It's invoked transparently by
    ``fetch_board_stocks_with_zzshare_fallback`` as a *fallback* for
    ``source='ths'`` + ``include_quote=False`` requests — see that
    helper's docstring for the routing rules.

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
    are first-class labels as of 2026-07-08).

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
    # `code` is the cross-source public board identifier (THS concept/industry
    # platecode 885xxx/881xxx, eastmoney BKxxxx, zhitu sw_xxx); `cid` is the
    # THS-internal concept cid (3xxxxx) — NULL for industry/eastmoney/zhitu
    # rows. Pre-2026-07-20 schema had `code` storing the THS concept cid and a
    # separate `platecode` column storing the public code; the migration
    # below unifies them so `code` always means the cross-source public id.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS stock_board (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL,
            name TEXT NOT NULL,
            board_type TEXT NOT NULL,
            subtype TEXT,
            source TEXT NOT NULL,
            cid TEXT,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(code, source)
        )
    """)
    # Forward-compat migration for pre-2026-07-20 databases:
    # old schema had `code` (cid) + `platecode` (public code). Rebuild the
    # table so `code` uniformly means the public board identifier and `cid`
    # stores the THS-internal cid (NULL for non-THS rows). Idempotency is
    # via the PRAGMA table_info early-return inside the migration function;
    # see _migrate_stock_board_to_code_cid's docstring.
    _migrate_stock_board_to_code_cid(cursor)
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


def _migrate_stock_board_to_code_cid(cursor) -> None:
    """Migrate pre-2026-07-20 ``stock_board`` rows from ``(code, platecode)``
    to the new unified schema of ``(code, cid)``.

    Pre-2026-07-20 schema:
      - ``code``     = THS concept CID (3xxxxx) or industry platecode (881xxx)
                        or eastmoney BKxxxx / zhitu sw_xxx
      - ``platecode`` = THS public code (885xxx for concept, == code for industry)

    New schema:
      - ``code`` = cross-source public board identifier (THS platecode /
                   eastmoney BKxxxx / zhitu sw_xxx / …)
      - ``cid``  = THS-internal concept CID (3xxxxx), NULL for others

    Migration strategy: rebuild the table (the rename gymnastics via
    ``ALTER TABLE RENAME COLUMN`` hit the column-name collision; rebuild is
    simpler and runs once).

    Idempotency: the function early-returns when the table is already in
    the new schema (``not has_platecode and has_cid``), so a second run
    against an up-to-date DB is a no-op. We deliberately don't use the
    ``PRAGMA user_version`` route here — the migration is cheap, and the
    in-place early-return check is sufficient.
    """
    cursor.execute("PRAGMA table_info(stock_board)")
    cols = {row["name"] for row in cursor.fetchall()}
    has_platecode = "platecode" in cols
    has_cid = "cid" in cols

    # New schema already in place (new DB or post-migration DB).
    if not has_platecode and has_cid:
        return

    # Old schema detected — the column name `platecode` is the signature.
    # Detect THS concept rows by (source='ths') AND (platecode NOT NULL) — those
    # are the rows where old `code` actually held a 3xxxxx cid. THS industry rows
    # have platecode == code (no separate cid), so we don't bump cid for them.
    if has_platecode:
        n_rows = cursor.execute("SELECT COUNT(*) AS n FROM stock_board").fetchone()["n"]
        # Pre-existing duplicates: legacy data can have two rows for the same
        # (platecode='885940', source='ths') — one with code=cid (308791)
        # and one with code=platecode (885940). After renaming platecode→code
        # both would collide on the new UNIQUE(code, source). De-duplicate
        # BEFORE inserting into the new table: for each (platecode, source)
        # tuple, prefer the row whose old `code` differs from `platecode`
        # (i.e. the cid-bearing row). Drop the redundant duplicate.
        cursor.execute("""
            CREATE TABLE stock_board_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL,
                name TEXT NOT NULL,
                board_type TEXT NOT NULL,
                subtype TEXT,
                source TEXT NOT NULL,
                cid TEXT,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(code, source)
            )
        """)
        # De-duplicate: keep one row per (code, source) AFTER migration.
        # Strategy: score each row by how informative it is:
        #   - THS concept rows where `code` differs from `platecode` (i.e.
        #     `code` holds a real cid) score HIGHEST — they're the only
        #     rows we can extract a `cid` from.
        #   - Rows where `code` == `platecode` (THS industry, or legacy
        #     THS concept bad rows) score next.
        #   - Rows where `platecode IS NULL` (EastMoney / Zhitu) score
        #     next; old `code` becomes the new `code`.
        # Per (platecode-or-code, source) group we keep the row with the
        # LOWEST score, breaking ties by lowest id (oldest write wins).
        cursor.execute("""
            INSERT INTO stock_board_new
                (id, code, name, board_type, subtype, source, cid, updated_at)
            SELECT
                id,
                COALESCE(platecode, code)              AS code,
                name,
                board_type,
                subtype,
                source,
                CASE
                    WHEN source = 'ths'
                     AND platecode IS NOT NULL
                     AND platecode != code
                    THEN code
                    ELSE NULL
                END                                    AS cid,
                updated_at
            FROM stock_board
            WHERE id IN (
                SELECT id FROM (
                    SELECT
                        id,
                        ROW_NUMBER() OVER (
                            PARTITION BY
                                COALESCE(platecode, code),
                                source
                            ORDER BY
                                -- score 0 = THS concept with real cid
                                --        (code != platecode AND platecode NOT NULL)
                                -- score 1 = THS industry / legacy duplicates
                                --        (code == platecode)
                                -- score 2 = EastMoney / Zhitu (no platecode)
                                CASE
                                    WHEN platecode IS NOT NULL AND code != platecode THEN 0
                                    WHEN platecode IS NOT NULL AND code = platecode  THEN 1
                                    ELSE 2
                                END,
                                id
                        ) AS rn
                    FROM stock_board
                )
                WHERE rn = 1
            )
        """)
        cursor.execute("DROP TABLE stock_board")
        cursor.execute("ALTER TABLE stock_board_new RENAME TO stock_board")
        n_after = cursor.execute("SELECT COUNT(*) AS n FROM stock_board").fetchone()["n"]
        logger.info(
            f"[BoardCache] migrated stock_board to unified (code, cid) schema "
            f"({n_rows} -> {n_after} rows; de-duplicated {n_rows - n_after} legacy "
            f"duplicate (platecode, source) tuples; old platecode -> new code, "
            f"old code -> new cid for THS concept rows)"
        )

    # Ensure `cid` column exists in any case (covers the rare "no platecode
    # but no cid" path that shouldn't happen on dev box but is safe).
    cursor.execute("PRAGMA table_info(stock_board)")
    cols = {row["name"] for row in cursor.fetchall()}
    if "cid" not in cols:
        try:
            cursor.execute("ALTER TABLE stock_board ADD COLUMN cid TEXT")
            logger.info("[BoardCache] added stock_board.cid column (forward-compat migration)")
        except sqlite3.OperationalError as e:
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
    source: str = "ths",
    refresh: bool = False,
    include_quote: bool = False,
    subtype: str | None = None,
    manager=None,
) -> tuple[list, str]:
    """Get board list with automatic refresh.

    Source routing:
    - ``source='ths'`` → fetch from ThsFetcher + ZzshareFetcher (merge by
      name, cache as source='ths'). This is the default and the only source
      that internally combines two fetchers.
    - ``source='eastmoney'`` / ``source='zhitu'`` → fetch directly from
      the corresponding fetcher via ``manager.get_all_boards``. Cache
      writes use the source name.

    Cache policy:
    - No local cache → fetch from upstream and write to cache.
    - First call of the day → force refresh.
    - refresh=True → force refresh.
    - include_quote=True → always fetch fresh data from upstream.
    - Otherwise → return cached data.

    Args:
        board_type: one of "concept" / "industry" / "index" / "special", or
            ``None`` to query every type the source exposes
            (e.g. ths → concept + industry; eastmoney → concept + industry).
        source: data source name (``"ths"`` / ``"eastmoney"`` / ``"zhitu"``).
            Must be pre-validated by the route layer via ``_resolve_source``.
        refresh: If True, force refresh from upstream.
        include_quote: If True, include realtime price/change/market data and skip cache.
        subtype: optional source-specific subtype filter.
        manager: DataFetcherManager instance. Required when fetching from upstream.

    Returns:
        Tuple of (boards, origin) where origin is:
          - "persistence" when data was read from the SQLite cache
          - source name (e.g. "ths", "eastmoney", "zhitu") when freshly fetched
        List of board dicts: [{"code", "name", "type", "subtype", "source", ...}, ...]
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

    if manager is None:
        raise ValueError("manager is required when refresh=True or cache miss")

    if source == "ths":
        boards = fetch_boards_with_zzshare_backfill(
            board_type=board_type,
            refresh=refresh,
            include_quote=include_quote,
            subtype=None,
            manager=manager,
        )
    else:
        boards, _ = manager.get_all_boards(
            source=source,
            board_type=board_type,
            subtype=None,
            include_quote=include_quote,
        )

    if boards:
        update_cached_boards(board_type, source, boards)
        logger.info(f"[BoardCache] Refreshed {len(boards)} boards for {board_type}/{source}")

    if subtype is not None:
        boards = [b for b in boards if b.get("subtype") == subtype]

    return boards, source


def _get_all_board_types(
    source: str,
    refresh: bool,
    include_quote: bool,
    subtype: str | None,
    manager,
) -> tuple[list[dict], str]:
    """All-types variant of :func:`get_board_list`.

    Iterates over every board_type the given source exposes (derived
    from ``VALID_SUBTYPES_BY_SOURCE[source]``). For ``source='ths'``
    this is concept + industry; for eastmoney it's concept + industry +
    index + special; etc.

    Returns:
        ``(combined_boards, origin)`` where ``origin`` is:
          - ``"persistence"`` when every per-type call was a cache hit
          - source name when every per-type call hit the network
          - ``"mixed"`` otherwise (some types fresh, some cached)
    """
    init_schema()

    if subtype is not None:
        raise ValueError(
            "subtype filter requires a specific board_type; "
            "cross-type subtype filtering is not supported."
        )

    if manager is None:
        raise ValueError(
            "manager is required when querying all board types "
            "(cache may be partially cold and an upstream call may be needed)"
        )

    supported_types = list(VALID_SUBTYPES_BY_SOURCE.get(source, {}).keys())
    if not supported_types:
        return [], "persistence"

    combined: list[dict] = []
    seen_codes: set[str] = set()
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
        if not boards and origin != "persistence":
            logger.warning(
                f"[BoardCache] all-types query for board_type='{bt}' "
                f"source='{source}' returned 0 rows from upstream "
                f"({origin}); partial result may be incomplete."
            )
        for b in boards:
            code = b.get("code")
            if not code or code in seen_codes:
                if code in seen_codes:
                    logger.debug(
                        f"[BoardCache] dropping duplicate code '{code}' (kept first occurrence)"
                    )
                continue
            seen_codes.add(code)
            combined.append(b)

    if origins == {"persistence"}:
        summary = "persistence"
    elif "persistence" in origins:
        summary = "mixed"
    else:
        summary = next(iter(origins))  # source name

    return combined, summary


def _resolve_ths_cid_from_code(code: str) -> str | None:
    """Resolve THS cid for a given public board code via the stock_board cache.

    Single SELECT against stock_board. The same query handles both
    concept boards (cid ≠ code: 300xxx vs 885xxx) and industry
    boards (cid == code: 881xxx) — for industry the row's
    ``code`` column stores 881xxx and the ``cid`` column also stores
    881xxx (redundant). No special-casing by length or prefix; the
    data layer is the single source of truth.

    Args:
        code: THS public board code (e.g. '885642' for concept,
            '881270' for industry). Pre-2026-07-20 callers referred
            to this as the ``platecode``; the conceptual name sticks
            even though the SQLite column is ``code`` now.

    Returns:
        The THS cid (3xxxxx for concept, == code for industry),
        or None if no row matches. Callers treat None as
        "no cid available — skip ThsFetcher path, rely on zzshare".
    """
    init_schema()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT cid FROM stock_board WHERE code = ? AND source = 'ths' LIMIT 1",
        (code,),
    )
    row = cursor.fetchone()
    return row["cid"] if row else None


# Backward-compat alias — pre-2026-07-20 callers (ThsFetcher, several tests)
# imported this name. Renaming the underlying function to
# ``_resolve_ths_cid_from_code`` reflects the column rename; the old alias
# is kept so existing imports still resolve.
_resolve_ths_cid_from_platecode = _resolve_ths_cid_from_code


def _merge_ths_zzshare_by_name(
    ths_rows: list[dict],
    zzshare_rows: list[dict],
) -> list[dict]:
    """Merge THS(primary) + ZZSHARE(platecode backfill) by board name.

    Cross-source asymmetry (verified 2026-07-09): ZzshareFetcher stores
    the plate_code value under ``code`` and does NOT emit a separate
    ``platecode`` field. Earlier versions of this helper built the
    backfill index by reading ``r.get("platecode")`` on zzshare rows —
    always None — which silently disabled the backfill and caused
    412/797 rows in ``stock_board`` to be persisted with ``platecode=NULL``.
    We normalize zzshare rows to promote ``code`` → ``platecode`` here
    so the same merge logic works against real fetcher output.

    Contract:
      - Every output row carries ``platecode`` (non-NULL when a code is
        known) and ``source='ths'`` regardless of origin.
      - THS rows that already carry ``platecode`` are kept as-is.
      - THS sidebar-only rows (platecode=None) are backfilled by name
        from the matching zzshare row's ``code`` (the plate_code).
      - zzshare rows not matched by any THS row are appended; their
        ``platecode`` is set to their own ``code``.
      - Dedup by (code, name) guards against upstream double-emit
        (rare; seen once in THS gnSection duplicates 2026-07-08). This
        is a second-layer safety net behind ThsFetcher's own internal
        `_merge_concept_sources` dedup (ths_fetcher.py:1300).

    **In-place mutation**: Both input lists' dicts are mutated in place
    (``platecode`` backfilled or promoted, ``source='ths'`` set on
    every row). Callers must not reuse the input lists after this call.

    Empty input edge cases:
      - ths=[] + zz=[] → []
      - ths=[] + zz=non-empty → all zzshare rows appended
      - ths=non-empty + zz=[] → ths rows returned as-is
    """
    # ZzshareFetcher.get_all_boards does not emit a 'platecode' field —
    # its plate_code value lives under 'code' only. Promote it here so
    # the backfill index below can read r['platecode'] uniformly.
    by_name: dict[str, str] = {}
    for r in zzshare_rows:
        if r.get("platecode") is None and r.get("code"):
            r["platecode"] = r["code"]
        name = r.get("name", "")
        if name and r.get("platecode"):
            by_name[name] = r["platecode"]

    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    ths_names: set[str] = set()
    for r in ths_rows:
        if not r.get("platecode") and r.get("name") in by_name:
            r["platecode"] = by_name[r["name"]]
        key = (r.get("code", ""), r.get("name", ""))
        if key in seen:
            continue
        seen.add(key)
        ths_names.add(r.get("name", ""))
        r["source"] = "ths"
        out.append(r)
    for r in zzshare_rows:
        # Same name already represented by a THS row — THS wins (THS cid
        # is the canonical code; zzshare's plate_code is metadata).
        if r.get("name", "") in ths_names:
            continue
        key = (r.get("code", ""), r.get("name", ""))
        if key in seen:
            continue
        seen.add(key)
        r["source"] = "ths"
        out.append(r)
    return out


def fetch_boards_with_zzshare_backfill(
    board_type: str | None,
    refresh: bool,
    include_quote: bool,
    subtype: str | None,
    manager,
) -> list[dict]:
    """Return unified board list with ths as primary, zzshare as platecode backfill.

    Behavior:
    - Always writes source='ths' to the cache (single source).
    - Always calls both ThsFetcher and ZzshareFetcher; merge by name.
    - When board_type is None, iterates every type VALID_SUBTYPES_BY_SOURCE['ths']
      supports (currently concept + industry; index/special are NOT exposed by
      ths — they fall through to persistence for eastmoney/zhitu callers).
    - When subtype is given, applies after merge (post-filter in memory).
    - When include_quote=True, the include_quote flag is forwarded to both
      ThsFetcher and ZzshareFetcher; zzshare's quote fields are sparse
      (only change_pct/amount/total_mv) so post-merge rows may have None
      for fields THS doesn't supply either.
    - ``refresh`` is accepted for call-site symmetry with the surrounding
      ``get_board_list`` wrapper (which decides cache vs. fresh fetch);
      this helper always fetches fresh data and ignores the value.

    Returns:
        list of {code, name, type, subtype, source, platecode, ...quote}
        where source='ths' on every row (zzshare rows are tagged with the
        same label after merge; the distinction is internal).

    Raises:
        DataFetchError: ThsFetcher's call failed. ZzshareFetcher failures
        are logged at WARNING and treated as empty list (best-effort
        backfill; primary path is THS).
    """
    types_to_fetch: list[str]
    if board_type is None:
        # Iterate every type ths supports (concept + industry currently).
        # Falls back to "concept" if the metadata table is somehow empty.
        ths_table = VALID_SUBTYPES_BY_SOURCE.get("ths", {})
        types_to_fetch = list(ths_table.keys()) or ["concept", "industry"]
    elif board_type in ("concept", "industry"):
        types_to_fetch = [board_type]
    else:
        # index / special are not exposed by ths; return empty
        return []

    out: list[dict] = []
    for bt in types_to_fetch:
        ths_rows: list[dict] = []
        try:
            ths_rows, _ = manager.get_all_boards(
                source="ths",
                board_type=bt,
                subtype=None,
                include_quote=include_quote,
            )
        except DataFetchError as e:
            logger.warning(
                f"[BoardCache] fetch_boards_with_zzshare_backfill: ths({bt}) failed: {e}"
            )
            # ThsFetcher failure is fatal for this bt — skip it.
            continue

        zz_rows: list[dict] = []
        try:
            zz_rows, _ = manager.get_all_boards(
                source="zzshare",
                board_type=bt,
                subtype=None,
                include_quote=include_quote,
            )
        except Exception as e:
            logger.warning(
                f"[BoardCache] fetch_boards_with_zzshare_backfill: "
                f"zzshare({bt}) failed (best-effort): {e}"
            )
            zz_rows = []

        merged = _merge_ths_zzshare_by_name(ths_rows, zz_rows)
        # Subtype filter is applied per-type post-merge (in-memory).
        if subtype is not None:
            merged = [r for r in merged if r.get("subtype") == subtype]
        out.extend(merged)
    return out


def fetch_board_stocks_with_zzshare_fallback(
    board_code: str,
    source: str,
    include_quote: bool,
    manager,
    *,
    sort_by: str | None = None,  # 2026-07-13: 透传到 ths
    sort_order: str = "desc",
    top_n: int = 50,
) -> tuple[list[dict], str, str, str | None]:
    """Get stocks for a board — STRICTLY source-routed with one cross-source fallback.

    Behaviour rules per source (per the 2026-07-10 optimization
    discussion; effective_source is ALWAYS populated, per the P4 product
    decision):

    - ``source='ths'``:
        * ``include_quote=True`` → THS is the only fetcher that emits
          realtime quote fields (price / change_pct / amount / …). On
          ``DataFetchError``, propagate so the route returns 5xx
          (zzshare fallback is forbidden here — its stocks carry no
          quote fields and the response shape would silently degrade).
          The new 2026-07-13 kwargs (``sort_by`` / ``sort_order`` /
          ``top_n``) are forwarded to THS so the response honours the
          user's sort+top-N contract.
        * ``include_quote=False`` → prefer zzshare first (lighter
          request, no quote enrichment needed); on zzshare
          ``DataFetchError`` OR empty-rows, fall back to THS. The
          route layer surfaces the actual fetcher via the
          ``effective_source`` field so the client can tell whether
          fallback fired. The sort/top-N kwargs are NOT forwarded to
          the include_quote=False branches (zzshare / THS-fallback) —
          the route layer 400-asserts those kwargs are at defaults
          whenever ``include_quote=False``.

    - ``source='zzshare'`` (internal label only; Literal at the route
      layer rejects it post-2026-07-08 unification): call ZzshareFetcher
      with the platecode. Errors propagate.
    - ``source='eastmoney'`` / ``source='zhitu'``: call the named
      fetcher with the platecode (these fetchers do not require cid
      translation). Errors propagate.

    Args:
        board_code: Public platecode (e.g. ``'885642'``). For ``ths``
            the helper looks up the THS concept cid internally.
        source: Fetcher slug. One of ``'ths'``, ``'zzshare'``,
            ``'eastmoney'``, ``'zhitu'``.
        include_quote: Forwarded to the fetcher. Affects routing
            inside the THS branch (above).
        manager: Required. ``DataFetcherManager`` instance.
        sort_by: 2026-07-13 — forwarded to the THS leg
            (``source='ths' + include_quote=True``). See
            ``ThsFetcher._THS_BOARD_STOCKS_SORT_FIELD_MAP`` for the
            accepted set. Other branches ignore this kwarg.
        sort_order: 2026-07-13 — ``"asc"`` / ``"desc"``. Same
            forwarding rules as ``sort_by``.
        top_n: 2026-07-13 — max number of THS rows. Same forwarding
            rules as ``sort_by``.

    Returns:
        ``(stocks, source_label, effective_source, reason)`` — 4-tuple:
          - ``stocks``: list of stock dicts (potentially empty).
          - ``source_label``: fetcher name matching the user's
            ``?source=`` (the *requested* source). For all branches
            except the THS+include_quote=False fallback path, this
            equals ``effective_source``.
          - ``effective_source``: the fetcher name that *actually
            served* the response (per P4: ALWAYS populated). When it
            differs from ``source_label``, the route response carries
            an actionable ``effective_source`` field so the client can
            tell the response came from a fallback fetcher.
          - ``reason``: optional annotation for the empty-result case.
            Currently only one value: ``"cid_unresolved"`` — when
            ``_resolve_ths_cid_from_platecode`` returned ``None`` and
            the helper could not perform any fetch. ``None`` for all
            other branches. The route layer maps ``reason="cid_unresolved"``
            to a 422 response (see ``api/routes/boards.py``).

        Note: this helper returns the bare 4-tuple above. The trailing
        ``quote_truncated`` / ``quote_total_in_board`` 6-tuple fields
        are only appended by ``get_board_stocks`` (which owns the
        50-stock heuristic + ZZSHARE fill-in logic). Callers that need
        the heuristic fields must compose them on top of this helper.

    Raises:
        DataFetchError: the chosen fetcher raised and no fallback was
            applicable (or the fallback also raised). Propagates so
            the route layer returns 5xx rather than masking the error.
        ValueError: ``source`` is not one of the four supported slugs.
    """
    if source == "ths":
        # include_quote=True: THS is mandatory — zzshare has no quote
        # fields, falling back would silently degrade the response to
        # null quotes. Propagate any failure unchanged. 2026-07-13:
        # forward sort_by/sort_order/top_n to THS so the user contract
        # (board-stocks top-N + sort) is honored end-to-end.
        if include_quote:
            cid = _resolve_ths_cid_from_platecode(board_code)
            if not cid:
                return [], "ths", "ths", "cid_unresolved"
            try:
                rows, _ = manager.get_board_stocks(
                    board_code=cid,
                    source="ths",
                    include_quote=True,
                    sort_by=sort_by,
                    sort_order=sort_order,
                    top_n=top_n,
                )
            except DataFetchError:
                raise
            return rows, "ths", "ths", None

        # include_quote=False: prefer THS F10 full (90+ members, no quote).
        # Added 2026-07-20 per spec §3.5.1: the F10 page server-renders
        # the full concept membership without the 50-stock cap that q.10jqka
        # AJAX enforces. Falls back to the existing ZZSHARE primary + THS
        # AJAX chain on any failure or empty result.
        #
        # Graceful degradation: if the manager's ``get_board_stocks_full``
        # is unconfigured (older test mocks) or returns a non-2-tuple
        # (MagicMock quirks), we silently skip the F10 leg and fall through
        # to ZZSHARE primary. The check is on the *return shape*, not the
        # call success — MagicMock auto-creates the attribute so
        # ``hasattr`` is unreliable here.
        f10_full = getattr(manager, "get_board_stocks_full", None)
        if callable(f10_full):
            try:
                _f10_ret = f10_full(
                    board_code=board_code,
                    source="ths",
                )
            except TypeError as ty_err:
                # TypeError: legacy mock managers don't accept kwargs.
                # Re-raise so test failures surface; production
                # DataFetcherManager always accepts the kwargs.
                raise ty_err
            except DataFetchError as f10_err:
                logger.info(
                    f"[BoardCache] fetch_board_stocks_with_zzshare_fallback: "
                    f"ths F10 raised DataFetchError for board={board_code}; "
                    f"falling back to zzshare primary "
                    f"({type(f10_err).__name__}: {f10_err})"
                )
                _f10_ret = None
            except Exception as f10_err:
                logger.info(
                    f"[BoardCache] fetch_board_stocks_with_zzshare_fallback: "
                    f"ths F10 raised for board={board_code}; "
                    f"falling back to zzshare primary "
                    f"({type(f10_err).__name__}: {f10_err})"
                )
                _f10_ret = None
            else:
                pass
            # Verify it's a 2-tuple; otherwise skip (mock quirk).
            if _f10_ret is not None and (
                isinstance(_f10_ret, tuple)
                and len(_f10_ret) == 2
                and isinstance(_f10_ret[0], list)
            ):
                f10_rows, _ = _f10_ret
                if f10_rows:
                    return f10_rows, "ths", "ths-f10", None
                logger.info(
                    f"[BoardCache] fetch_board_stocks_with_zzshare_fallback: "
                    f"ths F10 returned 0 rows for board={board_code}; "
                    f"falling back to zzshare primary"
                )
            # else: fall through to ZZSHARE primary

        # include_quote=False (continued): prefer zzshare (lighter request,
        # no quote enrichment). Fall back to ths on any DataFetchError
        # OR zzshare-returned-empty (consistent with prior behaviour
        # that 404 was treated as 'nothing here'). Both branches
        # populate effective_source so the client sees what fired.
        try:
            rows, _ = manager.get_board_stocks(
                board_code=board_code,
                source="zzshare",
                include_quote=False,
            )
        except DataFetchError as zz_err:
            logger.info(
                f"[BoardCache] fetch_board_stocks_with_zzshare_fallback: "
                f"zzshare raised for board={board_code}; "
                f"falling back to ths ({type(zz_err).__name__}: {zz_err})"
            )
        else:
            if rows:
                return rows, "ths", "zzshare", None
            logger.info(
                f"[BoardCache] fetch_board_stocks_with_zzshare_fallback: "
                f"zzshare returned 0 rows for board={board_code}; "
                f"falling back to ths"
            )

        # THS fallback path (include_quote=False from user).
        cid = _resolve_ths_cid_from_platecode(board_code)
        if not cid:
            return [], "ths", "ths", "cid_unresolved"   # cid unresolved → empty; no fetch happened
        try:
            rows, _ = manager.get_board_stocks(
                board_code=cid,
                source="ths",
                include_quote=False,
            )
        except DataFetchError:
            raise
        return rows, "ths", "ths", None

    if source == "zzshare":
        try:
            rows, _ = manager.get_board_stocks(
                board_code=board_code,
                source="zzshare",
                include_quote=include_quote,
            )
        except DataFetchError:
            raise
        return rows, "zzshare", "zzshare", None

    if source in ("eastmoney", "zhitu"):
        try:
            rows, _ = manager.get_board_stocks(
                board_code=board_code,
                source=source,
                include_quote=include_quote,
            )
        except DataFetchError:
            raise
        return rows, source, source, None

    raise ValueError(
        f"fetch_board_stocks_with_zzshare_fallback: unsupported source {source!r}"
    )


THS_HARD_CAP = 50  # THS upstream hard cap (5 pages * 10 rows)


def get_board_stocks(
    board_code: str,
    source: str = "ths",
    refresh: bool = False,
    include_quote: bool = False,
    manager=None,
    *,
    sort_by: str | None = None,  # 2026-07-13
    sort_order: str = "desc",  # 2026-07-13
    top_n: int = 50,  # 2026-07-13
) -> tuple[list, str, str, str | None, bool, int]:
    """Get stocks belonging to a board with automatic refresh.

    Cache is keyed on the public board_code (not on source — different
    sources all normalize to the same THS platecode). Cache hits return
    origin="persistence". Cache misses call
    ``fetch_board_stocks_with_zzshare_fallback`` which (post-2026-07-10):
      * Strictly honors the user-chosen ``source`` for the *primary*
        route.
      * For ``source='ths'`` + ``include_quote=False`` only, prefers
        ZZSHARE first and falls back to THS (see the helper docstring).
      * Exposes ``effective_source`` so the route / client can tell
        whether a fallback fired.

    Note (P3, 2026-07-10): rows written into the cache are always
    tagged with ``source='ths'`` regardless of the upstream that
    served them (post-unification policy). When ZZSHARE served the
    fetch, the cached rows **lack quote fields** (zzshare emits only
    stock_code / stock_name / exchange). The next caller using
    ``?include_quote=true`` will still bypass the cache (the
    ``needs_refresh`` flag forces a fresh THS fetch), so they don't
    see "apparent None quotes". Pass ``?refresh=true`` if you need to
    force a fresh THS fetch *and* the data is currently a ZZSHARE-served
    cache row.

    2026-07-13 (board-stocks top-N + sort): the return shape is now
    6-tuple. The new tail entries are:

      * ``quote_truncated`` (bool) — True if the response is a *partial*
        snapshot: the THS leg returned exactly ``THS_HARD_CAP`` rows
        (50) and we suspect the real membership may be larger. The
        caller-facing 50-stock heuristic (the THS upstream hard cap) is
        mitigated by an opportunistic ZZSHARE fill-in: we call
        ``manager.get_board_stocks(source='zzshare', include_quote=False)``
        and append any ZZSHARE members *not* already in the THS top-N
        as a suffix with no quote fields. When the suffix is non-empty,
        ``quote_truncated=True``. When ZZSHARE also returns empty /
        errors, ``quote_truncated=True`` is reported conservatively —
        the client should treat the result as potentially incomplete
        (cannot be distinguished from "board really has 50 stocks").
      * ``quote_total_in_board`` (int) — best-effort count of the
        board's full membership (THS top-N + ZZSHARE suffix) when the
        heuristic fired; otherwise the row count we actually returned.

    The 50-stock heuristic is gated on ``include_quote=True`` (only
    THS quote-fetched responses are size-capped; cache-hit
    ``include_quote=False`` paths return all rows from the cache table,
    which historically holds the full membership).

    Args:
        board_code: THS platecode (885xxx concept / 881xxx industry).
        source: User's chosen fetcher; defaults to ``'ths'`` for
            backward compatibility with the pre-strict-routing callers.
            Strictly routed downstream.
        refresh: If True, force refresh from upstream.
        include_quote: If True, always fetch fresh realtime data from upstream.
        manager: DataFetcherManager instance. Required when fetching from upstream.
        sort_by: 2026-07-13 — forwarded to THS (THS supported set;
            ignored for other sources). Default None = THS default
            (currently ``"change_pct"``).
        sort_order: 2026-07-13 — ``"asc"`` / ``"desc"``. Default ``"desc"``.
        top_n: 2026-07-13 — max THS rows. Default 50. THS upstream
            hard cap is 50; the heuristic at 50+ triggers the
            ZZSHARE suffix fill-in.

    Returns:
        6-tuple ``(stocks, origin, effective_source, reason,
        quote_truncated, quote_total_in_board)``:
          - ``stocks`` is the list of stock dicts (top-N + suffix
            merged when the heuristic fired; otherwise just the
            fetcher's response).
          - ``origin`` is ``"persistence"`` (cache hit) or the
            requested fetcher slug (cache miss path), as before.
          - ``effective_source`` is always populated to the fetcher
            slug that actually served the response — *post-fix* this is
            always a non-empty string. ``query_source vs effective_source``
            at the route layer tells the client whether the fallback fired.
          - ``reason``: optional annotation, currently only
            ``"cid_unresolved"`` when the THS cid-index cache missed
            for the board_code and no fetch was attempted. ``None`` in
            all other cases. The route layer maps
            ``reason="cid_unresolved"`` to HTTP 422; ``None`` (or any
            other empty-result case) maps to HTTP 404.
          - ``quote_truncated`` (bool) — see heuristic notes above.
          - ``quote_total_in_board`` (int) — see heuristic notes above.
    """
    init_schema()

    # Tracker key intentionally stays at "ths" — the SQLite cache is keyed
    # on (board_code, source='ths') regardless of which fetcher originally
    # populated it (post-unification policy). Per-source tracker keys would
    # mean non-ths callers always miss the cache, bypassing it even after
    # ths has populated the same row.
    needs_refresh = include_quote or refresh or _refresh_tracker.is_first_call(f"{board_code}:ths")

    cached_full = _read_board_stocks_from_db(board_code, "ths")
    cached_count = len(cached_full)

    if not needs_refresh and cached_full:
        # Cache hit: the upstream that originally wrote the row
        # is not surfaced here. The route layer reports
        # ``origin="persistence"``; clients that need the actual
        # upstream should pass ?refresh=true.
        return cached_full, "persistence", "ths", None, False, cached_count

    if manager is None:
        raise ValueError("manager is required when refresh=True or cache miss")

    if not include_quote:
        # include_quote=False path — the route layer 400-asserts the
        # 2026-07-13 sort/top_n kwargs are at defaults. Pass nothing
        # through to the helper so the include_quote=False branches
        # retain their existing include_quote=False semantics.
        try:
            stocks, origin, effective_source, reason = fetch_board_stocks_with_zzshare_fallback(
                board_code=board_code,
                source=source,
                include_quote=False,
                manager=manager,
            )
        except DataFetchError as e:
            # P3-a1 (H4): when both ZZSHARE and THS fail upstream, fall back
            # to whatever we have in SQLite. The user's request still
            # succeeds with yesterday's data instead of a hard 5xx. The
            # caller distinguishes via origin="persistence" + reason set.
            # Mirror of pool_daily.get_pool:325-336.
            if cached_full:
                logger.warning(
                    f"[BoardCache] Upstream failed for {board_code} "
                    f"(include_quote=False), serving {len(cached_full)} stale "
                    f"stocks: {e}"
                )
                return (
                    cached_full,
                    "persistence",
                    "ths",
                    "stale_after_upstream_failure",
                    False,
                    cached_count,
                )
            raise
        if stocks:
            update_cached_board_stocks(board_code, "ths", stocks)
            logger.info(
                f"[BoardCache] Refreshed {len(stocks)} stocks for board "
                f"{board_code}/ths (origin={origin}, effective_source={effective_source})"
            )
        # Return the initial DB count as-is (cached_count) — we just
        # refreshed the cache, but the variable intentionally stays
        # pinned to ``len(cached_full)`` so callers can compare
        # against the pre-refresh state without losing track of the
        # "what was in the cache at the start of this call" semantic.
        return stocks, origin, effective_source, reason, False, cached_count

    # include_quote=True path: the THS branch honors sort_by / sort_order / top_n.
    stocks, origin, effective_source, reason = fetch_board_stocks_with_zzshare_fallback(
        board_code=board_code,
        source=source,
        include_quote=True,
        manager=manager,
        sort_by=sort_by,
        sort_order=sort_order,
        top_n=top_n,
    )

    if not stocks:
        return [], origin, effective_source, reason, False, cached_count

    # 2026-07-13: per user Q&A — "include_quote=true 时, 总是调一次 ZZSHARE
    # 拉全量成员清单, 补全剩余股票" (regardless of top_n / len(stocks)).
    # 之前的 heuristic (len(stocks) >= 50) 让 top_n<50 的请求静默截断
    # 200 只成分股的 board, THS 返回 10 行, ZZSHARE 不被调, client 误以为
    # board 只有 10 只 — 契约撒谎. 新行为: 总是 1 次 ZZSHARE upstream call.
    suffix_no_quote: list[dict] = []
    try:
        zz_rows, _ = manager.get_board_stocks(
            board_code=board_code,
            source="zzshare",
            include_quote=False,
        )
    except DataFetchError as e:
        logger.warning(
            f"[BoardCache] ZZSHARE fill-in for {board_code} failed: {e}; "
            f"falling back to THS-only top-{len(stocks)}"
        )
        zz_rows = []

    quote_codes = {s["stock_code"] for s in stocks if s.get("stock_code")}
    suffix_no_quote = [
        r
        for r in (zz_rows or [])
        if r.get("stock_code") and r["stock_code"] not in quote_codes
    ]

    # quote_truncated: True iff suffix 非空 (真截断 observed) OR
    # ZZSHARE 失败/空 (无法验证, 保守 True). False iff suffix 空且
    # ZZSHARE 至少返回了行 — 表示 board 真有 top_n 只成员.
    if suffix_no_quote:
        quote_truncated = True
    elif not zz_rows:
        # ZZSHARE failed or returned empty; can't verify completeness.
        # Conservative: report True so clients can re-check.
        quote_truncated = True
        logger.info(
            f"[BoardCache] {board_code}: include_quote=true with no ZZSHARE "
            f"verification; quote_truncated=True conservatively"
        )
    else:
        # ZZSHARE returned, suffix empty → board genuinely has only what THS gave.
        quote_truncated = False

    # quote_total_in_board:
    #   suffix 非空 → len(stocks) + len(suffix_no_quote)  (ZZSHARE 是真板)
    #   suffix 空 + ZZSHARE 至少返回 → max(cached_count, len(stocks))
    #     (cached_count >= len(stocks) when cache had more rows pre-refresh)
    #   suffix 空 + ZZSHARE 失败 → cached_count (conservative, 不知道 board 真大小)
    if suffix_no_quote:
        quote_total_in_board = max(cached_count, len(stocks) + len(suffix_no_quote))
    elif zz_rows:
        quote_total_in_board = max(cached_count, len(stocks))
    else:
        quote_total_in_board = cached_count

    # 拼接最终响应列表 (top-N 在前, suffix 在后)
    if suffix_no_quote:
        final_stocks = stocks + suffix_no_quote
    else:
        final_stocks = stocks

    # 回写 cache: final_stocks 含 quote 字段, 但 update_cached_board_stocks
    # 投影只写 (board_code, source, stock_code, stock_name, board_name,
    # board_type, subtype, refreshed_at) — quote 字段自然被 SQLite 列投影丢弃
    # (CLAUDE.md "Don't cache realtime quote data in SQLite").
    update_cached_board_stocks(board_code, "ths", final_stocks)
    logger.info(
        f"[BoardCache] Refreshed {len(stocks)} ths + {len(suffix_no_quote)} zz suffix "
        f"for board {board_code}/ths "
        f"(origin={origin}, effective_source={effective_source}, "
        f"quote_truncated={quote_truncated}, total={quote_total_in_board})"
    )

    return final_stocks, origin, effective_source, reason, quote_truncated, quote_total_in_board


def resolve_board_types(
    codes: list[str],
    source: str,
) -> dict[str, dict[str, str | None]]:
    """Look up authoritative ``board_type`` / ``subtype`` for a batch of codes.

    Single source of truth for cross-layer type resolution. EastMoney's
    push2.slist/get reverse endpoint (used by ``get_stock_boards``) cannot
    distinguish concept / industry / region / index — every row has
    ``f152=2`` — so the fetcher hardcodes ``"industry"`` and relies on this
    helper to recover the true classification.

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
        - DELETE-then-INSERT inside the same ``with conn:`` transaction:
          stocks that left the board upstream are purged so the cache
          reflects the current snapshot rather than a monotonic union of
          all historical members. Both backfill tools
          (``tools/build_membership_index.py``, ``persistence/backfill.py``)
          pass the full board membership per call — partial-update
          callers would silently lose rows.
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
        # Purge stale members that left the board upstream, scoped to
        # (board_code, source) so other boards / source labels are untouched.
        cursor.execute(
            "DELETE FROM stock_board_membership WHERE board_code = ? AND source = ?",
            (board_code, source),
        )
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


def _read_membership_entries(
    stock_code: str, sources: list[str], cursor
) -> tuple[list[dict], set[str]]:
    """Read membership rows for a stock from the given sources. Returns (entries, present_sources).

    Read-time override (added 2026-07-09): LEFT JOIN ``stock_board`` so each
    entry's ``name`` / ``type`` / ``subtype`` prefer the authoritative
    stock_board values over the membership row's cached copy. This
    neutralises the legacy bug where ``update_cached_board_stocks`` wrote
    ``board_name = board_code`` and ``board_type = ''`` / ``subtype = NULL``
    to membership when stock_board was empty at write time. Once stock_board
    is populated (e.g. via the next board-list refresh), reads pick up the
    correct values immediately without rewriting the stale membership rows.

    THS concept-board quirk (added 2026-07-09): membership stores
    ``board_code = platecode`` (885xxx), and stock_board now also stores
    that same value under ``code`` (post-2026-07-20 schema unification).
    A single ``sb.code = m.board_code`` JOIN matches every source
    uniformly — for eastmoney/zhitu the column is the BKxxxx/sw_xxx
    identifier; for THS concept it's the 885xxx platecode; for THS
    industry it's the 881xxx (== platecode).

    Fallback: when stock_board has no row for the (board_code, source)
    pair, the membership row's stored values are kept — matches the route
    layer's existing fallback contract for boards that were never written
    to stock_board (see ``get_board_name_with_fallback``).
    """
    placeholders = ",".join("?" * len(sources))
    cursor.execute(
        f"""SELECT m.board_code, m.stock_code, m.source,
                   m.board_name, m.stock_name, m.board_type, m.subtype,
                   sb.name AS sb_name,
                   sb.board_type AS sb_board_type,
                   sb.subtype AS sb_subtype
           FROM stock_board_membership m
           LEFT JOIN stock_board sb
             ON sb.source = m.source
            AND sb.code = m.board_code
           WHERE m.stock_code = ? AND m.source IN ({placeholders})
           ORDER BY m.source, m.board_code""",
        (stock_code, *sources),
    )
    raw_rows = cursor.fetchall()
    entries = [
        {
            "code": r["board_code"],
            # Authoritative name/type/subtype from stock_board when present;
            # otherwise the membership row's stored value (legacy fallback).
            "name": r["sb_name"] if r["sb_name"] is not None else r["board_name"],
            "type": (r["sb_board_type"] if r["sb_board_type"] is not None else r["board_type"]),
            "subtype": ((r["sb_subtype"] if r["sb_subtype"] is not None else r["subtype"]) or ""),
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
    manager=None,
) -> tuple[list[dict], list[str], str]:
    """Single source of truth for stock→boards reverse lookup.

    Reads stock_board_membership for each requested source and applies
    type/subtype filters. Cold-fill (on-request fetcher-triggered population)
    has been removed — reverse lookup relies on the startup backfill
    (see ``persistence.backfill``) or accepts a cache miss surfaced via
    ``cold_sources``. The ``manager`` parameter is kept for API stability
    but is no longer used inside this function.

    Args:
        stock_code: 6-digit stock code (e.g. '600519').
        sources: list of canonical source names (route layer normalizes
                 'zzshare' → 'ths' before calling, so 'ths' appears here
                 when the caller used either label). May be empty.
        type: optional board type filter (concept/industry/index/special).
        subtype: optional source-specific subtype filter.
        manager: DataFetcherManager instance. Unused after the cold-fill
                  removal; kept for backward-compatible call signatures.

    Returns:
        (entries, cold_sources, origin_summary)
        - entries: list of {code, name, type, subtype, source}, one dict per row.
        - cold_sources: subset of `sources` with no data in the cache.
        - origin_summary:
            - "persistence" — entries from SQLite cache (no fetcher calls); also used
                              when entries is empty (cache miss)
            - "mixed"       — multi-source query with entries
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
    # Post-2026-07-20: `code` is the cross-source public identifier. THS
    # concept rows used to require `code OR platecode` because callers passed
    # the public platecode (885xxx) while the row stored the cid (3xxxxx);
    # the migration unified those into `code`, so a single-column match
    # covers every source uniformly.
    cursor.execute(
        "SELECT name FROM stock_board WHERE code = ? AND source = ? LIMIT 1",
        (board_code, source),
    )
    row = cursor.fetchone()
    return row["name"] if row else None


def get_board_metadata(
    board_code: str, source: str
) -> dict[str, Any] | None:
    """Look up full board metadata (name + type + subtype + cid) from the SQLite cache.

    Same fast-path semantics as :func:`get_board_name` — single-row read
    against ``stock_board``, matching on the public ``code`` column. No
    upstream fallback; returns ``None`` on cache miss.

    Args:
        board_code: Public board code (e.g. ``"BK1048"`` or ``"885595"``).
        source: Data source slug (``"ths"``, ``"eastmoney"``, etc.).

    Returns:
        Dict ``{"name": str, "type": str, "subtype": str, "code": str, "cid": str | None}``
        if a row exists; ``None`` on cache miss. ``type`` and ``subtype``
        mirror the cache column values verbatim (may be empty string for
        older rows where the column was added in a forward-compat migration).
        ``code`` is the cross-source public board identifier (THS platecode
        885xxx/881xxx, eastmoney BKxxxx, zhitu sw_xxx). ``cid`` is the THS
        internal concept cid (3xxxxx); NULL for THS industry, eastmoney,
        and zhitu rows.

        The ``code`` and ``cid`` keys replaced the pre-2026-07-20
        ``(code, platecode)`` pair (see spec
        ``2026-07-20-ths-board-f10-extension-design.md`` §1.1). Backward-
        compat: pre-existing callers that read ``platecode`` from the old
        return shape continue to work via the :func:`get_board_metadata_compat`
        alias — but new code should read ``code`` directly.
    """
    init_schema()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT name, board_type, subtype, code, cid FROM stock_board "
        "WHERE code = ? AND source = ? LIMIT 1",
        (board_code, source),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    # Migration gap detection (F2): the board_type column was added in a
    # forward-compat migration. Legacy rows from before that migration
    # have board_type=NULL. Surface this with a warning so operators
    # can spot the migration debt — the route layer treats this case
    # the same as a cache miss (board.type=null in the response), but
    # the call site can now distinguish "no row" from "row without type".
    if not row["board_type"]:
        logger.warning(
            f"[BoardCache] stock_board row exists for board_code={board_code!r} "
            f"source={source!r} but board_type column is NULL/empty — likely "
            f"a pre-migration row. Refresh the board list to backfill type."
        )
    return {
        "name": row["name"],
        "type": row["board_type"],
        "subtype": row["subtype"] or "",
        "code": row["code"],
        "cid": row["cid"],
    }


def get_board_metadata_compat(
    board_code: str, source: str
) -> dict[str, Any] | None:
    """Backward-compat wrapper that returns ``platecode`` instead of ``cid``.

    Post-2026-07-20, callers that previously read ``meta["platecode"]``
    can still do so via this wrapper — the wrapper maps the new
    ``code`` value into the ``platecode`` key (and drops ``cid``).
    New code should prefer :func:`get_board_metadata` directly.
    """
    meta = get_board_metadata(board_code, source)
    if meta is None:
        return None
    return {
        "name": meta["name"],
        "type": meta["type"],
        "subtype": meta["subtype"],
        "code": meta["code"],
        "platecode": meta["code"],  # post-migration: code == old platecode
    }


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
            match = next(
                (b["name"] for b in boards if board_code in (b.get("code"), b.get("platecode"))),
                None,
            )
            if match:
                return match
    except (DataFetchError, ValueError, AttributeError) as e:
        logger.debug(
            f"[BoardCache] board-name fallback for {board_code} "
            f"(source={source}): {type(e).__name__}: {e}"
        )
    return None


def _read_boards_from_db(
    board_type: str, source: str, subtype: str | None = None
) -> list[dict[str, Any]]:
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
            """SELECT code, name, board_type, subtype, source, cid, updated_at
               FROM stock_board WHERE board_type = ? AND source = ? ORDER BY name""",
            (board_type, source),
        )
    else:
        cursor.execute(
            """SELECT code, name, board_type, subtype, source, cid, updated_at
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
            # Post-2026-07-20 we expose both `code` (cross-source public) and
            # `cid` (THS internal). ``platecode`` is no longer a separate key
            # in the returned dict — callers that need it should read `code`
            # (which IS the old platecode for THS / BKxxxx for eastmoney).
            "cid": row["cid"],
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
                (code, name, board_type, subtype, source, cid, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        # post-2026-07-20 schema: `code` = cross-source public
                        # identifier (THS platecode / eastmoney BK / zhitu sw_xxx).
                        # Fetcher rows still emit THS's value under key
                        # ``platecode`` (legacy fetcher contract); fall back
                        # to ``code`` (the fetcher's general-key field) when
                        # the upstream didn't expose a separate platecode.
                        b.get("platecode") or b["code"],
                        b["name"],
                        board_type,
                        b.get("subtype") or "",
                        source,
                        # `cid` is the THS concept internal id (3xxxxx); for
                        # THS concept rows it lives under `code` in the
                        # fetcher dict, distinct from `platecode`. Only write
                        # a non-NULL cid when the two values actually differ
                        # (otherwise we'd store BK1048/eastmoney as a false cid).
                        (
                            b["code"]
                            if (
                                source == "ths"
                                and b.get("platecode")
                                and b["code"] != b.get("platecode")
                            )
                            else None
                        ),
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
            # Purge stale members that left the board upstream, scoped to
            # (board_code, source). The fetch path always re-reads the full
            # board on cache miss, so DELETE-then-INSERT inside one
            # transaction is the correct "snapshot replace" semantics —
            # partial-update callers would lose rows.
            cursor.execute(
                "DELETE FROM stock_board_membership WHERE board_code = ? AND source = ?",
                (board_code, source),
            )
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
