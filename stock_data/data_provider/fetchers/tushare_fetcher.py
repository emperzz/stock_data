"""
Tushare fetcher for A-share stock data (Priority 0).

Requires TUSHARE_TOKEN environment variable.
Gracefully falls back when token is not configured.
"""

import logging
import os

import pandas as pd

from ..base import BaseFetcher, DataCapability, DataFetchError, normalize_stock_code
from ..core.types import RealtimeSource, UnifiedRealtimeQuote, safe_float, safe_int
from ..index_symbols import CSI_INDEX_MAP
from ..utils.normalize import get_index_type, is_index_code

logger = logging.getLogger(__name__)


class TushareFetcher(BaseFetcher):
    """Tushare Pro API fetcher for A-share data."""

    name = "TushareFetcher"
    priority = int(os.getenv("TUSHARE_PRIORITY", "0"))
    supported_markets: set[str] = {"csi"}
    supported_data_types = DataCapability.HISTORICAL_DWM | DataCapability.REALTIME_QUOTE | DataCapability.STOCK_LIST | DataCapability.STOCK_NAME

    def _map_adjust(self, adjust: str) -> str | None:
        """Map unified adjust to Tushare value."""
        if not adjust:
            return None  # 不复权
        return adjust  # "qfq" or "hfq"

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

    def _fetch_raw_data(
        self,
        stock_code: str,
        start_date: str,
        end_date: str,
        frequency: str = "d",
        adjust: str | None = None,
    ) -> pd.DataFrame:
        """Fetch K-line data from Tushare (supports d/w/m for stocks and CSI indices).

        Args:
            stock_code: Stock code
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            frequency: K-line frequency - 'd'=日线, 'w'=周线, 'm'=月线
            adjust: Adjustment type - None=不复权, 'qfq'=前复权, 'hfq'=后复权.
                   Only effective for stocks with 'd' frequency. Indices ignore this parameter.
        """
        self._ensure_api()
        if self._api is None:
            raise DataFetchError("Tushare API not available (no token)")

        try:
            code = normalize_stock_code(stock_code)
            is_index = is_index_code(code) and get_index_type(code) == "csi"

            if is_index:
                # CSI index: use index_daily API (no adjustment support)
                entry = CSI_INDEX_MAP.get(code)
                if entry is not None:
                    bs_symbol = entry[0]
                    market_prefix = bs_symbol.split(".")[0].upper()
                    numeric_code = bs_symbol.split(".")[1]
                    ts_code = f"{numeric_code}.{market_prefix}"
                else:
                    ts_code = f"{code}.SH"
            else:
                # Regular stock
                if code.startswith(("6", "5")):
                    ts_code = f"{code}.SH"
                elif code.startswith(("4", "3", "0", "1", "2")):
                    ts_code = f"{code}.SZ"
                else:
                    raise DataFetchError(f"TushareFetcher does not support {stock_code}")

            start = start_date.replace("-", "")
            end = end_date.replace("-", "")

            # Map frequency to pro_bar freq
            freq_map = {"d": "D", "w": "W", "m": "M"}
            freq = freq_map.get(frequency, "D")

            # For stock daily data, determine adjustment handling
            # adjust=None means no adjustment (use api.query)
            # adjust='qfq' or 'hfq' means use pro_bar with adjustment
            if not is_index and frequency == "d" and adjust in ("qfq", "hfq"):
                import tushare as ts

                logger.debug(f"[TushareFetcher] Calling pro_bar for {ts_code} (adj={adjust})")

                df = ts.pro_bar(
                    ts_code=ts_code,
                    start_date=start,
                    end_date=end,
                    freq=freq,
                    adj=adjust,
                )
                if df is None or df.empty:
                    raise DataFetchError(f"Tushare returned no data for {stock_code}")
                return df

            # For no adjustment (adjust=None) or weekly/monthly/indices, use api.query
            api_map = {"d": "daily", "w": "weekly", "m": "monthly"}
            api_name = api_map.get(frequency)
            if not api_name:
                raise DataFetchError(f"TushareFetcher only supports d/w/m, got '{frequency}'")

            logger.debug(f"[TushareFetcher] Calling {api_name} for {ts_code} (no adjustment)")

            df = self._api.query(
                api_name,
                ts_code=ts_code,
                start_date=start,
                end_date=end,
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

        # Rename columns
        df = df.rename(columns={"trade_date": "date", "vol": "_vol_hand"})

        # Tushare vol is in "手" (100 shares per hand), convert to shares
        if "_vol_hand" in df.columns:
            df["volume"] = pd.to_numeric(df["_vol_hand"], errors="coerce") * 100
            df.drop(columns=["_vol_hand"], inplace=True)

        # Convert Tushare amount from 千 yuan to yuan
        if "amount" in df.columns:
            df["amount"] = pd.to_numeric(df["amount"], errors="coerce") * 1000

        # Use common normalization for the rest
        return self._normalize_dataframe(df, stock_code, {})

    def get_realtime_quote(self, stock_code: str) -> UnifiedRealtimeQuote | None:
        """Get realtime quote from Tushare (requires tick data permission)."""
        self._ensure_api()
        if self._api is None:
            return None

        try:
            import tushare as ts

            code = normalize_stock_code(stock_code)
            ts_code = f"{code}.SH" if code.startswith(("6", "5")) else f"{code}.SZ"

            # Try to get realtime tick via tushare directly
            df = ts.realtime_quote(ts_code=ts_code)
            if df is None or df.empty:
                return None

            row = df.iloc[0]

            # Check if data is valid (not all nulls/empty)
            # Tushare returns null fields when token lacks permission
            price = safe_float(row.get("price"))
            if price is None:
                logger.warning(f"[TushareFetcher] Realtime quote returned null data for {code}")
                return None

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

        except Exception:
            logger.warning(
                f"[TushareFetcher] Realtime quote failed for {stock_code}", exc_info=True
            )
            return None

    def get_stock_name(self, stock_code: str) -> str | None:
        """Get stock name from Tushare basic info."""
        self._ensure_api()
        if self._api is None:
            return None

        try:
            code = normalize_stock_code(stock_code)
            ts_code = f"{code}.SH" if code.startswith(("6", "5")) else f"{code}.SZ"

            df = self._api.stock_basic(ts_code=ts_code, list_status="L")
            if df is not None and not df.empty:
                return df.iloc[0].get("name")
        except Exception as e:
            logger.warning(f"[TushareFetcher] get_stock_name failed: {e}")

        return None
