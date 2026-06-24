"""Tests for ZhituFetcher board methods."""
from unittest.mock import patch, MagicMock

import pytest

from stock_data.data_provider.base import DataCapability
from stock_data.data_provider.fetchers.zhitu_fetcher import ZhituFetcher


def test_zhitu_fetcher_declares_stock_board_capability():
    assert DataCapability.STOCK_BOARD in ZhituFetcher.supported_data_types


def _make_fetcher(token: str = "test_token") -> ZhituFetcher:
    """Construct a ZhituFetcher bypassing __init__ (avoids env-var dependency)."""
    f = ZhituFetcher.__new__(ZhituFetcher)
    f._token = token
    f.is_available = lambda: bool(token)
    return f


@patch("stock_data.data_provider.fetchers.zhitu_fetcher.requests.get")
def test_get_all_boards_filters_by_type_and_subtype(mock_get):
    """Returns leaves matching requested type/subtype from /hs/index/tree."""
    mock_response = MagicMock()
    mock_response.json.return_value = [
        {"name": "A股-申万行业-煤炭", "code": "sw_mt", "type1": 0, "type2": 0,
         "level": 2, "pcode": "swhy", "pname": "A股-申万行业", "isleaf": 1},
        {"name": "A股-证监会行业-金融业", "code": "csrc_jr", "type1": 0, "type2": 5,
         "level": 2, "pcode": "csrc", "pname": "A股-证监会行业", "isleaf": 1},
        {"name": "A股-热门概念-区块链", "code": "chgn_700231", "type1": 0, "type2": 2,
         "level": 2, "pcode": "chgn", "pname": "A股-热门概念", "isleaf": 1},
        {"name": "A股-大盘指数-沪深300", "code": "idx_hs300", "type1": 0, "type2": 9,
         "level": 2, "pcode": "idx", "pname": "A股-大盘指数", "isleaf": 1},
    ]
    mock_response.raise_for_status = MagicMock()
    mock_get.return_value = mock_response

    fetcher = _make_fetcher()
    boards = fetcher.get_all_boards(board_type="industry", subtype="申万行业")
    assert boards == [
        {"code": "sw_mt", "name": "A股-申万行业-煤炭",
         "type": "industry", "subtype": "申万行业"}
    ]


@patch("stock_data.data_provider.fetchers.zhitu_fetcher.requests.get")
def test_get_all_boards_returns_all_subtypes_when_none(mock_get):
    mock_response = MagicMock()
    mock_response.json.return_value = [
        {"name": "A股-申万行业-煤炭", "code": "sw_mt", "type1": 0, "type2": 0,
         "level": 2, "pcode": "swhy", "pname": "A股-申万行业", "isleaf": 1},
        {"name": "A股-证监会行业-金融业", "code": "csrc_jr", "type1": 0, "type2": 5,
         "level": 2, "pcode": "csrc", "pname": "A股-证监会行业", "isleaf": 1},
    ]
    mock_response.raise_for_status = MagicMock()
    mock_get.return_value = mock_response

    fetcher = _make_fetcher()
    boards = fetcher.get_all_boards(board_type="industry", subtype=None)
    assert len(boards) == 2
    codes = {b["code"] for b in boards}
    assert codes == {"sw_mt", "csrc_jr"}


@patch("stock_data.data_provider.fetchers.zhitu_fetcher.requests.get")
def test_get_board_stocks_calls_index_stock_endpoint(mock_get):
    mock_response = MagicMock()
    mock_response.json.return_value = [
        {"dm": "920088", "mc": "科力股份", "jys": "bj"},
        {"dm": "603798", "mc": "康普顿", "jys": "sh"},
    ]
    mock_response.raise_for_status = MagicMock()
    mock_get.return_value = mock_response

    fetcher = _make_fetcher()
    stocks = fetcher.get_board_stocks("sw_sysh")
    assert stocks == [
        {"stock_code": "920088", "stock_name": "科力股份", "exchange": "bj"},
        {"stock_code": "603798", "stock_name": "康普顿", "exchange": "sh"},
    ]


@patch("stock_data.data_provider.fetchers.zhitu_fetcher.requests.get")
def test_get_stock_boards_calls_index_index_endpoint(mock_get):
    mock_response = MagicMock()
    mock_response.json.return_value = [
        {"code": "sw_yx", "name": "A股-申万行业-银行"},
        {"code": "chgn_700532", "name": "A股-热门概念-MSCI中国"},
        {"code": "gn_rzrq", "name": "A股-概念板块-融资融券"},
    ]
    mock_response.raise_for_status = MagicMock()
    mock_get.return_value = mock_response

    fetcher = _make_fetcher()
    boards = fetcher.get_stock_boards("000001")
    assert boards == [
        {"code": "sw_yx", "name": "A股-申万行业-银行",
         "type": "industry", "subtype": "申万行业"},
        {"code": "chgn_700532", "name": "A股-热门概念-MSCI中国",
         "type": "concept", "subtype": "热门概念"},
        {"code": "gn_rzrq", "name": "A股-概念板块-融资融券",
         "type": "concept", "subtype": "概念板块"},
    ]


def test_get_stock_boards_returns_none_when_token_missing():
    fetcher = _make_fetcher(token="")
    assert fetcher.get_stock_boards("000001") is None


def test_get_board_history_raises_not_implemented():
    """Board K-line is unimplemented for Zhitu."""
    fetcher = _make_fetcher()
    with pytest.raises(NotImplementedError, match="board-level K-line"):
        fetcher.get_board_history("sw_mt", frequency="d", days=30)
