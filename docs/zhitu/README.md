# 智兔数服 zhituapi — API 文档镜像（精编）

> 抓取时间：2026-10-08
> 源站点：<https://www.zhituapi.com/>

智兔数服（ZhiTuApi，网址 `https://www.zhituapi.com/`）提供 A 股及港股的金融数据 API 接口服务。本目录是上游 API 文档页的逐节镜像转录（保留上游原文，包括上游自身的笔误；凡本项目添加的注记均以 **本项目备注** 显式标出）。

上游 API 文档现共 **6 个页面、223 个接口节**（2026-10-08 清点）：

| 上游页面 | 内容 | 镜像文件 | 节数 |
|---|---|---|---|
| `hsstockapi.html` 沪深A股API文档 | 沪深股票侧，10 大类 | 01-09 | 69 |
| `hsindexapi.html` 沪深指数API文档 | 指数侧（`/hz/` 前缀） | 10 | 15 |
| `hsdataapi.html` 沪深数据API文档 | 融资融券/龙虎榜/选股/财务分析/机构持股/资金流向/南向·北向/可转债 | 11-14 | 77 |
| `bjdataapi.html` 京市A股API文档 | 北交所侧 | 15 | 27 |
| `kcdataapi.html` 科创行情API文档 | 科创板侧（仅列表+实时+盘口 3 接口） | 16 | 3 |
| `hkdataapi.html` 港股主板API文档 | **空壳页**（仅导航，无任何接口，2026-10-08 核实） | 16 内说明 | 0 |
| `fundmarketapi.html` 基金行情API文档 | 基金侧 | 17 | 32 |

> **关于凭证**：所有 API 均需 `token` 参数，将 `token证书` 替换为你的实际 token 即可调用。试用可使用文档示例中展示的 `ZHITU_TOKEN_LIMIT_TEST`。Pro/扩能包系列接口（路径含 `/pro/`，另有专属域名 `p.zhituapi.com`）需另购「API扩能包」，基础证书过期时只要扩能包有效仍可调用。

## 文件清单

| 文件 | 主题 |
|---|---|
| [01-stocks-list.md](01-stocks-list.md) | **股票列表**：股票列表、新股日历、风险警示（ST）、概念指数列表、一级市场板块列表、板块明细列表 |
| [02-indices-industries-concepts.md](02-indices-industries-concepts.md) | **指数、行业、概念**：指数/行业/概念树、概念查股票、股票查概念 |
| [03-limit-up-down-pools.md](03-limit-up-down-pools.md) | **涨跌股池**：涨停股池、跌停股池、强势股池、次新股池、炸板股池（2026-10-08 起各池新增 `hy` 所属行业字段） |
| [04-listed-company-details.md](04-listed-company-details.md) | **上市公司详情**：公司简介、所属指数、历届高管/董事/监事、近年分红/增发、解禁限售、近一年各季度利润/现金流、近年业绩预告、财务指标、十大股东、十大流通股东、股东变化趋势、基金持股、经营范围 |
| [05-realtime-trading.md](05-realtime-trading.md) | **实时交易**：公开/券商数据源的单只/全部/多选实时行情、当天逐笔、历史逐笔、五档盘口 + 上游「特色行情」分类的资金流向数据、历史资金流向数据 |
| [06-market-data.md](06-market-data.md) | **行情数据**：最新/历史分时、历史涨跌停价格、行情指标、企业版1m级历史数据、涨跌停表现、集合竞价表现、Pro版最新/历史/完整历史分时交易 |
| [07-basic-info.md](07-basic-info.md) | **基础信息**：股票基础信息（涨停价/跌停价/流通股本/总股本等） |
| [08-technical-indicators.md](08-technical-indicators.md) | **技术指标**：历史分时 MACD、MA、BOLL、KDJ + 4 个 Pro版·1分钟 指标（上游归类于「行情数据」，本文归并至此） |
| [09-financial-statements.md](09-financial-statements.md) | **财务报表**：资产负债表、利润表、现金流量表、财务主要指标、公司股本表、十大股东、十大流通股东、股东数 |
| [10-indices-api.md](10-indices-api.md) | **沪深指数 API**：`/hz/` 前缀模块 —— 指数列表、实时交易、最新/历史分时 K 线、Pro版分时（3 节）、历史 MACD/MA/BOLL/KDJ、Pro版·1分钟指标（4 节） |
| [11-hsdata-investment-dragon-tiger.md](11-hsdata-investment-dragon-tiger.md) | **沪深数据 API（一）**：投资参考（今日交易提示、融资融券总量/明细、大宗交易、解禁限售、打新收益、历史累计分红）+ 龙虎榜（每日详情、个股/营业部上榜统计、机构席位追踪/成交明细） |
| [12-hsdata-market-financial-institutional.md](12-hsdata-market-financial-institutional.md) | **沪深数据 API（二）**：市场表现（阶段最高最低、盘中新高/新低、成交骤增/骤减、连续放/缩量、连续涨/跌、周/月涨跌排名、流通市值/PE/PB/ROE 排行）+ 财务分析（盈利/运营/成长/偿债/现金流、业绩报表/预告/快报、利润细分）+ 机构持股（机构汇总、基金/社保/QFII 重仓） |
| [13-hsdata-fundflow-northbound.md](13-hsdata-fundflow-northbound.md) | **沪深数据 API（三）**：板块资金流向（证监会行业、概念板块）+ 个股资金流向（净流入额/率、主力、散户排名）+ 资金路线图（行业/概念路线图、个股阶段统计、主力连续净流入/流出）+ 南向·北向资金（21 节：概览、历史走势/总览、成分股行情、AH 股比价、十大成交股、周期排名、沪深股通/港股通历史数据） |
| [14-hsdata-convertible-bonds.md](14-hsdata-convertible-bonds.md) | **沪深数据 API（四）**：可转债一览、比价表、实时行情 |
| [15-beijing-a-share-api.md](15-beijing-a-share-api.md) | **京市 A 股 API**：股票/指数列表、实时数据、五档盘口、当天/历史逐笔、历史分时、Pro版分时与 1m 指标【京】、财务报表 8 节【京】、技术指标 4 节【京】 |
| [16-star-market-api.md](16-star-market-api.md) | **科创行情 API**：科创股票列表、股票实时数据、买卖五档盘口（共 3 节）+ 港股主板空壳页说明 |
| [17-fund-market-api.md](17-fund-market-api.md) | **基金行情 API**：基金列表/估值/行情/K线/MA/概况/净值/持仓/排名/业绩/分红/规模/其他/实时（共 32 节） |

