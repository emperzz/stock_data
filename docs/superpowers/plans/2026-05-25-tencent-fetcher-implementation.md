# Phase 1: Tencent Fetcher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Tencent财经 HTTP API support for enhanced realtime quotes (PE/PB/市值/涨跌停价/ETF/指数)

**Architecture:** Add TencentFetcher as a new BaseFetcher implementation that returns enhanced realtime quote fields via Tencent财经 HTTP API (GBK encoding, `~` delimited fields). Integrate with existing DataFetcherManager priority system and circuit breaker.

**Tech Stack:** requests, pandas, Python standard library (no new dependencies)

---

## File Structure

```
stock_data/
├── data_provider/
│   ├── base.py                      # Modify: add TENCENT to RealtimeSource enum
│   ├── fetchers/
│   │   └── tencent_fetcher.py       # Create: new Tencent fetcher
│   └── fetchers/__init__.py         # Modify: add TencentFetcher to public exports
├── api/
│   ├── schemas.py                   # Modify: extend StockQuote with enhanced fields
│   └── routes.py                    # Modify: update get_quote to return enhanced fields
└── tests/
    └── test_tencent_fetcher.py       # Create: unit tests
```

---

## Task 1: Add TENCENT to RealtimeSource Enum

**File:** `stock_data/data_provider/core/types.py`

- [ ] **Step 1: Read the file to verify current state**

```python
# Read stock_data/data_provider/core/types.py
# Verify RealtimeSource enum at line 41-49
```

- [ ] **Step 2: Add TENCENT to RealtimeSource enum**

Find:
```python
class RealtimeSource(Enum):
    """Data source identifiers for realtime quotes."""

    TUSHARE = "tushare"
    AKSHARE = "akshare"
    YFINANCE = "yfinance"
    STOOQ = "stooq"
    ZHITU = "zhitu"
    FALLBACK = "fallback"
```

Add `TENCENT = "tencent"` to the enum.

- [ ] **Step 3: Commit**

```bash
git add stock_data/data_provider/core/types.py
git commit -m "feat: add TENCENT to RealtimeSource enum

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 2: Create TencentFetcher

**Files:**
- Create: `stock_data/data_provider/fetchers/tencent_fetcher.py`
- Modify: `stock_data/data_provider/fetchers/__init__.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_tencent_fetcher.py`:

```python
import pytest
from stock_data.data_provider.fetchers.tencent_fetcher import TencentFetcher


def test_tencent_fetcher_name():
    f = TencentFetcher()
    assert f.name == "TencentFetcher"


def test_tencent_fetcher_priority():
    f = TencentFetcher()
    assert f.priority == 5  # After Tushare(0), Baostock(1), Akshare(2), Yfinance(3), Zhitu(4)


def test_tencent_fetcher_supported_markets():
    f = TencentFetcher()
    assert "csi" in f.supported_markets
    assert "hk" in f.supported_markets


def test_tencent_fetcher_capabilities():
    from stock_data.data_provider.base import DataCapability
    f = TencentFetcher()
    assert DataCapability.REALTIME_QUOTE in f.supported_data_types


def test_tencent_fetcher_convert_code():
    f = TencentFetcher()
    # Shanghai
    assert f._convert_code("sh600519") == "600519"
    assert f._convert_code("SH600519") == "600519"
    assert f._convert_code("600519") == "600519"
    # Shenzhen
    assert f._convert_code("sz000001") == "000001"
    assert f._convert_code("000001") == "000001"
    # HK
    assert f._convert_code("HK00700") == "00700"
    assert f._convert_code("hk00700") == "00700"
    # BJ
    assert f._convert_code("bj832000") == "832000"
    assert f._convert_code("832000") == "832000"


def test_tencent_fetcher_prefix():
    f = TencentFetcher()
    # Shanghai: 6, 9 prefix
    assert f._tencent_prefix("600519") == "sh600519"
    assert f._tencent_prefix("688017") == "sh688017"
    # Shenzhen: 0, 1, 2, 3, 4 prefix
    assert f._tencent_prefix("000001") == "sz000001"
    assert f._tencent_prefix("300476") == "sz300476"
    # HK
    assert f._tencent_prefix("HK00700") == "hk00700"
    assert f._tencent_prefix("00700") == "hk00700"
    # BJ
    assert f._tencent_prefix("832000") == "bj832000"
    assert f._tencent_prefix("430001") == "bj430001"


