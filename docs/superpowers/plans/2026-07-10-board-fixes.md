# Board Endpoint Post-Review Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 4 issues from a sub-agent code review of commit `330e2aa`: (1) CB doc/code mismatch, (2) cid-resolution miss masquerading as 404, (3) mid-pagination 401 truncation not covered by tests, (4) OpenAPI / schema description drift.

**Architecture:** Two new error semantics (`cid_unresolved` reason propagation + 422 response) layered on the existing 3-tuple return; F1/F3/F4 are doc-only; F3 also adds a test that locks the current "sticky boundary" behavior. All changes are TDD where applicable.

**Tech Stack:** Python 3.10, FastAPI, SQLite (persistence), pytest, `unittest.mock`. No new third-party dependencies.

---

## File Structure

Files modified by this plan:

- `stock_data/data_provider/persistence/board.py` — F2: `fetch_board_stocks_with_zzshare_fallback` and `get_board_stocks` return 4-tuple `(stocks, origin, effective_source, reason)`. `reason="cid_unresolved"` when `_resolve_ths_cid_from_platecode` returns `None`.
- `stock_data/api/routes/boards.py` — F2: route unpacks 4-tuple and raises 422 `cid_unresolved` for empty + reason. F4: rewrite `Query(description=...)` and `@endpoint_meta(summary=...)`.
- `stock_data/api/schemas.py` — F4: extend `BoardStocksResponse.effective_source` Field description with the "cache hit reports 'ths'" caveat.
- `CLAUDE.md` — F1: delete the "Circuit breaker interaction with THS beyond-data 401s" section.
- `stock_data/data_provider/fetchers/ths_fetcher.py` — F1: docstring edit ("circuit breaker can trip" → "the route returns 5xx"). F3: add a "Sticky boundary" paragraph to the `get_board_stocks` docstring.
- `tests/test_persistence_board_merge.py` — F2: 4 unpack sites become 4-tuple; 1 new test `test_cid_unresolved_returns_reason`.
- `tests/test_persistence_origin.py` — F2: 1 unpack site becomes 4-tuple.
- `tests/test_board_stocks_forward_route.py` — F2: 2 unpack sites become 4-tuple.
- `tests/test_boards.py` — F2: 5 mock return-tuple sites become 4-tuple.
- `tests/test_boards_api.py` — F2: 7 mock return-tuple sites become 4-tuple; 1 new test `test_cid_unresolved_returns_422`.
- `tests/test_ths_fetcher.py` — F3: 1 new test `test_mid_pagination_401_truncates_without_retry`.

---

## Task 1: Update `persistence/board.py` to return 4-tuple with `reason`

**Files:**
- Modify: `stock_data/data_provider/persistence/board.py:745-975` (two helpers)

- [ ] **Step 1: Update `fetch_board_stocks_with_zzshare_fallback` signature to 4-tuple**

In `stock_data/data_provider/persistence/board.py`, change the function signature and docstring to add a 4th return value `reason`.

Replace the signature line (currently):
```python
) -> tuple[list[dict], str, str]:
```

With:
```python
) -> tuple[list[dict], str, str, str | None]:
```

Replace the docstring's "Returns" block (currently describes a 3-tuple) with:
```
    Returns:
        ``(stocks, source_label, effective_source, reason)`` — 4-tuple:
          - ``stocks``: list of stock dicts (potentially empty).
          - ``source_label``: fetcher name matching the user's
            ``?source=`` (the *requested* source). For all branches
            except the THS+include_quote=False fallback path, this
            equals ``effective_source``.
          - ``effective_source``: the fetcher name that *actually
            served* the response (per P4: ALWAYS populated). When it
            differs from ``source_label``, the route response carries
            an actionable ``effective_source`` field so the client can
            tell the response came from a fallback fetcher.
          - ``reason``: optional annotation for the empty-result case.
            Currently only one value: ``"cid_unresolved"`` — when
            ``_resolve_ths_cid_from_platecode`` returned ``None`` and
            the helper could not perform any fetch. ``None`` for all
            other branches. The route layer maps ``reason="cid_unresolved"``
            to a 422 response (see ``api/routes/boards.py``).
```

- [ ] **Step 2: Update the `source == "ths"` + `include_quote=True` branch**

In the same function, find the early-return for `cid` being `None`:
```python
            if not cid:
                return [], "ths", "ths"
```

Replace with:
```python
            if not cid:
                return [], "ths", "ths", "cid_unresolved"
```

- [ ] **Step 3: Update the THS-fallback branch in `source == "ths"` + `include_quote=False`**

Find the early-return in the THS-fallback block (currently the last return-statement inside the `source == "ths"` branch):
```python
        if not cid:
            return [], "ths", "ths"   # cid unresolved → empty; no fetch happened
```

