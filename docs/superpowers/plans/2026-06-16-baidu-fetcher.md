# BaiduFetcher (news search backup) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `BaiduFetcher` as a P7 backup source for `NEWS_SEARCH` capability, using the Baidu Qianfan Web Search API (`POST https://qianfan.baidubce.com/v2/ai_search/web_search`).

**Architecture:** New `BaiduFetcher` class implementing `BaseFetcher.search_news()` with Bearer-token auth via `BAIDU_API_KEY` env var. The existing `DataFetcherManager.search_news` already routes all `NEWS_SEARCH`-capable fetchers via `_with_failover`, so no manager/route/schema changes are needed — just register the new fetcher and add tests.

**Tech Stack:** Python 3.11+, `requests`, `urllib.parse`, FastAPI (existing), pytest, ruff. Tests mock `requests.post` (NOT `requests.get` — Baidu uses POST).

---

## File Structure

**New files:**
- `stock_data/data_provider/fetchers/baidu_fetcher.py` — the fetcher class (~200 lines)
- `tests/test_baidu_search_news.py` — fetcher unit tests (~250 lines)
- `tests/test_news_failover_to_baidu.py` — manager-level failover test (~50 lines)

**Modified files:**
- `stock_data/data_provider/__init__.py` — add `BaiduFetcher` export
- `stock_data/data_provider/manager.py` — register `BaiduFetcher` in `_register_default_fetchers`
- `.env.example` — add `BAIDU_API_KEY` comment block
- `stock_data/CLAUDE.md` — add BaiduFetcher section + capability row

**Untouched** (already in place per spec):
- `stock_data/data_provider/base.py` — `DataCapability.NEWS_SEARCH` + `CAPABILITY_TO_METHOD` already exist
- `stock_data/api/routes.py` — `/news/search` endpoint already wires `NEWS_SEARCH` → `manager.search_news`
- `stock_data/api/schemas.py` — `NewsItem` schema already has all 6 fields we map to
- `stock_data/data_provider/manager.py` (search_news method) — already uses `_with_failover(NEWS_SEARCH, "csi", ...)`

---

## Task 1: BaiduFetcher skeleton + availability gating

**Files:**
- Create: `tests/test_baidu_search_news.py`
- Create: `stock_data/data_provider/fetchers/baidu_fetcher.py`

- [ ] **Step 1: Write the failing tests for is_available + unavailable_reason**

Create `tests/test_baidu_search_news.py`:

```python
"""Unit tests for BaiduFetcher.search_news() and gating."""
import os
from unittest.mock import MagicMock, patch

import pytest

from stock_data.data_provider.base import DataFetchError
from stock_data.data_provider.fetchers.baidu_fetcher import BaiduFetcher


# ---------- Availability gating ----------

class TestIsAvailable:
    def test_returns_false_when_api_key_missing(self, monkeypatch):
        monkeypatch.delenv("BAIDU_API_KEY", raising=False)
        fetcher = BaiduFetcher()
        assert fetcher.is_available() is False

    def test_returns_false_when_api_key_empty_string(self, monkeypatch):
        monkeypatch.setenv("BAIDU_API_KEY", "   ")
        fetcher = BaiduFetcher()
        assert fetcher.is_available() is False

    def test_returns_true_when_api_key_set(self, monkeypatch):
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/ALTAK-xxx/yyy")
        fetcher = BaiduFetcher()
        assert fetcher.is_available() is True

    def test_priority_default_is_seven(self, monkeypatch):
        monkeypatch.delenv("BAIDU_PRIORITY", raising=False)
        assert BaiduFetcher.priority == 7

    def test_priority_overridable_via_env(self, monkeypatch):
        monkeypatch.setenv("BAIDU_PRIORITY", "5")
        # Re-import to pick up env var (class attr read at class body time)
        import importlib
        from stock_data.data_provider.fetchers import baidu_fetcher
        importlib.reload(baidu_fetcher)
        assert baidu_fetcher.BaiduFetcher.priority == 5

    def test_unavailable_reason_mentions_env_var(self, monkeypatch):
        monkeypatch.delenv("BAIDU_API_KEY", raising=False)
        fetcher = BaiduFetcher()
        reason = fetcher.unavailable_reason()
        assert reason is not None
        assert "BAIDU_API_KEY" in reason


# ---------- Base method stubs ----------

class TestKLineMethodsRaise:
    def test_fetch_raw_data_raises(self):
        fetcher = BaiduFetcher()
        with pytest.raises(DataFetchError, match="does not support historical K-line"):
            fetcher._fetch_raw_data("600519", "2025-01-01", "2025-01-31")

    def test_normalize_data_raises(self):
        fetcher = BaiduFetcher()
        with pytest.raises(DataFetchError, match="does not support historical K-line"):
            fetcher._normalize_data(MagicMock(), "600519")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_baidu_search_news.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'stock_data.data_provider.fetchers.baidu_fetcher'`

- [ ] **Step 3: Implement BaiduFetcher skeleton**

Create `stock_data/data_provider/fetchers/baidu_fetcher.py`:

```python
"""
Baidu Qianfan Web Search API fetcher — news search only.

Provides: NEWS_SEARCH (Baidu 千帆 v2 ai_search/web_search)

API: POST https://qianfan.baidubce.com/v2/ai_search/web_search
Auth: Authorization: Bearer <BAIDU_API_KEY>

Reference: https://cloud.baidu.com/doc/qianfan-api/s/Wmbq4z7e5
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date
from typing import Any
from urllib.parse import urlparse

import requests

from ..base import BaseFetcher, DataCapability, DataFetchError

logger = logging.getLogger(__name__)

WEB_SEARCH_URL = "https://qianfan.baidubce.com/v2/ai_search/web_search"
API_KEY_ENV = "BAIDU_API_KEY"

# Baidu upstream hard limit on resource_type_filter[].top_k
BAIDU_MAX_TOP_K = 50

# Cap on user-provided q length (matches EastMoneyFetcher convention)
MAX_Q_LEN = 200


class BaiduFetcher(BaseFetcher):
    """Baidu Qianfan Web Search API fetcher — news search only."""

    name = "BaiduFetcher"
    priority = int(os.getenv("BAIDU_PRIORITY", "7"))
    supported_markets: set[str] = {"csi"}
    supported_data_types = DataCapability.NEWS_SEARCH

    def is_available(self) -> bool:
        return bool(os.getenv(API_KEY_ENV, "").strip())

    def unavailable_reason(self) -> str | None:
        if self.is_available():
            return None
        return f"BaiduFetcher unavailable: {API_KEY_ENV} env var is empty"

    # K-line methods are not supported by Baidu Web Search API.
    def _fetch_raw_data(self, stock_code, start_date, end_date, frequency="d", adjust=None):
        raise DataFetchError("BaiduFetcher does not support historical K-line data")

    def _normalize_data(self, df, stock_code):
        raise DataFetchError("BaiduFetcher does not support historical K-line data")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_baidu_search_news.py::TestIsAvailable tests/test_baidu_search_news.py::TestKLineMethodsRaise -v`
Expected: PASS (all 8 tests)

- [ ] **Step 5: Commit**

```bash
git add stock_data/data_provider/fetchers/baidu_fetcher.py tests/test_baidu_search_news.py
git commit -m "feat(news): add BaiduFetcher skeleton with availability gating"
```

---

## Task 2: search_news — happy path with normalized output

**Files:**
- Modify: `tests/test_baidu_search_news.py`
- Modify: `stock_data/data_provider/fetchers/baidu_fetcher.py`

- [ ] **Step 1: Add the happy path test**

Append to `tests/test_baidu_search_news.py`:

```python
# ---------- Helpers ----------

def _mock_post_returning(payload: dict, status: int = 200):
    mock_response = MagicMock()
    mock_response.status_code = status
    mock_response.json.return_value = payload
    mock_response.text = json.dumps(payload)
    return mock_response


SAMPLE_BAIDU_RESPONSE = {
    "request_id": "ca749cb1-26db-4ff6-9735-f7b472d59003",
    "references": [
        {
            "id": 1,
            "title": "贵州茅台前三季度业绩超预期",
            "url": "https://www.example.com/news/maotai-q3.html",
            "content": "贵州茅台发布公告,前三季度营收同比增长...",
            "date": "2026-05-20 10:30:00",
            "type": "web",
            "web_anchor": "贵州茅台前三季度业绩超预期",
        },
        {
            "id": 2,
            "title": "白酒板块整体上涨",
            "url": "https://finance.sina.com.cn/2026/baijiu.html",
            "content": "今日白酒板块迎来普涨行情...",
            "date": "2026-05-19 16:00:00",
            "type": "web",
            "web_anchor": "白酒板块整体上涨",
        },
    ],
}


# ---------- Happy path ----------

class TestSearchNewsHappyPath:
    @patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post")
    def test_returns_normalized_dicts(self, mock_post, monkeypatch):
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")
        mock_post.return_value = _mock_post_returning(SAMPLE_BAIDU_RESPONSE)

        fetcher = BaiduFetcher()
        results = fetcher.search_news(q="贵州茅台", limit=20)

        assert len(results) == 2
        first = results[0]
        assert first["title"] == "贵州茅台前三季度业绩超预期"
        assert first["url"] == "https://www.example.com/news/maotai-q3.html"
        assert first["source_domain"] == "www.example.com"
        assert first["publish_date"] == "2026-05-20"
        assert first["snippet"] == "贵州茅台发布公告,前三季度营收同比增长..."
        assert first["media_name"] == "www.example.com"  # Baidu 没有 mediaName 字段

    @patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post")
    def test_uses_correct_endpoint(self, mock_post, monkeypatch):
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")
        mock_post.return_value = _mock_post_returning({"references": []})

        BaiduFetcher().search_news(q="test", limit=5)

        called_url = mock_post.call_args.args[0]
        assert called_url == "https://qianfan.baidubce.com/v2/ai_search/web_search"

    @patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post")
    def test_sends_bearer_authorization_header(self, mock_post, monkeypatch):
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/SECRET-XYZ")
        mock_post.return_value = _mock_post_returning({"references": []})

        BaiduFetcher().search_news(q="test", limit=5)

        headers = mock_post.call_args.kwargs["headers"]
        assert headers["Authorization"] == "Bearer bce-v3/SECRET-XYZ"
        assert headers["Content-Type"] == "application/json"

    @patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post")
    def test_empty_references_returns_empty_list(self, mock_post, monkeypatch):
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")
        mock_post.return_value = _mock_post_returning({"request_id": "abc", "references": []})

        results = BaiduFetcher().search_news(q="nothing-here", limit=20)
        assert results == []

    @patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post")
    def test_missing_references_key_returns_empty_list(self, mock_post, monkeypatch):
        """Upstream may omit references on success — treat as empty, not error."""
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")
        mock_post.return_value = _mock_post_returning({"request_id": "abc"})

        results = BaiduFetcher().search_news(q="test", limit=20)
        assert results == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_baidu_search_news.py::TestSearchNewsHappyPath -v`
Expected: FAIL — `AttributeError: 'BaiduFetcher' object has no attribute 'search_news'`

- [ ] **Step 3: Implement search_news**

Append to `stock_data/data_provider/fetchers/baidu_fetcher.py`:

```python
    def search_news(
        self,
        q: str,
        from_date: str | None = None,
        to_date: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """Search Baidu news by keyword.

        Returns a list of normalized news-item dicts matching the NewsItem schema.
        Raises DataFetchError on upstream failure.
        """
        # ---- input validation ----
        if not q or len(q) > MAX_Q_LEN:
            raise DataFetchError(
                f"[BaiduFetcher] search_news: invalid q (len={len(q) if q else 0})"
            )
        try:
            limit = int(limit)
        except (TypeError, ValueError) as e:
            raise DataFetchError(
                f"[BaiduFetcher] search_news: limit must be an integer 1..100 (got {limit!r})"
            ) from e
        if not (1 <= limit <= 100):
            raise DataFetchError(
                f"[BaiduFetcher] search_news: limit must be 1..100 (got {limit})"
            )

        # ---- request ----
        api_key = os.getenv(API_KEY_ENV, "").strip()
        if not api_key:
            raise DataFetchError(f"[BaiduFetcher] search_news: {API_KEY_ENV} not set")

        body: dict[str, Any] = {
            "messages": [{"content": q, "role": "user"}],
            "search_source": "baidu_search_v2",
            "resource_type_filter": [
                {"type": "web", "top_k": min(limit, BAIDU_MAX_TOP_K)},
            ],
        }
        recency = _derive_recency(from_date)
        if recency:
            body["search_recency_filter"] = recency

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        logger.info(f"[BaiduFetcher] news search q={q!r} limit={limit}")
        try:
            resp = requests.post(WEB_SEARCH_URL, headers=headers, json=body, timeout=15)
        except Exception as e:
            raise DataFetchError(f"[BaiduFetcher] search_news network error: {e}") from e

        if not (200 <= resp.status_code < 300):
            raise DataFetchError(
                f"[BaiduFetcher] search_news HTTP {resp.status_code}"
            )

        try:
            payload = resp.json()
        except (ValueError, json.JSONDecodeError) as e:
            raise DataFetchError(f"[BaiduFetcher] search_news: bad JSON: {e}") from e

        # Baidu returns code/message only on errors; absence means success.
        if "code" in payload and payload["code"] not in (0, None, "0"):
            raise DataFetchError(
                f"[BaiduFetcher] search_news API code={payload['code']} msg={payload.get('message')}"
            )

        records = payload.get("references") or []
        out: list[dict] = []
        for rec in records:
            try:
                item = self._normalize_news_item(rec)
            except (KeyError, TypeError, ValueError) as e:
                logger.warning(f"[BaiduFetcher] skipping malformed record: {e}")
                continue
            if from_date and item["publish_date"] < from_date:
                continue
            if to_date and item["publish_date"] > to_date:
                continue
            out.append(item)
        return out

    @staticmethod
    def _normalize_news_item(rec: dict) -> dict:
        """Convert one upstream reference to the NewsItem dict schema.

        Raises KeyError/TypeError on missing critical fields; caller treats
        as a skip.
        """
        url = rec["url"]
        date_str = rec["date"][:10]
        domain = urlparse(url).netloc
        return {
            "title": rec["title"],
            "url": url,
            "source_domain": domain,
            "publish_date": date_str,
            "snippet": rec.get("content", ""),
            "media_name": domain,  # Baidu 没有专门的 mediaName 字段
        }


def _derive_recency(from_date: str | None) -> str | None:
    """Map from_date (YYYY-MM-DD) to Baidu search_recency_filter enum.

    Returns None if from_date is None or unparseable (Baidu then returns
    default recency — no client filter).
    """
    if not from_date:
        return None
    try:
        days = (date.today() - date.fromisoformat(from_date)).days
    except ValueError:
        return None
    if days <= 7:
        return "week"
    if days <= 30:
        return "month"
    if days <= 180:
        return "semiyear"
    return "year"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_baidu_search_news.py::TestSearchNewsHappyPath -v`
Expected: PASS (all 5 tests)

- [ ] **Step 5: Commit**

```bash
git add stock_data/data_provider/fetchers/baidu_fetcher.py tests/test_baidu_search_news.py
git commit -m "feat(news): BaiduFetcher.search_news happy path + endpoint/auth wiring"
```

---

## Task 3: search_news — request body shape (messages / top_k / recency)

**Files:**
- Modify: `tests/test_baidu_search_news.py`

- [ ] **Step 1: Add tests for request body fields**

Append to `tests/test_baidu_search_news.py`:

```python
class TestSearchNewsRequestBody:
    @patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post")
    def test_body_has_messages_with_role_user(self, mock_post, monkeypatch):
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")
        mock_post.return_value = _mock_post_returning({"references": []})

        BaiduFetcher().search_news(q="贵州茅台", limit=20)

        body = mock_post.call_args.kwargs["json"]
        assert body["messages"] == [{"content": "贵州茅台", "role": "user"}]

    @patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post")
    def test_body_has_search_source_baidu_search_v2(self, mock_post, monkeypatch):
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")
        mock_post.return_value = _mock_post_returning({"references": []})

        BaiduFetcher().search_news(q="test", limit=10)

        body = mock_post.call_args.kwargs["json"]
        assert body["search_source"] == "baidu_search_v2"

    @patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post")
    def test_body_has_resource_type_filter_web_with_top_k(self, mock_post, monkeypatch):
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")
        mock_post.return_value = _mock_post_returning({"references": []})

        BaiduFetcher().search_news(q="test", limit=15)

        body = mock_post.call_args.kwargs["json"]
        assert body["resource_type_filter"] == [{"type": "web", "top_k": 15}]

    @patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post")
    def test_top_k_clamped_to_50_when_limit_exceeds(self, mock_post, monkeypatch):
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")
        mock_post.return_value = _mock_post_returning({"references": []})

        BaiduFetcher().search_news(q="test", limit=100)

        body = mock_post.call_args.kwargs["json"]
        assert body["resource_type_filter"] == [{"type": "web", "top_k": 50}]

    @patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post")
    def test_top_k_passes_through_when_under_50(self, mock_post, monkeypatch):
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")
        mock_post.return_value = _mock_post_returning({"references": []})

        BaiduFetcher().search_news(q="test", limit=20)

        body = mock_post.call_args.kwargs["json"]
        assert body["resource_type_filter"][0]["top_k"] == 20

    @patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post")
    def test_no_recency_filter_when_from_date_none(self, mock_post, monkeypatch):
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")
        mock_post.return_value = _mock_post_returning({"references": []})

        BaiduFetcher().search_news(q="test", limit=10)

        body = mock_post.call_args.kwargs["json"]
        assert "search_recency_filter" not in body

    @patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post")
    def test_recency_filter_week_for_recent_from_date(self, mock_post, monkeypatch):
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")
        mock_post.return_value = _mock_post_returning({"references": []})

        # from_date 3 days ago → "week"
        from datetime import date, timedelta
        recent = (date.today() - timedelta(days=3)).isoformat()
        BaiduFetcher().search_news(q="test", limit=10, from_date=recent)

        body = mock_post.call_args.kwargs["json"]
        assert body["search_recency_filter"] == "week"

    @patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post")
    def test_recency_filter_year_for_old_from_date(self, mock_post, monkeypatch):
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")
        mock_post.return_value = _mock_post_returning({"references": []})

        from datetime import date, timedelta
        old = (date.today() - timedelta(days=365)).isoformat()
        BaiduFetcher().search_news(q="test", limit=10, from_date=old)

        body = mock_post.call_args.kwargs["json"]
        assert body["search_recency_filter"] == "year"

    @patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post")
    def test_recency_filter_month_for_30_days(self, mock_post, monkeypatch):
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")
        mock_post.return_value = _mock_post_returning({"references": []})

        from datetime import date, timedelta
        thirty = (date.today() - timedelta(days=30)).isoformat()
        BaiduFetcher().search_news(q="test", limit=10, from_date=thirty)

        body = mock_post.call_args.kwargs["json"]
        assert body["search_recency_filter"] == "month"

    @patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post")
    def test_recency_filter_semiyear_for_180_days(self, mock_post, monkeypatch):
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")
        mock_post.return_value = _mock_post_returning({"references": []})

        from datetime import date, timedelta
        one_eighty = (date.today() - timedelta(days=180)).isoformat()
        BaiduFetcher().search_news(q="test", limit=10, from_date=one_eighty)

        body = mock_post.call_args.kwargs["json"]
        assert body["search_recency_filter"] == "semiyear"
```

- [ ] **Step 2: Run tests to verify they pass (no impl change needed)**

Run: `.venv/Scripts/python.exe -m pytest tests/test_baidu_search_news.py::TestSearchNewsRequestBody -v`
Expected: PASS (all 10 tests — Task 2 implementation already has the right shape)

- [ ] **Step 3: Commit**

```bash
git add tests/test_baidu_search_news.py
git commit -m "test(news): lock BaiduFetcher request body shape (top_k, recency, messages)"
```

---

## Task 4: search_news — input validation

**Files:**
- Modify: `tests/test_baidu_search_news.py`

- [ ] **Step 1: Add validation tests**

Append to `tests/test_baidu_search_news.py`:

```python
class TestSearchNewsValidation:
    def test_empty_q_raises(self):
        fetcher = BaiduFetcher()
        with pytest.raises(DataFetchError, match="invalid q"):
            fetcher.search_news(q="", limit=10)

    def test_q_too_long_raises(self):
        fetcher = BaiduFetcher()
        with pytest.raises(DataFetchError, match="invalid q"):
            fetcher.search_news(q="x" * 201, limit=10)

    def test_q_exactly_200_chars_ok(self, monkeypatch):
        """200 is the documented max — must be accepted (boundary)."""
        from unittest.mock import patch
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")
        with patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post") as mock_post:
            mock_post.return_value = _mock_post_returning({"references": []})
            fetcher = BaiduFetcher()
            # Should NOT raise
            fetcher.search_news(q="x" * 200, limit=10)

    def test_limit_zero_raises(self):
        fetcher = BaiduFetcher()
        with pytest.raises(DataFetchError, match="limit must be 1..100"):
            fetcher.search_news(q="ok", limit=0)

    def test_limit_too_large_raises(self):
        fetcher = BaiduFetcher()
        with pytest.raises(DataFetchError, match="limit must be 1..100"):
            fetcher.search_news(q="ok", limit=101)

    def test_limit_negative_raises(self):
        fetcher = BaiduFetcher()
        with pytest.raises(DataFetchError, match="limit must be 1..100"):
            fetcher.search_news(q="ok", limit=-1)

    def test_limit_as_string_coerced(self, monkeypatch):
        """Explorer mini-form sends HTML input values as strings."""
        from unittest.mock import patch
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")
        with patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post") as mock_post:
            mock_post.return_value = _mock_post_returning({"references": []})
            fetcher = BaiduFetcher()
            results = fetcher.search_news(q="ok", limit="20")
            assert results == []
            body = mock_post.call_args.kwargs["json"]
            assert body["resource_type_filter"][0]["top_k"] == 20

    def test_limit_non_numeric_string_raises(self):
        fetcher = BaiduFetcher()
        with pytest.raises(DataFetchError, match="limit must be an integer"):
            fetcher.search_news(q="ok", limit="abc")

    def test_limit_none_raises(self):
        fetcher = BaiduFetcher()
        with pytest.raises(DataFetchError, match="limit must be an integer"):
            fetcher.search_news(q="ok", limit=None)
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_baidu_search_news.py::TestSearchNewsValidation -v`
Expected: PASS (all 9 tests — Task 2 implementation already validates input)

- [ ] **Step 3: Commit**

```bash
git add tests/test_baidu_search_news.py
git commit -m "test(news): lock BaiduFetcher input validation contract"
```

---

## Task 5: search_news — error handling

**Files:**
- Modify: `tests/test_baidu_search_news.py`

- [ ] **Step 1: Add error handling tests**

