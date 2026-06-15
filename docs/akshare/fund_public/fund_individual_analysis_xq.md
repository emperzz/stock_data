# `fund_individual_analysis_xq`

**描述**: 雪球基金-基金详情-数据分析

**目标地址**: <https://danjuanfunds.com/funding/000001>

**限量**: 返回单只基金历史表现分析数据


## 输入参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| symbol | str | symbol="000001"; 基金代码 |
| timeout | float | timeout=None; 默认不设置超时参数 |

## 输出参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| 周期 | object | - |
| 较同类风险收益比 | int64 | 注意单位：% |
| 较同类抗风险波动 | int64 | 注意单位：% |
| 年化波动率 | float64 | 注意单位：% |
| 年化夏普比率 | float64 | - |
| 最大回撤 | float64 | 注意单位：% |

## 接口示例

```python
import akshare as ak
fund_individual_analysis_xq_df = ak.fund_individual_analysis_xq(symbol="000001")
print(fund_individual_analysis_xq_df)
```

## 数据示例

```text
 周期 较同类风险收益比 较同类抗风险波动 年化波动率 年化夏普比率 最大回撤
0 近1年 3 61 12.72 -1.89 26.58
1 近3年 9 56 18.66 -0.93 48.55
2 近5年 2 57 19.04 -0.11 48.55
基金盈利概率
```
