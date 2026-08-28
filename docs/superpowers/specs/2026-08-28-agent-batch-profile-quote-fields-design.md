# `/api/v1/agent/{stocks,indices,boards}/batch-profile` — Quote Field Expansion

> Spec for extending the `quote` block on the three batch-profile
> endpoints. Currently a 2-field anchor (`price` + `change_pct`); this
> expands it to ~23 fields covering OHLV + turnover + valuation +
> 涨跌停价 + (board-only) 板块统计. No new endpoint, no new fetcher,
> no new `DataCapability`. Reuses the existing
> `UnifiedRealtimeQuote` (stock/index path) and the THS
> `get_board_realtime` dict (board path).

**Date**: 2026-08-28
**Status**: Draft
**Scope**: schema extension (`MinimalQuote`), two helper builders
(`_build_minimal_quote_from_unified` / `_build_minimal_quote_from_board_dict`),
three call-site rewrites in `agent.py`, three MD template updates
(`render_*_batch_profile_as_md`), unit + integration tests.

---

## 1. Background

The three batch-profile endpoints (`/agent/stocks/batch-profile`,
`/agent/indices/batch-profile`, `/agent/boards/batch-profile`) emit a
`MinimalQuote` block per entry. As of 2026-08-28 the block carries only
two fields:

```json
"quote": { "price": 12.34, "change_pct": 1.23 }
```

Agent callers that need today's open / high / low / volume / turnover /
PE must fall back to a separate `/stocks/{code}/quote` or
`/boards/{code}/quote` call per code — the N+1 fetch the batch-profile
endpoints were created to avoid.

The data is already on the wire: `UnifiedRealtimeQuote` (stock/index
path, 18 fields) and `get_board_realtime` dict (board path, ~16
fields) both carry the full OHLV + valuation + 涨跌停 set. The
restriction is purely in the agent-layer schema.

This spec exposes that data on the batch-profile responses, applying
three decisions made during brainstorming:

- **One schema, three call sites.** All three endpoints share
  `MinimalQuote`. Board-only fields (`up_count` / `down_count` /
  `net_inflow` / `rank`) live on the same schema, with `None` on the
  stock / index path. Result: one type, one MD template family, one
  client-side parser. Trade-off: a stock `quote` carries several
  `None` fields (e.g. `up_count`). That matches the existing
  `StockQuote` / `BoardQuoteResponse` precedent where "field present
  in schema, `None` upstream" is the norm.

- **Amount unified to 元.** Stock / index upstream returns amount in
  元 (passed through). Board upstream returns amount in 亿元; the
  helper multiplies by 1e8 to align with the rest of the server's
  public API surface (`BoardQuoteResponse.amount` at
  `/boards/{code}/quote` already does the same `×1e8` conversion in
  `routes/boards.py:857`). Field name is `amount` — 元 is the
  canonical unit the server reports everywhere else, so no rename /
  no `*_yi` suffix. `volume` is NOT unit-normalized: stock/index
  upstream is 股 (per spec §3.4 invariant — `KLineData.volume_unit`
  is always `"share"`); board upstream is 万手. Normalizing both
  into a single integer field is impossible without either
  precision loss (round 万手 → 手) or range overflow (multiply
  万手 by 10000 → 股 into the int64 max-out zone for high-volume
  indices). Disambiguating by `volume_unit` follows the existing
  `KLineData.volume_unit` precedent.

- **MD projection: 4-subgroup table.** `?format=md` rendering expands
  from one line (`- 最新: 12.34 (+1.23%)`) to four sub-tables:
  价格 / 量价 / 估值 / 板块统计. None values render as `—`, never
  omitted, per the api-reference.md "No data is dropped" contract and
  the test pinning in
  `tests/test_agent_batch_features.py::TestFormatMdFeatureCompleteness`.

**Non-goals**:
- Splitting into three separate schemas (`StockBatchQuote` /
  `IndexBatchQuote` / `BoardBatchQuote`). Decided against during
  brainstorming — field-shape divergence is small enough that one
  schema with conditional `None`s is cleaner than three
  near-duplicate types.