Append to `tests/test_baidu_search_news.py`:

```python
class TestSearchNewsErrors:
    @patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post")
    def test_http_500_raises(self, mock_post, monkeypatch):
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")
        mock_post.return_value = _mock_post_returning({}, status=500)
        with pytest.raises(DataFetchError, match="HTTP 500"):
            BaiduFetcher().search_news(q="ok", limit=10)

    @patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post")
    def test_http_401_unauthorized_raises(self, mock_post, monkeypatch):
        """Bad API key surfaces as DataFetchError so manager tries next fetcher."""
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/INVALID")
        mock_post.return_value = _mock_post_returning({"error": "invalid token"}, status=401)
        with pytest.raises(DataFetchError, match="HTTP 401"):
            BaiduFetcher().search_news(q="ok", limit=10)

    @patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post")
    def test_http_429_rate_limited_raises(self, mock_post, monkeypatch):
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")
        mock_post.return_value = _mock_post_returning({}, status=429)
        with pytest.raises(DataFetchError, match="HTTP 429"):
            BaiduFetcher().search_news(q="ok", limit=10)

    @patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post")
    def test_bad_json_raises(self, mock_post, monkeypatch):
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = ValueError("not json")
        mock_response.text = "not json"
        mock_post.return_value = mock_response
        with pytest.raises(DataFetchError, match="bad JSON"):
            BaiduFetcher().search_news(q="ok", limit=10)

    @patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post")
    def test_baidu_api_code_nonzero_raises(self, mock_post, monkeypatch):
        """Baidu's error envelope: {"code": 401, "message": "..."}."""
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")
        payload = {"code": 401, "message": "invalid api key", "request_id": "abc"}
        mock_post.return_value = _mock_post_returning(payload, status=200)
        with pytest.raises(DataFetchError, match="code=401"):
            BaiduFetcher().search_news(q="ok", limit=10)

    @patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post")
    def test_baidu_api_code_zero_string_ok(self, mock_post, monkeypatch):
        """Some Baidu variants return code as string \"0\" — treat as success."""
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")
        payload = {"code": "0", "references": [], "request_id": "abc"}
        mock_post.return_value = _mock_post_returning(payload, status=200)
        results = BaiduFetcher().search_news(q="ok", limit=10)
        assert results == []

    @patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post")
    def test_network_error_raises(self, mock_post, monkeypatch):
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")
        mock_post.side_effect = requests.ConnectionError("dns fail")
        with pytest.raises(DataFetchError, match="network error"):
            BaiduFetcher().search_news(q="ok", limit=10)

    @patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post")
    def test_records_missing_critical_fields_skipped(self, mock_post, monkeypatch):
        """3 records: complete, missing url, missing date, missing title."""
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")
        payload = {
            "references": [
                {
                    "title": "valid",
                    "url": "https://a.com/1.html",
                    "content": "snippet",
                    "date": "2026-05-20 10:00:00",
                },
                {
                    "title": "missing url",
                    "content": "snippet",
                    "date": "2026-05-20 10:00:00",
                },
                {
                    "title": "missing date",
                    "url": "https://a.com/3.html",
                    "content": "snippet",
                },
                {
                    "url": "https://a.com/4.html",
                    "content": "snippet",
                    "date": "2026-05-20 10:00:00",
                    # missing title
                },
            ]
        }
        mock_post.return_value = _mock_post_returning(payload)

        results = BaiduFetcher().search_news(q="ok", limit=10)
        assert len(results) == 1
        assert results[0]["title"] == "valid"
```

(Note: add `import requests` to the top of the file if not already there — it should already be at the top with `from unittest.mock import ...`.)

