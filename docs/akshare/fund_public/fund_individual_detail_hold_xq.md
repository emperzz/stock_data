# `fund_individual_detail_hold_xq`

**描述**: 雪球基金-基金详情-基金持仓-详情

**目标地址**: <https://danjuanfunds.com/rn/fund-detail/archive?id=103&code=000001>

**限量**: 单次返回单只基金指定日期的持仓大类资产比例


## 输入参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| symbol | str | symbol="000001"; 基金代码 |
| date | str | date="20231231"; 季度日期 |
| timeout | float | timeout=None; 默认不设置超时参数 |

## 输出参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| 资产类型 | object | - |
| 仓位占比 | float64 | 注意单位：% |

## 接口示例

```python
import akshare as ak
fund_individual_detail_hold_xq_df = ak.fund_individual_detail_hold_xq(symbol="002804", date="20231231")
print(fund_individual_detail_hold_xq_df)
```

## 数据示例

```text
 资产类型 仓位占比
0 股票 51.95
1 现金 19.51
2 其他 29.09
基金基本概况
```
