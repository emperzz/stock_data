# `migration_scale_baidu`

**描述**: 百度-百度地图慧眼-百度迁徙-迁徙规模

**目标地址**: <https://qianxi.baidu.com/?from=shoubai#city=0>


## 输入参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| area | str | area="广州市", 输入需要查询的省份或者城市, 都需要用全称, 比如: "浙江省", "乌鲁木齐市" |
| indicator | str | indicator="move_in", 返回迁入地详情, indicator="move_out", 返回迁出地详情 |

## 输出参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| 日期 | object | - |
| 迁徙规模指数 | float64 | 定义参见百度 |

## 接口示例

```python
import akshare as ak
migration_scale_baidu_df = ak.migration_scale_baidu(area="广州市", indicator="move_in")
print(migration_scale_baidu_df)
```

## 数据示例

```text
 日期 迁徙规模指数
0 2019-01-12 8.413535
1 2019-01-13 7.877218
2 2019-01-14 8.920660
3 2019-01-15 7.426858
4 2019-01-16 7.339183
 ... ...
1100 2023-09-18 13.620539
1101 2023-09-19 9.761666
1102 2023-09-20 9.755867
1103 2023-09-21 10.397938
1104 2023-09-22 10.492319
[1105 rows x 2 columns]
```