- Reusing `StockQuote.from_unified_quote()` directly. The field set
  on `StockQuote` is correct, but its `_nested` flag, the
  `current_price`/`change_amount` rename, the `volume_unit` /
  `pe_static` / `mcap_yi` conventions, and the `_serialize` semantics
  are all designed for the top-level `/stocks/{code}/quote` path. A
  dedicated `_build_minimal_quote_from_unified` mirrors the same
  mapping without dragging the nested-flag or schema-level concerns.
- Backward-compatible alias. The new field set strictly extends
  `MinimalQuote`; old clients reading only `price` / `change_pct`
  continue to work — no deprecation cycle needed.
- Re-introducing a composite cache. The batch-profile endpoints
  explicitly rely on fetcher-level TTLs (spec §5 / commit
  `0bdd5a7`). Adding a composite cache here would re-create the
  stale-risk window that was just removed.

---

## 2. Public API — Response shape changes

### 2.1 Stock path — `/agent/stocks/batch-profile`

Before:

```json
{
  "results": [{
    "code": "600519",
    "name": "贵州茅台",
    "quote": { "price": 1680.0, "change_pct": 1.23 },
    "features": { "trend": {...}, "pivots": {...}, "volume": {...} },
    "info": null,
    "boards": { "source": "persistence", "data": [...] },
    "errors": []
  }]
}
```

After (`quote` block expanded):

```json
{
  "results": [{
    "code": "600519",
    "name": "贵州茅台",
    "quote": {
      "price": 1680.0,
      "change_pct": 1.23,
      "change_amount": 20.4,
      "open": 1660.0,
      "high": 1690.0,
      "low": 1655.0,
      "prev_close": 1659.6,
      "volume": 12345678,
      "volume_unit": "share",
      "amount": 2050000000.0,
      "turnover_pct": 0.45,
      "amplitude_pct": 2.11,
      "volume_ratio": 1.2,
      "pe_ratio": 25.3,
      "pb_ratio": 8.7,
      "mcap_yi": 21123.5,
      "float_mcap_yi": 21000.1,
      "limit_up": 1825.56,
      "limit_down": 1493.64,
      "up_count": null,
      "down_count": null,
      "net_inflow": null,
      "rank": null
    },
    "features": { ... },
    "info": null,
    "boards": { ... },
    "errors": []
  }]
}
```

### 2.2 Index path — `/agent/indices/batch-profile`

`IndexProfile.quote` carries the same expanded shape. Index-specific
notes:

- `pe_ratio` / `pb_ratio` / `mcap_yi` / `float_mcap_yi` / `limit_up` /
  `limit_down` are typically `None` upstream — index realtime payloads
  don't carry these. They render as `—` in MD.
- `volume` / `amount` populated by `ZhituFetcher` / `AkshareFetcher`
  per upstream support; `volume_unit="share"`. Spec §3.4 (volume
  unit invariant) says all per-bar volume is 股; index realtime
  volume follows the same invariant.
- Board-only fields (`up_count` / `down_count` / `net_inflow` /
  `rank`) are `None` on indices.

### 2.3 Board path — `/agent/boards/batch-profile`

`BoardProfile.quote` carries the same expanded shape. Board-specific
notes:

- `volume_unit = "wan_shou"` (volume in 万手).
- `amount` is multiplied by 1e8 (THS upstream returns 亿元, server
  convention is 元 across the API surface — see
  `routes/boards.py:857`).
- `pe_ratio` / `pb_ratio` / `mcap_yi` / `float_mcap_yi` / `turnover_pct`
  / `limit_up` / `limit_down` are `None` (THS realtime dict doesn't
  expose them).
- `up_count` / `down_count` / `net_inflow` (亿元) / `rank` populated
  from the THS upstream dict.

### 2.4 Field inventory

