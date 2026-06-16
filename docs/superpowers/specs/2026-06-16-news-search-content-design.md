# 新闻搜索 + 内容提取 API 设计文档

> 日期：2026-06-16
> 状态：待审
> 范围：在 `EastmoneyFetcher` 上新增 `search_news` 方法，新增 `NewsContentExtractor` 工具类，新增 `GET /news/search` 和 `GET /news/content` 两个 endpoint，新增 `NEWS_SEARCH` capability

## 1. 目标与范围

为项目增加两个新能力：

1. **新闻搜索**：给定关键词（可以是股票代码、主题或自由文本），返回相关新闻列表（标题、URL、来源、发布时间、摘要）。
2. **新闻内容提取**：给定新闻 URL，抓取详情页并提取正文（已清洗的纯文本 + 元数据）。

**v1 范围**：
- 只接入**东方财富**作为搜索源（API: `https://so.eastmoney.com/web/s?keyword=...`）
- 内容提取走通用 `NewsContentExtractor`（内置 domain 分发，未来可加 source-specific handler）
- 不包含：Tavily / MiniMax 等通用搜索 API（架构上预留 capability 注册位，**零改动即可后续接入**）

**架构选型**：search 走 fetcher + capability 路由（与现有体系一致），content 走统一工具类（与 `utils/normalize.py` 同级）。

## 2. 架构

```
                ┌──────────────────────────────────────────┐
                │   api/routes.py  (新增两个 endpoint)       │
                │   GET /news/search   GET /news/content   │
                └──────────────┬───────────────────────────┘
                               │
       ┌───────────────────────┴────────────────────────┐
       │                                                │
       ▼                                                ▼
┌─────────────────────────┐                ┌────────────────────────────┐
│  DataFetcherManager     │                │  NewsContentExtractor      │
│  (新增 search_news)     │                │  data_provider/utils/      │
│  走 _with_failover      │                │  news_extractor.py         │
└──────────┬──────────────┘                │  extract(url) -> text      │
           │  按 NEWS_SEARCH               │  + 内部 domain 分发          │
           ▼                               └────────────────────────────┘
┌──────────────────────────────────────────────────────────┐
│  EastmoneyFetcher (扩展现有类)                              │
│  ├ 现有 capabilities: DRAGON_TIGER | MARGIN | ...        │
│  │   | RESEARCH_REPORT | HOLDER_NUM | ...                │
│  ├ 新增 NEWS_SEARCH (v1)                                   │
│  └ 新方法: search_news(q, from_, to_, limit)              │
└──────────────────────────────────────────────────────────┘
```

**关键边界**：
- `DataFetcherManager` 只管 `search_news` (按 capability 路由 + 优先级 failover)
- `NewsContentExtractor` **不是 fetcher**：不注册 capability、不进 `_filter_by_capability`、不进 explorer 的 fetcher drilldown
- 三个未来的搜索源（Tavily / MiniMax）只需各自实现 `BaseFetcher` + `search_news()` + 注册 `NEWS_SEARCH` capability，即可被 manager 自动路由

## 3. 数据流

### Search 流程

```
GET /news/search?q=贵州茅台&from=2025-01-01&to=2025-01-31&limit=20
   │
   ▼
routes.py: parse params, validate
   │
   ▼
manager.search_news(q, from_, to_, limit)
   │
   ▼
_with_failover(capability=NEWS_SEARCH, market="csi",
               call=f.search_news(q, from_, to_, limit))
   │
   ├─→ EastmoneyFetcher (P6)
   │     │
   │     ▼
   │     HTTP GET https://search-api-web.eastmoney.com/search/jsonp
   │       ?cb=jQuery_cb
   │       &param={"uid":"","keyword":q,"type":["cmsArticleWebOld"],
   │               "client":"web","clientType":"web","clientVersion":"curr",
   │               "param":{"cmsArticleWebOld":{
   │                 "searchScope":"default","sort":"default",
   │                 "pageIndex":1,"pageSize":limit,
   │                 "preTag":"<em>","postTag":"</em>"}}}
   │     │
   │     ▼
   │     parse JSONP → result.cmsArticleWebOld[]  →  strip <em>  →  post-filter [from_, to_]
   │     │
   │     ▼
   │     [NewsItem]
   │     ↓ raise DataFetchError
   │  (v1 没有下家,直接 502)
   ▼
   raise DataFetchError → 502
```

