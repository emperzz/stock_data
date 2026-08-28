# Agent Batch-Profile Quote Field Expansion — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend `MinimalQuote` on the three `/agent/{stocks,indices,boards}/batch-profile` endpoints from 2 fields (`price` + `change_pct`) to ~23 fields covering OHLV + turnover + valuation + 涨跌停价 + (board-only) 板块统计.

**Architecture:** One schema (`MinimalQuote`), three call-site rewrites in `agent.py` (one per endpoint), two pure helper builders (`_build_minimal_quote_from_unified` for stock/index, `_build_minimal_quote_from_board_dict` for board), one new MD projection helper (`_md_quote_block`) wired into the three existing MD templates. TDD throughout; each task ends with a passing test + a commit.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic v2, pytest. Existing test harness in `tests/test_agent_batch_features.py` (MagicMock + monkeypatch on `agent_module.get_manager`).

## Global Constraints

- **Volume unit invariant** (server-wide, spec §3.4): per-bar volume is **股** for stock/index. Realtime volume inherits the same invariant.
- **Board upstream volume** is **万手** (THS `q.10jqka` upstream); board upstream **amount is 亿元**.
- **Server-wide amount convention**: `StockQuote.amount` is 元, `BoardQuoteResponse.amount` is 元 (with `routes/boards.py:857` doing the `×1e8` conversion). MinimalQuote MUST match — `amount` field carries 元 across all three endpoints (board helper does `×1e8`).
- **CLAUDE.md "No data is dropped" contract** (api-reference.md, `TestFormatMdFeatureCompleteness`): every JSON field appears in MD too. None values render as `—` via `_md_num`, never omitted.
- **No new fetcher, no new DataCapability, no new endpoint, no composite cache.** Spec is schema + helpers + rewrites only.
- **Existing test harness reuse**: `_make_unified_quote` / `_stock_request` / `_bind_manager` / `_BOARD_STOCKS_PATCH` from `tests/test_agent_batch_features.py` — extend, don't fork.
- **Backward-compatible**: existing clients reading only `price` + `change_pct` keep working; field additions are purely additive.

## File Map

**Created:**
- `tests/test_minimal_quote_helpers.py` — unit tests for the two builder helpers.

**Modified:**
- `stock_data/api/schemas.py` — `MinimalQuote` (lines 1603-1607) extended to ~23 fields.
- `stock_data/api/routes/agent.py` — two new helpers + three call-site rewrites + one new MD helper + three MD template rewrites (~150 net lines added).
- `tests/test_agent_batch_features.py` — extend `TestFormatMdFeatureCompleteness` with quote-block assertions.
- `tests/test_agent_endpoints.py` — add three endpoint integration tests (one per batch-profile endpoint).
- `CLAUDE.md` — append one paragraph under "Agent Batch API" documenting the extended MinimalQuote and the volume-unit / amount-unit conventions.

---

## Task 1: Extend `MinimalQuote` schema

**Files:**
- Modify: `stock_data/api/schemas.py:1603-1607`
- Test: `tests/test_minimal_quote_helpers.py` (new file, contains only the schema test for this task — other tasks append to the same file)

**Interfaces:**
- Consumes: nothing.
- Produces: `MinimalQuote` with ~21 optional fields (price, change_pct, change_amount, open, high, low, prev_close, volume, volume_unit, amount, turnover_pct, amplitude_pct, volume_ratio, pe_ratio, pb_ratio, mcap_yi, float_mcap_yi, limit_up, limit_down, up_count, down_count, net_inflow, rank).

- [ ] **Step 0: Update the existing `test_minimal_quote` to use subset assertion**

The existing test at `tests/test_agent_batch_features.py:310-312` asserts exact equality:

```python
def test_minimal_quote(self):
    q = MinimalQuote(price=1721.0, change_pct=1.2)
    assert q.model_dump() == {"price": 1721.0, "change_pct": 1.2}
```

This will fail after Task 1's schema extension because `model_dump()` will return 23 keys (21 new `None`s + `volume_unit="share"` + the two populated fields). Replace the body with:

```python
def test_minimal_quote(self):
    q = MinimalQuote(price=1721.0, change_pct=1.2)
    dumped = q.model_dump()
    # Backward-compatible: the 2-field anchor still serializes
    # the original price/change_pct values; the rest are None defaults.
    assert dumped["price"] == 1721.0
    assert dumped["change_pct"] == 1.2
    assert dumped["volume_unit"] == "share"
    # New fields are present-but-None.
    assert dumped["open"] is None
    assert dumped["amount"] is None
    assert dumped["mcap_yi"] is None
    assert dumped["rank"] is None
```

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_batch_features.py::TestSchemas::test_minimal_quote -v`
Expected: FAIL with `AssertionError` on `dumped["price"]` (the new fields don't exist yet, so this test runs against the old 2-field schema and the assertion still passes — but the wider point is that this test runs cleanly under both schemas). Actually expected: PASS because `dumped["volume_unit"]` defaults to `"share"` after Task 1's schema extension; the subset check works against both schemas. The point of Step 0 is to convert the brittle exact-equality assertion into a robust subset/field-by-field check BEFORE Task 1's schema edit, so the test doesn't break in Step 4.

- [ ] **Step 1: Create the test file**

Write `tests/test_minimal_quote_helpers.py` with the schema-instantiation test (this task owns the file; subsequent tasks append to it):

```python
"""Unit tests for the two MinimalQuote builder helpers and the schema."""

from dataclasses import dataclass

import pytest

from stock_data.api.schemas import MinimalQuote
from stock_data.data_provider.core.types import RealtimeSource, UnifiedRealtimeQuote


class TestMinimalQuoteSchema:
    def test_all_fields_constructable_with_just_required(self):
        """All new fields are Optional; the bare-class instance must
        validate against `None` defaults."""
        q = MinimalQuote()
        assert q.price is None
        assert q.change_pct is None
        assert q.change_amount is None
        assert q.open is None
        assert q.high is None
        assert q.low is None
        assert q.prev_close is None
        assert q.volume is None
        assert q.volume_unit == "share"
        assert q.amount is None
        assert q.turnover_pct is None
        assert q.amplitude_pct is None
        assert q.volume_ratio is None
        assert q.pe_ratio is None
        assert q.pb_ratio is None
        assert q.mcap_yi is None
        assert q.float_mcap_yi is None
        assert q.limit_up is None
        assert q.limit_down is None
        assert q.up_count is None
        assert q.down_count is None
        assert q.net_inflow is None
        assert q.rank is None

    def test_volume_unit_default_is_share(self):
        """The default MUST be "share" — matches KLineData.volume_unit
        invariant (spec §3.4). Board callers override to "wan_shou"."""
        assert MinimalQuote().volume_unit == "share"

    def test_full_population_serializes_all_keys(self):
        q = MinimalQuote(
            price=12.34, change_pct=1.23, change_amount=0.15,
            open=12.20, high=12.40, low=12.10, prev_close=12.19,
            volume=1_234_567, volume_unit="share",
            amount=205_000_000.0,
            turnover_pct=0.45, amplitude_pct=2.11, volume_ratio=1.20,
            pe_ratio=25.3, pb_ratio=8.7,
            mcap_yi=21_123.5, float_mcap_yi=21_000.1,
            limit_up=13.41, limit_down=11.10,
            up_count=None, down_count=None, net_inflow=None, rank=None,
        )
        dumped = q.model_dump()
        # every field the spec promises is present (even None)
        expected_keys = {
            "price", "change_pct", "change_amount",
            "open", "high", "low", "prev_close",
            "volume", "volume_unit", "amount",
            "turnover_pct", "amplitude_pct", "volume_ratio",
            "pe_ratio", "pb_ratio", "mcap_yi", "float_mcap_yi",
            "limit_up", "limit_down",
            "up_count", "down_count", "net_inflow", "rank",
        }
        assert expected_keys <= dumped.keys()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_minimal_quote_helpers.py -v`
Expected: FAIL with `AttributeError: module 'stock_data.api.schemas' has no attribute 'MinimalQuote'` is wrong — `MinimalQuote` already exists but with only 2 fields. The test will fail on `assert q.open is None` because `MinimalQuote` has no `open` attribute → `AttributeError` (or Pydantic `ValidationError` on `test_full_population_serializes_all_keys` for an unknown field).

- [ ] **Step 3: Replace the existing `MinimalQuote` class**

In `stock_data/api/schemas.py`, find the existing definition (~line 1603):

```python
class MinimalQuote(BaseModel):
    """极简当前价锚点 (price + change_pct)."""

    price: float | None = None
    change_pct: float | None = None
