# `option_cffex_zz1000_daily_sina`

**描述**: 中金所-中证1000指数-指定合约-日频行情

**目标地址**: <https://stock.finance.sina.com.cn/futures/view/optionsCffexDP.php>

**限量**: 单次返回指定合约的日频行情


## 输入参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| symbol | str | symbol="mo2208P6200"; 具体合约代码(包括看涨和看跌标识), 可以通过 ak.option_cffex_zz1000_spot_sina 中的 call-标识 获取 |

## 输出参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| date | object | - |
| open | float64 | - |
| high | float64 | - |
| low | float64 | - |
| close | float64 | - |
| volume | int64 | - |

## 接口示例

```python
import akshare as ak
option_cffex_zz1000_daily_sina_df = ak.option_cffex_zz1000_daily_sina(symbol="mo2208P6200")
print(option_cffex_zz1000_daily_sina_df)
```

## 数据示例

```text
 date open high low close volume
0 2022-07-26 17.2 20.2 7.8 7.8 460
1 2022-07-27 7.8 8.2 6.4 6.8 475
2 2022-07-28 5.4 6.8 4.4 5.6 779
3 2022-07-29 5.4 8.8 4.6 8.4 462
4 2022-08-01 8.4 12.4 6.0 6.4 572
上交所
合约到期月份列表
```
