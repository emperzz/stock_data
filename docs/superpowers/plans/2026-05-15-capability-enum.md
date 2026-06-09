# Capability Enum Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the two-capability (`supports_historical` / `supports_realtime`) system with a `DataCapability` Flag enum that unifies routing for all data types: historical DWM K-line, minute K-line, realtime quotes, stock list, stock name, and trade calendar.

**Architecture:** Add a `DataCapability` Flag enum to `base.py`. Each fetcher replaces `supports_historical`/`supports_realtime` with `supported_data_types: DataCapability`. The Manager gains `_filter_by_capability()`. Calendar is brought into the Manager's failover system via a `get_trade_calendar()` method on fetchers.

**Tech Stack:** Python `enum.Flag`, existing SQLite cache modules.

---

## File Inventory

| File | Change |
|------|--------|
| `stock_data/data_provider/base.py` | Add `DataCapability` enum; add `supported_data_types` to `BaseFetcher`; add `_filter_by_capability()` to `DataFetcherManager`; add `get_trade_calendar()` stub to `BaseFetcher` |
| `stock_data/data_provider/baostock_fetcher.py` | Replace bool flags with `supported_data_types`; implement `get_trade_calendar()` |
| `stock_data/data_provider/akshare_fetcher.py` | Replace bool flags with `supported_data_types`; implement `get_trade_calendar()` |
| `stock_data/data_provider/tushare_fetcher.py` | Replace bool flags with `supported_data_types`; implement `get_trade_calendar()` (returns empty, token-gated) |
| `stock_data/data_provider/yfinance_fetcher.py` | Replace bool flags with `supported_data_types`; implement `get_trade_calendar()` (returns empty, market not supported) |
| `stock_data/data_provider/zhitu_fetcher.py` | Replace bool flags with `supported_data_types`; `get_trade_calendar()` returns None |
| `stock_data/data_provider/__init__.py` | Re-export `DataCapability` |
| `stock_data/data_provider/trade_calendar_cache.py` | No structural change; expose `get_cached_calendar()`, `update_cached_calendar()` as before |
| `stock_data/api/routes.py` | `list_stocks` uses `_filter_by_capability` instead of raw fetcher loop; `get_trade_calendar` delegates to manager |

---

## Task 1: Add `DataCapability` enum and update `BaseFetcher` in `base.py`

**Files:** Modify: `stock_data/data_provider/base.py:1-160`

- [ ] **Step 1: Add `DataCapability` Flag enum after the imports section (before `BaseFetcher` class)**

```python
from enum import Flag, auto


class DataCapability(Flag):
    """Flag enum for fetcher data capabilities."""

    HISTORICAL_DWM = auto()   # 日/周/月 K线 (d/w/m)
    HISTORICAL_MIN = auto()   # 分钟 K线 (1/5/15/30/60m)
    REALTIME_QUOTE = auto()   # 实时报价
    STOCK_LIST = auto()       # 股票列表 (get_all_stocks)
    STOCK_NAME = auto()       # 股票名称 (get_stock_name)
    TRADE_CALENDAR = auto()   # 交易日历
```

- [ ] **Step 2: In `BaseFetcher` class, replace the two bool attributes with one Flag set**

Replace (around line 165):
```python
    supports_historical: bool = True
    supports_realtime: bool = False
```

With:
```python
    supported_data_types: DataCapability = DataCapability(0)  # empty by default
```

- [ ] **Step 3: Add `get_trade_calendar()` stub to `BaseFetcher` (after `get_all_stocks`)**

```python
    def get_trade_calendar(self) -> list[str] | None:
        """Get trade calendar dates. Override in subclass if supported.

        Returns:
            List of trade dates as YYYY-MM-DD strings, sorted ascending,
            or None if not supported by this fetcher.
        """
        return None
```

- [ ] **Step 4: Run existing tests to verify nothing broke**

Run: `pytest tests/test_base_unit.py -v`
Expected: PASS (no changes to behavior yet)

---

## Task 2: Add `_filter_by_capability()` to `DataFetcherManager`

**Files:** Modify: `stock_data/data_provider/base.py:370-604`

- [ ] **Step 1: Replace `_filter_by_market()` with `_filter_by_capability()`**

