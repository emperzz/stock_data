# CLS Fetcher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 2 API endpoints (`/api/v1/cls/morning-briefing?date=YYYY-MM-DD` and `/api/v1/cls/market-review?date=YYYY-MM-DD`) backed by a new `ClsFetcher` that scrapes 财联社 (CLS) 早报 and 焦点复盘 subject streams via `__NEXT_DATA__` JSON extraction.

**Architecture:** ClsFetcher is a new `BaseFetcher` declaring 2 new `DataCapability` flags (`MORNING_BRIEFING`, `MARKET_RECAP`). Manager routes via `_with_failover` (capability-based, not source-pinned) so a future EastMoney fetcher can join the chain. Routes consume `get_cls_feed_cache()` (new 3600s TTL TTLCache) and surface `(None, "")` from manager as 404, distinct from `DataFetchError` → 503.

**Tech Stack:** Python 3.11+, FastAPI, `requests`, `beautifulsoup4`, `cachetools.TTLCache`, Pydantic v2, `pytest`. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-07-14-cls-fetcher-design.md` (review-verified READY FOR IMPLEMENTATION across 3 review rounds).

---

## File Structure

| File | Role | Action |
|---|---|---|
| `stock_data/data_provider/base.py` | `DataCapability` enum + `CAPABILITY_TO_METHOD` table | modify |
| `stock_data/data_provider/manager.py` | manager methods + `create_default_manager()` registration | modify |
| `stock_data/data_provider/fetchers/cls_fetcher.py` | fetcher implementation | **new** |
| `stock_data/data_provider/fetchers/__init__.py` | export | modify |
| `stock_data/api/schemas.py` | `ClsArticle` + `ClsFeedResponse` | modify |
| `stock_data/api/cache.py` | new TTLCache instance + key builder | modify |
| `stock_data/api/routes/cls.py` | 2 endpoints | **new** |
| `stock_data/api/routes/__init__.py` | re-export `cls_router` | modify |
| `stock_data/explorer/tags.py` | `CAPABILITY_LABELS` + `TAG_TO_TITLE` entries | modify |
| `stock_data/server.py` | include router with v1 prefix | modify |
| `tests/fixtures/cls_subject_list.json` | list-page `__NEXT_DATA__` fixture | **new** |
| `tests/fixtures/cls_article_detail.json` | detail-page `__NEXT_DATA__` fixture | **new** |
| `tests/test_cls_fetcher.py` | fetcher unit tests | **new** |
| `tests/test_cls_endpoints.py` | route unit tests | **new** |
| `tests/test_cls_live.py` | live network tests | **new** |
| `CLAUDE.md` | Fetcher table row + endpoint rows + capability routing table | modify |

---

## Task 1: Add 2 `DataCapability` flags + `CAPABILITY_TO_METHOD` entries

**Files:**
- Modify: `stock_data/data_provider/base.py:135-228`

- [ ] **Step 1: Add the 2 new flags to `DataCapability` enum**

Open `stock_data/data_provider/base.py`. Find the `class DataCapability(Flag):` block (line 135). Add the 2 new flags after the last existing flag (currently `STOCK_NEWS` at line 168):

```python
    STOCK_NEWS = auto()  # 个股新闻（按股票代码 → 列表）
    MORNING_BRIEFING = auto()  # 财联社早报（按日取全文本）
    MARKET_RECAP = auto()  # 财联社焦点复盘（按日取全文本）
```

- [ ] **Step 2: Add 2 entries to `CAPABILITY_TO_METHOD` dict**

In the same file, find `CAPABILITY_TO_METHOD: dict[DataCapability, str] = {` (line 189). Add the 2 new entries at the end of the dict (before the closing `}`):

```python
    DataCapability.STOCK_NEWS: "get_stock_news",
    DataCapability.MORNING_BRIEFING: "get_morning_briefing",
    DataCapability.MARKET_RECAP: "get_market_recap",
}
```

- [ ] **Step 3: Run capability-map test to verify**

Run: `.venv/Scripts/python.exe -m pytest tests/test_capability_method_map.py -v`
Expected: 1 test FAILS (the `test_every_capability_has_a_label_in_capability_labels` — we haven't added the `CAPABILITY_LABELS` entries yet, that's Task 2). The other 2-3 tests should still pass.

If only 1 test fails on `CAPABILITY_LABELS`, proceed. If more fail, fix before continuing.

- [ ] **Step 4: Commit**

```bash
git add stock_data/data_provider/base.py
git commit -m "feat(data_provider): add MORNING_BRIEFING + MARKET_RECAP capability flags"
```

---

## Task 2: Add `CAPABILITY_LABELS` + `TAG_TO_TITLE` entries

**Files:**
- Modify: `stock_data/explorer/tags.py:18-58`

- [ ] **Step 1: Add `"cls"` to `TAG_TO_TITLE`**

Open `stock_data/explorer/tags.py`. Find `TAG_TO_TITLE: dict[str, str] = {` (line 18). Add the `cls` entry at the end of the dict:

```python
    "news":          "新闻",
    "cls":           "财联社",
}
```

- [ ] **Step 2: Add 2 entries to `CAPABILITY_LABELS`**

In the same file, find `CAPABILITY_LABELS: dict[str, dict[str, str]] = {` (line 35). Add the 2 new entries at the end of the dict:

```python
    "STOCK_NEWS":           {"label": "个股新闻",         "icon": "📰"},
    "MORNING_BRIEFING":     {"label": "财联社早报",       "icon": "📰"},
    "MARKET_RECAP":         {"label": "财联社复盘",       "icon": "📊"},
}
```

- [ ] **Step 3: Re-run capability-map test**

Run: `.venv/Scripts/python.exe -m pytest tests/test_capability_method_map.py -v`
Expected: ALL tests PASS.

- [ ] **Step 4: Commit**

```bash
git add stock_data/explorer/tags.py
git commit -m "feat(explorer): add CAPABILITY_LABELS + TAG_TO_TITLE for cls endpoints"
```

---

## Task 3: Add Pydantic models `ClsArticle` + `ClsFeedResponse`

**Files:**
- Modify: `stock_data/api/schemas.py` (find the appropriate class list near the end)

- [ ] **Step 1: Add 2 new Pydantic models at the end of `schemas.py`**

Open `stock_data/api/schemas.py`. Append at the very end of the file:

```python
class ClsArticle(BaseModel):
    """Single CLS article (早报 / 复盘) — body_text is the BS4-extracted plain text."""

    article_id: int
    title: str
    brief: str
    author: str
    date: str  # YYYY-MM-DD
    ctime: int  # unix timestamp
    read_num: int
    comments_num: int
    share_num: int
    images: list[str] = []
    body_text: str  # BS4 抽出的纯文本，保留段落分隔（get_text("\n", strip=True) + 折叠空行）


class ClsFeedResponse(BaseModel):
    """Response shape for /api/v1/cls/morning-briefing and /api/v1/cls/market-review."""

    subject: str  # "morning_briefing" | "market_review"
    subject_id: int
    date: str  # 入参 date
    article: ClsArticle | None  # None → 404
    source: str = "cls"  # route 层用 manager_result[1] 覆盖；默认 "cls" 用于单测构造
