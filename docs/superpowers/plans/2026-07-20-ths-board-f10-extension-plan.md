# Plan: THS 板块 F10 扩展 + stock_board 列重命名

> Date: 2026-07-20
> Spec: `docs/superpowers/specs/2026-07-20-ths-board-f10-extension-design.md`
> Branch: `feat/ths-board-f10-extension` (sub-branch off master)

---

## Context

为什么改：

1. **`stock_board` 列语义不一致** — THS concept 行存了 `code` (cid, 3xxxxx) + `platecode` (885xxx) 双键，其他 source 只用 `code`。同一字段不同语义导致 `_resolve_ths_cid_from_platecode` 反向查找函数和 5+ 处 `code OR platecode` OR 谓词的存在。重命名让 `code` 对所有 source 一致地表示「对外公开的 board 标识」。

2. **成分股数量被硬 cap 50** — `ThsFetcher.get_board_stocks` 走 `q.10jqka.com.cn/gn/detail/code/{cid}/field/.../ajax/1/`，THS 上游硬上限 50，超过触发 401/403 边界信号。THS F10 页面 (`basic.10jqka.com.cn/48/{platecode}/`) server-render 90+ 全量。

3. **板块新闻和炒作周期未暴露** — THS F10 同一页面同时含 17 条新闻 + 5 个月份的炒作周期数据，server-render，但项目无 API 暴露。

预期成果：dev box 数据库 schema 升级、`/boards/{code}/stocks` 在不需要实时行情时返回 90+ 全量、新增 2 个 REST 端点。所有现有 client 与 OpenAPI 文档保持向后兼容（新字段全部 optional）。

---

## 实施步骤

按 4 个 phase 顺序进行。每个 phase 完成后跑相关测试，全部通过再进下一 phase。

### Phase 1: schema 迁移 + 列重命名（无功能新增）

**目标**：`stock_board` 表升级为新 schema（`code` + `cid`，无 `platecode`），所有持久层 SQL / dict key / 参数同步。**此 phase 不暴露新功能，只迁移底层。**

1. **`stock_data/data_provider/persistence/board.py`**：
   - `init_schema` (line 236) 的 CREATE TABLE：列名 `platecode` → `code`，新增 `cid TEXT`
   - 删 `_add_platecode_column_if_missing` (line 327)；新增 `_add_cid_column_if_missing`（同模式，幂等）
   - 新增 `_rename_platecode_to_code`：
     - `PRAGMA table_info(stock_board)` 检查列
     - 路径 A：`ALTER TABLE stock_board RENAME COLUMN platecode TO code`（sqlite ≥ 3.25）
     - 路径 B（fallback）：`ALTER TABLE stock_board RENAME TO stock_board_old` + 重建表 + `INSERT INTO stock_board (id, code, name, board_type, subtype, source, cid, updated_at) SELECT id, platecode, name, board_type, subtype, source, code, updated_at FROM stock_board_old` + `DROP TABLE stock_board_old` + 重建索引
   - **25+ 处重命名**（来自探查报告）— 用 `Edit` 工具的 `replace_all: true` 批量替换 `platecode` → `code`（小心：`code` 在 ths_fetcher 中既指代旧 `code` 也指代新 `code`；先逐个 `Grep` 上下文确认再 `replace_all`）
   - **6 处 dict key 重命名**（`r.get("platecode")` → `r.get("code")`，`b.get("platecode")` → `b.get("code")`）
   - **13+ 处 SQL 列重命名**（SELECT / INSERT 列表中的 `platecode` → `code`）
   - `_resolve_ths_cid_from_platecode` (line 553) 重命名为 `_resolve_ths_cid_from_code`，SQL `WHERE platecode = ?` 改为 `WHERE code = ?`（注意：参数名也叫 `code`，不是 `platecode`）
   - `get_board_metadata` (line 1514) 返回 dict：key `"platecode"` 改为 `"code"`，新增 `"cid"` key

