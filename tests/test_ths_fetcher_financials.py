"""ThsFetcher's three financial capabilities — parsers, derivation, orchestration.

Everything is pinned against REAL 2026-10-08 upstream captures under
``tests/fixtures/`` (see the fixture notes in ``conftest``-adjacent docstrings
below): the two finance JSONs for 300519, its GBK overview page valuation
table, and one ``main_business_structure`` payload.

Two layers are covered in one file, mirroring ``test_zhitu_financials.py``:
the pure module-level helpers in ``ths_fetcher`` (parsing / unit conversion /
derivation) and the three public ``ThsFetcher`` methods that orchestrate the
upstream calls and translate failures into the manager's failover language
(``DataFetchError``, or ``None``/``[]`` — never a bare ``ValueError``).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from stock_data.data_provider.base import DataFetchError
from stock_data.data_provider.fetchers.ths_fetcher import (
    ThsFetcher,
    _build_ths_business_composition,
    _build_ths_history,
    _build_ths_snapshot,
    _parse_ths_amount,
    _parse_ths_overview_valuation,
    _parse_ths_pct,
    _ths_market_id,
    _unwrap_ths_flash,
)

_FIX = Path(__file__).parent / "fixtures"


def _bytes(name: str, encoding: str = "utf-8") -> bytes:
    """Raw fixture body as the transport would deliver it."""
    return (_FIX / name).read_text(encoding=encoding).encode(encoding)


def _flash(name: str) -> dict:
    """Unescape the ``flashData`` envelope of a stored finance-JSON fixture."""
    raw = json.loads((_FIX / name).read_text(encoding="utf-8"))
    return json.loads(raw["flashData"])


MAIN = _flash("ths_finance_300519_main.json")
BENEFIT = _flash("ths_finance_300519_benefit.json")
OVERVIEW_HTML = (_FIX / "ths_overview_300519.html").read_text(encoding="gbk")
BIZCOMP = json.loads((_FIX / "ths_bizcomp_300519.json").read_text(encoding="utf-8"))

MAIN_RAW = _bytes("ths_finance_300519_main.json")
BENEFIT_RAW = _bytes("ths_finance_300519_benefit.json")
OVERVIEW_RAW = _bytes("ths_overview_300519.html", "gbk")
BIZCOMP_RAW = _bytes("ths_bizcomp_300519.json")


class TestParseAmount:
    """``report``/``simple``/``year`` cells are FORMATTED strings with 万/亿
    suffixes — unlike ``*_yoy``/``*_mom`` which are bare floats. Missing is
    the JSON boolean ``False`` (plus ``""``/``"--"``/``"-"``)."""

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("3971.21万", 3971.21e4),
            ("1.43亿", 1.43e8),
            ("2.65亿", 2.65e8),
            ("-1970.68万", -1970.68e4),
            ("0.25", 0.25),
            ("16000", 16000.0),
        ],
    )
    def test_suffixed_and_bare(self, text, expected):
        assert _parse_ths_amount(text) == pytest.approx(expected)

    @pytest.mark.parametrize("missing", ["", "--", "-", None, "abc", "  "])
    def test_text_sentinels(self, missing):
        assert _parse_ths_amount(missing) is None

    def test_json_false_is_missing_not_zero(self):
        # bool is an int subclass — `False` must not coerce to 0.0
        assert _parse_ths_amount(False) is None

    def test_real_zero_survives(self):
        assert _parse_ths_amount("0.00") == 0.0
        assert _parse_ths_amount(0) == 0.0


class TestParsePct:
    @pytest.mark.parametrize(
        "text,expected",
        [("24.46%", 24.46), ("-5.13%", -5.13), (81.16048277, 81.16048277), (0.0, 0.0)],
    )
    def test_values(self, text, expected):
        assert _parse_ths_pct(text) == pytest.approx(expected)

    @pytest.mark.parametrize("missing", ["", "--", None, False, "亏损"])
    def test_missing(self, missing):
        assert _parse_ths_pct(missing) is None


class TestMarketId:
    """``market`` is REQUIRED by the fuyao operate endpoints and must match
    the exchange — a wrong value answers ``status_code: 10001`` with an
    empty ``data`` (measured for 920002 on 17/33/34/18/105). Values come
    from the ``#marketId`` hidden input of ``basic.10jqka.com.cn/{code}/``."""

    @pytest.mark.parametrize(
        "code,expected",
        [
            ("600519", 17),  # 沪主板
            ("688981", 17),  # 科创板
            ("000001", 33),  # 深主板
            ("002415", 33),  # 中小板
            ("300519", 33),  # 创业板
            ("920002", 151),  # 北交所 (920xxx)
            ("832566", 151),  # 北交所 (legacy 8xxxxx)
            ("430047", 151),  # 北交所 (legacy 4xxxxx)
            ("900901", 18),  # 沪B
            ("200011", 34),  # 深B
        ],
    )
    def test_exchange_mapping(self, code, expected):
        assert _ths_market_id(code) == expected

    @pytest.mark.parametrize("code", ["", "AAPL", "HK00700", "00700", "12345"])
    def test_unmappable(self, code):
        assert _ths_market_id(code) is None


