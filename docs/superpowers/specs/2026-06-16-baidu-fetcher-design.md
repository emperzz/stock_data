# BaiduFetcher (news search) 设计文档

> 日期：2026-06-16
> 状态：待审
> 范围：新增 `BaiduFetcher`，注册 `NEWS_SEARCH` capability，作为 EastMoney news search 的备用源
> API 文档：https://cloud.baidu.com/doc/qianfan-api/s/Wmbq4z7e5

## 1. 目标与范围

为 `NEWS_SEARCH` capability 的 failover 链增加第二个源：**百度千帆 Web Search API**。

**动机**：
- 当前 news search 只接入了东方财富（`EastMoneyFetcher.search_news`，P6）。东方财富 JSONP 是非官方接口，存在反爬风险（403 / 验证码 / 接口结构变动）
- 百度千帆 Web Search 是百度智能云**官方付费 API**（每月免费 1500 次），稳定性更高，且有官方 SLA
- 新增 Baidu 作为 P7 **备用源**：东方财富成功时不消耗百度配额；东方财富失败时自动降级到百度

**v1 范围**：
- 新建 `BaiduFetcher`，实现 `search_news(q, from_date, to_date, limit) -> list[dict]`
- 注册 `NEWS_SEARCH` capability
- 默认优先级 **P7**（在 `EastMoneyFetcher` P6 之后），可通过 `BAIDU_PRIORITY` 环境变量覆盖
- 认证：从 `BAIDU_API_KEY` 环境变量读取 `bce-v3/...` 格式 token
- 仅使用 `requests.post` 一层（百度官方 API 带 Bearer token，无反爬，curl/playwright fallback 不必要）

**不在 v1 范围**：
- 不引入 curl subprocess 或 playwright 兜底（百度官方 API 走 Bearer token，requests 直连即可）
- 不分页（Baidu API 单次 top_k 最大 50，超出 50 的请求分页超出 v1 范围）
- 不缓存 Baidu 响应（已有 `api/cache.py` 的 TTL cache 在 `/news/search` 端点层覆盖）

## 2. 架构

```
                ┌──────────────────────────────────────────┐
                │   api/routes.py  (已存在的 endpoint)      │
                │   GET /news/search                        │
                └──────────────┬───────────────────────────┘
                               │
                               ▼
                ┌──────────────────────────────────────────┐
                │  DataFetcherManager.search_news           │
                │  (已存在的 _with_failover)                 │
                └──────────────┬───────────────────────────┘
                               │  capability=NEWS_SEARCH
                               │  market="csi"
                               │  按 priority 排序
              ┌────────────────┴────────────────┐
              ▼                                 ▼
   ┌──────────────────────────┐    ┌──────────────────────────┐
   │  EastMoneyFetcher (P6)   │    │  BaiduFetcher (P7) NEW   │
   │  search_news()           │    │  search_news()           │
   │  东方财富 JSONP          │    │  百度千帆官方 API         │
   │  (优先)                  │    │  (备用)                  │
   └──────────────────────────┘    └──────────────────────────┘
```

**复用现有边界**：
- `DataFetcherManager.search_news`（manager.py L301）已经按 `_with_failover` 路由所有 `NEWS_SEARCH` capability 的 fetcher，**零改动**
- `NewsItem` schema（schemas.py L731）已经定义了 `title / url / source_domain / publish_date / snippet / media_name`，**零改动**
- `/news/search` endpoint（routes.py L2072）已经支持 `source` 字段透传 fetcher 名，**零改动**
- `CAPABILITY_TO_METHOD[NEWS_SEARCH] = "search_news"`（base.py L102）已经存在，**零改动**