Replace with:
```python
        if not cid:
            return [], "ths", "ths", "cid_unresolved"   # cid unresolved → empty; no fetch happened
```

- [ ] **Step 4: Update the `source == "zzshare"` branch**

Find the return at the end of the `source == "zzshare"` branch:
```python
        return rows, "zzshare", "zzshare"
```

Replace with:
```python
        return rows, "zzshare", "zzshare", None
```

- [ ] **Step 5: Update the `source in ("eastmoney", "zhitu")` branch**

Find the return at the end of that branch:
```python
        return rows, source, source
```

Replace with:
```python
        return rows, source, source, None
```

- [ ] **Step 6: Update `get_board_stocks` signature to 4-tuple**

In the same file, find `get_board_stocks`'s signature:
```python
) -> tuple[list, str, str]:
```

Replace with:
```python
) -> tuple[list, str, str, str | None]:
```

- [ ] **Step 7: Update `get_board_stocks` cache-hit return**

Find the cache-hit return:
```python
            return cached, "persistence", "ths"
```

Replace with:
```python
            return cached, "persistence", "ths", None
```

- [ ] **Step 8: Update `get_board_stocks` unpacking + return**

Find the unpacking of `fetch_board_stocks_with_zzshare_fallback` and the final return:
```python
    stocks, origin, effective_source = fetch_board_stocks_with_zzshare_fallback(
        board_code=board_code,
        source=source,
        include_quote=include_quote,
        manager=manager,
    )

    if stocks:
        update_cached_board_stocks(board_code, "ths", stocks)
        logger.info(
            f"[BoardCache] Refreshed {len(stocks)} stocks for board "
            f"{board_code}/ths (origin={origin}, effective_source={effective_source})"
        )

    return stocks, origin, effective_source
```

Replace with:
```python
    stocks, origin, effective_source, reason = fetch_board_stocks_with_zzshare_fallback(
        board_code=board_code,
        source=source,
        include_quote=include_quote,
        manager=manager,
    )

    if stocks:
        update_cached_board_stocks(board_code, "ths", stocks)
        logger.info(
            f"[BoardCache] Refreshed {len(stocks)} stocks for board "
            f"{board_code}/ths (origin={origin}, effective_source={effective_source})"
        )

    return stocks, origin, effective_source, reason
```

Also update the "Returns" block in the `get_board_stocks` docstring to mention the 4-tuple and `reason` field.

- [ ] **Step 9: Run a quick smoke test**

Run:
```bash
.venv/Scripts/python.exe -c "from stock_data.data_provider.persistence import board; import inspect; print(inspect.signature(board.get_board_stocks)); print(inspect.signature(board.fetch_board_stocks_with_zzshare_fallback))"
```

Expected output:
```
(board_code: str, source: str = 'ths', refresh: bool = False, include_quote: bool = False, manager=None) -> tuple[list, str, str, str | None]
(board_code: str, source: str, include_quote: bool, manager) -> tuple[list[dict], str, str, str | None]
```

- [ ] **Step 10: Commit**

```bash
git add stock_data/data_provider/persistence/board.py
git commit -m "refactor(persistence): 4-tuple return for board-stocks helpers (stocks, origin, effective_source, reason)"
```

---

## Task 2: Add a unit test asserting the 4-tuple shape

**Files:**
- Test: `tests/test_persistence_board_merge.py` (add to `TestFetchBoardStocksWithZzshareFallback` class)

- [ ] **Step 1: Add `test_cid_unresolved_returns_reason` to the existing test class**

In `tests/test_persistence_board_merge.py`, find the end of `TestFetchBoardStocksWithZzshareFallback` (just before the next class or the end of the file). Append this test (it must live in the same class — keep the indentation aligned with the existing tests):

```python
    def test_cid_unresolved_returns_reason(self, mock_cid_resolver):
        """source='ths' + cid=None → returns 4-tuple with reason='cid_unresolved'.

        Regression test for F2 (2026-07-10). When the cid-index cache
        misses for a board_code, the helper cannot perform any fetch
        and surfaces ``reason='cid_unresolved'`` so the route layer
        can map it to HTTP 422 (instead of masquerading as a 404
        "Board not found" for a board that genuinely exists upstream).
        """
        from stock_data.data_provider.persistence import board as board_mod

        # No mock manager needed — cid=None short-circuits before any fetcher call.
        with mock_cid_resolver({('885642',): None}):
            stocks, origin, effective_source, reason = board_mod.fetch_board_stocks_with_zzshare_fallback(
                board_code='885642', source='ths',
                include_quote=True, manager=None,
            )
        assert stocks == []
        assert origin == 'ths'
        assert effective_source == 'ths'
        assert reason == 'cid_unresolved'

        # And the include_quote=False THS-fallback branch — same behavior.
        with mock_cid_resolver({('885642',): None}):
            stocks, origin, effective_source, reason = board_mod.fetch_board_stocks_with_zzshare_fallback(
                board_code='885642', source='ths',
                include_quote=False, manager=None,
            )
        assert reason == 'cid_unresolved'
```

