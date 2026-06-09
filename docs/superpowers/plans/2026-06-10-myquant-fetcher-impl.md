# MyquantFetcher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a new `MyquantFetcher` backup fetcher to the stock_data server that covers 7 server-exposed capabilities via myquant's free SDK (`gm` 3.0.184), with priority 1 (right after Tushare).

**Architecture:** New `MyquantFetcher(BaseFetcher)` module + 2 new `code_converter` functions + 1 new `RealtimeSource` enum value. Token read from `MYQUANT_TOKEN` env var. Frequencies: `d`/`5`/`15`/`30`/`60m` only (`w`/`m`/`1m` raise `DataFetchError` for transparent downgrade).

**Tech Stack:** Python 3.10+, pandas 2.x, gm 3.0.184 SDK, pytest, ruff.

**Reference spec:** `docs/superpowers/specs/2026-06-09-myquant-fetcher-design.md` (commit `a4efa6e`).

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `stock_data/data_provider/core/types.py` | Modify | Add `RealtimeSource.MYQUANT = "myquant"` |
| `stock_data/data_provider/utils/code_converter.py` | Modify | Add `to_myquant_format()` / `to_myquant_index_format()` |
| `stock_data/data_provider/fetchers/myquant_fetcher.py` | Create | Main fetcher class with 7 capabilities |
| `stock_data/data_provider/manager.py` | Modify | Register `MyquantFetcher` in `create_default_manager()` |
| `.env.example` | Modify | Add `MYQUANT_TOKEN=` block + `MYQUANT_PRIORITY` |
| `pyproject.toml` | Modify | Add `gm>=3.0.148,<4` to `dependencies` |
| `tests/test_fetcher_structure.py` | Modify | Add `TestMyquantFetcher` class (14 tests) |
| `CLAUDE.md` | Modify | Update fetcher priority table + capability table |

---

## Task 1: Add `RealtimeSource.MYQUANT` enum

**Files:**
- Modify: `stock_data/data_provider/core/types.py:42-51` (the `RealtimeSource` enum)

- [ ] **Step 1: Add enum value**

Open `stock_data/data_provider/core/types.py`, find the `RealtimeSource` enum:

```python
class RealtimeSource(Enum):
    """Data source identifiers for realtime quotes."""

    TUSHARE = "tushare"
    AKSHARE = "akshare"
    YFINANCE = "yfinance"
    STOOQ = "stooq"
    ZHITU = "zhitu"
    TENCENT = "tencent"
    FALLBACK = "fallback"
```

Add `MYQUANT = "myquant"` between `TENCENT` and `FALLBACK` (alphabetical-ish order, after token-required providers):

```python
class RealtimeSource(Enum):
    """Data source identifiers for realtime quotes."""

    TUSHARE = "tushare"
    AKSHARE = "akshare"
    YFINANCE = "yfinance"
    STOOQ = "stooq"
    ZHITU = "zhitu"
    TENCENT = "tencent"
    MYQUANT = "myquant"
    FALLBACK = "fallback"
```

- [ ] **Step 2: Verify import works**

Run: `cd E:/GitRepo/stock_data && .venv/Scripts/python.exe -c "from stock_data.data_provider.core.types import RealtimeSource; print(RealtimeSource.MYQUANT.value)"`
Expected: `myquant`

- [ ] **Step 3: Commit**

```bash
git add stock_data/data_provider/core/types.py
git commit -m "feat(types): add RealtimeSource.MYQUANT enum value"
```

---

## Task 2: Add `to_myquant_format()` and `to_myquant_index_format()` code converters

**Files:**
- Modify: `stock_data/data_provider/utils/code_converter.py` (append at end)
- Test: `tests/test_code_converter.py` (append at end)

- [ ] **Step 1: Write failing tests**

Open `tests/test_code_converter.py` and append:

```python
# ====================================================================
# Myquant
# ====================================================================

class TestToMyquantFormat:
    def test_shanghai_stock(self):
        from stock_data.data_provider.utils.code_converter import to_myquant_format
        assert to_myquant_format("600519") == "SHSE.600519"

    def test_shenzhen_stock(self):
        from stock_data.data_provider.utils.code_converter import to_myquant_format
        assert to_myquant_format("000001") == "SZSE.000001"

    def test_beijing_stock(self):
        from stock_data.data_provider.utils.code_converter import to_myquant_format
        # Beijing exchange codes (8xxxxx) route to SZSE prefix per myquant docs
        assert to_myquant_format("832000") == "SZSE.832000"

    def test_hk_raises(self):
        from stock_data.data_provider.utils.code_converter import to_myquant_format
        with pytest.raises(ValueError, match="does not support"):
            to_myquant_format("HK00700")

    def test_us_raises(self):
        from stock_data.data_provider.utils.code_converter import to_myquant_format
        with pytest.raises(ValueError, match="does not support"):
            to_myquant_format("AAPL")

    def test_index_raises(self):
        """Index code should raise to force caller to use to_myquant_index_format."""
        from stock_data.data_provider.utils.code_converter import to_myquant_format
        with pytest.raises(ValueError, match="to_myquant_index_format"):
            to_myquant_format("000300")

    def test_chinext(self):
        from stock_data.data_provider.utils.code_converter import to_myquant_format
        assert to_myquant_format("300750") == "SZSE.300750"

    def test_star_market(self):
        from stock_data.data_provider.utils.code_converter import to_myquant_format
        assert to_myquant_format("688981") == "SHSE.688981"


class TestToMyquantIndexFormat:
    def test_csi_shanghai(self):
        from stock_data.data_provider.utils.code_converter import to_myquant_index_format
        assert to_myquant_index_format("000300") == "SHSE.000300"

    def test_csi_shenzhen(self):
        from stock_data.data_provider.utils.code_converter import to_myquant_index_format
        assert to_myquant_index_format("399006") == "SZSE.399006"

    def test_non_csi_raises(self):
        from stock_data.data_provider.utils.code_converter import to_myquant_index_format
        with pytest.raises(ValueError, match="non-CSI"):
            to_myquant_index_format("HSI")

    def test_non_index_raises(self):
        from stock_data.data_provider.utils.code_converter import to_myquant_index_format
        with pytest.raises(ValueError, match="Not an index"):
            to_myquant_index_format("600519")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd E:/GitRepo/stock_data && .venv/Scripts/python.exe -m pytest tests/test_code_converter.py::TestToMyquantFormat tests/test_code_converter.py::TestToMyquantIndexFormat -v`