class TestUnwrapFlash:
    def test_real_fixture_round_trips(self):
        raw = json.loads((_FIX / "ths_finance_300519_main.json").read_text(encoding="utf-8"))
        fd = _unwrap_ths_flash(raw)
        assert fd["report"][0][0] == "2026-06-30"
        assert [t[0] if isinstance(t, list) else t for t in fd["title"]][1] == "净利润"

    @pytest.mark.parametrize(
        "payload",
        [None, {}, {"flashData": ""}, {"flashData": "not json"}, {"flashData": "[1,2]"}],
    )
    def test_garbage_returns_none(self, payload):
        assert _unwrap_ths_flash(payload) is None


class TestBuildHistory:
    """Single-quarter records, ASC. Fixture = 300519's real 6 periods."""

    def test_latest_record_maps_every_contract_field(self):
        recs = {r["report_date"]: r for r in _build_ths_history(MAIN, BENEFIT)}
        q2 = recs["2026-06-30"]
        # 单季 5,412.38万 营收 / 1,334.41万 归母 / 1,493.07万 营业利润 /
        # 1,097.09万 扣非 — all from the `simple` table, 元 → 亿
        assert q2["total_revenue_yi"] == pytest.approx(0.541238)
        assert q2["net_profit_attr_yi"] == pytest.approx(0.133441)
        assert q2["net_profit_yi"] == pytest.approx(0.133441)
        assert q2["operating_profit_yi"] == pytest.approx(0.149307)
        assert q2["deduct_net_profit_attr_yi"] == pytest.approx(0.109709)
        assert q2["eps"] == pytest.approx(0.09)
        assert q2["roe_pct"] == pytest.approx(1.58)
        assert q2["gross_margin_pct"] == pytest.approx(47.21)
        assert q2["net_margin_pct"] == pytest.approx(24.65)
        assert q2["pub_date"] is None  # 摘要 JSON 无披露日

    def test_yoy_comes_from_the_value_row_not_the_ratio_row(self):
        """``simple_yoy`` row 0 (净利润) is the YoY of the single-quarter
        amount; row 1 (净利润同比增长率) is the YoY *of that ratio* — a
        nonsense number (-53.65) that must never be emitted as a growth rate."""
        recs = {r["report_date"]: r for r in _build_ths_history(MAIN, BENEFIT)}
        q2 = recs["2026-06-30"]
        assert q2["net_profit_yoy_pct"] == pytest.approx(81.16048277)
        assert q2["revenue_yoy_pct"] == pytest.approx(13.4840511)
        assert q2["net_profit_qoq_pct"] == pytest.approx(-49.39282464)
        assert q2["revenue_qoq_pct"] == pytest.approx(-38.8220085)

    def test_q1_keeps_its_qoq_against_last_year_q4(self):
        # spec §3.2: 主备一致优先于语义洁癖 — Q1 环比保留真实值
        recs = {r["report_date"]: r for r in _build_ths_history(MAIN, BENEFIT)}
        q1 = recs["2026-03-31"]
        assert q1["revenue_qoq_pct"] == pytest.approx(48.08749726)
        assert q1["total_revenue_yi"] == pytest.approx(0.884693)

    def test_output_is_ascending(self):
        # upstream tables are DESC (newest first)
        dates = [r["report_date"] for r in _build_ths_history(MAIN, BENEFIT)]
        assert (
            dates
            == sorted(dates)
            == [
                "2025-03-31",
                "2025-06-30",
                "2025-09-30",
                "2025-12-31",
                "2026-03-31",
                "2026-06-30",
            ]
        )

    def test_window_filters_on_report_date(self):
        recs = _build_ths_history(MAIN, BENEFIT, start_date="2025-07-01", end_date="2026-03-31")
        assert [r["report_date"] for r in recs] == ["2025-09-30", "2025-12-31", "2026-03-31"]

    def test_default_keeps_last_12_periods(self):
        # 20 quarters, DESC exactly as upstream emits them
        quarters = [
            f"{y}-{md}" for y in range(2019, 2024) for md in ("03-31", "06-30", "09-30", "12-31")
        ]
        quarters.reverse()
        n = len(quarters)
        table = {
            "title": [r"科目\时间", "净利润", "营业总收入"],
            "simple": [quarters, ["100万"] * n, ["400万"] * n],
            "simple_yoy": [quarters, [0.0] * n, [0.0] * n],
            "simple_mom": [quarters, [0.0] * n, [0.0] * n],
        }
        recs = _build_ths_history(table, table)
        assert len(recs) == 12
        assert [r["report_date"] for r in recs] == sorted(quarters)[-12:]
        assert recs[-1]["report_date"] == "2023-12-31"

    def test_only_periods_present_in_both_tables_are_emitted(self):
        # 营业利润/含少数股东净利 live only in `benefit`; a period it lacks
        # must be dropped rather than emitted with half its fields nulled
        bare = {
            "title": BENEFIT["title"],
            "simple": [BENEFIT["simple"][0][:1]] + [[row[0]] for row in BENEFIT["simple"][1:]],
        }
        recs = _build_ths_history(MAIN, bare)
        assert [r["report_date"] for r in recs] == ["2026-06-30"]

    def test_missing_tables_degrade_to_empty_list(self):
        assert _build_ths_history(None, None) == []
        assert _build_ths_history(MAIN, None) == []

    def test_unusable_cells_become_none_not_zero(self):
        # THS marks a missing cell with JSON `false`
        broken = json.loads(json.dumps(BENEFIT))
        broken["simple"][32][0] = False  # 归母净利 @2026-06-30
        recs = {r["report_date"]: r for r in _build_ths_history(MAIN, broken)}
        assert recs["2026-06-30"]["net_profit_attr_yi"] is None
        assert recs["2026-06-30"]["total_revenue_yi"] is not None


