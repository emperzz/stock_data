# 15 京市 A 股 API

> 抓取时间：2026-10-08
> 源站点：<https://www.zhituapi.com/bjdataapi.html>
> 北交所股票独立文档页面（`bjdataapi.html`）。路径前缀 `/bj/`（以各节 API 地址为准）。

## 股票列表

### 京市股票列表

**API 地址**：

```
https://api.zhituapi.com/bj/list/all?token=token证书
```

**描述**：获取基础的股票代码和名称，用于后续接口的参数传入。

**更新频率**：每日16:20

**请求频率限制**：包量版1分钟300次 |体验版、包月版1分钟1000次 | 包年版1分钟3千次 | 至尊版1分钟6千次

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| dm | string | 股票代码，如：430017.BJ |
| mc | string | 股票名称，如：星昊医药 |
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
url = "https://api.zhituapi.com/bj/list/all?token=token证书"
response = requests.get(url)
data = response.json()
print(data)
```

### 京市指数列表

**API 地址**：

```
https://api.zhituapi.com/bj/list/index?token=token证书
```

**描述**：获取基础的股票代码和名称，用于后续接口的参数传入。

**更新频率**：每日16:20

**请求频率限制**：包量版1分钟300次 |体验版、包月版1分钟1000次 | 包年版1分钟3千次 | 至尊版1分钟6千次

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| dm | string | 指数代码，如：899050.BJ |
| mc | string | 指数名称，如：北证50 |
| jys | string | 交易所 |

**返回示例**：

```json
[{"dm":"899050.BJ","mc":"北证50","jys":"BJ"},{"dm":"899601.BJ","mc":"北证专精特新","jys":"BJ"}]
```

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/bj/list/index?token=token证书"
response = requests.get(url)
data = response.json()
print(data)
```

## 实时交易

### 股票实时数据

**API 地址**：

```
https://api.zhituapi.com/bj/stock/real/ssjy/股票代码(如920000)?token=token证书
```

**描述**：根据《京市股票列表》得到的股票代码获取实时交易数据（您可以理解为日线的最新数据），该接口为券商数据源。

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
url = "https://api.zhituapi.com/bj/stock/real/ssjy/股票代码(如920000)?token=token证书"
response = requests.get(url)
data = response.json()
print(data)
```

### 买卖五档盘口

**API 地址**：

```
https://api.zhituapi.com/bj/stock/real/mmwp/股票代码(如920000)?token=token证书
```

**描述**：根据《京市股票列表》得到的股票代码获取实时买卖五档盘口数据。

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
url = "https://api.zhituapi.com/bj/stock/real/mmwp/股票代码(如920000)?token=token证书"
response = requests.get(url)
data = response.json()
print(data)
```

### 指数实时数据

**API 地址**：

```
https://api.zhituapi.com/bj/index/real/ssjy/股票代码(如430017)?token=token证书
```

**描述**：根据《京市指数列表》得到的指数代码获取实时交易数据（您可以理解为日线的最新数据），该接口为券商数据源。

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

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/bj/index/real/ssjy/股票代码(如430017)?token=token证书"
response = requests.get(url)
data = response.json()
print(data)
```

### 当天逐笔交易【京】

**API 地址**：

```
https://api.zhituapi.com/bj/stock/real/zbjy/股票代码(如920000)?token=token证书
```

**描述**：根据《京市股票列表》得到的股票代码获取当天逐笔交易数据，按时间倒序。每个交易日开盘后返回的均为当日数据；交易时段内约每 60 分钟更新一次，收盘后由盘后任务定稿。历史交易日请使用「历史逐笔交易」接口。数据与沪深逐笔同源归档；北交所代码一般为 92 开头（如 920000）。

**更新频率**：交易时段约60分钟更新1次（盘后定稿）

**请求频率限制**：包量版1分钟300次 |体验版、包月版1分钟1000次 | 包年版1分钟3千次 | 至尊版1分钟6千次

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| d | string | 数据归属日期（yyyy-MM-dd） |
| t | string | 时间（HH:mm:ss） |
| v | number | 成交量（股） |
| p | number | 成交价 |
| ts | number | 交易方向（0：中性盘，1：买入，2：卖出） |

**返回示例**：

```json
[{"d": "2026-08-13", "t": "15:00:00", "v": 1000, "p": 8.5, "ts": 1}, {"d": "2026-08-13", "t": "14:57:00", "v": 500, "p": 8.48, "ts": 2}]
```

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/bj/stock/real/zbjy/股票代码(如920000)?token=token证书"
response = requests.get(url)
data = response.json()
print(data)
```

### 历史逐笔交易【京】

**API 地址**：

```
https://api.zhituapi.com/bj/stock/real/zbjy/交易日期(如20260813)/股票代码(如920000)?token=token证书
```

**描述**：按交易日期与京市股票代码获取历史逐笔交易数据，字段与「当天逐笔交易」一致，按时间倒序。重要：本接口数据自 2026-08-13（含）起开始累积归档；2026-08-13 之前的交易日无历史逐笔数据。交易日期格式为 yyyyMMdd（如 20260813）。

**更新频率**：按交易日盘后归档（自2026-08-13起累积）

**请求频率限制**：包量版1分钟300次 |体验版、包月版1分钟1000次 | 包年版1分钟3千次 | 至尊版1分钟6千次

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| d | string | 数据归属日期（yyyy-MM-dd） |
| t | string | 时间（HH:mm:ss） |
| v | number | 成交量（股） |
| p | number | 成交价 |
| ts | number | 交易方向（0：中性盘，1：买入，2：卖出） |

**返回示例**：

