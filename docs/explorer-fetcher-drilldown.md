# Explorer Stage 1/2 fetcher drill-down — data flow

Read this when changing `explorer/manifest.py`, the `fetchers[]` manifest
field, or `/control/fetcher-test`. Extracted from CLAUDE.md 2026-08-27; the
resident spec keeps the `fetcher_method` override table and the three
anti-patterns (those are default-wrong traps), and points here for the flow.

The `/explorer/` UI shows, under each endpoint card, a collapsible
"Fetcher backends" section listing every fetcher that can serve the
endpoint along with its internal method signature. Each row has a
`Test` button that opens an inline form posting to `POST /control/fetcher-test`
to invoke the fetcher method directly (bypassing manager failover).

## Data flow

1. `GET /control/api-manifest` returns endpoints with a new `fetchers[]`
   field. Each entry is `{name, method, priority, capabilities, signature, available, reason}`
   where `name` is the fetcher class name (e.g. `BaostockFetcher`),
   `available` indicates whether the fetcher is currently usable (config/token present),
   and `reason` explains why it's unavailable (null when available).
2. The manifest builder uses `data_provider.base.CAPABILITY_TO_METHOD`
   (and `EndpointMeta.fetcher_method` override) to figure out the right
   method per fetcher.
3. HTML renders the rows under a `<details>`-based collapse.
4. Clicking Test → POST `/control/fetcher-test` body
   `{fetcher, method, kwargs}` → **always HTTP 200**; success/failure in
   the body's `ok` field. Errors classified as
   `UnknownFetcher / UnknownMethod / FetcherUnavailable / TypeError / <ExceptionName>`,
   each with optional traceback.

## Per-fetcher method override

Beyond the `@endpoint_meta(fetcher_method=...)` table in CLAUDE.md, the
manifest builder has one per-fetcher override:
`_ZHITU_STOCK_KLINE_METHOD = "get_intraday_data"` — when the capability is
`STOCK_KLINE` and the fetcher is `ZhituFetcher`, the manifest uses
`get_intraday_data` instead of the default `get_kline_data`.

## Why board endpoints are source-routed

The `?source=` query parameter selects the fetcher (e.g. `eastmoney`,
`zhitu`). Different sources use incompatible board classification systems,
so failover between sources is intentionally not supported. The Manager
uses `_with_source()` (not `_with_failover()`) for all board methods.