Expected: All `ImportError` (functions don't exist yet)

- [ ] **Step 3: Implement the two functions**

Open `stock_data/data_provider/utils/code_converter.py`. The file already imports `is_hk_market, is_index_code, normalize_stock_code` at the top. Append at the end:

```python
# ---------------------------------------------------------------------------
# Myquant
# ---------------------------------------------------------------------------

def to_myquant_format(code: str) -> str:
    """Convert to myquant ``SHSE/SZSE.{code}`` format (A-share only).

    600519 → ``SHSE.600519``  (Shanghai: 5/6/7/9 prefix)
    000001 → ``SZSE.000001``  (Shenzhen/Beijing: 0/1/2/3/4/8 prefix)
    HK / US / Index → 抛 ``ValueError``

    Indices must use :func:`to_myquant_index_format` instead.
    """
    code = normalize_stock_code(code)

    if is_index_code(code):
        raise ValueError(f"Use to_myquant_index_format for index {code}")

    if is_hk_market(code):
        raise ValueError(f"Myquant does not support HK market {code}")
    if code.isalpha() and len(code) <= 5:
        raise ValueError(f"Myquant does not support US market {code}")

    if code.startswith(("5", "6", "7", "9")):
        return f"SHSE.{code}"
    # Default Shenzhen prefix covers 0/1/2/3/4 (SZ main + ChiNext) and 8 (BJ)
    if code.startswith(("0", "1", "2", "3", "4", "8")):
        return f"SZSE.{code}"
    raise ValueError(f"Cannot map code {code} to myquant format")


def to_myquant_index_format(code: str) -> str:
    """Convert CSI index to myquant format.

    000300 → ``SHSE.000300``  (沪深 300, 中证 500, etc.)
    399006 → ``SZSE.399006``  (创业板指, 深证 100, etc.)
    非 CSI 指数 / 非指数代码 → 抛 ``ValueError``
    """
    code = normalize_stock_code(code)

    if not is_index_code(code):
        raise ValueError(f"Not an index code: {code}")

    from ..fetchers.index_symbols import get_index_type

    if get_index_type(code) != "csi":
        raise ValueError(f"Myquant does not support non-CSI index {code}")

    # Shanghai indices: 0xxxxx (000300, 000905, 000016, ...)
    if code.startswith("0"):
        return f"SHSE.{code}"
    # Shenzhen indices: 3xxxxx (399006, 399001, 399905, ...)
    if code.startswith("3"):
        return f"SZSE.{code}"
    raise ValueError(f"Cannot map index {code} to myquant format")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd E:/GitRepo/stock_data && .venv/Scripts/python.exe -m pytest tests/test_code_converter.py::TestToMyquantFormat tests/test_code_converter.py::TestToMyquantIndexFormat -v`
Expected: All 13 tests pass.

- [ ] **Step 5: Commit**

```bash
git add stock_data/data_provider/utils/code_converter.py tests/test_code_converter.py
git commit -m "feat(code-converter): add myquant symbol converters"
```

---

## Task 3: Create `MyquantFetcher` skeleton with metadata + `is_available`

**Files:**
- Create: `stock_data/data_provider/fetchers/myquant_fetcher.py`
- Test: `tests/test_fetcher_structure.py` (add `TestMyquantFetcher` class)

- [ ] **Step 1: Write failing tests for metadata + `is_available`**

Open `tests/test_fetcher_structure.py` and append at the end:

```python
# ====================================================================
# MyquantFetcher
# ====================================================================

class TestMyquantFetcher:
    @pytest.fixture
    def fetcher(self, monkeypatch):
        """Build a fetcher with token pre-set."""
        monkeypatch.setenv("MYQUANT_TOKEN", "test-token")
        from stock_data.data_provider.fetchers.myquant_fetcher import MyquantFetcher
        return MyquantFetcher()

    @pytest.fixture
    def fetcher_no_token(self, monkeypatch):
        """Build a fetcher without a token."""
        monkeypatch.delenv("MYQUANT_TOKEN", raising=False)
        from stock_data.data_provider.fetchers.myquant_fetcher import MyquantFetcher
        return MyquantFetcher()

    def test_name_and_priority(self, fetcher):
        assert fetcher.name == "MyquantFetcher"
        assert fetcher.priority == 1

    def test_supported_markets(self, fetcher):
        assert fetcher.supported_markets == {"csi"}

    def test_capabilities(self, fetcher):
        caps = [
            DataCapability.HISTORICAL_DWM, DataCapability.HISTORICAL_MIN,
            DataCapability.REALTIME_QUOTE, DataCapability.STOCK_LIST,
            DataCapability.TRADE_CALENDAR, DataCapability.INDEX_HISTORICAL,
            DataCapability.INDEX_INTRADAY,
        ]
        for c in caps:
            assert c in fetcher.supported_data_types, f"missing {c}"

    def test_is_available_with_token(self, fetcher):
        assert fetcher.is_available() is True

    def test_is_available_without_token(self, fetcher_no_token):
        assert fetcher_no_token.is_available() is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd E:/GitRepo/stock_data && .venv/Scripts/python.exe -m pytest tests/test_fetcher_structure.py::TestMyquantFetcher -v`
Expected: `ImportError: cannot import name 'MyquantFetcher'`

- [ ] **Step 3: Implement the fetcher skeleton**

Create `stock_data/data_provider/fetchers/myquant_fetcher.py`:

```python
"""
Myquant (掘金量化) fetcher for A-share stock data (Priority 1).

API: ``gm`` SDK (https://www.myquant.cn/) — free public version (体验版/专业版/机构版)
covers history / current_price / get_symbols / get_trading_dates_by_year / stk_get_*.

Token configured via MYQUANT_TOKEN environment variable.
Lazy ``gm.api.set_token`` on first data call.

This fetcher is a *backup* — placed right after Tushare, before Baostock on
the failover list (tie-broken by registration order in create_default_manager).
"""

import logging
import os
from datetime import datetime

import pandas as pd

from ..base import BaseFetcher, DataCapability, DataFetchError, normalize_stock_code
from ..core.types import RealtimeSource, UnifiedRealtimeQuote, safe_float
from ..utils.code_converter import to_myquant_format, to_myquant_index_format

logger = logging.getLogger(__name__)

# myquant adjust constants (see gm.api)
ADJUST_NONE = 0   # 不复权
ADJUST_PREV = 1   # 前复权
ADJUST_POST = 2   # 后复权

# Frequency mapping: server "d/5/15/30/60" → myquant "1d/300s/900s/1800s/3600s"
_FREQ_MAP: dict[str, str] = {
    "d": "1d",
    "5": "300s",
    "15": "900s",
    "30": "1800s",
    "60": "3600s",
}

# Index intraday mapping (same minute periods)
_INDEX_FREQ_MAP: dict[str, str] = {
    "5": "300s",
    "15": "900s",
    "30": "1800s",
    "60": "3600s",
}


class MyquantFetcher(BaseFetcher):
    """Myquant (掘金量化) SDK fetcher for A-share data."""

    name = "MyquantFetcher"
    priority = int(os.getenv("MYQUANT_PRIORITY", "1"))
    supported_markets: set[str] = {"csi"}
    supported_data_types = (
        DataCapability.HISTORICAL_DWM
        | DataCapability.HISTORICAL_MIN
        | DataCapability.REALTIME_QUOTE
        | DataCapability.STOCK_LIST
        | DataCapability.TRADE_CALENDAR
        | DataCapability.INDEX_HISTORICAL
        | DataCapability.INDEX_INTRADAY
    )

    def __init__(self):
        self._token = os.getenv("MYQUANT_TOKEN", "").strip()
        self._initialized = False

    def _ensure_initialized(self) -> None:
        """Lazily import gm.api and call set_token on first use."""
        if self._initialized:
            return
        self._initialized = True
        if not self._token:
            logger.warning("[MyquantFetcher] MYQUANT_TOKEN not set")
            return
        try:
            from gm.api import set_token  # type: ignore

            set_token(self._token)
            logger.info("[MyquantFetcher] Initialized (token configured)")
        except Exception as e:
            logger.warning(f"[MyquantFetcher] Failed to set token: {e}")

    def is_available(self) -> bool:
        """True iff MYQUANT_TOKEN is set."""
        self._ensure_initialized()
        return bool(self._token)

    # ---- unsupported base abstract methods ----

    def _fetch_raw_data(
        self,
        stock_code: str,
        start_date: str,
        end_date: str,
        frequency: str = "d",
        adjust: str | None = None,
    ) -> pd.DataFrame:
        raise DataFetchError("MyquantFetcher routes through get_kline_data override")

    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        raise DataFetchError("MyquantFetcher routes through get_kline_data override")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd E:/GitRepo/stock_data && .venv/Scripts/python.exe -m pytest tests/test_fetcher_structure.py::TestMyquantFetcher::test_name_and_priority tests/test_fetcher_structure.py::TestMyquantFetcher::test_supported_markets tests/test_fetcher_structure.py::TestMyquantFetcher::test_capabilities tests/test_fetcher_structure.py::TestMyquantFetcher::test_is_available_with_token tests/test_fetcher_structure.py::TestMyquantFetcher::test_is_available_without_token -v`
Expected: All 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add stock_data/data_provider/fetchers/myquant_fetcher.py tests/test_fetcher_structure.py
git commit -m "feat(myquant-fetcher): skeleton with metadata + token init"
```

---

## Task 4: Add `_map_adjust`, `_convert_code`, and frequency checks

**Files:**
- Modify: `stock_data/data_provider/fetchers/myquant_fetcher.py`
- Modify: `tests/test_fetcher_structure.py` (append more tests)

- [ ] **Step 1: Write failing tests**

Append to `TestMyquantFetcher` in `tests/test_fetcher_structure.py`:

```python
    def test_map_adjust(self, fetcher):
        from stock_data.data_provider.fetchers.myquant_fetcher import (
            ADJUST_NONE, ADJUST_PREV, ADJUST_POST,
        )
        assert fetcher._map_adjust("") == ADJUST_NONE
        assert fetcher._map_adjust(None) == ADJUST_NONE
        assert fetcher._map_adjust("qfq") == ADJUST_PREV
        assert fetcher._map_adjust("hfq") == ADJUST_POST

    def test_convert_code_sh(self, fetcher):
        from stock_data.data_provider.utils.code_converter import to_myquant_format
        assert fetcher._convert_code("600519") == to_myquant_format("600519")

    def test_convert_code_sz(self, fetcher):
        from stock_data.data_provider.utils.code_converter import to_myquant_format
        assert fetcher._convert_code("000001") == to_myquant_format("000001")

    def test_convert_code_hk_raises(self, fetcher):
        from stock_data.data_provider.base import DataFetchError
        with pytest.raises(DataFetchError, match="Myquant does not support"):
            fetcher._convert_code("HK00700")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd E:/GitRepo/stock_data && .venv/Scripts/python.exe -m pytest tests/test_fetcher_structure.py::TestMyquantFetcher -k "map_adjust or convert_code" -v`
Expected: AttributeError on `_map_adjust` and `_convert_code`

- [ ] **Step 3: Add the three methods to the fetcher**

In `stock_data/data_provider/fetchers/myquant_fetcher.py`, **before** the class definition (or wherever logical), we don't need anything new. Add these methods **inside** `MyquantFetcher` class, right after `is_available`:

```python
    def _map_adjust(self, adjust: str) -> int:
        """Map unified adjust to myquant integer constant.

        "" / None → ADJUST_NONE (0)
        "qfq"      → ADJUST_PREV (1)
        "hfq"      → ADJUST_POST (2)
        """
        if not adjust:
            return ADJUST_NONE
        mapping = {"qfq": ADJUST_PREV, "hfq": ADJUST_POST}
        return mapping.get(adjust, ADJUST_NONE)

    def _convert_code(self, stock_code: str) -> str:
        """Convert to myquant ``SHSE/SZSE.{code}`` format. Raises DataFetchError on unsupported markets."""
        try:
            return to_myquant_format(stock_code)
        except ValueError as e:
            raise DataFetchError(f"Myquant does not support code {stock_code}: {e}") from e
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd E:/GitRepo/stock_data && .venv/Scripts/python.exe -m pytest tests/test_fetcher_structure.py::TestMyquantFetcher -k "map_adjust or convert_code" -v`
Expected: 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add stock_data/data_provider/fetchers/myquant_fetcher.py tests/test_fetcher_structure.py
git commit -m "feat(myquant-fetcher): add _map_adjust and _convert_code"
```

---

## Task 5: Implement stock historical K-line (`get_kline_data` override)

**Files:**
- Modify: `stock_data/data_provider/fetchers/myquant_fetcher.py`
- Modify: `tests/test_fetcher_structure.py`

- [ ] **Step 1: Write failing tests for frequency rejection and normalization**

Append to `TestMyquantFetcher`:

```python
    def test_fetch_unsupported_weekly_raises(self, fetcher):
        from stock_data.data_provider.base import DataFetchError
        with pytest.raises(DataFetchError, match="does not support frequency"):
            fetcher._fetch_raw_data("600519", "2024-01-01", "2024-01-31", frequency="w")

    def test_fetch_unsupported_monthly_raises(self, fetcher):
        from stock_data.data_provider.base import DataFetchError
        with pytest.raises(DataFetchError, match="does not support frequency"):
            fetcher._fetch_raw_data("600519", "2024-01-01", "2024-01-31", frequency="m")

    def test_fetch_unsupported_1min_raises(self, fetcher):
        from stock_data.data_provider.base import DataFetchError
        with pytest.raises(DataFetchError, match="does not support frequency"):
            fetcher._fetch_raw_data("600519", "2024-01-01", "2024-01-31", frequency="1")

    def test_normalize_history_dataframe(self, fetcher):
        """myquant history returns columns: open, close, high, low, amount, volume, bob, eob.
        Normalization should map 'bob' → 'date' and produce STANDARD_COLUMNS."""
        import pandas as pd
        raw = pd.DataFrame({
            "symbol": ["SHSE.600519"] * 3,
            "frequency": ["1d"] * 3,
            "open": [1700.0, 1710.0, 1720.0],
            "close": [1710.0, 1720.0, 1730.0],
            "high": [1715.0, 1725.0, 1735.0],
            "low": [1695.0, 1705.0, 1715.0],
            "amount": [1e9, 1.1e9, 1.2e9],
            "volume": [1e6, 1.1e6, 1.2e6],
            "bob": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]),
            "eob": pd.to_datetime(["2024-01-01 15:00", "2024-01-02 15:00", "2024-01-03 15:00"]),
        })
        normalized = fetcher._normalize_data(raw, "600519")
        # Required STANDARD_COLUMNS
        for col in ["date", "open", "high", "low", "close", "volume", "amount"]:
            assert col in normalized.columns, f"missing {col}"
        # pct_chg computed from close/open since myquant doesn't return it
        assert "pct_chg" in normalized.columns
        # First row pct_chg = 1710/1700 - 1 = 0.588% (rounded to 2 dp)
        assert abs(normalized.iloc[0]["pct_chg"] - 0.59) < 0.01
        # code column added
        assert "code" in normalized.columns
        assert normalized.iloc[0]["code"] == "600519"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd E:/GitRepo/stock_data && .venv/Scripts/python.exe -m pytest tests/test_fetcher_structure.py::TestMyquantFetcher -k "unsupported or normalize_history" -v`
Expected: AttributeError on `_fetch_raw_data` (current impl raises DataFetchError with wrong message) and the normalize test won't produce pct_chg (no impl yet).

- [ ] **Step 3: Implement `_fetch_raw_data` and `_normalize_data`**

In `stock_data/data_provider/fetchers/myquant_fetcher.py`, **replace** the placeholder implementations of `_fetch_raw_data` and `_normalize_data` with the real ones. The current placeholders raise `DataFetchError("MyquantFetcher routes through get_kline_data override")`. Replace the entire `_fetch_raw_data` method:

```python
    def _fetch_raw_data(
        self,
        stock_code: str,
        start_date: str,
        end_date: str,
        frequency: str = "d",
        adjust: str | None = None,
    ) -> pd.DataFrame:
        """Fetch K-line data from myquant (stocks only — indices use get_index_historical).

        Supported frequencies: d, 5, 15, 30, 60. Raises DataFetchError on others.
        """
        if not self.is_available():
            return None  # type: ignore[return-value]
        if frequency not in _FREQ_MAP:
            raise DataFetchError(
                f"MyquantFetcher does not support frequency={frequency!r} "
                f"(supported: {sorted(_FREQ_MAP.keys())})"
            )

        try:
            from gm.api import history  # type: ignore

            symbol = self._convert_code(stock_code)
            df = history(
                symbol=symbol,
                frequency=_FREQ_MAP[frequency],
                start_time=start_date,
                end_time=end_date,
                adjust=self._map_adjust(adjust or ""),
                df=True,
            )
            if df is None or df.empty:
                raise DataFetchError(f"Myquant returned empty for {stock_code}")
            return df
        except DataFetchError:
            raise
        except Exception as e:
            raise DataFetchError(f"Myquant fetch_raw_data failed for {stock_code}: {e}") from e
```

Now replace the placeholder `_normalize_data`:

```python
    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        """Normalize myquant history output to STANDARD_COLUMNS.

        myquant returns: symbol, frequency, open, close, high, low, amount, volume, bob, eob.
        - 'bob' (begin of bar) is the time anchor → renamed to 'date'
        - 'pct_chg' is NOT provided by myquant → computed from close/open (×100)
        - Other STANDARD_COLUMNS already match the source naming.
        """
        df = df.copy()
        if "bob" in df.columns:
            df = df.rename(columns={"bob": "date"})
        # myquant doesn't return pct_chg; derive it from close vs open (consistent with the
        # rest of the codebase, which uses open as the reference for "intraday change").
        if "pct_chg" not in df.columns and "open" in df.columns and "close" in df.columns:
            open_num = pd.to_numeric(df["open"], errors="coerce")
            close_num = pd.to_numeric(df["close"], errors="coerce")
            df["pct_chg"] = ((close_num / open_num) - 1.0) * 100.0
        return self._normalize_dataframe(df, stock_code, column_mapping={})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd E:/GitRepo/stock_data && .venv/Scripts/python.exe -m pytest tests/test_fetcher_structure.py::TestMyquantFetcher -k "unsupported or normalize_history" -v`
Expected: 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add stock_data/data_provider/fetchers/myquant_fetcher.py tests/test_fetcher_structure.py
git commit -m "feat(myquant-fetcher): implement stock historical kline + normalize"
```

---

## Task 6: Implement `get_realtime_quote` (minimal, price-only)

**Files:**
- Modify: `stock_data/data_provider/fetchers/myquant_fetcher.py`
- Modify: `tests/test_fetcher_structure.py`

- [ ] **Step 1: Write failing test**

Append to `TestMyquantFetcher`:

```python
    def test_realtime_quote_without_token_returns_none(self, fetcher_no_token):
        assert fetcher_no_token.get_realtime_quote("600519") is None

    def test_realtime_quote_uses_myquant_source(self, fetcher, monkeypatch):
        """When gm returns data, source should be RealtimeSource.MYQUANT."""
        from stock_data.data_provider.core.types import RealtimeSource
        from gm.api import current_price as gm_current_price

        def fake_current_price(symbols, **_kwargs):
            return [{"symbol": "SHSE.600519", "price": 1700.5, "created_at": None}]

        monkeypatch.setattr(
            "gm.api.current_price", fake_current_price, raising=False
        )
        quote = fetcher.get_realtime_quote("600519")
        assert quote is not None
        assert quote.code == "600519"
        assert quote.price == 1700.5
        assert quote.source == RealtimeSource.MYQUANT
        # Other fields are intentionally None
        assert quote.volume is None
        assert quote.change_pct is None
        assert quote.pre_close is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd E:/GitRepo/stock_data && .venv/Scripts/python.exe -m pytest tests/test_fetcher_structure.py::TestMyquantFetcher -k "realtime_quote" -v`
Expected: First test passes (return None) but second test will fail because `get_realtime_quote` doesn't exist (returns None from base class).

- [ ] **Step 3: Implement `get_realtime_quote`**

In `stock_data/data_provider/fetchers/myquant_fetcher.py`, add this method right after `_normalize_data`:

```python
    def get_realtime_quote(self, stock_code: str) -> UnifiedRealtimeQuote | None:
        """Get realtime quote from myquant.

        Note: myquant's ``current_price`` only returns ``{symbol, price, created_at}`` —
        no volume/amount/change_pct/open/high/low. This fetcher is therefore
        positioned as a *last-resort* backup; richer quotes come from Tushare/
        Tencent/Zhitu in the failover chain. Most other fields stay ``None``.
        """
        if not self.is_available():
            return None
        try:
            from gm.api import current_price  # type: ignore

            symbol = self._convert_code(stock_code)
            rows = current_price(symbols=symbol)
            if not rows:
                return None
            row = rows[0] if isinstance(rows, list) else rows
            return UnifiedRealtimeQuote(
                code=normalize_stock_code(stock_code),
                source=RealtimeSource.MYQUANT,
                price=safe_float(row.get("price")),
            )
        except Exception as e:
            logger.warning(f"[MyquantFetcher] get_realtime_quote failed for {stock_code}: {e}")
            return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd E:/GitRepo/stock_data && .venv/Scripts/python.exe -m pytest tests/test_fetcher_structure.py::TestMyquantFetcher -k "realtime_quote" -v`
Expected: Both tests pass.

- [ ] **Step 5: Commit**

```bash
git add stock_data/data_provider/fetchers/myquant_fetcher.py tests/test_fetcher_structure.py
git commit -m "feat(myquant-fetcher): implement get_realtime_quote (price-only)"
```

---

## Task 7: Implement `get_trade_calendar`

**Files:**
- Modify: `stock_data/data_provider/fetchers/myquant_fetcher.py`
- Modify: `tests/test_fetcher_structure.py`

- [ ] **Step 1: Write failing test**

Append to `TestMyquantFetcher`:

```python
    def test_trade_calendar_without_token_returns_none(self, fetcher_no_token):
        assert fetcher_no_token.get_trade_calendar() is None

    def test_trade_calendar_parses_myquant_dataframe(self, fetcher, monkeypatch):
        import pandas as pd
        from gm.api import get_trading_dates_by_year as gm_calendar

        def fake_calendar(*_args, **_kwargs):
            return pd.DataFrame({
                "date": ["2024-01-01", "2024-01-02", "2024-01-03"],
                "trade_date": ["", "2024-01-02", "2024-01-03"],
                "pre_trade_date": ["", "2023-12-29", "2024-01-02"],
                "next_trade_date": ["2024-01-02", "2024-01-03", "2024-01-04"],
            })

        monkeypatch.setattr(
            "gm.api.get_trading_dates_by_year", fake_calendar, raising=False
        )
        dates = fetcher.get_trade_calendar()
        assert dates == ["2024-01-02", "2024-01-03"]  # Empty trade_date filtered, sorted asc
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd E:/GitRepo/stock_data && .venv/Scripts/python.exe -m pytest tests/test_fetcher_structure.py::TestMyquantFetcher -k "trade_calendar" -v`
Expected: First passes, second fails (returns None from base class).

- [ ] **Step 3: Implement `get_trade_calendar`**

In `stock_data/data_provider/fetchers/myquant_fetcher.py`, add this method right after `get_realtime_quote`:

```python
    def get_trade_calendar(self) -> list[str] | None:
        """Get A-share trade calendar from myquant.

        Uses SHSE calendar (沪深共用). Returns ascending YYYY-MM-DD list.
        Returns None if unavailable or no data.
        """
        if not self.is_available():
            return None
        try:
            from gm.api import get_trading_dates_by_year  # type: ignore

            now = datetime.now()
            df = get_trading_dates_by_year(
                exchange="SHSE",
                start_year=2010,
                end_year=now.year,
            )
            if df is None or df.empty or "trade_date" not in df.columns:
                return None
            # myquant sets trade_date="" for non-trading days; filter those out
            dates = [
                d for d in df["trade_date"].astype(str).tolist()
                if d and d not in ("", "nan", "None")
            ]
            return sorted(dates)
        except Exception as e:
            logger.warning(f"[MyquantFetcher] get_trade_calendar failed: {e}")
            return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd E:/GitRepo/stock_data && .venv/Scripts/python.exe -m pytest tests/test_fetcher_structure.py::TestMyquantFetcher -k "trade_calendar" -v`
Expected: Both tests pass.

- [ ] **Step 5: Commit**

```bash
git add stock_data/data_provider/fetchers/myquant_fetcher.py tests/test_fetcher_structure.py
git commit -m "feat(myquant-fetcher): implement get_trade_calendar"
```

---

## Task 8: Implement `get_all_stocks` (STOCK_LIST)

**Files:**
- Modify: `stock_data/data_provider/fetchers/myquant_fetcher.py`
- Modify: `tests/test_fetcher_structure.py`

- [ ] **Step 1: Write failing test**

Append to `TestMyquantFetcher`:

```python
    def test_get_all_stocks_without_token_returns_empty(self, fetcher_no_token):
        assert fetcher_no_stock_list := fetcher_no_token.get_all_stocks("csi") == []

    def test_get_all_stocks_normalizes_myquant_dataframe(self, fetcher, monkeypatch):
        import pandas as pd
        from gm.api import get_symbols as gm_get_symbols

        def fake_get_symbols(*_args, **_kwargs):
            return pd.DataFrame({
                "symbol": ["SHSE.600519", "SZSE.000001"],
                "sec_name": ["贵州茅台", "平安银行"],
                "is_st": [False, False],
                "is_suspended": [False, False],
                "upper_limit": [1872.10, 11.55],
                "lower_limit": [1531.72, 9.45],
                "turn_rate": [0.5, 0.3],
                "adj_factor": [1.0, 1.0],
                "pre_close": [1701.91, 10.50],
            })

        monkeypatch.setattr("gm.api.get_symbols", fake_get_symbols, raising=False)
        stocks = fetcher.get_all_stocks("csi")
        assert len(stocks) == 2
        # SHSE.600519 → "600519" (strip exchange prefix)
        assert stocks[0]["code"] == "600519"
        assert stocks[0]["name"] == "贵州茅台"
        assert stocks[0]["upper_limit"] == 1872.10
        # SZSE.000001 → "000001"
        assert stocks[1]["code"] == "000001"

    def test_get_all_stocks_non_csi_returns_empty(self, fetcher):
        assert fetcher.get_all_stocks("hk") == []
        assert fetcher.get_all_stocks("us") == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd E:/GitRepo/stock_data && .venv/Scripts/python.exe -m pytest tests/test_fetcher_structure.py::TestMyquantFetcher -k "get_all_stocks" -v`
Expected: 3 failures.

- [ ] **Step 3: Implement `get_all_stocks`**

In `stock_data/data_provider/fetchers/myquant_fetcher.py`, add this method right after `get_trade_calendar`:

```python
    def get_all_stocks(self, market: str = "csi") -> list:
        """Get A-share stock list from myquant.

        myquant's ``get_symbols(sec_type1=1010)`` returns additional fields
        beyond code/name: upper_limit / lower_limit / is_st / is_suspended /
        pre_close / turn_rate / adj_factor. We surface these as raw dict keys
        so the persistence layer can optionally consume them.

        Returns ``[]`` for non-CSI markets (myquant only covers A-share).
        """
        if market != "csi":
            return []
        if not self.is_available():
            return []
        try:
            from gm.api import get_symbols  # type: ignore

            df = get_symbols(sec_type1=1010, df=True)
            if df is None or df.empty:
                return []
            out: list = []
            for _, row in df.iterrows():
                full = str(row.get("symbol", ""))
                code = full.split(".", 1)[1] if "." in full else full
                out.append({
                    "code": code,
                    "name": str(row.get("sec_name", "")),
                    "symbol_full": full,
                    "exchange": str(row.get("exchange", "")),
                    "is_st": bool(row.get("is_st", False)),
                    "is_suspended": bool(row.get("is_suspended", False)),
                    "upper_limit": safe_float(row.get("upper_limit")),
                    "lower_limit": safe_float(row.get("lower_limit")),
                    "turn_rate": safe_float(row.get("turn_rate")),
                    "adj_factor": safe_float(row.get("adj_factor")),
                    "pre_close": safe_float(row.get("pre_close")),
                })
            return out
        except Exception as e:
            logger.warning(f"[MyquantFetcher] get_all_stocks failed: {e}")
            return []
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd E:/GitRepo/stock_data && .venv/Scripts/python.exe -m pytest tests/test_fetcher_structure.py::TestMyquantFetcher -k "get_all_stocks" -v`
Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add stock_data/data_provider/fetchers/myquant_fetcher.py tests/test_fetcher_structure.py
git commit -m "feat(myquant-fetcher): implement get_all_stocks"
```

---

## Task 9: Implement `get_index_historical` and `get_index_intraday`

**Files:**
- Modify: `stock_data/data_provider/fetchers/myquant_fetcher.py`
- Modify: `tests/test_fetcher_structure.py`

- [ ] **Step 1: Write failing tests**

Append to `TestMyquantFetcher`:

```python
    def test_index_historical_without_token_returns_none(self, fetcher_no_token):
        assert fetcher_no_token.get_index_historical(
            "000300", "2024-01-01", "2024-01-31", "d"
        ) is None

    def test_index_historical_uses_myquant(self, fetcher, monkeypatch):
        import pandas as pd
        from gm.api import history as gm_history

        def fake_history(*_args, **_kwargs):
            return pd.DataFrame({
                "symbol": ["SHSE.000300"] * 2,
                "frequency": ["1d"] * 2,
                "open": [3500.0, 3510.0],
                "close": [3510.0, 3520.0],
                "high": [3520.0, 3530.0],
                "low": [3490.0, 3500.0],
                "amount": [1e11, 1.1e11],
                "volume": [1e8, 1.1e8],
                "bob": pd.to_datetime(["2024-01-01", "2024-01-02"]),
                "eob": pd.to_datetime(["2024-01-01 15:00", "2024-01-02 15:00"]),
            })

        monkeypatch.setattr("gm.api.history", fake_history, raising=False)
        df = fetcher.get_index_historical("000300", "2024-01-01", "2024-01-31", "d")
        assert df is not None
        assert "date" in df.columns
        assert "pct_chg" in df.columns

    def test_index_historical_minute_raises(self, fetcher):
        from stock_data.data_provider.base import DataFetchError
        with pytest.raises(DataFetchError, match="index does not support frequency"):
            fetcher.get_index_historical("000300", "2024-01-01", "2024-01-31", "5")

    def test_index_intraday_unsupported_1min_raises(self, fetcher):
        from stock_data.data_provider.base import DataFetchError
        with pytest.raises(DataFetchError, match="index intraday does not support"):
            fetcher.get_index_intraday("000300", period="1")

    def test_index_intraday_non_csi_raises(self, fetcher):
        from stock_data.data_provider.base import DataFetchError
        with pytest.raises(DataFetchError, match="Myquant does not support"):
            fetcher.get_index_intraday("HSI", period="5")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd E:/GitRepo/stock_data && .venv/Scripts/python.exe -m pytest tests/test_fetcher_structure.py::TestMyquantFetcher -k "index_" -v`
Expected: All fail (methods don't exist).

- [ ] **Step 3: Implement index methods**

In `stock_data/data_provider/fetchers/myquant_fetcher.py`, add these two methods after `get_all_stocks`:

```python
    def get_index_historical(
        self,
        index_code: str,
        start_date: str | None,
        end_date: str | None,
        frequency: str,
    ) -> pd.DataFrame | None:
        """Get historical K-line data for a CSI index via myquant.

        Only ``frequency="d"`` is supported. Weekly/monthly would need
        separate ``history`` calls aggregated client-side, which we don't
        implement here — the manager will fall through to other fetchers.
        """
        if not self.is_available():
            return None
        if frequency != "d":
            raise DataFetchError(
                f"MyquantFetcher index does not support frequency={frequency!r} "
                "(only 'd' is supported; use another fetcher for w/m)"
            )
        try:
            from gm.api import history  # type: ignore

            symbol = to_myquant_index_format(index_code)
            df = history(
                symbol=symbol,
                frequency="1d",
                start_time=start_date or "",
                end_time=end_date or "",
                df=True,
            )
            if df is None or df.empty:
                return None
            return self._normalize_index_df(df)
        except DataFetchError:
            raise
        except Exception as e:
            logger.warning(
                f"[MyquantFetcher] get_index_historical failed for {index_code}: {e}"
            )
            return None

    def get_index_intraday(
        self, index_code: str, period: str = "5"
    ) -> pd.DataFrame | None:
        """Get intraday minute-level data for a CSI index via myquant.

        Fetches the most recent trading day (myquant 18:00 wash rule applies
        for same-day data; for older dates the result is also fine).
        """
        if not self.is_available():
            return None
        if period not in _INDEX_FREQ_MAP:
            raise DataFetchError(
                f"MyquantFetcher index intraday does not support period={period!r} "
                f"(supported: {sorted(_INDEX_FREQ_MAP.keys())})"
            )
        try:
            from gm.api import history  # type: ignore

            symbol = to_myquant_index_format(index_code)
            today = datetime.now().strftime("%Y-%m-%d")
            df = history(
                symbol=symbol,
                frequency=_INDEX_FREQ_MAP[period],
                start_time=today,
                end_time=today,
                df=True,
            )
            if df is None or df.empty:
                return None
            return self._normalize_index_intraday_df(df, period)
        except DataFetchError:
            raise
        except Exception as e:
            logger.warning(
                f"[MyquantFetcher] get_index_intraday failed for {index_code}: {e}"
            )
            return None

    def _normalize_index_df(self, df: pd.DataFrame) -> pd.DataFrame:
        """Normalize myquant daily-index history to STANDARD_COLUMNS + 'code'."""
        df = df.copy()
        if "bob" in df.columns:
            df = df.rename(columns={"bob": "date"})
        if "pct_chg" not in df.columns and "open" in df.columns and "close" in df.columns:
            open_num = pd.to_numeric(df["open"], errors="coerce")
            close_num = pd.to_numeric(df["close"], errors="coerce")
            df["pct_chg"] = ((close_num / open_num) - 1.0) * 100.0
        # No 'code' column needed for index history; strip symbol-related noise
        for col in ("symbol", "frequency"):
            if col in df.columns:
                df = df.drop(columns=[col])
        return df

    def _normalize_index_intraday_df(
        self, df: pd.DataFrame, period: str
    ) -> pd.DataFrame:
        """Normalize myquant index intraday to time/o/h/l/c/v/a schema."""
        df = df.copy()
        if "bob" in df.columns:
            df = df.rename(columns={"bob": "time"})
        elif "eob" in df.columns:
            df = df.rename(columns={"eob": "time"})
        # Coerce to HH:MM:SS strings if datetime
        if "time" in df.columns and hasattr(df["time"].iloc[0] if len(df) else None, "strftime"):
            df["time"] = df["time"].dt.strftime("%H:%M:%S")
        for col in ("open", "high", "low", "close", "amount"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        if "volume" in df.columns:
            df["volume"] = pd.to_numeric(df["volume"], errors="coerce").astype("Int64")
        keep = [c for c in ("time", "open", "high", "low", "close", "volume", "amount") if c in df.columns]
        return df[keep]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd E:/GitRepo/stock_data && .venv/Scripts/python.exe -m pytest tests/test_fetcher_structure.py::TestMyquantFetcher -k "index_" -v`
Expected: All 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add stock_data/data_provider/fetchers/myquant_fetcher.py tests/test_fetcher_structure.py
git commit -m "feat(myquant-fetcher): implement index historical + intraday"
```

---

## Task 10: Register `MyquantFetcher` in manager

**Files:**
- Modify: `stock_data/data_provider/manager.py`

- [ ] **Step 1: Add import + registration**

Open `stock_data/data_provider/manager.py`. Find the `create_default_manager` function. The current order is:

```python
    fetcher_classes = [
        TushareFetcher,
        BaostockFetcher,
        AkshareFetcher,
        YfinanceFetcher,
        ZhituFetcher,
        TencentFetcher,
        EastMoneyFetcher,
        ThsFetcher,
        CninfoFetcher,
    ]
```

Add `MyquantFetcher` **between Baostock and Akshare** (so it gets priority 1 with Baostock, but Baostock retains the first slot by registration order). Also add the lazy import at the top of the imports block:

Modify the imports section to add:

```python
    from .fetchers.myquant_fetcher import MyquantFetcher
```

Right after `from .fetchers.eastmoney_fetcher import EastMoneyFetcher`. Then modify the list:

```python
    fetcher_classes = [
        TushareFetcher,
        BaostockFetcher,
        MyquantFetcher,
        AkshareFetcher,
        YfinanceFetcher,
        ZhituFetcher,
        TencentFetcher,
        EastMoneyFetcher,
        ThsFetcher,
        CninfoFetcher,
    ]
```

- [ ] **Step 2: Verify import works**

Run: `cd E:/GitRepo/stock_data && .venv/Scripts/python.exe -c "from stock_data.data_provider.manager import create_default_manager; m = create_default_manager(); print('fetchers:', [f.name for f in m.fetchers])"`
Expected: Includes `MyquantFetcher` (when MYQUANT_TOKEN is set) or skipped silently. Either way, no exceptions.

Note: Since the .env has `MYQUANT_TOKEN=270d45b48cd38b4824eadd1e69d637c60e13aa9e`, MyquantFetcher should be registered.

- [ ] **Step 3: Run the full fetcher test suite**

Run: `cd E:/GitRepo/stock_data && .venv/Scripts/python.exe -m pytest tests/test_fetcher_structure.py -v`
Expected: All fetcher tests pass (including the 22+ new Myquant tests + existing tests).

- [ ] **Step 4: Commit**

```bash
git add stock_data/data_provider/manager.py
git commit -m "feat(manager): register MyquantFetcher in create_default_manager"
```

---

## Task 11: Update `.env.example` and `pyproject.toml`

**Files:**
- Modify: `.env.example`
- Modify: `pyproject.toml`

- [ ] **Step 1: Add `MYQUANT_TOKEN` block to `.env.example`**

Open `.env.example`. After the `=== Zhitu ===` block (line ~12), add a new section before `=== Server Configuration ===`:

```bash
# === Myquant (掘金量化) (Priority 1 for A-share backup, requires token) ===
# Get your token from: https://www.myquant.cn/
MYQUANT_TOKEN=

# === Myquant Priority Override ===
# Default: 1 (right after Tushare=0, alongside Baostock=1)
# MYQUANT_PRIORITY=1
```

- [ ] **Step 2: Add `gm` dependency to `pyproject.toml`**

Open `pyproject.toml`. In the `dependencies` list (alphabetical-ish order), add `gm` right after `baostock`:

```toml
    "akshare>=1.14.0",
    "baostock>=0.8.8",
    "gm>=3.0.148,<4",
    "yfinance>=0.2.0",
```

- [ ] **Step 3: Verify install still works (with warning)**

Run: `cd E:/GitRepo/stock_data && .venv/Scripts/python.exe -m pip install -e ".[dev]" 2>&1 | tail -10`
Expected: Installs successfully. The gm/pandas dependency warning is expected and acceptable (verified in spec).

- [ ] **Step 4: Commit**

```bash
git add .env.example pyproject.toml
git commit -m "chore: add myquant token config + gm dependency"
```

---

## Task 12: Update `CLAUDE.md` (priority + capability tables)

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update fetcher capability declarations table**

Find the table in `CLAUDE.md` under "Fetcher capability declarations:". The current rows (top to bottom) are BaostockFetcher, AkshareFetcher, TushareFetcher, YfinanceFetcher, ZhituFetcher, TencentFetcher, EastMoneyFetcher, ThsFetcher, CninfoFetcher. Add a new row for MyquantFetcher right after TushareFetcher (alphabetical-ish):

```markdown
| MyquantFetcher | `HISTORICAL_DWM \| HISTORICAL_MIN \| REALTIME_QUOTE \| STOCK_LIST \| TRADE_CALENDAR \| INDEX_HISTORICAL \| INDEX_INTRADAY` | csi |
```

- [ ] **Step 2: Update environment variables section**

Find the "Configuration" section. Add `MYQUANT_TOKEN` and `MYQUANT_PRIORITY` entries after the `TENCENT_PRIORITY` line:

```markdown
- `MYQUANT_TOKEN` - 掘金量化 myquant SDK token (https://www.myquant.cn/)
- `MYQUANT_PRIORITY` - Override Myquant fetcher priority (default: 1)
```

- [ ] **Step 3: Add a new section in the Provider API Documentation for Myquant**

Right before the `## Provider Frequency Support` section, add a `### MyquantFetcher (Priority 1, A股 only, Requires Token, Backup fetcher)` section. Use this content (concise — full details in docs/myquant/):

```markdown
### MyquantFetcher (Priority 1, A股 only, Requires Token, Backup)

**SDK**: `gm` (pip install gm>=3.0.148) — https://www.myquant.cn/

**Used APIs** (all free / public-tier):
- `gm.api.history(symbol, frequency, ...)` — 日线 + 分钟线（60s/300s/900s/1800s/3600s）历史 K 线
- `gm.api.current_price(symbols)` — 实时最新价（仅 price，无其他字段；定位为"最后兜底"）
- `gm.api.get_symbols(sec_type1=1010)` — 股票列表（含 ST/停牌/涨跌停价/复权因子）
- `gm.api.get_trading_dates_by_year(exchange, ...)` — 交易日历
- `gm.api.history(指数代码)` — 指数 K 线（日线 + 分钟线）

**Token**: Set via `MYQUANT_TOKEN` environment variable. Lazy `gm.api.set_token` on first use.

**Note**:
- 仅 A 股（SHSE/SZSE），**无港股/美股**
- 不支持周线/月线/1 分钟线 — `raise DataFetchError` 透明降级
- 盘后 18:00 清洗入库
- myquant `current_price` 字段极简（仅 price），其他字段保持 None；fallover 链上为"最后兜底"角色
- 依赖注：gm 3.0.184 声明 `pandas<2.0`（Python ≤3.11）— 该 pin 是 myquant 端过度保守；运行时与 pandas 2.x 兼容（已验证）。`pip install` 会产生 dependency warning，不影响功能。
```

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: document MyquantFetcher in CLAUDE.md"
```

---

## Task 13: Run full test suite + lint, fix any breakage

**Files:** none (verification only)

- [ ] **Step 1: Run full test suite**

Run: `cd E:/GitRepo/stock_data && .venv/Scripts/python.exe -m pytest -v 2>&1 | tail -50`
Expected: All tests pass (existing + new TestMyquantFetcher). If any pre-existing test fails due to manager registration order, investigate and fix.

- [ ] **Step 2: Run ruff lint**

Run: `cd E:/GitRepo/stock_data && .venv/Scripts/python.exe -m ruff check . 2>&1 | tail -20`
Expected: Clean (no errors). If there are import-order or unused-import warnings, fix them.

- [ ] **Step 3: Run ruff format check**

Run: `cd E:/GitRepo/stock_data && .venv/Scripts/python.exe -m ruff format --check . 2>&1 | tail -10`
Expected: No changes needed (or auto-fix with `ruff format .` if minor).

- [ ] **Step 4: Smoke-test the manager with a real call**

Run: `cd E:/GitRepo/stock_data && .venv/Scripts/python.exe -c "
from stock_data.data_provider.manager import create_default_manager
m = create_default_manager()
print('Registered:', [f.name for f in m.fetchers])
# Try a quick route: get_kline_data should not error even if myquant fails (token in .env)
try:
    df, src = m.get_kline_data('600519', days=5, frequency='d')
    print(f'Source={src}, rows={len(df)}')
except Exception as e:
    print(f'Error (expected if no internet): {e}')
" 2>&1 | tail -10`
Expected: MyquantFetcher appears in registered list. If network available, kline data is returned (possibly from a different fetcher in the failover chain).

- [ ] **Step 5: Final commit if any fixups were needed**

```bash
git status
# If any files changed:
git add -A
git commit -m "chore: post-impl cleanup (ruff + tests)"
```

---

## Self-Review Checklist (run before declaring done)

- [ ] All 9 files created/modified as listed in File Structure
- [ ] 14+ new tests in `TestMyquantFetcher` all pass
- [ ] Existing fetcher tests still pass (no regression)
- [ ] `ruff check .` and `ruff format --check .` clean
- [ ] `manager.create_default_manager()` registers MyquantFetcher when token is set
- [ ] `.env.example` documents `MYQUANT_TOKEN`
- [ ] `CLAUDE.md` updated (priority table, env vars, provider doc)
- [ ] Spec at `docs/superpowers/specs/2026-06-09-myquant-fetcher-design.md` matches implementation (capability set, priority, frequency map)
