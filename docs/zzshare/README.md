# zzshare — A 股量化数据 API 文档（精编）

> 抓取时间：2026-06-24
> 源仓库：<https://github.com/zzquant/zzshare>
> 文档站点：<https://quant.zizizaizai.com/>
> 抓取对象：`d:\gitrepo\zzshare`（已包含本地 clone）

zzshare 是一个面向 AI Agent / LLM 场景优化的 A 股量化数据 SDK，提供行情、涨停复盘、龙虎榜、情绪、板块、资金流向等 40+ 接口，**仅覆盖沪深北 A 股市场**（不含港股 / 美股 / 指数）。底层是统一的 HTTP API（`https://api.zizizaizai.com`），上层提供 `DataApi` Python SDK、MCP Server（`zzshare-mcp` 命令）和 CLI（`zzshare-cli`）。

> **关于凭证**：**绝大多数接口无需 Token**，匿名即可调用（但有较严格的匿名频率限制）。高频接口（`rt_k`、部分 `uplimit_*` 接口等）需要 `ZZSHARE_TOKEN`（或调用时显式传入 `token=` 参数），可在官网 <https://quant.zizizaizai.com/me/profile?tab=2&invite_code=E22541A0> 免费申请。

## 文件清单

| 文件 | 主题 |
|---|---|
| [01-kline.md](01-kline.md) | **行情数据**：`daily`（日 K）、`stk_mins`（1/5/15/30/60 分钟 K）、`plate_kline`（板块指数 K）、`topic_kline`（题材合成指数 K） |
| [02-realtime.md](02-realtime.md) | **实时行情**：`rt_k`（实时快照，含五档盘口 / 涨跌停价 / PE / 总市值 等 26 个增强字段） |
| [03-basic-data.md](03-basic-data.md) | **基础数据**：`stock_basic`（全市场股票列表）、`trade_days`（交易日历）、`stock_info`（个股公司画像） |
| [04-uplimit-review.md](04-uplimit-review.md) | **涨停复盘**：`uplimit_hot`（涨停热门板块梯队）、`uplimit_stocks`（涨停个股）、`stock_uplimit_reason`（个股涨停原因）、`review_uplimit_reason`（涨停原因汇总）、`uplimit_market_value`（涨停市值统计） |
| [05-dragon-tiger.md](05-dragon-tiger.md) | **龙虎榜**：`lhb_list`（上榜概览）、`lhb_detail`（席位详情）、`lhb_stock_history`（个股历史）、`lhb_trader_history`（席位交易历史） |
| [06-sentiment.md](06-sentiment.md) | **情绪热度**：`market_sentiment`（市场情绪 K 线）、`sentiment_trend` / `sentiment_trend_range`（情绪趋势）、`updown_distribution`（涨跌分布）、`uplimit_trend`（涨停家数趋势）、`sentiment_timing` 等 14 个情绪指标 |
| [07-boards.md](07-boards.md) | **板块数据**：`plates_list`（板块列表）、`plates_rank`（板块排名）、`plates_stocks`（板块成分股）、`plates_trend`（板块分时）、`plates_rank_days`（区间排名）、`market_plate_stocks`（板块人气股）、`market_plate_popular_reason`（板块爆点） |
| [08-hot-topics.md](08-hot-topics.md) | **同花顺热度**：`ths_hot_top`（热度 TopN）、`stock_ths_hot`（个股热度） |
| [09-topic-library.md](09-topic-library.md) | **题材库 / AI 报告 / 异动监控**：`topic_table_list` / `topic_table_detail` / `topic_table_stocks`（题材库表格）、`ai_report_list` / `ai_report_detail`（AI 每日报告）、`movement_alerts`（异动数据）、`zdjk_get`（监管监控） |
| [10-rate-limits.md](10-rate-limits.md) | **频率限制速查表**：14 个核心接口 × {无 token, 有 token} 的限速对照 |

## 通用约定

### 股票代码格式

zzshare 使用 tushare 风格的 `ts_code`（**带点后缀**）。

| 输入 | zzshare ts_code | 备注 |
|---|---|---|
| `600519` | `600519.SH` | 上交所主板 |
| `000001` | `000001.SZ` | 深交所主板 |
| `300750` | `300750.SZ` | 深交所创业板（共享 SZ 后缀） |
| `688981` | `688981.SH` | 上交所科创板（共享 SH 后缀） |
| `830xxx` | `830xxx.BJ` | 北交所 |
| `000001.SS` / `000001.XSHG` | `000001.SH` | SDK 内部已自动规整 |