| Field | Type | Stock | Index | Board | Source / note |
|---|---|---|---|---|---|
| `price` | float \| None | ✓ | ✓ | ✓ | UnifiedRealtimeQuote / board dict |
| `change_pct` | float \| None | ✓ | ✓ | ✓ | same |
| `change_amount` | float \| None | ✓ | ✓ | ✓ | same |
| `open` | float \| None | ✓ | ✓ | ✓ | same |
| `high` | float \| None | ✓ | ✓ | ✓ | same |
| `low` | float \| None | ✓ | ✓ | ✓ | same |
| `prev_close` | float \| None | ✓ | ✓ | ✓ | `pre_close` on stock / `prev_close` on board |
| `volume` | int \| None | ✓ | ✓ | ✓ | raw value; see `volume_unit` |
| `volume_unit` | str | `"share"` | `"share"` | `"wan_shou"` | static per endpoint |
| `amount` | float \| None | ✓ | ✓ | ✓ | unified to 元 (board upstream 亿元 ×1e8, stock/index pass-through) |
| `turnover_pct` | float \| None | ✓ | ✓ | ✗ | stock/index only; `UnifiedRealtimeQuote.turnover_rate` |
| `amplitude_pct` | float \| None | ✓ | ✓ | ✗ | amplitude fallback `(h-l)/prev_close*100` when upstream omits |
| `volume_ratio` | float \| None | ✓ | ✓ | ✗ | 量比; `UnifiedRealtimeQuote.volume_ratio` |
| `pe_ratio` | float \| None | ✓ | ✗ | ✗ | index/board upstream don't expose |
| `pb_ratio` | float \| None | ✓ | ✗ | ✗ | same |
| `mcap_yi` | float \| None | ✓ | ✗ | ✗ | `UnifiedRealtimeQuote.total_mv / 1e8` |
| `float_mcap_yi` | float \| None | ✓ | ✗ | ✗ | `UnifiedRealtimeQuote.circ_mv / 1e8` |
| `limit_up` | float \| None | ✓ | ✗ | ✗ | Zzshare / Tencent only |
| `limit_down` | float \| None | ✓ | ✗ | ✗ | Zzshare / Tencent only |
| `up_count` | int \| None | ✗ | ✗ | ✓ | THS board realtime only |
| `down_count` | int \| None | ✗ | ✗ | ✓ | same |
| `net_inflow` | float \| None | ✗ | ✗ | ✓ | 资金净流入 亿元 |
| `rank` | str \| None | ✗ | ✗ | ✓ | e.g. `"229/389"` |

`✗` means "upstream doesn't expose; field present in schema as None".

---

## 3. Schema — `MinimalQuote` extension

`stock_data/api/schemas.py` — `MinimalQuote` (currently ~5 lines,
adding ~20):

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

The class lives at the bottom of the existing 12-line `MinimalQuote`
declaration; the `pass` is replaced with the field block above. No
other schema changes.

---

## 4. Helpers — Two pure builders

Add to `stock_data/api/routes/agent.py`, just above the
`post_boards_batch_profile` route handler:

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
        volume=q.get("volume"),  # THS upstream uses safe_int → int | None; pass-through
        volume_unit="wan_shou",
        amount=(raw_amount * 1e8) if raw_amount is not None else None,
        up_count=q.get("up_count"),
        down_count=q.get("down_count"),
        net_inflow=q.get("net_inflow"),  # board upstream already 亿元; pass-through
        rank=q.get("rank"),
    )
```

Both helpers are pure functions — no I/O, no exceptions raised on
partial input, return `MinimalQuote` with `None` for missing fields.
Idempotent on empty input (returns a default-instance `MinimalQuote`).

---

## 5. Call-site rewrites — `agent.py`

Three route handlers updated; each has exactly one line that touches
the `MinimalQuote` constructor today. The change is the same shape in
all three: replace the existing constructor with the matching helper.

### 5.1 `get_indices_batch_profile` (~line 658)

```python
# before
quote = MinimalQuote(price=q.price, change_pct=q.change_pct)

