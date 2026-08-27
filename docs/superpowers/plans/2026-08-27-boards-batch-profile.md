# `/agent/boards/batch-profile` — Board-level Computed Features — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a new POST endpoint `POST /api/v1/agent/boards/batch-profile` that fans out across 1-5 THS board platecodes, returning a per-board minimal realtime quote + computed `trend / pivots / volume` features at a single frequency — mirroring the existing `/agent/indices/batch-profile` shape but for boards.

**Architecture:** A new handler `post_boards_batch_profile` in `api/routes/agent.py` follows the exact loop skeleton of `get_indices_batch_profile` (2-aspect fan-out: `quote` + `features`, errors-as-dict). It calls `manager.get_board_realtime(board_code, source="ths")` and `manager.get_board_history(board_code, source="ths", ...)` per code. **No composite cache layer** (deviation from stocks/indices — see spec §5). New schemas in `api/schemas.py`; new MD template + `_MD_TEMPLATES` registration. Reuses `_FEATURE_FREQS`, `_resolve_and_validate_days`, `_batch_summary`, `_render_agent`, `_md_feature_block`, `_render_dict_block` from the agent module.

**Tech Stack:** Python 3, FastAPI, Pydantic v2, pytest, `stock_data.data_provider.features.build.build_features`. No new fetcher / manager method / `DataCapability` flag.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-27-boards-batch-profile-design.md`.
- Source is **fixed to `ths`** (single source). Do NOT add a `source` request param.
- `board_type` is **NOT** exposed to the caller; passed as `board_type=None` and resolved by `ThsFetcher.get_board_realtime` via the `stock_board` cache (with internal fallback) and by `ThsFetcher.get_board_history` likewise.
- Public `frequency` strings (`d / w / m / 1m / 5m / 15m / 30m / 60m`) validated against `_FEATURE_FREQS` (defined in `api/routes/agent.py`). The manager-facing frequency is `_FEATURE_FREQS[frequency].mgr_frequency` — `5m`→`5`, `15m`→`15`, …; `d/w/m` unchanged. **Never pass `5m` verbatim to `manager.get_board_history`** (fetchers only accept bare minute codes `1/5/15/30/60`).
- Per-frequency `days` (calendar) ranges — route must 422 outside these (min is inclusive, max is inclusive):
  `d:(2,365) w:(14,1095) m:(60,1825) 1m:(2,3) 5m:(2,5) 15m:(2,8) 30m:(2,15) 60m:(2,30)`
- Default `days` when omitted: `d:60 w:156 m:365 1m:3 5m:5 15m:8 30m:15 60m:30`.
- `codes` length: `min_length=1, max_length=5` (Pydantic validation, enforced).
- Boards are THS platecodes (885xxx concept / 881xxx industry). The route **does not** validate the prefix or shape; the manager's `_with_source` raises `ValueError` on bad code which surfaces in `errors["features"]`.
- `build_features(df, frequency=frequency, days=days)` is the single entry point. Pass `frequency` (not `mgr_frequency`) and `days` (not `fetch_days`). An empty DataFrame returns `{trend:{}, pivots:{}, volume:{}}` without raising — `BatchFeatures(**...)` accepts that via `default_factory`.
- `fetch_days = max(days, _FEATURE_FREQS[frequency].ma60_warmup_days)` — keep the MA60 warmup logic identical to indices/stocks.
- `name` resolution: call `stock_board_cache.get_board_name_with_fallback(board_code, "ths", manager=manager)`. The helper swallows `DataFetchError / ValueError / AttributeError` internally — handler MUST NOT wrap in try/except. On None → `name=""`.
- Quote dict keys: `manager.get_board_realtime` returns `(dict, source_name)`; extract `dict.get("price")` and `dict.get("change_pct")`. Both may be None — let `MinimalQuote` carry them through.
- **No new cache key factory** in `api/cache.py`. Handler MUST NOT call `cached_lookup` / `cached_store`. Do not add `make_boards_batch_profile_cache_key`.
- **No new `_aspect_try` helper.** Reuse the per-aspect `try/except: ... errors[name] = "..."` pattern directly (same shape as `get_indices_batch_profile`).
- Run tests with `.venv/Scripts/python.exe -m pytest`.
- Commit after every green test run. Keep commits small.
- Lint with `ruff check .` and `ruff format .` before the final commit.

---

## File Structure

| File | Role | Created? |
|---|---|---|
| `stock_data/api/schemas.py` | Add 3 new Pydantic models | Modified |
| `stock_data/api/routes/agent.py` | Add 1 handler + 1 MD template + 1 `_MD_TEMPLATES` entry | Modified |
| `tests/test_agent_boards_batch_profile.py` | New test module covering schema / handler / MD / no-cache-layer | Created |
| `docs/agent-batch-api-proposal-2026-07-27.md` | Append §3.2.4 describing the new endpoint | Modified |
| `CLAUDE.md` | Add 1 row to the Agent Batch API table + 1 bullet under "Design contract" | Modified |

No new fetcher, no new manager method, no new `DataCapability` flag, no new helper module, no new cache key factory. The handler loop is structurally a 2-aspect mirror of `get_indices_batch_profile`.

---

### Task 1: Schemas — `BoardProfile` + `BoardsBatchProfileRequest` + `BoardsBatchProfileResponse`

**Files:**
- Modify: `stock_data/api/schemas.py` (add 3 new models at the end of the file, after `StockBatchProfileResponse`)
- Test: `tests/test_agent_boards_batch_profile.py` (create, but for this task only the schema-import tests run)

**Interfaces:**
- Consumes: nothing (this is pure schema work).
- Produces:
  - `BoardProfile(BaseModel)` — `code: str`, `name: str = ""`, `quote: MinimalQuote | None`, `features: BatchFeatures | None`, `errors: dict[str, str | None]` (default_factory).
  - `BoardsBatchProfileRequest(BaseModel)` — `codes: list[str]` (min_length=1, max_length=5), `frequency: Literal[...] = "d"`, `days: int | None = Field(default=None, ge=2)`.
  - `BoardsBatchProfileResponse(BaseModel)` — `frequency: str = "d"`, `days: int = 0`, `boards: list[BoardProfile]` (default_factory), `summary: dict` (default_factory).

- [ ] **Step 1: Write the failing schema test**

Create `tests/test_agent_boards_batch_profile.py` with imports and three schema-only tests (these will FAIL because the schemas don't exist yet):

```python
"""Tests for /api/v1/agent/boards/batch-profile (THS board-level features)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from stock_data.api.schemas import (
    BatchFeatures,
    BoardProfile,
    BoardsBatchProfileRequest,
    BoardsBatchProfileResponse,
    MinimalQuote,
)


class TestSchemas:
    def test_board_profile_defaults(self):
        bp = BoardProfile(code="885595")
        assert bp.code == "885595"
        assert bp.name == ""
        assert bp.quote is None
        assert bp.features is None
        assert bp.errors == {}

    def test_board_profile_with_full_payload(self):
        bp = BoardProfile(
            code="881270",
            name="半导体",
            quote=MinimalQuote(price=1234.5, change_pct=1.23),
            features=BatchFeatures(),
            errors={"quote": None, "features": None},
        )
        assert bp.name == "半导体"
        assert bp.quote.price == 1234.5
        assert bp.features == BatchFeatures()
        assert bp.errors == {"quote": None, "features": None}

    def test_request_accepts_codes_and_defaults(self):
        req = BoardsBatchProfileRequest(codes=["885595", "881270"])
        assert req.codes == ["885595", "881270"]
        assert req.frequency == "d"
        assert req.days is None

    def test_request_rejects_empty_codes(self):
        with pytest.raises(ValidationError):
            BoardsBatchProfileRequest(codes=[])

    def test_request_rejects_too_many_codes(self):
        with pytest.raises(ValidationError):
            BoardsBatchProfileRequest(codes=[f"88{i:04d}" for i in range(6)])

    def test_request_accepts_all_supported_frequencies(self):
        for f in ("d", "w", "m", "1m", "5m", "15m", "30m", "60m"):
            req = BoardsBatchProfileRequest(codes=["885595"], frequency=f)
            assert req.frequency == f

    def test_request_rejects_unsupported_frequency(self):
        with pytest.raises(ValidationError):
            BoardsBatchProfileRequest(codes=["885595"], frequency="2h")

    def test_response_defaults(self):
        resp = BoardsBatchProfileResponse()
        assert resp.frequency == "d"
        assert resp.days == 0
        assert resp.boards == []
        assert resp.summary == {}

    def test_response_carries_boards_in_order(self):
        resp = BoardsBatchProfileResponse(
            frequency="d",
            days=60,
            boards=[
                BoardProfile(code="881270"),
                BoardProfile(code="885595"),
            ],
            summary={"requested": 2, "ok": 2, "failed": 0, "elapsed_ms": 100},
        )
        assert [b.code for b in resp.boards] == ["881270", "885595"]
        assert resp.summary["elapsed_ms"] == 100
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:
```bash
.venv/Scripts/python.exe -m pytest tests/test_agent_boards_batch_profile.py::TestSchemas -v
```

Expected: every test in `TestSchemas` fails with `ImportError: cannot import name 'BoardProfile' from 'stock_data.api.schemas'`.

- [ ] **Step 3: Add the three schemas to `stock_data/api/schemas.py`**

Append at the end of `stock_data/api/schemas.py` (after `StockBatchProfileResponse`):

```python
# ---------------------------------------------------------------------------
# POST /api/v1/agent/boards/batch-profile
# ---------------------------------------------------------------------------


class BoardProfile(BaseModel):
    """One board in /agent/boards/batch-profile.

    Mirrors ``IndexProfile`` (same shape — ``quote`` + ``features`` +
    ``errors{}`` dict). No ``info`` / ``boards`` sub-aspects (boards have no
    company-profile equivalent).
    """

    code: str
    name: str = Field(
        default="",
        description="Board name (resolved via stock_board_cache.get_board_name_with_fallback; '' on cache miss).",
    )
    quote: MinimalQuote | None = Field(
        default=None,
        description="Realtime anchor from manager.get_board_realtime; null when upstream failed.",
    )
    features: BatchFeatures | None = Field(
        default=None,
        description="Computed trend/pivots/volume; null when K-line fetch failed.",
    )
    errors: dict[str, str | None] = Field(
        default_factory=dict,
        description="Quote/features error map; null = ok.",
    )


class BoardsBatchProfileRequest(BaseModel):
    """POST body for /agent/boards/batch-profile.

    THS platecodes (885xxx concept / 881xxx industry). No ``source`` param —
    the route is fixed to ``source='ths'`` because THS is the only fetcher
    implementing ``get_board_realtime``.
    """

    codes: list[str] = Field(
        ...,
        min_length=1,
        max_length=5,
        description="THS board platecodes (1-5). Hard cap matches the stock-picking funnel.",
    )
    frequency: Literal["d", "w", "m", "1m", "5m", "15m", "30m", "60m"] = "d"
    days: int | None = Field(default=None, ge=2, description="Calendar days; per-frequency max validated in the route.")


class BoardsBatchProfileResponse(BaseModel):
    """POST response for /agent/boards/batch-profile."""

    frequency: str = "d"
    days: int = 0
    boards: list[BoardProfile] = Field(default_factory=list)
    summary: dict = Field(default_factory=dict)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run:
```bash
.venv/Scripts/python.exe -m pytest tests/test_agent_boards_batch_profile.py::TestSchemas -v
```

Expected: all 9 tests in `TestSchemas` PASS.

- [ ] **Step 5: Commit**

```bash
git add stock_data/api/schemas.py tests/test_agent_boards_batch_profile.py
git commit -m "feat(schemas): add BoardProfile + BoardsBatchProfileRequest/Response"
```

---

### Task 2: Handler `post_boards_batch_profile`

**Files:**
- Modify: `stock_data/api/routes/agent.py` (add 1 handler + import the 3 new schemas)
- Test: `tests/test_agent_boards_batch_profile.py` (append handler tests; use `unittest.mock` for manager + cache)

**Interfaces:**
- Consumes:
  - `BoardsBatchProfileRequest` (Task 1).
  - `manager.get_board_realtime(board_code, source="ths") -> tuple[dict, str]`.
  - `manager.get_board_history(board_code, source="ths", frequency=<mgr_freq>, days=<fetch_days>) -> tuple[list[dict], str]` where `list[dict]` is consumed by `pd.DataFrame(...)`.
  - `stock_board_cache.get_board_name_with_fallback(board_code, "ths", manager=manager) -> str | None` (swallows its own errors).
  - `build_features(df, frequency=frequency, days=days) -> dict` (returns `{trend:{}, pivots:{}, volume:{}}` on empty).
- Produces:
  - `post_boards_batch_profile(payload: BoardsBatchProfileRequest, format: str = Query(...)) -> Response`
  - Side effects: appends 1 import line for the 3 new schemas. **Must not** import from `..cache` any new key factory.

- [ ] **Step 1: Write the failing handler test**

Append to `tests/test_agent_boards_batch_profile.py` (below the `TestSchemas` class). Tests use mocked `manager` via `patch`; they verify behavior WITHOUT hitting the network (default `pytest` skips `live_network`).

```python
import contextlib
import random
from unittest.mock import MagicMock, patch

import pandas as pd
from fastapi.testclient import TestClient

from stock_data.api.routes import agent as agent_module
from stock_data.api.routes import reset_manager
from stock_data.api.schemas import BoardsBatchProfileRequest
from stock_data.data_provider.base import DataFetchError


@pytest.fixture(autouse=True)
def reset_before_test():
    """Same cache-clear as tests/test_agent_batch_features.py — boards/batch-profile
    MUST NOT touch any cache layer, but we still clear in case other tests
    in this run wrote to the caches."""
    reset_manager()
    from stock_data.api import cache as api_cache

    for getter_name in (
        "get_quote_cache",
        "get_index_quote_cache",
        "get_history_cache",
        "get_pools_cache",
        "get_stock_info_cache",
        "get_news_flash_cache",
        "get_cls_feed_cache",
        "get_dragontiger_cache",
    ):
        getter = getattr(api_cache, getter_name, None)
        if getter is None:
            continue
        with contextlib.suppress(TypeError):
            getter().clear()
    for f in ("d", "w", "m", "1", "5", "15", "30", "60"):
        with contextlib.suppress(Exception):
            api_cache.get_history_cache(f).clear()
    yield


def _make_kline_df(rows: int = 90, *, seed: int = 1) -> pd.DataFrame:
    """Deterministic OHLCV frame with 90 bars — enough to warm MA60."""
    rng = random.Random(seed)
    closes = [10.0]
    for _ in range(rows - 1):
        closes.append(closes[-1] * (1 + rng.uniform(-0.02, 0.03)))
    dates = pd.date_range("2026-01-01", periods=rows, freq="B")
    vols = [1_000_000 * (1 + abs(rng.gauss(0, 0.3))) for _ in range(rows)]
    return pd.DataFrame(
        {
            "date": [d.strftime("%Y-%m-%d") for d in dates],
            "open": [round(c * 0.995, 3) for c in closes],
            "high": [round(c * 1.01, 3) for c in closes],
            "low": [round(c * 0.99, 3) for c in closes],
            "close": [round(c, 3) for c in closes],
            "volume": vols,
            "amount": [v * c for v, c in zip(vols, closes)],
            "pct_chg": [0.0] * rows,
        }
    )


def _mock_manager(*, realtime_results: dict, history_results: dict, names: dict | None = None):
    """Build a MagicMock manager matching the manager interface used by handler.

    realtime_results: {code: dict} — what get_board_realtime(code, source='ths') returns as its 1st tuple item.
    history_results:  {code: pd.DataFrame} — what get_board_history(code, source='ths', ...) returns as its 1st tuple item.
    names:            {code: str|None} — what get_board_name_with_fallback returns.

    Raises DataFetchError for codes that map to DataFetchError instances;
    raises ValueError for codes that map to ValueError instances.
    """
    manager = MagicMock()
    manager.get_board_realtime.side_effect = lambda code, source: (
        (realtime_results[code], "ths")
        if not isinstance(realtime_results.get(code), Exception)
        else (_ for _ in ()).throw(realtime_results[code])
    )
    manager.get_board_history.side_effect = lambda code, source, frequency, days: (
        (history_results[code], "ths")
        if not isinstance(history_results.get(code), Exception)
        else (_ for _ in ()).throw(history_results[code])
    )
    return manager


def _patch_manager(manager):
    """Patch get_manager() to return the supplied manager mock + patch
    stock_board_cache.get_board_name_with_fallback to use the mock's name table."""
    return patch.object(agent_module, "get_manager", return_value=manager)


