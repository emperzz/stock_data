# `/api/v1/agent/market-stats` — Aggregate Market Statistics

> Spec for adding a server-side full-market statistical aggregator
> (mean / median / max / min / up-down-flat count + percentage buckets)
> across both stocks and boards, with per-block error isolation so a
> single upstream failure does NOT mask the other block's data.

**Date**: 2026-08-27
**Status**: Draft
**Scope**: API surface (one new GET route), schema, one pure-compute
helper module, cache key, MD projection, tests; **no new fetcher, no new
manager method, no new `DataCapability` flag**.

---

## 1. Background

The LLM agent layer needs a single-call "what does the market look like
right now?" snapshot — distribution of stock/board price changes across
the universe, plus simple summary stats. Today the only way to assemble
this is:

- `/api/v1/stocks?include_quote=true` returns the full A-share realtime
  snapshot (~5000+ rows) but the agent still has to fetch it, sort,
  bucket, and count client-side.
- `/api/v1/boards/{code}/quote` only returns ONE board's quote — no
  batched all-boards quote endpoint.
- `manager.get_all_boards(source='ths', include_quote=True)` returns
  the full board list WITH quotes, but the agent still has to bucket /
  count client-side.

This endpoint closes that loop: **fetch once, aggregate server-side,
return summary + bucket distribution** for both stocks and boards in
one response. Per the existing agent-endpoint contract, the LLM
consumes numeric facts only — no judgment, no ranking, no commentary.

**Goal**: a single GET that returns:

- `stocks` block — sample size, mean / median / max / min of
  `change_pct`, up / down / flat counts, 11 percentage buckets
  (3% bin width, clipped at ±12%, flat = 0% standalone bucket).
- `boards` block — same structure, 9 percentage buckets (1% bin width,
  clipped at ±3%, flat = 0% standalone bucket).
- Per-block error isolation — if either upstream fails, that block
  becomes `null` and the failure surfaces in `errors[]`; the other
  block continues normally.

**Non-goals**: HK / US / crypto (A-share only at v1); per-stock drill-
down (callers should chain to `/stocks/{code}/quote`); ranking or
recommendation (no LLM judgment); configurable bin width or clip
boundaries (hard-coded for v1; query param later if needed).

---

## 2. Public API

### 2.1 Endpoint

```
GET /api/v1/agent/market-stats
```

### 2.2 Query parameters

| Field | Type | Default | Constraints |
|---|---|---|---|
| `format` | `Literal["json","md"]` | `"json"` | matches existing agent endpoints; `md` returns `text/markdown; charset=utf-8` |
| `include_boards` | `bool` | `True` | when `false`, the `boards` block is skipped (no upstream call) |

### 2.3 Response

```jsonc
{
  "stocks": {                       // null when upstream failed
    "sample_size": 5123,
    "mean_pct":   0.32,
    "median_pct": 0.18,
    "max_pct":   11.20,
    "min_pct":   -9.85,
    "up_count":   2840,
    "down_count": 2150,
    "flat_count":   133,
    "bin_width":   3.0,
    "buckets": [
      { "label": "(-∞, -12%]",       "lower": null, "upper": -12.0, "count":   8 },
      { "label": "(-12%, -9%]",      "lower": -12.0, "upper":  -9.0, "count":  42 },
      { "label": "(-9%, -6%]",       "lower":  -9.0, "upper":  -6.0, "count": 185 },
      { "label": "(-6%, -3%]",       "lower":  -6.0, "upper":  -3.0, "count": 712 },
      { "label": "(-3%, 0)",         "lower":  -3.0, "upper":   0.0, "count": 1100 },
      { "label": "0% (平盘)",        "lower":   0.0, "upper":   0.0, "count":  133 },
      { "label": "(0, +3%]",         "lower":   0.0, "upper":   3.0, "count": 1650 },
      { "label": "(+3%, +6%]",       "lower":   3.0, "upper":   6.0, "count":  920 },
      { "label": "(+6%, +9%]",       "lower":   6.0, "upper":   9.0, "count":  310 },
      { "label": "(+9%, +12%]",      "lower":   9.0, "upper":  12.0, "count":   55 },
      { "label": "(+12%, +∞)",       "lower":  12.0, "upper": null, "count":   8 }
    ]
  },
  "boards": { /* same shape, 9 buckets of 1% width clipped at ±3%, + "source": "ths" */ },
  "errors": [],                     // see §4
  "summary": { "requested": 2, "ok": 2, "failed": 0, "elapsed_ms": 184 }
}
```