class TestParseOverviewValuation:
    """The GBK overview page ``basic.10jqka.com.cn/{code}/`` is THS's only
    valuation source — the astockpc SPA and finance.html carry none. Its
    valuation table uses ``<span ...>标签：</span><span ...>值</span>`` cells;
    总股本 alone wraps its value in a hidden ``<input id="stockzgb">``."""

    def test_real_fixture(self):
        out = _parse_ths_overview_valuation(OVERVIEW_HTML)
        assert out["pe_lyr"] == pytest.approx(43.83)  # 市盈率(静态)
        assert out["pb"] == pytest.approx(2.87)
        assert out["total_share_yi"] == pytest.approx(1.60)  # 总股本 (亿股)
        assert out["float_share_yi"] == pytest.approx(1.14)  # 流通A股 (亿股)

    @pytest.mark.parametrize("html", [None, "", "<html><body></body></html>"])
    def test_absent_page_yields_all_none(self, html):
        out = _parse_ths_overview_valuation(html)
        assert out == {
            "pe_lyr": None,
            "pb": None,
            "total_share_yi": None,
            "float_share_yi": None,
        }

    def test_loss_making_stock_has_null_static_pe(self):
        html = OVERVIEW_HTML.replace(">43.83<", ">--<")
        out = _parse_ths_overview_valuation(html)
        assert out["pe_lyr"] is None
        assert out["pb"] == pytest.approx(2.87)


