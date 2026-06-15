# `option_cffex_zz1000_list_sina`

**描述**: 中金所-中证1000指数-所有合约, 返回的第一个合约为主力合约

**目标地址**: <https://stock.finance.sina.com.cn/futures/view/optionsCffexDP.php>

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
option_cffex_zz1000_list_sina_df = ak.option_cffex_zz1000_list_sina()
print(option_cffex_zz1000_list_sina_df)
```

## 数据示例

```text
{'中证1000指数': ['mo2208', 'mo2209', 'mo2212', 'mo2210', 'mo2306', 'mo2303']}
实时行情-上证50指数
```
