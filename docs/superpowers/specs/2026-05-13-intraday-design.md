# 分时数据 API 设计

## 需求

在 server 上新增当日分时交易数据接口，支持多周期（1/5/15/30/60分钟）。优先使用 akshare，失败则 fallback 到 zhitu。

## API 设计

**Endpoint**: `GET /stocks/{stock_code}/intraday`

**Query 参数**:
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| period | str | "5" | 周期: "1", "5", "15", "30", "60" (分钟) |
| adjust | str | "" | 复权类型: ""=不复权, "qfq"=前复权, "hfq"=后复权 |

**响应** (Schema: `IntradayResponse`):
```python
{
  "stock_code": str,
  "stock_name": str,
  "period": str,        # "1m"/"5m"/"15m"/"30m"/"60m"
  "adjust": str,         # ""/"qfq"/"hfq"
  "date": str,           # 交易日期 YYYY-MM-DD
  "data": [
    {
      "time": str,       # HH:MM:SS
      "open": float,
      "high": float,
      "low": float,
      "close": float,
      "volume": int,
      "amount": float | null,
    }, ...
  ]
}
```

---

## Provider 层设计

## Provider 层设计

### AkshareFetcher 新增方法

```python
def get_intraday_data(
    self,
    stock_code: str,
    period: str = "5",      # "1"/"5"/"15"/"30"/"60"
    adjust: str = ""        # ""/"qfq"/"hfq"
) -> pd.DataFrame | None:
```

**内部策略**：按以下顺序尝试，成功即返回：

| 顺序 | 接口 | 函数 | 支持 adjust | 说明 |
|------|------|------|-------------|------|
| 1 | 东财 EM | `stock_zh_a_hist_min_em(symbol, start_date, end_date, period, adjust)` | ✅ | 1分钟数据只返回近5个交易日且不复权 |
| 2 | 新浪历史分钟 | `stock_zh_a_minute(symbol, period, adjust)` | ✅ | 直接返回最近交易日数据 |
| - | — | — | — | — |

> 注：原计划中的 EM `stock_intraday_em`（当日实时）和 Sina `stock_intraday_sina`（Tick 粒度）均**不支持 period 和 adjust**，不适用于分时数据需求，已排除。

**日期限制**：EM 接口支持 `start_date/end_date`，只传入最近一个交易日的日期区间（当日开盘 ~ 当日收盘）。新浪接口不支持日期参数，直接调用返回最近交易日数据。

**复权**：两个接口均支持 adjust 参数（`""`/`"qfq"`/`"hfq"`）。

**输出列标准化**：
- EM: `时间` → `time`, `开盘` → `open`, `收盘` → `close`, `最高` → `high`, `最低` → `low`, `成交量` → `volume`, `成交额` → `amount`
- 新浪历史分钟: `day` → `time`（提取 HH:MM:SS），`volume` 已是股数

### ZhituFetcher 新增方法

```python
def get_intraday_data(
    self,
    stock_code: str,
    period: str = "5",
    adjust: str = ""
) -> pd.DataFrame | None:
```

根据 zhitu 文档，历史分时交易 API：

**URL**: `https://api.zhituapi.com/hs/history/{code}.{market}/{period}/{adjust}?token={token}&st={start}&et={end}`

**URL 参数**：
- `code.market`: 股票代码+市场，如 `000001.SZ`、`600519.SH`
- `period`: 分时级别 — `5`/`15`/`30`/`60`（分钟），或 `d`/`w`/`m`/`y`（日/周/月/年）
- `adjust`: 除权方式 — `n`=不复权，`f`=前复权，`b`=后复权，`fr`=等比前复权，`br`=等比后复权
  - **注意**：分钟级数据无除权数据，统一用 `n`

**查询参数**：
- `st`: 开始时间，YYYYMMDD 或 YYYYMMDDhhmmss
- `et`: 结束时间，YYYYMMDD 或 YYYYMMDDhhmmss

**返回字段**（JSON）：
| 字段 | 类型 | 说明 |
|------|------|------|
| t | string | 交易时间 |
| o | float | 开盘价 |
| h | float | 最高价 |
| l | float | 最低价 |
| c | float | 收盘价 |
| v | float | 成交量 |
| a | float | 成交额 |
| pc | float | 前收盘价 |
| sf | int | 停牌标识（1停牌/0不停牌） |

**映射到标准列**：`t`→`time`，`o`→`open`，`h`→`high`，`l`→`low`，`c`→`close`，`v`→`volume`，`a`→`amount`

---

## Manager 层

`DataFetcherManager.get_intraday_data()` 按 priority 遍历 fetchers：

1. AkshareFetcher (priority 2) 优先
2. ZhituFetcher (priority 4) fallback

---

## 日期边界处理

Provider 接口若支持日期参数，传入逻辑：

```python
def _get_last_trade_date() -> str:
    # 从 stock_cache 获取最近交易日
    latest = get_latest_cached_trade_date()
    if not latest or latest < today:
        latest = today  # fallback to today
    return latest  # YYYY-MM-DD
```

Provider 调用时将日期传给支持日期的接口。

---

## 文件变更

| 文件 | 变更 |
|------|------|
| `data_provider/akshare_fetcher.py` | 新增 `get_intraday_data()`，内部 try/except 顺序尝试 EM → Sina → stock_zh_a_minute |
| `data_provider/zhitu_fetcher.py` | 新增 `get_intraday_data()`，调用 `/hs/history/{code}.{market}/{period}/{adjust}` 并解析返回字段 |
| `data_provider/base.py` | `BaseFetcher` 新增 `get_intraday_data()` 抽象方法；`DataFetcherManager` 新增 `get_intraday_data()` |
| `api/schemas.py` | 新增 `IntradayData`, `IntradayResponse` schema |
| `api/routes.py` | 新增 `/stocks/{stock_code}/intraday` endpoint |

---

## 错误处理

- 所有 provider 均失败：返回 500 + `DataFetchError`
- 不支持的 period：返回 400 + "不支持的周期"
- 非 A 股股票请求分时：返回 400 + "分时数据仅支持 A 股"
- Zhitu 不支持 `period=1`（分钟级无除权数据），当 Akshare 失败且降级到 Zhitu 时，若请求 `period=1` 则直接返回错误