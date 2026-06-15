# `index_option_50index_qvix`

**描述**: 上证50股指 期权波动率指数 QVIX

**目标地址**: <http://1.optbbs.com/s/vix.shtml?50index>

**限量**: 单次返回所有数据


## 输入参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| - | - | - |

## 输出参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| date | object | - |
| open | float64 | - |
| high | float64 | - |
| low | float64 | - |
| close | float64 | - |

## 接口示例

```python
import akshare as ak
index_option_50index_qvix_df = ak.index_option_50index_qvix()
print(index_option_50index_qvix_df)
```

## 数据示例

```text
 date open high low close
0 2015-02-09 NaN NaN NaN NaN
1 2015-02-10 NaN NaN NaN NaN
2 2015-02-11 NaN NaN NaN NaN
3 2015-02-12 NaN NaN NaN NaN
4 2015-02-13 NaN NaN NaN NaN
... ... ... ... ... ...
2393 2024-12-24 20.78 20.82 20.08 20.43
2394 2024-12-25 20.72 21.19 20.43 20.67
2395 2024-12-26 20.74 20.74 19.67 19.81
2396 2024-12-27 19.96 20.10 19.43 19.54
2397 2024-12-30 20.36 20.40 19.65 19.84
[2398 rows x 5 columns]
上证50股指 期权波动率指数-分时
```
