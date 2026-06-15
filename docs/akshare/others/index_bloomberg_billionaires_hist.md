# `index_bloomberg_billionaires_hist`

**描述**: 按照年份查询彭博亿万富豪指数; 该接口需要使用代理访问

**目标地址**: <https://stats.areppim.com/stats/links_billionairexlists.htm>

**限量**: 单次返回当年所有数据彭博亿万富豪排名数据


## 输入参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| year | str | year="2021"; choice of {"2021", "2019", "2018", ...} |

## 输出参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| rank | str | Rank |
| name | str | Name |
| total_net_worth | str | Total net worth |
| last_change | str | $ Last change |
| YTD_change | str | $ YTD change |
| country | str | Country |
| industry | str | Industry |
| age | str | Age |

## 接口示例

```python
import akshare as ak
index_bloomberg_billionaires_hist_df=ak.index_bloomberg_billionaires_hist(year='2019')
print(index_bloomberg_billionaires_hist_df)
```

## 数据示例

```text
 rank name ... country industry
0 1 Jeff Bezos ... United States Technology
1 2 Bill Gates ... United States Technology
2 3 Mark Zuckerberg ... United States Technology
3 4 Bernard Arnault ... France Consumer
4 5 Steve Ballmer ... United States Technology
.. ... ... ... ... ...
494 496 Ira Rennert ... United States Commodities
495 497 Traudl Engelhorn-Vechiatto ... Switzerland Diversified
496 498 Sergey Galitskiy ... Russian Federation Retail
497 499 Xu Jingren ... China Health Care
498 500 Shi Yonghong ... Singapore Consumer
TapTap 游戏榜单
```
