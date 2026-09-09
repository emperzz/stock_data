# `/api/v1/agent/market-stats` — boards 块增 top3 涨/跌板块明细（含 quote）

> Spec for adding top-3 gainers + top-3 losers board detail (with quote
> data) to the `boards` block of `/api/v1/agent/market-stats`. The
> existing `BoardStats` aggregate stays untouched; two new nested list
> fields carry per-board detail.

**Date**: 2026-09-09
**Status**: Draft (post-brainstorm)
**Scope**: `BoardStats` schema + `agent.py::build_market_stats_response`
handler + `_md_stats_block` MD renderer + tests for the boards block
of one existing endpoint. **No new fetcher, no new `DataCapability`
flag, no new manager method, no new endpoint, no new query param**.

---

## 1. Background

`/api/v1/agent/market-stats` currently exposes three blocks:
`stocks` (A-share full-market change_pct distribution),
`boards` (THS concept + industry boards distribution),
`limit_pools` (zt/dt pools). The `boards` block today is purely
aggregate — `sample_size` / `mean_pct` / `median_pct` / `up_count` /
`down_count` / `flat_count` / `buckets` — and gives no visibility into
*which* boards drove the day's move. Agents building dashboards need
that visibility: "全市场普涨但半导体 +5% 领涨" is a much more useful
signal than "383 个板块均值 +0.52%".

The THS board list with `include_quote=True` already returns every
board's `change_pct` (and a sparse set of quote fields) in a single
upstream call — the rows exist; we just don't surface them today.

**Non-goals**:
- HK / US / crypto boards (A-share only at v1).
- Configurable top_n (fixed at 3; leads if fewer available; matching the
  established convention used by `/agent/lead-stocks` default `top_n=3`).
- Re-fetching richer quote data via a second upstream call. The 6 fields
  that ARE populated by the existing THS row dict
  (`change_pct` / `volume` / `amount` / `net_inflow` / `up_count` /
  `down_count`) cover the moving-board use case; the remaining
  `MinimalQuote` fields stay None per the existing precedent set by
  `/agent/boards/batch-profile`.
- Changing the boards upstream call (`stock_board_cache.get_board_list(
  source='ths', include_quote=True)` is already the one upstream call).

---

## 2. Public API

### 2.1 `GET /api/v1/agent/market-stats` — after

```jsonc
{
  "stocks": { ... },
  "boards": {
    "sample_size": 383,
    "mean_pct": 0.52,
    "median_pct": 0.31,
    "max_pct": 5.82,
    "min_pct": -3.15,
    "up_count": 187,
    "down_count": 162,
    "flat_count": 34,
    "bin_width": 1.0,
    "buckets": [...],
    "source": "ths",
    "top_gainers": [
      {
        "code": "881154",
        "name": "半导体",
        "type": "industry",
        "subtype": "881",
        "source": "ths",
        "platecode": "881154",
        "quote": {
          "price": null,            // not in get_board_list row; per boards/batch-profile precedent
          "change_pct": 5.82,       // ✓ populated
          "change_amount": null,
          "open": null,
          "high": null,
          "low": null,
          "prev_close": null,
          "volume": 2345678,        // ✓ populated (wan_shou upstream)
          "volume_unit": "wan_shou",
          "amount": 1.2e9,          // ✓ populated (THS ×1e8 conversion)
          "turnover_pct": null,
          "amplitude_pct": null,
          "volume_ratio": null,
          "pe_ratio": null,         // stock-only, null for board
          "pb_ratio": null,
          "mcap_yi": null,
          "float_mcap_yi": null,
          "limit_up": null,
          "limit_down": null,
          "up_count": 23,           // ✓ populated
          "down_count": 5,          // ✓ populated
          "net_inflow": 4.5e8,      // ✓ populated
          "rank": null
        }
      },
      // ... up to 3
    ],
    "top_losers": [
      // same shape; sorted by change_pct ASC
    ]
  },
  "limit_pools": {...},
  "errors": [...],
  "summary": {...}
}
```

**New nested fields** on `BoardStats`: `top_gainers: list[BoardMoverEntry]`,
`top_losers: list[BoardMoverEntry]`.

**Removed**: nothing.

