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
        # Conditional on py_mini_racer + ths.js shipping — same shape
        # as the dedicated TestIsAvailable in test_ths_board_kline.py.
        # In dev environments the deps may or may not be present.
        f = ThsFetcher()
        result = f.is_available()
        assert isinstance(result, bool)
        if result:
            assert f.unavailable_reason() is None
        else:
            assert f.unavailable_reason() and "board_history unavailable" in f.unavailable_reason()

    def test_capabilities(self):
        f = ThsFetcher()
        assert DataCapability.HOT_TOPICS in f.supported_data_types
        assert DataCapability.NORTH_FLOW in f.supported_data_types
        assert DataCapability.NEWS_FLASH in f.supported_data_types
        assert DataCapability.NEWS_SEARCH in f.supported_data_types


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

    @patch("stock_data.data_provider.utils.http.requests.get")
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
        # rtime=1782181568 → 2026-06-22 16:26:08 UTC; verify dynamically so the
        # test doesn't break in 2027+ (year-coupled assertions rot on Jan 1).
        expected_year = datetime.utcfromtimestamp(1782181568).year
        assert result["publish_time"].startswith(f"{expected_year}-")
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
        with open("tests/fixtures/ths_flash_news.json", encoding="utf-8") as _f:
            fixture = json.load(_f)
        captured = {}

        def fake_get(url, params=None, headers=None, timeout=None):
            captured["url"] = url
            captured["params"] = params
            captured["headers"] = headers
            captured["timeout"] = timeout
            class R:
                status_code = 200
                def raise_for_status(self):
                    pass
                def json(self):
                    return fixture
            return R()

        import stock_data.data_provider.utils.http as http_mod
        monkeypatch.setattr(http_mod.requests, "get", fake_get)

        self.fetcher.fetch_flash_news(limit=10)

        assert captured["url"] == "https://news.10jqka.com.cn/tapp/news/push/stock"
        assert captured["params"] == {"page": "1", "tag": "", "track": "website"}
        assert "Chrome" in captured["headers"]["User-Agent"]
        assert "10jqka.com.cn" in captured["headers"]["Referer"]
        assert captured["timeout"] == 10

    def test_returns_normalized_dicts_from_fixture(self, monkeypatch):
        import json
        with open("tests/fixtures/ths_flash_news.json", encoding="utf-8") as _f:
            fixture = json.load(_f)

        def fake_get(url, params=None, headers=None, timeout=None):
            class R:
                status_code = 200
                def raise_for_status(self):
                    pass
                def json(self):
                    return fixture
            return R()

        import stock_data.data_provider.utils.http as http_mod
        monkeypatch.setattr(http_mod.requests, "get", fake_get)

        results = self.fetcher.fetch_flash_news(limit=20)

        assert len(results) == 20  # fixture has 20 items
        first = results[0]
        upstream_first = fixture["data"]["list"][0]
        assert first["title"] == upstream_first["title"]
        assert first["url"] == upstream_first["url"]
        assert first["source_domain"] == "news.10jqka.com.cn"
        assert first["snippet"] == upstream_first["digest"]
        # rtime=1782181568 → 2026-06-22 in UTC; verify dynamically (year-coupled
        # assertions rot on Jan 1, see test_normalize_flash_item_full).
        from datetime import datetime
        expected_year = datetime.utcfromtimestamp(1782181568).year
        assert first["publish_time"].startswith(f"{expected_year}-")


