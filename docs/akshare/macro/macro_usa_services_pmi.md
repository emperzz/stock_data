# `macro_usa_services_pmi`

**描述**: 美国Markit服务业PMI初值报告, 数据区间从 20120701-至今

**目标地址**: <https://datacenter.jin10.com/reportType/dc_usa_services_pmi>

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
macro_usa_services_pmi_df = ak.macro_usa_services_pmi()
print(macro_usa_services_pmi_df)
```

## 数据示例

```text
 商品 日期 今值 预测值 前值
0 美国Markit服务业PMI初值报告 2012-07-01 53.2 NaN NaN
1 美国Markit服务业PMI初值报告 2012-08-01 51.2 NaN 53.2
2 美国Markit服务业PMI初值报告 2012-09-01 52.0 NaN 51.2
3 美国Markit服务业PMI初值报告 2012-10-01 50.7 NaN 52.0
4 美国Markit服务业PMI初值报告 2012-11-01 52.7 NaN 50.7
.. ... ... ... ... ...
262 美国Markit服务业PMI初值报告 2024-02-22 51.3 52.4 52.5
263 美国Markit服务业PMI初值报告 2024-03-05 52.3 51.3 52.5
264 美国Markit服务业PMI初值报告 2024-03-21 51.7 52.0 52.3
265 美国Markit服务业PMI初值报告 2024-04-03 51.7 51.7 52.3
266 美国Markit服务业PMI初值报告 2024-04-23 NaN NaN 51.7
[267 rows x 5 columns]
美国商业库存月率报告
```