- [ ] **Step 2: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_baidu_search_news.py::TestSearchNewsErrors -v`
Expected: PASS (all 8 tests — Task 2 implementation already handles these)

If `test_baidu_api_code_zero_string_ok` fails because the implementation only treats numeric 0 as success, update the code line:
```python
if "code" in payload and payload["code"] not in (0, None, "0"):
```
(This is already what Task 2 implements — should be fine.)

If `test_network_error_raises` fails because `requests.ConnectionError` isn't a subclass of `Exception`, check the import:
```python
import requests
```
at the top of `baidu_fetcher.py` is required. Task 2 already includes it.

- [ ] **Step 3: Commit**

```bash
git add tests/test_baidu_search_news.py
git commit -m "test(news): lock BaiduFetcher error handling contract"
```

---

## Task 6: search_news — date post-filter

**Files:**
- Modify: `tests/test_baidu_search_news.py`

- [ ] **Step 1: Add date filter tests**

Append to `tests/test_baidu_search_news.py`:

```python
class TestSearchNewsDateFilter:
    @patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post")
    def test_from_date_filters_out_older_records(self, mock_post, monkeypatch):
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")
        payload = {
            "references": [
                {
                    "title": "new",
                    "url": "https://a.com/1.html",
                    "content": "snippet",
                    "date": "2026-06-09 10:00:00",
                },
                {
                    "title": "old",
                    "url": "https://a.com/2.html",
                    "content": "snippet",
                    "date": "2026-04-29 10:00:00",
                },
            ]
        }
        mock_post.return_value = _mock_post_returning(payload)

        results = BaiduFetcher().search_news(q="ok", limit=10, from_date="2026-05-01")
        assert len(results) == 1
        assert results[0]["title"] == "new"

    @patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post")
    def test_to_date_filters_out_newer_records(self, mock_post, monkeypatch):
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")
        payload = {
            "references": [
                {
                    "title": "new",
                    "url": "https://a.com/1.html",
                    "content": "snippet",
                    "date": "2026-06-09 10:00:00",
                },
                {
                    "title": "old",
                    "url": "https://a.com/2.html",
                    "content": "snippet",
                    "date": "2026-04-29 10:00:00",
                },
            ]
        }
        mock_post.return_value = _mock_post_returning(payload)

        results = BaiduFetcher().search_news(q="ok", limit=10, to_date="2026-05-01")
        assert len(results) == 1
        assert results[0]["title"] == "old"

    @patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post")
    def test_from_and_to_date_range(self, mock_post, monkeypatch):
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")
        payload = {
            "references": [
                {
                    "title": "in_range",
                    "url": "https://a.com/1.html",
                    "content": "snippet",
                    "date": "2026-05-20 10:00:00",
                },
                {
                    "title": "before",
                    "url": "https://a.com/2.html",
                    "content": "snippet",
                    "date": "2026-04-29 10:00:00",
                },
                {
                    "title": "after",
                    "url": "https://a.com/3.html",
                    "content": "snippet",
                    "date": "2026-06-09 10:00:00",
                },
            ]
        }
        mock_post.return_value = _mock_post_returning(payload)

        results = BaiduFetcher().search_news(
            q="ok", limit=10, from_date="2026-05-01", to_date="2026-05-31"
        )
        assert len(results) == 1
        assert results[0]["title"] == "in_range"

    @patch("stock_data.data_provider.fetchers.baidu_fetcher.requests.post")
    def test_no_date_filter_returns_all(self, mock_post, monkeypatch):
        monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")
        mock_post.return_value = _mock_post_returning(SAMPLE_BAIDU_RESPONSE)
        results = BaiduFetcher().search_news(q="ok", limit=10)
        assert len(results) == 2
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_baidu_search_news.py::TestSearchNewsDateFilter -v`
Expected: PASS (all 4 tests — Task 2 implementation already does client-side filter)

- [ ] **Step 3: Commit**

```bash
git add tests/test_baidu_search_news.py
git commit -m "test(news): lock BaiduFetcher client-side date filter contract"
```

---

## Task 7: Register BaiduFetcher in data_provider package

**Files:**
- Modify: `stock_data/data_provider/__init__.py`

- [ ] **Step 1: Read current exports section**

Run: Read `stock_data/data_provider/__init__.py` lines 28-45 to confirm current export layout.

- [ ] **Step 2: Add BaiduFetcher export**

In `stock_data/data_provider/__init__.py`, in the `from .fetchers.*_fetcher import ...` block (around line 32-39), add `BaiduFetcher` in alphabetical order — between `AkshareFetcher` (line ~33, in package form) and `CninfoFetcher`. Since alphabetical with uppercase letters: BaiduFetcher comes after AkshareFetcher.

```python
from .fetchers.baidu_fetcher import BaiduFetcher
```

(Insert as a new line after the `AkshareFetcher` import.)

Also add to the `__all__` list (around line 100-105, after `"AkshareFetcher",`):

```python
    "BaiduFetcher",
```

- [ ] **Step 3: Verify import works**

Run: `.venv/Scripts/python.exe -c "from stock_data.data_provider import BaiduFetcher; print(BaiduFetcher.name)"`
Expected output: `BaiduFetcher`

- [ ] **Step 4: Run existing tests to confirm no regressions**

Run: `.venv/Scripts/python.exe -m pytest tests/test_eastmoney_search_news.py tests/test_news_endpoints.py -v`
Expected: PASS (no regressions — adding a new import doesn't break existing code)

- [ ] **Step 5: Commit**

```bash
git add stock_data/data_provider/__init__.py
git commit -m "feat(news): export BaiduFetcher from data_provider package"
```

---

## Task 8: Register BaiduFetcher in manager.py

**Files:**
- Modify: `stock_data/data_provider/manager.py`

- [ ] **Step 1: Add BaiduFetcher to the registration list**

In `stock_data/data_provider/manager.py`, in `_register_default_fetchers` (line ~720-758):

After the `from .fetchers.akshare import AkshareFetcher` import block (lines 727-736), add:

```python
    from .fetchers.baidu_fetcher import BaiduFetcher
```

Then in the `fetcher_classes = [...]` list (lines 739-750), add `BaiduFetcher` after `EastMoneyFetcher` (since P7 comes after P6 EastMoneyFetcher):

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
            BaiduFetcher,       # NEW — P7 news search backup
            ThsFetcher,
            CninfoFetcher,
        ]
```

- [ ] **Step 2: Verify registration via a smoke test**

Run: `.venv/Scripts/python.exe -c "
import os
os.environ['BAIDU_API_KEY'] = 'bce-v3/TESTKEY'
from stock_data.data_provider.manager import create_default_manager
m = create_default_manager()
names = [f.name for f in m.fetchers]
print('BaiduFetcher in registered:', 'BaiduFetcher' in names)
print('EastMoneyFetcher in registered:', 'EastMoneyFetcher' in names)
print('All:', names)
"
`
Expected output (truncated):
```
BaiduFetcher in registered: True
EastMoneyFetcher in registered: True
All: [..., 'EastMoneyFetcher', 'BaiduFetcher', 'ThsFetcher', ...]
```

- [ ] **Step 3: Run existing news tests for regression**

Run: `.venv/Scripts/python.exe -m pytest tests/test_manager_news_search.py tests/test_news_endpoints.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add stock_data/data_provider/manager.py
git commit -m "feat(news): register BaiduFetcher (P7) in default manager"
```

---

## Task 9: Add BAIDU_API_KEY to .env.example

**Files:**
- Modify: `.env.example`

- [ ] **Step 1: Insert the Baidu section**

In `.env.example`, after the `MYQUANT_PRIORITY` line (around line 27), add:

```bash
# === Baidu Qianfan (Priority 7 for news search backup, requires API Key) ===
# Get your API Key from: https://console.bce.baidu.com/qianfan/ais/console/apiKey
# Format: bce-v3/ALTAK-xxx/xxx
BAIDU_API_KEY=
# BAIDU_PRIORITY=7
```

