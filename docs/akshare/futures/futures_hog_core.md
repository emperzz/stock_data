# `futures_hog_core`

**描述**: 玄田数据-核心数据

**目标地址**: <https://zhujia.zhuwang.com.cn>

**限量**: 单次返回指定 symbol 的所有历史数据


## 输入参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| symbol | str | symbol="外三元"; choice of {"外三元", "内三元", "土杂猪"} |

## 输出参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| date | object | - |
| value | float64 | - |

## 接口示例

```python
import akshare as ak
futures_hog_core_df = ak.futures_hog_core(symbol="外三元")
print(futures_hog_core_df)
```

## 数据示例

```text
 date value
0 2023-03-18 15.42
1 2023-03-19 15.46
2 2023-03-20 15.42
3 2023-03-21 15.44
4 2023-03-22 15.25
.. ... ...
362 2024-03-14 14.58
363 2024-03-15 14.53
364 2024-03-16 14.54
365 2024-03-17 14.67
366 2024-03-18 14.71
[367 rows x 2 columns]
成本维度
```
