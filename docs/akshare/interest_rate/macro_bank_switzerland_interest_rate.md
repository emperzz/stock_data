# `macro_bank_switzerland_interest_rate`

**描述**: 瑞士央行利率决议报告, 数据区间从 20080313-至今

**目标地址**: <https://datacenter.jin10.com/reportType/dc_switzerland_interest_rate_decision>

**限量**: 单次返回所有历史数据


## 输入参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| - | - | - |

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
macro_bank_switzerland_interest_rate_df = ak.macro_bank_switzerland_interest_rate()
print(macro_bank_switzerland_interest_rate_df)
```

## 数据示例

```text
 商品 日期 今值 预测值 前值
0 瑞士央行决议报告 2008-03-13 2.75 2.75 2.75
1 瑞士央行决议报告 2008-06-19 2.75 2.75 2.75
2 瑞士央行决议报告 2008-09-18 2.75 2.75 2.75
3 瑞士央行决议报告 2008-10-08 2.50 NaN 2.75
4 瑞士央行决议报告 2008-12-11 0.50 0.50 1.00
.. ... ... ... ... ...
67 瑞士央行决议报告 2023-12-14 1.75 1.75 1.75
68 瑞士央行决议报告 2024-03-21 1.50 1.75 1.75
69 瑞士央行决议报告 2024-06-20 1.25 1.50 1.50
70 瑞士央行决议报告 2024-09-26 1.00 1.00 1.25
71 瑞士央行决议报告 2024-12-12 NaN NaN NaN
[72 rows x 5 columns]
英国央行决议报告
```
