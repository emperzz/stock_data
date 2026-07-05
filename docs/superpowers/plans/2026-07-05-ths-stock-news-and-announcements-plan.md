# ThsFetcher Stock News + Announcements (P7 Backup) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `ThsFetcher.get_stock_news` and `ThsFetcher.get_announcements` so the existing `/stocks/{code}/news` and `/stocks/{code}/announcements` endpoints get THS as a P7 backup; expose the upstream `raw_url` (cninfo PDF) field through `AnnouncementRecord`.

**Architecture:** Pure-HTTP additions to `ThsFetcher` against `basic.10jqka.com.cn/fuyao/info/company/v1/news` and `/basicapi/notice/pub`. Capability flags `STOCK_NEWS` + `ANNOUNCEMENT` already exist in `DataCapability` and are already mapped in `CAPABILITY_TO_METHOD` — only the fetcher methods and one schema field are new. Manager failover engages automatically.

**Tech Stack:** Python 3.10+, FastAPI, Pydantic v2, `requests` (via `utils.http.json_get`), `pytest`.

---

## File Structure

| File | Change | Why |
|---|---|---|
| `stock_data/data_provider/fetchers/ths_fetcher.py` | Add 3 module-level constants, 2 methods, extend `supported_data_types`, update module docstring | Fetcher layer (the whole point of the feature) |
| `stock_data/api/schemas.py` | Add `raw_url: str` field on `AnnouncementRecord` | Schema allows THS's extra `raw_url` to surface cleanly |
| `tests/test_ths_fetcher_get_stock_news.py` | New | Mocked unit tests for the new method |
| `tests/test_ths_fetcher_get_announcements.py` | New | Mocked unit tests for the new method |
| `tests/test_ths_basic_endpoints_live.py` | New (marked `live_network`) | 1-2 endpoint smoke tests, default `pytest` skips |
| `tests/fixtures/ths_basic_news.json` | Already on disk (commit `78c48c4`) | Source fixture for both mock and live tests |
| `tests/fixtures/ths_basic_notice.json` | Already on disk (commit `78c48c4`) | Same |

**Zero-touch files:** `stock_data/data_provider/manager.py`, `stock_data/api/routes/news.py`, `stock_data/api/routes/stocks.py`, `stock_data/api/cache.py`, `stock_data/explorer/*` — failover routing auto-engages.

---

## Task 1: `ThsFetcher.get_stock_news` with TDD

**Files:**
- Modify: `stock_data/data_provider/fetchers/ths_fetcher.py:1-19` (module docstring), `:260-268` (`supported_data_types`), add three constants after `_THS_MARKET_ID_MAP` (~line 198) and the method
- Test: `tests/test_ths_fetcher_get_stock_news.py` (new)
- Fixture: `tests/fixtures/ths_basic_news.json` (read-only reference)

- [ ] **Step 1: Write the failing test for the happy path**

Create `tests/test_ths_fetcher_get_stock_news.py` with this content:

```python
"""Unit tests for ThsFetcher.get_stock_news (mocked, no live network)."""
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from stock_data.data_provider.base import DataFetchError
from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher


_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((_FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def ths() -> ThsFetcher:
    return ThsFetcher()


def test_get_stock_news_returns_normalized_items(ths):
    """Should normalize THS upstream into EastMoney-compatible dict shape."""
    payload = _load("ths_basic_news.json")
    with patch(
        "stock_data.data_provider.fetchers.ths_fetcher.json_get",
        return_value=payload,
    ) as mocked:
        items = ths.get_stock_news("300740", limit=15)
    assert mocked.call_count == 1
    call = mocked.call_args
    # Caller signature: json_get(url, params=..., headers=..., timeout=...)
    assert call.args[0] == "https://basic.10jqka.com.cn/fuyao/info/company/v1/news"
    assert call.kwargs["params"]["code"] == "300740"
    assert call.kwargs["params"]["market"] == "33"  # 深圳 → market=33
    assert call.kwargs["headers"]["Referer"].startswith("https://basic.10jqka.com.cn")
    assert isinstance(items, list)
    assert len(items) == 5  # fixture has 5 records
    first = items[0]
    # Shape must match EastMoneyFetcher.get_stock_news output exactly
    assert set(first.keys()) == {"title", "url", "source_domain", "publish_date", "media_name"}
    assert first["title"] == "行业周报|美容护理指数涨7.03%, 跑赢上证指数6.62%"
    assert first["url"].startswith("http://news.10jqka.com.cn/")
    assert first["source_domain"] == "news.10jqka.com.cn"
    assert first["publish_date"] == "2026-07-03"
    assert first["media_name"] == ""  # THS upstream has no media_name


def test_get_stock_news_no_market_id_returns_empty(ths):
    """Codes not in _THS_MARKET_ID_MAP (北交所 4/8, HK, US) → []. No HTTP call."""
    with patch(
        "stock_data.data_provider.fetchers.ths_fetcher.json_get"
    ) as mocked:
        items = ths.get_stock_news("400001", limit=10)  # 北交所不映射
    assert items == []
    mocked.assert_not_called()


def test_get_stock_news_upstream_error_code_returns_empty(ths):
    """status_code != 0 → return [], not raise. Manager will keep failing through."""
    bad_payload = {"status_code": 1, "status_msg": "upstream down", "data": {}}
    with patch(
        "stock_data.data_provider.fetchers.ths_fetcher.json_get",
        return_value=bad_payload,
    ):
        items = ths.get_stock_news("300740", limit=5)
    assert items == []


def test_get_stock_news_propagates_datafetcherror(ths):
    """Hard network failure raises DataFetchError; manager's _with_failover
    catches this and tries the next fetcher in the chain."""
    with patch(
        "stock_data.data_provider.fetchers.ths_fetcher.json_get",
        side_effect=DataFetchError("HTTP 503 from basic.10jqka.com.cn"),
    ):
        with pytest.raises(DataFetchError):
            ths.get_stock_news("600519", limit=5)


def test_get_stock_news_clamps_invalid_limit(ths):
    """Non-int / out-of-range limits clamp to [1, 100] / fallback 20."""
    payload = _load("ths_basic_news.json")
    for bad_input, expected in [
        ("abc", 20),
        (-3, 1),
        (9999, 100),
        (0, 1),
    ]:
        with patch(
            "stock_data.data_provider.fetchers.ths_fetcher.json_get",
            return_value=payload,
        ) as mocked:
            ths.get_stock_news("300740", limit=bad_input)
        params = mocked.call_args.kwargs["params"]
        assert params["limit"] == expected, (
            f"limit={bad_input!r} expected upstream limit={expected}, got {params['limit']}"
        )
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ths_fetcher_get_stock_news.py -v`
Expected: FAIL with `AttributeError: 'ThsFetcher' object has no attribute 'get_stock_news'` (or similar — the method does not exist yet).

- [ ] **Step 3: Update the module docstring**

In `stock_data/data_provider/fetchers/ths_fetcher.py:1-19`, change the docstring. Edit the existing block:

```python
"""
同花顺 HTTP API fetcher for signal layer data.

Provides: 热点题材(hot-topics), 北向资金(north-flow), 全球财经快讯(news-flash),
          新闻搜索(news-search), 板块 K 线(board-history), 个股新闻(stock-news),
          个股公告(announcements)
...existing lines preserved...
"""
```

(The "APIs:" lines are unchanged — only the first `Provides:` line changes.)

- [ ] **Step 4: Add the URL constants**

Immediately after the existing `_THS_MARKET_ID_MAP: dict[str, str] = {...}` block ending at line 197 (just before `_THS_BOARD_KLINE_URL`), insert:

```python
# 个股新闻 / 个股公告 — basic.10jqka.com.cn/fuyao/info/company/v1/...
_THS_NEWS_URL = "https://basic.10jqka.com.cn/fuyao/info/company/v1/news"
_THS_NOTICE_URL = "https://basic.10jqka.com.cn/basicapi/notice/pub"
_THS_BASIC_HEADERS = {
    "User-Agent": THS_UA,
    "Referer": "https://basic.10jqka.com.cn/astockpc/astockmain/index.html",
}
```

