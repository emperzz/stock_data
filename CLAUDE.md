# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A Python-based local stock data aggregation server that:
- Integrates 10 upstream stock data APIs (Tushare, Baostock, Akshare, Yfinance, Zhitu, Tencent, EastMoney, THS, Cninfo, Myquant)
- Normalizes data into a unified format across all capability groups (行情/资金面/基础数据/公告/研报/特殊池/etc.)
- Provides a stable REST API for consumption by AI agents like OpenClaw

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    API Layer (FastAPI)                   │
│   GET /stocks/{code}/quote   GET /stocks/{code}/history?indicators=ma,macd │
│   GET /stocks/{code}/intraday GET /stocks/{code}/dragon-tiger │
│   GET /stocks/{code}/margin   GET /stocks/{code}/block-trade │
│   GET /stocks/{code}/fund-flow GET /stocks/{code}/reports   │
│   GET /dragon-tiger/daily     GET /hot/topics              │
│   GET /north-flow/realtime    GET /indices/{code}/quote     │
│   GET /indicators/catalog                                  │
├─────────────────────────────────────────────────────────┤
│              IndicatorService (pure compute)              │
│   MA · MACD · BOLL · KDJ · RSI · WR · BIAS · CCI · ATR   │
│   OBV · ROC · DMI · SAR · KC                              │
│   Sits on top of the manager; no fetcher involvement       │
├─────────────────────────────────────────────────────────┤
│                 DataFetcherManager                        │
│    Priority-based failover, circuit breaker, caching       │
├─────────────────────────────────────────────────────────┤
│                   Source Adapters                         │
│  TushareFetcher  BaostockFetcher  AkshareFetcher  YfinanceFetcher ...    │
│  TencentFetcher  EastMoneyFetcher  ThsFetcher  CninfoFetcher              │
├─────────────────────────────────────────────────────────┤
│              Upstream Stock Data APIs                    │
```

Indicators are a **pure-compute** layer on top of `DataFetcherManager`
(see `data_provider/indicators/` for the architectural details and the
conventions that govern adding a new indicator).

## Directory Structure

```
stock_data/
├── __init__.py
├── server.py
├── api/
│   ├── __init__.py
│   ├── routes.py
│   ├── schemas.py
│   ├── cache.py                    # In-memory TTLCache for API responses
│   └── endpoint_meta.py            # @endpoint_meta decorator + REGISTRY (explorer manifest)
├── explorer/                       # /explorer/ HTML UI + /control/* management endpoints
│   ├── __init__.py                 # mount(app) entry point; also runs startup sanity checks
│   ├── manifest.py                 # build_manifest(app) — reflects app.routes + REGISTRY
│   ├── routes.py                   # /control/* FastAPI router (config, status, api-manifest)
│   ├── tags.py                     # TAG_TO_TITLE + CAPABILITY_LABELS + _INTERNAL_TAGS
│   └── static/
│       └── index.html              # Single-page interactive docs (vanilla JS)
└── data_provider/
    ├── __init__.py                  # Public API re-exports
    ├── base.py                      # BaseFetcher (ABC), DataCapability, DataFetchError
    ├── manager.py                   # DataFetcherManager (priority-based failover)
    ├── core/
    │   ├── __init__.py
    │   └── types.py                # UnifiedRealtimeQuote, CircuitBreaker, safe_float/int
    ├── fetchers/
    │   ├── __init__.py
    │   ├── index_symbols.py        # Index mappings (CSI/HK/US)
    │   ├── akshare/
    │   │   ├── __init__.py
    │   │   ├── fetcher.py
    │   │   ├── board.py
    │   │   └── index_norm.py
    │   ├── baostock_fetcher.py
    │   ├── cninfo_fetcher.py
    │   ├── eastmoney_fetcher.py
    │   ├── tencent_fetcher.py
    │   ├── ths_fetcher.py
    │   ├── tushare_fetcher.py
    │   ├── yfinance_fetcher.py
    │   └── zhitu_fetcher.py
    ├── persistence/                # Cross-process SQLite storage layer (on-disk; replaces legacy data_provider/cache/)
    │   ├── __init__.py             # Top-level API: init_schema(), reset_all() (used by STOCK_DB_INIT); re-exports CRUD
    │   ├── db.py                   # get_db_path() / get_connection() (public names)
    │   ├── stock_list.py           # Stock listing metadata (init_schema, get_stock_list, ...)
    │   ├── board.py                # Concept/industry board metadata
    │   ├── trade_calendar.py       # A-share trade calendar + is_trade_date() / get_latest_trade_date_on_or_before()
    │   └── pool_daily.py           # Unified pool_daily (zt | dt | zbgc) — single table, date-keyed
    ├── indicators/                 # Pure-compute technical indicator layer
    │   ├── __init__.py             # Public exports (IndicatorService + 14 calcs)
    │   ├── types.py                # IndicatorKey, MAOptions, MACDOptions, ...
    │   ├── registry.py             # INDICATOR_REGISTRY + estimate_lookback()
    │   ├── indicator_service.py    # Orchestrator (K-line → indicators → df)
    │   ├── ma.py                   # SMA / EMA / WMA + calcMA
    │   ├── macd.py
    │   ├── boll.py
    │   ├── kdj.py
    │   ├── rsi.py
    │   ├── wr.py
    │   ├── bias.py
    │   ├── cci.py
    │   ├── atr.py
    │   ├── obv.py
    │   ├── roc.py
    │   ├── dmi.py
    │   ├── sar.py
    │   └── kc.py
    └── utils/
        ├── __init__.py
        └── normalize.py            # normalize_stock_code, market_tag, etc.
