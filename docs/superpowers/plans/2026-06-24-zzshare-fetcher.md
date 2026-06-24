# ZzshareFetcher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a new `ZzshareFetcher` that exposes 10 server capabilities (HISTORICAL_DWM / HISTORICAL_MIN / REALTIME_QUOTE / STOCK_LIST / TRADE_CALENDAR / STOCK_BOARD / STOCK_ZT_POOL / DRAGON_TIGER / HOT_TOPICS / STOCK_INFO) backed by the zzshare DataApi SDK, with boards endpoint source-routing supporting `?source=zzshare`.

**Architecture:** Single-file `ZzshareFetcher(BaseFetcher)` class at `stock_data/data_provider/fetchers/zzshare_fetcher.py` with all 10 capabilities co-located. `is_available()` probes the DataApi SDK via `importlib.util.find_spec` (mirrors akshare pattern) and falls back to "unavailable" if missing — manager skips it. Boards 4 methods (get_all_boards / get_board_stocks / get_stock_boards / get_board_history) participate in the existing `_with_source` source-routing by adding `"zzshare"` to `_VALID_SOURCES` and the `VALID_SUBTYPES_BY_SOURCE` dict. Manager registration added to `create_default_manager()` between Zhitu(P4) and Tencent(P5).

**Tech Stack:** Python 3.11+, pandas, DataApi SDK (or `requests` fallback if SDK unavailable), pytest, ruff.

**Reference spec:** `docs/superpowers/specs/2026-06-24-zzshare-fetcher-design.md` (commit `ee0fa62`).

**Implementation note (2026-06-24):** `BaseFetcher.get_kline_data` raises `DataFetchError("No data for {stock_code}")` on empty `api.daily(...)` returns (see `base.py:277-278`). Therefore `test_daily_empty_df_returns_empty` should be `test_daily_empty_df_raises` with `pytest.raises(DataFetchError)`. This only applies to the daily K-line path; other empty-data tests (intraday via `get_intraday_data`, realtime, list, etc.) still return `None`/`[]` as written because they don't route through `get_kline_data`.

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `stock_data/data_provider/fetchers/zzshare_fetcher.py` | Create | The fetcher class (~700 lines, 10 caps) |
| `stock_data/data_provider/persistence/board.py` | Modify | Add `"zzshare"` to `VALID_SUBTYPES_BY_SOURCE` |
| `stock_data/api/routes/boards.py` | Modify | Add `"zzshare"` to `_VALID_SOURCES` + 3 Literal extensions + 1 if fix |
| `stock_data/data_provider/manager.py` | Modify | Register `ZzshareFetcher` in `create_default_manager()` |
| `tests/test_zzshare_fetcher.py` | Create | ~30 test cases for all 10 capabilities |
| `tests/test_capability_method_map.py` | Modify | Add `ZzshareFetcher` to `_CONCRETE_FETCHERS` |
| `pyproject.toml` | Modify | Add optional `zzshare` extra with `DataApi` (best-effort) |

