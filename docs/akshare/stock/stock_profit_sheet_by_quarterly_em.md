# `stock_profit_sheet_by_quarterly_em`

**描述**: 东方财富-股票-财务分析-利润表-按单季度

**目标地址**: <https://emweb.securities.eastmoney.com/PC_HSF10/NewFinanceAnalysis/Index?type=web&code=sh600519#lrb-0>

**限量**: 单次获取指定 symbol 的利润表-按单季度数据


## 输入参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| symbol | str | symbol="SH600519"; 股票代码 |

## 输出参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| - | - | 204 项，不逐一列出 |

## 接口示例

```python
import akshare as ak
stock_profit_sheet_by_quarterly_em_df = ak.stock_profit_sheet_by_quarterly_em(symbol="SH600519")
print(stock_profit_sheet_by_quarterly_em_df)
```

## 数据示例

```text
 SECUCODE SECURITY_CODE ... DEDUCT_PARENT_NETPROFIT DEDUCT_PARENT_NETPROFIT_QOQ
0 600519.SH 600519 ... 1.686819e+10 11.201931
1 600519.SH 600519 ... 1.516897e+10 -26.996696
2 600519.SH 600519 ... 2.077848e+10 12.934838
3 600519.SH 600519 ... 1.839864e+10 25.756158
4 600519.SH 600519 ... 1.463041e+10 16.858574
.. ... ... ... ... ...
82 600519.SH 600519 ... NaN NaN
83 600519.SH 600519 ... 6.878058e+07 -3.336461
84 600519.SH 600519 ... 7.115463e+07 NaN
85 600519.SH 600519 ... NaN NaN
86 600519.SH 600519 ... NaN NaN
[87 rows x 204 columns]
现金流量表-按报告期
```
