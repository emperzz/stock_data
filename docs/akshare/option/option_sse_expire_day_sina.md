# `option_sse_expire_day_sina`

**描述**: 获取指定到期月份指定品种的剩余到期时间

**目标地址**: <https://stock.finance.sina.com.cn/futures/view/optionsCffexDP.php>

**限量**: 单次返回指定品种的品种的剩余到期时间


## 输入参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| trade_date | str | trade_date="202002"; |
| symbol | str | symbol="50ETF"; "50ETF" or "300ETF" |
| exchange | str | exchange="null" |

## 输出参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| - | - | - |

## 接口示例

```python
import akshare as ak
option_sse_expire_day_sina_df = ak.option_sse_expire_day_sina(trade_date="202002", symbol="50ETF", exchange="null")
print(option_sse_expire_day_sina_df)
```

## 数据示例

```text
('2020-02-26', 3)
所有合约的代码
```
