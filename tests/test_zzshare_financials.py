"""ZzshareFetcher.get_financial_snapshot / get_financial_history (spec 2026-10-08 rev2 §3.1/§3.2).

Fixtures mirror the REAL 2026-10-08 probe responses for 600519.SH
(docs/zzshare/11-fundamentals.md §探针实测记录): single-quarter indicator
(eps 13.8186 / roe 6.62 / gross 89.48), daily valuation (pe_ttm 19.3209 /
market_cap in 亿元), and income absolute amounts in 元. The fake API records
every call so we can pin the `codes=`-silently-ignored trap guard: the
fetcher must only ever use finance_latest / finance_stock, never the base
finance_indicator(date, codes=...) form.
"""

from __future__ import annotations

import pytest

from stock_data.data_provider.base import DataFetchError
from stock_data.data_provider.fetchers.zzshare_fetcher import ZzshareFetcher

# --- real probe rows (2026-10-08) -----------------------------------------

INDICATOR_Q2_ROW = {
    "code": "600519.SH",
    "statDate": "2026-06-30",
    "pubDate": "2026-08-15",
    "eps": 13.8186,
    "adjusted_profit": 17224220000.0,
    "operating_profit": 23821340000.0,
    "roe": 6.62,
    "inc_revenue_year_on_year": -5.14,
    "inc_net_profit_year_on_year": -6.94,
    "inc_revenue_annual": -31.75,
    "inc_net_profit_annual": -36.49,
    "net_profit_margin": 48.59,
    "gross_profit_margin": 89.48,
    # real probe: these ratio-share fields are None upstream
    "operating_profit_to_total_profit": None,
    "net_profit_to_total_profit": None,
    "adjusted_profit_to_total_profit": None,
    "net_profit_to_total_revenue": 47.58,
    "adjusted_profit_to_total_revenue": None,
}
INDICATOR_Q1_ROW = {
    "code": "600519.SH",
    "statDate": "2026-03-31",
    "pubDate": "2026-04-25",
    "eps": 21.7545,
    "adjusted_profit": 27239990000.0,
    "operating_profit": 37510690000.0,
    "roe": 10.57,
    "inc_revenue_year_on_year": 6.54,
    "inc_net_profit_year_on_year": 1.37,
    "inc_revenue_annual": 33.49,
    "inc_net_profit_annual": 52.91,
    "net_profit_margin": 52.22,
    "gross_profit_margin": 89.91,
    "operating_profit_to_total_profit": None,
    "net_profit_to_total_profit": None,
    "adjusted_profit_to_total_profit": None,
    "net_profit_to_total_revenue": 51.47,
    "adjusted_profit_to_total_revenue": None,
}
INCOME_Q2_ROW = {
    "code": "600519.SH",
    "statDate": "2026-06-30",
    "pubDate": "2026-08-15",
    "total_operating_revenue": 37575160000.0,
    "operating_revenue": 36794010000.0,
    "operating_profit": 23874280000.0,
    "net_profit": 17879500000.0,
    "np_parent_company_owners": 17274370000.0,
    "deduct_parent_net_profit": None,  # real probe: upstream never fills it
    "minority_interest": None,
}
INCOME_Q1_ROW = {
    "code": "600519.SH",
    "statDate": "2026-03-31",
    "pubDate": "2026-04-25",
    "total_operating_revenue": 54702910000.0,
    "operating_revenue": 53909250000.0,
    "operating_profit": 37537010000.0,
    "net_profit": 28153830000.0,
    "np_parent_company_owners": 27242510000.0,
    "deduct_parent_net_profit": None,
    "minority_interest": None,
}
VALUATION_ROW = {
    "code": "600519.SH",
    "trade_date": "2026-09-30",
    "capitalization": 125008.1601,
    "circulating_cap": 125008.1601,
    "market_cap": 15733.777,
    "circulating_market_cap": 15733.777,
    "turnover_ratio": 0.3066,
    "pe_ratio": 19.3209,
    "pe_ratio_lyr": 19.1129,
    "pb_ratio": 6.2621,
    "ps_ratio": 9.0821,
    "pcf_ratio": 37.5276,
}


