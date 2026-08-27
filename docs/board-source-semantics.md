# Board endpoint source semantics

Read this when working on `/boards/*` or `/stocks/{code}/boards` responses,
or when a client asks "which fetcher actually served this?". Extracted from
CLAUDE.md 2026-08-27 to keep the always-resident spec lean; the resident
copy keeps only the pointer plus the two facts that are default-wrong
(read `effective_source`, not `data_source`; the circuit breaker does not
cover board endpoints).

## Board Cache Source-Normalization (post-unification)

`/boards/{code}/stocks` advertises "strict source routing" on the route layer (the user's `?source=` is plumbed through to the fetcher), **but the underlying SQLite cache (`stock_board_membership`) is keyed on `source='ths'` regardless of which fetcher served the response.** This is the post-2026-07-08 unification policy:

- **Why**: different sources normalize to the same THS platecode (e.g. eastmoney and ths both store `885595` for the same concept board). Per-source cache keys would force each source to cold-start its own cache row for the same board, doubling cold-path latency for no data-fidelity gain.
- **What it means in practice**: a user passing `?source=eastmoney` who hits a ths cache row will get ths data with `data_source='persistence'`. The user's `?source=` is only honored on the cache-miss / refresh path (where `update_cached_board_stocks` always writes under `source='ths'`).
- **User-visible contract**: `data_source='persistence'` does NOT mean the user's `?source=` was used — it means *some* fetcher served the request and the result was cached. The actual fetcher that served the most recent refresh is in the log, not the response.

If a future change requires per-source cache isolation (e.g. eastmoney-specific data fidelity concerns), change `update_cached_board_stocks(board_code, "ths", ...)` (board.py:900) to use the real origin label. Track this as a breaking change.

## `effective_source` (post-2026-07-10) — disambiguating fallback from primary

On `/boards/{code}/stocks`, the response carries **both** of:
  * `query_source` — the user's `?source=` (verbatim, after Literal validation).
  * `data_source` — `'persistence'` (cache hit) or the requested fetcher slug.
  * **`effective_source`** — the fetcher that *actually served* the upstream call (always populated, per P4 contract).

**Cache-hit caveat (clarified 2026-07-16, audit §B).** On a cache hit no upstream call runs, so `effective_source` returns the cache-key label (`'ths'` for the post-2026-07-08 unified-cache scheme) rather than a real upstream serving fetcher. Compare against `data_source=='persistence'` to distinguish cache hits from real upstream serving; comparing `effective_source` to `query_source` only meaningfully detects the ZZSHARE ↔ THS fallback chain described below (which fires on cache-miss / refresh).

For `source='ths'` + `include_quote=False` requests, the helper at
`persistence/board.py::fetch_board_stocks_with_zzshare_fallback` runs an
internal **ZZSHARE primary + THS fallback** chain. `effective_source` makes
the difference observable: `query_source='ths'` + `effective_source='zzshare'`
means ZZSHARE primary served, the THS leg was not needed; `effective_source='ths'`
means ZZSHARE failed or returned empty and THS fallback served.

Pre-2026-07-10 this distinction was *implicit* (silent cross-source
fallback). Clients should compare `effective_source` vs `query_source` to
detect fallback and avoid parsing `data_source` ambiguously.

**Side effect**: when ZZSHARE serves the fallback path, the cached rows
lack quote fields (ZZSHARE emits only `stock_code / stock_name / exchange`).
A subsequent `?include_quote=true` request with the same date will skip the
cache (`needs_refresh` is forced by `include_quote`) and re-fetch via THS,
so clients don't see "apparent None quotes" — but if you want to force a
fresh THS fetch on already-cached data, pass `?refresh=true`.

## Board endpoint failure observability

Board endpoints route through `DataFetcherManager._with_source`, which
does **not** integrate with the per-source `CircuitBreaker`. THS
outages on a board path therefore do **not** show up as CB state
changes — they surface as 5xx error rate. If you need CB-protected
failover, use a non-board endpoint (K-line, realtime quote) that
routes through `_with_failover` instead. (Documented 2026-07-10; the
previously-stated claim that "real THS board failures can trip the
circuit breaker" was incorrect — board methods have never been
CB-integrated.)

## Persistence ↔ manager bidirectional coupling (audit §M3)

The resident rule is one-directional ("board routes call `stock_board_cache`,
not `DataFetcherManager`"). The reverse direction also exists, and matters
only if someone swaps SQLite for another backend:

- `manager.py:692, 772` lazy-imports `persistence.trade_calendar` (`get_cached_calendar` / `update_cached_calendar`) and `persistence.pool_daily` (`get_pool`) inside method bodies, to break what would otherwise be a load-time circular import.
- Five fetchers also reach down into persistence for table lookup helpers: `baostock_fetcher.py:219` (cached calendar), `zzshare_fetcher.py:74-75` (`THS_CONCEPT_SUBTYPE` constants + `get_latest_trade_date_on_or_before`), `ths_fetcher.py:63, 849, 907, 1332, 1351` (`THS_CONCEPT_SUBTYPE` + `get_board_metadata` + `_resolve_ths_cid_from_platecode`), `zhitu_fetcher.py:218, 970` (`get_latest_cached_trade_date`), `eastmoney/_boards_mixin.py:674` (`resolve_board_types`).

If a future change swaps SQLite for another backend (Postgres / Redis), all six of those import sites need to move with it — they're not abstracted behind a port interface today. Track as future tech debt; not blocking under the local-personal-project premise (SQLite + `backfill.py` rebuild keeps the risk low).
