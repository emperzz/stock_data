# EastMoney / THS News Content Enhancement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `/api/v1/news/content` extract more EastMoney/THS article bodies while returning HTTP 200 with structured status for ordinary fetch/parse failures and preserving HTTP 400 for SSRF/invalid URL errors.

**Architecture:** Keep `NewsContentExtractor` as the standalone content utility. Add a structured result state to its dataclass, separate URL-security exceptions from ordinary fetch/parse outcomes, normalize fetched-page metadata once, and dispatch verified domain handlers before a deterministic generic extractor. The route will pass the new fields through unchanged; news fetchers and manager routing remain untouched.

**Tech Stack:** Python 3.10+, FastAPI, Pydantic v2, `requests`, BeautifulSoup4, pytest, existing `cache_endpoint`/TTL cache, existing `live_network` marker.

---

## File map and boundaries

| File | Responsibility in this plan |
|---|---|
| `stock_data/data_provider/utils/news_extractor.py` | URL validation, one HTTP fetch, redirect safety, response decoding, metadata extraction, domain dispatch, body extraction, structured failure result |
| `stock_data/api/schemas.py:1050-1060` | Public `NewsContentResponse` fields and defaults |
| `stock_data/api/routes/news.py:119-158` | HTTP response declaration and explicit field passthrough; no fetch logic |
| `tests/test_news_content_extractor.py` | Pure HTML/handler/metadata/status tests; all network calls mocked or skipped with `html=` |
| `tests/test_news_endpoints.py` | FastAPI response semantics, cache behavior, SSRF compatibility |
| `tests/test_news_content_ssrf.py` | Existing security contract; add only regression coverage if needed |
| `tests/test_news_content_live.py` | New opt-in, one-URL-per-host real probe; marked `live_network` |
| `tests/test_eastmoney_stock_news.py` | Existing EastMoney URL/source-domain contract remains the source of caifuhao probe URL |
| `tests/test_ths_fetcher_get_stock_news.py` | Existing THS URL/source-domain contract remains the source of THS probe URL |
| `tests/fixtures/news_content/` | Small, sanitized HTML fixtures for verified layouts and failure pages |
| `docs/superpowers/specs/2026-07-15-news-content-design.md` | Approved design; implementation must remain within its narrowed scope |

Do not modify `DataCapability`, `DataFetcherManager`, EastMoney news API calls, THS news API calls, or `.env.example` for this feature.

---

### Task 1: Add failing tests for the structured content contract

**Files:**
- Create: `tests/fixtures/news_content/eastmoney_standard.html`
- Create: `tests/fixtures/news_content/ths_article.html`
- Create: `tests/fixtures/news_content/generic_metadata.html`
- Create: `tests/fixtures/news_content/js_shell.html`
- Create: `tests/fixtures/news_content/blocked.html`
- Modify: `tests/test_news_content_extractor.py`
- Modify: `tests/test_news_endpoints.py`

- [ ] **Step 1: Add minimal sanitized fixtures**

Create fixtures containing only the structures under test:

```html
<!-- eastmoney_standard.html -->
<html>
  <head><link rel="canonical" href="https://finance.eastmoney.com/a/test.html"></head>
  <body>
    <div class="topbox">测试标题
      <span>2026年07月15日 10:30 来源：测试媒体</span>
    </div>
    <div class="contentbox">
      <p>在东方财富看资讯行情, 选东方财富证券一站式开户交易&gt;&gt;</p>
      <p>这是经过清洗后应返回的第一段正文，包含足够的业务信息。</p>
      <p>这是第二段正文，用于验证 EastMoney 原有正文边界和长度规则。</p>
      <p>文章来源: test</p>
      <p>责任编辑: test</p>
    </div>
  </body>
</html>
```

```html
<!-- ths_article.html -->
<html>
  <head>
    <meta property="og:title" content="THS 测试标题">
    <meta property="article:published_time" content="2026-07-15T09:00:00+08:00">
  </head>
  <body>
    <nav>导航</nav>
    <div class="article-detail">
      <p>这是同花顺详情页中的正文第一段，不能被导航或推荐内容覆盖。</p>
      <p>这是正文第二段，用于验证来源专用 handler。</p>
    </div>
    <aside>相关推荐</aside>
  </body>
</html>
```