class FakeApi:
    """Stands in for zzshare.client.DataApi via the raw ``query()`` channel.

    Mirrors the real SDK semantics verified 2026-10-08 (core.py::_query):
    SUCCESS returns the envelope ``data`` — a list of dicts, possibly empty
    for a true no-data answer (e.g. BJ); FAILURE (network / non-200 /
    business code) collapses to ``None``. Only 401/429 raise. Paths listed
    in ``fail_paths`` simulate that swallow-to-None outage channel.
    """

    def __init__(self, frames: dict, fail_paths=()):
        # frames keyed by (kind, table): ("latest","indicator") / ("stock","income")
        self.frames = frames
        self.fail_paths = set(fail_paths)
        self.calls: list[tuple] = []

    def query(self, api_name, params=None):
        params = dict(params or {})
        self.calls.append((api_name, params))
        if api_name in self.fail_paths:
            return None
        parts = api_name.split("/")
        # v3/fundamentals/{table}/latest  |  v3/fundamentals/{table}/stock/{code}
        table, kind = parts[2], parts[3]
        rows = list(self.frames.get((kind, table), []))
        if kind == "stock":
            if params.get("start_date"):
                rows = [r for r in rows if str(r.get("statDate", "")) >= params["start_date"]]
            if params.get("end_date"):
                rows = [r for r in rows if str(r.get("statDate", "")) <= params["end_date"]]
            if params.get("limit") is not None:
                rows = rows[: int(params["limit"])]
        return rows

    def __getattr__(self, name):  # shortcuts must NOT be used anymore
        raise AssertionError(f"ZzshareFetcher must not call shortcut {name!r} — raw query() only")


@pytest.fixture
def fetcher():
    saved = (ZzshareFetcher._init_attempted, ZzshareFetcher._init_ok, ZzshareFetcher._api)
    ZzshareFetcher._init_attempted = True
    ZzshareFetcher._init_ok = True
    ZzshareFetcher._api = None
    yield ZzshareFetcher
    ZzshareFetcher._init_attempted, ZzshareFetcher._init_ok, ZzshareFetcher._api = saved


def _wire(fetcher_cls, frames):
    fetcher_cls._api = FakeApi(frames)
    return fetcher_cls()


