"""Unit tests for BaiduFetcher.search_news() and gating."""

import json
from unittest.mock import MagicMock, patch

import pytest
import requests

from stock_data.data_provider.base import DataFetchError
from stock_data.data_provider.fetchers import baidu_fetcher
from stock_data.data_provider.fetchers.baidu_fetcher import (
    DEFAULT_BLOCKED_DOMAINS,
    DEFAULT_MOBILE_PREFIXES,
    DEFAULT_NEWS_DOMAINS,
    BaiduFetcher,
    _domain_matches,
    _is_mobile_host,
    _load_blocked_domains,
    _load_mobile_prefixes,
    _load_news_domains,
)

# ---------- Availability gating ----------


class TestIsAvailable:
    def test_returns_false_when_api_key_missing(self, monkeypatch):
        monkeypatch.delenv("BAIDU_API_KEY", raising=False)
        fetcher = BaiduFetcher()
        assert fetcher.is_available() is False

    def test_returns_false_when_api_key_empty_string(self, monkeypatch):
        monkeypatch.setenv("BAIDU_API_KEY", "   ")
        fetcher = BaiduFetcher()
        assert fetcher.is_available() is False

    def test_returns_true_when_api_key_set(self, monkeypatch):
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/ALTAK-xxx/yyy")
        fetcher = BaiduFetcher()
        assert fetcher.is_available() is True

    def test_priority_default_is_seven(self, monkeypatch):
        monkeypatch.delenv("BAIDU_PRIORITY", raising=False)
        assert BaiduFetcher.priority == 7

    def test_priority_overridable_via_env(self, monkeypatch):
        monkeypatch.setenv("BAIDU_PRIORITY", "5")
        # Re-import to pick up env var (class attr read at class body time)
        import importlib

        from stock_data.data_provider.fetchers import baidu_fetcher

        importlib.reload(baidu_fetcher)
        assert baidu_fetcher.BaiduFetcher.priority == 5

    def test_unavailable_reason_mentions_env_var(self, monkeypatch):
        monkeypatch.delenv("BAIDU_API_KEY", raising=False)
        fetcher = BaiduFetcher()
        reason = fetcher.unavailable_reason()
        assert reason is not None
        assert "BAIDU_API_KEY" in reason


# ---------- Base method stubs ----------


class TestKLineMethodsRaise:
    def test_fetch_raw_data_raises(self):
        fetcher = BaiduFetcher()
        with pytest.raises(DataFetchError, match="does not support historical K-line"):
            fetcher._fetch_raw_data("600519", "2025-01-01", "2025-01-31")

    def test_normalize_data_raises(self):
        fetcher = BaiduFetcher()
        with pytest.raises(DataFetchError, match="does not support historical K-line"):
            fetcher._normalize_data(MagicMock(), "600519")


# ---------- Helpers ----------


def _mock_post_returning(payload: dict, status: int = 200):
    mock_response = MagicMock()
    mock_response.status_code = status
    mock_response.json.return_value = payload
    mock_response.text = json.dumps(payload)
    return mock_response


SAMPLE_BAIDU_RESPONSE = {
    "request_id": "ca749cb1-26db-4ff6-9735-f7b472d59003",
    "references": [
        {
            "id": 1,
            "title": "贵州茅台前三季度业绩超预期",
            "url": "https://finance.eastmoney.com/news/maotai-q3.html",
            "content": "贵州茅台发布公告,前三季度营收同比增长...",
            "date": "2026-05-20 10:30:00",
            "type": "web",
            "web_anchor": "贵州茅台前三季度业绩超预期",
        },
        {
            "id": 2,
            "title": "白酒板块整体上涨",
            "url": "https://finance.eastmoney.com/news/baijiu-up-2026.html",
            "content": "今日白酒板块迎来普涨行情...",
            "date": "2026-05-19 16:00:00",
            "type": "web",
            "web_anchor": "白酒板块整体上涨",
        },
    ],
}


# ---------- Happy path ----------


class TestSearchNewsHappyPath:
    @patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post")
    def test_returns_normalized_dicts(self, mock_post, monkeypatch):
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")
        mock_post.return_value = _mock_post_returning(SAMPLE_BAIDU_RESPONSE)

        fetcher = BaiduFetcher()
        results = fetcher.search_news(q="贵州茅台", limit=20)

        assert len(results) == 2
        first = results[0]
        assert first["title"] == "贵州茅台前三季度业绩超预期"
        assert first["url"] == "https://finance.eastmoney.com/news/maotai-q3.html"
        assert first["source_domain"] == "finance.eastmoney.com"
        assert first["publish_date"] == "2026-05-20"
        assert first["snippet"] == "贵州茅台发布公告,前三季度营收同比增长..."
        assert first["media_name"] == "finance.eastmoney.com"  # Baidu 没有 mediaName 字段

    @patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post")
    def test_uses_correct_endpoint(self, mock_post, monkeypatch):
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")
        mock_post.return_value = _mock_post_returning({"references": []})

        BaiduFetcher().search_news(q="test", limit=5)

        called_url = mock_post.call_args.args[0]
        assert called_url == "https://qianfan.baidubce.com/v2/ai_search/web_search"

    @patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post")
    def test_sends_bearer_authorization_header(self, mock_post, monkeypatch):
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/SECRET-XYZ")
        mock_post.return_value = _mock_post_returning({"references": []})

        BaiduFetcher().search_news(q="test", limit=5)

        headers = mock_post.call_args.kwargs["headers"]
        assert headers["Authorization"] == "Bearer bce-v3/SECRET-XYZ"
        assert headers["Content-Type"] == "application/json"

    @patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post")
    def test_empty_references_returns_empty_list(self, mock_post, monkeypatch):
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")
        mock_post.return_value = _mock_post_returning({"request_id": "abc", "references": []})

        results = BaiduFetcher().search_news(q="nothing-here", limit=20)
        assert results == []

    @patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post")
    def test_missing_references_key_returns_empty_list(self, mock_post, monkeypatch):
        """Upstream may omit references on success — treat as empty, not error."""
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")
        mock_post.return_value = _mock_post_returning({"request_id": "abc"})

        results = BaiduFetcher().search_news(q="test", limit=20)
        assert results == []


# ---------- Request body shape contract ----------


