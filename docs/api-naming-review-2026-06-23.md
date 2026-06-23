# API 命名评审 (2026-06-23)

## 背景

对 `stock_data` 服务当前对外 API 的全量命名做了一次系统性梳理,发现命名空间不一致和资源层级混乱问题。本文档逐端点列出当前命名、建议命名和原因,作为后续迁移的参考。

---

## 1. 全局命名空间 (现状)

服务对外暴露 **4 套独立前缀**:

| 前缀 | 路由器 | 端点数 | 角色 | 是否对外 |
|---|---|---|---|---|
| `/api/v1/*` | `router` (`api/routes.py`) | 28 | 业务数据 API | ✅ |
| `/news/*` | `news_router` (`api/routes.py`) | 3 | 新闻/快讯 | ✅ |
| `/control/*` | `control_router` (`explorer/routes.py`) | 4 | 管理/控制平面 | ❌ (127.0.0.1-only) |
| `/explorer/*` | `StaticFiles` mount (`explorer/__init__.py`) | — | HTML UI | ❌ |

**核心问题**:
1. `/api/v1/*` 和 `/news/*` 都是**对外**业务端点,但只有前者带版本,后者完全裸奔——一旦新闻响应模型发生 breaking change,将直接破坏所有调用方。
2. `/api/v1/*` 内部已经有层级不一致(详见下文 §2),不是单纯"加新闻到 v1"就完事。

---

## 2. `/api/v1/*` 业务端点 (28 个)

### 2.1 一致性良好 (16 个) — 建议保留

| # | 当前路径 | 端点摘要 | 建议路径 | 原因 |
|---|---|---|---|---|
| 1 | `/api/v1/stocks/{code}/info` | 公司画像 | **保持不变** | 路径层级清晰,资源归属明确 |
| 2 | `/api/v1/stocks/{stock_code}/quote` | 实时行情 | **保持不变** | 同上 |
| 3 | `/api/v1/stocks/{stock_code}/history` | 历史 K 线 (含可选指标) | **保持不变** | 同上 |
| 4 | `/api/v1/stocks/{stock_code}/intraday` | 分钟 K 线 | **保持不变** | 同上 |
| 5 | `/api/v1/stocks` | 股票列表 (分页) | **保持不变** | 集合资源用复数,符合 REST |
| 6 | `/api/v1/indices` | 指数列表 | **保持不变** | 集合资源 |
| 7 | `/api/v1/indices/{index_code}/quote` | 指数实时行情 | **保持不变** | 同股票 |
| 8 | `/api/v1/indices/{index_code}/history` | 指数历史 K 线 | **保持不变** | 同上 |
| 9 | `/api/v1/indices/{index_code}/intraday` | 指数分钟 K 线 | **保持不变** | 同上 |
| 10 | `/api/v1/boards` | 概念 / 行业板块列表 | **保持不变** | 集合资源 |
| 11 | `/api/v1/boards/{board_code}/stocks` | 板块成分股 | **保持不变** | 子资源路径合理 |
| 12 | `/api/v1/stocks/{stock_code}/dragon-tiger` | 龙虎榜 (个股) | **保持不变** | 单只股票的龙虎榜 |
| 13 | `/api/v1/stocks/{stock_code}/margin` | 融资融券 | **保持不变** | 资源归属清晰 |
| 14 | `/api/v1/stocks/{stock_code}/block-trade` | 大宗交易 | **保持不变** | 同上 |
| 15 | `/api/v1/stocks/{stock_code}/holder-num` | 股东户数变化 | **保持不变** | 同上 |
| 16 | `/api/v1/stocks/{stock_code}/dividend` | 分红送转 | **保持不变** | 同上 |

### 2.2 资源层级合理但需小调 (2 个)

| # | 当前路径 | 端点摘要 | 建议路径 | 原因 |
|---|---|---|---|---|
| 17 | `/api/v1/stocks/{stock_code}/fund-flow` | 资金流 (分钟级) | **保持不变** | 资源归属清晰 |
| 18 | `/api/v1/stocks/{stock_code}/fund-flow/daily` | 资金流 (120 日) | **保持不变** | 子资源 `daily` 是 K 线频率标识,与 `/stocks/{code}/intraday` 平行,合理 |

### 2.3 🔴 需要调整 (6 个) — P0

