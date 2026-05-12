# -*- coding: utf-8 -*-
"""
Base classes and manager for stock data fetchers.
"""

import logging
import os
import random
import time
from abc import ABC, abstractmethod
from datetime import datetime
from threading import RLock
from typing import Any, List, Optional, Tuple

import pandas as pd

from .realtime_types import get_realtime_circuit_breaker

logger = logging.getLogger(__name__)

# Standard columns for normalized K-line data
STANDARD_COLUMNS = ["date", "open", "high", "low", "close", "volume", "amount", "pct_chg"]


class DataFetchError(Exception):
    """Raised when data fetching fails."""

    pass


class RateLimitError(DataFetchError):
    """Raised when rate limited by data source."""

    pass


# Market tag constants
ETF_PREFIXES = ("51", "52", "56", "58", "15", "16", "18")
BSE_CODES = ("92", "43", "81", "82", "83", "87", "88")


def normalize_stock_code(code: str) -> str:
    """
    Normalize stock code to canonical form.

    Examples:
        'SH600519' -> '600519'
        'SZ000001' -> '000001'
        'HK00700' -> 'HK00700'
        '600519.SS' -> '600519'
        'AAPL' -> 'AAPL'
    """
    code = code.strip()
    upper = code.upper()

    # HK prefix normalization
    if upper.startswith("HK") and not upper.startswith("HK."):
        digits = upper[2:]
        if digits.isdigit() and 1 <= len(digits) <= 5:
            return f"HK{digits.zfill(5)}"

    # Strip SH/SZ prefix
    if upper.startswith(("SH", "SZ")) and not upper.startswith(("SH.", "SZ.")):
        digits = code[2:]
        if digits.isdigit() and len(digits) in (5, 6):
            return digits

    # Strip BJ prefix
    if upper.startswith("BJ"):
        digits = code[2:]
        if digits.isdigit() and len(digits) == 6:
            return digits

    # Handle suffix forms
    if "." in code:
        base, suffix = code.rsplit(".", 1)
        if suffix.upper() == "HK" and base.isdigit() and 1 <= len(base) <= 5:
            return f"HK{base.zfill(5)}"
        if suffix.upper() in ("SH", "SZ", "SS", "BJ") and base.isdigit():
            return base
        # US stock like AAPL.US -> AAPL
        return code.upper()

    # For US codes (all letters), uppercase
    if code.isalpha():
        return code.upper()

    return code


def canonical_stock_code(code: str) -> str:
    """Return uppercase canonical form."""
    return code.strip().upper()


def is_us_market(code: str) -> bool:
    """Check if code is US stock/index."""
    code = (code or "").strip().upper()
    # 1-5 uppercase letters, optionally with .X suffix
    if len(code) <= 5 and code.isalpha():
        return True
    if "." in code:
        parts = code.split(".")
        return len(parts[0]) <= 5 and parts[0].isalpha()
    return False


def is_hk_market(code: str) -> bool:
    """Check if code is HK stock."""
    code = (code or "").strip().upper()
    if code.startswith("HK"):
        return True
    if code.endswith(".HK"):
        base = code[:-3]
        return base.isdigit() and 1 <= len(base) <= 5
    if code.isdigit() and len(code) == 5:
        return True
    return False


def is_etf_code(code: str) -> bool:
    """Check if code is A-share ETF."""
    normalized = normalize_stock_code(code)
    return normalized.isdigit() and len(normalized) == 6 and normalized.startswith(ETF_PREFIXES)


def is_bse_code(code: str) -> bool:
    """Check if code is Beijing Stock Exchange."""
    c = (code or "").strip().split(".")[0]
    if len(c) != 6 or not c.isdigit():
        return False
    return c.startswith(BSE_CODES)


def market_tag(code: str) -> str:
    """Return market tag: cn/us/hk."""
    if is_us_market(code):
        return "us"
    if is_hk_market(code):
        return "hk"
    return "cn"


