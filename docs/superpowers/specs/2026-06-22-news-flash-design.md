# 全球财经快讯 (News Flash) API — 设计稿

- **日期**：2026-06-22
- **状态**：Approved (待用户审阅)
- **范围**：新增 `GET /news/flash` 端点，复用 `EastMoneyFetcher` 拉取东财"全球财经快讯"（7×24 实时快讯）

## 1. 背景与目标

东财"全球财经快讯"（`https://kuaixun.eastmoney.com/7_24.html`）是 7×24 实时滚动推送的全球财经新闻流，覆盖 A 股、港股、美股、宏观、商品等。上游 HTTP API 为 `https://np-weblist.eastmoney.com/comm/web/getFastNewsList`，无需鉴权。

需求：把这条新闻流暴露为本地 API，供 AI agent（OpenClaw 等）订阅。**与现有 `/news/search`（关键词搜索）语义不同** —— 这是 push 模式的实时流，不是 query 模式的历史回搜。

akshare 已有 `stock_info_global_em()` 实现（用户提供的参考），但字段名是中文（标题/摘要/发布时间/链接）。本设计统一用英文归一化字段，和 `NewsItem` 对齐。

## 2. 上游探针结论（实测）

| 项 | 值 |
|---|---|
| URL | `https://np-weblist.eastmoney.com/comm/web/getFastNewsList` |
| 鉴权 | 无 |
| 必填参数 | `client=web`, `biz=web_724`, `fastColumn=102`, `sortEnd=""`, `pageSize`, `req_trace` |
| 响应 code | `0` = 成功 |
| 响应顶层 | `{req_trace, code, message, data: {sortEnd, index, total, size, fastNewsList: [...]}}` |
| 上游 `pageSize` | **服务端硬 cap 200**：实测 `pageSize=500/1000/2000` 都只返回 200 条 |
| `total` 字段 | 上游不填（始终为空），用 `data.size` 代替 |
| `hasMore` 字段 | 上游不填（始终为空），单次拉满 200 |

**item 字段**（实测）：`summary, code, titleColor, realSort, showTime, title, share, pinglun_Num, stockList, image`

## 3. API 设计

### 3.1 端点

```
GET /news/flash?limit=50
```

- 挂在 `news_router`（root，无 `/api/v1` 前缀）—— 和 `/news/search`、`/news/content` 一致；保持 OpenClaw 兼容性约定。
- 标签 `news`（同 news_router）。
- `markets=["csi"]`：仅用于能力路由（与 `search_news` 一致），返回内容不限于 csi 市场。

### 3.2 参数

| 参数 | 类型 | 范围 | 默认 | 说明 |
|---|---|---|---|---|
| `limit` | int | 1..200 | 50 | 客户端期望条数；服务端取 `min(limit, 200)` 真正请求上游 |

为什么 max=200：上游硬 cap，>200 没意义；min=1 防止空请求。

### 3.3 响应模型

```python
class FlashNewsItem(BaseModel):
    title: str           # 标题（原文，不 strip <em> —— 快讯无高亮）
    url: str             # "https://finance.eastmoney.com/a/{code}.html"
    source_domain: str   # 固定 "finance.eastmoney.com"
    publish_time: str    # "YYYY-MM-DD HH:MM:SS"（原始，不切到 date 或 ISO）
    snippet: str         # 摘要

class FlashNewsResponse(BaseModel):
    data: list[FlashNewsItem]
    total: int           # 实际返回条数（= data.size / len(fastNewsList)）
    limit: int           # 用户请求的 limit
    source: str          # fetcher 名（"eastmoney"）
```

### 3.4 字段映射

| 上游字段 | API 字段 | 说明 |
|---|---|---|
| `title` | `title` | 原文 |
| `summary` | `snippet` | 改名以和 `NewsItem` 一致 |
| `showTime` | `publish_time` | 保持原始字符串 |
| `code` | `url` | 重构为 `https://finance.eastmoney.com/a/{code}.html`（akshare 验证过） |
| 隐式 | `source_domain` | 固定 `"finance.eastmoney.com"` |
| `stockList` | (不暴露) | 关联股票列表；本期 YAGNI |
| `image` / `titleColor` / `realSort` / `share` / `pinglun_Num` | (不暴露) | UI 无关 |

**不暴露 `stockList` 的理由**：格式是 `['150.011668', '1.603529']`（疑似 code + pct），未官方确认。后续如要支持，新增 `related_stocks: list[str]` 字段即可，向后兼容。

## 4. 数据流

```
GET /news/flash?limit=50
   ↓
news_router.get_flash_news(limit)
   ├─ is_cache_enabled() && key in _news_flash_cache → return cached
   ↓
manager.get_flash_news(limit)
   └─ _with_failover(NEWS_FLASH, "csi", op_label, _fetch, return_source=True)
       └─ EastMoneyFetcher.fetch_flash_news(limit)
           ├─ _session.get(FLASH_URL, params=..., headers=..., timeout=15)
           ├─ 校验 resp.code == 0
           ├─ 校验 data.fastNewsList 存在
           ├─ 归一化每条 item → dict
           └─ return list[dict]
   ↓
build FlashNewsResponse
   ↓
cache_store(_news_flash_cache, key, response) if is_cache_enabled()
return response
```

## 5. 错误处理

