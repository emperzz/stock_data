"""
EastMoney data-centre HTTP API fetcher.

Provides: 龙虎榜(dragon-tiger), 融资融券(margin), 大宗交易(block-trade),
          股东户数(holder-num), 分红送转(dividend), 资金流向(fund-flow),
          研报(research-report)

Domains
-------
- datacenter-web.eastmoney.com  — 龙虎榜 / 融资融券 / 大宗交易 / 股东户数 / 分红送转
- push2.eastmoney.com           — 资金流分钟级
- push2his.eastmoney.com        — 资金流 120 日
- reportapi.eastmoney.com       — 研报列表
- pdf.dfcfw.com                 — 研报 PDF

Endpoint registry
-----------------
Every upstream API call is declared in ``ENDPOINTS`` (class attribute).
Methods reference entries by key rather than repeating URL / reportName /
sort / filter strings inline.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import requests

from ..base import BaseFetcher, DataCapability, DataFetchError
from ..utils.code_converter import to_eastmoney_secid
from ..utils.normalize import normalize_stock_code

logger = logging.getLogger(__name__)

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
DATACENTER_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"

# ---------------------------------------------------------------------------
# Per-endpoint metadata
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _DCEndpoint:
    """Descriptor for a single datacenter-web API endpoint."""
    report_name: str
    sort_columns: str = ""
    sort_types: str = "-1"
    page_size: int = 50
    code_filter_field: str = "SECURITY_CODE"  # some endpoints use "SCODE"


class _Endpoints:
    """Central registry of every EastMoney API endpoint used by this fetcher.

    Each entry declares the upstream parameters needed for a single
    ``_datacenter_query`` or ``_push2_query`` call.  Methods reference
    entries by name so that URL / reportName / sort defaults live in
    one place.
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
        "url": "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get",
        "params_template": {"lmt": "120"},
        "fields1": "f1,f2,f3,f7",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65",
    }

    # -- reportapi -------------------------------------------------------

    REPORT_LIST_URL = "https://reportapi.eastmoney.com/report/list"

    # -- PDF -------------------------------------------------------------

    PDF_URL_TPL = "https://pdf.dfcfw.com/pdf/H3_{info_code}_1.pdf"


ENDPOINTS = _Endpoints()


# ---------------------------------------------------------------------------
# Fetcher
# ---------------------------------------------------------------------------

