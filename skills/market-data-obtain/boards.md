# 特殊池 & 板块 — 端点明细

> 本文件是 `market-data-obtain` 主文件 [§9 特殊池 & 板块](../market-data-obtain.md) 的端点明细。  
> 主文件只列端点路径 + capability + 一句话用途；**字段、单位、调用约束、示例见本文**。  
> **板块数据源选择**：推荐显式传 `?source=ths`（ths 接口覆盖全、稳定性最好）；其他 source 的板块定义不保证与 ths 互通。

---

## 板块类型总览

4 种类型，以 `source=ths` 的分类为默认参考：

| 类型 | 含义 | ths 支持 | ths subtype | 典型代码前缀 | 其他 source |
|---|---|---|---|---|---|
| `concept` | 概念板块（题材/热点） | ✅ | `同花顺概念` / `同花顺题材` | `885xxx` | eastmoney（无 subtype 拆分）/ zhitu（`热门概念` / `概念板块` / `地域板块`） |
| `industry` | 行业板块 | ✅ | `同花顺行业` | `881xxx` | eastmoney / zhitu（`申万行业` / `申万二级` / `证监会行业`） |
| `index` | 大盘/分类指数 | ❌ | — | — | **仅 zhitu**（`分类` / `指数成分` / `大盘指数`） |
| `special` | 特殊池（风险警示/次新/沪深港通） | ❌ | — | — | **仅 zhitu**（`风险警示` / `次新股` / `沪港通` / `深港通`） |

**关键约束**：
- `source=ths` **只覆盖 `concept` + `industry` 两类**；要查 `index` / `special` 必须 `?source=zhitu`
- 不传 `?type=` = 默认查该 source 支持所有类型
- **跨 source 含义不同**：同名"互联网服务"概念，ths 与 eastmoney 的成分股集合**不保证一致**，默认 `source=ths` 可避免跨源语义混淆
- **错误示例**：`?source=ths&type=index` → 400；`?source=eastmoney&type=index` → 400

---

## 板块端点通用入参

下面这些参数在多个板块端点上语义一致，**详见各端点入参表的 `约束` 列**：

| 参数 | 端点 | 说明 |
|---|---|---|
| `source` | `/boards`、`/boards/{code}/stocks`、`/stocks/{code}/boards` | `ths` / `eastmoney` / `zhitu`；`zzshare` 已下线（部分端点仍以别名兼容） |
| `type` | `/boards`、`/stocks/{code}/boards` | 板块类型过滤 |
| `subtype` | `/boards`、`/stocks/{code}/boards` | source 专属 subtype（ths=`同花顺概念` 等）；需配合 `type` 才有意义 |
| `include_quote` | `/boards`、`/boards/{code}/stocks` | `true` 时每条带报价字段；不传 = `false` |
| `sort_by` | `/boards`、`/boards/{code}/stocks` | 排序键；**两个端点都强制要求 `include_quote=true` 且 `source='ths'`**（任一不满足 → 400 `invalid_combination`） |
| `sort_order` | `/boards`、`/boards/{code}/stocks` | `asc` / `desc`；默认 `desc` |
| `top_n` | `/boards/{code}/stocks` | 限制返回条数；默认 50（THS 上游硬上限） |
| `refresh` | `/boards`、`/boards/{code}/stocks`、`/zt-pools` | 强制从上游刷新；默认 `false` |

**`/boards/{code}/stocks` `source='ths'&include_quote=false` 的兜底**：`effective_source` 字段暴露实际服务的 fetcher（`ths` / `zzshare`）——读它判断是否走了兜底，不要读 `data_source`（缓存命中时固定为 `persistence`）。

**`/quote`、`/news`、`/surges` 三端点为 THS 单源**：
- `/quote`：**无 `source` 入参**——`get_board_realtime` 仅 ThsFetcher 实现；其他 fetcher 拼接 `?source=zzshare` 会被 FastAPI 静默忽略但也不会换源
- `/news` / `/surges`：有 `source: Literal["ths"]` 入参（默认 `ths`），传非 ths → 422

---

## `GET /api/v1/boards`

### 功能

获取板块清单（概念 / 行业 / 指数 / 特殊四类）。**`?source=` 必填**。可叠加 `?include_quote=true` 获取板块实时报价。

- 主要 fetcher: ths（默认推荐）/ eastmoney / zhitu
- `?sort_by=` 排序必须配合 `?include_quote=true`，否则 400

