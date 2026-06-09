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