```

Replace the entire class with the extended version:

```python
class MinimalQuote(BaseModel):
    """Extended realtime quote block for the three batch-profile endpoints.

    One schema across stock / index / board. Fields not exposed by the
    serving fetcher are None — this matches the existing StockQuote /
    BoardQuoteResponse precedent where "field present in schema, None
    upstream" is the documented contract.

    Units:
    - ``volume`` raw; disambiguate via ``volume_unit``
      (``"share"`` for stock/index, ``"wan_shou"`` for board).
    - ``amount`` unified to 元 (CNY); stock/index upstream passes
      through; board upstream (亿元) is multiplied by 1e8 — same
      conversion `/boards/{code}/quote` already applies at
      `routes/boards.py:857`.
    """

    # ── core ──
    price: float | None = None
    change_pct: float | None = None
    change_amount: float | None = None

    # ── OHLC ──
    open: float | None = None
    high: float | None = None
    low: float | None = None
    prev_close: float | None = None

    # ── 量价 ──
    volume: int | None = None
    volume_unit: str = Field(
        default="share",
        description='"share" (股) for stock/index; "wan_shou" (万手) for board.',
    )
    amount: float | None = Field(
        default=None,
        description="成交额 元. Unified to 元 across all three endpoints; board upstream (亿元) is ×1e8.",
    )
    turnover_pct: float | None = None
    amplitude_pct: float | None = None
    volume_ratio: float | None = None

    # ── 估值 (stock only) ──
    pe_ratio: float | None = None
    pb_ratio: float | None = None
    mcap_yi: float | None = None
    float_mcap_yi: float | None = None

    # ── 涨跌停 (stock only) ──
    limit_up: float | None = None
    limit_down: float | None = None

    # ── 板块统计 (board only) ──
    up_count: int | None = None
    down_count: int | None = None
    net_inflow: float | None = None
    rank: str | None = None
```

The `Field` import at the top of `schemas.py` already exists (`from pydantic import BaseModel, Field, PrivateAttr, model_serializer, model_validator`).

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_minimal_quote_helpers.py -v`
Expected: PASS for all 3 tests in `TestMinimalQuoteSchema`.

- [ ] **Step 5: Commit**

```bash
git add stock_data/api/schemas.py tests/test_minimal_quote_helpers.py
git commit -m "feat(schemas): extend MinimalQuote to ~23 fields for batch-profile

Adds OHLV, 量价 (turnover/amplitude/volume_ratio), 估值
(PE/PB/mcap_yi/float_mcap_yi), 涨跌停价, and (board-only) 板块统计
(up_count/down_count/net_inflow/rank). All fields Optional with
sensible defaults; old clients reading only price/change_pct
continue to work unchanged."
```

---

## Task 2: Implement `_build_minimal_quote_from_unified`

**Files:**
- Modify: `stock_data/api/routes/agent.py` (insert helper above `post_boards_batch_profile`, ~line 1010)
- Test: append to `tests/test_minimal_quote_helpers.py`

**Interfaces:**
- Consumes: a `UnifiedRealtimeQuote` instance.
- Produces: `MinimalQuote` with all stock/index fields populated per the mapping in spec §4.

- [ ] **Step 1: Append failing tests to `tests/test_minimal_quote_helpers.py`**

Add a `_mk_unified` helper at module scope (above the new test class):

```python
def _mk_unified(**overrides) -> UnifiedRealtimeQuote:
    """Build a fully-populated UnifiedRealtimeQuote for tests."""
    base = dict(
        code="600519",
        name="贵州茅台",
        source=RealtimeSource.ZZSHARE,
        price=1680.0,
        change_pct=1.23,
        change_amount=20.4,
        volume=12_345_678,
        volume_unit="share",
        amount=2_050_000_000.0,
        volume_ratio=1.2,
        turnover_rate=0.45,
        amplitude=2.11,
        open_price=1660.0,
        high=1690.0,
        low=1655.0,
        pre_close=1659.6,
        limit_up=1825.56,
        limit_down=1493.64,
        pe_ratio=25.3,
        pb_ratio=8.7,
        total_mv=2_112_350_000_000.0,
        circ_mv=2_100_010_000_000.0,
    )
    base.update(overrides)
    return UnifiedRealtimeQuote(**base)
```

Append the test class:

```python
class TestBuildMinimalQuoteFromUnified:
    def test_all_fields_populated(self):
        from stock_data.api.routes.agent import _build_minimal_quote_from_unified

        q = _build_minimal_quote_from_unified(_mk_unified())
        assert q.price == 1680.0
        assert q.change_pct == 1.23
        assert q.change_amount == 20.4
        assert q.open == 1660.0
        assert q.high == 1690.0
        assert q.low == 1655.0
        assert q.prev_close == 1659.6
        assert q.volume == 12_345_678
        assert q.volume_unit == "share"
        assert q.amount == 2_050_000_000.0  # 元 pass-through
        assert q.turnover_pct == 0.45
        assert q.amplitude_pct == 2.11
        assert q.volume_ratio == 1.2
        assert q.pe_ratio == 25.3
        assert q.pb_ratio == 8.7
        assert q.mcap_yi == pytest.approx(21_123.5)
        assert q.float_mcap_yi == pytest.approx(21_000.1)
        assert q.limit_up == 1825.56
        assert q.limit_down == 1493.64
        # board-only fields stay None on stock/index
        assert q.up_count is None
        assert q.down_count is None
        assert q.net_inflow is None
        assert q.rank is None

    def test_amplitude_fallback_when_upstream_missing(self):
        from stock_data.api.routes.agent import _build_minimal_quote_from_unified

        q = _build_minimal_quote_from_unified(_mk_unified(amplitude=None))
        expected = (1690.0 - 1655.0) / 1659.6 * 100
        assert q.amplitude_pct == pytest.approx(expected, rel=1e-6)

    def test_amplitude_fallback_skipped_when_prev_close_zero(self):
        """Defense-in-depth: don't divide by zero."""
        from stock_data.api.routes.agent import _build_minimal_quote_from_unified

        q = _build_minimal_quote_from_unified(_mk_unified(amplitude=None, pre_close=0.0))
        assert q.amplitude_pct is None

    def test_mcap_yi_divided_by_1e8(self):
        from stock_data.api.routes.agent import _build_minimal_quote_from_unified

        q = _build_minimal_quote_from_unified(
            _mk_unified(total_mv=123_456_789_012.0, circ_mv=987_654_321_098.0)
        )
        assert q.mcap_yi == pytest.approx(1234.56789012)
        assert q.float_mcap_yi == pytest.approx(9876.54321098)

    def test_none_fields_pass_through(self):
        from stock_data.api.routes.agent import _build_minimal_quote_from_unified

        bare = UnifiedRealtimeQuote(code="600519", source=RealtimeSource.AKSHARE)
        q = _build_minimal_quote_from_unified(bare)
        assert q.price is None
        assert q.change_pct is None
        assert q.change_amount is None
        assert q.open is None
        assert q.high is None
        assert q.low is None
        assert q.prev_close is None
        assert q.volume is None
        assert q.volume_unit == "share"  # default fallback when q.volume_unit is ""
        assert q.amount is None
        assert q.turnover_pct is None
        assert q.amplitude_pct is None
        assert q.volume_ratio is None
        assert q.pe_ratio is None
        assert q.pb_ratio is None
        assert q.mcap_yi is None
        assert q.float_mcap_yi is None
        assert q.limit_up is None
        assert q.limit_down is None

    def test_volume_unit_falls_back_to_share_when_empty(self):
        from stock_data.api.routes.agent import _build_minimal_quote_from_unified

        q = _build_minimal_quote_from_unified(_mk_unified(volume_unit=""))
        assert q.volume_unit == "share"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_minimal_quote_helpers.py::TestBuildMinimalQuoteFromUnified -v`