**Query params** (unchanged): `include_boards: bool = True`,
`include_pools: bool = True`, `trade_date: str | None`,
`format: Literal["json","md"]`.

### 2.2 `BoardMoverEntry` schema

```python
class BoardMoverEntry(BaseModel):
    """One board in /agent/market-stats top_gainers / top_losers."""
    code: str                                  # canonical 6-digit / 881xxx platecode
    name: str
    type: str                                  # "concept" | "industry" | "index" | "special"
    subtype: str                               # e.g. "881" (industry prefix)
    source: str                                # "ths" — always "ths" today
    quote: MinimalQuote | None                 # see §2.1 fill semantics
```

`BoardMoverEntry` is a new schema. It reuses the existing `MinimalQuote`
defined at `schemas.py:1694` (shared across all three batch-profile
endpoints — stock / index / board). **No new quote schema.**

---

## 3. Behavior

### 3.1 Sort + selection

For the boards block (when `include_boards=True` and the upstream call
succeeds):

1. Filter the ~383 rows to those with a finite numeric `change_pct`
   (excludes `None` — same predicate already used at `agent.py:1547`
   for the aggregate stats, so the mover set is consistent with the
   `sample_size` count).
2. `top_gainers` = rows sorted by `change_pct` **DESC** → take first 3.
3. `top_losers` = rows sorted by `change_pct` **ASC** → take first 3.
4. **Tie-breaker**: when `change_pct` ties, sort by `code` **ASC** so
   the result is deterministic across calls (no random ordering on a hot
   tie).
5. If fewer than 3 rows qualify (e.g. market just opened, only 5 boards
   have quotes yet), emit the available rows; do NOT pad with `None`
   entries or with boards that have `change_pct=None`.

The two lists are **independent** — they may contain the same board if
its `change_pct == 0.0`. With finite floats this is rare but the
behavior is intentionally simple: no overlap-dedup.

### 3.2 Quote fill semantics

Each `BoardMoverEntry.quote` is built from the upstream row dict using
a NEW helper `_build_minimal_quote_from_list_row_dict` that mirrors the
existing `_build_minimal_quote_from_board_dict` at `agent.py:1312`
(used by `/agent/boards/batch-profile`). The new helper accepts the
get_board_list row shape:

| `MinimalQuote` field | Source in get_board_list row | Conversion |
|---|---|---|
| `price` | — | `None` |
| `change_pct` | `change_pct` | pass-through |
| `change_amount` | — | `None` |
| `open` | — | `None` |
| `high` | — | `None` |
| `low` | — | `None` |
| `prev_close` | — | `None` |
| `volume` | `volume` | pass-through (THS upstream 万手) |
| `volume_unit` | const | `"wan_shou"` (board convention) |
| `amount` | `amount` | `× 1e8` (THS upstream 亿元 → 元) |
| `up_count` | `up_count` | pass-through |
| `down_count` | `down_count` | pass-through |
| `net_inflow` | `net_inflow` | pass-through |
| `rank` | — | `None` |
| 8 stock-only fields | — | `None` |

This is a **strict subset** of what `_build_minimal_quote_from_board_dict`
populates (the latter sees `get_board_realtime` rows which carry the
missing 7 fields). The sparse fill is the documented behavior — same
precedent as `/agent/boards/batch-profile`, which returns `MinimalQuote`
with `None` for fields the upstream didn't return.

### 3.3 Boards block — partial / total upstream failure

- **Upstream raises (whole boards block fails)**: `boards: BoardStats
  | None = null`; `errors[]` gets a `"boards"` entry. `top_gainers` and
  `top_losers` are absent (their parent is `None`). No behavior change
  vs. today.
- **Upstream succeeds, returns `[]`**: `boards` block has
  `sample_size=0` / `mean_pct=None` / `buckets=[...]` with all counts
  zero (existing behavior at `agent.py:1554`). `top_gainers=[]`,
  `top_losers=[]`. No `errors[]` entry — empty upstream is not an
  error.
- **`include_boards=False`**: `boards: null` (whole field absent);
  `top_gainers` / `top_losers` are NOT emitted (no parent). No errors
  (the route intentionally skips the upstream call).

### 3.4 Cache impact

