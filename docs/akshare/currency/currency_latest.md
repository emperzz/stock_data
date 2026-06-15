# `currency_latest`


## 输入参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| base | str | base="USD" |
| symbols | str | symbols=""; 默认返回全部, 可以在此处设置 symbols="AUD", 则返回 AUD 的数据; 可以在此处设置 symbols: str = "AUD,CNY", 则返回 AUD 和 CNY 的数据 |
| api_key | str | api_key="此处输入 API"; |

## 输出参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| currency | object | 货币代码 |
| date | datetime64[ns, UTC] | 日期时间-注意时区 |
| base | object | 货币 |
| rates | float64 | 比率 |

## 接口示例

```python
import akshare as ak
currency_latest_df = ak.currency_latest(base="USD", symbols="", api_key="此处输入 API")
print(currency_latest_df)
```

## 数据示例

```text
 currency date base rates
0 ADA 2023-07-24 10:56:21+00:00 USD 3.213363
1 AED 2023-07-24 10:56:21+00:00 USD 3.672500
2 AFN 2023-07-24 10:56:21+00:00 USD 85.665822
3 ALL 2023-07-24 10:56:21+00:00 USD 91.125190
4 AMD 2023-07-24 10:56:21+00:00 USD 387.300314
.. ... ... ... ...
215 ZAR 2023-07-24 10:56:21+00:00 USD 17.927659
216 ZMK 2023-07-24 10:56:21+00:00 USD 19493.346892
217 ZMW 2023-07-24 10:56:21+00:00 USD 19.493347
218 ZWD 2023-07-24 10:56:21+00:00 USD 361.900000
219 ZWL 2023-07-24 10:56:21+00:00 USD 4677.170339
[220 rows x 4 columns]
货币报价历史数据
```
