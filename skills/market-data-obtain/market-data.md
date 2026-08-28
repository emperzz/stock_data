# 行情类 — 端点明细

> 本文件是 `market-data-obtain` 主文件 [§4 行情类](../market-data-obtain.md) 的端点明细。  
> 主文件只列端点路径 + capability + 一句话用途；**字段、单位、调用约束、示例见本文**。  
> 注：项目主战场是 A 股（`market="csi"`），HK / US 端点仅在数据源支持时返回，非主流程。

---

## `GET /api/v1/stocks/{code}/quote`

### 功能

获取个股实时行情。响应含 OHLV + 估值（PE/PB）+ 市值（总 / 流通）+ 量价（换手率/振幅/量比）+ 涨跌停价。

- 主要 fetcher: Zzshare（P2 主力） → Tencent（PE/PB 增强） → 其他（Akshare / Zhitu / Yfinance / Tushare / Myquant）
- `pe_static` 字段**本服务固定返回 `null`**（直接用 `pe_ttm`）
- `limit_up` / `limit_down` 只有 Zzshare / Tencent 返回真实值；其他 fetcher 为 `null`，需要时按 `prev_close × (1 ± 10%)` 自行计算
- `pe_ttm` / `pb` / `mcap_yi` / `float_mcap_yi` / `turnover_pct` / `amplitude_pct` / `vol_ratio` 属于腾讯财经增强；HK / US 端点这些字段多为 `null`

### 入参

| 参数名 | 类型 | 必填 | 默认值 | 约束 |
|---|---|---|---|---|
| `code`（路径） | string | ✅ | — | 6 位 A 股 / `HK00700` / 美股代码；**指数代码（如 `000001`）会被 400 重定向到 `/indices/{code}/quote`**（消息含 "Use /indices/<code>/quote instead"） |
| `source`（query） | string | ❌ | — | 指定 fetcher（不传走 Manager 默认优先级） |

### 返回参数

| 字段 | 类型 | 单位 | 说明 |
|---|---|---|---|
| `current_price` | number | 元 | 当前价 |
| `change` | number | 元 | 涨跌额（`current_price - prev_close`） |
| `change_percent` | number | % | 涨跌幅（正=涨、负=跌） |
| `open` / `high` / `low` / `prev_close` | number | 元 | 今开 / 最高 / 最低 / 昨收 |
| `volume` | number | **股** | 成交量（**单位是股**，1 手 = 100 股） |
| `amount` | number | 元 | 成交额 |
| `pe_ttm` | number | — | 滚动市盈率（Tencent 增强） |
| `pe_static` | null | — | **固定 `null`**（用 `pe_ttm`） |
| `pb` | number | — | 市净率（Tencent 增强） |
| `mcap_yi` | number | **亿元** | 总市值（1 亿 = 1e8 元） |
| `float_mcap_yi` | number | **亿元** | 流通市值 |
| `turnover_pct` | number | % | 换手率（`volume / float_share`） |
| `amplitude_pct` | number | % | 振幅（`(high-low)/prev_close*100`） |
| `vol_ratio` | number | — | 量比（现量 / 过去 5 日同时段均量） |
| `limit_up` | number | 元 | 涨停价（仅 Zzshare / Tencent 返回真实值） |
| `limit_down` | number | 元 | 跌停价（同上） |
| `source` | string | — | 数据来源 fetcher 名（`zzshare` / `tencent` / `akshare` / ...） |

### 示例

```bash
curl 'http://localhost:8888/api/v1/stocks/600519/quote'
curl 'http://localhost:8888/api/v1/stocks/HK00700/quote'
```

---

## `GET /api/v1/stocks/{code}/kline`

### 功能

获取个股 K 线数据。支持日 / 周 / 月 + 1/5/15/30/60 分钟级频率，可选前 / 后复权，可叠加技术指标（`?indicators=`）。

- 主要 fetcher: Zzshare（d/w/m + 5/15/30/60m） → Baostock（d/w/m） → Akshare（1m 主力，无复权） → Yfinance
- `volume` 单位固定**股**（`volume_unit` 始终为 `"share"`）
- `amount` / `change_percent` **缺数据时为 `null`**（不是 `0`）
- `indicators` 字段**仅在传 `?indicators=` 时出现在 JSON 里**；未传则整个字段**从 JSON 省略**（非 `null`），客户端可据此判断是否请求了指标

### 入参

