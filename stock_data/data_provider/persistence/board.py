"""
SQLite persistence for stock board (concept/industry) data.

Provides persistent storage for board listing data to avoid repeated
upstream API calls which are slow and may fail.
"""

import logging
import sqlite3
from datetime import datetime, timedelta
from datetime import time as _dt_time
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    pass
from typing import Any

from ..base import DataFetchError
from . import db
from ._refresh import DailyRefreshTracker
from .db import get_connection, get_db_path

logger = logging.getLogger(__name__)


def get_cached_market_quotes(manager) -> list | None:
    """Read the /api/v1/stocks full-market quote cache. On miss, fetch
    and write back. Returns the unsorted, unsliced upstream list, or
    None on upstream failure.

    Reuses the same cache namespace (stock_list_quote:csi) and TTL
    (60s intraday, 7d close-tagged slow) as /stocks?include_quote=true,
    so any request that touches /stocks naturally warms this cache.

    Cache hit = zero upstream. Cache miss + fetch fail = None, which
    leaves suffix rows at None in the caller — never raises, by
    contract (the route layer's include_quote path is best-effort).

    Added 2026-07-30 alongside the cross-endpoint quote-cache fillup
    for /boards/{code}/stocks suffix rows.

    Note: intraday/slow-cache branch + (date, session) tag for slow
    cache write are inlined here rather than extracted to helpers
    (avoids duplicating /stocks route's _is_intraday / _latest_past_close,
    and there's only one call site).
    """
    from datetime import date as _date

    from ...api.cache import (
        cached_lookup,
        cached_store,
        get_stock_list_quote_cache,
        get_stock_list_quote_slow,
    )
    from . import trade_calendar

    cache_key = "stock_list_quote:csi"
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    today = now.date()
    t = now.time()
    is_trade_day = trade_calendar.is_trade_date(today.isoformat())
    # Inlined: intraday = 09:15-11:30 or 13:00-15:00 on a trade day.
    in_intraday = is_trade_day and (
        (_dt_time(9, 15) <= t < _dt_time(11, 30)) or (_dt_time(13, 0) <= t < _dt_time(15, 0))
    )

    if in_intraday:
        hit = cached_lookup(get_stock_list_quote_cache, cache_key, "stock_list_quote")
        if hit is not None:
            return hit[0]
    else:
        hit = cached_lookup(get_stock_list_quote_slow, cache_key, "stock_list_quote")
        if hit is not None:
            _, _, cached_quotes, _ = hit
            if cached_quotes is not None:
                return cached_quotes

    # Cache miss → fetch
    quotes, source = manager.get_realtime_quotes("csi")
    if not quotes:
        return None

    if in_intraday:
        cached_store(get_stock_list_quote_cache, cache_key, (quotes, source))
    else:
        # Inlined: pick (date, session) for the slow-cache tag — mirrors
        # /stocks route's _latest_past_close. Falls back to (today,
        # "afternoon") on empty calendar.
        if not is_trade_day or t < _dt_time(11, 30):
            prev = trade_calendar.get_latest_trade_date_on_or_before(
                (today - timedelta(days=1)).isoformat()
            )
            target_date = _date.fromisoformat(prev) if prev else today
            target_session = "afternoon"
        elif t < _dt_time(15, 0):
            target_date, target_session = today, "morning"
        else:
            target_date, target_session = today, "afternoon"
        cached_store(
            get_stock_list_quote_slow,
            cache_key,
            (target_date, target_session, quotes, source),
        )
    return quotes


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


# Board-stocks source 集合 (3 sources — ths/eastmoney/zhitu).
# `zzshare` is not in the public surface yet (Literal returns 422). It is
# NOT used internally by any cross-source fallback any more — the
# ZZSHARE-primary include_quote=False chain was deleted 2026-09-11
# (spec §2 D2); that path is now THS F10 only.
_BOARD_STOCKS_VALID_SOURCES: tuple[str, ...] = ("ths", "eastmoney", "zhitu")


