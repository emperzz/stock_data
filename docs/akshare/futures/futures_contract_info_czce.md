# `futures_contract_info_czce`

**描述**: 郑州商品交易所-交易数据-参考数据

**目标地址**: <http://www.czce.com.cn/cn/jysj/cksj/H770322index_1.htm>

**限量**: 单次返回指定 date 的期货合约信息数据


## 输入参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| date | str | date="20240228"; 交易日 |

## 输出参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| 产品名称 | object | - |
| 合约代码 | object | - |
| 产品代码 | object | - |
| 产品类型 | object | - |
| 交易所MIC编码 | object | - |
| 交易场所 | object | - |
| 交易时间节假日除外 | object | - |
| 交易国家ISO编码 | object | - |
| 交易币种ISO编码 | object | - |
| 结算币种ISO编码 | object | - |
| 到期时间待国家公布2025年节假日安排后进行调整 | object | - |
| 结算方式 | object | - |
| 挂牌频率 | object | - |
| 最小变动价位 | object | - |
| 最小变动价值 | object | - |
| 交易单位 | object | - |
| 计量单位 | object | - |
| 最大下单量 | object | - |
| 日持仓限额期货公司会员不限仓 | object | - |
| 大宗交易最小规模 | object | - |
| 是否受CESR监管 | object | - |
| 是否为灵活合约 | object | - |
| 上市周期该产品的所有合约月份 | object | - |
| 交割通知日 | object | - |
| 第一交易日 | object | - |
| 最后交易日待国家公布2025年节假日安排后进行调整 | object | - |
| 交割结算日 | object | - |
| 月份代码 | object | - |
| 年份代码 | object | - |
| 最后交割日 | object | - |
| 车（船）板最后交割日 | object | - |
| 合约交割月份本合约交割月份 | object | - |
| 交易保证金率 | object | - |
| 涨跌停板 | object | - |
| 费用币种ISO编码 | object | - |
| 交易手续费 | float64 | - |
| 手续费收取方式 | object | - |
| 交割手续费 | float64 | - |
| 平今仓手续费 | float64 | - |
| 交易限额 | float64 | - |

## 接口示例

```python
import akshare as ak
futures_contract_info_czce_df = ak.futures_contract_info_czce(date="20240228")
print(futures_contract_info_czce_df)
```

## 数据示例

```text
 产品名称 合约代码 产品代码 产品类型 交易所MIC编码 ... 交易手续费 手续费收取方式 交割手续费 平今仓手续费 交易限额
0 鲜苹果期货 AP403 AP 期货 XZCE ... 5.0 绝对值 0.0 20.0 NaN
1 鲜苹果期货 AP404 AP 期货 XZCE ... 5.0 绝对值 0.0 20.0 NaN
2 鲜苹果期货 AP405 AP 期货 XZCE ... 5.0 绝对值 0.0 20.0 NaN
3 鲜苹果期货 AP410 AP 期货 XZCE ... 5.0 绝对值 0.0 20.0 NaN
4 鲜苹果期货 AP411 AP 期货 XZCE ... 5.0 绝对值 0.0 20.0 NaN
.. ... ... ... ... ... ... ... ... ... ... ...
213 动力煤期货 ZC410 ZC 期货 XZCE ... 150.0 绝对值 0.0 150.0 20.0
214 动力煤期货 ZC411 ZC 期货 XZCE ... 150.0 绝对值 0.0 150.0 20.0
215 动力煤期货 ZC412 ZC 期货 XZCE ... 150.0 绝对值 0.0 150.0 20.0
216 动力煤期货 ZC501 ZC 期货 XZCE ... 150.0 绝对值 0.0 150.0 20.0
217 动力煤期货 ZC502 ZC 期货 XZCE ... 150.0 绝对值 0.0 150.0 20.0
[218 rows x 40 columns]
广州期货交易所
```