Expected: FAIL with `ImportError: cannot import name '_build_minimal_quote_from_unified'`.

- [ ] **Step 3: Insert the helper in `agent.py`**

Open `stock_data/api/routes/agent.py`. Find `post_boards_batch_profile` (around line 975) and insert the two helpers immediately above its `@router.post` decorator (after the closing `}` of the previous function and its `@router.post(...)` block — i.e. between the `stock_overlap` route and the boards batch-profile route is also fine; the cleanest spot is right before `post_boards_batch_profile`):

```python
def _build_minimal_quote_from_unified(q) -> MinimalQuote:
    """Map a UnifiedRealtimeQuote to the expanded MinimalQuote.

    Mirrors the field-mapping logic in StockQuote.from_unified_quote
    (schemas.py:126) — same fallback rules for amplitude, same 1e8
    division for mcap_yi / float_mcap_yi. Kept here (rather than
    reusing StockQuote.from_unified_quote) to keep the nested-flag /
    current_price-rename / _serialize semantics out of the agent
    path: MinimalQuote is always top-level, never embedded, and the
    helper returns the Pydantic instance directly.
    """
    amplitude = q.amplitude
    if amplitude is None and q.high is not None and q.low is not None and q.pre_close:
        amplitude = (q.high - q.low) / q.pre_close * 100

    def _yi(v):
        return None if v is None else v / 1e8

    return MinimalQuote(
        price=q.price,
        change_pct=q.change_pct,
        change_amount=q.change_amount,
        open=q.open_price,
        high=q.high,
        low=q.low,
        prev_close=q.pre_close,
        volume=q.volume,
        volume_unit=q.volume_unit or "share",
        amount=q.amount,  # UnifiedRealtimeQuote.amount is 元; pass-through
        turnover_pct=q.turnover_rate,
        amplitude_pct=amplitude,
        volume_ratio=q.volume_ratio,
        pe_ratio=q.pe_ratio,
        pb_ratio=q.pb_ratio,
        mcap_yi=_yi(q.total_mv),
        float_mcap_yi=_yi(q.circ_mv),
        limit_up=q.limit_up,
        limit_down=q.limit_down,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_minimal_quote_helpers.py::TestBuildMinimalQuoteFromUnified -v`
Expected: PASS for all 6 tests.

- [ ] **Step 5: Commit**

```bash
git add stock_data/api/routes/agent.py tests/test_minimal_quote_helpers.py
git commit -m "feat(agent): add _build_minimal_quote_from_unified helper

Maps UnifiedRealtimeQuote (stock/index) to the extended MinimalQuote,
mirroring the field-mapping logic in StockQuote.from_unified_quote
without dragging the nested-flag / current_price-rename / _serialize
semantics from the top-level /stocks/{code}/quote path."
```

---

## Task 3: Implement `_build_minimal_quote_from_board_dict`

**Files:**
- Modify: `stock_data/api/routes/agent.py` (immediately after the helper added in Task 2)
- Test: append to `tests/test_minimal_quote_helpers.py`

**Interfaces:**
- Consumes: a `dict` from `manager.get_board_realtime(code, source='ths')`.
- Produces: `MinimalQuote` with `volume_unit="wan_shou"`, `amount=raw*1e8`, and the 4 board-only fields populated.

- [ ] **Step 1: Append failing tests**

Append to `tests/test_minimal_quote_helpers.py`:

```python
class TestBuildMinimalQuoteFromBoardDict:
    def test_populated_fields(self):
        from stock_data.api.routes.agent import _build_minimal_quote_from_board_dict

        raw = {
            "price": 1234.5,
            "change_pct": 1.23,
            "change_amount": 15.0,
            "open": 1230.0,
            "high": 1240.0,
            "low": 1225.0,
            "prev_close": 1219.5,
            "volume": 15343,  # 万手 (int-truncated upstream)
            "amount": 12.5,  # 亿元 upstream
            "up_count": 12,
            "down_count": 5,
            "net_inflow": 1.23,  # 亿元
            "rank": "229/389",
        }
        q = _build_minimal_quote_from_board_dict(raw)
        assert q.price == 1234.5
        assert q.change_pct == 1.23
        assert q.change_amount == 15.0
        assert q.open == 1230.0
        assert q.high == 1240.0
        assert q.low == 1225.0
        assert q.prev_close == 1219.5
        assert q.volume == 15343
        assert q.volume_unit == "wan_shou"
        assert q.amount == pytest.approx(12.5 * 1e8)  # 1.25e9
        assert q.up_count == 12
        assert q.down_count == 5
        assert q.net_inflow == 1.23
        assert q.rank == "229/389"
        # stock-only fields stay None on board
        assert q.turnover_pct is None
        assert q.amplitude_pct is None
        assert q.volume_ratio is None
        assert q.pe_ratio is None
        assert q.pb_ratio is None
        assert q.mcap_yi is None
        assert q.float_mcap_yi is None
        assert q.limit_up is None
        assert q.limit_down is None

    def test_volume_unit_is_wan_shou(self):
        from stock_data.api.routes.agent import _build_minimal_quote_from_board_dict

        q = _build_minimal_quote_from_board_dict({"price": 100.0})
        assert q.volume_unit == "wan_shou"

    def test_amount_multiplied_by_1e8_from_yi(self):
        """Round-trip: upstream 亿元 → response 元 = ×1e8."""
        from stock_data.api.routes.agent import _build_minimal_quote_from_board_dict

        q = _build_minimal_quote_from_board_dict({"amount": 1.23})
        assert q.amount == pytest.approx(123_000_000.0)

    def test_amount_none_when_upstream_missing(self):
        """The None branch must NOT call ×1e8."""
        from stock_data.api.routes.agent import _build_minimal_quote_from_board_dict

        q = _build_minimal_quote_from_board_dict({})
        assert q.amount is None

    def test_net_inflow_pass_through_no_division(self):
        """net_inflow is in 亿元 upstream AND stays in 亿元 in the response
        (server convention for fund flow; no conversion)."""
        from stock_data.api.routes.agent import _build_minimal_quote_from_board_dict

        q = _build_minimal_quote_from_board_dict({"net_inflow": -2.5})
        assert q.net_inflow == -2.5

    def test_empty_dict_returns_default_instance(self):
        from stock_data.api.routes.agent import _build_minimal_quote_from_board_dict

        q = _build_minimal_quote_from_board_dict({})
        assert q.price is None
        assert q.change_pct is None
        assert q.open is None
        assert q.volume is None
        assert q.volume_unit == "wan_shou"  # always set on board
        assert q.amount is None
        assert q.up_count is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_minimal_quote_helpers.py::TestBuildMinimalQuoteFromBoardDict -v`
