# 02 指数、行业、概念

> 抓取时间：2026-06-10
> 源站点：<https://www.zhituapi.com/hsstockapi.html>

## 指数、行业、概念树

**API 地址**：

```
https://api.zhituapi.com/hs/index/tree?token=token证书
```

**描述**：获取指数、行业、概念（包括基金，债券，美股，外汇，期货，黄金等的代码），其中isleaf为1（叶子节点）的记录的code（代码）可以作为下方接口的参数传入，从而得到某个指数、行业、概念下的相关股票。

**更新频率**：每周六03:05

**请求频率限制**：包量版1分钟300次 |体验版、包月版1分钟1000次 | 包年版1分钟3千次 | 至尊版1分钟6千次

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| name | string | 名称 |
| code | string | 代码 |
| type1 | number | 一级分类（0:A股,1:创业板,2:科创板,3:基金,4:香港股市,5:债券,6:美国股市,7:外汇,8:期货,9:黄金,10:英国股市） |
| type2 | number | 二级分类（0:A股-申万行业,1:A股-申万二级,2:A股-热门概念,3:A股-概念板块,4:A股-地域板块,5:A股-证监会行业,6:A股-分类,7:A股-指数成分,8:A股-风险警示,9:A股-大盘指数,10:A股-次新股,11:A股-沪港通,12:A股-深港通,13:基金-封闭式基金,14:基金-开放式基金,15:基金-货币型基金,16:基金-ETF基金净值,17:基金-ETF基金行情,18:基金-LOF基金行情,21:基金-科创板基金,22:香港股市-恒生行业,23:香港股市-全部港股,24:香港股市-热门港股,25:香港股市-蓝筹股,26:香港股市-红筹股,27:香港股市-国企股,28:香港股市-创业板,29:香港股市-指数,30:香港股市-A+H,31:香港股市-窝轮,32:香港股市-ADR,33:香港股市-沪港通,34:香港股市-深港通,35:香港股市-中华系列指数,36:债券-沪深债券,37:债券-深市债券,38:债券-沪市债券,39:债券-沪深可转债,40:美国股市-中国概念股,41:美国股市-科技类,42:美国股市-金融类,43:美国股市-制造零售类,44:美国股市-汽车能源类,45:美国股市-媒体类,46:美国股市-医药食品类,48:外汇-基本汇率,49:外汇-热门汇率,50:外汇-所有汇率,51:外汇-交叉盘汇率,52:外汇-美元相关汇率,53:外汇-人民币相关汇率,54:期货-全球期货,55:期货-中国金融期货交易所,56:期货-上海期货交易所,57:期货-大连商品交易所,58:期货-郑州商品交易所,59:黄金-黄金现货,60:黄金-黄金期货） |
| level | number | 层级，从0开始，根节点为0，二级节点为1，以此类推 |
| pcode | string | 父节点代码 |
| pname | string | 父节点名称 |
| isleaf | number | 是否为叶子节点，0：否，1：是 |

**返回示例**：

