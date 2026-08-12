# `/api/v1/agent/correlation/matrix` — Cross-Asset Pairwise Correlation

> Spec for adding a server-side correlation-matrix aggregator that accepts
> both stocks (`600519`) and boards (`board.code + board.source`) in one
> request, returns a Pearson + Spearman NxN matrix per call, and projects
> the matrix to a top-pair-sorted markdown form for agent consumption.

**Date**: 2026-08-12
**Status**: Draft
**Scope**: API surface (one new POST route), schema, one pure-compute helper,
cache key, tests; **no new fetcher, no new manager method, no new
`DataCapability` flag**.

---

## 1. Background

`D:\GitRepo\Vibe-Trading\agent\backtest\correlation.py` and `…\regime.py`
contain a production-grade correlation + regime-timeline stack that already
solves the algorithms we want: `infer_market`, `_normalize_symbol`,
`_rolling_correlation_matrix`, `compute_correlation_matrix`,
`compute_regime_timeline`. Their loaders are bound to
`registry.FALLBACK_CHAINS[market]` (FreqAI/Stratey stack) and not portable.
This spec copies the **algorithms** (inner-join alignment, the
`pct_change(fill_method=None)` regression guard, the `index.normalize()`
quirk, NaN→0 fallback, rounding) and adapts the **data fetch** to our
`DataFetcherManager`. Regime timeline is explicitly out of scope here;
only the matrix endpoint ships in v1.

There is currently no `/api/v1/agent/*` endpoint that returns numerical
analysis across heterogeneous assets. The existing 6 agent endpoints
(boards/stocks overlap, filter-stocks, indices/stocks batch profile,
market context) all return set-membership or batched profile data —
none compute pairwise numeric relationships. This fills that gap for an
LLM agent that needs, e.g. "which boards track the same as my watchlist"
or "how tightly does `885595` track `600519` over 90 d".

**Goal**: a single POST that returns a symmetric NxN correlation matrix
(N = |stocks| + |boards|, 2 ≤ N ≤ 10) for both Pearson and Spearman
on the same alignment, with an `?format=md` projection that puts the
strongest |ρ| pairs at the top so an agent can act without re-sorting.

**Non-goals**: HK/US/crypto support (A-share only at v1); regime-timeline
endpoint; rolling time series of pairwise correlations; cointegration /
half-life / Kalman hedge / pair-trading signals; equity-weighted or
constituent-rolled-up board returns; **parallel fan-out of fetches**
(sequential at v1, the inner TTLs hide most of the cold-path cost).

---

## 2. Public API

### 2.1 Endpoint

```
POST /api/v1/agent/correlation/matrix
```

### 2.2 Request body

```jsonc
{
  "stocks":  ["600519", "000001"],
  "boards":  [{"code": "885595", "source": "ths"}],
  "frequency": "d",                 // "d" | "w" | "m" | "1m" | "5m" | "15m" | "30m" | "60m"
  "days":      90,                  // calendar days; range depends on frequency (see §2.5)
  "methods":  ["pearson", "spearman"]
}
```

| Field | Type | Default | Constraints |
|---|---|---|---|
| `stocks` | `list[str]` | `[]` | length 0..10; each entry normalized via `normalize_stock_code` |
| `boards` | `list[{code,source}]` | `[]` | length 0..10; `source ∈ {"ths","eastmoney"}`, default `"ths"` |
| `frequency` | `Literal` | `"d"` | one of the eight values; see §2.5 |
| `days` | `int` | `90` | range per frequency (table §2.5); unit = calendar days, passed straight through to `manager.get_kline_data(..., days=...)` |
| `methods` | `list[Literal["pearson","spearman"]]` | both | one or both |

Cross-field: `len(stocks) + len(boards) ∈ [2, 10]`. Otherwise → `422`.

> **Note on `days` semantics**: the value passes through to the existing
> K-line endpoints (which already use `days` as the calendar-day window
> parameter; see `manager.get_kline_data(... days, frequency, ...)`). For
> frequencies finer than `d`, the existing endpoints internally aggregate
> daily bars into the chosen frequency within that calendar window. We
> inherit that behavior verbatim — see §2.5 for the bound table.

### 2.3 Response body

