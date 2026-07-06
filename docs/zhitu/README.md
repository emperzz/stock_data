# 智兔数服 zhituapi — 沪深数据 API 文档（精编）

> 抓取时间：2026-06-10
> 源站点：<https://www.zhituapi.com/hsstockapi.html>

智兔数服（ZhiTuApi，网址 `https://www.zhituapi.com/`）提供 A 股及港股的金融数据 API 接口服务。本目录的文档覆盖**沪深数据 API**：股票侧 9 大类（来自 `hsstockapi.html`，约 60+ 个接口）以及指数侧独立模块（来自 `hsindexapi.html`，见 [10-indices-api.md](10-indices-api.md)，前缀 `/hz/`）。不涉及基金、债券、港股、美股、期货、黄金、外汇等其它模块。

> **关于凭证**：所有 API 均需 `token` 参数，将 `token证书` 替换为你的实际 token 即可调用。试用可使用文档示例中展示的 `ZHITU_TOKEN_LIMIT_TEST`。

## 文件清单

| 文件 | 主题 |
|---|---|
| [01-stocks-list.md](01-stocks-list.md) | **股票列表**：股票列表、新股日历、风险警示（ST）、概念指数列表、一级市场板块列表、板块明细列表 |
| [02-indices-industries-concepts.md](02-indices-industries-concepts.md) | **指数、行业、概念**：指数/行业/概念树、概念查股票、股票查概念 |
| [03-limit-up-down-pools.md](03-limit-up-down-pools.md) | **涨跌股池**：涨停股池、跌停股池、强势股池、次新股池、炸板股池 |
| [04-listed-company-details.md](04-listed-company-details.md) | **上市公司详情**：公司简介、所属指数、历届高管/董事/监事、近年分红/增发、解禁限售、近一年各季度利润/现金流、近年业绩预告、财务指标、十大股东、十大流通股东、股东变化趋势、基金持股、经营范围 |
| [05-realtime-trading.md](05-realtime-trading.md) | **实时交易**：公开/券商数据源的单只/全部/多选实时行情、当天逐笔、五档盘口、资金流向数据 |
| [06-market-data.md](06-market-data.md) | **行情数据**：最新分时、历史分时、历史涨跌停价格、行情指标、企业版1m级历史数据 |
| [07-basic-info.md](07-basic-info.md) | **基础信息**：股票基础信息（涨停价/跌停价/流通股本/总股本等） |
| [08-technical-indicators.md](08-technical-indicators.md) | **技术指标**：历史分时 MACD、MA、BOLL、KDJ |
| [09-financial-statements.md](09-financial-statements.md) | **财务报表**：资产负债表、利润表、现金流量表、财务主要指标、公司股本表、十大股东、十大流通股东、股东数 |
| [10-indices-api.md](10-indices-api.md) | **沪深指数 API**：`/hz/` 前缀独立模块 —— 指数列表、实时交易、最新/历史分时 K 线、历史 MACD/MA/BOLL/KDJ（与 `01-09` 的 `/hs/` 股票 API 平行） |

## 通用参数说明

### 股票代码格式

文档中提到的 `股票代码` 通常指 A 股 6 位数字代码（不带市场后缀），如 `000001`、`600519`。
对于需要指定市场的接口（如行情数据/技术指标），格式为 `股票代码.市场`：

- 上海：`000001.SH`、`600519.SH` 等
- 深圳：`000001.SZ`、`300750.SZ` 等
- 北京：`830xxx.BJ`

### 分时级别

| 参数值 | 含义 | 备注 |
|---|---|---|
| `1` | 1 分钟 | 仅企业版支持 |
| `5` | 5 分钟 | |
| `15` | 15 分钟 | |
| `30` | 30 分钟 | |
| `60` | 60 分钟 | |
| `d` | 日线 | |
| `w` | 周线 | |
| `m` | 月线 | |
| `y` | 年线 | |

### 除权方式

| 参数值 | 含义 | 备注 |
|---|---|---|
| `n` | 不复权 | 分钟级只能传 n |
| `f` | 前复权 | |
| `b` | 后复权 | |
| `fr` | 等比前复权 | |
| `br` | 等比后复权 | |

### 时间格式

- `YYYYMMDD` 例如 `20240101`
- `YYYYMMDDhhmmss` 例如 `20241231235959`

### 频率限制（所有接口通用）

| 版本 | 1 分钟请求次数 |
|---|---|
| 包量版 | 300 |
| 体验版、包月版 | 1000 |
| 包年版 | 3000 |
| 至尊版 | 6000 |

## 速查：按场景归类