class TestSnapshot:
    def test_maps_single_quarter_profit_and_valuation(self, fetcher):
        f = _wire(
            fetcher,
            {
                ("latest", "indicator"): [INDICATOR_Q2_ROW],
                ("latest", "valuation"): [VALUATION_ROW],
                ("stock", "income"): [INCOME_Q2_ROW],
            },
        )
        snap = f.get_financial_snapshot("600519")
        assert snap is not None
        assert snap["report_date"] == "2026-06-30"
        assert snap["pub_date"] == "2026-08-15"
        assert snap["eps"] == pytest.approx(13.8186)
        assert snap["roe_pct"] == pytest.approx(6.62)
        assert snap["gross_margin_pct"] == pytest.approx(89.48)
        assert snap["net_margin_pct"] == pytest.approx(48.59)
        assert snap["revenue_yoy_pct"] == pytest.approx(-5.14)
        assert snap["net_profit_yoy_pct"] == pytest.approx(-6.94)
        assert snap["revenue_qoq_pct"] == pytest.approx(-31.75)
        assert snap["net_profit_qoq_pct"] == pytest.approx(-36.49)
        # 元 → 亿元
        assert snap["total_revenue_yi"] == pytest.approx(375.7516)
        assert snap["net_profit_attr_yi"] == pytest.approx(172.7437)
        assert snap["deduct_net_profit_attr_yi"] == pytest.approx(172.2422)
        # valuation block (already 亿/万/百分数 upstream — pass-through values)
        assert snap["trade_date"] == "2026-09-30"
        assert snap["pe_ttm"] == pytest.approx(19.3209)
        assert snap["pe_lyr"] == pytest.approx(19.1129)
        assert snap["pb"] == pytest.approx(6.2621)
        assert snap["ps"] == pytest.approx(9.0821)
        assert snap["pcf"] == pytest.approx(37.5276)
        assert snap["market_cap_yi"] == pytest.approx(15733.777)
        assert snap["total_share_wan_shares"] == pytest.approx(125008.1601)
        assert snap["turnover_ratio_pct"] == pytest.approx(0.3066)

    def test_only_latest_and_stock_paths_are_called(self, fetcher):
        f = _wire(
            fetcher,
            {
                ("latest", "indicator"): [INDICATOR_Q2_ROW],
                ("latest", "valuation"): [VALUATION_ROW],
                ("stock", "income"): [INCOME_Q2_ROW],
            },
        )
        f.get_financial_snapshot("SH600519")
        api = fetcher._api
        # spec §7.1 pins BOTH the 3-call count and their order
        assert [c[0] for c in api.calls] == [
            "v3/fundamentals/indicator/latest",
            "v3/fundamentals/valuation/latest",
            "v3/fundamentals/income/stock/600519.SH",
        ]
        # outbound ts_code suffix on the stock leg; latest legs filter via codes=
        assert api.calls[0][1] == {"codes": "600519.SH"}
        assert api.calls[2][1] == {"limit": 1}
        # the base table form (v3/fundamentals/{table}/{date}) silently ignores
        # codes= and returns the whole market — must never be reachable
        assert not any(p.count("/") == 3 and p.split("/")[3].startswith("20") for p, _ in api.calls)

    def test_all_empty_returns_none_not_empty_dict(self, fetcher):
        """P0 guard: {} would short-circuit manager failover (_is_meaningful).
        Empty LIST from upstream = legitimate no-data (BJ), not an outage."""
        f = _wire(fetcher, {})
        assert f.get_financial_snapshot("920002") is None

    def test_valuation_empty_keeps_profit_block(self, fetcher):
        f = _wire(
            fetcher,
            {
                ("latest", "indicator"): [INDICATOR_Q2_ROW],
                ("stock", "income"): [INCOME_Q2_ROW],
            },
        )
        snap = f.get_financial_snapshot("600519")
        assert snap is not None
        assert snap["eps"] == pytest.approx(13.8186)
        assert snap["pe_ttm"] is None
        assert snap["market_cap_yi"] is None

    def test_income_only_rows_still_snapshots(self, fetcher):
        """Latest-disclosure skew: latest indicator/valuation windows empty but
        the income row exists — absolutes are usable data, not a None answer."""
        f = _wire(
            fetcher,
            {
                ("latest", "indicator"): [],
                ("latest", "valuation"): [],
                ("stock", "income"): [INCOME_Q2_ROW],
            },
        )
        snap = f.get_financial_snapshot("600519")
        assert snap is not None
        assert snap["total_revenue_yi"] == pytest.approx(375.7516)
        assert snap["eps"] is None

    def test_period_mismatch_nulls_cross_table_absolutes(self, fetcher):
        """report_date anchors on indicator; income limit=1 may be an OLDER
        period during disclosure skew. Mixing periods into one snapshot would
        mislabel them, so absolutes go null and only same-period (indicator)
        fields survive."""
        older = dict(INCOME_Q2_ROW, statDate="2025-12-31")
        f = _wire(
            fetcher,
            {
                ("latest", "indicator"): [INDICATOR_Q2_ROW],
                ("latest", "valuation"): [VALUATION_ROW],
                ("stock", "income"): [older],
            },
        )
        snap = f.get_financial_snapshot("600519")
        assert snap["report_date"] == "2026-06-30"
        assert snap["total_revenue_yi"] is None
        assert snap["net_profit_attr_yi"] is None
        assert snap["deduct_net_profit_attr_yi"] == pytest.approx(172.2422)
        assert snap["eps"] == pytest.approx(13.8186)

    def test_sdk_error_raises_datafetcherror(self, fetcher):
        class Boom(FakeApi):
            def query(self, api_name, params=None):
                raise RuntimeError("network down")

        fetcher._api = Boom({})
        f = fetcher()
        with pytest.raises(DataFetchError):
            f.get_financial_snapshot("600519")

    def test_sdk_none_means_outage_not_empty_answer(self, fetcher):
        """SDK ``_query`` swallows network / non-200 / business-code failures
        into ``None`` (only 401/429 raise) — verified 2026-10-08 in
        ``zzshare/core.py:133-161``. The fetcher MUST read ``None`` as a
        failure so the chain falls through / surfaces 503, never as the
        honest 200 empty contract (which would also be cached 24h)."""
        fetcher._api = FakeApi(
            {("latest", "indicator"): [INDICATOR_Q2_ROW]},
            fail_paths=["v3/fundamentals/valuation/latest"],
        )
        with pytest.raises(DataFetchError):
            fetcher().get_financial_snapshot("600519")

    def test_history_none_upstream_raises_too(self, fetcher):
        fetcher._api = FakeApi(
            {("stock", "indicator"): [INDICATOR_Q2_ROW]},
            fail_paths=["v3/fundamentals/income/stock/600519.SH"],
        )
        with pytest.raises(DataFetchError):
            fetcher().get_financial_history("600519")


