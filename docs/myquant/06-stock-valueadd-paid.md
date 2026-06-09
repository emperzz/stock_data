# 股票增值数据函数（付费） — 原始

> 抓自 `https://www.myquant.cn/docs2/sdk/python/API介绍/股票增值数据函数（付费）.html`
>
> **整页 22 个函数全部为付费功能** — 体验版无权限调用，会以升级提示报错。

## 函数清单（按主题）

### 行业（付费）
| 函数 | 签名 |
|---|---|
| `stk_get_industry_category` | `(source='zjh2012', level=1)` |
| `stk_get_industry_constituents` | `(industry_code, date="")` |
| `stk_get_symbol_industry` | `(symbols, source="zjh2012", level=1, date="")` |

### 板块（付费）
| 函数 | 签名 |
|---|---|
| `stk_get_sector_category` | `(sector_type)` — `1001`=市场板块, `1002`=地域板块, `1003`=概念板块 |
| `stk_get_sector_constituents` | `(sector_code)` |
| `stk_get_symbol_sector` | `(symbols, sector_type)` |

### 分红/配股/复权（付费）
| 函数 | 签名 |
|---|---|
| `stk_get_dividend` | `(symbol, start_date, end_date)` |
| `stk_get_ration` | `(symbol, start_date, end_date)` — 配股 |
| `stk_get_adj_factor` | `(symbol, start_date="", end_date="", base_date="")` |

### 股东 / 股本（付费）
| 函数 | 签名 |
|---|---|
| `stk_get_shareholder_num` | `(symbol, start_date="", end_date="")` |
| `stk_get_top_shareholder` | `(symbol, start_date="", end_date="", tradable_holder=False)` |
| `stk_get_share_change` | `(symbol, start_date="", end_date="")` |

### 龙虎榜（付费）
| 函数 | 签名 |
|---|---|
| `stk_abnor_change_stocks` | `(symbols=None, change_types=None, trade_date=None, fields=None, df=False)` |
| `stk_abnor_change_detail` | `(symbols=None, change_types=None, trade_date=None, fields=None, df=False)` |

### 沪深港通 / 北向资金（付费）
| 函数 | 签名 |
|---|---|
| `stk_quota_shszhk_infos` | `(types=None, start_date=None, end_date=None, count=None, df=False)` |
| `stk_hk_inst_holding_detail_info` | `(symbols=None, trade_date=None, df=False)` |
| `stk_hk_inst_holding_info` | `(symbols=None, trade_date=None, df=False)` |
| `stk_active_stock_top10_shszhk_info` | `(types=None, trade_date=None, df=False)` — types=`SHHK`/`SZHK`/`HKSH`/`HKSZ` |

### 资金流向 / 业绩预告 / 集合竞价（付费）
| 函数 | 签名 |
|---|---|
| `stk_get_money_flow` | `(symbols, trade_date=None)` |
| `stk_get_finance_audit` | `(symbols, date=None, rpt_date=None, df=False)` — 审计意见 |
| `stk_get_finance_forecast` | `(symbols, rpt_type=None, date=None, df=False)` — 业绩预告 |
| `get_open_call_auction` | `(symbols, trade_date=None)` — 集合竞价开盘成交 |
