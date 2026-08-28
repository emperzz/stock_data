# Agent 批量端点 — 端点明细

> 本文件是 `market-data-obtain` 主文件 [§9.1 Agent 批量端点](../market-data-obtain.md) 的端点明细。  
> 主文件只列端点路径 + 一句话用途；**输入约束、关键字段、错误隔离行为、示例见本文**。  
> **本节是面向 LLM agent 的高频组合查询**——把"多板块 / 多股票 / 跨资产批量画像"等 N+1 操作下沉到服务端。

## 通用行为

- **逐项错误隔离**：单 `code` / 单 aspect 拉取失败**不**中断整体响应；失败项进入 `errors[]`（或 `errors{}`，按端点形态不同），成功的项仍正常出现
- **`?format=md`**：6 个端点统一支持，默认 `json`；返回 `text/markdown; charset=utf-8`（**无数据丢失**——所有 JSON 字段都映射到 MD 表 / 列表项）。**例外**：`correlation/matrix` 走 `PlainTextResponse`，渲染失败 → 500（**无**自动回退 JSON + `X-MD-Render-Error` 响应头；其余 6 个端点 MD 渲染失败 → 自动回退 JSON + 响应头）
- **不做判断**：本节端点只返回"事实型"算结果（集合运算 / 过滤后列表 / Jaccard 系数 / 数值字段），不输出"龙头 / 候选"等结论

## MinimalQuote 字段约定（post-2026-08-28）

`/agent/*/batch-profile` 的 `quote` 块统一为扩展 `MinimalQuote`（**~23 字段**），覆盖 OHLV + 量价 + 估值 + 涨跌停价 + 板块统计。各端点字段填充规则：

| 字段组 | stock | index | board |
|---|---|---|---|
| OHLV（open / high / low / prev_close / volume / amount / change_pct / change_amount） | ✅ | ✅ | ✅（部分） |
| 量价（turnover_pct / amplitude_pct / volume_ratio） | ✅ | ✅ | ❌（`null`） |
| 估值（pe_ratio / pb_ratio / mcap_yi / float_mcap_yi） | ✅ | ❌（`null`） | ❌（`null`） |
| 涨跌停价（limit_up / limit_down） | ✅（仅 Zzshare/Tencent） | ❌（`null`） | ❌（`null`） |
| 板块统计（up_count / down_count / net_inflow / rank） | ❌（`null`） | ❌（`null`） | ✅ |
| `volume_unit` | `"share"` | `"share"` | `"wan_shou"`（THS 上游返回万手） |
| `amount` 单位 | 元 | 元 | 元（上游是亿元，helper ×1e8 转元——与 `/boards/{code}/quote` 对齐） |

各 batch-profile 端点的 `quote` 块填充细节见各端点章节。

---

## `POST /api/v1/agent/boards/stock-overlap`

### 功能

多板块（2-10）成分股两两交集 + Jaccard 系数。用于"判断哪些概念 / 行业同时覆盖了某批候选股"。

- 422 通常是 `codes` 不在 board 缓存中（board list 未刷新）——触发器是 `cid_unresolved`

### 入参

| 参数名 | 类型 | 必填 | 默认值 | 约束 |
|---|---|---|---|---|
| `codes`（body） | array | ✅ | — | 2-10 个板块代码（ths=`885xxx` / `881xxx`） |

### 返回参数

| 字段 | 类型 | 单位 | 说明 |
|---|---|---|---|
| `sets[]` | array | — | 每个板块的成分股集合 |
| `sets[].code` | string | — | 板块代码 |
| `sets[].count` | number | — | 成分股总数 |
| `sets[].source` | string | — | **即 `effective_source`**（`include_quote=False` 时若走 ZZSHARE 兜底会是 `"zzshare"`） |
| `pairs[]` | array | — | 板块两两交集 + Jaccard |
| `pairs[].a` / `pairs[].b` | string | — | 板块代码对 |
| `pairs[].intersection[]` | array | — | **按字母升序**的成分股代码数组 |
| `pairs[].intersection_count` | number | — | 交集大小 |
| `pairs[].jaccard` | number | — | Jaccard 系数（0-1） |
| `errors[]` | array | — | 失败的板块：`{code, error, message}` |