class TestHistory:
    def test_returns_ascending_joined_records(self, fetcher):
        # upstream returns DESCENDING (probe fact) — fetcher must re-sort ascending
        f = _wire(
            fetcher,
            {
                ("stock", "income"): [INCOME_Q2_ROW, INCOME_Q1_ROW],
                ("stock", "indicator"): [INDICATOR_Q2_ROW, INDICATOR_Q1_ROW],
            },
        )
        recs = f.get_financial_history("600519")
        assert [r["report_date"] for r in recs] == ["2026-03-31", "2026-06-30"]
        q1 = recs[0]
        assert q1["pub_date"] == "2026-04-25"
        assert q1["total_revenue_yi"] == pytest.approx(547.0291)
        assert q1["net_profit_yi"] == pytest.approx(281.5383)
        assert q1["net_profit_attr_yi"] == pytest.approx(272.4251)
        assert q1["operating_profit_yi"] == pytest.approx(375.3701)
        # deduct comes from indicator.adjusted_profit, NOT income.deduct_parent_net_profit (always None)
        assert q1["deduct_net_profit_attr_yi"] == pytest.approx(272.3999)
        assert q1["eps"] == pytest.approx(21.7545)
        assert q1["roe_pct"] == pytest.approx(10.57)
        assert q1["gross_margin_pct"] == pytest.approx(89.91)
        assert q1["net_margin_pct"] == pytest.approx(52.22)
        assert q1["revenue_yoy_pct"] == pytest.approx(6.54)
        assert q1["revenue_qoq_pct"] == pytest.approx(33.49)

    def test_default_calls_limit_12(self, fetcher):
        f = _wire(
            fetcher,
            {
                ("stock", "income"): [INCOME_Q2_ROW],
                ("stock", "indicator"): [INDICATOR_Q2_ROW],
            },
        )
        f.get_financial_history("600519")
        stock_calls = [c for c in fetcher._api.calls if "/stock/" in c[0]]
        assert len(stock_calls) == 2
        assert all(c[1].get("limit") == 12 for c in stock_calls)

    def test_start_end_window_passed_through(self, fetcher):
        f = _wire(
            fetcher,
            {
                ("stock", "income"): [INCOME_Q2_ROW, INCOME_Q1_ROW],
                ("stock", "indicator"): [INDICATOR_Q2_ROW, INDICATOR_Q1_ROW],
            },
        )
        recs = f.get_financial_history("600519", start_date="2026-04-01", end_date="2026-10-08")
        assert [r["report_date"] for r in recs] == ["2026-06-30"]
        stock_calls = [c for c in fetcher._api.calls if "/stock/" in c[0]]
        assert all(c[1].get("start_date") == "2026-04-01" for c in stock_calls)
        assert all(c[1].get("end_date") == "2026-10-08" for c in stock_calls)
        # window given → no 12-cap (user asked for a span, not a count)
        assert all(c[1].get("limit") is None for c in stock_calls)

    def test_empty_returns_empty_list(self, fetcher):
        f = _wire(fetcher, {})
        assert f.get_financial_history("920002") == []

    def test_indicator_missing_row_gives_null_ratio_fields(self, fetcher):
        """income has a period the indicator join lacks → ratios null, absolutes kept."""
        f = _wire(
            fetcher,
            {
                ("stock", "income"): [INCOME_Q2_ROW],
                ("stock", "indicator"): [INDICATOR_Q1_ROW],
            },
        )
        recs = f.get_financial_history("600519")
        assert len(recs) == 1
        assert recs[0]["report_date"] == "2026-06-30"
        assert recs[0]["total_revenue_yi"] == pytest.approx(375.7516)
        assert recs[0]["eps"] is None
        assert recs[0]["gross_margin_pct"] is None
