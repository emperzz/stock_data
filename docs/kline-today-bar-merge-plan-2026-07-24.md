# K 线今日 Partial Bar 合并 — Plan

- **Date**: 2026-07-24
- **Parent spec**: `docs/kline-today-bar-merge-spec-2026-07-24.md`
- **Strategy**: 最小改动 + 新增 helper + 19 个测试 case

## 1. 改动清单

| 文件 | 类型 | 行数估算 | 改动 |
|---|---|---|---|
| `stock_data/api/routes/helpers.py` | 新增函数 | ~40 | `_maybe_merge_today_bar(df, code, end_date, frequency, manager, *, asset)` |
| `stock_data/api/routes/stocks.py` | 1 行调用 | 1 | in `get_kline`，调用 helper |
| `stock_data/api/routes/indices.py` | 1 行调用 | 1 | in `get_index_kline`，调用 helper |
| `tests/test_kline_today_merge.py` | 新增 | ~280 | 19 个 case |
| `CLAUDE.md` | 文档 | ~30 | 1 节新增 + 1 条 anti-pattern |

**总计**：~270 行新增，0 行删除。

## 2. 实施步骤（按顺序）

### Step 1: helper 函数 — 1 文件

文件 `stock_data/api/routes/helpers.py`。**先确认顶部 import**（当前 `helpers.py:35-36` 是 `if TYPE_CHECKING: import pandas as pd`，**仅类型检查时导入**；helper 内 `pd.concat`/`pd.DataFrame` 是运行时调用，必须新增 `import pandas as pd` 到运行时 import 区）。

在 import 区追加：

```python
import pandas as pd
from ...data_provider.core.types import safe_float, safe_int
from ...data_provider.persistence.trade_calendar import is_trade_date
```

> 注：`persistence.trade_calendar` → `manager` 不存在循环（`trade_calendar.py` 全文不 import manager），`helpers.py → trade_calendar` 直接顶层 import 即可。

在 `_apply_indicators` 之后追加 helper：

```python
_MINUTE_FREQS = frozenset({"1", "5", "15", "30", "60"})


def _maybe_merge_today_bar(
    df: pd.DataFrame,
    code: str,
    end_date: str | None,
    frequency: str,
    manager: DataFetcherManager,
    *,
    asset: str = "stock",
) -> pd.DataFrame:
    """If end_date includes today AND today is a trading day AND the K-line
    doesn't already contain today's bar, best-effort fetch realtime quote
    and append/replace today's partial bar.

    Only triggers for daily/weekly/monthly frequency; minute bars are
    intraday aggregates and a single quote tick is semantically wrong to
    inject as a 5m/15m bar.

    See docs/kline-today-bar-merge-spec-2026-07-24.md §3 for contract.
    """
    # 0. minute freq → skip (semantically wrong)
    if frequency in _MINUTE_FREQS:
        return df

    if df is None or df.empty:
        return df

    today_str = date.today().isoformat()
    effective_end = end_date or today_str

    # 1. end_date must include today
    if effective_end < today_str:
        return df

    # 2. today must be a trading day (fail-closed on DB error)
    try:
        trade_day = is_trade_date(today_str)
    except Exception as e:
        logger.debug(f"[maybe_merge_today_bar] is_trade_date failed for {today_str}: {e}")
        return df
    if not trade_day:
        return df

    # 3. df already has today's bar → no-op (avoid quote call)
    last_date = str(df.iloc[-1]["date"])[:10]
    if last_date == today_str:
        return df

    # 4. best-effort fetch realtime quote. broadly catching Exception
    # because a quote outage must NEVER break the K-line response.
    try:
        quote = (
            manager.get_realtime_quote(code)
            if asset == "stock"
            else manager.get_index_realtime_quote(code)
        )
    except Exception as e:
        logger.debug(f"[maybe_merge_today_bar] quote fetch failed for {code}: {e}")
        return df

    if quote is None or quote.price is None:
        return df

    # 5. construct today's partial bar (safe_float/safe_int per
    # project invariant: NaN/inf/-inf must never leak into numeric
    # fields; nullable fields retain None).
    today_bar = {
        "date": today_str,
        "open": safe_float(quote.open_price, 0.0),
        "high": safe_float(quote.high, 0.0),
        "low": safe_float(quote.low, 0.0),
        "close": safe_float(quote.price, 0.0),
        "volume": safe_int(quote.volume, 0),
        "amount": safe_float(quote.amount, None),
        "pct_chg": safe_float(quote.change_pct, None),
    }
    return pd.concat([df, pd.DataFrame([today_bar])], ignore_index=True)
```

