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
    result = _maybe_merge_today_bar(df, "600519", YESTERDAY, "d", manager, asset="stock")[0]
    manager.get_realtime_quote.assert_not_called()
    assert len(result) == 1
    assert result.iloc[-1]["date"] == YESTERDAY


@patch("stock_data.api.routes.helpers.is_trade_date", return_value=False)
def test_end_date_today_but_not_trade_day_no_merge(mock_isd):
    """end_date=today AND 周末 → 不合并."""
    df = _make_df(YESTERDAY)
    manager = MagicMock()
    result = _maybe_merge_today_bar(df, "600519", TODAY, "d", manager, asset="stock")[0]
    manager.get_realtime_quote.assert_not_called()
    assert len(result) == 1


@patch("stock_data.api.routes.helpers.is_trade_date", return_value=True)
def test_end_date_today_merge_when_missing(mock_isd):
    """end_date=today AND df 末根=昨天 AND quote 有效 → 合并."""
    df = _make_df(YESTERDAY)
    manager = MagicMock()
    manager.get_realtime_quote.return_value = _quote()
    result = _maybe_merge_today_bar(df, "600519", TODAY, "d", manager, asset="stock")[0]
    manager.get_realtime_quote.assert_called_once_with("600519")
    assert len(result) == 2
    assert result.iloc[-1]["date"] == TODAY


@patch("stock_data.api.routes.helpers.is_trade_date", return_value=True)
def test_does_not_fetch_quote_when_today_bar_already_present(mock_isd):
    """★ 关键: df 末根=today → 不调 quote."""
    df = _make_df(TODAY)
    manager = MagicMock()
    result = _maybe_merge_today_bar(df, "600519", TODAY, "d", manager, asset="stock")[0]
    manager.get_realtime_quote.assert_not_called()
    assert len(result) == 1
    assert result.iloc[-1]["date"] == TODAY


@patch("stock_data.api.routes.helpers.is_trade_date", return_value=True)
def test_end_date_tomorrow_merge(mock_isd):
    """end_date=明天 → 仍合并 (today 在范围内)."""
    df = _make_df(YESTERDAY)
    manager = MagicMock()
    manager.get_realtime_quote.return_value = _quote()
    result = _maybe_merge_today_bar(df, "600519", TOMORROW, "d", manager, asset="stock")[0]
    assert len(result) == 2


@patch("stock_data.api.routes.helpers.is_trade_date", return_value=False)
def test_no_end_date_not_trade_day_no_merge(mock_isd):
    """默认 end_date → 用 today; 周末不合并."""
    df = _make_df(YESTERDAY)
    manager = MagicMock()
    _maybe_merge_today_bar(df, "600519", None, "d", manager, asset="stock")[0]
    manager.get_realtime_quote.assert_not_called()


@patch("stock_data.api.routes.helpers.is_trade_date", return_value=True)
def test_no_end_date_is_trade_day_merge(mock_isd):
    """默认 end_date → 用 today; 交易日 + 缺 today → 合并."""
    df = _make_df(YESTERDAY)
    manager = MagicMock()
    manager.get_realtime_quote.return_value = _quote()
    result = _maybe_merge_today_bar(df, "600519", None, "d", manager, asset="stock")[0]
    assert len(result) == 2


@patch("stock_data.api.routes.helpers.is_trade_date", return_value=True)
def test_quote_none_no_merge(mock_isd):
    """quote=None → graceful fallback."""
    df = _make_df(YESTERDAY)
    manager = MagicMock()
    manager.get_realtime_quote.return_value = None
    result = _maybe_merge_today_bar(df, "600519", TODAY, "d", manager, asset="stock")[0]
    assert len(result) == 1


@patch("stock_data.api.routes.helpers.is_trade_date", return_value=True)
def test_quote_price_none_no_merge(mock_isd):
    """quote.price=None → 不合并."""
    df = _make_df(YESTERDAY)
    manager = MagicMock()
    manager.get_realtime_quote.return_value = _quote(price=None)
    result = _maybe_merge_today_bar(df, "600519", TODAY, "d", manager, asset="stock")[0]
    assert len(result) == 1


@patch("stock_data.api.routes.helpers.is_trade_date", return_value=True)
def test_quote_volume_none_still_merges_as_zero(mock_isd):
    """quote.volume=None → 仍合并, volume 写 0 (量缺失不影响 OHLC 有效性)."""
    df = _make_df(YESTERDAY)
    manager = MagicMock()
    manager.get_realtime_quote.return_value = _quote(volume=None)
    result = _maybe_merge_today_bar(df, "600519", TODAY, "d", manager, asset="stock")[0]
    assert len(result) == 2
    assert result.iloc[-1]["volume"] == 0


