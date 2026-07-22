"""Tests for the manager-level board F10 wrappers.

Added 2026-07-20 per spec. Validates that manager.get_board_stocks_full,
manager.get_board_news, manager.get_board_surges forward to the right
fetcher method via _with_source (no failover; BOARD_NEWS/BOARD_SURGES
gate at the capability-check step).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from stock_data.data_provider.base import DataCapability
from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher
from stock_data.data_provider.manager import DataFetcherManager


def _build_manager_with_ths(ths_mock) -> DataFetcherManager:
    """Inject a mock ThsFetcher into a fresh manager._fetchers list.

    _with_source dispatches via self._slug_index.get(source.lower()) — by
    pointing the slug index at our mock we make sure the routing finds it.
    """
    ths_mock.name = "ThsFetcher"  # slug-based routing requires name set
    mgr = DataFetcherManager.__new__(DataFetcherManager)
    # Manager init sets up _lock + _slug_index; we replicate just enough.
    from threading import RLock

    mgr._lock = RLock()
    mgr._fetchers = [ths_mock]
    mgr._slug_index = {"ths": ths_mock}
    return mgr


def test_manager_get_board_news_forwards_to_ths():
    fake = MagicMock(spec=ThsFetcher)
    fake.supported_markets = {"csi"}
    fake.supported_data_types = DataCapability.BOARD_NEWS | DataCapability.STOCK_BOARD
    fake.get_board_news.return_value = [{"title": "x"}]

    mgr = _build_manager_with_ths(fake)
    rows, source = mgr.get_board_news("885914", "ths", limit=20)
    assert source == "ThsFetcher"
    fake.get_board_news.assert_called_once()
    assert rows == [{"title": "x"}]


def test_manager_get_board_surges_forwards_to_ths():
    fake = MagicMock(spec=ThsFetcher)
    fake.supported_markets = {"csi"}
    fake.supported_data_types = DataCapability.BOARD_SURGES
    fake.get_board_surges.return_value = [{"date": "2026-07-14"}]

    mgr = _build_manager_with_ths(fake)
    rows, source = mgr.get_board_surges("885914", "ths", limit=5)
    assert source == "ThsFetcher"
    fake.get_board_surges.assert_called_once()
    assert rows == [{"date": "2026-07-14"}]


def test_manager_get_board_stocks_full_forwards_to_ths():
    fake = MagicMock(spec=ThsFetcher)
    fake.supported_markets = {"csi"}
    fake.supported_data_types = DataCapability.STOCK_BOARD
    fake.get_board_stocks_full.return_value = [{"stock_code": "600227"}]

    mgr = _build_manager_with_ths(fake)
    rows, source = mgr.get_board_stocks_full("885914", "ths")
    assert source == "ThsFetcher"
    fake.get_board_stocks_full.assert_called_once()
    assert rows == [{"stock_code": "600227"}]


def test_manager_get_board_news_board_type_plumbed_through():
    fake = MagicMock(spec=ThsFetcher)
    fake.supported_markets = {"csi"}
    fake.supported_data_types = DataCapability.BOARD_NEWS
    fake.get_board_news.return_value = []

    mgr = _build_manager_with_ths(fake)
    mgr.get_board_news("881101", "ths", limit=10, board_type="industry")
    fake.get_board_news.assert_called_once_with("881101", limit=10, board_type="industry")


def test_manager_raises_valueerror_when_fetcher_lacks_capability():
    """Capability-flag check — fetcher without BOARD_NEWS → ValueError."""
    fake = MagicMock(spec=ThsFetcher)
    fake.supported_markets = {"csi"}
    fake.supported_data_types = DataCapability.STOCK_BOARD  # no BOARD_NEWS
    fake.get_board_news = MagicMock()
    mgr = _build_manager_with_ths(fake)

    with pytest.raises(ValueError, match="does not declare capability"):
        mgr.get_board_news("885914", "ths", limit=20)
    fake.get_board_news.assert_not_called()
