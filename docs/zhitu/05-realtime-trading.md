# 05 实时交易

> 抓取时间：2026-10-08
> 源站点：<https://www.zhituapi.com/hsstockapi.html>
> 分类对应上游「实时交易」9 节 + 上游「特色行情」2 节（资金流向，历史上并入本文件收录）。

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
| v | number | 成交量（手）—— **本项目备注**（2026-07-06 实测，与上游本行文字不符）：public 源实际返回**万手**（茅台 v=4.1），broker 源 `/hs/real/time/` 返回**手**（v=40970，4.1×10000≈40970）；`zhitu_fetcher` 按 `* 100 * 10000` 归一到股 per spec §3.4 |
| yc | number | 昨日收盘价（元） |
| zf | number | 振幅（%） |
| zs | number | 涨速（%） |
| sjl | number | 市净率 |
| zdf60 | number | 60日涨跌幅（%） |
| zdfnc | number | 年初至今涨跌幅（%） |
| t | string | 更新时间yyyy-MM-ddHH:mm:ss |

**返回示例**：

```json
{"o":11.69,"fm":0.17,"h":11.71,"hs":0.5,"lb":0.7,"l":11.55,"lt":225881388026.0,"pe":4.26,"pc":-0.17,"p":11.64,"sz":225884887825.0,"cje":1131033823.93,"ud":-0.02,"v":973969,"yc":11.66,"zf":1.37,"zs":0.17,"sjl":0.54,"zdf60":0.0,"zdfnc":-0.51,"t":"2025-02-21 15:29:05"}]
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

**描述**：根据《股票列表》得到的股票代码获取当天逐笔交易数据，按时间倒序。每个交易日开盘后返回的均为当日数据；交易时段内约每 60 分钟更新一次，收盘后由盘后任务定稿。历史交易日请使用「历史逐笔交易」接口。

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
[{"d":"2025-02-21","t":"15:00:00","v":1341800,"p":11.64,"ts":1},{"d":"2025-02-21","t":"14:57:00","v":3900,"p":11.62,"ts":2},{"d":"2025-02-21","t":"14:56:57","v":11300,"p":11.62,"ts":2},{"d":"2025-02-21","t":"14:56:54","v":31600,"p":11.62,"ts":1},{"d":"2025-02-21","t":"14:56:51","v":70900,"p":11.61,"ts":2},{"d":"2025-02-21","t":"14:56:48","v":8700,"p":11.61,"ts":2},{"d":"2025-02-21","t":"14:56:45","v":6500,"p":11.62,"ts":1},{"d":"2025-02-21","t":"14:56:42","v":2900,"p":11.62,"ts":2},{"d":"2025-02-21","t":"14:56:39","v":11500,"p":11.63,"ts":1},{"d":"2025-02-21","t":"14:56:36","v":7200,"p":11.61,"ts":2},{"d":"2025-02-21","t":"14:56:33","v":18000,"p":11.63,"ts":1},{"d":"2025-02-21","t":"14:56:30","v":20800,"p":11.61,"ts":2},{"d":"2025-02-21","t":"14:56:27","v":9000,"p":11.62,"ts":1},{"d":"2025-02-21","t":"14:56:24","v":5800,"p":11.62,"ts":1},{"d":"2025-02-21","t":"14:56:21","v":6500,"p":11.62,"ts":1},{"d":"2025-02-21","t":"14:56:18","v":7400,"p":11.62,"ts":1},{"d":"2025-02-21","t":"14:56:15","v":11300,"p":11.62,"ts":2},{"d":"2025-02-21","t":"14:56:12","v":3400,"p":11.61,"ts":2},{"d":"2025-02-21","t":"14:56:09","v":10400,"p":11.62,"ts":2},{"d":"2025-02-21","t":"14:56:06","v":11700,"p":11.62,"ts":2},{"d":"2025-02-21","t":"14:56:03","v":26400,"p":11.63,"ts":1},{"d":"2025-02-21","t":"14:56:00","v":130300,"p":11.62,"ts":2},{"d":"2025-02-21","t":"14:55:57","v":39400,"p":11.63,"ts":1},{"d":"2025-02-21","t":"14:55:54","v":8900,"p":11.62,"ts":2},{"d":"2025-02-21","t":"14:55:51","v":20500,"p":11.62,"ts":1},{"d":"2025-02-21","t":"14:55:48","v":4500,"p":11.62,"ts":1}]
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

**描述**：一次性获取《股票列表》中所有股票的实时交易数据（您可以理解为日线的最新数据）。包年版 / 至尊版，或已开通且未过期的 API扩能包可用（全市场 bulk 约 3 次/分钟）。

**更新频率**：交易时间段每1分钟

**请求频率限制**：包年版 / 至尊版，或已开通且未过期的 API扩能包；全市场 bulk 约 3 次/分钟（独立限流）

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
| v | number | 成交量（手） |
| yc | number | 昨日收盘价（元） |
| zf | number | 振幅（%） |
| zs | number | 涨速（%） |
| sjl | number | 市净率 |
| zdf60 | number | 60日涨跌幅（%） |
| zdfnc | number | 年初至今涨跌幅（%） |
| t | string | 更新时间yyyy-MM-ddHH:mm:ss |
| dm | string | 股票代码 |

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
    },
    {
        "o": 6.12,
        "fm": -0.16,
        "h": 6.22,
        "hs": 0.9,
        "lb": 0.89,
        "l": 6.1,
        "lt": 2147977873.0,
        "pe": 507.22,
        "pc": 0.98,
        "p": 6.2,
        "sz": 2147977873.0,
        "cje": 19206391.82,
        "ud": 0.06,
        "v": 31090,
        "yc": 6.14,
        "zf": 1.95,
        "zs": -0.16,
        "sjl": 16.66,
        "zdf60": -11.81,
        "zdfnc": -11.81,
        "t": "2025-04-03 15:29:10",
        "dm": "000007"
    },
    {
        "o": 8.14,
        "fm": -0.12,
        "h": 8.24,
        "hs": 0.32,
        "lb": 0.68,
        "l": 8.12,
        "lt": 20870700050.0,
        "pe": 41.06,
        "pc": -0.24,
        "p": 8.18,
        "sz": 21097970234.0,
        "cje": 66906490.52,
        "ud": -0.02,
        "v": 81774,
        "yc": 8.2,
        "zf": 1.46,
        "zs": -0.12,
        "sjl": 2.08,
        "zdf60": -10.6,
        "zdfnc": -10.6,
        "t": "2025-04-03 15:29:10",
        "dm": "000009"
    },
    {
        "o": 2.81,
        "fm": 0.36,
        "h": 2.85,
        "hs": 2.97,
        "lb": 0.77,
        "l": 2.77,
        "lt": 1483182838.0,
        "pe": -40.91,
        "pc": 0.36,
        "p": 2.82,
        "sz": 3242019463.0,
        "cje": 43862642.0,
        "ud": 0.01,
        "v": 156265,
        "yc": 2.81,
        "zf": 2.85,
        "zs": -0.35,
        "sjl": 14.82,
        "zdf60": 0.36,
        "zdfnc": 0.36,
        "t": "2025-04-03 15:29:10",
        "dm": "000010"
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
| v | number | 成交量（手） |
| yc | number | 昨日收盘价（元） |
| zf | number | 振幅（%） |
| zs | number | 涨速（%） |
| sjl | number | 市净率 |
| zdf60 | number | 60日涨跌幅（%） |
| zdfnc | number | 年初至今涨跌幅（%） |
| t | string | 更新时间yyyy-MM-ddHH:mm:ss |
| dm | string | 股票代码 |

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
    },
    {
        "o": 6.12,
        "fm": -0.16,
        "h": 6.22,
        "hs": 0.9,
        "lb": 0.89,
        "l": 6.1,
        "lt": 2147977873.0,
        "pe": 507.22,
        "pc": 0.98,
        "p": 6.2,
        "sz": 2147977873.0,
        "cje": 19206391.82,
        "ud": 0.06,
        "v": 31090,
        "yc": 6.14,
        "zf": 1.95,
        "zs": -0.16,
        "sjl": 16.66,
        "zdf60": -11.81,
        "zdfnc": -11.81,
        "t": "2025-04-03 15:29:10",
        "dm": "000007"
    },
    {
        "o": 8.14,
        "fm": -0.12,
        "h": 8.24,
        "hs": 0.32,
        "lb": 0.68,
        "l": 8.12,
        "lt": 20870700050.0,
        "pe": 41.06,
        "pc": -0.24,
        "p": 8.18,
        "sz": 21097970234.0,
        "cje": 66906490.52,
        "ud": -0.02,
        "v": 81774,
        "yc": 8.2,
        "zf": 1.46,
        "zs": -0.12,
        "sjl": 2.08,
        "zdf60": -10.6,
        "zdfnc": -10.6,
        "t": "2025-04-03 15:29:10",
        "dm": "000009"
    },
    {
        "o": 2.81,
        "fm": 0.36,
        "h": 2.85,
        "hs": 2.97,
        "lb": 0.77,
        "l": 2.77,
        "lt": 1483182838.0,
        "pe": -40.91,
        "pc": 0.36,
        "p": 2.82,
        "sz": 3242019463.0,
        "cje": 43862642.0,
        "ud": 0.01,
        "v": 156265,
        "yc": 2.81,
        "zf": 2.85,
        "zs": -0.35,
        "sjl": 14.82,
        "zdf60": 0.36,
        "zdfnc": 0.36,
        "t": "2025-04-03 15:29:10",
        "dm": "000010"
    }
]
```

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
| t | string | 更新时间 |
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

