"""
Manager for multiple stock data fetchers with priority-based failover.
"""

import logging
from collections.abc import Callable
from threading import RLock
from typing import Any, TypeVar

import pandas as pd

from .base import BaseFetcher, DataCapability, DataFetchError
from .core.types import (
    KLINE_CIRCUIT_BREAKER,
    REALTIME_CIRCUIT_BREAKER,
    CircuitBreaker,
    UnifiedRealtimeQuote,
)
from .utils.normalize import index_market_tag, market_tag, normalize_stock_code

logger = logging.getLogger(__name__)

T = TypeVar("T")


def _is_meaningful(result: Any) -> bool:
    """Treat None, empty DataFrames, and empty lists as 'no data' (skip fetcher)."""
    if result is None:
        return False
    if isinstance(result, pd.DataFrame) and result.empty:
        return False
    return not (isinstance(result, list) and len(result) == 0)


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
            slug: f for f in self._fetchers for slug in [self._derive_slug(f.name)] if slug
        }

    def add_fetcher(self, fetcher: BaseFetcher) -> None:
        """Add a fetcher and re-sort by priority."""
        with self._lock:
            self._fetchers.append(fetcher)
            self._fetchers.sort(key=lambda f: f.priority)
            self._refresh_index()

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

    def get_fetcher(self, source: str) -> BaseFetcher:
        """Look up a fetcher instance by its source slug (or full class name).

        Public API for the route layer — use this when you need to inspect
        a fetcher's capabilities (e.g. ``hasattr(fetcher, "get_board_realtime")``)
        *before* dispatching through ``_with_source``. Avoids reaching into
        the private ``_slug_index`` or iterating ``self._fetchers`` from
        outside the manager.

        Args:
            source: Fetcher name. Accepts the slug form (e.g. ``"ths"``,
                case-insensitive) or the full fetcher class name (e.g.
                ``"ThsFetcher"``). Slug match is preferred; full-name
                match is the fallback — same convention as
                :meth:`_with_source`.

        Returns:
            The registered :class:`BaseFetcher` instance.

        Raises:
            ValueError: when no fetcher matches the requested name.
                The exception message names the source slug.
        """
        target: BaseFetcher | None = None
        with self._lock:
            target = self._slug_index.get(source.lower())
            if target is None:
                for f in self._fetchers:
                    if f.name.lower() == source.lower():
                        target = f
                        break
        if target is None:
            raise ValueError(f"No fetcher with name {source!r} is registered")
        return target

    def _with_source(
        self,
        source: str,
        capability: DataCapability,
        market: str,
        op_label: str,
        call: Callable[[BaseFetcher], T],
        *,
        method_name: str | None = None,
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
            method_name: Optional method name to verify exists on the
                chosen fetcher. When provided, the fetcher is checked
                with ``hasattr`` before ``call`` runs; missing methods
                raise ``ValueError`` (caller decides how to surface
                — typically 400 / 404 / 422 with a clear message).
                This prevents AttributeError → 500 leaks when the route
                picks a fetcher that has the capability flag but does
                not implement the specific method.

        Returns:
            Whatever ``call(fetcher)`` returns.

        Raises:
            ValueError: when no fetcher matches the requested source,
                or the matching fetcher does not declare ``capability`` /
                does not support ``market`` / does not implement
                ``method_name``. The exception message names the cause
                and the missing flag / method.
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
            raise ValueError(f"No fetcher with name {source!r} is registered")
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
        if method_name is not None and not hasattr(target, method_name):
            raise ValueError(
                f"Fetcher {target.name!r} does not implement {method_name!r} "
                f"(required for {op_label}). "
                f"This is a capability-flag mismatch: the fetcher declares "
                f"{capability.name!r} but does not implement the specific method."
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
        candidates: list[BaseFetcher] | None = None,
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
            candidates: pre-filtered fetcher list (from ``_kline_candidates``
                or ``_quote_candidates``). When provided, skips internal
                ``_filter_by_capability`` — the caller already did the
                two-stage filter (capability bit → supports_fn).

        Returns:
            The first non-None/non-empty result (or ``(result, source_name)``
            when ``return_source=True``).

        Raises:
            DataFetchError: when all fetchers fail and ``allow_none`` is False.
        """
        fetchers = (
            candidates if candidates is not None else self._filter_by_capability(market, capability)
        )
        errors: list[str] = []
        # Track the last empty result so an "empty chain" (no fetcher raised
        # AND no fetcher returned meaningful data) can return a coherent
        # empty answer instead of a misleading "All fetchers failed" error
        # with an empty errors list. Review 2026-07-06 finding #6.
        last_empty_result: Any = None
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
            # Result is None/empty — remember the last empty result (prefer
            # [] over None for downstream compatibility) and treat as soft
            # failure for circuit breaker.
            if result is not None:
                last_empty_result = result
            if circuit_breaker is not None:
                circuit_breaker.record_failure(fetcher.name)

        # No fetcher returned meaningful data. Three sub-cases:
        #   (a) allow_none=True          → caller opts into (None, "")
        #   (b) no errors at all         → every candidate returned None/[];
        #                                  return the last empty result with
        #                                  source="" — this is "no data
        #                                  found", not "all failed".
        #   (c) errors occurred           → raise the aggregated failure.
        if allow_none:
            return (None, "") if return_source else None  # type: ignore[return-value]
        if not errors and last_empty_result is not None:
            logger.info(
                f"[Manager] {op_label}: all {len(fetchers)} candidates returned "
                f"empty results (no fetcher raised)"
            )
            return (last_empty_result, "") if return_source else last_empty_result  # type: ignore[return-value]
        prefix = error_prefix or f"All fetchers failed for {op_label}:"
        if not errors and circuit_breaker is not None:
            raise DataFetchError(
                f"{prefix} all candidate fetchers are circuit-open "
                f"(cooldown ~{circuit_breaker.cooldown_seconds:.0f}s). Retry later."
            )
        raise DataFetchError(prefix + "\n" + "\n".join(errors))

    # ---------- K-line & intraday (stocks) ----------
    #
    # Per spec §4.4: two-stage filter (capability bit → supports_kline).
    # Rev 3 explicitly removed fallback_cap (decorative dead code).

    def _candidates(
        self,
        market: str,
        capability: DataCapability,
        supports_fn: Callable[[BaseFetcher], bool],
    ) -> list[BaseFetcher]:
        """Generic two-stage filter: capability bit → per-fetcher support check.

        Stage 1 narrows by capability bit plus market. Stage 2 applies
        ``supports_fn(fetcher)`` to each candidate so we never try a
        fetcher that will refuse this exact request.

        Returns an unsorted list — caller sorts by priority and runs failover.
        """
        candidates = self._filter_by_capability(market, capability)
        return [f for f in candidates if supports_fn(f)]

    def _kline_candidates(
        self,
        market: str,
        asset: str,
        frequency: str,
        adjust: str | None,
    ) -> list[BaseFetcher]:
        """Two-stage filter for K-line per spec §4.4.

        Delegates to ``_candidates`` with KLINE capability and
        ``supports_kline`` check.
        """
        cap = DataCapability.INDEX_KLINE if asset == "index" else DataCapability.STOCK_KLINE
        adj = adjust or ""
        return self._candidates(
            market,
            cap,
            lambda f: f.supports_kline(frequency, adj, market, asset),
        )

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
        Get K-line data with automatic failover (spec §4.4 two-stage filter).

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
            DataFetchError: When no fetcher's supports_kline accepts the request
                (e.g. 1m + qfq), or when every supporting fetcher fails.
        """
        stock_code = normalize_stock_code(stock_code)
        index_tag = index_market_tag(stock_code)
        market = index_tag or market_tag(stock_code)
        asset = "index" if index_tag else "stock"

        candidates = self._kline_candidates(market, asset, frequency, adjust)
        if not candidates:
            raise DataFetchError(
                f"No fetcher supports asset={asset} period={frequency} "
                f"adjust={adjust!r} market={market}"
            )

        cap = DataCapability.INDEX_KLINE if asset == "index" else DataCapability.STOCK_KLINE
        return self._with_failover(
            cap,
            market,
            f"kline {stock_code} {frequency}",
            lambda f: f.get_kline_data(stock_code, start_date, end_date, days, frequency, adjust),
            return_source=True,
            circuit_breaker=KLINE_CIRCUIT_BREAKER,
            candidates=sorted(candidates, key=lambda f: f.priority),
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
            DataCapability.STOCK_LIST,
            market,
            f"all_stocks {market}",
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

    # ---------- CLS 财联社早报 / 焦点复盘 ----------

    def _fetch_cls_optional(
        self,
        capability: DataCapability,
        op_label: str,
        call: Callable[[BaseFetcher], T],
    ) -> tuple[T, str]:
        """CLS-specific failover: distinguishes "upstream failed" from "no article".

        Unlike ``_with_failover(allow_none=True)`` — which collapses both
        cases into ``(None, "")`` and makes the OpenAPI 503 unreachable —
        this helper:
          - raises DataFetchError when **all** candidate fetchers raised
            (route layer → 503 via @map_errors),
          - returns ``(None, "")`` when **all** candidates returned None
            (route layer → 404 "no article for this date"),
          - returns ``(article, fetcher.name)`` on the first success.
        """
        fetchers = self._filter_by_capability("csi", capability)
        if not fetchers:
            return None, ""  # type: ignore[return-value]
        errors: list[str] = []
        for fetcher in fetchers:
            try:
                result = call(fetcher)
            except DataFetchError as e:
                errors.append(f"[{fetcher.name}] {e}")
                logger.warning(f"[Manager] {fetcher.name} {op_label} failed: {e}")
                continue
            if result is not None:
                return result, fetcher.name
        # Every candidate either raised or returned None.
        if errors:
            prefix = f"All fetchers failed for {op_label}:"
            raise DataFetchError(prefix + "\n" + "\n".join(errors))
        return None, ""  # type: ignore[return-value]

    def get_morning_briefing(self, date: str) -> tuple[dict | None, str]:
        """Fetch 财联社早报 for `date` (YYYY-MM-DD) via MORNING_BRIEFING-capable fetchers.

        Returns:
            Tuple of (article_dict_or_None, fetcher_name).
            - article_dict_or_None: ClsArticle-shaped dict, or None if the date
              has no published article (route layer maps None → 404).
            - fetcher_name: fetcher class name (e.g. ``"ClsFetcher"``).

        Raises:
            DataFetchError: when all candidate fetchers raised (route layer
                maps this to 503 via @map_errors).
        """
        return self._fetch_cls_optional(
            capability=DataCapability.MORNING_BRIEFING,
            op_label=f"get_morning_briefing {date}",
            call=lambda f: f.get_morning_briefing(date),
        )

    def get_market_recap(self, date: str) -> tuple[dict | None, str]:
        """Fetch 财联社焦点复盘 for `date` (YYYY-MM-DD) via MARKET_RECAP-capable fetchers.

        Same return / raise semantics as get_morning_briefing.
        """
        return self._fetch_cls_optional(
            capability=DataCapability.MARKET_RECAP,
            op_label=f"get_market_recap {date}",
            call=lambda f: f.get_market_recap(date),
        )

    # ---------- stock news (per-stock feed) ----------

    def get_stock_news(self, code: str, limit: int = 20) -> tuple[list[dict], str]:
        """Get stock-specific news feed via STOCK_NEWS-capable fetchers.

        Capability-based routing: only fetchers that declare ``STOCK_NEWS``
        are tried. EastMoney is currently the sole fetcher declaring this
        capability (np-listapi endpoint).

        Returns:
            Tuple of (list_of_news_items, fetcher_name).
        """
        return self._with_failover(
            DataCapability.STOCK_NEWS,
            "csi",
            f"stock news {code}",
            lambda f: f.get_stock_news(code, limit),
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

    def _quote_candidates(
        self,
        market: str,
        capability: DataCapability,
    ) -> list[BaseFetcher]:
        """Two-stage filter for quote per spec §4.4.

        Delegates to ``_candidates`` with quote capability and
        ``supports_quote`` check.
        """
        return self._candidates(
            market,
            capability,
            lambda f: f.supports_quote(market),
        )

    def get_realtime_quote(self, stock_code: str) -> UnifiedRealtimeQuote | None:
        """Get realtime quote with two-stage filter and circuit breaker (spec §4.4).

        The circuit breaker is checked per-fetcher inside the failover loop —
        a fetcher in OPEN state is skipped without making a network call. The
        first non-None result wins; on total failure, raises ``DataFetchError``.
        """
        stock_code = normalize_stock_code(stock_code)
        market = market_tag(stock_code)

        candidates = self._quote_candidates(market, DataCapability.STOCK_REALTIME_QUOTE)
        if not candidates:
            raise DataFetchError(f"No fetcher supports quote market={market}")

        return self._with_failover(
            DataCapability.STOCK_REALTIME_QUOTE,
            market,
            f"quote {stock_code}",
            lambda f: f.get_realtime_quote(stock_code),
            circuit_breaker=REALTIME_CIRCUIT_BREAKER,
            candidates=sorted(candidates, key=lambda f: f.priority),
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
    ) -> tuple[list[dict], str, str | None]:
        """Get ZT (涨跌停) pool data with date-keyed persistence.

        Returns:
            Tuple of ``(stocks, origin, warning)`` forwarded straight
            from ``persistence.pool_daily.get_pool``.
            ``origin`` is the fetcher name (e.g. ``"akshare"``) when
            the data was served from the upstream, or ``"persistence"``
            when the data was read from the SQLite cache.
            ``warning`` is non-None iff the requested date is volatile
            (today + 交易日 + < 16:00); the persistence layer emits a
            single warning text that applies to all return paths
            (cache hit / fresh fetch / upstream-failure fallback).
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

        stocks, origin, warning = get_pool(
            pool_type=pool_type,
            date=query_date,
            manager=self,
            refresh=refresh,
        )
        return stocks, origin, warning

    # ---------- index methods ----------

    def get_index_realtime_quote(self, index_code: str) -> UnifiedRealtimeQuote | None:
        """Get realtime quote for an index with two-stage filter (spec §4.4).

        Routes through fetchers declaring INDEX_REALTIME_QUOTE capability
        and whose ``supports_quote(market)`` returns True. Each fetcher
        must implement ``get_index_realtime_quote()``.

        Args:
            index_code: Index code (e.g., 000300, 399006, SPX, HSI)

        Returns:
            UnifiedRealtimeQuote or None if not available.

        Raises:
            DataFetchError: When no fetcher survives both stages (capability +
                supports_quote) for the requested market.
        """
        index_code = normalize_stock_code(index_code)
        index_type = index_market_tag(index_code) or "csi"

        candidates = self._quote_candidates(index_type, DataCapability.INDEX_REALTIME_QUOTE)
        if not candidates:
            raise DataFetchError(f"No fetcher supports quote market={index_type}")

        return self._with_failover(
            DataCapability.INDEX_REALTIME_QUOTE,
            index_type,
            f"index_quote {index_code}",
            lambda f: f.get_index_realtime_quote(index_code),
            circuit_breaker=REALTIME_CIRCUIT_BREAKER,
            candidates=sorted(candidates, key=lambda f: f.priority),
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
    #   - get_board_history(board_code, source, frequency, *, start_date, end_date, days) → list[…]
    #     已实现于 ZzshareFetcher (zzshare plate_kline, daily-only).
    #     EastMoney/Zhitu 无对应上游 API, 故不实现该方法 (manifest 不再列出它们).

    def get_all_boards(
        self,
        source: str,
        board_type: str | None = None,
        subtype: str | None = None,
        include_quote: bool = False,
    ) -> tuple[list[dict], str]:
        """Get boards of a given type and optional subtype from the named source.

        Args:
            source: fetcher name (e.g. ``"eastmoney"``, ``"zhitu"``).
            board_type: one of ``concept / industry / index / special``, or
                ``None`` to query every type the source exposes.
            subtype: source-specific subtype filter (validated by persistence).
                Ignored when ``board_type`` is ``None`` (each type has its
                own subtype set; filtering across all types would be
                ambiguous and is unsupported at this layer).
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
        self,
        board_code: str,
        source: str,
        include_quote: bool = False,
        board_type: str | None = None,
        *,
        sort_by: str | None = None,  # 2026-07-13: forward to fetcher
        sort_order: str = "desc",  # 2026-07-13: forward to fetcher
        top_n: int = 50,  # 2026-07-13: forward to fetcher
    ) -> tuple[list[dict], str]:
        """Get stocks belonging to a board from the named source.

        New keyword-only params (2026-07-13): sort_by / sort_order / top_n.
        Forwarded to the fetcher when the chosen source implements them.
        Fetchers whose get_board_stocks(**kwargs) absorbs them silently
        (ZzshareFetcher, ZhituFetcher, MyquantFetcher) work without per-source
        changes; ThsFetcher explicitly reads the 3 kwargs; EastMoneyFetcher
        has no **kwargs, so route-layer 400 cross-validation guarantees
        eastmoney never receives these.

        Args:
            board_code: 6-digit ``BK`` prefixed board code.
            source: fetcher name (e.g. ``"eastmoney"``).
            include_quote: attach realtime quote fields when supported.
            board_type: When ``"concept"`` or ``"industry"`` is supplied,
                the fetcher dispatches directly without concept↔industry
                fallback. ``None`` (default) keeps the legacy fallback
                for fetchers that haven't implemented the explicit
                dispatch. Phase 4 (2026-07-02) wired this through to
                fix EastMoney's silent concept→industry fallback on a
                transient upstream 5xx — see BoardsMixin.get_board_stocks.

        Returns:
            ``(stocks, fetcher_name)`` — same shape as before; ``board_type``
            is only used to steer the fetcher, never returned in the
            result.
        """

        def call(f):
            kwargs = {
                "source": source,
                "include_quote": include_quote,
                "sort_by": sort_by,
                "sort_order": sort_order,
                "top_n": top_n,
            }
            # Only pass board_type when explicitly set — keeps the call
            # shape identical for callers that haven't migrated yet
            # (assert_called_once_with tests in test_board_source_routing).
            if board_type is not None:
                kwargs["board_type"] = board_type
            return f.get_board_stocks(board_code, **kwargs), f.name

        stocks, name = self._with_source(
            source=source,
            capability=DataCapability.STOCK_BOARD,
            market="csi",
            op_label=f"board stocks {board_code} ({source})",
            call=call,
        )
        return stocks, name

    def get_stock_boards(self, stock_code: str, source: str) -> tuple[list[dict] | None, str]:
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
        board_type: str | None = None,  # NEW — required for THS concept/industry
    ) -> tuple[list[dict], str]:
        """Get K-line for a board from the named source.

        `start_date` / `end_date` (YYYY-MM-DD) take precedence over `days`.
        Source-routed (no failover) per CLAUDE.md — board classification
        systems differ across sources.

        `board_type` is currently consumed only by ThsFetcher (must be
        ``"concept"`` or ``"industry"``); EastMoney and ZzshareFetcher
        ignore it. Pass it through regardless so the call shape is uniform.

        Frequency × source validation lives here (post-2026-07-14). The
        supported set per source is enumerated by
        :data:`BOARD_KLINE_FREQ_BY_SOURCE`. Today both ``"ths"`` and
        ``"eastmoney"`` accept the full 7-frequency set
        (``d / w / m / 5m / 15m / 30m / 60m``) — verified 2026-07-14 by
        probing each upstream segment against ``d.10jqka.com.cn`` (THS)
        and the corresponding push2his endpoint (EastMoney). A future
        fetcher that drops below the full set only needs to update the
        map; the route layer stays unchanged.
        """
        # Source × frequency validation. Validates before _with_source so
        # the route layer's @map_errors turns a ValueError into a clean
        # 400 (instead of letting the fetcher surface a confusing
        # DataFetchError mid-fetch).
        from .constants import BOARD_KLINE_FREQ_BY_SOURCE

        # Normalize source to slug form so the freq map lookup works for
        # both API-level "ths" / "eastmoney" and the manager's internal
        # full-class-name form ("ThsFetcher" / "EastMoneyFetcher"). Mirrors
        # the slug derivation in ``_derive_slug`` / ``_with_source``.
        slug = self._derive_slug(source)
        valid_freqs = BOARD_KLINE_FREQ_BY_SOURCE.get(slug)
        if valid_freqs is None:
            raise ValueError(
                f"Unknown source {source!r} for board K-line. "
                f"Valid sources: {sorted(BOARD_KLINE_FREQ_BY_SOURCE)}"
            )
        freq_key = (frequency or "d").lower()
        if freq_key not in valid_freqs:
            raise ValueError(
                f"Source {source!r} does not support frequency {frequency!r}; "
                f"supported: {sorted(valid_freqs)}"
            )

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
                    board_type=board_type,
                ),
                f.name,
            ),
        )
        return result, name

    def get_board_realtime(
        self,
        board_code: str,
        source: str,
        *,
        board_type: str | None = None,
    ) -> tuple[dict, str]:
        """Get board-level realtime quote from the named source (source-routed).

        No failover — board classification systems differ across sources.
        Currently only ThsFetcher implements ``get_board_realtime``; other
        sources fail fast with a ``ValueError`` (not AttributeError) — the
        route layer maps that to 400/422 with a clear ``unsupported``
        error instead of letting a 500 leak.

        ``method_name="get_board_realtime"`` triggers the
        capability-flag/method-implementation pre-check in
        :meth:`_with_source`. A fetcher that declares STOCK_BOARD but
        doesn't implement the method (today: EastMoneyFetcher, ZhituFetcher)
        raises ValueError before the call lambda runs.

        ``board_type`` is plumbed through to the fetcher so the
        concept/industry decision is data-driven (via the stock_board
        cache) rather than magic-string-based (legacy ``"881"`` prefix).
        When the caller passes None, the fetcher does a one-shot
        ``get_board_metadata`` fallback — see ThsFetcher for details.
        """
        return self._with_source(
            source=source,
            capability=DataCapability.STOCK_BOARD,
            market="csi",
            op_label=f"board realtime {board_code} ({source})",
            call=lambda f: (f.get_board_realtime(board_code, board_type=board_type), f.name),
            method_name="get_board_realtime",
        )

    def get_board_stocks_full(
        self,
        board_code: str,
        source: str,
        *,
        board_type: str | None = None,
    ) -> tuple[list[dict], str]:
        """Get THS F10 concept-page full membership (90+ members).

        Source-routed (``_with_source``) — only ``source='ths'`` is valid.
        No failover: only ThsFetcher implements
        :meth:`ThsFetcher.get_board_stocks_full` (the F10 page is THS-only).

        Invoked by ``persistence/board.py::fetch_board_stocks_with_zzshare_fallback``
        (leg 3 of the include_quote=False path, added 2026-07-20 per
        spec §3.5.1). Distinct from ``get_board_stocks`` (q.10jqka AJAX
        path with hard cap 50).
        """
        return self._with_source(
            source=source,
            capability=DataCapability.STOCK_BOARD,
            market="csi",
            op_label=f"board stocks full {board_code} ({source})",
            call=lambda f: (f.get_board_stocks_full(board_code, board_type=board_type), f.name),
            method_name="get_board_stocks_full",
        )

    def get_board_news(
        self,
        board_code: str,
        source: str,
        limit: int = 20,
        *,
        board_type: str | None = None,
    ) -> tuple[list[dict], str]:
        """Get THS F10 news section ``<div class="m_box post" id="news">``.

        Source-routed — only ``source='ths'`` is valid; the route layer
        pins this via ``Literal["ths"]``.
        """
        return self._with_source(
            source=source,
            capability=DataCapability.BOARD_NEWS,
            market="csi",
            op_label=f"board news {board_code} ({source})",
            call=lambda f: (
                f.get_board_news(board_code, limit=limit, board_type=board_type),
                f.name,
            ),
            method_name="get_board_news",
        )

    def get_board_surges(
        self,
        board_code: str,
        source: str,
        limit: int = 5,
        *,
        board_type: str | None = None,
    ) -> tuple[list[dict], str]:
        """Get THS F10 surges section ``<div class="m_box" id="period">``.

        Source-routed — only ``source='ths'`` is valid.
        """
        return self._with_source(
            source=source,
            capability=DataCapability.BOARD_SURGES,
            market="csi",
            op_label=f"board surges {board_code} ({source})",
            call=lambda f: (
                f.get_board_surges(board_code, limit=limit, board_type=board_type),
                f.name,
            ),
            method_name="get_board_surges",
        )

    # ---------- eastmoney datacenter endpoints ----------

    def _route_cap(
        self,
        capability: DataCapability,
        method_name: str,
        *args: Any,
        op_label: str | None = None,
    ) -> Any:
        """CSI-market capability routing boilerplate.

        Every get_* below used to be a 7-line ``_with_failover(<cap>, "csi",
        <label>, lambda f: f.<method>(<args>), return_source=True)`` block.
        Default ``op_label`` is ``"<method minus 'get_'> {args[0]}"`` when
        args is non-empty, else the bare short method name. Override for
        static labels (``"hot_topics"``, ``"north_flow"``,
        ``"daily dragon_tiger"``).
        """
        if op_label is None:
            short = method_name[4:] if method_name.startswith("get_") else method_name
            op_label = f"{short} {args[0]}" if args else short
        return self._with_failover(
            capability,
            "csi",
            op_label,
            lambda f: getattr(f, method_name)(*args),
            return_source=True,
        )

    def get_dragon_tiger(self, code: str, trade_date: str = "") -> tuple[dict, str]:
        return self._route_cap(DataCapability.DRAGON_TIGER, "get_dragon_tiger", code, trade_date)

    def get_daily_dragon_tiger(
        self, trade_date: str = "", min_net_buy: float | None = None
    ) -> tuple[dict, str]:
        return self._route_cap(
            DataCapability.DRAGON_TIGER,
            "get_daily_dragon_tiger",
            trade_date,
            min_net_buy,
            op_label="daily dragon_tiger",
        )

    def get_margin_trading(self, code: str, page_size: int = 30) -> tuple[list[dict], str]:
        return self._route_cap(DataCapability.MARGIN_TRADING, "get_margin_trading", code, page_size)

    def get_block_trade(self, code: str, page_size: int = 20) -> tuple[list[dict], str]:
        return self._route_cap(DataCapability.BLOCK_TRADE, "get_block_trade", code, page_size)

    # Log label is "holder_num {code}" (not "holder_num_change") to match the
    # upstream zhitu op_label + the cache hit_label in routes/stocks.py. The
    # short-name derivation in _route_cap uses method_name verbatim, so this
    # wrapper inlines the call to preserve the legacy label exactly.
    def get_holder_num_change(self, code: str, page_size: int = 10) -> tuple[list[dict], str]:
        return self._with_failover(
            DataCapability.HOLDER_NUM,
            "csi",
            f"holder_num {code}",
            lambda f: f.get_holder_num_change(code, page_size),
            return_source=True,
        )

    def get_dividend(self, code: str, page_size: int = 20) -> tuple[list[dict], str]:
        return self._route_cap(DataCapability.DIVIDEND, "get_dividend", code, page_size)

    def get_stock_info(self, code: str) -> tuple[dict, str]:
        """拉取公司画像 (A 股). Failover: Zhitu (P5) → Myquant (P9).

        Note: Zzshare (P2) was previously in this chain but removed 2026-07-14
        because its ``/v3/open/stock/info?info_type=1`` endpoint returns
        ``data: null`` for every A-share (verified against 10 主流 stocks;
        see docs/zzshare/03-basic-data.md § 3). Keeping it as primary would
        add ~3.8s of wasted network per request before falling through.
        """
        return self._route_cap(DataCapability.STOCK_INFO, "get_stock_info", code)

    def get_fund_flow_minute(self, code: str) -> tuple[list[dict], str]:
        return self._route_cap(DataCapability.FUND_FLOW, "get_fund_flow_minute", code)

    def get_fund_flow_120d(self, code: str) -> tuple[list[dict], str]:
        return self._route_cap(DataCapability.FUND_FLOW, "get_fund_flow_120d", code)

    # ---------- ths / research / announcement ----------

    def get_hot_topics(self, date_str: str = "") -> tuple[list[dict], str]:
        return self._route_cap(
            DataCapability.HOT_TOPICS, "get_hot_topics", date_str, op_label="hot_topics"
        )

    def get_north_flow(self) -> tuple[list[dict], str]:
        return self._route_cap(DataCapability.NORTH_FLOW, "get_north_flow")

    def get_reports(self, code: str, max_pages: int = 5) -> tuple[list[dict], str]:
        return self._route_cap(DataCapability.RESEARCH_REPORT, "get_reports", code, max_pages)

    def get_announcements(self, code: str, page_size: int = 30) -> tuple[list[dict], str]:
        return self._route_cap(DataCapability.ANNOUNCEMENT, "get_announcements", code, page_size)

    def get_report_pdf(self, report_id: str) -> tuple[str, str]:
        """Resolve a research report PDF.

        Returns ``(download_path, url)``. Routes through every fetcher that
        declares ``RESEARCH_REPORT`` capability, calling ``download_report_pdf``
        on each until one returns a non-None path.

        Raises:
            DataFetchError: when no fetcher can serve the PDF.
        """
        path, source = self._with_failover(
            DataCapability.RESEARCH_REPORT,
            "csi",
            f"report_pdf {report_id}",
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
    from .fetchers.cls_fetcher import ClsFetcher
    from .fetchers.cninfo_fetcher import CninfoFetcher
    from .fetchers.eastmoney_fetcher import EastMoneyFetcher
    from .fetchers.myquant_fetcher import MyquantFetcher
    from .fetchers.tencent_fetcher import TencentFetcher
    from .fetchers.ths_fetcher import ThsFetcher
    from .fetchers.tushare_fetcher import TushareFetcher
    from .fetchers.yfinance_fetcher import YfinanceFetcher
    from .fetchers.zhitu_fetcher import ZhituFetcher
    from .fetchers.zzshare_fetcher import ZzshareFetcher  # NEW

    manager = DataFetcherManager()
    fetcher_classes = [
        TushareFetcher,
        BaostockFetcher,
        MyquantFetcher,
        AkshareFetcher,
        YfinanceFetcher,
        ZhituFetcher,
        ZzshareFetcher,  # NEW (P5; placed after Zhitu for human-readable order)
        TencentFetcher,
        EastMoneyFetcher,
        BaiduFetcher,
        ThsFetcher,
        CninfoFetcher,
        ClsFetcher,
    ]
    for cls in fetcher_classes:
        instance = cls()
        if instance.is_available():
            manager.add_fetcher(instance)
            logger.info(f"{cls.__name__} added")
        else:
            logger.info(f"{cls.__name__} skipped")
    return manager
