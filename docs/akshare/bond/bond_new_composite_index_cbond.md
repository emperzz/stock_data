# `bond_new_composite_index_cbond`

**描述**: 中国债券信息网-中债指数-中债指数族系-总指数-综合类指数-中债-新综合指数

**目标地址**: <https://yield.chinabond.com.cn/cbweb-mn/indices/single_index_query>


## 输入参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| indicator | str | indicator="财富"; choice of {"全价", "净价", "财富", "平均市值法久期", "平均现金流法久期", "平均市值法凸性", "平均现金流法凸性", "平均现金流法到期收益率", "平均市值法到期收益率", "平均基点价值", "平均待偿期", "平均派息率", "指数上日总市值", "财富指数涨跌幅", "全价指数涨跌幅", "净价指数涨跌幅", "现券结算量"} |
| period | str | period="总值"; choice of {"总值", "1年以下", "1-3年", "3-5年", "5-7年", "7-10年", "10年以上", "0-3个月", "3-6个月", "6-9个月", "9-12个月", "0-6个月", "6-12个月"} |

## 输出参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| date | object | - |
| value | float64 | 注意单位 |

## 接口示例

```python
import akshare as ak
bond_new_composite_index_cbond_df = ak.bond_new_composite_index_cbond(indicator="财富", period="总值")
print(bond_new_composite_index_cbond_df)
```

## 数据示例

```text
 date value
0 2002-01-04 99.9731
1 2002-01-07 100.0149
2 2002-01-08 99.8273
3 2002-01-09 100.0203
4 2002-01-10 99.9317
 ... ...
5440 2023-09-27 226.5951
5441 2023-09-28 226.7308
5442 2023-10-07 226.9880
5443 2023-10-08 227.0376
5444 2023-10-09 226.9609
[5445 rows x 2 columns]
综合指数
```
