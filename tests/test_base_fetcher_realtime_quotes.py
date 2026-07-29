"""Verify the default ABC behavior for get_realtime_quotes."""

import pytest

from stock_data.data_provider.base import BaseFetcher, DataFetchError


class _MinimalFetcher(BaseFetcher):
    """Subclass that does not override get_realtime_quotes."""
    name = "MinimalFetcher"
    priority = 99

    def _normalize_data(self, df, stock_code):
        # Trivial stub: BaseFetcher._normalize_data is @abstractmethod; the
        # _MinimalFetcher only needs to be instantiable so get_realtime_quotes
        # can be exercised. This stub is never called in these tests.
        return df


class TestBaseFetcherGetRealtimeQuotesDefault:
    def test_default_raises_data_fetch_error(self):
        fetcher = _MinimalFetcher()
        with pytest.raises(DataFetchError, match="does not support all-market realtime quote"):
            fetcher.get_realtime_quotes("csi")

    def test_default_market_tag_independent(self):
        """The default raise fires regardless of market arg."""
        fetcher = _MinimalFetcher()
        for m in ("csi", "hk", "us", "cn", "unknown"):
            with pytest.raises(DataFetchError):
                fetcher.get_realtime_quotes(m)
