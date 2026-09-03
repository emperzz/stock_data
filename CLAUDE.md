# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A Python-based local stock data aggregation server that:
- Integrates 13 upstream stock data APIs (Tushare, Baostock, Akshare, Yfinance, Zhitu, Zzshare, Tencent, EastMoney, THS, Cninfo, Cls, Myquant, Baidu)
- Normalizes data into a unified format across all capability groups (行情/资金面/基础数据/公告/研报/特殊池/etc.)
- Provides a stable REST API for consumption by AI agents like OpenClaw

## Architecture

Four layers, top-down:

1. **API Layer (FastAPI)** — declarative routes; metadata-driven via `@endpoint_meta`.
2. **Indicator compute layer (module functions)** — `MA · MACD · BOLL · KDJ · RSI · WR · BIAS · CCI · ATR · OBV · ROC · DMI · SAR · KC`. Sits on top of the manager; no fetcher involvement. See `data_provider/indicators/` for the full descriptor registry and add-an-indicator conventions.
3. **DataFetcherManager** — capability-routed, priority-based failover + circuit breaker + TTLCache. See `data_provider/manager.py`.
4. **Source Adapters** — `Tushare · Baostock · Akshare · Yfinance · Zhitu · Zzshare · Tencent · EastMoney · Ths · Cninfo · Cls · Myquant · Baidu` (13 fetchers; details in each module's docstring).

## Directory Structure

Top-level (full layout — see `ls -R stock_data/` for the complete file list):

- `stock_data/server.py` — FastAPI app entry point.
- `stock_data/api/` — `routes/` (package: `stocks.py`, `indices.py`, `boards.py`, `data.py`, `news.py`, `calendar.py`, `health.py`, `helpers.py`, `errors.py`), `schemas.py` (Pydantic response models), `cache.py` (TTLCache), `endpoint_meta.py` (`@endpoint_meta` + `REGISTRY`).
- `stock_data/explorer/` — `/explorer/` HTML UI + `/control/*` management router. `mount(app)` is the only entry point; see `__init__.py` for startup sanity checks.
- `stock_data/data_provider/base.py` — `BaseFetcher` ABC, `DataCapability` flag enum, `DataFetchError`.
- `stock_data/data_provider/manager.py` — `DataFetcherManager` (capability routing, circuit breaker, failover).
- `stock_data/data_provider/fetchers/` — one file per data source: `tushare_fetcher.py`, `baostock_fetcher.py`, `akshare/` (package), `yfinance_fetcher.py`, `zhitu_fetcher.py`, `tencent_fetcher.py`, `eastmoney_fetcher.py`, `ths_fetcher.py`, `cninfo_fetcher.py`, `myquant_fetcher.py`, `baidu_fetcher.py`, plus `index_symbols.py` (CSI/HK/US index mappings).
- `stock_data/data_provider/persistence/` — on-disk SQLite layer (replaces legacy `data_provider/cache/`). Sub-modules: `db.py` (shared connection), `stock_list.py`, `board.py`, `trade_calendar.py`, `pool_daily.py` (unified zt/dt/zbgc table).
- `stock_data/data_provider/indicators/` — pure-compute indicator layer. One file per indicator: `ma.py`, `macd.py`, `boll.py`, `kdj.py`, `rsi.py`, `wr.py`, `bias.py`, `cci.py`, `atr.py`, `obv.py`, `roc.py`, `dmi.py`, `sar.py`, `kc.py`. Registry + orchestrator in `registry.py` / `indicator_service.py`.
- `stock_data/data_provider/utils/normalize.py` — code/market normalization.
- `stock_data/data_provider/core/types.py` — `UnifiedRealtimeQuote`, `CircuitBreaker`, `safe_float`/`safe_int`.

## Core Components

Per-file layout is in [Directory Structure](#directory-structure); read the
module docstring for any file's own API. Only the non-obvious contracts are
repeated here.

### `data_provider/base.py`
- `BaseFetcher`: `_normalize_data()` is `@abstractmethod`; `_fetch_raw_data()` defaults to raising `DataFetchError` (K-line fetchers override it). `SDKFetcherMixin` handles Tushare/Baostock/Myquant SDK init.
- `DataCapability` (Flag enum) is how fetchers declare capabilities; `STANDARD_COLUMNS` is the K-line column contract.

### `data_provider/manager.py`
- All data access methods route through `_filter_by_capability(market, capability)`.
- **Board methods** (`get_all_boards`, `get_board_stocks`, `get_stock_boards`, `get_board_history`) use `_with_source()` (source-routed, no failover) instead of `_with_failover()`, because different sources have incompatible board classification systems.

### `data_provider/persistence/`
- `stock_list.py` auto-refreshes on the first call of the day; `pool_daily.py` is ONE table for ZT/DT/ZBGC discriminated by a `pool_type` column; `trade_calendar.py` provides `is_trade_date()` / `get_latest_trade_date_on_or_before()`.

### `data_provider/core/types.py`
- `safe_float()` / `safe_int()` reject NaN / inf / -inf (not just non-numerics) — use them rather than bare `float()`.

### `api/endpoint_meta.py`
Per-route metadata used by the explorer manifest. Each route in `api/routes/`
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
Owns the `/explorer/` HTML UI and `/control/*` endpoints. `explorer.mount(app)`
is the single entry point (mounts static HTML, includes the router, and runs
`_validate_manifest_invariants` at startup — warns about routes missing
`@endpoint_meta` and tags missing from `TAG_TO_TITLE`). `build_manifest(app)`
reflects `app.routes` and is rebuilt on every `/control/api-manifest` request
(no caching — ~5 KB, sub-ms). All `/control/*` routes are tagged `control`
→ excluded from the manifest.

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

- **`KLineData` conditional serialization** (response of `/stocks/{code}/kline?indicators=...` and `/indices/{code}/kline?indicators=...`): `amount` / `change_pct` are emitted as JSON `null` when missing. The `indicators` field is **omitted from the JSON entirely** when its value is None/empty (via `@model_serializer` on `KLineData._serialize`). Contract: clients can rely on "key exists ⇔ indicator was computed".
- **`KLineData.indicators`** is a per-bar dict populated only when `?indicators=` is set. One entry per output column of the requested indicators (e.g. `{"ma5": 12.34, "macd_dif": 0.23}`). Per-indicator values like `ma5`, `ma10`, `ma20` live inside this dict, not as top-level fields.
- **Index indicators** share the same `KLineData` response shape as stocks — the orchestrator in `routes.py` (`_apply_indicators`, `_parse_indicators_param`) handles lookback expansion and truncation identically.
- **`/agent/stocks/batch-profile.boards.data[]`** — 与 `/stocks/{code}/boards` 共享同一份 11 字段 entry 契约 (5 legacy + 7 THS enrichment)。enrichment helper 在 `stock_data/api/_helpers/stock_boards.py::fetch_stock_boards_quote_enrichment`,60s in-process TTLCache (`_stock_boards_quote_cache`,shared with boards route)。`boards.source` 三态: `"persistence"` (warm-cache merge) / `"ths"` (cold-cache fallback) / `"persistence"` (fetcher 失败, enrichment 字段全 None)。`ok` flag 在 fetcher 失败时不变 `True`(仅 persistence 异常才 append `boards` aspect error)。
- **Historical K-line** uses `STANDARD_COLUMNS` (`date, open, high, low, close, volume, amount, pct_chg`).
- **`StockInfo.exchange`** is `"SH"` / `"SZ"` / `"BJ"` when known, else `null` (Zhitu / Myquant populate it; Baostock / Akshare do not).
- **`BoardStocksResponse.effective_source`** (post-2026-07-10): always populated to the fetcher slug that actually served the upstream call (`ths` / `zzshare` / `eastmoney` / `zhitu`). Compare against `query_source` (the user's `?source=`) to detect whether the internal ZZSHARE primary + THS fallback chain fired for `?source=ths&include_quote=false` (see "Board Cache Source-Normalization" below).
- **`/stocks/{code}/{kline,quote}` 400 contract (post-2026-07-23)** — `_reject_invalid_stock_code` (`api/routes/helpers.py`) raises 400 with `{"error":"invalid_request", ...}` and a message that branches on `is_index_code(code)`:
  - `True` (code in `CSI_INDEX_MAP`, e.g. `000001`, `000300`): `"Index {code} is not supported via this endpoint. Use /indices/{code}/{kline,quote} instead."` — caller likely wanted the index endpoint; the redirect hint points there.
  - `False` (typo / delisted / unsupported market tag): `"Stock code {code} was not found in the stock list."` — genuine not-found; no redirect.
  Both branches live in the same helper; tests in `tests/test_routes.py::TestKline` (`test_kline_invalid_stock`, `test_kline_index_coded_input_redirects_message`, `test_kline_unknown_code_gets_not_found_message`) pin the exact wording.

## Source Tracking

响应的 `source: str` 字段 (optional, `default=""`) 取值三类: **fetcher 名**
(实时拉取 / TTLCache 命中时保留写入时的 fetcher)、**`"persistence"`**
(SQLite 持久化层读取)、**缺失** (composite 聚合端点如
`/agent/correlation/matrix` · `/agent/*/batch-profile` · `/agent/market-context` · `/agent/market-recap`
—— 由多 fetcher 拼装,无单一 serving fetcher 可署名)。

Per-endpoint 覆盖矩阵: `docs/source-tracking.md`。

## Stage 1/2 Fetcher Drill-down (Explorer)

`/explorer/` lists, per endpoint, every fetcher that can serve it plus a
`Test` button posting to `POST /control/fetcher-test` (invokes the fetcher
method directly, bypassing manager failover). Manifest `fetchers[]` field,
request/response shape, error classification, and the ZhituFetcher
per-fetcher method override: `docs/explorer-fetcher-drilldown.md`.

### `fetcher_method` overrides

`@endpoint_meta(fetcher_method=...)` pins the method when the capability's
default isn't right:

| Endpoint | Capability | Override method |
|----------|------------|-----------------|
| `/boards/{board_code}/stocks` | `STOCK_BOARD` | `get_board_stocks` |
| `/stocks/{stock_code}/boards` | `STOCK_BOARD` | `get_stock_boards` |
| `/boards/{board_code}/history` | `STOCK_BOARD` | `get_board_history` |
| `/boards/{board_code}/quote` | `STOCK_BOARD` | `get_board_realtime` |
| `/dragon-tiger` | `DRAGON_TIGER` | `get_daily_dragon_tiger` |
| `/stocks/{stock_code}/fund-flow/daily` | `FUND_FLOW` | `get_fund_flow_120d` |

**Board endpoints are source-routed**: `?source=` selects the fetcher;
different sources use incompatible board classification systems, so the
Manager uses `_with_source()` (not `_with_failover()`) — no failover.

### Anti-patterns

- **Don't** add a `DataCapability` without putting it in
  `CAPABILITY_TO_METHOD`. Startup sanity checks and
  `tests/test_capability_method_map.py` will flag violations.
- **Don't** assume Stage 2 result is "production-equivalent" — it bypasses
  the manager's circuit breaker and the capability filter.
- **Don't** rely on `/control/fetcher-test` from external networks — it's
  127.0.0.1-only via the control router.

## Fetcher & Capability Routing

Each fetcher's module docstring is the **canonical spec** (URL endpoints, request/response fields, units, rate limits). Per-provider official upstream references are mirrored under `docs/baostock/`, `docs/zhitu/`, `docs/myquant/`.

Every fetcher declares its capabilities via `supported_data_types: DataCapability` (the `Flag` enum is defined in `data_provider/base.py`).

**Hard rule**: EVERY data access method in `DataFetcherManager` MUST route through
`_filter_by_capability(market, capability)`. Never hardcode a specific fetcher class
(e.g. `AkshareFetcher()`) — that bypasses priority-based failover and is forbidden.

**Anti-pattern**: Do NOT use `supports_historical` or `supports_realtime` — these are deprecated. Use `supported_data_types` with `DataCapability` flags.

### Fetcher overview

| Fetcher | P | Markets | Capabilities | Auth | Notes |
|---|---|---|---|---|---|
| `TushareFetcher` | 0 | csi | `STOCK_KLINE` `STOCK_REALTIME_QUOTE` `INDEX_KLINE` | `TUSHARE_TOKEN` | |
| `BaostockFetcher` | 1 | csi | `STOCK_KLINE` `INDEX_KLINE` `DIVIDEND` | none | |
| `ZzshareFetcher` | 2 | csi | `STOCK_KLINE` `STOCK_REALTIME_QUOTE` `STOCK_LIST` `TRADE_CALENDAR` `STOCK_BOARD` `STOCK_ZT_REASON` `DRAGON_TIGER` `HOT_TOPICS` | `ZZSHARE_TOKEN` (optional) | Board endpoints: not a public source label (unified under `ths`). `STOCK_INFO` removed 2026-07-14 — zzshare `/v3/open/stock/info` returns null for every A-share. `STOCK_ZT_POOL` removed 2026-09-03 — Zzshare no longer serves `/zt-pools`; the upstream `review_uplimit_reason` is exposed via dedicated capability `STOCK_ZT_REASON` + `/api/v1/zt-reasons` (only provider). `get_realtime_quotes(csi) via rt_k(ts_code='60*.SH,68*.SH,0*.SZ,3*.SZ,9*.BJ', fields='all')` (single call; rate-limited 20/min). |
| `AkshareFetcher` | 3 | csi, hk | `STOCK_KLINE` `STOCK_REALTIME_QUOTE` `STOCK_LIST` `TRADE_CALENDAR` `INDEX_REALTIME_QUOTE` `INDEX_KLINE` `STOCK_ZT_POOL` | none | `get_realtime_quotes(csi) via ak.stock_zh_a_spot_em()` (single call). |
| `YfinanceFetcher` | 4 | us, csi, hk | `STOCK_KLINE` `STOCK_REALTIME_QUOTE` `INDEX_KLINE` `INDEX_REALTIME_QUOTE` | none | |
| `ZhituFetcher` | 5 | csi | `STOCK_REALTIME_QUOTE` `STOCK_ZT_POOL` `STOCK_INFO` `STOCK_KLINE` (minute fallback) `STOCK_LIST` `STOCK_BOARD` `DIVIDEND` `FUND_FLOW` `HOLDER_NUM` `INDEX_REALTIME_QUOTE` `INDEX_KLINE` | `ZHITU_TOKEN` | Index K-line via `/hz/` prefix |
| `TencentFetcher` | 5 | csi, hk | `STOCK_REALTIME_QUOTE` (PE/PB/市值/涨跌停价 增强) | none | |
| `EastMoneyFetcher` | 6 | csi | `DRAGON_TIGER` `MARGIN_TRADING` `BLOCK_TRADE` `HOLDER_NUM` `DIVIDEND` `FUND_FLOW` `RESEARCH_REPORT` `NEWS_FLASH` `NEWS_SEARCH` `STOCK_BOARD` `STOCK_NEWS` `ANNOUNCEMENT` | none | |
| `ThsFetcher` | 7 | csi | `HOT_TOPICS` `NORTH_FLOW` `NEWS_FLASH` `NEWS_SEARCH` `STOCK_BOARD` `STOCK_NEWS` `ANNOUNCEMENT` | none | Board K-line d/w/m/1m/5m/15m/30m/60m; `get_board_stocks` supports sort_by + top_n |
| `BaiduFetcher` | 7 | csi | `NEWS_SEARCH` | `BAIDU_API_KEY` | Backup for EastMoney news |
| `CninfoFetcher` | 8 | csi | `ANNOUNCEMENT` | none | |
| `ClsFetcher` | 8 | csi | `MORNING_BRIEFING` `MARKET_RECAP` | none | 财联社早报 + 焦点复盘 via Next.js `__NEXT_DATA__` JSON; 20-28 day window (no upstream pagination) |
| `MyquantFetcher` | 9 | csi | `STOCK_KLINE` `STOCK_REALTIME_QUOTE` `STOCK_LIST` `TRADE_CALENDAR` `INDEX_KLINE` `STOCK_INFO` | `MYQUANT_TOKEN` | Last-resort backup |

**Default priority is overridable** via `*_PRIORITY` env vars (see [Configuration](#configuration)). The lower the priority number, the earlier the fetcher is tried in the failover chain.

### API → Capability routing

`DataFetcherManager._filter_by_capability(market, capability)` filters fetchers by market AND capability flag. Board methods use `_with_source()` (source-routed, no failover) instead of `_with_failover()`.

| API Method | Capability | Notes |
|---|---|---|
| `get_kline_data` (d/w/m) | `STOCK_KLINE` | ZzshareFetcher P2 primary |
| `get_kline_data` (5/15/30/60m) | `STOCK_KLINE` | ZzshareFetcher P2 primary |
| `get_kline_data` (1m) | `STOCK_KLINE` | AkshareFetcher P3, no adjust |
| `get_kline_data` (index d/w/m) | `INDEX_KLINE` | Baostock→Tushare→Akshare→Yfinance→Zhitu→Myquant |
| `get_kline_data` (index 5/15/30/60m) | `INDEX_KLINE` | Akshare→Yfinance→Zhitu |
| `get_realtime_quote` | `STOCK_REALTIME_QUOTE` | ZzshareFetcher P2 primary |
| `get_index_realtime_quote` | `INDEX_REALTIME_QUOTE` | CSI: Akshare→Yfinance→Zhitu; HK/US: Yfinance |
| `get_stock_name` | n/a | `persistence.stock_list` (DB + `STOCK_LIST` fallback) |
| `get_trade_calendar` | `TRADE_CALENDAR` | ZzshareFetcher P2 primary |
| `get_zt_pool` | `STOCK_ZT_POOL` | AkshareFetcher P3 primary — Zzshare removed 2026-09-03 (see Task #3); falls through to ZhituFetcher P5 |
| `get_zt_reason` | `STOCK_ZT_REASON` | ZzshareFetcher P2 primary — only provider; powers `/api/v1/zt-reasons` (added 2026-09-03) |
| `get_dragon_tiger` (per-stock + daily) | `DRAGON_TIGER` | ZzshareFetcher P2 primary; **empty result is a soft failure, fall through to EastMoney** (`empty_is_failure=True`, see [Dragon-Tiger empty-fall-through](#dragon-tiger-empty-fall-through)) |
| `get_margin_trading` | `MARGIN_TRADING` | |
| `get_block_trade` | `BLOCK_TRADE` | |
| `get_holder_num_change` | `HOLDER_NUM` | |
| `get_dividend` | `DIVIDEND` | |
| `get_fund_flow_*` | `FUND_FLOW` | |
| `get_hot_topics` | `HOT_TOPICS` | ZzshareFetcher P2 primary |
| `get_north_flow` | `NORTH_FLOW` | |
| `get_reports` / `get_report_pdf` | `RESEARCH_REPORT` | |
| `get_announcements` | `ANNOUNCEMENT` | |
| `fetch_flash_news` | `NEWS_FLASH` | EastMoney P6 → ThsFetcher P7 |
| `search_news` | `NEWS_SEARCH` | EastMoney P6 → ThsFetcher / BaiduFetcher P7 |
| `get_stock_news` | `STOCK_NEWS` | EastMoney P6 sole provider |
| `get_stock_info` | `STOCK_INFO` | Zhitu P5 → Myquant P9 (Zzshare removed 2026-07-14 — upstream endpoint returns null) |
| `get_news_content` | n/a | Pure utility in `utils/news_extractor.py` |
| `get_indicator_catalog` | n/a | Pure compute |
| `get_history` w/ `?indicators=` | n/a | `indicator_service.compute()` on top of `STOCK_KLINE` |
| `get_morning_briefing(date)` | `MORNING_BRIEFING` | ClsFetcher primary; ?date=YYYY-MM-DD; 20-28 day window; 404 on no article |
| `get_market_recap(date)` | `MARKET_RECAP` | ClsFetcher primary; ?date=YYYY-MM-DD; 20-28 day window; 404 on no article |

**Board endpoints** (source-routed, `_with_source()`, no failover):

| API Method | Valid sources | Notes |
|---|---|---|
| `get_all_boards` | `ths` `eastmoney` `zhitu` | `zzshare` unified under `ths` |
| `get_board_stocks` | `ths` `eastmoney` `zhitu` | `zzshare` returns 422. `source=ths` + `include_quote=False` → ZZSHARE primary + THS fallback; `effective_source` exposes which served. |
| `get_stock_boards` | `ths` `eastmoney` `zhitu` | `zzshare` aliased to `ths` |
| `get_board_history` | `ths` (d/w/m/1m/5m/15m/30m/60m) `eastmoney` (d/w/m/5m/15m/30m/60m) | `zzshare` aliased to `ths`; `board_type` auto-detected from cache for `ths` (pass platecode); 800-day cap |
| `get_board_realtime` | `ths` | Board realtime quote via q.10jqka |

### Index routing notes

Each fetcher that declares an INDEX_* capability must implement the corresponding public method (`get_index_realtime_quote`, `get_index_historical`). The Manager calls these methods directly — no `hasattr` checks, no fallback to stock methods. MyquantFetcher and TushareFetcher override `get_kline_data` to dispatch to their index API when `index_market_tag()` matches.

## Dragon-Tiger empty-fall-through

`/api/v1/dragon-tiger` + `/stocks/{code}/dragon-tiger` pass
`empty_is_failure=True` to `_with_failover`: a *structurally empty* Zzshare
(P2) result is a soft failure that falls through to EastMoney (P6), and
both-empty raises `DataFetchError` rather than returning a misleading 200.
This flag is enabled ONLY for these two methods.

Rationale, the `_is_empty_dict()` emptiness rules, and the exact empty
shapes: `docs/dragon-tiger-fallthrough.md`. Pinned by
`tests/test_dragon_tiger_zzshare_short_circuit.py`.

## Symbol Conventions

**Canonical format** (server-side): bare 6-digit for A-share (`600519`), `HK` + 5 digits for HK (`HK00700`), 1-5 letters for US (`AAPL`). `normalize_stock_code()` handles all input variants.

| Market | API path format | Outbound SDK examples |
|--------|----------------|----------------------|
| A-share | `600519` | Tushare `600519.SS`, Baostock `sh.600519`, Yfinance `600519.SS` |
| HK | `HK00700` | Yfinance `0700.HK` |
| US | `AAPL` | Yfinance `AAPL` |
| CSI indices | `000300` | Zhitu `000300.SH` |
| US indices | `SPX` | Yfinance `^GSPC` |

## Key Design Patterns

Cross-cutting behaviors implemented in `data_provider/manager.py` / `data_provider/core/types.py` (one-liners, see source for details):

- **Circuit breaker** — per-source state machine: `CLOSED → OPEN (after N failures) → HALF_OPEN (probe) → CLOSED (recover)`. Threshold and cooldown configurable.
- **Rate limiting / anti-banning** — **partial, not uniform.** `utils/http.py::json_get` (Zhitu / Baidu / Cninfo / part of THS) rotates a 4-UA pool; EastMoney uses `curl_cffi` fingerprinting + 1-2s delay on the board clist path; SDK-driven fetchers (Tushare / Baostock / Myquant / Akshare) inherit the SDK's limiter and expose no UA control; **THS uses raw `requests.get` with one static UA and no jitter — the weakest link under high-frequency single-IP use.** A unified jitter + UA pool is the target, not the state (see [[optimization-plan-2026-07-16]] P2-4 / P3-a). `tenacity` backoff wraps each fetcher's `_http_get` / `json_get`.
- **Market-aware routing** — request market is inferred from the stock code; A-share → Baostock → Akshare failover; US → Yfinance; HK → Akshare / Tencent / Yfinance. See [Fetcher & Capability Routing](#fetcher--capability-routing) for the capability side.
- **Code normalization** — `normalize_stock_code()` accepts `SH600519` / `sz000001` / `HK00700` and returns the canonical 6-digit or `HK`-prefixed form (see `data_provider/utils/normalize.py`).

### Persistence-Only Routing (board endpoints)

**Rule**: Board-related route handlers (`/boards/...`, `/stocks/.../boards`) call into `stock_data.data_provider.persistence.board` (`stock_board_cache.get_*`), **not** `DataFetcherManager` directly. Exceptions: `/control/fetcher-test` is a debug endpoint that intentionally bypasses this rule.

The fetcher API surface (`manager.*`) has exactly two consumers:
1. `persistence/board.py` lazy fill (cold-path single upstream call → upsert)
2. `tools/build_membership_index.py` (full-source bootstrap, per-source worker threads)

The reverse direction (persistence ← manager lazy-imports, five fetchers
reaching into persistence for lookup helpers) also exists and matters only
when swapping the SQLite backend — sites listed in `docs/board-source-semantics.md`.

Anti-pattern: `manager.get_board_stocks(...)` in `api/routes/boards.py`. Add a new method to `stock_board_cache` instead.

### Board response source fields — read `effective_source`

`/boards/{code}/stocks` carries three source fields: `query_source` (the
user's `?source=`), `data_source` (`'persistence'` on cache hit, else the
requested slug), and **`effective_source`** (the fetcher that actually
served). **`data_source` is NOT the user's fetcher choice** — the cache is
keyed on `source='ths'` regardless of who served, and `source='ths'` +
`include_quote=false` runs an internal ZZSHARE-primary/THS-fallback chain.
Compare `effective_source` vs `query_source` to detect fallback.

Board endpoints route through `_with_source`, which is **not**
CircuitBreaker-integrated — THS board outages surface as 5xx rate, never as
CB state changes.

Full semantics (cache-key normalization, cache-hit caveat, fallback side
effects, persistence↔manager coupling sites): `docs/board-source-semantics.md`.

### Indicator Computation
Pure DataFrame transformer at the orchestration boundary:
1. `routes.py` calls `manager.get_kline_data(code, days=max(days, lookback))`
   — `lookback` is the maximum across the requested indicators.
2. The returned DataFrame is handed to `indicator_service.compute(df, spec)`.
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

## K-line today's partial bar

K 线 routes (`/stocks/{code}/kline` + `/indices/{code}/kline`) 默认在以下条件全部满足时合并今日 partial bar：

1. `frequency ∈ {"d", "w", "m"}`（minute 频段不触发——单点 tick 不能混入聚合 bar）
2. `end_date`（显式或默认）包含今天
3. 今天在 A 股交易日历中（`is_trade_date(today)` 为 True）
4. K 线响应末根日期 ≠ 今天

合并 source：`manager.get_realtime_quote(code)` (stock) 或 `manager.get_index_realtime_quote(code)` (index)，best-effort，失败时回退到原 K 线。今日 partial bar **不**带 `?indicators=` 计算结果（指标只对已收盘数据计算）。详见 `docs/kline-today-bar-merge-spec-2026-07-24.md`。

**时区假设**：server 跑在 CST（Asia/Shanghai）；非 CST 环境下 `date.today()` 与 A 股交易日可能错位（晚 8h 才跨日）。

## Agent Batch API (`/api/v1/agent/*`)

All endpoints under `/api/v1/agent/*` live in `stock_data/api/routes/agent.py`. They are server-side aggregations designed to replace the LLM agent's typical N+1 fetch + manual set-arithmetic pattern.

### Routes

| Route | Purpose | Internal call |
|---|---|---|
| `POST /agent/boards/stock-overlap` | Pairwise stock-set intersection + Jaccard across 2-10 boards. | per-code `stock_board_cache.get_board_stocks(source='ths', include_quote=False)` |
| `POST /agent/stocks/board-overlap` | Pairwise board-set intersection + Jaccard across 2-10 stocks. | per-code `stock_board_cache.get_stock_memberships(sources=['ths'])` |
| `POST /agent/boards/filter-stocks` | Server-side numeric filter (turnover / change_pct / amount / mcap / max_gain_pct) on a board's constituents. | `stock_board_cache.get_board_stocks(source=<user>, include_quote=True, top_n=payload.limit or 50)` |
| `POST /agent/correlation/matrix` | Pairwise Pearson + Spearman matrix across stocks and boards; supports d/w/m/1-60m frequencies. | `manager.get_kline_data` + `manager.get_board_history` per asset, then inner-join + `pct_change(fill_method=None)` |
| `GET /agent/market-stats` | 全市场涨幅统计（个股 + 板块；均值/中位/最高/最低/上涨下跌家数 + 桶形数据）。 | `manager.get_realtime_quotes('csi')` + `stock_board_cache.get_board_list(board_type=None, source='ths', include_quote=True, manager=manager)`; 60s TTLCache via `get_quote_cache`; per-block 错误隔离。 |
| `GET /agent/indices/batch-profile` | Per-index fan-out: 极简 quote + 单 frequency 计算特征 (`trend`/`pivots`/`volume`)。1-5 codes, 默认 3 核心 CSI 指数。 | per-code `manager.get_index_realtime_quote` + `manager.get_kline_data(asset="index", adjust=None)`, then `features.build_features()` |
| `POST /agent/stocks/batch-profile` | Per-stock fan-out: quote + 计算特征 + info + boards。1-5 codes, 单 frequency。boards 块带 7 个 THS enrichment 字段 (change_pct/up_count/down_count/limit_up_count/limit_down_count/explain/relevance),与 `/stocks/{code}/boards` 共享 60s `_stock_boards_quote_cache`。 | per-code `manager.get_realtime_quote` + `manager.get_kline_data(adjust="qfq")` + `manager.get_stock_info` + `stock_board_cache`, then `features.build_features()` |
| `POST /agent/boards/batch-profile` | Per-board fan-out: 极简 realtime quote + 单 frequency 计算特征 (`trend`/`pivots`/`volume`)。1-5 THS platecodes, 单 frequency, 单源 THS。 | per-code `manager.get_board_realtime` + `manager.get_board_history` (THS 单源, fetcher 自动推断 board_type), then `features.build_features()` |
| `GET /agent/market-context` | 每日消息面快照（slim contract post-2026-09-02）：早报 + 复盘 + 快讯。涨跌停池 zt/dt 已迁出到 `agent/market-stats.limit_pools`;龙虎榜按需走 `/api/v1/dragon-tiger`。 | 多 fetcher 组合;`market_session` 由本地 CST + `is_trade_date()` 推得;per-block 错误隔离;缓存键 3-segment `(flash_limit, trade_date)`(slim 后 session 不再入键) |
| `GET /agent/market-recap` | 一站式复盘端点:`market-context` (messages) + `market-stats` (stocks/boards/pools) + 3 指数 quote (上证 / 深成指 / 创业板) 的服务端聚合。复盘 skill `skills/market-recap.md` 工作流的唯一推荐取数入口;**无 `trade_date` query 参数**(服务端固定解析为 ≤ today 的最新交易日)。 | per-block 错误隔离 (5 blocks);`asyncio.gather` 扇出 + sync helpers 走 `asyncio.to_thread`;3 指数内部顺序(manager 单例 + circuit breaker 不可重入);60s TTLCache via `get_quote_cache`;`?format=md` 渲染 14 列指数表 + context/stats verbatim |

- **Extended `MinimalQuote` (post-2026-08-28).** The `quote` block on
  `/agent/{stocks,indices,boards}/batch-profile` is no longer a 2-field
  anchor (`price` + `change_pct`). It's now a ~23-field `MinimalQuote`
  covering OHLV + 量价 (turnover/amplitude/volume_ratio) + 估值
  (PE/PB/mcap_yi/float_mcap_yi, stock-only) + 涨跌停价 (stock-only) +
  板块统计 (up_count/down_count/net_inflow/rank, board-only). Unit
  conventions match the rest of the server's public API surface:
  `volume` raw + `volume_unit` (`"share"` for stock/index, `"wan_shou"`
  for board, matching `KLineData.volume_unit`); `amount` unified to
  元 (board upstream 亿元 ×1e8 — same conversion `/boards/{code}/quote`
  applies at `routes/boards.py:857`). See
  `docs/superpowers/specs/2026-08-28-agent-batch-profile-quote-fields-design.md`
  for the full field inventory and unit policy.

### Design contract (don't violate these without a spec change)

- **Per-item error isolation.** A single upstream failure is reported in `errors[]`; the rest of the response is still emitted. Do not abort the whole response on first failure.
- **No LLM judgment.** These endpoints emit *only* numeric / set-arithmetic facts. "Which stock is the leader" / "Which board is the better pick" stays in `market-principles`, not here.
- **`@endpoint_meta(capabilities=[])`** — these endpoints don't map to a single `DataCapability` flag; leave the list empty.
- **Cache key is `(payload-hash, label)`.** The label is the user-facing route name (`agent_boards_stock_overlap` / `agent_stocks_board_overlap` / `agent_filter_stocks`). Keys reuse `get_quote_cache` as a generic 60s TTLCache slot; this is the documented layering exception to "don't reuse quote cache for non-quote data" — if a future change introduces a dedicated `agent_cache`, the `make_*_cache_key` signatures stay stable.
- **`filter-stocks` cache key MUST include `limit`.** `limit` is forwarded to the upstream `get_board_stocks(..., top_n=limit)`, so two requests with identical board/source/filters but different `limit` MUST use different cache entries. `make_filter_stocks_cache_key(board_code, source, filters, limit)` hashes `{filters, limit}` together. Do not remove `limit` from the signature; do not cache the *post-truncation* `matched_stocks` (upstream is already size-bounded, so a "cache full + truncate at response" optimization is not worth the cache-stale risk).
- **Default `top_n` when `limit` is omitted is 50** — matches the historical `stock_board_cache.get_board_stocks` default and keeps the response within THS's hard cap (5 pages × 10 rows).
- **422 on cid_unresolved.** `post_filter_stocks` calls the persistence helper which can return `reason='cid_unresolved'` when the THS platecode→cid index is cold; the route MUST translate that into a 422 (not a 200 with empty `matched_stocks`). Pinned by `tests/test_agent_endpoints.py::test_cid_unresolved_returns_422`. The shared `fetch_board_stocks_with_zzshare_fallback` helper handles this for `/boards/{code}/stocks` already; agent reuses the same path.
- **No agent-level composite cache (`correlation/matrix`).** Unlike the other agent routes, this endpoint deliberately relies on inner fetcher-level TTLs (`CACHE_TTL_STOCK_KLINE`, `manager.get_board_history` caching, persistence board cache). The composite-cache contract in CLAUDE.md exists to hide N+1 fetch latency; for N=2..10 within the inner TTL window, the inner caches already solve the problem without an additional layer. Tracked as a deliberate deviation; revert by adding `cached_lookup` / `cached_store` around the handler if cold-path latency becomes a complaint.
- **`?format=md` MUST NOT drop a field the JSON carries.** The contract is stated in `api-reference.md` ("No data is dropped — every JSON field appears in the MD output") and is pinned from two sides: `tests/test_agent_endpoints.py::TestFormatMdDataCompleteness` (overlap + market-context) and `tests/test_agent_batch_features.py::TestFormatMdFeatureCompleteness` (the batch-profile feature blocks). When adding a field to a response model, add it to the MD renderer in the SAME change. Two real regressions came from skipping this: `pivots.params` (which pins the ZigZag settings the swings were computed under — swings are uncalibratable without it) and `z_anomalies.open/high/low` (close alone can't separate a 放量长上影 from a 光头阳线, and `direction` is itself derived from `open`).
- **An empty feature block MUST render an explicit no-data marker, never a bare table skeleton.** `features.build_features()` returns `{"trend": {}, "pivots": {}, "volume": {}}` for a 0-bar DataFrame **without raising**, so `errors` stays `null` and the marker is the only signal the agent gets. `_render_dict_block` emits `（无数据）`; the hand-written swings table emits `（无确认摆动点）`. A heading followed by `| 字段 | 值 |` + separator + zero rows reads as "computed, but blank" — the opposite of the truth.
- **No composite cache on any batch-profile endpoint.** `stocks` / `indices` / `boards` batch-profile all rely on fetcher-level TTLs (`get_quote_cache` + `get_history_cache`) for N+1 fan-out (spec §5). The earlier `cached_lookup` / `cached_store` composite layer on stocks / indices was removed 2026-08-28 alongside the boards/batch-profile PR — it added a 60s-stale risk on intraday data without measurably reducing latency (the underlying fetcher caches already serve repeated requests with the same `(frequency, days)` shape). If a future requirement needs the composite layer back, add it behind a per-endpoint feature flag and validate with a real N+1 latency benchmark first.

### Anti-patterns

- **Don't** add a new `DataCapability` flag "just to give agent endpoints a non-empty `@endpoint_meta(capabilities=...)` list" — the empty list is the documented signal that the endpoint is an aggregation, not a fetcher-routed one.
- **Don't** skip writing the response to the cache on success even when `is_cache_enabled()` is True. The cache is the only thing that makes the route usable from agents under fan-out (N+1 board fetches otherwise dominate latency).
- **Don't** call `manager.get_board_stocks(...)` directly from agent code. Always go through `stock_board_cache` (the persistence layer), which handles the ZZSHARE↔THS fallback chain and the `effective_source` plumbing. This is the same rule `/boards/{code}/stocks` follows.
- **Don't** truncate `matched_stocks` before caching in `post_filter_stocks`; truncate in the response path only. Cached entry must reflect the upstream-bounded, un-truncated result, so a later `?limit=200` request (still within upstream cap) doesn't have to re-fetch.
- **Don't** collapse the three `make_*_cache_key` builders into a single generic helper — the keys live in a shared namespace and a typo or hash-input change here would silently invalidate *all* agent caches.
- **Don't** re-introduce parallel `frequency`-keyed dicts in `api/routes/agent.py`. The per-frequency knobs (manager frequency code, days range, default days, MA60 warm-up) live in ONE `FreqProfile` frozen dataclass registry (`_FEATURE_FREQS`). Four parallel dicts is how a missing MA60 warm-up entry silently degraded to `.get(freq, days)` — every MA60 value `None`, no error anywhere. With the dataclass, an omitted field is a construction-time `TypeError`.
- **Don't** write a hand-rolled markdown table in a renderer without guarding the empty case. Only guarding `_render_dict_block` is not enough — the swings table is hand-written and was missed exactly that way. Tests that scan only `| 字段 |` headers will not catch it; scan every `|---|` separator row and require a data row after it.
- **Don't** hardcode `adjust="qfq"` in `/agent/stocks/batch-profile` for minute frequencies — Zzshare P2 / Zhitu P5's `supports_kline` rejects `qfq` for minutes, kicking the primary chain out and leaving only fragile fallbacks. Per spec §3.4 the decision is per-frequency, not per-endpoint.

## Common Commands

> **Use `.venv/Scripts/python.exe` when it exists; fall back to system
> `python` otherwise.** `akshare` / `yfinance` / `gm` live only in `.venv/`.
> Running system `python` when `.venv/` exists makes
> `AkshareFetcher.is_available()` return `False`, silently breaking every
> akshare-routed endpoint (STOCK_BOARD, STOCK_LIST, INDEX_*, ZT_POOL,
> STOCK_REALTIME_QUOTE, …). Without `.venv/` the project still boots; those
> fetchers stay unavailable until you create it and `pip install -e ".[dev]"`.

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

Interactive docs at `http://localhost:8888/explorer/` once the server runs.

**Source of truth is server-side, not the HTML.** The page renders
`GET /control/api-manifest`, generated by reflecting `app.routes` +
`@endpoint_meta`. To change an endpoint's explorer metadata, edit the
`@endpoint_meta(...)` call in `api/routes/` — never the HTML.

## Configuration

`.env.example` is the canonical reference (~140 lines, all env vars + comments).
The non-obvious knobs worth memorizing here:

- `STOCK_DB_INIT=true` — **DROPs and recreates** all persistence tables on boot. Use only in dev/test. Any other value is treated as `false` (idempotent `CREATE IF NOT EXISTS`).
- `STOCK_CACHE_DB_PATH` — SQLite persistence file. Default: `<repo>/stock_data/stock_cache.db`.
- `ENABLE_API_CACHE` — toggle the in-memory `TTLCache` layer (default: `true`).
- `*_PRIORITY` env vars — override any fetcher's default priority at startup. The lower the number, the earlier the fetcher is tried.
- `TRADE_CALENDAR_START_YEAR` — start year for `get_trade_calendar` (zzshare + myquant); legacy `MYQUANT_CALENDAR_START_YEAR` still honored. Default: `1990` (matches akshare upstream's empirical min).
- `TRADE_CALENDAR_END_YEAR` — end year for `get_trade_calendar` (zzshare + myquant); defaults to current year.
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
- **Don't** reorder decorators on a route. The required order is `@router.get → @endpoint_meta → @map_errors → @cache_endpoint → def` (`@endpoint_meta` OUTER relative to `@map_errors`/`@cache_endpoint`, INNER relative to `@router.get`; see `api/routes/news.py:135`). This works only because `endpoint_meta.deco` returns the original `func`, so `route.endpoint` IS the `REGISTRY` key. Break either and the route silently vanishes from the explorer manifest — no error. (`explorer/manifest.py::_lookup_registry` walks `__wrapped__` defensively, but that path is unused today.)
- **Don't** add a `DataCapability` flag without declaring intent — every flag must be in `CAPABILITY_TO_METHOD` (maps to a fetcher method). `tests/test_capability_method_map.py` enforces this (test-only — startup sanity walk removed in b85ed88; `_validate_manifest_invariants` still warns about fetcher_method overrides, missing `@endpoint_meta`, and missing tag titles).
- **Don't** override `@endpoint_meta(fetcher_method=...)` with a method name that doesn't exist on any fetcher class — startup sanity check warns but the manifest will silently produce a misleading Stage 2 entry.
- **Don't** leak the outbound `ts_code` / `_to_xxx_ts_code` suffix into an inbound API response. The server's canonical stock_code format is **bare 6-digit** (e.g. `000034`, `600519`), enforced by `normalize_stock_code()`. Per-upstream protocol formats (Tushare `000034.SZ`, Baostock `sh.600519`, Yfinance `600519.SS`, Zhitu `600519.SH`) are an **outbound-only** concern — they live in helpers like `_to_zzshare_ts_code` / `to_tushare_format` / `to_baostock_code` that are called RIGHT BEFORE the SDK call. On the response side, always return the bare 6-digit (e.g. `ts_code.split(".")[0]`). Forgetting the inbound/outbound boundary is exactly how `ZzshareFetcher.get_board_stocks` / `get_daily_dragon_tiger` / `get_hot_topics` ended up returning `000034.SZ` instead of `000034` (fixed 2026-06-25). Same rule applies to HK (`HK00700`) and US (`AAPL`) codes — they keep their canonical form, never get re-suffixed.
- **Don't** let a fetcher reach into a peer fetcher's package internals — even clean imports like `from akshare.datasets import get_ths_js` or `from akshare.utils import demjson` invert the dependency direction between fetchers (they're peers, not a utility layer). If fetcher X needs to vendor an upstream asset (e.g. THS's `ths.js` JS blob), copy it into `stock_data/data_provider/fetchers/<x>_assets/` (a sub-package under X's directory, must have `__init__.py`) and bundle via `[tool.hatch.build.targets.wheel.force-include]` in `pyproject.toml`. Build-time helpers (e.g. `tools/vendor_ths_js.py`) are the only place allowed to touch a peer fetcher's vendored assets to refresh them; server runtime MUST stay peer-decoupled. See [[extend-not-spawn-fetcher]] + [[vendor-not-peer-import]].
- **Don't** invoke any OpenSpec skill in this project (`openspec-explore` / `opsx:explore`, `openspec-propose` / `opsx:propose`, `openspec-apply-change` / `opsx:apply`, `openspec-archive-change` / `opsx:archive`, `openspec-sync-specs` / `opsx:sync`). The project uses Superpowers + CLAUDE.md + `/control/api-manifest` as its spec substrate; OpenSpec is reserved for new projects. See **Skill Discipline** below for scope, rationale, and enforcement.
- **Don't** treat `data_source` on `/boards/{code}/stocks` as the user's fetcher choice — read `effective_source` instead. As of 2026-07-10 the helper transparently falls back from THS to ZZSHARE (or vice-versa) for `include_quote=false` requests on `source='ths'`; clients that compare `query_source` vs `data_source` to detect fallback will get false positives (cache hit reports `'persistence'`, real upstream serving reports `'ths'`/`'zzshare'`). The `effective_source` field is the only reliable fallback detector; `data_source=='persistence'` means "from cache" regardless of which fetcher originally wrote the row.
- **Don't** trust `stocks.length == top_n` as evidence that the board has exactly N members — it could mean truncation (THS upstream 50-stock login wall). Always read `quote_truncated` and `quote_total_in_board` together. (2026-07-13)
- **Don't** reintroduce `manager.get_stock_list(market, refresh=False)` in `persistence/stock_list.py::get_stock_name`'s cold-cache auto-warm branch. That method does NOT exist on `DataFetcherManager` (the public name is `get_all_stocks`); the `AttributeError` is silently swallowed by `except Exception: pass`, so the DB stays empty and every cold-cache request 400s. Use the persistence-level `get_stock_list(market, manager=manager)` (same file, line 105), which already wires fetch + `update_cached_stocks`. Likewise **don't** collapse `_reject_invalid_stock_code`'s two message branches into one template — the "Index X is not supported..." wording is correct ONLY when `is_index_code(code)` is true; for genuinely-unknown codes the helper emits "Stock code X was not found..." (see Standardized Data Schema → "/stocks/{code}/* 400 contract"). (2026-07-23)
- **Don't** 在 fetcher 层 hardcode "今日 partial bar" 合并逻辑；统一在 K-line route 层 helper 走。Fetcher 层的"今日 bar"逻辑会跨 fetcher 行为不一致，并绕过 manager 的短路与熔断保护。统一在 `api/routes/helpers.py::_maybe_merge_today_bar` 触发（见 [K-line today's partial bar](#k-line-todays-partial-bar)）。

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
