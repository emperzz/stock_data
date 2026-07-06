# 10 沪深指数 API

> 抓取时间：2026-07-06
> 源站点：<https://www.zhituapi.com/hsindexapi.html>

本页与 `01-09` 不同:URL 路径前缀是 `/hz/`(沪深指数)而不是 `/hs/`(沪深股票),代码格式为 `000001.SH` / `000300.SZ` 等带市场后缀的指数代码。

> **关于本项目接入现状**:智兔指数 API 已接入(2026-07-06,`zhitu_fetcher.py` 已声明 `INDEX_REALTIME_QUOTE | INDEX_KLINE` 并实现 `get_index_realtime_quote()` + `get_kline_data()` override)。接入时探活确认所有 4 个核心端点(`/hz/real/ssjy`、`/hz/latest/fsjy`、`/hz/history/fsjy`、`/hz/list/hszs`)均返回 200 真实数据;实测无 token / token 无效时返回 `{"detail": "..."}` 信封,已在 fetcher 中识别。

---

## 一、指数列表

### 沪深主要指数列表接口

**API 地址**：

```
https://api.zhituapi.com/hz/list/hszs?token=token证书
```

**描述**：获取沪深两市主要的指数代码和名称,用于后续接口的参数传入。

**更新频率**：每日0点

**请求频率限制**：包量版1分钟300次 |体验版、包月版1分钟1000次 | 包年版1分钟3千次 | 至尊版1分钟6千次

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| dm | string | 指数代码,如:`000001.SH` |
| mc | string | 指数名称,如:`上证指数` |
| jys | string | 交易所,`"sh"` 表示上证,`"sz"` 表示深证 |

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/hz/list/hszs?token=token证书"
response = requests.get(url)
data = response.json()
print(data)
```

---

## 二、实时交易

### 实时交易数据

**API 地址**：

```
https://api.zhituapi.com/hz/real/ssjy/指数代码(如:000001.SH)?token=token证书
```

**描述**：根据《指数列表》得到的股票代码获取实时交易数据(您可以理解为日线的最新数据)。

**更新频率**：实时

**请求频率限制**：包量版1分钟300次 |体验版、包月版1分钟1000次 | 包年版1分钟3千次 | 至尊版1分钟6千次

**字段说明**(实时报价部分)：

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

**字段说明**(最近一根 K 线快照部分,与实时报价并列返回)：

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

> **注意**:上游返回体内同时含实时报价字段(p/o/h/l/yc/cje/v/pv/ud/pc/zf/t)和最近 K 线字段(t/o/h/l/c/v/a/pc),命名风格略不同(前一组用 `yc`/`cje`/`pv`,后一组用 `pc`/`a`)。文档按上游原始结构保留。

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/hz/real/ssjy/指数代码(如:000001.SH)?token=token证书"
response = requests.get(url)
data = response.json()
print(data)
```

---

## 三、行情数据

### 最新分时交易

**API 地址**：

```
https://api.zhituapi.com/hz/latest/fsjy/指数代码.市场(如000001.SH)/分时级别(如d)?token=token证书&limit=最新条数(例如2)
```

**描述**：根据《指数列表》得到的指数代码和分时级别获取最新交易数据,交易时间升序。目前分时级别支持 5分钟、15分钟、30分钟、60分钟、日线、周线、月线、年线,对应的请求参数分别为 `5、15、30、60、d、w、m、y`。

**更新频率**：实时

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

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/hz/latest/fsjy/指数代码.市场(如000001.SH)/分时级别(如d)?token=token证书&limit=最新条数(例如2)"
response = requests.get(url)
data = response.json()
print(data)
```

### 历史分时交易

**API 地址**：

```
https://api.zhituapi.com/hz/history/fsjy/指数代码.市场(如000001.SH)/分时级别(如d)?token=token证书&st=开始时间(如20240601)&et=结束时间(如20250430)
```

**描述**：根据《指数列表》得到的指数代码和分时级别获取历史交易数据,交易时间升序。目前分时级别支持 5分钟、15分钟、30分钟、60分钟、日线、周线、月线、年线,对应的请求参数分别为 `5、15、30、60、d、w、m、y`。开始时间以及结束时间的格式均为 `YYYYMMDD` 或 `YYYYMMDDhhmmss`,例如:`'20240101'` 或 `'20241231235959'`。不设置开始时间和结束时间则为全部历史数据。

**更新频率**：日线以上数据每日下午 15:30 开始更新,预计 17:10 完成更新

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

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/hz/history/fsjy/指数代码.市场(如000001.SH)/分时级别(如d)?token=token证书&st=开始时间(如20240601)&et=结束时间(如20250430)"
response = requests.get(url)
data = response.json()
print(data)
```

