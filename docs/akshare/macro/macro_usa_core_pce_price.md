# `macro_usa_core_pce_price`

**描述**: 美国核心 PCE 物价指数年率报告, 数据区间从 19700101-至今

**目标地址**: <https://datacenter.jin10.com/reportType/dc_usa_core_pce_price>

**限量**: 单次返回所有历史数据


## 输入参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| - | - - |  |

## 输出参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| 商品 | object | - |
| 日期 | object | - |
| 今值 | float64 | 注意单位: % |
| 预测值 | float64 | 注意单位: % |
| 前值 | float64 | 注意单位: % |

## 接口示例

```python
import akshare as ak
macro_usa_core_pce_price_df = ak.macro_usa_core_pce_price()
print(macro_usa_core_pce_price_df)
```

## 数据示例

```text
 商品 日期 今值 预测值 前值
0 美国核心PCE物价指数年率 1970-01-01 4.8 NaN NaN
1 美国核心PCE物价指数年率 1970-02-01 4.7 NaN 4.8
2 美国核心PCE物价指数年率 1970-03-01 4.8 NaN 4.7
3 美国核心PCE物价指数年率 1970-04-01 4.7 NaN 4.8
4 美国核心PCE物价指数年率 1970-05-01 4.7 NaN 4.7
.. ... ... ... ... ...
649 美国核心PCE物价指数年率 2023-11-30 3.5 3.5 3.7
650 美国核心PCE物价指数年率 2023-12-22 3.2 3.3 3.4
651 美国核心PCE物价指数年率 2024-01-26 2.9 3.0 3.2
652 美国核心PCE物价指数年率 2024-02-29 2.8 2.8 2.9
653 美国核心PCE物价指数年率 2024-03-29 2.8 2.8 2.9
[654 rows x 5 columns]
美国实际个人消费支出季率初值报告
```
