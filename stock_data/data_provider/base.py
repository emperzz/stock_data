"""
Base classes and manager for stock data fetchers.
"""

import logging
import random
import time
from abc import ABC, abstractmethod
from datetime import datetime
from enum import Flag, auto
from threading import RLock

import pandas as pd

from .core.types import UnifiedRealtimeQuote, get_realtime_circuit_breaker
from .utils.normalize import (
    ETF_PREFIXES,
    BSE_CODES,
    index_market_tag,
    is_hk_market,
    is_us_market,
    market_tag,
    normalize_stock_code,
)

logger = logging.getLogger(__name__)

# Standard columns for normalized K-line data
STANDARD_COLUMNS = ["date", "open", "high", "low", "close", "volume", "amount", "pct_chg"]


class DataCapability(Flag):
    """Flag enum for fetcher data capabilities."""

    HISTORICAL_DWM = auto()  # 日/周/月 K线 (d/w/m)
    HISTORICAL_MIN = auto()  # 分钟 K线 (1/5/15/30/60m)
    REALTIME_QUOTE = auto()  # 实时报价
    STOCK_LIST = auto()  # 股票列表 (get_all_stocks)
    STOCK_NAME = auto()  # 股票名称 (get_stock_name)
    TRADE_CALENDAR = auto()  # 交易日历
    STOCK_BOARD = auto()  # 板块数据（概念/行业板块列表）


class DataFetchError(Exception):
    """Raised when data fetching fails."""

    pass


class RateLimitError(DataFetchError):
    """Raised when rate limited by data source."""

    pass


# Re-export utilities for backward compatibility
__all__ = [
    "DataCapability",
    "DataFetchError",
    "DataFetcherManager",
    "RateLimitError",
    "STANDARD_COLUMNS",
    "BSE_CODES",
    "ETF_PREFIXES",
    "index_market_tag",
    "is_hk_market",
    "is_us_market",
    "market_tag",
    "normalize_stock_code",
]