**None.** The boards block already routes through ONE upstream call
site (`stock_board_cache.get_board_list(...)`) that returns all ~383
rows (internally THS + zzshare merged via
`fetch_boards_with_zzshare_backfill` — that detail is unchanged).
Computing top-3 gainers / top-3 losers is pure in-memory sort. No new
upstream call site, no new fetcher-level cache key, no new top-level
cache key. The existing `make_market_stats_cache_key(include_boards,
include_pools, target_date)` signature is unchanged — its value is
unchanged — and the 60s TTL via `get_quote_cache` covers the new fields
automatically.

### 3.5 `ok` / `requested` accounting

`ok` is incremented **once** for the whole boards block, regardless of
how many top movers we emit (or whether the list is `[]`). This
matches the existing block-level accounting at `agent.py:1556`. The
new fields do not introduce a new error block.

---

## 4. Schema additions

### 4.1 `stock_data/api/schemas.py`

**New**:
```python
class BoardMoverEntry(BaseModel):
    """One board in /agent/market-stats top_gainers / top_losers."""
    code: str
    name: str
    type: str
    subtype: str
    source: str
    quote: MinimalQuote | None = None
```

**Modified** — extend `BoardStats` (existing at `schemas.py:2123`):
```python
class BoardStats(BaseModel):
    """Full-market board statistics (THS source)."""

    sample_size: int = Field(ge=0)
    mean_pct: float | None
    median_pct: float | None
    max_pct: float | None
    min_pct: float | None
    up_count: int = Field(ge=0)
    down_count: int = Field(ge=0)
    flat_count: int = Field(ge=0)
    bin_width: float = 1.0
    source: str = ""
    buckets: list[DistributionBucket]
    # NEW (2026-09-09): top movers for client dashboards. Always list
    # (never None) so consumers can iterate without null checks; list
    # may be empty if upstream returned 0 rows with non-None change_pct.
    top_gainers: list[BoardMoverEntry] = Field(default_factory=list)
    top_losers: list[BoardMoverEntry] = Field(default_factory=list)
```

**No changes** to `MarketStatsResponse`, `MarketStatsErrorEntry`,
`MarketStatsLimitPools`, or any other schema.

### 4.2 Cache key

**No changes.** `make_market_stats_cache_key(include_boards,
include_pools, trade_date)` keeps its 3-arg signature. The new fields
are derived deterministically from the upstream rows already in cache.

---

## 5. Handler / route layer

### 5.1 `stock_data/api/routes/agent.py`

**New helper** (placed next to `_build_minimal_quote_from_board_dict`):
```python
def _build_minimal_quote_from_list_row_dict(row: dict) -> MinimalQuote:
    """Map a stock_board_cache.get_board_list row to MinimalQuote.

    The get_board_list row shape is sparser than get_board_realtime's —
    only 6 of the 13 board-relevant MinimalQuote fields have upstream
    values (change_pct / volume / amount / net_inflow / up_count /
    down_count). The other 7 board-relevant fields (price / change_amount
    / OHLC / prev_close / rank) and the 8 stock-only fields stay None.
    This matches /agent/boards/batch-profile's "None when upstream
    doesn't supply" contract.

    `amount` is multiplied by 1e8 to convert THS upstream 亿元 → 元,
    matching the conversion already applied at `routes/boards.py:857`
    and inside `_build_minimal_quote_from_board_dict` for the realtime
    path.
    """
    raw_amount = row.get("amount")
    return MinimalQuote(
        change_pct=row.get("change_pct"),
        volume=row.get("volume"),
        volume_unit="wan_shou",
        amount=(raw_amount * 1e8) if raw_amount is not None else None,
        up_count=row.get("up_count"),
        down_count=row.get("down_count"),
        net_inflow=row.get("net_inflow"),
    )
```