2. **`stock_data/data_provider/persistence/board_csv.py`**：
   - `_STOCK_BOARD_COLS = {"code", "name", "board_type", "subtype", "source", "platecode"}` → `{"code", "name", "board_type", "subtype", "source", "cid"}`
   - 删 `_EASTMONEY_COLS = {"board_type", "board_code", "board_name"}`
   - `seed_stock_board_from_csv` (line 86) 改：1 个统一函数读 7 列，按 `source` 字段决定行归属（不再按 csv_path 后缀分发）
   - `seed_eastmoney_from_csv` (line ~200) 合并进 `seed_stock_board_from_csv`
   - INSERT 列名 `(code, name, board_type, subtype, source, platecode, updated_at)` → `(code, name, board_type, subtype, source, cid, updated_at)`

3. **`stock_data/data_provider/persistence/backfill.py`**：
   - 5 处 `platecode` 引用全部改为 `code`
   - `b.get("platecode")` → `b.get("code")`
   - 错误信息字符串里的 "platecode" 字面量同步

4. **CSV 文件数据迁移**（手动）：

   **`stock_data/stock_data_backup/stock_board_ths.csv`**：
   - 旧：列 `code, name, board_type, subtype, source, platecode, updated_at`，数据中 `code=301558, platecode=885642`
   - 新：列 `code, name, board_type, subtype, source, cid, updated_at`，数据中 **`code=885642, cid=301558`**（SWAP：旧 platecode 变新 code，旧 code 变新 cid）
   - 操作：用 Python 脚本读旧 CSV，写新 CSV（保留第 1 行重命名 header，行数据按列位置 SWAP）

   **`stock_data/stock_data_backup/stock_board_eastmoney.csv`**：
   - 旧：3 列 `board_type, board_code, board_name`
   - 新：7 列 `code, name, board_type, subtype, source, cid, updated_at`，从旧 3 列扩展
   - 映射规则：`board_code` → `code`；`board_name` → `name`；`board_type` 复制到 `subtype`（沿用旧 loader 行为）；`source = "eastmoney"`；`cid = ""`；`updated_at` 写当前时间戳
   - 操作：Python 脚本，idempotent（第二次运行不会破坏已迁移数据）

5. **测试修改**（7 个文件）：
   - `tests/test_board_csv_seed.py` — column set 适配，column count 断言
   - `tests/test_board_backfill.py` — dict key
   - `tests/test_boards_backfill_integration.py` — dict key
   - `tests/test_persistence_board_merge.py` — 间接（test 内部 dict literal）
   - `tests/test_persistence_board_name_fallback.py` — docstring + function name
   - `tests/test_persistence_board_memberships.py` — docstring
   - `tests/test_ths_fetcher_get_all_boards_live.py` — assertion + docstring

   **每个文件的具体改动**通过 `Grep` 工具精确定位后用 `Edit` 工具逐个替换。**关键陷阱**：`test_persistence_board_merge.py::test_concept_returns_different_cid` 这类 test 内部有 `{..., "platecode": ...}` 的 fixture dict literal，必须改。

**Phase 1 验证**：
```bash
# 1. schema 启动迁移
.venv/Scripts/python.exe -c "from stock_data.data_provider.persistence import init_schema; init_schema()"
# 期望日志: "renamed stock_board.platecode → code" + "added stock_board.cid column"

# 2. 直查 schema
.venv/Scripts/python.exe -c "
import sqlite3
conn = sqlite3.connect('stock_data/stock_cache.db')
cols = [r[1] for r in conn.execute('PRAGMA table_info(stock_board)').fetchall()]
print('columns:', cols)
print('THS sample:', conn.execute('SELECT code, cid, name FROM stock_board WHERE source=\"ths\" LIMIT 3').fetchall())
"
# 期望: columns = ['id', 'code', 'name', 'board_type', 'subtype', 'source', 'cid', 'updated_at']
# THS sample: code=885xxx (旧 platecode), cid=3xxxxx (旧 code)

# 3. 全部相关测试
.venv/Scripts/python.exe -m pytest tests/test_board_csv_seed.py tests/test_board_backfill.py tests/test_persistence_board_merge.py tests/test_persistence_board_name_fallback.py tests/test_persistence_board_memberships.py tests/test_ths_fetcher_get_all_boards_live.py -v
```

---

### Phase 2: 新增 3 个 fetcher 方法（无新路由）

**目标**：在 `ThsFetcher` 上加 `get_board_stocks_full` / `get_board_news` / `get_board_surges`，加 manager wrapper，加新 capability flag，写测试和 fixture。**此 phase 不动 API 路由层，新方法暂时只能从 fetcher 内部调。**

