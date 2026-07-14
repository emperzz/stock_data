# CLS Fetcher Design — 早报 + 焦点复盘

**Date:** 2026-07-14
**Status:** Approved (pending user review of written spec)
**Scope:** Add 2 new API endpoints (财联社早报、焦点复盘) + supporting `ClsFetcher` + 2 new `DataCapability` flags.

---

## 1. Goal

Expose 财联社 (CLS) 的两个主题流（**早报** / **焦点复盘**）作为稳定 API，供 AI agent 按日取用完整文章内容。

- 早报 URL: `https://www.cls.cn/subject/1151`
- 复盘 URL: `https://www.cls.cn/subject/1135`
- 单篇详情 URL 模板: `https://www.cls.cn/detail/{article_id}`

**Data source decision (verified 2026-07-14 via playwright):**
- CLS 列表页和详情页都是 Next.js SSR，`__NEXT_DATA__` 把完整结构化 JSON 嵌进 HTML。
- 不需要 headless browser、不需要 token / cookie、User-Agent 即可。
- 列表页一次返回最近 **~20-28 天**文章（无分页 API，详情见 §5 历史窗口限制）。

---

## 2. Design Constraints (verified by probing)

- **Plain `requests.get()` 即可**：HTML 改用 BS4 仅用于详情页 `body_text` 抽取；列表页解析走 `re.search` + `json.loads`。
- **历史窗口固定 ~20-28 天**：上游不暴露分页接口。超过窗口的日期 → API 返 404。
- **不加 `list` endpoint**：server 内部完成 list→article_id→detail 编排，对外仅暴露 `?date=` 入参。
- **Capability-flagged 路由**：`MORNING_BRIEFING` / `MARKET_RECAP` 两个新 flag。Manager 走 `_with_failover`（非 `_with_source`）—— 未来 EastMoney 接入同名 capability 时零改动。
- **方法命名无 cls 前缀**：`manager.get_morning_briefing(date)` / `get_market_recap(date)`，subject_id（1151/1135）是 ClsFetcher 内部细节，不外泄。

---

## 3. Architecture

```
GET /cls/morning-briefing?date=YYYY-MM-DD
        │
        ▼
api/routes/cls.py  ─→  manager.get_morning_briefing(date)
        │                       │
        │                       ▼  _with_failover(capability=MORNING_BRIEFING)
        │                ClsFetcher.get_morning_briefing(date)
        │                       │
        │                       ▼  (list 内部，外部不可见)
        │                _find_article_id_by_date(1151, date)
        │                       │  GET /subject/1151  → 解析 __NEXT_DATA__
        │                       ▼
        │                _fetch_article_detail(article_id)
        │                       │  GET /detail/{id}/  → 解析 __NEXT_DATA__ + BS4 抽 body_text
        │                       ▼
        │                return ClsArticle dict
        ▼
return ClsFeedResponse
```

**4 层职责**（与项目惯例对齐）：
1. **Route layer** (`api/routes/cls.py`): 入参校验 + `@map_errors` + 调 manager
2. **Manager** (`data_provider/manager.py`): `_with_failover` 编排
3. **Fetcher** (`data_provider/fetchers/cls_fetcher.py`): 实际 HTTP + 解析
4. **Utils**: `re` / `json` / `bs4` (已有)

---

## 4. Public API

### 4.1 `GET /api/v1/cls/morning-briefing`

**Endpoint metadata (`@endpoint_meta`):**
```python
@endpoint_meta(
    summary="财联社早报（按日取最新早报全文）",
    markets=["csi"],
    capabilities=["MORNING_BRIEFING"],
    tags=["cls"],
)
```

**Query parameters:**
- `date` (required, `YYYY-MM-DD`): 早报日期