---

## 四、技术指标

> 4 个技术指标接口共用同一模板,只是路径末段(`macd` / `ma` / `boll` / `kdj`)不同。所有频率都支持,日线及以上每日 15:35 更新,分钟级盘中按频率滚动更新。

### 历史分时 MACD

**API 地址**：

```
https://api.zhituapi.com/hz/history/macd/指数代码(000001.SH)/分时级别(d)?token=token证书&st=开始时间&et=结束时间&lt=最新条数
```

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| t | string | 交易时间,短分时级别格式为 `yyyy-MM-ddHH:mm:ss`,日线级别为 `yyyy-MM-dd` |
| diff | number | DIFF 值 |
| dea | number | DEA 值 |
| macd | number | MACD 值 |
| ema12 | number | EMA(12) 值 |
| ema26 | number | EMA(26) 值 |

**返回示例**：

```json
[
  {"t":"2025-04-17 00:00:00","diff":-27.043,"dea":-27.177,"macd":0.268,"ema12":3268.3451,"ema26":3295.3885},
  {"t":"2025-04-18 00:00:00","diff":-24.371,"dea":-26.616,"macd":4.489,"ema12":3269.6351,"ema26":3294.0064},
  {"t":"2025-04-21 00:00:00","diff":-20.827,"dea":-25.458,"macd":9.262,"ema12":3272.9881,"ema26":3293.8155},
  {"t":"2025-04-22 00:00:00","diff":-17.149,"dea":-23.796,"macd":13.295,"ema12":3277.1069,"ema26":3294.2559},
  {"t":"2025-04-23 00:00:00","diff":-14.343,"dea":-21.906,"macd":15.126,"ema12":3280.0689,"ema26":3294.4117}
]
```

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/hz/history/macd/指数代码(000001.SH)/分时级别(d)?token=token证书&st=开始时间&et=结束时间&lt=最新条数"
response = requests.get(url)
data = response.json()
print(data)
```

### 历史分时 MA

**API 地址**：

```
https://api.zhituapi.com/hz/history/ma/指数代码(如000001.SH)/分时级别(如d)?token=token证书&st=开始时间&et=结束时间&lt=最新条数
```

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| t | string | 交易时间,短分时级别格式为 `yyyy-MM-ddHH:mm:ss`,日线级别为 `yyyy-MM-dd` |
| ma3 | number | MA3,没有则为 null |
| ma5 | number | MA5,没有则为 null |
| ma10 | number | MA10,没有则为 null |
| ma15 | number | MA15,没有则为 null |
| ma20 | number | MA20,没有则为 null |
| ma30 | number | MA30,没有则为 null |
| ma60 | number | MA60,没有则为 null |
| ma120 | number | MA120,没有则为 null |
| ma200 | number | MA200,没有则为 null |
| ma250 | number | MA250,没有则为 null |

**返回示例**：

```json
[
  {
    "t": "2025-07-21 15:00",
    "ma3": 12.6, "ma5": 12.598, "ma10": 12.597, "ma15": 12.5927, "ma20": 12.591,
    "ma30": 12.5903, "ma60": 12.6127, "ma120": 12.6279, "ma200": 12.6154, "ma250": 12.6638
  },
  {
    "t": "2025-07-22 09:35",
    "ma3": 12.6, "ma5": 12.596, "ma10": 12.595, "ma15": 12.5933, "ma20": 12.5915,
    "ma30": 12.5897, "ma60": 12.6115, "ma120": 12.628, "ma200": 12.6146, "ma250": 12.6622
  }
]
```

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/hz/history/ma/指数代码(如000001.SH)/分时级别(如d)?token=token证书&st=开始时间&et=结束时间&lt=最新条数"
response = requests.get(url)
data = response.json()
print(data)
```

### 历史分时 BOLL

**API 地址**：

```
https://api.zhituapi.com/hz/history/boll/指数代码(如000001.SH)/分时级别(如d)?token=token证书&st=开始时间&et=结束时间&lt=最新条数
```

> **注**:上游描述文字与 KDJ 复制粘贴,实际接口路径正确为 `boll`,返回 BOLL 数据。

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| t | string | 交易时间,短分时级别格式为 `yyyy-MM-ddHH:mm:ss`,日线级别为 `yyyy-MM-dd` |
| u | number | 上轨 |
| d | number | 下轨 |
| m | number | 中轨 |

