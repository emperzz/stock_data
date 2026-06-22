# 全球财经快讯 (News Flash) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增 `GET /news/flash` 端点，复用 `EastMoneyFetcher` 拉取东财"全球财经快讯"（7×24 实时快讯流），覆盖测试 + 文档同步。

**Architecture:** 全栈新增 `NEWS_FLASH` capability flag（与现有 `NEWS_SEARCH` 镜像），分层为 fetcher 方法 → manager 包装 → schema → route，与现有 `/news/search` 走完全相同的 5 层架构。新增 `EastMoneyFetcher.fetch_flash_news()` 调用 `https://np-weblist.eastmoney.com/comm/web/getFastNewsList`，复用 `self._session`（chrome120 impersonation）。

**Tech Stack:** FastAPI、Pydantic v2、curl_cffi、TTLCache、pytest、ruff

---

## 文件改动一览

| # | 文件 | 类型 | 职责 |
|---|---|---|---|
| 1 | `stock_data/data_provider/base.py` | 修改 | 加 `DataCapability.NEWS_FLASH` + `CAPABILITY_TO_METHOD[NEWS_FLASH] = "fetch_flash_news"` |
| 2 | `stock_data/data_provider/fetchers/eastmoney_fetcher.py` | 修改 | 加 `supported_data_types.NEWS_FLASH`、加常量、加 `fetch_flash_news(limit)` 方法 |
| 3 | `stock_data/data_provider/manager.py` | 修改 | 加 `get_flash_news(limit)` 包装方法 |
| 4 | `stock_data/api/schemas.py` | 修改 | 加 `FlashNewsItem`、`FlashNewsResponse` |
| 5 | `stock_data/api/cache.py` | 修改 | 加 TTL/cache 实例/getter/key |
| 6 | `stock_data/api/routes.py` | 修改 | 加 `GET /news/flash?limit=...` 路由 |
| 7 | `stock_data/explorer/tags.py` | 修改 | 加 `CAPABILITY_LABELS["NEWS_FLASH"]` |
| 8 | `stock_data/explorer/static/index.html` | 修改 | `CAPABILITY_GROUPS.notices` 加 `NEWS_FLASH` |
| 9 | `stock_data/CLAUDE.md` | 修改 | 同步 capability 文档 |
| 10 | `tests/fixtures/flash_news_list.json` | 新建 | 上游响应 fixture（2 条样例） |
| 11 | `tests/test_eastmoney_flash_news.py` | 新建 | fetcher 单元测试 |
| 12 | `tests/test_manager_flash_news.py` | 新建 | manager 路由测试 |

---

### Task 1: 加 NEWS_FLASH capability flag

**Files:**
- Modify: `stock_data/data_provider/base.py:55-56`（`DataCapability` enum 末尾）
- Modify: `stock_data/data_provider/base.py:78-101`（`CAPABILITY_TO_METHOD` dict 末尾）

- [ ] **Step 1: 加 flag 到 enum**

在 `stock_data/data_provider/base.py` 的 `DataCapability` 类末尾、`NEWS_SEARCH` 后面追加：

```python
    NEWS_SEARCH = auto()  # 新闻搜索（关键词 → 列表）
    NEWS_FLASH = auto()  # 全球财经快讯（7×24 实时推送流）
```

- [ ] **Step 2: 在 CAPABILITY_TO_METHOD 末尾追加映射**

在 `stock_data/data_provider/base.py` 的 `CAPABILITY_TO_METHOD` dict 末尾追加：

```python
    DataCapability.NEWS_SEARCH: "search_news",
    DataCapability.NEWS_FLASH: "fetch_flash_news",
}
```

- [ ] **Step 3: 跑 map test 验证（应失败 — 方法还没注册）**

Run: `python -m pytest tests/test_capability_method_map.py::test_mapped_method_exists_on_base_or_subclass -v`
Expected: **FAIL** 包含 `DataCapability.NEWS_FLASH maps to method 'fetch_flash_news'`

这是预期的红 —— 我们的 flag 还没在 fetcher 上注册，等到 Task 4 实现后才会变绿。

- [ ] **Step 4: Commit**

```bash
git add stock_data/data_provider/base.py
git commit -m "feat(base): add NEWS_FLASH capability flag"
```

---

### Task 2: 写 fixture + 失败的 fetcher 测试

**Files:**
- Create: `tests/fixtures/flash_news_list.json`
- Create: `tests/test_eastmoney_flash_news.py`

- [ ] **Step 1: 写 fixture**

新建 `tests/fixtures/flash_news_list.json`（2 条样例，模拟真实 upstream 响应）：