### 2.4 Status codes

| Code | When |
|---|---|
| 200 | Always, when the route is hit. Partial data is signaled by `null` blocks + `errors[]` entries — NOT by status code. |
| 422 | `format` value other than `json` / `md` (handled by Pydantic `Literal`). |

The route never returns 5xx for upstream data failures. The only
`DataFetchError → 503` mapping happens at the `map_errors` decorator
boundary for "no fetcher supports market=csi at all" (a configuration
issue, not a transient outage).

---

## 3. Implementation

### 3.1 New file — `stock_data/data_provider/utils/stats.py`

Pure-compute helper, no I/O. Imports nothing from `data_provider` /
`api`. Easy to unit-test with synthetic value lists.

```python
"""Pure-compute distribution aggregation for change_pct values.

Used by /api/v1/agent/market-stats. Bucket math lives here so the
route layer stays a thin orchestration wrapper.
"""

from dataclasses import dataclass

@dataclass(frozen=True)
class DistributionBucket:
    label: str            # display label, e.g. "(-3%, 0)" or "0% (平盘)"
    lower: float | None   # bucket lower bound; None = -∞
    upper: float | None   # bucket upper bound; None = +∞; flat-bucket has lower == upper == 0
    count: int            # count of values falling in this bucket

@dataclass(frozen=True)
class AggregateStats:
    sample_size: int          # values with non-None change_pct
    mean_pct: float | None
    median_pct: float | None
    max_pct: float | None
    min_pct: float | None
    up_count: int             # change_pct >  1e-9
    down_count: int           # change_pct < -1e-9
    flat_count: int           # |change_pct| <= 1e-9
    bin_width: float          # informational; echoed back in response
    buckets: list[DistributionBucket]   # always full template (count may be 0)


STOCK_BUCKET_BIN_WIDTH = 3.0
STOCK_BUCKET_EDGES = (-12.0, 12.0)
BOARD_BUCKET_BIN_WIDTH = 1.0
BOARD_BUCKET_EDGES = (-3.0, 3.0)

_EPS = 1e-9


def build_stock_buckets() -> list[DistributionBucket]:
    """11 buckets: (-∞,-12], (-12,-9], (-9,-6], (-6,-3], (-3,0),
    {0}, (0,+3], (+3,+6], (+6,+9], (+9,+12], (+12,+∞)."""
    ...

def build_board_buckets() -> list[DistributionBucket]:
    """9 buckets: (-∞,-3], (-3,-2], (-2,-1], (-1,0), {0},
    (0,+1], (+1,+2], (+2,+3], (+3,+∞)."""
    ...

def compute_aggregate(
    values: list[float | None],
    *,
    bin_width: float,
    buckets_template: list[DistributionBucket],
) -> AggregateStats:
    """Aggregate a list of change_pct values.

    - None values are skipped (not in sample_size, not in any bucket).
    - flat = |v| <= 1e-9 (rounded-to-zero guard).
    - Returns a zero-valued AggregateStats when input is all-None
      (sample_size=0, all means/medians/extremes None, all counts 0,
      buckets echoed from the template).
    - Median via statistics.median; raises StatisticsError if input is
      empty (we guard for that and return None instead).
    """
    ...
```

Bucket assignment (inside `compute_aggregate`):

```python
def _assign(value: float, buckets: list[DistributionBucket]) -> DistributionBucket:
    if abs(value) <= _EPS:
        # flat bucket (lower == upper == 0.0)
        for b in buckets:
            if b.lower == 0.0 and b.upper == 0.0:
                return b
        raise AssertionError("flat bucket missing from template")
    for b in buckets:
        if b.lower == 0.0 and b.upper == 0.0:
            continue   # already handled above
        lo_ok = (b.lower is None) or value > b.lower
        hi_ok = (b.upper is None) or value <= b.upper
        if lo_ok and hi_ok:
            return b
    raise AssertionError(f"value {value} did not fall in any bucket")
```

The endpoint of "no bucket matches" is unreachable by construction
(±∞ boundaries catch everything), so `AssertionError` is a defensive
guard — it signals a buggy bucket template, not a data edge case.

### 3.2 New schemas in `stock_data/api/schemas.py`

