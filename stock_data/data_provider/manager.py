"""
Manager for multiple stock data fetchers with priority-based failover.
"""

import logging
from datetime import datetime, timedelta
from threading import RLock

import pandas as pd

from .base import BaseFetcher, DataCapability, DataFetchError
from .core.types import UnifiedRealtimeQuote, get_realtime_circuit_breaker
from .utils.normalize import index_market_tag, market_tag, normalize_stock_code

logger = logging.getLogger(__name__)


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
        with self._lock:
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

        # Determine capability based on frequency.
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
        else:
            market = market_tag(stock_code)
            fetchers = self._filter_by_capability(market, gen_cap)

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

    def get_zt_pool(
        self,
        pool_type: str,
        date: str | None = None,
        refresh: bool = False,
    ) -> list[dict]:
        """Get ZT (涨跌停) pool data with automatic failover and caching.

        Args:
            pool_type: Pool type - "zt" (涨停), "dt" (跌停), "zbgc" (炸板)
            date: Pool date in YYYY-MM-DD format. If None, uses latest cached or today.
            refresh: If True, force refresh from upstream and update cache.

        Returns:
            List of stock dicts with normalized fields.

        Raises:
            DataFetchError: When all fetchers fail and no cache available.
        """
        from .cache.stock_zt_pool_cache import (
            get_zt_pool_cached,
            save_zt_pool,
            get_latest_cached_date,
            has_cached_data,
        )

        # Determine the date to query
        query_date = date
        if not query_date:
            # Try latest cached date first
            latest = get_latest_cached_date(pool_type)
            if latest:
                query_date = latest
            else:
                # Use today as fallback
                from datetime import date as date_cls
                query_date = date_cls.today().strftime("%Y-%m-%d")

        # Check cache first (only if not refreshing)
        if not refresh:
            cached = get_zt_pool_cached(pool_type, query_date)
            if cached:
                logger.info(f"[Manager] ZT pool {pool_type} {query_date} found in cache ({len(cached)} stocks)")
                return cached

        # Fetch from upstream with capability-based routing
        fetchers = self._filter_by_capability("csi", DataCapability.STOCK_ZT_POOL)

        errors = []
        for fetcher in fetchers:
            try:
                # Akshare expects YYYYMMDD, Zhitu expects YYYY-MM-DD
                fetcher_date = query_date.replace("-", "") if fetcher.name == "AkshareFetcher" else query_date
                stocks = fetcher.get_zt_pool(pool_type, fetcher_date)
                if stocks:
                    # Save to cache
                    save_zt_pool(pool_type, query_date, stocks)
                    logger.info(f"[Manager] {fetcher.name} returned {len(stocks)} stocks for ZT pool {pool_type} {query_date}")
                    return stocks
            except Exception as e:
                errors.append(f"[{fetcher.name}] {e}")
                logger.warning(f"[Manager] {fetcher.name} ZT pool failed: {e}")
                continue

        # Fallback: return cached data if upstream fails and not already cached
        if not refresh:
            cached = get_zt_pool_cached(pool_type, query_date)
            if cached:
                logger.warning(f"[Manager] All fetchers failed for ZT pool, using {len(cached)} cached stocks")
                return cached

        raise DataFetchError(f"All fetchers failed for ZT pool {pool_type}:\n" + "\n".join(errors))

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
        fetchers = self._filter_by_capability(index_type, DataCapability.INDEX_QUOTE)

        for fetcher in fetchers:
            try:
                quote = fetcher.get_index_realtime_quote(index_code)
                if quote is not None:
                    logger.info(f"[Manager] {fetcher.name} succeeded for {index_code} index quote")
                    return quote
            except Exception as e:
                logger.warning(f"[Manager] {fetcher.name} index quote failed: {e}")
                continue

        return None

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
        from datetime import datetime, timedelta

        if not start_date:
            start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

        index_code = normalize_stock_code(index_code)
        index_type = index_market_tag(index_code) or "csi"
        fetchers = self._filter_by_capability(index_type, DataCapability.INDEX_HISTORICAL)

        errors = []
        for fetcher in fetchers:
            try:
                logger.info(f"[Manager] Trying {fetcher.name} for {index_code} index history")
                df = fetcher.get_index_historical(index_code, start_date, end_date, frequency)
                if df is not None and not df.empty:
                    logger.info(f"[Manager] {fetcher.name} succeeded for {index_code} index history")
                    return df, fetcher.name
            except Exception as e:
                errors.append(f"[{fetcher.name}] {e}")
                logger.warning(f"[Manager] {fetcher.name} index history failed: {e}")
                continue

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

        errors = []
        for fetcher in fetchers:
            try:
                logger.info(f"[Manager] Trying {fetcher.name} for {index_code} index intraday ({period})")
                df = fetcher.get_index_intraday(index_code, period)
                if df is not None and not df.empty:
                    logger.info(f"[Manager] {fetcher.name} succeeded for {index_code} index intraday")
                    return df, fetcher.name
            except Exception as e:
                errors.append(f"[{fetcher.name}] {e}")
                logger.warning(f"[Manager] {fetcher.name} index intraday failed: {e}")
                continue

        raise DataFetchError(
            f"All fetchers failed for {index_code} index intraday:\n" + "\n".join(errors)
        )

    def get_all_concept_boards(self, source: str = "eastmoney", include_quote: bool = False) -> list[dict]:
        """Get all concept boards from fetchers that support STOCK_BOARD capability.

        Args:
            source: Data source (e.g., "eastmoney")
            include_quote: If True, include realtime price/change/market data

        Returns:
            List of board dicts [{"code": "BK1048", "name": "互联网服务"}, ...]
            When include_quote=True, also includes: price, change_pct, change_amount,
            volume, amount, turnover_rate, total_mv, up_count, down_count,
            leading_stock, leading_stock_pct
        """
        fetchers = self._filter_by_capability("csi", DataCapability.STOCK_BOARD)
        errors = []
        for fetcher in fetchers:
            try:
                boards = fetcher.get_all_concept_boards(source=source, include_quote=include_quote)
                if boards:
                    logger.info(f"[Manager] {fetcher.name} returned {len(boards)} concept boards")
                    return boards
            except Exception as e:
                errors.append(f"[{fetcher.name}] {e}")
                logger.warning(f"[Manager] {fetcher.name} get_all_concept_boards failed: {e}")
                continue
        raise DataFetchError(f"All fetchers failed for concept boards:\n" + "\n".join(errors))

    def get_all_industry_boards(self, source: str = "eastmoney", include_quote: bool = False) -> list[dict]:
        """Get all industry boards from fetchers that support STOCK_BOARD capability.

        Args:
            source: Data source (e.g., "eastmoney")
            include_quote: If True, include realtime price/change/market data

        Returns:
            List of board dicts [{"code": "BK0418", "name": "银行"}, ...]
            When include_quote=True, also includes: price, change_pct, change_amount,
            volume, amount, turnover_rate, total_mv, up_count, down_count,
            leading_stock, leading_stock_pct
        """
        fetchers = self._filter_by_capability("csi", DataCapability.STOCK_BOARD)
        errors = []
        for fetcher in fetchers:
            try:
                boards = fetcher.get_all_industry_boards(source=source, include_quote=include_quote)
                if boards:
                    logger.info(f"[Manager] {fetcher.name} returned {len(boards)} industry boards")
                    return boards
            except Exception as e:
                errors.append(f"[{fetcher.name}] {e}")
                logger.warning(f"[Manager] {fetcher.name} get_all_industry_boards failed: {e}")
                continue
        raise DataFetchError(f"All fetchers failed for industry boards:\n" + "\n".join(errors))

    def get_concept_board_stocks(
        self, board_code: str, source: str = "eastmoney", include_quote: bool = False
    ) -> list[dict]:
        """Get stocks belonging to a concept board.

        Args:
            board_code: Board code (e.g., "BK1048")
            source: Data source (e.g., "eastmoney")
            include_quote: If True, include realtime price/change data

        Returns:
            List of stock dicts [{"stock_code": "600519", "stock_name": "贵州茅台"}, ...]
            When include_quote=True, also includes: price, change_pct, change_amount,
            volume, amount, turnover_rate, pe_ratio, pb_ratio, high, low, open, pre_close
        """
        fetchers = self._filter_by_capability("csi", DataCapability.STOCK_BOARD)
        errors = []
        for fetcher in fetchers:
            try:
                stocks = fetcher.get_concept_board_stocks(board_code, source=source, include_quote=include_quote)
                if stocks is not None:
                    logger.info(f"[Manager] {fetcher.name} returned {len(stocks)} stocks for concept board {board_code}")
                    return stocks
            except Exception as e:
                errors.append(f"[{fetcher.name}] {e}")
                logger.warning(f"[Manager] {fetcher.name} get_concept_board_stocks({board_code}) failed: {e}")
                continue
        raise DataFetchError(f"All fetchers failed for concept board stocks {board_code}:\n" + "\n".join(errors))

    def get_industry_board_stocks(
        self, board_code: str, source: str = "eastmoney", include_quote: bool = False
    ) -> list[dict]:
        """Get stocks belonging to an industry board.

        Args:
            board_code: Board code
            source: Data source (e.g., "eastmoney")
            include_quote: If True, include realtime price/change data

        Returns:
            List of stock dicts [{"stock_code": "600519", "stock_name": "贵州茅台"}, ...]
            When include_quote=True, also includes: price, change_pct, change_amount,
            volume, amount, turnover_rate, pe_ratio, pb_ratio, high, low, open, pre_close
        """
        fetchers = self._filter_by_capability("csi", DataCapability.STOCK_BOARD)
        errors = []
        for fetcher in fetchers:
            try:
                stocks = fetcher.get_industry_board_stocks(board_code, source=source, include_quote=include_quote)
                if stocks is not None:
                    logger.info(f"[Manager] {fetcher.name} returned {len(stocks)} stocks for industry board {board_code}")
                    return stocks
            except Exception as e:
                errors.append(f"[{fetcher.name}] {e}")
                logger.warning(f"[Manager] {fetcher.name} get_industry_board_stocks({board_code}) failed: {e}")
                continue
        raise DataFetchError(f"All fetchers failed for industry board stocks {board_code}:\n" + "\n".join(errors))

    def get_dragon_tiger(self, code: str, trade_date: str = "", look_back: int = 30) -> dict:
        """Get dragon tiger board data for a single stock."""
        fetchers = self._filter_by_capability("csi", DataCapability.DRAGON_TIGER)
        errors = []
        for fetcher in fetchers:
            try:
                result = fetcher.get_dragon_tiger(code, trade_date, look_back)
                if result is not None:
                    logger.info(f"[Manager] {fetcher.name} succeeded for {code} dragon_tiger")
                    return result
            except Exception as e:
                errors.append(f"[{fetcher.name}] {e}")
                logger.warning(f"[Manager] {fetcher.name} dragon_tiger failed: {e}")
                continue
        raise DataFetchError(f"All fetchers failed for dragon_tiger {code}:\n" + "\n".join(errors))

    def get_daily_dragon_tiger(self, trade_date: str = "", min_net_buy: float | None = None) -> dict:
        """Get daily market-wide dragon tiger board summary."""
        fetchers = self._filter_by_capability("csi", DataCapability.DRAGON_TIGER)
        errors = []
        for fetcher in fetchers:
            try:
                result = fetcher.get_daily_dragon_tiger(trade_date, min_net_buy)
                if result is not None:
                    logger.info(f"[Manager] {fetcher.name} succeeded for daily dragon_tiger")
                    return result
            except Exception as e:
                errors.append(f"[{fetcher.name}] {e}")
                logger.warning(f"[Manager] {fetcher.name} daily_dragon_tiger failed: {e}")
                continue
        raise DataFetchError(f"All fetchers failed for daily dragon_tiger:\n" + "\n".join(errors))

    def get_margin_trading(self, code: str, page_size: int = 30) -> list[dict]:
        """Get margin trading data."""
        fetchers = self._filter_by_capability("csi", DataCapability.MARGIN_TRADING)
        errors = []
        for fetcher in fetchers:
            try:
                result = fetcher.get_margin_trading(code, page_size)
                if result is not None:
                    logger.info(f"[Manager] {fetcher.name} succeeded for {code} margin_trading")
                    return result
            except Exception as e:
                errors.append(f"[{fetcher.name}] {e}")
                logger.warning(f"[Manager] {fetcher.name} margin_trading failed: {e}")
                continue
        raise DataFetchError(f"All fetchers failed for margin_trading {code}:\n" + "\n".join(errors))

    def get_block_trade(self, code: str, page_size: int = 20) -> list[dict]:
        """Get block trade records."""
        fetchers = self._filter_by_capability("csi", DataCapability.BLOCK_TRADE)
        errors = []
        for fetcher in fetchers:
            try:
                result = fetcher.get_block_trade(code, page_size)
                if result is not None:
                    logger.info(f"[Manager] {fetcher.name} succeeded for {code} block_trade")
                    return result
            except Exception as e:
                errors.append(f"[{fetcher.name}] {e}")
                logger.warning(f"[Manager] {fetcher.name} block_trade failed: {e}")
                continue
        raise DataFetchError(f"All fetchers failed for block_trade {code}:\n" + "\n".join(errors))

    def get_holder_num_change(self, code: str, page_size: int = 10) -> list[dict]:
        """Get shareholder count change."""
        fetchers = self._filter_by_capability("csi", DataCapability.HOLDER_NUM)
        errors = []
        for fetcher in fetchers:
            try:
                result = fetcher.get_holder_num_change(code, page_size)
                if result is not None:
                    logger.info(f"[Manager] {fetcher.name} succeeded for {code} holder_num")
                    return result
            except Exception as e:
                errors.append(f"[{fetcher.name}] {e}")
                logger.warning(f"[Manager] {fetcher.name} holder_num failed: {e}")
                continue
        raise DataFetchError(f"All fetchers failed for holder_num {code}:\n" + "\n".join(errors))

    def get_dividend(self, code: str, page_size: int = 20) -> list[dict]:
        """Get dividend history."""
        fetchers = self._filter_by_capability("csi", DataCapability.DIVIDEND)
        errors = []
        for fetcher in fetchers:
            try:
                result = fetcher.get_dividend(code, page_size)
                if result is not None:
                    logger.info(f"[Manager] {fetcher.name} succeeded for {code} dividend")
                    return result
            except Exception as e:
                errors.append(f"[{fetcher.name}] {e}")
                logger.warning(f"[Manager] {fetcher.name} dividend failed: {e}")
                continue
        raise DataFetchError(f"All fetchers failed for dividend {code}:\n" + "\n".join(errors))

    def get_fund_flow_minute(self, code: str) -> list[dict]:
        """Get minute-level fund flow."""
        fetchers = self._filter_by_capability("csi", DataCapability.FUND_FLOW)
        errors = []
        for fetcher in fetchers:
            try:
                result = fetcher.get_fund_flow_minute(code)
                if result is not None:
                    logger.info(f"[Manager] {fetcher.name} succeeded for {code} fund_flow_minute")
                    return result
            except Exception as e:
                errors.append(f"[{fetcher.name}] {e}")
                logger.warning(f"[Manager] {fetcher.name} fund_flow_minute failed: {e}")
                continue
        raise DataFetchError(f"All fetchers failed for fund_flow_minute {code}:\n" + "\n".join(errors))

    def get_fund_flow_120d(self, code: str) -> list[dict]:
        """Get 120-day fund flow history."""
        fetchers = self._filter_by_capability("csi", DataCapability.FUND_FLOW)
        errors = []
        for fetcher in fetchers:
            try:
                result = fetcher.get_fund_flow_120d(code)
                if result is not None:
                    logger.info(f"[Manager] {fetcher.name} succeeded for {code} fund_flow_120d")
                    return result
            except Exception as e:
                errors.append(f"[{fetcher.name}] {e}")
                logger.warning(f"[Manager] {fetcher.name} fund_flow_120d failed: {e}")
                continue
        raise DataFetchError(f"All fetchers failed for fund_flow_120d {code}:\n" + "\n".join(errors))

    def get_hot_topics(self, date_str: str = "") -> list[dict]:
        """Get hot topics."""
        fetchers = self._filter_by_capability("csi", DataCapability.HOT_TOPICS)
        errors = []
        for fetcher in fetchers:
            try:
                result = fetcher.get_hot_topics(date_str)
                if result is not None:
                    logger.info(f"[Manager] {fetcher.name} succeeded for hot_topics")
                    return result
            except Exception as e:
                errors.append(f"[{fetcher.name}] {e}")
                logger.warning(f"[Manager] {fetcher.name} hot_topics failed: {e}")
                continue
        raise DataFetchError(f"All fetchers failed for hot_topics:\n" + "\n".join(errors))

    def get_north_flow(self) -> list[dict]:
        """Get north-bound capital flow."""
        fetchers = self._filter_by_capability("csi", DataCapability.NORTH_FLOW)
        errors = []
        for fetcher in fetchers:
            try:
                result = fetcher.get_north_flow()
                if result is not None:
                    logger.info(f"[Manager] {fetcher.name} succeeded for north_flow")
                    return result
            except Exception as e:
                errors.append(f"[{fetcher.name}] {e}")
                logger.warning(f"[Manager] {fetcher.name} north_flow failed: {e}")
                continue
        raise DataFetchError(f"All fetchers failed for north_flow:\n" + "\n".join(errors))

    def get_reports(self, code: str, max_pages: int = 5) -> list[dict]:
        """Get research reports."""
        fetchers = self._filter_by_capability("csi", DataCapability.RESEARCH_REPORT)
        errors = []
        for fetcher in fetchers:
            try:
                result = fetcher.get_reports(code, max_pages)
                if result is not None:
                    logger.info(f"[Manager] {fetcher.name} succeeded for {code} reports")
                    return result
            except Exception as e:
                errors.append(f"[{fetcher.name}] {e}")
                logger.warning(f"[Manager] {fetcher.name} reports failed: {e}")
                continue
        raise DataFetchError(f"All fetchers failed for reports {code}:\n" + "\n".join(errors))

    def get_announcements(self, code: str, page_size: int = 30) -> list[dict]:
        """Get corporate announcements."""
        fetchers = self._filter_by_capability("csi", DataCapability.ANNOUNCEMENT)
        errors = []
        for fetcher in fetchers:
            try:
                result = fetcher.get_announcements(code, page_size)
                if result is not None:
                    logger.info(f"[Manager] {fetcher.name} succeeded for {code} announcements")
                    return result
            except Exception as e:
                errors.append(f"[{fetcher.name}] {e}")
                logger.warning(f"[Manager] {fetcher.name} announcements failed: {e}")
                continue
        raise DataFetchError(f"All fetchers failed for announcements {code}:\n" + "\n".join(errors))

    def get_report_pdf(self, report_id: str) -> tuple[str, str]:
        """Resolve a research report PDF via capability-based routing.

        Returns ``(download_path, url)``. Routes through every fetcher that
        declares ``RESEARCH_REPORT`` capability, calling ``download_report_pdf``
        on each until one returns a non-None path. The URL is recovered from
        the same fetcher.

        Raises:
            DataFetchError: when no fetcher can serve the PDF.
        """
        fetchers = self._filter_by_capability("csi", DataCapability.RESEARCH_REPORT)
        errors = []
        for fetcher in fetchers:
            try:
                path = fetcher.download_report_pdf(report_id)
                if path is not None:
                    url = fetcher.get_report_pdf_url(report_id) or ""
                    logger.info(
                        f"[Manager] {fetcher.name} served report PDF {report_id} -> {path}"
                    )
                    return path, url
            except Exception as e:
                errors.append(f"[{fetcher.name}] {e}")
                logger.warning(f"[Manager] {fetcher.name} report_pdf({report_id}) failed: {e}")
                continue
        raise DataFetchError(
            f"All fetchers failed for report_pdf {report_id}:\n" + "\n".join(errors) or "(none)"
        )

    @property
    def available_fetchers(self) -> list[str]:
        """List available fetcher names."""
        return [f.name for f in self._fetchers]

    @property
    def fetchers(self) -> list["BaseFetcher"]:  # type: ignore[misc]
        """List all fetchers. Prefer get_fetcher() for single fetcher lookup."""
        return list(self._fetchers)
