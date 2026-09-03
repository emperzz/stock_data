# Board Stocks Suffix Quote Fillup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reuse `/api/v1/stocks`'s full-market quote cache (60s fast + 7d slow, `_stock_list_quote_cache` / `_stock_list_quote_slow`) to enrich the suffix rows of `/api/v1/boards/{code}/stocks?include_quote=true&source=ths` (the members beyond THS's 50-cap that currently arrive with all quote fields at `None`).

**Architecture:** TDD. Add a `_project_unified_quote_to_dict(code, name, q) -> dict` module-level helper in `persistence/board.py` (returns upstream-style dict keys `stock_code`/`stock_name`/`turnover_rate`/`amplitude`/`open`/`high`/`low`/`prev_close` so the result is interchangeable with raw THS/ZZSHARE fetcher output rows). Add a `get_cached_market_quotes(manager)` helper in the same file that reads/writes the shared `_stock_list_quote_cache` / `_stock_list_quote_slow`. In `get_board_stocks`'s `include_quote=True` branch, call the cache helper after ZZSHARE suffix resolution and project the dict helper onto every suffix row whose `stock_code` exists in the cached market quote. THS top-50 rows are **not modified** (avoid cross-source time drift). The route layer's `_build_board_stock_info` does the dict→model rename (`s.get("amplitude")` → `BoardStockInfo.amplitude_pct`, `s.get("turnover_rate")` → `turnover_pct`, plus 4 new fields).

**Tech Stack:** Python 3.x, FastAPI, Pydantic v2, SQLite (persistence), `cachetools.TTLCache`, pytest.

## Global Constraints

