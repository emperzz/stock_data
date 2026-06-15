# `option_sse_list_sina`

**描述**: 获取期权-上交所-50ETF-合约到期月份列表

**目标地址**: <https://stock.finance.sina.com.cn/futures/view/optionsCffexDP.php>

**限量**: 单次返回指定品种的到期月份列表


## 输入参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| symbol | str | symbol="50ETF"; "50ETF" or "300ETF" |
| exchange | str | exchange="null" |

## 输出参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| - | - | - |

## 接口示例

```python
import akshare as ak
option_sse_list_sina_df = ak.option_sse_list_sina(symbol="50ETF", exchange="null")
print(option_sse_list_sina_df)
```

## 数据示例

```text
['202002', '202003', '202006', '202009']
合约到期月份列表
```
