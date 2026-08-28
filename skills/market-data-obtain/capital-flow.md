# 资金面 — 端点明细

> 本文件是 `market-data-obtain` 主文件 [§5 资金面](../market-data-obtain.md) 的端点明细。  
> 主文件只列端点路径 + capability + 一句话用途；**字段、单位、调用约束、示例见本文**。

---

## `GET /api/v1/stocks/{stock_code}/fund-flow`

### 功能

个股**分钟级**资金流。响应顶层 `type="minute"`。

- 主要 fetcher: Zhitu（P5 唯一实现）
- 主力 / 超大单 / 大单 / 中单 / 小单 5 级拆分
- 通常阈值：`|main_net| > 1e7`（1 千万）才视为显著；**别用 absolute amount 与换手率/涨跌幅混着判断**

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

- 主要 fetcher: Zhitu
- 字段语义同 `/fund-flow`（分钟级），仅时间字段从 `time` 变为 `date`

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

- 主要 fetcher: Ths（P7 唯一实现）

### 入参

无。

### 返回参数

顶层结构含 `records[]`。`records[]` 每条：

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

个股融资融券数据。杠杆情绪观察：`rzye`（融资余额）趋势 + `rzmre - rzche`（融资买入 - 融资偿还）增量；融券量小，多数场景只看融资侧。

- 主要 fetcher: EastMoney

### 入参

| 参数名 | 类型 | 必填 | 默认值 | 约束 |
|---|---|---|---|---|
| `stock_code`（路径） | string | ✅ | — | 6 位 A 股代码 |

### 返回参数

顶层结构含 `records[]`。`records[]` 每条：

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

- 主要 fetcher: EastMoney

### 入参

| 参数名 | 类型 | 必填 | 默认值 | 约束 |
|---|---|---|---|---|
| `stock_code`（路径） | string | ✅ | — | 6 位 A 股代码 |

### 返回参数

顶层结构含 `records[]`。`records[]` 每条：

| 字段 | 类型 | 单位 | 说明 |
|---|---|---|---|
| `date` | string | — | 成交日期 `YYYY-MM-DD` |
| `price` | number | 元 | 成交价 |
| `close` | number | 元 | 当日收盘价 |
| `premium_pct` | number | % | 溢价率（正=溢价、负=折价） |
| `vol` | number | 股 | 成交量 |
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

股东户数变化。`change_num` 减少通常视为筹码集中（看多信号之一）。

- 主要 fetcher: EastMoney → Zhitu

### 入参

| 参数名 | 类型 | 必填 | 默认值 | 约束 |
|---|---|---|---|---|
| `stock_code`（路径） | string | ✅ | — | 6 位 A 股代码 |

### 返回参数

顶层结构含 `records[]`。`records[]` 每条：

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
