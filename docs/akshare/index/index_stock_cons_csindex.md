# `index_stock_cons_csindex`

**描述**: 中证指数网站-成份股目录，可以通过 ak.index_csindex_all() 获取所有指数

**目标地址**: <http://www.csindex.com.cn/zh-CN/indices/index-detail/000300>


## 输入参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| symbol | str | symbol="000300"; 指数代码 |

## 输出参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| 日期 | object | - |
| 指数代码 | object | - |
| 指数名称 | object | - |
| 指数英文名称 | object | - |
| 成分券代码 | object | - |
| 成分券名称 | object | - |
| 成分券英文名称 | object | - |
| 交易所 | object | - |
| 交易所英文名称 | object | - |

## 数据示例

```text
 日期 指数代码 ... 交易所 交易所英文名称
0 2024-01-04 000300 ... 深圳证券交易所 Shenzhen Stock Exchange
1 2024-01-04 000300 ... 深圳证券交易所 Shenzhen Stock Exchange
2 2024-01-04 000300 ... 深圳证券交易所 Shenzhen Stock Exchange
3 2024-01-04 000300 ... 深圳证券交易所 Shenzhen Stock Exchange
4 2024-01-04 000300 ... 深圳证券交易所 Shenzhen Stock Exchange
.. ... ... ... ... ...
295 2024-01-04 000300 ... 上海证券交易所 Shanghai Stock Exchange
296 2024-01-04 000300 ... 上海证券交易所 Shanghai Stock Exchange
297 2024-01-04 000300 ... 上海证券交易所 Shanghai Stock Exchange
298 2024-01-04 000300 ... 上海证券交易所 Shanghai Stock Exchange
299 2024-01-04 000300 ... 上海证券交易所 Shanghai Stock Exchange
[300 rows x 9 columns]
中证指数成份股权重
```