### 入参

| 参数名 | 类型 | 必填 | 默认值 | 约束 |
|---|---|---|---|---|
| `source`（query） | string | ✅ | — | `ths` / `eastmoney` / `zhitu` |
| `type`（query） | string | ❌ | 全部（受 source 支持范围限制） | `concept` / `industry` / `index` / `special` |
| `subtype`（query） | string | ❌ | — | source 专属 subtype（ths=`同花顺概念` 等）；**必须配合 `type`**，否则 400 |
| `include_quote`（query） | bool | ❌ | `false` | `true` 时每条带报价字段 |
| `sort_by`（query） | string | ❌ | — | `change_pct` / `volume` / `amount` / `price`；**必须配合 `include_quote=true`**（否则 400） |
| `sort_order`（query） | string | ❌ | `desc` | `asc` / `desc` |
| `limit`（query） | int | ❌ | 全部 | 1-500；限制返回条数 |
| `refresh`（query） | bool | ❌ | `false` | 强制从上游刷新 |

### 返回参数

顶层结构含 `data[]`。**报价字段仅在 `?include_quote=true` 时填充**。`data[]` 每条：

| 字段 | 类型 | 单位 | 必有 | 说明 |
|---|---|---|---|---|
| `code` | string | — | 始终 | 板块代码（ths=`885xxx`/`881xxx`；eastmoney=`BKxxxx`；zhitu=`sw_xxx`） |
| `name` | string | — | 始终 | 板块名 |
| `type` | string | — | 始终 | `concept` / `industry` / `index` / `special` |
| `price` | number | 指数点位 | `include_quote=true` | 板块指数点位 |
| `change_pct` | number | % | `include_quote=true` | 涨跌幅 |
| `change_amount` | number | 指数点位 | `include_quote=true` | 涨跌额 |
| `volume` | number | 股 | `include_quote=true` | 板块成交量 |
| `amount` | number | 元 | `include_quote=true` | 板块成交额 |
| `turnover_pct` | number | % | `include_quote=true` | 换手率 |
| `total_mv` | number | 元 | `include_quote=true` | 总市值 |
| `up_count` | number | — | `include_quote=true` | 板块内上涨家数 |
| `down_count` | number | — | `include_quote=true` | 板块内下跌家数 |
| `leading_stock` | string | — | `include_quote=true` | 龙头股名 |
| `leading_stock_price` | number | 元 | `include_quote=true` | 龙头股价 |
| `leading_stock_pct` | number | % | `include_quote=true` | 龙头股涨幅 |
| `net_inflow` | number | **亿元** | **仅 industry** | 资金净流入（其他类型固定 `null`） |

### 示例

```bash
# ths 概念板块清单
curl 'http://localhost:8888/api/v1/boards?source=ths&type=concept'

# 行业板块带报价，按涨幅倒序前 10
curl 'http://localhost:8888/api/v1/boards?source=ths&type=industry&include_quote=true&sort_by=change_pct&limit=10'
```

---

## `GET /api/v1/boards/{board_code}/stocks`

### 功能

获取板块成分股。**`?source=` 必填**。THS 上游额外暴露 6 字段（涨速/量比/振幅/流通股/流通市值/市盈率）。

- 主要 fetcher: ths（默认）/ eastmoney / zhitu
- THS 上游 50 股登录墙：`include_quote=true` 时服务器额外调一次 ZZSHARE membership 补全无报价成员；看 `quote_truncated` + `quote_total_in_board` 判断是否截断

### 入参

| 参数名 | 类型 | 必填 | 默认值 | 约束 |
|---|---|---|---|---|
| `board_code`（路径） | string | ✅ | — | 板块代码（ths=`885xxx` / `881xxx`；eastmoney=`BKxxxx`） |
| `source`（query） | string | ✅ | — | `ths` / `eastmoney` / `zhitu` |
| `include_quote`（query） | bool | ❌ | `false` | `true` 时每条带报价字段 |
| `refresh`（query） | bool | ❌ | `false` | 强制从上游刷新（绕开持久化缓存） |
| `sort_by`（query） | string | ❌ | — | 排序键（**仅 `source='ths'` + `include_quote=true` 时生效**；否则 400） |
| `sort_order`（query） | string | ❌ | `desc` | `asc` / `desc`；同上约束 |
| `top_n`（query） | int | ❌ | `50` | 1-50；THS 上游硬上限 |
| `with_zt_flags`（query） | bool | ❌ | `false` | `true` 时额外拉涨停池并打标（每条 `is_limit_up` + `lb_count`） |

