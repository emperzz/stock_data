# `stock_hk_indicator_eniu`

**描述**: 亿牛网-港股个股指标: 市盈率, 市净率, 股息率, ROE, 市值

**目标地址**: <https://eniu.com/gu/hk01093/roe>

**限量**: 单次获取指定 symbol 和 indicator 的所有历史数据


## 输入参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| symbol | str | symbol="hk01093"; 可通过调用 ak.stock_hk_indicator_eniu(symbol="hk01093", indicator="港股") 获取股票代码 |
| indicator | str | indicator="市盈率"; choice of {"港股", "市盈率", "市净率", "股息率", "ROE", "市值"} |

## 输出参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| - | - | 根据 indicator 而异 |

## 接口示例

```python
import akshare as ak
stock_hk_indicator_eniu_df = ak.stock_hk_indicator_eniu(symbol="hk01093", indicator="市净率")
print(stock_hk_indicator_eniu_df)
```

## 数据示例

```text
 date pb price
0 2000-01-03 1.17 0.00
1 2000-01-04 1.24 0.00
2 2000-01-05 1.19 0.00
3 2000-01-06 1.06 0.00
4 2000-01-07 1.08 0.00
 ... ... ...
5041 2020-08-07 7.31 15.74
5042 2020-08-10 7.22 15.54
5043 2020-08-11 7.31 15.74
5044 2020-08-12 7.15 15.40
5045 2020-08-13 7.18 15.46
港股估值指标
```
