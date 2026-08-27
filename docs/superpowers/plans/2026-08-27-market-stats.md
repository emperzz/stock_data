# `/api/v1/agent/market-stats` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `GET /api/v1/agent/market-stats` — a server-side aggregator that returns full-market A-share statistics (mean / median / max / min / up-down-flat counts + percentage buckets) for both stocks and boards in a single response, with per-block error isolation so one upstream failure doesn't mask the other block.

**Architecture:** Pure-compute helper module `stock_data/data_provider/utils/stats.py` (no I/O, easy to unit-test). New Pydantic response models in `stock_data/api/schemas.py`. New cache key in `stock_data/api/cache.py`. New route handler in `stock_data/api/routes/agent.py` (extends existing module, same file as the other 6 agent endpoints). New MD template function in the same file. New pytest file `tests/test_agent_market_stats.py`. Two additional small test files (pure-compute unit tests + cache-key tests). No new fetcher, no new manager method, no new `DataCapability` flag.

**Tech Stack:** FastAPI, Pydantic v2, stdlib `statistics.median`, stdlib `dataclasses`. The server already has `manager.get_realtime_quotes("csi")` (single upstream call for full-market stock quotes) and `stock_board_cache.get_all_boards(source="ths", include_quote=True)` (single upstream call for full THS board list + quotes).

## Global Constraints

- **Python path:** Use `.venv/Scripts/python.exe` when present (per CLAUDE.md "Common Commands").
- **Test runner:** Default `pytest` skips `live_network`/`requires_token` markers (per CLAUDE.md). All new tests are pure-mock or pure-compute; no `live_network` needed.
- **Decorator order on new routes:** `@router.get → @endpoint_meta → @map_errors → def` (per CLAUDE.md "Anti-Patterns: Don't reorder decorators"). The route MUST be `@map_errors`-decorated (NOT `@cache_endpoint`-decorated); per-block error isolation is implemented via manual `try/except` inside the handler body.
- **`@endpoint_meta(capabilities=[])`:** Empty list — same as the 6 existing agent endpoints. NO new `DataCapability` flag.
- **Per-block error isolation:** A single upstream failure sets that block to `null` and surfaces the exception in `errors[]`; do NOT abort the whole response.
- **No hardcoded fetcher classes** in route — always go through `manager.get_realtime_quotes` and `stock_board_cache.get_all_boards`.
- **Stock code canonical form:** `normalize_stock_code()` returns bare 6-digit; never leak outbound suffixes (`.SH` / `.SZ`) into response labels.
- **Frequent commits:** Commit after each task. Use `feat:` / `test:` / `docs:` / `chore:` prefixes.

---

## File Structure

| File | Responsibility |
|---|---|
| `stock_data/data_provider/utils/stats.py` (NEW) | Pure-compute helpers: `DistributionBucket`, `AggregateStats`, `STOCK_BUCKET_BIN_WIDTH`, `BOARD_BUCKET_BIN_WIDTH`, `STOCK_BUCKET_EDGES`, `BOARD_BUCKET_EDGES`, `build_stock_buckets`, `build_board_buckets`, `compute_aggregate`. No I/O, no manager / fetcher imports. |
| `stock_data/api/schemas.py` (MODIFY) | Append 4 new Pydantic models: `DistributionBucket`, `StockStats`, `BoardStats`, `MarketStatsErrorEntry`, `MarketStatsResponse`. |
| `stock_data/api/cache.py` (MODIFY) | Add `make_market_stats_cache_key(include_boards: bool) -> str` builder. |
| `stock_data/api/routes/agent.py` (MODIFY) | Add `get_market_stats` handler + `render_market_stats_as_md` template + `_MD_TEMPLATES["market-stats"]` entry. Imports `compute_aggregate`, `build_stock_buckets`, `build_board_buckets`, `STOCK_BUCKET_BIN_WIDTH`, `BOARD_BUCKET_BIN_WIDTH` from `stock_data.data_provider.utils.stats`. |
| `tests/test_stats_compute.py` (NEW) | Unit tests for `compute_aggregate` + bucket templates (no I/O). |
| `tests/test_agent_market_stats.py` (NEW) | Integration tests for the route via `TestClient` with monkeypatched `manager` / `stock_board_cache`. |
| `CLAUDE.md` (MODIFY) | Append one row to the "Agent Batch API (`/api/v1/agent/*`)" table in CLAUDE.md listing the new endpoint. |

The two test files are split so the pure-compute layer can be reviewed independently of the FastAPI layer (matches the convention in other recent plans).

---

## Task 1: Pure-compute helper module

**Files:**
- Create: `stock_data/data_provider/utils/stats.py`
- Test: `tests/test_stats_compute.py`

**Interfaces:**
- Consumes: nothing (foundational; stdlib only)
- Produces:
  - `DistributionBucket(label: str, lower: float | None, upper: float | None, count: int)` (frozen dataclass)
  - `AggregateStats(sample_size: int, mean_pct: float | None, median_pct: float | None, max_pct: float | None, min_pct: float | None, up_count: int, down_count: int, flat_count: int, bin_width: float, buckets: list[DistributionBucket])` (frozen dataclass)
  - Module constants `STOCK_BUCKET_BIN_WIDTH = 3.0`, `BOARD_BUCKET_BIN_WIDTH = 1.0`, `STOCK_BUCKET_EDGES = (-12.0, 12.0)`, `BOARD_BUCKET_EDGES = (-3.0, 3.0)`, `_EPS = 1e-9`
  - `build_stock_buckets() -> list[DistributionBucket]` — 11 buckets
  - `build_board_buckets() -> list[DistributionBucket]` — 9 buckets
  - `compute_aggregate(values: list[float | None], *, bin_width: float, buckets_template: list[DistributionBucket]) -> AggregateStats`

- [ ] **Step 1.1: Write the failing unit tests**

Create `tests/test_stats_compute.py`:

