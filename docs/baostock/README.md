# Baostock 在线 API 文档(本地镜像)

来源:https://baostock.com (官方在线知识库,2026-06-10 抓取)

本目录是 baostock.com 知识库"Python API 文档"侧边栏全部 31 个子页面的本地镜像,内容通过 `POST https://baostock.com/helpdocs/api/markdown/{file}` 接口获取(原始 markdown 含 HTML 表格,原样保留)。

---

## 数据更新频率(API 层面)

汇总自 `home.md` 及各接口文档,供排期/限流/缓存决策参考。

### 全局数据刷新时间表(`home.md`)

| 时点 | 完成入库的内容 |
|------|-----------------|
| 当前交易日 17:30 | 日 K 线数据 |
| 当前交易日 18:00 | 复权因子数据 |
| 当前交易日 20:00 | 分钟 K 线数据 |
| 第二自然日 01:30 | 前交易日"其它财务报告数据" |
| 每周六 17:30 | 周 K 线数据 |
| 每月 1 号 17:30 | 上月月 K 线数据 |
| 每周一下午 | 上证 50、沪深 300、中证 500 成分股信息 |

### 各 API 接口的更新频率(逐接口)

| API | 更新频率 | 文档 |
|-----|----------|------|
| `query_history_k_data_plus()` 日/周/月线 | 17:30 / 周六 17:30 / 每月 1 号 17:30 | [stockKData.md](./stockKData.md) |
| `query_history_k_data_plus()` 5/15/30/60 分钟线 | 当前交易日 20:00 | [stockKData.md](./stockKData.md) |
| `query_history_k_data_plus()` ETF 全部频率 | 当前交易日 17:30(2026-01-05 起) | [stockKData.md](./stockKData.md) |
| `query_history_k_data_plus()` 指数日/周/月 | 17:30 / 周六 17:30 / 每月 1 号 17:30(无分钟线) | [indexData.md](./indexData.md) |
| `query_adjust_factor()` 复权因子 | 当前交易日 18:00 | [factorInfo.md](./factorInfo.md) |
| `query_dividend_data()` 除权除息信息 | 跟随财报披露(次交易日 01:30 起) | [dividInfo.md](./dividInfo.md) |
| 季频财务/业绩数据(`query_profit_data` 等 7 个) | 公司财报披露日(参考 [season*.md](./seasonProfit.md)) | season*.md |
| `query_performance_express_report()` 业绩快报 | 2006 年至今,披露即更新 | [seasonExpress.md](./seasonExpress.md) |
| `query_forecast_report()` 业绩预告 | 2003 年至今,披露即更新 | [seasonForecast.md](./seasonForecast.md) |
| `query_stock_basic()` 证券基本资料 | 跟随上市/退市状态变更 | [stockBasic.md](./stockBasic.md) |
| `query_trade_dates()` 交易日历 | 上交所 1990-今年 | [StockBasicInfoAPI.md](./StockBasicInfoAPI.md) |
| `query_all_stock()` 当日全证券 | **与日 K 线同时更新(17:30)** | [StockBasicInfoAPI.md](./StockBasicInfoAPI.md) |
| `query_industry_stock()` 行业分类 | **每周一更新** | [stockIndustry.md](./stockIndustry.md) |
| `query_sz50_stocks()` 上证 50 成分股 | **每周一更新** | [sz50Stock.md](./sz50Stock.md) |
| `query_hs300_stocks()` 沪深 300 成分股 | **每周一更新** | [hs300Stock.md](./hs300Stock.md) |
| `query_zz500_stocks()` 中证 500 成分股 | **每周一更新** | [zz500Stock.md](./zz500Stock.md) |
| `query_deposit_rate_data()` 存款利率 | 1990 至今,央行公告即更新 | [depositRate.md](./depositRate.md) |
| `query_loan_rate_data()` 贷款利率 | 2010 至今,央行公告即更新 | [loanRate.md](./loanRate.md) |
| `query_required_reserve_ratio_data()` 存款准备金率 | 1999 至今,公告即更新 | [reserveRatio.md](./reserveRatio.md) |
| `query_money_supply_data_month()` 货币供应量(月) | 1978 至今 | [supplyData.md](./supplyData.md) |
| `query_money_supply_data_year()` 货币供应量(年底) | 1952 至今 | [supplyDataYear.md](./supplyDataYear.md) |

