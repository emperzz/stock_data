"""Opt-in, low-frequency probes for representative news content URLs."""

import logging

import pytest

from stock_data.data_provider.utils.news_extractor import NewsContentExtractor
from tests.test_eastmoney_stock_news import SAMPLE_RESPONSE
from tests.test_ths_fetcher_get_stock_news import _load

logger = logging.getLogger(__name__)

_STATUSES = {
    "ok",
    "empty",
    "unsupported",
    "javascript_required",
    "blocked",
    "fetch_error",
}


def _probe(url: str):
    try:
        result = NewsContentExtractor.extract(url)
    except ValueError as exc:
        # Public DNS failures are fail-closed in the extractor. Do not turn a
        # local resolver outage into a false product failure.
        if "internal network" in str(exc):
            pytest.skip(f"public probe could not pass DNS safety check: {exc}")
        raise

    logger.info(
        "news content probe url=%s canonical=%s extractor=%s status=%s http=%s body_chars=%d",
        url,
        result.canonical_url,
        result.extractor,
        result.content_status,
        result.http_status,
        len(result.body),
    )
    assert result.content_status in _STATUSES
    return result


@pytest.mark.live_network
def test_live_finance_eastmoney_content_probe():
    _probe("http://finance.eastmoney.com/a/202607023791611310.html")


@pytest.mark.live_network
def test_live_caifuhao_eastmoney_content_probe():
    url = SAMPLE_RESPONSE["data"]["list"][1]["Art_Url"]
    assert url.startswith("http://caifuhao.eastmoney.com/")
    _probe(url)


@pytest.mark.live_network
def test_live_ths_content_probe():
    url = _load("ths_basic_news.json")["data"]["data"][0]["pc_url"]
    assert "news.10jqka.com.cn" in url
    _probe(url)