class TestSearchNewsRequestBody:
    @patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post")
    def test_body_has_messages_with_role_user(self, mock_post, monkeypatch):
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")
        mock_post.return_value = _mock_post_returning({"references": []})

        BaiduFetcher().search_news(q="贵州茅台", limit=20)

        body = mock_post.call_args.kwargs["json"]
        assert body["messages"] == [{"content": "贵州茅台", "role": "user"}]

    @patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post")
    def test_body_has_search_source_baidu_search_v2(self, mock_post, monkeypatch):
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")
        mock_post.return_value = _mock_post_returning({"references": []})

        BaiduFetcher().search_news(q="test", limit=10)

        body = mock_post.call_args.kwargs["json"]
        assert body["search_source"] == "baidu_search_v2"

    @patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post")
    def test_body_has_resource_type_filter_web_with_top_k(self, mock_post, monkeypatch):
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")
        mock_post.return_value = _mock_post_returning({"references": []})

        BaiduFetcher().search_news(q="test", limit=15)

        body = mock_post.call_args.kwargs["json"]
        assert body["resource_type_filter"] == [{"type": "web", "top_k": 15}]

    @patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post")
    def test_top_k_clamped_to_50_when_limit_exceeds(self, mock_post, monkeypatch):
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")
        mock_post.return_value = _mock_post_returning({"references": []})

        BaiduFetcher().search_news(q="test", limit=100)

        body = mock_post.call_args.kwargs["json"]
        assert body["resource_type_filter"] == [{"type": "web", "top_k": 50}]

    @patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post")
    def test_top_k_passes_through_when_under_50(self, mock_post, monkeypatch):
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")
        mock_post.return_value = _mock_post_returning({"references": []})

        BaiduFetcher().search_news(q="test", limit=20)

        body = mock_post.call_args.kwargs["json"]
        assert body["resource_type_filter"][0]["top_k"] == 20

    @patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post")
    def test_no_recency_filter_when_from_date_none(self, mock_post, monkeypatch):
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")
        mock_post.return_value = _mock_post_returning({"references": []})

        BaiduFetcher().search_news(q="test", limit=10)

        body = mock_post.call_args.kwargs["json"]
        assert "search_recency_filter" not in body

    @patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post")
    def test_recency_filter_week_for_recent_from_date(self, mock_post, monkeypatch):
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")
        mock_post.return_value = _mock_post_returning({"references": []})

        # from_date 3 days ago → "week"
        from datetime import date, timedelta

        recent = (date.today() - timedelta(days=3)).isoformat()
        BaiduFetcher().search_news(q="test", limit=10, from_date=recent)

        body = mock_post.call_args.kwargs["json"]
        assert body["search_recency_filter"] == "week"

    @patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post")
    def test_recency_filter_year_for_old_from_date(self, mock_post, monkeypatch):
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")
        mock_post.return_value = _mock_post_returning({"references": []})

        from datetime import date, timedelta

        old = (date.today() - timedelta(days=365)).isoformat()
        BaiduFetcher().search_news(q="test", limit=10, from_date=old)

        body = mock_post.call_args.kwargs["json"]
        assert body["search_recency_filter"] == "year"

    @patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post")
    def test_recency_filter_month_for_30_days(self, mock_post, monkeypatch):
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")
        mock_post.return_value = _mock_post_returning({"references": []})

        from datetime import date, timedelta

        thirty = (date.today() - timedelta(days=30)).isoformat()
        BaiduFetcher().search_news(q="test", limit=10, from_date=thirty)

        body = mock_post.call_args.kwargs["json"]
        assert body["search_recency_filter"] == "month"

    @patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post")
    def test_recency_filter_semiyear_for_180_days(self, mock_post, monkeypatch):
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")
        mock_post.return_value = _mock_post_returning({"references": []})

        from datetime import date, timedelta

        one_eighty = (date.today() - timedelta(days=180)).isoformat()
        BaiduFetcher().search_news(q="test", limit=10, from_date=one_eighty)

        body = mock_post.call_args.kwargs["json"]
        assert body["search_recency_filter"] == "semiyear"


# ---------- Input validation contract ----------


class TestSearchNewsValidation:
    def test_empty_q_raises(self):
        fetcher = BaiduFetcher()
        with pytest.raises(DataFetchError, match="invalid q"):
            fetcher.search_news(q="", limit=10)

    def test_q_too_long_raises(self):
        fetcher = BaiduFetcher()
        with pytest.raises(DataFetchError, match="invalid q"):
            fetcher.search_news(q="x" * 201, limit=10)

    def test_q_exactly_200_chars_ok(self, monkeypatch):
        """200 is the documented max — must be accepted (boundary)."""
        from unittest.mock import patch

        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")
        with patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post") as mock_post:
            mock_post.return_value = _mock_post_returning({"references": []})
            fetcher = BaiduFetcher()
            # Should NOT raise
            fetcher.search_news(q="x" * 200, limit=10)

    def test_limit_zero_raises(self):
        fetcher = BaiduFetcher()
        with pytest.raises(DataFetchError, match="limit must be 1..100"):
            fetcher.search_news(q="ok", limit=0)

    def test_limit_too_large_raises(self):
        fetcher = BaiduFetcher()
        with pytest.raises(DataFetchError, match="limit must be 1..100"):
            fetcher.search_news(q="ok", limit=101)

    def test_limit_negative_raises(self):
        fetcher = BaiduFetcher()
        with pytest.raises(DataFetchError, match="limit must be 1..100"):
            fetcher.search_news(q="ok", limit=-1)

    def test_limit_as_string_coerced(self, monkeypatch):
        """Explorer mini-form sends HTML input values as strings."""
        from unittest.mock import patch

        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")
        with patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post") as mock_post:
            mock_post.return_value = _mock_post_returning({"references": []})
            fetcher = BaiduFetcher()
            results = fetcher.search_news(q="ok", limit="20")
            assert results == []
            body = mock_post.call_args.kwargs["json"]
            assert body["resource_type_filter"][0]["top_k"] == 20

    def test_limit_non_numeric_string_raises(self):
        fetcher = BaiduFetcher()
        with pytest.raises(DataFetchError, match="limit must be an integer"):
            fetcher.search_news(q="ok", limit="abc")

    def test_limit_none_raises(self):
        fetcher = BaiduFetcher()
        with pytest.raises(DataFetchError, match="limit must be an integer"):
            fetcher.search_news(q="ok", limit=None)


