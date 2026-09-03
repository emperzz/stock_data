---
name: market-recap
description: A 股市场复盘 skill。agent 收到市场复盘请求时（盘前 / 盘中 / 盘后任一时段）使用。本 skill 是**复盘流程执行器**：规定"按什么顺序读、按什么策略写、归因到哪里"，不重复端点目录（走 `market-data-obtain`），不规定判断标准（走 `market-principles`）。
triggers:
  - "复盘" / "今日市场" / "市场总结" / "市场情况"
  - "盘前" / "早盘怎么看" / "开盘前"
  - "盘中" / "现在市场" / "盘中怎么样" / "午盘"
  - "盘后" / "今天市场怎么样" / "收盘总结" / "今天复盘"
  - "/market-recap"
scope:
  role: 复盘流程执行器（不规定判断标准、不做交易决策）
  market: A 股
  coverage:
    时段: pre-market / intraday / post-market 三时段自动判断
    全景层: 主板 / 创业板 / 科创板
    个股层: 主板 / 创业板 / 科创板
  exclusion:
    - 北交所个股作为龙头候选（30cm 涨跌幅与独立行情，主线识别时单独评估）
    - 美股 / 港股 / 期货 / 加密货币（超出 A 股范围）
    - 交易决策（仓位 / 止损 / 加减仓由用户自行决定）
  companions:
    - market-principles（判断方法论总入口；判断标准、文件管理协议、watchlist 约束）
    - market-data-obtain（数据获取；端点目录 + 服务器失败时的 fallback 策略）
---

# market-recap

A 股市场复盘 skill。**一个 skill 覆盖盘前 / 盘中 / 盘后三种时段**——agent 收到触发词后自动判断当前时段，按本 skill 描述的工作流执行复盘，输出 chat 精简摘要 + 写入 `market_recap/` 目录文件。

> **核心约束（来自 market-principles）**：本 skill 是**流程执行器**，不绑定任何特定数据 API；所有数据获取走配套 `market-data-obtain`（端点目录 + fallback 策略详见该 skill）；所有判断标准走配套 `market-principles`（方法论 + watchlist 约束详见该 skill）。

---

## 1. 适用场景

满足以下任一情况时启用本 skill：

- 用户说"复盘"、"今日市场"、"盘后总结"等显式触发词
- 用户在盘前 / 盘中 / 盘后请求市场看法（agent 通过当前时间判断时段）
- 用户调用 `/market-recap` 强制触发
- agent 在执行 `market-principles` 工作流时需要生成复盘产物
- 准备市场判断所需的 bootstrap 上下文（板块、龙头、资金、消息）

**不适用的请求**：

- 仓位管理、止损点、加减仓规则（属于交易决策层，本 skill 不覆盖）
- 美股、港股、外汇、期货、加密货币（市场范围超出 A 股）
- 长期价值投资、基本面研究（本 skill 隐含短线视角）
- 单只个股的深度研究（非市场复盘范畴）

---

## 2. 触发与时段自动判断

### 2.1 触发源

agent 通过以下任一方式激活本 skill：

| 来源 | 说明 |
|---|---|
| 关键词触发 | frontmatter `triggers` 列出的关键词 |
| 显式命令 | `/market-recap` 强制调用 |

### 2.2 时段自动判断

agent 根据当前 `Asia/Shanghai` 时间自动套用时段分支：

| 当前时间 | 模式 | 重点查询内容 |
|---|---|---|
| 交易日 09:15 前 | `pre-market` | 隔夜外盘（美股收盘）、昨日复盘、财联社早报、政策 / 公司公告预披露 |
| 交易日 09:15-15:00 | `intraday` | 当日分时、盘中新出的快讯与异动、实时资金流向 |
| 交易日 15:00 后 | `post-market` | 全天收盘行情、板块 / 个股涨跌排名、龙虎榜、热点题材、财联社焦点复盘 |

> **关键时间锚点**（影响数据完整度）：
> - **实时数据**（指数 / 个股行情 / 板块涨跌 / 涨停股池 / 资金流向）：交易时段持续可用，无需等待
> - **15:00 收盘**：当日板块涨跌排名完整、个股收盘行情定型
> - **17:00 后**：龙虎榜（深交所 / 上交所通常在 15:00-17:00 之间陆续发布）数据完整
> - **18:00 后**：财联社焦点复盘、各家盘后总结文章大部分发布
> - **20:30（美股开盘）后**：`pre-market` 模式下隔夜美股信息最完整

**用户可显式覆盖时段**：当用户措辞明确暗示其他时段（如 15:30 说"今天盘后"），agent 按用户意图覆盖自动判断。

---

## 3. 文件存储

### 3.1 目录结构