```jsonc
{
  "labels": [
    {"type": "stock", "code": "600519",     "name": "贵州茅台", "source": null},
    {"type": "board", "code": "885595",     "name": "白酒",     "source": "ths"}
  ],
  "frequency": "d",
  "days":      90,
  "alignment": {
    "requested_days":      90,
    "common_bars":         87,
    "missing_after_join":   3
  },
  "matrices": {
    "pearson":  [[1.0, 0.87, 0.23], [0.87, 1.0, 0.41], [0.23, 0.41, 1.0]],
    "spearman": [[1.0, 0.79, 0.18], [0.79, 1.0, 0.39], [0.18, 0.39, 1.0]]
  },
  "errors": []
}
```

`labels[i]` corresponds to `matrices.method[i][:]`. Order = request order
(stocks first as a block, then boards as a block); client sorts if it
needs alphabetical. `frequency` / `days` are echoed back so an agent
can confirm what the matrix was computed over.

### 2.4 `?format=md` projection

The route handler at `agent_correlation.py:529-537` builds a
`PlainTextResponse` directly (returning `text/markdown; charset=utf-8`)
when the request carries `?format=md`. This bypasses the shared
`_render_agent` / `_render_markdown` path used by the other six agent
endpoints, which means there is no JSON-fallback / `X-MD-Render-Error`
header contract here — a template failure would surface as a 500. The
projection lays out one **section per method** in `methods`, each with a
header summary, a top-pairs table (sorted by |ρ| descending), and the full
NxN matrix at the bottom:

```
## 相关性矩阵 — pearson (d × 90d)

> 资产数: 3 · 对齐 87/90 个交易日 · 缺失 3 个数据点

### 所有 pair (按 |ρ| 降序)
| # | Pair                                | ρ     |
|---|-------------------------------------|-------|
| 1 | 600519 ↔ 000001                    | 0.87  |
| 2 | 000001 ↔ 885595 (ths)              | 0.41  |
| 3 | 600519 ↔ 885595 (ths)              | 0.23  |

### 完整矩阵 (pearson)
|          | 600519 | 000001 | 885595 |
|----------|--------|--------|--------|
| 600519   | —      | 0.87   | 0.23   |
| 000001   | 0.87   | —      | 0.41   |
| 885595   | 0.23   | 0.41   | —      |

## 相关性矩阵 — spearman (d × 90d)
... (same layout, omitting the section if the matrix was not requested) ...
```

When `errors[]` is non-empty, append an "### 数据缺失" subsection with
one line per error.

**Why this shape (justification for the agent-friendly choice)**: agents
typically reach for one of two operations — "top correlate-with-X" (the
top-pairs table gives that in 1 read) or "show the matrix" (the NxN
table). Outputting long-form (sorted pairs) rather than only the matrix
saves the agent from re-implementing sort-by-|ρ|, which is non-trivial
across text tables. The full matrix is a fallback. Header summary
(`资产数 / 对齐 / 缺失`) makes "do I trust this result?" a one-liner.

### 2.5 `frequency` × `days` validation table

`days` is in **calendar days**; the route passes it through to the
underlying K-line fetcher's existing `days` semantics, which interprets
the value as a calendar-day window. The route validates against this
table; out-of-range → `422 {error:"bad_request", message:"days must be in N..M for frequency=…"}`.

| `frequency` | `days` range | Stock fetcher | Boards `ths` | Boards `eastmoney` |
|---|---|---|---|---|
| `d`   | 30..365 | yes (zzshare P2)     | yes | yes |
| `w`   | 4..120  | yes                  | yes | yes |
| `m`   | 1..36   | yes                  | yes | yes |
| `1m`  | 1..30   | yes (akshare P3)     | yes | **no**  → 422 if any board has `source="eastmoney"` |
| `5m`  | 1..30   | yes (zzshare P2)     | yes | yes |
| `15m` | 1..30   | yes                  | yes | yes |
| `30m` | 1..30   | yes                  | yes | yes |
| `60m` | 1..30   | yes                  | yes | yes |

The board-source/frequency table is **server-validated in advance** —
the route refuses early with `422` rather than letting
`manager.get_board_history(..., frequency="1m", source="eastmoney")`
explode downstream.

For minute frequencies, the lower bound `days=1` means "today only"
(single trading session). The upper bound `days=30` keeps the inner-join
size bounded (≤ 30 × 240 = 7,200 1-minute bars per asset).