```python
"""Pure-compute unit tests for stock_data.data_provider.utils.stats.

No I/O, no fetcher. The whole file is fast (< 100ms total).
"""
import math

import pytest

from stock_data.data_provider.utils.stats import (
    AggregateStats,
    BOARD_BUCKET_BIN_WIDTH,
    BOARD_BUCKET_EDGES,
    BOARD_BUCKET_BIN_WIDTH as _DUP,  # noqa: F401 — silence re-export check
    DistributionBucket,
    STOCK_BUCKET_BIN_WIDTH,
    STOCK_BUCKET_EDGES,
    build_board_buckets,
    build_stock_buckets,
    compute_aggregate,
)


def test_stock_bucket_template_has_11_buckets():
    buckets = build_stock_buckets()
    assert len(buckets) == 11


def test_stock_bucket_template_edges():
    """11 buckets: (-∞,-12], (-12,-9], (-9,-6], (-6,-3], (-3,0), {0},
    (0,+3], (+3,+6], (+6,+9], (+9,+12], (+12,+∞)."""
    b = build_stock_buckets()
    assert b[0].lower is None and b[0].upper == -12.0
    assert b[1].lower == -12.0 and b[1].upper == -9.0
    assert b[2].lower == -9.0 and b[2].upper == -6.0
    assert b[3].lower == -6.0 and b[3].upper == -3.0
    assert b[4].lower == -3.0 and b[4].upper == 0.0
    assert b[5].lower == 0.0 and b[5].upper == 0.0  # flat bucket
    assert b[6].lower == 0.0 and b[6].upper == 3.0
    assert b[7].lower == 3.0 and b[7].upper == 6.0
    assert b[8].lower == 6.0 and b[8].upper == 9.0
    assert b[9].lower == 9.0 and b[9].upper == 12.0
    assert b[10].lower == 12.0 and b[10].upper is None


def test_board_bucket_template_has_9_buckets():
    buckets = build_board_buckets()
    assert len(buckets) == 9


def test_board_bucket_template_edges():
    """9 buckets: (-∞,-3], (-3,-2], (-2,-1], (-1,0), {0},
    (0,+1], (+1,+2], (+2,+3], (+3,+∞)."""
    b = build_board_buckets()
    assert b[0].lower is None and b[0].upper == -3.0
    assert b[1].lower == -3.0 and b[1].upper == -2.0
    assert b[2].lower == -2.0 and b[2].upper == -1.0
    assert b[3].lower == -1.0 and b[3].upper == 0.0
    assert b[4].lower == 0.0 and b[4].upper == 0.0  # flat
    assert b[5].lower == 0.0 and b[5].upper == 1.0
    assert b[6].lower == 1.0 and b[6].upper == 2.0
    assert b[7].lower == 2.0 and b[7].upper == 3.0
    assert b[8].lower == 3.0 and b[8].upper is None


def test_compute_aggregate_basic_distribution():
    """Hand-picked values exercise mean, median, max, min, up/down/flat,
    and bucket placement."""
    values = [-12.0, -3.0, 0.0, 3.0, 12.0, 13.0]
    agg = compute_aggregate(
        values, bin_width=STOCK_BUCKET_BIN_WIDTH, buckets_template=build_stock_buckets()
    )
    assert agg.sample_size == 6
    assert math.isclose(agg.mean_pct, (-12.0 - 3.0 + 0.0 + 3.0 + 12.0 + 13.0) / 6, rel_tol=1e-9)
    assert agg.median_pct == 1.5       # median of [-12, -3, 0, 3, 12, 13] = (0 + 3) / 2
    assert agg.max_pct == 13.0
    assert agg.min_pct == -12.0
    assert agg.up_count == 3           # 3.0, 12.0, 13.0
    assert agg.down_count == 2         # -12.0, -3.0
    assert agg.flat_count == 1         # 0.0
    assert agg.bin_width == 3.0
    # Bucket counts (by index in template):
    assert agg.buckets[0].count == 1   # (-∞,-12]   catches -12.0
    assert agg.buckets[4].count == 1   # (-3,0)     catches -3.0
    assert agg.buckets[5].count == 1   # {0}        catches 0.0
    assert agg.buckets[6].count == 1   # (0,+3]     catches 3.0
    assert agg.buckets[9].count == 1   # (+9,+12]   catches 12.0
    assert agg.buckets[10].count == 1  # (+12,+∞)   catches 13.0


def test_compute_aggregate_bucket_assignment_edges():
    """Boundary values must land in the correct bucket per the spec's
    left-open right-closed convention with flat-first routing."""
    # -12.0 belongs to (-∞,-12] (closed upper); -11.999 to (-12,-9]
    values = [-12.0, -11.999, -9.0, -3.0, 0.0, 1e-10, 0.001, 3.0, 12.0, 12.001]
    agg = compute_aggregate(
        values, bin_width=STOCK_BUCKET_BIN_WIDTH, buckets_template=build_stock_buckets()
    )
    assert agg.buckets[0].count == 1   # (-∞,-12]    : -12.0
    assert agg.buckets[1].count == 1   # (-12,-9]    : -11.999
    assert agg.buckets[3].count == 1   # (-6,-3]     : -3.0 (closed upper)
    assert agg.buckets[4].count == 0   # (-3,0)
    assert agg.buckets[5].count == 2   # {0}         : 0.0 + 1e-10
    assert agg.buckets[6].count == 1   # (0,+3]      : 0.001
    assert agg.buckets[9].count == 1   # (+9,+12]    : 12.0
    assert agg.buckets[10].count == 1  # (+12,+∞)    : 12.001


def test_compute_aggregate_skips_none():
    """None values are dropped — not in sample_size, not in any bucket."""
    values = [None, None, 1.0]
    agg = compute_aggregate(
        values, bin_width=STOCK_BUCKET_BIN_WIDTH, buckets_template=build_stock_buckets()
    )
    assert agg.sample_size == 1
    assert agg.mean_pct == 1.0
    assert agg.median_pct == 1.0
    assert agg.max_pct == 1.0
    assert agg.min_pct == 1.0
    assert agg.up_count == 1
    assert agg.down_count == 0
    assert agg.flat_count == 0
    # All 11 buckets echoed from template, only the (0,+3] bucket has count=1.
    assert sum(b.count for b in agg.buckets) == 1
    assert agg.buckets[6].count == 1


def test_compute_aggregate_empty_input():
    """Empty input → zero-valued aggregate; full template echoed."""
    agg = compute_aggregate(
        [], bin_width=STOCK_BUCKET_BIN_WIDTH, buckets_template=build_stock_buckets()
    )
    assert agg.sample_size == 0
    assert agg.mean_pct is None
    assert agg.median_pct is None
    assert agg.max_pct is None
    assert agg.min_pct is None
    assert agg.up_count == 0
    assert agg.down_count == 0
    assert agg.flat_count == 0
    assert agg.bin_width == 3.0
    assert len(agg.buckets) == 11
    assert all(b.count == 0 for b in agg.buckets)


def test_compute_aggregate_all_none_input():
    """All-None input → same as empty (sample_size=0, all stats None)."""
    agg = compute_aggregate(
        [None, None], bin_width=STOCK_BUCKET_BIN_WIDTH, buckets_template=build_stock_buckets()
    )
    assert agg.sample_size == 0
    assert agg.mean_pct is None


def test_compute_aggregate_uses_template_invariant():
    """Output buckets length == template length; count labels are stable."""
    template = build_board_buckets()
    agg = compute_aggregate([0.5, -0.5, 0.0], bin_width=1.0, buckets_template=template)
    assert len(agg.buckets) == len(template)
    for out, tpl in zip(agg.buckets, template, strict=True):
        assert out.label == tpl.label
        assert out.lower == tpl.lower
        assert out.upper == tpl.upper


def test_compute_aggregate_board_distribution():
    """Smoke-test the board bucket width and clip boundaries."""
    values = [-3.5, -1.5, -0.5, 0.0, 0.5, 1.5, 3.5]
    agg = compute_aggregate(
        values, bin_width=BOARD_BUCKET_BIN_WIDTH, buckets_template=build_board_buckets()
    )
    assert agg.sample_size == 7
    assert agg.buckets[0].count == 1   # (-∞,-3]   : -3.5
    assert agg.buckets[2].count == 1   # (-2,-1]   : -1.5
    assert agg.buckets[3].count == 1   # (-1,0)    : -0.5
    assert agg.buckets[4].count == 1   # {0}       : 0.0
    assert agg.buckets[5].count == 1   # (0,+1]    : 0.5
    assert agg.buckets[6].count == 1   # (+1,+2]   : 1.5
    assert agg.buckets[8].count == 1   # (+3,+∞)   : 3.5


def test_compute_aggregate_constant_input():
    """All-same-value edge: mean == median == max == min == value."""
    agg = compute_aggregate(
        [2.0] * 5, bin_width=STOCK_BUCKET_BIN_WIDTH, buckets_template=build_stock_buckets()
    )
    assert agg.sample_size == 5
    assert agg.mean_pct == 2.0
    assert agg.median_pct == 2.0
    assert agg.max_pct == 2.0
    assert agg.min_pct == 2.0
    # 2.0 falls in (0, +3] (index 6)
    assert agg.buckets[6].count == 5
```

