---
name: watchlist-manager
description: 个股监控列表管理 skill。维护用户的"关注"与"持仓"状态——新增关注、记录买入/卖出、查询当前快照、补全关注/操作原因、取消关注并归档。配套 `market-principles` 与 `trade-timing-advisor` 使用——本 skill 是**状态 CRUD 执行器**：规定"按什么命令操作、字段怎么写、什么情况追问、什么情况阻止"，不重复判断逻辑（买卖时机判断走 `trade-timing-advisor`），不重复取数方法论（端点走 `market-data-obtain`）。
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
    - 主动行为（agent 不会主动建议关注、不会主动提醒补全 reason、不会主动调用判断 skill）
  companions:
    - trade-timing-advisor（判断买卖时机；本 skill 不做判断）
    - market-principles（判断方法论总入口）
    - market-data-obtain（取数；本 skill 不取数，但判断 skill 消费本 skill 的 portfolio.json）
---

# watchlist-manager

个股监控列表管理 skill。**纯被动状态写入器**——只在用户主动发起请求时操作文件，不主动判断、不主动触发其他 skill。

> **核心约束**：本 skill 不绑定任何特定数据 API。判断逻辑（"该不该买"、"该不该卖"）一律走 `trade-timing-advisor`。本 skill 只负责"用户说做了什么，就忠实地记录什么"。

---

## 1. 适用场景

满足以下任一情况时启用本 skill：

- 用户要新增 / 修改 / 删除关注股票
- 用户报告已发生的买入 / 卖出操作
- 用户想查看当前持仓 / 关注快照
- 用户要补全某只股票的关注原因或操作原因

**不适用的请求**：

- 判断买卖时机 / 复盘 / 选股 / 板块分析 → 走 `trade-timing-advisor` / `market-recap` / `stock-picking`
- 仓位 / 止损 / 加减仓策略 → 交易决策层，本 skill 不覆盖

---

## 2. 数据文件结构

本 skill 维护**3 个文件**，全部放在和 `market_tracking.md` **同一目录**下：