## 通用参数说明

### 股票代码格式

文档中提到的 `股票代码` 通常指 A 股 6 位数字代码（不带市场后缀），如 `000001`、`600519`。
对于需要指定市场的接口（如行情数据/技术指标），格式为 `股票代码.市场`：

- 上海：`000001.SH`、`600519.SH` 等
- 深圳：`000001.SZ`、`300750.SZ` 等
- 北京：`830xxx.BJ`

指数侧（`/hz/`）代码同样要求带市场后缀，且 `000xxx` → `.SH`、`399xxx` → `.SZ`（与股票 helper 相反）。

### 分时级别

| 参数值 | 含义 | 备注 |
|---|---|---|
| `1` | 1 分钟 | **常规分时接口已不开放 period=1**；须走 Pro/扩能包路径（`hs/pro/latest|history`、`p.zhituapi.com` 完整历史）或「企业版历史数据【1m级别】」 |
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

另有单次性限制的特例：`hs/public/realall`、`hs/custom/realall`（全市场实时）限制每分钟请求 1 次且仅限至尊版/包年版；`hs/public/ssjymore`、`hs/custom/ssjymore`（多股实时）仅限至尊版/包年版且单次 ≤20 支。

## 速查：按场景归类

### 沪深股票（01-09，`/hs/`）

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
| 历史逐笔（按日归档） | `hs/real/zbjy/<yyyyMMdd>/<code>`（数据自 2026-08-13 起累积） |
| 五档盘口 | `hs/real/five/<code>` |
| 最新/历史分时 | `hs/latest/<code>.<market>/<level>/<adj>`、`hs/history/<code>.<market>/<level>/<adj>` |
| 1m 分时（Pro） | `hs/pro/latest|history/<code>.<market>/1/n`、`p.zhituapi.com/hs/history/full/...` |
| 涨停/跌停表现 | `hs/lup/limit/<code>.<market>` |
| 集合竞价表现 | `hs/lup/auction/<code>.<market>` |
| 历史涨跌停价 | `hs/stopprice/history/<code>` |
| 行情指标（量比/涨速/N日涨幅换手） | `hs/indicators/<code>` |
| 涨停/跌停/强势/次新/炸板股池 | `hs/pool/{ztgc,dtgc,qsgc,cxgc,zbgc}/<date>` |
| 公司基本信息（画像） | `hs/gs/gsjj/<code>` |
| 公司股本/上市信息 | `hs/instrument/<code>` |
| 历届高管/董事/监事 | `hs/gs/{ljgg,ljds,ljjs}/<code>` |
| 分红、增发、解禁 | `hs/gs/{jnff,jnzf,jjxs}/<code>` |
| 季度利润/现金流/业绩预告 | `hs/gs/{jdlr,jdxj,yjyg}/<code>` |
| 财务指标 | `hs/gs/cwzb/<code>` |
| 十大股东/十大流通 | `hs/gs/{sdgd,ltgd}/<code>` |
| 股东数趋势、基金持股 | `hs/gs/{gdbh,jjcg}/<code>` |
| 经营范围 | `hs/gs/jyfw/<code>` |
| 资金流向（多日区间/最近1日） | `hs/history/transaction/<code>`（st+et ≤365 天） |
| 资金流向（单日） | `hs/history/transaction/<yyyyMMdd>/<code>` |
| 资产负债表/利润表/现金流量表 | `hs/fin/{balance,income,cashflow}/<code>` |
| 财务主要指标 | `hs/fin/ratios/<code>` |
| 公司股本表 | `hs/fin/capital/<code>` |
| 财务口径十大股东/十大流通 | `hs/fin/{topholder,flowholder}/<code>` |
| 股东户数 | `hs/fin/hm/<code>` |
| 技术指标（MACD/MA/BOLL/KDJ） | `hs/history/{macd,ma,boll,kdj}/<code>.<market>/<level>/<adj>`；1m 走 `hs/pro/history/{macd,ma,boll,kdj}/<code>.<market>/1/<adj>` |

