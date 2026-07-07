"""验证 persistence 方法返回 (data, origin) 元组。

Tasks 2, 3 & 4 of the source-tracking implementation plan: the persistence
layer methods must return ``(data, origin)`` tuples so the API layer
can report whether a response came from cache ("persistence") or was
freshly fetched from a fetcher (fetcher name, e.g. "akshare").

This file covers:
- ``trade_calendar.get_cached_calendar`` — returns ``(dates, origin)``
- ``pool_daily.get_pool`` — returns ``(stocks, origin)``
- ``board.get_board_list`` — returns ``(boards, origin)``
- ``board.get_board_stocks`` — returns ``(stocks, origin)``
- ``stock_list.get_stock_list`` — returns ``(stocks, origin)``

Reference: ``docs/superpowers/plans/2026-06-12-source-tracking.md``
"""
from stock_data.data_provider.persistence import board, trade_calendar
from unittest.mock import patch

import pytest


def test_get_cached_calendar_returns_tuple():
    """trade_calendar.get_cached_calendar 应该返回 (dates, origin)."""
    dates, origin = trade_calendar.get_cached_calendar()
    assert origin in ("persistence", "")  # 命中是 persistence, 空是 ""
    assert isinstance(dates, list)


def test_get_pool_returns_tuple(monkeypatch):
    """pool_daily.get_pool 应该返回 (stocks, origin)."""
    from stock_data.data_provider.persistence.pool_daily import get_pool

    # Mock manager: 不实际调上游
    class _MockManager:
        def get_zt_pool_raw(self, pool_type, date):
            return ([{"code": "000001", "name": "测试"}], "mock_fetcher")

    stocks, origin = get_pool(
        pool_type="zt", date="2026-01-01", manager=_MockManager(), refresh=True
    )
    # refresh=True 强制走 fetcher, origin 应该是 fetcher 路径
    assert origin != ""
    assert isinstance(stocks, list)


def test_get_board_list_returns_tuple(monkeypatch):
    """board.get_board_list 应该返回 (boards, origin)."""
    # Mock manager
    class _MockManager:
        def get_all_boards(self, source="eastmoney", board_type="concept", include_quote=False, **_):
            if board_type == "concept":
                return ([{"code": "BK0001", "name": "测试板块"}], "mock_fetcher")
            return ([], "")

    # 跳过 SQLite, 强制走 fetcher 路径
    monkeypatch.setattr(
        board,
        "_refresh_tracker",
        type("T", (), {"is_first_call": lambda *a: True})(),
    )
    boards, origin = board.get_board_list(
        "concept", "eastmoney", refresh=True, manager=_MockManager()
    )
    assert isinstance(boards, list)
    assert origin == "mock_fetcher"


def test_get_board_stocks_returns_tuple(monkeypatch):
    """board.get_board_stocks 应该返回 (stocks, origin)."""
    # Mock manager — unified entry point only.
    # Phase 4 (2026-07-02): real manager now also accepts ``board_type=`` to
    # steer the fetcher; ``**_`` keeps the mock interface-compatible for any
    # future kwargs (e.g. include_quote stays positional too).
    class _MockManager:
        def get_board_stocks(self, board_code, source="eastmoney", include_quote=False, **_):
            return ([{"stock_code": "600519", "stock_name": "贵州茅台"}], "mock_fetcher")

    # 跳过 SQLite, 强制走 fetcher 路径
    monkeypatch.setattr(
        board,
        "_refresh_tracker",
        type("T", (), {"is_first_call": lambda *a: True})(),
    )
    stocks, origin = board.get_board_stocks(
        "BK0001", "eastmoney", refresh=True, manager=_MockManager()
    )
    assert isinstance(stocks, list)
    assert origin == "mock_fetcher"


def test_get_stock_list_returns_tuple(monkeypatch):
    """stock_list.get_stock_list 应该返回 (stocks, origin)."""
    from stock_data.data_provider.persistence import stock_list

    class _MockManager:
        def get_all_stocks(self, market):
            return ([{"code": "000001", "name": "测试"}], "mock_fetcher")

    # 强制走 fetcher 路径
    monkeypatch.setattr(
        stock_list,
        "_refresh_tracker",
        type("T", (), {"is_first_call": lambda *a: True})(),
    )
    stocks, origin = stock_list.get_stock_list(
        "csi", refresh=True, manager=_MockManager()
    )
    assert isinstance(stocks, list)
    assert origin == "mock_fetcher"


