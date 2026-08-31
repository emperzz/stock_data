---
name: trade-timing-advisor
description: A 股个股买卖时机判断 skill。agent 收到判断请求时（"X 现在怎样"、"该不该买"、"该不该卖"、"扫一遍持仓"）——输出支持/不支持两组的论据，不下结论。本 skill 是**判断流程执行器**，不规定仓位/止损/加减仓（用户决策层），不重复端点目录（走 `market-data-obtain`），不重复龙头识别方法论（走 `market-principles §6`）。
triggers:
  - "X 现在怎样" / "X 怎么样" / "判断下 X"
  - "该不该买 X" / "X 能买吗" / "现在能不能买 X"
  - "该不该卖 X" / "X 要不要卖" / "现在卖 X 行不行"
  - "看下手里的票" / "扫一遍持仓" / "现在持仓要不要调"
  - "/trade-timing-advisor"
scope:
  role: 判断流程执行器（输出正反论据供用户决策，不下交易结论）
  market: A 股
  coverage:
    主体: 主板 / 创业板 / 科创板
    标的: 由用户当前请求决定（可以是 watchlist 中的一只 / 多只 / 全部，也可以是与 watchlist 无关的临时指定股票；后者需先确定最相关板块——见 §2.2 路径 C）
  exclusion:
    - 北交所个股 / ST 股 / 美股 / 港股 / 期货 / 加密货币
    - 仓位管理 / 止损 / 加减仓（交易决策层，由用户自行决定）
    - 选股 / 复盘（走 `stock-picking` / `market-recap`）
  companions:
    - watchlist-manager（**读** portfolio.json / events.jsonl 获取 watch / position 上下文；本 skill 不写）
    - market-data-obtain（**取数** —— 所有 stock_data server 调用走本 skill 的端点目录 + fallback 策略）
    - market-principles（判断方法论；龙头识别 §6、量价原则 §5.2、风险第一 §5.1）
    - market-recap（**可选读** market_tracking.md 取主线状态；仅在用户场景涉及主线时使用）
---

# trade-timing-advisor

A 股个股买卖时机判断 skill。**论据呈现器**——输出支持买入/不支持买入的两组论据，不下"该买/该卖"的最终结论。

> **核心约束**：本 skill 不绑定任何特定数据 API。所有数据通过 agent 调用 stock_data server（`http://localhost:8888`）的 agent batch API 获取——server 已经把趋势/顶底/量异常/板块分布/相关系数等指标计算好，本 skill 只做**翻译 + 分组 + 解读**。

---

## 1. 适用场景

满足以下任一情况时启用本 skill：

- 用户问某只票"现在怎么样" / "该不该买" / "该不该卖"
- 用户说"扫一遍持仓" / "看下手里的票"——批量判断当前持仓 / 关注
- 用户问外部票（不在 watchlist 内）的判断

**不适用的请求**：

- 加关注 / 买入 / 卖出 / 取消关注 → 走 `watchlist-manager`
- 选股 / 复盘 → 走 `stock-picking` / `market-recap`
- 仓位 / 止损 / 加减仓 → 交易决策层，本 skill 不覆盖

---

## 2. 判断输入

### 2.1 按需求取来源（不是按文件）

| 我需要什么 | 从哪里取 | 怎么取 |
|---|---|---|
| 当前 watch / position 上下文 | watchlist-manager（**读** portfolio.json + events.jsonl） | 路径 A 直接读 `codes[].watch.board`；批量场景（如"扫一遍持仓"）读全部 codes |
| 主线 / 板块轮动状态（**仅**复盘场景） | market-recap（**读** market_tracking.md） | 用户主动问"今天市场怎么样"或要求结合主线判断时再读；纯单股判断可跳过 |
| 实时行情 + 计算 features（趋势 / 顶底 / 量异常） | market-data-obtain 批量端点 | `agent/{indices,stocks,boards}/batch-profile`（参数见 §3） |
| 板块成分股 / 龙头 / 实时 | market-data-obtain 板块端点 | `/boards/{code}/stocks?source=ths&include_quote=true&with_zt_flags=true` |
| 板块行情 + 板块涨幅相对位置 | market-data-obtain agent 端点 | `agent/boards/batch-profile`（板块）+ `agent/market-stats.boards.buckets`（市场桶位） |
| 全市场情绪 / 涨跌停 / 龙虎榜 / 消息面 | market-data-obtain agent 端点 | `agent/market-stats` + `agent/market-context` |
| 跨资产重合度 / 相关性 | market-data-obtain agent 端点 | `agent/{stocks,boards}-overlap` + `agent/correlation/matrix` |
| 个股公司画像（业务重合度对比用） | market-data-obtain agent 端点 | `agent/stocks/batch-profile` 的 `info.data` 块（`business_scope` + `concepts`） |

