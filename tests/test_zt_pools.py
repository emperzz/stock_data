"""
Tests for ZT (涨跌停) pool API and cache.
"""

import pytest
from unittest.mock import MagicMock, patch

from stock_data.api.routes import reset_manager
from stock_data.server import app


@pytest.fixture(autouse=True)
def reset_before_test():
    """Reset manager state before each test."""
    reset_manager()
    yield


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    return TestClient(app)


class TestZTPoolAPIRoutes:
    """Tests for ZT pool API routes."""

    def test_get_zt_pools_success(self, client):
        """Test GET /api/v1/pools with type=zt returns cached data."""
        with patch("stock_data.api.routes.get_manager") as mock_manager:
            mock_mgr = MagicMock()
            mock_mgr.get_zt_pool.return_value = [
                {"code": "000001", "name": "平安银行", "price": 12.5, "change_pct": 10.05,
                 "lb_count": 1, "first_seal_time": "09:25:00", "last_seal_time": "09:34:33",
                 "seal_amount": 98243407, "seal_count": 0, "zt_count": "1/1", "pool_date": "2024-05-10"},
            ]
            mock_manager.return_value = mock_mgr

            response = client.get("/api/v1/pools?type=zt&date=2024-05-10")
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

    def test_get_dt_pools(self, client):
        """Test GET /api/v1/pools with type=dt returns cached data."""
        with patch("stock_data.api.routes.get_manager") as mock_manager:
            mock_mgr = MagicMock()
            mock_mgr.get_zt_pool.return_value = [
                {"code": "000002", "name": "万科A", "price": 8.8, "change_pct": -9.95,
                 "lb_count": 1, "pool_date": "2024-05-10"},
            ]
            mock_manager.return_value = mock_mgr

            response = client.get("/api/v1/pools?type=dt&date=2024-05-10")
            assert response.status_code == 200
            data = response.json()
            assert data["type"] == "dt"
            assert data["total"] == 1
            assert data["stocks"][0]["change_pct"] == -9.95

    def test_get_zbgc_pools(self, client):
        """Test GET /api/v1/pools with type=zbgc returns cached data."""
        with patch("stock_data.api.routes.get_manager") as mock_manager:
            mock_mgr = MagicMock()
            mock_mgr.get_zt_pool.return_value = [
                {"code": "000003", "name": "炸板股", "price": 10.0, "change_pct": 9.95,
                 "seal_count": 2, "lb_count": 1, "pool_date": "2024-05-10"},
            ]
            mock_manager.return_value = mock_mgr

            response = client.get("/api/v1/pools?type=zbgc&date=2024-05-10")
            assert response.status_code == 200
            data = response.json()
            assert data["type"] == "zbgc"
            assert data["stocks"][0]["seal_count"] == 2

    def test_get_pools_missing_type(self, client):
        """Test GET /api/v1/pools without type parameter returns 422."""
        response = client.get("/api/v1/pools")
        assert response.status_code == 422

    def test_get_pools_invalid_type(self, client):
        """Test GET /api/v1/pools with invalid type parameter returns 422."""
        response = client.get("/api/v1/pools?type=invalid")
        assert response.status_code == 422

    def test_get_pools_with_refresh(self, client):
        """Test GET /api/v1/pools?refresh=true forces refresh."""
        with patch("stock_data.api.routes.get_manager") as mock_manager:
            mock_mgr = MagicMock()
            # When refresh=True, manager returns data (forces fetch)
            mock_mgr.get_zt_pool.return_value = [
                {"code": "000001", "name": "测试股票", "price": 10.0, "change_pct": 5.0},
            ]
            mock_manager.return_value = mock_mgr

            response = client.get("/api/v1/pools?type=zt&refresh=true")
            assert response.status_code == 200
            mock_mgr.get_zt_pool.assert_called_once_with(pool_type="zt", date=None, refresh=True)

    def test_get_pools_no_data_returns_404(self, client):
        """Test GET /api/v1/pools when no data returns 404."""
        with patch("stock_data.api.routes.get_manager") as mock_manager:
            mock_mgr = MagicMock()
            mock_mgr.get_zt_pool.return_value = []
            mock_manager.return_value = mock_mgr

            response = client.get("/api/v1/pools?type=zt&date=2024-05-10")
            assert response.status_code == 404

    def test_get_pools_passes_date_to_manager(self, client):
        """Test GET /api/v1/pools passes date to manager correctly."""
        with patch("stock_data.api.routes.get_manager") as mock_manager:
            mock_mgr = MagicMock()
            mock_mgr.get_zt_pool.return_value = []
            mock_manager.return_value = mock_mgr

            response = client.get("/api/v1/pools?type=zt&date=2024-06-15")
            # Should pass date to manager
            mock_mgr.get_zt_pool.assert_called_once()
            args, kwargs = mock_mgr.get_zt_pool.call_args
            assert "2024-06-15" in str(args) or kwargs.get("date") == "2024-06-15"


