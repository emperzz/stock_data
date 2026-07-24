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

**响应 `source` 字段**：响应中可读取 `source`（fetcher 名 或 `'persistence'`），用于判断数据来自实时上游还是 SQLite 缓存层。Board 类端点还多带 `effective_source`，指示 `include_quote=False` 时实际服务的 fetcher（用于排查 fallback 链）。

---

## 3. Fallback 策略（服务器失败时）

> **本节是本 skill 的核心约束**——与 `market-principles` 的数据获取约束对齐。

### 3.1 何时触发 fallback

满足以下**任一**条件时，从服务器能力切换到 agent 自带的网络搜索 / 抓取工具（具体工具名因 agent 平台而异）：

1. **HTTP 5xx 错误**：服务器内部错误、上游 API 不可用（503 / 502 / 500）
2. **HTTP 422 / 404**：端点存在但请求的资源不存在（如未知股票代码、未知板块）
3. **HTTP 400 含指数重定向提示**（`message` 形如 `"...Use /indices/<code>/<kind> instead."`）：**不要 fallback** — 资源存在于指数端点。把 URL 从 `/stocks/<code>/...` 改写到 `/indices/<code>/<kind>` 后重试即可。400 但 *不带* 重定向提示意味着真 not-found（如 `"Stock code <code> was not found in the stock list."`），按 #2 fallback。
4. **返回空数据**：响应 `data: []`、`total: 0`，且与已知市场状态不符（如交易日 9:30 后龙虎榜仍为空）
5. **服务器未运行**：连接拒绝、超时
6. **特殊端点 28 天窗口限制**：`/news/morning-briefing` 和 `/news/market-recap` 仅支持最近 28 天；超出窗口时 fallback
7. **能力缺失**：服务器无对应端点（如某些仅在开盘期间才有的快讯）

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
| `GET /api/v1/stocks/{code}/quote` | STOCK_REALTIME_QUOTE | csi / hk / us | Zzshare / Tencent | 个股实时行情（PE/PB/市值/换手率/涨跌停价） |
| `GET /api/v1/stocks/{code}/kline` | STOCK_KLINE | csi / hk / us | Zzshare / Baostock / Yfinance | 个股 K 线（d/w/m + 1m/5m/15m/30m/60m；支持前复权/后复权/技术指标） |
| `GET /api/v1/stocks/{code}/info` | STOCK_INFO | csi | Zhitu → Myquant | 公司画像 |
| `GET /api/v1/stocks` | STOCK_LIST | csi / hk / us | Zzshare / Akshare | 股票列表（分页） |
| `GET /api/v1/indices` | — | csi / hk / us | 本地映射 | 指数列表（代码 + 名称 + 市场） |
| `GET /api/v1/indices/{code}/quote` | INDEX_REALTIME_QUOTE | csi / hk / us | Akshare / Yfinance / Zhitu | 指数实时行情 |
| `GET /api/v1/indices/{code}/kline` | INDEX_KLINE | csi / hk / us | Baostock / Akshare / Yfinance / Zhitu | 指数 K 线（不支持复权） |
| `GET /api/v1/calendar` | TRADE_CALENDAR | csi | Zzshare / Akshare / Myquant | A 股交易日历 |

---

## 5. 资金面（Capital Flow & Sentiment）

资金流向、北向资金、融资融券、大宗交易、股东户数。

| 端点 | Capability | Markets | 主要 fetcher | 用途 |
|---|---|---|---|---|
| `GET /api/v1/stocks/{stock_code}/fund-flow` | FUND_FLOW | csi | Zhitu | 个股分钟级资金流 |
| `GET /api/v1/stocks/{stock_code}/fund-flow/daily` | FUND_FLOW | csi | Zhitu | 个股 120 日资金流 |
| `GET /api/v1/north-flow/realtime` | NORTH_FLOW | csi | Ths | 北向资金（实时） |
| `GET /api/v1/stocks/{stock_code}/margin` | MARGIN_TRADING | csi | EastMoney | 个股融资融券 |
| `GET /api/v1/stocks/{stock_code}/block-trade` | BLOCK_TRADE | csi | EastMoney | 个股大宗交易 |
| `GET /api/v1/stocks/{stock_code}/holder-num` | HOLDER_NUM | csi | EastMoney / Zhitu | 股东户数变化 |

