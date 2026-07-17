"""
Unit tests for ZhituFetcher's gap-fix methods:

- get_dividend            →  hs/gs/jnff/{code}
- get_fund_flow_minute    →  hs/history/transaction/{code} (today)
- get_fund_flow_120d      →  hs/history/transaction/{code} (120 days)
- get_holder_num_change   →  hs/gs/gdbh/{code}

All four route through ZhituFetcher._fetch_json, which is the seam we
mock via ``requests.get``.
"""

import os
from unittest.mock import MagicMock, patch

import pytest
import requests

from stock_data.data_provider.base import DataCapability
from stock_data.data_provider.fetchers.zhitu_fetcher import ZhituFetcher

# ---------------------------------------------------------------------------
# Helpers — shared setup for every test (token + mock response).
# ---------------------------------------------------------------------------


def _enable_token(fetcher: ZhituFetcher, monkeypatch) -> None:
    """Force ``is_available()`` to return True without reading real env vars."""
    monkeypatch.setattr(
        "stock_data.data_provider.fetchers.zhitu_fetcher.os.getenv",
        lambda *a, **k: (
            "test_token" if a and a[0] == "ZHITU_TOKEN" else os.environ.get(a[0] if a else "", "")
        ),
    )
    fetcher._token = "test_token"


def _make_json_response(payload):
    """Build a requests.Response-like MagicMock that returns ``payload`` as JSON."""
    mock_response = MagicMock()
    mock_response.json.return_value = payload
    mock_response.raise_for_status = lambda: None
    return mock_response


def _patch_trade_calendar(monkeypatch, latest_date: str | None) -> None:
    """Patch ``get_latest_cached_trade_date`` so fund_flow_minute uses a stable date."""
    from stock_data.data_provider.persistence import trade_calendar as tc_module

    monkeypatch.setattr(tc_module, "get_latest_cached_trade_date", lambda: latest_date)


# ---------------------------------------------------------------------------
# Capability
# ---------------------------------------------------------------------------


class TestCapability:
    def test_dividend_capability_declared(self):
        assert DataCapability.DIVIDEND in ZhituFetcher().supported_data_types

    def test_fund_flow_capability_declared(self):
        assert DataCapability.FUND_FLOW in ZhituFetcher().supported_data_types

    def test_holder_num_capability_declared(self):
        assert DataCapability.HOLDER_NUM in ZhituFetcher().supported_data_types

    def test_methods_resolve(self):
        for m in (
            "get_dividend",
            "get_fund_flow_minute",
            "get_fund_flow_120d",
            "get_holder_num_change",
        ):
            assert callable(getattr(ZhituFetcher, m, None)), f"{m} missing"


# ===========================================================================
# get_dividend
# ===========================================================================