```
./market_recap/
├── YYYY-MM-DD.md        # 每日复盘（覆盖盘前 / 盘中 / 盘后三种模式）
└── market_tracking.md   # 跨日 watchlist（持续关注的板块 / 主线 / 龙头候选）
```

### 3.2 路径约定

- 每日文件路径：`./market_recap/{今天}.md`（如 `./market_recap/2026-07-21.md`）
- 跟踪文件路径：`./market_recap/market_tracking.md`（跨日单文件累积）

### 3.3 文件 vs Chat 分工

| 输出 | 内容 | 受众 |
|---|---|---|
| **chat 回复** | 精简摘要 + 结论（主线、龙头、归因） | 当下用户沟通 |
| **`{date}.md`** | 完整版（数据引用、源链接、时间戳、原始异动列表） | 事后追溯 / 跨日延续 |
| **`market_tracking.md`** | 跨日 watchlist（持续主线、龙头候选、待验证假设） | 跨日追踪 |

---

## 4. 工作流

agent 激活本 skill 后，按以下顺序执行（**步骤 1 是只读，步骤 2-4 是数据采集，步骤 5-6 是产出**）：

### 步骤 1：跨日读取（仅只读）

1. **先读 `./market_recap/market_tracking.md`** —— 拿到 watchlist
2. **根据 watchlist 内容决定要读哪些每日文件**：
   - 默认读**最近 3 个交易日**（含今天）的 `./market_recap/{date}.md`
   - 如 watchlist 中某个主线 / 龙头首次异动在更早（如 5 天前）→ 扩展读到那一天
3. **判断今天是否为首次复盘**（无历史）→ 跳过读取，直接进入步骤 2

**输出**：进入步骤 2 时，agent 心中已有的上下文：当前 watchlist、最近 N 天主线演化、待验证假设

### 步骤 2：判断时段

按第 2.2 节时段表分支，仅确定当前时段（`pre-market` / `intraday` / `post-market`）及对应时间锚点（17:00 龙虎榜、18:00 复盘、20:30 美股外盘等）。**本步不发起任何数据获取**——早报 / 美股收盘 / 消息面等全部在步骤 3 走 `/api/v1/agent/market-recap` 一次拿全，**服务器失败才** fallback 到 `market-data-obtain` 第 3 节的网络搜索协议（market-recap 不重复定义）。

### 步骤 3：拉取市场数据

**取数策略**：复盘所需的"市场全景"——指数三件套（上证 / 深证成指 / 创业板）+ 早报 / 复盘 / 快讯 + 个股 / 板块涨幅分布 + 涨跌停池——**统一走 `GET /api/v1/agent/market-recap` 一次拿全**（服务端聚合 + per-block 错误隔离，详见 [`market-data-obtain §9.1`](../market-data-obtain.md) 与 [agent-batch.md](./market-data-obtain/agent-batch.md)）。该端点对复盘流程的目标场景是"今天发生了什么 / 市场怎么走"，对所有时段（pre / intra / post / closed）均适用，参数仅 `flash_limit` / `include_boards` / `include_pools` / `format` 四个，无需选时段。

per-X 单次调用（龙虎榜、北向资金、个股资金流、个股新闻、公告、研报）仅在归因需要"个股级"或"事件级"信息时按需走主表端点；**龙虎榜不在本 skill 必经数据范围内**——归因需要时按 §4 步骤 4 单独走 `/api/v1/dragon-tiger`，否则不读。

### 步骤 4：归因（核心判断任务）

按 `market-principles` 的判断方法论（详见该 skill **第 5 节核心原则** + **第 6 节龙头股判断方法**）执行：

- **市场层面**：今日涨跌归因（政策 / 资金 / 外盘 / 事件）
- **市场情绪**：用**跌停 / 涨停比** + **跌停绝对数**两个维度综合判断情绪方向（强势 / 正常 / 偏弱 / 悲观）——具体定档由 agent 临场判定；跌停越多市场越悲观是核心直觉，但不锁死绝对阈值
- **板块层面**：领涨 / 领跌板块的归因（消息驱动 / 资金轮动 / 技术面）
- **板块 K 线走势**：领涨板块的三周期 K 线方向（上升 / 下降 / 震荡 / 突破）——关注大盘指数 K 线对板块走势的支撑 / 压制关系
- **个股层面**：龙头股连续涨停的归因（业绩 / 题材 / 事件 / 板块联动）

**轻量提醒**：归因时区分**事实**（搜索结果中明确写出的）和**推断**（基于事实的二次推断）；对**互相矛盾**的多源信息，列出主要分歧而非强行收敛。

**market-recap 不规定归因方法论本身**——具体判断标准完全走 market-principles。

### 步骤 5：chat 回复 + 写入文件

