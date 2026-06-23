# ThsFetcher NEWS_FLASH Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `fetch_flash_news(limit)` method to `ThsFetcher` so the existing `/news/flash` endpoint can fall back from EastMoney (P6) to THS (P7) when the upstream fails.

**Architecture:** ThsFetcher declares `NEWS_FLASH` capability, paginates the THS upstream (`pageSize` is hard-coded to 20/page by the server) up to `limit` items, and returns the same `FlashNewsItem` dict shape EastMoney already produces. No changes to `base.py`, `manager.py`, `routes.py`, or `schemas.py` — the existing `_with_failover(NEWS_FLASH, "csi", ...)` will pick up ThsFetcher automatically.

**Tech Stack:** Python 3, FastAPI, pytest, requests (THS upstream is plain HTTP, no JA3 fingerprinting needed — project has no record of THS being bot-blocked for `get_hot_topics` either, which uses the same `requests.get` pattern).

---

## File Structure

| File | Responsibility |
|---|---|
| `stock_data/data_provider/fetchers/ths_fetcher.py` (modify) | Add `fetch_flash_news` method, add `NEWS_FLASH` to capabilities, add THS-specific constants |
| `tests/fixtures/ths_flash_news.json` (create) | Real upstream response, captured 2026-06-23 (memory: `fixture-must-match-real-upstream`) |
| `tests/test_ths_fetcher.py` (modify) | Add `TestFetchFlashNews` class — unit tests for the new method |
| `tests/test_manager_flash_news.py` (modify) | Add failover tests: EastMoney (P6) tried first, falls back to ThsFetcher (P7) on failure |
| `CLAUDE.md` (modify) | Doc sync: add ThsFetcher NEWS_FLASH to capability tables |

---

## Task 1: Capture real upstream fixture

**Files:**
- Create: `tests/fixtures/ths_flash_news.json`

- [ ] **Step 1: Re-capture real upstream response (single source of truth for tests)**

```bash
cd "D:/GitRepo/skills/stock_data"
curl -s -A "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36" \
  -H "Referer: https://news.10jqka.com.cn/realtimenews.html" \
  "https://news.10jqka.com.cn/tapp/news/push/stock?page=1&tag=&track=website" \
  -o tests/fixtures/ths_flash_news.json
```

Expected: file is non-empty (the upstream returns ~28KB with `code=200`, `data.list` of 20 items).

- [ ] **Step 2: Verify the file is well-formed JSON with the expected structure**

```bash
cd "D:/GitRepo/skills/stock_data"
python -c "
import json
d = json.load(open('tests/fixtures/ths_flash_news.json', encoding='utf-8'))
assert d['code'] == 200, f'expected code=200, got {d[\"code\"]}'
lst = d['data']['list']
assert len(lst) == 20, f'expected 20 items, got {len(lst)}'
for it in lst:
    assert 'title' in it and 'digest' in it and 'rtime' in it and 'url' in it
print(f'OK: {len(lst)} items, first id={lst[0][\"id\"]} rtime={lst[0][\"rtime\"]}')
"
```

Expected: `OK: 20 items, first id=... rtime=...` (no assertion error).

- [ ] **Step 3: Commit**

```bash
cd "D:/GitRepo/skills/stock_data"
git add tests/fixtures/ths_flash_news.json
git commit -m "test(ths): add real upstream fixture for flash news

Captured from https://news.10jqka.com.cn/tapp/news/push/stock?page=1 on
2026-06-23 (28KB, 20 items, code=200). Mirrors the live response
shape so the unit tests assert against real field names, types, and
ordering (per fixture-must-match-real-upstream memory).

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Add `_normalize_flash_item` static helper + failing test

**Files:**
- Modify: `stock_data/data_provider/fetchers/ths_fetcher.py:33-126` (add helper at end)
- Modify: `tests/test_ths_fetcher.py:1-80` (add test class)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_ths_fetcher.py` (after the existing `TestHistoricalNotSupported` class):