### 返回参数

| 字段 | 类型 | 单位 | 说明 |
|---|---|---|---|
| `board` | object | — | 板块简表（字段同 `/boards` 必有列） |
| `stocks[]` | array | — | 成分股列表 |
| `stocks[].code` / `name` | string | — | 成分股代码 / 名 |
| `stocks[].price` | number | 元 | 成分股当前价（`include_quote=true` 才有） |
| `stocks[].change_pct` | number | % | 涨跌幅（同上） |
| `stocks[].change_amount` | number | 元 | 涨跌额（同上） |
| `stocks[].volume` | number | 股 | 成交量（同上） |
| `stocks[].amount` | number | 元 | 成交额（同上） |
| `stocks[].turnover_pct` | number | % | 换手率（同上） |
| `stocks[].change_speed` | number | % | 涨速（**仅 THS**） |
| `stocks[].volume_ratio` | number | — | 量比（**仅 THS**） |
| `stocks[].amplitude_pct` | number | % | 振幅（**仅 THS**） |
| `stocks[].free_float_shares` | number | 股 | 流通股（**仅 THS**） |
| `stocks[].float_market_cap` | number | 元 | 流通市值（**仅 THS**） |
| `stocks[].pe_ratio` | number | — | 市盈率（**仅 THS**） |
| `query_source` | string | — | 用户传入的 `?source=` |
| `data_source` | string | — | 缓存来源；`'persistence'` = 缓存命中，**不是**用户选择 |
| `effective_source` | string | — | **实际服务 fetcher**（`ths` / `zzshare` / `eastmoney` / `zhitu`）；用于判断是否走了 ZZSHARE 兜底 |
| `quote_source` | string / null | — | 板块级实时报价的 fetcher（仅 `include_quote=true` 时尝试填充） |
| `quote_error` | string / null | — | `null` 或 `unsupported` / `board_type_unresolved` / `upstream_failed: ...` |
| `quote_truncated` | bool | — | 报价是否被 `top_n` 截断后用 ZZSHARE 补全 |
| `quote_top_n` | int | — | 截断点（仅 `sort_by` / `top_n` 显式传时回显） |
| `quote_total_in_board` | int | — | 板块总成分股数（仅 `sort_by` / `top_n` 显式传时回显） |
| `quote_sort_by` | string / null | — | 排序键回显（同上） |
| `quote_sort_order` | string / null | — | 排序方向回显（同上） |

### 示例

```bash
# THS 概念板块成分股（不带报价，可能走 ZZSHARE 兜底）
curl 'http://localhost:8888/api/v1/boards/885595/stocks?source=ths'

# THS 行业板块成分股（带报价，按涨幅排序前 10）
curl 'http://localhost:8888/api/v1/boards/881270/stocks?source=ths&include_quote=true&sort_by=change_pct&top_n=10'
```

---

## `GET /api/v1/boards/{board_code}/quote`

### 功能

获取板块实时行情。**THS 唯一实现**（其他 fetcher 不支持板块实时行情）。`source` 路由层不开放。

- `volume` 上游返回**万手**，已由 fetcher 用 `safe_int` 截断为整数（精度损失约 0.005%）
- `amount` 单位是**元**（route 层 ×1e8 转换自上游的亿元）
- `net_inflow` 单位是**亿元**（route 层不转换）
- `rank` 形如 `"229/389"`（涨幅排名字符串）

### 入参

| 参数名 | 类型 | 必填 | 默认值 | 约束 |
|---|---|---|---|---|
| `board_code`（路径） | string | ✅ | — | THS 板块代码（`885xxx` / `881xxx`） |

### 返回参数