- [ ] **Step 2: Run the new test**

Run:
```bash
.venv/Scripts/python.exe -m pytest tests/test_persistence_board_merge.py::TestFetchBoardStocksWithZzshareFallback::test_cid_unresolved_returns_reason -v
```

Expected: PASS (the helper already returns 4-tuple after Task 1; this test pins the contract).

- [ ] **Step 3: Commit**

```bash
git add tests/test_persistence_board_merge.py
git commit -m "test(persistence): cid_unresolved reason on cid-index miss (F2)"
```

---

## Task 3: Update existing persistence tests for 4-tuple

**Files:**
- Modify: `tests/test_persistence_board_merge.py` (4 sites)
- Modify: `tests/test_persistence_origin.py` (1 site)
- Modify: `tests/test_board_stocks_forward_route.py` (2 sites)
- Modify: `tests/test_boards.py` (5 sites)
- Modify: `tests/test_boards_api.py` (7 sites)

- [ ] **Step 1: Update `tests/test_persistence_board_merge.py` — 4 unpack sites**

There are 4 unpack sites in `TestFetchBoardStocksWithZzshareFallback`. Each currently does:
```python
        stocks, origin, _effective_source = board_mod.fetch_board_stocks_with_zzshare_fallback(...)
```

Change each to:
```python
        stocks, origin, _effective_source, _reason = board_mod.fetch_board_stocks_with_zzshare_fallback(...)
```

The 4 sites are inside:
- `test_source_ths_routes_to_ths_only` (line ~276)
- `test_source_zzshare_routes_to_zzshare_with_platecode` (line ~293)
- `test_zzshare_empty_triggers_ths_fallback` (line ~318)
- `test_cid_unresolved_returns_reason` — already updated in Task 2, no change needed.

The 4th existing test (`test_source_ths_raises_propagates_no_fallback`) does NOT unpack the helper return (it asserts via `pytest.raises`), so no change there.

- [ ] **Step 2: Update `tests/test_persistence_origin.py` — 1 site**

Find:
```python
    stocks, origin, effective_source = board.get_board_stocks(
        "BK0001", refresh=True, manager=_MockManager()
    )
```

Replace with:
```python
    stocks, origin, effective_source, reason = board.get_board_stocks(
        "BK0001", refresh=True, manager=_MockManager()
    )
```

Also add `assert reason is None` to the assertions, to lock the contract that the mock manager's success path returns `reason=None`.

- [ ] **Step 3: Update `tests/test_board_stocks_forward_route.py` — 2 sites**

Site 1 (`test_get_board_stocks_reads_from_membership_table`):
```python
    stocks, origin, effective_source = board_mod.get_board_stocks(
        board_code="BK1001",
        manager=mock_manager,
    )
```
Becomes:
```python
    stocks, origin, effective_source, reason = board_mod.get_board_stocks(
        board_code="BK1001",
        manager=mock_manager,
    )
```
And add `assert reason is None` after the existing `assert effective_source == "ths"` line.

Site 2 (`test_get_board_stocks_lazy_fill_when_membership_empty`):
```python
    stocks, origin, effective_source = board_mod.get_board_stocks(
        board_code="885642",     # platecode
        source="ths",
        manager=mock_manager,
    )
```
Becomes:
```python
    stocks, origin, effective_source, reason = board_mod.get_board_stocks(
        board_code="885642",     # platecode
        source="ths",
        manager=mock_manager,
    )
```
And add `assert reason is None` after the existing assertions.

- [ ] **Step 4: Update `tests/test_boards.py` — 5 sites**

The 5 sites in this file use mock returns to drive the route. Each `return_value=...` for the persistence helper must become 4-tuple, and any assertion that unpacks the helper's return becomes 4-tuple.

Site 1 (`test_get_board_stocks`, line ~196):
```python
            mock_mgr.get_board_stocks.return_value = (
                [...],
                "ThsFetcher",
            )
```
(But this is the **manager** mock — `DataFetcherManager.get_board_stocks` still returns a 2-tuple per its public API, not the persistence 4-tuple. **DO NOT change**. The manager API and the persistence API are distinct.)

This is a critical distinction: the **manager-level** mock `mock_mgr.get_board_stocks` returns whatever shape the manager's API dictates (2-tuple `(rows, source_label)`). Only **persistence-level** mocks or unpacks return 4-tuple.