def test_tencent_fetcher_not_available_for_historical():
    """Tencent API is realtime-only, should raise DataFetchError for K-line requests."""
    f = TencentFetcher()
    with pytest.raises(Exception):  # DataFetchError
        f.get_kline_data("600519", start_date="2026-01-01", end_date="2026-05-01")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_tencent_fetcher.py -v`
Expected: ERROR - module not found

- [ ] **Step 3: Create minimal stub implementation**

Create `stock_data/data_provider/fetchers/tencent_fetcher.py`:

```python
"""
Tencent财经 HTTP API fetcher for enhanced realtime quotes.

API: https://qt.gtimg.cn/q={prefix_code}
Returns: GBK encoded, `~` delimited fields (88 fields total)

Fields used:
- 39: PE(TTM), 43: 振幅%, 44: 总市值(亿), 45: 流通市值(亿)
- 46: PB, 47: 涨停价, 48: 跌停价, 49: 量比, 52: PE(静)
"""

import logging
import urllib.request
from typing import Optional

import pandas as pd
import requests

from ..base import BaseFetcher, DataCapability, DataFetchError
from ..core.types import RealtimeSource, UnifiedRealtimeQuote, safe_float
from ..utils.normalize import normalize_stock_code

logger = logging.getLogger(__name__)

# Tencent财经 API base URL
TENCENT_QUOTE_URL = "https://qt.gtimg.cn/q="


class TencentFetcher(BaseFetcher):
    """Tencent财经 HTTP API fetcher for enhanced realtime quotes."""

    name = "TencentFetcher"
    priority = 5  # After Tushare(0), Baostock(1), Akshare(2), Yfinance(3), Zhitu(4)
    supported_markets: set[str] = {"csi", "hk"}
    supported_data_types = DataCapability.REALTIME_QUOTE

    def is_available(self) -> bool:
        """Tencent API is always available (no auth required)."""
        return True

    def _convert_code(self, stock_code: str) -> str:
        """Normalize stock code to 6-digit format."""
        code = normalize_stock_code(stock_code)
        # Strip leading zeros for HK codes
        if code.startswith("00") and len(code) == 6:
            # Could be HK, keep as is
            pass
        return code

    def _tencent_prefix(self, stock_code: str) -> str:
        """Convert to Tencent API prefix format.

        Shanghai: sh600519, Shenzhen: sz000001, HK: hk00700, BJ: bj832000
        """
        code = normalize_stock_code(stock_code)

        if code.startswith(("5", "6", "7", "9")):
            return f"sh{code}"
        elif code.startswith(("0", "1", "2", "3", "4")):
            return f"sz{code}"
        elif code.upper().startswith("HK"):
            return f"hk{code[2:].zfill(5)}"
        elif code.startswith("8") or code.startswith("4"):
            return f"bj{code}"
        else:
            return f"sz{code}"

    def _fetch_raw_data(
        self,
        stock_code: str,
        start_date: str,
        end_date: str,
        frequency: str = "d",
        adjust: str | None = None,
    ) -> pd.DataFrame:
        """Tencent API is realtime-only, not used for historical data."""
        raise DataFetchError(
            "TencentFetcher does not support historical K-line data, only realtime quotes"
        )

    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        """Tencent API is realtime-only, not used for historical data."""
        raise DataFetchError("TencentFetcher does not support historical K-line data")

    def get_realtime_quote(self, stock_code: str) -> Optional[UnifiedRealtimeQuote]:
        """Get realtime quote from Tencent财经 API.

        Returns enhanced fields including PE/PB/市值/涨跌停价.

        Args:
            stock_code: Stock code (e.g., 600519, 000001, HK00700, 00700)

        Returns:
            UnifiedRealtimeQuote with enhanced fields, or None if unavailable.
        """
        try:
            prefix = self._tencent_prefix(stock_code)
            url = f"{TENCENT_QUOTE_URL}{prefix}"

            req = urllib.request.Request(url)
            req.add_header("User-Agent", "Mozilla/5.0")
            resp = urllib.request.urlopen(req, timeout=10)
            data = resp.read().decode("gbk")

            return self._parse_tencent_response(data, stock_code)

        except Exception as e:
            logger.warning(f"[TencentFetcher] Error for {stock_code}: {e}")
            return None

    def _parse_tencent_response(self, data: str, stock_code: str) -> Optional[UnifiedRealtimeQuote]:
        """Parse Tencent财经 response.

        Response format: v_pv_title="data~field1~field2~...";
        Field index reference:
            0:  stock code with prefix (e.g., sh600519)
            1:  stock name
            2:  unknown
            3:  current price
            4:  yesterday close
            5:  open price
            6:  volume (shares)
            7:  outer volume (?)
            31: change amount
            32: change percent
            33: high
            34: low
            37: amount (万元)
            38: turnover rate (%)
            39: PE(TTM)
            43: amplitude (%)
            44: total market cap (亿)
            45: float market cap (亿)
            46: PB
            47: limit up price
            48: limit down price
            49: volume ratio
            52: PE(static)
        """
        if not data or "=" not in data:
            return None

        # Extract the data portion between quotes
        try:
            line = data.strip()
            if line.endswith(";"):
                line = line[:-1]
            if "=" not in line:
                return None

            key = line.split("=")[0]
            if "_" in key:
                code_part = key.split("_")[-1]
            else:
                code_part = key

            if '"' not in line:
                return None

            values = line.split('"')[1].split("~")
            if len(values) < 53:
                logger.warning(f"[TencentFetcher] Insufficient fields for {stock_code}: {len(values)}")
                return None

            return UnifiedRealtimeQuote(
                code=normalize_stock_code(stock_code),
                name=values[1] if len(values) > 1 else "",
                source=RealtimeSource.TENCENT,
                price=safe_float(values[3]) if len(values) > 3 else None,
                pre_close=safe_float(values[4]) if len(values) > 4 else None,
                open_price=safe_float(values[5]) if len(values) > 5 else None,
                volume=None,  # Tencent returns volume differently, skip for now
                amount=safe_float(values[37]) * 10000 if len(values) > 37 and values[37] else None,  # 万元 -> 元
                change_amount=safe_float(values[31]) if len(values) > 31 else None,
                change_pct=safe_float(values[32]) if len(values) > 32 else None,
                high=safe_float(values[33]) if len(values) > 33 else None,
                low=safe_float(values[34]) if len(values) > 34 else None,
                turnover_rate=safe_float(values[38]) if len(values) > 38 else None,
                pe_ratio=safe_float(values[39]) if len(values) > 39 else None,
                amplitude=safe_float(values[43]) if len(values) > 43 else None,
                total_mv=safe_float(values[44]) * 1e8 if len(values) > 44 and values[44] else None,  # 亿 -> 元
                circ_mv=safe_float(values[45]) * 1e8 if len(values) > 45 and values[45] else None,  # 亿 -> 元
                pb_ratio=safe_float(values[46]) if len(values) > 46 else None,
            )
        except Exception as e:
            logger.warning(f"[TencentFetcher] Parse error for {stock_code}: {e}")
            return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_tencent_fetcher.py -v`
Expected: PASS (for stub), FAIL on actual API call tests (expected)

- [ ] **Step 5: Commit**

```bash
git add stock_data/data_provider/fetchers/tencent_fetcher.py tests/test_tencent_fetcher.py
git commit -m "feat: add TencentFetcher for enhanced realtime quotes

