# `option_sse_underlying_spot_price_sina`

**描述**: 获取期权标的物的实时数据

**目标地址**: <https://stock.finance.sina.com.cn/futures/view/optionsCffexDP.php>

**限量**: 单次返回期权标的物的实时数据


## 输入参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| symbol | str | symbol="sh510300" |

## 输出参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| 字段 | object | - |
| 值 | object | - |

## 接口示例

```python
import akshare as ak
option_sse_underlying_spot_price_sina_df = ak.option_sse_underlying_spot_price_sina(symbol="sh510300")
print(option_sse_underlying_spot_price_sina_df)
```

## 数据示例

```text
 字段 值
0 证券简称 300ETF
1 今日开盘价 4.123
2 昨日收盘价 4.131
3 最近成交价 4.145
4 最高成交价 4.178
5 最低成交价 4.117
6 买入价 4.144
7 卖出价 4.146
8 成交数量 444470153
9 成交金额 1839049777.000
10 买数量一 364200
11 买价位一 4.144
12 买数量二 659700
13 买价位二 4.143
14 买数量三 82400
15 买价位三 4.142
16 买数量四 2600
17 买价位四 4.141
18 买数量五 864800
19 买价位五 4.140
20 卖数量一 2400
21 卖价位一 4.146
22 卖数量二 763100
23 卖价位二 4.147
24 卖数量三 556300
25 卖价位三 4.148
26 卖数量四 86500
27 卖价位四 4.149
28 卖数量五 351400
29 卖价位五 4.150
30 行情日期 2020-02-21
31 行情时间 15:00:00
32 停牌状态 00
期权希腊字母信息表
```