---

## 6. 基础数据（Fundamental）

| 端点 | Capability | Markets | 主要 fetcher | 用途 |
|---|---|---|---|---|
| `GET /api/v1/stocks/{stock_code}/dividend` | DIVIDEND | csi | EastMoney / Baostock / Zhitu | 分红送转 |

---

## 7. 公告（Announcements）

| 端点 | Capability | Markets | 主要 fetcher | 用途 |
|---|---|---|---|---|
| `GET /api/v1/stocks/{stock_code}/announcements` | ANNOUNCEMENT | csi | EastMoney / Cninfo / Ths | 公司公告（分页） |

---

## 8. 研报（Research Reports）

| 端点 | Capability | Markets | 主要 fetcher | 用途 |
|---|---|---|---|---|
| `GET /api/v1/stocks/{stock_code}/reports` | RESEARCH_REPORT | csi | EastMoney | 个股研报列表 |
| `GET /api/v1/stocks/{stock_code}/reports/{report_id}/pdf` | RESEARCH_REPORT | csi | EastMoney | 研报 PDF 下载（返回本地路径） |

---

## 9. 特殊池 & 板块（Special Pools & Boards）

板块分类、涨跌停股池、龙虎榜、热点题材。

| 端点 | Capability | Markets | 主要 fetcher | 用途 |
|---|---|---|---|---|
| `GET /api/v1/boards` | STOCK_BOARD | csi | Ths / EastMoney / Zhitu | 板块清单（概念/行业/指数/特殊，`?source=` 必填） |
| `GET /api/v1/boards/{board_code}/stocks` | STOCK_BOARD | csi | Ths / EastMoney / Zhitu | 板块成分股（`?source=` 必填；ths 内部可能走 ZZSHARE 兜底） |
| `GET /api/v1/boards/{board_code}/quote` | STOCK_BOARD | csi | Ths | 板块实时行情（ths 唯一实现） |
| `GET /api/v1/boards/{board_code}/news` | BOARD_NEWS | csi | Ths | 板块新闻（ths 唯一实现，news.10jqka timeline） |
| `GET /api/v1/boards/{board_code}/surges` | BOARD_SURGES | csi | Ths | 板块炒作周期（ths 唯一实现，F10 峰值周期） |
| `GET /api/v1/stocks/{stock_code}/boards` | STOCK_BOARD | csi | Ths / EastMoney / Zhitu | 个股所属板块 |
| `GET /api/v1/boards/{board_code}/history` | STOCK_BOARD | csi | Ths / EastMoney | 板块 K 线（d/w/m + 5m/15m/30m/60m；ths 额外支持 1m） |
| `GET /api/v1/zt-pools` | STOCK_ZT_POOL | csi | Zzshare | 涨跌停股池（type=zt/dt/zbgc） |
| `GET /api/v1/dragon-tiger` | DRAGON_TIGER | csi | Zzshare / EastMoney | 全市场龙虎榜 |
| `GET /api/v1/stocks/{stock_code}/dragon-tiger` | DRAGON_TIGER | csi | Zzshare / EastMoney | 个股龙虎榜 |
| `GET /api/v1/hot-topics` | HOT_TOPICS | csi | Zzshare / Ths | 热点题材（带原因标签） |

> **Board 数据源选择建议**：board 类端点推荐显式传 `?source=ths`。
>
> - 不同 source 的板块定义不可互换（ths、eastmoney、zhitu 对同名板块的成分股集合存在差异），统一使用 ths 可避免跨 source 数据语义不一致
> - ths 的 board 类接口覆盖更全、稳定性更好
> - `?source=zzshare` 已不再作为独立选项——会归一到 ths；需要区分 `include_quote=True/False` 时的实际服务 fetcher 时读响应里的 `effective_source`

---

## 10. 新闻 / 消息（News）