**约束**：
- 必须显式 `import pandas as pd`（已加 `from ... import safe_float, safe_int`）
- `is_trade_date` 顶层 import（无循环）
- `logger` 用 `logging.getLogger(__name__)`（已存在的模块顶部 logger）

### Step 2: 路由调用 — 2 文件

**`stock_data/api/routes/stocks.py::get_kline`**（line 265 之后）：

```python
df = _apply_indicators(df, requested_indicators, days=days, actual_days=actual_days)
df = _maybe_merge_today_bar(df, code, end_date, freq, manager, asset="stock")  # ← 新增
name = stock_list.get_stock_name(code, manager=manager)
```

**`stock_data/api/routes/indices.py::get_index_kline`**（line 195 之后）：

```python
df = _apply_indicators(df, requested_indicators, days=days, actual_days=actual_days)
df = _maybe_merge_today_bar(df, index_code, end_date, freq, manager, asset="index")  # ← 新增
index_name = _resolve_index_name(index_code)
```

### Step 3: 测试 — 1 文件

新建 `tests/test_kline_today_merge.py`：

```python
"""Tests for routes/_maybe_merge_today_bar helper.

See docs/kline-today-bar-merge-spec-2026-07-24.md §4 for the decision matrix.
"""
from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from stock_data.api.routes.helpers import _maybe_merge_today_bar
from stock_data.data_provider.core.types import UnifiedRealtimeQuote


TODAY = date(2026, 7, 24).isoformat()
YESTERDAY = date(2026, 7, 23).isoformat()
TOMORROW = date(2026, 7, 25).isoformat()


def _make_df(end_date: str, n: int = 1) -> pd.DataFrame:
    return pd.DataFrame([{
        "date": end_date, "open": 10.0, "high": 11.0, "low": 9.5,
        "close": 10.5, "volume": 1000, "amount": 10500.0, "pct_chg": 1.5,
    }] * n)


def _quote(**kw) -> UnifiedRealtimeQuote:
    base = dict(
        code="600519", name="", price=10.8,
        open_price=10.5, high=10.9, low=10.4,
        volume=500, amount=5400.0, change_pct=0.5,
    )
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
    result = _maybe_merge_today_bar(df, "600519", None, "d", manager, asset="stock")
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
        result = _maybe_merge_today_bar(pd.DataFrame(), "600519", TODAY, "d", manager, asset="stock")
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
def test_minute_freq_last_date_truncation(mock_isd):
    """df 末根日期含时间分量 (minute freq) → [:10] 截断后比较."""
    df = pd.DataFrame([{
        "date": "2026-07-24 14:30:00", "open": 10.0, "high": 11.0,
        "low": 9.5, "close": 10.5, "volume": 1000, "amount": 10500.0,
        "pct_chg": 1.5,
    }])
    manager = MagicMock()
    # 但因为 frequency='5' 提前返回，这条反而验证的是 minute 不合并
    result = _maybe_merge_today_bar(df, "600519", None, "5", manager, asset="stock")
    manager.get_realtime_quote.assert_not_called()


@patch("stock_data.api.routes.helpers.is_trade_date", return_value=True)
def test_last_date_with_time_freq_d_truncation(mock_isd):
    """daily freq 下 df 末根含时间分量 (异常但防御) → [:10] 截断比较."""
    df = pd.DataFrame([{
        "date": "2026-07-23 14:30:00", "open": 10.0, "high": 11.0,
        "low": 9.5, "close": 10.5, "volume": 1000, "amount": 10500.0,
        "pct_chg": 1.5,
    }])
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
```

### Step 4: 文档 — 1 文件

修改 `CLAUDE.md`（**注意位置：与 Indicator Computation 语义相邻**）：

**位置 1**：「Indicator Computation」节后追加新节「K-line today's partial bar」：

