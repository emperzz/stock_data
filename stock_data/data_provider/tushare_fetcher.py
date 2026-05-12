# -*- coding: utf-8 -*-
"""
Tushare fetcher for A-share stock data (Priority 0).

Requires TUSHARE_TOKEN environment variable.
Gracefully falls back when token is not configured.
"""

import logging
import os
from datetime import datetime
from typing import Any, Optional

import pandas as pd

from .base import BaseFetcher, DataFetchError, normalize_stock_code
from .realtime_types import UnifiedRealtimeQuote, RealtimeSource, safe_float, safe_int

logger = logging.getLogger(__name__)


class TushareFetcher(BaseFetcher):
    """Tushare Pro API fetcher for A-share data."""

    name = "TushareFetcher"
    priority = int(os.getenv("TUSHARE_PRIORITY", "0"))

    def __init__(self):
        self._token = os.getenv("TUSHARE_TOKEN", "").strip()
        self._api = None
        self._initialized = False

    def _ensure_api(self):
        """Lazily initialize Tushare API."""
        if self._initialized:
            return
        self._initialized = True

        if not self._token:
            logger.warning("[TushareFetcher] TUSHARE_TOKEN not set, will return empty results")
            return

        try:
            import tushare as ts

            self._api = ts.pro_api(self._token)
            logger.info("[TushareFetcher] Initialized successfully")
        except Exception as e:
            logger.warning(f"[TushareFetcher] Failed to initialize: {e}")
            self._api = None

    def is_available(self) -> bool:
        """Check if Tushare API is configured and available."""
        self._ensure_api()
        return self._api is not None

    def _fetch_raw_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """Fetch daily K-line data from Tushare."""
        self._ensure_api()
        if self._api is None:
            raise DataFetchError("Tushare API not available (no token)")

        # Tushare trade calendar API
        try:
            # Convert to Tushare format: 600519.SS -> 600519
            code = normalize_stock_code(stock_code)
            if not code.startswith(("6", "5", "4", "3", "0", "1", "2")):
                raise DataFetchError(f"TushareFetcher does not support {stock_code}")

            # Append exchange suffix for Tushare
            if code.startswith(("6", "5")):
                ts_code = f"{code}.SH"
            else:
                ts_code = f"{code}.SZ"

            # Remove date hyphens for Tushare
            start = start_date.replace("-", "")
            end = end_date.replace("-", "")

            logger.debug(f"[TushareFetcher] Calling pro_bar for {ts_code}")

            df = ts.pro_bar(
                ts_code=ts_code,
                start_date=start,
                end_date=end,
                adj="qfq",  # Forward-adjusted price
            )

            if df is None or df.empty:
                raise DataFetchError(f"Tushare returned no data for {stock_code}")

            return df

        except DataFetchError:
            raise
        except Exception as e:
            raise DataFetchError(f"TushareFetcher fetch failed: {e}") from e

    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        """Normalize Tushare data to standard columns."""
        df = df.copy()

        # Tushare columns: trade_date, open, high, low, close, vol, amount, pct_chg
        column_mapping = {
            "trade_date": "date",
            "vol": "volume",
        }

        df = df.rename(columns=column_mapping)

        if "date" not in df.columns and "trade_date" in df.columns:
            df["date"] = df["trade_date"]

        # Convert date format if needed
        if "date" in df.columns and df["date"].dtype == object:
            df["date"] = pd.to_datetime(df["date"])

        # Add code if missing
        if "code" not in df.columns:
            df["code"] = normalize_stock_code(stock_code)

        # Ensure standard columns exist
        keep_cols = ["code"] + [
            c
            for c in ["date", "open", "high", "low", "close", "volume", "amount", "pct_chg"]
            if c in df.columns
        ]
        df = df[[c for c in keep_cols if c in df.columns]]

        return df

    def get_realtime_quote(self, stock_code: str) -> Optional[UnifiedRealtimeQuote]:
        """Get realtime quote from Tushare (requires tick data permission)."""
        self._ensure_api()
        if self._api is None:
            return None

        try:
            import tushare as ts

            code = normalize_stock_code(stock_code)
            if code.startswith(("6", "5")):
                ts_code = f"{code}.SH"
            else:
                ts_code = f"{code}.SZ"

            # Try to get realtime tick
            df = ts.realtime_quote(ts_code=ts_code)
            if df is None or df.empty:
                return None

            row = df.iloc[0]

            return UnifiedRealtimeQuote(
                code=code,
                name=str(row.get("name", "")),
                source=RealtimeSource.TUSHARE,
                price=safe_float(row.get("price")),
                change_pct=safe_float(row.get("price_percent")),
                change_amount=safe_float(row.get("price_change")),
                volume=safe_int(row.get("volume")),
                amount=safe_float(row.get("amount")),
                open_price=safe_float(row.get("open")),
                high=safe_float(row.get("high")),
                low=safe_float(row.get("low")),
                pre_close=safe_float(row.get("pre_close")),
            )

        except Exception as e:
            logger.warning(f"[TushareFetcher] Realtime quote failed: {e}")
            return None

    def get_stock_name(self, stock_code: str) -> Optional[str]:
        """Get stock name from Tushare basic info."""
        self._ensure_api()
        if self._api is None:
            return None

        try:
            code = normalize_stock_code(stock_code)
            if code.startswith(("6", "5")):
                ts_code = f"{code}.SH"
            else:
                ts_code = f"{code}.SZ"

            df = self._api.stock_basic(ts_code=ts_code, list_status="L")
            if df is not None and not df.empty:
                return df.iloc[0].get("name")
        except Exception as e:
            logger.warning(f"[TushareFetcher] get_stock_name failed: {e}")

        return None
