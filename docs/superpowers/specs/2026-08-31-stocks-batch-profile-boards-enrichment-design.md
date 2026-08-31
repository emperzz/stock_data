# `/agent/stocks/batch-profile` — Boards Block THS Enrichment

> Spec for closing the gap that opened 2026-08-30 when
> `/stocks/{code}/boards` started live-enriching per-concept THS quote
> data (change_pct / up_count / down_count / limit_up_count /
> limit_down_count / explain / relevance) via
> `_fetch_stock_boards_quote_enrichment` (60s `_stock_boards_quote_cache`).
> Today only that route carries the 7 fields; the
> `/agent/stocks/batch-profile` endpoint reads the persistence layer
> directly and returns 5-field entries. This spec brings the agent
> endpoint to parity by reusing the helper, not duplicating it.

**Date**: 2026-08-31
**Status**: Draft
**Scope**: 1 new helper module (`stock_data/api/_helpers/stock_boards.py`),
2 route-layer rewrites (`api/routes/boards.py` + `api/routes/agent.py`),
1 MD template update (`render_stocks_batch_profile_as_md`), 3 new
agent tests + 1 import-path update across 8 existing ths-enrichment
tests, 2 cross-reference additions in `CLAUDE.md`. No new endpoint,
no new fetcher, no new `DataCapability`, no new cache slot.

---

## 1. Background

`/stocks/{code}/boards` (commit `cca07af`, 2026-08-30) added 7 THS
upstream fields to `StockBoardInfo`:

| Field | Upstream | Type |
|---|---|---|
| `change_pct` | `price_change_ratio_pct` | float \| None |
| `up_count` | `rise_cnt` | int \| None |
| `down_count` | `fall_cnt` | int \| None |
| `limit_up_count` | `up_down_limit_up_num` | int \| None |
| `limit_down_count` | `up_down_limit_down_num` | int \| None |
| `explain` | `explain` | str \| None |
| `relevance` | `weight` (0=普通 / 2=走势最相关) | int \| None |

The live-enrichment helper lives in `boards.py` as
`_fetch_stock_boards_quote_enrichment` (lines 1075-1173 of pre-spec
boards.py), wrapping `manager.get_stock_boards(stock_code, source="ths")`
behind a 60s in-process TTLCache. Three response branches:

1. **Warm THS cache** → 5 legacy fields from persistence + 7 enrichment
   fields merged in.
2. **Cold cache + fetcher has data** → live fetcher's full result IS
   the response data (no persistence writeback; design 2026-08-30).
3. **Non-THS source or all-cold no-fetcher-data** → persistence entries
   flow through unmodified, enrichment fields stay `None`.

`/agent/stocks/batch-profile` (`api/routes/agent.py:870-985`) currently
calls only `stock_board_cache.get_stock_memberships(stock_code,
sources=["ths"], manager=manager)` and returns 5-field entries in
`boards.data[i]`. Agent callers (LLM-side pickers) that need the
per-concept quote envelope — e.g. "筛选出数据中心板块涨幅 ≥ 2% 且涨停家数 ≥ 3 的板块成分股" — currently cannot get it from one call, defeating the
batch-profile's purpose.

The helper exists, the cache slot exists, the upstream contract exists;
this spec only relocates the helper out of a route file (where it's a
peer-private function) into a helpers module where both route files
can import it cleanly.

---

## 2. Goal

`/agent/stocks/batch-profile.boards.data[i]` returns the same 11-field
entry as `/stocks/{code}/boards.data[i]` (5 legacy + 7 enrichment),
shared 60s upstream QPS budget (`_stock_boards_quote_cache`),
identical three-branch merge logic, identical failure semantics.

---

## 3. Architecture — helper relocation

### 3.1 New module

`stock_data/api/_helpers/stock_boards.py` (new file, with
`stock_data/api/_helpers/__init__.py` empty).

