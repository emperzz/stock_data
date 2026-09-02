# `/api/v1/agent/market-context` & `/api/v1/agent/market-stats` — Slim Market-Context + Move ZT/DT Pools to Market-Stats

> Spec for slimming `market-context` to messages-only (drop dragon-tiger
> and limit_pools blocks), and absorbing the zt/dt pools block into
> `market-stats` as a third per-block aggregation alongside `stocks` and
> `boards`.

**Date**: 2026-09-02
**Status**: Draft (post-brainstorm)
**Scope**: route handler + cache key + schema + MD projection +
tests for two existing endpoints. **No new fetcher, no new
`DataCapability` flag, no new manager method, no new endpoint**.
Dragon-tiger functionality is preserved by the existing
`GET /api/v1/dragon-tiger` route — only the agent-level wrapper block
is removed.

---

## 1. Background

`market-context` was originally designed as a "market panorama" endpoint
that fans out to morning briefing, market recap, flash news, **涨跌停
(ztdt) pools**, and **dragon-tiger (龙虎榜)**. After two months in
production the dragon-tiger block in market-context surfaces the same
data as `GET /api/v1/dragon-tiger` (just one level of nesting deeper),
and the zt/dt pool block is structurally a full-market snapshot that
sits naturally next to the stocks / boards distribution in
`market-stats`.

Two operational issues motivate the split:

- **Cross-session cache invalidation complexity.** Market-context's
  cache key currently includes `session` (pre/intra/post/closed)
  *only* because pre-market forces zt/dt to null while intraday /
  post-market returns the full pool data. Once pools leave, the
  session no longer affects the response content — removing one
  dimension from the cache key eliminates a class of "same date,
  different session" cache drift concerns.
- **Per-call fan-out bloat.** A market-context request currently does
  up to 6 upstream calls (briefing + recap + flash + 2 pools +
  dragon-tiger). Splitting the work lets each consumer request only
  what it needs: an LLM that wants the news snapshot no longer pays
  for pool fetches; an LLM building a full-market dashboard gets pools
  alongside the existing stocks / boards blocks for one extra HTTP
  call instead of two.

The user's explicit guidance: remove dragon-tiger from market-context
entirely; move zt/dt into market-stats.

**Non-goals**: HK / US / crypto pools (A-share only at v1);
configurable bucket / clip params for pools (no aggregation — pools
are emitted as raw lists); replacing the existing
`GET /api/v1/zt-pools` route (this spec only moves the
market-context wrapper block).

---

## 2. Public API

### 2.1 `GET /api/v1/agent/market-context` — after

```jsonc
{
  "trade_date": "2026-09-02",
  "is_trade_day": true,
  "market_session": "intraday",        // pre-market | intraday | post-market | closed
  "messages": {
    "morning_briefing": { ... } | null,   // CLS 早报 article dict
    "market_recap":      { ... } | null,   // CLS 复盘 article dict
    "flash_news": [ ... ]                  // list of FlashNewsItem-shaped dicts
  },
  "summary": { "requested": 3, "ok": 3, "failed": 0, "elapsed_ms": 184 }
}
```

**Removed fields**: `dragon_tiger`, `limit_pools`.
**Removed dependencies**: `/api/v1/zt-pools`, `/api/v1/dragon-tiger`,
`manager.get_zt_pool`, `manager.get_daily_dragon_tiger`.

**Query params** (unchanged): `flash_limit: int = 20` (1-200),
`trade_date: str | None`, `format: Literal["json","md"]`.

### 2.2 `GET /api/v1/agent/market-stats` — after

```jsonc
{
  "stocks":      { /* same as before */ } | null,
  "boards":      { /* same as before; carries source field */ } | null,
  "limit_pools": { "zt": [...] | null, "dt": [...] | null } | null,
  "errors": [
    { "block": "stocks",   "error": "...", "message": "..." },
    { "block": "boards",   "error": "...", "message": "..." },
    { "block": "zt_pool",  "error": "...", "message": "..." },
    { "block": "dt_pool",  "error": "...", "message": "..." }
  ],
  "summary": { "requested": 4, "ok": 4, "failed": 0, "elapsed_ms": 220 }
}
```

