# zzshare · 基础数据

> 涵盖 `stock_basic` / `trade_days` / `stock_info` 三个接口

## 1. `stock_basic` — 全市场股票列表（兼容 tushare）

### 接口

- **HTTP**: 内部按 `exchange` 拆分为多次 `GET /v3/open/stocks/list`（每次一个市场）
- **SDK**: `DataApi.stock_basic(...)`

### 参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `exchange` | `str` | 否 | 见下表；空字符串表示全市场 |
| `list_status` | `str` | 否 | `L`（上市）/ `D`（退市）/ `P`（上市暂停，仅占位返回空表） |
| `ts_code` | `str` | 否 | 多个用逗号分隔的精确过滤 |
| `name` | `str` | 否 | 名称子串模糊过滤 |
| `is_hs` | `str` | 否 | `H` / `S` 时强制返回空表 |
| `fields` | `str` | 否 | 逗号分隔字段名 |

### `exchange` 取值

| 输入 | 含义 |
|---|---|
| `SSE` / `SH` / `SS` | 上交所主板 |
| `KSH` / `STAR` | 上交所科创板 |
| `SZSE` / `SZ` | 深交所主板（含创业板） |
| `BSE` / `BJ` | 北交所 |
| `GEM` | 创业板（独立后端维度） |
| `ALL` | 全市场（实测 5535 行，覆盖 5 个子市场） |

### 返回字段（默认 15 列）

| 字段 | 类型 | 说明 |
|---|---|---|
| `ts_code` | str | 规整后的 tushare 代码 |
| `symbol` | str | 6 位裸码 |
| `name` | str | 中文名 |
| `area` | str | 注册地（**zzshare 不填**，留空） |
| `industry` | str | 行业（**zzshare 不填**，留空） |
| `fullname` | str | 公司全名（= name） |
| `enname` / `cnspell` | str | 拼音 / 英文名（zzshare 不填） |
| `market` | str | `创业板` / `科创板` / `""` |
| `exchange` | str | `SSE` / `SZSE` / `BSE` |
| `curr_type` | str | 固定 `CNY` |
| `list_status` | str | `L` / `D` |
| `list_date` / `delist_date` | str | `YYYYMMDD`（zzshare 不填） |
| `is_hs` | str | 沪深港通标记（zzshare 不填） |

### 行为细节

- 与项目内 `persistence.stock_list` 的列对比，**`area` / `industry` / `list_date` 全为空**。
- `exchange=ALL` 内部会发 5 次 HTTP 请求（每个子市场一次）。
- `list_status='P'` 当前永远返回空表（带正确 schema），保留是为了 tushare 兼容。

### 示例

```python
# 全市场
df = api.stock_basic(exchange='ALL', list_status='L')

# 单交易所
df = api.stock_basic(exchange='SSE', list_status='L')

# 名称模糊查（找茅台的代码）
df = api.stock_basic(name='茅台')
```

---

## 2. `trade_days` — 交易日历

### 接口

- **HTTP**: `GET /market/trade/days`
- **SDK**: `DataApi.trade_days(...)`

### 参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `day_start` | `str` | 否 | 起始日期 `YYYYMMDD` |
| `day_end` | `str` | 否 | 截止日期 `YYYYMMDD` |
| `days` | `int` | 否 | 向前推 N 天（与 `day_start` 互斥） |

### 返回

```python
['2026-06-10', '2026-06-11', '2026-06-12', ..., '2026-06-24']  # list[str]
```

> 格式已是 **`YYYY-MM-DD`**。

### 行为细节

- `days` 参数是「向前推」，**实测**返回的是**最近 N 个连续交易日**（如 `days=10` 返回最近 10 个交易日），不是「向前推 10 天的日历」。

### 示例

```python
days = api.trade_days(days=10)            # 最近 10 个交易日
days = api.trade_days(day_start='20260101', day_end='20260630')  # 区间
```

---

## 3. `stock_info` — 个股公司画像

### 接口

- **HTTP**: `GET /v3/open/stock/info`
- **SDK**: `DataApi.stock_info(...)`

### 参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `stock_id` | `str` | ✅ | 6 位裸码（如 `600519`） |
| `info_type` | `int` | ✅ | 子表类型（**SDK 未公开 enum**，需实测枚举） |

### 频率限制

**实测匿名调用返回 `null`**——需 Token。

### 示例

```python
info = api.stock_info(stock_id='600519', info_type=1)
```