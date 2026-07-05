# ThsFetcher 接入个股新闻/个股公告（P7 备份）设计

> 日期: 2026-07-05
> 状态: 待用户审阅
> 范围: `ThsFetcher` 接入 `STOCK_NEWS` / `ANNOUNCEMENT` 两条 capability，作为现有 EastMoney 主链的 P7 备份；公告 schema 新增 `raw_url` 字段。
> 性质: **Fetcher 层 + schema 字段微调**。零 manager/route 路由层改动（failover 由 capability 路由自动生效），零 DB schema 变更。

---

## 1. 问题陈述

### 1.1 个股新闻依赖单源

`/stocks/{code}/news` 当前仅由 `EastMoneyFetcher`（`np-listapi.eastmoney.com/comm/web/getListInfo`，优先 P6）服务，**单点故障**：
- np-listapi 偶发 200 但 `code != 1`（实为业务错误），`EastMoneyFetcher.get_stock_news` 返回 `[]`（已见 logger.warning）。
- 单源限速让 listing 翻页受限。
- 没有真正第二份「按 stock_code 抓个股资讯」的备份。

### 1.2 个股公告虽双源，但 THS 字段更丰富

`/stocks/{code}/announcements` 现在由 EastMoney (`np-anotice-stock`，P6) + Cninfo (`cninfo.com.cn/new/hisAnnouncement/query`，P8) 服务。THS 同花顺的实际备份路径 **已经存在** 但未被利用：`basic.10jqka.com.cn/fuyao/info/company/v1/news` 与 `/basicapi/notice/pub` 是干净的 JSON 端点。

经 Playwright 在 `https://basic.10jqka.com.cn/.../news?code=300740&marketid=33` 抓到的 `/basicapi/notice/pub` 响应**额外带 `raw_url` 字段**（`http://static.cninfo.com.cn/finalpage/YYYY-MM-DD/...PDF`，巨潮原文 PDF 直链）。EastMoney / Cninfo 当前都不带这个字段。

### 1.3 ThsFetcher 已经在用 basic.10jqka.com.cn

`ThsFetcher.get_stock_boards`（`ths_fetcher.py:825-880`）已经在调用 `https://basic.10jqka.com.cn/fuyao/f10_stock_index/concept/v1/stock_concept_list`，同 `Referer` / 同 `_THS_MARKET_ID_MAP`。新增 STOCK_NEWS / ANNOUNCEMENT 接入**零新依赖、零新函数风格**，仅扩 `_check_ths_deps` 不动（这两个新方法是纯 HTTP，不需要 `py_mini_racer` / `bs4` / `demjson3` / `ths.js`）。

---

## 2. 目标与非目标

### 目标

1. **`STOCK_NEWS` 增加 THS 备份**：failover 链从 `EastMoney(P6)` 变成 `EastMoney(P6) → Ths(P7)`；下次 EastMoney 故障时 `manager.get_stock_news(code, limit)` 自动回退到 Ths。
2. **`ANNOUNCEMENT` 在 EastMoney 与 Cninfo 之间插入 THS 备份**：failover 链 `EastMoney(P6) → Ths(P7) → Cninfo(P8)`。
3. **公告 schema 新增 `raw_url: str = ""`**：把 THS 上游自然携带的巨潮 PDF 直链透出，向后兼容。
4. **响应 dict shape 严格对齐现有同 capability 的 fetcher**，让 `_with_failover` 在第一个 fetcher 失败时直接复用第二个的 list（无需 manager 再做转换）。
5. **测试覆盖**：默认 mock 路径覆盖「failover」、「CapabilityToMethod 完整性」、「normalize 字段完整性」；`live_network` 标记的真接口测试只跑最小 1-2 条用例以避免限速。

### 非目标