> **不重复端点目录**：每个端点的字段、单位、调用约束以 `market-data-obtain` 对应 detail 文件为准，**调用前必读**。本表只回答"取什么 / 从哪取"。

### 2.2 入口分流

#### 路径 A：code ∈ portfolio.json（默认）

直接读 `codes[code].watch.board` 作为该 code 的"最相关板块"，无需用户确认（用户在加关注时已确认过）。走完整三层漏斗。

#### 路径 B：用户主动提供 board

外部股票 + 用户同时提供 board（THS platecode code + name）→ 直接采用用户提供的 board。走完整三层漏斗。

#### 路径 C：code ∉ portfolio 且用户未提供 board（自动推荐）

调 `GET /api/v1/stocks/{code}/boards?source=ths`（THS 行 7 个 enrichment 字段契约见 `market-data-obtain/boards.md`），按以下优先级选 Top-1 推荐给用户确认：

1. **首选**：`relevance` 最高（关联度由 THS 上游给出，是最直接的"最相关板块"信号）
2. **次选**：若 `relevance` 缺失或并列，按 `limit_up_count` 降序（板块活跃度代理）
3. **兜底**：按 `change_pct` 降序（取当日涨幅最高）

向用户呈现：

> 该股票最相关的板块是 **{name}**（{code}），依据：{explain}。请确认是否以该板块作为判断基准？

- 用户确认 → 采用该 board，走路径 A
- 用户指定不同 board → 采用用户指定的（路径 B）
- 用户拒绝 / 想跳过板块层 → 仅做市场环境 + 个股自身两层（漏斗缺第 2 层），输出时明确标注"未做板块层对比"

> **禁止**在用户未确认前自行决定 board；不同 board 会导致板块层结论完全相反（消费 / 资源 / 金融三个方向的票差异巨大），属于用户判断层。

---

## 3. 数据获取策略

### 3.1 取数路由（按调用顺序）

> 请求格式、参数取值范围、字段与单位以 `market-data-obtain §9.1` + [agent-batch.md](market-data-obtain/agent-batch.md) 为准（调用前必读）；下表只列本 skill 的**取数需求 + 判断性参数选择**。

> **频率选择**：本 skill 只用 `d + days=365` 与 `5m + days=5` 两个频率覆盖长短期趋势——d+365 提供长周期信号（隐含 52 根周线），5m+5 覆盖当日分时。

| # | 层 | 取数需求 | 端点 | 本 skill 的参数选择 |
|---|---|---|---|---|
| 1 | 市场环境 | 大盘长期趋势 | `agent/indices/batch-profile` | `frequency=d`，`days=365`；`codes` 走 API 默认（`000001 / 399001 / 399006`——上证 + 深证 + 创业板） |
| 2 | 市场环境 | 大盘当日分时 | `agent/indices/batch-profile` | `frequency=5m`，`days=5`，`codes` 同上 |
| 3 | 市场环境 | 全市场个股 + 板块涨幅统计 | `agent/market-stats` | 默认（含板块块） |
| 4 | 市场环境 | 涨跌停 + 连板结构 + 龙虎榜 + 消息面 | `agent/market-context` | 默认 |
| 5 | 板块 | 板块长期 + 当日分时 features | `agent/boards/batch-profile` | THS platecodes，`frequency=d&days=365` 与 `frequency=5m&days=5` 各一次 |
| 6 | 板块 | 成分股龙头 / 前 3 + 当日触板标记 | `GET /boards/{code}/stocks` | `source=ths&include_quote=true&with_zt_flags=true`（龙头 / 前 3 = 列表按涨幅倒序的前几行；触板 = `is_limit_up`） |
| 7 | 个股 | 用户当前请求的每只 X 的长期 + 当日分时 features | `agent/stocks/batch-profile` | `frequency=d&days=365` 与 `frequency=5m&days=5` 各一次；`codes` = 用户本次请求涉及的股票集合（watchlist 子集 / 全集 / 或 watchlist 之外的临时指定） |
| 8 | 重合度 | X 与板块龙头的重合度（业务 + 板块 + 走势） | `agent/stocks/board-overlap` + `agent/correlation/matrix` + `info.data.business_scope/concepts` | 详见 §5.4 |
| 9 | 备查 | X 精确 K 线（仅在论据翻译规则需"近 N 日累计涨幅"等 batch-profile 不含字段时） | `GET /stocks/{code}/kline` 或 `GET /indices/{code}/kline` | 按需单拉，默认不调 |