class TestFetchFlashNewsMultiPage:
    """Tests for fetch_flash_news(limit>20): paginates until enough items."""

    def setup_method(self):
        self.fetcher = ThsFetcher()

    def test_paginates_to_3_pages_for_limit_50(self, monkeypatch):
        """limit=50 → 3 pages requested (3*20=60 >= 50), returns 50 items."""
        import json
        with open("tests/fixtures/ths_flash_news.json", encoding="utf-8") as _f:
            fixture = json.load(_f)
        page_calls = []

        def fake_get(url, params=None, headers=None, timeout=None):
            page_calls.append(params["page"])
            class R:
                status_code = 200
                def raise_for_status(self):
                    pass
                def json(self):
                    return fixture
            return R()

        import stock_data.data_provider.utils.http as http_mod
        monkeypatch.setattr(http_mod.requests, "get", fake_get)

        results = self.fetcher.fetch_flash_news(limit=50)

        assert page_calls == ["1", "2", "3"]  # 3 pages
        assert len(results) == 50  # 3 pages of 20, truncated to limit

    def test_paginates_to_10_pages_for_limit_200(self, monkeypatch):
        """limit=200 -> 10 pages, returns 200 items (max)."""
        import json
        with open("tests/fixtures/ths_flash_news.json", encoding="utf-8") as _f:
            fixture = json.load(_f)
        page_calls = []

        def fake_get(url, params=None, headers=None, timeout=None):
            page_calls.append(params["page"])
            class R:
                status_code = 200
                def raise_for_status(self):
                    pass
                def json(self):
                    return fixture
            return R()

        import stock_data.data_provider.utils.http as http_mod
        monkeypatch.setattr(http_mod.requests, "get", fake_get)

        results = self.fetcher.fetch_flash_news(limit=200)

        assert page_calls == [str(i) for i in range(1, 11)]  # 10 pages
        assert len(results) == 200

    def test_stops_on_empty_page(self, monkeypatch):
        """If upstream returns an empty list, stop paginating immediately."""
        import json
        with open("tests/fixtures/ths_flash_news.json", encoding="utf-8") as _f:
            fixture = json.load(_f)
        empty = {"code": "200", "msg": "ok", "data": {"list": []}}
        page_calls = []

        def fake_get(url, params=None, headers=None, timeout=None):
            page_calls.append(params["page"])
            payload = fixture if params["page"] == "1" else empty
            class R:
                status_code = 200
                def raise_for_status(self):
                    pass
                def json(self, p=payload):
                    return p
            return R()

        import stock_data.data_provider.utils.http as http_mod
        monkeypatch.setattr(http_mod.requests, "get", fake_get)

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
        with open("tests/fixtures/ths_flash_news.json", encoding="utf-8") as _f:
            fixture = json.load(_f)

        def fake_get(url, params=None, headers=None, timeout=None):
            class R:
                status_code = 200
                def raise_for_status(self):
                    pass
                def json(self):
                    return fixture
            return R()

        import stock_data.data_provider.utils.http as http_mod
        monkeypatch.setattr(http_mod.requests, "get", fake_get)

        results = self.fetcher.fetch_flash_news(limit="10")
        assert len(results) == 10

    def test_limit_non_numeric_raises(self):
        with pytest.raises(DataFetchError, match="limit must be int"):
            self.fetcher.fetch_flash_news(limit="abc")

    def test_limit_above_200_capped_not_raised(self, monkeypatch):
        """limit=500 doesn't raise; capped to 200 (10 pages)."""
        import json
        with open("tests/fixtures/ths_flash_news.json", encoding="utf-8") as _f:
            fixture = json.load(_f)
        page_calls = []

        def fake_get(url, params=None, headers=None, timeout=None):
            page_calls.append(params["page"])
            class R:
                status_code = 200
                def raise_for_status(self):
                    pass
                def json(self):
                    return fixture
            return R()

        import stock_data.data_provider.utils.http as http_mod
        monkeypatch.setattr(http_mod.requests, "get", fake_get)

        results = self.fetcher.fetch_flash_news(limit=500)
        assert page_calls == [str(i) for i in range(1, 11)]  # 10 pages
        assert len(results) == 200  # capped