**Response 200** (`ClsFeedResponse`):
```json
{
  "subject": "morning_briefing",
  "subject_id": 1151,
  "date": "2026-07-14",
  "article": {
    "article_id": 2425210,
    "title": "【早报】美伊冲突升级；美股存储股再度重挫；国际油价暴涨9%，金价大跌",
    "brief": "①李强：加大逆期调节力度...",
    "author": "财联社",
    "date": "2026-07-14",
    "ctime": 1783983600,
    "read_num": 546144,
    "comments_num": 19,
    "share_num": 1333,
    "images": ["https://image.cls.cn/images/20260714/..."],
    "body_text": "宏观新闻\n\n1、外交部发言人宣布..."
  },
  "source": "cls"
}
```

**Error responses:**

| Status | When |
|---|---|
| 400 | `date` missing / non-YYYY-MM-DD / > today |
| 404 | `date` < 窗口起始日 OR 该日 CLS 未发布 |
| 503 | All fetchers in `MORNING_BRIEFING` capability failed (`DataFetchError`) |
| 500 | Unhandled exception |

### 4.2 `GET /api/v1/cls/market-review`

**Endpoint metadata (`@endpoint_meta`):**
```python
@endpoint_meta(
    summary="财联社焦点复盘（按日取最新复盘全文）",
    markets=["csi"],
    capabilities=["MARKET_RECAP"],
    tags=["cls"],
)
```

同 4.1 区别：`subject="market_review"` / `subject_id=1135`。

---

## 5. Historical Window Limit

**Hard limit: ~20-28 days, no pagination API upstream.**

- 探查结论：list 页 `__NEXT_DATA__.props.pageProps.data.articles[]` 始终含 20 条最新文章。最老一条 → 最新一条的时间戳差 = 约 20-28 天（工作日 vs 节假日造成波动）。
- 应对：API 入参 `date` 早于 `today - 30 days` → 400 (bad request)；`date` 命中但 articles[] 里无该日 → 404。
- 404 边界澄清：route 层必须显式把 `(None, "")` 转 404，而**不是** 503。`allow_none=True` 的 `_with_failover` 在"上游返空"和"所有 fetchers 失败"时都返 `(None, "")`；只有当 `call` 抛 `DataFetchError` 时才会变成 503。所以 route 的判定顺序：(a) 抛 `DataFetchError` → 503；(b) 返 `None` → 404；(c) 返 dict → 200。
- 客户端需要更老的历史 → 上游无 API、爬取无分页，本次设计**不解决**（YAGNI；如需后续可探索 CLS 移动端 H5 接口或其他爬取路径）。

---

## 6. Data Schema (Pydantic models)

新增于 `stock_data/api/schemas.py`:

```python
class ClsArticle(BaseModel):
    article_id: int
    title: str
    brief: str
    author: str
    date: str                  # YYYY-MM-DD
    ctime: int                 # unix timestamp
    read_num: int
    comments_num: int
    share_num: int
    images: list[str] = []
    body_text: str             # 必填，BS4 抽出的纯文本

class ClsFeedResponse(BaseModel):
    subject: str               # "morning_briefing" | "market_review"
    subject_id: int
    date: str
    article: ClsArticle | None
    source: str = "cls"
```

**设计权衡**：
- `body_text` 为纯文本（不含 HTML 标签）—— agent 场景下 token 更省；图片 URL 单独走 `images[]` 字段。**抽取方式**：`BeautifulSoup(content, "lxml").get_text("\n", strip=True)` —— `separator="\n"` 保留段落分隔（HTML `<p>` 之间插入换行），`strip=True` 去除行内首尾空白。然后用 `re.sub(r"\n{3,}", "\n\n", text)` 折叠连续空行。
- `article` 字段允许 None —— 404 与"无内容"语义统一为 None。
- `source` 字段由 route 层在每次响应时由 `manager_result[1]` 填充到响应（`response.source = manager_result[1]`）。当前总为 `"cls"`（manager failover 链唯一），未来 EastMoney 接入同名 capability 时，manager 会返回对应 fetcher 名字。Schema 默认值 `"cls"` 仅用于单测构造；运行时由 route 显式覆盖。

---