### 示例

```bash
curl -X POST http://localhost:8888/api/v1/agent/boards/stock-overlap \
  -H 'Content-Type: application/json' \
  -d '{"codes": ["885595", "885914", "881270"]}'
```

---

## `POST /api/v1/agent/stocks/board-overlap`

### 功能

多股票（2-10）所属板块两两交集 + Jaccard。用于"龙头 / 候选是否同板块系"判断。

- 422 通常是 stock_list 缓存缺失

### 入参

| 参数名 | 类型 | 必填 | 默认值 | 约束 |
|---|---|---|---|---|
| `codes`（body） | array | ✅ | — | 2-10 个股票代码（6 位 A 股） |

### 返回参数

| 字段 | 类型 | 单位 | 说明 |
|---|---|---|---|
| `sets[]` | array | — | 每只股票的板块集合 |
| `sets[].code` | string | — | 股票代码 |
| `sets[].boards[]` | array | — | 该股所属板块列表 |
| `sets[].boards[].code` / `name` / `type` / `subtype` / `source` | string | — | 板块字段 |
| `pairs[]` | array | — | 股票两两共有板块 |
| `pairs[].a` / `pairs[].b` | string | — | 股票代码对 |
| `pairs[].common_boards[]` | array | — | 共有板块（**按 `code` 字母升序**） |
| `pairs[].intersection_count` | number | — | 共有板块数 |
| `pairs[].jaccard` | number | — | Jaccard 系数（0-1） |
| `errors[]` | array | — | 失败的股票：`{code, error, message}` |

### 示例

```bash
curl -X POST http://localhost:8888/api/v1/agent/stocks/board-overlap \
  -H 'Content-Type: application/json' \
  -d '{"codes": ["600519", "000858", "000568"]}'
```

---

## `POST /api/v1/agent/boards/filter-stocks`

### 功能

板块成分股服务端数值过滤（换手 / 涨跌幅 / 成交额 / 市值 / 最高涨幅）。

- 排序：先按 `max_gain_pct desc`，再按 `turnover_pct desc`
- `value=None` 的成分股在该字段有 filter 时直接剔除
- 422 `cid_unresolved` → THS platecode→cid 索引 cold，需刷新 board 缓存
- **本端点无 `errors[]` 字段**：整端点失败以 HTTP 422 / 503 表达；成功响应内只含 `matched_stocks`

### 入参

| 参数名 | 类型 | 必填 | 默认值 | 约束 |
|---|---|---|---|---|
| `board_code`（body） | string | ✅ | — | 板块代码（ths 推荐） |
| `source`（body） | string | ❌ | `ths` | `ths` / `eastmoney` / `zhitu` |
| `filters`（body） | object | ❌ | 空 | 见下表；空 = 不过滤 |
| `filters.turnover_pct` | object | ❌ | — | `{min?, max?}`，单位 **%** |
| `filters.change_pct` | object | ❌ | — | `{min?, max?}`，单位 **%** |
| `filters.amount_yi` | object | ❌ | — | `{min?, max?}`，单位 **亿元**（**不要与 `amount` 混用**） |
| `filters.mcap_yi` | object | ❌ | — | `{min?, max?}`，单位 **亿元** |
| `filters.max_gain_pct` | object | ❌ | — | `{min?, max?}`，单位 **%** |
| `limit`（body） | int | ❌ | `None`（代码内 `or 50` 回落为 50） | 截断上限；**参与缓存键** |

### 返回参数