> ⚠️ **未规整的代码**：`lhb_list` 返回的 `stock_code` 是 6 位裸码（不带 `.SH` / `.SZ`），调用方需要按首位（`6/68 → SH`, `0/3 → SZ`, `8/4/2/9 → BJ`）补后缀。

### 日期与时间格式

| 字段 | 格式 | 示例 |
|---|---|---|
| `date1` / `date2` / `trade_date` / `start_date` / `end_date` | `YYYYMMDD`（**无分隔符**） | `20260520` |
| `day_start` / `day_end` | `YYYYMMDD` | `20250101` |
| `trade_time`（分钟 K） | `YYYYMMDD` 或 `YYYYMMDD HH:MM:SS` | `20260520` / `20260520 14:30:00` |
| `start_time` / `end_time`（分钟 K） | `YYYYMMDD HH:MM:SS` | `20260520 09:30:00` |
| `plates_rank.date1` | `YYYY-MM-DD` 或 `YYYYMMDD` 均可 | `2026-05-20` / `20260520` |

### 复权方式

| 参数值 | 含义 | 说明 |
|---|---|---|
| `""`（默认） | 不复权 | |
| `qfq` | 前复权 | 内部映射为 `candle_mode=1` |
| `hfq` | 后复权 | 内部映射为 `candle_mode=2` |

### 频率限制

完整的接口限速速查表见 [10-rate-limits.md](10-rate-limits.md)。

> 触发 401 / 429 时 SDK 会抛 `ApiAuthError` / `ApiRateLimitError`，自定义重试只对 429 生效（最多 3 次，指数 backoff），不会自动处理 401。

### 响应格式（envelope）

所有接口返回的 HTTP body 形如：

```json
{ "code": 20000, "message": null, "data": ... }
```

- `code == 20000` 或 `200` 表示成功，`data` 字段是真正的业务载荷。
- 失败的 `code`（如 401/429）会被 SDK 转成异常或在 `_query` 内返回 `None`。

`data` 的形状因接口而异：

| 接口族 | `data` 形状 | SDK 已自动转 DataFrame? |
|---|---|---|
| `daily`、`stk_mins`、`stock_basic`、`plate_kline`、`topic_kline` | dict 包裹的 `list` 或裸 `list` | **是**（手工归一化） |
| `trade_days` | 裸 `list[str]`（日期） | 否（直接返回 list） |
| `rt_k` | dict 内的 `list` | **是**（手工归一化） |
| `uplimit_hot` | dict（含 `plate`/`ban_info`/`max_count`） | 否 |
| `uplimit_stocks`、`lhb_list`、`plates_rank`、`ths_hot_top`、`topic_table_*`、`ai_report_*` | 裸 `list[dict]` | 否 |
| `plates_list` | 裸 `list[dict]` | 否 |
| `lhb_detail`、`plates_stocks`、`market_plate_stocks` | list/dict | 否 |

### 排序约定

| 接口 | 默认排序 | 备注 |
|---|---|---|
| `daily` | `trade_date` **降序**（最新在前） | |
| `stk_mins` | `trade_time` **降序** | |
| `lhb_list` / `plates_rank` / `uplimit_*` | 服务端排序，无固定顺序 | |

## 接口能力映射（zzshare → DataCapability）

zzshare 接口与 `data_provider.base.DataCapability` 标志位的对应关系（**仅列接口直接对应的能力**，扩展能力如题材库 / 情绪指数 / AI 报告等未在枚举内的项目，列出原样不做映射）：

| zzshare 接口 | 对应 `DataCapability` 标志 |
|---|---|
| `daily`（d/w/m） | `HISTORICAL_DWM` |
| `stk_mins`（1/5/15/30/60m） | `HISTORICAL_MIN` |
| `rt_k` | `REALTIME_QUOTE` |
| `stock_basic` | `STOCK_LIST` |
| `trade_days` | `TRADE_CALENDAR` |
| `plates_list` / `plates_rank` / `plates_stocks` / `market_plate_stocks` | `STOCK_BOARD` |
| `uplimit_hot` / `uplimit_stocks` | `STOCK_ZT_POOL` |
| `lhb_list` / `lhb_detail` / `lhb_stock_history` / `lhb_trader_history` | `DRAGON_TIGER` |
| `ths_hot_top` / `stock_ths_hot` | `HOT_TOPICS` |
| `stock_info` | **已停用 2026-07-14** — 见下文 § 3；upstream `info_type=1` 对所有 A 股返 null，不再映射为 `STOCK_INFO` |
| `topic_table_list` / `topic_table_detail` / `topic_table_stocks` / `topic_kline` | (无现成 capability) |
| `plate_kline` | (无现成 capability) |
| `ai_report_list` / `ai_report_detail` | (无现成 capability) |
| `market_sentiment` / `market_hot_sentiment` / `market_style` / `open_sentiment_data` / `sentiment_timing` / `sentiment_market_hot_day` / `sentiment_trend` / `sentiment_trend_range` / `updown_distribution` / `uplimit_trend` / `sentiment_hot_day` / `sentiment_bull_data` | (无现成 capability) |
| `uplimit_market_value` | (无现成 capability) |
| `movement_alerts` | (无现成 capability) |
| `zdjk_get` | (无现成 capability) |
| `market_plate_popular_reason` | (无现成 capability) |
| `stock_moneyflow` / `market_mf`（已在 SDK 内注释） | (无现成 capability) |
| `sentiment_market_top_n`（已在 SDK 内注释） | (无现成 capability) |

