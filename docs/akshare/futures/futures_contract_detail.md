# `futures_contract_detail`

**描述**: 新浪财经-期货-期货合约详情数据

**目标地址**: <https://finance.sina.com.cn/futures/quotes/V2101.shtml>

**限量**: 单次返回指定 symbol 的合约详情数据


## 输入参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| symbol | str | symbol='AP2101'; 请参考新浪连续合约品种一览表, 也可通过 ak.futures_display_main_sina() 获取 |

## 输出参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| item | object | 合约具体的项目 |
| value | object | 合约具体的项目值 |

## 接口示例

```python
import akshare as ak
futures_contract_detail_df = ak.futures_contract_detail(symbol='V2001')
print(futures_contract_detail_df)
```

## 数据示例

```text
 item value
0 交易品种 聚氯乙烯
1 最小变动价位 5元/吨
2 交易时间 上午 09:00-10:15 10:30-11:30 下午 13:30-15:00 夜间 2...
3 交割品级 质量标准符合《悬浮法通用型聚氯乙烯树脂（GB/T 5761-2006）》规定的SG5型一等品...
4 交割方式 实物交割
5 交易单位 5吨/手
6 涨跌停板幅度 上一交易日结算价的±4%
7 最后交易日 合约月份第10个交易日
8 最低交易保证金 投机买卖20.0%，套保买卖20.0%
9 交易代码 V
10 报价单位 元(人民币/吨)
11 合约交割月份 1---12月
12 最后交割日 最后交易日后第3个交易日
13 交易手续费 开平仓2元/手，短线开平仓1元/手
14 上市交易所 大连商品交易所
期货合约详情-东财
```