| 字段 | 类型 | 单位 | 说明 |
|---|---|---|---|
| `code` | string | — | 板块代码（回显） |
| `board_name` | string / null | — | 板块名 |
| `filters_applied` | object | — | 请求中的 `filters` 原样回显 |
| `matched_stocks[]` | array | — | 过滤后的成分股 |
| `matched_stocks[].code` / `name` | string | — | 股票代码 / 名 |
| `matched_stocks[].price` / `change_pct` / `change_amount` | number | — | 行情字段 |
| `matched_stocks[].turnover_pct` | number | % | 换手率 |
| `matched_stocks[].amount_yi` | number | 亿元 | 成交额（**注意是 `amount_yi` 亿元，不是 `amount` 元**） |
| `matched_stocks[].mcap_yi` | number | 亿元 | 总市值（亿元） |
| `matched_stocks[].max_gain_pct` | number | % | 最高涨幅 `((high-open)/open*100)` |
| `matched_stocks[].volume` | number | 股 | 成交量 |
| `matched_stocks[].volume_ratio` | number | — | 量比 |
| `matched_stocks[].pe_ratio` | number | — | 市盈率 |
| `matched_stocks[].open` / `high` / `low` / `prev_close` | number | 元 | 今开 / 高 / 低 / 昨收 |
| `matched_stocks[].amplitude_pct` | number | % | 振幅 |
| `summary` | object | — | `{total_in_board, matched, limit_applied}` |

### 示例

```bash
curl -X POST http://localhost:8888/api/v1/agent/boards/filter-stocks \
  -H 'Content-Type: application/json' \
  -d '{
    "board_code": "885595",
    "source": "ths",
    "filters": {
      "turnover_pct": {"min": 5.0, "max": 20.0},
      "change_pct": {"min": 0.0}
    },
    "limit": 10
  }'
```

---

## `GET /api/v1/agent/indices/batch-profile`

### 功能

指数批量画像：每个指数**扩展 `MinimalQuote` + `trend` / `pivots` / `volume` 计算特征**。1-5 codes，默认 3 核心 CSI 指数。

- `frequency` 单值（`d/w/m/1m/5m/15m/30m/60m`），`days` 顶层回显
- `days` 范围按 frequency 校验（下界统一为 **2**，上界见下表）
- 空 feature 子块在 K 线 0 根时为 `{}`（**不报错**）；MD 投影下渲染为 `（无数据）` / `（无确认摆动点）`——这是唯一的缺数据信号
- 指数无复权

### 入参

| 参数名 | 类型 | 必填 | 默认值 | 约束 |
|---|---|---|---|---|
| `codes`（query） | array | ❌ | 3 核心 CSI 指数（`000001` / `399001` / `399006`） | 1-5 个指数代码（逗号分隔） |
| `frequency`（query） | string | ❌ | `d` | `d` / `w` / `m` / `1m` / `5m` / `15m` / `30m` / `60m` |
| `days`（query） | int | ❌ | d 60 / w 156 / m 365 / 1m 3 / 5m 5 / 15m 8 / 30m 15 / 60m 30 | 范围：d 2-365 / w 14-1095 / m 60-1825 / 1m 2-3 / 5m 2-5 / 15m 2-8 / 30m 2-15 / 60m 2-30 |

### 返回参数

| 字段 | 类型 | 单位 | 说明 |
|---|---|---|---|
| `frequency` / `days` | string / int | — | 顶层回显 |
| `indices[]` | array | — | 每个指数的画像 |
| `indices[].code` / `name` | string | — | 指数代码 / 名 |
| `indices[].quote` | object | — | `MinimalQuote`（index 路径：OHLCV + 量价字段；估值 / 涨跌停 / 板块字段为 `null`；`volume_unit="share"`） |
| `indices[].features.trend` | object | — | MA 5/10/15/20/30/60 最新值 + 环比昨日 % + ADX/PDI/MDI/RSI/BOLL |
| `indices[].features.pivots` | object | — | 区间最高 / 最低 / 最大量价 + ZigZag 摆动点 + 在途未确认 + `params`（**ZigZag 算法参数，JSON 与 MD 都输出**——摆动点脱离参数无法校准） |
| `indices[].features.volume` | object | — | 最新量 + 5 日量比 + Z>2 放量异动（每根异动 bar 带完整 OHLC） |
| `indices[].errors` | object | — | **`dict[str, str\|None]`**，key 为 `"quote"` / `"features"`；`null` = ok |
| `summary` | object | — | `{requested, ok, failed, elapsed_ms}` |

### 示例