```

## Core Components

### `data_provider/base.py`
- `BaseFetcher`: Abstract base defining `_fetch_raw_data()`, `_normalize_data()`, `get_kline_data()`, `get_realtime_quote()`
- `DataCapability`: Flag enum for fetcher capability declarations (see below)
- `DataFetchError`, `RateLimitError`: Exception classes
- `STANDARD_COLUMNS`: Standardized K-line column names

### `data_provider/manager.py`
- `DataFetcherManager`: Orchestrates fetchers with priority-based failover, circuit breakers, and capability-based routing
- All data access methods route through `_filter_by_capability(market, capability)`

### `data_provider/fetchers/`
- Each source has its own fetcher: `baostock_fetcher.py`, `akshare/` (package), `yfinance_fetcher.py`, `tushare_fetcher.py`, `zhitu_fetcher.py`, `tencent_fetcher.py`, `eastmoney_fetcher.py`, `ths_fetcher.py`, `cninfo_fetcher.py`
- Each fetcher handles:
  - Source-specific API calls
  - Rate limiting (random jitter, User-Agent rotation)
  - Data normalization to standard format
  - Retry with exponential backoff (using `tenacity`)

### `data_provider/core/types.py`
- `UnifiedRealtimeQuote`: Dataclass for normalized realtime quotes
- `CircuitBreaker`: Thread-safe circuit breaker implementation
- `safe_float()`, `safe_int()`: Type-safe conversion utilities (rejects NaN, inf, -inf)

### `data_provider/persistence/`
- `db.py`: Shared `get_db_path()` and `get_connection()` used by all persistence submodules
- `stock_list.py`: Persistent stock list with auto-refresh (first call of day)
- `board.py`: Concept/industry board metadata
- `pool_daily.py`: Unified ZT/DT/ZBGC pool table (single `pool_daily` table, `pool_type` column discriminator)
- `trade_calendar.py`: A-share trade calendar + `is_trade_date()` / `get_latest_trade_date_on_or_before()` helpers

### `data_provider/utils/normalize.py`
- `normalize_stock_code()`: Handles various input formats (SH600519 → 600519, etc.)
- `market_tag()`: Returns market tag (csi/us/hk)
- `is_us_market()`, `is_hk_market()`: Market detection utilities

### `api/endpoint_meta.py`
Per-route metadata used by the explorer manifest. Each route in `api/routes.py`
is decorated with `@endpoint_meta(summary=..., markets=[...], capabilities=[...])`,
which stores an `EndpointMeta` (frozen dataclass: `summary / markets / capabilities`)
in a module-level `REGISTRY: dict[Callable, EndpointMeta]`.

- **Decorator contract**: `endpoint_meta.deco` MUST return the same `func` it
  receives (not a wrapper). FastAPI captures `route.endpoint` at `@router.get`
  decoration time as the function reference AFTER the inner `@endpoint_meta` has
  run; if this ever wraps/replaces, `REGISTRY.get(route.endpoint)` misses and
  the route silently disappears from the explorer manifest.
- **Cache/sources/probe_url/section_id were removed** in the manifest cleanup;
  the manifest now carries only fields actually consumed by the HTML.

### `explorer/`
Subpackage owning the `/explorer/` HTML UI and `/control/*` management
endpoints. Mounted by `stock_data.server` via `explorer.mount(app)`.

- **`explorer/__init__.py`** — `mount(app)` is the single entry point. It mounts
  the static HTML, includes the `/control/*` router, and runs a startup sanity
  check (`_validate_manifest_invariants`) that warns about (a) routes missing
  `@endpoint_meta` and (b) route tags not present in `TAG_TO_TITLE`.
- **`explorer/manifest.py`** — `build_manifest(app)` reflects `app.routes`,
  merges each route's `route.endpoint` lookup into `REGISTRY`, and returns a
  JSON tree (`{meta, sections[]}` where each endpoint node has a `fetchers[]`
  field describing the fetcher backends; see "Stage 1/2 Fetcher Drill-down"
  below). Rebuilt on every request to `/control/api-manifest` (no caching —
  ~5 KB payload, sub-millisecond build).
- **`explorer/routes.py`** — `/control/*` APIRouter. Endpoints: `/config`,
  `/server/status`, `/api-manifest`, `/fetcher-test`. All tagged `control`
  → excluded from the manifest.
- **`explorer/tags.py`** — `TAG_TO_TITLE` (route tag → sidebar section title). The section id is the tag name itself (just a stable DOM anchor / URL hash; no business meaning).
  and `CAPABILITY_LABELS` (DataCapability flag → `{label, icon}`).
- **`explorer/static/index.html`** — Single-page interactive docs. Fetches
  `/control/api-manifest` on load and renders a sidebar with search, market
  filter, capability filter, and a right-side response panel. Includes a
  manifest-fetch-failure error banner (in `.main`, not the top bar).

### `data_provider/indicators/`
Pure-compute technical-indicator layer. Sits **on top of** `DataFetcherManager`
and never reaches down into fetchers or the network. Each indicator is a
standalone pure function in its own file; `registry.py` and
`indicator_service.py` provide the orchestration layer.

- **`types.py`** — `IndicatorKey` enum, per-indicator options TypedDicts
  (`MAOptions`, `MACDOptions`, `BOLLOptions`, ...), `OHLCV`, `IndicatorResult`
- **`registry.py`** — `INDICATOR_REGISTRY` (key → `IndicatorDescriptor`),
  `list_indicators()` (catalog for `/indicators/catalog`),
  `estimate_lookback(spec)` (how many K-line bars to fetch to warm up
  the requested indicators)
- **`indicator_service.py`** — `IndicatorService.compute(df, spec)` is the
  main entry point. It accepts either `["ma", "macd"]` (use defaults) or
  a full `{"ma": {"periods": [5,20]}, "macd": {}}` spec, and returns a
  copy of the K-line DataFrame with an added `indicators` column whose
  values are per-bar dicts (e.g. `{"ma5": 12.34, "macd_dif": 0.23}`)
- **One file per indicator** — `ma.py` (SMA/EMA/WMA), `macd.py`, `boll.py`,
  `kdj.py`, `rsi.py`, `wr.py`, `bias.py`, `cci.py`, `atr.py`, `obv.py`,
  `roc.py`, `dmi.py`, `sar.py`, `kc.py`. Each exports a `calcX(...)`
  function with the same calling convention.

**Conventions** (apply to all 14):
- Inputs are `list[float | None]` (closes) or `list[OHLCV]` (bars needing
  high/low/volume). `None` = "missing data", never 0.
- Outputs are aligned to the input index. A value is `None` whenever the
  indicator is not yet defined at that bar (insufficient lookback, NaN
  in input, etc.) — never a forward-fill, never a 0 placeholder.
- Outputs are rounded to 2 decimals at the boundary (not in inner loops,
  to keep recursive indicators like EMA numerically clean).
- NaN inputs in the input list are coerced to None by `_valid()` and
  treated as missing.

**Anti-patterns**:
- Do NOT call fetchers from inside an indicator. Indicators are pure.
- Do NOT add an indicator without registering it in `INDICATOR_REGISTRY`
  AND adding a public export in `__init__.py`. The catalog endpoint and
  the orchestrator both read the registry.
- Do NOT bake an indicator's `min_periods=1` workaround into a calc
  function to "produce a value sooner". Output `None` until the indicator
  is properly defined — this is the convention.

## Standardized Data Schema

**Historical K-line columns** (`STANDARD_COLUMNS`):
```
date, open, high, low, close, volume, amount, pct_chg
```

**Realtime quote fields**:
```
code, name, source, price, change_pct, change_amount,
volume, amount, volume_ratio, turnover_rate, amplitude,
open_price, high, low, pre_close, pe_ratio, pb_ratio, total_mv, circ_mv
```

**K-line with indicators** (response of `/stocks/{code}/history?indicators=...`
or `/indices/{code}/history?indicators=...`):
```python
KLineData(
    date, open, high, low, close, volume,
    amount: float|None,         # present in JSON as null when missing
    change_percent: float|None, # present in JSON as null when missing
    # ---- below: 4 fields OMITTED from JSON when their value is None/empty ----
    ma5, ma10, ma20,   # back-compat: copied from indicators dict when "ma" requested
    indicators: {     # per-bar dict; populated only when ?indicators= is set
        "ma5": float|None,
        "macd_dif": float|None, "macd_dea": float|None, "macd_hist": float|None,
        "kdj_k": float|None, "kdj_d": float|None, "kdj_j": float|None,
        "boll_mid": float|None, "boll_upper": float|None,
        "boll_lower": float|None, "boll_bandwidth": float|None,
        # ... one entry per output column of the requested indicators
    },
)
# Without `?indicators=`, the 4 fields above are absent from the JSON
# (KLineData._serialize uses @model_serializer to drop them when None/empty).
# `amount` and `change_percent` keep their original "present-as-null-when-missing" behavior.
```

**Indicator catalog entry** (response of `/indicators/catalog`):
```python
IndicatorCatalogEntry(
    key: str,                   # "ma" | "macd" | "boll" | ...
    input_shape: str,           # "closes" or "ohlcv"
    default_options: dict,      # e.g. {"short": 12, "long": 26, "signal": 9}
    output_columns: list[str],  # e.g. ["macd_dif", "macd_dea", "macd_hist"]
    default_lookback: int,      # bars of K-line needed to warm up with defaults
)
```

**StockInfo response** (response of `/stocks/{code}/info`):
```python
StockInfoResponse(
    code, name, ename, market,
    listed_date, delisted_date,
    total_shares, float_shares,  # 万股
    industry, concepts,           # `industry` 当前始终为空; 保留为扩展钩子
    registered_address, registered_capital, legal_representative,
    business_scope, established_date,
    secretary, secretary_phone, secretary_email,
    source,                       # "ZhituFetcher" | "MyquantFetcher"
)
```

**StockInfo response (list)** (response of `GET /stocks?market=csi|hk|us`):
```python
StockInfo(
    code, name, market,
    exchange: str|None,  # "SH" / "SZ" / "BJ" when known; null otherwise
                        # (Zhitu / Myquant populate; Baostock / Akshare leave null)
)
```

## Source Tracking (new)

所有响应都包含 `source: str` 字段, 取值:
- **fetcher 名** (e.g. `tushare`, `akshare`, `eastmoney`): 实时从上游拉取
- **fetcher 名**: API TTLCache 命中时, 保留写入时的 fetcher (Pydantic 字段自然带过去, 无需额外代码)
- **`"persistence"`**: 从 SQLite 持久化层读取 (历史数据 / 板块列表 / 交易日历等)

`source` 为可选字段, `default=""`. 旧 client 可忽略.

**覆盖矩阵**:

| Endpoint 类型 | 实时拉取 / 缓存命中 | SQLite persistence |
|---|---|---|
| K线 / 分时 / 实时行情 / 指数 | fetcher 名 (e.g. `tushare`, `akshare`) | n/a |
| 龙虎榜 / 融资融券 / 大宗交易 / 资金流 / 研报 / 公告 等 | fetcher 名 (e.g. `eastmoney`, `cninfo`, `ths`) | n/a (每次 fetch) |
| 板块 / 涨跌停 / 股票列表 / 交易日历 | fetcher 名 (refresh 时) | `"persistence"` (缓存命中) |
| 板块成分股 | 用户传入 source → `query_source`; 实际数据源 → `data_source` | `data_source = "persistence"` (缓存命中) |

> **注意**: `/stocks` 和 `/calendar` 当前响应**不暴露** source 字段 (其 response model 没有 source 字段), 持久化层 origin 仍被透传但被丢弃。这是 YAGNI 决策——如果未来要暴露, 给对应 response model 加 `source: str` 字段即可, 路由层已准备好。

## Stage 1/2 Fetcher Drill-down (Explorer)

The `/explorer/` UI shows, under each endpoint card, a collapsible
"Fetcher backends" section listing every fetcher that can serve the
endpoint along with its internal method signature. Each row has a
`Test` button that opens an inline form posting to `POST /control/fetcher-test`
to invoke the fetcher method directly (bypassing manager failover).

### Data flow

1. `GET /control/api-manifest` returns endpoints with a new `fetchers[]`
   field. Each entry is `{name, method, priority, capabilities, signature}`
   where `name` is the fetcher class name (e.g. `BaostockFetcher`).
2. The manifest builder uses `data_provider.base.CAPABILITY_TO_METHOD`
   (and `EndpointMeta.fetcher_method` override) to figure out the right
   method per fetcher.
3. HTML renders the rows under a `<details>`-based collapse.
4. Clicking Test → POST `/control/fetcher-test` body
   `{fetcher, method, kwargs}` → **always HTTP 200**; success/failure in
   the body's `ok` field. Errors classified as
   `UnknownFetcher / UnknownMethod / FetcherUnavailable / TypeError / <ExceptionName>`,
   each with optional traceback.

### `fetcher_method` overrides (3 known)

`@endpoint_meta(fetcher_method=...)` pins the method when the capability's
default isn't right:

| Endpoint | Capability | Override method |
|----------|------------|-----------------|
| `/boards/{board_code}/stocks` | `STOCK_BOARD` | `get_concept_board_stocks` |
| `/dragon-tiger/daily` | `DRAGON_TIGER` | `get_daily_dragon_tiger` |
| `/stocks/{stock_code}/fund-flow/daily` | `FUND_FLOW` | `get_fund_flow_120d` |

**`/boards` (single endpoint, `?type=concept|industry` dispatch) Stage 2
tests the concept variant by default**; industry variant is not exposed
in the UI (the user can change the method name in the mini-form manually).

### Anti-patterns

- **Don't** add a `DataCapability` without putting it in either
  `CAPABILITY_TO_METHOD` or `_NO_FETCHER_METHOD`. Both startup sanity
  checks and `tests/test_capability_method_map.py` will refuse silently.
- **Don't** assume Stage 2 result is "production-equivalent" — it bypasses
  the manager's circuit breaker and the capability filter.
- **Don't** rely on `/control/fetcher-test` from external networks — it's
  127.0.0.1-only via the control router.

## Provider API Documentation

### BaostockFetcher (Priority 1, A股 only, Free)

**API**: `bs.query_history_k_data_plus(code, fields, start_date, end_date, frequency, adjustflag)`

**Frequency**: `d`=日线, `w`=周线, `m`=月线, `5/15/30/60`=分钟线（不适用指数）

**Fields (日线)**:
```
date, open, high, low, close, preclose, volume, amount, adjustflag, turn, tradestatus, pctChg, isST
```

**Note**: Baostock has **NO realtime quotes API** - only historical data.

**Links**: https://baostock.com/mainContent?file=stockKData.md

---

### AkshareFetcher (Priority 2, A股+HK, Free)

**A-share API**: `ak.stock_zh_a_hist(symbol, period, start_date, end_date, adjust)`
- `period`: `'daily'`, `'weekly'`, `'monthly'`
- `adjust`: `''`=不复权, `'qfq'`=前复权, `'hfq'`=后复权

**HK API**: `ak.stock_hk_hist(symbol, period, start_date, end_date, adjust)`
- Same parameters as A-share

**Output columns (中文)**:
```
日期, 股票代码, 开盘, 收盘, 最高, 最低, 成交量, 成交额, 振幅, 涨跌幅, 涨跌额, 换手率
```

**Links**: https://akshare.akfamily.xyz/data/stock/stock.html

---

### TushareFetcher (Priority 0, A股, Requires Token)

**APIs**: `api.query('daily', ...)`, `api.query('weekly', ...)`, `api.query('monthly', ...)`

**Output columns** (same for daily/weekly/monthly):
```
ts_code, trade_date, open, high, low, close, pre_close, change, pct_chg, vol, amount
```

**Units**:
- `vol`: 手 (1手=100股) → convert to shares
- `amount`: 千元 → convert to yuan

**Note**: All three interfaces return **未复权行情**. For 复权数据, use the 复权因子接口 separately.

**Links**: https://tushare.pro/document/2?doc_id=27 (daily), doc_id=144 (weekly), doc_id=145 (monthly)

---

### YfinanceFetcher (Priority 3, US+A股+HK, Free)

**API**: `yf.download(tickers, start, end, auto_adjust=True)`

**Supports**: US stocks, US indices (via `US_INDEX_MAP`), A-share (.SS/.SZ), HK (.HK)

**Frequency**: Only daily (intervals via `interval` param: `'1d'`, `'1wk'`, `'1mo'`, `'5m'`, etc.)

---

### ZhituFetcher (Priority 4, A股 realtime only, Requires Token)

**API**: `https://api.zhituapi.com/hs/real/ssjy/{stock_code}?token={token}`

**Supports**: A股 realtime quotes only (no historical K-line data)

**Token**: Set via `ZHITU_TOKEN` environment variable

**Output fields**:
```
p (price), pc (change_pct), ud (change_amount), v (volume),
cje (amount), o (open), h (high), l (low), yc (pre_close),
zf (amplitude), lb (volume_ratio), hs (turnover_rate), pe (pe_ratio),
sjl (pb_ratio), sz (total_mv), lt (circ_mv)
```

**Note**: Zhitu API returns rich realtime data but **does not support historical D/W/M K-line data** —
no `get_kline_data` and no `_fetch_raw_data` (raises `DataFetchError`). It also serves as a
**minute-level K-line fallback** via `/hs/history/{symbol}.{sh|sz}/{period}/{adj}` (period ∈
`5`/`15`/`30`/`60`; adjust ∈ `n`/`f`/`b` for 不复权/前复权/后复权; `period=1` rejected). When
`HISTORICAL_MIN` is the requested capability, Zhitu joins the minute failover chain at
priority 4 (after Baostock P1 / Akshare P2 / Yfinance P3).

**Links**: https://www.zhituapi.com/hsstockapi.html

**Stock list endpoint**: `https://api.zhituapi.com/hs/list/all?token={token}` (P4 last-resort backup in STOCK_LIST failover chain)

- Single HTTP call returns the full A-share list (~5000+ stocks)
- Rate limit: 300/min (包量版), 1000/min (体验版/包月版), per Zhitu docs
- Update frequency: 16:20 daily
- Returns `{"dm": <code>, "mc": <name>, "jys": "sh"|"sz"}` — `jys` is passed through raw to the persistence layer, which normalizes via `_normalize_exchange` (zhitu `sh`/`sz`, myquant `SHSE`/`SZSE`, etc. all map to canonical `"SH"`/`"SZ"`/`"BJ"`).
- Non-A-share markets return `[]` (Zhitu only covers csi).

---

### TencentFetcher (Priority 5, A股+HK, Free)

**API**: `https://qt.gtimg.cn/q={prefix_code}` (HTTP GET, GBK encoding)

**Supports**: A-share + HK realtime quotes with enhanced valuation fields

**Key enhanced fields** (88-field `~` delimited response):
- Index 39: PE(TTM), Index 46: PB, Index 44/45: 总市值/流通市值(亿)
- Index 47/48: 涨停价/跌停价, Index 49: 量比, Index 52: PE(静)

**Note**: Tencent财经 provides enhanced valuation data not available from other providers. Uses `urllib` for GBK response handling.

---

### EastMoneyFetcher (Priority 6, A股, Free)

**Datacenter domain** (datacenter-web.eastmoney.com):
- 龙虎榜: `RPT_DAILYBILLBOARD_DETAILSNEW`, 席位: `RPT_BILLBOARD_DAILYDETAILSBUY/SELL`
- 融资融券: `RPTA_WEB_RZRQ_GGMX`
- 大宗交易: `RPT_DATA_BLOCKTRADE`
- 股东户数: `RPT_HOLDERNUMLATEST`
- 分红送转: `RPT_SHAREBONUS_DET`

**push2 domain** (push2.eastmoney.com / push2his.eastmoney.com):
- 资金流分钟级: `/api/qt/stock/fflow/kline/get?klt=1`
- 资金流120日: `/api/qt/stock/fflow/daykline/get?lmt=120`

**ReportAPI domain** (reportapi.eastmoney.com):
- 研报列表: `/report/list`, PDF: `https://pdf.dfcfw.com/pdf/H3_{info_code}_1.pdf`

**Note**: All domains share a unified `_datacenter_query()` helper. No authentication required.

---

### ThsFetcher (Priority 7, A股, Free)

**热点题材**: `http://zx.10jqka.com.cn/event/api/getharden/`
- Returns daily hot stocks with reason tags (题材归因), zero-auth, ~73ms

**北向资金**: `https://data.hexin.cn/market/hsgtApi/method/dayChart/`
- Minute-level 沪股通/深股通 cumulative net buy data (262 time points per day)

**Note**: No API key required. Simple HTTP GET with User-Agent header.

---

### CninfoFetcher (Priority 8, A股, Free)

**API**: `https://www.cninfo.com.cn/new/hisAnnouncement/query` (HTTP POST)

**Supports**: Full-text announcement search and retrieval for A-share stocks

**orgId format**: `gssh0{code}` (Shanghai), `gssz0{code}` (Shenzhen), `gsbj0{code}` (Beijing)

**Note**: Returns announcement title, type, date, and detail page URL. PDF download not yet implemented.

---

### MyquantFetcher (Priority 9 — last-resort backup, A股 only, Requires Token)

**SDK**: `gm` (pip install gm>=3.0.180,<4) — https://www.myquant.cn/

**Token**: Set via `MYQUANT_TOKEN` environment variable. `is_available()` calls
`gm.api.set_token` on first invocation; if `gm` is unimportable, the fetcher is
skipped at registration. A-share only (no HK/US); no weekly/monthly/1-minute
K-line. Realtime `current_price` is price-only. Implementation details
(field-by-field quirks, pct_chg derivation, defensive A-share filtering, the
gm/pandas dependency warning) live in the `myquant_fetcher.py` module docstring
— not duplicated here.

**Priority 9 is intentional**: it ensures the REALTIME_QUOTE failover chain is
`Tushare → Zhitu/Tencent/Akshare → Myquant` (richer-data first), matching the
"richer source wins" convention used by every other fetcher.

---

### BaiduFetcher (Priority 7, news search backup, A股 only, Requires API Key)

**API**: `POST https://qianfan.baidubce.com/v2/ai_search/web_search`

**Authentication**: `Authorization: Bearer <API Key>` (token read from `BAIDU_API_KEY` env var)

**Supported capability**: `NEWS_SEARCH` only — no K-line / quote / financial data. Functions as backup source when `EastMoneyFetcher.search_news` fails (saves Baidu's 1500/month free quota).

**Request body**:
```json
{
  "messages": [{"content": "query", "role": "user"}],
  "search_source": "baidu_search_v2",
  "resource_type_filter": [{"type": "web", "top_k": 20}],
  "search_recency_filter": "year"
}
```

**Response field**: `references[].{title, url, content, date, type, web_anchor}`

**Pricing**: 1500 calls/month free (released daily), then pay-as-you-go.

**Limitation**: `top_k` hard cap is 50; user-facing `limit` accepts 1..100 but is clamped internally to 50.

**Links**: https://cloud.baidu.com/doc/qianfan-api/s/Wmbq4z7e5

---

## Provider Frequency Support

| Provider | d | w | m | 5m | 15m | 30m | 60m |
|----------|---|---|---|----|----|-----|-----|
| BaostockFetcher | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| AkshareFetcher | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| TushareFetcher | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| YfinanceFetcher | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| ZhituFetcher | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ |

**Fallback**: Server queries providers in priority order. If provider doesn't support the requested frequency, it raises `DataFetchError` and the next provider is tried.

## Capability-Based Routing

Every fetcher declares its capabilities via `supported_data_types: DataCapability`, a `Flag` enum in `base.py`:

```python
class DataCapability(Flag):
    HISTORICAL_DWM   # 日/周/月 K线 (d/w/m)
    HISTORICAL_MIN   # 分钟 K线 (1/5/15/30/60m)
    REALTIME_QUOTE   # 实时报价
    STOCK_LIST       # 股票列表 (get_all_stocks)
    TRADE_CALENDAR   # 交易日历
    STOCK_BOARD      # 板块数据（概念/行业板块列表）
    INDEX_QUOTE      # 指数实时行情
    INDEX_HISTORICAL # 指数历史K线 (d/w/m)
    INDEX_INTRADAY   # 指数日内分时 (1/5/15/30/60m)
    STOCK_ZT_POOL    # 涨跌停股池
    DRAGON_TIGER     # 龙虎榜（个股+全市场）
    MARGIN_TRADING   # 融资融券
    BLOCK_TRADE      # 大宗交易
    HOLDER_NUM       # 股东户数变化
    DIVIDEND         # 分红送转
    FUND_FLOW        # 资金流（个股资金流分钟级+120日）
    HOT_TOPICS       # 热点题材（同花顺当日强势股+题材归因）
    NORTH_FLOW       # 北向资金（沪股通/深股通分钟流向）
    RESEARCH_REPORT  # 研报
    ANNOUNCEMENT     # 公告
```

**Hard rule**: EVERY data access method in `DataFetcherManager` MUST route through
`_filter_by_capability(market, capability)`. Never hardcode a specific fetcher class
(e.g. `AkshareFetcher()`) — that bypasses priority-based failover and is forbidden.
If a new data type needs routing, add a capability flag and declare it on the
fetchers that support it.

`DataFetcherManager._filter_by_capability(market, capability)` filters fetchers by market AND capability flag. Each data method routes through this filter:

| API Method | Capability Used |
|------------|----------------|
| `get_kline_data` (d/w/m, stocks) | `HISTORICAL_DWM` |
| `get_kline_data` (5/15/30/60, stocks) | `HISTORICAL_MIN` |
| `get_kline_data` (d/w/m, indices) | `INDEX_HISTORICAL` (fallback: `HISTORICAL_DWM`) |
| `get_kline_data` (5/15/30/60, indices) | `INDEX_INTRADAY` (fallback: `HISTORICAL_MIN`) |
| `get_realtime_quote` | `REALTIME_QUOTE` |
| `get_intraday_data` | `HISTORICAL_MIN` |
| `get_stock_name` | n/a — handled by `persistence.stock_list` (DB + `STOCK_LIST` fallback) |
| `get_trade_calendar` | `TRADE_CALENDAR` |
| `get_all_concept_boards` / `get_all_industry_boards` | `STOCK_BOARD` |
| `get_concept_board_stocks` / `get_industry_board_stocks` | `STOCK_BOARD` |
| `get_index_realtime_quote` | `INDEX_QUOTE` |
| `get_index_historical` | `INDEX_HISTORICAL` |
| `get_index_intraday` | `INDEX_INTRADAY` |
| `get_zt_pool` | `STOCK_ZT_POOL` |
| `get_dragon_tiger` | `DRAGON_TIGER` |
| `get_margin_trading` | `MARGIN_TRADING` |
| `get_block_trade` | `BLOCK_TRADE` |
| `get_holder_num_change` | `HOLDER_NUM` |
| `get_dividend` | `DIVIDEND` |
| `get_fund_flow_minute` / `get_fund_flow_120d` | `FUND_FLOW` |
| `get_hot_topics` | `HOT_TOPICS` |
| `get_north_flow` | `NORTH_FLOW` |
| `get_reports` | `RESEARCH_REPORT` |
| `get_announcements` | `ANNOUNCEMENT` |
| `get_stock_info` | `STOCK_INFO` |
| `get_indicator_catalog` (no routing needed) | n/a — pure compute |
| `get_history` w/ `?indicators=` (orchestrator) | n/a — `IndicatorService` on top of `HISTORICAL_DWM` |

**Fetcher capability declarations:**

| Fetcher | Capabilities |
|---------|-------------|
| BaiduFetcher | `NEWS_SEARCH` |
| BaostockFetcher | `HISTORICAL_DWM \| HISTORICAL_MIN \| TRADE_CALENDAR \| INDEX_HISTORICAL` |
| AkshareFetcher | `HISTORICAL_DWM \| HISTORICAL_MIN \| REALTIME_QUOTE \| STOCK_LIST \| TRADE_CALENDAR \| STOCK_BOARD \| INDEX_QUOTE \| INDEX_HISTORICAL \| INDEX_INTRADAY \| STOCK_ZT_POOL` |
| TushareFetcher | `HISTORICAL_DWM \| REALTIME_QUOTE \| INDEX_HISTORICAL` |
| MyquantFetcher | `HISTORICAL_DWM \| HISTORICAL_MIN \| REALTIME_QUOTE \| STOCK_LIST \| TRADE_CALENDAR \| INDEX_HISTORICAL \| INDEX_INTRADAY \| STOCK_INFO` |
| YfinanceFetcher | `HISTORICAL_DWM \| HISTORICAL_MIN \| REALTIME_QUOTE \| INDEX_HISTORICAL \| INDEX_QUOTE` |
| ZhituFetcher | `REALTIME_QUOTE \| STOCK_ZT_POOL \| STOCK_INFO \| HISTORICAL_MIN \| STOCK_LIST` |
| TencentFetcher | `REALTIME_QUOTE` (增强字段: PE/PB/市值/涨跌停价) |
| EastMoneyFetcher | `DRAGON_TIGER \| MARGIN_TRADING \| BLOCK_TRADE \| HOLDER_NUM \| DIVIDEND \| FUND_FLOW \| RESEARCH_REPORT` |
| ThsFetcher | `HOT_TOPICS \| NORTH_FLOW` |
| CninfoFetcher | `ANNOUNCEMENT` |

**Index routing design**: Each fetcher that declares an INDEX_* capability must implement the corresponding public method (`get_index_realtime_quote`, `get_index_historical`, `get_index_intraday`). The Manager calls these methods directly — no `hasattr` checks, no fallback to stock methods. Internally, a fetcher may delegate to shared data processing logic (e.g. `get_index_historical` → `get_kline_data`), but the public interface is always the dedicated index method.

**Anti-pattern**: Do NOT use `supports_historical` or `supports_realtime` — these are deprecated. Use `supported_data_types` with `DataCapability` flags.

## Symbol Conventions

| Market | Format | Examples |
|--------|--------|----------|
| A-share (Shanghai) | 6 digits + `.SS` | `600519.SS`, `000001.SZ` |
| A-share (Shenzhen) | 6 digits + `.SZ` | `000001.SZ` |
| HK stocks | `HK` + 5 digits | `HK00700`, `HK01810` |
| US stocks | 1-5 letters | `AAPL`, `TSLA` |
| US indices | Mapped to yfinance | `SPX` → `^GSPC` |

## Key Design Patterns

### Circuit Breaker
Per-source circuit breakers prevent cascading failures:
- CLOSED (normal) → OPEN (after N failures) → HALF_OPEN (probe) → CLOSED (recover)
- Configurable failure threshold and cooldown

### Rate Limiting / Anti-Banning
- Random jitter between requests (1.5-3.0s default)
- Random User-Agent rotation from pool
- Exponential backoff retry on failure

### Indicator Computation
Pure DataFrame transformer at the orchestration boundary:
1. `routes.py` calls `manager.get_kline_data(code, days=max(days, lookback))`
   — `lookback` is the maximum across the requested indicators.
2. The returned DataFrame is handed to `IndicatorService.compute(df, spec)`.
3. The service iterates `INDICATOR_REGISTRY` once per requested indicator,
   calls the corresponding `calc*` function, and merges the per-bar
   result dicts onto the DataFrame as an `indicators` column.
4. `routes.py` then truncates the DataFrame back to the user's `days`
   (the extra lookback was only needed to warm the indicator).

**Index indicators**: `/indices/{code}/history` accepts the same
`?indicators=` query param as `/stocks/{code}/history`. The
orchestrator in `routes.py` handles lookback expansion and truncation
the same way for both endpoints (`_apply_indicators`, `_parse_indicators_param`
are shared). Indices and stocks share the same `KLineData` response
shape — the same conditional serialization applies.

**`ma5`/`ma10`/`ma20` back-compat fields** on `KLineData` are backfilled
from the `ma` indicator's `ma5/ma10/ma20` output columns when the user
requests `?indicators=ma`. When no indicator is requested, the 4 indicator
fields (`ma5`, `ma10`, `ma20`, `indicators`) are **omitted from the JSON
response entirely** by `KLineData._serialize`'s `@model_serializer` —
they are not present as `null`. Contract: clients can rely on "key exists
⇔ indicator was computed".

### Market-Aware Routing
Manager routes requests based on stock code and capability:
- US stocks → YfinanceFetcher (primary), Stooq fallback
- A-shares → BaostockFetcher (primary), AkshareFetcher (fallback)
- Each fetcher declares supported markets via `supported_markets` and capabilities via `supported_data_types: DataCapability`

### Code Normalization
`normalize_stock_code()` handles various input formats:
- `SH600519` → `600519`, `sz000001` → `000001`, `HK00700` → `HK00700`

## Common Commands

> **Always use the project venv.** The `akshare` / `yfinance` / `gm`
> packages are installed in `.venv/`, not the system Python. Running
> `python` (system) will hit `ModuleNotFoundError` for those modules,
> and `AkshareFetcher.is_available()` will return `False`, breaking
> every endpoint that routes through akshare (STOCK_BOARD, STOCK_LIST,
> INDEX_*, ZT_POOL, REALTIME_QUOTE, …). Use `.venv/Scripts/python.exe`
> directly, or `source .venv/Scripts/activate` first.

```bash
# Install dependencies (into the venv)
.venv/Scripts/python.exe -m pip install -e ".[dev]"
#  — or, with the venv activated:  pip install -e ".[dev]"

# Run the server
.venv/Scripts/python.exe -m stock_data.server

# Run tests
.venv/Scripts/python.exe -m pytest

# Run a single test
.venv/Scripts/python.exe -m pytest tests/test_explorer_manifest_endpoint.py -v

# Lint
ruff check .

# Format
ruff format .
```

## API Documentation

Interactive web docs live at `stock_data/explorer/static/index.html` (the
`stock_data/explorer/` subpackage) and are mounted at `/explorer/` when the
server runs. After `python -m stock_data.server`, open
`http://localhost:8888/explorer/`. The page supports Try-it, search,
market/capability filtering, dark theme, and an optional Test Instance
subprocess (controlled from the sidebar).

**Source of truth is server-side**, not the HTML. The page fetches
`GET /control/api-manifest` on load, which is generated by
`explorer/manifest.build_manifest(app)` reflecting `app.routes` + the
`@endpoint_meta` decorator on each route. To add or change an endpoint's
explorer metadata, edit the `@endpoint_meta(...)` call in `api/routes.py` —
the manifest rebuilds on the next request.

The `/control/*` management endpoints live alongside at the same prefix.

## Configuration

Environment variables (see `.env.example`):
- `TUSHARE_TOKEN` - Tushare Pro API token
- `BAOSTOCK_PRIORITY` - Override Baostock fetcher priority (default: 1)
- `AKSHARE_PRIORITY` - Override Akshare fetcher priority (default: 2)
- `YFINANCE_PRIORITY` - Override Yfinance fetcher priority (default: 3)
- `ZHITU_TOKEN` - Zhitu API token for realtime quotes
- `ZHITU_PRIORITY` - Override Zhitu fetcher priority (default: 4)
- `ENABLE_API_CACHE` - Enable/disable API response caching (default: true)
- `STOCK_CACHE_DB_PATH` - Path to the SQLite persistence file (default: `<repo>/stock_data/stock_cache.db`)
- `STOCK_DB_INIT` - Startup hook. `true` → DROP + recreate all persistence tables on boot (full reset for dev/test). `false` → idempotent CREATE IF NOT EXISTS only (default). Any other value is treated as false. **WARNING: `true` wipes all cached metadata.**
- `MYQUANT_TOKEN` - 掘金量化 myquant SDK token (https://www.myquant.cn/)
- `MYQUANT_PRIORITY` - Override Myquant fetcher priority (default: 9 — last-resort backup)
- `MYQUANT_CALENDAR_START_YEAR` - Override the start year for `get_trade_calendar` (default: 2010)
- `TENCENT_PRIORITY` - Override Tencent fetcher priority (default: 5)
- `EASTMONEY_PRIORITY` - Override EastMoney fetcher priority (default: 6)
- `THS_PRIORITY` - Override ThsFetcher priority (default: 7)
- `CNINFO_PRIORITY` - Override Cninfo fetcher priority (default: 8)
- `CACHE_TTL_STOCK_INTRADAY` - Stock intraday cache TTL in seconds (default: 30)
- `CACHE_TTL_INDEX_INTRADAY` - Index intraday cache TTL in seconds (default: 30)
- `CACHE_TTL_STOCK_INFO` - 公司画像缓存 TTL 秒 (default: 3600)

## Anti-Patterns to Avoid

- **Don't** put all code in one file — split fetchers into separate modules
- **Don't** use verbose Hungarian notation like `_stock_name_cache_lock` — use `_lock` on the cache dict itself
- **Don't** mix inline imports and top-level imports inconsistently
- **Don't** add features not needed for core data fetching (defer fundamental data, sentiment, etc.)
- **Don't** create deeply nested manager hierarchies — one `DataFetcherManager` is sufficient
- **Don't** hardcode a specific fetcher class (e.g. `AkshareFetcher()`) in `DataFetcherManager` methods. The Hard rule under *Capability-Based Routing* above is the canonical statement; this list just mirrors it for grep-ability.
- **Don't** cache realtime quote data in SQLite — the `stock_board` and `stock_board_stock` tables store metadata only (code, name, type, timestamps). Quote/price data is always fetched live from the API.
- **Don't** put indicator math inside a `BaseFetcher` or anywhere in the fetcher layer. The fetcher's job is to deliver a clean standardized K-line DataFrame; the indicator service's job is to enrich it.
- **Don't** write `options.get(key) or default` for numeric/float option keys — when `key=0` is a valid value, the `or` treats it as missing. Use `options.get(key, default)` so `0` flows through.
- **Don't** re-introduce inline MA/EMA/WMA calculations in the fetcher path. If you need a moving average on K-line data, ask the indicator service via `?indicators=ma` (or compute it downstream of the API).
- **Don't** reorder decorators on a route so `@endpoint_meta` sits OUTSIDE `@router.get` (i.e. `@endpoint_meta(...) @router.get(...) def f`). The contract requires `@endpoint_meta` to be the INNER decorator so FastAPI captures the same function object that `REGISTRY[f]` was keyed on. Reversing the order silently drops the route from the explorer manifest (a startup warning is logged, but the endpoint still works as an API). The runtime sanity check in `explorer/__init__.py` catches this on boot.
- **Don't** add a `DataCapability` flag without declaring intent — every flag must be in either `CAPABILITY_TO_METHOD` (maps to a fetcher method) or `_NO_FETCHER_METHOD` (explicit "no method"). `tests/test_capability_method_map.py` enforces this; the explorer startup sanity check also warns about violations.
- **Don't** override `@endpoint_meta(fetcher_method=...)` with a method name that doesn't exist on any fetcher class — startup sanity check warns but the manifest will silently produce a misleading Stage 2 entry.