## 7. Manager & Fetcher Methods

### 7.1 `DataFetcherManager` (新增 2 个方法)

`_with_failover` 实际签名（`manager.py:263-302`）：
```python
def _with_failover(
    self,
    capability: DataCapability,
    market: str,
    op_label: str,
    call: Callable[[BaseFetcher], T],
    *,
    allow_none: bool = False,
    error_prefix: str | None = None,
    return_source: bool = False,
    ...
) -> T
```

Spec 实现（对齐 `search_news` 在 `manager.py:502` 的写法）：

```python
def get_morning_briefing(self, date: str) -> tuple[dict | None, str]:
    return self._with_failover(
        capability=DataCapability.MORNING_BRIEFING,
        market="csi",
        op_label="get_morning_briefing",
        call=lambda f: f.get_morning_briefing(date),
        allow_none=True,                # 该日无发布 → 返 None
        return_source=True,
    )

def get_market_recap(self, date: str) -> tuple[dict | None, str]:
    return self._with_failover(
        capability=DataCapability.MARKET_RECAP,
        market="csi",
        op_label="get_market_recap",
        call=lambda f: f.get_market_recap(date),
        allow_none=True,
        return_source=True,
    )
```

**Failover 链**：当前 = `[ClsFetcher]`。未来 EastMoney 接入同名 capability + 实现同名方法时，链自动扩展为 `[ClsFetcher, EastMoneyFetcher]`，按 priority 顺序尝试。manager 代码零改动。

**`(None, "")` 语义**：见 §5 "404 边界澄清"。

### 7.2 `ClsFetcher` (新增 fetcher)

| Method | Signature | Behavior |
|---|---|---|
| `name` / `priority` | class attr | `name="ClsFetcher"`, `priority=int(os.getenv("CLS_PRIORITY", "8"))` |
| `supported_markets` | class attr | `{"csi"}`（CLS 财经新闻属中国市场） |
| `supported_data_types` | class attr | `DataCapability.MORNING_BRIEFING \| DataCapability.MARKET_RECAP` |
| `is_available()` | `() -> bool` | 始终 True（无 token / 无 SDK 依赖） |
| `_normalize_data` | `(df, stock_code) -> DataFrame` | 抛 `DataFetchError("ClsFetcher does not support K-line")`（继承 `BaseFetcher` 抽象方法） |
| `get_morning_briefing` | `(date: str) -> dict \| None` | `_find_article_id_by_date(1151, date)` → `_fetch_article_detail(article_id)` |
| `get_market_recap` | `(date: str) -> dict \| None` | 同上，subject_id=1135 |
| `_find_article_id_by_date` | `(subject_id, date) -> int \| None` | 拉 list 页，遍历 `__NEXT_DATA__.props.pageProps.data.articles[]` 找 date 匹配（每条 `article_time` 转 YYYY-MM-DD 后字符串等值比对） |
| `_fetch_article_detail` | `(article_id) -> dict` | 拉 detail 页，从 `__NEXT_DATA__.props.pageProps.articleDetail` 取字段组装 ClsArticle dict |
| `_parse_next_data` | `(html) -> dict` | `re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)` + `json.loads` 提 `__NEXT_DATA__` |
| `_extract_body_text` | `(html_content: str) -> str` | `BS4(html_content, "lxml").get_text("\n", strip=True)` + 折叠空行 |

**Upstream JSON 路径约定**（以探查实测为准）：

- **list 页** `__NEXT_DATA__.props.pageProps.data.articles[]`：
  - 每条 = `{article_id, article_title, article_brief, article_author, article_time(unix ts), article_img, read_num, comments_num, share_num, subjects[]}`
  - `date` 派生 = `datetime.fromtimestamp(article_time).strftime("%Y-%m-%d")`
