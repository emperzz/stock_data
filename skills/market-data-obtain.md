---
name: market-data-obtain
description: A 股市场数据获取 skill。配套 `market-principles` 使用——告诉 agent 在做市场判断时，**所有数据获取都先走本 skill 描述的服务器端点**；服务器失败或返回空时，fallback 到 agent 自带的网络搜索 / 抓取工具（具体工具名因 agent 平台而异）总结再回复。本 skill 是服务器能力的完整参考手册：主文件只列端点清单（端点 / capability / 一句话用途），**每个端点的字段、单位、调用约束、示例见 `market-data-obtain/` 目录下的 detail 文件**——调用任何 API 前**必须**先 Read 对应 detail 文件。
triggers:
  - "需要数据" / "查询数据" / "获取行情"
  - "搜索新闻" / "查新闻" / "查公告" / "查研报"
  - "看资金流" / "看龙虎榜" / "看板块" / "看涨跌停"
  - "数据获取" / "数据查询"
  - "为什么涨/跌"（外部事件型原因 → 先服务器新闻能力，失败再 fallback 到 agent 自带的网络搜索工具）
scope:
  role: 仅做"**去哪里取数据 + 取不到时怎么办**"的方法论。不规定如何判断、不规定仓位决策。
  market: A 股（含主板 / 创业板 / 科创板，详见 market-principles）
  companion: market-principles（总入口）；本 skill 是其数据获取章节的展开
---

# market-data-obtain

A 股市场数据获取 skill。本 skill **不绑定任何特定数据 API**——agent 通过服务器 HTTP 端点（详见各 fetcher 实现）获取数据，agent 自行决定调用方式（HTTP / Python SDK / explorer UI）。

> **核心约束（来自 market-principles）**：所有市场数据获取都应通过本 skill 描述的服务器能力；服务器失败或返回空时，**fallback 到 agent 自带的网络搜索 / 抓取工具**总结再回复。详见第 3 节。

---

## 0. 使用守则

**调用本 skill 中任何 API 前，必须先 Read 对应 detail 文件**（路径见下方目录），获取字段、单位、调用约束、示例。主表只列端点路径 + capability + 一句话用途，**不读 detail 直接调用**会因单位 / 约束不熟导致 422 / 解析错误。

### detail 目录

| 文件 | 覆盖范围 | 端点数 |
|---|---|---|
| [market-data.md](market-data-obtain/market-data.md) | §4 行情类 | 8 |
| [capital-flow.md](market-data-obtain/capital-flow.md) | §5 资金面 | 6 |
| [fundamentals.md](market-data-obtain/fundamentals.md) | §6 基础数据 | 1 |
| [announcements.md](market-data-obtain/announcements.md) | §7 公告 | 1 |
| [research-reports.md](market-data-obtain/research-reports.md) | §8 研报 | 2 |
| [boards.md](market-data-obtain/boards.md) | §9 特殊池 & 板块（不含 agent 批量） | 11 |
| [agent-batch.md](market-data-obtain/agent-batch.md) | §9.1 Agent 批量端点 | 9 |
| [news.md](market-data-obtain/news.md) | §10 新闻 / 消息 | 6 |
| [meta.md](market-data-obtain/meta.md) | §11 其他 | 2 |

---

## 1. 适用场景

满足以下任一情况时启用本 skill：

- 用户请求获取行情、资金流、新闻、公告等任何市场数据
- agent 在执行 `market-principles` 工作流时需要采集数据（消息面 / 资金面 / 技术面 / 板块面）
- 用户询问"为什么涨/跌"等需要外部事件原因时
- 准备市场判断所需的 bootstrap 上下文（板块、龙头、资金、消息）

**不适用的请求**：

- 判断方法论、龙头识别、风险控制 → 走 `market-principles`
- 仓位管理、止损、加减仓 → 不在本 skill 覆盖范围
- 美股 / 港股 / 期货 / 加密货币 → 超出 A 股范围

---