---

## 目录索引

### 入门

- [home.md](./home.md) — 平台介绍、下载安装、版本历史、数据范围说明
- [pythonAPI.md](./pythonAPI.md) — Python API 完整目录(13 章,所有接口)
- [pythonDevRes.md](./pythonDevRes.md) — Python 开发资源链接(教程、框架、社区、数据源)

### 行情数据

- [stockKData.md](./stockKData.md) — A 股 K 线数据(`query_history_k_data_plus`)
- [indexData.md](./indexData.md) — 指数 K 线数据
- [valuationDaily.md](./valuationDaily.md) — 沪深 A 股估值指标(日频,peTTM / pbMRQ / psTTM / pcfNcfTTM)

### 复权 & 衍生

- [dividInfo.md](./dividInfo.md) — 除权除息信息
- [factorInfo.md](./factorInfo.md) — 复权因子(涨跌幅复权算法)
- [localdatafactorInfo.md](./localdatafactorInfoInfo.md) — 利用本地 K 线 + 复权因子手动算复权价 *(注:实际文件名 `localdatafactorInfo.md`)*

### 季频财务

- [seasonProfit.md](./seasonProfit.md) — 季频盈利能力
- [seasonOperation.md](./seasonOperation.md) — 季频营运能力
- [seasonGrowth.md](./seasonGrowth.md) — 季频成长能力
- [seasonBalance.md](./seasonBalance.md) — 季频偿债能力
- [seasonCashFlow.md](./seasonCashFlow.md) — 季频现金流量
- [seasonDupont.md](./seasonDupont.md) — 季频杜邦指数

### 季频公司报告

- [seasonExpress.md](./seasonExpress.md) — 季频业绩快报
- [seasonForecast.md](./seasonForecast.md) — 季频业绩预告

### 基础数据 & 板块

- [stockBasic.md](./stockBasic.md) — 证券基本资料
- [StockBasicInfoAPI.md](./StockBasicInfoAPI.md) — 证券元信息(交易日历 / 证券代码查询)
- [stockIndustry.md](./stockIndustry.md) — 行业分类
- [sz50Stock.md](./sz50Stock.md) — 上证 50 成分股
- [hs300Stock.md](./hs300Stock.md) — 沪深 300 成分股
- [zz500Stock.md](./zz500Stock.md) — 中证 500 成分股

### 宏观经济

- [depositRate.md](./depositRate.md) — 存款利率
- [loanRate.md](./loanRate.md) — 贷款利率
- [reserveRatio.md](./reserveRatio.md) — 存款准备金率
- [supplyData.md](./supplyData.md) — 货币供应量(月度)
- [supplyDataYear.md](./supplyDataYear.md) — 货币供应量(年底余额)

### 公式与指数

- [dataExplain.md](./dataExplain.md) — 公式与数据格式说明 / 指数代码大全(综合 / 规模 / 一级行业 / 二级行业 / 策略 / 成长 / 价值 / 主题 / 基金 / 债券共 10 类)

### 元信息

- [modifyRecord.md](./modifyRecord.md) — 数据调整记录(2018-2026 共 20 条)
- [goodArticle.md](./goodArticle.md) — 社区好文章(11 篇,链接 BaoStock 爱好者投稿的 PDF)

---

## 已跳过的页面

`访问统计` 入口指向 `/blacklist`,非文档页,已跳过。

## 抓取方式

```bash
# 抓取单个文件(以 home.md 为例)
curl -X POST 'https://baostock.com/helpdocs/api/markdown/home.md' \
  -H 'Content-Type: application/json' \
  -d '{}' --compressed
```

侧边栏 32 项中 31 项对应的 `file` 参数名通过 hook 浏览器 `history.pushState` 抓取,详见子页面对应的 `<a id="...">` 锚点。
