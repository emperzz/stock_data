# `stock_margin_underlying_info_szse`

**描述**: 深圳证券交易所-融资融券数据-标的证券信息

**目标地址**: <https://www.szse.cn/disclosure/margin/object/index.html>

**限量**: 单次返回交易日的所有历史数据


## 输入参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| date | str | date="20210205" |

## 输出参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| 证券代码 | object | - |
| 证券简称 | object | - |
| 融资标的 | object | - |
| 融券标的 | object | - |
| 当日可融资 | object | - |
| 当日可融券 | object | - |
| 融券卖出价格限制 | object | - |
| 涨跌幅限制 | object | - |

## 接口示例

```python
import akshare as ak
stock_margin_underlying_info_szse_df = ak.stock_margin_underlying_info_szse(date="20210727")
print(stock_margin_underlying_info_szse_df)
```

## 数据示例

```text
 证券代码 证券简称 融资标的 融券标的 当日可融资 当日可融券 融券卖出价格限制 涨跌幅限制
0 000001 平安银行 Y Y Y Y Y 10%
1 000002 万科Ａ Y Y Y Y Y 10%
2 000006 深振业Ａ Y Y Y Y Y 10%
3 000008 神州高铁 Y Y Y Y Y 10%
4 000009 中国宝安 Y Y Y Y Y 10%
 ... ... ... ... ... ... ... ...
1000 301030 C仕净 Y Y Y Y Y 无限制
1001 301031 中熔电气 Y Y Y Y Y 20%
1002 301032 C新柴 Y Y Y Y Y 无限制
1003 301033 C迈普 Y Y Y Y Y 无限制
1004 301039 中集车辆 Y Y Y Y Y 20%
盈利预测-东方财富
```
