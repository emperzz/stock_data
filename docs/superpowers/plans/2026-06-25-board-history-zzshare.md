# Board K-Line (zzshare) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the `/api/v1/boards/{board_code}/history` 501 stub with a working ZzshareFetcher implementation; remove the EastMoney / Zhitu placeholder methods; rewire the route to call through the manager.

**Architecture:** Single-source board K-line. Zzshare's `plate_kline(b_code, date1, date2)` returns the upstream DataFrame → normalize to STANDARD_COLUMNS → return `BoardKlineResponse` (new schema, KLineData rows). EastMoney and Zhitu have no upstream board-K-line API (per their own docstrings); remove their stub methods entirely. The explorer manifest will then list only ZzshareFetcher under this endpoint.

**Tech Stack:** Python 3.x, FastAPI, zzshare SDK (`plate_kline`), pandas, pytest, MagicMock for unit tests.

---

## File Structure

**Modify (no new files unless noted):**
- `stock_data/data_provider/fetchers/zzshare_fetcher.py:534-541` — replace `get_board_history` stub with real implementation using `api.plate_kline`.
- `stock_data/data_provider/fetchers/eastmoney_fetcher.py:1368-1379` — delete `get_board_history` stub.
- `stock_data/data_provider/fetchers/zhitu_fetcher.py:663-674` — delete `get_board_history` stub.
- `stock_data/data_provider/manager.py:748-768` — extend `get_board_history` signature to accept `start_date` / `end_date`, pass them through to fetcher.
- `stock_data/api/routes/boards.py:375-409` — remove 501 short-circuit; restrict `source` Literal to `["zzshare"]`; narrow `frequency` to `["d"]`; set `response_model=BoardKlineResponse`; resolve `start_date`/`end_date`/`days` into a date range; call manager; reshape result.
- `stock_data/api/schemas.py` — add `BoardKlineResponse` (NEW Pydantic model) alongside `StockHistoryResponse`.

**Tests (modify):**
- `tests/test_zzshare_fetcher.py:888-891` — replace `test_get_board_history_raises_not_implemented` with 4 real implementation tests.
- `tests/test_eastmoney_fetcher_board.py:404-409` — delete `test_get_board_history_raises_not_implemented`.
- `tests/test_zhitu_fetcher_board.py:111-116` — delete `test_get_board_history_raises_not_implemented`.
- `tests/test_boards_api.py:297-305` — replace 501 tests with 4 working-flow tests.

**Docs:**
- `docs/zzshare/01-kline.md` — already documents `plate_kline`; no change.
- `CLAUDE.md:268` — table row for `get_board_history` currently says "ZzshareFetcher P5" already; no edit needed. But the placeholder-summary description on the endpoint disappears after the route change.

---

## Background facts the engineer needs

1. **Upstream signature** (`docs/zzshare/01-kline.md` §3):
   - `api.plate_kline(b_code: str, date1: str = "", date2: str = "")`
   - `date1` / `date2` are `YYYYMMDD` (no dashes).
   - Returns a DataFrame; **column names are not documented** (docs say "列由后端决定（plate_kline_to_df 兼容多种日期列名）"). **Task 1 probes the real shape before implementation**.

2. **Outbound vs inbound code format** (CLAUDE.md, "Don't leak the outbound `ts_code` suffix"):
   - Zzshare SDK wants `b_code` directly. For board codes from zzshare's own board-list endpoint (e.g. `801001` 芯片, `881121` 半导体), no transformation is needed — pass as-is.
   - The user passes a `board_code` to the API; we forward verbatim to `b_code`. No cross-source translation (consistent with the rest of the board API where the user picks a source and passes source-specific codes).

3. **Frequencies**: Zzshare's `plate_kline` is daily-only. The current route accepts `Literal["d", "w", "m"]`. We'll narrow to `Literal["d"]` (Task 5). This is honest — fake "support" for w/m would 400 every other call.