- ❌ **HK / US 股票支持**（THS `market=33|17` 是 CSI 专用） — 行为对齐现有 `get_stock_boards` 对北交所 4/8 的 skip。
- ❌ **分页参数暴露给 route**（THS 上游支持 `current=`/`page=`，但本次只拉第一页，与现有 `?limit=` 行为对齐）。
- ❌ **公告 `classify=` 分类过滤**（THS 上游支持 `全部/业绩/重大事项/股份变动/决议`；本次固定 `classify=all`，未来按需暴露为 query 参数）。
- ❌ **Manager / Route / Cache 层改动**（`get_stock_news` / `get_announcements` 路由自动纳入新 fetcher）。
- ❌ **重启时持久化 / import-time 副作用**（如同花顺其它纯 HTTP 方法，无 class-level 状态）。

---

## 3. 设计

### 3.1 新增 endpoint（ths_fetcher.py）

```python
THIS_NEWS_URL = "https://basic.10jqka.com.cn/fuyao/info/company/v1/news"
THIS_NOTICE_URL = "https://basic.10jqka.com.cn/basicapi/notice/pub"
THIS_BASIC_HEADERS = {
    "User-Agent": THS_UA,  # 复用模块顶部已定义的常量
    "Referer": "https://basic.10jqka.com.cn/astockpc/astockmain/index.html",
}
THIS_NEWS_PAGE_SIZE = 15    # 上游默认值；本次不下发，用现有 route ?limit
THIS_NOTICE_PAGE_SIZE = 15  # 上游默认值；本次不下发
```

`User-Agent` 用 `THS_UA`（已有常量）；`Referer` 与现有 `get_stock_boards` 同源，**统一使用 helper**，便于未来一次性改 UA pool。

### 3.2 在 ThsFetcher 类顶部更新 supported_data_types

```python
supported_data_types = (
    DataCapability.HOT_TOPICS
    | DataCapability.NORTH_FLOW
    | DataCapability.NEWS_FLASH
    | DataCapability.NEWS_SEARCH
    | DataCapability.STOCK_BOARD
    | DataCapability.STOCK_NEWS       # 新
    | DataCapability.ANNOUNCEMENT     # 新
)
```

### 3.3 `get_stock_news(stock_code, limit=20)` — 新方法

```python
def get_stock_news(self, stock_code: str, limit: int = 20) -> list[dict]:
    """THS 个股新闻 via basic.10jqka.com.cn/fuyao/info/company/v1/news.

    复用已有的 _THS_MARKET_ID_MAP 把 6 位代码映射成上游 market_id。
    返回 dict shape 严格对齐 EastMoneyFetcher.get_stock_news:
      {title, url, source_domain, publish_date, media_name}.

    返回 [] 时与 EastMoney 同语义（即不视为 fetcher 错误，
    manager failover 不会因为 [] 而跳过)。
    """
    code = normalize_stock_code(stock_code)
    market_id = _THS_MARKET_ID_MAP.get(code[:1])
    if not market_id:
        logger.warning(f"[ThsFetcher] get_stock_news: no market_id for {code!r}")
        return []
    try:
        n = max(1, min(int(limit), 100))
    except (TypeError, ValueError):
        n = 20
    try:
        payload = json_get(
            THIS_NEWS_URL,
            params={
                "type": "stock",
                "code": code,
                "market": market_id,
                "current": 1,
                "limit": n,
            },
            headers=THIS_BASIC_HEADERS,
            timeout=10,
        )
    except DataFetchError as e:
        raise
    if not isinstance(payload, dict) or payload.get("status_code") != 0:
        logger.warning(
            f"[ThsFetcher] get_stock_news({code}) upstream "
            f"status_code={payload.get('status_code') if isinstance(payload, dict) else 'N/A'} "
            f"msg={payload.get('status_msg') if isinstance(payload, dict) else ''}"
        )
        return []
    rows = (payload.get("data") or {}).get("data") or []
    out: list[dict] = []
    for r in rows:
        url = r.get("pc_url") or r.get("client_url") or r.get("mobile_url") or ""
        try:
            source_domain = urlparse(url).hostname or ""
        except Exception:
            source_domain = ""
        out.append({
            "title": str(r.get("title", "")),
            "url": url,
            "source_domain": source_domain,
            "publish_date": str(r.get("date", "")),
            "media_name": "",  # 上游无 media_name 字段
        })
    return out
```

