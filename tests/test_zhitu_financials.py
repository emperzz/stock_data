"""ZhituFetcher financial backup chain — spec rev2 §2.2 derive pipeline.

Fixtures are the REAL 2026-10-08 probe responses of
``/hs/fin/income/600519.SH`` (CUMULATIVE report-period values, default
ASC order, incl. the genuine 2009-03-31 restatement duplicate with two
different ``plrq``).

The pipeline's algebra is pinned by cross-source checks measured the same
day: zhitu 2026 H1 44,516,880,421.86 − Q1 27,242,512,886.45 =
17,274,367,535.41 == zzshare single-quarter np_parent_company_owners
(digit-for-digit).
"""

from __future__ import annotations

import pytest

from stock_data.data_provider.fetchers.zhitu_fetcher import ZhituFetcher

# --- real cumulative rows (元) ---------------------------------------------

R_2025_Q1 = {
    "jzrq": "2025-03-31",
    "plrq": "2025-04-30",
    "yyzsr": 51443450583.77,
    "yysr": 50600957885.78,
    "yycb": 4061430550.43,
    "jlr": 27774636011.61,
    "gsmgsyzzdjlr": 26847474238.76,
    "jlrhfcjcx": 26849883702.9,
    "jbmgsy": 21.38,
    "yylr": 37036598228.0,
}
R_2025_Q2 = {
    "jzrq": "2025-06-30",
    "plrq": "2025-08-13",
    "yyzsr": 91093762553.97,
    "yysr": 89389354416.84,
    "yycb": 7777491083.93,
    "jlr": 46986681449.24,
    "gsmgsyzzdjlr": 45402962298.1,
    "jlrhfcjcx": 45390247623.82,
    "jbmgsy": 36.18,
    "yylr": 62768973374.37,
}
R_2025_Q3 = {
    "jzrq": "2025-09-30",
    "plrq": "2025-10-30",
    "yyzsr": 130903889634.88,
    "yysr": 128453707655.86,
    "yycb": 11183972073.77,
    "jlr": 66898804746.17,
    "gsmgsyzzdjlr": 64626746712.18,
    "jlrhfcjcx": 64680616431.2,
    "jbmgsy": 51.53,
    "yylr": 89489694566.48,
}
R_2025_Q4 = {
    "jzrq": "2025-12-31",
    "plrq": "2026-04-17",
    "yyzsr": 172054171890.91,
    "yysr": 168838102514.79,
    "yycb": 14892277570.91,
    "jlr": 85310324833.67,
    "gsmgsyzzdjlr": 82320067101.68,
    "jlrhfcjcx": 82293107655.25,
    "jbmgsy": 65.66,
    "yylr": 114808950164.24,
}
R_2026_Q1 = {
    "jzrq": "2026-03-31",
    "plrq": "2026-04-25",
    "yyzsr": 54702912385.23,
    "yysr": 53909252220.51,
    "yycb": 5520729200.32,
    "jlr": 28153831489.89,
    "gsmgsyzzdjlr": 27242512886.45,
    "jlrhfcjcx": 27239985194.41,
    "jbmgsy": 21.76,
    "yylr": 37537008686.42,
}
R_2026_Q2 = {
    "jzrq": "2026-06-30",
    "plrq": "2026-08-15",
    "yyzsr": 92278072083.21,
    "yysr": 90703260964.48,
    "yycb": 9473762565.88,
    "jlr": 46033330566.78,
    "gsmgsyzzdjlr": 44516880421.86,
    "jlrhfcjcx": 44464207646.01,
    "jbmgsy": 35.57,
    "yylr": 61411291686.27,
}
R_2009_A = {
    "jzrq": "2009-03-31",
    "plrq": "2009-04-21",
    "yyzsr": 2512537167.2,
    "yysr": 2512537167.2,
    "yycb": 251448334.92,
    "jlr": 1278840567.82,
    "gsmgsyzzdjlr": 1217009471.66,
    "jlrhfcjcx": 1216891506.66,
    "jbmgsy": 1.29,
    "yylr": 1704811540.33,
}
R_2009_B = {
    "jzrq": "2009-03-31",
    "plrq": "2010-04-26",
    "yyzsr": 2512537167.2,
    "yysr": 2512537167.2,
    "yycb": 251448334.92,
    "jlr": 1278840567.82,
    "gsmgsyzzdjlr": 1217009471.66,
    "jlrhfcjcx": 1216891506.66,
    "jbmgsy": 1.29,
    "yylr": 1704811540.33,
}

