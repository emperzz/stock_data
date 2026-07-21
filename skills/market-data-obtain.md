---
name: market-data-obtain
description: A 股市场数据获取 skill。配套 `market-principles` 使用——告诉 agent 在做市场判断时，**所有数据获取都先走本 skill 描述的服务器端点**；服务器失败或返回空时，fallback 到 agent 自带的网络搜索 / 抓取工具（具体工具名因 agent 平台而异）总结再回复。本 skill 是服务器能力的完整参考手册，按 capability 域（行情 / 资金面 / 基础数据 / 公告 / 研报 / 特殊池 / 新闻）组织。
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

> **核心约束（来自 market-principles）**：所有市场数据获取都应通过本 skill 描述的服务器能力；服务器失败或返回空时，**fallback 到 agent 自带的网络搜索 / 抓取工具**（具体工具名因 agent 平台而异，agent 应调用自己平台对应的搜索 / 抓取工具）总结再回复。详见第 3 节。

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

---

## 3. Fallback 策略（服务器失败时）

> **本节是本 skill 的核心约束**——与 `market-principles` 的数据获取约束对齐。

### 3.1 何时触发 fallback

满足以下**任一**条件时，从服务器能力切换到 agent 自带的网络搜索 / 抓取工具（具体工具名因 agent 平台而异）：

1. **HTTP 5xx 错误**：服务器内部错误、上游 API 不可用（503 / 502 / 500）
2. **HTTP 422 / 404**：端点存在但请求的资源不存在（如未知股票代码、未知板块）
3. **返回空数据**：响应 `data: []`、`total: 0`，且与已知市场状态不符（如交易日 9:30 后龙虎榜仍为空）
4. **服务器未运行**：连接拒绝、超时
5. **特殊端点 28 天窗口限制**：`/news/morning-briefing` 和 `/news/market-recap` 仅支持最近 28 天；超出窗口时 fallback
6. **能力缺失**：服务器无对应端点（如某些仅在开盘期间才有的快讯）

### 3.2 Fallback 优先级

按以下顺序选择 fallback 工具（**具体工具名因 agent 平台而异**——agent 应调用自己平台对应的搜索 / 抓取工具；本 skill 只规定"做什么"，不绑定"叫什么都工具"）：

| 优先级 | 工具类别 | 适用 |
|---|---|---|
| 1 | **网络搜索工具**（agent 自带） | 关键词搜索（新闻、公告、政策解读、市场观点） |
| 2 | **网页抓取工具**（agent 自带） | 指定 URL 抓取详情（如已知新闻链接） |

> **常见平台对应**（仅作参考）：
> - Claude Code：`WebSearch` / `WebFetch`
> - Codex / 其他 agent：调用各自平台对应的搜索 / 抓取工具
> - agent 应根据自己的实际能力调用，不要假设平台

**禁止**直接编造数据或凭模型先验知识生成"原因"——必须搜索后**总结**再回复。

### 3.3 Fallback 后的回复规范

- 标注来源（如"根据财联社报道..."、"根据搜索结果..."）
- 区分**事实**（搜索结果中明确写出的）与**推断**（基于事实的二次推断）
- 对**互相矛盾**的多源信息，列出主要分歧而非强行收敛
- 若所有 fallback 也失败，明确告知用户"未能获取到相关信息"，不要编造

---

## 4. 行情类（Market Data）

A 股 / 港股 / 美股 实时行情、历史 K 线、公司画像、股票列表、交易日历。

| 端点 | Capability | Markets | 主要 fetcher | 用途 |
|---|---|---|---|---|
| `GET /stocks/{code}/quote` | STOCK_REALTIME_QUOTE | csi / hk / us | Zzshare / Tencent | 个股实时行情（PE/PB/市值/换手率/涨跌停价） |
| `GET /stocks/{code}/kline` | STOCK_KLINE | csi / hk / us | Zzshare / Baostock / Yfinance | 个股 K 线（d/w/m + 1m/5m/15m/30m/60m；支持前复权/后复权/技术指标） |
| `GET /stocks/{code}/info` | STOCK_INFO | csi | Zhitu → Myquant | 公司画像 |
| `GET /stocks` | STOCK_LIST | csi / hk / us | Zzshare / Akshare / Yfinance | 股票列表（分页） |
| `GET /indices` | — | csi / hk / us | 本地映射 | 指数列表（代码 + 名称 + 市场） |
| `GET /indices/{code}/quote` | INDEX_REALTIME_QUOTE | csi / hk / us | Akshare / Yfinance / Zhitu | 指数实时行情 |
| `GET /indices/{code}/kline` | INDEX_KLINE | csi / hk / us | Baostock / Akshare / Yfinance / Zhitu | 指数 K 线（不支持复权） |
| `GET /calendar` | TRADE_CALENDAR | csi | Zzshare / Baostock | A 股交易日历 |