**描述**：一次性获取《股票列表》中所有股票的实时交易数据（您可以理解为日线的最新数据）。包年版 / 至尊版，或已开通且未过期的 API扩能包可用（全市场 bulk 约 3 次/分钟）。

**更新频率**：交易时间段每1分钟

**请求频率限制**：包年版 / 至尊版，或已开通且未过期的 API扩能包；全市场 bulk 约 3 次/分钟（独立限流）

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| dm | string | 股票代码 |
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
| t | string | 更新时间 |
| pe | number | 市盈率 |
| tr | number | 换手率 |
| pb_ratio | number | 市净率 |
| tv | number | 成交量 |
| dm | string | 股票代码 |

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/hs/custom/ssjymore?token=token证书&tock_codes=股票代码1,股票代码2……股票代码20"
response = requests.get(url)
data = response.json()
print(data)
```

## 历史逐笔交易

**API 地址**：

```
https://api.zhituapi.com/hs/real/zbjy/交易日期(如20260813)/股票代码?token=token证书
```

**描述**：按交易日期与股票代码获取历史逐笔交易数据，字段与「当天逐笔交易」一致，按时间倒序。重要：本接口数据自 2026-08-13（含）起开始累积归档；2026-08-13 之前的交易日无历史逐笔数据。交易日期格式为 yyyyMMdd（如 20260813）。

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
[{"d": "2026-08-13", "t": "15:00:00", "v": 1341800, "p": 11.64, "ts": 1}, {"d": "2026-08-13", "t": "14:57:00", "v": 3900, "p": 11.62, "ts": 2}]
```

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/hs/real/zbjy/交易日期(如20260813)/股票代码?token=token证书"
response = requests.get(url)
data = response.json()
print(data)
```

## 资金流向数据

**API 地址**：

```
https://api.zhituapi.com/hs/history/transaction/股票代码（如000001.SZ）?token=token证书
```

**描述**：【多日区间请用本接口】路径中不要带交易日期，仅股票代码与证书。无 st/et：仅返回最近 1 个交易日日频记录（当日数据逐日覆盖）；非交易日为最后 1 个交易日的数据。同时传 st 与 et（yyyyMMdd 或 yyyy-MM-dd）：按日合并返回区间内多日记录，单次最多 365 个自然日；缺日自动跳过；仅一侧有参返回 422。示例：…/history/transaction/000001/{licence}?st=20260801&et=20260826。注意：若把日期写进路径（…/transaction/20260826/000001/…）再加 st/et，那是「历史资金流向数据」单日接口，不会做区间合并。

**更新频率**：交易时段约每 15 分钟更新 1 次（当日数据逐日覆盖）；区间查询为已归档多日合并

**请求频率限制**：包量版1分钟300次 |体验版、包月版1分钟1000次 | 包年版1分钟3千次 | 至尊版1分钟6千次

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| t | string | 交易日期（yyyy-MM-dd HH:mm:ss） |
| dddx | number | 大单动向 |
| zddy | number | 涨跌动因 |
| ddcf | number | 大单差分 |
| zmbzds | number | 主买单总单数 |
| zmszds | number | 主卖单总单数 |
| zmbzdszl | number | 主买单总单数增量 |
| zmszdszl | number | 主卖单总单数增量 |
| cjbszl | number | 成交笔数增量 |
| zmbtdcje | number | 主买特大单成交额 |
| zmbddcje | number | 主买大单成交额 |
| zmbzdcje | number | 主买中单成交额 |
| zmbxdcje | number | 主买小单成交额 |
| zmbtdcjl | number | 主买特大单成交量 |
| zmbddcjl | number | 主买大单成交量 |
| zmbzdcjl | number | 主买中单成交量 |
| zmbxdcjl | number | 主买小单成交量 |
| zmbtdcjzl | number | 主买特大单成交额增量 |
| zmbddcjzl | number | 主买大单成交额增量 |
| zmbzdcjzl | number | 主买中单成交额增量 |
| zmbxdcjzl | number | 主买小单成交额增量 |
| zmbtdcjzlv | number | 主买特大单成交量增量 |
| zmbddcjzlv | number | 主买大单成交量增量 |
| zmbzdcjzlv | number | 主买中单成交量增量 |
| zmbxdcjzlv | number | 主买小单成交量增量 |
| zmstdcje | number | 主卖特大单成交额 |
| zmsddcje | number | 主卖大单成交额 |
| zmszdcje | number | 主卖中单成交额 |
| zmsxdcje | number | 主卖小单成交额 |
| zmstdcjl | number | 主卖特大单成交量 |
| zmsddcjl | number | 主卖大单成交量 |
| zmszdcjl | number | 主卖中单成交量 |
| zmsxdcjl | number | 主卖小单成交量 |
| zmstdcjzl | number | 主卖特大单成交额增量 |
| zmsddcjzl | number | 主卖大单成交额增量 |
| zmszdcjzl | number | 主卖中单成交额增量 |
| zmsxdcjzl | number | 主卖小单成交额增量 |
| zmstdcjzlv | number | 主卖特大单成交量增量 |
| zmsddcjzlv | number | 主卖大单成交量增量 |
| zmszdcjzlv | number | 主卖中单成交量增量 |
| zmsxdcjzlv | number | 主卖小单成交量增量 |
| bdmbtdcje | number | 被动买特大单成交额 |
| bdmbddcje | number | 被动买大单成交额 |
| bdmbzdcje | number | 被动买中单成交额 |
| bdmbxdcje | number | 被动买小单成交额 |
| bdmbtdcjl | number | 被动买特大单成交量 |
| bdmbddcjl | number | 被动买大单成交量 |
| bdmbzdcjl | number | 被动买中单成交量 |
| bdmbxdcjl | number | 被动买小单成交量 |
| bdmbtdcjzl | number | 被动买特大单成交额增量 |
| bdmbddcjzl | number | 被动买大单成交额增量 |
| bdmbzdcjzl | number | 被动买中单成交额增量 |
| bdmbxdcjzl | number | 被动买小单成交额增量 |
| bdmbtdcjzlv | number | 被动买特大单成交量增量 |
| bdmbddcjzlv | number | 被动买大单成交量增量 |
| bdmbzdcjzlv | number | 被动买中单成交量增量 |
| bdmbxdcjzlv | number | 被动买小单成交量增量 |
| bdmstdcje | number | 被动卖特大单成交额 |
| bdmsddcje | number | 被动卖大单成交额 |
| bdmszdcje | number | 被动卖中单成交额 |
| bdmsxdcje | number | 被动卖小单成交额 |
| bdmstdcjl | number | 被动卖特大单成交量 |
| bdmsddcjl | number | 被动卖大单成交量 |
| bdmszdcjl | number | 被动卖中单成交量 |
| bdmsxdcjl | number | 被动卖小单成交量 |
| bdmstdcjzl | number | 被动卖特大单成交额增量 |
| bdmsddcjzl | number | 被动卖大单成交额增量 |
| bdmszdcjzl | number | 被动卖中单成交额增量 |
| bdmsxdcjzl | number | 被动卖小单成交额增量 |
| bdmstdcjzlv | number | 被动卖特大单成交量增量 |
| bdmsddcjzlv | number | 被动卖大单成交量增量 |
| bdmszdcjzlv | number | 被动卖中单成交量增量 |
| bdmsxdcjzlv | number | 被动卖小单成交量增量 |

**返回示例**：

```json
[{"t":"2026-08-24 00:00:00","dddx":5.93,"zddy":4.94,"ddcf":-1.54,"zmbzds":2181,"zmszds":2408,"zmbzdszl":2181,"zmszdszl":2408,"cjbszl":91531,"zmbtdcje":419291294,"zmbddcje":202390171,"zmbzdcje":94361900,"zmbxdcje":11548543,"zmbtdcjl":363499,"zmbddcjl":175471,"zmbzdcjl":81703,"zmbxdcjl":9988,"zmbtdcjzl":419291294,"zmbddcjzl":202390171,"zmbzdcjzl":94361900,"zmbxdcjzl":11548543,"zmbtdcjzlv":363499,"zmbddcjzlv":175471,"zmbzdcjzlv":81703,"zmbxdcjzlv":9988,"zmstdcje":254935867,"zmsddcje":233680531,"zmszdcje":110770356,"zmsxdcje":12407239,"zmstdcjl":221166,"zmsddcjl":202546,"zmszdcjl":95880,"zmsxdcjl":10734,"zmstdcjzl":254935867,"zmsddcjzl":233680531,"zmszdcjzl":110770356,"zmsxdcjzl":12407239,"zmstdcjzlv":221166,"zmsddcjzlv":202546,"zmszdcjzlv":95880,"zmsxdcjzlv":10734,"bdmbtdcje":254935867,"bdmbddcje":233680531,"bdmbzdcje":110770356,"bdmbxdcje":12407239,"bdmbtdcjl":221166,"bdmbddcjl":202546,"bdmbzdcjl":95880,"bdmbxdcjl":10734,"bdmbtdcjzl":254935867,"bdmbddcjzl":233680531,"bdmbzdcjzl":110770356,"bdmbxdcjzl":12407239,"bdmbtdcjzlv":221166,"bdmbddcjzlv":202546,"bdmbzdcjzlv":95880,"bdmbxdcjzlv":10734,"bdmstdcje":419291294,"bdmsddcje":202390171,"bdmszdcje":94361900,"bdmsxdcje":11548543,"bdmstdcjl":363499,"bdmsddcjl":175471,"bdmszdcjl":81703,"bdmsxdcjl":9988,"bdmstdcjzl":419291294,"bdmsddcjzl":202390171,"bdmszdcjzl":94361900,"bdmsxdcjzl":11548543,"bdmstdcjzlv":363499,"bdmsddcjzlv":175471,"bdmszdcjzlv":81703,"bdmsxdcjzlv":9988}]
```

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/hs/history/transaction/股票代码（如000001.SZ）?token=token证书"
response = requests.get(url)
data = response.json()
print(data)
```