**New query params**:

| Field | Type | Default | Notes |
|---|---|---|---|
| `trade_date` | `str \| None` (YYYY-MM-DD) | server-defaulted via `trade_calendar.get_latest_trade_date_on_or_before(today)` | plumbed to `manager.get_zt_pool(pool_type="zt"/"dt", date=...)` |
| `include_pools` | `bool` | `True` | when `false`, `limit_pools` field is omitted from the JSON (route-layer `model_dump(exclude_none=True)`) and no upstream pool calls fire |
| `include_boards` | `bool` | `True` | unchanged |
| `format` | `Literal["json","md"]` | `"json"` | unchanged |

**New `errors[]` block literals**: `"zt_pool"`, `"dt_pool"` (extend
existing `Literal["stocks","boards"]`).

### 2.3 Status codes

Both endpoints: same as today. `format` invalid → 422 (FastAPI
validator). `trade_date` not YYYY-MM-DD → 400 (existing market-context
gate). Upstream failure → 200 + null block + errors[] entry.

---

## 3. Implementation

### 3.1 Files touched

| File | What |
|---|---|
| `stock_data/api/routes/agent.py` | Slim `get_market_context`; extend `get_market_stats` with pools block; new `_compute_limit_pools_block` helper; new `_md_limit_pools_block` MD renderer; `_MD_TEMPLATES` updates |
| `stock_data/api/schemas.py` | Add `MarketStatsLimitPools`; add `limit_pools` field to `MarketStatsResponse`; extend `MarketStatsErrorEntry.block` literal; **delete** `MarketContextLimitPools`, `MarketContextDragonTiger*`; **remove** `dragon_tiger` + `limit_pools` from `MarketContextResponse` |
| `stock_data/api/cache.py` | Update `make_market_stats_cache_key` signature; update `make_market_context_cache_key` signature |
| `tests/test_agent_endpoints.py` | Update / drop `TestMarketContext` tests for pools & dragon-tiger; update MD + cache-key tests |
| `tests/test_agent_market_stats.py` | Add pools tests |
| `tests/test_agent_market_stats_schemas.py` | Add `MarketStatsLimitPools` schema tests; update `MarketStatsErrorEntry` literal test |
| `docs/superpowers/specs/...` | This file |

### 3.2 Route handler — `get_market_context` (after)

```python
@router.get(
    "/agent/market-context",
    response_model=MarketContextResponse,
    responses={500: {"model": ErrorResponse, "description": "Server error"}},
    tags=["agent"],
)
@endpoint_meta(
    summary="市场消息面快照（早报 + 复盘 + 快讯；含时段判断）",
    markets=["csi"],
    capabilities=[],
    depends_on=[
        "/api/v1/calendar",
        "/api/v1/news/morning-briefing",
        "/api/v1/news/market-recap",
        "/api/v1/news/flash",
        "calendar.is_trade_date",
        "calendar.get_latest_trade_date_on_or_before",
    ],
)
@map_errors
def get_market_context(
    flash_limit: int = Query(default=20, ge=1, le=200, description="..."),
    trade_date: str | None = Query(default=None, description="..."),
    format: str = Query("json", pattern="^(json|md)$"),
) -> Response:
    if trade_date is not None and not _TRADE_DATE_RE.match(trade_date):
        raise HTTPException(status_code=400, detail={...})
    today_str = datetime.now(_CST).date().isoformat()
    is_trade_day = trade_calendar.is_trade_date(today_str)
    target_date = trade_date or trade_calendar.get_latest_trade_date_on_or_before(today_str) or today_str
    session = _classify_market_session(is_trade_day)

    cache_key = make_market_context_cache_key(flash_limit, target_date)
    hit = cached_lookup(get_quote_cache, cache_key, "agent_market_context")
    if hit is not None:
        return _render_agent("market-context", hit, format)

    started = time.monotonic()
    manager = get_manager()
    attempts: list[tuple[str, Callable, object]] = [
        ("morning_briefing", lambda: manager.get_morning_briefing(target_date)[0], None),
        ("market_recap",     lambda: manager.get_market_recap(target_date)[0],     None),
        ("flash_news",       lambda: manager.get_flash_news(limit=flash_limit)[0],  []),
    ]
    results: dict[str, object] = {}
    n_ok = 0
    for name, fn, default in attempts:
        try:
            results[name] = fn()
            n_ok += 1
        except Exception as exc:
            logger.warning(f"[agent/market-context] {name} failed: {exc}", exc_info=True)
            results[name] = default

    result = MarketContextResponse(
        trade_date=target_date,
        is_trade_day=is_trade_day,
        market_session=session,  # type: ignore[arg-type]
        messages=MarketContextMessages(
            morning_briefing=results["morning_briefing"],
            market_recap=results["market_recap"],
            flash_news=results["flash_news"],
        ),
        summary=_batch_summary(len(attempts), n_ok, started),
    )
    cached_store(get_quote_cache, cache_key, result)
    return _render_agent("market-context", result, format)
```

