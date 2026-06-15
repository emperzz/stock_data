# `migration_area_baidu`

**描述**: 百度-百度地图慧眼-百度迁徙-迁入/迁出地数据接口

**目标地址**: <https://qianxi.baidu.com/?from=shoubai#city=0>

**限量**: 单次返回前 100 个城市的数据


## 输入参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| area | str | area="乌鲁木齐市", 输入需要查询的省份或者城市, 都需要用全称, 比如: "浙江省", "乌鲁木齐市" |
| indicator | str | indicator="move_in", 返回迁入地详情, indicator="move_out", 返回迁出地详情 |
| date | str | date="20230922", 需要滞后一天 |

## 输出参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| city_name | object | 城市名称 |
| province_name | object | 所属省份 |
| value | float64 | 迁徙规模, 比例 |

## 接口示例

```python
import akshare as ak
migration_area_baidu_df = ak.migration_area_baidu(area="重庆市", indicator="move_in", date="20230922")
print(migration_area_baidu_df)
```

## 数据示例

```text
 city_name province_name value
0 苏州市 江苏省 24.43
1 嘉兴市 浙江省 6.46
2 杭州市 浙江省 5.09
3 南通市 江苏省 4.94
4 无锡市 江苏省 3.90
.. ... ... ...
95 淄博市 山东省 0.10
96 恩施土家族苗族自治州 湖北省 0.10
97 惠州市 广东省 0.10
98 汕头市 广东省 0.10
99 大理白族自治州 云南省 0.10
[100 rows x 3 columns]
迁徙规模
```
