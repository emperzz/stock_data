# `macro_usa_cme_merchant_goods_holding`

**描述**: CME-贵金属, 数据区间从 20180405-至今

**目标地址**: <https://datacenter.jin10.com/org>

**限量**: 单次返回所有历史数据


## 输入参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| - | - | - |

## 输出参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| 日期 | object | - |
| 品种 | object | - |
| 成交量 | float64 | - |

## 接口示例

```python
import akshare as ak
macro_usa_cme_merchant_goods_holding_df = ak.macro_usa_cme_merchant_goods_holding()
print(macro_usa_cme_merchant_goods_holding_df)
```

## 数据示例

```text
 日期 品种 成交量
0 2018-04-05 铜-看跌 597
1 2018-04-05 黄金-期货 288119
2 2018-04-05 黄金-期权 54434
3 2018-04-05 黄金-看涨 36821
4 2018-04-05 黄金-看跌 17613
 ... ... ...
30184 2024-04-04 铜-看跌 5704
30185 2024-04-04 铜-看涨 17858
30186 2024-04-04 铜-期权 23562
30187 2024-04-04 铂金-看涨 1077
30188 2024-04-04 黄金-期货 245856
[30189 rows x 3 columns]
全球宏观
宏观日历
```
