# 08 技术指标

> 抓取时间：2026-10-08
> 源站点：<https://www.zhituapi.com/hsstockapi.html>
> 上游分类「技术指标」4 节 + 「行情数据」分类下的 4 个 Pro版·1分钟 指标（同属技术指标，归并至此）。

## 历史分时MACD

**API 地址**：

```
https://api.zhituapi.com/hs/history/macd/股票代码(如000001.SZ)/分时级别(如d)/除权类型(如n)?token=token证书&st=开始时间&et=结束时间&lt=最新条数
```

**描述**：根据《股票列表》得到的股票代码和分时级别获取历史MACD数据，交易时间升序。目前分时级别支持5分钟、15分钟、30分钟、60分钟、日线、周线、月线、年线，对应的请求参数分别为5、15、30、60、d、w、m、y，日线以上除权方式有不复权、前复权、后复权、等比前复权、等比后复权，对应的参数分别为n、f、b、fr、br，分钟级仅限请求不复权数据，对应的参数为n。开始时间以及结束时间的格式均为 YYYYMMDD 或 YYYYMMDDhhmmss，例如：'20240101' 或'20241231235959'。不设置开始时间和结束时间则为全部历史数据。同时可以指定获取数据条数，例如指定lt=10，则获取最新的10条数据。 【重要】1分钟级别技术指标已改为API扩能包专属，请使用 /…/pro/history/{macd|ma|boll|kdj}/…/1/… ；普通本路径的 period=1 已停止开放。其它周期（5/15/30/60/d/w/m/y）不变。

**更新频率**：分钟级别数据盘中更新，分时越小越优先更新，如5分钟级别会每5分钟更新，15分钟级别会每15分钟更新，以此类推，日线及以上级别每日15:35更新