```python
class DistributionBucket(BaseModel):
    label: str
    lower: float | None
    upper: float | None
    count: int = Field(ge=0)

class StockStats(BaseModel):
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
    sample_size: int = Field(ge=0)
    mean_pct: float | None
    median_pct: float | None
    max_pct: float | None
    min_pct: float | None
    up_count: int = Field(ge=0)
    down_count: int = Field(ge=0)
    flat_count: int = Field(ge=0)
    bin_width: float = 1.0
    source: str                              # ths | persistence | ""
    buckets: list[DistributionBucket]

class MarketStatsErrorEntry(BaseModel):
    block: Literal["stocks", "boards"]
    error: str                               # exception class name
    message: str

class MarketStatsResponse(BaseModel):
    stocks: StockStats | None
    boards: BoardStats | None
    errors: list[MarketStatsErrorEntry]
    summary: dict                            # {requested, ok, failed, elapsed_ms}
```

### 3.3 Cache key — extend `stock_data/api/cache.py`

```python
def make_market_stats_cache_key(include_boards: bool) -> str:
    """Cache key for GET /agent/market-stats.

    Independent of format (json/md share one cache entry, same as
    every other agent endpoint). 60s TTL via get_quote_cache.
    """
    return f"agent_market_stats:{include_boards}"
```

### 3.4 Route handler — extend `stock_data/api/routes/agent.py`

```python
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
    """Per-block fan-out: stocks via get_realtime_quotes('csi');
    boards via stock_board_cache.get_all_boards(source='ths', include_quote=True).
    Per-block error isolation: a single upstream failure sets that
    block to null and surfaces the exception in errors[]; the other
    block continues normally. Cached 60s via get_quote_cache."""
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

    # --- stocks block ---
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
        stocks_stats = StockStats(
            sample_size=agg.sample_size,
            mean_pct=agg.mean_pct,
            median_pct=agg.median_pct,
            max_pct=agg.max_pct,
            min_pct=agg.min_pct,
            up_count=agg.up_count,
            down_count=agg.down_count,
            flat_count=agg.flat_count,
            bin_width=agg.bin_width,
            buckets=[
                DistributionBucket(
                    label=b.label, lower=b.lower, upper=b.upper, count=b.count
                )
                for b in agg.buckets
            ],
        )
        ok += 1
    except Exception as exc:
        logger.warning(f"[agent/market-stats] stocks failed: {exc}", exc_info=True)
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
            boards_stats = BoardStats(
                sample_size=agg.sample_size,
                mean_pct=agg.mean_pct,
                median_pct=agg.median_pct,
                max_pct=agg.max_pct,
                min_pct=agg.min_pct,
                up_count=agg.up_count,
                down_count=agg.down_count,
                flat_count=agg.flat_count,
                bin_width=agg.bin_width,
                source=src or "ths",
                buckets=[
                    DistributionBucket(
                        label=b.label, lower=b.lower, upper=b.upper, count=b.count
                    )
                    for b in agg.buckets
                ],
            )
            ok += 1
        except Exception as exc:
            logger.warning(f"[agent/market-stats] boards failed: {exc}", exc_info=True)
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

`_render_agent("market-stats", ...)` dispatches to
`render_market_stats_as_md` (added to `_MD_TEMPLATES`).

### 3.5 MD projection

```python
def render_market_stats_as_md(p: MarketStatsResponse) -> str:
    out: list[str] = ["# 市场全量统计", ""]
    out.extend(_md_stats_block("个股", p.stocks, total_universe_label="A 股全市场"))
    out.append("")
    out.extend(_md_stats_block("板块", p.boards, total_universe_label="ths 板块清单"))
    out.append("")
    out.append("## 失败列表")
    out.extend(_md_errors([e.model_dump() for e in p.errors], key="block", header="块"))
    out.append("")
    s = p.summary or {}
    out.append(
        f"## 汇总 — requested {s.get('requested', '?')}, "
        f"ok {s.get('ok', '?')}, failed {s.get('failed', '?')}, "
        f"elapsed {s.get('elapsed_ms', '?')}ms"
    )
    return "\n".join(out)


def _md_stats_block(title, stats, *, total_universe_label) -> list[str]:
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
    for b in stats.buckets:
        pct = (b.count / stats.sample_size * 100) if stats.sample_size else 0.0
        out.append(f"| {b.label} | {b.count} | {_md_num(pct, 2)}% |")
    return out