> **本节是 fallback 策略的高频触发区域**——"为什么涨/跌"等外部事件型原因主要通过本节端点获取。

| 端点 | Capability | Markets | 主要 fetcher | 用途 |
|---|---|---|---|---|
| `GET /api/v1/news/search` | NEWS_SEARCH | csi | EastMoney / Ths / Baidu | 新闻搜索（关键词/股票代码/主题） |
| `GET /api/v1/news/flash` | NEWS_FLASH | csi | EastMoney / Ths | 全球财经快讯（7×24 实时） |
| `GET /api/v1/news/content` | — | csi / hk / us | 本地解析器 | 新闻正文提取（给定 URL 抓详情页） |
| `GET /api/v1/stocks/{stock_code}/news` | STOCK_NEWS | csi | EastMoney / Ths | 个股资讯 |
| `GET /api/v1/news/morning-briefing` | MORNING_BRIEFING | csi | ClsFetcher | 财联社早报（按日，28 天窗口） |
| `GET /api/v1/news/market-recap` | MARKET_RECAP | csi | ClsFetcher | 财联社焦点复盘（按日，28 天窗口） |

---

## 11. 其他（Meta）

| 端点 | Capability | Markets | 主要 fetcher | 用途 |
|---|---|---|---|---|
| `GET /healthz` | — | csi / hk / us | 本地 | 健康检查 + fetcher 断路器状态 |
| `GET /api/v1/indicators` | — | csi / hk / us | 本地计算 | 技术指标目录（MA / MACD / BOLL / KDJ 等 14 种） |

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

## 13. 各端点返回字段说明

> **本节是 agent 解读响应的字段手册**——按 capability 域组织（行情/资金面/基础数据/公告/研报/特殊池/板块/新闻/其他）。每条端点列出**核心字段含义**与**易踩坑点**。完整 JSON 示例见 `api-reference.md`；运行时字段定义唯一真相源是 `stock_data/api/schemas.py` 的 Pydantic model。

### 13.1 行情类

#### `GET /stocks/{code}/quote` — 个股实时行情

| 字段 | 含义 | 使用建议 |
|---|---|---|
| `current_price` | 当前价(元) | 行情主字段 |
| `change` | 涨跌额(元) | `current_price - prev_close` |
| `change_percent` | 涨跌幅(%) | 直接显示；正值=涨、负值=跌 |
| `open` / `high` / `low` / `prev_close` | 今开/最高/最低/昨收(元) | 算振幅 `(high-low)/prev_close*100` |
| `volume` | 成交量(**股**) | 注意单位是**股**，1 手 = 100 股 |
| `amount` | 成交额(元) | — |
| `pe_ttm` | 滚动市盈率(TTM) | Tencent财经增强 |
| `pe_static` | 静态市盈率 | **本服务固定返回 null**，需要时直接用 `pe_ttm` |
| `pb` | 市净率 | Tencent 增强 |
| `mcap_yi` | **总市值（亿元）** | 1 亿 = 1e8 元；用于"大票/小票"判断 |
| `float_mcap_yi` | 流通市值（亿元） | — |
| `turnover_pct` | 换手率(%) | `volume / float_share` |
| `amplitude_pct` | 振幅(%) | `(high-low)/prev_close*100` |
| `vol_ratio` | 量比 | 现量/过去 5 日同时段均量 |
| `limit_up` / `limit_down` | 涨停价/跌停价 | **本服务固定返回 null**，按昨收 ±10% 自行计算 |
| `source` | 数据来源 fetcher 名（zzshare/akshare/...） | 用于判断数据新鲜度 |

#### `GET /stocks/{code}/kline` — K 线

顶层 `{code, stock_name, period, data[], source}`，核心在 `data[]` 每根 K 线：

