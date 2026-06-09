# 通用数据函数（免费） — 原始

> 抓自 `https://www.myquant.cn/docs2/sdk/python/API介绍/通用数据函数（免费）.html`
>
> 所有函数标注「掘金公版（体验版/专业版/机构版）函数，券商版以升级提示为准」——即免费版本即可使用，券商版可能需要升级。

## 函数清单

| 函数 | 说明 | 备注 |
|---|---|---|
| `get_symbol_infos` | 查询标的基本信息（与时间无关） | 必填 sec_type1；返回标的代码、名称、上市日、最小变动单位等 |
| `get_symbols` | 查询指定交易日多标的交易信息 | 含 is_suspended/is_st/涨跌停价/换手率/复权因子 |
| `get_history_symbol` | 查询指定标的多日交易信息 | 历史每日的涨跌停价、复权因子、ST 状态等 |
| `get_trading_dates_by_year` | 查询年度交易日历 | 返回 date / trade_date / next_trade_date / pre_trade_date |
| `get_previous_n_trading_dates` | 查询指定日期的前 n 个交易日 | 3.0.163+ |
| `get_next_n_trading_dates` | 查询指定日期的后 n 个交易日 | 3.0.163+ |
| `get_trading_session` | 查询交易时段 | 含连续竞价 + 集合竞价时段 |
| `get_contract_expire_rest_days` | 查询合约到期剩余天数 | 期货/期权/可转债 |

## # get_symbol_infos - 查询标的基本信息

```
get_symbol_infos(sec_type1, sec_type2=None, exchanges=None, symbols=None, df=False)
```

| 参数名 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| sec_type1 | int | Y | 无 | 证券大类。1010=股票, 1020=基金, 1030=债券, 1040=期货, 1050=期权, 1060=指数, 1070=板块 |
| sec_type2 | int | N | None | 证券细类。股票：101001=A股，101002=B股，101003=存托凭证。基金：102001=ETF，102002=LOF，102005=FOF，102009=基础设施 REITs。债券：103001=可转债，103008=回购。指数：106001=股票指数 等 |
| exchanges | str/list | N | None | 交易所代码。SHSE/SZSE/CFFEX/SHFE/DCE/CZCE/INE/GFEX |
| symbols | str/list | N | None | 标的代码 |
| df | bool | N | False | True 返回 DataFrame |

返回字段（股票相关）：symbol, sec_type1, sec_type2, board, exchange, sec_id, sec_name, sec_abbr, price_tick, trade_n（0=T+0/1=T+1/2=T+2）, listed_date, delisted_date, delisting_begin_date（退市整理开始日）。

`board` 取值：A 股 10100101=主板A股，10100102=创业板，10100103=科创板，10100104=北交所股票。ETF 10200101=股票ETF / 10200102=债券ETF / 10200103=商品ETF / 10200104=跨境ETF / 10200105=货币ETF。

## # get_symbols - 查询指定交易日多标的交易信息

```
get_symbols(sec_type1, sec_type2=None, exchanges=None, symbols=None,
            skip_suspended=True, skip_st=True, trade_date=None, df=False)
```

- 必填 sec_type1
- `skip_suspended` 默认跳过停牌；`skip_st` 默认跳过 ST/*ST/SST/S*ST
- `trade_date` 默认 None 取最新截面（含退市标的）

股票相关返回字段：trade_date, symbol, board, exchange, sec_id, sec_name, sec_abbr, price_tick, listed_date, delisted_date, is_suspended, is_st, pre_close, upper_limit, lower_limit, turn_rate, adj_factor, delisting_begin_date。

注意：可转债到期日 = delisted_date，转股价值 = (100/可转债转股价) × 股价。

## # get_history_symbol - 查询指定标的多日交易信息

```
get_history_symbol(symbol=None, start_date=None, end_date=None, df=False)
```

- 只支持单个 symbol
- 返回字段与 get_symbols 相同，按 trade_date 升序
- 停牌且发生除权除息时涨跌停价可能有误差
- start_date > end_date 时报错

## # 交易日历相关

### get_trading_dates_by_year(exchange, start_year, end_year)
返回 DataFrame：date / trade_date（非交易日为''）/ next_trade_date / pre_trade_date。

### get_previous_n_trading_dates(exchange, date, n=1)  ⓘ gm SDK 3.0.163+
返回前 n 个交易日字符串列表，不含 date 自身。

### get_next_n_trading_dates(exchange, date, n=1)  ⓘ gm SDK 3.0.163+
返回后 n 个交易日字符串列表，不含 date 自身。

## # get_trading_session - 查询交易时段

```
get_trading_session(symbols, df=False)
```

返回 `time_trading`（连续竞价时段列表）和 `time_auction`（集合竞价时段列表）。

## # get_contract_expire_rest_days - 查询合约到期剩余天数

```
get_contract_expire_rest_days(symbols, start_date=None, end_date=None, trade_flag=False, df=False)
```

- `trade_flag=False`（默认）按自然日；`True` 按交易日
- 到期日当天 days_to_expire=0；负数表示已过到期日
