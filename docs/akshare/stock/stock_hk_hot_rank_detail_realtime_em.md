# `stock_hk_hot_rank_detail_realtime_em`

**描述**: 东方财富网-个股人气榜-实时变动

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

## 接口示例

```python
import akshare as ak
stock_hk_hot_rank_detail_realtime_em_df = ak.stock_hk_hot_rank_detail_realtime_em(symbol="00700")
print(stock_hk_hot_rank_detail_realtime_em_df)
```

## 数据示例

```text
 时间 排名
0 2023-03-25 00:00:00 1
1 2023-03-25 00:10:00 1
2 2023-03-25 00:20:00 1
3 2023-03-25 00:30:00 1
4 2023-03-25 00:40:00 1
.. ... ..
137 2023-03-25 22:50:00 1
138 2023-03-25 23:00:00 1
139 2023-03-25 23:10:00 1
140 2023-03-25 23:20:00 1
141 2023-03-25 23:30:00 1
热门关键词
```
