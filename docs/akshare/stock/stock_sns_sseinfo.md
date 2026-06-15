# `stock_sns_sseinfo`

**描述**: 上证e互动-提问与回答

**目标地址**: <https://sns.sseinfo.com/company.do?uid=65>

**限量**: 单次返回指定 symbol 的提问与回答数据


## 输入参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| symbol | str | symbol="603119"; 股票代码 |

## 输出参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| 股票代码 | object | - |
| 公司简称 | object | - |
| 问题 | object | - |
| 回答 | object | - |
| 问题时间 | object | - |
| 回答时间 | object | - |
| 问题来源 | object | - |
| 回答来源 | object | - |
| 用户名 | object | - |

## 接口示例

```python
import akshare as ak
stock_sns_sseinfo_df = ak.stock_sns_sseinfo(symbol="603119")
print(stock_sns_sseinfo_df)
```

## 数据示例

```text
 股票代码 公司简称 ... 回答来源 用户名
0 603119 浙江荣泰 ... 网站 YiQi
1 603119 浙江荣泰 ... 网站 YiQi
2 603119 浙江荣泰 ... 网站 春暖花未开
3 603119 浙江荣泰 ... 网站 guest_zT0NfLL0L
4 603119 浙江荣泰 ... 网站 Kgk
.. ... ... ... ... ...
150 603119 浙江荣泰 ... 网站 龙投宝
151 603119 浙江荣泰 ... 网站 SummerIcey
152 603119 浙江荣泰 ... 网站 guest_Usy8rr8Ik
153 603119 浙江荣泰 ... 网站 赵子龙常山
154 603119 浙江荣泰 ... 网站 赵子龙常山
[155 rows x 9 columns]
个股人气榜-实时变动
A股
```
