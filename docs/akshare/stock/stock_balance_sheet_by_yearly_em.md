# `stock_balance_sheet_by_yearly_em`

**描述**: 东方财富-股票-财务分析-资产负债表-按年度

**目标地址**: <https://emweb.securities.eastmoney.com/PC_HSF10/NewFinanceAnalysis/Index?type=web&code=sh600519#lrb-0>

**限量**: 单次获取指定 symbol 的资产负债表-按年度数据


## 输入参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| symbol | str | symbol="SH600519"; 股票代码 |

## 输出参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| - | - | 319 项，不逐一列出 |

## 接口示例

```python
import akshare as ak
stock_balance_sheet_by_yearly_em_df = ak.stock_balance_sheet_by_yearly_em(symbol="SH600519")
print(stock_balance_sheet_by_yearly_em_df)
```

## 数据示例

```text
 SECUCODE SECURITY_CODE ... OSOPINION_TYPE LISTING_STATE
0 600519.SH 600519 ... None 0
1 600519.SH 600519 ... None 0
2 600519.SH 600519 ... None 0
3 600519.SH 600519 ... None 0
4 600519.SH 600519 ... None 0
5 600519.SH 600519 ... None 0
6 600519.SH 600519 ... None 0
7 600519.SH 600519 ... None 0
8 600519.SH 600519 ... None 0
9 600519.SH 600519 ... None 0
10 600519.SH 600519 ... None 0
11 600519.SH 600519 ... None 0
12 600519.SH 600519 ... None 0
13 600519.SH 600519 ... None 0
14 600519.SH 600519 ... None 0
15 600519.SH 600519 ... None 0
16 600519.SH 600519 ... None 0
17 600519.SH 600519 ... None 0
18 600519.SH 600519 ... None 0
19 600519.SH 600519 ... None 0
20 600519.SH 600519 ... None 0
21 600519.SH 600519 ... None 0
22 600519.SH 600519 ... None 0
23 600519.SH 600519 ... None 0
24 600519.SH 600519 ... None 0
[25 rows x 319 columns]
利润表-按报告期
```