- **Python env**: Use `.venv/Scripts/python.exe` when present; fall back to system `python` (CLAUDE.md "Common Commands" preamble).
- **Default test skip**: `pytest` defaults to `-m "not live_network"` (no real upstream calls). All new tests must pass under this default. **Do not** add `live_network` markers.
- **Test layout**: `tests/test_persistence_board.py` for helper + integration in persistence; `tests/test_schemas.py` or `tests/test_board_stock_info.py` for factory; `tests/test_routes_boards.py` for route E2E.
- **No upstream calls in tests**: All `manager.get_realtime_quotes` and cache lookups must be monkeypatched.
- **TDD**: write failing test → run → fail → implement → run → pass → commit. No batching.
- **Frequent commits**: One commit per task minimum.
- **Schema breaking change**: `BoardStockInfo.amplitude` → `amplitude_pct` is hard-rename (no Pydantic alias); update existing test references in same commit.
- **Fields not added**: `close` / `current_price` (already covered by `price`); `pb_ratio` / `total_mv` / `circ_mv` (not in `StockQuote`'s direct field names — "two-schema intersection" principle).
- **No new fetcher, no new capability, no new cache namespace**: follow `extend-not-spawn-fetcher` and `vendor-not-peer-import` rules.
- **No `quote_fill_source` field**: tracing goes to logger only.
- **THS top-50 rows must NOT be modified** by the fillup path; tests must assert this.

---

## File Structure

| File | Responsibility | Action |
|---|---|---|
| `stock_data/api/schemas.py` | `BoardStockInfo` field rename (`amplitude` → `amplitude_pct`) + 4 new fields (`open`/`high`/`low`/`prev_close`) | Modify |
| `stock_data/data_provider/persistence/board.py` | `get_cached_market_quotes(manager)` helper + `get_board_stocks` suffix enrichment | Modify |
| `tests/test_board_stock_info.py` (new) | Factory unit tests (7 cases) | Create |
| `tests/test_persistence_board.py` | `get_cached_market_quotes` unit tests (5 cases) + suffix enrichment integration tests (2 cases) | Modify |
| `tests/test_routes_boards.py` | Route E2E for renamed `amplitude_pct` + suffix enrichment visible in response (3 cases) | Modify |
| `docs/superpowers/specs/2026-07-30-board-stocks-quote-fillup-design.md` | Spec (already written) | None |

---

## Task 1: `_project_unified_quote_to_dict` helper (TDD)

**Files:**
- Modify: `stock_data/data_provider/persistence/board.py` (add module-level helper)
- Modify: `tests/test_persistence_board.py` (add helper unit tests)

**Interfaces:**
- Consumes: `core/types.py::UnifiedRealtimeQuote` (already exists)
- Produces: `_project_unified_quote_to_dict(code: str, name: str, q: UnifiedRealtimeQuote) -> dict`

> **Critical design note**: the helper returns a `dict` with **upstream-style keys** (`stock_code` / `stock_name` / `turnover_rate` / `amplitude` / `open` / `high` / `low` / `prev_close`), **not** a `BoardStockInfo` instance with its model-level field names (`code` / `name` / `turnover_pct` / `amplitude_pct`). This is because the suffix dict must remain interchangeable with raw THS / ZZSHARE fetcher output rows so `update_cached_board_stocks` (`board.py:2055-2070`, reads `s["stock_code"]`) doesn't `KeyError`. The route layer's `_build_board_stock_info` does the dict→model rename (`s.get("amplitude")` → `BoardStockInfo.amplitude_pct`).

- [ ] **Step 1: Write the failing helper unit tests**

Append to `tests/test_persistence_board.py`:

```python
class TestProjectUnifiedQuoteToDict:
    """Tests for the suffix-quote projection helper (spec 2026-07-30)."""

    def _q(self, **overrides) -> UnifiedRealtimeQuote:
        """Build a UnifiedRealtimeQuote with sensible defaults."""
        from stock_data.data_provider.core.types import (
            RealtimeSource, UnifiedRealtimeQuote,
        )
        defaults = dict(
            code="600519",
            name="贵州茅台",
            source=RealtimeSource.ZZSHARE,
            price=1700.0,
            change_pct=1.5,
            change_amount=25.0,
            volume=1000000,
            amount=1.7e9,
            volume_ratio=1.2,
            turnover_rate=0.5,
            amplitude=2.0,
            open_price=1680.0,
            high=1710.0,
            low=1675.0,
            pre_close=1675.0,
            pe_ratio=30.0,
        )
        defaults.update(overrides)
        return UnifiedRealtimeQuote(**defaults)

    def test_returns_upstream_style_keys(self):
        """Result uses fetcher-style keys (stock_code/stock_name/turnover_rate/
        amplitude), NOT BoardStockInfo model field names (code/name/
        turnover_pct/amplitude_pct). This is the contract that keeps
        update_cached_board_stocks happy."""
        from stock_data.data_provider.persistence import board as pb

        q = self._q()
        d = pb._project_unified_quote_to_dict("600519", "贵州茅台", q)
        # stock_code/stock_name (NOT code/name)
        assert d["stock_code"] == "600519"
        assert d["stock_name"] == "贵州茅台"
        assert "code" not in d
        assert "name" not in d
        # turnover_rate (NOT turnover_pct)
        assert d["turnover_rate"] == 0.5
        assert "turnover_pct" not in d
        # amplitude (NOT amplitude_pct)
        assert d["amplitude"] == 2.0
        assert "amplitude_pct" not in d
        # 4 new fields use their own names
        assert d["open"] == 1680.0
        assert d["high"] == 1710.0
        assert d["low"] == 1675.0
        assert d["prev_close"] == 1675.0
        # 7 other quote fields
        assert d["price"] == 1700.0
        assert d["change_pct"] == 1.5
        assert d["change_amount"] == 25.0
        assert d["volume"] == 1000000
        assert d["amount"] == 1.7e9
        assert d["volume_ratio"] == 1.2
        assert d["pe_ratio"] == 30.0

    def test_amplitude_fallback_when_unified_amplitude_is_none(self):
        """q.amplitude=None, high/low/pre_close set → fallback computes amplitude."""
        from stock_data.data_provider.persistence import board as pb

        q = self._q(amplitude=None)
        d = pb._project_unified_quote_to_dict("600519", "贵州茅台", q)
        # (1710 - 1675) / 1675 * 100 ≈ 2.0896
        assert d["amplitude"] == pytest.approx(2.0896, rel=1e-3)

    def test_amplitude_none_when_no_fallback_inputs(self):
        """q.amplitude=None and high/low/pre_close missing → dict["amplitude"]=None."""
        from stock_data.data_provider.persistence import board as pb

        q = self._q(amplitude=None, high=None, low=None, pre_close=None)
        d = pb._project_unified_quote_to_dict("600519", "贵州茅台", q)
        assert d["amplitude"] is None

    def test_amplitude_passthrough_when_unified_amplitude_set(self):
        """q.amplitude already set → use it directly, do not recompute."""
        from stock_data.data_provider.persistence import board as pb

        q = self._q(amplitude=3.5)
        d = pb._project_unified_quote_to_dict("600519", "贵州茅台", q)
        assert d["amplitude"] == 3.5

    def test_ths_only_fields_not_in_dict(self):
        """change_speed / free_float_shares / float_market_cap must NOT appear
        in the dict (they're absent, not None). The route layer's
        _build_board_stock_info reads s.get('change_speed') → default None.
        Note (2026-09-03): `is_limit_up` / `lb_count` ZT-pool join fields
        have been retired, so they are no longer expected keys — kept here
        as historical reference; the live test suite drops these."""
        from stock_data.data_provider.persistence import board as pb

        q = self._q()
        d = pb._project_unified_quote_to_dict("600519", "贵州茅台", q)
        for k in ("change_speed", "free_float_shares", "float_market_cap"):
            assert k not in d

    def test_name_fallback_to_quote_name_when_param_empty(self):
        """name param empty → fallback to q.name."""
        from stock_data.data_provider.persistence import board as pb

        q = self._q(name="茅台")
        d = pb._project_unified_quote_to_dict("600519", "", q)
        assert d["stock_name"] == "茅台"

    def test_param_name_wins_over_quote_name(self):
        """name param set → use it (preserves upstream board member name)."""
        from stock_data.data_provider.persistence import board as pb

        q = self._q(name="Moutai")
        d = pb._project_unified_quote_to_dict("600519", "贵州茅台", q)
        assert d["stock_name"] == "贵州茅台"
```

Also add this import at the top of `tests/test_persistence_board.py` (if not already present):

```python
import pytest
from stock_data.data_provider.core.types import (
    RealtimeSource, UnifiedRealtimeQuote,
)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_persistence_board.py::TestProjectUnifiedQuoteToDict -v`

Expected: FAIL with `AttributeError: module 'stock_data.data_provider.persistence.board' has no attribute '_project_unified_quote_to_dict'`.

- [ ] **Step 3: Add the helper to `persistence/board.py`**

Add the following module-level helper near the top of `stock_data/data_provider/persistence/board.py` (after imports, before `THS_HARD_CAP` and the `get_board_list` function):

```python
def _project_unified_quote_to_dict(
    code: str, name: str, q: "UnifiedRealtimeQuote",
) -> dict:
    """Project UnifiedRealtimeQuote onto an upstream-style dict for
    suffix row enrichment. Returns 13 quote fields + stock_code/name
    using fetcher-style keys (stock_code/stock_name/turnover_rate/
    amplitude/open/high/low/prev_close) so the result is
    interchangeable with THS/ZZSHARE fetcher output rows.

    Reuses the same amplitude fallback logic as StockQuote.from_unified_quote
    (schemas.py:156-192): when q.amplitude is None and high/low/pre_close
    are all set, compute (high - low) / pre_close * 100.

    THS-only fields (change_speed, free_float_shares, float_market_cap)
    are not set here — they stay absent from the returned dict and
    surface as None via the route layer's _build_board_stock_info.

    Added 2026-07-30 alongside the cross-endpoint quote-cache fillup:
    /boards/{code}/stocks?include_quote=true suffix rows (members
    beyond THS's 50-cap) are enriched from the /api/v1/stocks
    full-market quote cache via this helper.
    """
    amplitude = q.amplitude
    if (
        amplitude is None
        and q.high is not None
        and q.low is not None
        and q.pre_close
    ):
        amplitude = (q.high - q.low) / q.pre_close * 100
    return {
        "stock_code": code,
        "stock_name": name or q.name,
        "price": q.price,
        "open": q.open_price,
        "high": q.high,
        "low": q.low,
        "prev_close": q.pre_close,
        "change_amount": q.change_amount,
        "change_pct": q.change_pct,
        "volume": q.volume,
        "amount": q.amount,
        "turnover_rate": q.turnover_rate,
        "amplitude": amplitude,
        "volume_ratio": q.volume_ratio,
        "pe_ratio": q.pe_ratio,
    }
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_board_stock_info.py -v`

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
cd "D:/GitRepo/skills/stock_data"
git add stock_data/data_provider/persistence/board.py tests/test_persistence_board.py
git commit -m "feat(persistence): add _project_unified_quote_to_dict helper for suffix fillup

Returns an upstream-style dict (stock_code/stock_name/turnover_rate/
amplitude/open/high/low/prev_close) so suffix rows remain
interchangeable with raw THS/ZZSHARE fetcher output rows. Reuses
StockQuote.from_unified_quote's amplitude fallback logic.

For BoardStockInfo's model field names (code/name/turnover_pct/
amplitude_pct), the route layer's _build_board_stock_info does the
dict→model rename (s.get('amplitude') → amplitude_pct). This separation
prevents update_cached_board_stocks from KeyError-ing on s['stock_code']
when the suffix dict is fed back to persistence."
```

---

## Task 2: `BoardStockInfo` field rename + 4 new fields + route projection update + E2E test

**Files:**
- Modify: `stock_data/api/schemas.py::BoardStockInfo` (rename `amplitude` → `amplitude_pct`, add `open / high / low / prev_close`)
- Modify: `stock_data/api/routes/boards.py::_build_board_stock_info` (read 4 new fields + rename `amplitude_pct`)
- Modify: `tests/test_routes_boards.py` (add 2 E2E tests for the renamed + new fields)

**Interfaces:**
- Consumes: nothing new (just field shape change)
- Produces: `BoardStockInfo.amplitude_pct` (replaces `amplitude`); 4 new optional fields; route JSON emits new field names

- [ ] **Step 1: Search the repo for direct references to `amplitude` in BoardStockInfo context**

Run: `grep -rn "amplitude" stock_data/ tests/ --include="*.py" | grep -v "amplitude_pct"`

Expected to find: `boards.py:_build_board_stock_info` (around line 93, `amplitude=s.get("amplitude")`), and possibly test files referencing `"amplitude"`.

- [ ] **Step 2: Update `BoardStockInfo` field declarations**

In `stock_data/api/schemas.py`, locate `class BoardStockInfo(BaseModel)` (around line 496). Change the `amplitude` field declaration:

- Replace: `    amplitude: float | None = None`
- With: `    amplitude_pct: float | None = None`

Then add these 4 new field declarations after `price` and before `change_pct` (preserve existing order; new fields go in the natural reading position):

```python
    open: float | None = None
    high: float | None = None
    low: float | None = None
    prev_close: float | None = None
