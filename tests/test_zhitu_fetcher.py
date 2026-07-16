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
        # NOTE: ``self.fetcher._token`` is cached at ``__init__`` from .env —
        # monkeypatching ``os.getenv`` alone does NOT flip ``is_available()``,
        # because ``is_available()`` reads the cached attribute. Clear both.
        monkeypatch.setattr(
            "stock_data.data_provider.fetchers.zhitu_fetcher.os.getenv",
            lambda *a, **k: "" if a and a[0] == "ZHITU_TOKEN" else "",
        )
        self.fetcher._token = ""
        result = self.fetcher.get_stock_info("600519")
        assert result is None

    @patch("stock_data.data_provider.utils.http.requests.get")
    def test_normalizes_full_payload(self, mock_get, monkeypatch):
        """Verify mapping against the **real** Zhitu /hs/gs/gsjj/ payload shape
        (probed live against api.zhituapi.com 2026-07-14). Real upstream uses
        ``addr / rprice / principal / secre / sphone / semail`` and does NOT
        expose share-count fields — those land as ``None``.
        """
        monkeypatch.setattr(
            "stock_data.data_provider.fetchers.zhitu_fetcher.os.getenv",
            lambda *a, **k: "test_token" if a and a[0] == "ZHITU_TOKEN" else "",
        )
        self.fetcher._token = "test_token"
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "name": "贵州茅台酒股份有限公司",
            "ename": "Kweichow Moutai Co.,Ltd.",
            "market": "上海证券交易所",
            "ldate": "2001-08-27",
            "rdate": "1999-11-20",
            "addr": "贵州省仁怀市茅台镇",
            "rprice": "125008万元(CNY)",
            "principal": "南方证券有限公司",
            "bscope": "贵州茅台酒系列产品的生产与销售...",
            "idea": "所属概念板块,白酒,MSCI中国,百元股",
            "secre": "余思明",
            "sphone": "0851-22386002",
            "semail": "mtdm@moutaichina.com",
        }
        mock_get.return_value = mock_response
        mock_response.raise_for_status = lambda: None

        result = self.fetcher.get_stock_info("600519")
        assert result is not None
        assert result["code"] == "600519"
        assert result["name"] == "贵州茅台酒股份有限公司"
        assert result["ename"] == "Kweichow Moutai Co.,Ltd."
        assert result["market"] == "csi"
        assert result["listed_date"] == "2001-08-27"
        assert result["delisted_date"] == ""
        # Zhitu upstream does NOT expose share counts → None
        assert result["total_shares"] is None
        assert result["float_shares"] is None
        # Concepts parsed from comma-separated `idea`
        assert "白酒" in result["concepts"]
        assert "MSCI中国" in result["concepts"]
        # Real field-name mappings (addr/rprice/secre/sphone/semail)
        assert result["registered_address"] == "贵州省仁怀市茅台镇"
        assert result["registered_capital"] == "125008万元(CNY)"
        # `principal` upstream = 主承销商 (underwriter), NOT 法人代表 — must NOT
        # be mapped into `legal_representative` (Zhitu does not expose 法人代表).
        assert result["legal_representative"] == ""
        assert result["business_scope"] == "贵州茅台酒系列产品的生产与销售..."
        assert result["established_date"] == "1999-11-20"
        assert result["secretary"] == "余思明"
        assert result["secretary_phone"] == "0851-22386002"
        assert result["secretary_email"] == "mtdm@moutaichina.com"
        # No 'source' key — manager injects it
        assert "source" not in result

    @patch("stock_data.data_provider.utils.http.requests.get")
    def test_normalizes_code_before_url_interpolation(self, mock_get, monkeypatch):
        """P3-a3 (M10): URL path must use the bare 6-digit code, not raw input.

        Regression guard: callers from ``/control/fetcher-test`` may pass
        the upstream-formatted code (``600519.SH``). Without pre-URL
        ``normalize_stock_code()``, Zhitu returns 404 and the
        _fetch_json side reports a misleading "malformed payload" error.
        """
        monkeypatch.setattr(
            "stock_data.data_provider.fetchers.zhitu_fetcher.os.getenv",
            lambda *a, **k: "test_token" if a and a[0] == "ZHITU_TOKEN" else "",
        )
        self.fetcher._token = "test_token"
        mock_response = MagicMock()
        mock_response.json.return_value = {"name": "贵州茅台"}
        mock_response.raise_for_status = lambda: None
        mock_get.return_value = mock_response

        # Call with the upstream-form variant (SH suffix); the URL hit
        # by requests.get must use the bare 6-digit form.
        self.fetcher.get_stock_info("600519.SH")
        called_url = mock_get.call_args[0][0]
        assert "/hs/gs/gsjj/600519" in called_url, (
            f"URL was not normalized before interpolation: {called_url!r}"
        )
        assert "600519.SH" not in called_url

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
    def test_returns_none_on_detail_error_envelope(self, mock_get, monkeypatch):
        """``_fetch_json`` already strips Zhitu's ``{"detail": ...}`` envelope
        and returns None upstream of this method — but the upstream guard is
        the contract; assert the *direct* contract for callers: a dict whose
        only key is ``detail`` short-circuits to None (defence in depth).
        """
        monkeypatch.setattr(
            "stock_data.data_provider.fetchers.zhitu_fetcher.os.getenv",
            lambda *a, **k: "test_token" if a and a[0] == "ZHITU_TOKEN" else "",
        )
        self.fetcher._token = "test_token"
        mock_response = MagicMock()
        mock_response.json.return_value = {"detail": "Licence证书无效"}
        mock_response.raise_for_status = lambda: None
        mock_get.return_value = mock_response
        assert self.fetcher.get_stock_info("600519") is None

    @patch("stock_data.data_provider.utils.http.requests.get")
    def test_returns_none_on_non_dict_payload(self, mock_get, monkeypatch):
        """Defensive: a list or scalar at top-level must not crash — return None."""
        monkeypatch.setattr(
            "stock_data.data_provider.fetchers.zhitu_fetcher.os.getenv",
            lambda *a, **k: "test_token" if a and a[0] == "ZHITU_TOKEN" else "",
        )
        self.fetcher._token = "test_token"
        mock_response = MagicMock()
        mock_response.json.return_value = ["unexpected", "list"]
        mock_response.raise_for_status = lambda: None
        mock_get.return_value = mock_response
        assert self.fetcher.get_stock_info("600519") is None

    @patch("stock_data.data_provider.utils.http.requests.get")
    def test_returns_none_on_payload_without_name(self, mock_get, monkeypatch):
        """Real gsjj payloads always carry ``name`` — if it's missing, treat as
        malformed (some upstream rows are placeholders)."""
        monkeypatch.setattr(
            "stock_data.data_provider.fetchers.zhitu_fetcher.os.getenv",
            lambda *a, **k: "test_token" if a and a[0] == "ZHITU_TOKEN" else "",
        )
        self.fetcher._token = "test_token"
        mock_response = MagicMock()
        mock_response.json.return_value = {"market": "上海证券交易所", "ldate": ""}
        mock_response.raise_for_status = lambda: None
        mock_get.return_value = mock_response
        assert self.fetcher.get_stock_info("600519") is None

    @patch("stock_data.data_provider.utils.http.requests.get")
    def test_empty_optional_fields_default_to_blank(self, mock_get, monkeypatch):
        """Minimal real-shape payload (just ``name``) — all derived fields blank
        and share counts None (upstream doesn't expose them)."""
        monkeypatch.setattr(
            "stock_data.data_provider.fetchers.zhitu_fetcher.os.getenv",
            lambda *a, **k: "test_token" if a and a[0] == "ZHITU_TOKEN" else "",
        )
        self.fetcher._token = "test_token"
        mock_response = MagicMock()
        mock_response.json.return_value = {"name": "贵州茅台"}
        mock_response.raise_for_status = lambda: None
        mock_get.return_value = mock_response

        result = self.fetcher.get_stock_info("600519")
        assert result["code"] == "600519"
        assert result["name"] == "贵州茅台"
        assert result["ename"] == ""
        assert result["listed_date"] == ""
        assert result["total_shares"] is None
        assert result["float_shares"] is None
        assert result["concepts"] == []
        assert result["registered_address"] == ""
        assert result["registered_capital"] == ""
        assert result["legal_representative"] == ""
        assert result["business_scope"] == ""
        assert result["established_date"] == ""
        assert result["secretary"] == ""
        assert result["secretary_phone"] == ""
        assert result["secretary_email"] == ""


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


