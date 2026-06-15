# `article_oman_rv`

**描述**: 获取 Oxford-Man 已实现波动率数据

**目标地址**: <https://realized.oxford-man.ox.ac.uk/data/visualization>

**限量**: 单次返回某个指数具体指标的所有历史数据


## 输入参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| symbol | str | symbol="FTSE", 具体指数请查看如下 已实现波动率指数一览表 |
| index | str | index="rk_th2", 具体指标请查看如下 已实现波动率指标一览表 |

## 输出参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| index | datetime.datetime | 日期 |
| data | float | 数据 |

## 接口示例

```python
import akshare as ak
article_oman_rv_df = ak.article_oman_rv(symbol="FTSE", index="rk_th2")
print(article_oman_rv_df)
```

## 数据示例

```text
2000-01-04 22.95
2000-01-05 19.37
2000-01-06 18.22
2000-01-07 19.34
2000-01-10 15.67
 ...
2019-11-04 6.71
2019-11-05 5.90
2019-11-06 6.43
2019-11-07 5.81
2019-11-08 6.75
Risk-Lab
```