| 字段 | 类型 | 单位 | 说明 |
|---|---|---|---|
| `code` | string | — | 板块代码 |
| `board_name` | string | — | 板块名（**注意字段名是 `board_name`，不是 `name`**） |
| `source` | string | — | 实际数据来源 fetcher（当前固定 `ths`） |
| `price` | number | 指数点位 | 板块当前点位 |
| `change_pct` | number | % | 涨跌幅 |
| `change_amount` | number | 指数点位 | 涨跌额 |
| `open` / `high` / `low` / `prev_close` | number | 指数点位 | 今开 / 高 / 低 / 昨收 |
| `volume` | number | **万手（整数）** | 成交量（**注意单位是万手**） |
| `amount` | number | **元** | 成交额（route 层 ×1e8 转自上游亿元） |
| `net_inflow` | number | 亿元 | 资金净流入 |
| `up_count` | number | — | 上涨家数 |
| `down_count` | number | — | 下跌家数 |
| `rank` | string | — | 涨幅排名，**形如 `"229/389"`**（字符串） |

### 示例

```bash
curl 'http://localhost:8888/api/v1/boards/885595/quote'
```

---

## `GET /api/v1/boards/{board_code}/news`

### 功能

获取板块新闻（THS 唯一实现，走 `news.10jqka.com.cn` timeline）。

- `summary` THS 上游可能为空字符串
- 分页 `?limit=1-50`；游标分页**无** 14 条硬上限

### 入参

| 参数名 | 类型 | 必填 | 默认值 | 约束 |
|---|---|---|---|---|
| `board_code`（路径） | string | ✅ | — | THS 板块代码 |
| `limit`（query） | int | ❌ | `20` | 1-50 |
| `source`（query） | string | ❌ | `ths` | 路由 Literal 锁死，传非 `ths` → 422 |

### 返回参数

顶层 `{code, source, total, data[]}`。`data[]` 每条：

| 字段 | 类型 | 单位 | 说明 |
|---|---|---|---|
| `title` | string | — | 新闻标题 |
| `url` | string | — | 详情页 URL |
| `publish_date` | string | — | 发布日期 |
| `publish_time` | string | — | 发布时间（精确） |
| `summary` | string | — | 摘要；THS 上游可能为空字符串 |
| `source_domain` | string | — | 默认 `news.10jqka.com.cn` |

### 示例

```bash
curl 'http://localhost:8888/api/v1/boards/885595/news?limit=20'
```

---

## `GET /api/v1/boards/{board_code}/surges`

### 功能

获取板块炒作周期数据（F10 峰值周期，THS 唯一实现）。含板块涨幅 / 上证对比 / 涨停家数 / 涨停股列表。

- `sh_change_pct` **用上证做基准对比**
- `up_count` / `down_count` **F10 未暴露，固定 `null`**

### 入参

| 参数名 | 类型 | 必填 | 默认值 | 约束 |
|---|---|---|---|---|
| `board_code`（路径） | string | ✅ | — | THS 板块代码 |
| `limit`（query） | int | ❌ | `5` | 1-12 |
| `source`（query） | string | ❌ | `ths` | 路由 Literal 锁死，传非 `ths` → 422 |

### 返回参数

顶层 `{code, source, total, data[]}`。`data[]` 每条：

| 字段 | 类型 | 单位 | 说明 |
|---|---|---|---|
| `date` | string | — | 周期日期 `YYYY-MM-DD` |
| `board_change_pct` | number | % | 板块涨幅 |
| `sh_change_pct` | number | % | **上证同周期涨幅**（基准对比） |
| `limit_up_count` | number | — | 涨停家数 |
| `limit_up_stocks[]` | array | — | 涨停股代码列表 |
| `up_count` | null | — | **固定 `null`**（F10 未暴露） |
| `down_count` | null | — | **固定 `null`**（F10 未暴露） |

### 示例

```bash
curl 'http://localhost:8888/api/v1/boards/885595/surges'
```

---

## `GET /api/v1/stocks/{stock_code}/boards`

### 功能

获取个股所属板块列表。返回该股在所有 source 下的板块归属。

- 主要 fetcher: ths / eastmoney / zhitu
- `name` 形如 `"A股-申万行业-银行"`（含层级前缀）
- `cold_sources[]` 顶层字段：列出没拉到的 source（cold cache 提示，可选重试）
- **THS 板块额外带 7 个字段**（`change_pct` / `up_count` / `down_count` / `limit_up_count` / `limit_down_count` / `explain` / `relevance`）——见下表

### 入参

| 参数名 | 类型 | 必填 | 默认值 | 约束 |
|---|---|---|---|---|
| `stock_code`（路径） | string | ✅ | — | 6 位 A 股代码 |
| `source`（query） | string | ❌ | 全部（ths/eastmoney/zhitu） | 逗号分隔 CSV，如 `ths,eastmoney`；`zzshare` 视为 `ths` 别名 |
| `type`（query） | string | ❌ | — | `concept` / `industry` / `index` / `special` |
| `subtype`（query） | string | ❌ | — | source 专属 subtype；需配合 `type` 才有意义 |

