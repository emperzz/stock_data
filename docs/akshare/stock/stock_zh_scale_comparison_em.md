# `stock_zh_scale_comparison_em`

**描述**: 东方财富-行情中心-同行比较-公司规模

**目标地址**: <https://emweb.securities.eastmoney.com/pc_hsf10/pages/index.html?type=web&code=000895&color=b#/thbj/gsgm>

**限量**: 单次返回全部数据


## 输入参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| symbol | str | symbol="SZ000895" |

## 输出参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| 代码 | object | - |
| 简称 | object | - |
| 总市值 | float64 | - |
| 总市值排名 | int64 | - |
| 流通市值 | float64 | - |
| 流通市值排名 | int64 | - |
| 营业收入 | float64 | - |
| 营业收入排名 | int64 | - |
| 净利润 | float64 | - |
| 净利润排名 | int64 | - |

## 接口示例

```python
import akshare as ak
stock_zh_scale_comparison_em_df = ak.stock_zh_scale_comparison_em(symbol="SZ000895")
print(stock_zh_scale_comparison_em_df)
```

## 数据示例

```text
 代码 简称 总市值 总市值排名 流通市值 流通市值排名 营业收入 营业收入排名 净利润 净利润排名
0 000895 双汇发展 8.685906e+10 5 868.48 4 2.850309e+10 3 2.351218e+09 4
A股-CDR
历史行情数据
```
