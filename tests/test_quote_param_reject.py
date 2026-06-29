"""Per spec 5.5 -- /quote rejects period/adjust/days/start_date/end_date.

Quote is a snapshot endpoint. These parameters have no meaning for a snapshot
and must be rejected with 422 (user input error), not silently ignored.
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


@pytest.mark.parametrize("bad_param", ["period", "adjust", "days", "start_date", "end_date"])
def test_stocks_quote_rejects_bad_param(client, bad_param):
    """GET /stocks/{code}/quote?<bad_param>=foo -> 422."""
    r = client.get(f"/api/v1/stocks/600519/quote?{bad_param}=foo")
    assert r.status_code == 422, f"expected 422 for {bad_param}, got {r.status_code}"
    detail = r.json()["detail"]
    assert detail["error"] == "param_not_applicable"


@pytest.mark.parametrize("bad_param", ["period", "adjust", "days", "start_date", "end_date"])
def test_indices_quote_rejects_bad_param(client, bad_param):
    """GET /indices/{code}/quote?<bad_param>=foo -> 422."""
    r = client.get(f"/api/v1/indices/000300/quote?{bad_param}=foo")
    assert r.status_code == 422, f"expected 422 for {bad_param}, got {r.status_code}"
    detail = r.json()["detail"]
    assert detail["error"] == "param_not_applicable"


def test_stocks_quote_accepts_no_params(client):
    """GET /stocks/{code}/quote with no extra params should not 422."""
    r = client.get("/api/v1/stocks/600519/quote")
    # 200 = success, 404 = no fetcher available, 503 = all failed
    assert r.status_code in (200, 404, 503)


def test_indices_quote_accepts_no_params(client):
    """GET /indices/{code}/quote with no extra params should not 422."""
    r = client.get("/api/v1/indices/000300/quote")
    # 200 = success, 404 = no fetcher available, 503 = all failed
    assert r.status_code in (200, 404, 503)
