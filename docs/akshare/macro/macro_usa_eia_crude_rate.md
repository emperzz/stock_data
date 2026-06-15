# `macro_usa_eia_crude_rate`

**描述**: 美国EIA原油库存报告, 数据区间从 19950801-至今

**目标地址**: <https://cdn.jin10.com/dc/reports/dc_usa_michigan_consumer_sentiment_all.js?v=1578576228>

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
| 今值 | float64 | 注意单位: 万桶 |
| 预测值 | float64 | 注意单位: 万桶 |
| 前值 | float64 | 注意单位: 万桶 |

## 接口示例

```python
import akshare as ak
macro_usa_eia_crude_rate_df = ak.macro_usa_eia_crude_rate()
print(macro_usa_eia_crude_rate_df)
```

## 数据示例

```text
 商品 日期 今值 预测值 前值
0 美国EIA原油库存 1982-09-01 -263.0 NaN NaN
1 美国EIA原油库存 1982-10-01 -8.0 NaN -263.0
2 美国EIA原油库存 1982-11-01 -41.0 NaN -8.0
3 美国EIA原油库存 1982-12-01 -88.0 NaN -41.0
4 美国EIA原油库存 1983-01-01 51.0 NaN -88.0
 ... ... ... ... ...
1147 美国EIA原油库存 2024-03-13 -153.6 90.0 136.7
1148 美国EIA原油库存 2024-03-20 -195.2 -90.0 -153.6
1149 美国EIA原油库存 2024-03-27 316.5 -70.0 -195.2
1150 美国EIA原油库存 2024-04-03 321.0 -30.0 316.5
1151 美国EIA原油库存 2024-04-10 NaN NaN 321.0
[1152 rows x 5 columns]
美国初请失业金人数报告
```
