"""
Unit tests for ThsFetcher.
"""
from unittest.mock import MagicMock, patch

import pytest

from stock_data.data_provider.base import DataCapability, DataFetchError
from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher


class TestThsFetcherBasics:
    def test_name(self):
        f = ThsFetcher()
        assert f.name == "ThsFetcher"

    def test_priority(self):
        f = ThsFetcher()
        assert f.priority == 7

    def test_is_available(self):
        f = ThsFetcher()
        assert f.is_available() is True

    def test_capabilities(self):
        f = ThsFetcher()
        assert DataCapability.HOT_TOPICS in f.supported_data_types
        assert DataCapability.NORTH_FLOW in f.supported_data_types


class TestHotTopics:
    def setup_method(self):
        self.fetcher = ThsFetcher()

    def test_normalize_hot_topic(self):
        row = {
            "code": "600519", "name": "Test", "reason": "白酒+消费",
            "zhangfu": 5.5, "huanshou": 2.1, "chengjiaoliang": 50000,
            "chengjiaoe": 1000000, "ddejingliang": 100,
        }
        result = self.fetcher._normalize_hot_topic(row)
        assert result["code"] == "600519"
        assert result["reason"] == "白酒+消费"
        assert result["change_pct"] == 5.5
        assert result["turnover_rate"] == 2.1


class TestNorthFlow:
    def setup_method(self):
        self.fetcher = ThsFetcher()

    @patch("stock_data.data_provider.fetchers.ths_fetcher.requests.get")
    def test_returns_records(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "time": ["09:30", "09:31"],
            "hgt": [0.5, 0.7],
            "sgt": [0.3, None],
        }
        mock_get.return_value = mock_response
        result = self.fetcher.get_north_flow()
        assert len(result) == 2
        assert result[0]["hgt_yi"] == 0.5
        assert result[1]["sgt_yi"] is None


class TestHistoricalNotSupported:
    def test_fetch_raw_data_raises(self):
        from stock_data.data_provider.base import DataFetchError
        f = ThsFetcher()
        with pytest.raises(DataFetchError):
            f._fetch_raw_data("600519", "2026-01-01", "2026-05-01")

    def test_normalize_data_raises(self):
        import pandas as pd

        from stock_data.data_provider.base import DataFetchError
        f = ThsFetcher()
        with pytest.raises(DataFetchError):
            f._normalize_data(pd.DataFrame(), "600519")


class TestFetchFlashNewsNormalize:
    """Tests for the pure normalize helper (no network)."""

    def setup_method(self):
        self.fetcher = ThsFetcher()

    def test_normalize_flash_item_full(self):
        from datetime import datetime
        item = {
            "id": "4572951",
            "seq": "677638595",
            "title": "南向资金成交额超 1.7 万亿港元",
            "digest": "南向资金成交额超 1.7 万亿港元。",
            "url": "https://news.10jqka.com.cn/20260623/c677638595.shtml",
            "rtime": "1782181568",
        }
        result = self.fetcher._normalize_flash_item(item)
        assert result["title"] == "南向资金成交额超 1.7 万亿港元"
        assert result["url"] == "https://news.10jqka.com.cn/20260623/c677638595.shtml"
        assert result["source_domain"] == "news.10jqka.com.cn"
        # rtime=1782181568 → 2026-06-22 16:26:08 UTC (local tz may differ; verify just structure)
        assert result["publish_time"].startswith("2026-")
        assert len(result["publish_time"]) == 19  # "YYYY-MM-DD HH:MM:SS"
        assert result["snippet"] == "南向资金成交额超 1.7 万亿港元。"

    def test_normalize_flash_item_missing_optional(self):
        """Defensive: missing digest/rtime should still produce a row."""
        item = {
            "id": "1",
            "title": "标题",
            "url": "https://news.10jqka.com.cn/20260101/c1.shtml",
            # no rtime, no digest
        }
        result = self.fetcher._normalize_flash_item(item)
        assert result["title"] == "标题"
        assert result["url"] == "https://news.10jqka.com.cn/20260101/c1.shtml"
        assert result["source_domain"] == "news.10jqka.com.cn"
        assert result["publish_time"] == ""  # empty fallback
        assert result["snippet"] == ""  # empty fallback

    def test_normalize_flash_item_bad_rtime_keeps_raw(self):
        """If rtime is not a valid int, fall back to the raw string."""
        item = {
            "id": "2",
            "title": "t",
            "url": "https://news.10jqka.com.cn/x",
            "rtime": "not-a-number",
        }
        result = self.fetcher._normalize_flash_item(item)
        assert result["publish_time"] == "not-a-number"  # graceful fallback