**请求频率限制**：包量版1分钟300次 |体验版、包月版1分钟1000次 | 包年版1分钟3千次 | 至尊版1分钟6千次

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| t | string | 交易时间，短分时级别格式为yyyy-MM-ddHH:mm:ss，日线级别为yyyy-MM-dd |
| diff | number | DIFF值 |
| dea | number | DEA值 |
| macd | number | MACD值 |
| ema12 | number | EMA（12）值 |
| ema26 | number | EMA（26）值 |

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/hs/history/macd/股票代码(如000001.SZ)/分时级别(如d)/除权类型(如n)?token=token证书&st=开始时间&et=结束时间&lt=最新条数"
response = requests.get(url)
data = response.json()
print(data)
```

## 历史分时MA

**API 地址**：

```
https://api.zhituapi.com/hs/history/ma/股票代码(如000001.SZ)/分时级别(如d)/除权类型(如n)?token=token证书&st=开始时间&et=结束时间&lt=最新条数
```

**描述**：根据《股票列表》得到的股票代码和分时级别获取历史MA数据，交易时间升序。目前分时级别支持5分钟、15分钟、30分钟、60分钟、日线、周线、月线、年线，对应的请求参数分别为5、15、30、60、d、w、m、y，日线以上除权方式有不复权、前复权、后复权、等比前复权、等比后复权，对应的参数分别为n、f、b、fr、br，分钟级仅限请求不复权数据，对应的参数为n。开始时间以及结束时间的格式均为 YYYYMMDD 或 YYYYMMDDhhmmss，例如：'20240101' 或'20241231235959'。不设置开始时间和结束时间则为全部历史数据。同时可以指定获取数据条数，例如指定lt=10，则获取最新的10条数据。 【重要】1分钟级别技术指标已改为API扩能包专属，请使用 /…/pro/history/{macd|ma|boll|kdj}/…/1/… ；普通本路径的 period=1 已停止开放。其它周期（5/15/30/60/d/w/m/y）不变。

**更新频率**：分钟级别数据盘中更新，分时越小越优先更新，如5分钟级别会每5分钟更新，15分钟级别会每15分钟更新，以此类推，日线及以上级别每日15:35更新

**请求频率限制**：包量版1分钟300次 |体验版、包月版1分钟1000次 | 包年版1分钟3千次 | 至尊版1分钟6千次

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
[
        {
        "t": "2025-07-21 15:00",
        "ma3": 12.6,
        "ma5": 12.598,
        "ma10": 12.597,
        "ma15": 12.5927,
        "ma20": 12.591,
        "ma30": 12.5903,
        "ma60": 12.6127,
        "ma120": 12.6279,
        "ma200": 12.6154,
        "ma250": 12.6638
    },
    {
        "t": "2025-07-22 09:35",
        "ma3": 12.6,
        "ma5": 12.596,
        "ma10": 12.595,
        "ma15": 12.5933,
        "ma20": 12.5915,
        "ma30": 12.5897,
        "ma60": 12.6115,
        "ma120": 12.628,
        "ma200": 12.6146,
        "ma250": 12.6622
    }
]
```

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/hs/history/ma/股票代码(如000001.SZ)/分时级别(如d)/除权类型(如n)?token=token证书&st=开始时间&et=结束时间&lt=最新条数"
response = requests.get(url)
data = response.json()
print(data)
```

## 历史分时BOLL

**API 地址**：

```
https://api.zhituapi.com/hs/history/boll/股票代码(如000001.SZ)/分时级别(如d)/除权类型(如n)?token=token证书&st=开始时间&et=结束时间&lt=最新条数
```

**描述**：根据《股票列表》得到的股票代码和分时级别获取历史BOLL数据，交易时间升序。目前分时级别支持5分钟、15分钟、30分钟、60分钟、日线、周线、月线、年线，对应的请求参数分别为5、15、30、60、d、w、m、y，日线以上除权方式有不复权、前复权、后复权、等比前复权、等比后复权，对应的参数分别为n、f、b、fr、br，分钟级仅限请求不复权数据，对应的参数为n。开始时间以及结束时间的格式均为 YYYYMMDD 或 YYYYMMDDhhmmss，例如：'20240101' 或'20241231235959'。不设置开始时间和结束时间则为全部历史数据。同时可以指定获取数据条数，例如指定lt=10，则获取最新的10条数据。 【重要】1分钟级别技术指标已改为API扩能包专属，请使用 /…/pro/history/{macd|ma|boll|kdj}/…/1/… ；普通本路径的 period=1 已停止开放。其它周期（5/15/30/60/d/w/m/y）不变。

**更新频率**：分钟级别数据盘中更新，分时越小越优先更新，如5分钟级别会每5分钟更新，15分钟级别会每15分钟更新，以此类推，日线及以上级别每日15:35更新

**请求频率限制**：包量版1分钟300次 |体验版、包月版1分钟1000次 | 包年版1分钟3千次 | 至尊版1分钟6千次

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| t | string | 交易时间，短分时级别格式为yyyy-MM-ddHH:mm:ss，日线级别为yyyy-MM-dd |
| u | number | 上轨 |
| d | number | 下轨 |
| m | number | 中轨 |

**返回示例**：

```json
[    
    {
        "t": "2025-07-18 14:00",
        "u": 13.11,
        "d": 12.38,
        "m": 12.75
    },
    {
        "t": "2025-07-18 15:00",
        "u": 13.09,
        "d": 12.38,
        "m": 12.74
    }
]
```

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/hs/history/boll/股票代码(如000001.SZ)/分时级别(如d)/除权类型(如n)?token=token证书&st=开始时间&et=结束时间&lt=最新条数"
response = requests.get(url)
data = response.json()
print(data)
```

## 历史分时KDJ

**API 地址**：

```
https://api.zhituapi.com/hs/history/kdj/股票代码(如000001.SZ)/分时级别(如d)/除权类型(如n)?token=token证书&st=开始时间&et=结束时间&lt=最新条数
```

**描述**：根据《股票列表》得到的股票代码和分时级别获取历史KDJ数据，交易时间升序。目前分时级别支持5分钟、15分钟、30分钟、60分钟、日线、周线、月线、年线，对应的请求参数分别为5、15、30、60、d、w、m、y，日线以上除权方式有不复权、前复权、后复权、等比前复权、等比后复权，对应的参数分别为n、f、b、fr、br，分钟级仅限请求不复权数据，对应的参数为n。开始时间以及结束时间的格式均为 YYYYMMDD 或 YYYYMMDDhhmmss，例如：'20240101' 或'20241231235959'。不设置开始时间和结束时间则为全部历史数据。同时可以指定获取数据条数，例如指定lt=10，则获取最新的10条数据。 【重要】1分钟级别技术指标已改为API扩能包专属，请使用 /…/pro/history/{macd|ma|boll|kdj}/…/1/… ；普通本路径的 period=1 已停止开放。其它周期（5/15/30/60/d/w/m/y）不变。

**更新频率**：分钟级别数据盘中更新，分时越小越优先更新，如5分钟级别会每5分钟更新，15分钟级别会每15分钟更新，以此类推，日线及以上级别每日15:35更新

**请求频率限制**：包量版1分钟300次 |体验版、包月版1分钟1000次 | 包年版1分钟3千次 | 至尊版1分钟6千次

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| t | string | 交易时间，短分时级别格式为yyyy-MM-ddHH:mm:ss，日线级别为yyyy-MM-dd |
| k | number | K值 |
| d | number | D值 |
| j | number | J值 |