```
<workspace>/
  portfolio.json                 # 当前快照（按 code 管理）
  events.jsonl                   # 事件流（append-only，source of truth）
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
      "关注": {
        "reason": "高端消费复苏",
        "added_at": "2026-08-27",
        "board": { "code": "881xxx", "name": "白酒" }
      },
      "持仓": {
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

**关键字段说明**：

- `codes[]` 按 code 索引（一个 code 一条记录），关注与持仓是该 code 的子状态字段
- `关注.board` **必填**，且 `code` **必须是 THS platecode**（`885xxx` 概念 / `881xxx` 行业）——下游 `trade-timing-advisor` 的板块取数走 THS 单源，东财 `BKxxxx` 等异源代码会在判断时 422。加关注时若用户未提供，反馈用户要求提供 code + name
- `关注.reason` 可选——用户没给就留空字符串，**agent 不自动生成**
- `持仓` 可为 `null`（仅关注未买入）；非空时 `shares > 0`
- `last_event_action` 记录该 code 最近一次操作方向，供判断 skill 快速读取

### events.jsonl 结构（每行一个 JSON）

```json
{"ts": "2026-08-27T10:30:00", "code": "600519", "action": "buy", "shares": 100, "price": 1820.50, "reason": "首次建仓"}
```

- `action` ∈ `{"buy", "sell"}`（**只有两个取值**，加仓/减仓/止损/止盈统一记为 buy/sell）
- `reason` 可选字符串——用户没给就留空，**agent 不自动生成**

### archive/removed_codes.json 结构

```json
[
  {
    "code": "000034",
    "name": "神州数码",
    "关注_added_at": "2026-06-10",
    "removed_at": "2026-08-27",
    "removed_reason": "板块走弱" | ""
  }
]
```

`removed_reason` 可选——用户没给就留空。

---

## 3. 数据一致性规则

### 3.1 事件流为唯一真相源

**所有 portfolio.json 的字段都由 events.jsonl 派生**。每次写入事件后必须：

1. 追加一行到 `events.jsonl`
2. 重算该 code 的 `持仓.shares`、`持仓.avg_cost`、`持仓.last_event_at`、`last_event_action`
3. 更新 `portfolio.json`

**重算公式**：

```
总买入金额 = Σ(buy.shares × buy.price)
总卖出金额 = Σ(sell.shares × sell.price)
剩余份额 = Σ(buy.shares) - Σ(sell.shares)
平均持仓成本 = (总买入金额 - 总卖出金额) / 剩余份额
```

`剩余份额 == 0` 时 → 该 code 的 `持仓` 字段设为 `null`，但**保留主表行**（用户仍可能关注一只已清仓的票）。

> **为什么 events.jsonl 是 source of truth**：双写时如果 portfolio.json 写成功、events.jsonl 写失败，或反过来，会留下不一致状态。agent 是唯一写入方（用户操作后告诉 agent），追加 + 重算顺序操作，要么都成功要么都失败。

### 3.2 code 主键不变性

- `codes[]` 中每个 code **只有一条记录**——关注和持仓是该 code 的子字段
- 同一 code 再次"关注"不是新增记录，而是**已存在则只更新 `关注.added_at`（如果用户要求）**
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
| `关注.board.code` | **必须用户提供**，无默认（THS platecode 885xxx/881xxx） |
| `关注.board.name` | 必须用户提供，或由 board code 反查 |

**选填字段**：

| 字段 | 处理 |
|---|---|
| `关注.reason` | 用户提供就写，否则留空字符串 |
| `关注.added_at` | 默认当天（YYYY-MM-DD） |

**操作流程**：

1. 检查 code 是否已存在于 `codes[]`
2. 存在 → 更新该 code 的 `关注.*` 字段（`added_at` 默认不动，用户说"重新加入"才更新）
3. 不存在 → 新增条目，`持仓: null`，`last_event_action: null`

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
| `reason` | 用户提供就写，否则留空字符串 |

**操作流程**：

1. 验证 code 已存在于 `codes[]`——**若不存在则提示用户先加关注**（"code X 不在关注列表，要先关注吗？"），等用户决定
2. 验证 shares / price / ts 都是正数且 ts 不晚于今天
3. 追加到 `events.jsonl`
4. 重算该 code 的 `持仓` 字段：
   - 算剩余份额 = 旧份额 + (action=buy ? +shares : -shares)
   - 剩余份额 == 0 → `持仓` 设为 `null`，但保留主表行
   - 剩余份额 > 0 → 按公式重算 `avg_cost`
5. 更新 `last_event_action` 和 `持仓.last_event_at`（或首次买入时 `持仓.first_event_at`）

**反模式**：

- ❌ 不要把"加仓" / "减仓" / "止损" / "止盈" 当独立 action type——统一是 `buy` / `sell`，上下文写在 `reason` 字段
- ❌ 不要自动生成 reason——用户没给就留空
- ❌ 不要"猜测"用户没说的字段——缺哪个就追问哪个

### 4.3 查询

**触发**：用户说"看下我的持仓" / "我的关注列表" / "持仓清单" / "X 现在状态如何"

**行为**：

- 读 `portfolio.json`，按用户要求展示（全部 / 单只 / 按关注分组）
- **不调任何 server API**——本 skill 是纯文件操作

### 4.4 取消关注

**触发**：用户说"取消关注 X" / "不再关注 X"

**操作流程**：

1. 检查该 code 是否存在
2. 检查 `持仓.shares`：
   - **shares > 0** → 阻止，反馈用户"该 code 仍有持仓 X 股（平均成本 Y），请确认是否还有未告知的卖出操作"，等用户明确
   - **shares == 0 或 持仓 == null** → 直接从 `codes[]` 删除 + 追加到 `archive/removed_codes.json`
3. 不二次确认，直接执行

### 4.5 补全 reason

**触发**：用户说"补全 X 的关注原因：Y" 或 "X 的买入原因是 Y"

**操作流程**：

- "关注原因" → 更新 `codes[].关注.reason`
- "买入/卖出原因" → **不修改历史 events.jsonl**（append-only 不变性），而是新增一条 note 提示用户"events.jsonl 是 append-only，历史操作原因不能回填；如需记录，可追加一条新的 buy/sell with reason"

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

### 6.1 完全被动

agent **不会**主动：

- ❌ 建议用户关注某只股票
- ❌ 提醒用户补全 reason（用户没说就不提）
- ❌ 触发 `trade-timing-advisor`（用户问"现在该不该买"才走判断 skill）
- ❌ 校验数据合理性（用户说"100股 @1元" agent 也照写，不评判）

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

---

## 8. 与 trade-timing-advisor 的衔接

- `portfolio.json` 是 `trade-timing-advisor` 的输入数据源之一（读取 `关注.board.code`、`持仓.shares/avg_cost` 等）
- 本 skill **不调** `trade-timing-advisor`
- `trade-timing-advisor` **不写** portfolio.json / events.jsonl（判断输出是文本/对话，不落盘）

判断 skill 的入口命令（"X 现在怎样"、"判断下 X"）**不走本 skill**——直接走判断 skill 的命令动词清单。