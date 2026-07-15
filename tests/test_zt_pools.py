"""
Tests for ZT (涨跌停) pool API and persistence layer.

Updated during the persistence refactor (2026-06): the three legacy
per-type tables (zt_pool / dt_pool / zbgc_pool) have been merged into a
single `pool_daily` table. Tests now target the unified schema; the
old `_get_table_name` helper is gone.
"""

from unittest.mock import MagicMock, patch

import pytest

from stock_data.api.cache import (
    get_dragontiger_cache,
    get_pools_cache,
    get_quote_cache,
)
from stock_data.api.routes import reset_manager


@pytest.fixture(autouse=True)
def reset_state_and_caches():
    """Reset manager state and clear in-memory response caches before each test.

    Without clearing the in-memory `_pools_cache` (and friends), tests that
    share the same query (e.g. `?type=zt&date=2024-05-10`) interfere with
    each other — the first test writes the response into the TTL cache,
    and subsequent tests hit that entry instead of reaching the mocked
    manager.
    """
    reset_manager()
    for cache in (
        get_pools_cache(),
        get_quote_cache(),
        get_dragontiger_cache(),
    ):
        cache.clear()
    yield


@pytest.fixture
def client(app):
    # Function-scoped on purpose: each test mutates app.state via the
    # mock-patched manager, so we want a fresh client per test even though
    # `app` itself is shared (session-scoped in conftest.py).
    from fastapi.testclient import TestClient
    return TestClient(app)