1. **`stock_data/data_provider/fetchers/ths_fetcher.py`** 顶部常量：
   - 新增 `_THS_F10_BOARD_URL = "https://basic.10jqka.com.cn/{marketid}/{platecode}/"`
   - `_THS_F10_MARKETID = {"concept": "48", "industry": "47"}`（marketid 是 THS F10 内部市场 ID，需实测验证；fallback 到 `48`）
   - `_THS_F10_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/117.0.0.0 Safari/537.36"`（与现有 `THS_UA` 一致即可）

2. **新方法 `get_board_stocks_full(self, board_code, *, board_type=None, **kwargs) -> list[dict]`**：
   - 根据 `board_type` 选 marketid；未指定则试 concept first, fallback industry
   - `requests.get(_THS_F10_BOARD_URL.format(...), headers=..., timeout=10)`
   - `r.encoding = "gbk"`（F10 页面也用 gbk）
   - BeautifulSoup 解析 `<div id="c_table">` 下 `<table class="m_table m_hl">`
   - 每行 `<tr class="c_highlight">` 抽 7 字段（rank/code/name/exchange/limit_up_count_year/eps/float_share_yi/float_mv_yi）
   - 从 `popInfoArr` 拿 analysis 文本（regex 提取 `var popInfoArr = [...];`，按 index 索引）
   - HTTP 401/403 → 返回 `[]`（与现有 boundary signal 一致）
   - HTTP 5xx / 网络失败 → 抛 `DataFetchError`
   - HTML 解析失败（找不到 c_table）→ 抛 `DataFetchError`

3. **新方法 `get_board_news(self, board_code, *, limit=20, board_type=None, **kwargs) -> list[dict]`**：
   - URL 同 stocks_full
   - BeautifulSoup 解析 `<div class="m_box post" id="news">` 下 `<div class="newslist clearfix">`
   - 每个 `<dl>` 抽 6 字段（title/url/publish_date/publish_time/summary/source_domain）
   - `source_domain = "news.10jqka.com.cn"`（常量）
   - `publish_date` 从 URL path `/field/YYYYMMDD/` 提取
   - `rows[:limit]` 截断

4. **新方法 `get_board_surges(self, board_code, *, limit=5, board_type=None, **kwargs) -> list[dict]`**：
   - URL 同 stocks_full
   - BeautifulSoup 解析 `<div class="m_box" id="period">` 下 `<div class="history clearfix">`
   - 每个 `<div class="timeline">` 抽：date / board_change_pct / sh_change_pct / limit_up_count / limit_up_stocks[]
   - 抓第 2 个 `<p class="flexcont" style="display:none;">` 拿完整涨停股列表
   - `rows[:limit]` 截断

5. **`ThsFetcher.supported_data_types` (line 451)**：
   - 现有：`HOT_TOPICS | NORTH_FLOW | NEWS_FLASH | NEWS_SEARCH | STOCK_BOARD | STOCK_NEWS | ANNOUNCEMENT`
   - 改：加 `BOARD_NEWS | BOARD_SURGES`（共 8 个 flag）

6. **`stock_data/data_provider/base.py`**：
   - `DataCapability` enum (line 167) 新增 `BOARD_NEWS = auto()` / `BOARD_SURGES = auto()`
   - `CAPABILITY_TO_METHOD` (line 223) 新增 2 条：`BOARD_NEWS → "get_board_news"`, `BOARD_SURGES → "get_board_surges"`

7. **`stock_data/data_provider/manager.py`**：
   - 新增 `get_board_news(self, board_code, source, limit=20, *, board_type=None)` wrapper
   - 新增 `get_board_surges(self, board_code, source, limit=5, *, board_type=None)` wrapper
   - 模式与现有 `get_board_realtime` (line 1032) 完全相同：`_with_source(source, capability=..., method_name="get_board_news", market="csi", call=lambda f: f.get_board_news(...))`