---

## 5. 资金面（Capital Flow & Sentiment）

资金流向、北向资金、融资融券、大宗交易、股东户数。

| 端点 | Capability | Markets | 主要 fetcher | 用途 |
|---|---|---|---|---|
| `GET /stocks/{stock_code}/fund-flow` | FUND_FLOW | csi | Zhitu | 个股分钟级资金流 |
| `GET /stocks/{stock_code}/fund-flow/daily` | FUND_FLOW | csi | Zhitu | 个股 120 日资金流 |
| `GET /north-flow/realtime` | NORTH_FLOW | csi | Ths | 北向资金（实时） |
| `GET /stocks/{stock_code}/margin` | MARGIN_TRADING | csi | EastMoney | 个股融资融券 |
| `GET /stocks/{stock_code}/block-trade` | BLOCK_TRADE | csi | EastMoney | 个股大宗交易 |
| `GET /stocks/{stock_code}/holder-num` | HOLDER_NUM | csi | EastMoney / Zhitu | 股东户数变化 |

---

## 6. 基础数据（Fundamental）

| 端点 | Capability | Markets | 主要 fetcher | 用途 |
|---|---|---|---|---|
| `GET /stocks/{stock_code}/dividend` | DIVIDEND | csi | EastMoney / Baostock / Zhitu | 分红送转 |

---

## 7. 公告（Announcements）

| 端点 | Capability | Markets | 主要 fetcher | 用途 |
|---|---|---|---|---|
| `GET /stocks/{stock_code}/announcements` | ANNOUNCEMENT | csi | EastMoney / Cninfo / Ths | 公司公告（分页） |

---

## 8. 研报（Research Reports）

| 端点 | Capability | Markets | 主要 fetcher | 用途 |
|---|---|---|---|---|
| `GET /stocks/{stock_code}/reports` | RESEARCH_REPORT | csi | EastMoney | 个股研报列表 |
| `GET /stocks/{stock_code}/reports/{report_id}/pdf` | RESEARCH_REPORT | csi | EastMoney | 研报 PDF 下载（返回本地路径） |

---

## 9. 特殊池 & 板块（Special Pools & Boards）

板块分类、涨跌停股池、龙虎榜、热点题材。

| 端点 | Capability | Markets | 主要 fetcher | 用途 |
|---|---|---|---|---|
| `GET /boards` | STOCK_BOARD | csi | Ths / EastMoney / Zhitu | 板块清单（概念/行业/指数/特殊，`?source=` 必填） |
| `GET /boards/{board_code}/stocks` | STOCK_BOARD | csi | Ths / EastMoney / Zhitu | 板块成分股（`?source=` 必填；ths 内部可能走 ZZSHARE 兜底） |
| `GET /boards/{board_code}/quote` | STOCK_BOARD | csi | Ths | 板块实时行情（ths 唯一实现） |
| `GET /boards/{board_code}/news` | BOARD_NEWS | csi | Ths | 板块新闻（ths 唯一实现，news.10jqka timeline） |
| `GET /boards/{board_code}/surges` | BOARD_SURGES | csi | Ths | 板块炒作周期（ths 唯一实现，F10 峰值周期） |
| `GET /stocks/{stock_code}/boards` | STOCK_BOARD | csi | Ths / EastMoney / Zhitu | 个股所属板块 |
| `GET /boards/{board_code}/history` | STOCK_BOARD | csi | Ths / EastMoney | 板块 K 线（d/w/m + 5m/15m/30m/60m） |
| `GET /zt-pools` | STOCK_ZT_POOL | csi | Zzshare | 涨跌停股池（type=zt/dt/zbgc） |
| `GET /dragon-tiger` | DRAGON_TIGER | csi | Zzshare / EastMoney | 全市场龙虎榜 |
| `GET /stocks/{stock_code}/dragon-tiger` | DRAGON_TIGER | csi | Zzshare / EastMoney | 个股龙虎榜 |
| `GET /hot-topics` | HOT_TOPICS | csi | Zzshare / Ths | 热点题材（带原因标签） |

