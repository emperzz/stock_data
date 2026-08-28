# 资金面 — 端点明细

> 主文件已列端点路径与 capability；本文给出字段、单位、入参约束与示例。

---

## `GET /api/v1/stocks/{stock_code}/fund-flow`

### 功能

个股**分钟级**资金流。响应顶层 `type="minute"`。主力 / 超大单 / 大单 / 中单 / 小单 5 级拆分。

### 入参

| 参数名 | 类型 | 必填 | 默认值 | 约束 |
|---|---|---|---|---|
| `stock_code`（路径） | string | ✅ | — | 6 位 A 股代码 |

### 返回参数

顶层 `{code, name, type, records[], source}`，`type="minute"`。`records[]` 每条：

| 字段 | 类型 | 单位 | 说明 |
|---|---|---|---|
| `time` | string | — | 时间 `HH:mm` |
| `main_net` | number | 元 | 主力净流入（**正=流入、负=流出**） |
| `super_net` | number | 元 | 超大单净流入 |
| `large_net` | number | 元 | 大单净流入 |
| `mid_net` | number | 元 | 中单净流入 |
| `small_net` | number | 元 | 小单净流入 |

### 示例

```bash
curl 'http://localhost:8888/api/v1/stocks/600519/fund-flow'
```

---

## `GET /api/v1/stocks/{stock_code}/fund-flow/daily`

### 功能

个股**近 120 个交易日**资金流（日级）。响应顶层 `type="daily"`。

字段语义同 `/fund-flow`（分钟级），仅时间字段从 `time` 变为 `date`。

### 入参

| 参数名 | 类型 | 必填 | 默认值 | 约束 |
|---|---|---|---|---|
| `stock_code`（路径） | string | ✅ | — | 6 位 A 股代码 |

### 返回参数

顶层 `{code, name, type, records[], source}`，`type="daily"`。`records[]` 每条：

| 字段 | 类型 | 单位 | 说明 |
|---|---|---|---|
| `date` | string | — | 日期 `YYYY-MM-DD` |
| `main_net` | number | 元 | 主力净流入 |
| `super_net` | number | 元 | 超大单净流入 |
| `large_net` | number | 元 | 大单净流入 |
| `mid_net` | number | 元 | 中单净流入 |
| `small_net` | number | 元 | 小单净流入 |

### 示例

```bash
curl 'http://localhost:8888/api/v1/stocks/600519/fund-flow/daily'
```

---

## `GET /api/v1/north-flow/realtime`

### 功能

北向资金实时累计净买入。`hgt_yi`（沪股通）+ `sgt_yi`（深股通）= 北向资金合计。

- 当前仅 ThsFetcher 实现此端点（其他 fetcher 未声明 NORTH_FLOW capability）

### 入参

无。

### 返回参数

顶层 `{records[], source}`。`records[]` 每条：

| 字段 | 类型 | 单位 | 说明 |
|---|---|---|---|
| `time` | string | — | 时间 `HH:mm` |
| `hgt_yi` | number | 亿元 | 沪股通累计净买入 |
| `sgt_yi` | number | 亿元 | 深股通累计净买入 |

### 示例

```bash
curl 'http://localhost:8888/api/v1/north-flow/realtime'
```

---

## `GET /api/v1/stocks/{stock_code}/margin`

### 功能

个股融资融券数据。`rzye`（融资余额）+ `rzrqye`（融资融券余额合计）为常用指标，`rzmre - rzche` 为当日融资净买入额。

### 入参

| 参数名 | 类型 | 必填 | 默认值 | 约束 |
|---|---|---|---|---|
| `stock_code`（路径） | string | ✅ | — | 6 位 A 股代码 |
| `page_size`（query） | int | ❌ | `30` | 返回条数（`1 ≤ page_size ≤ 100`） |

### 返回参数

顶层 `{code, name, records[], source}`。`records[]` 每条：

| 字段 | 类型 | 单位 | 说明 |
|---|---|---|---|
| `date` | string | — | 日期 `YYYY-MM-DD` |
| `rzye` | number | 元 | 融资余额 |
| `rzmre` | number | 元 | 融资买入额 |
| `rzche` | number | 元 | 融资偿还额 |
| `rqye` | number | 元 | 融券余额 |
| `rqmcl` | number | 股 | 融券卖出量 |
| `rqchl` | number | 股 | 融券偿还量 |
| `rzrqye` | number | 元 | 融资融券余额合计 |

### 示例

```bash
curl 'http://localhost:8888/api/v1/stocks/600519/margin'
```

---

## `GET /api/v1/stocks/{stock_code}/block-trade`

### 功能

个股大宗交易数据。`premium_pct` 正值=溢价成交、负值=折价成交。

### 入参

| 参数名 | 类型 | 必填 | 默认值 | 约束 |
|---|---|---|---|---|
| `stock_code`（路径） | string | ✅ | — | 6 位 A 股代码 |
| `page_size`（query） | int | ❌ | `20` | 返回条数（`1 ≤ page_size ≤ 100`） |

### 返回参数

顶层 `{code, name, total, records[], source}`。`records[]` 每条：

| 字段 | 类型 | 单位 | 说明 |
|---|---|---|---|
| `date` | string | — | 成交日期 `YYYY-MM-DD` |
| `price` | number | 元 | 成交价 |
| `close` | number | 元 | 当日收盘价 |
| `premium_pct` | number | % | 溢价率（正=溢价、负=折价） |
| `volume` | number | 股 | 成交量 |
| `amount` | number | 元 | 成交额 |
| `buyer` | string | — | 买方营业部（如"机构专用"、"中信证券"） |
| `seller` | string | — | 卖方营业部 |

### 示例

```bash
curl 'http://localhost:8888/api/v1/stocks/600519/block-trade'
```

---

## `GET /api/v1/stocks/{stock_code}/holder-num`

### 功能

股东户数变化。`change_num` 与 `change_ratio` 反映户数环比变化。

### 入参

| 参数名 | 类型 | 必填 | 默认值 | 约束 |
|---|---|---|---|---|
| `stock_code`（路径） | string | ✅ | — | 6 位 A 股代码 |
| `page_size`（query） | int | ❌ | `10` | 返回条数（`1 ≤ page_size ≤ 50`） |

### 返回参数

顶层 `{code, name, records[], source}`。`records[]` 每条：

| 字段 | 类型 | 单位 | 说明 |
|---|---|---|---|
| `date` | string | — | 报告期 `YYYY-MM-DD` |
| `holder_num` | number | — | 股东户数 |
| `change_num` | number | — | 较上期变化（**正=户数增加、负=减少**） |
| `change_ratio` | number | % | 环比变化率 |
| `avg_shares` | number | 股 | 户均持股 |

### 示例

```bash
curl 'http://localhost:8888/api/v1/stocks/600519/holder-num'
```