```json
[{"d": "2026-08-13", "t": "15:00:00", "v": 1000, "p": 8.5, "ts": 1}, {"d": "2026-08-13", "t": "14:57:00", "v": 500, "p": 8.48, "ts": 2}]
```

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/bj/stock/real/zbjy/交易日期(如20260813)/股票代码(如920000)?token=token证书"
response = requests.get(url)
data = response.json()
print(data)
```

## 行情数据

### 历史分时交易【京】

**API 地址**：

```
https://api.zhituapi.com/bj/history/股票代码.市场（如920547.BJ）/分时级别(如d)/除权方式?token=token证书&st=开始时间(如20240101)&et=结束时间(如20260630)
```

**描述**：根据《京市股票列表》得到的股票代码和分时级别获取历史交易数据，交易时间升序。目前分时级别支持5分钟、15分钟、30分钟、60分钟、日线、周线、月线、年线，对应的请求参数分别为5、15、30、60、d、w、m、y，日线以上除权方式有不复权、前复权、后复权、等比前复权、等比后复权，对应的参数分别为n、f、b、fr、br，分钟级无除权数据，对应的参数为n。开始时间以及结束时间的格式均为 YYYYMMDD 或 YYYYMMDDhhmmss，例如：'20250101' 或'20251231235959'。不设置开始时间和结束时间则为全部历史数据。同时可以指定获取数据条数，例如指定lt=10，则获取最新的10条数据；另：1 分钟分时请使用「最新/历史分时交易（Pro版）」路径（含 /pro/），勿在常规分时接口传 period=1

**更新频率**：分钟级别数据盘中更新，分时越小越优先更新，如5分钟级别会每5分钟更新，15分钟级别会每15分钟更新，以此类推，日线及以上级别每日15:30开始更新，预计17:10完成

**请求频率限制**：包量版1分钟300次 |体验版、包月版1分钟1000次 | 包年版1分钟3千次 | 至尊版1分钟6千次

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| t | string | 交易时间 |
| o | float | 开盘价 |
| h | float | 最高价 |
| l | float | 最低价 |
| c | float | 收盘价 |
| v | float | 成交量 |
| a | float | 成交额 |
| pc | float | 前收盘价 |
| sf | int | 停牌 1停牌，0 不停牌 |

**返回示例**：

```json
[
  {
    "t": "2025-06-03 00:00:00",
    "o": 21,
    "h": 21.76,
    "l": 21,
    "c": 21.3,
    "v": 17782,
    "a": 37951440,
    "pc": 21.84,
    "sf": 0
  },
  {
    "t": "2025-06-04 00:00:00",
    "o": 21.29,
    "h": 21.57,
    "l": 21.22,
    "c": 21.39,
    "v": 10654,
    "a": 22780321,
    "pc": 21.3,
    "sf": 0
  },
  {
    "t": "2025-06-05 00:00:00",
    "o": 21.39,
    "h": 21.55,
    "l": 21.22,
    "c": 21.54,
    "v": 10888,
    "a": 23308193,
    "pc": 21.39,
    "sf": 0
  },
  {
    "t": "2025-06-06 00:00:00",
    "o": 21.58,
    "h": 22.1,
    "l": 21.33,
    "c": 21.52,
    "v": 17951,
    "a": 38837930,
    "pc": 21.54,
    "sf": 0
  }]
```

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/bj/history/股票代码.市场（如920547.BJ）/分时级别(如d)/除权方式?token=token证书&st=开始时间(如20240101)&et=结束时间(如20260630)"
response = requests.get(url)
data = response.json()
print(data)
```

### 最新分时交易（Pro版）【京】

**API 地址**：

```
https://api.zhituapi.com/bj/pro/latest/股票代码.市场（如920000.BJ）/1/除权方式(如n)?token=token证书&lt=最新条数(如5)
```

**描述**：API扩能包专属。路径须含 /pro/。获取京市 A 股最新 1 分钟 K 线（period 固定为 1）。除权参数分钟级请使用 n。基础证过期时只要 API Pro 仍有效仍可调用。亦可经专属域名 https://p.zhituapi.com 同路径访问。

**更新频率**：1 分钟级数据由 Redis 提供；盘中增量更新，需已开通「API扩能包」

**请求频率限制**：需有效 token + 已开通且未过期的 API扩能包；基础证过期时只要 API Pro 未到期仍可调用本接口。限流同证书档位

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| t | string | 交易时间（北京时间），格式 yyyy-MM-dd HH:mm:ss |
| o | float | 开盘价 |
| h | float | 最高价 |
| l | float | 最低价 |
| c | float | 收盘价 |
| v | float | 成交量 |
| a | float | 成交额 |
| pc | float | 前收价（若有） |
| sf | float | 停牌标志，0 表示正常交易，非 0 表示停牌（若有） |

**返回示例**：

```json
[{"t":"2026-09-10 14:59:00","o":11.2,"h":11.25,"l":11.18,"c":11.22,"v":123456,"a":1380000,"pc":11.19,"sf":0}]
```

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/bj/pro/latest/股票代码.市场（如920000.BJ）/1/除权方式(如n)?token=token证书&lt=最新条数(如5)"
response = requests.get(url)
data = response.json()
print(data)
```

### 历史分时交易（Pro版）【京】

**API 地址**：

```
https://api.zhituapi.com/bj/pro/history/股票代码.市场（如920000.BJ）/1/除权方式(如n)?token=token证书&st=开始时间&et=结束时间&lt=最新条数
```

**描述**：API扩能包专属。路径须含 /pro/。获取京市 A 股 1 分钟历史 K 线（period 固定为 1）。除权参数分钟级请使用 n。基础证过期时只要 API Pro 仍有效仍可调用。亦可经专属域名 https://p.zhituapi.com 同路径访问。

**更新频率**：1 分钟级数据由 Redis 提供；盘中增量更新，需已开通「API扩能包」

**请求频率限制**：需有效 token + 已开通且未过期的 API扩能包；基础证过期时只要 API Pro 未到期仍可调用本接口。限流同证书档位

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| t | string | 交易时间（北京时间），格式 yyyy-MM-dd HH:mm:ss |
| o | float | 开盘价 |
| h | float | 最高价 |
| l | float | 最低价 |
| c | float | 收盘价 |
| v | float | 成交量 |
| a | float | 成交额 |
| pc | float | 前收价（若有） |
| sf | float | 停牌标志，0 表示正常交易，非 0 表示停牌（若有） |

**返回示例**：

```json
[{"t":"2026-09-10 14:59:00","o":11.2,"h":11.25,"l":11.18,"c":11.22,"v":123456,"a":1380000,"pc":11.19,"sf":0}]
```

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/bj/pro/history/股票代码.市场（如920000.BJ）/1/除权方式(如n)?token=token证书&st=开始时间&et=结束时间&lt=最新条数"
response = requests.get(url)
data = response.json()
print(data)
```

### 完整历史分时交易（Pro版）【京】

**API 地址**：

```
https://p.zhituapi.com/bj/history/full/{股票代码}/{分时级别}/{除权方式}?token=token证书
```

**描述**：API扩能包专属。根据京市股票代码与分时级别获取该标的完整历史分钟K线。请求路径：https://p.zhituapi.com/bj/history/full/{股票代码}/{分时级别}/{除权方式}?token=。分时级别支持 1、5、15、30、60；分钟级除权方式请使用 n。可选查询参数 year=YYYY，仅获取指定年份；不传 year 则按时间顺序返回全部历史。本接口托管于 Pro 专用域名，推荐直接请求 https://p.zhituapi.com；若仍请求 api.zhituapi.com 同路径，网关将 302 跳转至 Pro 域名（过渡期也可能由主站直出）。沪深主流标的分钟线最长可回溯至约 1991 年（三十余年，以标的可采数据为准）；不传 year 时按年片合并返回全部可采历史；传 year=YYYY 仅返回该年。本年度数据每月更新 1 次，获取本年度最新分钟线请使用含 /pro/ 的最新/历史分时或常规分时接口。鉴权为 Query 参数 token=；未开通或已过期的 API扩能包将返回 108；本接口限流为每分钟 60 次。

