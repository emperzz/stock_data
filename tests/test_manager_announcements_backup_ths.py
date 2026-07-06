"""Tests for /stocks/{code}/announcements failover: EastMoney → Ths → Cninfo."""

from unittest.mock import patch

import pytest

from stock_data.data_provider.base import DataCapability, DataFetchError
from stock_data.data_provider.manager import create_default_manager


def _make_manager():
    return create_default_manager()


def test_ths_declares_announcement_capability():
    """ThsFetcher.supported_data_types must include ANNOUNCEMENT."""
    from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

    assert DataCapability.ANNOUNCEMENT in ThsFetcher.supported_data_types


def test_announcement_priority_order_eastmoney_ths_cninfo():
    """Failover chain should be EastMoney(P6) → Ths(P7) → Cninfo(P8).

    List is sorted by priority ascending (lower = earlier). THS P7 must
    sit between EastMoney P6 and Cninfo P8.
    """
    mgr = _make_manager()
    candidates = mgr._filter_by_capability("csi", DataCapability.ANNOUNCEMENT)
    by_name = {f.name: f.priority for f in candidates}
    assert "ThsFetcher" in by_name, (
        f"ThsFetcher missing from ANNOUNCEMENT candidates: {list(by_name)}"
    )
    if "EastMoneyFetcher" in by_name and "CninfoFetcher" in by_name:
        assert by_name["EastMoneyFetcher"] < by_name["ThsFetcher"] < by_name["CninfoFetcher"], (
            f"Priority order wrong: {by_name}"
        )


def test_get_announcements_falls_back_from_eastmoney_to_ths():
    """When EastMoney raises DataFetchError, manager should try Ths next."""
    mgr = _make_manager()
    fetchers = mgr._filter_by_capability("csi", DataCapability.ANNOUNCEMENT)
    by_name = {f.name: f for f in fetchers}
    if "EastMoneyFetcher" not in by_name or "ThsFetcher" not in by_name:
        pytest.skip("EastMoneyFetcher or ThsFetcher missing — env issue")
    eastmoney = by_name["EastMoneyFetcher"]
    ths = by_name["ThsFetcher"]
    fake_items = [
        {
            "title": "ths-t",
            "type": "",
            "date": "2026-07-02",
            "url": "http://x",
            "raw_url": "http://pdf",
        }
    ]
    with (
        patch.object(eastmoney, "get_announcements", side_effect=DataFetchError("EM down")),
        patch.object(ths, "get_announcements", return_value=fake_items) as ths_patched,
    ):
        items, source = mgr.get_announcements("300740", page_size=10)
    assert items == fake_items
    assert source == "ThsFetcher"
    ths_patched.assert_called_once_with("300740", 10)


def test_get_announcements_falls_back_eastmoney_ths_then_cninfo():
    """Both EastMoney and Ths raising → Cninfo gets the call."""
    mgr = _make_manager()
    fetchers = mgr._filter_by_capability("csi", DataCapability.ANNOUNCEMENT)
    by_name = {f.name: f for f in fetchers}
    if not {"EastMoneyFetcher", "ThsFetcher", "CninfoFetcher"}.issubset(by_name):
        pytest.skip("Need all three fetchers in env")
    cninfo = by_name["CninfoFetcher"]
    fake_items = [{"title": "cninfo-t", "type": "公告", "date": "2026-07-02", "url": "http://y"}]
    with (
        patch.object(
            by_name["EastMoneyFetcher"], "get_announcements", side_effect=DataFetchError("EM down")
        ),
        patch.object(
            by_name["ThsFetcher"], "get_announcements", side_effect=DataFetchError("THS down")
        ),
        patch.object(cninfo, "get_announcements", return_value=fake_items) as cninfo_patched,
    ):
        items, source = mgr.get_announcements("300740", page_size=10)
    assert items == fake_items
    assert source == "CninfoFetcher"
    cninfo_patched.assert_called_once_with("300740", 10)


def test_get_announcements_empty_chain_returns_empty_list_not_misleading_error():
    """Regression (review 2026-07-06 finding #6): when EVERY fetcher in the
    chain returns [] (no exceptions, just empty data), the manager must NOT
    raise ``DataFetchError("All fetchers failed for announcements ...:")``
    with an empty errors list — that's a misleading 5xx for what's actually
    "no data found across all sources". The contract should be: empty chain
    returns ``([], "")`` so the route can serve a normal empty list to
    clients.
    """
    from stock_data.data_provider.base import DataFetchError

    mgr = _make_manager()
    fetchers = mgr._filter_by_capability("csi", DataCapability.ANNOUNCEMENT)
    if not fetchers:
        pytest.skip("No ANNOUNCEMENT-capable fetcher registered")

    # Patch every candidate to return [] — no exceptions, just empty data.
    patches = [
        patch.object(f, "get_announcements", return_value=[]) for f in fetchers
    ]
    from contextlib import ExitStack

    with ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        # Should NOT raise. Should return ([], "") so route serves empty list.
        items, source = mgr.get_announcements("300740", page_size=10)
    assert items == []
    assert source == "", (
        f"empty-chain source should be '' (no fetcher succeeded), got {source!r}"
    )
