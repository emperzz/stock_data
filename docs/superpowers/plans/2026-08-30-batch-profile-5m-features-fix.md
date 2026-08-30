# 5m Features=null Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix `POST /api/v1/agent/stocks/batch-profile` returning `features: null` for `frequency="5m"` by aligning the route with the per-frequency `adjust` decision that spec §3.4 already specified.

**Architecture:** Single expression change in `post_stocks_batch_profile` so minute frequencies pass `adjust=None` (restoring Zzshare P2 / Zhitu P5 to the manager's candidate list) while `d`/`w`/`m` keep `adjust="qfq"`. Backed by a regression-pin test, synced spec, and a CLAUDE.md anti-pattern.

**Tech Stack:** Python 3, FastAPI, pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-30-batch-profile-5m-features-fix-design.md`

---

## Task 1: Add CLAUDE.md anti-pattern (lock the contract first)

**Files:**
- Modify: `CLAUDE.md:371-379` (append one bullet to the "Agent Batch API → Anti-patterns" subsection)

- [ ] **Step 1: Open `CLAUDE.md`, locate the Agent Batch API subsection**

The relevant section is `### Anti-patterns` under `## Agent Batch API (\`/api/v1/agent/*\`)`. It's at line 371 (header) through 379 (last bullet before `## Common Commands` at line 381). The block currently has 7 bullets; we add an 8th.

- [ ] **Step 2: Append one bullet**

After the existing bullet ending `... scan every \`|---\` separator row and require a data row after it.` (line 379), insert:

```markdown
- **Don't** hardcode `adjust="qfq"` in `/agent/stocks/batch-profile` for minute frequencies — Zzshare P2 / Zhitu P5's `supports_kline` rejects `qfq` for minutes, kicking the primary chain out and leaving only fragile fallbacks. Per spec §3.4 the decision is per-frequency, not per-endpoint.
```

The inserted text must use the same bullet pattern (`- **Don't** ...`) and indentation (no leading spaces — the bullets sit flush-left under `### Anti-patterns`).

- [ ] **Step 3: Verify the edit visually**

Run: `grep -n "hardcode .adjust=" CLAUDE.md`

Expected: exactly one line containing the new bullet text, located at line 380 (immediately after the previous bullet at 379, before `## Common Commands` at 381).

- [ ] **Step 4: Commit**

```bash
cd E:/GitRepo/stock_data
git add CLAUDE.md
git commit -m "docs(claude): don't hardcode adjust=qfq for minute in batch-profile"
```

---

## Task 2: Sync spec §3.4

**Files:**
- Modify: `docs/superpowers/specs/2026-08-27-agent-batch-profile-features-design.md:283-295` (replace pseudo-code + comment)
- Modify: same file (insert new `### 3.4.1` subsection between current §3.4 and the next heading)

- [ ] **Step 1: Open the spec, locate §3.4**

The file is `docs/superpowers/specs/2026-08-27-agent-batch-profile-features-design.md`. §3.4 spans roughly line 251 (`### 3.4 Per-frequency \`days\` validation`) through line 295 (end of the "qfq applied where..." bullet). The lines to replace are 283-295 — the bullet beginning `2. Per code: \`manager.get_kline_data(code, days=feature_days, ...`

- [ ] **Step 2: Replace lines 283-295**

Current text (verbatim):

```markdown
2. Per code: `manager.get_kline_data(code, days=feature_days,
   frequency=<mgr-freq>, adjust="qfq" if asset=="stock" else None,
   asset=<stock|index>)`.
   - `feature_days = max(requested days, indicator warm-up)` — the
     existing `max(days, lookback)` pattern (see CLAUDE.md "Indicator
     Computation"). MA60 + 20-bar context + ATR14 + swing detection want
     ≥ ~90 daily bars to be warm; minute frames warm in fewer bars.
   - `adjust="qfq"` is **hard-coded** for stocks (user decision: no
     `adjust` request param; 前复权 so ex-dividend gaps do not corrupt
     MA / support-resistance math). Indices: no adjust. Minute
     frequencies: qfq applied where the serving fetcher supports it;
     otherwise upstream returns unadjusted bars (documented, not an
     error).
```

Replace with:

```markdown
2. Per code: `manager.get_kline_data(code, days=feature_days,
   frequency=<mgr-freq>, adjust=<per-asset-and-frequency>,
   asset=<stock|index>)`. The `adjust` value is decided by both axes:
   - **stock + d/w/m** → `"qfq"`. 前复权让 ex-dividend gaps 不污染 MA /
     支撑压力位算术; d/w/m 的 serving fetcher(Tushare P0 / Baostock P1 /
     Zzshare P2 / Akshare P3 / Yfinance P4)全部接受 qfq。
   - **stock + minute (1m/5m/15m/30m/60m)** → `None`. Zzshare P2 和
     Zhitu P5 的 `supports_kline` 在 minute 下显式拒绝 qfq(stk_mins /
     stock-history upstream 忽略 adjust); 若 route 仍传 qfq,两 fetcher
     被 filter 排除,候选只剩 Akshare/Yfinance/Myquant 这条脆弱 fallback
     链,生产里 `MYQUANT_TOKEN` 未配或 `.venv` 未装 akshare/yfinance 时
     整个 aspect fail、`features=null`。Spec §3.4 早在初版就预告过
     *"qfq applied where the serving fetcher supports it; otherwise
     upstream returns unadjusted bars"* — 此处实现终于对齐这条注释。
   - **index** → `None`. 指数无 qfq/hfq 概念,所有 index fetcher 都是
     `adjust in ("", None)` 接受度。
   - `feature_days = max(requested days, indicator warm-up)` — the
     existing `max(days, lookback)` pattern (see CLAUDE.md "Indicator
     Computation"). MA60 + 20-bar context + ATR14 + swing detection want
     ≥ ~90 daily bars to be warm; minute frames warm in fewer bars.
```

- [ ] **Step 3: Insert new §3.4.1 subsection**

Insert this block **between** the just-replaced section (which now ends with `accept 度。`) and the next existing line (the start of step `3. The fetched df feeds the pure feature module...`):

```markdown
### 3.4.1 Minute-frequency qfq 决策表(防止 hard-code 回归)

| frequency | stock adjust | index adjust | 原因 |
|---|---|---|---|
| `d` | `"qfq"` | `None` | stock: 全部 serving fetcher 支持 qfq; index: 无 qfq 概念 |
| `w` | `"qfq"` | `None` | 同上 |
| `m` | `"qfq"` | `None` | 同上 |
| `1m`/`5m`/`15m`/`30m`/`60m` | `None` | `None` | stock: Zzshare P2 / Zhitu P5 的 minute upstream 忽略 adjust; index: 无 qfq |

这条表是 `post_stocks_batch_profile` 的 **唯一权威来源** ——
不要凭印象 hard-code `adjust="qfq"`。route 的实现
(`api/routes/agent.py:918` 区域)直接读 `profile.mgr_frequency`,
不在调用点重复 if/else。
```

- [ ] **Step 4: Verify the spec still reads as one coherent section**

Run: `grep -n "^### 3.4" docs/superpowers/specs/2026-08-27-agent-batch-profile-features-design.md`

Expected: two hits — `### 3.4 Per-frequency` (unchanged) and `### 3.4.1 Minute-frequency qfq 决策表` (new), in that order.

- [ ] **Step 5: Commit**

```bash
cd E:/GitRepo/stock_data
git add docs/superpowers/specs/2026-08-27-agent-batch-profile-features-design.md
git commit -m "docs(spec): sync §3.4 with per-frequency adjust decision"
```

---

## Task 3: Write failing tests (TDD red phase)

**Files:**
- Modify: `tests/test_agent_batch_features.py:414-428` (rename + split test)
- Modify: `tests/test_agent_batch_features.py` (add new test after the renamed one)

- [ ] **Step 1: Read the existing test to understand the fixture pattern**

Open `tests/test_agent_batch_features.py` and locate:

```python
def test_passes_adjust_qfq_and_converts_minute_freq_for_manager(self, client, monkeypatch):
    mock_manager = MagicMock()
    mock_manager.get_realtime_quote.return_value = _make_unified_quote("600519")
    mock_manager.get_kline_data.return_value = (_make_kline_df(120), "zzshare")
    mock_manager.get_stock_info.return_value = ({"industry": "白酒"}, "zhitu")
    _bind_manager(monkeypatch, mock_manager)
    with patch(_BOARD_STOCKS_PATCH, return_value=([], False, "persistence")):
        client.post(
            "/api/v1/agent/stocks/batch-profile",
            json=_stock_request(["600519"], frequency="5m", days=3),
        )
    kwargs = mock_manager.get_kline_data.call_args.kwargs
    assert kwargs["adjust"] == "qfq"
    assert kwargs["asset"] == "stock"
    assert kwargs["frequency"] == "5"  # public "5m" -> manager "5"
```

This is the test we're splitting. Note the helpers used: `_make_unified_quote`, `_make_kline_df`, `_bind_manager`, `_BOARD_STOCKS_PATCH`, `_stock_request`. All are imported at the top of the file.

- [ ] **Step 2: Replace the existing test with the split version**

Delete the body of `test_passes_adjust_qfq_and_converts_minute_freq_for_manager` (lines 414-428 inclusive) and the `def` line above it. Replace the whole def block with:

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

The class context is `TestStocksBatchProfile`; this method is at the same indentation level as the other `def test_*(self, ...)` methods around it (4-space indent for method definition).

- [ ] **Step 3: Add the regression-pin test immediately after the renamed one**

Insert this method directly below `test_passes_adjust_qfq_for_d_and_none_for_minute`:

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

- [ ] **Step 4: Run the new tests and verify they fail (RED)**

Run:

```bash
cd E:/GitRepo/stock_data
.venv/Scripts/python.exe -m pytest tests/test_agent_batch_features.py::TestStocksBatchProfile::test_passes_adjust_qfq_for_d_and_none_for_minute tests/test_agent_batch_features.py::TestStocksBatchProfile::test_5m_features_uses_unadjusted_so_zzshare_is_in_candidates -v
```

Expected: both tests FAIL. The 5m assertion `m_kwargs["adjust"] is None` will fail with `assert 'qfq' is None`. The regression pin will fail the same way. The d assertion (which still passes today) is in the same test method; expect the test to fail as a whole because pytest stops at the first failed assertion.

If pytest reports both tests as `PASSED`, **stop** — that means the route already passes `adjust=None` for minute, contradicting the spec. Investigate before continuing.

- [ ] **Step 5: Commit the failing tests (with the expected red state)**

```bash
cd E:/GitRepo/stock_data
git add tests/test_agent_batch_features.py
git commit -m "test(batch-profile): pin 5m→adjust=None; rename split test (red)"
```

The commit message notes "red" so the next commit can be "green" — standard TDD bookkeeping.

---

## Task 4: Implement the fix (TDD green phase)

**Files:**
- Modify: `stock_data/api/routes/agent.py:914-921` (one expression)

- [ ] **Step 1: Open `stock_data/api/routes/agent.py`, locate line 918**

The exact current text at lines 914-921:

```python
            df, _src = manager.get_kline_data(
                code,
                days=fetch_days,
                frequency=profile.mgr_frequency,
                adjust="qfq",
                asset="stock",
            )
```

- [ ] **Step 2: Edit the `adjust=` line**

Replace `adjust="qfq",` with:

```python
                adjust="qfq" if profile.mgr_frequency in ("d", "w", "m") else None,
```

The replacement line has 16 leading spaces (matches the indentation of the surrounding `manager.get_kline_data(` block; inside the function-call the lines are indented to align with the `(`).

After the edit, lines 914-921 read:

```python
            df, _src = manager.get_kline_data(
                code,
                days=fetch_days,
                frequency=profile.mgr_frequency,
                adjust="qfq" if profile.mgr_frequency in ("d", "w", "m") else None,
                asset="stock",
            )
```

- [ ] **Step 3: Run the previously-failing tests and verify they pass (GREEN)**

Run:

```bash
cd E:/GitRepo/stock_data
.venv/Scripts/python.exe -m pytest tests/test_agent_batch_features.py::TestStocksBatchProfile::test_passes_adjust_qfq_for_d_and_none_for_minute tests/test_agent_batch_features.py::TestStocksBatchProfile::test_5m_features_uses_unadjusted_so_zzshare_is_in_candidates -v
```

Expected: both tests PASS. If any fails, **stop** and re-check the expression — common bug: forgetting the `else None` branch.

- [ ] **Step 4: Run the full TestStocksBatchProfile class**

Run:

```bash
cd E:/GitRepo/stock_data
.venv/Scripts/python.exe -m pytest tests/test_agent_batch_features.py::TestStocksBatchProfile -v
```

Expected: all `TestStocksBatchProfile` tests PASS. In particular:
- `test_all_aspects_populated` (line 354) — uses default `frequency="d"`, must still pass.
- `test_kline_failure_isolated` (line 398) — mocks `get_kline_data.side_effect = DataFetchError(...)`, must still pass (route still raises → `features=None`).
- `test_days_out_of_range_422` (line 430) — `_resolve_and_validate_days` is upstream of the adjust branch, must still pass.

- [ ] **Step 5: Run TestIndicesBatchProfile and TestBoardsBatchProfile (regression check)**

Run:

```bash
cd E:/GitRepo/stock_data
.venv/Scripts/python.exe -m pytest tests/test_agent_batch_features.py -v
```

Expected: the full `test_agent_batch_features.py` file PASSes. The change is local to `post_stocks_batch_profile` so indices/boards tests should be unaffected, but verify.

- [ ] **Step 6: Commit the fix**

```bash
cd E:/GitRepo/stock_data
git add stock_data/api/routes/agent.py
git commit -m "fix(batch-profile): minute freq passes adjust=None to keep Zzshare P2 / Zhitu P5 in candidates"
```

---

## Task 5: Final verification + housekeeping

**Files:** none modified — verification only

- [ ] **Step 1: Run default pytest suite**

Run:

```bash
cd E:/GitRepo/stock_data
.venv/Scripts/python.exe -m pytest
```

Expected: passes. Default `addopts = ["-m", "not live_network"]` (per `pyproject.toml`) skips live_network tests. The `test_5m_features_uses_unadjusted_so_zzshare_is_in_candidates` is a regular (non-marked) test, so it runs.

- [ ] **Step 2: Run ruff format + lint**

Run:

```bash
cd E:/GitRepo/stock_data
ruff format .
ruff check .
```

Expected: no formatting changes, no lint errors. If `ruff format` rewrites anything, that's a problem — re-check the test code style against surrounding tests. If `ruff check` flags issues, fix them inline.

- [ ] **Step 3: Verify the route line via grep**

Run:

```bash
grep -n "adjust=\"qfq\" if profile.mgr_frequency" stock_data/api/routes/agent.py
```

Expected: exactly one line, the new expression.

Run:

```bash
grep -n "adjust=\"qfq\"" stock_data/api/routes/agent.py
```

Expected: zero lines. The old hard-coded form should be gone.

- [ ] **Step 4: Show the commit log for this change**

Run:

```bash
cd E:/GitRepo/stock_data
git log --oneline -5
```

Expected: 4 commits visible from this branch's HEAD:
1. `docs(spec): 5m features=null fix design — per-frequency adjust` (the spec, already on master)
2. `docs(claude): don't hardcode adjust=qfq for minute in batch-profile` (Task 1)
3. `docs(spec): sync §3.4 with per-frequency adjust decision` (Task 2)
4. `test(batch-profile): pin 5m→adjust=None; rename split test (red)` (Task 3)
5. `fix(batch-profile): minute freq passes adjust=None to keep Zzshare P2 / Zhitu P5 in candidates` (Task 4)

If any is missing, **stop** and investigate — do not proceed to declaration of completion with a missing piece.

---

## Self-review

### Spec coverage

| Spec § | Task implementing it |
|---|---|
| §3.1 Route change | Task 4 |
| §3.2 Decision table | Task 2 (inserted as §3.4.1 in the design spec); route reads `profile.mgr_frequency` per Task 4 |
| §3.3 No retry layer | N/A — explicit non-action; spec §3.3 already records the decision |
| §3.4 Other endpoints unchanged | Task 4 (verify only the stocks route) + Task 5 (full pytest) |
| §4 Error semantics | Task 5 Step 1 (default pytest covers `test_kline_failure_isolated`) |
| §5.1 Test split | Task 3 Steps 2 |
| §5.2 New regression test | Task 3 Step 3 |
| §5.3 Optional live_network | NOT INCLUDED — user picked "route + test + spec" scope; live_network test deferred |
| §5.4 Untouched tests still pass | Task 4 Step 4 + Task 5 Step 1 |
| §6.1 Spec §3.4 sync | Task 2 |
| §6.2 CLAUDE.md anti-pattern | Task 1 |

Note on §5.3: the spec includes it as "Optional" but the user-selected scope during brainstorming was "route + test + spec" (option 2), which does NOT cover adding new live_network tests. Removing §5.3 from the implementation scope — if the user wants it later, add it as a follow-up.

### Placeholder scan

No "TBD", "TODO", "implement later", or "fill in details" in any step. Every code block contains the actual content.

### Type / name consistency

- `profile.mgr_frequency` referenced consistently in Task 2 (spec edit) and Task 4 (route edit) — same source-of-truth field.
- `_FEATURE_FREQS` and `FreqProfile` referenced in Task 2 (spec context) — match definitions at `agent.py:131-173`.
- Test method names `test_passes_adjust_qfq_for_d_and_none_for_minute` and `test_5m_features_uses_unadjusted_so_zzshare_is_in_candidates` consistent across Task 3 step 3 (run command), Task 3 step 4 (verification), Task 4 step 3 (verification), Task 4 step 4 (verification).
- Helper names `_make_unified_quote`, `_make_kline_df`, `_bind_manager`, `_BOARD_STOCKS_PATCH`, `_stock_request` — defined at top of `tests/test_agent_batch_features.py` (not modified by this plan). Verified by Step 1 of Task 3.