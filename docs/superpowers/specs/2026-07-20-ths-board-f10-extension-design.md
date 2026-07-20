# THS 板块 F10 扩展 + stock_board 列重命名 设计文档

> 日期：2026-07-20
> 状态：待审（2026-07-20 review 后修订：修正分流层 / 砍过度设计 / F10 HTML 复用）
> 范围：
> 1. `stock_board` 表的 `platecode` 列改为 `code`，新增 `cid` 列
> 2. `ThsFetcher` 新增 `get_board_stocks_full`（90+ 完整成分股，HTML 抓取自 `basic.10jqka.com.cn/48/{platecode}/`）
> 3. 新增 `get_board_news`（板块热点新闻，HTML 抓取）
> 4. 新增 `get_board_surges`（板块炒作周期，HTML 抓取）
> 5. 同步暴露 3 个新的 REST 端点：`/boards/{code}/news` `/boards/{code}/surges`；`/boards/{code}/stocks` 在 `include_quote=false` 时内部走新 full API

---

## 1. 背景与动机

### 1.1 列重命名（platecode → code + 新增 cid）

**现状问题**：THS 概念板在表里同时存了 `code`（cid, 3xxxxx）和 `platecode`（885xxx）。其他 source（eastmoney / zhitu）只用一个 `code` 字段。这意味着同一行的 `code` 字段在不同 source 下语义不一致：

- THS concept：`code` = cid（`301558`），`platecode` = 公开的 K-line 标识（`885642`）
- THS industry：`code` = `platecode` = `881xxx`（重叠）
- eastmoney / zhitu：`code` = 业务唯一码，`platecode` = NULL

这种不对称导致：
- `_resolve_ths_cid_from_platecode(platecode)` 这样一个反向查找函数必须存在
- 多数读 SQL 都用 `code OR platecode` 的 OR 谓词（`board.py:1392`, `1507`, `1549`）
- 服务器对外暴露 `code` 字段时，THS 用户拿到 cid 而其他 source 拿到 board_code — 同一字段不同语义，客户端解析时要分情况

**目标**：让 `stock_board.code` 对所有 source 一致地表示「对外公开的唯一 board 标识」（即 THS 的 platecode / eastmoney 的 BKxxxx / zhitu 的 sw_yx），新增 `cid` 列专存 THS 内部 cid，THS 概念的 `(code, cid)` 双键结构变成显式 schema 表达。

### 1.2 get_board_stocks_full 90+ 完整成分股

**现状**：`ThsFetcher.get_board_stocks` 走 `q.10jqka.com.cn/gn/detail/code/{cid}/field/.../ajax/1/`，THS 上游硬上限 50 只，超过 401/403 触发 boundary signal。这导致：对于「煤炭概念」这种 90+ 只股票的板块，服务器最多只能返回前 50。

**新发现**：`basic.10jqka.com.cn/48/{platecode}/` 的 F10 页面 server-render 出完整的「概念股排名」表格，90 只股票全部在 HTML 里（含 `code` 属性、股票名称、所属主板、涨停次数、每股收益、流通股本、流通市值、个股解析）。1 次 GET 200ms 拿全。

**目标**：当 `?include_quote=false`（不需要实时行情）时，服务器走 F10 抓全 90+ 只，回填 stock_board_membership 缓存，签名与现有 `get_board_stocks` 对齐。

### 1.3 /boards/{code}/news 和 /boards/{code}/surges

**现状**：项目「板块」概念下已经有 K 线 / 成分股 / 实时行情 / 列表，但没有「板块新闻」和「炒作周期」数据。THS F10 页面同时 server-render 这两部分（17 条新闻 + 5 个月份的炒作周期），无新接口暴露。

**目标**：暴露两个 THS-only 端点：
- `/boards/{code}/news?limit=20&source=ths` — 板块热点新闻
- `/boards/{code}/surges?limit=5&source=ths` — 板块炒作周期（按月聚合）

`source` 预留，但 v1 仅 THS 实现，其他 source 返回 400。

---

## 2. 现状

### 2.1 `stock_board` 当前 schema

`stock_data/data_provider/persistence/board.py:259-272`：

```sql
CREATE TABLE IF NOT EXISTS stock_board (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    board_type TEXT NOT NULL,
    subtype TEXT,
    source TEXT NOT NULL,
    platecode TEXT,                          -- ← 改为 code，新增 cid
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(code, source)
)
```

约束：`UNIQUE(code, source)`。索引：`(board_type)`, `(source)`, `(board_type, subtype, source)`。

### 2.2 现存 `platecode` 引用清单（来自 3-agent 探查报告）

总共 50+ 处 SQL / Python dict key / 参数名引用，分布在：

| 文件 | 引用类型 | 数量 |
|---|---|---|
| `stock_data/data_provider/persistence/board.py` | SQL 列、dict key、参数 | 25+ |
| `stock_data/data_provider/persistence/board_csv.py` | CSV 列名、`_STOCK_BOARD_COLS`、`_EASTMONEY_COLS` | 6 |
| `stock_data/data_provider/persistence/backfill.py` | dict key | 5 |
| `stock_data/data_provider/fetchers/ths_fetcher.py` | dict key、参数 | 7 |
| `tests/test_boards_backfill_integration.py` | dict key | 2 |
| `tests/test_board_backfill.py` | dict key | 4 |
| `tests/test_persistence_board_merge.py` | 间接测试 | 多 |
| `tests/test_ths_fetcher_get_all_boards_live.py` | docstring + assertion | 3 |
| `tests/test_persistence_board_name_fallback.py` | docstring | 1 |

