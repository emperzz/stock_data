# ThsFetcher 添加 NEWS_FLASH Capability — 设计稿

- **日期**: 2026-06-23
- **状态**: Approved (待用户审阅)
- **范围**: 给 `ThsFetcher` 增加 `fetch_flash_news` 方法和 `NEWS_FLASH` capability, 作为 `EastMoneyFetcher` 的 failover 备选。**不改 schema / route / manager / base.py**。
- **上游**: `https://news.10jqka.com.cn/tapp/news/push/stock`

## 1. 背景与目标

现有的 `/news/flash` 端点只挂 `EastMoneyFetcher` (priority=6)。当东财上游异常时, manager 没有第二条 `NEWS_FLASH` 链路可降级, 用户直接拿到 502。

同花顺 (THS) 有同质化的"全球财经直播"快讯流 (`https://news.10jqka.com.cn/realtimenews.html`), 上游 HTTP API 为 `https://news.10jqka.com.cn/tapp/news/push/stock`, 无鉴权。

**目标**: 在 `ThsFetcher` 上挂 `fetch_flash_news` 方法, 复用现有 `NEWS_FLASH` capability, 让 manager 自动按 priority 链 failover: EastMoney(P6) → ThsFetcher(P7)。

## 2. 上游探针结论 (实测 2026-06-23)

| 项 | 值 |
|---|---|
| URL | `https://news.10jqka.com.cn/tapp/news/push/stock` |
| Method | GET |
| 鉴权 | 无 |
| 必填参数 | `page=N` (1-based 页号), `tag=` (空=全部), `track=website` |
| 可选参数 | `tag=-21101` (重要) / `tag=21103` (A股) / `tag=21111` (异动) 等; 本期不暴露 |
| 响应 code | `200` = 成功 |
| 响应顶层 | `{code, msg, time, data: {list: [...], filter: [...], total: N}}` |
| **每页条数** | **服务端硬编码 20**, 所有变体参数 (`pageSize` / `limit` / `num` / `size` / `count` / `rows` / `numPerPage` / `psize`) 均无效, 一律返回 20 |
| `data.total` | feed 总条数 (如全部=12142, 重要=2562), 用于算 `totalPage = ceil(total/20)` |
| `data.filter` | 8 个分类 tab (全球/重要/A股/港股/美股/商品/基金/异动), 本期不用 |
| 分页 | 真实分页: page=1 和 page=2 互不重叠, 按 `rtime` 严格降序; page=999 返回空 list (code=200, 不报错) |

**item 字段** (实测): `id, seq, title, digest, url, appUrl, shareUrl, color, tag, tags[], ctime, rtime, source, picUrl, nature, stock[], field[], short, import, tagInfo[]`。

关键字段:
- `rtime` 是 10 位 Unix timestamp (如 `1782181568`), 需要格式化。
- `url` 上游已拼好 (如 `https://news.10jqka.com.cn/20260623/c677638595.shtml`), **直接用**。
- `digest` 是摘要, 映射到 `snippet`。

## 3. 设计决策

| 决策 | 选择 | 理由 |
|---|---|---|
| Capability 复用 | 用现有 `NEWS_FLASH` | EastMoney 已声明, 路由/manager 不变 |
| 方法名 | `fetch_flash_news(limit)` | 与 EastMoney 同名, 适配 manager 的 `lambda f: f.fetch_flash_news(limit)` |
| 分页策略 | fetcher 内部翻页到 `len >= limit` | 上游硬限 20/页, 用户传 limit 时内部 `ceil(limit/20)` 次请求 |
| limit 上限 | 200 (与 EastMoney 对齐) | 路由层 `Query(le=200)` 拦住, fetcher 二次防御 |
| 空页停止 | `data.list == []` 时立即停止翻页 | 翻到末页是空 list, 不抛错 |
| 时间格式 | `datetime.fromtimestamp(int(rtime)).strftime("%Y-%m-%d %H:%M:%S")` | 与用户参考代码一致, 失败时降级用原 rtime 字符串 |
| url 处理 | 直接用上游 `url` 字段 | 上游已拼好完整 URL, 不再合成 |
| source_domain | `"news.10jqka.com.cn"` | 与 upstream host 一致; schema 的 `source_domain: str` 字段接受任意值 |
| snippet | `digest` 字段 | 与用户参考代码一致 |
| tag 过滤 | **不做** (YAGNI) | 用户未要求; 后续可加 `tag` 参数 |
| 失败行为 | 抛 `DataFetchError` | 与 EastMoney 一致, manager 自动 failover |
| 空 list 行为 | 返回 `[]` (不抛错) | 与 EastMoney 一致, page=999 是合法空响应 |
| 单条坏数据 | skip + warn, 不抛错 | 与 EastMoney 的 `KeyError/TypeError` 处理一致 |
| User-Agent | Chrome 120 字符串 (复用 `THS_UA` 或新增) | 项目其他 fetcher 一律 Chrome 系 |
| Referer | `https://news.10jqka.com.cn/realtimenews.html` | 与用户参考代码中的 live page URL 一致 |