# ===== Subtype round-trip + filter (regression for source-tracking wiring) =====


def test_board_list_subtype_round_trip(tmp_path, monkeypatch):
    """subtype field survives write (update_cached_boards) → read (_read_boards_from_db).

    Uses a temp DB so the test is hermetic and doesn't depend on the project's
    real stock_cache.db. We point db.get_db_path at the temp file AND reset
    the module-level connection singleton so the next get_connection() opens
    a fresh sqlite3 handle against the new path.
    """
    from stock_data.data_provider.persistence import db

    db_file = tmp_path / "board_subtype_test.db"
    monkeypatch.setattr(db, "get_db_path", lambda: db_file)
    monkeypatch.setattr(db, "_conn", None)
    monkeypatch.setattr(db, "_db_path", None)

    # Force re-init against the new path
    import stock_data.data_provider.persistence.board as board_mod
    board_mod._schema_initialized_paths.clear()

    # Write boards with mixed subtypes
    boards = [
        {"code": "BK0001", "name": "板块A", "subtype": "热门概念"},
        {"code": "BK0002", "name": "板块B", "subtype": "概念板块"},
        {"code": "BK0003", "name": "板块C", "subtype": "热门概念"},
    ]
    board_mod.update_cached_boards("concept", "zhitu", boards)

    # Read back — all rows present, subtype preserved
    all_rows = board_mod._read_boards_from_db("concept", "zhitu")
    assert len(all_rows) == 3
    assert {r["subtype"] for r in all_rows} == {"热门概念", "概念板块"}

    # Subtype filter narrows the result
    hot = board_mod._read_boards_from_db("concept", "zhitu", subtype="热门概念")
    assert len(hot) == 2
    assert {r["code"] for r in hot} == {"BK0001", "BK0003"}
    assert all(r["subtype"] == "热门概念" for r in hot)

    # Subtype filter with no matches → empty list
    empty = board_mod._read_boards_from_db("concept", "zhitu", subtype="nonexistent")
    assert empty == []


def test_get_board_list_always_fetches_full_then_filters(tmp_path, monkeypatch):
    """Cache miss with subtype=X: fetcher is called with subtype=None (full
    list), then result is narrowed in-memory before returning.
    """
    from stock_data.data_provider.persistence import db

    db_file = tmp_path / "board_subtype_filter_test.db"
    monkeypatch.setattr(db, "get_db_path", lambda: db_file)
    monkeypatch.setattr(db, "_conn", None)
    monkeypatch.setattr(db, "_db_path", None)

    import stock_data.data_provider.persistence.board as board_mod
    board_mod._schema_initialized_paths.clear()

    # Mock manager — returns full set with subtype tags
    class _MockManager:
        def get_all_boards(self, source, board_type, subtype=None, include_quote=False):
            assert subtype is None, "persistence should always fetch full list"
            return (
                [
                    {"code": "BK0001", "name": "板块A", "subtype": "热门概念"},
                    {"code": "BK0002", "name": "板块B", "subtype": "概念板块"},
                ],
                "MockFetcher",
            )

    # Force cache miss (tracker says first call of day)
    monkeypatch.setattr(
        board_mod,
        "_refresh_tracker",
        type("T", (), {"is_first_call": lambda *a: True})(),
    )

    # With subtype filter: fetcher called full, result narrowed before return
    boards, origin = board_mod.get_board_list(
        "concept", "zhitu", subtype="热门概念", manager=_MockManager()
    )
    assert origin == "MockFetcher"
    assert len(boards) == 1
    assert boards[0]["code"] == "BK0001"