| 字段 | 含义 | 备注 |
|---|---|---|
| `date` | YYYY-MM-DD (d/w/m) 或 `YYYY-MM-DD HH:MM:SS` (分钟级) | 格式随 frequency 变化 |
| `frequency` | d/w/m/1m/5m/15m/30m/60m | 每根 K 线**自带**频率标签，校验用 |
| `open` / `high` / `low` / `close` | OHLC（元） | — |
| `volume` | 成交量(**股**) | 单位固定股，1 手 = 100 股 |
| `volume_unit` | 固定 `"share"` | 不变式：始终是股 |
| `amount` | 成交额(元) | 缺数据时为 `null`（不是 0） |
| `change_percent` | 涨跌幅(%) | 缺数据时为 `null` |
| `indicators` | dict, e.g. `{ma5: 12.34, macd_dif: 0.23}` | **仅在传 `?indicators=` 时出现**；未传则整个字段从 JSON 中**省略**（非 null） |

> 复权: `?adjust=qfq` 前复权 / `?adjust=hfq` 后复权 / 不传 不复权。**注意 1m 拒绝 adjust**（Akshare 1m 端点不支持复权），传了会报错。

#### `GET /stocks/{code}/info` — 公司画像

| 字段 | 含义 |
|---|---|
| `code` / `name` | 6 位代码 / 股票名 |
| `exchange` | `SH` / `SZ` / `BJ`，**未匹配时为 `null`**（注意不是空字符串） |
| `industry` | 行业 |
| `listing_date` | 上市日 YYYY-MM-DD |
| `total_share` | 总股本(**股**) |
| `float_share` | 流通股(**股**) |
| `reg_capital` | 注册资本(元) |

> 字段**不会**包含股价/市值/PE；要看行情用 `/quote`，要看财务用其他基本面端点（当前项目未实现）。

#### `GET /stocks` — 股票列表

每条 `{code, name, market, exchange}`：
- `market` 固定 `csi` / `hk` / `us`（**A 股是 `csi`，不是 `cn`**）
- `exchange` 可能为 `null`

#### `GET /indices` / `GET /indices/{code}/quote` / `GET /indices/{code}/kline`

- `/indices` 列表：`{code, name, market}`，三市场（csi/hk/us）
- `/indices/{code}/quote`：**字段含义同 `/stocks/{code}/quote`**，但**没有** PE/PB/市值/换手率/振幅/涨跌停价等腾讯增强字段；`current_price` 单位是**指数点位**（不是元）
- `/indices/{code}/kline`：结构同 `/stocks/{code}/kline`（每根 K 线 shape 完全一致），但**指数无复权**，传 `?adjust=qfq|hfq` 会被 422 拒绝

#### `GET /calendar` — A 股交易日历

| 字段 | 含义 |
|---|---|
| `trade_dates[]` | 所有交易日期（升序） |
| `latest_date` | 最新一日 |
| `total` | 总天数 |

---

### 13.2 资金面

#### `GET /stocks/{code}/fund-flow` (分钟级) / `/fund-flow/daily` (120 日)

顶层 `{code, name, type, records[], source}`，`type` 区分 `"minute"` / `"daily"`。

`records[]` 每条：

| 字段 | 含义 | 备注 |
|---|---|---|
| `time` (minute) / `date` (daily) | HH:mm / YYYY-MM-DD | — |
| `main_net` | 主力净流入(元) | **正=流入、负=流出** |
| `super_net` | 超大单净流入(元) | — |
| `large_net` | 大单净流入(元) | — |
| `mid_net` | 中单净流入(元) | — |
| `small_net` | 小单净流入(元) | — |

> 通常阈值: `|main_net| > 1e7`(1千万) 才视为显著。**别用 absolute amount 与换手率/涨跌幅混着判断**。

#### `GET /north-flow/realtime` — 北向资金

`records[]` 每条 `{time (HH:mm), hgt_yi (沪股通累计净买入/亿元), sgt_yi (深股通累计净买入/亿元)}`。
沪+深相加为北向资金合计。

#### `GET /stocks/{code}/margin` — 融资融券

`records[]` 每条：

| 字段 | 含义 |
|---|---|
| `date` | YYYY-MM-DD |
| `rzye` | 融资余额(元) |
| `rzmre` | 融资买入额(元) |
| `rzche` | 融资偿还额(元) |
| `rqye` | 融券余额(元) |
| `rqmcl` | 融券卖出量(股) |
| `rqchl` | 融券偿还量(股) |
| `rzrqye` | 融资融券余额合计(元) |

