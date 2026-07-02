"""Test: EastMoneyFetcher is now in the ANNOUNCEMENT failover chain.

Verifies that adding ``DataCapability.ANNOUNCEMENT`` to
``EastMoneyFetcher.supported_data_types`` (Task 7) wires the eastmoney
source into the existing ``Manager.get_announcements`` failover chain
alongside ``CninfoFetcher``.

The method on EastMoneyFetcher is ``get_announcements`` (renamed from
``get_stock_announcements`` in Task 7 to match the manager's failover
lambda and CninfoFetcher's method name), so the existing
``_with_failover(DataCapability.ANNOUNCEMENT, "csi", ..., lambda f:
f.get_announcements(code, page_size))`` picks it up automatically once
the capability flag is declared.
"""
from unittest.mock import patch

import pytest

from stock_data.data_provider.base import (
    CAPABILITY_TO_METHOD,
    DataCapability,
)
from stock_data.data_provider.fetchers.eastmoney_fetcher import EastMoneyFetcher
from stock_data.data_provider.manager import (
    DataFetcherManager,
    create_default_manager,
)


def _make_manager() -> DataFetcherManager:
    """Build a manager with all available fetchers registered.

    Mirrors the helper used in ``test_manager_stock_news.py`` — using
    ``create_default_manager()`` (not ``DataFetcherManager()``) ensures
    these tests see the same routing population the server uses.
    """
    return create_default_manager()


def test_eastmoney_declares_announcement_capability():
    """EastMoneyFetcher.supported_data_types must include ANNOUNCEMENT."""
    assert DataCapability.ANNOUNCEMENT in EastMoneyFetcher.supported_data_types


def test_capability_to_method_maps_announcement():
    """CAPABILITY_TO_METHOD['ANNOUNCEMENT'] must be 'get_announcements'.

    Pre-existing entry (set when CninfoFetcher was the sole ANNOUNCEMENT
    source). Pinning it here as a regression guard: a future refactor
    that renames the method MUST update both ``base.py`` and the
    manager's lambda at manager.py:887-892 together.
    """
    assert CAPABILITY_TO_METHOD.get(DataCapability.ANNOUNCEMENT) == "get_announcements"


def test_eastmoney_in_announcement_failover():
    """create_default_manager()'s announcement failover must include EastMoneyFetcher."""
    mgr = _make_manager()
    fetchers = mgr._filter_by_capability("csi", DataCapability.ANNOUNCEMENT)
    names = [f.name for f in fetchers]
    assert "EastMoneyFetcher" in names, (
        f"EastMoneyFetcher missing from ANNOUNCEMENT-capable fetchers: {names}"
    )


def test_manager_get_announcements_routes_via_failover():
    """DataFetcherManager.get_announcements should now reach EastMoneyFetcher.

    EastMoney has priority 6 (default), Cninfo has priority 8; so the
    failover will try EastMoney first and (when it succeeds) return
    ``source == 'EastMoneyFetcher'``. The exact source depends on
    priority ordering and is non-deterministic across env overrides;
    here we just verify EastMoney is reachable through the failover
    by patching its ``get_announcements`` method on the registered
    instance and confirming the manager routes to it.
    """
    mgr = _make_manager()
    fetchers = mgr._filter_by_capability("csi", DataCapability.ANNOUNCEMENT)
    if "EastMoneyFetcher" not in [f.name for f in fetchers]:
        pytest.skip("EastMoneyFetcher not registered (env-dependent)")

    target = next(f for f in fetchers if f.name == "EastMoneyFetcher")
    fake_items = [
        {
            "title": "贵州茅台:关于...",
            "type": "A,SHA",
            "date": "2026-07-02",
            "url": "http://example.com/notices/detail/600519/AN123.html",
        }
    ]
    with patch.object(target, "get_announcements", return_value=fake_items) as patched:
        items, source = mgr.get_announcements("600519", page_size=10)

    # Resulting list is whatever the patched method returned.
    assert items == fake_items
    # Source identifies which fetcher served the request. EastMoney (P6)
    # is higher priority than Cninfo (P8), so on a healthy manager the
    # patched eastmoney is reached and the source is "EastMoneyFetcher".
    assert source == "EastMoneyFetcher"
    # The patched method was called exactly once with the routed kwargs.
    patched.assert_called_once_with("600519", 10)


def test_eastmoney_announcements_method_signature_compatible():
    """Manager's lambda calls ``get_announcements(code, page_size)``.

    EastMoneyFetcher.get_announcements must accept these two positional
    args (plus optional ``page_index``) — guards against future refactors
    that change the signature and silently break the failover.
    """
    import inspect

    sig = inspect.signature(EastMoneyFetcher.get_announcements)
    # Drop ``self`` so we compare only the public-facing positional args.
    params = [name for name in sig.parameters if name != "self"]
    assert params[:2] == ["code", "page_size"], (
        f"First two params must be (code, page_size); got {params[:2]}"
    )