Delete the entire `_filter_by_market` method (lines ~412-431) and replace with:

```python
    def _filter_by_capability(
        self, market: str, capability: DataCapability, for_historical: bool | None = None
    ) -> list[BaseFetcher]:
        """Filter fetchers by market support and data capability.

        Args:
            market: Market tag (csi/hk/us)
            capability: Required DataCapability flag
            for_historical: Deprecated, unused. Kept for backward compat during transition.

        Returns:
            Filtered list of fetchers sorted by priority.
        """
        result = []
        for f in self._fetchers:
            if market not in f.supported_markets:
                continue
            if capability not in f.supported_data_types:
                continue
            result.append(f)
        return result
```

- [ ] **Step 2: Update `get_kline_data` to use `_filter_by_capability(market, DataCapability.HISTORICAL_DWM)`**

In `get_kline_data` (around line 463-469), replace:
```python
        fetchers = self._filter_by_market(market, for_historical=True)
```

With:
```python
        fetchers = self._filter_by_capability(market, DataCapability.HISTORICAL_DWM)
```

For minute-level frequencies (5/15/30/60), use `DataCapability.HISTORICAL_MIN` instead. Add a helper at the top of the method:

```python
        # Determine capability based on frequency
        if frequency in ("5", "15", "30", "60"):
            cap = DataCapability.HISTORICAL_MIN
        else:
            cap = DataCapability.HISTORICAL_DWM
```

Then use `cap` in the filter call.

- [ ] **Step 3: Update `get_realtime_quote` to use `_filter_by_capability(market, DataCapability.REALTIME_QUOTE)`**

Replace:
```python
        fetchers = self._filter_by_market(market, for_historical=False)
```
With:
```python
        fetchers = self._filter_by_capability(market, DataCapability.REALTIME_QUOTE)
```

- [ ] **Step 4: Update `get_intraday_data` to use `_filter_by_capability(market, DataCapability.HISTORICAL_MIN)`**

Replace (around line 576):
```python
        fetchers = self._filter_by_market(market, for_historical=False)
```
With:
```python
        fetchers = self._filter_by_capability(market, DataCapability.HISTORICAL_MIN)
```

- [ ] **Step 5: Add `get_trade_calendar` method to `DataFetcherManager`**

After `get_intraday_data` (before `available_fetchers` property):

```python
    def get_trade_calendar(self) -> list[str]:
        """Get A-share trade calendar with automatic failover.

        Tries each fetcher's get_trade_calendar() in priority order.
        Akshare is primary; Baostock is fallback.

        Returns:
            List of trade dates as YYYY-MM-DD strings, sorted ascending.

        Raises:
            DataFetchError: When all fetchers fail.
        """
        from .trade_calendar_cache import get_cached_calendar, update_cached_calendar

        fetchers = self._filter_by_capability("csi", DataCapability.TRADE_CALENDAR)

        errors = []
        for fetcher in fetchers:
            try:
                dates = fetcher.get_trade_calendar()
                if dates:
                    update_cached_calendar(dates)
                    logger.info(f"[Manager] {fetcher.name} returned {len(dates)} calendar dates")
                    return sorted(dates)
            except Exception as e:
                errors.append(f"[{fetcher.name}] {e}")
                logger.warning(f"[Manager] {fetcher.name} calendar failed: {e}")
                continue

        # Fallback: return cached data if upstream fails
        cached = get_cached_calendar()
        if cached:
            logger.warning(f"[Manager] All fetchers failed calendar, using {len(cached)} cached dates")
            return cached

        raise DataFetchError(f"All fetchers failed for trade calendar:\n" + "\n".join(errors))
```

- [ ] **Step 6: Update `get_stock_name` to filter by `DataCapability.STOCK_NAME`**

Replace the unconditional fetcher loop with:
```python
        fetchers = self._filter_by_capability(market, DataCapability.STOCK_NAME)
        for fetcher in fetchers:
            ...
```

And the cache population fallback loop:
```python
        fetchers = self._filter_by_capability(market, DataCapability.STOCK_LIST)
        for fetcher in fetchers:
            ...
```

- [ ] **Step 7: Run tests**