```bash
# 默认 3 核心 CSI 指数
curl 'http://localhost:8888/api/v1/agent/indices/batch-profile'

# 自定义 5 指数 + 5 分钟
curl 'http://localhost:8888/api/v1/agent/indices/batch-profile?codes=000001,000300,000905,399001,399006&frequency=5m&days=5'
```

---

## `GET /api/v1/agent/market-context`

### 功能

每日市场全景快照：早报 + 复盘 + 快讯 + 涨跌停 + 龙虎榜。`market_session` 由服务器本地 CST + `is_trade_date(today)` 推得：`pre-market`（09:15 前）/ `intraday`（09:15-15:00）/ `post-market`（15:00 后）/ `closed`（非交易日）。

- **pre-market 时涨跌停池强制 `null`**（池子可能未成形）
- `dragon_tiger.summary` 服务端计算：`total_net_buy_wan` 符号位（正=净买入、负=净卖出）；`top_by_net_sell` 仅取 `net_buy_wan < 0` 的行（all-positive 日子里不会出现"伪卖出"）
- per-block 错误隔离：CLS / zt / dt / dtiger 任一失败不影响其他（**本端点无 `errors[]` 字段**：失败块以该字段 `null` 表达，例如 `messages.morning_briefing=null`、`dragon_tiger=null`）
- **`trade_date` 格式必须 `YYYY-MM-DD`**，否则 400（防止"yesterday"这类非日期字符串静默 200 返回空结果）

### 入参

| 参数名 | 类型 | 必填 | 默认值 | 约束 |
|---|---|---|---|---|
| `flash_limit`（query） | int | ❌ | `20` | 快讯条数；1-200 |
| `trade_date`（query） | string | ❌ | 今日（CST） | `YYYY-MM-DD`；**格式错 → 400** |

### 返回参数

| 字段 | 类型 | 单位 | 说明 |
|---|---|---|---|
| `trade_date` | string | — | 快照对应的交易日 `YYYY-MM-DD` |
| `is_trade_day` | bool | — | 服务端本地今天是否是 A 股交易日 |
| `market_session` | string | — | `pre-market` / `intraday` / `post-market` / `closed` |
| `messages.morning_briefing` | object / null | — | 财联社早报（28 天窗口）；null = 上游失败 / 无文章 |
| `messages.market_recap` | object / null | — | 财联社复盘（28 天窗口）；null 同上 |
| `messages.flash_news[]` | array | — | 快讯列表；空列表 = 上游静默期 |
| `limit_pools.zt` | array / null | — | 涨停股池；**`pre-market` 时为 `null`** |
| `limit_pools.dt` | array / null | — | 跌停股池；`pre-market` 时为 `null` |
| `dragon_tiger.stocks[]` | array / null | — | 龙虎榜个股列表；null = 上游失败 |
| `dragon_tiger.summary.total_net_buy_wan` | number | 万元 | 净买入合计（**符号位表方向**） |
| `dragon_tiger.summary.top_by_net_sell[]` | array | — | 净卖出排行（**仅 `net_buy_wan < 0` 的行**） |
| `dragon_tiger.summary.top_by_net_buy[]` | array | — | 净买入 Top 10 |
| `summary` | object | — | `{requested, ok, failed, elapsed_ms}` |

### 示例

```bash
curl 'http://localhost:8888/api/v1/agent/market-context?flash_limit=20'
curl 'http://localhost:8888/api/v1/agent/market-context?flash_limit=50&trade_date=2026-05-20'
```

---

## `POST /api/v1/agent/stocks/batch-profile`

### 功能

股票批量画像：每只股票**扩展 `MinimalQuote` + `trend` / `pivots` / `volume` features + info + boards**。1-5 codes，单 frequency 单 days。

- 固定 `adjust=qfq`（前复权）
- per-aspect 错误隔离：quote / features / info / boards 任一失败不影响其他；失败记录在 `results[i].errors[]` 数组里
- 摆动点默认 `pivot_window=2, reversal_atr_mult=1.0, ATR14`；`pivots.params` 回显这组参数，**JSON 与 MD 两种投影都输出**（脱离参数无法校准）

