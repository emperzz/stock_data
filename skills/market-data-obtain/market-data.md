# 行情类 — 端点明细

> 主文件已列端点路径与 capability；本文给出字段、单位、入参约束与示例。项目主战场是 A 股（`market="csi"`），HK / US 仅在数据源支持时返回。

---

## `GET /api/v1/stocks/{code}/quote`

### 功能

获取个股实时行情。响应含 OHLV + 估值（PE/PB）+ 市值（总 / 流通）+ 量价（换手率/振幅/量比）+ 涨跌停价。

- `pe_static` 字段**本服务固定返回 `null`**（用 `pe_ttm`）
- `limit_up` / `limit_down` 由腾讯财经等增强源返回真实值；其他 fetcher 为 `null`，需要时按 `prev_close × (1 ± 10%)` 自行计算
- `pe_ttm` / `pb` / `mcap_yi` / `float_mcap_yi` / `turnover_pct` / `amplitude_pct` / `volume_ratio` 属于腾讯财经增强；HK / US 端点这些字段多为 `null`

### 入参

| 参数名 | 类型 | 必填 | 默认值 | 约束 |
|---|---|---|---|---|
| `code`（路径） | string | ✅ | — | 6 位 A 股 / `HK00700` / 美股代码；**指数代码（如 `000001`）会被 400 重定向到 `/indices/{code}/quote`**（消息含 "Use /indices/<code>/quote instead"） |

> 本端点**不接受任何 query 参数**——传 `period` / `adjust` / `days` / `start_date` / `end_date` / `indicators` 会被显式拒绝（422）。也**没有** `source` 参数用于指定 fetcher。

### 返回参数

顶层 JSON `{code, name, current_price, change_amount, ..., source}`。

| 字段 | 类型 | 单位 | 说明 |
|---|---|---|---|
| `code` | string | — | 股票代码（6 位 A 股 / `HK00700` / 美股代码） |
| `name` | string | — | 股票名 |
| `current_price` | number | 元 | 当前价 |
| `change_amount` | number | 元 | 涨跌额（`current_price - prev_close`） |
| `change_pct` | number | % | 涨跌幅（正=涨、负=跌） |
| `open` / `high` / `low` / `prev_close` | number | 元 | 今开 / 最高 / 最低 / 昨收 |
| `volume` | number | **股** | 成交量（**单位是股**，1 手 = 100 股） |
| `volume_unit` | string | — | 固定 `"share"` |
| `amount` | number | 元 | 成交额 |
| `pe_ttm` | number | — | 滚动市盈率 |
| `pe_static` | null | — | **固定 `null`**（用 `pe_ttm`） |
| `pb` | number | — | 市净率 |
| `mcap_yi` | number | **亿元** | 总市值（1 亿 = 1e8 元） |
| `float_mcap_yi` | number | **亿元** | 流通市值 |
| `turnover_pct` | number | % | 换手率 |
| `amplitude_pct` | number | % | 振幅（`(high-low)/prev_close*100`） |
| `volume_ratio` | number | — | 量比（现量 / 过去 5 日同时段均量） |
| `limit_up` | number | 元 | 涨停价（部分 fetcher 返回真实值） |
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

- `volume` 单位固定**股**（`volume_unit` 始终为 `"share"`）
- `amount` / `change_pct` **缺数据时为 `null`**（不是 `0`）
- `indicators` 字段**仅在传 `?indicators=` 时出现在 JSON 里**；未传则整个字段**从 JSON 省略**（非 `null`），客户端可据此判断是否请求了指标

### 入参

