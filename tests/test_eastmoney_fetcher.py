"""
Unit tests for EastMoneyFetcher.
"""
import pytest
from unittest.mock import MagicMock, patch

from stock_data.data_provider.fetchers.eastmoney_fetcher import EastMoneyFetcher
from stock_data.data_provider.base import DataCapability


class TestEastMoneyFetcherBasics:
    def test_name(self):
        f = EastMoneyFetcher()
        assert f.name == "EastMoneyFetcher"

    def test_priority(self):
        f = EastMoneyFetcher()
        assert f.priority == 6

    def test_is_available(self):
        f = EastMoneyFetcher()
        assert f.is_available() is True

    def test_capabilities(self):
        f = EastMoneyFetcher()
        assert DataCapability.DRAGON_TIGER in f.supported_data_types
        assert DataCapability.MARGIN_TRADING in f.supported_data_types
        assert DataCapability.BLOCK_TRADE in f.supported_data_types
        assert DataCapability.HOLDER_NUM in f.supported_data_types
        assert DataCapability.DIVIDEND in f.supported_data_types


class TestDatacenterQuery:
    def setup_method(self):
        self.fetcher = EastMoneyFetcher()

    @patch("stock_data.data_provider.fetchers.eastmoney_fetcher.requests.get")
    def test_query_returns_data(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "result": {"data": [{"SECURITY_CODE": "600519", "SECURITY_NAME_ABBR": "Test"}]}
        }
        mock_get.return_value = mock_response

        result = self.fetcher._datacenter_query("RPT_TEST", filter_str='(SECURITY_CODE="600519")')
        assert len(result) == 1
        assert result[0]["SECURITY_CODE"] == "600519"

    @patch("stock_data.data_provider.fetchers.eastmoney_fetcher.requests.get")
    def test_query_returns_empty_on_error(self, mock_get):
        mock_get.side_effect = Exception("Network error")
        result = self.fetcher._datacenter_query("RPT_TEST")
        assert result == []

    @patch("stock_data.data_provider.fetchers.eastmoney_fetcher.requests.get")
    def test_query_returns_empty_on_null_result(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = {"result": None}
        mock_get.return_value = mock_response
        result = self.fetcher._datacenter_query("RPT_TEST")
        assert result == []


class TestMarginTrading:
    def setup_method(self):
        self.fetcher = EastMoneyFetcher()

    @patch.object(EastMoneyFetcher, "_datacenter_query")
    def test_returns_records(self, mock_query):
        mock_query.return_value = [
            {"DATE": "2026-05-20T00:00:00", "RZYE": 100000000, "RZMRE": 5000000,
             "RZCHE": 3000000, "RQYE": 2000000, "RQMCL": 1000, "RQCHL": 500,
             "RZRQYE": 102000000}
        ]
        result = self.fetcher.get_margin_trading("600519")
        assert len(result) == 1
        assert result[0]["date"] == "2026-05-20"
        assert result[0]["rzye"] == 100000000


class TestBlockTrade:
    def setup_method(self):
        self.fetcher = EastMoneyFetcher()

    @patch.object(EastMoneyFetcher, "_datacenter_query")
    def test_returns_records_with_premium(self, mock_query):
        mock_query.return_value = [
            {"TRADE_DATE": "2026-05-20T00:00:00", "DEAL_PRICE": 100.0,
             "CLOSE_PRICE": 98.0, "DEAL_VOLUME": 50000, "DEAL_AMT": 5000000,
             "BUYER_NAME": "机构专用", "SELLER_NAME": "中信证券"}
        ]
        result = self.fetcher.get_block_trade("600519")
        assert len(result) == 1
        assert result[0]["date"] == "2026-05-20"
        assert result[0]["premium_pct"] > 0  # premium when deal > close


class TestHolderNum:
    def setup_method(self):
        self.fetcher = EastMoneyFetcher()

    @patch.object(EastMoneyFetcher, "_datacenter_query")
    def test_returns_records(self, mock_query):
        mock_query.return_value = [
            {"END_DATE": "2026-03-31T00:00:00", "HOLDER_NUM": 150000,
             "HOLDER_NUM_CHANGE": -5000, "HOLDER_NUM_RATIO": -3.2,
             "AVG_FREE_SHARES": 8000.0}
        ]
        result = self.fetcher.get_holder_num_change("600519")
        assert len(result) == 1
        assert result[0]["date"] == "2026-03-31"
        assert result[0]["change_ratio"] == -3.2


class TestDividend:
    def setup_method(self):
        self.fetcher = EastMoneyFetcher()

    @patch.object(EastMoneyFetcher, "_datacenter_query")
    def test_returns_records(self, mock_query):
        mock_query.return_value = [
            {"EX_DIVIDEND_DATE": "2025-06-19T00:00:00", "PRETAX_BONUS_RMB": 21.91,
             "TRANSFER_RATIO": 0, "BONUS_RATIO": 0, "ASSIGN_PROGRESS": "实施完成"}
        ]
        result = self.fetcher.get_dividend("600519")
        assert len(result) == 1
        assert result[0]["date"] == "2025-06-19"
        assert result[0]["bonus_rmb"] == 21.91


class TestHistoricalNotSupported:
    def test_fetch_raw_data_raises(self):
        from stock_data.data_provider.base import DataFetchError
        f = EastMoneyFetcher()
        with pytest.raises(DataFetchError, match="does not support historical"):
            f._fetch_raw_data("600519", "2026-01-01", "2026-05-01")

    def test_normalize_data_raises(self):
        from stock_data.data_provider.base import DataFetchError
        import pandas as pd
        f = EastMoneyFetcher()
        with pytest.raises(DataFetchError, match="does not support historical"):
            f._normalize_data(pd.DataFrame(), "600519")
