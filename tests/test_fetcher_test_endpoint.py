"""Tests for POST /control/fetcher-test endpoint."""
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from stock_data.server import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        c.get("/control/server/status")  # trigger lifespan
        yield c


def _post(client, body: dict):
    return client.post("/control/fetcher-test", json=body)


def test_happy_path_returns_ok_true(client):
    fake = MagicMock()
    fake.is_available.return_value = True
    fake.get_realtime_quote.return_value = {"price": 100.0}
    with patch.object(app.state.manager, "get_fetcher", return_value=fake):
        r = _post(client, {"fetcher": "baostock", "method": "get_realtime_quote",
                           "kwargs": {"stock_code": "600519"}})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["fetcher"] == "baostock"
    assert body["method"] == "get_realtime_quote"
    assert body["result"] == {"price": 100.0}
    assert body["error"] is None
    assert isinstance(body["elapsed_ms"], int)
    assert body["elapsed_ms"] >= 0


def test_unknown_fetcher_returns_ok_false_http_200(client):
    with patch.object(app.state.manager, "get_fetcher", return_value=None):
        r = _post(client, {"fetcher": "ghost", "method": "get_realtime_quote",
                           "kwargs": {"stock_code": "600519"}})
    assert r.status_code == 200  # always 200
    body = r.json()
    assert body["ok"] is False
    assert body["error"]["type"] == "UnknownFetcher"
    assert "ghost" in body["error"]["message"]


def test_unknown_method_returns_ok_false_http_200(client):
    fake = MagicMock()
    with patch.object(app.state.manager, "get_fetcher", return_value=fake):
        r = _post(client, {"fetcher": "baostock", "method": "__init__",
                           "kwargs": {}})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["error"]["type"] == "UnknownMethod"


def test_fetcher_unavailable_returns_ok_false(client):
    fake = MagicMock()
    fake.is_available.return_value = False
    with patch.object(app.state.manager, "get_fetcher", return_value=fake):
        r = _post(client, {"fetcher": "baostock", "method": "get_realtime_quote",
                           "kwargs": {"stock_code": "600519"}})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["error"]["type"] == "FetcherUnavailable"


def test_missing_kwarg_returns_type_error(client):
    fake = MagicMock()
    fake.is_available.return_value = True
    fake.get_realtime_quote.side_effect = TypeError(
        "get_realtime_quote() missing 1 required positional argument: 'stock_code'"
    )
    with patch.object(app.state.manager, "get_fetcher", return_value=fake):
        r = _post(client, {"fetcher": "baostock", "method": "get_realtime_quote", "kwargs": {}})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["error"]["type"] == "TypeError"


def test_fetcher_exception_returns_class_name_with_traceback(client):
    fake = MagicMock()
    fake.is_available.return_value = True
    from stock_data.data_provider.base import DataFetchError
    fake.get_realtime_quote.side_effect = DataFetchError("BaoStock login failed")
    with patch.object(app.state.manager, "get_fetcher", return_value=fake):
        r = _post(client, {"fetcher": "baostock", "method": "get_realtime_quote",
                           "kwargs": {"stock_code": "600519"}})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["error"]["type"] == "DataFetchError"
    assert "BaoStock login failed" in body["error"]["message"]
    assert body["error"]["traceback"]  # non-empty


def test_missing_body_field_returns_422(client):
    """Pydantic validation kicks in for missing required body fields."""
    r = _post(client, {"fetcher": "baostock"})  # missing method, kwargs
    assert r.status_code == 422
