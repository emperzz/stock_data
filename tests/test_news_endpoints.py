"""
Integration tests for /api/v1/news/search and /api/v1/news/content endpoints.
"""
from unittest.mock import patch

from fastapi.testclient import TestClient

from stock_data.server import app

client = TestClient(app)


# ---------------------- /api/v1/news/search ----------------------

class TestNewsSearchEndpoint:
    def test_search_200_returns_schema(self):
        fake_items = [
            {
                "title": "t1", "url": "http://finance.eastmoney.com/a/1.html",
                "source_domain": "finance.eastmoney.com", "publish_date": "2026-06-09",
                "snippet": "s1", "media_name": "证券时报网",
            }
        ]
        with patch(
            "stock_data.data_provider.manager.DataFetcherManager.search_news",
            return_value=(fake_items, "EastMoneyFetcher"),
        ):
            resp = client.get("/api/v1/news/search", params={"q": "603777", "limit": 5})

        assert resp.status_code == 200
        body = resp.json()
        assert body["data"] == fake_items
        assert body["source"] == "EastMoneyFetcher"
        assert body["query"] == "603777"
        assert body["limit"] == 5

    def test_search_missing_q_returns_422(self):
        resp = client.get("/api/v1/news/search")
        assert resp.status_code == 422  # FastAPI validation rejects missing required param

    def test_search_limit_too_high_returns_422(self):
        resp = client.get("/api/v1/news/search", params={"q": "ok", "limit": 999})
        assert resp.status_code == 422

    def test_search_from_after_to_returns_400_or_502(self):
        resp = client.get(
            "/api/v1/news/search",
            params={"q": "ok", "from": "2026-06-30", "to": "2026-01-01"},
        )
        # Either 400 (handler rejects at the boundary) or 502 (handler raises DataFetchError)
        assert resp.status_code in (400, 502)

    def test_search_upstream_failure_returns_503(self):
        from stock_data.data_provider.base import DataFetchError
        with patch(
            "stock_data.data_provider.manager.DataFetcherManager.search_news",
            side_effect=DataFetchError("all failed"),
        ):
            resp = client.get("/api/v1/news/search", params={"q": "ok"})

        assert resp.status_code == 503


# ---------------------- /api/v1/news/content ----------------------

class TestNewsContentEndpoint:
    def test_content_200_returns_schema(self):
        fake = {
            "url": "https://finance.eastmoney.com/a/1.html",
            "title": "Test Title",
            "body": "Body content here for testing.",
            "publish_date": "2026-06-09",
            "author": "TestMedia",
            "source_domain": "finance.eastmoney.com",
            "extractor": "eastmoney_v1",
            "byte_size": 28,
        }
        with patch(
            "stock_data.data_provider.utils.news_extractor.NewsContentExtractor.extract",
            return_value=fake,
        ):
            resp = client.get("/api/v1/news/content", params={"url": fake["url"]})

        assert resp.status_code == 200
        assert resp.json()["title"] == "Test Title"

    def test_content_missing_url_returns_422(self):
        resp = client.get("/api/v1/news/content")
        assert resp.status_code == 422

    def test_content_ssrf_localhost_returns_400(self):
        resp = client.get("/api/v1/news/content", params={"url": "http://localhost/"})
        assert resp.status_code == 400
        detail = resp.json()["detail"]
        assert "internal" in (detail.get("message", "") if isinstance(detail, dict) else str(detail)).lower()

    def test_content_non_http_scheme_returns_400(self):
        resp = client.get("/api/v1/news/content", params={"url": "file:///etc/passwd"})
        assert resp.status_code == 400

    def test_content_extraction_failure_returns_400(self):
        with patch(
            "stock_data.data_provider.utils.news_extractor.NewsContentExtractor.extract",
            side_effect=ValueError("could not extract main content"),
        ):
            resp = client.get(
                "/api/v1/news/content", params={"url": "https://example.com/x"}
            )
        assert resp.status_code == 400