- **chat 回复**：精简摘要 + 结论（**市场情绪方向**、主线 1-N、龙头候选、**领涨板块 K 线方向**、关键归因）
- **`{date}.md`**：完整版（数据引用、源链接、时间戳、归因展开、板块 K 线方向）——**不列**涨跌停股原始明细，写入端点路径（`GET /zt-pools?type=zt\|dt`）供按需查询；文件保留"总结 + 重点关注的股票"。**`{date}.md` 嵌入**：本步骤要写入文件的取数（`GET /api/v1/agent/market-recap?format=md`）通过 `?format=md` 拿 markdown 投影直接 paste——服务端保证无信息丢失（每个 JSON 字段映射到 MD 表格 / 列表 / 段落），渲染失败自动回退 JSON，agent 永远能拿到数据
- **`market_tracking.md`**：本次复盘新识别的主线 / 龙头 / 待验证假设 + **强制追加**今日领涨板块至"持续关注的板块"区（**退出规则**：板块多日走弱 + 无龙头 → agent 临场判定淘汰，判定标准走 [market-files.md](./market-files.md) §4 移除规则）

### 步骤 6：处理用户追问

复盘完成后，用户可能追问：

- "X 板块为什么涨？" → 按步骤 4 局部重做归因，更新 `{date}.md` 该板块章节
- "Y 龙头能买吗？" → **不属于本 skill 范畴**，引导用户走交易决策层
- "再详细说说 Z" → 展开 `{date}.md` 中的相关章节到 chat

---

## 5. 写入策略

### 5.1 每日文件 `{date}.md`

**模板与写入协议**：每日 md 的模板（消息 / 时间戳判断 / 主线归因 / 判断演化日志）、覆写 / 追加策略、写入前必做见 [market-files.md](./market-files.md) §2 + §3——market-recap 不重复定义，**与 `market-principles` 共用同一份模板**。

**首次写入**：先 Write 完整模板骨架；之后每次按 [market-files.md](./market-files.md) 的覆写 / 追加协议操作。

### 5.2 跟踪文件 `market_tracking.md`

**模板与结构**：参照 [market-files.md](./market-files.md) §4——含 活跃主线 / 减弱主线 / 持续关注的龙头股 / 板块轮动状态 / 未兑现的逻辑。market-recap 不重复定义模板，**与 `market-principles` 共用同一份模板**。

**slug 命名**：主线条目 `标识` 字段的 slug 硬规则 + 创建工作流见 [market-files.md](./market-files.md) 附录 A，词汇映射表见 [slug_glossary.md](./slug_glossary.md)。**禁止自由命名**。

**更新规则**：每次复盘按需同步更新（全量重写或 diff 增量均可，见 [market-files.md](./market-files.md) §2）；移除 / 淘汰触发见 [market-files.md](./market-files.md) §4 移除规则。

---

## 6. 与配套 Skills 的协作

### 6.1 与 `market-data-obtain` 的关系

**market-recap 是数据消费者，`market-data-obtain` 是数据提供者。** 本 skill **不重复定义**：

- 端点目录（行情 / 资金面 / 基础数据 / 公告 / 研报 / 特殊池 / 新闻 → market-data-obtain 第 4-11 节）
- 服务器失败时的 fallback 策略（market-data-obtain 第 3 节）
- 信源优先级（market-data-obtain 第 3.2 节）

agent 在执行步骤 2-3 时，按需跳读 `market-data-obtain` 取端点。

### 6.2 与 `market-principles` 的关系

**market-recap 是流程执行器，`market-principles` 是判断方法论总入口。** 本 skill **不规定**：

- 归因判断标准（市场 / 板块 / 个股归因的原则 → market-principles 第 5 节）
- 文件模板（每日 md / market_tracking.md 模板 → [market-files.md](./market-files.md) §3 / §4）
- 写入协议（覆写 / 追加 / 淘汰触发 → [market-files.md](./market-files.md) §2 / §4 移除规则）
- watchlist 维护规则（[market-files.md](./market-files.md) §4 移除规则 + §2 任务前后协议）

agent 在执行步骤 4-5 时，按需跳读 `market-principles` 取判断方法。

### 6.3 早报模式说明

本 skill 没有独立的 morning-briefing skill——早报与复盘统一由本 skill 承担：盘前模式输出早报内容（总结**隔夜变化**：外盘 + 政策 + 公告预披露），盘后模式输出复盘内容（总结**日内变化**：涨跌 + 板块轮动 + 龙头归因），写入**同一个**每日文件（按时间戳判断块自然区分）。

---

## 7. Anti-patterns（不要做）