After re-checking, no changes are needed in `test_boards.py` for F2. The 5 sites listed in the spec were based on the assumption that this file mocks the persistence helper, but it actually mocks the manager (different layer, different return shape). The actual changes are limited to sites that mock or unpack the persistence helper directly: `test_persistence_board_merge.py`, `test_persistence_origin.py`, `test_board_stocks_forward_route.py`, and `test_boards_api.py`.

Verify by running `grep -n "board_mod.get_board_stocks\|persistence.board.get_board_stocks" tests/test_boards.py` — expect 0 hits (this file uses `manager.get_board_stocks`, not the persistence helper).

Skip this step.

- [ ] **Step 5: Update `tests/test_boards_api.py` — 7 mock sites**

These all patch `stock_data.data_provider.persistence.board.get_board_stocks` and pass `return_value=(...)`. Each must become 4-tuple.

Site 1 (`test_get_board_stocks_returns_404_on_empty`, line ~398):
```python
        return_value=([], "eastmoney", "eastmoney"),
```
Becomes:
```python
        return_value=([], "eastmoney", "eastmoney", None),
```

Site 2 (`test_get_board_stocks_cache_hit_returns_persistence`, line ~421):
```python
        mock_get.return_value = (fake, "eastmoney", "eastmoney")
```
Becomes:
```python
        mock_get.return_value = (fake, "eastmoney", "eastmoney", None)
```

Site 3 (`test_get_board_stocks_cache_hit_returns_persistence` second call, line ~428):
```python
        mock_get.return_value = (fake, "persistence", "eastmoney")
```
Becomes:
```python
        mock_get.return_value = (fake, "persistence", "eastmoney", None)
```

Site 4 (`test_get_board_stocks_refresh_forces_persistence_refresh`, line ~446):
```python
            return_value=(fake, "eastmoney", "eastmoney"),
```
Becomes:
```python
            return_value=(fake, "eastmoney", "eastmoney", None),
```

Site 5 (`test_get_board_stocks_source_ths_passes_ths_to_persistence`, line ~478):
```python
                      return_value=([], "ths", "ths")) as mock_fetch:
```
Becomes:
```python
                      return_value=([], "ths", "ths", None)) as mock_fetch:
```

Site 6 (`test_get_board_stocks_projects_amount_from_fetcher_output`, line ~528):
```python
            return_value=(fake, "ths", "ths"),
```
Becomes:
```python
            return_value=(fake, "ths", "ths", None),
```

Site 7 (`test_get_board_stocks_projects_change_amount_and_turnover_rate`, line ~568):
```python
            return_value=(fake, "ths", "ths"),
```
Becomes:
```python
            return_value=(fake, "ths", "ths", None),
```

Site 8 (`test_get_board_stocks_projects_change_amount_and_turnover_rate_null_when_absent`, line ~603):
```python
            return_value=(fake, "zzshare", "zzshare"),
```
Becomes:
```python
            return_value=(fake, "zzshare", "zzshare", None),
```

Site 9 (`test_get_board_stocks_ths_falls_back_when_get_all_boards_unavailable`, line ~635):
```python
            return_value=(fake, "ths", "ths"),
```
Becomes:
```python
            return_value=(fake, "ths", "ths", None),
```

- [ ] **Step 6: Run all updated tests to verify they pass**

Run:
```bash
.venv/Scripts/python.exe -m pytest tests/test_persistence_board_merge.py tests/test_persistence_origin.py tests/test_board_stocks_forward_route.py tests/test_boards_api.py -v
```

Expected: All pass. (If any fail, the most common cause is a missed unpack site — re-grep for `stocks, origin, effective_source = ` and fix any that survived.)

- [ ] **Step 7: Commit**

```bash
git add tests/test_persistence_board_merge.py tests/test_persistence_origin.py tests/test_board_stocks_forward_route.py tests/test_boards_api.py
git commit -m "test: unpack 4-tuple return from board-stocks persistence helpers (F2)"
```

---

## Task 4: Update `api/routes/boards.py` to map `cid_unresolved` to HTTP 422

**Files:**
- Modify: `stock_data/api/routes/boards.py:445-471`

- [ ] **Step 1: Update the unpacking in the route handler**

Find:
```python
        stocks, origin, effective_source = stock_board_cache.get_board_stocks(
            board_code,
            source=source,
            refresh=refresh,
            include_quote=include_quote,
            manager=manager,
        )
```

Replace with:
```python
        stocks, origin, effective_source, reason = stock_board_cache.get_board_stocks(
            board_code,
            source=source,
            refresh=refresh,
            include_quote=include_quote,
            manager=manager,
        )
```

- [ ] **Step 2: Update the empty-stocks branch to honor `reason`**

Find:
```python
    if not stocks:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "message": f"No stocks found for board {board_code}"},
        )
```