### 入参

| 参数名 | 类型 | 必填 | 默认值 | 约束 |
|---|---|---|---|---|
| `codes`（body） | array | ✅ | — | 1-5 个股票代码（6 位 A 股） |
| `frequency`（body） | string | ❌ | `d` | `d` / `w` / `m` / `1m` / `5m` / `15m` / `30m` / `60m` |
| `days`（body） | int | ❌ | d 60 / w 156 / m 365 / 1m 3 / 5m 5 / 15m 8 / 30m 15 / 60m 30 | 范围同 indices/batch-profile |

### 返回参数

| 字段 | 类型 | 单位 | 说明 |
|---|---|---|---|
| `frequency` / `days` | string / int | — | 顶层回显 |
| `results[]` | array | — | 每只股票的画像 |
| `results[].code` / `name` | string | — | 股票代码 / 名 |
| `results[].ok` | bool | — | 至少一个 aspect 成功即 `true`；全部失败才 `false` |
| `results[].quote` | object | — | `MinimalQuote`（stock 路径：OHLCV + 量价 + 估值 PE/PB/mcap_yi/float_mcap_yi + 涨跌停价 limit_up/limit_down 仅 Zzshare/Tencent；board 独有字段 `null`） |
| `results[].features.trend` | object | — | 同 indices/batch-profile |
| `results[].features.pivots` | object | — | 同 indices/batch-profile（含 `params`） |
| `results[].features.volume` | object | — | 同 indices/batch-profile |
| `results[].info` | object | — | **形状是 `{"source": str, "data": {...}}`**——公司画像在 `data` 子键下，`source` 标记 fetcher / `"persistence"` |
| `results[].boards` | object | — | **形状是 `{"source": str, "data": [...]}`**——所属板块列表在 `data` 子键下 |
| `results[].errors[]` | array | — | 失败的 aspect 列表；每条 `{aspect, error, message}`（`aspect` ∈ `quote` / `features` / `info` / `boards`） |
| `summary` | object | — | `{requested, ok, failed, elapsed_ms}` |

### 示例

```bash
curl -X POST http://localhost:8888/api/v1/agent/stocks/batch-profile \
  -H 'Content-Type: application/json' \
  -d '{"codes": ["600519", "000858"], "frequency": "d", "days": 60}'
```

---

## `POST /api/v1/agent/boards/batch-profile`

### 功能

板块批量画像：每个板块**扩展 `MinimalQuote`（board 路径：`up_count` / `down_count` / `net_inflow` / `rank` 填充，`volume_unit="wan_shou"`，`amount` 由亿元 ×1e8 转元）+ `trend` / `pivots` / `volume` features**。1-5 THS platecode，单 frequency 单 days，单源 THS。

- **THS 单源**（其他 fetcher 不实现 `get_board_realtime`；且 board codes 跨源不兼容——THS platecode vs EastMoney BKxxxx）
- `board_type`（concept/industry）**未暴露**——`ThsFetcher` 自动从 `stock_board` cache + 内部 fallback 推断
- 422 通常是 `codes` 不为 THS platecode

### 入参

| 参数名 | 类型 | 必填 | 默认值 | 约束 |
|---|---|---|---|---|
| `codes`（body） | array | ✅ | — | 1-5 个 THS platecode（`885xxx` concept / `881xxx` industry） |
| `frequency`（body） | string | ❌ | `d` | `d` / `w` / `m` / `1m` / `5m` / `15m` / `30m` / `60m`。**必须传这里列出的公开字符串**（`"5m"` / `"30m"`），传 `"5"` / `"30"` 会 422（Pydantic Literal 校验） |
| `days`（body） | int | ❌ | 60（`d` 默认） | 范围同 indices/batch-profile |

### 返回参数

