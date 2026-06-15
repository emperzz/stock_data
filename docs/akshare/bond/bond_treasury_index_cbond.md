# `bond_treasury_index_cbond`

**描述**: 中国债券信息网-中债指数-中债指数族系-总指数-综合类指数-中债-国债指数

**目标地址**: <https://yield.chinabond.com.cn/cbweb-mn/indices/single_index_query>


## 输入参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| indicator | str | indicator="财富"; choice of {"全价", "净价", "财富"} |
| period | str | period="5Y"; choice of {'0-1Y', '0-3Y', '0-5Y', '0-10Y', '1-3Y', '1-5Y', '1-10Y', '3-5Y', '5Y', '7Y', '7-10Y', '10Y', '30Y'} |

## 输出参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| date | object | - |
| value | float64 | 注意单位 |

## 接口示例

```python
import akshare as ak
bond_treasury_index_cbond_df = ak.bond_treasury_index_cbond(indicator="财富", period="5Y")
print(bond_treasury_index_cbond_df)
```

## 数据示例

```text
 date value
0 2008-01-02 100.1752
1 2008-01-03 100.1729
2 2008-01-04 100.2592
3 2008-01-07 100.3394
4 2008-01-08 100.4001
... ... ...
4562 2026-04-03 210.4979
4563 2026-04-07 210.5423
4564 2026-04-08 210.5118
4565 2026-04-09 210.4856
4566 2026-04-10 210.4820
[4567 rows x 2 columns]
中债指数族系
可选指数
```