```html
<!-- generic_metadata.html -->
<html>
  <head>
    <title>Fallback title</title>
    <meta property="og:title" content="OG title">
    <meta property="article:published_time" content="2026-07-15T08:00:00Z">
    <script type="application/ld+json">
      {"headline":"JSON-LD title","datePublished":"2026-07-15","author":{"name":"JSON Author"}}
    </script>
  </head>
  <body><article><p>通用正文第一段，包含足够的文字用于验证正文长度和元数据提取。</p><p>通用正文第二段，确保候选正文不会被误判为空。</p></article></body>
</html>
```

```html
<!-- js_shell.html -->
<html><head><script>window.__NEXT_DATA__ = {};</script></head>
<body><div id="app"></div><script src="/bundle.js"></script></body></html>
```

```html
<!-- blocked.html -->
<html><body><div>访问频繁，请完成验证码后继续</div></body></html>
```

- [ ] **Step 2: Add extractor tests that describe the new statuses**

Extend `tests/test_news_content_extractor.py` with tests like:

```python
from pathlib import Path

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "news_content"


def _fixture(name: str) -> str:
    return (_FIXTURES / name).read_text(encoding="utf-8")


def test_success_has_structured_status_and_defaults():
    result = NewsContentExtractor.extract(
        "https://example.com/article", html=_fixture("generic_metadata.html")
    )
    assert result.content_status == "ok"
    assert result.reason is None
    assert result.http_status is None
    assert result.body
    assert result.byte_size == len(result.body.encode("utf-8"))


def test_js_shell_returns_200_contract_result():
    result = NewsContentExtractor.extract(
        "https://example.com/app", html=_fixture("js_shell.html")
    )
    assert result.content_status == "javascript_required"
    assert result.body == ""
    assert result.byte_size == 0


def test_block_page_returns_blocked_status():
    result = NewsContentExtractor.extract(
        "https://example.com/blocked", html=_fixture("blocked.html")
    )
    assert result.content_status == "blocked"
    assert result.body == ""
```

Change the existing `test_short_body_raises` assertion so a valid public URL with an empty/short page returns `content_status in {"empty", "unsupported"}` instead of raising. Keep all SSRF exceptions in `tests/test_news_content_ssrf.py` unchanged.

- [ ] **Step 3: Add endpoint tests before implementation**

In `tests/test_news_endpoints.py`, add new fields to the fake `NewsContent` object and assert they are returned:

```python
fake = NewsContent(
    url="https://finance.eastmoney.com/a/1.html",
    title="Test Title",
    body="Body content here for testing.",
    publish_date="2026-06-09",
    author="TestMedia",
    source_domain="finance.eastmoney.com",
    extractor="eastmoney_v1",
    byte_size=28,
    content_status="ok",
    canonical_url="https://finance.eastmoney.com/a/1.html",
    http_status=200,
)

assert resp.json()["content_status"] == "ok"
assert resp.json()["canonical_url"] == fake.canonical_url
assert resp.json()["http_status"] == 200
```

Add a structured-failure route test using a returned `NewsContent`, not a raised `ValueError`:

```python
def test_content_403_returns_200_with_blocked_status(self, client):
    from stock_data.data_provider.utils.news_extractor import NewsContent

    fake = NewsContent._build(
        url="https://example.com/blocked",
        extractor="generic",
        content_status="blocked",
        reason="upstream HTTP 403",
        http_status=403,
    )
    with patch(
        "stock_data.data_provider.utils.news_extractor.NewsContentExtractor.extract",
        return_value=fake,
    ):
        resp = client.get("/api/v1/news/content", params={"url": fake.url})

    assert resp.status_code == 200
    assert resp.json()["content_status"] == "blocked"
    assert resp.json()["body"] == ""
```

Replace `test_content_extraction_failure_returns_400` with a test that keeps HTTP 400 only for a raised SSRF `ValueError`; the ordinary parse/fetch failure contract must be represented by the test above.

- [ ] **Step 4: Run the new tests to confirm they fail for the intended reasons**

Run:

```bash
.venv/Scripts/python.exe -m pytest tests/test_news_content_extractor.py tests/test_news_endpoints.py -q
```