| 字段 | 类型 | 单位 | 说明 |
|---|---|---|---|
| `frequency` / `days` | string / int | — | 顶层回显 |
| `boards[]` | array | — | 每个板块的画像 |
| `boards[].code` / `name` | string | — | 板块代码 / 名 |
| `boards[].quote` | object | — | `MinimalQuote`（board 路径：`volume_unit="wan_shou"`；`amount` 由 helper ×1e8 转元；`up_count` / `down_count` / `net_inflow`（亿元）/ `rank` 填充；stock-only 字段（turnover_pct/amplitude_pct/volume_ratio/pe_ratio/pb_ratio/mcap_yi/float_mcap_yi/limit_up/limit_down）均为 `null`） |
| `boards[].features.trend` / `pivots` / `volume` | object | — | 同 indices/batch-profile |
| `boards[].errors` | object | — | **`dict[str, str\|None]`**，key 为 `"quote"` / `"features"`；`null` = ok |
| `summary` | object | — | `{requested, ok, failed, elapsed_ms}` |

### 示例

```bash
curl -X POST http://localhost:8888/api/v1/agent/boards/batch-profile \
  -H 'Content-Type: application/json' \
  -d '{"codes": ["885595", "881270"], "frequency": "d", "days": 60}'
```

---

## `POST /api/v1/agent/correlation/matrix`

### 功能

跨资产（股票 + 板块）两两 Pearson + Spearman 相关性矩阵。2-10 个资产混合，d/w/m/1m/5m/15m/30m/60m 频率。

- **A 股 only**
- `labels[i]` 对应 `matrices.<method>[i][:]`，顺序 = 请求顺序（股票块在前、板块块在后）
- 股票 `source: null`；板块 `source` = **请求时**源（ths/eastmoney），**不是**实际服务的 fetcher
- `alignment.common_bars` 是 inner-join 后实际样本量；`alignment.missing_after_join` 是 join 本身丢掉的天数（**先于** trailing-window trim 计算）
- `matrices.<method>` 对称、对角线=1、NaN→0、4 位小数；未请求的方法返回 `null`（**key 始终存在**）
- **`?format=md` 走 `PlainTextResponse`**——渲染失败 → 500，**无**自动回退 JSON + `X-MD-Render-Error` 响应头

### 入参

| 参数名 | 类型 | 必填 | 默认值 | 约束 |
|---|---|---|---|---|
| `stocks`（body） | array | ❌ | — | 股票代码列表（与 `boards` 合计 2-10） |
| `boards`（body） | array | ❌ | — | 板块列表：`"885xxx"` 裸字符串（默认源 `ths`）**或** `{"code": str, "source": str}`；与 `stocks` 合计 2-10 |
| `frequency`（body） | string | ❌ | `d` | `d` / `w` / `m` / `1m` / `5m` / `15m` / `30m` / `60m` |
| `days`（body） | int | ❌ | **`90`** | **日历日**（非 padding）；范围见下表；实际对齐样本 ≈ 0.7×`days`（需 ≥2 根 return） |
| `methods`（body） | array | ❌ | `["pearson", "spearman"]` | 至少一个 |

### 频率 × days 范围（与 batch-profile **不同**，因为不涉及 MA60 等热启动）

| frequency | days 下界 | days 上界 | 备注 |
|---|---|---|---|
| `d` | 2 | 365 | |
| `w` | 14 | 1095 | |
| `m` | 60 | 1825 | |
| `1m` | 2 | 3 | |
| `5m` | 2 | **3**（**注意不是 5**——比 batch-profile 的 5m 上界 5 更紧） | |
| `15m` | 2 | **5**（**注意不是 8**——比 batch-profile 的 15m 上界 8 更紧） | |
| `30m` | 2 | **10**（**注意不是 15**——比 batch-profile 的 30m 上界 15 更紧） | |
| `60m` | 2 | **20**（**注意不是 30**——比 batch-profile 的 60m 上界 30 更紧） | |

### 频率×days×source 组合约束（超出 → 422）

- `1m + eastmoney` → **直接 422**（eastmoney 不支持 1m 板 K 线）

### 返回参数

