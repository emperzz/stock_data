"""Tests for /stocks/{code}/news endpoint.

The live test at the bottom (``test_stocks_news_endpoint_live``) hits the
real upstream and is tagged ``@pytest.mark.live_network`` so the default
``pytest`` run skips it via ``pyproject.toml addopts = ["-m", "not
live_network"]``. To run it: ``pytest -m live_network
tests/test_stocks_news_endpoint.py``.
"""
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from stock_data.server import app


@pytest.fixture
def client():
    return TestClient(app)


def _make_fake_manager(items=None, source="EastMoneyFetcher"):
    mgr = MagicMock()
    mgr.get_stock_news = MagicMock(return_value=(items or [], source))
    return mgr


def test_endpoint_returns_news(client):
    fake_items = [
        {"title": "T1", "url": "http://x", "publish_date": "2026-07-02",
         "source_domain": "x.com", "media_name": "X"}
    ]
    with patch("stock_data.api.routes.news.get_manager",
               return_value=_make_fake_manager(items=fake_items)):
        resp = client.get("/api/v1/stocks/600519/news?limit=10")
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == "600519"
    assert len(body["data"]) == 1
    assert body["data"][0]["title"] == "T1"
    assert body["source"] == "EastMoneyFetcher"
    assert body["limit"] == 10
    assert body["total"] == 1


def test_endpoint_validates_limit(client):
    """FastAPI Query(le=100) validation should reject limit > 100."""
    resp = client.get("/api/v1/stocks/600519/news?limit=500")
    assert resp.status_code == 422


def test_endpoint_validates_limit_min(client):
    """FastAPI Query(ge=1) validation should reject limit < 1."""
    resp = client.get("/api/v1/stocks/600519/news?limit=0")
    assert resp.status_code == 422


def test_endpoint_default_limit(client):
    """Default limit should be 20."""
    fake_items = [{"title": f"T{i}", "url": "", "publish_date": "",
                   "source_domain": "", "media_name": ""} for i in range(3)]
    with patch("stock_data.api.routes.news.get_manager",
               return_value=_make_fake_manager(items=fake_items)) as m:
        resp = client.get("/api/v1/stocks/600519/news")
    assert resp.status_code == 200
    body = resp.json()
    assert body["limit"] == 20
    m.return_value.get_stock_news.assert_called_once_with("600519", limit=20)


# ---------------------------------------------------------------------------
# Live network tests (skipped by default; see module docstring).
# ---------------------------------------------------------------------------


@pytest.mark.live_network
def test_stocks_news_endpoint_live(client):
    """End-to-end: /api/v1/stocks/600519/news returns EastMoneyFetcher news."""
    resp = client.get("/api/v1/stocks/600519/news?limit=5")
    assert resp.status_code == 200, f"Got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert body["code"] == "600519"
    assert "data" in body
    assert len(body["data"]) > 0, "Live news feed should not be empty"
    assert body["source"] == "EastMoneyFetcher", \
        f"Expected EastMoneyFetcher, got {body['source']}"
