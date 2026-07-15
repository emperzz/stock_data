"""Contracts for news URLs handed from EastMoney/THS lists to content extraction."""

from unittest.mock import patch

from stock_data.data_provider.fetchers.eastmoney_fetcher import EastMoneyFetcher
from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher
from stock_data.data_provider.utils.news_extractor import NewsContentExtractor
from stock_data.data_provider.utils.url_helpers import source_domain
from tests.test_eastmoney_stock_news import SAMPLE_RESPONSE, _mock_resp
from tests.test_ths_fetcher_get_stock_news import _load

_GENERIC_ARTICLE = """
<html><body>
  <article>
    <p>This mocked article body contains enough text to exercise content input compatibility.</p>
    <p>The URL came from a normalized EastMoney or THS news item.</p>
  </article>
</body></html>
"""


def test_eastmoney_normalized_urls_are_content_inputs(monkeypatch):
    fetcher = EastMoneyFetcher()
    with patch.object(fetcher._session, "get", return_value=_mock_resp(SAMPLE_RESPONSE)):
        items = fetcher.get_stock_news("600519", limit=2)

    monkeypatch.setattr(
        "stock_data.data_provider.utils.news_extractor._is_private_ip",
        lambda host: False,
    )
    for item in items:
        assert item["url"].startswith(("http://", "https://"))
        assert item["source_domain"] == source_domain(item["url"])
        assert item["title"]
        assert item["publish_date"]
        result = NewsContentExtractor.extract(item["url"], html=_GENERIC_ARTICLE)
        assert result.url == item["url"]
        assert result.content_status in {"ok", "empty", "unsupported"}


def test_ths_normalized_urls_are_content_inputs(monkeypatch):
    fetcher = ThsFetcher()
    payload = _load("ths_basic_news.json")
    with patch(
        "stock_data.data_provider.fetchers.ths_fetcher.json_get",
        return_value=payload,
    ):
        items = fetcher.get_stock_news("300740", limit=5)

    monkeypatch.setattr(
        "stock_data.data_provider.utils.news_extractor._is_private_ip",
        lambda host: False,
    )
    for item in items:
        assert item["url"].startswith(("http://", "https://"))
        assert item["source_domain"] == source_domain(item["url"])
        assert item["title"]
        assert item["publish_date"]
        result = NewsContentExtractor.extract(item["url"], html=_GENERIC_ARTICLE)
        assert result.url == item["url"]
        assert result.content_status in {"ok", "empty", "unsupported"}
