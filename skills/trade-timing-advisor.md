---
name: trade-timing-advisor
description: A 股个股买卖时机判断 skill。配套 `watchlist-manager` 与 `market-principles` 使用——agent 收到判断请求时（"X 现在怎样"、"判断下 X"、"该不该买"、"该不该卖"），按"市场环境→板块→个股"三层漏斗给出**正反两组论据**供用户决策。本 skill 是**判断流程执行器**：规定"按什么顺序取数、论据怎么翻译、分组怎么输出、判断逻辑怎么落地"，不规定仓位/止损/加减仓（用户决策层），不重复端点目录（走 `market-data-obtain`），不重复龙头识别方法论（走 `market-principles §6`）。
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
    标的: watchlist 内的关注+持仓股票，或用户临时指定的外部股票（外部股票要求用户先提供 board）
  exclusion:
    - 北交所个股 / ST 股 / 美股 / 港股 / 期货 / 加密货币
    - 仓位管理 / 止损 / 加减仓（交易决策层，由用户自行决定）
    - 选股 / 复盘（走 `stock-picking` / `market-recap`）
  companions:
    - watchlist-manager（读取 portfolio.json / events.jsonl 获取当前持仓+关注状态）
    - market-principles（判断方法论总入口；龙头识别 §6、量价原则 §5.2、风险第一 §5.1）
    - market-data-obtain（端点目录；本 skill 全部数据通过 agent 调用 stock_data server API 获取）
---

# trade-timing-advisor

A 股个股买卖时机判断 skill。**论据呈现器**——输出支持买入/不支持买入的两组论据，不下"该买/该卖"的最终结论。

> **核心约束**：本 skill 不绑定任何特定数据 API。所有数据通过 agent 调用 stock_data server（`http://localhost:8888`）的 agent batch API 获取——server 已经把趋势/顶底/量异常/板块分布/相关系数等指标计算好，本 skill 只做**翻译 + 分组 + 解读**。

---

## 1. 适用场景

满足以下任一情况时启用本 skill：

- 用户问某只票"现在怎么样" / "该不该买" / "该不该卖"
- 用户说"扫一遍持仓" / "看下手里的票"——批量判断所有 watchlist
- 用户问外部票（不在 watchlist 内）的判断

**不适用的请求**：

- 加关注 / 买入 / 卖出 / 取消关注 → 走 `watchlist-manager`
- 选股 / 复盘 → 走 `stock-picking` / `market-recap`
- 仓位 / 止损 / 加减仓 → 交易决策层，本 skill 不覆盖

---

## 2. 判断输入

### 2.1 输入来源

| 来源 | 用法 |
|---|---|
| `portfolio.json`（`watchlist-manager` 维护） | 读 `关注.board.code`（**须为 THS platecode 885xxx/881xxx**——本 skill 板块取数全部走 THS 单源）、`持仓.shares/avg_cost/last_event_at` |
| `events.jsonl`（`watchlist-manager` 维护） | 读近期操作节奏（最近 5 条事件的 ts 间隔） |
| `market_tracking.md`（`market-recap` 维护） | 读活跃主线、龙头股、板块轮动状态 |
| stock_data server agent API | 实时行情 + 服务端计算的 features（trend/pivots/volume） |

### 2.2 入口分流

**路径 A（默认）**：code ∈ portfolio.json `codes[]`

- 读 `关注.board` 作为该 code 的"最相关板块"
- 走完整三层漏斗

**路径 B**：code ∉ portfolio（用户外部询问）

- 反馈用户先提供 board（code + name，**code 须为 THS platecode 885xxx/881xxx**），等用户提供
- 用户提供后再启动判断（避免选错板块导致判断失真）

---

## 3. 数据获取策略

### 3.1 取数路由（按调用顺序）

> 请求格式、参数取值范围、字段与单位以 `market-data-obtain §9.1` + [agent-batch.md](market-data-obtain/agent-batch.md) 为准（调用前必读）；下表只列本 skill 的**取数需求 + 判断性参数选择**。