```python
class TestFetchFlashNewsNormalize:
    """Tests for the pure normalize helper (no network)."""

    def setup_method(self):
        self.fetcher = ThsFetcher()

    def test_normalize_flash_item_full(self):
        from datetime import datetime
        item = {
            "id": "4572951",
            "seq": "677638595",
            "title": "南向资金成交额超 1.7 万亿港元",
            "digest": "南向资金成交额超 1.7 万亿港元。",
            "url": "https://news.10jqka.com.cn/20260623/c677638595.shtml",
            "rtime": "1782181568",
        }
        result = self.fetcher._normalize_flash_item(item)
        assert result["title"] == "南向资金成交额超 1.7 万亿港元"
        assert result["url"] == "https://news.10jqka.com.cn/20260623/c677638595.shtml"
        assert result["source_domain"] == "news.10jqka.com.cn"
        # rtime=1782181568 → 2026-06-22 16:26:08 UTC (local tz may differ; verify just structure)
        assert result["publish_time"].startswith("2026-")
        assert len(result["publish_time"]) == 19  # "YYYY-MM-DD HH:MM:SS"
        assert result["snippet"] == "南向资金成交额超 1.7 万亿港元。"

    def test_normalize_flash_item_missing_optional(self):
        """Defensive: missing digest/rtime should still produce a row."""
        item = {
            "id": "1",
            "title": "标题",
            "url": "https://news.10jqka.com.cn/20260101/c1.shtml",
            # no rtime, no digest
        }
        result = self.fetcher._normalize_flash_item(item)
        assert result["title"] == "标题"
        assert result["url"] == "https://news.10jqka.com.cn/20260101/c1.shtml"
        assert result["source_domain"] == "news.10jqka.com.cn"
        assert result["publish_time"] == ""  # empty fallback
        assert result["snippet"] == ""  # empty fallback

    def test_normalize_flash_item_bad_rtime_keeps_raw(self):
        """If rtime is not a valid int, fall back to the raw string."""
        item = {
            "id": "2",
            "title": "t",
            "url": "https://news.10jqka.com.cn/x",
            "rtime": "not-a-number",
        }
        result = self.fetcher._normalize_flash_item(item)
        assert result["publish_time"] == "not-a-number"  # graceful fallback
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `python -m pytest tests/test_ths_fetcher.py::TestFetchFlashNewsNormalize -v`
Expected: FAIL with `AttributeError: 'ThsFetcher' object has no attribute '_normalize_flash_item'` (or similar import-time error).

- [ ] **Step 3: Implement the helper**

Add to `stock_data/data_provider/fetchers/ths_fetcher.py` (append at end of file, after `get_north_flow`):

```python
    # ------------------------------------------------------------------
    # 全球财经快讯 (Flash News) — 同花顺 7x24 实时流
    # ------------------------------------------------------------------

    _FLASH_NEWS_URL = "https://news.10jqka.com.cn/tapp/news/push/stock"
    # 上游 pageSize 硬编码 20/页(实测: pageSize/limit/num/size 等参数均无效)
    _FLASH_NEWS_PAGE_SIZE = 20
    # 与 EastMoneyFetcher.fetch_flash_news 对齐;路由层 Query(le=200) 也会拦
    _FLASH_NEWS_MAX_LIMIT = 200
    _FLASH_NEWS_MIN_LIMIT = 1
    # 单页 HTTP 超时(秒)
    _FLASH_NEWS_TIMEOUT = 10

    @staticmethod
    def _normalize_flash_item(item: dict) -> dict:
        """Convert one upstream record to the FlashNewsItem dict shape.

        与 EastMoneyFetcher.fetch_flash_news 输出 schema 对齐:
        {title, url, source_domain, publish_time, snippet}
        """
        # 防御: rtime 可能是 10 位 Unix timestamp、字符串数字、或脏数据
        rtime_raw = item.get("rtime", "")
        publish_time = ""
        if rtime_raw:
            try:
                from datetime import datetime
                publish_time = datetime.fromtimestamp(int(rtime_raw)).strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
            except (TypeError, ValueError, OSError):
                publish_time = str(rtime_raw)  # graceful fallback

        return {
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "source_domain": "news.10jqka.com.cn",
            "publish_time": publish_time,
            "snippet": item.get("digest", ""),
        }
```

- [ ] **Step 4: Run the test and verify it passes**

Run: `python -m pytest tests/test_ths_fetcher.py::TestFetchFlashNewsNormalize -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
cd "D:/GitRepo/skills/stock_data"
git add stock_data/data_provider/fetchers/ths_fetcher.py tests/test_ths_fetcher.py
git commit -m "feat(ths): add _normalize_flash_item helper for flash news

Pure transform: THS upstream record → FlashNewsItem dict.
Defensive against missing rtime / non-int rtime (falls back to raw).

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Add `fetch_flash_news` single-page + failing test

**Files:**
- Modify: `stock_data/data_provider/fetchers/ths_fetcher.py` (add method after `_normalize_flash_item`)
- Modify: `tests/test_ths_fetcher.py` (add `TestFetchFlashNewsSinglePage` class)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_ths_fetcher.py`:

```python
class TestFetchFlashNewsSinglePage:
    """Tests for fetch_flash_news(limit<=20): single upstream page."""

    def setup_method(self):
        self.fetcher = ThsFetcher()

    def test_fetch_one_page_uses_correct_url(self, monkeypatch):
        """Verify the upstream URL, params, and headers."""
        import json
        fixture = json.load(open("tests/fixtures/ths_flash_news.json", encoding="utf-8"))
        captured = {}

        def fake_get(url, params=None, headers=None, timeout=None):
            captured["url"] = url
            captured["params"] = params
            captured["headers"] = headers
            captured["timeout"] = timeout
            class R:
                status_code = 200
                def json(self_inner):
                    return fixture
            return R()

        import stock_data.data_provider.fetchers.ths_fetcher as mod
        monkeypatch.setattr(mod.requests, "get", fake_get)

        self.fetcher.fetch_flash_news(limit=10)

        assert captured["url"] == "https://news.10jqka.com.cn/tapp/news/push/stock"
        assert captured["params"] == {"page": "1", "tag": "", "track": "website"}
        assert "Chrome" in captured["headers"]["User-Agent"]
        assert "10jqka.com.cn" in captured["headers"]["Referer"]
        assert captured["timeout"] == 10

    def test_returns_normalized_dicts_from_fixture(self, monkeypatch):
        import json
        fixture = json.load(open("tests/fixtures/ths_flash_news.json", encoding="utf-8"))

        def fake_get(url, params=None, headers=None, timeout=None):
            class R:
                status_code = 200
                def json(self_inner):
                    return fixture
            return R()

        import stock_data.data_provider.fetchers.ths_fetcher as mod
        monkeypatch.setattr(mod.requests, "get", fake_get)

        results = self.fetcher.fetch_flash_news(limit=20)

        assert len(results) == 20  # fixture has 20 items
        first = results[0]
        upstream_first = fixture["data"]["list"][0]
        assert first["title"] == upstream_first["title"]
        assert first["url"] == upstream_first["url"]
        assert first["source_domain"] == "news.10jqka.com.cn"
        assert first["snippet"] == upstream_first["digest"]
        # rtime=1782181568 → 2026-06-22 in UTC (any local tz still year 2026)
        assert first["publish_time"].startswith("2026-")
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `python -m pytest tests/test_ths_fetcher.py::TestFetchFlashNewsSinglePage -v`
Expected: FAIL with `AttributeError: 'ThsFetcher' object has no attribute 'fetch_flash_news'`.

