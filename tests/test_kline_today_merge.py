"""Tests for routes/_maybe_merge_today_bar helper.

See docs/kline-today-bar-merge-spec-2026-07-24.md §4 for the decision matrix.
"""

from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from stock_data.api.routes.helpers import _maybe_merge_today_bar
from stock_data.data_provider.core.types import UnifiedRealtimeQuote

TODAY = date.today().isoformat()
YESTERDAY = date.fromordinal(date.today().toordinal() - 1).isoformat()
TOMORROW = date.fromordinal(date.today().toordinal() + 1).isoformat()


def _make_df(end_date: str, n: int = 1) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "date": end_date,
                "open": 10.0,
                "high": 11.0,
                "low": 9.5,
                "close": 10.5,
                "volume": 1000,
                "amount": 10500.0,
                "pct_chg": 1.5,
            }
        ]
        * n
    )


def _quote(**kw) -> UnifiedRealtimeQuote:
    base = {
        "code": "600519",
        "name": "",
        "price": 10.8,
        "open_price": 10.5,
        "high": 10.9,
        "low": 10.4,
        "volume": 500,
        "amount": 5400.0,
        "change_pct": 0.5,
    }
    base.update(kw)
    return UnifiedRealtimeQuote(**base)


# === §4 判定矩阵 ===


@patch("stock_data.api.routes.helpers.is_trade_date", return_value=True)
def test_end_date_yesterday_no_merge(mock_isd):
    """end_date=昨天 → 不合并, 不调 quote."""
    df = _make_df(YESTERDAY)
    manager = MagicMock()
    result = _maybe_merge_today_bar(df, "600519", YESTERDAY, "d", manager, asset="stock")
    manager.get_realtime_quote.assert_not_called()
    assert len(result) == 1
    assert result.iloc[-1]["date"] == YESTERDAY


@patch("stock_data.api.routes.helpers.is_trade_date", return_value=False)
def test_end_date_today_but_not_trade_day_no_merge(mock_isd):
    """end_date=today AND 周末 → 不合并."""
    df = _make_df(YESTERDAY)
    manager = MagicMock()
    result = _maybe_merge_today_bar(df, "600519", TODAY, "d", manager, asset="stock")
    manager.get_realtime_quote.assert_not_called()
    assert len(result) == 1


@patch("stock_data.api.routes.helpers.is_trade_date", return_value=True)
def test_end_date_today_merge_when_missing(mock_isd):
    """end_date=today AND df 末根=昨天 AND quote 有效 → 合并."""
    df = _make_df(YESTERDAY)
    manager = MagicMock()
    manager.get_realtime_quote.return_value = _quote()
    result = _maybe_merge_today_bar(df, "600519", TODAY, "d", manager, asset="stock")
    manager.get_realtime_quote.assert_called_once_with("600519")
    assert len(result) == 2
    assert result.iloc[-1]["date"] == TODAY


@patch("stock_data.api.routes.helpers.is_trade_date", return_value=True)
def test_does_not_fetch_quote_when_today_bar_already_present(mock_isd):
    """★ 关键: df 末根=today → 不调 quote."""
    df = _make_df(TODAY)
    manager = MagicMock()
    result = _maybe_merge_today_bar(df, "600519", TODAY, "d", manager, asset="stock")
    manager.get_realtime_quote.assert_not_called()
    assert len(result) == 1
    assert result.iloc[-1]["date"] == TODAY


@patch("stock_data.api.routes.helpers.is_trade_date", return_value=True)
def test_end_date_tomorrow_merge(mock_isd):
    """end_date=明天 → 仍合并 (today 在范围内)."""
    df = _make_df(YESTERDAY)
    manager = MagicMock()
    manager.get_realtime_quote.return_value = _quote()
    result = _maybe_merge_today_bar(df, "600519", TOMORROW, "d", manager, asset="stock")
    assert len(result) == 2


@patch("stock_data.api.routes.helpers.is_trade_date", return_value=False)
def test_no_end_date_not_trade_day_no_merge(mock_isd):
    """默认 end_date → 用 today; 周末不合并."""
    df = _make_df(YESTERDAY)
    manager = MagicMock()
    _maybe_merge_today_bar(df, "600519", None, "d", manager, asset="stock")
    manager.get_realtime_quote.assert_not_called()


@patch("stock_data.api.routes.helpers.is_trade_date", return_value=True)
def test_no_end_date_is_trade_day_merge(mock_isd):
    """默认 end_date → 用 today; 交易日 + 缺 today → 合并."""
    df = _make_df(YESTERDAY)
    manager = MagicMock()
    manager.get_realtime_quote.return_value = _quote()
    result = _maybe_merge_today_bar(df, "600519", None, "d", manager, asset="stock")
    assert len(result) == 2


@patch("stock_data.api.routes.helpers.is_trade_date", return_value=True)
def test_quote_none_no_merge(mock_isd):
    """quote=None → graceful fallback."""
    df = _make_df(YESTERDAY)
    manager = MagicMock()
    manager.get_realtime_quote.return_value = None
    result = _maybe_merge_today_bar(df, "600519", TODAY, "d", manager, asset="stock")
    assert len(result) == 1


