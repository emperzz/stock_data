"""Unit tests for ThsFetcher.get_stock_news (mocked, no live network)."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from stock_data.data_provider.base import DataFetchError
from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((_FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def ths() -> ThsFetcher:
    return ThsFetcher()


def test_get_stock_news_returns_normalized_items(ths):
    """Should normalize THS upstream into EastMoney-compatible dict shape."""
    payload = _load("ths_basic_news.json")
    with patch(
        "stock_data.data_provider.fetchers.ths_fetcher.json_get",
        return_value=payload,
    ) as mocked:
        items = ths.get_stock_news("300740", limit=15)
    assert mocked.call_count == 1
    call = mocked.call_args
    assert call.args[0] == "https://basic.10jqka.com.cn/fuyao/info/company/v1/news"
    assert call.kwargs["params"]["code"] == "300740"
    assert call.kwargs["params"]["market"] == 33  # int, not the str the old first-char map held
    assert call.kwargs["headers"]["Referer"].startswith("https://basic.10jqka.com.cn")
    assert isinstance(items, list)
    assert len(items) == 5
    first = items[0]
    assert set(first.keys()) == {
        "title",
        "url",
        "source_domain",
        "publish_date",
        "publish_time",
        "media_name",
    }
    assert first["title"] == "行业周报|美容护理指数涨7.03%, 跑赢上证指数6.62%"
    assert first["url"].startswith("http://news.10jqka.com.cn/")
    assert first["source_domain"] == "news.10jqka.com.cn"
    assert first["publish_date"] == "2026-07-03"
    # 该上游只给到日: publish_time 如实等于 publish_date, 不编造时分秒。
    assert first["publish_time"] == "2026-07-03"
    assert first["media_name"] == ""


def test_get_stock_news_no_market_id_returns_empty(ths):
    """Codes with no derivable market id (HK / US / indices) → []. No HTTP call.

    北交所 codes are NOT in this set any more: the first-char map used to
    skip them, and sent 9xxxxx to 17 (another company's news). ``_ths_market_id``
    resolves 4xxxxx / 8xxxxx / 920xxx to 151.
    """
    with patch("stock_data.data_provider.fetchers.ths_fetcher.json_get") as mocked:
        assert ths.get_stock_news("HK00700", limit=10) == []
        assert ths.get_stock_news("AAPL", limit=10) == []
    mocked.assert_not_called()


def test_get_stock_news_bj_uses_market_151(ths):
    """北交所 must ask market=151 — market=17 answered with a DIFFERENT
    company's headlines (920002 → 中文在线, measured 2026-10-08)."""
    payload = _load("ths_basic_news.json")
    with patch(
        "stock_data.data_provider.fetchers.ths_fetcher.json_get",
        return_value=payload,
    ) as mocked:
        ths.get_stock_news("920002", limit=5)
    assert mocked.call_args.kwargs["params"]["market"] == 151


def test_get_stock_news_upstream_error_code_returns_empty(ths):
    """status_code != 0 → return [], not raise."""
    bad_payload = {"status_code": 1, "status_msg": "upstream down", "data": {}}
    with patch(
        "stock_data.data_provider.fetchers.ths_fetcher.json_get",
        return_value=bad_payload,
    ):
        items = ths.get_stock_news("300740", limit=5)
    assert items == []


def test_get_stock_news_propagates_datafetcherror(ths):
    """Hard network failure raises DataFetchError."""
    with (
        patch(
            "stock_data.data_provider.fetchers.ths_fetcher.json_get",
            side_effect=DataFetchError("HTTP 503 from basic.10jqka.com.cn"),
        ),
        pytest.raises(DataFetchError),
    ):
        ths.get_stock_news("600519", limit=5)


def test_get_stock_news_clamps_invalid_limit(ths):
    """Non-int / out-of-range limits clamp to [1, 100] / fallback 20."""
    payload = _load("ths_basic_news.json")
    for bad_input, expected in [
        ("abc", 20),
        (-3, 1),
        (9999, 100),
        (0, 1),
    ]:
        with patch(
            "stock_data.data_provider.fetchers.ths_fetcher.json_get",
            return_value=payload,
        ) as mocked:
            ths.get_stock_news("300740", limit=bad_input)
        params = mocked.call_args.kwargs["params"]
        assert params["limit"] == expected, (
            f"limit={bad_input!r} expected upstream limit={expected}, got {params['limit']}"
        )