```

- [ ] **Step 2: Verify import works**

Run: `.venv/Scripts/python.exe -c "from stock_data.api.schemas import ClsArticle, ClsFeedResponse; print(ClsFeedResponse(subject='morning_briefing', subject_id=1151, date='2026-07-14', article=None).model_dump())"`
Expected: prints a dict with `subject='morning_briefing'`, `subject_id=1151`, `date='2026-07-14'`, `article=None`, `source='cls'`.

- [ ] **Step 3: Commit**

```bash
git add stock_data/api/schemas.py
git commit -m "feat(api): add ClsArticle + ClsFeedResponse Pydantic models"
```

---

## Task 4: Add CLS feed cache infrastructure

**Files:**
- Modify: `stock_data/api/cache.py`

- [ ] **Step 1: Add TTL constant + cache instance**

Open `stock_data/api/cache.py`. Add this after the existing TTL constants (after line 46, end of the TTL constants block):

```python
_TTL_CLS_FEED = int(os.getenv("CACHE_TTL_CLS_FEED", "3600"))  # CLS 早报/复盘 (1h, immutable)
```

Then add the cache instance after `_news_flash_cache` (line 64):

```python
_news_flash_cache: TTLCache = TTLCache(maxsize=64, ttl=_TTL_NEWS_FLASH)
_cls_feed_cache: TTLCache = TTLCache(maxsize=512, ttl=_TTL_CLS_FEED)
```

- [ ] **Step 2: Add accessor + key builder at the end of the file**

Append at the end of `stock_data/api/cache.py`:

```python
def get_cls_feed_cache() -> TTLCache:
    """Return the CLS feed (早报/复盘) cache instance (TTL 3600s by default)."""
    return _cls_feed_cache


def make_cls_feed_cache_key(subject: str, date: str) -> str:
    """Build the cache key for a CLS feed entry. Subject is the namespace
    ('morning_briefing' or 'market_review') so the two endpoints don't
    collide on the same date."""
    return f"cls:{subject}:{date}"
```

- [ ] **Step 3: Verify import works**

Run: `.venv/Scripts/python.exe -c "from stock_data.api.cache import get_cls_feed_cache, make_cls_feed_cache_key; print(make_cls_feed_cache_key('morning_briefing', '2026-07-14')); c = get_cls_feed_cache(); print(c.ttl)"`
Expected: prints `cls:morning_briefing:2026-07-14` and `3600`.

- [ ] **Step 4: Commit**

```bash
git add stock_data/api/cache.py
git commit -m "feat(api/cache): add cls_feed cache (3600s TTL) + key builder"
```

---

## Task 5: Capture real upstream fixtures (desensitized)

**Files:**
- Create: `tests/fixtures/cls_subject_list.json`
- Create: `tests/fixtures/cls_article_detail.json`

These fixtures mirror the real `__NEXT_DATA__` shape from CLS so tests don't drift from the actual upstream structure (per project memory `fixture-must-match-real-upstream`).

- [ ] **Step 1: Use playwright to grab real `__NEXT_DATA__` for both pages**

In a Python shell with playwright access (use a one-off script if needed), navigate to:
- `https://www.cls.cn/subject/1151` (morning briefing list)
- `https://www.cls.cn/detail/2425210` (morning briefing detail)

For each, run in the page console:
```js
const data = JSON.parse(document.querySelector('script#__NEXT_DATA__').textContent);
copy(data.props.pageProps.data);  // or .articleDetail for the detail page
```

The list page's `data.articles[]` and the detail page's `articleDetail` are what you need.

- [ ] **Step 2: Write `tests/fixtures/cls_subject_list.json`**

Save the desensitized `data` from the list page (subject_id=1151) to this file. Truncate `articles` to 3 entries; redact `read_num` to 100, `comments_num` to 10, `share_num` to 100; keep `article_id`/`article_title`/`article_brief`/`article_author`/`article_time`/`subjects` exact.

The top-level structure should be:
```json
{
  "id": 1151,
  "name": "有声早报",
  "description": "...",
  "articles": [ {...}, {...}, {...} ]
}
```

- [ ] **Step 3: Write `tests/fixtures/cls_article_detail.json`**

Save the desensitized `articleDetail` from the detail page (article_id=2425210) to this file. Keep the `content` field intact (it has HTML structure the body_text test will exercise). Redact `read_num` to 100, `commentNum` to 10.

Top-level structure:
```json
{
  "id": 2425210,
  "title": "【早报】...",
  "brief": "...",
  "content": "<p>...</p>",
  "ctime": 1783983600,
  "readingNum": 100,
  "author": {"name": "财联社"},
  "commentNum": 10,
  "images": [],
  "subject": [...]
}
```

- [ ] **Step 4: Verify fixture structure**

Run: `.venv/Scripts/python.exe -c "import json; d = json.load(open('tests/fixtures/cls_subject_list.json')); assert 'articles' in d and len(d['articles']) >= 1; d2 = json.load(open('tests/fixtures/cls_article_detail.json')); assert 'content' in d2 and d2['content'].startswith('<p>')"`
Expected: no error (silent success).

- [ ] **Step 5: Commit**

```bash
git add tests/fixtures/cls_subject_list.json tests/fixtures/cls_article_detail.json
git commit -m "test(cls): add real-upstream-shape fixtures (list + detail)"
```

---

## Task 6: Write failing test for `_parse_next_data` + implement it

**Files:**
- Create: `tests/test_cls_fetcher.py`
- Create: `stock_data/data_provider/fetchers/cls_fetcher.py`

- [ ] **Step 1: Create the fetcher skeleton with stub `_parse_next_data`**

Create `stock_data/data_provider/fetchers/cls_fetcher.py` with this minimal content:

```python
"""财联社 (CLS) HTTP fetcher — 早报 + 焦点复盘.

数据源:
- 列表: GET https://www.cls.cn/subject/{1151│1135}  →  __NEXT_DATA__.props.pageProps.data.articles[]
- 详情: GET https://www.cls.cn/detail/{article_id}    →  __NEXT_DATA__.props.pageProps.articleDetail

List page returns ~20 most recent articles (~20-28 day window — CLS has no
pagination API; requests for older dates return 404).

Capabilities: MORNING_BRIEFING (subject 1151) | MARKET_RECAP (subject 1135).
"""

import json
import logging
import os
import re
from datetime import datetime
from typing import Any

import requests

from ..base import BaseFetcher, DataCapability, DataFetchError
from ..core.types import safe_int

logger = logging.getLogger(__name__)

# CLS list page 早报 subject id (verified 2026-07-14)
CLS_SUBJECT_MORNING_BRIEFING = 1151
# CLS list page 焦点复盘 subject id (verified 2026-07-14)
CLS_SUBJECT_MARKET_RECAP = 1135

CLS_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36"

# Subject id → human-readable name (used in error messages and as cache namespace)
CLS_SUBJECT_NAMES: dict[int, str] = {
    CLS_SUBJECT_MORNING_BRIEFING: "morning_briefing",
    CLS_SUBJECT_MARKET_RECAP: "market_review",
}

_NEXT_DATA_RE = re.compile(
    r'<script\s+id="__NEXT_DATA__"[^>]*>(.*?)</script>',
    re.DOTALL,
)


class ClsFetcher(BaseFetcher):
    """财联社 fetcher — 早报 (subject 1151) + 焦点复盘 (subject 1135)."""

    name = "ClsFetcher"
    priority = int(os.getenv("CLS_PRIORITY", "8"))
    supported_markets: set[str] = {"csi"}
    supported_data_types = (
        DataCapability.MORNING_BRIEFING | DataCapability.MARKET_RECAP
    )

    def is_available(self) -> bool:
        return True

    def _normalize_data(self, df, stock_code):
        raise DataFetchError("ClsFetcher does not support historical K-line data")

    # ------------------------------------------------------------------
    # Internal: __NEXT_DATA__ JSON extraction
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_next_data(html: str) -> dict[str, Any]:
        """Extract the __NEXT_DATA__ JSON object embedded in the SSR HTML.

        Raises DataFetchError if the script tag is missing or the JSON
        is malformed. Returns the parsed dict.
        """
        if not html:
            raise DataFetchError("[ClsFetcher] empty HTML body")
        m = _NEXT_DATA_RE.search(html)
        if m is None:
            raise DataFetchError(
                "[ClsFetcher] __NEXT_DATA__ script tag not found in HTML"
            )
        try:
            return json.loads(m.group(1))
        except (ValueError, json.JSONDecodeError) as e:
            raise DataFetchError(f"[ClsFetcher] __NEXT_DATA__ JSON parse failed: {e}") from e
```

