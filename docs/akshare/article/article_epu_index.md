# `article_epu_index`

**描述**: 国家或地区的经济政策不确定性(EPU)数据

**目标地址**: <https://www.policyuncertainty.com/index.html>

**限量**: 单次返回某个具体国家或地区的所有月度经济政策不确定性数据


## 输入参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| symbol | str | symbol="China"; 按 国家和地区一览表 输入相应参数 |

## 输出参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| - | - | 每个国家或地区不同 |

## 接口示例

```python
import akshare as ak
article_epu_index_df = ak.article_epu_index(symbol="China") # 注意单词第一个字母大写
print(article_epu_index_df)
```

## 数据示例

```text
 year month China_Policy_Index
0 1995 1 192.911910
1 1995 2 193.987850
2 1995 3 88.227035
3 1995 4 131.034710
4 1995 5 177.096860
.. ... ... ...
342 2023 7 704.566080
343 2023 8 709.881990
344 2023 9 819.746150
345 2023 10 603.739890
346 2023 11 743.397580
[347 rows x 3 columns]
```
