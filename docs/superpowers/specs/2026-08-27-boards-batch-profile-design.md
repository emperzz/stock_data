# `/api/v1/agent/boards/batch-profile` — Board-level Computed Features

> Spec for a new POST endpoint under the `/agent/*` namespace that mirrors
> the existing `/agent/indices/batch-profile` and `/agent/stocks/batch-profile`
> shapes, but for **board** assets (THS concept / industry platecodes).
>
> Each entry returns a minimal realtime quote + computed trend / pivots /
> volume features at one frequency, so an LLM agent can profile a short
> list of candidate boards in one call.

**Date**: 2026-08-27
**Status**: Draft
**Scope**: new POST handler, new schemas (`BoardsBatchProfileRequest`,
`BoardsBatchProfileResponse`, `BoardProfile`), new MD template, new test
file. **No new fetcher, no new `DataCapability` flag, no new manager
method.** Reuses `_FEATURE_FREQS` / `_resolve_and_validate_days` /
`_batch_summary` / `_render_agent` / `_md_feature_block` / `_render_dict_block`
— the same helper set indices/stocks batch-profile already use.

---

## 1. Background

The agent batch endpoint family (`/agent/*`) today exposes profile-shaped
payloads for stocks and indices, both via `build_features` over a single
K-line DataFrame. Boards are the third asset class the agent consumes
heavily (`stock-picking` §4 step 5 funnels candidate sectors; `market-recap`
§4 step 4 profiles sectors; the batch overlap / filter routes already
serve boards at the *membership* level but never at the *feature* level).

