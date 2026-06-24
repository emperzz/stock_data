"""
zzshare fetcher for A-share multi-capability (Priority 5, default).

API: DataApi Python SDK (https://github.com/zzquant/zzshare)
Token configured via ZZSHARE_TOKEN environment variable (anonymous also works
for most endpoints — see docs/zzshare/10-rate-limits.md).

Most endpoints are anonymous-capable; only stock_info and uplimit_stocks
require a token. The fetcher is_available() returns True as long as the
SDK is importable, even without a token.
"""

import importlib.util
import logging
import os
from typing import Any

import pandas as pd

from ..base import BaseFetcher, DataCapability, DataFetchError
from ..core.types import RealtimeSource, UnifiedRealtimeQuote, safe_float, safe_int
from ..utils.normalize import normalize_stock_code

logger = logging.getLogger(__name__)


def _to_zzshare_ts_code(code: str) -> str:
    """Convert 6-digit A-share code to tushare-style ts_code suffix.

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


def _add_exchange_suffix(stock_code: str) -> str:
    """6-digit bare code -> '600519.SH' style (same rules as _to_zzshare_ts_code)."""
    return _to_zzshare_ts_code(stock_code)


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


class ZzshareFetcher(BaseFetcher):
    """zzshare SDK fetcher — A-share multi-capability (priority 5)."""

    name = "ZzshareFetcher"
    priority = int(os.getenv("ZZSHARE_PRIORITY", "5"))
    supported_markets: set[str] = {"csi"}
    supported_data_types = (
        DataCapability.HISTORICAL_DWM
        | DataCapability.HISTORICAL_MIN
        | DataCapability.REALTIME_QUOTE
        | DataCapability.STOCK_LIST
        | DataCapability.TRADE_CALENDAR
        | DataCapability.STOCK_BOARD
        | DataCapability.STOCK_ZT_POOL
        | DataCapability.DRAGON_TIGER
        | DataCapability.HOT_TOPICS
        | DataCapability.STOCK_INFO
    )

    def __init__(self):
        self._token = os.getenv("ZZSHARE_TOKEN", "").strip()
        self._api = None
        self._init_error: str | None = None

    def is_available(self) -> bool:
        """True iff DataApi SDK is importable. Token is optional.

        Mirrors the akshare pattern: probe via importlib.util.find_spec so
        the manager can skip this fetcher cleanly when DataApi isn't
        installed. Token is checked lazily inside per-method calls.
        """
        return importlib.util.find_spec("DataApi") is not None

    def unavailable_reason(self) -> str | None:
        if self.is_available():
            return None
        return f"{self.name} unavailable: DataApi SDK not installed (pip install DataApi)"

    def _ensure_api(self) -> Any:
        """Lazy-init the DataApi SDK; caches in self._api.

        Returns the DataApi instance, or None if SDK is missing. Records
        the specific init failure into self._init_error for
        unavailable_reason() reporting.
        """
        if self._api is not None:
            return self._api
        if importlib.util.find_spec("DataApi") is None:
            self._init_error = "DataApi SDK not importable"
            return None
        try:
            from DataApi import DataApi  # type: ignore

            if self._token:
                self._api = DataApi(token=self._token)
            else:
                self._api = DataApi()
            self._init_error = None
            return self._api
        except Exception as e:
            self._init_error = f"DataApi init failed: {e}"
            logger.warning("[ZzshareFetcher] %s", self._init_error)
            return None

    def _fetch_raw_data(
        self,
        stock_code: str,
        start_date: str,
        end_date: str,
        frequency: str = "d",
        adjust: str | None = None,
    ) -> pd.DataFrame:
        """Fetch daily K-line from zzshare. Raises for weekly/monthly."""
        if frequency in ("w", "m"):
            raise DataFetchError(
                f"ZzshareFetcher 不支持周线/月线 (frequency={frequency}, 仅日线 daily)"
            )
        api = self._ensure_api()
        if api is None:
            raise DataFetchError(
                f"ZzshareFetcher DataApi SDK 不可用: {self._init_error}"
            )
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
        """Normalize zzshare daily output to STANDARD_COLUMNS.

        Column mapping: vol -> volume, trade_date -> date (YYYY-MM-DD).
        """
        if df is None or df.empty:
            return df
        df = df.copy()
        rename = {}
        if "vol" in df.columns:
            rename["vol"] = "volume"
        if "trade_date" in df.columns:
            rename["trade_date"] = "date"
        df = df.rename(columns=rename)
        if "date" in df.columns:
            df["date"] = df["date"].astype(str).apply(_from_yyyymmdd)
            df["date"] = pd.to_datetime(df["date"])
        if "code" not in df.columns:
            df["code"] = normalize_stock_code(stock_code)
        keep = ["code"] + [c for c in [
            "date", "open", "high", "low", "close",
            "volume", "amount", "pct_chg",
        ] if c in df.columns]
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

        Note: zzshare minute K does not support adjust — the ``adjust`` param
        is accepted for interface symmetry but is not forwarded to the SDK.
        """
        from datetime import datetime, timedelta

        api = self._ensure_api()
        if api is None:
            return None
        ts_code = _to_zzshare_ts_code(normalize_stock_code(stock_code))
        # Determine the date to query (latest trade date or today).
        trade_time = (datetime.now() - timedelta(days=2)).strftime("%Y%m%d")
        freq = self._PERIOD_TO_FREQ.get(period, "5min")
        try:
            df = api.stk_mins(ts_code=ts_code, trade_time=trade_time, freq=freq)
        except Exception as e:
            logger.warning(f"[ZzshareFetcher] stk_mins({ts_code}, {freq}) failed: {e}")
            return None
        if df is None or df.empty:
            return None
        df = df.copy()
        if "vol" in df.columns:
            df = df.rename(columns={"vol": "volume"})
        if "trade_time" in df.columns:
            # YYYYMMDDHHMM (12 digits) -> HH:MM:SS (positions 8..12 = HHMM, pad SS=00)
            df["time"] = df["trade_time"].astype(str).str.slice(8, 12).apply(
                lambda s: f"{s[:2]}:{s[2:4]}:00" if len(s) == 4 else s
            )
            df = df.drop(columns=["trade_time"])
        keep = ["time", "open", "high", "low", "close", "volume", "amount"]
        df = df[[c for c in keep if c in df.columns]]
        return df

    def get_realtime_quote(self, stock_code: str) -> UnifiedRealtimeQuote | None:
        """Fetch realtime snapshot from zzshare rt_k(fields='all').

        Returns None if SDK unavailable or upstream returns empty.
        """
        api = self._ensure_api()
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
            change_amount=(close - pre_close) if (close is not None and pre_close is not None) else None,
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
