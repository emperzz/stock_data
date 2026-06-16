"""
Unit tests for EastMoneyFetcher.search_news().

Covers the JSONP request shape, <em> tag stripping, date normalization,
post-filter on from_date/to_date, and error handling for the spec-defined
failure modes.
"""
import json
from unittest.mock import MagicMock, patch

import pytest

from stock_data.data_provider.base import DataFetchError
from stock_data.data_provider.fetchers.eastmoney_fetcher import EastMoneyFetcher

FIXTURE_PATH = "tests/fixtures/news_search_jsonp.txt"


def _load_fixture() -> str:
    with open(FIXTURE_PATH, encoding="utf-8") as f:
        return f.read()


def _mock_get_returning(text: str, status: int = 200):
    mock_response = MagicMock()
    mock_response.status_code = status
    mock_response.text = text
    return mock_response


class TestSearchNewsHappyPath:
    def setup_method(self):
        self.fetcher = EastMoneyFetcher()

    @patch("stock_data.data_provider.fetchers.eastmoney_fetcher.requests.get")
    def test_returns_normalized_dicts(self, mock_get):
        mock_get.return_value = _mock_get_returning(_load_fixture())

        results = self.fetcher.search_news(q="603777", limit=20)

        assert len(results) == 2
        first = results[0]
        assert first["title"] == "白酒概念下跌1.10%, 8股主力资金净流出超3000万元"  # <em> stripped
        assert first["url"] == "http://finance.eastmoney.com/a/202606093765150130.html"
        assert first["source_domain"] == "finance.eastmoney.com"
        assert first["publish_date"] == "2026-06-09"
        assert first["media_name"] == "证券时报网"
        assert "<em>" not in first["snippet"]

    @patch("stock_data.data_provider.fetchers.eastmoney_fetcher.requests.get")
    def test_request_uses_jsonp_endpoint(self, mock_get):
        mock_get.return_value = _mock_get_returning(_load_fixture())

        self.fetcher.search_news(q="白酒概念", limit=5)

        called_url = mock_get.call_args.args[0]
        called_kwargs = mock_get.call_args.kwargs
        assert called_url == "https://search-api-web.eastmoney.com/search/jsonp"
        params = called_kwargs["params"]
        assert params["cb"].startswith("jQuery_")  # JSONP callback
        decoded = json.loads(params["param"])
        assert decoded["keyword"] == "白酒概念"
        assert decoded["type"] == ["cmsArticleWebOld"]
        assert decoded["param"]["cmsArticleWebOld"]["pageSize"] == 5
        # UA + Referer for anti-bot politeness
        headers = called_kwargs["headers"]
        assert "User-Agent" in headers
        assert "Referer" in headers


class TestSearchNewsFilters:
    def setup_method(self):
        self.fetcher = EastMoneyFetcher()

    @patch("stock_data.data_provider.fetchers.eastmoney_fetcher.requests.get")
    def test_from_date_filter(self, mock_get):
        mock_get.return_value = _mock_get_returning(_load_fixture())

        results = self.fetcher.search_news(q="603777", from_date="2026-05-01")

        assert len(results) == 1  # Only 2026-06-09 matches; 2026-04-29 excluded
        assert results[0]["publish_date"] == "2026-06-09"

    @patch("stock_data.data_provider.fetchers.eastmoney_fetcher.requests.get")
    def test_to_date_filter(self, mock_get):
        mock_get.return_value = _mock_get_returning(_load_fixture())

        results = self.fetcher.search_news(q="603777", to_date="2026-05-01")

        assert len(results) == 1  # Only 2026-04-29 matches
        assert results[0]["publish_date"] == "2026-04-29"

    @patch("stock_data.data_provider.fetchers.eastmoney_fetcher.requests.get")
    def test_date_range_filter(self, mock_get):
        mock_get.return_value = _mock_get_returning(_load_fixture())

        results = self.fetcher.search_news(
            q="603777", from_date="2026-05-01", to_date="2026-06-30"
        )

        assert len(results) == 1
        assert results[0]["publish_date"] == "2026-06-09"


class TestSearchNewsErrors:
    def setup_method(self):
        self.fetcher = EastMoneyFetcher()

    @patch("stock_data.data_provider.fetchers.eastmoney_fetcher.requests.get")
    def test_http_non_200_raises(self, mock_get):
        mock_get.return_value = _mock_get_returning("", status=500)
        with pytest.raises(DataFetchError):
            self.fetcher.search_news(q="603777")

    @patch("stock_data.data_provider.fetchers.eastmoney_fetcher.requests.get")
    def test_jsonp_parse_error_raises(self, mock_get):
        mock_get.return_value = _mock_get_returning("not jsonp at all")
        with pytest.raises(DataFetchError):
            self.fetcher.search_news(q="603777")

    @patch("stock_data.data_provider.fetchers.eastmoney_fetcher.requests.get")
    def test_api_code_nonzero_raises(self, mock_get):
        body = 'jQuery_cb({"code": 403, "msg": "rate limited", "result": {}})'
        mock_get.return_value = _mock_get_returning(body)
        with pytest.raises(DataFetchError):
            self.fetcher.search_news(q="603777")

    @patch("stock_data.data_provider.fetchers.eastmoney_fetcher.requests.get")
    def test_q_too_long_raises(self, mock_get):
        with pytest.raises(DataFetchError):
            self.fetcher.search_news(q="x" * 201)

    @patch("stock_data.data_provider.fetchers.eastmoney_fetcher.requests.get")
    def test_limit_out_of_range_raises(self, mock_get):
        with pytest.raises(DataFetchError):
            self.fetcher.search_news(q="ok", limit=0)
        with pytest.raises(DataFetchError):
            self.fetcher.search_news(q="ok", limit=101)

    @patch("stock_data.data_provider.fetchers.eastmoney_fetcher.requests.get")
    def test_records_missing_critical_fields_are_skipped(self, mock_get):
        # First record OK, second missing 'url', third missing 'date'
        body = (
            'jQuery_cb({"code":0,"hitsTotal":3,"msg":"OK","result":{"cmsArticleWebOld":['
            '{"date":"2026-06-09 16:36:00","title":"<em>603777</em>","url":"http://finance.eastmoney.com/a/1.html","mediaName":"A"},'
            '{"date":"2026-06-09 16:36:00","title":"missing url","mediaName":"B"},'
            '{"title":"missing date","url":"http://finance.eastmoney.com/a/3.html","mediaName":"C"}'
            "]}})"
        )
        mock_get.return_value = _mock_get_returning(body)

        results = self.fetcher.search_news(q="603777")

        assert len(results) == 1
        assert results[0]["media_name"] == "A"
