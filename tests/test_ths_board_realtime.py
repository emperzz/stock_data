"""Tests for ThsFetcher.get_board_realtime (board-level realtime quote scrape)."""

from unittest.mock import MagicMock, patch

from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

# Real captured .heading block from q.10jqka.com.cn/gn/detail/code/301546/
# (rising board sample, 2026-07-09).
_HEADING_UP = """
<div class="heading">
  <div class="board-hq" style="background:#d75442;">
    <h3>央企国企改革<span>885595</span></h3>
    <span class="board-xj arr-rise">2934.39</span>
    <p class="board-zdf">10.92&nbsp;&nbsp;&nbsp;&nbsp;0.37%</p>
  </div>
  <div class="board-infos">
    <dl><dt>今开</dt><dd class="c-fall">2921.12</dd></dl>
    <dl><dt>昨收</dt><dd>2923.48</dd></dl>
    <dl><dt>最低</dt><dd class="c-fall">2870.11</dd></dl>
    <dl><dt>最高</dt><dd class="c-rise">2936.89</dd></dl>
    <dl><dt>成交量(万手)</dt><dd>15343.80</dd></dl>
    <dl><dt>板块涨幅</dt><dd class="c-rise">0.37%</dd></dl>
    <dl><dt>涨幅排名</dt><dd>229/389</dd></dl>
    <dl><dt>涨跌家数</dt><dd><span class="arr-rise-s">175</span><span class="arr-fall-s">207</span></dd></dl>
    <dl><dt>资金净流入(亿)</dt><dd class="c-rise">34.79</dd></dl>
    <dl><dt>成交额(亿)</dt><dd>2642.50</dd></dl>
  </div>
</div>
"""

# Synthetic falling board: flip board-xj to arr-fall and net-inflow dd to c-fall.
_HEADING_DOWN = (
    _HEADING_UP
    .replace('board-xj arr-rise', 'board-xj arr-fall')
    .replace('<dd class="c-rise">34.79</dd>', '<dd class="c-fall">34.79</dd>')
)


def _parse(html):
    from bs4 import BeautifulSoup
    return ThsFetcher._parse_board_realtime(BeautifulSoup(html, features="lxml"))


def test_parse_board_realtime_rising_sample():
    d = _parse(_HEADING_UP)
    assert d["board_code"] == "885595"
    assert d["board_name"] == "央企国企改革"
    assert d["price"] == 2934.39
    assert d["change_amount"] == 10.92
    assert d["change_pct"] == 0.37
    assert d["open"] == 2921.12
    assert d["prev_close"] == 2923.48
    assert d["low"] == 2870.11
    assert d["high"] == 2936.89
    assert d["volume"] == 15343  # 万手, safe_int
    assert d["amount"] == 2642.50  # 亿元, raw
    assert d["up_count"] == 175
    assert d["down_count"] == 207
    assert d["net_inflow"] == 34.79  # 亿元, raw
    assert d["rank"] == "229/389"


def test_parse_board_realtime_sign_from_css_class():
    """Falling board → change_amount/change_pct/net_inflow negative (sign from class)."""
    d = _parse(_HEADING_DOWN)
    assert d["change_amount"] == -10.92
    assert d["change_pct"] == -0.37
    assert d["net_inflow"] == -34.79
    # Absolute prices stay positive regardless of direction.
    assert d["open"] == 2921.12
    assert d["high"] == 2936.89


def test_get_board_realtime_resolves_cid_and_hits_detail_url():
    """platecode 885595 → cid 301546 (via persistence) → /gn/detail/code/301546/."""
    f = ThsFetcher.__new__(ThsFetcher)
    captured = {}

    def fake_get(url, headers=None, timeout=None, **kw):
        captured["url"] = url
        r = MagicMock()
        r.status_code = 200
        r.content = b"x" * 100
        r.text = _HEADING_UP
        r.encoding = "gbk"
        return r

    with patch(
        "stock_data.data_provider.persistence.board._resolve_ths_cid_from_platecode",
        return_value="301546",
    ), patch.object(ThsFetcher, "_http_get", side_effect=fake_get), patch.object(
        ThsFetcher, "_v_token", return_value="tok"
    ):
        d = f.get_board_realtime("885595")
    assert "/gn/detail/code/301546/" in captured["url"]
    assert d["board_name"] == "央企国企改革"


def test_get_board_realtime_falls_back_to_input_when_cid_unresolved():
    """cid resolution miss → use board_code as-is in the URL."""
    f = ThsFetcher.__new__(ThsFetcher)
    captured = {}

    def fake_get(url, headers=None, timeout=None, **kw):
        captured["url"] = url
        r = MagicMock()
        r.status_code = 200
        r.content = b"x" * 100
        r.text = _HEADING_UP
        r.encoding = "gbk"
        return r

    with patch(
        "stock_data.data_provider.persistence.board._resolve_ths_cid_from_platecode",
        return_value=None,
    ), patch.object(ThsFetcher, "_http_get", side_effect=fake_get), patch.object(
        ThsFetcher, "_v_token", return_value="tok"
    ):
        f.get_board_realtime("301546")
    assert "/gn/detail/code/301546/" in captured["url"]


def test_get_board_realtime_raises_on_http_error():
    from stock_data.data_provider.base import DataFetchError
    import pytest
    f = ThsFetcher.__new__(ThsFetcher)

    def fake_get(url, headers=None, timeout=None, **kw):
        r = MagicMock()
        r.status_code = 500
        r.content = b""
        return r

    with patch(
        "stock_data.data_provider.persistence.board._resolve_ths_cid_from_platecode",
        return_value="301546",
    ), patch.object(ThsFetcher, "_http_get", side_effect=fake_get), patch.object(
        ThsFetcher, "_v_token", return_value="tok"
    ):
        with pytest.raises(DataFetchError):
            f.get_board_realtime("885595")
