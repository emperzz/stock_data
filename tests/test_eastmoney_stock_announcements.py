"""Tests for EastMoneyFetcher.get_announcements (np-anotice-stock direct HTTP).

Note: the method was originally named ``get_stock_announcements``;
renamed to ``get_announcements`` in Task 7 to align with the manager's
failover lambda (`f.get_announcements(...)`) and CninfoFetcher's method
name. The capability flag (``DataCapability.ANNOUNCEMENT``) routes both
fetchers through the same failover chain.
"""
from unittest.mock import MagicMock, patch

from stock_data.data_provider.fetchers.eastmoney_fetcher import EastMoneyFetcher

SAMPLE_RESPONSE = {
    "data": {
        "total_hits": 1067,
        "list": [
            {
                "art_code": "AN202606211823708334",
                "title": "贵州茅台:贵州茅台2025年年度权益分派实施公告",
                "notice_date": "2026-06-22 00:00:00",
                "display_time": "2026-06-21 15:31:10:656",
                "eiTime": "2026-06-21 15:32:01:000",
                "codes": [{
                    "stock_code": "600519",
                    "short_name": "贵州茅台",
                    "market_code": "1",
                    "ann_type": "A,SHA",
                }],
                "columns": [{"column_code": "001002002001005", "column_name": "分红送配"}],
            },
            {
                "art_code": "AN202606111823465368",
                "title": "贵州茅台:贵州茅台关于聘任董事会秘书的公告",
                "notice_date": "2026-06-12 00:00:00",
                "display_time": "2026-06-11 20:55:07:400",
                "codes": [{
                    "stock_code": "600519",
                    "short_name": "贵州茅台",
                    "market_code": "1",
                    "ann_type": "A,SHA",
                }],
                "columns": [],
            },
        ],
    },
}


def _mock_resp(payload, status=200):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = payload
    return r


def test_returns_normalized_list():
    fetcher = EastMoneyFetcher()
    with patch.object(fetcher._session, "get", return_value=_mock_resp(SAMPLE_RESPONSE)):
        result = fetcher.get_announcements("600519", page_size=10)
    assert len(result) == 2
    first = result[0]
    assert first["title"] == "贵州茅台:贵州茅台2025年年度权益分派实施公告"
    assert first["date"] == "2026-06-22"
    assert first["type"] == "A,SHA"
    assert "AN202606211823708334" in first["url"]
    assert first["url"].startswith("https://data.eastmoney.com/notices/detail/600519/")


def test_uses_stock_list_param_with_6digit_code():
    """stock_list param is just the 6-digit code, NOT a secid (different from boards/news)."""
    fetcher = EastMoneyFetcher()
    with patch.object(fetcher._session, "get", return_value=_mock_resp(SAMPLE_RESPONSE)) as m:
        fetcher.get_announcements("600519", page_size=20, page_index=2)
    params = m.call_args.kwargs["params"]
    assert params["stock_list"] == "600519"
    assert params["page_size"] == 20
    assert params["page_index"] == 2


def test_returns_empty_on_empty_list():
    fetcher = EastMoneyFetcher()
    empty = {"data": {"total_hits": 0, "list": []}}
    with patch.object(fetcher._session, "get", return_value=_mock_resp(empty)):
        result = fetcher.get_announcements("600519", page_size=10)
    assert result == []


def test_referer_is_data_eastmoney():
    """data.eastmoney.com/notices is the page that emits these requests."""
    fetcher = EastMoneyFetcher()
    with patch.object(fetcher._session, "get", return_value=_mock_resp(SAMPLE_RESPONSE)) as m:
        fetcher.get_announcements("600519", page_size=10)
    headers = m.call_args.kwargs["headers"]
    assert headers["Referer"] == "https://data.eastmoney.com/"


def test_invalid_code_returns_empty():
    """Invalid code → empty list, no HTTP call."""
    fetcher = EastMoneyFetcher()
    with patch.object(fetcher._session, "get") as m:
        result = fetcher.get_announcements("", page_size=10)
    assert result == []
    m.assert_not_called()


def test_handles_missing_codes_array():
    """Defensive: announcement with missing codes[0] should not crash."""
    fetcher = EastMoneyFetcher()
    bad = {
        "data": {
            "total_hits": 1,
            "list": [{
                "art_code": "AN123",
                "title": "t",
                "notice_date": "2026-01-01 00:00:00",
                "codes": [],  # empty
            }],
        },
    }
    with patch.object(fetcher._session, "get", return_value=_mock_resp(bad)):
        result = fetcher.get_announcements("600519", page_size=10)
    assert len(result) == 1
    assert result[0]["type"] == ""  # type falls back to empty