def test_get_board_list_cache_hit_with_subtype_filter(tmp_path, monkeypatch):
    """Cache hit with subtype=X: SQL filters at read time, no fetcher call.

    Pre-populate the cache, then request with a subtype filter. The fetcher
    must NOT be called because the (board_type, source) key was already
    refreshed today.
    """
    from stock_data.data_provider.persistence import db

    db_file = tmp_path / "board_cache_hit_subtype.db"
    monkeypatch.setattr(db, "get_db_path", lambda: db_file)
    monkeypatch.setattr(db, "_conn", None)
    monkeypatch.setattr(db, "_db_path", None)

    import stock_data.data_provider.persistence.board as board_mod
    board_mod._schema_initialized_paths.clear()

    # Pre-populate the cache directly (simulating a previous fresh fetch)
    board_mod.update_cached_boards(
        "concept",
        "zhitu",
        [
            {"code": "BK0001", "name": "板块A", "subtype": "热门概念"},
            {"code": "BK0002", "name": "板块B", "subtype": "概念板块"},
        ],
    )

    # Fetcher that should NOT be called on cache hit
    fetcher_called = {"count": 0}

    class _SpyManager:
        def get_all_boards(self, **_):
            fetcher_called["count"] += 1
            return ([], "ShouldNotBeCalled")

    # Tracker says NOT first call today → cache eligible
    monkeypatch.setattr(
        board_mod,
        "_refresh_tracker",
        type("T", (), {"is_first_call": lambda *a: False})(),
    )

    boards, origin = board_mod.get_board_list(
        "concept", "zhitu", subtype="热门概念", manager=_SpyManager()
    )
    assert origin == "persistence", "second call on same day must hit cache"
    assert fetcher_called["count"] == 0, "fetcher must NOT be called on cache hit"
    assert len(boards) == 1
    assert boards[0]["code"] == "BK0001"


def test_get_board_list_refresh_bypasses_cache(tmp_path, monkeypatch):
    """refresh=True forces fetcher call even when cache is populated."""
    from stock_data.data_provider.persistence import db

    db_file = tmp_path / "board_refresh_test.db"
    monkeypatch.setattr(db, "get_db_path", lambda: db_file)
    monkeypatch.setattr(db, "_conn", None)
    monkeypatch.setattr(db, "_db_path", None)

    import stock_data.data_provider.persistence.board as board_mod
    board_mod._schema_initialized_paths.clear()

    # Pre-populate cache
    board_mod.update_cached_boards(
        "concept", "zzshare",
        [{"code": "OLD01", "name": "old", "subtype": "同花顺概念"}],
    )

    class _MockManager:
        def get_all_boards(self, source, board_type, subtype=None, include_quote=False):
            return (
                [{"code": "NEW01", "name": "new", "subtype": "同花顺概念"}],
                "ZzshareFetcher",
            )

    boards, origin = board_mod.get_board_list(
        "concept", "zzshare", refresh=True, manager=_MockManager()
    )
    assert origin == "ZzshareFetcher"
    assert boards[0]["code"] == "NEW01"


def test_eastmoney_boards_have_subtype_tagged():
    """Regression: EastMoneyFetcher tags boards with subtype=board_type so the
    persistence layer has a uniform shape across sources.
    """
    from unittest.mock import patch

    from stock_data.data_provider.fetchers.eastmoney_fetcher import EastMoneyFetcher

    fetcher = object.__new__(EastMoneyFetcher)  # bypass __init__ (no network)

    with patch.object(
        EastMoneyFetcher,
        "get_all_concept_boards",
        return_value=[{"code": "BK0001", "name": "互联网"}],
    ):
        boards = fetcher.get_all_boards(board_type="concept")
    assert len(boards) == 1
    assert boards[0]["subtype"] == "concept"  # tagged by get_all_boards entry


# =============================================================================
# All-types (board_type=None) persistence behavior
# =============================================================================
# The route now accepts ``?type=`` as optional. When omitted, the persistence
# layer must:
# 1. Iterate over every type the source exposes (per VALID_SUBTYPES_BY_SOURCE)
# 2. Write each type's boards to its own (board_type, source) cache slot
# 3. Tag every returned row with its ``type`` field so callers can split
# 4. Report origin as "persistence" / fetcher-name / "merged" honestly