# after
quote = _build_minimal_quote_from_unified(q) if q is not None else None
```

Same `q is None` guard as today. The `try / except (DataFetchError,
ValueError)` block above is unchanged.

### 5.2 `post_stocks_batch_profile` (~line 905)

```python
# before
quote = MinimalQuote(price=q.price, change_pct=q.change_pct)
name = getattr(q, "name", "") or ""

# after
quote = _build_minimal_quote_from_unified(q) if q is not None else None
name = q.name or ""
```

Both rewrites stay inside the existing `if q is not None:` block (which
is itself inside the `try / except`). The defensive
`getattr(q, "name", "")` collapses to `q.name or ""` because
`UnifiedRealtimeQuote` always declares `name: str` — it's never
missing as an attribute, only sometimes empty as a value. The `or ""`
fallback handles the empty-string case identically.

### 5.3 `post_boards_batch_profile` (~line 1027)

```python
# before
quote = MinimalQuote(
    price=q.get("price"),
    change_pct=q.get("change_pct"),
)

# after
quote = _build_minimal_quote_from_board_dict(q) if q is not None else None
```

`q` is the dict from `manager.get_board_realtime(code, source="ths")`;
`None` means upstream failed (already surfaced via `errors.quote`).
The `try / except` block above is unchanged.

### 5.4 Imports

No new top-level imports needed — both helpers are local in `agent.py`,
and `MinimalQuote` is already imported at line 93.

---

## 6. MD projection — 4-subgroup table

### 6.1 The four subgroups

```
### 价格
| 字段 | 值 |
|---|---|
| 当前 | 12.34 |
| 涨跌额 | +0.15 |
| 涨跌幅 | +1.23% |
| 今开 | 12.20 |
| 最高 | 12.40 |
| 最低 | 12.10 |
| 昨收 | 12.19 |
| 涨跌停价 | 13.41 / 11.10 |     # only on stock path

### 量价
| 字段 | 值 |
|---|---|
| 成交量 | 12,345,678 股 / 1,534 万手 | # unit-aware
| 成交额 | 2,050,000,000 |        # 元,unified
| 换手率 | 0.45% |                # stock/index only
| 振幅 | 2.11% |                  # stock/index only
| 量比 | 1.20 |                    # stock/index only

### 估值
| 字段 | 值 |
|---|---|
| PE | 25.30 |                     # stock only
| PB | 8.70 |                      # stock only
| 总市值 | 21,123.50 亿 |          # stock only
| 流通市值 | 21,000.10 亿 |        # stock only