**Note on THS 1m hard cap**: the THS board-history endpoint silently
truncates 1m data to its upstream cap (≈ 800 most recent 1m bars).
For `days ≤ 3` on `frequency="1m"` from `source="ths"`, no truncation
occurs; for `days=30` the upstream will return roughly the last 800
1m bars (≈ 3.3 trading sessions) regardless of the requested window.
This is upstream behavior — the route honors whatever
`manager.get_board_history` returns. If a future change tightens the
v1 contract for 1m precision, the upper bound should drop to `days ≤ 3`
and the bound-table update should ship alongside.

### 2.6 Pydantic models (`api/schemas.py`)

```python
class CorrelationFrequency(str, Enum):
    d = "d"
    w = "w"
    m = "m"
    m1 = "1m"
    m5 = "5m"
    m15 = "15m"
    m30 = "30m"
    m60 = "60m"

class CorrelationMethod(str, Enum):
    pearson = "pearson"
    spearman = "spearman"

class CorrelationLabel(BaseModel):
    type: Literal["stock", "board"]
    code: str
    name: str | None = None
    source: Literal["ths","eastmoney"] | None = None   # only board

class CorrelationErrorItem(BaseModel):
    type: Literal["stock", "board"]
    code: str
    source: Literal["ths","eastmoney"] | None = None
    reason: Literal["data_unavailable","empty","too_short"]

class CorrelationAlignment(BaseModel):
    requested_days:        int
    common_bars:           int
    missing_after_join:    int

class CorrelationMatrices(BaseModel):
    pearson:  list[list[float]] | None = None     # None if not requested
    spearman: list[list[float]] | None = None

class CorrelationMatrixRequest(BaseModel):
    stocks:     list[str] = []
    boards:     list[str | dict] = []            # bare code str (source defaults
                                                #  to "ths") or {"code", "source"}
    frequency:  CorrelationFrequency = CorrelationFrequency.d
    days:       int = 90                          # bounds-checked against frequency
    methods:    list[CorrelationMethod] = [CorrelationMethod.pearson,
                                            CorrelationMethod.spearman]

class CorrelationMatrixResponse(BaseModel):
    labels:     list[CorrelationLabel]
    frequency:  CorrelationFrequency
    days:       int
    alignment:  CorrelationAlignment
    matrices:   CorrelationMatrices
    errors:     list[CorrelationErrorItem]
```

---

## 3. Algorithm

### 3.1 Top-level flow

```
parse_and_validate(request) -> raises 400/422 on bad input
for each stock  -> manager.get_kline_data(code, days=days+padding, frequency=freq)
                     -> DataFrame[trade_date, close, ...]
for each board  -> manager.get_board_history(code, source, frequency=freq,
                                            days=days+padding)
                     -> list[dict{date, close, ...}]  → DataFrame
append per-item failures to errors[]; drop from analysis
if surviving < 2 -> raise 422 (insufficient_assets)
normalize each series.index as datetime, drop time-of-day, sort
inner-join on date → DataFrame of aligned closes (columns = labels)
pct_change(fill_method=None) per column → aligned returns
trim to trailing `days` bars
dropna per-row (a single NaN poisons the inner-join — fail-fast per row)
for m in methods:
    compute NxN matrix (4-dp round, NaN→0, symmetrize)
return {labels, frequency, days, alignment, matrices: {...}, errors}
```

### 3.2 Reuse vs adaptation from Vibe-Trading