## 2. 调用方式（agent 自决）

agent 可通过以下任意方式访问服务器能力（**先确认服务器在运行**——默认 `localhost:8888`）：

| 方式 | 适用 |
|---|---|
| HTTP 直接调用（如 `curl http://localhost:8888/api/v1/...`） | 大多数场景 |
| Python SDK（直接 import `DataFetcherManager`） | 嵌入 Python 工作流时 |
| `/explorer/` UI | 人工浏览 / 调试 |

**端点元数据单一真相**：`/control/api-manifest` 暴露全部端点的路径、capability、markets、fetcher 来源。agent 应优先从 manifest 反射端点列表，而非硬编码（与 `market-principles` 工作流协同）。

**响应 `source` 字段**：响应中可读取 `source`（fetcher 名 或 `'persistence'`），用于判断数据来自实时上游还是 SQLite 缓存层。Board 类端点还多带 `effective_source`，指示 `include_quote=False` 时实际服务的 fetcher（用于排查 fallback 链）。

---

## 3. Fallback 策略（服务器失败时）

> **本节是本 skill 的核心约束**——与 `market-principles` 的数据获取约束对齐。

### 3.1 何时触发 fallback

满足以下**任一**条件时，从服务器能力切换到 agent 自带的网络搜索 / 抓取工具：

1. **HTTP 5xx 错误**：服务器内部错误、上游 API 不可用（503 / 502 / 500）
2. **HTTP 422 / 404**：端点存在但请求的资源不存在（如未知股票代码、未知板块）
3. **HTTP 400 含指数重定向提示**（`message` 形如 `"...Use /indices/<code>/<kind> instead."`）：**不要 fallback** — 资源存在于指数端点。把 URL 从 `/stocks/<code>/...` 改写到 `/indices/<code>/<kind>` 后重试即可。400 但 *不带* 重定向提示意味着真 not-found（如 `"Stock code <code> was not found in the stock list."`），按 #2 fallback。
4. **返回空数据**：响应 `data: []`、`total: 0`，且与已知市场状态不符（如交易日 9:30 后龙虎榜仍为空）
5. **服务器未运行**：连接拒绝、超时
6. **特殊端点 28 天窗口限制**：`/news/morning-briefing` 和 `/news/market-recap` 仅支持最近 28 天；超出窗口时 fallback
7. **能力缺失**：服务器无对应端点（如某些仅在开盘期间才有的快讯）

### 3.2 Fallback 优先级

1. **网络搜索工具** — 关键词搜索（新闻、公告、政策解读、市场观点）
2. **网页抓取工具** — 指定 URL 抓取详情（如已知新闻链接）

具体工具名因平台而异（Claude Code 为 `WebSearch` / `WebFetch`），agent 调用自己平台对应的工具即可。

**禁止**直接编造数据或凭模型先验知识生成"原因"——必须搜索后**总结**再回复。

### 3.3 Fallback 后的回复规范

- 标注来源（如"根据财联社报道..."、"根据搜索结果..."）
- 区分**事实**（搜索结果中明确写出的）与**推断**（基于事实的二次推断）
- 对**互相矛盾**的多源信息，列出主要分歧而非强行收敛
- 若所有 fallback 也失败，明确告知用户"未能获取到相关信息"，不要编造

---

## 4. 行情类（Market Data）

| 端点 | Capability | 一句话用途 |
|---|---|---|
| `GET /api/v1/stocks/{code}/quote` | `STOCK_REALTIME_QUOTE` | 获取个股实时行情（OHLV + 估值 + 涨跌停价） |
| `GET /api/v1/stocks/{code}/kline` | `STOCK_KLINE` | 获取个股 K 线（d/w/m + 1-60 分钟；支持复权与技术指标） |
| `GET /api/v1/stocks/{code}/info` | `STOCK_INFO` | 获取个股公司画像（基础信息） |
| `GET /api/v1/stocks` | `STOCK_LIST` | 获取股票列表（csi / hk / us；分页） |
| `GET /api/v1/indices` | — | 获取指数列表（csi / hk / us） |
| `GET /api/v1/indices/{code}/quote` | `INDEX_REALTIME_QUOTE` | 获取指数实时行情 |
| `GET /api/v1/indices/{code}/kline` | `INDEX_KLINE` | 获取指数 K 线（不支持复权） |
| `GET /api/v1/calendar` | `TRADE_CALENDAR` | 获取 A 股交易日历 |

