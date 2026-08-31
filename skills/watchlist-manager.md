---
name: watchlist-manager
description: 个股监控列表管理 skill。维护用户的"watch"（关注）与"position"（持仓）状态——新增关注、记录买入/卖出、查询当前快照、补全关注/操作原因、取消关注并归档。本 skill 是**纯被动状态写入器**：只规定"按什么命令操作、字段怎么写、什么情况追问、什么情况阻止"，不做交易判断也不绑定任何特定下游消费者。
triggers:
  - "关注 X" / "加关注 X" / "加入关注 X"
  - "我买了 X" / "买入 X" / "建仓 X"
  - "我卖了 X" / "卖出 X" / "清仓 X" / "减仓 X"
  - "看下我的持仓" / "我的关注列表" / "持仓清单"
  - "取消关注 X" / "不再关注 X"
  - "补全 X 的原因：Y" / "更新 X 的关注原因"
  - "/watchlist-manager"
scope:
  role: 状态 CRUD 执行器（不规定判断标准、不做交易决策、不主动触发任何分析）
  market: A 股
  coverage:
    主体: 主板 / 创业板 / 科创板
  exclusion:
    - 北交所个股 / ST 股 / 美股 / 港股 / 期货 / 加密货币（超出 A 股范围）
    - 交易决策（仓位 / 止损 / 加减仓由用户自行决定）
    - 主动行为（agent 不会主动建议关注、不会反复追问 reason、不会主动调用任何判断 skill）
---

# watchlist-manager

个股监控列表管理 skill。**纯被动状态写入器**——只在用户主动发起请求时操作文件，不主动判断、不主动触发其他 skill。