> **个股层覆盖范围**：第 7 行的 codes 由 §2.2 入口分流后确定：
> - 单股查询（"判断下 X"）→ codes = [X]
> - "扫一遍持仓" → codes = portfolio.json 中所有有 watch 的 codes（去重）
> - "看下 X + Y + Z" → codes = [X, Y, Z]
> - watchlist 之外的临时指定（如"帮我看看 002415"）→ codes = [002415]，且需先走 §2.2 路径 C 确定板块

### 3.2 批处理策略

> **API 限制（单次最大 codes 数等）以 `market-data-obtain/agent-batch.md` 为准。** 本节只列 trade-timing-advisor 特化的批处理关注点。

- **去重**：批量场景（"扫一遍持仓 + 龙头 + 前 3"）的 codes 合并后必须去重——同一 code 出现在 watchlist 和龙头列表里只算一次
- **顺序保留**：相关性矩阵的 `labels` 顺序需对齐请求顺序——`agent/correlation/matrix` 的 stock 块在前、board 块在后，agent 在切片时不要打乱顺序
- **股票 / 板块分开调用**：不要试图把 stocks 和 boards 混在同一次 `batch-profile` 里——`agent/stocks/batch-profile` 只接股票 codes，`agent/boards/batch-profile` 只接 THS platecodes

---

## 4. 论据翻译规则（从 server features 翻译成投资语言）

判断 skill 的核心工作 = **读 features 字段 → 翻译成中文论据**。

> **频率上下文**：features 是按 batch-profile 的 frequency 计算的——同一指标名在不同频率下的含义不同。下表每条规则末尾标注 `(from d)` 或 `(from 5m)` 标明论据来自哪个频率的调用：
> - `(from d)` —— 来自 `d + days=365` 调用，是"中期 / 长周期"信号
> - `(from 5m)` —— 来自 `5m + days=5` 调用，是"日内 / 短线"信号
>
> 例：`RSI6` from d 是"6 日 RSI"（中期动能），`RSI6` from 5m 是"30 分钟级别 RSI"（日内动能）。两者阈值含义不同。

> **量化阈值是经验起点，不是硬门槛**：下表的数字（ADX=25、RSI=70 等）是常见经验阈值，**不是"达到即触发决策"的硬线**。最终判断要看多条论据的总体权衡（与 §7 反模式对齐）。

### 4.1 趋势（features.trend，from d）

| 字段组合 | 论据 |
|---|---|
| `ma.ma5 > ma.ma20 > ma.ma60` | "均线多头排列"（中期） |
| `ma.ma5 < ma.ma20 < ma.ma60` | "均线空头排列"（中期） |
| `ma.ma5 > ma.ma20` 但 `ma.ma20 < ma.ma60` | "短期反弹中期仍弱" |
| `adx > 25` 且 `pdi > mdi` | "中期上升趋势确立（ADX=X）" |
| `adx > 25` 且 `mdi > pdi` | "中期下降趋势确立（ADX=X）" |
| `adx < 20` | "中期趋势不明（ADX=X，震荡市）" |
| `rsi.rsi_6 > 70`（from d） | "中期超买（6 日 RSI=X）" |
| `rsi.rsi_6 < 30`（from d） | "中期超卖（6 日 RSI=X）" |
| `rsi.rsi_6` 介于 40-60（from d） | "中期动能中性（6 日 RSI=X）" |
| 当前价距 `boll.lower` < 5%（from d） | "价处布林下轨附近" |
| 当前价突破 `boll.upper`（from d） | "价处布林上轨之上，追高风险" |

### 4.2 顶底（features.pivots，from d）