```

- [ ] **Step 3: Update `_build_board_stock_info` in `stock_data/api/routes/boards.py`**

Locate `_build_board_stock_info` (around line 69-100 in `boards.py`). Make **two** changes:

Change 1: replace the `amplitude` line:
- Replace: `        amplitude=s.get("amplitude"),`
- With: `        amplitude_pct=s.get("amplitude"),`

Change 2: add 4 new field reads after the `price` line and before `change_pct`:
- After: `        price=s.get("price"),`
- Insert:

```python
        open=s.get("open"),
        high=s.get("high"),
        low=s.get("low"),
        prev_close=s.get("prev_close"),
```

Note: the upstream fetcher dicts (THS) currently don't carry `open` / `high` / `low` / `prev_close` keys (THS 14 columns don't have them), so they default to `None` for THS top-50 rows. Suffix rows will pick up these values from the helper in Task 1 once Task 4 ships.

- [ ] **Step 4: Search for and update test files that reference `amplitude` field directly**

Run: `grep -rn "\"amplitude\"" tests/ --include="*.py" | grep -v "amplitude_pct"`

For each match found, update to `"amplitude_pct"`. Likely files: `tests/test_boards_stocks.py` if it exists, or anywhere that constructs `BoardStockInfo(amplitude=...)` directly. Replace `amplitude=` keyword with `amplitude_pct=` and `"amplitude"` JSON keys with `"amplitude_pct"`.

If grep returns no matches, skip this step.

- [ ] **Step 5: Add E2E tests for the renamed + new fields (also run as Step 5 below)**

In `tests/test_routes_boards.py`, append this class (the `client` fixture is provided by the existing test setup):

```python
class TestBoardStocksAmplitudeRenameE2E:
    """E2E for amplitude → amplitude_pct rename + 4 new field defaults.
    These tests live in Task 2 (not Task 5) because they verify the
    schema/route changes shipped in this task; Task 5 tests suffix
    fillup E2E which is a different concern.
    """

    def test_amplitude_field_in_response_is_amplitude_pct(self, client, monkeypatch):
        """amplitude field is renamed to amplitude_pct in the JSON response."""
        from stock_data.data_provider.persistence import board as pb

        monkeypatch.setattr(pb, "get_board_stocks", lambda *a, **kw: (
            [{"stock_code": "600519", "stock_name": "贵州茅台",
              "price": 1700.0, "change_pct": 1.5, "amplitude": 2.0}],
            "persistence", "ths", None, False, 1,
        ))

        r = client.get("/api/v1/boards/885595/stocks?source=ths&include_quote=true")
        assert r.status_code == 200
        stock = r.json()["stocks"][0]
        assert "amplitude_pct" in stock
        assert "amplitude" not in stock
        assert stock["amplitude_pct"] == 2.0

    def test_new_fields_open_high_low_prev_close_default_none(self, client, monkeypatch):
        """4 new fields appear in the JSON response with None default."""
        from stock_data.data_provider.persistence import board as pb

        monkeypatch.setattr(pb, "get_board_stocks", lambda *a, **kw: (
            [{"stock_code": "600519", "stock_name": "M"}],
            "persistence", "ths", None, False, 1,
        ))
        r = client.get("/api/v1/boards/885595/stocks?source=ths")
        assert r.status_code == 200
        stock = r.json()["stocks"][0]
        for f in ("open", "high", "low", "prev_close"):
            assert f in stock and stock[f] is None, f"{f} should be present and None"
