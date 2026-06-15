# `option_commodity_contract_sina`

**描述**: 新浪财经-商品期权当前在交易的合约

**目标地址**: <https://stock.finance.sina.com.cn/futures/view/optionsDP.php>

**限量**: 单次返回指定 symbol 的所有合约数据


## 输入参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| symbol | str | symbol="玉米期权" |

## 输出参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| 序号 | str | - |
| 合约 | str | - |

## 接口示例

```python
import akshare as ak
option_commodity_contract_sina_df = ak.option_commodity_contract_sina(symbol="黄金期权")
print(option_commodity_contract_sina_df)
```

## 数据示例

```text
 序号 合约
0 1 au2204
1 2 au2202
2 3 au2206
3 4 au2203
当前合约
```