class TestZTPoolAPIRoutes:
    """Tests for ZT pool API routes."""

    def test_get_zt_pools_success(self, client):
        """Test GET /api/v1/zt-pools with type=zt returns cached data."""
        with patch("stock_data.api.routes.boards.get_manager") as mock_manager:
            mock_mgr = MagicMock()
            mock_mgr.get_zt_pool.return_value = (
                [
                    {"code": "000001", "name": "平安银行", "price": 12.5, "change_pct": 10.05,
                     "lb_count": 1, "first_seal_time": "09:25:00", "last_seal_time": "09:34:33",
                     "seal_amount": 98243407, "seal_count": 0, "zt_count": "1/1", "pool_date": "2024-05-10"},
                ],
                "akshare",
                None,
            )
            mock_manager.return_value = mock_mgr

            response = client.get("/api/v1/zt-pools?type=zt&date=2024-05-10")
            assert response.status_code == 200
            data = response.json()
            assert data["type"] == "zt"
            assert data["date"] == "2024-05-10"
            assert data["total"] == 1
            assert len(data["stocks"]) == 1
            assert data["stocks"][0]["code"] == "000001"
            assert data["stocks"][0]["name"] == "平安银行"
            assert data["stocks"][0]["price"] == 12.5
            assert data["stocks"][0]["change_pct"] == 10.05
            assert data["source"] == "akshare"

    def test_get_dt_pools(self, client):
        """Test GET /api/v1/zt-pools with type=dt returns cached data."""
        with patch("stock_data.api.routes.boards.get_manager") as mock_manager:
            mock_mgr = MagicMock()
            mock_mgr.get_zt_pool.return_value = (
                [
                    {"code": "000002", "name": "万科A", "price": 8.8, "change_pct": -9.95,
                     "lb_count": 1, "pool_date": "2024-05-10"},
                ],
                "persistence",
                None,
            )
            mock_manager.return_value = mock_mgr

            response = client.get("/api/v1/zt-pools?type=dt&date=2024-05-10")
            assert response.status_code == 200
            data = response.json()
            assert data["type"] == "dt"
            assert data["total"] == 1
            assert data["stocks"][0]["change_pct"] == -9.95
            assert data["source"] == "persistence"

    def test_get_zbgc_pools(self, client):
        """Test GET /api/v1/zt-pools with type=zbgc returns cached data."""
        with patch("stock_data.api.routes.boards.get_manager") as mock_manager:
            mock_mgr = MagicMock()
            mock_mgr.get_zt_pool.return_value = (
                [
                    {"code": "000003", "name": "炸板股", "price": 10.0, "change_pct": 9.95,
                     "seal_count": 2, "lb_count": 1, "pool_date": "2024-05-10"},
                ],
                "akshare",
                None,
            )
            mock_manager.return_value = mock_mgr

            response = client.get("/api/v1/zt-pools?type=zbgc&date=2024-05-10")
            assert response.status_code == 200
            data = response.json()
            assert data["type"] == "zbgc"
            assert data["stocks"][0]["seal_count"] == 2

    def test_get_pools_missing_type(self, client):
        """Test GET /api/v1/zt-pools without type parameter returns 422."""
        response = client.get("/api/v1/zt-pools")
        assert response.status_code == 422

    def test_get_pools_invalid_type(self, client):
        """Test GET /api/v1/zt-pools with invalid type parameter returns 422."""
        response = client.get("/api/v1/zt-pools?type=invalid")
        assert response.status_code == 422

    def test_get_pools_with_refresh(self, client):
        """Test GET /api/v1/zt-pools?refresh=true forces refresh.

        The route resolves a missing `date` to either today (if today is
        a trade day) or the latest trade date <= today. The volatile/
        historical policy now lives in pool_daily.get_pool — the route
        just resolves the date and forwards it. Pin the date so the
        assertion is deterministic regardless of when the test runs.
        """
        with patch("stock_data.api.routes.boards.get_manager") as mock_manager:
            mock_mgr = MagicMock()
            # When refresh=True, manager returns data (forces fetch)
            mock_mgr.get_zt_pool.return_value = (
                [{"code": "000001", "name": "测试股票", "price": 10.0, "change_pct": 5.0}],
                "akshare",
                None,
            )
            mock_manager.return_value = mock_mgr

            response = client.get("/api/v1/zt-pools?type=zt&refresh=true&date=2024-05-10")
            assert response.status_code == 200
            # date pinned to 2024-05-10 (a historical Friday) — the
            # route no longer passes is_current_day; the persistence
            # layer computes volatility from the date itself.
            mock_mgr.get_zt_pool.assert_called_once_with(
                pool_type="zt", date="2024-05-10", refresh=True,
            )

    def test_get_pools_no_data_returns_404(self, client):
        """Test GET /api/v1/zt-pools when no data returns 404."""
        with patch("stock_data.api.routes.boards.get_manager") as mock_manager:
            mock_mgr = MagicMock()
            mock_mgr.get_zt_pool.return_value = ([], "", None)
            mock_manager.return_value = mock_mgr

            response = client.get("/api/v1/zt-pools?type=zt&date=2024-05-10")
            assert response.status_code == 404

    def test_get_pools_passes_date_to_manager(self, client):
        """Test GET /api/v1/zt-pools passes date to manager correctly."""
        with patch("stock_data.api.routes.boards.get_manager") as mock_manager:
            mock_mgr = MagicMock()
            mock_mgr.get_zt_pool.return_value = ([], "", None)
            mock_manager.return_value = mock_mgr

            client.get("/api/v1/zt-pools?type=zt&date=2024-06-15")
            # Should pass date to manager
            mock_mgr.get_zt_pool.assert_called_once()
            args, kwargs = mock_mgr.get_zt_pool.call_args
            assert "2024-06-15" in str(args) or kwargs.get("date") == "2024-06-15"

    def test_get_pools_omitted_date_uses_trade_calendar(self, client):
        """No `date` param: today if it's a trade day, else latest trade date <= today.

        Skips when today IS a trade day (the other branch is exercised by
        the explicit-date and refresh tests). Forces today to look like a
        non-trade day by patching is_trade_date to return False.
        """
        from datetime import date as date_cls

        from stock_data.data_provider.persistence import trade_calendar

        today_str = date_cls.today().strftime("%Y-%m-%d")
        latest = trade_calendar.get_latest_trade_date_on_or_before(today_str)
        if not latest:
            pytest.skip("trade_calendar table is empty; cannot determine latest trade date")
        if latest == today_str:
            pytest.skip("Today is itself a trade day; this test exercises the fallback branch")

        # Pretend today is not a trade day so the route falls back to `latest`.
        with (
            patch.object(trade_calendar, "is_trade_date", return_value=False),
            patch("stock_data.api.routes.boards.get_manager") as mock_manager,
        ):
            mock_mgr = MagicMock()
            mock_mgr.get_zt_pool.return_value = (
                [{"code": "000099", "name": "最近交易日股", "price": 1.0}],
                "akshare",
                None,
            )
            mock_manager.return_value = mock_mgr

            response = client.get("/api/v1/zt-pools?type=zt")
            assert response.status_code == 200
            # Post-c40d108: the route no longer passes is_current_day down to the
            # manager — that flag is ignored and the persistence layer computes
            # volatility from the date itself (see pool_daily.is_volatile_date).
            # We only assert the kwargs the route still actually sends.
            mock_mgr.get_zt_pool.assert_called_once_with(
                pool_type="zt", date=latest, refresh=False,
            )