> zzshare **不支持**的能力（其余 fetcher 覆盖）：
>
> - `INDEX_HISTORICAL` / `INDEX_INTRADAY` / `INDEX_QUOTE`——zzshare 无指数 API
> - `MARGIN_TRADING` / `BLOCK_TRADE` / `HOLDER_NUM` / `DIVIDEND`
> - `FUND_FLOW`——`stock_moneyflow` 和 `market_mf` 已在 SDK 内注释，等同下线
> - `NORTH_FLOW` / `RESEARCH_REPORT` / `ANNOUNCEMENT` / `NEWS_SEARCH` / `NEWS_FLASH`
>
> zzshare **仅支持 csi 市场**（沪深北 A 股），不支持 `hk` / `us`。

## 数据行为细节

- `daily` 返回 DataFrame 的列名是 `vol` / `amount` / `trade_date`（YYYYMMDD 字符串），与项目 `STANDARD_COLUMNS`（`volume` / `amount` / `date` YYYY-MM-DD）不一致，需要 rename + 日期格式化。
- `daily` 的 `pct_chg` 与 `quote_rate` 在 `fields='all'` 时会同时存在但值相等。
- `stk_mins` 不支持复权（`adj` 参数在分钟档不生效）。
- `stock_basic` 的 `area` / `industry` / `list_date` 等字段返回空字符串（zzshare 不填），需要其他 fetcher 兜底。
- `trade_days(days=10)` 实测返回**最近 10 个连续交易日**，不是「向前推 10 天的日期」。
- `lhb_list` 返回的 `stock_code` 是 6 位裸码（无市场后缀），需要自行补 `.SH` / `.SZ`。
- `rt_k` 的 `market_value` 单位为元；`turnover_rate` / `quote_rate` 已是百分数。

## 探针实测记录（2026-06-24）

| 接口 | 实测样本 | 状态 |
|---|---|---|
| `trade_days(days=10)` | 返回 10 个 `YYYY-MM-DD` 日期 | ✅ 匿名 |
| `stock_basic(exchange='ALL', list_status='L')` | DataFrame 5535 行，字段 ts_code/symbol/name/exchange | ✅ 匿名 |
| `daily(ts_code='600519.SH', 20260501~20260515)` | 8 行 DataFrame，含 pre_close/change/pct_chg/vol/amount | ✅ 匿名 |
| `daily(..., adj='qfq')` | 8 行，列相同（具体数值已复权处理） | ✅ 匿名 |
| `stk_mins(ts_code='600519.SH', 20260520, freq='5min')` | 48 行，`trade_time` 形如 `202605201500` | ✅ 匿名 |
| `rt_k(ts_code='600519.SH')` | 1 行 14 列（pre_close/open/high/low/close/vol/amount/ask/bid…） | ✅ 匿名（README 称需 Token，实测单股通过） |
| `stock_info('600519', info_type=1)` | `null` | ⚠️ 需 Token |
| `uplimit_hot('20260520')` | dict 含 `plate` / `ban_info` / `max_count` | ✅ 匿名 |
| `uplimit_stocks('20260520')` | `[]` | ⚠️ 需 Token |
| `lhb_list('20260520')` | list[dict]，`stock_code` 为 6 位裸码（如 `000078`） | ✅ 匿名 |
| `ths_hot_top('20260520', top_n=5)` | list[dict]，含 `symbol_code` / `last_pct` / `rank` | ✅ 匿名 |
| `plates_rank(plate_type=14, '20260520')` | list[dict]，含 `plate_code` / `plate_name` / `rate` | ✅ 匿名 |
| `plates_rank(plate_type=14, date1='2026-05-20')` | 同样成功 | ✅ 匿名（`YYYY-MM-DD` 也接受） |