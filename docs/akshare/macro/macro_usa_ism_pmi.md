# `macro_usa_ism_pmi`

**描述**: 美国 ISM 制造业 PMI 报告, 数据区间从 19700101-至今

**目标地址**: <https://datacenter.jin10.com/reportType/dc_usa_ism_pmi>

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
macro_usa_ism_pmi_df = ak.macro_usa_ism_pmi()
print(macro_usa_ism_pmi_df)
```

## 数据示例

```text
 商品 日期 今值 预测值 前值
0 美国ISM制造业PMI报告 1970-01-01 52.0 NaN NaN
1 美国ISM制造业PMI报告 1970-02-01 48.7 NaN 52.0
2 美国ISM制造业PMI报告 1970-03-01 47.4 NaN 48.7
3 美国ISM制造业PMI报告 1970-04-01 46.9 NaN 47.4
4 美国ISM制造业PMI报告 1970-05-01 45.0 NaN 46.9
.. ... ... ... ... ...
648 美国ISM制造业PMI报告 2023-12-01 46.7 47.6 46.7
649 美国ISM制造业PMI报告 2024-01-03 47.4 47.1 46.7
650 美国ISM制造业PMI报告 2024-02-01 49.1 47.2 47.1
651 美国ISM制造业PMI报告 2024-03-01 47.8 49.5 49.1
652 美国ISM制造业PMI报告 2024-04-01 50.3 48.5 47.8
[653 rows x 5 columns]
工业
美国工业产出月率报告
```