4. **Manager routing**: `DataFetcherManager.get_board_history(...)` already uses `_with_source(source=...)` which looks up `manager._fetchers` by name and calls `f.get_board_history(...)`. No changes to the failover semantics — board endpoints are intentionally source-routed (CLAUDE.md).

5. **`safe_float` / `safe_int`** (`stock_data/data_provider/core/types.py`) — use these for upstream values that may be `None` or strings. Don't use plain `float()` / `int()`.

---

## Task 1: Probe upstream `plate_kline` response shape

**Files:** none (read-only probe via `.venv/Scripts/python.exe`).

The SDK docs explicitly say columns are not stable. We must probe a real call to know what we're normalizing against. Without this, the fetcher is guessing.

- [ ] **Step 1: Run probe script**

Create `scratch/probe_plate_kline.py`:

```python
"""Scratch probe — DO NOT COMMIT."""
from zzshare.client import DataApi
import pandas as pd

api = DataApi()  # anonymous; rate-limited but enough for probe
df = api.plate_kline(b_code="883957", date1="20260515", date2="20260520")
print("TYPE:", type(df).__name__)
print("SHAPE:", df.shape)
print("DTYPES:")
print(df.dtypes)
print("HEAD:")
print(df.head(3).to_string())
print("COLUMNS:", list(df.columns))
print("INDEX:", df.index.name, type(df.index).__name__)
```

Run:

```bash
.venv/Scripts/python.exe scratch/probe_plate_kline.py
```

- [ ] **Step 2: Record findings in `docs/zzshare/01-kline.md` §3 "返回" section**

Append the discovered schema to the section under "### 返回". Example placeholder:

```markdown
### 返回（实测 2026-06-25）

DataFrame 列（以 `plate_kline(b_code='883957', date1='20260515', date2='20260520')` 实测）:

| 字段 | dtype | 说明 |
|---|---|---|
| `<date>` | str / datetime | 日期列（具体列名由后端决定，见 probe） |
| `open` / `high` / `low` / `close` | float | OHLC |
| ... | ... | （按实际填写） |

排序：`<observed>`（升 / 降）。
```

If `df` is empty / the call fails, try a different `b_code` (`801001`, `881121`) or widen the date range. If all probes fail, raise to the user — the plan cannot proceed without the schema.

- [ ] **Step 3: Delete `scratch/probe_plate_kline.py`** — never commit scratch.

---

## Task 2: Add `BoardKlineResponse` Pydantic model

**Files:**
- Modify: `stock_data/api/schemas.py` (add after `BoardStocksResponse` ~line 316)

- [ ] **Step 1: Write failing test**

In `tests/test_boards.py` `class TestBoardSchemas` (around line 267), add:

```python
def test_board_kline_response_serializes_zhongzheng_shape(self):
    """BoardKlineResponse wraps KLineData[] and exposes source."""
    from stock_data.api.schemas import BoardKlineResponse, KLineData

    r = BoardKlineResponse(
        board_code="883957",
        board_name="同花顺全A",
        period="daily",
        data=[
            KLineData(
                date="2026-05-20",
                open=100.0, high=105.0, low=99.0, close=104.0,
                volume=1_000_000, amount=104_000_000.0, change_percent=4.0,
            ),
        ],
        source="ZzshareFetcher",
    )
    out = r.model_dump()
    assert out["board_code"] == "883957"
    assert out["board_name"] == "同花顺全A"
    assert out["period"] == "daily"
    assert out["source"] == "ZzshareFetcher"
    assert len(out["data"]) == 1
    assert out["data"][0]["date"] == "2026-05-20"
    # Conditional serialization: indicator keys absent when None
    assert "ma5" not in out["data"][0]
    assert "indicators" not in out["data"][0]
```

