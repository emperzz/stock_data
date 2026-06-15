# `macro_usa_house_price_index`

**描述**: 美国 FHFA 房价指数月率报告, 数据区间从 19910301-至今

**目标地址**: <https://datacenter.jin10.com/reportType/dc_usa_house_price_index>

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
macro_usa_house_price_index_df = ak.macro_usa_house_price_index()
print(macro_usa_house_price_index_df)
```

## 数据示例

```text
 商品 日期 今值 预测值 前值
0 美国FHFA房价指数月率报告 1991-03-01 0.5 NaN NaN
1 美国FHFA房价指数月率报告 1991-04-01 0.0 NaN 0.5
2 美国FHFA房价指数月率报告 1991-05-01 -0.2 NaN 0.0
3 美国FHFA房价指数月率报告 1991-06-01 0.1 NaN -0.2
4 美国FHFA房价指数月率报告 1991-07-01 0.1 NaN 0.1
.. ... ... ... ... ...
392 美国FHFA房价指数月率报告 2023-11-28 0.6 0.4 0.7
393 美国FHFA房价指数月率报告 2023-12-26 0.3 0.5 0.7
394 美国FHFA房价指数月率报告 2024-01-30 0.3 0.2 0.3
395 美国FHFA房价指数月率报告 2024-02-27 0.1 0.3 0.4
396 美国FHFA房价指数月率报告 2024-03-26 -0.1 0.2 0.1
[397 rows x 5 columns]
美国S&P/CS20座大城市房价指数年率报告
```