class TestGetDividend:
    def setup_method(self):
        self.fetcher = ZhituFetcher()

    def test_returns_empty_when_token_missing(self, monkeypatch):
        self.fetcher._token = ""
        assert self.fetcher.get_dividend("600519") == []

    @patch("stock_data.data_provider.utils.http.requests.get")
    def test_normalizes_payload(self, mock_get, monkeypatch):
        _enable_token(self.fetcher, monkeypatch)
        mock_get.return_value = _make_json_response(
            [
                {
                    "sdate": "2024-09-26",
                    "give": "0",
                    "change": "0",
                    "send": "2.46",
                    "line": "实施",
                    "cdate": "2024-10-10",
                    "edate": "2024-10-09",
                    "hdate": "--",
                },
                {
                    "sdate": "2024-06-06",
                    "give": "1",
                    "change": "2",
                    "send": "7.19",
                    "line": "实施",
                    "cdate": "2024-06-14",
                    "edate": "2024-06-13",
                    "hdate": "--",
                },
            ]
        )
        result = self.fetcher.get_dividend("600519")
        assert len(result) == 2
        assert result[0]["date"] == "2024-10-10"
        assert result[0]["bonus_rmb"] == pytest.approx(
            0.246
        )  # 2.46 / 10 (per-10-share → per-share)
        assert result[0]["transfer_ratio"] == 0.0
        assert result[0]["bonus_ratio"] == 0.0
        assert result[0]["plan"] == "实施"
        assert result[1]["date"] == "2024-06-14"
        assert result[1]["bonus_rmb"] == pytest.approx(
            0.719
        )  # 7.19 / 10 (per-10-share → per-share)
        assert result[1]["transfer_ratio"] == 2.0
        assert result[1]["bonus_ratio"] == 1.0

    @patch("stock_data.data_provider.utils.http.requests.get")
    def test_sorts_newest_first(self, mock_get, monkeypatch):
        _enable_token(self.fetcher, monkeypatch)
        mock_get.return_value = _make_json_response(
            [
                {"cdate": "2023-07-15", "send": "0.10", "change": "0", "give": "0", "line": "实施"},
                {"cdate": "2025-06-23", "send": "0.50", "change": "0", "give": "0", "line": "实施"},
                {"cdate": "2024-06-17", "send": "0.30", "change": "0", "give": "0", "line": "实施"},
            ]
        )
        result = self.fetcher.get_dividend("600519")
        assert [r["date"] for r in result] == ["2025-06-23", "2024-06-17", "2023-07-15"]

    @patch("stock_data.data_provider.utils.http.requests.get")
    def test_drops_records_without_ex_date(self, mock_get, monkeypatch):
        """预案 / 预披露 rows have empty cdate — must be filtered out."""
        _enable_token(self.fetcher, monkeypatch)
        mock_get.return_value = _make_json_response(
            [
                {"cdate": "", "send": "0.20", "change": "0", "give": "0", "line": "预案"},
                {"cdate": "2025-06-23", "send": "0.50", "change": "0", "give": "0", "line": "实施"},
            ]
        )
        result = self.fetcher.get_dividend("600519")
        assert len(result) == 1
        assert result[0]["date"] == "2025-06-23"

    @patch("stock_data.data_provider.utils.http.requests.get")
    def test_page_size_caps_results(self, mock_get, monkeypatch):
        _enable_token(self.fetcher, monkeypatch)
        mock_get.return_value = _make_json_response(
            [
                {
                    "cdate": f"{year}-06-23",
                    "send": "0.50",
                    "change": "0",
                    "give": "0",
                    "line": "实施",
                }
                for year in range(2020, 2025)
            ]
        )
        result = self.fetcher.get_dividend("600519", page_size=2)
        assert len(result) == 2
        assert result[0]["date"] == "2024-06-23"
        assert result[1]["date"] == "2023-06-23"

    @patch("stock_data.data_provider.utils.http.requests.get")
    def test_returns_empty_on_detail_error(self, mock_get, monkeypatch):
        """``{"detail": ...}`` response (e.g. invalid token) → []."""
        _enable_token(self.fetcher, monkeypatch)
        mock_get.return_value = _make_json_response({"detail": "Licence证书无效"})
        assert self.fetcher.get_dividend("600519") == []

    @patch("stock_data.data_provider.utils.http.requests.get")
    def test_returns_empty_on_unexpected_response_type(self, mock_get, monkeypatch):
        """Response is neither list nor error dict → []."""
        _enable_token(self.fetcher, monkeypatch)
        mock_get.return_value = _make_json_response({"unexpected": "object"})
        assert self.fetcher.get_dividend("600519") == []

    @patch("stock_data.data_provider.utils.http.requests.get")
    def test_returns_empty_on_http_error(self, mock_get, monkeypatch):
        _enable_token(self.fetcher, monkeypatch)
        mock_get.side_effect = requests.ConnectionError("upstream down")
        assert self.fetcher.get_dividend("600519") == []


# ===========================================================================
# get_fund_flow_minute
# ===========================================================================