- [ ] **Step 2: Run to confirm it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_boards.py::TestBoardSchemas::test_board_kline_response_serializes_zhongzheng_shape -v`
Expected: `ImportError` / `AttributeError: module 'stock_data.api.schemas' has no attribute 'BoardKlineResponse'`.

- [ ] **Step 3: Add the schema**

Insert after `class BoardStocksResponse(BaseModel):` (around line 309), before `class StockBoardInfo`:

```python
class BoardKlineResponse(BaseModel):
    """Response for board K-line endpoint (`/boards/{board_code}/history`)."""

    board_code: str = Field(description="Board code (source-specific, e.g. '883957' for zzshare)")
    board_name: str = Field(default="", description="Board name (best-effort lookup; may be empty)")
    period: str = Field(default="daily", description="K-line period (always 'daily' for now)")
    data: list[KLineData] = Field(default_factory=list, description="K-line data points")
    source: str = Field(
        default="",
        description="数据来源 fetcher 名 (目前固定为 'ZzshareFetcher')",
    )
```

- [ ] **Step 4: Run to confirm it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_boards.py::TestBoardSchemas::test_board_kline_response_serializes_zhongzheng_shape -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add stock_data/api/schemas.py tests/test_boards.py
git commit -m "feat(api): add BoardKlineResponse schema for /boards/{code}/history"
```

---

## Task 3: Implement `ZzshareFetcher.get_board_history`

**Files:**
- Modify: `stock_data/data_provider/fetchers/zzshare_fetcher.py:534-541` (replace stub)

This is the centerpiece. The stub raises `NotImplementedError`; we replace it with a real implementation.

The fetcher signature stays consistent with the rest of the file's STOCK_BOARD methods (matches `EastMoneyFetcher.get_board_history`'s accepted kwargs):

```python
def get_board_history(
    self,
    board_code: str,
    frequency: str = "d",
    days: int = 30,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    source: str | None = None,
    **kwargs,
) -> list[dict]:
    """..."""
```

`source` and `**kwargs` are accepted (ignored) to match the manager's call shape (`manager.py:761-764` passes `source=`, plus future-proof for `frequency`/`days` not passed by route).

- [ ] **Step 1: Replace the stub with a date-range helper + failing implementation**

Replace the entire `get_board_history` method body. Use the column names discovered in Task 1; this template shows the structure with placeholder column names — substitute the real ones once Task 1 completes:

```python
def get_board_history(
    self,
    board_code: str,
    frequency: str = "d",
    days: int = 30,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    source: str | None = None,
    **kwargs,
) -> list[dict]:
    """K-line for a board via zzshare ``plate_kline``.

    Daily-only. ``start_date`` / ``end_date`` take precedence over ``days``
    (when both null, defaults to the most-recent ``days`` calendar days).
    ``source`` and ``frequency`` are accepted for signature parity with
    other fetchers / the manager call shape but ignored (zzshare has no
    per-stock concept of board-source routing and is daily-only).
    """
    if frequency != "d":
        raise DataFetchError(
            f"ZzshareFetcher 板块 K 线仅支持日线 (frequency={frequency!r})"
        )
    api = self._ensure_api()
    if api is None:
        raise DataFetchError(
            f"ZzshareFetcher zzshare SDK 不可用: {self._init_error}"
        )

    # Date range: start_date/end_date win; else last `days` calendar days
    end_d = (
        datetime.strptime(end_date, "%Y-%m-%d").date()
        if end_date else date.today()
    )
    if start_date:
        start_d = datetime.strptime(start_date, "%Y-%m-%d").date()
    else:
        start_d = end_d - timedelta(days=days)
    date1 = start_d.strftime("%Y%m%d")
    date2 = end_d.strftime("%Y%m%d")

    try:
        df = api.plate_kline(b_code=board_code, date1=date1, date2=date2)
    except Exception as e:
        raise DataFetchError(
            f"plate_kline({board_code!r}, {date1}-{date2}) failed: {e}"
        ) from e

    if df is None or df.empty:
        return []

    df = df.copy()
    # ---- normalize: <substitute real column names from Task 1> ----
    # Date column rename (one of these, depending on actual upstream):
    for date_col in ("trade_date", "date", "datetime"):
        if date_col in df.columns and date_col != "date":
            df = df.rename(columns={date_col: "date"})
            break
    if "date" in df.columns:
        df["date"] = df["date"].astype(str).apply(_from_yyyymmdd)

    # Volume column rename:
    if "vol" in df.columns:
        df = df.rename(columns={"vol": "volume"})

    # Sort ascending by date so the response is oldest -> newest (matches
    # stock-history convention):
    if "date" in df.columns:
        df = df.sort_values("date").reset_index(drop=True)

    keep = [
        c for c in [
            "date", "open", "high", "low", "close", "volume", "amount",
            "pct_chg",
        ] if c in df.columns
    ]
    df = df[keep]
    return df.to_dict(orient="records")
```

