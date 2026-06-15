# `macro_usa_industrial_production`

**描述**: 美国工业产出月率报告, 数据区间从 19700101-至今

**目标地址**: <https://datacenter.jin10.com/reportType/dc_usa_industrial_production>

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
macro_usa_industrial_production_df = ak.macro_usa_industrial_production()
print(macro_usa_industrial_production_df)
```

## 数据示例

```text
 商品 日期 今值 预测值 前值
0 美国工业产出月率报告 1970-01-01 -0.3 NaN NaN
1 美国工业产出月率报告 1970-02-01 -1.9 NaN -0.3
2 美国工业产出月率报告 1970-03-01 -0.1 NaN -1.9
3 美国工业产出月率报告 1970-04-01 -0.1 NaN -0.1
4 美国工业产出月率报告 1970-05-01 -0.3 NaN -0.1
.. ... ... ... ... ...
647 美国工业产出月率报告 2023-12-15 0.2 0.3 -0.9
648 美国工业产出月率报告 2024-01-17 0.1 0.0 0.0
649 美国工业产出月率报告 2024-02-15 -0.1 0.2 0.1
650 美国工业产出月率报告 2024-03-15 0.1 0.0 -0.5
651 美国工业产出月率报告 2024-04-16 NaN NaN 0.1
[652 rows x 5 columns]
美国耐用品订单月率报告
```
