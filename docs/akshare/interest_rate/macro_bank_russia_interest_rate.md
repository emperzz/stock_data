# `macro_bank_russia_interest_rate`

**描述**: 俄罗斯利率决议报告, 数据区间从 20030601-至今

**目标地址**: <https://datacenter.jin10.com/reportType/dc_russia_interest_rate_decision>

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
macro_bank_russia_interest_rate_df = ak.macro_bank_russia_interest_rate()
print(macro_bank_russia_interest_rate_df)
```

## 数据示例

```text
 商品 日期 今值 预测值 前值
0 俄罗斯央行决议报告 2003-06-01 6.5 NaN NaN
1 俄罗斯央行决议报告 2003-07-01 6.5 NaN 6.5
2 俄罗斯央行决议报告 2003-08-01 6.5 NaN 6.5
3 俄罗斯央行决议报告 2003-09-01 6.5 NaN 6.5
4 俄罗斯央行决议报告 2003-10-01 6.5 NaN 6.5
.. ... ... ... ... ...
214 俄罗斯央行决议报告 2024-04-26 16.0 16.0 16.0
215 俄罗斯央行决议报告 2024-06-07 16.0 16.0 16.0
216 俄罗斯央行决议报告 2024-07-26 18.0 18.0 16.0
217 俄罗斯央行决议报告 2024-09-13 19.0 18.0 18.0
218 俄罗斯央行决议报告 2024-10-25 21.0 20.0 19.0
[219 rows x 5 columns]
印度利率决议报告
```
