# `macro_china_cpi_monthly`

**描述**: 中国月度 CPI 数据, 数据区间从 19960201-至今

**目标地址**: <https://datacenter.jin10.com/reportType/dc_chinese_cpi_mom>

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
macro_china_cpi_monthly_df = ak.macro_china_cpi_monthly()
print(macro_china_cpi_monthly_df)
```

## 数据示例

```text
 商品 日期 今值 预测值 前值
0 中国CPI月率报告 1996-02-01 2.1 NaN NaN
1 中国CPI月率报告 1996-03-01 2.3 NaN 2.1
2 中国CPI月率报告 1996-04-01 0.6 NaN 2.3
3 中国CPI月率报告 1996-05-01 0.7 NaN 0.6
4 中国CPI月率报告 1996-06-01 -0.5 NaN 0.7
.. ... ... ... ... ...
334 中国CPI月率报告 2023-12-09 -0.5 -0.1 -0.1
335 中国CPI月率报告 2024-01-12 0.1 0.2 -0.5
336 中国CPI月率报告 2024-02-08 0.3 0.4 0.1
337 中国CPI月率报告 2024-03-09 1.0 0.7 0.3
338 中国CPI月率报告 2024-04-11 NaN NaN 1.0
[339 rows x 5 columns]
中国 PPI 年率报告
```