@patch("stock_data.api.routes.helpers.is_trade_date", return_value=True)
def test_quote_open_price_none_no_merge(mock_isd):
    """quote.open_price=None → 不合并 (不再注入 open=0.0).

    今日 bar 会进入指标窗口; 一根 open/high/low 被填 0 的 bar 会把
    ATR/TR/KC/CCI 放大 6-64x。缺失 OHLC 时宁可不出今日 bar。
    """
    df = _make_df(YESTERDAY)
    manager = MagicMock()
    manager.get_realtime_quote.return_value = _quote(open_price=None)
    result = _maybe_merge_today_bar(df, "600519", TODAY, "d", manager, asset="stock")[0]
    assert len(result) == 1


@patch("stock_data.api.routes.helpers.is_trade_date", return_value=True)
def test_quote_high_none_no_merge(mock_isd):
    """quote.high=None → 不合并."""
    df = _make_df(YESTERDAY)
    manager = MagicMock()
    manager.get_realtime_quote.return_value = _quote(high=None)
    result = _maybe_merge_today_bar(df, "600519", TODAY, "d", manager, asset="stock")[0]
    assert len(result) == 1


@patch("stock_data.api.routes.helpers.is_trade_date", return_value=True)
def test_quote_low_above_high_no_merge(mock_isd):
    """low > high (上游异常) → 不合并."""
    df = _make_df(YESTERDAY)
    manager = MagicMock()
    manager.get_realtime_quote.return_value = _quote(low=11.0, high=10.0)
    result = _maybe_merge_today_bar(df, "600519", TODAY, "d", manager, asset="stock")[0]
    assert len(result) == 1


@patch("stock_data.api.routes.helpers.is_trade_date", return_value=True)
def test_quote_close_outside_range_no_merge(mock_isd):
    """price 不在 [low, high] 内 → 不合并."""
    df = _make_df(YESTERDAY)
    manager = MagicMock()
    manager.get_realtime_quote.return_value = _quote(price=99.0)
    result = _maybe_merge_today_bar(df, "600519", TODAY, "d", manager, asset="stock")[0]
    assert len(result) == 1


@patch("stock_data.api.routes.helpers.is_trade_date", return_value=True)
def test_quote_price_zero_no_merge(mock_isd):
    """price=0.0 (盘中无成交/异常) → 不合并."""
    df = _make_df(YESTERDAY)
    manager = MagicMock()
    manager.get_realtime_quote.return_value = _quote(price=0.0)
    result = _maybe_merge_today_bar(df, "600519", TODAY, "d", manager, asset="stock")[0]
    assert len(result) == 1


# === 新增不变量 ===


@patch("stock_data.api.routes.helpers.is_trade_date", return_value=True)
def test_returns_merged_true_when_appended(mock_isd):
    """合并发生 → (df, True)."""
    df = _make_df(YESTERDAY)
    manager = MagicMock()
    manager.get_realtime_quote.return_value = _quote()
    result, merged = _maybe_merge_today_bar(df, "600519", TODAY, "d", manager, asset="stock")
    assert merged is True
    assert len(result) == 2


@patch("stock_data.api.routes.helpers.is_trade_date", return_value=True)
def test_returns_merged_false_when_today_already_present(mock_isd):
    """fetcher 已给今日 bar → (df, False) — 日期比较无法区分来源."""
    df = _make_df(TODAY)
    manager = MagicMock()
    result, merged = _maybe_merge_today_bar(df, "600519", TODAY, "d", manager, asset="stock")
    assert merged is False
    assert len(result) == 1


@patch("stock_data.api.routes.helpers.is_trade_date", return_value=True)
def test_future_last_date_no_merge(mock_isd):
    """末根=未来日期 (fetcher/时区异常) → 不合并, 不把今日 bar 埋在它之前."""
    df = _make_df(TOMORROW)
    manager = MagicMock()
    result, merged = _maybe_merge_today_bar(df, "600519", None, "d", manager, asset="stock")
    manager.get_realtime_quote.assert_not_called()
    assert merged is False
    assert result.iloc[-1]["date"] == TOMORROW