> **本项目备注**（非上游原文）：本项目 `ZhituFetcher.get_fund_flow_minute` / `get_fund_flow_120d` 即封装本接口（`/hs/history/transaction/{code}`）。上游 2026-10 文档确认语义：无 `st/et` 仅返回最近 1 个交易日；区间查询须同时传 `st`+`et`（≤365 自然日，仅传一侧 422）；按日期取单日数据请改用下方「历史资金流向数据」。

## 历史资金流向数据

**API 地址**：

```
https://api.zhituapi.com/hs/history/transaction/交易日期（如20260821）/股票代码（如000001.SZ）?token=token证书
```

**描述**：【仅单日】路径必须带 yyyyMMdd（如 …/transaction/20260826/000001/{licence}），只返回该交易日的 JSON 数组；无该日返回数据不存在。本接口不支持 st、et：路径后即使写 ?st=&et= 也不会拼多日，接口会提示改用「资金流向数据」。多日区间正确用法：「资金流向数据」路径无日期 + ?st=起始&et=结束（最多 365 自然日）。数据自全量回填完成后按日累积。

**更新频率**：盘后按日增量更新（仅单日）

**请求频率限制**：包量版1分钟300次 |体验版、包月版1分钟1000次 | 包年版1分钟3千次 | 至尊版1分钟6千次

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| t | string | 交易日期（yyyy-MM-dd HH:mm:ss） |
| dddx | number | 大单动向 |
| zddy | number | 涨跌动因 |
| ddcf | number | 大单差分 |
| zmbzds | number | 主买单总单数 |
| zmszds | number | 主卖单总单数 |
| zmbzdszl | number | 主买单总单数增量 |
| zmszdszl | number | 主卖单总单数增量 |
| cjbszl | number | 成交笔数增量 |
| zmbtdcje | number | 主买特大单成交额 |
| zmbddcje | number | 主买大单成交额 |
| zmbzdcje | number | 主买中单成交额 |
| zmbxdcje | number | 主买小单成交额 |
| zmbtdcjl | number | 主买特大单成交量 |
| zmbddcjl | number | 主买大单成交量 |
| zmbzdcjl | number | 主买中单成交量 |
| zmbxdcjl | number | 主买小单成交量 |
| zmbtdcjzl | number | 主买特大单成交额增量 |
| zmbddcjzl | number | 主买大单成交额增量 |
| zmbzdcjzl | number | 主买中单成交额增量 |
| zmbxdcjzl | number | 主买小单成交额增量 |
| zmbtdcjzlv | number | 主买特大单成交量增量 |
| zmbddcjzlv | number | 主买大单成交量增量 |
| zmbzdcjzlv | number | 主买中单成交量增量 |
| zmbxdcjzlv | number | 主买小单成交量增量 |
| zmstdcje | number | 主卖特大单成交额 |
| zmsddcje | number | 主卖大单成交额 |
| zmszdcje | number | 主卖中单成交额 |
| zmsxdcje | number | 主卖小单成交额 |
| zmstdcjl | number | 主卖特大单成交量 |
| zmsddcjl | number | 主卖大单成交量 |
| zmszdcjl | number | 主卖中单成交量 |
| zmsxdcjl | number | 主卖小单成交量 |
| zmstdcjzl | number | 主卖特大单成交额增量 |
| zmsddcjzl | number | 主卖大单成交额增量 |
| zmszdcjzl | number | 主卖中单成交额增量 |
| zmsxdcjzl | number | 主卖小单成交额增量 |
| zmstdcjzlv | number | 主卖特大单成交量增量 |
| zmsddcjzlv | number | 主卖大单成交量增量 |
| zmszdcjzlv | number | 主卖中单成交量增量 |
| zmsxdcjzlv | number | 主卖小单成交量增量 |
| bdmbtdcje | number | 被动买特大单成交额 |
| bdmbddcje | number | 被动买大单成交额 |
| bdmbzdcje | number | 被动买中单成交额 |
| bdmbxdcje | number | 被动买小单成交额 |
| bdmbtdcjl | number | 被动买特大单成交量 |
| bdmbddcjl | number | 被动买大单成交量 |
| bdmbzdcjl | number | 被动买中单成交量 |
| bdmbxdcjl | number | 被动买小单成交量 |
| bdmbtdcjzl | number | 被动买特大单成交额增量 |
| bdmbddcjzl | number | 被动买大单成交额增量 |
| bdmbzdcjzl | number | 被动买中单成交额增量 |
| bdmbxdcjzl | number | 被动买小单成交额增量 |
| bdmbtdcjzlv | number | 被动买特大单成交量增量 |
| bdmbddcjzlv | number | 被动买大单成交量增量 |
| bdmbzdcjzlv | number | 被动买中单成交量增量 |
| bdmbxdcjzlv | number | 被动买小单成交量增量 |
| bdmstdcje | number | 被动卖特大单成交额 |
| bdmsddcje | number | 被动卖大单成交额 |
| bdmszdcje | number | 被动卖中单成交额 |
| bdmsxdcje | number | 被动卖小单成交额 |
| bdmstdcjl | number | 被动卖特大单成交量 |
| bdmsddcjl | number | 被动卖大单成交量 |
| bdmszdcjl | number | 被动卖中单成交量 |
| bdmsxdcjl | number | 被动卖小单成交量 |
| bdmstdcjzl | number | 被动卖特大单成交额增量 |
| bdmsddcjzl | number | 被动卖大单成交额增量 |
| bdmszdcjzl | number | 被动卖中单成交额增量 |
| bdmsxdcjzl | number | 被动卖小单成交额增量 |
| bdmstdcjzlv | number | 被动卖特大单成交量增量 |
| bdmsddcjzlv | number | 被动卖大单成交量增量 |
| bdmszdcjzlv | number | 被动卖中单成交量增量 |
| bdmsxdcjzlv | number | 被动卖小单成交量增量 |

