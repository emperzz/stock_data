"""Static endpoint metadata and field-code maps for EastMoneyFetcher.

This module is data-only — no ``self``, no HTTP, no Fetcher state. It
centralises every EastMoney URL / report-name / sort-default / fs-prefix
that the rest of the fetcher references by symbolic name.

Two top-level singletons are exported:
- ``URLS``  (``_EastMoneyURLs``) — the 6 push2/news subdomain URLs.
- ``ENDPOINTS``  (``_Endpoints``) — every API entry the methods call:
  dataclass entries for ``datacenter-web.eastmoney.com`` (7 endpoints),
  dict entries for ``push2.eastmoney.com`` fund-flow + board clist,
  plus ``reportapi`` and PDF.

Field-code maps at the bottom of the module decouple the upstream
``f1,f2,f3,...`` opaque field codes from the public JSON response
keys. The mixins below consume these by lookup.
"""

from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
DATACENTER_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"


class _EastMoneyURLs:
    """EastMoney URL registry — consolidated (was 6 scattered ``_*_URL``
    constants before Phase 1). Each member is the full upstream URL for one
    push2/news domain endpoint.
    """

    STOCK_BOARDS = "https://push2.eastmoney.com/api/qt/slist/get"
    STOCK_NEWS = "https://np-listapi.eastmoney.com/comm/web/getListInfo"
    STOCK_ANNOUNCEMENTS = "https://np-anotice-stock.eastmoney.com/api/security/ann"
    NEWS_SEARCH = "https://search-api-web.eastmoney.com/search/jsonp"
    NEWS_WARMUP = "https://so.eastmoney.com/news/s"
    FLASH_NEWS = "https://np-weblist.eastmoney.com/comm/web/getFastNewsList"


URLS = _EastMoneyURLs()


# ---------------------------------------------------------------------------
# Per-endpoint metadata
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _DCEndpoint:
    """Descriptor for a single ``datacenter-web.eastmoney.com`` API endpoint.
    Used by ``_datacenter_query`` to build the standard ``reportName /
    columns / filter / pageSize / sortColumns / sortTypes / source / client``
    request payload, and by ``_datacenter_records`` to apply the
    ``code_filter_field`` (most use ``SECURITY_CODE``; margin uses ``SCODE``).
    """

    report_name: str
    sort_columns: str = ""
    sort_types: str = "-1"
    page_size: int = 50
    code_filter_field: str = "SECURITY_CODE"  # some endpoints use "SCODE"