- [ ] **Step 5: Extend `supported_data_types`**

In `class ThsFetcher` (line ~262), change the existing `supported_data_types = (...)` to add two flags:

```python
supported_data_types = (
    DataCapability.HOT_TOPICS
    | DataCapability.NORTH_FLOW
    | DataCapability.NEWS_FLASH
    | DataCapability.NEWS_SEARCH
    | DataCapability.STOCK_BOARD
    | DataCapability.STOCK_NEWS       # 新: 个股新闻 basic.10jqka.com.cn
    | DataCapability.ANNOUNCEMENT     # 新: 个股公告 basic.10jqka.com.cn
)
```

- [ ] **Step 6: Add the `get_stock_news` method**

Insert the implementation at the end of `ThsFetcher` (right before the existing `get_stock_boards`, around line 825):

```python
def get_stock_news(self, stock_code: str, limit: int = 20) -> list[dict]:
    """THS 个股新闻 via basic.10jqka.com.cn/fuyao/info/company/v1/news.

    返回 dict shape 严格对齐 EastMoneyFetcher.get_stock_news:
      {title, url, source_domain, publish_date, media_name}.

    Soft failures (no market_id, upstream status_code != 0) → return [].
    Hard failures (network / JSON parse) → raise DataFetchError for
    manager.failover fallback to next fetcher.

    Returns:
        list of normalized news items; possibly empty.
    """
    code = normalize_stock_code(stock_code)
    market_id = _THS_MARKET_ID_MAP.get(code[:1])
    if not market_id:
        logger.warning(f"[ThsFetcher] get_stock_news: no market_id for {code!r}")
        return []
    try:
        n = max(1, min(int(limit), 100))
    except (TypeError, ValueError):
        n = 20
    payload = json_get(
        _THS_NEWS_URL,
        params={
            "type": "stock",
            "code": code,
            "market": market_id,
            "current": 1,
            "limit": n,
        },
        headers=_THS_BASIC_HEADERS,
        timeout=10,
    )
    if not isinstance(payload, dict) or payload.get("status_code") != 0:
        logger.warning(
            f"[ThsFetcher] get_stock_news({code}) upstream "
            f"status_code={payload.get('status_code') if isinstance(payload, dict) else 'N/A'}"
        )
        return []
    rows = (payload.get("data") or {}).get("data") or []
    out: list[dict] = []
    for r in rows:
        url = r.get("pc_url") or r.get("client_url") or r.get("mobile_url") or ""
        try:
            source_domain = urlparse(url).hostname or ""
        except Exception:
            source_domain = ""
        out.append({
            "title": str(r.get("title", "")),
            "url": url,
            "source_domain": source_domain,
            "publish_date": str(r.get("date", "")),
            "media_name": "",
        })
    return out
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ths_fetcher_get_stock_news.py -v`
Expected: 5 passed.

- [ ] **Step 8: Run the capability-method test to confirm wiring**

