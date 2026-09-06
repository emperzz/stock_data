# `/agent/{stocks,indices,boards}/batch-profile` Quote Enrichment (12 fields)

**Date**: 2026-08-27
**Status**: Approved (awaiting implementation plan)
**Scope**: widen the `MinimalQuote` Pydantic model from 2 fields to 12, populate the new fields opportunistically across the three batch-profile handlers, and update the MD renderers + tests + docs in lockstep. **No new fetcher, no new `DataCapability` flag, no new manager method.** No new composite cache layer; existing fetcher-level TTLs continue to govern.

---

## 1. Background

The three `/agent/*/batch-profile` endpoints (`stocks`, `indices`, `boards`) currently surface only **2 fields** in their `quote` aspect: `price` and `change_pct`. Every other field of the upstream `UnifiedRealtimeQuote` (defined at `stock_data/data_provider/core/types.py:57`) is silently dropped on the floor by `agent.py:935` / `:1060` / `:674`.

For intraday / short-horizon decisions — *today* is the goal: agents running `stock-picking` §4 step 5 need to see whether a candidate is changing hands, the day's range, and turnover — the 2-field payload is too thin. Today an agent has to make a second round-trip to `/stocks/{code}/quote` after `batch-profile` returned. Both calls hit the same fetcher (Zzshare / Akshare / Tencent realtime) and the second is fully cacheable, but the latency stacks up under fan-out.

The 12-field enrichment fixes this at the API boundary: the `quote` aspect in `batch-profile` now carries every common short-horizon anchor that `UnifiedRealtimeQuote` already plumbs, with `None` semantics for fields the upstream doesn't populate (boards via THS, in particular, do not surface `turnover_pct` / `amplitude` / `volume_ratio`).

**User intent** (brainstorming 2026-08-27): "返回的数据除了有 price 和 change_pct，将 volume、open、high、turnover_pct 等值都带上" — explicit field set; `open` and `turnover_pct` named verbatim, others specified by intent.

**Non-goals**:

