"""
Tests for ZhituFetcher index support: get_index_realtime_quote + get_kline_data index branch.

Probed upstream payload (2026-07-06) — used to derive expected fields.

Realtime (GET /hz/real/ssjy/000001.SH):
    {"ud":-2.405,"pc":-0.0595,"zf":1.3516,"p":4041.238,"o":4059.194,
     "h":4060.069,"l":4005.414,"yc":4043.643,"cje":1432112821100,
     "v":590364903,"pv":590364903,"tv":2503638,"t":"2026-07-06 15:00:06"}

History (GET /hz/history/fsjy/000001.SH/d?st=20250701&et=20250704):
    [{"t":"2025-07-01 00:00:00","o":3445.85,"h":3459.59,"l":3441.04,
      "c":3457.75,"v":444356739.0,"a":553556536157.0,"pc":3444.43,"sf":0.0}, ...]

5-min history (GET /hz/history/fsjy/000001.SH/5?st=20250704&et=20250704):
    [{"t":"2025-07-04 09:35:00","o":3459.59,"h":3460.98,"l":3457.0,
      "c":3459.34,"v":49991931.0,"a":53593854040.0,"pc":3461.15,"sf":0.0}, ...]
"""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
import requests

from stock_data.data_provider.base import DataCapability
from stock_data.data_provider.core.types import RealtimeSource
from stock_data.data_provider.fetchers.zhitu_fetcher import ZhituFetcher

# ────────────────────────────────────────────────────────────────────────────
# Capability / supports_* declarations
# ────────────────────────────────────────────────────────────────────────────


class TestZhituIndexCapabilities:
    def setup_method(self):
        self.fetcher = ZhituFetcher()

    def test_supports_index_realtime_quote_capability(self):
        assert DataCapability.INDEX_REALTIME_QUOTE in self.fetcher.supported_data_types

    def test_supports_index_kline_capability(self):
        assert DataCapability.INDEX_KLINE in self.fetcher.supported_data_types

    def test_market_is_csi_only(self):
        # 智兔指数 API 只支持沪深 (csi) — HK/US 仍走其他 fetcher。
        assert self.fetcher.supported_markets == {"csi"}

    @pytest.mark.parametrize("period", ["d", "w", "m", "5", "15", "30", "60"])
    def test_supports_kline_index_all_levels(self, period):
        assert self.fetcher.supports_kline(period, "", "csi", "index") is True

    def test_supports_kline_index_rejects_1m(self):
        # 智兔指数 API 不提供 1m, manager 应跳到下一个 fetcher。
        assert self.fetcher.supports_kline("1", "", "csi", "index") is False

    def test_supports_kline_rejects_non_csi_market(self):
        # 智兔只支持 csi, 美/港指仍走 Akshare / Yfinance / Tencent。
        assert self.fetcher.supports_kline("d", "", "hk", "index") is False
        assert self.fetcher.supports_kline("d", "", "us", "index") is False

    def test_supports_kline_stock_unchanged(self):
        # 股票 d/w/m Zhitu 不支持 (只有分钟), 行为不能因为加 index 支持而退化。
        assert self.fetcher.supports_kline("d", "", "csi", "stock") is False
        assert self.fetcher.supports_kline("5", "", "csi", "stock") is True
        assert self.fetcher.supports_kline("1", "", "csi", "stock") is False

    def test_supports_quote_csi(self):
        assert self.fetcher.supports_quote("csi") is True


# ────────────────────────────────────────────────────────────────────────────
# get_index_realtime_quote
# ────────────────────────────────────────────────────────────────────────────


ZHITU_INDEX_REALTIME_PAYLOAD = {
    "ud": -2.405,
    "pc": -0.0595,
    "zf": 1.3516,
    "p": 4041.238,
    "o": 4059.194,
    "h": 4060.069,
    "l": 4005.414,
    "yc": 4043.643,
    "cje": 1432112821100.0,
    "v": 590364903,
    "pv": 590364903,
    "tv": 2503638,
    "t": "2026-07-06 15:00:06",
}


def _set_zhitu_token(fetcher, token: str) -> None:
    """Set the token directly; bypasses os.getenv at the module boundary."""
    fetcher._token = token


def _patch_token(monkeypatch, token: str) -> None:
    """Patch the module-level getenv so is_available() returns True."""
    monkeypatch.setattr(
        "stock_data.data_provider.fetchers.zhitu_fetcher.os.getenv",
        lambda *a, **k: token if a and a[0] == "ZHITU_TOKEN" else "",
    )