**重命名原则**：
- `code` (旧) → `cid`（专存 THS 内部 cid）
- `platecode` (旧) → `code`（专存对外公开的 board 标识）
- 唯一约束从 `UNIQUE(code, source)` 改为 `UNIQUE(code, source)` 不变（因为新 `code` = 旧 `platecode` 对 THS concept，`code` = 旧 `code` = 旧 `platecode` 对 THS industry/eastmoney/zhitu）

### 2.3 ThsFetcher 现状

`stock_data/data_provider/fetchers/ths_fetcher.py` 中已存在的方法：

- `get_board_stocks` (line 1113) — q.10jqka AJAX，硬 cap 50，含 11 种实时行情排序键
- `get_board_realtime` (line 1313) — q.10jqka concept detail page
- `get_board_history` (line 800) — d.10jqka.com.cn K 线
- `get_stock_news` (line 1419) — basic.10jqka 个股新闻
- `get_all_boards` (line 1655) — q.10jqka index pages
- `get_stock_boards` (line 1533) — basic.10jqka stock_concept_list
- `_resolve_ths_platecode_from_cid` (line 587) — 反向（cid → platecode）

**`get_board_stocks_full` / `get_board_news` / `get_board_surges` 都不存在**，是净新增。

### 2.4 CSV 种子文件

`stock_data/stock_data_backup/`：

- `stock_board_ths.csv`：列 `code, name, board_type, subtype, source, platecode, updated_at`
- `stock_board_eastmoney.csv`：列 `board_type, board_code, board_name`（旧 3 列格式，loader 内部填默认值）
- `stock_board_membership_ths.csv`：列 `board_code, stock_code, source, board_name, stock_name, board_type, subtype, refreshed_at`（**不变** — 它的 `board_code` 已经是 platecode）

`stock_data/data_provider/persistence/board_csv.py` 中：
- `_STOCK_BOARD_COLS = {"code", "name", "board_type", "subtype", "source", "platecode"}` — 改为 `{"code", "name", "board_type", "subtype", "source", "cid"}`
- `_EASTMONEY_COLS = {"board_type", "board_code", "board_name"}` — eastmoney 旧 3 列格式可以保持不变（loader 内部映射 `board_code` → 新 `code` 即可，简化方案）；或者**对齐新列名**采用 `code, name, board_type, subtype, source, cid, updated_at`（与 ths CSV 一致），让 backfill 统一路径

**决策**：把 eastmoney CSV 也对齐成与 ths 一样的 7 列结构。理由：用户允许「如果能简化 backfill 代码就一并调整」，统一后 `board_csv.py` 只需要 1 个 loader 函数处理 2 个 source（eastmoney 旧 3 列格式只是少了几个字段，由 loader 填默认值）。这样：
- `_EASTMONEY_COLS` 删除
- `seed_stock_board_from_csv(source, csv_path)` 一份代码处理所有 source
- backfill 调试时拿到的 CSV 镜像跟 SQLite 表 schema 完全对齐

### 2.5 `manager._with_source` 已支持的模式

`stock_data/data_provider/manager.py:164` 已有 `_with_source(source, capability, market, method_name, **kwargs)`，它**不**做 failover，只按 source slug 选 fetcher。3 个新方法（`get_board_stocks_full`, `get_board_news`, `get_board_surges`）只需：
- 在 `ThsFetcher` 上加方法
- 在 `DataFetcherManager` 加对应 wrapper（与现有 `get_board_stocks` / `get_board_realtime` 模式相同）
- 注册到 `CAPABILITY_TO_METHOD`（如果有新 capability flag）

### 2.6 路由风格

现有 `/boards/{code}/stocks` / `/boards/{code}/quote` / `/boards/{code}/history` 路径形态。新增：
- `/boards/{code}/news` — 板块新闻
- `/boards/{code}/surges` — 板块炒作周期

---

## 3. 目标设计

### 3.1 `stock_board` schema 变更

**新 DDL**：

```sql
CREATE TABLE IF NOT EXISTS stock_board (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL,           -- 对外公开的 board 标识
                                   --   THS concept/industry: platecode (885xxx/881xxx)
                                   --   eastmoney: BKxxxx
                                   --   zhitu: sw_xxx
    name TEXT NOT NULL,
    board_type TEXT NOT NULL,
    subtype TEXT,
    source TEXT NOT NULL,
    cid TEXT,                     -- 仅 THS 概念板存内部 cid (3xxxxx)
                                   -- 其他 source 留 NULL
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(code, source)
)
```

**Migration 路径**：
- 新数据库：CREATE TABLE 走新 schema
- 旧数据库（dev box 现状）：`_add_cid_column_if_missing` + `_rename_platecode_to_code` 两条 ALTER
  - SQLite 不支持 `RENAME COLUMN` 直到 3.25.0；项目用 WAL + python 3.10+ 默认 sqlite ≥ 3.37，**支持** `ALTER TABLE stock_board RENAME COLUMN platecode TO code`
  - 不支持的话 fallback：创建新表 + INSERT INTO ... SELECT + DROP + RENAME
  - `_add_cid_column_if_missing` 镜像现有 `_add_platecode_column_if_missing` 模式

**字段语义**：

| 场景 | `code` (新) | `cid` |
|---|---|---|
| THS concept | `885642` (旧 platecode) | `301558` (旧 code) |
| THS industry | `881270` (旧 code = 旧 platecode) | `881270` (与 code 相同冗余存；可选存，简化起见存一份) |
| eastmoney | `BK1048` | NULL |
| zhitu | `sw_yx` | NULL |