```python
"""Stock-board enrichment helpers shared by /stocks/{code}/boards and
/agent/stocks/batch-profile.

Live-fetches THS ``stock_concept_list`` for per-concept quote envelope
(涨跌幅/涨跌家数/涨停跌停家数/概念解析/关联度) and returns it as a
merge-ready dict keyed by THS platecode. Backed by a 60s in-process
TTLCache (``_stock_boards_quote_cache``) shared with the boards route.
"""
```

Function `fetch_stock_boards_quote_enrichment(stock_code, manager)`
(public name, no leading underscore) is a 1:1 move of
`boards.py::_fetch_stock_boards_quote_enrichment` (lines 1075-1173):
docstring, cache key, try/except contract, return tuple — all
unchanged.

### 3.2 `boards.py` — drop the local copy

`stock_data/api/routes/boards.py`:

- Delete lines 1072-1173 (helper + section comment header).
- Add `from ._helpers.stock_boards import fetch_stock_boards_quote_enrichment` near the top of the file.
- In `get_stock_boards` (line 971), replace
  `_fetch_stock_boards_quote_enrichment(stock_code, get_manager())`
  with `fetch_stock_boards_quote_enrichment(stock_code, get_manager())`.

`stock_data/api/cache.py` — update one docstring cross-link
(line 244):

- ``api/routes/boards.py::_fetch_stock_boards_quote_enrichment``
  →
  ``api/_helpers/stock_boards.py::fetch_stock_boards_quote_enrichment``.

The 8 existing tests in `tests/test_stock_boards_ths_enrichment.py`
change their import path only:
`from ...api.routes.boards import _fetch_stock_boards_quote_enrichment`
→
`from ...api._helpers.stock_boards import fetch_stock_boards_quote_enrichment`.
Test bodies unchanged.

### 3.3 `agent.py` — import + use

`stock_data/api/routes/agent.py`:

- Add `from ._helpers.stock_boards import fetch_stock_boards_quote_enrichment` to the import section near other `from .cache import ...` lines.
- Rewrite the boards `try` block in `post_stocks_batch_profile`
  (lines 939-948) to a three-branch merge (see §4.2).

### 3.4 No new cache slot

`_stock_boards_quote_cache` (maxsize=512, ttl=60s) lives in
`stock_data/api/cache.py` and is already imported by `boards.py` as
`get_stock_boards_quote_cache()`. The helper continues to use the same
cache key (`f"stock_boards_quote:{stock_code}"`) — agent calls and
boards-route calls share the 60s window, so the batch-profile fan-out
of N≤5 stocks is bounded to ≤5 cold misses at once (then 0 within TTL).

---

## 4. Data contract — agent boards block

### 4.1 Schema

`StockBatchProfileEntry.boards` (`api/schemas.py:1926`) is currently
`dict | None`. We do NOT tighten it to a typed model — the existing
`{source, data}` shape stays. Each entry in `data` becomes a flat dict
with 11 keys (5 legacy + 7 enrichment):

```python
{
  "code": "881155",
  "name": "数据中心",
  "type": "concept",
  "subtype": "concept",
  "source": "ths",
  "change_pct": 1.23,
  "up_count": 15,
  "down_count": 8,
  "limit_up_count": 2,
  "limit_down_count": 0,
  "explain": "2022年8月23日公司互动回复：…",
  "relevance": 2,
}
```

### 4.2 Three-branch merge

Replaces the current single-branch:

```python
try:
    entries, _cold, _origin = stock_board_cache.get_stock_memberships(
        stock_code=code, sources=["ths"], manager=manager
    )
    boards = {"source": "persistence", "data": entries}
except Exception as exc:
    ...
```

with:

```python
try:
    entries, _cold, _origin = stock_board_cache.get_stock_memberships(
        stock_code=code, sources=["ths"], manager=manager
    )
    fetcher_full_result, enrichment_by_code = fetch_stock_boards_quote_enrichment(
        code, manager
    )
    ths_cached = [e for e in entries if e["source"] == "ths"]
    if ths_cached:
        # warm-cache merge: persistence 5 fields + enrichment 7 fields
        merged = []
        for e in ths_cached:
            base = {k: e.get(k) for k in ("code", "name", "type", "subtype", "source")}
            base.update(enrichment_by_code.get(e["code"], {}))
            merged.append(base)
        boards = {"source": "persistence", "data": merged}
    elif fetcher_full_result:
        # cold-cache fallback: fetcher IS the response (11 fields already)
        boards = {"source": "ths", "data": fetcher_full_result}
    else:
        # fetcher empty / disabled cache / failed: persistence as-is
        boards = {"source": "persistence", "data": entries}
except Exception as exc:
    logger.warning(...)
    errors.append(StockBatchAspectError(aspect="boards", ...))
```

