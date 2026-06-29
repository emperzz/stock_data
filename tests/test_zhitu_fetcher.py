"""
Unit tests for ZhituFetcher.
"""
from unittest.mock import MagicMock, patch

import requests

from stock_data.data_provider.base import DataCapability
from stock_data.data_provider.fetchers.zhitu_fetcher import ZhituFetcher


class TestZhituFetcherBasics:
    def test_name(self):
        assert ZhituFetcher().name == "ZhituFetcher"

    def test_priority_default(self):
        assert ZhituFetcher().priority == 4

    def test_capabilities(self):
        caps = ZhituFetcher().supported_data_types
        assert DataCapability.STOCK_REALTIME_QUOTE in caps
        assert DataCapability.STOCK_ZT_POOL in caps
        assert DataCapability.STOCK_INFO in caps  # NEW


class TestGetStockInfo:
    def setup_method(self):
        self.fetcher = ZhituFetcher()

    def test_returns_none_when_unavailable(self, monkeypatch):
        monkeypatch.setattr("stock_data.data_provider.fetchers.zhitu_fetcher.os.getenv", lambda *a, **k: "" if a and a[0] == "ZHITU_TOKEN" else "")
        result = self.fetcher.get_stock_info("600519")
        assert result is None

    @patch("stock_data.data_provider.fetchers.zhitu_fetcher.requests.get")
    def test_normalizes_full_payload(self, mock_get, monkeypatch):
        monkeypatch.setattr(
            "stock_data.data_provider.fetchers.zhitu_fetcher.os.getenv",
            lambda *a, **k: "test_token" if a and a[0] == "ZHITU_TOKEN" else "",
        )
        self.fetcher._token = "test_token"
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "code": "600519",
            "name": "贵州茅台",
            "ename": "Kweichow Moutai Co.,Ltd.",
            "ldate": "2001-08-27",
            "rdate": "1999-11-20",
            "totalstock": "125619.78",
            "flowstock": "125619.78",
            "idea": "白酒,融资融券,证金持股,沪股通",
            "raddr": "贵州省遵义市仁怀市茅台镇",
            "rcapital": "9.82亿",
            "rname": "丁雄军",
            "bscope": "酒类生产、销售...",
            "bsname": "蒋焰",
            "bsphone": "0851-22386002",
            "bsemail": "mtdm@maotai.com.cn",
        }
        mock_get.return_value = mock_response
        mock_response.raise_for_status = lambda: None

        result = self.fetcher.get_stock_info("600519")
        assert result is not None
        assert result["code"] == "600519"
        assert result["name"] == "贵州茅台"
        assert result["ename"] == "Kweichow Moutai Co.,Ltd."
        assert result["market"] == "csi"
        assert result["listed_date"] == "2001-08-27"
        assert result["delisted_date"] == ""
        assert result["total_shares"] == 125619.78
        assert result["float_shares"] == 125619.78
        assert result["industry"] == ""
        assert result["concepts"] == ["白酒", "融资融券", "证金持股", "沪股通"]
        assert result["registered_address"] == "贵州省遵义市仁怀市茅台镇"
        assert result["registered_capital"] == "9.82亿"
        assert result["legal_representative"] == "丁雄军"
        assert result["business_scope"] == "酒类生产、销售..."
        assert result["established_date"] == "1999-11-20"
        assert result["secretary"] == "蒋焰"
        assert result["secretary_phone"] == "0851-22386002"
        assert result["secretary_email"] == "mtdm@maotai.com.cn"
        # No 'source' key — manager injects it
        assert "source" not in result

    @patch("stock_data.data_provider.fetchers.zhitu_fetcher.requests.get")
    def test_returns_none_on_http_error(self, mock_get, monkeypatch):
        monkeypatch.setattr(
            "stock_data.data_provider.fetchers.zhitu_fetcher.os.getenv",
            lambda *a, **k: "test_token" if a and a[0] == "ZHITU_TOKEN" else "",
        )
        self.fetcher._token = "test_token"
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = requests.HTTPError("500 Server Error")
        mock_get.return_value = mock_response
        assert self.fetcher.get_stock_info("600519") is None

    @patch("stock_data.data_provider.fetchers.zhitu_fetcher.requests.get")
    def test_returns_none_on_malformed_payload(self, mock_get, monkeypatch):
        monkeypatch.setattr(
            "stock_data.data_provider.fetchers.zhitu_fetcher.os.getenv",
            lambda *a, **k: "test_token" if a and a[0] == "ZHITU_TOKEN" else "",
        )
        self.fetcher._token = "test_token"
        mock_response = MagicMock()
        mock_response.json.return_value = {"detail": "Licence证书无效"}
        mock_response.raise_for_status = lambda: None
        mock_get.return_value = mock_response
        # No 'code' key in payload → returns None
        assert self.fetcher.get_stock_info("600519") is None

    @patch("stock_data.data_provider.fetchers.zhitu_fetcher.requests.get")
    def test_empty_optional_fields_default_to_blank(self, mock_get, monkeypatch):
        monkeypatch.setattr(
            "stock_data.data_provider.fetchers.zhitu_fetcher.os.getenv",
            lambda *a, **k: "test_token" if a and a[0] == "ZHITU_TOKEN" else "",
        )
        self.fetcher._token = "test_token"
        mock_response = MagicMock()
        mock_response.json.return_value = {"code": "600519", "name": "贵州茅台"}
        mock_response.raise_for_status = lambda: None
        mock_get.return_value = mock_response

        result = self.fetcher.get_stock_info("600519")
        assert result["ename"] == ""
        assert result["listed_date"] == ""
        assert result["total_shares"] is None
        assert result["concepts"] == []
        assert result["registered_address"] == ""
        assert result["secretary"] == ""