THS industry 行的 `cid = code` 是冗余但无害：它保留了「这一行是 THS 源」的标识，`_resolve_ths_cid_from_platecode` 的 WHERE `source='ths'` 谓词已经够用，但 `cid` 列仍写以方便外部调试。

### 3.2 `get_board_stocks_full` 设计

**入口**：
```python
def get_board_stocks_full(
    self,
    board_code: str,                              # platecode (885xxx concept)
    *,
    board_type: str | None = None,                # "concept" / None
    **kwargs,
) -> list[dict]:
```

**URL**（v1 仅 concept）：
- 概念板：`https://basic.10jqka.com.cn/48/{platecode}/`
- 行业板（`881xxx`）：**v1 不支持**。现有 THS fetcher 走的是 `basic.10jqka.com.cn/fuyao/...` 新 API 路径，从未实测过 `/47/{platecode}/` 这类行业 F10 页面；未 probe 就写死 marketid 违反项目 `upstream-probe-success-case` / `fixture-must-match-real-upstream` 两条 memory。行业板的 F10 path 留到实测后再加（返回空 `[]` + 日志，不抛）。

#### 3.2.1 F10 页面抓取与复用（三个方法共用）

`get_board_stocks_full` / `get_board_news` / `get_board_surges` 都 GET 同一个 F10 URL。为避免客户端同时调三个端点时抓同一页 3 次，抽一个薄方法 + 短 TTL HTML 复用缓存：

```python
_F10_HTML_TTL = 45  # 秒；窗口内同一 platecode 只抓 1 次

def get_board_f10_page(self, board_code: str, *, board_type: str | None = None) -> str:
    """抓 F10 页面 HTML，带 module-level 短 TTL 缓存。

    三个公开方法（stocks_full / news / surges）各自调本方法拿 HTML
    再解析各自的 section，互不依赖。route 层 `@cache_endpoint` 的
    长 TTL（30min/1h）不受影响——本缓存只覆盖「同一请求窗口内
    多个解析方法重叠抓取」。
    """
```

- 缓存载体：module-level `_f10_html_cache: dict[str, tuple[str, float]]`（platecode → (html, ts)）。FastAPI 同步路径无需加锁；若将来上线程池再补 `threading.Lock`。
- TTL 45s：足够覆盖客户端连调三端点 + route 层 TTL 失效后首个重叠请求；又不至于让限流/封禁信号滞后太久。
- 401/403：本方法返回 `""`（空串），三个解析方法各自把空串当"无数据"处理（返回 `[]`），与既有 boundary signal 一致。
- 5xx / 网络失败：抛 `DataFetchError`（不缓存）。

#### 3.2.2 HTML 解析（成分股排名表）

1. 找 `<div id="c_table">` 下的 `<table class="m_table m_hl">`
2. 每行 `<tr class="c_highlight">`：
   - stock_code：`a.jumpto[code="xxxxxx"]` 的 `code` 属性
   - stock_name：`a.jumpto` 文本（去掉 `<em class="ccept_long">` 子元素）
   - 主板：`td:nth-child(3).tc` 文本（"上交所"/"深交所"/"北交所"）→ 映射 `exchange = "sh"/"sz"/"bj"`
   - 排名：`td:nth-child(1).tc` 文本（仅作可选排序辅助，**不进响应**——见下方"返回 shape"）

**返回 dict shape**（与 `get_board_stocks` 对齐，quote 字段全 None）：
```python
{
    "stock_code": "600227",        # 6 位 bare
    "stock_name": "赤天化",
    "exchange": "sh",               # "sh"/"sz"/"bj"/""
    # quote 字段全 None（F10 不提供实时行情；与 get_board_stocks
    # 的 BoardStockInfo 字段集对齐，路由层零映射）
    "price": None,
    "change_pct": None,
    "change_amount": None,
    # ... 其余 quote 字段同 None
}
```

**砍掉的 F10 字段（过度设计回退）**：`rank / limit_up_count_year / eps / float_share_yi / float_mv_yi / analysis` 这 6 个字段**不进 `BoardStockInfo`**。用户需求 2 的目标是「拿全 90+ 只成分股」，不是把 F10 排名表的额外列都暴露。引入 6 个新 schema 字段 + 一个 `_convert_full_to_stocks_info` 映射 helper 比"quote 字段填 None"更复杂、更偏离 YAGNI（本地个人项目）。F10 的每股收益/流通市值等若将来真要暴露，再单开 `/boards/{code}/stocks/full` 端点，不污染既有响应。

**砍掉 `popInfoArr` 解析**：原 spec 用 regex `re.search(r'var\s+popInfoArr\s*=\s*\[(.*?)\];', ...)` + split 处理 JS 数组内嵌 HTML 字符串（带 `\"` / `\n` 转义）。这种解析在引号转义/嵌套标签上易翻车，而 `analysis` 字段又属于上方已砍的"额外字段"。v1 不解析 `popInfoArr`，`analysis` 不返回。

**排序**：F10 页面默认按 `涨停次数 desc` 排序。`?sort_by` 在 v1 不支持 — 因为 F10 server-render 不接受 URL query 改排序，且真实场景里「涨停次数 desc」一般够用。**如果客户端要按 `流通市值 desc` 排序**，回退到 `get_board_stocks(include_quote=true, sort_by=float_market_cap)` — 50 只上限，但带实时行情。`top_n` 参数：F10 一次返回所有 90+，无 cap；可传 `top_n` 做客户端裁剪。

**失败处理**：
- HTTP 401/403：返回空 `[]`（F10 限流的容错信号 — 与 `get_board_stocks` 的 401/403 边界信号处理一致）
- HTTP 5xx / 网络失败：抛 `DataFetchError`
- HTML 解析失败（找不到 `c_table`）：抛 `DataFetchError`
- industry board_type 传入：返回空 `[]` + 日志（v1 不支持，见上方）

