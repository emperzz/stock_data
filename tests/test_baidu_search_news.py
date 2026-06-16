"""Unit tests for BaiduFetcher.search_news() and gating."""
from unittest.mock import MagicMock

import pytest

from stock_data.data_provider.base import DataFetchError
from stock_data.data_provider.fetchers.baidu_fetcher import BaiduFetcher

# ---------- Availability gating ----------

class TestIsAvailable:
    def test_returns_false_when_api_key_missing(self, monkeypatch):
        monkeypatch.delenv("BAIDU_API_KEY", raising=False)
        fetcher = BaiduFetcher()
        assert fetcher.is_available() is False

    def test_returns_false_when_api_key_empty_string(self, monkeypatch):
        monkeypatch.setenv("BAIDU_API_KEY", "   ")
        fetcher = BaiduFetcher()
        assert fetcher.is_available() is False

    def test_returns_true_when_api_key_set(self, monkeypatch):
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/ALTAK-xxx/yyy")
        fetcher = BaiduFetcher()
        assert fetcher.is_available() is True

    def test_priority_default_is_seven(self, monkeypatch):
        monkeypatch.delenv("BAIDU_PRIORITY", raising=False)
        assert BaiduFetcher.priority == 7

    def test_priority_overridable_via_env(self, monkeypatch):
        monkeypatch.setenv("BAIDU_PRIORITY", "5")
        # Re-import to pick up env var (class attr read at class body time)
        import importlib

        from stock_data.data_provider.fetchers import baidu_fetcher
        importlib.reload(baidu_fetcher)
        assert baidu_fetcher.BaiduFetcher.priority == 5

    def test_unavailable_reason_mentions_env_var(self, monkeypatch):
        monkeypatch.delenv("BAIDU_API_KEY", raising=False)
        fetcher = BaiduFetcher()
        reason = fetcher.unavailable_reason()
        assert reason is not None
        assert "BAIDU_API_KEY" in reason


# ---------- Base method stubs ----------

class TestKLineMethodsRaise:
    def test_fetch_raw_data_raises(self):
        fetcher = BaiduFetcher()
        with pytest.raises(DataFetchError, match="does not support historical K-line"):
            fetcher._fetch_raw_data("600519", "2025-01-01", "2025-01-31")

    def test_normalize_data_raises(self):
        fetcher = BaiduFetcher()
        with pytest.raises(DataFetchError, match="does not support historical K-line"):
            fetcher._normalize_data(MagicMock(), "600519")