Expected: FAIL because `NewsContent` has no new fields, handlers still raise on short bodies, and the route does not serialize the new fields. Existing SSRF tests should remain passing.

---

### Task 2: Implement the result model and fetch/exception boundary

**Files:**
- Modify: `stock_data/data_provider/utils/news_extractor.py:31-62, 112-184`
- Test: `tests/test_news_content_extractor.py`
- Test: `tests/test_news_content_ssrf.py`

- [ ] **Step 1: Extend `NewsContent` and both builders with keyword-only status metadata**

Add a `ContentStatus` type alias and fields with compatibility defaults:

```python
from dataclasses import dataclass, replace
from typing import Literal

ContentStatus = Literal[
    "ok",
    "empty",
    "unsupported",
    "javascript_required",
    "blocked",
    "fetch_error",
]

@dataclass
class NewsContent:
    url: str
    title: str | None
    body: str
    publish_date: str | None
    author: str | None
    source_domain: str
    extractor: str
    byte_size: int
    content_status: ContentStatus = "ok"
    reason: str | None = None
    canonical_url: str | None = None
    http_status: int | None = None
```

Update `NewsContent._build()` and `NewsContentExtractor._build()` to accept these as keyword arguments and preserve `byte_size = len(body.encode("utf-8"))`. Ensure existing callers that only pass the old fields still produce `content_status="ok"`.

- [ ] **Step 2: Add a result finalizer for fetched-page metadata**

Use `dataclasses.replace` or an equivalent named-field construction so a handler result can be finalized without changing every handler signature:

```python
def _finalize_result(
    result: NewsContent,
    *,
    response_url: str | None = None,
    canonical_url: str | None = None,
    http_status: int | None = None,
) -> NewsContent:
    final_url = response_url or result.url
    return replace(
        result,
        source_domain=source_domain_from_url(final_url),
        canonical_url=canonical_url,
        http_status=http_status,
        byte_size=len(result.body.encode("utf-8")),
    )
```

Keep `result.url` equal to the caller’s original URL for backward compatibility. Use the final response URL only for `source_domain` and canonical fallback.

- [ ] **Step 3: Refactor `extract()` to keep SSRF errors exceptional and ordinary failures structured**

Preserve `_validate_url()` and post-redirect private-IP checks as `ValueError` paths. For a network request:

```python
try:
    resp = requests.get(
        url,
        headers={"User-Agent": _EM_USER_AGENT},
        timeout=15,
        allow_redirects=True,
    )
except (requests.RequestException, UnicodeError, OSError) as exc:
    return NewsContent._build(
        url=url,
        extractor="none",
        content_status="fetch_error",
        reason=f"fetch failed: {exc}",
    )
```

Do not catch broad `Exception`, because parser programming errors must remain observable. After redirect validation, expose a final HTTP response result:

- 403 or 429: return `content_status="blocked"` with `http_status` and no body;
- other 4xx/5xx: return `content_status="fetch_error"` with `http_status` and no body;
- 2xx/3xx-final HTML: decode and dispatch to a handler;
- `html=` test calls have `http_status=None` and do not make a network request.

- [ ] **Step 4: Add regression tests for the exception boundary**

Mock `requests.get` and assert:

```python
def test_network_error_returns_structured_fetch_error(monkeypatch):
    def fail(*args, **kwargs):
        raise requests.Timeout("timed out")

    monkeypatch.setattr(news_extractor.requests, "get", fail)
    result = NewsContentExtractor.extract("https://example.com/news")
    assert result.content_status == "fetch_error"
    assert result.http_status is None


def test_redirect_to_private_still_raises(monkeypatch):
    response = SimpleNamespace(url="http://127.0.0.1/secret", status_code=200, text="")
    monkeypatch.setattr(news_extractor.requests, "get", lambda *a, **k: response)
    with pytest.raises(ValueError, match="internal network"):
        NewsContentExtractor.extract("https://example.com/news")
```

Use the existing `bypass_ssrf` fixture only for HTML parsing tests; do not place SSRF assertions in that file.

- [ ] **Step 5: Run the focused model/boundary tests**

Run:

```bash
.venv/Scripts/python.exe -m pytest \
  tests/test_news_content_extractor.py \
  tests/test_news_content_ssrf.py \
  tests/test_news_endpoints.py -q
```