### 返回参数

顶层结构含 `code` / `source` / `data[]` / `cold_sources[]`。`data[]` 每条：

| 字段 | 类型 | 单位 | 说明 |
|---|---|---|---|
| `code` | string | — | 板块代码 |
| `name` | string | — | 板块全名（形如 `"A股-申万行业-银行"`） |
| `type` | string | — | `concept` / `industry` / `index` / `special` |
| `subtype` | string | — | 子类型（ths=`同花顺概念` / zhitu=`申万行业` 等） |
| `source` | string | — | 来自哪个 fetcher（`ths` / `eastmoney` / `zhitu`） |
| `change_pct` | number | % | **板块涨跌幅（THS 才有）** |
| `up_count` | number | — | **上涨家数（THS 才有）** |
| `down_count` | number | — | **下跌家数（THS 才有）** |
| `limit_up_count` | number | — | **涨停家数（THS 才有；上游无涨停时为 `null`）** |
| `limit_down_count` | number | — | **跌停家数（THS 才有；上游无跌停时为 `null`）** |
| `explain` | string | — | **概念解析文本（THS 才有；如 `"2022年8月23日公司互动回复：..."`）** |
| `relevance` | number | — | **关联度标签（THS 才有；`2` = UI 的"走势最相关"标签，`0` = 普通）** |
| `cold_sources`（顶层） | array | — | **顶层字段**，不在 `data[]` 内：拉取失败的 source 列表 |

**7 个新字段的填充规则**：

- **仅 `source='ths'` 的行才填充**。其他 source 行这 7 个字段一律为 `null`
- `change_pct` / `up_count` / `down_count` 字段名与 `/boards/{code}/quote` 一致，可复用客户端解析代码
- 字段类型：`change_pct` 为 `float`；`up_count` / `down_count` / `limit_up_count` / `limit_down_count` / `relevance` 为 `int`；`limit_up_count` / `limit_down_count` 上游无对应数据时为 `null`（不是 `0`）；`explain` 为 `str` 或 `null`

### 示例

```bash
# 默认查所有 source；THS 行带 7 字段，其他 source 行这 7 字段为 null
curl 'http://localhost:8888/api/v1/stocks/600519/boards'

# 仅 THS（7 字段全填）
curl 'http://localhost:8888/api/v1/stocks/600519/boards?source=ths'

# THS + type 过滤
curl 'http://localhost:8888/api/v1/stocks/600519/boards?source=ths&type=concept'
```

---

## `GET /api/v1/boards/{board_code}/history`

### 功能

获取板块 K 线。**`data[]` 每根 K 线 shape 与 `/stocks/{code}/kline` 完全一致**（OHLCV + frequency + amount + change_pct）。

- 主要 fetcher: ths（d/w/m + 1m/5m/15m/30m/60m 全 8 频率） / eastmoney（d/w/m + 5/15/30/60m，**不支持 1m**）
- `board_type` 由 ThsFetcher 自动从 `stock_board` cache + 内部 fallback 推断，agent 无需关心
- 800 天历史上限

### 入参

| 参数名 | 类型 | 必填 | 默认值 | 约束 |
|---|---|---|---|---|
| `board_code`（路径） | string | ✅ | — | 板块代码 |
| `source`（query） | string | ✅ | — | `ths` / `eastmoney`（`source=eastmoney&frequency=1m` 走 `@map_errors` 翻 **400**，因 EastMoney 不支持 1m）；`zzshare` 视为 `ths` 别名 |
| `frequency`（query） | string | ❌ | **`d`** | `d` / `w` / `m` / `1m` / `5m` / `15m` / `30m` / `60m` |
| `days`（query） | int | ❌ | **按 frequency 取默认**（d/w/m=30、1m=800、5m/15m/30m/60m=30） | 1-800；不传时按 frequency 取默认 |
| `start_date`（query） | string | ❌ | — | `YYYY-MM-DD`；与 `end_date` 跨度 ≤ 800 天 |
| `end_date`（query） | string | ❌ | — | `YYYY-MM-DD` |
| `board_type`（query） | string | ❌ | — | `concept` / `industry`；省略时从 cache 自动推断（ths） |