**注**: `from`/`to` 日期过滤是**客户端** post-filter(API 不支持服务端日期过滤),只对返回的 `limit` 条结果生效。如果用户指定很长的日期范围但 `limit` 太小,可能拿不到日期范围内的全部结果 —— 这是已知限制(在 §11 风险中记录)。

### Content 流程

```
GET /news/content?url=http://finance.eastmoney.com/a/202606153771411317.html
   │
   ▼
routes.py: parse url, validate (http/https only, SSRF check)
   │
   ▼
NewsContentExtractor.extract(url)
   │
   ▼
1. domain = urlparse(url).netloc (strip leading "www.")
2. if domain in _domain_handlers: handler = _domain_handlers[domain]
   else: handler = _default_handler
3. handler(url) →
   a. SSRF re-check (resolve DNS, reject private IPs)
   b. requests.get(url, headers=UA, timeout=15)
   c. parse HTML
   d. domain-specific strategy:
      - finance.eastmoney.com / stock.eastmoney.com:
          - title: <div class="topbox"> 第一行 (按 \n 切, 取第一段)
          - source_date: <div class="infos"> 或 .topbox 中 "YYYY年MM月DD日 HH:MM 来源： XX" 段
          - body: <div class="contentbox"> 内的 <p> 元素列表
                 - 跳过第一段 (通常是 "在东方财富看资讯行情..." 推广)
                 - 终止于遇到 "文章来源" / "责任编辑" / "郑重声明" / "网友评论" 任一关键词
                 - 各 <p>.innerText 用 \n\n 拼接
      - default: 用通用逻辑 (find <article>, fallback to <main>, fallback to <div class=content>)
   e. clean: 移除 <script>/<style>/<nav>/<aside>/<header>/<footer>, normalize whitespace
   f. extract metadata: title / publish_date / author
4. return NewsContent(...)
```

## 4. Capability 注册

### `DataCapability` 新增 flag

```python
class DataCapability(Flag):
    # ... 现有 flags ...
    NEWS_SEARCH = auto()  # 新闻搜索（关键词 → 列表）
    # 不新增 NEWS_CONTENT flag —— content 走统一工具类,不走 fetcher 体系
```

### `CAPABILITY_TO_METHOD` 新增映射

```python
CAPABILITY_TO_METHOD: dict[DataCapability, str] = {
    # ... 现有映射 ...
    DataCapability.NEWS_SEARCH: "search_news",
}
```

`_NO_FETCHER_METHOD` 不变（content 不注册 capability）。

### `EastmoneyFetcher` 修改

```python
class EastmoneyFetcher(BaseFetcher):
    # priority 不变 (P6)
    supported_markets: set[str] = {"csi"}
    supported_data_types = (
        DataCapability.DRAGON_TIGER
        | DataCapability.MARGIN_TRADING
        | DataCapability.BLOCK_TRADE
        | DataCapability.HOLDER_NUM
        | DataCapability.DIVIDEND
        | DataCapability.FUND_FLOW
        | DataCapability.RESEARCH_REPORT
        | DataCapability.NEWS_SEARCH   # NEW
    )

    def search_news(
        self,
        q: str,
        from_date: str | None = None,
        to_date: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """东方财富新闻搜索

        上游: https://search-api-web.eastmoney.com/search/jsonp
        返回: list of NewsItem dict, 参见 §6 schema。

        实现要点 (基于 2026-06-16 playwright 实测):
        - 用 requests.get(URL, params={"cb": "jQuery_cb", "param": json.dumps(inner)})
        - inner 见下面"API 详情"
        - 响应是 JSONP: 剥掉 jQuery_cb(...) 包装, json.loads 括号内
        - strip title/content 里的 <em> 标签
        - publish_date 从 "YYYY-MM-DD HH:MM:SS" 取前 10 字符
        - from_date / to_date 是客户端 post-filter, 只在返回的 limit 条上过滤
        - HTTP 非 200 / JSONP parse fail / code != 0 / 缺关键字段 → raise DataFetchError
        """
        # ... 见下"API 详情"
```

**API 详情 (基于实测响应结构)**:

```python
# 上游 endpoint
URL = "https://search-api-web.eastmoney.com/search/jsonp"

# Query 参数
params = {
    "cb": "jQuery_news_search",          # 任意唯一字符串, 剥括号用
    "param": json.dumps({
        "uid": "",
        "keyword": q,                     # 搜索词 (支持股票代码 / 中文 / 自由文本)
        "type": ["cmsArticleWebOld"],      # 资讯类
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
                "postTag": "</em>"
            }
        }
    }, ensure_ascii=False)
}

# Headers (实测无需 cookie)
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://so.eastmoney.com/news/s",
}
```

**实测响应**:
```json
{
  "code": 0,
  "hitsTotal": 122,
  "msg": "OK",
  "result": {
    "cmsArticleWebOld": [
      {
        "date": "2026-06-09 16:36:00",
        "code": "202606093765150130",
        "title": "白酒概念下跌1.1<em>0</em>%, ...",
        "content": "2.67 0.68 -673.56 600300 维维股份 ...",
        "mediaName": "证券时报网",
        "url": "http://finance.eastmoney.com/a/202606093765150130.html",
        "image": ""
      }
    ]
  },
  "searchId": "..."
}
```

**输出 dict schema (post-normalize)**:
```python
{
    "title": "白酒概念下跌1.10%, ...",        # 已 strip <em>
    "url": "http://finance.eastmoney.com/a/...",
    "source_domain": "finance.eastmoney.com",  # 从 url 解析
    "publish_date": "2026-06-09",                # YYYY-MM-DD
    "snippet": "...",                              # content 已 strip <em>
    "media_name": "证券时报网",
}
```

**重要**：扩展现有 `EastmoneyFetcher`，**不**新建 `EastmoneyNewsFetcher` 类。理由：现有 fetcher 已经持有 User-Agent / cookie / rate-limit 处理的合理基线，分裂两个类只会重复基础设施。

## 5. Manager 新方法

```python
# data_provider/manager.py

def search_news(
    self,
    q: str,
    from_date: str | None = None,
    to_date: str | None = None,
    limit: int = 20,
) -> tuple[list[dict], str]:
    """新闻搜索（按 NEWS_SEARCH capability 路由 + 优先级 failover）。

    Returns:
        Tuple of (list_of_NewsItem, fetcher_name)
    """
    return self._with_failover(
        DataCapability.NEWS_SEARCH, "csi", f"news search q={q}",
        lambda f: f.search_news(q, from_date, to_date, limit),
        return_source=True,
    )
```

## 6. API 契约

### Endpoint 1: `GET /news/search`

**Query 参数**：
| 参数 | 类型 | 必传 | 默认 | 说明 |
|---|---|---|---|---|
| `q` | string | ✅ | — | 搜索词（股票代码 / 主题 / 自由文本，max 200 chars） |
| `from` | string (YYYY-MM-DD) | ❌ | — | 起始日期 |
| `to` | string (YYYY-MM-DD) | ❌ | — | 结束日期 |
| `limit` | int | ❌ | 20 | 结果数上限，1-100。v1 单次返回不超过 `limit` 条;分页不在 v1 范围 |

**Response 200**:
```json
{
  "data": [
    {
      "title": "贵州茅台发布前三季度业绩公告",
      "url": "https://finance.eastmoney.com/news/1234.html",
      "source_domain": "eastmoney.com",
      "publish_date": "2025-01-15",
      "snippet": "公司前三季度实现营业收入1234亿元...",
      "stock_codes": ["600519"]
    }
  ],
  "total": 156,
  "limit": 20,
  "query": "贵州茅台",
  "source": "EastmoneyFetcher"
}
```

**错误码**：
- 400: `q` 缺失 / 过长 / `from > to` / `limit` 越界
- 502: 所有 fetcher fail（DataFetchError 复用）

### Endpoint 2: `GET /news/content`

**Query 参数**：
| 参数 | 类型 | 必传 | 说明 |
|---|---|---|---|
| `url` | string (URL-encoded) | ✅ | 要抓取的新闻详情页 URL，必须 http(s) 协议 |

**Response 200**:
```json
{
  "url": "https://finance.eastmoney.com/news/1234.html",
  "title": "贵州茅台发布前三季度业绩公告",
  "body": "公司前三季度实现营业收入1234亿元,同比增长...",
  "publish_date": "2025-01-15",
  "author": "财经网",
  "source_domain": "eastmoney.com",
  "extractor": "default",
  "extracted_at": "2026-06-16T10:30:00Z",
  "byte_size": 1234
}
```