- [ ] **Step 3: Implement `fetch_flash_news` (single-page path only)**

Add to `stock_data/data_provider/fetchers/ths_fetcher.py` (after `_normalize_flash_item`):

```python
    def fetch_flash_news(self, limit: int = 50) -> list[dict]:
        """Get THS 7x24 global financial flash news.

        上游 URL: https://news.10jqka.com.cn/tapp/news/push/stock
        上游 pageSize 硬编码 20/页;本方法内部翻 ceil(limit/20) 页
        直到拿到 limit 条或上游返回空 list。

        Returns:
            归一化后的 list[dict],每条形如
            {title, url, source_domain, publish_time, snippet}。
            上游 list 缺失/null/空 → 返回 []。

        Raises:
            DataFetchError: 网络异常 / HTTP 非 200 / 上游 code != 200 / limit 越界
        """
        import math
        # limit 防御(路由层 Query(ge=1,le=200) 会拦,这里二次防御)
        try:
            limit = int(limit)
        except (TypeError, ValueError) as e:
            raise DataFetchError(
                f"[ThsFetcher] fetch_flash_news: limit must be int (got {limit!r})"
            ) from e
        if limit < self._FLASH_NEWS_MIN_LIMIT:
            raise DataFetchError(
                f"[ThsFetcher] fetch_flash_news: limit must be "
                f">= {self._FLASH_NEWS_MIN_LIMIT} (got {limit})"
            )
        # 上限不报错,直接 cap,与 EastMoneyFetcher 行为一致
        effective_limit = min(limit, self._FLASH_NEWS_MAX_LIMIT)
        max_pages = math.ceil(effective_limit / self._FLASH_NEWS_PAGE_SIZE)

        out: list[dict] = []
        for page in range(1, max_pages + 1):
            rows = self._fetch_flash_news_page(page)
            if not rows:
                break  # 翻到末页 / 越界,立即停
            out.extend(rows)
            if len(out) >= effective_limit:
                break

        return out[:effective_limit]

    def _fetch_flash_news_page(self, page: int) -> list[dict]:
        """Fetch one upstream page; return normalized list (empty on no-data)."""
        params = {"page": str(page), "tag": "", "track": "website"}
        headers = {
            "User-Agent": THS_UA,
            "Referer": "https://news.10jqka.com.cn/realtimenews.html",
        }
        try:
            r = requests.get(
                self._FLASH_NEWS_URL,
                params=params,
                headers=headers,
                timeout=self._FLASH_NEWS_TIMEOUT,
            )
        except Exception as e:
            raise DataFetchError(
                f"[ThsFetcher] fetch_flash_news network error: {e}"
            ) from e

        if r.status_code != 200:
            raise DataFetchError(
                f"[ThsFetcher] fetch_flash_news HTTP {r.status_code}"
            )

        try:
            payload = r.json()
        except (ValueError,) as e:
            raise DataFetchError(
                f"[ThsFetcher] fetch_flash_news: bad JSON: {e}"
            ) from e

        # 上游成功时 code 是字符串 "200"(实测,不是 int 200)。
        # 与 EastMoneyFetcher.fetch_flash_news 一致,接受 str 和 int 两种"成功"
        # 指示符。仅当 code 是已知失败值(-1、"0"、None)时才报错。
        # 参考 commit 3ae6dfa "fix(eastmoney): accept real upstream code values"。
        if payload.get("code") not in (200, "200"):
            raise DataFetchError(
                f"[ThsFetcher] fetch_flash_news API code={payload.get('code')} "
                f"msg={payload.get('msg')}"
            )

        raw_list = (payload.get("data") or {}).get("list")
        if not raw_list:
            return []

        out: list[dict] = []
        for rec in raw_list:
            # url 是必填字段(对应 EastMoney 校验 rec["code"] 的模式);
            # 缺失视为坏数据,跳过但不抛错。
            if not rec.get("url"):
                logger.warning(
                    f"[ThsFetcher] fetch_flash_news: skipping record without url: "
                    f"id={rec.get('id', '?')}"
                )
                continue
            try:
                out.append(self._normalize_flash_item(rec))
            except (KeyError, TypeError, ValueError) as e:
                # 单条记录缺关键字段就跳过,避免一条坏数据废整个 list
                logger.warning(
                    f"[ThsFetcher] fetch_flash_news: skipping malformed record: {e}"
                )
                continue
        return out
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `python -m pytest tests/test_ths_fetcher.py::TestFetchFlashNewsSinglePage -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
cd "D:/GitRepo/skills/stock_data"
git add stock_data/data_provider/fetchers/ths_fetcher.py tests/test_ths_fetcher.py
git commit -m "feat(ths): add fetch_flash_news with single-page path