- [ ] **Step 2: Create the test file with the first failing test**

Create `tests/test_cls_fetcher.py`:

```python
"""Tests for ClsFetcher — uses real-upstream-shape fixtures from
tests/fixtures/cls_*.json (per project memory: fixture must mirror real
upstream, not just field names/types)."""

import json
import pathlib

import pytest

from stock_data.data_provider.base import DataFetchError
from stock_data.data_provider.fetchers.cls_fetcher import ClsFetcher

FIXTURE_DIR = pathlib.Path(__file__).parent / "fixtures"


@pytest.fixture
def fetcher() -> ClsFetcher:
    return ClsFetcher()


@pytest.fixture
def list_html() -> str:
    """Wrap fixture JSON in the full __NEXT_DATA__ envelope the way CLS SSR does.

    The fixture file is the inner `data` object (what the fetcher sees at
    `__NEXT_DATA__.props.pageProps.data`). The wrapper adds the upstream
    `props.pageProps` envelope around it so the fetcher can navigate
    `.props.pageProps.data.articles[]` correctly.
    """
    inner = json.loads((FIXTURE_DIR / "cls_subject_list.json").read_text(encoding="utf-8"))
    envelope = {"props": {"pageProps": {"data": inner}}}
    return f'<html><body><script id="__NEXT_DATA__" type="application/json">{json.dumps(envelope, ensure_ascii=False)}</script></body></html>'


@pytest.fixture
def detail_html() -> str:
    """Same wrapping pattern as list_html, but for the detail page (articleDetail)."""
    inner = json.loads((FIXTURE_DIR / "cls_article_detail.json").read_text(encoding="utf-8"))
    envelope = {"props": {"pageProps": {"articleDetail": inner}}}
    return f'<html><body><script id="__NEXT_DATA__" type="application/json">{json.dumps(envelope, ensure_ascii=False)}</script></body></html>'


def test_parse_next_data_valid(fetcher, list_html):
    """Standard SSR HTML → returns parsed JSON dict."""
    result = fetcher._parse_next_data(list_html)
    assert isinstance(result, dict)
    assert result["id"] == 1151
    assert "articles" in result["articles"][0]


def test_parse_next_data_empty_html(fetcher):
    """Empty HTML body → DataFetchError."""
    with pytest.raises(DataFetchError, match="empty HTML body"):
        fetcher._parse_next_data("")


def test_parse_next_data_no_script_tag(fetcher):
    """HTML without __NEXT_DATA__ → DataFetchError."""
    with pytest.raises(DataFetchError, match="__NEXT_DATA__ script tag not found"):
        fetcher._parse_next_data("<html><body>no script here</body></html>")


def test_parse_next_data_malformed_json(fetcher):
    """Truncated JSON inside the script tag → DataFetchError."""
    bad = '<script id="__NEXT_DATA__" type="application/json">{"id": 1151,</script>'
    with pytest.raises(DataFetchError, match="JSON parse failed"):
        fetcher._parse_next_data(bad)
```

- [ ] **Step 3: Run the tests, expect 1 pass + 3 fail (only valid-HTML passes)**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cls_fetcher.py -v`
Expected:
- `test_parse_next_data_valid` PASSES (skeleton already implements it)
- The other 3 fail (skeleton already raises for them too — these are the "negative" tests, not the failing-test-first pattern)

If any test fails unexpectedly, fix the skeleton's `_parse_next_data`.

- [ ] **Step 4: Commit**

```bash
git add stock_data/data_provider/fetchers/cls_fetcher.py tests/test_cls_fetcher.py
git commit -m "feat(cls): add ClsFetcher skeleton + _parse_next_data + initial tests"
```

---

## Task 7: `_parse_subject_articles` + `_find_article_id_by_date`

**Files:**
- Modify: `stock_data/data_provider/fetchers/cls_fetcher.py` (add 2 methods)
- Modify: `tests/test_cls_fetcher.py` (add tests)

- [ ] **Step 1: Add the 2 methods to ClsFetcher**

In `stock_data/data_provider/fetchers/cls_fetcher.py`, add these methods after `_parse_next_data`:

```python
    # ------------------------------------------------------------------
    # Internal: list page parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_subject_articles(subject_id: int, html: str, limit: int = 20) -> list[dict]:
        """Parse the list-page __NEXT_DATA__ → list of normalized article dicts.

        Path: __NEXT_DATA__.props.pageProps.data.articles[]
        Each article is normalized to: {article_id, title, brief, author, ctime,
        date (YYYY-MM-DD), read_num, comments_num, share_num, images}.

        Returns at most `limit` entries (default 20, matching upstream's
        observed article count per subject).
        """
        next_data = ClsFetcher._parse_next_data(html)
        # Validate the shape — if subject_id mismatch, this is a real upstream change
        actual_subject_id = next_data.get("id")
        if actual_subject_id is not None and int(actual_subject_id) != int(subject_id):
            logger.warning(
                f"[ClsFetcher] subject_id mismatch: requested={subject_id} "
                f"upstream={actual_subject_id}; parsing anyway"
            )
        articles_raw = (
            next_data.get("props", {})
            .get("pageProps", {})
            .get("data", {})
            .get("articles", [])
        )
        out: list[dict] = []
        for raw in articles_raw[:limit]:
            article_id = safe_int(raw.get("article_id"))
            if article_id is None or article_id == 0:
                continue
            ctime = safe_int(raw.get("article_time"))
            date = (
                datetime.fromtimestamp(int(ctime)).strftime("%Y-%m-%d")
                if ctime
                else ""
            )
            out.append(
                {
                    "article_id": int(article_id),
                    "title": str(raw.get("article_title", "")),
                    "brief": str(raw.get("article_brief", "")),
                    "author": str(raw.get("article_author", "")),
                    "ctime": int(ctime) if ctime else 0,
                    "date": date,
                    "read_num": int(safe_int(raw.get("read_num")) or 0),
                    "comments_num": int(safe_int(raw.get("comments_num")) or 0),
                    "share_num": int(safe_int(raw.get("share_num")) or 0),
                    "images": [str(raw.get("article_img", ""))] if raw.get("article_img") else [],
                }
            )
        return out

    @staticmethod
    def _find_article_id_by_date(
        articles: list[dict], date: str
    ) -> int | None:
        """Find the article_id whose `date` matches the given YYYY-MM-DD.

        Linear scan — the upstream returns ~20 entries so a dict index is overkill.
        Returns None if no match (route layer should map None → 404).
        """
        for art in articles:
            if art.get("date") == date:
                return int(art["article_id"])
        return None
```

- [ ] **Step 2: Add tests**

Append to `tests/test_cls_fetcher.py`:

```python
def test_parse_subject_articles_normal(fetcher, list_html):
    """Standard list HTML → returns normalized list."""
    arts = fetcher._parse_subject_articles(1151, list_html)
    assert isinstance(arts, list)
    assert len(arts) >= 1
    first = arts[0]
    # All canonical fields present
    for k in ("article_id", "title", "brief", "author", "ctime", "date", "read_num", "comments_num", "share_num", "images"):
        assert k in first, f"missing field: {k}"
    # date format check
    assert len(first["date"]) == 10 and first["date"][4] == "-"
    # article_id is a positive int
    assert first["article_id"] > 0


def test_parse_subject_articles_limit(fetcher, list_html):
    """limit=2 → returns at most 2 articles."""
    arts = fetcher._parse_subject_articles(1151, list_html, limit=2)
    assert len(arts) <= 2


