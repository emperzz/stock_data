"""
Manager for multiple stock data fetchers with priority-based failover.
"""

import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from threading import RLock
from typing import Any, TypeVar

import pandas as pd

from .base import BaseFetcher, DataCapability, DataFetchError
from .core.types import UnifiedRealtimeQuote, get_realtime_circuit_breaker
from .utils.normalize import index_market_tag, market_tag, normalize_stock_code

logger = logging.getLogger(__name__)

T = TypeVar("T")


def _is_meaningful(result: Any) -> bool:
    """Treat None and empty DataFrames as 'no data' (skip fetcher)."""
    if result is None:
        return False
    return not (isinstance(result, pd.DataFrame) and result.empty)


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

    # ---------- registration / lookup ----------

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
        with self._lock:
            for f in self._fetchers:
                if market not in f.supported_markets:
                    continue
                if capability not in f.supported_data_types:
                    continue
                result.append(f)
        return result

    # ---------- the single failover helper ----------
    #
    # Every public `get_*` below is a thin wrapper around `_with_failover`,
    # which encapsulates: filter-by-capability, iterate in priority order,
    # call the fetcher, treat None / empty DataFrame as "no data", log
    # success/failure, aggregate errors, and raise DataFetchError when all
    # fetchers fail (or return None if `allow_none=True`).
    #
    # Methods that need extra pre-/post- processing (persistence, circuit
    # breaker, fallback to cache) keep that logic in the wrapper and only
    # delegate the basic loop to this helper.

    def _with_failover(
        self,
        capability: DataCapability,
        market: str,
        op_label: str,
        call: Callable[[BaseFetcher], T],
        *,
        allow_none: bool = False,
        error_prefix: str | None = None,
    ) -> T:
        """Run `call(fetcher)` over every fetcher with the given capability, in priority order.

        Args:
            capability: required DataCapability flag for routing
            market: market tag (csi/hk/us)
            op_label: short label for log messages (e.g. "kline 600519")
            call: fetcher-bound function; its return value is treated as
                "found" if it's not None and not an empty DataFrame
            allow_none: if True, return None on total failure instead of raising
            error_prefix: override for the DataFetchError prefix (default:
                f"All fetchers failed for {op_label}:")

        Returns:
            The first non-None/non-empty result, with `fetcher.name` already
            included via the call site (the helper does not return the source).

        Raises:
            DataFetchError: when all fetchers fail and `allow_none` is False.
        """
        fetchers = self._filter_by_capability(market, capability)
        errors: list[str] = []
        for fetcher in fetchers:
            try:
                result = call(fetcher)
            except Exception as e:
                errors.append(f"[{fetcher.name}] {e}")
                logger.warning(f"[Manager] {fetcher.name} {op_label} failed: {e}")
                continue
            if _is_meaningful(result):
                logger.info(f"[Manager] {fetcher.name} succeeded for {op_label}")
                return result

        if allow_none:
            return None  # type: ignore[return-value]
        prefix = error_prefix or f"All fetchers failed for {op_label}:"
        raise DataFetchError(prefix + "\n" + "\n".join(errors))

    # ---------- K-line & intraday (stocks) ----------

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
        index_tag = index_market_tag(stock_code)

        # Index codes prefer INDEX_HISTORICAL/INDEX_INTRADAY so fetchers can
        # declare index support independently of stock K-line support, then
        # fall back to HISTORICAL_DWM/HISTORICAL_MIN for backward compat.
        if frequency in ("5", "15", "30", "60"):
            index_cap = DataCapability.INDEX_INTRADAY
            gen_cap = DataCapability.HISTORICAL_MIN
        else:
            index_cap = DataCapability.INDEX_HISTORICAL
            gen_cap = DataCapability.HISTORICAL_DWM

        if index_tag:
            fetchers = self._filter_by_capability(index_tag, index_cap)
            if not fetchers:
                fetchers = self._filter_by_capability(index_tag, gen_cap)
            market = index_tag
        else:
            market = market_tag(stock_code)
            fetchers = self._filter_by_capability(market, gen_cap)

        # Custom loop because the helper returns only the data, not the source.
        errors: list[str] = []
        for fetcher in fetchers:
            try:
                df = fetcher.get_kline_data(
                    stock_code, start_date, end_date, days, frequency, adjust
                )
            except Exception as e:
                errors.append(f"[{fetcher.name}] {e}")
                logger.warning(f"[Manager] {fetcher.name} failed: {e}")
                continue
            if _is_meaningful(df):
                logger.info(f"[Manager] {fetcher.name} succeeded for {stock_code} ({frequency})")
                return df, fetcher.name

        raise DataFetchError(f"All fetchers failed for {stock_code}:\n" + "\n".join(errors))

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

        errors: list[str] = []
        for fetcher in fetchers:
            try:
                df = fetcher.get_intraday_data(stock_code, period, adjust)
            except Exception as e:
                errors.append(f"[{fetcher.name}] {e}")
                logger.warning(f"[Manager] {fetcher.name} intraday failed: {e}")
                continue
            if _is_meaningful(df):
                logger.info(
                    f"[Manager] {fetcher.name} succeeded for {stock_code} intraday"
                )
                return df, fetcher.name

        raise DataFetchError(
            f"All fetchers failed for {stock_code} intraday:\n" + "\n".join(errors)
        )

    # ---------- realtime quotes (with circuit breaker) ----------

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
            except Exception as e:
                cb.record_failure(fetcher.name)
                logger.warning(f"[Manager] {fetcher.name} realtime quote failed: {e}")
                continue
            if quote is not None:
                cb.record_success(fetcher.name)
                return quote
            cb.record_failure(fetcher.name)

        return None

    # ---------- trade calendar (with persistence) ----------

    def get_trade_calendar(self) -> list[str]:
        """Get A-share trade calendar with automatic failover.

        Tries each fetcher's get_trade_calendar() in priority order.
        Akshare is primary; Baostock is fallback. On success, the result
        is persisted; on total upstream failure, the cached value is
        returned (or DataFetchError if no cache either).

        Returns:
            List of trade dates as YYYY-MM-DD strings, sorted ascending.

        Raises:
            DataFetchError: When all fetchers fail and no cache available.
        """
        from .persistence.trade_calendar import get_cached_calendar, update_cached_calendar

        def _fetch_and_persist(fetcher: BaseFetcher) -> list[str] | None:
            dates = fetcher.get_trade_calendar()
            if dates:
                update_cached_calendar(dates)
                return sorted(dates)
            return None

        try:
            return self._with_failover(
                DataCapability.TRADE_CALENDAR,
                "csi",
                "trade calendar",
                _fetch_and_persist,
            )
        except DataFetchError:
            # Fallback: return cached data if upstream fails
            cached = get_cached_calendar()
            if cached:
                logger.warning(
                    f"[Manager] All fetchers failed calendar, using {len(cached)} cached dates"
                )
                return cached
            raise

    # ---------- ZT/DT/ZBGC pool (with persistence) ----------

    def get_zt_pool(
        self,
        pool_type: str,
        date: str | None = None,
        refresh: bool = False,
        is_current_day: bool = False,
    ) -> list[dict]:
        """Get ZT (涨跌停) pool data with date-keyed persistence.

        Args:
            pool_type: "zt" (涨停) | "dt" (跌停) | "zbgc" (炸板)
            date: Pool date in YYYY-MM-DD. If None, falls back to the latest
                persisted date for this pool_type, or today.
            refresh: Force upstream fetch (bypass cache read; the persistence
                write policy is still determined by ``is_current_day``).
            is_current_day: True iff the query is for the "current trading day"
                (today AND today is a trade date). When True:
                - NEVER reads from persistence (当日不该有 cache,即便有也不该用——
                  可能是历史策略切换前残留的中间态)
                - NEVER writes to persistence (避免固化未收盘的状态)
                - 上游失败 → 抛 DataFetchError(不回退 cache)

        Returns:
            List of stock dicts with normalized fields.

        Raises:
            DataFetchError: When all fetchers fail and no cache available
                (or, for the current trading day, the upstream failed and
                there is no cache to fall back to by design).
        """
        from .persistence.pool_daily import (
            get_latest_cached_date,
            get_pool_cached,
            save_pool,
        )

        # Determine the date to query
        query_date = date
        if not query_date:
            latest = get_latest_cached_date(pool_type)
            if latest:
                query_date = latest
            else:
                from datetime import date as date_cls
                query_date = date_cls.today().strftime("%Y-%m-%d")

        # Non-current-day + not refreshing: check persistence first
        if not is_current_day and not refresh:
            cached = get_pool_cached(pool_type, query_date)
            if cached:
                logger.info(
                    f"[Manager] ZT pool {pool_type} {query_date} found in persistence "
                    f"({len(cached)} stocks)"
                )
                return cached

        def _fetch(fetcher: BaseFetcher) -> list[dict] | None:
            # All fetchers must accept YYYY-MM-DD and convert internally if needed
            stocks = fetcher.get_zt_pool(pool_type, query_date)
            if stocks and not is_current_day:
                save_pool(pool_type, query_date, stocks)
            return stocks or None

        try:
            return self._with_failover(
                DataCapability.STOCK_ZT_POOL,
                "csi",
                f"ZT pool {pool_type} {query_date}",
                _fetch,
            )
        except DataFetchError:
            # Fallback: return persisted data if upstream fails (only for non-current-day)
            if not is_current_day and not refresh:
                cached = get_pool_cached(pool_type, query_date)
                if cached:
                    logger.warning(
                        f"[Manager] All fetchers failed for ZT pool {pool_type} {query_date}, "
                        f"using {len(cached)} persisted stocks"
                    )
                    return cached
            raise

    # ---------- index methods ----------

    def get_index_realtime_quote(self, index_code: str) -> UnifiedRealtimeQuote | None:
        """Get realtime quote for an index with capability-based failover.

        Routes through fetchers declaring INDEX_QUOTE capability.
        Each fetcher must implement get_index_realtime_quote().

        Args:
            index_code: Index code (e.g., 000300, 399006, SPX, HSI)

        Returns:
            UnifiedRealtimeQuote or None if not available.
        """
        index_code = normalize_stock_code(index_code)
        index_type = index_market_tag(index_code) or "csi"
        return self._with_failover(
            DataCapability.INDEX_QUOTE,
            index_type,
            f"{index_code} index quote",
            lambda f: f.get_index_realtime_quote(index_code),
            allow_none=True,
        )

    def get_index_historical(
        self,
        index_code: str,
        start_date: str | None = None,
        end_date: str | None = None,
        days: int = 30,
        frequency: str = "d",
    ) -> tuple[pd.DataFrame, str]:
        """Get historical K-line data for an index with capability-based failover.

        Routes through fetchers declaring INDEX_HISTORICAL capability.
        Each fetcher must implement get_index_historical().

        Args:
            index_code: Index code (e.g., 000300, 399006, SPX, HSI)
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            days: Number of days when start_date not provided
            frequency: K-line period - 'd'=daily, 'w'=weekly, 'm'=monthly

        Returns:
            Tuple of (DataFrame, source_name)
        """
        if not start_date:
            start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        index_code = normalize_stock_code(index_code)
        index_type = index_market_tag(index_code) or "csi"
        fetchers = self._filter_by_capability(index_type, DataCapability.INDEX_HISTORICAL)

        errors: list[str] = []
        for fetcher in fetchers:
            try:
                df = fetcher.get_index_historical(index_code, start_date, end_date, frequency)
            except Exception as e:
                errors.append(f"[{fetcher.name}] {e}")
                logger.warning(f"[Manager] {fetcher.name} index history failed: {e}")
                continue
            if _is_meaningful(df):
                logger.info(f"[Manager] {fetcher.name} succeeded for {index_code} index history")
                return df, fetcher.name

        raise DataFetchError(
            f"All fetchers failed for {index_code} index history:\n" + "\n".join(errors)
        )

    def get_index_intraday(
        self, index_code: str, period: str = "5"
    ) -> tuple[pd.DataFrame, str]:
        """Get intraday minute-level data for an index with capability-based failover.

        Routes through fetchers declaring INDEX_INTRADAY capability.
        Each fetcher must implement get_index_intraday().

        Args:
            index_code: Index code (e.g., 000300, 399006)
            period: Minute period - "1", "5", "15", "30", "60"

        Returns:
            Tuple of (DataFrame, source_name)
        """
        index_code = normalize_stock_code(index_code)
        index_type = index_market_tag(index_code) or "csi"
        fetchers = self._filter_by_capability(index_type, DataCapability.INDEX_INTRADAY)

        errors: list[str] = []
        for fetcher in fetchers:
            try:
                df = fetcher.get_index_intraday(index_code, period)
            except Exception as e:
                errors.append(f"[{fetcher.name}] {e}")
                logger.warning(f"[Manager] {fetcher.name} index intraday failed: {e}")
                continue
            if _is_meaningful(df):
                logger.info(f"[Manager] {fetcher.name} succeeded for {index_code} index intraday")
                return df, fetcher.name

        raise DataFetchError(
            f"All fetchers failed for {index_code} index intraday:\n" + "\n".join(errors)
        )

    # ---------- boards (concept / industry) ----------

    def get_all_concept_boards(self, source: str = "eastmoney", include_quote: bool = False) -> list[dict]:
        """Get all concept boards. See _with_failover docstring for behavior."""
        return self._with_failover(
            DataCapability.STOCK_BOARD,
            "csi",
            "concept boards",
            lambda f: f.get_all_concept_boards(source=source, include_quote=include_quote),
        )

    def get_all_industry_boards(self, source: str = "eastmoney", include_quote: bool = False) -> list[dict]:
        """Get all industry boards. See _with_failover docstring for behavior."""
        return self._with_failover(
            DataCapability.STOCK_BOARD,
            "csi",
            "industry boards",
            lambda f: f.get_all_industry_boards(source=source, include_quote=include_quote),
        )

    def get_concept_board_stocks(
        self, board_code: str, source: str = "eastmoney", include_quote: bool = False
    ) -> list[dict]:
        """Get stocks belonging to a concept board."""
        return self._with_failover(
            DataCapability.STOCK_BOARD,
            "csi",
            f"concept board stocks {board_code}",
            lambda f: f.get_concept_board_stocks(board_code, source=source, include_quote=include_quote),
        )

    def get_industry_board_stocks(
        self, board_code: str, source: str = "eastmoney", include_quote: bool = False
    ) -> list[dict]:
        """Get stocks belonging to an industry board."""
        return self._with_failover(
            DataCapability.STOCK_BOARD,
            "csi",
            f"industry board stocks {board_code}",
            lambda f: f.get_industry_board_stocks(board_code, source=source, include_quote=include_quote),
        )

    # ---------- eastmoney datacenter endpoints ----------

    def get_dragon_tiger(self, code: str, trade_date: str = "", look_back: int = 30) -> dict:
        return self._with_failover(
            DataCapability.DRAGON_TIGER, "csi", f"dragon_tiger {code}",
            lambda f: f.get_dragon_tiger(code, trade_date, look_back),
        )

    def get_daily_dragon_tiger(self, trade_date: str = "", min_net_buy: float | None = None) -> dict:
        return self._with_failover(
            DataCapability.DRAGON_TIGER, "csi", "daily dragon_tiger",
            lambda f: f.get_daily_dragon_tiger(trade_date, min_net_buy),
        )

    def get_margin_trading(self, code: str, page_size: int = 30) -> list[dict]:
        return self._with_failover(
            DataCapability.MARGIN_TRADING, "csi", f"margin_trading {code}",
            lambda f: f.get_margin_trading(code, page_size),
        )

    def get_block_trade(self, code: str, page_size: int = 20) -> list[dict]:
        return self._with_failover(
            DataCapability.BLOCK_TRADE, "csi", f"block_trade {code}",
            lambda f: f.get_block_trade(code, page_size),
        )

    def get_holder_num_change(self, code: str, page_size: int = 10) -> list[dict]:
        return self._with_failover(
            DataCapability.HOLDER_NUM, "csi", f"holder_num {code}",
            lambda f: f.get_holder_num_change(code, page_size),
        )

    def get_dividend(self, code: str, page_size: int = 20) -> list[dict]:
        return self._with_failover(
            DataCapability.DIVIDEND, "csi", f"dividend {code}",
            lambda f: f.get_dividend(code, page_size),
        )

    def get_fund_flow_minute(self, code: str) -> list[dict]:
        return self._with_failover(
            DataCapability.FUND_FLOW, "csi", f"fund_flow_minute {code}",
            lambda f: f.get_fund_flow_minute(code),
        )

    def get_fund_flow_120d(self, code: str) -> list[dict]:
        return self._with_failover(
            DataCapability.FUND_FLOW, "csi", f"fund_flow_120d {code}",
            lambda f: f.get_fund_flow_120d(code),
        )

    # ---------- ths / research / announcement ----------

    def get_hot_topics(self, date_str: str = "") -> list[dict]:
        return self._with_failover(
            DataCapability.HOT_TOPICS, "csi", "hot_topics",
            lambda f: f.get_hot_topics(date_str),
        )

    def get_north_flow(self) -> list[dict]:
        return self._with_failover(
            DataCapability.NORTH_FLOW, "csi", "north_flow",
            lambda f: f.get_north_flow(),
        )

    def get_reports(self, code: str, max_pages: int = 5) -> list[dict]:
        return self._with_failover(
            DataCapability.RESEARCH_REPORT, "csi", f"reports {code}",
            lambda f: f.get_reports(code, max_pages),
        )

    def get_announcements(self, code: str, page_size: int = 30) -> list[dict]:
        return self._with_failover(
            DataCapability.ANNOUNCEMENT, "csi", f"announcements {code}",
            lambda f: f.get_announcements(code, page_size),
        )

    def get_report_pdf(self, report_id: str) -> tuple[str, str]:
        """Resolve a research report PDF.

        Returns ``(download_path, url)``. Routes through every fetcher that
        declares ``RESEARCH_REPORT`` capability, calling ``download_report_pdf``
        on each until one returns a non-None path.

        Raises:
            DataFetchError: when no fetcher can serve the PDF.
        """
        fetchers = self._filter_by_capability("csi", DataCapability.RESEARCH_REPORT)
        errors: list[str] = []
        for fetcher in fetchers:
            try:
                path = fetcher.download_report_pdf(report_id)
            except Exception as e:
                errors.append(f"[{fetcher.name}] {e}")
                logger.warning(f"[Manager] {fetcher.name} report_pdf({report_id}) failed: {e}")
                continue
            if path is not None:
                url = fetcher.get_report_pdf_url(report_id) or ""
                logger.info(
                    f"[Manager] {fetcher.name} served report PDF {report_id} -> {path}"
                )
                return path, url
        raise DataFetchError(
            f"All fetchers failed for report_pdf {report_id}:\n" + "\n".join(errors) or "(none)"
        )

    # ---------- introspection ----------

    @property
    def available_fetchers(self) -> list[str]:
        """List available fetcher names."""
        return [f.name for f in self._fetchers]

    @property
    def fetchers(self) -> list["BaseFetcher"]:  # type: ignore[misc]
        """List all fetchers. Prefer get_fetcher() for single fetcher lookup."""
        return list(self._fetchers)
