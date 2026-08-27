# Dragon-Tiger empty-fall-through contract

Read this when touching `/api/v1/dragon-tiger` or `/stocks/{code}/dragon-tiger`,
or when changing `DataFetcherManager._with_failover`'s emptiness handling.
Extracted from CLAUDE.md 2026-08-27; the resident spec keeps a one-line
pointer. Contract tests: `tests/test_dragon_tiger_zzshare_short_circuit.py`
(6 cases: empty fall-through, populated short-circuit, both-empty raises,
exception cascade, per-stock variant).

Both `/api/v1/dragon-tiger` (全市场) and `/stocks/{code}/dragon-tiger` (个股) opt into `empty_is_failure=True` on their `DataFetcherManager._with_failover` call. The contract:

- A non-empty result from Zzshare (P2 primary) → short-circuit with `source="zzshare"`.
- A *structurally empty* result from Zzshare (i.e. ``{"stocks": []}`` for daily, ``{"records": [], "seats": {"buy": [], "sell": []}, "institution": {}}`` for per-stock) → treat as soft failure, fall through to EastMoney (P6).
- If EastMoney also returns structurally empty, raise `DataFetchError` (caller sees an explicit failure rather than a misleading "all candidates returned empty" 200).

**Why**: Zzshare's `lhb_list` / `lhb_detail` return the official CSRC 龙虎榜 list. An empty result is "this day had no events for the requested scope" — but EastMoney has different coverage and field shape (it ships `close` / `buy_wan` / `sell_wan` that Zzshare omits), so when Zzshare says "empty", EastMoney often has the real data the caller wants. Falling through preserves coverage.

**Opt-in mechanism**: `DataFetcherManager._with_failover(empty_is_failure=True)`. Internally this routes through `_is_empty_dict()` (with recursive `_is_empty_collection()`), which classifies a dict as empty when:
- it has at least one list/dict value, AND
- all list/dict values are recursively empty (no inner non-empty list/dict survives)

A dict of only scalars (e.g. `{"date": "X", "url": "Y"}`) is **not** classified as empty (no collection to evaluate). The flag is currently enabled only for `get_dragon_tiger` + `get_daily_dragon_tiger`; other endpoints use the default "non-None dict is meaningful" behavior.