- [ ] **Step 2: Verify .env already has BAIDU_API_KEY**

Run: `grep BAIDU_API_KEY .env`
Expected: at least one line containing `BAIDU_API_KEY` (the user's `.env` already has it — `.env.example` should mirror the structure).

If `.env` is missing it, add the same block to `.env` too (the user's version uses `BAIDU_API_KEY = bce-v3/ALTAK-...` with spaces around `=`, but our parser tolerates that).

- [ ] **Step 3: Commit**

```bash
git add .env.example
git commit -m "docs(config): document BAIDU_API_KEY and BAIDU_PRIORITY"
```

---

## Task 10: Update CLAUDE.md

**Files:**
- Modify: `stock_data/CLAUDE.md`

- [ ] **Step 1: Add BaiduFetcher capability row**

In `stock_data/CLAUDE.md`, find the "Fetcher capability declarations" table. Add a new row after the `TencentFetcher` row (or in alphabetical order):

```
| BaiduFetcher | `NEWS_SEARCH` |
```

- [ ] **Step 2: Add BaiduFetcher section after EastMoneyFetcher section**

In `stock_data/CLAUDE.md`, find the `### EastMoneyFetcher` section and add after it:

```markdown
### BaiduFetcher (Priority 7, news search backup, A股 only, Requires API Key)

**API**: `POST https://qianfan.baidubce.com/v2/ai_search/web_search`

**Authentication**: `Authorization: Bearer <API Key>` (token read from `BAIDU_API_KEY` env var)

**Supported capability**: `NEWS_SEARCH` only — no K-line / quote / financial data. Functions as backup source when `EastMoneyFetcher.search_news` fails (saves Baidu's 1500/month free quota).

**Request body**:
```json
{
  "messages": [{"content": "query", "role": "user"}],
  "search_source": "baidu_search_v2",
  "resource_type_filter": [{"type": "web", "top_k": 20}],
  "search_recency_filter": "year"
}
```

**Response field**: `references[].{title, url, content, date, type, web_anchor}`

**Pricing**: 1500 calls/month free (released daily), then pay-as-you-go.

**Limitation**: `top_k` hard cap is 50; user-facing `limit` accepts 1..100 but is clamped internally to 50.

**Links**: https://cloud.baidu.com/doc/qianfan-api/s/Wmbq4z7e5
```

- [ ] **Step 3: Verify the diff is sensible**

Run: `git diff stock_data/CLAUDE.md | head -80`
Expected: shows the new row and section, no accidental damage to surrounding content.

- [ ] **Step 4: Commit**

```bash
git add stock_data/CLAUDE.md
git commit -m "docs(CLAUDE): document BaiduFetcher (P7 news search backup)"
```

---

## Task 11: Manager failover integration test

**Files:**
- Create: `tests/test_news_failover_to_baidu.py`

- [ ] **Step 1: Write the failover test**

Create `tests/test_news_failover_to_baidu.py`:

```python
"""Manager-level failover test: when EastMoney raises, manager tries Baidu."""
from unittest.mock import MagicMock, patch

import pytest

from stock_data.data_provider.base import DataFetchError


def _baidu_payload():
    return {
        "request_id": "abc",
        "references": [
            {
                "title": "from baidu",
                "url": "https://baidu.example.com/1.html",
                "content": "snippet",
                "date": "2026-05-20 10:00:00",
            }
        ],
    }


def _mock_post(payload, status=200):
    mock = MagicMock()
    mock.status_code = status
    mock.json.return_value = payload
    mock.text = str(payload)
    return mock


def test_eastmoney_failover_to_baidu(monkeypatch):
    """If EastMoney raises DataFetchError, manager.search_news falls back to BaiduFetcher."""
    monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")

    # EastMoney raises on every search_news call
    with patch(
        "stock_data.data_provider.fetchers.eastmoney_fetcher.EastMoneyFetcher.search_news",
        side_effect=DataFetchError("[EastMoneyFetcher] simulated failure"),
    ):
        # Baidu returns a normal payload
        with patch(
            "stock_data.data_provider.fetchers.baidu_fetcher.requests.post",
            return_value=_mock_post(_baidu_payload()),
        ):
            # Build a manager with both fetchers
            from stock_data.data_provider import BaiduFetcher, EastMoneyFetcher
            from stock_data.data_provider.manager import DataFetcherManager

            mgr = DataFetcherManager()
            mgr.add_fetcher(EastMoneyFetcher())
            mgr.add_fetcher(BaiduFetcher())

            items, source = mgr.search_news(q="贵州茅台", limit=10)

    assert source == "BaiduFetcher"
    assert len(items) == 1
    assert items[0]["title"] == "from baidu"


def test_eastmoney_success_does_not_invoke_baidu(monkeypatch):
    """If EastMoney returns successfully, Baidu is never called."""
    monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")

    eastmoney_items = [
        {
            "title": "from eastmoney",
            "url": "http://finance.eastmoney.com/a/1.html",
            "source_domain": "finance.eastmoney.com",
            "publish_date": "2026-05-20",
            "snippet": "snippet",
            "media_name": "证券时报网",
        }
    ]
    with patch(
        "stock_data.data_provider.fetchers.eastmoney_fetcher.EastMoneyFetcher.search_news",
        return_value=eastmoney_items,
    ) as em_mock:
        with patch(
            "stock_data.data_provider.fetchers.baidu_fetcher.requests.post"
        ) as baidu_mock:
            from stock_data.data_provider import BaiduFetcher, EastMoneyFetcher
            from stock_data.data_provider.manager import DataFetcherManager

            mgr = DataFetcherManager()
            mgr.add_fetcher(EastMoneyFetcher())
            mgr.add_fetcher(BaiduFetcher())

            items, source = mgr.search_news(q="贵州茅台", limit=10)

    assert source == "EastMoneyFetcher"
    assert items[0]["title"] == "from eastmoney"
    em_mock.assert_called_once()
    baidu_mock.assert_not_called()


def test_both_fail_yields_data_fetch_error(monkeypatch):
    """If both fetchers fail, manager raises DataFetchError."""
    monkeypatch.setenv("BAIDU_API_KEY", "bce-v3/TESTKEY")

    with patch(
        "stock_data.data_provider.fetchers.eastmoney_fetcher.EastMoneyFetcher.search_news",
        side_effect=DataFetchError("em fail"),
    ):
        with patch(
            "stock_data.data_provider.fetchers.baidu_fetcher.requests.post",
            side_effect=Exception("network"),
        ):
            from stock_data.data_provider import BaiduFetcher, EastMoneyFetcher
            from stock_data.data_provider.manager import DataFetcherManager

            mgr = DataFetcherManager()
            mgr.add_fetcher(EastMoneyFetcher())
            mgr.add_fetcher(BaiduFetcher())

            with pytest.raises(DataFetchError):
                mgr.search_news(q="贵州茅台", limit=10)
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_news_failover_to_baidu.py -v`
Expected: PASS (all 3 tests)

If `test_eastmoney_failover_to_baidu` fails with `KeyError: 'EastMoneyFetcher'`, it means `manager._fetchers_by_name` wasn't refreshed. Check that `add_fetcher` calls `_refresh_index()` (already does in `manager.py:67`).

- [ ] **Step 3: Commit**

```bash
git add tests/test_news_failover_to_baidu.py
git commit -m "test(news): lock EastMoney → Baidu failover contract"
```

---

## Task 12: Final cleanup — lint, format, full news test suite

**Files:** (none modified; this task only validates)

- [ ] **Step 1: Run ruff check on touched files**

Run: `.venv/Scripts/python.exe -m ruff check stock_data/data_provider/fetchers/baidu_fetcher.py tests/test_baidu_search_news.py tests/test_news_failover_to_baidu.py`
Expected: 0 errors. If errors, fix them inline (likely import order, unused vars, or line length).

- [ ] **Step 2: Run ruff format on touched files**

Run: `.venv/Scripts/python.exe -m ruff format stock_data/data_provider/fetchers/baidu_fetcher.py tests/test_baidu_search_news.py tests/test_news_failover_to_baidu.py`
Expected: file(s) unchanged or auto-formatted.

- [ ] **Step 3: Run the full news test suite**

Run: `.venv/Scripts/python.exe -m pytest tests/test_baidu_search_news.py tests/test_news_failover_to_baidu.py tests/test_eastmoney_search_news.py tests/test_manager_news_search.py tests/test_news_endpoints.py tests/test_news_content_extractor.py tests/test_news_content_ssrf.py -v`
Expected: ALL PASS

- [ ] **Step 4: Run capability-method-map test (validates no broken capabilities)**

Run: `.venv/Scripts/python.exe -m pytest tests/test_capability_method_map.py -v`
Expected: PASS — BaiduFetcher implements `search_news` which the map already expects.

- [ ] **Step 5: Run a quick smoke check via the live API (manual)**

(Optional — requires `BAIDU_API_KEY` set in `.env` and network.)

Run: `.venv/Scripts/python.exe -c "
import os
os.environ['BAIDU_API_KEY'] = open('.env').read().split('BAIDU_API_KEY=')[1].split()[0]
from stock_data.data_provider import BaiduFetcher
f = BaiduFetcher()
items = f.search_news('贵州茅台', limit=3)
for it in items:
    print(it['publish_date'], it['title'])
"`
Expected: 0-3 lines printed, no exceptions. (If 0 lines and no exception, Baidu returned empty references for that query — still a successful failover path.)

- [ ] **Step 6: Commit any format-only changes**

```bash
git status
# If any ruff format-only changes exist:
git add -u
git commit -m "style(news): address ruff format on BaiduFetcher files"
```

(If no changes, skip this step.)

---

## Self-Review Checklist (run before handoff)

- [x] **Spec coverage**:
  - §3 (request shape) → Task 2 + Task 3 ✓
  - §4 (class definition + methods) → Task 1 + Task 2 + Task 4-6 ✓
  - §5 (registration in __init__.py + manager.py) → Task 7 + Task 8 ✓
  - §6 (tests) → Task 1 + Task 2 + Task 3 + Task 4 + Task 5 + Task 6 + Task 11 ✓
  - §8 (recency filter) → Task 3 (recency tests) ✓
  - §8 (top_k clamping) → Task 3 (top_k tests) ✓
  - §8 (media_name = netloc) → Task 2 (happy path) ✓
  - §9 (.env.example + CLAUDE.md) → Task 9 + Task 10 ✓
  - §10 (exclusions — curl/playwright/etc) → explicitly NOT in any task ✓
- [x] **No placeholders**: scanned, none present.
- [x] **Type consistency**:
  - `BaiduFetcher.search_news(q: str, from_date: str | None, to_date: str | None, limit: int) -> list[dict]` defined consistently across all tasks.
  - `BAIDU_MAX_TOP_K = 50` constant used the same way in all tasks.
  - `_normalize_news_item` signature consistent across Tasks 2, 5, 6.
  - `BaiduFetcher.priority = int(os.getenv("BAIDU_PRIORITY", "7"))` matches in Tasks 1 and 3.
  - `_derive_recency` is a module-level function (not method), used consistently.
- [x] **Test isolation**: each test class uses its own monkeypatch + patch context; no shared state.
- [x] **No regressions**: Task 7 verifies `test_eastmoney_search_news.py` still passes; Task 8 verifies `test_manager_news_search.py` and `test_news_endpoints.py` still pass.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-16-baidu-fetcher.md`.

12 tasks total. Estimated time: ~90 min including test debugging. Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration with isolated context.

2. **Inline Execution** — I execute tasks in this session using executing-plans, batch execution with checkpoints for review.

Which approach?