Expected: the new status tests pass once Task 2 is complete; domain-specific extraction tests may still fail until Task 3 and Task 4 are implemented.

---

### Task 3: Implement metadata, encoding, blocked-page detection, and deterministic generic extraction

**Files:**
- Modify: `stock_data/data_provider/utils/news_extractor.py:186-232`
- Create/modify: `tests/fixtures/news_content/generic_metadata.html`
- Modify: `tests/test_news_content_extractor.py`

- [ ] **Step 1: Add metadata helpers with fixed precedence**

Implement small pure helpers with this precedence:

- title: `og:title` → JSON-LD `headline` → `<title>`;
- date: `article:published_time` → JSON-LD `datePublished` → no value;
- author: JSON-LD author name → known page metadata → no value;
- canonical: `<link rel="canonical">` if valid `http(s)`, otherwise final response URL.

Normalize dates to the first 10 characters only when they match the existing `YYYY-MM-DD` contract. Invalid metadata must be ignored rather than raised.

- [ ] **Step 2: Add response decoding before BeautifulSoup**

For fetched pages, choose encoding in this order:

1. explicit `Content-Type` charset;
2. UTF-8 BOM or a valid UTF-8 decode;
3. `resp.apparent_encoding` for pages such as THS that declare GBK/GB18030;
4. UTF-8 with replacement as the final fallback.

Keep `html=` fixture input unchanged. Add a mocked response test whose `content` is GBK/GB18030 encoded and assert Chinese body text is readable.

- [ ] **Step 3: Add conservative blocked and JS-shell classifiers**

Implement classifiers that run before normal extraction:

```python
_BLOCK_MARKERS = (
    "请输入验证码", "访问频繁", "请求过于频繁", "人机验证",
    "安全验证", "登录后查看", "access denied", "captcha", "challenge",
)
```

Rules:

- final status 403/429 is blocked regardless of HTML;
- for a 2xx page, only classify marker text as blocked when the cleaned page is short and no credible article candidate exists;
- detect JS shell by `__NEXT_DATA__`, `id="app"`, script-heavy HTML, or client bundle markers, but first attempt `<noscript>` content;
- if no usable `<noscript>`/article text remains, return `javascript_required`.

Tests must cover a blocked fixture, a JS shell fixture, and a JS shell with readable `<noscript>` content.

- [ ] **Step 4: Replace generic exceptions with structured statuses**

Refactor `_default_handler()` so it returns `NewsContent` instead of raising for short/unsupported pages:

```python
if main is None or not body:
    return NewsContent._build(
        url=url,
        title=title,
        publish_date=publish_date,
        extractor="generic",
        content_status="unsupported",
        reason="no supported article container",
    )

if len(body) < 80 and (paragraph_count < 2 or len(body) < 40):
    return NewsContent._build(
        url=url,
        title=title,
        publish_date=publish_date,
        body="",
        extractor="generic",
        content_status="empty",
        reason="cleaned body is below the generic length threshold",
    )
```

Use deterministic candidate order and longest accepted candidate; do not implement a multi-dimensional scoring system. Remove `form` along with the existing noise tags, but preserve `noscript` until it has been checked.

- [ ] **Step 5: Add generic extraction tests**

Assert:

- `article` beats `main` and body noise;
- `div.content`, `div#content`, `.article-content`, `.article-body` remain supported;
- links-heavy navigation is not selected as article body;
- JSON-LD/OpenGraph metadata is returned with a normal body;
- `canonical_url` is present only in fetched/finalized results or in a fixture handler that explicitly supplies it;
- `byte_size` is the cleaned-body byte count;
- short pages return `empty`/`unsupported`, never a raised “could not extract” `ValueError`.

- [ ] **Step 6: Run generic tests and lint the extractor**

Run:

```bash
.venv/Scripts/python.exe -m pytest tests/test_news_content_extractor.py -q
.venv/Scripts/python.exe -m ruff check stock_data/data_provider/utils/news_extractor.py tests/test_news_content_extractor.py
```

Expected: all extractor unit tests pass; no ruff errors.

---

### Task 4: Add verified EastMoney and THS source handlers

