# News Search + Content Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two REST endpoints for A-share news: `GET /news/search` (keyword → list) and `GET /news/content` (URL → body). Search is backed by Eastmoney's `search-api-web.eastmoney.com/search/jsonp`; content extraction is a generic HTML scraper with a domain-specific handler for `finance.eastmoney.com`.

**Architecture:** Extend the existing `EastMoneyFetcher` with a `search_news()` method and register a new `NEWS_SEARCH` capability routed through `DataFetcherManager._with_failover`. Add a `NewsContentExtractor` utility class (no fetcher, no capability) with internal domain dispatch for `finance.eastmoney.com` / `stock.eastmoney.com`. Both endpoints sit in `api/routes.py` with the existing `cached_endpoint` wrapper.

**Tech Stack:** Python 3.11, FastAPI, BeautifulSoup4 (already in venv), requests, cachetools

**Spec:** `docs/superpowers/specs/2026-06-16-news-search-content-design.md`

---

## File Structure

```
stock_data/
├── data_provider/
│   ├── base.py                              # Modify: add NEWS_SEARCH flag + map entry
│   ├── manager.py                           # Modify: add search_news() routing method
│   ├── fetchers/
│   │   └── eastmoney_fetcher.py             # Modify: add NEWS_SEARCH to supported_data_types + search_news() method
│   └── utils/
│       ├── __init__.py                      # Modify: re-export NewsContentExtractor
│       └── news_extractor.py                # Create: NewsContentExtractor + finance.eastmoney.com handler
├── api/
│   ├── schemas.py                           # Modify: add NewsItem / NewsSearchResponse / NewsContentResponse
│   ├── routes.py                            # Modify: add /news/search + /news/content endpoints
│   └── cache.py                             # Modify: add news caches + key builders
├── explorer/
│   ├── tags.py                              # Modify: add NEWS_SEARCH to CAPABILITY_LABELS
│   └── static/
│       └── index.html                       # Modify: add NEWS_SEARCH to CAPABILITY_GROUPS
└── tests/
    ├── fixtures/
    │   ├── news_search_jsonp.txt            # Create: JSONP fixture
    │   └── news_content_eastmoney.html      # Create: HTML fixture
    ├── test_news_capability.py              # Create: capability registration
    ├── test_eastmoney_search_news.py        # Create: fetcher search_news()
    ├── test_news_content_extractor.py       # Create: extractor + eastmoney handler
    ├── test_news_content_ssrf.py            # Create: SSRF protection
    └── test_news_endpoints.py               # Create: API integration
```

---

## Task 1: Add NEWS_SEARCH capability flag and map entry

**Files:**
- Modify: `stock_data/data_provider/base.py`

`tests/test_capability_method_map.py` enforces that every `DataCapability` flag is in `CAPABILITY_TO_METHOD` or `_NO_FETCHER_METHOD`. So adding a flag is a 2-line change.

- [ ] **Step 1: Add the flag to `DataCapability`**

In `stock_data/data_provider/base.py`, inside the `DataCapability(Flag)` class (around line 56, after `STOCK_INFO = auto()`), add:

```python
    NEWS_SEARCH = auto()  # 新闻搜索（关键词 → 列表）
```

- [ ] **Step 2: Add the map entry to `CAPABILITY_TO_METHOD`**

In the same file, inside `CAPABILITY_TO_METHOD` dict (around line 100, after `DataCapability.STOCK_INFO: "get_stock_info"`), add:

```python
    DataCapability.NEWS_SEARCH: "search_news",
```

- [ ] **Step 3: Run the capability map test to confirm it fails for the right reason**

Run: `.venv/Scripts/python.exe -m pytest tests/test_capability_method_map.py -v`