def test_get_board_list_all_types_persists_each_type_separately(tmp_path, monkeypatch):
    """All-types query: every (board_type, source) cache slot is populated.

    Regression for the user-reported bug: querying boards without a type
    filter must result in correct persistence writes for every type the
    source exposes. Each type is written to its own UNIQUE(code, source)
    row in stock_board, so reading back with a single-type filter must
    return only that type's boards.
    """
    from stock_data.data_provider.persistence import db

    db_file = tmp_path / "all_types_persist.db"
    monkeypatch.setattr(db, "get_db_path", lambda: db_file)
    monkeypatch.setattr(db, "_conn", None)
    monkeypatch.setattr(db, "_db_path", None)

    import stock_data.data_provider.persistence.board as board_mod
    board_mod._schema_initialized_paths.clear()

    # Fetcher returns per-type boards (board_type=None branch).
    # zzshare has only industry + concept (plate=17 "题材" is unified under
    # concept with subtype="同花顺题材" retained). The mock mirrors the
    # new fetcher shape: one concept row per upstream subtype.
    class _MockManager:
        def get_all_boards(self, source, board_type, subtype=None, include_quote=False):
            rows = {
                "concept": [
                    {"code": "BK_C1", "name": "概念1", "type": "concept", "subtype": "同花顺概念"},
                    {"code": "BK_C2", "name": "题材1", "type": "concept", "subtype": "同花顺题材"},
                ],
                "industry": [
                    {"code": "BK_I1", "name": "行业1", "type": "industry", "subtype": "同花顺行业"},
                ],
            }
            return rows.get(board_type, []), "MockFetcher"

    # Force cache miss (tracker says first call of day, per type)
    monkeypatch.setattr(
        board_mod,
        "_refresh_tracker",
        type("T", (), {"is_first_call": lambda *a: True})(),
    )

    # All-types query (board_type=None) for zzshare (concept/industry only)
    boards, origin = board_mod.get_board_list(
        None, "zzshare", refresh=True, manager=_MockManager()
    )
    assert origin == "MockFetcher"
    assert len(boards) == 3
    by_code = {b["code"]: b for b in boards}
    assert by_code["BK_C1"]["type"] == "concept"
    assert by_code["BK_C2"]["type"] == "concept"  # plate=17 unified under concept
    assert by_code["BK_C2"]["subtype"] == "同花顺题材"
    assert by_code["BK_I1"]["type"] == "industry"

    # Verify each type was actually persisted to its own slot.
    concept_rows = board_mod._read_boards_from_db("concept", "zzshare")
    industry_rows = board_mod._read_boards_from_db("industry", "zzshare")
    assert {r["code"] for r in concept_rows} == {"BK_C1", "BK_C2"}
    assert {r["code"] for r in industry_rows} == {"BK_I1"}
    # The board_type column in the DB matches the per-type cache slot.
    assert {r["board_type"] for r in concept_rows} == {"concept"}
    assert {r["board_type"] for r in industry_rows} == {"industry"}
    # zzshare no longer has a "special" slot.
    special_rows = board_mod._read_boards_from_db("special", "zzshare")
    assert special_rows == []


def test_get_board_list_all_types_summary_origin_persistence(tmp_path, monkeypatch):
    """All-types query, every type cache-hit → origin='persistence'."""
    from stock_data.data_provider.persistence import db

    db_file = tmp_path / "all_types_cache_hit.db"
    monkeypatch.setattr(db, "get_db_path", lambda: db_file)
    monkeypatch.setattr(db, "_conn", None)
    monkeypatch.setattr(db, "_db_path", None)

    import stock_data.data_provider.persistence.board as board_mod
    board_mod._schema_initialized_paths.clear()

    # Pre-populate every supported type for zzshare (concept + industry only;
    # the old "special" type was unified into concept on 2026-07-07).
    for bt, code in [("concept", "BK_C"), ("industry", "BK_I")]:
        board_mod.update_cached_boards(
            bt, "zzshare", [{"code": code, "name": bt, "subtype": bt}]
        )

    # Fetcher that must NOT be called (cache hit on every type)
    fetcher_called = {"count": 0}

    class _SpyManager:
        def get_all_boards(self, **_):
            fetcher_called["count"] += 1
            return ([], "ShouldNotBeCalled")

    # Tracker: every (type, source) pair has been refreshed today
    monkeypatch.setattr(
        board_mod,
        "_refresh_tracker",
        type("T", (), {"is_first_call": lambda *a: False})(),
    )

    boards, origin = board_mod.get_board_list(
        None, "zzshare", manager=_SpyManager()
    )
    assert origin == "persistence"
    assert fetcher_called["count"] == 0
    # 2 boards: one concept + one industry (zzshare dropped special on 2026-07-07)
    assert len(boards) == 2


