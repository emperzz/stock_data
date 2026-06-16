"""Manager-level failover test: when EastMoney raises, manager tries Baidu."""

from unittest.mock import MagicMock, patch

import pytest

from stock_data.data_provider.base import DataFetchError


def _baidu_payload():
    return {
        "request_id": "abc",
        "references": [
            {
                "title": "from baidu",
                "url": "https://finance.eastmoney.com/1.html",
                "content": "snippet",
                "date": "2026-05-20 10:00:00",
            }
        ],
    }


def _mock_post(payload, status=200):
    mock = MagicMock()
    mock.status_code = status
    mock.json.return_value = payload
    mock.text = str(payload)
    return mock


def test_eastmoney_failover_to_baidu(monkeypatch):
    """If EastMoney raises DataFetchError, manager.search_news falls back to BaiduFetcher."""
    monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")

    # EastMoney raises on every search_news call; Baidu returns a normal payload
    with (
        patch(
            "stock_data.data_provider.fetchers.eastmoney_fetcher.EastMoneyFetcher.search_news",
            side_effect=DataFetchError("[EastMoneyFetcher] simulated failure"),
        ),
        patch(
            "stock_data.data_provider.fetchers.baidu_fetcher.requests.post",
            return_value=_mock_post(_baidu_payload()),
        ),
    ):
        # Build a manager with both fetchers
        from stock_data.data_provider import BaiduFetcher, EastMoneyFetcher
        from stock_data.data_provider.manager import DataFetcherManager

        mgr = DataFetcherManager()
        mgr.add_fetcher(EastMoneyFetcher())
        mgr.add_fetcher(BaiduFetcher())

        items, source = mgr.search_news(q="贵州茅台", limit=10)

    assert source == "BaiduFetcher"
    assert len(items) == 1
    assert items[0]["title"] == "from baidu"


def test_eastmoney_success_does_not_invoke_baidu(monkeypatch):
    """If EastMoney returns successfully, Baidu is never called."""
    monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")

    eastmoney_items = [
        {
            "title": "from eastmoney",
            "url": "http://finance.eastmoney.com/a/1.html",
            "source_domain": "finance.eastmoney.com",
            "publish_date": "2026-05-20",
            "snippet": "snippet",
            "media_name": "证券时报网",
        }
    ]
    with (
        patch(
            "stock_data.data_provider.fetchers.eastmoney_fetcher.EastMoneyFetcher.search_news",
            return_value=eastmoney_items,
        ) as em_mock,
        patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post") as baidu_mock,
    ):
        from stock_data.data_provider import BaiduFetcher, EastMoneyFetcher
        from stock_data.data_provider.manager import DataFetcherManager

        mgr = DataFetcherManager()
        mgr.add_fetcher(EastMoneyFetcher())
        mgr.add_fetcher(BaiduFetcher())

        items, source = mgr.search_news(q="贵州茅台", limit=10)

    assert source == "EastMoneyFetcher"
    assert items[0]["title"] == "from eastmoney"
    em_mock.assert_called_once()
    baidu_mock.assert_not_called()


def test_both_fail_yields_data_fetch_error(monkeypatch):
    """If both fetchers fail, manager raises DataFetchError."""
    monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")

    with (
        patch(
            "stock_data.data_provider.fetchers.eastmoney_fetcher.EastMoneyFetcher.search_news",
            side_effect=DataFetchError("em fail"),
        ),
        patch(
            "stock_data.data_provider.fetchers.baidu_fetcher.requests.post",
            side_effect=Exception("network"),
        ),
    ):
        from stock_data.data_provider import BaiduFetcher, EastMoneyFetcher
        from stock_data.data_provider.manager import DataFetcherManager

        mgr = DataFetcherManager()
        mgr.add_fetcher(EastMoneyFetcher())
        mgr.add_fetcher(BaiduFetcher())

        with pytest.raises(DataFetchError):
            mgr.search_news(q="贵州茅台", limit=10)