- [ ] **Step 2: Write failing test for date-range resolution + SDK call**

In `tests/test_zzshare_fetcher.py`, inside `class TestBoards` (line 795), replace `test_get_board_history_raises_not_implemented` (lines 888-891) with:

```python
def test_get_board_history_calls_plate_kline_with_yyyymmdd_range(self):
    """start_date/end_date win; YYYYMMDD conversion happens."""
    df_mock = pd.DataFrame({
        "trade_date": ["20260515", "20260520"],
        "open": [1.0, 2.0], "high": [1.1, 2.1], "low": [0.9, 1.9],
        "close": [1.05, 2.05], "vol": [100, 200], "amount": [105.0, 410.0],
    })
    fetcher = self._fetcher_with_api(plate_kline=df_mock)
    fetcher.get_board_history(
        "883957", start_date="2026-05-15", end_date="2026-05-20",
    )
    call = fetcher._api.plate_kline.call_args
    assert call.kwargs.get("b_code") == "883957"
    assert call.kwargs.get("date1") == "20260515"
    assert call.kwargs.get("date2") == "20260520"


def test_get_board_history_uses_days_when_no_dates(self):
    """When start_date is None, fall back to end_date - days."""
    df_mock = pd.DataFrame({"trade_date": ["20260620"], "close": [1.0]})
    fetcher = self._fetcher_with_api(plate_kline=df_mock)
    fetcher.get_board_history("883957", days=7)
    call = fetcher._api.plate_kline.call_args
    # days=7 with no end_date → end_date defaults to today; start = today-7
    from datetime import date, timedelta
    today = date.today()
    assert call.kwargs.get("date2") == today.strftime("%Y%m%d")
    assert call.kwargs.get("date1") == (today - timedelta(days=7)).strftime("%Y%m%d")


def test_get_board_history_normalizes_to_standard_columns(self):
    """Response rows use date/volume (not trade_date/vol) + YYYY-MM-DD dates."""
    df_mock = pd.DataFrame({
        "trade_date": ["20260520"],
        "open": [1.0], "high": [1.1], "low": [0.9], "close": [1.05],
        "vol": [100], "amount": [105.0], "pct_chg": [5.0],
    })
    fetcher = self._fetcher_with_api(plate_kline=df_mock)
    rows = fetcher.get_board_history("883957", start_date="2026-05-20", end_date="2026-05-20")
    assert len(rows) == 1
    assert rows[0]["date"] == "2026-05-20"     # YYYY-MM-DD, not YYYYMMDD
    assert rows[0]["volume"] == 100             # renamed from vol
    assert rows[0]["open"] == 1.0
    assert rows[0]["close"] == 1.05


def test_get_board_history_rejects_weekly_frequency(self):
    """Non-daily frequency is a user-input error → DataFetchError."""
    fetcher = ZzshareFetcher()
    with pytest.raises(DataFetchError, match="仅支持日线"):
        fetcher.get_board_history("883957", frequency="w", days=30)
```

Add to the imports at the top of the test file:

```python
import pandas as pd
```