Implements the NEWS_FLASH capability for ThsFetcher. Handles the
limit<=20 case (single upstream page). Pagination for limit>20 is
exercised in the next task via the same _fetch_flash_news_page helper.

- Method signature matches EastMoneyFetcher.fetch_flash_news so the
  manager's _with_failover(NEWS_FLASH, ...) lambda works generically.
- Hard cap 200, matches EastMoney. Route-layer Query(le=200) is the
  primary guard; fetcher-level clamp is a defensive belt-and-suspenders.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: Test multi-page behavior (limit > 20)

**Files:**
- Modify: `tests/test_ths_fetcher.py` (add `TestFetchFlashNewsMultiPage` class)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_ths_fetcher.py`:

```python
class TestFetchFlashNewsMultiPage:
    """Tests for fetch_flash_news(limit>20): paginates until enough items."""

    def setup_method(self):
        self.fetcher = ThsFetcher()

    def test_paginates_to_3_pages_for_limit_50(self, monkeypatch):
        """limit=50 → 3 pages requested (3*20=60 ≥ 50), returns 50 items."""
        import json
        fixture = json.load(open("tests/fixtures/ths_flash_news.json", encoding="utf-8"))
        page_calls = []

        def fake_get(url, params=None, headers=None, timeout=None):
            page_calls.append(params["page"])
            class R:
                status_code = 200
                def json(self_inner):
                    return fixture
            return R()

        import stock_data.data_provider.fetchers.ths_fetcher as mod
        monkeypatch.setattr(mod.requests, "get", fake_get)

        results = self.fetcher.fetch_flash_news(limit=50)

        assert page_calls == ["1", "2", "3"]  # 3 pages
        assert len(results) == 50  # 3 pages of 20, truncated to limit

    def test_paginates_to_10_pages_for_limit_200(self, monkeypatch):
        """limit=200 → 10 pages, returns 200 items (max)."""
        import json
        fixture = json.load(open("tests/fixtures/ths_flash_news.json", encoding="utf-8"))
        page_calls = []

        def fake_get(url, params=None, headers=None, timeout=None):
            page_calls.append(params["page"])
            class R:
                status_code = 200
                def json(self_inner):
                    return fixture
            return R()

        import stock_data.data_provider.fetchers.ths_fetcher as mod
        monkeypatch.setattr(mod.requests, "get", fake_get)

        results = self.fetcher.fetch_flash_news(limit=200)

        assert page_calls == [str(i) for i in range(1, 11)]  # 10 pages
        assert len(results) == 200

    def test_stops_on_empty_page(self, monkeypatch):
        """If upstream returns an empty list, stop paginating immediately."""
        import json
        fixture = json.load(open("tests/fixtures/ths_flash_news.json", encoding="utf-8"))
        empty = {"code": 200, "msg": "ok", "data": {"list": []}}
        page_calls = []

        def fake_get(url, params=None, headers=None, timeout=None):
            page_calls.append(params["page"])
            if params["page"] == "1":
                payload = fixture
            else:
                payload = empty
            class R:
                status_code = 200
                def json(self_inner, p=payload):
                    return p
            return R()

        import stock_data.data_provider.fetchers.ths_fetcher as mod
        monkeypatch.setattr(mod.requests, "get", fake_get)

        results = self.fetcher.fetch_flash_news(limit=200)

        # page 1 has data (20 items), page 2 is empty → stop
        assert page_calls == ["1", "2"]
        assert len(results) == 20
```

- [ ] **Step 2: Run the tests and verify they pass (they should — the implementation is already in Task 3)**

Run: `python -m pytest tests/test_ths_fetcher.py::TestFetchFlashNewsMultiPage -v`
Expected: 3 passed. (Implementation already supports pagination; these tests are the contract.)

If any fails, debug: the loop in `fetch_flash_news` is `for page in range(1, max_pages + 1)` and breaks on empty rows or `len(out) >= effective_limit`.

- [ ] **Step 3: Commit**

```bash
cd "D:/GitRepo/skills/stock_data"
git add tests/test_ths_fetcher.py
git commit -m "test(ths): cover fetch_flash_news pagination (limit>20)

