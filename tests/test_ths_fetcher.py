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

    def test_is_available_docstring_lists_all_six_endpoints(self):
        """Regression (review 2026-07-06 finding #8): the docstring used to
        say 'four pure-HTTP THS endpoints' but the diff on 2026-07-05 added
        STOCK_NEWS + ANNOUNCEMENT, bringing the count to six (hot-topics /
        north-flow / flash-news / news-search / stock-news / announcements).

        Locks the docstring against silent drift if more pure-HTTP
        endpoints are added in the future. Update this list in tandem.
        """
        doc = ThsFetcher.is_available.__doc__
        assert doc is not None
        for endpoint in (
            "hot-topics",
            "north-flow",
            "flash-news",
            "news-search",
            "stock-news",
            "announcements",
        ):
            assert endpoint in doc, (
                f"is_available() docstring missing '{endpoint}' — "
                f"the dep-loss impact count is now stale"
            )

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
            "code": "600519",
            "name": "Test",
            "reason": "白酒+消费",
            "zhangfu": 5.5,
            "huanshou": 2.1,
            "chengjiaoliang": 50000,
            "chengjiaoe": 1000000,
            "ddejingliang": 100,
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
                    {
                        "id": "1",
                        "title": "good",
                        "url": "https://x",
                        "digest": "d",
                        "rtime": "1782181568",
                    },
                    {"id": "2", "title": "bad"},  # missing url → skipped
                    {
                        "id": "3",
                        "title": "also good",
                        "url": "https://y",
                        "digest": "d2",
                        "rtime": "1782181567",
                    },
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
            "title",
            "url",
            "source_domain",
            "publish_date",
            "snippet",
            "media_name",
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
        rec = {
            "url": "https://a.b.com/p",
            "title": "t",
            "extra": {},
            "publish_date": "2026-01-01 00:00:00",
        }
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
                "title",
                "url",
                "source_domain",
                "publish_date",
                "snippet",
                "media_name",
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


# --- get_stock_boards ---------------------------------------------------


class TestGetStockBoards:
    """Tests for ThsFetcher.get_stock_boards (basic.10jqka.com.cn concept list)."""

    def setup_method(self):
        self.fetcher = ThsFetcher()

    def test_returns_normalized_dicts(self):
        """Verify HTTP call shape + response normalization for known market."""
        fake_payload = {
            "status_code": 0,
            "data": [
                {"quote_code": "885642", "name": "跨境电商"},
                {"quote_code": "885910", "name": "拼多多概念"},
            ],
        }

        with patch(
            "stock_data.data_provider.fetchers.ths_fetcher.json_get",
            return_value=fake_payload,
        ) as mock_get:
            result = self.fetcher.get_stock_boards("300740")

        # HTTP called with right URL + params + headers
        args, kwargs = mock_get.call_args
        assert "basic.10jqka.com.cn" in args[0]
        assert args[0].endswith("/stock_concept_list")
        assert kwargs["params"]["code"] == "300740"
        assert kwargs["params"]["market_id"] == "33"  # 深市 (3xx prefix)
        assert kwargs["params"]["simple"] == 1
        assert "Referer" in kwargs["headers"]

        # Response normalized
        assert len(result) == 2
        assert result[0] == {
            "code": "885642",
            "name": "跨境电商",
            "type": "concept",
            "subtype": "同花顺概念",
        }
        assert result[1]["code"] == "885910"

    def test_market_id_mapping(self):
        """沪市代码 → market_id=17; 深市 → 33."""
        fake_payload = {"status_code": 0, "data": []}

        with patch(
            "stock_data.data_provider.fetchers.ths_fetcher.json_get",
            return_value=fake_payload,
        ) as mock_get:
            # 沪市主板 (600xxx)
            self.fetcher.get_stock_boards("600519")
            assert mock_get.call_args.kwargs["params"]["market_id"] == "17"

            # 沪市 B 股 (900xxx)
            self.fetcher.get_stock_boards("900901")
            assert mock_get.call_args.kwargs["params"]["market_id"] == "17"

            # 深市主板 (000xxx)
            self.fetcher.get_stock_boards("000001")
            assert mock_get.call_args.kwargs["params"]["market_id"] == "33"

            # 深市创业板 (300xxx)
            self.fetcher.get_stock_boards("300750")
            assert mock_get.call_args.kwargs["params"]["market_id"] == "33"

    def test_empty_on_unknown_prefix(self):
        """北交所代码 (4/8 prefix) 无 mapping → 空列表 + 不调上游."""
        with patch(
            "stock_data.data_provider.fetchers.ths_fetcher.json_get",
        ) as mock_get:
            result = self.fetcher.get_stock_boards("830799")  # 北交所

        assert result == []
        mock_get.assert_not_called()

    def test_raises_data_fetch_error_on_http_failure(self):
        """json_get 抛异常 → 包装为 DataFetchError."""
        with (
            patch(
                "stock_data.data_provider.fetchers.ths_fetcher.json_get",
                side_effect=RuntimeError("network unreachable"),
            ),
            pytest.raises(DataFetchError, match="stock_concept_list"),
        ):
            self.fetcher.get_stock_boards("300740")

    def test_raises_data_fetch_error_on_business_error(self):
        """上游 status_code != 0 → DataFetchError (对齐 search_news 的契约).

        之前 fetcher 静默返回 [],会让 cold-fill 调用方以为'查了但没数据' —— 实际是
        上游业务级错误 (权限/限流等)。现在抛 DataFetchError,cold-fill 路径可以
        在 cold_sources 中体现失败。
        """
        with (
            patch(
                "stock_data.data_provider.fetchers.ths_fetcher.json_get",
                return_value={"status_code": -1, "status_msg": "forbidden", "data": []},
            ),
            pytest.raises(DataFetchError, match="status_code=-1"),
        ):
            self.fetcher.get_stock_boards("300740")