Replace with:
```python
    if not stocks:
        # F2 (2026-07-10): when the persistence helper reports
        # reason="cid_unresolved", the THS cid-index cache missed for
        # this board_code. The board may genuinely exist upstream;
        # a force-refresh can warm the index. Return 422 (not 404) so
        # clients can distinguish "board doesn't exist" from
        # "configuration missing" — the latter is fixable by an
        # operator, the former is a hard 404.
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
            detail={"error": "not_found", "message": f"No stocks found for board {board_code}"},
        )
```

- [ ] **Step 3: Run the existing 404 test to verify nothing regressed**

Run:
```bash
.venv/Scripts/python.exe -m pytest tests/test_boards_api.py::test_get_board_stocks_returns_404_on_empty -v
```

Expected: PASS. The 404 test mocks the persistence helper with `( [], "eastmoney", "eastmoney", None )` after Task 3; the `reason is None` branch fires, returning 404.

- [ ] **Step 4: Commit**

```bash
git add stock_data/api/routes/boards.py
git commit -m "feat(boards): 422 cid_unresolved for cid-index cache miss (F2)"
```

---

## Task 5: Add the 422 cid_unresolved route test

**Files:**
- Test: `tests/test_boards_api.py` (append a new test)

- [ ] **Step 1: Add `test_cid_unresolved_returns_422` after `test_get_board_stocks_returns_404_on_empty`**

In `tests/test_boards_api.py`, find the test `test_get_board_stocks_returns_404_on_empty` (line ~394). Insert the following test immediately after it (before the next blank-line-separated test):

```python
def test_cid_unresolved_returns_422(client):
    """cid-index miss → HTTP 422 with error='cid_unresolved'.

    Regression test for F2 (2026-07-10). The persistence helper now
    reports ``reason='cid_unresolved'`` when the THS cid-index cache
    misses for the board_code; the route layer maps this to 422 so
    operators can distinguish "board doesn't exist" (404) from
    "cid-index needs warming" (422).
    """
    with patch(
        "stock_data.data_provider.persistence.board.get_board_stocks",
        return_value=([], "ths", "ths", "cid_unresolved"),
    ):
        r = client.get("/api/v1/boards/885642/stocks?source=ths&include_quote=true")
    assert r.status_code == 422
    body = r.json()
    assert body["detail"]["error"] == "cid_unresolved"
    assert "885642" in body["detail"]["message"]
    assert "?refresh=true" in body["detail"]["message"]
```

- [ ] **Step 2: Run the new test**

Run:
```bash
.venv/Scripts/python.exe -m pytest tests/test_boards_api.py::test_cid_unresolved_returns_422 -v
```

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_boards_api.py
git commit -m "test(boards): 422 cid_unresolved route mapping (F2)"
```

---

## Task 6: F4 — Rewrite `Query(description=...)` and `@endpoint_meta(summary=...)` for `/boards/{code}/stocks`

**Files:**
- Modify: `stock_data/api/routes/boards.py:408-413` (summary) and `:417-424` (description)

- [ ] **Step 1: Update the `@endpoint_meta` summary**

Find:
```python
@endpoint_meta(
    summary="板块成分股 (ths/eastmoney/zhitu; ?source=zzshare 已下线; 严格按用户选择的 source 路由, 无跨源 fallback)",
    markets=["csi"],
    capabilities=["STOCK_BOARD"],
    fetcher_method="get_board_stocks",
)
```

Replace the `summary=...` line with:
```python
    summary="板块成分股 (ths/eastmoney/zhitu; ?source=zzshare 已下线; source=ths&include_quote=false 内部可能走 ZZSHARE primary + THS fallback, 通过 effective_source 字段暴露实际服务 fetcher)",
```

- [ ] **Step 2: Update the `Query(description=...)` for the `source` parameter**

Find:
```python
    source: Literal["ths", "eastmoney", "zhitu"] = Query(
        ...,
        description=(
            "Data source (REQUIRED). 'zzshare' was unified under 'ths' "
            "on 2026-07-08. Strictly source-routed: the chosen fetcher "
            "is the only one invoked; failures propagate (no silent "
            "fallback to a sibling source)."
        ),
    ),
```

Replace the entire `description=(...)` argument with:
```python
        description=(
            "Data source (REQUIRED). 'zzshare' was unified under 'ths' "
            "on 2026-07-08. Source-routing with one cross-source "
            "fallback: for `source='ths'&include_quote=False` the server "
            "may invoke ZZSHARE first and fall back to THS on empty / "
            "upstream error. The actual fetcher that served the request "
            "is exposed via `BoardStocksResponse.effective_source` — "
            "compare against this `query_source` to detect fallback. "
            "For `source='eastmoney'|'zhitu'` or when `include_quote=True`, "
            "the chosen fetcher is the only one invoked and failures "
            "propagate as 5xx."
        ),