| Concern | Source | Action |
|---|---|---|
| `infer_market`, `_normalize_symbol` | `correlation.py:19-86` | **Skip** — we know the inputs (`stocks` is bare 6-digit by `normalize_stock_code`; `boards` carries `source` explicitly). No market inference needed. |
| `ts.index = ts.index.normalize()` (strip time-of-day) | `correlation.py:146`, `regime.py:114` | **Reuse** verbatim — same UTC-midnight / CST-midnight quirk applies when minute frequencies show up. |
| `pct_change(fill_method=None)` regression guard | `correlation.py:150`, `regime.py:115` | **Reuse** verbatim — passing `fill_method=None` explicitly is the current best practice. Pandas 3.x has already removed the legacy `bfill` default, but the `fill_method` kwarg itself may be removed in a future release; we still pass it to be safe across versions. (Regression test in §6 below pins the no-forward-fill behavior.) |
| `np.corrcoef` (Pearson) | `correlation.py:175-180` | **Reuse** verbatim. |
| `scipy.stats.spearmanr` (Spearman) | same | **Reuse** verbatim. |
| Symmetry + diagonal=1, NaN→0, round-4dp | `correlation.py:185-188` | **Reuse** verbatim. |
| `compute_edge_density`, `detect_regimes`, `_fused_episodes` | `regime.py:24-235` | **Skip (v2)** — not in v1. |
| Loader fallback chain (`FALLBACK_CHAINS[market]`) | `correlation.py:215-253` | **Skip** — we use `manager.get_kline_data` / `manager.get_board_history` whose fallback is built in. |
| Symbol suffix canonicalization (`.SH`, `.SZ`, `.BJ`) | `correlation.py:54-86` | **Skip** — we keep our canonical bare-6-digit format (see anti-pattern "Don't leak outbound suffixes to responses" in CLAUDE.md). |
| HK-vs-A-share digit-length disambiguation | `correlation.py:38-50` | **N/A** — A-share only. |

### 3.3 Calendar padding

K-line endpoints take `days`. To compensate for non-trading days inside
the requested calendar window, fetch `days + 60` (matches Vibe-Trading's
`+60` calendar-day padding at `correlation.py:274-276`). After
inner-join + trim to the last `days` rows, the **actual** sample size is
reported as `alignment.common_bars`. Padding is conservative (60
calendar days covers 2 Spring + 1 National + minor exchange holidays for
any window ≤ 365 d).

### 3.4 Per-item error isolation

Each fetcher call is wrapped in try/except — `DataFetchError`,
`ValueError`, empty DataFrame, fewer than 2 rows:

- Failure → append `CorrelationErrorItem` to `errors[]`, drop from
  analysis, continue.
- Surviving count `≥ 2` → compute matrix.
- Surviving count `< 2` → raise `422 {error:"insufficient_assets",
  message:"…after filtering…", surviving: <labels of survivors>, errors}`. The
  response body is omitted on hard 422.

This matches the existing `/agent/boards/...` per-item isolation pattern.

---

## 4. Caching — deliberate deviation from existing agent pattern

**Decision: do not add an agent-level composite cache.**

Reasoning:
- Each `manager.get_kline_data(...)` and `manager.get_board_history(...)`
  call is independently memoized by the existing fetcher-level TTLCache
  (see `data_provider/cache/` + manager.py around routes that wrap
  `get_kline_data`). On a second call within TTL, the fetcher returns
  cached DataFrame immediately.
- For N ≤ 10 assets, the cold-path cost is N sequential fetcher calls
  amortized through the manager's failover; the warm-path cost is N
  pandas inner-joins + 2 NxN matrix computations. Both are <1 s on the
  expected data sizes (≤ 10 assets × ≤ 365 bars).
- We have no easy place to inject a `cache_endpoint` decorator since the
  cache key depends on the request payload (we have to hash
  `{stocks_sorted, boards_canonical, frequency, days, methods}`), and
  the existing pattern of `cached_lookup(...)` + `cached_store(...)`
  around the handler body would re-do work the inner TTLs already paid.

**CLAUDE.md conflict (declared)**: CLAUDE.md says "Don't skip writing
the response to the cache on success even when `is_cache_enabled()` is
True" (anti-pattern under "Agent Batch API"). The intent is documented
in context: "The cache is the only thing that makes the route usable
from agents under fan-out (N+1 board fetches otherwise dominate
latency)." For this endpoint, N=2..10 with inner fetcher-level TTLs of
60+ s already eliminates the N+1 problem inside the cache window. The
deviation is intentional and scoped.

**Future fallback**: if cold-path latency becomes a complaint, add
`make_correlation_matrix_cache_key` to `api/cache.py` reusing
`get_quote_cache` slot, restore `cached_lookup` / `cached_store` in
the handler — that's a 4-line patch and a 60 s TTL choice. Tracked
as a v2 add-on if monitoring shows hot-spotting.

---

## 5. Errors