class TestGetIndexRealtimeQuote:
    def setup_method(self):
        self.fetcher = ZhituFetcher()

    def test_returns_none_when_token_unset(self, monkeypatch):
        monkeypatch.setattr(
            "stock_data.data_provider.fetchers.zhitu_fetcher.os.getenv",
            lambda *a, **k: "" if a and a[0] == "ZHITU_TOKEN" else "",
        )
        self.fetcher._token = ""
        assert self.fetcher.get_index_realtime_quote("000001") is None

    @patch("stock_data.data_provider.utils.http.requests.get")
    def test_normalizes_full_payload(self, mock_get, monkeypatch):
        _patch_token(monkeypatch, "test_token")
        self.fetcher._token = "test_token"
        mock_response = MagicMock()
        mock_response.json.return_value = ZHITU_INDEX_REALTIME_PAYLOAD
        mock_response.raise_for_status = lambda: None
        mock_get.return_value = mock_response

        q = self.fetcher.get_index_realtime_quote("000001")

        assert q is not None
        assert q.code == "000001"
        # 上游不返回 name, fetcher 不应伪造 — name 留空让 route 层用 index_symbols 补。
        assert q.name == ""
        assert q.source == RealtimeSource.ZHITU
        assert q.price == 4041.238
        assert q.open_price == 4059.194
        assert q.high == 4060.069
        assert q.low == 4005.414
        assert q.pre_close == 4043.643
        assert q.change_amount == -2.405
        assert q.change_pct == -0.0595
        assert q.amplitude == 1.3516
        assert q.amount == 1432112821100.0
        # 智兔指数 v 是**手** (590364903), 归一到股: × 100 = 59036490300。
        # Cross-verified 2026-07-06: Myquant gm SDK 同日 SHSE.000001
        # v=59036490300 股 (公比 / 100 = Zhitu v), 证明 v 是手不是股。
        assert q.volume == 59036490300
        # 结构性不变量: 沪市指数成分股加权均价应在 5-50 元/股
        # cje / volume 应等于成分股加权均价 (元/股)。
        implied_per_share = q.amount / q.volume
        assert 5.0 < implied_per_share < 50.0, (
            f"implied per-share={implied_per_share:.2f} 元/股, "
            f"偏离沪市合理区间 5-50 元/股 — 检查 v 单位是否还正确"
        )
        # 指数无 PE / PB / 总市值 / 流通市值。
        assert q.pe_ratio is None
        assert q.pb_ratio is None
        assert q.total_mv is None
        assert q.circ_mv is None

    @patch("stock_data.data_provider.utils.http.requests.get")
    def test_url_targets_hz_prefix(self, mock_get, monkeypatch):
        """URL 必须是 /hz/ (指数前缀) 而不是 /hs/ (股票前缀) — 防止复制粘贴股票路径。"""
        _patch_token(monkeypatch, "test_token")
        self.fetcher._token = "test_token"
        mock_response = MagicMock()
        mock_response.json.return_value = ZHITU_INDEX_REALTIME_PAYLOAD
        mock_response.raise_for_status = lambda: None
        mock_get.return_value = mock_response

        self.fetcher.get_index_realtime_quote("000001")

        # json_get 用 params= 拼 query string; 检查 path 包含 /hz/real/ssjy/。
        called_url = mock_get.call_args.kwargs.get("url") or mock_get.call_args.args[0]
        assert "/hz/real/ssjy/000001.SH" in called_url
        # market suffix 用 .SH 大写 — 上游实测接受; 若改成小写, 加个测试。
        assert called_url.endswith("000001.SH") or ".SH?" in called_url

    @patch("stock_data.data_provider.utils.http.requests.get")
    def test_returns_none_on_http_error(self, mock_get, monkeypatch):
        _patch_token(monkeypatch, "test_token")
        self.fetcher._token = "test_token"
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = requests.HTTPError("500")
        mock_get.return_value = mock_response
        assert self.fetcher.get_index_realtime_quote("000001") is None

    @patch("stock_data.data_provider.utils.http.requests.get")
    def test_returns_none_on_detail_error(self, mock_get, monkeypatch):
        """上游 {"detail": "..."} 错误信封应被识别为错误, 返回 None。"""
        _patch_token(monkeypatch, "test_token")
        self.fetcher._token = "test_token"
        mock_response = MagicMock()
        mock_response.json.return_value = {"detail": "Licence证书无效"}
        mock_response.raise_for_status = lambda: None
        mock_get.return_value = mock_response
        assert self.fetcher.get_index_realtime_quote("000001") is None

    @patch("stock_data.data_provider.utils.http.requests.get")
    def test_returns_none_on_unexpected_type(self, mock_get, monkeypatch):
        _patch_token(monkeypatch, "test_token")
        self.fetcher._token = "test_token"
        mock_response = MagicMock()
        mock_response.json.return_value = "not a dict"
        mock_response.raise_for_status = lambda: None
        mock_get.return_value = mock_response
        assert self.fetcher.get_index_realtime_quote("000001") is None

    @patch("stock_data.data_provider.utils.http.requests.get")
    def test_returns_none_on_empty_dict(self, mock_get, monkeypatch):
        _patch_token(monkeypatch, "test_token")
        self.fetcher._token = "test_token"
        mock_response = MagicMock()
        mock_response.json.return_value = {}
        mock_response.raise_for_status = lambda: None
        mock_get.return_value = mock_response
        # 与股票 get_realtime_quote 一致: 空 dict 返 None(让 manager failover)。
        assert self.fetcher.get_index_realtime_quote("000001") is None