| 参数名 | 类型 | 必填 | 默认值 | 约束 |
|---|---|---|---|---|
| `code`（路径） | string | ✅ | — | 6 位 A 股 / `HK00700` / 美股；指数代码被 400 重定向（参见 `/quote` 注释） |
| `period`（query） | string | ❌ | `daily` | `daily` / `weekly` / `monthly` / `1m` / `5m` / `15m` / `30m` / `60m` |
| `days`（query） | int | ❌ | `30` | 拉取天数；统一约束 `1 ≤ days ≤ 365`（所有频率一致） |
| `start_date`（query） | string | ❌ | `null` | `YYYY-MM-DD`；与 `end_date` / `days` 配合使用 |
| `end_date`（query） | string | ❌ | 今日 | `YYYY-MM-DD`；含今日时若今天为 A 股交易日，可能合并今日 partial bar（d/w/m 频率；分钟级不触发） |
| `adjust`（query） | string | ❌ | `""`（空串） | 仅接受 `qfq` 前复权 / `hfq` 后复权 / 空串不复权；**传 `none` 等其它值会 422**。**分钟级频段路由层不拒绝 `adjust`**，但上游大多不支持复权，结果可能为空或报错 |
| `indicators`（query） | string | ❌ | — | 逗号分隔多个指标 key（先 `GET /indicators` 查可用 key） |

### 返回参数

顶层 `{code, name, period, data[], source}`。`data[]` 每根 K 线：

| 字段 | 类型 | 单位 | 说明 |
|---|---|---|---|
| `date` | string | — | `YYYY-MM-DD`（d/w/m）或 `YYYY-MM-DD HH:MM:SS`（分钟级） |
| `frequency` | string | — | `d` / `w` / `m` / `1m` / `5m` / `15m` / `30m` / `60m`（**每根 K 线自带频率标签**，校验用） |
| `open` / `high` / `low` / `close` | number | 元 | OHLC |
| `volume` | number | **股** | 成交量（**单位固定股**，1 手 = 100 股） |
| `volume_unit` | string | — | 固定 `"share"`（不变式） |
| `amount` | number | 元 | 成交额；**缺数据时为 `null`** |
| `change_pct` | number | % | 涨跌幅；**缺数据时为 `null`** |
| `indicators` | object | — | 例：`{ma5: 12.34, macd_dif: 0.23}`；**仅在传 `?indicators=` 时存在**，未传则整个字段从 JSON 省略 |

### 示例

```bash
# 30 日日 K + MA/MACD 指标
curl 'http://localhost:8888/api/v1/stocks/600519/kline?period=daily&days=30&indicators=ma,macd'

# 5 分钟级前复权
curl 'http://localhost:8888/api/v1/stocks/600519/kline?period=5m&days=5&adjust=qfq'

# 1 分钟级
curl 'http://localhost:8888/api/v1/stocks/600519/kline?period=1m&days=2'

# 指定时间段
curl 'http://localhost:8888/api/v1/stocks/600519/kline?period=daily&start_date=2025-01-01&end_date=2025-12-31'
```

---

## `GET /api/v1/stocks/{code}/info`

### 功能

获取个股公司画像（基础信息）。**不**包含股价 / 市值 / PE（要看行情用 `/quote`）。

- `exchange` 由 code prefix 推断（A 股返 `SH`/`SZ`/`BJ`），其他市场为 `null`
- 股本字段单位为**万股**（不是股）；`registered_capital` 字段是**字符串**（如 `"9.82亿"`），不是数字

### 入参

| 参数名 | 类型 | 必填 | 默认值 | 约束 |
|---|---|---|---|---|
| `code`（路径） | string | ✅ | — | 6 位 A 股代码（HK / US 端点不一定可用） |

### 返回参数

| 字段 | 类型 | 单位 | 说明 |
|---|---|---|---|
| `code` | string | — | 6 位代码 |
| `name` | string | — | 中文名 |
| `ename` | string | — | 英文名（部分 fetcher 返回） |
| `market` | string | — | 市场标签（`csi`） |
| `exchange` | string \| null | — | `SH` / `SZ` / `BJ`；未匹配时为 `null`（不是空字符串） |
| `listed_date` | string | — | 上市日 `YYYY-MM-DD` |
| `delisted_date` | string | — | 退市日 `YYYY-MM-DD`（多数情况下为空字符串） |
| `total_shares` | number \| null | **万股** | 总股本 |
| `float_shares` | number \| null | **万股** | 流通股本 |
| `concepts` | string[] | — | 概念标签列表 |
| `registered_address` | string | — | 注册地址 |
| `registered_capital` | **string** | — | 注册资本（如 `"9.82亿"`，**字符串**，不是 number） |
| `legal_representative` | string | — | 法人代表 |
| `business_scope` | string | — | 经营范围 |
| `established_date` | string | — | 成立日期 `YYYY-MM-DD` |
| `secretary` | string | — | 董秘姓名 |
| `secretary_phone` | string | — | 董秘电话 |
| `secretary_email` | string | — | 董秘邮箱 |
| `source` | string | — | 数据源 fetcher 名（`zhitu` / `myquant`） |

