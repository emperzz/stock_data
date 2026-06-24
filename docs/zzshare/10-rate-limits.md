# zzshare · 接口频率限制速查表

> 抓取时间：2026-06-24
> 数据来源：zzshare 官方

## 主表

| 接口（zzshare） | 无 token | 有 token |
|---|---|---|
| `daily()` | 100 次/分 | 600 次/分 |
| `rt_k()` | 10 次/分 | 20 次/分 |
| `stk_mins()` | 30 次/分 | 100 次/分 |
| `plates_rank()` | 20 次/分 | 60 次/分 |
| `market_plate_stocks()` | 20 次/分 | 60 次/分 |
| `plates_rank_days()` | 10 次/分 | 30 次/分 |
| `plates_rank_days_new()` | 10 次/分 | 30 次/分 |
| `market_plate_popular_reason()` | 20 次/分 | 60 次/分 |
| `market_sentiment_kline()` | 10 次/分 | 60 次/分 |
| `sentiment_timing()` | 60 次/分 | 180 次/分 |
| `sentiment_trend()` | 30 次/分 | 120 次/分 |
| `review_uplimit_reason()` | 30 次/分 | 120 次/分 |
| `topic_table_kline_web()` | -- | 20 次/分 |
| `topic_table_stocks_web()` | -- | 10 次/分 |

## 详细说明

### `daily()` — 历史日线行情

- **无 token**：100 次/分
- **有 token**：600 次/分
- 单股单次 ≤ 1000 行，**超量需 `offset` / `limit` 分页**；全市场单次 ≤ 10000。
- 详见 [01-kline.md § 1 `daily`](01-kline.md#1-daily--日线行情兼容-tushare)。

### `rt_k()` — 实时行情日线快照

- **无 token**：10 次/分
- **有 token**：20 次/分
- 详见 [02-realtime.md § `rt_k`](02-realtime.md)。

### `stk_mins()` — 分钟数据（实时 + 历史）

- **无 token**：30 次/分
- **有 token**：100 次/分
- 详见 [01-kline.md § 2 `stk_mins`](01-kline.md#2-stk_mins--分钟-k-线兼容-tushare)。

### `plates_rank()` — 获取全市场（题材 / 概念 / 行业）的热度排名

- **无 token**：20 次/分
- **有 token**：60 次/分
- 详见 [07-boards.md § 2 `plates_rank`](07-boards.md#2-plates_rank--板块热度排名)。

### `market_plate_stocks()` — 板块成分股人气排行

- **无 token**：20 次/分
- **有 token**：60 次/分
- 详见 [07-boards.md § 4 `market_plate_stocks`](07-boards.md#4-market_plate_stocks--板块成分股按人气排名)。

### `plates_rank_days()` — 板块 Top（区间排名）

- **无 token**：10 次/分
- **有 token**：30 次/分
- 详见 [07-boards.md § 7 `plates_rank_days`](07-boards.md#7-plates_rank_days--板块区间排名)。

### `plates_rank_days_new()` — 板块 Top（区间排名 + 新进标记）

- **无 token**：10 次/分
- **有 token**：30 次/分
- 详见 [07-boards.md § 8 `plates_rank_days_new`](07-boards.md#8-plates_rank_days_new--区间排名--新进标记)。

### `market_plate_popular_reason()` — 板块爆发催化剂分析

- **无 token**：20 次/分
- **有 token**：60 次/分
- 详见 [07-boards.md § 5 `market_plate_popular_reason`](07-boards.md#5-market_plate_popular_reason--板块爆点--原因)。

### `market_sentiment_kline()` — 市场情绪日 K

- **无 token**：10 次/分
- **有 token**：60 次/分
- 与 SDK 中的 `market_sentiment`（HTTP `/v3/market/sentiment/0/kline`）对应同一接口族；详细字段见 [06-sentiment.md § 1 `market_sentiment`](06-sentiment.md#1-market_sentiment--综合市场情绪-k-线)。

### `sentiment_timing()` — 情绪小周期择时（需权限）

- **无 token**：60 次/分
- **有 token**：180 次/分
- 需 `sentiment_vip` 权限。详见 [06-sentiment.md § 5 `sentiment_timing`](06-sentiment.md#5-sentiment_timing--vip-择时信号)。

### `sentiment_trend()` — 市场情绪分时

- **无 token**：30 次/分
- **有 token**：120 次/分
- 详见 [06-sentiment.md § 7 `sentiment_trend`](06-sentiment.md#7-sentiment_trend--情绪趋势按模型)。

### `review_uplimit_reason()` — 每日涨停原因

- **无 token**：30 次/分
- **有 token**：120 次/分
- 详见 [04-uplimit-review.md § 5 `review_uplimit_reason`](04-uplimit-review.md#5-review_uplimit_reason--全市场涨停原因汇总)。

### `topic_table_kline_web()` — 登录权限下的题材 K 线

- **无 token**：-- （不可用）
- **有 token**：20 次/分
- 与 SDK 中的 `topic_kline`（HTTP `/v3/topic/table/{tid}/kline`）对应同一接口族；`_web` 后缀表明该方法在 MCP Server 中以独立 web 方法名暴露。详见 [01-kline.md § 4 `topic_kline`](01-kline.md#4-topic_kline--题材合成指数-k-线)。

### `topic_table_stocks_web()` — 题材表格股票列表（登录权限下）

- **无 token**：-- （不可用）
- **有 token**：10 次/分
- 与 SDK 中的 `topic_table_stocks`（HTTP `/v3/topic/table/{tid}/stocks`）对应同一接口族；`_web` 后缀表明该方法在 MCP Server 中以独立 web 方法名暴露。详见 [09-topic-library.md § 1.3 `topic_table_stocks`](09-topic-library.md#3-topic_table_stocks--题材下个股列表)。