### 4.3 `boards.source` three states

| State | Trigger | `boards.source` | `boards.data[i]` field count |
|---|---|---|---|
| Warm-cache merge | `ths_cached` non-empty | `"persistence"` | 11 |
| Cold-cache fallback | `ths_cached` empty AND `fetcher_full_result` non-empty | `"ths"` | 11 |
| All-cold / fetcher failure | `fetcher_full_result` is None or `[]` | `"persistence"` | 5 (enrichment all None) |

The agent response `ok` flag stays `True` whenever any of
quote/features/info/boards succeeded — fetcher-side failure does NOT
demote `ok`. This matches the boards-route contract (fetcher
exception is WARNING + fields None, not 5xx).

### 4.4 Backward compatibility

- Adding 7 keys to `boards.data[i]` is purely additive. Existing
  clients reading `code/name/type/subtype/source` continue to work.
- `boards.source` was always `"persistence"` for this endpoint; the
  new `"ths"` state is a new value but not a breaking change.
- `boards` itself remains `dict | None` (no schema hardening).

---

## 5. MD rendering — `render_stocks_batch_profile_as_md`

`api/routes/agent.py:1836-1841` currently emits a flat bullet list:

```python
if entry.boards and entry.boards.get("data"):
    out.append("### 所属板块")
    for b in entry.boards["data"]:
        t = b.get("type") or "-"
        out.append(f"- {b.get('code', '?')} ({t}) {b.get('name', '')}")
```

New rendering — a 6-column markdown table, None → "—":

```python
if entry.boards and entry.boards.get("data"):
    out.append("### 所属板块")
    out.append("| 板块 | 涨跌幅 | 上涨/下跌 | 涨停/跌停 | 关联度 | 解析 |")
    out.append("|---|---|---|---|---|---|")
    for b in entry.boards["data"]:
        code = b.get("code", "?")
        name = b.get("name", "")
        type_ = b.get("type", "") or "—"
        cp = _md_pct(b.get("change_pct")) if b.get("change_pct") is not None else "—"
        uc, dc = b.get("up_count"), b.get("down_count")
        up_dn = f"{uc}/{dc}" if (uc is not None and dc is not None) else "—"
        luc, ldc = b.get("limit_up_count"), b.get("limit_down_count")
        lim = f"{luc}/{ldc}" if (luc is not None and ldc is not None) else "—"
        rel = b.get("relevance")
        rel_str = "—" if rel is None else ("走势最相关" if rel == 2 else "普通")
        explain = b.get("explain") or "—"
        out.append(f"| {code} {name} ({type_}) | {cp} | {up_dn} | {lim} | {rel_str} | {explain} |")
    out.append("")
```

