# 掘金量化 myQuant — 股票相关 API 文档（精编）

> 抓取时间：2026-06-09
> 源站点：
> - SDK 基本函数：<https://www.myquant.cn/docs2/sdk/python/API介绍/基本函数.html>
> - 数据文档总入口（股票）：<https://www.myquant.cn/docs2/docs/>
>
> 本目录只覆盖 **股票相关 API**（A 股、含港股通/北向资金，含可转债/ETF 涉及股票的部分），不涉及期货/期权/纯基金。每个 API 明确标注**免费 / 付费**版本归属。

## 文件清单

| 文件 | 主题 |
|---|---|
| [00-overview-and-pricing.md](00-overview-and-pricing.md) | **必读**：版本分层（体验版/专业版/券商版/机构版）、免费 vs 付费的判定规则 |
| [01-strategy-lifecycle.md](01-strategy-lifecycle.md) | 策略生命周期：`init` / `schedule` / `run` / `stop` / `timer` / `timer_stop` |
| [02-data-subscription-events.md](02-data-subscription-events.md) | 数据订阅 + 事件：`subscribe` / `unsubscribe` / `on_tick` / `on_bar` / `on_l2transaction` / `on_l2order` |
| [03-quote-query-free.md](03-quote-query-free.md) | 行情查询（免费）：`last_tick` / `current_price` / `history` / `history_n` / `context.data`；**含 5 个付费 L2 函数** |
| [04-common-data-free.md](04-common-data-free.md) | 通用数据（免费）：标的信息、交易日历、交易时段、合约到期天数 |
| [05-stock-fundamentals-free.md](05-stock-fundamentals-free.md) | 股票财务 & 基础数据（免费）：财报、主要/衍生指标、估值/市值/股本日数据、指数成分股 |
| [06-stock-valueadd-paid.md](06-stock-valueadd-paid.md) | 股票增值数据（**全部付费**）：行业 / 板块 / 分红 / 股东 / 龙虎榜 / 北向 / 资金流 / 业绩预告 / 集合竞价 |
| [07-trading-functions.md](07-trading-functions.md) | 交易：下单 / 撤单 / 调仓 / 委托查询 / 资金持仓 / 标的池 / 交易事件 |
| [08-margin-trading.md](08-margin-trading.md) | 两融交易（融资融券） |
| [09-algo-ipo-misc.md](09-algo-ipo-misc.md) | 算法交易、新股新债申购、其他工具函数（set_token/log/version） |
| [10-data-reference-stock.md](10-data-reference-stock.md) | 数据文档「股票」页字段参考（行情/财务/行业/板块/分红/股本/龙虎榜/北向） |
| [appendix-fundamentals-full-fields.md](appendix-fundamentals-full-fields.md) | 附录：股票财务数据 17 个函数的**全字段表**（约 135 KB，含资产负债表 / 现金流量表 / 利润表完整字段） |

## 速查：免费可调用 vs 付费可调用

| 类别 | 免费版（体验/专业/机构公版）可用 | 需付费/券商版/特定权限 |
|---|---|---|
| **K 线/Tick** | `history` `history_n` `last_tick` `current_price` `subscribe` 日线/分钟线 | 历史 L2 系列（`get_history_l2ticks` / `bars` / `transactions` / `orders` / `orders_queue`）；高频/逐笔订阅多由券商版/付费） |
| **标的与日历** | `get_symbol_infos` `get_symbols` `get_history_symbol` `get_trading_dates_by_year` `get_previous/next_n_trading_dates` `get_trading_session` `get_contract_expire_rest_days` | — |
| **财务报表** | `stk_get_fundamentals_balance/cashflow/income`(及 `_pt`) `stk_get_finance_prime/deriv`(及 `_pt`) | `stk_get_finance_audit` `stk_get_finance_forecast` |
| **估值/市值/股本日线** | `stk_get_daily_valuation/mktvalue/basic`(及 `_pt`) | — |
| **指数** | `stk_get_index_constituents` | — |
| **行业 / 板块 / 分红 / 配股 / 复权因子** | — | `stk_get_industry_*` `stk_get_sector_*` `stk_get_dividend` `stk_get_ration` `stk_get_adj_factor` |
| **股东 / 股本变动** | — | `stk_get_shareholder_num` `stk_get_top_shareholder` `stk_get_share_change` |
| **龙虎榜 / 沪深港通 / 资金流** | — | `stk_abnor_change_*` `stk_quota_shszhk_infos` `stk_hk_inst_holding_*` `stk_active_stock_top10_shszhk_info` `stk_get_money_flow` |
| **集合竞价开盘成交** | — | `get_open_call_auction` |
| **交易/委托/账户** | 全部委托/查询函数（功能本身免费，需绑定有交易权限的账户） | — |
| **两融** | 同上 | — |
| **算法交易 / IPO 申购** | 同上 | — |

> 说明：「免费」指 SDK 公版（体验版及以上）即可调用；个别函数在**券商版**上以「升级提示」形式存在，请以掘金弹窗为准。

## 整体使用流程图

```
┌─────────────────────────────────────────────────────────────┐
│  ① 策略入口：run(strategy_id, filename, mode, token, ...)    │
│                                                              │
│  ② init(context) — 初始化、subscribe、schedule、set_token    │
│                                                              │
│  ③ 事件循环（由 SDK 调度）：                                  │
│     • on_tick(context, tick)      ← tick 推送                │
│     • on_bar(context, bars)        ← bar 推送                │
│     • on_l2transaction / on_l2order ← 付费 L2                │
│     • on_order_status              ← 委托状态                │
│     • on_execution_report          ← 成交回报                │
│     • on_account_status            ← 账户状态                │
│     • schedule / timer 回调        ← 定时                    │
│                                                              │
│  ④ 数据查询（pull）：history / history_n / current_price    │
│     stk_get_* / get_symbols / get_trading_dates_by_year ...  │
│                                                              │
│  ⑤ 下单：order_volume / order_value / order_target_*         │
│     algo_order / credit_* / ipo_buy                          │
│                                                              │
│  ⑥ stop() — 退出进程                                          │
└─────────────────────────────────────────────────────────────┘
```