**Files:**
- Modify: `stock_data/data_provider/utils/news_extractor.py:235-295`
- Create: `tests/fixtures/news_content/ths_article.html`
- Create if live HTML confirms a structure: `tests/fixtures/news_content/caifuhao_eastmoney.html`
- Modify: `tests/test_news_content_extractor.py`
- Reference only: `tests/test_eastmoney_stock_news.py`, `tests/test_ths_fetcher_get_stock_news.py`

- [ ] **Step 1: Preserve and convert the existing EastMoney handler**

Keep `div.topbox` title/date/source parsing and `div.contentbox` paragraph behavior. Change body-too-short behavior from `raise ValueError` to a structured `empty` result while retaining `extractor="eastmoney_v1"`. Keep these exact rules:

- skip `_EM_AD_KEYWORDS` paragraphs;
- stop at `_EM_BODY_STOP_KEYWORDS`;
- keep the existing 100-byte EastMoney threshold;
- return title/date/author even when the body is empty.

Add fallback candidates only after the existing `.topbox`/`.contentbox` path has been attempted: `article`, `.article-content`, `.article-body`, `#ContentBody`.

- [ ] **Step 2: Add the THS handler with verified selectors**

Implement `_ths_news_handler(url, html)` and register `news.10jqka.com.cn`. Try, in order:

```python
_THS_BODY_SELECTORS = (
    ".article-detail",
    ".article-content",
    ".news-content",
    ".txt",
    "article",
    "main",
)
```

For the first selector containing acceptable body text:

- remove scripts, styles, navigation, recommendation, login and comment blocks;
- preserve paragraphs, table text and image captions;
- extract title/date/author from the shared metadata helper;
- return `extractor="ths_news_v1"` and `content_status="ok"` when the source-specific 20-character threshold passes;
- return `empty` when a selector exists but cleans to too little text;
- return `unsupported` when no selector exists.

Add a fixture test asserting the body excludes nav and recommendations and the extractor name is `ths_news_v1`.

- [ ] **Step 3: Perform the fixture-first caifuhao decision without guessing selectors**

Use the already recorded EastMoney stock-news URL from `tests/test_eastmoney_stock_news.py`:

```text
http://caifuhao.eastmoney.com/news/20260702101113747001360
```

Perform at most one live fetch manually or via the opt-in probe in Task 7. If the enhanced generic handler extracts a stable body, keep the generic path and record that result in the live probe; do not add a duplicate domain handler only because the hostname is different. If the generic handler fails but the response exposes a stable, verified article structure, save only a sanitized fixture, document the selector in the test, implement `_eastmoney_caifuhao_handler`, and register it. If the response is blocked, unavailable, or only a shell/index page, do not add speculative selectors; leave the domain on the generic path and add a structured `blocked`, `fetch_error`, `javascript_required`, or `unsupported` regression fixture for the observed shape.

- [ ] **Step 4: Add EastMoney/THS dispatch and failure tests**

Assert:

```python
assert NewsContentExtractor.extract(
    "https://finance.eastmoney.com/a/1.html", html=em_html
).extractor == "eastmoney_v1"

assert NewsContentExtractor.extract(
    "https://news.10jqka.com.cn/20260715/c1.html", html=ths_html
).extractor == "ths_news_v1"
```

Also assert registry matching is case-insensitive for the hostname and that `www.`/port normalization does not select the wrong handler. Keep custom handler registration tests passing.

- [ ] **Step 5: Run all content extractor tests**

Run:

```bash
.venv/Scripts/python.exe -m pytest tests/test_news_content_extractor.py -q
```

Expected: EastMoney, THS, generic, metadata, blocked, JS-shell, custom registry, and short-body tests pass.

---

### Task 5: Expose the new fields and enforce the HTTP 200 route contract

**Files:**
- Modify: `stock_data/api/schemas.py:1050-1060`
- Modify: `stock_data/api/routes/news.py:119-158`
- Modify: `tests/test_news_endpoints.py`

- [ ] **Step 1: Add response fields with backward-compatible defaults**

Extend `NewsContentResponse` exactly as follows:

```python
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
    content_status: str = Field(default="ok")
    reason: str | None = Field(default=None)
    canonical_url: str | None = Field(default=None)
    http_status: int | None = Field(default=None)
```

