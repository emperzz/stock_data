# `option_risk_indicator_sse`

**描述**: 上海证券交易所-产品-股票期权-期权风险指标数据

**目标地址**: <http://www.sse.com.cn/assortment/options/risk/>

**限量**: 单次返回指定 date 的数据


## 输入参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| date | str | date="20240626"; 交易日; 从 20150209 开始 |

## 输出参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| TRADE_DATE | object | - |
| SECURITY_ID | object | - |
| CONTRACT_ID | object | - |
| CONTRACT_SYMBOL | object | - |
| DELTA_VALUE | float64 | - |
| THETA_VALUE | float64 | - |
| GAMMA_VALUE | float64 | - |
| VEGA_VALUE | float64 | - |
| RHO_VALUE | float64 | - |
| IMPLC_VOLATLTY | float64 | - |

## 接口示例

```python
import akshare as ak
option_risk_indicator_sse_df = ak.option_risk_indicator_sse(date="20240626")
print(option_risk_indicator_sse_df)
```

## 数据示例

```text
 TRADE_DATE SECURITY_ID ... RHO_VALUE IMPLC_VOLATLTY
0 2024-06-26 10007437 ... 0.163 0.182
1 2024-06-26 10007425 ... 0.164 0.149
2 2024-06-26 10007333 ... 0.152 0.141
3 2024-06-26 10007334 ... 0.128 0.131
4 2024-06-26 10007335 ... 0.089 0.129
.. ... ... ... ... ...
391 2024-06-26 10007225 ... -0.253 0.279
392 2024-06-26 10007226 ... -0.308 0.306
393 2024-06-26 10007227 ... -0.353 0.336
394 2024-06-26 10007228 ... -0.392 0.367
395 2024-06-26 10007238 ... -0.426 0.401
[396 rows x 10 columns]
当日合约-上海证券交易所
```