### 3.4 `get_announcements(code, page_size=30)` — 新方法

```python
def get_announcements(self, code: str, page_size: int = 30) -> list[dict]:
    """THS 个股公告 via basic.10jqka.com.cn/basicapi/notice/pub.

    返回 dict shape 对齐 CninfoFetcher.get_announcements:
      {title, type, date, url}, 额外带 raw_url (巨潮 PDF 直链).

    Returns [] on no market_id mapping / upstream error.
    """
    code = normalize_stock_code(code)
    market_id = _THS_MARKET_ID_MAP.get(code[:1])
    if not market_id:
        logger.warning(f"[ThsFetcher] get_announcements: no market_id for {code!r}")
        return []
    try:
        n = max(1, min(int(page_size), 100))
    except (TypeError, ValueError):
        n = 30
    try:
        payload = json_get(
            THIS_NOTICE_URL,
            params={
                "type": "stock",
                "code": code,
                "market": market_id,
                "classify": "all",   # 未来如要分类过滤，再暴露为参数
                "page": 1,
                "limit": n,
            },
            headers=THIS_BASIC_HEADERS,
            timeout=10,
        )
    except DataFetchError:
        raise
    if not isinstance(payload, dict) or payload.get("status_code") != 0:
        logger.warning(
            f"[ThsFetcher] get_announcements({code}) upstream "
            f"status_code={payload.get('status_code') if isinstance(payload, dict) else 'N/A'}"
        )
        return []
    rows = payload.get("data") or {}
    # 上游结构: {data: {data: [records], total, page, limit}, type: [...]}
    items = rows.get("data") if isinstance(rows, dict) else []
    out: list[dict] = []
    for r in items:
        url = r.get("pc_url") or r.get("mobile_url") or ""
        out.append({
            "title": str(r.get("title", "")),
            "type": "",          # 上游 type 字段是分类维度, 不是公告 type; 留空
            "date": str(r.get("date", "")),
            "url": url,
            # raw_url 不在现有 schema; 路由层通过 extra='allow' 透传
            # 见 §3.6 schema 升级
            "raw_url": r.get("raw_url") or "",
        })
    return out
```

### 3.5 Manager / Route / Cache 层 — 零代码改动

- `DataCapability.STOCK_NEWS` 已在 `CAPABILITY_TO_METHOD` 映射 `get_stock_news`，`thsfetcher` 类上有同名方法即可被纳入；`Test_capability_method_map.py` 自动覆盖。
- `DataCapability.ANNOUNCEMENT` 同理。
- `routes/news.py::get_stock_news` / `routes/stocks.py::get_announcements` 不动；`manager._with_failover` 按 priority 排序自动选择 EastMoney → Ths → Cninfo。
- 缓存键 `make_news_stock_cache_key` / `make_announcements_cache_key` 已经按 `(code, limit/page_size)` 区分；不同 fetcher 输出相同 dict shape，缓存命中率不损失。

### 3.6 Schema 调整 — `api/schemas.py::AnnouncementRecord`

```python
class AnnouncementRecord(_UpstreamSanitizedModel):
    """公告记录"""

    title: str = Field(default="", description="标题")
    type: str = Field(default="", description="公告类型")
    date: str = Field(default="", description="发布日期")
    url: str = Field(default="", description="公告链接")
    # 新增: 巨潮原文 PDF 直链; 默认空字符串, 向后兼容旧 client.
    # 上游仅 ThsFetcher 在 basic.10jqka.com.cn 端点上携带; 其他 fetcher 留空.
    raw_url: str = Field(default="", description="巨潮原文 PDF 直链 (ThsFetcher only)")
```

`_UpstreamSanitizedModel`（如启用 sanitization）会自动忽略 list 中的额外字段；新字段对老 client 是 forward-compatible 的。

> **风险点**：如果 `_UpstreamSanitizedModel` 默认 `extra="ignore"` 且不含字段会被丢弃，仅 `**extra` 时抛弃，`raw_url` 显式声明则 Pydantic 不会丢；但还要查 `Route 端构造 AnnouncementRecord(**r)` 的位置是否容忍 schema 多字段 — 我们这次只新增字段，旧 fetcher 返回的 dict 不带 `raw_url`，Pydantic 取默认 `""`，**没问题**。

