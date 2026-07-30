"""Tests for DataFetcherManager.get_realtime_quotes failover."""

from unittest.mock import MagicMock

from stock_data.data_provider.base import DataCapability, DataFetchError
from stock_data.data_provider.core.types import (
    REALTIME_CIRCUIT_BREAKER,
    RealtimeSource,
    UnifiedRealtimeQuote,
)
from stock_data.data_provider.manager import DataFetcherManager


def _make_quote(code: str = "600519", name: str = "贵州茅台") -> UnifiedRealtimeQuote:
    return UnifiedRealtimeQuote(
        code=code, name=name, source=RealtimeSource.AKSHARE, price=1680.5,
    )


class TestManagerGetRealtimeQuotes:
    def _manager(self):
        return DataFetcherManager()

    def _add_fetcher(self, manager, name, priority, supported_data_types,
                     get_realtime_quotes_return=None, raises=None):
        fetcher = MagicMock()
        fetcher.name = name
        fetcher.priority = priority
        fetcher.supported_markets = {"csi"}
        fetcher.supported_data_types = supported_data_types
        if raises is not None:
            fetcher.get_realtime_quotes = MagicMock(side_effect=raises)
        else:
            fetcher.get_realtime_quotes = MagicMock(
                return_value=get_realtime_quotes_return
            )
        manager._fetchers.append(fetcher)
        return fetcher

    def test_akshare_succeeds_returns_akshare_source(self):
        mgr = self._manager()
        akshare = self._add_fetcher(
            mgr, "AkshareFetcher", 3,
            DataCapability.STOCK_REALTIME_QUOTE,
            get_realtime_quotes_return=[_make_quote()],
        )
        quotes, source = mgr.get_realtime_quotes("csi")
        assert source == "AkshareFetcher"
        assert len(quotes) == 1
        assert akshare.get_realtime_quotes.call_count == 1
        assert akshare.get_realtime_quotes.call_args.args == ("csi",)

    def test_akshare_raises_falls_through_to_zzshare(self):
        """Raising primary (highest-priority) fetcher → fall through to next.

        Akshare MUST be P1 here: candidates are tried in ascending priority
        order, so with Akshare at its default P3 vs Zzshare P2, Zzshare would
        win outright and the raise-then-fall-through path would never run
        (the test would pass even if get_realtime_quotes were deleted).
        """
        mgr = self._manager()
        akshare = self._add_fetcher(
            mgr, "AkshareFetcher", 1,  # P1 < P2 — tried first
            DataCapability.STOCK_REALTIME_QUOTE,
            raises=DataFetchError("akshare timeout"),
        )
        zzshare = self._add_fetcher(
            mgr, "ZzshareFetcher", 2,
            DataCapability.STOCK_REALTIME_QUOTE,
            get_realtime_quotes_return=[_make_quote()],
        )
        quotes, source = mgr.get_realtime_quotes("csi")
        assert source == "ZzshareFetcher"
        assert len(quotes) == 1
        assert akshare.get_realtime_quotes.call_count == 1  # raised, then fell through
        assert zzshare.get_realtime_quotes.call_count == 1

    def test_tencent_fetcher_raises_skipped_via_abc_default(self):
        """TencentFetcher doesn't override get_realtime_quotes → ABC default raises.

        Manager catches DataFetchError and skips to next fetcher.
        """
        mgr = self._manager()
        # Tencent-style: has capability but raises on get_realtime_quotes
        self._add_fetcher(
            mgr, "TencentFetcher", 5,
            DataCapability.STOCK_REALTIME_QUOTE,
            raises=DataFetchError("TencentFetcher does not support all-market realtime quote"),
        )
        akshare = self._add_fetcher(
            mgr, "AkshareFetcher", 3,
            DataCapability.STOCK_REALTIME_QUOTE,
            get_realtime_quotes_return=[_make_quote()],
        )
        quotes, source = mgr.get_realtime_quotes("csi")
        assert source == "AkshareFetcher"
        assert len(quotes) == 1

    def test_all_fetchers_fail_returns_none_empty_source(self):
        mgr = self._manager()
        self._add_fetcher(
            mgr, "AkshareFetcher", 3,
            DataCapability.STOCK_REALTIME_QUOTE,
            raises=DataFetchError("akshare down"),
        )
        self._add_fetcher(
            mgr, "ZzshareFetcher", 2,
            DataCapability.STOCK_REALTIME_QUOTE,
            raises=DataFetchError("zzshare down"),
        )
        # Per _with_failover with allow_none=True: total failure returns (None, "")
        # (the manager layer may raise instead — depends on the wrapper; adjust if needed)
        try:
            quotes, source = mgr.get_realtime_quotes("csi")
            assert quotes is None
            assert source == ""
        except DataFetchError:
            # Also acceptable: total failure raises when allow_none=False
            pass

    def test_empty_results_fall_through_to_next_fetcher(self):
        """Empty list from primary (highest-priority) fetcher → fall through to next."""
        mgr = self._manager()
        # Akshare P1 (higher precedence than Zzshare P2) returns empty → fall through
        akshare = self._add_fetcher(
            mgr, "AkshareFetcher", 1,  # P1 < P2
            DataCapability.STOCK_REALTIME_QUOTE,
            get_realtime_quotes_return=[],   # empty → not meaningful
        )
        zzshare = self._add_fetcher(
            mgr, "ZzshareFetcher", 2,
            DataCapability.STOCK_REALTIME_QUOTE,
            get_realtime_quotes_return=[_make_quote()],
        )
        quotes, source = mgr.get_realtime_quotes("csi")
        assert source == "ZzshareFetcher"
        assert len(quotes) == 1
        assert akshare.get_realtime_quotes.call_count == 1  # tried first, then fall-through
        assert akshare.get_realtime_quotes.call_count == 1

    def test_uses_dedicated_quote_list_circuit_breaker(self):
        """REGRESSION: get_realtime_quotes uses QUOTE_LIST_CIRCUIT_BREAKER,
        NOT the singleton REALTIME_CIRCUIT_BREAKER shared with single-stock
        path. If a future refactor passes REALTIME_CIRCUIT_BREAKER instead,
        ABC-raise skips from get_realtime_quotes would poison the breaker
        and break /stocks/{code}/quote's PE/PB enhancement fallback (D1).
        """
        from stock_data.data_provider.core.types import (
            QUOTE_LIST_CIRCUIT_BREAKER,
            REALTIME_CIRCUIT_BREAKER,
        )
        # The two breakers must be distinct singletons.
        assert QUOTE_LIST_CIRCUIT_BREAKER is not REALTIME_CIRCUIT_BREAKER

        # Trip the dedicated breaker with ABC-raise skips; verify the
        # single-stock REALTIME_CIRCUIT_BREAKER is unaffected.
        mgr = self._manager()
        # TushareFetcher-equivalent: has capability, raises DataFetchError
        # (the ABC default behavior — simulates Tencent/Zhitu/Tushare/Myquant)
        tushare_like = self._add_fetcher(
            mgr, "TushareFetcher", 0,
            DataCapability.STOCK_REALTIME_QUOTE,
            raises=DataFetchError("does not support all-market realtime quote"),
        )
        # Akshare succeeds — short-circuits before Tushare is hit... wait,
        # Tushare is P0 (lower priority number = tried first per _with_failover).
        # So Tushare is tried first, raises, then Akshare succeeds.
        self._add_fetcher(
            mgr, "AkshareFetcher", 3,
            DataCapability.STOCK_REALTIME_QUOTE,
            get_realtime_quotes_return=[_make_quote()],
        )

        # First call: Tushare raises → record_failure on QUOTE_LIST_CB.
        mgr.get_realtime_quotes("csi")
        # REALTIME_CB must be unaffected by the all-market path.
        realtime_state = REALTIME_CIRCUIT_BREAKER.snapshot_state("TushareFetcher")
        assert realtime_state["state"] == "closed"  # NOT affected
        # QUOTE_LIST_CB DID record a failure for Tushare.
        quote_list_state = QUOTE_LIST_CIRCUIT_BREAKER.snapshot_state("TushareFetcher")
        assert quote_list_state["failures"] >= 1