Expected: FAIL with `ImportError: cannot import name '_build_minimal_quote_from_board_dict'`.

- [ ] **Step 3: Insert the helper in `agent.py`**

Immediately after the helper added in Task 2, insert:

```python
def _build_minimal_quote_from_board_dict(q: dict) -> MinimalQuote:
    """Map a ThsFetcher.get_board_realtime dict to MinimalQuote.

    THS upstream returns volume in 万手 (matches ``volume_unit``) and
    amount in 亿元 — multiplied by 1e8 here to align with the rest
    of the server's API surface (see `routes/boards.py:857`, the
    /boards/{code}/quote route does the same conversion). The 8
    stock-only fields (turnover / amplitude / valuation / 涨跌停)
    stay None; the 4 board-only fields (up_count / down_count /
    net_inflow / rank) are populated.
    """
    raw_amount = q.get("amount")
    return MinimalQuote(
        price=q.get("price"),
        change_pct=q.get("change_pct"),
        change_amount=q.get("change_amount"),
        open=q.get("open"),
        high=q.get("high"),
        low=q.get("low"),
        prev_close=q.get("prev_close"),
        volume=q.get("volume"),  # already int-truncated from upstream "15343.80" string
        volume_unit="wan_shou",
        amount=raw_amount * 1e8 if raw_amount is not None else None,
        up_count=q.get("up_count"),
        down_count=q.get("down_count"),
        net_inflow=q.get("net_inflow"),  # board upstream already 亿元; pass-through
        rank=q.get("rank"),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_minimal_quote_helpers.py::TestBuildMinimalQuoteFromBoardDict -v`
Expected: PASS for all 6 tests.

- [ ] **Step 5: Run all helper tests together**

Run: `.venv/Scripts/python.exe -m pytest tests/test_minimal_quote_helpers.py -v`
Expected: ALL PASS (3 schema + 6 unified + 6 board = 15 tests).

- [ ] **Step 6: Commit**

```bash
git add stock_data/api/routes/agent.py tests/test_minimal_quote_helpers.py
git commit -m "feat(agent): add _build_minimal_quote_from_board_dict helper

Maps the THS /boards/{code}/quote upstream dict to the extended
MinimalQuote. volume_unit hard-coded to 'wan_shou' (THS upstream
returns 万手); amount ×1e8 (THS upstream returns 亿元, server
convention is 元 across the API surface — see routes/boards.py:857).
net_inflow is pass-through (upstream already 亿元)."
```

---

## Task 4: Wire helpers into all three batch-profile route handlers

**Files:**
- Modify: `stock_data/api/routes/agent.py` — three call-site rewrites.

**Interfaces:**
- Consumes: the two helpers from Tasks 2-3.
- Produces: three route handlers that produce the extended MinimalQuote per entry.

- [ ] **Step 1: Update `get_indices_batch_profile` (around line 658)**

Find:

```python
            else:
                quote = MinimalQuote(price=q.price, change_pct=q.change_pct)
```

Replace with:

```python
            else:
                quote = _build_minimal_quote_from_unified(q)
```

- [ ] **Step 2: Update `post_stocks_batch_profile` (around line 905)**

Find:

```python
            if q is not None:
                quote = MinimalQuote(price=q.price, change_pct=q.change_pct)
                name = getattr(q, "name", "") or ""
```

Replace with:

```python
            if q is not None:
                quote = _build_minimal_quote_from_unified(q)
                name = q.name or ""
```

(The `getattr(q, "name", "")` was a defensive guard for hypothetical `q` types that lacked `name`; `UnifiedRealtimeQuote` always has it, and the `or ""` fallback is preserved for empty strings.)

- [ ] **Step 3: Update `post_boards_batch_profile` (around line 1027)**

Find:

```python
            if q is not None:
                quote = MinimalQuote(
                    price=q.get("price"),
                    change_pct=q.get("change_pct"),
                )
```

Replace with:

```python
            if q is not None:
                quote = _build_minimal_quote_from_board_dict(q)
```

- [ ] **Step 4: Verify no `MinimalQuote(...)` direct construction remains in `agent.py`**

Run: `grep -n "MinimalQuote(" stock_data/api/routes/agent.py`
Expected: One match (the new `_build_minimal_quote_from_board_dict` helper) — the three old call sites are gone. If you see additional matches, you've missed a call site.

- [ ] **Step 5: Run existing batch-profile tests to verify no regression**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_batch_features.py tests/test_agent_boards_batch_profile.py -v`
Expected: PASS for all existing tests. The three call-site rewrites are pure field-population changes — no behavior shift for fields the existing tests check.

- [ ] **Step 6: Commit**

```bash
git add stock_data/api/routes/agent.py
git commit -m "refactor(agent): wire MinimalQuote builders into batch-profile routes