- **detail 页** `__NEXT_DATA__.props.pageProps.articleDetail`：
  - `{id, title, brief, content (HTML), ctime, readingNum, author.name, commentNum, images[], subject[]}`
  - `body_text` = `_extract_body_text(content)`（BS4 抽纯文本，保留段落分隔）
  - `images` 合并去重：`articleDetail.images[]` ∪ 从 `content` 内 `<p><img src=...>` 解析出的 src（`BS4(content).find_all("img")` 提取 `src`）
  - `date` 派生 = `datetime.fromtimestamp(ctime).strftime("%Y-%m-%d")`

**`_normalize_data` 占位**：ClsFetcher 不支持 K-line，但 `BaseFetcher._normalize_data` 是 `@abstractmethod`，必须 override 即使只是抛错（否则 `ClsFetcher()` 都不能实例化）。这是项目惯例（参考 `CninfoFetcher._normalize_data`）。

### 7.3 `DataCapability` 新增 + `CAPABILITY_TO_METHOD` 新增

```python
class DataCapability(Flag):
    ...
    MORNING_BRIEFING = auto()
    MARKET_RECAP = auto()

CAPABILITY_TO_METHOD = {
    ...
    DataCapability.MORNING_BRIEFING: "get_morning_briefing",
    DataCapability.MARKET_RECAP: "get_market_recap",
}
```

`tests/test_capability_method_map.py` 自动验证映射完整性，无需新增测试代码。

### 7.4 `explorer/tags.py` 新增 capability labels

`tests/test_capability_method_map.py:144` (`test_every_capability_has_a_label_in_capability_labels`) 强制要求每个 `DataCapability` flag 在 `stock_data/explorer/tags.py::CAPABILITY_LABELS` 中有 `{label, icon}` 条目。需新增：

```python
DataCapability.MORNING_BRIEFING: {"label": "财联社早报", "icon": "📰"},
DataCapability.MARKET_RECAP: {"label": "财联社复盘", "icon": "📊"},
```

---

## 8. Caching

TTLCache 在 route 层加（与 `news.py` 一致模式）：

- **不**复用 `get_news_search_cache()` —— 它有 300s（5 min）TTL（`CACHE_TTL_NEWS_SEARCH`），与 CLS 不可变新闻流的特征不匹配。
- 新增独立 `get_cls_feed_cache()` 实例（`api/cache.py`），TTL = `CACHE_TTL_CLS_FEED` 默认 **3600s（1h）**，与 CLS 文章发布后不变的安全前提匹配。
- 缓存 key = `(subject, date)` —— 两个 endpoint 的 key 命名空间隔离。
- `make_cls_feed_cache_key(subject, date)` 作为 module-level helper 添加在 `api/cache.py`（按项目惯例的 `make_*_cache_key` 模式）。

```python
# api/cache.py 新增
_CLS_FEED_TTL = int(os.getenv("CACHE_TTL_CLS_FEED", "3600"))
_cls_feed_cache: TTLCache = TTLCache(maxsize=512, ttl=_CLS_FEED_TTL)

def get_cls_feed_cache() -> TTLCache:
    return _cls_feed_cache

def make_cls_feed_cache_key(subject: str, date: str) -> str:
    return f"cls:{subject}:{date}"
```

```python
# api/routes/cls.py
@cache_endpoint(
    cache_fn=lambda *args, **kwargs: get_cls_feed_cache(),
    key_builder=lambda date: make_cls_feed_cache_key("morning_briefing", date),
    hit_label="cls_morning_briefing",
)
def get_morning_briefing(date: str = ...) -> ClsFeedResponse:
    ...

@cache_endpoint(
    cache_fn=lambda *args, **kwargs: get_cls_feed_cache(),
    key_builder=lambda date: make_cls_feed_cache_key("market_review", date),
    hit_label="cls_market_review",
)
def get_market_recap(date: str = ...) -> ClsFeedResponse:
    ...
```

**注意**：CLS 文章发布日期当天可能在 7-8 点后才有；缓存命中时不会发现 "今天还没发布"。客户端在 7-8 点前请求 → 命中昨日缓存，**对早报场景这是正确行为**（早报是次日看的，agent 不太可能在当日 7 点前调今日早报）。

