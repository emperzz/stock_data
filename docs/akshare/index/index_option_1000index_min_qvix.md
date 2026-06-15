# `index_option_1000index_min_qvix`

**描述**: 中证1000股指 期权波动率指数-分时

**目标地址**: <http://1.optbbs.com/s/vix.shtml?Index1000>

**限量**: 单次返回最近交易日的分时数据


## 输入参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| - | - | - |

## 输出参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| time | object | - |
| qvix | float64 | - |

## 接口示例

```python
import akshare as ak
index_option_1000index_min_qvix_df = ak.index_option_1000index_min_qvix()
print(index_option_1000index_min_qvix_df)
```

## 数据示例

```text
 time qvix
0 9:30:00 26.79
1 9:31:51 26.84
2 9:32:51 26.90
3 9:33:51 26.93
4 9:34:51 26.78
.. ... ...
234 14:53:59 27.50
235 14:54:59 27.47
236 14:55:59 27.51
237 14:56:59 27.55
238 15:00:59 27.55
[239 rows x 2 columns]
上证50股指 期权波动率指数
```