Three call-site rewrites in /agent/{indices,stocks,boards}/batch-profile
to use _build_minimal_quote_from_unified / _build_minimal_quote_from_board_dict.
Each entry now exposes the full ~21-field quote block (OHLV + 量价 + 估值
+ 涨跌停 + (board) 板块统计) instead of the legacy 2-field anchor."
```

---

## Task 5: Add `_md_quote_block` helper + render test

**Files:**
- Modify: `stock_data/api/routes/agent.py` (insert above `_md_feature_block`, around line 1410)
- Test: append to `tests/test_minimal_quote_helpers.py`

**Interfaces:**
- Consumes: a `MinimalQuote` instance.
- Produces: four subgroup tables appended to the `out` list (or skips empty subgroups entirely).

- [ ] **Step 1: Append failing render tests**

Append to `tests/test_minimal_quote_helpers.py`:

```python
class TestMdQuoteBlock:
    """Pin the 4-subgroup MD projection: 价格 / 量价 / 估值 / 板块统计.

    Pinned per api-reference.md 'No data is dropped' contract and the
    TestFormatMdFeatureCompleteness pattern.
    """

    def _render(self, q):
        from stock_data.api.routes.agent import _md_quote_block

        out: list[str] = []
        _md_quote_block(out, q)
        return "\n".join(out)

    def test_stock_quote_renders_all_four_subgroups(self):
        q = MinimalQuote(
            price=12.34, change_pct=1.23, change_amount=0.15,
            open=12.20, high=12.40, low=12.10, prev_close=12.19,
            volume=1_234_567, volume_unit="share",
            amount=2_050_000_000.0,
            turnover_pct=0.45, amplitude_pct=2.11, volume_ratio=1.20,
            pe_ratio=25.3, pb_ratio=8.7,
            mcap_yi=21_123.5, float_mcap_yi=21_000.1,
            limit_up=13.41, limit_down=11.10,
        )
        body = self._render(q)
        assert "### 行情" in body
        assert "### 价格" in body
        assert "### 量价" in body
        assert "### 估值" in body
        assert "### 板块统计" not in body  # no board-only fields populated
        # unit-aware volume
        assert "股" in body
        # 涨跌停价 is the 价格 subgroup's last row when present
        assert "涨跌停价" in body

    def test_index_quote_omits_valuation_subgroup(self):
        """Index realtime doesn't carry PE/PB/mcap; the 估值 subgroup must
        be skipped (not rendered with all-`—` cells — that's the
        'computed but blank' anti-pattern)."""
        q = MinimalQuote(
            price=3000.0, change_pct=0.5,
            volume=5_000_000, volume_unit="share",
            amount=1e10,
            turnover_pct=0.3,
        )
        body = self._render(q)
        assert "### 价格" in body
        assert "### 量价" in body
        assert "### 估值" not in body  # all stock-only valuation is None
        assert "### 板块统计" not in body

    def test_board_quote_uses_wan_shou_and_omits_valuation(self):
        q = MinimalQuote(
            price=1234.5, change_pct=1.23,
            volume=15343, volume_unit="wan_shou",
            amount=1_250_000_000.0,
            up_count=12, down_count=5,
            net_inflow=1.23, rank="229/389",
        )
        body = self._render(q)
        assert "### 行情" in body
        assert "### 价格" in body
        assert "### 量价" in body
        assert "### 估值" not in body
        assert "### 板块统计" in body
        assert "万手" in body
        assert "上涨家数" in body
        assert "229/389" in body

    def test_empty_quote_renders_only_header_with_no_subgroups(self):
        """A fully-None MinimalQuote (cold-path failure) renders just the
        heading with no subgroup table — the agent can detect via
        `errors.quote` and via the absent subgroups."""
        body = self._render(MinimalQuote())
        assert "### 行情" in body
        assert "### 价格" not in body  # all values None → subgroup skipped
        assert "### 量价" not in body
        assert "### 估值" not in body
        assert "### 板块统计" not in body

    def test_partial_quote_renders_em_dash_for_none_cells(self):
        """When SOME fields in a subgroup are populated and others None,
        render the subgroup with None cells as '—' (NOT omit the
        subgroup, NOT 'omit the cell')."""
        q = MinimalQuote(
            price=12.34, change_pct=1.23,
            # all other 价格 fields None
            volume=1_000_000, volume_unit="share",
            amount=2_000_000_000.0,
            # turnover / amplitude / volume_ratio all None
        )
        body = self._render(q)
        # 价格 subgroup is rendered (has price+change_pct+change_amount)
        assert "### 价格" in body
        # 量价 subgroup is rendered (has volume+amount)
        assert "### 量价" in body
        # None cells in 价格 show as '—'
        assert "—" in body
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_minimal_quote_helpers.py::TestMdQuoteBlock -v`
Expected: FAIL with `ImportError: cannot import name '_md_quote_block'`.

- [ ] **Step 3: Insert the helper in `agent.py`**

Find `_md_feature_block` (around line 1410 in `agent.py`) and insert `_md_quote_block` immediately above it:

```python
def _md_quote_block(out: list[str], q) -> None:
    """Render the MinimalQuote block as four subgroup tables.

    Skips empty subgroups entirely (see spec §6.2 rationale). Renders
    None cells as "—" via the existing _md_num helper.
    """
    out.append("### 行情")
    out.append("")

    # ── 价格 ──
    price_rows = [
        ("当前", _md_num(q.price, 3)),
        ("涨跌额", _md_num(q.change_amount, 3)),
        ("涨跌幅", _md_pct(q.change_pct)),
        ("今开", _md_num(q.open, 3)),
        ("最高", _md_num(q.high, 3)),
        ("最低", _md_num(q.low, 3)),
        ("昨收", _md_num(q.prev_close, 3)),
    ]
    if q.limit_up is not None or q.limit_down is not None:
        price_rows.append(
            ("涨跌停价", f"{_md_num(q.limit_up, 3)} / {_md_num(q.limit_down, 3)}")
        )
    if any(v and v != "—" for _, v in price_rows):
        _render_dict_block(out, "价格", dict(price_rows))

    # ── 量价 ──
    volume_str = (
        _md_num(q.volume, 0) + (" 股" if q.volume_unit == "share" else " 万手")
        if q.volume is not None
        else "—"
    )
    vol_rows = [
        ("成交量", volume_str),
        ("成交额(元)", _md_num(q.amount, 0)),
    ]
    if q.turnover_pct is not None:
        vol_rows.append(("换手率", _md_pct(q.turnover_pct)))
    if q.amplitude_pct is not None:
        vol_rows.append(("振幅", _md_num(q.amplitude_pct, 2) + "%"))
    if q.volume_ratio is not None:
        vol_rows.append(("量比", _md_num(q.volume_ratio, 2)))
    if any(v and v != "—" for _, v in vol_rows):
        _render_dict_block(out, "量价", dict(vol_rows))

    # ── 估值 (stock only) ──
    val_rows = []
    if q.pe_ratio is not None:
        val_rows.append(("PE", _md_num(q.pe_ratio, 2)))
    if q.pb_ratio is not None:
        val_rows.append(("PB", _md_num(q.pb_ratio, 2)))
    if q.mcap_yi is not None:
        val_rows.append(("总市值(亿)", _md_num(q.mcap_yi)))
    if q.float_mcap_yi is not None:
        val_rows.append(("流通市值(亿)", _md_num(q.float_mcap_yi)))
    if val_rows:
        _render_dict_block(out, "估值", dict(val_rows))

    # ── 板块统计 (board only) ──
    board_rows = []
    if q.up_count is not None:
        board_rows.append(("上涨家数", _md_num(q.up_count, 0)))
    if q.down_count is not None:
        board_rows.append(("下跌家数", _md_num(q.down_count, 0)))
    if q.net_inflow is not None:
        board_rows.append(("资金净流入(亿)", _md_num(q.net_inflow)))
    if q.rank is not None:
        board_rows.append(("涨幅排名", q.rank))
    if board_rows:
        _render_dict_block(out, "板块统计", dict(board_rows))
```

`_md_num`, `_md_pct`, `_render_dict_block` are already defined in `agent.py` above this point.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_minimal_quote_helpers.py::TestMdQuoteBlock -v`
Expected: PASS for all 5 tests.

- [ ] **Step 5: Commit**

```bash
git add stock_data/api/routes/agent.py tests/test_minimal_quote_helpers.py
git commit -m "feat(agent): add _md_quote_block MD projection helper

Renders the extended MinimalQuote as four subgroup tables (价格/量价/
估值/板块统计) per the api-reference.md 'No data is dropped' contract.
Skips empty subgroups entirely; partial subgroups render None cells
as '—' via the existing _md_num helper."
```

---

## Task 6: Wire `_md_quote_block` into the three batch-profile MD templates

**Files:**
- Modify: `stock_data/api/routes/agent.py` — three MD template rewrites (one per batch-profile endpoint).

**Interfaces:**
- Consumes: `_md_quote_block` from Task 5.
- Produces: three updated MD templates that render the quote block on every entry.

- [ ] **Step 1: Update `render_stocks_batch_profile_as_md` (around line 1687)**

Find:

```python
        if entry.quote:
            out.append(f"- 最新: {_md_num(entry.quote.price)} ({_md_pct(entry.quote.change_pct)})")
        out.append("")
```

Replace with:

```python
        quote_err = next((e.message for e in entry.errors if e.aspect == "quote"), None)
        if entry.quote:
            _md_quote_block(out, entry.quote)
        elif quote_err:
            out.append(f"- 行情失败: {quote_err}")
        out.append("")
```

