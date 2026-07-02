"""
Tests for DataFetcherManager.get_flash_news() routing.

确认 manager 把 get_flash_news 委托给声明 NEWS_FLASH capability 的 fetcher,
按优先级返回 (result, source)。
"""
from unittest.mock import patch

import pytest

from stock_data.data_provider.base import DataFetchError
from stock_data.data_provider.fetchers.eastmoney_fetcher import EastMoneyFetcher
from stock_data.data_provider.manager import DataFetcherManager


def _make_manager_with_only_eastmoney():
    mgr = DataFetcherManager()
    mgr.reset()
    mgr.add_fetcher(EastMoneyFetcher())
    return mgr


class TestManagerFlashNews:
    def test_routes_to_eastmoney_when_available(self):
        mgr = _make_manager_with_only_eastmoney()
        expected = [
            {"title": "fake", "url": "http://x", "publish_time": "2026-06-22 16:00:00"}
        ]
        with patch.object(
            EastMoneyFetcher, "fetch_flash_news", return_value=expected
        ) as mock_fetch:
            data, source = mgr.get_flash_news(limit=50)

        assert data == expected
        assert source == "EastMoneyFetcher"
        mock_fetch.assert_called_once_with(50)

    def test_propagates_limit(self):
        mgr = _make_manager_with_only_eastmoney()
        with patch.object(
            EastMoneyFetcher, "fetch_flash_news", return_value=[{"title": "fake"}]
        ) as mock_fetch:
            mgr.get_flash_news(limit=200)

        mock_fetch.assert_called_once_with(200)

    def test_only_news_flash_capable_fetchers_are_consulted(self):
        """不声明 NEWS_FLASH 的 fetcher 不应被调用。"""
        from stock_data.data_provider.fetchers.cninfo_fetcher import CninfoFetcher

        mgr = _make_manager_with_only_eastmoney()
        mgr.add_fetcher(CninfoFetcher())  # CNINFO 不声明 NEWS_FLASH

        with patch.object(
            EastMoneyFetcher, "fetch_flash_news", return_value=[{"title": "fake"}]
        ) as mock_fetch:
            mgr.get_flash_news(limit=10)

        # CninfoFetcher 被 _filter_by_capability 过滤掉
        mock_fetch.assert_called_once()

    def test_raises_when_all_fetchers_fail(self):
        mgr = _make_manager_with_only_eastmoney()
        with patch.object(
            EastMoneyFetcher, "fetch_flash_news",
            side_effect=Exception("upstream broken"),
        ), pytest.raises(DataFetchError, match="All fetchers failed"):
            mgr.get_flash_news(limit=10)


# -----------------------------------------------------------------------------
# EastMoney (P6) → ThsFetcher (P7) failover
# -----------------------------------------------------------------------------


class TestFlashNewsFailover:
    """When EastMoneyFetcher raises, the manager should fall back to ThsFetcher."""

    def _mgr(self):
        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher
        self._ThsFetcher = ThsFetcher

        mgr = DataFetcherManager()
        mgr.reset()
        mgr.add_fetcher(EastMoneyFetcher())  # priority 6
        mgr.add_fetcher(ThsFetcher())        # priority 7
        return mgr

    def test_eastmoney_succeeds_no_failover(self):
        """Happy path: EastMoney returns, ThsFetcher never called."""
        mgr = self._mgr()
        ths_fetcher = self._ThsFetcher
        with patch.object(
            EastMoneyFetcher, "fetch_flash_news",
            return_value=[{"title": "from em"}],
        ) as em, patch.object(
            ths_fetcher, "fetch_flash_news",
        ) as ths:
            data, source = mgr.get_flash_news(limit=20)

        assert data == [{"title": "from em"}]
        assert source == "EastMoneyFetcher"
        em.assert_called_once_with(20)
        ths.assert_not_called()

    def test_eastmoney_raises_falls_back_to_ths(self):
        """EastMoney raises → ThsFetcher is called next."""
        mgr = self._mgr()
        ths_fetcher = self._ThsFetcher
        with patch.object(
            EastMoneyFetcher, "fetch_flash_news",
            side_effect=Exception("em broken"),
        ), patch.object(
            ths_fetcher, "fetch_flash_news",
            return_value=[{"title": "from ths"}],
        ) as ths:
            data, source = mgr.get_flash_news(limit=20)

        assert data == [{"title": "from ths"}]
        assert source == "ThsFetcher"
        ths.assert_called_once_with(20)

    def test_eastmoney_returns_empty_falls_back_to_ths(self):
        """EastMoney returns [] (e.g. upstream 0 items) → ThsFetcher tried next.

        _is_meaningful treats [] as 'no data', so failover continues.
        """
        mgr = self._mgr()
        ths_fetcher = self._ThsFetcher
        with patch.object(
            EastMoneyFetcher, "fetch_flash_news", return_value=[],
        ), patch.object(
            ths_fetcher, "fetch_flash_news",
            return_value=[{"title": "from ths"}],
        ) as ths:
            data, source = mgr.get_flash_news(limit=20)

        assert source == "ThsFetcher"
        ths.assert_called_once_with(20)

    def test_both_fail_raises(self):
        """Both fetchers raise → DataFetchError, source empty."""
        mgr = self._mgr()
        ths_fetcher = self._ThsFetcher
        with patch.object(EastMoneyFetcher, "fetch_flash_news", side_effect=Exception("em")), \
             patch.object(ths_fetcher, "fetch_flash_news", side_effect=Exception("ths")), \
             pytest.raises(DataFetchError, match="All fetchers failed"):
            mgr.get_flash_news(limit=20)
