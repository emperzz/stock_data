# `stock_a_below_net_asset_statistics`

**描述**: 乐咕乐股-A 股破净股统计数据

**目标地址**: <https://www.legulegu.com/stockdata/below-net-asset-statistics>

**限量**: 单次获取指定 symbol 的所有历史数据


## 输入参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| symbol | str | symbol="全部A股"; choice of {"全部A股", "沪深300", "上证50", "中证500"} |

## 输出参数 - 全部A股

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| date | object | 交易日 |
| below_net_asset | float64 | 破净股家数 |
| total_company | float64 | 总公司数 |
| below_net_asset_ratio | float64 | 破净股比率 |

## 输出参数 - 沪深 300

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| date | object | 交易日 |
| below_net_asset | float64 | 破净股家数 |
| total_company | float64 | 总公司数 |
| below_net_asset_ratio | float64 | 破净股比率 |

## 接口示例

```python
import akshare as ak
stock_a_below_net_asset_statistics_df = ak.stock_a_below_net_asset_statistics(symbol="沪深300")
print(stock_a_below_net_asset_statistics_df)
```

## 数据示例

```text
 date below_net_asset total_company below_net_asset_ratio
0 2005-04-07 22 299 0.0736
1 2005-04-10 21 299 0.0702
2 2005-04-11 23 299 0.0769
3 2005-04-12 20 299 0.0669
4 2005-04-13 22 299 0.0736
 ... ... ... ...
4627 2024-04-21 63 300 0.2100
4628 2024-04-22 63 300 0.2100
4629 2024-04-23 63 300 0.2100
4630 2024-04-24 63 300 0.2100
4631 2024-04-25 62 300 0.2067
[4632 rows x 4 columns]
基金持股
```