class TestZTPoolPersistence:
    """Tests for the unified pool_daily persistence module."""

    def test_save_and_get_zt_pool(self):
        """Test saving and retrieving ZT pool data via the unified pool_daily table."""
        from stock_data.data_provider.persistence.pool_daily import (
            get_pool_cached,
            init_schema,
            save_pool,
        )

        init_schema()

        # Use a unique date to avoid conflicts with other tests
        test_date = "2099-11-30"

        sample_stocks = [
            {
                "code": "999999",
                "name": "测试股票",
                "price": 12.5,
                "change_pct": 10.05,
                "amount": 436073568.0,
                "turnover_rate": 3.77,
                "lb_count": 1,
                "first_seal_time": "09:25:00",
                "last_seal_time": "09:34:33",
                "seal_amount": 98243407,
                "seal_count": 0,
                "zt_count": "1/1",
            },
        ]

        save_pool("zt", test_date, sample_stocks)

        stocks = get_pool_cached("zt", test_date)
        assert len(stocks) == 1
        assert stocks[0]["code"] == "999999"
        assert stocks[0]["name"] == "测试股票"
        assert stocks[0]["price"] == 12.5
        assert stocks[0]["change_pct"] == 10.05
        assert stocks[0]["lb_count"] == 1
        # pool_type discriminator round-trips
        assert stocks[0]["pool_type"] == "zt"
        assert stocks[0]["pool_date"] == test_date

    def test_get_pool_count(self):
        """Test getting pool count from the unified table."""
        from stock_data.data_provider.persistence.pool_daily import (
            get_pool_count,
            init_schema,
            save_pool,
        )

        init_schema()

        test_date = "2099-01-15"

        sample_stocks = [
            {"code": "999991", "name": "股票1", "price": 10.0, "change_pct": 10.0},
            {"code": "999992", "name": "股票2", "price": 8.0, "change_pct": 10.0},
            {"code": "999993", "name": "股票3", "price": 6.0, "change_pct": 10.0},
        ]

        save_pool("zt", test_date, sample_stocks)

        count = get_pool_count("zt", test_date)
        assert count == 3

    def test_get_pool_count_empty(self):
        """Test getting pool count returns 0 for empty pool."""
        from stock_data.data_provider.persistence.pool_daily import get_pool_count

        count = get_pool_count("zt", "2999-12-31")
        assert count == 0

    def test_invalid_pool_type_raises_valueerror(self):
        """save_pool / get_pool_cached should reject unknown pool types."""
        from stock_data.data_provider.persistence.pool_daily import (
            get_pool_cached,
            save_pool,
        )

        with pytest.raises(ValueError, match="Unknown pool_type"):
            save_pool("invalid", "2099-01-01", [])
        with pytest.raises(ValueError, match="Unknown pool_type"):
            get_pool_cached("invalid", "2099-01-01")

    def test_unified_table_stores_all_pool_types(self):
        """zt / dt / zbgc co-exist in the unified pool_daily table by (pool_type, date)."""
        from stock_data.data_provider.persistence.pool_daily import (
            get_pool_cached,
            init_schema,
            save_pool,
        )

        init_schema()
        test_date = "2098-06-01"
        save_pool("zt", test_date, [{"code": "600001", "name": "涨停股", "price": 10.0}])
        save_pool("dt", test_date, [{"code": "600002", "name": "跌停股", "price": 5.0}])
        save_pool("zbgc", test_date, [{"code": "600003", "name": "炸板股", "price": 8.0}])

        zt = get_pool_cached("zt", test_date)
        dt = get_pool_cached("dt", test_date)
        zbgc = get_pool_cached("zbgc", test_date)

        assert len(zt) == 1 and zt[0]["code"] == "600001"
        assert len(dt) == 1 and dt[0]["code"] == "600002"
        assert len(zbgc) == 1 and zbgc[0]["code"] == "600003"