```

- [ ] **Step 3: Verify the OpenAPI schema**

Run a one-liner to verify the manifest still builds:

```bash
.venv/Scripts/python.exe -c "from stock_data.server import app; from stock_data.explorer.manifest import build_manifest; m = build_manifest(app); routes = [r for r in m['sections'][0]['endpoints'] if 'stocks' in r.get('path','') and 'boards' in r.get('path','')]; print('ok' if routes else 'missing')"
```

Expected: `ok`.

(If this is too fragile — depends on `app.sections` ordering — the alternate check is `python -c "from stock_data.server import app; print('app boots')"`.)

- [ ] **Step 4: Commit**

```bash
git add stock_data/api/routes/boards.py
git commit -m "docs(boards): clarify source=ths&include_quote=false fallback chain in OpenAPI"
```

---

## Task 7: F4 — Extend `BoardStocksResponse.effective_source` schema description

**Files:**
- Modify: `stock_data/api/schemas.py:374-382`

- [ ] **Step 1: Append the cache-hit caveat to the Field description**

Find:
```python
    effective_source: str | None = Field(
        default=None,
        description=(
            "实际服务本响应的 fetcher 名称 (ths / zzshare / eastmoney / zhitu). "
            "路由层总是填充——None 只在直构造 Pydantic 模型 (如 schema 测试) 不传参时出现. "
            "区别于 query_source 即可判 fallback: "
            "query_source='ths' 且 effective_source='zzshare' 表示走 ZZSHARE fallback."
        ),
    )
```

Replace the inner `description=(...)` text with:
```python
        description=(
            "实际服务本响应的 fetcher 名称 (ths / zzshare / eastmoney / zhitu). "
            "路由层总是填充——None 只在直构造 Pydantic 模型 (如 schema 测试) 不传参时出现. "
            "区别于 query_source 即可判 fallback: "
            "query_source='ths' 且 effective_source='zzshare' 表示走 ZZSHARE fallback. "
            "缓存命中时该字段固定为 'ths' (因为 stock_board_membership 表不存 per-row origin 列); "
            "需要暴露真实 upstream 时传 ?refresh=true."
        ),
```

- [ ] **Step 2: Run the schema smoke test**

```bash
.venv/Scripts/python.exe -c "from stock_data.api.schemas import BoardStocksResponse; print(BoardStocksResponse.model_fields['effective_source'].description)"
```

Expected output ends with:
```
传 ?refresh=true.
```

- [ ] **Step 3: Commit**

```bash
git add stock_data/api/schemas.py
git commit -m "docs(schemas): cache-hit caveat on BoardStocksResponse.effective_source"
```

---

## Task 8: F1 — Delete the CB paragraph from `CLAUDE.md` and update `ths_fetcher.py` docstring

**Files:**
- Modify: `CLAUDE.md` (delete one section)
- Modify: `stock_data/data_provider/fetchers/ths_fetcher.py:867-871` (docstring)

- [ ] **Step 1: Find the CB section in `CLAUDE.md`**

Search `CLAUDE.md` for the heading `### Circuit breaker interaction with THS beyond-data 401s` (introduced by commit `330e2aa`). The section sits between the previous section and the `## Indicator Computation` section.

- [ ] **Step 2: Delete the entire section**

Delete the section including its heading and the prose block underneath. Do NOT touch the surrounding sections.

- [ ] **Step 3: Insert a one-paragraph replacement note in the right location**

Immediately after the "Board Cache Source-Normalization" section's `### effective_source` subsection and before whatever section used to follow the deleted CB section, insert a short subsection:

```markdown
### Board endpoint failure observability

Board endpoints route through `DataFetcherManager._with_source`, which
does **not** integrate with the per-source `CircuitBreaker`. THS
outages on a board path therefore do **not** show up as CB state
changes — they surface as 5xx error rate. If you need CB-protected
failover, use a non-board endpoint (K-line, realtime quote) that
routes through `_with_failover` instead. (Documented 2026-07-10; the
previously-stated claim that "real THS board failures can trip the
circuit breaker" was incorrect — board methods have never been
CB-integrated.)
```

- [ ] **Step 4: Update the `ThsFetcher.get_board_stocks` docstring**

Find (within the docstring of `get_board_stocks` in `ths_fetcher.py`, around lines 856-871):

```python
        # Scope per P1 (2026-07-10): ONLY 401/403 are tolerated as
        # boundary signals (raised as ``ThsBoundarySignalError``, a
        # ``DataFetchError`` subclass). 5xx (real upstream failure) and
        # network errors still propagate so the route returns 5xx, the
        # circuit breaker can trip, and ops dashboards see the upstream
        # breakage — silent partial data on real failure is worse than
        # a 5xx.
```