class TestGetAllStocks:
    def setup_method(self):
        self.fetcher = ZhituFetcher()

    def test_returns_empty_when_unavailable(self, monkeypatch):
        import os as _os
        _real_getenv = _os.getenv  # capture before patching (os is shared)
        monkeypatch.setattr(
            "stock_data.data_provider.fetchers.zhitu_fetcher.os.getenv",
            lambda *a, **k: "" if a and a[0] == "ZHITU_TOKEN" else _real_getenv(*a, **k),
        )
        # Fetcher was constructed in setup_method before the monkeypatch,
        # so self._token already holds the real env value. Blank it now so
        # is_available() returns False (matches the "no token" scenario).
        self.fetcher._token = ""
        result = self.fetcher.get_all_stocks("csi")
        assert result == []

    def test_returns_empty_for_non_csi_market(self, monkeypatch):
        monkeypatch.setattr(
            "stock_data.data_provider.fetchers.zhitu_fetcher.os.getenv",
            lambda *a, **k: "test_token" if a and a[0] == "ZHITU_TOKEN" else "",
        )
        self.fetcher._token = "test_token"
        assert self.fetcher.get_all_stocks("hk") == []
        assert self.fetcher.get_all_stocks("us") == []

    @patch("stock_data.data_provider.fetchers.zhitu_fetcher.requests.get")
    def test_normalizes_zhitu_payload(self, mock_get, monkeypatch):
        monkeypatch.setattr(
            "stock_data.data_provider.fetchers.zhitu_fetcher.os.getenv",
            lambda *a, **k: "test_token" if a and a[0] == "ZHITU_TOKEN" else "",
        )
        self.fetcher._token = "test_token"
        mock_response = MagicMock()
        mock_response.json.return_value = [
            {"dm": "688411", "mc": "N海博", "jys": "sh"},
            {"dm": "000001", "mc": "平安银行", "jys": "sz"},
            {"dm": "300750", "mc": "宁德时代", "jys": "sz"},
        ]
        mock_response.raise_for_status = lambda: None
        mock_get.return_value = mock_response

        result = self.fetcher.get_all_stocks("csi")
        assert len(result) == 3
        assert result[0] == {"code": "688411", "name": "N海博", "exchange": "sh"}
        assert result[1] == {"code": "000001", "name": "平安银行", "exchange": "sz"}
        assert result[2] == {"code": "300750", "name": "宁德时代", "exchange": "sz"}

    @patch("stock_data.data_provider.fetchers.zhitu_fetcher.requests.get")
    def test_empty_list_response(self, mock_get, monkeypatch):
        monkeypatch.setattr(
            "stock_data.data_provider.fetchers.zhitu_fetcher.os.getenv",
            lambda *a, **k: "test_token" if a and a[0] == "ZHITU_TOKEN" else "",
        )
        self.fetcher._token = "test_token"
        mock_response = MagicMock()
        mock_response.json.return_value = []
        mock_response.raise_for_status = lambda: None
        mock_get.return_value = mock_response
        assert self.fetcher.get_all_stocks("csi") == []

    @patch("stock_data.data_provider.fetchers.zhitu_fetcher.requests.get")
    def test_error_detail_returns_empty(self, mock_get, monkeypatch):
        monkeypatch.setattr(
            "stock_data.data_provider.fetchers.zhitu_fetcher.os.getenv",
            lambda *a, **k: "test_token" if a and a[0] == "ZHITU_TOKEN" else "",
        )
        self.fetcher._token = "test_token"
        mock_response = MagicMock()
        mock_response.json.return_value = {"detail": "Licence证书无效"}
        mock_response.raise_for_status = lambda: None
        mock_get.return_value = mock_response
        assert self.fetcher.get_all_stocks("csi") == []

    @patch("stock_data.data_provider.fetchers.zhitu_fetcher.requests.get")
    def test_unexpected_response_type_returns_empty(self, mock_get, monkeypatch):
        monkeypatch.setattr(
            "stock_data.data_provider.fetchers.zhitu_fetcher.os.getenv",
            lambda *a, **k: "test_token" if a and a[0] == "ZHITU_TOKEN" else "",
        )
        self.fetcher._token = "test_token"
        mock_response = MagicMock()
        mock_response.json.return_value = "not a list"
        mock_response.raise_for_status = lambda: None
        mock_get.return_value = mock_response
        assert self.fetcher.get_all_stocks("csi") == []

    @patch("stock_data.data_provider.fetchers.zhitu_fetcher.requests.get")
    def test_http_failure_returns_empty(self, mock_get, monkeypatch):
        monkeypatch.setattr(
            "stock_data.data_provider.fetchers.zhitu_fetcher.os.getenv",
            lambda *a, **k: "test_token" if a and a[0] == "ZHITU_TOKEN" else "",
        )
        self.fetcher._token = "test_token"
        mock_get.side_effect = requests.ConnectionError("boom")
        assert self.fetcher.get_all_stocks("csi") == []

    @patch("stock_data.data_provider.fetchers.zhitu_fetcher.requests.get")
    def test_skips_rows_with_empty_code(self, mock_get, monkeypatch):
        monkeypatch.setattr(
            "stock_data.data_provider.fetchers.zhitu_fetcher.os.getenv",
            lambda *a, **k: "test_token" if a and a[0] == "ZHITU_TOKEN" else "",
        )
        self.fetcher._token = "test_token"
        mock_response = MagicMock()
        mock_response.json.return_value = [
            {"dm": "600519", "mc": "贵州茅台", "jys": "sh"},
            {"dm": "", "mc": "无名", "jys": "sz"},
        ]
        mock_response.raise_for_status = lambda: None
        mock_get.return_value = mock_response
        result = self.fetcher.get_all_stocks("csi")
        assert len(result) == 1
        assert result[0]["code"] == "600519"

    def test_capability_includes_stock_list(self):
        assert DataCapability.STOCK_LIST in ZhituFetcher().supported_data_types
