# Stock Board Membership 反向索引 — 实施规格说明

> 日期: 2026-07-01
> 范围: 新增 `stock_board_membership` 反向索引表,让任何 STOCK_BOARD source 都能反查 stock→boards,API 响应 < 10ms,不动 fetcher 层接口。
> 性质: **persistence 层 + 路由层扩展 + 新 CLI 工具**。零 fetcher 侵入,零新 capability,零 v1 定时调度。
> 设计文档: [`docs/stock-board-reverse-index-design-2026-07-01.md`](../../stock-board-reverse-index-design-2026-07-01.md) (578 行,本规格的"完整设计"出处)。
> 评审决议: 见设计文档 §14。

---

## 1. 目标与非目标

### 目标

1. **消除 fetcher 反向能力空缺**:EastMoney / Zzshare 没有 stock→boards 上游 API,通过服务端"正向写入 + 反向读取"构造视图
2. **API 响应 < 10ms (热路径)**:单一 SQLite 索引读,无 JOIN
3. **不动 fetcher 层**:0 新方法、0 新 capability、0 新依赖
4. **冷数据显式可见**:`cold_sources` 字段区分"零数据"与"无数据"
5. **单一真相表**:正向 (`/boards/{code}/stocks`) 与反向 (`/stocks/{code}/boards`) 读同一张表

### 非目标 (v1)

- 跨源 canonical board 映射 (留 v2)
- 同日增量 diff (留 v1.1)
- 定时调度器 (留 v1.1)
- 新增 `STOCK_BOARDS_REVERSE` capability flag (留 v2,需要时再加)
- 跨源 subtype 编码统一 (留 v2)

---

## 2. 数据模型

### 2.1 新表 `stock_board_membership`

```sql
CREATE TABLE IF NOT EXISTS stock_board_membership (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    board_code  TEXT NOT NULL,
    stock_code  TEXT NOT NULL,
    source      TEXT NOT NULL,            -- 'eastmoney' | 'zhitu' | 'zzshare'
    board_name  TEXT NOT NULL,            -- 反范式:避免读时 JOIN stock_board
    stock_name  TEXT NOT NULL,            -- 反范式:避免读时 JOIN stock_list
    board_type  TEXT NOT NULL,            -- 'concept' | 'industry' | 'index' | 'special'
    subtype     TEXT,                     -- source-specific 原始值
    refreshed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(board_code, source, stock_code)
);

CREATE INDEX IF NOT EXISTS idx_membership_reverse
    ON stock_board_membership(stock_code, source);

CREATE INDEX IF NOT EXISTS idx_membership_forward
    ON stock_board_membership(board_code, source);
```

**字段命名规范**:

- `refreshed_at` (membership 表) vs `updated_at` (stock_board / stock_board_stock) — membership 表用 `refreshed_at` 因为只有 refresh 路径会更新,语义更准
- `board_code` / `stock_code` — 同表内需要前缀区分字段

**TTL 语义**: `refreshed_at` 是**所属 board 的最后更新时间**,同一 `(board_code, source)` 下所有 stock 行共享。不存在 row 级 TTL。

### 2.2 表替代关系

| 旧表 | 归宿 |
|---|---|
| `stock_board` | **保留** (board metadata) |
| `stock_board_stock` | **DROP** (数据迁移到新表后,见 §3) |

---

## 3. 实施步骤 (8 个独立 commit)

每个步骤独立可测可回滚。**步骤 3-8 是双写窗口期**。

### Step 1 — 新表 + 自动迁移老数据

**Preflight (在 Step 1 之前)**:

- 新建 memory 文件:
  - `persistence-is-the-only-call-target` (`metadata.type=feedback`,源:评审 Q2)
  - `ttl-is-board-level-not-row-level` (`metadata.type=feedback`,源:评审 v1.1)
  - `daily-refresh-tracker-is-lazy-not-scheduled` (`metadata.type=feedback`,源:评审澄清)
- 更新 `CLAUDE.md`:在 "Key Design Patterns" 段落加上 "Server routes → persistence 唯一入口" 原则