Three cases:
- limit=50: 3 pages requested, 50 items returned
- limit=200: 10 pages, 200 items
- empty upstream page triggers early stop

The implementation was already multi-page-aware; these tests pin
the behavior so future refactors don't accidentally regress to
single-page (which would silently cap at 20).

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: Test limit edge cases (validation, cap, bad input)

**Files:**
- Modify: `tests/test_ths_fetcher.py` (add `TestFetchFlashNewsLimits` class)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_ths_fetcher.py`:

```python
class TestFetchFlashNewsLimits:
    """Limit validation and clamping."""

    def setup_method(self):
        self.fetcher = ThsFetcher()

    def test_limit_zero_raises(self):
        with pytest.raises(DataFetchError, match="limit must be"):
            self.fetcher.fetch_flash_news(limit=0)

    def test_limit_negative_raises(self):
        with pytest.raises(DataFetchError, match="limit must be"):
            self.fetcher.fetch_flash_news(limit=-5)

    def test_limit_string_coerced(self, monkeypatch):
        """Route layer sends str; fetcher should coerce to int."""
        import json
        fixture = json.load(open("tests/fixtures/ths_flash_news.json", encoding="utf-8"))

        def fake_get(url, params=None, headers=None, timeout=None):
            class R:
                status_code = 200
                def json(self_inner):
                    return fixture
            return R()

        import stock_data.data_provider.fetchers.ths_fetcher as mod
        monkeypatch.setattr(mod.requests, "get", fake_get)

        results = self.fetcher.fetch_flash_news(limit="10")
        assert len(results) == 10

    def test_limit_non_numeric_raises(self):
        with pytest.raises(DataFetchError, match="limit must be int"):
            self.fetcher.fetch_flash_news(limit="abc")

    def test_limit_above_200_capped_not_raised(self, monkeypatch):
        """limit=500 doesn't raise; capped to 200 (10 pages)."""
        import json
        fixture = json.load(open("tests/fixtures/ths_flash_news.json", encoding="utf-8"))
        page_calls = []

        def fake_get(url, params=None, headers=None, timeout=None):
            page_calls.append(params["page"])
            class R:
                status_code = 200
                def json(self_inner):
                    return fixture
            return R()

        import stock_data.data_provider.fetchers.ths_fetcher as mod
        monkeypatch.setattr(mod.requests, "get", fake_get)

        results = self.fetcher.fetch_flash_news(limit=500)
        assert page_calls == [str(i) for i in range(1, 11)]  # 10 pages
        assert len(results) == 200  # capped
```

- [ ] **Step 2: Run the tests and verify they pass (all should — Task 3's implementation handles these)**

Run: `python -m pytest tests/test_ths_fetcher.py::TestFetchFlashNewsLimits -v`
Expected: 5 passed. If `test_limit_string_coerced` fails, the `int(limit)` call in `fetch_flash_news` is the fix.

- [ ] **Step 3: Commit**

```bash
cd "D:/GitRepo/skills/stock_data"
git add tests/test_ths_fetcher.py
git commit -m "test(ths): cover fetch_flash_news limit edge cases

- limit=0/-5 → DataFetchError
- limit=string → coerced to int
- limit='abc' → DataFetchError
- limit=500 → capped to 200 (10 pages), no raise

Pins the defensive behavior from Task 3's implementation. The fetcher
clamps to 200 instead of raising because the route layer's
Query(le=200) is the primary guard; the fetcher only needs to avoid
silently sending an unbounded request to upstream.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: Test error paths (HTTP error, bad code, empty list, bad record)