Replace the final phrase "the circuit breaker can trip, and ops dashboards see the upstream breakage" with "ops dashboards see the upstream breakage as 5xx rate". The resulting lines should read:

```python
        # Scope per P1 (2026-07-10): ONLY 401/403 are tolerated as
        # boundary signals (raised as ``ThsBoundarySignalError``, a
        # ``DataFetchError`` subclass). 5xx (real upstream failure) and
        # network errors still propagate so the route returns 5xx and
        # ops dashboards see the upstream breakage as 5xx rate — silent
        # partial data on real failure is worse than a 5xx.
```

- [ ] **Step 5: Verify the file no longer mentions CB in misleading places**

Run:
```bash
grep -n "circuit breaker can trip" CLAUDE.md stock_data/data_provider/fetchers/ths_fetcher.py
```

Expected: no output.

- [ ] **Step 6: Commit**

```bash
git add CLAUDE.md stock_data/data_provider/fetchers/ths_fetcher.py
git commit -m "docs(boards): correct CB claim — board endpoints do not integrate with CircuitBreaker"
```

---

## Task 9: F3 — Add the sticky-boundary docstring paragraph and the lock-in test

**Files:**
- Modify: `stock_data/data_provider/fetchers/ths_fetcher.py` (add paragraph to `get_board_stocks` docstring)
- Test: `tests/test_ths_fetcher.py` (add new test in `TestGetBoardStocks`)

- [ ] **Step 1: Add the sticky-boundary paragraph to the docstring**

In `stock_data/data_provider/fetchers/ths_fetcher.py`, find the `get_board_stocks` docstring's "Sticky boundary" block (which is the comment block at lines ~856-871, immediately above the `for page in range(...)` loop). The block currently ends with the sentence "...silent partial data on real failure is worse than a 5xx." Append a new paragraph after the existing block (still inside the docstring — keep the leading `#` and indentation aligned with the existing comment block):

```python
        # Sticky boundary (2026-07-10 trade-off): the first 401/403
        # after any data has been received ends the pagination loop
        # immediately, even if subsequent pages would have contained
        # more rows. This is the simplest way to interpret THS's
        # "no more data" signal, but it can silently truncate boards
        # whose upstream returns transient 401/403 mid-pagination.
        # The _MAX_BOARD_STOCKS_PAGES=50 cap is the only guard
        # against infinite loops on a buggy upstream; it does not
        # protect against partial data on a healthy upstream with
        # flaky 401s. If truncation becomes a recurring issue, the
        # proper fix is a retry-with-backoff loop, not to relax the
        # sticky-boundary rule. See
        # ``tests/test_ths_fetcher.py::TestGetBoardStocks::test_mid_pagination_401_truncates_without_retry``.
```

- [ ] **Step 2: Add `test_mid_pagination_401_truncates_without_retry` to `TestGetBoardStocks`**

In `tests/test_ths_fetcher.py`, find the end of `TestGetBoardStocks` (just before the helper `test_ths_boundary_signal_error_is_subclass_of_data_fetch_error` which is also in the class). Append:

```python
    def test_mid_pagination_401_truncates_without_retry(self):
        """First 401/403 after data ends the loop, even if more pages exist.

        Locks the 'sticky boundary' trade-off documented in
        ``get_board_stocks``'s docstring. The 3-call sequence is
        page1=10 rows → page2=401 → page3=10 rows; the test asserts
        that the fetcher returns only page1's 10 rows and the
        pagination loop does NOT issue page3.

        Pairs with ``test_401_after_data_treated_as_end_of_pagination``
        which covers the *last-page* 401 case (page1=10 → page2=5 →
        page3=401). Together they pin the full behavior: any 401/403
        after data is the boundary, regardless of whether more data
        would have followed.
        """
        page1_html = self._build_html(
            [
                [
                    str(i + 1),
                    f"3007{40 + i:02d}",
                    f"股票{i}",
                    "10.00",
                    "1.00",
                    "0.10",
                    "0.05",
                    "0.80",
                    "1.00",
                    "1.50",
                    "100000000",
                    "500000000",
                    "5250000000",
                    "30.0",
                ]
                for i in range(10)
            ]
        )
        # page3 is constructed but the test asserts the loop never consumes it.
        page3_html = self._build_html(
            [
                [
                    str(i + 11),
                    f"3008{40 + i:02d}",
                    f"股票{i + 10}",
                    "10.00",
                    "1.00",
                    "0.10",
                    "0.05",
                    "0.80",
                    "1.00",
                    "1.50",
                    "100000000",
                    "500000000",
                    "5250000000",
                    "30.0",
                ]
                for i in range(10)
            ]
        )

        class _MidPaginationAuth:
            """THS returning 401 mid-pagination (NOT on the last page)."""
            status_code = 401
            encoding = "utf-8"
            text = "<html>Unauthorized</html>"
            content = b"<html>Unauthorized</html>"

        responses = [
            self._make_response(page1_html),
            _MidPaginationAuth(),
            self._make_response(page3_html),  # would-be-ignored
        ]

        with patch.object(ThsFetcher, "_http_get", side_effect=responses) as mock_get:
            result = self.fetcher.get_board_stocks("308709")

        # Only page1's 10 rows — page3 was never issued.
        assert len(result) == 10
        assert result[0]["stock_code"] == "300740"
        assert result[9]["stock_code"] == "300749"
        # Loop broke on page2; page3 was never issued.
        assert mock_get.call_count == 2
```

