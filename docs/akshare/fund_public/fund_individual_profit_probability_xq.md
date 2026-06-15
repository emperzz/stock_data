# `fund_individual_profit_probability_xq`

**描述**: 雪球基金-基金详情-盈利概率；历史任意时点买入，持有满X时间，盈利概率，以及平均收益

**目标地址**: <https://danjuanfunds.com/funding/000001>

**限量**: 单次返回单只基金历史任意时点买入，持有满 X 时间，盈利概率，以及平均收益


## 输入参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| symbol | str | symbol="000001"; 基金代码 |
| timeout | float | timeout=None; 默认不设置超时参数 |

## 输出参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| 持有时长 | object | - |
| 盈利概率 | object | 注意单位：% |
| 平均收益 | object | 注意单位：% |

## 接口示例

```python
import akshare as ak
fund_individual_profit_probability_xq_df = ak.fund_individual_profit_probability_xq(symbol="000001")
print(fund_individual_profit_probability_xq_df)
```

## 数据示例

```text
 持有时长 盈利概率 平均收益
0 满6个月 53 5.97
1 满1年 59 14.23
2 满2年 66 32.34
3 满3年 76 51.16
基金持仓资产比例
```