`_md_pct` (already in `agent.py`) handles percentage formatting.
This satisfies the CLAUDE.md "MD 数据完整性契约" — every JSON field
in the new entries appears in the MD output (None → "—" preserves
column count, unlike option-A's skip-None-conditionally).

---

## 6. Tests

### 6.1 New cases — `tests/test_agent_batch_features.py`

Three new methods in the existing `TestStocksBatchProfileBoards`
section (or new file if the section doesn't exist — preference is to
extend the existing file):

| Case | Setup | Assertion |
|---|---|---|
| `test_boards_enrichment_warm_cache_merge` | Mock persistence returns 1 entry (code=`881155`, source=`ths`); mock `manager.get_stock_boards` returns 1 entry with 11 fields. | `boards.source == "persistence"`; `len(boards.data) == 1`; entry has 11 keys with values matching fetcher's enrichment; `errors == []`. |
| `test_boards_enrichment_cold_cache_fallback` | Mock persistence returns `[]`; mock `manager.get_stock_boards` returns 2 entries (11 fields each). | `boards.source == "ths"`; `len(boards.data) == 2`; each entry has 11 keys; `errors == []`. |
| `test_boards_enrichment_fetcher_failure` | Mock persistence returns 1 entry; mock `manager.get_stock_boards` raises `DataFetchError`. | `boards.source == "persistence"`; entry has 5 keys (enrichment all absent); `errors == []` (boards aspect NOT in errors — fetcher failure is not a boards failure). |

### 6.2 MD completeness case

Add to `TestFormatMdFeatureCompleteness` (or new section):

`test_md_boards_block_full_field_table` — request with `format=md`,
assert:

- `### 所属板块` header present.
- All 6 columns headers present: `涨跌幅 / 上涨/下跌 / 涨停/跌停 / 关联度 / 解析`.
- For an entry with `change_pct=1.23, up_count=15, down_count=8,
  limit_up_count=2, limit_down_count=0, relevance=2, explain="..."`:
  the rendered row contains `+1.23%`, `15/8`, `2/0`, `走势最相关`.
- For an entry with all enrichment fields `None`: the rendered row
  contains four `—` markers (4 None fields → 4 "—" cells), the
  column count is preserved.

### 6.3 Updated import path

`tests/test_stock_boards_ths_enrichment.py` has 5 reference sites for the
helper (verified via grep 2026-08-31: lines 83, 88, 381, 389, 395, 420):

- **1 direct import** (line 381):
  `from stock_data.api.routes.boards import _fetch_stock_boards_quote_enrichment`
  →
  `from stock_data.api._helpers.stock_boards import fetch_stock_boards_quote_enrichment`.
- **2 direct call sites** (lines 389, 395):
  `_fetch_stock_boards_quote_enrichment(stock_code, fake_mgr)`
  →
  `fetch_stock_boards_quote_enrichment(stock_code, fake_mgr)`.
- **2 `monkeypatch` / `patch.object` sites** (lines 83, 88, 420) — these
  currently patch `_fetch_stock_boards_quote_enrichment` *as an attribute
  of `stock_data.api.routes.boards`* (helper `_patch_enrichment_with`,
  lines 60-90). After the move, the helper lives on
  `stock_data.api._helpers.stock_boards`, not on `boards`. The patch
  must target the new module — change `_patch_enrichment_with` to:

  ```python
  from stock_data.api._helpers import stock_boards as stock_boards_helper
  ...
  return patch.object(
      stock_boards_helper,
      "fetch_stock_boards_quote_enrichment",
      side_effect=RuntimeError("simulated fetcher failure"),
  )
  ```

  This works because `boards.py` re-imports the helper via
  `from ._helpers.stock_boards import fetch_stock_boards_quote_enrichment` — Python's module-level attribute lookup chains through
  the import, so patching the original module's attribute also patches
  what `boards.py` sees when it calls the helper.

  The `patch.object(boards_route, "_fetch_stock_boards_quote_enrichment", side_effect=RuntimeError("boom"))` call at line 420
  (in `test_helper_internal_try_except_swallows_fetcher_error`) also
  needs the same module-target switch.

- Test bodies, assertions, and request/response shapes are otherwise
  unchanged. The 8 cases still pin the same contract.

### 6.4 Pre-flight test run

Before commit: `.venv/Scripts/python.exe -m pytest tests/test_stock_boards_ths_enrichment.py tests/test_agent_batch_features.py -v` must pass.

---

## 7. CLAUDE.md — two cross-reference additions

### 7.1 Agent Batch API table — `/agent/stocks/batch-profile` row

Current row in CLAUDE.md:

> POST /agent/stocks/batch-profile | Per-stock fan-out: quote + 计算特征 + info + boards。1-5 codes, 单 frequency。

Replace with:

> POST /agent/stocks/batch-profile | Per-stock fan-out: quote + 计算特征 + info + boards。1-5 codes, 单 frequency。boards 块带 7 个 THS enrichment 字段 (change_pct/up_count/down_count/limit_up_count/limit_down_count/explain/relevance),与 `/stocks/{code}/boards` 共享 60s `_stock_boards_quote_cache`。

### 7.2 Standardized Data Schema — new bullet

Add a bullet under "Standardized Data Schema" describing the boards
field on the agent endpoint:

> - **`/agent/stocks/batch-profile.boards.data[]`** — 与 `/stocks/{code}/boards` 共享同一份 11 字段 entry 契约 (5 legacy + 7 THS enrichment)。enrichment helper 在 `stock_data/api/_helpers/stock_boards.py::fetch_stock_boards_quote_enrichment`,60s in-process TTLCache (`_stock_boards_quote_cache`,shared with boards route)。`boards.source` 三态: `"persistence"` (warm-cache merge) / `"ths"` (cold-cache fallback) / `"persistence"` (fetcher 失败, enrichment 字段全 None)。`ok` flag 在 fetcher 失败时不变 `True`(仅 persistence 异常才 append `boards` aspect error)。

---

## 8. Files changed

| File | Type | Lines (est.) |
|---|---|---|
| `stock_data/api/_helpers/__init__.py` | new (empty) | 1 |
| `stock_data/api/_helpers/stock_boards.py` | new | ~100 (1:1 move from boards.py) |
| `stock_data/api/routes/boards.py` | edit (delete helper, change import, change 1 call site) | -100 + 1 |
| `stock_data/api/routes/agent.py` | edit (import + rewrite boards try block in `post_stocks_batch_profile` + MD template) | +30 / -10 |
| `tests/test_stock_boards_ths_enrichment.py` | edit (import path + 8 call-site renames) | ~10 lines changed |
| `tests/test_agent_batch_features.py` | edit (3 new boards-enrichment tests + 1 MD completeness test) | +120 |
| `CLAUDE.md` | edit (2 cross-references) | +6 |

Total net: ~+170 / -110.

---

## 9. Risk + 回退

### 9.1 Risk — helper relocation

`_helpers/stock_boards.py` is a brand-new module — no precedent for
`api/_helpers/` in the codebase. To reduce blast radius:

- The helper is `1:1` move (docstring, body, return tuple, try/except
  contract all preserved verbatim).
- The 8 existing tests assert behavior, not location. Switching their
  import path is the only change needed; if the move accidentally
  breaks behavior, those tests will fail loudly.

### 9.2 Risk — agent boards contract change

- 7 new keys on `boards.data[i]` — no client breaking change.
- New `"ths"` value for `boards.source` — additive.

### 9.3 Risk — MD output volume

The 6-column table per entry makes the MD larger (vs. the prior
bullet list). For batch-profile with N=5 stocks × M=~10 boards each,
MD output grows by ~6 lines per board ≈ +300 lines worst case. Not a
concern for the use case (LLM agent consumes this; larger MD = better
context), but worth noting.

### 9.4 回退

If helper relocation introduces a regression in boards.py:

1. Revert `boards.py` to keep the inline helper.
2. Keep `_helpers/stock_boards.py` (it's a no-op import from
   `agent.py`'s perspective once boards.py reverts).

If the agent-side merge logic is wrong:

1. Revert `agent.py` boards `try` to the single-branch call.
2. Keep helper relocation (boards.py still works).

Either rollback is a single-file revert; no migration needed.

---

## 10. Out of scope

- **`/agent/stocks/board-overlap`** — already calls
  `stock_board_cache.get_stock_memberships(source='ths')` and returns
  `{code, name, type}` only (not enrichment fields). Out of scope per
  spec focus; if needed, follow-up spec.
- **`/agent/indices/batch-profile` and `/agent/boards/batch-profile`** —
  different boards semantics; not in scope.
- **`/agent/boards/filter-stocks`** — operates on a single board's
  constituents; current payload shape is unaffected by this change.
- **Hardcoded `sources=["ths"]`** — keeping as-is per A1+a. Future
  expansion to multi-source requires a separate spec.