class TestFetchFlashNewsErrors:
    """Error handling for fetch_flash_news."""

    def setup_method(self):
        self.fetcher = ThsFetcher()

    def test_http_error_raises(self, monkeypatch):
        import requests as _requests
        class R:
            status_code = 500
            def raise_for_status(self):
                raise _requests.exceptions.HTTPError("500 Server Error")
            def json(self):
                return {}
        import stock_data.data_provider.utils.http as http_mod
        monkeypatch.setattr(http_mod.requests, "get", lambda *a, **kw: R())
        with pytest.raises(DataFetchError, match="HTTP"):
            self.fetcher.fetch_flash_news(limit=10)

    def test_network_error_raises(self, monkeypatch):
        import requests as _requests

        import stock_data.data_provider.utils.http as http_mod
        def boom(*a, **kw):
            raise _requests.ConnectionError("refused")
        monkeypatch.setattr(http_mod.requests, "get", boom)
        with pytest.raises(DataFetchError, match="Request failed"):
            self.fetcher.fetch_flash_news(limit=10)

    def test_bad_json_raises(self, monkeypatch):
        class R:
            status_code = 200
            def raise_for_status(self):
                pass
            def json(self):
                raise ValueError("bad json")
        import stock_data.data_provider.utils.http as http_mod
        monkeypatch.setattr(http_mod.requests, "get", lambda *a, **kw: R())
        with pytest.raises(DataFetchError, match="Invalid JSON"):
            self.fetcher.fetch_flash_news(limit=10)

    def test_upstream_error_code_raises(self, monkeypatch):
        bad = {"code": -1, "msg": "rate limited", "data": None}
        class R:
            status_code = 200
            def raise_for_status(self):
                pass
            def json(self):
                return bad
        import stock_data.data_provider.utils.http as http_mod
        monkeypatch.setattr(http_mod.requests, "get", lambda *a, **kw: R())
        with pytest.raises(DataFetchError, match="code=-1"):
            self.fetcher.fetch_flash_news(limit=10)

    def test_empty_list_returns_empty(self, monkeypatch):
        empty = {"code": "200", "msg": "ok", "data": {"list": []}}
        class R:
            status_code = 200
            def raise_for_status(self):
                pass
            def json(self):
                return empty
        import stock_data.data_provider.utils.http as http_mod
        monkeypatch.setattr(http_mod.requests, "get", lambda *a, **kw: R())
        results = self.fetcher.fetch_flash_news(limit=10)
        assert results == []

    def test_null_list_returns_empty(self, monkeypatch):
        """data.list is null (not []) -> return [] (not raise)."""
        null_list = {"code": "200", "msg": "ok", "data": {"list": None}}
        class R:
            status_code = 200
            def raise_for_status(self):
                pass
            def json(self):
                return null_list
        import stock_data.data_provider.utils.http as http_mod
        monkeypatch.setattr(http_mod.requests, "get", lambda *a, **kw: R())
        results = self.fetcher.fetch_flash_news(limit=10)
        assert results == []

    def test_missing_data_returns_empty(self, monkeypatch):
        """data key entirely missing -> return []."""
        no_data = {"code": "200", "msg": "ok"}
        class R:
            status_code = 200
            def raise_for_status(self):
                pass
            def json(self):
                return no_data
        import stock_data.data_provider.utils.http as http_mod
        monkeypatch.setattr(http_mod.requests, "get", lambda *a, **kw: R())
        results = self.fetcher.fetch_flash_news(limit=10)
        assert results == []

    def test_malformed_record_skipped(self, monkeypatch):
        """One record with missing url → skipped, others kept."""
        fixture = {
            "code": "200",
            "msg": "ok",
            "data": {
                "list": [
                    {"id": "1", "title": "good", "url": "https://x", "digest": "d", "rtime": "1782181568"},
                    {"id": "2", "title": "bad"},  # missing url → skipped
                    {"id": "3", "title": "also good", "url": "https://y", "digest": "d2", "rtime": "1782181567"},
                ]
            },
        }
        class R:
            status_code = 200
            def raise_for_status(self):
                pass
            def json(self):
                return fixture
        import stock_data.data_provider.utils.http as http_mod
        monkeypatch.setattr(http_mod.requests, "get", lambda *a, **kw: R())
        results = self.fetcher.fetch_flash_news(limit=10)
        assert len(results) == 2
        assert results[0]["title"] == "good"
        assert results[1]["title"] == "also good"


# ----------------------------------------------------------------------
# News search (问财 iWenCai) tests
# ----------------------------------------------------------------------

# 一条真实形态的 iWenCai comprehensive/search 响应(裁剪)。
_IWENCAI_FIXTURE = {
    "status_msg": "OK",
    "status_code": 0,
    "total": 3,
    "data": [
        {
            "channel": "news",
            "id": "55bb135d35c4b018",
            "url": "https://finance.sina.com.cn/wm/2026-06-03/doc-iniacnun2387005.shtml",
            "title": "贵州茅台拟提高每股分红金额",
            "summary": "贵州茅台6月2日晚间发布公告，调整2025年年度利润分配方案。",
            "extra": {"publish_source": "新浪财经", "host_name": "finance.sina.com.cn"},
            "publish_date": "2026-06-03 16:53:00",
        },
        {
            "channel": "news",
            "id": "af9a96fa73c76ed6",
            "url": "http://stock.10jqka.com.cn/20260630/c677840543.shtml",
            "title": "<em>茅台</em>股东会召开",
            "summary": "贵州<em>茅台</em>2025年度股东会在茅台会议中心举行。",
            "extra": {"publish_source": "证券时报网", "host_name": "stock.10jqka.com.cn"},
            "publish_date": "2026-06-30 18:28:21",
        },
        {
            "channel": "news",
            "id": "deadbeef",
            # 缺 title → 坏数据, 应被跳过
            "url": "http://example.com/x",
            "summary": "no title here",
            "extra": {},
            "publish_date": "2026-06-20 09:00:00",
        },
    ],
}