# ────────────────────────────────────────────────────────────────────────────
# get_kline_data index branch (via override of BaseFetcher.get_kline_data)
# ────────────────────────────────────────────────────────────────────────────


ZHITU_INDEX_HISTORY_DAILY = [
    {
        "t": "2025-07-01 00:00:00",
        "o": 3445.85,
        "h": 3459.59,
        "l": 3441.04,
        "c": 3457.75,
        "v": 444356739.0,
        "a": 553556536157.0,
        "pc": 3444.43,
        "sf": 0.0,
    },
    {
        "t": "2025-07-02 00:00:00",
        "o": 3458.17,
        "h": 3461.33,
        "l": 3447.96,
        "c": 3454.79,
        "v": 498116776.0,
        "a": 543130721694.0,
        "pc": 3457.75,
        "sf": 0.0,
    },
    {
        "t": "2025-07-03 00:00:00",
        "o": 3456.15,
        "h": 3463.62,
        "l": 3446.97,
        "c": 3461.15,
        "v": 438543465.0,
        "a": 500211767756.0,
        "pc": 3454.79,
        "sf": 0.0,
    },
    {
        "t": "2025-07-04 00:00:00",
        "o": 3459.59,
        "h": 3497.22,
        "l": 3455.49,
        "c": 3472.32,
        "v": 500195210.0,
        "a": 567240000000.0,
        "pc": 3461.15,
        "sf": 0.0,
    },
]

ZHITU_INDEX_HISTORY_5MIN = [
    {
        "t": "2025-07-04 09:35:00",
        "o": 3459.59,
        "h": 3460.98,
        "l": 3457.0,
        "c": 3459.34,
        "v": 49991931.0,
        "a": 53593854040.0,
        "pc": 3461.15,
        "sf": 0.0,
    },
    {
        "t": "2025-07-04 09:40:00",
        "o": 3459.62,
        "h": 3459.62,
        "l": 3455.49,
        "c": 3458.02,
        "v": 28923730.0,
        "a": 30740140140.0,
        "pc": 3459.34,
        "sf": 0.0,
    },
]