**Files:**
- Modify: `tests/test_ths_fetcher.py` (add `TestFetchFlashNewsErrors` class)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_ths_fetcher.py`:

```python
class TestFetchFlashNewsErrors:
    """Error handling for fetch_flash_news."""

    def setup_method(self):
        self.fetcher = ThsFetcher()

    def test_http_error_raises(self, monkeypatch):
        class R:
            status_code = 500
            def json(self_inner):
                return {}
        import stock_data.data_provider.fetchers.ths_fetcher as mod
        monkeypatch.setattr(mod.requests, "get", lambda *a, **kw: R())
        with pytest.raises(DataFetchError, match="HTTP 500"):
            self.fetcher.fetch_flash_news(limit=10)

    def test_network_error_raises(self, monkeypatch):
        import stock_data.data_provider.fetchers.ths_fetcher as mod
        def boom(*a, **kw):
            raise ConnectionError("refused")
        monkeypatch.setattr(mod.requests, "get", boom)
        with pytest.raises(DataFetchError, match="network error"):
            self.fetcher.fetch_flash_news(limit=10)

    def test_bad_json_raises(self, monkeypatch):
        class R:
            status_code = 200
            def json(self_inner):
                raise ValueError("bad json")
        import stock_data.data_provider.fetchers.ths_fetcher as mod
        monkeypatch.setattr(mod.requests, "get", lambda *a, **kw: R())
        with pytest.raises(DataFetchError, match="bad JSON"):
            self.fetcher.fetch_flash_news(limit=10)

    def test_upstream_error_code_raises(self, monkeypatch):
        bad = {"code": -1, "msg": "rate limited", "data": None}
        class R:
            status_code = 200
            def json(self_inner):
                return bad
        import stock_data.data_provider.fetchers.ths_fetcher as mod
        monkeypatch.setattr(mod.requests, "get", lambda *a, **kw: R())
        with pytest.raises(DataFetchError, match="code=-1"):
            self.fetcher.fetch_flash_news(limit=10)

    def test_empty_list_returns_empty(self, monkeypatch):
        empty = {"code": 200, "msg": "ok", "data": {"list": []}}
        class R:
            status_code = 200
            def json(self_inner):
                return empty
        import stock_data.data_provider.fetchers.ths_fetcher as mod
        monkeypatch.setattr(mod.requests, "get", lambda *a, **kw: R())
        results = self.fetcher.fetch_flash_news(limit=10)
        assert results == []

    def test_null_list_returns_empty(self, monkeypatch):
        """data.list is null (not []) → return [] (not raise)."""
        null_list = {"code": 200, "msg": "ok", "data": {"list": None}}
        class R:
            status_code = 200
            def json(self_inner):
                return null_list
        import stock_data.data_provider.fetchers.ths_fetcher as mod
        monkeypatch.setattr(mod.requests, "get", lambda *a, **kw: R())
        results = self.fetcher.fetch_flash_news(limit=10)
        assert results == []

    def test_missing_data_returns_empty(self, monkeypatch):
        """data key entirely missing → return []."""
        no_data = {"code": 200, "msg": "ok"}
        class R:
            status_code = 200
            def json(self_inner):
                return no_data
        import stock_data.data_provider.fetchers.ths_fetcher as mod
        monkeypatch.setattr(mod.requests, "get", lambda *a, **kw: R())
        results = self.fetcher.fetch_flash_news(limit=10)
        assert results == []

    def test_malformed_record_skipped(self, monkeypatch):
        """One record with missing url → skipped, others kept."""
        fixture = {
            "code": 200,
            "msg": "ok",
            "data": {
                "list": [
                    {"id": "1", "title": "good", "url": "https://x", "digest": "d", "rtime": "1782181568"},
                    {"id": "2", "title": "bad"},  # missing url → skipped
                    {"id": "3", "title": "also good", "url": "https://y", "digest": "d2", "rtime": "1782181567"},
                ]
            },
        }
        class R:
            status_code = 200
            def json(self_inner):
                return fixture
        import stock_data.data_provider.fetchers.ths_fetcher as mod
        monkeypatch.setattr(mod.requests, "get", lambda *a, **kw: R())
        results = self.fetcher.fetch_flash_news(limit=10)
        assert len(results) == 2
        assert results[0]["title"] == "good"
        assert results[1]["title"] == "also good"
```

- [ ] **Step 2: Run the tests and verify they pass (all 8 should — Task 3's implementation handles these)**

Run: `python -m pytest tests/test_ths_fetcher.py::TestFetchFlashNewsErrors -v`
Expected: 8 passed. The "malformed record" test relies on Task 3's `if not rec.get("url"): continue` guard, which skips records without a url before calling `_normalize_flash_item`.

- [ ] **Step 3: Commit**

```bash
cd "D:/GitRepo/skills/stock_data"
git add tests/test_ths_fetcher.py
git commit -m "test(ths): cover fetch_flash_news error paths

- HTTP 500, network error, bad JSON, upstream code != 200 → DataFetchError
- empty/null/missing list → returns [] (not an error)
- malformed record → skipped, others kept

These pin the error-handling contract from Task 3's implementation
so the manager's _with_failover has well-defined failure modes.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7: Register `NEWS_FLASH` in `ThsFetcher.supported_data_types`

**Files:**
- Modify: `stock_data/data_provider/fetchers/ths_fetcher.py:39-42` (add `NEWS_FLASH` to supported_data_types)
- Modify: `stock_data/data_provider/fetchers/ths_fetcher.py:1-9` (update docstring)

- [ ] **Step 1: Add NEWS_FLASH to the capability tuple**

Edit `stock_data/data_provider/fetchers/ths_fetcher.py`. Change:

```python
    supported_data_types = (
        DataCapability.HOT_TOPICS
        | DataCapability.NORTH_FLOW
    )
```

to:

```python
    supported_data_types = (
        DataCapability.HOT_TOPICS
        | DataCapability.NORTH_FLOW
        | DataCapability.NEWS_FLASH
    )
```

- [ ] **Step 2: Update module docstring**

Edit the top docstring of `stock_data/data_provider/fetchers/ths_fetcher.py`. Change:

```python
"""
同花顺 HTTP API fetcher for signal layer data.

Provides: 热点题材(hot-topics), 北向资金(north-flow)

APIs:
- 热点: zx.10jqka.com.cn/event/api/getharden/
- 北向: data.hexin.cn/market/hsgtApi/method/dayChart/
"""
```

to:

```python
"""
同花顺 HTTP API fetcher for signal layer data.

Provides: 热点题材(hot-topics), 北向资金(north-flow), 全球财经快讯(news-flash)

APIs:
- 热点: zx.10jqka.com.cn/event/api/getharden/
- 北向: data.hexin.cn/market/hsgtApi/method/dayChart/
- 快讯: news.10jqka.com.cn/tapp/news/push/stock  (pageSize 硬编码 20/页, 内部翻页)
"""
```

