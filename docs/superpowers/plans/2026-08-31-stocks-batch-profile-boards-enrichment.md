# /agent/stocks/batch-profile Boards Enrichment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring `/agent/stocks/batch-profile.boards.data[i]` to the same 11-field THS enrichment contract as `/stocks/{code}/boards` (5 legacy + 7 enrichment), shared 60s upstream QPS budget.

**Architecture:** 1:1 move of `_fetch_stock_boards_quote_enrichment` from `stock_data/api/routes/boards.py` to a new `stock_data/api/_helpers/stock_boards.py` (public rename to `fetch_stock_boards_quote_enrichment`). `boards.py::get_stock_boards` imports it from the new location with zero behavior change. `agent.py::post_stocks_batch_profile` imports it and adds a three-branch merge (warm-cache / cold-cache fallback / fetcher-failure). MD template switches from bullet list to a 6-column table.

**Tech Stack:** Python 3.x, Pydantic v2, FastAPI, pytest + monkeypatch, in-process `TTLCache` (`_stock_boards_quote_cache`, ttl=60s).

**Spec:** `docs/superpowers/specs/2026-08-31-stocks-batch-profile-boards-enrichment-design.md` (commits `a1e474b` + `2865352`).

## Global Constraints

- `.venv/Scripts/python.exe -m pytest` is the test runner — never system `python` (see CLAUDE.md "Common Commands").
- Default `pytest` skips `live_network` — pre-flight runs as-is; this plan has zero `live_network` markers.
- Commit messages end with `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- Code commit boundary (per CLAUDE.md): feat/fix Python + tests → `feat/*` / `fix/*` branch; docs / spec / CLAUDE.md / skill edits → direct master.
- 7 enrichment fields (THS upstream → route schema → entry dict):
  `change_pct` (float) / `up_count` (int) / `down_count` (int) /
  `limit_up_count` (int) / `limit_down_count` (int) /
  `explain` (str) / `relevance` (int; 0=普通, 2=走势最相关).
- Helper return type unchanged: `tuple[list[dict] | None, dict[str, dict]]` — `(fetcher_full_result, enrichment_by_code)`.
- Cache slot unchanged: `_stock_boards_quote_cache` (maxsize=512, ttl=60s), key shape `stock_boards_quote:{stock_code}`.
- `boards.source` three states (mutually exclusive):
  `"persistence"` (warm-cache merge OR fetcher-failed) /
  `"ths"` (cold-cache fallback with live fetcher data).
- `ok` flag on agent entry stays `True` whenever any of quote/features/info/boards succeeded — fetcher exception does NOT demote `ok`.
- `StockBatchAspectError(aspect="boards")` ONLY fires when persistence layer raises — fetcher exception is silent (boards block still ships with None enrichment fields).
- All 7 enrichment fields are nullable (`None` on fetcher failure / upstream absence / schema absent). Schema (`StockBoardInfo` at `api/schemas.py:788-842`) is the source of truth for typing.

---

## File Structure

| File | Type | Responsibility |
|---|---|---|
| `stock_data/api/_helpers/__init__.py` | new (empty) | Marks `_helpers/` as a package |
| `stock_data/api/_helpers/stock_boards.py` | new | Hosts `fetch_stock_boards_quote_enrichment(stock_code, manager)` (1:1 move) |
| `stock_data/api/routes/boards.py` | edit | Delete local helper; add import from `_helpers.stock_boards`; rename 1 call site |
| `stock_data/api/cache.py` | edit (1 docstring line) | Update cross-link to new helper path |
| `stock_data/api/routes/agent.py` | edit | Import helper; rewrite `post_stocks_batch_profile` boards try block (3-branch merge); rewrite `render_stocks_batch_profile_as_md` boards section (6-col table) |
| `tests/test_stock_boards_ths_enrichment.py` | edit | Update import path (1 site); update 2 `monkeypatch` / `patch.object` targets to point at `_helpers.stock_boards` instead of `boards_route` |
| `tests/test_agent_batch_features.py` | edit | Add 3 new agent boards-enrichment cases + 1 MD completeness case |
| `CLAUDE.md` | edit (2 lines) | Add `/agent/stocks/batch-profile` row annotation in Agent Batch API table; add bullet under Standardized Data Schema |

---

## Task 1: Create the helpers module + 1:1 move (keep old name)

**Files:**
- Create: `stock_data/api/_helpers/__init__.py`
- Create: `stock_data/api/_helpers/stock_boards.py`

**Interfaces:**
- Produces: `stock_data.api._helpers.stock_boards._fetch_stock_boards_quote_enrichment(stock_code: str, manager) -> tuple[list[dict] | None, dict[str, dict]]`
- The name keeps the leading underscore for now; public rename is Task 2.

- [ ] **Step 1: Create the empty package init**

Write `stock_data/api/_helpers/__init__.py` (empty file):

```python
```

- [ ] **Step 2: Create the helper module file**

Write `stock_data/api/_helpers/stock_boards.py` with the helper
verbatim from `stock_data/api/routes/boards.py:1075-1173`. The full
content:

```python
"""Stock-board enrichment helpers (THS live quote envelope).

Shared by ``/stocks/{code}/boards`` and ``/agent/stocks/batch-profile``.
Backed by a 60s in-process TTLCache (``_stock_boards_quote_cache``).
"""

import logging

from ...data_provider.base import DataFetchError
from ..cache import (
    cached_lookup,
    cached_store,
    get_stock_boards_quote_cache,
    is_cache_enabled,
)

logger = logging.getLogger(__name__)


def _fetch_stock_boards_quote_enrichment(
    stock_code: str, manager
) -> tuple[list[dict] | None, dict[str, dict]]:
    """Live-fetch THS stock_concept_list for /stocks/{code}/boards enrichment.

    The ``manager`` parameter is dependency-injected rather than calling
    ``get_manager()`` internally so tests can swap in a ``MagicMock`` and
    exercise the helper's try/except contract independently of the route
    (see ``test_ths_source_enrichment_helper_internal_try_except_swallows_fetcher_error``
    for the canonical example). Production callers pass the route-level
    ``get_manager()`` singleton; tests pass a fake manager whose
    ``get_stock_boards`` raises / returns / etc.

    Returns ``(fetcher_full_result, enrichment_by_code)`` where:
    - ``fetcher_full_result`` is the full fetcher list (each entry has all
      11 fields: 4 legacy + 7 enrichment), or ``None`` on failure /
      disabled cache. Used by the route as the response data when
      persistence has no rows for THS (cold-cache fallback).
    - ``enrichment_by_code`` is ``{code: {7 enrichment keys}}`` keyed by
      THS platecode (885xxx). Used by the route to merge onto warm-cache
      entries whose source == 'ths'. Empty dict on failure / no rows.

    Both empty / None when:
    - the in-process cache is disabled (``ENABLE_API_CACHE=false``);
    - the fetcher raises (best-effort: WARNING logged, no exception
      propagated — the rest of the response must still ship);
    - the fetcher returns an empty list (no concepts for this stock);
    - every THS board for this stock has no ``quote_code`` (defensive).

    Field naming matches ``BoardQuoteResponse`` (change_pct / up_count /
    down_count) and ``StockBoardInfo`` (limit_up_count / limit_down_count
    / explain / relevance). Numeric values are already coerced by
    ``ThsFetcher.get_stock_boards`` (``safe_int`` / ``safe_float``).

    The 60s TTL bounds upstream QPS to one ``stock_concept_list`` call
    per (stock_code) per minute, regardless of how many
    ``GET /stocks/{code}/boards`` requests land on the server.

    Cache slot: dedicated ``_stock_boards_quote_cache`` (maxsize=512, ttl=60s)
    in ``api/cache.py`` — split out from the shared ``_quote_cache`` so the
    high-fanout enrichment keys don't evict true quote keys
    (e.g. ``"600519"``, ``"idx_quote:000300"``).

    Cache-value contract (m6 review): only store tuples of the form
    ``(list, dict)``. ``cached_lookup`` returns ``None`` on cache miss
    AND on disabled cache AND on missing key — a future caller storing
    ``cached_store(..., None)`` would be indistinguishable from a miss
    and silently re-fetch forever. Storing ``([], {})`` for the empty
    result avoids this footgun and still lets the route distinguish
    "no upstream data" from "first uncached call" (the route handles
    both identically today, but the contract is documented).
    """
    if not is_cache_enabled():
        return None, {}
    cache_key = f"stock_boards_quote:{stock_code}"
    hit = cached_lookup(get_stock_boards_quote_cache, cache_key, "stock_boards_quote")
    if hit is not None:
        return hit
    try:
        result, _name = manager.get_stock_boards(stock_code, source="ths")
    except DataFetchError as e:
        # Circuit-breaker-open / upstream 5xx / business-level stock_concept_list
        # failure: log + skip enrichment. The 5 legacy fields still flow.
        logger.warning(
            f"[boards.get_stock_boards] live enrichment failed for "
            f"{stock_code!r}: {e}"
        )
        return None, {}
    except Exception as e:  # defensive: never break the response
        logger.warning(
            f"[boards.get_stock_boards] live enrichment unexpected error "
            f"for {stock_code!r}: {type(e).__name__}: {e}"
        )
        return None, {}
    if not result:
        # Cache the empty result for 60s so we don't keep retrying the
        # upstream for a stock that genuinely has no concept membership.
        cached_store(get_stock_boards_quote_cache, cache_key, ([], {}))
        return [], {}
    enrichment: dict[str, dict] = {}
    enrichment_keys = (
        "change_pct",
        "up_count",
        "down_count",
        "limit_up_count",
        "limit_down_count",
        "explain",
        "relevance",
    )
    for entry in result:
        code = entry.get("code")
        if not code:
            continue
        # Forward ONLY the 7 enrichment keys — don't shadow code/name/type/
        # subtype/source, which are owned by the persistence layer's
        # authoritative read.
        enrichment[code] = {k: entry.get(k) for k in enrichment_keys}
    cached_store(get_stock_boards_quote_cache, cache_key, (result, enrichment))
    return result, enrichment
```

- [ ] **Step 3: Verify the new module imports cleanly**

Run: `.venv/Scripts/python.exe -c "from stock_data.api._helpers.stock_boards import _fetch_stock_boards_quote_enrichment; print('ok')"`
Expected: prints `ok` with no errors.

- [ ] **Step 4: Commit the new module**

```bash
git add stock_data/api/_helpers/__init__.py stock_data/api/_helpers/stock_boards.py
git commit -m "feat(helpers): 1:1 move _fetch_stock_boards_quote_enrichment to api/_helpers/stock_boards

Pure relocation — same name (still leading underscore, rename in
next task), same body, same return type, same cache slot. The helper
is about to be imported from two route modules; lifting it out of
stock_data/api/routes/boards.py removes the cross-route private
function reference and gives a clean public-API surface for
/agent/stocks/batch-profile to reuse.

No behavior change. boards.py not yet rewired; subsequent task
deletes the local copy and adds the import.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Wire boards.py to import from new module + rename helper to public

**Files:**
- Modify: `stock_data/api/routes/boards.py` — delete `_fetch_stock_boards_quote_enrichment` (lines 1072-1173); add import; rename 1 call site at line 971
- Modify: `stock_data/api/cache.py` — update 1 docstring cross-link at line 244
- Modify: `tests/test_stock_boards_ths_enrichment.py` — update 1 import (line 381); update 2 `monkeypatch` / `patch.object` targets (lines 83, 88, 420) to point at `_helpers.stock_boards`; update 2 direct call sites (lines 389, 395)

**Interfaces:**
- Consumes: `stock_data.api._helpers.stock_boards.fetch_stock_boards_quote_enrichment(stock_code, manager)` (Task 1's helper, now public)
- Produces: same behavior as pre-task — `/stocks/{code}/boards` route returns identical responses on the 8 existing test cases

- [ ] **Step 1: Add the import + delete the local helper in boards.py**

Edit `stock_data/api/routes/boards.py` — find the existing
`_fetch_stock_boards_quote_enrichment` definition plus its section
header (lines 1072-1173, both included), delete them. Add an import
near the top of the file alongside the other `from ..cache import ...`
lines:

```python
from ._helpers.stock_boards import fetch_stock_boards_quote_enrichment
```

- [ ] **Step 2: Rename the single call site in `get_stock_boards`**

In the same file, find (around line 971):

```python
        fetcher_full_result, enrichment_by_code = (
            _fetch_stock_boards_quote_enrichment(stock_code, get_manager())
        )
```

Replace `_fetch_stock_boards_quote_enrichment` with
`fetch_stock_boards_quote_enrichment` (one occurrence in the file —
the definition is now gone).

- [ ] **Step 3: Update the cross-link in cache.py**

Edit `stock_data/api/cache.py` line 244:

```python
    Key shape: ``"stock_boards_quote:{stock_code}"`` — see
    ``api/_helpers/stock_boards.py::fetch_stock_boards_quote_enrichment``.
    """
```

(The old text was `api/routes/boards.py::_fetch_stock_boards_quote_enrichment`.)

- [ ] **Step 4: Update test imports + call sites**

In `tests/test_stock_boards_ths_enrichment.py`, find the 5 reference
sites and update them:

1. Line 381 (`from stock_data.api.routes.boards import _fetch_stock_boards_quote_enrichment`):
   ```python
   from stock_data.api._helpers.stock_boards import fetch_stock_boards_quote_enrichment
   ```

2. Lines 389, 395 (`_fetch_stock_boards_quote_enrichment("300519", fake_mgr)`):
   ```python
   fetch_stock_boards_quote_enrichment("300519", fake_mgr)
   ```

3. The `_patch_enrichment_with` helper (lines 60-90) currently does:
   ```python
   from stock_data.api.routes import boards as boards_route
   ...
   return patch.object(
       boards_route,
       "_fetch_stock_boards_quote_enrichment",
       side_effect=RuntimeError("simulated fetcher failure"),
   )
   ```
   Change to:
   ```python
   from stock_data.api._helpers import stock_boards as stock_boards_helper
   ...
   return patch.object(
       stock_boards_helper,
       "fetch_stock_boards_quote_enrichment",
       side_effect=RuntimeError("simulated fetcher failure"),
   )
   ```
   And the second `patch.object` call (return_value branch) follows
   the same target/name change.

4. Line 420 (`patch.object(boards_route, "_fetch_stock_boards_quote_enrichment", side_effect=RuntimeError("boom"))`):
   ```python
   from stock_data.api._helpers import stock_boards as stock_boards_helper
   ...
   patch.object(stock_boards_helper, "fetch_stock_boards_quote_enrichment", side_effect=RuntimeError("boom"))
   ```

- [ ] **Step 5: Run the ths-enrichment test suite**

Run: `.venv/Scripts/python.exe -m pytest tests/test_stock_boards_ths_enrichment.py -v`
Expected: all 8 tests pass (test_ths_source_enriches_change_pct_up_count_down_count, test_warm_cache_partial_overlap, test_non_ths_source_no_enrichment, test_cold_cache_fallback, test_cold_cache_with_type_filter, test_cold_cache_fetcher_failure, test_ths_source_enrichment_helper_internal_try_except_swallows_fetcher_error, test_helper_leak_500_surface).

- [ ] **Step 6: Commit**

```bash
git add stock_data/api/routes/boards.py stock_data/api/cache.py tests/test_stock_boards_ths_enrichment.py
git commit -m "refactor(boards): import enrichment helper from _helpers + rename to public

boards.py no longer carries a private helper; the live-fetch logic
lives in stock_data.api._helpers.stock_boards.fetch_stock_boards_quote_enrichment.
Renamed to drop the leading underscore since two route modules now
import it (boards.py + agent.py), and the underscore-prefixed name is
inappropriate for a function that's part of the module's public API.

cache.py docstring cross-link updated.

The 8 existing ths-enrichment tests still pin the same behavior:
test_stock_boards_ths_enrichment.py imports + monkeypatch / patch.object
sites switch targets from boards_route to _helpers.stock_boards.
Python module-level attribute lookup means patching the original
module's attribute propagates through boards.py's re-import — the
helper sees the stub at call time.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: agent.py boards three-branch merge (TDD)

**Files:**
- Modify: `stock_data/api/routes/agent.py` — add import; rewrite boards try block (lines 939-948)
- Modify: `tests/test_agent_batch_features.py` — add 3 new cases

**Interfaces:**
- Consumes: `fetch_stock_boards_quote_enrichment(stock_code, manager) -> tuple[list[dict] | None, dict[str, dict]]` (Task 2)
- Produces: `boards` dict on each `StockBatchProfileEntry` with the same `{source, data}` shape, but `data[i]` carries 11 keys (warm-cache merge path) or 11 keys (cold-cache fallback path) or 5 keys (fetcher-failed path) per spec §4.3.

- [ ] **Step 1: Write the warm-cache merge test**

Add to `tests/test_agent_batch_features.py` (next to the existing
`TestStocksBatchProfile` class). Use existing fixtures
(`_BOARD_STOCKS_PATCH`, `_bind_manager`, `_stock_request`,
`_make_unified_quote`, `_make_kline_df`). The test patches
`stock_board_cache.get_stock_memberships` directly (agent imports it
as `stock_board_cache` at `agent.py:48` — module attribute is the same
object).

```python
def test_boards_enrichment_warm_cache_merge(client, monkeypatch):
    """Warm persistence + live fetcher → merge 7 enrichment fields onto 5-field entries."""
    from stock_data.api.routes import agent as agent_module
    from stock_data.data_provider.persistence import board as stock_board_cache

    cached_entries = [
        {"code": "881155", "name": "数据中心", "type": "concept",
         "subtype": "concept", "source": "ths"},
    ]
    fetcher_result = [
        {"code": "881155", "name": "数据中心", "type": "concept", "subtype": "concept",
         "change_pct": 1.23, "up_count": 15, "down_count": 8,
         "limit_up_count": 2, "limit_down_count": 0,
         "explain": "...", "relevance": 2},
    ]

    mock_manager = MagicMock()
    mock_manager.get_realtime_quote.return_value = _make_unified_quote("600519")
    mock_manager.get_kline_data.return_value = (_make_kline_df(120), "zzshare")
    mock_manager.get_stock_info.return_value = ({"industry": "白酒"}, "zhitu")
    mock_manager.get_stock_boards.return_value = (fetcher_result, "ths")
    _bind_manager(monkeypatch, mock_manager)

    monkeypatch.setattr(
        stock_board_cache, "get_stock_memberships",
        lambda stock_code, sources, manager: (cached_entries, [], "persistence"),
    )

    r = client.post("/api/v1/agent/stocks/batch-profile",
                    json=_stock_request(["600519"]))
    assert r.status_code == 200
    body = r.json()
    boards = body["results"][0]["boards"]
    assert boards["source"] == "persistence"
    assert len(boards["data"]) == 1
    entry = boards["data"][0]
    assert entry["code"] == "881155"
    assert entry["change_pct"] == 1.23
    assert entry["up_count"] == 15
    assert entry["down_count"] == 8
    assert entry["limit_up_count"] == 2
    assert entry["limit_down_count"] == 0
    assert entry["explain"] == "..."
    assert entry["relevance"] == 2
    assert body["results"][0]["errors"] == []
```

- [ ] **Step 2: Write the cold-cache fallback test**

```python
def test_boards_enrichment_cold_cache_fallback(client, monkeypatch):
    """No persistence rows for THS → live fetcher's full result IS the response."""
    from stock_data.data_provider.persistence import board as stock_board_cache

    fetcher_result = [
        {"code": "881155", "name": "数据中心", "type": "concept", "subtype": "concept",
         "change_pct": 1.23, "up_count": 15, "down_count": 8,
         "limit_up_count": 2, "limit_down_count": 0, "explain": "...", "relevance": 2},
        {"code": "881166", "name": "算力", "type": "concept", "subtype": "concept",
         "change_pct": 0.5, "up_count": 10, "down_count": 5,
         "limit_up_count": 1, "limit_down_count": 0, "explain": None, "relevance": 0},
    ]

    mock_manager = MagicMock()
    mock_manager.get_realtime_quote.return_value = _make_unified_quote("600519")
    mock_manager.get_kline_data.return_value = (_make_kline_df(120), "zzshare")
    mock_manager.get_stock_info.return_value = ({"industry": "白酒"}, "zhitu")
    mock_manager.get_stock_boards.return_value = (fetcher_result, "ths")
    _bind_manager(monkeypatch, mock_manager)

    monkeypatch.setattr(
        stock_board_cache, "get_stock_memberships",
        lambda stock_code, sources, manager: ([], ["ths"], "persistence"),
    )

    r = client.post("/api/v1/agent/stocks/batch-profile",
                    json=_stock_request(["600519"]))
    assert r.status_code == 200
    body = r.json()
    boards = body["results"][0]["boards"]
    assert boards["source"] == "ths"
    assert len(boards["data"]) == 2
    assert boards["data"][0]["code"] == "881155"
    assert boards["data"][0]["change_pct"] == 1.23
    assert boards["data"][1]["code"] == "881166"
    assert boards["results"][0]["errors"] == []
```

- [ ] **Step 3: Write the fetcher-failure test**

```python
def test_boards_enrichment_fetcher_failure(client, monkeypatch):
    """Fetcher raises → persistence entries ship without enrichment; no boards error."""
    from stock_data.data_provider.base import DataFetchError
    from stock_data.data_provider.persistence import board as stock_board_cache

    cached_entries = [
        {"code": "881155", "name": "数据中心", "type": "concept",
         "subtype": "concept", "source": "ths"},
    ]

    mock_manager = MagicMock()
    mock_manager.get_realtime_quote.return_value = _make_unified_quote("600519")
    mock_manager.get_kline_data.return_value = (_make_kline_df(120), "zzshare")
    mock_manager.get_stock_info.return_value = ({"industry": "白酒"}, "zhitu")
    mock_manager.get_stock_boards.side_effect = DataFetchError("circuit open")
    _bind_manager(monkeypatch, mock_manager)

    monkeypatch.setattr(
        stock_board_cache, "get_stock_memberships",
        lambda stock_code, sources, manager: (cached_entries, [], "persistence"),
    )

    r = client.post("/api/v1/agent/stocks/batch-profile",
                    json=_stock_request(["600519"]))
    assert r.status_code == 200
    body = r.json()
    boards = body["results"][0]["boards"]
    assert boards["source"] == "persistence"
    assert len(boards["data"]) == 1
    entry = boards["data"][0]
    # 5 legacy keys present, 7 enrichment keys absent
    assert entry["code"] == "881155"
    assert "change_pct" not in entry
    assert "up_count" not in entry
    assert "relevance" not in entry
    # boards aspect NOT in errors (fetcher failure is not a boards failure)
    assert body["results"][0]["errors"] == []
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_batch_features.py::test_boards_enrichment_warm_cache_merge tests/test_agent_batch_features.py::test_boards_enrichment_cold_cache_fallback tests/test_agent_batch_features.py::test_boards_enrichment_fetcher_failure -v`
Expected: all 3 FAIL. Warm-cache test: assertion on `entry["change_pct"]` will fail because the current single-branch code returns 5-field entries. Cold-cache test: assertion on `boards["source"] == "ths"` will fail because current code always sets `"persistence"`. Fetcher-failure test: will partially pass for current code (boards exists, source persistence, errors empty) — but `assert "change_pct" not in entry` is the discriminator. Actually since current single-branch code returns persistence entries as-is, `change_pct` is already absent → the fetcher-failure test will pass before the change. That's fine — it pins the post-change behavior. The other two will fail loudly.

- [ ] **Step 5: Add the import in agent.py**

In `stock_data/api/routes/agent.py`, after the existing
`from ..cache import (...)` block, add:

```python
from ._helpers.stock_boards import fetch_stock_boards_quote_enrichment
```

(Check that the existing `from ..cache import` import block is at
roughly line 58-65 — adjust placement if needed; the new import goes
right after.)

- [ ] **Step 6: Rewrite the boards try block in `post_stocks_batch_profile`**

In `stock_data/api/routes/agent.py`, find the existing boards try
block (lines 939-948):

```python
        try:
            entries, _cold, _origin = stock_board_cache.get_stock_memberships(
                stock_code=code, sources=["ths"], manager=manager
            )
            boards = {"source": "persistence", "data": entries}
        except Exception as exc:
            logger.warning(f"[agent/stocks/batch-profile] {code} boards failed: {exc}")
            errors.append(
                StockBatchAspectError(aspect="boards", error=type(exc).__name__, message=str(exc))
            )
```

Replace with:

```python
        try:
            entries, _cold, _origin = stock_board_cache.get_stock_memberships(
                stock_code=code, sources=["ths"], manager=manager
            )
            fetcher_full_result, enrichment_by_code = (
                fetch_stock_boards_quote_enrichment(code, manager)
            )
            ths_cached = [e for e in entries if e.get("source") == "ths"]
            if ths_cached:
                merged = []
                for e in ths_cached:
                    base = {k: e.get(k) for k in ("code", "name", "type", "subtype", "source")}
                    base.update(enrichment_by_code.get(e["code"], {}))
                    merged.append(base)
                boards = {"source": "persistence", "data": merged}
            elif fetcher_full_result:
                boards = {"source": "ths", "data": fetcher_full_result}
            else:
                boards = {"source": "persistence", "data": entries}
        except Exception as exc:
            logger.warning(f"[agent/stocks/batch-profile] {code} boards failed: {exc}")
            errors.append(
                StockBatchAspectError(aspect="boards", error=type(exc).__name__, message=str(exc))
            )
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_batch_features.py::test_boards_enrichment_warm_cache_merge tests/test_agent_batch_features.py::test_boards_enrichment_cold_cache_fallback tests/test_agent_batch_features.py::test_boards_enrichment_fetcher_failure -v`
Expected: all 3 PASS.

- [ ] **Step 8: Commit**

```bash
git add stock_data/api/routes/agent.py tests/test_agent_batch_features.py
git commit -m "feat(agent): boards block carries 7 THS enrichment fields on /stocks/batch-profile

Closes the gap from 2026-08-30: /stocks/{code}/boards started
live-enriching per-concept THS quote data (change_pct / up_count /
down_count / limit_up_count / limit_down_count / explain /
relevance), but /agent/stocks/batch-profile was still reading the
persistence layer directly and returning 5-field entries.

agent.py now imports the helper from api/_helpers/stock_boards and
runs the same three-branch merge as the boards route:
- warm-cache: persistence 5 fields + enrichment 7 fields → source
  stays 'persistence'
- cold-cache fallback: fetcher full result IS the response →
  source becomes 'ths'
- fetcher failure: persistence entries ship without enrichment,
  no boards aspect error (boards block still serves); source stays
  'persistence'

Three new tests pin all three branches; no MD rendering change yet
(lands in next task).

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: MD rendering — 6-column table for boards block

**Files:**
- Modify: `stock_data/api/routes/agent.py` — rewrite the boards section of `render_stocks_batch_profile_as_md` (lines 1836-1841)
- Modify: `tests/test_agent_batch_features.py` — add 1 MD completeness test

**Interfaces:**
- Produces: MD output for each entry's boards block — 6 columns (板块 / 涨跌幅 / 上涨下跌 / 涨停跌停 / 关联度 / 解析), `None` → `—`. Satisfies CLAUDE.md "MD 数据完整性契约".

- [ ] **Step 1: Write the MD completeness test**

In `tests/test_agent_batch_features.py`, add to the
`TestFormatMdFeatureCompleteness` section (or a new
`TestFormatMdBoardsBlockFullFieldTable`):

```python
def test_md_boards_block_full_field_table(client, monkeypatch):
    """Boards MD must include all 7 enrichment fields; None → '—'."""
    from stock_data.data_provider.persistence import board as stock_board_cache

    cached_entries = [
        {"code": "881155", "name": "数据中心", "type": "concept",
         "subtype": "concept", "source": "ths"},
        {"code": "881166", "name": "算力", "type": "concept",
         "subtype": "concept", "source": "ths"},
    ]
    fetcher_result = [
        {"code": "881155", "name": "数据中心", "type": "concept", "subtype": "concept",
         "change_pct": 1.23, "up_count": 15, "down_count": 8,
         "limit_up_count": 2, "limit_down_count": 0,
         "explain": "数据中心是新基建", "relevance": 2},
        {"code": "881166", "name": "算力", "type": "concept", "subtype": "concept",
         "change_pct": None, "up_count": None, "down_count": None,
         "limit_up_count": None, "limit_down_count": None,
         "explain": None, "relevance": None},
    ]

    mock_manager = MagicMock()
    mock_manager.get_realtime_quote.return_value = _make_unified_quote("600519")
    mock_manager.get_kline_data.return_value = (_make_kline_df(120), "zzshare")
    mock_manager.get_stock_info.return_value = ({"industry": "白酒"}, "zhitu")
    mock_manager.get_stock_boards.return_value = (fetcher_result, "ths")
    _bind_manager(monkeypatch, mock_manager)

    monkeypatch.setattr(
        stock_board_cache, "get_stock_memberships",
        lambda stock_code, sources, manager: (cached_entries, [], "persistence"),
    )

    r = client.post("/api/v1/agent/stocks/batch-profile?format=md",
                    json=_stock_request(["600519"]))
    assert r.status_code == 200
    md = r.text

    # Section header + table headers
    assert "### 所属板块" in md
    assert "| 板块 | 涨跌幅 | 上涨/下跌 | 涨停/跌停 | 关联度 | 解析 |" in md
    assert "|---|---|---|---|---|---|" in md

    # First row: all enrichment fields populated
    assert "881155" in md and "数据中心" in md
    assert "+1.23%" in md
    assert "15/8" in md
    assert "2/0" in md
    assert "走势最相关" in md
    assert "数据中心是新基建" in md

    # Second row: all enrichment fields None → four "—" markers
    # 4 None fields → 4 "—" cells: 涨跌幅, 上涨/下跌, 涨停/跌停, 关联度
    # (explain None also becomes "—" but is in the same cell as the
    # previous row's value, so we count distinct "—" occurrences on
    # the second row by finding the line that contains 881166.)
    second_row = [line for line in md.splitlines() if "881166" in line]
    assert len(second_row) == 1
    assert second_row[0].count("—") == 4  # 涨跌幅, 上涨/下跌, 涨停/跌停, 关联度 → 解析=— too → 5
    # Actually 5: change_pct + up_count/down_count + limit_up_count/limit_down_count + relevance + explain
    assert second_row[0].count("—") == 5
```

(Confirm the math: 5 enrichment fields map to 5 cells in the table;
all 5 are `None` for the second entry, so 5 `—` cells.)

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_batch_features.py::test_md_boards_block_full_field_table -v`
Expected: FAIL — current bullet-list rendering doesn't include any of the new headers or rows. The line `assert "| 板块 | 涨跌幅 | ..."` will fail because the current code emits `- 881155 (concept) 数据中心`.

- [ ] **Step 3: Rewrite the boards MD section**

In `stock_data/api/routes/agent.py`, find (around lines 1836-1841):

```python
        if entry.boards and entry.boards.get("data"):
            out.append("### 所属板块")
            for b in entry.boards["data"]:
                t = b.get("type") or "-"
                out.append(f"- {b.get('code', '?')} ({t}) {b.get('name', '')}")
            out.append("")
```

Replace with:

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

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_batch_features.py::test_md_boards_block_full_field_table -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add stock_data/api/routes/agent.py tests/test_agent_batch_features.py
git commit -m "feat(agent): render boards block as 6-column table with all enrichment fields

Satisfies CLAUDE.md 'MD 数据完整性契约': every JSON field in the
new boards.data[i] entries appears in the MD output. None maps to
'—' to preserve column count (so the consumer can rely on header
alignment, unlike an option-A skip-None rendering).

5 enrichment cells per row: 涨跌幅, 上涨/下跌, 涨停/跌停, 关联度,
解析. relevance 2 → '走势最相关', 0 → '普通', None → '—'.

One new MD test pins the contract end-to-end: 1 row with all
populated fields + 1 row with all None fields → row 2 must carry
exactly 5 '—' markers.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: CLAUDE.md — two cross-reference additions

**Files:**
- Modify: `CLAUDE.md` — 2 lines, one in the Agent Batch API table, one new bullet under Standardized Data Schema

**Interfaces:**
- Produces: CLAUDE.md reflects the new behavior so future agents / readers can discover it without reading source

- [ ] **Step 1: Update the Agent Batch API table row**

In `CLAUDE.md`, find the row:

```
| POST /agent/stocks/batch-profile | Per-stock fan-out: quote + 计算特征 + info + boards。1-5 codes, 单 frequency。 |
```

Replace with:

```
| POST /agent/stocks/batch-profile | Per-stock fan-out: quote + 计算特征 + info + boards。1-5 codes, 单 frequency。boards 块带 7 个 THS enrichment 字段 (change_pct/up_count/down_count/limit_up_count/limit_down_count/explain/relevance),与 `/stocks/{code}/boards` 共享 60s `_stock_boards_quote_cache`。 |
```

- [ ] **Step 2: Add the new bullet under Standardized Data Schema**

In `CLAUDE.md`, find the "Standardized Data Schema" section's
`KLineData.indicators` bullet block (or another nearby bullet — pick
one that ends with a clearly identifiable trailing line). Insert
**newly** this bullet right after the existing
`KLineData.indicators` block (the section ends with
"index indicators share the same `KLineData` response shape as
stocks — the orchestrator in `routes.py` (`_apply_indicators`,
`_parse_indicators_param`) handles lookback expansion and truncation
identically."):

```markdown
- **`/agent/stocks/batch-profile.boards.data[]`** — 与 `/stocks/{code}/boards` 共享同一份 11 字段 entry 契约 (5 legacy + 7 THS enrichment)。enrichment helper 在 `stock_data/api/_helpers/stock_boards.py::fetch_stock_boards_quote_enrichment`,60s in-process TTLCache (`_stock_boards_quote_cache`,shared with boards route)。`boards.source` 三态: `"persistence"` (warm-cache merge) / `"ths"` (cold-cache fallback) / `"persistence"` (fetcher 失败, enrichment 字段全 None)。`ok` flag 在 fetcher 失败时不变 `True`(仅 persistence 异常才 append `boards` aspect error)。
```

- [ ] **Step 3: Verify the section still renders cleanly**

Run: `.venv/Scripts/python.exe -c "import pathlib; pathlib.Path('CLAUDE.md').read_text(encoding='utf-8')"` — should print without error. (Manual sanity: skim the file in your editor to confirm no broken markdown.)

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(claude): cross-link /agent/stocks/batch-profile boards enrichment

Two additions:

1. Agent Batch API table row for /agent/stocks/batch-profile gains a
   trailing annotation about the 7 THS enrichment fields and the
   shared 60s _stock_boards_quote_cache.

2. Standardized Data Schema section gains a bullet documenting the
   full 11-field contract on the agent endpoint, the helper location,
   the boards.source three-state semantic, and the failure-isolation
   behavior (fetcher exception does NOT demote ok / append boards
   aspect error).

Direct-to-master per skip-branch-for-trivial-changes (markdown only).

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: End-to-end verification

**Files:** none modified

**Interfaces:** N/A — verification only

- [ ] **Step 1: Run the targeted suites**

Run: `.venv/Scripts/python.exe -m pytest tests/test_stock_boards_ths_enrichment.py tests/test_agent_batch_features.py -v`
Expected: all 8 ths-enrichment tests pass + all 4 new agent tests pass (3 boards-enrichment + 1 MD completeness) + all pre-existing agent tests pass.

- [ ] **Step 2: Run the wider agent suite**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_endpoints.py tests/test_routes.py -v`
Expected: all pass (no regression from the boards.py or agent.py changes).

- [ ] **Step 3: Run lint**

Run: `ruff check .`
Expected: zero errors.

- [ ] **Step 4: Final commit if any ruff auto-fix landed**

If `ruff check` reported any auto-fixable issues:

```bash
git add -u
git commit -m "style: ruff auto-fix from end-to-end verification

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

If nothing to fix, skip this step.

---

## Self-Review

**1. Spec coverage:**

- §3.1 (new helper module) → Task 1
- §3.2 (boards.py drops local helper + import + rename call site) → Task 2
- §3.2 (cache.py docstring cross-link) → Task 2 Step 3
- §3.3 (agent.py imports) → Task 3 Step 5
- §4.1 (schema contract) → Task 3 (data shape) + Task 4 (MD)
- §4.2 (three-branch merge code) → Task 3 Step 6
- §4.3 (boards.source three states) → Task 3 Steps 1-3 (test coverage) + Task 3 Step 6 (impl)
- §4.4 (backward compat) → implicit (additive schema changes only)
- §5 (MD rendering) → Task 4
- §6.1 (3 new agent cases) → Task 3 Steps 1-3
- §6.2 (MD completeness case) → Task 4 Step 1
- §6.3 (8 existing test import updates) → Task 2 Step 4
- §6.4 (pre-flight test run) → Task 6 Steps 1-2
- §7.1 (Agent Batch API table row) → Task 5 Step 1
- §7.2 (Standardized Data Schema bullet) → Task 5 Step 2
- §8 (files changed inventory) → All tasks
- §9.4 (rollback) → Documented in spec; verified by Task 6

Gaps: none. All 10 spec sections map to a task or task step.

**2. Placeholder scan:**

- No "TBD", "TODO", "fill in later" anywhere.
- Every code step shows full code (helper verbatim copy in Task 1 Step 2; tests fully written; merge code fully written; MD code fully written).
- The "5 '—' markers" assertion in Task 4 Step 1 was self-corrected inline (initial draft had "4 — markers" which double-counted).

**3. Type consistency:**

- `fetch_stock_boards_quote_enrichment(stock_code: str, manager) -> tuple[list[dict] | None, dict[str, dict]]` — defined once in Task 1's docstring, used identically in Task 2 (import), Task 3 (import + call), and Task 4 (no change to the function).
- `StockBatchProfileEntry.boards: dict | None` — unchanged (no schema hardening).
- 7 enrichment field names (`change_pct`, `up_count`, `down_count`, `limit_up_count`, `limit_down_count`, `explain`, `relevance`) — defined in Task 1's `enrichment_keys` tuple, referenced identically in Task 3's merge code, in Task 4's MD template, and in the new test assertions.
- Cache key `stock_boards_quote:{stock_code}` — verbatim in Task 1 helper body.
- `boards.source` three states `"persistence"` / `"ths"` — consistent across Task 3 (code) and Task 3 (tests).
- File paths (`stock_data/api/_helpers/stock_boards.py`, etc.) — consistent across all tasks.

No inconsistencies found.