### 3.3 `get_board_news` 设计

**入口**：
```python
def get_board_news(
    self,
    board_code: str,                              # platecode
    *,
    limit: int = 20,                              # 1-50
    **kwargs,
) -> list[dict]:
```

**HTML 来源**：调 `self.get_board_f10_page(board_code)`（§3.2.1，带短 TTL 缓存），不重复抓取。

**HTML 解析**：

1. 找 `<div class="m_box post" id="news">` 下的 `<div class="newslist clearfix">`
2. 每个新闻是 `<dl>`：
   - URL：`dt > a[href*="news.10jqka.com.cn"]` 的 `href` 属性
   - 标题：`dt > a > strong` 文本
   - 时间：`span.fr.date` 文本（"08:44" 格式）
   - 摘要：`dd.hot_preview p` 文本（部分新闻为空 → 摘要为 `""`）
   - 日期：从 URL 路径 `/field/{YYYYMMDD}/{id}.shtml` 提取

**返回 dict shape**：
```python
{
    "title": "中国神华：...",
    "url": "http://news.10jqka.com.cn/field/20260720/678277988.shtml",
    "publish_date": "2026-07-20",   # 来自 URL path
    "publish_time": "08:44",        # 来自 span.fr.date
    "summary": "中国神华(601088.SH)...",  # 来自 dd.hot_preview p
    "source_domain": "news.10jqka.com.cn",
}
```

**limit 处理**：F10 一次返回约 17 条新闻（`count = html.count('<dl>')`），超过 limit 在 Python 端 `rows[:limit]` 截断；少于则全返。

**v1 范围 / source 校验**：`?source=ths` 是默认且**唯一合法值**，路由签名用 `source: Literal["ths"] = Query("ths")`，非 ths 值由 FastAPI 自动返回 422。**fetcher / manager 层不做 `source != "ths"` 手动校验**——避免与路由层 `Literal` 校验重复（原 spec 的 `raise NotImplementedError → map_errors 转 400` 与路由 `HTTPException(400)` 两种机制互相矛盾，统一收敛到 `Literal` 422）。

### 3.4 `get_board_surges` 设计

**入口**：
```python
def get_board_surges(
    self,
    board_code: str,                              # platecode
    *,
    limit: int = 5,                               # 1-12
    **kwargs,
) -> list[dict]:
```

**HTML 来源**：调 `self.get_board_f10_page(board_code)`（§3.2.1，带短 TTL 缓存），不重复抓取。

**HTML 解析**：

1. 找 `<div class="m_box" id="period">` → `<div class="history clearfix">`
2. 每个时间点是 `<div class="timeline">`：
   - 日期：`<span class="time">{YYYY-MM-DD}</span>`
   - 板块涨幅：`<thead> tr.f14 > th:nth-child(1) .upcolor` 或 `.fallcolor` 文本（带 `%`）
   - 上证涨幅：`<thead> tr.f14 > th:nth-child(2)` 同
   - 涨停家数：`<thead> tr.f14 > th:nth-child(3) .tip` 文本（"8家"）
   - 涨停股完整列表：第 2 个 `<p class="flexcont" style="display:none;">` 里的所有 `<a class="jumpto">[code="..."]</a>` 链接

   第 1 个 `<p class="flexcont">` 是默认显示的 5 只（带 `查看全部▼`），第 2 个是完整列表（带 `收起▲`）。我们**抓第 2 个**，因为它一次性给完整涨停股名单。

**返回 dict shape**：
```python
{
    "date": "2026-07-14",
    "board_change_pct": 3.67,
    "sh_change_pct": 0.01,
    "limit_up_count": 8,
    "limit_up_stocks": [            # 全部涨停股代码
        "600180", "600595", "603012", "600403",
        "601101", "002128", "000968", "600227"
    ],
    # 关联涨跌家数（如果有）
    "up_count": None,               # F10 暂不提供
    "down_count": None,
}
```

**limit 处理**：F10 返回约 5 个月份（最近 1 年内的「相对炒作高峰」），超过 limit 在 Python 端 `rows[:limit]` 截断。

**v1 范围 / source 校验**：同 §3.3，`source: Literal["ths"]`，非 ths 值 422，fetcher/manager 层不重复校验。

### 3.5 路由层设计

#### 3.5.1 `/boards/{code}/stocks`（修改）

**分流点放在 `persistence/board.py` 的 fallback helper 里，不放 `manager.get_board_stocks`。**

项目架构（CLAUDE.md「Persistence-Only Routing」+ 实测代码）是：
路由层 → `persistence/board.py::get_board_stocks`（board.py:928，返回 6-tuple）→ cold-path 委托 `fetch_board_stocks_with_zzshare_fallback`（board.py:745）→ 该 helper 调 `manager.get_board_stocks`（board.py:846/864/889/900/911）。

而 `fetch_board_stocks_with_zzshare_fallback` 在 `source='ths'` + `include_quote=False` 时**已经**有一条「ZZSHARE primary + THS fallback」链路（board.py:944-961 docstring + `effective_source` 暴露哪条腿服务）。原 spec 把分流放 `manager.get_board_stocks`、且通篇不提这个 helper，会导致新 F10 腿和既有 ZZSHARE 腿重叠打架。

**修正后的分流**：在 `fetch_board_stocks_with_zzshare_fallback` 里新增第三条腿，与既有 ZZSHARE/THS 链并列：

