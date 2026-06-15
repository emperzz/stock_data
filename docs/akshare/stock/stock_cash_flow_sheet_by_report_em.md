# `stock_cash_flow_sheet_by_report_em`

**描述**: 东方财富-股票-财务分析-现金流量表-按报告期

**目标地址**: <https://emweb.securities.eastmoney.com/PC_HSF10/NewFinanceAnalysis/Index?type=web&code=sh600519#lrb-0>

**限量**: 单次获取指定 symbol 的现金流量表-按报告期数据


## 输入参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| symbol | str | symbol="SH600519"; 股票代码 |

## 输出参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| - | - | 252 项，不逐一列出 |

## 接口示例

```python
import akshare as ak
stock_cash_flow_sheet_by_report_em_df = ak.stock_cash_flow_sheet_by_report_em(symbol="SH600519")
print(stock_cash_flow_sheet_by_report_em_df)
```

## 数据示例

```text
 SECUCODE SECURITY_CODE ... MINORITY_INTEREST MINORITY_INTEREST_YOY
0 600519.SH 600519 ... NaN NaN
1 600519.SH 600519 ... NaN NaN
2 600519.SH 600519 ... NaN NaN
3 600519.SH 600519 ... NaN NaN
4 600519.SH 600519 ... NaN NaN
.. ... ... ... ... ...
83 600519.SH 600519 ... NaN NaN
84 600519.SH 600519 ... NaN NaN
85 600519.SH 600519 ... NaN NaN
86 600519.SH 600519 ... NaN NaN
87 600519.SH 600519 ... NaN NaN
[88 rows x 252 columns]
现金流量表-按年度
```
