"""Tests for ThsFetcher.get_board_surges (THS F10 surges/timeline section).

Added 2026-07-20 per spec ``2026-07-20-ths-board-f10-extension-design.md`` §3.4.
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


def test_get_board_surges_parses_timeline(fake_html_bytes):
    fetcher, stack = _patched_fetcher(lambda: _mock_response(200, fake_html_bytes))
    try:
        surges = fetcher.get_board_surges("885914", limit=10)
        assert len(surges) == 3, f"expected 3 surges; got {len(surges)}"
        first = surges[0]
        assert first["date"] == "2026-07-14"
        assert isinstance(first["board_change_pct"], (int, float))
        assert isinstance(first["limit_up_count"], int)
        assert isinstance(first["limit_up_stocks"], list)
        for s in first["limit_up_stocks"]:
            assert isinstance(s, str) and len(s) == 6
        # 1st entry: lu_count == len(limit_up_stocks)
        assert first["limit_up_count"] == len(first["limit_up_stocks"])
    finally:
        stack.close()


def test_get_board_surges_limit_truncates(fake_html_bytes):
    fetcher, stack = _patched_fetcher(lambda: _mock_response(200, fake_html_bytes))
    try:
        surges = fetcher.get_board_surges("885914", limit=2)
        assert len(surges) == 2
    finally:
        stack.close()


def test_get_board_surges_industry_returns_empty(fake_html_bytes):
    fetcher, stack = _patched_fetcher(lambda: _mock_response(200, fake_html_bytes))
    try:
        assert fetcher.get_board_surges("881101", board_type="industry") == []
    finally:
        stack.close()


def test_get_board_surges_401_returns_empty():
    fetcher, stack = _patched_fetcher(lambda: _mock_response(401, b""))
    try:
        assert fetcher.get_board_surges("885914") == []
    finally:
        stack.close()


def test_get_board_surges_no_period_returns_empty():
    stripped = b"<html><body>no period</body></html>"
    fetcher, stack = _patched_fetcher(lambda: _mock_response(200, stripped))
    try:
        assert fetcher.get_board_surges("885914") == []
    finally:
        stack.close()