class TestBuildSnapshot:
    """Profit block = the newest single-quarter record. Valuation comes from
    the overview page, with 总市值 **derived** rather than scraped: the page
    only renders it rounded to whole 亿元 ("23亿" for a true 23.76亿, −3.2%),
    so market cap is reconstructed as 静态PE × 上年报归母净利 — the exact
    definition of 静态市盈率 — then peeled back into a price per share for
    the float market cap and the TTM multiples."""

    def _snap(self, main=MAIN, benefit=BENEFIT, html=OVERVIEW_HTML):
        return _build_ths_snapshot(main, benefit, html)

    def test_profit_block_is_the_latest_single_quarter(self):
        snap = self._snap()
        assert snap["report_date"] == "2026-06-30"
        assert snap["total_revenue_yi"] == pytest.approx(0.541238)
        assert snap["net_profit_attr_yi"] == pytest.approx(0.133441)
        assert snap["roe_pct"] == pytest.approx(1.58)
        assert snap["net_profit_qoq_pct"] == pytest.approx(-49.39282464)

    def test_market_cap_is_derived_not_scraped(self):
        # 43.83 (静态PE) × 5421.15万 (上年报归母) = 23.7609亿 — not the page's "23亿"
        snap = self._snap()
        assert snap["market_cap_yi"] == pytest.approx(23.76090045, abs=1e-6)
        assert snap["total_share_wan_shares"] == pytest.approx(16000.0)
        assert snap["float_share_wan_shares"] == pytest.approx(11400.0)
        # price = 23.7609亿 / 1.60亿股 = 14.85056 元 → float cap = 1.14亿 × price
        assert snap["float_market_cap_yi"] == pytest.approx(16.92964157, abs=1e-6)

    def test_ttm_multiples_from_four_single_quarters(self):
        # TTM 归母 = 1342.85+887.53+2636.80+1334.41 万 = 0.620159亿
        # TTM 营收 = 6467.56+5974.13+8846.93+5412.38 万 = 2.670100亿
        snap = self._snap()
        assert snap["pe_ttm"] == pytest.approx(38.31420724, abs=1e-6)
        assert snap["ps"] == pytest.approx(8.89888036, abs=1e-6)

    def test_pe_lyr_and_pb_pass_through(self):
        snap = self._snap()
        assert snap["pe_lyr"] == pytest.approx(43.83)
        assert snap["pb"] == pytest.approx(2.87)

    def test_trade_date_is_null_not_guessed(self):
        """The overview page carries no timestamp — and it is measurably STALE
        for some names: 920002's page implied 51.90 while the live price was
        49.14 (its previous close), inflating the derived market cap by 5.7%.
        Stamping "today" would launder that staleness as freshness."""
        assert self._snap()["trade_date"] is None

    def test_unavailable_valuation_is_null_not_zero(self):
        snap = self._snap()
        assert snap["pcf"] is None  # 上游无现成来源；不做近似
        assert snap["turnover_ratio_pct"] is None  # 概览页无换手率字段
        assert snap["trade_date"] is None  # 页面不带时间戳

    def test_short_history_still_yields_a_snapshot(self):
        # TTM block needs 4 quarters; a stored series may be shorter
        short = {
            "title": BENEFIT["title"],
            "simple": [BENEFIT["simple"][0][:2]] + [r[:2] for r in BENEFIT["simple"][1:]],
        }
        snap = _build_ths_snapshot(MAIN, short, OVERVIEW_HTML)
        assert snap["report_date"] == "2026-06-30"
        assert snap["pe_ttm"] is None
        assert snap["ps"] is None
        assert snap["pb"] == pytest.approx(2.87)  # page-sourced fields survive

    def test_no_annual_report_row_nulls_market_cap(self):
        # 上年报归母 anchors the 静态PE inversion; without it market cap and
        # everything derived from it must be null rather than guessed. It
        # comes from the CUMULATIVE table — `simple`'s 12-31 row is Q4 alone
        # (887.53万, not the 5421.15万 annual), so both columns are dropped
        # here to prove which one the derivation actually reads.
        def drop_1231(tbl):
            cols = BENEFIT[tbl][0]
            keep = [i for i, d in enumerate(cols) if d != "2025-12-31"]
            return [[cols[i] for i in keep]] + [[r[i] for i in keep] for r in BENEFIT[tbl][1:]]

        trimmed = {
            "title": BENEFIT["title"],
            "simple": drop_1231("simple"),
            "report": drop_1231("report"),
        }
        snap = _build_ths_snapshot(MAIN, trimmed, OVERVIEW_HTML)
        assert snap["market_cap_yi"] is None
        assert snap["float_market_cap_yi"] is None
        assert snap["pe_ttm"] is None
        assert snap["total_share_wan_shares"] == pytest.approx(16000.0)

    def test_missing_valuation_page_keeps_the_profit_block(self):
        snap = self._snap(html=None)
        assert snap["total_revenue_yi"] == pytest.approx(0.541238)
        assert snap["pe_lyr"] is None
        assert snap["market_cap_yi"] is None

    def test_no_history_returns_none_never_empty_dict(self):
        # `_is_meaningful({})` is True and would short-circuit failover
        assert _build_ths_snapshot(None, None, OVERVIEW_HTML) is None
        assert _build_ths_snapshot(MAIN, None, OVERVIEW_HTML) is None


