# `stock_hk_hot_rank_detail_em`

**描述**: 东方财富网-股票热度-历史趋势

**目标地址**: <https://guba.eastmoney.com/rank/stock?code=HK_00700>

**限量**: 单次返回指定 symbol 的股票近期历史数据


## 输入参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| symbol | str | symbol="00700" |

## 输出参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| 时间 | object | - |
| 排名 | int64 | - |
| 证券代码 | object | - |

## 接口示例

```python
import akshare as ak
stock_hk_hot_rank_detail_em_df = ak.stock_hk_hot_rank_detail_em(symbol="00700")
print(stock_hk_hot_rank_detail_em_df)
```

## 数据示例

```text
 时间 排名 证券代码
0 2022-11-26 1 00700
1 2022-11-27 2 00700
2 2022-11-28 1 00700
3 2022-11-29 1 00700
4 2022-11-30 1 00700
.. ... .. ...
115 2023-03-21 1 00700
116 2023-03-22 1 00700
117 2023-03-23 1 00700
118 2023-03-24 1 00700
119 2023-03-25 1 00700
互动平台
互动易-提问
```
