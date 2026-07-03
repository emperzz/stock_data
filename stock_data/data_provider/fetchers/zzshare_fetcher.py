"""
zzshare fetcher for A-share multi-capability (Priority 5, default).

API: zzshare Python SDK (https://github.com/zzquant/zzshare, PyPI: ``zzshare``).
Client class: ``zzshare.client.DataApi``.
Token configured via ZZSHARE_TOKEN environment variable (anonymous also works
for most endpoints — see docs/zzshare/10-rate-limits.md).

Most endpoints are anonymous-capable; only stock_info and uplimit_stocks
require a token. The fetcher is_available() returns True as long as the
SDK is importable, even without a token.
"""

import importlib.util
import logging
import os
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd

from ..base import BaseFetcher, DataCapability, DataFetchError, SDKFetcherMixin
from ..core.types import RealtimeSource, UnifiedRealtimeQuote, safe_float, safe_int
from ..persistence.trade_calendar import get_latest_trade_date_on_or_before
from ..utils.normalize import normalize_stock_code

logger = logging.getLogger(__name__)


def _to_zzshare_ts_code(code: str) -> str:
    """Convert 6-digit A-share code to tushare-style ts_code suffix.

    OUTBOUND-ONLY: pass this result to zzshare SDK methods (rt_k / stk_mins /
    stock_basic / etc.) which expect the tushare-style code. Never leak this
    format into the API response — return the bare 6-digit form to clients
    (see normalize_stock_code() for the canonical format).

    Rules (from docs/zzshare/README.md §「股票代码格式」):
        6/68/5 -> .SH
        0/3/1  -> .SZ
        8/4/2/9 -> .BJ
    """
    c = code.strip()
    if c.startswith(("6", "68", "5")):
        return f"{c}.SH"
    if c.startswith(("0", "3", "1")):
        return f"{c}.SZ"
    if c.startswith(("8", "4", "2", "9")):
        return f"{c}.BJ"
    return c  # 兜底: 无法识别时不加后缀


def _to_yyyymmdd(date: str) -> str:
    """'2026-05-20' -> '20260520' (strips dashes).

    Pass-through for already-formatted YYYYMMDD strings.
    """
    return date.replace("-", "")


def _from_yyyymmdd(date: str) -> str:
    """'20260520' -> '2026-05-20' (inserts dashes).

    Pass-through for already-formatted YYYY-MM-DD strings.
    """
    if len(date) == 8 and date.isdigit():
        return f"{date[:4]}-{date[4:6]}-{date[6:8]}"
    return date