# --- get_board_stocks ---------------------------------------------------


class TestGetBoardStocks:
    """Tests for ThsFetcher.get_board_stocks (q.10jqka.com.cn board stocks).

    All tests mock at the boundary (ThsFetcher._http_get) so py_mini_racer /
    ths.js are not exercised — the v-token is patched to a literal "x"
    per the precedent in tests/test_ths_board_kline.py:137.
    """

    def setup_method(self):
        self.fetcher = ThsFetcher()
        # Bypass v-token mint (avoids py_mini_racer import during tests).
        self._v_token_patcher = patch.object(ThsFetcher, "_v_token", return_value="x")
        self._v_token_patcher.start()

    def teardown_method(self):
        self._v_token_patcher.stop()

    @staticmethod
    def _make_response(html: str):
        """Build a fake requests.Response with .text/.encoding/.status_code."""

        class _Resp:
            status_code = 200
            encoding = "gbk"
            content = b""

            def __init__(self, body):
                self.text = body
                self.content = body.encode("gbk")

        return _Resp(html)

    @staticmethod
    def _build_html(rows: list) -> str:
        """Build a minimal q.10jqka.com.cn board-stocks HTML fragment.

        14 columns: 序号/代码/名称/现价/涨跌幅/涨跌/涨速/换手/量比/振幅/
                     成交额/流通股/流通市值/市盈率
        """
        body_rows = ""
        for row in rows:
            tds = "".join(f"<td>{c}</td>" for c in row)
            body_rows += f"<tr>{tds}</tr>\n"
        return f"<html><body><table><tbody>\n{body_rows}</tbody></table></body></html>"

    def test_single_page_returns_normalized_dicts(self):
        """One page, two rows → two normalized dicts in canonical shape."""
        html = self._build_html(
            [
                [
                    "1",
                    "300740",
                    "皇台酒业",
                    "10.50",
                    "5.20",
                    "0.52",
                    "0.10",
                    "3.50",
                    "1.20",
                    "2.10",
                    "100000000",
                    "500000000",
                    "5250000000",
                    "30.5",
                ],
                [
                    "2",
                    "000001",
                    "平安银行",
                    "12.30",
                    "1.50",
                    "0.18",
                    "0.05",
                    "0.80",
                    "0.90",
                    "1.50",
                    "200000000",
                    "19000000000",
                    "234000000000",
                    "5.2",
                ],
            ]
        )
        # side_effect list: page 1 returns data; pages 2+ return empty
        # (loop terminates after first empty page). We provide enough
        # empties so the test doesn't depend on the hard cap value.
        side_effects = [self._make_response(html)] + [
            self._make_response(self._build_html([])) for _ in range(49)
        ]
        with patch.object(ThsFetcher, "_http_get", side_effect=side_effects) as mock_get:
            result = self.fetcher.get_board_stocks("308709")

        # URL shape — first call is page 1, field/199112, ajax/1
        first_call = mock_get.call_args_list[0]
        url = first_call.args[0]
        assert "q.10jqka.com.cn" in url
        assert "/gn/detail/code/308709/" in url
        assert "/field/199112/" in url
        assert "/page/1/" in url
        assert "/ajax/1/" in url
        # Cookie + UA + Referer + XHR header (THS AJAX requires XHR)
        headers = first_call.kwargs["headers"]
        assert headers["Cookie"] == "v=x"
        assert "Referer" in headers
        assert "User-Agent" in headers
        assert headers["X-Requested-With"] == "XMLHttpRequest"

        # Output schema — baseline fields populated
        assert len(result) == 2
        assert result[0]["stock_code"] == "300740"
        assert result[0]["stock_name"] == "皇台酒业"
        assert result[0]["exchange"] == "sz"  # 300xxx → 深市
        # Quote fields
        assert result[0]["price"] == 10.50
        assert result[0]["change_pct"] == 5.20
        # THS field/199112 上游没有 成交量(手) 列 — 14 列里只有 成交额(元)
        # (idx 10). 因为 BoardStockInfo.volume 语义是 成交量(股),此处必须 None
        # 而不是塞成交额进去 (避免把元单位当成股单位).
        assert result[0]["volume"] is None
        assert result[0]["amount"] == 100000000.0

        assert result[1]["stock_code"] == "000001"
        assert result[1]["stock_name"] == "平安银行"
        assert result[1]["exchange"] == "sz"

    def test_exchange_mapping(self):
        """沪市 codes → 'sh'; 深市 codes → 'sz'."""
        html = self._build_html(
            [
                [
                    "1",
                    "600519",
                    "贵州茅台",
                    "1800.00",
                    "0.50",
                    "9.00",
                    "0",
                    "0.30",
                    "1.00",
                    "1.00",
                    "50000000",
                    "1200000000",
                    "2160000000000",
                    "30.0",
                ],
                [
                    "2",
                    "000001",
                    "平安银行",
                    "12.00",
                    "1.00",
                    "0.12",
                    "0",
                    "0.50",
                    "0.80",
                    "1.00",
                    "100000000",
                    "19000000000",
                    "228000000000",
                    "5.0",
                ],
                [
                    "3",
                    "300750",
                    "宁德时代",
                    "200.00",
                    "2.00",
                    "4.00",
                    "0",
                    "0.80",
                    "1.00",
                    "2.00",
                    "80000000",
                    "4300000000",
                    "860000000000",
                    "20.0",
                ],
            ]
        )
        side_effects = [self._make_response(html)] + [
            self._make_response(self._build_html([])) for _ in range(49)
        ]
        with patch.object(ThsFetcher, "_http_get", side_effect=side_effects):
            result = self.fetcher.get_board_stocks("301558")
        assert result[0]["exchange"] == "sh"
        assert result[1]["exchange"] == "sz"
        assert result[2]["exchange"] == "sz"

    def test_em_dash_fields_become_none(self):
        """'--' (em-dash) for missing numeric → None (not 0.0)."""
        html = self._build_html(
            [
                [
                    "1",
                    "300740",
                    "皇台酒业",
                    "--",
                    "--",
                    "--",
                    "--",
                    "--",
                    "--",
                    "--",
                    "--",
                    "--",
                    "--",
                    "--",
                ],
            ]
        )
        side_effects = [self._make_response(html)] + [
            self._make_response(self._build_html([])) for _ in range(49)
        ]
        with patch.object(ThsFetcher, "_http_get", side_effect=side_effects):
            result = self.fetcher.get_board_stocks("308709")
        assert len(result) == 1
        # All numeric fields should be None
        for k in ("price", "change_pct", "volume", "turnover_rate", "amount"):
            assert result[0][k] is None, f"{k}={result[0][k]} (expected None)"

    def test_pagination_fans_out_until_empty_page(self):
        """3 pages, page 3 returns 0 rows → loop terminates after page 3."""
        page1_html = self._build_html(
            [
                [
                    str(i + 1),
                    f"3007{40 + i:02d}",
                    f"股票{i}",
                    "10.00",
                    "1.00",
                    "0.10",
                    "0.05",
                    "0.80",
                    "1.00",
                    "1.50",
                    "100000000",
                    "500000000",
                    "5250000000",
                    "30.0",
                ]
                for i in range(10)
            ]
        )
        page2_html = self._build_html(
            [
                [
                    str(i + 11),
                    f"3008{40 + i:02d}",
                    f"股票{i + 10}",
                    "10.00",
                    "1.00",
                    "0.10",
                    "0.05",
                    "0.80",
                    "1.00",
                    "1.50",
                    "100000000",
                    "500000000",
                    "5250000000",
                    "30.0",
                ]
                for i in range(10)
            ]
        )
        page3_html = self._build_html([])  # empty page → terminate

        responses = [
            self._make_response(page1_html),
            self._make_response(page2_html),
            self._make_response(page3_html),
        ]

        with patch.object(ThsFetcher, "_http_get", side_effect=responses) as mock_get:
            result = self.fetcher.get_board_stocks("308709")

        # 3 HTTP calls (page 1, 2, 3 — page 3 is empty so loop terminates)
        assert mock_get.call_count == 3
        # Page numbers in URLs
        urls = [c.args[0] for c in mock_get.call_args_list]
        assert "/page/1/" in urls[0]
        assert "/page/2/" in urls[1]
        assert "/page/3/" in urls[2]
        # Result union: 10 + 10 = 20 rows
        assert len(result) == 20
        assert result[0]["stock_code"] == "300740"
        assert result[9]["stock_code"] == "300749"
        assert result[10]["stock_code"] == "300840"
        assert result[19]["stock_code"] == "300849"

    def test_raises_data_fetch_error_on_http_failure(self):
        """HTTP non-2xx on the FIRST page → DataFetchError (real failure).

        The first page is the only page where a non-2xx is fatal — we have
        no rows yet, so we can't tell whether the upstream is down or just
        signalling an out-of-range page. The next test
        (``test_401_after_data_treated_as_end_of_pagination``) locks the
        beyond-data tolerance contract.
        """

        class _Bad:
            status_code = 401
            encoding = "utf-8"
            text = "<html>Unauthorized</html>"
            content = b"<html>Unauthorized</html>"

        with (
            patch.object(ThsFetcher, "_http_get", return_value=_Bad()),
            pytest.raises(DataFetchError, match="board_stocks"),
        ):
            self.fetcher.get_board_stocks("308709")

    def test_401_after_data_treated_as_end_of_pagination(self):
        """HTTP 401 on a beyond-data page → graceful end-of-pagination.

        Repro for the user-reported bug
        /api/v1/boards/885652/stocks?source=ths&include_quote=false
        → ``[ThsFetcher] board_stocks(300351, page=3) HTTP 401 (417B body)``.

        THS upstream routinely obscures the end-of-pagination boundary by
        returning a small 401/403 on the page PAST the data. When we've
        already received data on prior pages, that's not a real failure —
        it's their signal that there's nothing left, and we treat it as
        end-of-data so callers get the rows we DO have instead of a 5xx.

        Scope: only 401/403 are tolerated. 5xx (real upstream failure)
        and network errors still propagate — see
        ``test_5xx_after_data_still_raises`` and
        ``test_network_error_after_data_still_raises``.
        """
        page1_html = self._build_html(
            [
                [
                    str(i + 1),
                    f"3007{40 + i:02d}",
                    f"股票{i}",
                    "10.00",
                    "1.00",
                    "0.10",
                    "0.05",
                    "0.80",
                    "1.00",
                    "1.50",
                    "100000000",
                    "500000000",
                    "5250000000",
                    "30.0",
                ]
                for i in range(10)
            ]
        )
        page2_html = self._build_html(
            [
                [
                    str(i + 11),
                    f"3008{40 + i:02d}",
                    f"股票{i + 10}",
                    "10.00",
                    "1.00",
                    "0.10",
                    "0.05",
                    "0.80",
                    "1.00",
                    "1.50",
                    "100000000",
                    "500000000",
                    "5250000000",
                    "30.0",
                ]
                for i in range(5)
            ]
        )

        class _EndOfPagination:
            """THS's 'we have no more data' signal — sometimes a clean
            200 empty body, sometimes a small 401/403 body."""
            status_code = 401
            encoding = "utf-8"
            text = "<html>Unauthorized</html>"
            content = b"<html>Unauthorized</html>"

        responses = [
            self._make_response(page1_html),
            self._make_response(page2_html),
            _EndOfPagination(),
        ]

        with patch.object(ThsFetcher, "_http_get", side_effect=responses) as mock_get:
            result = self.fetcher.get_board_stocks("308709")

        # 15 rows from pages 1+2; page 3's 401 was tolerated.
        assert len(result) == 15
        assert result[0]["stock_code"] == "300740"
        assert result[14]["stock_code"] == "300844"
        # 3 HTTP calls made (page 1, page 2, page 3 with 401 — loop broke).
        assert mock_get.call_count == 3

    def test_5xx_after_data_still_raises(self):
        """A 5xx on a beyond-data page is NOT tolerated — still raises.

        Guards the P1 product decision: only 401/403 are upstream
        boundary signals. 5xx means the upstream is genuinely broken,
        and surfacing it (so the route returns 5xx, the circuit breaker
        can trip, ops can see it) is more important than silently
        returning partial data.
        """
        page1_html = self._build_html(
            [
                [
                    str(i + 1),
                    f"3007{40 + i:02d}",
                    f"股票{i}",
                    "10.00",
                    "1.00",
                    "0.10",
                    "0.05",
                    "0.80",
                    "1.00",
                    "1.50",
                    "100000000",
                    "500000000",
                    "5250000000",
                    "30.0",
                ]
                for i in range(10)
            ]
        )

        class _ServerError:
            status_code = 503
            encoding = "utf-8"
            text = "<html>upstream down</html>"
            content = b"<html>upstream down</html>"

        responses = [
            self._make_response(page1_html),
            _ServerError(),  # 503 — NOT a boundary signal; must raise
        ]

        with (
            patch.object(ThsFetcher, "_http_get", side_effect=responses),
            pytest.raises(DataFetchError, match="HTTP 503"),
        ):
            self.fetcher.get_board_stocks("308709")

    def test_network_error_after_data_still_raises(self):
        """A network error on a beyond-data page is NOT tolerated — still raises.

        Same P1 rationale: only 401/403 are upstream boundary signals.
        ConnectionError indicates a real transport problem that the
        route / circuit breaker should see, not partial data.
        """
        page1_html = self._build_html(
            [
                [
                    str(i + 1),
                    f"3007{40 + i:02d}",
                    f"股票{i}",
                    "10.00",
                    "1.00",
                    "0.10",
                    "0.05",
                    "0.80",
                    "1.00",
                    "1.50",
                    "100000000",
                    "500000000",
                    "5250000000",
                    "30.0",
                ]
                for i in range(10)
            ]
        )

        import requests as _requests

        responses = [
            self._make_response(page1_html),
            _requests.ConnectionError("refused"),
        ]

        with (
            patch.object(ThsFetcher, "_http_get", side_effect=responses),
            pytest.raises(DataFetchError, match="network failed"),
        ):
            self.fetcher.get_board_stocks("308709")

    def test_raises_data_fetch_error_on_network_failure(self):
        """requests.ConnectionError → DataFetchError."""
        import requests as _requests

        with (
            patch.object(
                ThsFetcher,
                "_http_get",
                side_effect=_requests.ConnectionError("refused"),
            ),
            pytest.raises(DataFetchError, match="board_stocks"),
        ):
            self.fetcher.get_board_stocks("308709")

    def test_accepts_kwargs_for_interface_parity(self):
        """Accepts source/include_quote/board_type kwargs without error."""
        html = self._build_html([])
        with patch.object(ThsFetcher, "_http_get", return_value=self._make_response(html)):
            result = self.fetcher.get_board_stocks(
                "308709",
                source="ths",
                include_quote=True,
                board_type="concept",
            )
        assert result == []

    def test_mid_pagination_401_truncates_without_retry(self):
        """First 401/403 after data ends the loop, even if more pages exist.

        Locks the 'sticky boundary' trade-off documented in
        ``get_board_stocks``'s docstring. The 3-call sequence is
        page1=10 rows → page2=401 → page3=10 rows; the test asserts
        that the fetcher returns only page1's 10 rows and the
        pagination loop does NOT issue page3.

        Pairs with ``test_401_after_data_treated_as_end_of_pagination``
        which covers the *last-page* 401 case (page1=10 → page2=5 →
        page3=401). Together they pin the full behavior: any 401/403
        after data is the boundary, regardless of whether more data
        would have followed.
        """
        page1_html = self._build_html(
            [
                [
                    str(i + 1),
                    f"3007{40 + i:02d}",
                    f"股票{i}",
                    "10.00",
                    "1.00",
                    "0.10",
                    "0.05",
                    "0.80",
                    "1.00",
                    "1.50",
                    "100000000",
                    "500000000",
                    "5250000000",
                    "30.0",
                ]
                for i in range(10)
            ]
        )
        # page3 is constructed but the test asserts the loop never consumes it.
        page3_html = self._build_html(
            [
                [
                    str(i + 11),
                    f"3008{40 + i:02d}",
                    f"股票{i + 10}",
                    "10.00",
                    "1.00",
                    "0.10",
                    "0.05",
                    "0.80",
                    "1.00",
                    "1.50",
                    "100000000",
                    "500000000",
                    "5250000000",
                    "30.0",
                ]
                for i in range(10)
            ]
        )

        class _MidPaginationAuth:
            """THS returning 401 mid-pagination (NOT on the last page)."""
            status_code = 401
            encoding = "utf-8"
            text = "<html>Unauthorized</html>"
            content = b"<html>Unauthorized</html>"

        responses = [
            self._make_response(page1_html),
            _MidPaginationAuth(),
            self._make_response(page3_html),  # would-be-ignored
        ]

        with patch.object(ThsFetcher, "_http_get", side_effect=responses) as mock_get:
            result = self.fetcher.get_board_stocks("308709")

        # Only page1's 10 rows — page3 was never issued.
        assert len(result) == 10
        assert result[0]["stock_code"] == "300740"
        assert result[9]["stock_code"] == "300749"
        # Loop broke on page2; page3 was never issued.
        assert mock_get.call_count == 2


    def test_ths_boundary_signal_error_is_subclass_of_data_fetch_error(self):
        """ThsBoundarySignalError is a DataFetchError subclass; carries status_code.

        Locks the public exception surface: callers that catch
        DataFetchError (the broader category) still see boundary
        signals, and ``status_code`` is observable for observability
        + tests.
        """
        from stock_data.data_provider.fetchers.ths_fetcher import (
            ThsBoundarySignalError,
        )

        err = ThsBoundarySignalError("test", status_code=401)
        # Public contract: subclass relationship + status_code attribute.
        assert isinstance(err, DataFetchError)
        assert err.status_code == 401
        assert "test" in str(err)

        # Boundary tolerance frozenset is the single source of truth.
        from stock_data.data_provider.fetchers.ths_fetcher import (
            _BOUNDARY_TOLERATED_STATUSES,
        )

        assert 401 in _BOUNDARY_TOLERATED_STATUSES
        assert 403 in _BOUNDARY_TOLERATED_STATUSES
        # 5xx / 200 / 302 must NOT be tolerated.
        assert 503 not in _BOUNDARY_TOLERATED_STATUSES
        assert 200 not in _BOUNDARY_TOLERATED_STATUSES


