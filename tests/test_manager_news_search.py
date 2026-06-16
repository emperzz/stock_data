"""
Tests for DataFetcherManager.search_news() routing.

Confirms the manager delegates to NEWS_SEARCH-capable fetchers in priority
order and returns (result, source) on the first success.
"""
from unittest.mock import patch

from stock_data.data_provider.fetchers.eastmoney_fetcher import EastMoneyFetcher
from stock_data.data_provider.manager import DataFetcherManager


def _make_manager_with_only_eastmoney():
    mgr = DataFetcherManager()
    mgr.reset()
    mgr.add_fetcher(EastMoneyFetcher())
    return mgr


class TestManagerSearchNews:
    def test_routes_to_eastmoney_when_available(self):
        mgr = _make_manager_with_only_eastmoney()
        expected = [{"title": "fake", "url": "http://x", "publish_date": "2026-06-09"}]
        with patch.object(
            EastMoneyFetcher, "search_news", return_value=expected
        ) as mock_search:
            data, source = mgr.search_news(q="603777", limit=5)

        assert data == expected
        assert source == "EastMoneyFetcher"
        mock_search.assert_called_once_with("603777", None, None, 5)

    def test_propagates_from_to_date(self):
        mgr = _make_manager_with_only_eastmoney()
        with patch.object(
            EastMoneyFetcher, "search_news", return_value=[]
        ) as mock_search:
            mgr.search_news(
                q="603777", from_date="2026-01-01", to_date="2026-06-30", limit=10
            )

        mock_search.assert_called_once_with(
            "603777", "2026-01-01", "2026-06-30", 10
        )

    def test_only_news_search_capable_fetchers_are_consulted(self):
        """A fetcher that does not declare NEWS_SEARCH should not be called."""
        from stock_data.data_provider.fetchers.cninfo_fetcher import CninfoFetcher

        mgr = _make_manager_with_only_eastmoney()
        mgr.add_fetcher(CninfoFetcher())  # CNINFO does not declare NEWS_SEARCH

        with patch.object(
            EastMoneyFetcher, "search_news", return_value=[]
        ) as mock_search:
            mgr.search_news(q="603777")

        # CninfoFetcher was filtered out by _filter_by_capability
        mock_search.assert_called_once()