**改动**:
- `stock_data/data_provider/persistence/board.py::init_schema()`:
  - 加 `CREATE TABLE IF NOT EXISTS stock_board_membership (...)` + 两个索引
  - 加探测逻辑:发现老表 `stock_board_stock` 存在则执行 `INSERT OR IGNORE INTO stock_board_membership SELECT ... FROM stock_board_stock JOIN stock_board`

**测试** (`tests/persistence/test_board_membership_migration.py`):
- 冷启动:无老表 → 新表创建成功
- 迁移:`stock_board_stock` 有 100 行 → 迁移后新表有 100 行,字段对齐
- 重复执行幂等:`INSERT OR IGNORE` 不会重复

**Commit**: `feat(persistence/board): add stock_board_membership table + auto-migrate`

### Step 2 — `read_membership` / `upsert_membership_bulk` 函数

**改动** (`persistence/board.py`):

```python
def read_membership(
    board_code: str | None = None,
    stock_code: str | None = None,
    source: str | None = None,
) -> list[dict]:
    """双向查询入口。board_code 与 stock_code 二选一必填。"""

def upsert_membership_bulk(
    source: str,
    stocks: list[dict],       # [{stock_code, stock_name}, ...]
    board_code: str,
    board_name: str,
    board_type: str,
    subtype: str | None,
) -> int:
    """批量 upsert 一整个 board 的所有 stock。返回影响行数。"""
```

**测试** (`tests/persistence/test_board_membership_readwrite.py`):
- `read_membership(board_code=...)` 返回正向列表
- `read_membership(stock_code=...)` 返回反向列表
- `read_membership(board_code=X, source=Y)` 隔离 source
- `upsert_membership_bulk` 新增场景:行不存在 → INSERT
- `upsert_membership_bulk` 更新场景:行已存在 → `INSERT OR REPLACE` 刷新 `refreshed_at`
- `upsert_membership_bulk` 批量:一次 100 行,只 1 次 SQL executemany

**Commit**: `feat(persistence/board): add read_membership + upsert_membership_bulk`

### Step 3 — `update_cached_board_stocks` 双写改造

**改动** (`persistence/board.py::update_cached_board_stocks`):
- 保持原有 INSERT OR REPLACE INTO `stock_board_stock` 逻辑
- **新增**:在同一 transaction 内 INSERT OR REPLACE INTO `stock_board_membership`
- `stock_name` 字段从 `stocks[i].get('stock_name')` 取(forward path 返回的字典已有此字段)

**测试** (`tests/persistence/test_double_write.py`):
- 一次调用,两张表都新增 50 行
- 一次调用,两张表都更新已有行(以 board_code/source/stock_code 为键)
- 双写失败时 transaction 回滚(模拟 stock_board_stock 写入失败)

**Commit**: `feat(persistence/board): dual-write board_stocks to membership table`

### Step 4 — 路由层 `/boards/{code}/stocks` 读新表

**改动** (`persistence/board.py::get_board_stocks`):
- `_read_board_stocks_from_db` 改为 `_read_membership_by_board`(查 membership 表)
- 保留 lazy fill 路径(冷数据时调 fetcher → upsert membership → 返回)
- 验证 forward path 完全等价

**路由层** (`api/routes/boards.py::get_board_stocks`):
- **不变** —— 已经走 `stock_board_cache.get_board_stocks()`,只需 persistence 层改动即可

**测试** (`tests/api/test_board_stocks_forward.py`):
- 集成测试:httpx.AsyncClient + temp SQLite
- 命中:数据库有 50 行,接口返回 50 条 BoardStockInfo
- Cold path:数据库空,mocked manager 返回 30 行 → upsert 后接口返回 30 条
- `?refresh=true` 强制 cold path

**Commit**: `refactor(persistence/board): route forward reads through membership table`

### Step 5 — `/stocks/{code}/boards` 扩到所有 source

**改动** (`api/routes/boards.py::get_stock_boards`):
- 移除 `if source not in ("zhitu",): raise 501` 限制
- 改为:所有 source 走"读 membership → zhitu cold path → 404 + cold_source"
- zhitu cold path 写 membership 时 `stock_name = stock_list_cache.get_stock_name(stock_code) or ''`