### 板块统计
| 字段 | 值 |
|---|---|
| 上涨家数 | 12 |                  # board only
| 下跌家数 | 5 |                   # board only
| 资金净流入 | 1.23 亿 |            # board only
| 涨幅排名 | 229 / 389 |            # board only
```

### 6.2 Empty-subgroup rule (CLAUDE.md)

Each subgroup is only rendered when at least one of its fields is
non-`None`. When the whole subgroup is `None` for that endpoint (e.g.
`估值` on index / board), skip the heading + table entirely — the
agent already sees `quote` is `None` or partially populated. This is
NOT the same anti-pattern as "computed but blank": the schema itself
documents that valuation only applies to stock, so the absence is a
structural fact, not a missing-data signal.

When the subgroup has SOME fields populated and others `None`, render
the subgroup with `None` cells as `—` (existing `_md_num` behavior).

### 6.3 Implementation — single helper

Add to `agent.py` (just above `_md_feature_block`):

```python
def _md_quote_block(out: list[str], q) -> None:
    """Render the MinimalQuote block as four subgroup tables.

    Skips empty subgroups entirely (see §6.2 rationale). Renders None
    cells as "—" via the existing _md_num helper.
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
    if any(v for _, v in price_rows if v and v != "—"):
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
    if any("—" not in v and v for _, v in vol_rows):
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

### 6.4 Per-endpoint MD rewrites

Three templates updated. The stocks template has no existing failure
branch (errors are surfaced per-aspect via `errors[]`), so the
"before/after" is straightforward. The indices and boards templates
ALREADY have an else branch that surfaces the failure (`- 行情失败: ...`)
on the `quote` key — the rewrite preserves that branch verbatim.

**Stocks template** (`render_stocks_batch_profile_as_md`):

```python
# before
if entry.quote:
    out.append(f"- 最新: {_md_num(entry.quote.price)} ({_md_pct(entry.quote.change_pct)})")
out.append("")

# after
quote_err = next((e.message for e in entry.errors if e.aspect == "quote"), None)
if entry.quote:
    _md_quote_block(out, entry.quote)
elif quote_err:
    out.append(f"- 行情失败: {quote_err}")
out.append("")
```

The stocks template's errors shape is `list[StockBatchAspectError]`
(not `dict[str, str | None]`), so we extract the quote error by
filtering on `e.aspect == "quote"`.

**Indices / boards templates** (`render_indices_batch_profile_as_md` /
`render_boards_batch_profile_as_md`):

```python
# before
if idx.quote:  # or board.quote
    out.append(f"- 最新: {_md_num(idx.quote.price)} ({_md_pct(idx.quote.change_pct)})")
else:
    out.append(f"- 行情失败: {(idx.errors or {}).get('quote') or 'no quote'}")
out.append("")

# after (else branch unchanged)
if idx.quote:  # or board.quote
    _md_quote_block(out, idx.quote)
else:
    out.append(f"- 行情失败: {(idx.errors or {}).get('quote') or 'no quote'}")
out.append("")
```

`_MD_TEMPLATES` map unchanged — same template function names, same
route keys.

---

## 7. Error handling — unchanged

The per-aspect error isolation contract (CLAUDE.md "Agent Batch API"
section) is untouched:

- A single quote failure sets `errors.quote = "<exc>"` and leaves
  `quote` as `None`. The rest of the response (features / info /
  boards) is still emitted.
- A `None` field on a successful quote is NOT an error — it's the
  documented "field not exposed upstream" signal.
- Both helpers return `MinimalQuote` for any non-None input without
  raising; the route handlers continue to wrap the upstream call in
  `try / except`.

No new error shapes, no new error codes, no new HTTP statuses.

---

## 8. Testing — TDD

### 8.1 Unit tests — `tests/test_minimal_quote_helpers.py` (new file)

```python
class TestBuildMinimalQuoteFromUnified:
    def test_all_fields_populated(self): ...
    def test_amplitude_fallback_h_minus_l_over_prev_close(self): ...
    def test_amplitude_kept_when_upstream_set(self): ...
    def test_mcap_yi_divided_by_1e8(self): ...
    def test_none_fields_pass_through(self): ...

class TestBuildMinimalQuoteFromBoardDict:
    def test_populated_fields(self): ...
    def test_volume_unit_is_wan_shou(self): ...
    def test_amount_multiplied_by_1e8_from_yi(self): ...
    def test_amount_none_when_upstream_missing(self): ...
    def test_board_only_fields(self): ...
    def test_empty_dict_returns_default_instance(self): ...
```

### 8.2 MD completeness tests — extension to `test_agent_batch_features.py`

Append to `TestFormatMdFeatureCompleteness`:

- New test `test_md_renders_quote_subgroups` — POST all three batch-
  profile endpoints with a known-good code, assert each rendered MD
  contains `### 行情`, `### 价格` (when `price is not None`),
  `### 量价`, and (board only) `### 板块统计`.
- New test `test_md_does_not_drop_quote_fields` — assert `振幅`,
  `量比`, `换手率` appear in stock MD; `上涨家数`, `资金净流入`
  appear in board MD. Pinned by JSON `quote` field presence.

### 8.3 Endpoint integration tests — `tests/test_agent_endpoints.py`

- `test_stocks_batch_profile_quote_has_extended_fields` — POST
  `["600519"]`, assert `results[0].quote` has all 21 keys.
- `test_indices_batch_profile_quote_volume_unit_share` — GET default
  codes, assert `quote.volume_unit == "share"` on every entry.
- `test_boards_batch_profile_quote_volume_unit_wan_shou` — POST
  `["885595"]`, assert `quote.volume_unit == "wan_shou"` and
  `quote.up_count is not None`.

### 8.4 Manual smoke

Three `manager.*` calls with real upstream (skipped by default,
`@pytest.mark.live_network`):

```python
@pytest.mark.live_network
def test_real_upstream_population():
    m = DataFetcherManager(...)
    s_q = m.get_realtime_quote("600519")
    i_q = m.get_index_realtime_quote("000300")
    b_q = m.get_board_realtime("885595", source="ths")
    # assert the helpers map every populated field
```

No `requires_token` markers needed — all three upstreams are token-
free in the dev environment.

---

## 9. Rollout

- Branch: `feat/agent-batch-profile-quote-fields` (single-file
  change plus two test files; matches the trivial-change threshold
  but the MD projection and field inventory are large enough that a
  branch keeps `git log --oneline` clean).
- Files touched:
  - `stock_data/api/schemas.py` — `MinimalQuote` class expansion.
  - `stock_data/api/routes/agent.py` — two helpers + three call-site
    rewrites + one MD helper + three MD-template rewrites.
  - `tests/test_minimal_quote_helpers.py` — new (unit).
  - `tests/test_agent_batch_features.py` — appended (MD completeness).
  - `tests/test_agent_endpoints.py` — appended (endpoint integration).
- Docs:
  - `CLAUDE.md` — append one paragraph under "Agent Batch API"
    noting the extended `MinimalQuote` and the
    amount-yi / volume-unit conventions.
  - `docs/agent-batch-api-proposal-2026-07-27.md` — reference link
    to this spec (the proposal predates this change).

---

## 10. Open questions

None. All three core decisions (schema shape / unit strategy / MD
projection) were resolved during brainstorming before this spec was
written. Edge cases discovered during spec self-review:

- **amplitude fallback edge case**: when `prev_close == 0` (shouldn't
  happen on a real A-share but defense-in-depth) the fallback
  computes `(h-l)/0`. Existing `StockQuote.from_unified_quote` uses
  `q.pre_close` truthiness as the guard — i.e. only falls back when
  `pre_close` is truthy. New helper uses the same guard. Pinned by
  the unit test
  `test_amplitude_fallback_skipped_when_prev_close_zero`.
- **Board amount ×1e8 conversion correctness**: must round-trip —
  `1.23` upstream (亿元) becomes `1.23e8 = 123000000.0` in the
  response. Pinned by `test_amount_multiplied_by_1e8_from_yi` and
  `test_amount_none_when_upstream_missing` (the None branch must
  NOT call `1e8`).
- **Empty dict on board realtime**: the helper returns a default
  `MinimalQuote(volume_unit="wan_shou")` for an empty dict. The
  schema's defaults ensure no `KeyError`. Pinned by
  `test_empty_dict_returns_default_instance`.

---

## 11. References

- `stock_data/api/routes/agent.py:905` — current `MinimalQuote(price,
  change_pct)` call site.
- `stock_data/api/schemas.py:1603` — current `MinimalQuote` 2-field
  definition.
- `stock_data/data_provider/core/types.py:56` — `UnifiedRealtimeQuote`
  field inventory (18 fields).
- `stock_data/data_provider/fetchers/ths_fetcher.py:1378` —
  `get_board_realtime` dict keys (the same set we map into the board
  `MinimalQuote`).
- `stock_data/api/schemas.py:50` — `StockQuote.from_unified_quote`
  (the field-mapping logic we mirror in
  `_build_minimal_quote_from_unified`).
- `docs/agent-batch-api-proposal-2026-07-27.md` — the proposal this
  spec extends.
- `docs/superpowers/specs/2026-08-27-boards-batch-profile-design.md`
  — the most recent batch-profile spec (this change inherits its
  design language).