| 字段 | 类型 | 单位 | 说明 |
|---|---|---|---|
| `labels[]` | array | — | 资产标签（顺序 = 请求顺序：股票块在前、板块块在后） |
| `labels[].code` | string | — | 资产代码 |
| `labels[].type` | string | — | `stock` / `board` |
| `labels[].source` | string / null | — | 股票 `null`；板块 = 请求时源（**不是**实际服务 fetcher） |
| `labels[].name` | string / null | — | 资产名（best-effort 解析；股票 = `/stocks/{code}` 缓存名，板块 = `stock_board` 缓存名） |
| `alignment.requested_days` | int | — | 请求中的 `days` 回显 |
| `alignment.common_bars` | number | — | inner-join 后实际样本量 |
| `alignment.missing_after_join` | number | — | join 本身丢掉的天数（**先于** trim） |
| `matrices.pearson` | 2D array | — | Pearson 相关系数矩阵（**对称、对角线=1、NaN→0、4 位小数**） |
| `matrices.spearman` | 2D array | — | Spearman 相关系数矩阵（同上） |
| `errors[]` | array | — | 失败的资产：`{type, code, source, reason}`；`reason` ∈ `data_unavailable` / `empty` / `too_short` |

### 示例

```bash
curl -X POST http://localhost:8888/api/v1/agent/correlation/matrix \
  -H 'Content-Type: application/json' \
  -d '{
    "stocks": ["600519", "000858"],
    "boards": [{"code": "881270", "source": "ths"}],
    "frequency": "d",
    "days": 90,
    "methods": ["pearson", "spearman"]
  }'
```

---

## `GET /api/v1/agent/market-stats`

### 功能

全市场涨幅统计：个股 + 板块各 1 块，含均值 / 中位 / 最高 / 最低 / 上涨下跌平盘家数 + 桶形数据（个股 3% 宽 ±12% 截断，板块 1% 宽 ±3% 截断；0% 单独成桶）。

- **A 股 only**
- per-block 错误隔离（个股块 / 板块块）；失败的块为 `null`，失败原因进入 `errors[]`
- `?include_boards=false` 时**板块上游根本不被调用**

### 入参

| 参数名 | 类型 | 必填 | 默认值 | 约束 |
|---|---|---|---|---|
| `include_boards`（query） | bool | ❌ | `true` | `false` 时跳过板块上游 |
| `format`（query） | string | ❌ | `json` | `json` / `md` |

### 返回参数

| 字段 | 类型 | 单位 | 说明 |
|---|---|---|---|
| `stocks` | object / null | — | 个股块；`null` = 上游失败（见 `errors[]`） |
| `stocks.sample_size` | int | — | 样本数 |
| `stocks.mean_pct` | number | % | 均值 |
| `stocks.median_pct` | number | % | 中位数 |
| `stocks.max_pct` / `min_pct` | number | % | 最高 / 最低 |
| `stocks.up_count` / `down_count` / `flat_count` | int | — | 上涨 / 下跌 / 平盘家数 |
| `stocks.bin_width` | number | % | 桶宽（个股固定 3） |
| `stocks.buckets[]` | array | — | 11 个 3% 宽桶 [-12%, +9%]，0% 单独成桶 |
| `boards` | object / null | — | 板块块；`include_boards=false` 或上游失败时为 `null` |
| `boards.sample_size` / `mean_pct` / `median_pct` / `max_pct` / `min_pct` / `up_count` / `down_count` / `flat_count` / `bin_width` / `buckets[]` | 同 `stocks` | — | 9 个 1% 宽桶 [-3%, +3%]，0% 单独成桶；`bin_width` 固定 1；多一个 `source` 字段标记 fetcher |
| `boards.source` | string | — | 服务本次数据的 fetcher（ths / persistence） |
| `errors[]` | array | — | 失败的块：`{block, error, message}`（`block` ∈ `stocks` / `boards`） |
| `summary` | object | — | `{requested, ok, failed, elapsed_ms}` |

### 示例

```bash
# 完整（含板块）
curl 'http://localhost:8888/api/v1/agent/market-stats'

# 只看个股
curl 'http://localhost:8888/api/v1/agent/market-stats?include_boards=false'

# markdown 投影
curl 'http://localhost:8888/api/v1/agent/market-stats?format=md'
```
