# ZzshareFetcher 分钟级 K 线 + 移除 INDEX→HISTORICAL 兜底 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `manager.get_kline_data` capability-only routing (no silent INDEX→HISTORICAL fallback) and make `ZzshareFetcher.get_kline_data(frequency="5|15|30|60")` correctly route through `api.stk_mins` with multi-day concatenation.

**Architecture:** Two surgical edits — `manager.py` removes an 18-line fallback block; `zzshare_fetcher.py` extracts a `_fetch_minute_kline` helper shared by `_fetch_raw_data` (multi-day loop with `pd.concat`) and `get_intraday_data` (single-day). No new files; no new dependencies; no schema changes.

**Tech Stack:** Python 3.11+, pandas, existing `zzshare` PyPI SDK, existing `pytest` test suite.

**Spec:** `docs/superpowers/specs/2026-06-29-zzshare-min-kline-and-index-fallback-design.md`

---

## File Structure

**Modified files:**

| File | Responsibility | Why |
|---|---|---|
| `stock_data/data_provider/manager.py` | Route `get_kline_data` via capability only | Task 1: delete 18-line fallback at 308-326 |
| `stock_data/data_provider/fetchers/zzshare_fetcher.py` | Minute K-line via `api.stk_mins` | Task 2: helper + minute branch in `_fetch_raw_data` + `_normalize_data` minute branch + `get_intraday_data` refactor |

**Test files modified:**

| File | Tests added |
|---|---|
| `tests/test_base_unit.py` | Task 1: index fallback removal (2 tests) |
| `tests/test_zzshare_fetcher.py` | Task 2: minute `_fetch_raw_data` (8 new tests) |

**No new files.**

---

## Task 1: Remove INDEX→HISTORICAL fallback in `manager.get_kline_data`

**Files:**
- Modify: `stock_data/data_provider/manager.py:308-326` (delete fallback block)
- Test: `tests/test_base_unit.py`

### Step 1: Write failing test for fallback removal (daily frequency)

Add to `tests/test_base_unit.py` after the existing `MockFetcher` definition (search for `class TestDataFetcherManagerUnit`):

```python
class MockFetcherIndexOnly:
    """Mock that declares HISTORICAL_DWM only (NOT INDEX_HISTORICAL).
    
    Used to verify that index codes routed via manager.get_kline_data
    fall through to a clean DataFetchError when no INDEX_* fetcher is
    registered — i.e., the INDEX→HISTORICAL silent fallback is gone.
    """
    name = "MockFetcherIndexOnly"
    priority = 10
    supported_markets = {"csi"}
    supported_data_types = DataCapability.HISTORICAL_DWM

    def get_kline_data(self, stock_code, start_date=None, end_date=None,
                       days=30, frequency="d", adjust=None):
        return pd.DataFrame({"date": pd.to_datetime(["2026-05-01"]),
                             "open": [1.0], "high": [2.0], "low": [0.5],
                             "close": [1.5], "volume": [1000.0]})
```

Then in the `TestDataFetcherManagerUnit` class, add these two tests:

```python
def test_get_kline_data_index_no_fallback_daily(self):
    """Index code + only HISTORICAL_DWM fetcher: must raise DataFetchError.
    
    Pre-fix: silently routed through HISTORICAL_DWM and returned fake data.
    Post-fix: no INDEX_HISTORICAL declaration → DataFetchError.
    """
    from stock_data.data_provider.base import DataFetchError
    mgr = DataFetcherManager([MockFetcherIndexOnly()])
    with pytest.raises(DataFetchError):
        mgr.get_kline_data("000300", days=5, frequency="d")

def test_get_kline_data_index_no_fallback_minute(self):
    """Index code + minute freq + only HISTORICAL_MIN fetcher: must raise."""
    from stock_data.data_provider.base import DataFetchError
    mgr_only_hist = DataFetcherManager([MockFetcherIndexOnly()])
    with pytest.raises(DataFetchError):
        mgr_only_hist.get_kline_data("000300", days=5, frequency="5")
```

