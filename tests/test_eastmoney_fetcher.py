"""
Unit tests for EastMoneyFetcher.
"""

from unittest.mock import MagicMock, patch

import pytest

from stock_data.data_provider.base import DataCapability
from stock_data.data_provider.fetchers.eastmoney_fetcher import EastMoneyFetcher, _DCEndpoint


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

    _TEST_EP = _DCEndpoint(report_name="RPT_TEST")

    def test_query_returns_data(self):
        # Production uses self._session.get (curl_cffi Session, Chrome 120
        # impersonation) for the JA3 defense — mock at the session level
        # rather than the legacy module-level requests.get.
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "result": {"data": [{"SECURITY_CODE": "600519", "SECURITY_NAME_ABBR": "Test"}]}
        }
        with patch.object(self.fetcher._session, "get", return_value=mock_response):
            result = self.fetcher._datacenter_query(
                self._TEST_EP, filter_str='(SECURITY_CODE="600519")'
            )
        assert len(result) == 1
        assert result[0]["SECURITY_CODE"] == "600519"

    def test_query_returns_empty_on_error(self):
        with patch.object(self.fetcher._session, "get", side_effect=Exception("Network error")):
            result = self.fetcher._datacenter_query(self._TEST_EP)
        assert result == []

    def test_query_returns_empty_on_null_result(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {"result": None}
        with patch.object(self.fetcher._session, "get", return_value=mock_response):
            result = self.fetcher._datacenter_query(self._TEST_EP)
        assert result == []


class TestMarginTrading:
    def setup_method(self):
        self.fetcher = EastMoneyFetcher()

    @patch.object(EastMoneyFetcher, "_datacenter_query")
    def test_returns_records(self, mock_query):
        mock_query.return_value = [
            {
                "DATE": "2026-05-20T00:00:00",
                "RZYE": 100000000,
                "RZMRE": 5000000,
                "RZCHE": 3000000,
                "RQYE": 2000000,
                "RQMCL": 1000,
                "RQCHL": 500,
                "RZRQYE": 102000000,
            }
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
            {
                "TRADE_DATE": "2026-05-20T00:00:00",
                "DEAL_PRICE": 100.0,
                "CLOSE_PRICE": 98.0,
                "DEAL_VOLUME": 50000,
                "DEAL_AMT": 5000000,
                "BUYER_NAME": "机构专用",
                "SELLER_NAME": "中信证券",
            }
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
            {
                "END_DATE": "2026-03-31T00:00:00",
                "HOLDER_NUM": 150000,
                "HOLDER_NUM_CHANGE": -5000,
                "HOLDER_NUM_RATIO": -3.2,
                "AVG_FREE_SHARES": 8000.0,
            }
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
            {
                "EX_DIVIDEND_DATE": "2025-06-19T00:00:00",
                "PRETAX_BONUS_RMB": 21.91,
                "TRANSFER_RATIO": 0,
                "BONUS_RATIO": 0,
                "ASSIGN_PROGRESS": "实施完成",
            }
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
        import pandas as pd

        from stock_data.data_provider.base import DataFetchError

        f = EastMoneyFetcher()
        with pytest.raises(DataFetchError, match="does not support historical"):
            f._normalize_data(pd.DataFrame(), "600519")


class TestSecid:
    def setup_method(self):
        self.fetcher = EastMoneyFetcher()

    def test_secid_sh(self):
        assert self.fetcher._secid("600519") == "1.600519"
        assert self.fetcher._secid("688017") == "1.688017"

    def test_secid_sz(self):
        assert self.fetcher._secid("000001") == "0.000001"
        assert self.fetcher._secid("300476") == "0.300476"


class TestFundFlowMinute:
    def setup_method(self):
        self.fetcher = EastMoneyFetcher()

    def test_returns_records(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": {"klines": ["09:30,1000,200,300,400,600"]}}
        with patch.object(self.fetcher._session, "get", return_value=mock_response):
            result = self.fetcher.get_fund_flow_minute("600519")
        assert len(result) == 1
        assert result[0]["time"] == "09:30"
        assert result[0]["main_net"] == 1000

    def test_returns_empty_on_error(self):
        with patch.object(self.fetcher._session, "get", side_effect=Exception("Network error")):
            result = self.fetcher.get_fund_flow_minute("600519")
        assert result == []


class TestFundFlow120d:
    def setup_method(self):
        self.fetcher = EastMoneyFetcher()

    def test_returns_records(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": {"klines": ["2026-05-20,5000,1000,2000,3000,4000,6000,7000"]}
        }
        with patch.object(self.fetcher._session, "get", return_value=mock_response):
            result = self.fetcher.get_fund_flow_120d("600519")
        assert len(result) == 1
        assert result[0]["date"] == "2026-05-20"
        assert result[0]["main_net"] == 5000


class TestReports:
    def setup_method(self):
        self.fetcher = EastMoneyFetcher()

    # Records mirror a live probe of reportapi.eastmoney.com/report/list
    # (2026-10-08, code=600519). Non-obvious upstream facts pinned here:
    # aim prices arrive as numeric STRINGS ("" when the report has no target
    # price), and emRatingName (东财评级) / sRatingName (券商评级) are two
    # DIFFERENT rating scales on the same record. The odd literal
    # "Tranding Buy" is EastMoney's own typo, kept verbatim.
    _PRICED = {
        "title": "飞天整体稳健，推进全面向C",
        "publishDate": "2026-08-18 00:00:00.000",
        "orgSName": "群益证券",
        "infoCode": "AP202608181828101201",
        "emRatingName": "持有",
        "sRatingName": "区间操作(Tranding Buy)",
        "indvAimPriceT": "1430.0000000000",
        "indvAimPriceL": "1430.0000000000",
        "predictThisYearEps": "68.12",
        "predictNextYearEps": "73.29",
        "predictNextTwoYearEps": "77.44",
    }
    _NO_PRICE = {
        "title": "贵州茅台公司跟踪报告：以动销定投放，缓解市场压力，低速稳态发展",
        "publishDate": "2026-09-21 00:00:00.000",
        "orgSName": "诚通证券",
        "infoCode": "AP202609211829719676",
        "emRatingName": "买入",
        "sRatingName": "强烈推荐",
        "indvAimPriceT": "",
        "indvAimPriceL": "",
        "predictThisYearEps": "65.1400000000",
        "predictNextYearEps": "67.8700000000",
        "predictNextTwoYearEps": "71.3200000000",
    }

    def test_returns_records(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": [self._PRICED, self._NO_PRICE], "TotalPage": 1}
        with patch.object(self.fetcher._session, "get", return_value=mock_response):
            result = self.fetcher.get_reports("600519", max_pages=1)
        assert len(result) == 2
        priced, no_price = result
        assert priced["title"] == "飞天整体稳健，推进全面向C"
        assert priced["publish_date"] == "2026-08-18"
        assert priced["org"] == "群益证券"
        assert priced["info_code"] == "AP202608181828101201"
        assert priced["rating"] == "持有"
        assert priced["predict_eps_this"] == "68.12"
        assert priced["predict_eps_next"] == "73.29"
        assert priced["predict_eps_next2"] == "77.44"
        # target price + 券商评级 — dropped by this projection before 2026-10-08
        assert priced["target_price"] == "1430.0000000000"
        assert priced["target_price_low"] == "1430.0000000000"
        assert priced["broker_rating"] == "区间操作(Tranding Buy)"
        # upstream emits "" for absent aim prices; fetcher passes it through,
        # ReportRecord sanitization turns it into null at the API boundary.
        assert no_price["target_price"] == ""
        assert no_price["target_price_low"] == ""
        assert no_price["broker_rating"] == "强烈推荐"

    def test_pdf_url(self):
        f = EastMoneyFetcher()
        url = f.get_report_pdf_url("ABC123")
        assert "ABC123" in url
        assert url.startswith("https://pdf.dfcfw.com")

    def test_pdf_url_none(self):
        f = EastMoneyFetcher()
        assert f.get_report_pdf_url("") is None
