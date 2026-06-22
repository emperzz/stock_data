"""
Unit tests for EastMoneyFetcher.fetch_flash_news().

覆盖字段映射、limit 边界、上游错误码、空响应、复用 _session。
"""
import json
from unittest.mock import MagicMock, patch

import pytest

from stock_data.data_provider.base import DataFetchError
from stock_data.data_provider.fetchers.eastmoney_fetcher import EastMoneyFetcher

FIXTURE_PATH = "tests/fixtures/flash_news_list.json"


def _load_fixture() -> dict:
    with open(FIXTURE_PATH, encoding="utf-8") as f:
        return json.load(f)


def _mock_response(data: dict, status: int = 200) -> MagicMock:
    mock_response = MagicMock()
    mock_response.status_code = status
    mock_response.json.return_value = data
    return mock_response


class TestFetchFlashNewsHappyPath:
    def setup_method(self):
        self.fetcher = EastMoneyFetcher()

    def test_returns_normalized_dicts(self):
        fixture = _load_fixture()
        with patch.object(
            self.fetcher._session, "get", return_value=_mock_response(fixture)
        ):
            results = self.fetcher.fetch_flash_news(limit=50)

        assert len(results) == 2
        first = results[0]
        assert first["title"] == fixture["data"]["fastNewsList"][0]["title"]
        # url 由 code 拼出
        item_code = fixture["data"]["fastNewsList"][0]["code"]
        assert first["url"] == f"https://finance.eastmoney.com/a/{item_code}.html"
        assert first["source_domain"] == "finance.eastmoney.com"
        assert first["publish_time"] == "2026-06-22 16:23:59"
        # summary 改名 snippet
        assert first["snippet"] == fixture["data"]["fastNewsList"][0]["summary"]

    def test_request_uses_flash_endpoint(self):
        fixture = _load_fixture()
        with patch.object(
            self.fetcher._session, "get", return_value=_mock_response(fixture)
        ) as mock_get:
            self.fetcher.fetch_flash_news(limit=20)

        called_url = mock_get.call_args.args[0]
        params = mock_get.call_args.kwargs["params"]
        assert called_url == "https://np-weblist.eastmoney.com/comm/web/getFastNewsList"
        assert params["client"] == "web"
        assert params["biz"] == "web_724"
        assert params["fastColumn"] == "102"
        # pageSize 取 min(limit, 200)
        assert params["pageSize"] == "20"

    def test_limit_capped_to_200(self):
        """用户传 limit=300 也不应让上游 pageSize 超过 200（虽然路由层会拦，但 fetcher 也防御）。"""
        fixture = _load_fixture()
        with patch.object(
            self.fetcher._session, "get", return_value=_mock_response(fixture)
        ) as mock_get:
            self.fetcher.fetch_flash_news(limit=300)

        params = mock_get.call_args.kwargs["params"]
        assert params["pageSize"] == "200"

    def test_limit_below_one_rejected(self):
        """limit=0 在 fetcher 层抛 DataFetchError。"""
        with pytest.raises(DataFetchError):
            self.fetcher.fetch_flash_news(limit=0)

    def test_uses_chrome120_session_not_plain_requests(self):
        """必须调用 self._session.get，不能新建裸 requests.Session。"""
        fixture = _load_fixture()
        with patch.object(
            self.fetcher._session, "get", return_value=_mock_response(fixture)
        ) as mock_get:
            self.fetcher.fetch_flash_news(limit=10)

        assert mock_get.call_count == 1


class TestFetchFlashNewsErrors:
    def setup_method(self):
        self.fetcher = EastMoneyFetcher()

    def test_non_zero_code_raises(self):
        bad = {"code": -1, "message": "rate limit", "data": None}
        with patch.object(
            self.fetcher._session, "get", return_value=_mock_response(bad)
        ):
            with pytest.raises(DataFetchError, match="code=-1"):
                self.fetcher.fetch_flash_news(limit=10)

    def test_http_error_raises(self):
        bad = _mock_response({}, status=500)
        with patch.object(
            self.fetcher._session, "get", return_value=bad
        ):
            with pytest.raises(DataFetchError, match="HTTP 500"):
                self.fetcher.fetch_flash_news(limit=10)

    def test_empty_fast_news_list_returns_empty(self):
        """fastNewsList 缺失或为 null → 返回 []，不抛错。"""
        empty = {"code": 0, "message": "ok", "data": {"size": 0, "fastNewsList": None}}
        with patch.object(
            self.fetcher._session, "get", return_value=_mock_response(empty)
        ):
            results = self.fetcher.fetch_flash_news(limit=10)
        assert results == []

    def test_zero_items_in_list_returns_empty(self):
        zero = {"code": 0, "message": "ok", "data": {"size": 0, "fastNewsList": []}}
        with patch.object(
            self.fetcher._session, "get", return_value=_mock_response(zero)
        ):
            results = self.fetcher.fetch_flash_news(limit=10)
        assert results == []