**更新频率**：历史年片最长可回溯至约1991年（以标的为准）；本年度数据每月更新1次。若需本年度最新分钟线，建议改用常规历史/最新分时接口（含 /pro/ 的 1 分钟滚动窗口）

**请求频率限制**：1分钟60次；仅 API扩能包可用

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| t | string | 交易时间（北京时间），格式 yyyy-MM-dd HH:mm:ss |
| o | float | 开盘价 |
| h | float | 最高价 |
| l | float | 最低价 |
| c | float | 收盘价 |
| v | float | 成交量 |
| a | float | 成交额 |
| pc | float | 前收价（若有） |
| sf | float | 停牌标志，0 表示正常交易，非 0 表示停牌（若有） |

**返回示例**：

```json
[{"t":"2010-01-04 10:30:00","o":24.52,"h":24.56,"l":24.21,"c":24.24,"v":40553.0,"a":98799520.0,"pc":24.37,"sf":0}]
```

**Python 接入示例**：

```python
import requests
url = "https://p.zhituapi.com/bj/history/full/{股票代码}/{分时级别}/{除权方式}?token=token证书"
response = requests.get(url)
data = response.json()
print(data)
```

### 历史分时MACD（Pro版·1分钟）【京】

**API 地址**：

```
https://api.zhituapi.com/bj/pro/history/macd/股票代码(如920000.BJ)/1/除权类型(如n)?token=token证书&st=开始时间&et=结束时间&lt=最新条数
```

**描述**：API扩能包专属。路径须含 /pro/history/macd/。根据《京市股票列表》代码获取1分钟历史MACD（period 固定为 1）。除权参数请使用 n。支持 st/et/lt。请勿再使用普通路径 /bj/history/macd/…/1/（已停止开放）。

**更新频率**：基于 1 分钟历史分时实时计算；盘中可结合 Redis :today 合并。须已开通且未过期的「API扩能包」。

**请求频率限制**：需有效证书 + API扩能包未过期；基础证过期时只要 Pro 未到期仍可调用。限流同证书档位。普通路径 period=1 已关闭。

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| t | string | 交易时间，分钟级格式为 yyyy-MM-dd HH:mm:ss |
| diff | number | DIFF值 |
| dea | number | DEA值 |
| macd | number | MACD值 |
| ema12 | number | EMA（12）值 |
| ema26 | number | EMA（26）值 |

**返回示例**：

```json
[{"t":"2026-09-30 14:59:00","diff":-0.005,"dea":-0.004,"macd":-0.002,"ema12":11.5868,"ema26":11.5921},{"t":"2026-09-30 15:00:00","diff":-0.006,"dea":-0.005,"macd":-0.003,"ema12":11.5842,"ema26":11.5905}]
```

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/bj/pro/history/macd/股票代码(如920000.BJ)/1/除权类型(如n)?token=token证书&st=开始时间&et=结束时间&lt=最新条数"
response = requests.get(url)
data = response.json()
print(data)
```

### 历史分时MA（Pro版·1分钟）【京】

**API 地址**：

```
https://api.zhituapi.com/bj/pro/history/ma/股票代码(如920000.BJ)/1/除权类型(如n)?token=token证书&st=开始时间&et=结束时间&lt=最新条数
```

**描述**：API扩能包专属。路径须含 /pro/history/ma/。根据《京市股票列表》代码获取1分钟历史MA（period 固定为 1）。除权参数请使用 n。支持 st/et/lt。请勿再使用普通路径 /bj/history/ma/…/1/（已停止开放）。

**更新频率**：基于 1 分钟历史分时实时计算；盘中可结合 Redis :today 合并。须已开通且未过期的「API扩能包」。

**请求频率限制**：需有效证书 + API扩能包未过期；基础证过期时只要 Pro 未到期仍可调用。限流同证书档位。普通路径 period=1 已关闭。

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| t | string | 交易时间，分钟级格式为 yyyy-MM-dd HH:mm:ss |
| ma3 | number | MA3，没有则为null |
| ma5 | number | MA5，没有则为null |
| ma10 | number | MA10，没有则为null |
| ma15 | number | MA15，没有则为null |
| ma20 | number | MA20，没有则为null |
| ma30 | number | MA30，没有则为null |
| ma60 | number | MA60，没有则为null |
| ma120 | number | MA120，没有则为null |
| ma200 | number | MA200，没有则为null |
| ma250 | number | MA250，没有则为null |

**返回示例**：

```json
[{"t":"2026-09-30 15:00:00","ma3":11.58,"ma5":11.582,"ma10":11.59,"ma15":11.595,"ma20":11.6,"ma30":11.61,"ma60":11.62,"ma120":null,"ma200":null,"ma250":null}]
```

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/bj/pro/history/ma/股票代码(如920000.BJ)/1/除权类型(如n)?token=token证书&st=开始时间&et=结束时间&lt=最新条数"
response = requests.get(url)
data = response.json()
print(data)
```

### 历史分时BOLL（Pro版·1分钟）【京】

**API 地址**：

```
https://api.zhituapi.com/bj/pro/history/boll/股票代码(如920000.BJ)/1/除权类型(如n)?token=token证书&st=开始时间&et=结束时间&lt=最新条数
```

**描述**：API扩能包专属。路径须含 /pro/history/boll/。根据《京市股票列表》代码获取1分钟历史BOLL（period 固定为 1）。除权参数请使用 n。支持 st/et/lt。请勿再使用普通路径 /bj/history/boll/…/1/（已停止开放）。

**更新频率**：基于 1 分钟历史分时实时计算；盘中可结合 Redis :today 合并。须已开通且未过期的「API扩能包」。

**请求频率限制**：需有效证书 + API扩能包未过期；基础证过期时只要 Pro 未到期仍可调用。限流同证书档位。普通路径 period=1 已关闭。

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| t | string | 交易时间，分钟级格式为 yyyy-MM-dd HH:mm:ss |
| u | number | 上轨 |
| d | number | 下轨 |
| m | number | 中轨 |

**返回示例**：

```json
[{"t":"2026-09-30 15:00:00","u":11.65,"d":11.49,"m":11.57}]
```

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/bj/pro/history/boll/股票代码(如920000.BJ)/1/除权类型(如n)?token=token证书&st=开始时间&et=结束时间&lt=最新条数"
response = requests.get(url)
data = response.json()
print(data)
```

### 历史分时KDJ（Pro版·1分钟）【京】

**API 地址**：

```
https://api.zhituapi.com/bj/pro/history/kdj/股票代码(如920000.BJ)/1/除权类型(如n)?token=token证书&st=开始时间&et=结束时间&lt=最新条数
```

**描述**：API扩能包专属。路径须含 /pro/history/kdj/。根据《京市股票列表》代码获取1分钟历史KDJ（period 固定为 1）。除权参数请使用 n。支持 st/et/lt。请勿再使用普通路径 /bj/history/kdj/…/1/（已停止开放）。

**更新频率**：基于 1 分钟历史分时实时计算；盘中可结合 Redis :today 合并。须已开通且未过期的「API扩能包」。

**请求频率限制**：需有效证书 + API扩能包未过期；基础证过期时只要 Pro 未到期仍可调用。限流同证书档位。普通路径 period=1 已关闭。

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| t | string | 交易时间，分钟级格式为 yyyy-MM-dd HH:mm:ss |
| k | number | K值 |
| d | number | D值 |
| j | number | J值 |

**返回示例**：

```json
[{"t":"2026-09-30 15:00:00","k":45.2,"d":48.1,"j":39.4}]
```

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/bj/pro/history/kdj/股票代码(如920000.BJ)/1/除权类型(如n)?token=token证书&st=开始时间&et=结束时间&lt=最新条数"
response = requests.get(url)
data = response.json()
print(data)
```