class EastMoneyFetcher(BaseFetcher):
    """EastMoney data-centre API fetcher for financial data."""

    name = "EastMoneyFetcher"
    priority = int(os.getenv("EASTMONEY_PRIORITY", "6"))
    supported_markets: set[str] = {"csi"}
    supported_data_types = (
        DataCapability.DRAGON_TIGER
        | DataCapability.MARGIN_TRADING
        | DataCapability.BLOCK_TRADE
        | DataCapability.HOLDER_NUM
        | DataCapability.DIVIDEND
        | DataCapability.FUND_FLOW
        | DataCapability.RESEARCH_REPORT
        | DataCapability.NEWS_SEARCH
    )

    def is_available(self) -> bool:
        return True

    def _fetch_raw_data(self, stock_code, start_date, end_date, frequency="d", adjust=None):
        raise DataFetchError("EastMoneyFetcher does not support historical K-line data")

    def _normalize_data(self, df, stock_code):
        raise DataFetchError("EastMoneyFetcher does not support historical K-line data")

    # ------------------------------------------------------------------
    # Shared query helpers
    # ------------------------------------------------------------------

    def _datacenter_query(
        self,
        endpoint: _DCEndpoint,
        *,
        filter_str: str = "",
        page_size: int | None = None,
    ) -> list[dict[str, Any]]:
        """Query a datacenter-web endpoint.

        Args:
            endpoint: ``_DCEndpoint`` entry from ``ENDPOINTS``.
            filter_str: EastMoney filter-expression string.
            page_size: Override the endpoint's default page size.
        """
        params = {
            "reportName": endpoint.report_name,
            "columns": "ALL",
            "filter": filter_str,
            "pageNumber": "1",
            "pageSize": str(page_size or endpoint.page_size),
            "sortColumns": endpoint.sort_columns,
            "sortTypes": endpoint.sort_types,
            "source": "WEB",
            "client": "WEB",
        }
        headers = {"User-Agent": UA, "Referer": "https://data.eastmoney.com/"}
        try:
            r = requests.get(DATACENTER_URL, params=params, headers=headers, timeout=15)
            d = r.json()
            if d.get("result") and d["result"].get("data"):
                return d["result"]["data"]
            return []
        except Exception as e:
            logger.warning(f"[EastMoneyFetcher] datacenter query failed: {e}")
            return []

    def _push2_query(
        self,
        endpoint: dict[str, Any],
        secid: str,
        *,
        extra_params: dict[str, str] | None = None,
        timeout: int = 15,
    ) -> list[str]:
        """Query a push2 / push2his comma-separated kline endpoint.

        Args:
            endpoint: Entry from ``ENDPOINTS`` (e.g. ``FUND_FLOW_MINUTE``).
            secid: EastMoney security ID.
            extra_params: Additional query params merged onto the template.

        Returns:
            List of comma-separated kline strings (raw).
        """
        params: dict[str, str] = {
            "secid": secid,
            "fields1": endpoint["fields1"],
            "fields2": endpoint["fields2"],
            **endpoint["params_template"],
        }
        if extra_params:
            params.update(extra_params)
        headers = {"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"}
        try:
            r = requests.get(endpoint["url"], params=params, headers=headers, timeout=timeout)
            d = r.json()
            return d.get("data", {}).get("klines") or []
        except Exception as e:
            logger.warning(f"[EastMoneyFetcher] push2 query failed: {e}")
            return []

    def _secid(self, code: str) -> str:
        """Build EastMoney secid. Delegates to ``to_eastmoney_secid``."""
        return to_eastmoney_secid(code)

    # ------------------------------------------------------------------
    # 龙虎榜 (Dragon Tiger Board) — per-stock
    # ------------------------------------------------------------------

    def get_dragon_tiger(self, code: str, trade_date: str = "", look_back: int = 30) -> dict:
        """Get dragon tiger board data for a single stock.

        Returns: {records: [...], seats: {buy: [...], sell: [...]}, institution: {...}}
        """
        code = normalize_stock_code(code)
        if not trade_date:
            trade_date = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.strptime(trade_date, "%Y-%m-%d")
                 - timedelta(days=look_back)).strftime("%Y-%m-%d")

        ep = ENDPOINTS.DRAGON_TIGER
        filter_str = (
            f"(TRADE_DATE>='{start}')(TRADE_DATE<='{trade_date}')"
            f'(SECURITY_CODE="{code}")'
        )
        data = self._datacenter_query(ep, filter_str=filter_str)

        records = []
        for row in data:
            records.append({
                "date": str(row.get("TRADE_DATE", ""))[:10],
                "reason": row.get("EXPLANATION", ""),
                "net_buy_wan": round((row.get("BILLBOARD_NET_AMT") or 0) / 10000, 1),
                "turnover_pct": round(float(row.get("TURNOVERRATE") or 0), 2),
            })

        seats: dict[str, list[dict]] = {"buy": [], "sell": []}
        institution: dict[str, float] = {"buy_amt": 0, "sell_amt": 0, "net_amt": 0}
        if records:
            latest_date = records[0]["date"]
            code_filter = f"(TRADE_DATE='{latest_date}')(SECURITY_CODE=\"{code}\")"

            buy_data = self._datacenter_query(
                ENDPOINTS.DRAGON_TIGER_BUY_SEATS, filter_str=code_filter,
            )
            for row in buy_data[:5]:
                seats["buy"].append({
                    "name": row.get("OPERATEDEPT_NAME", ""),
                    "buy_wan": round((row.get("BUY") or 0) / 10000, 1),
                    "sell_wan": round((row.get("SELL") or 0) / 10000, 1),
                    "net_wan": round((row.get("NET") or 0) / 10000, 1),
                })
            sell_data = self._datacenter_query(
                ENDPOINTS.DRAGON_TIGER_SELL_SEATS, filter_str=code_filter,
            )
            for row in sell_data[:5]:
                seats["sell"].append({
                    "name": row.get("OPERATEDEPT_NAME", ""),
                    "buy_wan": round((row.get("BUY") or 0) / 10000, 1),
                    "sell_wan": round((row.get("SELL") or 0) / 10000, 1),
                    "net_wan": round((row.get("NET") or 0) / 10000, 1),
                })
            for detail_data, side in [(buy_data, "buy"), (sell_data, "sell")]:
                for row in detail_data:
                    if str(row.get("OPERATEDEPT_CODE", "")) == "0":
                        amt = (row.get("BUY") or 0) if side == "buy" else (row.get("SELL") or 0)
                        if side == "buy":
                            institution["buy_amt"] += amt
                        else:
                            institution["sell_amt"] += amt
            institution["buy_amt"] = round(institution["buy_amt"] / 10000, 1)
            institution["sell_amt"] = round(institution["sell_amt"] / 10000, 1)
            institution["net_amt"] = round(institution["buy_amt"] - institution["sell_amt"], 1)

        return {"records": records, "seats": seats, "institution": institution}

    # ------------------------------------------------------------------
    # 全市场龙虎榜 (Daily Dragon Tiger)
    # ------------------------------------------------------------------

    def get_daily_dragon_tiger(
        self, trade_date: str = "", min_net_buy: float | None = None
    ) -> dict:
        """Get daily market-wide dragon tiger board summary."""
        if not trade_date:
            trade_date = datetime.now().strftime("%Y-%m-%d")

        ep = ENDPOINTS.DAILY_DRAGON_TIGER
        filter_str = f"(TRADE_DATE>='{trade_date}')(TRADE_DATE<='{trade_date}')"
        data = self._datacenter_query(ep, filter_str=filter_str)

        stocks = []
        for row in data:
            net_buy = (row.get("BILLBOARD_NET_AMT") or 0) / 10000
            if min_net_buy is not None and net_buy < min_net_buy:
                continue
            stocks.append({
                "code": row.get("SECURITY_CODE", ""),
                "name": row.get("SECURITY_NAME_ABBR", ""),
                "reason": row.get("EXPLANATION", ""),
                "close": row.get("CLOSE_PRICE", 0),
                "change_pct": round(float(row.get("CHANGE_RATE") or 0), 2),
                "net_buy_wan": round(net_buy, 1),
                "buy_wan": round((row.get("BILLBOARD_BUY_AMT") or 0) / 10000, 1),
                "sell_wan": round((row.get("BILLBOARD_SELL_AMT") or 0) / 10000, 1),
                "turnover_pct": round(float(row.get("TURNOVERRATE") or 0), 2),
            })
        return {"date": trade_date, "total": len(stocks), "stocks": stocks}

    # ------------------------------------------------------------------
    # 融资融券 (Margin Trading)
    # ------------------------------------------------------------------

    def get_margin_trading(self, code: str, page_size: int = 30) -> list[dict]:
        """Get margin trading data."""
        code = normalize_stock_code(code)
        ep = ENDPOINTS.MARGIN_TRADING
        filter_str = f'({ep.code_filter_field}="{code}")'
        data = self._datacenter_query(ep, filter_str=filter_str, page_size=page_size)
        rows = []
        for row in data:
            rows.append({
                "date": str(row.get("DATE", ""))[:10],
                "rzye": row.get("RZYE", 0),
                "rzmre": row.get("RZMRE", 0),
                "rzche": row.get("RZCHE", 0),
                "rqye": row.get("RQYE", 0),
                "rqmcl": row.get("RQMCL", 0),
                "rqchl": row.get("RQCHL", 0),
                "rzrqye": row.get("RZRQYE", 0),
            })
        return rows

    # ------------------------------------------------------------------
    # 大宗交易 (Block Trade)
    # ------------------------------------------------------------------

    def get_block_trade(self, code: str, page_size: int = 20) -> list[dict]:
        """Get block trade records."""
        code = normalize_stock_code(code)
        ep = ENDPOINTS.BLOCK_TRADE
        filter_str = f'({ep.code_filter_field}="{code}")'
        data = self._datacenter_query(ep, filter_str=filter_str, page_size=page_size)
        rows = []
        for row in data:
            close = row.get("CLOSE_PRICE") or 0
            deal_price = row.get("DEAL_PRICE") or 0
            premium = ((deal_price / close - 1) * 100) if close else 0
            rows.append({
                "date": str(row.get("TRADE_DATE", ""))[:10],
                "price": deal_price,
                "close": close,
                "premium_pct": round(premium, 2),
                "vol": row.get("DEAL_VOLUME", 0),
                "amount": row.get("DEAL_AMT", 0),
                "buyer": row.get("BUYER_NAME", ""),
                "seller": row.get("SELLER_NAME", ""),
            })
        return rows

    # ------------------------------------------------------------------
    # 股东户数变化 (Holder Number Change)
    # ------------------------------------------------------------------

    def get_holder_num_change(self, code: str, page_size: int = 10) -> list[dict]:
        """Get shareholder count change (quarterly)."""
        code = normalize_stock_code(code)
        ep = ENDPOINTS.HOLDER_NUM
        filter_str = f'({ep.code_filter_field}="{code}")'
        data = self._datacenter_query(ep, filter_str=filter_str, page_size=page_size)
        rows = []
        for row in data:
            rows.append({
                "date": str(row.get("END_DATE", ""))[:10],
                "holder_num": row.get("HOLDER_NUM", 0),
                "change_num": row.get("HOLDER_NUM_CHANGE", 0),
                "change_ratio": row.get("HOLDER_NUM_RATIO", 0),
                "avg_shares": row.get("AVG_FREE_SHARES", 0),
            })
        return rows

    # ------------------------------------------------------------------
    # 分红送转 (Dividend)
    # ------------------------------------------------------------------

    def get_dividend(self, code: str, page_size: int = 20) -> list[dict]:
        """Get dividend history."""
        code = normalize_stock_code(code)
        ep = ENDPOINTS.DIVIDEND
        filter_str = f'({ep.code_filter_field}="{code}")'
        data = self._datacenter_query(ep, filter_str=filter_str, page_size=page_size)
        rows = []
        for row in data:
            rows.append({
                "date": str(row.get("EX_DIVIDEND_DATE", ""))[:10],
                "bonus_rmb": row.get("PRETAX_BONUS_RMB", 0),
                "transfer_ratio": row.get("TRANSFER_RATIO", 0),
                "bonus_ratio": row.get("BONUS_RATIO", 0),
                "plan": row.get("ASSIGN_PROGRESS", ""),
            })
        return rows

    # ------------------------------------------------------------------
    # 资金流向 (Fund Flow) — push2 APIs
    # ------------------------------------------------------------------

    def _parse_push2_kline(
        self, lines: list[str], fields: tuple[str, ...], min_parts: int = 6
    ) -> list[dict[str, Any]]:
        """Parse push2 comma-separated kline strings.

        Field 0 is always a string (time or date); remaining fields are
        numeric with ``"-"`` treated as 0.
        """
        rows: list[dict[str, Any]] = []
        for line in lines:
            parts = line.split(",")
            if len(parts) < min_parts:
                continue
            row: dict[str, Any] = {fields[0]: parts[0]}
            for i in range(1, len(fields)):
                val = parts[i] if i < len(parts) else "-"
                row[fields[i]] = float(val) if val != "-" else 0.0
            rows.append(row)
        return rows

    _FUND_FLOW_MINUTE_FIELDS = ("time", "main_net", "small_net", "mid_net", "large_net", "super_net")

    def get_fund_flow_minute(self, code: str) -> list[dict]:
        """Get minute-level capital flow (intraday)."""
        code = normalize_stock_code(code)
        lines = self._push2_query(ENDPOINTS.FUND_FLOW_MINUTE, self._secid(code), timeout=10)
        return self._parse_push2_kline(lines, self._FUND_FLOW_MINUTE_FIELDS, min_parts=6)

    _FUND_FLOW_DAILY_FIELDS = ("date", "main_net", "small_net", "mid_net", "large_net", "super_net")

    def get_fund_flow_120d(self, code: str) -> list[dict]:
        """Get 120-day capital flow history."""
        code = normalize_stock_code(code)
        lines = self._push2_query(ENDPOINTS.FUND_FLOW_DAILY, self._secid(code))
        return self._parse_push2_kline(lines, self._FUND_FLOW_DAILY_FIELDS, min_parts=7)

    # ------------------------------------------------------------------
    # 研究报告 (Research Reports) — reportapi
    # ------------------------------------------------------------------

    def get_reports(self, code: str, max_pages: int = 5) -> list[dict]:
        """Get research report list for a stock."""
        code = normalize_stock_code(code)
        session = requests.Session()
        session.headers.update({"User-Agent": UA, "Referer": "https://data.eastmoney.com/"})
        all_records = []
        for page in range(1, max_pages + 1):
            params = {
                "industryCode": "*", "pageSize": "100", "industry": "*",
                "rating": "*", "ratingChange": "*",
                "beginTime": "2000-01-01", "endTime": "2030-01-01",
                "pageNo": str(page), "fields": "", "qType": "0",
                "orgCode": "", "code": code, "rcode": "",
                "p": str(page), "pageNum": str(page), "pageNumber": str(page),
            }
            try:
                r = session.get(ENDPOINTS.REPORT_LIST_URL, params=params, timeout=30)
                d = r.json()
                rows = d.get("data") or []
                if not rows:
                    break
                all_records.extend(rows)
                if page >= (d.get("TotalPage", 1) or 1):
                    break
            except Exception as e:
                logger.warning(f"[EastMoneyFetcher] reports failed page {page}: {e}")
                break
        return [
            {
                "title": r.get("title", ""),
                "publish_date": (r.get("publishDate") or "")[:10],
                "org": r.get("orgSName", ""),
                "info_code": r.get("infoCode", ""),
                "rating": r.get("emRatingName", ""),
                "predict_eps_this": r.get("predictThisYearEps"),
                "predict_eps_next": r.get("predictNextYearEps"),
                "predict_eps_next2": r.get("predictNextTwoYearEps"),
            }
            for r in all_records
        ]

    def get_report_pdf_url(self, info_code: str) -> str | None:
        if not info_code:
            return None
        return ENDPOINTS.PDF_URL_TPL.format(info_code=info_code)

    def download_report_pdf(self, info_code: str, target_dir: str = "./reports") -> str | None:
        url = self.get_report_pdf_url(info_code)
        if not url:
            return None
        try:
            r = requests.get(
                url,
                headers={"User-Agent": UA, "Referer": "https://data.eastmoney.com/"},
                timeout=60,
            )
            if r.status_code == 200 and len(r.content) >= 1024:
                target = Path(target_dir) / f"{info_code}.pdf"
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(r.content)
                return str(target)
        except Exception as e:
            logger.warning(f"[EastMoneyFetcher] PDF download failed: {e}")
        return None

    # ------------------------------------------------------------------
    # News search (https://search-api-web.eastmoney.com/search/jsonp)
    # ------------------------------------------------------------------

    _NEWS_SEARCH_URL = "https://search-api-web.eastmoney.com/search/jsonp"
    _NEWS_USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    _NEWS_REFERER = "https://so.eastmoney.com/news/s"

    def search_news(
        self,
        q: str,
        from_date: str | None = None,
        to_date: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """Search EastMoney news by keyword.

        Returns a list of normalized news-item dicts; see spec §6.1 for schema.
        Raises DataFetchError on upstream failure.
        """
        if not q or len(q) > 200:
            raise DataFetchError(f"[EastMoneyFetcher] search_news: invalid q (len={len(q) if q else 0})")
        if not (1 <= limit <= 100):
            raise DataFetchError(f"[EastMoneyFetcher] search_news: limit must be 1..100 (got {limit})")

        import json as _json
        import os as _os
        import random as _random
        import re as _re

        cb = f"jQuery_news_{_os.getpid()}_{_random.randint(0, 99999)}"
        inner = {
            "uid": "",
            "keyword": q,
            "type": ["cmsArticleWebOld"],
            "client": "web",
            "clientType": "web",
            "clientVersion": "curr",
            "param": {
                "cmsArticleWebOld": {
                    "searchScope": "default",
                    "sort": "default",
                    "pageIndex": 1,
                    "pageSize": limit,
                    "preTag": "<em>",
                    "postTag": "</em>",
                }
            },
        }
        params = {"cb": cb, "param": _json.dumps(inner, ensure_ascii=False)}
        headers = {
            "User-Agent": self._NEWS_USER_AGENT,
            "Referer": self._NEWS_REFERER,
        }

        logger.info(f"[EastMoneyFetcher] news search q={q!r} limit={limit}")
        try:
            resp = requests.get(
                self._NEWS_SEARCH_URL, params=params, headers=headers, timeout=15
            )
        except Exception as e:
            raise DataFetchError(f"[EastMoneyFetcher] search_news network error: {e}") from e

        if resp.status_code != 200:
            raise DataFetchError(
                f"[EastMoneyFetcher] search_news HTTP {resp.status_code}"
            )

        text = resp.text.strip()
        # Strip JSONP wrapper: "jQuery_cb_name({"...": ...})"
        m = _re.match(r"^\w+\((.*)\)$", text, _re.DOTALL)
        if not m:
            raise DataFetchError("[EastMoneyFetcher] search_news: response not JSONP")
        try:
            payload = _json.loads(m.group(1))
        except _json.JSONDecodeError as e:
            raise DataFetchError(f"[EastMoneyFetcher] search_news: bad JSON: {e}") from e

        if payload.get("code") != 0:
            raise DataFetchError(
                f"[EastMoneyFetcher] search_news API code={payload.get('code')} msg={payload.get('msg')}"
            )

        records = (payload.get("result") or {}).get("cmsArticleWebOld") or []
        out: list[dict] = []
        for rec in records:
            try:
                item = self._normalize_news_item(rec)
            except (KeyError, TypeError, ValueError) as e:
                logger.warning(f"[EastMoneyFetcher] skipping malformed record: {e}")
                continue
            if from_date and item["publish_date"] < from_date:
                continue
            if to_date and item["publish_date"] > to_date:
                continue
            out.append(item)
        return out

    @staticmethod
    def _normalize_news_item(rec: dict) -> dict:
        """Convert one upstream record to the spec's NewsItem dict.

        Raises KeyError/TypeError/ValueError on missing critical fields,
        which the caller treats as a skip.
        """
        from urllib.parse import urlparse

        url = rec["url"]
        date_str = rec["date"][:10]  # "YYYY-MM-DD HH:MM:SS" -> "YYYY-MM-DD"
        return {
            "title": rec["title"].replace("<em>", "").replace("</em>", ""),
            "url": url,
            "source_domain": urlparse(url).netloc,
            "publish_date": date_str,
            "snippet": rec.get("content", "").replace("<em>", "").replace("</em>", ""),
            "media_name": rec.get("mediaName", ""),
        }
