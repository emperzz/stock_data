"""Manager-level test: verify ZzshareFetcher handles minute K via get_kline_data.

Complements tests/test_zzshare_fetcher.py (unit) by exercising the full
manager.get_kline_data → ZzshareFetcher._fetch_raw_data → stk_mins path.
"""

from unittest.mock import MagicMock

import pandas as pd

from stock_data.data_provider.fetchers.zzshare_fetcher import ZzshareFetcher
from stock_data.data_provider.manager import DataFetcherManager


def _make_manager_with_zzshare_only():
    """Manager with only ZzshareFetcher (mocked as available).

    Injects fake_api at the CLASS level since init state lives there
    (once-per-process). Skips actual SDK init by setting
    ``_init_attempted=True`` so ``_ensure_api()`` short-circuits.
    """
    fetcher = ZzshareFetcher()
    fetcher.is_available = lambda: True
    fake_api = MagicMock()
    ZzshareFetcher._api = fake_api
    ZzshareFetcher._init_attempted = True
    mgr = DataFetcherManager()
    mgr.add_fetcher(fetcher)
    return mgr, fake_api


def test_manager_routes_one_minute_kline_to_zzshare():
    """manager.get_kline_data(frequency="1") → stk_mins, not daily."""
    mgr, fake_api = _make_manager_with_zzshare_only()
    fake_api.stk_mins = MagicMock(
        return_value=pd.DataFrame(
            {
                "trade_time": ["202607231000", "202607231001"],
                "open": [10.0, 10.1],
                "high": [10.1, 10.2],
                "low": [9.9, 10.0],
                "close": [10.1, 10.2],
                "vol": [1000, 1100],
                "amount": [10000, 11000],
            }
        )
    )

    df, source = mgr.get_kline_data(
        "000001",
        start_date="2026-07-23",
        end_date="2026-07-23",
        frequency="1",
        asset="stock",
    )

    assert source == "ZzshareFetcher"
    assert len(df) == 2
    assert fake_api.stk_mins.called
    assert not fake_api.daily.called
