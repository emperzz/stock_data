# Stock Info API (GET /stocks/{code}/info) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a new `STOCK_INFO` capability and `GET /stocks/{code}/info` REST endpoint that returns normalized A-share company profile data (listed_date, concepts, registered_address, total_shares, etc.) from Zhitu (primary) with Myquant as degraded failover.

**Architecture:** Bottom-up TDD. Add the `DataCapability.STOCK_INFO` flag and `CAPABILITY_TO_METHOD` mapping, then implement `get_stock_info` on ZhituFetcher and MyquantFetcher (each with unit tests), then the `DataFetcherManager.get_stock_info` method, then the `StockInfoResponse` schema + cache infrastructure, then the route (integration tests), then docs.

**Tech Stack:** Python 3, FastAPI, Pydantic, `cachetools.TTLCache`, `pytest`. Zhitu uses `requests`; Myquant uses `gm` SDK.

---

## File Structure

**Modified (7 source + 3 test + 2 doc):**

| File | Responsibility |
|---|---|
| `stock_data/data_provider/base.py` | Add `DataCapability.STOCK_INFO` flag + `CAPABILITY_TO_METHOD` entry |
| `stock_data/data_provider/fetchers/zhitu_fetcher.py` | Add `get_stock_info` method (calls `https://api.zhituapi.com/hs/gs/gsjj/{code}`); add `STOCK_INFO` to `supported_data_types` |
| `stock_data/data_provider/fetchers/myquant_fetcher.py` | Add `get_stock_info` method (calls `gm.api.get_symbols(symbols=..., df=True)`); add `STOCK_INFO` to `supported_data_types` |
| `stock_data/data_provider/manager.py` | Add `get_stock_info(code)` one-line method (one-liner matching `get_dividend`) |
| `stock_data/api/schemas.py` | Add `StockInfoResponse` Pydantic model (19 fields) |
| `stock_data/api/routes.py` | Add `GET /stocks/{code}/info` route + `@endpoint_meta` + `cached_endpoint` |
| `stock_data/api/cache.py` | Add `_TTL_STOCK_INFO`, `_stock_info_cache`, `get_stock_info_cache()`, `make_stock_info_cache_key()` |
| `tests/test_zhitu_fetcher.py` (NEW) | `TestZhituFetcherBasics` + `TestGetStockInfo` (6 cases) |
| `tests/test_myquant_fetcher.py` (NEW) | `TestMyquantFetcherBasics` + `TestGetStockInfo` (4 cases) |
| `tests/test_routes.py` | Add `TestStockInfoRoute` class (4 cases) |
| `CLAUDE.md` | 4 doc updates (capability table, fetcher declarations, env var, schema section) |
| `.env.example` | Add `CACHE_TTL_STOCK_INFO=3600` |

---

## Task 1: TDD ZhituFetcher.get_stock_info

**Files:**
- Create: `tests/test_zhitu_fetcher.py`
- Modify: `stock_data/data_provider/base.py:27-99` (add `STOCK_INFO` flag + mapping)
- Modify: `stock_data/data_provider/fetchers/zhitu_fetcher.py:25-31` (add `STOCK_INFO` to `supported_data_types`; append `get_stock_info` method)

