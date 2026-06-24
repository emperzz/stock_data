"""Tests for EastMoneyFetcher board methods (migrated from AkshareFetcher)."""
from unittest.mock import patch, MagicMock
import pandas as pd
import pytest

from stock_data.data_provider.fetchers.eastmoney_fetcher import EastMoneyFetcher


def _make_em_board_df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


@patch("stock_data.data_provider.fetchers.eastmoney.board._AKSHARE")
def test_get_all_concept_boards_parses_em_response(mock_ak):
    mock_ak.stock_board_concept_name_em.return_value = _make_em_board_df([
        {"板块代码": "BK0001", "板块名称": "测试概念1"},
        {"板块代码": "BK0002", "板块名称": "测试概念2"},
    ])
    fetcher = EastMoneyFetcher()
    boards = fetcher.get_all_concept_boards(source="eastmoney", include_quote=False)
    assert boards == [
        {"code": "BK0001", "name": "测试概念1"},
        {"code": "BK0002", "name": "测试概念2"},
    ]


@patch("stock_data.data_provider.fetchers.eastmoney.board._AKSHARE")
def test_get_all_industry_boards_parses_em_response(mock_ak):
    mock_ak.stock_board_industry_name_em.return_value = _make_em_board_df([
        {"板块代码": "BK1001", "板块名称": "测试行业1"},
    ])
    fetcher = EastMoneyFetcher()
    boards = fetcher.get_all_industry_boards(source="eastmoney", include_quote=False)
    assert boards == [{"code": "BK1001", "name": "测试行业1"}]


@patch("stock_data.data_provider.fetchers.eastmoney.board._AKSHARE")
def test_get_concept_board_stocks_parses_em_response(mock_ak):
    mock_ak.stock_board_concept_cons_em.return_value = _make_em_board_df([
        {"代码": "600519", "名称": "贵州茅台"},
        {"代码": "000001", "名称": "平安银行"},
    ])
    fetcher = EastMoneyFetcher()
    stocks = fetcher.get_concept_board_stocks(
        "BK0001", source="eastmoney", include_quote=False
    )
    assert stocks == [
        {"stock_code": "600519", "stock_name": "贵州茅台"},
        {"stock_code": "000001", "stock_name": "平安银行"},
    ]


@patch("stock_data.data_provider.fetchers.eastmoney.board._AKSHARE")
def test_get_industry_board_stocks_parses_em_response(mock_ak):
    mock_ak.stock_board_industry_cons_em.return_value = _make_em_board_df([
        {"代码": "600519", "名称": "贵州茅台"},
    ])
    fetcher = EastMoneyFetcher()
    stocks = fetcher.get_industry_board_stocks(
        "BK1001", source="eastmoney", include_quote=False
    )
    assert stocks == [{"stock_code": "600519", "stock_name": "贵州茅台"}]


def test_eastmoney_fetcher_declares_stock_board_capability():
    from stock_data.data_provider.base import DataCapability
    assert DataCapability.STOCK_BOARD in EastMoneyFetcher.supported_data_types