# zzshare · 行情数据（K 线）

> 涵盖 `daily` / `stk_mins` / `plate_kline` / `topic_kline` 四个接口
> 基础 URL：`https://api.zizizaizai.com/v3/market/kline/...`

## 1. `daily` — 日线行情（兼容 tushare）

### 接口

- **HTTP**: `GET /v3/market/kline/day` 或 `GET /v3/market/kline/day/{ts_code}`
- **SDK**: `DataApi.daily(...)` / 模块级 `daily(...)`

### 参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `ts_code` | `str` | 否（与 `trade_date` 二选一） | tushare 风格代码，如 `600519.SH` |
| `trade_date` | `str` | 视情况 | 单日查询 `YYYYMMDD`；`ts_code` 为空时必填 |
| `start_date` | `str` | 否 | `YYYYMMDD` |
| `end_date` | `str` | 否 | `YYYYMMDD` |
| `offset` | `int` | 否 | 分页偏移 |
| `limit` | `int` | 否 | 单股上限 1000，全市场上限 10000（建议 6000） |
| `fields` | `str` | 否 | 逗号分隔字段名；`'all'` 透传 18 字段 |
| `adj` | `str` | 否 | `''`/`'qfq'`/`'hfq'`，内部映射到 `candle_mode` 0/1/2 |
| `candle_mode` | `int` | 否 | 同 `adj`，优先级更高 |

### 返回字段

**默认 11 字段**：

| 字段 | 类型 | 说明 |
|---|---|---|
| `ts_code` | str | 规整后的 tushare 风格代码 |
| `trade_date` | str | `YYYYMMDD` |
| `open` | float | 开盘价 |
| `high` | float | 最高价 |
| `low` | float | 最低价 |
| `close` | float | 收盘价 |
| `pre_close` | float | 昨收 |
| `change` | float | 涨跌额 |
| `pct_chg` | float | 涨跌幅（%） |
| `vol` | float | 成交量（股） |
| `amount` | float | 成交额（元） |

**`fields='all'` 追加字段**：`factor` / `avg_price` / `high_limit` / `low_limit` / `turnover_rate` / `amp_rate` / `quote_rate` / `is_paused` / `is_st`（注意 `volume` / `turnover` 名字会**替代** `vol` / `amount` / `pct_chg`）。

### 数据范围

- 历史日线：**2005 年至今**（20+ 年）
- 单只股票单次请求最多返回 **1000 条**；获取更多历史数据需配合 `offset` 参数分页。
- 全市场数据一次最多 **10000 条**，一般 6000 条可取全市场当日数据。

### 行为细节

- 输出列名是 `vol` / `amount` / `trade_date`，与项目 `STANDARD_COLUMNS`（`volume` / `amount` / `date` YYYY-MM-DD）不一致。
- `pct_chg` 与 `quote_rate` 在 `fields='all'` 时会同时存在但值相等。
- 排序方向：**降序**（最新日期在前）。

### 示例

```python
# 单股区间
df = api.daily(ts_code='600519.SH', start_date='20260501', end_date='20260515')

# 单股分页（每次 100 行 × 3 页）
df = api.daily(ts_code='600871.SH', start_date='20250101', end_date='20260423',
               offset=200, limit=100)

# 全市场快照（单日）
df = api.daily(trade_date='20260515', limit=6000)

# 前复权
df = api.daily(ts_code='600519.SH', start_date='20260101', end_date='20260515',
               adj='qfq')

# 全量字段
df = api.daily(ts_code='600519.SH', start_date='20260501', end_date='20260515',
               fields='all')
```

---

## 2. `stk_mins` — 分钟 K 线（兼容 tushare）

### 接口

- **HTTP**: `GET /v3/market/kline/minute/{ts_code}`
- **SDK**: `DataApi.stk_mins(...)`

### 参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `ts_code` | `str` | ✅ | tushare 风格代码 |
| `freq` | `str` | 否 | `1min` / `5min` / `15min` / `30min` / `60min`，默认 `1min` |
| `trade_time` | `str` | 否 | `YYYYMMDD`（按日查）或 `YYYYMMDD HH:MM:SS`（从该时间点开始） |
| `start_time` | `str` | 否 | 区间起点 `YYYYMMDD HH:MM:SS` |
| `end_time` | `str` | 否 | 区间终点 `YYYYMMDD HH:MM:SS` |
| `count` | `int` | 否 | 返回条数 |

### 三种查询方式

| 方式 | 调用 | 说明 |
|---|---|---|
| 单日 | `trade_time='20260520'` | 该日全部分钟 K |
| 区间 | `start_time='20260520 09:30:00', end_time='20260520 10:00:00'` | 指定时间窗口 |
| 时间点 | `trade_time='20260520 14:30:00'` | 从该点往后取 |