### 沪深指数（10，`/hz/`）

| 场景 | 推荐接口 |
|---|---|
| 指数列表 | `hz/list/hszs` |
| 指数实时行情 | `hz/real/ssjy/<code>` |
| 指数最新分时 K 线 | `hz/latest/fsjy/<code>.<market>/<level>` |
| 指数历史分时 K 线 | `hz/history/fsjy/<code>.<market>/<level>` |
| 指数 1m K 线（Pro） | `hz/pro/latest|history/fsjy/<code>.<market>/1`、`hz/history/full/fsjy/...` |
| 指数技术指标 | `hz/history/{macd,ma,boll,kdj}/<code>/<level>`；1m 走 `hz/pro/history/{macd,ma,boll,kdj}/<code>/1` |

### 沪深数据（11-14）

沪深数据 API 的路径前缀**不再是** `/hs/`，而是按域分组：`hitc`（投资参考）、`hilh`（龙虎榜）、`himk`（市场表现/选股）、`hicw`（财务分析）、`hijg`（机构持股）、`hibk`（板块资金流向）、`higg`（个股资金流向）、`hizj`（资金路线图）、`ht/nbzj`（南向·北向资金）、`kzz`（可转债）。

| 场景 | 推荐接口 |
|---|---|
| 今日交易提示（停复牌/除权等） | `hitc/jrts` |
| 融资融券总量/明细 | `hitc/rzrqzl`、`hitc/rzrqmx` |
| 大宗交易 | `hitc/dzjy` |
| 解禁限售 / 打新收益 / 历史累计分红 | `hitc/jjxs`、`hitc/dxsy`、`hitc/lsfh` |
| 龙虎榜每日详情与各类上榜统计 | `hilh/{mrxq,ggsb,yybsb,jgxw,xwmx}` |
| 选股类（盘中新高/新低、连续涨跌、骤增/骤减、周月排名、市值/PE/PB/ROE 排行） | `himk/*`，共 15 节，见 12 |
| 财务分析类（盈利/运营/成长/偿债/现金流五维 + 业绩报表/预告/快报） | `hicw/*`，共 9 节，见 12 |
| 机构持股（机构汇总、基金/社保/QFII 重仓） | `hijg/*`（须带 `年度/季度` 路径段） |
| 板块/个股资金流向排名、资金路线图 | `hibk/{zjhhy,gnbk}`、`higg/{jlr,...}`、`hizj/{zjh,bk,ggzl,ggjd,lxlr}` |
| 北向/南向资金（概览、走势、成分股行情、十大成交股、周期排名、历史数据）与 AH 股比价 | `ht/nbzj/*`，共 21 节，见 13 |
| 可转债（一览、比价、实时） | `kzz/{list,comparison,spot}` |

### 其它市场（15-17）