```json
{
  "req_trace": "1710315450384",
  "code": 0,
  "message": "success",
  "data": {
    "sortEnd": "",
    "index": 1,
    "total": null,
    "size": 2,
    "fastNewsList": [
      {
        "summary": "某科技公司全资子公司近日业务调整公告内容。",
        "code": "202606223778033979",
        "titleColor": 0,
        "realSort": 1782116639033979,
        "showTime": "2026-06-22 16:23:59",
        "title": "某科技全资子公司业务调整",
        "share": 1,
        "pinglun_Num": 0,
        "stockList": ["600519", "1.5"],
        "image": []
      },
      {
        "summary": "央行今日开展 1000 亿元 MLF 操作。",
        "code": "202606223778033980",
        "titleColor": 0,
        "realSort": 1782116639033978,
        "showTime": "2026-06-22 16:20:00",
        "title": "央行开展 1000 亿 MLF 操作",
        "share": 0,
        "pinglun_Num": 5,
        "stockList": [],
        "image": []
      }
    ]
  }
}
```

- [ ] **Step 2: 写测试文件**

新建 `tests/test_eastmoney_flash_news.py`：

```python
"""
Unit tests for EastMoneyFetcher.fetch_flash_news().

覆盖字段映射、limit 边界、上游错误码、空响应、复用 _session。
"""
import json
from unittest.mock import MagicMock, patch

import pytest

from stock_data.data_provider.base import DataFetchError
from stock_data.data_provider.fetchers.eastmoney_fetcher import EastMoneyFetcher

FIXTURE_PATH = "tests/fixtures/flash_news_list.json"


def _load_fixture() -> dict:
    with open(FIXTURE_PATH, encoding="utf-8") as f:
        return json.load(f)


def _mock_response(data: dict, status: int = 200) -> MagicMock:
    mock_response = MagicMock()
    mock_response.status_code = status
    mock_response.json.return_value = data
    return mock_response


class TestFetchFlashNewsHappyPath:
    def setup_method(self):
        self.fetcher = EastMoneyFetcher()

    def test_returns_normalized_dicts(self):
        fixture = _load_fixture()
        with patch.object(
            self.fetcher._session, "get", return_value=_mock_response(fixture)
        ):
            results = self.fetcher.fetch_flash_news(limit=50)

        assert len(results) == 2
        first = results[0]
        assert first["title"] == fixture["data"]["fastNewsList"][0]["title"]
        # url 由 code 拼出
        item_code = fixture["data"]["fastNewsList"][0]["code"]
        assert first["url"] == f"https://finance.eastmoney.com/a/{item_code}.html"
        assert first["source_domain"] == "finance.eastmoney.com"
        assert first["publish_time"] == "2026-06-22 16:23:59"
        # summary 改名 snippet
        assert first["snippet"] == fixture["data"]["fastNewsList"][0]["summary"]

    def test_request_uses_flash_endpoint(self):
        fixture = _load_fixture()
        with patch.object(
            self.fetcher._session, "get", return_value=_mock_response(fixture)
        ) as mock_get:
            self.fetcher.fetch_flash_news(limit=20)

        called_url = mock_get.call_args.args[0]
        params = mock_get.call_args.kwargs["params"]
        assert called_url == "https://np-weblist.eastmoney.com/comm/web/getFastNewsList"
        assert params["client"] == "web"
        assert params["biz"] == "web_724"
        assert params["fastColumn"] == "102"
        # pageSize 取 min(limit, 200)
        assert params["pageSize"] == "20"

    def test_limit_capped_to_200(self):
        """用户传 limit=300 也不应让上游 pageSize 超过 200（虽然路由层会拦，但 fetcher 也防御）。"""
        fixture = _load_fixture()
        with patch.object(
            self.fetcher._session, "get", return_value=_mock_response(fixture)
        ) as mock_get:
            self.fetcher.fetch_flash_news(limit=300)

        params = mock_get.call_args.kwargs["params"]
        assert params["pageSize"] == "200"

    def test_limit_below_one_rejected(self):
        """limit=0 在 fetcher 层抛 DataFetchError。"""
        with pytest.raises(DataFetchError):
            self.fetcher.fetch_flash_news(limit=0)

    def test_uses_chrome120_session_not_plain_requests(self):
        """必须调用 self._session.get，不能新建裸 requests.Session。"""
        fixture = _load_fixture()
        with patch.object(
            self.fetcher._session, "get", return_value=_mock_response(fixture)
        ) as mock_get:
            self.fetcher.fetch_flash_news(limit=10)

        assert mock_get.call_count == 1


class TestFetchFlashNewsErrors:
    def setup_method(self):
        self.fetcher = EastMoneyFetcher()

    def test_non_zero_code_raises(self):
        bad = {"code": -1, "message": "rate limit", "data": None}
        with patch.object(
            self.fetcher._session, "get", return_value=_mock_response(bad)
        ):
            with pytest.raises(DataFetchError, match="code=-1"):
                self.fetcher.fetch_flash_news(limit=10)

    def test_http_error_raises(self):
        bad = _mock_response({}, status=500)
        with patch.object(
            self.fetcher._session, "get", return_value=bad
        ):
            with pytest.raises(DataFetchError, match="HTTP 500"):
                self.fetcher.fetch_flash_news(limit=10)

    def test_empty_fast_news_list_returns_empty(self):
        """fastNewsList 缺失或为 null → 返回 []，不抛错。"""
        empty = {"code": 0, "message": "ok", "data": {"size": 0, "fastNewsList": None}}
        with patch.object(
            self.fetcher._session, "get", return_value=_mock_response(empty)
        ):
            results = self.fetcher.fetch_flash_news(limit=10)
        assert results == []

    def test_zero_items_in_list_returns_empty(self):
        zero = {"code": 0, "message": "ok", "data": {"size": 0, "fastNewsList": []}}
        with patch.object(
            self.fetcher._session, "get", return_value=_mock_response(zero)
        ):
            results = self.fetcher.fetch_flash_news(limit=10)
        assert results == []
```