| 字段组合 | 论据 |
|---|---|
| `(window_high.price - quote.price) / quote.price < 5%` | "距 365 日阶段高点 X%，空间被压缩" |
| `(quote.price - window_low.price) / window_low.price < 5%` | "距 365 日阶段低点 X%，支撑近" |
| `pending.side=high` 且 `pending.bars >= 3` | "正在构造高点（已 N 根未确认）" |
| `pending.side=low` 且 `pending.bars >= 3` | "正在构造低点（已 N 根未确认）" |
| `swings` 最近一项 `type=high` | "前高已确认、尚无新确认低点——可能处于自高点回落段" |
| `swings` ≥4 项且相邻同类点抬高（`high_n > high_{n-1}` 且 `low_n > low_{n-1}`） | "高低点抬高，中期趋势向上" |

### 4.3 量异常（features.volume，from d）

| 字段组合 | 论据 |
|---|---|
| `vol_ratio_5 > 1.5` | "近期放量（量比 5= X）" |
| `vol_ratio_5 < 0.7` | "近期缩量（量比 5= X）" |
| `z_anomalies` 长度 > 0 且 `direction=up` 占多数 | "近 N 日有 X 次放量上涨（z>2）" |
| `z_anomalies` 长度 > 0 且 `direction=down` 占多数 | "近 N 日有 X 次放量下跌（出货嫌疑）" |

### 4.4 日内分时（features.pivots / volume，from 5m）

| 字段组合 | 论据 |
|---|---|
| `pivots.swings` 当日 `low → high → low` 二次见底 | "当日分时二次见底，止跌信号" |
| `pivots.swings` 当日 `high → low → high` 单次冲高回落 | "当日冲高回落" |
| `quote.change_pct` 与 `pivots.swings` 高点一致 | "当前价即日内高点" |
| `volume.z_anomalies` 当日 | "当日有量能异常" |
| `rsi.rsi_6 > 70`（from 5m） | "日内 30 分钟级别超买（RSI6=X）" |
| `rsi.rsi_6 < 30`（from 5m） | "日内 30 分钟级别超卖（RSI6=X）" |
| `adx > 25` 且 `pdi > mdi`（from 5m） | "日内趋势向上确立" |
| `adx > 25` 且 `mdi > pdi`（from 5m） | "日内趋势向下确立" |

### 4.5 连续上涨后空间评估

```
距前期高点 = (window_high.price - quote.price) / quote.price × 100%
```

加速上行用 `trend.ma_change.ma5`（MA5 最新一根环比 %）近似。

| 组合 | 论据 |
|---|---|
| `ma_change.ma5 > 2%` 且 距前期高点 < 5% | "短期加速且距前期高点仅 +Y%——上涨空间被压缩" |
| `ma_change.ma5 > 2%` 且 距前期高点 > 10% | "短期加速且距前期高点还有 +Y%——仍有空间" |

> batch-profile 响应不含 5 日前收盘价，"近 N 日累计涨幅"无法由 features 推出——需要精确值时按 §3.1 第 9 行单拉 K 线。

### 4.6 当日涨幅 vs 涨停空间

```
涨停空间 = (涨停限制 - 当前涨跌幅)
```

| 板块 | 涨停限制 |
|---|---|
| 主板 | +10% |
| 创业板 / 科创板 | +20% |
| ST 股 | +5%（本 skill 不覆盖） |
| 北交所 | +30%（本 skill 不覆盖） |

| 涨停空间 | 论据 |
|---|---|
| 涨停空间 < 3% | "距涨停仅 X%，上涨空间低，风险高" |
| 涨停空间 > 5% | "距涨停 X%，尚有空间" |

### 4.7 板块涨幅相对性（market-stats.boards）

读取 `/agent/market-stats` 的 `boards.buckets[]`（9 桶，左开右闭、0% 单独成桶：`(-∞,-3%]`、`(-3%,-2%]`、`(-2%,-1%]`、`(-1%,0)`、`{0%}`、`(0,+1%]`、`(+1%,+2%]`、`(+2%,+3%]`、`(+3%,+∞)`）。

| 组合 | 论据 |
|---|---|
| 当前板块涨幅落在 +3% 以上桶 | "板块涨幅居前（>+3%，板块市场 +X% 桶）" |
| 当前板块涨幅落在 +1%~+2% 桶 | "板块涨幅居中" |
| 当前板块涨幅落在 -1% 以下桶 | "板块涨幅靠后，市场偏弱" |
| `boards.mean_pct` 与当前板块涨幅比较 | "板块涨幅强/弱于市场均值（市场均值 +X%）" |

### 4.8 重合度（vs 板块龙头 / 前 3）

> 重合度对比的目标是"板块龙头 / 前 3"——见 §5.4 的回退链选择。

