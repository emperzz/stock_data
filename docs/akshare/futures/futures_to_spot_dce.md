# `futures_to_spot_dce`

**描述**: 大连商品交易所-期转现统计数据

**目标地址**: <http://www.dce.com.cn/dalianshangpin/xqsj/tjsj26/jgtj/qzxcx/index.html>

**限量**: 单次返回指定交易日的期转现统计数据


## 输入参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| date | str | date="202312"; 交易年月 |

## 输出参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| 合约代码 | object | - |
| 期转现发生日期 | object | - |
| 期转现数量 | int64 | 注意单位: 手 |

## 接口示例

```python
import akshare as ak
futures_to_spot_dce_df = ak.futures_to_spot_dce(date="202312")
print(futures_to_spot_dce_df)
```

## 数据示例

```text
 合约代码 期转现发生日期 期转现数量
0 c2401 2023-12-19 1480
1 c2401 2023-12-26 1490
2 eb2312 2023-12-20 176
期转现-郑商所
```
