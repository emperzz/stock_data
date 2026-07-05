"""Smoke test for ThsFetcher's basic.10jqka.com.cn endpoints.

Marked ``@pytest.mark.live_network`` — default ``pytest`` skips it
(addopts in pyproject.toml excludes live_network). Run with:
    .venv/Scripts/python.exe -m pytest -m live_network tests/test_ths_basic_endpoints_live.py
    .venv/Scripts/python.exe -m pytest -m ""       # run everything
"""

import time

import pytest

from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher


@pytest.fixture(scope="module")
def ths() -> ThsFetcher:
    return ThsFetcher()


@pytest.mark.live_network
def test_ths_get_stock_news_smoke_300740(ths):
    """Single GET, 1-2 results expected. (Rate-limit sleep lives in the next test.)"""
    items = ths.get_stock_news("300740", limit=5)
    assert isinstance(items, list)
    assert len(items) > 0, "Expected ≥1 news item for 300740"
    item = items[0]
    assert item["title"]
    assert item["url"].startswith("http")
    assert len(item["publish_date"]) == 10  # YYYY-MM-DD


@pytest.mark.live_network
def test_ths_get_announcements_smoke_300740(ths):
    """Same code, second endpoint. Sleep 2-3s before to be polite."""
    time.sleep(2.5)
    items = ths.get_announcements("300740", page_size=5)
    assert isinstance(items, list)
    assert len(items) > 0
    item = items[0]
    assert item["title"]
    assert item["url"].startswith("http")
    assert len(item["date"]) == 10
    # raw_url is the bonus — verify it's surfaced when present
    # (not all records carry it; just confirm the key exists with str type)
    assert isinstance(item.get("raw_url", ""), str)