```markdown
## K-line today's partial bar

K 线 routes (`/stocks/{code}/kline` + `/indices/{code}/kline`) 默认在以下条件全部满足时合并今日 partial bar：

1. `frequency ∈ {"d", "w", "m"}`（minute 频段不触发——单点 tick 不能混入聚合 bar）
2. `end_date`（显式或默认）包含今天
3. 今天在 A 股交易日历中（`is_trade_date(today)` 为 True）
4. K 线响应末根日期 ≠ 今天

合并 source：`manager.get_realtime_quote(code)` (stock) 或 `manager.get_index_realtime_quote(code)` (index)，best-effort，失败时回退到原 K 线。今日 partial bar **不**带 `?indicators=` 计算结果（指标只对已收盘数据计算）。详见 `docs/kline-today-bar-merge-spec-2026-07-24.md`。

**时区假设**：server 跑在 CST（Asia/Shanghai）；非 CST 环境下 `date.today()` 与 A 股交易日可能错位（晚 8h 才跨日）。
```

**位置 2**：「Anti-Patterns to Avoid」节追加（通用化表述）：

```markdown
- **Don't** 在 fetcher 层 hardcode "今日 partial bar" 合并逻辑；统一在 K-line route 层 helper 走。Fetcher 层的"今日 bar"逻辑会跨 fetcher 行为不一致，并绕过 manager 的短路与熔断保护。
```

## 3. 验证清单

| 步骤 | 命令 | 期望 |
|---|---|---|
| 单测 | `.venv/Scripts/python.exe -m pytest tests/test_kline_today_merge.py -v` | 19 pass |
| 全量 | `.venv/Scripts/python.exe -m pytest` | 全绿（默认跳 live_network） |
| Lint | `ruff check .` | 0 issues |
| Format | `ruff format .` | 无 diff |
| 手测 | `curl localhost:8888/api/v1/stocks/600519/kline?days=5` | 6 根（5 + 今日 partial） |
| 手测 | `curl localhost:8888/api/v1/stocks/600519/kline?days=5&end_date=2026-07-22` | 5 根（止于 2026-07-22） |
| 手测 | `curl localhost:8888/api/v1/indices/000300/kline?days=5` | 6 根 |

## 4. 风险与回滚

| 风险 | 触发条件 | 缓解 |
|---|---|---|
| `is_trade_date` 冷表 → 整段交易时段无 today bar | 首次安装 / 持久化空 | `is_trade_date` 返回 False（fail-closed）；**用户需手动**调 `update_cached_calendar` 恢复（无 lazy fill） |
| `is_trade_date` 抛异常 | DB 锁 / schema 损坏 | helper 内 try/except 兜底，不合并 |
| 行情失败 → 响应变慢 | quote 30s 超时 | best-effort except，返回原 df |
| 5 min cache 期间内行情跳 | 用户高频 poll | 下轮自动刷新 |
| Yfinance `end-exclusive` | 实际导致末根 ≤ yesterday | helper 兜底（无副作用） |
| Manager 短路 | Tushare/Baostock 抢先 | 无影响（helper 在 manager 之后跑） |
| 缓存过期瞬间并发触发 N 次 quote | TTL=300s 边界 | 一次 cache 填充后命中；N 上限 = 客户端并发数，可接受 |
| 分钟频段（1m/5m/15m/30m/60m） | frequency ≠ d/w/m | 直接不触发 helper（无混合语义） |

**回滚方案**（共 4 步）：
1. 删除 `routes/stocks.py` 的 1 行调用
2. 删除 `routes/indices.py` 的 1 行调用
3. 删除 `tests/test_kline_today_merge.py`（否则 dev loop 找不到 `_maybe_merge_today_bar` 会 19 个失败）
4. 删除 `stock_data/api/routes/helpers.py` 里的 helper 函数

helper 是纯加法（merge 逻辑在指标之后）——若 quote 接口全挂，K 线仍返回原 settle 状态。无破坏性。

## 5. 后续（不在本次范围）

- K 线日终落盘（收盘后批量写今日 bar 到 SQLite，避免每次实时 merge）
- Yfinance fetcher 内部 `end + 1 day` 修正（拆为独立 PR）
- `KLineData.is_partial` 字段（用户可显式判断）
- 跨市场时区（CST / EST / HKT）适配
- `get_realtime_quote` 失败时返回部分字段（如只有 `price` 而无 OHLC）合成今日 bar

## 6. 验收签字

- [ ] Spec review 通过（待 sub-agent review）
- [ ] 13 unit test 全绿
- [ ] dev loop 全量 pytest 全绿
- [ ] ruff check + format 0 issues
- [ ] 手测 3 个 endpoint 验证
- [ ] CLAUDE.md 更新同步
- [ ] commit + push
