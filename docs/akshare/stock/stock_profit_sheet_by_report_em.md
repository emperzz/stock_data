# `stock_profit_sheet_by_report_em`

**描述**: 东方财富-股票-财务分析-利润表-报告期

**目标地址**: <https://emweb.securities.eastmoney.com/PC_HSF10/NewFinanceAnalysis/Index?type=web&code=sh600519#lrb-0>

**限量**: 单次获取指定 symbol 的利润表-报告期数据


## 输入参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| symbol | str | symbol="SH600519"; 股票代码 |

## 输出参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| - | - | 203 项，不逐一列出 |

## 接口示例

```python
import akshare as ak
stock_profit_sheet_by_report_em_df = ak.stock_profit_sheet_by_report_em(symbol="SH600519")
print(stock_profit_sheet_by_report_em_df)
```

## 数据示例

```text
 SECUCODE SECURITY_CODE ... ACF_END_INCOME_YOY OPINION_TYPE
0 600519.SH 600519 ... None None
1 600519.SH 600519 ... None None
2 600519.SH 600519 ... None None
3 600519.SH 600519 ... None 标准无保留意见
4 600519.SH 600519 ... None None
.. ... ... ... ... ...
87 600519.SH 600519 ... None 标准无保留意见
88 600519.SH 600519 ... None 标准无保留意见
89 600519.SH 600519 ... None 标准无保留意见
90 600519.SH 600519 ... None 标准无保留意见
91 600519.SH 600519 ... None 标准无保留意见
[92 rows x 203 columns]
利润表-按年度
```
