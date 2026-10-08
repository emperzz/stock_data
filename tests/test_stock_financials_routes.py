"""Route-layer contracts for /stocks/{code}/financials[, /history, /business-composition].

Spec rev2 §3 + §6. All upstream interaction is stubbed at the manager
boundary (monkeypatched get_manager, session-scoped `client` from conftest).
Pins: two-layer input validation (market gate BEFORE existence check),
the helper's new generic index-code fallback, coherent-empty → 200 +
nulls + source="", DataFetchError → 503, route-owned 400s for bad dates /
unavailable report_date, and cache fan-out (second identical call must not
re-enter the manager).
"""

from __future__ import annotations

import pytest

from stock_data.api.cache import (
    get_financial_history_cache,
    get_financial_snapshot_cache,
    get_main_business_cache,
)
from stock_data.api.routes import stocks as stocks_module
from stock_data.data_provider.base import DataFetchError

SNAP_OK = {
    "report_date": "2026-06-30",
    "pub_date": "2026-08-15",
    "eps": 13.8186,
    "roe_pct": 6.62,
    "gross_margin_pct": 89.48,
    "net_margin_pct": 48.59,
    "total_revenue_yi": 375.7516,
    "net_profit_attr_yi": 172.7437,
    "deduct_net_profit_attr_yi": 172.2422,
    "revenue_yoy_pct": -5.14,
    "net_profit_yoy_pct": -6.94,
    "revenue_qoq_pct": -31.75,
    "net_profit_qoq_pct": -36.49,
    "trade_date": "2026-09-30",
    "pe_ttm": 19.3209,
    "pe_lyr": 19.1129,
    "pb": 6.2621,
    "ps": 9.0821,
    "pcf": 37.5276,
    "market_cap_yi": 15733.777,
    "float_market_cap_yi": 15733.777,
    "total_share_wan_shares": 125008.1601,
    "float_share_wan_shares": 125008.1601,
    "turnover_ratio_pct": 0.3066,
}

HIST_OK = [
    {
        "report_date": "2026-03-31",
        "pub_date": "2026-04-25",
        "total_revenue_yi": 547.03,
        "net_profit_yi": 281.54,
        "net_profit_attr_yi": 272.43,
        "operating_profit_yi": 375.37,
        "deduct_net_profit_attr_yi": 272.4,
        "eps": 21.7545,
        "roe_pct": 10.57,
        "gross_margin_pct": 89.91,
        "net_margin_pct": 52.22,
        "revenue_yoy_pct": 6.54,
        "net_profit_yoy_pct": 1.37,
        "revenue_qoq_pct": 33.49,
        "net_profit_qoq_pct": 52.91,
    },
    {
        "report_date": "2026-06-30",
        "pub_date": "2026-08-15",
        "total_revenue_yi": 375.75,
        "net_profit_yi": 178.79,
        "net_profit_attr_yi": 172.74,
        "operating_profit_yi": 238.74,
        "deduct_net_profit_attr_yi": 172.24,
        "eps": 13.8186,
        "roe_pct": 6.62,
        "gross_margin_pct": 89.48,
        "net_margin_pct": 48.59,
        "revenue_yoy_pct": -5.14,
        "net_profit_yoy_pct": -6.94,
        "revenue_qoq_pct": -31.75,
        "net_profit_qoq_pct": -36.49,
    },
]

COMP_OK = {
    "report_date": "2026-06-30",
    "records": [
        {
            "category": "product",
            "item": "茅台酒",
            "rank": 1,
            "revenue_yi": 777.24,
            "revenue_share_pct": 85.69,
            "cost_yi": 60.01,
            "cost_share_pct": 63.34,
            "profit_yi": 717.24,
            "profit_share_pct": 88.3,
            "gross_margin_pct": 92.28,
        }
    ],
    "available_report_dates": ["2026-06-30"],
    "requested_report_date_available": None,
}


class FakeManager:
    def __init__(self):
        self.snapshot_result = (SNAP_OK, "ZzshareFetcher")
        self.history_result = (HIST_OK, "ZzshareFetcher")
        self.comp_result = (COMP_OK, "EastMoneyFetcher")
        self.raise_error = False
        self.calls: list[tuple] = []

    def _maybe_raise(self):
        if self.raise_error:
            raise DataFetchError("all fetchers down")

    def get_financial_snapshot(self, code):
        self.calls.append(("snapshot", code))
        self._maybe_raise()
        return self.snapshot_result

    def get_financial_history(self, code, start_date=None, end_date=None):
        self.calls.append(("history", code, start_date, end_date))
        self._maybe_raise()
        return self.history_result

    def get_main_business_composition(self, code, category=None, report_date=None):
        self.calls.append(("composition", code, category, report_date))
        self._maybe_raise()
        return self.comp_result


@pytest.fixture(autouse=True)
def _clear_financial_caches():
    caches = (
        get_financial_snapshot_cache(),
        get_financial_history_cache(),
        get_main_business_cache(),
    )
    for c in caches:
        c.clear()
    yield
    for c in caches:
        c.clear()


@pytest.fixture
def fm(monkeypatch):
    fake = FakeManager()
    monkeypatch.setattr(stocks_module, "get_manager", lambda: fake)
    names = {
        "600519": "贵州茅台",
        "920002": "倍益康",
        "HK00700": "腾讯控股",  # EXISTS in list — market gate must still 400 it
    }
    monkeypatch.setattr(
        stocks_module.stock_list,
        "get_stock_name",
        lambda code, manager=None: names.get(code, ""),
    )
    return fake