def _fake_post_ok(payload):
    """Build a fake requests.post returning ``payload`` with HTTP 200."""

    def _post(url, json=None, headers=None, timeout=None):
        class R:
            status_code = 200
            encoding = "utf-8"

            def raise_for_status(self):
                pass

            def json(self):
                return payload

        return R()

    return _post


class TestSearchNewsNormalize:
    """Pure normalize helper — no network."""

    def setup_method(self):
        self.fetcher = ThsFetcher()

    def test_normalize_full(self):
        rec = _IWENCAI_FIXTURE["data"][0]
        out = self.fetcher._normalize_search_item(rec)
        assert set(out.keys()) == {
            "title", "url", "source_domain", "publish_date", "snippet", "media_name",
        }
        assert out["title"] == "贵州茅台拟提高每股分红金额"
        assert out["url"] == rec["url"]
        assert out["source_domain"] == "finance.sina.com.cn"
        assert out["publish_date"] == "2026-06-03"  # 截到日
        assert out["media_name"] == "新浪财经"
        assert "晚间发布公告" in out["snippet"]

    def test_normalize_strips_em_tags(self):
        rec = _IWENCAI_FIXTURE["data"][1]
        out = self.fetcher._normalize_search_item(rec)
        assert "<em>" not in out["title"] and "</em>" not in out["title"]
        assert out["title"] == "茅台股东会召开"
        assert "<em>" not in out["snippet"]

    def test_normalize_source_domain_falls_back_to_url(self):
        rec = {"url": "https://a.b.com/p", "title": "t", "extra": {}, "publish_date": "2026-01-01 00:00:00"}
        out = self.fetcher._normalize_search_item(rec)
        assert out["source_domain"] == "a.b.com"  # extra.host_name 缺失 → urlparse

    def test_normalize_missing_url_raises(self):
        with pytest.raises(KeyError):
            self.fetcher._normalize_search_item({"title": "t", "extra": {}})


class TestSearchNewsRequest:
    """search_news request construction + response handling."""

    def setup_method(self):
        self.fetcher = ThsFetcher()

    def test_builds_correct_request(self, monkeypatch):
        captured = {}

        def fake_post(url, json=None, headers=None, timeout=None):
            captured.update(url=url, json=json, headers=headers, timeout=timeout)
            class R:
                status_code = 200
                encoding = "utf-8"
                def raise_for_status(self):
                    pass
                def json(self):
                    return _IWENCAI_FIXTURE
            return R()

        import stock_data.data_provider.utils.http as http_mod
        monkeypatch.setattr(http_mod.requests, "post", fake_post)

        self.fetcher.search_news("茅台", limit=5)

        assert captured["url"].endswith("/gateway/mobilesearch/comprehensive/search")
        assert "iwencai.com" in captured["url"]
        assert captured["json"]["query"] == "茅台"
        assert captured["json"]["size"] == 5
        assert captured["json"]["app_id"] == "wencai_pc"
        assert captured["json"]["channels"] == ["news_filter", "web"]
        assert captured["timeout"] == 15

    def test_returns_normalized_dicts_and_skips_malformed(self, monkeypatch):
        import stock_data.data_provider.utils.http as http_mod
        monkeypatch.setattr(http_mod.requests, "post", _fake_post_ok(_IWENCAI_FIXTURE))

        results = self.fetcher.search_news("茅台", limit=10)

        # fixture 有 3 条, 第 3 条缺 title → 跳过 → 2 条
        assert len(results) == 2
        assert results[0]["title"] == "贵州茅台拟提高每股分红金额"
        assert results[1]["title"] == "茅台股东会召开"
        for it in results:
            assert set(it.keys()) == {
                "title", "url", "source_domain", "publish_date", "snippet", "media_name",
            }

    def test_from_date_filter(self, monkeypatch):
        import stock_data.data_provider.utils.http as http_mod
        monkeypatch.setattr(http_mod.requests, "post", _fake_post_ok(_IWENCAI_FIXTURE))
        # 只保留 2026-06-30 当天及以后 → 仅第 2 条
        results = self.fetcher.search_news("茅台", from_date="2026-06-10", limit=10)
        assert len(results) == 1
        assert results[0]["publish_date"] == "2026-06-30"

    def test_to_date_filter(self, monkeypatch):
        import stock_data.data_provider.utils.http as http_mod
        monkeypatch.setattr(http_mod.requests, "post", _fake_post_ok(_IWENCAI_FIXTURE))
        # 只保留 2026-06-03 当天及以前 → 仅第 1 条
        results = self.fetcher.search_news("茅台", to_date="2026-06-10", limit=10)
        assert len(results) == 1
        assert results[0]["publish_date"] == "2026-06-03"

    def test_empty_data_returns_empty(self, monkeypatch):
        import stock_data.data_provider.utils.http as http_mod
        payload = {"status_msg": "OK", "status_code": 0, "total": 0, "data": []}
        monkeypatch.setattr(http_mod.requests, "post", _fake_post_ok(payload))
        assert self.fetcher.search_news("不存在的词", limit=10) == []