class TestBuildBusinessComposition:
    """Mirrors EastMoneyFetcher's return contract exactly (the route reads
    ``available_report_dates`` / ``requested_report_date_available`` for its
    400 decision). ``classify`` 1/2/3 = 按行业/按产品/按地区.

    Ratio SHAPE differs from EastMoney (percent here vs 0..1 fractions there)
    and so does the denominator: THS normalises to 当期营业总收入 (600519 茅台酒
    84.2285%) while EM divides by its own product-row sum (85.6909%). The
    fixture's 72.5783% happens to match EM's — for 300519 the two row sets
    coincide — so the divergence is NOT visible from this fixture alone; see
    ``docs``/api-reference.md for the 600519 counter-example.
    """

    def test_default_serves_the_newest_period(self):
        out = _build_ths_business_composition(BIZCOMP)
        assert out["report_date"] == "2026-06-30"
        assert out["available_report_dates"] == ["2025-12-31", "2026-06-30"]
        assert out["requested_report_date_available"] is None

    def test_maps_units_categories_and_every_field(self):
        out = _build_ths_business_composition(BIZCOMP, category="product")
        top = out["records"][0]
        assert top["category"] == "product"
        assert top["item"] == "黄芪生脉饮"
        assert top["rank"] is None  # upstream carries no rank
        assert top["revenue_yi"] == pytest.approx(1.0349157459)
        assert top["revenue_share_pct"] == pytest.approx(72.57825363)
        assert top["cost_yi"] == pytest.approx(0.52219578)
        assert top["cost_share_pct"] == pytest.approx(67.89770909)
        assert top["profit_yi"] == pytest.approx(0.5127199659)
        assert top["profit_share_pct"] == pytest.approx(78.05869691)
        assert top["gross_margin_pct"] == pytest.approx(49.54219394)

    def test_unfiltered_returns_every_category_grouped(self):
        out = _build_ths_business_composition(BIZCOMP)
        assert {r["category"] for r in out["records"]} == {"product", "region"}
        assert [r["category"] for r in out["records"]] == sorted(
            r["category"] for r in out["records"]
        )
        # revenue-descending inside a category (no upstream rank to sort by)
        products = [r["revenue_yi"] for r in out["records"] if r["category"] == "product"]
        assert products == sorted(products, reverse=True)

    def test_industry_category_is_legitimately_empty_for_the_newest_period(self):
        # 300519 has 行业行 only in the annual report (same shape as EM's
        # 茅台 finding) — an empty answer here is a fact, not a failure
        out = _build_ths_business_composition(BIZCOMP, category="industry")
        assert out["records"] == []
        assert out["report_date"] == "2026-06-30"

    def test_explicit_report_date(self):
        out = _build_ths_business_composition(
            BIZCOMP, category="industry", report_date="2025-12-31"
        )
        assert out["report_date"] == "2025-12-31"
        assert out["requested_report_date_available"] is True
        assert [r["item"] for r in out["records"]] == ["医药行业"]

    def test_unknown_report_date_flags_unavailable_without_raising(self):
        # fetchers speak only DataFetchError/returns — the 400 is the route's
        out = _build_ths_business_composition(BIZCOMP, report_date="2011-12-31")
        assert out["requested_report_date_available"] is False
        assert out["records"] == []
        assert out["report_date"] == "2011-12-31"

    @pytest.mark.parametrize(
        "payload", [None, {}, {"data": []}, {"data": None}, {"status_code": 10001, "data": []}]
    )
    def test_empty_or_wrong_market_yields_the_empty_contract(self, payload):
        out = _build_ths_business_composition(payload)
        assert out == {
            "report_date": None,
            "records": [],
            "available_report_dates": [],
            "requested_report_date_available": None,
        }

    def test_unknown_category_is_dropped_not_guessed(self):
        out = _build_ths_business_composition(BIZCOMP, category="nonsense")
        assert out["records"] == []