@pytest.mark.parametrize("freq", ["w", "m"])
def test_weekly_monthly_freq_does_not_merge(freq):
    """w/m 不合并 — 单日 tick 冒充一根周/月 bar 会污染整条序列."""
    df = _make_df(YESTERDAY)
    manager = MagicMock()
    with patch("stock_data.api.routes.helpers.is_trade_date", return_value=True):
        result, merged = _maybe_merge_today_bar(df, "600519", None, freq, manager, asset="stock")
    manager.get_realtime_quote.assert_not_called()
    assert merged is False
    assert len(result) == 1


@patch("stock_data.api.routes.helpers.is_trade_date", return_value=True)
def test_hfq_adjust_does_not_merge(mock_isd):
    """adjust=hfq → 不合并 (后复权锚定最早 bar, 实时原价不可比)."""
    df = _make_df(YESTERDAY)
    manager = MagicMock()
    result, merged = _maybe_merge_today_bar(
        df, "600519", None, "d", manager, asset="stock", adjust="hfq"
    )
    manager.get_realtime_quote.assert_not_called()
    assert merged is False


@pytest.mark.parametrize("adjust", ["qfq", None, ""])
@patch("stock_data.api.routes.helpers.is_trade_date", return_value=True)
def test_qfq_and_unadjusted_still_merge(mock_isd, adjust):
    """qfq / 不复权 → 仍合并 (今日原价 == 今日前复权价)."""
    df = _make_df(YESTERDAY)
    manager = MagicMock()
    manager.get_realtime_quote.return_value = _quote()
    _result, merged = _maybe_merge_today_bar(
        df, "600519", None, "d", manager, asset="stock", adjust=adjust
    )
    assert merged is True


@pytest.mark.parametrize("code", ["HK00700", "AAPL"])
@patch("stock_data.api.routes.helpers.is_trade_date", return_value=True)
def test_non_csi_stock_no_merge(mock_isd, code):
    """HK/US 用 A 股日历判定交易日不成立 → 不合并."""
    df = _make_df(YESTERDAY)
    manager = MagicMock()
    result, merged = _maybe_merge_today_bar(df, code, None, "d", manager, asset="stock")
    manager.get_realtime_quote.assert_not_called()
    assert merged is False


@patch("stock_data.api.routes.helpers.is_trade_date", return_value=True)
def test_quote_fetch_exception_no_merge(mock_isd):
    """quote 抛异常 → except 兜底."""
    df = _make_df(YESTERDAY)
    manager = MagicMock()
    manager.get_realtime_quote.side_effect = RuntimeError("boom")
    result = _maybe_merge_today_bar(df, "600519", TODAY, "d", manager, asset="stock")[0]
    assert len(result) == 1


def test_empty_df_no_merge():
    """df 空 → 返回空."""
    manager = MagicMock()
    with patch("stock_data.api.routes.helpers.is_trade_date", return_value=True):
        result = _maybe_merge_today_bar(
            pd.DataFrame(), "600519", TODAY, "d", manager, asset="stock"
        )[0]
    manager.get_realtime_quote.assert_not_called()
    assert len(result) == 0


@patch("stock_data.api.routes.helpers.is_trade_date", return_value=True)
def test_index_path_calls_index_realtime_quote(mock_isd):
    """asset='index' → 调 get_index_realtime_quote."""
    df = _make_df(YESTERDAY)
    manager = MagicMock()
    manager.get_index_realtime_quote.return_value = _quote()
    result = _maybe_merge_today_bar(df, "000300", TODAY, "d", manager, asset="index")[0]
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
    result = _maybe_merge_today_bar(df, "600519", TODAY, "d", manager, asset="stock")[0]
    manager.get_realtime_quote.assert_not_called()
    assert len(result) == 1


@pytest.mark.parametrize("freq", ["1", "5", "15", "30", "60"])
def test_minute_freq_does_not_merge(freq):
    """1m/5m/15m/30m/60m → 不调 quote (单点 tick 不能混入聚合 bar)."""
    df = _make_df(YESTERDAY)
    manager = MagicMock()
    with patch("stock_data.api.routes.helpers.is_trade_date", return_value=True):
        result = _maybe_merge_today_bar(df, "600519", None, freq, manager, asset="stock")[0]
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
    result = _maybe_merge_today_bar(df, "600519", None, "d", manager, asset="stock")[0]
    manager.get_realtime_quote.assert_called_once()
    assert len(result) == 2
    assert result.iloc[-1]["date"] == TODAY


