# Board Endpoint Post-Review Fixes (2026-07-10)

> Fix 4 issues surfaced by a sub-agent code review of commit `330e2aa`
> ("fix(boards): tolerate THS beyond-data 401/403 + ZZSHARE primary fallback").
>
> Status: design — pending user approval. After approval this spec is the
> contract for the implementation plan and the implementation itself.

## Background

Commit `330e2aa` (2026-07-10) introduced the ZZSHARE-primary + THS-fallback
chain for `?source=ths&include_quote=false`, the `effective_source` field on
`BoardStocksResponse`, and a THS boundary-401 tolerance. A high-effort
recall-biased code review of that commit (run via the `code-review` skill
followed by a meta-review) produced 4 findings that need fixing:

1. **F1** — `CLAUDE.md` and the `ThsFetcher.get_board_stocks` docstring
   claim board-stock failures "can trip the circuit breaker", but
   `DataFetcherManager._with_source` (which board methods route through) has
   no `circuit_breaker` integration. The "previously counted toward THS CB
   failure budget" sentence in `CLAUDE.md` is false in the code's history.
2. **F2** — `fetch_board_stocks_with_zzshare_fallback` returns
   `([], "ths", "ths")` when `_resolve_ths_cid_from_platecode` misses; the
   route layer maps an empty result to **404 "Board not found"** for any
   platecode whose THS cid is not yet cached — including real boards whose
   cid-index has not been warmed. This is a misdiagnosis: the board exists
   upstream, but the server pretends otherwise.
3. **F3** — `ThsFetcher.get_board_stocks`'s pagination loop treats the
   **first 401/403 after page 1** as end-of-pagination regardless of whether
   subsequent pages would have data. The existing test
   `test_401_after_data_treated_as_end_of_pagination` only exercises the
   edge case where the 401 is on the *last* page, so the "mid-pagination
   401 truncates silently" case is not covered. The docstring acknowledges
   the loop is capped at `_MAX_BOARD_STOCKS_PAGES=50` but does not call out
   the sticky-boundary trade-off.
4. **F4** — The OpenAPI `Query(description=...)` on
   `/boards/{code}/stocks` still says "Strictly source-routed: the chosen
   fetcher is the only one invoked; failures propagate (no silent fallback
   to a sibling source)" — but the same commit made
   `source='ths'&include_quote=false` invoke ZZSHARE first. The
   `@endpoint_meta(summary=...)` repeats the same string. The
   `BoardStocksResponse.effective_source` schema description does not
   document the "cache hit always reports 'ths'" caveat.

User-confirmed design decisions (from brainstorming):

- **F1** — Doc-only fix: delete / rewrite the CB paragraph, do **not**
  rewire `_with_source` to the circuit breaker. (Reason: board methods
  intentionally lack CB integration; the doc should reflect that, not
  fight it.)
- **F2** — Return **HTTP 422 with `error: "cid_unresolved"`** and a
  logger.warning. Plumb the reason through a 4-tuple return
  `(stocks, origin, effective_source, reason)` from
  `fetch_board_stocks_with_zzshare_fallback` and `get_board_stocks`.
- **F3** — Code stays as-is. Add a test that **locks the current
  "boundary signal is sticky" behavior** and update the docstring to
  call out the trade-off explicitly. No retry/backoff logic.
- **F4** — Rewrite the OpenAPI description, the `@endpoint_meta` summary,
  and the `effective_source` schema description together so the three
  artifacts are aligned.

## Architecture

### F1 — Doc alignment

Two text-only edits:

- `CLAUDE.md` — remove the "Circuit breaker interaction with THS
  beyond-data 401s" section (lines ~412-427). Replace with a one-paragraph
  note that **board endpoints route through `_with_source` and never
  integrate with the circuit breaker**; THS outages are observable via
  5xx rate, not via CB state.
- `stock_data/data_provider/fetchers/ths_fetcher.py` — update the
  docstring of `get_board_stocks` (lines ~856-871) to remove the phrase
  "the circuit breaker can trip" and replace with "the route returns 5xx
  on real upstream failure".

No code change. No test change.

### F2 — `cid_unresolved` reason propagation

Change the return signature of two helpers from a 3-tuple
`(stocks, origin, effective_source)` to a **4-tuple
`(stocks, origin, effective_source, reason)`** where `reason` is one of:

- `None` — no annotation (default for "I don't have a reason to call out";
  the route layer will use the historical 404 behavior).
- `"cid_unresolved"` — `_resolve_ths_cid_from_platecode(board_code)` returned
  `None` and no fetch was attempted.

Plumbing:

1. `stock_data/data_provider/persistence/board.py`:
   - `fetch_board_stocks_with_zzshare_fallback(...)` returns 4-tuple.
     - For `source='ths'` + `include_quote=True` branch (line 811-812):
       when `cid` is `None`, return `([], "ths", "ths", "cid_unresolved")`.
     - For `source='ths'` + `include_quote=False` branch (line 851-852):
       when the THS-fallback `cid` is `None`, return
       `([], "ths", "ths", "cid_unresolved")`. The ZZSHARE primary leg is
       unchanged — when it succeeds, the route has data and the reason is
       irrelevant. (If ZZSHARE primary returns empty and cid resolution
       misses, the call has reached this branch, so reason applies.)
     - For `source='zzshare'`, `source='eastmoney'`, `source='zhitu'`
       branches: return `(rows, source, source, None)`. These fetchers
       don't need cid translation; nothing to flag.
   - `get_board_stocks(...)` (line 890) signature returns 4-tuple. The
     cache-hit path is unaffected (returns 3 fields + `None` reason). The
     cache-miss path forwards the reason from
     `fetch_board_stocks_with_zzshare_fallback`.
   - Update the docstring for both helpers.

2. `stock_data/api/routes/boards.py` (`get_board_stocks` handler,
   line 437-471):
   - Unpack 4-tuple: `stocks, origin, effective_source, reason = ...`.
   - Replace the unconditional 404 at line 467-471 with:
     ```python
     if not stocks:
         if reason == "cid_unresolved":
             logger.warning(
                 f"[boards] /boards/{board_code}/stocks: THS cid not in "
                 f"cache; source={source}; returning 422 cid_unresolved"
             )
             raise HTTPException(
                 status_code=422,
                 detail={
                     "error": "cid_unresolved",
                     "message": (
                         f"THS concept cid for platecode {board_code!r} "
                         f"is not in the local cid-index cache. Pass "
                         f"?refresh=true to force a cid resolution, or "
                         f"check that the board_code is a valid THS "
                         f"concept/industry platecode."
                     ),
                 },
             )
         raise HTTPException(
             status_code=404,
             detail={
                 "error": "not_found",
                 "message": f"No stocks found for board {board_code}",
             },
         )
     ```

3. Test updates — the 4-tuple is a breaking change to internal helpers.
   Update the following test files' `unpack` sites to match the new
   signature:
   - `tests/test_persistence_board_merge.py` — 4 sites in
     `TestFetchBoardStocksWithZzshareFallback`.
   - `tests/test_persistence_origin.py` — `test_get_board_stocks_returns_tuple`.
   - `tests/test_board_stocks_forward_route.py` — 2 sites
     (`test_get_board_stocks_reads_from_membership_table`,
     `test_get_board_stocks_lazy_fill_when_membership_empty`).
   - `tests/test_boards.py` — `test_boards_api_*` mocks that return
     `(fake, "ths", "ths")` for the persistence helper become
     `(fake, "ths", "ths", None)`. Plus the same for eastmoney/zzshare.
   - `tests/test_boards_api.py` — 5 sites (404 test, cache-hit test,
     refresh test, source-ths test, projects tests).

4. New test: `test_cid_unresolved_returns_422` in
   `tests/test_boards_api.py` — patch `get_board_stocks` to return
   `([], "ths", "ths", "cid_unresolved")`, call
   `/api/v1/boards/885642/stocks?source=ths&include_quote=true`, assert
   `status_code == 422` and `body["detail"]["error"] == "cid_unresolved"`.

5. Logger format: keep `[boards]` prefix consistent with the other
   logger.warning calls in `api/routes/boards.py` (line 550-552).

### F3 — Test + docstring for sticky boundary

Two changes:

1. `stock_data/data_provider/fetchers/ths_fetcher.py` — extend the
   docstring of `get_board_stocks` (lines ~856-871) with a new paragraph:

   > **Sticky boundary (2026-07-10 trade-off)**: the first 401/403 after
   > any data has been received ends the pagination loop immediately,
   > even if subsequent pages would have contained more rows. This is
   > the simplest way to interpret THS's "no more data" signal, but it
   > can silently truncate boards whose upstream returns transient
   > 401/403 mid-pagination. The `_MAX_BOARD_STOCKS_PAGES=50` cap is
   > the only guard against infinite loops on a buggy upstream; it does
   > not protect against partial data on a healthy upstream with flaky
   > 401s. If truncation becomes a recurring issue, the proper fix is
   > a retry-with-backoff loop, not to relax the sticky-boundary rule.