class TestZTFetcherCapabilities:
    """Tests for ZT pool fetcher capabilities."""

    def test_zhitu_fetcher_supports_zt_pool(self):
        """Test ZhituFetcher declares STOCK_ZT_POOL capability."""
        from stock_data.data_provider.base import DataCapability
        from stock_data.data_provider.fetchers.zhitu_fetcher import ZhituFetcher

        fetcher = ZhituFetcher()
        assert DataCapability.STOCK_ZT_POOL in fetcher.supported_data_types

    def test_akshare_fetcher_supports_zt_pool(self):
        """Test AkshareFetcher declares STOCK_ZT_POOL capability."""
        from stock_data.data_provider.base import DataCapability
        from stock_data.data_provider.fetchers.akshare import AkshareFetcher

        fetcher = AkshareFetcher()
        assert DataCapability.STOCK_ZT_POOL in fetcher.supported_data_types

    def test_zhitu_fetcher_has_get_zt_pool_method(self):
        """Test ZhituFetcher has get_zt_pool method."""
        from stock_data.data_provider.fetchers.zhitu_fetcher import ZhituFetcher

        fetcher = ZhituFetcher()
        assert hasattr(fetcher, "get_zt_pool")

    def test_akshare_fetcher_has_get_zt_pool_method(self):
        """Test AkshareFetcher has get_zt_pool method."""
        from stock_data.data_provider.fetchers.akshare import AkshareFetcher

        fetcher = AkshareFetcher()
        assert hasattr(fetcher, "get_zt_pool")


class TestZTFetcherManager:
    """Tests for DataFetcherManager ZT pool methods."""

    def test_manager_get_zt_pool_uses_cache(self):
        """Test manager uses persistence when data available (historical date)."""
        from stock_data.data_provider import DataFetcherManager
        from stock_data.data_provider.persistence.pool_daily import (
            init_schema,
            save_pool,
        )

        init_schema()

        # Pre-populate persistence with a historical date
        sample_stocks = [
            {"code": "000001", "name": "持久化股票", "price": 10.0, "change_pct": 5.0},
        ]
        save_pool("zt", "2024-05-10", sample_stocks)

        mgr = DataFetcherManager()
        # Without any fetchers, should fallback to persistence (historical date)
        stocks = mgr.get_zt_pool("zt", "2024-05-10", refresh=False)
        assert len(stocks) >= 1

    def test_manager_get_zt_pool_skips_write_on_volatile_date(self):
        """Volatile date: reads from cache, fetches upstream on miss, skips the write.

        Post-2026-07-15 contract: ``is_volatile_date(date)`` is the single source
        of truth for the volatile/historical split. On a volatile date the
        persistence layer:
          1. Always tries the cache read first (a previous ``refresh=true`` may
             have left volatile data, which is still meaningful with a warning).
          2. Calls upstream on miss.
          3. Skips the write-back UNLESS the caller passed ``refresh=true``.

        This test exercises the "read miss + upstream fetch + skip write" path:
        the cache is empty for today, the upstream returns data, and the cache
        MUST remain empty. The 3-tuple return carries a non-None warning.

        Setup: seed today into the trade calendar so ``is_volatile_date(today)``
        is True regardless of whether the system clock is in trading hours.
        Clean up the seeded row in finally.
        """
        from datetime import date as date_cls

        from stock_data.data_provider import DataFetcherManager
        from stock_data.data_provider.persistence.db import get_connection
        from stock_data.data_provider.persistence.pool_daily import (
            get_pool_cached,
            init_schema,
        )
        from stock_data.data_provider.persistence.trade_calendar import (
            init_schema as init_calendar_schema,
        )
        from stock_data.data_provider.persistence.trade_calendar import (
            update_cached_calendar,
        )

        init_schema()
        init_calendar_schema()

        today_str = date_cls.today().strftime("%Y-%m-%d")

        # Seed trade_calendar with today so is_volatile_date(today) -> True.
        # update_cached_calendar is a pure upsert (post-fix), so this is safe
        # to call from a test without wiping pre-existing calendar state.
        update_cached_calendar([today_str])

        conn = get_connection()
        conn.execute(
            "DELETE FROM pool_daily WHERE pool_type = 'zt' AND pool_date = ?",
            (today_str,),
        )
        conn.commit()

        try:
            # Stub the upstream call so we don't hit the network
            class FakeFetcher:
                name = "FakeFetcher"
                def get_zt_pool(self, pool_type, date):
                    return [{"code": "FAKE001", "name": "Fake", "price": 1.0}]

            real_mgr = DataFetcherManager()
            real_mgr._filter_by_capability = MagicMock(return_value=[FakeFetcher()])

            # is_current_day kwarg is intentionally omitted: it's been ignored
            # since c40d108. Volatility is now derived from the date + calendar.
            stocks, origin, warning = real_mgr.get_zt_pool(
                "zt", today_str, refresh=False,
            )
            assert len(stocks) == 1
            assert stocks[0]["code"] == "FAKE001"
            assert origin == "FakeFetcher"
            # Today is volatile → warning is emitted
            assert warning is not None
            assert "16:00" in warning

            # Persistence MUST NOT have been written for today's date
            persisted = get_pool_cached("zt", today_str)
            assert persisted == []
        finally:
            # Clean up the seeded calendar row so we don't leak state to
            # other tests in the same session.
            conn = get_connection()
            conn.execute(
                "DELETE FROM trade_calendar WHERE trade_date = ?",
                (today_str,),
            )
            conn.commit()

    def test_manager_get_zt_pool_normalizes_code(self):
        """Test that manager.get_zt_pool normalizes the pool type code."""
        from stock_data.data_provider import DataFetcherManager
        from stock_data.data_provider.persistence.pool_daily import init_schema

        init_schema()
        mgr = DataFetcherManager()
        # _filter_by_capability returns no fetchers; the call should still
        # validate the pool type via the persistence layer helper.
        with pytest.raises(ValueError, match="Unknown pool_type"):
            mgr.get_zt_pool("invalid", "2099-01-01", refresh=False)