| 参数名 | 类型 | 必填 | 默认值 | 约束 |
|---|---|---|---|---|
| `code`（路径） | string | ✅ | — | 6 位 A 股 / `HK00700` / 美股；指数代码被 400 重定向（参见 `/quote` 注释） |
| `frequency`（query） | string | ✅ | — | `d` / `w` / `m` / `1m` / `5m` / `15m` / `30m` / `60m` |
| `days`（query） | int | ✅ | — | 拉取天数（不同频率上限不同，d≤365 / 1m≤3 / 5m≤5 / 15m≤8 / 30m≤15 / 60m≤30 等） |
| `adjust`（query） | string | ❌ | `none` | `qfq` 前复权 / `hfq` 后复权 / 不传不复权。**⚠️ 1m 频段拒绝 `adjust`**（Akshare 1m 端点不支持复权），传了会 422 |
| `indicators`（query） | string | ❌ | — | 逗号分隔多个指标 key（先 `GET /indicators` 查可用 key） |
| `end_date`（query） | string | ❌ | 今日 | `YYYY-MM-DD`；含今日时若今天为 A 股交易日，可能合并今日 partial bar（d/w/m 频率；分钟级不触发） |

### 返回参数

顶层 `{code, stock_name, period, data[], source}`。`data[]` 每根 K 线：

| 字段 | 类型 | 单位 | 说明 |
|---|---|---|---|
| `date` | string | — | `YYYY-MM-DD`（d/w/m）或 `YYYY-MM-DD HH:MM:SS`（分钟级） |
| `frequency` | string | — | `d` / `w` / `m` / `1m` / `5m` / `15m` / `30m` / `60m`（**每根 K 线自带频率标签**，校验用） |
| `open` / `high` / `low` / `close` | number | 元 | OHLC |
| `volume` | number | **股** | 成交量（**单位固定股**，1 手 = 100 股） |
| `volume_unit` | string | — | 固定 `"share"`（不变式） |
| `amount` | number | 元 | 成交额；**缺数据时为 `null`** |
| `change_percent` | number | % | 涨跌幅；**缺数据时为 `null`** |
| `indicators` | object | — | 例：`{ma5: 12.34, macd_dif: 0.23}`；**仅在传 `?indicators=` 时存在**，未传则整个字段从 JSON 省略 |

### 示例

```bash
# 30 日日 K + MA/MACD 指标
curl 'http://localhost:8888/api/v1/stocks/600519/kline?frequency=d&days=30&indicators=ma,macd'

# 5 分钟级前复权
curl 'http://localhost:8888/api/v1/stocks/600519/kline?frequency=5m&days=5&adjust=qfq'

# 1 分钟级（不允许复权）
curl 'http://localhost:8888/api/v1/stocks/600519/kline?frequency=1m&days=2'
```

---

## `GET /api/v1/stocks/{code}/info`

### 功能

获取个股公司画像（基础信息）。**不**包含股价 / 市值 / PE（要看行情用 `/quote`）。

- 主要 fetcher: Zhitu → Myquant（Zzshare 已移除 2026-07-14——上游 `/v3/open/stock/info` 对所有 A 股返回 null）
- `exchange` 字段 Zhitu / Myquant 填充（`SH` / `SZ` / `BJ`）；其他 fetcher 留 `null`

### 入参

| 参数名 | 类型 | 必填 | 默认值 | 约束 |
|---|---|---|---|---|
| `code`（路径） | string | ✅ | — | 6 位 A 股代码 |

### 返回参数

| 字段 | 类型 | 单位 | 说明 |
|---|---|---|---|
| `code` | string | — | 6 位代码 |
| `name` | string | — | 股票名 |
| `exchange` | string | — | `SH` / `SZ` / `BJ`；**未匹配时为 `null`**（不是空字符串） |
| `industry` | string | — | 行业 |
| `listing_date` | string | — | 上市日 `YYYY-MM-DD` |
| `total_share` | number | **股** | 总股本 |
| `float_share` | number | **股** | 流通股 |
| `reg_capital` | number | 元 | 注册资本 |

### 示例

```bash
curl 'http://localhost:8888/api/v1/stocks/600519/info'
```

---

## `GET /api/v1/stocks`

### 功能

获取股票列表（分页）。含全部 A 股 / 港股 / 美股代码 + 名称 + 市场标签 + 交易所。

- 主要 fetcher: Zzshare（csi） / Akshare（csi / hk）
- `market="csi"` 才是 A 股（**不是 `"cn"`**）
- `exchange` 可能为 `null`（未匹配时）

### 入参

| 参数名 | 类型 | 必填 | 默认值 | 约束 |
|---|---|---|---|---|
| `market`（query） | string | ✅ | — | `csi` / `hk` / `us` |
| `page`（query） | int | ❌ | `1` | 页码 |
| `page_size`（query） | int | ❌ | `50` | 单页条数 |

### 返回参数

顶层结构含 `data[]`。`data[]` 每条：

| 字段 | 类型 | 单位 | 说明 |
|---|---|---|---|
| `code` | string | — | 股票代码（A 股 6 位 / `HK00700` / 美股 1-5 字母） |
| `name` | string | — | 股票名 |
| `market` | string | — | `csi` / `hk` / `us`（**A 股是 `csi`，不是 `cn"`**） |
| `exchange` | string | — | 可能为 `null` |

### 示例

