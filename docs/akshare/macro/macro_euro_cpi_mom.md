# `macro_euro_cpi_mom`

**描述**: 欧元区 CPI 月率报告, 数据区间从 19900301-至今

**目标地址**: <https://datacenter.jin10.com/reportType/dc_eurozone_cpi_mom>

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
macro_euro_cpi_mom_df = ak.macro_euro_cpi_mom()
print(macro_euro_cpi_mom_df)
```

## 数据示例

```text
 商品 日期 今值 预测值 前值
0 欧元区CPI月率 1990-03-01 0.4 NaN NaN
1 欧元区CPI月率 1990-04-01 0.2 NaN 0.4
2 欧元区CPI月率 1990-05-01 0.4 NaN 0.2
3 欧元区CPI月率 1990-06-01 0.2 NaN 0.4
4 欧元区CPI月率 1990-07-01 0.1 NaN 0.2
.. ... ... ... ... ...
421 欧元区CPI月率 2022-09-16 0.6 0.5 0.1
422 欧元区CPI月率 2022-09-30 1.2 0.9 0.6
423 欧元区CPI月率 2022-10-19 1.2 1.2 0.6
424 欧元区CPI月率 2022-10-31 1.5 NaN 1.2
425 欧元区CPI月率 2022-11-17 NaN 1.2 1.2
欧元区CPI年率报告
```