| 场景 | 推荐接口 |
|---|---|
| 北交所股票/指数清单、实时、分时、财报 | `/bj/` 系列，见 15 |
| 科创板清单、实时、五档盘口 | `/tech/` 系列（`tech/list/all`、`tech/real/ssjy`、`tech/real/mmwp`），见 16 |
| 基金清单、估值、K线、净值、分红、排名 | `/fund/` 与 `/jh/` 系列，见 17 |

## 与本项目 `ZhituFetcher` 的对应

`ZhituFetcher`（P5，`data_provider/fetchers/zhitu_fetcher.py`）当前实际调用的上游端点：

| 智兔接口 | 对应 `DataCapability` 标志 | 备注 |
|---|---|---|
| `hs/list/all` | `STOCK_LIST` | 落库 `data_provider/persistence/stock_list.py` |
| `hs/pool/{ztgc,dtgc,zbgc}/<date>` | `STOCK_ZT_POOL` | 涨跌停/炸板股池（强势、次新池未接入） |
| `hs/real/ssjy/<code>` | `STOCK_REALTIME_QUOTE` | 实时报价（增强字段：PE/PB/市值/涨跌停价/量比/换手率/涨速/振幅 等） |
| `hs/latest/fsjy/*`、`hs/history/*/<level>/<adj>` | `STOCK_KLINE` | d/w/m + 5/15/30/60m（分钟级 adjust 只能 `n`）；1m 常规接口上游已关闭 |
| `hs/index/tree`、`hs/index/stock/<code>`、`hs/index/index/<code>` | `STOCK_BOARD` | 概念/行业树与双向互查 |
| `hs/gs/gsjj/<code>` | `STOCK_INFO` | 公司画像（18 字段；2026-07-14 实测 payload 无 `code` 键、`principal` 实为主承销商） |
| `hs/gs/jnff/<code>` | `DIVIDEND` | 近年分红 |
| `hs/gs/gdbh/<code>` | `HOLDER_NUM` | 股东变化趋势 |
| `hs/history/transaction/<code>` | `FUND_FLOW` | 资金流向（注意 2026-10 上游语义：无 st/et 仅最近 1 日；区间 ≤365 天） |
| `hz/list/hszs` | n/a | 本项目用 `data_provider/fetchers/index_symbols.py` 维护指数清单，不调用它 |
| `hz/real/ssjy/<code>` | `INDEX_REALTIME_QUOTE` | **已接入**（2026-07-06），详见 [10-indices-api.md](10-indices-api.md) 尾部映射表 |
| `hz/history/fsjy/<code>.<market>/<level>` | `INDEX_KLINE` | **已接入**（同上；5/15/30/60m 与 d/w/m） |

**未接入**（保持镜像以便日后评估）：`hs/instrument`、`hs/gs/*` 其余公司详情、`hs/fin/*` 财务报表（本项目不做 fundamental data）、`hs/indicators`、`hs/stopprice/history`、`hs/lup/*`、Pro/扩能包全系（付费墙）、以及 11-17 全部模块（融资融券/龙虎榜/选股/北向等本项目由 EastMoney/THS/Zzshare 等覆盖；基金、北交所、科创板侧未接入）。

> 本项目指标计算走自有 `data_provider/indicators/` 服务，不依赖智兔 `hs|hz/history/{macd,ma,boll,kdj}`。

## 变更记录（相对 2026-06-10 / 07-06 抓取）

- **新增镜像**：`hsdataapi.html`（77 节，11-14）、`bjdataapi.html`（27 节，15）、`kcdataapi.html`（3 节，16）、`fundmarketapi.html`（32 节，17）；确认 `hkdataapi.html` 为空壳页。
- **hsstockapi 新增节**：历史逐笔交易（数据自 2026-08-13 起归档）、涨跌停表现、集合竞价表现、最新/历史/完整历史分时交易（Pro版）、4 个 Pro版·1分钟 技术指标、历史资金流向数据。
- **hsstockapi 字段/语义变更**：五个涨跌股池新增 `hy`（所属行业）；资金流向数据 URL 与 st/et 语义重写（无日期=最近 1 日、st+et≤365 天、单日改走历史接口）；全部/多选实时行情补全独立字段表；财务指标（`hs/gs/cwzb`）、三大财务报表字段表大幅扩充；实时交易（公开）`v` 上游写作"手"，与本项目 2026-07-06 实测"万手"不符（见 05 注记）；常规分时 `period=1` 明确关闭。
- **hsindexapi 新增节**：指数侧 Pro版最新/历史/完整历史分时 + 4 个 Pro版·1分钟 指标（共 7 节）；`hz/history/{macd,ma,boll,kdj}` 的 period=1 上游明确停止开放。