| 场景 | 行为 |
|---|---|
| `limit < 1` 或 `> 200` | FastAPI 路由层 400（`Query(ge=1, le=200)`） |
| 网络异常 / 非 200 HTTP | `fetch_flash_news` 包成 `DataFetchError` → manager failover → 只有 1 个 fetcher，raise → 路由层 502 |
| upstream `code != 0` | `fetch_flash_news` 抛 `DataFetchError` → 502 |
| `fastNewsList` 缺失 / 为 null | 返回 `[]`（不是错误） |
| `ENABLE_API_CACHE=false` | 跳过 cache 读写（和现有端点一致） |
| upstream 0 条但 HTTP 200 | 返回 `data=[]`, `total=0`, `source="eastmoney"`（200 OK） |

## 6. 缓存

| 项 | 值 |
|---|---|
| TTL | `CACHE_TTL_NEWS_FLASH` env，默认 **60s** |
| Cache key | `("news_flash", limit)` |
| Cache instance | `_news_flash_cache: TTLCache(maxsize=64, ttl=60)` |
| `ENABLE_API_CACHE=false` | gate 跳过 |

为什么 60s：快讯时效性强；`/news/search` 300s 是历史回搜可缓存更久；实时推送 60s 折中（用户能 1 分钟看到新内容；上游不会被打爆）。

## 7. 文件改动清单

| # | 文件 | 改动 |
|---|---|---|
| 1 | `stock_data/data_provider/base.py` | 新增 `DataCapability.NEWS_FLASH` flag；`CAPABILITY_TO_METHOD[NEWS_FLASH] = "fetch_flash_news"` |
| 2 | `stock_data/data_provider/fetchers/eastmoney_fetcher.py` | `supported_data_types` 加 `NEWS_FLASH`（保留 `NEWS_SEARCH`）；新增 `FLASH_NEWS_URL` 常量 + `fetch_flash_news(limit)` 方法；复用现有 `__init__` 的 `self._session`（chrome120） |
| 3 | `stock_data/data_provider/manager.py` | 新增 `get_flash_news(limit)`，走 `_with_failover(NEWS_FLASH, "csi", ...)` |
| 4 | `stock_data/api/schemas.py` | 新增 `FlashNewsItem`、`FlashNewsResponse` |
| 5 | `stock_data/api/cache.py` | 新增 `_TTL_NEWS_FLASH` 常量、`_news_flash_cache` 实例、`get_news_flash_cache()` getter、`make_news_flash_cache_key(limit)` |
| 6 | `stock_data/api/routes.py` | 在 `news_router` 加 `GET /news/flash?limit=...`，用 `@endpoint_meta` 标注 `summary` / `markets=["csi"]` / `capabilities=["NEWS_FLASH"]`；用 `cached_endpoint` 包装 |
| 7 | `stock_data/CLAUDE.md` | (文档同步) EastMoneyFetcher capability 表格加 `NEWS_FLASH`；capability-routing 表格加 `get_flash_news → NEWS_FLASH` |

### 关键实现细节

- `EastMoneyFetcher.fetch_flash_news(limit)` 复用 `self._session`（已配 chrome120 impersonation），不新建 `requests.Session`。
- Headers：`User-Agent=UA, Referer=https://kuaixun.eastmoney.com/`（快讯页面的 referer）。
- Timeout：15s（和 search_news 一致）。
- `pageSize` 参数：`min(limit, 200)` —— 客户端传 300 时不会触发上游封顶，只是浪费一次大请求；FastAPI 的 `Query(le=200)` 在路由层就拦掉了 300。

## 8. 测试计划（仅任务相关，不全量）

| 测试文件 | 覆盖点 |
|---|---|
| `tests/test_eastmoney_flash_news.py`（新） | (1) 字段映射正确性（fixture 上游响应 → `FlashNewsItem`）；(2) `limit=1/50/200` 都通过；(3) `limit=300` 路由层 400；(4) 上游 `code != 0` 抛 `DataFetchError`；(5) `fastNewsList` 缺失返回 `[]`；(6) 复用 `_session`（不新建裸 requests） |
| `tests/test_capability_method_map.py`（已有） | 新增 `NEWS_FLASH` 后自动通过 map 检查 |
| `tests/test_explorer_manifest_endpoint.py`（已有） | `/news/flash` 出现在 manifest、capability 标签 `NEWS_FLASH` |
| 追加到 `tests/test_manager*.py` | `get_flash_news` 走 `_with_failover(NEWS_FLASH, "csi", ...)`，mock fetcher 失败时 raise |

不跑全量 suite（参见 `subagent-test-scope` 经验）。

## 9. 不在本期范围（YAGNI）

- 关联股票列表（`stockList`）解析
- 按股票代码 / 关键词过滤
- WebSocket / SSE 推送
- 多 provider failover（只有东财一家有 7x24 快讯，目前没必要）
- 历史快讯持久化（快讯即看即用）
- 把所有 news 路由从 root 迁到 `/api/v1/news/...` 的统一化重构（**单独的破坏性改动**，不在本任务范围）

## 10. 反模式自检

- [x] 不硬编码 fetcher 类（走 `_with_failover(NEWS_FLASH, ...)`）
- [x] 不把 K 线 / 分钟线算在 fetcher 里
- [x] 不在 fetcher 里写 indicator
- [x] 新增 capability flag 同时在 `CAPABILITY_TO_METHOD` 登记（`test_capability_method_map.py` 会自动覆盖）
- [x] `@endpoint_meta` 是 inner 装饰器（在 `@router.get` 内层）
- [x] 不引入新的内存缓存层级（继续用 `TTLCache` + `cached_endpoint` 模式）
- [x] 不持久化快讯到 SQLite（实时数据，不属于"历史可缓存"范畴）
- [x] 不动 news_router 已经挂好的 `/news/search` 和 `/news/content`