**测试** (`tests/api/test_stock_boards_reverse.py`):
- 命中:zhitu 在 membership 表有 5 行 → 返回 5 个 StockBoardInfo,source='persistence'
- 命中:eastmoney / zzshare 在表有数据 → 返回,source='persistence'
- Cold path zhitu:表空 + mocked manager 返回 5 个 board → upsert + 返回 source='zhitu'
- Cold path eastmoney:表空 + non-zhitu → 404 + cold_source=true,message 含 CLI 入口
- Cold path eastmoney:stock_name 在 stock_list 缺 → 兜底空字符串

**Commit**: `feat(api/boards): extend stock->boards reverse lookup to all sources`

### Step 6 — CLI 工具 `build_membership_index`

**改动**:
- **新增** `stock_data/tools/__init__.py`(如不存在)
- **新增** `stock_data/tools/build_membership_index.py`:
  - `build_membership_index(source=None, board_type=None, inter_call_sleep=(1.0, 3.0), on_progress=None, manager=None) -> list[BuildReport]`
  - **Cross-source parallel**:每个 source 独占一个 worker thread (3 sources → 3 threads,顶层 `ThreadPoolExecutor`)。
  - **Intra-source serial**:source 内部 board-by-board 串行 fetch,因为同 client IP 撞同一上游限流,开并发反而有害。
  - 每个 worker thread 独立 sqlite3 connection (WAL 模式允许并发写)。
  - `BuildReport` dataclass:`source, total_boards, success_count, error_count, error_samples, duration_seconds`
- **新增** `stock_data/tools/README.md`:使用说明 + 速度预估

**测试** (`tests/tools/test_build_membership_index.py`):
- Mock fetcher:每个 board 返回固定 stocks,验证 upsert 入库
- Mock fetcher:某个 board 抛异常 → 该 source 报告 error_count=1,其他 board 仍写入
- 多线程:3 source × 5 board,验证总耗时 ≤ 串行的 1/3
- 空 source:`source=None` 枚举 `_VALID_SOURCES`
- inter_call_sleep 范围:[1.0, 2.0] 内随机(不写死)

**Commit**: `feat(tools): add build_membership_index CLI with per-source threading`

### Step 7 — `/stocks/{code}/board-memberships` 跨源视图

**改动**:
- `api/schemas.py`:新增 `BoardMembershipsResponse` (含 `stock_code, memberships: dict[source, list[BoardEntry]], cold_sources: list[str], stale_sources: list[str] | None`)
- `api/routes/boards.py::get_stock_board_memberships`:跨源聚合,过滤 type/subtype,生成 cold_sources 列表
- `_VALID_SOURCES` 从 `routes/boards.py` 动态导入,避免硬编码

**测试** (`tests/api/test_stock_board_memberships.py`):
- 3 source 都有数据 → 返回 3 个 key 的 memberships,cold_sources=[]
- 只有 zhitu 有数据 → cold_sources=['eastmoney', 'zzshare']
- `?type=concept` 过滤 → 只返回 board_type=concept
- `?subtype=热门概念` 过滤 → 只返回 zhitu 热门概念 boards

**Commit**: `feat(api/boards): add cross-source board-memberships view`

### Step 8 — `scripts/migrate_to_membership.py`

**改动**:
- **新增** `scripts/migrate_to_membership.py`:
  - `--dry-run` (默认):打印 `stock_board_stock` 行数、最后写入时间、与 `stock_board_membership` 差集
  - `--execute`:确认差集为空后 `DROP TABLE stock_board_stock`
  - `--force`:跳过差集检查(用于已知一致情况)
- **修改** `persistence/board.py::update_cached_board_stocks`:移除 `stock_board_stock` 写入分支,改为只写 `stock_board_membership`

**测试** (`tests/scripts/test_migrate_to_membership.py`):
- dry-run 打印但不修改
- execute 且差集空 → DROP 成功
- execute 且差集非空 → 拒绝执行
- force → 强制 DROP
- DROP 后 `update_cached_board_stocks` 只写 membership,不再引用 `stock_board_stock`

**Commit**: `chore: drop legacy stock_board_stock table + migrate script`

---

## 4. 跨切关注点

### 4.1 架构原则

**Server 路由 → persistence 唯一入口** (除 `/control/fetcher-test`):

