# 16 科创行情 API（含港股主板空壳说明）

> 抓取时间：2026-10-08
> 源站点：<https://www.zhituapi.com/kcdataapi.html>
> 科创板独立文档页面（`kcdataapi.html`），共 3 个接口，路径前缀 `/tech/`。

## 股票列表

### 科创股票列表

**API 地址**：

```
https://api.zhituapi.com/tech/list/all?token=token证书
```

**描述**：获取基础的股票代码和名称，用于后续接口的参数传入。

**更新频率**：每日16:20

**请求频率限制**：包量版1分钟300次 |体验版、包月版1分钟1000次 | 包年版1分钟3千次 | 至尊版1分钟6千次

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| dm | string | 股票代码，如：688001.SH |
| mc | string | 股票名称，如：华兴源创 |
| jys | string | 交易所 |

**返回示例**：

```json
[
{
"dm":"688411",
"mc":"N海博",
"jys":"sh"
},
{
"dm":"001395",
"mc":"N亚联",
"jys":"sz"
},
{
"dm":"300766",
"mc":"每日互动",
"jys":"sz"
},
{
"dm":"301248",
"mc":"杰创智能",
"jys":"sz"
},
{
"dm":"301299",
"mc":"卓创资讯",
"jys":"sz"
},
{
"dm":"300229",
"mc":"拓尔思",
"jys":"sz"
},
{
"dm":"300996",
"mc":"普联软件",
"jys":"sz"
},
{
"dm":"300697",
"mc":"电工合金",
"jys":"sz"
}
]
```

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/tech/list/all?token=token证书"
response = requests.get(url)
data = response.json()
print(data)
```

## 实时交易

### 股票实时数据

**API 地址**：

```
https://api.zhituapi.com/tech/real/ssjy/股票代码(如688001)?token=token证书
```

**描述**：根据《科创股票列表》得到的股票代码获取实时交易数据（您可以理解为日线的最新数据），该接口为券商数据源。

**更新频率**：盘中实时

**请求频率限制**：包量版1分钟300次 |体验版、包月版1分钟1000次 | 包年版1分钟3千次 | 至尊版1分钟6千次

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| p | number | 最新价 |
| o | number | 开盘价 |
| h | number | 最高价 |
| l | number | 最低价 |
| yc | number | 前收盘价 |
| cje | number | 成交总额 |
| v | number | 成交总量 |
| pv | number | 原始成交总量 |
| ud | float | 涨跌额 |
| pc | float | 涨跌幅 |
| zf | float | 振幅 |
| t | string | 更新时间 |
| pe | number | 市盈率 |
| tr | number | 换手率 |
| pb_ratio | number | 市净率 |
| tv | number | 成交量 |

**返回示例**：

```json
{"o":11.69,"fm":0.17,"h":11.71,"hs":0.5,"lb":0.7,"l":11.55,"lt":225881388026.0,"pe":4.26,"pc":-0.17,"p":11.64,"sz":225884887825.0,"cje":1131033823.93,"ud":-0.02,"v":973969,"yc":11.66,"zf":1.37,"zs":0.17,"sjl":0.54,"zdf60":0.0,"zdfnc":-0.51,"t":"2025-02-2115:29:05"}]
```

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/tech/real/ssjy/股票代码(如688001)?token=token证书"
response = requests.get(url)
data = response.json()
print(data)
```

### 买卖五档盘口

**API 地址**：

```
https://api.zhituapi.com/tech/real/mmwp/股票代码(如688001)?token=token证书
```

**描述**：根据《科创股票列表》得到的股票代码获取实时买卖五档盘口数据。

**更新频率**：盘中实时

**请求频率限制**：包量版1分钟300次 |体验版、包月版1分钟1000次 | 包年版1分钟3千次 | 至尊版1分钟6千次

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| ps | number | 委卖价 |
| pb | number | 委买价 |
| vs | number | 委卖量 |
| vb | number | 委买量 |
| t | string | 更新时间 |

**返回示例**：

```json
{"t":"2025-02-2115:00:19","vc":-111,"vb":-0.17,"pb1":11.63,"vb1":424,"pb2":11.62,"vb2":1291,"pb3":11.61,"vb3":12014,"pb4":11.6,"vb4":11339,"pb5":11.59,"vb5":7333,"ps1":11.64,"vs1":7330,"ps2":11.65,"vs2":7698,"ps3":11.66,"vs3":7584,"ps4":11.67,"vs4":5842,"ps5":11.68,"vs5":4058}]
```

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/tech/real/mmwp/股票代码(如688001)?token=token证书"
response = requests.get(url)
data = response.json()
print(data)
```

## 港股主板 API

> 上游页面 `hkdataapi.html`（<https://www.zhituapi.com/hkdataapi.html>）截至 2026-10-08 仅有标题与站点导航，**无任何接口内容**（疑为待上线空壳页），故不收录。如需港股行情请再次核对上游页面。