## 财务报表

### 资产负债表【京】

**API 地址**：

```
https://api.zhituapi.com/bj/fin/balance/股票代码（如920547.BJ）?token=token证书&st=开始时间&et=结束时间
```

**描述**：根据《京市股票列表》得到的股票代码获取资产负债表，开始时间以及结束时间的格式均为 YYYYMMDD，例如：'20240101'。不设置开始时间和结束时间则为全部数据。

**更新频率**：每日0点

**请求频率限制**：包量版1分钟300次 |体验版、包月版1分钟1000次 | 包年版1分钟3千次 | 至尊版1分钟6千次

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| jzrq | string | 截止日期 |
| plrq | string | 披露日期 |
| nbysk | float | 内部应收款 |
| gdzcql | float | 固定资产清理 |
| yffbzk | float | 应付分保账款 |
| jsbfj | float | 结算备付金 |
| ysbf | float | 应收保费 |
| ysfbzk | float | 应收分保账款 |
| ysfbhtzbj | float | 应收分保合同准备金 |
| ysgl | float | 应收股利 |
| ysckts | float | 应收出口退税 |
| ysbtk | float | 应收补贴款 |
| ysbzj | float | 应收保证金 |
| dfy | float | 待摊费用 |
| dclldzcsy | float | 待处理流动资产损益 |
| ynndqdfldzc | float | 一年内到期的非流动资产 |
| cqysk | float | 长期应收款 |
| qtcqtz | float | 其他长期投资 |
| gdzcyz | float | 固定资产原值 |
| gdzcjz | float | 固定资产净值 |
| gdzcjzzbj | float | 固定资产减值准备 |
| scxswzc | float | 生产性生物资产 |
| gyxswzc | float | 公益性生物资产 |
| yqzc | float | 油气资产 |
| kfzc | float | 开发支出 |
| gqfzltq | float | 股权分置流通权 |
| qtfldzc | float | 其他非流动资产 |
| yfsxfyj | float | 应付手续费及佣金 |
| qtjyk | float | 其他应交款 |
| yfbzj | float | 应付保证金 |
| nbyfk | float | 内部应付款 |
| ytfy | float | 预提费用 |
| bxhtzbj | float | 保险合同准备金 |
| dlmmzqk | float | 代理买卖证券款 |
| dlcxzqk | float | 代理承销证券款 |
| gjpjjs | float | 国际票证结算 |
| gnpjjs | float | 国内票证结算 |
| dysr | float | 递延收益 |
| yfdqzq | float | 应付短期债券 |
| cqdysr | float | 长期递延收益 |
| wqddtzss | float | 未确定的投资损失 |
| nfpxjgl | float | 拟分配现金股利 |
| yjfz | float | 预计负债 |
| xsckjtycf | float | 吸收存款及同业存放 |
| yjldfz | float | 预计流动负债 |
| j_kcg | float | 减:库存股 |
| hbzj | float | 货币资金 |
| cczj | float | 拆出资金 |
| jyxjrzc | float | 交易性金融资产 |
| ysjrzc | float | 衍生金融资产 |
| yspj | float | 应收票据 |
| yszk | float | 应收账款 |
| yfkx | float | 预付款项 |
| yslx | float | 应收利息 |
| qtysk | float | 其他应收款 |
| mrfsjrzck | float | 买入返售金融资产款 |
| gyjzjzbdqjsrdq | float | 以公允价值计量且其变动计入当期损益的金融资产 |
| ch | float | 存货 |
| qtldzc | float | 其他流动资产 |
| ldzchj | float | 流动资产合计 |
| ffdkjjd | float | 发放贷款及垫款 |
| kkgsjrzc | float | 可供出售金融资产 |
| cyzdqtz | float | 持有至到期投资 |
| cqgqtz | float | 长期股权投资 |
| tzxfd | float | 投资性房地产 |
| ljzj | float | 累计折旧 |
| gdzc | float | 固定资产 |
| zjgc | float | 在建工程 |
| gcwz | float | 工程物资 |
| cqfz | float | 长期负债 |
| wxzc | float | 无形资产 |
| sy | float | 商誉 |
| cqdtfy | float | 长期待摊费用 |
| dysdszc | float | 递延所得税资产 |
| fldzchj | float | 非流动资产合计 |
| zczj | float | 资产总计 |
| dqjk | float | 短期借款 |
| xzyhyhk | float | 向中央银行借款 |
| crzj | float | 拆入资金 |
| jyxjrfz | float | 交易性金融负债 |
| ysjrfz | float | 衍生金融负债 |
| yfpj | float | 应付票据 |
| yfzk | float | 应付账款 |
| ysk | float | 预收账款 |
| mchgjrzck | float | 卖出回购金融资产款 |
| yfgzxc | float | 应付职工薪酬 |
| yjsf | float | 应交税费 |
| yflx | float | 应付利息 |
| yfgl | float | 应付股利 |
| qtfzk | float | 其他应付款 |
| ynndqdfldfz | float | 一年内到期的非流动负债 |
| qtldfz | float | 其他流动负债 |
| ldfzhj | float | 流动负债合计 |
| cqjk | float | 长期借款 |
| yfzq | float | 应付债券 |
| cqyfk | float | 长期应付款 |
| zxyfk | float | 专项应付款 |
| dysdsfz | float | 递延所得税负债 |
| qtfldfz | float | 其他非流动负债 |
| fldfzhj | float | 非流动负债合计 |
| fzhj | float | 负债合计 |
| sszb | float | 实收资本(或股本) |
| zbgj | float | 资本公积 |
| zxzb | float | 专项储备 |
| ylgj | float | 盈余公积 |
| ybfxzb | float | 一般风险准备 |
| wfplr | float | 未分配利润 |
| wbbzbzhc | float | 外币报表折算差额 |
| gsmgdqsyhj | float | 归属于母公司股东权益合计 |
| ssgdqy | float | 少数股东权益 |
| syzqyhj | float | 所有者权益合计 |
| fzhgdqyzj | float | 负债和股东权益总计 |

**返回示例**：