# ---------- Error handling contract ----------


class TestSearchNewsErrors:
    @patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post")
    def test_http_500_raises(self, mock_post, monkeypatch):
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")
        mock_post.return_value = _mock_post_returning({}, status=500)
        with pytest.raises(DataFetchError, match="HTTP 500"):
            BaiduFetcher().search_news(q="ok", limit=10)

    @patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post")
    def test_http_401_unauthorized_raises(self, mock_post, monkeypatch):
        """Bad API key surfaces as DataFetchError so manager tries next fetcher."""
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/INVALID")
        mock_post.return_value = _mock_post_returning({"error": "invalid token"}, status=401)
        with pytest.raises(DataFetchError, match="HTTP 401"):
            BaiduFetcher().search_news(q="ok", limit=10)

    @patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post")
    def test_http_429_rate_limited_raises(self, mock_post, monkeypatch):
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")
        mock_post.return_value = _mock_post_returning({}, status=429)
        with pytest.raises(DataFetchError, match="HTTP 429"):
            BaiduFetcher().search_news(q="ok", limit=10)

    @patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post")
    def test_bad_json_raises(self, mock_post, monkeypatch):
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = ValueError("not json")
        mock_response.text = "not json"
        mock_post.return_value = mock_response
        with pytest.raises(DataFetchError, match="bad JSON"):
            BaiduFetcher().search_news(q="ok", limit=10)

    @patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post")
    def test_baidu_api_code_nonzero_raises(self, mock_post, monkeypatch):
        """Baidu's error envelope: {"code": 401, "message": "..."}."""
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")
        payload = {"code": 401, "message": "invalid api key", "request_id": "abc"}
        mock_post.return_value = _mock_post_returning(payload, status=200)
        with pytest.raises(DataFetchError, match="code=401"):
            BaiduFetcher().search_news(q="ok", limit=10)

    @patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post")
    def test_baidu_api_code_zero_string_ok(self, mock_post, monkeypatch):
        """Some Baidu variants return code as string "0" — treat as success."""
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")
        payload = {"code": "0", "references": [], "request_id": "abc"}
        mock_post.return_value = _mock_post_returning(payload, status=200)
        results = BaiduFetcher().search_news(q="ok", limit=10)
        assert results == []

    @patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post")
    def test_network_error_raises(self, mock_post, monkeypatch):
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")
        mock_post.side_effect = requests.ConnectionError("dns fail")
        with pytest.raises(DataFetchError, match="network error"):
            BaiduFetcher().search_news(q="ok", limit=10)

    @patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post")
    def test_records_missing_critical_fields_skipped(self, mock_post, monkeypatch):
        """3 records: complete, missing url, missing date, missing title."""
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")
        payload = {
            "references": [
                {
                    "title": "valid",
                    "url": "https://finance.eastmoney.com/1.html",
                    "content": "snippet",
                    "date": "2026-05-20 10:00:00",
                },
                {
                    "title": "missing url",
                    "content": "snippet",
                    "date": "2026-05-20 10:00:00",
                },
                {
                    "title": "missing date",
                    "url": "https://finance.eastmoney.com/3.html",
                    "content": "snippet",
                },
                {
                    "url": "https://finance.eastmoney.com/4.html",
                    "content": "snippet",
                    "date": "2026-05-20 10:00:00",
                    # missing title
                },
            ]
        }
        mock_post.return_value = _mock_post_returning(payload)

        results = BaiduFetcher().search_news(q="ok", limit=10)
        assert len(results) == 1
        assert results[0]["title"] == "valid"


# ---------- Date post-filter contract ----------


class TestSearchNewsDateFilter:
    @patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post")
    def test_from_date_filters_out_older_records(self, mock_post, monkeypatch):
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")
        payload = {
            "references": [
                {
                    "title": "new",
                    "url": "https://finance.eastmoney.com/a/1.html",
                    "content": "snippet",
                    "date": "2026-06-09 10:00:00",
                },
                {
                    "title": "old",
                    "url": "https://finance.eastmoney.com/a/2.html",
                    "content": "snippet",
                    "date": "2026-04-29 10:00:00",
                },
            ]
        }
        mock_post.return_value = _mock_post_returning(payload)

        results = BaiduFetcher().search_news(q="ok", limit=10, from_date="2026-05-01")
        assert len(results) == 1
        assert results[0]["title"] == "new"

    @patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post")
    def test_to_date_filters_out_newer_records(self, mock_post, monkeypatch):
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")
        payload = {
            "references": [
                {
                    "title": "new",
                    "url": "https://finance.eastmoney.com/a/1.html",
                    "content": "snippet",
                    "date": "2026-06-09 10:00:00",
                },
                {
                    "title": "old",
                    "url": "https://finance.eastmoney.com/a/2.html",
                    "content": "snippet",
                    "date": "2026-04-29 10:00:00",
                },
            ]
        }
        mock_post.return_value = _mock_post_returning(payload)

        results = BaiduFetcher().search_news(q="ok", limit=10, to_date="2026-05-01")
        assert len(results) == 1
        assert results[0]["title"] == "old"

    @patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post")
    def test_from_and_to_date_range(self, mock_post, monkeypatch):
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")
        payload = {
            "references": [
                {
                    "title": "in_range",
                    "url": "https://finance.eastmoney.com/a/1.html",
                    "content": "snippet",
                    "date": "2026-05-20 10:00:00",
                },
                {
                    "title": "before",
                    "url": "https://finance.eastmoney.com/a/2.html",
                    "content": "snippet",
                    "date": "2026-04-29 10:00:00",
                },
                {
                    "title": "after",
                    "url": "https://finance.eastmoney.com/a/3.html",
                    "content": "snippet",
                    "date": "2026-06-09 10:00:00",
                },
            ]
        }
        mock_post.return_value = _mock_post_returning(payload)

        results = BaiduFetcher().search_news(
            q="ok", limit=10, from_date="2026-05-01", to_date="2026-05-31"
        )
        assert len(results) == 1
        assert results[0]["title"] == "in_range"

    @patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post")
    def test_no_date_filter_returns_all(self, mock_post, monkeypatch):
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")
        mock_post.return_value = _mock_post_returning(SAMPLE_BAIDU_RESPONSE)
        results = BaiduFetcher().search_news(q="ok", limit=10)
        assert len(results) == 2