- [ ] **Step 3: Run to confirm new tests pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_zzshare_fetcher.py::TestBoards -v`
Expected: 4 PASS, 0 FAIL (the old `test_get_board_history_raises_not_implemented` is gone, the 4 new ones pass).

- [ ] **Step 4: Commit**

```bash
git add stock_data/data_provider/fetchers/zzshare_fetcher.py tests/test_zzshare_fetcher.py
git commit -m "feat(zzshare): implement get_board_history via plate_kline"
```

---

## Task 4: Remove EastMoneyFetcher / ZhituFetcher `get_board_history` stubs

**Files:**
- Modify: `stock_data/data_provider/fetchers/eastmoney_fetcher.py:1368-1379` (delete method)
- Modify: `stock_data/data_provider/fetchers/zhitu_fetcher.py:663-674` (delete method)
- Modify: `tests/test_eastmoney_fetcher_board.py:404-409` (delete test)
- Modify: `tests/test_zhitu_fetcher_board.py:111-116` (delete test)

Removing the methods means the manifest builder (`explorer/manifest.py:_resolve_fetchers` line 360-362) will skip these fetchers when STOCK_BOARD is paired with `fetcher_method="get_board_history"`, because `getattr(instance, effective_method, None)` returns `None`. The endpoint will list only ZzshareFetcher in its backend panel — exactly what we want.

- [ ] **Step 1: Delete EastMoneyFetcher method**

In `eastmoney_fetcher.py`, delete lines 1368-1379 (the entire `get_board_history` method, including its 1-line preceding blank if needed).

- [ ] **Step 2: Delete ZhituFetcher method**

In `zhitu_fetcher.py`, delete lines 663-674 (the entire `get_board_history` method).

- [ ] **Step 3: Delete the obsolete stub tests**

In `tests/test_eastmoney_fetcher_board.py`, delete lines 404-409 (`test_get_board_history_raises_not_implemented`).

In `tests/test_zhitu_fetcher_board.py`, delete lines 111-116 (`test_get_board_history_raises_not_implemented`).

- [ ] **Step 4: Run full test_boards / test_eastmoney_fetcher_board / test_zhitu_fetcher_board suites**

Run:

```bash
.venv/Scripts/python.exe -m pytest tests/test_eastmoney_fetcher_board.py tests/test_zhitu_fetcher_board.py tests/test_boards.py -v
```

Expected: all PASS. If `test_boards.py` or another file references `EastMoneyFetcher.get_board_history` / `ZhituFetcher.get_board_history` (e.g. capability-coverage assertions), fix those references too. The pattern to check: `grep -rn 'get_board_history' stock_data tests` should only show ZzshareFetcher, the manager, and the route after this step.

- [ ] **Step 5: Commit**

```bash
git add stock_data/data_provider/fetchers/eastmoney_fetcher.py stock_data/data_provider/fetchers/zhitu_fetcher.py tests/test_eastmoney_fetcher_board.py tests/test_zhitu_fetcher_board.py
git commit -m "refactor: drop board-K-line stubs on EastMoney/Zhitu (no upstream API)"
```

---

## Task 5: Extend `DataFetcherManager.get_board_history` to accept date range

**Files:**
- Modify: `stock_data/data_provider/manager.py:748-768`

The manager currently has `(board_code, source, frequency="d", days=30)`. The route needs to pass `start_date` / `end_date` through too. We extend the signature; existing callers (just the route) are updated in Task 6.

- [ ] **Step 1: Update manager signature + call shape**

Replace lines 748-768 of `manager.py` with:

```python
def get_board_history(
    self,
    board_code: str,
    source: str,
    frequency: str = "d",
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    days: int = 30,
) -> tuple[list[dict], str]:
    """Get K-line for a board from the named source (zzshare only).

    `start_date` / `end_date` (YYYY-MM-DD) take precedence over `days`.
    Source-routed (no failover) per CLAUDE.md — board classification
    systems differ across sources.
    """
    result, name = self._with_source(
        source=source,
        capability=DataCapability.STOCK_BOARD,
        market="csi",
        op_label=f"board K-line {board_code} ({source})",
        call=lambda f: (
            f.get_board_history(
                board_code,
                frequency=frequency,
                days=days,
                start_date=start_date,
                end_date=end_date,
                source=source,
            ),
            f.name,
        ),
    )
    return result, name
