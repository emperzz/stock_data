# zzshare · 情绪热度

> 涵盖 14 个情绪相关接口

## 接口清单

| 接口 | HTTP | 功能 |
|---|---|---|
| `market_sentiment` | `GET /v3/market/sentiment/0/kline` | 综合市场情绪 K 线 |
| `market_hot_sentiment` | `GET /v3/market/sentiment/20/kline` | 市场热度 K 线 |
| `market_style` | `GET /v2/api/timing/market/style` | 市场风格评估 |
| `open_sentiment_data` | `GET /v3/sentiment/data` | 多维情绪聚合 |
| `sentiment_timing` | `GET /v3/sentiment/timing` | VIP 择时信号 |
| `sentiment_market_hot_day` | `GET /v3/api/sentiment/market/hot/day` | 当日市场热度 |
| `sentiment_trend` | `GET /v3/api/sentiment/trend/{model}` | 情绪趋势（单日） |
| `sentiment_trend_range` | `GET /v3/api/sentiment/trend/{model}/range` | 情绪趋势（区间） |
| `updown_distribution` | `GET /open/sentiment/updown/disctribution` | 涨跌分布统计 |
| `uplimit_trend` | `GET /open/sentiment/uplimit/trend` | 涨停家数趋势 |
| `sentiment_hot_day` | `GET /open/sentiment/hot/day` | 日度人气热点 |
| `sentiment_bull_data` | `GET /open/sentiment/bull/data` | 牛熊情绪对比 |
| `sentiment_market_top_n` | `GET /v2/api/sentiment/market/top/n` | 市场 TopN 情绪（**SDK 内已注释**） |

## 1. `market_sentiment` — 综合市场情绪 K 线

### 参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `date1` | `str` | ✅ | 起始日期 `YYYYMMDD` |
| `date2` | `str` | 否 | 截止日期 |

### 返回

`dict`（含日期轴 + 多维情绪指标序列），适合后处理成 DataFrame。

---

## 2. `market_hot_sentiment` — 市场热度 K 线

### 参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `date1` | `str` | ✅ | `YYYYMMDD` |
| `date2` | `str` | 否 | `YYYYMMDD` |

---

## 3. `market_style` — 市场风格评估

### 参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `date1` | `str` | ✅ | `YYYYMMDD` |

### 返回

适合什么风格的市场（成长 / 价值 / 大盘 / 小盘 等）的量化评估数据。

---

## 4. `open_sentiment_data` — 多维情绪聚合

### 参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `date1` | `str` | ✅ | `YYYYMMDD` |
| `date2` | `str` | 否 | `YYYYMMDD` |

---

## 5. `sentiment_timing` — VIP 择时信号

### 参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `date1` | `str` | ✅ | `YYYYMMDD` |
| `date2` | `str` | 否 | `YYYYMMDD` |

> 需 `sentiment_vip` 权限（高级 Token）。

---

## 6. `sentiment_market_hot_day` — 当日市场热度

### 参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `date` | `str` | ✅ | `YYYYMMDD` |

---

## 7. `sentiment_trend` — 情绪趋势（按模型）

### 参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `model` | `int` | ✅ | 模型 ID（1/2/3...，需实测枚举） |
| `date1` | `str` | 否 | `YYYYMMDD` |

---

## 8. `sentiment_trend_range` — 情绪趋势区间

### 参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `model` | `int` | ✅ | 模型 ID |
| `date1` | `str` | 否 | 区间起点 |
| `date2` | `str` | 否 | 区间终点 |

---

## 9. `updown_distribution` — 涨跌分布

### 参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `date1` | `str` | ✅ | `YYYYMMDD` |

### 返回

全市场每日上涨 / 下跌家数分布及涨停 / 跌停总数统计。

---

## 10. `uplimit_trend` — 涨停家数趋势

### 参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `date1` | `str` | ✅ | `YYYYMMDD` |

### 返回

全市场涨停家数趋势及赚钱效应分析。

---

## 11. `sentiment_hot_day` — 日度人气热点

### 参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `index` | `int` | 否 | 默认 0 |
| `st` | `int` | 否 | 默认 100（包含 ST 筛选） |

---

## 12. `sentiment_bull_data` — 牛熊情绪对比

### 参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `date1` | `str` | ✅ | `YYYYMMDD` |
| `date2` | `str` | 否 | `YYYYMMDD` |

---

## 13. `sentiment_market_top_n` — 市场 TopN 情绪（SDK 已注释）

### 接口

- **HTTP**: `GET /v2/api/sentiment/market/top/n`
- **SDK**: `DataApi.SHORTCUTS` 中此条目**已注释**——`client.py` 内未注册为方法，但 `client.pyi` 中保留了类型提示。

### 参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `modal_id` | `int` | 否 | 默认 1 |
| `date1` | `str` | 否 | 区间起点 |
| `date2` | `str` | 否 | 区间终点 |

> 注：实际调用需绕过 SDK 的快捷方法注册逻辑，直接通过 `api.query("v2/api/sentiment/market/top/n", params=...)` 调用。