```
source='ths' + include_quote=False:
    leg 1 (现有): ZZSHARE primary   →  ~50 只 bare codes
    leg 2 (现有): THS AJAX fallback  →  50 只带 quote（ZZSHARE 失败/空时）
    leg 3 (新增): THS F10 full       →  90+ 只 bare codes + quote=None（首选）
```

优先级：v1 让 **THS F10 full 优先**（90+ 全量是用户需求 2 的目标）。F10 返回非空 → 用它，`effective_source='ths-f10'`；F10 返回空/401/403 → 退回既有 ZZSHARE primary + THS fallback 链，`effective_source` 取 `zzshare`/`ths`。

> 三条腿只取一条结果（非拼接）：F10 成功就用 F10 的 90+；F10 失败才退回旧链。这避免了"50 + 40+ 拼接"的排序破坏问题（见 §5.3）。

**`manager.get_board_stocks` 不承载 board 业务分流**——它只是被 persistence helper 调用的底层 fetcher dispatcher。新增的 `manager.get_board_stocks_full(board_code, source, ...)` wrapper（与 `get_board_news`/`get_board_surges` 同模式，走 `_with_source`）仅供 persistence helper 的 leg 3 调用，与既有 `manager.get_board_stocks` 并列，互不侵入。

**`include_quote=true` 完全不变**（用户需求 2 原文：「查询实时数据(include=true)时，走原逻辑」）：
- 仍走 `get_board_stocks` 原路径（q.10jqka AJAX，硬 cap 50 + ZZSHARE suffix 既有逻辑）
- **不**做"50 带 quote + 40+ 不带 quote 拼接"——那会破坏既有 sort 契约（client 看到 quote=None 行混在带 quote 行里）
- 现有 11 种 sort_by、`quote_truncated` / `quote_total_in_board` 契约全部保持

**响应 shape 兼容性**：
- `get_board_stocks_full` 返回的 dict 与 `get_board_stocks` **同 shape**（quote 字段全 None，见 §3.2.2）
- 路由层**零映射**：`include_quote=false` 路径直接把 full 返回的 dict 喂给 `BoardStockInfo`，无需 `_convert_full_to_stocks_info` helper（该 helper 随 §3.8 字段映射一并砍掉）
- 客户端语义：`include_quote=false` 本来就表示「不返回 quote」，与新行为一致

#### 3.5.2 `/boards/{code}/news`（新增）

```python
@router.get(
    "/boards/{board_code}/news",
    response_model=BoardNewsResponse,
    tags=["boards"],
)
@endpoint_meta(
    summary="板块热点新闻 (THS basic.10jqka.com.cn/48/{code}/ 抓取)",
    markets=["csi"],
    capabilities=["BOARD_NEWS"],
    fetcher_method="get_board_news",
)
@map_errors
@cache_endpoint(ttl=1800)  # 30 min, 板块新闻非强实时
def get_board_news_route(
    board_code: str = Path(max_length=30),
    limit: int = Query(20, ge=1, le=50),
    source: Literal["ths"] = Query("ths"),   # 非 ths → FastAPI 自动 422
):
    rows = manager.get_board_news(board_code, source="ths", limit=limit)
    return BoardNewsResponse(board_code=board_code, source="ths", data=rows)
```

> 不在路由内写 `if source != "ths": raise HTTPException(400)`——`Literal["ths"]` 已在类型层保证，重复校验只会让 422 vs 400 不一致。

#### 3.5.3 `/boards/{code}/surges`（新增）

```python
@router.get(
    "/boards/{board_code}/surges",
    response_model=BoardSurgesResponse,
    tags=["boards"],
)
@endpoint_meta(
    summary="板块炒作周期 (THS F10 页面 .history 区段抓取)",
    markets=["csi"],
    capabilities=["BOARD_SURGES"],
    fetcher_method="get_board_surges",
)
@map_errors
@cache_endpoint(ttl=3600)  # 1 h, 周期数据按月聚合,变化慢
def get_board_surges_route(...):
    ...
```

### 3.6 新增 `DataCapability` flags

| Flag | Default Method | 用途 |
|---|---|---|
| `BOARD_NEWS` | `get_board_news` | 板块新闻 |
| `BOARD_SURGES` | `get_board_surges` | 板块炒作周期 |

**添加到**：
- `stock_data/data_provider/base.py:167` 的 `DataCapability` enum
- `stock_data/data_provider/base.py:223` 的 `CAPABILITY_TO_METHOD`
- `ThsFetcher.supported_data_types` (line 451)

### 3.7 CSV 列重命名（用户已批准）

| 文件 | 旧列 | 新列 |
|---|---|---|
| `stock_data_backup/stock_board_ths.csv` | `code, name, ..., platecode, updated_at` | `code, name, ..., cid, updated_at` |
| `stock_data_backup/stock_board_eastmoney.csv` | `board_type, board_code, board_name` | `code, name, board_type, subtype, source, cid, updated_at`（补齐 + 排序与 ths 一致） |

**THS 行的转换**：旧 `code` (cid) → 新 `cid`；旧 `platecode` → 新 `code`。两个值都保留。

**EastMoney 行的转换**：旧 `board_code` → 新 `code`；新增 `subtype = board_type`（沿用原行为）；`source = eastmoney`（写死）；`cid = NULL`。

**`board_csv.py` 修改**：
- `_STOCK_BOARD_COLS` 改为 `{"code", "name", "board_type", "subtype", "source", "cid"}`
- 删除 `_EASTMONEY_COLS`（统一走 `_STOCK_BOARD_COLS`）
- `seed_stock_board_from_csv` 不再按 source 分支：1 份函数读 7 列
- INSERT 改用 `(code, name, board_type, subtype, source, cid, updated_at)`