**关键决策**：
- **新建 `BaiduFetcher` 类**，而不是给 `EastMoneyFetcher` 加 if-branch：CLAUDE.md 明确规定"extend not spawn fetcher" 仅适用于**同一源**，跨源是允许的（项目已有 10 个 fetcher 类）。百度和东方财富是完全不同的上游，分开符合既有约定
- **不进 `NewsContentExtractor`**：content 端点抓的是 URL 详情页，绕过 search API，不在 BaiduFetcher 责任范围

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
_with_failover(capability=NEWS_SEARCH, market="csi", ...)
   │
   │  按 priority 排序: [EastMoneyFetcher(P6), BaiduFetcher(P7)]
   │
   ├─→ EastMoneyFetcher (P6)  优先
   │     │  HTTP GET https://search-api-web.eastmoney.com/search/jsonp
   │     │  → JSONP 响应 → strip <em> → post-filter [from_, to_]
   │     │  → [NewsItem, ...]
   │     │  (若 EastMoney raise DataFetchError，继续)
   │
   └─→ BaiduFetcher (P7)  备用
         │  POST https://qianfan.baidubce.com/v2/ai_search/web_search
         │  Header: Authorization: Bearer <BAIDU_API_KEY>
         │  Body: {messages:[{content:q,role:"user"}], search_source:"baidu_search_v2",
         │         resource_type_filter:[{type:"web",top_k:limit}],
         │         search_recency_filter:<derived from from_date>}
         │  → JSON 响应 → references[] → 标准化 NewsItem
         │
         ▼
         返回 (list_of_NewsItem, "BaiduFetcher")
```

### `search_recency_filter` 派生规则

Baidu API 支持 `search_recency_filter` 服务端日期过滤（比 EastMoney 强）：week / month / semiyear / year。

```python
def _derive_recency(from_date: str | None) -> str | None:
    """根据 from_date 推断搜索时效窗。None 时 Baidu 默认行为。"""
    if not from_date:
        return None
    days = (date.today() - date.fromisoformat(from_date)).days
    if days <= 7:   return "week"
    if days <= 30:  return "month"
    if days <= 180: return "semiyear"
    return "year"