class BaseFetcher(ABC):
    """
    Abstract base for stock data fetchers.

    Subclasses must implement:
    - _fetch_raw_data(): Fetch raw data from source
    - _normalize_data(): Normalize to standard columns
    """

    name: str = "BaseFetcher"
    priority: int = 99  # Lower is higher priority

    # Markets supported by this fetcher: {"csi", "hk", "us"}
    supported_markets: set[str] = set()
    # Data capabilities via Flag enum
    supported_data_types: DataCapability = DataCapability(0)  # empty by default

    def _map_adjust(self, adjust: str) -> str | None:
        """Map unified adjust parameter to provider-specific value.

        Unified values (from API layer):
            "" = 不复权, "qfq" = 前复权, "hfq" = 后复权

        Override in subclasses for source-specific mappings.
        Returns the provider-specific adjust value, or None.
        """
        if not adjust:
            return None
        return adjust

    @abstractmethod
    def _fetch_raw_data(
        self,
        stock_code: str,
        start_date: str,
        end_date: str,
        frequency: str = "d",
        adjust: str | None = None,
    ) -> pd.DataFrame:
        """Fetch raw data from the source. Returns DataFrame with source-specific columns.

        Args:
            stock_code: Stock code
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            frequency: K-line frequency - 'd'=日线, 'w'=周线, 'm'=月线, '5/15/30/60'=分钟线
            adjust: Provider-specific adjustment value (already mapped by _map_adjust)
        """
        pass

    @abstractmethod
    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        """Normalize data to standard columns: date, open, high, low, close, volume, amount, pct_chg."""
        pass

    def _normalize_dataframe(
        self,
        df: pd.DataFrame,
        stock_code: str,
        column_mapping: dict[str, str],
    ) -> pd.DataFrame:
        """Generic dataframe normalization using a column mapping dict.

        Handles rename, date conversion, numeric coercion, and standard column selection.
        Subclasses can call this from _normalize_data to reduce boilerplate.
        """
        df = df.rename(columns={k: v for k, v in column_mapping.items() if k in df.columns})

        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])

        numeric_cols = ["open", "high", "low", "close", "volume", "amount", "pct_chg"]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        if "code" not in df.columns:
            df["code"] = normalize_stock_code(stock_code)

        keep_cols = ["code"] + [c for c in STANDARD_COLUMNS if c in df.columns]
        df = df[[c for c in keep_cols if c in df.columns]]

        return df

    def get_kline_data(
        self,
        stock_code: str,
        start_date: str | None = None,
        end_date: str | None = None,
        days: int = 30,
        frequency: str = "d",
        adjust: str | None = None,
    ) -> pd.DataFrame:
        """
        Get K-line data (daily, weekly, monthly, or minute).

        Args:
            stock_code: Stock code
            start_date: Start date (YYYY-MM-DD), defaults to days ago
            end_date: End date (YYYY-MM-DD), defaults to today
            days: Number of days when start_date not provided
            frequency: K-line frequency - 'd'=日线, 'w'=周线, 'm'=月线, '5/15/30/60'=分钟线
            adjust: Adjustment type - None=不复权, 'qfq'=前复权, 'hfq'=后复权 (unified, mapped per-provider)

        Returns:
            DataFrame with standard columns and technical indicators
        """
        if end_date is None:
            end_date = datetime.now().strftime("%Y-%m-%d")

        if start_date is None:
            from datetime import timedelta

            start_dt = datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=days * 2)
            start_date = start_dt.strftime("%Y-%m-%d")

        # Map unified adjust to provider-specific value
        provider_adjust = self._map_adjust(adjust or "")

        logger.info(
            f"[{self.name}] Fetching {stock_code} {frequency} data: {start_date} ~ {end_date}"
        )

        try:
            raw_df = self._fetch_raw_data(
                stock_code, start_date, end_date, frequency, provider_adjust
            )
            if raw_df is None or raw_df.empty:
                raise DataFetchError(f"[{self.name}] No data for {stock_code}")

            df = self._normalize_data(raw_df, stock_code)
            # Single copy at entry point
            df = self._clean_data(df)
            df = self._calculate_indicators(df)

            logger.info(f"[{self.name}] {stock_code} got {len(df)} rows")
            return df

        except Exception as e:
            logger.error(f"[{self.name}] {stock_code} failed: {e}")
            raise DataFetchError(f"[{self.name}] {stock_code}: {e}") from e

    def _clean_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """Clean and validate data (operates in-place on caller's copy)."""
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])

        numeric_cols = ["open", "high", "low", "close", "volume", "amount", "pct_chg"]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        before = len(df)
        df = df.dropna(subset=["close", "volume"])
        dropped = before - len(df)
        if dropped > 0:
            logger.debug(f"[{self.name}] Dropped {dropped} rows with NaN close/volume")

        df = df.sort_values("date", ascending=True).reset_index(drop=True)
        return df

    def _calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calculate technical indicators (operates in-place on caller's copy)."""
        # Moving averages
        df["ma5"] = df["close"].rolling(window=5, min_periods=1).mean()
        df["ma10"] = df["close"].rolling(window=10, min_periods=1).mean()
        df["ma20"] = df["close"].rolling(window=20, min_periods=1).mean()

        # Volume ratio (guard against div-by-zero producing inf)
        avg_vol = df["volume"].rolling(window=5, min_periods=1).mean()
        df["volume_ratio"] = df["volume"] / avg_vol.shift(1)
        df["volume_ratio"] = (
            df["volume_ratio"].replace([float("inf"), float("-inf")], 1.0).fillna(1.0)
        )

        # Round to 2 decimals
        for col in ["ma5", "ma10", "ma20", "volume_ratio"]:
            if col in df.columns:
                df[col] = df[col].round(2)

        return df

    @staticmethod
    def random_sleep(min_seconds: float = 1.0, max_seconds: float = 3.0) -> None:
        """Sleep with random jitter to avoid rate limiting."""
        sleep_time = random.uniform(min_seconds, max_seconds)
        logger.debug(f"[{__name__}] Sleep {sleep_time:.2f}s")
        time.sleep(sleep_time)

    def get_realtime_quote(self, stock_code: str) -> UnifiedRealtimeQuote | None:
        """Get realtime quote. Override in subclass if supported."""
        return None

    def get_stock_name(self, stock_code: str) -> str | None:
        """Get stock name. Override in subclass if supported."""
        return None

    def get_all_stocks(self, market: str = "csi") -> list:
        """Get all available stocks for a market. Override in subclass if supported."""
        return []

    def get_trade_calendar(self) -> list[str] | None:
        """Get trade calendar dates. Override in subclass if supported.

        Returns:
            List of trade dates as YYYY-MM-DD strings, sorted ascending,
            or None if not supported by this fetcher.
        """
        return None

    def get_intraday_data(
        self, stock_code: str, period: str = "5", adjust: str = ""
    ) -> pd.DataFrame | None:
        """Get intraday minute-level data for a stock.

        Args:
            stock_code: Stock code (e.g., 600519, 000001)
            period: Minute period - "1", "5", "15", "30", "60"
            adjust: Adjustment type - ""=不复权, "qfq"=前复权, "hfq"=后复权

        Returns:
            DataFrame with columns: time, open, high, low, close, volume, amount
            or None if not supported.
        """
        return None


class DataFetcherManager:
    """
    Manager for multiple data fetchers with priority-based failover.

    Market routing is driven by each fetcher's supported_markets class attribute
    combined with the DataCapability supported_data_types flags.

    Usage:
        manager = DataFetcherManager()
        df, source = manager.get_kline_data("600519")
    """

    def __init__(self, fetchers: list[BaseFetcher] | None = None):
        self._fetchers: list[BaseFetcher] = []
        self._fetchers_by_name: dict = {}
        self._lock = RLock()

        if fetchers:
            self._fetchers = sorted(fetchers, key=lambda f: f.priority)
            self._refresh_index()

    def reset(self) -> None:
        """Clear all fetchers, allowing re-registration (e.g., after config changes)."""
        with self._lock:
            self._fetchers.clear()
            self._fetchers_by_name.clear()

    def _refresh_index(self) -> None:
        """Refresh fetcher name index."""
        self._fetchers_by_name = {f.name: f for f in self._fetchers}

    def add_fetcher(self, fetcher: BaseFetcher) -> None:
        """Add a fetcher and re-sort by priority."""
        with self._lock:
            self._fetchers.append(fetcher)
            self._fetchers.sort(key=lambda f: f.priority)
            self._refresh_index()

    def get_fetcher(self, name: str) -> BaseFetcher | None:
        """Get fetcher by name."""
        return self._fetchers_by_name.get(name)

    def _filter_by_capability(self, market: str, capability: DataCapability) -> list[BaseFetcher]:
        """Filter fetchers by market support and data capability.

        Args:
            market: Market tag (csi/hk/us)
            capability: Required DataCapability flag

        Returns:
            Filtered list of fetchers sorted by priority.
        """
        result = []
        for f in self._fetchers:
            if market not in f.supported_markets:
                continue
            if capability not in f.supported_data_types:
                continue
            result.append(f)
        return result

    def get_kline_data(
        self,
        stock_code: str,
        start_date: str | None = None,
        end_date: str | None = None,
        days: int = 30,
        frequency: str = "d",
        adjust: str | None = None,
    ) -> tuple[pd.DataFrame, str]:
        """
        Get K-line data with automatic failover.

        Args:
            stock_code: Stock code
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            days: Number of days when start_date not provided
            frequency: K-line frequency - 'd'=日线, 'w'=周线, 'm'=月线, '5/15/30/60'=分钟线
            adjust: Adjustment type - None=不复权, 'qfq'=前复权, 'hfq'=后复权

        Returns:
            Tuple of (DataFrame, source_name)

        Raises:
            DataFetchError: When all fetchers fail
        """
        stock_code = normalize_stock_code(stock_code)

        # Check if it's an index code for routing
        index_tag = index_market_tag(stock_code)

        # Determine capability based on frequency
        if frequency in ("5", "15", "30", "60"):
            cap = DataCapability.HISTORICAL_MIN
        else:
            cap = DataCapability.HISTORICAL_DWM

        if index_tag:
            fetchers = self._filter_by_capability(index_tag, cap)
            if not fetchers:
                fetchers = self._filter_by_capability(market_tag(stock_code), cap)
        else:
            market = market_tag(stock_code)
            fetchers = self._filter_by_capability(market, cap)

        errors = []

        for fetcher in fetchers:
            try:
                logger.info(f"[Manager] Trying {fetcher.name} for {stock_code} ({frequency})")
                df = fetcher.get_kline_data(
                    stock_code, start_date, end_date, days, frequency, adjust
                )
                if df is not None and not df.empty:
                    logger.info(f"[Manager] {fetcher.name} succeeded for {stock_code}")
                    return df, fetcher.name
            except Exception as e:
                errors.append(f"[{fetcher.name}] {e}")
                logger.warning(f"[Manager] {fetcher.name} failed: {e}")
                continue

        raise DataFetchError(f"All fetchers failed for {stock_code}:\n" + "\n".join(errors))

    def get_realtime_quote(self, stock_code: str) -> UnifiedRealtimeQuote | None:
        """Get realtime quote with automatic failover and circuit breaker."""
        stock_code = normalize_stock_code(stock_code)
        market = market_tag(stock_code)

        cb = get_realtime_circuit_breaker()
        fetchers = self._filter_by_capability(market, DataCapability.REALTIME_QUOTE)

        for fetcher in fetchers:
            if not cb.is_available(fetcher.name):
                logger.debug(f"[Manager] {fetcher.name} circuit open, skipping")
                continue
            try:
                quote = fetcher.get_realtime_quote(stock_code)
                if quote is not None:
                    cb.record_success(fetcher.name)
                    return quote
                cb.record_failure(fetcher.name)
            except Exception as e:
                cb.record_failure(fetcher.name)
                logger.warning(f"[Manager] {fetcher.name} realtime quote failed: {e}")
                continue

        return None

    def get_intraday_data(
        self, stock_code: str, period: str = "5", adjust: str = ""
    ) -> tuple[pd.DataFrame, str]:
        """Get intraday minute-level data with automatic failover.

        Args:
            stock_code: Stock code
            period: Minute period - "1", "5", "15", "30", "60"
            adjust: Adjustment type - ""=不复权, "qfq"=前复权, "hfq"=后复权

        Returns:
            Tuple of (DataFrame, source_name)

        Raises:
            DataFetchError: When all fetchers fail
        """
        stock_code = normalize_stock_code(stock_code)
        market = market_tag(stock_code)
        fetchers = self._filter_by_capability(market, DataCapability.HISTORICAL_MIN)

        errors = []
        for fetcher in fetchers:
            try:
                logger.info(f"[Manager] Trying {fetcher.name} for {stock_code} intraday ({period})")
                df = fetcher.get_intraday_data(stock_code, period, adjust)
                if df is not None and not df.empty:
                    logger.info(f"[Manager] {fetcher.name} succeeded for {stock_code} intraday")
                    return df, fetcher.name
            except Exception as e:
                errors.append(f"[{fetcher.name}] {e}")
                logger.warning(f"[Manager] {fetcher.name} intraday failed: {e}")
                continue

        raise DataFetchError(
            f"All fetchers failed for {stock_code} intraday:\n" + "\n".join(errors)
        )

    def get_trade_calendar(self) -> list[str]:
        """Get A-share trade calendar with automatic failover.

        Tries each fetcher's get_trade_calendar() in priority order.
        Akshare is primary; Baostock is fallback.

        Returns:
            List of trade dates as YYYY-MM-DD strings, sorted ascending.

        Raises:
            DataFetchError: When all fetchers fail.
        """
        from .cache.trade_calendar_cache import get_cached_calendar, update_cached_calendar

        fetchers = self._filter_by_capability("csi", DataCapability.TRADE_CALENDAR)

        errors = []
        for fetcher in fetchers:
            try:
                dates = fetcher.get_trade_calendar()
                if dates:
                    update_cached_calendar(dates)
                    logger.info(f"[Manager] {fetcher.name} returned {len(dates)} calendar dates")
                    return sorted(dates)
            except Exception as e:
                errors.append(f"[{fetcher.name}] {e}")
                logger.warning(f"[Manager] {fetcher.name} calendar failed: {e}")
                continue

        # Fallback: return cached data if upstream fails
        cached = get_cached_calendar()
        if cached:
            logger.warning(
                f"[Manager] All fetchers failed calendar, using {len(cached)} cached dates"
            )
            return cached

        raise DataFetchError("All fetchers failed for trade calendar:\n" + "\n".join(errors))

    @property
    def available_fetchers(self) -> list[str]:
        """List available fetcher names."""
        return [f.name for f in self._fetchers]

    @property
    def fetchers(self) -> list["BaseFetcher"]:  # type: ignore[misc]
        """List all fetchers. Prefer get_fetcher() for single fetcher lookup."""
        return list(self._fetchers)