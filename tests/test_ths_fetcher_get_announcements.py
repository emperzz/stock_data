"""Unit tests for ThsFetcher.get_announcements (mocked, no live network)."""

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


def test_get_announcements_returns_normalized_items(ths):
    """Normalize THS into Cninfo-compatible shape, including raw_url bonus."""
    payload = _load("ths_basic_notice.json")
    with patch(
        "stock_data.data_provider.fetchers.ths_fetcher.json_get",
        return_value=payload,
    ) as mocked:
        items = ths.get_announcements("300740", page_size=15)
    call = mocked.call_args
    assert call.args[0] == "https://basic.10jqka.com.cn/basicapi/notice/pub"
    assert call.kwargs["params"]["code"] == "300740"
    assert call.kwargs["params"]["market"] == "33"
    assert call.kwargs["params"]["classify"] == "all"
    assert call.kwargs["params"]["page"] == 1
    assert call.kwargs["params"]["limit"] == 15
    assert len(items) == 5
    first = items[0]
    assert first["title"] == "水羊股份：关于2026年第二季度可转换公司债券转股情况的公告"
    assert first["type"] == ""
    assert first["date"] == "2026-07-02"
    assert first["url"].startswith("http://news.10jqka.com.cn/")
    assert first["raw_url"].startswith("http://static.cninfo.com.cn/finalpage/")


def test_get_announcements_no_market_id_returns_empty(ths):
    """Codes not in _THS_MARKET_ID_MAP → []. No HTTP call."""
    with patch("stock_data.data_provider.fetchers.ths_fetcher.json_get") as mocked:
        items = ths.get_announcements("400001", page_size=10)
    assert items == []
    mocked.assert_not_called()


def test_get_announcements_upstream_error_code_returns_empty(ths):
    """status_code != 0 → [], not raise."""
    with patch(
        "stock_data.data_provider.fetchers.ths_fetcher.json_get",
        return_value={"status_code": 1, "status_msg": "boom", "data": {}},
    ):
        items = ths.get_announcements("300740", page_size=5)
    assert items == []


def test_get_announcements_propagates_datafetcherror(ths):
    """Hard network failure raises DataFetchError (manager failover relies on this)."""
    with (
        patch(
            "stock_data.data_provider.fetchers.ths_fetcher.json_get",
            side_effect=DataFetchError("HTTP 503"),
        ),
        pytest.raises(DataFetchError),
    ):
        ths.get_announcements("600519", page_size=5)


def test_get_announcements_clamps_invalid_page_size(ths):
    """Non-int / out-of-range page_size → clamp to [1, 100] / fallback 30."""
    payload = _load("ths_basic_notice.json")
    for bad_input, expected in [
        ("abc", 30),
        (-3, 1),
        (9999, 100),
        (0, 1),
    ]:
        with patch(
            "stock_data.data_provider.fetchers.ths_fetcher.json_get",
            return_value=payload,
        ) as mocked:
            ths.get_announcements("300740", page_size=bad_input)
        assert mocked.call_args.kwargs["params"]["limit"] == expected