- [ ] **Step 3: Run the capability method map test to verify**

Run: `python -m pytest tests/test_capability_method_map.py -v`
Expected: PASS. The test asserts every `DataCapability` flag is either in `CAPABILITY_TO_METHOD` or `_NO_FETCHER_METHOD`. `NEWS_FLASH → "fetch_flash_news"` is already in the map; adding it to ThsFetcher.supported_data_types doesn't change the map, but `tests/test_fetcher_structure.py` (if it walks every fetcher and checks `fetch_<method>` exists) will validate that ThsFetcher actually implements `fetch_flash_news`.

Run: `python -m pytest tests/test_fetcher_structure.py -v`
Expected: PASS. If this fails with "ThsFetcher has no method fetch_flash_news", re-check Task 3's implementation.

- [ ] **Step 4: Commit**

```bash
cd "D:/GitRepo/skills/stock_data"
git add stock_data/data_provider/fetchers/ths_fetcher.py
git commit -m "feat(ths): declare NEWS_FLASH capability

ThsFetcher now serves as a NEWS_FLASH fallback for EastMoneyFetcher.
The existing _with_failover(NEWS_FLASH, ...) in manager.py will pick
this up automatically — EastMoney (priority 6) tried first, ThsFetcher
(priority 7) on failure. No manager / route / schema changes needed.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 8: Manager failover tests (EastMoney → ThsFetcher)

**Files:**
- Modify: `tests/test_manager_flash_news.py` (add `TestFlashNewsFailover` class)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_manager_flash_news.py`:

```python
# -----------------------------------------------------------------------------
# EastMoney (P6) → ThsFetcher (P7) failover
# -----------------------------------------------------------------------------


class TestFlashNewsFailover:
    """When EastMoneyFetcher raises, the manager should fall back to ThsFetcher."""

    def _mgr(self):
        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

        mgr = DataFetcherManager()
        mgr.reset()
        mgr.add_fetcher(EastMoneyFetcher())  # priority 6
        mgr.add_fetcher(ThsFetcher())        # priority 7
        return mgr

    def test_eastmoney_succeeds_no_failover(self):
        """Happy path: EastMoney returns, ThsFetcher never called."""
        mgr = self._mgr()
        with patch.object(
            EastMoneyFetcher, "fetch_flash_news",
            return_value=[{"title": "from em"}],
        ) as em, patch.object(
            ThsFetcher, "fetch_flash_news",
        ) as ths:
            data, source = mgr.get_flash_news(limit=20)

        assert data == [{"title": "from em"}]
        assert source == "EastMoneyFetcher"
        em.assert_called_once_with(20)
        ths.assert_not_called()

    def test_eastmoney_raises_falls_back_to_ths(self):
        """EastMoney raises → ThsFetcher is called next."""
        mgr = self._mgr()
        with patch.object(
            EastMoneyFetcher, "fetch_flash_news",
            side_effect=Exception("em broken"),
        ), patch.object(
            ThsFetcher, "fetch_flash_news",
            return_value=[{"title": "from ths"}],
        ) as ths:
            data, source = mgr.get_flash_news(limit=20)

        assert data == [{"title": "from ths"}]
        assert source == "ThsFetcher"
        ths.assert_called_once_with(20)

    def test_eastmoney_returns_empty_falls_back_to_ths(self):
        """EastMoney returns [] (e.g. upstream 0 items) → ThsFetcher tried next.

        _is_meaningful treats [] as 'no data', so failover continues.
        """
        mgr = self._mgr()
        with patch.object(
            EastMoneyFetcher, "fetch_flash_news", return_value=[],
        ), patch.object(
            ThsFetcher, "fetch_flash_news",
            return_value=[{"title": "from ths"}],
        ) as ths:
            data, source = mgr.get_flash_news(limit=20)

        assert source == "ThsFetcher"
        ths.assert_called_once_with(20)

    def test_both_fail_raises(self):
        """Both fetchers raise → DataFetchError, source empty."""
        mgr = self._mgr()
        with patch.object(EastMoneyFetcher, "fetch_flash_news", side_effect=Exception("em")), \
             patch.object(ThsFetcher, "fetch_flash_news", side_effect=Exception("ths")):
            with pytest.raises(DataFetchError, match="All fetchers failed"):
                mgr.get_flash_news(limit=20)
```

- [ ] **Step 2: Run the tests and verify they pass**

Run: `python -m pytest tests/test_manager_flash_news.py::TestFlashNewsFailover -v`
Expected: 4 passed. The manager's `_with_failover` is the contract; these tests pin the priority order (P6 before P7) and the empty-result failover semantics.

If `test_eastmoney_returns_empty_falls_back_to_ths` fails, double-check that `_is_meaningful` in `manager.py` returns False for `[]` (it does — confirmed at line 28 of `manager.py`).

- [ ] **Step 3: Commit**