- [ ] **Step 1.2: Run the tests; expect import errors**

Run: `.venv/Scripts/python.exe -m pytest tests/test_stats_compute.py -v`
Expected: `ModuleNotFoundError: No module named 'stock_data.data_provider.utils.stats'` (or `cannot import name 'compute_aggregate'`).

- [ ] **Step 1.3: Create `stock_data/data_provider/utils/stats.py`**

Create the file with the following content:

```python
"""Pure-compute distribution aggregation for change_pct values.

Used by /api/v1/agent/market-stats. Bucket math lives here so the
route layer stays a thin orchestration wrapper. No I/O, no fetcher
imports — easy to unit-test with synthetic value lists.
"""

from __future__ import annotations

from dataclasses import dataclass
import statistics
from typing import Iterable


@dataclass(frozen=True)
class DistributionBucket:
    """One percentage bucket in the distribution.

    Convention: left-open right-closed `[lower, upper]` for interior
    buckets. The ±∞ boundary buckets have one of {lower, upper} = None.
    The flat bucket has lower == upper == 0 and is checked FIRST in
    `_assign` (so a value of exactly 0 lands there, not in either
    adjacent open bucket).
    """

    label: str
    lower: float | None
    upper: float | None
    count: int


@dataclass(frozen=True)
class AggregateStats:
    """Aggregated statistics over a non-None change_pct series."""

    sample_size: int
    mean_pct: float | None
    median_pct: float | None
    max_pct: float | None
    min_pct: float | None
    up_count: int
    down_count: int
    flat_count: int
    bin_width: float
    buckets: list[DistributionBucket]


# Module-level constants — kept here so the route layer reads them
# from one place and the unit tests can pin the values.
STOCK_BUCKET_BIN_WIDTH = 3.0
STOCK_BUCKET_EDGES = (-12.0, 12.0)
BOARD_BUCKET_BIN_WIDTH = 1.0
BOARD_BUCKET_EDGES = (-3.0, 3.0)

_EPS = 1e-9


def _label(left: float | None, right: float | None) -> str:
    """Render a bucket label matching the JSON example in the spec."""
    lo = "-∞" if left is None else f"{left:+.0f}%"
    hi = "+∞" if right is None else f"{right:+.0f}%"
    return f"({lo}, {hi}]"


def build_stock_buckets() -> list[DistributionBucket]:
    """11 buckets (left-open right-closed, flat = {0}).

    Order: (-∞,-12%], (-12%,-9%], (-9%,-6%], (-6%,-3%], (-3%,0),
    {0}, (0,+3%], (+3%,+6%], (+6%,+9%], (+9%,+12%], (+12%,+∞).
    """
    return [
        DistributionBucket(_label(None, -12.0), lower=None, upper=-12.0, count=0),
        DistributionBucket(_label(-12.0, -9.0), lower=-12.0, upper=-9.0, count=0),
        DistributionBucket(_label(-9.0, -6.0), lower=-9.0, upper=-6.0, count=0),
        DistributionBucket(_label(-6.0, -3.0), lower=-6.0, upper=-3.0, count=0),
        DistributionBucket(_label(-3.0, 0.0), lower=-3.0, upper=0.0, count=0),
        DistributionBucket("0% (平盘)", lower=0.0, upper=0.0, count=0),
        DistributionBucket(_label(0.0, 3.0), lower=0.0, upper=3.0, count=0),
        DistributionBucket(_label(3.0, 6.0), lower=3.0, upper=6.0, count=0),
        DistributionBucket(_label(6.0, 9.0), lower=6.0, upper=9.0, count=0),
        DistributionBucket(_label(9.0, 12.0), lower=9.0, upper=12.0, count=0),
        DistributionBucket(_label(12.0, None), lower=12.0, upper=None, count=0),
    ]


def build_board_buckets() -> list[DistributionBucket]:
    """9 buckets (same convention as stocks):

    (-∞,-3%], (-3%,-2%], (-2%,-1%], (-1%,0),
    {0},
    (0,+1%], (+1%,+2%], (+2%,+3%], (+3%,+∞).
    """
    return [
        DistributionBucket(_label(None, -3.0), lower=None, upper=-3.0, count=0),
        DistributionBucket(_label(-3.0, -2.0), lower=-3.0, upper=-2.0, count=0),
        DistributionBucket(_label(-2.0, -1.0), lower=-2.0, upper=-1.0, count=0),
        DistributionBucket(_label(-1.0, 0.0), lower=-1.0, upper=0.0, count=0),
        DistributionBucket("0% (平盘)", lower=0.0, upper=0.0, count=0),
        DistributionBucket(_label(0.0, 1.0), lower=0.0, upper=1.0, count=0),
        DistributionBucket(_label(1.0, 2.0), lower=1.0, upper=2.0, count=0),
        DistributionBucket(_label(2.0, 3.0), lower=2.0, upper=3.0, count=0),
        DistributionBucket(_label(3.0, None), lower=3.0, upper=None, count=0),
    ]


def _assign(value: float, buckets: list[DistributionBucket]) -> DistributionBucket:
    """Route a single non-None value to its bucket.

    Flat bucket is checked FIRST; interior buckets are left-open
    right-closed `[lower, upper]`. Returns the matching bucket, or
    raises AssertionError if no bucket matches (should be unreachable
    given the ±∞ boundaries; signals a buggy template).
    """
    if abs(value) <= _EPS:
        for b in buckets:
            if b.lower == 0.0 and b.upper == 0.0:
                return b
        raise AssertionError("flat bucket missing from template")

    for b in buckets:
        if b.lower == 0.0 and b.upper == 0.0:
            continue  # already routed above
        lo_ok = (b.lower is None) or value > b.lower
        hi_ok = (b.upper is None) or value <= b.upper
        if lo_ok and hi_ok:
            return b
    raise AssertionError(f"value {value} did not fall in any bucket")


def compute_aggregate(
    values: Iterable[float | None],
    *,
    bin_width: float,
    buckets_template: list[DistributionBucket],
) -> AggregateStats:
    """Aggregate a list of change_pct values.

    - None values are skipped (not in sample_size, not in any bucket).
    - flat = |v| <= 1e-9 (rounded-to-zero guard).
    - Empty / all-None input → zero-valued aggregate; full template
      echoed with all counts = 0.
    - Median via statistics.median; StatisticsError on empty input is
      swallowed and None is returned.
    """
    cleaned: list[float] = [v for v in values if v is not None]
    sample_size = len(cleaned)

    mean_pct: float | None = None
    median_pct: float | None = None
    max_pct: float | None = None
    min_pct: float | None = None
    up_count = 0
    down_count = 0
    flat_count = 0

    if sample_size:
        mean_pct = statistics.fmean(cleaned)
        try:
            median_pct = statistics.median(cleaned)
        except statistics.StatisticsError:
            median_pct = None
        max_pct = max(cleaned)
        min_pct = min(cleaned)
        for v in cleaned:
            if abs(v) <= _EPS:
                flat_count += 1
            elif v > 0:
                up_count += 1
            else:
                down_count += 1

    # Bucket template copy with counts filled in
    buckets = [
        DistributionBucket(
            label=tpl.label,
            lower=tpl.lower,
            upper=tpl.upper,
            count=0,
        )
        for tpl in buckets_template
    ]
    if sample_size:
        for v in cleaned:
            matched = _assign(v, buckets)
            idx = buckets.index(matched)
            buckets[idx] = DistributionBucket(
                label=matched.label,
                lower=matched.lower,
                upper=matched.upper,
                count=matched.count + 1,
            )

    return AggregateStats(
        sample_size=sample_size,
        mean_pct=mean_pct,
        median_pct=median_pct,
        max_pct=max_pct,
        min_pct=min_pct,
        up_count=up_count,
        down_count=down_count,
        flat_count=flat_count,
        bin_width=bin_width,
        buckets=buckets,
    )
```