**New helper** (pure function, no upstream calls):
```python
def _select_top_board_movers(
    rows: list[dict], *, top_n: int = 3
) -> tuple[list[BoardMoverEntry], list[BoardMoverEntry]]:
    """Pick top-N gainers and losers from the get_board_list rows.

    Filters out rows with non-finite change_pct (None / bool / str).
    Tie-breaker = code ASC. Returns two independent lists — both may
    contain the same row if its change_pct == 0.0.
    """
    def _pct(r):
        v = r.get("change_pct")
        return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None

    eligible = [
        (r, _pct(r)) for r in (rows or [])
    ]
    eligible = [(r, p) for r, p in eligible if p is not None]

    gainers = sorted(eligible, key=lambda rp: (-rp[1], rp[0].get("code") or ""))[:top_n]
    losers = sorted(eligible, key=lambda rp: (rp[1], rp[0].get("code") or ""))[:top_n]

    def _to_entry(rp):
        r, _ = rp
        return BoardMoverEntry(
            code=r.get("code") or "",
            name=r.get("name") or "",
            type=r.get("type") or "",
            subtype=r.get("subtype") or "",
            source=r.get("source") or "ths",
            quote=_build_minimal_quote_from_list_row_dict(r),
        )

    return [_to_entry(rp) for rp in gainers], [_to_entry(rp) for rp in losers]
```

**Modified** — extend the boards block in
`build_market_stats_response` (`agent.py:1535`):
```python
if include_boards:
    try:
        boards, src = stock_board_cache.get_board_list(
            board_type=None, source="ths", include_quote=True, manager=manager,
        )
        values = [
            b.get("change_pct")
            for b in (boards or [])
            if isinstance(b.get("change_pct"), (int, float))
            and not isinstance(b.get("change_pct"), bool)
        ]
        agg = compute_aggregate(
            values, bin_width=BOARD_BUCKET_BIN_WIDTH,
            buckets_template=build_board_buckets(),
        )
        top_gainers, top_losers = _select_top_board_movers(boards, top_n=3)
        boards_stats = _board_stats_from_aggregate(agg, src or "ths")
        boards_stats.top_gainers = top_gainers      # NEW
        boards_stats.top_losers = top_losers        # NEW
        ok += 1
    except Exception as exc:
        # unchanged
```

**Stub impact** (`_stats_stub_null` at `agent.py:2690`): unchanged.
`BoardStats(...)` with default factory for both new list fields yields
`top_gainers=[]` / `top_losers=[]`, which is the right "no data" shape.
No explicit stub update needed.

### 5.2 MD renderer

**Modified** — extend `_md_stats_block` (currently at `agent.py:2183`)
to render the new fields after the existing stats summary + buckets.
Layout:

```
## 板块
样本数: 383 (ths 板块清单); 均值 +0.52%, 中位 +0.31%, 最高 +5.82%, 最低 -3.15%
上涨: 187 / 下跌: 162 / 平盘: 34

| 区间 | 计数 | 占比 |
|---|---|---|
| ... |

### 涨幅前三
| 代码 | 名称 | 涨跌幅 | 成交额(亿) | 成交量(万手) | 上涨 | 下跌 | 资金净流入(亿) |
|---|---|---|---|---|---|---|---|
| 881154 | 半导体 | +5.82% | 12.0 | 2345678 | 23 | 5 | 4.5 |
| ...

### 跌幅前三
| 代码 | 名称 | 涨跌幅 | 成交额(亿) | 成交量(万手) | 上涨 | 下跌 | 资金净流入(亿) |
|---|---|---|---|---|---|---|---|
| 881127 | 煤炭 | -3.15% | ...
```

- New helper `_md_top_movers(out: list[str], title: str, entries:
  list[BoardMoverEntry])` emits a heading + a single table OR a single
  `（无数据）` marker when the list is empty — same empty-table rule
  as `_render_dict_block` (no bare heading + separator + zero rows).
- `_md_stats_block` is extended to call the helper after the buckets
  table.
- The full `BoardMoverEntry.quote` (23 `MinimalQuote` fields, sparse
  per §3.2) is surfaced in the JSON unchanged. The MD table projects
  only the 7 most-relevant fields (code / name / change_pct / amount /
  volume / up_count / down_count / net_inflow) — agents that need the
  full 23-field quote read JSON. This is an intentional MD projection
  choice, not a CLAUDE.md "no field dropped" violation, because the
  contract is "MD omits Nothing the JSON carries"; here JSON still
  carries every field (the MD just doesn't render them all in tabular
  form). A future iteration can project the full quote per-row if the
  consumer signals demand.