class TestVolatileDatePolicy:
    """Tests for the time-of-day cutoff in is_volatile_date and the
    volatile-write-skip / refresh-bypass behavior in get_pool.
    """

    def _fake_clock(self, monkeypatch, fake_now):
        """Patch pool_daily.date / pool_daily.datetime with thin wrappers.

        We can't monkeypatch built-in ``datetime.date.today`` because the
        C-implemented class is immutable. Instead, swap the module-level
        ``date`` and ``datetime`` names for FakeClass wrappers that
        delegate to real instances — that way the function under test
        (which uses the module-level names) sees the fakes.
        """
        from datetime import date as real_date_cls, datetime as real_datetime_cls
        from stock_data.data_provider.persistence import pool_daily

        fake_today = real_date_cls(fake_now.year, fake_now.month, fake_now.day)

        class _FakeDate:
            @classmethod
            def today(cls):
                return fake_today

        class _FakeDatetime:
            @classmethod
            def now(cls):
                return fake_now

        monkeypatch.setattr(pool_daily, "date", _FakeDate)
        monkeypatch.setattr(pool_daily, "datetime", _FakeDatetime)

    def test_is_volatile_date_before_16(self, monkeypatch):
        """At 15:59 on a trade day, today is still volatile."""
        from datetime import datetime

        from stock_data.data_provider.persistence import pool_daily
        from stock_data.data_provider.persistence import trade_calendar

        fake_now = datetime(2026, 7, 15, 15, 59, 0)
        self._fake_clock(monkeypatch, fake_now)
        monkeypatch.setattr(trade_calendar, "is_trade_date", lambda d: True)

        assert pool_daily.is_volatile_date("2026-07-15") is True

    def test_is_volatile_date_after_16(self, monkeypatch):
        """At 16:01 on a trade day, today is NO LONGER volatile."""
        from datetime import datetime

        from stock_data.data_provider.persistence import pool_daily
        from stock_data.data_provider.persistence import trade_calendar

        fake_now = datetime(2026, 7, 15, 16, 1, 0)
        self._fake_clock(monkeypatch, fake_now)
        monkeypatch.setattr(trade_calendar, "is_trade_date", lambda d: True)

        # 16:01 → past the 16:00 cutoff → not volatile
        assert pool_daily.is_volatile_date("2026-07-15") is False

    def test_is_volatile_date_historical(self, monkeypatch):
        """A non-today date is never volatile regardless of the clock."""
        from datetime import datetime

        from stock_data.data_provider.persistence import pool_daily

        fake_now = datetime(2026, 7, 15, 14, 30, 0)
        self._fake_clock(monkeypatch, fake_now)

        # Historical date is never volatile
        assert pool_daily.is_volatile_date("2024-05-10") is False

    def test_is_volatile_date_today_not_trade_day(self, monkeypatch):
        """Today is not a trade day → not volatile (calendar short-circuits)."""
        from datetime import datetime

        from stock_data.data_provider.persistence import pool_daily
        from stock_data.data_provider.persistence import trade_calendar

        fake_now = datetime(2026, 7, 15, 14, 30, 0)
        self._fake_clock(monkeypatch, fake_now)
        monkeypatch.setattr(trade_calendar, "is_trade_date", lambda d: False)

        assert pool_daily.is_volatile_date("2026-07-15") is False


