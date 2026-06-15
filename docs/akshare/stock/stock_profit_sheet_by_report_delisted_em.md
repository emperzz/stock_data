# `stock_profit_sheet_by_report_delisted_em`

**描述**: 东方财富-股票-财务分析-利润表-已退市股票-按报告期

**目标地址**: <https://emweb.securities.eastmoney.com/pc_hsf10/pages/index.html?type=web&code=SZ000013#/cwfx/lrb>

**限量**: 单次获取指定 symbol 的利润表-按报告期数据


## 输入参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| symbol | str | symbol="SZ000013"; 带市场标识的已退市股票代码 |

## 输出参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| - | - | 203 项，不逐一列出 |

## 接口示例

```python
import akshare as ak
stock_profit_sheet_by_report_delisted_em_df = ak.stock_profit_sheet_by_report_delisted_em(symbol="SZ000013")
print(stock_profit_sheet_by_report_delisted_em_df)
```

## 数据示例

```text
 SECUCODE SECURITY_CODE ... ACF_END_INCOME_YOY OPINION_TYPE
0 000013.SZ 000013 ... None None
1 000013.SZ 000013 ... None None
2 000013.SZ 000013 ... None None
3 000013.SZ 000013 ... None None
4 000013.SZ 000013 ... None None
5 000013.SZ 000013 ... None None
6 000013.SZ 000013 ... None None
7 000013.SZ 000013 ... None None
8 000013.SZ 000013 ... None None
9 000013.SZ 000013 ... None None
10 000013.SZ 000013 ... None None
11 000013.SZ 000013 ... None None
12 000013.SZ 000013 ... None None
13 000013.SZ 000013 ... None None
14 000013.SZ 000013 ... None 标准无保留意见
15 000013.SZ 000013 ... None None
16 000013.SZ 000013 ... None 带解释性说明的无保留意见
17 000013.SZ 000013 ... None None
18 000013.SZ 000013 ... None None
19 000013.SZ 000013 ... None 无法表示意见
20 000013.SZ 000013 ... None None
21 000013.SZ 000013 ... None 未经审计
22 000013.SZ 000013 ... None None
23 000013.SZ 000013 ... None 无法表示意见
24 000013.SZ 000013 ... None None
25 000013.SZ 000013 ... None 未经审计
26 000013.SZ 000013 ... None None
27 000013.SZ 000013 ... None 无法表示意见
28 000013.SZ 000013 ... None None
29 000013.SZ 000013 ... None 无法表示意见
30 000013.SZ 000013 ... None None
31 000013.SZ 000013 ... None None
32 000013.SZ 000013 ... None None
33 000013.SZ 000013 ... None None
34 000013.SZ 000013 ... None None
35 000013.SZ 000013 ... None None
36 000013.SZ 000013 ... None None
37 000013.SZ 000013 ... None None
38 000013.SZ 000013 ... None None
[39 rows x 203 columns]
现金流量表-按报告期
```
