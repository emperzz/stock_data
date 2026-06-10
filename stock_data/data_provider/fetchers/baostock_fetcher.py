"""
Baostock fetcher for A-share stock data (Priority 1).

Free data source, no API token required.
"""

import logging
import os

import pandas as pd

from ..base import (
    BaseFetcher,
    DataCapability,
    DataFetchError,
    normalize_stock_code,
)
from ..core.types import UnifiedRealtimeQuote
from ..utils.code_converter import to_baostock_format
from ..utils.normalize import get_index_type, is_a_share_stock_code, is_index_code

logger = logging.getLogger(__name__)


class BaostockFetcher(BaseFetcher):
    """Baostock API fetcher for A-share data (free, no token)."""

    name = "BaostockFetcher"
    priority = int(os.getenv("BAOSTOCK_PRIORITY", "1"))
    supported_markets: set[str] = {"csi"}
    supported_data_types = (
        DataCapability.HISTORICAL_DWM
        | DataCapability.HISTORICAL_MIN
        | DataCapability.TRADE_CALENDAR
        | DataCapability.INDEX_HISTORICAL
    )

    def _map_adjust(self, adjust: str) -> str | None:
        """Map unified adjust to Baostock adjustflag."""
        if not adjust:
            return "3"  # 不复权
        mapping = {"qfq": "2", "hfq": "1"}
        return mapping.get(adjust, "3")

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
        """Convert to Baostock ``(bs_code, yw_code)``. Delegates to ``to_baostock_format``."""
        try:
            return to_baostock_format(stock_code)
        except ValueError as e:
            raise DataFetchError(str(e)) from e

    def _fetch_raw_data(
        self,
        stock_code: str,
        start_date: str,
        end_date: str,
        frequency: str = "d",
        adjust: str | None = None,
    ) -> pd.DataFrame:
        """Fetch K-line data from Baostock (supports d/w/m/5/15/30/60 for stocks, d/w/m for indices).

        Args:
            stock_code: Stock code
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            frequency: K-line frequency - 'd'=日线, 'w'=周线, 'm'=月线, '5/15/30/60'=分钟线
            adjust: Adjustment type - None/3=不复权, '2'=前复权, '1'=后复权.
                   Defaults to '2' (前复权) if not specified.
        """
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

            # adjust is already mapped by _map_adjust
            adjflag = adjust or "3"

            logger.debug(
                f"[BaostockFetcher] Calling query_history_k_data_plus for {bs_code} ({frequency}, adjustflag={adjflag})"
            )

            rs = bs.query_history_k_data_plus(
                bs_code,
                "date,open,high,low,close,volume,amount,pctChg",
                start_date=start_date,
                end_date=end_date,
                frequency=frequency,
                adjustflag=adjflag,
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
        return self._normalize_dataframe(df, stock_code, {"pctChg": "pct_chg"})

    def get_realtime_quote(self, stock_code: str) -> UnifiedRealtimeQuote | None:
        """Get realtime quote from Baostock.

        Note: Baostock does NOT support realtime quotes - it only provides historical data.
        This method always returns None.
        """
        # Baostock has no realtime quotes API, only historical K-line data
        return None

    def get_stock_name(self, stock_code: str) -> str | None:
        """Get stock name from Baostock query_stock_basic."""
        self._ensure_initialized()
        if not self._initialized:
            return None

        try:
            import baostock as bs

            bs_code, _ = self._convert_code(stock_code)
            rs = bs.query_stock_basic(code=bs_code)
            if rs.error_code != "0":
                return None

            while rs.next():
                row = rs.get_row_data()
                if len(row) >= 2:
                    return row[1]  # code_name
        except Exception:
            logger.debug("Failed to query stock name via baostock", exc_info=True)

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
            # Baostock only supports A-share. 'cn' is the fetcher-internal
            # tag; the public 'csi' is translated upstream by
            # persistence/stock_list.py.
            return []

        self._ensure_initialized()
        if not self._initialized:
            return []

        try:
            from datetime import date

            import baostock as bs

            result = []
            # Query all A-share stocks, must pass trading day parameter for non-empty results
            # Use cached trade calendar to find valid trading dates
            from ..persistence.trade_calendar import get_cached_calendar

            today_str = date.today().strftime("%Y-%m-%d")
            calendar = get_cached_calendar()
            # Find most recent date <= today, iterate in reverse to get latest first
            valid_dates = [d for d in reversed(calendar) if d <= today_str]

            query_day = None
            for d in valid_dates:
                rs = bs.query_all_stock(day=d)
                if rs.error_code == "0":
                    df = rs.get_data()
                    if df is not None and not df.empty:
                        query_day = d
                        for _, row in df.iterrows():
                            code = str(row.get("code", "")).strip()
                            name = str(row.get("code_name", "")).strip()
                            # Exclude indices: sh.000xxx are all indices (e.g., sh.000001 = 上证指数)
                            # Keep sz.000xxx which are real stocks (e.g., sz.000001 = 平安银行)
                            if code.startswith("sh.000") or code.startswith("sz.000"):
                                # Keep only if it's sz.000xxx (real stock), skip sh.000xxx (index)
                                if code.startswith("sz.000"):
                                    code = code[3:]  # sz.000001 -> 000001
                                    result.append({"code": code, "name": name})
                                continue
                            if code and code.startswith(("sh.", "sz.")):
                                code = code[3:]
                            # Filter: only actual stocks (not ETFs or indices).
                            # The A-share stock prefix list is centralised in
                            # utils/normalize.py (A_SHARE_STOCK_PREFIXES) so
                            # adding a new board code is a one-line change.
                            if is_a_share_stock_code(code):
                                result.append({"code": code, "name": name})
                        break

            if not query_day:
                logger.warning("[BaostockFetcher] query_all_stock returned no data for any cached trading day")

            return result

        except Exception as e:
            logger.warning(f"[BaostockFetcher] get_all_stocks failed: {e}")
            return []

    def get_trade_calendar(self) -> list[str] | None:
        """Get A-share trade calendar from Baostock."""
        import baostock as bs

        try:
            rs = bs.query_trade_dates()
            dates = []
            while rs.error_code == "0" and rs.next():
                row = rs.get_row_data()
                if row[1] == "1":  # is_trading_day == "1"
                    dates.append(row[0])
            if dates:
                return sorted(dates)
        except Exception as e:
            logger.warning(f"[BaostockFetcher] get_trade_calendar failed: {e}")
        return None

    def get_index_historical(
        self, index_code: str, start_date: str | None, end_date: str | None, frequency: str
    ) -> pd.DataFrame | None:
        """Get historical K-line data for a CSI index.

        Internally delegates to get_kline_data which handles CSI indices via
        _convert_code (sh.000300 / sz.399006 format). Only d/w/m supported;
        minute frequency not supported for indices.

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
        if frequency in ("5", "15", "30", "60"):
            return None

        if not start_date:
            start_date = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")

        try:
            return self.get_kline_data(index_code, start_date, end_date, days=365, frequency=frequency)
        except DataFetchError:
            return None