### 返回字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `ts_code` | str | tushare 风格代码 |
| `trade_time` | str | `YYYYMMDDHHMM`（**12 位无分隔符**） |
| `open` / `high` / `low` / `close` | float | OHLC |
| `vol` | float | 成交量 |
| `amount` | float | 成交额 |

### 频率限制

匿名 **30 次/分钟**；Token 用户更高。

### 行为细节

- 返回 DataFrame 按 `trade_time` **降序**排序。
- 列名同样是 `vol` / `amount`（与 `STANDARD_COLUMNS` 的 `volume` 不一致）。
- 分钟级**无复权**（`adj` 参数在分钟档不生效）。

### 示例

```python
# 5 分钟 K，按日查
df = api.stk_mins(ts_code='600000.SH', trade_time='20260520', freq='5min')

# 区间查询
df = api.stk_mins(ts_code='000001', start_time='20260520 09:30:00',
                  end_time='20260520 10:00:00', freq='1min')

# 5 分钟 K，按 1000 条返回（高频场景）
df = api.stk_mins(ts_code='600519.SH', trade_time='20260520',
                  freq='5min', count=1000)
```

---

## 3. `plate_kline` — 板块日线行情

> 用于查看「同花顺全 A」（代码 `883957`）等板块指数的全市场成交量走势。

**⚠️ 上游限制（实测 2026-06-25）**：`plate_kline` 仅支持 board code `883957`（同花顺全A）。
其他板块代码（概念/行业/题材，如 `710002`、`881101`、`881121`、`801001`、`801660`）均返回空 DataFrame。
这是 zzshare 上游 API 的硬性约束，不是 fetcher 的 bug。
替代方案：`plates_trend` 可获取板块每日涨跌幅/资金流向（非 OHLC K线）。

### 接口

- **HTTP**: `GET /v3/market/kline/plate/{b_code}`
- **SDK**: `DataApi.plate_kline(...)`

### 参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `b_code` | `str` | ✅ | 板块代码（如 `883957` 同花顺全 A） |
| `date1` | `str` | 否 | 起始日期 `YYYYMMDD` |
| `date2` | `str` | 否 | 截止日期 `YYYYMMDD` |

### 返回（实测 2026-06-25）

DataFrame 列（以 `plate_kline(b_code='883957', date1='20260515', date2='20260520')` 实测）:

| 字段 | dtype | 说明 |
|---|---|---|
| `b_id` | int | 板块代码（同入参 `b_code`） |
| `b_name` | str | 板块名称（UTF-8，gbk 编码需解码） |
| `id` | int | 行 ID（板块日内递增序号，非日期） |
| `platform` | int | 平台代码（恒为 `1`） |
| `quote_rate` | float | 涨跌幅（%，与 stock `daily.pct_chg` 同义） |
| `p_close` | float | 收盘价 |
| `p_low` | float | 最低价 |
| `p_prev_close` | float | 昨收 |
| `turnover` | float | 成交额（元） |
| `date` | str | 日期 `YYYY-MM-DD` |
| `p_open` | float | 开盘价 |
| `p_high` | float | 最高价 |
| `volume` | float | 成交量（股） |
| `trade_date` | str | 日期 `YYYYMMDD`（与 `date` 等价，另一种格式） |

行数：返回区间内的实际交易日数；上例 4 天（5/15、5/18、5/19、5/20）。

排序：**升序**（最早日期在前；与 stock `daily` 的降序相反）。

索引：默认 `RangeIndex`（无 `DatetimeIndex`）。

日期列说明：`date` 与 `trade_date` 同时存在且值一一对应（`YYYY-MM-DD` vs `YYYYMMDD`），下游需选其一即可。

注意：OHLC 全部带 `p_` 前缀（与 stock `daily` 的 `open/high/low/close` 无前缀不同）；成交量是 `volume` 而非 `vol`；成交额是 `turnover` 而非 `amount`。归一化时需做列名映射。

### 示例

```python
df = api.plate_kline(b_code='883957', date1='20240101', date2='20260520')
```

---

## 4. `topic_kline` — 题材合成指数 K 线

### 接口

- **HTTP**: `GET /v3/topic/table/{tid}/kline`
- **SDK**: `DataApi.topic_kline(...)`

### 参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `tid` | `int` | ✅ | 题材库表格 ID（来自 `topic_table_list`） |
| `start_date` | `str` | 否 | 起始日期 |

### 返回

DataFrame（`plate_kline_to_df` 后处理）。