# ---------- Domain whitelist contract ----------


class TestSearchNewsDomainFilter:
    """Default whitelist + `search_domain_filter` upstream body field."""

    @patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post")
    def test_default_domains_sent_in_body(self, mock_post, monkeypatch):
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")
        monkeypatch.delenv("BAIDU_NEWS_DOMAINS", raising=False)
        mock_post.return_value = _mock_post_returning({"references": []})

        BaiduFetcher().search_news(q="test", limit=10)

        body = mock_post.call_args.kwargs["json"]
        # Baidu's official whitelist lives under search_filter.match.site
        # (NOT search_domain_filter — that field doesn't exist on this endpoint).
        # See https://cloud.baidu.com/doc/qianfan-api/s/Wmbq4z7e5
        assert body["search_filter"] == {"match": {"site": list(DEFAULT_NEWS_DOMAINS)}}
        sites = body["search_filter"]["match"]["site"]
        # The default whitelist is the canonical news subdomain of each
        # of the 3 authoritative Chinese financial-news sources:
        #   东方财富: finance.eastmoney.com
        #   财联社:   www.cls.cn  (CLS has no dedicated news subdomain;
        #                         www. is the only web-front-end host)
        #   同花顺:   news.10jqka.com.cn
        # Each entry is the specific subdomain (not the parent domain),
        # so non-news entry points (guba / quote / fund / m-cls / etc.)
        # are excluded by construction.
        assert set(sites) == {
            "finance.eastmoney.com",
            "www.cls.cn",
            "news.10jqka.com.cn",
        }
        assert len(sites) == 3

    @patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post")
    def test_env_var_overrides_default(self, mock_post, monkeypatch):
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")
        monkeypatch.setenv("BAIDU_NEWS_DOMAINS", "foo.com,bar.cn")
        mock_post.return_value = _mock_post_returning({"references": []})

        BaiduFetcher().search_news(q="test", limit=10)

        body = mock_post.call_args.kwargs["json"]
        assert body["search_filter"] == {"match": {"site": ["foo.com", "bar.cn"]}}

    @patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post")
    def test_empty_env_var_disables_filter(self, mock_post, monkeypatch):
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")
        monkeypatch.setenv("BAIDU_NEWS_DOMAINS", "")
        mock_post.return_value = _mock_post_returning({"references": []})

        BaiduFetcher().search_news(q="test", limit=10)

        body = mock_post.call_args.kwargs["json"]
        assert "search_filter" not in body

    @patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post")
    def test_whitespace_only_env_var_disables_filter(self, mock_post, monkeypatch):
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")
        monkeypatch.setenv("BAIDU_NEWS_DOMAINS", "   ,  ,")
        mock_post.return_value = _mock_post_returning({"references": []})

        BaiduFetcher().search_news(q="test", limit=10)

        body = mock_post.call_args.kwargs["json"]
        assert "search_filter" not in body

    @patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post")
    def test_client_side_drops_record_outside_whitelist(self, mock_post, monkeypatch):
        """Defense in depth: even if upstream returns an out-of-whitelist record,
        we drop it before returning to the caller."""
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")
        monkeypatch.delenv("BAIDU_NEWS_DOMAINS", raising=False)
        payload = {
            "references": [
                {
                    "title": "from eastmoney (allowed)",
                    "url": "https://finance.eastmoney.com/a/1.html",
                    "content": "x",
                    "date": "2026-05-20 10:00:00",
                },
                {
                    "title": "from sina (blocked)",
                    "url": "https://finance.sina.com.cn/2026/x.html",
                    "content": "x",
                    "date": "2026-05-20 10:00:00",
                },
            ]
        }
        mock_post.return_value = _mock_post_returning(payload)

        results = BaiduFetcher().search_news(q="test", limit=10)

        assert len(results) == 1
        assert results[0]["title"] == "from eastmoney (allowed)"

    @patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post")
    def test_subdomain_matches_parent_domain(self, mock_post, monkeypatch):
        """All 3 whitelisted subdomains (and any deeper subdomains of each)
        match the default whitelist."""
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")
        monkeypatch.delenv("BAIDU_NEWS_DOMAINS", raising=False)
        payload = {
            "references": [
                {
                    "title": "em-finance",
                    "url": "https://finance.eastmoney.com/a.html",
                    "content": "x",
                    "date": "2026-05-20 10:00:00",
                },
                {
                    "title": "em-news-finance",
                    "url": "https://news.finance.eastmoney.com/x.html",
                    "content": "x",
                    "date": "2026-05-20 10:00:00",
                },
                {
                    "title": "cls-www",
                    "url": "https://www.cls.cn/y.html",
                    "content": "x",
                    "date": "2026-05-20 10:00:00",
                },
                {
                    "title": "ths-news",
                    "url": "https://news.10jqka.com.cn/z.html",
                    "content": "x",
                    "date": "2026-05-20 10:00:00",
                },
            ]
        }
        mock_post.return_value = _mock_post_returning(payload)

        results = BaiduFetcher().search_news(q="test", limit=10)

        assert len(results) == 4

    @patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post")
    def test_similar_but_different_domain_blocked(self, mock_post, monkeypatch):
        """badeastmoney.com must NOT match the eastmoney.com whitelist entry."""
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")
        monkeypatch.delenv("BAIDU_NEWS_DOMAINS", raising=False)
        payload = {
            "references": [
                {
                    "title": "evil",
                    "url": "https://news.badeastmoney.com/phishing.html",
                    "content": "x",
                    "date": "2026-05-20 10:00:00",
                },
            ]
        }
        mock_post.return_value = _mock_post_returning(payload)

        results = BaiduFetcher().search_news(q="test", limit=10)
        assert results == []


# ---------- Default 3-source canonical-subdomain scope (record-level) ----------