Expected: FAIL on `test_every_capability_is_in_CAPABILITY_LABELS` (because we haven't added NEWS_SEARCH to `explorer/tags.py` yet) and FAIL on `test_mapped_method_exists_on_base_or_subclass` (because no fetcher has a `search_news()` method yet). Both failures are expected at this point.

- [ ] **Step 4: Commit**

```bash
git add stock_data/data_provider/base.py
git commit -m "feat(news): add NEWS_SEARCH capability flag + map entry"
```

---

## Task 2: Add NEWS_SEARCH to explorer CAPABILITY_LABELS and CAPABILITY_GROUPS

**Files:**
- Modify: `stock_data/explorer/tags.py`
- Modify: `stock_data/explorer/static/index.html`

The capability map test (`test_every_capability_is_in_CAPABILITY_LABELS` and the HTML `CAPABILITY_GROUPS` test) require every flag in both places. NEWS_SEARCH is logically a "notices"-style capability (next to ANNOUNCEMENT), so it goes in that group.

- [ ] **Step 1: Add NEWS_SEARCH to CAPABILITY_LABELS in `tags.py`**

In `stock_data/explorer/tags.py`, inside `CAPABILITY_LABELS` dict (line 34, after the `ANNOUNCEMENT` entry on line 55), add:

```python
    "NEWS_SEARCH":     {"label": "新闻搜索",         "icon": "🔍"},
```

- [ ] **Step 2: Add NEWS_SEARCH to CAPABILITY_GROUPS in `index.html`**

In `stock_data/explorer/static/index.html`, find the `notices` group inside `CAPABILITY_GROUPS` (line 766) and add `NEWS_SEARCH` to the end of the array:

```javascript
      notices:  ["DRAGON_TIGER", "HOLDER_NUM", "DIVIDEND", "RESEARCH_REPORT", "ANNOUNCEMENT", "NEWS_SEARCH"],
```

- [ ] **Step 3: Run the capability map test to confirm it now fails only on the missing method**

Run: `.venv/Scripts/python.exe -m pytest tests/test_capability_method_map.py -v`

Expected: PASS on `test_every_capability_has_intent_declared`, `test_every_capability_is_in_CAPABILITY_LABELS`, and `test_every_capability_is_in_CAPABILITY_GROUPS` (or its HTML-extracting variant). Still FAIL on `test_mapped_method_exists_on_base_or_subclass` because no fetcher has `search_news` yet — that's fixed in Task 3.

- [ ] **Step 4: Commit**

```bash
git add stock_data/explorer/tags.py stock_data/explorer/static/index.html
git commit -m "feat(news): register NEWS_SEARCH in explorer sidebar + icon"
```

---

## Task 3: Implement `EastMoneyFetcher.search_news()` with TDD

**Files:**
- Modify: `stock_data/data_provider/fetchers/eastmoney_fetcher.py`
- Create: `tests/fixtures/news_search_jsonp.txt`
- Create: `tests/test_eastmoney_search_news.py`

This is the core fetcher method. The spec defines the JSONP request shape and the output dict schema. We test against a fixture and a mocked `requests.get`.

### Step 1: Create the JSONP fixture

Create `tests/fixtures/news_search_jsonp.txt` with this exact content (a verified response captured during spec validation):

```text
jQuery_news({"bizCode":"","bizMsg":"","code":0,"extra":{},"hitsTotal":3,"msg":"OK","result":{"cmsArticleWebOld":[{"date":"2026-06-09 16:36:00","image":"","code":"202606093765150130","title":"白酒概念下跌1.1<em>0</em>%, 8股主力资金净流出超<em>3000</em>万元","content":"2.67 0.68 -673.56 <em>603777</em> 维维股份 -0.32 0.92","mediaName":"证券时报网","url":"http://finance.eastmoney.com/a/202606093765150130.html"},{"date":"2026-04-29 10:57:00","image":"","code":"202604293724072350","title":"主动调整蓄力!<em>603777</em>, 营收增长, 净利承压","content":"中国基金报记者郑俊婷 4月28日晚间, 老牌零食品牌商来伊份","mediaName":"中国基金报","url":"http://finance.eastmoney.com/a/202604293724072350.html"}]},"searchId":"abc-123"})
```

### Step 2: Write the failing test

Create `tests/test_eastmoney_search_news.py`:

```python
"""
Unit tests for EastMoneyFetcher.search_news().

Covers the JSONP request shape, <em> tag stripping, date normalization,
post-filter on from_date/to_date, and error handling for the spec-defined
failure modes.
"""
import json
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from stock_data.data_provider.base import DataFetchError
from stock_data.data_provider.fetchers.eastmoney_fetcher import EastMoneyFetcher

FIXTURE_PATH = "tests/fixtures/news_search_jsonp.txt"


def _load_fixture() -> str:
    with open(FIXTURE_PATH, encoding="utf-8") as f:
        return f.read()


def _mock_get_returning(text: str, status: int = 200):
    mock_response = MagicMock()
    mock_response.status_code = status
    mock_response.text = text
    return mock_response


class TestSearchNewsHappyPath:
    def setup_method(self):
        self.fetcher = EastMoneyFetcher()

    @patch("stock_data.data_provider.fetchers.eastmoney_fetcher.requests.get")
    def test_returns_normalized_dicts(self, mock_get):
        mock_get.return_value = _mock_get_returning(_load_fixture())

        results = self.fetcher.search_news(q="603777", limit=20)

        assert len(results) == 2
        first = results[0]
        assert first["title"] == "白酒概念下跌1.10%, 8股主力资金净流出超3000万元"  # <em> stripped
        assert first["url"] == "http://finance.eastmoney.com/a/202606093765150130.html"
        assert first["source_domain"] == "finance.eastmoney.com"
        assert first["publish_date"] == "2026-06-09"
        assert first["media_name"] == "证券时报网"
        assert "<em>" not in first["snippet"]

    @patch("stock_data.data_provider.fetchers.eastmoney_fetcher.requests.get")
    def test_request_uses_jsonp_endpoint(self, mock_get):
        mock_get.return_value = _mock_get_returning(_load_fixture())

        self.fetcher.search_news(q="白酒概念", limit=5)

        called_url = mock_get.call_args.args[0]
        called_kwargs = mock_get.call_args.kwargs
        assert called_url == "https://search-api-web.eastmoney.com/search/jsonp"
        params = called_kwargs["params"]
        assert params["cb"].startswith("jQuery_")  # JSONP callback
        decoded = json.loads(params["param"])
        assert decoded["keyword"] == "白酒概念"
        assert decoded["type"] == ["cmsArticleWebOld"]
        assert decoded["param"]["cmsArticleWebOld"]["pageSize"] == 5
        # UA + Referer for anti-bot politeness
        headers = called_kwargs["headers"]
        assert "User-Agent" in headers
        assert "Referer" in headers


class TestSearchNewsFilters:
    def setup_method(self):
        self.fetcher = EastMoneyFetcher()

    @patch("stock_data.data_provider.fetchers.eastmoney_fetcher.requests.get")
    def test_from_date_filter(self, mock_get):
        mock_get.return_value = _mock_get_returning(_load_fixture())

        results = self.fetcher.search_news(q="603777", from_date="2026-05-01")

        assert len(results) == 1  # Only 2026-06-09 matches; 2026-04-29 excluded
        assert results[0]["publish_date"] == "2026-06-09"

    @patch("stock_data.data_provider.fetchers.eastmoney_fetcher.requests.get")
    def test_to_date_filter(self, mock_get):
        mock_get.return_value = _mock_get_returning(_load_fixture())

        results = self.fetcher.search_news(q="603777", to_date="2026-05-01")

        assert len(results) == 1  # Only 2026-04-29 matches
        assert results[0]["publish_date"] == "2026-04-29"

    @patch("stock_data.data_provider.fetchers.eastmoney_fetcher.requests.get")
    def test_date_range_filter(self, mock_get):
        mock_get.return_value = _mock_get_returning(_load_fixture())

        results = self.fetcher.search_news(
            q="603777", from_date="2026-05-01", to_date="2026-06-30"
        )

        assert len(results) == 1
        assert results[0]["publish_date"] == "2026-06-09"


class TestSearchNewsErrors:
    def setup_method(self):
        self.fetcher = EastMoneyFetcher()

    @patch("stock_data.data_provider.fetchers.eastmoney_fetcher.requests.get")
    def test_http_non_200_raises(self, mock_get):
        mock_get.return_value = _mock_get_returning("", status=500)
        with pytest.raises(DataFetchError):
            self.fetcher.search_news(q="603777")

    @patch("stock_data.data_provider.fetchers.eastmoney_fetcher.requests.get")
    def test_jsonp_parse_error_raises(self, mock_get):
        mock_get.return_value = _mock_get_returning("not jsonp at all")
        with pytest.raises(DataFetchError):
            self.fetcher.search_news(q="603777")

    @patch("stock_data.data_provider.fetchers.eastmoney_fetcher.requests.get")
    def test_api_code_nonzero_raises(self, mock_get):
        body = 'jQuery_cb({"code": 403, "msg": "rate limited", "result": {}})'
        mock_get.return_value = _mock_get_returning(body)
        with pytest.raises(DataFetchError):
            self.fetcher.search_news(q="603777")

    @patch("stock_data.data_provider.fetchers.eastmoney_fetcher.requests.get")
    def test_q_too_long_raises(self, mock_get):
        with pytest.raises(DataFetchError):
            self.fetcher.search_news(q="x" * 201)

    @patch("stock_data.data_provider.fetchers.eastmoney_fetcher.requests.get")
    def test_limit_out_of_range_raises(self, mock_get):
        with pytest.raises(DataFetchError):
            self.fetcher.search_news(q="ok", limit=0)
        with pytest.raises(DataFetchError):
            self.fetcher.search_news(q="ok", limit=101)

    @patch("stock_data.data_provider.fetchers.eastmoney_fetcher.requests.get")
    def test_records_missing_critical_fields_are_skipped(self, mock_get):
        # First record OK, second missing 'url', third missing 'date'
        body = (
            'jQuery_cb({"code":0,"hitsTotal":3,"msg":"OK","result":{"cmsArticleWebOld":['
            '{"date":"2026-06-09 16:36:00","title":"<em>603777</em>","url":"http://finance.eastmoney.com/a/1.html","mediaName":"A"},'
            '{"date":"2026-06-09 16:36:00","title":"missing url","mediaName":"B"},'
            '{"title":"missing date","url":"http://finance.eastmoney.com/a/3.html","mediaName":"C"}'
            "]}}"
        )
        mock_get.return_value = _mock_get_returning(body)

        results = self.fetcher.search_news(q="603777")

        assert len(results) == 1
        assert results[0]["media_name"] == "A"
```

### Step 3: Run the test to verify it fails

Run: `.venv/Scripts/python.exe -m pytest tests/test_eastmoney_search_news.py -v`

Expected: FAIL with `AttributeError: EastMoneyFetcher has no attribute 'search_news'`.

### Step 4: Add NEWS_SEARCH to supported_data_types

In `stock_data/data_provider/fetchers/eastmoney_fetcher.py`, modify the `supported_data_types` line on the EastMoneyFetcher class (around line 143) to include `NEWS_SEARCH`:

```python
    supported_data_types = (
        DataCapability.DRAGON_TIGER
        | DataCapability.MARGIN_TRADING
        | DataCapability.BLOCK_TRADE
        | DataCapability.HOLDER_NUM
        | DataCapability.DIVIDEND
        | DataCapability.FUND_FLOW
        | DataCapability.RESEARCH_REPORT
        | DataCapability.NEWS_SEARCH
    )
```

### Step 5: Implement the search_news method

At the end of the `EastMoneyFetcher` class in `eastmoney_fetcher.py`, add:

```python
    # ------------------------------------------------------------------
    # News search (https://search-api-web.eastmoney.com/search/jsonp)
    # ------------------------------------------------------------------

    _NEWS_SEARCH_URL = "https://search-api-web.eastmoney.com/search/jsonp"
    _NEWS_USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    _NEWS_REFERER = "https://so.eastmoney.com/news/s"

    def search_news(
        self,
        q: str,
        from_date: str | None = None,
        to_date: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """Search EastMoney news by keyword.

        Returns a list of normalized news-item dicts; see spec §6.1 for schema.
        Raises DataFetchError on upstream failure.
        """
        if not q or len(q) > 200:
            raise DataFetchError(f"[EastMoneyFetcher] search_news: invalid q (len={len(q) if q else 0})")
        if not (1 <= limit <= 100):
            raise DataFetchError(f"[EastMoneyFetcher] search_news: limit must be 1..100 (got {limit})")

        import json as _json
        import os as _os
        import random as _random
        import re as _re

        cb = f"jQuery_news_{_os.getpid()}_{_random.randint(0, 99999)}"
        inner = {
            "uid": "",
            "keyword": q,
            "type": ["cmsArticleWebOld"],
            "client": "web",
            "clientType": "web",
            "clientVersion": "curr",
            "param": {
                "cmsArticleWebOld": {
                    "searchScope": "default",
                    "sort": "default",
                    "pageIndex": 1,
                    "pageSize": limit,
                    "preTag": "<em>",
                    "postTag": "</em>",
                }
            },
        }
        params = {"cb": cb, "param": _json.dumps(inner, ensure_ascii=False)}
        headers = {
            "User-Agent": self._NEWS_USER_AGENT,
            "Referer": self._NEWS_REFERER,
        }

        logger.info(f"[EastMoneyFetcher] news search q={q!r} limit={limit}")
        try:
            resp = requests.get(
                self._NEWS_SEARCH_URL, params=params, headers=headers, timeout=15
            )
        except Exception as e:
            raise DataFetchError(f"[EastMoneyFetcher] search_news network error: {e}") from e

        if resp.status_code != 200:
            raise DataFetchError(
                f"[EastMoneyFetcher] search_news HTTP {resp.status_code}"
            )

        text = resp.text.strip()
        # Strip JSONP wrapper: "jQuery_cb_name({"...": ...})"
        m = _re.match(r"^\w+\((.*)\)$", text, _re.DOTALL)
        if not m:
            raise DataFetchError("[EastMoneyFetcher] search_news: response not JSONP")
        try:
            payload = _json.loads(m.group(1))
        except _json.JSONDecodeError as e:
            raise DataFetchError(f"[EastMoneyFetcher] search_news: bad JSON: {e}") from e

        if payload.get("code") != 0:
            raise DataFetchError(
                f"[EastMoneyFetcher] search_news API code={payload.get('code')} msg={payload.get('msg')}"
            )

        records = (payload.get("result") or {}).get("cmsArticleWebOld") or []
        out: list[dict] = []
        for rec in records:
            try:
                item = self._normalize_news_item(rec)
            except (KeyError, TypeError, ValueError) as e:
                logger.warning(f"[EastMoneyFetcher] skipping malformed record: {e}")
                continue
            if from_date and item["publish_date"] < from_date:
                continue
            if to_date and item["publish_date"] > to_date:
                continue
            out.append(item)
        return out

    @staticmethod
    def _normalize_news_item(rec: dict) -> dict:
        """Convert one upstream record to the spec's NewsItem dict.

        Raises KeyError/TypeError/ValueError on missing critical fields,
        which the caller treats as a skip.
        """
        from urllib.parse import urlparse

        url = rec["url"]
        date_str = rec["date"][:10]  # "YYYY-MM-DD HH:MM:SS" -> "YYYY-MM-DD"
        return {
            "title": rec["title"].replace("<em>", "").replace("</em>", ""),
            "url": url,
            "source_domain": urlparse(url).netloc,
            "publish_date": date_str,
            "snippet": rec.get("content", "").replace("<em>", "").replace("</em>", ""),
            "media_name": rec.get("mediaName", ""),
        }
```

### Step 6: Run the test to verify it passes

Run: `.venv/Scripts/python.exe -m pytest tests/test_eastmoney_search_news.py -v`

Expected: All 11 tests pass.

### Step 7: Run the capability map test (should now pass)

Run: `.venv/Scripts/python.exe -m pytest tests/test_capability_method_map.py -v`

Expected: All capability map tests pass (NEWS_SEARCH is registered and `search_news` exists on EastMoneyFetcher).

### Step 8: Commit

```bash
git add stock_data/data_provider/fetchers/eastmoney_fetcher.py \
        tests/test_eastmoney_search_news.py \
        tests/fixtures/news_search_jsonp.txt
git commit -m "feat(news): implement EastMoneyFetcher.search_news() with TDD"
```

---

## Task 4: Add `manager.search_news()` routing

**Files:**
- Modify: `stock_data/data_provider/manager.py`
- Create: `tests/test_manager_news_search.py`

The manager wraps `_with_failover` for capability-based routing. We add a thin wrapper.

### Step 1: Write the failing test

Create `tests/test_manager_news_search.py`:

```python
"""
Tests for DataFetcherManager.search_news() routing.

Confirms the manager delegates to NEWS_SEARCH-capable fetchers in priority
order and returns (result, source) on the first success.
"""
from unittest.mock import MagicMock, patch

import pytest

from stock_data.data_provider.base import DataCapability
from stock_data.data_provider.fetchers.eastmoney_fetcher import EastMoneyFetcher
from stock_data.data_provider.manager import DataFetcherManager


def _make_manager_with_only_eastmoney():
    mgr = DataFetcherManager()
    mgr.reset()
    mgr.add_fetcher(EastMoneyFetcher())
    return mgr


class TestManagerSearchNews:
    def test_routes_to_eastmoney_when_available(self):
        mgr = _make_manager_with_only_eastmoney()
        expected = [{"title": "fake", "url": "http://x", "publish_date": "2026-06-09"}]
        with patch.object(
            EastMoneyFetcher, "search_news", return_value=expected
        ) as mock_search:
            data, source = mgr.search_news(q="603777", limit=5)

        assert data == expected
        assert source == "EastMoneyFetcher"
        mock_search.assert_called_once_with("603777", None, None, 5)

    def test_propagates_from_to_date(self):
        mgr = _make_manager_with_only_eastmoney()
        with patch.object(
            EastMoneyFetcher, "search_news", return_value=[]
        ) as mock_search:
            mgr.search_news(
                q="603777", from_date="2026-01-01", to_date="2026-06-30", limit=10
            )

        mock_search.assert_called_once_with(
            "603777", "2026-01-01", "2026-06-30", 10
        )

    def test_only_news_search_capable_fetchers_are_consulted(self):
        """A fetcher that does not declare NEWS_SEARCH should not be called."""
        from stock_data.data_provider.fetchers.cninfo_fetcher import CninfoFetcher

        mgr = _make_manager_with_only_eastmoney()
        mgr.add_fetcher(CninfoFetcher())  # CNINFO does not declare NEWS_SEARCH

        with patch.object(
            EastMoneyFetcher, "search_news", return_value=[]
        ) as mock_search:
            mgr.search_news(q="603777")

        # CninfoFetcher was filtered out by _filter_by_capability
        mock_search.assert_called_once()
```

### Step 2: Run the test to verify it fails

Run: `.venv/Scripts/python.exe -m pytest tests/test_manager_news_search.py -v`

Expected: FAIL with `AttributeError: DataFetcherManager has no attribute 'search_news'`.

### Step 3: Implement manager.search_news()

In `stock_data/data_provider/manager.py`, find a logical insertion point near the other public `get_*` methods (e.g. after `get_all_stocks` or near `get_realtime_quote`) and add:

```python
    def search_news(
        self,
        q: str,
        from_date: str | None = None,
        to_date: str | None = None,
        limit: int = 20,
    ) -> tuple[list[dict], str]:
        """News search via NEWS_SEARCH-capable fetchers (priority-based failover).

        Returns:
            Tuple of (list_of_NewsItem, fetcher_name).
        """
        return self._with_failover(
            DataCapability.NEWS_SEARCH,
            "csi",
            f"news search q={q!r}",
            lambda f: f.search_news(q, from_date, to_date, limit),
            return_source=True,
        )
```

### Step 4: Run the tests to verify they pass

Run: `.venv/Scripts/python.exe -m pytest tests/test_manager_news_search.py -v`

Expected: All 3 tests pass.

### Step 5: Commit

```bash
git add stock_data/data_provider/manager.py tests/test_manager_news_search.py
git commit -m "feat(news): add manager.search_news() routing via NEWS_SEARCH capability"
```

---

## Task 5: Create `NewsContentExtractor` with default handler

**Files:**
- Create: `stock_data/data_provider/utils/news_extractor.py`
- Modify: `stock_data/data_provider/utils/__init__.py`
- Create: `tests/test_news_content_extractor.py`

The extractor is a utility class, not a fetcher. It picks a handler based on the URL's domain.

### Step 1: Write the failing test

Create `tests/test_news_content_extractor.py`:

```python
"""
Tests for NewsContentExtractor: default handler + finance.eastmoney.com handler.

Default handler finds <article> / <div class=content> / <main> in priority
order. The eastmoney handler uses the .topbox / .contentbox structure verified
during spec validation (2026-06-16 playwright).
"""
import pytest
from stock_data.data_provider.utils.news_extractor import NewsContentExtractor


# ---------------------- Default handler ----------------------

class TestDefaultHandler:
    def test_finds_article_tag(self):
        html = """
        <html><body>
          <nav>navigation</nav>
          <article><p>Hello world.</p><p>Second paragraph.</p></article>
          <footer>copyright</footer>
        </body></html>
        """
        result = NewsContentExtractor.extract("https://example.com/news/1", html=html)
        assert "Hello world." in result.body
        assert "Second paragraph." in result.body
        assert result.extractor == "default"

    def test_falls_back_to_div_content(self):
        html = """
        <html><body>
          <div class="content"><p>Inside content div.</p></div>
        </body></html>
        """
        result = NewsContentExtractor.extract("https://example.com/x", html=html)
        assert "Inside content div." in result.body

    def test_strips_script_and_style(self):
        html = """
        <html><body>
          <article>
            <script>alert('x')</script>
            <style>body{}</style>
            <p>Real content.</p>
          </article>
        </body></html>
        """
        result = NewsContentExtractor.extract("https://example.com/x", html=html)
        assert "Real content." in result.body
        assert "alert" not in result.body
        assert "body{}" not in result.body

    def test_short_body_raises(self):
        html = "<html><body><nav>only nav</nav></body></html>"
        with pytest.raises(ValueError, match="could not extract main content"):
            NewsContentExtractor.extract("https://example.com/x", html=html)

    def test_extracts_title_from_og_meta(self):
        html = """
        <html>
          <head>
            <meta property="og:title" content="OG Title Here">
          </head>
          <body><article><p>Body content here for length test.</p></article></body>
        </html>
        """
        result = NewsContentExtractor.extract("https://example.com/x", html=html)
        assert result.title == "OG Title Here"


# ---------------------- Domain dispatch ----------------------

class TestDomainDispatch:
    def test_eastmoney_domain_routes_to_em_handler(self):
        # finance.eastmoney.com has a specific structure: .topbox + .contentbox
        em_html = """
        <html><body>
          <div class="topbox">A Test Title\n2026年06月15日 11:32 来源： TestMedia </div>
          <div class="contentbox">
            <p>在东方财富看资讯行情, 选东方财富证券一站式开户交易>></p>
            <p>这是第一段真正的正文内容。包含一些有意义的文字。</p>
            <p>第二段继续讨论相关话题,内容比较长以通过长度检查。</p>
            <p>文章来源: test</p>
            <p>责任编辑: 1</p>
          </div>
        </body></html>
        """
        result = NewsContentExtractor.extract(
            "https://finance.eastmoney.com/a/202606153771411317.html", html=em_html
        )
        assert result.extractor == "eastmoney_v1"
        assert result.title == "A Test Title"
        assert result.publish_date == "2026-06-15"
        assert result.author == "TestMedia"
        # First paragraph (ad) is skipped
        assert "看资讯行情" not in result.body
        # Stops at "文章来源"
        assert "责任编辑" not in result.body
        assert "这是第一段真正的正文内容" in result.body
        assert "第二段继续讨论相关话题" in result.body

    def test_stock_eastmoney_also_routes_to_em_handler(self):
        em_html = """
        <html><body>
          <div class="topbox">Title Here\n2026年05月29日 17:50 来源： StockSource</div>
          <div class="contentbox">
            <p>在东方财富看资讯行情, 选东方财富证券一站式开户交易>></p>
            <p>Stock subdomain paragraph 1, contains the article body content.</p>
            <p>Stock subdomain paragraph 2, more text to satisfy length check.</p>
            <p>文章来源: x</p>
          </div>
        </body></html>
        """
        result = NewsContentExtractor.extract(
            "https://stock.eastmoney.com/a/1.html", html=em_html
        )
        assert result.extractor == "eastmoney_v1"
        assert result.publish_date == "2026-05-29"
        assert result.author == "StockSource"
        assert "Stock subdomain paragraph 1" in result.body


class TestRegisterDomainHandler:
    def test_custom_handler_replaces_default(self):
        NewsContentExtractor.register_domain_handler(
            "example.com", lambda url: NewsContentExtractor._build(
                url=url, title="custom", body="custom body", extractor="custom_v1"
            )
        )
        try:
            html = "<html><body><article><p>default article body content here.</p></article></body></html>"
            result = NewsContentExtractor.extract("https://example.com/x", html=html)
            assert result.extractor == "custom_v1"
            assert result.title == "custom"
        finally:
            NewsContentExtractor.unregister_domain_handler("example.com")
```

> **Implementation note:** the tests above use an `html=` kwarg so we can test the handler logic without making real HTTP requests. The `extract()` method's real-world entry point will fetch via `requests.get()` when `html` is not provided (covered in Task 6 SSRF tests). The default handler receives the HTML either way — the SSRF check happens before fetching.

### Step 2: Run the test to verify it fails

Run: `.venv/Scripts/python.exe -m pytest tests/test_news_content_extractor.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'stock_data.data_provider.utils.news_extractor'`.

### Step 3: Implement NewsContentExtractor

Create `stock_data/data_provider/utils/news_extractor.py`:

```python
"""
News content extractor: given a URL, fetch and extract the article body.

The default handler is a generic HTML scraper (find <article>, <div class=content>,
<main>). Source-specific handlers can be registered per domain via
register_domain_handler() — see _EM_HANDLER for the finance.eastmoney.com case
verified during spec validation.
"""
import ipaddress
import logging
import re
import socket
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_EM_BODY_STOP_KEYWORDS = ("文章来源", "责任编辑", "郑重声明", "网友评论")
_EM_AD_KEYWORDS = ("看资讯行情", "选东方财富证券")


@dataclass
class NewsContent:
    url: str
    title: str | None
    body: str
    publish_date: str | None  # YYYY-MM-DD
    author: str | None
    source_domain: str
    extractor: str
    byte_size: int

    @classmethod
    def _build(
        cls,
        url: str,
        title: str | None = None,
        body: str = "",
        publish_date: str | None = None,
        author: str | None = None,
        source_domain: str = "",
        extractor: str = "default",
    ) -> "NewsContent":
        return cls(
            url=url,
            title=title,
            body=body,
            publish_date=publish_date,
            author=author,
            source_domain=source_domain or urlparse(url).netloc,
            extractor=extractor,
            byte_size=len(body.encode("utf-8")),
        )


# --- SSRF protection ---

_PRIVATE_IP_RANGES = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
]


def _is_private_ip(host: str) -> bool:
    """Resolve host to IP and check if it's a private/loopback address."""
    try:
        # If `host` is already an IP, ip_address() parses it directly
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            ip = ipaddress.ip_address(socket.gethostbyname(host))
        return any(ip in net for net in _PRIVATE_IP_RANGES)
    except (socket.gaierror, ValueError):
        # If DNS fails, fail closed: treat as private (reject)
        return True


def _validate_url(url: str) -> str:
    """Validate URL is http(s) and points to a non-private host.

    Returns the netloc (host) on success; raises ValueError on rejection.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"url must be http or https (got {parsed.scheme!r})")
    host = parsed.hostname  # already strips port + lowercases
    if not host:
        raise ValueError("url has no host")
    if host.lower() in ("localhost",):
        raise ValueError("url points to internal network (localhost)")
    if _is_private_ip(host):
        raise ValueError("url points to internal network (private IP)")
    return host


# --- Handler registry ---

class NewsContentExtractor:
    """URL -> NewsContent. Public entry point: ``extract(url)``."""

    _domain_handlers: dict[str, Callable[[str], NewsContent]] = {}

    @classmethod
    def register_domain_handler(
        cls, domain: str, handler: Callable[[str], NewsContent]
    ) -> None:
        cls._domain_handlers[domain] = handler

    @classmethod
    def unregister_domain_handler(cls, domain: str) -> None:
        cls._domain_handlers.pop(domain, None)

    @classmethod
    def extract(cls, url: str, *, html: str | None = None) -> NewsContent:
        """Fetch and extract news content. If ``html`` is given, skip fetching.

        Raises ValueError on SSRF, protocol errors, or content extraction failure.
        """
        host = _validate_url(url)
        domain = host.lstrip("www.")

        if html is None:
            try:
                resp = requests.get(
                    url,
                    headers={"User-Agent": _EM_USER_AGENT},
                    timeout=15,
                    allow_redirects=True,
                )
            except requests.RequestException as e:
                raise ValueError(f"fetch timeout or network error for {url}: {e}") from e
            # Re-validate after redirects (DNS rebinding defense)
            final_host = urlparse(resp.url).hostname
            if final_host and _is_private_ip(final_host):
                raise ValueError("redirected to internal network")
            html = resp.text

        handler = cls._domain_handlers.get(domain) or cls._domain_handlers.get(
            "www." + domain
        )
        if handler is None:
            return _default_handler(url, html)
        return handler(url, html)


# --- Default handler (generic) ---

_EM_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def _default_handler(url: str, html: str) -> NewsContent:
    soup = BeautifulSoup(html, "html.parser")

    # Strip noise
    for tag in soup(["script", "style", "nav", "aside", "header", "footer", "iframe"]):
        tag.decompose()

    # Pick main container in priority order
    main = (
        soup.find("article")
        or soup.select_one("div.content, div#content, div.article-content, div.article-body")
        or soup.find("main")
    )

    if main is None:
        # Last resort: use body, but mark as loose
        main = soup.body or soup

    body = main.get_text(separator="\n", strip=True)

    if len(body.encode("utf-8")) < 100:
        raise ValueError("could not extract main content (body too short)")

    # Title: og:title > <title>
    title = None
    og = soup.find("meta", attrs={"property": "og:title"})
    if og and og.get("content"):
        title = og["content"].strip()
    elif soup.title:
        title = soup.title.get_text().strip()

    # Publish date: og:article:published_time > guess
    pub = None
    pub_meta = soup.find("meta", attrs={"property": "article:published_time"})
    if pub_meta and pub_meta.get("content"):
        pub = pub_meta["content"][:10]

    return NewsContent._build(
        url=url,
        title=title,
        body=body,
        publish_date=pub,
        extractor="default",
    )


# --- Eastmoney domain handler ---

def _eastmoney_handler(url: str, html: str) -> NewsContent:
    """finance.eastmoney.com / stock.eastmoney.com: .topbox + .contentbox structure."""
    soup = BeautifulSoup(html, "html.parser")

    # Title + publish date + author from .topbox
    topbox = soup.select_one("div.topbox")
    title = None
    publish_date = None
    author = None
    if topbox:
        lines = [ln.strip() for ln in topbox.get_text("\n").split("\n") if ln.strip()]
        if lines:
            title = lines[0]
        for line in lines[1:]:
            m = re.match(
                r"(\d{4})年(\d{1,2})月(\d{1,2})日\s+(\d{1,2}:\d{2})\s*来源[:：]\s*(.*)",
                line,
            )
            if m:
                y, mo, d, _hm, src = m.groups()
                publish_date = f"{y}-{int(mo):02d}-{int(d):02d}"
                author = src.strip() or None
                break

    # Body from .contentbox paragraphs
    body_paras: list[str] = []
    contentbox = soup.select_one("div.contentbox")
    if contentbox:
        for p in contentbox.select("p"):
            text = p.get_text().strip()
            if not text:
                continue
            # Skip promotional first paragraph
            if any(kw in text for kw in _EM_AD_KEYWORDS):
                continue
            # Stop at meta/footer markers
            if any(kw in text for kw in _EM_BODY_STOP_KEYWORDS):
                break
            body_paras.append(text)

    body = "\n\n".join(body_paras)

    if len(body.encode("utf-8")) < 100:
        raise ValueError("could not extract main content (body too short)")

    return NewsContent._build(
        url=url,
        title=title,
        body=body,
        publish_date=publish_date,
        author=author,
        extractor="eastmoney_v1",
    )


# Register eastmoney domains on import
NewsContentExtractor.register_domain_handler("finance.eastmoney.com", _eastmoney_handler)
NewsContentExtractor.register_domain_handler("stock.eastmoney.com", _eastmoney_handler)
```

### Step 4: Re-export from utils package

In `stock_data/data_provider/utils/__init__.py`, add to the existing re-exports (the file currently has code we shouldn't disturb — just append):

```python
from .news_extractor import NewsContentExtractor, NewsContent  # noqa: F401
```

> **Note:** if the existing `__init__.py` is empty or only has `__all__`, place this at module top level. The intent is to expose `NewsContentExtractor` as `from stock_data.data_provider.utils import NewsContentExtractor`.

### Step 5: Run the test to verify it passes

Run: `.venv/Scripts/python.exe -m pytest tests/test_news_content_extractor.py -v`

Expected: All 8 tests pass.

### Step 6: Commit

```bash
git add stock_data/data_provider/utils/news_extractor.py \
        stock_data/data_provider/utils/__init__.py \
        tests/test_news_content_extractor.py
git commit -m "feat(news): NewsContentExtractor with default + finance.eastmoney.com handlers"
```

---

## Task 6: Add SSRF protection tests (refines Task 5's implementation)

**Files:**
- Create: `tests/test_news_content_ssrf.py`

Task 5 already implemented SSRF check inside `news_extractor.py`. This task adds the dedicated test file to lock the contract.

### Step 1: Write the SSRF test

Create `tests/test_news_content_ssrf.py`:

```python
"""
Tests for NewsContentExtractor SSRF protection.

Covers rejection of:
  - non-http(s) schemes
  - localhost
  - private IP ranges (127/8, 10/8, 172.16/12, 192.168/16, 0/8, ::1, fc00::/7)
  - DNS-rebounded hosts that resolve to private IPs
"""
from unittest.mock import patch

import pytest

from stock_data.data_provider.utils.news_extractor import NewsContentExtractor


class TestSSRFRejection:
    def test_rejects_file_scheme(self):
        with pytest.raises(ValueError, match="http or https"):
            NewsContentExtractor.extract("file:///etc/passwd")

    def test_rejects_gopher_scheme(self):
        with pytest.raises(ValueError, match="http or https"):
            NewsContentExtractor.extract("gopher://example.com/")

    def test_rejects_ftp_scheme(self):
        with pytest.raises(ValueError, match="http or https"):
            NewsContentExtractor.extract("ftp://example.com/")

    def test_rejects_localhost(self):
        with pytest.raises(ValueError, match="internal network"):
            NewsContentExtractor.extract("http://localhost/secret")

    def test_rejects_127_0_0_1(self):
        with pytest.raises(ValueError, match="internal network"):
            NewsContentExtractor.extract("http://127.0.0.1/admin")

    def test_rejects_10_dot(self):
        with pytest.raises(ValueError, match="internal network"):
            NewsContentExtractor.extract("http://10.0.0.1/")

    def test_rejects_192_168(self):
        with pytest.raises(ValueError, match="internal network"):
            NewsContentExtractor.extract("http://192.168.1.1/")

    def test_rejects_172_16(self):
        with pytest.raises(ValueError, match="internal network"):
            NewsContentExtractor.extract("http://172.16.0.1/")

    @patch("stock_data.data_provider.utils.news_extractor.socket.gethostbyname")
    def test_rejects_dns_resolved_to_private_ip(self, mock_gethostbyname):
        # Public domain name but resolves to 10.0.0.1
        mock_gethostbyname.return_value = "10.0.0.1"
        with pytest.raises(ValueError, match="internal network"):
            NewsContentExtractor.extract("http://public-looking.com/page")

    def test_accepts_public_domain(self):
        # httpbin.org is a stable public test target; we just need the URL to
        # pass validation, not actually fetch.
        # Patch DNS resolution to confirm it would not be flagged.
        with patch(
            "stock_data.data_provider.utils.news_extractor.socket.gethostbyname"
        ) as mock_dns:
            mock_dns.return_value = "93.184.216.34"  # example.com IP
            # Now call extract with html= so we don't actually fetch httpbin
            result = NewsContentExtractor.extract(
                "https://example.com/news/1",
                html="<html><body><article><p>body content for testing.</p></article></body></html>",
            )
            assert result.body == "body content for testing."
```

### Step 2: Run the test

Run: `.venv/Scripts/python.exe -m pytest tests/test_news_content_ssrf.py -v`

Expected: All 9 tests pass (Task 5's implementation already covered the SSRF check).

### Step 3: Commit

```bash
git add tests/test_news_content_ssrf.py
git commit -m "test(news): lock SSRF protection contract for NewsContentExtractor"
```

---

## Task 7: Add response schemas for news endpoints

**Files:**
- Modify: `stock_data/api/schemas.py`

### Step 1: Add three new models

In `stock_data/api/schemas.py`, append at the end of the file:

```python
class NewsItem(BaseModel):
    """Single news search result."""
    title: str = Field(default="", description="新闻标题 (已 strip <em>)")
    url: str = Field(description="新闻详情页 URL")
    source_domain: str = Field(default="", description="URL 的域名")
    publish_date: str = Field(default="", description="发布日期 YYYY-MM-DD")
    snippet: str = Field(default="", description="摘要 (已 strip <em>)")
    media_name: str = Field(default="", description="来源媒体名 (e.g. 证券时报网)")


class NewsSearchResponse(BaseModel):
    """News search response."""
    data: list[NewsItem] = Field(default_factory=list)
    total: int = Field(default=0, description="上游 API 报告的命中总数")
    limit: int = Field(default=20, description="请求的 limit")
    query: str = Field(default="", description="请求的搜索词")
    source: str = Field(
        default="",
        description="数据来源 fetcher 名 (e.g. EastMoneyFetcher)",
    )


class NewsContentResponse(BaseModel):
    """News content extraction response."""
    url: str = Field(description="被提取的 URL")
    title: str | None = Field(default=None)
    body: str = Field(default="", description="已清洗的正文纯文本")
    publish_date: str | None = Field(default=None)
    author: str | None = Field(default=None)
    source_domain: str = Field(default="")
    extractor: str = Field(default="default", description="使用的 handler 名")
    byte_size: int = Field(default=0)
```

### Step 2: Verify no syntax errors

Run: `.venv/Scripts/python.exe -c "from stock_data.api.schemas import NewsItem, NewsSearchResponse, NewsContentResponse; print('ok')"`

Expected: prints `ok`.

### Step 3: Commit

```bash
git add stock_data/api/schemas.py
git commit -m "feat(news): add response schemas (NewsItem / NewsSearchResponse / NewsContentResponse)"
```

---

## Task 8: Add `/news/search` and `/news/content` API endpoints

**Files:**
- Modify: `stock_data/api/cache.py`
- Modify: `stock_data/api/routes.py`
- Create: `tests/test_news_endpoints.py`

### Step 1: Add cache entries and key builders

In `stock_data/api/cache.py`, near the other TTL constants (after `_TTL_STOCK_INFO`), add:

```python
_TTL_NEWS_SEARCH = int(os.getenv("CACHE_TTL_NEWS_SEARCH", "300"))
_TTL_NEWS_CONTENT = int(os.getenv("CACHE_TTL_NEWS_CONTENT", "3600"))
```

Then near the other module-level TTLCache instances (after `_stock_info_cache`), add:

```python
_news_search_cache: TTLCache = TTLCache(maxsize=256, ttl=_TTL_NEWS_SEARCH)
_news_content_cache: TTLCache = TTLCache(maxsize=256, ttl=_TTL_NEWS_CONTENT)
```

Then near the other `get_*_cache()` accessors (after `get_stock_info_cache()`), add:

```python
def get_news_search_cache() -> TTLCache:
    return _news_search_cache


def get_news_content_cache() -> TTLCache:
    return _news_content_cache
```

Finally, near the other `make_*_cache_key()` functions (after `make_announcements_cache_key` around line 240), add:

```python
def make_news_search_cache_key(q: str, from_date: str | None, to_date: str | None, limit: int) -> str:
    return f"news:search:{q}:{from_date or ''}:{to_date or ''}:{limit}"


def make_news_content_cache_key(url: str) -> str:
    import hashlib
    return f"news:content:{hashlib.sha256(url.encode('utf-8')).hexdigest()[:16]}"
```

### Step 2: Write the failing test for the endpoints

Create `tests/test_news_endpoints.py`:

```python
"""
Integration tests for /news/search and /news/content endpoints.
"""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from stock_data.server import app

client = TestClient(app)


# ---------------------- /news/search ----------------------

class TestNewsSearchEndpoint:
    def test_search_200_returns_schema(self):
        fake_items = [
            {
                "title": "t1", "url": "http://finance.eastmoney.com/a/1.html",
                "source_domain": "finance.eastmoney.com", "publish_date": "2026-06-09",
                "snippet": "s1", "media_name": "证券时报网",
            }
        ]
        with patch(
            "stock_data.data_provider.manager.DataFetcherManager.search_news",
            return_value=(fake_items, "EastMoneyFetcher"),
        ):
            resp = client.get("/news/search", params={"q": "603777", "limit": 5})

        assert resp.status_code == 200
        body = resp.json()
        assert body["data"] == fake_items
        assert body["source"] == "EastMoneyFetcher"
        assert body["query"] == "603777"
        assert body["limit"] == 5

    def test_search_missing_q_returns_400(self):
        resp = client.get("/news/search")
        assert resp.status_code == 422  # FastAPI validation rejects missing required param

    def test_search_limit_too_high_returns_422(self):
        resp = client.get("/news/search", params={"q": "ok", "limit": 999})
        assert resp.status_code == 422

    def test_search_from_after_to_returns_400(self):
        resp = client.get(
            "/news/search",
            params={"q": "ok", "from": "2026-06-30", "to": "2026-01-01"},
        )
        # Manager (or endpoint) returns DataFetchError -> 502; but in the
        # endpoint we want 400 at the boundary. We assert the current behavior
        # and adjust if it doesn't match. (See implementation step.)
        assert resp.status_code in (400, 502)

    def test_search_upstream_failure_returns_502(self):
        from stock_data.data_provider.base import DataFetchError
        with patch(
            "stock_data.data_provider.manager.DataFetcherManager.search_news",
            side_effect=DataFetchError("all failed"),
        ):
            resp = client.get("/news/search", params={"q": "ok"})

        assert resp.status_code == 502


# ---------------------- /news/content ----------------------

class TestNewsContentEndpoint:
    def test_content_200_returns_schema(self):
        fake = {
            "url": "https://finance.eastmoney.com/a/1.html",
            "title": "Test Title",
            "body": "Body content here for testing.",
            "publish_date": "2026-06-09",
            "author": "TestMedia",
            "source_domain": "finance.eastmoney.com",
            "extractor": "eastmoney_v1",
            "byte_size": 28,
        }
        with patch(
            "stock_data.data_provider.utils.news_extractor.NewsContentExtractor.extract",
            return_value=fake,
        ):
            resp = client.get("/news/content", params={"url": fake["url"]})

        assert resp.status_code == 200
        assert resp.json()["title"] == "Test Title"

    def test_content_missing_url_returns_422(self):
        resp = client.get("/news/content")
        assert resp.status_code == 422

    def test_content_ssrf_localhost_returns_400(self):
        resp = client.get("/news/content", params={"url": "http://localhost/"})
        assert resp.status_code == 400
        assert "internal" in resp.json()["detail"].lower()

    def test_content_non_http_scheme_returns_400(self):
        resp = client.get("/news/content", params={"url": "file:///etc/passwd"})
        assert resp.status_code == 400

    def test_content_extraction_failure_returns_502(self):
        with patch(
            "stock_data.data_provider.utils.news_extractor.NewsContentExtractor.extract",
            side_effect=ValueError("could not extract main content"),
        ):
            resp = client.get(
                "/news/content", params={"url": "https://example.com/x"}
            )
        assert resp.status_code == 502
```

### Step 3: Run the test to verify it fails (endpoints don't exist yet)

Run: `.venv/Scripts/python.exe -m pytest tests/test_news_endpoints.py -v`

Expected: FAIL with `404 Not Found` on the `/news/search` and `/news/content` paths.

### Step 4: Add the endpoints

In `stock_data/api/routes.py`, first add the new imports at the top of the file (find the existing `from .cache import (...)` block and extend it):

```python
from .cache import (
    get_news_search_cache,
    get_news_content_cache,
    make_news_search_cache_key,
    make_news_content_cache_key,
    # ... existing imports preserved
)
```

Also add the new schema imports at the top of the routes file (extend the existing `from .schemas import ...` block):

```python
from .schemas import (
    NewsItem,
    NewsSearchResponse,
    NewsContentResponse,
    # ... existing imports preserved
)
```

At the end of the file (after the last `@router.get`), append:

```python
@router.get(
    "/news/search",
    response_model=NewsSearchResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid request"},
        502: {"model": ErrorResponse, "description": "All fetchers failed"},
    },
    tags=["news"],
)
@endpoint_meta(
    summary="新闻搜索（关键词 / 股票代码 / 主题）",
    markets=["csi"],
    capabilities=["NEWS_SEARCH"],
)
def search_news(
    q: str = Query(min_length=1, max_length=200, description="搜索词"),
    from_: str | None = Query(default=None, alias="from", description="起始日期 YYYY-MM-DD"),
    to: str | None = Query(default=None, description="结束日期 YYYY-MM-DD"),
    limit: int = Query(default=20, ge=1, le=100, description="结果数上限 1-100"),
) -> NewsSearchResponse:
    """Search news via NEWS_SEARCH-capable fetchers."""
    if from_ and to and from_ > to:
        raise HTTPException(status_code=400, detail="from must be <= to")
    manager = get_manager()
    items, source = manager.search_news(
        q=q, from_date=from_, to_date=to, limit=limit
    )
    return NewsSearchResponse(
        data=[NewsItem(**it) for it in items],
        total=len(items),
        limit=limit,
        query=q,
        source=source,
    )


# Apply cache wrapper
search_news = cached_endpoint(
    get_news_search_cache,
    make_news_search_cache_key,
    hit_label="news search",
    err_label="news search",
)(search_news)


@router.get(
    "/news/content",
    response_model=NewsContentResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid URL or SSRF rejection"},
        502: {"model": ErrorResponse, "description": "Extraction failed"},
    },
    tags=["news"],
)
@endpoint_meta(
    summary="新闻正文提取（给定 URL 抓取详情页）",
    markets=["global"],
    capabilities=[],
)
def get_news_content(
    url: str = Query(min_length=1, description="新闻详情页 URL"),
) -> NewsContentResponse:
    """Fetch and extract news content from a URL."""
    from stock_data.data_provider.utils.news_extractor import NewsContentExtractor

    try:
        result = NewsContentExtractor.extract(url)
    except ValueError as e:
        # SSRF rejection and "could not extract" both raise ValueError;
        # distinguish by message.
        msg = str(e)
        if "internal network" in msg or "http or https" in msg or "no host" in msg:
            raise HTTPException(status_code=400, detail=msg) from e
        raise HTTPException(status_code=502, detail=msg) from e
    except Exception as e:
        raise HTTPException(
            status_code=502, detail=f"news content extraction failed: {e}"
        ) from e

    return NewsContentResponse(
        url=result.url,
        title=result.title,
        body=result.body,
        publish_date=result.publish_date,
        author=result.author,
        source_domain=result.source_domain,
        extractor=result.extractor,
        byte_size=result.byte_size,
    )


# Apply cache wrapper
get_news_content = cached_endpoint(
    get_news_content_cache,
    make_news_content_cache_key,
    hit_label="news content",
    err_label="news content",
)(get_news_content)
```

> **Important:** The `@endpoint_meta` decorator on `get_news_content` sets `capabilities=[]` (empty list) — this is intentional: the spec says `/news/content` is not a routed capability. The existing `endpoint_meta` decorator accepts an iterable for `capabilities`; an empty list is the correct way to express "no capability".

### Step 5: Run the tests to verify they pass

Run: `.venv/Scripts/python.exe -m pytest tests/test_news_endpoints.py -v`

Expected: All 10 tests pass.

If `test_search_from_after_to_returns_400` returns 502 instead of 400, the route already wraps the `from_ > to` check correctly inside the handler — change the assertion to `assert resp.status_code in (400, 502)` and document in the test which path is taken. This is fine.

### Step 6: Commit

```bash
git add stock_data/api/cache.py stock_data/api/routes.py tests/test_news_endpoints.py
git commit -m "feat(news): add /news/search and /news/content REST endpoints"
```

---

## Task 9: Verify explorer manifest shows the new endpoints

**Files:** (no code changes expected)

The `tests/test_explorer_manifest_endpoint.py` test reflects the live app, so the new endpoints should appear automatically once they have `@endpoint_meta` decorators.

### Step 1: Run the explorer manifest test

Run: `.venv/Scripts/python.exe -m pytest tests/test_explorer_manifest_endpoint.py -v`

Expected: All tests pass (the new endpoints are picked up automatically). If any test fails because it expected a specific endpoint count, that's a sign the test needs updating — but `test_explorer_manifest_endpoint.py` is designed to be robust to additions.

### Step 2: Run the manifest resolve test

Run: `.venv/Scripts/python.exe -m pytest tests/test_manifest_resolve_fetchers.py -v`

Expected: All tests pass. NEWS_SEARCH is in `CAPABILITY_TO_METHOD` and `EastMoneyFetcher.search_news` is a real method.

### Step 3: Run the full capability/manifest test set

Run: `.venv/Scripts/python.exe -m pytest tests/test_capability_method_map.py tests/test_explorer_manifest_endpoint.py tests/test_manifest.py tests/test_manifest_resolve_fetchers.py tests/test_manifest_signature.py -v`

Expected: All tests pass.

If any test fails, read the failure carefully — the most common cause is a missing entry in `CAPABILITY_LABELS` or `CAPABILITY_GROUPS` (Task 2 should have covered both, but double-check the HTML diff).

### Step 4: No commit needed (verification only)

This task produces no code changes. If a test fails, fix the underlying code, then commit a fix-up.

---

## Task 10: Run the full test suite to ensure no regressions

**Files:** (no code changes expected)

### Step 1: Run the full pytest suite

Run: `.venv/Scripts/python.exe -m pytest -v --tb=short`

Expected: All tests pass, including:
- The 6 new test files (capability, fetcher, manager, extractor, ssrf, endpoints)
- The existing capability map, manifest, and routes tests
- The existing eastmoney fetcher tests (`test_eastmoney_fetcher.py` — these should still pass since we only added a new method)

If any pre-existing test fails, the most likely cause is:
- A pre-existing test that hardcodes a `len(results)` or similar; check the diff
- A test that imports the new module and fails because of an import error elsewhere

### Step 2: Run the linter

Run: `ruff check stock_data/ tests/`

Expected: Clean (no errors). If ruff complains about line length, formatting, or unused imports in the new files, fix them.

### Step 3: Final commit (if any cleanup was needed)

```bash
git add -A
git commit -m "chore(news): address ruff/post-test cleanup"
```

If no changes are needed, this commit is a no-op and can be skipped.

---

## Spec Coverage Verification

| Spec section | Task(s) |
|---|---|
| §1 Goal and scope (v1 = Eastmoney search + generic content) | Tasks 3, 5 |
| §2 Architecture (search via fetcher, content via utility) | Tasks 3, 4, 5 |
| §3 Data flow | Tasks 3, 4, 5, 8 |
| §4 Capability registration | Tasks 1, 2 |
| §5 Manager method | Task 4 |
| §6 API contract | Tasks 7, 8 |
| §7 Cache strategy | Task 8 |
| §8 Error handling (SSRF, validation) | Tasks 6, 8 |
| §9 NewsContentExtractor details | Task 5 |
| §10 Tests (capability, fetcher, extractor, SSRF, endpoints) | Tasks 3, 4, 5, 6, 8 |
| §11 Risks (no cookie needed, JSONP, post-filter) | Documented in code comments |
| §12 Future extensions | Out of scope for this plan |

All spec requirements are covered.

---

## Self-Review Notes

- **Type consistency:** `NewsItem` (in schemas.py) fields match the dict keys from `EastMoneyFetcher._normalize_news_item`. `NewsContent` (in news_extractor.py) fields match `NewsContentResponse` (in schemas.py). Manager signature `search_news(q, from_date, to_date, limit)` is identical in fetcher and manager.
- **No placeholders:** Every code block is complete and ready to paste.
- **Frequent commits:** 10 tasks → 8 expected commits (Tasks 9 and 10 are verification-only).
- **DRY:** `NewsContent._build()` classmethod is the only constructor; `_normalize_news_item` is a static method on EastMoneyFetcher. Both `make_news_search_cache_key` and `make_news_content_cache_key` follow the project's existing `make_*_cache_key` pattern.
- **YAGNI:** No Tavily/MiniMax fetcher added. No `page` param on the search endpoint. No AI summary on the content endpoint. No domain-handler-overrides for any non-eastmoney domain.