| 数据 | 论据 |
|---|---|
| `info.data.business_scope`（经营范围）+ `info.data.concepts` 双方对比 | "业务重合度高 / 中 / 低" |
| `board-overlap.pairs[X↔leader].jaccard > 0.5` | "共同板块占比高（Jaccard X）" |
| `correlation/matrix` Pearson `ρ > 0.7` | "走势强相关（ρ=X）" |
| `0.4 < ρ < 0.7` | "走势中度相关（ρ=X）" |
| `ρ < 0.4` | "走势独立 / 弱相关（ρ=X）" |

---

## 5. 判断逻辑（三层漏斗）

### 5.1 第一层——市场环境（大盘）

**输入**：

- `agent/indices/batch-profile`（`d&days=365`）的 `features.trend / pivots / volume`（长期趋势 + 中期顶底）
- `agent/indices/batch-profile`（`5m&days=5`）的 `features.pivots`（当日分时顶底 + 量能）
- `agent/market-stats.stocks`（11 桶分布 + 算术平均 + 中位数）
- `agent/market-stats.boards`（9 桶分布 + 算术平均 + 中位数）
- `agent/market-context.limit_pools`（涨跌停池）

**输出**（共享给所有 code）：

- **长期趋势描述**（来自 d+365 features.trend）
- **当日分时描述**（来自 5m+5 features）
- **涨跌分布**：**up_count / down_count / flat_count + sample_size + 算术平均 + 中位数**
- **涨跌停统计**：涨停 X 只（含 20cm 涨停 Y 只），跌停 Z 只
- **连板分布广度**：1 板 / 2 板 / 3 板 / 4 板 / 5 板+ 各多少只
- **板块分布**：板块整体 mean_pct / median_pct + 9 桶分布

### 5.2 第二层——个股所在板块

**输入**：

- `agent/boards/batch-profile`（`d&days=365` 与 `5m&days=5` 各一次）的 `features.trend / pivots / volume`
- `agent/market-stats.boards.buckets[]` 看该 code 所在板块涨幅落在哪个桶
- `/boards/{code}/stocks` 取龙头 / 前 3 + 触板状态（必带参数见 §3.1 #6）

**每只 code 的板块层论据**：

- 板块长期趋势（来自 d+365 features.trend）
- 板块当日分时（来自 5m+5 features）
- 板块涨幅相对位置（market-stats 桶位 + 算术平均 / 中位数对比）
- 龙头 / 前 3 行情（如有）
- 龙头 / 前 3 当日是否触板

### 5.3 第三层——个股自身

**输入**：

- `agent/stocks/batch-profile (d, days=365)` 的 `features.trend / pivots / volume`
- `agent/stocks/batch-profile (5m, days=5)` 的 `features.pivots.swings + features.volume.z_anomalies`
- `agent/stocks/batch-profile.quote` 的 extended `MinimalQuote`（`price/change_pct/open/high/low/volume/turnover_pct/amplitude_pct` 等，字段与单位见 agent-batch.md）
- `agent/stocks/batch-profile.info` 的主营近似（`business_scope` + `concepts`）
- `agent/stocks/batch-profile.boards` 的所属板块（用于和 portfolio.json 对照；与 `/stocks/{code}/boards` 同契约，见 `market-data-obtain/boards.md`）

**每只 code 的个股层论据**：

- 长期趋势（d+365 features.trend）
- 当日分时（5m+5 features.pivots）
- 当前价 vs 顶底（pivots.window_high / low vs quote.price）
- 连续上涨后空间评估（§4.5）
- 当日涨幅 vs 涨停空间（§4.6）
- 主营近似（`info.data.business_scope` / `concepts`）
- 所属板块与 portfolio.json watch.board 是否一致（不一致提示用户复核 §2.2 路径 A）

### 5.4 重合度（vs 板块龙头 / 前 3）

**目标选择回退链**（重要）：

```
1. 板块有明确龙头（有 1 板 / 2 板 / 触板状态的领涨股） → 对比目标 = 龙头
2. 板块无明确龙头 → 对比目标 = 涨幅前 3（按 /boards/{code}/stocks 列表 change_pct 降序的前 3 行）
3. 板块成分股少于 3 只 → 全部纳入对比目标
```

**输入**：

- `agent/correlation/matrix`（`stocks=[X, 对比目标...]`，`boards=[X 所在板块]`，`frequency=d&days=90` 默认 Pearson + Spearman）
- `agent/stocks/board-overlap`（`codes=[X, 对比目标...]`）
- 双方 `info.data.business_scope` + `concepts`