class TestGetKlineDataIndexDispatch:
    def setup_method(self):
        self.fetcher = ZhituFetcher()

    @patch("stock_data.data_provider.utils.http.requests.get")
    def test_index_daily_uses_hz_prefix(self, mock_get, monkeypatch):
        """Index 6 位代码必须走 /hz/history/fsjy/<code>.<mkt>/<level>。"""
        _patch_token(monkeypatch, "test_token")
        self.fetcher._token = "test_token"
        mock_response = MagicMock()
        mock_response.json.return_value = ZHITU_INDEX_HISTORY_DAILY
        mock_response.raise_for_status = lambda: None
        mock_get.return_value = mock_response

        self.fetcher.get_kline_data("000001", days=4, frequency="d")

        called_url = mock_get.call_args.kwargs.get("url") or mock_get.call_args.args[0]
        assert "/hz/history/fsjy/000001.SH/d" in called_url
        # st/et 是 YYYYMMDD 格式 (上游要求), 验证日期转换
        params = mock_get.call_args.kwargs.get("params", {})
        for date_key in ("st", "et"):
            v = str(params.get(date_key, ""))
            assert len(v) == 8 and v.isdigit(), f"expected YYYYMMDD for {date_key}, got {v!r}"

    @patch("stock_data.data_provider.utils.http.requests.get")
    def test_index_5min_uses_5_level(self, mock_get, monkeypatch):
        _patch_token(monkeypatch, "test_token")
        self.fetcher._token = "test_token"
        mock_response = MagicMock()
        mock_response.json.return_value = ZHITU_INDEX_HISTORY_5MIN
        mock_response.raise_for_status = lambda: None
        mock_get.return_value = mock_response

        self.fetcher.get_kline_data("000001", days=1, frequency="5")

        called_url = mock_get.call_args.kwargs.get("url") or mock_get.call_args.args[0]
        assert "/hz/history/fsjy/000001.SH/5" in called_url

    @patch("stock_data.data_provider.utils.http.requests.get")
    def test_index_399xxx_routes_to_sz(self, mock_get, monkeypatch):
        """深证指数 (399xxx) 必须用 .SZ 后缀。"""
        _patch_token(monkeypatch, "test_token")
        self.fetcher._token = "test_token"
        mock_response = MagicMock()
        mock_response.json.return_value = ZHITU_INDEX_HISTORY_DAILY
        mock_response.raise_for_status = lambda: None
        mock_get.return_value = mock_response

        self.fetcher.get_kline_data("399006", days=2, frequency="d")

        called_url = mock_get.call_args.kwargs.get("url") or mock_get.call_args.args[0]
        assert "/hz/history/fsjy/399006.SZ/d" in called_url

    @patch("stock_data.data_provider.utils.http.requests.get")
    def test_returns_standard_columns(self, mock_get, monkeypatch):
        _patch_token(monkeypatch, "test_token")
        self.fetcher._token = "test_token"
        mock_response = MagicMock()
        mock_response.json.return_value = ZHITU_INDEX_HISTORY_DAILY
        mock_response.raise_for_status = lambda: None
        mock_get.return_value = mock_response

        df = self.fetcher.get_kline_data("000001", days=4, frequency="d")

        assert isinstance(df, pd.DataFrame)
        # 必须含 KLineData 所需的所有列 — 由 api/routes/helpers.py:_build_kline_data 读取
        for col in ("date", "open", "high", "low", "close", "volume", "amount", "pct_chg"):
            assert col in df.columns, f"missing column {col}"
        assert len(df) == 4
        # date 列是 datetime
        assert pd.api.types.is_datetime64_any_dtype(df["date"])

    @patch("stock_data.data_provider.utils.http.requests.get")
    def test_pct_chg_computed_from_pc(self, mock_get, monkeypatch):
        """pct_chg 必须从 (c - pc) / pc * 100 计算, 不能留空。"""
        _patch_token(monkeypatch, "test_token")
        self.fetcher._token = "test_token"
        mock_response = MagicMock()
        mock_response.json.return_value = ZHITU_INDEX_HISTORY_DAILY
        mock_response.raise_for_status = lambda: None
        mock_get.return_value = mock_response

        df = self.fetcher.get_kline_data("000001", days=4, frequency="d")

        # 2025-07-01: c=3457.75, pc=3444.43, expected ≈ 0.387
        first = df.iloc[0]
        expected = (3457.75 - 3444.43) / 3444.43 * 100
        assert abs(first["pct_chg"] - expected) < 1e-6, (
            f"pct_chg={first['pct_chg']}, expected={expected}"
        )

    @patch("stock_data.data_provider.utils.http.requests.get")
    def test_volume_is_shares_after_x100_normalization(self, mock_get, monkeypatch):
        """指数 /hz/history/fsjy/ v 是**手** — 归一到股后应等于 Myquant 同日 v。

        Cross-verified 2026-07-06 with real ZHITU_TOKEN + MYQUANT_TOKEN:
        2025-07-01 Zhitu v=444356739, Myquant v=44435673900 (= 444356739 × 100)
        2025-07-04 Zhitu v=500195210, Myquant v=50019521000
        公比 1:100 精确匹配 — 见 [[zhitu-upstream-volume-unit-inconsistency]]。
        """
        _patch_token(monkeypatch, "test_token")
        self.fetcher._token = "test_token"
        mock_response = MagicMock()
        mock_response.json.return_value = ZHITU_INDEX_HISTORY_DAILY
        mock_response.raise_for_status = lambda: None
        mock_get.return_value = mock_response

        df = self.fetcher.get_kline_data("000001", days=4, frequency="d")

        # 444356739.0 (手) × 100 = 44,435,673,900 (股) — 与 Myquant 一致
        assert df.iloc[0]["volume"] == 44435673900
        # 结构性不变量: cje / volume 应该是合理的成分股加权均价
        # 2025-07-01 SSE Comp: c=3457.75, a=553556536157, expected ~12.46 元/股
        first = df.iloc[0]
        implied = first["amount"] / first["volume"]
        assert 5.0 < implied < 50.0, (
            f"implied per-share={implied:.2f} 元/股, 偏离沪市合理区间"
        )

    @patch("stock_data.data_provider.utils.http.requests.get")
    def test_empty_history_returns_empty_dataframe(self, mock_get, monkeypatch):
        """上游返空 list (非交易日 / 无数据) → 应让 manager 跳到下一个 fetcher。"""
        _patch_token(monkeypatch, "test_token")
        self.fetcher._token = "test_token"
        mock_response = MagicMock()
        mock_response.json.return_value = []
        mock_response.raise_for_status = lambda: None
        mock_get.return_value = mock_response

        from stock_data.data_provider.base import DataFetchError

        with pytest.raises(DataFetchError):
            self.fetcher.get_kline_data("000001", days=4, frequency="d")

    @patch("stock_data.data_provider.utils.http.requests.get")
    def test_stock_daily_still_raises(self, mock_get, monkeypatch):
        """加 index 支持不能影响股票: 股票 d 仍由 base impl 抛 DataFetchError (Zhitu 不支持)。"""
        _patch_token(monkeypatch, "test_token")
        self.fetcher._token = "test_token"
        # 故意让 mock 不被调用 — 抛错就说明没碰到网络
        from stock_data.data_provider.base import DataFetchError

        with pytest.raises(DataFetchError):
            self.fetcher.get_kline_data("600519", days=4, frequency="d")
        assert not mock_get.called, "stock daily should not call Zhitu upstream"

    @patch("stock_data.data_provider.utils.http.requests.get")
    def test_pc_zero_pct_chg_is_na(self, mock_get, monkeypatch):
        """``pc == 0`` 时 ``(close - pc) / pc`` 得 inf, 替换为 NA — 防止
        Route 层的 Pydantic 校验把 inf 渲染成 1.7976931348623157e+308
        (JSON 非有限数)。
        """
        import math

        _patch_token(monkeypatch, "test_token")
        self.fetcher._token = "test_token"
        mock_response = MagicMock()
        # pc=0 (应触发 inf→NA 替换)
        mock_response.json.return_value = [
            {
                "t": "2025-07-01 00:00:00",
                "o": 100.0,
                "h": 101.0,
                "l": 99.0,
                "c": 100.5,
                "v": 1000.0,
                "a": 100000.0,
                "pc": 0.0,
                "sf": 0.0,
            },
        ]
        mock_response.raise_for_status = lambda: None
        mock_get.return_value = mock_response

        df = self.fetcher.get_kline_data("000001", days=1, frequency="d")

        v = df.iloc[0]["pct_chg"]
        assert pd.isna(v) or (isinstance(v, float) and math.isnan(v)), (
            f"expected NA/NaN for pc=0 row, got {v!r}"
        )

    @patch("stock_data.data_provider.utils.http.requests.get")
    def test_code_column_present_for_export_consistency(self, mock_get, monkeypatch):
        """返回 DataFrame 必须含 ``code`` 列(与 base._normalize_dataframe
        对齐), 这样下游 CSV/DB 导出工具对 stock/index 行为一致。
        """
        _patch_token(monkeypatch, "test_token")
        self.fetcher._token = "test_token"
        mock_response = MagicMock()
        mock_response.json.return_value = ZHITU_INDEX_HISTORY_DAILY
        mock_response.raise_for_status = lambda: None
        mock_get.return_value = mock_response

        df = self.fetcher.get_kline_data("000001", days=4, frequency="d")

        assert "code" in df.columns
        assert (df["code"] == "000001").all()