- [ ] **Step 3: 跑测试确认失败**

Run: `python -m pytest tests/test_eastmoney_flash_news.py -v`
Expected: **FAIL** 全部 9 个测试报 `AttributeError: 'EastMoneyFetcher' object has no attribute 'fetch_flash_news'`

- [ ] **Step 4: Commit（红）**

```bash
git add tests/fixtures/flash_news_list.json tests/test_eastmoney_flash_news.py
git commit -m "test(eastmoney): add fixture and failing tests for fetch_flash_news"
```

---

### Task 3: 实现 EastMoneyFetcher.fetch_flash_news（让测试变绿）

**Files:**
- Modify: `stock_data/data_provider/fetchers/eastmoney_fetcher.py:150-159`（`supported_data_types`）
- Modify: `stock_data/data_provider/fetchers/eastmoney_fetcher.py:611-615` 附近（加常量）
- Modify: `stock_data/data_provider/fetchers/eastmoney_fetcher.py:880` 文件末尾（加方法）

- [ ] **Step 1: 把 NEWS_FLASH 加到 supported_data_types**

在 `stock_data/data_provider/fetchers/eastmoney_fetcher.py` 的 `supported_data_types` block（150-159 行），把 `NEWS_SEARCH` 那一行改成 `NEWS_SEARCH` + `NEWS_FLASH`（在末尾追加 `| DataCapability.NEWS_FLASH`）：

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
        | DataCapability.NEWS_FLASH
    )
```

- [ ] **Step 2: 加常量**

在 `stock_data/data_provider/fetchers/eastmoney_fetcher.py` 第 611 行附近（`_NEWS_SEARCH_URL` 后面），追加：

```python
    # -- 7x24 全球财经快讯 ----------------------------------------------------
    _FLASH_NEWS_URL = "https://np-weblist.eastmoney.com/comm/web/getFastNewsList"
    # pageSize 上游硬 cap 200；超过就 cap；下限 1
    _FLASH_NEWS_MAX_PAGE_SIZE = 200
    _FLASH_NEWS_MIN_LIMIT = 1
