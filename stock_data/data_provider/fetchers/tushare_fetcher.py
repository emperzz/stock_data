"""
Tushare fetcher for A-share stock data (Priority 0).

Requires TUSHARE_TOKEN environment variable.
Gracefully falls back when token is not configured.
"""

import logging
import os
import threading
from typing import Any

import pandas as pd

from ..base import BaseFetcher, DataCapability, DataFetchError, normalize_stock_code
from ..core.types import RealtimeSource, UnifiedRealtimeQuote, safe_float, safe_int
from ..utils.code_converter import to_tushare_format
from ..utils.normalize import get_index_type, is_index_code

logger = logging.getLogger(__name__)


class TushareFetcher(BaseFetcher):
    """Tushare Pro API fetcher for A-share data."""

    name = "TushareFetcher"
    priority = int(os.getenv("TUSHARE_PRIORITY", "0"))
    supported_markets: set[str] = {"csi"}
    supported_data_types = (
        DataCapability.STOCK_KLINE
        | DataCapability.STOCK_REALTIME_QUOTE
        | DataCapability.INDEX_KLINE
    )

    # Class-level once-per-process init. The manifest builder and health
    # endpoint each create a fresh TushareFetcher per endpoint, so a
    # per-instance _initialized would re-run ts.pro_api() / env-var read
    # on every page load. Class-level state survives across instances:
    # init runs at most once per process, success or failure cached.
    # _init_lock guards against two threads both observing
    # _init_attempted==False and both running pro_api (the resulting
    # client object would just overwrite — benign today, but explicit).
    _init_lock: "threading.Lock" = threading.Lock()
    _init_attempted: bool = False
    _init_ok: bool = False
    _cls_token: str = ""
    _init_error: str | None = None
    _api: Any | None = None

    def _map_adjust(self, adjust: str) -> str | None:
        """Map unified adjust to Tushare value."""
        if not adjust:
            return None  # 不复权
        return adjust  # "qfq" or "hfq"

    def supports_kline(self, period, adjust, market, asset):
        # Tushare: only csi + d/w/m; weekly/monthly adjust IS supported via adj='qfq|hfq'.
        return market == "csi" and period in ("d", "w", "m")

    def __init__(self):
        pass

    def _ensure_api(self) -> None:
        """Lazily initialize Tushare API (once per process)."""
        if TushareFetcher._init_attempted:
            return
        with TushareFetcher._init_lock:
            # Double-check after acquiring the lock.
            if TushareFetcher._init_attempted:
                return
            TushareFetcher._init_attempted = True
            TushareFetcher._cls_token = os.getenv("TUSHARE_TOKEN", "").strip()

            if not TushareFetcher._cls_token:
                TushareFetcher._init_error = "TUSHARE_TOKEN not set"
                logger.warning(
                    "[TushareFetcher] TUSHARE_TOKEN not set, will return empty results"
                )
                return

            try:
                import tushare as ts

                TushareFetcher._api = ts.pro_api(TushareFetcher._cls_token)
                TushareFetcher._init_ok = True
                logger.info("[TushareFetcher] Initialized successfully")
            except Exception as e:
                TushareFetcher._init_error = str(e)
                logger.warning(f"[TushareFetcher] Failed to initialize: {e}")

    def is_available(self) -> bool:
        """Check if Tushare API is configured and available."""
        self._ensure_api()
        return TushareFetcher._init_ok

    def unavailable_reason(self) -> str | None:
        """Return a human-readable reason this fetcher is unavailable, or None."""
        if self.is_available():
            return None
        if not TushareFetcher._cls_token:
            return f"TUSHARE_TOKEN environment variable not set (required by {self.name})"
        return (
            f"tushare SDK could not initialize for {self.name} "
            f"({TushareFetcher._init_error or 'token may be invalid, or the tushare package is not importable'})"
        )

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
        if TushareFetcher._api is None:
            raise DataFetchError("Tushare API not available (no token)")

        try:
            code = normalize_stock_code(stock_code)
            is_index = is_index_code(code) and get_index_type(code) == "csi"

            try:
                ts_code = to_tushare_format(stock_code)
            except ValueError as e:
                raise DataFetchError(str(e)) from e

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

            df = TushareFetcher._api.query(
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
        if TushareFetcher._api is None:
            return None

        try:
            import tushare as ts

            code = normalize_stock_code(stock_code)
            ts_code = to_tushare_format(stock_code)

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
        if TushareFetcher._api is None:
            return None

        try:
            ts_code = to_tushare_format(stock_code)

            df = TushareFetcher._api.stock_basic(ts_code=ts_code, list_status="L")
            if df is not None and not df.empty:
                return df.iloc[0].get("name")
        except Exception as e:
            logger.warning(f"[TushareFetcher] get_stock_name failed: {e}")

        return None

    def get_index_historical(
        self, index_code: str, start_date: str | None, end_date: str | None, frequency: str
    ) -> pd.DataFrame | None:
        """Get historical K-line data for a CSI index.

        Internally delegates to get_kline_data which handles CSI indices via
        the index_daily/index_weekly/index_monthly API. Only d/w/m supported.

        Args:
            index_code: Index code (e.g., 000300, 399006)
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            frequency: K-line period - 'd'=daily, 'w'=weekly, 'm'=monthly

        Returns:
            DataFrame or None if not supported.
        """
        from datetime import datetime, timedelta

        code = normalize_stock_code(index_code)
        if not is_index_code(code) or get_index_type(code) != "csi":
            return None

        if not start_date:
            start_date = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")

        try:
            return self.get_kline_data(index_code, start_date, end_date, days=365, frequency=frequency)
        except DataFetchError:
            return None
