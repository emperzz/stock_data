# `stock_analyst_detail_em`

**描述**: 东方财富网-数据中心-研究报告-东方财富分析师指数-分析师详情

**目标地址**: <https://data.eastmoney.com/invest/invest/11000257131.html>

**限量**: 单次获取指定 indicator 指定的数据


## 输入参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| analyst_id | str | analyst_id="11000257131"; 分析师ID, 从 ak.stock_analyst_rank_em() 获取 |
| indicator | str | indicator="最新跟踪成分股"; 从 {"最新跟踪成分股", "历史跟踪成分股", "历史指数"} 中选择 |

## 输出参数 - 最新跟踪成分股

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| 序号 | int64 | - |
| 股票代码 | object | - |
| 股票名称 | object | - |
| 调入日期 | object | - |
| 最新评级日期 | object | - |
| 当前评级名称 | object | - |
| 成交价格(前复权) | float64 | - |
| 最新价格 | float64 | - |
| 阶段涨跌幅 | float64 | 注意单位: % |

## 输出参数 - 历史跟踪成分股

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| 序号 | int64 | - |
| 股票代码 | object | - |
| 股票名称 | object | - |
| 调入日期 | object | - |
| 调出日期 | object | - |
| 调入时评级名称 | object | - |
| 调出原因 | object | - |
| 累计涨跌幅 | float64 | 注意单位: % |

## 输出参数 - 历史指数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| date | object | 日期 |
| value | float64 | 指数数值; 注意: 此指数为东方财富制定 |

## 接口示例

```python
import akshare as ak
stock_em_analyst_detail_df = ak.stock_analyst_detail_em(analyst_id="11000200926", indicator="历史指数")
print(stock_em_analyst_detail_df)
```

## 数据示例

```text
 date value
0 2018-11-19 1000.000000
1 2018-11-20 970.738195
2 2018-11-21 1011.450675
3 2018-11-22 1003.817085
4 2018-11-23 989.822170
... ... ...
1479 2024-12-23 5466.064721
1480 2024-12-24 5572.478788
1481 2024-12-25 5521.539014
1482 2024-12-26 5550.570662
1483 2024-12-27 5507.349611
[1484 rows x 2 columns]
千股千评
```