```

- [ ] **Step 3: 在文件末尾加 fetch_flash_news 方法**

在 `stock_data/data_provider/fetchers/eastmoney_fetcher.py` 第 880 行（`_normalize_news_item` 静态方法后）追加：

```python
    # ------------------------------------------------------------------
    # 7×24 全球财经快讯 (Flash News)
    # ------------------------------------------------------------------

    def fetch_flash_news(self, limit: int = 50) -> list[dict]:
        """Get 7x24 global financial flash news.

        上游 URL: https://np-weblist.eastmoney.com/comm/web/getFastNewsList
        上游 pageSize 硬 cap 200;超过就 cap 到 200。
        响应: ``{"code": 0, "data": {"size": N, "fastNewsList": [...]}}``
        每个 item 字段: title, summary, code (文章 ID), showTime, ...

        Returns:
            归一化后的 list[dict],每条形如:
            ``{title, url, source_domain, publish_time, snippet}``
            当上游 fastNewsList 缺失或为 null 时返回 ``[]``。

        Raises:
            DataFetchError: 网络异常 / HTTP 非 200 / 上游 code != 0 / limit 越界
        """
        # 参数防御: 路由层 FastAPI Query(ge=1, le=200) 会拦,但 fetcher 也独立校验
        # (单一职责, 跨调用方安全)。
        try:
            limit = int(limit)
        except (TypeError, ValueError) as e:
            raise DataFetchError(
                f"[EastMoneyFetcher] fetch_flash_news: limit must be int (got {limit!r})"
            ) from e
        if not (self._FLASH_NEWS_MIN_LIMIT <= limit <= self._FLASH_NEWS_MAX_PAGE_SIZE):
            raise DataFetchError(
                f"[EastMoneyFetcher] fetch_flash_news: limit must be "
                f"{self._FLASH_NEWS_MIN_LIMIT}..{self._FLASH_NEWS_MAX_PAGE_SIZE} (got {limit})"
            )

        page_size = min(limit, self._FLASH_NEWS_MAX_PAGE_SIZE)
        params = {
            "client": "web",
            "biz": "web_724",
            "fastColumn": "102",
            "sortEnd": "",
            "pageSize": str(page_size),
            "req_trace": str(int(time.time() * 1000)),
        }
        headers = {
            "User-Agent": UA,
            "Referer": "https://kuaixun.eastmoney.com/",
        }
        try:
            resp = self._session.get(
                self._FLASH_NEWS_URL, params=params, headers=headers, timeout=15
            )
        except Exception as e:
            raise DataFetchError(
                f"[EastMoneyFetcher] fetch_flash_news network error: {e}"
            ) from e

        if resp.status_code != 200:
            raise DataFetchError(
                f"[EastMoneyFetcher] fetch_flash_news HTTP {resp.status_code}"
            )

        try:
            payload = resp.json()
        except (ValueError, json.JSONDecodeError) as e:
            raise DataFetchError(
                f"[EastMoneyFetcher] fetch_flash_news: bad JSON: {e}"
            ) from e

        if payload.get("code") != 0:
            raise DataFetchError(
                f"[EastMoneyFetcher] fetch_flash_news API code={payload.get('code')} "
                f"msg={payload.get('message')}"
            )

        raw_list = (payload.get("data") or {}).get("fastNewsList")
        if not raw_list:
            return []

        out: list[dict] = []
        for rec in raw_list:
            try:
                code = rec["code"]
                out.append(
                    {
                        "title": rec.get("title", ""),
                        "url": f"https://finance.eastmoney.com/a/{code}.html",
                        "source_domain": "finance.eastmoney.com",
                        "publish_time": rec.get("showTime", ""),
                        "snippet": rec.get("summary", ""),
                    }
                )
            except (KeyError, TypeError) as e:
                # 单条记录缺关键字段(article code)就跳过, 避免一条坏数据废整个 list
                logger.warning(
                    f"[EastMoneyFetcher] fetch_flash_news: skipping malformed record: {e}"
                )
                continue
        return out
```

- [ ] **Step 4: 跑 fetcher 测试**

Run: `python -m pytest tests/test_eastmoney_flash_news.py -v`
Expected: **ALL PASS** (9 tests)

- [ ] **Step 5: 跑 capability map test**

Run: `python -m pytest tests/test_capability_method_map.py -v`
Expected: **ALL PASS** （Task 1 时的红现在变绿）

- [ ] **Step 6: Commit（绿）**

```bash
git add stock_data/data_provider/fetchers/eastmoney_fetcher.py
git commit -m "feat(eastmoney): implement fetch_flash_news for 7x24 flash feed"
```

---

### Task 4: 写 manager 失败的测试

**Files:**
- Create: `tests/test_manager_flash_news.py`

- [ ] **Step 1: 写测试文件**

新建 `tests/test_manager_flash_news.py`：

```python
"""
Tests for DataFetcherManager.get_flash_news() routing.

确认 manager 把 get_flash_news 委托给声明 NEWS_FLASH capability 的 fetcher,
按优先级返回 (result, source)。
"""
from unittest.mock import patch

import pytest

from stock_data.data_provider.base import DataFetchError
from stock_data.data_provider.fetchers.eastmoney_fetcher import EastMoneyFetcher
from stock_data.data_provider.manager import DataFetcherManager


def _make_manager_with_only_eastmoney():
    mgr = DataFetcherManager()
    mgr.reset()
    mgr.add_fetcher(EastMoneyFetcher())
    return mgr