class TestRefreshBypassOnVolatile:
    """refresh=True forces the write-back even on a volatile date."""

    def _fake_clock(self, monkeypatch, fake_now):
        from datetime import date as real_date_cls, datetime as real_datetime_cls
        from stock_data.data_provider.persistence import pool_daily

        fake_today = real_date_cls(fake_now.year, fake_now.month, fake_now.day)

        class _FakeDate:
            @classmethod
            def today(cls):
                return fake_today

        class _FakeDatetime:
            @classmethod
            def now(cls):
                return fake_now

        monkeypatch.setattr(pool_daily, "date", _FakeDate)
        monkeypatch.setattr(pool_daily, "datetime", _FakeDatetime)

    def test_refresh_true_writes_volatile_date(self, monkeypatch):
        """Today (volatile) + refresh=True: persistence layer fetches AND writes."""
        from datetime import datetime

        from stock_data.data_provider import DataFetcherManager
        from stock_data.data_provider.persistence import pool_daily
        from stock_data.data_provider.persistence import trade_calendar
        from stock_data.data_provider.persistence.db import get_connection
        from stock_data.data_provider.persistence.pool_daily import (
            get_pool_cached,
            init_schema,
        )
        from stock_data.data_provider.persistence.trade_calendar import (
            init_schema as init_calendar_schema,
        )
        from stock_data.data_provider.persistence.trade_calendar import (
            update_cached_calendar,
        )

        # Force "now" to 14:30 on a trade day so is_volatile_date(today) is True.
        fake_now = datetime(2026, 7, 15, 14, 30, 0)
        self._fake_clock(monkeypatch, fake_now)
        monkeypatch.setattr(trade_calendar, "is_trade_date", lambda d: True)

        init_schema()
        init_calendar_schema()
        today_str = fake_now.strftime("%Y-%m-%d")

        # Seed trade_calendar for completeness (some checks go through it).
        update_cached_calendar([today_str])

        conn = get_connection()
        # Wipe any prior rows for today so we can assert exactly what gets written.
        conn.execute(
            "DELETE FROM pool_daily WHERE pool_type = 'zt' AND pool_date = ?",
            (today_str,),
        )
        conn.commit()

        try:
            class FakeFetcher:
                name = "FakeFetcher"
                def get_zt_pool(self, pool_type, date):
                    return [{"code": "REFR001", "name": "Refreshed", "price": 9.9}]

            real_mgr = DataFetcherManager()
            real_mgr._filter_by_capability = MagicMock(return_value=[FakeFetcher()])

            stocks, origin, warning = real_mgr.get_zt_pool(
                "zt", today_str, refresh=True,
            )
            assert stocks[0]["code"] == "REFR001"
            assert origin == "FakeFetcher"
            # Volatile → warning is non-None
            assert warning is not None

            # refresh=True forces the write even on a volatile date
            persisted = get_pool_cached("zt", today_str)
            assert len(persisted) == 1
            assert persisted[0]["code"] == "REFR001"
        finally:
            conn = get_connection()
            conn.execute(
                "DELETE FROM pool_daily WHERE pool_type = 'zt' AND pool_date = ?",
                (today_str,),
            )
            conn.execute(
                "DELETE FROM trade_calendar WHERE trade_date = ?",
                (today_str,),
            )
            conn.commit()