`_summarize_dragon_tiger` helper **deleted**.

### 3.3 New helper — `_compute_limit_pools_block`

```python
def _compute_limit_pools_block(
    manager, target_date: str, session: str
) -> tuple[MarketStatsLimitPools | None, list[MarketStatsErrorEntry]]:
    """Compute the limit_pools block for market-stats.

    Pre-market: returns (None, []) — both pools forced null per spec
    §3.2.3 (pools may not be formed yet; not a failure). Other
    sessions: per-pool fan-out with per-pool error isolation — zt
    failure emits a `{"block": "zt_pool"}` entry and leaves zt=None
    while dt is still attempted.
    """
    if session == "pre-market":
        return None, []

    errors: list[MarketStatsErrorEntry] = []
    zt: list[dict] | None = None
    dt: list[dict] | None = None

    try:
        zt, _src, _ = manager.get_zt_pool(pool_type="zt", date=target_date)
    except Exception as exc:
        logger.warning(f"[agent/market-stats] zt_pool failed: {exc}", exc_info=True)
        errors.append(
            MarketStatsErrorEntry(
                block="zt_pool", error=type(exc).__name__, message=str(exc),
            )
        )

    try:
        dt, _src, _ = manager.get_zt_pool(pool_type="dt", date=target_date)
    except Exception as exc:
        logger.warning(f"[agent/market-stats] dt_pool failed: {exc}", exc_info=True)
        errors.append(
            MarketStatsErrorEntry(
                block="dt_pool", error=type(exc).__name__, message=str(exc),
            )
        )

    return MarketStatsLimitPools(zt=zt, dt=dt), errors
```

### 3.4 Route handler — `get_market_stats` (after)