def test_parse_subject_articles_empty(fetcher):
    """HTML with empty articles list → returns []."""
    empty_html = f'<html><script id="__NEXT_DATA__" type="application/json">{{"id":1151,"articles":[]}}</script></html>'
    arts = fetcher._parse_subject_articles(1151, empty_html)
    assert arts == []


def test_find_article_id_by_date_match(fetcher, list_html):
    """Find article_id for a date that exists in the fixture."""
    arts = fetcher._parse_subject_articles(1151, list_html)
    assert len(arts) >= 1
    target_date = arts[0]["date"]
    found = fetcher._find_article_id_by_date(arts, target_date)
    assert found == arts[0]["article_id"]


def test_find_article_id_by_date_no_match(fetcher, list_html):
    """Date that doesn't appear in the fixture → None."""
    arts = fetcher._parse_subject_articles(1151, list_html)
    assert fetcher._find_article_id_by_date(arts, "2020-01-01") is None
```

- [ ] **Step 3: Run tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cls_fetcher.py -v`
Expected: ALL 9 tests (4 from Task 6 + 5 from this task) PASS.

- [ ] **Step 4: Commit**

```bash
git add stock_data/data_provider/fetchers/cls_fetcher.py tests/test_cls_fetcher.py
git commit -m "feat(cls): add _parse_subject_articles + _find_article_id_by_date"
```

---

## Task 8: `_fetch_article_detail` + `_extract_body_text` + image dedup

**Files:**
- Modify: `stock_data/data_provider/fetchers/cls_fetcher.py` (add 2 methods + 1 helper)
- Modify: `tests/test_cls_fetcher.py` (add tests)

- [ ] **Step 1: Add the 3 methods/helpers**

Append to `ClsFetcher` class in `stock_data/data_provider/fetchers/cls_fetcher.py`:

```python
    # ------------------------------------------------------------------
    # Internal: detail page parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_body_text(html_content: str) -> str:
        """BS4 抽出纯文本，保留段落分隔。

        get_text(separator='\\n') 让 <p> 之间的换行保留；strip=True 去行内空白；
        最后 re.sub 折叠连续 3+ 空行为 2 个（避免 <p>嵌套产生过多空行）。
        """
        if not html_content:
            return ""
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html_content, "lxml")
        text = soup.get_text("\n", strip=True)
        # 折叠连续 3+ 空行为 2 个
        return re.sub(r"\n{3,}", "\n\n", text)

    @staticmethod
    def _dedup_images(article_detail: dict) -> list[str]:
        """合并 `images` 字段和 `content` 内 <img src>，去重保序。"""
        seen: set[str] = set()
        out: list[str] = []
        # 1) articleDetail.images[] 优先
        for url in article_detail.get("images", []) or []:
            if url and url not in seen:
                seen.add(url)
                out.append(str(url))
        # 2) 从 content HTML 里提取 <img src>
        content = article_detail.get("content", "") or ""
        if content:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(content, "lxml")
            for img in soup.find_all("img"):
                src = img.get("src")
                if src and src not in seen:
                    seen.add(src)
                    out.append(str(src))
        return out

    @staticmethod
    def _fetch_article_detail(article_id: int, html: str) -> dict | None:
        """Parse a detail-page __NEXT_DATA__ → ClsArticle-shaped dict.

        Path: __NEXT_DATA__.props.pageProps.articleDetail
        Fields: id, title, brief, content (HTML), ctime, readingNum, author.name,
                commentNum, images[], subject[].

        Returns None if the articleDetail is missing (CLS returns an empty
        object for invalid IDs).
        """
        next_data = ClsFetcher._parse_next_data(html)
        detail = (
            next_data.get("props", {})
            .get("pageProps", {})
            .get("articleDetail", {})
        )
        # CLS returns an empty dict (or just an error code) for invalid article IDs
        if not detail or not detail.get("id"):
            return None
        ctime = safe_int(detail.get("ctime")) or 0
        date = (
            datetime.fromtimestamp(int(ctime)).strftime("%Y-%m-%d")
            if ctime
            else ""
        )
        body_text = ClsFetcher._extract_body_text(detail.get("content", "") or "")
        images = ClsFetcher._dedup_images(detail)
        author_obj = detail.get("author") or {}
        return {
            "article_id": int(detail["id"]),
            "title": str(detail.get("title", "")),
            "brief": str(detail.get("brief", "")),
            "author": str(author_obj.get("name", "")) if isinstance(author_obj, dict) else "",
            "ctime": int(ctime),
            "date": date,
            "read_num": int(safe_int(detail.get("readingNum")) or 0),
            "comments_num": int(safe_int(detail.get("commentNum")) or 0),
            "share_num": 0,  # detail page doesn't expose share_num; list does
            "images": images,
            "body_text": body_text,
        }
```

- [ ] **Step 2: Add tests**

Append to `tests/test_cls_fetcher.py`:

```python
def test_extract_body_text_strips_html(fetcher):
    """body_text has no HTML tags, preserves paragraph separators."""
    html = "<p>第一段</p><p>第二段有<strong>加粗</strong></p><p>第三段</p>"
    out = fetcher._extract_body_text(html)
    assert "<" not in out and ">" not in out
    assert "第一段" in out
    assert "加粗" in out  # text content preserved
    # at least 2 newlines (paragraph separator)
    assert "\n" in out


def test_extract_body_text_empty(fetcher):
    assert fetcher._extract_body_text("") == ""


def test_extract_body_text_collapses_blank_lines(fetcher):
    """3+ consecutive newlines collapse to 2."""
    html = "<p>a</p><p></p><p></p><p></p><p>b</p>"
    out = fetcher._extract_body_text(html)
    assert "\n\n\n" not in out  # no 3+ consecutive newlines


def test_dedup_images(fetcher):
    detail = {
        "images": ["https://a.com/1.jpg", "https://a.com/2.jpg"],
        "content": '<p><img src="https://a.com/2.jpg"></p><p><img src="https://a.com/3.jpg"></p>',
    }
    out = fetcher._dedup_images(detail)
    assert out == [
        "https://a.com/1.jpg",  # from images field
        "https://a.com/2.jpg",  # appears in both — first occurrence wins
        "https://a.com/3.jpg",  # from content
    ]


def test_fetch_article_detail_normal(fetcher, detail_html):
    """Standard detail HTML → full ClsArticle-shaped dict."""
    art = fetcher._fetch_article_detail(2425210, detail_html)
    assert art is not None
    assert art["article_id"] == 2425210
    assert art["title"].startswith("【")
    assert len(art["body_text"]) > 100
    # date is YYYY-MM-DD
    assert len(art["date"]) == 10 and art["date"][4] == "-"
    # images is a list (possibly empty)
    assert isinstance(art["images"], list)


def test_fetch_article_detail_empty_dict(fetcher):
    """__NEXT_DATA__ with empty articleDetail → None."""
    html = '<html><script id="__NEXT_DATA__" type="application/json">{"props":{"pageProps":{"articleDetail":{}}}}</script></html>'
    assert fetcher._fetch_article_detail(99999, html) is None
```