**返回示例**：

```json
[{"t":"2026-08-24 00:00:00","dddx":5.93,"zddy":4.94,"ddcf":-1.54,"zmbzds":2181,"zmszds":2408,"zmbzdszl":2181,"zmszdszl":2408,"cjbszl":91531,"zmbtdcje":419291294,"zmbddcje":202390171,"zmbzdcje":94361900,"zmbxdcje":11548543,"zmbtdcjl":363499,"zmbddcjl":175471,"zmbzdcjl":81703,"zmbxdcjl":9988,"zmbtdcjzl":419291294,"zmbddcjzl":202390171,"zmbzdcjzl":94361900,"zmbxdcjzl":11548543,"zmbtdcjzlv":363499,"zmbddcjzlv":175471,"zmbzdcjzlv":81703,"zmbxdcjzlv":9988,"zmstdcje":254935867,"zmsddcje":233680531,"zmszdcje":110770356,"zmsxdcje":12407239,"zmstdcjl":221166,"zmsddcjl":202546,"zmszdcjl":95880,"zmsxdcjl":10734,"zmstdcjzl":254935867,"zmsddcjzl":233680531,"zmszdcjzl":110770356,"zmsxdcjzl":12407239,"zmstdcjzlv":221166,"zmsddcjzlv":202546,"zmszdcjzlv":95880,"zmsxdcjzlv":10734,"bdmbtdcje":254935867,"bdmbddcje":233680531,"bdmbzdcje":110770356,"bdmbxdcje":12407239,"bdmbtdcjl":221166,"bdmbddcjl":202546,"bdmbzdcjl":95880,"bdmbxdcjl":10734,"bdmbtdcjzl":254935867,"bdmbddcjzl":233680531,"bdmbzdcjzl":110770356,"bdmbxdcjzl":12407239,"bdmbtdcjzlv":221166,"bdmbddcjzlv":202546,"bdmbzdcjzlv":95880,"bdmbxdcjzlv":10734,"bdmstdcje":419291294,"bdmsddcje":202390171,"bdmszdcje":94361900,"bdmsxdcje":11548543,"bdmstdcjl":363499,"bdmsddcjl":175471,"bdmszdcjl":81703,"bdmsxdcjl":9988,"bdmstdcjzl":419291294,"bdmsddcjzl":202390171,"bdmszdcjzl":94361900,"bdmsxdcjzl":11548543,"bdmstdcjzlv":363499,"bdmsddcjzlv":175471,"bdmszdcjzlv":81703,"bdmsxdcjzlv":9988}]
```

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/hs/history/transaction/交易日期（如20260821）/股票代码（如000001.SZ）?token=token证书"
response = requests.get(url)
data = response.json()
print(data)
```

