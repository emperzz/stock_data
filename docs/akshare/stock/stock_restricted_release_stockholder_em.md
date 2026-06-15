# `stock_restricted_release_stockholder_em`

**描述**: 东方财富网-数据中心-个股限售解禁-解禁股东

**目标地址**: <https://data.eastmoney.com/dxf/q/600000.html>

**限量**: 单次获取指定 symbol 的解禁批次数据


## 输入参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| symbol | str | symbol="600000" |
| date | str | date="20200904"; 通过 ak.stock_restricted_release_queue_em(symbol="600000") 获取 |

## 输出参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| 序号 | int64 | - |
| 股东名称 | object | - |
| 解禁数量 | int64 | 注意单位: 股 |
| 实际解禁数量 | int64 | 注意单位: 股 |
| 解禁市值 | float64 | 注意单位: 元 |
| 锁定期 | int64 | 注意单位: 月 |
| 剩余未解禁数量 | int64 | 注意单位: 股 |
| 限售股类型 | object | - |
| 进度 | object | - |

## 接口示例

```python
import akshare as ak
stock_restricted_release_stockholder_em_df = ak.stock_restricted_release_stockholder_em(symbol="600000", date="20200904")
print(stock_restricted_release_stockholder_em_df)
```

## 数据示例

```text
 序号 股东名称 解禁数量 实际解禁数量 ... 锁定期 剩余未解禁数量 限售股类型 进度
0 1 上海国际集团有限公司 842003367 842003367 ... 36 0 定向增发机构配售股份 实施
1 2 上海国鑫投资发展有限公司 406313131 406313131 ... 36 0 定向增发机构配售股份 实施
流通股东
```