```json
[
    {
        "name": "A股-申万行业-煤炭",
        "code": "sw_mt",
        "type1": 0,
        "type2": 0,
        "level": 2,
        "pcode": "swhy",
        "pname": "A股-申万行业",
        "isleaf": 1
    },
    {
        "name": "A股-申万行业-石油石化",
        "code": "sw_sysh",
        "type1": 0,
        "type2": 0,
        "level": 2,
        "pcode": "swhy",
        "pname": "A股-申万行业",
        "isleaf": 1
    },
    {
        "name": "A股-申万行业-美容护理",
        "code": "sw_mrhl",
        "type1": 0,
        "type2": 0,
        "level": 2,
        "pcode": "swhy",
        "pname": "A股-申万行业",
        "isleaf": 1
    },
    {
        "name": "A股-申万行业-环保",
        "code": "sw_hb",
        "type1": 0,
        "type2": 0,
        "level": 2,
        "pcode": "swhy",
        "pname": "A股-申万行业",
        "isleaf": 1
    },
    {
        "name": "A股-申万行业-电力设备",
        "code": "sw_dlsb",
        "type1": 0,
        "type2": 0,
        "level": 2,
        "pcode": "swhy",
        "pname": "A股-申万行业",
        "isleaf": 1
    },
    {
        "name": "A股-申万行业-社会服务",
        "code": "sw_shfw",
        "type1": 0,
        "type2": 0,
        "level": 2,
        "pcode": "swhy",
        "pname": "A股-申万行业",
        "isleaf": 1
    },
    {
        "name": "A股-申万行业-商贸零售",
        "code": "sw_smls",
        "type1": 0,
        "type2": 0,
        "level": 2,
        "pcode": "swhy",
        "pname": "A股-申万行业",
        "isleaf": 1
    },
    {
        "name": "A股-申万行业-纺织服饰",
        "code": "sw_fzfs",
        "type1": 0,
        "type2": 0,
        "level": 2,
        "pcode": "swhy",
        "pname": "A股-申万行业",
        "isleaf": 1
    },
    {
        "name": "A股-申万行业-基础化工",
        "code": "sw_jchg",
        "type1": 0,
        "type2": 0,
        "level": 2,
        "pcode": "swhy",
        "pname": "A股-申万行业",
        "isleaf": 1
    }
]
```

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/hs/index/tree?token=token证书"
response = requests.get(url)
data = response.json()
print(data)
```

## 根据指数、行业、概念找相关股票

**API 地址**：

```
https://api.zhituapi.com/hs/index/stock/sw_sysh?token=ZHITU_TOKEN_LIMIT_TEST
```

**描述**：根据"指数、行业、概念树"接口得到的代码作为参数，得到相关的股票。

**更新频率**：每周六11:00

**请求频率限制**：包量版1分钟300次 |体验版、包月版1分钟1000次 | 包年版1分钟3千次 | 至尊版1分钟6千次

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| dm | string | 代码（根据接口参数可能是A股股票代码，也可能是其他指数、行业、概念的股票代码） |
| mc | string | 名称（根据接口参数可能是A股股票代码，也可能是其他指数、行业、概念的股票名称） |
| jys | string | 交易所，"sh"表示上证，"sz"表示深证（如果返回的是A股的股票，那么有值，否则是null） |

**返回示例**：

```json
[
    {
        "dm": "920088",
        "mc": "科力股份",
        "jys": "bj"
    },
    {
        "dm": "603798",
        "mc": "康普顿",
        "jys": "sh"
    },
    {
        "dm": "603727",
        "mc": "博迈科",
        "jys": "sh"
    },
    {
        "dm": "603619",
        "mc": "中曼石油",
        "jys": "sh"
    },
    {
        "dm": "603353",
        "mc": "和顺石油",
        "jys": "sh"
    },
    {
        "dm": "603223",
        "mc": "恒通股份",
        "jys": "sh"
    },
    {
        "dm": "601857",
        "mc": "中国石油",
        "jys": "sh"
    },
    {
        "dm": "601808",
        "mc": "中海油服",
        "jys": "sh"
    }
]
```

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/hs/index/stock/指数、行业、概念代码?token=token证书"
response = requests.get(url)
data = response.json()
print(data)
```

## 根据股票找相关指数、行业、概念

**API 地址**：

```
https://api.zhituapi.com/hs/index/index/000001?token=ZHITU_TOKEN_LIMIT_TEST
```

**描述**：根据《股票列表》得到的股票代码作为参数，得到相关的指数、行业、概念。

**更新频率**：每周六11:00

**请求频率限制**：包量版1分钟300次 |体验版、包月版1分钟1000次 | 包年版1分钟3千次 | 至尊版1分钟6千次

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| code | string | 指数、行业、概念代码，如：sw2_650300 |
| name | string | 指数、行业、概念名称，如：沪深股市-申万二级-国防军工-地面兵装 |

**返回示例**：

```json
[
    {
        "code": "sw_yx",
        "name": "A股-申万行业-银行"
    },
    {
        "code": "sw2_480300",
        "name": "A股-申万二级-股份制银行Ⅱ"
    },
    {
        "code": "chgn_700532",
        "name": "A股-热门概念-MSCI中国"
    },
    {
        "code": "chgn_700231",
        "name": "A股-热门概念-区块链"
    },
    {
        "code": "chgn_700095",
        "name": "A股-热门概念-融资融券"
    },
    {
        "code": "chgn_700216",
        "name": "A股-热门概念-证金汇金"
    },
    {
        "code": "chgn_700014",
        "name": "A股-热门概念-大盘"
    },
    {
        "code": "gn_rzrq",
        "name": "A股-概念板块-融资融券"
    },
    {
        "code": "gn_wzbj",
        "name": "A股-概念板块-外资背景"
    },
    {
        "code": "gn_byjj",
        "name": "A股-概念板块-本月解禁"
    },
    {
        "code": "gn_sbzc",
        "name": "A股-概念板块-社保重仓"
    }
]
```

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/hs/index/index/股票代码?token=token证书"
response = requests.get(url)
data = response.json()
print(data)
```