2. `tests/test_ths_fetcher.py` — new test in `TestGetBoardStocks`. The
   shape mirrors `test_401_after_data_treated_as_end_of_pagination`
   (which already constructs 10-row pages with the test class's
   `_build_html` / `_make_response` helpers). The new test constructs
   the same 10-row page1_html as the existing test but feeds a
   3-response sequence: `[page1=10 rows, page2=401, page3=10 rows]`
   and asserts:
   - `len(result) == 10` (only page1's rows).
   - `mock_get.call_count == 2` (page3 was never issued — the loop
     broke on the first beyond-data 401).

   The test docstring explicitly cites the "sticky boundary"
   trade-off and names `test_401_after_data_treated_as_end_of_pagination`
   as the existing test that covers the *last-page* 401 case, so the
   two tests together pin the full behavior.

### F4 — OpenAPI / schema doc alignment

Three text-only edits, all user-visible:

1. `stock_data/api/routes/boards.py` `Query(description=...)` on
   `source` (line 417-424) — replace the current text with:

   > Data source (REQUIRED). 'zzshare' was unified under 'ths' on
   > 2026-07-08. **Source-routing with one cross-source fallback**:
   > for `source='ths'&include_quote=False` the server may invoke
   > ZZSHARE first and fall back to THS on empty / upstream error
   > (see `BoardStocksResponse.effective_source` for the actually
   > served fetcher; compare against this query source to detect
   > fallback). For `source='eastmoney'|'zhitu'` or when
   > `include_quote=True`, the chosen fetcher is the only one invoked
   > and failures propagate as 5xx.

2. `stock_data/api/routes/boards.py` `@endpoint_meta(summary=...)` for
   the same route — change from the current summary to:

   > Get stocks belonging to a board (source-routed; with
   > `source=ths&include_quote=false` the server may transparently
   > try ZZSHARE first and fall back to THS).

3. `stock_data/api/schemas.py` `BoardStocksResponse.effective_source`
   Field description (line ~374-382) — append a sentence:

   > Always populated by the route layer; on cache hits this field
   > reports `"ths"` because the `stock_board_membership` table does
   > not store per-row origin (use `?refresh=true` to force a fresh
   > upstream fetch and expose the actual fetcher).

## Data Flow

### F1 — Doc-only

No data flow change. The change is purely textual in two documentation
locations.

### F2 — cid_unresolved

```
GET /api/v1/boards/885642/stocks?source=ths&include_quote=true
  ↓
api/routes/boards.py::get_board_stocks
  ↓
persistence/board.py::get_board_stocks
  ↓ (cache miss)
persistence/board.py::fetch_board_stocks_with_zzshare_fallback
  ↓
_resolve_ths_cid_from_platecode("885642")  →  None
  ↓
returns ([], "ths", "ths", "cid_unresolved")
  ↓
api/routes/boards.py sees reason="cid_unresolved" + empty rows
  ↓
raises HTTPException(422, detail={"error": "cid_unresolved", ...})
  ↓
logger.warning("[boards] /boards/885642/stocks: THS cid not in cache; ...")
```

The 4-tuple signature is internal to the `persistence` module. Public
API (`BoardStocksResponse`) does **not** grow a `reason` field; the
reason only matters for the 404/422 branching in the route layer. (If
a future need arises to expose `reason` in the response body, that
would be a separate change.)

### F3 — Test lock-in

```
ThsFetcher.get_board_stocks("308709")
  ↓ loop
page=1 → 200 + 10 rows → all_rows.extend
page=2 → 401 + ThsBoundarySignalError raised
  ↓
caught by the loop's `except ThsBoundarySignalError`:
  all_rows is non-empty (10 rows) → log + break
page=3 → never issued
  ↓
return all_rows (length 10)
```

The new test exercises this path with `_MAX_BOARD_STOCKS_PAGES=50`
intact; the test does **not** assert the cap, just the break-on-first-401
behavior.

### F4 — Doc alignment

No data flow change. All three text artifacts are surfaced through
the same code path they already document.

## Error Handling

### F2 — new error case

- **HTTP 422** `cid_unresolved`
  - Triggered when `_resolve_ths_cid_from_platecode` returns `None`
    AND no upstream fetch was attempted.
  - Body: `{"detail": {"error": "cid_unresolved", "message": "THS
    concept cid for platecode '885642' is not in the local cid-index
    cache. Pass ?refresh=true to force a cid resolution, or check
    that the board_code is a valid THS concept/industry platecode."}}`.
  - Logged at `logger.warning` level (one line).
  - Distinct from the existing 404 "not_found" (board truly has no
    stocks upstream) and the 422 "board_type_unresolved" (board_type
    cache miss for the realtime-quote sub-block). Three separate
    error codes, three different meanings:
    - `404 not_found` — board_code is valid but the upstream
      fetcher returned zero rows.
    - `422 cid_unresolved` — board_code's THS cid is not in the local
      cache; an upstream refresh would resolve it.
    - `422 board_type_unresolved` — board_type (concept / industry)
      is not in the local cache; only the realtime-quote sub-block
      is affected, the stocks list itself is fine.

### F1 / F3 / F4 — no error handling change.

## Testing

### F1 — no test change

Doc-only; existing tests still pass.

### F2 — affected test files

The 4-tuple return is a breaking change to internal helpers. Every test
that unpacks the 3-tuple return of
`fetch_board_stocks_with_zzshare_fallback` or `get_board_stocks` must be
updated to unpack 4-tuple. Affected:

- `tests/test_persistence_board_merge.py` — 4 unpack sites.
- `tests/test_persistence_origin.py` — 1 unpack site.
- `tests/test_board_stocks_forward_route.py` — 2 unpack sites.
- `tests/test_boards.py` — 5+ mock return-tuple sites.
- `tests/test_boards_api.py` — 5 mock return-tuple sites + 1 new test.

New test:

- `tests/test_boards_api.py::test_cid_unresolved_returns_422` — patch
  `persistence.board.get_board_stocks` to return
  `([], "ths", "ths", "cid_unresolved")`, hit the route, assert 422
  + body.

New test (also F2-related, in `tests/test_persistence_board_merge.py`):

- `TestFetchBoardStocksWithZzshareFallback::test_cid_unresolved_returns_reason`
  — assert the helper returns the 4-tuple with `reason="cid_unresolved"`
  in both `include_quote=True` and the THS-fallback branch.

### F3 — new test

- `tests/test_ths_fetcher.py::TestGetBoardStocks::test_mid_pagination_401_truncates_without_retry`
  — see the snippet in §F3 above. Locks the sticky-boundary behavior.

### F4 — no test change

Doc-only; the OpenAPI description and summary are surfaced by the
manifest, but a contract test for "the description mentions fallback"
would be over-engineering.

### Regression run

After all four fixes land, run:

```bash
.venv/Scripts/python.exe -m pytest -m "not live_network"
```

Expected: 287 → 290+ tests pass (existing 287 + 2 new tests + 1
cid_unresolved 422 test). Live-network tests still skipped by default.

## Risks

- **F2 4-tuple change is a breaking internal-API change.** The
  `fetch_board_stocks_with_zzshare_fallback` and `get_board_stocks`
  helpers change from 3-tuple to 4-tuple. Every test that unpacks
  the 3-tuple must be updated. A `grep` audit (`stocks, origin,
  effective_source = ...`) of the repo is required before
  merging.
- **F2 422 might break a client that expects 404 on "unknown board".**
  A client that walks the error code space by trying
  `/boards/{code}/stocks` and treating all 4xx the same way is fine.
  A client that branches on `404 → "board_code is wrong"` and
  `422 → "input validation problem"` may need to add a third branch.
  This is a contract change; call it out in the commit message.
- **F3 "sticky boundary" is documented but not fixed.** The new test
  locks in the current truncation behavior. If a future incident
  proves mid-pagination 401s are common, the fix is to add retry-with-
  backoff; do not relax the rule today.
- **F4 documentation drift.** If a future change reverts the ZZSHARE
  primary path, the OpenAPI description and summary will again
  drift. A future `tests/test_explorer_manifest_endpoint.py` could
  lock the summary string, but that's out of scope.

## Out of Scope

- Adding a `reason` field to `BoardStocksResponse` (public response
  model stays unchanged).
- Rewiring `_with_source` to integrate with the circuit breaker
  (user-confirmed as doc-only fix).
- Retry / backoff on mid-pagination 401s (user-confirmed as
  test-only fix).
- Logging the effective source for every `BoardStocksResponse` at
  `logger.info` level (already done by `get_board_stocks` line
  ~970-973 in `persistence/board.py`).
- Adding a `cid_index` warmup CLI tool (separate task; would be
  `tools/warmup_ths_cid_index.py` if pursued).
- Pinning the new 422 in `tests/test_explorer_manifest_endpoint.py`
  (the manifest rebuilds on every request, no caching).

## Checklist

Implementation order (independent within the same file, sequential
across files because tests depend on the new signature):

1. `persistence/board.py` — 4-tuple change in
   `fetch_board_stocks_with_zzshare_fallback` + `get_board_stocks`.
2. `api/routes/boards.py` — 4-tuple unpack + 422 branch in
   `get_board_stocks` handler.
3. `api/routes/boards.py` — F4 description + summary edits.
4. `api/schemas.py` — F4 schema description edit.
5. `CLAUDE.md` — F1 doc edit.
6. `ths_fetcher.py` — F1 docstring edit + F3 sticky-boundary
   paragraph.
7. `tests/test_persistence_board_merge.py` — 4-tuple updates + 1 new test.
8. `tests/test_persistence_origin.py` — 4-tuple update.
9. `tests/test_board_stocks_forward_route.py` — 4-tuple updates.
10. `tests/test_boards.py` — 4-tuple updates.
11. `tests/test_boards_api.py` — 4-tuple updates + 1 new test.
12. `tests/test_ths_fetcher.py` — F3 new test.
13. `pytest -m "not live_network"` — regression run.
14. `git add` + `git commit` per-file or as one combined commit.