## 4. API 设计

**API 端点**: 不变, 仍是 `GET /news/flash?limit=...`。

**Fetcher 方法签名**:

```python
def fetch_flash_news(self, limit: int = 50) -> list[dict]:
    """Get THS 7x24 global financial flash news via paginated upstream calls.

    上游 URL: https://news.10jqka.com.cn/tapp/news/push/stock
    上游 pageSize 硬编码 20;fetcher 内部翻 ceil(limit/20) 页直到
    拿到 limit 条或上游返回空页。

    Returns:
        归一化后的 list[dict],每条形如:
        {title, url, source_domain, publish_time, snippet}
        当上游 list 缺失或为 null 时返回 []。

    Raises:
        DataFetchError: 网络异常 / HTTP 非 200 / 上游 code != 200 / limit 越界
    """
```

**响应 schema**: 不变, 仍用 `FlashNewsItem` / `FlashNewsResponse` (`schemas.py`)。

| FlashNewsItem 字段 | THS 来源 |
|---|---|
| `title` | `item["title"]` |
| `url` | `item["url"]` (上游已拼好) |
| `source_domain` | `"news.10jqka.com.cn"` |
| `publish_time` | `datetime.fromtimestamp(int(item["rtime"]))` → `"YYYY-MM-DD HH:MM:%S"` |
| `snippet` | `item["digest"]` |

## 5. 翻页算法

```python
PAGE_SIZE = 20  # 上游硬编码
MAX_PAGES = 10  # limit=200 / 20
MAX_LIMIT = 200  # 与 EastMoney 一致

def fetch_flash_news(self, limit: int = 50) -> list[dict]:
    limit = clamp(limit, 1, 200)  # 路由层也会拦, fetcher 二次防御
    page_size = PAGE_SIZE
    max_pages = math.ceil(limit / page_size)  # limit=200 → 10 页

    out: list[dict] = []
    for page in range(1, max_pages + 1):
        rows = self._fetch_one_page(page)
        if not rows:
            break  # 翻到末页 (page=999 等), 立即停
        out.extend(rows)
        if len(out) >= limit:
            break

    return out[:limit]  # 多拉的截断到 limit
```

`_fetch_one_page(page)`:
- `GET https://news.10jqka.com.cn/tapp/news/push/stock?page={page}&tag=&track=website`
- Headers: `User-Agent: Chrome/120.0.0.0`, `Referer: https://news.10jqka.com.cn/realtimenews.html`
- Timeout: 10s (和 ThsFetcher 其他方法一致)
- 校验 `resp.status_code == 200` 否则 raise
- 校验 `payload["code"] == 200` 否则 raise
- 解析 `payload["data"]["list"]` (缺失/null/[] 都返回 `[]`)
- 归一化每条: `title`, `url`, `source_domain="news.10jqka.com.cn"`, `publish_time` (格式化 rtime), `snippet=digest`
- 单条 `KeyError/TypeError/ValueError` 时 warn 并 skip

## 6. 改动文件清单

| # | 文件 | 改动 |
|---|---|---|
| 1 | `stock_data/data_provider/fetchers/ths_fetcher.py` | (1) `supported_data_types` 加 `DataCapability.NEWS_FLASH`; (2) 新增常量 `_FLASH_NEWS_URL`, `_FLASH_NEWS_PAGE_SIZE=20`, `_FLASH_NEWS_MAX_LIMIT=200`; (3) 新增 `fetch_flash_news(limit)` 方法; (4) 模块 docstring 加 `flash-news` 行 |
| 2 | `tests/fixtures/ths_flash_news.json` | 新增: 真实上游响应 (page=1, 2 条记录), 用于 happy path 测试 |
| 3 | `tests/test_ths_fetcher.py` | 新增 `TestFetchFlashNews` 类: (a) `_normalize_flash_item` 字段映射; (b) `fetch_flash_news(limit=10)` 单页 + take 10; (c) `limit=200` 翻 10 页; (d) `limit=0` 抛 `DataFetchError`; (e) 上游空 list 返回 `[]`; (f) 上游 `code != 200` 抛; (g) HTTP 500 抛; (h) 单条坏数据 skip |
| 4 | `tests/test_manager_flash_news.py` | 新增: (a) ThsFetcher + EastMoneyFetcher 都注册时, EastMoney 优先; (b) EastMoney 抛错时降级到 ThsFetcher; (c) ThsFetcher priority (7) < EastMoney (6) 在 _filter_by_capability 排序里 EastMoney 在前 |
| 5 | `CLAUDE.md` | (a) ThsFetcher capability 表格加 `NEWS_FLASH`; (b) fetcher capability declarations 表格加 ThsFetcher NEWS_FLASH; (c) capability-routing 表 `get_flash_news → NEWS_FLASH` 行注明 "EastMoney P6, ThsFetcher P7 fallback" |

