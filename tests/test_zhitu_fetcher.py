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
        assert ZhituFetcher().priority == 5

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

    @patch("stock_data.data_provider.utils.http.requests.get")
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

    @patch("stock_data.data_provider.utils.http.requests.get")
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

    @patch("stock_data.data_provider.utils.http.requests.get")
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

    @patch("stock_data.data_provider.utils.http.requests.get")
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

    @patch("stock_data.data_provider.utils.http.requests.get")
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

    @patch("stock_data.data_provider.utils.http.requests.get")
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

    @patch("stock_data.data_provider.utils.http.requests.get")
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

    @patch("stock_data.data_provider.utils.http.requests.get")
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

    @patch("stock_data.data_provider.utils.http.requests.get")
    def test_http_failure_returns_empty(self, mock_get, monkeypatch):
        monkeypatch.setattr(
            "stock_data.data_provider.fetchers.zhitu_fetcher.os.getenv",
            lambda *a, **k: "test_token" if a and a[0] == "ZHITU_TOKEN" else "",
        )
        self.fetcher._token = "test_token"
        mock_get.side_effect = requests.ConnectionError("boom")
        assert self.fetcher.get_all_stocks("csi") == []

    @patch("stock_data.data_provider.utils.http.requests.get")
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


class TestGetRealtimeQuoteVolumeUnit:
    """Spec §3.4: /quote `volume` 永远是股.

    Zhitu public stock endpoint `/hs/real/ssjy/` returns `v` in **万手**
    (10,000 lots) — empirically verified 2026-07-06 with real token.
    See [[zhitu-upstream-volume-unit-inconsistency]].

    This test was missing before 2026-07-06 — the bug shipped silently
    for ~4 months (ZhituFetcher merged 2026-03). Pin the correct unit
    here so it can't regress.
    """

    def setup_method(self):
        self.fetcher = ZhituFetcher()

    @patch("stock_data.data_provider.utils.http.requests.get")
    def test_stock_volume_is_shares_not_wanshou(self, mock_get, monkeypatch):
        """茅台 2026-07-06 实测: public /hs/real/ssjy/ v=万手 → 股。

        Upstream 实测值 4.1 万手 (mid-day) = 41,000 手 = 4,100,000 股。
        4.1 经 safe_int 截成 4,期望 4,000,000 股 — 数量级与 broker 源
        `/hs/real/time/` v=40,970 手 = 4,097,000 股 一致 (差 < 3%)。

        修复前(2026-07-06 之前): 输出 400, 偏离真实 4_000_000 4 个数量级。
        修复后: 输出 4_000_000,与 Myquant/Akshare 数量级一致。
        """
        import os as _os
        _real_getenv = _os.getenv
        monkeypatch.setattr(
            "stock_data.data_provider.fetchers.zhitu_fetcher.os.getenv",
            lambda *a, **k: "test_token" if a and a[0] == "ZHITU_TOKEN" else _real_getenv(*a, **k),
        )
        self.fetcher._token = "test_token"

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "t": "2026-07-06 15:06:24",
            "p": 1206.91,
            "pc": 1.04,
            "ud": 12.46,
            "v": 4.1,             # 万手 — public 源实测是万手
            "cje": 4913750668.0,
            "zf": 2.93,
            "hs": 0.33,
            "pe": 13.85,
            "lb": 0.78,
            "fm": 0.0,
            "h": 1215.0,
            "l": 1180.0,
            "o": 1186.0,
            "yc": 1194.45,
            "sz": 1508735985063,
            "lt": 1508735985063,
            "zs": 0.0,
            "sjl": 6.4,
            "zdf60": -14.52,
            "zdfnc": -10.54,
        }
        mock_response.raise_for_status = lambda: None
        mock_get.return_value = mock_response

        q = self.fetcher.get_realtime_quote("600519")
        assert q is not None
        # 万手 × 10000 × 100 = 股: int(4.1) × 1_000_000 = 4_000_000
        # (上游 v 是浮点;safe_int 截尾,精度损失 1 万手 = 100,000 股,误差 < 3%)
        assert q.volume == 4_000_000, (
            f"expected 4,000,000 shares (万手 × 1_000_000), got {q.volume}. "
            f"检查 spec §3.4 归一系数是否还正确 — 见 [[zhitu-upstream-volume-unit-inconsistency]]"
        )
        # 结构性不变量: cje / volume 应在合理 per-share 价格区间
        # (茅台 1206.91 元/股, 但 cje 是公司层面的累计成交额元, 不是单股)
        # 数量级 check 1e6 级别 — 茅台单日 400 万股上下
        assert 1_000_000 < q.volume < 100_000_000, (
            f"volume {q.volume} 数量级异常 — 万手/手/股 归一可能错位"
        )