class TestManagerFlashNews:
    def test_routes_to_eastmoney_when_available(self):
        mgr = _make_manager_with_only_eastmoney()
        expected = [
            {"title": "fake", "url": "http://x", "publish_time": "2026-06-22 16:00:00"}
        ]
        with patch.object(
            EastMoneyFetcher, "fetch_flash_news", return_value=expected
        ) as mock_fetch:
            data, source = mgr.get_flash_news(limit=50)

        assert data == expected
        assert source == "EastMoneyFetcher"
        mock_fetch.assert_called_once_with(50)

    def test_propagates_limit(self):
        mgr = _make_manager_with_only_eastmoney()
        with patch.object(
            EastMoneyFetcher, "fetch_flash_news", return_value=[]
        ) as mock_fetch:
            mgr.get_flash_news(limit=200)

        mock_fetch.assert_called_once_with(200)

    def test_only_news_flash_capable_fetchers_are_consulted(self):
        """不声明 NEWS_FLASH 的 fetcher 不应被调用。"""
        from stock_data.data_provider.fetchers.cninfo_fetcher import CninfoFetcher

        mgr = _make_manager_with_only_eastmoney()
        mgr.add_fetcher(CninfoFetcher())  # CNINFO 不声明 NEWS_FLASH

        with patch.object(
            EastMoneyFetcher, "fetch_flash_news", return_value=[]
        ) as mock_fetch:
            mgr.get_flash_news(limit=10)

        # CninfoFetcher 被 _filter_by_capability 过滤掉
        mock_fetch.assert_called_once()

    def test_raises_when_all_fetchers_fail(self):
        mgr = _make_manager_with_only_eastmoney()
        with patch.object(
            EastMoneyFetcher, "fetch_flash_news",
            side_effect=Exception("upstream broken"),
        ):
            with pytest.raises(DataFetchError, match="All fetchers failed"):
                mgr.get_flash_news(limit=10)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_manager_flash_news.py -v`
Expected: **FAIL** `AttributeError: 'DataFetcherManager' object has no attribute 'get_flash_news'`

- [ ] **Step 3: Commit（红）**

```bash
git add tests/test_manager_flash_news.py
git commit -m "test(manager): add failing tests for get_flash_news routing"
```

---

### Task 5: 实现 DataFetcherManager.get_flash_news（让 manager 测试变绿）

**Files:**
- Modify: `stock_data/data_provider/manager.py`（在 `search_news` 方法后面加新方法）

- [ ] **Step 1: 在 manager 加 get_flash_news 方法**

在 `stock_data/data_provider/manager.py` 的 `search_news` 方法后面（约 323 行），追加：

```python
    # ---------- news flash ----------

    def get_flash_news(self, limit: int = 50) -> tuple[list[dict], str]:
        """全球财经快讯 (7x24 实时推送),通过 NEWS_FLASH-capable fetcher 获取。

        上游 pageSize 硬 cap 200;用户传超过 200 时,路由层 Query(le=200) 会先拦,
        这里再二次防御。

        Returns:
            Tuple of (list_of_FlashNewsItem, fetcher_name)。
        """
        return self._with_failover(
            DataCapability.NEWS_FLASH,
            "csi",
            f"news flash limit={limit}",
            lambda f: f.fetch_flash_news(limit),
            return_source=True,
        )
```

- [ ] **Step 2: 跑 manager 测试**

Run: `python -m pytest tests/test_manager_flash_news.py -v`
Expected: **ALL PASS** (4 tests)

- [ ] **Step 3: Commit**

```bash
git add stock_data/data_provider/manager.py
git commit -m "feat(manager): route get_flash_news via NEWS_FLASH capability"
```

---

### Task 6: 加 schema 模型

**Files:**
- Modify: `stock_data/api/schemas.py:737` 附近（`NewsContentResponse` 后面）

- [ ] **Step 1: 在 schemas.py 末尾加新模型**

在 `stock_data/api/schemas.py` 第 738 行（`NewsContentResponse` 末尾）追加：

```python


class FlashNewsItem(BaseModel):
    """单条全球财经快讯。

    字段命名刻意和 ``NewsItem`` 保持风格一致(英文 snake_case),
    区别:
    - ``publish_time`` (含时分秒) vs ``NewsItem.publish_date`` (只到日)
    - ``snippet`` (摘要) vs ``NewsItem.snippet`` (同名)
    - 没有 ``media_name``: 快讯本身不区分发布媒体
    """

    title: str = Field(default="", description="标题 (原文)")
    url: str = Field(description="详情页 URL (https://finance.eastmoney.com/a/{code}.html)")
    source_domain: str = Field(default="finance.eastmoney.com", description="URL 域名")
    publish_time: str = Field(default="", description="发布时间 YYYY-MM-DD HH:MM:SS")
    snippet: str = Field(default="", description="摘要")


