# `macro_usa_ism_non_pmi`

**描述**: 美国 ISM 非制造业 PMI 报告, 数据区间从 19970801-至今

**目标地址**: <https://datacenter.jin10.com/reportType/dc_usa_ism_non_pmi>

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
| 今值 | float64 | - |
| 预测值 | float64 | - |
| 前值 | float64 | - |

## 接口示例

```python
import akshare as ak
macro_usa_ism_non_pmi_df = ak.macro_usa_ism_non_pmi()
print(macro_usa_ism_non_pmi_df)
```

## 数据示例

```text
 商品 日期 今值 预测值 前值
0 美国ISM非制造业PMI报告 1997-08-01 56.7 NaN NaN
1 美国ISM非制造业PMI报告 1997-09-01 62.0 NaN 56.7
2 美国ISM非制造业PMI报告 1997-10-01 56.2 NaN 62.0
3 美国ISM非制造业PMI报告 1997-11-01 56.6 NaN 56.2
4 美国ISM非制造业PMI报告 1997-12-01 58.5 NaN 56.6
.. ... ... ... ... ...
319 美国ISM非制造业PMI报告 2023-12-05 52.7 52.0 51.8
320 美国ISM非制造业PMI报告 2024-01-05 50.6 52.6 52.7
321 美国ISM非制造业PMI报告 2024-02-05 53.4 52.0 50.5
322 美国ISM非制造业PMI报告 2024-03-05 52.6 53.0 53.4
323 美国ISM非制造业PMI报告 2024-04-03 51.4 52.8 52.6
[324 rows x 5 columns]
房地产
美国NAHB房产市场指数报告
```
