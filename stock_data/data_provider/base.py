"""
Base classes and manager for stock data fetchers.
"""

import logging
from abc import ABC, abstractmethod
from datetime import datetime
from enum import Flag, auto

import pandas as pd

from .core.types import UnifiedRealtimeQuote
from .utils.normalize import (
    is_hk_market,  # noqa: F401 — re-exported for fetchers
    is_us_market,  # noqa: F401 — re-exported for fetchers
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

    # --- rev 3 unified flags ---
    STOCK_KLINE = auto()              # 股票 d/w/m + 1m/5m/15m/30m/60m
    INDEX_KLINE = auto()              # 指数 d/w/m + 1m/5m/15m/30m/60m
    STOCK_REALTIME_QUOTE = auto()     # 股票实时快照
    INDEX_REALTIME_QUOTE = auto()     # 指数实时快照
    # --- unchanged ---
    STOCK_LIST = auto()  # 股票列表 (get_all_stocks)
    TRADE_CALENDAR = auto()  # 交易日历
    STOCK_BOARD = auto()  # 板块数据（概念/行业板块列表）
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
    STOCK_INFO = auto()  # 公司画像（上市日期/概念/经营范围/注册地/总股本等）
    NEWS_SEARCH = auto()  # 新闻搜索（关键词 → 列表）
    NEWS_FLASH = auto()  # 全球财经快讯（7×24 实时推送流）


# ────────────────────────────────────────────────────────────────────────
# Capability → fetcher method name lookup
# ────────────────────────────────────────────────────────────────────────
#
# Single source of truth used by the explorer manifest (`build_manifest`)
# to enumerate "which fetcher method corresponds to this capability".
# Manager.py does NOT consume this table — its routing methods already
# hardcode the method call (e.g. `manager.get_kline_data` calls
# `fetcher.get_kline_data` directly). This table is reflection-only.
#
# Rule (enforced by tests/test_capability_method_map.py):
#   Every DataCapability flag MUST be in CAPABILITY_TO_METHOD.
#   Adding a new capability without declaring intent breaks the test suite.
#
# When a single capability is used by multiple endpoints that call
# different fetcher methods (STOCK_BOARD, DRAGON_TIGER, FUND_FLOW),
# the value here is the DEFAULT. Endpoints that need a different
# method override via `@endpoint_meta(fetcher_method="...")`.
CAPABILITY_TO_METHOD: dict[DataCapability, str] = {
    DataCapability.STOCK_KLINE: "get_kline_data",
    DataCapability.INDEX_KLINE: "get_index_historical",
    DataCapability.STOCK_REALTIME_QUOTE: "get_realtime_quote",
    DataCapability.INDEX_REALTIME_QUOTE: "get_index_realtime_quote",
    DataCapability.STOCK_LIST: "get_all_stocks",
    DataCapability.TRADE_CALENDAR: "get_trade_calendar",
    DataCapability.STOCK_BOARD: "get_all_boards",            # default; .stocks variant overrides
    DataCapability.STOCK_ZT_POOL: "get_zt_pool",
    DataCapability.DRAGON_TIGER: "get_dragon_tiger",         # default; /daily variant overrides
    DataCapability.MARGIN_TRADING: "get_margin_trading",
    DataCapability.BLOCK_TRADE: "get_block_trade",
    DataCapability.HOLDER_NUM: "get_holder_num_change",
    DataCapability.DIVIDEND: "get_dividend",
    DataCapability.FUND_FLOW: "get_fund_flow_minute",        # default; /daily variant overrides
    DataCapability.HOT_TOPICS: "get_hot_topics",
    DataCapability.NORTH_FLOW: "get_north_flow",
    DataCapability.RESEARCH_REPORT: "get_reports",
    DataCapability.ANNOUNCEMENT: "get_announcements",
    DataCapability.STOCK_INFO: "get_stock_info",
    DataCapability.NEWS_SEARCH: "search_news",
    DataCapability.NEWS_FLASH: "fetch_flash_news",
}


class DataFetchError(Exception):
    """Raised when data fetching fails."""

    pass


__all__ = [
    "BaseFetcher",
    "DataCapability",
    "DataFetchError",
    "STANDARD_COLUMNS",
    "CAPABILITY_TO_METHOD",
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

    def unavailable_reason(self) -> str | None:
        """Return a human-readable reason this fetcher is unavailable, or None.

        Default impl: if the fetcher reports available, no reason is needed;
        otherwise return a generic message naming this fetcher. Token-gated
        fetchers (Zhitu, Tushare, Myquant) override with a more specific
        message derived from their actual gating logic (env var / SDK state).
        The explorer's manifest calls this only when is_available() returns
        False, so the "always None" path is hit for fetchers that pass.
        """
        if self.is_available():
            return None
        return f"{self.name} unavailable (is_available() returned False)"

    def is_available(self) -> bool:
        """Default: the fetcher is unconditionally available.

        Concrete fetchers override this to check tokens (Tushare/Zhitu/Myquant)
        or SDK importability (Akshare/Baostock/Yfinance). The default `True`
        lets test fakes and "no-prereq" fetchers skip ceremony.
        """
        return True

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
            # Note: technical indicators (MA/MACD/KDJ/...) are no longer
            # computed here. The indicator layer above this is responsible —
            # see stock_data.data_provider.indicators and the `?indicators=`
            # query param on /stocks/{code}/history.

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
        df = df.dropna(subset=["open", "high", "low", "close", "volume"])
        dropped = before - len(df)
        if dropped > 0:
            logger.debug(f"[{self.name}] Dropped {dropped} rows with NaN in required OHLCV fields")

        df = df.sort_values("date", ascending=True).reset_index(drop=True)
        return df

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

    def supports_kline(
        self,
        period: str,
        adjust: str,
        market: str,
        asset: str,
    ) -> bool:
        """Return True iff this fetcher CAN serve (asset, period, market).

        Default behaviour (spec §4.2): True when (a) market is in
        ``supported_markets`` AND (b) the fetcher has STOCK_KLINE / INDEX_KLINE
        matching ``asset``. Subclasses narrow further to express upstream
        quirks (e.g. Yfinance hfq silently downgrades to qfq -> unsupported,
        Akshare refuses 1m + adjust). See task 3 for per-fetcher overrides.

        Note: the ``adjust`` argument is intentionally NOT checked in the
        default. Different fetchers have different supported adjust
        combinations for different (period, market, asset); subclasses
        encode those in ``supports_kline()`` overrides.
        """
        if market not in self.supported_markets:
            return False
        if asset == "stock" and DataCapability.STOCK_KLINE not in self.supported_data_types:
            return False
        if asset == "index" and DataCapability.INDEX_KLINE not in self.supported_data_types:
            return False
        return period in ("d", "w", "m", "1", "5", "15", "30", "60")

    def supports_quote(self, market: str) -> bool:
        """Return True iff this fetcher can serve realtime quote for ``market``.

        Default (spec §4.2.1): market in ``supported_markets`` AND fetcher
        has STOCK_REALTIME_QUOTE or INDEX_REALTIME_QUOTE. Subclasses override
        only for edge cases (Tencent's csi/hk limitation is in
        ``supported_markets``, so no override needed).
        """
        if market not in self.supported_markets:
            return False
        return (
            DataCapability.STOCK_REALTIME_QUOTE in self.supported_data_types
            or DataCapability.INDEX_REALTIME_QUOTE in self.supported_data_types
        )