**错误码**：
- 400: `url` 缺失 / 非 http(s) / 指向内网 (SSRF)
- 502: 上游 HTTP 非 200 / fetch 超时
- 422: HTML 解析后 body < 100 字节（无法识别主体）

### `@endpoint_meta` 标注

```python
@router.get("/news/search", ...)
@endpoint_meta(
    summary="新闻搜索（关键词 / 股票代码 / 主题）",
    markets=["csi"],
    capabilities=[DataCapability.NEWS_SEARCH],
)
async def search_news_endpoint(...): ...

@router.get("/news/content", ...)
@endpoint_meta(
    summary="新闻正文提取（给定 URL 抓取详情页）",
    markets=["global"],   # content 不限市场
    capabilities=[],       # 故意空,不是 routed capability
)
async def get_news_content_endpoint(...): ...
```

## 7. 缓存策略

复用 `api/cache.py` 现有 `TTLCache`：

| 端点 | Cache key | TTL | 备注 |
|---|---|---|---|
| `/news/search` | `("news", "search", q, from_, to_, limit)` → sha256 hex prefix | 300s (5min) | 新闻实时性中等,5min 缓存合理 |
| `/news/content` | `("news", "content", sha256(url))` → sha256 hex prefix | 3600s (1h) | URL hash 后存,避免 URL 注入 key |

**URL hash 化**：原始 URL 可能含特殊字符（`?&=%`），直接做 cache key 既不优雅也有注入风险，统一先 sha256 再用前 16 字节 hex。

## 8. 错误处理

### Search 端

| 场景 | HTTP | 响应 |
|---|---|---|
| 缺少 `q` | 400 | `{"detail": "q is required"}` |
| `q` 长度 > 200 | 400 | `{"detail": "q too long (max 200 chars)"}` |
| `from > to` | 400 | `{"detail": "from must be <= to"}` |
| `limit` 越界 (1-100) | 400 | `{"detail": "limit must be 1..100"}` |
| 所有 fetcher fail | 502 | `{"detail": "All fetchers failed for news search: ..."}` |
| 单条记录解析失败 | 200 | 跳过该条,继续解析其他 |

### Content 端

| 场景 | HTTP | 响应 |
|---|---|---|
| 缺少 `url` | 400 | `{"detail": "url is required"}` |
| `url` 非 http(s) | 400 | `{"detail": "url must be http or https"}` |
| **SSRF 防护** | 400 | `{"detail": "url points to internal network"}` |
| fetch 超时 (>15s) | 504 | `{"detail": "fetch timeout for {url}"}` |
| HTTP 非 200 | 502 | `{"detail": "upstream returned {status} for {url}"}` |
| 找不到主体(清洗后 < 100 字节) | 422 | `{"detail": "could not extract main content"}` |

**SSRF 防护实现要点**（必须）：
- URL 解析后**重新解析 IP**（防止 DNS rebinding）：
  - 拒绝 `127.0.0.0/8`, `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `0.0.0.0`, `::1`, `fc00::/7`
  - 拒绝 `localhost`, `0.0.0.0`
- 拒绝 `file://`, `gopher://`, `ftp://` 等非 http(s) 协议
- 接受 `https://public-domain.com` 的请求,记录解析后的 IP 到日志(便于审计)

**为什么需要 SSRF 防护**：content 端点接受任意 URL,这是把"任意 URL 抓取"暴露为 API。AI agent 调用时如果误传 `http://10.0.0.1/admin` 就会扫描内网。这是硬性要求。

## 9. `NewsContentExtractor` 实现要点

**位置**：`stock_data/data_provider/utils/news_extractor.py`

```python
class NewsContentExtractor:
    """给定 URL 抓取并提取新闻正文。
    
    默认 handler 处理通用网页（HTTP GET + BeautifulSoup 找 <article> / <div class=content>）。
    domain 特定 handler 在 _domain_handlers 注册,用于 source-specific 提取逻辑
    （例如东方财富部分文章需要走 AJAX 接口拿正文 HTML,而不是详情页）。
    """

    _domain_handlers: dict[str, Callable[[str], NewsContent]] = {}  # 未来加 source-specific 走这里

    @classmethod
    def register_domain_handler(cls, domain: str, handler: Callable[[str], NewsContent]) -> None:
        cls._domain_handlers[domain] = handler

    @classmethod
    def extract(cls, url: str) -> NewsContent:
        # 1. SSRF check
        # 2. domain = urlparse(url).netloc, strip leading "www."
        # 3. handler = _domain_handlers.get(domain) or _default_handler
        # 4. return handler(url)
```

