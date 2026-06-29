"""Zhitu minute-K regression guard.

Verifies that Zhitu's supports_kline() override correctly:
- Returns True for minute frequencies (Zhitu has minute K via its SDK)
- Returns False for daily (Zhitu has no daily K-line)
"""

from stock_data.data_provider.fetchers.zhitu_fetcher import ZhituFetcher


def test_zhitu_supports_minute_k_returns_true():
    """Zhitu.supports_kline('5', '', 'csi', 'stock') should be True."""
    f = ZhituFetcher.__new__(ZhituFetcher)
    f.supported_markets = ZhituFetcher.supported_markets
    assert f.supports_kline("5", "", "csi", "stock") is True


def test_zhitu_supports_daily_k_returns_false():
    """Zhitu.supports_kline('d', '', 'csi', 'stock') should be False."""
    f = ZhituFetcher.__new__(ZhituFetcher)
    f.supported_markets = ZhituFetcher.supported_markets
    assert f.supports_kline("d", "", "csi", "stock") is False