Use the same status literal/enum convention as the extractor if the project schema style supports it; do not make new fields required for old cached/test objects.

- [ ] **Step 2: Remove the dead content 502 response declaration**

Change the `/news/content` route declaration to contain only the invalid URL/SSRF 400 response:

```python
responses={
    400: {"model": ErrorResponse, "description": "Invalid URL or SSRF rejection"},
}
```

Do not remove 502 declarations from `/news/search`, `/news/flash`, or `/stocks/{stock_code}/news`; those endpoints still use manager failover errors.

- [ ] **Step 3: Forward all fields explicitly**

Extend the existing constructor in `get_news_content()`:

```python
return NewsContentResponse(
    url=result.url,
    title=result.title,
    body=result.body,
    publish_date=result.publish_date,
    author=result.author,
    source_domain=result.source_domain,
    extractor=result.extractor,
    byte_size=result.byte_size,
    content_status=result.content_status,
    reason=result.reason,
    canonical_url=result.canonical_url,
    http_status=result.http_status,
)
```

Keep the existing `@map_errors` and content cache decorator. The route should not inspect or reinterpret `content_status`.

- [ ] **Step 4: Update endpoint tests for success, structured failure, cache, and SSRF**

Add assertions for all four new fields on successful and blocked responses. Verify a cached `NewsContent` object retains the new fields on the second request. Keep `test_content_ssrf_localhost_returns_400` and `test_content_non_http_scheme_returns_400` unchanged. Add an assertion that a raised `ValueError("redirected to internal network")` still maps to 400.

- [ ] **Step 5: Run endpoint tests and inspect OpenAPI**

Run:

```bash
.venv/Scripts/python.exe -m pytest tests/test_news_endpoints.py -q
```

Expected: all content endpoint tests pass, including HTTP 200 structured failures and HTTP 400 security failures.

Then use the existing FastAPI test client or a one-line Python check to assert `/openapi.json` no longer lists a 502 response for `/api/v1/news/content`.

---

### Task 6: Add URL/source-domain contract coverage without changing fetcher behavior

**Files:**
- Modify: `tests/test_eastmoney_stock_news.py` only if a missing assertion is discovered
- Modify: `tests/test_ths_fetcher_get_stock_news.py` only if a missing assertion is discovered
- Create or modify: `tests/test_news_content_url_contract.py`

- [ ] **Step 1: Add fixture-driven URL contract tests**

Use mocked EastMoney and THS payloads already present in the two fetcher tests. Assert every normalized news item has:

```python
from stock_data.data_provider.utils.url_helpers import source_domain

assert item["url"].startswith(("http://", "https://"))
assert item["source_domain"] == source_domain(item["url"])
assert item["title"]
assert item["publish_date"]
```

Explicitly cover the existing EastMoney `caifuhao.eastmoney.com` URL and THS `news.10jqka.com.cn` URL. Do not change URL rewriting or source-domain behavior unless a test exposes an actual mismatch.

- [ ] **Step 2: Add a content-input compatibility assertion**

For each normalized URL, patch `stock_data.data_provider.utils.news_extractor._is_private_ip` to return `False` (the test is about URL shape, not DNS), pass a mocked HTML page to `NewsContentExtractor.extract(url, html=...)`, and assert it returns a `NewsContent` object rather than rejecting the URL for formatting reasons. Do not assert `content_status="ok"` for a page whose actual source structure is not represented by the fixture; the content status is the intended diagnostic boundary.

- [ ] **Step 3: Run the URL contract tests and existing fetcher tests**

Run:

```bash
.venv/Scripts/python.exe -m pytest \
  tests/test_news_content_url_contract.py \
  tests/test_eastmoney_stock_news.py \
  tests/test_ths_fetcher_get_stock_news.py -q
```

Expected: existing normalized fields remain unchanged and no fetcher upstream behavior is modified.

---

### Task 7: Add and run low-frequency live probes

**Files:**
- Create: `tests/test_news_content_live.py`
- Do not modify upstream fetcher implementations for this task

- [ ] **Step 1: Create opt-in probes with one URL per host**

Mark the module or each test with `@pytest.mark.live_network`. Use only these sources, with no preliminary news-list request:

- one existing EastMoney `finance.eastmoney.com` URL from `tests/test_eastmoney_stock_news.py`:
  `http://finance.eastmoney.com/a/202607023791611310.html`;
- the existing EastMoney `caifuhao.eastmoney.com` URL from `tests/test_eastmoney_stock_news.py`;
- one THS URL loaded from the first item in `tests/fixtures/ths_basic_news.json`.

The probe must call `NewsContentExtractor.extract()` once per selected host, sequentially, and assert only that the result is a valid `NewsContent` with `content_status` in the defined status set. Print or log URL, final/canonical URL, extractor, status, HTTP status, and body length for manual analysis. Never loop through a list of live news items.

- [ ] **Step 2: Run probes only when explicitly requested**

Default command (must skip the probes):

```bash
.venv/Scripts/python.exe -m pytest tests/test_news_content_live.py -q
```

Expected: all tests skipped because `pyproject.toml` excludes `live_network` by default.

Opt-in command:

```bash
.venv/Scripts/python.exe -m pytest -m live_network tests/test_news_content_live.py -v
```

The existing `tests/conftest.py` network-to-xfail hook may downgrade upstream/network failures. Report the observed statuses rather than retrying a failed host. If the caifuhao probe is blocked or unavailable, do not invent a handler selector; retain the generic/structured-status behavior.

- [ ] **Step 3: Use probe results to finalize only verified selectors**

If a live response proves a stable caifuhao or THS layout not covered by fixtures, add the smallest sanitized fixture and selector test. If the response is blocked, retain the status classifier and record the limitation in the final implementation report. Do not add browser rendering, source API fallback, retry, or cooldown based on a single probe.

---

### Task 8: Run the complete relevant verification set

**Files:**
- No new source files; update tests only if a failure is directly caused by this feature

- [ ] **Step 1: Run all news/content-related tests**

Run:

```bash
.venv/Scripts/python.exe -m pytest \
  tests/test_news_content_extractor.py \
  tests/test_news_content_ssrf.py \
  tests/test_news_endpoints.py \
  tests/test_news_content_url_contract.py \
  tests/test_eastmoney_stock_news.py \
  tests/test_ths_fetcher_get_stock_news.py \
  tests/test_manager_news_search.py \
  tests/test_manager_stock_news.py \
  tests/test_manager_flash_news.py -q
```

Expected: all non-live tests pass. Any upstream test failures must be separated from local regressions; do not widen the implementation to solve unrelated provider failures.

- [ ] **Step 2: Run formatting/lint checks on changed files**

Run:

```bash
.venv/Scripts/python.exe -m ruff check \
  stock_data/data_provider/utils/news_extractor.py \
  stock_data/api/schemas.py \
  stock_data/api/routes/news.py \
  tests/test_news_content_extractor.py \
  tests/test_news_content_ssrf.py \
  tests/test_news_endpoints.py \
  tests/test_news_content_url_contract.py \
  tests/test_news_content_live.py
```

Expected: no ruff violations.

- [ ] **Step 3: Verify the API behavior end-to-end without live upstream**

Use the existing `TestClient` with `NewsContentExtractor.extract` patched to return:

1. `content_status="ok"`, non-empty body;
2. `content_status="blocked"`, `http_status=403`, empty body;
3. `content_status="javascript_required"`, empty body;
4. raised SSRF `ValueError`.

Confirm statuses are respectively HTTP 200, 200, 200, and 400, and that all response fields survive serialization.

- [ ] **Step 4: Run the default project suite relevant to this change**

Run:

```bash
.venv/Scripts/python.exe -m pytest -q
```

Expected: the default non-live suite passes. Do not run the full live suite as part of normal verification; the opt-in probe in Task 7 is the only required real-upstream test for this feature.

- [ ] **Step 5: Report limitations explicitly**

The final implementation report must state:

- which EastMoney and THS URL layouts returned `ok` in fixtures and live probe;
- which returned `blocked`, `fetch_error`, `empty`, `unsupported`, or `javascript_required`;
- whether caifuhao received a verified fixture/handler or remained on the generic path;
- that no browser rendering, source API fallback, automatic retry, or host cooldown was added;
- exact test commands and pass/skip/xfail results.

Do not commit or push changes unless the user explicitly requests it.