> ⚠️ 字段、单位、调用约束、示例：[detail/market-data.md](market-data-obtain/market-data.md)

> **命名说明**：个股/指数 K 线统一用 `period=daily|weekly|monthly|1m|5m|15m|30m|60m`；**板块 K 线 `/boards/{code}/history` 仍用旧名 `frequency=d|w|m|...`（内部 mgr 频率码 `1`/`5`/`15`/`30`/`60` 别映射）**——两块端点参数名不同是当前代码现实，不要混用。

---

## 5. 资金面（Capital Flow & Sentiment）

| 端点 | Capability | 一句话用途 |
|---|---|---|
| `GET /api/v1/stocks/{stock_code}/fund-flow` | `FUND_FLOW` | 获取个股分钟级资金流 |
| `GET /api/v1/stocks/{stock_code}/fund-flow/daily` | `FUND_FLOW` | 获取个股 120 日资金流 |
| `GET /api/v1/north-flow/realtime` | `NORTH_FLOW` | 获取北向资金实时累计净买入 |
| `GET /api/v1/stocks/{stock_code}/margin` | `MARGIN_TRADING` | 获取个股融资融券数据 |
| `GET /api/v1/stocks/{stock_code}/block-trade` | `BLOCK_TRADE` | 获取个股大宗交易 |
| `GET /api/v1/stocks/{stock_code}/holder-num` | `HOLDER_NUM` | 获取个股股东户数变化 |

> ⚠️ 字段、单位、调用约束、示例：[detail/capital-flow.md](market-data-obtain/capital-flow.md)

---

## 6. 基础数据（Fundamental）

| 端点 | Capability | 一句话用途 |
|---|---|---|
| `GET /api/v1/stocks/{stock_code}/dividend` | `DIVIDEND` | 获取个股分红送转记录 |

> ⚠️ 字段、单位、调用约束、示例：[detail/fundamentals.md](market-data-obtain/fundamentals.md)

---

## 7. 公告（Announcements）

| 端点 | Capability | 一句话用途 |
|---|---|---|
| `GET /api/v1/stocks/{stock_code}/announcements` | `ANNOUNCEMENT` | 获取个股公司公告（分页） |

> ⚠️ 字段、单位、调用约束、示例：[detail/announcements.md](market-data-obtain/announcements.md)

---

## 8. 研报（Research Reports）

| 端点 | Capability | 一句话用途 |
|---|---|---|
| `GET /api/v1/stocks/{stock_code}/reports` | `RESEARCH_REPORT` | 获取个股研报列表 |
| `GET /api/v1/stocks/{stock_code}/reports/{report_id}/pdf` | `RESEARCH_REPORT` | 下载研报 PDF（返回本地路径） |

> ⚠️ 字段、单位、调用约束、示例：[detail/research-reports.md](market-data-obtain/research-reports.md)

---

## 9. 特殊池 & 板块（Special Pools & Boards）