> 此原则的 CLAUDE.md 同步更新放在 Step 1 之前的 preflight 任务 (与新 memory 一起)。

```python
# ✅ 正确
stocks, origin = stock_board_cache.get_board_stocks(board_code, source, manager=manager)

# ❌ 错误:路由层绕过 persistence 直连 fetcher
stocks, origin = manager.get_board_stocks(board_code, source=source)
```

### 4.2 fetcher 调用矩阵

| 入口 | 谁调用 fetcher | 用途 |
|---|---|---|
| 路由层 forward (`/boards/{code}/stocks`) | `persistence.get_board_stocks` lazy fill | 单 board cold fill |
| 路由层 reverse zhitu (`/stocks/{code}/boards`) | `persistence` 调用 `manager.get_stock_boards` (仅 zhitu) | 单 stock cold fill |
| 路由层 cross-source | **不调用 fetcher** | 纯 DB 聚合 |
| `/control/fetcher-test` | 直连 fetcher | Stage 2 调试,不进生产路径 |
| `tools/build_membership_index.py` | per-source worker thread | 全量 bootstrap |

### 4.3 SQLite 配置

- `PRAGMA journal_mode=WAL` 必须开 (`db.py` 已开)
- `PRAGMA busy_timeout=5000` 防偶发 lock
- 每 thread 一个 connection,**不要**共享 sqlite3 connection
- 写入 ~90K 行 / 30 min 远低于 SQLite 上限

### 4.4 测试策略 (确认决议)

- **persistence 单元测试**:temp SQLite + mocked manager
- **路由集成测试**:httpx.AsyncClient + 真实 persistence + mocked fetcher
- **不连真实上游**:符合 CLAUDE.md `live_network` 默认 skip
- 单元测试覆盖率目标:persistence 新增函数 ≥ 90%,路由 ≥ 80%

### 4.5 Commit 策略 (确认决议)

- **8 个独立 commit**,每个步骤一个
- 每个 commit 标题遵循 `<type>(<scope>): <subject>` 格式
- 每个 commit 通过 CI 后再进入下一步

---

## 5. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 首次 build 上游调用多,触发对端限流 | `build_membership_index` 内置 per-source worker 内部 sleep 抖动 (默认 1.0-2.0s);复用 fetcher 层 tenacity 指数退避 |
| 上游数据变更未及时捕获 | 24h TTL 标注 stale (响应 `warning` 字段) + forward-path lazy refresh 覆盖热 board;长尾 board 靠 `?refresh=true` / CLI bootstrap |
| 老数据未迁移完整就 drop | `scripts/migrate_to_membership.py --dry-run` 默认 + 差集非空禁止 drop + `--force` 二次确认 |
| 反范式字段 (board_name / stock_name) 漂移 | 写表时以本次写入值为准,允许临时不一致,下次 refresh 自愈 |
| 多线程并发写 SQLite | 每 thread 一个 connection,WAL 单 writer 串行化,3 thread 写入 ~90K 行无压力 |
| `stock_name` 反查依赖 `stock_list` 表 | zhitu cold path 写 membership 时 `stock_list_cache.get_stock_name(stock_code)` 兜底空字符串 |
| 双写窗口期数据不一致 | `update_cached_board_stocks` 同步写两张表 + 路由层读新表;`--execute` DROP 前必须确认双写逻辑完整 |
| Membership 表单调增长 (无 stale GC) | v1 已知运维债务,~150K 行 / 3 source ≈ < 10MB;v1.1 引入 diff snapshot 时一并解决 |
| Fetcher 整 source 长期不可用 | CLI 末尾打印"X source 最近一次成功 build 时间 > N 天"告警;响应 `warning` 字段携带 stale source 名 |

---

## 6. 验收标准

### 6.1 功能验收