---

## 9. Error Handling

Route 层用 `@map_errors` 装饰器 + `api/routes/errors.py` 集中处理（对齐 `errors.py:46-66` 现有翻译规则）：

| Exception | HTTP | 触发场景 |
|---|---|---|
| `HTTPException(400)` | 400 | `date` 缺失 / 格式错 / 未来日期 / 早于窗口 |
| `HTTPException(404)` | 404 | list 返 0 命中 / detail 返空（route 显式判 `result is None` → 404） |
| `DataFetchError` | 503 | upstream HTTP 5xx / 解析失败 / 网络异常 / 所有 fetchers 失败 |
| `Exception` | 500 | 兜底 |

Manager 层 `_with_failover(allow_none=True, return_source=True)` 返回 `(None, "")` 区分于抛错：
- 抛 `DataFetchError` → 503
- 返 `(None, "")` → route 显式 raise `HTTPException(404)`，**不**走 `@map_errors`
- 返 `(dict, "cls")` → 200

**重要**：`@map_errors` 不会把 `(None, "")` 自动转 404 —— 那需要 route 在 `manager.get_morning_briefing(date)` 之后显式判空。这是 project 现有 `search_news` 等 endpoint 的同样模式（route 决定 404 vs 502 的边界）。

---

## 10. Testing Strategy

### 10.1 Unit tests (`tests/test_cls_fetcher.py`)

| Test | 验证 |
|---|---|
| `test_parse_next_data_valid` | 标准 HTML → dict |
| `test_parse_next_data_no_script` | 无 `__NEXT_DATA__` → 抛 |
| `test_parse_next_data_malformed_json` | JSON 截断 → 抛 |
| `test_parse_subject_articles_normal` | 5 篇 articles → 5 个标准化 dict |
| `test_parse_subject_articles_limit` | limit=2 → 返 2 |
| `test_parse_subject_articles_empty` | articles=[] → 返 [] |
| `test_find_article_id_by_date_match` | date 命中 → 返 article_id |
| `test_find_article_id_by_date_no_match` | date 不在 list → 返 None |
| `test_fetch_article_detail_normal` | detail HTML → body_text + images 完整 |
| `test_fetch_article_detail_strips_html` | body_text 不含 `<p>`/`<strong>`/`<a>` 标签 |
| `test_fetch_article_detail_image_dedup` | images 字段与 content 内 `<img>` 重复 → 去重 |
| `test_get_morning_briefing_full_path` | mock 两次 HTTP（list + detail）→ 完整 dict |
| `test_get_morning_briefing_not_found` | list 无目标 date → 返 None |
| `test_get_market_recap_full_path` | 同上，subject_id=1135 |

### 10.2 Route tests (`tests/test_cls_endpoints.py`)

| Test | 验证 |
|---|---|
| `test_morning_briefing_missing_date` | 400 |
| `test_morning_briefing_bad_date_format` | 400 |
| `test_morning_briefing_future_date` | 400 |
| `test_morning_briefing_old_date` | 400 (date < today-30) |
| `test_morning_briefing_no_article` | 404 |
| `test_morning_briefing_success` | 200, response 完整 |
| `test_market_review_*` | 同上 6 case |

### 10.3 Live network tests (`@pytest.mark.live_network`)

| Test | 验证 |
|---|---|
| `test_live_get_morning_briefing_today` | `?date=<today>` → 200, body_text 非空 |
| `test_live_get_market_recap_today` | 同上 |
| `test_live_get_morning_briefing_yesterday` | `?date=<yesterday>` → 200 |
| `test_live_subject_list_window` | 直接调 fetcher.list → ≥3 篇，跨度 ≥3 天（避免长周末 flakiness；不严格依赖 7 天跨度） |

### 10.4 Fixture discipline

