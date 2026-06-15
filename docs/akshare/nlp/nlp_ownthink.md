# `nlp_ownthink`

**描述**: 思知-知识图谱的接口, 以此来查询知识图谱数据

**目标地址**: <https://ownthink.com/>

**限量**: 单次返回查询的数据结果


## 输入参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| word | str | word="人工智能" |
| indicator | str | indicator="entity"; Please refer Indicator Info table |

## 输出参数 - entity

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| - | str | 结果 |

## 输出参数 - desc

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| - | str | 结果 |

## 输出参数 - avg

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| - | str | 结果 |

## 输出参数 - tag

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| - | list | 结果 |

## 接口示例

```python
import akshare as ak
nlp_ownthink_df = ak.nlp_ownthink(word="人工智能", indicator="tag")
print(nlp_ownthink_df)
```

## 数据示例

```text
['中国通信学会', '学科']
智能问答
```