- [ ] **Step 3: Run tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cls_fetcher.py -v`
Expected: ALL tests (4 + 5 + 6 = 15) PASS.

- [ ] **Step 4: Commit**

```bash
git add stock_data/data_provider/fetchers/cls_fetcher.py tests/test_cls_fetcher.py
git commit -m "feat(cls): add detail page parser (body_text + image dedup)"
```

---

## Task 9: Public methods `get_morning_briefing` + `get_market_recap`

**Files:**
- Modify: `stock_data/data_provider/fetchers/cls_fetcher.py` (add 2 public methods + 2 HTTP helpers)
- Modify: `tests/test_cls_fetcher.py` (add tests with mocked HTTP)

- [ ] **Step 1: Add HTTP helpers + public methods to ClsFetcher**

Append to `ClsFetcher` class:

```python
    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    def _http_get_text(self, url: str, *, timeout: int = 15) -> str:
        """Plain requests.get returning the response body text.

        CLS SSR pages don't fingerprint-block; no proxy / no UA rotation needed.
        On 4xx/5xx raises DataFetchError so the manager's _with_failover
        can route to the next fetcher (currently only ClsFetcher, but the
        contract is forward-compatible with EastMoney failover).
        """
        try:
            r = requests.get(
                url,
                headers={"User-Agent": CLS_UA},
                timeout=timeout,
            )
        except requests.RequestException as e:
            raise DataFetchError(f"[ClsFetcher] HTTP GET failed: {url} → {e}") from e
        if not (200 <= r.status_code < 300):
            raise DataFetchError(
                f"[ClsFetcher] HTTP {r.status_code} for {url} ({len(r.content)}B body)"
            )
        return r.text or ""

    # ------------------------------------------------------------------
    # Public methods (called by DataFetcherManager)
    # ------------------------------------------------------------------

    def get_morning_briefing(self, date: str) -> dict | None:
        """Return the 财联社早报 article for `date` (YYYY-MM-DD) or None if no article.

        Internally fetches the list page (subject 1151) to find the article_id
        for the given date, then fetches the detail page for the full body.
        Returns None when either step yields nothing (route layer maps to 404).
        """
        return self._get_subject_article(CLS_SUBJECT_MORNING_BRIEFING, date)

    def get_market_recap(self, date: str) -> dict | None:
        """Return the 财联社焦点复盘 article for `date` (YYYY-MM-DD) or None.

        Subject 1135; same orchestration as get_morning_briefing.
        """
        return self._get_subject_article(CLS_SUBJECT_MARKET_RECAP, date)

    def _get_subject_article(self, subject_id: int, date: str) -> dict | None:
        """Shared orchestration: list page → find article_id by date → detail page."""
        list_url = f"https://www.cls.cn/subject/{subject_id}"
        try:
            list_html = self._http_get_text(list_url)
        except DataFetchError:
            raise  # let the manager's _with_failover see it
        articles = self._parse_subject_articles(subject_id, list_html, limit=20)
        article_id = self._find_article_id_by_date(articles, date)
        if article_id is None:
            return None
        detail_url = f"https://www.cls.cn/detail/{article_id}"
        detail_html = self._http_get_text(detail_url)
        return self._fetch_article_detail(article_id, detail_html)
```

- [ ] **Step 2: Add tests with mocked HTTP (use `unittest.mock`)**

Append to `tests/test_cls_fetcher.py`:

```python
from unittest.mock import patch


def _wrap_fixture(filename: str, *, envelope_key: str) -> str:
    """Helper: wrap a fixture JSON in the full __NEXT_DATA__ envelope the way CLS SSR does.

    The fixture file is the inner object (e.g. `data` for list, `articleDetail` for detail).
    The wrapper adds the upstream `props.pageProps` envelope so the fetcher can
    navigate `.props.pageProps.<envelope_key>.<...>` correctly.

    Args:
        filename: fixture file name (in tests/fixtures/).
        envelope_key: the key under `pageProps` — `"data"` for list, `"articleDetail"` for detail.
    """
    inner = json.loads((FIXTURE_DIR / filename).read_text(encoding="utf-8"))
    envelope = {"props": {"pageProps": {envelope_key: inner}}}
    return f'<html><body><script id="__NEXT_DATA__" type="application/json">{json.dumps(envelope, ensure_ascii=False)}</script></body></html>'


def test_get_morning_briefing_full_path(fetcher):
    """Mock list+detail HTTP → full article dict returned."""
    list_html = _wrap_fixture("cls_subject_list.json", envelope_key="data")
    detail_html = _wrap_fixture("cls_article_detail.json", envelope_key="articleDetail")
    with patch.object(fetcher, "_http_get_text", side_effect=[list_html, detail_html]) as m:
        # pick a date that exists in the list fixture
        arts = fetcher._parse_subject_articles(1151, list_html)
        target_date = arts[0]["date"]
        art = fetcher.get_morning_briefing(target_date)
    assert art is not None
    assert art["article_id"] == 2425210
    assert len(art["body_text"]) > 100
    # 2 HTTP calls (list + detail)
    assert m.call_count == 2


def test_get_morning_briefing_not_found(fetcher):
    """Date not in list → returns None (only 1 HTTP call — no detail fetch)."""
    list_html = _wrap_fixture("cls_subject_list.json", envelope_key="data")
    with patch.object(fetcher, "_http_get_text", return_value=list_html) as m:
        art = fetcher.get_morning_briefing("2020-01-01")
    assert art is None
    # Only 1 HTTP call (list); no detail fetch on not-found
    assert m.call_count == 1


def test_get_market_recap_full_path(fetcher):
    """Same as morning_briefing but for subject 1135."""
    # Build a synthetic list HTML for subject 1135 with one article on a known date
    list_data = {
        "id": 1135,
        "articles": [
            {
                "article_id": 99999,
                "article_title": "【焦点复盘】test",
                "article_brief": "test brief",
                "article_author": "财联社",
                "article_time": 1783983600,  # 2026-07-14
                "read_num": 100,
                "comments_num": 5,
                "share_num": 10,
                "article_img": "",
            }
        ],
    }
    list_html = f'<html><script id="__NEXT_DATA__" type="application/json">{json.dumps({"props": {"pageProps": {"data": list_data}}}, ensure_ascii=False)}</script></html>'
    detail_html = _wrap_fixture("cls_article_detail.json", envelope_key="articleDetail")
    with patch.object(fetcher, "_http_get_text", side_effect=[list_html, detail_html]):
        art = fetcher.get_market_recap("2026-07-14")
    assert art is not None
    assert art["article_id"] == 2425210  # from the detail fixture


def test_get_morning_briefing_http_failure(fetcher):
    """If list HTTP fails → DataFetchError propagates (no swallow)."""
    with patch.object(fetcher, "_http_get_text", side_effect=DataFetchError("network down")):
        with pytest.raises(DataFetchError, match="network down"):
            fetcher.get_morning_briefing("2026-07-14")
```

- [ ] **Step 3: Run tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cls_fetcher.py -v`
Expected: ALL tests (15 + 4 = 19) PASS.

- [ ] **Step 4: Commit**

```bash
git add stock_data/data_provider/fetchers/cls_fetcher.py tests/test_cls_fetcher.py
git commit -m "feat(cls): add public get_morning_briefing + get_market_recap + HTTP layer"
```

---

## Task 10: Add `ClsFetcher` to `create_default_manager()` + export

**Files:**
- Modify: `stock_data/data_provider/manager.py` (find `create_default_manager()`)
- Modify: `stock_data/data_provider/fetchers/__init__.py`

- [ ] **Step 1: Read `create_default_manager()` to find the right insertion point**

Run: `grep -n "ClsFetcher\|CninfoFetcher\|ThsFetcher" stock_data/data_provider/manager.py | head -10`

- [ ] **Step 2: Add `ClsFetcher` to the fetcher instantiation block**

Open `stock_data/data_provider/manager.py`. Find the section where fetchers are instantiated (look for `CninfoFetcher()` or `BaiduFetcher()`). Add `ClsFetcher()` to the list in a sensible position (alphabetical or by priority order — match the existing style). Also add the import at the top of the file:

Add to imports at the top:
```python
from .fetchers.cls_fetcher import ClsFetcher
```

Add `ClsFetcher()` to the instantiation block (alongside the other fetchers). If the block uses `add_fetcher()` calls, add `manager.add_fetcher(ClsFetcher())`. The exact placement depends on the existing pattern — match it.

- [ ] **Step 3: Export `ClsFetcher` from the package**

Open `stock_data/data_provider/fetchers/__init__.py`. Add `ClsFetcher` to the imports/exports (mirror the style for other fetchers like `CninfoFetcher` or `ThsFetcher`).