class BaseFetcher(ABC):
    """
    Abstract base for stock data fetchers.

    Subclasses must implement:
    - _fetch_raw_data(): Fetch raw data from source
    - _normalize_data(): Normalize to standard columns
    """

    name: str = "BaseFetcher"
    priority: int = 99  # Lower is higher priority

    @abstractmethod
    def _fetch_raw_data(
        self, stock_code: str, start_date: str, end_date: str, frequency: str = "d"
    ) -> pd.DataFrame:
        """Fetch raw data from the source. Returns DataFrame with source-specific columns.

        Args:
            stock_code: Stock code
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            frequency: K-line frequency - 'd'=日线, 'w'=周线, 'm'=月线, '5/15/30/60'=分钟线
        """
        pass

    @abstractmethod
    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        """Normalize data to standard columns: date, open, high, low, close, volume, amount, pct_chg."""
        pass

    def get_daily_data(
        self,
        stock_code: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        days: int = 30,
        frequency: str = "d",
    ) -> pd.DataFrame:
        """
        Get daily K-line data.

        Args:
            stock_code: Stock code
            start_date: Start date (YYYY-MM-DD), defaults to days ago
            end_date: End date (YYYY-MM-DD), defaults to today
            days: Number of days when start_date not provided
            frequency: K-line frequency - 'd'=日线, 'w'=周线, 'm'=月线, '5/15/30/60'=分钟线

        Returns:
            DataFrame with standard columns and technical indicators
        """
        if end_date is None:
            end_date = datetime.now().strftime("%Y-%m-%d")

        if start_date is None:
            from datetime import timedelta

            start_dt = datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=days * 2)
            start_date = start_dt.strftime("%Y-%m-%d")

        logger.info(f"[{self.name}] Fetching {stock_code} {frequency} data: {start_date} ~ {end_date}")

        try:
            raw_df = self._fetch_raw_data(stock_code, start_date, end_date, frequency)
            if raw_df is None or raw_df.empty:
                raise DataFetchError(f"[{self.name}] No data for {stock_code}")

            df = self._normalize_data(raw_df, stock_code)
            df = self._clean_data(df)
            df = self._calculate_indicators(df)

            logger.info(f"[{self.name}] {stock_code} got {len(df)} rows")
            return df

        except Exception as e:
            logger.error(f"[{self.name}] {stock_code} failed: {e}")
            raise DataFetchError(f"[{self.name}] {stock_code}: {e}") from e

    def _clean_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """Clean and validate data."""
        df = df.copy()

        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])

        numeric_cols = ["open", "high", "low", "close", "volume", "amount", "pct_chg"]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        df = df.dropna(subset=["close", "volume"])
        df = df.sort_values("date", ascending=True).reset_index(drop=True)
        return df

    def _calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calculate technical indicators."""
        df = df.copy()

        # Moving averages
        df["ma5"] = df["close"].rolling(window=5, min_periods=1).mean()
        df["ma10"] = df["close"].rolling(window=10, min_periods=1).mean()
        df["ma20"] = df["close"].rolling(window=20, min_periods=1).mean()

        # Volume ratio
        avg_vol = df["volume"].rolling(window=5, min_periods=1).mean()
        df["volume_ratio"] = df["volume"] / avg_vol.shift(1)
        df["volume_ratio"] = df["volume_ratio"].fillna(1.0)

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

    def get_realtime_quote(self, stock_code: str) -> Optional[Any]:
        """Get realtime quote. Override in subclass if supported."""
        return None

    def get_stock_name(self, stock_code: str) -> Optional[str]:
        """Get stock name. Override in subclass if supported."""
        return None


class DataFetcherManager:
    """
    Manager for multiple data fetchers with priority-based failover.

    Usage:
        manager = DataFetcherManager()
        df, source = manager.get_daily_data("600519")
    """

    # Market support per fetcher
    _MARKET_SUPPORT = {
        "TushareFetcher": {"cn", "hk"},
        "BaostockFetcher": {"cn"},
        "AkshareFetcher": {"cn", "hk"},
        "YfinanceFetcher": {"cn", "hk", "us"},
    }

    def __init__(self, fetchers: Optional[List[BaseFetcher]] = None):
        self._fetchers: List[BaseFetcher] = []
        self._fetchers_by_name: dict = {}
        self._lock = RLock()

        if fetchers:
            self._fetchers = sorted(fetchers, key=lambda f: f.priority)
            self._refresh_index()

    def _refresh_index(self) -> None:
        """Refresh fetcher name index."""
        self._fetchers_by_name = {f.name: f for f in self._fetchers}

    def add_fetcher(self, fetcher: BaseFetcher) -> None:
        """Add a fetcher and re-sort by priority."""
        with self._lock:
            self._fetchers.append(fetcher)
            self._fetchers.sort(key=lambda f: f.priority)
            self._refresh_index()

    def get_fetcher(self, name: str) -> Optional[BaseFetcher]:
        """Get fetcher by name."""
        return self._fetchers_by_name.get(name)

    def _filter_by_market(self, market: str) -> List[BaseFetcher]:
        """Filter fetchers by market support."""
        result = []
        for f in self._fetchers:
            supported = self._MARKET_SUPPORT.get(f.name)
            if supported is None or market in supported:
                result.append(f)
        return result

    def get_daily_data(
        self,
        stock_code: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        days: int = 30,
        frequency: str = "d",
    ) -> Tuple[pd.DataFrame, str]:
        """
        Get daily data with automatic failover.

        Args:
            stock_code: Stock code
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            days: Number of days when start_date not provided
            frequency: K-line frequency - 'd'=日线, 'w'=周线, 'm'=月线, '5/15/30/60'=分钟线

        Returns:
            Tuple of (DataFrame, source_name)

        Raises:
            DataFetchError: When all fetchers fail
        """
        stock_code = normalize_stock_code(stock_code)
        market = market_tag(stock_code)

        fetchers = self._filter_by_market(market)
        errors = []

        for fetcher in fetchers:
            try:
                logger.info(f"[Manager] Trying {fetcher.name} for {stock_code} ({frequency})")
                df = fetcher.get_daily_data(stock_code, start_date, end_date, days, frequency)
                if df is not None and not df.empty:
                    logger.info(f"[Manager] {fetcher.name} succeeded for {stock_code}")
                    return df, fetcher.name
            except Exception as e:
                errors.append(f"[{fetcher.name}] {e}")
                logger.warning(f"[Manager] {fetcher.name} failed: {e}")
                continue

        raise DataFetchError(f"All fetchers failed for {stock_code}:\n" + "\n".join(errors))

    def get_realtime_quote(self, stock_code: str) -> Optional[Any]:
        """Get realtime quote with automatic failover."""
        stock_code = normalize_stock_code(stock_code)
        market = market_tag(stock_code)

        cb = get_realtime_circuit_breaker()
        fetchers = self._filter_by_market(market)

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

    @property
    def available_fetchers(self) -> List[str]:
        """List available fetcher names."""
        return [f.name for f in self._fetchers]