Today an agent wanting "5 candidate boards, recent trend + volume + pivots"
must either:
1. Hit `/boards/{code}/history?source=ths&frequency=d` per board (N+1),
2. Or hit `/agent/correlation/matrix` with 5 board labels (over-fetched —
   returns full pairwise matrices the caller doesn't want).

Neither is a clean "board profile" surface. This spec fills the gap with a
post-2026-08 design that mirrors the existing two batch-profile endpoints
exactly — same feature blocks, same per-aspect error isolation, same MD
projection — and applies two corrections decided during brainstorming:

- **No composite cache layer.** Boards' upstream `get_board_realtime` and
  `get_board_history` are already cached at the fetcher/manager layer
  (`get_quote_cache` short-TTL + `get_history_cache` per-frequency). A
  composite cache here would duplicate the same `(codes, frequency, days)`
  decision with no benefit (features are pure compute, sub-millisecond).
  This is a deviation from the stocks/indices endpoints, which **do**
  carry a composite cache today; see §8 Future Work for the follow-up.

- **No new code-reuse helper.** The handler directly mirrors the
  `get_indices_batch_profile` loop skeleton. A new `_aspect_try`-style
  helper was considered and rejected: stocks and indices use different
  error containers (dict vs `list[StockBatchAspectError]`), so a generic
  helper would be either ugly at the call site or force a parallel
  refactor of stocks/indices — out of scope for this change.

**Non-goals**: multi-source support (only THS implements
`get_board_realtime`; board codes are source-specific so cross-source
fan-out would force callers to send one platecode per source anyway);
exposed `board_type` param (auto-detected via stock_board cache +
ThsFetcher's internal fallback); judgment labels; raw K-line bars in the
response (use `/boards/{code}/history` instead).

---

## 2. Public API

### 2.1 Request

```
POST /api/v1/agent/boards/batch-profile
Content-Type: application/json
```

```json
{
  "codes": ["885595", "881270"],
  "frequency": "d",
  "days": 60
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `codes` | `list[str]` (1-5) | yes | THS platecodes (885xxx concept / 881xxx industry). Hard cap matches the stock-picking funnel (1-5). |
| `frequency` | `"d"\|"w"\|"m"\|"1m"\|"5m"\|"15m"\|"30m"\|"60m"` | no (default `"d"`) | Reuses `_FEATURE_FREQS` registry — same frequency set as indices/stocks batch-profile. |
| `days` | `int ≥ 2` | no | Calendar-day window. Per-frequency default + range applied via `_resolve_and_validate_days` (422 on out-of-range). |
| `format` (query) | `"json"\|"md"` | no (default `"json"`) | Same convention as every other agent route. |

### 2.2 Response (JSON)

```json
{
  "frequency": "d",
  "days": 60,
  "boards": [
    {
      "code": "885595",
      "name": "人形机器人",
      "quote": { "price": 1234.5, "change_pct": 1.23 },
      "features": {
        "trend":  { "ma": {...}, "ma_change": {...}, "adx": ..., "rsi": {...}, "boll": {...} },
        "pivots": { "window_high": {...}, "swings": [...], "pending": {...}, "params": {...} },
        "volume": { "latest_volume": ..., "vol_ratio_5": ..., "z_anomalies": [...] }
      },
      "errors": { "quote": null, "features": null }
    },
    {
      "code": "881270",
      "name": "半导体",
      "quote": { "price": 567.8, "change_pct": -0.45 },
      "features": { "trend": {}, "pivots": {}, "volume": {} },
      "errors": { "quote": null, "features": "ValueError: Source 'ths' does not support frequency '1m'..." }
    }
  ],
  "summary": { "requested": 2, "ok": 2, "failed": 0, "elapsed_ms": 187 }
}
```

`ok` here means "at least one of quote/features succeeded" — same semantic
as `get_indices_batch_profile` (no `ok` flag on entry; entry-level
health is encoded by which `errors{}` keys are null).

### 2.3 Response (MD, `?format=md`)

```markdown
# 板块批量画像 — d 60d

## 885595 人形机器人 ✓
- 最新: 1,234.50 (+1.23%)
### 指标
**趋势**
### MA
| 字段 | 值 |
|---|---|
| ma5 | ...
…

## 881270 半导体 ✓
- 最新: 567.80 (-0.45%)
### 指标 — 失败: ValueError: Source 'ths' does not support frequency '1m'...

## 汇总 — requested 2, ok 2, failed 0, elapsed 187ms
```

Same `_md_feature_block` as the other two batch-profile templates.
Empty feature blocks render `（无数据）` (trend/pivots/volume each).
Empty swings / z_anomalies render the dedicated `（无确认摆动点）` /
`（无 z>2 放量异动）` markers — never a bare `| 字段 |` skeleton.

---

## 3. Data flow

### 3.1 Per-code aspect fan-out

For each `code` in `payload.codes`:

1. **quote** (best-effort):
   ```python
   q = manager.get_board_realtime(board_code, source="ths", board_type=None)
   ```
   `board_type=None` lets `ThsFetcher` look it up from the `stock_board`
   cache and fall back to `get_board_metadata` if absent.
   - On success → `MinimalQuote(price=q.price, change_pct=q.change_pct)`.
   - On `Exception` (mirrors the catch used by stocks/indices batch-profile) →
     `errors["quote"] = "<exception class>: <message>"`, `quote = None`.
2. **features** (best-effort):
   ```python
   df, _src = manager.get_board_history(
       board_code,
       source="ths",
       frequency=_FEATURE_FREQS[frequency].mgr_frequency,
       days=max(days, profile.ma60_warmup_days),
   )
   features = BatchFeatures(**build_features(df, frequency=frequency, days=days))
   ```
   - On `Exception` →
     `errors["features"] = "<exception class>: <message>"`, `features = None`.
   - **Empty DataFrame is not an error** — `build_features` returns
     `{trend:{}, pivots:{}, volume:{}}` without raising, and `BatchFeatures`
     accepts those via `default_factory`. The MD template emits
     `（无数据）` for each empty block.
3. **name resolution** (best-effort, no errors reported):
   ```python
   name = stock_board_cache.get_board_name_with_fallback(code, "ths", manager=manager) or ""
   ```
   - Cache miss → fetcher-side fallback. Falls back to empty string silently
     (the code itself is the canonical identifier; name is decoration).

### 3.2 Aggregation

After the loop:
- `n_ok = sum(1 for b in boards if b.quote is not None or b.features is not None)`
- `summary = _batch_summary(len(codes), n_ok, started)`

### 3.3 Order preservation

The `codes` order in `payload.codes` is preserved verbatim in `boards[]`.
No sorting. This matches the stocks/indices endpoints' behavior.

---

## 4. Validation + error model

| Failure | Status | Body |
|---|---|---|
| `frequency ∉ _FEATURE_FREQS` | 422 | `{"error":"invalid_request","message":"unsupported frequency: ..."}` |
| `days` out of `_FEATURE_FREQS[frequency].days_range` | 422 | `{"error":"invalid_request","message":"days must be an int in [lo, hi] for frequency=..."}` |
| `len(codes) == 0` or `> 5` | 422 | Pydantic: `min_length=1, max_length=5` |
| Single board upstream failure | 200 (entry-level) | `errors["quote"]` / `errors["features"]` set; other boards unaffected |
| All boards failed | 200 | `summary.failed = len(codes)`; entry-level errors still populated |
| `trade_date` not used here | n/a | (intentional — boards/batch-profile has no date axis) |

### 4.1 Why 200, not 5xx, when everything failed?

Per agent-endpoint contract (CLAUDE.md §"Agent Batch API → Design
contract"): "Per-item error isolation. A single upstream failure is
reported in `errors[]`; the rest of the response is still emitted. Do not
abort the whole response on first failure." Returning 5xx when *all*
items failed would force callers to write two error-handling code paths;
200 with per-entry errors keeps the contract uniform.

---

## 5. Caching

**No composite cache layer.** This is a deliberate deviation from
`/agent/stocks/batch-profile` and `/agent/indices/batch-profile`.

Justification:

1. `manager.get_board_realtime` → `get_quote_cache` (short TTL, ~30s)
2. `manager.get_board_history` → `get_history_cache` (frequency-keyed,
   multi-day TTL — already verified to absorb the same N+1 fan-out pattern)
3. `build_features` is pure compute, sub-millisecond on a 200-bar frame

A composite cache here would:
- Add a 60s-stale risk window on top of the existing per-call caches
  (board data freshness matters more than index/stock during intraday)
- Multiply cache entries by `(codes, frequency, days)` — a 10x explosion
  vs single-key upstream caches
- Save only the `build_features` cost (~1-5ms), which is dwarfed by the
  network round-trip to THS for each board

**Removal of stock/indices composite cache is tracked separately** (see
§8 Future Work). It is intentionally **not** part of this PR — both
endpoints are live, with the composite cache as a load-bearing contract
under fan-out (the existing comment in `agent.py:874-880` notes the N+1
concern). Removing without separate validation risks regression for
agents already tuned to the 60s warm-cache shape.

---

## 6. Code reuse matrix

| Existing helper | Used by boards/batch-profile | Same as |
|---|---|---|
| `_FEATURE_FREQS` (FreqProfile dataclass) | ✓ | stocks, indices |
| `_resolve_and_validate_days(frequency, days)` | ✓ | stocks, indices |
| `_batch_summary(requested, ok, started)` | ✓ | stocks, indices |
| `_render_agent(route_key, payload, fmt)` | ✓ | every agent route |
| `_render_markdown(payload, template_fn)` | ✓ | every agent route |
| `_md_feature_block(out, features)` | ✓ | indices, stocks MD |
| `_render_dict_block(out, title, d)` | ✓ | every agent route with dict blocks |
| `_md_num` / `_md_pct` / `_md_errors` | ✓ | every agent route |
| `BatchFeatures`, `TrendFeatures`, `PivotFeatures`, `VolumeFeatures`, `MinimalQuote` | ✓ (reused verbatim) | stocks, indices |
| `IndexProfile` schema shape | ✓ (mirrored as `BoardProfile`) | indices |

**No new helper introduced.** The handler loop is structurally identical
to `get_indices_batch_profile` (both 2-aspect, errors-dict, computed
features); it just calls `manager.get_board_realtime` and
`manager.get_board_history` instead of the index/stock equivalents, and
resolves the name via `stock_board_cache.get_board_name_with_fallback`.

---

## 7. File-level changes

### 7.1 `stock_data/api/schemas.py` — add

```python
class BoardProfile(BaseModel):
    """One board in /agent/boards/batch-profile."""
    code: str
    name: str = Field(default="", description="Board name (resolved from cache/fetcher).")
    quote: MinimalQuote | None = Field(default=None, description="Realtime anchor; null when upstream failed.")
    features: BatchFeatures | None = Field(default=None, description="Computed trend/pivots/volume.")
    errors: dict[str, str | None] = Field(
        default_factory=dict,
        description="Quote/features error map; null = ok.",
    )


class BoardsBatchProfileRequest(BaseModel):
    """POST body for /agent/boards/batch-profile."""
    codes: list[str] = Field(..., min_length=1, max_length=5, description="THS platecodes (1-5).")
    frequency: Literal["d", "w", "m", "1m", "5m", "15m", "30m", "60m"] = "d"
    days: int | None = Field(default=None, ge=2, description="Calendar days; per-frequency max validated in the route.")


class BoardsBatchProfileResponse(BaseModel):
    """POST response for /agent/boards/batch-profile."""
    frequency: str = "d"
    days: int = 0
    boards: list[BoardProfile] = Field(default_factory=list)
    summary: dict = Field(default_factory=dict)
```

### 7.2 `stock_data/api/routes/agent.py` — add

- `post_boards_batch_profile` handler (mirrors `get_indices_batch_profile`,
  ~40 LOC including imports).
- `render_boards_batch_profile_as_md` template (~30 LOC, structurally
  identical to `render_indices_batch_profile_as_md`).
- One line in `_MD_TEMPLATES`: `"boards/batch-profile": render_boards_batch_profile_as_md,`.
- **No** `make_boards_batch_profile_cache_key` in `api/cache.py`.

### 7.3 `tests/test_agent_boards_batch_profile.py` — new

- `test_request_schema_validation` — codes=0 / codes=6 / unsupported
  frequency → 422
- `test_days_range_validation` — boundary checks per `_FEATURE_FREQS`
- `test_per_code_error_isolation` — mock one board failing on quote AND
  features; another succeeding on both; response still 200 with two
  entries, errors[] set per-entry
- `test_features_compute_on_min_history` — 1-bar DataFrame → empty
  trend/pivots/volume blocks, no exception
- `test_name_resolution_falls_back_silently` — cache miss → name=""
- `test_response_preserves_input_order` — reordering input codes does NOT
  change response order
- `test_md_renders_empty_feature_marker` — empty trend dict → MD emits
  `（无数据）`, not a `|---|` skeleton with zero rows
- `test_md_renders_no_swings_marker` — empty swings → MD emits
  `（无确认摆动点）`
- `test_no_cache_layer_added` — verify the handler does NOT touch
  `get_quote_cache` (regression guard against accidental cache re-introduction)

### 7.4 `docs/agent-batch-api-proposal-2026-07-27.md` — append

Add §3.2.4 "boards/batch-profile" describing the new endpoint, mirroring
§3.2.1 / §3.2.2 structurally.

### 7.5 `CLAUDE.md` — update

Add one row to the "Agent Batch API" route table:
```
| `POST /agent/boards/batch-profile` | Per-board fan-out: 极简 quote + 单 frequency 计算特征 (`trend`/`pivots`/`volume`)。1-5 codes, 单 frequency。 | per-code `manager.get_board_realtime` + `manager.get_board_history`, then `features.build_features()` |
```
And one bullet under "Design contract (don't violate these without a
spec change)" clarifying that boards/batch-profile **does not** have a
composite cache layer (deliberate deviation; see §8 Future Work).

---

## 8. Future Work

These are **out of scope** for this PR but flagged during brainstorming:

### 8.1 Remove composite cache from stocks/indices batch-profile

The `make_stocks_batch_profile_cache_key` / `make_indices_batch_profile_cache_key`
+ `cached_lookup` / `cached_store` calls in `post_stocks_batch_profile`
and `get_indices_batch_profile` duplicate the fetcher-level TTL caches
with no measurable benefit. Removal would:

- Simplify the handler (drop cache lookup + reorder logic)
- Eliminate the `_reorder_by_code` helper dependency (only used by
  cache-hit paths)
- Remove a 60s-stale risk on intraday data
- Apply the same design correction this PR makes for boards

Risk: existing agents tuned to the 60s warm-cache response shape may
need re-tuning. Mitigation: ship behind a feature flag for one release
cycle, then flip default.

**This is explicitly sequenced AFTER the boards/batch-profile PR** —
do not bundle into one change. The user reaffirmed the sequencing on
2026-08-27.

### 8.2 Multi-source fan-out (THS + EastMoney)

THS platecodes and EastMoney `BKxxxx` codes are not interoperable. A
multi-source version would require `?source=ths` (default) / `?source=eastmoney`
+ per-source board codes in the request. Out of scope today; revisit if
agents start routinely wanting both views.

### 8.3 Exposed `board_type` param

If agents want to *override* the cache-derived type (e.g., 881270 could
be both an industry and a concept depending on definition date),
exposing `board_type` as an optional request field is the natural
extension. Adds `metadata.type` to the response for clients to verify
what was used.

---

## 9. Open questions (none blocking)

None. All design decisions resolved during brainstorming on 2026-08-27
with the user (source = THS-only, board_type = auto, API shape = POST
+ codes 1-5, entry shape = IndexProfile, no composite cache, no new
helper).