- [ ] **Step 1.4: Run tests; expect PASS**

Run: `.venv/Scripts/python.exe -m pytest tests/test_stats_compute.py -v`
Expected: 12 passed.

- [ ] **Step 1.5: Commit**

```bash
git add stock_data/data_provider/utils/stats.py tests/test_stats_compute.py
git commit -m "feat(stats): pure-compute helper for /agent/market-stats distribution aggregation

Adds stock_data.data_provider.utils.stats with DistributionBucket,
AggregateStats, build_stock_buckets (11 buckets), build_board_buckets
(9 buckets), and compute_aggregate (mean/median/max/min/up/down/flat
counts plus bucket assignment). Bucket convention: left-open
right-closed [lower, upper] for interior buckets, {0} flat bucket
checked first, +/-infinity boundaries via None. No I/O — easy to
unit-test with synthetic value lists.

12 unit tests pin the bucket template edges, boundary-value routing
(-12.0 / -11.999 / 0.0 / 1e-10 / 12.0 / 12.001), None-skipping,
empty input, and constant-input edges.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 2: Pydantic schemas

**Files:**
- Modify: `stock_data/api/schemas.py` (append at end)
- Test: `tests/test_agent_market_stats_schemas.py`

**Interfaces:**
- Consumes: nothing (foundational)
- Produces: 5 new Pydantic classes exported from `stock_data.api.schemas`:
  - `DistributionBucket(label: str, lower: float | None, upper: float | None, count: int)`
  - `StockStats(sample_size, mean_pct, median_pct, max_pct, min_pct, up_count, down_count, flat_count, bin_width=3.0, buckets: list[DistributionBucket])`
  - `BoardStats(sample_size, mean_pct, median_pct, max_pct, min_pct, up_count, down_count, flat_count, bin_width=1.0, source: str, buckets: list[DistributionBucket])`
  - `MarketStatsErrorEntry(block: Literal["stocks","boards"], error: str, message: str)`
  - `MarketStatsResponse(stocks: StockStats | None, boards: BoardStats | None, errors: list[MarketStatsErrorEntry], summary: dict)`

- [ ] **Step 2.1: Write failing schema tests**

Create `tests/test_agent_market_stats_schemas.py`:

```python
"""Schema validation tests for GET /api/v1/agent/market-stats."""
from stock_data.api.schemas import (
    BoardStats,
    DistributionBucket,
    MarketStatsErrorEntry,
    MarketStatsResponse,
    StockStats,
)


def _bucket(label: str, lower, upper, count: int) -> DistributionBucket:
    return DistributionBucket(label=label, lower=lower, upper=upper, count=count)


def test_distribution_bucket_serialization():
    b = _bucket("(-∞, -12%]", None, -12.0, 8)
    assert b.model_dump() == {"label": "(-∞, -12%]", "lower": None, "upper": -12.0, "count": 8}


def test_stock_stats_default_bin_width_is_3():
    s = StockStats(
        sample_size=10,
        mean_pct=0.5,
        median_pct=0.3,
        max_pct=2.0,
        min_pct=-1.0,
        up_count=6,
        down_count=3,
        flat_count=1,
        buckets=[_bucket("(-∞, -12%]", None, -12.0, 0)],
    )
    assert s.bin_width == 3.0
    assert s.sample_size == 10


def test_board_stats_default_bin_width_is_1_and_carries_source():
    s = BoardStats(
        sample_size=5,
        mean_pct=None,
        median_pct=None,
        max_pct=None,
        min_pct=None,
        up_count=0,
        down_count=0,
        flat_count=0,
        source="ths",
        buckets=[],
    )
    assert s.bin_width == 1.0
    assert s.source == "ths"


def test_market_stats_error_entry_block_literal():
    e = MarketStatsErrorEntry(block="stocks", error="DataFetchError", message="upstream down")
    assert e.block == "stocks"
    assert e.error == "DataFetchError"


def test_market_stats_response_accepts_null_blocks():
    r = MarketStatsResponse(
        stocks=None,
        boards=None,
        errors=[
            MarketStatsErrorEntry(block="stocks", error="DataFetchError", message="x"),
            MarketStatsErrorEntry(block="boards", error="ValueError", message="y"),
        ],
        summary={"requested": 2, "ok": 0, "failed": 2, "elapsed_ms": 42},
    )
    assert r.stocks is None and r.boards is None
    assert len(r.errors) == 2
    assert r.summary["ok"] == 0


def test_market_stats_response_summary_is_dict():
    """summary stays a free-form dict so we don't lock ourselves to a
    fixed schema before the contract stabilises (matches the pattern
    in IndicesBatchProfileResponse / MarketContextResponse)."""
    r = MarketStatsResponse(stocks=None, boards=None, errors=[], summary={})
    assert r.summary == {}
```

- [ ] **Step 2.2: Run tests; expect import errors**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_market_stats_schemas.py -v`
Expected: `ImportError: cannot import name 'DistributionBucket' from 'stock_data.api.schemas'`.

- [ ] **Step 2.3: Append schemas to `stock_data/api/schemas.py`**

Open `stock_data/api/schemas.py`, scroll to the end of the file, and append:

```python
# ---------------------------------------------------------------------------
# GET /api/v1/agent/market-stats
# ---------------------------------------------------------------------------
from typing import Literal as _Literal


class DistributionBucket(BaseModel):
    """One percentage bucket in the distribution (see stats.py).

    Convention: left-open right-closed `[lower, upper]` for interior
    buckets. ±∞ boundary buckets have one of {lower, upper} = None.
    Flat bucket has lower == upper == 0.
    """

    label: str
    lower: float | None
    upper: float | None
    count: int = Field(ge=0)


class StockStats(BaseModel):
    """Full-market A-share statistics."""

    sample_size: int = Field(ge=0)
    mean_pct: float | None
    median_pct: float | None
    max_pct: float | None
    min_pct: float | None
    up_count: int = Field(ge=0)
    down_count: int = Field(ge=0)
    flat_count: int = Field(ge=0)
    bin_width: float = 3.0
    buckets: list[DistributionBucket]


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


class MarketStatsErrorEntry(BaseModel):
    """One per-block failure surfaced in errors[]."""

    block: _Literal["stocks", "boards"]
    error: str
    message: str


class MarketStatsResponse(BaseModel):
    """Top-level response for /agent/market-stats.

    Either block may be `null` (the upstream call failed); the failure
    is captured in `errors[]`. `summary` mirrors the contract used by
    IndicesBatchProfileResponse / MarketContextResponse:
    `{requested, ok, failed, elapsed_ms}`.
    """

    stocks: StockStats | None
    boards: BoardStats | None
    errors: list[MarketStatsErrorEntry]
    summary: dict
```