### 返回参数

顶层 `{code, board_name, period, data[], source}`。`data[]` shape **与 `/stocks/{code}/kline` 完全一致**（OHLCV + `volume_unit="share"` + `amount` / `change_pct` 可为 `null`）。**注意顶层字段名是 `code`（不是 `board_code`）**。

### 示例

```bash
# THS 板块 30 日日 K
curl 'http://localhost:8888/api/v1/boards/885595/history?frequency=d&days=30'

# THS 1 分钟级
curl 'http://localhost:8888/api/v1/boards/885595/history?frequency=1m&days=2'
```

---

## `GET /api/v1/zt-pools`

### 功能

获取涨跌停股池（涨停 / 跌停 / 炸板三类型）。`type=zt|dt|zbgc`。

- 主要 fetcher: Zzshare
- `date` 默认取今日或最近一个交易日
- `zt` = 涨停；`dt` = 跌停；`zbgc` = 炸板（**曾涨停但未封住**）
- 交易日内早于 16:00 时 `warning` 非空（盘中提示，池子仍在变化）

### 入参

| 参数名 | 类型 | 必填 | 默认值 | 约束 |
|---|---|---|---|---|
| `type`（query） | string | ✅ | — | `zt` / `dt` / `zbgc` |
| `date`（query） | string | ❌ | 今日或最近交易日 | `YYYY-MM-DD` |
| `refresh`（query） | bool | ❌ | `false` | 强制从上游刷新（**当日盘中仍不写持久化**，避免持久化部分成形的数据） |

### 返回参数

顶层结构含 `stocks[]`、`warning`。`stocks[]` 每条：

| 字段 | 类型 | 单位 | 说明 |
|---|---|---|---|
| `code` / `name` | string | — | 股票代码 / 名 |
| `price` | number | 元 | 当前价 |
| `change_pct` | number | % | 涨跌幅 |
| `amount` | number | 元 | 成交额 |
| `circ_mv` | number | 元 | 流通市值 |
| `total_mv` | number | 元 | 总市值 |
| `turnover_pct` | number | % | 换手率 |
| `lb_count` | number | — | **连板数**（N 连板） |
| `first_seal_time` | string | — | 首次封板时间 `HH:mm` |
| `last_seal_time` | string | — | 最后封板时间 `HH:mm` |
| `seal_amount` | number | 元 | 封单金额 |
| `seal_count` | number | — | 封单次数（涨停后开板又封回去的次数） |
| `zt_count` | number | — | 涨停次数 |
| `warning`（顶层） | string / null | — | **顶层字段**：非空 = 涉及交易时段（今天 + 是交易日 + 早于 16:00），池子可能未成形；历史日期或收盘后为 `null` |

### 示例

```bash
curl 'http://localhost:8888/api/v1/zt-pools?type=zt'
curl 'http://localhost:8888/api/v1/zt-pools?type=dt'
curl 'http://localhost:8888/api/v1/zt-pools?type=zbgc'
```

---

## `GET /api/v1/dragon-tiger`

### 功能

获取全市场龙虎榜（按日）。**`?trade_date=` 可选**，不传时由 fetcher 自行决定（多数 fetcher 取最近一个交易日）。`?min_net_buy=` 筛显著净买入。

- 主要 fetcher: Zzshare（P2 主力） → EastMoney（P6 兜底）
- **空结果 = 软失败**（fall through 到 EastMoney），不要凭空结果判断"无上榜"
- `close` Zzshare 上游**不返回**，固定 `null`；EastMoney 有值
- `buy_wan` / `sell_wan` Zzshare 上游**不拆分**，固定 `null`；EastMoney 有值

### 入参

| 参数名 | 类型 | 必填 | 默认值 | 约束 |
|---|---|---|---|---|
| `trade_date`（query） | string | ❌ | 空串（上游自行决定） | `YYYY-MM-DD` |
| `min_net_buy`（query） | number | ❌ | — | 净买入下限（**万元**），筛显著净买入 |

### 返回参数

顶层 `{date, total, stocks[], source}`。`stocks[]` 每条：

