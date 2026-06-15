# `macro_china_hk_rate_of_unemployment`

**描述**: 东方财富-经济数据一览-中国香港-失业率

**目标地址**: <https://data.eastmoney.com/cjsj/foreign_8_2.html>

**限量**: 单次返回所有历史数据


## 输入参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| - | - | - |

## 输出参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| 时间 | object | - |
| 前值 | float64 | 注意单位: % |
| 现值 | float64 | 注意单位: % |
| 发布日期 | object | - |

## 接口示例

```python
import akshare as ak
macro_china_hk_rate_of_unemployment_df = ak.macro_china_hk_rate_of_unemployment()
print(macro_china_hk_rate_of_unemployment_df)
```

## 数据示例

```text
 时间 前值 现值 发布日期
0 2008年01月 3.4 3.4 2008-02-18
1 2008年02月 3.4 3.3 2008-03-20
2 2008年03月 3.3 3.3 2008-04-18
3 2008年04月 3.3 3.3 2008-05-19
4 2008年05月 3.3 3.3 2008-06-18
.. ... ... ... ...
190 2023年11月 2.9 2.9 2023-12-19
191 2023年12月 2.9 2.9 2024-01-18
192 2024年01月 2.9 2.9 2024-02-20
193 2024年02月 2.9 2.9 2024-03-18
194 2024年03月 2.9 NaN 2024-04-18
[195 rows x 4 columns]
GDP
```
