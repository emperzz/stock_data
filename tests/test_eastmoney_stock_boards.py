"""Tests for EastMoneyFetcher.get_stock_boards (push2 slist/get direct HTTP)."""
import json
from unittest.mock import MagicMock, patch

import pytest

from stock_data.data_provider.fetchers.eastmoney_fetcher import EastMoneyFetcher


SAMPLE_RESPONSE = {
    "rc": 0,
    "rt": 18,
    "data": {
        "total": 29,
        "diff": [
            {"f3": 34, "f4": 8180, "f12": "BK0438", "f13": 90, "f14": "食品饮料",
             "f128": "中炬高新", "f140": "600872", "f141": 1, "f152": 2},
            {"f3": -105, "f4": -4222, "f12": "BK1277", "f13": 90, "f14": "白酒Ⅱ",
             "f128": "贵州茅台", "f140": "600519", "f141": 1, "f152": 2},
            {"f3": -12, "f4": -4387, "f12": "BK0477", "f13": 90, "f14": "酿酒概念",
             "f128": "*ST西发", "f140": "000752", "f141": 0, "f152": 2},
        ],
    },
}


def _mock_resp(payload: dict, status: int = 200) -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.json.return_value = payload
    r.text = json.dumps(payload, ensure_ascii=False)
    return r


def test_returns_normalized_list():
    fetcher = EastMoneyFetcher()
    with patch.object(fetcher._session, "get", return_value=_mock_resp(SAMPLE_RESPONSE)):
        result = fetcher.get_stock_boards("600519", source="eastmoney")
    assert result is not None
    assert len(result) == 3
    first = result[0]
    assert first["code"] == "BK0438"
    assert first["name"] == "食品饮料"
    assert first["change_pct"] == pytest.approx(0.34)
    assert first["leading_stock_code"] == "600872"


def test_secid_format_sh_for_6xxxxx():
    fetcher = EastMoneyFetcher()
    with patch.object(fetcher._session, "get", return_value=_mock_resp(SAMPLE_RESPONSE)) as m:
        fetcher.get_stock_boards("600519", source="eastmoney")
    params = m.call_args.kwargs["params"]
    assert params["secid"] == "1.600519"


def test_secid_format_sz_for_other():
    fetcher = EastMoneyFetcher()
    with patch.object(fetcher._session, "get", return_value=_mock_resp(SAMPLE_RESPONSE)) as m:
        fetcher.get_stock_boards("000001", source="eastmoney")
    params = m.call_args.kwargs["params"]
    assert params["secid"] == "0.000001"


def test_returns_empty_list_on_empty_data():
    fetcher = EastMoneyFetcher()
    empty = {"rc": 0, "data": {"total": 0, "diff": []}}
    with patch.object(fetcher._session, "get", return_value=_mock_resp(empty)):
        result = fetcher.get_stock_boards("600519", source="eastmoney")
    assert result == []


def test_raises_on_network_error():
    fetcher = EastMoneyFetcher()
    with patch.object(fetcher._session, "get", side_effect=Exception("timeout")):
        with pytest.raises(Exception):
            fetcher.get_stock_boards("600519", source="eastmoney")