> 杠杆情绪观察: `rzye` 趋势 + `rzmre - rzche` 增量；融券量小，多数场景只看融资侧。

#### `GET /stocks/{code}/block-trade` — 大宗交易

`records[]` 每条 `{date, price, close, premium_pct, vol, amount, buyer, seller}`：
- `premium_pct` 溢价率(%)：正值=溢价成交、负值=折价成交
- `vol` 成交量(**股**)
- `buyer` / `seller` 营业部名（如"机构专用"、"中信证券"）

#### `GET /stocks/{code}/holder-num` — 股东户数

`records[]` 每条 `{date, holder_num, change_num, change_ratio, avg_shares}`：
- `change_num` 正=户数增加、负=减少；**减少通常视为筹码集中**（看多信号之一）
- `change_ratio` 环比(%)；`avg_shares` 户均持股(**股**)

---

### 13.3 基础数据

#### `GET /stocks/{code}/dividend` — 分红送转

`records[]` 每条 `{date, bonus_rmb, transfer_ratio, bonus_ratio, plan}`：
- `date` 除权除息日
- `bonus_rmb` **每股派息（税前，元）**
- `transfer_ratio` 每 10 股转增股数（如 5 表示 10 转 5）
- `bonus_ratio` 每 10 股送股数
- `plan` 进度（如"实施完成"、"股东大会通过"）

---

### 13.4 公告 / 研报

#### `GET /stocks/{code}/announcements` — 公告

`announcements[]` 每条 `{title, type, date, url}`：
- `type` 类型（如"年报"、"季报"、"重大事项"）
- `url` 详情页 URL（cninfo / eastmoney）

#### `GET /stocks/{code}/reports` — 研报列表

`reports[]` 每条 `{title, publish_date, org, info_code, rating, predict_eps_this, predict_eps_next, predict_eps_next2}`：
- `org` 机构名（中信证券等）
- `info_code` 报告 ID，**用于 `/reports/{report_id}/pdf` 下载**
- `rating` 评级（"买入" / "增持" / "中性" / "减持" / "卖出"）
- `predict_eps_this/next/next2` 当年/次年/后年 EPS 预测（元）

#### `GET /stocks/{code}/reports/{report_id}/pdf` — 研报 PDF

返回 `{report_id, download_path (本地路径), url (原始 URL)}`。

---

### 13.5 特殊池 & 板块

#### 板块类型总览（`concept` / `industry` / `index` / `special`）

系统定义 4 种板块类型，以 `source=ths` 的分类为默认参考：

| 类型 | 含义 | `ths` 支持 | `ths` subtype | 典型代码前缀 | 其他 source 补充 |
|---|---|---|---|---|---|
| `concept` | 概念板块（题材/热点） | ✅ | `同花顺概念` / `同花顺题材` | `885xxx` | eastmoney（无 subtype 拆分）/ zhitu（`热门概念` / `概念板块` / `地域板块`） |
| `industry` | 行业板块 | ✅ | `同花顺行业` | `881xxx` | eastmoney / zhitu（`申万行业` / `申万二级` / `证监会行业`） |
| `index` | 大盘/分类指数 | ❌ 不暴露 | — | — | **仅 zhitu**（`分类` / `指数成分` / `大盘指数`） |
| `special` | 特殊池（风险警示/次新/沪深港通） | ❌ 不暴露 | — | — | **仅 zhitu**（`风险警示` / `次新股` / `沪港通` / `深港通`） |

**关键约束**：

- **`source=ths` 只覆盖 `concept` + `industry` 两类**。要查 `index` / `special` 必须 `?source=zhitu`。
- **不传 `?type=` = 默认查该 source 支持的所有类型**（route 内部 fan-out：ths 走 concept+industry；zhitu 走全 4 类；eastmoney 走 concept+industry）。
- **跨 source 含义不同**：同名"互联网服务"概念，ths 与 eastmoney 的成分股集合**不保证一致**（不同源用的板块分类系统不同），默认用 `source=ths` 可避免跨源语义混淆。
- 错误示例：`?source=ths&type=index` → 400（ths 不支持 index）；`?source=ths&type=special` → 400（ths 不支持 special）；`?source=eastmoney&type=index` → 400（同理）。

