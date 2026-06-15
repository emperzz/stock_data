# `macro_china_urban_unemployment`

**描述**: 国家统计局-月度数据-城镇调查失业率

**目标地址**: <https://data.stats.gov.cn/dg/website/page.html#/pc/national/monthData>

**限量**: 单次返回所有历史数据


## 输入参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| - | - | - |

## 输出参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| date | object | 年月 |
| item | object | - |
| value | float64 | - |

## 接口示例

```python
import akshare as ak
macro_china_urban_unemployment_df = ak.macro_china_urban_unemployment()
print(macro_china_urban_unemployment_df)
```

## 数据示例

```text
 date item value
0 201801 全国城镇25—59岁劳动力失业率 4.4
1 201801 全国城镇调查失业率 5.0
2 201802 全国城镇调查失业率 5.0
3 201802 全国城镇25—59岁劳动力失业率 4.5
4 201803 全国城镇调查失业率 5.1
.. ... ... ...
283 202601 全国城镇本地户籍劳动力失业率 5.3
284 202601 全国城镇调查失业率 5.2
285 202602 全国城镇外来户籍劳动力失业率 5.0
286 202602 全国城镇本地户籍劳动力失业率 5.4
287 202602 全国城镇调查失业率 5.3
[288 rows x 3 columns]
社会融资规模增量统计
```