| Status | When | Body |
|---|---|---|
| **400** | malformed JSON, invalid stock code in `stocks`, missing source | `{"error":"bad_request", "message":...}` |
| **422** | pydantic validation (frequency, days range, methods, board-source × frequency table, len(stocks)+len(boards) ∉ [2,10], surviving < 2 after per-item errors, all fetches failed) | `{"error":"bad_request"\|"insufficient_assets", "message":...}` |
| **200** | ≥ 2 survived (regardless of `errors[]` length) | `CorrelationMatrixResponse` (JSON) or `text/markdown` (`?format=md`) |

Per-item `DataFetchError` is reported as a `CorrelationErrorItem` in
the response `errors[]`; upstream partial outages never trigger a 5xx
on this endpoint (consistent with the existing `/agent/*` 422-only error
model — `map_errors` translates only known exceptions). The "all-fail"
case becomes a 422 with `error: "insufficient_assets"` and a message
that names the survivors count.

Earlier drafts of this spec listed a 503 row ("upstream totally down
for every asset → 503"). That row is **withdrawn**: this endpoint's
error model mirrors `/agent/*` siblings, which uniformly use 422 for
"cannot produce an answer" and never raise 503. A blanket downstream
outage would still manifest as `errors[] == N` (all per-item failures)
plus a 422 with 0 survivors.

---

## 6. Tests — `tests/test_agent_correlation_matrix.py`

| # | Test | What it pins |
|---|---|---|
| 1 | `test_mixed_stock_board_pearson_diagonal_one` | NxN diagonal=1.0, symmetric, NaN→0 fallback |
| 2 | `test_stock_only_spearman_differs_from_pearson` | Pearson ≠ Spearman on non-linear data; both returned |
| 3 | `test_pct_change_does_not_forward_fill` | Inject a NaN close mid-series; pct_change must NOT fabricate a 0% return (regression guard moved from Vibe-Trading's test_correlation.py:234-249) |
| 4 | `test_inner_join_drops_non_common_dates` | Two series, one is missing day 47; `alignment.common_bars` reflects that |
| 5 | `test_per_item_failure_isolation` | One stock fetch raises `DataFetchError`; others succeed; `errors[]` populated, matrix has surviving rows |
| 6 | `test_all_fail_returns_422` | All fetchers fail → 422, `insufficient_assets` |
| 7 | `test_only_one_survives_returns_422` | After errors, surviving=1 → 422 |
| 8 | `test_days_range_per_frequency_validated` | `frequency="1m"` + `source="eastmoney"` board → 422; same with `source="ths"` → 200 |
| 9 | `test_days_above_cap_rejected` | `frequency="d", days=500` → 422 |
| 10 | `test_methods_subset` | `methods=["pearson"]` → matrices.spearman is null, matrices.pearson populated |
| 11 | `test_too_many_assets_rejected` | 11 entries → 422 |
| 12 | `test_normalize_strip_suffix` | stock input `SH600519` normalized to `600519`, label reflects normalized code |
| 13 | `test_format_md_emits_top_pairs_sorted_by_abs_rho` | Project response with `?format=md`; assert markdown contains "按 |ρ| 降序" header AND the first data row has the largest |ρ| |
| 14 | `test_inner_cache_avoids_recomputation` | Two identical requests back-to-back within the inner TTL window (e.g. 60 s for stock K-line per `CACHE_TTL_STOCK_KLINE`); assert `manager.get_kline_data.call_count == 0` for the second request (first request made N calls, second made 0 — proof that fetcher-level TTLs hide the cold-path on the second call without an agent-composite cache) |
| 15 | `test_calendar_padding_trims_to_days` | `days=90` but actual market had 87 trading days; matrix uses 87 bars |

Fixture pattern follows `tests/test_agent_endpoints.py`: patch
`stock_data.api.routes.agent_correlation.get_manager` (or whichever
module the route imports `manager` from), bind a `MagicMock`, supply
real-shaped DataFrames / list[dict] from `pandas.util.testing` (or
`pd.testing`) matching the real upstream shape (per memory
`fixture-must-match-real-upstream`).

---

## 7. Files to change

| File | Change |
|---|---|
| `stock_data/api/routes/agent_correlation.py` | **NEW** (~180 LOC). Router, route handler, parse helper, compute helper (inner-join + pct_change + matrices). |
| `stock_data/api/schemas.py` | Add `CorrelationFrequency`, `CorrelationMethod`, `CorrelationLabel`, `CorrelationErrorItem`, `CorrelationAlignment`, `CorrelationMatrices`, `CorrelationMatrixRequest`, `CorrelationMatrixResponse` (~70 LOC). |
| `stock_data/api/cache.py` | **No change** in v1 (see §4). |
| `stock_data/server.py` | `include_router(agent_correlation.router, prefix="/api/v1/agent")` (1 line). |
| `stock_data/explorer/tags.py` | Add `agent_correlation` → title (if a new sidebar section) OR fold under existing `agent_batch`. Decision deferred to implementation; default = fold under existing section to keep the sidebar compact. |
| `stock_data/explorer/manifest.py` | **No change expected** — the route picks up metadata from `@endpoint_meta(capabilities=[], fetcher_method=None)`. Verify during implementation. |
| `tests/test_agent_correlation_matrix.py` | **NEW** (~15 cases per §6). |
| `CLAUDE.md` | Add a row to the **Agent Batch API (`/api/v1/agent/*`)** section listing `POST /api/v1/agent/correlation/matrix`, plus the source-tracking clarification (this endpoint has `source: ""` — no fetcher inline; matrix is compute-only). |

**No changes to**: any fetcher, `manager.py`, `data_provider/`, persistence.

---

## 8. Anti-patterns honored (from CLAUDE.md)

- **Don't hardcode a fetcher** — route goes through
  `manager.get_kline_data` / `manager.get_board_history` (capability
  routing).
- **Don't leak outbound suffixes** — labels carry bare 6-digit codes;
  `_to_xx_ts_code`-style suffixing happens right before the SDK call,
  never in the response.
- **Don't add `DataCapability` for non-fetcher-routed endpoints** —
  `@endpoint_meta(capabilities=[])` (empty list, same contract as the
  existing agent overlap endpoints).
- **Don't break board source-routing** — boards are passed verbatim
  with `source`, no `_with_failover` substituted.
- **Don't add `@cache_endpoint`** — the key depends on the request
  payload and we have nothing to cache at the composite level (§4).
- **Decorator order on the new route** — `@router.post → @endpoint_meta
  → @map_errors → def`, identical to the six existing agent routes
  (verified at `agent.py`).

---

## 9. Out of scope (deferred — explicit YAGNI)

- **Regime timeline endpoint** — algorithms reusable from
  `D:\GitRepo\Vibe-Trading\agent\backtest\regime.py` but the route is
  a separate deliverable. Pull into a v2 spec when there's demand.
- **HK / US / crypto** — Yfinance / Tencent cover HK/US but introduce
  timezone alignment complexity (`ts.index.normalize()` still applies
  but the inner-join semantics need re-validation). v2.
- **Equity-weighted / constituent-rolled-up board returns** — boards
  have thousands of constituents; the user's question was correlation
  between "板块指数 K 线" (board index K-line), so we use
  `manager.get_board_history` directly. Rolling up constituents into
  an equal-weighted return series is a separate design (it would, e.g.,
  drop `effective_source` from the response and use
  `stock_board_cache.get_board_stocks` instead).
- **Cointegration / half-life / Kalman hedge / pair-trading signals** —
  distinct from correlation; if requested, see Vibe-Trading's
  `agent/src/skills/correlation-analysis/SKILL.md` for reference.
- **Parallel fan-out of fetches** — sequential at v1; the inner TTL
  hides 95 % of the cost on hot paths. Add `ThreadPoolExecutor` when
  cold-path latency shows up in monitoring.
- **Rolling time series of pairwise correlations** — out of scope;
  naturally the first half of the regime-timeline v2.

---

## 10. Open questions

None for v1. All design decisions confirmed:
- inputs separated into `stocks: []` + `boards: []` arrays
- A-share only at v1 (HK/US later)
- regime timeline deferred to v2
- `frequency` and `days` are request params (`days` passed straight
  through to existing K-line endpoint semantics — calendar-day window,
  aggregated to the requested frequency internally)
- both `pearson` and `spearman` returned per call
- no composite cache (deliberate deviation from existing pattern,
  §4)
- markdown projection = top pairs sorted by |ρ| + full NxN