class TestSearchNewsDefaultScope:
    """The default whitelist is the 3 canonical news subdomains of
    东方财富 / 财联社 / 同花顺:
      - finance.eastmoney.com
      - www.cls.cn
      - news.10jqka.com.cn
    These tests verify the client-side post-filter keeps the 3 whitelisted
    subdomains and drops sibling subdomains (guba, stock, fund, m-cls, ...)
    even if upstream leaks through.
    """

    @patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post")
    def test_keeps_all_three_canonical_subdomains_by_default(self, mock_post, monkeypatch):
        """One record per canonical subdomain — all 3 must pass the
        default whitelist filter."""
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")
        monkeypatch.delenv("BAIDU_NEWS_DOMAINS", raising=False)
        payload = {
            "references": [
                {
                    "title": "em",
                    "url": "https://finance.eastmoney.com/a/1.html",
                    "content": "x",
                    "date": "2026-05-20 10:00:00",
                },
                {
                    "title": "cls",
                    "url": "https://www.cls.cn/detail/1234",
                    "content": "x",
                    "date": "2026-05-20 10:00:00",
                },
                {
                    "title": "ths",
                    "url": "https://news.10jqka.com.cn/20260622/c123.shtml",
                    "content": "x",
                    "date": "2026-05-20 10:00:00",
                },
            ]
        }
        mock_post.return_value = _mock_post_returning(payload)

        results = BaiduFetcher().search_news(q="test", limit=10)
        assert len(results) == 3
        titles = {r["title"] for r in results}
        assert titles == {"em", "cls", "ths"}

    @patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post")
    def test_drops_other_eastmoney_subdomains_by_default(self, mock_post, monkeypatch):
        """stock., guba., quote., emwap., fund., data. are NOT in the default
        whitelist — only finance.eastmoney.com is. These sibling subdomains
        are non-news entry points (forum / quote / fund) that the specific
        subdomain deliberately excludes."""
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")
        monkeypatch.delenv("BAIDU_NEWS_DOMAINS", raising=False)
        payload = {
            "references": [
                {
                    "title": "stock subdomain",
                    "url": "https://stock.eastmoney.com/a.html",
                    "content": "x",
                    "date": "2026-05-20 10:00:00",
                },
                {
                    "title": "guba subdomain",
                    "url": "https://guba.eastmoney.com/list.html",
                    "content": "x",
                    "date": "2026-05-20 10:00:00",
                },
                {
                    "title": "quote subdomain",
                    "url": "https://quote.eastmoney.com/sh600519.html",
                    "content": "x",
                    "date": "2026-05-20 10:00:00",
                },
                {
                    "title": "finance subdomain (kept)",
                    "url": "https://finance.eastmoney.com/a/ok.html",
                    "content": "x",
                    "date": "2026-05-20 10:00:00",
                },
            ]
        }
        mock_post.return_value = _mock_post_returning(payload)

        results = BaiduFetcher().search_news(q="test", limit=10)
        assert len(results) == 1
        assert results[0]["title"] == "finance subdomain (kept)"

    @patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post")
    def test_drops_other_cls_subdomains_by_default(self, mock_post, monkeypatch):
        """wwwjs., cdnjs., api3., image. are CLS siblings of www. — not
        whitelisted by default. www. is the canonical news subdomain;
        the others host static assets / API / images with no article body."""
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")
        monkeypatch.delenv("BAIDU_NEWS_DOMAINS", raising=False)
        payload = {
            "references": [
                {
                    "title": "wwwjs (static)",
                    "url": "https://wwwjs.cls.cn/bundle.js",
                    "content": "x",
                    "date": "2026-05-20 10:00:00",
                },
                {
                    "title": "cdnjs (static)",
                    "url": "https://cdnjs.cls.cn/lib.js",
                    "content": "x",
                    "date": "2026-05-20 10:00:00",
                },
                {
                    "title": "www (kept)",
                    "url": "https://www.cls.cn/detail/1",
                    "content": "x",
                    "date": "2026-05-20 10:00:00",
                },
            ]
        }
        mock_post.return_value = _mock_post_returning(payload)

        results = BaiduFetcher().search_news(q="test", limit=10)
        assert len(results) == 1
        assert results[0]["title"] == "www (kept)"

    @patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post")
    def test_drops_other_10jqka_subdomains_by_default(self, mock_post, monkeypatch):
        """stock. is just HK/US-stock nav, fund./goodsfu. are non-news
        finance verticals — only news. is whitelisted by default."""
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")
        monkeypatch.delenv("BAIDU_NEWS_DOMAINS", raising=False)
        payload = {
            "references": [
                {
                    "title": "stock (nav hub, not news)",
                    "url": "https://stock.10jqka.com.cn/hks/",
                    "content": "x",
                    "date": "2026-05-20 10:00:00",
                },
                {
                    "title": "fund",
                    "url": "https://fund.10jqka.com.cn/",
                    "content": "x",
                    "date": "2026-05-20 10:00:00",
                },
                {
                    "title": "news (kept)",
                    "url": "https://news.10jqka.com.cn/20260622/c1.shtml",
                    "content": "x",
                    "date": "2026-05-20 10:00:00",
                },
            ]
        }
        mock_post.return_value = _mock_post_returning(payload)

        results = BaiduFetcher().search_news(q="test", limit=10)
        assert len(results) == 1
        assert results[0]["title"] == "news (kept)"

    @patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post")
    def test_keeps_deeper_subdomains_of_each_canonical(self, mock_post, monkeypatch):
        """Any deeper subdomain of the 3 canonical subdomains must pass
        through (e.g. news.finance.eastmoney.com, deeper www.cls.cn,
        deeper news.10jqka.com.cn)."""
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")
        monkeypatch.delenv("BAIDU_NEWS_DOMAINS", raising=False)
        payload = {
            "references": [
                {
                    "title": "news.finance",
                    "url": "https://news.finance.eastmoney.com/a/1.html",
                    "content": "x",
                    "date": "2026-05-20 10:00:00",
                },
                {
                    "title": "www.cls root",
                    "url": "https://www.cls.cn/a/2.html",
                    "content": "x",
                    "date": "2026-05-20 10:00:00",
                },
                {
                    "title": "news.ths root",
                    "url": "https://news.10jqka.com.cn/b/3.html",
                    "content": "x",
                    "date": "2026-05-20 10:00:00",
                },
            ]
        }
        mock_post.return_value = _mock_post_returning(payload)

        results = BaiduFetcher().search_news(q="test", limit=10)
        assert len(results) == 3

    @patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post")
    def test_env_var_can_restore_parent_domain_scope(self, mock_post, monkeypatch):
        """Setting BAIDU_NEWS_DOMAINS to the parent-domain style list
        (e.g. `eastmoney.com,cls.cn,10jqka.com.cn`) widens the scope to
        admit all subdomains — this is the env-var escape hatch for users
        who want the older behavior. The new default is the specific
        canonical subdomains; the env-var override brings back the
        broader scope for testing or special use cases.

        `guba.eastmoney.com` is in DEFAULT_BLOCKED_DOMAINS, so the denylist
        still drops it even when the parent-domain scope admits it — this
        verifies the three-layer filtering (whitelist → denylist) works as
        designed under the env-var override.
        """
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")
        monkeypatch.setenv("BAIDU_NEWS_DOMAINS", "eastmoney.com,cls.cn,10jqka.com.cn")
        payload = {
            "references": [
                {
                    "title": "guba (admitted by parent scope, dropped by denylist)",
                    "url": "https://guba.eastmoney.com/list.html",
                    "content": "x",
                    "date": "2026-05-20 10:00:00",
                },
                {
                    "title": "quote (admitted by parent scope, dropped by denylist)",
                    "url": "https://quote.eastmoney.com/sh600519.html",
                    "content": "x",
                    "date": "2026-05-20 10:00:00",
                },
            ]
        }
        mock_post.return_value = _mock_post_returning(payload)

        results = BaiduFetcher().search_news(q="test", limit=10)
        assert results == []