**`stock_board_membership_ths.csv` 不变** — 它的 `board_code` 已经是 platecode（与新 `code` 同义），无需迁移。

### 3.8 `get_board_stocks` / `get_board_stocks_full` 关系

**`include_quote=false`（默认）**：
- `persistence/board.py::fetch_board_stocks_with_zzshare_fallback` 新增「THS F10 full」leg（首选，90+ 全量），失败退回既有 ZZSHARE primary + THS fallback 链（见 §3.5.1）
- 90+ 全量，回填 stock_board_membership 缓存（snapshot replace）
- 返回 dict 与 `get_board_stocks` 同 shape（quote 字段全 None），`BoardStockInfo` 零扩展、路由层零映射

**`include_quote=true`**：
- **完全不变**，走 `get_board_stocks` 原路径（q.10jqka AJAX，硬 cap 50 + 既有 ZZSHARE suffix 逻辑）
- **不做** "50 带 quote + 40+ 不带 quote 拼接"——会破坏既有 sort 契约（用户需求 2 原文要求 `include_quote=true` 走原逻辑）

**`BoardStockInfo` 不扩展**（过度设计回退）：
```python
class BoardStockInfo(BaseModel):
    code: str
    name: str = ""
    price: float | None
    change_pct: float | None
    ...                                   # 现有字段全部保留，无新增
```

原 spec 拟加的 `rank / limit_up_count_year / eps / float_share_yi / float_mv_yi / analysis` 6 个字段**全部砍掉**（理由见 §3.2.2「砍掉的 F10 字段」）。`get_board_stocks_full` 返回的 dict 与 `get_board_stocks` 同 shape（quote 字段全 None），路由层零映射、无需 `_convert_full_to_stocks_info` helper。`BoardStocksResponse` 不变。

---

## 4. 文件改动清单

### 4.1 schema / persistence（核心改动）

| 文件 | 改动 |
|---|---|
| `stock_data/data_provider/persistence/board.py` | (1) CREATE TABLE 改 `platecode` → `code`，新增 `cid` (2) 旧 db 迁移：`_add_cid_column_if_missing` + `_rename_platecode_to_code` (3) 25+ 处 `platecode` → `code` 重命名（dict key、SQL 列、参数） (4) 6 处 `r.get("platecode")` / `b.get("platecode")` → 同样重命名 (5) 13+ 处 SELECT/INSERT 的 `platecode` 列名重命名 (6) 删 `_resolve_ths_cid_from_platecode`，新增 `_resolve_ths_cid_from_code`，SQL 从 `WHERE platecode = ?` 改为 `WHERE code = ?` (7) `get_board_metadata` 返回值：`"platecode"` key 改为 `"code"`，新增 `"cid"` key |
| `stock_data/data_provider/persistence/board_csv.py` | (1) `_STOCK_BOARD_COLS` 加 `cid`、去掉 `platecode` (2) 删 `_EASTMONEY_COLS` (3) `seed_stock_board_from_csv` 1 个统一函数 (4) INSERT 列名改 |
| `stock_data/data_provider/persistence/backfill.py` | 5 处 `b.get("platecode")` → `b.get("code")` |
| `stock_data/stock_data_backup/stock_board_ths.csv` | 列名 `platecode` → `cid`，数据从 `code` 列搬到 `cid` 列（SWAP 语义） |
| `stock_data/stock_data_backup/stock_board_eastmoney.csv` | 旧 3 列 → 新 7 列（`code, name, board_type, subtype, source, cid, updated_at`），数据补齐 |

### 4.2 fetcher

| 文件 | 改动 |
|---|---|
| `stock_data/data_provider/fetchers/ths_fetcher.py` | (1) 新增 `_THS_F10_BOARD_URL` 常量（concept only，v1 不写死 industry marketid） (2) 新增 `get_board_f10_page` 薄方法 + module-level 短 TTL HTML 缓存（§3.2.1） (3) 新增 `get_board_stocks_full`（调 `get_board_f10_page`，同 shape、quote=None） (4) 新增 `get_board_news`（调 `get_board_f10_page`） (5) 新增 `get_board_surges`（调 `get_board_f10_page`） (6) 5 处 `r["platecode"]` / `meta["platecode"]` 改为 `r["code"]` / `meta["code"]`，新引用 `meta["cid"]` (7) `supported_data_types` 加 `BOARD_NEWS \| BOARD_SURGES` |
| `stock_data/data_provider/manager.py` | (1) 新增 `get_board_news(board_code, source, limit)` wrapper (2) 新增 `get_board_surges(board_code, source, limit)` wrapper (3) **新增** `get_board_stocks_full(board_code, source, ...)` wrapper（走 `_with_source`，仅供 persistence helper leg 3 调用，**不侵入**既有 `get_board_stocks`） (4) `_with_source` 调用新方法。**不修改 `get_board_stocks`**——分流在 persistence helper |
| `stock_data/data_provider/persistence/board.py`（§3.5.1 分流） | `fetch_board_stocks_with_zzshare_fallback` 新增 THS F10 leg（首选，失败退回 ZZSHARE+THS 链），`effective_source` 取 `ths-f10`/`zzshare`/`ths` |
| `stock_data/data_provider/base.py` | (1) `DataCapability` 加 `BOARD_NEWS` / `BOARD_SURGES` (2) `CAPABILITY_TO_METHOD` 加 2 条 (3) docstring 更新 |

### 4.3 API / 路由

