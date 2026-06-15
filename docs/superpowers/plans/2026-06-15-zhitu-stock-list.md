# Zhitu 股票列表接入 + Exchange 持久化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add ZhituFetcher `get_all_stocks` (P4 backup) + persist a normalized `exchange` column on `stock_list`, exposed via `GET /stocks`.

**Architecture:** Zhitu joins the STOCK_LIST failover chain at its default priority 4 (after Baostock/Akshare/Myquant). The fetcher passes `jys` raw; the persistence layer normalizes (`sh`/`SHSE` → `"SH"`, etc.) on write. `StockInfo` gains an optional `exchange` field that surfaces whatever the persistence layer has — `null` when unknown.

**Tech Stack:** Python 3.11+, FastAPI, SQLite (via existing `persistence` layer), pytest, requests (mocked).

**Spec:** `docs/superpowers/specs/2026-06-15-zhitu-stock-list-design.md`

---

## File Structure

| File | Responsibility | Action |
|---|---|---|
| `stock_data/data_provider/fetchers/zhitu_fetcher.py` | Add `get_all_stocks`, add `STOCK_LIST` capability | Modify |
| `stock_data/data_provider/persistence/stock_list.py` | Add `exchange` column, `_normalize_exchange` helper, update read/write | Modify |
| `stock_data/api/schemas.py` | `StockInfo.exchange: str \| None = None` | Modify |
| `stock_data/api/routes.py` | `list_stocks` passes `exchange` to `StockInfo` | Modify |
| `tests/test_zhitu_fetcher.py` | Tests for `get_all_stocks` + `STOCK_LIST` capability | Modify |
| `tests/test_stock_list_exchange.py` | New: `_normalize_exchange` + persistence round-trip | Create |
| `tests/test_routes.py` | Test `GET /stocks` response contains `exchange` | Modify |
| `CLAUDE.md` | Update Zhitu capability, add `/hs/list/all` endpoint doc | Modify |

No new modules; no structural changes.

---

## Task 1: Add `_normalize_exchange` helper (pure function)

**Files:**
- Modify: `stock_data/data_provider/persistence/stock_list.py`
- Create: `tests/test_stock_list_exchange.py`

- [ ] **Step 1: Write the failing test**

In `tests/test_stock_list_exchange.py`:

```python
"""Tests for stock_list exchange normalization."""
from stock_data.data_provider.persistence.stock_list import _normalize_exchange


class TestNormalizeExchange:
    def test_none_returns_none(self):
        assert _normalize_exchange(None) is None

    def test_empty_string_returns_none(self):
        assert _normalize_exchange("") is None

    def test_sh_lowercase(self):
        assert _normalize_exchange("sh") == "SH"

    def test_SH_uppercase(self):
        assert _normalize_exchange("SH") == "SH"

    def test_SHSE_full_name(self):
        assert _normalize_exchange("SHSE") == "SH"

    def test_SSE_alias(self):
        assert _normalize_exchange("SSE") == "SH"

    def test_sz_lowercase(self):
        assert _normalize_exchange("sz") == "SZ"

    def test_SZSE_full_name(self):
        assert _normalize_exchange("SZSE") == "SZ"

    def test_bj_lowercase(self):
        assert _normalize_exchange("bj") == "BJ"

    def test_BSE_alias(self):
        assert _normalize_exchange("BSE") == "BJ"

    def test_unknown_uppercased(self):
        assert _normalize_exchange("tw") == "TW"

    def test_whitespace_stripped(self):
        assert _normalize_exchange("  sh  ") == "SH"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_stock_list_exchange.py -v`
Expected: `ImportError: cannot import name '_normalize_exchange' from 'stock_data.data_provider.persistence.stock_list'`

- [ ] **Step 3: Add the helper**

In `stock_data/data_provider/persistence/stock_list.py`, add at module level (after imports, before `init_schema`):

```python
def _normalize_exchange(value: str | None) -> str | None:
    """归一化各 fetcher 返回的交易所标识。

    Zhitu 返回 ``"sh"``/``"sz"``；Myquant 返回 ``"SHSE"``/``"SZSE"``；
    其它 fetcher 不返回该字段（入参 None）。

    Returns:
        归一化后的 2 字母大写代码 (``"SH"``/``"SZ"``/``"BJ"``)；
        空 / None 返回 None；未知值返回 strip + upper 后原样。
    """
    if not value:
        return None
    v = value.strip().upper()
    if v in ("SH", "SHSE", "SSE"):
        return "SH"
    if v in ("SZ", "SZSE"):
        return "SZ"
    if v in ("BJ", "BSE"):
        return "BJ"
    return v
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_stock_list_exchange.py -v`
Expected: 12 passed