```

- [ ] **Step 2: Write manager-level test**

In `tests/test_boards.py` (or a new `tests/test_board_source_routing.py` if one already exists — it does, see line 56), inside the appropriate class, add:

```python
def test_manager_passes_date_range_to_fetcher(self):
    """start_date/end_date/days are forwarded verbatim to fetcher."""
    from stock_data.data_provider.manager import DataFetcherManager
    captured_kwargs = {}

    class FakeFetcher:
        name = "FakeFetcher"
        supported_data_types = DataCapability.STOCK_BOARD
        supported_markets = {"csi"}
        priority = 5

        def get_board_history(self, board_code, **kwargs):
            captured_kwargs.update(kwargs)
            return [{"date": "2026-05-20", "close": 1.0}]

    manager = DataFetcherManager()
    manager.add_fetcher(FakeFetcher())
    rows, name = manager.get_board_history(
        "883957", source="FakeFetcher",
        start_date="2026-05-15", end_date="2026-05-20", days=30,
    )
    assert captured_kwargs["start_date"] == "2026-05-15"
    assert captured_kwargs["end_date"] == "2026-05-20"
    assert captured_kwargs["days"] == 30
    assert captured_kwargs["source"] == "FakeFetcher"
```

(The `add_fetcher` / source-routing shape mirrors `tests/test_board_source_routing.py`. Adjust class name / fixtures to match that file's existing conventions.)

- [ ] **Step 3: Run to confirm it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_board_source_routing.py -v`
Expected: PASS (existing 6 tests + new one).

- [ ] **Step 4: Commit**

```bash
git add stock_data/data_provider/manager.py tests/test_board_source_routing.py
git commit -m "feat(manager): pass start_date/end_date through get_board_history"
```

---

## Task 6: Rewire the route

**Files:**
- Modify: `stock_data/api/routes/boards.py:375-409`

Replace the 501 stub with a real handler. Restrict the source Literal, narrow frequency, resolve the date range, call the manager, reshape to `BoardKlineResponse`.

- [ ] **Step 1: Replace the route decorator + handler**

Replace lines 375-409 of `boards.py` with:

```python
@router.get(
    "/boards/{board_code}/history",
    response_model=BoardKlineResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid source / frequency"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["boards"],
)
@endpoint_meta(
    summary="板块 K 线（日线，ZZSHARE）",
    markets=["csi"],
    capabilities=["STOCK_BOARD"],
    fetcher_method="get_board_history",
)
@map_errors
def get_board_history(
    board_code: str = Path(max_length=30, description="Board code (zzshare format, e.g. '883957')"),
    source: Literal["zzshare"] = Query(..., description="Data source (only 'zzshare' is supported)"),
    frequency: Literal["d"] = Query("d", description="K-line frequency (daily only — zzshare plate_kline is daily-only)"),
    start_date: str | None = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: str | None = Query(None, description="End date (YYYY-MM-DD)"),
    days: int = Query(30, ge=1, le=365, description="Days (used when start_date not given)"),
) -> BoardKlineResponse:
    """Get historical K-line for a board (zzshare plate_kline)."""
    _resolve_source(source)
    manager = get_manager()
    try:
        rows, origin = manager.get_board_history(
            board_code,
            source=source,
            frequency=frequency,
            start_date=start_date,
            end_date=end_date,
            days=days,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"error": str(e)})

    # Reshape manager rows (list[dict]) into KLineData list. Defensive —
    # if a fetcher returns a partial row missing required fields, drop it
    # rather than 500ing.
    kline_data: list[KLineData] = []
    for row in rows or []:
        try:
            kline_data.append(
                KLineData(
                    date=str(row.get("date", "")),
                    open=float(row.get("open", 0.0)),
                    high=float(row.get("high", 0.0)),
                    low=float(row.get("low", 0.0)),
                    close=float(row.get("close", 0.0)),
                    volume=int(row.get("volume", 0)),
                    amount=_safe_optional_float(row.get("amount")),
                    change_percent=_safe_optional_float(row.get("pct_chg")),
                )
            )
        except (TypeError, ValueError):
            continue

    # Best-effort board name (no extra upstream call — use cached board list).
    from ...data_provider.persistence import board as stock_board_cache
    board_name = stock_board_cache.get_board_name(board_code, source) or board_code

    return BoardKlineResponse(
        board_code=board_code,
        board_name=board_name,
        period="daily",
        data=kline_data,
        source=origin,
    )


def _safe_optional_float(v):
    """Return None for None / NaN, else float(v). Used by route layer."""
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
```

