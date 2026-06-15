# `futures_hog_supply`

**描述**: 玄田数据-供应维度

**目标地址**: <https://zhujia.zhuwang.com.cn>

**限量**: 单次返回指定 symbol 的所有历史数据


## 输入参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| symbol | str | symbol="玉米"; choice of {"猪肉批发价", "储备冻猪肉", "饲料原料数据", "白条肉", "生猪产能", "育肥猪", "肉类价格指数", "猪粮比价"} |

## 输出参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| date | object | - |
| value | float64 | - |

## 接口示例

```python
import akshare as ak
futures_hog_supply_df = ak.futures_hog_supply(symbol="猪肉批发价")
print(futures_hog_supply_df)
```

## 数据示例

```text
 date value
0 2023-12-17 20.14
1 2023-12-18 20.12
2 2023-12-19 20.24
3 2023-12-20 20.39
4 2023-12-21 20.54
.. ... ...
85 2024-03-11 19.89
86 2024-03-12 19.96
87 2024-03-13 20.01
88 2024-03-14 20.12
89 2024-03-15 20.27
[90 rows x 2 columns]
生猪市场价格指数
```
