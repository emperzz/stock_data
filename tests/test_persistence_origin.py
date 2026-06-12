"""验证 persistence 方法返回 (data, origin) 元组。

Task 2 of the source-tracking implementation plan: the persistence
layer methods must return ``(data, origin)`` tuples so the API layer
can report whether a response came from cache ("persistence") or was
freshly fetched from a fetcher (fetcher name, e.g. "akshare").

This task covers:
- ``trade_calendar.get_cached_calendar`` — returns ``(dates, origin)``
- ``pool_daily.get_pool`` — returns ``(stocks, origin)``

Reference: ``docs/superpowers/plans/2026-06-12-source-tracking.md`` (Task 2)
"""
from stock_data.data_provider.persistence import trade_calendar


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
