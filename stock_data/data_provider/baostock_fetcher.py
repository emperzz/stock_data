# -*- coding: utf-8 -*-
"""
Baostock fetcher for A-share stock data (Priority 1).

Free data source, no API token required.
"""

import logging
import os
from datetime import datetime
from typing import Optional

import pandas as pd

from .base import BaseFetcher, DataFetchError, normalize_stock_code
from .realtime_types import UnifiedRealtimeQuote, RealtimeSource, safe_float, safe_int

logger = logging.getLogger(__name__)


class BaostockFetcher(BaseFetcher):
    """Baostock API fetcher for A-share data (free, no token)."""

    name = "BaostockFetcher"
    priority = int(os.getenv("BAOSTOCK_PRIORITY", "1"))

    def __init__(self):
        self._initialized = False

    def _ensure_initialized(self):
        """Lazily initialize Baostock."""
        if self._initialized:
            return
        self._initialized = True

        try:
            import baostock as bs

            lg = bs.login()
            if lg.error_code != "0":
                logger.warning(f"[BaostockFetcher] Login failed: {lg.error_msg}")
                self._initialized = False
            else:
                logger.info("[BaostockFetcher] Initialized successfully")
        except ImportError:
            logger.warning("[BaostockFetcher] baostock not installed")
            self._initialized = False
        except Exception as e:
            logger.warning(f"[BaostockFetcher] Init failed: {e}")
            self._initialized = False

    def is_available(self) -> bool:
        """Check if Baostock is available."""
        self._ensure_initialized()
        return self._initialized

    def _convert_code(self, stock_code: str) -> tuple:
        """
        Convert A-share code to Baostock format.

        Returns (bs_code, yw_code):
            600519 -> (sh.600519, 600519)
            000001 -> (sz.000001, 000001)
        """
        code = normalize_stock_code(stock_code)
        if code.startswith(("6", "5")):
            return f"sh.{code}", code
        else:
            return f"sz.{code}", code

    def _fetch_raw_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """Fetch daily K-line data from Baostock."""
        self._ensure_initialized()
        if not self._initialized:
            raise DataFetchError("Baostock not available")

        try:
            import baostock as bs

            bs_code, _ = self._convert_code(stock_code)

            logger.debug(f"[BaostockFetcher] Calling query_history_k_data for {bs_code}")

            rs = bs.query_history_k_data(
                bs_code,
                "date,open,high,low,close,volume,amount,pct_chg",
                start_date=start_date,
                end_date=end_date,
                frequency="d",
                adjustflag="2",  # Forward-adjusted
            )

            if rs.error_code != "0":
                raise DataFetchError(f"Baostock query failed: {rs.error_msg}")

            # Convert to DataFrame
            data_list = []
            while rs.next():
                data_list.append(rs.get_row_data())

            if not data_list:
                raise DataFetchError(f"Baostock returned no data for {stock_code}")

            df = pd.DataFrame(data_list, columns=rs.fields)
            return df

        except DataFetchError:
            raise
        except Exception as e:
            raise DataFetchError(f"BaostockFetcher fetch failed: {e}") from e

    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        """Normalize Baostock data to standard columns."""
        df = df.copy()

        # Baostock columns: date, open, high, low, close, volume, amount, pct_chg (already standard-ish)

        # Convert numeric columns
        numeric_cols = ["open", "high", "low", "close", "volume", "amount", "pct_chg"]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        # Convert date
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])

        # Add code
        if "code" not in df.columns:
            df["code"] = normalize_stock_code(stock_code)

        keep_cols = ["code"] + [c for c in STANDARD_COLUMNS if c in df.columns]
        df = df[[c for c in keep_cols if c in df.columns]]

        return df

    def get_realtime_quote(self, stock_code: str) -> Optional[UnifiedRealtimeQuote]:
        """Get realtime quote from Baostock."""
        self._ensure_initialized()
        if not self._initialized:
            return None

        try:
            import baostock as bs

            bs_code, code = self._convert_code(stock_code)
            rs = bs.query_realtime_quotes(bs_code)

            if rs.error_code != "0":
                logger.warning(f"[BaostockFetcher] Realtime quote failed: {rs.error_msg}")
                return None

            data_list = []
            while rs.next():
                data_list.append(rs.get_row_data())

            if not data_list:
                return None

            row = pd.Series(data_list[0], index=rs.fields)

            return UnifiedRealtimeQuote(
                code=code,
                name=str(row.get("name", "")),
                source=RealtimeSource.FALLBACK,
                price=safe_float(row.get("close")),
                change_pct=safe_float(row.get("pct_chg")),
                change_amount=safe_float(row.get("chg")),
                volume=safe_int(row.get("volume")),
                amount=safe_float(row.get("amount")),
                open_price=safe_float(row.get("open")),
                high=safe_float(row.get("high")),
                low=safe_float(row.get("low")),
                pre_close=safe_float(row.get("preclose")),
            )

        except Exception as e:
            logger.warning(f"[BaostockFetcher] Realtime quote failed: {e}")
            return None


# Import STANDARD_COLUMNS at module level for use in _normalize_data
from .base import STANDARD_COLUMNS