- **不要**凭记忆猜或硬编端点 —— 取数时去 `market-data-obtain` 查当前端点（服务器端点会变，硬编即漂移）
- **不要**规定判断标准（"消息影响市场的判定：政策 > 业绩 > 行业新闻"等） —— 判断标准走 `market-principles`
- **不要**把北交所个股与主板 / 创业板直接比较连板高度 —— 北交所 30cm 涨跌幅与独立行情，龙头识别时单独评估
- **不要**写完文件不更新 `market_tracking.md` —— watchlist 是本 skill 的核心产出
- **不要**把 chat 回复写成"复制文件全文" —— chat 是结论层、文件是证据层，分工明确
- **不要**在 18:00 前硬要输出盘后总结 —— 此时信息不完整，应在 post-market 模式下提醒用户"待 18:00 后数据齐全再复盘"
- **不要**做交易决策（"建议买入"、"止损位 N 元"） —— 交易决策层由用户自行决定
- **不要**在盘中模式下硬要"找齐今天所有原因" —— 盘中数据不全，归因尽量但不强求
- **不要**为同一天的多次调用保留多份独立文件（如 `2026-07-21-am.md` / `2026-07-21-pm.md`）—— 同日多模式合并到单文件 + 时间戳判断块
- **不要**在 `{date}.md` 列出所有涨跌停股原始明细 —— 写入端点路径（`GET /zt-pools?type=zt\|dt`）供按需查询，文件保留"总结 + 重点关注的股票"即可
- **不要**把复盘所需的市场全景（指数 + 消息 + 涨跌停池 + 情绪桶）拆成多个 per-call 手拼 —— 统一走 `GET /api/v1/agent/market-recap` 一次拿全（§4 步骤 3）；该端点内部已聚合 `market-context` + `market-stats` + 3 指数 quote，agent 无需再单点拉这三条
- 龙虎榜（`/api/v1/dragon-tiger`）按需且归因需要时单独拉，**不**进复盘必经流程——避免无关消费与无谓上下文开销
- **不要**把 `agent/*` 响应拿 JSON 后再 client-side 转 markdown 嵌入 `{date}.md` —— 直接 `?format=md` 让服务端投影（§4 步骤 5）

---

## 8. 典型调用示例

### 8.1 盘前 briefing（09:00）

```
用户："今天市场怎么看？"

agent 流程：
1. 读取 market_tracking.md + 最近 3 个交易日文件
2. 判断时段：pre-market
3. 数据获取：`GET /api/v1/agent/market-recap?format=md`（一次拿全 3 指数 + 早报 / 复盘 / 快讯 + 涨跌停池 + 全市场情绪桶；服务端 fallback 走网络搜索协议）
4. 归因：今日可能的主线（基于昨日尾盘 + 隔夜外盘 + 早报）
5. 输出：
   - chat：今日关注主线 1-N，关键事件 X、Y、Z
   - 文件：2026-07-21.md（追加 [HH:MM] 时间戳判断块 + 更新消息 / 复盘块）
   - tracking：追加新主线 / 更新主线天数
```

### 8.2 盘中 intraday（11:30）

```
用户："现在市场怎么样？"

agent 流程：
1. 读取今日已有文件（如果盘前已写过）
2. 判断时段：intraday
3. 数据获取：`GET /api/v1/agent/market-recap?format=md`（一次拿全 3 指数分时 + 当日涨跌停池 + 盘中快讯 + 实时情绪桶）
4. 归因：上午的板块轮动 + 异动个股归因
5. 输出：
   - chat：上午主线、关键异动、盘中关注点
   - 文件：2026-07-21.md（追加 [HH:MM] 时间戳判断块）
   - tracking：识别新主线则追加
```

### 8.3 盘后 recap（18:30）

```
用户："今天复盘"

agent 流程：
1. 读取今日已有文件（盘前 / 盘中内容）
2. 判断时段：post-market
3. 数据获取：`GET /api/v1/agent/market-recap?format=md`（一次拿全当日收盘 + 板块涨跌排名 + 涨停股池 + 财联社焦点复盘）
4. 覆写顶部"消息" / "复盘"块（用最新数据替换盘中版本）
5. 归因：全天主线 / 板块归因 / 龙头归因
6. 输出：
   - chat：今日主线 1-N、龙头候选、关键归因
   - 文件：2026-07-21.md（追加 [HH:MM] 时间戳判断块 + 覆写消息 / 复盘块）
   - tracking：本次复盘新识别的主线 / 龙头 / 待验证假设
```

---

## 9. 跨 skill 调用约定

收到市场复盘请求时：

1. **优先看本 skill 的 frontmatter triggers** —— 匹配则激活本 skill
2. **数据采集跳读 `market-data-obtain`** —— 取端点和 fallback 策略
3. **归因跳读 `market-principles`** —— 取判断方法论和 watchlist 约束
4. **不要**把本 skill 当作"什么都能答"的入口 —— 超出复盘范畴（交易决策、单股深度研究）的请求引导用户走其他 skill 或自行处理