class _Stub:
    """Records every upstream URL and answers from a fragment → body map."""

    def __init__(self, responses: dict[str, object]):
        self.responses = responses
        self.calls: list[str] = []

    def __call__(self, url: str):
        self.calls.append(url)
        for fragment, value in self.responses.items():
            if fragment in url:
                if isinstance(value, Exception):
                    raise value
                if isinstance(value, tuple):
                    return value
                return 200, value
        raise AssertionError(f"unexpected upstream URL: {url}")


@pytest.fixture
def build(monkeypatch):
    def _build(responses: dict[str, object]):
        fetcher = ThsFetcher()
        stub = _Stub(responses)
        monkeypatch.setattr(fetcher, "_ths_get", stub, raising=True)
        return fetcher, stub

    return _build


class TestFinancialSnapshot:
    def test_combines_the_three_upstreams(self, build):
        fetcher, stub = build(
            {
                "_main.json": MAIN_RAW,
                "_benefit.json": BENEFIT_RAW,
                "/300519/": OVERVIEW_RAW,
            }
        )
        snap = fetcher.get_financial_snapshot("300519")
        assert sorted(stub.calls) == sorted(
            [
                "https://basic.10jqka.com.cn/api/stock/finance/300519_main.json",
                "https://basic.10jqka.com.cn/api/stock/finance/300519_benefit.json",
                "https://basic.10jqka.com.cn/300519/",
            ]
        )
        assert snap["report_date"] == "2026-06-30"
        assert snap["total_revenue_yi"] == pytest.approx(0.541238)
        assert snap["pb"] == pytest.approx(2.87)
        assert snap["market_cap_yi"] == pytest.approx(23.76090045, abs=1e-6)
        assert snap["trade_date"] is None

    def test_normalizes_prefixed_codes(self, build):
        fetcher, stub = build(
            {"_main.json": MAIN_RAW, "_benefit.json": BENEFIT_RAW, "/300519/": OVERVIEW_RAW}
        )
        fetcher.get_financial_snapshot("SZ300519")
        assert all(
            "300519_main.json" in url or "300519_benefit.json" in url or url.endswith("/300519/")
            for url in stub.calls
        )

    def test_valuation_leg_is_best_effort(self, build):
        # unlike zzshare's three co-required legs, the overview page only
        # carries valuation — losing it must not throw away a valid profit
        # block (same rule the zhitu quote leg follows)
        fetcher, _ = build(
            {
                "_main.json": MAIN_RAW,
                "_benefit.json": BENEFIT_RAW,
                "/300519/": (503, b""),
            }
        )
        snap = fetcher.get_financial_snapshot("300519")
        assert snap["total_revenue_yi"] == pytest.approx(0.541238)
        assert snap["pe_lyr"] is None
        assert snap["market_cap_yi"] is None

    def test_valuation_leg_transport_error_is_still_best_effort(self, build):
        """A tolerated leg must survive `requests`-level exceptions, not just
        non-200: ``_ths_get`` goes through a bare ``requests.get``, so a
        ConnectionError/Timeout would otherwise escape the fan-out and turn the
        whole snapshot into a 503, discarding a perfectly good profit block."""
        import requests

        fetcher, _ = build(
            {
                "_main.json": MAIN_RAW,
                "_benefit.json": BENEFIT_RAW,
                "/300519/": requests.ConnectionError("valuation host unreachable"),
            }
        )
        snap = fetcher.get_financial_snapshot("300519")
        assert snap["total_revenue_yi"] == pytest.approx(0.541238)
        assert snap["pb"] is None
        assert snap["market_cap_yi"] is None

    def test_profit_leg_transport_error_still_raises(self, build):
        import requests

        fetcher, _ = build(
            {
                "_main.json": MAIN_RAW,
                "_benefit.json": requests.ConnectionError("down"),
                "/300519/": OVERVIEW_RAW,
            }
        )
        with pytest.raises(requests.ConnectionError):
            fetcher.get_financial_snapshot("300519")

    def test_profit_leg_failure_raises_datafetcherror(self, build):
        fetcher, _ = build(
            {
                "_main.json": MAIN_RAW,
                "_benefit.json": DataFetchError("boom"),
                "/300519/": OVERVIEW_RAW,
            }
        )
        with pytest.raises(DataFetchError):
            fetcher.get_financial_snapshot("300519")

    def test_empty_upstream_payload_returns_none(self, build):
        # upstream answered, but with no usable table → coherent-empty (None),
        # never {} — the manager's `_is_meaningful({})` is True
        fetcher, _ = build(
            {
                "_main.json": b'{"flashData": ""}',
                "_benefit.json": b'{"flashData": ""}',
                "/300519/": OVERVIEW_RAW,
            }
        )
        assert fetcher.get_financial_snapshot("300519") is None

    def test_malformed_json_raises_rather_than_masquerading_as_empty(self, build):
        # a body that is not JSON means the endpoint changed / was blocked —
        # an outage, not an authoritative empty answer
        fetcher, _ = build({"_main.json": b"<html>blocked</html>", "_benefit.json": BENEFIT_RAW})
        with pytest.raises(DataFetchError):
            fetcher.get_financial_snapshot("300519")

    def test_non_200_raises(self, build):
        fetcher, _ = build({"_main.json": (500, b"oops")})
        with pytest.raises(DataFetchError):
            fetcher.get_financial_snapshot("300519")