**默认 handler 流程**：
1. `requests.get(url, headers=UA, timeout=15, allow_redirects=True)`
2. **二次 SSRF check**：`socket.gethostbyname` 解析最终 URL 的 host，拒绝内网 IP
3. BeautifulSoup parse HTML
4. 找主体容器（按优先级）：
   - `<article>`
   - `<div class="content">` / `<div id="content">` / `<div class="article-content">`
   - `<main>`
   - 兜底：返回整页 `body.get_text()` 但 `extractor="default_loose"`
5. 清洗：移除 `<script>`, `<style>`, `<nav>`, `<aside>`, `<header>`, `<footer>`, `<iframe>`
6. 提取元数据：title（`<title>` 或 `<meta property="og:title">`）, publish_date（`<meta name="article:published_time">` 或猜测）, author（`<meta name="author">`）

**东方财富 domain handler**（v1 必装 — 实测 finance.eastmoney.com 的默认 handler 误伤严重）:

注册到 `NewsContentExtractor.register_domain_handler("finance.eastmoney.com", em_handler)` 以及 `stock.eastmoney.com`:

```python
def em_handler(url: str) -> NewsContent:
    """finance.eastmoney.com / stock.eastmoney.com 详情页正文提取

    实测 HTML 结构 (2026-06-16 playwright 验证):
    - <div class="topbox">  第一行是 title, 第二行是 "YYYY年MM月DD日 HH:MM 来源： XX"
    - <div class="contentbox">  内含 <p> 列表, 真实正文在第 2-N 段
    - 第一段通常是广告 "在东方财富看资讯行情..."
    - 终止标志: "文章来源" / "责任编辑" / "郑重声明" / "网友评论"
    """
    html = requests.get(url, headers=UA, timeout=15).text
    soup = BeautifulSoup(html, "html.parser")

    # 元数据
    topbox = soup.select_one("div.topbox")
    title = None
    publish_date = None
    source_name = None
    if topbox:
        lines = [l.strip() for l in topbox.get_text("\n").split("\n") if l.strip()]
        if lines:
            title = lines[0]
        # 找 "2026年06月15日 11:32 来源： 中新经纬" 模式
        for line in lines[1:]:
            m = re.match(r"(\d{4})年(\d{1,2})月(\d{1,2})日\s+(\d{1,2}:\d{2})\s*来源[:：]\s*(.*)", line)
            if m:
                y, mo, d, hm, src = m.groups()
                publish_date = f"{y}-{int(mo):02d}-{int(d):02d}"
                source_name = src.strip()
                break

    # 正文
    contentbox = soup.select_one("div.contentbox")
    body_paras = []
    if contentbox:
        for p in contentbox.select("p"):
            text = p.get_text().strip()
            if not text:
                continue
            # 跳过广告首段
            if "看资讯行情" in text or "选东方财富证券" in text:
                continue
            # 终止条件
            if any(kw in text for kw in ["文章来源", "责任编辑", "郑重声明", "网友评论"]):
                break
            body_paras.append(text)

    body = "\n\n".join(body_paras)
    return NewsContent(
        url=url,
        title=title,
        body=body,
        publish_date=publish_date,
        author=source_name,
        source_domain="finance.eastmoney.com",
        extractor="eastmoney_v1",
    )
```

## 10. 测试

### 单元测试

1. **`tests/test_news_capability.py`** — capability 注册
   - `NEWS_SEARCH` 在 `DataCapability` enum
   - `CAPABILITY_TO_METHOD[NEWS_SEARCH] == "search_news"`
   - `tests/test_capability_method_map.py` 不挂
   - `EastmoneyFetcher.supported_data_types` 包含 `NEWS_SEARCH`（与其他 capability 共存）

2. **`tests/test_eastmoney_search_news.py`** — fetcher 行为
   - mock `requests.get` 模拟 JSONP 响应 → 解析出 NewsItem 列表
   - `<em>` 高亮标签被 strip
   - `date` 字段 "YYYY-MM-DD HH:MM:SS" 截取为 "YYYY-MM-DD"
   - 缺关键字段 (`date` / `url` / `title`) 的 record 被跳过
   - `from_date` / `to_date` post-filter 生效
   - HTTP 非 200 / JSONP parse fail / `code != 0` → raise `DataFetchError`
   - 验证请求 URL 包含 `cb=...` 和 `param=<urlencoded json>`, `param.keyword == q`, `param.param.cmsArticleWebOld.pageSize == limit`