```python
@router.get(
    "/agent/market-stats",
    response_model=MarketStatsResponse,
    responses={500: {"model": ErrorResponse, "description": "Server error"}},
    tags=["agent"],
)
@endpoint_meta(
    summary="市场全量统计（个股+板块涨幅分布 + 涨跌停池 + 桶形数据）",
    markets=["csi"],
    capabilities=[],
    depends_on=[
        "/api/v1/stocks",
        "/api/v1/boards",
        "/api/v1/zt-pools",      # NEW
        "manager.get_realtime_quotes",
        "cache.get_board_list",
        "manager.get_zt_pool",
        "calendar.get_latest_trade_date_on_or_before",
    ],
)
@map_errors
def get_market_stats(
    include_boards: bool = Query(default=True, description="..."),
    include_pools: bool = Query(
        default=True,
        description="是否包含涨跌停池块;false 时只返回个股+板块 (无 zt/dt 上游调用)",
    ),
    trade_date: str | None = Query(
        default=None,
        description=(
            "交易日 YYYY-MM-DD;不传默认 = "
            "get_latest_trade_date_on_or_before(today). 影响 zt/dt 池子查询日期."
        ),
    ),
    format: str = Query("json", pattern="^(json|md)$"),
) -> Response:
    # trade_date gate (same regex as market-context)
    if trade_date is not None and not _TRADE_DATE_RE.match(trade_date):
        raise HTTPException(status_code=400, detail={...})
    today_str = datetime.now(_CST).date().isoformat()
    target_date = (
        trade_date
        or trade_calendar.get_latest_trade_date_on_or_before(today_str)
        or today_str
    )
    is_trade_day = trade_calendar.is_trade_date(today_str)
    session = _classify_market_session(is_trade_day)

    cache_key = make_market_stats_cache_key(include_boards, include_pools, target_date)
    hit = cached_lookup(get_quote_cache, cache_key, "agent_market_stats")
    if hit is not None:
        return _render_agent("market-stats", hit, format)

    started = time.monotonic()
    manager = get_manager()
    errors: list[MarketStatsErrorEntry] = []
    stocks_stats: StockStats | None = None
    boards_stats: BoardStats | None = None
    limit_pools_block: MarketStatsLimitPools | None = None

    # Pools count toward `requested` only when they'd actually be
    # attempted — pre-market returns (None, []) without firing any
    # upstream call, so it must NOT count as requested or failed.
    pools_active = include_pools and session != "pre-market"
    requested = 1 + (1 if include_boards else 0) + (1 if pools_active else 0)
    ok = 0

    # --- stocks block (always attempted) ---
    try:
        quotes, _src = manager.get_realtime_quotes("csi")
        values = [q.change_pct for q in (quotes or []) if getattr(q, "change_pct", None) is not None]
        agg = compute_aggregate(values, bin_width=STOCK_BUCKET_BIN_WIDTH, buckets_template=build_stock_buckets())
        stocks_stats = _stock_stats_from_aggregate(agg)
        ok += 1
    except Exception as exc:
        logger.warning(f"[agent/market-stats] stocks failed: {exc}", exc_info=True)
        errors.append(MarketStatsErrorEntry(block="stocks", error=type(exc).__name__, message=str(exc)))

    # --- boards block (skipped when include_boards=false) ---
    if include_boards:
        try:
            boards, src = stock_board_cache.get_board_list(board_type=None, source="ths", include_quote=True, manager=manager)
            values = [
                b.get("change_pct") for b in (boards or [])
                if isinstance(b.get("change_pct"), (int, float)) and not isinstance(b.get("change_pct"), bool)
            ]
            agg = compute_aggregate(values, bin_width=BOARD_BUCKET_BIN_WIDTH, buckets_template=build_board_buckets())
            boards_stats = _board_stats_from_aggregate(agg, src or "ths")
            ok += 1
        except Exception as exc:
            logger.warning(f"[agent/market-stats] boards failed: {exc}", exc_info=True)
            errors.append(MarketStatsErrorEntry(block="boards", error=type(exc).__name__, message=str(exc)))

    # --- limit_pools block (skipped when include_pools=false or pre-market) ---
    if pools_active:
        limit_pools_block, pool_errors = _compute_limit_pools_block(manager, target_date, session)
        errors.extend(pool_errors)
        # OK when the helper returns a non-None block (i.e. it actually
        # fired upstream calls). Per-pool failures inside the helper
        # are surfaced via errors[] but do NOT decrement ok — the
        # call DID complete (with partial data).
        if limit_pools_block is not None:
            ok += 1

    result = MarketStatsResponse(
        stocks=stocks_stats,
        boards=boards_stats,
        limit_pools=limit_pools_block,
        errors=errors,
        summary=_batch_summary(requested, ok, started),
    )
    cached_store(get_quote_cache, cache_key, result)
    return _render_agent("market-stats", result, format)
```

**Wire format for `limit_pools`**: the field is always present in the
JSON output (Pydantic serializes the model field as `null` when
unset). Consumers distinguish three states via the field's inner
shape + `errors[]`:

| State | `limit_pools` JSON | `errors[]` entries |
|---|---|---|
| include_pools=false | `{"zt": null, "dt": null}` | none |
| pre-market, include_pools=true | `{"zt": null, "dt": null}` | none (not attempted, not failed) |
| include_pools=true, both OK | `{"zt": [...], "dt": [...]}` | none |
| include_pools=true, zt failed | `{"zt": null, "dt": [...]}` | `[{"block": "zt_pool"}]` |
| include_pools=true, dt failed | `{"zt": [...], "dt": null}` | `[{"block": "dt_pool"}]` |
| include_pools=true, both failed | `{"zt": null, "dt": null}` | 2 entries |

