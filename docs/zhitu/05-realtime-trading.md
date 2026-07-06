# 05 实时交易

> 抓取时间：2026-06-10
> 源站点：<https://www.zhituapi.com/hsstockapi.html>

## 实时交易（公开数据源）

**API 地址**：

```
https://api.zhituapi.com/hs/real/ssjy/股票代码?token=token证书
```

**描述**：根据《股票列表》得到的股票代码获取实时交易数据（您可以理解为日线的最新数据）。

**更新频率**：交易时间段每1分钟

**请求频率限制**：包量版1分钟300次 |体验版、包月版1分钟1000次 | 包年版1分钟3千次 | 至尊版1分钟6千次

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| fm | number | 五分钟涨跌幅（%） |
| h | number | 最高价（元） |
| hs | number | 换手（%） |
| lb | number | 量比（%） |
| l | number | 最低价（元） |
| lt | number | 流通市值（元） |
| o | number | 开盘价（元） |
| pe | number | 市盈率（动态，总市值除以预估全年净利润，例如当前公布一季度净利润1000万，则预估全年净利润4000万） |
| pc | number | 涨跌幅（%） |
| p | number | 当前价格（元） |
| sz | number | 总市值（元） |
| cje | number | 成交额（元） |
| ud | number | 涨跌额（元） |
| v | number | 成交量(万手;broker 源 `/hs/real/time/` 是手;`* 1000000` 归一到股 per spec §3.4。2026-07-06 实测:茅台 v=4.1, broker 源 v=40970, 4.1 × 10000 = 41000 ≈ 40970。⚠️ 本项目 zhitu_fetcher `* 100 * 10000` 即此) |
| yc | number | 昨日收盘价（元） |
| zf | number | 振幅（%） |
| zs | number | 涨速（%） |
| sjl | number | 市净率 |
| zdf60 | number | 60日涨跌幅（%） |
| zdfnc | number | 年初至今涨跌幅（%） |
| t | string | 更新时间yyyy-MM-ddHH:mm:ss |

**返回示例**：

```json
{"o":11.69,"fm":0.17,"h":11.71,"hs":0.5,"lb":0.7,"l":11.55,"lt":225881388026.0,"pe":4.26,"pc":-0.17,"p":11.64,"sz":225884887825.0,"cje":1131033823.93,"ud":-0.02,"v":973969,"yc":11.66,"zf":1.37,"zs":0.17,"sjl":0.54,"zdf60":0.0,"zdfnc":-0.51,"t":"2025-02-21 15:29:05"}
```

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/hs/real/ssjy/股票代码?token=token证书"
response = requests.get(url)
data = response.json()
print(data)
```

## 当天逐笔交易

**API 地址**：

```
https://api.zhituapi.com/hs/real/zbjy/股票代码?token=token证书
```

**描述**：根据《股票列表》得到的股票代码获取当天逐笔交易数据，按时间倒序。

**更新频率**：21:00

**请求频率限制**：包量版1分钟300次 |体验版、包月版1分钟1000次 | 包年版1分钟3千次 | 至尊版1分钟6千次

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| d | string | 数据归属日期（yyyy-MM-dd） |
| t | string | 时间（HH:mm:dd） |
| v | number | 成交量（股） |
| p | number | 成交价 |
| ts | number | 交易方向（0：中性盘，1：买入，2：卖出） |

**返回示例**：

```json
[{"d":"2025-02-21","t":"15:00:00","v":1341800,"p":11.64,"ts":1},{"d":"2025-02-21","t":"14:57:00","v":3900,"p":11.62,"ts":2},{"d":"2025-02-21","t":"14:56:57","v":11300,"p":11.62,"ts":2},{"d":"2025-02-21","t":"14:56:54","v":31600,"p":11.62,"ts":1},{"d":"2025-02-21","t":"14:56:51","v":70900,"p":11.61,"ts":2},{"d":"2025-02-21","t":"14:56:48","v":8700,"p":11.61,"ts":2}]
```

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/hs/real/zbjy/股票代码?token=token证书"
response = requests.get(url)
data = response.json()
print(data)
```

