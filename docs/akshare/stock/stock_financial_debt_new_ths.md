# `stock_financial_debt_new_ths`

**描述**: 同花顺-财务指标-资产负债表；替换 stock_financial_debt_ths 接口

**目标地址**: <https://basic.10jqka.com.cn/astockpc/astockmain/index.html#/financen?code=000063>

**限量**: 单次获取资产负债表所有历史数据


## 输入参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| symbol | str | symbol="000063"; 股票代码 |
| indicator | str | indicator="按报告期"; choice of {"按报告期", "按年度"} |

## 输出参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| report_date | object | - |
| report_name | object | - |
| report_period | object | - |
| quarter_name | object | - |
| metric_name | object | - |
| value | float64 | - |
| single | object | - |
| yoy | float64 | - |
| mom | object | - |
| single_yoy | object | - |

## 接口示例

```python
import akshare as ak
stock_financial_debt_new_ths_df = ak.stock_financial_debt_new_ths(symbol="000063", indicator="按年度")
print(stock_financial_debt_new_ths_df)
```

## 数据示例

```text
 report_date report_name report_period ... yoy mom single_yoy
0 2024-12-31 2024年报 2024-4 ... <NA> <NA> <NA>
1 2024-12-31 2024年报 2024-4 ... <NA> <NA> <NA>
2 2024-12-31 2024年报 2024-4 ... 0.16420728 <NA> <NA>
3 2024-12-31 2024年报 2024-4 ... -0.15807123 <NA> <NA>
4 2024-12-31 2024年报 2024-4 ... 0.00005916 <NA> <NA>
... ... ... ... ... ... ... ...
3684 1994-12-31 1994年报 1994-4 ... <NA> <NA> <NA>
3685 1994-12-31 1994年报 1994-4 ... <NA> <NA> <NA>
3686 1994-12-31 1994年报 1994-4 ... <NA> <NA> <NA>
3687 1994-12-31 1994年报 1994-4 ... <NA> <NA> <NA>
3688 1994-12-31 1994年报 1994-4 ... <NA> <NA> <NA>
[3689 rows x 10 columns]
利润表
```