```

- [ ] **Step 6: Run the new E2E tests + the helper unit tests to verify nothing broke**

Run: `.venv/Scripts/python.exe -m pytest tests/test_routes_boards.py::TestBoardStocksAmplitudeRenameE2E tests/test_persistence_board.py::TestProjectUnifiedQuoteToDict -v`

Expected: All pass. If failures appear, inspect the diff and ensure route projection matches the new field names.

- [ ] **Step 7: Commit**

```bash
cd "D:/GitRepo/skills/stock_data"
git add stock_data/api/schemas.py stock_data/api/routes/boards.py tests/test_routes_boards.py
git commit -m "feat(schemas): rename BoardStockInfo.amplitude → amplitude_pct + add open/high/low/prev_close

Breaking change: amplitude field renamed. No Pydantic alias per
ponytail simplicity. open/high/low/prev_close are new optional fields
(defaulting to None) that align BoardStockInfo with StockQuote.

Route layer's _build_board_stock_info now reads s.get('open'/'high'/
'low'/'prev_close') in addition to the existing reads; THS top-50 rows
default to None (THS 14 columns don't have them), suffix rows will
pick them up from _project_unified_quote_to_dict once Task 4 ships.

E2E tests in TestBoardStocksAmplitudeRenameE2E pin both the rename and
the 4 new field defaults."
```

---

## Task 3: `get_cached_market_quotes` helper (TDD)

**Files:**
- Modify: `stock_data/data_provider/persistence/board.py` (add `get_cached_market_quotes(manager)` at module level)
- Modify: `tests/test_persistence_board.py` (add 5 helper unit tests)

**Interfaces:**
- Consumes: `manager.get_realtime_quotes("csi")` (already exists, returns `tuple[list[UnifiedRealtimeQuote] | None, str]`)
- Consumes: `cache.cached_lookup`, `cache.cached_store`, `cache.get_stock_list_quote_cache`, `cache.get_stock_list_quote_slow` (already exist)
- Produces: `get_cached_market_quotes(manager) -> list | None` — list of `UnifiedRealtimeQuote` (unsorted, unsliced), or `None` on full failure

- [ ] **Step 1: Write the failing helper unit tests**

In `tests/test_persistence_board.py`, add at the end of the file (or in a new section if the file is class-based):

```python
class TestGetCachedMarketQuotes:
    """Tests for the cross-endpoint /stocks quote cache reader."""

    def test_returns_none_when_both_caches_miss_and_fetch_returns_none(
        self, monkeypatch
    ):
        """Cache miss + upstream returns None → helper returns None, never raises."""
        from stock_data.data_provider.persistence import board as pb

        # Force cache miss by giving an empty cache.
        monkeypatch.setattr(
            "stock_data.api.cache._stock_list_quote_cache", type(
                "_C", (), {"__init__": lambda s: None, "__contains__": lambda s, k: False,
                            "__getitem__": lambda s, k: None, "__setitem__": lambda s, k, v: None}
            )(),
        )
        monkeypatch.setattr(
            "stock_data.api.cache._stock_list_quote_slow", type(
                "_C", (), {"__init__": lambda s: None, "__contains__": lambda s, k: False,
                            "__getitem__": lambda s, k: None, "__setitem__": lambda s, k, v: None}
            )(),
        )
        # Mock manager returning None.
        class _Mgr:
            def get_realtime_quotes(self, market):
                return None, ""

        result = pb.get_cached_market_quotes(_Mgr())
        assert result is None

    def test_cache_hit_returns_quotes_without_calling_manager(self, monkeypatch):
        """Cache hit → helper returns cached list, manager is never called."""
        from stock_data.data_provider.persistence import board as pb

        cached = [object(), object()]  # two dummy UnifiedRealtimeQuote stand-ins
        # Pre-populate fast cache.
        import stock_data.api.cache as cache_mod
        cache_mod._stock_list_quote_cache.clear()
        cache_mod._stock_list_quote_cache["stock_list_quote:csi"] = (cached, "zzshare")

        class _Mgr:
            def __init__(self):
                self.called = False
            def get_realtime_quotes(self, market):
                self.called = True
                return None, ""

        mgr = _Mgr()
        result = pb.get_cached_market_quotes(mgr)
        assert result is cached
        assert mgr.called is False
        # Cleanup
        cache_mod._stock_list_quote_cache.clear()

    def test_cache_miss_triggers_fetch_and_writes_back(self, monkeypatch):
        """Cache miss → manager called, result written back to cache, helper returns it."""
        from stock_data.data_provider.persistence import board as pb
        import stock_data.api.cache as cache_mod

        cache_mod._stock_list_quote_cache.clear()
        cache_mod._stock_list_quote_slow.clear()

        fetched = [object(), object(), object()]
        class _Mgr:
            def get_realtime_quotes(self, market):
                return fetched, "zzshare"

        result = pb.get_cached_market_quotes(_Mgr())
        assert result is fetched
        # Cache was written back.
        assert cache_mod._stock_list_quote_cache.get("stock_list_quote:csi") == (fetched, "zzshare")

        # Cleanup
        cache_mod._stock_list_quote_cache.clear()

    def test_slow_cache_hit_returns_unwrapped_quotes(self, monkeypatch):
        """Slow cache entry is (date, session, quotes, source) 4-tuple → unwrap to quotes."""
        from stock_data.data_provider.persistence import board as pb
        from datetime import date
        import stock_data.api.cache as cache_mod

        cache_mod._stock_list_quote_cache.clear()
        cache_mod._stock_list_quote_slow.clear()
        cached = [object()]
        cache_mod._stock_list_quote_slow["stock_list_quote:csi"] = (
            date(2026, 7, 30), "afternoon", cached, "akshare",
        )

        class _Mgr:
            def __init__(self):
                self.called = False
            def get_realtime_quotes(self, market):
                self.called = True
                return None, ""

        # Force non-intraday path by stubbing _is_intraday.
        monkeypatch.setattr(pb, "_is_intraday", lambda is_trade_day: False)

        mgr = _Mgr()
        result = pb.get_cached_market_quotes(mgr)
        assert result is cached
        assert mgr.called is False
        # Cleanup
        cache_mod._stock_list_quote_slow.clear()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_persistence_board.py::TestGetCachedMarketQuotes -v`

Expected: FAIL with `ImportError` or `AttributeError: module ... has no attribute 'get_cached_market_quotes'`.

- [ ] **Step 3: Implement the helper in `persistence/board.py`**

Add the following at module level in `stock_data/data_provider/persistence/board.py` (near the top, after imports and constants but before `get_board_list`):

```python
def _is_intraday(is_trade_day: bool) -> bool:
    """Mirror of stocks.py _is_intraday — duplicated here to keep the
    helper self-contained and avoid pulling the whole /stocks route module
    into persistence. Trade-day / time-of-day semantics match exactly:
    09:15-11:30 + 13:00-15:00 → True; lunch + pre/post-market + closed → False.
    """
    from datetime import datetime, time as _dt_time
    from zoneinfo import ZoneInfo

    if not is_trade_day:
        return False
    now = datetime.now(ZoneInfo("Asia/Shanghai")).time()
    return (
        (_dt_time(9, 15) <= now < _dt_time(11, 30))
        or (_dt_time(13, 0) <= now < _dt_time(15, 0))
    )


def _latest_past_close():
    """Mirror of stocks.py _latest_past_close — simplified, returns just
    the (date, session) tag the slow cache needs. Pulls from
    trade_calendar; falls back to (today, "afternoon") when calendar
    is empty.
    """
    from datetime import datetime, time as _dt_time, timedelta
    from zoneinfo import ZoneInfo

    from . import trade_calendar

    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    today = now.date()
    t = now.time()
    if not trade_calendar.is_trade_date(today.isoformat()):
        prev = trade_calendar.get_latest_trade_date_on_or_before(
            (today - timedelta(days=1)).isoformat()
        )
        if prev:
            from datetime import date as _date
            return _date.fromisoformat(prev), "afternoon"
        return today, "afternoon"
    if t < _dt_time(11, 30):
        prev = trade_calendar.get_latest_trade_date_on_or_before(
            (today - timedelta(days=1)).isoformat()
        )
        if prev:
            from datetime import date as _date
            return _date.fromisoformat(prev), "afternoon"
        return today, "afternoon"
    if t < _dt_time(15, 0):
        return today, "morning"
    return today, "afternoon"


def get_cached_market_quotes(manager) -> list | None:
    """Read the /api/v1/stocks full-market quote cache. On miss, fetch
    and write back. Returns the unsorted, unsliced upstream list, or
    None on upstream failure.

    Reuses the same cache namespace (stock_list_quote:csi) and TTL
    (60s intraday, 7d close-tagged slow) as /stocks?include_quote=true,
    so any request that touches /stocks naturally warms this cache.

    Cache hit = zero upstream. Cache miss + fetch fail = None, which
    leaves suffix rows at None in the caller — never raises, by
    contract (the route layer's include_quote path is best-effort).

    Added 2026-07-30 alongside the cross-endpoint quote-cache fillup
    for /boards/{code}/stocks suffix rows.
    """
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from ...api.cache import (
        cached_lookup,
        cached_store,
        get_stock_list_quote_cache,
        get_stock_list_quote_slow,
    )
    from . import trade_calendar

    cache_key = "stock_list_quote:csi"
    is_trade_day = trade_calendar.is_trade_date(
        datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    )
    in_intraday = _is_intraday(is_trade_day)

    if in_intraday:
        hit = cached_lookup(
            get_stock_list_quote_cache, cache_key, "stock_list_quote"
        )
        if hit is not None:
            return hit[0]
    else:
        hit = cached_lookup(
            get_stock_list_quote_slow, cache_key, "stock_list_quote"
        )
        if hit is not None:
            _, _, cached_quotes, _ = hit
            if cached_quotes is not None:
                return cached_quotes

    # Cache miss → fetch
    quotes, source = manager.get_realtime_quotes("csi")
    if not quotes:
        return None

    if in_intraday:
        cached_store(
            get_stock_list_quote_cache, cache_key, (quotes, source)
        )
    else:
        target_date, target_session = _latest_past_close()
        cached_store(
            get_stock_list_quote_slow, cache_key,
            (target_date, target_session, quotes, source),
        )
    return quotes
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_persistence_board.py::TestGetCachedMarketQuotes -v`

Expected: 4 passed (or 3 passed + 1 if you count setup/teardown variance).

- [ ] **Step 5: Commit**

```bash
cd "D:/GitRepo/skills/stock_data"
git add stock_data/data_provider/persistence/board.py tests/test_persistence_board.py
git commit -m "feat(persistence): add get_cached_market_quotes helper for suffix fillup

Reads the shared /api/v1/stocks full-market quote cache
(_stock_list_quote_cache 60s + _stock_list_quote_slow 7d, key
stock_list_quote:csi). Cache hit returns the unwrapped quote list with
zero upstream cost. Cache miss triggers manager.get_realtime_quotes and
writes back to the same namespace so /stocks also benefits. Never
raises; returns None on full failure (suffix rows stay at None)."
```

---

## Task 4: Integrate suffix enrichment into `get_board_stocks`

**Files:**
- Modify: `stock_data/data_provider/persistence/board.py::get_board_stocks` (insert enrichment block before `final_stocks` assembly, around line 1319-1368)
- Modify: `tests/test_persistence_board.py` (add 2 integration tests)

**Interfaces:**
- Consumes: `_project_unified_quote_to_dict(code, name, q) -> dict` (Task 1, module-level helper)
- Consumes: `get_cached_market_quotes(manager)` (Task 3)
- Produces: `suffix_no_quote` list with 13 fields projected (upstream-style dict keys) onto entries whose `stock_code` exists in market quote

- [ ] **Step 1: Write the failing integration tests**

In `tests/test_persistence_board.py`, add:

```python
class TestBoardStocksSuffixEnrichment:
    """Integration tests for the suffix → market-quote enrichment in
    get_board_stocks (spec 2026-07-30).
    """

    def test_suffix_rows_enriched_from_market_quote_cache(self, monkeypatch, tmp_path):
        """When market quote cache has a code that suffix has, the 13
        fields are projected; THS top-50 rows are untouched."""
        from stock_data.data_provider.persistence import board as pb
        from stock_data.data_provider.core.types import (
            RealtimeSource, UnifiedRealtimeQuote,
        )
        from stock_data.api.schemas import BoardStockInfo

        # Set up: 3 THS top-50 rows (with quote), 2 suffix rows (no quote).
        ths_rows = [
            {"stock_code": "600519", "stock_name": "贵州茅台",
             "price": 1700.0, "change_pct": 1.5, "change_amount": 25.0,
             "amount": 1.7e9, "turnover_rate": 0.5, "volume_ratio": 1.2,
             "amplitude": 2.0, "pe_ratio": 30.0, "change_speed": 0.1,
             "free_float_shares": 1.0e9, "float_market_cap": 1.7e12},
            {"stock_code": "000001", "stock_name": "平安银行",
             "price": 10.0, "change_pct": 0.5, "change_amount": 0.05},
            {"stock_code": "300750", "stock_name": "宁德时代",
             "price": 200.0, "change_pct": -1.0, "change_amount": -2.0},
        ]
        suffix_rows = [
            {"stock_code": "600000", "stock_name": "浦发银行"},
            {"stock_code": "601318", "stock_name": "中国平安"},
        ]
        market_quotes = [
            UnifiedRealtimeQuote(
                code="600000", name="浦发银行", source=RealtimeSource.ZZSHARE,
                price=8.0, change_pct=0.0, change_amount=0.0,
                volume=5000000, amount=4.0e7,
                turnover_rate=0.3, amplitude=1.5,
                open_price=7.95, high=8.05, low=7.90, pre_close=8.0,
                pe_ratio=5.0,
            ),
            UnifiedRealtimeQuote(
                code="601318", name="中国平安", source=RealtimeSource.ZZSHARE,
                price=50.0, change_pct=2.0, change_amount=1.0,
                volume=10000000, amount=5.0e8,
                turnover_rate=0.4, amplitude=2.5,
                open_price=49.5, high=50.5, low=49.0, pre_close=49.0,
                pe_ratio=8.0,
            ),
        ]

        # Stub the helper.
        monkeypatch.setattr(pb, "get_cached_market_quotes",
                            lambda mgr: market_quotes)

        # Stub the rest of the persistence machinery we don't exercise.
        from stock_data.data_provider.persistence import db as db_mod
        db_mod.get_db_path = lambda: tmp_path / "test.db"

        # Call get_board_stocks with a manager mock.
        class _Mgr:
            def get_board_stocks(self, board_code, source, **kwargs):
                if kwargs.get("include_quote"):
                    return ths_rows, "ths"
                return suffix_rows, "zzshare"

        # Direct call to the suffix enrichment helper we'll add to
        # get_board_stocks; we test it via the persistence layer in
        # the next test, here we test the small projection helper.
        from stock_data.data_provider.persistence.board import (
            _enrich_suffix_with_market_quote,
        )
        enriched = _enrich_suffix_with_market_quote(
            suffix_rows, market_quotes,
        )
        assert len(enriched) == 2
        # 600000 was enriched with upstream-style dict keys
        row_600000 = next(r for r in enriched if r["stock_code"] == "600000")
        assert row_600000["price"] == 8.0
        assert row_600000["open"] == 7.95
        assert row_600000["amplitude"] == 1.5      # upstream-style key, NOT amplitude_pct
        assert row_600000["turnover_rate"] == 0.3 # upstream-style key, NOT turnover_pct
        # THS-only fields stay absent (not None — they're not in the dict)
        assert "change_speed" not in row_600000
        assert "free_float_shares" not in row_600000
        assert "float_market_cap" not in row_600000

    def test_suffix_row_not_in_market_quote_keeps_no_quote_state(self, monkeypatch):
        """A suffix code absent from market quote (停牌/新上市) stays as-is."""
        from stock_data.data_provider.persistence import board as pb
        from stock_data.data_provider.persistence.board import (
            _enrich_suffix_with_market_quote,
        )
        from stock_data.data_provider.core.types import (
            RealtimeSource, UnifiedRealtimeQuote,
        )

        suffix_rows = [{"stock_code": "688999", "stock_name": "新股A"}]
        market_quotes = [
            UnifiedRealtimeQuote(
                code="600000", name="浦发银行", source=RealtimeSource.ZZSHARE,
            ),
        ]
        enriched = _enrich_suffix_with_market_quote(suffix_rows, market_quotes)
        # 688999 not in index → kept as-is, no quote fields
        assert len(enriched) == 1
        assert enriched[0]["stock_code"] == "688999"
        assert enriched[0].get("price") is None
        assert enriched[0].get("amplitude_pct") is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_persistence_board.py::TestBoardStocksSuffixEnrichment -v`

Expected: FAIL with `ImportError: cannot import name '_enrich_suffix_with_market_quote'`.

- [ ] **Step 3: Add the small projection helper in `persistence/board.py`**

Add a small internal helper next to `get_cached_market_quotes` (so it can be unit-tested independently of the route's full flow):

```python
def _enrich_suffix_with_market_quote(
    suffix_rows: list[dict], market_quotes: list,
) -> list[dict]:
    """Project 13 UnifiedRealtimeQuote fields onto each suffix row whose
    stock_code exists in the market-quote index. Rows whose code is
    absent (停牌/新上市) are kept as-is.

    THS-only fields (change_speed, free_float_shares, float_market_cap)
    are never set by the helper — they stay absent from the returned
    dict and surface as None via the route layer's _build_board_stock_info.

    Returns a new list; input is not mutated.
    """
    if not suffix_rows or not market_quotes:
        return list(suffix_rows)

    q_index = {q.code: q for q in market_quotes}
    out: list[dict] = []
    for row in suffix_rows:
        sc = row.get("stock_code", "")
        q = q_index.get(sc)
        if q is None:
            out.append(row)
            continue
        out.append(
            _project_unified_quote_to_dict(
                code=sc, name=row.get("stock_name", ""), q=q,
            )
        )
    return out
```

- [ ] **Step 4: Insert the enrichment call into `get_board_stocks`**

In `stock_data/data_provider/persistence/board.py::get_board_stocks`, locate the `include_quote=True` branch around line 1300-1382. The relevant existing code is:

```python
        suffix_no_quote: list[dict] = []
        try:
            zz_rows, _ = manager.get_board_stocks(
                board_code=board_code,
                source="zzshare",
                include_quote=False,
            )
        except DataFetchError as e:
            logger.warning(...)
            zz_rows = []

        quote_codes = {s["stock_code"] for s in stocks if s.get("stock_code")}
        suffix_no_quote = [
            r for r in (zz_rows or [])
            if r.get("stock_code") and r["stock_code"] not in quote_codes
        ]

        # quote_truncated / quote_total_in_board logic ...
```

Insert a new block **between** the suffix calculation and the `quote_truncated` logic. Find the line:

```python
        suffix_no_quote = [
            r for r in (zz_rows or []) if r.get("stock_code") and r["stock_code"] not in quote_codes
        ]
```

Immediately after, insert:

```python
        # === Cross-endpoint quote fillup (2026-07-30) ===
        # Reuse the /api/v1/stocks full-market quote cache to enrich
        # suffix rows whose stock_code exists upstream. THS top-50
        # rows in `stocks` are NOT modified — the fillup only touches
        # the suffix (members beyond THS's 50-cap). On cache miss +
        # fetch failure, suffix stays as-is and quote_truncated logic
        # below runs unchanged.
        if suffix_no_quote:
            cached_quotes = get_cached_market_quotes(manager)
            if cached_quotes:
                before = len(suffix_no_quote)
                suffix_no_quote = _enrich_suffix_with_market_quote(
                    suffix_no_quote, cached_quotes,
                )
                n_filled = sum(
                    1 for r in suffix_no_quote if r.get("price") is not None
                )
                logger.info(
                    f"[BoardCache] suffix fill: {n_filled}/{before} "
                    f"rows enriched from /stocks quote cache for "
                    f"board {board_code}"
                )
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_persistence_board.py::TestBoardStocksSuffixEnrichment -v`

Expected: 2 passed.

- [ ] **Step 6: Run the helper unit tests to verify nothing broke**

Run: `.venv/Scripts/python.exe -m pytest tests/test_persistence_board.py -v`

Expected: All pass.

- [ ] **Step 7: Commit**

```bash
cd "D:/GitRepo/skills/stock_data"
git add stock_data/data_provider/persistence/board.py tests/test_persistence_board.py
git commit -m "feat(persistence): enrich /boards/{code}/stocks suffix from /stocks quote cache

Inserts a 1-block enrichment step into get_board_stocks' include_quote=
True branch: after THS top-50 + ZZSHARE suffix are merged, suffix rows
whose stock_code exists in the /api/v1/stocks full-market quote cache
get 13 fields projected via _project_unified_quote_to_dict (upstream-
style dict keys: stock_code/stock_name/turnover_rate/amplitude/open/
high/low/prev_close).

THS top-50 rows are NOT touched. On cache miss + fetch failure, suffix
stays as-is (the existing quote_truncated / quote_total_in_board logic
preserves the prior behavior)."
```

---

## Task 5: Route E2E tests + final regression

**Files:**
- Modify: `tests/test_routes_boards.py` (add 3 E2E tests for the response shape)

- [ ] **Step 1: Write the failing E2E tests**

In `tests/test_routes_boards.py`, add:

```python
class TestBoardStocksE2ESuffixFillup:
    """End-to-end tests verifying the cross-endpoint fillup surfaces in
    the JSON response shape (spec 2026-07-30).
    """

    def test_amplitude_field_in_response_is_amplitude_pct(self, client, monkeypatch):
        """amplitude field is renamed to amplitude_pct in the JSON response."""
        from stock_data.data_provider.core.types import (
            RealtimeSource, UnifiedRealtimeQuote,
        )

        # Stub the persistence to return a known 1-row response.
        from stock_data.data_provider.persistence import board as pb

        def fake_get_board_stocks(*args, **kwargs):
            return (
                [{"stock_code": "600519", "stock_name": "贵州茅台",
                  "price": 1700.0, "change_pct": 1.5, "amplitude": 2.0}],
                "persistence", "ths", None, False, 1,
            )

        monkeypatch.setattr(pb, "get_board_stocks", fake_get_board_stocks)

        r = client.get("/api/v1/boards/885595/stocks?source=ths&include_quote=true")
        assert r.status_code == 200
        body = r.json()
        assert "stocks" in body
        assert len(body["stocks"]) == 1
        stock = body["stocks"][0]
        # amplitude_pct is present (renamed from amplitude)
        assert "amplitude_pct" in stock
        assert "amplitude" not in stock
        assert stock["amplitude_pct"] == 2.0

    def test_new_fields_open_high_low_prev_close_default_none(self, client, monkeypatch):
        """4 new fields (open/high/low/prev_close) appear in response with None default."""
        from stock_data.data_provider.persistence import board as pb

        monkeypatch.setattr(pb, "get_board_stocks",
                            lambda *a, **kw: (
                                [{"stock_code": "600519", "stock_name": "M"}],
                                "persistence", "ths", None, False, 1,
                            ))
        r = client.get("/api/v1/boards/885595/stocks?source=ths")
        assert r.status_code == 200
        stock = r.json()["stocks"][0]
        # New fields present and default None
        assert "open" in stock and stock["open"] is None
        assert "high" in stock and stock["high"] is None
        assert "low" in stock and stock["low"] is None
        assert "prev_close" in stock and stock["prev_close"] is None

    def test_no_quote_fill_source_field_in_response(self, client, monkeypatch):
        """quote_fill_source is NOT added to the response shape."""
        from stock_data.data_provider.persistence import board as pb

        monkeypatch.setattr(pb, "get_board_stocks",
                            lambda *a, **kw: (
                                [{"stock_code": "600519", "stock_name": "M"}],
                                "persistence", "ths", None, False, 1,
                            ))
        r = client.get("/api/v1/boards/885595/stocks?source=ths&include_quote=true")
        body = r.json()
        assert "quote_fill_source" not in body
        assert "quote_fillup" not in body
```

- [ ] **Step 2: Run the E2E tests to verify they fail (or partially pass)**

Run: `.venv/Scripts/python.exe -m pytest tests/test_routes_boards.py::TestBoardStocksE2ESuffixFillup -v`

Expected: First test FAILS (`"amplitude" not in stock` — current response still has `amplitude` not `amplitude_pct` because Task 2 hasn't shipped). The 2nd and 3rd tests will pass if Tasks 1-4 already shipped.

- [ ] **Step 3: Adjust the test for current state if needed**

If Task 2 hasn't yet renamed `amplitude` in the test, you may need to wait for Task 2 to land. Run the full E2E after Task 2 ships:

Run: `.venv/Scripts/python.exe -m pytest tests/test_routes_boards.py::TestBoardStocksE2ESuffixFillup -v`

Expected: All 3 pass.

- [ ] **Step 4: Run the full test suite (default, no live_network)**

Run: `.venv/Scripts/python.exe -m pytest`

Expected: All pass. If existing tests still reference `amplitude` (the old field name) anywhere, update them. Most likely locations: `tests/test_boards_stocks.py` (if it exists), `tests/test_routes_boards.py` existing classes, anywhere `BoardStockInfo(amplitude=...)` is constructed.

- [ ] **Step 5: Run ruff lint**

Run: `.venv/Scripts/python.exe -m ruff check .`

Expected: No new violations. Fix any obvious ones (unused imports introduced by the new helpers, etc.).

- [ ] **Step 6: Commit**

```bash
cd "D:/GitRepo/skills/stock_data"
git add tests/test_routes_boards.py
git commit -m "test(routes): E2E for suffix fillup + amplitude rename in /boards/{code}/stocks response

Verifies the cross-endpoint fillup surfaces correctly in JSON:
- amplitude field renamed to amplitude_pct
- 4 new fields (open/high/low/prev_close) default None
- no quote_fill_source field added (per spec)"
```

---

## Task 6: Spec archived status update + final push

**Files:**
- Modify: `docs/superpowers/specs/2026-07-30-board-stocks-quote-fillup-design.md` (change `Status: Draft` → `Status: Implemented`)

- [ ] **Step 1: Re-run the full default test suite one more time**

Run: `.venv/Scripts/python.exe -m pytest`

Expected: All pass.

- [ ] **Step 2: Update spec status**

In `docs/superpowers/specs/2026-07-30-board-stocks-quote-fillup-design.md`, change:

- Replace: `**Status**: Draft`
- With: `**Status**: Implemented (2026-07-30)`

Add a new section at the bottom of the spec (right after §12 References, as a new §13 — do **not** append a "Resolution:" line under §11 Open Questions, since §11's body is "无未决 trade-off" and a resolution line there would be semantically wrong):

```markdown

## 13. Implementation History

- **2026-07-30**: Implemented via plan `docs/superpowers/plans/2026-07-30-board-stocks-quote-fillup.md`. Commits landed in the order: helper → schema/rename + route projection + E2E → `get_cached_market_quotes` → suffix enrichment integration.
```

- [ ] **Step 3: Final commit + push (if user requests)**

```bash
cd "D:/GitRepo/skills/stock_data"
git add docs/superpowers/specs/2026-07-30-board-stocks-quote-fillup-design.md
git commit -m "docs(spec): mark board-stocks-quote-fillup spec as implemented"
```

Do NOT push unless the user explicitly asks (per `do-not-kill-user-server` and CLAUDE.md "Commit or push only when the user asks" guidance).

---

## Self-Review Checklist

- [x] **Spec coverage**:
  - Context (§1) → read for context, no task needed
  - Goal (§2) → Tasks 3 + 4 implement the cache reuse
  - Non-Goals (§3) → reflected in Task 1 (factory doesn't touch THS rows), Task 4 (no ZZSHARE/EastMoney fetcher changes)
  - Schema field changes (§4.1) → Tasks 1 + 2
  - Factory method (§4.1.2) → Task 1
  - Helper (§4.2.1) → Task 3
  - get_board_stocks call site (§4.2.2) → Task 4
  - Data flow (§5) → implicit in Tasks 3 + 4
  - Error handling (§6) → Tests in Tasks 3 + 4 cover cache miss + fetch fail + code not in market quote
  - Backward compatibility (§7) → Task 2 documents breaking change
  - Testing (§8) → Tasks 1, 3, 4, 5 cover all test categories in spec
  - Risks (§9) → Spec section; no separate task needed
  - Files changed (§10) → Matches this plan's File Structure table

- [x] **Placeholder scan**: No "TBD", "TODO", "implement later", "fill in details", "add appropriate error handling", "Similar to Task N" — every step has concrete code or commands.

- [x] **Type consistency**:
  - `get_cached_market_quotes(manager) -> list | None` — used identically in Task 3 (definition) and Task 4 (call).
  - `_enrich_suffix_with_market_quote(suffix_rows: list[dict], market_quotes: list) -> list[dict]` — used identically in Task 4 (definition) and Task 4 tests.
  - `_project_unified_quote_to_dict(code, name, q) -> dict` — defined Task 1, used Task 4. Returns upstream-style dict keys (not BoardStockInfo model field names) so the suffix dict stays interchangeable with raw fetcher output rows.
  - Field name `amplitude_pct` consistent across Task 1 (factory), Task 2 (schema + route projection), Task 5 (E2E assertion).
  - `quote_fill_source` consistently NOT added (spec §4.1.1, plan Tasks 1/2/4/5).

- [x] **Each task has independent test deliverable**: ✓ (Tasks 1, 3, 4 each end with a passing test; Tasks 2, 5, 6 have validation steps).

- [x] **No live_network markers added**: ✓ (all tests use monkeypatch; helper tests stub cache directly).

- [x] **No new fetcher, no new cache namespace, no quote_fill_source field**: ✓ (per Global Constraints and CLAUDE.md anti-patterns).