| # | 层 | 取数需求 | 端点 | 本 skill 的参数选择 |
|---|---|---|---|---|
| 1 | 市场环境 | 大盘长期趋势（周 K） | `agent/indices/batch-profile` | `codes=000300`，`w`，`days=156` |
| 2 | 市场环境 | 大盘短期趋势（重点，日 K） | `agent/indices/batch-profile` | `000300`，`d`，`days=30` |
| 3 | 市场环境 | 大盘当日分时 | `agent/indices/batch-profile` | `000300`，`5m`，`days=2` |
| 4 | 市场环境 | 全市场个股 + 板块涨幅统计 | `agent/market-stats` | 默认（含板块块） |
| 5 | 市场环境 | 涨跌停 + 连板结构 + 龙虎榜 + 消息面 | `agent/market-context` | 默认 |
| 6 | 板块 | 相关板块短期趋势（日 K） | `agent/boards/batch-profile` | THS platecodes，`d`，`days=30` |
| 7 | 板块 | 相关板块当日分时 | `agent/boards/batch-profile` | 同上 codes，`5m`，`days=2` |
| 8 | 板块 | 成分股龙头/前3 + 当日触板标记 | `GET /boards/{code}/stocks` | `source=ths&include_quote=true&with_zt_flags=true`（龙头/前3 = 列表按涨幅倒序的前几行；触板 = `is_limit_up`） |
| 9 | 个股 | watchlist + 各板块龙头日线 features | `agent/stocks/batch-profile` | `d`，`days=365` |
| 10 | 个股 | 同上的 5 分钟分时 features | `agent/stocks/batch-profile` | `5m`，`days=5` |
| 11 | 重合度 | watchlist 内两两板块重合 | `agent/stocks/board-overlap` | 一次调用 |
| 12 | 重合度 | 每只 X vs 前三龙头 + 所在板块的相关性 | `agent/correlation/matrix` | stocks=[X, 3 龙头] + boards=[X 所在板块]，`d`，`days=90`，pearson |

### 3.2 自动分批规则

- `stocks/batch-profile` 与 `boards/batch-profile` 的 codes 按 5 切片串行调用（保留输入顺序，合并结果）
- `stocks/board-overlap` codes 按 10 切片
- `correlation/matrix` 每次固定 5 个资产（X + 前三龙头 + 所在板块）
- 分批调用之间无需限流等待——重复请求由服务端消化

---

## 4. 论据翻译规则（从 server features 翻译成投资语言）

判断 skill 的核心工作 = **读 features 字段 → 翻译成中文论据**。

### 4.1 趋势（features.trend）

| 字段组合 | 论据 |
|---|---|
| `ma.ma5 > ma.ma20 > ma.ma60` | "均线多头排列" |
| `ma.ma5 < ma.ma20 < ma.ma60` | "均线空头排列" |
| `ma.ma5 > ma.ma20` 但 `ma.ma20 < ma.ma60` | "短期反弹中期仍弱" |
| `adx > 25` 且 `pdi > mdi` | "上升趋势确立（ADX=X）" |
| `adx > 25` 且 `mdi > pdi` | "下降趋势确立（ADX=X）" |
| `adx < 20` | "趋势不明（ADX=X，震荡市）" |
| `rsi.rsi_6 > 70` | "短期超买（RSI6=X）" |
| `rsi.rsi_6 < 30` | "短期超卖（RSI6=X）" |
| `rsi.rsi_6` 介于 40-60 | "短期动能中性（RSI6=X）" |
| 当前价距 `boll.lower` < 5% | "价处布林下轨附近" |
| 当前价突破 `boll.upper` | "价处布林上轨之上，追高风险" |

### 4.2 顶底（features.pivots）

| 字段组合 | 论据 |
|---|---|
| `(window_high.price - quote.price) / quote.price < 5%` | "距 365 日阶段高点 X%，空间被压缩" |
| `(quote.price - window_low.price) / window_low.price < 5%` | "距 365 日阶段低点 X%，支撑近" |
| `pending.side=high` 且 `pending.bars >= 3` | "正在构造高点（已 N 根未确认）" |
| `pending.side=low` 且 `pending.bars >= 3` | "正在构造低点（已 N 根未确认）" |
| `swings` 最近一项 `type=high` | "前高已确认、尚无新确认低点——可能处于自高点回落段" |
| `swings` ≥4 项且相邻同类点抬高（`high_n > high_{n-1}` 且 `low_n > low_{n-1}`） | "高低点抬高，趋势向上" |

### 4.3 量异常（features.volume）

| 字段组合 | 论据 |
|---|---|
| `vol_ratio_5 > 1.5` | "近期放量（量比 5= X）" |
| `vol_ratio_5 < 0.7` | "近期缩量（量比 5= X）" |
| `z_anomalies` 长度 > 0 且 `direction=up` 占多数 | "近 N 日有 X 次放量上涨（z>2）" |
| `z_anomalies` 长度 > 0 且 `direction=down` 占多数 | "近 N 日有 X 次放量下跌（出货嫌疑）" |

### 4.4 当日分时（5m features.pivots）