BASE = "/api/v1/stocks"


class TestSnapshotRoute:
    def test_happy_path(self, client, fm):
        r = client.get(f"{BASE}/600519/financials")
        assert r.status_code == 200
        j = r.json()
        assert j["code"] == "600519"
        assert j["name"] == "贵州茅台"
        assert j["source"] == "ZzshareFetcher"
        assert j["eps"] == pytest.approx(13.8186)
        assert j["pe_ttm"] == pytest.approx(19.3209)
        assert j["gross_margin_pct"] == pytest.approx(89.48)
        assert fm.calls == [("snapshot", "600519")]

    def test_coherent_empty_is_200_nulls_source_empty(self, client, fm):
        fm.snapshot_result = (None, "")
        r = client.get(f"{BASE}/920002/financials")
        assert r.status_code == 200
        j = r.json()
        assert j["source"] == ""
        assert j["eps"] is None
        assert j["pe_ttm"] is None

    def test_manager_failure_503(self, client, fm):
        fm.raise_error = True
        r = client.get(f"{BASE}/600519/financials")
        assert r.status_code == 503

    def test_hk_code_400_even_when_listed(self, client, fm):
        # the existence check would PASS (name stubbed); market gate must not
        r = client.get(f"{BASE}/HK00700/financials")
        assert r.status_code == 400
        assert fm.calls == []

    def test_unknown_code_400_not_found_message(self, client, fm):
        r = client.get(f"{BASE}/999999/financials")
        assert r.status_code == 400
        d = r.json()["detail"]
        assert d["error"] == "invalid_request"
        assert "Stock code 999999 was not found in the stock list." in d["message"]

    def test_index_code_400_generic_fallback(self, client, fm):
        # 000300 is index-only, absent from stock list → helper reaches its
        # new-kind fallback (previously KeyError → 500)
        r = client.get(f"{BASE}/000300/financials")
        assert r.status_code == 400
        d = r.json()["detail"]
        assert "Index 000300 is not supported via this endpoint." in d["message"]
        assert "does not serve index codes" in d["message"]

    def test_response_cached_per_code(self, client, fm):
        client.get(f"{BASE}/600519/financials")
        client.get(f"{BASE}/600519/financials")
        assert fm.calls == [("snapshot", "600519")]


class TestHistoryRoute:
    def test_happy_window_passthrough(self, client, fm):
        r = client.get(
            f"{BASE}/600519/financials/history?start_date=2026-01-01&end_date=2026-10-08"
        )
        assert r.status_code == 200
        j = r.json()
        assert j["basis"] == "single_quarter"
        assert j["total"] == 2
        assert [x["report_date"] for x in j["records"]] == ["2026-03-31", "2026-06-30"]
        assert fm.calls == [("history", "600519", "2026-01-01", "2026-10-08")]

    def test_default_window_no_params(self, client, fm):
        r = client.get(f"{BASE}/600519/financials/history")
        assert r.status_code == 200
        assert fm.calls[-1] == ("history", "600519", None, None)

    def test_yyyymmdd_normalized_before_forward(self, client, fm):
        r = client.get(f"{BASE}/600519/financials/history?start_date=20260101")
        assert r.status_code == 200
        assert fm.calls[-1] == ("history", "600519", "2026-01-01", None)

    def test_bad_date_format_400(self, client, fm):
        for bad in ("2026-13-45", "202601", "not-a-date", "2026/01/01"):
            r = client.get(f"{BASE}/600519/financials/history?start_date={bad}")
            assert r.status_code == 400, bad
        assert fm.calls == []  # validation must happen BEFORE the manager


class TestCompositionRoute:
    def test_happy_passthrough(self, client, fm):
        r = client.get(f"{BASE}/600519/business-composition?category=product")
        assert r.status_code == 200
        j = r.json()
        assert j["report_date"] == "2026-06-30"
        assert j["total"] == 1
        assert j["records"][0]["item"] == "茅台酒"
        assert j["records"][0]["revenue_share_pct"] == pytest.approx(85.69)
        assert "available_report_dates" not in j  # internal field must not leak
        assert fm.calls == [("composition", "600519", "product", None)]

    def test_unavailable_report_date_400_with_hint(self, client, fm):
        comp = dict(COMP_OK)
        comp.update(report_date="2019-12-31", records=[], requested_report_date_available=False)
        comp["available_report_dates"] = ["2017-03-31", "2026-06-30"]
        fm.comp_result = (comp, "EastMoneyFetcher")
        r = client.get(f"{BASE}/600519/business-composition?report_date=2019-12-31")
        assert r.status_code == 400
        d = r.json()["detail"]
        assert d["error"] == "invalid_request"
        assert "2017-03-31" in d["message"] and "2026-06-30" in d["message"]

    def test_bad_category_400(self, client, fm):
        r = client.get(f"{BASE}/600519/business-composition?category=galaxy")
        assert r.status_code == 400
        assert fm.calls == []

    def test_industry_legitimate_empty_200(self, client, fm):
        comp = dict(COMP_OK, records=[])
        fm.comp_result = (comp, "EastMoneyFetcher")
        r = client.get(f"{BASE}/600519/business-composition?category=industry")
        assert r.status_code == 200
        assert r.json()["records"] == []

    def test_upstream_failure_503(self, client, fm):
        fm.raise_error = True
        r = client.get(f"{BASE}/600519/business-composition")
        assert r.status_code == 503