- [ ] **Step 2: Update `render_indices_batch_profile_as_md` (around line 1506)**

Find:

```python
        if idx.quote:
            out.append(f"- 最新: {_md_num(idx.quote.price)} ({_md_pct(idx.quote.change_pct)})")
        else:
            out.append(f"- 行情失败: {(idx.errors or {}).get('quote') or 'no quote'}")
        out.append("")
```

Replace with:

```python
        if idx.quote:
            _md_quote_block(out, idx.quote)
        else:
            out.append(f"- 行情失败: {(idx.errors or {}).get('quote') or 'no quote'}")
        out.append("")
```

- [ ] **Step 3: Update `render_boards_batch_profile_as_md` (around line 1480)**

Find:

```python
        if board.quote:
            out.append(f"- 最新: {_md_num(board.quote.price)} ({_md_pct(board.quote.change_pct)})")
        else:
            err = (board.errors or {}).get("quote") or "no quote"
            out.append(f"- 行情失败: {err}")
        out.append("")
```

Replace with:

```python
        if board.quote:
            _md_quote_block(out, board.quote)
        else:
            err = (board.errors or {}).get("quote") or "no quote"
            out.append(f"- 行情失败: {err}")
        out.append("")
```

- [ ] **Step 4: Verify no legacy single-line quote rendering remains**

Run: `grep -n "最新:" stock_data/api/routes/agent.py`
Expected: ZERO matches. If you see any, you've missed a template.

- [ ] **Step 5: Run the existing MD render tests to verify no regression**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_batch_features.py::TestFormatMdFeatures -v`
Expected: PASS for all `test_*_batch_profile_md` tests. The new `_md_quote_block` output is additive (more lines, not fewer) — the existing assertions (`趋势` / `顶底` / `量价`) still pass.

- [ ] **Step 6: Commit**

```bash
git add stock_data/api/routes/agent.py
git commit -m "feat(agent): wire _md_quote_block into three batch-profile MD templates

render_stocks_batch_profile_as_md, render_indices_batch_profile_as_md,
and render_boards_batch_profile_as_md now emit the 4-subgroup quote
table instead of the legacy single-line '- 最新: X (Y%)' line.
Each template preserves its existing failure-surfacing branch
(errors.quote on indices/boards; per-aspect errors[] on stocks)."
```

---

## Task 7: Extend MD completeness test for new quote subgroups

**Files:**
- Modify: `tests/test_agent_batch_features.py` (append new tests to `TestFormatMdFeatureCompleteness`)

**Interfaces:**
- Consumes: existing test helpers (`_make_unified_quote`, `_stock_request`, `_bind_manager`, `_BOARD_STOCKS_PATCH`).
- Produces: tests that pin the 4-subgroup MD projection at the route level (not just the helper level — Task 5 already pinned the helper).

- [ ] **Step 1: Read the existing test class structure**

Open `tests/test_agent_batch_features.py` around line 537 (`TestFormatMdFeatureCompleteness`). Note that the existing tests use `_render()` to call `_md_feature_block` directly; for quote completeness we need to call the route's MD template instead.

- [ ] **Step 2: Append route-level MD completeness tests**

Append to `TestFormatMdFeatureCompleteness`:

```python
    def test_stocks_batch_profile_md_renders_quote_subgroups(self, client, monkeypatch):
        """api-reference.md 'No data is dropped' — every JSON quote field
        must surface in the MD projection. Stock path includes 价格 +
        量价 + 估值 (no 板块统计)."""
        mock_manager = MagicMock()
        # Populate a UnifiedRealtimeQuote with enough fields to fill all
        # four stock subgroups (价格 / 量价 / 估值; 涨跌停价 triggers when
        # limit_up/limit_down is set).
        q = UnifiedRealtimeQuote(
            code="600519", name="贵州茅台", source=RealtimeSource.ZZSHARE,
            price=1680.0, change_pct=1.23, change_amount=20.4,
            open_price=1660.0, high=1690.0, low=1655.0, pre_close=1659.6,
            volume=12_345_678, volume_unit="share", amount=2_050_000_000.0,
            turnover_rate=0.45, amplitude=2.11, volume_ratio=1.20,
            pe_ratio=25.3, pb_ratio=8.7,
            total_mv=2_112_350_000_000.0, circ_mv=2_100_010_000_000.0,
            limit_up=1825.56, limit_down=1493.64,
        )
        mock_manager.get_realtime_quote.return_value = q
        mock_manager.get_kline_data.return_value = (_make_kline_df(120), "zzshare")
        mock_manager.get_stock_info.return_value = ({"industry": "白酒"}, "zhitu")
        _bind_manager(monkeypatch, mock_manager)
        with patch(_BOARD_STOCKS_PATCH, return_value=([], False, "persistence")):
            resp = client.post(
                "/api/v1/agent/stocks/batch-profile?format=md",
                json=_stock_request(["600519"]),
            )
        assert resp.status_code == 200
        body = resp.text
        assert "### 行情" in body
        assert "### 价格" in body
        assert "### 量价" in body
        assert "### 估值" in body
        assert "### 板块统计" not in body  # stock path has no board-only fields
        # Pin specific values rendered (so a "computed but blank" regression
        # can't pass).
        assert "1,680.000" in body
        assert "+1.23%" in body
        assert "PE" in body
        assert "PB" in body
        assert "涨跌停价" in body

    def test_indices_batch_profile_md_omits_stock_only_subgroups(self, client, monkeypatch):
        """Index path lacks valuation (PE/PB/mcap) and 板块统计.
        Only 价格 + 量价 subgroups render (when populated)."""
        mock_manager = MagicMock()
        q = UnifiedRealtimeQuote(
            code="000300", name="沪深300", source=RealtimeSource.AKSHARE,
            price=3000.0, change_pct=0.5,
            volume=5_000_000, volume_unit="share", amount=1e10,
            turnover_rate=0.3,
        )
        mock_manager.get_index_realtime_quote.return_value = q
        mock_manager.get_kline_data.return_value = (_make_kline_df(120), "akshare")
        _bind_manager(monkeypatch, mock_manager)
        resp = client.get("/api/v1/agent/indices/batch-profile?format=md")
        assert resp.status_code == 200
        body = resp.text
        assert "### 行情" in body
        assert "### 价格" in body
        assert "### 量价" in body
        assert "### 估值" not in body  # all valuation is None on index
        assert "### 板块统计" not in body

    def test_boards_batch_profile_md_renders_board_subgroup(self, client, monkeypatch):
        """Board path emits 板块统计 (上涨/下跌家数 + 资金净流入 + 涨幅排名).
        Use THS-style board realtime dict shape."""
        mock_manager = MagicMock()
        board_quote = {
            "board_code": "885595", "board_name": "人形机器人",
            "price": 1234.5, "change_pct": 1.23, "change_amount": 15.0,
            "open": 1230.0, "high": 1240.0, "low": 1225.0, "prev_close": 1219.5,
            "volume": 15343, "amount": 12.5,  # 万手 / 亿元
            "up_count": 12, "down_count": 5,
            "net_inflow": 1.23, "rank": "229/389",
        }
        mock_manager.get_board_realtime.return_value = (board_quote, "ths")
        mock_manager.get_board_history.return_value = ([
            {"date": "2026-08-01", "open": 1200, "high": 1210, "low": 1190,
             "close": 1205, "volume": 100, "amount": 1_000_000, "pct_chg": 0.5},
        ], "ths")
        _bind_manager(monkeypatch, mock_manager)
        resp = client.post(
            "/api/v1/agent/boards/batch-profile?format=md",
            json={"codes": ["885595"], "frequency": "d", "days": 60},
        )
        assert resp.status_code == 200
        body = resp.text
        assert "### 行情" in body
        assert "### 价格" in body
        assert "### 量价" in body
        assert "### 估值" not in body  # board has no PE/PB
        assert "### 板块统计" in body
        assert "万手" in body  # volume unit annotation
        assert "上涨家数" in body
        assert "229/389" in body