```json
"[
```

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/bj/fin/balance/股票代码（如920547.BJ）?token=token证书&st=开始时间&et=结束时间"
response = requests.get(url)
data = response.json()
print(data)
```

### 利润表【京】

**API 地址**：

```
https://api.zhituapi.com/bj/fin/income/股票代码（如920547.BJ）?token=token证书&st=开始时间&et=结束时间
```

**描述**：根据《京市股票列表》得到的股票代码获取利润表，开始时间以及结束时间的格式均为 YYYYMMDD，例如：'20240101'。不设置开始时间和结束时间则为全部数据。

**更新频率**：每日0点

**请求频率限制**：包量版1分钟300次 |体验版、包月版1分钟1000次 | 包年版1分钟3千次 | 至尊版1分钟6千次

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| jzrq | string | 截止日期 |
| plrq | string | 披露日期 |
| yysr | float | 营业收入 |
| yzbf | float | 已赚保费 |
| fdczssr | float | 房地产销售收入 |
| yyzcb | float | 营业总成本 |
| fdczscb | float | 房地产销售成本 |
| yffy | float | 研发费用 |
| tbj | float | 退保金 |
| pczjje | float | 赔付支出净额 |
| tqbxhtzbjje | float | 提取保险合同准备金净额 |
| bdhlzc | float | 保单红利支出 |
| fbfy | float | 分保费用 |
| gyjzbdsy | float | 公允价值变动收益 |
| qhsy | float | 期货损益 |
| tgsy | float | 托管收益 |
| btsr | float | 补贴收入 |
| qtywlr | float | 其他业务利润 |
| bhbfzhbqsljlr | float | 被合并方在合并前实现净利润 |
| lxsr | float | 利息收入 |
| sxfjyjsr | float | 手续费及佣金收入 |
| sxfjyjzc | float | 手续费及佣金支出 |
| qtywcb | float | 其他业务成本 |
| hdsy | float | 汇兑收益 |
| fldzcczsy | float | 非流动资产处置收益 |
| sdsfy | float | 所得税费用 |
| wqrtzss | float | 未确认投资损失 |
| gsmgsyzzdjlr | float | 归属于母公司所有者的净利润 |
| lxzc | float | 利息支出 |
| qtywsr | float | 其他业务收入 |
| yyzsr | float | 营业总收入 |
| yycb | float | 营业成本 |
| yysjjfj | float | 营业税金及附加 |
| xsfy | float | 销售费用 |
| glfy | float | 管理费用 |
| cwfy | float | 财务费用 |
| zcjzss | float | 资产减值损失 |
| tzsy | float | 投资收益 |
| lyqyhhhqydtzsy | float | 联营企业和合营企业的投资收益 |
| yylr | float | 营业利润 |
| ywsr | float | 营业外收入 |
| ywzc | float | 营业外支出 |
| lrze | float | 利润总额 |
| jlr | float | 净利润 |
| jlrhfcjcx | float | 净利润(扣除非经常性损益后) |
| ssgdsy | float | 少数股东损益 |
| jbmgsy | float | 基本每股收益 |
| xsmgsy | float | 稀释每股收益 |
| zhsyz | float | 综合收益总额 |
| gsssgdzhsyz | float | 归属于少数股东的综合收益总额 |
| qtsy | float | 其他收益 |

**返回示例**：

```json
"[
```

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/bj/fin/income/股票代码（如920547.BJ）?token=token证书&st=开始时间&et=结束时间"
response = requests.get(url)
data = response.json()
print(data)
```

### 现金流量表【京】

**API 地址**：

```
https://api.zhituapi.com/bj/fin/cashflow/股票代码（如920547.BJ）?token=token证书&st=开始时间&et=结束时间
```

**描述**：根据《京市股票列表》得到的股票代码获取现金流量表，开始时间以及结束时间的格式均为 YYYYMMDD，例如：'20240101'。不设置开始时间和结束时间则为全部数据。

**更新频率**：每日0点

