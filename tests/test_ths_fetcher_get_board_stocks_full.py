"""Tests for ThsFetcher.get_board_stocks_full (THS F10 concept table).

Added 2026-07-20 per spec ``2026-07-20-ths-board-f10-extension-design.md`` §3.2.2.
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


def _patched_fetcher(response_factory):
    """Patch + return fetcher (caller closes the stack)."""
    stack = ExitStack()
    stack.enter_context(
        patch.object(ThsFetcher, "_http_get",
                     side_effect=lambda url, *, headers=None, timeout=10: response_factory())
    )
    stack.enter_context(
        patch.object(ThsFetcher, "_v_token", return_value="fake")
    )
    return ThsFetcher(), stack


def test_get_board_stocks_full_returns_90_rows(fake_html_bytes):
    fetcher, stack = _patched_fetcher(lambda: _mock_response(200, fake_html_bytes))
    try:
        rows = fetcher.get_board_stocks_full("885914")
        assert len(rows) == 90, f"expected 90 stock rows; got {len(rows)}"
    finally:
        stack.close()


def test_get_board_stocks_full_shape_and_quote_none(fake_html_bytes):
    fetcher, stack = _patched_fetcher(lambda: _mock_response(200, fake_html_bytes))
    try:
        rows = fetcher.get_board_stocks_full("885914")
        assert rows
        quote_keys = (
            "price", "change_pct", "change_amount", "volume", "amount",
            "turnover_rate", "amplitude", "high", "low", "open",
            "prev_close", "speed_open", "speed_current",
            "speed_change_pct", "speed_change_amount", "speed_volume",
            "speed_turnover_rate", "rank", "eps", "float_share_yi",
            "float_mv_yi", "limit_up_count_year", "analysis", "pop_info",
        )
        for r in rows[:5]:
            for k in quote_keys:
                assert r[k] is None, f"row {r['stock_code']} {k}={r[k]}"
            assert r["stock_code"]
            assert r["exchange"] in ("sh", "sz", "bj", "")
    finally:
        stack.close()


def test_get_board_stocks_full_industry_returns_empty(fake_html_bytes):
    fetcher, stack = _patched_fetcher(lambda: _mock_response(200, fake_html_bytes))
    try:
        rows = fetcher.get_board_stocks_full("881101", board_type="industry")
        assert rows == []
    finally:
        stack.close()


def test_get_board_stocks_full_401_returns_empty():
    fetcher, stack = _patched_fetcher(lambda: _mock_response(401, b""))
    try:
        rows = fetcher.get_board_stocks_full("885914")
        assert rows == []
    finally:
        stack.close()


def test_get_board_stocks_full_invalid_html_raises():
    stripped = b"<html><body>no c_table here</body></html>"
    fetcher, stack = _patched_fetcher(lambda: _mock_response(200, stripped))
    try:
        with pytest.raises(DataFetchError):
            fetcher.get_board_stocks_full("885914")
    finally:
        stack.close()
