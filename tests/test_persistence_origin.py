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
    class _MockManager:
        def get_board_stocks(self, board_code, source="eastmoney", include_quote=False):
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

    with patch.object(
        EastMoneyFetcher,
        "get_all_industry_boards",
        return_value=[{"code": "BK0816", "name": "银行"}],
    ):
        boards = fetcher.get_all_boards(board_type="industry")
    assert boards[0]["subtype"] == "industry"