**每只 code 的重合度论据**：

- **业务重合**：主营描述对比（"高 / 中 / 低"——文本相似度由 agent 判断，无硬阈值）
- **板块重合**：共同板块数 + Jaccard 系数
- **走势重合**：Pearson ρ（按 §4.8 阈值）
- 综合判断三层重合度

---

## 6. 输出格式

判断 skill 输出 **Markdown 文本**，由 chat 或文件呈现（用户可指定写盘到 `<workspace>/trade_judgment/{date}.md`）。

### 6.1 模板

```markdown
# 持仓/关注判断 — {trade_date} {market_session}

## 市场环境（大盘）

**长期趋势**（上证 + 深证 + 创业板 d+365）：{features.trend 翻译}
**当日分时**（上证 + 深证 + 创业板 5m+5）：{5m features 翻译}
**涨跌分布**（全市场 {sample_size} 只）：涨 {up_count} / 跌 {down_count} / 平 {flat_count}，算术平均 {mean_pct:+.2f}%，中位数 {median_pct:+.2f}%

**涨跌幅分布**（11 桶）：
- (>+12%): X 只
- (+9%,+12%]: X 只
- ...
- (-3%,0): X 只
- 0% (平盘): X 只

**涨跌停**：涨停 X 只（含 20cm 涨停 Y 只），跌停 Z 只
**连板分布**：1 板 X / 2 板 Y / 3 板 Z / 4 板 W / 5 板+ V

**板块分布**（N 个板块）：算术平均 {boards.mean_pct:+.2f}%，中位数 {boards.median_pct:+.2f}%

---

## 600519 贵州茅台

**当前状态**（来自 portfolio.json）：watch + position 200 股 @1807.50
**所属板块**（来自 portfolio.json）：白酒 (881xxx，THS platecode)

### 板块环境
**板块长期趋势**（d+365）：{boards/batch-profile features 翻译}
**板块当日分时**（5m+5）：{5m features 翻译}
**板块当日涨幅**：{boards.quote.change_pct:+.2f}%，落在 market-stats 桶 {bucket_label}（板块整体均值 {boards.mean_pct:+.2f}%）。`boards.quote` 已是 extended `MinimalQuote`（字段与单位见 agent-batch.md），不必再单拉 `/boards/{code}/quote`
**龙头 / 前 3**（按 §5.4 目标选择回退链）：
- 龙头 A (X 板): 价格 Y，涨幅 Z%
- 前 3 B: 价格 Y，涨幅 Z%
- 前 3 C: 价格 Y，涨幅 Z%
**板块内涨跌分布**：{从成分股计算}

### 个股自身
**长期趋势**（d+365）：{features.trend 翻译}
**当日分时**（5m+5）：{5m features 翻译}
**当前价 vs 顶底**：距 365 日高点 {X%}，距 365 日低点 {Y%}
**当日涨幅 vs 涨停空间**：主板 +10%（距涨停 {Z%}）
**主营**：{info.data.business_scope}

### 重合度（vs {龙头 / 前 3}）
**业务重合**：{主营对比}
**板块重合**：共同板块 {N} 个，Jaccard {X}
**走势重合**：Pearson ρ {X}（强 / 中 / 弱相关）

### 支持买入的论据（{N} 条）
- 事实 1：{具体数值} → 原因：{翻译}
- 事实 2：... → 原因：...
- ...

### 不支持买入的论据（{M} 条）
- 事实 1：{具体数值} → 原因：{翻译}
- 事实 2：... → 原因：...
- ...

### 核心论据 + 薄弱点
- **支持的最强论据**：{事实}，薄弱点：{反向条件}
- **反对的最强论据**：{事实}，薄弱点：{反向条件}

**由用户自行判断**。
```

### 6.2 关键约束

- ❌ **不下"该买/该卖"结论**——只摆正反论据
- ❌ **不写"建议加仓/减仓"**——仓位是用户决策
- ✅ **每条论据必须可追溯到具体数值**（server 返回的原始字段）——禁止写"看起来不错"等套话
- ✅ **正反两组的论据数量不限**——0 条也是合法的（说明没有明显支持/反对的论据）
- ✅ **核心论据**必须各挑 1 条最强 + 1 个反向条件（"在什么情况下这条论据会失效"）
- ✅ **市场环境**作为共享部分只输出一次（开头），每个 code 不重复
- ✅ **外部股票（路径 C）**必须在 code 标题下注明"外部股票" + 板块来源（如"由 API 推荐确认"或"用户指定"）