```

- [ ] **Step 3: Run the new tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_batch_features.py::TestFormatMdFeatureCompleteness -v`
Expected: PASS for the 3 new tests AND the existing `test_pivots_params_rendered` / `test_z_anomaly_ohlc_rendered`.

- [ ] **Step 4: Commit**

```bash
git add tests/test_agent_batch_features.py
git commit -m "test(agent): pin 4-subgroup MD projection in batch-profile routes

Three new TestFormatMdFeatureCompleteness tests covering the route-
level MD output of /agent/{stocks,indices,boards}/batch-profile.
Pins that 板块统计 renders for boards, 估值 is omitted for index/
board, and price/change_pct values appear verbatim in MD."
```

---

## Task 8: Add endpoint integration tests

**Files:**
- Modify: `tests/test_agent_endpoints.py` — append three new tests.

**Interfaces:**
- Consumes: existing `client` fixture + MagicMock helpers.
- Produces: tests asserting the JSON path carries the extended MinimalQuote fields.

- [ ] **Step 1: Locate the test file structure**

Open `tests/test_agent_endpoints.py`. Find an existing class like `TestStocksBatchProfile` or `TestAgentEndpoints` and append a new test class at the end of the file.

- [ ] **Step 2: Append the integration tests**

Append to `tests/test_agent_endpoints.py`:

```python
class TestBatchProfileQuoteFields:
    """Pins the JSON-path contract: every extended MinimalQuote field
    is present in the batch-profile response (even when None)."""

    def test_stocks_batch_profile_quote_has_all_23_keys(self, client, monkeypatch):
        from stock_data.api.routes import agent as agent_module
        from stock_data.api.routes import reset_manager

        reset_manager()
        mock_manager = MagicMock()
        q = UnifiedRealtimeQuote(
            code="600519", name="贵州茅台", source=RealtimeSource.ZZSHARE,
            price=1680.0, change_pct=1.23, change_amount=20.4,
            open_price=1660.0, high=1690.0, low=1655.0, pre_close=1659.6,
            volume=12_345_678, volume_unit="share", amount=2_050_000_000.0,
            turnover_rate=0.45, amplitude=2.11, volume_ratio=1.20,
            pe_ratio=25.3, pb_ratio=8.7,
            total_mv=2_112_350_000_000.0, circ_mv=2_100_010_000_000.0,
            limit_up=1825.56, limit_down=1493.64,
        )
        mock_manager.get_realtime_quote.return_value = q
        mock_manager.get_kline_data.return_value = (_make_kline_df(120), "zzshare")
        mock_manager.get_stock_info.return_value = ({"industry": "白酒"}, "zhitu")
        monkeypatch.setattr(agent_module, "get_manager", lambda: mock_manager)
        with patch(_BOARD_STOCKS_PATCH, return_value=([], False, "persistence")):
            resp = client.post(
                "/api/v1/agent/stocks/batch-profile",
                json={"codes": ["600519"], "frequency": "d", "days": 60},
            )
        assert resp.status_code == 200
        data = resp.json()
        quote = data["results"][0]["quote"]
        expected = {
            "price", "change_pct", "change_amount",
            "open", "high", "low", "prev_close",
            "volume", "volume_unit", "amount",
            "turnover_pct", "amplitude_pct", "volume_ratio",
            "pe_ratio", "pb_ratio", "mcap_yi", "float_mcap_yi",
            "limit_up", "limit_down",
            "up_count", "down_count", "net_inflow", "rank",
        }
        assert expected <= set(quote.keys())
        assert quote["volume_unit"] == "share"
        assert quote["amount"] == 2_050_000_000.0
        assert quote["mcap_yi"] == pytest.approx(21_123.5)

    def test_indices_batch_profile_volume_unit_share(self, client, monkeypatch):
        from stock_data.api.routes import agent as agent_module
        from stock_data.api.routes import reset_manager

        reset_manager()
        mock_manager = MagicMock()
        q = UnifiedRealtimeQuote(
            code="000300", name="沪深300", source=RealtimeSource.AKSHARE,
            price=3000.0, change_pct=0.5,
            volume=5_000_000, volume_unit="share", amount=1e10,
            turnover_rate=0.3,
        )
        mock_manager.get_index_realtime_quote.return_value = q
        mock_manager.get_kline_data.return_value = (_make_kline_df(120), "akshare")
        monkeypatch.setattr(agent_module, "get_manager", lambda: mock_manager)
        resp = client.get("/api/v1/agent/indices/batch-profile")
        assert resp.status_code == 200
        data = resp.json()
        for entry in data["indices"]:
            assert entry["quote"]["volume_unit"] == "share"

    def test_boards_batch_profile_volume_unit_wan_shou_and_x1e8(self, client, monkeypatch):
        from stock_data.api.routes import agent as agent_module
        from stock_data.api.routes import reset_manager

        reset_manager()
        mock_manager = MagicMock()
        board_quote = {
            "board_code": "885595", "board_name": "人形机器人",
            "price": 1234.5, "change_pct": 1.23, "change_amount": 15.0,
            "open": 1230.0, "high": 1240.0, "low": 1225.0, "prev_close": 1219.5,
            "volume": 15343, "amount": 12.5,
            "up_count": 12, "down_count": 5,
            "net_inflow": 1.23, "rank": "229/389",
        }
        mock_manager.get_board_realtime.return_value = (board_quote, "ths")
        mock_manager.get_board_history.return_value = ([
            {"date": "2026-08-01", "open": 1200, "high": 1210, "low": 1190,
             "close": 1205, "volume": 100, "amount": 1_000_000, "pct_chg": 0.5},
        ], "ths")
        monkeypatch.setattr(agent_module, "get_manager", lambda: mock_manager)
        resp = client.post(
            "/api/v1/agent/boards/batch-profile",
            json={"codes": ["885595"], "frequency": "d", "days": 60},
        )
        assert resp.status_code == 200
        data = resp.json()
        quote = data["boards"][0]["quote"]
        assert quote["volume_unit"] == "wan_shou"
        assert quote["volume"] == 15343
        assert quote["amount"] == pytest.approx(1_250_000_000.0)  # 12.5 × 1e8
        assert quote["up_count"] == 12
        assert quote["down_count"] == 5
        assert quote["net_inflow"] == 1.23  # 亿元 pass-through
        assert quote["rank"] == "229/389"
        # stock-only fields are None on board
        assert quote["pe_ratio"] is None
        assert quote["mcap_yi"] is None
        assert quote["limit_up"] is None
```

- [ ] **Step 3: Add missing imports if needed**

Verify the test file already imports `UnifiedRealtimeQuote`, `RealtimeSource`, `MagicMock`, `patch`, `pytest`, and `_make_kline_df`. If any is missing, add it at the top:

```python
from unittest.mock import MagicMock, patch

import pytest

from stock_data.api.routes import agent as agent_module
from stock_data.api.routes import reset_manager
from stock_data.data_provider.core.types import RealtimeSource, UnifiedRealtimeQuote
```