class TestWarningEmission:
    """The warning is emitted on every return path that yields data on a volatile date."""

    def _fake_clock(self, monkeypatch, fake_now):
        from datetime import date as real_date_cls, datetime as real_datetime_cls
        from stock_data.data_provider.persistence import pool_daily

        fake_today = real_date_cls(fake_now.year, fake_now.month, fake_now.day)

        class _FakeDate:
            @classmethod
            def today(cls):
                return fake_today

        class _FakeDatetime:
            @classmethod
            def now(cls):
                return fake_now

        monkeypatch.setattr(pool_daily, "date", _FakeDate)
        monkeypatch.setattr(pool_daily, "datetime", _FakeDatetime)

    def test_warning_on_volatile_fresh_fetch(self, monkeypatch):
        """Volatile date + cache miss + upstream fetch: warning present."""
        from datetime import datetime

        from stock_data.data_provider.persistence import pool_daily
        from stock_data.data_provider.persistence import trade_calendar
        from stock_data.data_provider.persistence.pool_daily import init_schema

        fake_now = datetime(2026, 7, 15, 14, 30, 0)
        self._fake_clock(monkeypatch, fake_now)
        monkeypatch.setattr(trade_calendar, "is_trade_date", lambda d: True)

        init_schema()

        class FakeManager:
            def get_zt_pool_raw(self, pool_type, date):
                return ([{"code": "F001", "name": "x"}], "FakeFetcher")

        stocks, origin, warning = pool_daily.get_pool(
            "zt", "2026-07-15", manager=FakeManager(), refresh=False,
        )
        assert len(stocks) == 1
        assert origin == "FakeFetcher"
        assert warning is not None
        assert "16:00" in warning

    def test_warning_on_volatile_cache_hit(self, monkeypatch):
        """Volatile date + cache HIT: warning still present.

        The warning is purely a function of "this date is volatile";
        it is NOT conditional on whether we just fetched. A previous
        ``refresh=true`` may have left volatile data in the cache —
        the user must still see the warning.
        """
        from datetime import datetime

        from stock_data.data_provider.persistence import pool_daily
        from stock_data.data_provider.persistence import trade_calendar
        from stock_data.data_provider.persistence.pool_daily import (
            init_schema,
            save_pool,
        )

        fake_now = datetime(2026, 7, 15, 14, 30, 0)
        today_str = fake_now.strftime("%Y-%m-%d")
        self._fake_clock(monkeypatch, fake_now)
        monkeypatch.setattr(trade_calendar, "is_trade_date", lambda d: True)

        init_schema()

        # Pre-seed the cache with volatile data (simulating a prior refresh=true)
        save_pool("zt", today_str, [{"code": "VOL001", "name": "VolatileCache", "price": 1.0}])

        # Manager whose get_zt_pool_raw MUST NOT be called (cache hit short-circuits)
        class _ShouldNotBeCalledManager:
            def get_zt_pool_raw(self, pool_type, date):
                raise AssertionError("cache hit must not call upstream")

        stocks, origin, warning = pool_daily.get_pool(
            "zt", today_str, manager=_ShouldNotBeCalledManager(), refresh=False,
        )
        assert len(stocks) == 1
        assert stocks[0]["code"] == "VOL001"
        assert origin == "persistence"
        # The data came from cache, but the date is volatile → warning is present
        assert warning is not None

    def test_no_warning_on_historical_date(self, monkeypatch):
        """Historical date: no warning, even on fresh fetch."""
        from datetime import datetime

        from stock_data.data_provider.persistence import pool_daily
        from stock_data.data_provider.persistence.pool_daily import init_schema

        # Force the clock to a recent date so 2024-05-10 is clearly historical
        fake_now = datetime(2026, 7, 15, 14, 30, 0)
        self._fake_clock(monkeypatch, fake_now)

        init_schema()

        class FakeManager:
            def get_zt_pool_raw(self, pool_type, date):
                return ([{"code": "H001", "name": "Historical"}], "FakeFetcher")

        stocks, origin, warning = pool_daily.get_pool(
            "zt", "2024-05-10", manager=FakeManager(), refresh=False,
        )
        assert warning is None

    def test_no_warning_on_today_after_16(self, monkeypatch):
        """Today at 16:30 (post-cutoff): is_volatile_date is False, no warning."""
        from datetime import datetime

        from stock_data.data_provider.persistence import pool_daily
        from stock_data.data_provider.persistence import trade_calendar
        from stock_data.data_provider.persistence.pool_daily import init_schema

        fake_now = datetime(2026, 7, 15, 16, 30, 0)
        self._fake_clock(monkeypatch, fake_now)
        monkeypatch.setattr(trade_calendar, "is_trade_date", lambda d: True)

        init_schema()

        class FakeManager:
            def get_zt_pool_raw(self, pool_type, date):
                return ([{"code": "P001", "name": "PostClose"}], "FakeFetcher")

        stocks, origin, warning = pool_daily.get_pool(
            "zt", "2026-07-15", manager=FakeManager(), refresh=False,
        )
        assert warning is None

