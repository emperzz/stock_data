# `/agent/stocks/batch-profile` — 5m Features=null Fix (per-frequency `adjust`)

**Date**: 2026-08-30
**Status**: Approved (awaiting plan)
**Scope**: localize `adjust` to per-frequency in `post_stocks_batch_profile` so minute frequencies stop dropping Zzshare P2 / Zhitu P5 from the manager's candidate list. One-line route change + one test split + one new regression pin + spec §3.4 sync. **No fetcher API change, no manager API change, no `DataCapability` flag change.**

---

## 1. Background

`POST /api/v1/agent/stocks/batch-profile` with `frequency="5m"` returns `features: null` in production for many environments. The user can directly call `ZzshareFetcher.get_kline_data(code, frequency="5", adjust="qfq")` and get data back, which makes the null result look like a backend regression — but it isn't. The actual failure is upstream of the fetcher call: Zzshare (and Zhitu) are filtered out by the manager's `supports_kline` check because the route hard-codes `adjust="qfq"` for all frequencies, and both fetchers explicitly reject `qfq` for minute K-lines. The remaining candidates (Akshare, Yfinance, Myquant) are all fallbacks, and any one of them being unavailable (`MYQUANT_TOKEN` missing, `akshare`/`yfinance` not in `.venv`, baostock's minute-no-qfq SDK rejection mid-call) collapses the whole failover chain.

This spec aligns the route with the existing design intent recorded in
`docs/superpowers/specs/2026-08-27-agent-batch-profile-features-design.md §3.4` —
*"qfq applied where the serving fetcher supports it; otherwise upstream returns unadjusted bars"* — which was correct on paper but never implemented at the route boundary.

---

## 2. Root cause

### 2.1 The hard-coded `adjust` in the route

`stock_data/api/routes/agent.py:914-921` (current):

```python
df, _src = manager.get_kline_data(
    code,
    days=fetch_days,
    frequency=profile.mgr_frequency,
    adjust="qfq",          # ← unconditional; minute 下把 Zzshare P2 / Zhitu P5 filter 掉
    asset="stock",
)
```

### 2.2 The `supports_kline` filter asymmetry

Per-fetcher `supports_kline(period=..., adjust="qfq", market="csi", asset="stock")` matrix:

| mgr_frequency | Tushare P0 | Baostock P1 | **Zzshare P2** | Akshare P3 | Yfinance P4 | **Zhitu P5** | Myquant P9 | Robust? |
|---|---|---|---|---|---|---|---|---|
| `d` | ✅ qfq | ✅ qfq | ✅ unconditional | ✅ | ✅ | ❌ minute-only | ✅ | ✅ (6/7 serve) |
| `w` | ✅ qfq | ✅ qfq | ❌ w/m returns False (line 187) | ✅ | ✅ | ❌ | ❌ d/minute-only | ✅ (Tushare+Baostock+Akshare+Yfinance) |
| `m` | ✅ qfq | ✅ qfq | ❌ | ✅ | ✅ | ❌ | ❌ | ✅ (same 4) |
| `5`/`15`/`30`/`60` | ❌ no minute | ⚠️ filter pass, runtime reject | **❌ `adjust in ("", None)`** | ✅ | ✅ | **❌ `adjust in ("", None)`** | ✅ (needs `MYQUANT_TOKEN`) | **❌ fragile** |

The two fetchers that should be minute's primary (Zzshare P2 per CLAUDE.md, Zhitu P5) both reject `qfq` for minutes because their upstream APIs (`stk_mins` / stock-history) ignore the adjust parameter — the `supports_kline` filter is a safety net against silent semantic loss, but at the cost of dropping the primary chain entirely.

### 2.3 Why only minute is fragile

`d`/`w`/`m` have 4+ working candidates even with Zzshare/Zhitu excluded (Tushare P0 / Baostock P1 / Akshare P3 / Yfinance P4 all accept qfq for daily). Minute has only Akshare / Yfinance / Myquant, and each depends on environment state (`.venv` install, env var) that the test suite doesn't validate.

### 2.4 Confirmed by user direct test

`ZzshareFetcher.get_kline_data(code, frequency="5", adjust="qfq")` returns data successfully when called directly because the fetcher's `get_kline_data` (`base.py:457`) does **not** consult `supports_kline` — that filter is only used by `manager._kline_candidates`. The minute branch in `_fetch_raw_data` (`zzshare_fetcher.py:217-250`) ignores `adjust` entirely and returns unadjusted bars. So Zzshare *can* serve 5m+qfq; it's only excluded by the manager's filter, which the route forces into the filter by hard-coding `adjust="qfq"`.

---

## 3. Fix

### 3.1 Route change (`stock_data/api/routes/agent.py:914-921`)

```python
df, _src = manager.get_kline_data(
    code,
    days=fetch_days,
    frequency=profile.mgr_frequency,
    adjust="qfq" if profile.mgr_frequency in ("d", "w", "m") else None,
    asset="stock",
)
```

`profile.mgr_frequency` is one of `"d"|"w"|"m"|"1"|"5"|"15"|"30"|"60"` per `_FEATURE_FREQS` (`agent.py:160-173`). The branch expression reuses an existing field — no new state, no new validation layer, no parallel frequency-keyed dict (CLAUDE.md anti-pattern).

### 3.2 Per-frequency `adjust` decision table (authoritative)

This table is the **single source of truth** for what `adjust` value the route sends to `manager.get_kline_data` for the stocks batch-profile endpoint. Do not encode this elsewhere.

| frequency | stock `adjust` | index `adjust` | Rationale |
|---|---|---|---|
| `d` | `"qfq"` | `None` | stock: all d-serving fetchers (Tushare P0 / Baostock P1 / Zzshare P2 / Akshare P3 / Yfinance P4) accept qfq; 前复权让 ex-dividend gaps 不污染 MA / 支撑压力位。index: 无 qfq 概念。 |
| `w` | `"qfq"` | `None` | 同 d。 |
| `m` | `"qfq"` | `None` | 同 d。 |
| `1m`/`5m`/`15m`/`30m`/`60m` | `None` | `None` | stock: Zzshare P2 / Zhitu P5 的 minute upstream 忽略 adjust —— 传 qfq 会把它们从 candidate filter 踢出,只剩 Akshare/Yfinance/Myquant 这条脆弱 fallback 链。index: 无 qfq。 |

The route implementation (`api/routes/agent.py`) reads `profile.mgr_frequency` directly. Don't repeat the if/else at the call site — the source of truth is this table.

### 3.3 Why a retry/fallback layer is **not** the right shape

A second attempt with `adjust=None` after a first attempt with `adjust="qfq"` would add a route-level retry on top of manager's existing `_with_failover`. That doubles the error surface (`errors[]` semantics become ambiguous: a qfq-fail + None-success would surface as either one or two records depending on how the exception handler is structured), and the manager's failover already covers per-fetcher retry+circuit-breaker. The single-attempt, pre-filtered-right shape is what makes the route deterministic.

### 3.4 No change to other endpoints

| Endpoint | Current `adjust` | After |
|---|---|---|
| `/agent/stocks/batch-profile` | `"qfq"` always | per §3.2 table |
| `/agent/indices/batch-profile` | `None` always (`agent.py:668`) | unchanged — already aligned with table |
| `/agent/boards/batch-profile` | N/A (uses `get_board_history`, THS single-source) | unchanged |

The indices route was already correct. The stocks route is the only one being changed; the boards route doesn't go through `get_kline_data` at all.

---

## 4. Error semantics (unchanged)

`manager.get_kline_data` failure → `except Exception` in the route (`agent.py:922-928`) still:
1. logs `[agent/stocks/batch-profile] {code} features failed: {exc}` with `exc_info=True`
2. leaves `features = None`
3. appends `StockBatchAspectError(aspect="features", error=..., message=...)` to `errors[]`
4. the entry's `ok = any(v is not None for v in (quote, features, info, boards))` still works — `features=null` does not flip `ok` to `False` unless every aspect failed.

The only behavioral change is that 5m/15m/30m/60m now have a real primary candidate (Zzshare P2 or Zhitu P5) in the failover chain, so the probability of hitting the error path drops significantly in production.

---

## 5. Testing

### 5.1 Modify `tests/test_agent_batch_features.py::TestStocksBatchProfile::test_passes_adjust_qfq_and_converts_minute_freq_for_manager`

Rename to `test_passes_adjust_qfq_for_d_and_none_for_minute`. Split the single body into two assertion blocks:

```python
def test_passes_adjust_qfq_for_d_and_none_for_minute(self, client, monkeypatch):
    mock_manager = MagicMock()
    mock_manager.get_realtime_quote.return_value = _make_unified_quote("600519")
    mock_manager.get_kline_data.return_value = (_make_kline_df(120), "zzshare")
    mock_manager.get_stock_info.return_value = ({"industry": "白酒"}, "zhitu")
    _bind_manager(monkeypatch, mock_manager)
    with patch(_BOARD_STOCKS_PATCH, return_value=([], False, "persistence")):
        # d → qfq
        client.post(
            "/api/v1/agent/stocks/batch-profile",
            json=_stock_request(["600519"], frequency="d", days=60),
        )
        d_kwargs = mock_manager.get_kline_data.call_args.kwargs
        assert d_kwargs["adjust"] == "qfq"
        assert d_kwargs["asset"] == "stock"
        assert d_kwargs["frequency"] == "d"

        # 5m → None (Zzshare P2 不再被 supports_kline filter 踢掉)
        client.post(
            "/api/v1/agent/stocks/batch-profile",
            json=_stock_request(["600519"], frequency="5m", days=3),
        )
        m_kwargs = mock_manager.get_kline_data.call_args.kwargs
        assert m_kwargs["adjust"] is None
        assert m_kwargs["asset"] == "stock"
        assert m_kwargs["frequency"] == "5"
```

### 5.2 Add new test — `test_5m_features_uses_unadjusted_so_zzshare_is_in_candidates`

Regression pin against future hard-code regressions:

```python
def test_5m_features_uses_unadjusted_so_zzshare_is_in_candidates(
    self, client, monkeypatch
):
    """Pin the contract: 5m + adjust=None keeps Zzshare/Zhitu in the manager's
    candidate list so the primary P2/P5 chain is exercised; with the old
    hard-coded qfq they were filtered out by supports_kline and the call fell
    through to fragile fallbacks (Akshare/Yfinance/Myquant), giving features=null
    in production whenever those three were unavailable.

    The test mocks get_kline_data so it doesn't hit real upstreams; the
    assertion is at the route boundary (adjust value sent to manager) — same
    level as the regression pin above.
    """
    mock_manager = MagicMock()
    mock_manager.get_realtime_quote.return_value = _make_unified_quote("600519")
    mock_manager.get_kline_data.return_value = (_make_kline_df(120), "zzshare")
    mock_manager.get_stock_info.return_value = ({"industry": "白酒"}, "zhitu")
    _bind_manager(monkeypatch, mock_manager)
    with patch(_BOARD_STOCKS_PATCH, return_value=([], False, "persistence")):
        resp = client.post(
            "/api/v1/agent/stocks/batch-profile",
            json=_stock_request(["600519"], frequency="5m", days=3),
        )
    assert resp.status_code == 200
    sent_adjust = mock_manager.get_kline_data.call_args.kwargs["adjust"]
    assert sent_adjust is None, (
        "5m + adjust='qfq' filters Zzshare/Zhitu out of candidates via "
        "supports_kline, leaving only fragile fallbacks. Spec §3.4 mandates "
        "`adjust='qfq' where the fetcher supports it`; minute fetchers "
        "ignore adjust upstream, so passing None keeps the primary chain alive."
    )
```

### 5.3 Optional live-network sanity test

```python
@pytest.mark.live_network
def test_5m_features_not_null_in_real_env(self, client):
    """Sanity: with real network, /agent/stocks/batch-profile?frequency=5m on
    a liquid CSI stock should return features != null.

    Skipped by default (CLAUDE.md pytest addopts: `-m "not live_network"`);
    only runs under `pytest -m ""` or `pytest -m live_network`. The
    network guard xfails on transient outages (see tests/_network_guard.py).
    """
    resp = client.post(
        "/api/v1/agent/stocks/batch-profile",
        json={"codes": ["600519"], "frequency": "5m", "days": 3},
    )
    assert resp.status_code == 200
    e = resp.json()["results"][0]
    assert e["features"] is not None, (
        f"5m features should not be null in a properly configured env; "
        f"errors={e['errors']}"
    )
```

### 5.4 Untouched tests (verification of non-regression)

- `test_kline_failure_isolated` (`agent_batch_features.py:398`) — mocks `get_kline_data.side_effect = DataFetchError(...)`. After the fix the route still raises → `features=None` → `errors[]` populated → unchanged behavior.
- `test_days_out_of_range_422` (`agent_batch_features.py:430`) — `_resolve_and_validate_days` is upstream of the adjust branch. Unchanged.
- `TestIndicesBatchProfile::*` and `TestBoardsBatchProfile::*` — different routes, no change.
- `TestStocksBatchProfile::test_all_aspects_populated` (`agent_batch_features.py:358` region) — uses default `frequency="d"` which now still passes `adjust="qfq"`. Unchanged behavior.

---

## 6. Spec / docs sync

### 6.1 `docs/superpowers/specs/2026-08-27-agent-batch-profile-features-design.md §3.4`

Replace line 283-295 (the pseudo-code line `2. Per code: ...`) with a per-frequency breakdown matching §3.2 above. Add a `### 3.4.1 Minute-frequency qfq 决策表` subsection reproducing the §3.2 table verbatim. Mention that the table is the route's **single source of truth**.

### 6.2 `CLAUDE.md` Anti-patterns

Add a new bullet to the Agent Batch API subsection's `### Anti-patterns` block (CLAUDE.md line 371-379, after the existing bullets):

> **Don't** hardcode `adjust="qfq"` in `/agent/stocks/batch-profile` for minute frequencies — Zzshare P2 / Zhitu P5's `supports_kline` rejects `qfq` for minutes, kicking the primary chain out and leaving only fragile fallbacks. Per spec §3.4 the decision is per-frequency, not per-endpoint.

### 6.3 Out-of-scope docs

- `api-reference.md` — describes the response shape, not the adjust selection logic. No change.
- `docs/agent-batch-api-proposal-2026-07-27.md` — historical proposal, doesn't reference adjust. No change.
- README — no change.

---

## 7. Risk analysis

### 7.1 Daily/weekly/monthly behavior unchanged

`d`/`w`/`m` already pass `"qfq"` before this change and continue to do so. The candidate filter result is identical for these frequencies. No production-visible behavior change for any user currently calling with `frequency="d"` (the default).

### 7.2 Minute bars no longer 前复权

The minute block in `_fetch_raw_data` for Zzshare (`zzshare_fetcher.py:209-217`) explicitly ignores `adjust`. So this spec change is in **direction alignment with upstream reality**: the bars were never qfq-adjusted even when `adjust="qfq"` was passed. The change makes the contract honest (None = unadjusted upstream) rather than aspirational (qfq = silent upstream-no-op).

Caveat for users: any current caller that was *relying* on the `adjust="qfq"` parameter being honored (e.g. computing minute MA60 over adjusted prices for a stock with recent ex-dividend actions) will see different values. Mitigation: this is the original "by design" per spec §3.4 ("qfq applied where the serving fetcher supports it"); there is no actual upstream qfq for minute, so the previous behavior was misleading at best.

### 7.3 Cache invalidation

The 60s `get_quote_cache` TTLCache used by all agent endpoints will hold entries under the old `adjust="qfq"` shape for up to 60s after deploy. The cached payload is the *response*, not the request, so cache shape is unchanged (same `BatchFeatures` schema, same field set). No invalidation needed.

### 7.4 Test isolation

`test_kline_failure_isolated` mocks `get_kline_data` to raise regardless of arguments, so the `adjust` value sent to the mock is irrelevant to that test. After the fix the route still raises → `features=None`. The test passes identically.

### 7.5 Live-network test flakiness

The optional `test_5m_features_not_null_in_real_env` carries the standard `live_network` flakiness risk; marked accordingly and not part of the default pytest run. CI with real fetcher credentials can opt in.

---

## 8. Implementation plan

Once this design is approved, the next step is `superpowers:writing-plans` to produce a multi-step implementation plan. The plan will sequence:

1. **Route change** (`api/routes/agent.py:914-921`) — single expression-level edit.
2. **Test split** (`tests/test_agent_batch_features.py`) — rename and split the existing assertion; add the regression pin; optionally add the live_network sanity.
3. **Spec sync** (`docs/superpowers/specs/2026-08-27-agent-batch-profile-features-design.md §3.4`) — replace pseudo-code line with per-frequency breakdown; add §3.4.1 subsection.
4. **CLAUDE.md** — add the anti-pattern line.
5. **Verify** — `pytest tests/test_agent_batch_features.py` (default deselect), full suite `pytest -m ""`, ruff format + lint.

Each step is independently testable; the steps roughly map to file boundaries.