class TestFetchFlashNewsSinglePage:
    """Tests for fetch_flash_news(limit<=20): single upstream page."""

    def setup_method(self):
        self.fetcher = ThsFetcher()

    def test_fetch_one_page_uses_correct_url(self, monkeypatch):
        """Verify the upstream URL, params, and headers."""
        import json
        fixture = json.load(open("tests/fixtures/ths_flash_news.json", encoding="utf-8"))
        captured = {}

        def fake_get(url, params=None, headers=None, timeout=None):
            captured["url"] = url
            captured["params"] = params
            captured["headers"] = headers
            captured["timeout"] = timeout
            class R:
                status_code = 200
                def json(self_inner):
                    return fixture
            return R()

        import stock_data.data_provider.fetchers.ths_fetcher as mod
        monkeypatch.setattr(mod.requests, "get", fake_get)

        self.fetcher.fetch_flash_news(limit=10)

        assert captured["url"] == "https://news.10jqka.com.cn/tapp/news/push/stock"
        assert captured["params"] == {"page": "1", "tag": "", "track": "website"}
        assert "Chrome" in captured["headers"]["User-Agent"]
        assert "10jqka.com.cn" in captured["headers"]["Referer"]
        assert captured["timeout"] == 10

    def test_returns_normalized_dicts_from_fixture(self, monkeypatch):
        import json
        fixture = json.load(open("tests/fixtures/ths_flash_news.json", encoding="utf-8"))

        def fake_get(url, params=None, headers=None, timeout=None):
            class R:
                status_code = 200
                def json(self_inner):
                    return fixture
            return R()

        import stock_data.data_provider.fetchers.ths_fetcher as mod
        monkeypatch.setattr(mod.requests, "get", fake_get)

        results = self.fetcher.fetch_flash_news(limit=20)

        assert len(results) == 20  # fixture has 20 items
        first = results[0]
        upstream_first = fixture["data"]["list"][0]
        assert first["title"] == upstream_first["title"]
        assert first["url"] == upstream_first["url"]
        assert first["source_domain"] == "news.10jqka.com.cn"
        assert first["snippet"] == upstream_first["digest"]
        # rtime=1782181568 → 2026-06-22 in UTC (any local tz still year 2026)
        assert first["publish_time"].startswith("2026-")


