# `futures_spot_sys`

**描述**: 生意社-商品与期货-现期图

**目标地址**: <https://www.100ppi.com/sf/792.html>

**限量**: 单次返回指定品种的现期图数据


## 输入参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| symbol | str | symbol="铜"; 期货品种 |
| contract | str | indicator="市场价格"; choice of {"市场价格", "基差率", "主力基差"} |

## 输出参数 - 市场价格

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| 日期 | object | - |
| 现货价格 | float64 | - |
| 主力合约 | float64 | - |
| 最近合约 | float64 | - |

## 输出参数 - 基差率

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| 日期 | object | - |
| 基差率 | float64 | - |

## 输出参数 - 主力基差

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| 日期 | object | - |
| 主力基差 | float64 | - |

## 接口示例

```python
import akshare as ak
futures_spot_sys_df = ak.futures_spot_sys(symbol="铜", indicator="主力基差")
print(futures_spot_sys_df)
```

## 数据示例

```text
 日期 主力基差
0 11-26 NaN
1 12-05 805.00
2 12-14 583.33
3 12-23 NaN
4 01-01 NaN
5 01-10 280.00
6 01-19 183.33
7 01-28 NaN
8 02-06 -128.33
9 02-15 NaN
10 02-24 NaN
合约信息
上海期货交易所
```