**不改**:
- `base.py` (`CAPABILITY_TO_METHOD[NEWS_FLASH] = "fetch_flash_news"` 已存在)
- `manager.py` (`get_flash_news` 已走 `_with_failover(NEWS_FLASH, "csi", ...)`, 自动支持 ThsFetcher)
- `routes.py` (`/news/flash` route 已存在, 自动覆盖)
- `schemas.py` (`FlashNewsItem.source_domain: str = Field(default="finance.eastmoney.com", ...)` 接受任意值, fetcher 显式传 `"news.10jqka.com.cn"` 即可)
- `api/cache.py` (`_news_flash_cache` 已用 `("news_flash", limit)` 作 key, 不区分源)

## 7. 测试计划 (仅任务相关, 不跑全量)

| 测试文件 | 覆盖点 |
|---|---|
| `tests/test_ths_fetcher.py` (追加 `TestFetchFlashNews`) | 见 §6 #3 |
| `tests/test_manager_flash_news.py` (追加) | 见 §6 #4 |
| `tests/test_capability_method_map.py` (已有) | 自动通过 (ThsFetcher.supported_data_types 多了 NEWS_FLASH, 但 `fetch_flash_news` 方法名匹配 `CAPABILITY_TO_METHOD[NEWS_FLASH]`) |
| `tests/test_explorer_manifest_endpoint.py` (已有) | `/news/flash` 的 `fetchers[]` 数组多出 `ThsFetcher` 条目 (priority=7, signature=...) |

**不跑** `test_eastmoney_flash_news.py` (无改动) / `test_baidu_search_news.py` (无改动) 等。

## 8. 不在本期范围 (YAGNI)

- `tag` 参数 (按 重要/A股/异动 过滤): 用户未要求, schema 不动, 后续可加 `?tag=-21101` query param
- 关联股票列表 (`item["stockList"]`): THS 的 stock 字段格式未官方确认, 与 EastMoney 一律不暴露
- WebSocket / SSE 推送: 与 NEWS_FLASH 语义不符
- 持久化: 快讯即看即用, 不入 SQLite
- `appUrl` / `shareUrl` / `picUrl` / `color` / `import` 等附加字段: UI 无关, 与 EastMoney 对齐不暴露

## 9. 反模式自检 (CLAUDE.md)

- [x] **不硬编码 fetcher 类**: 走 `_with_failover(NEWS_FLASH, "csi", ...)`, ThsFetcher 自动接管
- [x] **不新建 fetcher 类**: 走 `extend-not-spawn-fetcher` memory, 给现有 ThsFetcher 加方法
- [x] **不加新 capability**: 复用 NEWS_FLASH, `base.py` 不动
- [x] **不改 schema / route / manager**: 完全复用现有
- [x] **fixture 来自真实上游**: 走 `fixture-must-match-real-upstream` memory, 用 2026-06-23 实测的 28KB 响应
- [x] **limit 用 `min`, 不是 `or`**: 走 `options.get(key, default)` 模式, 避免 `limit=0` 被吞
- [x] **不在 fetcher 里加缓存**: TTLCache 在 routes 层, fetcher 只管 fetch
- [x] **错误用 DataFetchError 包**: 与 EastMoney 一致, manager 自动 failover
- [x] **priority 排序**: ThsFetcher (7) < EastMoney (6) → EastMoney 仍排前面, THS 是 fallback
- [x] **测试以测试为准**: 走 `test-wins-spec` memory, 翻页算法用 TDD 写

## 10. 关键风险

| 风险 | 缓解 |
|---|---|
| 翻 10 页慢 (limit=200) | 路由层 TTL 60s 缓存, 用户重复刷只走 1 次; 串行翻页 ~5s 内完成 |
| 上游 page=N 翻越末页返回 `[]` 时, 我们已拿到足够, 但多发 1 次请求 | 检测到空 list 立即 break (见 §5) |
| ThsFetcher `_session` 不存在 (用裸 requests?) | 项目用 `requests.get` 即可 (ThsFetcher 没建 _session), 与 `get_hot_topics` / `get_north_flow` 一致 |
| 时间格式化 `fromtimestamp` 跨时区 | 10 位 Unix timestamp 与时区无关, `strftime` 用本地时区 (项目其他 fetcher 一致) |
| THS 反爬 | 第一次真请求可能 200, 短期内 100 次/小时级无忧 (参考 akshare 的同接口) |