> **Board 数据源选择建议**：board 类端点推荐显式传 `?source=ths`。
>
> - 不同 source 的板块定义不可互换（ths、eastmoney、zhitu 对同名板块的成分股集合存在差异），统一使用 ths 可避免跨 source 数据语义不一致
> - ths 的 board 类接口覆盖更全、稳定性更好

---

## 10. 新闻 / 消息（News）

> **本节是 fallback 策略的高频触发区域**——"为什么涨/跌"等外部事件型原因主要通过本节端点获取。

| 端点 | Capability | Markets | 主要 fetcher | 用途 |
|---|---|---|---|---|
| `GET /news/search` | NEWS_SEARCH | csi | EastMoney / Ths / Baidu | 新闻搜索（关键词/股票代码/主题） |
| `GET /news/flash` | NEWS_FLASH | csi | EastMoney / Ths | 全球财经快讯（7×24 实时） |
| `GET /news/content` | — | csi / hk / us | 本地解析器 | 新闻正文提取（给定 URL 抓详情页） |
| `GET /stocks/{stock_code}/news` | STOCK_NEWS | csi | EastMoney / Ths | 个股资讯 |
| `GET /news/morning-briefing` | MORNING_BRIEFING | csi | ClsFetcher | 财联社早报（按日，28 天窗口） |
| `GET /news/market-recap` | MARKET_RECAP | csi | ClsFetcher | 财联社焦点复盘（按日，28 天窗口） |

---

## 11. 其他（Meta）

| 端点 | Capability | Markets | 主要 fetcher | 用途 |
|---|---|---|---|---|
| `GET /healthz` | — | csi / hk / us | 本地 | 健康检查 + fetcher 断路器状态 |
| `GET /indicators` | — | csi / hk / us | 本地计算 | 技术指标目录（MA / MACD / BOLL / KDJ 等 14 种） |

---

## 12. 典型场景的端点组合

### 场景 A：判断"为什么今天 X 股票/板块涨/跌"

| 步骤 | 端点 | 失败 fallback |
|---|---|---|
| 1. 拉快讯看当日大事 | `GET /news/flash` | 网络搜索工具 `"今日 A股 快讯"` |
| 2. 拉个股/板块新闻 | `GET /stocks/{code}/news` 或 `GET /news/search?q={code or keyword}` | 网络搜索工具 + 关键词 |
| 3. 拉板块清单确认关联 | `GET /boards` 或 `GET /stocks/{code}/boards` | — |
| 4. 拉资金流验证 | `GET /stocks/{code}/fund-flow/daily` | — |
| 5. 拉龙虎榜看机构动向 | `GET /stocks/{code}/dragon-tiger` | 网络搜索工具 `"{code} 龙虎榜"` |
| 6. 拉公告/研报 | `GET /stocks/{code}/announcements` / `GET /stocks/{code}/reports` | 网络搜索工具 |

### 场景 B：复盘当日市场

| 步骤 | 端点 |
|---|---|
| 1. 拉指数行情 | `GET /indices/{code}/quote` |
| 2. 拉涨跌停股池 | `GET /zt-pools?type=zt`、`GET /zt-pools?type=dt` |
| 3. 拉全市场龙虎榜 | `GET /dragon-tiger` |
| 4. 拉热点题材 | `GET /hot-topics` |
| 5. 拉早报/复盘（如已发布） | `GET /news/morning-briefing`、`GET /news/market-recap` |

### 场景 C：判断龙头股

| 步骤 | 端点 |
|---|---|
| 1. 圈定候选池 | `GET /zt-pools?type=zt` |
| 2. 看板块归属 | `GET /stocks/{code}/boards` |
| 3. 看板块行情 | `GET /boards/{board_code}/quote` 或 `GET /boards?type=concept&include_quote=true` |
| 4. 看板块 K 线 | `GET /boards/{board_code}/history` |
| 5. 看个股 K 线 + 量价 | `GET /stocks/{code}/kline?period=daily&days=30` |

---

## 13. 与 `market-principles` 的协作

- **入口**：agent 收到市场判断请求 → 触发 `market-principles`
- **数据采集**：`market-principles` 工作流第 5 步（"收集当日消息、行情数据"）→ 通过**本 skill** 选定服务器端点
- **判断**：采集完数据后，回到 `market-principles` 第 4 节核心原则做判断
- **回写**：判断结果按 `market-principles` 第 7/8 节模板写入每日 md 和 `market_tracking.md`

详细工作流见 `market-principles` 第 9 节。