class TestBoardStocksSortFieldMap:
    def test_field_map_has_11_entries(self):
        from stock_data.data_provider.fetchers.ths_fetcher import (
            _THS_BOARD_STOCKS_SORT_FIELD_MAP,
        )
        assert len(_THS_BOARD_STOCKS_SORT_FIELD_MAP) == 11

    def test_field_map_known_entries(self):
        """11 个排序键与实测 THS 上游列代码对应 (2026-07-13 playwright probe)."""
        from stock_data.data_provider.fetchers.ths_fetcher import (
            _THS_BOARD_STOCKS_SORT_FIELD_MAP,
        )
        expected = {
            "change_pct":        "199112",
            "price":             "10",
            "turnover_rate":     "1968584",
            "volume_ratio":      "1771976",
            "amplitude":         "526792",
            "change_amount":     "264648",
            "change_speed":      "48",
            "amount":            "19",
            "pe_ratio":          "2034120",
            "float_market_cap":  "3475914",
            "free_float_shares": "407",
        }
        assert _THS_BOARD_STOCKS_SORT_FIELD_MAP == expected


class TestBoardStocksUrlTemplate:
    def test_url_template_renders_with_field_code_and_order(self):
        from stock_data.data_provider.fetchers.ths_fetcher import (
            _BOARD_STOCKS_URL_TEMPLATE,
        )
        url = _BOARD_STOCKS_URL_TEMPLATE.format(
            concept_id="301085", field_code="10", order="desc", page=1
        )
        assert url == (
            "https://q.10jqka.com.cn/gn/detail/code/301085"
            "/field/10/order/desc/page/1/ajax/1/"
        )