class TestGetFundFlowMinute:
    def setup_method(self):
        self.fetcher = ZhituFetcher()

    def test_returns_empty_when_token_missing(self, monkeypatch):
        self.fetcher._token = ""
        assert self.fetcher.get_fund_flow_minute("600519") == []

    @patch("stock_data.data_provider.utils.http.requests.get")
    def test_normalizes_main_super_large_mid_small(self, mock_get, monkeypatch):
        """主买-主卖 → super/large net；主力 = super+large net."""
        _enable_token(self.fetcher, monkeypatch)
        _patch_trade_calendar(monkeypatch, "2025-06-23")
        # Only the buy-side fields are populated in this mock — sell-side
        # defaults to 0 so the net = buy amount.
        mock_get.return_value = _make_json_response(
            [
                {
                    "t": "2025-06-23 09:35:00",
                    "zmbstdcje": 1000,
                    "zmsstdcje": 0,  # super: +1000
                    "zmbddcje": 200,
                    "zmsddcje": 0,  # large: +200
                    "zmbzdcje": 50,
                    "zmszdcje": 0,  # mid:   +50
                    "zmbxdcje": 10,
                    "zmsxdcje": 0,
                },  # small: +10
                {
                    "t": "2025-06-23 09:40:00",
                    "zmbstdcje": 0,
                    "zmsstdcje": 500,  # super: -500
                    "zmbddcje": 0,
                    "zmsddcje": 100,  # large: -100
                    "zmbzdcje": 30,
                    "zmszdcje": 0,  # mid:   +30
                    "zmbxdcje": 0,
                    "zmsxdcje": 5,
                },  # small: -5
            ]
        )
        result = self.fetcher.get_fund_flow_minute("600519")
        assert len(result) == 2
        # Row 1: all positive (主买 only).
        assert result[0]["time"] == "09:35:00"
        assert result[0]["super_net"] == 1000
        assert result[0]["large_net"] == 200
        assert result[0]["mid_net"] == 50
        assert result[0]["small_net"] == 10
        assert result[0]["main_net"] == 1200  # super+large
        assert "date" not in result[0]
        # Row 2: mixed.
        assert result[1]["super_net"] == -500
        assert result[1]["large_net"] == -100
        assert result[1]["mid_net"] == 30
        assert result[1]["small_net"] == -5
        assert result[1]["main_net"] == -600

    @patch("stock_data.data_provider.utils.http.requests.get")
    def test_uses_cached_trade_date(self, mock_get, monkeypatch):
        """When trade calendar has a cached date, that date is used as st/et."""
        _enable_token(self.fetcher, monkeypatch)
        _patch_trade_calendar(monkeypatch, "2025-06-23")
        mock_get.return_value = _make_json_response([])
        self.fetcher.get_fund_flow_minute("600519")

        # Verify query string carried the cached date in YYYYMMDD form.
        kwargs = mock_get.call_args.kwargs
        params = kwargs["params"]
        assert params["st"] == "20250623"
        assert params["et"] == "20250623"

    @patch("stock_data.data_provider.utils.http.requests.get")
    def test_skips_non_dict_rows(self, mock_get, monkeypatch):
        """Defensive: non-dict entries in the response list are skipped."""
        _enable_token(self.fetcher, monkeypatch)
        _patch_trade_calendar(monkeypatch, "2025-06-23")
        mock_get.return_value = _make_json_response(
            [
                {
                    "t": "2025-06-23 09:35:00",
                    "zmbstdcje": 100,
                    "zmsstdcje": 0,
                    "zmbddcje": 0,
                    "zmsddcje": 0,
                    "zmbzdcje": 0,
                    "zmszdcje": 0,
                    "zmbxdcje": 0,
                    "zmsxdcje": 0,
                },
                "garbage-row",  # non-dict — should be silently skipped
                None,  # also skipped
            ]
        )
        result = self.fetcher.get_fund_flow_minute("600519")
        assert len(result) == 1
        assert result[0]["time"] == "09:35:00"

    @patch("stock_data.data_provider.utils.http.requests.get")
    def test_returns_empty_on_detail_error(self, mock_get, monkeypatch):
        _enable_token(self.fetcher, monkeypatch)
        _patch_trade_calendar(monkeypatch, "2025-06-23")
        mock_get.return_value = _make_json_response({"detail": "rate limit"})
        assert self.fetcher.get_fund_flow_minute("600519") == []


# ===========================================================================
# get_fund_flow_120d
# ===========================================================================