- [ ] **Step 3: Run the new test**

Run:
```bash
.venv/Scripts/python.exe -m pytest tests/test_ths_fetcher.py::TestGetBoardStocks::test_mid_pagination_401_truncates_without_retry -v
```

Expected: PASS.

- [ ] **Step 4: Run the rest of `TestGetBoardStocks` to ensure no regression**

Run:
```bash
.venv/Scripts/python.exe -m pytest tests/test_ths_fetcher.py::TestGetBoardStocks -v
```

Expected: All tests in `TestGetBoardStocks` pass, including the new one.

- [ ] **Step 5: Commit**

```bash
git add stock_data/data_provider/fetchers/ths_fetcher.py tests/test_ths_fetcher.py
git commit -m "test+docs(ths): lock sticky-boundary 401 behavior for mid-pagination"
```

---

## Task 10: Final regression run

**Files:** none (verification only)

- [ ] **Step 1: Run the full non-live suite**

```bash
.venv/Scripts/python.exe -m pytest -m "not live_network"
```

Expected: All pass. Test count should be 287 + 2 new = 289 (F2's `test_cid_unresolved_returns_reason` + F2's `test_cid_unresolved_returns_422` + F3's `test_mid_pagination_401_truncates_without_retry` = 290 total). Verify with:

```bash
.venv/Scripts/python.exe -m pytest -m "not live_network" --collect-only -q | tail -5
```

Expected: roughly `290 tests collected`.

- [ ] **Step 2: Verify the new test names are present**

```bash
.venv/Scripts/python.exe -m pytest -m "not live_network" -v 2>&1 | grep -E "(test_cid_unresolved_returns_reason|test_cid_unresolved_returns_422|test_mid_pagination_401_truncates_without_retry)"
```

Expected: 3 lines, one per test.

- [ ] **Step 3: Verify no live_network tests are accidentally enabled**

```bash
.venv/Scripts/python.exe -m pytest -m "not live_network" -v 2>&1 | grep -E "live_network" | head -5
```

Expected: no live_network tests in the output (they're filtered out by `-m "not live_network"`).

- [ ] **Step 4: Final commit if any leftover changes**

If you made any cleanup edits during the regression run, commit them:

```bash
git status
# If any files are modified:
git add -u
git commit -m "chore: post-regression cleanup"
```

Otherwise skip this step.

---

## Self-Review

1. **Spec coverage** — every item in `docs/superpowers/specs/2026-07-10-board-fixes-design.md` maps to a task:
   - F1 doc alignment → Task 8.
   - F2 4-tuple + 422 + tests → Tasks 1-5.
   - F3 sticky-boundary test + docstring → Task 9.
   - F4 OpenAPI / schema / summary → Tasks 6-7.
   - Final regression → Task 10.

2. **Placeholder scan** — every step has actual code or a concrete command. No "TBD", no "fill in later", no "similar to above". The only embedded code that references a fixture (`mock_cid_resolver`) is in the test classes that already use it; the implementation task that defines the helper does not need a separate definition because the test class is unchanged in scope.

3. **Type consistency** — every place that consumes the new 4-tuple unpacks the same way: `(stocks, origin, effective_source, reason)`. The new parameter on `fetch_board_stocks_with_zzshare_fallback` and `get_board_stocks` is consistently `str | None`. The new `reason="cid_unresolved"` literal appears in three places (helper, route, test) and matches in spelling.

4. **Risks called out**:
   - F2 4-tuple is a breaking internal change — Task 3 step 6 catches missed unpack sites via the test run.
   - F2 422 vs 404 contract change — Task 4 has a logger.warning that makes the new path observable; the new test in Task 5 documents the 422 response shape.
   - F3 sticky-boundary is a lock-in, not a fix — Task 9 step 4's regression run catches if the new test breaks (it should not).
   - F4 doc drift — Task 6 step 3 verifies the manifest still builds.