Run: `.venv/Scripts/python.exe -m pytest tests/test_capability_method_map.py -v`
Expected: all passed (we did not modify CAPABILITY_TO_METHOD, but `get_announcements` from Step 6's neighboring fetcher must still exist; we only added `get_stock_news` — already covered).

- [ ] **Step 9: Commit**

```bash
git add stock_data/data_provider/fetchers/ths_fetcher.py tests/test_ths_fetcher_get_stock_news.py
git commit -m "feat(ths): get_stock_news via basic.10jqka.com.cn (P7 backup)"
```

---

## Task 2: `ThsFetcher.get_announcements` with TDD

**Files:**
- Modify: `stock_data/data_provider/fetchers/ths_fetcher.py` (append method right after `get_stock_news`)
- Test: `tests/test_ths_fetcher_get_announcements.py` (new)
- Fixture: `tests/fixtures/ths_basic_notice.json` (read-only reference)

- [ ] **Step 1: Write the failing test for the happy path**

Create `tests/test_ths_fetcher_get_announcements.py`:

```python
"""Unit tests for ThsFetcher.get_announcements (mocked, no live network)."""
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from stock_data.data_provider.base import DataFetchError
from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher


_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((_FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def ths() -> ThsFetcher:
    return ThsFetcher()


def test_get_announcements_returns_normalized_items(ths):
    """Normalize THS into Cninfo-compatible shape, including raw_url bonus."""
    payload = _load("ths_basic_notice.json")
    with patch(
        "stock_data.data_provider.fetchers.ths_fetcher.json_get",
        return_value=payload,
    ) as mocked:
        items = ths.get_announcements("300740", page_size=15)
    call = mocked.call_args
    assert call.args[0] == "https://basic.10jqka.com.cn/basicapi/notice/pub"
    assert call.kwargs["params"]["code"] == "300740"
    assert call.kwargs["params"]["market"] == "33"
    assert call.kwargs["params"]["classify"] == "all"
    assert call.kwargs["params"]["page"] == 1
    assert len(items) == 5
    first = items[0]
    # Must contain at least the Cninfo-compatible fields; raw_url is the bonus
    assert first["title"] == "水羊股份：关于2026年第二季度可转换公司债券转股情况的公告"
    assert first["type"] == ""  # THS upstream `type` is classification, not announcement type
    assert first["date"] == "2026-07-02"
    assert first["url"].startswith("http://news.10jqka.com.cn/")
    # raw_url is the THS-specific bonus — that's the whole point of §1.2
    assert first["raw_url"].startswith("http://static.cninfo.com.cn/finalpage/")


def test_get_announcements_no_market_id_returns_empty(ths):
    """Codes not in _THS_MARKET_ID_MAP → []. No HTTP call."""
    with patch(
        "stock_data.data_provider.fetchers.ths_fetcher.json_get"
    ) as mocked:
        items = ths.get_announcements("400001", page_size=10)
    assert items == []
    mocked.assert_not_called()


def test_get_announcements_upstream_error_code_returns_empty(ths):
    """status_code != 0 → [], not raise."""
    with patch(
        "stock_data.data_provider.fetchers.ths_fetcher.json_get",
        return_value={"status_code": 1, "status_msg": "boom", "data": {}},
    ):
        items = ths.get_announcements("300740", page_size=5)
    assert items == []


def test_get_announcements_propagates_datafetcherror(ths):
    """Hard network failure raises DataFetchError (manager failover relies on this)."""
    with patch(
        "stock_data.data_provider.fetchers.ths_fetcher.json_get",
        side_effect=DataFetchError("HTTP 503"),
    ):
        with pytest.raises(DataFetchError):
            ths.get_announcements("600519", page_size=5)


def test_get_announcements_clamps_invalid_page_size(ths):
    """Non-int / out-of-range page_size → clamp to [1, 100] / fallback 30."""
    payload = _load("ths_basic_notice.json")
    for bad_input, expected in [
        ("abc", 30),
        (-3, 1),
        (9999, 100),
        (0, 1),
    ]:
        with patch(
            "stock_data.data_provider.fetchers.ths_fetcher.json_get",
            return_value=payload,
        ) as mocked:
            ths.get_announcements("300740", page_size=bad_input)
        assert mocked.call_args.kwargs["params"]["limit"] == expected
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ths_fetcher_get_announcements.py -v`
Expected: FAIL with `AttributeError: 'ThsFetcher' object has no attribute 'get_announcements'`.

- [ ] **Step 3: Add the `get_announcements` method**

In `stock_data/data_provider/fetchers/ths_fetcher.py`, immediately after the `get_stock_news` method added in Task 1:

```python
def get_announcements(self, code: str, page_size: int = 30) -> list[dict]:
    """THS 个股公告 via basic.10jqka.com.cn/basicapi/notice/pub.

    Returns dict shape compatible with CninfoFetcher.get_announcements:
      {title, type, date, url}; bonus field `raw_url` (cninfo PDF 直链).

    class 'type' field is the static classification list (业绩/重大事项/...)
    in upstream's `data.type` array — it's not per-record announcement type.
    Left as "" to match the existing schema's "type" semantics used by
    /stocks/{code}/announcements.

    Soft failures → return []. Hard failures → raise DataFetchError.
    """
    code = normalize_stock_code(code)
    market_id = _THS_MARKET_ID_MAP.get(code[:1])
    if not market_id:
        logger.warning(f"[ThsFetcher] get_announcements: no market_id for {code!r}")
        return []
    try:
        n = max(1, min(int(page_size), 100))
    except (TypeError, ValueError):
        n = 30
    payload = json_get(
        _THS_NOTICE_URL,
        params={
            "type": "stock",
            "code": code,
            "market": market_id,
            "classify": "all",
            "page": 1,
            "limit": n,
        },
        headers=_THS_BASIC_HEADERS,
        timeout=10,
    )
    if not isinstance(payload, dict) or payload.get("status_code") != 0:
        logger.warning(
            f"[ThsFetcher] get_announcements({code}) upstream "
            f"status_code={payload.get('status_code') if isinstance(payload, dict) else 'N/A'}"
        )
        return []
    rows = payload.get("data") or {}
    items = rows.get("data") if isinstance(rows, dict) else []
    out: list[dict] = []
    for r in items:
        url = r.get("pc_url") or r.get("mobile_url") or ""
        out.append({
            "title": str(r.get("title", "")),
            "type": "",
            "date": str(r.get("date", "")),
            "url": url,
            "raw_url": r.get("raw_url") or "",
        })
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ths_fetcher_get_announcements.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add stock_data/data_provider/fetchers/ths_fetcher.py tests/test_ths_fetcher_get_announcements.py
git commit -m "feat(ths): get_announcements via basic.10jqka.com.cn (P7 backup)"
```

---

## Task 3: Manager-level failover assertions (mocked)

**Files:**
- Create: `tests/test_manager_announcements_backup_ths.py`
- (Extends existing `tests/test_manager_stock_news.py` in Step 4 for stock news)

This task verifies the wiring at the manager level — the new fetcher methods actually show up as failover candidates in the right order.

- [ ] **Step 1: Write the failing test for the announcements failover path**

Create `tests/test_manager_announcements_backup_ths.py`:

```python
"""Tests for /stocks/{code}/announcements failover: EastMoney → Ths → Cninfo."""
from unittest.mock import patch

import pytest

from stock_data.data_provider.base import DataCapability, DataFetchError
from stock_data.data_provider.manager import create_default_manager


def _make_manager():
    return create_default_manager()


def test_ths_declares_announcement_capability():
    """ThsFetcher.supported_data_types must include ANNOUNCEMENT."""
    from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher
    assert DataCapability.ANNOUNCEMENT in ThsFetcher.supported_data_types


def test_announcement_priority_order_eastmoney_ths_cninfo():
    """Failover chain should be EastMoney(P6) → Ths(P7) → Cninfo(P8).

    List is sorted by priority ascending (lower = earlier). THS P7 must
    sit between EastMoney P6 and Cninfo P8.
    """
    mgr = _make_manager()
    candidates = mgr._filter_by_capability("csi", DataCapability.ANNOUNCEMENT)
    by_name = {f.name: f.priority for f in candidates}
    assert "ThsFetcher" in by_name, (
        f"ThsFetcher missing from ANNOUNCEMENT candidates: {list(by_name)}"
    )
    # Strict: EastMoney < Ths < Cninfo in priority number ordering
    if "EastMoneyFetcher" in by_name and "CninfoFetcher" in by_name:
        assert by_name["EastMoneyFetcher"] < by_name["ThsFetcher"] < by_name["CninfoFetcher"], (
            f"Priority order wrong: {by_name}"
        )


def test_get_announcements_falls_back_from_eastmoney_to_ths():
    """When EastMoney raises DataFetchError, manager should try Ths next."""
    mgr = _make_manager()
    fetchers = mgr._filter_by_capability("csi", DataCapability.ANNOUNCEMENT)
    by_name = {f.name: f for f in fetchers}
    if "EastMoneyFetcher" not in by_name or "ThsFetcher" not in by_name:
        pytest.skip("EastMoneyFetcher or ThsFetcher missing — env issue")
    eastmoney = by_name["EastMoneyFetcher"]
    ths = by_name["ThsFetcher"]
    fake_items = [{"title": "ths-t", "type": "", "date": "2026-07-02",
                   "url": "http://x", "raw_url": "http://pdf"}]
    with patch.object(eastmoney, "get_announcements",
                      side_effect=DataFetchError("EM down")), \
         patch.object(ths, "get_announcements", return_value=fake_items) as ths_patched:
        items, source = mgr.get_announcements("300740", page_size=10)
    assert items == fake_items
    assert source == "ThsFetcher"
    ths_patched.assert_called_once_with("300740", 10)


def test_get_announcements_falls_back_eastmoney_ths_then_cninfo():
    """Both EastMoney and Ths raising → Cninfo gets the call."""
    mgr = _make_manager()
    fetchers = mgr._filter_by_capability("csi", DataCapability.ANNOUNCEMENT)
    by_name = {f.name: f for f in fetchers}
    if not {"EastMoneyFetcher", "ThsFetcher", "CninfoFetcher"}.issubset(by_name):
        pytest.skip("Need all three fetchers in env")
    cninfo = by_name["CninfoFetcher"]
    fake_items = [{"title": "cninfo-t", "type": "公告", "date": "2026-07-02",
                   "url": "http://y"}]
    with patch.object(by_name["EastMoneyFetcher"], "get_announcements",
                      side_effect=DataFetchError("EM down")), \
         patch.object(by_name["ThsFetcher"], "get_announcements",
                      side_effect=DataFetchError("THS down")), \
         patch.object(cninfo, "get_announcements", return_value=fake_items) as cninfo_patched:
        items, source = mgr.get_announcements("300740", page_size=10)
    assert items == fake_items
    assert source == "CninfoFetcher"
    cninfo_patched.assert_called_once_with("300740", 10)
```

- [ ] **Step 2: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_manager_announcements_backup_ths.py -v`
Expected: all 4 tests pass.

> Note: this plan documents Steps 2 as "expected FAIL" in the skeleton template, but Tasks 1+2 already wired ThsFetcher. The "failing test first" TDD discipline was enforced *per method* in Tasks 1+2 (where each method genuinely did not exist yet); here in Task 3 we're verifying *integration* — the fetcher methods exist, the capability flag matches, the routing picks the right chain, the failover mocking works. If anything fails here, it indicates a wiring mismatch from Tasks 1+2 (e.g., `supported_data_types` not updated, or method signature mismatch). Fix and re-run before moving to Step 3.

- [ ] **Step 3: Add stock-news failover assertion to existing test file**

Append to `tests/test_manager_stock_news.py` (existing file, after the existing tests, before the EOF):

```python
def test_ths_declares_stock_news_capability():
    """ThsFetcher.supported_data_types must include STOCK_NEWS."""
    from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher
    assert DataCapability.STOCK_NEWS in ThsFetcher.supported_data_types


def test_get_stock_news_falls_back_from_eastmoney_to_ths():
    """EastMoney raises → manager falls through to Ths."""
    mgr = _make_manager()
    fetchers = mgr._filter_by_capability("csi", DataCapability.STOCK_NEWS)
    by_name = {f.name: f for f in fetchers}
    if "EastMoneyFetcher" not in by_name or "ThsFetcher" not in by_name:
        pytest.skip("EastMoneyFetcher or ThsFetcher missing")
    eastmoney = by_name["EastMoneyFetcher"]
    ths = by_name["ThsFetcher"]
    fake_items = [{"title": "ths-news", "url": "http://x", "publish_date": "2026-07-02",
                   "source_domain": "news.10jqka.com.cn", "media_name": ""}]
    with patch.object(eastmoney, "get_stock_news",
                      side_effect=DataFetchError("EM down")), \
         patch.object(ths, "get_stock_news", return_value=fake_items) as ths_patched:
        items, source = mgr.get_stock_news("300740", limit=10)
    assert items == fake_items
    assert source == "ThsFetcher"
    ths_patched.assert_called_once_with("300740", 10)
```

- [ ] **Step 4: Run both manager-level test files**

Run: `.venv/Scripts/python.exe -m pytest tests/test_manager_stock_news.py tests/test_manager_announcements_backup_ths.py -v`
Expected: all passed — confirms ThsFetcher is in both failover chains and serves items when EastMoney raises.

- [ ] **Step 5: Commit**

```bash
git add tests/test_manager_stock_news.py tests/test_manager_announcements_backup_ths.py
git commit -m "test(manager): Ths P7 backup for stock_news + announcements"
```

---

## Task 4: Schema `AnnouncementRecord.raw_url` field

**Files:**
- Modify: `stock_data/api/schemas.py:774-780` (the `AnnouncementRecord` class)

- [ ] **Step 1: Add the field**

Edit `stock_data/api/schemas.py` to change the existing class:

```python
class AnnouncementRecord(_UpstreamSanitizedModel):
    """公告记录"""

    title: str = Field(default="", description="标题")
    type: str = Field(default="", description="公告类型")
    date: str = Field(default="", description="发布日期")
    url: str = Field(default="", description="公告链接")
    # raw_url 上游仅 ThsFetcher (basic.10jqka.com.cn) 携带; 其他 fetcher 留空.
    # Pydantic v2 默认 extra='ignore': 老 fetcher dict 缺 raw_url → 用 "" 默认.
    raw_url: str = Field(default="", description="巨潮原文 PDF 直链 (ThsFetcher only)")
```

- [ ] **Step 2: Sanity-check the route can still build the model**

Run a one-liner:

```bash
.venv/Scripts/python.exe -c "
from stock_data.api.schemas import AnnouncementRecord
from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher
# Simulate what /stocks/{code}/announcements does
fake = {'title':'t','type':'','date':'2026-07-02','url':'http://x','raw_url':'http://p'}
m = AnnouncementRecord(**fake)
print(m.title, m.raw_url)

# Backward compat: dict WITHOUT raw_url (from EastMoney / Cninfo)
old = {'title':'t','type':'','date':'2026-07-02','url':'http://x'}
m2 = AnnouncementRecord(**old)
print('OLD raw_url:', repr(m2.raw_url))
"
```

Expected: prints `t http://p` on the first line, and `OLD raw_url: ''` on the second.

- [ ] **Step 3: Run schema-touching tests to confirm no regression**

Run: `.venv/Scripts/python.exe -m pytest tests/ -v -k "announcement or schema" --no-header -x`
Expected: all passed.

- [ ] **Step 4: Commit**

```bash
git add stock_data/api/schemas.py
git commit -m "feat(schemas): AnnouncementRecord.raw_url (cninfo PDF link, additive)"
```

---

## Task 5: Live network smoke test (optional, marked `live_network`)

**Files:**
- Create: `tests/test_ths_basic_endpoints_live.py`

This task is **optional** in the dev loop (default `pytest` skips `live_network`), but should exist so CI can smoke-test once per release. The user's rate-limit concern applies here — keep this test minimal.

- [ ] **Step 1: Write the test**

```python
"""Smoke test for ThsFetcher's basic.10jqka.com.cn endpoints.

Marked ``@pytest.mark.live_network`` — default ``pytest`` skips it
(addopts in pyproject.toml excludes live_network). Run with:
    .venv/Scripts/python.exe -m pytest -m live_network
    .venv/Scripts/python.exe -m pytest -m ""   # run everything
"""
import time

import pytest

from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher


@pytest.fixture(scope="module")
def ths() -> ThsFetcher:
    return ThsFetcher()


@pytest.mark.live_network
def test_ths_get_stock_news_smoke_300740(ths):
    """Single GET, 1-2 results expected. Sleep 2-3s to be polite."""
    items = ths.get_stock_news("300740", limit=5)
    assert isinstance(items, list)
    assert len(items) > 0, "Expected ≥1 news item for 300740"
    item = items[0]
    assert item["title"]
    assert item["url"].startswith("http")
    assert len(item["publish_date"]) == 10  # YYYY-MM-DD
    time.sleep(2.5)  # rate-limit politeness, even after a single request


@pytest.mark.live_network
def test_ths_get_announcements_smoke_300740(ths):
    """Same code, second endpoint. Sleep 2-3s between."""
    items = ths.get_announcements("300740", page_size=5)
    assert isinstance(items, list)
    assert len(items) > 0
    item = items[0]
    assert item["title"]
    assert item["url"].startswith("http")
    assert len(item["date"]) == 10
    # raw_url is the bonus — verify it's surfaced when present
    # (not all records carry it; just confirm the key exists with str type)
    assert isinstance(item.get("raw_url", ""), str)
```

- [ ] **Step 2: Verify it gets skipped under default `pytest`**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ths_basic_endpoints_live.py -v`
Expected: the two tests **deselected** (shown as `deselect` in output) because of `addopts = ["-m", "not live_network"]`.

- [ ] **Step 3: Commit (skipped tests still count as code)**

```bash
git add tests/test_ths_basic_endpoints_live.py
git commit -m "test(ths,live): smoke for basic.10jqka.com.cn endpoints (live_network marked)"
```

---

## Task 6: Final verification — full test sweep + linter

- [ ] **Step 1: Run full test suite (default, no live)**

Run: `.venv/Scripts/python.exe -m pytest`
Expected: green. Default `pytest` skips `live_network` so this stays fast (~1 min per CLAUDE.md).

- [ ] **Step 2: Lint**

Run: `ruff check stock_data/data_provider/fetchers/ths_fetcher.py tests/test_ths_fetcher_get_stock_news.py tests/test_ths_fetcher_get_announcements.py tests/test_manager_announcements_backup_ths.py stock_data/api/schemas.py`
Expected: 0 issues (fix any ruff complaints before continuing).

Run: `ruff format --check stock_data/data_provider/fetchers/ths_fetcher.py`
Expected: no diff. If format wants changes, run `ruff format` on the touched files and amend the relevant commit.

- [ ] **Step 3: Live smoke (manual, optional — verify on user's machine)**

Run: `.venv/Scripts/python.exe -m pytest -m live_network tests/test_ths_basic_endpoints_live.py -v`
Expected: 2 passed. If upstream is down, the `conftest.py::_network_guard` hook reclassifies to xfail (per `tests/_network_guard.py`).

- [ ] **Step 4: Final commit (if format amend)**

```bash
git add stock_data/data_provider/fetchers/ths_fetcher.py
git commit --amend --no-edit
```

---

## Self-Review Checklist (run before declaring done)

- [ ] All 5 tasks above land green
- [ ] `tests/test_capability_method_map.py::test_mapped_method_exists_on_base_or_subclass[STOCK_NEWS-get_stock_news]` is green
- [ ] `tests/test_capability_method_map.py::test_mapped_method_exists_on_base_or_subclass[ANNOUNCEMENT-get_announcements]` is green
- [ ] `ths_fetcher.py` module docstring lists STOCK_NEWS + ANNOUNCEMENT (Task 1 Step 3)
- [ ] `tests/fixtures/ths_basic_{news,notice}.json` referenced by Steps 1 of Tasks 1 + 2 actually exist on disk — yes (commit `78c48c4`)
- [ ] No file other than `ths_fetcher.py`, `schemas.py`, the 4 test files, and 0 fixture files was modified
- [ ] `raw_url` is on `AnnouncementRecord` (Task 4) but NOT on `StockNewsItem` (out of scope per spec §5)