| 文件 | 改动 |
|---|---|
| `stock_data/api/schemas.py` | (1) **`BoardStockInfo` 不加字段**（同 shape、quote=None 即可） (2) 新增 `BoardNewsItem` / `BoardNewsResponse` (3) 新增 `BoardSurgeItem` / `BoardSurgesResponse` |
| `stock_data/api/routes/boards.py` | (1) `/boards/{code}/news` 新路由（`source: Literal["ths"]`，无手动 400 校验） (2) `/boards/{code}/surges` 新路由（同） (3) `/boards/{code}/stocks` 路由 docstring 更新，提示 `include_quote=false` 走 F10 全量；`include_quote=true` 行为不变 |
| `stock_data/api/routes/helpers.py` | (1) 如果 cache 装饰器需要新增 `BoardNews` / `BoardSurges` key，加到这里 |

### 4.4 测试

新增：
- `tests/test_ths_fetcher_get_board_stocks_full.py` — 解析 90+ 行；mock HTTP 返回 fixture HTML
- `tests/test_ths_fetcher_get_board_news.py` — 解析新闻列表；mock fixture
- `tests/test_ths_fetcher_get_board_surges.py` — 解析炒作周期；mock fixture
- `tests/test_boards_news_route.py` — 路由 + schema 验证
- `tests/test_boards_surges_route.py` — 路由 + schema 验证
- `tests/test_persistence_stock_board_cid.py` — 新 schema 验证

修改：
- `tests/test_board_csv_seed.py` — 新列名适配
- `tests/test_board_backfill.py` — `platecode` → `code`
- `tests/test_boards_backfill_integration.py` — 同
- `tests/test_persistence_board_merge.py` — 同
- `tests/test_persistence_board_name_fallback.py` — 同
- `tests/test_persistence_board_memberships.py` — 同
- `tests/test_ths_fetcher_get_all_boards_live.py` — 字段名

### 4.5 fixtures

- `tests/fixtures/ths_basic_board_885914_full.html` — 今天保存的 `/tmp/ths_board_html.html` + playwright dump 的 90 行排名表（dev box 复现用）
- `tests/fixtures/ths_basic_board_885914_news.html` — 板块新闻片段
- `tests/fixtures/ths_basic_board_885914_surges.html` — 板块炒作周期片段

---

## 5. 兼容性 / Migration 风险

### 5.1 数据库 Migration

**风险点**：dev box 已有 `stock_board` 表，列名是 `code` + `platecode`，数据是 1000+ 行。

**Migration 步骤**（在 `init_schema` 启动时执行，幂等）：
1. `_add_cid_column_if_missing(cursor)` — `ALTER TABLE stock_board ADD COLUMN cid TEXT`
2. `_rename_platecode_to_code(cursor)`：
   - 路径 A（sqlite ≥ 3.25）：`ALTER TABLE stock_board RENAME COLUMN platecode TO code`
   - 路径 B（fallback）：`ALTER TABLE stock_board RENAME TO stock_board_old` + `CREATE TABLE stock_board (..., code TEXT, cid TEXT, ...)` + `INSERT INTO stock_board SELECT id, platecode AS code, name, board_type, subtype, source, code AS cid, updated_at FROM stock_board_old` + `DROP TABLE stock_board_old`
3. 重建索引（如果路径 B 走了，索引不会随 RENAME 迁移）

**风险缓解**：
- 启动日志输出 `migrated stock_board.platecode→code, populated cid from old code`
- 失败时回滚方案：保留 `stock_board_old` 5 分钟，超时 DROP（dev 项目，简化）
- 备份机制：现有 `stock_data_backup/stock_board_*.csv` 就是 dev box 的种子备份，备份刷新后即可回填

### 5.2 跨 fetcher 一致性

- `_resolve_ths_cid_from_platecode(platecode)` 重命名为 `_resolve_ths_cid_from_code(code)`，所有调用点同步更新
- 5 处 server-side Python 代码 + 2 处 test patch 同步
- THS fetcher 内部 `meta["platecode"]` 改 `meta["code"]`，新增 `meta["cid"]` 引用

### 5.3 排序契约保持（`include_quote=true` 不变）

**修订**：原 spec 让 `include_quote=true` 返回「50 带 quote + 40+ 不带 quote 拼接」，会破坏既有 sort 契约（`sort_by=float_market_cap` 只对 50 只带 quote 行有效，拼接的 40+ quote=None 行排序无意义）。该改动同时违反用户需求 2 原文（`include_quote=true` 走原逻辑）。**修订后 `include_quote=true` 完全不变**，无排序字段丢失风险。

`include_quote=false` 走 F10 全量，F10 默认按涨停次数 desc 排序、不支持 URL 改排序；客户端若要按 quote 字段排序，显式传 `include_quote=true`（50 cap + ZZSHARE suffix 既有逻辑）。两个路径职责清晰，不互相污染。

### 5.4 缓存失效

`/boards/{code}/stocks` 在 `include_quote=false` 时改走 F10 路径后，stock_board_membership 缓存的回填频率可能提升。已有 `DailyRefreshTracker` 控制 daily refresh 行为；route 层 `@cache_endpoint(ttl=1800)`（30 min）控制请求级缓存；fetcher 内 `get_board_f10_page` 的 45s HTML 缓存（§3.2.1）覆盖短窗口重叠抓取。三层 TTL 互不冲突。

---

## 6. 替代方案

### 6.1 不重命名列，加 `cid` 列

**做法**：`stock_board` 保留 `code` + `platecode`，新增 `cid` 列。THS concept 行：`code = cid (3xxxxx)`，`platecode = 885xxx`，`cid = 3xxxxx` (冗余存)。