def normalize_board_stocks_source(source: str) -> str:
    """Validate a source name for the board-stocks endpoint.

    Unlike ``normalize_stock_board_source`` (which aliases
    ``zzshare → ths``), this helper does NOT alias. Public surface
    accepts the three source labels whose fetcher owns the route:

    - ``ths``: ThsFetcher (q.10jqka.com.cn AJAX — concept boards)
    - ``eastmoney``: EastMoneyFetcher (push2his)
    - ``zhitu``: ZhituFetcher

    ``zzshare`` is not a public label here. It is no longer invoked
    transparently on ``source='ths'`` requests either: the cross-source
    fallback was deleted 2026-09-11 (spec §2 D2 — strict isolation).

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
    # THS cid → platecode map. The single query point for "which of THS's
    # two board identifiers do I use here" — see docs/superpowers/specs/
    # 2026-09-11-board-source-split-design.md §3. `cid` is the stable key
    # (3xxxxx concept / 881xxx industry); `platecode` is the public one.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ths_board_id_map (
            cid        TEXT PRIMARY KEY,
            platecode  TEXT NOT NULL,
            name       TEXT,
            board_type TEXT,
            observed_at DATETIME
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_ths_board_id_map_platecode
            ON ths_board_id_map(platecode)
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
                -- cid: THS-internal id. For THS source, the post-migration
                -- contract stores a non-NULL cid even for industry rows
                -- (where platecode==code), so the resolver can rely on a
                -- always-present THS cid. EastMoney / Zhitu still get NULL.
                CASE
                    WHEN source = 'ths' AND code IS NOT NULL
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

    # One call per source, no merge branch. `ths` used to route through
    # fetch_boards_with_zzshare_backfill, which blended zzshare rows into
    # the ths namespace by board name — the mechanism behind spec §1.3's
    # 240 mislabelled rows. Strict isolation (spec §2 D2) deletes it.
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
            board_code = b.get("board_code")
            if not board_code or board_code in seen_codes:
                if board_code in seen_codes:
                    logger.debug(
                        f"[BoardCache] dropping duplicate board_code "
                        f"'{board_code}' (kept first occurrence)"
                    )
                continue
            seen_codes.add(board_code)
            combined.append(b)

    if origins == {"persistence"}:
        summary = "persistence"
    elif "persistence" in origins:
        summary = "mixed"
    else:
        summary = next(iter(origins))  # source name

    return combined, summary


def resolve_ths_cid(board_code: str) -> str | None:
    """Resolve the THS internal cid for a THS public board_code.

    Returns ``None`` when no THS row exists, or when the row's ``cid``
    column is NULL. **There is deliberately no fallback to ``code``.**

    That fallback is what let a zzshare plate code (801xxx) be handed to
    ThsFetcher as if it were a cid (spec §1.3, mechanism 5), and it also
    masked genuinely-unresolvable boards behind a plausible-looking value.
    Industry rows keep ``cid == code`` (881xxx) by construction, so they
    resolve normally without any special case.

    Args:
        board_code: THS public board code — 885xxx/886xxx (concept) or
            881xxx (industry).

    Returns:
        The THS cid (3xxxxx for concept, == board_code for industry), or
        ``None`` when unknown. Callers treat ``None`` as "cannot address
        this board on the AJAX tier".
    """
    init_schema()
    row = get_connection().execute(
        "SELECT cid FROM stock_board WHERE code = ? AND source = 'ths' LIMIT 1",
        (board_code,),
    ).fetchone()
    return row["cid"] if row and row["cid"] else None


def _enrich_rows_with_market_quote(
    rows: list[dict],
    market_quotes: list,
) -> list[dict]:
    """Union semantics: for each row, fill in any quote-shaped field
    whose value is None or missing by looking up the row's stock_code
    in the market-quote index. Existing non-None values are preserved
    (THS rows take priority for fields they have; /stocks cache fills
    the gaps).

    Applied to BOTH THS top-50 rows and suffix rows:

    - **THS top-50 row**: has 11/13 quote fields (price/change_pct/
      change_amount/amount/turnover_rate/amplitude/volume_ratio/
      pe_ratio/change_speed/free_float_shares/float_market_cap) +
      3 THS-only fields. Missing: open/high/low/prev_close/volume
      (THS 14 columns don't include them). Enrichment fills these
      5 fields from /stocks cache; existing fields untouched.
    - **Suffix row**: has only stock_code/stock_name (ZZSHARE raw).
      Missing all 13 fillable fields. Enrichment fills all of them.

    THS-only fields (change_speed, free_float_shares, float_market_cap)
    are NEVER set by this helper.

    Note 2026-09-03: ZT-pool join fields (is_limit_up, lb_count) have
    been retired from BoardStockInfo; this helper no longer touches them.

    Fillable fields (13) and their UnifiedRealtimeQuote source:
        price                ← q.price
        change_pct           ← q.change_pct
        change_amount        ← q.change_amount
        volume               ← q.volume
        amount               ← q.amount
        turnover_rate        ← q.turnover_rate
        volume_ratio         ← q.volume_ratio
        pe_ratio             ← q.pe_ratio
        open                 ← q.open_price
        high                 ← q.high
        low                  ← q.low
        pre_close            ← q.pre_close
        amplitude            ← q.amplitude, fallback (h-l)/pre_close*100

    Returns a new list; input is not mutated. Rows whose code is
    absent from market_quote are returned as-is (no fillup).
    """
    if not rows or not market_quotes:
        return list(rows)

    # Map: dict key (matches BoardStockInfo field name + route layer
    # _build_board_stock_info reads) → UnifiedRealtimeQuote attribute name.
    # Important: the dict_key must match what _build_board_stock_info
    # reads (e.g., "open" not "open_price" — see boards.py:88-91). The
    # previous typo "pre_close" → "pre_close" stored the value under
    # the UnifiedRealtimeQuote key, which the route never reads.
    fillable: list[tuple[str, str]] = [
        ("price", "price"),
        ("change_pct", "change_pct"),
        ("change_amount", "change_amount"),
        ("volume", "volume"),
        ("amount", "amount"),
        ("turnover_rate", "turnover_rate"),
        ("volume_ratio", "volume_ratio"),
        ("pe_ratio", "pe_ratio"),
        ("open", "open_price"),
        ("high", "high"),
        ("low", "low"),
        ("prev_close", "pre_close"),
    ]

    q_index = {q.code: q for q in market_quotes}
    out: list[dict] = []
    for row in rows:
        sc = row.get("stock_code", "")
        q = q_index.get(sc)
        if q is None:
            out.append(row)
            continue

        new_row = dict(row)
        for dict_key, quote_attr in fillable:
            if new_row.get(dict_key) is None:
                v = getattr(q, quote_attr, None)
                if v is not None:
                    new_row[dict_key] = v

        # amplitude: fill from q.amplitude, else compute fallback
        if new_row.get("amplitude") is None:
            if q.amplitude is not None:
                new_row["amplitude"] = q.amplitude
            elif q.high is not None and q.low is not None and q.pre_close:
                new_row["amplitude"] = (q.high - q.low) / q.pre_close * 100

        out.append(new_row)
    return out


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

    Cache is keyed on the public board_code (not on source — a row written
    by one source is never served to another; see spec §7). Cache hits
    return origin="persistence".

    Cache miss: ONE source, ONE tier, no cross-source fallback (spec §2 D2).

      * ``include_quote=False`` → the THS F10 page: full membership
        (90+ concept / 150-180 industry), addressed by the public
        platecode, no quote columns. Falls back to the SQLite copy on
        upstream failure (reason="stale_after_upstream_failure").
      * ``include_quote=True`` → the THS AJAX endpoint: `top_n` rows,
        addressed by THS's internal **cid**, hard-capped at 50 by
        upstream. Quote fields are then union-filled from the /stocks
        full-market quote cache. An unresolvable cid returns
        ``reason="cid_unresolved"``.

    ``source`` is strictly routed: ``?source=ths`` never reaches zzshare
    and vice versa. Before 2026-09-11 ``?source=ths`` + include_quote=False
    ran a ZZSHARE-primary chain internally; that is gone.

    Args:
        board_code: THS platecode (885xxx/886xxx concept, 881xxx industry).
        source: The fetcher slug to serve from. Strictly routed.
        refresh: If True, force refresh from upstream.
        include_quote: Selects the tier (see above).
        manager: DataFetcherManager instance. Required when fetching from
            upstream.
        sort_by: Forwarded to THS (supported set only). Default None =
            THS default (currently ``"change_pct"``).
        sort_order: ``"asc"`` / ``"desc"``. Default ``"desc"``.
        top_n: Max AJAX rows. Default 50; THS's upstream hard cap for that
            endpoint is also 50.

    Returns:
        6-tuple ``(stocks, origin, effective_source, reason,
        quote_truncated, quote_total_in_board)``:
          - ``stocks`` — the row dicts served.
          - ``origin`` — ``"persistence"`` (cache hit) or the serving
            fetcher slug.
          - ``effective_source`` — the slug that served. With no
            cross-source fallback left this always equals ``source``
            (the cache-hit path used to hardcode ``"ths"``).
          - ``reason`` — ``"cid_unresolved"`` when the AJAX tier could not
            address the board (route maps it to HTTP 422);
            ``"stale_after_upstream_failure"`` when a stale cache copy was
            served; ``None`` otherwise (route maps an empty result with no
            reason to HTTP 404).
          - ``quote_truncated`` — ``len(stocks) >= top_n`` on the AJAX
            tier: True means "possibly cut off at the cap", which is the
            honest answer even for a board that genuinely has exactly
            ``top_n`` members. Always False on the F10 tier.
          - ``quote_total_in_board`` — best-effort count; the larger of
            the pre-refresh cache size and what we are returning.
    """
    init_schema()

    # Both the tracker key and the cache read are per-source: a ths request
    # and a zzshare request for the same board_code are different boards
    # (disjoint code spaces), so neither may read the other's rows.
    needs_refresh = (
        include_quote or refresh or _refresh_tracker.is_first_call(f"{board_code}:{source}")
    )

    cached_full = _read_board_stocks_from_db(board_code, source)
    cached_count = len(cached_full)

    if not needs_refresh and cached_full:
        # Cache hit: the upstream that originally wrote the row
        # is not surfaced here. The route layer reports
        # ``origin="persistence"``; clients that need the actual
        # upstream should pass ?refresh=true.
        # effective_source is the ROW's source, not a hardcoded "ths" —
        # pre-split a zzshare request that hit the cache was signed ths.
        return cached_full, "persistence", source, None, False, cached_count

    if manager is None:
        raise ValueError("manager is required when refresh=True or cache miss")

    # board_type picks THS's /thshy/ vs /gn/ section, and the F10
    # extraction strategy. Only ths rows have one.
    _meta = get_board_metadata(board_code, source)
    board_type_resolved = _meta.get("board_type") if _meta else None

    if not include_quote:
        # One source, one leg, no cross-source fallback (spec §2 D2):
        #   ths      → the F10 page: full membership (90+ concept /
        #              150-180 industry), platecode-addressed, no quote
        #              columns, no 50-row cap.
        #   others   → their own constituent endpoint, board_code-addressed.
        try:
            if source == "ths":
                stocks, origin = manager.get_board_stocks_full(
                    board_code=board_code,
                    source=source,
                    board_type=board_type_resolved,
                )
            else:
                stocks, origin = manager.get_board_stocks(
                    board_code=board_code,
                    source=source,
                    include_quote=False,
                    board_type=board_type_resolved,
                )
        except DataFetchError as e:
            if cached_full:
                logger.warning(
                    f"[BoardCache] Upstream failed for {board_code} "
                    f"(include_quote=False), serving {len(cached_full)} stale "
                    f"stocks: {e}"
                )
                return (
                    cached_full,
                    "persistence",
                    source,
                    "stale_after_upstream_failure",
                    False,
                    cached_count,
                )
            raise
        if stocks:
            update_cached_board_stocks(board_code, source, stocks)
        return stocks, origin, source, None, False, cached_count

    # include_quote=True. THS's AJAX endpoint is cid-addressed
    # (q.10jqka.com.cn/{section}/detail/code/{slug}/ — the slug is the cid,
    # NOT the public platecode) and hard-caps at 50 rows. eastmoney
    # (BKxxxx) and zhitu (sw_xxx) take their own board_code straight
    # through, so the translation below is THS-only.
    fetch_code = board_code
    fetch_kwargs: dict = {}
    if source == "ths":
        fetch_code = resolve_ths_cid(board_code) or ""
        if not fetch_code:
            # An unresolvable cid is reported as reason="cid_unresolved"
            # (the route maps it to 422) instead of an empty 404: "we
            # cannot address this board" and "this board has no members"
            # are different answers.
            return [], source, source, "cid_unresolved", False, cached_count
        fetch_kwargs = {"sort_by": sort_by, "sort_order": sort_order, "top_n": top_n}

    stocks, origin = manager.get_board_stocks(
        board_code=fetch_code,
        source=source,
        include_quote=True,
        board_type=board_type_resolved,
        **fetch_kwargs,
    )

    if not stocks:
        return [], origin, source, None, False, cached_count

    # Union-fill quote fields from the /stocks full-market quote cache.
    # THS's 14 AJAX columns lack open/high/low/prev_close/volume; the cache
    # supplies them without a second upstream call.
    cached_quotes = get_cached_market_quotes(manager)
    if cached_quotes:
        stocks = _enrich_rows_with_market_quote(stocks, cached_quotes)

    update_cached_board_stocks(board_code, source, stocks)
    quote_truncated = len(stocks) >= top_n
    return stocks, origin, source, None, quote_truncated, max(cached_count, len(stocks))


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
        ``{board_code: {"board_type": str | None, "subtype": str | None}}``
        for codes present in the ``stock_board`` cache. Codes absent from the
        table are simply not in the result; callers should default-fill.
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
        row["code"]: {"board_type": row["board_type"], "subtype": row["subtype"]}
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
            "board_code": r["board_code"],
            # Authoritative name/type/subtype from stock_board when present;
            # otherwise the membership row's stored value (legacy fallback).
            "name": r["sb_name"] if r["sb_name"] is not None else r["board_name"],
            "board_type": (
                r["sb_board_type"] if r["sb_board_type"] is not None else r["board_type"]
            ),
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
        entries = [e for e in entries if e["board_type"] == type]
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


def get_board_metadata(board_code: str, source: str) -> dict[str, Any] | None:
    """Look up full board metadata from the SQLite cache.

    Same fast-path semantics as :func:`get_board_name` — single-row read
    against ``stock_board``, matching on the public ``code`` column. No
    upstream fallback; returns ``None`` on cache miss.

    Args:
        board_code: Public board code (e.g. ``"BK1048"`` or ``"885595"``).
        source: Data source slug (``"ths"``, ``"eastmoney"``, etc.).

    Returns:
        A board row dict — ``{"name", "board_type", "subtype",
        "board_code", "ths_cid"}`` — or ``None`` on cache miss.
        ``board_type`` and ``subtype`` mirror the cache columns verbatim
        (may be an empty string for older rows where the column was added
        in a forward-compat migration). ``board_code`` is the cross-source
        public board identifier (THS platecode 885xxx/886xxx/881xxx,
        eastmoney BKxxxx, zhitu sw_xxx). ``ths_cid`` is THS's internal
        concept cid (3xxxxx), or ``board_code`` itself for THS industry
        (881xxx); NULL for eastmoney / zhitu rows.

        Key names follow the board-path naming contract (spec §5.1): rows
        use ``board_code`` / ``ths_cid`` / ``board_type``, never a bare
        ``code`` / ``cid`` / ``type``. See also the pre-2026-09-11 rename
        in ``docs/superpowers/plans/2026-09-11-board-source-split-plan-2-internal.md``.
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
        "board_type": row["board_type"],
        "subtype": row["subtype"] or "",
        "board_code": row["code"],
        "ths_cid": row["cid"],
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
                (b["name"] for b in boards if board_code == b.get("board_code")),
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
            "board_code": row["code"],
            "name": row["name"],
            "board_type": row["board_type"],
            "subtype": row["subtype"],
            "source": row["source"],
            # The single canonical key for THS's internal cid. Non-THS
            # sources carry NULL by construction (spec §4 rule 3), so a
            # caller can read this without knowing which source it came
            # from.
            "ths_cid": row["cid"],
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


def _is_ths_cid(value: Any) -> bool:
    """True iff ``value`` is a THS board cid.

    A THS cid is either a concept cid (3xxxxx) or an industry cid
    (881xxx — identical to its platecode). Everything else is rejected.
    The legacy ``stock_board_ths.csv`` stores 118 concept rows whose
    ``cid`` column is not a cid at all: 110 of them are THS platecodes
    (885×98 / 886×12 / 883×1, from the pre-2026-07-20 layout) and only 8
    are zzshare codes (803×6 / 710×1). None of the 118 is a mapping
    (spec §3.1) — this guard is also what keeps those 110 platecode-shaped
    values out of ``ths_cid`` when the CSV is split (spec §4 rule 6).
    """
    if not isinstance(value, str) or len(value) != 6:
        return False
    # isascii() guards against fullwidth digits, which str.isdigit() accepts.
    if not (value.isascii() and value.isdigit()):
        return False
    return value.startswith("3") or value.startswith("881")


def upsert_ths_board_id_map(
    rows: list[dict], conn: sqlite3.Connection | None = None
) -> int:
    """Upsert THS ``cid → platecode`` mappings. Returns the rows written.

    Rows whose ``cid`` fails :func:`_is_ths_cid`, or that carry no
    platecode, are skipped silently (the caller's row count is the
    diagnostic). Last write wins, so callers merge *live* observations
    after CSV seeds — the CSV is a snapshot, live data is authoritative
    (spec §3.2).
    """
    if not rows:
        return 0
    init_schema()
    if conn is None:
        conn = get_connection()
    payload = [
        (
            r["cid"],
            r["platecode"],
            r.get("name") or "",
            r.get("board_type") or "",
        )
        for r in rows
        if _is_ths_cid(r.get("cid")) and r.get("platecode")
    ]
    if not payload:
        return 0
    with conn:
        conn.cursor().executemany(
            """INSERT OR REPLACE INTO ths_board_id_map
               (cid, platecode, name, board_type, observed_at)
               VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)""",
            payload,
        )
    return len(payload)


def resolve_ths_platecode(ths_cid: str) -> str | None:
    """Return the THS platecode for a THS cid, or ``None`` when unmapped.

    Single SELECT. This helper is the only sanctioned cid → platecode
    lookup (spec §3.2) — callers must not rebuild the relation ad hoc
    (that is how the by-board-name join ended up conflating two code
    spaces).
    """
    if not ths_cid:
        return None
    init_schema()
    row = get_connection().execute(
        "SELECT platecode FROM ths_board_id_map WHERE cid = ?", (ths_cid,)
    ).fetchone()
    return row["platecode"] if row else None


def get_ths_board_id_map_rows() -> list[dict[str, Any]]:
    """All mappings ordered by cid (CSV export / tool / test use)."""
    init_schema()
    rows = get_connection().execute(
        "SELECT cid, platecode, name, board_type, observed_at "
        "FROM ths_board_id_map ORDER BY cid"
    ).fetchall()
    return [dict(r) for r in rows]


def update_cached_boards(board_type: str, source: str, boards: list) -> int:
    """
    Replace cached boards metadata for a (board_type, source) pair.

    **Snapshot replace: rows for this ``(board_type, source)`` pair are
    deleted before insert.** Pre-2026-09-11 there was no DELETE, so a board
    that disappeared upstream lingered forever, and a board first observed
    under a cid-shaped key and later under a platecode-shaped key ended up
    stored twice and never merged (spec §1.3, mechanism 3). Mirrors
    ``update_cached_board_stocks``' DELETE-then-INSERT contract.

    Only stores metadata (board_code, name, board_type, source, timestamp,
    and the THS cid). Realtime quote data is always fetched from the API,
    never cached in SQLite.

    Args:
        board_type: "concept" or "industry"
        source: Data source slug
        boards: List of board row dicts [{"board_code": "BK1048",
            "name": "互联网服务", "board_type": "industry", "ths_cid": None}, ...]

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

            cursor.execute(
                "DELETE FROM stock_board WHERE board_type = ? AND source = ?",
                (board_type, source),
            )

            cursor.executemany(
                """INSERT OR REPLACE INTO stock_board
                (code, name, board_type, subtype, source, cid, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        # `code` (SQL column) = the cross-source public
                        # identifier — THS platecode / eastmoney BKxxxx /
                        # zhitu sw_xxx. It is a REQUIRED field on every
                        # board row (fetchers all emit it).
                        b["board_code"],
                        b["name"],
                        board_type,
                        b.get("subtype") or "",
                        source,
                        # `cid` (SQL column) = THS's internal cid. Only THS
                        # rows may carry one (spec §4 rule 3): for concept
                        # boards it is a 3xxxxx distinct from board_code,
                        # for industry it equals board_code (881xxx).
                        # `.get` rather than `[...]` on purpose — a fetcher
                        # that forgot to emit ths_cid should degrade to
                        # NULL, never KeyError the whole board-list write.
                        b.get("ths_cid") if source == "ths" else None,
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