**请求频率限制**：包量版1分钟300次 |体验版、包月版1分钟1000次 | 包年版1分钟3千次 | 至尊版1分钟6千次

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| jzrq | string | 截止日期 |
| plrq | string | 披露日期 |
| sdydbxbfqdxj | float | 收到原保险合同保费取得的现金 |
| sdzbxywxjjje | float | 收到再保险业务现金净额 |
| bhcjjtkkjzje | float | 保户储金及投资款净增加额 |
| czjyxjrzcjzje | float | 处置交易性金融资产净增加额 |
| sqlxsxfjyjdxj | float | 收取利息、手续费及佣金的现金 |
| hgywzjjzje | float | 回购业务资金净增加额 |
| zfybxhtpfkxdj | float | 支付原保险合同赔付款项的现金 |
| zfbdhldxj | float | 支付保单红利的现金 |
| czfzgsjqtsddxj | float | 处置子公司及其他收到的现金 |
| jszyhdqckssddxj | float | 减少质押和定期存款所收到的现金 |
| tzszfdxj | float | 投资所支付的现金 |
| zydkjzje | float | 质押贷款净增加额 |
| qdfzgsjqtywdwzfdxjje | float | 取得子公司及其他营业单位支付的现金净额 |
| zjzyhdqckszfdxj | float | 增加质押和定期存款所支付的现金 |
| qzfzgsxrxj | float | 其中子公司吸收现金 |
| qz:fzgszfgsssgdglr | float | 其中:子公司支付给少数股东的股利、利润 |
| ssgdsy | float | 少数股东损益 |
| wqrdtzss | float | 未确认的投资损失 |
| dysyzj(j:js) | float | 递延收益增加(减:减少) |
| yjfz | float | 预计负债 |
| jxyyfxmdzj | float | 经营性应付项目的增加 |
| ywgwswjskdjs(j:zj) | float | 已完工尚未结算款的减少(减:增加) |
| yjswgwgdjz(j:js) | float | 已结算尚未完工款的增加(减:减少) |
| xssptglwsddxj | float | 销售商品、提供劳务收到的现金 |
| khckhtyckxkjzje | float | 客户存款和同业存放款项净增加额 |
| xzyhyhkjzje | float | 向中央银行借款净增加额(万元) |
| xtjrgjqjcrzjjzje | float | 向其他金融机构拆入资金净增加额 |
| sddsfyfh | float | 收到的税费与返还 |
| tzzfdxj | float | 投资支付的现金 |
| sdqtyjyghdxj | float | 收到的其他与经营活动有关的现金 |
| jyhdxjlrxj | float | 经营活动现金流入小计 |
| gmspjslwzfdxj | float | 购买商品、接受劳务支付的现金 |
| khdkjdknzje | float | 客户贷款及垫款净增加额 |
| cfzyxhytckxkjzje | float | 存放中央银行和同业款项净增加额 |
| zflxsxfjyjdxj | float | 支付利息、手续费及佣金的现金 |
| zfgzyjwzgzfdxj | float | 支付给职工以及为职工支付的现金 |
| zfdgxsf | float | 支付的各项税费 |
| zfqtyjyghdxj | float | 支付其他与经营活动有关的现金 |
| jyhdxjlcxj | float | 经营活动现金流出小计 |
| jyhdcsdxjlje | float | 经营活动产生的现金流量净额 |
| shtzssddxj | float | 收回投资所收到的现金 |
| qdtzsysddxj | float | 取得投资收益所收到的现金 |
| czgdzcwxzhqtqctzssddxj | float | 处置固定资产、无形资产和其他长期投资收到的现金 |
| sdqtytzghdxj | float | 收到的其他与投资活动有关的现金 |
| tzhdxjlrxj | float | 投资活动现金流入小计 |
| gjgdzcwxzhqtqctzzfdxj | float | 购建固定资产、无形资产和其他长期投资支付的现金 |
| tzhdxjlcxj | float | 投资活动现金流出小计 |
| tzhdcsdxjlxj | float | 投资活动产生的现金流量净额 |
| xstzsdj | float | 吸收投资收到的现金 |
| qdjkjddxj | float | 取得借款收到的现金 |
| fxzjsddxj | float | 发行债券收到的现金 |
| sdqtczghdxj | float | 收到其他与筹资活动有关的现金 |
| czhdxjlrxj | float | 筹资活动现金流入小计 |
| chzwzfxj | float | 偿还债务支付现金 |
| fpglrlhcllxzfdxj | float | 分配股利、利润或偿付利息支付的现金 |
| zfqtczdxj | float | 支付其他与筹资的现金 |
| czhdxjlcxj | float | 筹资活动现金流出小计 |
| czhdcsdxjlxj | float | 筹资活动产生的现金流量净额 |
| hlbddxjdxy | float | 汇率变动对现金的影响 |
| xjxjdhwjzje | float | 现金及现金等价物净增加额 |
| qcxjjxjdhwye | float | 期初现金及现金等价物余额 |
| qmxjjxjdhwye | float | 期末现金及现金等价物余额 |
| jlr | float | 净利润 |
| zcjzzb | float | 资产减值准备 |
| gdzczjyqzcshscxwzczj | float | 固定资产折旧、油气资产折耗、生产性物资折旧 |
| wxzctx | float | 无形资产摊销 |
| cqdtfytx | float | 长期待摊费用摊销 |
| dtfydjs | float | 待摊费用的减少 |
| ytfydzj | float | 预提费用的增加 |
| czgdzcwxzhqtqctzss | float | 处置固定资产、无形资产和其他长期资产的损失 |
| gdzcgbss | float | 固定资产报废损失 |
| gyjzbds | float | 公允价值变动损失 |
| cwfy | float | 财务费用 |
| tzss | float | 投资损失 |
| dysdszcjs | float | 递延所得税资产减少 |
| dysdsfzzj | float | 递延所得税负债增加 |
| chdjs | float | 存货的减少 |
| jxyysxmdjs | float | 经营性应收项目的减少 |
| qt | float | 其他 |
| jyhdcsdxjlxj | float | 经营活动产生现金流量净额 |
| zwzwzb | float | 债务转为资本 |
| ynndqdkzhgzq | float | 一年内到期的可转换公司债券 |
| rzrgdzc | float | 融资租入固定资产 |
| xjdqmye | float | 现金的期末余额 |
| xjdqcye | float | 现金的期初余额 |
| xjdhwdqmye | float | 现金等价物的期末余额 |
| xjdhwdqcye | float | 现金等价物的期初余额 |
| xjxjdhwdjzje | float | 现金及现金等价物的净增加额 |

**返回示例**：

```json
"[
```

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/bj/fin/cashflow/股票代码（如920547.BJ）?token=token证书&st=开始时间&et=结束时间"
response = requests.get(url)
data = response.json()
print(data)
```

### 财务主要指标【京】

**API 地址**：

```
https://api.zhituapi.com/bj/fin/ratios/股票代码（如920547.BJ）?token=token证书&st=开始时间&et=结束时间
```

**描述**：根据《京市股票列表》得到的股票代码获取财务主要指标，开始时间以及结束时间的格式均为 YYYYMMDD，例如：'20240101'。不设置开始时间和结束时间则为全部数据。

**更新频率**：每日0点

**请求频率限制**：包量版1分钟300次 |体验版、包月版1分钟1000次 | 包年版1分钟3千次 | 至尊版1分钟6千次

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| mgzbgjj | float | 每股资本公积金 |
| kfmgsy | float | 扣非每股收益 |
| jzcsyl | float | 净资产收益率 |
| xsmlv | float | 销售毛利率 |
| zyyrsrzz | float | 主营收入同比增长 |
| jlrzz | float | 净利润同比增长 |
| gsmgsyzzdjlrzz | float | 归属于母公司所有者的净利润同比增长 |
| kfjlrzz | float | 扣非净利润同比增长 |
| yyzsrgdhbzz | float | 营业总收入滚动环比增长 |
| sljlrjqhbzz | float | 归属净利润滚动环比增长 |
| kfjlrgdhbzz | float | 扣非净利润滚动环比增长 |
| jqjzcsyl | float | 加权净资产收益率 |
| tbjzcsyl | float | 摊薄净资产收益率 |
| tbzzcsyl | float | 摊薄总资产收益率 |
| mlv | float | 毛利率 |
| jlv | float | 净利率 |
| sjslv | float | 实际税率 |
| yskyysr | float | 预收款营业收入 |
| xsxjlyysr | float | 销售现金流营业收入 |
| zcfzl | float | 资产负债比率 |
| chzzl | float | 存货周转率 |
| jzrq | string | 截止日期 |
| plrq | string | 披露日期 |
| mgjyhdxjl | float | 每股经营活动现金流量 |
| mgjzc | float | 每股净资产 |
| jbmgsy | float | 基本每股收益 |
| xsmgsy | float | 稀释每股收益 |
| mgwfplr | float | 每股未分配利润 |

**返回示例**：

```json
"[
```

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/bj/fin/ratios/股票代码（如920547.BJ）?token=token证书&st=开始时间&et=结束时间"
response = requests.get(url)
data = response.json()
print(data)
```

### 公司股本表【京】

**API 地址**：

```
https://api.zhituapi.com/bj/fin/capital/股票代码（如920547.BJ）?token=token证书&st=开始时间&et=结束时间
```

**描述**：根据《京市股票列表》得到的股票代码获取公司股本表，开始时间以及结束时间的格式均为 YYYYMMDD，例如：'20240101'。不设置开始时间和结束时间则为全部数据。

**更新频率**：每日0点

**请求频率限制**：包量版1分钟300次 |体验版、包月版1分钟1000次 | 包年版1分钟3千次 | 至尊版1分钟6千次

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| zgb | float | 总股本 |
| ysltag | float | 已上市流通A股 |
| xsltgf | float | 限售流通股份 |
| bdrq | string | 变动日期 |
| ggr | string | 公告日 |

**返回示例**：