Run: `pytest tests/test_base_unit.py tests/test_providers.py -v`
Expected: PASS (behavior unchanged, just capability routing)

---

## Task 3: Update each fetcher's capability declarations

**Files:** Modify each fetcher file, replacing the two bool flags with `supported_data_types`.

### BaostockFetcher

**Files:** Modify: `stock_data/data_provider/baostock_fetcher.py`

- [ ] **Step 1: Replace bool flags and add import**

In `BaostockFetcher` class (after `supported_markets`):

Replace:
```python
    supports_historical = True
    supports_realtime = False
```

With:
```python
    supported_data_types = DataCapability.HISTORICAL_DWM | DataCapability.HISTORICAL_MIN | DataCapability.TRADE_CALENDAR
```

Add import at top of file (after existing imports):
```python
from .base import DataCapability
```

- [ ] **Step 2: Add `get_trade_calendar()` method to BaostockFetcher**

After the last existing method in the class:

```python
    def get_trade_calendar(self) -> list[str] | None:
        """Get A-share trade calendar from Baostock."""
        import baostock as bs

        try:
            rs = bs.query_trade_dates()
            dates = []
            while rs.error_code == "0" and rs.next():
                row = rs.get_row_data()
                if row[1] == "1":  # is_trading_day == "1"
                    dates.append(row[0])
            if dates:
                return sorted(dates)
        except Exception as e:
            logger.warning(f"[BaostockFetcher] get_trade_calendar failed: {e}")
        return None
```

---

### AkshareFetcher

**Files:** Modify: `stock_data/data_provider/akshare_fetcher.py`

- [ ] **Step 1: Replace bool flags and add import**

Replace:
```python
    supports_historical = True
    supports_realtime = True
```

With:
```python
    supported_data_types = (
        DataCapability.HISTORICAL_DWM
        | DataCapability.REALTIME_QUOTE
        | DataCapability.STOCK_LIST
        | DataCapability.STOCK_NAME
        | DataCapability.TRADE_CALENDAR
    )
```

Note: Akshare does NOT support `HISTORICAL_MIN` (intraday).

Add import at top:
```python
from .base import DataCapability
```

- [ ] **Step 2: Add `get_trade_calendar()` method**

```python
    def get_trade_calendar(self) -> list[str] | None:
        """Get A-share trade calendar from Akshare."""
        try:
            import akshare as ak

            df = ak.tool_trade_date_hist_sina()
            dates = df["trade_date"].astype(str).tolist()
            if dates:
                return sorted(dates)
        except Exception as e:
            logger.warning(f"[AkshareFetcher] get_trade_calendar failed: {e}")
        return None
```

---

### TushareFetcher

**Files:** Modify: `stock_data/data_provider/tushare_fetcher.py`

- [ ] **Step 1: Replace bool flags and add import**

Replace:
```python
    supports_historical = True
    supports_realtime = True
```

With:
```python
    supported_data_types = DataCapability.HISTORICAL_DWM | DataCapability.REALTIME_QUOTE | DataCapability.STOCK_LIST | DataCapability.STOCK_NAME
```

(No TRADE_CALENDAR — Tushare does not expose a trade calendar API)

Add import:
```python
from .base import DataCapability
```

---

### YfinanceFetcher

**Files:** Modify: `stock_data/data_provider/yfinance_fetcher.py`

- [ ] **Step 1: Replace bool flags and add import**

Replace:
```python
    supports_historical = True
    supports_realtime = True
```

With:
```python
    supported_data_types = (
        DataCapability.HISTORICAL_DWM
        | DataCapability.HISTORICAL_MIN
        | DataCapability.REALTIME_QUOTE
    )
```

Note: Yfinance does NOT support STOCK_LIST, STOCK_NAME, or TRADE_CALENDAR for the markets it covers.

Add import:
```python
from .base import DataCapability
```

---

### ZhituFetcher

**Files:** Modify: `stock_data/data_provider/zhitu_fetcher.py`

- [ ] **Step 1: Replace bool flags and add import**

Replace:
```python
    supports_historical = False
    supports_realtime = True
```

With:
```python
    supported_data_types = DataCapability.REALTIME_QUOTE
```

