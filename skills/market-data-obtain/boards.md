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
- 不传 `?type=` = 默认查该 source 支持的所有类型
- **跨 source 含义不同**：同名"互联网服务"概念，ths 与 eastmoney 的成分股集合**不保证一致**，默认 `source=ths` 可避免跨源语义混淆
- **错误示例**：`?source=ths&type=index` → 400；`?source=eastmoney&type=index` → 400

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
| `include_quote`（query） | bool | ❌ | `false` | `true` 时每条带报价字段 |
| `sort_by`（query） | string | ❌ | — | `change_pct` / `volume` / `amount` / `price`；**必须配合 `include_quote=true`**（否则 400） |
| `sort_order`（query） | string | ❌ | `desc` | `asc` / `desc` |
| `top_n`（query） | int | ❌ | 全部 | 限制返回条数 |

### 返回参数

顶层结构含 `data[]`。**报价字段仅在 `?include_quote=true` 时填充**。`data[]` 每条：

| 字段 | 类型 | 单位 | 必有 | 说明 |
|---|---|---|---|---|
| `code` | string | — | 始终 | 板块代码（ths=`885xxx`/`881xxx`；eastmoney=`BKxxxx`；zhitu=`sw_xxx`） |
| `name` | string | — | 始终 | 板块名 |
| `type` | string | — | 始终 | `concept` / `industry` / `index` / `special` |
| `subtype` | string | — | ths 必有 | 子类型（ths=`同花顺概念` / `同花顺行业` 等） |
| `price` | number | 指数点位 | `include_quote=true` | 板块指数点位 |
| `change_pct` | number | % | `include_quote=true` | 涨跌幅 |
| `change_amount` | number | 指数点位 | `include_quote=true` | 涨跌额 |
| `volume` | number | 股 | `include_quote=true` | 板块成交量 |
| `amount` | number | 元 | `include_quote=true` | 板块成交额 |
| `turnover_rate` | number | % | `include_quote=true` | 换手率 |
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
curl 'http://localhost:8888/api/v1/boards?source=ths&type=industry&include_quote=true&sort_by=change_pct&top_n=10'
```

---

## `GET /api/v1/boards/{board_code}/stocks`

### 功能

获取板块成分股。**`?source=` 必填**。THS 上游额外暴露 6 字段（涨速/量比/振幅/流通股/流通市值/市盈率）。

- 主要 fetcher: ths（默认）/ eastmoney / zhitu
- `?source=ths&include_quote=false` 走 **ZZSHARE 优先 + THS 兜底** 内部链；用响应 `effective_source` 字段判断实际服务者
- THS 上游 50 股登录墙：超过 `top_n` 截断后用 ZZSHARE 补全无报价成员；看 `quote_truncated` + `quote_total_in_board` 判断是否截断

### 入参

| 参数名 | 类型 | 必填 | 默认值 | 约束 |
|---|---|---|---|---|
| `board_code`（路径） | string | ✅ | — | 板块代码（ths=`885xxx` / `881xxx`；eastmoney=`BKxxxx`） |
| `source`（query） | string | ✅ | — | `ths` / `eastmoney` / `zhitu` |
| `include_quote`（query） | bool | ❌ | `false` | `true` 时每条带报价字段 |
| `sort_by`（query） | string | ❌ | — | 排序键（`include_quote=true` 时才有意义） |
| `top_n`（query） | int | ❌ | 全部 | 限制返回条数 |

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
| `stocks[].turnover_rate` | number | % | 换手率（同上） |
| `stocks[].change_speed` | number | % | 涨速（**仅 THS**） |
| `stocks[].volume_ratio` | number | — | 量比（**仅 THS**） |
| `stocks[].amplitude` | number | % | 振幅（**仅 THS**） |
| `stocks[].free_float_shares` | number | 股 | 流通股（**仅 THS**） |
| `stocks[].float_market_cap` | number | 元 | 流通市值（**仅 THS**） |
| `stocks[].pe_ratio` | number | — | 市盈率（**仅 THS**） |
| `query_source` | string | — | 用户传入的 `?source=` |
| `data_source` | string | — | 缓存来源；`'persistence'` = 缓存命中，**不是**用户选择 |
| `effective_source` | string | — | **实际服务 fetcher**（`ths` / `zzshare` / `eastmoney` / `zhitu`）；用于判断是否走了 ZZSHARE 兜底 |
| `quote_truncated` | bool | — | 报价是否被 `top_n` 截断后用 ZZSHARE 补全（仅 `?include_quote=true` + 排序/限额时） |
| `quote_top_n` | int | — | 截断点 |
| `quote_total_in_board` | int | — | 板块总成分股数 |

### 示例

```bash
# THS 概念板块成分股（不带报价，走 ZZSHARE 兜底可能）
curl 'http://localhost:8888/api/v1/boards/885595/stocks?source=ths'