**优点**：不用做 ALTER TABLE 迁移，dev box 不需重置数据。
**缺点**：
- 没解决「同一字段不同语义」问题
- `_resolve_ths_cid_from_platecode` 还是要存在
- 多数读 SQL 仍需 `code OR platecode` 的 OR 谓词
- 客户端拿 `BoardInfo.code` 时，THS 仍是 cid（300xxx），其他 source 是 BKxxxx，不一致

**决策**：用户明确说「platecode 才是其他 source 一致的对外暴露的唯一 code」，所以选重命名。

### 6.2 get_board_stocks_full 不回填 stock_board_membership

**做法**：F10 数据直接走 fetcher 路径，绕过缓存层。

**优点**：简单，stock_board_membership 不会因高频调用而 snapshot-replace
**缺点**：
- 30 个板块 × 5 分钟 = 30 req / 5 min，命中 ths 上游限流
- 客户端要 90+ 数据时，每次都 200ms 抓 F10
- 反向查询（`/stocks/{code}/boards`）的 cold_sources 永远填不上

**决策**：回填 `stock_board_membership` 缓存。

### 6.3 板块新闻/炒作周期不暴露 REST 端点

**做法**：仅在 fetcher 上加方法，不注册路由。

**优点**：最少改动
**缺点**：用户明确说要新增 API。

---

## 7. 验证

### 7.1 单元测试

```bash
# 全部单元测试（dev loop, fast, ~1min）
.venv/Scripts/python.exe -m pytest

# 新增的 3 个 fetcher 解析测试
.venv/Scripts/python.exe -m pytest tests/test_ths_fetcher_get_board_stocks_full.py -v
.venv/Scripts/python.exe -m pytest tests/test_ths_fetcher_get_board_news.py -v
.venv/Scripts/python.exe -m pytest tests/test_ths_fetcher_get_board_surges.py -v

# 新增的 2 个路由测试
.venv/Scripts/python.exe -m pytest tests/test_boards_news_route.py -v
.venv/Scripts/python.exe -m pytest tests/test_boards_surges_route.py -v

# schema 重命名后所有 board 持久化测试
.venv/Scripts/python.exe -m pytest tests/test_board_csv_seed.py tests/test_board_backfill.py tests/test_persistence_board_merge.py -v

# 验证 capability 注册
.venv/Scripts/python.exe -m pytest tests/test_capability_method_map.py -v
```

### 7.2 集成 / live 测试

```bash
# live network（CI / 预发布使用, 10+ min）
.venv/Scripts/python.exe -m pytest -m live_network

# 端到端：启动 server, 用 curl 验证 3 个端点
.venv/Scripts/python.exe -m stock_data.server &
sleep 5
curl -s "http://localhost:8888/api/v1/boards/885914/news?limit=5" | python -m json.tool
curl -s "http://localhost:8888/api/v1/boards/885914/surges?limit=5" | python -m json.tool
curl -s "http://localhost:8888/api/v1/boards/885914/stocks" | python -m json.tool  # 默认 include_quote=false, 应返回 90+ 只
curl -s "http://localhost:8888/api/v1/boards/885914/stocks?include_quote=true" | python -m json.tool  # 50 + 40+ 混合
```

### 7.3 Manifest sanity check

```bash
# 启动时检查
.venv/Scripts/python.exe -m stock_data.server 2>&1 | grep -E "(BoardCache|migrated|exponent|F10exponent)" | head
# 期望看到：
#   [BoardCache] Database initialized at ...
#   [BoardCache] added stock_board.cid column (forward-compat migration)
#   [BoardCache] renamed stock_board.platecode → code (forward-compat migration)
#   [Explorer] no warning about BOARD_NEWS / BOARD_SURGES
```

### 7.4 SQL 直查验证

```bash
# 启动后, 直查 SQLite 验证 schema
.venv/Scripts/python.exe -c "
import sqlite3
conn = sqlite3.connect('stock_data/stock_cache.db')
print(conn.execute('PRAGMA table_info(stock_board)').fetchall())
print(conn.execute('SELECT code, cid, name, source FROM stock_board WHERE source=\"ths\" LIMIT 3').fetchall())
"
# 期望: 列名包含 (code, cid), 不再包含 platecode
# THS 行的 code = 885xxx, cid = 3xxxxx
```

---

## 8. 时间估计

| 任务 | 工时 |
|---|---|
| schema 迁移 + 5 文件重命名 | 1.5h |
| CSV 改造 + eastmoney 7 列对齐 | 0.5h |
| `get_board_f10_page` 薄方法 + 短 TTL HTML 缓存 + 测试 | 1h |
| `get_board_stocks_full` fetcher 实现 + 测试 + fixture（同 shape、无 analysis 解析） | 1.5h |
| `get_board_news` fetcher 实现 + 测试 + fixture | 1h |
| `get_board_surges` fetcher 实现 + 测试 + fixture | 1h |
| `manager.get_board_stocks_full` wrapper + 2 个 news/surges wrapper | 0.5h |
| `fetch_board_stocks_with_zzshare_fallback` 新增 F10 leg（含 `effective_source`） + 测试 | 1h |
| 2 个新路由 + schema + capability 注册 | 1h |
| 测试文件新增 5 个 + 修改 7 个 | 1.5h |
| 集成测试 + live 测试 + manifest sanity | 0.5h |
| **合计** | **~10.5h** |

> 注：原 spec ~11.5h；砍掉 `BoardStockInfo` 6 字段 + 映射 helper + `popInfoArr` 解析（-2h），新增 `get_board_f10_page` 缓存 + persistence helper F10 leg（+1h），净降 ~1h。