## 实时交易（全部 | 公开数据）

**API 地址**：

```
https://api.zhituapi.com/hs/public/realall?token=token证书
```

**描述**：一次性获取《股票列表》中所有股票的实时交易数据（您可以理解为日线的最新数据），该接口仅限至尊版和包年版token使用且限制每分钟请求1次。

**更新频率**：交易时间段每1分钟

**请求频率限制**：包量版1分钟300次 |体验版、包月版1分钟1000次 | 包年版1分钟3千次 | 至尊版1分钟6千次

**字段说明**：同"实时交易（公开数据源）"，额外增加字段 `dm`（股票代码）。

**返回示例**：

```json
[
    {
        "o": 11.31,
        "fm": -0.09,
        "h": 11.39,
        "hs": 0.33,
        "lb": 0.82,
        "l": 11.3,
        "lt": 220059184779.0,
        "pe": 4.94,
        "pc": -0.26,
        "p": 11.34,
        "sz": 220063112365.0,
        "cje": 730375807.93,
        "ud": -0.03,
        "v": 643914,
        "yc": 11.37,
        "zf": 0.79,
        "zs": 0.0,
        "sjl": 0.52,
        "zdf60": -3.08,
        "zdfnc": -3.08,
        "t": "2025-04-03 15:29:10",
        "dm": "000001"
    }
]
```

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/hs/public/realall?token=token证书"
response = requests.get(url)
data = response.json()
print(data)
```

## 实时交易（多选 | 公开数据）

**API 地址**：

```
https://api.zhituapi.com/hs/public/ssjymore?stock_codes=股票1代码,股票2代码,……,股票20代码&token=token证书
```

**描述**：根据《股票列表》得到的股票代码指定不超过20支股票代码获取实时交易数据（您可以理解为日线的最新数据），该接口仅限至尊版和包年版token使用。

**更新频率**：交易时间段每1分钟

**请求频率限制**：包量版1分钟300次 |体验版、包月版1分钟1000次 | 包年版1分钟3千次 | 至尊版1分钟6千次

**字段说明**：同"实时交易（公开数据源）"，额外增加字段 `dm`（股票代码）。

**返回示例**：同"实时交易（全部 | 公开数据）"。

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/hs/public/ssjymore?stock_codes=股票1代码,股票2代码,……,股票20代码&token=token证书"
response = requests.get(url)
data = response.json()
print(data)
```

## 实时交易（券商数据源）

**API 地址**：

```
https://api.zhituapi.com/hs/real/time/股票代码?token=token证书
```

**描述**：根据《股票列表》得到的股票代码获取实时交易数据（您可以理解为日线的最新数据）。

**更新频率**：实时

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
| t | string | 更新时间 |
| ud | float | 涨跌额 |
| pc | float | 涨跌幅 |
| zf | float | 振幅 |
| pe | number | 市盈率 |
| tr | number | 换手率 |
| pb_ratio | number | 市净率 |
| tv | number | 成交量 |

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/hs/real/time/股票代码?token=token证书"
response = requests.get(url)
data = response.json()
print(data)
```

## 买卖五档盘口(新增)

**API 地址**：

```
https://api.zhituapi.com/hs/real/five/股票代码?token=token证书
```

**描述**：根据《股票列表》得到的股票代码获取实时买卖五档盘口数据。

**更新频率**：实时

**请求频率限制**：包量版1分钟300次 |体验版、包月版1分钟1000次 | 包年版1分钟3千次 | 至尊版1分钟6千次

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| ps | number | 委卖价 |
| pb | number | 委买价 |
| vs | number | 委卖量 |
| vb | number | 委买量 |
| t | string | 更新时间 |

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/hs/real/five/股票代码?token=token证书"
response = requests.get(url)
data = response.json()
print(data)
```

## 实时交易（全部 | 券商数据）

**API 地址**：

```
https://api.zhituapi.com/hs/custom/realall?token=token证书
```

**描述**：一次性获取《股票列表》中所有股票的实时交易数据（您可以理解为日线的最新数据），该接口仅限至尊版和包年版证书使用且限制每分钟请求1次。