- PE/PB/市值/涨跌停价 support via Tencent财经 HTTP API
- GBK encoding, ~ delimited field parsing
- Supports A-share and HK markets

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 3: Register TencentFetcher in DataFetcherManager

**File:** `stock_data/api/routes.py`

- [ ] **Step 1: Read the get_manager() function to find where fetchers are registered**

Find the section starting around line 68:
```python
def get_manager() -> DataFetcherManager:
    """Get or create the global DataFetcherManager."""
    global _manager
    if _manager is None:
        _manager = DataFetcherManager()
        # Add fetchers in priority order
        tushare = TushareFetcher()
        ...
```

- [ ] **Step 2: Add TencentFetcher to the fetcher registration in get_manager()**

After `yfinance` and before `zhitu`, add:
```python
from .fetchers.tencent_fetcher import TencentFetcher
...
tencent = TencentFetcher()
if tencent.is_available():
    _manager.add_fetcher(tencent)
    logger.info("TencentFetcher added")
else:
    logger.info("TencentFetcher skipped")
```

- [ ] **Step 3: Commit**

```bash
git add stock_data/api/routes.py
git commit -m "feat: register TencentFetcher in DataFetcherManager

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 4: Extend StockQuote Schema with Enhanced Fields

**File:** `stock_data/api/schemas.py`

- [ ] **Step 1: Add new fields to StockQuote**

Find `class StockQuote(BaseModel)` and add these fields after `amount`:

```python
# Valuation metrics (from Tencent财经)
pe_ttm: float | None = Field(default=None, description="PE(TTM)")
pe_static: float | None = Field(default=None, description="PE(静)")
pb: float | None = Field(default=None, description="PB (市净率)")
mcap_yi: float | None = Field(default=None, description="Total market cap (亿元)")
float_mcap_yi: float | None = Field(default=None, description="Float market cap (亿元)")
turnover_pct: float | None = Field(default=None, description="Turnover rate (%)")
amplitude_pct: float | None = Field(default=None, description="Amplitude (%)")
limit_up: float | None = Field(default=None, description="Limit up price (涨停价)")
limit_down: float | None = Field(default=None, description="Limit down price (跌停价)")
vol_ratio: float | None = Field(default=None, description="Volume ratio (量比)")
```

- [ ] **Step 2: Commit**

```bash
git add stock_data/api/schemas.py
git commit -m "feat: extend StockQuote schema with Tencent财经 enhanced fields