| 场景 | 推荐接口 |
|---|---|
| 拉取 A 股股票清单 | `hs/list/all` |
| 拉取新股上市日程 | `hs/list/new` |
| 拉取 ST 股票 | `hs/list/fx` |
| 拉取概念板块 | `hs/list/sectors` |
| 概念与股票互查 | `hs/index/tree`、`hs/index/stock/<code>`、`hs/index/index/<code>` |
| 实时行情 | `hs/real/ssjy/<code>` |
| 全市场实时行情（批量） | `hs/public/realall`、`hs/custom/realall`（限至尊/包年） |
| 多股实时行情 | `hs/public/ssjymore`、`hs/custom/ssjymore`（限至尊/包年） |
| 当天逐笔 | `hs/real/zbjy/<code>` |
| 五档盘口 | `hs/real/five/<code>` |
| 历史日线/分钟线 | `hs/history/<code>.<market>/<level>/<adj>` |
| 资金流向 | `hs/history/transaction/<code>` |
| 历史涨跌停价 | `hs/stopprice/history/<code>` |
| 行情指标（量比/涨速/N日涨幅换手） | `hs/indicators/<code>` |
| 涨停/跌停/强势/次新/炸板股池 | `hs/pool/{ztgc,dtgc,qsgc,cxgc,zbgc}/<date>` |
| 公司基本信息 | `hs/gs/gsjj/<code>` |
| 公司股本/上市信息 | `hs/instrument/<code>` |
| 历届高管/董事/监事 | `hs/gs/{ljgg,ljds,ljjs}/<code>` |
| 分红、增发、解禁 | `hs/gs/{jnff,jnzf,jjxs}/<code>` |
| 季度利润/现金流/业绩预告 | `hs/gs/{jdlr,jdxj,yjyg}/<code>` |
| 财务指标 | `hs/gs/cwzb/<code>` |
| 十大股东/十大流通 | `hs/gs/{sdgd,ltgd}/<code>` |
| 股东数趋势、基金持股 | `hs/gs/{gdbh,jjcg}/<code>` |
| 经营范围 | `hs/gs/jyfw/<code>` |
| 资产负债表/利润表/现金流量表 | `hs/fin/{balance,income,cashflow}/<code>` |
| 财务主要指标 | `hs/fin/ratios/<code>` |
| 公司股本表 | `hs/fin/capital/<code>` |
| 财务口径十大股东/十大流通 | `hs/fin/{topholder,flowholder}/<code>` |
| 股东户数 | `hs/fin/hm/<code>` |
| 技术指标（MACD/MA/BOLL/KDJ） | `hs/history/{macd,ma,boll,kdj}/<code>.<market>/<level>/<adj>` |
| 指数列表 | `hz/list/hszs` |
| 指数实时行情 | `hz/real/ssjy/<code>` |
| 指数最新分时 K 线 | `hz/latest/fsjy/<code>.<market>/<level>` |
| 指数历史分时 K 线 | `hz/history/fsjy/<code>.<market>/<level>` |
| 指数技术指标（MACD/MA/BOLL/KDJ） | `hz/history/{macd,ma,boll,kdj}/<code>/<level>` |

## 与本项目 `DataFetcherManager` 的对应

| 智兔接口 | 对应 `DataCapability` 标志 | 备注 |
|---|---|---|
| `hs/list/all` | `STOCK_LIST` | 落库 `data_provider/persistence/stock_list.py` |
| `hs/pool/ztgc/*` / `hs/pool/dtgc/*` | `STOCK_ZT_POOL` | 涨跌停股池 |
| `hs/real/ssjy/*` | `REALTIME_QUOTE` | 实时报价（增强字段：PE/PB/市值/涨跌停价/量比/换手率/涨速/振幅 等） |
| `hs/instrument/*` | n/a | 由 `persistence.stock_list` 处理（DB 优先 + `STOCK_LIST` 回退） |
| `hs/fin/balance/income/cashflow/ratios` | n/a | 财务报表（**本项目暂未接入**） |
| `hs/gs/*`（公司详情） | n/a | **本项目暂未接入** |
| `hs/history/macd/ma/boll/kdj` | n/a | **本项目已有自有 indicator 服务**（`data_provider/indicators/`），不依赖智兔 |
| `hz/list/hszs` | n/a | 静态指数列表；本项目用 `data_provider/fetchers/index_symbols.py` 维护 |
| `hz/real/ssjy/<code>` | `INDEX_REALTIME_QUOTE` | **当前未接入**（`ZhituFetcher.supported_data_types` 未声明该 flag，详见 [10-indices-api.md](10-indices-api.md)） |
| `hz/latest/fsjy/<code>.<market>/<level>`、`hz/history/fsjy/...` | `INDEX_KLINE` | **当前未接入**（同上） |
| `hz/history/{macd,ma,boll,kdj}/<code>/<level>` | n/a | **本项目已有自有 indicator 服务**，不依赖智兔 |

> 本项目 `ZhituFetcher` 当前只用了 `REALTIME_QUOTE` 与 `STOCK_ZT_POOL` 两个 capability（参考 `CLAUDE.md` 中的 fetcher 能力声明）。文档中的其它接口如需接入，可通过 `get_realtime_quote` / `get_zt_pool` 等方法 + 新增 `DataCapability` 标志位来扩展。