```bash
# A 股列表
curl 'http://localhost:8888/api/v1/stocks?market=csi&page=1&page_size=100'
```

---

## `GET /api/v1/indices`

### 功能

获取指数列表（含 CSI / HK / US 三市场）。数据来源是本地 `index_symbols.py` 映射，不消耗 fetcher 配额。

### 入参

| 参数名 | 类型 | 必填 | 默认值 | 约束 |
|---|---|---|---|---|
| `market`（query） | string | ❌ | 全部 | `csi` / `hk` / `us`（不传则返回全部） |

### 返回参数

顶层结构含 `data[]`。`data[]` 每条：

| 字段 | 类型 | 单位 | 说明 |
|---|---|---|---|
| `code` | string | — | 指数代码（CSI 6 位 / `HK` / `SPX` 等） |
| `name` | string | — | 指数名 |
| `market` | string | — | `csi` / `hk` / `us` |

### 示例

```bash
curl 'http://localhost:8888/api/v1/indices?market=csi'
```

---

## `GET /api/v1/indices/{code}/quote`

### 功能

获取指数实时行情。**字段含义同 `/stocks/{code}/quote`**，但有以下差异：

- **没有** PE / PB / 市值 / 换手率 / 振幅 / 涨跌停价等腾讯增强字段
- `current_price` 单位是**指数点位**（不是元）
- 主要 fetcher: Akshare（csi） / Yfinance（hk / us / csi） / Zhitu（csi，`/hz/` 前缀）

### 入参

| 参数名 | 类型 | 必填 | 默认值 | 约束 |
|---|---|---|---|---|
| `code`（路径） | string | ✅ | — | 指数代码（CSI 6 位 / `HK` / `SPX`） |

### 返回参数

字段集与 `/stocks/{code}/quote` 一致，但 PE / PB / 市值 / 换手率 / 振幅 / 涨跌停价 / 量比 / `pe_static` 均为 `null`；`current_price` 单位是指数点位而非元。

### 示例

```bash
curl 'http://localhost:8888/api/v1/indices/000300/quote'   # 沪深 300
curl 'http://localhost:8888/api/v1/indices/SPX/quote'       # 标普 500
```

---

## `GET /api/v1/indices/{code}/kline`

### 功能

获取指数 K 线。**每根 K 线 shape 与 `/stocks/{code}/kline` 完全一致**，但**指数无复权**——传 `?adjust=qfq|hfq` 会被 422 拒绝。

- 主要 fetcher: Baostock（csi, d/w/m） / Akshare（csi/hk, 5/15/30/60m） / Yfinance / Zhitu（csi, `/hz/` 前缀）

### 入参

| 参数名 | 类型 | 必填 | 默认值 | 约束 |
|---|---|---|---|---|
| `code`（路径） | string | ✅ | — | 指数代码 |
| `frequency`（query） | string | ✅ | — | `d` / `w` / `m` / `1m` / `5m` / `15m` / `30m` / `60m`（指数 1m 仅部分 fetcher 支持） |
| `days`（query） | int | ✅ | — | 拉取天数 |
| `end_date`（query） | string | ❌ | 今日 | `YYYY-MM-DD`；含今日时若今天为 A 股交易日，可能合并今日 partial bar（d/w/m） |
| `indicators`（query） | string | ❌ | — | 逗号分隔多个指标 key |

### 返回参数

`data[]` 每根 K 线字段与 `/stocks/{code}/kline` **完全一致**（OHLCV + `volume_unit="share"` + `amount` / `change_percent` 可为 `null` + `indicators` 仅在 `?indicators=` 时存在）。`adjust` 字段不接受（422）。

### 示例

```bash
curl 'http://localhost:8888/api/v1/indices/000300/kline?frequency=d&days=30&indicators=ma,boll'
```

---

## `GET /api/v1/calendar`

### 功能

获取 A 股交易日历。返回指定年份区间内所有交易日 + 最新一日 + 总天数。

- 主要 fetcher: Zzshare（csi） → Akshare（csi） → Myquant（csi）
- **A 股 only**（不返回 HK / US 交易日历）

### 入参

| 参数名 | 类型 | 必填 | 默认值 | 约束 |
|---|---|---|---|---|
| `start_year`（query） | int | ❌ | `TRADE_CALENDAR_START_YEAR`（默认 1990） | 起始年份 |
| `end_year`（query） | int | ❌ | 当前年 | 结束年份 |

### 返回参数

| 字段 | 类型 | 单位 | 说明 |
|---|---|---|---|
| `trade_dates[]` | array | — | 所有交易日期（升序） |
| `latest_date` | string | — | 最新一日 `YYYY-MM-DD` |
| `total` | number | — | 总天数 |

### 示例

```bash
curl 'http://localhost:8888/api/v1/calendar'
curl 'http://localhost:8888/api/v1/calendar?start_year=2024&end_year=2026'
```
