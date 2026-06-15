# `stock_profit_sheet_by_yearly_em`

**描述**: 东方财富-股票-财务分析-利润表-按年度

**目标地址**: <https://emweb.securities.eastmoney.com/PC_HSF10/NewFinanceAnalysis/Index?type=web&code=sh600519#lrb-0>

**限量**: 单次获取指定 symbol 的利润表-按年度数据


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
stock_profit_sheet_by_yearly_em_df = ak.stock_profit_sheet_by_yearly_em(symbol="SH600519")
print(stock_profit_sheet_by_yearly_em_df)
```

## 数据示例

```text
 SECUCODE SECURITY_CODE ... ACF_END_INCOME_YOY OPINION_TYPE
0 600519.SH 600519 ... None 标准无保留意见
1 600519.SH 600519 ... None 标准无保留意见
2 600519.SH 600519 ... None 标准无保留意见
3 600519.SH 600519 ... None 标准无保留意见
4 600519.SH 600519 ... None 标准无保留意见
5 600519.SH 600519 ... None 标准无保留意见
6 600519.SH 600519 ... None 标准无保留意见
7 600519.SH 600519 ... None 标准无保留意见
8 600519.SH 600519 ... None 标准无保留意见
9 600519.SH 600519 ... None 标准无保留意见
10 600519.SH 600519 ... None 标准无保留意见
11 600519.SH 600519 ... None 标准无保留意见
12 600519.SH 600519 ... None 标准无保留意见
13 600519.SH 600519 ... None 标准无保留意见
14 600519.SH 600519 ... None 标准无保留意见
15 600519.SH 600519 ... None 标准无保留意见
16 600519.SH 600519 ... None 标准无保留意见
17 600519.SH 600519 ... None 标准无保留意见
18 600519.SH 600519 ... None 标准无保留意见
19 600519.SH 600519 ... None 标准无保留意见
20 600519.SH 600519 ... None 标准无保留意见
21 600519.SH 600519 ... None 标准无保留意见
22 600519.SH 600519 ... None 标准无保留意见
23 600519.SH 600519 ... None 标准无保留意见
24 600519.SH 600519 ... None 标准无保留意见
[25 rows x 203 columns]
利润表-按单季度
```
