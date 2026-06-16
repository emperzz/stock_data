"""Unit tests for BaiduFetcher.search_news() and gating."""
import json
from unittest.mock import MagicMock, patch

import pytest

from stock_data.data_provider.base import DataFetchError
from stock_data.data_provider.fetchers.baidu_fetcher import BaiduFetcher

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
            "url": "https://www.example.com/news/maotai-q3.html",
            "content": "贵州茅台发布公告,前三季度营收同比增长...",
            "date": "2026-05-20 10:30:00",
            "type": "web",
            "web_anchor": "贵州茅台前三季度业绩超预期",
        },
        {
            "id": 2,
            "title": "白酒板块整体上涨",
            "url": "https://finance.sina.com.cn/2026/baijiu.html",
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
        assert first["url"] == "https://www.example.com/news/maotai-q3.html"
        assert first["source_domain"] == "www.example.com"
        assert first["publish_date"] == "2026-05-20"
        assert first["snippet"] == "贵州茅台发布公告,前三季度营收同比增长..."
        assert first["media_name"] == "www.example.com"  # Baidu 没有 mediaName 字段

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
