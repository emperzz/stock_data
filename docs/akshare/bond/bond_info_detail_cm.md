# `bond_info_detail_cm`

**描述**: 中国外汇交易中心暨全国银行间同业拆借中心-数据-债券信息-信息查询-债券详情

**目标地址**: <https://www.chinamoney.com.cn/chinese/zqjc/?bondDefinedCode=egfjh08154>


## 输入参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| symbol | str | symbol="19万林投资CP001"; 通过 ak.bond_info_cm() 查询 债券简称 |

## 输出参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| name | object | - |
| value | object | - |

## 接口示例

```python
import akshare as ak
bond_info_detail_cm_df = ak.bond_info_detail_cm(symbol="19万林投资CP001")
print(bond_info_detail_cm_df)
```

## 数据示例

```text
 name value
0 bondFullName 重庆万林投资发展有限公司2019年度第一期短期融资券
1 bondDefinedCode 695327xh9n
2 bondName 19万林投资CP001
3 bondCode 041900126
4 isinCode ---
.. ... ...
59 chrgngMthds ---
60 crdtEv ---
61 brchStlmntMthd ---
62 rgstrtnCnfrmtnDay ---
63 inptTp 0
[64 rows x 2 columns]
债券基础名词
固定收益证券
是指持券人可以在特定的时间内取得固定的收益并预先知道取得收益的数量和时间, 如固定利率债券、优先股股票等.
国债
国债又称国家公债, 是国家以其信用为基础, 按照债券的一般原则, 通过向社会发行债券筹集资金所形成的债权债务关系. 国债是中央政府为筹集财政资金而发行的一种政府债券, 由中央政府向投资者出具的、承诺在一定时期支付利息和到期偿还本金的债权债务凭证, 由于国债的发行主体是国家, 所以它具有最高的信用度, 被公认为是最安全的投资工具.
上交所债券
债券现券市场概览
```