# ---------- Helper-function unit tests ----------


class TestDomainHelpers:
    def test_load_news_domains_default_when_unset(self, monkeypatch):
        monkeypatch.delenv("BAIDU_NEWS_DOMAINS", raising=False)
        assert _load_news_domains() == DEFAULT_NEWS_DOMAINS

    def test_load_news_domains_parses_csv(self, monkeypatch):
        monkeypatch.setenv("BAIDU_NEWS_DOMAINS", " a.com , b.cn,c.com ")
        assert _load_news_domains() == ("a.com", "b.cn", "c.com")

    def test_load_news_domains_empty_string_disables(self, monkeypatch):
        monkeypatch.setenv("BAIDU_NEWS_DOMAINS", "")
        assert _load_news_domains() == ()

    def test_load_news_domains_whitespace_only_disables(self, monkeypatch):
        monkeypatch.setenv("BAIDU_NEWS_DOMAINS", "   ,  ")
        assert _load_news_domains() == ()

    @pytest.mark.parametrize(
        "host,want",
        [
            # --- 东方财富: finance.eastmoney.com (and any deeper subdomain) ---
            ("finance.eastmoney.com", True),
            ("news.finance.eastmoney.com", True),
            # Sibling eastmoney.com subdomains (guba / stock / quote / fund /
            # data) are NOT whitelisted — they are non-news entry points.
            ("stock.eastmoney.com", False),
            ("guba.eastmoney.com", False),
            ("eastmoney.com", False),
            # --- 财联社: www.cls.cn (and any deeper subdomain) ---
            ("www.cls.cn", True),
            # Sibling cls.cn subdomains host static / API / images, not articles.
            ("m.cls.cn", False),
            ("wwwjs.cls.cn", False),
            ("cls.cn", False),
            # --- 同花顺: news.10jqka.com.cn (and any deeper subdomain) ---
            ("news.10jqka.com.cn", True),
            # Sibling 10jqka.com.cn subdomains are non-news verticals.
            ("stock.10jqka.com.cn", False),
            ("fund.10jqka.com.cn", False),
            ("10jqka.com.cn", False),
            # --- Unrelated sources always blocked ---
            ("example.com", False),
            ("finance.sina.com.cn", False),
            ("finance.eastmoney.com.evil.cn", False),  # suffix match, not substring
            ("", False),
        ],
    )
    def test_domain_matches(self, host, want):
        assert _domain_matches(host, DEFAULT_NEWS_DOMAINS) is want

    def test_domain_matches_case_insensitive(self):
        assert _domain_matches("Finance.EASTMONEY.com", DEFAULT_NEWS_DOMAINS) is True

    def test_domain_matches_trailing_dot(self):
        """Hosts may end in '.' (FQDN form); strip it before comparing."""
        assert _domain_matches("finance.eastmoney.com.", DEFAULT_NEWS_DOMAINS) is True

    def test_default_whitelist_targets_canonical_news_subdomains(self):
        """Guard against accidental removal of any of the 3 default sources.

        The default whitelist is the canonical news subdomain of each of
        the 3 authoritative Chinese financial-news sources. Each entry is
        the SPECIFIC subdomain (not the parent domain) — using the parent
        domain would pull in non-news entry points (guba / quote / fund /
        m-cls / etc.).
        """
        assert DEFAULT_NEWS_DOMAINS == (
            "finance.eastmoney.com",
            "www.cls.cn",
            "news.10jqka.com.cn",
        )

    def test_module_exports_whitelist_constant(self):
        """Public surface: callers can introspect the default whitelist."""
        assert hasattr(baidu_fetcher, "DEFAULT_NEWS_DOMAINS")
        assert len(baidu_fetcher.DEFAULT_NEWS_DOMAINS) == 3


# ---------- Mobile-host denylist contract ----------


