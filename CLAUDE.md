# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A Python-based local stock data aggregation server that:
- Integrates 12 upstream stock data APIs (Tushare, Baostock, Akshare, Yfinance, Zhitu, Zzshare, Tencent, EastMoney, THS, Cninfo, Myquant, Baidu)
- Normalizes data into a unified format across all capability groups (行情/资金面/基础数据/公告/研报/特殊池/etc.)
- Provides a stable REST API for consumption by AI agents like OpenClaw

## Architecture

Four layers, top-down:

1. **API Layer (FastAPI)** — declarative routes; metadata-driven via `@endpoint_meta`.
2. **IndicatorService (pure compute)** — `MA · MACD · BOLL · KDJ · RSI · WR · BIAS · CCI · ATR · OBV · ROC · DMI · SAR · KC`. Sits on top of the manager; no fetcher involvement. See `data_provider/indicators/` for the full descriptor registry and add-an-indicator conventions.
3. **DataFetcherManager** — capability-routed, priority-based failover + circuit breaker + TTLCache. See `data_provider/manager.py`.
4. **Source Adapters** — `Tushare · Baostock · Akshare · Yfinance · Zhitu · Zzshare · Tencent · EastMoney · Ths · Cninfo · Myquant · Baidu` (12 fetchers; details in each module's docstring).

## Directory Structure

Top-level (full layout — see `ls -R stock_data/` for the complete file list):

- `stock_data/server.py` — FastAPI app entry point.
- `stock_data/api/` — `routes.py` (all `/stocks/...` endpoints), `schemas.py` (Pydantic response models), `cache.py` (TTLCache), `endpoint_meta.py` (`@endpoint_meta` + `REGISTRY`).
- `stock_data/explorer/` — `/explorer/` HTML UI + `/control/*` management router. `mount(app)` is the only entry point; see `__init__.py` for startup sanity checks.
- `stock_data/data_provider/base.py` — `BaseFetcher` ABC, `DataCapability` flag enum, `DataFetchError`.
- `stock_data/data_provider/manager.py` — `DataFetcherManager` (capability routing, circuit breaker, failover).
- `stock_data/data_provider/fetchers/` — one file per data source: `tushare_fetcher.py`, `baostock_fetcher.py`, `akshare/` (package), `yfinance_fetcher.py`, `zhitu_fetcher.py`, `tencent_fetcher.py`, `eastmoney_fetcher.py`, `ths_fetcher.py`, `cninfo_fetcher.py`, `myquant_fetcher.py`, `baidu_fetcher.py`, plus `index_symbols.py` (CSI/HK/US index mappings).
- `stock_data/data_provider/persistence/` — on-disk SQLite layer (replaces legacy `data_provider/cache/`). Sub-modules: `db.py` (shared connection), `stock_list.py`, `board.py`, `trade_calendar.py`, `pool_daily.py` (unified zt/dt/zbgc table).
- `stock_data/data_provider/indicators/` — pure-compute indicator layer. One file per indicator: `ma.py`, `macd.py`, `boll.py`, `kdj.py`, `rsi.py`, `wr.py`, `bias.py`, `cci.py`, `atr.py`, `obv.py`, `roc.py`, `dmi.py`, `sar.py`, `kc.py`. Registry + orchestrator in `registry.py` / `indicator_service.py`.
- `stock_data/data_provider/utils/normalize.py` — code/market normalization.
- `stock_data/data_provider/core/types.py` — `UnifiedRealtimeQuote`, `CircuitBreaker`, `safe_float`/`safe_int`.

## Core Components

### `data_provider/base.py`
- `BaseFetcher`: Abstract base defining `_fetch_raw_data()`, `_normalize_data()`, `get_kline_data()`, `get_realtime_quote()`
- `DataCapability`: Flag enum for fetcher capability declarations (see below)
- `DataFetchError`: Exception class
- `STANDARD_COLUMNS`: Standardized K-line column names

### `data_provider/manager.py`
- `DataFetcherManager`: Orchestrates fetchers with priority-based failover, circuit breakers, and capability-based routing
- All data access methods route through `_filter_by_capability(market, capability)`
- **Board methods** (`get_all_boards`, `get_board_stocks`, `get_stock_boards`, `get_board_history`) use `_with_source()` routing (source-routed, no failover) instead of `_with_failover()`, because different sources have incompatible board classification systems

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
- `board.py`: Board metadata (concept/industry/index/special), source-keyed persistence
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
`indicator_service.py` provide the orchestration layer. See
`data_provider/indicators/__init__.py` for the layer's public surface and
the conventions / anti-patterns that govern adding a new indicator.

## Standardized Data Schema

Full Pydantic response models live in `api/schemas.py` — that is the source of truth.
The non-obvious behaviors worth memorizing here are:

- **`KLineData` conditional serialization** (response of `/stocks/{code}/kline?indicators=...` and `/indices/{code}/kline?indicators=...`): `amount` / `change_percent` are emitted as JSON `null` when missing. The `indicators` field is **omitted from the JSON entirely** when its value is None/empty (via `@model_serializer` on `KLineData._serialize`). Contract: clients can rely on "key exists ⇔ indicator was computed".
- **`KLineData.indicators`** is a per-bar dict populated only when `?indicators=` is set. One entry per output column of the requested indicators (e.g. `{"ma5": 12.34, "macd_dif": 0.23}`). Per-indicator values like `ma5`, `ma10`, `ma20` live inside this dict, not as top-level fields.
- **Index indicators** share the same `KLineData` response shape as stocks — the orchestrator in `routes.py` (`_apply_indicators`, `_parse_indicators_param`) handles lookback expansion and truncation identically.
- **Historical K-line** uses `STANDARD_COLUMNS` (`date, open, high, low, close, volume, amount, pct_chg`).
- **`StockInfo.exchange`** is `"SH"` / `"SZ"` / `"BJ"` when known, else `null` (Zhitu / Myquant populate it; Baostock / Akshare do not).

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
| 板块清单 | 用户传入 `source`; fetcher 名 (fetch 时) | `"persistence"` (缓存命中) |
| 板块成分股 | 用户传入 `source`; fetcher 名 (fetch 时) | `"persistence"` (缓存命中) |
| 涨跌停 / 股票列表 / 交易日历 | fetcher 名 (refresh 时) | `"persistence"` (缓存命中) |

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
| `/boards/{board_code}/stocks` | `STOCK_BOARD` | `get_board_stocks` |
| `/stocks/{stock_code}/boards` | `STOCK_BOARD` | `get_stock_boards` |
| `/boards/{board_code}/history` | `STOCK_BOARD` | `get_board_history` |
| `/dragon-tiger/daily` | `DRAGON_TIGER` | `get_daily_dragon_tiger` |
| `/stocks/{stock_code}/fund-flow/daily` | `FUND_FLOW` | `get_fund_flow_120d` |

**Board endpoints are source-routed**: the `?source=` query parameter selects
the fetcher (e.g. `eastmoney`, `zhitu`). Different sources use incompatible
board classification systems, so failover between sources is intentionally
not supported. The Manager uses `_with_source()` (not `_with_failover()`)
for all board methods.

### Anti-patterns

- **Don't** add a `DataCapability` without putting it in
  `CAPABILITY_TO_METHOD`. Startup sanity checks and
  `tests/test_capability_method_map.py` will flag violations.
- **Don't** assume Stage 2 result is "production-equivalent" — it bypasses
  the manager's circuit breaker and the capability filter.
- **Don't** rely on `/control/fetcher-test` from external networks — it's
  127.0.0.1-only via the control router.

## Provider API Documentation

Each fetcher's module docstring is the **canonical spec** (URL endpoints, request/response fields, units, rate limits, capability set). Read the docstring of the fetcher you're touching before changing its behavior. Per-provider official upstream references are mirrored under `docs/baostock/`, `docs/zhitu/`, `docs/myquant/`.

Compact overview:

| Fetcher | Priority | Markets | Capabilities (in addition to defaults) | Auth |
|---|---|---|---|---|
| `TushareFetcher` | 0 | csi | `STOCK_KLINE`, `STOCK_REALTIME_QUOTE`, `INDEX_KLINE` | `TUSHARE_TOKEN` |
| `BaostockFetcher` | 1 | csi | `STOCK_KLINE`, `TRADE_CALENDAR`, `INDEX_KLINE`, `DIVIDEND` | none |
| `AkshareFetcher` | 3 | csi, hk | `STOCK_KLINE`, `STOCK_REALTIME_QUOTE`, `STOCK_LIST`, `TRADE_CALENDAR`, `INDEX_*`, `STOCK_ZT_POOL` | none |
| `YfinanceFetcher` | 4 | us, csi, hk | `STOCK_KLINE`, `STOCK_REALTIME_QUOTE`, `INDEX_KLINE`, `INDEX_REALTIME_QUOTE` | none |
| `ZhituFetcher` | 5 | csi | `STOCK_REALTIME_QUOTE`, `STOCK_ZT_POOL`, `STOCK_INFO`, `STOCK_KLINE` (minute fallback), `STOCK_LIST` (P5 backup), `STOCK_BOARD`, `DIVIDEND`, `FUND_FLOW`, `HOLDER_NUM`, `INDEX_REALTIME_QUOTE`, `INDEX_KLINE` (d/w/m + 5/15/30/60m, csi only — `INDEX_KLINE` declared 2026-07-06 via `/hz/history/fsjy/<code>.<mkt>/<level>`; see `docs/zhitu/10-indices-api.md`) | `ZHITU_TOKEN` |
| `ZzshareFetcher` | 2 | csi | `STOCK_KLINE`, `STOCK_REALTIME_QUOTE`, `STOCK_LIST`, `TRADE_CALENDAR`, `STOCK_BOARD`, `STOCK_ZT_POOL`, `DRAGON_TIGER`, `HOT_TOPICS`, `STOCK_INFO` | `ZZSHARE_TOKEN` (optional) |
| `TencentFetcher` | 5 | csi, hk | `STOCK_REALTIME_QUOTE` (PE/PB/市值/涨跌停价 增强 — 仅股票; Tencent 未声明 `INDEX_REALTIME_QUOTE`,不进指数 quote 链) | none |
| `EastMoneyFetcher` | 6 | csi | `DRAGON_TIGER`, `MARGIN_TRADING`, `BLOCK_TRADE`, `HOLDER_NUM`, `DIVIDEND`, `FUND_FLOW`, `RESEARCH_REPORT`, `NEWS_FLASH`, `NEWS_SEARCH`, `STOCK_BOARD`, `STOCK_NEWS`, `ANNOUNCEMENT` | none |
| `ThsFetcher` | 7 | csi | `HOT_TOPICS`, `NORTH_FLOW`, `NEWS_FLASH`, `NEWS_SEARCH` (via 问财 iWenCai) | none |
| `BaiduFetcher` | 7 | csi | `NEWS_SEARCH` (backup for EastMoney news) | `BAIDU_API_KEY` |
| `CninfoFetcher` | 8 | csi | `ANNOUNCEMENT` | none |
| `MyquantFetcher` | 9 | csi | `STOCK_KLINE`, `STOCK_REALTIME_QUOTE`, `STOCK_LIST`, `TRADE_CALENDAR`, `INDEX_KLINE`, `STOCK_INFO` (last-resort backup; richer sources win) | `MYQUANT_TOKEN` |

**Default priority is overridable** via `*_PRIORITY` env vars (see [Configuration](#configuration)). The lower the priority number, the earlier the fetcher is tried in the failover chain.

**`BaiduFetcher` (news-search only)**: POST to `https://qianfan.baidubce.com/v2/ai_search/web_search` with `Authorization: Bearer <BAIDU_API_KEY>`. Backup source for `EastMoneyFetcher.search_news`; details (request body schema, `top_k` ≤ 50 cap, 1500/month free quota) in `baidu_fetcher.py`'s docstring.

## Provider Frequency Support

Stock support (per `supports_kline(asset="stock")`):

| Provider | d | w | m | 1m | 5m | 15m | 30m | 60m |
|----------|---|---|---|----|----|-----|-----|-----|
| BaostockFetcher | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ |
| AkshareFetcher | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| TushareFetcher | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| YfinanceFetcher | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ |
| ZhituFetcher | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ |
| ZzshareFetcher | ✅ | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |

Index support (per `supports_kline(asset="index")`; column "mkt" lists supported markets):

| Provider | d | w | m | 1m | 5m | 15m | 30m | 60m | mkt | adjust |
|----------|---|---|---|----|----|-----|-----|-----|-----|--------|
| BaostockFetcher | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | csi | n/a (指数无复权) |
| TushareFetcher | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | csi | n/a |
| AkshareFetcher | ✅ | ✅ | ✅ | ✅¹ | ✅ | ✅ | ✅ | ✅ | csi, hk² | n/a |
| YfinanceFetcher | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | csi, hk, us | 无 hfq(Stage 2 即剔除) |
| ZhituFetcher | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | csi | n/a |
| MyquantFetcher | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | csi | n/a |

¹ Akshare 指数 1m 走 `index_zh_a_hist_min_em`,需单日窗口(start_date=end_date),内部用 `09:30:00 - 15:00:00` 拉单日全部分时。
² Akshare `get_index_historical` 内部只走 Sina/EM A 股 feed(实盘仅 csi),但 `supports_kline` 不剔 hk,所以 hk 指数代码会在 `get_kline_data` 中进入分支后落空。

**Fallback**: Server queries providers in priority order. If provider doesn't support the requested frequency, it raises `DataFetchError` and the next provider is tried.

**Anti-pattern**: Don't assume "1m" works for every market — for **index** 1m, only Akshare (csi, single trading day) is wired up. Yfinance has no 1m interval upstream; Zhitu lacks a 1m endpoint; Baostock / Tushare / Myquant don't serve index minutes at all.

## Capability-Based Routing

Every fetcher declares its capabilities via `supported_data_types: DataCapability` (the `Flag` enum is defined in `data_provider/base.py`).

**Hard rule**: EVERY data access method in `DataFetcherManager` MUST route through
`_filter_by_capability(market, capability)`. Never hardcode a specific fetcher class
(e.g. `AkshareFetcher()`) — that bypasses priority-based failover and is forbidden.
If a new data type needs routing, add a capability flag and declare it on the
fetchers that support it.

`DataFetcherManager._filter_by_capability(market, capability)` filters fetchers by market AND capability flag. Each data method routes through this filter:

| API Method | Capability Used |
|------------|----------------|
| `get_kline_data` (d/w/m, stocks) | `STOCK_KLINE` (ZzshareFetcher P2) |
| `get_kline_data` (5/15/30/60m, stocks) | `STOCK_KLINE` (ZzshareFetcher P2) |
| `get_kline_data` (1m, stocks) | `STOCK_KLINE` (AkshareFetcher P3, no adjust) |
| `get_kline_data` (d/w/m, indices) | `INDEX_KLINE` |
| `get_kline_data` (5/15/30/60m, indices) | `INDEX_KLINE` (MyquantFetcher P9) |
| `get_realtime_quote` | `STOCK_REALTIME_QUOTE` (ZzshareFetcher P2) |
| `get_stock_name` | n/a — handled by `persistence.stock_list` (DB + `STOCK_LIST` fallback) |
| `get_trade_calendar` | `TRADE_CALENDAR` (ZzshareFetcher P2) |
| `get_all_boards` | `STOCK_BOARD` (source-routed, no failover) (ZzshareFetcher P2) |
| `get_board_stocks` | `STOCK_BOARD` (source-routed, no failover) (ZzshareFetcher P2) |
| `get_stock_boards` | `STOCK_BOARD` (source-routed, no failover) (ZzshareFetcher P2) |
| `get_board_history` | `STOCK_BOARD` (source-routed, no failover; eastmoney/ths; `source=zzshare` is aliased to `ths` at the route layer — see board-history note below) |
| `get_index_realtime_quote` | `INDEX_REALTIME_QUOTE` |
| `get_index_historical` | `INDEX_KLINE` |
| `get_kline_data` (index) | `INDEX_KLINE` |
| `get_zt_pool` | `STOCK_ZT_POOL` (ZzshareFetcher P2) |
| `get_dragon_tiger` | `DRAGON_TIGER` (ZzshareFetcher P2) |
| `get_margin_trading` | `MARGIN_TRADING` |
| `get_block_trade` | `BLOCK_TRADE` |
| `get_holder_num_change` | `HOLDER_NUM` |
| `get_dividend` | `DIVIDEND` |
| `get_fund_flow_minute` / `get_fund_flow_120d` | `FUND_FLOW` |
| `get_hot_topics` | `HOT_TOPICS` (ZzshareFetcher P2) |
| `get_north_flow` | `NORTH_FLOW` |
| `get_reports` | `RESEARCH_REPORT` |
| `get_announcements` | `ANNOUNCEMENT` |
| `get_flash_news` | `NEWS_FLASH` (EastMoney P6 → ThsFetcher P7) |
| `search_news` | `NEWS_SEARCH` (EastMoney P6 → ThsFetcher / BaiduFetcher P7) |
| `get_stock_news` | `STOCK_NEWS` (EastMoney P6; np-listapi per-stock feed — `/stocks/{code}/news`) |
| `get_news_content` (URL extractor; no fetcher routing) | n/a — pure utility in `utils/news_extractor.py` |
| `get_stock_info` | `STOCK_INFO` (ZzshareFetcher P2) |
| `get_indicator_catalog` (no routing needed) | n/a — pure compute |
| `get_history` w/ `?indicators=` (orchestrator) | n/a — `IndicatorService` on top of `STOCK_KLINE` |

**Board K-line (`/boards/{board_code}/history`)** — source-routed; `source=zzshare` 在 route 层 alias 到
`ths`(ZzshareFetcher 已不提供 board K-line,详见 `docs/superpowers/plans/2026-07-02-board-kline-eastmoney-ths.md`)。
实现: EastMoneyFetcher (d/w/m + 5/15/30/60m via push2his) + ThsFetcher (d-only, concept/industry)。

**Fetcher capability declarations:**

| Fetcher | Capabilities |
|---------|-------------|
| BaiduFetcher | `NEWS_SEARCH` |
| BaostockFetcher | `STOCK_KLINE \| TRADE_CALENDAR \| INDEX_KLINE` |
| AkshareFetcher | `STOCK_KLINE \| STOCK_REALTIME_QUOTE \| STOCK_LIST \| TRADE_CALENDAR \| INDEX_REALTIME_QUOTE \| INDEX_KLINE \| STOCK_ZT_POOL` |
| TushareFetcher | `STOCK_KLINE \| STOCK_REALTIME_QUOTE \| INDEX_KLINE` |
| MyquantFetcher | `STOCK_KLINE \| STOCK_REALTIME_QUOTE \| STOCK_LIST \| TRADE_CALENDAR \| INDEX_KLINE \| STOCK_INFO` |
| YfinanceFetcher | `STOCK_KLINE \| STOCK_REALTIME_QUOTE \| INDEX_KLINE \| INDEX_REALTIME_QUOTE` |
| ZhituFetcher | `STOCK_REALTIME_QUOTE \| STOCK_ZT_POOL \| STOCK_INFO \| STOCK_KLINE \| STOCK_LIST \| STOCK_BOARD \| DIVIDEND \| FUND_FLOW \| HOLDER_NUM \| INDEX_REALTIME_QUOTE \| INDEX_KLINE` |
| TencentFetcher | `STOCK_REALTIME_QUOTE` (增强字段: PE/PB/市值/涨跌停价 — 仅股票) |
| EastMoneyFetcher | `DRAGON_TIGER \| MARGIN_TRADING \| BLOCK_TRADE \| HOLDER_NUM \| DIVIDEND \| FUND_FLOW \| RESEARCH_REPORT \| NEWS_FLASH \| NEWS_SEARCH \| STOCK_BOARD \| STOCK_NEWS \| ANNOUNCEMENT` |
| ThsFetcher | `HOT_TOPICS \| NORTH_FLOW \| NEWS_FLASH \| NEWS_SEARCH` |
| CninfoFetcher | `ANNOUNCEMENT` |

**Index routing design**: Each fetcher that declares an INDEX_* capability must implement the corresponding public method (`get_index_realtime_quote`, `get_index_historical`, `get_index_intraday`). The Manager calls these methods directly — no `hasattr` checks, no fallback to stock methods. Internally, a fetcher may delegate to shared data processing logic (e.g. `get_index_historical` → `get_kline_data`), but the public interface is always the dedicated index method.

**Anti-pattern**: Do NOT use `supports_historical` or `supports_realtime` — these are deprecated. Use `supported_data_types` with `DataCapability` flags.

**ZhituFetcher index support (added 2026-07-06)**: 智兔指数 API `/hz/` 前缀(`https://www.zhituapi.com/hsindexapi.html`)现已接入 — 文档见 [`docs/zhitu/10-indices-api.md`](docs/zhitu/10-indices-api.md)。`ZhituFetcher.supported_data_types` 已声明 `INDEX_REALTIME_QUOTE | INDEX_KLINE`,manager 现在按以下优先级链路由:

- **指数 quote**: 见上文 Capability-Based Routing 表 — CSI = `Akshare→Yfinance→Zhitu`;HK/US = `Yfinance`(Akshare 内部只查 A 股 feed,Zhitu `supported_markets={csi}` 被自动剔除)。
- **指数 K 线 d/w/m**: `Baostock → Tushare → Akshare → Yfinance → Zhitu → Myquant`
- **指数 K 线 5/15/30/60m**: `Akshare → Yfinance → Zhitu`(Myquant index `supports_kline` 只在 `period == "d"` 时返回 True,非 d 周期被剔除)

实现细节 (`zhitu_fetcher.py` 源码 + memory `zhitu-fetcher-implements-index-api` /
`zhitu-index-000xxx-sh-vs-sz` / `zhitu-upstream-volume-unit-inconsistency`):
volume 单位归一 / market suffix 反转 / `supports_kline` 分流见上。`/indices/{code}/quote`
在上游不返回 name 时 fallback 到 `_resolve_index_name(index_code)`(与 `/kline` 一致)。

**Index K-line dispatch fixes (committed 2026-07-06)**: MyquantFetcher (`myquant_fetcher.py:198-237`) 与
TushareFetcher (`tushare_fetcher.py:169-223`) 都 override `get_kline_data`,`index_market_tag()` 命中时派发到
对应 index API,不再 fall through 到 stock path 哑火。Myquant 同时收紧 `supports_kline` (index 仅 d)。

## Symbol Conventions

| Market | Format | Examples |
|--------|--------|----------|
| A-share (Shanghai) | 6 digits + `.SS` | `600519.SS`, `000001.SZ` |
| A-share (Shenzhen) | 6 digits + `.SZ` | `000001.SZ` |
| HK stocks | `HK` + 5 digits | `HK00700`, `HK01810` |
| US stocks | 1-5 letters | `AAPL`, `TSLA` |
| US indices | Mapped to yfinance | `SPX` → `^GSPC` |

## Key Design Patterns

Cross-cutting behaviors implemented in `data_provider/manager.py` / `data_provider/core/types.py` (one-liners, see source for details):

- **Circuit breaker** — per-source state machine: `CLOSED → OPEN (after N failures) → HALF_OPEN (probe) → CLOSED (recover)`. Threshold and cooldown configurable.
- **Rate limiting / anti-banning** — random 1.5-3.0s jitter, rotating `User-Agent` pool, exponential backoff on retry (via `tenacity`).
- **Market-aware routing** — request market is inferred from the stock code; A-share → Baostock → Akshare failover; US → Yfinance; HK → Akshare / Tencent / Yfinance. See [Capability-Based Routing](#capability-based-routing) for the capability side.
- **Code normalization** — `normalize_stock_code()` accepts `SH600519` / `sz000001` / `HK00700` and returns the canonical 6-digit or `HK`-prefixed form (see `data_provider/utils/normalize.py`).

### Persistence-Only Routing (board endpoints)

**Rule**: Board-related route handlers (`/boards/...`, `/stocks/.../boards`) call into `stock_data.data_provider.persistence.board` (`stock_board_cache.get_*`), **not** `DataFetcherManager` directly. Exceptions: `/control/fetcher-test` is a debug endpoint that intentionally bypasses this rule.

The fetcher API surface (`manager.*`) has exactly two consumers:
1. `persistence/board.py` lazy fill (cold-path single upstream call → upsert)
2. `tools/build_membership_index.py` (full-source bootstrap, per-source worker threads)

Anti-pattern: `manager.get_board_stocks(...)` in `api/routes/boards.py`. Add a new method to `stock_board_cache` instead.

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

**Index indicators**: `/indices/{code}/kline` accepts the same `?indicators=`
query param as `/stocks/{code}/kline` and runs through the same
`_apply_indicators` / `_parse_indicators_param` helpers in `routes.py`.
The `KLineData` response shape and its conditional serialization behavior
are the same as stocks (see [Standardized Data Schema](#standardized-data-schema)).

## Common Commands

> **Always use the project venv.** The `akshare` / `yfinance` / `gm`
> packages are installed in `.venv/`, not the system Python. Running
> `python` (system) will hit `ModuleNotFoundError` for those modules,
> and `AkshareFetcher.is_available()` will return `False`, breaking
> every endpoint that routes through akshare (STOCK_BOARD, STOCK_LIST,
> INDEX_*, ZT_POOL, STOCK_REALTIME_QUOTE, …). Use `.venv/Scripts/python.exe`
> directly, or `source .venv/Scripts/activate` first.

```bash
# Install dependencies (into the venv)
.venv/Scripts/python.exe -m pip install -e ".[dev]"
#  — or, with the venv activated:  pip install -e ".[dev]"

# Run the server
.venv/Scripts/python.exe -m stock_data.server

# Run tests — DEFAULT skips live_network (fast dev loop, ~1 min)
.venv/Scripts/python.exe -m pytest

# Run a single test (markers also skipped unless deselected)
.venv/Scripts/python.exe -m pytest tests/test_explorer_manifest_endpoint.py -v

# Run FULL suite (incl. live_network/requires_token — CI use; 10+ min)
.venv/Scripts/python.exe -m pytest -m ""

# Run only live_network tests
.venv/Scripts/python.exe -m pytest -m live_network

# Run in parallel via pytest-xdist (OPT-IN; not recommended on Windows).
# On this dev box xdist was 21× SLOWER than serial (57 s → 1196 s) because
# each worker boots a fresh Python process and re-imports the entire
# stock_data.server.app tree (akshare, yfinance, gm, baostock, ...). May
# help on Linux CI where process startup is cheaper; benchmark before
# relying on it. Requires explicit `-n auto` — never default.
# .venv/Scripts/python.exe -m pytest -n auto

# Lint
ruff check .

# Format
ruff format .
```

> **Default `pytest` skips `live_network` and `requires_token` tests** (set
> via `addopts = ["-m", "not live_network"]` in `pyproject.toml`). These
> tests hit real upstream APIs and can take 10+ minutes — they're meant
> for CI / pre-release runs, not the dev loop. To run them locally, use
> `pytest -m ""` (clear the default deselect). Tests marked `live_network`
> also auto-downgrade network-class failures to `x` (xfail) via the hook
> in `tests/conftest.py`; see `tests/_network_guard.py` for the legend.

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

`.env.example` is the canonical reference (66 lines, all env vars + comments).
The non-obvious knobs worth memorizing here:

- `STOCK_DB_INIT=true` — **DROPs and recreates** all persistence tables on boot. Use only in dev/test. Any other value is treated as `false` (idempotent `CREATE IF NOT EXISTS`).
- `STOCK_CACHE_DB_PATH` — SQLite persistence file. Default: `<repo>/stock_data/stock_cache.db`.
- `ENABLE_API_CACHE` — toggle the in-memory `TTLCache` layer (default: `true`).
- `*_PRIORITY` env vars — override any fetcher's default priority at startup. The lower the number, the earlier the fetcher is tried.
- `MYQUANT_CALENDAR_START_YEAR` — start year for `get_trade_calendar` (default: `2010`).
- `CACHE_TTL_STOCK_INTRADAY` — minute-line cache TTL in seconds (default: `30`).
- `CACHE_TTL_STOCK_INFO` — 公司画像 (`StockInfoResponse`) cache TTL in seconds (default: `3600`).

## Anti-Patterns to Avoid

- **Don't** put all code in one file — split fetchers into separate modules
- **Don't** use verbose Hungarian notation like `_stock_name_cache_lock` — use `_lock` on the cache dict itself
- **Don't** mix inline imports and top-level imports inconsistently
- **Don't** add features not needed for core data fetching (defer fundamental data, sentiment, etc.)
- **Don't** create deeply nested manager hierarchies — one `DataFetcherManager` is sufficient
- **Don't** hardcode a specific fetcher class (e.g. `AkshareFetcher()`) in `DataFetcherManager` methods. The Hard rule under *Capability-Based Routing* above is the canonical statement; this list just mirrors it for grep-ability.
- **Don't** cache realtime quote data in SQLite — the `stock_board` and `stock_board_membership` tables store metadata only (code, name, type, timestamps). Quote/price data is always fetched live from the API.
- **Don't** put indicator math inside a `BaseFetcher` or anywhere in the fetcher layer. The fetcher's job is to deliver a clean standardized K-line DataFrame; the indicator service's job is to enrich it.
- **Don't** write `options.get(key) or default` for numeric/float option keys — when `key=0` is a valid value, the `or` treats it as missing. Use `options.get(key, default)` so `0` flows through.
- **Don't** re-introduce inline MA/EMA/WMA calculations in the fetcher path. If you need a moving average on K-line data, ask the indicator service via `?indicators=ma` (or compute it downstream of the API).
- **Don't** reorder decorators on a route so `@endpoint_meta` sits OUTSIDE `@router.get` (i.e. `@endpoint_meta(...) @router.get(...) def f`). The contract requires `@endpoint_meta` to be the INNER decorator so FastAPI captures the same function object that `REGISTRY[f]` was keyed on. Reversing the order silently drops the route from the explorer manifest (a startup warning is logged, but the endpoint still works as an API). The runtime sanity check in `explorer/__init__.py` catches this on boot.
- **Don't** add a `DataCapability` flag without declaring intent — every flag must be in `CAPABILITY_TO_METHOD` (maps to a fetcher method). `tests/test_capability_method_map.py` enforces this; the explorer startup sanity check also warns about violations.
- **Don't** override `@endpoint_meta(fetcher_method=...)` with a method name that doesn't exist on any fetcher class — startup sanity check warns but the manifest will silently produce a misleading Stage 2 entry.
- **Don't** leak the outbound `ts_code` / `_to_xxx_ts_code` suffix into an inbound API response. The server's canonical stock_code format is **bare 6-digit** (e.g. `000034`, `600519`), enforced by `normalize_stock_code()`. Per-upstream protocol formats (Tushare `000034.SZ`, Baostock `sh.600519`, Yfinance `600519.SS`, Zhitu `600519.SH`) are an **outbound-only** concern — they live in helpers like `_to_zzshare_ts_code` / `to_tushare_format` / `to_baostock_code` that are called RIGHT BEFORE the SDK call. On the response side, always return the bare 6-digit (e.g. `ts_code.split(".")[0]`). Forgetting the inbound/outbound boundary is exactly how `ZzshareFetcher.get_board_stocks` / `get_daily_dragon_tiger` / `get_hot_topics` ended up returning `000034.SZ` instead of `000034` (fixed 2026-06-25). Same rule applies to HK (`HK00700`) and US (`AAPL`) codes — they keep their canonical form, never get re-suffixed.
- **Don't** let a fetcher reach into a peer fetcher's package internals — even clean imports like `from akshare.datasets import get_ths_js` or `from akshare.utils import demjson` invert the dependency direction between fetchers (they're peers, not a utility layer). If fetcher X needs to vendor an upstream asset (e.g. THS's `ths.js` JS blob), copy it into `stock_data/data_provider/fetchers/<x>_assets/` (a sub-package under X's directory, must have `__init__.py`) and bundle via `[tool.hatch.build.targets.wheel.force-include]` in `pyproject.toml`. Build-time helpers (e.g. `tools/vendor_ths_js.py`) are the only place allowed to touch a peer fetcher's vendored assets to refresh them; server runtime MUST stay peer-decoupled. See [[extend-not-spawn-fetcher]] + [[vendor-not-peer-import]].
- **Don't** invoke any OpenSpec skill in this project (`openspec-explore` / `opsx:explore`, `openspec-propose` / `opsx:propose`, `openspec-apply-change` / `opsx:apply`, `openspec-archive-change` / `opsx:archive`, `openspec-sync-specs` / `opsx:sync`). The project uses Superpowers + CLAUDE.md + `/control/api-manifest` as its spec substrate; OpenSpec is reserved for new projects. See **Skill Discipline** below for scope, rationale, and enforcement.

## Skill Discipline

This project's spec substrate is `CLAUDE.md` + module docstrings + `/control/api-manifest` + pytest fixtures. OpenSpec is **not** in scope here — it is reserved for new projects that start from scratch and need a spec that grows alongside the code.

**Superpowers skills (in scope):** brainstorming, test-driven-development, verification-before-completion, code-review, systematic-debugging, dispatching-parallel-agents, executing-plans, writing-skills, and any other session-internal discipline skill that does not write spec artifacts into the repo.

**OpenSpec skills (blocked — both naming variants):**
- `openspec-explore` / `opsx:explore`
- `openspec-propose` / `opsx:propose`
- `openspec-apply-change` / `opsx:apply`
- `openspec-archive-change` / `opsx:archive`
- `openspec-sync-specs` / `opsx:sync`

**Enforcement (belt + suspenders):**
- **Intent layer (this section)** — every session reads CLAUDE.md and sees the rule, so the model does not try to invoke these skills even when the system reminder lists them as available.
- **Structural layer** — `.claude/settings.json` has a `PreToolUse` hook on the `Skill` tool matcher that exits non-zero when the skill name matches `^openspec-` or `^opsx:`, so the call physically cannot reach the Skill tool. Project-local: new projects are unaffected.

**When the situation feels "perfect for OpenSpec":** stop and reconsider. This project is mature; retro-fitting OpenSpec is high cost and half-applied OpenSpec is worse than no OpenSpec. If a future change genuinely breaks the assumption that CLAUDE.md + manifest + docstring are sufficient (e.g. capability drift across multiple fetchers, or AI-agent-facing contracts that need machine-readable spec), raise it with the user before enabling OpenSpec for that specific change — do not enable it unilaterally.
