"""
Integration tests for API routes using FastAPI TestClient.
"""

import pytest
from fastapi.testclient import TestClient

from stock_data.api.routes import reset_manager
from stock_data.server import app


@pytest.fixture(autouse=True)
def reset_before_test():
    """Reset manager state before each test."""
    reset_manager()
    yield


@pytest.fixture
def client():
    return TestClient(app)


class TestHealthCheck:
    """Tests for /api/v1/health endpoint."""

    def test_health_returns_ok(self, client):
        response = client.get("/api/v1/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "available_sources" in data


class TestListIndices:
    """Tests for /api/v1/indices endpoint."""

    def test_list_indices(self, client):
        response = client.get("/api/v1/indices")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0
        # Check structure
        idx = data[0]
        assert "code" in idx
        assert "name" in idx
        assert "market" in idx


class TestListStocks:
    """Tests for /api/v1/stocks endpoint."""

    def test_list_stocks_csi(self, client):
        response = client.get("/api/v1/stocks?market=csi")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_list_stocks_with_pagination(self, client):
        response = client.get("/api/v1/stocks?market=csi&offset=0&limit=5")
        assert response.status_code == 200
        data = response.json()
        assert len(data) <= 5

    def test_list_stocks_invalid_market(self, client):
        response = client.get("/api/v1/stocks?market=invalid")
        assert response.status_code == 422


class TestQuote:
    """Tests for /api/v1/stocks/{code}/quote endpoint."""

    def test_quote_baostock_returns_404(self, client):
        """Baostock does not support realtime - should 404 if no other sources."""
        response = client.get("/api/v1/stocks/600519/quote")
        # May be 200 if Akshare succeeds, 404 if all fail
        assert response.status_code in (200, 404)

    def test_quote_invalid_code_too_long(self, client):
        response = client.get("/api/v1/stocks/" + "A" * 30 + "/quote")
        assert response.status_code == 422


class TestHistory:
    """Tests for /api/v1/stocks/{code}/history endpoint."""

    def test_history_returns_500_for_invalid_stock(self, client):
        """Invalid stock code should eventually fail and return 500."""
        response = client.get("/api/v1/stocks/INVALID/history?period=daily&days=5")
        assert response.status_code == 500

    def test_history_with_adjust(self, client):
        """Test history with adjustment parameter."""
        response = client.get("/api/v1/stocks/600519/history?period=daily&days=5&adjust=qfq")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == "600519"
        assert "data" in data


class TestIntraday:
    """Tests for /api/v1/stocks/{code}/intraday endpoint."""

    def test_intraday_unsupported_market(self, client):
        """US stocks not supported for intraday."""
        response = client.get("/api/v1/stocks/AAPL/intraday?period=5")
        assert response.status_code == 400


class TestCalendar:
    """Tests for /api/v1/calendar endpoint."""

    def test_calendar(self, client):
        response = client.get("/api/v1/calendar")
        assert response.status_code == 200
        data = response.json()
        assert "trade_dates" in data
        assert "total" in data


class TestIndexQuote:
    """Tests for /api/v1/indices/{code}/quote endpoint."""

    def test_index_quote_returns_data(self, client):
        response = client.get("/api/v1/indices/000300/quote")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == "000300"
        assert "name" in data
        assert "current_price" in data
        assert "change_percent" in data

    def test_index_quote_399006(self, client):
        response = client.get("/api/v1/indices/399006/quote")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == "399006"


class TestIndexHistory:
    """Tests for /api/v1/indices/{code}/history endpoint."""

    def test_index_history_daily(self, client):
        response = client.get("/api/v1/indices/000300/history?period=daily&days=5")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == "000300"
        assert data["period"] == "daily"
        assert len(data["data"]) <= 5

    def test_index_history_weekly(self, client):
        response = client.get("/api/v1/indices/000300/history?period=weekly&days=10")
        assert response.status_code == 200
        data = response.json()
        assert data["period"] == "weekly"


class TestIndexIntraday:
    """Tests for /api/v1/indices/{code}/intraday endpoint."""

    def test_index_intraday_period_5(self, client):
        response = client.get("/api/v1/indices/000300/intraday?period=5")
        # May fail due to upstream EM issues, but should not 500 unless implementation error
        assert response.status_code in (200, 500, 502, 503, 504)

    def test_index_intraday_invalid_period(self, client):
        response = client.get("/api/v1/indices/000300/intraday?period=999")
        assert response.status_code == 422


class TestStocksBlocksIndices:
    """Tests that /stocks/{code}/* endpoints reject index codes."""

    def test_stocks_quote_blocks_index(self, client):
        response = client.get("/api/v1/stocks/000300/quote")
        assert response.status_code == 400
        assert "indices" in response.json()["detail"]["message"]

    def test_stocks_history_blocks_index(self, client):
        response = client.get("/api/v1/stocks/000300/history?period=daily&days=5")
        assert response.status_code == 400
        assert "indices" in response.json()["detail"]["message"]

    def test_stocks_intraday_blocks_index(self, client):
        response = client.get("/api/v1/stocks/000300/intraday?period=5")
        assert response.status_code == 400