def test_get_board_list_all_types_mixed_origin(tmp_path, monkeypatch):
    """All-types query with one type cache-hit and the others cache-miss → 'merged'."""
    from stock_data.data_provider.persistence import db

    db_file = tmp_path / "all_types_mixed.db"
    monkeypatch.setattr(db, "get_db_path", lambda: db_file)
    monkeypatch.setattr(db, "_conn", None)
    monkeypatch.setattr(db, "_db_path", None)

    import stock_data.data_provider.persistence.board as board_mod
    board_mod._schema_initialized_paths.clear()

    # Pre-populate only concept
    board_mod.update_cached_boards(
        "concept", "zzshare", [{"code": "BK_C", "name": "c", "subtype": "同花顺概念"}]
    )

    class _MockManager:
        def get_all_boards(self, source, board_type, subtype=None, include_quote=False):
            return (
                [{"code": f"BK_{board_type[0].upper()}", "name": board_type, "type": board_type}],
                "MockFetcher",
            )

    # Tracker: concept has been refreshed today (cache eligible),
    # industry has not → cache miss on that one. zzshare's "special" type
    # was unified into concept on 2026-07-07, so it's no longer in the
    # supported set.
    def _is_first_call(self, key: str) -> bool:
        return not key.startswith("concept:")

    monkeypatch.setattr(
        board_mod,
        "_refresh_tracker",
        type("T", (), {"is_first_call": _is_first_call})(),
    )

    boards, origin = board_mod.get_board_list(
        None, "zzshare", manager=_MockManager()
    )
    # concept hits cache (persistence), industry hits fetcher (MockFetcher).
    # Summary must honestly reflect the mix. The label is "mixed" — aligned
    # with get_stock_memberships.
    assert origin == "mixed"
    assert len(boards) == 2
    by_code = {b["code"]: b for b in boards}
    assert by_code["BK_C"]["type"] == "concept"  # cache hit
    assert by_code["BK_I"]["type"] == "industry"  # fetcher hit


def test_get_board_list_all_types_rejects_subtype(tmp_path, monkeypatch):
    """subtype filter is rejected for the all-types variant.

    Subtypes are scoped per (source, type). The all-types branch
    intentionally does not support subtype filtering because there's
    no single type to validate against — the caller must split the
    response and filter client-side, or re-query with ``type=`` set.
    """
    from stock_data.data_provider.persistence import db

    db_file = tmp_path / "all_types_subtype_reject.db"
    monkeypatch.setattr(db, "get_db_path", lambda: db_file)
    monkeypatch.setattr(db, "_conn", None)
    monkeypatch.setattr(db, "_db_path", None)

    import stock_data.data_provider.persistence.board as board_mod
    board_mod._schema_initialized_paths.clear()

    class _MockManager:
        def get_all_boards(self, **_):
            return ([], "ShouldNotBeCalled")

    with pytest.raises(ValueError, match="subtype"):
        board_mod.get_board_list(
            None, "zzshare", subtype="同花顺概念", manager=_MockManager()
        )


def test_get_board_list_all_types_skips_unsupported_types():
    """zzshare has no 'index' type — all-types query must NOT call the
    manager for it (the per-source subtype table is the source of truth)."""

    import stock_data.data_provider.persistence.board as board_mod

    called_types: list[str] = []

    class _MockManager:
        def get_all_boards(self, source, board_type, subtype=None, include_quote=False):
            called_types.append(board_type)
            return (
                [{"code": f"BK_{board_type}", "name": board_type, "type": board_type}],
                "MockFetcher",
            )

    # Force cache miss
    board_mod._refresh_tracker = type("T", (), {"is_first_call": lambda self, *a: True})()

    boards, origin = board_mod.get_board_list(
        None, "zzshare", refresh=True, manager=_MockManager()
    )
    # zzshare's subtype table: concept / industry only (no index, no special
    # — plate=17 unified under concept on 2026-07-07)
    assert set(called_types) == {"concept", "industry"}
    assert "index" not in called_types
    assert "special" not in called_types
    assert len(boards) == 2