| # | 当前路径 | 端点摘要 | 建议路径 | 原因 |
|---|---|---|---|---|
| 19 | `/api/v1/health` | 健康检查 + 断路器状态 | **`/healthz`** (或 `/api/v1/meta/health`) | 健康检查是 infra 级 endpoint,不是业务资源;k8s 惯例用 `/healthz`/`/readyz`;与 `/stocks`、`/boards` 平级会误导调用方把它当成某种数据集合。`/meta/health` 是保持版本号的备选 |
| 20 | `/api/v1/dragon-tiger/daily` | 龙虎榜 (全市场) | **`/api/v1/dragon-tiger`** (查询参数 `?date=YYYY-MM-DD`) | 与第 12 行 `/stocks/{code}/dragon-tiger` 是同一资源,两个端点分两个层级违反 REST;`daily` 是查询条件 (时间窗口) 不是路径段;按"`/resource` + `?query`"统一 |
| 21 | `/api/v1/pools` | 涨跌停股池 | **`/api/v1/zt-pool`** 或 **`/api/v1/zt-pools`** | `pools` 单复数模糊,且未说明是什么池——`STOCK_ZT_POOL` capability 名已经明说是"涨跌停";改 `/zt-pool` 直接对齐 capability |
| 22 | `/api/v1/indicators/catalog` | 技术指标目录 | **`/api/v1/indicators`** | `catalog` 是冗余后缀;`/calendar`、`/boards` 都没有 `catalog` 后缀;语义就是"指标列表",直接做 collection |
| 23 | `/api/v1/hot/topics` | 热点题材 | **`/api/v1/hot-topics`** (单段) | 双短词 `hot/topics` 没有真实层级意义;业内通用是 `hot-topics` (THS 同花顺、东方财富均如此);统一到 kebab-case 单段 |
| 24 | `/api/v1/north-flow/realtime` | 北向资金 | **`/api/v1/northbound/flow/realtime`** 或 **`/api/v1/northbound-flow/realtime`** | `north-flow` 命名模糊,易与"北风"混淆;金融标准术语是 `northbound` (北向) 与 `southbound` (南向) 对称;同时 `flow` 单独成段,与 `/fund-flow` 风格一致 |

### 2.4 🟡 子资源路径合理 (3 个) — 建议保留

| # | 当前路径 | 端点摘要 | 建议路径 | 原因 |
|---|---|---|---|---|
| 25 | `/api/v1/calendar` | A 股交易日历 | **保持不变** | 复数无意义 (1 个历法),单数合理 |
| 26 | `/api/v1/stocks/{stock_code}/reports` | 研报列表 | **保持不变** | 子资源清晰 |
| 27 | `/api/v1/stocks/{stock_code}/reports/{report_id}/pdf` | 研报 PDF 下载 | **保持不变** | 文件格式作为路径段是 REST 惯例 (`/report.pdf` vs `/report/{id}/download`) |

### 2.5 ⚪ 与 §2.3 序号 20 重叠需注意

| # | 当前路径 | 端点摘要 | 建议路径 | 原因 |
|---|---|---|---|---|
| 28 | `/api/v1/stocks/{stock_code}/announcements` | 公告 | **保持不变** | 资源归属清晰;迁移时与 1-16 一起处理 |

> 序号对应关系: §2.1 (1-16) + §2.2 (17-18) + §2.3 (19-24) + §2.4 (25-27) + §2.5 (28) = 28 个端点 ✓

---

## 3. `/news/*` 新闻端点 (3 个) — 🔴 P0

| # | 当前路径 | 端点摘要 | 建议路径 | 原因 |
|---|---|---|---|---|
| 29 | `/news/search` | 新闻搜索 | **`/api/v1/news/search`** (兼容旧路径 6 个月) | 与主 API 命名空间保持一致;`/news/*` 唯一被特殊处理不带前缀的业务端点,代码注释 (`routes.py:2067-2073`) 提到"外部工具硬编码",这正是兼容垫片要解决的问题 |
| 30 | `/news/flash` | 全球财经快讯 | **`/api/v1/news/flash`** (兼容旧路径) | 同上;且快讯与搜索是同一类资源,必须放一起 |
| 31 | `/news/content` | 新闻正文提取 | **`/api/v1/news/content`** (兼容旧路径) | 同上 |

**迁移方案**:
- 把 `news_router` 也挂到 `/api/v1` 前缀
- 保留旧路径 6 个月,响应加 `Deprecation` / `Sunset` HTTP 头 (RFC 8594)
- 6 个月后下线旧路径
- 删除 `routes.py:2067-2073` 的"故意不加前缀"注释

---

## 4. `/control/*` 控制平面端点 (4 个) — ✅ 保持不变

