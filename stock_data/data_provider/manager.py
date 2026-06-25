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
from .core.types import REALTIME_CIRCUIT_BREAKER, CircuitBreaker, UnifiedRealtimeQuote
from .utils.normalize import index_market_tag, market_tag, normalize_stock_code

logger = logging.getLogger(__name__)

T = TypeVar("T")


def _is_meaningful(result: Any) -> bool:
    """Treat None, empty DataFrames, and empty lists as 'no data' (skip fetcher)."""
    if result is None:
        return False
    if isinstance(result, pd.DataFrame) and result.empty:
        return False
    if isinstance(result, list) and len(result) == 0:
        return False
    return True


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
        # Slug → fetcher 路由索引。Slug 从 fetcher.name 派生（去掉 "Fetcher" 后缀，转小写）。
        # 例如 "ZhituFetcher" → "zhitu", "EastMoneyFetcher" → "eastmoney"。
        # 用于 _with_source() 的 source 参数（API 层传 slug 形式）。
        self._slug_index: dict[str, BaseFetcher] = {}
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
            self._slug_index.clear()

    def _refresh_index(self) -> None:
        """Refresh name and slug indices from ``_fetchers``.

        Both indices are derived state and must be rebuilt together whenever
        ``_fetchers`` changes. Without the slug rebuild, source-routed
        lookups (e.g. ``_with_source(source='zzshare')``) fail after
        ``add_fetcher()`` even though ``add_fetcher`` is the production
        registration path used by ``create_default_manager()``.
        """
        self._fetchers_by_name = {f.name: f for f in self._fetchers}
        self._slug_index = {
            slug: f
            for f in self._fetchers
            for slug in [self._derive_slug(f.name)]
            if slug
        }

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

    @staticmethod
    def _derive_slug(fetcher_name: str) -> str:
        """Derive source slug from fetcher class name.

        Strips trailing "Fetcher" (case-insensitive) and lowercases.
        Examples:
            "ZhituFetcher" → "zhitu"
            "EastMoneyFetcher" → "eastmoney"
            "Zhitu" → "zhitu"  # already bare
            "MyquantFetcher" → "myquant"
        """
        if not fetcher_name:
            return ""
        # Strip "Fetcher" suffix (case-insensitive)
        name = fetcher_name
        if name.lower().endswith("fetcher"):
            name = name[:-7]
        return name.lower()

    def _with_source(
        self,
        source: str,
        capability: DataCapability,
        market: str,
        op_label: str,
        call: Callable[[BaseFetcher], T],
    ) -> T:
        """Run ``call(fetcher)`` on the single fetcher whose name matches ``source``.

        Unlike ``_with_failover``, this primitive does NOT iterate over a
        capability-filtered list. It picks exactly one fetcher by name and
        invokes ``call`` on it. This is required for endpoints where the
        caller must be able to address a specific backend — e.g. board
        endpoints, where different fetchers use incompatible sector
        classification systems and board-code schemes, so transparent
        failover would be misleading.

        Args:
            source: Fetcher name to route to. Accepts either the slug
                form (e.g. ``"zhitu"``, case-insensitive) or the full
                fetcher class name (e.g. ``"ZhituFetcher"``). Slug
                match is preferred; full-name match is the fallback.
            capability: DataCapability the chosen fetcher must declare.
            market: Market tag the chosen fetcher must support.
            op_label: Short label for the log message.
            call: Fetcher-bound function whose return value is forwarded
                to the caller as-is.

        Returns:
            Whatever ``call(fetcher)`` returns.

        Raises:
            ValueError: when no fetcher matches the requested source,
                or the matching fetcher does not declare ``capability`` /
                does not support ``market``. The exception message names
                the cause and the missing flag.
            Exception: any exception raised inside ``call`` propagates
                unchanged — no failover is attempted.
        """
        # 1. Slug match (preferred — API layer uses slug form)
        # 2. Fallback to full name match (case-insensitive)
        target: BaseFetcher | None = None
        with self._lock:
            target = self._slug_index.get(source.lower())
            if target is None:
                for f in self._fetchers:
                    if f.name.lower() == source.lower():
                        target = f
                        break
        if target is None:
            raise ValueError(
                f"No fetcher with name {source!r} is registered"
            )
        if market not in target.supported_markets:
            raise ValueError(
                f"Fetcher {target.name!r} does not support market {market!r} "
                f"(supported: {sorted(target.supported_markets)})"
            )
        if capability not in target.supported_data_types:
            raise ValueError(
                f"Fetcher {target.name!r} does not declare capability {capability!r} "
                f"required for {op_label}"
            )
        logger.info(f"[Manager] {target.name} {op_label} via explicit source routing")
        return call(target)

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
        return_source: bool = False,
        circuit_breaker: CircuitBreaker | None = None,
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
            return_source: if True, return ``(result, fetcher_name)`` tuple
                instead of plain ``result``
            circuit_breaker: optional CircuitBreaker to integrate per-fetcher
                availability checks and success/failure recording

        Returns:
            The first non-None/non-empty result (or ``(result, source_name)``
            when ``return_source=True``).

        Raises:
            DataFetchError: when all fetchers fail and ``allow_none`` is False.
        """
        fetchers = self._filter_by_capability(market, capability)
        errors: list[str] = []
        for fetcher in fetchers:
            # Circuit breaker: skip fetchers in OPEN state
            if circuit_breaker is not None and not circuit_breaker.is_available(fetcher.name):
                logger.debug(f"[Manager] {fetcher.name} circuit open, skipping")
                continue
            try:
                result = call(fetcher)
            except Exception as e:
                if circuit_breaker is not None:
                    circuit_breaker.record_failure(fetcher.name)
                errors.append(f"[{fetcher.name}] {e}")
                logger.warning(f"[Manager] {fetcher.name} {op_label} failed: {e}")
                continue
            if _is_meaningful(result):
                logger.info(f"[Manager] {fetcher.name} succeeded for {op_label}")
                if circuit_breaker is not None:
                    circuit_breaker.record_success(fetcher.name)
                return (result, fetcher.name) if return_source else result  # type: ignore[return-value]
            # Result is None/empty — treat as soft failure for circuit breaker
            if circuit_breaker is not None:
                circuit_breaker.record_failure(fetcher.name)

        if allow_none:
            return (None, "") if return_source else None  # type: ignore[return-value]
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
            market = index_tag
            capability = index_cap
            if not self._filter_by_capability(market, index_cap):
                capability = gen_cap
        else:
            market = market_tag(stock_code)
            capability = gen_cap

        def _fetch(fetcher: BaseFetcher) -> pd.DataFrame:
            return fetcher.get_kline_data(
                stock_code, start_date, end_date, days, frequency, adjust
            )

        return self._with_failover(
            capability, market, f"kline {frequency} {stock_code}",
            _fetch, return_source=True,
        )

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
        return self._with_failover(
            DataCapability.HISTORICAL_MIN, market, f"intraday {stock_code}",
            lambda f: f.get_intraday_data(stock_code, period, adjust),
            return_source=True,
        )

    # ---------- stock list ----------

    def get_all_stocks(self, market: str) -> tuple[list[dict], str]:
        """Get the full stock list for *market* via STOCK_LIST-capable fetchers.

        Args:
            market: Public market tag (csi/hk/us). The manager uses this
                for capability-based routing (fetcher ``supported_markets``).
                The public tag is translated to the fetcher's internal
                tag (``csi`` -> ``cn``) at the call boundary so the rest
                of the persistence layer can keep using the public
                ``csi`` tag consistently (DB key, response, logs).

        Returns:
            Tuple of ``(stocks, fetcher_name)``. ``fetcher_name`` is the
            name of the first STOCK_LIST-capable fetcher that returned
            a non-empty list (e.g. ``"akshare"``); ``""`` when no
            fetcher produced data.

        Raises:
            DataFetchError: When all fetchers raise (none returned
                data AND all raised). An empty result from every
                fetcher is returned as ``([], "")`` rather than
                raising — distinguishing "the upstream truly has no
                list for this market" from "the upstream is broken".
        """
        # ``_is_meaningful`` short-circuits on empty DataFrame but not
        # on empty list. Wrap the call to (a) translate ``[]`` -> ``None``
        # for the meaningfulness check (so the failover loop keeps
        # trying fetchers when one returns an empty list), and (b) apply
        # the public->fetcher market-tag conversion so the fetcher's
        # internal branch (e.g. ``if market == "cn":``) still matches.
        public_to_fetcher = {"csi": "cn"}
        fetcher_market = public_to_fetcher.get(market, market)

        def _call(fetcher: BaseFetcher):
            return fetcher.get_all_stocks(fetcher_market)

        return self._with_failover(
            DataCapability.STOCK_LIST, market, f"all_stocks {market}",
            _call,
            return_source=True,
            allow_none=True,
        )

    # ---------- news search ----------

    def search_news(
        self,
        q: str,
        from_date: str | None = None,
        to_date: str | None = None,
        limit: int = 20,
    ) -> tuple[list[dict], str]:
        """News search via NEWS_SEARCH-capable fetchers (priority-based failover).

        Returns:
            Tuple of (list_of_NewsItem, fetcher_name).
        """
        return self._with_failover(
            DataCapability.NEWS_SEARCH,
            "csi",
            f"news search q={q!r}",
            lambda f: f.search_news(q, from_date, to_date, limit),
            return_source=True,
        )

    # ---------- news flash ----------

    def get_flash_news(self, limit: int = 50) -> tuple[list[dict], str]:
        """全球财经快讯 (7x24 实时推送),通过 NEWS_FLASH-capable fetcher 获取。

        上游 pageSize 硬 cap 200;用户传超过 200 时,路由层 Query(le=200) 会先拦,
        这里再二次防御。

        Returns:
            Tuple of (list_of_FlashNewsItem, fetcher_name)。
        """
        return self._with_failover(
            DataCapability.NEWS_FLASH,
            "csi",
            f"news flash limit={limit}",
            lambda f: f.fetch_flash_news(limit),
            return_source=True,
        )

    # ---------- realtime quotes (with circuit breaker) ----------

    def get_realtime_quote(self, stock_code: str) -> UnifiedRealtimeQuote | None:
        """Get realtime quote with automatic failover and circuit breaker."""
        stock_code = normalize_stock_code(stock_code)
        market = market_tag(stock_code)

        return self._with_failover(
            DataCapability.REALTIME_QUOTE, market, f"realtime {stock_code}",
            lambda f: f.get_realtime_quote(stock_code),
            allow_none=True, circuit_breaker=REALTIME_CIRCUIT_BREAKER,
        )

    # ---------- trade calendar (with persistence) ----------

    def get_trade_calendar(self) -> tuple[list[str], str]:
        """Get A-share trade calendar with automatic failover.

        Tries each fetcher's get_trade_calendar() in priority order.
        Akshare is primary; Baostock is fallback. On success, the result
        is persisted; on total upstream failure, the cached value is
        returned (or DataFetchError if no cache either).

        Returns:
            Tuple of ``(dates, origin)`` where ``origin`` is the
            fetcher name (e.g. ``"akshare"``) when the data was
            freshly fetched, or ``"persistence"`` when the cached
            value was used as the upstream-failure fallback.
            ``dates`` is a list of YYYY-MM-DD strings, sorted ascending.

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
            dates, fetcher_source = self._with_failover(
                DataCapability.TRADE_CALENDAR,
                "csi",
                "trade calendar",
                _fetch_and_persist,
                return_source=True,
            )
            return dates, fetcher_source
        except DataFetchError:
            # Fallback: return cached data if upstream fails
            cached, _ = get_cached_calendar()
            if cached:
                logger.warning(
                    f"[Manager] All fetchers failed calendar, using {len(cached)} cached dates"
                )
                return cached, "persistence"
            raise

    # ---------- ZT/DT/ZBGC pool (with persistence) ----------

    def get_zt_pool_raw(
        self,
        pool_type: str,
        date: str,
    ) -> tuple[list[dict], str]:
        """Pure upstream ZT/DT/ZBGC pool fetch — no caching, no fallback.

        Thin wrapper over the ZT_POOL-capability failover. Raises
        ``DataFetchError`` when every fetcher fails. The persistence
        layer (``pool_daily.get_pool``) is responsible for all
        date-aware read/write/fallback policy; this method is the
        single point of "talk to upstream" and has no opinion on
        volatility or current-day semantics.

        Returns:
            Tuple of (stocks, fetcher_name) when the upstream call
            succeeds; the persistence layer unpacks this to forward
            the fetcher name as the response's origin.
        """
        def _fetch(fetcher: BaseFetcher) -> list[dict] | None:
            return fetcher.get_zt_pool(pool_type, date)
        return self._with_failover(
            DataCapability.STOCK_ZT_POOL,
            "csi",
            f"ZT pool {pool_type} {date}",
            _fetch,
            return_source=True,
        )

    def get_zt_pool(
        self,
        pool_type: str,
        date: str | None = None,
        refresh: bool = False,
        is_current_day: bool = False,
    ) -> tuple[list[dict], str]:
        """Get ZT (涨跌停) pool data with date-keyed persistence.

        Convenience wrapper that resolves the query date and delegates
        to ``persistence.pool_daily.get_pool``, which owns the
        "current day vs historical" policy. The ``is_current_day``
        parameter is kept for backward compatibility but is now
        ignored — the persistence layer computes volatility from the
        date itself.

        Returns:
            Tuple of ``(stocks, origin)`` forwarded straight from
            ``persistence.pool_daily.get_pool``. ``origin`` is the
            fetcher name (e.g. ``"akshare"``) when the data was
            served from the upstream, or ``"persistence"`` when the
            data was read from the SQLite cache.
        """
        from .persistence.pool_daily import (
            get_latest_cached_date,
            get_pool,
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

        stocks, origin = get_pool(
            pool_type=pool_type,
            date=query_date,
            manager=self,
            refresh=refresh,
        )
        return stocks, origin

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
        return self._with_failover(
            DataCapability.INDEX_HISTORICAL, index_type, f"index_hist {index_code}",
            lambda f: f.get_index_historical(index_code, start_date, end_date, frequency),
            return_source=True,
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
        return self._with_failover(
            DataCapability.INDEX_INTRADAY, index_type, f"index_intra {index_code}",
            lambda f: f.get_index_intraday(index_code, period),
            return_source=True,
        )

    # ---------- boards (unified entry points) ----------
    #
    # 板块方法使用 _with_source 路由（按 source 名定位 fetcher），不做 failover。
    # 不同数据源的板块分类体系不兼容（EastMoney 用 concept/industry 二分，
    # Zhitu 用 board_type × subtype 二维），failover 会产生误导性结果。
    #
    # 每个 fetcher 必须实现 4 个统一入口方法：
    #   - get_all_boards(board_type, subtype, source) → list[{code, name, type, subtype, ...quote}]
    #   - get_board_stocks(board_code, source) → list[{stock_code, stock_name, exchange}]
    #   - get_stock_boards(stock_code, source) → list[{code, name, type, subtype}] | None
    #   - get_board_history(board_code, source, frequency, days) → list[…]
    #     当前 EastMoney / Zhitu fetcher 内部 raise NotImplementedError;
    #     Manager 路由已就绪, 等 fetcher 实现.

    def get_all_boards(
        self,
        source: str,
        board_type: str,
        subtype: str | None = None,
        include_quote: bool = False,
    ) -> tuple[list[dict], str]:
        """Get boards of a given type and optional subtype from the named source.

        Args:
            source: fetcher name (e.g. ``"eastmoney"``, ``"zhitu"``).
            board_type: one of ``concept / industry / index / special``.
            subtype: source-specific subtype filter (validated by persistence).
            include_quote: forward to fetcher — include realtime quote fields.

        Returns:
            ``(boards, fetcher_name)`` tuple.
        """
        boards, name = self._with_source(
            source=source,
            capability=DataCapability.STOCK_BOARD,
            market="csi",
            op_label=f"{board_type}/{subtype or '*'} boards ({source})",
            call=lambda f: (
                f.get_all_boards(
                    board_type=board_type,
                    subtype=subtype,
                    source=source,
                    include_quote=include_quote,
                ),
                f.name,
            ),
        )
        return boards, name

    def get_board_stocks(
        self, board_code: str, source: str, include_quote: bool = False
    ) -> tuple[list[dict], str]:
        """Get stocks belonging to a board from the named source."""
        stocks, name = self._with_source(
            source=source,
            capability=DataCapability.STOCK_BOARD,
            market="csi",
            op_label=f"board stocks {board_code} ({source})",
            call=lambda f: (
                f.get_board_stocks(
                    board_code, source=source, include_quote=include_quote,
                ),
                f.name,
            ),
        )
        return stocks, name

    def get_stock_boards(
        self, stock_code: str, source: str
    ) -> tuple[list[dict] | None, str]:
        """Get boards a stock belongs to from the named source.

        Returns ``(None, name)`` if the fetcher signals "no data" (vs empty list).
        """
        result, name = self._with_source(
            source=source,
            capability=DataCapability.STOCK_BOARD,
            market="csi",
            op_label=f"stock boards {stock_code} ({source})",
            call=lambda f: (f.get_stock_boards(stock_code, source=source), f.name),
        )
        return result, name

    def get_board_history(
        self,
        board_code: str,
        source: str,
        frequency: str = "d",
        *,
        start_date: str | None = None,
        end_date: str | None = None,
        days: int = 30,
    ) -> tuple[list[dict], str]:
        """Get K-line for a board from the named source (zzshare only).

        `start_date` / `end_date` (YYYY-MM-DD) take precedence over `days`.
        Source-routed (no failover) per CLAUDE.md — board classification
        systems differ across sources.
        """
        result, name = self._with_source(
            source=source,
            capability=DataCapability.STOCK_BOARD,
            market="csi",
            op_label=f"board K-line {board_code} ({source})",
            call=lambda f: (
                f.get_board_history(
                    board_code,
                    frequency=frequency,
                    days=days,
                    start_date=start_date,
                    end_date=end_date,
                    source=source,
                ),
                f.name,
            ),
        )
        return result, name

    # ---------- eastmoney datacenter endpoints ----------

    def get_dragon_tiger(self, code: str, trade_date: str = "", look_back: int = 30) -> tuple[dict, str]:
        return self._with_failover(
            DataCapability.DRAGON_TIGER, "csi", f"dragon_tiger {code}",
            lambda f: f.get_dragon_tiger(code, trade_date, look_back),
            return_source=True,
        )

    def get_daily_dragon_tiger(self, trade_date: str = "", min_net_buy: float | None = None) -> tuple[dict, str]:
        return self._with_failover(
            DataCapability.DRAGON_TIGER, "csi", "daily dragon_tiger",
            lambda f: f.get_daily_dragon_tiger(trade_date, min_net_buy),
            return_source=True,
        )

    def get_margin_trading(self, code: str, page_size: int = 30) -> tuple[list[dict], str]:
        return self._with_failover(
            DataCapability.MARGIN_TRADING, "csi", f"margin_trading {code}",
            lambda f: f.get_margin_trading(code, page_size),
            return_source=True,
        )

    def get_block_trade(self, code: str, page_size: int = 20) -> tuple[list[dict], str]:
        return self._with_failover(
            DataCapability.BLOCK_TRADE, "csi", f"block_trade {code}",
            lambda f: f.get_block_trade(code, page_size),
            return_source=True,
        )

    def get_holder_num_change(self, code: str, page_size: int = 10) -> tuple[list[dict], str]:
        return self._with_failover(
            DataCapability.HOLDER_NUM, "csi", f"holder_num {code}",
            lambda f: f.get_holder_num_change(code, page_size),
            return_source=True,
        )

    def get_dividend(self, code: str, page_size: int = 20) -> tuple[list[dict], str]:
        return self._with_failover(
            DataCapability.DIVIDEND, "csi", f"dividend {code}",
            lambda f: f.get_dividend(code, page_size),
            return_source=True,
        )

    def get_stock_info(self, code: str) -> tuple[dict, str]:
        """拉取公司画像 (A 股). Failover: Zhitu (P4) → Myquant (P9)."""
        return self._with_failover(
            DataCapability.STOCK_INFO, "csi", f"stock_info {code}",
            lambda f: f.get_stock_info(code),
            return_source=True,
        )

    def get_fund_flow_minute(self, code: str) -> tuple[list[dict], str]:
        return self._with_failover(
            DataCapability.FUND_FLOW, "csi", f"fund_flow_minute {code}",
            lambda f: f.get_fund_flow_minute(code),
            return_source=True,
        )

    def get_fund_flow_120d(self, code: str) -> tuple[list[dict], str]:
        return self._with_failover(
            DataCapability.FUND_FLOW, "csi", f"fund_flow_120d {code}",
            lambda f: f.get_fund_flow_120d(code),
            return_source=True,
        )

    # ---------- ths / research / announcement ----------

    def get_hot_topics(self, date_str: str = "") -> tuple[list[dict], str]:
        return self._with_failover(
            DataCapability.HOT_TOPICS, "csi", "hot_topics",
            lambda f: f.get_hot_topics(date_str),
            return_source=True,
        )

    def get_north_flow(self) -> tuple[list[dict], str]:
        return self._with_failover(
            DataCapability.NORTH_FLOW, "csi", "north_flow",
            lambda f: f.get_north_flow(),
            return_source=True,
        )

    def get_reports(self, code: str, max_pages: int = 5) -> tuple[list[dict], str]:
        return self._with_failover(
            DataCapability.RESEARCH_REPORT, "csi", f"reports {code}",
            lambda f: f.get_reports(code, max_pages),
            return_source=True,
        )

    def get_announcements(self, code: str, page_size: int = 30) -> tuple[list[dict], str]:
        return self._with_failover(
            DataCapability.ANNOUNCEMENT, "csi", f"announcements {code}",
            lambda f: f.get_announcements(code, page_size),
            return_source=True,
        )

    def get_report_pdf(self, report_id: str) -> tuple[str, str]:
        """Resolve a research report PDF.

        Returns ``(download_path, url)``. Routes through every fetcher that
        declares ``RESEARCH_REPORT`` capability, calling ``download_report_pdf``
        on each until one returns a non-None path.

        Raises:
            DataFetchError: when no fetcher can serve the PDF.
        """
        path, source = self._with_failover(
            DataCapability.RESEARCH_REPORT, "csi", f"report_pdf {report_id}",
            lambda f: f.download_report_pdf(report_id),
            return_source=True,
        )
        fetcher = self.get_fetcher(source)
        url = fetcher.get_report_pdf_url(report_id) or "" if fetcher else ""
        logger.info(f"[Manager] {source} served report PDF {report_id} -> {path}")
        return path, url

    # ---------- introspection ----------

    @property
    def available_fetchers(self) -> list[str]:
        """List available fetcher names."""
        return [f.name for f in self._fetchers]

    @property
    def fetchers(self) -> list["BaseFetcher"]:  # type: ignore[misc]
        """List all fetchers. Prefer get_fetcher() for single fetcher lookup."""
        return list(self._fetchers)


def create_default_manager() -> DataFetcherManager:
    """Create a DataFetcherManager with all available fetchers registered.

    Each fetcher is instantiated and tested via ``is_available()``; only
    available fetchers are registered. This is the single source of truth
    for fetcher registration — callers in ``routes.py`` and ``persistence/``
    should use this factory instead of constructing their own manager.

    Returns:
        A fully configured DataFetcherManager with available fetchers
        registered in priority order.
    """
    # Lazy imports to avoid circular dependencies at module level
    from .fetchers.akshare import AkshareFetcher
    from .fetchers.baidu_fetcher import BaiduFetcher
    from .fetchers.baostock_fetcher import BaostockFetcher
    from .fetchers.cninfo_fetcher import CninfoFetcher
    from .fetchers.eastmoney_fetcher import EastMoneyFetcher
    from .fetchers.myquant_fetcher import MyquantFetcher
    from .fetchers.tencent_fetcher import TencentFetcher
    from .fetchers.ths_fetcher import ThsFetcher
    from .fetchers.tushare_fetcher import TushareFetcher
    from .fetchers.yfinance_fetcher import YfinanceFetcher
    from .fetchers.zhitu_fetcher import ZhituFetcher
    from .fetchers.zzshare_fetcher import ZzshareFetcher   # NEW

    manager = DataFetcherManager()
    fetcher_classes = [
        TushareFetcher,
        BaostockFetcher,
        MyquantFetcher,
        AkshareFetcher,
        YfinanceFetcher,
        ZhituFetcher,
        ZzshareFetcher,   # NEW (P5; placed after Zhitu for human-readable order)
        TencentFetcher,
        EastMoneyFetcher,
        BaiduFetcher,
        ThsFetcher,
        CninfoFetcher,
    ]
    for cls in fetcher_classes:
        instance = cls()
        if instance.is_available():
            manager.add_fetcher(instance)
            logger.info(f"{cls.__name__} added")
        else:
            logger.info(f"{cls.__name__} skipped")
    return manager