class TestGetFundFlow120d:
    def setup_method(self):
        self.fetcher = ZhituFetcher()

    def test_returns_empty_when_token_missing(self, monkeypatch):
        self.fetcher._token = ""
        assert self.fetcher.get_fund_flow_120d("600519") == []

    @patch("stock_data.data_provider.utils.http.requests.get")
    def test_normalizes_daily_records(self, mock_get, monkeypatch):
        """Daily records expose ``date`` and zero out ``time``."""
        _enable_token(self.fetcher, monkeypatch)
        mock_get.return_value = _make_json_response(
            [
                {
                    "t": "2025-06-20",
                    "zmbstdcje": 1000,
                    "zmsstdcje": 200,
                    "zmbddcje": 500,
                    "zmsddcje": 100,
                    "zmbzdcje": 50,
                    "zmszdcje": 10,
                    "zmbxdcje": 5,
                    "zmsxdcje": 1,
                },
            ]
        )
        result = self.fetcher.get_fund_flow_120d("600519")
        assert len(result) == 1
        assert result[0]["date"] == "2025-06-20"
        assert result[0]["super_net"] == 800
        assert result[0]["large_net"] == 400
        assert result[0]["mid_net"] == 40
        assert result[0]["small_net"] == 4
        assert result[0]["main_net"] == 1200  # 800+400
        assert "time" not in result[0]

    @patch("stock_data.data_provider.utils.http.requests.get")
    def test_query_window_is_120_days(self, mock_get, monkeypatch):
        """``st`` should be ~120 days before ``et`` (today)."""
        _enable_token(self.fetcher, monkeypatch)
        mock_get.return_value = _make_json_response([])
        self.fetcher.get_fund_flow_120d("600519")

        from datetime import date, timedelta

        params = mock_get.call_args.kwargs["params"]
        et = params["et"]
        st = params["st"]
        # Parse YYYYMMDD back into date objects.
        et_date = date(int(et[:4]), int(et[4:6]), int(et[6:8]))
        st_date = date(int(st[:4]), int(st[4:6]), int(st[6:8]))
        assert et_date == date.today()
        assert et_date - st_date == timedelta(days=120)
        assert params["lt"] == "120"


# ===========================================================================
# get_holder_num_change
# ===========================================================================