**更新频率**：交易时间段每1分钟

**请求频率限制**：包量版1分钟300次 |体验版、包月版1分钟1000次 | 包年版1分钟3千次 | 至尊版1分钟6千次

**字段说明**：同"实时交易（券商数据源）"，额外增加字段 `dm`（股票代码）。

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/hs/custom/realall?token=token证书"
response = requests.get(url)
data = response.json()
print(data)
```

## 实时交易（多选 | 券商数据）

**API 地址**：

```
https://api.zhituapi.com/hs/custom/ssjymore?token=token证书&tock_codes=股票代码1,股票代码2……股票代码20
```

**描述**：一次性获取《股票列表》中不超过20支股票的实时交易数据（您可以理解为日线的最新数据），该接口仅限至尊版和包年版token使用。

**更新频率**：实时

**请求频率限制**：包量版1分钟300次 |体验版、包月版1分钟1000次 | 包年版1分钟3千次 | 至尊版1分钟6千次

**字段说明**：同"实时交易（券商数据源）"，额外增加字段 `dm`（股票代码）。

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/hs/custom/ssjymore?token=token证书&tock_codes=股票代码1,股票代码2……股票代码20"
response = requests.get(url)
data = response.json()
print(data)
```

## 资金流向数据

**API 地址**：

```
https://api.zhituapi.com/hs/history/transaction/股票代码?token=token证书&st=开始时间&et=结束时间&lt=最新条数
```

**描述**：根据《股票列表》得到的股票代码获取资金流向数据。开始时间以及结束时间的格式均为 YYYYMMDD，例如：'20240101'，不设置开始时间和结束时间则为全部历史数据。同时可以指定获取数据条数，例如指定lt=10，则获取最新的10条数据。下列字段中，特大单为成交金额大于或等于100万元或成交量大于或等于5000手，大单为成交金额大于或等于20万元或成交量大于或等于1000手，中单为成交金额大于或等于4万元或成交量大于或等于200手，其他为小单。

**更新频率**：每日21:30更新

**请求频率限制**：包量版1分钟300次 |体验版、包月版1分钟1000次 | 包年版1分钟3千次 | 至尊版1分钟6千次

**字段说明**（节选主要字段）：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| t | int | 交易时间 |
| zmbzds | int | 主买单总单数 |
| zmszds | int | 主卖单总单数 |
| dddx | float | 大单动向 |
| zddy | float | 涨跌动因 |
| ddcf | float | 大单差分 |
| zmbzdszl | int | 主买单总单数增量 |
| zmszdszl | int | 主卖单总单数增量 |
| cjbszl | int | 成交笔数增量 |
| zmbtdcje | float | 主买特大单成交额 |
| zmbddcje | float | 主买大单成交额 |
| zmbzdcje | float | 主买中单成交额 |
| zmbxdcje | float | 主买小单成交额 |
| zmstdcje | float | 主卖特大单成交额 |
| zmsddcje | float | 主卖大单成交额 |
| zmszdcje | float | 主卖中单成交额 |
| zmsxdcje | float | 主卖小单成交额 |
| ... | ... | 其它增量/成交量/笔数字段（详见源站点） |

**返回示例**：

```json
{
    "t": "2025-08-15 00:00:00",
    "zmbzds": 2567,
    "zmszds": 2113,
    "dddx": -5.3,
    "zddy": -9.69,
    "ddcf": 2.39,
    "zmbtdcje": 643556632.0,
    "zmbddcje": 358436868.0,
    "zmbzdcje": 112809518.0,
    "zmbxdcje": 8789754.0,
    "zmstdcje": 809155040.0,
    "zmsddcje": 316750969.0,
    "zmbtdcjl": 534893,
    "zmbddcjl": 297992,
    "zmbzdcjl": 93818,
    "zmbxdcjl": 7307
}
```

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/hs/history/transaction/股票代码?token=token证书&st=开始时间&et=结束时间&lt=最新条数"
response = requests.get(url)
data = response.json()
print(data)
```