| # | 当前路径 | 端点摘要 | 建议路径 | 原因 |
|---|---|---|---|---|
| 32 | `/control/config` | 静态配置 (供外部工具/AI agent) | **保持不变** | 控制平面 127.0.0.1-only,无需版本;`/control` 前缀明确角色 |
| 33 | `/control/server/status` | 主服务状态 | **保持不变** | 同上 |
| 34 | `/control/api-manifest` | Explorer UI 加载时拉取 | **保持不变** | 同上 |
| 35 | `/control/fetcher-test` | Stage 2 fetcher 调试入口 | **保持不变** | 同上 |

---

## 5. `/explorer/*` 静态 UI — ✅ 保持不变

| # | 当前路径 | 角色 | 建议路径 | 原因 |
|---|---|---|---|---|
| 36 | `/explorer/` | HTML UI (FastAPI `StaticFiles` mount) | **保持不变** | UI 入口,合理 |

---

## 6. 迁移优先级汇总

| 优先级 | 端点 | 影响面 | 风险 |
|---|---|---|---|
| 🔴 **P0** | #19 `/health` | 改 `/healthz` 或 `/meta/health` | k8s/lb probe 需要更新 |
| 🔴 **P0** | #20 `/dragon-tiger/daily` | 合并到 `/dragon-tiger` | 客户端需去掉路径段、加 query 参数 |
| 🔴 **P0** | #29-31 `/news/*` | 移到 `/api/v1/news/*` | 需兼容垫片 |
| 🟡 **P1** | #21 `/pools` | 改 `/zt-pool` | 客户端路径替换 |
| 🟡 **P1** | #22 `/indicators/catalog` | 改 `/indicators` | 客户端路径替换 |
| 🟡 **P1** | #23 `/hot/topics` | 改 `/hot-topics` | 客户端路径替换 |
| 🟡 **P1** | #24 `/north-flow/realtime` | 改 `/northbound/...` | 客户端路径替换 |
| ✅ **保留** | 1-18, 25-28, 32-36 | — | 无 |

---

## 7. 不在本次评审范围

- 路径参数的命名风格 (如 `{stock_code}` vs `{code}` 不统一,出现在 #1 与 #2-4) — 是另一个独立问题,本次仅做资源层级评审
- Query 参数命名 (`from_` vs `from_date`、`limit` vs `count`) — 同上
- 响应字段命名 (`data / total / limit / source` 的 Pydantic 模型) — 同上

如需对上述做评审,请另起 RFC。

---

## 附录: 端点摘要索引

按 §2.3 P0 整改后的最终 API 形态:

```
GET  /healthz                                        # 健康检查
GET  /api/v1/stocks                                  # 股票列表
GET  /api/v1/stocks/{code}/info                      # 公司画像
GET  /api/v1/stocks/{stock_code}/quote               # 实时行情
GET  /api/v1/stocks/{stock_code}/history             # 历史 K 线
GET  /api/v1/stocks/{stock_code}/intraday            # 分钟 K 线
GET  /api/v1/stocks/{stock_code}/dragon-tiger        # 龙虎榜 (个股)
GET  /api/v1/stocks/{stock_code}/margin              # 融资融券
GET  /api/v1/stocks/{stock_code}/block-trade         # 大宗交易
GET  /api/v1/stocks/{stock_code}/holder-num          # 股东户数变化
GET  /api/v1/stocks/{stock_code}/dividend            # 分红送转
GET  /api/v1/stocks/{stock_code}/fund-flow           # 资金流 (分钟)
GET  /api/v1/stocks/{stock_code}/fund-flow/daily     # 资金流 (120 日)
GET  /api/v1/stocks/{stock_code}/reports             # 研报列表
GET  /api/v1/stocks/{stock_code}/reports/{id}/pdf    # 研报 PDF
GET  /api/v1/stocks/{stock_code}/announcements       # 公告

GET  /api/v1/indices                                 # 指数列表
GET  /api/v1/indices/{code}/quote
GET  /api/v1/indices/{code}/history
GET  /api/v1/indices/{code}/intraday

GET  /api/v1/calendar                                # 交易日历
GET  /api/v1/boards                                  # 板块列表
GET  /api/v1/boards/{code}/stocks                    # 板块成分股

GET  /api/v1/dragon-tiger?date=YYYY-MM-DD            # 龙虎榜 (全市场)
GET  /api/v1/zt-pool                                 # 涨跌停池
GET  /api/v1/hot-topics                              # 热点题材
GET  /api/v1/northbound/flow/realtime                # 北向资金
GET  /api/v1/indicators                              # 指标目录

GET  /api/v1/news/search                             # 新闻搜索
GET  /api/v1/news/flash                              # 全球快讯
GET  /api/v1/news/content                            # 新闻正文

GET  /control/config                                 # 静态配置
GET  /control/server/status
GET  /control/api-manifest
POST /control/fetcher-test

GET  /explorer/                                      # HTML UI
```