class TestGetHolderNumChange:
    def setup_method(self):
        self.fetcher = ZhituFetcher()

    def test_returns_empty_when_token_missing(self, monkeypatch):
        self.fetcher._token = ""
        assert self.fetcher.get_holder_num_change("600519") == []

    @patch("stock_data.data_provider.utils.http.requests.get")
    def test_normalizes_full_payload(self, mock_get, monkeypatch):
        _enable_token(self.fetcher, monkeypatch)
        mock_get.return_value = _make_json_response(
            [
                {"jzrq": "2025-03-31", "gdhs": "517695", "bh": "减少28718"},
                {"jzrq": "2024-12-31", "gdhs": "546413", "bh": "减少21489"},
            ]
        )
        result = self.fetcher.get_holder_num_change("600519")
        assert len(result) == 2
        assert result[0]["date"] == "2025-03-31"
        assert result[0]["holder_num"] == 517695
        # P3-a4 (M17) fix: "减少N" means holder_num dropped by N → negative sign.
        # Live-network probe (scripts/probe_zhitu_holder_num.py, 2026-07-17)
        # verified across 105 rows that the intuitive semantic matches Zhitu's
        # actual gdhs delta; the previous "减少→positive" convention was inverted.
        assert result[0]["change_num"] == -28718
        # Zhitu doesn't expose change_ratio / avg_shares.
        assert result[0]["change_ratio"] == 0.0
        assert result[0]["avg_shares"] == 0.0
        assert result[1]["holder_num"] == 546413

    @patch("stock_data.data_provider.utils.http.requests.get")
    def test_sorts_newest_first(self, mock_get, monkeypatch):
        _enable_token(self.fetcher, monkeypatch)
        mock_get.return_value = _make_json_response(
            [
                {"jzrq": "2023-12-31", "gdhs": "100", "bh": "新增20"},
                {"jzrq": "2025-03-31", "gdhs": "200", "bh": "减少30"},
                {"jzrq": "2024-06-30", "gdhs": "150", "bh": "减少10"},
            ]
        )
        result = self.fetcher.get_holder_num_change("600519")
        assert [r["date"] for r in result] == ["2025-03-31", "2024-06-30", "2023-12-31"]

    @patch("stock_data.data_provider.utils.http.requests.get")
    def test_xinzeng_keeps_positive(self, mock_get, monkeypatch):
        """P3-a4 (M17): ``新增1702`` → change_num == +1702.

        Live probe confirmed: gdhs delta = +1702 when bh reads ``新增1702``.
        Renamed from the prior ``test_xinzeng_flips_sign_to_negative`` (which
        codified the inverted semantic that 105/105 live rows violated).
        """
        _enable_token(self.fetcher, monkeypatch)
        mock_get.return_value = _make_json_response(
            [
                {"jzrq": "2024-03-31", "gdhs": "1702", "bh": "新增1702"},
            ]
        )
        result = self.fetcher.get_holder_num_change("600519")
        assert result[0]["change_num"] == 1702

    @patch("stock_data.data_provider.utils.http.requests.get")
    def test_unknown_change_text_defaults_to_zero(self, mock_get, monkeypatch):
        """Free-form text with no ``新增`` / ``减少`` prefix → 0."""
        _enable_token(self.fetcher, monkeypatch)
        mock_get.return_value = _make_json_response(
            [
                {"jzrq": "2024-03-31", "gdhs": "500", "bh": "数据调整"},
            ]
        )
        result = self.fetcher.get_holder_num_change("600519")
        assert result[0]["change_num"] == 0

    @patch("stock_data.data_provider.utils.http.requests.get")
    def test_drops_rows_with_empty_date(self, mock_get, monkeypatch):
        """Empty ``jzrq`` would surface as ``date=""`` — filter out."""
        _enable_token(self.fetcher, monkeypatch)
        mock_get.return_value = _make_json_response(
            [
                {"jzrq": "", "gdhs": "100", "bh": "减少10"},
                {"jzrq": "2025-03-31", "gdhs": "200", "bh": "减少30"},
            ]
        )
        result = self.fetcher.get_holder_num_change("600519")
        assert len(result) == 1
        assert result[0]["date"] == "2025-03-31"

    @patch("stock_data.data_provider.utils.http.requests.get")
    def test_skips_non_dict_rows(self, mock_get, monkeypatch):
        _enable_token(self.fetcher, monkeypatch)
        mock_get.return_value = _make_json_response(
            [
                {"jzrq": "2025-03-31", "gdhs": "200", "bh": "减少30"},
                "garbage",
                None,
            ]
        )
        result = self.fetcher.get_holder_num_change("600519")
        assert len(result) == 1
        assert result[0]["holder_num"] == 200

    @patch("stock_data.data_provider.utils.http.requests.get")
    def test_page_size_caps_results(self, mock_get, monkeypatch):
        _enable_token(self.fetcher, monkeypatch)
        mock_get.return_value = _make_json_response(
            [
                {"jzrq": f"{y}-03-31", "gdhs": str(100 + y), "bh": "减少10"}
                for y in range(2020, 2025)
            ]
        )
        result = self.fetcher.get_holder_num_change("600519", page_size=2)
        assert len(result) == 2
        assert result[0]["date"] == "2024-03-31"
        assert result[1]["date"] == "2023-03-31"

    @patch("stock_data.data_provider.utils.http.requests.get")
    def test_returns_empty_on_detail_error(self, mock_get, monkeypatch):
        _enable_token(self.fetcher, monkeypatch)
        mock_get.return_value = _make_json_response({"detail": "rate limit"})
        assert self.fetcher.get_holder_num_change("600519") == []

    @patch("stock_data.data_provider.utils.http.requests.get")
    def test_returns_empty_on_http_error(self, mock_get, monkeypatch):
        _enable_token(self.fetcher, monkeypatch)
        mock_get.side_effect = requests.ConnectionError("upstream down")
        assert self.fetcher.get_holder_num_change("600519") == []
