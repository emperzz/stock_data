"""
Baostock fetcher for A-share stock data (Priority 1).

Free data source, no API token required.
"""

import logging
import os

import pandas as pd

from .base import (
    STANDARD_COLUMNS,
    BaseFetcher,
    DataFetchError,
    get_index_type,
    is_index_code,
    normalize_stock_code,
)
from .index_symbols import CSI_INDEX_MAP
from .realtime_types import UnifiedRealtimeQuote

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
            000300 -> (sh.000300, 000300)  CSI 300 index
            HSI -> raises DataFetchError (not supported by Baostock)
        """
        code = normalize_stock_code(stock_code)

        # Check if it's a CSI index
        if is_index_code(code):
            index_type = get_index_type(code)
            if index_type == "csi":
                # CSI indices use same sh./sz. format as stocks
                if code in CSI_INDEX_MAP:
                    bs_symbol = CSI_INDEX_MAP[code]
                    return bs_symbol, code
                # Fallback: CSI indices starting with 00 are Shanghai, 39 are Shenzhen
                if code.startswith("00"):
                    return f"sh.{code}", code
                else:
                    return f"sz.{code}", code
            else:
                # HK and US indices not supported by Baostock
                raise DataFetchError(f"Baostock does not support {index_type} index {code}")

        if code.startswith(("6", "5")):
            return f"sh.{code}", code
        else:
            return f"sz.{code}", code

    def _fetch_raw_data(
        self, stock_code: str, start_date: str, end_date: str, frequency: str = "d"
    ) -> pd.DataFrame:
        """Fetch K-line data from Baostock (supports d/w/m/5/15/30/60 for stocks, d/w/m for indices)."""
        self._ensure_initialized()
        if not self._initialized:
            raise DataFetchError("Baostock not available")

        # Check if requesting minute frequency for an index (indices don't support minute data)
        if frequency in ("5", "15", "30", "60"):
            code = normalize_stock_code(stock_code)
            if is_index_code(code) and get_index_type(code) == "csi":
                raise DataFetchError("Baostock does not support minute frequency for indices")

        try:
            import baostock as bs

            bs_code, _ = self._convert_code(stock_code)

            logger.debug(
                f"[BaostockFetcher] Calling query_history_k_data_plus for {bs_code} ({frequency})"
            )

            rs = bs.query_history_k_data_plus(
                bs_code,
                "date,open,high,low,close,volume,amount,pctChg",
                start_date=start_date,
                end_date=end_date,
                frequency=frequency,
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

        # Baostock uses pctChg, we want pct_chg
        if "pctChg" in df.columns:
            df = df.rename(columns={"pctChg": "pct_chg"})

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

    def get_realtime_quote(self, stock_code: str) -> UnifiedRealtimeQuote | None:
        """Get realtime quote from Baostock.

        Note: Baostock does NOT support realtime quotes - it only provides historical data.
        This method always returns None.
        """
        # Baostock has no realtime quotes API, only historical K-line data
        return None

    def get_all_stocks(self, market: str = "cn") -> list:
        """
        Get all available stocks for a market.

        Args:
            market: Market type - cn (A-share), hk, us

        Returns:
            List of dicts: [{"code": "600519", "name": "贵州茅台"}, ...]
        """
        if market != "cn":
            # Baostock only supports A-share
            return []

        self._ensure_initialized()
        if not self._initialized:
            return []

        try:
            import baostock as bs

            result = []
            # Query all A-share stocks (both sh and sz)
            rs = bs.query_all_stock()
            if rs.error_code != "0":
                logger.warning(f"[BaostockFetcher] query_all_stock failed: {rs.error_msg}")
                return []

            while rs.next():
                row = rs.get_row_data()
                if len(row) >= 2:
                    code = row[0]
                    name = row[1] if len(row) > 1 else ""
                    if code and code.startswith(("sh.", "sz.")):
                        # Normalize: sh.600519 -> 600519, sz.000001 -> 000001
                        code = code[3:]
                    if code:
                        result.append({"code": code, "name": name})

            return result

        except Exception as e:
            logger.warning(f"[BaostockFetcher] get_all_stocks failed: {e}")
            return []
