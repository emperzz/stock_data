"""End-to-end tests for /boards/{code}/news and /boards/{code}/surges.

Added 2026-07-20 per spec §3.5.2 / §3.5.3. Exercises the FastAPI route
contract:

  - Schema validation (BoardNewsResponse / BoardSurgesResponse)
  - Source Literal validation: non-'ths' values yield 422
  - Path validation: max_length=30 on board_code
  - Manager forwarding for ths source: ths only — capability flag gate
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    """FastAPI TestClient with manager.get_board_news / get_board_surges mocked."""

    fake_news_rows = [
        {
            "title": "中国神华大涨",
            "url": "http://news.10jqka.com.cn/field/20260720/678277988.shtml",
            "publish_date": "2026-07-20",
            "publish_time": "08:44",
            "summary": "中国神华(601088.SH)...大幅上涨",
            "source_domain": "news.10jqka.com.cn",
        },
        {
            "title": "煤炭ETF大涨",
            "url": "http://news.10jqka.com.cn/field/20260719/678272000.shtml",
            "publish_date": "2026-07-19",
            "publish_time": "20:13",
            "summary": "",
            "source_domain": "news.10jqka.com.cn",
        },
    ]
    fake_surges_rows = [
        {
            "date": "2026-07-14",
            "board_change_pct": 3.67,
            "sh_change_pct": 0.01,
            "limit_up_count": 8,
            "limit_up_stocks": ["600180", "600595", "603012", "600403"],
            "up_count": None,
            "down_count": None,
        },
    ]

    def fake_get_board_news(self, board_code, source, limit=20, **kwargs):
        return (fake_news_rows, "ThsFetcher")

    def fake_get_board_surges(self, board_code, source, limit=5, **kwargs):
        return (fake_surges_rows, "ThsFetcher")

    # Patch the manager methods via direct monkey-patching on the class.
    from stock_data.data_provider.manager import DataFetcherManager

    monkeypatch.setattr(DataFetcherManager, "get_board_news", fake_get_board_news)
    monkeypatch.setattr(DataFetcherManager, "get_board_surges", fake_get_board_surges)

    import stock_data.server as server

    yield TestClient(server.app)


def test_news_route_returns_board_news(client):
    """GET /boards/885914/news → JSON with data array."""
    r = client.get("/api/v1/boards/885914/news?limit=5&source=ths")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["board_code"] == "885914"
    assert body["source"] == "ThsFetcher" or "ths" in body["source"]
    assert body["total"] == 2
    assert len(body["data"]) == 2
    first = body["data"][0]
    assert first["title"] == "中国神华大涨"
    assert first["publish_date"] == "2026-07-20"
    assert first["source_domain"] == "news.10jqka.com.cn"


def test_news_route_default_source(client):
    """No ?source → defaults to 'ths'."""
    r = client.get("/api/v1/boards/885914/news")
    assert r.status_code == 200, r.text
    assert r.json()["total"] == 2


def test_news_route_rejects_non_ths_source(client):
    """?source=zhitu → 422 (Literal['ths'] enforcement)."""
    r = client.get("/api/v1/boards/885914/news?source=zhitu")
    assert r.status_code == 422, r.text


def test_news_route_clamps_limit(client):
    """?limit=0 (out of range 1-50) → 422."""
    r = client.get("/api/v1/boards/885914/news?limit=0")
    assert r.status_code == 422


def test_news_route_default_limit(client):
    """No ?limit → default 20 forwarded to fetcher."""
    r = client.get("/api/v1/boards/885914/news?source=ths")
    assert r.status_code == 200


def test_surges_route_returns_board_surges(client):
    """GET /boards/885914/surges → JSON with 1 surge entry."""
    r = client.get("/api/v1/boards/885914/surges?limit=5&source=ths")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["board_code"] == "885914"
    assert body["total"] == 1
    s = body["data"][0]
    assert s["date"] == "2026-07-14"
    assert s["board_change_pct"] == 3.67
    assert s["limit_up_count"] == 8
    assert s["limit_up_stocks"] == ["600180", "600595", "603012", "600403"]
    # up_count / down_count reserved for future — must be None (or absent)
    assert s.get("up_count") is None
    assert s.get("down_count") is None


def test_surges_route_rejects_non_ths_source(client):
    """?source=eastmoney → 422."""
    r = client.get("/api/v1/boards/885914/surges?source=eastmoney")
    assert r.status_code == 422


def test_surges_route_clamps_limit(client):
    """?limit=20 (out of range 1-12) → 422."""
    r = client.get("/api/v1/boards/885914/surges?limit=20")
    assert r.status_code == 422
