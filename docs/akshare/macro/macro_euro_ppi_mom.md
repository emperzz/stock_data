# `macro_euro_ppi_mom`

**描述**: 欧元区 PPI 月率报告, 数据区间从 19810301-至今

**目标地址**: <https://datacenter.jin10.com/reportType/dc_eurozone_ppi_mom>

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
macro_euro_ppi_mom_df = ak.macro_euro_ppi_mom()
print(macro_euro_ppi_mom_df)
```

## 数据示例

```text
 商品 日期 今值 预测值 前值
0 欧元区PPI月率 1981-03-01 1.0 NaN NaN
1 欧元区PPI月率 1981-04-01 0.7 NaN 1.0
2 欧元区PPI月率 1981-05-01 1.5 NaN 0.7
3 欧元区PPI月率 1981-06-01 0.7 NaN 1.5
4 欧元区PPI月率 1981-07-01 0.6 NaN 0.7
.. ... ... ... ... ...
499 欧元区PPI月率 2022-07-04 0.7 1.0 1.2
500 欧元区PPI月率 2022-08-03 1.1 1.0 0.5
501 欧元区PPI月率 2022-09-02 4.0 2.5 1.3
502 欧元区PPI月率 2022-10-04 5.0 4.9 4.0
503 欧元区PPI月率 2022-11-04 NaN 1.7 5.0
欧元区零售销售月率报告
```
