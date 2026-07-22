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


def test_get_board_stocks_full_industry_via_changecode():
    """Industry F10 board stocks are extracted from ``<a onclick="changecode('XXXXXX')">``.

    The page server-renders the full member list inline (no AJAX / no
    pagination) — probed 2026-07-22 against 881121, which yields 157
    unique A-share codes via this pattern.
    """
    # Build the fixture at runtime so the Chinese names are GBK-encoded
    # via ``.encode('gbk')`` (bytes literals can only contain ASCII).
    html_str = """
    <html><body>
      <table>
        <tr><td>1</td><td><a href="javascript:void(0)" onclick="changecode('002213')">大为股份</a></td><td>10.00</td></tr>
        <tr><td>2</td><td><a href="javascript:void(0)" onclick="changecode('002371')">北方华创</a></td><td>2.26</td></tr>
        <tr><td>3</td><td><a href="javascript:void(0)" onclick="changecode('600519')">贵州茅台</a></td><td>100.00</td></tr>
        <tr><td>4</td><td><a href="javascript:void(0)" onclick="changecode('688049')">炬芯科技</a></td><td>43.56</td></tr>
        <tr><td>5</td><td><a href="javascript:void(0)" onclick="changecode('301536')">星宸科技</a></td><td>138.69</td></tr>
        <tr><td>6</td><td><a href="javascript:void(0)" onclick="changecode('830799')">艾融软件</a></td><td>5.55</td></tr>
        <!-- duplicate onclick — same row rendered 10x by tableSorter; must dedup -->
        <tr><td>7</td><td><a href="javascript:void(0)" onclick="changecode('002213')">大为股份</a></td><td>10.00</td></tr>
        <!-- bogus: not a 6-digit code -->
        <tr><td>9</td><td><a href="javascript:void(0)" onclick="changecode('not-a-code')">空</a></td><td>0</td></tr>
        <tr><td>10</td><td><a href="javascript:void(0)" onclick="changecode('')">空</a></td><td>0</td></tr>
        <!-- empty name — must be skipped -->
        <tr><td>11</td><td><a href="javascript:void(0)" onclick="changecode('002156')">   </a></td><td>0</td></tr>
      </table>
    </body></html>
    """
    html = html_str.encode("gbk")
    fetcher, stack = _patched_fetcher(lambda: _mock_response(200, html))
    try:
        rows = fetcher.get_board_stocks_full("881121", board_type="industry")
    finally:
        stack.close()

    # 6 unique valid rows (002213 / 002371 / 600519 / 688049 / 301536 / 830799).
    # 002156's name is whitespace-only → skipped.
    # Bogus `not-a-code` and `''` don't match the regex.
    assert len(rows) == 6, f"expected 6 rows; got {len(rows)}: {[r['stock_code'] for r in rows]}"
    codes = [r["stock_code"] for r in rows]
    assert codes == ["002213", "002371", "600519", "688049", "301536", "830799"]

    # Exchange is inferred from prefix.
    exch_map = {r["stock_code"]: r["exchange"] for r in rows}
    assert exch_map["002213"] == "sz"   # 0/3 → SZ
    assert exch_map["002371"] == "sz"
    assert exch_map["600519"] == "sh"   # 6 → SH
    assert exch_map["688049"] == "sh"   # 6 → SH (科创板)
    assert exch_map["301536"] == "sz"   # 3 → SZ (创业板)
    assert exch_map["830799"] == "bj"   # 8 → BJ (北交所)

    # Names decoded correctly (GBK).
    names = {r["stock_code"]: r["stock_name"] for r in rows}
    assert names["002213"] == "大为股份"
    assert names["002371"] == "北方华创"
    assert names["600519"] == "贵州茅台"

    # All quote-shaped fields None (F10 has no realtime quote).
    for r in rows:
        assert r["price"] is None
        assert r["change_pct"] is None
        assert r["amount"] is None
        assert r["turnover_rate"] is None
        assert r["rank"] is None
        assert r["exchange"] in ("sh", "sz", "bj", "")


def test_get_board_stocks_full_industry_no_changecode_returns_empty():
    """Industry F10 page without ``onclick=\"changecode(...)"`` → 0 rows.

    The upstream may drop the pattern (THS has done similar rewrites
    in the past). The contract: caller falls back to ZZSHARE primary
    + THS AJAX chain rather than crashing.
    """
    html = b"<html><body><p>no stock rows here</p></body></html>"
    fetcher, stack = _patched_fetcher(lambda: _mock_response(200, html))
    try:
        rows = fetcher.get_board_stocks_full("881121", board_type="industry")
    finally:
        stack.close()
    assert rows == []


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