class TestFetchFlashNewsMultiPage:
    """Tests for fetch_flash_news(limit>20): paginates until enough items."""

    def setup_method(self):
        self.fetcher = ThsFetcher()

    def test_paginates_to_3_pages_for_limit_50(self, monkeypatch):
        """limit=50 → 3 pages requested (3*20=60 >= 50), returns 50 items."""
        import json
        fixture = json.load(open("tests/fixtures/ths_flash_news.json", encoding="utf-8"))
        page_calls = []

        def fake_get(url, params=None, headers=None, timeout=None):
            page_calls.append(params["page"])
            class R:
                status_code = 200
                def json(self_inner):
                    return fixture
            return R()

        import stock_data.data_provider.fetchers.ths_fetcher as mod
        monkeypatch.setattr(mod.requests, "get", fake_get)

        results = self.fetcher.fetch_flash_news(limit=50)

        assert page_calls == ["1", "2", "3"]  # 3 pages
        assert len(results) == 50  # 3 pages of 20, truncated to limit

    def test_paginates_to_10_pages_for_limit_200(self, monkeypatch):
        """limit=200 -> 10 pages, returns 200 items (max)."""
        import json
        fixture = json.load(open("tests/fixtures/ths_flash_news.json", encoding="utf-8"))
        page_calls = []

        def fake_get(url, params=None, headers=None, timeout=None):
            page_calls.append(params["page"])
            class R:
                status_code = 200
                def json(self_inner):
                    return fixture
            return R()

        import stock_data.data_provider.fetchers.ths_fetcher as mod
        monkeypatch.setattr(mod.requests, "get", fake_get)

        results = self.fetcher.fetch_flash_news(limit=200)

        assert page_calls == [str(i) for i in range(1, 11)]  # 10 pages
        assert len(results) == 200

    def test_stops_on_empty_page(self, monkeypatch):
        """If upstream returns an empty list, stop paginating immediately."""
        import json
        fixture = json.load(open("tests/fixtures/ths_flash_news.json", encoding="utf-8"))
        empty = {"code": "200", "msg": "ok", "data": {"list": []}}
        page_calls = []

        def fake_get(url, params=None, headers=None, timeout=None):
            page_calls.append(params["page"])
            if params["page"] == "1":
                payload = fixture
            else:
                payload = empty
            class R:
                status_code = 200
                def json(self_inner, p=payload):
                    return p
            return R()

        import stock_data.data_provider.fetchers.ths_fetcher as mod
        monkeypatch.setattr(mod.requests, "get", fake_get)

        results = self.fetcher.fetch_flash_news(limit=200)

        # page 1 has data (20 items), page 2 is empty -> stop
        assert page_calls == ["1", "2"]
        assert len(results) == 20


class TestFetchFlashNewsLimits:
    """Limit validation and clamping."""

    def setup_method(self):
        self.fetcher = ThsFetcher()

    def test_limit_zero_raises(self):
        with pytest.raises(DataFetchError, match="limit must be"):
            self.fetcher.fetch_flash_news(limit=0)

    def test_limit_negative_raises(self):
        with pytest.raises(DataFetchError, match="limit must be"):
            self.fetcher.fetch_flash_news(limit=-5)

    def test_limit_string_coerced(self, monkeypatch):
        """Route layer sends str; fetcher should coerce to int."""
        import json
        fixture = json.load(open("tests/fixtures/ths_flash_news.json", encoding="utf-8"))

        def fake_get(url, params=None, headers=None, timeout=None):
            class R:
                status_code = 200
                def json(self_inner):
                    return fixture
            return R()

        import stock_data.data_provider.fetchers.ths_fetcher as mod
        monkeypatch.setattr(mod.requests, "get", fake_get)

        results = self.fetcher.fetch_flash_news(limit="10")
        assert len(results) == 10

    def test_limit_non_numeric_raises(self):
        with pytest.raises(DataFetchError, match="limit must be int"):
            self.fetcher.fetch_flash_news(limit="abc")

    def test_limit_above_200_capped_not_raised(self, monkeypatch):
        """limit=500 doesn't raise; capped to 200 (10 pages)."""
        import json
        fixture = json.load(open("tests/fixtures/ths_flash_news.json", encoding="utf-8"))
        page_calls = []

        def fake_get(url, params=None, headers=None, timeout=None):
            page_calls.append(params["page"])
            class R:
                status_code = 200
                def json(self_inner):
                    return fixture
            return R()

        import stock_data.data_provider.fetchers.ths_fetcher as mod
        monkeypatch.setattr(mod.requests, "get", fake_get)

        results = self.fetcher.fetch_flash_news(limit=500)
        assert page_calls == [str(i) for i in range(1, 11)]  # 10 pages
        assert len(results) == 200  # capped