class TestHandler:
    def test_happy_path_returns_features_and_quote(self):
        df = _make_kline_df(90)
        realtime = {"885595": {"price": 1234.5, "change_pct": 1.23}}
        history = {"885595": df}
        manager = _mock_manager(realtime_results=realtime, history_results=history)

        with _patch_manager(manager), patch(
            "stock_data.data_provider.persistence.board.get_board_name_with_fallback",
            return_value="人形机器人",
        ):
            client = TestClient(_build_app())
            r = client.post(
                "/api/v1/agent/boards/batch-profile",
                json={"codes": ["885595"], "frequency": "d", "days": 60},
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["frequency"] == "d"
        assert body["days"] == 60
        assert len(body["boards"]) == 1
        board = body["boards"][0]
        assert board["code"] == "885595"
        assert board["name"] == "人形机器人"
        assert board["quote"] == {"price": 1234.5, "change_pct": 1.23}
        assert board["features"]["trend"]  # non-empty (90 bars → MA values)
        assert board["errors"] == {"quote": None, "features": None}
        assert body["summary"]["requested"] == 1
        assert body["summary"]["ok"] == 1

    def test_per_code_error_isolation(self):
        """One board fails on both quote + features; the other succeeds."""
        df_ok = _make_kline_df(90, seed=1)
        realtime = {
            "881270": {"price": 567.8, "change_pct": -0.45},
            "885595": DataFetchError("upstream timeout"),
        }
        history = {
            "881270": df_ok,
            "885595": DataFetchError("no K-line for this code"),
        }
        manager = _mock_manager(realtime_results=realtime, history_results=history)

        with _patch_manager(manager), patch(
            "stock_data.data_provider.persistence.board.get_board_name_with_fallback",
            side_effect=lambda code, source, manager=None: {"881270": "半导体", "885595": None}[code],
        ):
            client = TestClient(_build_app())
            r = client.post(
                "/api/v1/agent/boards/batch-profile",
                json={"codes": ["881270", "885595"], "frequency": "d"},
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert len(body["boards"]) == 2
        ok_board, bad_board = body["boards"]
        assert ok_board["code"] == "881270"
        assert ok_board["name"] == "半导体"
        assert ok_board["quote"] == {"price": 567.8, "change_pct": -0.45}
        assert ok_board["features"]["trend"]
        assert ok_board["errors"] == {"quote": None, "features": None}
        assert bad_board["code"] == "885595"
        assert bad_board["name"] == ""
        assert bad_board["quote"] is None
        assert bad_board["features"] is None
        assert "DataFetchError" in bad_board["errors"]["quote"]
        assert "DataFetchError" in bad_board["errors"]["features"]
        # summary: requested=2, ok=1 (the 881270 has at least one aspect)
        assert body["summary"] == {"requested": 2, "ok": 1, "failed": 1, "elapsed_ms": body["summary"]["elapsed_ms"]}

    def test_response_preserves_input_order(self):
        df = _make_kline_df(90, seed=2)
        realtime = {c: {"price": 1.0, "change_pct": 0.1} for c in ("881270", "885595", "883957")}
        history = {c: df for c in ("881270", "885595", "883957")}
        manager = _mock_manager(realtime_results=realtime, history_results=history)

        with _patch_manager(manager), patch(
            "stock_data.data_provider.persistence.board.get_board_name_with_fallback",
            side_effect=lambda code, source, manager=None: code,
        ):
            client = TestClient(_build_app())
            r = client.post(
                "/api/v1/agent/boards/batch-profile",
                json={"codes": ["883957", "881270", "885595"], "frequency": "d"},
            )
        body = r.json()
        assert [b["code"] for b in body["boards"]] == ["883957", "881270", "885595"]

    def test_unsupported_frequency_returns_422(self):
        client = TestClient(_build_app())
        r = client.post(
            "/api/v1/agent/boards/batch-profile",
            json={"codes": ["885595"], "frequency": "2h"},
        )
        assert r.status_code == 422  # Pydantic Literal catches it before the route

    def test_days_out_of_range_returns_422(self):
        client = TestClient(_build_app())
        r = client.post(
            "/api/v1/agent/boards/batch-profile",
            json={"codes": ["885595"], "frequency": "1m", "days": 10},  # 1m max=3
        )
        assert r.status_code == 422
        assert "days" in str(r.json()).lower()

    def test_empty_codes_returns_422(self):
        client = TestClient(_build_app())
        r = client.post(
            "/api/v1/agent/boards/batch-profile",
            json={"codes": []},
        )
        assert r.status_code == 422

    def test_too_many_codes_returns_422(self):
        client = TestClient(_build_app())
        r = client.post(
            "/api/v1/agent/boards/batch-profile",
            json={"codes": [f"88{i:04d}" for i in range(6)]},
        )
        assert r.status_code == 422

    def test_empty_kline_dataframe_yields_empty_features(self):
        """Empty DataFrame → build_features returns {} for all 3 blocks,
        handler wraps in BatchFeatures(...)."""
        empty_df = pd.DataFrame(
            {"date": [], "open": [], "high": [], "low": [], "close": [], "volume": [], "amount": [], "pct_chg": []}
        )
        realtime = {"885595": {"price": 1.0, "change_pct": 0.0}}
        history = {"885595": empty_df}
        manager = _mock_manager(realtime_results=realtime, history_results=history)

        with _patch_manager(manager), patch(
            "stock_data.data_provider.persistence.board.get_board_name_with_fallback",
            return_value=None,
        ):
            client = TestClient(_build_app())
            r = client.post(
                "/api/v1/agent/boards/batch-profile",
                json={"codes": ["885595"], "frequency": "d"},
            )
        assert r.status_code == 200, r.text
        body = r.json()
        board = body["boards"][0]
        # Empty DataFrame → trend/pivots/volume all default-empty.
        # ``quote`` succeeded, ``features`` succeeded (no exception raised),
        # so errors{} stays all-null and summary counts it as ok.
        assert board["features"] == {"trend": {}, "pivots": {}, "volume": {}}
        assert board["errors"] == {"quote": None, "features": None}
        assert body["summary"]["ok"] == 1

    def test_handler_does_not_touch_quote_cache(self):
        """Regression guard: the handler MUST NOT call cached_lookup / cached_store.
        Verifies the no-composite-cache decision from spec §5."""
        from stock_data.api import cache as api_cache

        df = _make_kline_df(90)
        realtime = {"885595": {"price": 1.0, "change_pct": 0.0}}
        history = {"885595": df}
        manager = _mock_manager(realtime_results=realtime, history_results=history)

        with _patch_manager(manager), patch(
            "stock_data.data_provider.persistence.board.get_board_name_with_fallback",
            return_value=None,
        ), patch.object(api_cache, "cached_lookup", wraps=api_cache.cached_lookup) as lookup_spy, patch.object(
            api_cache, "cached_store", wraps=api_cache.cached_store
        ) as store_spy:
            client = TestClient(_build_app())
            r = client.post(
                "/api/v1/agent/boards/batch-profile",
                json={"codes": ["885595"], "frequency": "d"},
            )
        assert r.status_code == 200
        # The handler MUST NOT use the composite agent cache layer.
        assert lookup_spy.call_count == 0, "cached_lookup was called; boards/batch-profile must NOT add a composite cache"
        assert store_spy.call_count == 0, "cached_store was called; boards/batch-profile must NOT add a composite cache"
```

Append a helper at the bottom of the test module:

```python
def _build_app():
    """Build the FastAPI app under test. Mirrors the pattern used by
    tests/test_agent_batch_features.py — direct construction to avoid the
    server-side lifespan side effects.
    """
    from stock_data.server import create_app

    return create_app()
```

- [ ] **Step 2: Run the handler tests to verify they fail**

Run:
```bash
.venv/Scripts/python.exe -m pytest tests/test_agent_boards_batch_profile.py::TestHandler -v
```

Expected: every `TestHandler` test fails with a 404 / ImportError / AttributeError (the route doesn't exist yet, the imports are missing).

- [ ] **Step 3: Implement the handler**

In `stock_data/api/routes/agent.py`:

(a) Add the new imports next to the existing schema imports (around line 70):

```python
from ..schemas import (
    # ... existing imports ...
    BoardsBatchProfileRequest,
    BoardsBatchProfileResponse,
    BoardProfile,
)
```

(Keep alphabetical if the existing block is alphabetised; check the file and merge in.)

(b) Append the handler below `post_stocks_batch_profile` (after line 978, before the `_stats_payload` helper):

```python
@router.post(
    "/agent/boards/batch-profile",
    response_model=BoardsBatchProfileResponse,
    responses={
        422: {"model": ErrorResponse, "description": "days out of range / unsupported frequency"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["agent"],
)
@endpoint_meta(
    summary="板块批量画像（trend/pivots/volume 计算指标 + 极简 realtime，THS 单源，单 frequency）",
    markets=["csi"],
    capabilities=[],
)
@map_errors
def post_boards_batch_profile(
    payload: BoardsBatchProfileRequest,
    format: str = Query(
        "json",
        pattern="^(json|md)$",
        description="Output format. json=application/json (default); md=text/markdown.",
    ),
) -> Response:
    """Per-board fan-out: minimal realtime quote + computed features at one frequency.

    Source is fixed to THS (only fetcher implementing ``get_board_realtime``;
    board codes are source-specific so cross-source fan-out would force
    callers to send one platecode per source anyway). ``board_type`` is
    NOT exposed to the caller — ``ThsFetcher.get_board_realtime`` resolves
    it from the stock_board cache with an internal fallback. Per-board
    failures land in ``boards[i].errors{}``; the rest of the response is
    still emitted. **No composite cache layer** (spec §5) — fetcher-level
    TTLs already cover N+1; this layer would only add a stale-risk window.
    """
    days = _resolve_and_validate_days(payload.frequency, payload.days)
    started = time.monotonic()
    manager = get_manager()
    profile = _FEATURE_FREQS[payload.frequency]
    fetch_days = max(days, profile.ma60_warmup_days)
    boards: list[BoardProfile] = []
    n_ok = 0

    for code in payload.codes:
        errors: dict[str, str | None] = {"quote": None, "features": None}
        quote = None
        features = None
        name = ""

        # --- realtime quote ---
        try:
            q, _src = manager.get_board_realtime(code, source="ths")
            if q is not None:
                quote = MinimalQuote(
                    price=q.get("price"),
                    change_pct=q.get("change_pct"),
                )
        except Exception as exc:
            logger.warning(
                f"[agent/boards/batch-profile] quote {code} failed: {exc}",
                exc_info=True,
            )
            errors["quote"] = f"{type(exc).__name__}: {exc}"

        # --- computed features ---
        try:
            df, _src = manager.get_board_history(
                code,
                source="ths",
                frequency=profile.mgr_frequency,
                days=fetch_days,
            )
            features = BatchFeatures(**build_features(df, frequency=payload.frequency, days=days))
        except Exception as exc:
            logger.warning(
                f"[agent/boards/batch-profile] features {code} {payload.frequency} failed: {exc}",
                exc_info=True,
            )
            errors["features"] = f"{type(exc).__name__}: {exc}"

        # --- name resolution (best-effort; helper swallows its own errors) ---
        name = stock_board_cache.get_board_name_with_fallback(code, "ths", manager=manager) or ""

        if quote is not None or features is not None:
            n_ok += 1
        boards.append(
            BoardProfile(
                code=code,
                name=name,
                quote=quote,
                features=features,
                errors=errors,
            )
        )

    result = BoardsBatchProfileResponse(
        frequency=payload.frequency,
        days=days,
        boards=boards,
        summary=_batch_summary(len(payload.codes), n_ok, started),
    )
    return _render_agent("boards/batch-profile", result, format)
```

- [ ] **Step 4: Run the handler tests to verify they pass**

Run:
```bash
.venv/Scripts/python.exe -m pytest tests/test_agent_boards_batch_profile.py::TestHandler -v
```

Expected: all 9 `TestHandler` tests PASS.

- [ ] **Step 5: Commit**

```bash
git add stock_data/api/routes/agent.py tests/test_agent_boards_batch_profile.py
git commit -m "feat(agent): add POST /agent/boards/batch-profile (THS boards, no composite cache)"
```

---

### Task 3: MD template `render_boards_batch_profile_as_md` + `_MD_TEMPLATES` registration

**Files:**
- Modify: `stock_data/api/routes/agent.py` (add 1 template function + 1 `_MD_TEMPLATES` line)
- Test: `tests/test_agent_boards_batch_profile.py` (append `TestMarkdown` class)

**Interfaces:**
- Consumes:
  - `BoardsBatchProfileResponse` (Tasks 1-2).
  - Existing `_md_num`, `_md_pct`, `_md_feature_block`, `_render_dict_block` (already imported in `agent.py`).
- Produces:
  - `render_boards_batch_profile_as_md(p: BoardsBatchProfileResponse) -> str`
  - `_MD_TEMPLATES["boards/batch-profile"] = render_boards_batch_profile_as_md`

- [ ] **Step 1: Write the failing MD test**

Append to `tests/test_agent_boards_batch_profile.py`:

```python
class TestMarkdown:
    def test_md_renders_full_payload(self):
        from stock_data.api.routes.agent import render_boards_batch_profile_as_md
        from stock_data.api.schemas import (
            BoardsBatchProfileResponse,
            BoardProfile,
            MinimalQuote,
        )
        from stock_data.data_provider.features.build import build_features
        from stock_data.data_provider.features.pivots import PivotFeatures
        from stock_data.data_provider.features.trend import TrendFeatures
        from stock_data.data_provider.features.volume import VolumeFeatures

        df = _make_kline_df(90)
        resp = BoardsBatchProfileResponse(
            frequency="d",
            days=60,
            boards=[
                BoardProfile(
                    code="885595",
                    name="人形机器人",
                    quote=MinimalQuote(price=1234.5, change_pct=1.23),
                    features=BatchFeatures(**build_features(df, frequency="d", days=60)),
                    errors={"quote": None, "features": None},
                ),
            ],
            summary={"requested": 1, "ok": 1, "failed": 0, "elapsed_ms": 100},
        )
        md = render_boards_batch_profile_as_md(resp)
        assert "# 板块批量画像 — d 60d" in md
        assert "## 885595 人形机器人 ✓" in md
        assert "1,234.50" in md
        assert "+1.23%" in md
        assert "### 指标" in md
        # Summary block
        assert "## 汇总" in md

    def test_md_empty_features_render_explicit_marker(self):
        """Empty feature block → '（无数据）' marker (NOT a bare | 字段 | skeleton)."""
        from stock_data.api.routes.agent import render_boards_batch_profile_as_md
        from stock_data.api.schemas import BoardsBatchProfileResponse, BoardProfile, MinimalQuote
        from stock_data.data_provider.features.build import build_features

        empty_df = pd.DataFrame(
            {"date": [], "open": [], "high": [], "low": [], "close": [], "volume": [], "amount": [], "pct_chg": []}
        )
        resp = BoardsBatchProfileResponse(
            frequency="d",
            days=60,
            boards=[
                BoardProfile(
                    code="885595",
                    name="",
                    quote=MinimalQuote(price=1.0, change_pct=0.0),
                    features=BatchFeatures(**build_features(empty_df, frequency="d", days=60)),
                    errors={"quote": None, "features": None},
                ),
            ],
            summary={"requested": 1, "ok": 1, "failed": 0, "elapsed_ms": 1},
        )
        md = render_boards_batch_profile_as_md(resp)
        # Each empty block renders the dedicated marker
        assert "（无数据）" in md
        # Defensive: NO bare |---| separator with zero data rows under it
        # (a separator with only whitespace / nothing after it is the
        # exact regression we are guarding against — see CLAUDE.md MD contract)
        lines = md.splitlines()
        for i, line in enumerate(lines):
            if line.strip().startswith("|---"):
                # The NEXT non-blank line must contain either data OR a
                # known no-data marker.
                next_nonblank = next(
                    (ln for ln in lines[i + 1 :] if ln.strip()),
                    "",
                )
                assert (
                    next_nonblank.startswith("|")
                    or "（无" in next_nonblank
                    or next_nonblank.startswith("#")
                ), f"Bare header+separator with no data row: {line!r} → {next_nonblank!r}"

    def test_md_no_swings_marker(self):
        """No confirmed pivots → '（无确认摆动点）' marker (NOT bare header)."""
        from stock_data.api.routes.agent import render_boards_batch_profile_as_md
        from stock_data.api.schemas import BoardsBatchProfileResponse, BoardProfile, MinimalQuote
        from stock_data.data_provider.features.build import build_features

        empty_df = pd.DataFrame(
            {"date": [], "open": [], "high": [], "low": [], "close": [], "volume": [], "amount": [], "pct_chg": []}
        )
        resp = BoardsBatchProfileResponse(
            frequency="d",
            days=60,
            boards=[
                BoardProfile(
                    code="881270",
                    name="半导体",
                    quote=MinimalQuote(price=2.0, change_pct=0.5),
                    features=BatchFeatures(**build_features(empty_df, frequency="d", days=60)),
                    errors={"quote": None, "features": None},
                ),
            ],
            summary={"requested": 1, "ok": 1, "failed": 0, "elapsed_ms": 1},
        )
        md = render_boards_batch_profile_as_md(resp)
        assert "（无确认摆动点）" in md

    def test_md_per_entry_failure_marker(self):
        """Entry whose features failed renders the failure reason in the heading."""
        from stock_data.api.routes.agent import render_boards_batch_profile_as_md
        from stock_data.api.schemas import BoardsBatchProfileResponse, BoardProfile

        resp = BoardsBatchProfileResponse(
            frequency="d",
            days=60,
            boards=[
                BoardProfile(
                    code="885595",
                    name="人形机器人",
                    quote=None,
                    features=None,
                    errors={"quote": "DataFetchError: network timeout", "features": "DataFetchError: no K-line"},
                ),
            ],
            summary={"requested": 1, "ok": 0, "failed": 1, "elapsed_ms": 100},
        )
        md = render_boards_batch_profile_as_md(resp)
        assert "## 885595 人形机器人 ✗" in md  # ✗ because both aspects failed
        assert "DataFetchError: network timeout" in md
        assert "DataFetchError: no K-line" in md
```

- [ ] **Step 2: Run the MD tests to verify they fail**

Run:
```bash
.venv/Scripts/python.exe -m pytest tests/test_agent_boards_batch_profile.py::TestMarkdown -v
```

Expected: all 4 tests fail with `ImportError: cannot import name 'render_boards_batch_profile_as_md'`.

- [ ] **Step 3: Implement the MD template**

In `stock_data/api/routes/agent.py`, append the template function near the other `render_*_as_md` functions (right before `render_indices_batch_profile_as_md` to keep the family together):

```python
def render_boards_batch_profile_as_md(p: BoardsBatchProfileResponse) -> str:
    out = [f"# 板块批量画像 — {p.frequency} {p.days}d", ""]
    for board in p.boards:
        ok_marker = "✓" if (board.quote or board.features) else "✗"
        out.append(f"## {board.code} {board.name} {ok_marker}")
        if board.quote:
            out.append(
                f"- 最新: {_md_num(board.quote.price)} ({_md_pct(board.quote.change_pct)})"
            )
        else:
            err = (board.errors or {}).get("quote") or "no quote"
            out.append(f"- 行情失败: {err}")
        out.append("")
        if board.features:
            _md_feature_block(out, board.features)
        else:
            err = (board.errors or {}).get("features") or "no features"
            out.append(f"### 指标 — 失败: {err}")
            out.append("")
    s = p.summary or {}
    out.append(
        f"## 汇总 — requested {s.get('requested', '?')}, "
        f"ok {s.get('ok', '?')}, failed {s.get('failed', '?')}, "
        f"elapsed {s.get('elapsed_ms', '?')}ms"
    )
    return "\n".join(out)
```

Then add one line to `_MD_TEMPLATES` (alongside the indices entry):

```python
_MD_TEMPLATES: dict[str, Callable] = {
    # ... existing entries ...
    "boards/batch-profile": render_boards_batch_profile_as_md,
}
```

- [ ] **Step 4: Run the MD tests to verify they pass**

Run:
```bash
.venv/Scripts/python.exe -m pytest tests/test_agent_boards_batch_profile.py::TestMarkdown -v
```

Expected: all 4 tests PASS.

- [ ] **Step 5: Run the full new test file + lint**

```bash
.venv/Scripts/python.exe -m pytest tests/test_agent_boards_batch_profile.py -v
.venv/Scripts/python.exe -m ruff check stock_data/api/routes/agent.py stock_data/api/schemas.py tests/test_agent_boards_batch_profile.py
.venv/Scripts/python.exe -m ruff format stock_data/api/routes/agent.py stock_data/api/schemas.py tests/test_agent_boards_batch_profile.py
```

Expected: all tests pass; ruff clean (or only pre-existing warnings on unrelated lines).

- [ ] **Step 6: Commit**

```bash
git add stock_data/api/routes/agent.py tests/test_agent_boards_batch_profile.py
git commit -m "feat(agent): add MD projection for /agent/boards/batch-profile"
```

---

### Task 4: Docs — `CLAUDE.md` table + proposal §3.2.4

**Files:**
- Modify: `CLAUDE.md` (add 1 row to Agent Batch API table + 1 design-contract bullet)
- Modify: `docs/agent-batch-api-proposal-2026-07-27.md` (append §3.2.4)

**Interfaces:** None (docs only).

- [ ] **Step 1: Update CLAUDE.md**

In `CLAUDE.md`, find the Agent Batch API table (under `## Agent Batch API (\`/api/v1/agent/*\`)`). Add one row at the bottom of the table (before the `### Design contract` subsection):

```markdown
| `POST /agent/boards/batch-profile` | Per-board fan-out: 极简 realtime quote + 单 frequency 计算特征 (`trend`/`pivots`/`volume`)。1-5 THS platecodes, 单 frequency。 | per-code `manager.get_board_realtime` + `manager.get_board_history` (THS 单源, fetcher 自动推断 board_type), then `features.build_features()` |
```

Then find the bullet list under `### Design contract (don't violate these without a spec change)`. Add one bullet (place it next to the cache-related bullets to group logically):

```markdown
- **`/agent/boards/batch-profile` has NO composite cache layer** — by design (spec §5). The fetcher-level `get_quote_cache` + `get_history_cache` already cover N+1 fan-out; a composite cache here would only add a stale-risk window. Stocks / indices batch-profile DO have a composite cache today (legacy design); their removal is tracked as a separate follow-up — do NOT bundle into a boards/batch-profile change.
```

- [ ] **Step 2: Append §3.2.4 to the agent-batch-api proposal**

In `docs/agent-batch-api-proposal-2026-07-27.md`, append a new section at the end (or under the §3.2 series):

```markdown
### §3.2.4 `boards/batch-profile` (added 2026-08-27)

Per-board fan-out endpoint added to complete the asset-class coverage
of the batch-profile family (stocks / indices → boards). Source is fixed
to `ths` because board codes are source-specific (THS platecode 885xxx /
881xxx vs EastMoney BKxxxx) and only THS implements `get_board_realtime`.
`board_type` (concept vs industry) is auto-detected by `ThsFetcher` from
the `stock_board` cache + internal fallback; not exposed to the caller.

**Response shape**: identical to `/agent/indices/batch-profile`
(`{frequency, days, boards[i].{code,name,quote,features,errors{}}, summary}`),
with `boards[i].code` being a THS platecode instead of an index code.

**Caching**: **NO composite cache layer** — this is a deliberate
deviation from stocks/indices batch-profile (see spec §5). Rationale:
fetcher-level TTLs already absorb the N+1 fan-out, and a composite
cache would add a 60s-stale risk on intraday board data. Reverting
this for stocks/indices is tracked as §8.1 Future Work in the spec.

**No new helper introduced** — the handler mirrors `get_indices_batch_profile`
exactly (same 2-aspect loop, same errors-dict shape), only swapping the
data sources. A `_aspect_try`-style helper was considered and rejected
because stocks and indices use incompatible error containers (dict vs
list).
```

- [ ] **Step 3: Verify changes**

```bash
git diff CLAUDE.md docs/agent-batch-api-proposal-2026-07-27.md
```

Expected: both diffs visible; the new content matches what was added.

- [ ] **Step 4: Run the full new test file + the related batch-profile test files**

```bash
.venv/Scripts/python.exe -m pytest tests/test_agent_boards_batch_profile.py tests/test_agent_batch_features.py tests/test_agent_endpoints.py -v
```

Expected: all three test files PASS (no test in the related family is broken by the schema additions or the new `_MD_TEMPLATES` entry).

- [ ] **Step 5: Run the lint + the agent endpoint smoke test**

```bash
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m ruff format .
.venv/Scripts/python.exe -m pytest tests/test_agent_endpoints.py::TestFormatMdDataCompleteness -v 2>&1 || true
```

Expected: ruff clean. (The `TestFormatMdDataCompleteness` test may not exist or may pass already — run it to confirm the format-md contract tests still pass with the new endpoint; adjust if they reference specific endpoint lists.)

- [ ] **Step 6: Commit**

```bash
git add CLAUDE.md docs/agent-batch-api-proposal-2026-07-27.md
git commit -m "docs: document POST /agent/boards/batch-profile in CLAUDE.md + proposal"
```

---

## Self-Review (author checklist before execution)

1. **Spec coverage** —
   - §2 Public API → Tasks 1 (schemas) + 2 (handler) + 3 (MD)
   - §3 Data flow → Task 2 (per-code loop)
   - §4 Validation + error model → Task 2 tests (`unsupported_frequency`, `days_out_of_range`, `empty_codes`, `too_many_codes`)
   - §5 Caching (no composite cache) → Task 2 `test_handler_does_not_touch_quote_cache` regression guard
   - §6 Code reuse matrix → Task 2 uses only the documented helpers (no new ones)
   - §7 File-level changes → Tasks 1-4 hit every file listed
   - §8 Future Work → §3.2.4 in Task 4 calls out §8.1 explicitly
2. **Placeholder scan** — no TBD / TODO / "implement later" anywhere.
3. **Type consistency** —
   - `manager.get_board_realtime(code, source="ths")` returns `tuple[dict, str]`; handler unpacks as `(q, _src)`. ✓
   - `manager.get_board_history(code, source="ths", frequency=..., days=...)` returns `tuple[list[dict], str]`; handler unpacks as `(df, _src)` and feeds to `build_features`. ✓
   - `stock_board_cache.get_board_name_with_fallback(code, "ths", manager=manager)` returns `str | None`; handler does `or ""`. ✓
   - `BatchFeatures(**build_features(df, frequency=..., days=...))` matches `build_features` return shape. ✓
   - `_FEATURE_FREQS[frequency].mgr_frequency` used at the manager boundary (not `frequency` raw). ✓
   - `fetch_days = max(days, profile.ma60_warmup_days)` matches indices/stocks. ✓
4. **No new helper introduced** — confirmed (handler mirrors `get_indices_batch_profile`).
5. **No new cache key factory** — confirmed (`api/cache.py` not in any task).