8. **Tests + Fixtures**：
   - `tests/fixtures/ths_basic_board_885914_full.html` — 用今天保存的 `/tmp/ths_board_html.html` (21299 字节) + playwright 抓到的 90 行 `<tr>` HTML 拼接（dev box 操作）
   - `tests/fixtures/ths_basic_board_885914_news.html` — 单 section HTML（从今天 playwright dump 截取 `.m_box.post#news`）
   - `tests/fixtures/ths_basic_board_885914_surges.html` — 单 section HTML（截取 `.m_box#period`）
   - `tests/test_ths_fetcher_get_board_stocks_full.py` — 单元测试 90+ 解析
   - `tests/test_ths_fetcher_get_board_news.py` — 单元测试 17 条新闻解析
   - `tests/test_ths_fetcher_get_board_surges.py` — 单元测试 5 个月份解析
   - `tests/test_manager_get_board_news_surges.py` — wrapper 转发验证
   - `tests/test_capability_method_map.py` — 加 2 个 flag 的测试

**Phase 2 验证**：
```bash
.venv/Scripts/python.exe -m pytest tests/test_ths_fetcher_get_board_stocks_full.py tests/test_ths_fetcher_get_board_news.py tests/test_ths_fetcher_get_board_surges.py tests/test_manager_get_board_news_surges.py tests/test_capability_method_map.py -v
```

---

### Phase 3: 改 `/boards/{code}/stocks` 走 F10 全量

**目标**：`include_quote=false`（默认）时，`get_board_stocks` 自动改调 `get_board_stocks_full`，90+ 全量回填 stock_board_membership 缓存；`include_quote=true` 行为不变。

1. **`stock_data/data_provider/manager.py::get_board_stocks`** (line 880)：
   - 现有方法签名不变
   - **内部判断新增**：
     ```python
     if not include_quote and source == "ths":
         rows = _with_source(
             source, capability=STOCK_BOARD, market="csi",
             method_name="get_board_stocks_full",
             call=lambda f: f.get_board_stocks_full(board_code, board_type=board_type),
         )
         # rows 形状与 get_board_stocks 不同（无实时行情字段）
         # 路由层负责字段映射
         return rows
     ```
   - **关键问题**：现有 `get_board_stocks` 返回 `list[dict]`，字段是 `BoardStockInfo` 的全集（带 quote 字段）；`get_board_stocks_full` 返回的 dict 缺这些字段，但**多**了 5 个新字段（rank/limit_up_count_year/eps/float_share_yi/float_mv_yi/analysis）
   - **方案 A（推荐）**：返回不同的 dict 集合，路由层在 `include_quote=false` 路径用 `_convert_full_to_stocks_info(rows)` helper 把 `limit_up_count_year → rank` 等映射成统一格式；缺失 quote 字段填 None
   - **方案 B**：让 fetcher 返回统一 shape，full 方法自己填 quote=None。**不推荐** — 引入不必要的 None 字段污染

   选方案 A。

2. **`stock_data/data_provider/persistence/board.py::get_board_stocks`** (line 927) — 缓存回填逻辑：
   - 现有逻辑：`include_quote=true` → 调 fetcher → 写入 stock_board_membership
   - **修改**：`include_quote=false` 路径也调 `get_board_stocks_full` → 写入 stock_board_membership
   - **cache key 不变**（仍按 `(board_code, source)` 索引），因此原 `lazy fill` 行为自动复用

3. **`stock_data/api/schemas.py::BoardStockInfo`** (line 364)：
   - 新增 5 个 optional 字段：
     ```python
     rank: int | None = None
     limit_up_count_year: int | None = None
     eps: float | None = None
     float_share_yi: float | None = None
     float_mv_yi: float | None = None
     analysis: str | None = None
     ```
   - 老客户端读不到这些字段 → 无影响（schema 默认值 None）
   - 新客户端读 `include_quote=false` 时拿到 90+ 只 + 5 个新字段

4. **`stock_data/api/routes/boards.py::get_board_stocks`** (line 415) — 字段映射：
   - `include_quote=false` 时，rows 来自 `get_board_stocks_full`，需要做字段映射：
     ```python
     mapped = [
         BoardStockInfo(
             code=r["stock_code"],
             name=r.get("stock_name", ""),
             exchange=...,
             price=None, change_pct=None, change_amount=None, ...  # 全部 None
             rank=r.get("rank"),
             limit_up_count_year=r.get("limit_up_count_year"),
             eps=r.get("eps"),
             float_share_yi=r.get("float_share_yi"),
             float_mv_yi=r.get("float_mv_yi"),
             analysis=r.get("analysis"),
         )
         for r in rows
     ]
     ```

