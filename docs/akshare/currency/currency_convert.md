# `currency_convert`


## 输入参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| base | str | base="USD"; 基础货币 |
| to | str | to="CNY"; 需要转换到的货币 |
| amount | str | amount="10000"; 转换量 |
| api_key | str | api_key="此处输入 API"; |

## 输出参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| item | object | - |
| value | object | - |

## 接口示例

```python
import akshare as ak
currency_convert_df = ak.currency_convert(base="USD", to="CNY", amount="10000", api_key="此处输入 API")
print(currency_convert_df)
```

## 数据示例

```text
 item value
0 timestamp 2023-07-24 11:31:20
1 date 2023-07-24
2 from USD
3 to CNY
4 amount 10000
5 value 71898.995
```
