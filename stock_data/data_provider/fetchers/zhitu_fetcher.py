"""
Zhitu fetcher for A-share realtime quote (Priority 99).

API: https://api.zhituapi.com/hs/real/ssjy/{stock_code}?token={token}
Token configured via ZHITU_TOKEN environment variable.
"""

import logging
import os
import re
from datetime import date, timedelta

import pandas as pd

from ..base import BaseFetcher, DataCapability, DataFetchError, normalize_stock_code
from ..core.types import RealtimeSource, UnifiedRealtimeQuote, safe_float, safe_int
from ..utils.code_converter import to_zhitu_format, to_zhitu_market_suffix
from ..utils.normalize import split_concepts as _split_concepts

logger = logging.getLogger(__name__)

# API base URL
ZHITU_API_BASE = "https://api.zhituapi.com"

# Zhitu /hs/index/tree type2 → (type, subtype) mapping
ZHITU_TYPE2_MAPPING: dict[int, tuple[str, str]] = {
    0: ("industry", "申万行业"),
    1: ("industry", "申万二级"),
    2: ("concept", "热门概念"),
    3: ("concept", "概念板块"),
    4: ("concept", "地域板块"),
    5: ("industry", "证监会行业"),
    6: ("index", "分类"),
    7: ("index", "指数成分"),
    8: ("special", "风险警示"),
    9: ("index", "大盘指数"),
    10: ("special", "次新股"),
    11: ("special", "沪港通"),
    12: ("special", "深港通"),
}

# type → 合法 subtype 集合（与 persistence/board.py 保持同步）
ZHITU_SUBTYPES_BY_TYPE: dict[str, set[str]] = {
    "industry": {"申万行业", "申万二级", "证监会行业"},
    "concept": {"热门概念", "概念板块", "地域板块"},
    "index": {"分类", "指数成分", "大盘指数"},
    "special": {"风险警示", "次新股", "沪港通", "深港通"},
}