5. **Tests**：
   - `tests/test_boards.py::test_get_board_stocks*` — 新增 `include_quote=false` 走 F10 的 mock
   - `tests/test_board_stocks_forward_route.py` — 改测试 fixture 路径
   - `tests/test_manager_get_board_stocks_kwargs.py` — 加 `include_quote=false` 路径测试

**Phase 3 验证**：
```bash
.venv/Scripts/python.exe -m pytest tests/test_boards.py tests/test_board_stocks_forward_route.py tests/test_manager_get_board_stocks_kwargs.py -v
```

---

### Phase 4: 新增 `/boards/{code}/news` 和 `/boards/{code}/surges` 路由

**目标**：暴露 2 个新 REST 端点，THS only（v1），`?source=ths` 默认。

1. **`stock_data/api/schemas.py`**：
   - 新增 `BoardNewsItem`：
     ```python
     class BoardNewsItem(BaseModel):
         title: str
         url: str
         publish_date: str
         publish_time: str = ""
         summary: str = ""
         source_domain: str = "news.10jqka.com.cn"
     ```
   - 新增 `BoardNewsResponse`：
     ```python
     class BoardNewsResponse(BaseModel):
         board_code: str
         source: str = "ths"
         total: int
         data: list[BoardNewsItem]
     ```
   - 新增 `BoardSurgeItem`：
     ```python
     class BoardSurgeItem(BaseModel):
         date: str
         board_change_pct: float | None
         sh_change_pct: float | None
         limit_up_count: int
         limit_up_stocks: list[str] = Field(default_factory=list)
     ```
   - 新增 `BoardSurgesResponse`：
     ```python
     class BoardSurgesResponse(BaseModel):
         board_code: str
         source: str = "ths"
         total: int
         data: list[BoardSurgeItem]
     ```

2. **`stock_data/api/routes/boards.py`**：
   - 新增 `/boards/{board_code}/news` 路由：
     - `@router.get` + `@endpoint_meta(capabilities=["BOARD_NEWS"], fetcher_method="get_board_news")` + `@map_errors` + `@cache_endpoint(ttl=1800)`
     - Query: `limit=20` (1-50), `source="ths"` (Literal)
     - 实现：调 `manager.get_board_news(board_code, source, limit)` → 映射成 `BoardNewsResponse`
     - 错误处理：`source != "ths"` → `HTTPException(400, detail={"error": "unsupported_source"})`
   - 新增 `/boards/{board_code}/surges` 路由：
     - `@router_meta(capabilities=["BOARD_SURGES"], fetcher_method="get_board_surges")` + `@cache_endpoint(ttl=3600)`
     - Query: `limit=5` (1-12), `source="ths"`
     - 同样 400 处理

3. **Tests**：
   - `tests/test_boards_news_route.py` — 路由 + schema + source validation
   - `tests/test_boards_surges_route.py` — 同
   - `tests/test_boards_schemas.py` — 新 schema 字段

4. **Manifest sanity**：
   - 启动 server 时 `explorer/__init__.py:_validate_manifest_invariants` 会跑：
     - 验证 `BOARD_NEWS` / `BOARD_SURGES` 在 `CAPABILITY_TO_METHOD`（已加）
     - 验证 `get_board_news` / `get_board_surges` 在 `ThsFetcher` 上（已加）
   - 不应该有 WARNING

**Phase 4 验证**：
```bash
.venv/Scripts/python.exe -m pytest tests/test_boards_news_route.py tests/test_boards_surges_route.py tests/test_boards_schemas.py -v

# 端到端
.venv/Scripts/python.exe -m stock_data.server &
sleep 5
curl -s "http://localhost:8888/api/v1/boards/885914/news?limit=5" | python -m json.tool
curl -s "http://localhost:8888/api/v1/boards/885914/surges?limit=5" | python -m json.tool
curl -s "http://localhost:8888/api/v1/boards/885914/stocks" | python -c "
import json, sys
d = json.load(sys.stdin)
print('count:', len(d.get('stocks', [])))
print('sample:', d['stocks'][0] if d.get('stocks') else None)
"
```

---

## Critical files

**核心文件（重点 review）**：