class FlashNewsResponse(BaseModel):
    """全球财经快讯响应。"""

    data: list[FlashNewsItem] = Field(default_factory=list, description="快讯列表")
    total: int = Field(default=0, description="实际返回条数 (= len(data))")
    limit: int = Field(default=50, description="请求的 limit (1..200)")
    source: str = Field(
        default="",
        description="数据来源 fetcher 名 (e.g. EastMoneyFetcher)",
    )
```

- [ ] **Step 2: 手动验证模型可被 import**

Run: `python -c "from stock_data.api.schemas import FlashNewsItem, FlashNewsResponse; print(list(FlashNewsItem.model_fields.keys()))"`
Expected: `['title', 'url', 'source_domain', 'publish_time', 'snippet']`

- [ ] **Step 3: Commit**

```bash
git add stock_data/api/schemas.py
git commit -m "feat(schemas): add FlashNewsItem and FlashNewsResponse"
```

---

### Task 7: 加缓存

**Files:**
- Modify: `stock_data/api/cache.py`

- [ ] **Step 1: 加 TTL 常量**

在 `stock_data/api/cache.py` 第 47 行（`_TTL_NEWS_CONTENT` 后面）追加：

```python
_TTL_NEWS_FLASH = int(os.getenv("CACHE_TTL_NEWS_FLASH", "60"))  # 7x24 快讯 (60s)
```

- [ ] **Step 2: 加 cache 实例**

在 `stock_data/api/cache.py` 第 64 行（`_news_content_cache` 后面）追加：

```python
_news_flash_cache: TTLCache = TTLCache(maxsize=64, ttl=_TTL_NEWS_FLASH)
```

- [ ] **Step 3: 加 getter 和 key**

在 `stock_data/api/cache.py` 的 getter 区（在 `get_news_content_cache` 后面）追加：

```python


def get_news_flash_cache() -> TTLCache:
    return _news_flash_cache


def make_news_flash_cache_key(limit: int) -> tuple:
    """Cache key for /news/flash?limit=N. Single-param, opaque tuple."""
    return ("news_flash", limit)
```

- [ ] **Step 4: 手动验证**

Run: `python -c "from stock_data.api.cache import get_news_flash_cache, make_news_flash_cache_key; c = get_news_flash_cache(); print(c.maxsize, c.ttl); print(make_news_flash_cache_key(50))"`
Expected: `64 60` 然后 `('news_flash', 50)`

- [ ] **Step 5: Commit**

```bash
git add stock_data/api/cache.py
git commit -m "feat(cache): add news_flash cache (60s TTL)"
```

---

### Task 8: 加路由

**Files:**
- Modify: `stock_data/api/routes.py`（imports + `search_news` 路由后）

- [ ] **Step 1: 加 imports**

在 `stock_data/api/routes.py` 的 `from .cache import (...)` 块，找到 `get_news_content_cache` 那一行附近，加 `get_news_flash_cache`（注意按字母顺序，flash 在 content 之前）：

```python
from .cache import (
    ...
    get_news_content_cache,
    get_news_flash_cache,                # 新增
    get_news_search_cache,
    ...
    make_news_content_cache_key,
    make_news_flash_cache_key,           # 新增
    make_news_search_cache_key,
    ...
)
```

以及 schema imports：

```python
from .schemas import (
    ...
    FlashNewsItem,                       # 新增
    FlashNewsResponse,                   # 新增
    NewsContentResponse,
    NewsItem,
    NewsSearchResponse,
    ...
)
```

- [ ] **Step 2: 在 search_news 路由后加新路由**

在 `stock_data/api/routes.py` 第 2132 行（`search_news` 函数结束）后面追加：

```python
@news_router.get(
    "/news/flash",
    response_model=FlashNewsResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid limit"},
        502: {"model": ErrorResponse, "description": "All fetchers failed"},
    },
    tags=["news"],
)
@endpoint_meta(
    summary="全球财经快讯（7×24 实时推送）",
    markets=["csi"],
    capabilities=["NEWS_FLASH"],
)
def get_flash_news(
    limit: int = Query(default=50, ge=1, le=200, description="条数 1-200, 默认 50"),
) -> FlashNewsResponse:
    """全球财经快讯（东财 7x24 实时流，60s 缓存）。"""
    try:
        if is_cache_enabled():
            cache = get_news_flash_cache()
            key = make_news_flash_cache_key(limit)
            if key in cache:
                logger.info(f"[APICache] news flash hit: limit={limit}")
                return cache[key]

        manager = get_manager()
        items, source = manager.get_flash_news(limit=limit)

        result = FlashNewsResponse(
            data=[FlashNewsItem(**it) for it in items],
            total=len(items),
            limit=limit,
            source=source,
        )

        if is_cache_enabled():
            cache[key] = result
        return result
    except DataFetchError as e:
        logger.warning(f"News flash unavailable: {e}")
        raise HTTPException(
            status_code=502,
            detail={"error": "data_unavailable", "message": str(e)},
        ) from e
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"News flash error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail={"error": "internal_error", "message": str(e)}
        ) from e