```json
"[
```

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/bj/fin/capital/股票代码（如920547.BJ）?token=token证书&st=开始时间&et=结束时间"
response = requests.get(url)
data = response.json()
print(data)
```

### 公司十大股东【京】

**API 地址**：

```
https://api.zhituapi.com/bj/fin/topholder/股票代码（如920547.BJ）?token=token证书&st=开始时间&et=结束时间
```

**描述**：根据《京市股票列表》得到的股票代码获取公司十大股东，开始时间以及结束时间的格式均为 YYYYMMDD，例如：'20240101'。不设置开始时间和结束时间则为全部数据。

**更新频率**：每日0点

**请求频率限制**：包量版1分钟300次 |体验版、包月版1分钟1000次 | 包年版1分钟3千次 | 至尊版1分钟6千次

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| ggrq | string | 公告日期 |
| jzrq | string | 截止日期 |
| gdmc | string | 股东名称 |
| gdlx | string | 股东类型 |
| cgsl | string | 持股数量 |
| bdyy | string | 变动原因 |
| cgbl | string | 持股比例 |
| gfxz | string | 股份性质 |
| cgpm | string | 持股排名 |

**返回示例**：

```json
"[
```

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/bj/fin/topholder/股票代码（如920547.BJ）?token=token证书&st=开始时间&et=结束时间"
response = requests.get(url)
data = response.json()
print(data)
```

### 公司十大流通股东【京】

**API 地址**：

```
https://api.zhituapi.com/bj/fin/flowholder/股票代码（如920547.BJ）?token=token证书&st=开始时间&et=结束时间
```

**描述**：根据《京市股票列表》得到的股票代码获取公司十大流通股东，开始时间以及结束时间的格式均为 YYYYMMDD，例如：'20240101'。不设置开始时间和结束时间则为全部数据。

**更新频率**：每日0点

**请求频率限制**：包量版1分钟300次 |体验版、包月版1分钟1000次 | 包年版1分钟3千次 | 至尊版1分钟6千次

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| ggrq | string | 公告日期 |
| jzrq | string | 截止日期 |
| gdmc | string | 股东名称 |
| gdlx | string | 股东类型 |
| cgsl | string | 持股数量 |
| bdyy | string | 变动原因 |
| cgbl | string | 持股比例 |
| gfxz | string | 股份性质 |
| cgpm | string | 持股排名 |

**返回示例**：

```json
"[
```

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/bj/fin/flowholder/股票代码（如920547.BJ）?token=token证书&st=开始时间&et=结束时间"
response = requests.get(url)
data = response.json()
print(data)
```

### 公司股东数【京】

**API 地址**：

```
https://api.zhituapi.com/bj/fin/hm/股票代码（如920547.BJ）?token=token证书&st=开始时间&et=结束时间
```

**描述**：根据《京市股票列表》得到的股票代码获取公司股东数，开始时间以及结束时间的格式均为 YYYYMMDD，例如：'20240101'。不设置开始时间和结束时间则为全部数据。

**更新频率**：每日0点

**请求频率限制**：包量版1分钟300次 |体验版、包月版1分钟1000次 | 包年版1分钟3千次 | 至尊版1分钟6千次

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| jzrq | string | 截止日期 |
| gdzs | string | 股东总数 |
| agdhs | string | A股东户数 |
| bgdhs | string | B股东户数 |
| hgdhs | string | H股东户数 |
| yltgdhs | string | 已流通股东户数 |
| wltgdhs | string | 未流通股东户数 |

**返回示例**：

```json
"[
```

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/bj/fin/hm/股票代码（如920547.BJ）?token=token证书&st=开始时间&et=结束时间"
response = requests.get(url)
data = response.json()
print(data)
```

## 技术指标

### 历史分时MACD【京】

**API 地址**：

```
https://api.zhituapi.com/bj/history/macd/股票代码(如920000.BJ)/分时级别(如d)/除权类型(如n)?token=token证书&st=开始时间&et=结束时间&lt=最新条数
```

**描述**：根据《京市股票列表》得到的股票代码和分时级别获取历史MACD数据，交易时间升序。目前分时级别支持5分钟、15分钟、30分钟、60分钟、日线、周线、月线、年线，对应的请求参数分别为5、15、30、60、d、w、m、y，日线以上除权方式有不复权、前复权、后复权、等比前复权、等比后复权，对应的参数分别为n、f、b、fr、br，分钟级仅限请求不复权数据，对应的参数为n。开始时间以及结束时间的格式均为 YYYYMMDD 或 YYYYMMDDhhmmss，例如：'20240101' 或'20241231235959'。不设置开始时间和结束时间则为全部历史数据。同时可以指定获取数据条数，例如指定lt=10，则获取最新的10条数据。 【重要】1分钟级别技术指标已改为API扩能包专属，请使用 /…/pro/history/{macd|ma|boll|kdj}/…/1/… ；普通本路径的 period=1 已停止开放。其它周期（5/15/30/60/d/w/m/y）不变。

**更新频率**：分钟级别数据盘中更新，分时越小越优先更新，如5分钟级别会每5分钟更新，15分钟级别会每15分钟更新，以此类推，日线及以上级别每日15:35更新

**请求频率限制**：包量版1分钟300次 | 包月版、体验版1分钟1千次| 包年版1分钟3千次 | 至尊版1分钟6千次

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| t | string | 交易时间，短分时级别格式为yyyy-MM-ddHH:mm:ss，日线级别为yyyy-MM-dd |
| diff | number | DIFF值 |
| dea | number | DEA值 |
| macd | number | MACD值 |
| ema12 | number | EMA（12）值 |
| ema26 | number | EMA（26）值 |

**返回示例**：