按项目 memory `fixture-must-match-real-upstream`：所有 fixture 字符串用 2026-07-14 playwright 实际抓到的 `__NEXT_DATA__` 截取/脱敏，**不臆造字段名/类型**。

### 10.5 capability map test

`tests/test_capability_method_map.py` 自动覆盖新 flag。

---

## 11. File Changes

| Path | Action | Notes |
|---|---|---|
| `stock_data/data_provider/base.py` | modify | +2 `DataCapability` flags, +2 `CAPABILITY_TO_METHOD` rows |
| `stock_data/data_provider/manager.py` | modify | (a) +2 manager methods (b) `create_default_manager()` 实例化 `ClsFetcher` 并 `add_fetcher()` 注册（关键 — 不注册则 capability filter 返空） |
| `stock_data/data_provider/fetchers/cls_fetcher.py` | **new** | ~250 行 |
| `stock_data/data_provider/fetchers/__init__.py` | modify | export `ClsFetcher` |
| `stock_data/api/routes/cls.py` | **new** | 2 endpoints |
| `stock_data/api/schemas.py` | modify | +2 Pydantic models |
| `stock_data/server.py` | modify | `app.include_router(cls_router, prefix="/api/v1")`（与其他 9 个数据 router 一致的 v1 prefix） |
| `stock_data/api/cache.py` | modify | + `get_cls_feed_cache()` / `make_cls_feed_cache_key()` / `_CLS_FEED_TTL` / `_cls_feed_cache` (与 `_news_search_cache` 同模式) |
| `stock_data/explorer/tags.py` | modify | (a) `CAPABILITY_LABELS` +2 entries（MORNING_BRIEFING / MARKET_RECAP → `{label, icon}`），否则 `test_capability_method_map.py` 红。(b) `TAG_TO_TITLE` +1 entry（`"cls"` → `"财联社"`，与 §4 endpoint metadata `tags=["cls"]` 对应），否则 `_validate_manifest_invariants` 启动会 warn |
| `tests/test_cls_fetcher.py` | **new** | fetcher 单元测试 |
| `tests/test_cls_endpoints.py` | **new** | route 单元测试 |
| `tests/fixtures/cls_subject_list.json` | **new** | 脱敏 fixture |
| `tests/fixtures/cls_article_detail.json` | **new** | 脱敏 fixture |
| `CLAUDE.md` | modify | 加 ClsFetcher 表格行 + 2 endpoint 行 + CAPABILITY 路由表行 |

**依赖**：无新增（`requests` / `beautifulsoup4` / `re` / `json` 已就位）。

---

## 12. Anti-Patterns Avoided

- **未引入 playwright** —— `__NEXT_DATA__` 是结构化 JSON，HTML 解析即可；引入 ~250MB 浏览器二进制违反 "轻量数据服务" 定位。
- **未加 list endpoint** —— 对外隐藏 list 编排，API 表面最小化。
- **未用 `_with_source`** —— 用 `_with_failover`，未来 EastMoney 接入时零 manager 改动。
- **未硬编码 subject_id 到 manager** —— 1151/1135 仅在 ClsFetcher 内部。
- **未写 HTML→Markdown 转换** —— body_text 用 `BeautifulSoup.get_text()` 抽出纯文本已够 agent 消费。
- **未持久化到 SQLite** —— CLS 文章是只读新闻流，TTLCache 足矣（与 `/news/flash` 决策一致）。
- **未做爬虫并发** —— 单日 2 次 HTTP（list+detail）串行 1-3s 内完成，无需并发。

---

## 13. Future Work (out of scope for this spec)

- **更老历史** (~21+ 天): 需要探查 CLS 移动 H5 接口或 search 端点；本次不解决。
- **多 fetcher failover** (EastMoney 接入): 留待未来；本 spec 留好 capability+方法签名口子。
- **图片代理/缓存** (CLS 图床访问偶有 403): 如 agent 反馈图打不开再加。
- **早报音频**: 早报有 `video_duration` 字段，本期不暴露音频流 URL（仅文字版够用）。
