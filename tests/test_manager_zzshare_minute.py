"""Manager-level test: verify ZzshareFetcher handles minute K via get_kline_data.

Complements tests/test_zzshare_fetcher.py (unit) by exercising the full
manager.get_kline_data → ZzshareFetcher._fetch_raw_data → stk_mins path.
"""
from unittest.mock import MagicMock

import pandas as pd

from stock_data.data_provider.fetchers.zzshare_fetcher import ZzshareFetcher
from stock_data.data_provider.manager import DataFetcherManager


def _make_manager_with_zzshare_only():
    """Manager with only ZzshareFetcher (mocked as available)."""
    fetcher = ZzshareFetcher()
    fetcher.is_available = lambda: True
    # Patch _ensure_api to return a mock api so we don't need real SDK
    fake_api = MagicMock()
    fetcher._api = fake_api
    mgr = DataFetcherManager()
    mgr.add_fetcher(fetcher)
    return mgr, fake_api


def test_manager_routes_minute_kline_to_zzshare():
    """manager.get_kline_data(frequency="5") → ZzshareFetcher → stk_mins."""
    mgr, fake_api = _make_manager_with_zzshare_only()
    fake_api.stk_mins = MagicMock(return_value=pd.DataFrame({
        "trade_time": ["202605200935", "202605200940"],
        "open": [1700.0, 1705.0], "high": [1708.0, 1712.0],
        "low": [1698.0, 1702.0], "close": [1705.0, 1710.0],
        "vol": [1e5, 1.1e5], "amount": [1e8, 1.1e8],
    }))

    df, source = mgr.get_kline_data(
        "600519", start_date="2026-05-20", end_date="2026-05-20", frequency="5"
    )

    assert source == "ZzshareFetcher"
    assert fake_api.stk_mins.called
    assert "date" in df.columns
    assert len(df) == 2