3. **`tests/test_news_content_extractor.py`** — 提取器
   - 默认 handler：`<article>` 结构 → 提取 body
   - 默认 handler：`<div class="content">` 结构 → 提取 body
   - `register_domain_handler` 注册后, 该域名 URL 走自定义 handler
   - **finance.eastmoney.com handler**: 用 fixture HTML 模拟 `.topbox` + `.contentbox` 结构
     - title 从 `.topbox` 第一行取
     - publish_date 从 "2026年06月15日 11:32 来源： 中新经纬" 解析为 "2026-06-15"
     - body 跳过第一段广告 ("在东方财富看资讯行情"), 拼接到 "责任编辑" 终止
     - author = "中新经纬"

4. **`tests/test_news_content_ssrf.py`** — SSRF 防护
   - `http://localhost` / `http://127.0.0.1` / `http://10.0.0.1` / `http://192.168.1.1` 全部 400
   - `file:///etc/passwd` → 400
   - DNS 解析到内网 IP (mock `socket.gethostbyname`) → 400
   - `https://public-domain.com` 正常通过

5. **`tests/test_news_endpoints.py`** — API 集成
   - `GET /news/search?q=...` 200, 返回符合 schema 的 JSON
   - `GET /news/search` (无 q) → 400
   - `GET /news/search?limit=999` → 400
   - `GET /news/content?url=...` 200
   - `GET /news/content` (无 url) → 400
   - `/news/search` 出现在 `/explorer/` manifest 的 sidebar
   - `/news/content` 出现在 manifest 但**不**进 fetcher drilldown（capability=[]）

### 反爬合规测试

- 确认 Eastmoney 的请求带 `User-Agent` + `Referer: https://so.eastmoney.com/`
- 复用 `BaseFetcher.random_sleep` 做合理间隔

### 端到端 smoke test

- 真实调一次 `GET /news/search?q=贵州茅台`,确认能拿到至少一条结果
- 测试环境网络不通时,设 `xfail`（复用 commit `0b6a247` 的 xfail 分类约定）

## 11. 风险与决策

| 风险 | 决策 |
|---|---|
| 东方财富 JSONP API 结构变动 | 解析层用 key 访问 + `KeyError` try/except, 单条失败跳过 |
| 东方财富反爬加强 (403 / 验证码) | v1 不对抗, 失败返回 502; 未来加代理/IP 池或转 Tavily |
| `from`/`to` 日期 post-filter 漏数据 | API 一次最多返回 `limit` 条, 长日期范围 + 小 `limit` 拿不全。响应里 `total=hitsTotal` 暴露总数, 但 v1 不实现多页抓取。文档里加 note: "若需全量历史,加大 limit" |
| Content 提取误判主体 | 提取后 < 100 字节抛 422, 不返回半截页面 |
| finance.eastmoney.com 改版 (class 名换) | handler 集中在一处, 失败 fallback 默认 handler (返回整页正文, `extractor="default_loose"`) |
| SSRF 防护被绕过 (DNS rebinding) | 解析 URL → 拿 IP → 拒绝内网 IP → 再 `requests.get` |
| 缓存中存敏感 URL | URL 先 sha256 再做 cache key, 原始 URL 不进 key |
| JSONP cb 名字冲突 (和其他模块都用 jQuery) | 用 `f"jQuery_news_{os.getpid()}"` 加 pid 保证唯一 |
| finance.eastmoney.com 不是 https (实测 http) | endpoints 同时接受 http/https, 但 SSRF 检查不做协议限制 (只做 IP 限制) |

## 12. 未来扩展（非 v1 范围）

- **Tavily / MiniMax 接入**：新建 `TavilyFetcher` / `MiniMaxFetcher`,实现 `search_news()`,注册 `NEWS_SEARCH` capability,manager 自动加入 failover 链
- **新闻去重 / 聚合**：搜索结果按 url hash 去重, 多源合并
- **AI 总结**：在 content 基础上加 `summary` 字段, 调 LLM 总结
- **News content 持久化**：高频抓取的 URL 存到 SQLite, 减少重复抓取
- **定时任务**：定期拉特定主题 / 股票代码的新闻, 写入数据库