class ZhituFetcher(BaseFetcher):
    """Zhitu API fetcher for A-share realtime quotes (no historical data)."""

    name = "ZhituFetcher"
    priority = int(os.getenv("ZHITU_PRIORITY", "5"))
    supported_markets: set[str] = {"csi"}
    supported_data_types = (
        DataCapability.STOCK_REALTIME_QUOTE
        | DataCapability.STOCK_ZT_POOL
        | DataCapability.STOCK_INFO
        | DataCapability.STOCK_KLINE
        | DataCapability.STOCK_LIST
        | DataCapability.STOCK_BOARD
        | DataCapability.DIVIDEND
        | DataCapability.FUND_FLOW
        | DataCapability.HOLDER_NUM
    )

    def __init__(self):
        self._token = os.getenv("ZHITU_TOKEN", "").strip()

    def is_available(self) -> bool:
        """Check if Zhitu API token is configured."""
        return bool(self._token)

    def supports_kline(self, period, adjust, market, asset):
        # Zhitu: minutes only (5/15/30/60) + forces no adjust.
        return period in ("5", "15", "30", "60") and adjust in ("", None)

    def unavailable_reason(self) -> str | None:
        """Return a human-readable reason this fetcher is unavailable, or None.

        Mirrors the actual availability check so the explorer's docs can
        surface *why* the fetcher didn't register. Derived from real state
        (no hardcoded "token not set" literal that could drift from
        is_available()).
        """
        if not self._token:
            return f"ZHITU_TOKEN environment variable not set (required by {self.name})"
        return None

    def _convert_code(self, stock_code: str) -> str:
        """Convert to Zhitu format. Delegates to ``to_zhitu_format``."""
        return to_zhitu_format(stock_code)

    def _market_suffix(self, stock_code: str) -> str:
        """Zhitu market suffix. Delegates to ``to_zhitu_market_suffix``."""
        return to_zhitu_market_suffix(stock_code)

    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        """Zhitu does not support historical data normalization."""
        raise DataFetchError("ZhituFetcher does not support historical K-line data")

    def get_realtime_quote(self, stock_code: str) -> UnifiedRealtimeQuote | None:
        """Get realtime quote from Zhitu API.

        Args:
            stock_code: Stock code (e.g., 600519, 000001)

        Returns:
            UnifiedRealtimeQuote with realtime data, or None if unavailable.
        """
        if not self.is_available():
            logger.warning("[ZhituFetcher] ZHITU_TOKEN not configured")
            return None

        code = self._convert_code(stock_code)
        data = self._fetch_json(
            f"/hs/real/ssjy/{code}",
            op_label=f"quote {stock_code}",
        )

        # Zhitu returns a dict directly (not a list). _fetch_json already
        # returns None for transport errors AND for the {"detail": ...}
        # upstream error envelope; both cases short-circuit to None here.
        if not isinstance(data, dict):
            logger.warning(
                f"[ZhituFetcher] Unexpected response type for {stock_code}: {type(data)}"
            )
            return None

        if not data:
            logger.warning(f"[ZhituFetcher] Empty response for {stock_code}")
            return None

        row = data

        return UnifiedRealtimeQuote(
            code=normalize_stock_code(stock_code),
            name=str(row.get("nm", "")),
            source=RealtimeSource.ZHITU,
            price=safe_float(row.get("p")),
            change_pct=safe_float(row.get("pc")),
            change_amount=safe_float(row.get("ud")),
            volume=safe_int(row.get("v"), 0) * 100,  # 手→股 per spec §3.4
            amount=safe_float(row.get("cje")),
            open_price=safe_float(row.get("o")),
            high=safe_float(row.get("h")),
            low=safe_float(row.get("l")),
            pre_close=safe_float(row.get("yc")),
            amplitude=safe_float(row.get("zf")),
            volume_ratio=safe_float(row.get("lb")),
            turnover_rate=safe_float(row.get("hs")),
            pe_ratio=safe_float(row.get("pe")),
            pb_ratio=safe_float(row.get("sjl")),
            total_mv=safe_float(row.get("sz")),
            circ_mv=safe_float(row.get("lt")),
        )

    def get_intraday_data(
        self, stock_code: str, period: str = "5", adjust: str = ""
    ) -> pd.DataFrame | None:
        """Get intraday minute-level data from Zhitu history API.

        API: https://api.zhituapi.com/hs/history/{code}.{market}/{period}/{adjust}?token={token}&st={date}&et={date}

        Args:
            stock_code: Stock code (e.g., 600519, 000001)
            period: Minute period - "5", "15", "30", "60" (NOT "1")
            adjust: Adjustment type - ""=不复权, "qfq"=前复权, "hfq"=后复权

        Returns:
            DataFrame with columns: time, open, high, low, close, volume, amount
            or None if not supported or period=1 (not supported by Zhitu).
        """
        # Zhitu doesn't support period=1 — checked BEFORE the network call
        # so we can raise DataFetchError (lets manager try next fetcher)
        # instead of swallowing it via _fetch_json's None-return.
        if period == "1":
            raise DataFetchError("ZhituFetcher does not support period=1")

        if not self.is_available():
            logger.warning("[ZhituFetcher] ZHITU_TOKEN not configured")
            return None

        code = normalize_stock_code(stock_code)
        market = self._market_suffix(stock_code)
        symbol = f"{code}{market}"

        # Map adjust: API format
        adj_map = {"": "n", "qfq": "f", "hfq": "b"}
        adj_value = adj_map.get(adjust, "n")

        # Get latest trade date
        from ..persistence.trade_calendar import get_latest_cached_trade_date

        latest_date = get_latest_cached_trade_date()
        if not latest_date:
            latest_date = date.today().strftime("%Y%m%d")
        else:
            latest_date = latest_date.replace("-", "")

        data = self._fetch_json(
            f"/hs/history/{symbol}/{period}/{adj_value}",
            params={"st": latest_date, "et": latest_date},
            op_label=f"intraday {stock_code}",
        )

        if not isinstance(data, list):
            logger.warning(f"[ZhituFetcher] Unexpected response type: {type(data)}")
            return None

        if not data:
            return None

        df = pd.DataFrame(data)
        return self._normalize_intraday_zhitu(df)

    def get_zt_pool(self, pool_type: str, date: str) -> list[dict] | None:
        """
        Get ZT (涨跌停) pool data from Zhitu API.

        Args:
            pool_type: Pool type - "zt" (涨停), "dt" (跌停), "zbgc" (炸板)
            date: Pool date in YYYY-MM-DD format

        Returns:
            List of stock dicts with normalized fields, or None if unavailable.
        """
        if not self.is_available():
            logger.warning("[ZhituFetcher] ZHITU_TOKEN not configured")
            return None

        # Map pool_type to Zhitu API path
        path_map = {"zt": "ztgc", "dt": "dtgc", "zbgc": "zbgc"}
        api_path = path_map.get(pool_type)
        if not api_path:
            logger.warning(f"[ZhituFetcher] Unknown pool_type: {pool_type}")
            return None

        data = self._fetch_json(
            f"/hs/pool/{api_path}/{date}",
            op_label=f"ZT pool {pool_type} {date}",
        )

        if not isinstance(data, list):
            logger.warning(f"[ZhituFetcher] Unexpected response type: {type(data)}")
            return None

        # Normalize and return
        return [self._normalize_zt_stock(row, pool_type) for row in data]

    def _normalize_zt_stock(self, row: dict, pool_type: str) -> dict:
        """Normalize Zhitu ZT pool response to standard format."""
        code = row.get("dm", "")
        # Strip exchange prefix: "sz000657" -> "000657", "sh600519" -> "600519"
        if code.startswith(("sh", "sz", "SH", "SZ")):
            code = code[2:]

        return {
            "code": code,
            "name": row.get("mc", ""),
            "price": row.get("p"),
            "change_pct": row.get("zf"),
            "amount": row.get("cje"),
            "circ_mv": row.get("lt"),
            "total_mv": row.get("zsz"),
            "turnover_rate": row.get("hs"),
            "lb_count": row.get("lbc"),
            "first_seal_time": row.get("fbt"),
            "last_seal_time": row.get("lbt"),
            "seal_amount": row.get("zj"),
            "seal_count": row.get("zbc"),
            "zt_count": row.get("tj"),
        }

    def _normalize_intraday_zhitu(self, df: pd.DataFrame) -> pd.DataFrame:
        """Normalize Zhitu history API output."""
        df = df.copy()
        df = df.rename(
            columns={
                "t": "time",
                "o": "open",
                "h": "high",
                "l": "low",
                "c": "close",
                "v": "volume",
                "a": "amount",
            }
        )
        if "time" in df.columns:
            # Zhitu returns ISO format with T, extract HH:MM:SS
            df["time"] = df["time"].astype(str).str[-8:]
        numeric_cols = ["open", "high", "low", "close", "volume", "amount"]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        keep_cols = ["time", "open", "high", "low", "close", "volume", "amount"]
        df = df[[c for c in keep_cols if c in df.columns]]
        return df

    def get_all_stocks(self, market: str = "csi") -> list:
        """Get the full A-share stock list from Zhitu's ``/hs/list/all``.

        Zhitu only supports A-share (``csi``); HK/US return ``[]`` so the
        manager's failover keeps trying other fetchers. Each item is
        ``{"code": <dm>, "name": <mc>, "exchange": <jys>}`` — the
        ``exchange`` value is passed through raw (``"sh"``/``"sz"``);
        persistence normalizes via ``_normalize_exchange``.

        Returns:
            List of stock dicts, or ``[]`` on token absence / HTTP
            failure / parse error. Empty list (not raise) keeps the
            failover loop alive so the next fetcher can try.
        """
        if market != "csi":
            return []
        if not self.is_available():
            logger.warning("[ZhituFetcher] ZHITU_TOKEN not configured")
            return []

        data = self._fetch_json(
            "/hs/list/all",
            op_label="get_all_stocks",
        )

        if not isinstance(data, list):
            logger.warning(
                f"[ZhituFetcher] get_all_stocks unexpected type: {type(data)}"
            )
            return []

        result: list = []
        for row in data:
            if not isinstance(row, dict):
                continue
            code = str(row.get("dm", "")).strip()
            if not code:
                continue
            result.append(
                {
                    "code": code,
                    "name": str(row.get("mc", "")).strip(),
                    "exchange": str(row.get("jys", "")).strip().lower(),
                }
            )
        return result

    def get_stock_info(self, stock_code: str) -> dict | None:
        """公司画像 — Zhitu gs/gsjj 端点 (https://api.zhituapi.com/hs/gs/gsjj/{code}).

        返回归一化的 18 user-data 字段 (source 由 manager 注入)。失败返 None 让 failover 工作。
        """
        if not self.is_available():
            return None
        data = self._fetch_json(
            f"/hs/gs/gsjj/{stock_code}",
            op_label=f"stock_info {stock_code}",
        )
        if not isinstance(data, dict) or "code" not in data:
            logger.warning("[ZhituFetcher] get_stock_info %s: malformed payload", stock_code)
            return None
        return {
            "code":              stock_code,
            "name":              data.get("name", "") or "",
            "ename":             data.get("ename", "") or "",
            "market":            "csi",
            "listed_date":       str(data.get("ldate", "") or ""),
            "delisted_date":     "",
            "total_shares":      safe_float(data.get("totalstock")),
            "float_shares":      safe_float(data.get("flowstock")),
            "concepts":          _split_concepts(data.get("idea", "")),
            "registered_address": data.get("raddr", "") or "",
            "registered_capital": data.get("rcapital", "") or "",
            "legal_representative": data.get("rname", "") or "",
            "business_scope":    data.get("bscope", "") or "",
            "established_date":  str(data.get("rdate", "") or ""),
            "secretary":         data.get("bsname", "") or "",
            "secretary_phone":   data.get("bsphone", "") or "",
            "secretary_email":   data.get("bsemail", "") or "",
        }

    # ---------- board methods ----------

    def _fetch_board_tree(self) -> list[dict] | None:
        """Fetch raw /hs/index/tree response leaves. Returns list or None on failure."""
        if not self.is_available():
            return None
        data = self._fetch_json(
            "/hs/index/tree",
            op_label="_fetch_board_tree",
        )
        if not isinstance(data, list):
            return None
        return [r for r in data if isinstance(r, dict) and r.get("isleaf") == 1]

    def get_all_boards(
        self,
        board_type: str,
        subtype: str | None = None,
        source: str = "zhitu",
        include_quote: bool = False,
    ) -> list[dict]:
        """Get boards of a given type and optional subtype (unified entry).

        Args:
            board_type: one of ``concept / industry / index / special``.
            subtype: source-specific subtype (validated by persistence).
            source: fetcher name (accepted for Manager interface symmetry;
                Zhitu is the only source here).
            include_quote: accepted for interface symmetry but ignored —
                Zhitu's ``/hs/index/tree`` doesn't expose realtime quote fields.

        Returns list of ``{code, name, type, subtype}`` dicts.
        Returns ``[]`` on failure or no match.
        """
        # ``source`` and ``include_quote`` are accepted for Manager interface
        # symmetry but unused here — Zhitu is the sole source for this method
        # and its /hs/index/tree endpoint doesn't expose quote fields.
        _ = source, include_quote

        leaves = self._fetch_board_tree()
        if leaves is None:
            return []

        out: list[dict] = []
        for row in leaves:
            type2 = row.get("type2")
            mapped = ZHITU_TYPE2_MAPPING.get(type2)
            if mapped is None:
                continue
            row_type, row_subtype = mapped
            if row_type != board_type:
                continue
            if subtype is not None and row_subtype != subtype:
                continue
            out.append({
                "code": str(row.get("code", "")),
                "name": str(row.get("name", "")),
                "type": row_type,
                "subtype": row_subtype,
            })
        return out

    def get_board_stocks(self, board_code: str, **kwargs) -> list[dict]:
        """Get stocks belonging to a Zhitu board via /hs/index/stock/{code}.

        Returns ``[{stock_code, stock_name, exchange}]`` or ``[]`` on failure.

        ``**kwargs`` absorbs ``source``/``include_quote`` passed by the Manager
        for interface symmetry — Zhitu's board-stock endpoint does not expose
        realtime quote fields, so ``include_quote`` is ignored.
        """
        if not self.is_available():
            return []
        data = self._fetch_json(
            f"/hs/index/stock/{board_code}",
            op_label=f"get_board_stocks({board_code})",
        )
        if not isinstance(data, list):
            return []
        return [
            {
                "stock_code": str(r.get("dm", "")).strip(),
                "stock_name": str(r.get("mc", "")).strip(),
                "exchange": str(r.get("jys", "")).strip().lower(),
            }
            for r in data
            if isinstance(r, dict) and r.get("dm")
        ]

    def get_stock_boards(self, stock_code: str, **kwargs) -> list[dict] | None:
        """Get boards a stock belongs to via /hs/index/index/{stock_code}.

        Returns ``[{code, name, type, subtype}]`` or ``None`` on failure.
        ``None`` (not ``[]``) so callers can distinguish "no data" from "no match".

        ``**kwargs`` absorbs ``source`` passed by the Manager for interface symmetry.
        """
        if not self.is_available():
            return None
        data = self._fetch_json(
            f"/hs/index/index/{stock_code}",
            op_label=f"get_stock_boards({stock_code})",
        )
        if not isinstance(data, list):
            return None

        out: list[dict] = []
        for r in data:
            if not isinstance(r, dict):
                continue
            code = str(r.get("code", "")).strip()
            name = str(r.get("name", "")).strip()
            if not code:
                continue
            subtype = self._infer_subtype_from_name(name)
            row_type = self._infer_type_from_subtype(subtype)
            out.append({
                "code": code,
                "name": name,
                "type": row_type,
                "subtype": subtype,
            })
        return out

    @staticmethod
    def _infer_subtype_from_name(name: str) -> str:
        """Extract subtype from Zhitu's ``A股-{大类}-{细分}`` name format.

        Example: "A股-申万行业-银行" → "申万行业"
        """
        parts = name.split("-")
        if len(parts) >= 2 and parts[0] == "A股":
            return parts[1]
        return ""

    @staticmethod
    def _infer_type_from_subtype(subtype: str) -> str:
        """Map subtype back to type."""
        for board_type, subtypes in ZHITU_SUBTYPES_BY_TYPE.items():
            if subtype in subtypes:
                return board_type
        return ""

    # ---------- shared helpers ----------

    def _fetch_json(
        self,
        path: str,
        *,
        params: dict | None = None,
        op_label: str,
        timeout: int = 10,
    ) -> object | None:
        """GET ``https://api.zhituapi.com{path}`` and return parsed JSON.

        Thin wrapper over :func:`stock_data.data_provider.utils.http.json_get`
        that injects the Zhitu token, classifies Zhitu's ``{"detail": ...}``
        error envelope, and swallows network errors so the manager's
        failover loop can transparently move on to the next fetcher.

        Centralises the boilerplate used by every ``hs/gs/*`` /
        ``hs/history/transaction/*`` endpoint we wrap: token injection, error
        envelope check, response raise, and exception logging. Returns ``None``
        on any failure so callers can treat "no data" uniformly.

        Args:
            path: URL path beginning with ``/`` (e.g. ``/hs/gs/jnff/600519``).
            params: Extra query string params; ``token`` is auto-merged.
            op_label: Short label for log messages (e.g. ``"dividend 600519"``).
            timeout: requests timeout in seconds.

        Returns:
            Parsed JSON (typically ``list`` or ``dict``), or ``None`` on
            network/HTTP/parse failure or upstream ``detail`` error.
        """
        from ..utils.http import json_get

        if not self.is_available():
            logger.warning(f"[ZhituFetcher] ZHITU_TOKEN not configured; skipping {op_label}")
            return None
        url = f"{ZHITU_API_BASE}{path}"
        merged: dict = {"token": self._token}
        if params:
            merged.update(params)
        try:
            data = json_get(url, params=merged, timeout=timeout)
        except DataFetchError as e:
            # json_get raises on timeout / HTTP error / parse error.
            # Log at warning level (same severity as the original hand-
            # rolled except block) and return None for failover semantics.
            logger.warning(f"[ZhituFetcher] {op_label} HTTP error: {e}")
            return None
        if isinstance(data, dict) and "detail" in data:
            logger.warning(
                f"[ZhituFetcher] {op_label} API error: "
                f"{str(data.get('detail', ''))[:80]}"
            )
            return None
        return data

    # ---------- dividend (hs/gs/jnff) ----------

    def get_dividend(self, code: str, page_size: int = 20) -> list[dict]:
        """Get dividend history via Zhitu ``hs/gs/jnff`` endpoint.

        Zhitu schema (per docs/zhitu/04-listed-company-details.md, 近年分红):
            sdate   — 公告日期 yyyy-MM-dd
            give    — 每 10 股送股
            change  — 每 10 股转增
            send    — 每 10 股派息 (元, pre-tax)
            line    — 进度 (实施 / 预案 / 股东大会通过)
            cdate   — 除权除息日 yyyy-MM-dd
            edate   — 股权登记日 yyyy-MM-dd
            hdate   — 红股上市日 yyyy-MM-dd

        Zhitu's ``send`` is per-10-share (每10股派息); the unified schema's
        ``bonus_rmb`` is per-share (每股派息), so we ÷10 on that field.
        ``give`` / ``change`` are already per-10-share and need no scaling.

        Records with empty ``cdate`` (pre-disclosure only) are dropped —
        the unified ``date`` field is ``除权除息日`` and surfacing
        ``date=""`` would mislead clients. Records are sorted by
        ``cdate`` descending so the result matches the EastMoney /
        Baostock contract (most-recent ex-date first).

        ``page_size`` is applied as a post-sort cap (Zhitu returns all
        records in one call).
        """
        data = self._fetch_json(
            f"/hs/gs/jnff/{code}",
            op_label=f"dividend {code}",
        )
        if not isinstance(data, list) or not data:
            return []
        rows = [r for r in data if isinstance(r, dict) and str(r.get("cdate") or "")]
        rows.sort(key=lambda r: str(r.get("cdate") or ""), reverse=True)
        out: list[dict] = []
        for row in rows[: max(1, page_size)]:
            out.append({
                "date": str(row.get("cdate") or ""),
                "bonus_rmb": safe_float(row.get("send"), 0.0) / 10,  # 每10股→每股
                "transfer_ratio": safe_float(row.get("change"), 0.0),
                "bonus_ratio": safe_float(row.get("give"), 0.0),
                "plan": str(row.get("line") or ""),
            })
        return out

    # ---------- fund flow (hs/history/transaction) ----------

    @staticmethod
    def _parse_fund_flow_row(t: object) -> dict:
        """Map a Zhitu ``hs/history/transaction`` row to a fund-flow record.

        Zhitu classifies orders as 特大单 / 大单 / 中单 / 小单 (super / large /
        mid / small). The unified schema groups them into
        ``main_net`` (主力 = 特大 + 大) + ``mid_net`` + ``small_net`` +
        ``large_net`` + ``super_net`` — same five-tuple the EastMoney
        fetcher emits. Empty / missing fields fall back to 0.

        Zhitu's ``t`` (trading time) is one of:
            - daily: ``YYYY-MM-DD``  → exposed as ``date``
            - minute: ``YYYY-MM-DD HH:MM:SS``  → exposed as ``time``
        We preserve the raw string; the route layer's ``_format_date``
        helper handles datetime conversion.
        """
        if not isinstance(t, dict):
            return {}
        # 主力净流入 = 特大单 + 大单 (主买 - 主卖)
        super_net = (
            safe_float(t.get("zmbstdcje"), 0.0)
            - safe_float(t.get("zmsstdcje"), 0.0)
        )
        large_net = (
            safe_float(t.get("zmbddcje"), 0.0)
            - safe_float(t.get("zmsddcje"), 0.0)
        )
        mid_net = (
            safe_float(t.get("zmbzdcje"), 0.0)
            - safe_float(t.get("zmszdcje"), 0.0)
        )
        small_net = (
            safe_float(t.get("zmbxdcje"), 0.0)
            - safe_float(t.get("zmsxdcje"), 0.0)
        )
        time_str = str(t.get("t") or "")
        # Zhitu minute records carry "YYYY-MM-DD HH:MM:SS"; daily records
        # carry "YYYY-MM-DD". The minute schema wants ``HH:MM:SS`` — slice
        # the last 8 chars (mirrors Zhitu's own ``_normalize_intraday_zhitu``
        # convention). For daily the time field is irrelevant and gets
        # dropped at the route boundary.
        has_time = " " in time_str
        record: dict = {
            "time": time_str[-8:] if has_time else "",
            "date": time_str.split(" ")[0] if time_str else "",
            "main_net": super_net + large_net,
            "small_net": small_net,
            "mid_net": mid_net,
            "large_net": large_net,
            "super_net": super_net,
        }
        return record

    def _fund_flow_records(
        self,
        code: str,
        *,
        st: str,
        et: str,
        limit: int,
        op_label: str,
    ) -> list[dict]:
        """Shared helper for minute / daily fund flow.

        ``st`` / ``et`` use Zhitu's ``YYYYMMDD`` format. ``limit`` caps the
        number of returned rows (Zhitu's ``lt=`` query param).
        """
        data = self._fetch_json(
            f"/hs/history/transaction/{code}",
            params={"st": st, "et": et, "lt": str(limit)},
            op_label=op_label,
        )
        if not isinstance(data, list) or not data:
            return []
        out: list[dict] = []
        for t in data:
            row = self._parse_fund_flow_row(t)
            if row:
                out.append(row)
        return out

    def get_fund_flow_minute(self, code: str) -> list[dict]:
        """Get intraday minute-level fund flow via Zhitu.

        Returns the most recent trading day's minute bars (Zhitu updates
        ``hs/history/transaction`` at 21:30 with the day's final bars).
        Records expose ``time`` (HH:MM:SS) and zero out ``date`` so the
        response model (which is ``FundFlowMinuteRecord``) renders
        correctly.

        Per docs/zhitu/05-realtime-trading.md: 资金流向数据 with no
        ``st``/``et`` returns all historical data; we constrain to the
        latest cached trade date to keep payloads small.
        """
        from ..persistence.trade_calendar import get_latest_cached_trade_date

        latest = get_latest_cached_trade_date()  # YYYY-MM-DD or None
        ymd = latest.replace("-", "") if latest else date.today().strftime("%Y%m%d")
        rows = self._fund_flow_records(
            code, st=ymd, et=ymd, limit=480,
            op_label=f"fund_flow_minute {code}",
        )
        # Strip the date field — minute schema doesn't carry it.
        for r in rows:
            r.pop("date", None)
        return rows

    def get_fund_flow_120d(self, code: str) -> list[dict]:
        """Get 120-day fund flow history via Zhitu.

        Returns daily bars (Zhitu updates daily at 21:30). Records
        expose ``date`` (YYYY-MM-DD) and zero out ``time`` so the
        response model (``FundFlowDailyRecord``) renders correctly.
        """
        et = date.today().strftime("%Y%m%d")
        st = (date.today() - timedelta(days=120)).strftime("%Y%m%d")
        rows = self._fund_flow_records(
            code, st=st, et=et, limit=120,
            op_label=f"fund_flow_120d {code}",
        )
        # Strip the time field — daily schema doesn't carry it.
        for r in rows:
            r.pop("time", None)
        return rows

    # ---------- holder_num (hs/gs/gdbh) ----------

    def get_holder_num_change(self, code: str, page_size: int = 10) -> list[dict]:
        """Get shareholder count change via Zhitu ``hs/gs/gdbh`` endpoint.

        Zhitu schema (per docs/zhitu/04-listed-company-details.md, 股东变化趋势):
            jzrq — 截止日期 yyyy-MM-dd (报告期)
            gdhs — 股东户数 (string in payload — coerce to int)
            bh   — 比上期变化情况 (free text like ``减少28718`` / ``新增1702``)

        Unified schema (``HolderNumRecord``) wants:
            date / holder_num / change_num / change_ratio / avg_shares

        Zhitu doesn't expose ``change_ratio`` or ``avg_shares`` — those
        land as 0.0 / 0. We extract the absolute change from ``bh`` by
        skipping ``新增``/``减少`` prefixes (best-effort; falls back to 0
        on unrecognised text).
        """
        data = self._fetch_json(
            f"/hs/gs/gdbh/{code}",
            op_label=f"holder_num {code}",
        )
        if not isinstance(data, list) or not data:
            return []
        rows: list[dict] = []
        for r in data:
            if not isinstance(r, dict):
                continue
            date_str = str(r.get("jzrq") or "")
            if not date_str:
                continue
            holder_num = safe_int(r.get("gdhs"), 0)
            bh_raw = str(r.get("bh") or "")
            # Extract the leading integer magnitude. ``bh`` shapes seen
            # in the docs: "减少28718", "减少21489", "新增1702", "新增43053".
            m = re.search(r"-?\d+", bh_raw.replace(",", ""))
            change_num = int(m.group(0)) if m else 0
            # 新增 / 减少 flips the sign of the magnitude.
            if "新增" in bh_raw and change_num > 0:
                change_num = -change_num
            elif "减少" in bh_raw and change_num > 0:
                pass  # already positive — matches the docs example
            rows.append({
                "date": date_str,
                "holder_num": holder_num,
                "change_num": change_num,
                "change_ratio": 0.0,
                "avg_shares": 0.0,
            })
        # Newest report date first — matches EastMoney / schema expectation.
        rows.sort(key=lambda r: r["date"], reverse=True)
        return rows[: max(1, page_size)]