### 示例

```bash
curl 'http://localhost:8888/api/v1/stocks/600519/info'
```

---

## `GET /api/v1/stocks`

### 功能

获取股票列表（分页）。含 A 股 / 港股 / 美股代码 + 名称 + 市场标签 + 交易所。

- `market="csi"` 才是 A 股（**不是 `"cn"`**）
- `exchange` 可能为 `null`（未匹配时）
- `include_quote=true` 返回全市场实时行情快照（单次上游调用、缓存 60s），**仅 `market=csi` 支持**，HK / US 传了会 422
- `sort_by` 必须配合 `include_quote=true` 使用（可排序字段都在行情里）

### 入参

| 参数名 | 类型 | 必填 | 默认值 | 约束 |
|---|---|---|---|---|
| `market`（query） | string | ✅ | — | `csi` / `hk` / `us` |
| `include_quote`（query） | bool | ❌ | `false` | 是否返回实时行情；仅 `market=csi` 支持 |
| `sort_by`（query） | string | ❌ | `null` | 排序键：`change_pct` / `amount` / `turnover_rate` / `price` / `total_mv` / `volume` |
| `sort_order`（query） | string | ❌ | `desc` | `asc` / `desc` |
| `offset`（query） | int | ❌ | `0` | 分页偏移（`ge=0`） |
| `limit`（query） | int | ❌ | `100` | 单页条数（`1 ≤ limit ≤ 10000`） |

### 返回参数

**顶层即数组**（无 `data[]` 包装），每条 `StockInfo`：

| 字段 | 类型 | 单位 | 说明 |
|---|---|---|---|
| `code` | string | — | 股票代码（A 股 6 位 / `HK00700` / 美股 1-5 字母） |
| `name` | string | — | 股票名 |
| `market` | string | — | `csi` / `hk` / `us`（**A 股是 `csi`，不是 `"cn"`**） |
| `exchange` | string \| null | — | 可能为 `null` |
| `quote` | object \| null | — | 仅 `include_quote=true` 时出现，字段集见上文 `/quote`；否则为 `null` |
| `source` | string | — | 列表/行情来源 fetcher 名（或 `persistence`） |

### 示例

```bash
# A 股列表（默认元数据，分页）
curl 'http://localhost:8888/api/v1/stocks?market=csi&offset=0&limit=100'

# A 股 + 实时行情 + 按涨跌幅排序
curl 'http://localhost:8888/api/v1/stocks?market=csi&include_quote=true&sort_by=change_pct&sort_order=desc&limit=50'
```

---

## `GET /api/v1/indices`

### 功能

获取指数列表（含 CSI / HK / US 三市场）。数据来源是本地 `index_symbols.py` 静态映射，不消耗 fetcher 配额。

### 入参

无。

### 返回参数

**顶层即数组**（无 `data[]` 包装），每条：

| 字段 | 类型 | 单位 | 说明 |
|---|---|---|---|
| `code` | string | — | 指数代码（CSI 6 位 / `HK` / `SPX` 等） |
| `name` | string | — | 指数名 |
| `market` | string | — | `csi` / `hk` / `us` |

### 示例

```bash
curl 'http://localhost:8888/api/v1/indices'
```

---

## `GET /api/v1/indices/{code}/quote`

### 功能