**返回示例**：

```json
[
  {"t": "2025-07-18 14:00", "u": 13.11, "d": 12.38, "m": 12.75},
  {"t": "2025-07-18 15:00", "u": 13.09, "d": 12.38, "m": 12.74}
]
```

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/hz/history/boll/指数代码(如000001.SH)/分时级别(如d)?token=token证书&st=开始时间&et=结束时间&lt=最新条数"
response = requests.get(url)
data = response.json()
print(data)
```

### 历史分时 KDJ

**API 地址**：

```
https://api.zhituapi.com/hz/history/kdj/指数代码(如000001.SH)/分时级别(如d)?token=token证书&st=开始时间&et=结束时间&lt=最新条数
```

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| t | string | 交易时间,短分时级别格式为 `yyyy-MM-ddHH:mm:ss`,日线级别为 `yyyy-MM-dd` |
| k | number | K 值 |
| d | number | D 值 |
| j | number | J 值 |

**返回示例**：

```json
[
  {"t": "2025-07-18 14:00", "k": 57.73, "d": 43.01, "j": 87.16},
  {"t": "2025-07-18 15:00", "k": 63.88, "d": 49.97, "j": 91.71}
]
```

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/hz/history/kdj/指数代码(如000001.SH)/分时级别(如d)?token=token证书&st=开始时间&et=结束时间&lt=最新条数"
response = requests.get(url)
data = response.json()
print(data)
```

---

## 与本项目 `DataFetcherManager` 的对应

| 智兔指数接口 | 对应 `DataCapability` 标志 | 备注 |
|---|---|---|
| `hz/list/hszs` | n/a | 静态指数列表;本项目用 `data_provider/fetchers/index_symbols.py` 维护,不依赖智兔 |
| `hz/real/ssjy/<code>` | `INDEX_REALTIME_QUOTE` | **已接入**(`zhitu_fetcher.get_index_realtime_quote`)。⚠️ 上游**不返回** `name` 字段;`/indices/{code}/quote` route 层用 `index_symbols.CSI_INDEX_MAP` 兜底。`v` 字段是**手**(`* 100` 归一到股 per spec §3.4;与同 URL 模式的股票 `/hs/real/ssjy/` 不同 — 股票 public 是**万手**,broker `/hs/real/time/` 是手;2026-07-06 实测)。无 PE/PB/总市值/流通市值。 |
| `hz/latest/fsjy/<code>.<mkt>/<level>` | `INDEX_KLINE` | **已接入**;Manager 实际只调用 `hz/history/fsjy`(`hz/latest/fsjy` 文档存在但未实现,留作未来优化) |
| `hz/history/fsjy/<code>.<mkt>/<level>` | `INDEX_KLINE` | **已接入**(`zhitu_fetcher._get_index_kline_data`);`v` 字段是**手**(`* 100` 归一到股 per spec §3.4;与 Myquant gm SDK 同日 `volume_shares / Zhitu_v` = 100 精确匹配,2026-07-06 实测);`pct_chg` 由 `(close - pc) / pc * 100` 自算(上游不返百分比字段);`pc == 0` 时结果为 NA |
| `hz/history/{macd,ma,boll,kdj}/<code>/<level>` | n/a | **本项目已有自有 indicator 服务**(`data_provider/indicators/`),不依赖智兔 |

> 当前 `/indices/*` 三端点(`/indices`、`/indices/{code}/quote`、`/indices/{code}/kline`)的实际优先级链(2026-07-06 更新):
> - **quote**:`Akshare` → `Yfinance` → **Zhitu** → `Tencent`
> - **kline d/w/m**:`Baostock` → `Tushare` → `Akshare` → `Yfinance` → **Zhitu** → `Myquant`
> - **kline 5/15/30/60m**:`Akshare` → `Yfinance` → **Zhitu** → `Myquant`(**Zhitu 1m 不支持**,1m 仍走原链)
>
> Zhitu 后缀规则(`to_zhitu_index_market_suffix`):`000xxx` → `.SH`,`399xxx` → `.SZ`(**与股票 helper 相反**:股票 `000xxx` 是 SZ)。URL 路径中的代码段格式为 `<code>.<SH|SZ>`,例如 `000001.SH` / `399006.SZ`。
> Zhitu 港股/美股指数:不支持,`supports_kline` 对 hk/us 一律 False,Manager 跳过。