### 3.7 测试策略

| 测试 | 类别 | 触发方式 |
|---|---|---|
| `tests/test_manager_stock_news.py::test_ths_added_as_backup` | 离线/mock | 默认跑 |
| `tests/test_manager_announcements.py` (新) — EastMoney 抛错时回退到 Ths | 离线/mock | 默认跑 |
| `tests/test_capability_method_map.py::test_ths_supports_announcement_and_stock_news` | 离线 | 默认跑 |
| `tests/fixtures/ths_basic_news.json`, `tests/fixtures/ths_basic_notice.json` | 离线 | 用 Playwright 一次性抓取（已抓过，不重复抓） |
| `tests/test_ths_basic_endpoints_live.py` (新, `@pytest.mark.live_network`) | 在线（限速 2-3s, 仅 1-2 case） | 仅 `-m ""` 或 `-m live_network` |

### 3.8 错误处理

| 场景 | 行为 |
|---|---|
| `code` 无 `market_id` 映射（4/8 开头，或 HK/US） | logger.warning + return `[]`（对齐 `get_stock_boards`） |
| 上游 `status_code != 0` | logger.warning + return `[]`（**不 raise**）— 让 manager failover 跳到下一家 |
| HTTP timeout / 5xx / JSON parse | `json_get` 抛 `DataFetchError`；manager failover 捕获后跳下一家 |
| 上游 payload 不是 dict | logger.warning + return `[]` |

> **不 raise** 的关键：falsy response 不能让 manager 误以为本 fetcher 还能服务下一次同请求。只有 `DataFetchError` 才能保证 manager 进入下一家。

---

## 4. 风险与缓解

| 风险 | 缓解 |
|---|---|
| `basic.10jqka.com.cn` 限速未知（用户已 prompt 提醒） | 默认离线 mock；live 测试每条间隔 2-3s, 仅 1-2 case |
| 北交所代码返回 `[]` vs 抛错 | 跟 `get_stock_boards` 同 return `[]`, **不 raise** |
| 上游字段改版 (e.g. `pc_url` 重命名) | `str(r.get(..., ""))` + try/except；logger.warning 单行告警 |
| `raw_url` 字段加进 schema 触发老 client 报错 | 默认 `""`，Pydantic 反序列化时忽略额外 key；schema 是 additive-only |
| `manager._with_failover` 在 THS 返回 `[]` 时不会自动跳下一家 | 与 EastMoney 一致 — 同问题已存在；不属本次范围；failover 由 `DataFetchError` 触发，本次同 EastMoney 返回 `[]` 的语义 |

---

## 5. 文件改动清单

| 文件 | 改动 |
|---|---|
| `stock_data/data_provider/fetchers/ths_fetcher.py` | 新增 `THIS_NEWS_URL` / `THIS_NOTICE_URL` / `THIS_BASIC_HEADERS` 常量；`supported_data_types` 加 `STOCK_NEWS` / `ANNOUNCEMENT`；新增 `get_stock_news` / `get_announcements` 方法 |
| `stock_data/api/schemas.py::AnnouncementRecord` | 新增 `raw_url: str = Field(default="", ...)` |
| `tests/test_manager_announcements.py` | 新建（EastMoney P6 fail → Ths P7 backup 路径断言） |
| `tests/fixtures/ths_basic_news.json` | 新建（300740 单页 fixture, 5-10 条记录） |
| `tests/fixtures/ths_basic_notice.json` | 新建（300740 单页 fixture, 5-10 条记录） |
| `tests/test_ths_basic_endpoints_live.py` | 新建, 标记 `@pytest.mark.live_network` |

零改动：`stock_data/data_provider/manager.py`、`stock_data/api/routes/news.py`、`stock_data/api/routes/stocks.py`、`stock_data/api/cache.py`、`stock_data/explorer/*`（manifest 自动 reflect 新方法）。