class TestNormalizeIntradayZhitu:
    """Mock-based coverage for ``_normalize_intraday_zhitu`` and the full
    ``get_intraday_data`` stock minute K-line path.

    Spec §3.4: /kline `volume` is always in shares (股). Zhitu's
    stock history endpoint ``/hs/history/...`` returns ``v`` in **万手**
    (10,000 lots) — empirically verified 2026-07-06 with real token
    against Myquant gm SDK (returns shares directly, ratio = 1_000_000).
    The normalize step must convert ``万手 × 10000 手/万手 × 100 股/手
    = × 1_000_000``. See [[zhitu-upstream-volume-unit-inconsistency]].

    Live-network tests at ``test_providers.py::TestZhituFetcherIntraday``
    only assert column presence, never volume unit. Without these mock
    tests a regression to ``* 100`` (treating v as 手) would ship silently
    and produce 10000× too small volume values.
    """

    def setup_method(self):
        self.fetcher = ZhituFetcher()

    # ---- _normalize_intraday_zhitu direct unit tests ----

    def test_volume_wanshou_to_shares_conversion(self):
        """Direct call to _normalize_intraday_zhitu — verify × 1_000_000.

        Simulates 平安银行 2025-02-21 09:35: 1000 万手 单根 K 线
        (公开源 /hs/real/ssjy/ 也是这个单位) — expected volume in shares:
        1000 × 1_000_000 = 1_000_000_000 股 = 10 亿股, 与沪深大票 5/15/30
        分钟线典型量级一致。
        """
        import pandas as pd

        df = pd.DataFrame(
            [
                {
                    "t": "2025-02-21T09:35:00",
                    "o": 10.5,
                    "h": 10.52,
                    "l": 10.48,
                    "c": 10.51,
                    "v": 1000.0,        # 万手
                    "a": 10_500_000.0,  # 元
                }
            ]
        )
        out = self.fetcher._normalize_intraday_zhitu(df)
        assert out.iloc[0]["volume"] == 1_000_000_000, (
            f"expected 1_000_000_000 shares (万手 × 1_000_000), "
            f"got {out.iloc[0]['volume']}. 检查 spec §3.4 归一系数。"
        )

    def test_volume_cje_v_implied_price_invariant(self):
        """cje / volume 应等于该 bar 的近似价格(元/股)。

        平安 10.51 元/股 + 1000 万手 = 10.51 × 1000 × 10000 × 100
        = 10_510_000_000 元 成交额(cje)。cje/volume_shares = 10.51。
        若归一错位(cje/v 数量级变 10000× off), 断言会失败。
        """
        import pandas as pd

        df = pd.DataFrame(
            [
                {
                    "t": "2025-02-21T09:35:00",
                    "o": 10.5,
                    "h": 10.52,
                    "l": 10.48,
                    "c": 10.51,
                    "v": 1000.0,                  # 万手
                    "a": 10.51 * 1000 * 1_000_000, # cje = price × volume_shares
                }
            ]
        )
        out = self.fetcher._normalize_intraday_zhitu(df)
        v_shares = out.iloc[0]["volume"]
        cje = out.iloc[0]["amount"]
        implied = cje / v_shares
        # 应等于该 bar 收盘价 10.51
        assert abs(implied - 10.51) < 0.01, (
            f"cje/volume={implied:.2f} 元/股, 期望接近 10.51 (bar 收盘价). "
            f"如果数量级差 100 或 10000,说明 v 单位归一错位。"
        )

    def test_columns_renamed_and_time_truncated(self):
        """t→time, o→open, h→high, l→low, c→close, v→volume, a→amount;
        time 取 HH:MM:SS(从 ISO 字符串末 8 字符)。"""
        import pandas as pd

        df = pd.DataFrame(
            [
                {
                    "t": "2025-02-21T09:35:00",
                    "o": 10.0,
                    "h": 10.1,
                    "l": 9.9,
                    "c": 10.05,
                    "v": 100.0,
                    "a": 100_500.0,
                }
            ]
        )
        out = self.fetcher._normalize_intraday_zhitu(df)
        assert set(out.columns) == {
            "time", "open", "high", "low", "close", "volume", "amount",
        }
        assert out.iloc[0]["time"] == "09:35:00"

    def test_numeric_coercion_handles_string_volumes(self):
        """上游有时把 v 返为字符串 — pd.to_numeric errors='coerce' 应能容忍。"""
        import pandas as pd

        df = pd.DataFrame(
            [
                {"t": "2025-02-21T10:00:00", "o": "10.0", "h": "10.1",
                 "l": "9.9", "c": "10.05", "v": "500", "a": "502500"}
            ]
        )
        out = self.fetcher._normalize_intraday_zhitu(df)
        assert out.iloc[0]["volume"] == 500 * 1_000_000

    def test_keeps_only_standard_columns(self):
        """pc / sf 等上游多返字段应被丢弃(keep_cols 白名单)。"""
        import pandas as pd

        df = pd.DataFrame(
            [
                {"t": "2025-02-21T10:00:00", "o": 10.0, "h": 10.1,
                 "l": 9.9, "c": 10.05, "v": 100.0, "a": 100_500.0,
                 "pc": 9.95, "sf": 0.0, "extra_field": "noise"}
            ]
        )
        out = self.fetcher._normalize_intraday_zhitu(df)
        assert "pc" not in out.columns
        assert "sf" not in out.columns
        assert "extra_field" not in out.columns

    def test_multiple_bars_preserve_order(self):
        """多根 K 线保留原始顺序(不做 sort_values)。"""
        import pandas as pd

        df = pd.DataFrame(
            [
                {"t": "2025-02-21T14:55:00", "o": 10.0, "h": 10.1, "l": 9.9,
                 "c": 10.05, "v": 200.0, "a": 2_010_000.0},
                {"t": "2025-02-21T14:56:00", "o": 10.1, "h": 10.2, "l": 10.0,
                 "c": 10.15, "v": 300.0, "a": 3_045_000.0},
                {"t": "2025-02-21T14:57:00", "o": 10.2, "h": 10.3, "l": 10.1,
                 "c": 10.25, "v": 400.0, "a": 4_100_000.0},
            ]
        )
        out = self.fetcher._normalize_intraday_zhitu(df)
        assert len(out) == 3
        assert list(out["volume"]) == [200_000_000, 300_000_000, 400_000_000]
        # 时间顺序保留
        assert list(out["time"]) == ["14:55:00", "14:56:00", "14:57:00"]

    def test_does_not_mutate_input_dataframe(self):
        """normalize 应该是纯函数 — df.copy() 隔离, 不修改入参。"""
        import pandas as pd

        df = pd.DataFrame(
            [
                {"t": "2025-02-21T10:00:00", "o": 10.0, "h": 10.1, "l": 9.9,
                 "c": 10.05, "v": 100.0, "a": 1_005_000.0}
            ]
        )
        original_v = df["v"].iloc[0]  # 100.0 (万手)
        _ = self.fetcher._normalize_intraday_zhitu(df)
        assert df["v"].iloc[0] == original_v, "normalize 不应修改入参 df"
        assert "v" in df.columns, "rename 只在副本上, 不应污染入参"

    # ---- get_intraday_data end-to-end (mocked HTTP) ----

    @patch("stock_data.data_provider.utils.http.requests.get")
    def test_get_intraday_data_normalizes_volume(self, mock_get, monkeypatch):
        """E2E: 模拟 /hs/history/... 返回的 v=万手, 经 _normalize_intraday_zhitu
        归一后应为股. 1 万手 → 1_000_000 股.
        """
        import os as _os
        _real_getenv = _os.getenv
        monkeypatch.setattr(
            "stock_data.data_provider.fetchers.zhitu_fetcher.os.getenv",
            lambda *a, **k: "test_token" if a and a[0] == "ZHITU_TOKEN" else _real_getenv(*a, **k),
        )
        self.fetcher._token = "test_token"

        # 屏蔽 trade_calendar DB 依赖 — 强制走 date.today() fallback.
        monkeypatch.setattr(
            "stock_data.data_provider.persistence.trade_calendar.get_latest_cached_trade_date",
            lambda: None,
        )

        mock_response = MagicMock()
        mock_response.json.return_value = [
            {
                "t": "2025-02-21T09:35:00",
                "o": 10.0, "h": 10.1, "l": 9.9, "c": 10.05,
                "v": 5.0,          # 5 万手
                "a": 5_025_000.0,  # cje 应等于 5 × 1M × 10.05 = 50,250,000
                                  # 这里故意给个不匹配 cje, 让 cje/v 不变量测试在校验
                                  # volume 之前先通过(volume 是归一后的真值)
            },
            {
                "t": "2025-02-21T09:40:00",
                "o": 10.1, "h": 10.2, "l": 10.0, "c": 10.15,
                "v": 7.5,          # 7.5 万手
                "a": 7_612_500.0,
            },
        ]
        mock_response.raise_for_status = lambda: None
        mock_get.return_value = mock_response

        df = self.fetcher.get_intraday_data("000001", period="5", adjust="")

        assert df is not None
        assert len(df) == 2
        # 5 万手 → 5_000_000 股; 7.5 万手 → 7_500_000 股
        assert df.iloc[0]["volume"] == 5_000_000
        assert df.iloc[1]["volume"] == 7_500_000
        # 数量级合理性 (单只股票 5 分钟线 1e5-1e8 股)
        for v in df["volume"]:
            assert 1e5 < v < 1e8, f"volume {v} 数量级异常"

    @patch("stock_data.data_provider.utils.http.requests.get")
    def test_get_intraday_data_returns_none_for_empty_list(
        self, mock_get, monkeypatch
    ):
        """上游返空 list(节假日/无数据) → 应返 None 让 manager failover。"""
        import os as _os
        _real_getenv = _os.getenv
        monkeypatch.setattr(
            "stock_data.data_provider.fetchers.zhitu_fetcher.os.getenv",
            lambda *a, **k: "test_token" if a and a[0] == "ZHITU_TOKEN" else _real_getenv(*a, **k),
        )
        self.fetcher._token = "test_token"
        monkeypatch.setattr(
            "stock_data.data_provider.persistence.trade_calendar.get_latest_cached_trade_date",
            lambda: None,
        )

        mock_response = MagicMock()
        mock_response.json.return_value = []
        mock_response.raise_for_status = lambda: None
        mock_get.return_value = mock_response

        assert self.fetcher.get_intraday_data("000001", period="5") is None

    @patch("stock_data.data_provider.utils.http.requests.get")
    def test_get_intraday_data_returns_none_on_http_error(
        self, mock_get, monkeypatch
    ):
        """HTTP 5xx 应让 _fetch_json 返 None, get_intraday_data 应传播 None。"""
        import os as _os
        _real_getenv = _os.getenv
        monkeypatch.setattr(
            "stock_data.data_provider.fetchers.zhitu_fetcher.os.getenv",
            lambda *a, **k: "test_token" if a and a[0] == "ZHITU_TOKEN" else _real_getenv(*a, **k),
        )
        self.fetcher._token = "test_token"
        monkeypatch.setattr(
            "stock_data.data_provider.persistence.trade_calendar.get_latest_cached_trade_date",
            lambda: None,
        )

        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = requests.HTTPError("500")
        mock_get.return_value = mock_response

        assert self.fetcher.get_intraday_data("000001", period="5") is None

    def test_get_intraday_data_rejects_period_1(self, monkeypatch):
        """period='1' 智兔不支持 — 应抛 DataFetchError 让 manager failover。"""
        from stock_data.data_provider.base import DataFetchError

        self.fetcher._token = "test_token"
        with pytest.raises(DataFetchError):
            self.fetcher.get_intraday_data("000001", period="1")

    def test_get_intraday_data_returns_none_when_token_missing(self, monkeypatch):
        """token 缺失时, is_available() 为 False, get_intraday_data 应返 None。"""
        monkeypatch.setattr(
            "stock_data.data_provider.fetchers.zhitu_fetcher.os.getenv",
            lambda *a, **k: "" if a and a[0] == "ZHITU_TOKEN" else "",
        )
        self.fetcher._token = ""
        assert self.fetcher.get_intraday_data("000001", period="5") is None


# Import at bottom so the class is discoverable by pytest
import pytest  # noqa: E402