---

## 7. 反模式

- ❌ 不要在判断 skill 内手动计算 MA / RSI / DMI 等指标——server 的 `build_features` 已经算好，直接读
- ❌ 不要在判断 skill 内手动分桶涨跌停——用 `/agent/market-stats` 的桶
- ❌ 不要遍历个股的所有所属板块——只用 portfolio.json 里用户指定的那一个最相关板块（外部股票走 §2.2 路径 C 确定）
- ❌ 不要对所有 watchlist 票算两两相关系数——只算每只 vs §5.4 回退链选出的对比目标
- ❌ 不要让判断 skill 写 portfolio.json / events.jsonl——只读不写（与 watchlist-manager 的写入分工）
- ❌ 不要在判断输出里给"目标价"——本 skill 不预测价格
- ❌ 不要把"经验阈值"当"硬门槛"——下表数字（ADX=25 / RSI=70 等）是经验起点，最终判断要看多条论据的总体权衡
- ❌ 不要给路径 C 自动推荐 board 加上"我认为 X 板块最相关"的判断语气——这是 API 推荐的客观结果，agent 只做"展示 + 询问确认"，不下结论

---

## 8. 与其他 skill 的衔接

### 8.1 读

- `watchlist-manager` 的 `portfolio.json`（watch 列表 + position + 板块映射——路径 A 的输入）
- `watchlist-manager` 的 `events.jsonl`（近期操作节奏——仅"扫一遍持仓"场景使用，决定是否提示"近期已多次操作"）
- `market-recap` 的 `market_tracking.md`（活跃主线 + 龙头股 + 板块轮动状态——仅用户场景涉及主线时读）
- `market-principles §6`（龙头识别方法论——§5.4 目标选择回退链使用）
- `market-principles §5.1/5.2`（风险第一 / 量价原则——§4 翻译规则的判断背景）

### 8.2 写

- 默认输出到 chat（用户对话窗口）
- 用户要求存档时写到 `<workspace>/trade_judgment/{date}.md`

### 8.3 不做

- 不写 portfolio.json / events.jsonl（写操作走 `watchlist-manager`）
- 不调 stock_data server 的写接口（搜索 / 关注 / 取数全部是只读）
- 不预测价格 / 不给目标价 / 不建议仓位

---

## 9. 工作流示例

### 9.1 用户："看下 600519 现在怎样"（路径 A：watchlist 内）

```
1. 路径 A：code ∈ portfolio.json → 读 watch.board（白酒 881xxx）
2. 拉数据：
   - 大盘 2 个 frequency（indices/batch-profile d+365 / 5m+5）
   - market-stats + market-context
   - 白酒板块 boards/batch-profile (d+365 / 5m+5)
   - 600519 stocks/batch-profile (d+365 / 5m+5)
   - boards/{881xxx}/stocks 取龙头 / 前 3
   - correlation/matrix (stocks: [600519, 龙头/前3], boards: [881xxx])
3. 论据翻译 → 输出 600519 一段
```

### 9.2 用户："扫一遍持仓"（批量 + 路径 A）

```
1. 读 portfolio.json 的所有 codes
2. 去重所有 board_codes + 龙头 / 前 3 codes（§3.2 批处理策略）
3. 拉数据：
   - 大盘 2 个 frequency（同上）
   - market-stats + market-context
   - boards/batch-profile 按 5 切片（每板块 d+365 / 5m+5）
   - stocks/batch-profile 按 5 切片（每只 d+365 / 5m+5）
   - boards/{code}/stocks（每板块一次）
   - correlation/matrix（每只 X vs §5.4 回退链目标，按 5 切片）
4. 输出：市场环境（一次）+ 每只 code 一段
```

### 9.3 工作流要点

- §9.1 / §9.2 走完默认漏斗后，输出仍按 §6 模板；如有任何 code 走 §2.2 路径 B / C（外部股票），该 code 段落需按 §6.2 加"外部股票"标注
- "扫一遍持仓"场景下若 portfolio.json 包含大量 codes，按 §3.2 批处理策略去重 + 切片；若某次请求 codes ≤ 5，stocks/boards 的 batch-profile 单次即可（详见 agent-batch.md 的 `codes` 上界）
