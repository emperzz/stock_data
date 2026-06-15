# `car_market_total_cpca`

**描述**: 乘联会-统计数据-总体市场

**目标地址**: <http://data.cpcadata.com/TotalMarket>

**限量**: 单次返回指定 symbol 和 indicator 的数据


## 输入参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| symbol | str | symbol="狭义乘用车"; choice of {"狭义乘用车", "广义乘用车"} |
| indicator | str | indicator="产量"; choice of {"产量", "批发", "零售", "出口"} |

## 输出参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| 月份 | object | - |
| {前一个年份}年 | float64 | 注意单位: 万辆 |
| {当前年份}年 | float64 | 注意单位: 万辆 |

## 接口示例

```python
import akshare as ak
car_market_total_cpca_df = ak.car_market_total_cpca(symbol="狭义乘用车", indicator="产量")
print(car_market_total_cpca_df)
```

## 数据示例

```text
 月份 2023年 2024年
0 1月 134.6266 202.0941
1 2月 166.4180 123.4852
2 3月 208.7694 NaN
3 4月 172.8825 NaN
4 5月 198.9448 NaN
5 6月 219.4569 NaN
6 7月 208.9492 NaN
7 8月 223.7048 NaN
8 9月 243.6938 NaN
9 10月 244.8691 NaN
10 11月 264.3703 NaN
11 12月 267.8423 NaN
乘联会-统计数据-厂商排名
```