class ZzshareFetcher(SDKFetcherMixin, BaseFetcher):
    """zzshare SDK fetcher — A-share multi-capability (priority 5)."""

    name = "ZzshareFetcher"
    priority = int(os.getenv("ZZSHARE_PRIORITY", "2"))
    supported_markets: set[str] = {"csi"}
    supported_data_types = (
        DataCapability.STOCK_KLINE
        | DataCapability.STOCK_REALTIME_QUOTE
        | DataCapability.STOCK_LIST
        | DataCapability.TRADE_CALENDAR
        | DataCapability.STOCK_BOARD
        | DataCapability.STOCK_ZT_POOL
        | DataCapability.DRAGON_TIGER
        | DataCapability.HOT_TOPICS
        | DataCapability.STOCK_INFO
    )

    # SDKFetcherMixin declarations. Token is optional (anonymous works
    # for most endpoints); _init_sdk handles the empty-token case.
    _TOKEN_ENV_VAR = "ZZSHARE_TOKEN"
    _SDK_NAME = "zzshare"

    def __init__(self):
        pass

    def _init_sdk(self, token: str) -> Any:
        """Initialise the zzshare SDK. Token is optional."""
        if importlib.util.find_spec("zzshare") is None:
            raise ImportError("zzshare SDK not importable (pip install zzshare)")
        from zzshare.client import DataApi  # type: ignore

        if token:
            return DataApi(token=token)
        return DataApi()

    def is_available(self) -> bool:
        """True iff the zzshare PyPI package is importable. Token is optional.

        Overrides the mixin's is_available() (which triggers _ensure_api)
        because Zzshare only requires the SDK to be installed — token is
        checked lazily inside per-method calls via _ensure_api().
        """
        return importlib.util.find_spec("zzshare") is not None

    def supports_kline(self, period, adjust, market, asset):
        if period == "d":
            return True
        if period in ("1", "5", "15", "30", "60"):
            # Zzshare stk_mins upstream ignores adjust — treat as unsupported.
            return adjust in ("", None)
        return False  # no weekly/monthly

    def unavailable_reason(self) -> str | None:
        if self.is_available():
            return None
        return f"{self.name} unavailable: zzshare SDK not installed (pip install zzshare)"

    def _fetch_raw_data(
        self,
        stock_code: str,
        start_date: str,
        end_date: str,
        frequency: str = "d",
        adjust: str | None = None,
    ) -> pd.DataFrame:
        """Fetch K-line from zzshare.

        Daily: api.daily (single call).
        Minute (5/15/30/60): api.stk_mins is single-day only; loop over
        the date range and pd.concat. adjust is ignored for minute
        (zzshare upstream: minute K has no adjustment).
        """
        if frequency in ("w", "m"):
            raise DataFetchError(
                f"ZzshareFetcher 不支持周线/月线 (frequency={frequency}, 仅日线 daily)"
            )

        # Minute-frequency branch — multi-day loop with concat
        if frequency in ("5", "15", "30", "60"):
            # Mirror the daily branch's SDK-availability check so users get
            # a distinct "SDK 不可用" error instead of a misleading "无分钟数据".
            self._ensure_api()
            if self.__class__._api is None:
                raise DataFetchError(
                    f"ZzshareFetcher zzshare SDK 不可用: {ZzshareFetcher._init_error}"
                )
            freq = self._PERIOD_TO_FREQ.get(frequency, f"{frequency}min")
            try:
                start_d = datetime.strptime(start_date, "%Y-%m-%d").date()
                end_d = datetime.strptime(end_date, "%Y-%m-%d").date()
            except ValueError as e:
                raise DataFetchError(f"Invalid date for minute K: {e}") from e
            day_count = (end_d - start_d).days + 1
            if day_count > 14:
                logger.warning(
                    "[ZzshareFetcher] minute K over %d days for %s — %d SDK calls expected",
                    day_count, stock_code, day_count,
                )
            dfs: list[pd.DataFrame] = []
            cur = start_d
            while cur <= end_d:
                df_one = self._fetch_minute_kline(
                    stock_code, cur.strftime("%Y%m%d"), freq
                )
                if df_one is not None:
                    dfs.append(df_one)
                cur += timedelta(days=1)
            if not dfs:
                raise DataFetchError(
                    f"ZzshareFetcher 无分钟数据 for {stock_code} {start_date}~{end_date}"
                )
            return pd.concat(dfs, ignore_index=True)

        # Daily branch (existing path)
        self._ensure_api()
        api = self.__class__._api
        if api is None:
            raise DataFetchError(f"ZzshareFetcher zzshare SDK 不可用: {ZzshareFetcher._init_error}")
        ts_code = _to_zzshare_ts_code(normalize_stock_code(stock_code))
        kwargs: dict = {
            "ts_code": ts_code,
            "start_date": _to_yyyymmdd(start_date),
            "end_date": _to_yyyymmdd(end_date),
        }
        if adjust:
            kwargs["adj"] = adjust
        return api.daily(**kwargs)

    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        """Normalize zzshare K-line output to STANDARD_COLUMNS.

        Daily: trade_date (YYYYMMDD) -> date.
        Minute: trade_time (YYYYMMDDHHMM, 12 digits) -> date (first 8 digits).
        Column rename: vol -> volume. pct_chg absent for minute.
        """
        if df is None or df.empty:
            return df
        df = df.copy()
        rename = {}
        if "vol" in df.columns:
            rename["vol"] = "volume"
        # Daily path: trade_date (YYYYMMDD) → date
        if "trade_date" in df.columns and "date" not in df.columns:
            rename["trade_date"] = "date"
        df = df.rename(columns=rename)
        # Minute path: derive date from trade_time (first 8 digits of YYYYMMDDHHMM)
        if "date" not in df.columns and "trade_time" in df.columns:
            df["date"] = df["trade_time"].astype(str).str.slice(0, 8).apply(_from_yyyymmdd)
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
        if "code" not in df.columns:
            df["code"] = normalize_stock_code(stock_code)
        keep = ["code"] + [
            c
            for c in [
                "date",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "amount",
                "pct_chg",
            ]
            if c in df.columns
        ]
        return df[[c for c in keep if c in df.columns]]

    # Minute-period -> zzshare freq mapping
    _PERIOD_TO_FREQ: dict[str, str] = {
        "1": "1min",
        "5": "5min",
        "15": "15min",
        "30": "30min",
        "60": "60min",
    }

    def get_intraday_data(
        self, stock_code: str, period: str = "5", adjust: str = ""
    ) -> pd.DataFrame | None:
        """Fetch minute K-line from zzshare (period=1/5/15/30/60).

        Single-day, latest available (today - 2 days as a safe trade-time
        default — same heuristic the previous inline implementation used).

        Note: zzshare minute K does not support adjust — the ``adjust`` param
        is accepted for interface symmetry but is not forwarded to the SDK.
        """
        freq = self._PERIOD_TO_FREQ.get(period, "5min")
        trade_time = (datetime.now() - timedelta(days=2)).strftime("%Y%m%d")
        df = self._fetch_minute_kline(stock_code, trade_time, freq)
        if df is None:
            return None
        df = df.copy()
        if "vol" in df.columns:
            df = df.rename(columns={"vol": "volume"})
        if "trade_time" in df.columns:
            # YYYYMMDDHHMM (12 digits) -> HH:MM:SS (positions 8..12 = HHMM, pad SS=00)
            df["time"] = (
                df["trade_time"]
                .astype(str)
                .str.slice(8, 12)
                .apply(lambda s: f"{s[:2]}:{s[2:4]}:00" if len(s) == 4 else s)
            )
            df = df.drop(columns=["trade_time"])
        keep = ["time", "open", "high", "low", "close", "volume", "amount"]
        df = df[[c for c in keep if c in df.columns]]
        return df

    def _fetch_minute_kline(
        self, stock_code: str, trade_date_yyyymmdd: str, freq: str
    ) -> pd.DataFrame | None:
        """底层调 api.stk_mins,返回 DataFrame 或 None。

        单日调用封装。统一供 _fetch_raw_data（多日循环）和
        get_intraday_data（单日）使用。SDK 不可用、上游异常、
        或返回空 df 时返回 None，调用方需自行决定下一步。
        """
        self._ensure_api()
        api = self.__class__._api
        if api is None:
            return None
        ts_code = _to_zzshare_ts_code(normalize_stock_code(stock_code))
        try:
            df = api.stk_mins(
                ts_code=ts_code,
                trade_time=trade_date_yyyymmdd,
                freq=freq,
            )
        except Exception as e:
            logger.warning(
                f"[ZzshareFetcher] stk_mins({ts_code}, {freq}) failed: {e}"
            )
            return None
        if df is None or df.empty:
            return None
        return df

    def get_realtime_quote(self, stock_code: str) -> UnifiedRealtimeQuote | None:
        """Fetch realtime snapshot from zzshare rt_k(fields='all').

        Returns None if SDK unavailable or upstream returns empty.
        """
        self._ensure_api()
        api = self.__class__._api
        if api is None:
            return None
        ts_code = _to_zzshare_ts_code(normalize_stock_code(stock_code))
        try:
            df = api.rt_k(ts_code=ts_code, fields="all")
        except Exception as e:
            logger.warning(f"[ZzshareFetcher] rt_k({ts_code}) failed: {e}")
            return None
        if df is None or df.empty:
            return None
        row = df.iloc[0].to_dict()
        pre_close = safe_float(row.get("pre_close"))
        close = safe_float(row.get("close"))
        return UnifiedRealtimeQuote(
            code=normalize_stock_code(stock_code),
            name=str(row.get("name", "")),
            source=RealtimeSource.ZZSHARE,
            price=close,
            change_pct=safe_float(row.get("quote_rate")),
            change_amount=(close - pre_close)
            if (close is not None and pre_close is not None)
            else None,
            volume=safe_int(row.get("vol")),
            amount=safe_float(row.get("amount")),
            open_price=safe_float(row.get("open")),
            high=safe_float(row.get("high")),
            low=safe_float(row.get("low")),
            pre_close=pre_close,
            turnover_rate=safe_float(row.get("turnover_rate")),
            total_mv=safe_float(row.get("market_value")),
            circ_mv=safe_float(row.get("circulation_value")),
            pe_ratio=safe_float(row.get("ttm_pe_rate")),
        )

    def get_all_stocks(self, market: str = "csi") -> list:
        """Fetch the A-share stock list from zzshare stock_basic(exchange='ALL').

        area/industry/list_date left empty (zzshare does not fill them; other
        fetchers will backfill via persistence layer).

        ``market`` accepts the public ``"csi"`` tag AND the fetcher-internal
        ``"cn"`` alias — the manager translates ``"csi"`` → ``"cn"`` at the
        call boundary (see ``manager.get_all_stocks`` ``public_to_fetcher``
        map), and rejecting ``"cn"`` here would silently fall through to
        the next fetcher in the failover chain (regression 2026-07-03:
        Akshare P3 winning over Zzshare P2 on ``GET /api/v1/stocks``).

        Returns [] on failure or unrecognized market tag.
        """
        if market not in ("csi", "cn"):
            return []
        self._ensure_api()
        api = self.__class__._api
        if api is None:
            return []
        try:
            df = api.stock_basic(exchange="ALL", list_status="L")
        except Exception as e:
            logger.warning(f"[ZzshareFetcher] stock_basic failed: {e}")
            return []
        if df is None or df.empty:
            return []
        out: list = []
        for _, row in df.iterrows():
            ts_code = str(row.get("ts_code", ""))
            if not ts_code:
                continue
            # ts_code like "600519.SH" -> bare "600519"
            code = ts_code.split(".")[0]
            out.append(
                {
                    "code": code,
                    "name": str(row.get("name", "")),
                    "exchange": str(row.get("exchange", "")),
                }
            )
        return out

    def get_trade_calendar(self) -> list[str] | None:
        """Fetch full A-share trade calendar from zzshare trade_days.

        Returns the ascending YYYY-MM-DD list of all trade dates in
        [day_start, day_end]. Aligned with MyquantFetcher's
        ``MYQUANT_CALENDAR_START_YEAR`` default (2010) so the cache has
        a consistent lookback window across fetchers — downstream helpers
        (``is_trade_date`` / ``get_latest_trade_date_on_or_before``) work
        correctly with both partial and full ranges, but a full range
        lets us answer "was date X a trade day" queries reliably for any
        historical date.

        Note: ``trade_days()`` with no args returns only ~8 recent dates
        (a small rolling window), and ``days=N`` caps the count. To get
        the full range we MUST pass explicit ``day_start`` and
        ``day_end`` — that's what the SDK's ``market/trade/days``
        endpoint requires for a complete pull.

        Returns:
            list[str] of YYYY-MM-DD strings, or None on failure.
        """
        self._ensure_api()
        api = self.__class__._api
        if api is None:
            return None
        try:
            # Reuse the project-wide start-year env var (default 2010) so
            # the cache window matches MyquantFetcher. End year = current
            # year; the SDK returns the full calendar within bounds.
            # Canonical name is TRADE_CALENDAR_START_YEAR; legacy
            # MYQUANT_CALENDAR_START_YEAR kept as a fallback for
            # existing .env files.
            start_year = int(
                os.getenv("TRADE_CALENDAR_START_YEAR")
                or os.getenv("MYQUANT_CALENDAR_START_YEAR")
                or "2010"
            )
            end_year = datetime.now().year
            dates = api.trade_days(
                day_start=f"{start_year}-01-01",
                day_end=f"{end_year}-12-31",
            )
        except Exception as e:
            logger.warning(f"[ZzshareFetcher] trade_days failed: {e}")
            return None
        if not dates:
            return None
        return list(dates)

    def get_stock_info(self, stock_code: str) -> dict | None:
        """公司画像 — zzshare stock_info(stock_id, info_type=1).

        Returns 18-field dict matching ZhituFetcher.get_stock_info's shape.
        info_type=1 is the company-profile enum (README 探测确认可用).
        """
        from ..utils.normalize import split_concepts as _split_concepts

        self._ensure_api()
        api = self.__class__._api
        if api is None:
            return None
        code = normalize_stock_code(stock_code)
        try:
            data = api.stock_info(stock_id=code, info_type=1)
        except Exception as e:
            logger.warning(f"[ZzshareFetcher] stock_info({code}) failed: {e}")
            return None
        if not isinstance(data, dict):
            return None
        return {
            "code": code,
            "name": str(data.get("name", "") or ""),
            "ename": str(data.get("ename", "") or ""),
            "market": "csi",
            "listed_date": str(data.get("ldate", "") or ""),
            "delisted_date": "",
            "total_shares": safe_float(data.get("totalstock")),
            "float_shares": safe_float(data.get("flowstock")),
            "concepts": _split_concepts(data.get("idea", "")),
            "registered_address": str(data.get("raddr", "") or ""),
            "registered_capital": str(data.get("rcapital", "") or ""),
            "legal_representative": str(data.get("rname", "") or ""),
            "business_scope": str(data.get("bscope", "") or ""),
            "established_date": str(data.get("rdate", "") or ""),
            "secretary": str(data.get("bsname", "") or ""),
            "secretary_phone": str(data.get("bsphone", "") or ""),
            "secretary_email": str(data.get("bsemail", "") or ""),
        }

    # Pool type -> zzshare endpoint name
    _POOL_TYPE_MAP: dict[str, str] = {
        "zt": "uplimit_stocks",  # primary
    }

    def get_zt_pool(self, pool_type: str, date: str) -> list[dict] | None:
        """Fetch ZT pool from zzshare uplimit_stocks (token-gated).

        Falls back gracefully: if uplimit_stocks returns empty (no token or
        no data), returns None so the manager failover chain can try the
        next fetcher.
        """
        if pool_type not in self._POOL_TYPE_MAP:
            return None
        self._ensure_api()
        api = self.__class__._api
        if api is None:
            return None
        date_yyyymmdd = _to_yyyymmdd(date)
        try:
            rows = api.uplimit_stocks(date1=date_yyyymmdd)
        except Exception as e:
            logger.warning(f"[ZzshareFetcher] uplimit_stocks({date_yyyymmdd}) failed: {e}")
            return None
        if not rows:
            return None
        out: list[dict] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            ts_code = str(row.get("ts_code", ""))
            out.append(
                {
                    "code": ts_code.split(".")[0] if ts_code else "",
                    "name": str(row.get("name", "")),
                    "price": safe_float(row.get("price") or row.get("p")),
                    "change_pct": safe_float(row.get("pct_chg")),
                    "amount": safe_float(row.get("amount")),
                    "circ_mv": safe_float(row.get("circ_mv") or row.get("lt")),
                    "total_mv": safe_float(row.get("total_mv") or row.get("zsz")),
                    "turnover_rate": safe_float(row.get("turnover_rate")),
                    "lb_count": safe_int(row.get("lb_count")),
                    "first_seal_time": str(row.get("first_seal_time", "")),
                    "last_seal_time": str(row.get("last_seal_time", "")),
                    "seal_amount": safe_float(row.get("seal_amount")),
                    "seal_count": safe_int(row.get("seal_count")),
                    "zt_count": safe_int(row.get("zt_count")),
                }
            )
        return out

    # Board type/subtype -> zzshare plate_type
    _PLATE_TYPE_BY_BOARD_TYPE: dict[str, int] = {
        "industry": 14,
        "concept": 15,
        "special": 17,
    }
    _BOARD_TYPE_BY_PLATE_TYPE: dict[int, tuple[str, str]] = {
        14: ("industry", "同花顺行业"),
        15: ("concept", "同花顺概念"),
        17: ("special", "同花顺题材"),
    }

    def get_all_boards(
        self,
        board_type: str | None = None,
        subtype: str | None = None,
        source: str = "zzshare",
        include_quote: bool = False,
    ) -> list[dict]:
        """Get boards of a given (type, subtype) from zzshare plates_list.

        include_quote is accepted for interface symmetry but ignored —
        plates_list does not expose realtime quote fields.

        ``board_type=None`` queries every type the source exposes (industry,
        concept, special). zzshare does not expose index boards.
        ``subtype`` is ignored when ``board_type`` is ``None`` because
        subtypes are scoped per type and the cross-type union is undefined.
        """
        _ = source, include_quote  # accepted for Manager interface
        self._ensure_api()
        api = self.__class__._api
        if api is None:
            return []
        out: list[dict] = []
        target_plate_types = [
            pt for pt, (bt, st) in self._BOARD_TYPE_BY_PLATE_TYPE.items()
            if board_type is None or bt == board_type
        ]
        for pt in target_plate_types:
            try:
                rows = api.plates_list(plate_type=pt)
            except Exception as e:
                logger.warning(f"[ZzshareFetcher] plates_list({pt}) failed: {e}")
                continue
            if not rows:
                continue
            mapped_type, mapped_subtype = self._BOARD_TYPE_BY_PLATE_TYPE[pt]
            for row in rows:
                if not isinstance(row, dict):
                    continue
                row_plate_type = row.get("plate_type")
                if row_plate_type is not None and row_plate_type != pt:
                    continue
                if subtype is not None and mapped_subtype != subtype:
                    continue
                out.append(
                    {
                        "code": str(row.get("plate_code", "")),
                        "name": str(row.get("plate_name", "")),
                        "type": mapped_type,
                        "subtype": mapped_subtype,
                    }
                )
        return out

    def get_board_stocks(self, board_code: str, **kwargs) -> list[dict]:
        """Get stocks belonging to a board via plates_stocks.

        Returns [{stock_code, stock_name, exchange}] or [] on failure.
        ``**kwargs`` absorbs source/include_quote for interface symmetry.
        """
        source = kwargs.get("source", "zzshare")
        _ = source  # currently always 'zzshare' for this fetcher
        self._ensure_api()
        api = self.__class__._api
        if api is None:
            return []
        # Try each plate_type (14/15/17) until one returns data.
        rows = None
        for pt in self._BOARD_TYPE_BY_PLATE_TYPE:
            try:
                r = api.plates_stocks(plate_type=pt, plate_code=board_code)
                if r:
                    rows = r
                    break
            except Exception:
                continue
        if not rows:
            return []
        out: list[dict] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            stock_code = str(row.get("stock_code", "")).strip()
            if not stock_code:
                continue
            out.append(
                {
                    "stock_code": stock_code,
                    "stock_name": str(row.get("stock_name", "")).strip(),
                    "exchange": str(row.get("exchange", "")).strip().lower(),
                }
            )
        return out

    def get_stock_boards(self, stock_code: str, **kwargs) -> list[dict] | None:
        """Reverse lookup: boards a stock belongs to.

        zzshare SDK does not provide a direct stock->boards endpoint. Return
        None so the route layer can 404 (matches EastMoney behavior).
        """
        return None

    # NOTE: get_board_history was removed (2026-07-03). zzshare's ``plate_kline``
    # upstream only supports board code 883957 (同花顺全A); all concept / industry
    # / special codes return empty. The board-history route now aliases
    # ``source=zzshare`` → ``source=ths`` so callers can use the same label
    # while being served by ThsFetcher. See _resolve_board_history_source in
    # stock_data/api/routes/boards.py.

    def get_daily_dragon_tiger(
        self, trade_date: str = "", min_net_buy: float | None = None
    ) -> dict:
        """全市场龙虎榜 via zzshare lhb_list.

        Returns ``{date, total, stocks[]}`` matching the manager's
        contract. ``min_net_buy`` filters rows whose buy_in < threshold.
        """
        self._ensure_api()
        api = self.__class__._api
        if api is None:
            raise DataFetchError("ZzshareFetcher zzshare SDK 不可用")
        date_str = (
            _to_yyyymmdd(trade_date)
            if trade_date
            else _to_yyyymmdd(
                get_latest_trade_date_on_or_before(date.today().strftime("%Y-%m-%d")) or ""
            )
        )
        try:
            rows = api.lhb_list(date1=date_str)
        except Exception as e:
            logger.warning(f"[ZzshareFetcher] lhb_list({date_str}) failed: {e}")
            raise DataFetchError(f"lhb_list failed: {e}") from e
        out_stocks: list[dict] = []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            buy_in = safe_float(row.get("buy_in")) or 0.0
            if min_net_buy is not None and buy_in < min_net_buy:
                continue
            stock_code = str(row.get("stock_code", "")).strip()
            out_stocks.append(
                {
                    "code": stock_code,
                    "name": str(row.get("stock_name", "")),
                    "net_buy": buy_in,
                    "amplitude": safe_float(row.get("amplitude")),
                    "change_pct": safe_float(row.get("quote_change")),
                    "turnover": safe_float(row.get("turnover")),
                    "turnover_rate": safe_float(row.get("turnover_ratio")),
                    "join_num": safe_int(row.get("join_num")),
                    "reason": str(row.get("up_reason", "")),
                    "t_type": safe_int(row.get("t_type")),
                    "d3": safe_float(row.get("d3")),
                }
            )
        return {
            "date": _from_yyyymmdd(date_str),
            "total": len(out_stocks),
            "stocks": out_stocks,
        }

    def get_dragon_tiger(self, code: str, trade_date: str = "", look_back: int = 30) -> dict:
        """个股龙虎榜 via zzshare lhb_detail, fallback lhb_stock_history.

        Returns ``{records[], seats{buy, sell}, institution}`` matching
        the manager's per-stock contract.
        """
        self._ensure_api()
        api = self.__class__._api
        if api is None:
            raise DataFetchError("ZzshareFetcher zzshare SDK 不可用")
        bare_code = normalize_stock_code(code)
        date_str = _to_yyyymmdd(trade_date) if trade_date else ""
        records: list[dict] = []
        seats: dict[str, list] = {"buy": [], "sell": []}
        # 1) Try detail (per-day seats)
        try:
            detail = api.lhb_detail(date1=date_str, stock_code=bare_code) if date_str else None
        except Exception as e:
            logger.warning(f"[ZzshareFetcher] lhb_detail failed: {e}")
            detail = None
        if detail and isinstance(detail, list):
            for row in detail:
                if not isinstance(row, dict):
                    continue
                trader = str(row.get("trader_name", ""))
                buy_amt = safe_float(row.get("buy")) or 0.0
                sell_amt = safe_float(row.get("sell")) or 0.0
                if buy_amt > 0:
                    seats["buy"].append({"name": trader, "amount": buy_amt})
                if sell_amt > 0:
                    seats["sell"].append({"name": trader, "amount": sell_amt})
        # 2) If detail empty, fall back to stock history
        if not seats["buy"] and not seats["sell"]:
            try:
                history = api.lhb_stock_history(stock_code=bare_code)
            except Exception as e:
                logger.warning(f"[ZzshareFetcher] lhb_stock_history failed: {e}")
                history = None
            if history and isinstance(history, list):
                for row in history:
                    if not isinstance(row, dict):
                        continue
                    records.append(
                        {
                            "date": str(row.get("trade_date", "")),
                            "net_buy": safe_float(row.get("buy_in")),
                            "reason": str(row.get("reason", "")),
                        }
                    )
        return {
            "records": records,
            "seats": seats,
            "institution": {},
        }

    def get_hot_topics(self, date_str: str = "") -> list[dict]:
        """同花顺热度 TopN via zzshare ths_hot_top.

        Returns list of normalized {code, name, change_pct, rank, ...} dicts.
        date_str empty -> today.
        """

        self._ensure_api()
        api = self.__class__._api
        if api is None:
            return []
        d = _to_yyyymmdd(date_str) if date_str else date.today().strftime("%Y%m%d")
        try:
            rows = api.ths_hot_top(date1=d, top_n=100)
        except Exception as e:
            logger.warning(f"[ZzshareFetcher] ths_hot_top({d}) failed: {e}")
            return []
        out: list[dict] = []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            symbol = str(row.get("symbol_code", "")).strip()
            out.append(
                {
                    "code": symbol,
                    "name": str(row.get("symbol_name", "")),
                    "rank": safe_int(row.get("rank")),
                    "rank_diff": safe_int(row.get("rank_diff")),
                    "change_pct": safe_float(row.get("last_pct")),
                    "price": safe_float(row.get("last_price")),
                    "circ_mv": safe_float(row.get("circulation_value")),
                    "date": str(row.get("collect_date", "")),
                }
            )
        return out