The MD renderer (`render_market_stats_as_md`) checks the same shape
and emits `## 涨跌停` with an appropriate marker for each state.

### 3.5 Schema changes — `stock_data/api/schemas.py`

```python
# NEW — replaces MarketContextLimitPools in the market-stats path
class MarketStatsLimitPools(BaseModel):
    """涨跌停 block of /agent/market-stats.

    Both pools forced to null in pre-market (per spec §3.2.3). Each
    pool is independently nullable: zt may be null while dt has data
    (per-pool error isolation).
    """

    zt: list[dict] | None = Field(
        default=None,
        description="涨停池 list. null in pre-market OR on per-pool upstream failure.",
    )
    dt: list[dict] | None = Field(
        default=None,
        description="跌停池 list. null in pre-market OR on per-pool upstream failure.",
    )


# UPDATED — extend error-entry literal to cover pool failures
class MarketStatsErrorEntry(BaseModel):
    block: Literal["stocks", "boards", "zt_pool", "dt_pool"]
    error: str
    message: str


# UPDATED — add limit_pools field; default None keeps
# include_pools=false wire-clean (dropped via model_dump)
class MarketStatsResponse(BaseModel):
    stocks: StockStats | None
    boards: BoardStats | None
    limit_pools: MarketStatsLimitPools | None = None
    errors: list[MarketStatsErrorEntry]
    summary: dict


# UPDATED — slim to messages-only
class MarketContextResponse(BaseModel):
    """GET response for /agent/market-context.

    Post-2026-09-02: messages-only snapshot. ZT/DT pools moved to
    /agent/market-stats; dragon-tiger removed entirely (callers use
    GET /api/v1/dragon-tiger directly).
    """

    trade_date: str
    is_trade_day: bool
    market_session: MarketSession
    messages: MarketContextMessages = Field(default_factory=MarketContextMessages)
    summary: dict = Field(default_factory=dict)


# DELETED — no longer referenced anywhere
#   MarketContextLimitPools
#   MarketContextDragonTiger
#   MarketContextDragonTigerSummary
#   MarketContextDragonTigerSummaryTop
```

### 3.6 Cache keys — `stock_data/api/cache.py`

```python
def make_market_context_cache_key(flash_limit: int, trade_date: str) -> str:
    """Cache key for GET /agent/market-context.

    Session removed (post-2026-09-02): the response no longer varies
    by session — pools and dragon-tiger moved out, so pre/intra/post/
    closed produce identical bodies for a given (flash_limit,
    trade_date). Kept the two-knob signature stable for backwards
    compatibility with any existing cache entries.
    """
    return f"agent_market_context:{flash_limit}:{trade_date}"


def make_market_stats_cache_key(
    include_boards: bool, include_pools: bool, trade_date: str
) -> str:
    """Cache key for GET /api/v1/agent/market-stats.

    All three knobs participate: changing any of them produces a
    materially different response (different blocks populated / zt
    pool for a different date). 60s TTL via get_quote_cache.
    """
    return f"agent_market_stats:{include_boards}:{include_pools}:{trade_date}"
```

### 3.7 MD projection

**market-context MD (after)**: drop the `## 涨跌停` and `## 龙虎榜`
sections from `render_market_context_as_md`. Header sequence becomes
`# 市场全景 — {date} {session}` + `## 消息面` (早报/复盘/快讯) +
`## 汇总`. `render_market_context_as_md` updated accordingly.

**market-stats MD (after)**: new `_md_limit_pools_block` helper +
updated `render_market_stats_as_md` calls it after the boards block:

```python
def _md_limit_pools_block(out: list[str], pools) -> None:
    """Render the limit_pools block. Always emits a `## 涨跌停` heading;
    distinguishes disabled / pre-market / partial / full via inner labels."""
    out.append("## 涨跌停")
    if pools is None:
        # Field absent from JSON (defensive; the handler should always
        # populate it as `MarketStatsLimitPools(zt=None, dt=None)` for
        # pre-market / include_pools=false, but a None model is also OK).
        out.append("（未启用）")
        out.append("")
        return
    for label, key, headers in [
        ("涨停池", "zt", "| 代码 | 名称 | 涨跌幅 | 涨停时间 | 连板数 | 所属行业 |"),
        ("跌停池", "dt", "| 代码 | 名称 | 涨跌幅 | 跌停时间 | 所属行业 |"),
    ]:
        rows = getattr(pools, key)
        if rows is None:
            out.append(f"**{label}**: null")
        elif not rows:
            out.append(f"**{label}**: （空）")
        else:
            out.append(f"**{label}**: {len(rows)} 只")
            out.append("")
            out.append(headers)
            out.append("|---|---|---|---|---|---|")
            for s in rows:
                code = s.get("code", "")
                name = s.get("name", "")
                pct = s.get("pct_chg") or s.get("change_pct")
                if key == "zt":
                    t = s.get("limit_time") or s.get("first_limit_time") or ""
                    lb = s.get("limit_count") or s.get("continuous_limit_count")
                    industry = s.get("industry", "")
                    out.append(
                        f"| {code} | {name} | {_md_pct(pct)} | {t} | "
                        f"{lb if lb is not None else '—'} | {industry} |"
                    )
                else:
                    t = s.get("limit_time") or s.get("first_limit_time") or ""
                    industry = s.get("industry", "")
                    out.append(
                        f"| {code} | {name} | {_md_pct(pct)} | {t} | {industry} |"
                    )
        out.append("")


def render_market_stats_as_md(p: MarketStatsResponse) -> str:
    out: list[str] = ["# 市场全量统计", ""]
    out.extend(_md_stats_block("个股", p.stocks, total_universe_label="A 股全市场"))
    out.append("")
    out.extend(_md_stats_block("板块", p.boards, total_universe_label="ths 板块清单"))
    out.append("")
    _md_limit_pools_block(out, p.limit_pools)
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
```

`_MD_TEMPLATES["market-stats"]` continues to point at
`render_market_stats_as_md`.

---

## 4. Error isolation matrix (market-stats)

| Scenario | stocks | boards | limit_pools (wire) | errors[] | summary.{req,ok,failed} |
|---|---|---|---|---|---|
| All blocks OK | populated | populated | `{zt:[...], dt:[...]}` | `[]` | `{4, 4, 0}` |
| Stocks fails | `null` | populated | `{zt:[...], dt:[...]}` | `[stocks]` | `{4, 3, 1}` |
| Boards fails | populated | `null` | `{zt:[...], dt:[...]}` | `[boards]` | `{4, 3, 1}` |
| ZT pool fails | populated | populated | `{zt:null, dt:[...]}` | `[zt_pool]` | `{4, 3, 1}` |
| DT pool fails | populated | populated | `{zt:[...], dt:null}` | `[dt_pool]` | `{4, 3, 1}` |
| Both pools fail | populated | populated | `{zt:null, dt:null}` | `[zt_pool, dt_pool]` | `{4, 2, 2}` |
| Pre-market, pools on | populated | populated | `{zt:null, dt:null}` | `[]` | `{3, 3, 0}` |
| Pre-market, pools off | populated | populated | `{zt:null, dt:null}` | `[]` | `{2, 2, 0}` |
| `include_pools=false` | populated | populated | `{zt:null, dt:null}` | `[]` | `{2, 2, 0}` (or `{1, 1, 0}` with `include_boards=false`) |
| All blocks fail | `null` | `null` | `{zt:null, dt:null}` | 3+ entries | `{4, 0, 4}` |

`limit_pools` is always present in the JSON. The three "null but no
error" rows (pre-market × 2, include_pools=false) all surface as
`{zt:null, dt:null}` with empty `errors[]` — the difference is
visible only in `summary.requested` (counts the upstream call) and the
absence of any pool-specific error entry.

Pre-market contract rationale: per spec §3.2.3, 涨跌停 pools may not be
formed yet at pre-market — emitting null is the documented behavior,
not a failure. We treat pre-market as "not applicable" — counted out
of `requested`, no error reported. Distinct from "upstream failed"
where the field is present with the failing inner pool(s) null and
`errors[]` records the cause.

---

## 5. Tests

### 5.1 `tests/test_agent_endpoints.py` — `TestMarketContext` changes

**Delete** (pools / dragon-tiger no longer in market-context):

- `test_pre_market_pools_forced_null` — no pools field to assert on.
- `test_dragon_tiger_failure_isolated_other_blocks_served` — no dragon-tiger field.
- `test_market_context_pre_market_summary_drops_pool_attempts` — pre-market no longer affects summary.
- `test_market_context_cache_key_includes_session` — cache key no longer has session.
- `test_market_context_zt_dt_full_pool_table` — no pools section.
- `test_market_context_dragon_tiger_full_table` — no dragon-tiger section.
- `test_market_context_dragon_tiger_summary_still_present` — no dragon-tiger section.

**Update**:

- `test_happy_path_all_blocks_present` → renamed to
  `test_messages_only_no_pools_no_dragon_tiger`. Asserts `limit_pools`
  and `dragon_tiger` keys are **absent** from the response.
- `test_morning_briefing_null_on_no_article` — no change (only news
  block; should still work).
- `test_trade_date_query_param` — drop `get_daily_dragon_tiger`
  assertion; only morning_briefing + market_recap receive trade_date.
- `test_cache_hit_same_flash_limit_and_date` — drop `get_daily_dragon_tiger` mock.

**TestPhase2DefensiveGuards** changes:

- `test_market_context_trade_date_malformed_400` — unchanged.
- `test_market_context_cache_key_includes_session` — DELETE
  (session no longer in key). Add new
  `test_market_context_cache_key_omits_session` asserting
  `make_market_context_cache_key(20, "2026-09-02") ==
  "agent_market_context:20:2026-09-02"`.

**TestFormatMd** changes:

- `test_market_context_md` — drop `## 涨跌停` and `## 龙虎榜`
  assertions; add `### 快讯` (already present) and assert NO `## 涨跌停` /
  NO `## 龙虎榜` substrings in body.

### 5.2 `tests/test_agent_market_stats.py` — additions

| Test | What it pins |
|---|---|
| `test_market_stats_limit_pools_happy_path` | zt + dt both populated; `errors==[]`; `summary.requested==3` (stocks + boards + pools), `ok==3` |
| `test_market_stats_zt_pool_failure_isolates_dt` | `manager.get_zt_pool(side_effect=[..., raise DataFetchError("zt down"), ...])` → `limit_pools.zt is None`, `limit_pools.dt` populated, `errors[]` has 1 `zt_pool` entry, `summary.ok==2` |
| `test_market_stats_dt_pool_failure_isolates_zt` | symmetric — dt fails, zt populated |
| `test_market_stats_both_pools_fail` | both raise → `limit_pools.zt is None and limit_pools.dt is None`, 2 pool errors in `errors[]` |
| `test_market_stats_pre_market_pools_forced_null` | patch `_classify_market_session` to "pre-market" → `manager.get_zt_pool.assert_not_called()`, `limit_pools.zt is None and limit_pools.dt is None` (field present, both inner nulls), `errors==[]`, `summary.requested==2` |
| `test_market_stats_include_pools_false_skips_pools_upstream` | `?include_pools=false` → `manager.get_zt_pool.assert_not_called()`, `limit_pools.zt is None and limit_pools.dt is None` (field present, both inner nulls), `errors==[]`, `summary.requested==2` |
| `test_market_stats_pools_trade_date_passed_through` | `?trade_date=2026-09-01` → `manager.get_zt_pool.call_args.kwargs["date"]=="2026-09-01"` for both zt and dt |
| `test_market_stats_pools_trade_date_malformed_400` | `?trade_date=not-a-date` → 400 |
| `test_market_stats_pools_trade_date_default_to_latest_trade_date` | omit `?trade_date` → call goes through `get_latest_trade_date_on_or_before(today)`; pin with monkeypatch on `trade_calendar` |
| `test_market_stats_pools_cache_hit` | second call with same `(include_boards, include_pools, trade_date)` → `manager.get_zt_pool.call_count == 1` (cache hit) |
| `test_market_stats_format_md_renders_pools_section` | `?format=md` → body contains `## 涨跌停`, `**涨停池**`, `**跌停池**`, table headers |
| `test_market_stats_format_md_omits_pools_when_disabled` | `?include_pools=false&format=md` → body contains `## 涨跌停` heading + `**涨停池**: null` / `**跌停池**: null` markers (no upstream call, no failure — field is present-but-null) |

### 5.3 `tests/test_agent_market_stats_schemas.py` — additions

| Test | What it pins |
|---|---|
| `test_market_stats_limit_pools_both_populated` | `{zt:[...], dt:[...]}` round-trip |
| `test_market_stats_limit_pools_both_null` | `{zt:None, dt:None}` — per-pool failure round-trip |
| `test_market_stats_limit_pools_zt_only` | asymmetric (zt OK, dt failed) |
| `test_market_stats_error_entry_pool_literals` | `MarketStatsErrorEntry(block="zt_pool", ...)` and `block="dt_pool", ...` validate |
| `test_market_stats_response_includes_limit_pools_field` | `MarketStatsResponse` model_fields contains `limit_pools` |
| `test_market_stats_response_default_limit_pools_is_none` | omitting `limit_pools` keyword → field is None (enables `exclude_none` strip) |

### 5.4 Schema delete verification (post-change sanity check)

A grep for `MarketContextLimitPools` / `MarketContextDragonTiger` /
`MarketContextDragonTigerSummary` should return zero matches in both
`stock_data/` and `tests/`. (Mechanical — pinned by running `rg
"MarketContext(LimitPools|DragonTiger)"` after the change.)

---

## 6. Anti-patterns / what NOT to do

- **Don't** keep `_summarize_dragon_tiger()` as dead code. It's no
  longer referenced — delete it. (Per project memory [[respond-in-chinese]]
  + cleanup hygiene.)
- **Don't** introduce a parallel "limit_pools cache key" or its own
  TTL. market-stats already manages one composite cache key; adding
  another layer here would re-introduce the very regression
  `test_market_stats_cache_hit_skips_upstream` exists to pin (per
  CLAUDE.md "No composite cache" anti-pattern).
- **Don't** emit `limit_pools: {zt: null, dt: null}` for pre-market
  the same way as upstream failure. Pre-market pools are
  **not applicable**; the field should be absent from the wire (via
  `exclude_none`), keeping `summary.requested==2` (only stocks +
  boards attempted). Mixing them in `errors[]` would mislead
  consumers into "pool upstream is down".
- **Don't** leave `MarketContextDragonTiger*` schemas around "just in
  case". They're not referenced anywhere else after the change.
  Cleanup is the documented anti-pattern antidote (per
  [[skill-docs-contract-not-mechanism]] — keep the surface tight).
- **Don't** `manager.get_zt_pool(pool_type="zt")` and
  `manager.get_zt_pool(pool_type="dt")` sequentially with the same
  `target_date` unless you're certain the upstream batches them. The
  current akshare / zzshare chains do not; two sequential calls is
  the documented behavior, not a regression.
- **Don't** call `manager.get_zt_pool` with `pool_type="zt"` from a
  stale `target_date`. Resolve trade_date via
  `trade_calendar.get_latest_trade_date_on_or_before(today)` first;
  an empty string / `None` would silently skip akshare's date filter
  and return today's data even on a non-trade day.
- **Don't** skip writing the response to the cache on success even
  when `is_cache_enabled()` is True. (Per CLAUDE.md "Don't skip
  writing the response to the cache on success" — same rule as
  every other agent endpoint.)

---

## 7. Out of scope (future)

- Configurable bucket / clip params for the pools block (no
  aggregation — pools are emitted as raw lists; bucketing is a
  separate spec if needed).
- Multi-source pools (currently only Zzshare + Akshare chain via
  `manager.get_zt_pool`; exposing `?source=` is a separate change).
- HK / US pools (A-share only at v1; mirroring the existing
  `market-stats` scope).
- Removing `cache.get_dragontiger_cache` from the autouse
  `reset_before_test` fixture in `test_agent_endpoints.py` — that
  cache is still used by `/api/v1/dragon-tiger`, just not by the
  agent endpoint anymore. Leave it in the fixture.