class TestSearchNewsValidation:
    """q / limit validation (mirrors EastMoney/Baidu search_news)."""

    def setup_method(self):
        self.fetcher = ThsFetcher()

    def test_empty_q_raises(self):
        with pytest.raises(DataFetchError, match="invalid q"):
            self.fetcher.search_news("", limit=10)

    def test_too_long_q_raises(self):
        with pytest.raises(DataFetchError, match="invalid q"):
            self.fetcher.search_news("x" * 201, limit=10)

    def test_limit_zero_raises(self):
        with pytest.raises(DataFetchError, match="limit must be 1..100"):
            self.fetcher.search_news("茅台", limit=0)

    def test_limit_over_100_raises(self):
        with pytest.raises(DataFetchError, match="limit must be 1..100"):
            self.fetcher.search_news("茅台", limit=101)

    def test_limit_non_numeric_raises(self):
        with pytest.raises(DataFetchError, match="must be an integer"):
            self.fetcher.search_news("茅台", limit="abc")

    def test_limit_string_coerced(self, monkeypatch):
        import stock_data.data_provider.utils.http as http_mod
        monkeypatch.setattr(http_mod.requests, "post", _fake_post_ok(_IWENCAI_FIXTURE))
        results = self.fetcher.search_news("茅台", limit="10")
        assert len(results) == 2


class TestSearchNewsErrors:
    """Error handling for search_news."""

    def setup_method(self):
        self.fetcher = ThsFetcher()

    def test_http_error_raises(self, monkeypatch):
        import requests as _requests
        class R:
            status_code = 502
            encoding = "utf-8"
            def raise_for_status(self):
                raise _requests.exceptions.HTTPError("502 Bad Gateway")
            def json(self):
                return {}
        import stock_data.data_provider.utils.http as http_mod
        monkeypatch.setattr(http_mod.requests, "post", lambda *a, **kw: R())
        with pytest.raises(DataFetchError, match="HTTP"):
            self.fetcher.search_news("茅台", limit=10)

    def test_network_error_raises(self, monkeypatch):
        import requests as _requests

        import stock_data.data_provider.utils.http as http_mod
        def boom(*a, **kw):
            raise _requests.ConnectionError("refused")
        monkeypatch.setattr(http_mod.requests, "post", boom)
        with pytest.raises(DataFetchError, match="Request failed"):
            self.fetcher.search_news("茅台", limit=10)

    def test_bad_json_raises(self, monkeypatch):
        class R:
            status_code = 200
            encoding = "utf-8"
            def raise_for_status(self):
                pass
            def json(self):
                raise ValueError("bad json")
        import stock_data.data_provider.utils.http as http_mod
        monkeypatch.setattr(http_mod.requests, "post", lambda *a, **kw: R())
        with pytest.raises(DataFetchError, match="Invalid JSON"):
            self.fetcher.search_news("茅台", limit=10)

    def test_upstream_status_code_raises(self, monkeypatch):
        bad = {"status_msg": "FAIL", "status_code": -1, "data": []}
        import stock_data.data_provider.utils.http as http_mod
        monkeypatch.setattr(http_mod.requests, "post", _fake_post_ok(bad))
        with pytest.raises(DataFetchError, match="status_code=-1"):
            self.fetcher.search_news("茅台", limit=10)
