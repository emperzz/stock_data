"""Tests for DataFetcherManager.get_stock_news routing."""
from unittest.mock import patch

import pytest

from stock_data.data_provider.base import DataCapability
from stock_data.data_provider.manager import (
    DataFetcherManager,
    create_default_manager,
)


def _make_manager() -> DataFetcherManager:
    """Build a manager with all available fetchers registered.

    ``create_default_manager()`` is the production entry point that
    instantiates each fetcher and registers it iff ``is_available()``
    returns True. Using it (instead of ``DataFetcherManager()``) ensures
    these tests see the same routing population the server uses.
    """
    return create_default_manager()


def test_eastmoney_in_stock_news_capability():
    """EastMoneyFetcher should declare STOCK_NEWS capability."""
    mgr = _make_manager()
    fetchers = mgr._filter_by_capability("csi", DataCapability.STOCK_NEWS)
    names = [f.name for f in fetchers]
    assert "EastMoneyFetcher" in names, (
        f"EastMoneyFetcher missing from STOCK_NEWS-capable fetchers: {names}"
    )


def test_get_stock_news_routes_to_eastmoney():
    """get_stock_news should call EastMoneyFetcher.get_stock_news."""
    mgr = _make_manager()
    fetchers = mgr._filter_by_capability("csi", DataCapability.STOCK_NEWS)
    if not fetchers:
        pytest.skip("No STOCK_NEWS-capable fetcher registered")
    target = next(f for f in fetchers if f.name == "EastMoneyFetcher")
    fake_items = [{"title": "t", "url": "http://x", "publish_date": "2026-07-02",
                   "source_domain": "x.com", "media_name": "X"}]
    with patch.object(target, "get_stock_news", return_value=fake_items) as patched:
        items, source = mgr.get_stock_news("600519", limit=10)
    assert items == fake_items
    assert source == "EastMoneyFetcher"
    patched.assert_called_once_with("600519", 10)


def test_capability_method_map_includes_stock_news():
    """CAPABILITY_TO_METHOD must include STOCK_NEWS (anti-pattern check)."""
    from stock_data.data_provider.base import CAPABILITY_TO_METHOD, DataCapability
    assert DataCapability.STOCK_NEWS in CAPABILITY_TO_METHOD
    assert CAPABILITY_TO_METHOD[DataCapability.STOCK_NEWS] == "get_stock_news"