```

`to_date` 仍走客户端 post-filter（Baidu API 不支持 to_date）。

### Limit 处理

- 上游 `top_k` 最大 50（百度硬性限制）
- 我们接受的 limit 范围 1..100（与 EastMoney 一致）
- **截断策略**：limit > 50 时取 50（避免 Baidu 返回不足）。当 `search_recency_filter` 服务端过滤生效时，结果数可能少于 limit — 这与 EastMoney 行为一致
- **不抛错**：Baidu 不支持 limit > 100 的硬性约束，但内部截断到 50，避免上层 API 行为不一致

## 4. `BaiduFetcher` 类定义

### 位置和结构

`stock_data/data_provider/fetchers/baidu_fetcher.py`（与 `eastmoney_fetcher.py` 同级）。

```python
class BaiduFetcher(BaseFetcher):
    """Baidu Qianfan Web Search API fetcher — news search only."""

    name = "BaiduFetcher"
    priority = int(os.getenv("BAIDU_PRIORITY", "7"))
    supported_markets: set[str] = {"csi"}
    supported_data_types = DataCapability.NEWS_SEARCH

    # API endpoint + auth
    _WEB_SEARCH_URL = "https://qianfan.baidubce.com/v2/ai_search/web_search"
    _API_KEY_ENV = "BAIDU_API_KEY"

    # Constants
    _BAIDU_MAX_TOP_K = 50  # 上游 top_k 硬性上限
    _MAX_Q_LEN = 200        # 与 EastMoney 一致

    def is_available(self) -> bool:
        return bool(os.getenv(self._API_KEY_ENV, "").strip())

    def unavailable_reason(self) -> str | None:
        """当 is_available() 返回 False 时被 explorer 调用, 给出具体缺失原因。"""
        if self.is_available():
            return None
        return f"BaiduFetcher unavailable: {self._API_KEY_ENV} env var is empty"

    # _fetch_raw_data / _normalize_data: 与 EastMoneyFetcher 相同, raise DataFetchError
    def _fetch_raw_data(self, stock_code, start_date, end_date, frequency="d", adjust=None):
        raise DataFetchError("BaiduFetcher does not support historical K-line data")

    def _normalize_data(self, df, stock_code):
        raise DataFetchError("BaiduFetcher does not support historical K-line data")

    def search_news(
        self,
        q: str,
        from_date: str | None = None,
        to_date: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """调用百度千帆 Web Search API, 返回标准化 NewsItem list.

        Raises DataFetchError on upstream failure / network error / 非 2xx / 缺关键字段.
        """
        # 1. Validate input (与 EastMoney 一致)
        # 2. _request()  →  list[dict] (references 数组的原始元素)
        # 3. _normalize_news_item() per record, KeyError/TypeError → skip
        # 4. Post-filter on from_date / to_date
        # 5. return list[dict] (每个 dict 是 NewsItem schema)
```

### API 详情（基于 2026-06-16 playwright 验证）

```python
URL = "https://qianfan.baidubce.com/v2/ai_search/web_search"

headers = {
    "Authorization": f"Bearer {os.environ['BAIDU_API_KEY']}",
    "Content-Type": "application/json",
}

body = {
    "messages": [
        {"content": q, "role": "user"},
    ],
    "search_source": "baidu_search_v2",          # 固定值
    "resource_type_filter": [
        {"type": "web", "top_k": min(limit, _BAIDU_MAX_TOP_K)},
    ],
    # 仅当 from_date 提供时附带 (由 _derive_recency 派生)
    "search_recency_filter": _derive_recency(from_date),  # "week" | "month" | "semiyear" | "year"
}

resp = requests.post(URL, headers=headers, json=body, timeout=15)
```

### 响应结构（实测 2026-06-16）

```json
{
  "request_id": "ca749cb1-26db-4ff6-9735-f7b472d59003",
  "references": [
    {
      "id": 1,
      "title": "【河北天气】河北天气预报...",
      "url": "https://www.weather.com.cn/html/weather/101031600.shtml",
      "content": "河北天气预报, 及时准确发布中央气象台天气信息...",
      "date": "2025-04-27 18:02:00",
      "type": "web",
      "web_anchor": "【河北天气】河北天气预报...",
      "image": null,
      "icon": null,
      "video": null
    }
  ]
}
```

### 字段映射

| Baidu response | NewsItem 字段 | 备注 |
|---|---|---|
| `references[i].title` | `title` | 已 strip 任何  /  控制字符 (百度响应中的真实案例) |
| `references[i].url` | `url` | 直接透传 |
| `urlparse(url).netloc` | `source_domain` | 与 EastMoney 一致 |
| `references[i].date[:10]` | `publish_date` | "YYYY-MM-DD HH:MM:SS" → "YYYY-MM-DD" |
| `references[i].content` | `snippet` | 直接透传 (Baidu 不返回 `<em>` 标记, 无需 strip) |
| `urlparse(url).netloc` | `media_name` | **Baidu 没有专门的 media_name 字段**。取 netloc 让 source_domain == media_name, 字段始终非空 (EastMoney 在没数据时是空字符串, 这是轻微不一致, 但能保证 schema 字段非空) |

**为什么 `media_name` 取 netloc 而不是空串**：
- EastMoney 用 `mediaName` 字段（媒体名如"证券时报网"），Baidu 不暴露
- 空 `media_name` 会让客户端 UI 显示空白，Baidu 路径下用户的体验更差
- 取 netloc 让客户端至少知道来源站点（如 `www.weather.com.cn`）
- 若未来 Baidu 升级 API 暴露媒体名，再升级映射

### 错误处理

| 场景 | 处理 |
|---|---|
| `BAIDU_API_KEY` 未设 | `is_available()` 返回 False, fetcher 不注册 (manager 自动跳过) |
| `q` 空或 len > 200 | `raise DataFetchError("...invalid q...")` |
| `limit` 非整数 / 越界 1..100 | `raise DataFetchError("...limit must be 1..100...")` |
| `requests.post` 网络异常 | `raise DataFetchError(f"...network error: {e}")` |
| HTTP 非 2xx | `raise DataFetchError(f"...HTTP {status_code}")` |
| 响应 JSON 解析失败 | `raise DataFetchError(f"...bad JSON: {e}")` |
| 响应 `code` 字段非 0（异常码） | `raise DataFetchError(f"...code={code} msg={msg}")` |
| 单条 record 缺 `title`/`url`/`date`/`content` | log warning + skip (不抛错, 让其他 record 通过) |

错误格式参考 EastMoney 已有模式，便于 manager 统一日志。

## 5. 注册流程

### `data_provider/__init__.py` 新增 export

```python
from .fetchers.baidu_fetcher import BaiduFetcher  # NEW
```

（位置在 `EastMoneyFetcher` 之后，按字母顺序排列）

### `data_provider/manager.py` `_register_default_fetchers` 新增

```python
from .fetchers.baidu_fetcher import BaiduFetcher  # NEW (与现有 imports 同 block)

fetcher_classes = [
    TushareFetcher,
    BaostockFetcher,
    MyquantFetcher,
    AkshareFetcher,
    YfinanceFetcher,
    ZhituFetcher,
    TencentFetcher,
    EastMoneyFetcher,
    BaiduFetcher,       # NEW (P7, 在 EastMoney 之后)
    ThsFetcher,
    CninfoFetcher,
]
```

### 环境变量

`.env.example` 新增：

```bash
# === Baidu Qianfan (Priority 7 for news search backup, requires API key) ===
# Get your API Key from: https://console.bce.baidu.com/qianfan/ais/console/apiKey
# Format: bce-v3/ALTAK-xxx/xxx
BAIDU_API_KEY=
# BAIDU_PRIORITY=7
```

`.env` 已经包含 `BAIDU_API_KEY = bce-v3/ALTAK-TcKAnXHZ29xSusZ9kk0Hb/...`，无需修改。

## 6. 测试

### `tests/test_baidu_search_news.py`（与 `test_eastmoney_search_news.py` 同结构）

**Happy path**:
- `test_returns_normalized_dicts`: mock POST 响应, 验证返回 list[dict] 包含 title/url/source_domain/publish_date/snippet/media_name
- `test_request_uses_bce_endpoint`: 验证调用 URL 是 `https://qianfan.baidubce.com/v2/ai_search/web_search`
- `test_bearer_auth_header`: 验证 `Authorization: Bearer <BAIDU_API_KEY>`
- `test_body_shape`: 验证 request body 包含 `messages[0].content == q`、`resource_type_filter[0].top_k == min(limit, 50)`、`search_source == "baidu_search_v2"`
- `test_recency_filter_derived`: 验证 from_date 不同时 `search_recency_filter` 取值正确 (week/month/semiyear/year/None)
- `test_no_recency_when_from_date_none`: 验证 `search_recency_filter` 不在 body 中
- `test_top_k_clamped_to_50`: limit=100 时 top_k=50

**Filters**:
- `test_from_date_post_filter`: from_date 过滤, 跳过 publish_date 更早的记录
- `test_to_date_post_filter`: to_date 过滤
- `test_date_range_post_filter`: from+to 同时过滤

**Errors**:
- `test_http_non_2xx_raises`: 401/500 → `DataFetchError`
- `test_baidu_api_code_nonzero_raises`: 响应 `code != 0` → `DataFetchError`
- `test_bad_json_raises`: 响应非 JSON → `DataFetchError`
- `test_q_too_long_raises`: len(q) > 200 → `DataFetchError`
- `test_limit_out_of_range_raises`: limit=0 / 101 → `DataFetchError`
- `test_limit_as_string_is_coerced`: limit="20" → 正常工作
- `test_limit_non_numeric_string_raises`: limit="abc" → `DataFetchError`
- `test_records_missing_critical_fields_are_skipped`: 缺 url/date/title 的 record 被跳过

**Availability**:
- `test_is_available_false_when_api_key_missing`: unset `BAIDU_API_KEY` → is_available 返回 False, fetcher 不被 manager 添加
- `test_unavailable_reason_mentions_env_var`: is_available=False 时, unavailable_reason() 提到 `BAIDU_API_KEY`

### Manager 集成测试

- `tests/test_manager_news_search.py` 现有测试无需修改（NEWS_SEARCH capability 列表里新增 BaiduFetcher 不影响 EastMoney 行为）
- 新增 `tests/test_news_failover_to_baidu.py`:
  - mock `EastMoneyFetcher.search_news` raise DataFetchError
  - mock `BaiduFetcher.search_news` 返回正常 list
  - 验证 manager 返回 Baidu 结果, `source == "BaiduFetcher"`

### 反爬合规测试（手工，不进 CI）

- 启动 server, 真实调一次 `GET /news/search?q=贵州茅台`
- 预期：EastMoney 优先返回，若 EastMoney 抛错则降级到 Baidu

## 7. 风险与决策

| 风险 | 决策 |
|---|---|
| 百度配额耗尽 | 每月免费 1500 次（按天发放），EastMoney 优先用，Baidu 仅在 EastMoney 失败时消耗。quota 耗尽时 BaiduFetcher.search_news 抛 `DataFetchError`，manager 抛 502，无静默失败 |
| 百度 API key 失效 / 过期 | `is_available()` 检测空 env var。运行时 key 失效（401）→ 抛 `DataFetchError`，被 manager 当作 fetcher 失败处理 |
| `references[i].content` 含 ``/`` 等控制字符 | normalize 时 strip（百度响应实测案例）；不影响 NewsItem schema |
| 百度响应 `date` 字段格式不一致 | 与 EastMoney 一致截取前 10 字符。空字符串 / 长度 < 10 的 record 直接 skip |
| 百度 API 结构变动 | 解析层用 key 访问 + try/except；records 数组用 `.get("references") or []` 容错；单条 record 失败 skip |
| 东方财富 + 百度同时失败 | manager `_with_failover` 抛 `DataFetchError` → endpoint 返回 502（既有行为，无变化） |
| curl / playwright 三级回退 | **不实现**：百度官方 API 不需要，EastMoney 路径上如有反爬再单独处理 |

## 8. 未来扩展（非 v1 范围）

- 智能搜索生成（`百度搜索 v2`）支持 `lite` edition → 加 `edition` 参数控制
- 视频/图片搜索（`resource_type_filter` 已支持）→ 加 `?media_type=` 参数
- 阿拉丁结构化信息（`type: "aladdin"`）→ 加 `?include_aladdin=true` 参数
- 新闻去重 / 聚合：按 url hash 去重, 多源合并
- 定时任务：定期拉特定主题 / 股票代码的新闻, 写入数据库

## 9. CLAUDE.md 更新

在 `stock_data/CLAUDE.md` 的 "Fetcher capability declarations" 表中新增一行：

```
| BaiduFetcher | `NEWS_SEARCH` |
```

在 CLAUDE.md "数据源优先级" 部分（CLAUDE.md L138 附近）的 Tencent/EastMoney/THS 之间插入：

```
### BaiduFetcher (Priority 7, news search backup, A股 only, Requires API Key)

**API**: `POST https://qianfan.baidubce.com/v2/ai_search/web_search`

**认证**: `Authorization: Bearer <API Key>` (从 `BAIDU_API_KEY` 环境变量读取)

**支持的 capability**: `NEWS_SEARCH` (仅 news search, 不支持 K线 / 行情)

**请求体**:
```json
{
  "messages": [{"content": "query", "role": "user"}],
  "search_source": "baidu_search_v2",
  "resource_type_filter": [{"type": "web", "top_k": 20}],
  "search_recency_filter": "year"
}
```

**响应字段**: `references[].{title, url, content, date, type, web_anchor}`

**费率**: 每月免费 1500 次（按天发放），超出按量计费

**Links**: https://cloud.baidu.com/doc/qianfan-api/s/Wmbq4z7e5
```

## 10. 不在范围内的事项（明确排除）

- ❌ 文档第三条提到的 `curl → playwright` 三级回退（Baidu 官方 API 不需要）
- ❌ 智能搜索生成（`百度搜索 v2` 的 `lite` edition）
- ❌ 视频 / 图片 / 阿拉丁搜索（`resource_type_filter` 其他 type）
- ❌ BaiduFetcher 的 `_fetch_raw_data` / `_normalize_data` 任何 K线实现（百度 Web Search API 完全没有 K线数据）
- ❌ 拆分/合并 `EastMoneyFetcher` 现有 `search_news`（CLAUDE.md 明确禁止同源分叉）
- ❌ 给 BaiduFetcher 增加任何 K线 / 行情 / 财报 / 公告 capability（v1 纯 news search）