#### `GET /boards` — 板块清单

`data[]` 每条 BoardInfo 字段（**`include_quote=true` 才会有报价字段**）：

| 字段 | 含义 | include_quote 必填? |
|---|---|---|
| `code` | 板块代码（ths=`885xxx`/`881xxx`；eastmoney=`BKxxxx`；zhitu=`sw_xxx`） | 否 |
| `name` | 板块名 | 否 |
| `type` | concept / industry / index / special | 否（始终填充） |
| `price` / `change_pct` / `change_amount` | 板块指数点位 / 涨跌幅 / 涨跌额 | **是** |
| `volume` / `amount` / `turnover_rate` / `total_mv` | 板块量价数据 | **是** |
| `up_count` / `down_count` | 板块内上涨/下跌家数 | **是** |
| `leading_stock` / `leading_stock_price` / `leading_stock_pct` | 龙头股名/价/涨幅 | **是** |
| `net_inflow` | 资金净流入(亿元) | **行业板块 only**，其他类型固定 null |

> 排序: `?sort_by=change_pct|volume|amount|price` + `?sort_order=asc|desc`，**必须**配合 `?include_quote=true`（否则 400）。

#### `GET /boards/{code}/stocks` — 板块成分股

- `board` 板块简表（字段同 `/boards`）
- `stocks[]` 每条 BoardStockInfo：核心字段 `{code, name, price, change_pct, change_amount, volume, amount, turnover_rate}`；THS 上游额外暴露 6 字段 `{change_speed (涨速%), volume_ratio (量比), amplitude (振幅%), free_float_shares (流通股/股), float_market_cap (流通市值/元), pe_ratio (市盈率)}`
- `query_source` / `data_source` / `effective_source` 数据源追踪；判 fallback 用 `query_source != effective_source`（详见 `api-reference.md` / `CLAUDE.md` 缓存部分）
- `quote_truncated` / `quote_top_n` / `quote_total_in_board` 仅在 `?include_quote=true` 配合 `?sort_by`/`?top_n` 时填充；`truncated=true` 表示超过 `top_n` 截断后用 ZZSHARE 补全无报价的成员

#### `GET /boards/{code}/quote` — 板块实时行情

| 字段 | 含义 | 备注 |
|---|---|---|
| `price` / `change_pct` / `change_amount` | 板块指数点位/涨跌幅/额 | THS 唯一实现 |
| `open` / `high` / `low` / `prev_close` | 今开/高/低/昨收(指数点位) | — |
| `volume` | **成交量(万手，整数)** | 上游返回浮点字符串，fetcher `safe_int` 截断；精度损失约 0.005% |
| `amount` | 成交额(亿元) | — |
| `net_inflow` | 资金净流入(亿元) | — |
| `up_count` / `down_count` | 涨跌家数 | — |
| `rank` | 涨幅排名，形如 `"229/389"` | string |

#### `GET /boards/{code}/news` — 板块新闻

`data[]` 每条 `{title, url, publish_date, publish_time, summary, source_domain}`：
- `summary` 摘要（THS 上游可能为空字符串 `""`）
- `source_domain` 默认 `news.10jqka.com.cn`
- 分页: `?limit=20`（1-50），游标分页无 14 条硬上限

#### `GET /boards/{code}/surges` — 板块炒作周期

`data[]` 每条 `{date, board_change_pct, sh_change_pct, limit_up_count, limit_up_stocks[], up_count, down_count}`：
- `board_change_pct` 板块涨幅(%)；`sh_change_pct` 上证同周期涨幅(%)（**用上证做基准对比**）
- `limit_up_count` 涨停家数；`limit_up_stocks[]` 涨停股代码列表
- `up_count` / `down_count` **F10 未暴露，固定 null**

#### `GET /stocks/{code}/boards` — 个股所属板块