> **Note:** If `schemas.py` already has a `from typing import Literal` at the top, use that import and skip the `from typing import Literal as _Literal` line. Read the top of the file first; if the symbol `Literal` is already imported, just use it directly. Do not duplicate imports.

- [ ] **Step 2.4: Run tests; expect PASS**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_market_stats_schemas.py -v`
Expected: 6 passed.

- [ ] **Step 2.5: Commit**

```bash
git add stock_data/api/schemas.py tests/test_agent_market_stats_schemas.py
git commit -m "feat(schemas): add 5 Pydantic models for /agent/market-stats

- DistributionBucket (label/lower/upper/count)
- StockStats (sample_size + 6 stats + bin_width=3.0 default + buckets)
- BoardStats (same shape + source + bin_width=1.0 default)
- MarketStatsErrorEntry (block: Literal[stocks,boards])
- MarketStatsResponse (stocks/boards optional + errors[] + summary dict)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 3: Cache key builder

**Files:**
- Modify: `stock_data/api/cache.py` (append one function after the existing `make_stocks_batch_profile_cache_key`)
- Test: `tests/test_cache_keys.py` (extend the existing cache-key test file if it exists, else create it)

**Interfaces:**
- Consumes: nothing
- Produces: `make_market_stats_cache_key(include_boards: bool) -> str` exported from `stock_data.api.cache`.

- [ ] **Step 3.1: Inspect existing cache-key test file**

Run: `ls tests/ | grep -i cache` (or check `tests/test_cache.py` if present).

If a cache-key test file already exists with a pattern for testing `make_*_cache_key` builders, append a new test there. Otherwise create `tests/test_cache_keys.py` with:

```python
"""Smoke tests for agent-endpoint cache-key builders."""
from stock_data.api.cache import make_market_stats_cache_key


def test_market_stats_cache_key_includes_include_boards():
    assert make_market_stats_cache_key(True) == "agent_market_stats:True"
    assert make_market_stats_cache_key(False) == "agent_market_stats:False"


def test_market_stats_cache_keys_are_distinct():
    """Two calls with different include_boards produce different entries —
    critical so the boards-skipped response doesn't pollute the
    boards-included cache."""
    assert make_market_stats_cache_key(True) != make_market_stats_cache_key(False)
```

- [ ] **Step 3.2: Run tests; expect import error**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cache_keys.py::test_market_stats_cache_key_includes_include_boards -v`
Expected: `ImportError: cannot import name 'make_market_stats_cache_key'`.

- [ ] **Step 3.3: Append the cache-key builder to `stock_data/api/cache.py`**

Open `stock_data/api/cache.py`, find the end of the file (after `make_stocks_batch_profile_cache_key`), and append:

```python
def make_market_stats_cache_key(include_boards: bool) -> str:
    """Cache key for GET /api/v1/agent/market-stats.

    Independent of ``format`` (json/md share one cache entry, same
    convention as every other agent endpoint). 60s TTL via
    ``get_quote_cache``.
    """
    return f"agent_market_stats:{include_boards}"
```

- [ ] **Step 3.4: Run tests; expect PASS**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cache_keys.py -v`
Expected: 2 passed.

- [ ] **Step 3.5: Commit**

```bash
git add stock_data/api/cache.py tests/test_cache_keys.py
git commit -m "feat(cache): add make_market_stats_cache_key for /agent/market-stats

Boolean include_boards param drives the key so the boards-skipped
and boards-included variants never share a cache entry.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 4: Route handler — core JSON path

**Files:**
- Modify: `stock_data/api/routes/agent.py` (add new imports near the top + the route handler; do NOT modify existing routes)
- Test: `tests/test_agent_market_stats.py` (NEW)

**Interfaces:**
- Consumes:
  - `from stock_data.data_provider.utils.stats import (BOARD_BUCKET_BIN_WIDTH, STOCK_BUCKET_BIN_WIDTH, build_board_buckets, build_stock_buckets, compute_aggregate)` (added to existing imports block)
  - `make_market_stats_cache_key` from `stock_data.api.cache`
  - `BoardStats, DistributionBucket, MarketStatsErrorEntry, MarketStatsResponse, StockStats` from `stock_data.api.schemas`
- Produces: `get_market_stats(include_boards: bool, format: str) -> Response` registered on the existing `router` with `@router.get("/agent/market-stats", ...)`. JSON branch returns the `MarketStatsResponse` Pydantic instance; MD branch returns via `_render_agent(...)`.

- [ ] **Step 4.1: Write failing integration tests**

Create `tests/test_agent_market_stats.py`:

```python
"""Integration tests for GET /api/v1/agent/market-stats.

All tests mock at the FastAPI route layer (manager + stock_board_cache)
so they're fast and don't touch the network.
"""
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from stock_data.api.cache import make_market_stats_cache_key
from stock_data.api.routes import agent as agent_module
from stock_data.data_provider.base import DataFetchError
from stock_data.data_provider.core.types import UnifiedRealtimeQuote


# ----- fixtures -----


@pytest.fixture
def client():
    """Fresh FastAPI TestClient per test; cache cleared by
    ENABLE_API_CACHE off + key isolation in each test."""
    from stock_data.server import app

    # Disable cache for the duration of these tests so each one starts
    # cold. Set the env var BEFORE importing app — see test_setup below.
    import os
    os.environ["ENABLE_API_CACHE"] = "false"
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clear_quote_cache():
    """Reset the in-memory quote cache between tests so a 60s TTL
    doesn't leak state across tests."""
    from stock_data.api.cache import get_quote_cache

    cache = get_quote_cache()
    cache.clear()
    yield
    cache.clear()


def _make_quote(code: str, change_pct, name: str = "—"):
    """Build a UnifiedRealtimeQuote with the fields the route reads."""
    return UnifiedRealtimeQuote(
        code=code,
        name=name,
        price=10.0,
        open=10.0,
        high=10.0,
        low=10.0,
        prev_close=10.0,
        volume=0,
        amount=0,
        change_pct=change_pct,
        change_amount=0.0,
        turnover_rate=0.0,
        amplitude=0.0,
        pe_ratio=None,
        pb_ratio=None,
        total_mv=None,
        circulating_mv=None,
    )


def _patch_manager(monkeypatch, *, quotes, get_all_boards_return):
    """Patch both the manager methods the route uses."""
    fake_manager = MagicMock()
    fake_manager.get_realtime_quotes.return_value = (quotes, "akshare")
    fake_manager.get_all_boards.return_value = get_all_boards_return
    monkeypatch.setattr(agent_module, "get_manager", lambda: fake_manager)
    return fake_manager