class _Endpoints:
    """Central registry of every EastMoney API endpoint this fetcher uses.

    Each entry declares the upstream parameters needed for one
    ``_datacenter_query`` or ``_push2_query`` call. Methods reference entries
    by name so URL / reportName / sort defaults live in one place — adding a
    new endpoint is one registry line + one wrapper method, no inline soup.
    """

    # -- datacenter-web endpoints ----------------------------------------

    DRAGON_TIGER = _DCEndpoint(
        report_name="RPT_DAILYBILLBOARD_DETAILSNEW",
        sort_columns="TRADE_DATE",
        page_size=50,
    )
    DRAGON_TIGER_BUY_SEATS = _DCEndpoint(
        report_name="RPT_BILLBOARD_DAILYDETAILSBUY",
        sort_columns="BUY",
        page_size=10,
    )
    DRAGON_TIGER_SELL_SEATS = _DCEndpoint(
        report_name="RPT_BILLBOARD_DAILYDETAILSSELL",
        sort_columns="SELL",
        page_size=10,
    )
    DAILY_DRAGON_TIGER = _DCEndpoint(
        report_name="RPT_DAILYBILLBOARD_DETAILSNEW",
        sort_columns="BILLBOARD_NET_AMT",
        page_size=500,
    )
    MARGIN_TRADING = _DCEndpoint(
        report_name="RPTA_WEB_RZRQ_GGMX",
        sort_columns="DATE",
        code_filter_field="SCODE",
    )
    BLOCK_TRADE = _DCEndpoint(
        report_name="RPT_DATA_BLOCKTRADE",
        sort_columns="TRADE_DATE",
    )
    HOLDER_NUM = _DCEndpoint(
        report_name="RPT_HOLDERNUMLATEST",
        sort_columns="END_DATE",
    )
    DIVIDEND = _DCEndpoint(
        report_name="RPT_SHAREBONUS_DET",
        sort_columns="EX_DIVIDEND_DATE",
    )

    # -- push2 / push2his ------------------------------------------------

    FUND_FLOW_MINUTE = {
        "url": "https://push2.eastmoney.com/api/qt/stock/fflow/kline/get",
        "params_template": {"klt": 1},
        "fields1": "f1,f2,f3,f7",
        "fields2": "f51,f52,f53,f54,f55,f56,f57",
    }
    FUND_FLOW_DAILY = {
        "url": "https://push2.eastmoney.com/api/qt/stock/fflow/daykline/get",
        "params_template": {"lmt": "120"},
        "fields1": "f1,f2,f3,f7",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65",
    }

    # -- reportapi -------------------------------------------------------

    REPORT_LIST_URL = "https://reportapi.eastmoney.com/report/list"

    # -- PDF -------------------------------------------------------------

    PDF_URL_TPL = "https://pdf.dfcfw.com/pdf/H3_{info_code}_1.pdf"

    # -- Board clist (概念 / 行业 板块清单与成分股) --------------------
    # Direct push2.eastmoney.com clist. fs / fid / fields align with akshare's
    # stock_board_*_em / stock_board_*_cons_em request shape; field-code →
    # output key translations live in the _BOARD_*_FIELD_MAP constants below.
    #
    # url_prefixes (added 2026-07-03, push2 WAF hardening):
    # Each push2 clist endpoint may have multiple URL variants — a numeric
    # subdomain prefix (akshare's known-good pattern: 79/17/29) plus the bare
    # push2.eastmoney.com fallback. The fetcher's _build_clist_url_variants()
    # iterates these in order, first success wins. Empty string in the list
    # means "no prefix" (bare push2.eastmoney.com).
    # Override per-endpoint via env var: EASTMONEY_PUSH2_{CONCEPT,INDUSTRY,
    # COMPONENTS}_PREFIXES — comma-separated prefix list, e.g. "29,17,".
    BOARD_LIST_CONCEPT = {
        "url": "https://push2.eastmoney.com/api/qt/clist/get",
        "url_prefixes": ["79", ""],  # 79.push2 (akshare) → bare push2 (fallback)
        "fs": "m:90+t:3+f:!50",
        "fid": "f12",
        "fields": "f2,f3,f4,f8,f12,f14,f15,f20,f104,f105,f128,f136",
    }
    BOARD_LIST_INDUSTRY = {
        "url": "https://push2.eastmoney.com/api/qt/clist/get",
        "url_prefixes": ["17", ""],  # 17.push2 (akshare) → bare push2 (fallback)
        "fs": "m:90+t:2+f:!50",
        "fid": "f3",
        "fields": "f2,f3,f4,f8,f12,f14,f16,f20,f104,f105,f128,f136",
    }
    BOARD_COMPONENTS = {
        "url": "https://push2.eastmoney.com/api/qt/clist/get",
        "url_prefixes": ["29", ""],  # 29.push2 (akshare cons) → bare push2 (fallback)
        "fs_template": "b:{board_code}+f:!50",
        "fid": "f3",
        "fields": "f2,f3,f4,f5,f6,f7,f8,f9,f14,f16,f17,f18,f20,f21,f22",
    }

    # -- Board K-line (push2his /api/qt/stock/kline/get) ----------------
    # Same endpoint as the per-stock kline; only the ``secid`` differs
    # (``90.BKxxxx`` for boards). ``ut`` is the observed constant from
    # quote.eastmoney.com JS (bk2.js, emcharts.js).
    BOARD_KLINE = {
        "url": "https://push2his.eastmoney.com/api/qt/stock/kline/get",
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "freq_map": {"d": 101, "w": 102, "m": 103, "5m": 5, "15m": 15, "30m": 30, "60m": 60},
        "ut": "fa5fd1943c7b386f172d6893dbfba10b",
    }


ENDPOINTS = _Endpoints()


# ---------------------------------------------------------------------------
# Board field-code → output key mappings
# ---------------------------------------------------------------------------
#
# EastMoney's clist / push2 API uses ``f1,f2,f3,...`` (internal opaque id)
# as the ``fields`` query param; ``data.diff`` is either per-field dicts or
# positional lists aligned with the ``fields`` order. The maps below translate
# the field codes to the JSON keys the route layer exposes.
#
# Field-code semantics (probed 2026-07-03 from push2.eastmoney.com reply;
# fixture in tests/test_eastmoney_stock_boards.py:22-26):
# - concept board list:  f12=board code (e.g. "BK0438"), f14=board name
#                        (e.g. "食品饮料"); f15 is some numeric quote field
# - industry board list: f12=board code, f14=board name; f16 is a numeric
#                        quote field (NOT the name — that was the prior bug,
#                        see commit history)
# - board components:    f14=stock code, f16=stock name, f17=high, f18=low,
#                        f20=open, f21=prev_close, f22=PB
# Note: the comment in akshare's stock_board_concept_em / industry_em source
# has the inverse mapping (says f14=code, f15/f16=name); that's stale. Trust
# the actual upstream probe, not the akshare column headers.

_BOARD_LIST_FIELD_MAP: dict[str, str] = {
    "f2": "price",
    "f3": "change_pct",
    "f4": "change_amount",
    "f8": "turnover_rate",
    "f12": "code",
    "f14": "name",
    "f20": "total_mv",
    "f104": "up_count",
    "f105": "down_count",
    "f128": "leading_stock",
    "f136": "leading_stock_pct",
}
# Both endpoints now use f14 for the board name. Per-endpoint symbols
# retained so each method's intent stays locally readable (the production
# code branches by symbol, not by value).
_CONCEPT_LIST_NAME_FIELD = "f14"
_INDUSTRY_LIST_NAME_FIELD = "f14"

_BOARD_COMPONENTS_FIELD_MAP: dict[str, str] = {
    "f2": "price",
    "f3": "change_pct",
    "f4": "change_amount",
    "f5": "volume",
    "f6": "amount",
    "f7": "amplitude",
    "f8": "turnover_rate",
    "f9": "pe_ratio",
    "f14": "stock_code",
    "f16": "stock_name",
    "f17": "high",
    "f18": "low",
    "f20": "open",
    "f21": "pre_close",
    "f22": "pb_ratio",
}