```

- [ ] **Step 3: 跑相关测试（应全过）**

Run: `python -m pytest tests/test_eastmoney_flash_news.py tests/test_manager_flash_news.py tests/test_capability_method_map.py -v`
Expected: **ALL PASS**

- [ ] **Step 4: 启动 server 跑 e2e**

Run:
```bash
python -m stock_data.server &
SERVER_PID=$!
sleep 5

echo "=== happy path ==="
curl -sS "http://127.0.0.1:8888/news/flash?limit=3" | python -m json.tool | head -30

echo
echo "=== HTTP code for limit=5 ==="
curl -sS -o /dev/null -w "%{http_code}\n" "http://127.0.0.1:8888/news/flash?limit=5"

echo "=== HTTP code for limit=201 (over) ==="
curl -sS -o /dev/null -w "%{http_code}\n" "http://127.0.0.1:8888/news/flash?limit=201"

echo "=== HTTP code for limit=0 (under) ==="
curl -sS -o /dev/null -w "%{http_code}\n" "http://127.0.0.1:8888/news/flash?limit=0"

kill $SERVER_PID
```

Expected:
- happy path: 3 条 JSON, `source="EastMoneyFetcher"`
- `limit=5` 返回 200
- `limit=201` 返回 422
- `limit=0` 返回 422

- [ ] **Step 5: Commit**

```bash
git add stock_data/api/routes.py
git commit -m "feat(route): add GET /news/flash endpoint"
```

---

### Task 9: 同步 explorer manifest 依赖

**Files:**
- Modify: `stock_data/explorer/tags.py:35-58`（`CAPABILITY_LABELS`）
- Modify: `stock_data/explorer/static/index.html:766`（`CAPABILITY_GROUPS.notices`）

- [ ] **Step 1: 加 CAPABILITY_LABELS 条目**

在 `stock_data/explorer/tags.py` 的 `CAPABILITY_LABELS` 末尾（`NEWS_SEARCH` 后面）追加：

```python
    "NEWS_SEARCH":      {"label": "新闻搜索",         "icon": "🔍"},
    "NEWS_FLASH":       {"label": "全球财经快讯",     "icon": "📡"},
```

- [ ] **Step 2: 把 NEWS_FLASH 加到 index.html 的 notices group**

在 `stock_data/explorer/static/index.html` 第 766 行，把：

```javascript
      notices:  ["DRAGON_TIGER", "HOLDER_NUM", "DIVIDEND", "RESEARCH_REPORT", "ANNOUNCEMENT", "NEWS_SEARCH"],
```

改成：

```javascript
      notices:  ["DRAGON_TIGER", "HOLDER_NUM", "DIVIDEND", "RESEARCH_REPORT", "ANNOUNCEMENT", "NEWS_SEARCH", "NEWS_FLASH"],