def _patch_board_cache(monkeypatch, *, all_boards_payload):
    """Patch stock_board_cache.get_all_boards used inside the route."""
    fake_cache = MagicMock()
    fake_cache.get_all_boards.return_value = all_boards_payload
    monkeypatch.setattr(agent_module, "stock_board_cache", fake_cache)
    return fake_cache


# ----- happy path -----


def test_market_stats_returns_200(client, monkeypatch):
    """Happy path — both blocks populated, summary reports 2/2 ok."""
    quotes = [_make_quote("600000", 1.0), _make_quote("600001", -1.0), _make_quote("600002", 0.0)]
    boards = [{"code": "BK0001", "name": "X", "change_pct": 0.5}]
    _patch_manager(monkeypatch, quotes=quotes, get_all_boards_return=(boards, "ths"))
    _patch_board_cache(monkeypatch, all_boards_payload=(boards, "ths"))

    resp = client.get("/api/v1/agent/market-stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body["stocks"]["sample_size"] == 3
    assert body["stocks"]["up_count"] == 1
    assert body["stocks"]["down_count"] == 1
    assert body["stocks"]["flat_count"] == 1
    assert body["boards"]["sample_size"] == 1
    assert body["boards"]["source"] == "ths"
    assert body["errors"] == []
    assert body["summary"]["requested"] == 2
    assert body["summary"]["ok"] == 2


# ----- error isolation -----


def test_stocks_upstream_failure_does_not_affect_boards(client, monkeypatch):
    """When get_realtime_quotes raises, stocks=null but boards is still populated."""
    fake_manager = MagicMock()
    fake_manager.get_realtime_quotes.side_effect = DataFetchError("upstream down")
    monkeypatch.setattr(agent_module, "get_manager", lambda: fake_manager)
    boards = [{"code": "BK0001", "name": "X", "change_pct": 0.5}]
    _patch_board_cache(monkeypatch, all_boards_payload=(boards, "ths"))

    resp = client.get("/api/v1/agent/market-stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body["stocks"] is None
    assert body["boards"] is not None
    assert body["boards"]["sample_size"] == 1
    assert any(e["block"] == "stocks" for e in body["errors"])
    assert body["summary"]["ok"] == 1
    assert body["summary"]["failed"] == 1


def test_boards_upstream_failure_does_not_affect_stocks(client, monkeypatch):
    """Symmetric — boards=null but stocks still populated."""
    quotes = [_make_quote("600000", 1.0)]
    _patch_manager(monkeypatch, quotes=quotes, get_all_boards_return=([], ""))
    fake_cache = MagicMock()
    fake_cache.get_all_boards.side_effect = ValueError("cid_unresolved")
    monkeypatch.setattr(agent_module, "stock_board_cache", fake_cache)

    resp = client.get("/api/v1/agent/market-stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body["stocks"] is not None
    assert body["boards"] is None
    assert any(e["block"] == "boards" for e in body["errors"])
    assert body["summary"]["ok"] == 1


def test_both_blocks_fail(client, monkeypatch):
    """Both upstream failures — both null, 2 errors, summary.ok=0."""
    fake_manager = MagicMock()
    fake_manager.get_realtime_quotes.side_effect = DataFetchError("stocks down")
    monkeypatch.setattr(agent_module, "get_manager", lambda: fake_manager)
    fake_cache = MagicMock()
    fake_cache.get_all_boards.side_effect = RuntimeError("boards down")
    monkeypatch.setattr(agent_module, "stock_board_cache", fake_cache)

    resp = client.get("/api/v1/agent/market-stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body["stocks"] is None
    assert body["boards"] is None
    assert len(body["errors"]) == 2
    assert body["summary"]["ok"] == 0
    assert body["summary"]["requested"] == 2


# ----- include_boards toggle -----


def test_include_boards_false_skips_boards_upstream(client, monkeypatch):
    """?include_boards=false must NOT invoke any boards upstream call."""
    quotes = [_make_quote("600000", 1.0)]
    fake_manager = MagicMock()
    fake_manager.get_realtime_quotes.return_value = (quotes, "akshare")
    monkeypatch.setattr(agent_module, "get_manager", lambda: fake_manager)
    fake_cache = MagicMock()
    monkeypatch.setattr(agent_module, "stock_board_cache", fake_cache)

    resp = client.get("/api/v1/agent/market-stats?include_boards=false")
    assert resp.status_code == 200
    body = resp.json()
    assert body["stocks"] is not None
    assert body["boards"] is None
    assert body["errors"] == []
    assert body["summary"]["requested"] == 1
    assert body["summary"]["ok"] == 1
    # Boards upstream NEVER called — fake_cache.get_all_boards.assert_not_called()
    fake_cache.get_all_boards.assert_not_called()


# ----- format dispatch -----


def test_format_md_returns_markdown(client, monkeypatch):
    """?format=md → text/markdown; body contains expected section headers."""
    quotes = [_make_quote("600000", 1.0)]
    boards = [{"code": "BK0001", "name": "白酒", "change_pct": 0.5}]
    _patch_manager(monkeypatch, quotes=quotes, get_all_boards_return=(boards, "ths"))
    _patch_board_cache(monkeypatch, all_boards_payload=(boards, "ths"))

    resp = client.get("/api/v1/agent/market-stats?format=md")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/markdown")
    body = resp.text
    assert "# 市场全量统计" in body
    assert "## 个股" in body
    assert "## 板块" in body
    assert "## 失败列表" in body
    assert "## 汇总" in body


def test_format_invalid_returns_422(client):
    """Unknown format → 422 (handled by Query pattern in the handler)."""
    resp = client.get("/api/v1/agent/market-stats?format=xml")
    assert resp.status_code == 422


# ----- cache key -----


def test_cache_key_includes_include_boards():
    assert make_market_stats_cache_key(True) == "agent_market_stats:True"
    assert make_market_stats_cache_key(False) == "agent_market_stats:False"
    assert make_market_stats_cache_key(True) != make_market_stats_cache_key(False)
```

> **Note on fixture:** `client` fixture sets `ENABLE_API_CACHE=false` so each test starts cold. The `_clear_quote_cache` autouse fixture is a belt-and-suspenders defense against cross-test TTL leaks.

- [ ] **Step 4.2: Run the integration tests; expect import / NotImplemented errors**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_market_stats.py -v`
Expected: `404` (route doesn't exist yet) for the route tests, OR `ImportError` for missing schema imports.

- [ ] **Step 4.3: Add imports to `stock_data/api/routes/agent.py`**

Open `stock_data/api/routes/agent.py`. Find the existing `from ..schemas import (...)` block (around line 59-86) and append the new schema imports to the same import group:

```python
    BoardStats,
    DistributionBucket,
    MarketContextDragonTiger,
    MarketContextDragonTigerSummary,
    MarketContextDragonTigerSummaryTop,
    MarketContextLimitPools,
    MarketContextMessages,
    MarketContextResponse,
    MarketStatsErrorEntry,
    MarketStatsResponse,
    StockBatchAspectError,
    StockBatchProfileEntry,
    StockBatchProfileRequest,
    StockBatchProfileResponse,
    StockQuote,
    StockStats,
    StocksBoardOverlapPair,
    StocksBoardOverlapRequest,
    StocksBoardOverlapResponse,
    StocksBoardOverlapStockSet,
```

(Insert `BoardStats`, `DistributionBucket`, `MarketStatsErrorEntry`, `MarketStatsResponse`, `StockStats` alphabetically into the existing list. Do not duplicate any name already there.)

Next, find the existing `from ..cache import (...)` block and append:

```python
    make_indices_batch_profile_cache_key,
    make_market_context_cache_key,
    make_market_stats_cache_key,
    make_stocks_batch_profile_cache_key,
    make_stocks_board_overlap_cache_key,
```

(Insert `make_market_stats_cache_key` alphabetically.)

Finally, append a new import block after the existing `from .helpers import (...)` line:

```python
from ...data_provider.utils.stats import (
    BOARD_BUCKET_BIN_WIDTH,
    STOCK_BUCKET_BIN_WIDTH,
    build_board_buckets,
    build_stock_buckets,
    compute_aggregate,
)
```

- [ ] **Step 4.4: Append the route handler at the end of `stock_data/api/routes/agent.py`**

Find the last route handler (the `def post_stocks_batch_profile(...)` block) and append the new route + helper immediately after its closing line but **before** the `# === MD projection layer ===` comment block:

```python
def _stats_block_from_aggregate(
    agg, *, bin_width_default: float, source: str = ""
) -> dict:
    """Convert an AggregateStats dataclass into the dict shape the
    StockStats / BoardStats Pydantic models expect.

    Splits on `bin_width_default` to pick the right model:
      3.0 → StockStats (no source field)
      1.0 → BoardStats (carries source)
    """
    common = {
        "sample_size": agg.sample_size,
        "mean_pct": agg.mean_pct,
        "median_pct": agg.median_pct,
        "max_pct": agg.max_pct,
        "min_pct": agg.min_pct,
        "up_count": agg.up_count,
        "down_count": agg.down_count,
        "flat_count": agg.flat_count,
        "bin_width": agg.bin_width,
        "buckets": [
            DistributionBucket(
                label=b.label,
                lower=b.lower,
                upper=b.upper,
                count=b.count,
            )
            for b in agg.buckets
        ],
    }
    if bin_width_default == BOARD_BUCKET_BIN_WIDTH:
        return BoardStats(**common, source=source)
    return StockStats(**common)


@router.get(
    "/agent/market-stats",
    response_model=MarketStatsResponse,
    responses={500: {"model": ErrorResponse, "description": "Server error"}},
    tags=["agent"],
)
@endpoint_meta(
    summary="市场全量统计（个股+板块涨幅分布 + 桶形数据）",
    markets=["csi"],
    capabilities=[],                          # agent aggregation, no single capability
)
@map_errors
def get_market_stats(
    include_boards: bool = Query(
        default=True,
        description="是否包含板块块;false 时只返回个股块 (无板块上游调用)",
    ),
    format: str = Query(
        "json",
        pattern="^(json|md)$",
        description="Output format. json=application/json (default); md=text/markdown.",
    ),
) -> Response:
    """Per-block fan-out with per-block error isolation.

    stocks block:  manager.get_realtime_quotes('csi') (single upstream call)
    boards block:  stock_board_cache.get_all_boards(source='ths', include_quote=True)
                   (single upstream call, persistence-routed)

    A single upstream failure sets that block to ``null`` and surfaces
    the exception in ``errors[]``; the other block continues normally.
    Cached 60s via ``get_quote_cache`` (one entry shared between json/md).
    """
    cache_key = make_market_stats_cache_key(include_boards)
    hit = cached_lookup(get_quote_cache, cache_key, "agent_market_stats")
    if hit is not None:
        return _render_agent("market-stats", hit, format)

    started = time.monotonic()
    manager = get_manager()
    errors: list[MarketStatsErrorEntry] = []
    stocks_stats: StockStats | None = None
    boards_stats: BoardStats | None = None
    requested = 1 + (1 if include_boards else 0)
    ok = 0

    # --- stocks block (always attempted) ---
    try:
        quotes, _src = manager.get_realtime_quotes("csi")
        values = [
            q.change_pct for q in (quotes or [])
            if getattr(q, "change_pct", None) is not None
        ]
        agg = compute_aggregate(
            values,
            bin_width=STOCK_BUCKET_BIN_WIDTH,
            buckets_template=build_stock_buckets(),
        )
        stocks_stats = _stats_block_from_aggregate(agg, bin_width_default=STOCK_BUCKET_BIN_WIDTH)
        ok += 1
    except Exception as exc:
        logger.warning(
            f"[agent/market-stats] stocks failed: {exc}", exc_info=True
        )
        errors.append(
            MarketStatsErrorEntry(
                block="stocks",
                error=type(exc).__name__,
                message=str(exc),
            )
        )

    # --- boards block (skipped when include_boards=false) ---
    if include_boards:
        try:
            boards, src = stock_board_cache.get_all_boards(
                source="ths", include_quote=True, manager=manager
            )
            values = [
                b.get("change_pct") for b in (boards or [])
                if isinstance(b.get("change_pct"), (int, float))
            ]
            agg = compute_aggregate(
                values,
                bin_width=BOARD_BUCKET_BIN_WIDTH,
                buckets_template=build_board_buckets(),
            )
            boards_stats = _stats_block_from_aggregate(
                agg, bin_width_default=BOARD_BUCKET_BIN_WIDTH, source=src or "ths"
            )
            ok += 1
        except Exception as exc:
            logger.warning(
                f"[agent/market-stats] boards failed: {exc}", exc_info=True
            )
            errors.append(
                MarketStatsErrorEntry(
                    block="boards",
                    error=type(exc).__name__,
                    message=str(exc),
                )
            )

    result = MarketStatsResponse(
        stocks=stocks_stats,
        boards=boards_stats,
        errors=errors,
        summary=_batch_summary(requested, ok, started),
    )
    cached_store(get_quote_cache, cache_key, result)
    return _render_agent("market-stats", result, format)
```

- [ ] **Step 4.5: Run integration tests; expect JSON tests pass, MD tests fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_market_stats.py -v -k "not format_md"`

Expected: 9 tests pass (happy path + 3 error-isolation + include_boards false + 2 cache-key tests + invalid format → 422).

The `test_format_md_returns_markdown` test will FAIL because `render_market_stats_as_md` doesn't exist yet in `_MD_TEMPLATES`. That's expected; it's the gate for Task 5.

- [ ] **Step 4.6: Commit**

```bash
git add stock_data/api/routes/agent.py tests/test_agent_market_stats.py
git commit -m "feat(agent): GET /api/v1/agent/market-stats — core JSON path

Adds the route handler with per-block error isolation (independent
try/except around stocks + boards; one block's failure never touches
the other). 60s TTL via get_quote_cache. ?format=md dispatch through
_render_agent (template added in next commit).

- stocks block: manager.get_realtime_quotes('csi')
- boards block: stock_board_cache.get_all_boards(source='ths', include_quote=True)
- ?include_boards=false skips the boards upstream entirely
- summary uses _batch_summary helper (requested/ok/failed/elapsed_ms)
- failures cached for 60s too (avoid hammering a broken upstream)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 5: MD projection layer

**Files:**
- Modify: `stock_data/api/routes/agent.py` (append `render_market_stats_as_md` + register in `_MD_TEMPLATES`)

**Interfaces:**
- Consumes: `MarketStatsResponse` from `stock_data.api.schemas`
- Produces: a markdown string matching the layout in the spec §3.5

- [ ] **Step 5.1: Run the failing MD test from Task 4**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_market_stats.py::test_format_md_returns_markdown -v`
Expected: FAIL with `KeyError: 'market-stats'` from `_MD_TEMPLATES`.

- [ ] **Step 5.2: Append `render_market_stats_as_md` to `agent.py`**

Find the `_MD_TEMPLATES` dict (the last few lines of `agent.py`) and:

(a) Append the render function BEFORE `_MD_TEMPLATES`:

```python
def _md_stats_block(
    title: str, stats, *, total_universe_label: str
) -> list[str]:
    """Render one stats block (个股 or 板块) to MD table rows."""
    out: list[str] = [f"## {title}"]
    if stats is None:
        out.append("（失败 — 详见 errors）")
        return out
    out.append(
        f"样本数: **{stats.sample_size}** ({total_universe_label}); "
        f"均值 {_md_pct(stats.mean_pct)}, 中位 {_md_pct(stats.median_pct)}, "
        f"最高 {_md_pct(stats.max_pct)}, 最低 {_md_pct(stats.min_pct)}"
    )
    out.append(
        f"上涨: **{stats.up_count}** / 下跌: **{stats.down_count}** / "
        f"平盘: **{stats.flat_count}**"
    )
    out.append("")
    out.append("| 区间 | 计数 | 占比 |")
    out.append("|---|---|---|")
    if stats.sample_size:
        for b in stats.buckets:
            pct = b.count / stats.sample_size * 100
            out.append(f"| {b.label} | {b.count} | {_md_num(pct, 2)}% |")
    else:
        for b in stats.buckets:
            out.append(f"| {b.label} | 0 | — |")
    return out


def render_market_stats_as_md(p: MarketStatsResponse) -> str:
    out: list[str] = ["# 市场全量统计", ""]
    out.extend(_md_stats_block("个股", p.stocks, total_universe_label="A 股全市场"))
    out.append("")
    out.extend(_md_stats_block("板块", p.boards, total_universe_label="ths 板块清单"))
    out.append("")
    out.append("## 失败列表")
    out.extend(
        _md_errors(
            [e.model_dump() for e in p.errors], key="block", header="块"
        )
    )
    out.append("")
    s = p.summary or {}
    out.append(
        f"## 汇总 — requested {s.get('requested', '?')}, "
        f"ok {s.get('ok', '?')}, failed {s.get('failed', '?')}, "
        f"elapsed {s.get('elapsed_ms', '?')}ms"
    )
    return "\n".join(out)
```

(b) Add the entry to `_MD_TEMPLATES` (currently a 6-entry dict):

```python
_MD_TEMPLATES: dict[str, Callable] = {
    "boards/stock-overlap": render_boards_overlap_as_md,
    "stocks/board-overlap": render_stocks_board_overlap_as_md,
    "boards/filter-stocks": render_filter_stocks_as_md,
    "indices/batch-profile": render_indices_batch_profile_as_md,
    "market-context": render_market_context_as_md,
    "stocks/batch-profile": render_stocks_batch_profile_as_md,
    "market-stats": render_market_stats_as_md,         # ← new
}
```

- [ ] **Step 5.3: Run all integration tests; expect all PASS**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_market_stats.py -v`
Expected: all tests pass (10 tests: 9 from Task 4 + 1 MD test).

- [ ] **Step 4 (sanity): also re-run the existing agent test suite to confirm no regressions**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_endpoints.py -v`
Expected: all existing tests still pass (route additions must not disturb the 6 existing endpoints).

- [ ] **Step 5.4: Commit**

```bash
git add stock_data/api/routes/agent.py
git commit -m "feat(agent): MD projection for /agent/market-stats

Adds render_market_stats_as_md and registers it in _MD_TEMPLATES so
?format=md returns text/markdown; charset=utf-8 with the two stats
tables (个股 + 板块), errors list, and the standard summary line.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 6: CLAUDE.md documentation update

**Files:**
- Modify: `CLAUDE.md` (add one row to the "Agent Batch API" table + one row to the manifest drill-down table if applicable)

**Interfaces:** none — documentation only.

- [ ] **Step 6.1: Find the "Agent Batch API" table in CLAUDE.md**

Search for `### Agent Batch API (`/api/v1/agent/*`)` and read the surrounding table.

- [ ] **Step 6.2: Append the new row**

Add a new row to the table inside that section:

```
| `GET /agent/market-stats` | 全市场涨幅统计（个股 + 板块；均值/中位/最高/最低/上涨下跌家数 + 桶形数据）。 | `manager.get_realtime_quotes('csi')` + `stock_board_cache.get_all_boards(source='ths', include_quote=True)`; 60s TTLCache via `get_quote_cache`. |
```

- [ ] **Step 6.3: Verify with grep**

Run: `grep -n "agent/market-stats" CLAUDE.md`
Expected: one match in the table.

- [ ] **Step 6.4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: document GET /api/v1/agent/market-stats in CLAUDE.md

Adds the new endpoint to the Agent Batch API section table, noting
the dual-upstream fan-out (stocks realtime quotes + THS board list
with quotes) and the shared 60s TTL.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 7: Final sanity sweep + manifest rebuild

**Files:**
- Touch: none — verification + commit only

- [ ] **Step 7.1: Run the agent test suite end-to-end**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_market_stats.py tests/test_agent_market_stats_schemas.py tests/test_stats_compute.py tests/test_agent_endpoints.py -v`
Expected: all pass.

- [ ] **Step 7.2: Confirm the route is in the explorer manifest**

Start the server briefly (no external probes) and confirm:

Run: `.venv/Scripts/python.exe -c "from stock_data.server import app; from stock_data.explorer.manifest import build_manifest; m = build_manifest(app); routes = [r['path'] for s in m['sections'] for r in s.get('endpoints', []) if isinstance(r, dict)]; print(any('agent/market-stats' in p for p in routes))"`

Expected: prints `True`. Stop the server (Ctrl+C).

- [ ] **Step 7.3: Lint**

Run: `.venv/Scripts/python.exe -m ruff check stock_data/data_provider/utils/stats.py stock_data/api/routes/agent.py stock_data/api/schemas.py stock_data/api/cache.py tests/test_agent_market_stats.py tests/test_stats_compute.py tests/test_agent_market_stats_schemas.py`
Expected: no errors.

- [ ] **Step 7.4: Final commit (if Step 7.2 surfaced a manifest wiring fix)**

If the manifest probe in 7.2 returned False, fix the missing
`@endpoint_meta` decoration and commit:

```bash
git add stock_data/api/routes/agent.py
git commit -m "fix(agent): ensure /agent/market-stats surfaces in the explorer manifest

[describe the actual fix; e.g. decorator re-order, missing meta fields]

Co-Authored-By: Claude <noreply@anthropic.com>"
```

Otherwise, no commit needed for this task — the previous task commits are the deliverable.