def test_get_board_list_all_types_include_quote_bypasses_cache(tmp_path, monkeypatch):
    """``include_quote=True`` forces a network call for *every* type,
    regardless of cache state.

    The all-types branch loops over each supported type and delegates to
    ``get_board_list(type, source, include_quote=True, ...)``. Because
    ``include_quote=True`` flips ``needs_refresh`` to True unconditionally,
    cache state is ignored — every type hits the fetcher.
    """
    from stock_data.data_provider.persistence import db

    db_file = tmp_path / "all_types_include_quote.db"
    monkeypatch.setattr(db, "get_db_path", lambda: db_file)
    monkeypatch.setattr(db, "_conn", None)
    monkeypatch.setattr(db, "_db_path", None)

    import stock_data.data_provider.persistence.board as board_mod
    board_mod._schema_initialized_paths.clear()

    # Pre-populate every supported type (so a cache-hit path would otherwise be
    # available). include_quote=True must bypass this and re-fetch. zzshare's
    # supported set dropped "special" on 2026-07-07 (plate=17 unified under
    # concept).
    for bt in ("concept", "industry"):
        board_mod.update_cached_boards(
            bt, "zzshare", [{"code": f"OLD_{bt}", "name": "old", "subtype": bt}]
        )

    fetcher_calls: list[str] = []

    class _SpyManager:
        def get_all_boards(self, source, board_type, subtype=None, include_quote=False):
            fetcher_calls.append(board_type)
            return (
                [
                    {
                        "code": f"NEW_{board_type}",
                        "name": "fresh",
                        "type": board_type,
                        "subtype": "同花顺" + ("概念" if bt_short(board_type) == "concept"
                                              else "行业" if bt_short(board_type) == "industry"
                                              else "题材"),
                        "price": 100.0,
                        "change_pct": 1.5,
                    }
                ],
                "MockFetcher",
            )

    # Tracker says every (type, source) was already refreshed today —
    # without include_quote, all would be cache hits.
    board_mod._refresh_tracker = type("T", (), {"is_first_call": lambda self, *a: False})()

    boards, origin = board_mod.get_board_list(
        None, "zzshare", include_quote=True, manager=_SpyManager()
    )
    # Fetcher was called for every supported type, not bypassed. "special" no
    # longer in the supported set after the 2026-07-07 unification.
    assert set(fetcher_calls) == {"concept", "industry"}
    assert "special" not in fetcher_calls
    # Origin reflects the fetcher, not persistence.
    assert origin == "MockFetcher"
    # New data wins over old cached data.
    assert {b["code"] for b in boards} == {"NEW_concept", "NEW_industry"}


def bt_short(bt: str) -> str:
    return bt


def test_get_board_list_cache_hit_rows_carry_type_field(tmp_path, monkeypatch):
    """Cache-hit rows must carry the ``type`` key (post-review contract).

    Regression for H1: previously ``_read_boards_from_db`` projected the
    SQL column as ``board_type`` while the fresh fetcher path used
    ``type``. The route had to ``b.get("type") or b.get("board_type")``
    to bridge the gap. The fix is to project the column as ``type`` in
    the cache result so all rows — fresh and cached — share the same
    key.
    """
    from stock_data.data_provider.persistence import db

    db_file = tmp_path / "cache_hit_type_key.db"
    monkeypatch.setattr(db, "get_db_path", lambda: db_file)
    monkeypatch.setattr(db, "_conn", None)
    monkeypatch.setattr(db, "_db_path", None)

    import stock_data.data_provider.persistence.board as board_mod
    board_mod._schema_initialized_paths.clear()

    # Write boards to the cache.
    board_mod.update_cached_boards(
        "concept", "zzshare",
        [{"code": "BK_C", "name": "c", "subtype": "同花顺概念"}],
    )

    # Read back via the internal helper that the cache-hit path uses.
    rows = board_mod._read_boards_from_db("concept", "zzshare")
    assert len(rows) == 1
    assert rows[0]["type"] == "concept"
    # board_type is also retained as a backwards-compat alias.
    assert rows[0]["board_type"] == "concept"

    # End-to-end: a get_board_list cache hit also surfaces ``type``.
    class _SpyManager:
        def get_all_boards(self, **_):
            raise AssertionError("cache hit must not call the fetcher")

    board_mod._refresh_tracker = type("T", (), {"is_first_call": lambda self, *a: False})()
    boards, origin = board_mod.get_board_list(
        "concept", "zzshare", manager=_SpyManager()
    )
    assert origin == "persistence"
    assert boards[0]["type"] == "concept"