- `stock_data/data_provider/persistence/board.py` — 25+ 处 `platecode` 重命名，DDL 变更，6 个 reader 函数签名/返回值变化
- `stock_data/data_provider/persistence/board_csv.py` — 列名集合重写，1 个统一 loader
- `stock_data/data_provider/fetchers/ths_fetcher.py` — 3 个新方法，5+ 处字段引用重命名
- `stock_data/data_provider/manager.py` — 1 个新判断分支 + 2 个新 wrapper
- `stock_data/api/routes/boards.py` — 1 个现有路由行为变化 + 2 个新路由
- `stock_data/api/schemas.py` — 5 个新 optional 字段 + 4 个新 model

**复用的现有工具**：

- `ThsFetcher._http_get` (ths_fetcher.py:553) — UA rotation 已实现，新方法直接复用
- `safe_float` / `safe_int` (core/types.py) — 解析 HTML 数字字段
- `stock_data/data_provider/utils/http.py::json_get` — 这次不用（F10 返回 HTML 不是 JSON）
- `@cache_endpoint` (api/cache.py) — 复用 30 min / 1 h TTL
- `manager._with_source` (manager.py:164) — 新 wrapper 直接复用
- `_validate_manifest_invariants` (explorer/__init__.py:91) — 自动验证新 capability

---

## Verification

### 单元测试（dev loop, ~1 min, 不打外网）

```bash
# 全套（按 phase 顺序验证）
.venv/Scripts/python.exe -m pytest

# 重点：capability map 必须包含新 flag
.venv/Scripts/python.exe -m pytest tests/test_capability_method_map.py -v
```

### 集成测试（dev box 上手测，server 启动后）

```bash
.venv/Scripts/python.exe -m stock_data.server &
sleep 5

# 验证 schema 迁移
sqlite3 stock_data/stock_cache.db ".schema stock_board"
# 期望列名: code, cid (不再有 platecode)

# 验证路由
curl -s "http://localhost:8888/api/v1/boards/885914/stocks" | python -c "
import json, sys
d = json.load(sys.stdin)
assert len(d['stocks']) >= 80, f'expected 80+, got {len(d[\"stocks\"])}'
print('stocks count:', len(d['stocks']))
print('has rank field:', 'rank' in d['stocks'][0])
print('has eps field:', 'eps' in d['stocks'][0])
"

curl -s "http://localhost:8888/api/v1/boards/885914/news?limit=3" | python -m json.tool
curl -s "http://localhost:8888/api/v1/boards/885914/surges?limit=3" | python -m json.tool

# 验证 source validation
curl -s "http://localhost:8888/api/v1/boards/885914/news?source=zhitu" -o /dev/null -w "%{http_code}\n"
# 期望: 400

# 验证 explorer manifest
curl -s "http://localhost:8888/control/api-manifest" | python -c "
import json, sys
m = json.load(sys.stdin)
endpoints = [e for s in m['sections'] for e in s['endpoints']]
for ep in endpoints:
    if 'news' in ep['path'] or 'surges' in ep['path']:
        print(ep['path'], '->', ep.get('summary', ''))
"
# 期望: 看到 /boards/{board_code}/news 和 /boards/{board_code}/surges
```

### Live network 测试（CI / 预发布）

```bash
.venv/Scripts/python.exe -m pytest -m live_network
```

### Manifest sanity

```bash
# 启动日志检查
.venv/Scripts/python.exe -m stock_data.server 2>&1 | grep -iE "(board_cache|migrated|exponent|warning|error)" | head -20
# 期望:
#   [BoardCache] Database initialized at ...
#   [BoardCache] added stock_board.cid column ...
#   [BoardCache] renamed stock_board.platecode → code ...
#   无 capability/manifest 警告
```

### CSV 验证

```bash
# 检查 CSV header 和数据迁移正确性
head -3 stock_data/stock_data_backup/stock_board_ths.csv
# 期望: code, name, board_type, subtype, source, cid, updated_at (header)
# data line: 885642, ... 同花顺概念, concept, 同花顺概念, ths, 301558, ... (code=platecode, cid=old code)

head -3 stock_data/stock_data_backup/stock_board_eastmoney.csv
# 期望: code, name, board_type, subtype, source, cid, updated_at (7 列)
# data line: BK1048, 互联网服务, industry, industry, eastmoney, , ... (cid 为空)
```
