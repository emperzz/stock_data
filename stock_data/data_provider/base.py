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
    """Flag enum for fetcher data capabilities.

    Design rule: EVERY data access path in DataFetcherManager must route
    through _filter_by_capability(market, capability). Hardcoding a specific
    fetcher class (e.g. AkshareFetcher()) bypasses priority-based failover
    and is forbidden. If a data type needs routing, add a capability flag here
    and declare it on the fetchers that support it.
    """

    HISTORICAL_DWM = auto()  # 日/周/月 K线 (d/w/m)
    HISTORICAL_MIN = auto()  # 分钟 K线 (1/5/15/30/60m)
    REALTIME_QUOTE = auto()  # 实时报价
    STOCK_LIST = auto()  # 股票列表 (get_all_stocks)
    STOCK_NAME = auto()  # 股票名称 (get_stock_name)
    TRADE_CALENDAR = auto()  # 交易日历
    STOCK_BOARD = auto()  # 板块数据（概念/行业板块列表）
    INDEX_QUOTE = auto()  # 指数实时行情
    INDEX_HISTORICAL = auto()  # 指数历史K线 (d/w/m)
    INDEX_INTRADAY = auto()  # 指数日内分时 (1/5/15/30/60m)
    STOCK_ZT_POOL = auto()  # 涨跌停股池（涨停/跌停/炸板）
    DRAGON_TIGER = auto()  # 龙虎榜（个股+全市场）
    MARGIN_TRADING = auto()  # 融资融券
    BLOCK_TRADE = auto()  # 大宗交易
    HOLDER_NUM = auto()  # 股东户数变化
    DIVIDEND = auto()  # 分红送转
    FUND_FLOW = auto()  # 资金流（个股资金流分钟级+120日）
    HOT_TOPICS = auto()  # 热点题材（同花顺当日强势股+题材归因）
    NORTH_FLOW = auto()  # 北向资金（沪股通/深股通分钟流向）
    RESEARCH_REPORT = auto()  # 研报
    ANNOUNCEMENT = auto()  # 公告


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

    def get_report_pdf_url(self, report_id: str) -> str | None:
        """Return the canonical PDF URL for ``report_id``, or None if unsupported.

        Subclasses that serve research report PDFs override this and
        ``download_report_pdf``. The base implementation returns None so
        ``_filter_by_capability`` callers can transparently skip fetchers
        that don't serve PDFs.
        """
        return None

    def download_report_pdf(self, report_id: str) -> str | None:
        """Download the PDF for ``report_id`` to a local cache. Returns the
        local file path, or None if unsupported / download failed.
        """
        return None


# Backward-compatible re-export of DataFetcherManager (now in .manager)
from .manager import DataFetcherManager  # noqa: E402, F401