class TestSearchNewsMobileFilter:
    """Desktop-only: records served from `m.` / `wap.` / `mobile.` / `mb.` subdomains
    are dropped by the client-side post-filter, even when their parent domain
    is in the whitelist.

    These tests cover the mobile-prefix safety net, which is meaningful only
    when the whitelist admits the parent domain. The default whitelist is
    the 3 specific canonical subdomains (finance.eastmoney.com / www.cls.cn /
    news.10jqka.com.cn), none of which are mobile-style, so we override
    the whitelist to the parent-domain style via env var to exercise the
    mobile filter against a representative spread of records.
    """

    @patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post")
    def test_drops_m_subdomain(self, mock_post, monkeypatch):
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")
        monkeypatch.setenv(
            "BAIDU_NEWS_DOMAINS", "eastmoney.com,cls.cn,10jqka.com.cn"
        )
        monkeypatch.delenv("BAIDU_NEWS_MOBILE_PREFIXES", raising=False)
        payload = {
            "references": [
                {
                    "title": "m.cls.cn — mobile",
                    "url": "https://m.cls.cn/a/1.html",
                    "content": "x",
                    "date": "2026-05-20 10:00:00",
                },
                {
                    "title": "www.cls.cn — desktop",
                    "url": "https://www.cls.cn/a/2.html",
                    "content": "x",
                    "date": "2026-05-20 10:00:00",
                },
            ]
        }
        mock_post.return_value = _mock_post_returning(payload)

        results = BaiduFetcher().search_news(q="test", limit=10)
        assert len(results) == 1
        assert results[0]["title"] == "www.cls.cn — desktop"

    @patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post")
    def test_drops_wap_subdomain(self, mock_post, monkeypatch):
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")
        monkeypatch.delenv("BAIDU_NEWS_MOBILE_PREFIXES", raising=False)
        payload = {
            "references": [
                {
                    "title": "wap.eastmoney.com — mobile",
                    "url": "https://wap.eastmoney.com/a/1.html",
                    "content": "x",
                    "date": "2026-05-20 10:00:00",
                },
                {
                    "title": "finance.eastmoney.com — desktop",
                    "url": "https://finance.eastmoney.com/a/2.html",
                    "content": "x",
                    "date": "2026-05-20 10:00:00",
                },
            ]
        }
        mock_post.return_value = _mock_post_returning(payload)

        results = BaiduFetcher().search_news(q="test", limit=10)
        assert len(results) == 1
        assert results[0]["title"] == "finance.eastmoney.com — desktop"

    @patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post")
    def test_drops_mobile_and_mb_subdomains(self, mock_post, monkeypatch):
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")
        monkeypatch.setenv(
            "BAIDU_NEWS_DOMAINS", "eastmoney.com,cls.cn,10jqka.com.cn"
        )
        monkeypatch.delenv("BAIDU_NEWS_MOBILE_PREFIXES", raising=False)
        payload = {
            "references": [
                {
                    "title": "mobile.10jqka.com.cn",
                    "url": "https://mobile.10jqka.com.cn/a.html",
                    "content": "x",
                    "date": "2026-05-20 10:00:00",
                },
                {
                    "title": "mb.10jqka.com.cn",
                    "url": "https://mb.10jqka.com.cn/b.html",
                    "content": "x",
                    "date": "2026-05-20 10:00:00",
                },
                {
                    "title": "stock.10jqka.com.cn — desktop",
                    "url": "https://stock.10jqka.com.cn/c.html",
                    "content": "x",
                    "date": "2026-05-20 10:00:00",
                },
            ]
        }
        mock_post.return_value = _mock_post_returning(payload)

        results = BaiduFetcher().search_news(q="test", limit=10)
        assert len(results) == 1
        assert results[0]["title"] == "stock.10jqka.com.cn — desktop"

    @patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post")
    def test_keeps_desktop_subdomains(self, mock_post, monkeypatch):
        """finance., stock., emweb., so. — all desktop subdomains of the
        whitelisted sources that are NOT on the denylist, must pass through.

        Note: with the new default whitelist (`finance.eastmoney.com` only),
        only the first record would survive. This test exercises the
        mobile-filter behavior under the legacy 3-source whitelist via
        env var, where all 4 desktop subdomains should pass."""
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")
        monkeypatch.setenv(
            "BAIDU_NEWS_DOMAINS", "eastmoney.com,cls.cn,10jqka.com.cn"
        )
        monkeypatch.delenv("BAIDU_NEWS_MOBILE_PREFIXES", raising=False)
        payload = {
            "references": [
                {
                    "title": "finance",
                    "url": "https://finance.eastmoney.com/a.html",
                    "content": "x",
                    "date": "2026-05-20 10:00:00",
                },
                {
                    "title": "stock",
                    "url": "https://stock.eastmoney.com/b.html",
                    "content": "x",
                    "date": "2026-05-20 10:00:00",
                },
                {
                    "title": "emweb",
                    "url": "https://emweb.securities.eastmoney.com/c.html",
                    "content": "x",
                    "date": "2026-05-20 10:00:00",
                },
                {
                    "title": "news",
                    "url": "https://news.10jqka.com.cn/d.html",
                    "content": "x",
                    "date": "2026-05-20 10:00:00",
                },
            ]
        }
        mock_post.return_value = _mock_post_returning(payload)

        results = BaiduFetcher().search_news(q="test", limit=10)
        assert len(results) == 4

    @patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post")
    def test_env_var_disables_mobile_filter(self, mock_post, monkeypatch):
        """Setting `BAIDU_NEWS_MOBILE_PREFIXES=""` allows mobile-style URLs through
        (provided they aren't on the explicit denylist — here we disable BOTH
        the block list and the mobile prefix list to isolate the prefix-check
        behavior, since every mobile subdomain of the 3 whitelisted sources
        is in the default block list).

        We override the whitelist to admit `m.eastmoney.com`'s parent domain
        — under the new default whitelist (`finance.eastmoney.com` only),
        `m.eastmoney.com` would never reach the mobile filter."""
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")
        monkeypatch.setenv(
            "BAIDU_NEWS_DOMAINS", "eastmoney.com,cls.cn,10jqka.com.cn"
        )
        monkeypatch.setenv("BAIDU_NEWS_MOBILE_PREFIXES", "")
        monkeypatch.setenv("BAIDU_NEWS_BLOCKED_DOMAINS", "")
        # Use a whitelisted mobile-style host: it would be caught by the
        # mobile-prefix filter unless the env var disables it.
        payload = {
            "references": [
                {
                    "title": "mobile allowed",
                    "url": "https://m.eastmoney.com/a/1.html",
                    "content": "x",
                    "date": "2026-05-20 10:00:00",
                },
            ]
        }
        mock_post.return_value = _mock_post_returning(payload)

        results = BaiduFetcher().search_news(q="test", limit=10)
        assert len(results) == 1

    @patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post")
    def test_env_var_can_extend_denylist(self, mock_post, monkeypatch):
        """Custom prefix list: drop `mini.` too. Override the whitelist to
        include cls.cn so `www.cls.cn` and `mini.cls.cn` are both in scope
        for the mobile filter to act on."""
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")
        monkeypatch.setenv(
            "BAIDU_NEWS_DOMAINS", "eastmoney.com,cls.cn,10jqka.com.cn"
        )
        monkeypatch.setenv("BAIDU_NEWS_MOBILE_PREFIXES", "m.,wap.,mobile.,mb.,mini.")
        payload = {
            "references": [
                {
                    "title": "mini.cls.cn",
                    "url": "https://mini.cls.cn/a.html",
                    "content": "x",
                    "date": "2026-05-20 10:00:00",
                },
                {
                    "title": "www.cls.cn",
                    "url": "https://www.cls.cn/b.html",
                    "content": "x",
                    "date": "2026-05-20 10:00:00",
                },
            ]
        }
        mock_post.return_value = _mock_post_returning(payload)

        results = BaiduFetcher().search_news(q="test", limit=10)
        assert len(results) == 1
        assert results[0]["title"] == "www.cls.cn"

    @patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post")
    def test_mobile_filter_runs_after_whitelist(self, mock_post, monkeypatch):
        """Out-of-whitelist-and-mobile records are dropped by the whitelist
        first (defense in depth); no need for the mobile filter to fire."""
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")
        monkeypatch.delenv("BAIDU_NEWS_MOBILE_PREFIXES", raising=False)
        payload = {
            "references": [
                {
                    "title": "mobile sina — not whitelisted anyway",
                    "url": "https://m.sina.cn/a.html",
                    "content": "x",
                    "date": "2026-05-20 10:00:00",
                },
            ]
        }
        mock_post.return_value = _mock_post_returning(payload)

        results = BaiduFetcher().search_news(q="test", limit=10)
        assert results == []