```bash
cd "D:/GitRepo/skills/stock_data"
git add tests/test_manager_flash_news.py
git commit -m "test(manager): cover NEWS_FLASH failover EastMoney → ThsFetcher

4 scenarios:
- EastMoney success: ThsFetcher never called
- EastMoney raises: ThsFetcher takes over
- EastMoney returns []: treated as no-data, ThsFetcher takes over
- Both fail: DataFetchError

Pins the priority-based failover contract. Without ThsFetcher
NEWS_FLASH support, the second/third cases would raise immediately;
with it, the chain absorbs single-source outages.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 9: Update CLAUDE.md (doc sync)

**Files:**
- Modify: `CLAUDE.md` (3 places: provider table, fetcher capability table, capability-routing table)

- [ ] **Step 1: Update the provider overview table (add NEWS_FLASH to ThsFetcher row)**

Edit `CLAUDE.md`. In the provider-overview table (search for `| \`ThsFetcher\` |`), the ThsFetcher row currently reads:

```
| `ThsFetcher` | 7 | csi | `HOT_TOPICS`, `NORTH_FLOW` | none |
```

Change to:

```
| `ThsFetcher` | 7 | csi | `HOT_TOPICS`, `NORTH_FLOW`, `NEWS_FLASH` | none |
```

- [ ] **Step 2: Update the fetcher capability declarations table**

Edit `CLAUDE.md`. Find the row for `ThsFetcher` in the "Fetcher capability declarations" table. It currently reads:

```
| ThsFetcher | `HOT_TOPICS \| NORTH_FLOW` |
```

Change to:

```
| ThsFetcher | `HOT_TOPICS \| NORTH_FLOW \| NEWS_FLASH` |
```

- [ ] **Step 3: Update the capability-routing table to note the failover order**

Edit `CLAUDE.md`. Find the row in the capability-routing table for `get_flash_news`. It currently reads:

```
| `get_flash_news` | `NEWS_FLASH` |
```

Change to:

```
| `get_flash_news` | `NEWS_FLASH` (EastMoney P6 → ThsFetcher P7) |
```

- [ ] **Step 4: Commit**

```bash
cd "D:/GitRepo/skills/stock_data"
git add CLAUDE.md
git commit -m "docs(CLAUDE): add ThsFetcher NEWS_FLASH to capability tables

Three updates:
1. Provider overview: ThsFetcher now lists NEWS_FLASH
2. Fetcher capability declarations: ThsFetcher | ... | NEWS_FLASH
3. Capability routing: get_flash_news notes EastMoney (P6) → ThsFetcher (P7)
   failover order

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 10: Final verification — run the relevant test subset

**Files:** none (verification only)

- [ ] **Step 1: Run all task-related tests**

```bash
cd "D:/GitRepo/skills/stock_data"
python -m pytest \
  tests/test_ths_fetcher.py \
  tests/test_manager_flash_news.py \
  tests/test_eastmoney_flash_news.py \
  tests/test_capability_method_map.py \
  tests/test_fetcher_structure.py \
  tests/test_explorer_manifest_endpoint.py \
  -v
```

Expected: all pass. If any fail, debug and fix (the tasks are designed so failures indicate a regression, not a missing step).

- [ ] **Step 2: Run the explorer manifest check to confirm ThsFetcher shows up under /news/flash**

```bash
cd "D:/GitRepo/skills/stock_data"
python -c "
from stock_data.server import app
import json
from stock_data.explorer.manifest import build_manifest
manifest = build_manifest(app)
for section in manifest['sections']:
    for endpoint in section.get('endpoints', []):
        if endpoint.get('path', '').endswith('/news/flash'):
            fetchers = endpoint.get('fetchers', [])
            print('fetchers for /news/flash:')
            for f in fetchers:
                print(f'  - {f[\"name\"]} (priority={f[\"priority\"]}, method={f[\"method\"]})')
            assert any(f['name'] == 'ThsFetcher' for f in fetchers), 'ThsFetcher missing!'
            print('OK: ThsFetcher is listed as a NEWS_FLASH backend')
"
```

Expected output: prints `ThsFetcher (priority=7, ...)` and ends with `OK: ThsFetcher is listed as a NEWS_FLASH backend`.

- [ ] **Step 3: Live smoke test (optional, requires network)**

```bash
cd "D:/GitRepo/skills/stock_data"
python -c "
from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher
import logging
logging.basicConfig(level=logging.WARNING)
f = ThsFetcher()
result = f.fetch_flash_news(limit=5)
print(f'Got {len(result)} items')
for r in result[:3]:
    print(f'  - {r[\"title\"][:50]} ({r[\"publish_time\"]})')
    print(f'    url={r[\"url\"]}')
"
```

Expected: 5 items printed, real titles, real timestamps formatted as `YYYY-MM-DD HH:MM:SS`. If it fails with `DataFetchError`, the upstream may be down — that's a network issue, not a code issue.

- [ ] **Step 4: Final summary commit (no code changes)**

```bash
cd "D:/GitRepo/skills/stock_data"
git log --oneline -10
```

Expected: 9 commits (Tasks 1-9) all on `master` branch, all pushed-able (push optional per user preference).
