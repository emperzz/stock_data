"""Live network verification for the 3 new EastMoney fetcher methods (Tasks 1-3).

Marks: ``@pytest.mark.live_network`` so failures are reclassified to xfail
by ``tests/conftest.py``. Run with::

    pytest -m live_network tests/test_eastmoney_new_apis_live.py -v

Skipped by default in the dev loop (see pyproject.toml ``addopts = ["-m", "not live_network"]``).
"""
import pytest

from stock_data.data_provider.fetchers.eastmoney_fetcher import EastMoneyFetcher


pytestmark = pytest.mark.live_network


@pytest.fixture(scope="module")
def fetcher():
    return EastMoneyFetcher()


# ---------------------------------------------------------------------------
# Task 1: get_stock_boards (push2 slist/get)
# ---------------------------------------------------------------------------
class TestGetStockBoardsLive:
    def test_600519_returns_real_boards(self, fetcher):
        """贵州茅台: page shows 食品饮料/白酒Ⅲ/白酒Ⅱ/贵州板块/酿酒概念 as first 5."""
        result = fetcher.get_stock_boards("600519", source="eastmoney")
        assert result is not None, "Should not return None for valid SH code"
        assert len(result) > 0, "贵州茅台 should belong to multiple boards"
        codes = {b["code"] for b in result}
        names = {b["name"] for b in result}
        # BK1277 = 白酒Ⅱ, BK0438 = 食品饮料 — both should appear
        assert "BK1277" in codes, f"Expected BK1277 in {codes}"
        assert any("白酒" in n for n in names), f"Expected 白酒* in {names}"
        assert any("食品饮料" in n or "酿酒" in n for n in names), \
            f"Expected 食品饮料/酿酒 in {names}"

    def test_000001_sz_secid(self, fetcher):
        """平安银行 (SZ) — verify secid construction works for non-SH codes."""
        result = fetcher.get_stock_boards("000001", source="eastmoney")
        assert result is not None
        assert len(result) > 0

    def test_invalid_code_returns_none(self, fetcher):
        result = fetcher.get_stock_boards("", source="eastmoney")
        assert result is None


# ---------------------------------------------------------------------------
# Task 2: get_stock_news (np-listapi getListInfo)
# ---------------------------------------------------------------------------
class TestGetStockNewsLive:
    def test_600519_returns_recent_news(self, fetcher):
        result = fetcher.get_stock_news("600519", limit=5)
        assert isinstance(result, list)
        assert len(result) > 0, "Should return at least 1 news item"
        first = result[0]
        assert "title" in first and first["title"], f"Missing title: {first}"
        assert "url" in first and first["url"], f"Missing url: {first}"
        assert "publish_date" in first
        assert len(first["publish_date"]) == 10, f"Date should be YYYY-MM-DD: {first}"

    def test_limit_respected(self, fetcher):
        result = fetcher.get_stock_news("600519", limit=3)
        assert len(result) <= 3


# ---------------------------------------------------------------------------
# Task 3: get_announcements (np-anotice-stock)
# ---------------------------------------------------------------------------
class TestGetAnnouncementsLive:
    def test_600519_returns_recent_announcements(self, fetcher):
        result = fetcher.get_announcements("600519", page_size=5)
        assert isinstance(result, list)
        assert len(result) > 0, "Should return at least 1 announcement"
        first = result[0]
        assert "title" in first and first["title"]
        assert "url" in first and "AN" in first["url"], \
            f"URL should contain announcement code: {first}"
        assert "date" in first and len(first["date"]) == 10

    def test_pagination_works(self, fetcher):
        """page_index=2 should return different (earlier) announcements than page=1."""
        page1 = fetcher.get_announcements("600519", page_size=5, page_index=1)
        page2 = fetcher.get_announcements("600519", page_size=5, page_index=2)
        assert len(page1) > 0
        assert len(page2) > 0
        # Dates should be different (page2 is older)
        if page1 and page2:
            assert page1[0]["date"] >= page2[0]["date"], \
                f"page1 should be newer than page2: {page1[0]['date']} vs {page2[0]['date']}"


# ---------------------------------------------------------------------------
# Task 5+7: End-to-end route smoke tests (hit real fetcher via Manager)
# ---------------------------------------------------------------------------
class TestRoutesLive:
    def test_stocks_news_endpoint(self):
        from fastapi.testclient import TestClient
        from stock_data.server import app
        client = TestClient(app)
        resp = client.get("/api/v1/stocks/600519/news?limit=5")
        assert resp.status_code == 200, f"Got {resp.status_code}: {resp.text}"
        body = resp.json()
        assert body["code"] == "600519"
        assert "data" in body
        assert len(body["data"]) > 0, "Live news feed should not be empty"
        assert body["source"] == "EastMoneyFetcher", \
            f"Expected EastMoneyFetcher, got {body['source']}"

    def test_stocks_boards_eastmoney_source(self):
        """?source=eastmoney should return eastmoney data via persistence cold-fill."""
        from fastapi.testclient import TestClient
        from stock_data.server import app
        client = TestClient(app)
        resp = client.get("/api/v1/stocks/600519/boards?source=eastmoney")
        # Acceptable: 200 (data) or 502 (no fetcher in env)
        assert resp.status_code in (200, 502), f"Got {resp.status_code}: {resp.text}"
        if resp.status_code == 200:
            body = resp.json()
            assert "data" in body
            # Should have at least one board
            assert len(body["data"]) > 0, "Live boards should not be empty"

    def test_stocks_announcements_endpoint(self):
        from fastapi.testclient import TestClient
        from stock_data.server import app
        client = TestClient(app)
        resp = client.get("/api/v1/stocks/600519/announcements?page_size=5")
        assert resp.status_code == 200, f"Got {resp.status_code}: {resp.text}"
        body = resp.json()
        assert body["code"] == "600519"
        assert "announcements" in body
        assert len(body["announcements"]) > 0
        # source should be either EastMoneyFetcher or CninfoFetcher (failover)
        assert body["source"] in ("EastMoneyFetcher", "CninfoFetcher"), \
            f"Unexpected source: {body['source']}"