- Multi-source for boards (still THS only).
- New `DataCapability` flag — `@endpoint_meta(capabilities=[])` stays empty (per CLAUDE.md).
- Adding raw K-line bars to the response (use `/stocks/{code}/kline`).
- Filling fields the upstream can't supply — missing = `None`, never a stale placeholder.
- Touching `boards_overlap` / `stocks_overlap` / `filter-stocks` / `market-stats` / `market-context` (those don't have a `quote` aspect).

---

## 2. Public API

All three endpoints inherit the same widening; no request changes; no new query parameters.

### 2.1 Response shape change

**Before** (current):
```json
"quote": {"price": 1721.0, "change_pct": 1.2}
```

**After** (12 fields, all optional, missing → `null`):
```json
"quote": {
  "price":         1721.0,
  "change_pct":    1.2,
  "open":          1700.0,
  "high":          1730.0,
  "low":           1695.0,
  "pre_close":     1700.5,
  "volume":        3100000,
  "amount":        5.34e8,
  "change_amount": 20.5,
  "turnover_pct":  0.85,
  "amplitude":     2.06,
  "volume_ratio":  1.42
}
```

### 2.2 Field reference table

| Field | Type | Source mapping | Notes |
|---|---|---|---|
| `price` | `float\|null` | `UnifiedRealtimeQuote.price` | Existing. Last trade price. |
| `change_pct` | `float\|null` | `UnifiedRealtimeQuote.change_pct` | Existing. Percent vs `pre_close`. |
| `open` | `float\|null` | `UnifiedRealtimeQuote.open_price` | New. Renamed from `open_price` per user request. |
| `high` | `float\|null` | `UnifiedRealtimeQuote.high` | New. Day's high. |
| `low` | `float\|null` | `UnifiedRealtimeQuote.low` | New. Day's low. |
| `pre_close` | `float\|null` | `UnifiedRealtimeQuote.pre_close` | New. Previous-close reference. |
| `volume` | `int\|null` | `UnifiedRealtimeQuote.volume` | New. Shares traded (never shares×100; spec §3.4 `volume_unit` is always `"share"`). |
| `amount` | `float\|null` | `UnifiedRealtimeQuote.amount` | New. Total traded value (CNY). |
| `change_amount` | `float\|null` | `UnifiedRealtimeQuote.change_amount` | New. Price delta vs pre_close. |
| `turnover_pct` | `float\|null` | `UnifiedRealtimeQuote.turnover_rate` | New. Renamed from `turnover_rate` per user request; the source field IS a percentage per spec §3.4. |
| `amplitude` | `float\|null` | `UnifiedRealtimeQuote.amplitude` | New. Day's `(high - low) / pre_close * 100`. |
| `volume_ratio` | `float\|null` | `UnifiedRealtimeQuote.volume_ratio` | New. Latest volume / 5-bar mean. |

**Per-source availability**:

- **Stocks** (`manager.get_realtime_quote`) — Zzshare / Akshare / Tencent / Zhitu / Myquant all populate 10-12 of 12 (depending on the field). Most fields pop in production.
- **Indices** (`manager.get_index_realtime_quote`) — A股 (CSI) indices via Akshare / Yfinance / Zhitu; HK / US indices via Yfinance. Some fields (`volume_ratio`, `amplitude`) may be sparse for HK / US — same `None` semantics.
- **Boards** (`manager.get_board_realtime(source="ths")`) — dict-shaped upstream; THS provides `price`, `change_pct`, `open`, `high`, `low`, `pre_close`, `volume`, `amount`. `change_amount`, `turnover_pct`, `amplitude`, `volume_ratio` are **not surfaced** by THS and stay `None`.

### 2.3 Naming discipline

Per CLAUDE.md "don't leak the outbound `ts_code` suffix" + "don't expose internal field names verbatim", we deliberately rename two fields against the internal `UnifiedRealtimeQuote` dataclass:

- `open_price` → `open` (shorter; matches user request wording).
- `turnover_rate` → `turnover_pct` (the source field is already a percentage per spec §3.4; the API name is honest).

All other 10 fields keep their `UnifiedRealtimeQuote` field name verbatim. The route-layer mapping is a one-time conversion, never re-broadcast.

---

## 3. Implementation

### 3.1 Schema (`stock_data/api/schemas.py:1603`)

```python
class MinimalQuote(BaseModel):
    """Realtime anchor — 12-field short-horizon decision support.

    Widened from 2 → 12 fields on 2026-08-27 (batch-profile quote
    enrichment). All fields are None when the upstream doesn't populate
    them; this is the canonical "absent → null" contract for the three
    batch-profile endpoints. See
    docs/superpowers/specs/2026-08-27-batch-profile-quote-enrichment-design.md.
    """
    # core (existing)
    price: float | None = None
    change_pct: float | None = None
    # range
    open: float | None = None
    high: float | None = None
    low: float | None = None
    pre_close: float | None = None
    # money
    volume: int | None = None
    amount: float | None = None
    change_amount: float | None = None
    # ratios
    turnover_pct: float | None = None
    amplitude: float | None = None
    volume_ratio: float | None = None
```

The class name `MinimalQuote` is a misnomer now — it carries 12 fields, but renaming it to `Quote` would be a big search-and-replace across route handlers, MD templates, tests, and OpenAPI consumers. **Deferred** as a follow-up; tracked but not in scope for this change.

### 3.2 Stocks handler (`stock_data/api/routes/agent.py:932-936`)

```python
try:
    q = manager.get_realtime_quote(code)
    if q is not None:
        quote = MinimalQuote(
            price=q.price,
            change_pct=q.change_pct,
            open=q.open_price,
            high=q.high,
            low=q.low,
            pre_close=q.pre_close,
            volume=q.volume,
            amount=q.amount,
            change_amount=q.change_amount,
            turnover_pct=q.turnover_rate,
            amplitude=q.amplitude,
            volume_ratio=q.volume_ratio,
        )
        name = getattr(q, "name", "") or ""
except Exception as exc:
    logger.warning(f"[agent/stocks/batch-profile] {code} quote failed: {exc}")
    errors.append(
        StockBatchAspectError(aspect="quote", error=type(exc).__name__, message=str(exc))
    )
```

The existing `try/except` for the `quote` aspect stays — defensive fill is opportunistic, so any `getattr`-style fallback we add would only hide bugs. Plain attribute access means missing source fields raise `AttributeError`, which the outer `except` catches and surfaces in `errors[]` as a quote failure (not silently null). This is the existing semantics; we keep it.

### 3.3 Indices handler (`stock_data/api/routes/agent.py:~675`)

Same shape as §3.2 — `manager.get_index_realtime_quote(code)` returns `UnifiedRealtimeQuote` per `data_provider/manager.py`'s contract. The existing routing through `manager.get_index_realtime_quote` is unchanged; only the field mapping into `MinimalQuote` widens.

### 3.4 Boards handler (`stock_data/api/routes/agent.py:1056-1061`)

Boards return a dict, not an `UnifiedRealtimeQuote`. The fill uses `.get()` with no default (so missing keys → `None`):

```python
q, _src = manager.get_board_realtime(code, source="ths")
if q is not None:
    quote = MinimalQuote(
        price=q.get("price"),
        change_pct=q.get("change_pct"),
        open=q.get("open"),
        high=q.get("high"),
        low=q.get("low"),
        pre_close=q.get("pre_close"),
        volume=q.get("volume"),
        amount=q.get("amount"),
        # change_amount, turnover_pct, amplitude, volume_ratio
        # not surfaced by THS → default None
    )
```

**Type caveat — investigation needed during implementation**: THS board realtime for `volume` may arrive as `float` (e.g. `3.0e7` for 30M shares). Pydantic v2 with `volume: int | None = None` will reject a `float` assignment with `ValidationError`, which the outer `except` in `post_boards_batch_profile` would re-raise as an entry-level 500. The mitigations in order of preference:

1. Cast `int(q.get("volume"))` in the boards branch — but loses `None` semantics (`int(None)` is `TypeError`, caught by outer except → spurious 500).
2. Branch on `isinstance`: `volume=int(v) if isinstance(v, float) and v == int(v) else (v if v is None else int(v))` — verbose.
3. Change schema to `volume: float | None = None` (broader type, but loses the int contract).

**Decision**: implementation should verify THS dict's volume type before touching the code path. If THS returns float shares, fall back to option 3 (loosen schema to `float | None`) and add a comment in the schema explaining why. If THS returns int, current schema is fine. **Defer to the implementation plan** for the empirical check.

### 3.5 MD renderer (`stock_data/api/routes/agent.py:1701, 1524, 1498`)

Per CLAUDE.md "No data is dropped — every JSON field appears in the MD output", all 12 fields must render in the MD projection when populated. Extract a shared helper (same lifecycle as `_md_feature_block`):

```python
QUOTE_FIELDS = (
    # (label, attr, formatter)
    ("最新价",     "price",          _md_num),
    ("涨跌幅",     "change_pct",     _md_pct),
    ("开盘价",     "open",           _md_num),
    ("最高价",     "high",           _md_num),
    ("最低价",     "low",            _md_num),
    ("昨收",       "pre_close",      _md_num),
    ("成交量(股)", "volume",         lambda v: f"{int(v):,}" if v is not None else None),
    ("成交额(元)", "amount",         lambda v: f"{v:,.2f}"),
    ("涨跌额",     "change_amount",  _md_num),
    ("换手率",     "turnover_pct",   _md_pct),
    ("振幅",       "amplitude",      _md_pct),
    ("量比",       "volume_ratio",   _md_num),
)

def _md_quote_block(out: list[str], q: MinimalQuote) -> None:
    """Emit one bullet per populated quote field; absent = hidden."""
    out.append("### 实时报价")
    any_emitted = False
    for label, key, fmt in QUOTE_FIELDS:
        v = getattr(q, key)
        if v is None:
            continue
        out.append(f"- **{label}**: {fmt(v)}")
        any_emitted = True
    if not any_emitted:
        out.append("（无数据）")
    out.append("")
```

The three renderers (`render_stocks_batch_profile_as_md`, `render_indices_batch_profile_as_md`, `render_boards_batch_profile_as_md`) call this helper in place of the current single-line `最新: {price} ({pct})`. Headers (`板块画像`, `股票画像`, `指数画像`) stay verbatim.

**Empty case**: when a board has only `price`/`change_pct` (THS realtime sparse during pre-market), at least 2 fields emit. When ALL 12 are `None` (upstream total failure), `_md_quote_block` never gets called because `entry.quote` itself is `None`. The block is **never called with all-None values** by design — the route already guards with `if entry.quote:` before the renderer.

---

## 4. Testing

### 4.1 `tests/test_agent_batch_features.py` updates

Existing test `TestStocksBatchProfile::test_all_aspects_populated` (line 358) pins:

```python
assert e["quote"] == {"price": 100.0, "change_pct": 1.5}
```

This is a strict equality — widening the schema breaks it. **Must update**: expand the assertion to the full 12-field dict (driven by `_make_unified_quote` at line ~339). Three of the new fields (`turnover_rate`, `amplitude`, `volume_ratio`) are not populated by the test fixture, so they stay absent from the expected dict (Pydantic `model_dump()` excludes defaults).

New test classes / cases:

```python
class TestStocksQuoteEnrichment:
    """Pins the 12-field schema + per-source fill rules."""

    def test_full_unified_quote_populates_all_12(self, client, monkeypatch):
        """A complete UnifiedRealtimeQuote → 12-field MinimalQuote."""
        ...

    def test_partial_quote_only_some_fields(self, client, monkeypatch):
        """A UnifiedRealtimeQuote with only price/change_pct → 10 fields null."""
        ...

    def test_boards_only_ths_fields_populated(self, client, monkeypatch):
        """THS board realtime dict → 8 fields populated, 4 fields null."""
        ...

class TestMdRendersAllQuoteFields:
    """Pins the api-reference.md 'No data is dropped' contract for the quote aspect."""

    def test_md_includes_all_populated_quote_fields(self, client, monkeypatch):
        """When 12 fields are populated, all 12 appear in the MD output."""
        ...
```

For `TestStocksBatchProfile::test_kline_failure_isolated` etc. (the existing partial-failure tests), the `quote` assertion `e["quote"] is not None` keeps working (the schema widens but the field is still optional). No update needed there.

### 4.2 Pinned with new tests

- `test_full_unified_quote_populates_all_12` — semantic: schema accepts all 12 from a complete upstream object.
- `test_partial_quote_only_some_fields` — semantic: opportunistic fill; missing attributes stay `null` not error.
- `test_boards_only_ths_fields_populated` — semantic: boards branch uses `.get()` semantics; THS-shaped dict produces the documented 8-field result.
- `test_md_includes_all_populated_quote_fields` — semantic: MD no-drop contract per CLAUDE.md.
- `test_indices_quote_also_enriched` — regression test that the indices handler was also widened (would catch an oversight that only stocks widened).

### 4.3 Out of test scope

- `tests/test_agent_boards_batch_profile.py` already pins "quote shape after boards enrichment" for 8 fields; don't double-pinning, just update assertion.
- `tests/test_agent_endpoints.py::TestFormatMdDataCompleteness` — pins the MD no-drop contract for boards_overlap, stocks_overlap, market-context. Not affected by this change.

---

## 5. Documentation

| File | Section | Change |
|---|---|---|
| `api-reference.md` | `/agent/indices/batch-profile` (line 1620) | Update JSON example; update field reference row `Minimal realtime anchor {price, change_pct}` → list 12 fields. |
| `api-reference.md` | `/agent/stocks/batch-profile` (line 1813) | Same. |
| `api-reference.md` | `/agent/boards/batch-profile` (line 1953) | Same; explicitly note THS doesn't surface `change_amount` / `turnover_pct` / `amplitude` / `volume_ratio`. |
| `CLAUDE.md` | "Agent Batch API" routing table | Update the `quote` description from "极简 quote" to "12-field MinimalQuote (enriched 2026-08-27)". |
| `docs/agent-batch-api-proposal-2026-07-27.md` | Historical proposal | Update only if it specifies the schema. Likely no change needed. |

---

## 6. Risk analysis

### 6.1 Cache — 60s mixed-shape transition window

The cache slot is the same `get_quote_cache` (60s TTLCache) used by every agent endpoint. After deployment but before the 60s expiry, in-flight requests could see a `StockBatchProfileResponse` cached under the old 2-field schema. Mitigations:

- **Best**: brief process restart clears the in-memory cache cleanly.
- **Acceptable**: live with up to 60s of mixed-shape responses. Downstream consumers reading `entry["quote"]["price"]` continue to work; consumers iterating `entry["quote"].items()` see 2-12 fields depending on cache age. None of this breaks Pydantic validation.
- **Document**: mention in the change commit + PR description that the cache self-heals within 60s.

### 6.2 Type mismatch — THS volume as float

Investigation deferred to implementation §3.4. If THS returns float shares, schema loosens to `float | None`. Schema loosening is a **separate contract change**: API consumers iterating `volume` as int would break. Mitigation: emit in MD as `f"{int(v):,}"` for readability but ship the raw float in JSON, with a follow-up task to migrate sources to int consistently.

### 6.3 Index markets — sparse HK / US

`manager.get_index_realtime_quote` for HK / US indices may return a `UnifiedRealtimeQuote` with many `None`s. Not a regression — already happens today for `change_pct` etc. — but now visible across 12 fields instead of 2. Implementation: same `AttributeError` → outer-except → entry-level `errors[]` semantics; partial-failure rules apply. Add an MD test that pins "HK index with sparse quote → only populated fields render; absent = silently hidden".

### 6.4 No new fixture for boards

`_make_unified_quote` in `tests/test_agent_batch_features.py:339` produces a stock-shaped object. Boards tests use a different fixture path (`_BOARD_STOCKS_PATCH`). Implementation needs a new boards-quote fixture (THS dict-shaped) — lightweight, inline-construct.

---

## 7. Out of scope (explicit non-goals)

- No new `DataCapability` flag — `@endpoint_meta(capabilities=[])` stays empty.
- No new fetcher upstream calls — `manager.get_realtime_quote` / `get_index_realtime_quote` / `get_board_realtime` already plumb all 12 fields; we just stop dropping them.
- No new cache key — same `(codes, frequency, days)` signature, but the cached payload is widened (transparent to callers).
- No `boards_overlap` / `stocks_overlap` / `filter-stocks` / `market-stats` / `market-context` — those don't have a `quote` aspect.
- No class-name rename (`MinimalQuote` → `Quote`) — deferred as a search-and-replace follow-up.
- No MD-renderer table-format refactor — keep the bullet list. A table could come later if it proves easier to read.

---

## 8. Implementation plan

Once this design is approved, the next step is the `writing-plans` skill to produce a multi-step implementation plan. The plan will sequence:

1. **Schema** (`schemas.py`) — widen `MinimalQuote`.
2. **Stocks handler** — populate 12 fields from `UnifiedRealtimeQuote`.
3. **Boards handler** — populate 8 from THS dict, investigate volume type.
4. **Indices handler** — populate 12 from `UnifiedRealtimeQuote`.
5. **MD helper** (`_md_quote_block`) — extract shared renderer.
6. **MD renderers** — call helper from the three renderers.
7. **Tests** — update existing assertions; add 4 new tests.
8. **Docs** — `api-reference.md` × 3 sections + `CLAUDE.md` Agent Batch API row.

Each step is independently testable; the steps roughly map to file boundaries.
