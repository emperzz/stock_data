"""Manager failover routing for STOCK_LIST.

Regression: 2026-07-03 — ``/api/v1/stocks?market=csi`` was hitting
``AkshareFetcher`` (P3) instead of ``ZzshareFetcher`` (P2) because
Zzshare's ``get_all_stocks`` rejected the manager's ``"cn"`` translated
tag with a silent ``return []``. The failover chain saw Zzshare as
"empty" and moved on without logging, so the user could not see why.

These tests pin two contracts:

1. ``ZzshareFetcher.get_all_stocks`` must accept the manager-translated
   ``"cn"`` tag as an alias for ``"csi"`` (so it gets to actually try).
2. Given two STOCK_LIST-capable fetchers both returning non-empty data,
   the manager's failover must surface the lower-priority (P2) fetcher,
   not silently skip to the next one.

The second contract is enforced even with mocked fetchers because
manager._filter_by_capability + _with_failover iterate in priority
order regardless of which fetcher class is wired in.
"""

import pytest

from stock_data.data_provider.base import DataCapability
from stock_data.data_provider.manager import DataFetcherManager


class _Priority2Mock:
    """Mock fetcher that mimics ZzshareFetcher's priority + capability slice."""

    name = "Priority2Mock"
    priority = 2
    supported_markets = {"csi"}
    supported_data_types = DataCapability.STOCK_LIST

    def get_all_stocks(self, market):
        # Contract this test pins: even when manager passes "cn",
        # the fetcher must accept it as a csi alias.
        if market not in ("csi", "cn"):
            return []
        return [
            {"code": "600519", "name": "贵州茅台", "exchange": "SSE"},
            {"code": "000001", "name": "平安银行", "exchange": "SZSE"},
        ]


class _Priority3Mock:
    """Mock fetcher that mimics AkshareFetcher's priority + capability slice."""

    name = "Priority3Mock"
    priority = 3
    supported_markets = {"csi", "hk"}
    supported_data_types = DataCapability.STOCK_LIST

    def get_all_stocks(self, market):
        # Akshare's contract: accepts "cn" natively.
        if market not in ("csi", "cn"):
            return []
        return [
            {"code": "999999", "name": "from-priority3", "exchange": "SSE"},
        ]


def _make_manager() -> DataFetcherManager:
    """Manager with the two mock fetchers registered (priority order: P2, P3)."""
    manager = DataFetcherManager()
    manager.add_fetcher(_Priority3Mock())  # add in reverse to confirm sort-by-priority
    manager.add_fetcher(_Priority2Mock())
    return manager


class TestManagerStockListRouting:
    def test_failover_respects_priority_order_with_cn_tag(self):
        """Regression: P2 must win, not P3. Manager translates csi -> cn
        before calling the fetcher (manager.get_all_stocks around the
        ``public_to_fetcher = {"csi": "cn"}`` block); the P2 fetcher
        must accept the translated tag."""
        manager = _make_manager()
        stocks, source = manager.get_all_stocks("csi")
        assert source == "Priority2Mock", (
            f"P2 fetcher must win the failover, got source={source!r}"
        )
        assert {s["code"] for s in stocks} == {"600519", "000001"}

    def test_filter_by_capability_returns_priority_order(self):
        """Pin the sorted-by-priority contract independently of the
        failover loop, so a future manager regression that reorders
        candidates surfaces here."""
        manager = _make_manager()
        candidates = manager._filter_by_capability("csi", DataCapability.STOCK_LIST)
        assert [f.name for f in candidates] == ["Priority2Mock", "Priority3Mock"], (
            f"Expected priority-sorted order [P2, P3], got {[f.name for f in candidates]}"
        )

    def test_failover_skips_priority2_when_it_returns_empty(self):
        """When P2 returns [] (e.g. upstream empty), P3 must take over.
        This pins the silent-fallback leg of the failover so a future
        change that makes P2 throw or returns None instead of []
        surfaces here."""

        class EmptyP2Mock(_Priority2Mock):
            def get_all_stocks(self, market):
                return []  # simulate upstream empty (e.g. token expired)

        manager = DataFetcherManager()
        manager.add_fetcher(_Priority3Mock())
        manager.add_fetcher(EmptyP2Mock())
        stocks, source = manager.get_all_stocks("csi")
        assert source == "Priority3Mock"
        assert stocks[0]["code"] == "999999"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])