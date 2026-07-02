"""EastMoneyFetcher class — datacenter-web / push2 / reportapi endpoints.

Mixed with ``BoardsMixin`` (push2 clist for board listings) and
``NewsMixin`` (search-api-web / np-listapi / np-anotice-stock /
np-weblist for news + announcements + 7×24 flash) to compose the full
EastMoney upstream coverage in one class — no parallel fetcher classes
([[extend-not-spawn-fetcher]] rule).

Endpoint coverage of THIS module:
- datacenter-web.eastmoney.com: 龙虎榜 (dragon tiger), 融资融券, 大宗交易,
  股东户数, 分红送转
- push2/push2his.eastmoney.com: 资金流 (minute-level + 120-day)
- reportapi.eastmoney.com: 研报列表
- pdf.dfcfw.com: 研报 PDF

See the two mixin modules for the rest.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from curl_cffi import requests as cffi_requests

from ...base import BaseFetcher, DataCapability, DataFetchError
from ...utils.code_converter import to_eastmoney_secid
from ...utils.normalize import normalize_stock_code
from ._boards_mixin import BoardsMixin
from ._endpoints import DATACENTER_URL, ENDPOINTS, UA
from ._news_mixin import NewsMixin

logger = logging.getLogger(__name__)


class EastMoneyFetcher(NewsMixin, BoardsMixin, BaseFetcher):
    """EastMoney data-centre API fetcher for financial data.

    Composition order: ``NewsMixin`` → ``BoardsMixin`` → ``BaseFetcher``.
    MRO walks left-to-right, so attribute lookups prefer the mixins for
    ``_STOCK_BOARDS_*`` / ``_BOARD_*`` / ``_NEWS_*`` constants and methods,
    and fall through to ``BaseFetcher`` for everything else (capability
    flags, circuit-breaker plumbing, market detection).

    curl_cffi note
    --------------
    Every HTTP call goes through ``self._session``, a
    ``cffi_requests.Session(impersonate="chrome120")``. This matches
    Chrome's TLS handshake + HTTP/2 fingerprint at the CDN/WAF layer (JA3
    defence). Drop-in for ``requests.Session`` for every operation we
    use (headers / cookies / .get / timeout).
    """

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
        | DataCapability.NEWS_FLASH
        | DataCapability.STOCK_BOARD  # migrated from AkshareFetcher
        | DataCapability.STOCK_NEWS  # per-stock news feed (np-listapi)
        | DataCapability.ANNOUNCEMENT  # joins failover chain alongside CninfoFetcher
    )

    def is_available(self) -> bool:
        return True

    def _normalize_data(self, df, stock_code):
        raise DataFetchError("EastMoneyFetcher does not support historical K-line data")

    # ==================================================================
    # Shared query helpers — datacenter + push2
    # ==================================================================

    def _datacenter_query(
        self,
        endpoint,
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
        # Use the shared curl_cffi Session (Chrome 120 impersonation) for
        # the same JA3 / TLS-fingerprint defence we rely on for the news
        # search endpoint. Per-call headers below override the news-search
        # defaults (Referer / User-Agent) so each eastmoney subdomain sees
        # the Origin/Referer the original code intended.
        headers = {"User-Agent": UA, "Referer": "https://data.eastmoney.com/"}
        try:
            r = self._session.get(DATACENTER_URL, params=params, headers=headers, timeout=15)
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
        # Same Session reuse rationale as _datacenter_query: Chrome 120
        # impersonation + per-call Referer override for the quote subdomain.
        headers = {"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"}
        try:
            r = self._session.get(endpoint["url"], params=params, headers=headers, timeout=timeout)
            d = r.json()
            return d.get("data", {}).get("klines") or []
        except Exception as e:
            logger.warning(f"[EastMoneyFetcher] push2 query failed: {e}")
            return []

    # ==================================================================
    # 板块 K 线 (Board K-line) — push2his board kline endpoint
    # ==================================================================
    #
    # EastMoney's quote subdomain uses the SAME `/api/qt/stock/kline/get`
    # endpoint for both stocks and boards — only the `secid` differs:
    #   stock:  "0.000725" / "1.600519" / "0.300059" ...
    #   board:  "90.BK0996" / "90.BK0806" ...   (90 = board market prefix)
    #
    # See ``ENDPOINTS.BOARD_KLINE['freq_map']`` for the supported klt (period)
    # values. The endpoint returns `data.klines` as a list of comma-separated
    # strings
    # (`date,open,high,low,close,volume,amount,amplitude,pct_chg,change_amount,turnover_rate`).

    @staticmethod
    def _board_secid(board_code: str) -> str:
        """Build EastMoney board secid from a board code.

        Accepts any of ``"BK0996"`` / ``"bk0996"`` / ``"0996"`` / ``"996"``
        — case-insensitive prefix, length-tolerant suffix (leading zeros are
        kept; we only normalize the prefix). Returns the canonical
        ``"90.BK0996"`` form. Anything else (non-digit suffix) is passed
        through so the upstream 4xx gives a clearer error than we'd raise
        locally.
        """
        code = (board_code or "").strip()
        if not code:
            return "90.BK"
        upper = code.upper()
        if upper.startswith("BK"):
            # Preserve the digit portion verbatim (keep leading zeros), just
            # uppercase the prefix so callers can pass "bk0806" too.
            digits = code[2:]
            code = f"BK{digits}"
        elif code.isdigit():
            code = f"BK{code}"
        return f"90.{code}"

    @staticmethod
    def _parse_board_kline(raw: str) -> dict | None:
        """Parse one ``data.klines`` comma string to a row dict.

        Upstream field order (12 fields):
            date, open, high, low, close, volume, amount,
            amplitude, pct_chg, change_amount, turnover_rate, _
        Trailing fields after position 11 are not surfaced (unknown).
        ``fqt`` (复权) is meaningless for boards but accepted as a no-op
        upstream — we don't apply any post-processing here.

        Returns ``None`` on malformed rows (caller skips).
        """
        if not raw:
            return None
        parts = raw.split(",")
        if len(parts) < 11:
            return None
        try:
            return {
                "date": parts[0],
                "open": float(parts[1]),
                "high": float(parts[2]),
                "low": float(parts[3]),
                "close": float(parts[4]),
                "volume": int(float(parts[5])),
                "amount": float(parts[6]),
                "amplitude": float(parts[7]),
                "pct_chg": float(parts[8]),
                "change_amount": float(parts[9]),
                "turnover_rate": float(parts[10]),
            }
        except (TypeError, ValueError):
            return None

    def get_board_history(
        self,
        board_code: str,
        frequency: str = "d",
        days: int = 30,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
        source: str | None = None,
        **kwargs,
    ) -> list[dict]:
        """K-line for a board via push2his.

        Args:
            board_code: Board code (e.g. ``"BK0996"`` or ``"0996"``).
                EastMoney format. The ``BK`` prefix is optional.
            frequency: One of ``d`` / ``w`` / ``m`` / ``5m`` / ``15m`` /
                ``30m`` / ``60m``. Mapping:
                  d→101, w→102, m→103, 5m→5, 15m→15, 30m→30, 60m→60
                (verified against emcharts.js — see
                ``docs/stock-board-reverse-index-design-2026-07-01.md``).
            days: Used when ``start_date`` is not given; controls ``lmt``
                (bar count). Capped at 800 to avoid push2his auto-escalating
                klt from daily→weekly→monthly when ``lmt`` ≥ 1000.
            start_date: ``YYYY-MM-DD`` — inclusive lower bound (applied
                post-fetch).
            end_date: ``YYYY-MM-DD`` — inclusive upper bound (applied
                post-fetch).
            source: Source slug. Ignored by EastMoneyFetcher (kept for
                signature parity with zzshare's ``get_board_history``).
            **kwargs: Future-proof (e.g. ``adjust`` / ``fqt``).

        Returns:
            list[dict] — one row per bar, sorted oldest → newest. Each row
            has keys: ``date, open, high, low, close, volume, amount,
            amplitude, pct_chg, change_amount, turnover_rate``. Empty list
            on upstream failure (logged at WARNING).

        Raises:
            DataFetchError: ``frequency`` not in ``ENDPOINTS.BOARD_KLINE['freq_map']``.
        """
        freq_map = ENDPOINTS.BOARD_KLINE["freq_map"]
        freq_key = (frequency or "d").lower()
        klt = freq_map.get(freq_key)
        if klt is None:
            raise DataFetchError(
                f"[EastMoneyFetcher] get_board_history: unsupported frequency "
                f"{frequency!r}; valid: {sorted(freq_map.keys())}"
            )

        secid = self._board_secid(board_code)

        # Cap lmt at 800 to avoid emcharts.js's auto-escalation rule:
        #   lmt ≥ 1000 → klt forced to 102 (weekly)
        #   lmt ≥ 5000 → klt forced to 103 (monthly)
        # Caller's chosen klt is what they want; let it stand.
        # Route layer caps `days` at 365 via Query(le=365); the 800 cap only kicks in for non-route callers.
        lmt = max(1, min(int(days), 800))

        params: dict[str, str] = {
            "secid": secid,
            "fields1": ENDPOINTS.BOARD_KLINE["fields1"],
            "fields2": ENDPOINTS.BOARD_KLINE["fields2"],
            "klt": str(klt),
            "fqt": "1",
            "end": "20500101",  # far-future → upstream returns last `lmt` bars
            "lmt": str(lmt),
            "ut": ENDPOINTS.BOARD_KLINE["ut"],
        }
        headers = {"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"}
        try:
            r = self._session.get(
                ENDPOINTS.BOARD_KLINE["url"],
                params=params,
                headers=headers,
                timeout=15,
            )
            raws: list[str] = r.json().get("data", {}).get("klines") or []
        except Exception as e:
            logger.warning(
                f"[EastMoneyFetcher] get_board_history({board_code}, freq={frequency}) failed: {e}"
            )
            return []

        rows: list[dict] = []
        for raw in raws:
            row = self._parse_board_kline(raw)
            if row is not None:
                rows.append(row)

        # Sort ascending by date (upstream order is already asc, defensive).
        rows.sort(key=lambda r: r["date"])

        # Date-range filter — start_date/end_date win over days (matches zzshare's contract).
        if start_date:
            rows = [r for r in rows if r["date"] >= start_date]
        if end_date:
            rows = [r for r in rows if r["date"] <= end_date]

        return rows

    def _secid(self, code: str) -> str:
        """Build EastMoney secid. Delegates to ``to_eastmoney_secid``."""
        return to_eastmoney_secid(code)

    def _datacenter_records(
        self,
        endpoint,
        code: str,
        *,
        page_size: int,
        mapper: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Query a code-keyed datacenter-web endpoint and map each row.

        Shared boilerplate for the four datacenter endpoints that filter by
        stock code and project each row to a normalized dict (margin trading,
        block trade, holder-number change, dividend). Lets us collapse ~75
        lines of copy-paste into a single helper plus four tiny wrappers.
        Each wrapper keeps its own field-mapping logic where it belongs.

        Args:
            endpoint: ``_DCEndpoint`` entry from ``ENDPOINTS``.
            code: 6-digit stock code (will be normalized).
            page_size: Row cap passed through to ``_datacenter_query``.
            mapper: Pure per-row transformer (upstream row → response row).

        Returns:
            List of mapped rows, one per upstream record. Empty list on no
            upstream data or upstream error.
        """
        code = normalize_stock_code(code)
        filter_str = f'({endpoint.code_filter_field}="{code}")'
        data = self._datacenter_query(endpoint, filter_str=filter_str, page_size=page_size)
        return [mapper(row) for row in data]

    # ==================================================================
    # 龙虎榜 (Dragon Tiger Board) — per-stock
    # ==================================================================

    def get_dragon_tiger(self, code: str, trade_date: str = "", look_back: int = 30) -> dict:
        """Get dragon tiger board data for a single stock.

        Returns: {records: [...], seats: {buy: [...], sell: [...]}, institution: {...}}
        """
        code = normalize_stock_code(code)
        if not trade_date:
            trade_date = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=look_back)).strftime(
            "%Y-%m-%d"
        )

        ep = ENDPOINTS.DRAGON_TIGER
        filter_str = (
            f"(TRADE_DATE>='{start}')(TRADE_DATE<='{trade_date}')(SECURITY_CODE=\"{code}\")"
        )
        data = self._datacenter_query(ep, filter_str=filter_str)

        records = []
        for row in data:
            records.append(
                {
                    "date": str(row.get("TRADE_DATE", ""))[:10],
                    "reason": row.get("EXPLANATION", ""),
                    "net_buy_wan": round((row.get("BILLBOARD_NET_AMT") or 0) / 10000, 1),
                    "turnover_pct": round(float(row.get("TURNOVERRATE") or 0), 2),
                }
            )

        seats: dict[str, list[dict]] = {"buy": [], "sell": []}
        institution: dict[str, float] = {"buy_amt": 0, "sell_amt": 0, "net_amt": 0}
        if records:
            latest_date = records[0]["date"]
            code_filter = f"(TRADE_DATE='{latest_date}')(SECURITY_CODE=\"{code}\")"

            buy_data = self._datacenter_query(
                ENDPOINTS.DRAGON_TIGER_BUY_SEATS,
                filter_str=code_filter,
            )
            for row in buy_data[:5]:
                seats["buy"].append(
                    {
                        "name": row.get("OPERATEDEPT_NAME", ""),
                        "buy_wan": round((row.get("BUY") or 0) / 10000, 1),
                        "sell_wan": round((row.get("SELL") or 0) / 10000, 1),
                        "net_wan": round((row.get("NET") or 0) / 10000, 1),
                    }
                )
            sell_data = self._datacenter_query(
                ENDPOINTS.DRAGON_TIGER_SELL_SEATS,
                filter_str=code_filter,
            )
            for row in sell_data[:5]:
                seats["sell"].append(
                    {
                        "name": row.get("OPERATEDEPT_NAME", ""),
                        "buy_wan": round((row.get("BUY") or 0) / 10000, 1),
                        "sell_wan": round((row.get("SELL") or 0) / 10000, 1),
                        "net_wan": round((row.get("NET") or 0) / 10000, 1),
                    }
                )
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
            stocks.append(
                {
                    "code": row.get("SECURITY_CODE", ""),
                    "name": row.get("SECURITY_NAME_ABBR", ""),
                    "reason": row.get("EXPLANATION", ""),
                    "close": row.get("CLOSE_PRICE", 0),
                    "change_pct": round(float(row.get("CHANGE_RATE") or 0), 2),
                    "net_buy_wan": round(net_buy, 1),
                    "buy_wan": round((row.get("BILLBOARD_BUY_AMT") or 0) / 10000, 1),
                    "sell_wan": round((row.get("BILLBOARD_SELL_AMT") or 0) / 10000, 1),
                    "turnover_pct": round(float(row.get("TURNOVERRATE") or 0), 2),
                }
            )
        return {"date": trade_date, "total": len(stocks), "stocks": stocks}

    # ------------------------------------------------------------------
    # 融资融券 / 大宗交易 / 股东户数 / 分红 (datacenter factory consumers)
    # ------------------------------------------------------------------

    def get_margin_trading(self, code: str, page_size: int = 30) -> list[dict]:
        """Get margin trading data."""
        return self._datacenter_records(
            ENDPOINTS.MARGIN_TRADING,
            code,
            page_size=page_size,
            mapper=lambda r: {
                "date": str(r.get("DATE", ""))[:10],
                "rzye": r.get("RZYE", 0),
                "rzmre": r.get("RZMRE", 0),
                "rzche": r.get("RZCHE", 0),
                "rqye": r.get("RQYE", 0),
                "rqmcl": r.get("RQMCL", 0),
                "rqchl": r.get("RQCHL", 0),
                "rzrqye": r.get("RZRQYE", 0),
            },
        )

    def get_block_trade(self, code: str, page_size: int = 20) -> list[dict]:
        """Get block trade records.

        Computes ``premium_pct = (deal_price / close - 1) * 100`` per row
        before projecting — this is the one endpoint whose mapper needs
        a small pre-computation, hence the named function instead of
        a lambda.
        """

        def mapper(r: dict) -> dict:
            close = r.get("CLOSE_PRICE") or 0
            deal_price = r.get("DEAL_PRICE") or 0
            premium = ((deal_price / close - 1) * 100) if close else 0
            return {
                "date": str(r.get("TRADE_DATE", ""))[:10],
                "price": deal_price,
                "close": close,
                "premium_pct": round(premium, 2),
                "vol": r.get("DEAL_VOLUME", 0),
                "amount": r.get("DEAL_AMT", 0),
                "buyer": r.get("BUYER_NAME", ""),
                "seller": r.get("SELLER_NAME", ""),
            }

        return self._datacenter_records(
            ENDPOINTS.BLOCK_TRADE,
            code,
            page_size=page_size,
            mapper=mapper,
        )

    def get_holder_num_change(self, code: str, page_size: int = 10) -> list[dict]:
        """Get shareholder count change (quarterly)."""
        return self._datacenter_records(
            ENDPOINTS.HOLDER_NUM,
            code,
            page_size=page_size,
            mapper=lambda r: {
                "date": str(r.get("END_DATE", ""))[:10],
                "holder_num": r.get("HOLDER_NUM", 0),
                "change_num": r.get("HOLDER_NUM_CHANGE", 0),
                "change_ratio": r.get("HOLDER_NUM_RATIO", 0),
                "avg_shares": r.get("AVG_FREE_SHARES", 0),
            },
        )

    def get_dividend(self, code: str, page_size: int = 20) -> list[dict]:
        """Get dividend history."""
        return self._datacenter_records(
            ENDPOINTS.DIVIDEND,
            code,
            page_size=page_size,
            mapper=lambda r: {
                "date": str(r.get("EX_DIVIDEND_DATE", ""))[:10],
                "bonus_rmb": r.get("PRETAX_BONUS_RMB", 0),
                "transfer_ratio": r.get("TRANSFER_RATIO", 0),
                "bonus_ratio": r.get("BONUS_RATIO", 0),
                "plan": r.get("ASSIGN_PROGRESS", ""),
            },
        )

    # ==================================================================
    # 资金流向 (Fund Flow) — push2 APIs
    # ==================================================================

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

    _FUND_FLOW_MINUTE_FIELDS = (
        "time",
        "main_net",
        "small_net",
        "mid_net",
        "large_net",
        "super_net",
    )

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

    # ==================================================================
    # 研究报告 (Research Reports) — reportapi + PDF
    # ==================================================================

    def get_reports(self, code: str, max_pages: int = 5) -> list[dict]:
        """Get research report list for a stock."""
        code = normalize_stock_code(code)
        # Reuse the shared curl_cffi Session; pass per-page headers to keep
        # the Referer/UA per-page (the original code used a per-call local
        # Session for connection reuse, which the shared Session also gives
        # us — bonus, we get Chrome 120 fingerprint matching the rest of
        # the fetcher).
        all_records = []
        for page in range(1, max_pages + 1):
            params = {
                "industryCode": "*",
                "pageSize": "100",
                "industry": "*",
                "rating": "*",
                "ratingChange": "*",
                "beginTime": "2000-01-01",
                "endTime": datetime.now().strftime("%Y-%m-%d"),
                "pageNo": str(page),
                "fields": "",
                "qType": "0",
                "orgCode": "",
                "code": code,
                "rcode": "",
                "p": str(page),
                "pageNum": str(page),
                "pageNumber": str(page),
            }
            try:
                r = self._session.get(
                    ENDPOINTS.REPORT_LIST_URL,
                    params=params,
                    headers={"User-Agent": UA, "Referer": "https://data.eastmoney.com/"},
                    timeout=30,
                )
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
            r = self._session.get(
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

    # ==================================================================
    # __init__ — single source of truth for Session + warmup flag.
    # Lives here (not in a mixin) because every mixin reads
    # ``self._session`` / ``self._news_warmed`` — placing init in this
    # central class keeps the wiring coherent.
    # ==================================================================

    def __init__(self) -> None:
        super().__init__()
        # curl_cffi Session with Chrome 120 impersonation matches Chrome's
        # TLS handshake + HTTP/2 fingerprint, defeating JA3-style fingerprint
        # detection at the CDN/WAF layer. Drop-in for requests.Session for
        # every operation we use (headers / cookies / .get / timeout).
        self._session = cffi_requests.Session(impersonate="chrome120")
        self._session.headers.update(self._NEWS_SEARCH_BASE_HEADERS)
        self._news_warmed = False