Also add `import pandas as pd` at the top of `test_base_unit.py` if not already present (it currently has `import pandas as pd` — verify by reading the file's head).

### Step 2: Run tests to verify they fail

Run:
```bash
.venv/Scripts/python.exe -m pytest tests/test_base_unit.py::TestDataFetcherManagerUnit::test_get_kline_data_index_no_fallback_daily tests/test_base_unit.py::TestDataFetcherManagerUnit::test_get_kline_data_index_no_fallback_minute -v
```

Expected: BOTH FAIL with `DataFetchError` NOT raised (current code falls back to HISTORICAL_DWM and returns the mock's df).

### Step 3: Remove fallback block in `manager.py`

Edit `stock_data/data_provider/manager.py:308-326`. The current code (lines 307-326):

```python
# Index codes prefer INDEX_HISTORICAL/INDEX_INTRADAY so fetchers can
# declare index support independently of stock K-line support, then
# fall back to HISTORICAL_DWM/HISTORICAL_MIN for backward compat.
if frequency in ("5", "15", "30", "60"):
    index_cap = DataCapability.INDEX_INTRADAY
    gen_cap = DataCapability.HISTORICAL_MIN
else:
    index_cap = DataCapability.INDEX_HISTORICAL
    gen_cap = DataCapability.HISTORICAL_DWM

if index_tag:
    market = index_tag
    capability = index_cap
    if not self._filter_by_capability(market, index_cap):
        capability = gen_cap
else:
    market = market_tag(stock_code)
    capability = gen_cap
```

Replace with:

```python
# Capability routing is capability-only — "no declaration = no capability".
# When index_tag is set, require INDEX_*; for stock codes, require HISTORICAL_*.
# A missing declaration surfaces as DataFetchError via _with_failover.
if index_tag:
    market = index_tag
    capability = (
        DataCapability.INDEX_INTRADAY
        if frequency in ("5", "15", "30", "60")
        else DataCapability.INDEX_HISTORICAL
    )
else:
    market = market_tag(stock_code)
    capability = (
        DataCapability.HISTORICAL_MIN
        if frequency in ("5", "15", "30", "60")
        else DataCapability.HISTORICAL_DWM
    )
```

### Step 4: Run tests to verify they pass

Run:
```bash
.venv/Scripts/python.exe -m pytest tests/test_base_unit.py::TestDataFetcherManagerUnit::test_get_kline_data_index_no_fallback_daily tests/test_base_unit.py::TestDataFetcherManagerUnit::test_get_kline_data_index_no_fallback_minute -v
```

Expected: BOTH PASS.

### Step 5: Run full test_base_unit.py + capability_method_map.py regression

Run:
```bash
.venv/Scripts/python.exe -m pytest tests/test_base_unit.py tests/test_capability_method_map.py -v
```

Expected: ALL PASS (no regression in capability routing).

### Step 6: Commit

```bash
git add stock_data/data_provider/manager.py tests/test_base_unit.py
git commit -m "feat(manager): remove INDEX→HISTORICAL silent fallback in get_kline_data"
```

---

## Task 2: ZzshareFetcher `_fetch_minute_kline` helper

**Files:**
- Modify: `stock_data/data_provider/fetchers/zzshare_fetcher.py`
- Test: `tests/test_zzshare_fetcher.py`

### Step 1: Write failing test for `_fetch_minute_kline` helper

Add to `tests/test_zzshare_fetcher.py` at the end of the existing `TestIntradayKline` class (around line 437). First read the file around line 437 to confirm the class boundary:

```python
class TestFetchMinuteKline:
    """Tests for the private _fetch_minute_kline helper (Task 2 prep)."""

    def test_helper_dispatches_to_stk_mins(self):
        """Helper calls api.stk_mins with correct ts_code / freq / trade_time."""
        import pandas as pd

        fetcher = ZzshareFetcher()
        fake_api = MagicMock()
        fake_api.stk_mins = MagicMock(
            return_value=pd.DataFrame({"trade_time": ["202605200935"]})
        )
        fetcher._api = fake_api
        df = fetcher._fetch_minute_kline("600519", "20260520", "5min")
        call = fake_api.stk_mins.call_args
        assert call.kwargs["ts_code"] == "600519.SH"
        assert call.kwargs["freq"] == "5min"
        assert call.kwargs["trade_time"] == "20260520"
        assert df is not None

    def test_helper_sdk_unavailable_returns_none(self, monkeypatch):
        monkeypatch.delenv("ZZSHARE_TOKEN", raising=False)
        with patch("importlib.util.find_spec", return_value=None):
            fetcher = ZzshareFetcher()
            assert fetcher._fetch_minute_kline("600519", "20260520", "5min") is None

    def test_helper_sdk_exception_returns_none(self):
        fetcher = ZzshareFetcher()
        fake_api = MagicMock()
        fake_api.stk_mins = MagicMock(side_effect=RuntimeError("rate limit"))
        fetcher._api = fake_api
        assert fetcher._fetch_minute_kline("600519", "20260520", "5min") is None

    def test_helper_empty_df_returns_none(self):
        import pandas as pd

        fetcher = ZzshareFetcher()
        fake_api = MagicMock()
        fake_api.stk_mins = MagicMock(return_value=pd.DataFrame())
        fetcher._api = fake_api
        assert fetcher._fetch_minute_kline("600519", "20260520", "5min") is None
```

### Step 2: Run tests to verify they fail

Run:
```bash
.venv/Scripts/python.exe -m pytest tests/test_zzshare_fetcher.py::TestFetchMinuteKline -v
```

Expected: ALL FAIL with `AttributeError: 'ZzshareFetcher' object has no attribute '_fetch_minute_kline'`.

### Step 3: Implement `_fetch_minute_kline` helper

In `stock_data/data_provider/fetchers/zzshare_fetcher.py`, add the helper method right after the existing `_PERIOD_TO_FREQ` dict (around line 203). Insert immediately AFTER the `get_intraday_data` method body (after line 242) and BEFORE `get_realtime_quote`:

```python
    def _fetch_minute_kline(
        self, stock_code: str, trade_date_yyyymmdd: str, freq: str
    ) -> pd.DataFrame | None:
        """底层调 api.stk_mins,返回 DataFrame 或 None。

        单日调用封装。统一供 _fetch_raw_data（多日循环）和
        get_intraday_data（单日）使用。SDK 不可用、上游异常、
        或返回空 df 时返回 None，调用方需自行决定下一步。
        """
        api = self._ensure_api()
        if api is None:
            return None
        ts_code = _to_zzshare_ts_code(normalize_stock_code(stock_code))
        try:
            df = api.stk_mins(
                ts_code=ts_code,
                trade_time=trade_date_yyyymmdd,
                freq=freq,
            )
        except Exception as e:
            logger.warning(
                f"[ZzshareFetcher] stk_mins({ts_code}, {freq}) failed: {e}"
            )
            return None
        if df is None or df.empty:
            return None
        return df
```

### Step 4: Run tests to verify they pass

Run:
```bash
.venv/Scripts/python.exe -m pytest tests/test_zzshare_fetcher.py::TestFetchMinuteKline -v
```

Expected: ALL 4 PASS.

### Step 5: Commit

```bash
git add stock_data/data_provider/fetchers/zzshare_fetcher.py tests/test_zzshare_fetcher.py
git commit -m "refactor(zzshare): extract _fetch_minute_kline helper"
```

---

## Task 3: ZzshareFetcher `_fetch_raw_data` minute branch (single-day)

**Files:**
- Modify: `stock_data/data_provider/fetchers/zzshare_fetcher.py:135-159`
- Test: `tests/test_zzshare_fetcher.py`

### Step 1: Write failing test for single-day minute K via `_fetch_raw_data`

Add to `tests/test_zzshare_fetcher.py` inside `TestKlineDWM` (or new class). Search for `class TestKlineDWM` to find the right location. Add at the end of that class:

```python
    def test_fetch_raw_data_minute_single_day(self):
        """_fetch_raw_data(frequency="5") routes through api.stk_mins for a single day."""
        import pandas as pd

        fetcher = ZzshareFetcher()
        fake_api = MagicMock()
        fake_api.stk_mins = MagicMock(return_value=pd.DataFrame({
            "ts_code": ["600519.SH"] * 3,
            "trade_time": ["202605200935", "202605200940", "202605200945"],
            "open": [1700.0, 1705.0, 1710.0],
            "high": [1708.0, 1712.0, 1717.0],
            "low": [1698.0, 1702.0, 1708.0],
            "close": [1705.0, 1710.0, 1715.0],
            "vol": [1e5, 1.1e5, 1.2e5],
            "amount": [1e8, 1.1e8, 1.2e8],
        }))
        fetcher._api = fake_api

        df = fetcher.get_kline_data(
            "600519", "2026-05-20", "2026-05-20", frequency="5"
        )

        # 验证走的是 stk_mins 而不是 daily
        assert fake_api.stk_mins.called
        assert not fake_api.daily.called
        # 验证调用参数
        call = fake_api.stk_mins.call_args
        assert call.kwargs["freq"] == "5min"
        assert call.kwargs["trade_time"] == "20260520"
        assert call.kwargs["ts_code"] == "600519.SH"

    def test_fetch_raw_data_minute_adjust_ignored(self):
        """adjust='qfq' on minute frequency: must NOT be forwarded to stk_mins."""
        import pandas as pd

        fetcher = ZzshareFetcher()
        fake_api = MagicMock()
        fake_api.stk_mins = MagicMock(return_value=pd.DataFrame({
            "trade_time": ["202605200935"],
            "open": [1700.0], "high": [1708.0], "low": [1698.0], "close": [1705.0],
            "vol": [1e5], "amount": [1e8],
        }))
        fetcher._api = fake_api

        fetcher.get_kline_data(
            "600519", "2026-05-20", "2026-05-20", frequency="5", adjust="qfq"
        )
        call = fake_api.stk_mins.call_args
        assert "adj" not in call.kwargs
        assert "adjust" not in call.kwargs

    def test_fetch_raw_data_minute_sdk_unavailable_raises(self, monkeypatch):
        """SDK not installed → minute path raises DataFetchError."""
        monkeypatch.delenv("ZZSHARE_TOKEN", raising=False)
        with patch("importlib.util.find_spec", return_value=None):
            fetcher = ZzshareFetcher()
            with pytest.raises(DataFetchError, match="无分钟数据"):
                fetcher.get_kline_data(
                    "600519", "2026-05-20", "2026-05-20", frequency="5"
                )

    def test_fetch_raw_data_minute_all_days_empty_raises(self):
        """When stk_mins returns empty for the only day, raise DataFetchError."""
        import pandas as pd

        fetcher = ZzshareFetcher()
        fake_api = MagicMock()
        fake_api.stk_mins = MagicMock(return_value=pd.DataFrame())
        fetcher._api = fake_api

        with pytest.raises(DataFetchError, match="无分钟数据"):
            fetcher.get_kline_data(
                "600519", "2026-05-20", "2026-05-20", frequency="5"
            )
```

### Step 2: Run tests to verify they fail

Run:
```bash
.venv/Scripts/python.exe -m pytest "tests/test_zzshare_fetcher.py::TestKlineDWM::test_fetch_raw_data_minute_single_day" "tests/test_zzshare_fetcher.py::TestKlineDWM::test_fetch_raw_data_minute_adjust_ignored" "tests/test_zzshare_fetcher.py::TestKlineDWM::test_fetch_raw_data_minute_sdk_unavailable_raises" "tests/test_zzshare_fetcher.py::TestKlineDWM::test_fetch_raw_data_minute_all_days_empty_raises" -v
```

Expected: ALL 4 FAIL — `_fetch_raw_data` currently raises `DataFetchError("不支持周/月线")` for `frequency="5"` (line 144-147) OR if the w/m check passed, it would call `api.daily` (wrong).

### Step 3: Add minute branch to `_fetch_raw_data`

Edit `stock_data/data_provider/fetchers/zzshare_fetcher.py` `_fetch_raw_data` method (lines 135-159). Current code:

```python
    def _fetch_raw_data(
        self,
        stock_code: str,
        start_date: str,
        end_date: str,
        frequency: str = "d",
        adjust: str | None = None,
    ) -> pd.DataFrame:
        """Fetch daily K-line from zzshare. Raises for weekly/monthly."""
        if frequency in ("w", "m"):
            raise DataFetchError(
                f"ZzshareFetcher 不支持周线/月线 (frequency={frequency}, 仅日线 daily)"
            )
        api = self._ensure_api()
        if api is None:
            raise DataFetchError(f"ZzshareFetcher zzshare SDK 不可用: {self._init_error}")
        ts_code = _to_zzshare_ts_code(normalize_stock_code(stock_code))
        kwargs: dict = {
            "ts_code": ts_code,
            "start_date": _to_yyyymmdd(start_date),
            "end_date": _to_yyyymmdd(end_date),
        }
        if adjust:
            kwargs["adj"] = adjust
        return api.daily(**kwargs)
```

Replace with:

```python
    def _fetch_raw_data(
        self,
        stock_code: str,
        start_date: str,
        end_date: str,
        frequency: str = "d",
        adjust: str | None = None,
    ) -> pd.DataFrame:
        """Fetch K-line from zzshare.

        Daily: api.daily (single call).
        Minute (5/15/30/60): api.stk_mins is single-day only; loop over
        the date range and pd.concat. adjust is ignored for minute
        (zzshare upstream: minute K has no adjustment).
        """
        if frequency in ("w", "m"):
            raise DataFetchError(
                f"ZzshareFetcher 不支持周线/月线 (frequency={frequency}, 仅日线 daily)"
            )

        # Minute-frequency branch — multi-day loop with concat
        if frequency in ("5", "15", "30", "60"):
            freq = self._PERIOD_TO_FREQ.get(frequency, f"{frequency}min")
            try:
                start_d = datetime.strptime(start_date, "%Y-%m-%d").date()
                end_d = datetime.strptime(end_date, "%Y-%m-%d").date()
            except ValueError as e:
                raise DataFetchError(f"Invalid date for minute K: {e}") from e
            day_count = (end_d - start_d).days + 1
            if day_count > 14:
                logger.warning(
                    "[ZzshareFetcher] minute K over %d days for %s — %d SDK calls expected",
                    day_count, stock_code, day_count,
                )
            dfs: list[pd.DataFrame] = []
            cur = start_d
            while cur <= end_d:
                df_one = self._fetch_minute_kline(
                    stock_code, cur.strftime("%Y%m%d"), freq
                )
                if df_one is not None:
                    dfs.append(df_one)
                cur += timedelta(days=1)
            if not dfs:
                raise DataFetchError(
                    f"ZzshareFetcher 无分钟数据 for {stock_code} {start_date}~{end_date}"
                )
            return pd.concat(dfs, ignore_index=True)

        # Daily branch (existing path)
        api = self._ensure_api()
        if api is None:
            raise DataFetchError(f"ZzshareFetcher zzshare SDK 不可用: {self._init_error}")
        ts_code = _to_zzshare_ts_code(normalize_stock_code(stock_code))
        kwargs: dict = {
            "ts_code": ts_code,
            "start_date": _to_yyyymmdd(start_date),
            "end_date": _to_yyyymmdd(end_date),
        }
        if adjust:
            kwargs["adj"] = adjust
        return api.daily(**kwargs)
```

Also update the docstring at the top of the method body (line 144 comment) which currently says "Raises for weekly/monthly" — replace with the new docstring (done inline above).

Verify `timedelta` and `datetime` are already imported in the module (they are — line 17: `from datetime import date, datetime, timedelta`).

### Step 4: Run tests to verify single-day passes

Run:
```bash
.venv/Scripts/python.exe -m pytest "tests/test_zzshare_fetcher.py::TestKlineDWM::test_fetch_raw_data_minute_single_day" "tests/test_zzshare_fetcher.py::TestKlineDWM::test_fetch_raw_data_minute_adjust_ignored" "tests/test_zzshare_fetcher.py::TestKlineDWM::test_fetch_raw_data_minute_sdk_unavailable_raises" "tests/test_zzshare_fetcher.py::TestKlineDWM::test_fetch_raw_data_minute_all_days_empty_raises" -v
```

Expected: ALL 4 PASS.

### Step 5: Run existing `get_kline_data` daily tests to verify no regression

Run:
```bash
.venv/Scripts/python.exe -m pytest tests/test_zzshare_fetcher.py -v -k "TestKlineDWM"
```

Expected: ALL PASS (including the original daily tests).

### Step 6: Commit

```bash
git add stock_data/data_provider/fetchers/zzshare_fetcher.py tests/test_zzshare_fetcher.py
git commit -m "feat(zzshare): _fetch_raw_data minute branch with multi-day loop"
```

---

## Task 4: ZzshareFetcher `_normalize_data` minute branch

**Files:**
- Modify: `stock_data/data_provider/fetchers/zzshare_fetcher.py:161-194`
- Test: `tests/test_zzshare_fetcher.py`

### Step 1: Write failing test for minute normalization

Add to `tests/test_zzshare_fetcher.py` (any class; create `TestNormalizeMinute`):

```python
class TestNormalizeMinute:
    """Tests for _normalize_data minute branch."""

    def test_normalize_minute_extracts_date_from_trade_time(self):
        """trade_time (YYYYMMDDHHMM, 12 digits) → date column (YYYY-MM-DD)."""
        import pandas as pd

        fetcher = ZzshareFetcher()
        raw = pd.DataFrame({
            "ts_code": ["600519.SH"] * 4,
            "trade_time": ["202605200935", "202605200940", "202605210935", "202605210940"],
            "open": [1700.0, 1705.0, 1710.0, 1715.0],
            "high": [1708.0, 1712.0, 1718.0, 1723.0],
            "low": [1698.0, 1702.0, 1708.0, 1713.0],
            "close": [1705.0, 1710.0, 1715.0, 1720.0],
            "vol": [1e5, 1.1e5, 1.2e5, 1.3e5],
            "amount": [1e8, 1.1e8, 1.2e8, 1.3e8],
        })
        out = fetcher._normalize_data(raw, "600519")
        assert "date" in out.columns
        # trade_time[0:8] = "20260520" → "2026-05-20"
        dates = sorted(out["date"].astype(str).unique())
        assert dates == ["2026-05-20", "2026-05-21"]
        # vol renamed to volume
        assert "volume" in out.columns
        assert "vol" not in out.columns
        # No time column (lost per spec §3.1)
        assert "time" not in out.columns
```

### Step 2: Run test to verify it fails

Run:
```bash
.venv/Scripts/python.exe -m pytest tests/test_zzshare_fetcher.py::TestNormalizeMinute -v
```

Expected: FAIL — `_normalize_data` currently looks for `trade_date` (not present) or `date` (not present in minute output), so date column is missing or wrong.

### Step 3: Add minute branch to `_normalize_data`

Edit `stock_data/data_provider/fetchers/zzshare_fetcher.py:161-194`. Current code:

```python
    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        """Normalize zzshare daily output to STANDARD_COLUMNS.

        Column mapping: vol -> volume, trade_date -> date (YYYY-MM-DD).
        """
        if df is None or df.empty:
            return df
        df = df.copy()
        rename = {}
        if "vol" in df.columns:
            rename["vol"] = "volume"
        if "trade_date" in df.columns:
            rename["trade_date"] = "date"
        df = df.rename(columns=rename)
        if "date" in df.columns:
            df["date"] = df["date"].astype(str).apply(_from_yyyymmdd)
            df["date"] = pd.to_datetime(df["date"])
        if "code" not in df.columns:
            df["code"] = normalize_stock_code(stock_code)
        keep = ["code"] + [
            c
            for c in [
                "date",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "amount",
                "pct_chg",
            ]
            if c in df.columns
        ]
        return df[[c for c in keep if c in df.columns]]
```

Replace with:

```python
    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        """Normalize zzshare K-line output to STANDARD_COLUMNS.

        Daily: trade_date (YYYYMMDD) -> date.
        Minute: trade_time (YYYYMMDDHHMM, 12 digits) -> date (first 8 digits).
        Column rename: vol -> volume. pct_chg absent for minute.
        """
        if df is None or df.empty:
            return df
        df = df.copy()
        rename = {}
        if "vol" in df.columns:
            rename["vol"] = "volume"
        # Daily path: trade_date (YYYYMMDD) → date
        if "trade_date" in df.columns and "date" not in df.columns:
            rename["trade_date"] = "date"
        df = df.rename(columns=rename)
        # Minute path: derive date from trade_time (first 8 digits of YYYYMMDDHHMM)
        if "date" not in df.columns and "trade_time" in df.columns:
            df["date"] = df["trade_time"].astype(str).str.slice(0, 8).apply(_from_yyyymmdd)
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
        if "code" not in df.columns:
            df["code"] = normalize_stock_code(stock_code)
        keep = ["code"] + [
            c
            for c in [
                "date",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "amount",
                "pct_chg",
            ]
            if c in df.columns
        ]
        return df[[c for c in keep if c in df.columns]]
```

### Step 4: Run test to verify it passes

Run:
```bash
.venv/Scripts/python.exe -m pytest tests/test_zzshare_fetcher.py::TestNormalizeMinute -v
```

Expected: PASS.

### Step 5: Run full test_zzshare_fetcher.py to verify no regression

Run:
```bash
.venv/Scripts/python.exe -m pytest tests/test_zzshare_fetcher.py -v
```

Expected: ALL PASS (existing daily + intraday + new minute tests).

### Step 6: Commit

```bash
git add stock_data/data_provider/fetchers/zzshare_fetcher.py tests/test_zzshare_fetcher.py
git commit -m "feat(zzshare): _normalize_data minute branch (date from trade_time)"
```

---

## Task 5: ZzshareFetcher multi-day minute test coverage

**Files:**
- Modify: `tests/test_zzshare_fetcher.py`

### Step 1: Write failing test for multi-day minute K loop

Add to `tests/test_zzshare_fetcher.py` inside `TestKlineDWM` (after the single-day tests):

```python
    def test_fetch_raw_data_minute_three_day_loop(self):
        """3-day minute range → 3 stk_mins calls + concat."""
        import pandas as pd

        fetcher = ZzshareFetcher()
        fake_api = MagicMock()
        fake_api.stk_mins = MagicMock(side_effect=[
            pd.DataFrame({
                "trade_time": ["202605180935", "202605180940"],
                "open": [1700.0, 1705.0], "high": [1708.0, 1712.0],
                "low": [1698.0, 1702.0], "close": [1705.0, 1710.0],
                "vol": [1e5, 1.1e5], "amount": [1e8, 1.1e8],
            }),
            pd.DataFrame({
                "trade_time": ["202605190935", "202605190940"],
                "open": [1710.0, 1715.0], "high": [1718.0, 1723.0],
                "low": [1708.0, 1713.0], "close": [1715.0, 1720.0],
                "vol": [1.2e5, 1.3e5], "amount": [1.2e8, 1.3e8],
            }),
            pd.DataFrame({
                "trade_time": ["202605200935", "202605200940"],
                "open": [1720.0, 1725.0], "high": [1728.0, 1733.0],
                "low": [1718.0, 1723.0], "close": [1725.0, 1730.0],
                "vol": [1.4e5, 1.5e5], "amount": [1.4e8, 1.5e8],
            }),
        ])
        fetcher._api = fake_api

        df = fetcher.get_kline_data(
            "600519", "2026-05-18", "2026-05-20", frequency="5"
        )

        assert fake_api.stk_mins.call_count == 3
        # Verify trade_time argument across calls
        times = [c.kwargs["trade_time"] for c in fake_api.stk_mins.call_args_list]
        assert times == ["20260518", "20260519", "20260520"]
        # Total rows
        assert len(df) == 6

    def test_fetch_raw_data_minute_skips_empty_days(self):
        """Non-trade days returning None/empty are skipped, not raised."""
        import pandas as pd

        fetcher = ZzshareFetcher()
        fake_api = MagicMock()
        fake_api.stk_mins = MagicMock(side_effect=[
            pd.DataFrame({
                "trade_time": ["202605180935"],
                "open": [1700.0], "high": [1708.0], "low": [1698.0], "close": [1705.0],
                "vol": [1e5], "amount": [1e8],
            }),
            pd.DataFrame(),  # 19th: empty (non-trade day)
            pd.DataFrame({
                "trade_time": ["202605200935"],
                "open": [1720.0], "high": [1728.0], "low": [1718.0], "close": [1725.0],
                "vol": [1.4e5], "amount": [1.4e8],
            }),
        ])
        fetcher._api = fake_api

        df = fetcher.get_kline_data(
            "600519", "2026-05-18", "2026-05-20", frequency="5"
        )
        assert fake_api.stk_mins.call_count == 3
        assert len(df) == 2  # only 18 and 20 contributed

    def test_fetch_raw_data_minute_long_range_logs_warning(self, caplog):
        """Range > 14 days triggers a logger.warning."""
        import logging
        import pandas as pd

        fetcher = ZzshareFetcher()
        fake_api = MagicMock()
        fake_api.stk_mins = MagicMock(return_value=pd.DataFrame({
            "trade_time": ["202605180935"],
            "open": [1700.0], "high": [1708.0], "low": [1698.0], "close": [1705.0],
            "vol": [1e5], "amount": [1e8],
        }))
        fetcher._api = fake_api

        with caplog.at_level(logging.WARNING, logger="stock_data.data_provider.fetchers.zzshare_fetcher"):
            fetcher.get_kline_data(
                "600519", "2026-05-01", "2026-05-20", frequency="5"
            )

        assert any("over 20 days" in r.message for r in caplog.records)
```

### Step 2: Run tests to verify they pass (or fail if not yet implemented)

Run:
```bash
.venv/Scripts/python.exe -m pytest "tests/test_zzshare_fetcher.py::TestKlineDWM::test_fetch_raw_data_minute_three_day_loop" "tests/test_zzshare_fetcher.py::TestKlineDWM::test_fetch_raw_data_minute_skips_empty_days" "tests/test_zzshare_fetcher.py::TestKlineDWM::test_fetch_raw_data_minute_long_range_logs_warning" -v
```

Expected: ALL 3 PASS (since Task 3 already implemented the loop). If any fail, debug — likely an issue with `pd.concat` column alignment; ensure `pd.concat(dfs, ignore_index=True)` works without specifying `axis`.

If `pd.concat` complains about columns, add `sort=False` (default in pandas 2.x is False; verify).

### Step 3: Run full test_zzshare_fetcher.py

Run:
```bash
.venv/Scripts/python.exe -m pytest tests/test_zzshare_fetcher.py -v
```

Expected: ALL PASS.

### Step 4: Commit

```bash
git add tests/test_zzshare_fetcher.py
git commit -m "test(zzshare): multi-day minute K loop coverage"
```

---

## Task 6: ZzshareFetcher `get_intraday_data` refactor (use helper)

**Files:**
- Modify: `stock_data/data_provider/fetchers/zzshare_fetcher.py:205-242`
- Test: `tests/test_zzshare_fetcher.py` (existing tests must continue passing)

### Step 1: Verify existing tests still pass before refactor

Run:
```bash
.venv/Scripts/python.exe -m pytest tests/test_zzshare_fetcher.py::TestIntradayKline -v
```

Expected: ALL 5 EXISTING tests PASS (baseline).

### Step 2: Refactor `get_intraday_data` to use `_fetch_minute_kline`

Edit `stock_data/data_provider/fetchers/zzshare_fetcher.py:205-242`. Current code:

```python
    def get_intraday_data(
        self, stock_code: str, period: str = "5", adjust: str = ""
    ) -> pd.DataFrame | None:
        """Fetch minute K-line from zzshare (period=1/5/15/30/60).

        Note: zzshare minute K does not support adjust — the ``adjust`` param
        is accepted for interface symmetry but is not forwarded to the SDK.
        """

        api = self._ensure_api()
        if api is None:
            return None
        ts_code = _to_zzshare_ts_code(normalize_stock_code(stock_code))
        # Determine the date to query (latest trade date or today).
        trade_time = (datetime.now() - timedelta(days=2)).strftime("%Y%m%d")
        freq = self._PERIOD_TO_FREQ.get(period, "5min")
        try:
            df = api.stk_mins(ts_code=ts_code, trade_time=trade_time, freq=freq)
        except Exception as e:
            logger.warning(f"[ZzshareFetcher] stk_mins({ts_code}, {freq}) failed: {e}")
            return None
        if df is None or df.empty:
            return None
        df = df.copy()
        if "vol" in df.columns:
            df = df.rename(columns={"vol": "volume"})
        if "trade_time" in df.columns:
            # YYYYMMDDHHMM (12 digits) -> HH:MM:SS (positions 8..12 = HHMM, pad SS=00)
            df["time"] = (
                df["trade_time"]
                .astype(str)
                .str.slice(8, 12)
                .apply(lambda s: f"{s[:2]}:{s[2:4]}:00" if len(s) == 4 else s)
            )
            df = df.drop(columns=["trade_time"])
        keep = ["time", "open", "high", "low", "close", "volume", "amount"]
        df = df[[c for c in keep if c in df.columns]]
        return df
```

Replace with:

```python
    def get_intraday_data(
        self, stock_code: str, period: str = "5", adjust: str = ""
    ) -> pd.DataFrame | None:
        """Fetch minute K-line from zzshare (period=1/5/15/30/60).

        Single-day, latest available (today - 2 days as a safe trade-time
        default — same heuristic the previous inline implementation used).

        Note: zzshare minute K does not support adjust — the ``adjust`` param
        is accepted for interface symmetry but is not forwarded to the SDK.
        """
        freq = self._PERIOD_TO_FREQ.get(period, "5min")
        trade_time = (datetime.now() - timedelta(days=2)).strftime("%Y%m%d")
        df = self._fetch_minute_kline(stock_code, trade_time, freq)
        if df is None:
            return None
        df = df.copy()
        if "vol" in df.columns:
            df = df.rename(columns={"vol": "volume"})
        if "trade_time" in df.columns:
            # YYYYMMDDHHMM (12 digits) -> HH:MM:SS (positions 8..12 = HHMM, pad SS=00)
            df["time"] = (
                df["trade_time"]
                .astype(str)
                .str.slice(8, 12)
                .apply(lambda s: f"{s[:2]}:{s[2:4]}:00" if len(s) == 4 else s)
            )
            df = df.drop(columns=["trade_time"])
        keep = ["time", "open", "high", "low", "close", "volume", "amount"]
        df = df[[c for c in keep if c in df.columns]]
        return df
```

### Step 3: Verify existing intraday tests still pass

Run:
```bash
.venv/Scripts/python.exe -m pytest tests/test_zzshare_fetcher.py::TestIntradayKline -v
```

Expected: ALL 5 EXISTING tests PASS (no behavior change).

### Step 4: Run full test_zzshare_fetcher.py

Run:
```bash
.venv/Scripts/python.exe -m pytest tests/test_zzshare_fetcher.py -v
```

Expected: ALL PASS.

### Step 5: Commit

```bash
git add stock_data/data_provider/fetchers/zzshare_fetcher.py
git commit -m "refactor(zzshare): get_intraday_data uses _fetch_minute_kline helper"
```

---

## Task 7: Manager-level integration test (verify failover to ZzshareFetcher works for minute K)

**Files:**
- Create: `tests/test_manager_zzshare_minute.py`

### Step 1: Write integration test

Create new file `tests/test_manager_zzshare_minute.py`:

```python
"""Manager-level test: verify ZzshareFetcher handles minute K via get_kline_data.

Complements tests/test_zzshare_fetcher.py (unit) by exercising the full
manager.get_kline_data → ZzshareFetcher._fetch_raw_data → stk_mins path.
"""
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from stock_data.data_provider.base import DataCapability
from stock_data.data_provider.fetchers.zzshare_fetcher import ZzshareFetcher
from stock_data.data_provider.manager import DataFetcherManager


class _FakeZ:
    """Wraps ZzshareFetcher and forces availability regardless of SDK install."""
    pass


def _make_manager_with_zzshare_only() -> DataFetcherManager:
    """Manager with only ZzshareFetcher (mocked as available)."""
    fetcher = ZzshareFetcher()
    fetcher.is_available = lambda: True
    # Patch _ensure_api to return a mock api so we don't need real SDK
    fake_api = MagicMock()
    fetcher._api = fake_api
    mgr = DataFetcherManager()
    mgr.add_fetcher(fetcher)
    return mgr, fake_api


def test_manager_routes_minute_kline_to_zzshare():
    """manager.get_kline_data(frequency="5") → ZzshareFetcher → stk_mins."""
    import pandas as pd

    mgr, fake_api = _make_manager_with_zzshare_only()
    fake_api.stk_mins = MagicMock(return_value=pd.DataFrame({
        "trade_time": ["202605200935", "202605200940"],
        "open": [1700.0, 1705.0], "high": [1708.0, 1712.0],
        "low": [1698.0, 1702.0], "close": [1705.0, 1710.0],
        "vol": [1e5, 1.1e5], "amount": [1e8, 1.1e8],
    }))

    df, source = mgr.get_kline_data(
        "600519", start_date="2026-05-20", end_date="2026-05-20", frequency="5"
    )

    assert source == "ZzshareFetcher"
    assert fake_api.stk_mins.called
    assert "date" in df.columns
    assert len(df) == 2
```

### Step 2: Run test to verify it passes

Run:
```bash
.venv/Scripts/python.exe -m pytest tests/test_manager_zzshare_minute.py -v
```

Expected: PASS (integration path works end-to-end).

### Step 3: Commit

```bash
git add tests/test_manager_zzshare_minute.py
git commit -m "test(manager): zzshare minute K integration via manager.get_kline_data"
```

---

## Task 8: Full regression suite

**Files:** none modified.

### Step 1: Run full default test suite

Run:
```bash
.venv/Scripts/python.exe -m pytest -v
```

Expected: ALL PASS (default skips `live_network` and `requires_token` markers).

### Step 2: Run capability_method_map test specifically

Run:
```bash
.venv/Scripts/python.exe -m pytest tests/test_capability_method_map.py -v
```

Expected: ALL PASS (no capability table regression).

### Step 3: Lint check

Run:
```bash
ruff check stock_data/data_provider/manager.py stock_data/data_provider/fetchers/zzshare_fetcher.py tests/test_zzshare_fetcher.py tests/test_base_unit.py tests/test_manager_zzshare_minute.py
```

Expected: 0 errors (warnings OK).

### Step 4: Final commit (docs if any drift)

If CLAUDE.md needs an update to capability tables / fetcher description, update and commit:

```bash
git add CLAUDE.md
git commit -m "docs(claude): note zzshare minute K support via _fetch_raw_data"
```

Otherwise skip this step.

---

## Self-Review Checklist

**Spec coverage:**

| Spec section | Task |
|---|---|
| §0 摘要 — Task 1 | Task 1 ✓ |
| §0 摘要 — Task 2 (helper + multi-day loop) | Tasks 2, 3, 4, 5, 6 ✓ |
| §1.3 persistence boundary clarification | (informational, no code change) ✓ |
| §2.1 manager.py fallback deletion | Task 1 ✓ |
| §2.2 helper signature | Task 2 ✓ |
| §2.2 `_fetch_raw_data` minute branch | Task 3 ✓ |
| §2.2 `_normalize_data` minute branch | Task 4 ✓ |
| §2.2 `get_intraday_data` refactor | Task 6 ✓ |
| §2.2 adjust handling | Task 3 test "test_fetch_raw_data_minute_adjust_ignored" ✓ |
| §2.2 test matrix | Tasks 2, 3, 4, 5 ✓ |
| §2.3 boundary conditions | Task 7 (integration) ✓ |
| §3.1 time granularity loss | Documented in spec; accepted by user ✓ |
| §3.2 QoS cost (>14 day warning) | Task 5 test "test_fetch_raw_data_minute_long_range_logs_warning" ✓ |

**No placeholders** — every step has concrete code, exact file paths, exact commands.

**Type consistency:**

- `_fetch_minute_kline(stock_code, trade_date_yyyymmdd, freq)` returns `pd.DataFrame | None` — used consistently across Tasks 2, 3, 6.
- `_normalize_data(df, stock_code)` returns `pd.DataFrame` — used in Tasks 3, 4.
- `_fetch_raw_data` signature unchanged — Task 3 only adds branches.
- `_PERIOD_TO_FREQ` dict (existing) used in Tasks 3, 6.

**Pre-flight checks to verify before starting:**

1. Confirm `timedelta` import in `zzshare_fetcher.py` line 17: `from datetime import date, datetime, timedelta`. (Confirmed via Read.)
2. Confirm `pd.concat` is available (pandas already a dependency).
3. Confirm `pytest`, `MagicMock`, `patch` are imported in `test_zzshare_fetcher.py` (they should be from existing tests).
4. Confirm `_PERIOD_TO_FREQ` is defined before `_fetch_raw_data` and `get_intraday_data` (it's at line 197, both methods use it).