def test_init_schema_migrates_zzshare_special_rows_to_concept(tmp_path, monkeypatch):
    """Pre-existing zzshare/special rows must be rewritten to type=concept
    on the next ``init_schema()`` call so persisted data matches the new
    unified schema (plate=15 + plate=17 both → concept). The migration
    must touch both ``stock_board`` and ``stock_board_membership``, and
    must preserve the ``subtype`` so callers can still tell 概念 vs 题材
    apart. It must be idempotent — running twice is a no-op.
    """
    from stock_data.data_provider.persistence import db

    db_file = tmp_path / "zzshare_special_migration.db"
    monkeypatch.setattr(db, "get_db_path", lambda: db_file)
    monkeypatch.setattr(db, "_conn", None)
    monkeypatch.setattr(db, "_db_path", None)

    import stock_data.data_provider.persistence.board as board_mod
    board_mod._schema_initialized_paths.clear()

    # Seed the DB with rows that match the OLD shape (board_type='special',
    # subtype='同花顺题材') so the migration has something to rewrite.
    board_mod.update_cached_boards(
        "special",
        "zzshare",
        [
            {"code": "BK_S1", "name": "题材1", "subtype": "同花顺题材"},
            {"code": "BK_S2", "name": "题材2", "subtype": "同花顺题材"},
        ],
    )
    # Membership table also needs stale rows.
    board_mod.upsert_membership_bulk(
        source="zzshare",
        stocks=[
            {"stock_code": "600000", "stock_name": "浦发银行"},
            {"stock_code": "600036", "stock_name": "招商银行"},
        ],
        board_code="BK_S1",
        board_name="题材1",
        board_type="special",
        subtype="同花顺题材",
    )

    # Sanity: rows are pre-migration as expected.
    pre_concept = board_mod._read_boards_from_db("concept", "zzshare")
    pre_special = board_mod._read_boards_from_db("special", "zzshare")
    assert {r["code"] for r in pre_special} == {"BK_S1", "BK_S2"}
    assert pre_concept == []
    conn = db.get_connection()
    pre_membership = conn.execute(
        "SELECT board_type, subtype FROM stock_board_membership "
        "WHERE source='zzshare' AND board_code='BK_S1'"
    ).fetchall()
    assert all(r["board_type"] == "special" for r in pre_membership)

    # Trigger migration: reset the schema-init cache and re-init.
    board_mod._schema_initialized_paths.clear()
    board_mod.init_schema()

    # After migration: stock_board rows are now under "concept", subtype kept.
    post_concept = board_mod._read_boards_from_db("concept", "zzshare")
    post_special = board_mod._read_boards_from_db("special", "zzshare")
    assert {r["code"] for r in post_concept} == {"BK_S1", "BK_S2"}
    assert all(r["subtype"] == "同花顺题材" for r in post_concept)
    assert all(r["type"] == "concept" for r in post_concept)
    assert post_special == []

    # After migration: stock_board_membership rows are also rewritten.
    post_membership = conn.execute(
        "SELECT board_type, subtype FROM stock_board_membership "
        "WHERE source='zzshare' AND board_code='BK_S1'"
    ).fetchall()
    assert len(post_membership) == 2
    assert all(r["board_type"] == "concept" for r in post_membership)
    assert all(r["subtype"] == "同花顺题材" for r in post_membership)

    # Idempotency: running init_schema again must not touch already-migrated
    # rows. Verify by counting rows that match the migration predicate
    # before and after — should be 0 both times.
    before_second = conn.execute(
        "SELECT COUNT(*) AS n FROM stock_board "
        "WHERE source='zzshare' AND board_type='special' "
        "AND subtype='同花顺题材'"
    ).fetchone()["n"]
    board_mod._schema_initialized_paths.clear()
    board_mod.init_schema()
    after_second = conn.execute(
        "SELECT COUNT(*) AS n FROM stock_board "
        "WHERE source='zzshare' AND board_type='special' "
        "AND subtype='同花顺题材'"
    ).fetchone()["n"]
    assert before_second == 0
    assert after_second == 0

    # The migrated rows must still be readable as concept after the second
    # init — the migration didn't drop them.
    final_concept = board_mod._read_boards_from_db("concept", "zzshare")
    assert {r["code"] for r in final_concept} == {"BK_S1", "BK_S2"}
