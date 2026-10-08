"""EastMoneyFetcher.get_main_business_composition — spec rev2 §3.3.

Fixture: REAL 2026-10-08 capture of
``emweb.securities.eastmoney.com/PC_HSF10/BusinessAnalysis/PageAjax?code=SH600519``
newest-report-period slice (tests/fixtures/eastmoney_f10_zygcfx_600519.json).
The capture preserves the upstream typos ``MAIN_BUSINESS_RPOFIT`` /
``GROSS_RPOFIT_RATIO``, the ``" 00:00:00"`` date suffix, 元 amounts and
0..1 fraction ratios — exactly as measured.

Note the capture's newest period carries only MAINOP_TYPE 2/3 (product/
region) — 茅台 has no 行业行 in interim reports (review finding), which
pins the "category=industry → legitimate 200 + empty records" contract.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from stock_data.data_provider.base import DataFetchError
from stock_data.data_provider.fetchers.eastmoney.fetcher import EastMoneyFetcher

_FIX = json.loads(
    (Path(__file__).parent / "fixtures" / "eastmoney_f10_zygcfx_600519.json").read_text(
        encoding="utf-8"
    )
)


class FakeResp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeSession:
    def __init__(self, resp):
        self.resp = resp
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append({"url": url, "params": params})
        return self.resp


@pytest.fixture
def fetcher():
    f = EastMoneyFetcher.__new__(EastMoneyFetcher)  # skip __init__ network state
    return f


def _wire(f, resp):
    f._session = FakeSession(resp)
    return f


def _full_payload(rows):
    return {"zyfw": [], "jyps": [], "zygcfx": rows}


class TestHappyPath:
    def test_maps_units_and_typos(self, fetcher):
        f = _wire(fetcher, FakeResp(_full_payload(_FIX["zygcfx"])))
        out = f.get_main_business_composition("600519")
        assert out["report_date"] == "2026-06-30"
        assert out["requested_report_date_available"] is None  # user didn't ask
        maotai = next(r for r in out["records"] if r["item"] == "茅台酒")
        assert maotai["category"] == "product"
        assert maotai["rank"] == 1
        assert maotai["revenue_yi"] == pytest.approx(777.24437925)
        assert maotai["revenue_share_pct"] == pytest.approx(85.6909)
        assert maotai["cost_yi"] == pytest.approx(60.008842287)
        assert maotai["cost_share_pct"] == pytest.approx(63.3421)
        assert maotai["profit_yi"] == pytest.approx(717.23553697)
        assert maotai["profit_share_pct"] == pytest.approx(88.2974)
        assert maotai["gross_margin_pct"] == pytest.approx(92.2793)

    def test_outbound_code_is_f10_prefix_form(self, fetcher):
        f = _wire(fetcher, FakeResp(_full_payload(_FIX["zygcfx"])))
        f.get_main_business_composition("SH600519")
        call = f._session.calls[0]
        assert call["params"] == {"code": "SH600519"}
        # 深圳/北京 also map
        f.get_main_business_composition("000001")
        assert f._session.calls[-1]["params"] == {"code": "SZ000001"}
        f.get_main_business_composition("920002")
        assert f._session.calls[-1]["params"] == {"code": "BJ920002"}

    def test_available_report_dates_listed(self, fetcher):
        rows = [
            dict(_FIX["zygcfx"][0], REPORT_DATE="2025-12-31 00:00:00"),
            *_FIX["zygcfx"],
        ]
        f = _wire(fetcher, FakeResp(_full_payload(rows)))
        out = f.get_main_business_composition("600519")
        assert out["available_report_dates"] == ["2025-12-31", "2026-06-30"]

    def test_category_filter(self, fetcher):
        f = _wire(fetcher, FakeResp(_full_payload(_FIX["zygcfx"])))
        regions = f.get_main_business_composition("600519", category="region")["records"]
        assert regions and all(r["category"] == "region" for r in regions)

    def test_industry_legitimately_empty_on_interim(self, fetcher):
        # 茅台 interim window has NO MAINOP_TYPE=1 rows — this is a fact,
        # not an error: 200 + [] must be returned (never fall through to an
        # implicit date-1 report).
        f = _wire(fetcher, FakeResp(_full_payload(_FIX["zygcfx"])))
        out = f.get_main_business_composition("600519", category="industry")
        assert out["records"] == []
        assert out["report_date"] == "2026-06-30"

    def test_explicit_report_date_selection(self, fetcher):
        rows = [
            dict(
                _FIX["zygcfx"][0],
                REPORT_DATE="2025-12-31 00:00:00",
                ITEM_NAME="去年茅台",
                MAINOP_TYPE="2",
            ),
            *_FIX["zygcfx"],
        ]
        f = _wire(fetcher, FakeResp(_full_payload(rows)))
        out = f.get_main_business_composition("600519", report_date="2025-12-31")
        assert out["report_date"] == "2025-12-31"
        assert out["requested_report_date_available"] is True
        assert [r["item"] for r in out["records"]] == ["去年茅台"]

    def test_missing_report_date_flags_for_route_400(self, fetcher):
        f = _wire(fetcher, FakeResp(_full_payload(_FIX["zygcfx"])))
        out = f.get_main_business_composition("600519", report_date="2019-12-31")
        assert out["requested_report_date_available"] is False
        assert out["records"] == []
        assert out["report_date"] == "2019-12-31"


class TestEmptyAndFailure:
    def test_empty_zygcfx_is_authoritative_empty_200(self, fetcher):
        # defensive clause: 20 probe stocks never hit this; mock pins contract
        f = _wire(fetcher, FakeResp(_full_payload([])))
        out = f.get_main_business_composition("600519")
        assert out == {
            "report_date": None,
            "records": [],
            "available_report_dates": [],
            "requested_report_date_available": None,
        }

    def test_http_error_raises_datafetcherror_not_swallowed(self, fetcher):
        # unlike _datacenter_query's swallow-to-[] precedent, this helper MUST
        # raise so the single-source chain surfaces 503 (spec §4.3)
        f = _wire(fetcher, FakeResp(RuntimeError("connection reset")))
        with pytest.raises(DataFetchError):
            f.get_main_business_composition("600519")

    def test_non_dict_body_raises(self, fetcher):
        f = _wire(fetcher, FakeResp("not-json"))
        with pytest.raises(DataFetchError):
            f.get_main_business_composition("600519")

    def test_no_valueerror_leaks(self, fetcher):
        # upstream garbage rows degrade silently — never ValueError from a fetcher
        f = _wire(fetcher, FakeResp(_full_payload([{"REPORT_DATE": None, "ITEM_NAME": None}])))
        out = f.get_main_business_composition("600519")
        assert out["records"] == []


class TestReviewP1FollowUps:
    def test_non_200_status_raises_even_with_parseable_json(self, fetcher):
        """Review P1-2: spec §4.3 — 非 200 必须 raise。反爬场景会回 403+JSON
        错误体；若只靠 .json() 是否成功来判失败，会把封锁伪装成权威空集。"""
        f = _wire(fetcher, FakeResp(_full_payload(_FIX["zygcfx"]), status=429))
        with pytest.raises(DataFetchError):
            f.get_main_business_composition("600519")

    def test_industry_rows_map_from_real_annual_capture(self, fetcher):
        """Review P2-11③: MAINOP_TYPE='1' mapping was never data-covered
        (the newest-period slice has no 行业行). Use the REAL annual-period
        type-1 rows captured 2026-10-08."""
        rows = _FIX["industry_rows_real"] + _FIX["zygcfx"]
        f = _wire(fetcher, FakeResp(_full_payload(rows)))
        annual = _FIX["industry_rows_real"][-1]["REPORT_DATE"].split(" ")[0]
        out = f.get_main_business_composition("600519", category="industry", report_date=annual)
        assert out["requested_report_date_available"] is True
        assert out["records"], "real type-1 rows must map to category=industry"
        assert all(r["category"] == "industry" for r in out["records"])
        assert all(r["revenue_share_pct"] is not None for r in out["records"])

    def test_unknown_mainop_type_dropped_not_raised(self, fetcher):
        rows = [dict(_FIX["zygcfx"][0], MAINOP_TYPE="4")]
        f = _wire(fetcher, FakeResp(_full_payload(rows)))
        out = f.get_main_business_composition("600519")
        assert out["records"] == []
        # the period IS served (date known), only its breakdown is unmappable
        assert out["report_date"] == "2026-06-30"