```

`render_market_stats_as_md` added to `_MD_TEMPLATES` dict.

---

## 4. Error isolation contract (pinned)

| Failure | stocks | boards | errors[] | HTTP |
|---|---|---|---|---|
| Both upstream OK | populated | populated | `[]` | 200 |
| Only stocks fails | `null` | populated | `[{"block":"stocks",...}]` | 200 |
| Only boards fails | populated | `null` | `[{"block":"boards",...}]` | 200 |
| Both fail | `null` | `null` | 2 entries | 200 |
| `include_boards=false` | populated | `null` (not attempted) | `[]` | 200 |

The contract is that **one block's failure NEVER references state from
the other block**: each block has its own try/except with its own
local variables. The `summary.ok` count tells the caller how many
blocks succeeded; `errors[]` tells which and why.

---

## 5. Tests (`tests/test_agent_market_stats.py`)

All tests use `monkeypatch` on the route layer's `manager` /
`stock_board_cache` references — no `live_network` marker, fast dev
loop.

| Test | What it pins |
|---|---|
| `test_compute_aggregate_basic_distribution` | mean/median/max/min/up/down/flat counts on a hand-picked value list (e.g. `[-12.0, -3.0, 0.0, 3.0, 12.0, 13.0]`) |
| `test_compute_aggregate_bucket_assignment_edges` | boundary values `−12.0`, `−11.999`, `−9.0`, `0.0`, `1e-10`, `0.001`, `+12.0`, `+12.001` land in the right bucket (incl. flat bucket via 1e-10) |
| `test_compute_aggregate_skips_none` | input `[None, None, 1.0]` → sample_size=1, all stats from `[1.0]` |
| `test_compute_aggregate_empty_input` | `[]` → sample_size=0, all means None, buckets echoed with count=0 |
| `test_compute_aggregate_bucket_count_template_invariant` | output buckets == input template length (no buckets dropped / merged) |
| `test_market_stats_returns_200` | happy path, both blocks populated |
| `test_market_stats_stocks_failure_isolates_boards` | stocks upstream raises `DataFetchError`; boards populated, `errors[]` has `{"block":"stocks",...}`, `summary.ok=1` |
| `test_market_stats_boards_failure_isolates_stocks` | symmetric: boards raises; stocks populated, `errors[]` has `{"block":"boards",...}` |
| `test_market_stats_both_fail` | both raise; both null, 2 entries in errors, `summary.ok=0` |
| `test_market_stats_include_boards_false_skips_boards_upstream` | `?include_boards=false` → boards=null, NO boards upstream call, errors=[], `summary.requested=1` |
| `test_market_stats_format_md_returns_markdown` | `?format=md` → `Content-Type: text/markdown; charset=utf-8`, body contains `## 个股` and `## 板块` |
| `test_market_stats_cache_hit_skips_upstream` | second call within 60s does not invoke manager methods |
| `test_market_stats_cache_key_includes_include_boards` | two calls with different `include_boards` produce distinct cache entries |

---

## 6. Anti-patterns / what NOT to do

- **Don't** reuse `manager.get_realtime_quote(code)` per stock. Use
  `manager.get_realtime_quotes('csi')` — single upstream call.
- **Don't** call `manager.get_board_realtime` per board. Use
  `stock_board_cache.get_all_boards(source='ths', include_quote=True)`
  — single upstream call.
- **Don't** add `?bin_width=` / `?max_abs_pct=` query params in v1.
  Hard-code per spec §3.1. YAGNI — add later if a client actually needs
  them.
- **Don't** introduce a new `DataCapability` flag. The endpoint is an
  aggregation over two existing capabilities (STOCK_REALTIME_QUOTE for
  stocks, STOCK_BOARD for boards); per CLAUDE.md, agent endpoints
  declare `capabilities=[]`.
- **Don't** cross-pollinate state between blocks. Each try/except owns
  its own local variables. A `stocks_stats is None` test in the boards
  block would be a code smell.
- **Don't** drop the bucket template on empty input. Always return the
  full 11 / 9 buckets with `count=0` so the client can render a stable
  table shape.
- **Don't** return 5xx on upstream failure. Always 200 + null block +
  errors[] entry. Status code carries only the "this endpoint exists
  and understood your request" signal.

---

## 7. Out of scope (future)

- Configurable bin width / clip boundaries (`?bin_width=`, `?max_abs=`)
- HK / US market stats (would require a multi-source fan-out and
  different upstream shape; revisit if a client asks)
- Per-stock drill-down top-N (callers chain to `/stocks/{code}/quote`
  today)
- Constituent-weighted board stats (use raw board `change_pct` only
  at v1; weighted-by-mcap is a separate spec)
- Cache invalidation on intraday tick boundary (60s TTL is fine — the
  market-context endpoint uses the same default)