| 字段组合 | 论据 |
|---|---|
| `pivots.swings` 当日 `low → high → low` 二次见底 | "当日分时二次见底，止跌信号" |
| `pivots.swings` 当日 `high → low → high` 单次冲高回落 | "当日冲高回落" |
| `quote.change_pct` 与 `pivots.swings` 高点一致 | "当前价即日内高点" |
| `volume.z_anomalies` 当日 | "当日有量能异常" |

### 4.5 连续上涨后空间评估

```
距前期高点 = (window_high.price - quote.price) / quote.price × 100%
```

加速上行用 `trend.ma_change.ma5`（MA5 最新一根环比 %）近似。

| 组合 | 论据 |
|---|---|
| `ma_change.ma5 > 2%` 且 距前期高点 < 5% | "短期加速且距前期高点仅 +Y%——上涨空间被压缩" |
| `ma_change.ma5 > 2%` 且 距前期高点 > 10% | "短期加速且距前期高点还有 +Y%——仍有空间" |

> batch-profile 响应不含 5 日前收盘价，"近 N 日累计涨幅"无法由 features 推出——需要精确值时另调 `GET /stocks/{code}/kline?period=daily&days=10`。

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

### 4.8 重合度（correlation/matrix + board-overlap + info）

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
- `indices/batch-profile` 的 `features.trend/pivots/volume`（长期 + 短期 + 当日分时）
- `market-stats.stocks`（11 桶分布 + 算术平均 + 中位数）
- `market-stats.boards`（9 桶分布 + 算术平均 + 中位数）
- `market-context.limit_pools`（涨跌停池）

**输出**（共享给所有 code）：

- **长期趋势描述**（周线 features.trend）
- **短期趋势描述**（日线 features.trend + features.pivots）
- **当日分时描述**（5m features）
- **涨跌分布**：**up_count / down_count / flat_count + sample_size + 算术平均 + 中位数**
- **涨跌停统计**：涨停 X 只（含 20cm 涨停 Y 只），跌停 Z 只
- **连板分布广度**：1 板 / 2 板 / 3 板 / 4 板 / 5 板+ 各多少只
- **板块分布**：板块整体 mean_pct / median_pct + 9 桶分布

### 5.2 第二层——个股所在板块

**输入**：
- `boards/batch-profile` 的 `features.trend/pivots/volume`（长期 + 短期 + 当日分时）
- `market-stats.boards.buckets[]` 看该 code 所在板块涨幅落在哪个桶
- `boards/{code}/stocks` 取龙头/前 3 + 触板状态（必带参数见 §3.1 #8）

**每只 code 的板块层论据**：

- 板块短期 + 长期趋势（读 features.trend）
- 板块当日分时（读 5m features）
- 板块涨幅相对位置（market-stats 桶位 + 算术平均 / 中位数对比）
- 龙头/前 3 行情（如有）
- 龙头/前 3 当日是否触板

### 5.3 第三层——个股自身

**输入**：
- `stocks/batch-profile (d, days=365)` 的 `features.trend/pivots/volume`
- `stocks/batch-profile (5m, days=5)` 的 `features.pivots.swings + features.volume.z_anomalies`
- `stocks/batch-profile.quote` 的 extended `MinimalQuote`（`price/change_pct/open/high/low/volume/turnover_pct/amplitude_pct` 等，字段与单位见 agent-batch.md）
- `stocks/batch-profile.info` 的主营近似（`business_scope` + `concepts`）
- `stocks/batch-profile.boards` 的所属板块（用于和 portfolio.json 对照）

**每只 code 的个股层论据**：

- 长期趋势（365 日 features.trend）
- 短期趋势（近 5 日 features.pivots + features.trend）
- 当日分时（5m features.pivots.swings）
- 当前价 vs 顶底（pivots.window_high/low vs quote.price）
- 连续上涨后空间评估
- 当日涨幅 vs 涨停空间
- 主营近似（`info.data.business_scope` / `concepts`）

### 5.4 重合度（针对 watchlist 内票）

**输入**：
- `correlation/matrix`（每只 watchlist 票一次）
- `stocks/board-overlap`（watchlist 内两两板块重合）
- 双方 `info.data.business_scope` + `concepts`

**每只 code 的重合度论据**：

- 业务重合（主营描述对比）
- 板块重合（共同板块数 + Jaccard）
- 走势重合（Pearson ρ）
- 综合判断三层重合度

---

## 6. 输出格式

判断 skill 输出**Markdown 文本**，由 chat 或文件呈现（用户可指定写盘到 `<workspace>/trade_judgment/{date}.md`）。

### 6.1 模板