SERIES = [R_2025_Q1, R_2025_Q2, R_2025_Q3, R_2025_Q4, R_2026_Q1, R_2026_Q2]


def _sq(rows):
    return ZhituFetcher._build_single_quarter_series(rows)


class TestPipeline:
    def test_q1_is_identity_and_later_quarters_are_deltas(self):
        recs = {r["report_date"]: r for r in _sq(SERIES)}
        q1 = recs["2026-03-31"]
        assert q1["total_revenue_yi"] == pytest.approx(547.0291238523)
        assert q1["net_profit_attr_yi"] == pytest.approx(272.4251288645)
        q2 = recs["2026-06-30"]
        # THE cross-source pinned value: 44,516,880,421.86 − 27,242,512,886.45
        assert q2["net_profit_attr_yi"] == pytest.approx(172.7436753541, abs=1e-6)
        assert q2["total_revenue_yi"] == pytest.approx(375.7515969798)
        assert q2["net_profit_yi"] == pytest.approx(178.7949907689)
        assert q2["deduct_net_profit_attr_yi"] == pytest.approx(172.2422245160)
        assert q2["operating_profit_yi"] == pytest.approx(238.7428299985)
        assert q2["eps"] == pytest.approx(35.57 - 21.76)  # cumulative EPS is additive
        assert q2["pub_date"] == "2026-08-15"

    def test_single_quarter_margins_derived(self):
        recs = {r["report_date"]: r for r in _sq(SERIES)}
        q2 = recs["2026-06-30"]
        # (Δyyzsr − Δyycb) / Δyyzsr × 100 — matches zzshare gross_profit_margin 89.48 within 0.01
        assert q2["gross_margin_pct"] == pytest.approx(89.4804, abs=0.02)
        assert q2["net_margin_pct"] == pytest.approx(47.583, abs=0.05)

    def test_yoy_and_qoq_from_derived_quarters(self):
        recs = {r["report_date"]: r for r in _sq(SERIES)}
        q2 = recs["2026-06-30"]
        # yoy vs 2025Q2 derived single-quarter: (375.7516 − 396.5031) / 396.5031
        assert q2["revenue_yoy_pct"] == pytest.approx(-5.2336, abs=0.05)
        assert q2["net_profit_yoy_pct"] == pytest.approx(-6.905, abs=0.05)
        assert q2["revenue_qoq_pct"] == pytest.approx(-31.311, abs=0.05)
        assert q2["net_profit_qoq_pct"] == pytest.approx(-36.59, abs=0.2)
        q1 = recs["2026-03-31"]
        # Q1 qoq compares against last year's Q4 derived quarter (spec §3.2: 保留)
        assert q1["revenue_qoq_pct"] is not None

    def test_roe_always_null(self):
        # weighted ROE is not additive — no fake conversion
        assert all(r["roe_pct"] is None for r in _sq(SERIES))

    def test_duplicate_report_dates_keep_latest_disclosure(self):
        recs = _sq([R_2009_A, R_2009_B, R_2026_Q1, R_2026_Q2])
        d_2009 = [r for r in recs if r["report_date"] == "2009-03-31"]
        assert len(d_2009) == 1
        assert d_2009[0]["pub_date"] == "2010-04-26"  # max plrq (restatement wins)

    def test_out_of_order_input_normalized(self):
        # upstream DESC (with st/et) must produce the same records as ASC input
        asc = _sq(SERIES)
        desc = _sq(list(reversed(SERIES)))
        assert asc == desc

    def test_placeholder_strings_cleaned_to_none(self):
        row = dict(R_2026_Q2, jlrhfcjcx="--", jbmgsy="-")
        recs = {r["report_date"]: r for r in _sq([R_2026_Q1, row])}
        assert recs["2026-06-30"]["deduct_net_profit_attr_yi"] is None
        assert recs["2026-06-30"]["eps"] is None

    def test_missing_previous_quarter_nulls_deltas_for_that_period(self):
        # only a 06-30 row present: no 03-31 predecessor → deltas None,
        # but the record still exists with dates
        recs = _sq([R_2026_Q2])
        assert len(recs) == 1
        assert recs[0]["report_date"] == "2026-06-30"
        assert recs[0]["total_revenue_yi"] is None
        assert recs[0]["net_profit_yi"] is None