# THS 行业板块成分股（带报价，按涨幅排序前 10）
curl 'http://localhost:8888/api/v1/boards/881270/stocks?source=ths&include_quote=true&sort_by=change_pct&top_n=10'
```

---

## `GET /api/v1/boards/{board_code}/quote`

### 功能

获取板块实时行情。**THS 唯一实现**（其他 fetcher 不支持板块实时行情）。

- `volume` 上游返回**万手**，已由 fetcher 用 `safe_int` 截断为整数（精度损失约 0.005%）
- `amount` 单位是**亿元**
- `rank` 形如 `"229/389"`（涨幅排名字符串）

### 入参

| 参数名 | 类型 | 必填 | 默认值 | 约束 |
|---|---|---|---|---|
| `board_code`（路径） | string | ✅ | — | THS 板块代码（`885xxx` / `881xxx`） |

### 返回参数

| 字段 | 类型 | 单位 | 说明 |
|---|---|---|---|
| `code` | string | — | 板块代码 |
| `name` | string | — | 板块名 |
| `price` | number | 指数点位 | 板块当前点位 |
| `change_pct` | number | % | 涨跌幅 |
| `change_amount` | number | 指数点位 | 涨跌额 |
| `open` / `high` / `low` / `prev_close` | number | 指数点位 | 今开 / 高 / 低 / 昨收 |
| `volume` | number | **万手（整数）** | 成交量（**注意单位是万手**） |
| `amount` | number | **亿元** | 成交额 |
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
| `cursor`（query） | string | ❌ | — | 游标（分页用） |

### 返回参数

顶层结构含 `data[]`。`data[]` 每条：

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

### 返回参数

顶层结构含 `data[]`。`data[]` 每条：

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
- `cold_sources[]` 列出没拉到的 source（cold cache 提示，可选重试）

### 入参

| 参数名 | 类型 | 必填 | 默认值 | 约束 |
|---|---|---|---|---|
| `stock_code`（路径） | string | ✅ | — | 6 位 A 股代码 |

### 返回参数

顶层结构含 `data[]`。`data[]` 每条：

| 字段 | 类型 | 单位 | 说明 |
|---|---|---|---|
| `code` | string | — | 板块代码 |
| `name` | string | — | 板块全名（形如 `"A股-申万行业-银行"`） |
| `type` | string | — | `concept` / `industry` / `index` / `special` |
| `subtype` | string | — | 子类型（ths=`同花顺概念` / zhitu=`申万行业` 等） |
| `source` | string | — | 来自哪个 fetcher（`ths` / `eastmoney` / `zhitu`） |
| `cold_sources[]` | array | — | 拉取失败的 source 列表（可选重试） |

### 示例

```bash
curl 'http://localhost:8888/api/v1/stocks/600519/boards'
```

---

## `GET /api/v1/boards/{board_code}/history`

### 功能

获取板块 K 线。**`data[]` 每根 K 线 shape 与 `/stocks/{code}/kline` 完全一致**（OHLCV + frequency + amount + change_percent）。

- 主要 fetcher: ths（d/w/m + 1m/5m/15m/30m/60m 全 8 频率） / eastmoney（d/w/m + 5/15/30/60m，**不支持 1m**）
- `board_type` 由 ThsFetcher 自动从 `stock_board` cache + 内部 fallback 推断，agent 无需关心
- 800 天历史上限

### 入参

| 参数名 | 类型 | 必填 | 默认值 | 约束 |
|---|---|---|---|---|
| `board_code`（路径） | string | ✅ | — | 板块代码 |
| `source`（query） | string | ❌ | 自动推断 | `ths` / `eastmoney`（**1m 仅 THS 支持**——`source=eastmoney&frequency=1m` 会 5xx） |
| `frequency`（query） | string | ✅ | — | `d` / `w` / `m` / `1m` / `5m` / `15m` / `30m` / `60m` |
| `days`（query） | int | ✅ | — | 拉取天数（上限 800） |

### 返回参数

顶层 `{board_code, board_name, period, data[], source}`。`data[]` shape **与 `/stocks/{code}/kline` 完全一致**（OHLCV + `volume_unit="share"` + `amount` / `change_percent` 可为 `null`）。

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

### 入参

| 参数名 | 类型 | 必填 | 默认值 | 约束 |
|---|---|---|---|---|
| `type`（query） | string | ✅ | — | `zt` / `dt` / `zbgc` |
| `date`（query） | string | ❌ | 今日或最近交易日 | `YYYY-MM-DD` |

### 返回参数

顶层结构含 `stocks[]`。`stocks[]` 每条：

| 字段 | 类型 | 单位 | 说明 |
|---|---|---|---|
| `code` / `name` | string | — | 股票代码 / 名 |
| `price` | number | 元 | 当前价 |
| `change_pct` | number | % | 涨跌幅 |
| `amount` | number | 元 | 成交额 |
| `circ_mv` | number | 元 | 流通市值 |
| `total_mv` | number | 元 | 总市值 |
| `turnover_rate` | number | % | 换手率 |
| `lb_count` | number | — | **连板数**（N 连板） |
| `first_seal_time` | string | — | 首次封板时间 `HH:mm` |
| `last_seal_time` | string | — | 最后封板时间 `HH:mm` |
| `seal_amount` | number | 元 | 封单金额 |
| `seal_count` | number | — | 封单次数（涨停后开板又封回去的次数） |
| `zt_count` | number | — | 涨停次数 |

### 示例

```bash
curl 'http://localhost:8888/api/v1/zt-pools?type=zt'
curl 'http://localhost:8888/api/v1/zt-pools?type=dt'
curl 'http://localhost:8888/api/v1/zt-pools?type=zbgc'
```

---

## `GET /api/v1/dragon-tiger`

### 功能

获取全市场龙虎榜（按日）。**`?trade_date=` 必传**。`?min_net_buy=` 筛显著净买入。

- 主要 fetcher: Zzshare（P2 主力） → EastMoney（P6 兜底）
- **空结果 = 软失败**（fall through 到 EastMoney），不要凭空结果判断"无上榜"
- `close` Zzshare 上游**不返回**，固定 `null`；EastMoney 有值
- `buy_wan` / `sell_wan` Zzshare 上游**不拆分**，固定 `null`；EastMoney 有值

### 入参

| 参数名 | 类型 | 必填 | 默认值 | 约束 |
|---|---|---|---|---|
| `trade_date`（query） | string | ✅ | — | `YYYY-MM-DD`（**必传**） |
| `min_net_buy`（query） | number | ❌ | — | 净买入下限（**万元**），筛显著净买入 |

### 返回参数

顶层 `{date, total, stocks[]}`。`stocks[]` 每条：

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
| `limit`（query） | int | ❌ | `30` | 返回条数 |

### 返回参数

顶层结构含 `topics[]`。`topics[]` 每条：

| 字段 | 类型 | 单位 | 说明 |
|---|---|---|---|
| `code` | string | — | 题材代码 |
| `name` | string | — | 题材名 |
| `reason` | string | — | **题材归因**（如 `"人形机器人+减速器+特斯拉"`） |
| `change_pct` | number | % | 涨跌幅 |
| `turnover_rate` | number | % | 换手率 |
| `volume` | number | 股 | 成交量 |
| `amount` | number | 元 | 成交额 |
| `dde_net` | number | — | 大单净量（DDX 风格） |

### 示例

```bash
curl 'http://localhost:8888/api/v1/hot-topics?limit=20'
```