- [ ] **Step 4: Verify import works and ClsFetcher is registered**

Run: `.venv/Scripts/python.exe -c "from stock_data.data_provider.manager import create_default_manager; m = create_default_manager(); print('ClsFetcher registered:', any(isinstance(f, type(m).__mro__[0]) for f in []))"`
Better verification:

Run: `.venv/Scripts/python.exe -c "from stock_data.data_provider.fetchers.cls_fetcher import ClsFetcher; from stock_data.data_provider.manager import create_default_manager; m = create_default_manager(); caps = [f for f in m._fetchers.values() if hasattr(f, 'supported_data_types') and f.supported_data_types & (1 << 23)]; print('ClsFetcher in manager:', any(isinstance(f, ClsFetcher) for f in m._fetchers.values()))"`

Expected: prints `ClsFetcher in manager: True`. (The exact introspection depends on manager internals; the simpler check: look up the fetcher by name.)

If the manager's internal API is different, use this alternative:
```python
from stock_data.data_provider.fetchers.cls_fetcher import ClsFetcher
from stock_data.data_provider.manager import create_default_manager
m = create_default_manager()
print(ClsFetcher.__name__ in [type(f).__name__ for f in m._fetchers.values()])
```

- [ ] **Step 5: Commit**

```bash
git add stock_data/data_provider/manager.py stock_data/data_provider/fetchers/__init__.py
git commit -m "feat(manager): register ClsFetcher in create_default_manager() + export"
```

---

## Task 11: Add 2 manager methods `get_morning_briefing` + `get_market_recap`

**Files:**
- Modify: `stock_data/data_provider/manager.py` (add methods near the other capability-routed methods, e.g. near `search_news` at line ~500)

- [ ] **Step 1: Find the right insertion point**

Run: `grep -n "def search_news\|def get_stock_news" stock_data/data_provider/manager.py`

- [ ] **Step 2: Add the 2 methods**

Add right after `search_news` (or in a logical news-bucket section):

```python
    # ---------- CLS 财联社早报 / 焦点复盘 ----------

    def get_morning_briefing(self, date: str) -> tuple[dict | None, str]:
        """Fetch 财联社早报 for `date` (YYYY-MM-DD) via MORNING_BRIEFING-capable fetchers.

        Returns:
            Tuple of (article_dict_or_None, fetcher_name).
            - article_dict_or_None: ClsArticle-shaped dict, or None if the date
              has no published article (route layer maps None → 404).
            - fetcher_name: "cls" (current only ClsFetcher implements this).
        """
        return self._with_failover(
            capability=DataCapability.MORNING_BRIEFING,
            market="csi",
            op_label=f"get_morning_briefing {date}",
            call=lambda f: f.get_morning_briefing(date),
            allow_none=True,
            return_source=True,
        )

    def get_market_recap(self, date: str) -> tuple[dict | None, str]:
        """Fetch 财联社焦点复盘 for `date` (YYYY-MM-DD) via MARKET_RECAP-capable fetchers.

        Same return semantics as get_morning_briefing.
        """
        return self._with_failover(
            capability=DataCapability.MARKET_RECAP,
            market="csi",
            op_label=f"get_market_recap {date}",
            call=lambda f: f.get_market_recap(date),
            allow_none=True,
            return_source=True,
        )
```

- [ ] **Step 3: Verify import works**

Run: `.venv/Scripts/python.exe -c "from stock_data.data_provider.manager import create_default_manager; m = create_default_manager(); print(hasattr(m, 'get_morning_briefing'), hasattr(m, 'get_market_recap'))"`
Expected: `True True`.

- [ ] **Step 4: Commit**

```bash
git add stock_data/data_provider/manager.py
git commit -m "feat(manager): add get_morning_briefing + get_market_recap via _with_failover"
```

---

## Task 12: Create the 2 routes in `api/routes/cls.py`

**Files:**
- Create: `stock_data/api/routes/cls.py`
- Modify: `stock_data/api/routes/__init__.py` (re-export `cls_router` if applicable)

- [ ] **Step 1: Create `stock_data/api/routes/cls.py`**

```python
"""财联社 早报 / 焦点复盘 endpoints.

Mounted by `stock_data.server` with prefix="/api/v1"; this router's own paths
are /cls/morning-briefing and /cls/market-review. Both require ?date=YYYY-MM-DD
and return the single article for that date (or 404 if not published).
"""

from datetime import date as _date
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Query

from ..cache import (
    get_cls_feed_cache,
    make_cls_feed_cache_key,
)
from ..endpoint_meta import endpoint_meta
from ..schemas import ClsFeedResponse
from .errors import map_errors
from .helpers import get_manager

cls_router = APIRouter()

# Hard window limit: 30 days. CLS list page returns ~20-28 days; 30 is a
# safety margin that catches typos (e.g. user passes 2020-01-01) early
# without rejecting legit "yesterday" requests.
_DATE_WINDOW_DAYS = 30


def _validate_date(date_str: str) -> str:
    """Validate the ?date= query param. Raises HTTPException(400) on bad input.

    Returns the validated YYYY-MM-DD string.
    """
    if not date_str:
        raise HTTPException(status_code=400, detail="date is required (YYYY-MM-DD)")
    try:
        parsed = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"date must be YYYY-MM-DD (got {date_str!r})",
        )
    if parsed > _date.today():
        raise HTTPException(
            status_code=400,
            detail=f"date must not be in the future (got {date_str!r})",
        )
    if parsed < _date.today() - timedelta(days=_DATE_WINDOW_DAYS):
        raise HTTPException(
            status_code=400,
            detail=(
                f"date older than {_DATE_WINDOW_DAYS} days is outside the "
                f"CLS upstream window (got {date_str!r})"
            ),
        )
    return date_str


@cls_router.get(
    "/cls/morning-briefing",
    response_model=ClsFeedResponse,
    responses={
        400: {"description": "Invalid date"},
        404: {"description": "No article published for this date"},
        503: {"description": "All fetchers failed"},
    },
    tags=["cls"],
)
@endpoint_meta(
    summary="财联社早报（按日取最新早报全文）",
    markets=["csi"],
    capabilities=["MORNING_BRIEFING"],
    tags=["cls"],
)
@map_errors
@__import_cache_endpoint()
def get_morning_briefing(
    date: str = Query(description="日期 YYYY-MM-DD"),
) -> ClsFeedResponse:
    """Return the 财联社早报 article for `date`."""
    date = _validate_date(date)
    manager = get_manager()
    article, source = manager.get_morning_briefing(date)
    if article is None:
        raise HTTPException(
            status_code=404,
            detail=f"No 财联社早报 article for {date}",
        )
    return ClsFeedResponse(
        subject="morning_briefing",
        subject_id=1151,
        date=date,
        article=article,
        source=source,
    )


@cls_router.get(
    "/cls/market-review",
    response_model=ClsFeedResponse,
    responses={
        400: {"description": "Invalid date"},
        404: {"description": "No article published for this date"},
        503: {"description": "All fetchers failed"},
    },
    tags=["cls"],
)
@endpoint_meta(
    summary="财联社焦点复盘（按日取最新复盘全文）",
    markets=["csi"],
    capabilities=["MARKET_RECAP"],
    tags=["cls"],
)
@map_errors
@__import_cache_endpoint()
def get_market_recap(
    date: str = Query(description="日期 YYYY-MM-DD"),
) -> ClsFeedResponse:
    """Return the 财联社焦点复盘 article for `date`."""
    date = _validate_date(date)
    manager = get_manager()
    article, source = manager.get_market_recap(date)
    if article is None:
        raise HTTPException(
            status_code=404,
            detail=f"No 财联社焦点复盘 article for {date}",
        )
    return ClsFeedResponse(
        subject="market_review",
        subject_id=1135,
        date=date,
        article=article,
        source=source,
    )
```

