# `stock_irm_ans_cninfo`

**描述**: 互动易-回答

**目标地址**: <https://irm.cninfo.com.cn/>

**限量**: 单次返回指定 symbol 的回答数据


## 输入参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| symbol | str | symbol="1495108801386602496"; 通过 ak.stock_irm_cninfo 来获取具体的提问者编号 |

## 输出参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| 股票代码 | object | - |
| 公司简称 | object | - |
| 问题 | object | - |
| 回答内容 | object | - |
| 提问者 | object | - |
| 提问时间 | datetime64[ns] | - |
| 回答时间 | datetime64[ns] | - |

## 接口示例

```python
import akshare as ak
stock_irm_ans_cninfo_df = ak.stock_irm_ans_cninfo(symbol="1495108801386602496")
print(stock_irm_ans_cninfo_df)
```

## 数据示例

```text
 股票代码 公司简称 ... 提问时间 回答时间
0 002594 比亚迪 ... 2023-07-08 04:12:53 2023-07-12 00:34:31
[1 rows x 7 columns]
上证e互动
```