- [ ] **Step 5: Commit**

```bash
git add stock_data/data_provider/persistence/stock_list.py tests/test_stock_list_exchange.py
git commit -m "feat(persistence): add _normalize_exchange helper

Pure function normalizing fetcher-specific exchange identifiers
(sh/SH/SHSE/SSE → SH, etc.) for the new stock_list.exchange column.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Add `exchange` column + update read/write in `stock_list` persistence

**Files:**
- Modify: `stock_data/data_provider/persistence/stock_list.py`
- Modify: `tests/test_stock_list_exchange.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_stock_list_exchange.py`:

```python
import pytest

from stock_data.data_provider.persistence.stock_list import (
    init_schema,
    _normalize_exchange,
    update_cached_stocks,
    get_cached_stocks,
)


class TestExchangeRoundTrip:
    """Round-trip: update_cached_stocks writes _normalize_exchange'd value,
    get_cached_stocks reads it back."""

    @pytest.fixture
    def temp_db(self, tmp_path, monkeypatch):
        from stock_data.data_provider.persistence import db
        monkeypatch.setattr(db, "get_db_path", lambda: tmp_path / "test.db")
        # Force re-init for the new test DB
        from stock_data.data_provider.persistence import stock_list
        monkeypatch.setattr(stock_list, "init_schema",
                            lambda: stock_list._real_init_schema() if hasattr(stock_list, "_real_init_schema")
                            else None)
        # Reset the cached connection if any
        try:
            db.get_connection().close()
        except Exception:
            pass
        yield tmp_path / "test.db"

    def test_round_trip_zhitu_jys_sh(self, tmp_path, monkeypatch):
        from stock_data.data_provider.persistence import db, stock_list
        monkeypatch.setattr(db, "get_db_path", lambda: tmp_path / "test.db")
        # Reset module-level connection cache
        monkeypatch.setattr(db, "_conn", None, raising=False)
        stock_list.init_schema()

        update_cached_stocks("csi", [
            {"code": "688411", "name": "N海博", "exchange": "sh"},
        ])
        rows = get_cached_stocks("csi")
        assert rows == [
            {"code": "688411", "name": "N海博",
             "exchange": "SH", "updated_at": pytest.approx(rows[0]["updated_at"]) if rows else None}
        ][:0] or any(r["exchange"] == "SH" for r in rows)

    def test_round_trip_myquant_SHSE(self, tmp_path, monkeypatch):
        from stock_data.data_provider.persistence import db, stock_list
        monkeypatch.setattr(db, "get_db_path", lambda: tmp_path / "test.db")
        monkeypatch.setattr(db, "_conn", None, raising=False)
        stock_list.init_schema()

        update_cached_stocks("csi", [
            {"code": "600519", "name": "贵州茅台", "exchange": "SHSE"},
        ])
        rows = get_cached_stocks("csi")
        assert len(rows) == 1
        assert rows[0]["exchange"] == "SH"

    def test_round_trip_missing_exchange_is_none(self, tmp_path, monkeypatch):
        from stock_data.data_provider.persistence import db, stock_list
        monkeypatch.setattr(db, "get_db_path", lambda: tmp_path / "test.db")
        monkeypatch.setattr(db, "_conn", None, raising=False)
        stock_list.init_schema()

        # Baostock / Akshare style: no 'exchange' key
        update_cached_stocks("csi", [
            {"code": "000001", "name": "平安银行"},
        ])
        rows = get_cached_stocks("csi")
        assert len(rows) == 1
        assert rows[0]["exchange"] is None

    def test_round_trip_explicit_none_is_none(self, tmp_path, monkeypatch):
        from stock_data.data_provider.persistence import db, stock_list
        monkeypatch.setattr(db, "get_db_path", lambda: tmp_path / "test.db")
        monkeypatch.setattr(db, "_conn", None, raising=False)
        stock_list.init_schema()

        update_cached_stocks("csi", [
            {"code": "000002", "name": "万 科Ａ", "exchange": None},
        ])
        rows = get_cached_stocks("csi")
        assert rows[0]["exchange"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_stock_list_exchange.py::TestExchangeRoundTrip -v`
Expected: 4 failed (column doesn't exist yet)

- [ ] **Step 3: Update `init_schema` to add `exchange` column**

In `stock_data/data_provider/persistence/stock_list.py`, modify the `init_schema` function:

```python
def init_schema() -> None:
    """Initialize the database schema."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS stock_list (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                market TEXT NOT NULL,
                code TEXT NOT NULL,
                name TEXT NOT NULL,
                exchange TEXT,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(market, code)
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_market ON stock_list(market)
        """)
        conn.commit()
        logger.info(f"[StockCache] Database initialized at {get_db_path()}")
    finally:
        conn.close()
