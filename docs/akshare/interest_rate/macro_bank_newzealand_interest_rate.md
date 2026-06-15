# `macro_bank_newzealand_interest_rate`

**描述**: 新西兰联储决议报告, 数据区间从 19990401-至今

**目标地址**: <https://datacenter.jin10.com/reportType/dc_newzealand_interest_rate_decision>

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
macro_bank_newzealand_interest_rate_df = ak.macro_bank_newzealand_interest_rate()
print(macro_bank_newzealand_interest_rate_df)
```

## 数据示例

```text
 商品 日期 今值 预测值 前值
0 新西兰利率决议报告 1999-04-01 4.50 NaN NaN
1 新西兰利率决议报告 1999-05-01 4.50 NaN 4.50
2 新西兰利率决议报告 1999-06-01 4.50 NaN 4.50
3 新西兰利率决议报告 1999-07-01 4.50 NaN 4.50
4 新西兰利率决议报告 1999-08-01 4.50 NaN 4.50
.. ... ... ... ... ...
230 新西兰利率决议报告 2024-05-22 5.50 5.50 5.50
231 新西兰利率决议报告 2024-07-10 5.50 5.50 5.50
232 新西兰利率决议报告 2024-08-14 5.25 5.50 5.50
233 新西兰利率决议报告 2024-10-09 4.75 4.75 5.25
234 新西兰利率决议报告 2024-11-27 NaN NaN 4.75
[235 rows x 5 columns]
中国央行决议报告
```