| 端点 | Capability | 一句话用途 |
|---|---|---|
| `GET /api/v1/boards` | `STOCK_BOARD` | 获取板块清单（概念 / 行业 / 指数 / 特殊） |
| `GET /api/v1/boards/{board_code}/stocks` | `STOCK_BOARD` | 获取板块成分股 |
| `GET /api/v1/boards/{board_code}/quote` | `STOCK_BOARD` | 获取板块实时行情 |
| `GET /api/v1/boards/{board_code}/news` | `BOARD_NEWS` | 获取板块新闻 |
| `GET /api/v1/boards/{board_code}/surges` | `BOARD_SURGES` | 获取板块炒作周期 |
| `GET /api/v1/stocks/{stock_code}/boards` | `STOCK_BOARD` | 获取个股所属板块（**THS 行额外带 7 个 live-enrichment 字段**：板块涨跌幅 / 上涨家数 / 下跌家数 / 涨停家数 / 跌停家数 / 概念解析 / 关联度） |
| `GET /api/v1/boards/{board_code}/history` | `STOCK_BOARD` | 获取板块 K 线 |
| `GET /api/v1/zt-pools` | `STOCK_ZT_POOL` | 获取涨跌停股池（zt / dt / zbgc） |
| `GET /api/v1/dragon-tiger` | `DRAGON_TIGER` | 获取全市场龙虎榜 |
| `GET /api/v1/stocks/{stock_code}/dragon-tiger` | `DRAGON_TIGER` | 获取个股龙虎榜 |
| `GET /api/v1/hot-topics` | `HOT_TOPICS` | 获取热点题材（带归因标签） |

> ⚠️ 字段、单位、调用约束、示例：[detail/boards.md](market-data-obtain/boards.md)  
> 推荐显式 `?source=ths`（覆盖全、稳定性最好）；不同 source 的板块定义**不保证互通**。

### 9.1 Agent 批量端点

把 N+1 集合运算 / 数值过滤 / 批量画像下沉到服务端——典型场景见 §12。

| 端点 | 一句话用途 |
|---|---|
| `POST /api/v1/agent/boards/stock-overlap` | 多板块成分股两两交集 + Jaccard（2-10 板块） |
| `POST /api/v1/agent/stocks/board-overlap` | 多股票所属板块两两交集 + Jaccard（2-10 股票） |
| `POST /api/v1/agent/boards/filter-stocks` | 板块成分股服务端数值过滤（换手 / 涨跌幅 / 成交额 / 市值） |
| `GET /api/v1/agent/indices/batch-profile` | 指数批量画像（1-5 指数；单 frequency） |
| `GET /api/v1/agent/market-context` | 每日市场全景快照（早报 + 复盘 + 快讯 + 涨跌停 + 龙虎榜） |
| `POST /api/v1/agent/stocks/batch-profile` | 股票批量画像（1-5 股票；quote + features + info + boards） |
| `POST /api/v1/agent/boards/batch-profile` | 板块批量画像（1-5 THS platecode；单 frequency） |
| `POST /api/v1/agent/correlation/matrix` | 跨资产 Pearson + Spearman 相关性矩阵（2-10 资产） |
| `GET /api/v1/agent/market-stats` | 全市场涨幅统计（个股 + 板块 + 桶形数据） |

> ⚠️ 字段、单位、调用约束、典型调用模式：[detail/agent-batch.md](market-data-obtain/agent-batch.md)

---

## 10. 新闻 / 消息（News）

> **本节是 fallback 策略的高频触发区域**——"为什么涨/跌"等外部事件型原因主要通过本节端点获取。

| 端点 | Capability | 一句话用途 |
|---|---|---|
| `GET /api/v1/news/search` | `NEWS_SEARCH` | 按关键词 / 股票代码搜索新闻 |
| `GET /api/v1/news/flash` | `NEWS_FLASH` | 获取全球财经快讯（7×24 实时） |
| `GET /api/v1/news/content` | — | 给定 URL 抓取新闻详情页正文（SSRF 防护） |
| `GET /api/v1/stocks/{stock_code}/news` | `STOCK_NEWS` | 获取个股相关新闻 |
| `GET /api/v1/news/morning-briefing` | `MORNING_BRIEFING` | 获取财联社早报（28 天窗口） |
| `GET /api/v1/news/market-recap` | `MARKET_RECAP` | 获取财联社焦点复盘（28 天窗口） |

> ⚠️ 字段、单位、调用约束、示例：[detail/news.md](market-data-obtain/news.md)

---

## 11. 其他（Meta）

