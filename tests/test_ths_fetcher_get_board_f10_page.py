"""Tests for ThsFetcher.get_board_f10_page + HTML cache.

Added 2026-07-20 per spec ``2026-07-20-ths-board-f10-extension-design.md`` §3.2.1.
"""

from __future__ import annotations

from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import pytest

from stock_data.data_provider.base import DataFetchError
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


def _patched_fetcher(get_side_effect):
    """Patch ThsFetcher._http_get / _v_token, return (fetcher, exit_stack).

    Caller is responsible for calling ``stack.close()`` after they're done
    with the fetcher. ``with patch.object(...) return ...`` works in
    standalone Python but pytest's loader can interfere with the implicit
    patch scope; using an explicit ExitStack avoids that.
    """
    stack = ExitStack()
    stack.enter_context(patch.object(ThsFetcher, "_http_get", side_effect=get_side_effect))
    stack.enter_context(patch.object(ThsFetcher, "_v_token", return_value="fake"))
    fetcher = ThsFetcher()
    return fetcher, stack


def test_get_board_f10_page_returns_html_on_2xx(fake_html_bytes):
    log = [0]

    def fake_get(url, *, headers=None, timeout=10):
        log[0] += 1
        return _mock_response(200, fake_html_bytes)

    fetcher, stack = _patched_fetcher(fake_get)
    try:
        html = fetcher.get_board_f10_page("885914")
        assert len(html) > 1000, f"expected non-empty HTML; got {len(html)}"
        assert log[0] == 1, f"expected 1 GET; got {log[0]}"

        # Second call hits cache — no second upstream GET.
        html2 = fetcher.get_board_f10_page("885914")
        assert html2 == html
        assert log[0] == 1, f"cache miss re-fetched: {log[0]}"
    finally:
        stack.close()


def test_get_board_f10_page_returns_empty_on_401(fake_html_bytes):
    log = [0]

    def fake_get(url, *, headers=None, timeout=10):
        log[0] += 1
        return _mock_response(401, b"")

    fetcher, stack = _patched_fetcher(fake_get)
    try:
        html = fetcher.get_board_f10_page("885914")
        assert html == ""
        assert log[0] == 1
        # 401 must NOT be cached — second call should retry upstream.
        fetcher.get_board_f10_page("885914")
        assert log[0] == 2, f"401 should not cache; got {log[0]} GETs"
    finally:
        stack.close()


def test_get_board_f10_page_returns_empty_on_403(fake_html_bytes):
    log = [0]

    def fake_get(url, *, headers=None, timeout=10):
        log[0] += 1
        return _mock_response(403, b"")

    fetcher, stack = _patched_fetcher(fake_get)
    try:
        assert fetcher.get_board_f10_page("885914") == ""
    finally:
        stack.close()


def test_get_board_f10_page_raises_on_5xx(fake_html_bytes):
    def fake_get(url, *, headers=None, timeout=10):
        return _mock_response(503, b"")

    fetcher, stack = _patched_fetcher(fake_get)
    try:
        with pytest.raises(DataFetchError):
            fetcher.get_board_f10_page("885914")
    finally:
        stack.close()


def test_get_board_f10_page_industry_hits_upstream(fake_html_bytes):
    """Industry F10 page is reachable (post-2026-07-22).

    Pre-2026-07-22 industry was a v1 stub (returned ``""`` without
    hitting upstream). Now we fetch ``basic.10jqka.com.cn/{code}/``
    (no ``/48/`` prefix for industry) and parse the inline
    ``onclick="changecode(...)"`` rows. The concept fixture used
    here also exercises the no-prefix URL; the change is verified by
    asserting the upstream was hit AND the returned HTML matches what
    the mock served.
    """
    log = [0]

    def fake_get(url, *, headers=None, timeout=10):
        log[0] += 1
        return _mock_response(200, fake_html_bytes)

    fetcher, stack = _patched_fetcher(fake_get)
    try:
        html = fetcher.get_board_f10_page("881121", board_type="industry")
        assert html != "", "industry F10 page must be fetched, not stubbed"
        assert log[0] == 1, "industry must hit upstream exactly once"
    finally:
        stack.close()


def test_get_board_f10_page_industry_url_no_marketid_prefix():
    """Industry URL is ``basic.10jqka.com.cn/{code}/`` (no ``/48/``).

    Concept uses ``/48/{code}/`` (THS upstream marketId convention);
    industry omits the prefix. Verified 2026-07-22 against
    ``basic.10jqka.com.cn/881121/``.
    """
    captured_url = []

    def fake_get(url, *, headers=None, timeout=10):
        captured_url.append(url)
        return _mock_response(200, b"<html></html>")

    fetcher, stack = _patched_fetcher(fake_get)
    try:
        fetcher.get_board_f10_page("881121", board_type="industry")
    finally:
        stack.close()

    assert captured_url[0] == "https://basic.10jqka.com.cn/881121/"


def test_get_board_f10_page_cache_ttl_respected(fake_html_bytes):
    log = [0]

    def fake_get(url, *, headers=None, timeout=10):
        log[0] += 1
        return _mock_response(200, fake_html_bytes)

    fetcher, stack = _patched_fetcher(fake_get)
    try:
        fetcher.get_board_f10_page("885914")
        fetcher.get_board_f10_page("885914")
        assert log[0] == 1

        # Force-expire cache entry.
        cache_key = ThsFetcher._throttle_f10_cache_key("885914", "concept")
        cached_html, _ = tff._f10_html_cache[cache_key]
        tff._f10_html_cache[cache_key] = (cached_html, 0.0)

        fetcher.get_board_f10_page("885914")
        assert log[0] == 2, f"expired cache must refetch; got {log[0]}"
    finally:
        stack.close()
