# `stock_news_main_cx`

**描述**: 财新网-财新数据通-最新

**目标地址**: <https://cxdata.caixin.com/pc/>

**限量**: 返回最新 100 条新闻数据


## 输入参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| - | - | - |

## 输出参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| tag | object | - |
| summary | object | - |
| url | object | - |

## 接口示例

```python
import akshare as ak
stock_news_main_cx_df = ak.stock_news_main_cx()
print(stock_news_main_cx_df)
```

## 数据示例

```text
 tag ... url
0 今日热点 ... https://database.caixin.com/2025-12-25/1023970...
5 市场动态 ... https://database.caixin.com/2025-12-25/1023969...
6 市场动态 ... https://database.caixin.com/2025-12-25/1023969...
9 市场动态 ... https://database.caixin.com/2025-12-25/1023969...
10 市场动态 ... https://database.caixin.com/2025-12-25/1023969...
.. ... ... ...
105 市场动态 ... https://database.caixin.com/2025-12-15/1023934...
106 市场动态 ... https://database.caixin.com/2025-12-15/1023934...
107 市场动态 ... https://database.caixin.com/2025-12-15/1023934...
108 市场洞察 ... https://database.caixin.com/2025-12-15/1023933...
109 市场洞察 ... https://database.caixin.com/2025-12-15/1023933...
[100 rows x 3 columns]
财报发行
```
