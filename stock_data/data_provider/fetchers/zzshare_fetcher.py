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


def _ensure_api(self_ref) -> Any:
    """Lazy-init the DataApi SDK; caches in self_ref._api.

    Returns the DataApi instance, or None if SDK is missing. Records
    the specific init failure into self_ref._init_error for
    unavailable_reason() reporting.
    """
    if self_ref._api is not None:
        return self_ref._api
    if importlib.util.find_spec("DataApi") is None:
        self_ref._init_error = "DataApi SDK not importable"
        return None
    try:
        from DataApi import DataApi  # type: ignore

        if self_ref._token:
            self_ref._api = DataApi(token=self_ref._token)
        else:
            self_ref._api = DataApi()
        self_ref._init_error = None
        return self_ref._api
    except Exception as e:
        self_ref._init_error = f"DataApi init failed: {e}"
        logger.warning("[ZzshareFetcher] %s", self_ref._init_error)
        return None


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
        api = _ensure_api(self)
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