`_make_kline_df` lives in `tests/test_agent_batch_features.py`; if `tests/test_agent_endpoints.py` doesn't import it, use a direct inline definition:

```python
import pandas as pd

def _make_kline_df(rows=120, seed=1):
    """Minimal OHLCV frame — see test_agent_batch_features._make_kline_df
    for the canonical helper; we inline a stripped version here to
    avoid cross-file fixture coupling."""
    import random
    rng = random.Random(seed)
    closes = [10.0]
    for _ in range(rows - 1):
        closes.append(closes[-1] * (1 + rng.uniform(-0.02, 0.03)))
    dates = pd.date_range("2026-01-01", periods=rows, freq="B")
    vols = [1_000_000 * (1 + abs(rng.gauss(0, 0.3))) for _ in range(rows)]
    return pd.DataFrame({
        "date": [d.strftime("%Y-%m-%d") for d in dates],
        "open": [round(c * 0.995, 3) for c in closes],
        "high": [round(c * 1.01, 3) for c in closes],
        "low": [round(c * 0.99, 3) for c in closes],
        "close": [round(c, 3) for c in closes],
        "volume": vols,
        "amount": [v * c for v, c in zip(vols, closes, strict=True)],
        "pct_chg": [0.0] * rows,
    })
```

- [ ] **Step 4: Run the new tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_endpoints.py::TestBatchProfileQuoteFields -v`
Expected: PASS for all 3 tests.

- [ ] **Step 5: Commit**

```bash
git add tests/test_agent_endpoints.py
git commit -m "test(agent): pin JSON-path field inventory on three batch-profile routes

Three new endpoint tests asserting:
- stocks: 21-key MinimalQuote with volume_unit='share', amount in 元,
  mcap_yi divided by 1e8 from upstream total_mv.
- indices: volume_unit='share' across all entries.
- boards: volume_unit='wan_shou', amount = upstream.amount × 1e8,
  4 board-only fields populated, 4 stock-only valuation fields None."
```

---

## Task 9: Update CLAUDE.md

**Files:**
- Modify: `CLAUDE.md` — append one paragraph under the "Agent Batch API (`/api/v1/agent/*`)" section.

**Interfaces:**
- Consumes: nothing.
- Produces: a CLAUDE.md note documenting the extended MinimalQuote.

- [ ] **Step 1: Locate the section anchor**

Find the heading `## Agent Batch API (/api/v1/agent/*)` in `CLAUDE.md` (around the middle of the file under "Standardized Data Schema" — verify with `grep -n "Agent Batch API" CLAUDE.md`).

- [ ] **Step 2: Append a new bullet at the end of the "Routes" subsection (or before "Design contract")**

Find the "Design contract" paragraph under the Agent Batch API section and insert the following paragraph immediately BEFORE it:

```markdown
- **Extended `MinimalQuote` (post-2026-08-28).** The `quote` block on
  `/agent/{stocks,indices,boards}/batch-profile` is no longer a 2-field
  anchor (`price` + `change_pct`). It's now a ~21-field `MinimalQuote`
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
```

- [ ] **Step 3: Verify the insertion**

Run: `grep -n "Extended \`MinimalQuote\`\|agent-batch-profile-quote-fields" CLAUDE.md`
Expected: TWO matches (one for the bullet heading, one for the spec reference). If only one shows up, you likely inserted in the wrong location.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: note extended MinimalQuote on batch-profile endpoints

Adds one paragraph under 'Agent Batch API' documenting the 2-field →
~21-field expansion, the volume_unit disambiguation, and the amount
unified-to-元 convention (board upstream 亿元 ×1e8)."
```

---

## Task 10: Final verification + manual smoke

**Files:**
- No file modifications. Pure verification gate.

- [ ] **Step 1: Run the full test suite (default — skips live_network)**

Run: `.venv/Scripts/python.exe -m pytest`
Expected: PASS for all tests. No `x` (xfail) regressions on the new tests; existing tests stay green.

- [ ] **Step 2: Run only the new + extended tests for fast feedback**

Run: `.venv/Scripts/python.exe -m pytest tests/test_minimal_quote_helpers.py tests/test_agent_batch_features.py::TestFormatMdFeatureCompleteness tests/test_agent_endpoints.py::TestBatchProfileQuoteFields -v`
Expected: PASS for all 15+3+3 = 21 new tests added by this plan, plus the 2 pre-existing `TestFormatMdFeatureCompleteness` tests.

- [ ] **Step 3: Live smoke test (optional, requires real upstream)**

Marked `@pytest.mark.live_network` — gated by default.

```python
@pytest.mark.live_network
def test_real_upstream_population_smoke():
    from stock_data.data_provider.manager import DataFetcherManager
    mgr = DataFetcherManager(...)
    s_q = mgr.get_realtime_quote("600519")
    assert s_q.price is not None
    assert s_q.volume is not None  # 股
    assert s_q.amount is not None  # 元
    b_q, _ = mgr.get_board_realtime("885595", source="ths")
    assert b_q["volume"] is not None  # 万手
    assert b_q["amount"] is not None  # 亿元
    print(f"stock: price={s_q.price}, volume={s_q.volume} 股, amount={s_q.amount} 元")
    print(f"board: price={b_q['price']}, volume={b_q['volume']} 万手, amount={b_q['amount']} 亿元")
```

Run (optional): `.venv/Scripts/python.exe -m pytest -m live_network tests/test_minimal_quote_helpers.py -k test_real_upstream_population_smoke -v`
Expected: PASS, with stdout showing the unit-correct values.

- [ ] **Step 4: Confirm branch state**

Run: `git log --oneline -10`
Expected: 9 new commits on top of `7cb3698` (the spec commit), each prefixed with `feat(...)` / `test(...)` / `refactor(...)` / `docs(...)` per the per-task commit message. If the branch is `feat/agent-batch-profile-quote-fields`, that's the expected layout.

- [ ] **Step 5: Push branch (only if the user asks)**

The user controls the push / PR flow. Default: leave the branch local.

---

## Self-Review Notes (writer → reader)

- **Spec coverage**: §1 Background → CLAUDE.md update (Task 9). §2 Public API → Task 1 (schema) + Tasks 4 (call-site rewrites). §3 Schema → Task 1. §4 Helpers → Tasks 2-3. §5 Call-site rewrites → Task 4. §6 MD projection → Tasks 5-6. §7 Error handling → no changes needed (existing contract preserved). §8 Testing → Tasks 1, 5, 7, 8. §9 Rollout → Task 9 (CLAUDE.md) + per-task commits. §10 Open questions → pinned by unit tests in Tasks 2-3.
- **Placeholder scan**: zero `TBD` / `TODO` / "implement later" / "add appropriate" in any task. Every code block is complete.
- **Type consistency**: `MinimalQuote` schema in Task 1 matches the helper return types in Tasks 2-3 matches the MD helper input in Task 5 matches the test fixtures in Tasks 7-8. The `volume_unit` field name is consistent (always `"share"` / `"wan_shou"` literal strings, never aliased).
- **Single-source-of-truth reuse**: `_make_unified_quote` / `_stock_request` / `_bind_manager` / `_BOARD_STOCKS_PATCH` from `tests/test_agent_batch_features.py` are reused in Task 7; Task 8 inlines a stripped `_make_kline_df` to avoid cross-file fixture coupling (a deliberate deviation, justified in the inline comment).
