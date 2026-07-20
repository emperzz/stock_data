"""Tests for ThsFetcher.get_board_news (THS F10 news section).

Added 2026-07-20 per spec ``2026-07-20-ths-board-f10-extension-design.md`` §3.3.
"""

from __future__ import annotations

from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import pytest

from stock_data.data_provider.fetchers import ths_fetcher as tff
from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher


@pytest.fixture
def fake_html_bytes():
    with open("tests/fixtures/ths_basic_board_885914_full.html", "rb") as f:
        return f.read()


@pytest.fixture(autouse=True)
def _clear_html_cache():
    tff._f10_html_cache.clear()
    yield
    tff._f10_html_cache.clear()


def _mock_response(status_code: int, body_bytes: bytes) -> MagicMock:
    r = MagicMock()
    r.status_code = status_code
    r.encoding = "gbk"
    r.text = body_bytes.decode("gbk", errors="replace")
    r.content = body_bytes
    return r


def _patched_fetcher(response_factory):
    stack = ExitStack()
    stack.enter_context(
        patch.object(ThsFetcher, "_http_get",
                     side_effect=lambda url, *, headers=None, timeout=10: response_factory())
    )
    stack.enter_context(
        patch.object(ThsFetcher, "_v_token", return_value="fake")
    )
    return ThsFetcher(), stack


def test_get_board_news_parses_dl_in_comments(fake_html_bytes):
    fetcher, stack = _patched_fetcher(lambda: _mock_response(200, fake_html_bytes))
    try:
        news = fetcher.get_board_news("885914", limit=20)
        assert len(news) == 3, f"expected 3 news items; got {len(news)}"
        for n in news:
            assert n["title"]
            assert n["url"].startswith("http://news.10jqka.com.cn/field/")
            assert n["publish_date"] == "2026-07-20"
            assert n["source_domain"] == "news.10jqka.com.cn"
            assert n["publish_time"]
    finally:
        stack.close()


def test_get_board_news_limit_truncates(fake_html_bytes):
    fetcher, stack = _patched_fetcher(lambda: _mock_response(200, fake_html_bytes))
    try:
        news = fetcher.get_board_news("885914", limit=1)
        assert len(news) == 1
    finally:
        stack.close()


def test_get_board_news_industry_returns_empty(fake_html_bytes):
    fetcher, stack = _patched_fetcher(lambda: _mock_response(200, fake_html_bytes))
    try:
        assert fetcher.get_board_news("881101", board_type="industry") == []
    finally:
        stack.close()


def test_get_board_news_401_returns_empty():
    fetcher, stack = _patched_fetcher(lambda: _mock_response(401, b""))
    try:
        assert fetcher.get_board_news("885914") == []
    finally:
        stack.close()


def test_get_board_news_no_newslist_returns_empty():
    stripped = (
        b"<html><body>"
        b"<div id='news'><div class='bd clearfix'></div></div>"
        b"</body></html>"
    )
    fetcher, stack = _patched_fetcher(lambda: _mock_response(200, stripped))
    try:
        assert fetcher.get_board_news("885914") == []
    finally:
        stack.close()