```

- [ ] **Step 3: 跑 capability map test 验证（覆盖 explorer guard）**

Run: `python -m pytest tests/test_capability_method_map.py -v`
Expected: **ALL PASS** （`test_every_capability_is_in_CAPABILITY_LABELS` 和 `test_every_capability_is_in_some_CAPABILITY_GROUP` 都通过）

- [ ] **Step 4: 启动 server 验证 manifest 包含 /news/flash**

Run:
```bash
python -m stock_data.server &
SERVER_PID=$!
sleep 5
curl -sS "http://127.0.0.1:8888/control/api-manifest" | python -c "
import json, sys
m = json.load(sys.stdin)
endpoints = [(s.get('tag'), e.get('path')) for s in m.get('sections', []) for e in s.get('endpoints', [])]
flash = [e for t, e in endpoints if e == '/news/flash']
print('Found /news/flash:', len(flash))
assert flash, 'flash endpoint not in manifest'
"
kill $SERVER_PID
```

Expected: `Found /news/flash: 1`

- [ ] **Step 5: Commit**

```bash
git add stock_data/explorer/tags.py stock_data/explorer/static/index.html
git commit -m "feat(explorer): register NEWS_FLASH in capability labels and groups"
```

---

### Task 10: 同步 CLAUDE.md 文档

**Files:**
- Modify: `stock_data/CLAUDE.md`

- [ ] **Step 1: 更新 EastMoneyFetcher capability 描述**

在 `stock_data/CLAUDE.md` 找到 EastMoneyFetcher 那一行（provider API 表格中，capabilities 列含 `NEWS_SEARCH`），把 `NEWS_SEARCH` 改成 `NEWS_SEARCH \| NEWS_FLASH`。

定位关键字：搜索 `EastMoneyFetcher` + `NEWS_SEARCH`。

- [ ] **Step 2: 在 capability-routing 表里加 get_flash_news 行**

定位关键字：搜索 "get_announcements" 表格行（Manager 路由方法表），在其后加：

```
| `get_flash_news` | `NEWS_FLASH` |
```

- [ ] **Step 3: Commit**

```bash
git add stock_data/CLAUDE.md
git commit -m "docs(CLAUDE): document NEWS_FLASH capability"
```

---

### Task 11: 端到端冒烟验证 + 任务相关测试

**Files:** 无修改

- [ ] **Step 1: 跑所有任务相关测试**

Run:
```bash
python -m pytest \
  tests/test_eastmoney_flash_news.py \
  tests/test_manager_flash_news.py \
  tests/test_capability_method_map.py \
  tests/test_explorer_manifest_endpoint.py \
  tests/test_manifest.py \
  tests/test_manifest_resolve_fetchers.py \
  tests/test_manifest_signature.py \
  tests/test_endpoint_meta.py \
  tests/test_eastmoney_search_news.py \
  tests/test_manager_news_search.py \
  -v
```
Expected: **ALL PASS**

- [ ] **Step 2: 启动 server 跑最终 e2e**

Run:
```bash
python -m stock_data.server &
SERVER_PID=$!
sleep 5

echo "=== happy path ==="
curl -sS "http://127.0.0.1:8888/news/flash?limit=3" | python -m json.tool | head -30

echo
echo "=== limit=1 (min) ==="
curl -sS -o /dev/null -w "HTTP %{http_code}\n" "http://127.0.0.1:8888/news/flash?limit=1"

echo "=== limit=200 (max) ==="
curl -sS -o /dev/null -w "HTTP %{http_code}\n" "http://127.0.0.1:8888/news/flash?limit=200"

echo "=== limit=201 (over) ==="
curl -sS -o /dev/null -w "HTTP %{http_code}\n" "http://127.0.0.1:8888/news/flash?limit=201"

echo "=== limit=0 (under) ==="
curl -sS -o /dev/null -w "HTTP %{http_code}\n" "http://127.0.0.1:8888/news/flash?limit=0"

echo "=== cache hit (second call within 60s) ==="
curl -sS "http://127.0.0.1:8888/news/flash?limit=5" > /dev/null
curl -sS "http://127.0.0.1:8888/news/flash?limit=5" > /dev/null
echo "(check server logs for '[APICache] news flash hit')"

kill $SERVER_PID
```

Expected:
- happy path: 3 条 JSON, 字段齐全（title, url, source_domain, publish_time, snippet）, `source="EastMoneyFetcher"`
- `limit=1` / `limit=200` 都返回 200
- `limit=201` / `limit=0` 返回 422 (FastAPI 校验)
- 第二次同样的 limit=5 调用，server log 有 `[APICache] news flash hit`

- [ ] **Step 3: 如果所有验证通过,不需要再 commit**

如果任一步骤失败,定位修复,然后单独 commit 修复,再回到这一步重跑。

---

## 自检结果

- [x] **Spec coverage**：spec 的 5 处文件改动 + CLAUDE.md 同步 + 1 个新测试文件全部覆盖（Task 1-10）。Task 11 跑任务相关测试。
- [x] **Placeholder scan**：无 TBD/TODO；每步都有具体代码块。
- [x] **Type consistency**：
  - `fetch_flash_news(limit: int) -> list[dict]` —— 在 fetcher (Task 3)、manager lambda (Task 5)、route (Task 8) 三处签名一致
  - `get_flash_news(limit: int) -> tuple[list[dict], str]` —— manager (Task 5) 和 route (Task 8) 一致
  - `FlashNewsItem` 字段名 `title, url, source_domain, publish_time, snippet` —— schema (Task 6) 和 route 解构 (Task 8) 一致
  - `make_news_flash_cache_key(limit)` —— cache (Task 7) 和 route (Task 8) 一致
- [x] **任务顺序遵循 TDD**：fixture + 红测试 (Task 2) → 实现 (Task 3) → 测试变绿
- [x] **频率 commit**：每个 Task 末尾都有 commit
- [x] **不走全量测试**：Task 11 明确列出任务相关测试范围（受 `subagent-test-scope` 经验约束）