Update the imports at the top of `boards.py`:

```python
from ..schemas import (
    BoardInfo,
    BoardKlineResponse,        # NEW
    BoardListResponse,
    BoardStockInfo,
    BoardStocksResponse,
    ErrorResponse,
    KLineData,                 # NEW
    StockBoardInfo,
    StockBoardsResponse,
    ZTPoolResponse,
    ZTPoolStock,
)
```

- [ ] **Step 2: Replace the 501 tests in `tests/test_boards_api.py`**

Replace lines 297-305 with:

```python
# ===== get_board_history (zzshare-only) =====


def test_get_board_history_source_required(client):
    """GET /boards/{code}/history without source → 422."""
    r = client.get("/api/v1/boards/883957/history")
    assert r.status_code == 422


def test_get_board_history_rejects_non_zzshare_source(client):
    """source must be 'zzshare' (Literal validated by FastAPI)."""
    r = client.get("/api/v1/boards/883957/history?source=eastmoney")
    assert r.status_code == 422


def test_get_board_history_rejects_non_daily_frequency(client):
    """frequency must be 'd' (Literal validated by FastAPI)."""
    r = client.get("/api/v1/boards/883957/history?source=zzshare&frequency=w")
    assert r.status_code == 422


def test_get_board_history_zzshare_returns_kline(client):
    """Happy path: zzshare returns rows → 200 with BoardKlineResponse."""
    fake_rows = [
        {
            "date": "2026-05-20", "open": 1.0, "high": 1.1, "low": 0.9,
            "close": 1.05, "volume": 100, "amount": 105.0, "pct_chg": 5.0,
        },
    ]
    with patch(
        "stock_data.data_provider.manager.DataFetcherManager.get_board_history",
        return_value=(fake_rows, "ZzshareFetcher"),
    ):
        r = client.get("/api/v1/boards/883957/history?source=zzshare&days=7")
    assert r.status_code == 200
    body = r.json()
    assert body["board_code"] == "883957"
    assert body["period"] == "daily"
    assert body["source"] == "ZzshareFetcher"
    assert len(body["data"]) == 1
    assert body["data"][0]["date"] == "2026-05-20"
    assert body["data"][0]["close"] == 1.05
```

