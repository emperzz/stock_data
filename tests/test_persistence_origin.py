"""验证 persistence 方法返回 (data, origin) 元组。

Tasks 2 & 3 of the source-tracking implementation plan: the persistence
layer methods must return ``(data, origin)`` tuples so the API layer
can report whether a response came from cache ("persistence") or was
freshly fetched from a fetcher (fetcher name, e.g. "akshare").

This file covers:
- ``trade_calendar.get_cached_calendar`` — returns ``(dates, origin)``
- ``pool_daily.get_pool`` — returns ``(stocks, origin)``
- ``board.get_board_list`` — returns ``(boards, origin)``
- ``board.get_board_stocks`` — returns ``(stocks, origin)``

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
        def get_all_concept_boards(self, source="eastmoney", include_quote=False):
            return ([{"code": "BK0001", "name": "测试板块"}], "mock_fetcher")

        def get_all_industry_boards(self, source="eastmoney", include_quote=False):
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
    # Mock manager — return_source 风格的 tuple
    class _MockManager:
        def _get_board_type(self, board_code, source):
            return None  # 走 concept/industry 兜底路径

        def get_concept_board_stocks(self, board_code, source="eastmoney", include_quote=False):
            return ([{"stock_code": "600519", "stock_name": "贵州茅台"}], "mock_fetcher")

        def get_industry_board_stocks(self, board_code, source="eastmoney", include_quote=False):
            return ([], "")

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