class TestPublicMethods:
    def _fetcher(self, monkeypatch, payload):
        f = ZhituFetcher()
        monkeypatch.setattr(f, "_fetch_json", lambda path, **kw: payload, raising=True)
        return f

    def test_history_window_and_default_cap(self, monkeypatch):
        f = self._fetcher(monkeypatch, SERIES)
        recs = f.get_financial_history("600519")
        assert len(recs) == 6 and recs[0]["report_date"] == "2025-03-31"
        win = f.get_financial_history("600519", start_date="2026-01-01", end_date="2026-06-30")
        assert [r["report_date"] for r in win] == ["2026-03-31", "2026-06-30"]

    def test_history_default_last_12(self, monkeypatch):
        # 16 quarters available — default window must keep only the LAST 12
        rows = []
        for y in (2021, 2022, 2023, 2024):
            for q, md in ((1, "03-31"), (2, "06-30"), (3, "09-30"), (4, "12-31")):
                rows.append(
                    {
                        "jzrq": f"{y}-{md}",
                        "plrq": f"{y}-{md}",
                        "yyzsr": 1000.0 * (q + y),
                        "yysr": 900.0,
                        "yycb": 100.0,
                        "jlr": 500.0,
                        "gsmgsyzzdjlr": 450.0,
                        "jlrhfcjcx": 440.0,
                        "jbmgsy": 5.0,
                        "yylr": 600.0,
                    }
                )
        f = self._fetcher(monkeypatch, rows)
        recs = f.get_financial_history("600519")
        assert len(recs) == 12
        assert recs[0]["report_date"] == "2022-03-31"
        assert recs[-1]["report_date"] == "2024-12-31"

    def test_history_empty_or_none_returns_list(self, monkeypatch):
        assert self._fetcher(monkeypatch, None).get_financial_history("920002") == []
        assert self._fetcher(monkeypatch, []).get_financial_history("920002") == []

    def test_snapshot_from_last_record(self, monkeypatch):
        f = self._fetcher(monkeypatch, SERIES)
        snap = f.get_financial_snapshot("SH600519")
        assert snap["report_date"] == "2026-06-30"
        assert snap["net_profit_attr_yi"] == pytest.approx(172.7436753541, abs=1e-6)
        assert snap["eps"] == pytest.approx(13.81)
        # backup chain: ROE and the entire valuation block are honest nulls
        assert snap["roe_pct"] is None
        assert snap["pe_ttm"] is None
        assert snap["market_cap_yi"] is None
        assert "trade_date" in snap

    def test_snapshot_none_when_no_rows(self, monkeypatch):
        # P0 guard: must be None, never {} (_is_meaningful short-circuit)
        assert self._fetcher(monkeypatch, None).get_financial_snapshot("920002") is None

    def test_no_valueerror_ever_raised_from_public_methods(self, monkeypatch):
        # fetchers speak only DataFetchError/returns (spec §6) — garbage rows
        # must degrade to None/[] not crash the failover chain semantics
        f = self._fetcher(monkeypatch, [{"jzrq": None, "plrq": None}])
        assert f.get_financial_history("600519") == []
        assert f.get_financial_snapshot("600519") is None
