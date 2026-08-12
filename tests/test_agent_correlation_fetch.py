"""Tests for stock/board fetch wrappers."""
from unittest.mock import MagicMock

import pandas as pd
import pytest

from stock_data.api.routes import agent_correlation as ac


@pytest.fixture
def mock_manager():
    mgr = MagicMock()
    return mgr


def _patch_manager(monkeypatch, mgr):
    # Patch the route module's `get_manager` symbol — the fetcher helpers
    # and the route handler both call it. Mirrors test_agent_endpoints.py:706-716.
    monkeypatch.setattr(ac, "get_manager", lambda: mgr)


def test_fetch_stock_series_returns_close_series(monkeypatch, mock_manager):
    df = pd.DataFrame({
        "trade_date": pd.date_range("2026-01-01", periods=5, freq="D"),
        "close":      [100.0, 101.5, 102.0, 99.5, 100.5],
    })
    mock_manager.get_kline_data.return_value = (df, "tushare")
    _patch_manager(monkeypatch, mock_manager)
    s, name, reason = ac._fetch_stock_series("SH600519", days=5, frequency="d")
    assert reason is None
    assert s is not None and len(s) == 5
    assert abs(s.iloc[0] - 100.0) < 1e-9
    # normalize_stock_code canonicalized to bare 6-digit
    called = mock_manager.get_kline_data.call_args.kwargs
    assert called["stock_code"] == "600519"
    assert called["days"] == 5
    assert called["frequency"] == "d"
    # asset="stock" must be passed to disambiguate from index codes
    assert called["asset"] == "stock"


def test_fetch_stock_series_returns_none_on_data_fetch_error(monkeypatch, mock_manager):
    from stock_data.data_provider.base import DataFetchError
    mock_manager.get_kline_data.side_effect = DataFetchError("upstream down")
    _patch_manager(monkeypatch, mock_manager)
    s, name, reason = ac._fetch_stock_series("600519", days=5, frequency="d")
    assert s is None and name is None
    assert reason == "data_unavailable"


def test_fetch_stock_series_returns_none_on_empty_df(monkeypatch, mock_manager):
    mock_manager.get_kline_data.return_value = (pd.DataFrame(), "tushare")
    _patch_manager(monkeypatch, mock_manager)
    s, name, reason = ac._fetch_stock_series("600519", days=5, frequency="d")
    assert s is None and name is None
    assert reason == "empty"


def test_fetch_stock_series_returns_none_on_too_short(monkeypatch, mock_manager):
    # 1 bar → spec §3.4 "fewer than 2 rows" per-item failure
    df = pd.DataFrame({
        "trade_date": pd.date_range("2026-01-01", periods=1, freq="D"),
        "close":      [100.0],
    })
    mock_manager.get_kline_data.return_value = (df, "tushare")
    _patch_manager(monkeypatch, mock_manager)
    s, name, reason = ac._fetch_stock_series("600519", days=5, frequency="d")
    assert s is None and name is None
    assert reason == "too_short"


def test_fetch_board_series_returns_close_series(monkeypatch, mock_manager):
    rows = [
        {"date": "2026-01-01", "close": 1000.0},
        {"date": "2026-01-02", "close": 1010.0},
        {"date": "2026-01-03", "close": 1005.0},
    ]
    mock_manager.get_board_history.return_value = (rows, "ths")
    _patch_manager(monkeypatch, mock_manager)
    s, name, reason = ac._fetch_board_series("885595", "ths", days=3, frequency="d")
    assert reason is None
    assert s is not None and len(s) == 3
    called = mock_manager.get_board_history.call_args.kwargs
    assert called["board_code"] == "885595"
    assert called["source"] == "ths"
    assert called["days"] == 3
    assert called["frequency"] == "d"


def test_fetch_board_series_returns_none_on_data_fetch_error(monkeypatch, mock_manager):
    from stock_data.data_provider.base import DataFetchError
    mock_manager.get_board_history.side_effect = DataFetchError("ths timeout")
    _patch_manager(monkeypatch, mock_manager)
    s, name, reason = ac._fetch_board_series("885595", "ths", days=3, frequency="d")
    assert s is None and name is None
    assert reason == "data_unavailable"
