# Board endpoint source semantics

Read this when working on `/boards/*` or `/stocks/{code}/boards` responses,
or when a client asks "which fetcher actually served this?". Extracted from
CLAUDE.md 2026-08-27 to keep the always-resident spec lean; the resident
copy keeps only the pointer plus the two facts that are default-wrong
(read `effective_source`, not `data_source`; the circuit breaker does not
cover board endpoints).

## Source isolation (2026-09-11 split)

`ths` and `zzshare` are two independent first-class sources with disjoint
board code spaces. There is NO cross-source fallback and NO alias: a
`?source=ths` request never calls zzshare, and vice versa.

| source | board_code namespace | ths_cid | history | realtime quote |
|---|---|---|---|---|
| `ths` | 885xxx / 886xxx / 881xxx | 3xxxxx (concept) / ==code (industry) / NULL | yes | yes |
| `zzshare` | 801xxx / 803xxx / 710xxx / 883xxx | always NULL | no (400) | no |
| `eastmoney` | BKxxxx | NULL | yes | no |
| `zhitu` | sw_xxx | NULL | no | no |

`/boards/{code}/quote` takes **no `?source=` parameter at all** — it is
hardcoded to ths, and an unexpected `?source=` is silently ignored (NOT
422). `/boards/{code}/news` and `/surges` DO declare `Literal["ths"]` and
therefore really do 422 on any other value.

`/stocks/{code}/boards` with no `?source=` aggregates all four sources, so
zzshare's ~55k membership rows are reachable through the label that names
them. The old `zzshare → ths` alias meant every entry came back as
`source='ths'` and those rows were unreachable.

## Cache

`stock_board` and `stock_board_membership` are keyed `(code, source)` and
`(board_code, source, stock_code)`. A cache hit for one source can never
serve another source's rows, and the board-stock refresh tracker is keyed
`f"{board_code}:{source}"`. `update_cached_boards` is a
`(board_type, source)` snapshot replace (DELETE-then-INSERT), so a board
that left upstream stops lingering and a board seen once under a cid-shaped
key and later under a platecode-shaped key cannot be stored twice.

`data_source='persistence'` means "served from SQLite"; `effective_source`
is the fetcher that served. Since there is no cross-source fallback, it only
ever distinguishes legs WITHIN one source — the THS AJAX (<=50 rows) and F10
(>50 rows) tiers.

## effective_source no longer signals a fallback

Pre-split, `query_source='ths'` + `effective_source='zzshare'` meant the
cross-source fallback fired. That combination is now impossible. The
cache-hit early return used to hardcode `effective_source='ths'`; it now
reports the row's own `source` (2026-09-11).

## THS cid <-> platecode (2026-09-11)

THS gives every concept board two identifiers: a public `platecode`
(885xxx / 886xxx) and an internal `cid` (3xxxxx). They are NOT
interchangeable — the gn AJAX constituent endpoint takes the cid, the F10
page and board K-line take the platecode. Industry boards use one value
(881xxx) for both.

`ths_board_id_map` (SQLite) is the single cid -> platecode lookup. It is
seeded at startup from `stock_data/stock_data_backup/ths_board_id_map.csv`
and refreshed by
`.venv/Scripts/python.exe -m stock_data.tools.refresh_ths_board_id_map --apply`,
which sweeps THS's own `GET /gn/` (gnSection pair) and falls back to one
`/gn/detail/code/{cid}/` request per unresolved board. The runtime board
path additionally resolves an individual miss on demand and writes the
result back, so each board costs at most one detail-page request ever.

**The CSV is a snapshot, never authoritative.** It only contains pairs THS
has shown us at some point; live observations must always overwrite it, or
a THS renumbering would go unnoticed until a fetch 404s. The refresh tool
prints an added / changed / removed diff for exactly that reason.

A `ths_cid` value is always a real cid or NULL — never a platecode. The
110 legacy rows that had `cid == code == 885xxx/886xxx` (the pre-2026-07-20
layout wrote a platecode into the cid column) had their `cid` cleared during
the 2026-09-11 CSV split.

## The seed CSVs are per-source, and split by provenance

`stock_data/stock_data_backup/` holds one CSV per source:
`stock_board_ths.csv` (588 rows), `stock_board_zzshare.csv` (186),
`stock_board_eastmoney.csv` (992), `ths_board_id_map.csv` (480), plus
`stock_board_membership_ths.csv` (59,780 rows) and
`stock_board_membership_zzshare.csv` (55,301).

The membership pair is a **provenance split, not a preference**: the legacy
combined file was 55,301 zzshare rows (801/803/710/883) + 59,780 THS rows
(881/885/886), proven by disjoint code spaces and by the two sources'
distinct subtype vocabularies (zzshare emits 同花顺题材 from plate=17, which
THS never does; THS emits 同花顺行业 on 881xxx). Relabelling the whole file
either way mislabels half of it.

Neither side is complete: zzshare 186/186 boards have membership (plus 44
membership codes with no board row), THS 558/588 (95%). Runtime lazy fill
and `BOARD_BACKFILL_ON_STARTUP` cover the rest.

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

