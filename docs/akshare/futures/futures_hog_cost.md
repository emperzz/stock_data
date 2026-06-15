# `futures_hog_cost`

**描述**: 玄田数据-成本维度

**目标地址**: <https://zhujia.zhuwang.com.cn>

**限量**: 单次返回指定 symbol 的所有历史数据


## 输入参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| symbol | str | symbol="玉米"; choice of {"玉米", "豆粕", "二元母猪价格", "仔猪价格"} |

## 输出参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| date | object | - |
| value | float64 | - |

## 接口示例

```python
import akshare as ak
futures_hog_cost_df = ak.futures_hog_cost(symbol="玉米")
print(futures_hog_cost_df)
```

## 数据示例

```text
 date value
0 2023-03-18 2915
1 2023-03-19 2895
2 2023-03-20 2874
3 2023-03-21 2903
4 2023-03-22 2891
.. ... ...
362 2024-03-14 2474
363 2024-03-15 2486
364 2024-03-16 2473
365 2024-03-17 2471
366 2024-03-18 2462
[367 rows x 2 columns]
供应维度
```
