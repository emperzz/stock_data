"""
Unit tests for ThsFetcher.
"""
from unittest.mock import MagicMock, patch

import pytest

from stock_data.data_provider.base import DataCapability
from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher


class TestThsFetcherBasics:
    def test_name(self):
        f = ThsFetcher()
        assert f.name == "ThsFetcher"

    def test_priority(self):
        f = ThsFetcher()
        assert f.priority == 7

    def test_is_available(self):
        f = ThsFetcher()
        assert f.is_available() is True

    def test_capabilities(self):
        f = ThsFetcher()
        assert DataCapability.HOT_TOPICS in f.supported_data_types
        assert DataCapability.NORTH_FLOW in f.supported_data_types


class TestHotTopics:
    def setup_method(self):
        self.fetcher = ThsFetcher()

    def test_normalize_hot_topic(self):
        row = {
            "code": "600519", "name": "Test", "reason": "白酒+消费",
            "zhangfu": 5.5, "huanshou": 2.1, "chengjiaoliang": 50000,
            "chengjiaoe": 1000000, "ddejingliang": 100,
        }
        result = self.fetcher._normalize_hot_topic(row)
        assert result["code"] == "600519"
        assert result["reason"] == "白酒+消费"
        assert result["change_pct"] == 5.5
        assert result["turnover_rate"] == 2.1


class TestNorthFlow:
    def setup_method(self):
        self.fetcher = ThsFetcher()

    @patch("stock_data.data_provider.fetchers.ths_fetcher.requests.get")
    def test_returns_records(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "time": ["09:30", "09:31"],
            "hgt": [0.5, 0.7],
            "sgt": [0.3, None],
        }
        mock_get.return_value = mock_response
        result = self.fetcher.get_north_flow()
        assert len(result) == 2
        assert result[0]["hgt_yi"] == 0.5
        assert result[1]["sgt_yi"] is None


class TestHistoricalNotSupported:
    def test_fetch_raw_data_raises(self):
        from stock_data.data_provider.base import DataFetchError
        f = ThsFetcher()
        with pytest.raises(DataFetchError):
            f._fetch_raw_data("600519", "2026-01-01", "2026-05-01")

    def test_normalize_data_raises(self):
        import pandas as pd

        from stock_data.data_provider.base import DataFetchError
        f = ThsFetcher()
        with pytest.raises(DataFetchError):
            f._normalize_data(pd.DataFrame(), "600519")


class TestFetchFlashNewsNormalize:
    """Tests for the pure normalize helper (no network)."""

    def setup_method(self):
        self.fetcher = ThsFetcher()

    def test_normalize_flash_item_full(self):
        from datetime import datetime
        item = {
            "id": "4572951",
            "seq": "677638595",
            "title": "南向资金成交额超 1.7 万亿港元",
            "digest": "南向资金成交额超 1.7 万亿港元。",
            "url": "https://news.10jqka.com.cn/20260623/c677638595.shtml",
            "rtime": "1782181568",
        }
        result = self.fetcher._normalize_flash_item(item)
        assert result["title"] == "南向资金成交额超 1.7 万亿港元"
        assert result["url"] == "https://news.10jqka.com.cn/20260623/c677638595.shtml"
        assert result["source_domain"] == "news.10jqka.com.cn"
        # rtime=1782181568 → 2026-06-22 16:26:08 UTC (local tz may differ; verify just structure)
        assert result["publish_time"].startswith("2026-")
        assert len(result["publish_time"]) == 19  # "YYYY-MM-DD HH:MM:SS"
        assert result["snippet"] == "南向资金成交额超 1.7 万亿港元。"

    def test_normalize_flash_item_missing_optional(self):
        """Defensive: missing digest/rtime should still produce a row."""
        item = {
            "id": "1",
            "title": "标题",
            "url": "https://news.10jqka.com.cn/20260101/c1.shtml",
            # no rtime, no digest
        }
        result = self.fetcher._normalize_flash_item(item)
        assert result["title"] == "标题"
        assert result["url"] == "https://news.10jqka.com.cn/20260101/c1.shtml"
        assert result["source_domain"] == "news.10jqka.com.cn"
        assert result["publish_time"] == ""  # empty fallback
        assert result["snippet"] == ""  # empty fallback

    def test_normalize_flash_item_bad_rtime_keeps_raw(self):
        """If rtime is not a valid int, fall back to the raw string."""
        item = {
            "id": "2",
            "title": "t",
            "url": "https://news.10jqka.com.cn/x",
            "rtime": "not-a-number",
        }
        result = self.fetcher._normalize_flash_item(item)
        assert result["publish_time"] == "not-a-number"  # graceful fallback
