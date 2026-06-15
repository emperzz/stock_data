# `option_cffex_sz50_list_sina`

**描述**: 中金所-上证50指数-所有合约, 返回的第一个合约为主力合约

**目标地址**: <https://stock.finance.sina.com.cn/futures/view/optionsCffexDP.php/ho/cffex>

**限量**: 单次返回所有合约


## 输入参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| - | - | - |

## 输出参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| - | - | - |

## 接口示例

```python
import akshare as ak
option_cffex_sz50_list_sina_df = ak.option_cffex_sz50_list_sina()
print(option_cffex_sz50_list_sina_df)
```

## 数据示例

```text
{'上证50指数': ['ho2301', 'ho2303', 'ho2302', 'ho2306', 'ho2312', 'ho2309']}
沪深300指数列表
```