**STOP** — the `@__import_cache_endpoint()` placeholder above needs to be replaced with the actual `cache_endpoint` decorator. The full implementation has separate decorators for the two endpoints. Let me correct this:

- [ ] **Step 1 (corrected): Create the file with proper cache_endpoint per endpoint**

Replace the file content above with the corrected version (the `@__import_cache_endpoint()` placeholders must be replaced):

For the morning_briefing endpoint, use:
```python
from ..cache import cache_endpoint  # add to imports

@cache_endpoint(
    cache_fn=lambda *args, **kwargs: get_cls_feed_cache(),
    key_builder=lambda date: make_cls_feed_cache_key("morning_briefing", date),
    hit_label="cls_morning_briefing",
)
def get_morning_briefing(...) -> ClsFeedResponse:
    ...
```

For the market_recap endpoint, use:
```python
@cache_endpoint(
    cache_fn=lambda *args, **kwargs: get_cls_feed_cache(),
    key_builder=lambda date: make_cls_feed_cache_key("market_review", date),
    hit_label="cls_market_review",
)
def get_market_recap(...) -> ClsFeedResponse:
    ...
```

The decorator order MUST be (from outermost to innermost):
```python
@cls_router.get(...)     # 1. FastAPI routing
@endpoint_meta(...)      # 2. Manifest registration (must be inner to router.get per CLAUDE.md)
@map_errors              # 3. Error mapping
@cache_endpoint(...)     # 4. Cache (innermost — wraps the actual handler)
def handler(...): ...
```

**Verify the `cache_endpoint` import**: open `stock_data/api/cache.py` and confirm it exports `cache_endpoint`. If not, also add it (it should already exist as a public function — see `news.py` for usage).

- [ ] **Step 2: Re-export `cls_router` from `api/routes/__init__.py` if the package uses re-exports**

Open `stock_data/api/routes/__init__.py`. Check if other routers are re-exported there. If yes, add `from .cls import cls_router` and include in `__all__`. If no, skip this step.

- [ ] **Step 3: Verify the route module imports cleanly**

Run: `.venv/Scripts/python.exe -c "from stock_data.api.routes.cls import cls_router, get_morning_briefing, get_market_recap; print('routes OK:', len(cls_router.routes))"`
Expected: prints `routes OK: 2`.

- [ ] **Step 4: Commit**

```bash
git add stock_data/api/routes/cls.py
git commit -m "feat(api): add /cls/morning-briefing + /cls/market-review routes"
```

---

## Task 13: Wire `cls_router` into `stock_data/server.py`

**Files:**
- Modify: `stock_data/server.py` (find the `include_router` block)

- [ ] **Step 1: Find existing router includes**

Run: `grep -n "include_router" stock_data/server.py`

- [ ] **Step 2: Add `cls_router` include**

Open `stock_data/server.py`. Add an import at the top alongside other router imports:

```python
from .api.routes.cls import cls_router
```

Add the `include_router` call in the same block as the other 9 data routers:

```python
app.include_router(cls_router, prefix="/api/v1")
```

- [ ] **Step 3: Smoke-test the server starts and the routes are mounted**

Run: `.venv/Scripts/python.exe -c "from stock_data.server import app; routes = [r.path for r in app.routes if hasattr(r, 'path')]; cls_routes = [p for p in routes if '/cls/' in p]; print(cls_routes)"`
Expected: prints `['/api/v1/cls/morning-briefing', '/api/v1/cls/market-review']`.

- [ ] **Step 4: Commit**

```bash
git add stock_data/server.py
git commit -m "feat(server): include cls_router with /api/v1 prefix"
```

---

## Task 14: Write route unit tests

**Files:**
- Create: `tests/test_cls_endpoints.py`

- [ ] **Step 1: Create the test file**

```python
"""Route tests for /api/v1/cls/morning-briefing and /api/v1/cls/market-review.

Uses FastAPI's TestClient to exercise the full middleware + decorator stack
(@map_errors, @cache_endpoint, @endpoint_meta) without making real HTTP calls.
Manager + fetcher are mocked via monkeypatch of `get_manager()`.
"""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from stock_data.api.schemas import ClsArticle
from stock_data.server import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def sample_article() -> dict:
    return {
        "article_id": 2425210,
        "title": "【早报】test",
        "brief": "test brief",
        "author": "财联社",
        "ctime": 1783983600,
        "date": "2026-07-14",
        "read_num": 100,
        "comments_num": 5,
        "share_num": 10,
        "images": [],
        "body_text": "宏观新闻\n\ntest body",
    }


def test_morning_briefing_success(client, sample_article, monkeypatch):
    """Valid date + manager returns article → 200 with full body."""
    mock_mgr = MagicMock()
    mock_mgr.get_morning_briefing.return_value = (sample_article, "cls")
    # Patch the get_manager() helper that the route uses to fetch the manager.
    from stock_data.api.routes import cls as cls_routes
    monkeypatch.setattr(cls_routes, "get_manager", lambda: mock_mgr)
    # Bypass the cache (force the handler to run)
    from stock_data.api.cache import get_cls_feed_cache
    get_cls_feed_cache().clear()
    r = client.get("/api/v1/cls/morning-briefing?date=2026-07-14")
    assert r.status_code == 200
    body = r.json()
    assert body["subject"] == "morning_briefing"
    assert body["subject_id"] == 1151
    assert body["date"] == "2026-07-14"
    assert body["source"] == "cls"
    assert body["article"]["article_id"] == 2425210


def test_morning_briefing_missing_date(client):
    """No ?date= → 400."""
    r = client.get("/api/v1/cls/morning-briefing")
    assert r.status_code == 400


def test_morning_briefing_bad_date_format(client):
    """?date=2026/07/14 → 400."""
    r = client.get("/api/v1/cls/morning-briefing?date=2026/07/14")
    assert r.status_code == 400


def test_morning_briefing_future_date(client):
    """?date=2099-01-01 → 400."""
    r = client.get("/api/v1/cls/morning-briefing?date=2099-01-01")
    assert r.status_code == 400


def test_morning_briefing_old_date(client):
    """?date=2020-01-01 → 400 (outside 30-day window)."""
    r = client.get("/api/v1/cls/morning-briefing?date=2020-01-01")
    assert r.status_code == 400


def test_morning_briefing_not_found(client, monkeypatch):
    """Manager returns (None, "") → 404."""
    mock_mgr = MagicMock()
    mock_mgr.get_morning_briefing.return_value = (None, "")
    from stock_data.api.routes import cls as cls_routes
    monkeypatch.setattr(cls_routes, "get_manager", lambda: mock_mgr)
    from stock_data.api.cache import get_cls_feed_cache
    get_cls_feed_cache().clear()
    r = client.get("/api/v1/cls/morning-briefing?date=2026-07-14")
    assert r.status_code == 404


def test_market_recap_success(client, sample_article, monkeypatch):
    """Same shape for /market-review."""
    mock_mgr = MagicMock()
    mock_mgr.get_market_recap.return_value = (sample_article, "cls")
    from stock_data.api.routes import cls as cls_routes
    monkeypatch.setattr(cls_routes, "get_manager", lambda: mock_mgr)
    from stock_data.api.cache import get_cls_feed_cache
    get_cls_feed_cache().clear()
    r = client.get("/api/v1/cls/market-review?date=2026-07-14")
    assert r.status_code == 200
    body = r.json()
    assert body["subject"] == "market_review"
    assert body["subject_id"] == 1135
```

- [ ] **Step 2: Run the tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cls_endpoints.py -v`
Expected: ALL 7 tests PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_cls_endpoints.py
git commit -m "test(cls): add route unit tests for /morning-briefing + /market-review"
```

---