**Untouched** (already in place per spec):
- `stock_data/data_provider/base.py` — `DataCapability` flags + `CAPABILITY_TO_METHOD` already exist
- `stock_data/data_provider/core/types.py` — `RealtimeSource` enum (we'll add `ZZSHARE = "zzshare"` in Task 5)
- `stock_data/api/schemas.py` — all response models already exist (DragonTigerResponse / ZTPoolResponse / etc.)
- `stock_data/explorer/tags.py` / `index.html` — all 10 capabilities already have labels/groups

---

## Task 1: ZzshareFetcher skeleton + availability

**Files:**
- Create: `tests/test_zzshare_fetcher.py`
- Create: `stock_data/data_provider/fetchers/zzshare_fetcher.py`

- [ ] **Step 1: Write the failing availability tests**

Create `tests/test_zzshare_fetcher.py`:

```python
"""Unit tests for ZzshareFetcher — structural + per-capability.

All tests mock the DataApi SDK (no real network/token).
"""
import importlib
import os
from unittest.mock import MagicMock, patch

import pytest

from stock_data.data_provider.base import DataCapability, DataFetchError
from stock_data.data_provider.fetchers.zzshare_fetcher import ZzshareFetcher


# ====================================================================
# Metadata + availability
# ====================================================================

class TestZzshareFetcherMetadata:
    def test_name(self):
        assert ZzshareFetcher.name == "ZzshareFetcher"

    def test_priority_default(self, monkeypatch):
        monkeypatch.delenv("ZZSHARE_PRIORITY", raising=False)
        assert ZzshareFetcher.priority == 5

    def test_priority_env_override(self, monkeypatch):
        monkeypatch.setenv("ZZSHARE_PRIORITY", "3")
        from stock_data.data_provider.fetchers import zzshare_fetcher
        importlib.reload(zzshare_fetcher)
        try:
            assert zzshare_fetcher.ZzshareFetcher.priority == 3
        finally:
            monkeypatch.delenv("ZZSHARE_PRIORITY", raising=False)
            importlib.reload(zzshare_fetcher)

    def test_supported_markets(self):
        assert ZzshareFetcher.supported_markets == {"csi"}

    def test_supported_data_types_all_10_caps(self):
        expected = {
            DataCapability.HISTORICAL_DWM,
            DataCapability.HISTORICAL_MIN,
            DataCapability.REALTIME_QUOTE,
            DataCapability.STOCK_LIST,
            DataCapability.TRADE_CALENDAR,
            DataCapability.STOCK_BOARD,
            DataCapability.STOCK_ZT_POOL,
            DataCapability.DRAGON_TIGER,
            DataCapability.HOT_TOPICS,
            DataCapability.STOCK_INFO,
        }
        assert ZzshareFetcher.supported_data_types == expected


class TestZzshareFetcherAvailability:
    def test_is_available_false_when_sdk_missing(self, monkeypatch):
        monkeypatch.delenv("ZZSHARE_TOKEN", raising=False)
        with patch("importlib.util.find_spec", return_value=None):
            fetcher = ZzshareFetcher()
            assert fetcher.is_available() is False

    def test_is_available_true_when_sdk_present_no_token(self, monkeypatch):
        monkeypatch.delenv("ZZSHARE_TOKEN", raising=False)
        with patch("importlib.util.find_spec", return_value=MagicMock()):
            fetcher = ZzshareFetcher()
            assert fetcher.is_available() is True

    def test_is_available_true_when_sdk_and_token(self, monkeypatch):
        monkeypatch.setenv("ZZSHARE_TOKEN", "test-token-123")
        with patch("importlib.util.find_spec", return_value=MagicMock()):
            fetcher = ZzshareFetcher()
            assert fetcher.is_available() is True

    def test_unavailable_reason_mentions_sdk_when_missing(self, monkeypatch):
        monkeypatch.delenv("ZZSHARE_TOKEN", raising=False)
        with patch("importlib.util.find_spec", return_value=None):
            fetcher = ZzshareFetcher()
            reason = fetcher.unavailable_reason()
            assert reason is not None
            assert "DataApi" in reason or "SDK" in reason


class TestKLineMethodsRaise:
    def test_fetch_raw_data_raises_for_unsupported_freq(self):
        fetcher = ZzshareFetcher()
        with pytest.raises(DataFetchError, match="不支持.*周.*月"):
            fetcher._fetch_raw_data("600519", "2026-05-01", "2026-05-31", frequency="w")

    def test_fetch_raw_data_raises_for_unsupported_freq_monthly(self):
        fetcher = ZzshareFetcher()
        with pytest.raises(DataFetchError, match="不支持.*周.*月"):
            fetcher._fetch_raw_data("600519", "2026-05-01", "2026-05-31", frequency="m")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_zzshare_fetcher.py -v`
Expected: `ModuleNotFoundError: No module named 'stock_data.data_provider.fetchers.zzshare_fetcher'`

- [ ] **Step 3: Create the skeleton fetcher**

Create `stock_data/data_provider/fetchers/zzshare_fetcher.py`:

```python
"""
zzshare fetcher for A-share multi-capability (Priority 5, default).

API: DataApi Python SDK (https://github.com/zzquant/zzshare)
Token configured via ZZSHARE_TOKEN environment variable (anonymous also works
for most endpoints — see docs/zzshare/10-rate-limits.md).

Most endpoints are anonymous-capable; only stock_info and uplimit_stocks
require a token. The fetcher is_available() returns True as long as the
SDK is importable, even without a token.
"""

import importlib.util
import logging
import os
from typing import Any

import pandas as pd

from ..base import BaseFetcher, DataCapability, DataFetchError
from ..core.types import RealtimeSource, UnifiedRealtimeQuote, safe_float, safe_int
from ..utils.normalize import normalize_stock_code

logger = logging.getLogger(__name__)


def _to_zzshare_ts_code(code: str) -> str:
    """Convert 6-digit A-share code to tushare-style ts_code suffix.

    Rules (from docs/zzshare/README.md §「股票代码格式」):
        6/68/5 -> .SH
        0/3/1  -> .SZ
        8/4/2/9 -> .BJ
    """
    c = code.strip()
    if c.startswith(("6", "68", "5")):
        return f"{c}.SH"
    if c.startswith(("0", "3", "1")):
        return f"{c}.SZ"
    if c.startswith(("8", "4", "2", "9")):
        return f"{c}.BJ"
    return c  # 兜底: 无法识别时不加后缀


def _add_exchange_suffix(stock_code: str) -> str:
    """6-digit bare code -> '600519.SH' style (same rules as _to_zzshare_ts_code)."""
    return _to_zzshare_ts_code(stock_code)


def _to_yyyymmdd(date: str) -> str:
    """'2026-05-20' -> '20260520' (strips dashes).

    Pass-through for already-formatted YYYYMMDD strings.
    """
    return date.replace("-", "")


def _from_yyyymmdd(date: str) -> str:
    """'20260520' -> '2026-05-20' (inserts dashes).

    Pass-through for already-formatted YYYY-MM-DD strings.
    """
    if len(date) == 8 and date.isdigit():
        return f"{date[:4]}-{date[4:6]}-{date[6:8]}"
    return date


def _ensure_api(self_ref) -> Any:
    """Lazy-init the DataApi SDK; caches in self_ref._api.

    Returns the DataApi instance, or None if SDK is missing. Records
    the specific init failure into self_ref._init_error for
    unavailable_reason() reporting.
    """
    if self_ref._api is not None:
        return self_ref._api
    if importlib.util.find_spec("DataApi") is None:
        self_ref._init_error = "DataApi SDK not importable"
        return None
    try:
        from DataApi import DataApi  # type: ignore

        if self_ref._token:
            self_ref._api = DataApi(token=self_ref._token)
        else:
            self_ref._api = DataApi()
        self_ref._init_error = None
        return self_ref._api
    except Exception as e:
        self_ref._init_error = f"DataApi init failed: {e}"
        logger.warning("[ZzshareFetcher] %s", self_ref._init_error)
        return None


class ZzshareFetcher(BaseFetcher):
    """zzshare SDK fetcher — A-share multi-capability (priority 5)."""

    name = "ZzshareFetcher"
    priority = int(os.getenv("ZZSHARE_PRIORITY", "5"))
    supported_markets: set[str] = {"csi"}
    supported_data_types = (
        DataCapability.HISTORICAL_DWM
        | DataCapability.HISTORICAL_MIN
        | DataCapability.REALTIME_QUOTE
        | DataCapability.STOCK_LIST
        | DataCapability.TRADE_CALENDAR
        | DataCapability.STOCK_BOARD
        | DataCapability.STOCK_ZT_POOL
        | DataCapability.DRAGON_TIGER
        | DataCapability.HOT_TOPICS
        | DataCapability.STOCK_INFO
    )

    def __init__(self):
        self._token = os.getenv("ZZSHARE_TOKEN", "").strip()
        self._api = None
        self._init_error: str | None = None

    def is_available(self) -> bool:
        """True iff DataApi SDK is importable. Token is optional.

        Mirrors the akshare pattern: probe via importlib.util.find_spec so
        the manager can skip this fetcher cleanly when DataApi isn't
        installed. Token is checked lazily inside per-method calls.
        """
        return importlib.util.find_spec("DataApi") is not None

    def unavailable_reason(self) -> str | None:
        if self.is_available():
            return None
        return f"{self.name} unavailable: DataApi SDK not installed (pip install DataApi)"

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
                f"ZzshareFetcher 不支持 {frequency} 线 (仅日线 daily)"
            )
        api = _ensure_api(self)
        if api is None:
            raise DataFetchError(
                f"ZzshareFetcher DataApi SDK 不可用: {self._init_error}"
            )
        ts_code = _to_zzshare_ts_code(normalize_stock_code(stock_code))
        kwargs: dict = {
            "ts_code": ts_code,
            "start_date": _to_yyyymmdd(start_date),
            "end_date": _to_yyyymmdd(end_date),
        }
        if adjust:
            kwargs["adj"] = adjust
        return api.daily(**kwargs)

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
        keep = ["code"] + [c for c in [
            "date", "open", "high", "low", "close",
            "volume", "amount", "pct_chg",
        ] if c in df.columns]
        return df[[c for c in keep if c in df.columns]]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_zzshare_fetcher.py::TestZzshareFetcherMetadata tests/test_zzshare_fetcher.py::TestZzshareFetcherAvailability tests/test_zzshare_fetcher.py::TestKLineMethodsRaise -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
cd E:/GitRepo/stock_data
git add stock_data/data_provider/fetchers/zzshare_fetcher.py tests/test_zzshare_fetcher.py
git commit -m "feat(zzshare): add ZzshareFetcher skeleton with 10 capabilities + is_available gating"
```

---

## Task 2: Helper functions unit tests

The helpers (`_to_zzshare_ts_code`, `_to_yyyymmdd`, etc.) are in Task 1's skeleton but untested. This task adds focused unit tests for them.

**Files:**
- Modify: `tests/test_zzshare_fetcher.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_zzshare_fetcher.py`:

```python
# ====================================================================
# Helpers
# ====================================================================

class TestToZzshareTsCode:
    def test_shanghai_main(self):
        from stock_data.data_provider.fetchers.zzshare_fetcher import _to_zzshare_ts_code
        assert _to_zzshare_ts_code("600519") == "600519.SH"

    def test_shanghai_star(self):
        from stock_data.data_provider.fetchers.zzshare_fetcher import _to_zzshare_ts_code
        assert _to_zzshare_ts_code("688981") == "688981.SH"

    def test_shenzhen_main(self):
        from stock_data.data_provider.fetchers.zzshare_fetcher import _to_zzshare_ts_code
        assert _to_zzshare_ts_code("000001") == "000001.SZ"

    def test_chinext(self):
        from stock_data.data_provider.fetchers.zzshare_fetcher import _to_zzshare_ts_code
        assert _to_zzshare_ts_code("300750") == "300750.SZ"

    def test_beijing(self):
        from stock_data.data_provider.fetchers.zzshare_fetcher import _to_zzshare_ts_code
        assert _to_zzshare_ts_code("830799") == "830799.BJ"

    def test_passthrough_unrecognized(self):
        from stock_data.data_provider.fetchers.zzshare_fetcher import _to_zzshare_ts_code
        assert _to_zzshare_ts_code("XYZ") == "XYZ"


class TestToYyyymmdd:
    def test_with_dashes(self):
        from stock_data.data_provider.fetchers.zzshare_fetcher import _to_yyyymmdd
        assert _to_yyyymmdd("2026-05-20") == "20260520"

    def test_passthrough_yyyymmdd(self):
        from stock_data.data_provider.fetchers.zzshare_fetcher import _to_yyyymmdd
        assert _to_yyyymmdd("20260520") == "20260520"


class TestFromYyyymmdd:
    def test_eight_digits(self):
        from stock_data.data_provider.fetchers.zzshare_fetcher import _from_yyyymmdd
        assert _from_yyyymmdd("20260520") == "2026-05-20"

    def test_passthrough_with_dashes(self):
        from stock_data.data_provider.fetchers.zzshare_fetcher import _from_yyyymmdd
        assert _from_yyyymmdd("2026-05-20") == "2026-05-20"

    def test_other_format_passthrough(self):
        from stock_data.data_provider.fetchers.zzshare_fetcher import _from_yyyymmdd
        assert _from_yyyymmdd("garbage") == "garbage"
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_zzshare_fetcher.py::TestToZzshareTsCode tests/test_zzshare_fetcher.py::TestToYyyymmdd tests/test_zzshare_fetcher.py::TestFromYyyymmdd -v`
Expected: All PASS (helpers already in skeleton from Task 1)

- [ ] **Step 3: Commit**

```bash
cd E:/GitRepo/stock_data
git add tests/test_zzshare_fetcher.py
git commit -m "test(zzshare): add unit tests for code/date helper functions"
```

---

## Task 3: Add `RealtimeSource.ZZSHARE` enum value

The `UnifiedRealtimeQuote.source` field needs a new enum value so REALTIME_QUOTE can identify zzshare as the origin.

**Files:**
- Modify: `stock_data/data_provider/core/types.py:42-51`

- [ ] **Step 1: Add enum value**

Open `stock_data/data_provider/core/types.py`, find the `RealtimeSource` enum and add `ZZSHARE = "zzshare"` between `TENCENT` and `FALLBACK`:

```python
class RealtimeSource(Enum):
    """Data source identifiers for realtime quotes."""

    TUSHARE = "tushare"
    AKSHARE = "akshare"
    YFINANCE = "yfinance"
    STOOQ = "stooq"
    ZHITU = "zhitu"
    TENCENT = "tencent"
    ZZSHARE = "zzshare"   # NEW
    MYQUANT = "myquant"
    FALLBACK = "fallback"
```

- [ ] **Step 2: Verify import works**

Run: `.venv/Scripts/python.exe -c "from stock_data.data_provider.core.types import RealtimeSource; print(RealtimeSource.ZZSHARE.value)"`
Expected: `zzshare`

- [ ] **Step 3: Commit**

```bash
cd E:/GitRepo/stock_data
git add stock_data/data_provider/core/types.py
git commit -m "feat(types): add RealtimeSource.ZZSHARE enum value"
```

---

## Task 4: Daily K-line normalization tests + implementation

The skeleton has `_fetch_raw_data` raising for non-daily and `_normalize_data` doing the column rename. This task adds comprehensive tests for the actual daily fetch + normalize round-trip.

**Files:**
- Modify: `tests/test_zzshare_fetcher.py` (append)
- Modify: `stock_data/data_provider/fetchers/zzshare_fetcher.py` (verify behavior)

- [ ] **Step 1: Write the failing daily K-line tests**

Append to `tests/test_zzshare_fetcher.py`:

```python
# ====================================================================
# K-line (HISTORICAL_DWM)
# ====================================================================

class TestDailyKline:
    def _fetcher_with_api(self, fake_daily):
        """Helper: return fetcher with DataApi.daily mocked."""
        fetcher = ZzshareFetcher()
        fake_api = MagicMock()
        fake_api.daily = MagicMock(return_value=fake_daily)
        fetcher._api = fake_api
        return fetcher

    def test_daily_normalizes_columns(self):
        import pandas as pd
        raw = pd.DataFrame({
            "ts_code": ["600519.SH"] * 3,
            "trade_date": ["20260501", "20260502", "20260503"],
            "open": [1700.0, 1710.0, 1720.0],
            "high": [1715.0, 1725.0, 1735.0],
            "low": [1695.0, 1705.0, 1715.0],
            "close": [1710.0, 1720.0, 1730.0],
            "pre_close": [1700.0, 1710.0, 1720.0],
            "change": [10.0, 10.0, 10.0],
            "pct_chg": [0.59, 0.58, 0.58],
            "vol": [1e6, 1.1e6, 1.2e6],
            "amount": [1e9, 1.1e9, 1.2e9],
        })
        fetcher = self._fetcher_with_api(raw)
        df = fetcher.get_kline_data("600519", "2026-05-01", "2026-05-03")
        # Required STANDARD_COLUMNS present
        for col in ["date", "open", "high", "low", "close", "volume", "amount", "pct_chg"]:
            assert col in df.columns, f"missing {col}"
        # vol -> volume rename
        assert "vol" not in df.columns
        # trade_date -> date (YYYY-MM-DD format)
        assert str(df.iloc[0]["date"])[:10] == "2026-05-01"
        # code column added
        assert "code" in df.columns
        assert df.iloc[0]["code"] == "600519"
        # pct_chg passed through
        assert abs(df.iloc[0]["pct_chg"] - 0.59) < 0.01

    def test_daily_passes_yyyymmdd_to_sdk(self):
        import pandas as pd
        raw = pd.DataFrame({"ts_code": ["600519.SH"], "trade_date": ["20260501"],
                            "open": [1700.0], "high": [1715.0], "low": [1695.0],
                            "close": [1710.0], "vol": [1e6], "amount": [1e9],
                            "pct_chg": [0.59]})
        fetcher = self._fetcher_with_api(raw)
        fetcher.get_kline_data("600519", "2026-05-01", "2026-05-03")
        call = fetcher._api.daily.call_args
        # start_date/end_date converted to YYYYMMDD
        assert call.kwargs["start_date"] == "20260501"
        assert call.kwargs["end_date"] == "20260503"
        # ts_code formatted with .SH suffix
        assert call.kwargs["ts_code"] == "600519.SH"

    def test_daily_qfq_adjust_passes_through(self):
        import pandas as pd
        raw = pd.DataFrame({"ts_code": ["600519.SH"], "trade_date": ["20260501"],
                            "open": [1700.0], "high": [1715.0], "low": [1695.0],
                            "close": [1710.0], "vol": [1e6], "amount": [1e9],
                            "pct_chg": [0.59]})
        fetcher = self._fetcher_with_api(raw)
        fetcher.get_kline_data("600519", "2026-05-01", "2026-05-03", adjust="qfq")
        call = fetcher._api.daily.call_args
        assert call.kwargs.get("adj") == "qfq"

    def test_daily_no_adjust_does_not_pass_adj(self):
        import pandas as pd
        raw = pd.DataFrame({"ts_code": ["600519.SH"], "trade_date": ["20260501"],
                            "open": [1700.0], "high": [1715.0], "low": [1695.0],
                            "close": [1710.0], "vol": [1e6], "amount": [1e9],
                            "pct_chg": [0.59]})
        fetcher = self._fetcher_with_api(raw)
        fetcher.get_kline_data("600519", "2026-05-01", "2026-05-03")
        call = fetcher._api.daily.call_args
        assert "adj" not in call.kwargs

    def test_daily_empty_df_returns_empty(self):
        import pandas as pd
        fetcher = self._fetcher_with_api(pd.DataFrame())
        df = fetcher.get_kline_data("600519", "2026-05-01", "2026-05-03")
        assert df.empty
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_zzshare_fetcher.py::TestDailyKline -v`
Expected: All PASS (skeleton from Task 1 already implements this correctly)

- [ ] **Step 3: Commit**

```bash
cd E:/GitRepo/stock_data
git add tests/test_zzshare_fetcher.py
git commit -m "test(zzshare): add daily K-line normalization round-trip tests"
```

---

## Task 5: Minute K-line implementation + tests

**Files:**
- Modify: `stock_data/data_provider/fetchers/zzshare_fetcher.py` (add `get_intraday_data`)
- Modify: `tests/test_zzshare_fetcher.py` (append)

- [ ] **Step 1: Write the failing minute K-line tests**

Append to `tests/test_zzshare_fetcher.py`:

```python
# ====================================================================
# K-line (HISTORICAL_MIN) — get_intraday_data
# ====================================================================

class TestIntradayKline:
    def _fetcher_with_api(self, fake_stk_mins):
        fetcher = ZzshareFetcher()
        fake_api = MagicMock()
        fake_api.stk_mins = MagicMock(return_value=fake_stk_mins)
        fetcher._api = fake_api
        return fetcher

    def test_intraday_normalizes_time(self):
        import pandas as pd
        raw = pd.DataFrame({
            "ts_code": ["600519.SH"] * 3,
            "trade_time": ["202605200935", "202605200940", "202605200945"],
            "open": [1700.0, 1705.0, 1710.0],
            "high": [1708.0, 1712.0, 1717.0],
            "low": [1698.0, 1702.0, 1708.0],
            "close": [1705.0, 1710.0, 1715.0],
            "vol": [1e5, 1.1e5, 1.2e5],
            "amount": [1e8, 1.1e8, 1.2e8],
        })
        fetcher = self._fetcher_with_api(raw)
        df = fetcher.get_intraday_data("600519", period="5")
        assert "time" in df.columns
        assert list(df["time"]) == ["09:35:00", "09:40:00", "09:45:00"]
        assert "vol" not in df.columns
        assert "volume" in df.columns

    def test_intraday_period_to_freq(self):
        import pandas as pd
        raw = pd.DataFrame({"ts_code": ["600519.SH"], "trade_time": ["202605200935"],
                            "open": [1700.0], "high": [1708.0], "low": [1698.0],
                            "close": [1705.0], "vol": [1e5], "amount": [1e8]})
        fetcher = self._fetcher_with_api(raw)
        fetcher.get_intraday_data("600519", period="15")
        call = fetcher._api.stk_mins.call_args
        assert call.kwargs.get("freq") == "15min"

    def test_intraday_adjust_ignored(self):
        """Minute K has no adjust — adjust param should not be passed."""
        import pandas as pd
        raw = pd.DataFrame({"ts_code": ["600519.SH"], "trade_time": ["202605200935"],
                            "open": [1700.0], "high": [1708.0], "low": [1698.0],
                            "close": [1705.0], "vol": [1e5], "amount": [1e8]})
        fetcher = self._fetcher_with_api(raw)
        fetcher.get_intraday_data("600519", period="5", adjust="qfq")
        call = fetcher._api.stk_mins.call_args
        assert "adj" not in call.kwargs
        assert "adjust" not in call.kwargs

    def test_intraday_date_converted_to_yyyymmdd(self):
        import pandas as pd
        raw = pd.DataFrame({"ts_code": ["600519.SH"], "trade_time": ["202605200935"],
                            "open": [1700.0], "high": [1708.0], "low": [1698.0],
                            "close": [1705.0], "vol": [1e5], "amount": [1e8]})
        fetcher = self._fetcher_with_api(raw)
        fetcher.get_intraday_data("600519", period="5")
        call = fetcher._api.stk_mins.call_args
        # The base fetcher calls get_intraday_data with start_date from days=2 default;
        # we verify the date string passed to SDK is in YYYYMMDD format
        assert call.kwargs.get("trade_time", "").replace("-", "") == call.kwargs.get("trade_time", "")

    def test_intraday_no_token_returns_empty(self, monkeypatch):
        """When SDK is not available, get_intraday_data returns None per BaseFetcher contract."""
        monkeypatch.delenv("ZZSHARE_TOKEN", raising=False)
        with patch("importlib.util.find_spec", return_value=None):
            fetcher = ZzshareFetcher()
            result = fetcher.get_intraday_data("600519", period="5")
            assert result is None
```

- [ ] **Step 2: Run tests to verify they fail (get_intraday_data not implemented yet)**

Run: `.venv/Scripts/python.exe -m pytest tests/test_zzshare_fetcher.py::TestIntradayKline -v`
Expected: First 4 tests FAIL (intraday uses default BaseFetcher returning None)

- [ ] **Step 3: Implement get_intraday_data**

Open `stock_data/data_provider/fetchers/zzshare_fetcher.py` and add `get_intraday_data` after the `_normalize_data` method:

```python
    # Minute-period -> zzshare freq mapping
    _PERIOD_TO_FREQ: dict[str, str] = {
        "1": "1min",
        "5": "5min",
        "15": "15min",
        "30": "30min",
        "60": "60min",
    }

    def get_intraday_data(
        self, stock_code: str, period: str = "5", adjust: str = ""
    ) -> pd.DataFrame | None:
        """Fetch minute K-line from zzshare (period=1/5/15/30/60).

        Note: zzshare minute K does not support adjust — the ``adjust`` param
        is accepted for interface symmetry but is not forwarded to the SDK.
        """
        from datetime import datetime, timedelta

        api = _ensure_api(self)
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
            # YYYYMMDDHHMM (12 digits) -> HH:MM:SS
            df["time"] = df["trade_time"].astype(str).str[-6:].apply(
                lambda s: f"{s[:2]}:{s[2:4]}:{s[4:6]}" if len(s) == 6 else s
            )
            df = df.drop(columns=["trade_time"])
        keep = ["time", "open", "high", "low", "close", "volume", "amount"]
        df = df[[c for c in keep if c in df.columns]]
        return df
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_zzshare_fetcher.py::TestIntradayKline -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
cd E:/GitRepo/stock_data
git add stock_data/data_provider/fetchers/zzshare_fetcher.py tests/test_zzshare_fetcher.py
git commit -m "feat(zzshare): add get_intraday_data (HISTORICAL_MIN) with period->freq mapping"
```

---

## Task 6: Real-time quote implementation + tests

**Files:**
- Modify: `stock_data/data_provider/fetchers/zzshare_fetcher.py` (add `get_realtime_quote`)
- Modify: `tests/test_zzshare_fetcher.py` (append)

- [ ] **Step 1: Write the failing realtime quote tests**

Append to `tests/test_zzshare_fetcher.py`:

```python
# ====================================================================
# REALTIME_QUOTE
# ====================================================================

class TestRealtimeQuote:
    def _fetcher_with_api(self, fake_rt_k):
        fetcher = ZzshareFetcher()
        fake_api = MagicMock()
        fake_api.rt_k = MagicMock(return_value=fake_rt_k)
        fetcher._api = fake_api
        return fetcher

    def test_realtime_basic_fields(self):
        import pandas as pd
        raw = pd.DataFrame([{
            "ts_code": "600519.SH",
            "name": "贵州茅台",
            "pre_close": 1700.0,
            "open": 1710.0, "high": 1725.0, "low": 1695.0, "close": 1720.0,
            "vol": 1e6, "amount": 1e9,
            "quote_rate": 1.18,
            "turnover_rate": 0.5,
            "high_limit": 1870.0, "low_limit": 1530.0,
            "market_value": 2.16e12,
            "circulation_value": 2.16e12,
            "ttm_pe_rate": 25.5,
        }])
        fetcher = self._fetcher_with_api(raw)
        quote = fetcher.get_realtime_quote("600519")
        assert quote is not None
        assert quote.code == "600519"
        assert quote.name == "贵州茅台"
        assert quote.source.value == "zzshare"
        assert quote.price == 1720.0
        assert quote.change_pct == 1.18
        assert quote.pre_close == 1700.0
        assert quote.open_price == 1710.0
        assert quote.total_mv == 2.16e12
        assert quote.circ_mv == 2.16e12
        assert quote.pe_ratio == 25.5
        assert quote.turnover_rate == 0.5

    def test_realtime_uses_fields_all(self):
        import pandas as pd
        raw = pd.DataFrame([{"ts_code": "600519.SH", "name": "茅台", "close": 1720.0,
                             "pre_close": 1700.0, "open": 1710.0, "high": 1725.0,
                             "low": 1695.0, "vol": 1e6, "amount": 1e9,
                             "quote_rate": 1.18, "turnover_rate": 0.5,
                             "market_value": 2.16e12, "circulation_value": 2.16e12,
                             "ttm_pe_rate": 25.5}])
        fetcher = self._fetcher_with_api(raw)
        fetcher.get_realtime_quote("600519")
        call = fetcher._api.rt_k.call_args
        # Enhanced fields mode requested
        assert call.kwargs.get("fields") == "all"

    def test_realtime_empty_df_returns_none(self):
        import pandas as pd
        fetcher = self._fetcher_with_api(pd.DataFrame())
        assert fetcher.get_realtime_quote("600519") is None

    def test_realtime_sdk_unavailable_returns_none(self, monkeypatch):
        monkeypatch.delenv("ZZSHARE_TOKEN", raising=False)
        with patch("importlib.util.find_spec", return_value=None):
            fetcher = ZzshareFetcher()
            assert fetcher.get_realtime_quote("600519") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_zzshare_fetcher.py::TestRealtimeQuote -v`
Expected: All FAIL (default returns None)

- [ ] **Step 3: Implement get_realtime_quote**

Open `stock_data/data_provider/fetchers/zzshare_fetcher.py` and add `get_realtime_quote`:

```python
    def get_realtime_quote(self, stock_code: str) -> UnifiedRealtimeQuote | None:
        """Fetch realtime snapshot from zzshare rt_k(fields='all').

        Returns None if SDK unavailable or upstream returns empty.
        """
        api = _ensure_api(self)
        if api is None:
            return None
        ts_code = _to_zzshare_ts_code(normalize_stock_code(stock_code))
        try:
            df = api.rt_k(ts_code=ts_code, fields="all")
        except Exception as e:
            logger.warning(f"[ZzshareFetcher] rt_k({ts_code}) failed: {e}")
            return None
        if df is None or df.empty:
            return None
        row = df.iloc[0].to_dict()
        return UnifiedRealtimeQuote(
            code=normalize_stock_code(stock_code),
            name=str(row.get("name", "")),
            source=RealtimeSource.ZZSHARE,
            price=safe_float(row.get("close")),
            change_pct=safe_float(row.get("quote_rate")),
            change_amount=safe_float(row.get("close")) and safe_float(row.get("pre_close"))
                          and (safe_float(row.get("close")) - safe_float(row.get("pre_close"))),
            volume=safe_int(row.get("vol")),
            amount=safe_float(row.get("amount")),
            open_price=safe_float(row.get("open")),
            high=safe_float(row.get("high")),
            low=safe_float(row.get("low")),
            pre_close=safe_float(row.get("pre_close")),
            turnover_rate=safe_float(row.get("turnover_rate")),
            total_mv=safe_float(row.get("market_value")),
            circ_mv=safe_float(row.get("circulation_value")),
            pe_ratio=safe_float(row.get("ttm_pe_rate")),
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_zzshare_fetcher.py::TestRealtimeQuote -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
cd E:/GitRepo/stock_data
git add stock_data/data_provider/fetchers/zzshare_fetcher.py tests/test_zzshare_fetcher.py
git commit -m "feat(zzshare): add get_realtime_quote with UnifiedRealtimeQuote mapping"
```

---

## Task 7: Stock list implementation + tests

**Files:**
- Modify: `stock_data/data_provider/fetchers/zzshare_fetcher.py` (add `get_all_stocks`)
- Modify: `tests/test_zzshare_fetcher.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_zzshare_fetcher.py`:

```python
# ====================================================================
# STOCK_LIST
# ====================================================================

class TestStockList:
    def _fetcher_with_api(self, fake_basic):
        fetcher = ZzshareFetcher()
        fake_api = MagicMock()
        fake_basic_obj = MagicMock(return_value=fake_basic)
        fake_api.stock_basic = fake_basic_obj
        fetcher._api = fake_api
        return fetcher, fake_basic_obj

    def test_get_all_stocks_normalizes_exchange(self):
        import pandas as pd
        raw = pd.DataFrame({
            "ts_code": ["600519.SH", "000001.SZ", "830799.BJ"],
            "symbol": ["600519", "000001", "830799"],
            "name": ["贵州茅台", "平安银行", "殷图网联"],
            "exchange": ["SSE", "SZSE", "BSE"],
            "area": ["", "", ""],
            "industry": ["", "", ""],
            "list_date": ["", "", ""],
        })
        fetcher, _ = self._fetcher_with_api(raw)
        result = fetcher.get_all_stocks("csi")
        assert len(result) == 3
        assert result[0] == {"code": "600519", "name": "贵州茅台", "exchange": "SSE"}
        assert result[1] == {"code": "000001", "name": "平安银行", "exchange": "SZSE"}
        assert result[2] == {"code": "830799", "name": "殷图网联", "exchange": "BSE"}

    def test_get_all_stocks_non_csi_returns_empty(self):
        fetcher = ZzshareFetcher()
        # Even with SDK available, non-csi returns []
        with patch("importlib.util.find_spec", return_value=MagicMock()):
            assert fetcher.get_all_stocks("hk") == []
            assert fetcher.get_all_stocks("us") == []

    def test_get_all_stocks_calls_stock_basic_all(self):
        import pandas as pd
        raw = pd.DataFrame({"ts_code": ["600519.SH"], "symbol": ["600519"],
                            "name": ["贵州茅台"], "exchange": ["SSE"],
                            "area": [""], "industry": [""], "list_date": [""]})
        fetcher, fake = self._fetcher_with_api(raw)
        fetcher.get_all_stocks("csi")
        call = fake.call_args
        assert call.kwargs.get("exchange") == "ALL"
        assert call.kwargs.get("list_status") == "L"

    def test_get_all_stocks_sdk_unavailable_returns_empty(self, monkeypatch):
        monkeypatch.delenv("ZZSHARE_TOKEN", raising=False)
        with patch("importlib.util.find_spec", return_value=None):
            fetcher = ZzshareFetcher()
            assert fetcher.get_all_stocks("csi") == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_zzshare_fetcher.py::TestStockList -v`
Expected: FAIL (default returns [])

- [ ] **Step 3: Implement get_all_stocks**

Open `stock_data/data_provider/fetchers/zzshare_fetcher.py` and add `get_all_stocks`:

```python
    def get_all_stocks(self, market: str = "csi") -> list:
        """Fetch the A-share stock list from zzshare stock_basic(exchange='ALL').

        area/industry/list_date left empty (zzshare does not fill them; other
        fetchers will backfill via persistence layer).

        Returns [] on failure or non-csi market (manager failover keeps trying).
        """
        if market != "csi":
            return []
        api = _ensure_api(self)
        if api is None:
            return []
        try:
            df = api.stock_basic(exchange="ALL", list_status="L")
        except Exception as e:
            logger.warning(f"[ZzshareFetcher] stock_basic failed: {e}")
            return []
        if df is None or df.empty:
            return []
        out: list = []
        for _, row in df.iterrows():
            ts_code = str(row.get("ts_code", ""))
            if not ts_code:
                continue
            # ts_code like "600519.SH" -> bare "600519"
            code = ts_code.split(".")[0]
            out.append({
                "code": code,
                "name": str(row.get("name", "")),
                "exchange": str(row.get("exchange", "")),
            })
        return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_zzshare_fetcher.py::TestStockList -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
cd E:/GitRepo/stock_data
git add stock_data/data_provider/fetchers/zzshare_fetcher.py tests/test_zzshare_fetcher.py
git commit -m "feat(zzshare): add get_all_stocks (STOCK_LIST) with ts_code strip"
```

---

## Task 8: Trade calendar implementation + tests

**Files:**
- Modify: `stock_data/data_provider/fetchers/zzshare_fetcher.py` (add `get_trade_calendar`)
- Modify: `tests/test_zzshare_fetcher.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_zzshare_fetcher.py`:

```python
# ====================================================================
# TRADE_CALENDAR
# ====================================================================

class TestTradeCalendar:
    def _fetcher_with_api(self, fake_days):
        fetcher = ZzshareFetcher()
        fake_api = MagicMock()
        fake_api.trade_days = MagicMock(return_value=fake_days)
        fetcher._api = fake_api
        return fetcher

    def test_trade_calendar_passthrough(self):
        dates = ["2026-05-20", "2026-05-21", "2026-05-22"]
        fetcher = self._fetcher_with_api(dates)
        result = fetcher.get_trade_calendar()
        assert result == dates

    def test_trade_calendar_empty_returns_none(self):
        fetcher = self._fetcher_with_api([])
        assert fetcher.get_trade_calendar() is None

    def test_trade_calendar_sdk_unavailable_returns_none(self, monkeypatch):
        monkeypatch.delenv("ZZSHARE_TOKEN", raising=False)
        with patch("importlib.util.find_spec", return_value=None):
            fetcher = ZzshareFetcher()
            assert fetcher.get_trade_calendar() is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_zzshare_fetcher.py::TestTradeCalendar -v`
Expected: FAIL (default returns None)

- [ ] **Step 3: Implement get_trade_calendar**

Open `stock_data/data_provider/fetchers/zzshare_fetcher.py` and add `get_trade_calendar`:

```python
    def get_trade_calendar(self) -> list[str] | None:
        """Fetch recent N trade dates from zzshare trade_days(days=10).

        Returns list of YYYY-MM-DD strings (already formatted by SDK),
        or None on failure.
        """
        api = _ensure_api(self)
        if api is None:
            return None
        try:
            dates = api.trade_days(days=10)
        except Exception as e:
            logger.warning(f"[ZzshareFetcher] trade_days failed: {e}")
            return None
        if not dates:
            return None
        return list(dates)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_zzshare_fetcher.py::TestTradeCalendar -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
cd E:/GitRepo/stock_data
git add stock_data/data_provider/fetchers/zzshare_fetcher.py tests/test_zzshare_fetcher.py
git commit -m "feat(zzshare): add get_trade_calendar (TRADE_CALENDAR)"
```

---

## Task 9: Stock info implementation + tests

**Files:**
- Modify: `stock_data/data_provider/fetchers/zzshare_fetcher.py` (add `get_stock_info`)
- Modify: `tests/test_zzshare_fetcher.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_zzshare_fetcher.py`:

```python
# ====================================================================
# STOCK_INFO
# ====================================================================

class TestStockInfo:
    def _fetcher_with_api(self, fake_info):
        fetcher = ZzshareFetcher()
        fake_api = MagicMock()
        fake_api.stock_info = MagicMock(return_value=fake_info)
        fetcher._api = fake_api
        return fetcher

    def test_stock_info_returns_normalized_dict(self):
        raw = {
            "name": "贵州茅台",
            "ename": "Kweichow Moutai Co.,Ltd.",
            "ldate": "2001-08-27",
            "totalstock": 1256197800,
            "flowstock": 1256197800,
            "idea": "白酒, 消费, 蓝筹",
            "raddr": "贵州省遵义市",
            "rcapital": "100000万人民币",
            "rname": "丁雄军",
            "bscope": "酒类生产与销售...",
            "rdate": "1999-11-20",
            "bsname": "蒋焰",
            "bsphone": "0851-22386000",
            "bsemail": "mt@maotaichina.com",
        }
        fetcher = self._fetcher_with_api(raw)
        info = fetcher.get_stock_info("600519")
        assert info is not None
        assert info["code"] == "600519"
        assert info["name"] == "贵州茅台"
        assert info["market"] == "csi"
        assert info["listed_date"] == "2001-08-27"
        assert info["total_shares"] == 1256197800
        assert "白酒" in info["concepts"]

    def test_stock_info_concepts_deduped(self):
        raw = {
            "name": "Test", "ename": "", "ldate": "", "totalstock": 0, "flowstock": 0,
            "idea": "白酒, 消费, 白酒, 消费",
            "raddr": "", "rcapital": "", "rname": "", "bscope": "",
            "rdate": "", "bsname": "", "bsphone": "", "bsemail": "",
        }
        fetcher = self._fetcher_with_api(raw)
        info = fetcher.get_stock_info("000001")
        # Duplicates removed, order preserved
        assert info["concepts"] == ["白酒", "消费"]

    def test_stock_info_no_token_returns_none(self, monkeypatch):
        """Without token, stock_info() returns None (other fetchers will cover)."""
        monkeypatch.delenv("ZZSHARE_TOKEN", raising=False)
        with patch("importlib.util.find_spec", return_value=None):
            fetcher = ZzshareFetcher()
            assert fetcher.get_stock_info("600519") is None

    def test_stock_info_empty_idea_yields_empty_concepts(self):
        raw = {
            "name": "Test", "ename": "", "ldate": "", "totalstock": 0, "flowstock": 0,
            "idea": "",
            "raddr": "", "rcapital": "", "rname": "", "bscope": "",
            "rdate": "", "bsname": "", "bsphone": "", "bsemail": "",
        }
        fetcher = self._fetcher_with_api(raw)
        info = fetcher.get_stock_info("000001")
        assert info["concepts"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_zzshare_fetcher.py::TestStockInfo -v`
Expected: FAIL (default returns None)

- [ ] **Step 3: Implement get_stock_info**

Open `stock_data/data_provider/fetchers/zzshare_fetcher.py` and add `get_stock_info` (mirror ZhituFetcher's shape):

```python
    def get_stock_info(self, stock_code: str) -> dict | None:
        """公司画像 — zzshare stock_info(stock_id, info_type=1).

        Returns 18-field dict matching ZhituFetcher.get_stock_info's shape.
        info_type=1 is the company-profile enum (README 探测确认可用).
        """
        from .zhitu_fetcher import _split_concepts  # reuse dedup helper
        api = _ensure_api(self)
        if api is None:
            return None
        code = normalize_stock_code(stock_code)
        try:
            data = api.stock_info(stock_id=code, info_type=1)
        except Exception as e:
            logger.warning(f"[ZzshareFetcher] stock_info({code}) failed: {e}")
            return None
        if not isinstance(data, dict):
            return None
        return {
            "code": code,
            "name": str(data.get("name", "") or ""),
            "ename": str(data.get("ename", "") or ""),
            "market": "csi",
            "listed_date": str(data.get("ldate", "") or ""),
            "delisted_date": "",
            "total_shares": safe_float(data.get("totalstock")),
            "float_shares": safe_float(data.get("flowstock")),
            "industry": "",
            "concepts": _split_concepts(data.get("idea", "")),
            "registered_address": str(data.get("raddr", "") or ""),
            "registered_capital": str(data.get("rcapital", "") or ""),
            "legal_representative": str(data.get("rname", "") or ""),
            "business_scope": str(data.get("bscope", "") or ""),
            "established_date": str(data.get("rdate", "") or ""),
            "secretary": str(data.get("bsname", "") or ""),
            "secretary_phone": str(data.get("bsphone", "") or ""),
            "secretary_email": str(data.get("bsemail", "") or ""),
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_zzshare_fetcher.py::TestStockInfo -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
cd E:/GitRepo/stock_data
git add stock_data/data_provider/fetchers/zzshare_fetcher.py tests/test_zzshare_fetcher.py
git commit -m "feat(zzshare): add get_stock_info (STOCK_INFO) mirroring ZhituFetcher 18-field shape"
```

---

## Task 10: ZT pool implementation + tests

**Files:**
- Modify: `stock_data/data_provider/fetchers/zzshare_fetcher.py` (add `get_zt_pool`)
- Modify: `tests/test_zzshare_fetcher.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_zzshare_fetcher.py`:

```python
# ====================================================================
# STOCK_ZT_POOL
# ====================================================================

class TestZtPool:
    def _fetcher_with_api(self, hot=None, stocks=None, hot_raises=False):
        fetcher = ZzshareFetcher()
        fake_api = MagicMock()
        if hot_raises:
            fake_api.uplimit_hot = MagicMock(side_effect=Exception("upstream error"))
        else:
            fake_api.uplimit_hot = MagicMock(return_value=hot if hot is not None else {})
        fake_api.uplimit_stocks = MagicMock(return_value=stocks if stocks is not None else [])
        fetcher._api = fake_api
        return fetcher

    def test_zt_pool_combines_hot_and_stocks(self):
        hot = {
            "plate": [
                ["芯片", "801001", 21973],
                ["机器人概念", "801159", 6292],
            ],
            "ban_info": {"1": {"count": 46}, "2": {"count": 5}},
            "max_count": 2,
        }
        stocks = [
            {"ts_code": "600519.SH", "name": "贵州茅台", "pct_chg": 10.0,
             "amount": 1e9, "circ_mv": 2e12, "total_mv": 2.2e12,
             "turnover_rate": 0.5, "lb_count": 1, "first_seal_time": "10:30",
             "last_seal_time": "14:55", "seal_amount": 5e8, "seal_count": 3,
             "zt_count": 1},
        ]
        fetcher = self._fetcher_with_api(hot=hot, stocks=stocks)
        result = fetcher.get_zt_pool("zt", "2026-05-20")
        assert result is not None
        # uplimit_stocks returns the primary list (matches ZTPoolResponse shape)
        assert len(result) == 1
        assert result[0]["code"] == "600519"
        assert result[0]["name"] == "贵州茅台"
        assert result[0]["change_pct"] == 10.0

    def test_zt_pool_no_token_still_returns_hot_data(self):
        """If uplimit_stocks raises (token-gated), still return non-empty."""
        hot = {
            "plate": [["芯片", "801001", 21973]],
            "ban_info": {}, "max_count": 0,
        }
        fetcher = self._fetcher_with_api(hot=hot, stocks=[])  # stocks is []
        result = fetcher.get_zt_pool("zt", "2026-05-20")
        # stocks=[] -> result is None (BaseFetcher contract: None on no data)
        assert result is None

    def test_zt_pool_hot_raises_returns_none(self):
        fetcher = self._fetcher_with_api(hot_raises=True)
        result = fetcher.get_zt_pool("zt", "2026-05-20")
        assert result is None

    def test_zt_pool_dt_returns_empty(self):
        """zzshare only supports zt via uplimit_* — dt/zbgc return None."""
        fetcher = self._fetcher_with_api()
        # dt not in pool_type_to_endpoint
        assert fetcher.get_zt_pool("dt", "2026-05-20") is None
        assert fetcher.get_zt_pool("zbgc", "2026-05-20") is None

    def test_zt_pool_sdk_unavailable_returns_none(self, monkeypatch):
        monkeypatch.delenv("ZZSHARE_TOKEN", raising=False)
        with patch("importlib.util.find_spec", return_value=None):
            fetcher = ZzshareFetcher()
            assert fetcher.get_zt_pool("zt", "2026-05-20") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_zzshare_fetcher.py::TestZtPool -v`
Expected: FAIL (default returns None)

- [ ] **Step 3: Implement get_zt_pool**

Open `stock_data/data_provider/fetchers/zzshare_fetcher.py` and add `get_zt_pool`:

```python
    # Pool type -> zzshare endpoint name
    _POOL_TYPE_MAP: dict[str, str] = {
        "zt": "uplimit_stocks",  # primary
    }

    def get_zt_pool(self, pool_type: str, date: str) -> list[dict] | None:
        """Fetch ZT pool from zzshare uplimit_stocks (token-gated).

        Falls back gracefully: if uplimit_stocks returns empty (no token or
        no data), returns None so the manager failover chain can try the
        next fetcher.
        """
        if pool_type not in self._POOL_TYPE_MAP:
            return None
        api = _ensure_api(self)
        if api is None:
            return None
        date_yyyymmdd = _to_yyyymmdd(date)
        try:
            rows = api.uplimit_stocks(date1=date_yyyymmdd)
        except Exception as e:
            logger.warning(f"[ZzshareFetcher] uplimit_stocks({date_yyyymmdd}) failed: {e}")
            return None
        if not rows:
            return None
        out: list[dict] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            ts_code = str(row.get("ts_code", ""))
            out.append({
                "code": ts_code.split(".")[0] if ts_code else "",
                "name": str(row.get("name", "")),
                "price": safe_float(row.get("price") or row.get("p")),
                "change_pct": safe_float(row.get("pct_chg")),
                "amount": safe_float(row.get("amount")),
                "circ_mv": safe_float(row.get("circ_mv") or row.get("lt")),
                "total_mv": safe_float(row.get("total_mv") or row.get("zsz")),
                "turnover_rate": safe_float(row.get("turnover_rate")),
                "lb_count": safe_int(row.get("lb_count")),
                "first_seal_time": str(row.get("first_seal_time", "")),
                "last_seal_time": str(row.get("last_seal_time", "")),
                "seal_amount": safe_float(row.get("seal_amount")),
                "seal_count": safe_int(row.get("seal_count")),
                "zt_count": safe_int(row.get("zt_count")),
            })
        return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_zzshare_fetcher.py::TestZtPool -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
cd E:/GitRepo/stock_data
git add stock_data/data_provider/fetchers/zzshare_fetcher.py tests/test_zzshare_fetcher.py
git commit -m "feat(zzshare): add get_zt_pool (STOCK_ZT_POOL) for zt pool"
```

---

## Task 11: Boards — 4 methods implementation + tests

**Files:**
- Modify: `stock_data/data_provider/fetchers/zzshare_fetcher.py` (add 4 board methods)
- Modify: `tests/test_zzshare_fetcher.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_zzshare_fetcher.py`:

```python
# ====================================================================
# STOCK_BOARD (4 methods)
# ====================================================================

# zzshare plate_type -> project (type, subtype)
_PLATE_TYPE_MAP: dict[int, tuple[str, str]] = {
    14: ("industry", "同花顺行业"),
    15: ("concept", "同花顺概念"),
    17: ("special", "同花顺题材"),
}


class TestBoards:
    def _fetcher_with_api(self, **mocks):
        fetcher = ZzshareFetcher()
        fake_api = MagicMock()
        for name, value in mocks.items():
            setattr(fake_api, name, MagicMock(return_value=value))
        fetcher._api = fake_api
        return fetcher

    def test_get_all_boards_concept_via_15(self):
        rows = [
            {"plate_code": "801001", "plate_name": "芯片", "plate_type": 15, "rate": 1.5},
            {"plate_code": "801660", "plate_name": "通信", "plate_type": 15, "rate": 0.8},
        ]
        fetcher = self._fetcher_with_api(plates_list=rows)
        boards = fetcher.get_all_boards(board_type="concept", subtype="同花顺概念", source="zzshare")
        assert len(boards) == 2
        assert boards[0]["code"] == "801001"
        assert boards[0]["name"] == "芯片"
        assert boards[0]["type"] == "concept"
        assert boards[0]["subtype"] == "同花顺概念"

    def test_get_all_boards_filters_by_subtype(self):
        rows = [
            {"plate_code": "801001", "plate_name": "芯片", "plate_type": 15, "rate": 1.5},
            {"plate_code": "881121", "plate_name": "半导体", "plate_type": 14, "rate": 0.5},
        ]
        fetcher = self._fetcher_with_api(plates_list=rows)
        boards = fetcher.get_all_boards(board_type="concept", subtype="同花顺概念", source="zzshare")
        # Only plate_type=15 (concept) matches
        assert len(boards) == 1
        assert boards[0]["code"] == "801001"

    def test_get_all_boards_industry_via_14(self):
        rows = [
            {"plate_code": "881121", "plate_name": "半导体", "plate_type": 14, "rate": 0.5},
        ]
        fetcher = self._fetcher_with_api(plates_list=rows)
        boards = fetcher.get_all_boards(board_type="industry", subtype="同花顺行业", source="zzshare")
        assert len(boards) == 1
        assert boards[0]["type"] == "industry"

    def test_get_all_boards_special_via_17(self):
        rows = [
            {"plate_code": "881999", "plate_name": "题材", "plate_type": 17, "rate": 2.0},
        ]
        fetcher = self._fetcher_with_api(plates_list=rows)
        boards = fetcher.get_all_boards(board_type="special", subtype="同花顺题材", source="zzshare")
        assert len(boards) == 1
        assert boards[0]["type"] == "special"

    def test_get_all_boards_no_subtype_returns_all_matching_type(self):
        rows = [
            {"plate_code": "801001", "plate_name": "芯片", "plate_type": 15, "rate": 1.5},
            {"plate_code": "801002", "plate_name": "通信", "plate_type": 15, "rate": 0.8},
            {"plate_code": "881121", "plate_name": "半导体", "plate_type": 14, "rate": 0.5},
        ]
        fetcher = self._fetcher_with_api(plates_list=rows)
        boards = fetcher.get_all_boards(board_type="concept", subtype=None, source="zzshare")
        # Only concept (plate_type=15) match
        assert len(boards) == 2

    def test_get_board_stocks_adds_exchange_suffix(self):
        rows = [
            {"stock_code": "600519", "stock_name": "贵州茅台", "exchange": "sh"},
            {"stock_code": "000001", "stock_name": "平安银行", "exchange": "sz"},
        ]
        fetcher = self._fetcher_with_api(plates_stocks=rows)
        stocks = fetcher.get_board_stocks("801001", source="zzshare")
        assert stocks[0]["stock_code"] == "600519.SH"
        assert stocks[1]["stock_code"] == "000001.SZ"
        assert stocks[0]["stock_name"] == "贵州茅台"

    def test_get_stock_boards_returns_none(self):
        """SDK has no stock->boards reverse lookup; return None (route 404)."""
        fetcher = ZzshareFetcher()
        assert fetcher.get_stock_boards("600519", source="zzshare") is None

    def test_get_board_history_raises_not_implemented(self):
        fetcher = ZzshareFetcher()
        with pytest.raises(NotImplementedError, match="ZzshareFetcher does not provide"):
            fetcher.get_board_history("801001", source="zzshare", frequency="d", days=30)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_zzshare_fetcher.py::TestBoards -v`
Expected: FAIL (4 board methods not implemented yet)

- [ ] **Step 3: Implement the 4 board methods**

Open `stock_data/data_provider/fetchers/zzshare_fetcher.py` and add after `get_zt_pool`:

```python
    # Board type/subtype -> zzshare plate_type
    _PLATE_TYPE_BY_BOARD_TYPE: dict[str, int] = {
        "industry": 14,
        "concept": 15,
        "special": 17,
    }
    _BOARD_TYPE_BY_PLATE_TYPE: dict[int, tuple[str, str]] = {
        14: ("industry", "同花顺行业"),
        15: ("concept", "同花顺概念"),
        17: ("special", "同花顺题材"),
    }

    def get_all_boards(
        self,
        board_type: str,
        subtype: str | None = None,
        source: str = "zzshare",
        include_quote: bool = False,
    ) -> list[dict]:
        """Get boards of a given (type, subtype) from zzshare plates_list.

        include_quote is accepted for interface symmetry but ignored —
        plates_list does not expose realtime quote fields.
        """
        _ = source, include_quote  # accepted for Manager interface
        api = _ensure_api(self)
        if api is None:
            return []
        # Try each plate_type matching the requested board_type
        out: list[dict] = []
        target_plate_types = [
            pt for pt, (bt, st) in self._BOARD_TYPE_BY_PLATE_TYPE.items()
            if bt == board_type
        ]
        for pt in target_plate_types:
            try:
                rows = api.plates_list(plate_type=pt)
            except Exception as e:
                logger.warning(f"[ZzshareFetcher] plates_list({pt}) failed: {e}")
                continue
            if not rows:
                continue
            mapped_type, mapped_subtype = self._BOARD_TYPE_BY_PLATE_TYPE[pt]
            for row in rows:
                if not isinstance(row, dict):
                    continue
                if subtype is not None and mapped_subtype != subtype:
                    continue
                out.append({
                    "code": str(row.get("plate_code", "")),
                    "name": str(row.get("plate_name", "")),
                    "type": mapped_type,
                    "subtype": mapped_subtype,
                })
        return out

    def get_board_stocks(self, board_code: str, **kwargs) -> list[dict]:
        """Get stocks belonging to a board via plates_stocks.

        Returns [{stock_code, stock_name, exchange}] or [] on failure.
        ``**kwargs`` absorbs source/include_quote for interface symmetry.
        """
        source = kwargs.get("source", "zzshare")
        _ = source  # currently always 'zzshare' for this fetcher
        api = _ensure_api(self)
        if api is None:
            return []
        # Try each plate_type (14/15/17) until one returns data.
        # plate_type itself isn't needed downstream — we just need the rows.
        rows = None
        for pt in self._BOARD_TYPE_BY_PLATE_TYPE:
            try:
                r = api.plates_stocks(plate_type=pt, plate_code=board_code)
                if r:
                    rows = r
                    break
            except Exception:
                continue
        if not rows:
            return []
        out: list[dict] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            stock_code = str(row.get("stock_code", "")).strip()
            if not stock_code:
                continue
            out.append({
                "stock_code": _add_exchange_suffix(stock_code),
                "stock_name": str(row.get("stock_name", "")).strip(),
                "exchange": str(row.get("exchange", "")).strip().lower(),
            })
        return out

    def get_stock_boards(self, stock_code: str, **kwargs) -> list[dict] | None:
        """Reverse lookup: boards a stock belongs to.

        zzshare SDK does not provide a direct stock->boards endpoint. Return
        None so the route layer can 404 (matches EastMoney behavior).
        """
        return None

    def get_board_history(
        self, board_code: str, frequency: str = "d", days: int = 30, **kwargs
    ) -> list[dict]:
        """K-line for a board — not yet implemented for zzshare."""
        raise NotImplementedError(
            f"ZzshareFetcher does not provide board-level K-line data "
            f"(board_code={board_code!r}). v2 may use api.plate_kline()."
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_zzshare_fetcher.py::TestBoards -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
cd E:/GitRepo/stock_data
git add stock_data/data_provider/fetchers/zzshare_fetcher.py tests/test_zzshare_fetcher.py
git commit -m "feat(zzshare): add 4 board methods (get_all_boards, get_board_stocks, get_stock_boards, get_board_history)"
```

---

## Task 12: Dragon-tiger implementation + tests

**Files:**
- Modify: `stock_data/data_provider/fetchers/zzshare_fetcher.py` (add 2 methods)
- Modify: `tests/test_zzshare_fetcher.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_zzshare_fetcher.py`:

```python
# ====================================================================
# DRAGON_TIGER
# ====================================================================

class TestDragonTiger:
    def _fetcher_with_api(self, **mocks):
        fetcher = ZzshareFetcher()
        fake_api = MagicMock()
        for name, value in mocks.items():
            setattr(fake_api, name, MagicMock(return_value=value))
        fetcher._api = fake_api
        return fetcher

    def test_daily_dragon_tiger_normalizes_stock_code(self):
        rows = [
            {"stock_code": "000078", "stock_name": "海王生物",
             "concepts": "801723:中药,801369:医美",
             "amplitude": 5.2, "quote_change": 10.0, "turnover": 5e8,
             "turnover_ratio": 8.5, "capitalization": 1e9, "circ_price": 5e8,
             "buy_in": 1e8, "join_num": 5, "up_reason": "涨幅偏离值达7%",
             "t_type": 0, "d3": 12.0},
        ]
        fetcher = self._fetcher_with_api(lhb_list=rows)
        data = fetcher.get_daily_dragon_tiger("2026-05-20", None)
        assert data["date"] == "2026-05-20"
        assert data["total"] == 1
        # 000078 -> 000078.SZ (ChiNext prefix 0/3 -> SZ)
        assert data["stocks"][0]["code"] == "000078.SZ"
        assert data["stocks"][0]["name"] == "海王生物"
        assert data["stocks"][0]["net_buy"] == 1e8

    def test_daily_dragon_tiger_min_net_buy_filter(self):
        rows = [
            {"stock_code": "000078", "stock_name": "A", "buy_in": 5e7},
            {"stock_code": "600519", "stock_name": "B", "buy_in": 2e8},
        ]
        fetcher = self._fetcher_with_api(lhb_list=rows)
        data = fetcher.get_daily_dragon_tiger("2026-05-20", 1e8)
        # Only stock with buy_in >= 1e8 (200M) survives; 600519 starts with 6 -> .SH
        assert data["total"] == 1
        assert data["stocks"][0]["code"] == "600519.SH"

    def test_daily_dragon_tiger_empty_returns_zeros(self):
        fetcher = self._fetcher_with_api(lhb_list=[])
        data = fetcher.get_daily_dragon_tiger("2026-05-20", None)
        assert data["date"] == "2026-05-20"
        assert data["total"] == 0
        assert data["stocks"] == []

    def test_dragon_tiger_uses_detail(self):
        detail = [
            {"trader_name": "东方证券绍兴解放南路营业部", "buy": 1e8, "sell": 5e7, "net": 5e7},
            {"trader_name": "华泰证券深圳益田路荣超商务中心", "buy": 5e7, "sell": 3e7, "net": 2e7},
        ]
        fetcher = self._fetcher_with_api(lhb_detail=detail)
        data = fetcher.get_dragon_tiger("000078", "2026-05-20", 30)
        assert "seats" in data
        # 2 buy seats and 2 sell seats
        assert len(data["seats"]["buy"]) == 2
        assert len(data["seats"]["sell"]) == 2
        assert data["seats"]["buy"][0]["name"] == "东方证券绍兴解放南路营业部"

    def test_dragon_tiger_falls_back_to_stock_history(self):
        """When lhb_detail returns empty, try lhb_stock_history."""
        from stock_data.data_provider.base import DataFetchError
        fetcher = self._fetcher_with_api(
            lhb_detail=[],  # empty
            lhb_stock_history=[
                {"trade_date": "2026-05-15", "buy_in": 5e7, "reason": "涨幅偏离"}
            ],
        )
        data = fetcher.get_dragon_tiger("000078", "2026-05-20", 30)
        # records should have at least 1 entry from history
        assert len(data["records"]) >= 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_zzshare_fetcher.py::TestDragonTiger -v`
Expected: FAIL

- [ ] **Step 3: Implement get_daily_dragon_tiger and get_dragon_tiger**

Open `stock_data/data_provider/fetchers/zzshare_fetcher.py` and add:

```python
    def get_daily_dragon_tiger(
        self, trade_date: str = "", min_net_buy: float | None = None
    ) -> dict:
        """全市场龙虎榜 via zzshare lhb_list.

        Returns ``{date, total, stocks[]}`` matching the manager's
        contract. ``min_net_buy`` filters rows whose buy_in < threshold.
        """
        from .zhitu_fetcher import _split_concepts  # reuse helper if needed
        _ = _split_concepts
        api = _ensure_api(self)
        if api is None:
            raise DataFetchError("ZzshareFetcher DataApi SDK 不可用")
        date_str = _to_yyyymmdd(trade_date) if trade_date else _to_yyyymmdd(
            __import__("datetime").date.today().strftime("%Y-%m-%d")
        )
        try:
            rows = api.lhb_list(date1=date_str)
        except Exception as e:
            logger.warning(f"[ZzshareFetcher] lhb_list({date_str}) failed: {e}")
            raise DataFetchError(f"lhb_list failed: {e}") from e
        out_stocks: list[dict] = []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            buy_in = safe_float(row.get("buy_in")) or 0.0
            if min_net_buy is not None and buy_in < min_net_buy:
                continue
            stock_code = str(row.get("stock_code", "")).strip()
            out_stocks.append({
                "code": _add_exchange_suffix(stock_code) if stock_code else "",
                "name": str(row.get("stock_name", "")),
                "net_buy": buy_in,
                "amplitude": safe_float(row.get("amplitude")),
                "change_pct": safe_float(row.get("quote_change")),
                "turnover": safe_float(row.get("turnover")),
                "turnover_rate": safe_float(row.get("turnover_ratio")),
                "join_num": safe_int(row.get("join_num")),
                "reason": str(row.get("up_reason", "")),
                "t_type": safe_int(row.get("t_type")),
                "d3": safe_float(row.get("d3")),
            })
        return {
            "date": _from_yyyymmdd(date_str),
            "total": len(out_stocks),
            "stocks": out_stocks,
        }

    def get_dragon_tiger(
        self, code: str, trade_date: str = "", look_back: int = 30
    ) -> dict:
        """个股龙虎榜 via zzshare lhb_detail, fallback lhb_stock_history.

        Returns ``{records[], seats{buy, sell}, institution}`` matching
        the manager's per-stock contract.
        """
        api = _ensure_api(self)
        if api is None:
            raise DataFetchError("ZzshareFetcher DataApi SDK 不可用")
        bare_code = normalize_stock_code(code)
        date_str = _to_yyyymmdd(trade_date) if trade_date else ""
        records: list[dict] = []
        seats: dict[str, list] = {"buy": [], "sell": []}
        # 1) Try detail (per-day seats)
        try:
            detail = api.lhb_detail(date1=date_str, stock_code=bare_code) if date_str else None
        except Exception as e:
            logger.warning(f"[ZzshareFetcher] lhb_detail failed: {e}")
            detail = None
        if detail and isinstance(detail, list):
            for row in detail:
                if not isinstance(row, dict):
                    continue
                trader = str(row.get("trader_name", ""))
                buy_amt = safe_float(row.get("buy")) or 0.0
                sell_amt = safe_float(row.get("sell")) or 0.0
                net = safe_float(row.get("net")) or (buy_amt - sell_amt)
                if buy_amt > 0:
                    seats["buy"].append({"name": trader, "amount": buy_amt})
                if sell_amt > 0:
                    seats["sell"].append({"name": trader, "amount": sell_amt})
        # 2) If detail empty, fall back to stock history
        if not seats["buy"] and not seats["sell"]:
            try:
                history = api.lhb_stock_history(stock_code=bare_code)
            except Exception as e:
                logger.warning(f"[ZzshareFetcher] lhb_stock_history failed: {e}")
                history = None
            if history and isinstance(history, list):
                for row in history:
                    if not isinstance(row, dict):
                        continue
                    records.append({
                        "date": str(row.get("trade_date", "")),
                        "net_buy": safe_float(row.get("buy_in")),
                        "reason": str(row.get("reason", "")),
                    })
        return {
            "records": records,
            "seats": seats,
            "institution": {},
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_zzshare_fetcher.py::TestDragonTiger -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
cd E:/GitRepo/stock_data
git add stock_data/data_provider/fetchers/zzshare_fetcher.py tests/test_zzshare_fetcher.py
git commit -m "feat(zzshare): add get_dragon_tiger + get_daily_dragon_tiger (DRAGON_TIGER)"
```

---

## Task 13: Hot topics implementation + tests

**Files:**
- Modify: `stock_data/data_provider/fetchers/zzshare_fetcher.py` (add `get_hot_topics`)
- Modify: `tests/test_zzshare_fetcher.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_zzshare_fetcher.py`:

```python
# ====================================================================
# HOT_TOPICS
# ====================================================================

class TestHotTopics:
    def _fetcher_with_api(self, fake_top):
        fetcher = ZzshareFetcher()
        fake_api = MagicMock()
        fake_api.ths_hot_top = MagicMock(return_value=fake_top)
        fetcher._api = fake_api
        return fetcher

    def test_hot_topics_normalizes_symbol_code(self):
        rows = [
            {"rank": 1, "rank_diff": 1, "symbol_code": "002342", "symbol_name": "巨力索具",
             "last_price": 5.5, "last_pct": 10.0, "circulation_value": 50.0,
             "collect_date": "2026-05-20", "update_time": "2026-05-20 15:00:00", "id": 1},
            {"rank": 2, "rank_diff": -2, "symbol_code": "600519", "symbol_name": "贵州茅台",
             "last_price": 1720.0, "last_pct": 1.18, "circulation_value": 21600.0,
             "collect_date": "2026-05-20", "update_time": "2026-05-20 15:00:00", "id": 2},
        ]
        fetcher = self._fetcher_with_api(rows)
        topics = fetcher.get_hot_topics("2026-05-20")
        assert len(topics) == 2
        # 002342 -> 002342.SZ
        assert topics[0]["code"] == "002342.SZ"
        assert topics[0]["name"] == "巨力索具"
        assert topics[0]["change_pct"] == 10.0
        assert topics[0]["rank"] == 1
        # 600519 -> 600519.SH
        assert topics[1]["code"] == "600519.SH"

    def test_hot_topics_empty_returns_empty_list(self):
        fetcher = self._fetcher_with_api([])
        assert fetcher.get_hot_topics("2026-05-20") == []

    def test_hot_topics_uses_today_when_date_empty(self):
        fetcher = self._fetcher_with_api([])
        fetcher.get_hot_topics("")  # empty -> today
        call = fetcher._api.ths_hot_top.call_args
        # date1 should be today's YYYYMMDD
        from datetime import date
        expected = date.today().strftime("%Y%m%d")
        assert call.kwargs.get("date1") == expected

    def test_hot_topics_default_top_n(self):
        fetcher = self._fetcher_with_api([])
        fetcher.get_hot_topics("2026-05-20")
        call = fetcher._api.ths_hot_top.call_args
        assert call.kwargs.get("top_n") == 100
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_zzshare_fetcher.py::TestHotTopics -v`
Expected: FAIL

- [ ] **Step 3: Implement get_hot_topics**

Open `stock_data/data_provider/fetchers/zzshare_fetcher.py` and add:

```python
    def get_hot_topics(self, date_str: str = "") -> list[dict]:
        """同花顺热度 TopN via zzshare ths_hot_top.

        Returns list of normalized {code, name, change_pct, rank, ...} dicts.
        date_str empty -> today.
        """
        from datetime import date as _date

        api = _ensure_api(self)
        if api is None:
            return []
        d = _to_yyyymmdd(date_str) if date_str else _date.today().strftime("%Y%m%d")
        try:
            rows = api.ths_hot_top(date1=d, top_n=100)
        except Exception as e:
            logger.warning(f"[ZzshareFetcher] ths_hot_top({d}) failed: {e}")
            return []
        out: list[dict] = []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            symbol = str(row.get("symbol_code", "")).strip()
            out.append({
                "code": _add_exchange_suffix(symbol) if symbol else "",
                "name": str(row.get("symbol_name", "")),
                "rank": safe_int(row.get("rank")),
                "rank_diff": safe_int(row.get("rank_diff")),
                "change_pct": safe_float(row.get("last_pct")),
                "price": safe_float(row.get("last_price")),
                "circ_mv": safe_float(row.get("circulation_value")),
                "date": str(row.get("collect_date", "")),
            })
        return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_zzshare_fetcher.py::TestHotTopics -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
cd E:/GitRepo/stock_data
git add stock_data/data_provider/fetchers/zzshare_fetcher.py tests/test_zzshare_fetcher.py
git commit -m "feat(zzshare): add get_hot_topics (HOT_TOPICS) with ths_hot_top + symbol_code suffix"
```

---

## Task 14: Boards source-routing in API + persistence

Wire the `zzshare` source into the boards endpoint, `_VALID_SOURCES`, and the `VALID_SUBTYPES_BY_SOURCE` table.

**Files:**
- Modify: `stock_data/api/routes/boards.py` (3 Literal + 1 if fix)
- Modify: `stock_data/data_provider/persistence/board.py` (add `"zzshare"` to dict)
- Modify: `tests/test_zzshare_fetcher.py` (append board subtype validation test)

- [ ] **Step 1: Add a subtype validation test (failing)**

Append to `tests/test_zzshare_fetcher.py`:

```python
# ====================================================================
# Boards source-routing — persistence layer integration
# ====================================================================

class TestBoardSubtypeValidation:
    """Verify VALID_SUBTYPES_BY_SOURCE has zzshare entries."""

    def test_zzshare_industry_subtype(self):
        from stock_data.data_provider.persistence.board import VALID_SUBTYPES_BY_SOURCE
        assert "zzshare" in VALID_SUBTYPES_BY_SOURCE
        assert "industry" in VALID_SUBTYPES_BY_SOURCE["zzshare"]
        assert "同花顺行业" in VALID_SUBTYPES_BY_SOURCE["zzshare"]["industry"]

    def test_zzshare_concept_subtype(self):
        from stock_data.data_provider.persistence.board import VALID_SUBTYPES_BY_SOURCE
        assert "同花顺概念" in VALID_SUBTYPES_BY_SOURCE["zzshare"]["concept"]

    def test_zzshare_special_subtype(self):
        from stock_data.data_provider.persistence.board import VALID_SUBTYPES_BY_SOURCE
        assert "同花顺题材" in VALID_SUBTYPES_BY_SOURCE["zzshare"]["special"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_zzshare_fetcher.py::TestBoardSubtypeValidation -v`
Expected: FAIL ("zzshare" not in VALID_SUBTYPES_BY_SOURCE)

- [ ] **Step 3: Update persistence/board.py**

Open `stock_data/data_provider/persistence/board.py`, find the `VALID_SUBTYPES_BY_SOURCE` dict and add the `zzshare` key (keep the existing `eastmoney` and `zhitu` entries unchanged):

```python
VALID_SUBTYPES_BY_SOURCE: dict[str, dict[str, set[str]]] = {
    "eastmoney": {
        "concept": {"concept"},
        "industry": {"industry"},
        "index": {"index"},
        "special": {"special"},
    },
    "zhitu": {
        "industry": {"申万行业", "申万二级", "证监会行业"},
        "concept": {"热门概念", "概念板块", "地域板块"},
        "index": {"分类", "指数成分", "大盘指数"},
        "special": {"风险警示", "次新股", "沪港通", "深港通"},
    },
    "zzshare": {   # NEW
        "industry": {"同花顺行业"},
        "concept": {"同花顺概念"},
        "special": {"同花顺题材"},
        # "index" — zzshare 不暴露大盘指数板块
    },
}
```

- [ ] **Step 4: Update api/routes/boards.py**

Open `stock_data/api/routes/boards.py`. Make 4 changes:

**Change 1** — expand `_VALID_SOURCES`:

```python
_VALID_SOURCES = {"eastmoney", "zhitu", "zzshare"}
```

**Change 2** — `/boards` endpoint source Literal:

```python
source: Literal["eastmoney", "zhitu", "zzshare"] = Query(...),
```

**Change 3** — `/boards/{board_code}/stocks` endpoint source Literal:

```python
source: Literal["eastmoney", "zhitu", "zzshare"] = Query(...),
```

**Change 4** — `/stocks/{code}/boards` endpoint source Literal + the 501 if:

```python
source: Literal["zhitu", "eastmoney", "zzshare"] = Query(...),
```

```python
# Replace:
if source != "zhitu":
    raise HTTPException(status_code=501, ...)
# With:
if source not in ("zhitu", "zzshare"):
    raise HTTPException(status_code=501, ...)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_zzshare_fetcher.py::TestBoardSubtypeValidation -v`
Expected: All PASS

- [ ] **Step 6: Run all existing boards tests to verify no regression**

Run: `.venv/Scripts/python.exe -m pytest tests/test_boards.py tests/test_boards_api.py tests/test_board_persistence_subtype.py -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
cd E:/GitRepo/stock_data
git add stock_data/api/routes/boards.py stock_data/data_provider/persistence/board.py tests/test_zzshare_fetcher.py
git commit -m "feat(boards): add 'zzshare' to source whitelist + subtype table"
```

---

## Task 15: Manager registration + capability test

Register `ZzshareFetcher` in `create_default_manager()` and add it to the test's `_CONCRETE_FETCHERS` set.

**Files:**
- Modify: `stock_data/data_provider/manager.py` (1 import + 1 list entry)
- Modify: `tests/test_capability_method_map.py` (1 list entry)

- [ ] **Step 1: Run the failing capability test first**

Run: `.venv/Scripts/python.exe -m pytest tests/test_capability_method_map.py -v`
Expected: PASS (test still works because ZzshareFetcher hasn't been added to `_CONCRETE_FETCHERS` yet — but we want it to also exercise ZzshareFetcher's methods)

- [ ] **Step 2: Update test_capability_method_map.py**

Open `tests/test_capability_method_map.py`. Find the `_CONCRETE_FETCHERS` tuple and add `ZzshareFetcher`:

```python
from stock_data.data_provider import (
    AkshareFetcher,
    BaostockFetcher,
    CninfoFetcher,
    EastMoneyFetcher,
    TencentFetcher,
    ThsFetcher,
    TushareFetcher,
    YfinanceFetcher,
    ZhituFetcher,
    ZzshareFetcher,   # NEW
)
from stock_data.data_provider.fetchers.myquant_fetcher import MyquantFetcher


_CONCRETE_FETCHERS = (
    AkshareFetcher,
    BaostockFetcher,
    CninfoFetcher,
    EastMoneyFetcher,
    MyquantFetcher,
    TencentFetcher,
    ThsFetcher,
    TushareFetcher,
    YfinanceFetcher,
    ZhituFetcher,
    ZzshareFetcher,   # NEW
)
```

- [ ] **Step 3: Update manager.py**

Open `stock_data/data_provider/manager.py`. Find the import block and the `fetcher_classes` list:

```python
    # Lazy imports to avoid circular dependencies at module level
    from .fetchers.akshare import AkshareFetcher
    from .fetchers.baidu_fetcher import BaiduFetcher
    from .fetchers.baostock_fetcher import BaostockFetcher
    from .fetchers.cninfo_fetcher import CninfoFetcher
    from .fetchers.eastmoney_fetcher import EastMoneyFetcher
    from .fetchers.myquant_fetcher import MyquantFetcher
    from .fetchers.tencent_fetcher import TencentFetcher
    from .fetchers.ths_fetcher import ThsFetcher
    from .fetchers.tushare_fetcher import TushareFetcher
    from .fetchers.yfinance_fetcher import YfinanceFetcher
    from .fetchers.zhitu_fetcher import ZhituFetcher
    from .fetchers.zzshare_fetcher import ZzshareFetcher   # NEW

    manager = DataFetcherManager()
    fetcher_classes = [
        TushareFetcher,
        BaostockFetcher,
        MyquantFetcher,
        AkshareFetcher,
        YfinanceFetcher,
        ZhituFetcher,
        ZzshareFetcher,   # NEW (P5; placed after Zhitu for human-readable order)
        TencentFetcher,
        EastMoneyFetcher,
        BaiduFetcher,
        ThsFetcher,
        CninfoFetcher,
    ]
```

- [ ] **Step 4: Run all related tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_capability_method_map.py tests/test_zzshare_fetcher.py -v`
Expected: All PASS

- [ ] **Step 5: Run the full suite to verify no regression**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: All PASS (existing tests + new tests)

- [ ] **Step 6: Commit**

```bash
cd E:/GitRepo/stock_data
git add stock_data/data_provider/manager.py tests/test_capability_method_map.py
git commit -m "feat(manager): register ZzshareFetcher (P5) in create_default_manager + capability test"
```

---

## Task 16: pyproject.toml + manual smoke test

Add optional `zzshare` extra dependency (best-effort) and run end-to-end smoke test.

**Files:**
- Modify: `pyproject.toml` (1 optional dep block)

- [ ] **Step 1: Update pyproject.toml**

Open `pyproject.toml`. Find the `[project.optional-dependencies]` section and add the `zzshare` extra:

```toml
[project.optional-dependencies]
# ... existing extras ...
zzshare = ["DataApi>=0.1.0"]   # Verify availability: pip index versions DataApi
```

(If `DataApi` is not on PyPI, this can be omitted or replaced with `zzshare = ["zzshare-mcp"]`. The fetcher's `is_available()` uses `importlib.util.find_spec` and gracefully reports "unavailable" if the package isn't installed.)

- [ ] **Step 2: Run the linter**

Run: `ruff check stock_data/data_provider/fetchers/zzshare_fetcher.py tests/test_zzshare_fetcher.py`
Expected: 0 errors (fix any style warnings)

Run: `ruff format stock_data/data_provider/fetchers/zzshare_fetcher.py tests/test_zzshare_fetcher.py`

- [ ] **Step 3: Run the full test suite one more time**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: All PASS

- [ ] **Step 4: Manual smoke test (skip if SDK not installed)**

If the DataApi SDK is installed (or `pip install DataApi` is run):

```bash
# Start the server
.venv/Scripts/python.exe -m stock_data.server &

# Verify manifest includes zzshare
curl -s http://localhost:8888/api/v1/control/api-manifest | python -c "
import json, sys
manifest = json.load(sys.stdin)
zzshare_endpoints = []
for section in manifest.get('sections', []):
    for ep in section.get('endpoints', []):
        for f in ep.get('fetchers', []):
            if f.get('name') == 'ZzshareFetcher':
                zzshare_endpoints.append(ep['path'])
print('ZzshareFetcher endpoints:', zzshare_endpoints)
"
# Expected: list of paths including /stocks/{code}/history, /stocks/{code}/quote,
# /boards, /boards/{code}/stocks, /stocks/{code}/dragon-tiger, /hot-topics, etc.
```

If the SDK is NOT installed, this step is a no-op — `is_available()` returns False and zzshare doesn't appear in the manifest. That's expected behavior.

- [ ] **Step 5: Commit pyproject change**

```bash
cd E:/GitRepo/stock_data
git add pyproject.toml
git commit -m "chore(pyproject): add optional 'zzshare' extra dependency"
```

---

## Done Checklist

- [ ] All 30+ tests in `tests/test_zzshare_fetcher.py` pass
- [ ] `tests/test_capability_method_map.py` passes with `ZzshareFetcher` included
- [ ] `tests/test_boards.py` + `tests/test_boards_api.py` + `tests/test_board_persistence_subtype.py` pass (no regression)
- [ ] Full test suite passes
- [ ] `ruff check` + `ruff format` clean
- [ ] All commits pushed to feature branch (suggested: `feat/zzshare-fetcher`)

**Rollback**: To roll back, delete `zzshare_fetcher.py` + `test_zzshare_fetcher.py`, revert the 4 modified files (boards.py / persistence/board.py / manager.py / test_capability_method_map.py / pyproject.toml) via `git revert` of the relevant commits. The boards endpoint will refuse `?source=zzshare` with 400 (since it's not in `_VALID_SOURCES` again) — no dangling references.

---

## Task 17: Update CLAUDE.md

The spec §11 calls for CLAUDE.md documentation updates. **Three** tables need updates (per `grep -n "^|" stock_data/CLAUDE.md`):

- Line 211-223: Fetcher capability declarations table
- Line 231-237: Provider Frequency Support table
- Line 253+: Capability-Based Routing table

**Files:**
- Modify: `stock_data/CLAUDE.md` (3 tables)

- [ ] **Step 1: Add ZzshareFetcher row in the capability declarations table**

Open `stock_data/CLAUDE.md`. Find the table at line 211 with the header `| Fetcher | Priority | Markets | Capabilities (in addition to defaults) | Auth |`. Add a `ZzshareFetcher` row between `ZhituFetcher` and `TencentFetcher` (priority order):

```markdown
| `ZzshareFetcher` | 5 | csi | `HISTORICAL_DWM`, `HISTORICAL_MIN`, `REALTIME_QUOTE`, `STOCK_LIST`, `TRADE_CALENDAR`, `STOCK_BOARD`, `STOCK_ZT_POOL`, `DRAGON_TIGER`, `HOT_TOPICS`, `STOCK_INFO` | `ZZSHARE_TOKEN` (optional) |
```

- [ ] **Step 2: Add ZzshareFetcher row in the Provider Frequency Support table**

Find the table at line 231 with header `| Provider | d | w | m | 5m | 15m | 30m | 60m |`. Add a row for ZzshareFetcher (zzshare supports d and 5/15/30/60m via stk_mins; w/m not supported — see Task 1's `_fetch_raw_data` raising for them):

```markdown
| ZzshareFetcher | ✅ | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ |
```

- [ ] **Step 3: Add `(ZzshareFetcher P5)` annotations in the Capability-Based Routing table**

Find the table at line 253 with header `| API Method | Capability Used |`. For each of the 10 capabilities ZzshareFetcher supports, add the annotation to the `Capability Used` column. Specifically, update these rows:

| Row | New value |
|---|---|
| `get_kline_data` (d/w/m, stocks) | `HISTORICAL_DWM` → `HISTORICAL_DWM` |
| `get_kline_data` (5/15/30/60, stocks) | `HISTORICAL_MIN` → `HISTORICAL_MIN` |
| `get_realtime_quote` | `REALTIME_QUOTE` → `REALTIME_QUOTE` |
| `get_all_stocks` | `STOCK_LIST` → `STOCK_LIST` |
| `get_trade_calendar` | `TRADE_CALENDAR` → `TRADE_CALENDAR` |
| `get_zt_pool` | `STOCK_ZT_POOL` → `STOCK_ZT_POOL` |
| `get_dragon_tiger` | `DRAGON_TIGER` → `DRAGON_TIGER` |
| `get_hot_topics` | `HOT_TOPICS` → `HOT_TOPICS` |
| `get_stock_info` | `STOCK_INFO` → `STOCK_INFO` |
| (board methods use STOCK_BOARD) | already covered |

For the **first occurrence** of each capability in the routing column, append ` (ZzshareFetcher P5)` if no other fetcher already lists it. For capabilities already covered by other fetchers (most are), just append the annotation. Example for `get_realtime_quote`:

```markdown
| `get_realtime_quote` | `REALTIME_QUOTE` (ZzshareFetcher P5) |
```

- [ ] **Step 4: Update the "11 upstream" / "11 fetchers" count if present**

Search for any count mention:

Run: `grep -n "11" stock_data/CLAUDE.md | head`

If you find a line like "Integrates 11 upstream stock data APIs" or "11 fetchers", bump to 12. If not, skip this step.

- [ ] **Step 5: Verify the markdown still renders**

Run: `git diff stock_data/CLAUDE.md`
Expected: 2-4 small additions in the right tables, no broken syntax (no orphan pipes, no empty cells).

- [ ] **Step 6: Commit**

```bash
cd E:/GitRepo/stock_data
git add stock_data/CLAUDE.md
git commit -m "docs(CLAUDE): document ZzshareFetcher (P5, 10 capabilities, optional token)"
```


