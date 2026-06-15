# `index_option_100etf_min_qvix`

**描述**: 深证100ETF 期权波动率指数-分时

**目标地址**: <http://1.optbbs.com/s/vix.shtml?100ETF>

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
index_option_100etf_min_qvix_df = ak.index_option_100etf_min_qvix()
print(index_option_100etf_min_qvix_df)
```

## 数据示例

```text
 time qvix
0 9:30:00 22.80
1 9:31:51 22.95
2 9:32:51 22.85
3 9:33:51 22.75
4 9:34:51 22.66
.. ... ...
234 14:53:59 23.05
235 14:54:59 22.90
236 14:55:59 23.02
237 14:56:59 23.05
238 15:00:59 23.04
[239 rows x 2 columns]
中证300股指 期权波动率指数
```