获取指数实时行情。**字段集是 `/stocks/{code}/quote` 的严格子集**——不包含 PE / PB / 市值 / 换手率 / 振幅 / 量比 / 涨跌停价；`current_price` 单位是**指数点位**（不是元）。

### 入参

| 参数名 | 类型 | 必填 | 默认值 | 约束 |
|---|---|---|---|---|
| `code`（路径） | string | ✅ | — | 指数代码（CSI 6 位 / `HK` / `SPX`） |

### 返回参数

| 字段 | 类型 | 说明 |
|---|---|---|
| `code` | string | 指数代码 |
| `name` | string | 指数名 |
| `source` | string | 数据来源 fetcher |
| `current_price` | number | 当前点位 |
| `change_amount` | number | 涨跌额（点位） |
| `change_pct` | number | 涨跌幅（%） |
| `open` | number \| null | 今开 |
| `high` | number \| null | 最高 |
| `low` | number \| null | 最低 |
| `prev_close` | number \| null | 昨收 |
| `volume` | number \| null | 成交量 |
| `volume_unit` | string | 固定 `"share"` |
| `amount` | number \| null | 成交额 |
| `update_time` | string \| null | 上游更新时间戳 |

### 示例

```bash
curl 'http://localhost:8888/api/v1/indices/000300/quote'   # 沪深 300
curl 'http://localhost:8888/api/v1/indices/SPX/quote'       # 标普 500
```

---

## `GET /api/v1/indices/{code}/kline`

### 功能

获取指数 K 线。**每根 K 线 shape 与 `/stocks/{code}/kline` 完全一致**，但**指数无复权**——传 `?adjust=qfq|hfq` 会被 422 拒绝。

### 入参

| 参数名 | 类型 | 必填 | 默认值 | 约束 |
|---|---|---|---|---|
| `code`（路径） | string | ✅ | — | 指数代码 |
| `period`（query） | string | ❌ | `daily` | 同 `/stocks/{code}/kline`（指数 1m 仅部分 fetcher 支持） |
| `days`（query） | int | ❌ | `30` | `1 ≤ days ≤ 365` |
| `start_date`（query） | string | ❌ | `null` | `YYYY-MM-DD` |
| `end_date`（query） | string | ❌ | 今日 | `YYYY-MM-DD`；含今日时若今天为 A 股交易日，可能合并今日 partial bar（d/w/m） |
| `indicators`（query） | string | ❌ | — | 逗号分隔多个指标 key |
| `adjust`（query） | string | ❌ | — | **不接受** `qfq` / `hfq`，传了 422 |

### 返回参数

顶层 `{code, name, period, data[], source}`。`data[]` 每根 K 线字段与 `/stocks/{code}/kline` **完全一致**（OHLCV + `volume_unit="share"` + `amount` / `change_pct` 可为 `null` + `indicators` 仅在 `?indicators=` 时存在）。

### 示例

```bash
curl 'http://localhost:8888/api/v1/indices/000300/kline?period=daily&days=30&indicators=ma,boll'
```

---

## `GET /api/v1/calendar`

### 功能

获取 A 股交易日历。返回所有交易日期 + 最新一日 + 总天数。优先读 SQLite 缓存；缓存为空或最新日早于今天时自动刷新，可显式 `?refresh=true` 强制刷新。

- **A 股 only**（不返回 HK / US 交易日历）

### 入参

| 参数名 | 类型 | 必填 | 默认值 | 约束 |
|---|---|---|---|---|
| `refresh`（query） | bool | ❌ | `false` | 强制从上游刷新最新数据；不传时若缓存最新日 < 今日也自动触发后台刷新 |

### 返回参数

| 字段 | 类型 | 单位 | 说明 |
|---|---|---|---|
| `trade_dates[]` | array | — | 所有交易日期（升序） |
| `latest_date` | string | — | 最新一日 `YYYY-MM-DD` |
| `total` | number | — | 总天数 |

### 示例

```bash
curl 'http://localhost:8888/api/v1/calendar'
curl 'http://localhost:8888/api/v1/calendar?refresh=true'
```
