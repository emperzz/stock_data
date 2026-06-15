# `option_vol_gfex`

**描述**: 广州期货交易所-商品期权数据-隐含波动参考值

**目标地址**: <http://www.gfex.com.cn/gfex/rihq/hqsj_tjsj.shtml>

**限量**: 单次返回指定 symbol 和 trade_date 的期权行情数据


## 输入参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| symbol | str | symbol="工业硅"; choice of {"工业硅", "碳酸锂"} |
| trade_date | str | trade_date="20230724" |

## 输出参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| 合约系列 | object |  |
| 隐含波动率 | float64 |  |

## 接口示例

```python
import akshare as ak
option_vol_gfex_df = ak.option_vol_gfex(symbol="工业硅", trade_date="20230418")
print(option_vol_gfex_df)
```

## 数据示例

```text
 合约系列 隐含波动率
0 si2308 22.542314
1 si2309 21.018517
2 si2310 21.018517
3 si2311 21.018517
4 si2312 19.894257
5 si2401 19.894257
6 si2402 19.894257
7 si2403 19.729307
历史数据
```