@patch("stock_data.api.routes.helpers.is_trade_date", return_value=True)
def test_quote_price_none_no_merge(mock_isd):
    """quote.price=None → 不合并."""
    df = _make_df(YESTERDAY)
    manager = MagicMock()
    manager.get_realtime_quote.return_value = _quote(price=None)
    result = _maybe_merge_today_bar(df, "600519", TODAY, "d", manager, asset="stock")
    assert len(result) == 1


@patch("stock_data.api.routes.helpers.is_trade_date", return_value=True)
def test_quote_volume_none_treated_as_zero(mock_isd):
    """quote.volume=None → safe_int(..., 0) 写 0."""
    df = _make_df(YESTERDAY)
    manager = MagicMock()
    manager.get_realtime_quote.return_value = _quote(volume=None)
    result = _maybe_merge_today_bar(df, "600519", TODAY, "d", manager, asset="stock")
    assert result.iloc[-1]["volume"] == 0


@patch("stock_data.api.routes.helpers.is_trade_date", return_value=True)
def test_quote_open_price_none_treated_as_zero(mock_isd):
    """quote.open_price=None → safe_float(..., 0.0) 写 0.0 (避免 dtype 污染)."""
    df = _make_df(YESTERDAY)
    manager = MagicMock()
    manager.get_realtime_quote.return_value = _quote(open_price=None)
    result = _maybe_merge_today_bar(df, "600519", TODAY, "d", manager, asset="stock")
    assert result.iloc[-1]["open"] == 0.0


@patch("stock_data.api.routes.helpers.is_trade_date", return_value=True)
def test_quote_fetch_exception_no_merge(mock_isd):
    """quote 抛异常 → except 兜底."""
    df = _make_df(YESTERDAY)
    manager = MagicMock()
    manager.get_realtime_quote.side_effect = RuntimeError("boom")
    result = _maybe_merge_today_bar(df, "600519", TODAY, "d", manager, asset="stock")
    assert len(result) == 1


def test_empty_df_no_merge():
    """df 空 → 返回空."""
    manager = MagicMock()
    with patch("stock_data.api.routes.helpers.is_trade_date", return_value=True):
        result = _maybe_merge_today_bar(
            pd.DataFrame(), "600519", TODAY, "d", manager, asset="stock"
        )
    manager.get_realtime_quote.assert_not_called()
    assert len(result) == 0


@patch("stock_data.api.routes.helpers.is_trade_date", return_value=True)
def test_index_path_calls_index_realtime_quote(mock_isd):
    """asset='index' → 调 get_index_realtime_quote."""
    df = _make_df(YESTERDAY)
    manager = MagicMock()
    manager.get_index_realtime_quote.return_value = _quote()
    result = _maybe_merge_today_bar(df, "000300", TODAY, "d", manager, asset="index")
    manager.get_index_realtime_quote.assert_called_once_with("000300")
    manager.get_realtime_quote.assert_not_called()
    assert len(result) == 2


# === 新增 (review 反馈) ===


@patch("stock_data.api.routes.helpers.is_trade_date", return_value=True)
def test_is_trade_date_raises_returns_df_unchanged(mock_isd):
    """is_trade_date 抛异常 (DB 锁等) → 兜底, 不合并."""
    mock_isd.side_effect = RuntimeError("DB locked")
    df = _make_df(YESTERDAY)
    manager = MagicMock()
    result = _maybe_merge_today_bar(df, "600519", TODAY, "d", manager, asset="stock")
    manager.get_realtime_quote.assert_not_called()
    assert len(result) == 1


@pytest.mark.parametrize("freq", ["1", "5", "15", "30", "60"])
def test_minute_freq_does_not_merge(freq):
    """1m/5m/15m/30m/60m → 不调 quote (单点 tick 不能混入聚合 bar)."""
    df = _make_df(YESTERDAY)
    manager = MagicMock()
    with patch("stock_data.api.routes.helpers.is_trade_date", return_value=True):
        result = _maybe_merge_today_bar(df, "600519", None, freq, manager, asset="stock")
    manager.get_realtime_quote.assert_not_called()
    assert len(result) == 1


@patch("stock_data.api.routes.helpers.is_trade_date", return_value=True)
def test_last_date_with_time_freq_d_truncation(mock_isd):
    """daily freq 下 df 末根含时间分量 (异常但防御) → [:10] 截断比较."""
    df = pd.DataFrame(
        [
            {
                "date": YESTERDAY + " 14:30:00",
                "open": 10.0,
                "high": 11.0,
                "low": 9.5,
                "close": 10.5,
                "volume": 1000,
                "amount": 10500.0,
                "pct_chg": 1.5,
            }
        ]
    )
    manager = MagicMock()
    manager.get_realtime_quote.return_value = _quote()
    result = _maybe_merge_today_bar(df, "600519", None, "d", manager, asset="stock")
    manager.get_realtime_quote.assert_called_once()
    assert len(result) == 2
    assert result.iloc[-1]["date"] == TODAY


@patch("stock_data.api.routes.helpers.is_trade_date", return_value=True)
def test_multi_row_df_truncation_then_merge(mock_isd):
    """100 行 df + 末根=昨天 → 合并后 101 行, 末根=today."""
    df = _make_df(YESTERDAY, n=100)
    manager = MagicMock()
    manager.get_realtime_quote.return_value = _quote()
    result = _maybe_merge_today_bar(df, "600519", None, "d", manager, asset="stock")
    assert len(result) == 101
    assert result.iloc[-1]["date"] == TODAY
    assert result.iloc[-2]["date"] == YESTERDAY