# ---------- Explicit denylist (`block_websites`) contract ----------


class TestSearchNewsBlockWebsites:
    """Default denylist + `block_websites` upstream body field.

    The default denylist excludes sub-par eastmoney.com entry points
    (emwap/quote/guba) and all known mobile subdomains of the 3
    whitelisted sources. The list is sent upstream via `block_websites`
    AND mirrored client-side as a safety net.
    """

    @patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post")
    def test_default_block_list_sent_in_body(self, mock_post, monkeypatch):
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")
        monkeypatch.delenv("BAIDU_NEWS_BLOCKED_DOMAINS", raising=False)
        mock_post.return_value = _mock_post_returning({"references": []})

        BaiduFetcher().search_news(q="test", limit=10)

        body = mock_post.call_args.kwargs["json"]
        # `block_websites` is Baidu's official denylist mechanism (exact hosts).
        assert body["block_websites"] == list(DEFAULT_BLOCKED_DOMAINS)
        # Sanity-check the eastmoney sub-par entry points are present:
        assert "emwap.eastmoney.com" in body["block_websites"]
        assert "emdatah5.eastmoney.com" in body["block_websites"]
        assert "quote.eastmoney.com" in body["block_websites"]
        assert "guba.eastmoney.com" in body["block_websites"]
        assert "mguba.eastmoney.com" in body["block_websites"]
        assert "fund.eastmoney.com" in body["block_websites"]
        assert "data.eastmoney.com" in body["block_websites"]
        # And the mobile subdomains for each whitelisted source:
        for host in (
            "m.eastmoney.com",
            "wap.eastmoney.com",
            "mobile.eastmoney.com",
            "mb.eastmoney.com",
            "m.cls.cn",
            "wap.cls.cn",
            "mobile.cls.cn",
            "mb.cls.cn",
            "m.10jqka.com.cn",
            "wap.10jqka.com.cn",
            "mobile.10jqka.com.cn",
            "mb.10jqka.com.cn",
        ):
            assert host in body["block_websites"], f"missing {host} from block_websites"

    @patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post")
    def test_block_websites_omitted_when_empty(self, mock_post, monkeypatch):
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")
        monkeypatch.setenv("BAIDU_NEWS_BLOCKED_DOMAINS", "")
        mock_post.return_value = _mock_post_returning({"references": []})

        BaiduFetcher().search_news(q="test", limit=10)

        body = mock_post.call_args.kwargs["json"]
        assert "block_websites" not in body

    @patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post")
    def test_env_var_overrides_default(self, mock_post, monkeypatch):
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")
        monkeypatch.setenv("BAIDU_NEWS_BLOCKED_DOMAINS", "evil.com,spam.cn")
        mock_post.return_value = _mock_post_returning({"references": []})

        BaiduFetcher().search_news(q="test", limit=10)

        body = mock_post.call_args.kwargs["json"]
        assert body["block_websites"] == ["evil.com", "spam.cn"]

    @patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post")
    def test_client_side_drops_emwap(self, mock_post, monkeypatch):
        """emwap.eastmoney.com is in the default denylist (sub-par entry point)."""
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")
        monkeypatch.delenv("BAIDU_NEWS_BLOCKED_DOMAINS", raising=False)
        payload = {
            "references": [
                {
                    "title": "emwap",
                    "url": "https://emwap.eastmoney.com/a/1.html",
                    "content": "x",
                    "date": "2026-05-20 10:00:00",
                },
                {
                    "title": "finance",
                    "url": "https://finance.eastmoney.com/a/2.html",
                    "content": "x",
                    "date": "2026-05-20 10:00:00",
                },
            ]
        }
        mock_post.return_value = _mock_post_returning(payload)

        results = BaiduFetcher().search_news(q="test", limit=10)
        assert len(results) == 1
        assert results[0]["title"] == "finance"

    @patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post")
    def test_client_side_drops_quote(self, mock_post, monkeypatch):
        """quote.eastmoney.com is in the default denylist (quote pages, no body)."""
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")
        monkeypatch.delenv("BAIDU_NEWS_BLOCKED_DOMAINS", raising=False)
        payload = {
            "references": [
                {
                    "title": "quote page",
                    "url": "https://quote.eastmoney.com/sh600519.html",
                    "content": "x",
                    "date": "2026-05-20 10:00:00",
                },
            ]
        }
        mock_post.return_value = _mock_post_returning(payload)

        results = BaiduFetcher().search_news(q="test", limit=10)
        assert results == []