```json
[{"t":"2026-08-05","diff":0.544,"dea":0.262,"macd":0.565,"ema12":13.6648,"ema26":13.1209},{"t":"2026-08-06","diff":0.58,"dea":0.325,"macd":0.509,"ema12":13.8118,"ema26":13.232},{"t":"2026-08-07","diff":0.577,"dea":0.376,"macd":0.403,"ema12":13.89,"ema26":13.3126}]
```

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/bj/history/macd/股票代码(如920000.BJ)/分时级别(如d)/除权类型(如n)?token=token证书&st=开始时间&et=结束时间&lt=最新条数"
response = requests.get(url)
data = response.json()
print(data)
```

### 历史分时MA【京】

**API 地址**：

```
https://api.zhituapi.com/bj/history/ma/股票代码(如920000.BJ)/分时级别(如d)/除权类型(如n)?token=token证书&st=开始时间&et=结束时间&lt=最新条数
```

**描述**：根据《京市股票列表》得到的股票代码和分时级别获取历史MA数据，交易时间升序。目前分时级别支持5分钟、15分钟、30分钟、60分钟、日线、周线、月线、年线，对应的请求参数分别为5、15、30、60、d、w、m、y，日线以上除权方式有不复权、前复权、后复权、等比前复权、等比后复权，对应的参数分别为n、f、b、fr、br，分钟级仅限请求不复权数据，对应的参数为n。开始时间以及结束时间的格式均为 YYYYMMDD 或 YYYYMMDDhhmmss，例如：'20240101' 或'20241231235959'。不设置开始时间和结束时间则为全部历史数据。同时可以指定获取数据条数，例如指定lt=10，则获取最新的10条数据。 【重要】1分钟级别技术指标已改为API扩能包专属，请使用 /…/pro/history/{macd|ma|boll|kdj}/…/1/… ；普通本路径的 period=1 已停止开放。其它周期（5/15/30/60/d/w/m/y）不变。

**更新频率**：分钟级别数据盘中更新，分时越小越优先更新，如5分钟级别会每5分钟更新，15分钟级别会每15分钟更新，以此类推，日线及以上级别每日15:35更新

**请求频率限制**：包量版1分钟300次 | 包月版、体验版1分钟1千次| 包年版1分钟3千次 | 至尊版1分钟6千次

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| t | string | 交易时间，短分时级别格式为yyyy-MM-ddHH:mm:ss，日线级别为yyyy-MM-dd |
| ma3 | number | MA3，没有则为null |
| ma5 | number | MA5，没有则为null |
| ma10 | number | MA10，没有则为null |
| ma15 | number | MA15，没有则为null |
| ma20 | number | MA20，没有则为null |
| ma30 | number | MA30，没有则为null |
| ma60 | number | MA60，没有则为null |
| ma120 | number | MA120，没有则为null |
| ma200 | number | MA200，没有则为null |
| ma250 | number | MA250，没有则为null |

**返回示例**：

```json
[{"t":"2026-08-06","ma3":14.49,"ma5":14.452,"ma10":14.088,"ma15":13.37,"ma20":12.9235,"ma30":12.4697,"ma60":13.2398,"ma120":15.0528,"ma200":17.0104,"ma250":18.0051},{"t":"2026-08-07","ma3":14.4667,"ma5":14.396,"ma10":14.102,"ma15":13.5347,"ma20":13.057,"ma30":12.5603,"ma60":13.216,"ma120":15.0166,"ma200":16.9798,"ma250":17.9789}]
```

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/bj/history/ma/股票代码(如920000.BJ)/分时级别(如d)/除权类型(如n)?token=token证书&st=开始时间&et=结束时间&lt=最新条数"
response = requests.get(url)
data = response.json()
print(data)
```

### 历史分时BOLL【京】

**API 地址**：

```
https://api.zhituapi.com/bj/history/boll/股票代码(如920000.BJ)/分时级别(如d)/除权类型(如n)?token=token证书&st=开始时间&et=结束时间&lt=最新条数
```

**描述**：根据《京市股票列表》得到的股票代码和分时级别获取历史BOLL数据，交易时间升序。目前分时级别支持5分钟、15分钟、30分钟、60分钟、日线、周线、月线、年线，对应的请求参数分别为5、15、30、60、d、w、m、y，日线以上除权方式有不复权、前复权、后复权、等比前复权、等比后复权，对应的参数分别为n、f、b、fr、br，分钟级仅限请求不复权数据，对应的参数为n。开始时间以及结束时间的格式均为 YYYYMMDD 或 YYYYMMDDhhmmss，例如：'20240101' 或'20241231235959'。不设置开始时间和结束时间则为全部历史数据。同时可以指定获取数据条数，例如指定lt=10，则获取最新的10条数据。 【重要】1分钟级别技术指标已改为API扩能包专属，请使用 /…/pro/history/{macd|ma|boll|kdj}/…/1/… ；普通本路径的 period=1 已停止开放。其它周期（5/15/30/60/d/w/m/y）不变。

**更新频率**：分钟级别数据盘中更新，分时越小越优先更新，如5分钟级别会每5分钟更新，15分钟级别会每15分钟更新，以此类推，日线及以上级别每日15:35更新

**请求频率限制**：包量版1分钟300次 | 包月版、体验版1分钟1千次| 包年版1分钟3千次 | 至尊版1分钟6千次

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| t | string | 交易时间，短分时级别格式为yyyy-MM-ddHH:mm:ss，日线级别为yyyy-MM-dd |
| u | number | 上轨 |
| d | number | 下轨 |
| m | number | 中轨 |

**返回示例**：

```json
[{"t":"2026-08-06","u":15.58,"d":10.27,"m":12.92},{"t":"2026-08-07","u":15.71,"d":10.4,"m":13.06}]
```

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/bj/history/boll/股票代码(如920000.BJ)/分时级别(如d)/除权类型(如n)?token=token证书&st=开始时间&et=结束时间&lt=最新条数"
response = requests.get(url)
data = response.json()
print(data)
```

### 历史分时KDJ【京】

**API 地址**：

```
https://api.zhituapi.com/bj/history/kdj/股票代码(如920000.BJ)/分时级别(如d)/除权类型(如n)?token=token证书&st=开始时间&et=结束时间&lt=最新条数
```

**描述**：根据《京市股票列表》得到的股票代码和分时级别获取历史KDJ数据，交易时间升序。目前分时级别支持5分钟、15分钟、30分钟、60分钟、日线、周线、月线、年线，对应的请求参数分别为5、15、30、60、d、w、m、y，日线以上除权方式有不复权、前复权、后复权、等比前复权、等比后复权，对应的参数分别为n、f、b、fr、br，分钟级仅限请求不复权数据，对应的参数为n。开始时间以及结束时间的格式均为 YYYYMMDD 或 YYYYMMDDhhmmss，例如：'20240101' 或'20241231235959'。不设置开始时间和结束时间则为全部历史数据。同时可以指定获取数据条数，例如指定lt=10，则获取最新的10条数据。 【重要】1分钟级别技术指标已改为API扩能包专属，请使用 /…/pro/history/{macd|ma|boll|kdj}/…/1/… ；普通本路径的 period=1 已停止开放。其它周期（5/15/30/60/d/w/m/y）不变。

**更新频率**：分钟级别数据盘中更新，分时越小越优先更新，如5分钟级别会每5分钟更新，15分钟级别会每15分钟更新，以此类推，日线及以上级别每日15:35更新

**请求频率限制**：包量版1分钟300次 | 包月版、体验版1分钟1千次| 包年版1分钟3千次 | 至尊版1分钟6千次

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| t | string | 交易时间，短分时级别格式为yyyy-MM-ddHH:mm:ss，日线级别为yyyy-MM-dd |
| k | number | K值 |
| d | number | D值 |
| j | number | J值 |

**返回示例**：

```json
[{"t":"2026-08-06","k":66.63,"d":67.25,"j":65.39},{"t":"2026-08-07","k":63.81,"d":66.1,"j":59.22}]
```

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/bj/history/kdj/股票代码(如920000.BJ)/分时级别(如d)/除权类型(如n)?token=token证书&st=开始时间&et=结束时间&lt=最新条数"
response = requests.get(url)
data = response.json()
print(data)
```