### 5.3 CLAUDE.md

**No change.** Per project convention ("Don't write to CLAUDE.md
unless explicitly asked"), the spec + plan are the contract substrate.

---

## 6. Tests

### 6.1 `tests/test_agent_market_stats_schemas.py`

- `test_board_stats_default_top_movers`: `BoardStats(...)` constructs
  with `top_gainers=[]` and `top_losers=[]`.
- `test_board_mover_entry_minimal_quote_none_when_sparse`: a
  `BoardMoverEntry` constructed from a `get_board_list` row with only
  `change_pct` populates `quote` with the 1 populated field and 22
  None fields.

### 6.2 `tests/test_agent_market_stats.py`

- `test_boards_top_gainers_top_losers_sorted`: feed 10 fake boards
  with mixed change_pcts; assert top 3 / bottom 3 by change_pct.
- `test_boards_top_movers_none_change_pct_excluded`: feed rows with
  `change_pct=None` / `change_pct="—"`. Assert None and string rows
  are skipped; remaining numeric rows appear in the movers.
- `test_boards_top_movers_tie_break_code_asc`: feed 4 rows with
  identical change_pct. Assert they appear in code ASC order.
- `test_boards_top_movers_fewer_than_three`: feed only 2 numeric rows.
  Assert `len(top_gainers) == 2` and `len(top_losers) == 2`.
- `test_boards_top_movers_include_quote_amount_units`: feed a row
  with `amount=1.5` (亿元). Assert `entry.quote.amount == 1.5e8` (元).
- `test_boards_block_failure_leaves_top_movers_absent`: patch
  `stock_board_cache.get_board_list` to raise `DataFetchError`; assert
  `response.boards is None`, `response.errors` has a `block="boards"`
  entry, and the JSON-encoded response does NOT contain
  `top_gainers` (the field is absent because its parent is absent).
- `test_boards_block_empty_upstream_emits_empty_top_movers`: patch
  `get_board_list` to return `[]`; assert
  `response.boards.top_gainers == []` and
  `response.boards.top_losers == []`.

### 6.3 MD tests

- `test_market_stats_md_includes_top_movers_sections`: existing
  `test_format_md_returns_markdown` extended to assert the
  `### 涨幅前三` / `### 跌幅前三` headings and ≥1 data row each.
- `test_market_stats_md_empty_movers_emits_explicit_marker`: feed 0
  boards; assert MD contains `### 涨幅前三` + `（无数据）` (not a
  bare-table skeleton).

### 6.4 Regression coverage

The existing `test_boards_upstream_failure_does_not_affect_stocks`,
`test_stocks_upstream_failure_does_not_affect_boards`,
`test_both_blocks_fail`, `test_include_boards_false_skips_boards_upstream`,
`test_cache_key_includes_include_boards`, and
`test_market_stats_cache_hit_skips_upstream` must pass unchanged.
The mock helpers (`_patch_board_cache`, `_patch_manager`) already
return enough structure to drive the new top-movers logic — no
fixture extension needed.

---

## 7. Migration / rollout

Single PR / single merge. Schema additions are forward-compatible:
existing consumers that don't know about `top_gainers` /
`top_losers` see them as additional unknown JSON fields (Pydantic
default behavior is permissive — `extra="ignore"` is the project
default). No client coordination needed.

The cache key signature is unchanged; in-flight 60s entries from
before the deploy are simply missing the new fields. Self-expires in
TTL — no flush, no migration. After the deploy, all new entries have
the new fields populated.

---

## 8. Open questions / future work

- Should we later add `?movers_top_n=N` for configurable N? Currently
  fixed at 3 per user direction. Defer until there's demand.
- Should the movers use the same `top_gainers` / `top_losers` field
  names as the `/agent/market-stats` stocks block might use if it
  gained a similar block? Currently `/agent/market-stats.stocks` has
  no such nested fields — only the boards block does. If/when stocks
  gains similar fields, naming will be mirrored.
- Should `top_gainers` and `top_losers` ever overlap on a `change_pct
  == 0.0` board? Currently they do (intentional, per §3.1 item 5).
  If the user later asks for non-overlap, a one-line filter fixes it.