- [ ] `GET /boards/BK1048/stocks?source=eastmoney` 返回成分股列表,首次调用从 fetcher 拉取并 upsert membership,二次调用从 cache 返回 (source='persistence')
- [ ] `GET /stocks/600519/boards?source=eastmoney` 在 membership 表有数据时返回 boards 列表;表为空且 source=zhitu 时调 fetcher 写表后返回;表为空且 source≠zhitu 时返回 404 + cold_source=true
- [ ] `GET /stocks/600519/board-memberships` 返回 3 source 的聚合,`cold_sources` 列出无数据的 source
- [ ] 跨源视图支持 `?type=concept` 和 `?subtype=热门概念` 过滤
- [ ] `python -m stock_data.tools.build_membership_index` 串行跑完 3 source 用时 < 45 min,并行 < 15 min
- [ ] `python scripts/migrate_to_membership.py --dry-run` 显示差集(可能为空)
- [ ] `python scripts/migrate_to_membership.py --execute` DROP 后,`update_cached_board_stocks` 不再引用老表

### 6.2 性能验收

- [ ] 命中 cache 的 `/boards/{code}/stocks` 响应 < 10ms (P95)
- [ ] 命中 cache 的 `/stocks/{code}/boards` 响应 < 10ms (P95)
- [ ] 跨源视图响应 < 20ms (3 source 聚合,P95)
- [ ] 三 source 并行 build 总耗时 < 15 min (per-source worker)

### 6.3 测试验收

- [ ] persistence 单元测试覆盖率 ≥ 90%
- [ ] 路由集成测试覆盖率 ≥ 80%
- [ ] 所有测试通过 (`pytest`,默认 skip `live_network`)
- [ ] `ruff check .` 通过
- [ ] `ruff format .` 通过

### 6.4 数据验收 (运维,本规格不实施)

- [ ] 运维手动运行 `python -m stock_data.tools.build_membership_index` 完成 bootstrap
- [ ] `SELECT COUNT(*) FROM stock_board_membership GROUP BY source` 显示三 source 都有数据
- [ ] `GET /stocks/600519/board-memberships` 返回真实数据,`cold_sources=[]`

---

## 7. 不在本文档范围内的内容

明确**不做**的事,留给未来 v1.1 / v2:

1. **跨源 canonical board 映射** (v2):不构建 `(canonical_id, source, board_code)` 三元映射
2. **同日增量 diff** (v1.1):`_membership_snapshot` 协助判定 stock 进出
3. **定时调度器** (v1.1):cron 21:30 全量 walk ~10-15 min,作为 lazy refresh 兜底
4. **`STOCK_BOARDS_REVERSE` capability flag** (v2):本设计不需要 fetcher 暴露新方法,保留未来扩展空间
5. **跨源 subtype 编码统一** (v2):EastMoney 的 concept vs Zhitu 的 `热门概念` vs Zzshare 的 `同花顺概念` 保留各 source 原始值
6. **stale row GC** (v1.1,和 diff snapshot 一起):v1 不清理上游已删除的 membership 行

---

## 8. 决策日志

| 决议 | 来源 |
|---|---|
| Server 路由 → persistence 唯一入口 | 评审 Q2 (2026-07-01) |
| Lazy fill 封装在 persistence 内部 | 评审 Q2 |
| Per-source worker thread + jittered sleep | 评审 Q3 |
| v1 不引入定时调度器 | 评审 Q4 |
| `cold_sources` 字段保留 | 评审 Q5 |
| 只交付代码,数据由运维手动 bootstrap | 用户 (2026-07-01) |
| Persistence 单元测试 + 路由集成测试 | 用户 (2026-07-01) |
| 每步一个独立 commit (8 commits) | 用户 (2026-07-01) |
| TTL 是 board 级,不是 row 级 | 评审 v1.1 (2026-07-01) |
| `DailyRefreshTracker` 是懒触发,不是定时 | 评审澄清 (2026-07-01) |

---

## 9. 关联记忆

- [[extend-not-spawn-fetcher]]: 给既有 fetcher 加能力,不派生新类
- [[fixture-must-match-real-upstream]]: 上游真实响应字段必须 probe 后再确认
- [[windows-python-taskkill-gotcha]]: 跑 CLI build 工具前确认 8888 端口空闲
- [[persistence-is-the-only-call-target]]: Server 路由 → persistence (新)
- [[ttl-is-board-level-not-row-level]]: TTL 是 board 级时间戳 (新)
- [[daily-refresh-tracker-is-lazy-not-scheduled]]: DailyRefreshTracker 不会主动 walk (新)