**返回示例**：

```json
[   
    {
        "t": "2025-07-18 14:00",
        "k": 57.73,
        "d": 43.01,
        "j": 87.16
    },
    {
        "t": "2025-07-18 15:00",
        "k": 63.88,
        "d": 49.97,
        "j": 91.71
    }
]
```

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/hs/history/kdj/股票代码(如000001.SZ)/分时级别(如d)/除权类型(如n)?token=token证书&st=开始时间&et=结束时间&lt=最新条数"
response = requests.get(url)
data = response.json()
print(data)
```

<!-- 以下 4 节上游归类于「行情数据」 -->

## 历史分时MACD（Pro版·1分钟）

**API 地址**：

```
https://api.zhituapi.com/hs/pro/history/macd/股票代码(如000001.SZ)/1/除权类型(如n)?token=token证书&st=开始时间&et=结束时间&lt=最新条数
```

**描述**：API扩能包专属。路径须含 /pro/history/macd/。根据《股票列表》代码获取1分钟历史MACD（period 固定为 1）。除权参数请使用 n。支持 st/et/lt。请勿再使用普通路径 /hs/history/macd/…/1/（已停止开放）。其它周期指标仍走普通 /history/macd/ 路径。

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
url = "https://api.zhituapi.com/hs/pro/history/macd/股票代码(如000001.SZ)/1/除权类型(如n)?token=token证书&st=开始时间&et=结束时间&lt=最新条数"
response = requests.get(url)
data = response.json()
print(data)
```

## 历史分时MA（Pro版·1分钟）

**API 地址**：

```
https://api.zhituapi.com/hs/pro/history/ma/股票代码(如000001.SZ)/1/除权类型(如n)?token=token证书&st=开始时间&et=结束时间&lt=最新条数
```

**描述**：API扩能包专属。路径须含 /pro/history/ma/。根据《股票列表》代码获取1分钟历史MA（period 固定为 1）。除权参数请使用 n。支持 st/et/lt。请勿再使用普通路径 /hs/history/ma/…/1/（已停止开放）。其它周期指标仍走普通 /history/ma/ 路径。

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
url = "https://api.zhituapi.com/hs/pro/history/ma/股票代码(如000001.SZ)/1/除权类型(如n)?token=token证书&st=开始时间&et=结束时间&lt=最新条数"
response = requests.get(url)
data = response.json()
print(data)
```

## 历史分时BOLL（Pro版·1分钟）

**API 地址**：

```
https://api.zhituapi.com/hs/pro/history/boll/股票代码(如000001.SZ)/1/除权类型(如n)?token=token证书&st=开始时间&et=结束时间&lt=最新条数
```

**描述**：API扩能包专属。路径须含 /pro/history/boll/。根据《股票列表》代码获取1分钟历史BOLL（period 固定为 1）。除权参数请使用 n。支持 st/et/lt。请勿再使用普通路径 /hs/history/boll/…/1/（已停止开放）。其它周期指标仍走普通 /history/boll/ 路径。

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
url = "https://api.zhituapi.com/hs/pro/history/boll/股票代码(如000001.SZ)/1/除权类型(如n)?token=token证书&st=开始时间&et=结束时间&lt=最新条数"
response = requests.get(url)
data = response.json()
print(data)
```

## 历史分时KDJ（Pro版·1分钟）

**API 地址**：

```
https://api.zhituapi.com/hs/pro/history/kdj/股票代码(如000001.SZ)/1/除权类型(如n)?token=token证书&st=开始时间&et=结束时间&lt=最新条数
```

**描述**：API扩能包专属。路径须含 /pro/history/kdj/。根据《股票列表》代码获取1分钟历史KDJ（period 固定为 1）。除权参数请使用 n。支持 st/et/lt。请勿再使用普通路径 /hs/history/kdj/…/1/（已停止开放）。其它周期指标仍走普通 /history/kdj/ 路径。

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
url = "https://api.zhituapi.com/hs/pro/history/kdj/股票代码(如000001.SZ)/1/除权类型(如n)?token=token证书&st=开始时间&et=结束时间&lt=最新条数"
response = requests.get(url)
data = response.json()
print(data)
```

> **本项目备注**（非上游原文）：Pro 系列接口属「API扩能包」付费能力，本项目 `ZhituFetcher` 未接入；股票分钟线现走 `hs/latest|history/fsjy`（5/15/30/60m）与「企业版历史数据【1m级别】」。

