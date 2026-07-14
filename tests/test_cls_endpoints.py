"""Route tests for /api/v1/news/morning-briefing and /api/v1/news/market-recap.

Uses FastAPI's TestClient to exercise the full middleware + decorator stack
(@map_errors, @cache_endpoint, @endpoint_meta) without making real HTTP calls.
Manager + fetcher are mocked via monkeypatch of the `get_manager()` symbol
imported into the cls routes module.
"""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from stock_data.server import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def sample_article() -> dict:
    return {
        "article_id": 2425210,
        "title": "test",
        "brief": "test brief",
        "author": "",
        "ctime": 1783983600,
        "date": "2026-07-14",
        "read_num": 100,
        "comments_num": 10,
        "share_num": 100,
        "images": [],
        "body_text": "test body",
    }


def test_morning_briefing_success(client, sample_article, monkeypatch):
    """Valid date + manager returns article 200 with full body.

    Manager returns the fetcher class name ("ClsFetcher") as it does in
    production; the route derives the slug ("cls") for the response field.
    """
    mock_mgr = MagicMock()
    mock_mgr.get_morning_briefing.return_value = (sample_article, "ClsFetcher")
    from stock_data.api.routes import cls as cls_routes
    monkeypatch.setattr(cls_routes, "get_manager", lambda: mock_mgr)
    from stock_data.api.cache import get_cls_feed_cache
    get_cls_feed_cache().clear()
    r = client.get("/api/v1/news/morning-briefing?date=2026-07-14")
    assert r.status_code == 200
    body = r.json()
    assert body["subject"] == "morning_briefing"
    assert body["subject_id"] == 1151
    assert body["date"] == "2026-07-14"
    assert body["source"] == "cls"  # slug derived from "ClsFetcher"
    assert body["article"]["article_id"] == 2425210


def test_morning_briefing_missing_date(client):
    """No ?date= → 422 (FastAPI rejects missing required query param)."""
    r = client.get("/api/v1/news/morning-briefing")
    assert r.status_code == 422


def test_morning_briefing_bad_date_format(client):
    """?date=2026/07/14 400."""
    r = client.get("/api/v1/news/morning-briefing?date=2026/07/14")
    assert r.status_code == 400


def test_morning_briefing_future_date(client):
    """?date=2099-01-01 400."""
    r = client.get("/api/v1/news/morning-briefing?date=2099-01-01")
    assert r.status_code == 400


def test_morning_briefing_old_date(client):
    """?date=2020-01-01 → 400 (outside 28-day window)."""
    r = client.get("/api/v1/news/morning-briefing?date=2020-01-01")
    assert r.status_code == 400


def test_morning_briefing_not_found(client, monkeypatch):
    """Manager returns (None, "") → 404 (no article published for this date)."""
    mock_mgr = MagicMock()
    mock_mgr.get_morning_briefing.return_value = (None, "")
    from stock_data.api.routes import cls as cls_routes
    monkeypatch.setattr(cls_routes, "get_manager", lambda: mock_mgr)
    from stock_data.api.cache import get_cls_feed_cache
    get_cls_feed_cache().clear()
    r = client.get("/api/v1/news/morning-briefing?date=2026-07-14")
    assert r.status_code == 404


def test_morning_briefing_all_fetchers_raised(client, monkeypatch):
    """Manager raises DataFetchError (all fetchers raised) → 503 (was 404 before fix).

    Defends the OpenAPI-documented 503 contract: 'all fetchers failed'
    must propagate to a 503, not collapse into a 404 via allow_none=True.
    """
    from stock_data.data_provider.base import DataFetchError
    mock_mgr = MagicMock()
    mock_mgr.get_morning_briefing.side_effect = DataFetchError(
        "All fetchers failed for get_morning_briefing 2026-07-14:\n"
        "[ClsFetcher] HTTP GET failed"
    )
    from stock_data.api.routes import cls as cls_routes
    monkeypatch.setattr(cls_routes, "get_manager", lambda: mock_mgr)
    from stock_data.api.cache import get_cls_feed_cache
    get_cls_feed_cache().clear()
    r = client.get("/api/v1/news/morning-briefing?date=2026-07-14")
    assert r.status_code == 503


def test_market_recap_success(client, sample_article, monkeypatch):
    """Same shape for /market-recap."""
    mock_mgr = MagicMock()
    mock_mgr.get_market_recap.return_value = (sample_article, "ClsFetcher")
    from stock_data.api.routes import cls as cls_routes
    monkeypatch.setattr(cls_routes, "get_manager", lambda: mock_mgr)
    from stock_data.api.cache import get_cls_feed_cache
    get_cls_feed_cache().clear()
    r = client.get("/api/v1/news/market-recap?date=2026-07-14")
    assert r.status_code == 200
    body = r.json()
    assert body["subject"] == "market_review"
    assert body["subject_id"] == 1135
    assert body["source"] == "cls"  # slug derived from "ClsFetcher"