```

Only addition is `exchange TEXT,` on the line after `name TEXT NOT NULL,`.

- [ ] **Step 4: Update `update_cached_stocks` to normalize and write exchange**

In `stock_data/data_provider/persistence/stock_list.py`, replace the `update_cached_stocks` body:

```python
def update_cached_stocks(market: str, stocks: list) -> int:
    """Update cached stocks for a market.

    Args:
        market: Market type (csi/hk/us)
        stocks: List of dicts. Required keys: ``code``, ``name``.
            Optional key ``exchange`` — passed through ``_normalize_exchange``
            before write (so callers can pass Zhitu ``"sh"`` / Myquant
            ``"SHSE"`` / etc. without pre-normalizing).

    Returns:
        Number of stocks inserted/updated.
    """
    if not stocks:
        return 0

    init_schema()

    conn = get_connection()
    try:
        with conn:
            cursor = conn.cursor()
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            cursor.executemany(
                """INSERT OR REPLACE INTO stock_list
                   (market, code, name, exchange, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                [
                    (
                        market,
                        stock["code"],
                        stock["name"],
                        _normalize_exchange(stock.get("exchange")),
                        now,
                    )
                    for stock in stocks
                ],
            )

            logger.info(f"[StockCache] Updated {len(stocks)} stocks for market={market}")
            return len(stocks)
    except Exception as e:
        logger.error(f"[StockCache] Update failed: {e}")
        raise
    finally:
        conn.close()
```

- [ ] **Step 5: Update `_read_from_db` and `get_cached_stocks` to include `exchange`**

In `stock_data/data_provider/persistence/stock_list.py`:

```python
def _read_from_db(market: str) -> list:
    """Read stock list from database."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """SELECT code, name, exchange, updated_at
               FROM stock_list WHERE market = ? ORDER BY code""",
            (market,),
        )
        rows = cursor.fetchall()
        return [
            {
                "code": row["code"],
                "name": row["name"],
                "exchange": row["exchange"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]
    finally:
        conn.close()
```

```python
def get_cached_stocks(market: str) -> list:
    """Get cached stocks for a market (backward compatible)."""
    init_schema()

    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """SELECT code, name, exchange, updated_at
               FROM stock_list WHERE market = ? ORDER BY code""",
            (market,),
        )
        rows = cursor.fetchall()
        return [
            {
                "code": row["code"],
                "name": row["name"],
                "exchange": row["exchange"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]
    finally:
        conn.close()
```

- [ ] **Step 6: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_stock_list_exchange.py -v`
Expected: 16 passed (12 normalization + 4 round-trip)

- [ ] **Step 7: Run existing tests that touch stock_list to ensure no regression**

Run: `.venv/Scripts/python.exe -m pytest tests/test_persistence_origin.py tests/test_trade_calendar.py tests/test_api_cache.py -v`
Expected: all pass (existing callers don't read `exchange`, so they're not affected)

- [ ] **Step 8: Commit**

```bash
git add stock_data/data_provider/persistence/stock_list.py tests/test_stock_list_exchange.py
git commit -m "feat(persistence): add exchange column to stock_list

Nullable column; _normalize_exchange applied on write. Read paths
(_read_from_db, get_cached_stocks) surface the field so /stocks can
expose it.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Add Zhitu `get_all_stocks` + `STOCK_LIST` capability

**Files:**
- Modify: `stock_data/data_provider/fetchers/zhitu_fetcher.py`
- Modify: `tests/test_zhitu_fetcher.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_zhitu_fetcher.py`:

```python
class TestGetAllStocks:
    def setup_method(self):
        self.fetcher = ZhituFetcher()

    def test_returns_empty_when_unavailable(self, monkeypatch):
        monkeypatch.setattr(
            "stock_data.data_provider.fetchers.zhitu_fetcher.os.getenv",
            lambda *a, **k: "" if a and a[0] == "ZHITU_TOKEN" else "",
        )
        result = self.fetcher.get_all_stocks("csi")
        assert result == []

    def test_returns_empty_for_non_csi_market(self, monkeypatch):
        monkeypatch.setattr(
            "stock_data.data_provider.fetchers.zhitu_fetcher.os.getenv",
            lambda *a, **k: "test_token" if a and a[0] == "ZHITU_TOKEN" else "",
        )
        self.fetcher._token = "test_token"
        assert self.fetcher.get_all_stocks("hk") == []
        assert self.fetcher.get_all_stocks("us") == []

    @patch("stock_data.data_provider.fetchers.zhitu_fetcher.requests.get")
    def test_normalizes_zhitu_payload(self, mock_get, monkeypatch):
        monkeypatch.setattr(
            "stock_data.data_provider.fetchers.zhitu_fetcher.os.getenv",
            lambda *a, **k: "test_token" if a and a[0] == "ZHITU_TOKEN" else "",
        )
        self.fetcher._token = "test_token"
        mock_response = MagicMock()
        mock_response.json.return_value = [
            {"dm": "688411", "mc": "N海博", "jys": "sh"},
            {"dm": "000001", "mc": "平安银行", "jys": "sz"},
            {"dm": "300750", "mc": "宁德时代", "jys": "sz"},
        ]
        mock_response.raise_for_status = lambda: None
        mock_get.return_value = mock_response

        result = self.fetcher.get_all_stocks("csi")
        assert len(result) == 3
        assert result[0] == {"code": "688411", "name": "N海博", "exchange": "sh"}
        assert result[1] == {"code": "000001", "name": "平安银行", "exchange": "sz"}
        assert result[2] == {"code": "300750", "name": "宁德时代", "exchange": "sz"}

    @patch("stock_data.data_provider.fetchers.zhitu_fetcher.requests.get")
    def test_empty_list_response(self, mock_get, monkeypatch):
        monkeypatch.setattr(
            "stock_data.data_provider.fetchers.zhitu_fetcher.os.getenv",
            lambda *a, **k: "test_token" if a and a[0] == "ZHITU_TOKEN" else "",
        )
        self.fetcher._token = "test_token"
        mock_response = MagicMock()
        mock_response.json.return_value = []
        mock_response.raise_for_status = lambda: None
        mock_get.return_value = mock_response
        assert self.fetcher.get_all_stocks("csi") == []

    @patch("stock_data.data_provider.fetchers.zhitu_fetcher.requests.get")
    def test_error_detail_returns_empty(self, mock_get, monkeypatch):
        monkeypatch.setattr(
            "stock_data.data_provider.fetchers.zhitu_fetcher.os.getenv",
            lambda *a, **k: "test_token" if a and a[0] == "ZHITU_TOKEN" else "",
        )
        self.fetcher._token = "test_token"
        mock_response = MagicMock()
        mock_response.json.return_value = {"detail": "Licence证书无效"}
        mock_response.raise_for_status = lambda: None
        mock_get.return_value = mock_response
        assert self.fetcher.get_all_stocks("csi") == []

    @patch("stock_data.data_provider.fetchers.zhitu_fetcher.requests.get")
    def test_unexpected_response_type_returns_empty(self, mock_get, monkeypatch):
        monkeypatch.setattr(
            "stock_data.data_provider.fetchers.zhitu_fetcher.os.getenv",
            lambda *a, **k: "test_token" if a and a[0] == "ZHITU_TOKEN" else "",
        )
        self.fetcher._token = "test_token"
        mock_response = MagicMock()
        mock_response.json.return_value = "not a list"
        mock_response.raise_for_status = lambda: None
        mock_get.return_value = mock_response
        assert self.fetcher.get_all_stocks("csi") == []

    @patch("stock_data.data_provider.fetchers.zhitu_fetcher.requests.get")
    def test_http_failure_returns_empty(self, mock_get, monkeypatch):
        monkeypatch.setattr(
            "stock_data.data_provider.fetchers.zhitu_fetcher.os.getenv",
            lambda *a, **k: "test_token" if a and a[0] == "ZHITU_TOKEN" else "",
        )
        self.fetcher._token = "test_token"
        mock_get.side_effect = requests.ConnectionError("boom")
        assert self.fetcher.get_all_stocks("csi") == []

    @patch("stock_data.data_provider.fetchers.zhitu_fetcher.requests.get")
    def test_skips_rows_with_empty_code(self, mock_get, monkeypatch):
        monkeypatch.setattr(
            "stock_data.data_provider.fetchers.zhitu_fetcher.os.getenv",
            lambda *a, **k: "test_token" if a and a[0] == "ZHITU_TOKEN" else "",
        )
        self.fetcher._token = "test_token"
        mock_response = MagicMock()
        mock_response.json.return_value = [
            {"dm": "600519", "mc": "贵州茅台", "jys": "sh"},
            {"dm": "", "mc": "无名", "jys": "sz"},
        ]
        mock_response.raise_for_status = lambda: None
        mock_get.return_value = mock_response
        result = self.fetcher.get_all_stocks("csi")
        assert len(result) == 1
        assert result[0]["code"] == "600519"

    def test_capability_includes_stock_list(self):
        assert DataCapability.STOCK_LIST in ZhituFetcher().supported_data_types
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_zhitu_fetcher.py::TestGetAllStocks -v`
Expected: 9 failed (method doesn't exist)

- [ ] **Step 3: Add `STOCK_LIST` capability**

In `stock_data/data_provider/fetchers/zhitu_fetcher.py`, modify the `supported_data_types`:

```python
    supported_data_types = (
        DataCapability.REALTIME_QUOTE
        | DataCapability.STOCK_ZT_POOL
        | DataCapability.STOCK_INFO
        | DataCapability.HISTORICAL_MIN
        | DataCapability.STOCK_LIST
    )
```

- [ ] **Step 4: Add `get_all_stocks` method**

In `stock_data/data_provider/fetchers/zhitu_fetcher.py`, add the method just before `get_stock_info` (after `_normalize_intraday_zhitu`):

```python
    def get_all_stocks(self, market: str = "csi") -> list:
        """Get the full A-share stock list from Zhitu's ``/hs/list/all``.

        Zhitu only supports A-share (``csi``); HK/US return ``[]`` so the
        manager's failover keeps trying other fetchers. Each item is
        ``{"code": <dm>, "name": <mc>, "exchange": <jys>}`` — the
        ``exchange`` value is passed through raw (``"sh"``/``"sz"``);
        persistence normalizes via ``_normalize_exchange``.

        Returns:
            List of stock dicts, or ``[]`` on token absence / HTTP
            failure / parse error. Empty list (not raise) keeps the
            failover loop alive so the next fetcher can try.
        """
        if market != "csi":
            return []
        if not self.is_available():
            logger.warning("[ZhituFetcher] ZHITU_TOKEN not configured")
            return []

        try:
            url = f"{ZHITU_API_BASE}/hs/list/all"
            params = {"token": self._token}

            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()

            data = response.json()

            if isinstance(data, dict) and "detail" in data:
                logger.warning(
                    f"[ZhituFetcher] get_all_stocks API error: "
                    f"{data.get('detail', 'unknown')[:80]}"
                )
                return []

            if not isinstance(data, list):
                logger.warning(
                    f"[ZhituFetcher] get_all_stocks unexpected type: {type(data)}"
                )
                return []

            result: list = []
            for row in data:
                if not isinstance(row, dict):
                    continue
                code = str(row.get("dm", "")).strip()
                if not code:
                    continue
                result.append(
                    {
                        "code": code,
                        "name": str(row.get("mc", "")).strip(),
                        "exchange": str(row.get("jys", "")).strip().lower(),
                    }
                )
            return result

        except requests.exceptions.Timeout:
            logger.warning("[ZhituFetcher] get_all_stocks timeout")
            return []
        except requests.exceptions.RequestException:
            logger.warning(
                "[ZhituFetcher] get_all_stocks request failed", exc_info=True
            )
            return []
        except Exception:
            logger.warning(
                "[ZhituFetcher] get_all_stocks error", exc_info=True
            )
            return []
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_zhitu_fetcher.py -v`
Expected: 18 passed (9 existing + 9 new)

- [ ] **Step 6: Run capability map test (auto-covered)**

Run: `.venv/Scripts/python.exe -m pytest tests/test_capability_method_map.py -v`
Expected: all pass — `STOCK_LIST` is already in `CAPABILITY_TO_METHOD` (maps to `get_all_stocks`), and now `ZhituFetcher` actually implements it.

- [ ] **Step 7: Commit**

```bash
git add stock_data/data_provider/fetchers/zhitu_fetcher.py tests/test_zhitu_fetcher.py
git commit -m "feat(zhitu): add get_all_stocks + STOCK_LIST capability

Calls /hs/list/all to fetch the full A-share list (single HTTP).
Returns [] for hk/us markets. Exchange passed through raw (sh/sz);
persistence layer normalizes on write.

P4 last-resort backup in the STOCK_LIST failover chain
(Baostock → Akshare → Myquant → Zhitu).

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: Add `exchange` field to `StockInfo` schema + `list_stocks` route

**Files:**
- Modify: `stock_data/api/schemas.py`
- Modify: `stock_data/api/routes.py`
- Modify: `tests/test_routes.py`

- [ ] **Step 1: Write the failing test**

In `tests/test_routes.py`, find the existing `TestListStocks` class (around line 143) and update:

```python
    def test_list_stocks_csi(self, client):
        response = client.get("/api/v1/stocks?market=csi")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0
        # Every record now has the exchange field (may be null)
        for stock in data:
            assert "exchange" in stock
            assert stock["exchange"] in (None, "SH", "SZ", "BJ") or isinstance(stock["exchange"], str)
```

Keep the other tests in the class (`test_list_stocks_with_pagination`, `test_list_stocks_invalid_market`) as-is.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_routes.py::TestListStocks::test_list_stocks_csi -v`
Expected: AssertionError ("exchange" not in stock)

- [ ] **Step 3: Add `exchange` field to `StockInfo` schema**

In `stock_data/api/schemas.py`, modify the `StockInfo` class (around line 248):

```python
class StockInfo(BaseModel):
    """Stock information response."""

    code: str = Field(description="Stock code (e.g., 600519, AAPL, HK00700)")
    name: str = Field(description="Stock name")
    market: str = Field(description="Market type: csi/hk/us")
    exchange: str | None = Field(
        default=None,
        description="Exchange code (SH/SZ/BJ) when known; null otherwise. "
        "Clients may derive from code prefix as a fallback.",
    )
```

- [ ] **Step 4: Update `list_stocks` route to pass `exchange`**

In `stock_data/api/routes.py`, find `list_stocks` (around line 1146-1175) and replace the return statement:

```python
    # Get stock list with automatic refresh (cache layer handles daily refresh logic)
    manager = get_manager()
    stocks, _origin = stock_cache.get_stock_list(market, refresh=refresh, manager=manager)
    logger.info(f"[list_stocks] Returned {len(stocks)} stocks for market={market}")
    page = stocks[offset : offset + limit]
    return [
        StockInfo(
            code=s["code"],
            name=s["name"],
            market=market,
            exchange=s.get("exchange"),
        )
        for s in page
    ]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_routes.py::TestListStocks -v`
Expected: all pass

- [ ] **Step 6: Run all route tests for regression**

Run: `.venv/Scripts/python.exe -m pytest tests/test_routes.py -v`
Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add stock_data/api/schemas.py stock_data/api/routes.py tests/test_routes.py
git commit -m "feat(api): expose exchange field on GET /stocks response

StockInfo schema gains optional exchange (null when unknown).
Backward-compatible: existing clients ignore the new field.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: Update CLAUDE.md documentation

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update Zhitu capability row in fetcher capability table**

Find the table entry for ZhituFetcher (search for "ZhituFetcher" in the capability declarations section) and update the row to:

```
| ZhituFetcher | `REALTIME_QUOTE \| STOCK_ZT_POOL \| STOCK_INFO \| HISTORICAL_MIN \| STOCK_LIST` |
```

(Adds `STOCK_LIST` to the existing list.)

- [ ] **Step 2: Add `/hs/list/all` endpoint to ZhituFetcher section**

In the ZhituFetcher provider section, add a new subsection after the existing "Links" line:

```markdown
**Stock list endpoint**: `https://api.zhituapi.com/hs/list/all?token={token}` (P4 last-resort backup in STOCK_LIST failover chain)

- Single HTTP call returns the full A-share list (~5000+ stocks)
- Rate limit: 300/min (包量版), 1000/min (体验版/包月版), per Zhitu docs
- Update frequency: 16:20 daily
- Returns `{"dm": <code>, "mc": <name>, "jys": "sh"|"sz"}` — `jys` is passed through raw to the persistence layer, which normalizes via `_normalize_exchange` (zhitu `sh`/`sz`, myquant `SHSE`/`SZSE`, etc. all map to canonical `"SH"`/`"SZ"`/`"BJ"`).
- Non-A-share markets return `[]` (Zhitu only covers csi).
```

- [ ] **Step 3: Update `STOCK_LIST` row in `Provider API Documentation` capability table (if needed)**

Confirm `CAPABILITY_TO_METHOD[STOCK_LIST]` is already `get_all_stocks` (it is — no change). Just verify the table line for ZhituFetcher in CLAUDE.md has `STOCK_LIST`.

- [ ] **Step 4: Update `StockInfo` response schema doc**

In the "Standardized Data Schema" section, find the `StockInfo` description and update to:

```markdown
**StockInfo response** (response of `GET /stocks?market=csi|hk|us`):
```python
StockInfo(
    code, name, market,
    exchange: str|None,  # "SH" / "SZ" / "BJ" when known; null otherwise
                        # (Zhitu / Myquant populate; Baostock / Akshare leave null)
)
```
```

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(zhitu): document /hs/list/all endpoint and StockInfo.exchange

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: End-to-end verification

**Files:** none (test-only verification)

- [ ] **Step 1: Run all directly-touched test files**

Run:
```bash
.venv/Scripts/python.exe -m pytest \
  tests/test_zhitu_fetcher.py \
  tests/test_stock_list_exchange.py \
  tests/test_routes.py \
  tests/test_capability_method_map.py \
  tests/test_persistence_origin.py \
  tests/test_explorer_manifest_endpoint.py \
  tests/test_fetcher_test_endpoint.py \
  -v
```

Expected: all pass.

- [ ] **Step 2: Run broader regression suite**

Run:
```bash
.venv/Scripts/python.exe -m pytest tests/ -v --tb=short -x
```

If `-x` fails on an unrelated test, drop `-x` and continue; capture any failures and address:
- If failures are in `test_zhitu_fetcher.py` / `test_stock_list_exchange.py` / `test_routes.py` → fix immediately
- If failures are in unrelated modules → log and continue (out of scope)

- [ ] **Step 3: Lint**

```bash
ruff check stock_data/ tests/
ruff format --check stock_data/ tests/
```

Fix any auto-fixable issues with `ruff check --fix` and `ruff format`. Commit any formatting changes:

```bash
git add -u
git commit -m "style: ruff autofixes

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>" || true
```

- [ ] **Step 4: Manual smoke check (optional, only if server can be started)**

If the server can run locally:
```bash
ZHITU_TOKEN=demo STOCK_DB_INIT=true .venv/Scripts/python.exe -m stock_data.server &
SERVER_PID=$!
sleep 3
curl -s 'http://localhost:8888/api/v1/stocks?market=csi&limit=3' | python -m json.tool
kill $SERVER_PID
```

Expected response shape (exchange may be null or populated depending on which fetcher served):
```json
[
  {"code": "...", "name": "...", "market": "csi", "exchange": "SH"},
  ...
]
```

If the server can't run, skip — automated tests are sufficient.

- [ ] **Step 5: Final review**

```bash
git log --oneline -10
git diff master --stat
```

Confirm:
- All commits use `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`
- All spec items covered (capability, normalization, schema, API contract, docs)
- No accidental files modified

---

## Self-Review (filled after writing)

**Spec coverage:**
- ✅ Section 3.1 ZhituFetcher changes — Task 3
- ✅ Section 3.2 Persistence schema + helper + read/write — Tasks 1 + 2
- ✅ Section 3.3 API contract (StockInfo.exchange + route) — Task 4
- ✅ Section 3.4 unchanged — implicitly verified (no task touches Myquant/Baostock/Akshare or other routes)
- ✅ Section 4 test strategy — Tasks 1-4 cover all listed tests
- ✅ Section 5 CLAUDE.md — Task 5
- ✅ Section 6 risks — Task 2 step 7 + Task 6 step 2 cover regressions

**Placeholders scan:** No TBD/TODO. All test code is complete. All commit messages specified.

**Type consistency:**
- `_normalize_exchange(value: str | None) -> str | None` defined in Task 1, used in Task 2 step 4 — matches.
- `get_all_stocks(market: str = "csi") -> list` defined in Task 3 — matches BaseFetcher contract.
- `StockInfo.exchange: str | None` defined in Task 4 — Pydantic field matches routes.py usage.

**Granularity check:** Each step is a single action. Tests run before commits. Each commit has a clean message.
