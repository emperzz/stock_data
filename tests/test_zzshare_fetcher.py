"""Unit tests for ZzshareFetcher — structural + per-capability.

All tests mock the DataApi SDK (no real network/token).
"""
import importlib
import os
from unittest.mock import MagicMock, patch

import pytest

from stock_data.data_provider.base import DataCapability, DataFetchError
from stock_data.data_provider.fetchers.zzshare_fetcher import ZzshareFetcher


# ====================================================================
# Metadata + availability
# ====================================================================

class TestZzshareFetcherMetadata:
    def test_name(self):
        assert ZzshareFetcher.name == "ZzshareFetcher"

    def test_priority_default(self, monkeypatch):
        monkeypatch.delenv("ZZSHARE_PRIORITY", raising=False)
        assert ZzshareFetcher.priority == 5

    def test_priority_env_override(self, monkeypatch):
        monkeypatch.setenv("ZZSHARE_PRIORITY", "3")
        from stock_data.data_provider.fetchers import zzshare_fetcher
        importlib.reload(zzshare_fetcher)
        try:
            assert zzshare_fetcher.ZzshareFetcher.priority == 3
        finally:
            monkeypatch.delenv("ZZSHARE_PRIORITY", raising=False)
            importlib.reload(zzshare_fetcher)

    def test_supported_markets(self):
        assert ZzshareFetcher.supported_markets == {"csi"}

    def test_supported_data_types_all_10_caps(self):
        expected = {
            DataCapability.HISTORICAL_DWM,
            DataCapability.HISTORICAL_MIN,
            DataCapability.REALTIME_QUOTE,
            DataCapability.STOCK_LIST,
            DataCapability.TRADE_CALENDAR,
            DataCapability.STOCK_BOARD,
            DataCapability.STOCK_ZT_POOL,
            DataCapability.DRAGON_TIGER,
            DataCapability.HOT_TOPICS,
            DataCapability.STOCK_INFO,
        }
        # supported_data_types is a DataCapability Flag enum value; check membership
        for cap in expected:
            assert cap in ZzshareFetcher.supported_data_types


class TestZzshareFetcherAvailability:
    def test_is_available_false_when_sdk_missing(self, monkeypatch):
        monkeypatch.delenv("ZZSHARE_TOKEN", raising=False)
        with patch("importlib.util.find_spec", return_value=None):
            fetcher = ZzshareFetcher()
            assert fetcher.is_available() is False

    def test_is_available_true_when_sdk_present_no_token(self, monkeypatch):
        monkeypatch.delenv("ZZSHARE_TOKEN", raising=False)
        with patch("importlib.util.find_spec", return_value=MagicMock()):
            fetcher = ZzshareFetcher()
            assert fetcher.is_available() is True

    def test_is_available_true_when_sdk_and_token(self, monkeypatch):
        monkeypatch.setenv("ZZSHARE_TOKEN", "test-token-123")
        with patch("importlib.util.find_spec", return_value=MagicMock()):
            fetcher = ZzshareFetcher()
            assert fetcher.is_available() is True

    def test_unavailable_reason_mentions_sdk_when_missing(self, monkeypatch):
        monkeypatch.delenv("ZZSHARE_TOKEN", raising=False)
        with patch("importlib.util.find_spec", return_value=None):
            fetcher = ZzshareFetcher()
            reason = fetcher.unavailable_reason()
            assert reason is not None
            assert "DataApi" in reason or "SDK" in reason


class TestKLineMethodsRaise:
    def test_fetch_raw_data_raises_for_unsupported_freq(self):
        fetcher = ZzshareFetcher()
        with pytest.raises(DataFetchError, match="不支持.*周.*月"):
            fetcher._fetch_raw_data("600519", "2026-05-01", "2026-05-31", frequency="w")

    def test_fetch_raw_data_raises_for_unsupported_freq_monthly(self):
        fetcher = ZzshareFetcher()
        with pytest.raises(DataFetchError, match="不支持.*周.*月"):
            fetcher._fetch_raw_data("600519", "2026-05-01", "2026-05-31", frequency="m")