| 字段 | 类型 | 单位 | 说明 |
|---|---|---|---|
| `code` / `name` | string | — | 股票代码 / 名 |
| `reason` | string | — | **上榜原因**（"日涨幅偏离值达7%"、"换手率20%"等）——用于筛选 / 分组 |
| `change_pct` | number | % | 涨跌幅 |
| `turnover_pct` | number | % | 换手率 |
| `close` | number | 元 | 收盘价（**Zzshare `null`，EastMoney 有值**） |
| `net_buy_wan` | number | **万元** | 净买入 |
| `buy_wan` | number | 万元 | 买入额（**Zzshare `null`**，EastMoney 有值） |
| `sell_wan` | number | 万元 | 卖出额（**Zzshare `null`**，EastMoney 有值） |

### 示例

```bash
# 指定日期
curl 'http://localhost:8888/api/v1/dragon-tiger?trade_date=2026-05-20'

# 筛净买入 ≥ 5000 万
curl 'http://localhost:8888/api/v1/dragon-tiger?trade_date=2026-05-20&min_net_buy=5000'
```

---

## `GET /api/v1/stocks/{stock_code}/dragon-tiger`

### 功能

获取个股龙虎榜（含营业部席位 + 机构合计）。单日 `?trade_date=` 不传时默认查最新一个交易日。

- 主要 fetcher: Zzshare → EastMoney
- `records` 最多包含一条对应 `trade_date` 的上榜记录
- `seats.buy[]` / `seats.sell[]` 是营业部席位；`institution` 是机构席位合计

### 入参

| 参数名 | 类型 | 必填 | 默认值 | 约束 |
|---|---|---|---|---|
| `stock_code`（路径） | string | ✅ | — | 6 位 A 股代码 |
| `trade_date`（query） | string | ❌ | 最新一个交易日 | `YYYY-MM-DD` |

### 返回参数

顶层 `{code, name, records[], seats{buy[], sell[]}, institution, source}`。

| 字段 | 类型 | 单位 | 说明 |
|---|---|---|---|
| `records[]` | array | — | 个股当日上榜记录（通常 1 条） |
| `records[].code` / `name` | string | — | 股票代码 / 名 |
| `records[].reason` | string | — | 上榜原因 |
| `records[].change_pct` | number | % | 涨跌幅 |
| `records[].turnover_pct` | number | % | 换手率 |
| `records[].net_buy_wan` | number | 万元 | 净买入 |
| `seats.buy[]` | array | — | 买入营业部席位 |
| `seats.buy[].name` | string | — | 营业部名 |
| `seats.buy[].buy_wan` | number | 万元 | 买入额 |
| `seats.buy[].sell_wan` | number | 万元 | 卖出额 |
| `seats.buy[].net_wan` | number | 万元 | 净买入 |
| `seats.sell[]` | array | — | 卖出营业部席位（结构同上） |
| `institution.buy_amt` | number | 万元 | 机构席位买入合计 |
| `institution.sell_amt` | number | 万元 | 机构席位卖出合计 |
| `institution.net_amt` | number | 万元 | 机构席位净买入 |

### 示例

```bash
# 最新一日
curl 'http://localhost:8888/api/v1/stocks/600519/dragon-tiger'

# 指定日期
curl 'http://localhost:8888/api/v1/stocks/600519/dragon-tiger?trade_date=2026-05-20'
```

---

## `GET /api/v1/hot-topics`

### 功能

获取热点题材（带归因标签）。`reason` 字段是题材归因（分类 / 筛选的关键字段）。

- 主要 fetcher: Zzshare → Ths
- `dde_net` 大单净量（DDX 风格指标）

### 入参

| 参数名 | 类型 | 必填 | 默认值 | 约束 |
|---|---|---|---|---|
| `date`（query） | string | ❌ | 空串（上游自行决定，多为今日） | `YYYY-MM-DD` |

### 返回参数

顶层结构含 `date` / `total` / `topics[]` / `source`。`topics[]` 每条：

| 字段 | 类型 | 单位 | 说明 |
|---|---|---|---|
| `code` | string | — | 题材代码 |
| `name` | string | — | 题材名 |
| `reason` | string | — | **题材归因**（如 `"人形机器人+减速器+特斯拉"`） |
| `change_pct` | number | % | 涨跌幅 |
| `turnover_pct` | number | % | 换手率 |
| `volume` | number | 股 | 成交量 |
| `amount` | number | 元 | 成交额 |
| `dde_net` | number | — | 大单净量（DDX 风格） |

### 示例

```bash
curl 'http://localhost:8888/api/v1/hot-topics'
```