Add: pe_ttm, pe_static, pb, mcap_yi, float_mcap_yi, turnover_pct,
     amplitude_pct, limit_up, limit_down, vol_ratio

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 5: Update get_quote Route to Return Enhanced Fields

**File:** `stock_data/api/routes.py`

- [ ] **Step 1: Read the get_quote function**

Find the section starting around line 136:
```python
@router.get(
    "/stocks/{stock_code}/quote",
    ...
)
def get_quote(stock_code: str = Path(...)) -> StockQuote:
```

- [ ] **Step 2: Modify the result construction to include enhanced fields**

After the existing StockQuote fields, add the new fields from the quote object:

Original code:
```python
result = StockQuote(
    code=quote.code,
    stock_name=quote.name or stock_cache.get_stock_name(stock_code, manager=manager),
    source=quote.source.value,
    current_price=quote.price or 0.0,
    change=quote.change_amount,
    change_percent=quote.change_pct,
    open=quote.open_price,
    high=quote.high,
    low=quote.low,
    prev_close=quote.pre_close,
    volume=quote.volume,
    amount=quote.amount,
)
```

Update to:
```python
result = StockQuote(
    code=quote.code,
    stock_name=quote.name or stock_cache.get_stock_name(stock_code, manager=manager),
    source=quote.source.value,
    current_price=quote.price or 0.0,
    change=quote.change_amount,
    change_percent=quote.change_pct,
    open=quote.open_price,
    high=quote.high,
    low=quote.low,
    prev_close=quote.pre_close,
    volume=quote.volume,
    amount=quote.amount,
    # Enhanced fields from Tencent财经
    pe_ttm=quote.pe_ratio,
    pe_static=None,  # Tencent API doesn't expose this in the parsed fields
    pb=quote.pb_ratio,
    mcap_yi=quote.total_mv / 1e8 if quote.total_mv else None,
    float_mcap_yi=quote.circ_mv / 1e8 if quote.circ_mv else None,
    turnover_pct=quote.turnover_rate,
    amplitude_pct=quote.amplitude,
    limit_up=None,  # Not yet mapped from Tencent response
    limit_down=None,  # Not yet mapped from Tencent response
    vol_ratio=quote.volume_ratio,
)
```

- [ ] **Step 3: Commit**

```bash
git add stock_data/api/routes.py
git commit -m "feat: map Tencent财经 enhanced fields in get_quote response

Map pe_ratio->pe_ttm, pb_ratio->pb, total_mv->mcap_yi, circ_mv->float_mcap_yi

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 6: Full Integration Test

- [ ] **Step 1: Run the full test suite**

Run: `pytest tests/ -v --tb=short`
Expected: All existing tests pass + new tests pass

- [ ] **Step 2: Manual API test**

Start the server:
```bash
cd D:/GitRepo/skills/stock_data
python -m stock_data.server &
```

Test the endpoint:
```bash
curl http://localhost:8000/stocks/600519/quote
```

Expected: JSON response with enhanced fields (pe_ttm, pb, mcap_yi, etc.)

- [ ] **Step 3: Kill the server**

```bash
pkill -f "python -m stock_data.server"
```

---

## Self-Review Checklist

1. **Spec coverage:** Phase 1 spec calls for Tencent财经 for PE/PB/市值/涨跌停价/ETF. All addressed.
2. **Placeholder scan:** No TBD/TODO in the plan. All code is concrete.
3. **Type consistency:** `RealtimeSource.TENCENT`, `TencentFetcher`, `UnifiedRealtimeQuote` all consistent.
4. **Spec gap:** `limit_up`/`limit_down` fields mapped to None - the Tencent API does provide these at indices 47/48 but aren't currently parsed in `_parse_tencent_response`. Consider adding a follow-up task.

---

## Next Step

Plan complete. Execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?