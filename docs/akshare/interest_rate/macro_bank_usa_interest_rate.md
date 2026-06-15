# `macro_bank_usa_interest_rate`

**描述**: 美联储利率决议报告, 数据区间从 19820927-至今

**目标地址**: <https://datacenter.jin10.com/reportType/dc_usa_interest_rate_decision>

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
macro_bank_usa_interest_rate_df = ak.macro_bank_usa_interest_rate()
print(macro_bank_usa_interest_rate_df)
```

## 数据示例

```text
 商品 日期 今值 预测值 前值
0 美联储利率决议报告 1982-09-28 10.25 NaN NaN
1 美联储利率决议报告 1982-10-02 10.00 NaN 10.25
2 美联储利率决议报告 1982-10-08 9.50 NaN 10.00
3 美联储利率决议报告 1982-11-20 9.00 NaN 9.50
4 美联储利率决议报告 1982-12-15 8.50 NaN 9.00
.. ... ... ... ... ...
282 美联储利率决议报告 2024-06-13 5.50 5.50 5.50
283 美联储利率决议报告 2024-08-01 5.50 5.50 5.50
284 美联储利率决议报告 2024-09-19 5.00 5.25 5.50
285 美联储利率决议报告 2024-11-08 NaN 4.75 5.00
286 美联储利率决议报告 2024-12-19 NaN NaN NaN
[287 rows x 5 columns]
欧洲央行决议报告
```