class TestFinancialHistory:
    def test_hits_only_the_two_json_legs(self, build):
        fetcher, stub = build({"_main.json": MAIN_RAW, "_benefit.json": BENEFIT_RAW})
        recs = fetcher.get_financial_history("300519")
        assert len(stub.calls) == 2  # no overview page for the history contract
        assert [r["report_date"] for r in recs][-1] == "2026-06-30"
        assert recs[-1]["operating_profit_yi"] == pytest.approx(0.149307)

    def test_window_is_forwarded(self, build):
        fetcher, _ = build({"_main.json": MAIN_RAW, "_benefit.json": BENEFIT_RAW})
        recs = fetcher.get_financial_history(
            "300519", start_date="2026-01-01", end_date="2026-03-31"
        )
        assert [r["report_date"] for r in recs] == ["2026-03-31"]

    def test_no_data_returns_empty_list(self, build):
        fetcher, _ = build({"_main.json": b'{"flashData": ""}', "_benefit.json": b"{}"})
        assert fetcher.get_financial_history("300519") == []


class TestMainBusinessComposition:
    def test_uses_the_derived_market_id(self, build):
        fetcher, stub = build({"main_business_structure": BIZCOMP_RAW})
        out = fetcher.get_main_business_composition("300519", category="product")
        assert len(stub.calls) == 1
        assert "market=33" in stub.calls[0]
        assert "code=300519" in stub.calls[0]
        assert out["report_date"] == "2026-06-30"
        assert out["records"][0]["item"] == "黄芪生脉饮"

    @pytest.mark.parametrize("code,market", [("600519", 17), ("920002", 151)])
    def test_market_id_per_exchange(self, build, code, market):
        fetcher, stub = build({"main_business_structure": BIZCOMP_RAW})
        fetcher.get_main_business_composition(code)
        assert f"market={market}" in stub.calls[0]

    def test_upstream_error_status_yields_the_empty_contract(self, build):
        # status_code 10001 = "market/code mismatch", not an outage: it is
        # the authoritative "no breakdown for this code" answer
        body = json.dumps({"status_code": 10001, "status_msg": "empty"}).encode()
        fetcher, _ = build({"main_business_structure": body})
        out = fetcher.get_main_business_composition("300519")
        assert out["records"] == [] and out["report_date"] is None

    def test_unmappable_code_never_calls_upstream(self, build):
        fetcher, stub = build({"main_business_structure": BIZCOMP_RAW})
        out = fetcher.get_main_business_composition("HK00700")
        assert stub.calls == []
        assert out["records"] == []

    def test_network_failure_raises(self, build):
        fetcher, _ = build({"main_business_structure": DataFetchError("down")})
        with pytest.raises(DataFetchError):
            fetcher.get_main_business_composition("300519")


class TestCapabilityDeclaration:
    def test_declares_all_three_financial_capabilities(self):
        from stock_data.data_provider.base import DataCapability

        declared = ThsFetcher.supported_data_types
        assert DataCapability.STOCK_FINANCIAL in declared
        assert DataCapability.STOCK_FINANCIAL_SERIES in declared
        assert DataCapability.STOCK_MAIN_BUSINESS in declared


class TestMarketIdMapIsGone:
    """``_THS_MARKET_ID_MAP`` keyed on the FIRST character and sent 9xxxxx to
    17, so ``get_stock_news`` on a 北交所 code silently returned a DIFFERENT
    company's news (920002 → market 17 → 中文在线 headlines; measured
    2026-10-08). It now uses the shared ``ths_market_id`` derivation."""

    def test_bj_news_requests_market_151(self, build, monkeypatch):
        fetcher = ThsFetcher()
        seen: dict = {}

        def fake_json_get(url, params=None, **kwargs):
            seen.update(params or {})
            return {"status_code": 0, "data": {"data": []}}

        monkeypatch.setattr("stock_data.data_provider.fetchers.ths_fetcher.json_get", fake_json_get)
        fetcher.get_stock_news("920002")
        assert seen["market"] == 151
