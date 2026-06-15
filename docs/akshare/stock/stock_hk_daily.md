# `stock_hk_daily`

**描述**: 港股-历史行情数据, 可以选择返回复权后数据,更新频率为日频

**目标地址**: <http://stock.finance.sina.com.cn/hkstock/quotes/01336.html(个例)>

**限量**: 单次返回指定上市公司的历史行情数据(包括前后复权因子), 提供新浪财经拥有的该股票的所有数据(


## 输入参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| symbol | str | 港股代码,可以通过 ak.stock_hk_spot() 函数返回所有港股代码 |
| adjust | str | "": 返回未复权的数据 ; qfq: 返回前复权后的数据; hfq: 返回后复权后的数据; qfq-factor: 返回前复权因子和调整; hfq-factor: 返回后复权因子和调整; |

## 输出参数 - 历史行情数据(后复权)

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| date | object | 日期 |
| open | float64 | 开盘价 |
| high | float64 | 最高价 |
| low | float64 | 最低价 |
| close | float64 | 收盘价 |
| volume | float64 | 成交量 |

## 输出参数 - 历史行情数据(未复权)

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| date | object | 日期 |
| open | float64 | 开盘价 |
| high | float64 | 最高价 |
| low | float64 | 最低价 |
| close | float64 | 收盘价 |
| volume | float64 | 成交量 |

## 输出参数 - 后复权因子

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| date | object | 日期 |
| hfq_factor | object | 后复权因子 |
| cash | object | 现金分红 |

## 接口示例

```python
import akshare as ak
stock_hk_daily_hfq_factor_df = ak.stock_hk_daily(symbol="00700", adjust="hfq-factor")
print(stock_hk_daily_hfq_factor_df)
```

## 数据示例

```text
 date hfq_factor cash
0 2021-05-24 5 35.54
1 2020-05-15 5 27.54
2 2019-05-17 5 21.54
3 2018-12-28 5 16.54
4 2018-05-18 5 16.28
5 2017-05-19 5 11.88
6 2016-05-20 5 8.83
7 2015-05-15 5 6.48
8 2014-05-16 5 4.68
9 2014-05-15 5 3.48
10 2013-05-20 1 3.48
11 2012-05-18 1 2.48
12 2011-05-03 1 1.73
13 2010-05-05 1 1.18
14 2009-05-06 1 0.78
15 2008-05-06 1 0.43
16 2007-05-09 1 0.27
17 2006-05-15 1 0.15
18 2005-04-19 1 0.07
19 1900-01-01 1 0
知名港股
```