`data[]` 每条 `{code, name, type, subtype, source}`：
- `name` 板块全名（形如 `"A股-申万行业-银行"`）
- `subtype` 子类型（ths=同花顺概念/同花顺行业；zhitu=申万行业/热门概念 等）
- `source` 来自哪个 fetcher（ths / eastmoney / zhitu）
- `cold_sources[]` 没拉到的 source 列表（cold cache 提示，可选重试）

#### `GET /boards/{code}/history` — 板块 K 线

顶层 `{board_code, board_name, period, data[], source}`，`data[]` 每根 K 线 shape 与 `/stocks/{code}/kline` 完全一致（OHLCV + frequency + amount + change_percent）。`period` 取值 `d | w | m | 1m | 5m | 15m | 30m | 60m`；ths 支持全 8 频率，eastmoney 支持 7 频率（**无 1m**，传 1m 会在 fetcher 内部 5xx 报错）。

#### `GET /zt-pools` — 涨跌停股池

`stocks[]` 每条 ZTPoolStock：

| 字段 | 含义 |
|---|---|
| `code` / `name` / `price` / `change_pct` / `amount` | 股票基础信息 |
| `circ_mv` | 流通市值(元) |
| `total_mv` | 总市值(元) |
| `turnover_rate` | 换手率(%) |
| `lb_count` | **连板数**（N 连板） |
| `first_seal_time` / `last_seal_time` | 首次/最后封板时间(HH:mm) |
| `seal_amount` | 封单金额(元) |
| `seal_count` | 封单次数（涨停后开板又封回去的次数） |
| `zt_count` | 涨停次数 |

> zt vs dt vs zbgc: zt=涨停；dt=跌停；zbgc=炸板（**曾涨停但未封住**）。`date` 默认取今日或最近一个交易日。

#### `GET /dragon-tiger` — 全市场龙虎榜

顶层 `{date, total, stocks[]}`，`stocks[]` 每条 DailyDragonTigerStock：

| 字段 | 含义 | 备注 |
|---|---|---|
| `code` / `name` | 股票代码/名 | — |
| `reason` | **上榜原因**（"日涨幅偏离值达7%"、"换手率20%"等） | 用于筛选/分组 |
| `change_pct` | 涨跌幅(%) | — |
| `turnover_pct` | 换手率(%) | — |
| `close` | 收盘价 | Zzshare 上游**不返回**，固定 null；EastMoney 有值 |
| `net_buy_wan` | 净买入(万元) | 主力资金净买入 |
| `buy_wan` / `sell_wan` | 买入/卖出(万元) | Zzshare 上游不拆分，固定 null；EastMoney 有值 |

过滤: `?trade_date=YYYY-MM-DD` 必传；`?min_net_buy=5000`（万元）筛显著净买入。

#### `GET /stocks/{code}/dragon-tiger` — 个股龙虎榜

顶层 `{code, name, records[], seats{buy[], sell[]}, institution, source}`：
- `records[]` 字段同全市场 `stocks[]`（个股当日上榜记录，通常 1 条）
- `seats.buy[]` / `seats.sell[]` 营业部席位 `{name, buy_wan, sell_wan, net_wan}`
- `institution` 机构席位合计 `{buy_amt, sell_amt, net_amt}`（万元）

> 单日 `?trade_date=` 不传时默认查最新一个交易日。`records` 最多包含一条对应 `trade_date` 的上榜记录。

#### `GET /hot-topics` — 热点题材

`topics[]` 每条 `{code, name, reason, change_pct, turnover_rate, volume, amount, dde_net}`：
- `reason` **题材归因**（如 `"人形机器人+减速器+特斯拉"`）——分类/筛选的关键字段
- `dde_net` 大单净量（DDX 风格指标）

---

### 13.6 新闻

#### `GET /news/search` — 新闻搜索

`data[]` 每条 `{title, url, publish_date, source_domain, summary}`：
- `publish_date` YYYY-MM-DD
- `summary` 可能为空（部分上游不提供）
- `source_domain` 限定 `finance.eastmoney.com` / `www.cls.cn` / `news.10jqka.com.cn`（canonical 子域白名单）