## Task 15: Write live network tests (marked `live_network`)

**Files:**
- Create: `tests/test_cls_live.py`

- [ ] **Step 1: Create the live tests file**

```python
"""Live network tests for ClsFetcher — run only with `pytest -m live_network`
or `pytest -m ""` (CI use). Auto-downgraded to xfail on network failure by
tests/_network_guard.py."""

from datetime import date, timedelta

import pytest

from stock_data.data_provider.fetchers.cls_fetcher import ClsFetcher


@pytest.fixture
def fetcher() -> ClsFetcher:
    return ClsFetcher()


@pytest.mark.live_network
def test_live_get_morning_briefing_today(fetcher):
    """Real upstream call for today's date → returns article with non-empty body."""
    today = date.today().strftime("%Y-%m-%d")
    art = fetcher.get_morning_briefing(today)
    if art is None:
        pytest.xfail(f"No 早报 article for {today} (CLS hasn't published yet)")
    assert art["article_id"] > 0
    assert art["title"].startswith("【")
    assert len(art["body_text"]) > 100


@pytest.mark.live_network
def test_live_get_market_recap_today(fetcher):
    """Same for 复盘. 复盘 publishes at ~17:30; before that, today's article may not exist."""
    today = date.today().strftime("%Y-%m-%d")
    art = fetcher.get_market_recap(today)
    if art is None:
        pytest.xfail(f"No 复盘 article for {today}")
    assert art["article_id"] > 0
    assert len(art["body_text"]) > 100


@pytest.mark.live_network
def test_live_get_morning_briefing_yesterday(fetcher):
    """Yesterday's article should always exist (CLS publishes every weekday)."""
    yesterday = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
    art = fetcher.get_morning_briefing(yesterday)
    assert art is not None, f"No 早报 for {yesterday}"
    assert art["date"] == yesterday


@pytest.mark.live_network
def test_live_subject_list_window(fetcher):
    """List page should have ≥3 articles spanning ≥3 days (relaxed from spec to
    avoid weekend flakiness)."""
    # Internal helper for list-page fetch
    list_html = fetcher._http_get_text("https://www.cls.cn/subject/1151")
    articles = fetcher._parse_subject_articles(1151, list_html, limit=20)
    assert len(articles) >= 3
    distinct_dates = {a["date"] for a in articles}
    assert len(distinct_dates) >= 3
```

- [ ] **Step 2: Run only the non-live tests (default marker filter)**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cls_live.py -v`
Expected: all 4 tests are collected but xfail/skipped because `live_network` is excluded by default. No errors.

If you want to actually exercise them, run with `-m ""` (clear default deselect):

Run: `.venv/Scripts/python.exe -m pytest tests/test_cls_live.py -m live_network -v`
Expected: ALL 4 PASS (or xfail on the today tests if CLS hasn't published yet).

- [ ] **Step 3: Commit**

```bash
git add tests/test_cls_live.py
git commit -m "test(cls): add live_network tests for morning_briefing + market_recap"
```

---

## Task 16: Run the full test suite to verify nothing regressed

**Files:** none (verification only)

- [ ] **Step 1: Run the project's full test suite (default — skips `live_network`)**

Run: `.venv/Scripts/python.exe -m pytest -v`
Expected: ALL tests pass, including the new `tests/test_cls_fetcher.py`, `tests/test_cls_endpoints.py`, `tests/test_cls_live.py` (the live_network ones xfail or skip). Zero failures.

If any failures appear, fix them before proceeding. The likely candidates:
- `test_capability_method_map.py` (already verified in Task 1-2)
- `test_explorer_manifest_endpoint.py` (validates manifest consistency)
- `tests/test_fetcher_test.py` (validates the Stage 2 fetcher drill-down)

- [ ] **Step 2: Run linter**

Run: `ruff check .`
Expected: zero errors.

If errors appear (most likely unused imports), fix them.

- [ ] **Step 3: Commit (if any fixes were needed)**

```bash
git add -A
git commit -m "chore: address lint + regression fixes from full test run" --allow-empty
```

---

## Task 17: Update CLAUDE.md

**Files:**
- Modify: `CLAUDE.md` (Fetche r table + endpoint table + capability routing table)

- [ ] **Step 1: Find the relevant tables**

Run: `grep -n "ZzshareFetcher\|CninfoFetcher\|BaiduFetcher\|Fetcher & Capability Routing" CLAUDE.md | head -10`

- [ ] **Step 2: Add `ClsFetcher` row to the Fetcher overview table**

In the Fetcher overview table, add a new row (place it in priority order or alphabetical; match existing style):

```markdown
| `ClsFetcher` | 8 | csi | `MORNING_BRIEFING` `MARKET_RECAP` | none | 财联社早报 + 焦点复盘 via Next.js `__NEXT_DATA__` JSON; 20-28 day window (no upstream pagination) |
```

Adjust the `P` (priority) column to match the chosen position.

- [ ] **Step 3: Add 2 rows to the API → Capability routing table**

In the "API → Capability routing" section, add:

```markdown
| `get_morning_briefing` | `MORNING_BRIEFING` | ClsFetcher primary, ~20-28 day window |
| `get_market_recap` | `MARKET_RECAP` | ClsFetcher primary, ~20-28 day window |
```

(Place them in a sensible position — alphabetical or grouped with the other signal/news methods.)

- [ ] **Step 4: Verify CLAUDE.md renders correctly**

Run: `.venv/Scripts/python.exe -c "import re; md = open('CLAUDE.md').read(); assert 'ClsFetcher' in md and 'MORNING_BRIEFING' in md; print('OK')"`
Expected: prints `OK`.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(claude): add ClsFetcher + 2 routing rows"
```

---

## Self-Review

**Spec coverage:**

| Spec section | Task |
|---|---|
| §4.1 / §4.2 (API surface, error codes) | Task 12 (routes), Task 14 (route tests) |
| §5 (historical window) | Task 12 (`_validate_date`), Task 14 (`test_morning_briefing_old_date`) |
| §6 (Pydantic models) | Task 3 |
| §7.1 (manager methods) | Task 11 |
| §7.2 (fetcher methods) | Tasks 6-9 |
| §7.3 (capability flags) | Task 1 |
| §7.4 (CAPABILITY_LABELS) | Task 2 |
| §8 (cache) | Task 4, Task 12 |
| §9 (error mapping) | Task 12 (route explicit None → 404), Task 14 (asserts 400/404) |
| §10.1-10.4 (unit + fixture tests) | Tasks 5, 6-9, 14 |
| §10.5 (capability map test) | Task 2 (verifies via existing test) |
| §11 (file changes) | All 17 tasks |
| `create_default_manager()` registration | Task 10 |
| `tags.py::TAG_TO_TITLE` | Task 2 |
| `server.py` `include_router` | Task 13 |
| `CLAUDE.md` update | Task 17 |

**Type consistency check:**
- `ClsFetcher.get_morning_briefing(date) -> dict | None` defined in Task 9, called via `manager._with_failover` lambda in Task 11. ✓
- `manager.get_morning_briefing(date) -> tuple[dict | None, str]` defined in Task 11, consumed in Task 12 route. ✓
- `ClsFeedResponse.article: ClsArticle | None` (Task 3), route sets `article=manager_result[0]` (Task 12). ✓
- `_DATE_WINDOW_DAYS = 30` (Task 12) — matches spec §5 "today - 30 days" cut-off. ✓

**Placeholder scan:** No TBD/TODO/"implement later" remaining. The one `@__import_cache_endpoint()` placeholder in Task 12 Step 1 is explicitly flagged for replacement in Step 1 (corrected).

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-14-cls-fetcher-implementation.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration. Best for plans of this size (~17 tasks) where independent tasks can run in parallel.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints for review. Best when you want full visibility into each step.

**Which approach?**