(Only realtime quotes; no historical, no stock list, no calendar)

Add import:
```python
from .base import DataCapability
```

---

## Task 4: Update `__init__.py` exports

**Files:** Modify: `stock_data/data_provider/__init__.py`

- [ ] **Step 1: Add `DataCapability` to imports and `__all__`**

Replace:
```python
from .base import STANDARD_COLUMNS, BaseFetcher, DataFetcherManager, DataFetchError, RateLimitError
```

With:
```python
from .base import (
    STANDARD_COLUMNS,
    BaseFetcher,
    DataCapability,
    DataFetcherManager,
    DataFetchError,
    RateLimitError,
)
```

Replace `__all__`:
```python
__all__ = [
    "BaseFetcher",
    "DataCapability",
    "DataFetcherManager",
    "DataFetchError",
    "RateLimitError",
    "STANDARD_COLUMNS",
    "UnifiedRealtimeQuote",
    "CircuitBreaker",
    "RealtimeSource",
]
```

---

## Task 5: Update routes.py

**Files:** Modify: `stock_data/api/routes.py`

- [ ] **Step 1: Update `list_stocks` to use manager's `_filter_by_capability`**

In `list_stocks` function (around line 430), replace:
```python
    result = []
    for fetcher in manager.fetchers:
        try:
            stocks = fetcher.get_all_stocks(market)
            if stocks:
                result = stocks
                break
        except Exception as e:
            logger.warning(f"[list_stocks] {fetcher.name} failed: {e}")
            continue
```

With:
```python
    from ..data_provider.base import DataCapability

    result = []
    fetchers = manager._filter_by_capability(market, DataCapability.STOCK_LIST)
    for fetcher in fetchers:
        try:
            stocks = fetcher.get_all_stocks(market)
            if stocks:
                result = stocks
                break
        except Exception as e:
            logger.warning(f"[list_stocks] {fetcher.name} failed: {e}")
            continue
```

- [ ] **Step 2: Update `get_trade_calendar` to use manager**

Replace the entire calendar-fetching block inside `get_trade_calendar` (lines 490-525) — the akshare-hardcoded logic — with a call to the manager:

```python
    if should_refresh:
        logger.info(f"[calendar] Fetching fresh data from upstream, refresh={refresh}")
        try:
            manager = get_manager()
            dates = manager.get_trade_calendar()
            if dates:
                logger.info(f"[calendar] Updated {len(dates)} dates from manager")
        except Exception as e:
            logger.error(f"[calendar] Manager calendar failed: {e}")
            cached_dates = get_cached_calendar()
            if not cached_dates:
                raise HTTPException(
                    status_code=500,
                    detail={"error": "fetch_failed", "message": str(e)},
                ) from e
            # Fall through to use cached data
```

The route still uses `get_cached_calendar()` and `get_latest_cached_trade_date()` for the final response — the manager call only refreshes the cache.

---

## Task 6: Final integration test

- [ ] **Step 1: Run full test suite**

Run: `pytest tests/ -v --tb=short`
Expected: All tests pass.

- [ ] **Step 2: Smoke test the API**

Run: `python -m stock_data.server &` (or use uvicorn directly), then:
```bash
curl "http://localhost:8000/calendar"
curl "http://localhost:8000/stocks?market=csi&limit=3"
curl "http://localhost:8000/stocks/600519/history?days=5"
```
Expected: All return valid JSON.

---

## Self-Review Checklist

- [ ] `DataCapability` enum covers all 6 data types
- [ ] Each fetcher declares `supported_data_types` with correct flags
- [ ] `_filter_by_capability` replaces `_filter_by_market` in all 4 manager methods
- [ ] Minute frequency (`5/15/30/60`) routes to `HISTORICAL_MIN`; daily/weekly/monthly routes to `HISTORICAL_DWM`
- [ ] `get_trade_calendar` is no longer hardcoded to akshare in routes.py
- [ ] `list_stocks` uses `_filter_by_capability` instead of raw fetcher loop
- [ ] `BaseFetcher` has `get_trade_calendar()` stub returning `None`
- [ ] No remaining references to `supports_historical` or `supports_realtime` in fetchers or base.py
- [ ] All existing tests pass