> **核心约束**：本 skill 是文件状态写入层（writer），不做任何交易判断。"该不该买"、"该不该卖"由用户或专门的判断 skill 自行处理，本 skill 不耦合到任何特定下游消费者。判断 skill 若要消费本 skill 的产出，按需读 `portfolio.json` / `events.jsonl` 即可（详见 [数据文件结构](#2-数据文件结构) 与 [数据一致性规则](#3-数据一致性规则)）。

---

## 1. 适用场景

满足以下任一情况时启用本 skill：

- 用户要新增 / 修改 / 删除关注股票
- 用户报告已发生的买入 / 卖出操作
- 用户想查看当前持仓 / 关注快照
- 用户要补全某只股票的关注原因或操作原因

**不适用的请求**：

- 判断买卖时机 / 复盘 / 选股 / 板块分析 → 走对应的判断 / 复盘 / 选股 skill
- 仓位 / 止损 / 加减仓策略 → 交易决策层，本 skill 不覆盖

---

## 2. 数据文件结构

本 skill 维护 **3 个文件**，全部放在和 `market_tracking.md` **同一目录**下：

```
<workspace>/
  portfolio.json                 # 当前快照（按 code 管理）
  events.jsonl                   # 事件流（operations append-only；reason 字段可回填）
  archive/
    removed_codes.json           # 取消关注的 code 备份
```

### portfolio.json 结构

```json
{
  "codes": [
    {
      "code": "600519",
      "name": "贵州茅台",
      "watch": {
        "reason": "高端消费复苏",
        "added_at": "2026-08-27",
        "board": { "code": "881xxx", "name": "白酒" }
      },
      "position": {
        "shares": 200,
        "avg_cost": 1807.50,
        "first_event_at": "2026-07-10",
        "last_event_at": "2026-08-27"
      } | null,
      "last_event_action": "buy" | "sell" | null
    }
  ]
}
```

**字段命名**：watch（关注）+ position（持仓）是两个互不依赖的子状态；同一 code 在 watch 但未买入时 `position` 为 `null`。

**关键字段说明**：

- `codes[]` 按 code 索引（一个 code 一条记录），watch 与 position 是该 code 的子状态字段
- `watch.board` **必填**，`code` **必须是 THS platecode**（`885xxx` 概念 / `881xxx` 行业）。理由：stock_data server 的板块端点（板块 K 线、成分股、板块统计等）走 THS 单源，异源代码（如东财 `BKxxxx`）无法通用。在加关注时一次性记录，可避免事后手工补查。**异源代码不要写入**。加关注时若用户未提供，反馈用户要求提供 code + name
- `watch.reason` 可选——用户没给就留空字符串，**agent 不自动生成**
- `position` 可为 `null`（仅关注未买入）；非空时 `shares > 0`
- `last_event_action` 记录该 code 最近一次操作方向，供下游消费者快速读取

### events.jsonl 结构（每行一个 JSON）

```json
{"ts": "2026-08-27T10:30:00", "code": "600519", "action": "buy", "shares": 100, "price": 1820.50, "reason": "首次建仓"}
```

- `action` ∈ `{"buy", "sell"}`（**只有两个取值**，加仓/减仓/止损/止盈统一记为 buy/sell）
- `reason` 可选字符串——用户没给就留空，**agent 不自动生成**
- **append-only 范围**：新增操作（buy/sell）只能通过追加新行完成，**不允许**删除或修改既有行的 `ts` / `code` / `action` / `shares` / `price`。**`reason` 字段可回填**——回填采用"按行重写"方式（详见 [§4.5 补全 reason](#45-补全-reason)）。这一区分的理由：`ts/code/action/shares/price` 是金融事实，事后不可改；`reason` 是用户事后可补全的注释
- 该文件是 portfolio.json `position` 字段的 **source of truth**——`position.shares / avg_cost / first_event_at / last_event_at / last_event_action` 任何时候都可由 events.jsonl 重算得出

### archive/removed_codes.json 结构

```json
[
  {
    "code": "000034",
    "name": "神州数码",
    "added_at": "2026-06-10",
    "reason": "关注时的原因（高端服务器渠道转型预期）",
    "board": { "code": "881xxx", "name": "信息技术" },
    "removed_at": "2026-08-27",
    "removed_reason": "板块走弱" | ""
  }
]
```

**字段说明**：

- `added_at` —— 加关注的时间（YYYY-MM-DD）
- `reason` —— **加关注时**填写的 reason（非 removed 时的原因）；用户当时未填写则为空字符串
- `board` —— 加关注时记录的板块快照（保留便于事后追溯"当时为什么关注它"）
- `removed_reason` 可选——用户没给就留空
- 字段命名沿用 portfolio.json 的英文 schema（`added_at` / `reason` / `board`），**不再带 `关注_` 前缀**

---

## 3. 数据一致性规则

### 3.1 事件流为唯一真相源

**所有 portfolio.json 的 `position.*` 字段都由 events.jsonl 派生**。每次写入事件后必须：

1. 追加一行到 `events.jsonl`（新行可写完整 reason，也可后续回填）
2. 重算该 code 的 `position.shares`、`position.avg_cost`、`position.last_event_at`、`last_event_action`
3. 更新 `portfolio.json`

**重算公式**：

```
总买入金额 = Σ(buy.shares × buy.price)
总卖出金额 = Σ(sell.shares × sell.price)
剩余份额 = Σ(buy.shares) - Σ(sell.shares)
平均持仓成本 = (总买入金额 - 总卖出金额) / 剩余份额
```

`剩余份额 == 0` 时 → 该 code 的 `position` 字段设为 `null`，但**保留主表行**（用户仍可能关注一只已清仓的票）。

**回填 reason 时不必重算 position**：回填只修改 events.jsonl 中已有行的 `reason` 字段，不改变 ts/code/action/shares/price，因此 portfolio.json 的 position 派生结果不变。

### 3.2 code 主键不变性

- `codes[]` 中每个 code **只有一条记录**——watch 和 position 是该 code 的子字段
- 同一 code 再次"关注"不是新增记录，而是**已存在则只更新 `watch.*` 字段**（`added_at` 默认不动，用户说"重新加入"才更新）
- 取消关注 = 主表删除该 code + 写 archive

---

## 4. 命令动词清单

agent 根据用户输入识别命令 → 映射到 schema 操作。

### 4.1 加关注 / 修改关注

**触发**：用户说"关注 X / 加关注 X / 把 X 加入关注"

**必填字段**（缺一就追问）：

| 字段 | 来源 |
|---|---|
| `code` | 用户提供（优先 code，可由 name 反查但需确认） |
| `name` | 用户提供，或由 code 反查 |
| `watch.board.code` | **必须用户提供**，无默认（THS platecode 885xxx/881xxx） |
| `watch.board.name` | 必须用户提供，或由 board code 反查 |

**选填字段**：

| 字段 | 处理 |
|---|---|
| `watch.reason` | 用户提供就写，否则留空字符串；agent **触发后会追问一次** reason（详见 [§6.1](#61-完全被动)） |
| `watch.added_at` | 默认当天（YYYY-MM-DD） |

**操作流程**：

1. 检查 code 是否已存在于 `codes[]`
2. 存在 → 更新该 code 的 `watch.*` 字段（`added_at` 默认不动，用户说"重新加入"才更新）
3. 不存在 → 新增条目，`position: null`，`last_event_action: null`
4. 完成后追问一次"要补 reason 吗？"，用户答复则回填（见 [§4.5](#45-补全-reason)）

### 4.2 记录买入 / 卖出

**触发**：用户说"我买了 X / 买入 X / 建仓 X / 加仓 X / 我卖了 X / 卖出 X / 清仓 X / 减仓 X"

**必填字段**（缺一就追问）：

| 字段 | 来源 |
|---|---|
| `code` | 用户提供 |
| `action` | 用户语义判断（买/卖），或用户明确说"buy"/"sell" |
| `shares` | 用户提供的股数 |
| `price` | 用户提供的成交价 |
| `ts` | 成交时间（YYYY-MM-DD HH:MM:SS 或 YYYY-MM-DD） |

**选填字段**：

| 字段 | 处理 |
|---|---|
| `reason` | 用户提供就写，否则留空字符串；agent **触发后会追问一次** reason |

**操作流程**：

1. 验证 code 已存在于 `codes[]`——**若不存在则提示用户先加关注**（"code X 不在关注列表，要先关注吗？"），等用户决定
2. 验证 shares / price / ts 都是正数且 ts 不晚于今天
3. 追加到 `events.jsonl`（**只追加新行，不修改既有行的 action/shares/price/ts**）
4. 重算该 code 的 `position` 字段：
   - 算剩余份额 = 旧份额 + (action=buy ? +shares : -shares)
   - 剩余份额 == 0 → `position` 设为 `null`，但保留主表行
   - 剩余份额 > 0 → 按公式重算 `avg_cost`
5. 更新 `last_event_action` 和 `position.last_event_at`（或首次买入时 `position.first_event_at`）
6. 完成后追问一次"要补 reason 吗？"，用户答复则按 [§4.5](#45-补全-reason) 回填

**反模式**：

- ❌ 不要把"加仓" / "减仓" / "止损" / "止盈" 当独立 action type——统一是 `buy` / `sell`，上下文写在 `reason` 字段
- ❌ 不要自动生成 reason——用户没给就留空
- ❌ 不要"猜测"用户没说的字段——缺哪个就追问哪个

### 4.3 查询

**触发**：用户说"看下我的持仓" / "我的关注列表" / "持仓清单" / "X 现在状态如何"

**行为**：

- 读 `portfolio.json`，按用户要求展示（全部 / 单只 / 按 watch 分组）
- **不调任何 server API**——本 skill 是纯文件操作

### 4.4 取消关注

**触发**：用户说"取消关注 X" / "不再关注 X"

**操作流程**：

1. 检查该 code 是否存在
2. 检查 `position.shares`：
   - **shares > 0** → 阻止，反馈用户"该 code 仍有持仓 X 股（平均成本 Y），请确认是否还有未告知的卖出操作"，等用户明确
   - **shares == 0 或 position == null** → 直接从 `codes[]` 删除 + 追加到 `archive/removed_codes.json`
3. 不二次确认，直接执行

### 4.5 补全 reason

**触发**：用户说"补全 X 的关注原因：Y" / "X 的买入原因是 Y" / agent 在 [§4.1](#41-加关注--修改关注) / [§4.2](#42-记录买入--卖出) 后追问得到的答复

#### 4.5.1 补全 watch.reason

- 直接更新 `codes[].watch.reason`

#### 4.5.2 补全 events.jsonl 中某条 buy/sell 的 reason

- **匹配规则**：默认匹配**该 code 最近一次**对应 action（buy 或 sell）的 event 行；若用户指定了日期或时间戳，则匹配该日（YYYY-MM-DD）内最近一次对应 action 的 event 行
- **写入方式**：用更新后的 `reason` 重写该行 JSON 并原地写回 events.jsonl。**该行的 ts/code/action/shares/price 一律不改**
- **匹配失败**：若 events.jsonl 中找不到匹配行，反馈用户"没有可补全的 event 行；若您想记录新的操作，请用买入/卖出命令"，**不要**伪造一条 event 行

#### 4.5.3 不允许的反模式

- ❌ 不要为了"补全"而新增一条 buy/sell event 行——补全是修改既有行，不是新增操作
- ❌ 不要把"加仓/减仓/止损/止盈"作为 reason 的枚举值——reason 就是自由文本
- ❌ 不要在补全 reason 时重算 portfolio.json（reason 不影响 position 派生结果）

---

## 5. 输入完整性规则

agent 写之前必须验证用户输入是否齐全。决策表：

| 用户输入形态 | 示例 | agent 行为 |
|---|---|---|
| **结构化齐全** | "买入 600519，100 股 @1820，时间 2026-08-27 10:30，原因是 X" | **直接写** |
| **缺关键字段**（code/shares/price/time 任一缺失） | "我买了 600519 100 股"（没价格） | **追问**到字段齐全才写 |
| **缺识别字段**（code/name 任一缺失） | "我买了一些茅台"（没 code） | **追问** |
| **缺 board**（仅加关注时） | "关注茅台"（没 board） | **追问** board（THS platecode code + name） |
| **模糊语义** | "好像"、"估计"、"可能"、"应该买了点" | **拒绝写入**，要求用户重新确认 |

**特别注意**：

- 追问是结构化的输入验证（"我需要 X 才能写"），不是 agent 的"我觉得你应该..."
- agent 不允许基于历史或默认值自动补全任何字段
- agent 追问之后必须等用户回复

---

## 6. agent 行为边界（重要）

### 6.1 主动 vs 一次性询问

agent **不会**主动：

- ❌ 建议用户关注某只股票
- ❌ **反复**追问 reason——追问只在用户**刚触发** watch/buy/sell 操作后**进行一次**，用户不答就记空 reason 继续流程，下次再触发同样的操作时也不重提（避免骚扰）
- ❌ 主动调用任何下游判断 skill（用户明确说"判断下"才走）
- ❌ 校验数据合理性（用户说"100股 @1元" agent 也照写，不评判）

agent **会**：

- ✅ 在 [§4.1](#41-加关注--修改关注) / [§4.2](#42-记录买入--卖出) 完成后**一次**询问"要补 reason 吗？"——这是补全数据完整性的一环，不算主动行为

### 6.2 不写模糊记录

如果用户输入含糊到 agent 无法解析为具体操作，agent 必须追问或拒绝，**绝不**写一条带猜测字段的事件。

### 6.3 archive 不可逆

`archive/removed_codes.json` 一旦写入就保留作审计。不删除、不修改、不二次归档（同一 code 不会被归档两次——它已经从主表移除了）。

---

## 7. 反模式

- ❌ 不要在 fetcher 或 route 层调用本 skill——本 skill 是 agent 侧的 Markdown，调用方是 agent 自己
- ❌ 不要让 portfolio.json 持久化历史——历史全部在 events.jsonl，portfolio.json 任何时候都可以从 events.jsonl 重算
- ❌ 不要把 reason 字段做枚举（"建仓" / "加仓" / "止损"）——它就是自由文本，用户怎么写就怎么记
- ❌ 不要在 agent 收到 buy/sell 操作后立即调判断 skill——本 skill 写完就结束，不联动
- ❌ 不要给 portfolio.json 加 schema 版本号或迁移逻辑——schema 是 agent 内部约定，变了就改 agent 的读取逻辑，旧 portfolio.json 可以直接读（旧字段被忽略）
- ❌ 不要把本 skill 视为某个下游 skill 的"前置依赖"——它只是状态写入器，任何下游消费者（判断 skill / 复盘 / 用户自定义查询）按需读 portfolio.json / events.jsonl 即可，**不存在必然的上下游关系**