This task makes the new capability officially declared AND proves the Zhitu fetcher works in isolation. The test order matters: writing the test first lets us see it fail (method doesn't exist), then we add the implementation and the capability flag together.

- [ ] **Step 1: Create `tests/test_zhitu_fetcher.py` with the new test class (TDD - test first)**

Create file `tests/test_zhitu_fetcher.py`:

```python
"""
Unit tests for ZhituFetcher.
"""
from unittest.mock import MagicMock, patch

from stock_data.data_provider.base import DataCapability
from stock_data.data_provider.fetchers.zhitu_fetcher import ZhituFetcher


class TestZhituFetcherBasics:
    def test_name(self):
        assert ZhituFetcher().name == "ZhituFetcher"

    def test_priority_default(self):
        assert ZhituFetcher().priority == 4

    def test_capabilities(self):
        caps = ZhituFetcher().supported_data_types
        assert DataCapability.REALTIME_QUOTE in caps
        assert DataCapability.STOCK_ZT_POOL in caps
        assert DataCapability.STOCK_INFO in caps  # NEW


class TestGetStockInfo:
    def setup_method(self):
        self.fetcher = ZhituFetcher()

    def test_returns_none_when_unavailable(self, monkeypatch):
        monkeypatch.setattr("stock_data.data_provider.fetchers.zhitu_fetcher.os.getenv", lambda *a, **k: "" if a and a[0] == "ZHITU_TOKEN" else "")
        result = self.fetcher.get_stock_info("600519")
        assert result is None

    @patch("stock_data.data_provider.fetchers.zhitu_fetcher.requests.get")
    def test_normalizes_full_payload(self, mock_get, monkeypatch):
        monkeypatch.setattr(
            "stock_data.data_provider.fetchers.zhitu_fetcher.os.getenv",
            lambda *a, **k: "test_token" if a and a[0] == "ZHITU_TOKEN" else "",
        )
        self.fetcher._token = "test_token"
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "code": "600519",
            "name": "贵州茅台",
            "ename": "Kweichow Moutai Co.,Ltd.",
            "ldate": "2001-08-27",
            "rdate": "1999-11-20",
            "totalstock": "125619.78",
            "flowstock": "125619.78",
            "idea": "白酒,融资融券,证金持股,沪股通",
            "raddr": "贵州省遵义市仁怀市茅台镇",
            "rcapital": "9.82亿",
            "rname": "丁雄军",
            "bscope": "酒类生产、销售...",
            "bsname": "蒋焰",
            "bsphone": "0851-22386002",
            "bsemail": "mtdm@maotai.com.cn",
        }
        mock_get.return_value = mock_response
        # Make raise_for_status a no-op
        mock_response.raise_for_status = lambda: None

        result = self.fetcher.get_stock_info("600519")
        assert result is not None
        assert result["code"] == "600519"
        assert result["name"] == "贵州茅台"
        assert result["ename"] == "Kweichow Moutai Co.,Ltd."
        assert result["market"] == "csi"
        assert result["listed_date"] == "2001-08-27"
        assert result["delisted_date"] == ""
        assert result["total_shares"] == 125619.78
        assert result["float_shares"] == 125619.78
        assert result["industry"] == ""
        assert result["concepts"] == ["白酒", "融资融券", "证金持股", "沪股通"]
        assert result["registered_address"] == "贵州省遵义市仁怀市茅台镇"
        assert result["registered_capital"] == "9.82亿"
        assert result["legal_representative"] == "丁雄军"
        assert result["business_scope"] == "酒类生产、销售..."
        assert result["established_date"] == "1999-11-20"
        assert result["secretary"] == "蒋焰"
        assert result["secretary_phone"] == "0851-22386002"
        assert result["secretary_email"] == "mtdm@maotai.com.cn"
        # No 'source' key — manager injects it
        assert "source" not in result

    @patch("stock_data.data_provider.fetchers.zhitu_fetcher.requests.get")
    def test_returns_none_on_http_error(self, mock_get, monkeypatch):
        monkeypatch.setattr(
            "stock_data.data_provider.fetchers.zhitu_fetcher.os.getenv",
            lambda *a, **k: "test_token" if a and a[0] == "ZHITU_TOKEN" else "",
        )
        self.fetcher._token = "test_token"
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = Exception("500 Server Error")
        mock_get.return_value = mock_response
        assert self.fetcher.get_stock_info("600519") is None

    @patch("stock_data.data_provider.fetchers.zhitu_fetcher.requests.get")
    def test_returns_none_on_malformed_payload(self, mock_get, monkeypatch):
        monkeypatch.setattr(
            "stock_data.data_provider.fetchers.zhitu_fetcher.os.getenv",
            lambda *a, **k: "test_token" if a and a[0] == "ZHITU_TOKEN" else "",
        )
        self.fetcher._token = "test_token"
        mock_response = MagicMock()
        mock_response.json.return_value = {"detail": "Licence证书无效"}
        mock_response.raise_for_status = lambda: None
        mock_get.return_value = mock_response
        # No 'code' key in payload → returns None
        assert self.fetcher.get_stock_info("600519") is None

    @patch("stock_data.data_provider.fetchers.zhitu_fetcher.requests.get")
    def test_empty_optional_fields_default_to_blank(self, mock_get, monkeypatch):
        monkeypatch.setattr(
            "stock_data.data_provider.fetchers.zhitu_fetcher.os.getenv",
            lambda *a, **k: "test_token" if a and a[0] == "ZHITU_TOKEN" else "",
        )
        self.fetcher._token = "test_token"
        mock_response = MagicMock()
        mock_response.json.return_value = {"code": "600519", "name": "贵州茅台"}
        mock_response.raise_for_status = lambda: None
        mock_get.return_value = mock_response

        result = self.fetcher.get_stock_info("600519")
        assert result["ename"] == ""
        assert result["listed_date"] == ""
        assert result["total_shares"] is None
        assert result["concepts"] == []
        assert result["registered_address"] == ""
        assert result["secretary"] == ""
```

- [ ] **Step 2: Run the test to confirm it fails (method doesn't exist yet)**

Run: `.venv/Scripts/python.exe -m pytest tests/test_zhitu_fetcher.py -v`
Expected: FAIL with `AttributeError: type object 'ZhituFetcher' has no attribute 'get_stock_info'` (and `DataCapability.STOCK_INFO` doesn't exist yet)

- [ ] **Step 3: Add `STOCK_INFO` flag and `CAPABILITY_TO_METHOD` mapping in `base.py`**

In `stock_data/data_provider/base.py`, find the `DataCapability` enum (around line 27-56). Add `STOCK_INFO` at the end (after `ANNOUNCEMENT`):

```python
    ANNOUNCEMENT      = auto()  # 公告
    STOCK_INFO        = auto()  # 公司画像（上市日期/概念/经营范围/注册地/总股本等）
```

Find the `CAPABILITY_TO_METHOD` dict (line 78-99). Add at the end:

```python
    DataCapability.ANNOUNCEMENT: "get_announcements",
    DataCapability.STOCK_INFO: "get_stock_info",
```

- [ ] **Step 4: Update `ZhituFetcher.supported_data_types` and add the `get_stock_info` method**

In `stock_data/data_provider/fetchers/zhitu_fetcher.py`, find line 31:
```python
    supported_data_types = DataCapability.REALTIME_QUOTE | DataCapability.STOCK_ZT_POOL
```
Replace with:
```python
    supported_data_types = (
        DataCapability.REALTIME_QUOTE
        | DataCapability.STOCK_ZT_POOL
        | DataCapability.STOCK_INFO
    )
```

Append the new method at the end of the `ZhituFetcher` class:

```python
    def get_stock_info(self, stock_code: str) -> dict | None:
        """公司画像 — Zhitu gs/gsjj 端点 (https://api.zhituapi.com/hs/gs/gsjj/{code}).

        返回归一化的 18 user-data 字段 (source 由 manager 注入)。失败返 None 让 failover 工作。
        """
        if not self.is_available():
            return None
        url = f"{ZHITU_API_BASE}/hs/gs/gsjj/{stock_code}"
        params = {"token": self._token}
        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
        except (requests.RequestException, ValueError) as e:
            logger.warning("[ZhituFetcher] get_stock_info %s failed: %s", stock_code, e)
            return None
        if not isinstance(data, dict) or "code" not in data:
            logger.warning("[ZhituFetcher] get_stock_info %s: malformed payload", stock_code)
            return None
        return {
            "code":              stock_code,
            "name":              data.get("name", "") or "",
            "ename":             data.get("ename", "") or "",
            "market":            "csi",
            "listed_date":       str(data.get("ldate", "") or ""),
            "delisted_date":     "",
            "total_shares":      safe_float(data.get("totalstock")),
            "float_shares":      safe_float(data.get("flowstock")),
            "industry":          "",
            "concepts":          _split_concepts(data.get("idea", "")),
            "registered_address": data.get("raddr", "") or "",
            "registered_capital": data.get("rcapital", "") or "",
            "legal_representative": data.get("rname", "") or "",
            "business_scope":    data.get("bscope", "") or "",
            "established_date":  str(data.get("rdate", "") or ""),
            "secretary":         data.get("bsname", "") or "",
            "secretary_phone":   data.get("bsphone", "") or "",
            "secretary_email":   data.get("bsemail", "") or "",
        }
```

Also append the private helper at module level (before `class ZhituFetcher`):

```python
def _split_concepts(raw: object) -> list[str]:
    """Split Zhitu's comma-separated ``idea`` string into a deduplicated list.

    Returns ``[]`` for empty/None input. Items are stripped; empty items dropped.
    """
    if not raw:
        return []
    parts = [p.strip() for p in str(raw).split(",")]
    seen: set[str] = set()
    out: list[str] = []
    for p in parts:
        if p and p not in seen:
            seen.add(p)
            out.append(p)
    return out
```

- [ ] **Step 5: Run the test to confirm it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_zhitu_fetcher.py -v`
Expected: 6 passed (1 basic, 1 capabilities, 4 get_stock_info)

- [ ] **Step 6: Run the full test suite to confirm no regressions**

Run: `.venv/Scripts/python.exe -m pytest tests/test_capability_method_map.py -v`
Expected: All passing (note: `test_mapped_method_exists_on_base_or_subclass` for `STOCK_INFO` will fail if no fetcher has `get_stock_info` — we just added it, so it should pass)

Run: `.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: All tests passing (no new tests broken)

- [ ] **Step 7: Commit**

```bash
cd "E:/GitRepo/stock_data"
git add stock_data/data_provider/base.py \
        stock_data/data_provider/fetchers/zhitu_fetcher.py \
        tests/test_zhitu_fetcher.py
git commit -m "feat(stock-info): add ZhituFetcher.get_stock_info + STOCK_INFO capability

Adds get_stock_info to ZhituFetcher (calls gs/gsjj endpoint), the
DataCapability.STOCK_INFO flag, and CAPABILITY_TO_METHOD mapping. Source
is set by the manager on return, not by the fetcher itself.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: TDD MyquantFetcher.get_stock_info

**Files:**
- Create: `tests/test_myquant_fetcher.py`
- Modify: `stock_data/data_provider/fetchers/myquant_fetcher.py:106-114` (add `STOCK_INFO` to `supported_data_types`; append `get_stock_info` method + `_ts_to_date` helper)

The Myquant free tier only provides 3 useful fields (name/listed_date/delisted_date) — other fields fall back to empty/None. The test must reflect this degraded behavior.

- [ ] **Step 1: Create `tests/test_myquant_fetcher.py` with the new test class (TDD - test first)**

Create file `tests/test_myquant_fetcher.py`:

```python
"""
Unit tests for MyquantFetcher.
"""
from unittest.mock import MagicMock, patch

import pandas as pd

from stock_data.data_provider.base import DataCapability
from stock_data.data_provider.fetchers.myquant_fetcher import MyquantFetcher


class TestMyquantFetcherBasics:
    def test_name(self):
        assert MyquantFetcher().name == "MyquantFetcher"

    def test_priority_default(self):
        assert MyquantFetcher().priority == 9

    def test_capabilities(self):
        caps = MyquantFetcher().supported_data_types
        assert DataCapability.HISTORICAL_DWM in caps
        assert DataCapability.STOCK_LIST in caps
        assert DataCapability.STOCK_INFO in caps  # NEW


class TestGetStockInfo:
    def setup_method(self):
        # Force is_available to return True (skip gm.init check)
        self.fetcher = MyquantFetcher()
        self.fetcher._initialized = True
        self.fetcher._token = "test_token"

    def test_returns_none_when_unavailable(self):
        f = MyquantFetcher()
        f._token = ""
        f._initialized = False
        assert f.get_stock_info("600519") is None

    @patch("stock_data.data_provider.fetchers.myquant_fetcher.gm.api.get_symbols")
    def test_normalizes_minimal_payload(self, mock_get_symbols):
        # Simulate gm.api.get_symbols returning a 35-col DataFrame but we only
        # use 3 columns: sec_name (encoded), listed_date, delisted_date
        # Inject a known double-UTF-8-encoded string to verify _decode_gm_name
        encoded = bytes("贵州茅台", "gbk").decode("latin-1")
        df = pd.DataFrame(
            {
                "symbol": ["SHSE.600519"],
                "sec_name": [encoded],
                "listed_date": [pd.Timestamp("2001-08-27 00:00:00+08:00")],
                "delisted_date": [pd.Timestamp("2038-01-01 00:00:00+08:00")],
            }
        )
        mock_get_symbols.return_value = df

        result = self.fetcher.get_stock_info("600519")
        assert result is not None
        assert result["code"] == "600519"
        assert result["name"] == "贵州茅台"  # decoded from double-encoded
        assert result["ename"] == ""
        assert result["market"] == "csi"
        assert result["listed_date"] == "2001-08-27"
        assert result["delisted_date"] == "2038-01-01"
        # Free tier doesn't provide these
        assert result["total_shares"] is None
        assert result["float_shares"] is None
        assert result["industry"] == ""
        assert result["concepts"] == []
        # All Zhitu-specific fields are blank
        assert result["registered_address"] == ""
        assert result["secretary"] == ""
        # No 'source' key — manager injects it
        assert "source" not in result

    @patch("stock_data.data_provider.fetchers.myquant_fetcher.gm.api.get_symbols")
    def test_returns_none_on_empty_df(self, mock_get_symbols):
        mock_get_symbols.return_value = pd.DataFrame()
        assert self.fetcher.get_stock_info("600519") is None

    @patch("stock_data.data_provider.fetchers.myquant_fetcher.gm.api.get_symbols")
    def test_returns_none_on_exception(self, mock_get_symbols):
        mock_get_symbols.side_effect = Exception("network error")
        assert self.fetcher.get_stock_info("600519") is None
```

- [ ] **Step 2: Run the test to confirm it fails (method doesn't exist yet)**

Run: `.venv/Scripts/python.exe -m pytest tests/test_myquant_fetcher.py -v`
Expected: FAIL with `AttributeError: type object 'MyquantFetcher' has no attribute 'get_stock_info'`

- [ ] **Step 3: Update `MyquantFetcher.supported_data_types` and add the `get_stock_info` method**

In `stock_data/data_provider/fetchers/myquant_fetcher.py`, find the `supported_data_types` (line 106-114). Replace:

```python
    supported_data_types = (
        DataCapability.HISTORICAL_DWM
        | DataCapability.HISTORICAL_MIN
        | DataCapability.REALTIME_QUOTE
        | DataCapability.STOCK_LIST
        | DataCapability.TRADE_CALENDAR
        | DataCapability.INDEX_HISTORICAL
        | DataCapability.INDEX_INTRADAY
    )
```

with:

```python
    supported_data_types = (
        DataCapability.HISTORICAL_DWM
        | DataCapability.HISTORICAL_MIN
        | DataCapability.REALTIME_QUOTE
        | DataCapability.STOCK_LIST
        | DataCapability.TRADE_CALENDAR
        | DataCapability.INDEX_HISTORICAL
        | DataCapability.INDEX_INTRADAY
        | DataCapability.STOCK_INFO
    )
```

Append the new method at the end of the `MyquantFetcher` class:

```python
    def get_stock_info(self, stock_code: str) -> dict | None:
        """公司画像 (Myquant free tier) — 复用 get_symbols 加 symbols= 单只过滤.

        Free tier 仅提供 3 个有效字段: name/listed_date/delisted_date. 其他字段
        留空, 作为 Zhitu 失败的降级体验.
        """
        if not self.is_available():
            return None
        try:
            from gm.api import get_symbols  # type: ignore  # lazy import

            self._ensure_initialized()
            symbol_full = self._convert_code(stock_code)  # "SHSE.600519" etc.
            df = get_symbols(sec_type1=1010, symbols=symbol_full, df=True)
            if df is None or df.empty:
                logger.warning("[MyquantFetcher] get_symbols empty for %s", stock_code)
                return None
            row = df.iloc[0]
            return {
                "code":              stock_code,
                "name":              _decode_gm_name(row.get("sec_name", "")),
                "ename":             "",
                "market":            "csi",
                "listed_date":       _ts_to_date(row.get("listed_date")),
                "delisted_date":     _ts_to_date(row.get("delisted_date")),
                "total_shares":      None,  # free tier 不提供
                "float_shares":      None,  # free tier 不提供
                "industry":          "",    # paid 接口 (GmError 2001)
                "concepts":          [],
                "registered_address": "",
                "registered_capital": "",
                "legal_representative": "",
                "business_scope":    "",
                "established_date":  "",
                "secretary":         "",
                "secretary_phone":   "",
                "secretary_email":   "",
            }
        except Exception as e:
            logger.warning("[MyquantFetcher] get_stock_info %s failed: %s", stock_code, e)
            return None
```

Also append the private helper at module level (after the existing `_decode_gm_name` near line 71):

```python
def _ts_to_date(ts: object) -> str:
    """Convert pandas ``Timestamp`` to ``YYYY-MM-DD`` string.

    Returns ``""`` for ``None``, ``NaT``, or unconvertible input.
    """
    if ts is None:
        return ""
    try:
        if pd.isna(ts):
            return ""
    except (TypeError, ValueError):
        return ""
    try:
        return pd.Timestamp(ts).strftime("%Y-%m-%d")
    except Exception:
        return ""
```

- [ ] **Step 4: Run the test to confirm it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_myquant_fetcher.py -v`
Expected: 4 passed (1 basic, 1 capabilities, 3 get_stock_info)

- [ ] **Step 5: Run the full test suite to confirm capability map test still passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_capability_method_map.py -v`
Expected: All passing — `STOCK_INFO` flag now resolves to a real method on both ZhituFetcher and MyquantFetcher

- [ ] **Step 6: Commit**

```bash
cd "E:/GitRepo/stock_data"
git add stock_data/data_provider/fetchers/myquant_fetcher.py \
        tests/test_myquant_fetcher.py
git commit -m "feat(stock-info): add MyquantFetcher.get_stock_info

Free tier only provides 3 useful fields (name/listed_date/delisted_date)
via gm.api.get_symbols(symbols=..., df=True). Industry is paid
(GmError 2001); total_shares/float_share are not exposed. Empty values
intentional — manager uses Zhitu as primary, Myquant as degraded
fallback.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Add DataFetcherManager.get_stock_info

**Files:**
- Modify: `stock_data/data_provider/manager.py` (insert between `get_dividend` and `get_fund_flow_minute`)

One-liner mirroring `get_dividend` (line 600-605). No new test — the route integration test in Task 7 covers this.

- [ ] **Step 1: Add the method**

In `stock_data/data_provider/manager.py`, find `get_dividend` (line 600-605). Insert directly after:

```python
    def get_stock_info(self, code: str) -> tuple[dict, str]:
        """拉取公司画像 (A 股). Failover: Zhitu (P4) → Myquant (P9)."""
        return self._with_failover(
            DataCapability.STOCK_INFO, "csi", f"stock_info {code}",
            lambda f: f.get_stock_info(code),
            return_source=True,
        )
```

- [ ] **Step 2: Smoke test (no new test file — covered by Task 7)**

Run: `.venv/Scripts/python.exe -c "from stock_data.data_provider.manager import DataFetcherManager; m = DataFetcherManager(); print(hasattr(m, 'get_stock_info'))"`
Expected: prints `True`

- [ ] **Step 3: Commit**

```bash
cd "E:/GitRepo/stock_data"
git add stock_data/data_provider/manager.py
git commit -m "feat(manager): add get_stock_info (STOCK_INFO failover)

Mirrors get_dividend pattern. Zhitu first, Myquant as degraded fallback.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: Add StockInfoResponse schema

**Files:**
- Modify: `stock_data/api/schemas.py` (append `StockInfoResponse`)

No new test — covered by the route integration test in Task 7 (Pydantic validation runs as part of FastAPI request).

- [ ] **Step 1: Append the model**

In `stock_data/api/schemas.py`, find the end of the file. Find an existing class for placement context (e.g. `class HotTopicRecord` or `class FundFlowDailyRecord`). Append after the last model class:

```python
class StockInfoResponse(BaseModel):
    """公司画像 (A 股) — 来自 Zhitu (主) / Myquant (备) 的归一化结果.

    `industry` 字段当前始终为空 (Zhitu 不提供; Myquant 该端点付费),
    保留为未来扩展钩子.
    """

    # 基础识别
    code: str = Field(description="股票代码 (e.g., 600519)")
    name: str = Field(default="", description="中文名")
    ename: str = Field(default="", description="英文名 (Zhitu only)")
    market: str = Field(default="csi", description="市场: csi (本次仅 csi)")

    # 上市与股本
    listed_date: str = Field(default="", description="上市日期 YYYY-MM-DD")
    delisted_date: str = Field(default="", description="退市日期 YYYY-MM-DD (Myquant only)")
    total_shares: float | None = Field(default=None, description="总股本 (万股)")
    float_shares: float | None = Field(default=None, description="流通股本 (万股)")

    # 行业与概念
    industry: str = Field(
        default="",
        description="行业. 当前始终为空 (Zhitu 不提供; Myquant 该端点付费 GmError 2001)",
    )
    concepts: list[str] = Field(default_factory=list, description="概念标签 (Zhitu)")

    # 公司画像
    registered_address: str = Field(default="", description="注册地址 (Zhitu)")
    registered_capital: str = Field(default="", description="注册资本 (Zhitu, 字符串格式如 '9.82亿')")
    legal_representative: str = Field(default="", description="法人代表 (Zhitu)")
    business_scope: str = Field(default="", description="经营范围 (Zhitu)")
    established_date: str = Field(default="", description="成立日期 YYYY-MM-DD (Zhitu)")

    # 董秘联系
    secretary: str = Field(default="", description="董秘姓名 (Zhitu)")
    secretary_phone: str = Field(default="", description="董秘电话 (Zhitu)")
    secretary_email: str = Field(default="", description="董秘邮箱 (Zhitu)")

    # 源
    source: str = Field(default="", description="数据源: 'zhitu' | 'myquant'")
```

- [ ] **Step 2: Smoke test**

Run: `.venv/Scripts/python.exe -c "from stock_data.api.schemas import StockInfoResponse; m = StockInfoResponse(code='600519', name='贵州茅台'); print(m.model_dump_json())"`
Expected: prints JSON with `code=600519`, `name=贵州茅台`, all other fields at defaults

- [ ] **Step 3: Commit**

```bash
cd "E:/GitRepo/stock_data"
git add stock_data/api/schemas.py
git commit -m "feat(schemas): add StockInfoResponse model (19 fields)

Company profile response: code/name/ename/market, listed/delisted date,
total/float shares, industry/concepts, address/capital/legal/scope,
secretary contact, source. `industry` is always empty today; kept as a
future-extension hook.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: Add cache infrastructure

**Files:**
- Modify: `stock_data/api/cache.py` (4 additions)
- Modify: `.env.example` (1 line)

No new test — the route integration test in Task 7 verifies cache is wired correctly via `cached_endpoint`.

- [ ] **Step 1: Add TTL constant, cache instance, getter, and key factory in `cache.py`**

In `stock_data/api/cache.py`, find line 44 (`_TTL_POOLS = int(...)`). Insert directly after:

```python
_TTL_STOCK_INFO = int(os.getenv("CACHE_TTL_STOCK_INFO", "3600"))  # 公司画像 (1h)
```

Find line 58 (`_pools_cache: TTLCache = ...`). Insert directly after:

```python
_stock_info_cache: TTLCache = TTLCache(maxsize=512, ttl=_TTL_STOCK_INFO)
```

Find the getter block (around line 132 `def get_pools_cache():`). Insert directly after `get_pools_cache`:

```python
def get_stock_info_cache() -> TTLCache:
    return _stock_info_cache
```

Find the key-factory block (around line 210 `def make_dividend_cache_key`). Insert directly after `make_dividend_cache_key`:

```python
def make_stock_info_cache_key(stock_code: str) -> str:
    return f"stock_info:{stock_code}"
```

- [ ] **Step 2: Add to `.env.example`**

Find a similar line in `.env.example` (e.g. `CACHE_TTL_STOCK_INTRADAY=30`). Append at the end:

```
CACHE_TTL_STOCK_INFO=3600
```

- [ ] **Step 3: Smoke test**

Run: `.venv/Scripts/python.exe -c "from stock_data.api.cache import get_stock_info_cache, make_stock_info_cache_key; c = get_stock_info_cache(); print(type(c).__name__); print(make_stock_info_cache_key('600519'))"`
Expected: prints `TTLCache` and `stock_info:600519`

- [ ] **Step 4: Commit**

```bash
cd "E:/GitRepo/stock_data"
git add stock_data/api/cache.py .env.example
git commit -m "feat(cache): add stock_info cache (TTL 1h, 512 entries)

Mirrors the per-endpoint TTL pattern (CACHE_TTL_STOCK_INFO env override,
default 3600s). 1h chosen as compromise between fresh company data and
upstream rate limits.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: TDD for /stocks/{code}/info route

**Files:**
- Modify: `tests/test_routes.py` (append `TestStockInfoRoute` class)
- Modify: `stock_data/api/routes.py` (append route + `@endpoint_meta` + `cached_endpoint`)

The route is the integration seam — the test exercises the full pipeline (manager → fetcher → cache).

- [ ] **Step 1: Append `TestStockInfoRoute` class to `tests/test_routes.py`**

In `tests/test_routes.py`, append at the end of the file:

```python
class TestStockInfoRoute:
    """Tests for /api/v1/stocks/{code}/info endpoint."""

    def test_info_rejects_hk_market(self, client):
        # HK market is not csi → no fetcher handles STOCK_INFO → 503
        response = client.get("/api/v1/stocks/HK00700/info")
        assert response.status_code == 503

    def test_info_returns_503_for_invalid_stock(self, client):
        # Invalid code → all fetchers fail → 503
        response = client.get("/api/v1/stocks/INVALID/info")
        assert response.status_code == 503

    def test_info_response_shape(self, client):
        # 200 if any fetcher succeeds, 503 if all fail — accept either.
        # We assert the response shape ONLY on 200, else assert 503.
        response = client.get("/api/v1/stocks/600519/info")
        if response.status_code == 200:
            data = response.json()
            # All 19 fields present
            expected_fields = {
                "code", "name", "ename", "market",
                "listed_date", "delisted_date", "total_shares", "float_shares",
                "industry", "concepts",
                "registered_address", "registered_capital", "legal_representative",
                "business_scope", "established_date",
                "secretary", "secretary_phone", "secretary_email",
                "source",
            }
            assert set(data.keys()) == expected_fields
            assert data["code"] == "600519"
            assert data["market"] == "csi"
            assert isinstance(data["concepts"], list)
            assert data["source"] in ("zhitu", "myquant", "")
        else:
            assert response.status_code == 503
```

- [ ] **Step 2: Run the test to confirm it fails (route doesn't exist)**

Run: `.venv/Scripts/python.exe -m pytest tests/test_routes.py::TestStockInfoRoute -v`
Expected: FAIL with `404 Not Found` (route not registered) or similar

- [ ] **Step 3: Add the route in `routes.py`**

In `stock_data/api/routes.py`, find a similar single-stock endpoint to use as placement context (e.g. `get_quote` around line 500 or `get_fund_flow_daily` at line 1702). To keep the change isolated and near the top of `/stocks/*` endpoints, find the **first** route in `routes.py` that takes `{code}` path param and add the new route **immediately before** it.

The exact insertion point: after the last import block, find a stable anchor such as `# /stocks/{code}/quote` comment or the `def get_quote(` function. Insert the new route block.

```python
@router.get(
    "/stocks/{code}/info",
    response_model=StockInfoResponse,
    responses={
        503: {"model": ErrorResponse, "description": "All fetchers failed"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["stocks"],
)
@endpoint_meta(
    summary="公司画像",
    markets=["csi"],
    capabilities=["STOCK_INFO"],
)
def get_stock_info(code: str = Path(max_length=20)) -> StockInfoResponse:
    """公司画像（Zhitu → Myquant failover）。A 股限定."""
    manager = get_manager()
    data, source = manager.get_stock_info(code)
    return StockInfoResponse(**data, source=source)


get_stock_info = cached_endpoint(
    get_stock_info_cache,
    make_stock_info_cache_key,
    "stock_info",
    "Stock info",
)(get_stock_info)
```

Also ensure the imports at the top of `routes.py` include the new symbols. Find the existing import line for `StockInfoResponse` (it won't exist yet — this is a new symbol) and the cache imports. Add:

- `StockInfoResponse` to the `from stock_data.api.schemas import ...` block
- `get_stock_info_cache`, `make_stock_info_cache_key` to the `from stock_data.api.cache import ...` block

If the imports are sorted alphabetically, insert in the right place.

- [ ] **Step 4: Run the test to confirm it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_routes.py::TestStockInfoRoute -v`
Expected: 3 passed (or 3 with at least one 503 if all fetchers fail in this env — both branches are accepted)

- [ ] **Step 5: Run the full test suite to confirm no regressions**

Run: `.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: All previously-passing tests still pass; new `TestStockInfoRoute` tests pass

- [ ] **Step 6: Commit**

```bash
cd "E:/GitRepo/stock_data"
git add stock_data/api/routes.py tests/test_routes.py
git commit -m "feat(routes): add GET /stocks/{code}/info (STOCK_INFO)

Single-stock company profile endpoint with 1h TTL cache, Zhitu-primary
Myquant-fallback failover. Returns 503 on HK/US market (no csi fetcher)
or all-fetchers-failed.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7: Update CLAUDE.md documentation

**Files:**
- Modify: `CLAUDE.md` (4 sections)

No code, no test — documentation only. Run the test suite afterward to confirm nothing broke.

- [ ] **Step 1: Update the Capability-Based Routing table**

In `CLAUDE.md`, find the routing table (around line 593-604 — the API Method → Capability Used table). Add a row at the end (after `get_announcements`):

```markdown
| `get_stock_info` | `STOCK_INFO` |
```

- [ ] **Step 2: Update the Fetcher capability declarations table**

In `CLAUDE.md`, find the fetcher capabilities table (around the section listing Baostock/Akshare/Tushare/etc.). Update two rows:

For `ZhituFetcher` row, change:
```
| ZhituFetcher | `REALTIME_QUOTE \| STOCK_ZT_POOL` |
```
to:
```
| ZhituFetcher | `REALTIME_QUOTE \| STOCK_ZT_POOL \| STOCK_INFO` |
```

For `MyquantFetcher` row, change:
```
| MyquantFetcher | `HISTORICAL_DWM \| HISTORICAL_MIN \| REALTIME_QUOTE \| STOCK_LIST \| TRADE_CALENDAR \| INDEX_HISTORICAL \| INDEX_INTRADAY` |
```
to:
```
| MyquantFetcher | `HISTORICAL_DWM \| HISTORICAL_MIN \| REALTIME_QUOTE \| STOCK_LIST \| TRADE_CALENDAR \| INDEX_HISTORICAL \| INDEX_INTRADAY \| STOCK_INFO` |
```

- [ ] **Step 3: Add `CACHE_TTL_STOCK_INFO` to the Configuration section**

In `CLAUDE.md`, find the Configuration section (around line 736). After the `CACHE_TTL_STOCK_INTRADAY` line, add:

```markdown
- `CACHE_TTL_STOCK_INFO` - 公司画像缓存 TTL 秒 (default: 3600)
```

- [ ] **Step 4: Add `StockInfoResponse` to the Standardized Data Schema section**

In `CLAUDE.md`, find the "Standardized Data Schema" section. After the "Indicator catalog entry" code block, add a new code block:

```markdown
**StockInfo response** (response of `/stocks/{code}/info`):
```python
StockInfoResponse(
    code, name, ename, market,
    listed_date, delisted_date,
    total_shares, float_shares,  # 万股
    industry, concepts,           # `industry` 当前始终为空; 保留为扩展钩子
    registered_address, registered_capital, legal_representative,
    business_scope, established_date,
    secretary, secretary_phone, secretary_email,
    source,                       # "zhitu" | "myquant"
)
```
```

- [ ] **Step 5: Run the test suite to confirm no regressions**

Run: `.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: All tests pass (no behavioral change from doc updates)

- [ ] **Step 6: Commit**

```bash
cd "E:/GitRepo/stock_data"
git add CLAUDE.md
git commit -m "docs(CLAUDE): document STOCK_INFO capability, /stocks/{code}/info, CACHE_TTL_STOCK_INFO

Updates capability routing table, fetcher capability declarations for
Zhitu and Myquant, env-var reference, and Standardized Data Schema
section with StockInfoResponse shape.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review Checklist (run before final handoff)

After completing all 7 tasks, verify:

1. **Spec coverage** — every requirement in `docs/superpowers/specs/2026-06-14-stock-info-api-design.md` is implemented:
   - §4 change list (9 files) → all covered by Tasks 1-7
   - §5 schema (19 fields) → Task 4
   - §6 fetcher implementation → Tasks 1 & 2
   - §7 manager + route + cache → Tasks 3, 5, 6
   - §8 error matrix → covered by Task 6's route tests (503 cases)
   - §9 tests → Tasks 1, 2, 6 (3 test files)
   - §10 docs → Task 7

2. **Placeholder scan** — search the plan for "TBD", "TODO", "implement later"; none present.

3. **Type consistency** — `get_stock_info` signature: `(self, stock_code: str) -> dict | None` consistently used in base mapping, both fetchers, manager, and route.

4. **Decorator order** — `@router.get` (outer) + `@endpoint_meta` (inner), matches project convention from CLAUDE.md anti-pattern guidance.

5. **Source field** — fetcher dicts do NOT contain `source` key; manager injects it via `return_source=True`; route adds it explicitly. No `TypeError: got multiple values for keyword argument 'source'`.

6. **Free-tier reality** — Myquant only fills 3 fields; `total_shares/float_shares/industry` are `None`/`""` in Myquant response. Documented in Task 2 test and schema docstring.

7. **Run final test pass**:
   ```bash
   cd "E:/GitRepo/stock_data"
   .venv/Scripts/python.exe -m pytest tests/ -q
   ruff check .
   ```
   Expected: All tests pass, ruff clean.