(The patch target may need adjustment depending on where `get_board_history` is bound at import time — if patching at the manager class doesn't intercept, patch at `stock_data.api.routes.boards.get_board_history` instead. Check `tests/test_boards_api.py:29` for the analogous persistence-layer patch pattern.)

- [ ] **Step 3: Run tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_boards_api.py -v`
Expected: all PASS (the 2 old 501 tests replaced, 4 new ones pass).

- [ ] **Step 4: Boot the server and curl-verify**

Start the dev server in background (it won't have ZZSHARE_TOKEN but the SDK import path still works):

```bash
.venv/Scripts/python.exe -m stock_data.server
```

In another shell:

```bash
curl -s "http://localhost:8888/api/v1/boards/883957/history?source=zzshare&days=7" | python -m json.tool | head -30
```

Expected: HTTP 200, JSON body with `board_code: "883957"`, `period: "daily"`, `data: [...]` (rows). If 503 with "ZzshareFetcher zzshare SDK 不可用", the zzshare package isn't installed in `.venv` — fix with `.venv/Scripts/python.exe -m pip install zzshare`.

- [ ] **Step 5: Verify the explorer UI**

Open `http://localhost:8888/explorer/`, navigate to `/api/v1/boards/{board_code}/history`. Confirm:

1. Summary now reads "板块 K 线（日线，ZZSHARE）" (not "占位 — 暂未实现").
2. The "Fetcher backends" section lists only **ZzshareFetcher** (no ZhituFetcher, no EastMoneyFetcher).

If ZhituFetcher / EastMoneyFetcher still appear, check `getattr(instance, "get_board_history", None)` is returning None — confirm Task 4 deletes landed.

- [ ] **Step 6: Commit**

```bash
git add stock_data/api/routes/boards.py tests/test_boards_api.py
git commit -m "feat(api): wire /boards/{code}/history through zzshare plate_kline"
```

---

## Task 7: Final verification + CLAUDE.md touch-up

**Files:**
- Modify: `docs/superpowers/plans/2026-06-25-board-history-zzshare.md` (mark plan complete; or leave as-is for record)

- [ ] **Step 1: Run full default suite**

Run: `.venv/Scripts/python.exe -m pytest`
Expected: PASS (live_network tests skipped by default). If any pre-existing test fails unrelated to this change, investigate before proceeding.

- [ ] **Step 2: Run ruff**

Run: `ruff check .`
Expected: no new violations.

- [ ] **Step 3: Update CLAUDE.md if needed**

Check the row at CLAUDE.md line 268:

```
| `get_board_history` | `STOCK_BOARD` (source-routed, no failover; currently stub) (ZzshareFetcher P5) |
```

Change "currently stub" → "implemented via zzshare plate_kline (daily only)". Optionally add a note under the "Stage 1/2 Fetcher Drill-down" `fetcher_method` overrides table that this endpoint now lists only ZzshareFetcher in the manifest (not a code change, but useful documentation).

- [ ] **Step 4: Commit (if CLAUDE.md changed)**

```bash
git add CLAUDE.md
git commit -m "docs(CLAUDE): mark board-K-line as implemented via zzshare plate_kline"
```

---

## Self-review

**Spec coverage:**

- ✅ ZzshareFetcher implements board K-line — Task 3.
- ✅ EastMoney/Zhitu stubs removed — Task 4.
- ✅ Server route wires through — Task 6.
- ✅ Tests cover new + removed behaviors — Tasks 3, 4, 5, 6.
- ✅ Schema added — Task 2.
- ✅ Manifest stops showing phantom fetchers — Task 4 (delete method) is what makes this happen; Task 6 Step 5 verifies it.
- ✅ Source tracking preserved — `BoardKlineResponse.source` carries fetcher name verbatim from manager.
- ✅ Inbound/outbound code boundary — Task 3 accepts `board_code` as-is from the route (no ts_code suffixing), per CLAUDE.md "Don't leak outbound ts_code" rule.

**Placeholder scan:**

- "按实际填写" in Task 1 — this is intentional: the engineer must record what the probe found.
- The `_safe_optional_float` helper in Task 6 is fully specified.
- All test bodies contain real assertions, no "similar to Task N" shortcuts.

**Type consistency:**

- `BoardKlineResponse` (Task 2) used consistently in Task 6 (route decorator + return).
- `get_board_history` signature: fetcher (Task 3) accepts `frequency, days, *, start_date, end_date, source`; manager (Task 5) calls `f.get_board_history(board_code, frequency=..., days=..., start_date=..., end_date=..., source=...)` — matches.
- `KLineData` field names (`date`, `open`, `high`, `low`, `close`, `volume`, `amount`, `change_percent`) used in Task 6's reshape — match `schemas.py` (line 78+).

**Open question deferred to execution:**

- The probe in Task 1 may discover columns I didn't anticipate (e.g. `turnover_rate`, `circulation_value`). The fetcher's `keep = [...]` list will need to be edited after the probe. That's why the keep list is the only "fill in after probe" zone — everything else is concrete.