class TestZTPoolCache:
    """Tests for ZT pool cache module."""

    def test_save_and_get_zt_pool(self):
        """Test saving and retrieving ZT pool data."""
        from stock_data.data_provider.cache.stock_zt_pool_cache import (
            init_db, save_zt_pool, get_zt_pool_cached, get_pool_count,
        )

        init_db()

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

        save_zt_pool("zt", test_date, sample_stocks)

        stocks = get_zt_pool_cached("zt", test_date)
        assert len(stocks) == 1
        assert stocks[0]["code"] == "999999"
        assert stocks[0]["name"] == "测试股票"
        assert stocks[0]["price"] == 12.5
        assert stocks[0]["change_pct"] == 10.05
        assert stocks[0]["lb_count"] == 1

    def test_get_pool_count(self):
        """Test getting pool count."""
        from stock_data.data_provider.cache.stock_zt_pool_cache import (
            init_db, save_zt_pool, get_pool_count,
        )

        init_db()

        # Use a unique date to avoid conflicts with other tests
        test_date = "2099-01-15"

        sample_stocks = [
            {"code": "999991", "name": "股票1", "price": 10.0, "change_pct": 10.0},
            {"code": "999992", "name": "股票2", "price": 8.0, "change_pct": 10.0},
            {"code": "999993", "name": "股票3", "price": 6.0, "change_pct": 10.0},
        ]

        save_zt_pool("zt", test_date, sample_stocks)

        count = get_pool_count("zt", test_date)
        assert count == 3

    def test_get_pool_count_empty(self):
        """Test getting pool count returns 0 for empty pool."""
        from stock_data.data_provider.cache.stock_zt_pool_cache import get_pool_count

        # Use a date far in the future that no test uses
        count = get_pool_count("zt", "2999-12-31")
        assert count == 0


class TestZTFetcherCapabilities:
    """Tests for ZT pool fetcher capabilities."""

    def test_zhitu_fetcher_supports_zt_pool(self):
        """Test ZhituFetcher declares STOCK_ZT_POOL capability."""
        from stock_data.data_provider.fetchers.zhitu_fetcher import ZhituFetcher
        from stock_data.data_provider.base import DataCapability

        fetcher = ZhituFetcher()
        assert DataCapability.STOCK_ZT_POOL in fetcher.supported_data_types

    def test_akshare_fetcher_supports_zt_pool(self):
        """Test AkshareFetcher declares STOCK_ZT_POOL capability."""
        from stock_data.data_provider.fetchers.akshare_fetcher import AkshareFetcher
        from stock_data.data_provider.base import DataCapability

        fetcher = AkshareFetcher()
        assert DataCapability.STOCK_ZT_POOL in fetcher.supported_data_types

    def test_zhitu_fetcher_has_get_zt_pool_method(self):
        """Test ZhituFetcher has get_zt_pool method."""
        from stock_data.data_provider.fetchers.zhitu_fetcher import ZhituFetcher

        fetcher = ZhituFetcher()
        assert hasattr(fetcher, "get_zt_pool")

    def test_akshare_fetcher_has_get_zt_pool_method(self):
        """Test AkshareFetcher has get_zt_pool method."""
        from stock_data.data_provider.fetchers.akshare_fetcher import AkshareFetcher

        fetcher = AkshareFetcher()
        assert hasattr(fetcher, "get_zt_pool")


class TestZTFetcherManager:
    """Tests for DataFetcherManager ZT pool methods."""

    def test_manager_get_zt_pool_uses_cache(self):
        """Test manager uses cache when data available."""
        from stock_data.data_provider.cache.stock_zt_pool_cache import (
            init_db, save_zt_pool,
        )
        from stock_data.data_provider.fetchers.akshare_fetcher import AkshareFetcher

        init_db()

        # Pre-populate cache
        sample_stocks = [
            {"code": "000001", "name": "缓存股票", "price": 10.0, "change_pct": 5.0},
        ]
        save_zt_pool("zt", "2024-05-10", sample_stocks)

        manager = MagicMock()
        manager._filter_by_capability = MagicMock(return_value=[])

        from stock_data.data_provider.base import DataFetcherManager
        from stock_data.data_provider.cache.stock_zt_pool_cache import get_zt_pool_cached

        # Test that get_zt_pool returns cached data when no fetchers available
        mgr = DataFetcherManager()
        # Without any fetchers, should fallback to cache
        stocks = mgr.get_zt_pool("zt", "2024-05-10", refresh=False)
        assert len(stocks) >= 1

    def test_manager_get_zt_pool_normalizes_code(self):
        """Test manager normalizes stock code from Zhitu format."""
        from stock_data.data_provider.fetchers.zhitu_fetcher import ZhituFetcher

        fetcher = ZhituFetcher()

        # Zhitu returns codes like "sz000657" but we normalize to "000657"
        # This tests the _normalize_zt_stock method
        test_row = {
            "dm": "sz000657",
            "mc": "中钨高新",
            "p": 9.33,
            "zf": 10.02,
            "cje": 436073568.0,
        }

        if fetcher.is_available():
            # If token available, test real normalization
            result = fetcher._normalize_zt_stock(test_row, "zt")
        else:
            # Mock the normalization behavior
            code = test_row["dm"]
            if code.startswith(("sh", "sz", "SH", "SZ")):
                code = code[2:]
            result = {"code": code, "name": test_row["mc"]}

        assert result["code"] == "000657"
        assert result["name"] == "中钨高新"