# `currency_currencies`


## 输入参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| c_type | str | c_type="fiat" |
| api_key | str | api_key="此处输入 API"; |

## 输出参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| id | int64 | - |
| name | object | - |
| short_code | object | - |
| code | object | - |
| precision | int64 | - |
| subunit | int64 | - |
| symbol | object | - |
| symbol_first | bool | - |
| decimal_mark | object | - |
| thousands_separator | object | - |

## 接口示例

```python
import akshare as ak
currency_currencies_df = ak.currency_currencies(c_type="fiat", api_key="此处输入 API")
print(currency_currencies_df)
```

## 数据示例

```text
 id name ... decimal_mark thousands_separator
0 1 UAE Dirham ... . ,
1 2 Afghani ... . ,
2 3 Lek ... . ,
3 4 Armenian Dram ... . ,
4 5 Netherlands Antillean Guilder ... , .
.. ... ... ... ... ...
156 157 CFP Franc ... . ,
157 158 Yemeni Rial ... . ,
158 159 Rand ... . ,
159 160 Zambian Kwacha ... . ,
160 161 Zimbabwe Dollar ... . ,
[161 rows x 10 columns]
货币对价格转换
```
