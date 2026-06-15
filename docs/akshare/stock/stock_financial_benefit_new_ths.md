# `stock_financial_benefit_new_ths`

**描述**: 同花顺-财务指标-利润表；替换 stock_financial_benefit_ths 接口

**目标地址**: <https://basic.10jqka.com.cn/astockpc/astockmain/index.html#/financen?code=000063>

**限量**: 单次获取利润表所有历史数据


## 输入参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| symbol | str | symbol="000063"; 股票代码 |
| indicator | str | indicator="按报告期"; choice of {"按报告期", "一季度", "二季度", "三季度", "四季度", "按年度"} |

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
stock_financial_benefit_new_ths_df = ak.stock_financial_benefit_new_ths(symbol="000063", indicator="按报告期")
print(stock_financial_benefit_new_ths_df)
```

## 数据示例

```text
 report_date report_name report_period ... yoy mom single_yoy
0 2025-09-30 2025三季报 2025-3 ... -0.307496 -0.912701 -0.893714
1 2025-09-30 2025三季报 2025-3 ... NaN NaN NaN
2 2025-09-30 2025三季报 2025-3 ... 0.116943 -0.221946 -0.139571
3 2025-09-30 2025三季报 2025-3 ... NaN NaN NaN
4 2025-09-30 2025三季报 2025-3 ... NaN NaN NaN
... ... ... ... ... ... ... ...
2545 2013-06-30 2013中报 2013-2 ... 0.285714 -0.500000 0.000000
2546 2013-06-30 2013中报 2013-2 ... NaN NaN NaN
2547 2013-06-30 2013中报 2013-2 ... NaN NaN NaN
2548 2013-06-30 2013中报 2013-2 ... NaN NaN NaN
2549 2013-06-30 2013中报 2013-2 ... -11.669821 0.777595 0.078450
[2550 rows x 10 columns]
现金流量表
```
