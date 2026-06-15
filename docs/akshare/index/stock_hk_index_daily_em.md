# `stock_hk_index_daily_em`

**描述**: 东方财富网-港股-股票指数数据

**目标地址**: <https://quote.eastmoney.com/gb/zsHSTECF2L.html>

**限量**: 单次返回指定 symbol 的所有数据


## 输入参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| symbol | str | symbol="HSTECF2L"; 可以通过 ak.stock_hk_index_spot_em() 获取 |

## 输出参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| date | object | - |
| open | float64 | - |
| high | float64 | - |
| low | float64 | - |
| latest | float64 | 最新价 |

## 接口示例

```python
import akshare as ak
stock_zh_index_daily_em_df = ak.stock_hk_index_daily_em(symbol="HSTECF2L")
print(stock_zh_index_daily_em_df)
```

## 数据示例

```text
 date open high low latest
0 2021-04-12 3004.54 3031.66 2864.62 2873.91
1 2021-04-13 2885.20 2931.77 2781.46 2799.10
2 2021-04-14 2907.05 2970.43 2887.55 2948.15
3 2021-04-15 2914.56 2931.71 2785.23 2871.69
4 2021-04-16 2844.18 2960.53 2840.66 2957.73
.. ... ... ... ... ...
675 2024-01-08 313.48 317.70 295.35 296.93
676 2024-01-09 300.03 307.01 291.85 292.02
677 2024-01-10 288.51 296.62 284.45 289.18
678 2024-01-11 288.87 306.52 288.03 300.63
679 2024-01-12 296.03 305.46 291.92 294.83
[680 rows x 5 columns]
美股股票指数
指数行情
```