#### `GET /news/flash` — 全球财经快讯

`data[]` 每条 `{title, publish_time, url, code, source_domain}`：
- **`code` 是文章 ID，不是股票代码**（⚠️ 踩坑高发区）
- `publish_time` 形如 `"2026-05-20 09:31:00"`

#### `GET /news/content` — 新闻正文

| 字段 | 含义 |
|---|---|
| `url` | 入参 URL（echo） |
| `title` / `body` | 标题 / 提取的正文纯文本（保留段落换行） |
| `publish_date` / `author` / `source_domain` | 元信息 |
| `extractor` | 解析器名（`"default"` 等） |
| `byte_size` | body 字节数 |
| `content_status` | `ok` / `failed` |
| `reason` | 失败原因（仅 failed 时非空） |
| `canonical_url` / `http_status` | 抓取诊断（URL 跳转后的最终地址 / HTTP 状态码） |

> 入口做了 SSRF 防护：`127.0.0.1` / `10.0.0.0/8` 等内网 URL 会被 400 拒绝。

#### `GET /stocks/{code}/news` — 个股资讯

`data[]` 每条 `{title, url, publish_time, source_domain}`，结构比 `/news/search` 简（无 `summary`）。

#### `GET /news/morning-briefing` / `/news/market-recap` — 财联社

顶层 `{subject, subject_id, date, article{}, source}`：
- `subject` `"morning_briefing"` / `"market_recap"`
- `subject_id` 固定 `1151` / `1135`（CLS 上游枚举，probed 2026-07-14；如 CLS 改枚举，service 会通过 `subject_id mismatch` 告警）
- `article`：
  - `article_id` 文章 ID
  - `title` / `brief` 标题 / 简介
  - `author` / `date` / `ctime`（epoch 秒）
  - `read_num` / `comments_num` / `share_num` 阅读/评论/分享数
  - `images[]` 图片 URL 列表
  - `body_text` **完整正文（纯文本，BS4 提取 `get_text("\n", strip=True)`，3+ 空行折叠为 2）**——这是 agent 拿全文做总结的主字段

> **28 天窗口**（`?date=` 校验）：超出窗口 → 400；窗口内但 CLS 当日未发 → 404。

---

### 13.7 其他（Meta）

#### `GET /healthz` — 健康检查

`status`: `ok` / `degraded` / `unhealthy`；`?details=true` 时 `sources[]` 列出每个 fetcher：

| 字段 | 含义 |
|---|---|
| `name` | fetcher 名（tushare/akshare/...） |
| `state` | `closed` / `open` / `half_open`（断路器状态） |
| `available` | 当前是否可用（无 token / 配置缺失 = false） |
| `last_success_time` / `last_failure_time` | epoch 秒；缺数据时为 null |
| `failure_count` | 累计失败次数 |
| `unavailable_reason` | 不可用原因（仅 `available=false` 时填充） |

#### `GET /indicators` — 技术指标目录

`indicators[]` 每条：
- `key` 标识符（`ma` / `macd` / `kdj` / `boll` / ...）
- `input_shape` `"closes"` 或 `"ohlcv"`
- `default_options` 字典（如 `ma: {periods: [5,10,20,30,60], type: "sma"}`）
- `output_columns[]` 输出列名（如 `["ma5","ma10",...]`）
- `default_lookback` 预热所需最少 K 线根数（路由层会自动 `max(days, lookback)` 拉更多再截断）

> agent 用法：先 `GET /indicators` 看可用指标，再在 K 线请求里 `?indicators=ma,macd,kdj` 一次取多个。

---

## 14. 与 `market-principles` 的协作

- **入口**：agent 收到市场判断请求 → 触发 `market-principles`
- **数据采集**：`market-principles` 工作流第 5 步（"收集当日消息、行情数据"）→ 通过**本 skill** 选定服务器端点
- **判断**：采集完数据后，回到 `market-principles` 第 4 节核心原则做判断
- **回写**：判断结果按 `market-principles` 第 7/8 节模板写入每日 md 和 `market_tracking.md`

详细工作流见 `market-principles` 第 9 节。