@patch("stock_data.api.routes.helpers.is_trade_date", return_value=True)
def test_multi_row_df_truncation_then_merge(mock_isd):
    """100 行 df + 末根=昨天 → 合并后 101 行, 末根=today."""
    df = _make_df(YESTERDAY, n=100)
    manager = MagicMock()
    manager.get_realtime_quote.return_value = _quote()
    result = _maybe_merge_today_bar(df, "600519", None, "d", manager, asset="stock")[0]
    assert len(result) == 101
    assert result.iloc[-1]["date"] == TODAY
    assert result.iloc[-2]["date"] == YESTERDAY


# === 完整链路: merge → compute → 截断 (今日实时数据参与指标计算) ===


def _closed_df(n: int = 10) -> pd.DataFrame:
    """n 根已收盘日线, close = 1..n, 日期止于 TODAY 之前."""
    dates = pd.bdate_range(end=TODAY, periods=n + 1)[:-1]
    return pd.DataFrame(
        [
            {
                "date": d.strftime("%Y-%m-%d"),
                "open": float(i),
                "high": float(i) + 0.5,
                "low": float(i) - 0.5,
                "close": float(i),
                "volume": 1000.0,
                "amount": 10000.0,
                "pct_chg": 0.0,
            }
            for i, d in enumerate(dates, start=1)
        ]
    )


@patch("stock_data.api.routes.helpers.is_trade_date", return_value=True)
def test_today_bar_gets_indicators_including_today_close(mock_isd):
    """★ 核心契约: 今日实时数据参与计算 — 今日 ma5 含今日实时 close."""
    from stock_data.api.routes.helpers import _finalize_kline

    df = _closed_df(10)
    manager = MagicMock()
    # 今日实时 close = 100.0，远高于历史的 1..10
    manager.get_realtime_quote.return_value = _quote(
        price=100.0, open_price=99.0, high=101.0, low=98.5
    )

    merged_df, merged = _maybe_merge_today_bar(df, "600519", None, "d", manager, asset="stock")
    out = _finalize_kline(merged_df, ["ma"], days=10, merged=merged)

    assert merged is True
    assert len(out) == 11  # 10 根已收盘 + 1 根今日 partial

    today_inds = out.iloc[-1]["indicators"]
    assert isinstance(today_inds, dict)
    # ma5 = mean(close[-5:]) = mean([7, 8, 9, 10, 100]) = 26.8
    assert today_inds["ma5"] == pytest.approx(26.8)

    # 已收盘行的指标不受追加影响 — 与「不合并直接算」逐位相同 (ma5=8.0)
    baseline = _finalize_kline(df, ["ma"], days=10, merged=False)
    for i in range(len(baseline)):
        assert out.iloc[i]["indicators"]["ma5"] == pytest.approx(
            baseline.iloc[i]["indicators"]["ma5"]
        )


@patch("stock_data.api.routes.helpers.is_trade_date", return_value=True)
def test_output_keeps_days_plus_today_after_lookback_truncation(mock_isd):
    """★ 行数契约: lookback 展开后仍保留今日行 (days + 1)."""
    from stock_data.api.routes.helpers import _expand_indicator_lookback, _finalize_kline

    # days=5 + ma 的 warmup 需求 → actual_days 远大于 days
    actual_days = _expand_indicator_lookback(["ma"], 5)
    assert actual_days > 5

    df = _closed_df(actual_days)
    manager = MagicMock()
    manager.get_realtime_quote.return_value = _quote(
        price=100.0, open_price=99.0, high=101.0, low=98.5
    )
    merged_df, merged = _maybe_merge_today_bar(df, "600519", None, "d", manager, asset="stock")
    assert merged is True
    assert len(merged_df) == actual_days + 1

    out = _finalize_kline(merged_df, ["ma"], days=5, merged=merged)
    assert len(out) == 6  # 5 根已收盘 + 1 根今日，不是 5
    assert str(out.iloc[-1]["date"])[:10] == TODAY
    assert isinstance(out.iloc[-1]["indicators"], dict)


@patch("stock_data.api.routes.helpers.is_trade_date", return_value=True)
def test_no_merge_does_not_add_a_row(mock_isd):
    """未合并时不得多出一行 (merged=False → days 行)."""
    from stock_data.api.routes.helpers import _finalize_kline

    # 末根已经是今日 → helper 不合并 (fetcher 盘后已 backfill)
    df = pd.concat([_closed_df(29), _closed_df(1).assign(date=TODAY)], ignore_index=True)
    manager = MagicMock()
    merged_df, merged = _maybe_merge_today_bar(df, "600519", TODAY, "d", manager, asset="stock")
    assert merged is False
    assert len(merged_df) == 30

    out = _finalize_kline(merged_df, ["ma"], days=30, merged=merged)
    assert len(out) == 30