```markdown
# 持仓/关注判断 — {trade_date} {market_session}

## 市场环境（大盘）

**长期趋势**（沪深300 周线）：{features.trend 翻译}
**短期趋势**（沪深300 日线）：{features.trend 翻译}
**当日分时**：{5m features 翻译}
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

**当前状态**（来自 portfolio.json）：关注+持仓 200 股 @1807.50
**所属板块**（来自 portfolio.json）：白酒 (881xxx，THS platecode)

### 板块环境
**板块趋势**：{boards/batch-profile features 翻译}
**板块当日涨幅**：{boards.quote.change_pct:+.2f}%，落在 market-stats 桶 {bucket_label}（板块整体均值 {boards.mean_pct:+.2f}%）。`boards.quote` 已是 extended `MinimalQuote`（字段与单位见 agent-batch.md），不必再单拉 `/boards/{code}/quote`
**龙头/前 3**：
- 龙头 A (X 板): 价格 Y，涨幅 Z%
- 前 3 B: 价格 Y，涨幅 Z%
- 前 3 C: 价格 Y，涨幅 Z%
**板块内涨跌分布**：{从成分股计算}

### 个股自身
**长期趋势**（365 日）：{features.trend 翻译}
**短期趋势**（近 5 日）：{pivots + trend 翻译}
**当日分时**：{5m features 翻译}
**当前价 vs 顶底**：距 365 日高点 {X%}，距 365 日低点 {Y%}
**当日涨幅 vs 涨停空间**：主板 +10%（距涨停 {Z%}）
**主营**：{info.data.business_scope}

### 重合度（vs 龙头 A）
**业务重合**：{主营对比}
**板块重合**：共同板块 {N} 个，Jaccard {X}
**走势重合**：Pearson ρ {X}（强/中/弱相关）

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

---

## 7. 反模式

- ❌ 不要在判断 skill 内手动计算 MA / RSI / DMI 等指标——server 的 `build_features` 已经算好，直接读
- ❌ 不要在判断 skill 内手动分桶涨跌停——用 `/agent/market-stats` 的桶
- ❌ 不要遍历个股的所有所属板块——只用 portfolio.json 里用户指定的那一个最相关板块
- ❌ 不要对所有 watchlist 票算两两相关系数——只算每只 vs 各自龙头/前 3
- ❌ 不要让判断 skill 写 portfolio.json / events.jsonl——只读不写
- ❌ 不要在判断输出里给"目标价"——本 skill 不预测价格
- ❌ 不要把"硬门槛"塞进判断逻辑——股票判断是所有条件的总体权衡，没有绝对标准

---

## 8. 与其他 skill 的衔接

### 8.1 读

- `watchlist-manager` 的 `portfolio.json`（关注列表 + 持仓 + 板块映射）
- `watchlist-manager` 的 `events.jsonl`（近期操作节奏）
- `market-recap` 的 `market_tracking.md`（活跃主线 + 龙头股 + 板块轮动状态）
- `market-principles §6`（龙头识别方法论）
- `market-principles §5.1/5.2`（风险第一 / 量价原则）

### 8.2 写

- 默认输出到 chat（用户对话窗口）
- 用户要求存档时写到 `<workspace>/trade_judgment/{date}.md`

### 8.3 不做

- 不写 portfolio.json / events.jsonl（写操作走 `watchlist-manager`）
- 不调 stock_data server 的写接口（搜索 / 关注 / 取数全部是只读）
- 不预测价格 / 不给目标价 / 不建议仓位

---

## 9. 工作流示例

### 9.1 用户："看下 600519 现在怎样"

```
1. 路径 A：code ∈ portfolio.json → 读 关注.board
2. 拉数据：
   - 大盘 3 个 frequency（indices/batch-profile）
   - market-stats + market-context
   - 600519 所属板块 boards/batch-profile (d + 5m)
   - 600519 + 龙头 stocks/batch-profile (d=365 + 5m=5)
   - boards/{code}/stocks 取龙头/前 3
   - correlation/matrix (stocks: [600519, 龙头, top2, top3], boards: [board])
3. 论据翻译 → 输出 600519 一段
```

### 9.2 用户："扫一遍持仓"

```
1. 读 portfolio.json 的所有 codes
2. 去重所有 board_codes + 龙头 codes
3. 拉数据（同上但批量）：
   - stocks/batch-profile (分批 ≤5)
   - boards/batch-profile (分批 ≤5)
   - boards/{code}/stocks (每板块一次)
   - stocks/board-overlap (watchlist 内一次)
   - correlation/matrix (每只 watchlist 一次)
4. 输出：市场环境（一次）+ 每只 code 一段
```

### 9.3 用户："判断下 000001（不在 watchlist）"

```
1. 路径 B：反馈用户"请提供该股票所属板块 code + name（THS platecode 885xxx/881xxx）"
2. 用户提供后，启动判断（路径 A）
```