| 端点 | Capability | 一句话用途 |
|---|---|---|
| `GET /healthz` | — | 服务器健康检查 + fetcher 断路器状态 |
| `GET /api/v1/indicators` | — | 获取技术指标目录（MA / MACD / BOLL / KDJ 等 14 种） |

> ⚠️ 字段、单位、调用约束、示例：[detail/meta.md](market-data-obtain/meta.md)

---

## 12. 典型场景的端点组合

> 本节只列"做 X 任务需要哪些端点"——**具体调用顺序、入参、失败 fallback 见每个端点的 detail 文件**。

### 场景 A：判断"为什么今天 X 股票 / 板块涨 / 跌"

| 步骤 | 端点 | 失败 fallback |
|---|---|---|
| 1. 拉快讯看当日大事 | `/news/flash` | 网络搜索工具 `"今日 A股 快讯"` |
| 2. 拉个股 / 板块新闻 | `/stocks/{code}/news` 或 `/news/search?q={code or keyword}` | 网络搜索工具 + 关键词 |
| 3. 拉板块清单确认关联 | `/boards` 或 `/stocks/{code}/boards` | — |
| 4. 拉资金流验证 | `/stocks/{code}/fund-flow/daily` | — |
| 5. 拉龙虎榜看机构动向 | `/stocks/{code}/dragon-tiger` | 网络搜索工具 `"{code} 龙虎榜"` |
| 6. 拉公告 / 研报 | `/stocks/{code}/announcements` / `/stocks/{code}/reports` | 网络搜索工具 |

### 场景 B：复盘当日市场

| 步骤 | 端点 |
|---|---|
| 1. 拉指数行情 | `/indices/{code}/quote` |
| 1.1 指数全景（一次 fan-out） | `/agent/indices/batch-profile` |
| 2. 拉涨跌停股池 | `/zt-pools?type=zt` / `/zt-pools?type=dt` |
| 3. 拉全市场龙虎榜 | `/dragon-tiger` |
| 4. 拉热点题材 | `/hot-topics` |
| 5. 拉早报 / 复盘 | `/news/morning-briefing` / `/news/market-recap` |
| 5.1 市场全景（一次拿全） | `/agent/market-context` |

### 场景 C：判断龙头股

| 步骤 | 端点 |
|---|---|
| 1. 圈定候选池 | `/zt-pools?type=zt` |
| 2. 看板块归属 | `/stocks/{code}/boards` |
| 3. 看板块行情 | `/boards/{board_code}/quote` 或 `/boards?type=concept&include_quote=true` |
| 4. 看板块 K 线 | `/boards/{board_code}/history` |
| 4.1 候选板块批量画像 | `/agent/boards/batch-profile` |
| 5. 看个股 K 线 + 量价 | `/stocks/{code}/kline` |
| 5.1 看候选股两两同板块 | `/agent/stocks/board-overlap` |
| 5.2 看候选板块两两同成分股 | `/agent/boards/stock-overlap` |
| 5.3 板块成分股数值过滤 | `/agent/boards/filter-stocks` |
| 5.4 候选股批量画像 | `/agent/stocks/batch-profile` |
| 5.5 候选股 / 板块两两相关性 | `/agent/correlation/matrix` |
| 5.6 全市场情绪 | `/agent/market-stats` |

---

## 13. 与 `market-principles` 的协作

- **入口**：agent 收到市场判断请求 → 触发 `market-principles`
- **数据采集**：`market-principles` 工作流第 5 步（通过配套 skill 收集消息、行情、板块、资金数据）→ 通过**本 skill** 选定服务器端点
- **判断**：采集完数据后，回到 `market-principles` **第 5 节核心原则 + 第 6 节龙头股判断方法**做判断
- **回写**：判断结果按 `market-principles` **第 9 节（每日 md 文件模板）** + **第 10 节（持久化文档模板）** 写入每日 md 和 `market_tracking.md`

详细工作流见 `market-principles` 第 9 节。
