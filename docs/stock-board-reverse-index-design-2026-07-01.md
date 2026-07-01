# 股票→板块反向索引设计 (2026-07-01)

## 背景

当前 `get_stock_boards(stock_code, source)` 反向查询**只有 zhitu 真正可用**——EastMoney / Zzshare fetcher 层没有 stock→boards 的上游 API,Server 端拿到调用只能 `None` 返 404。这导致两条问题:

1. **能力空缺**:Agent (OpenClaw 等) 拿到一只股票后,只能依赖 zhitu 单源答案,EastMoney / Zzshare 各自的板块分类视角完全看不到。
2. **数据不可对齐**:即便有能力,不同 source 对"概念 / 行业"的 `subtype` 体系不一致 (EastMoney 用 concept/industry 二分;Zhitu 用 board_type × subtype 二维,例如 `industry` × `申万行业` / `申万二级` / `证监会行业`)。强行合并会误导下游。

本文档只解决"server 在 fetcher 不暴露反向 API 时如何构造反向数据",**不尝试**统一跨源板块语义 (canonical 映射留作未来 v2)。

---

## 1. 设计目标

| # | 目标 | 反例 (Not-this) |
|---|---|---|
| 1 | 任何 STOCK_BOARD source 都能反查 stock→boards | 仅 zhitu |
| 2 | API 响应 < 10ms (热路径) | 每次 O(boards) 实时枚举 |
| 3 | 不重写 fetcher 层 | 给 EastMoney / Zzshare 加 hidden API 反向方法 |
| 4 | Cold data 显式告知,不静默漏报 | 假装"我查过了,没有" |
| 5 | 单一真相表,正向 / 反向读同一张 | 双表同步问题 |

---

## 2. 当前持久层现状

`stock_data/data_provider/persistence/board.py` 已经维护两张表:

| 表 | 现有字段 | 角色 |
|---|---|---|
| `stock_board` | `(code, name, board_type, subtype, source, updated_at)` | Board metadata + 每 (source, board_type) 缓存 |
| `stock_board_stock` | `(board_code, source, stock_code, stock_name, updated_at)` | Board→Stock 正向关系 |

**关键观察**: `stock_board_stock` 已经是 `get_board_stocks` 的查询路径,每次 forward 请求都会被拉一遍 (走 `daily-refresh-tracker` 自动刷新)。**只要把同一份数据持久化为双向可读,反向查询就不再需要单独构建路径**——这是一切的基础。

---

## 3. 目标 Schema

### 3.1 新表 `stock_board_membership`

```sql
CREATE TABLE IF NOT EXISTS stock_board_membership (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- 维度键 (双索引都用得到)
    board_code  TEXT NOT NULL,
    stock_code  TEXT NOT NULL,
    source      TEXT NOT NULL,            -- 'eastmoney' | 'zhitu' | 'zzshare'

    -- 反范式字段:避免读时 JOIN
    board_name  TEXT NOT NULL,
    stock_name  TEXT NOT NULL,
    board_type  TEXT NOT NULL,            -- 'concept' / 'industry' / 'index' / 'special'
    subtype     TEXT,                     -- source-specific

    refreshed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(board_code, source, stock_code)  -- 同一 (board, source) 里一只股票不重复
);

-- 反向热点索引
CREATE INDEX IF NOT EXISTS idx_membership_reverse
    ON stock_board_membership(stock_code, source);

-- 正向热点索引 (替代原 stock_board_stock 的访问形态)
CREATE INDEX IF NOT EXISTS idx_membership_forward
    ON stock_board_membership(board_code, source);

-- 跨源去重辅助
CREATE INDEX IF NOT EXISTS idx_membership_stock_name
    ON stock_board_membership(stock_code, board_name);
```

### 3.2 保留 `stock_board`

保留 `stock_board` 表 (board-centric metadata)。理由:
- Board-list API 仍需要"所有概念板块"列表,主要按 type / subtype 索引
- Membership 表对纯 board 元数据冗余存储成本可忽略,但单独查询 (不带 stock) 时仍走 `stock_board` 路径更清晰

### 3.3 替代关系

| 旧表 | 新归宿 |
|---|---|
| `stock_board` | **保留** (新增 `membership` 不冲突) |
| `stock_board_stock` | **DROP,数据迁移到 `stock_board_membership`** |

---

## 4. 迁移策略

`init_schema()` 中通过表名探测实现自动迁移,零外部脚本依赖:

```python
def init_schema() -> None:
    ...
    # 1. 探测老表存在
    cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='stock_board_stock'"
    )
    legacy_exists = cur.fetchone() is not None

    # 2. 创建新表 (IF NOT EXISTS)
    cur.execute("CREATE TABLE IF NOT EXISTS stock_board_membership (...)")
    cur.execute("CREATE INDEX IF NOT EXISTS ...")

    # 3. 数据迁移 (仅一次性)
    if legacy_exists:
        cur.execute("""
            INSERT OR IGNORE INTO stock_board_membership
                (board_code, source, stock_code, stock_name,
                 board_name, board_type, subtype, refreshed_at)
            SELECT bs.board_code, bs.source, bs.stock_code, bs.stock_name,
                   COALESCE(b.name, ''),
                   COALESCE(b.board_type, ''),
                   b.subtype,
                   CURRENT_TIMESTAMP
            FROM stock_board_stock bs
            LEFT JOIN stock_board b
              ON b.code = bs.board_code AND b.source = bs.source
        """)

    # 4. 单独管 drop——必须人工触发,不放在 init_schema 自动流程里
    #    见 §10 手动迁移脚本
```

### 为什么 DROP 不放进 init_schema

- SQLite 没有 transactional DDL,DROP TABLE 即丢数据不可回滚
- 老表里有未持久化到新表的临界态数据 (在 init_schema 执行和 INSERT 之间被写入) 的风险
- 实践:把 DROP 包装成 `scripts/migrate_to_membership.py`,带 `--dry-run` 默认值,运维显式执行

---

## 5. API 层改造

`stock_data/api/routes/boards.py` 三处变化:

### 5.1 `/boards/{board_code}/stocks` (正向,已存在)

**路径**: 走 `stock_board_cache.get_board_stocks()` (persistence 层入口):

- 命中 `stock_board_membership` → 直接返回
- 未命中 → persistence 内部调用 `manager.get_board_stocks()` 拉上游 → upsert membership → 返回

**架构原则 (重要)**: Server 路由**不直接**调用 fetcher。所有 fetcher 调用都封装在以下两处:

1. **persistence 层 lazy fill** (cold path, 单次 upstream call 后写表)
2. **CLI 构建工具** (`tools/build_membership_index`, 全量 bootstrap)

这样保证:

- HTTP 请求路径只做 cache read,或在 cold path 走**单次** upstream call (latency 可控,不会突然混入长时间全量构建)
- "冷数据填充策略" (lazy / CLI / 未来定时) 是 persistence 内部决策,路由层不感知
- `manager.*` fetcher API 表面被 persistence 和 CLI 共享,路由层只依赖 `stock_board_cache.*`

```python
# persistence/board.py::get_board_stocks —— 路由层只调这个
def get_board_stocks(board_code, source, refresh=False, include_quote=False, manager=None):
    cached = _read_membership_by_board(board_code, source)
    if cached and not refresh and not include_quote:
        return cached, "persistence"

    if manager is None:
        raise ValueError("manager required on cold path")

    # Lazy fill: 单次 upstream call → upsert membership
    _ = _get_board_type(board_code, source, manager)  # warms stock_board cache
    stocks, origin = manager.get_board_stocks(board_code, source=source, include_quote=include_quote)

    if stocks:
        board_name = _resolve_board_name(board_code, source, manager)
        upsert_membership_bulk(
            board_code=board_code, source=source, stocks=stocks,
            board_name=board_name, board_type=..., subtype=...,
        )
    return stocks, origin
```

### 5.2 `/stocks/{stock_code}/boards` (反向,现状 zhitu-only)

**改为**: 所有 source 都支持。优先级三级:

```
① read membership table (本地 < 5ms)
② 若空 + source=='zhitu' → 单次调 fetcher 反向 API 并写表
③ 若空 + 其他 source → 抛 404 + cold source 提示,告知 CLI 入口
```

```python
def get_stock_boards(stock_code, source):
    # ① 命中 membership
    rows = stock_board_cache.read_membership(stock_code=stock_code, source=source)
    if rows:
        return StockBoardsResponse(source='persistence', data=rows)

    # ② zhitu cold path: 单次上游 API,fetch + 写表
    if source == 'zhitu':
        rows = manager.get_stock_boards(stock_code, source='zhitu')
        if rows is not None:
            # zhitu.get_stock_boards 返回 [{code, name, type, subtype}],
            # 没有 stock_name 字段。从 stock_list 查表补全,反范式写入 membership。
            stock_name = stock_list_cache.get_stock_name(stock_code) or ''
            stock_board_cache.upsert_membership_bulk(
                source='zhitu',
                stocks=rows,                       # 含 board_code/board_name/board_type/subtype
                stock_code=stock_code,
                stock_name=stock_name,             # 来自 stock_list
            )
            return StockBoardsResponse(source='zhitu', data=rows)

    # ③ eastmoney / zzshare 没有 stock→boards 上游 API,
    # server 端无法在请求路径内"对单只股票扫描所有 board" (成本 = 全 source 全 board 拉取)。
    raise HTTPException(
        404,
        detail={
            'error': 'cold_stock_board_data',
            'message': f'No reverse-index for {stock_code} in {source}. '
                       f'Run `python -m stock_data.tools.build_membership_index '
                       f'--source={source}` to populate.',
            'cold_source': True,
        }
    )
```

**`?ensure=true` 设计决策 (不做)**:

- zhitu cold path 不需要 `ensure` 标志 —— 默认就走 cold path (单次 API, <2s)。
- eastmoney / zzshare 即便 `?ensure=true` 也**无济于事**:
  这两个 fetcher 没有 stock→boards 上游 API。
  server 在请求路径无法"为单只股票扫描所有 board" (成本 = 全 source ~600 boards 拉取)。
  `ensure` 在 CLI 工具 (全量 bootstrap) 层面才有意义。
- 因此路由层**不暴露 `?ensure=true`**,改为在 404 detail 中明确告知运维入口。

**注意**: 同一个 `stock_board_cache.upsert_membership_bulk` 调用,§5.1 (forward path) 和 §5.2 (zhitu reverse) 共用。forward path 由 persistence 内部调用,reverse path 在路由层显式调用 (因为 zhitu 走的是 fetcher 的 `get_stock_boards`,不是 `get_board_stocks`)。这条边界要写进 persistence 的 docstring 防止日后被拆。

### 5.3 新增 `/stocks/{stock_code}/board-memberships` (跨源视图)

一次性返回所有 source 已知数据,带 cold source 提示。`type` / `subtype` 过滤参数与 §5.2 单源端点对齐:

```python
@router.get("/stocks/{stock_code}/board-memberships")
def get_stock_board_memberships(
    stock_code: str,
    type: str | None = None,           # 与单源端点对齐
    subtype: str | None = None,        # 与单源端点对齐
):
    rows = stock_board_cache.read_membership(stock_code=stock_code)

    # type / subtype 过滤在 SQL 层完成(走索引)
    if type is not None:
        rows = [r for r in rows if r['board_type'] == type]
    if subtype is not None:
        rows = [r for r in rows if r['subtype'] == subtype]

    by_source = {}
    for row in rows:
        by_source.setdefault(row['source'], []).append({
            'board_code': row['board_code'],
            'board_name': row['board_name'],
            'board_type': row['board_type'],
            'subtype': row['subtype'],
        })
    # 动态从 _VALID_SOURCES 读,避免硬编码未来新 source
    from .boards import _VALID_SOURCES
    cold = [s for s in _VALID_SOURCES if s not in by_source]
    return {
        'stock_code': stock_code,
        'memberships': by_source,
        'cold_sources': cold,
    }
```

**`cold_sources` 字段是设计契约**: Agent 接到响应就知道"这个 source 没有本地数据",而不是"看起来空所以就没数据"。即使默认走 persistence,这字段仍**必需**:

- membership 表是**增量**构建的 (lazy fill + CLI bootstrap),一只股票没被任何 board→stocks 查询引用过、也没在 bootstrap 范围内,该 source 自然为空
- 区分"零数据 = stock 真的不属于任何 board" vs "零数据 = 我们没查过"对 agent 决策至关重要
- 这条契约在 §1 设计目标 #4 (cold data 显式告知) 已经声明

**注意**: `cold_sources` 与"该 source 长时间未刷新"是两个不同的概念。后者是"有过数据但 stale",前者是"从未有过数据"。两者通过响应中的 `stale_sources: list[str]` 字段区分 (v1.1 加,v1 暂用 404 detail 文字说明)。

---

## 6. 构建策略

### 6.1 三种触发方式 (v1)

| 触发 | 入口 | 时机 | 用途 |
|---|---|---|---|
| 运营 CLI | `python -m stock_data.tools.build_membership_index` | 部署后初次 / 周期性 CI | 显式全量构建 / 重 bootstrap |
| Lazy refresh (现有 `DailyRefreshTracker`) | 路由层 persistence 入口 | 用户首次调用某 (board_type, source) 当日 | 已查询的 board 数据当日刷新一次 |
| API 端 `?refresh=true` | `/boards/{code}/stocks?refresh=true` | 用户主动 | 单 board 强制重拉上游 |

**v1 不引入定时调度器 (apscheduler / cron)**:

- 板块和板块成分股变化**不频繁**:
  - 概念板块:每日 ~1-5% 股票进出 (变化较快)
  - 行业板块 (申万 / 同花顺):月级别变化,日级别 rebuild 浪费
  - 指数成分股:季度级别变化
  - 题材 / 特殊板块 (风险警示 / 次新股):日级别
- **热 board 已被 forward-path 查询覆盖**:任何被 agent 主动查过的 board 都会走 lazy refresh,数据保鲜。
- **长尾 board** (从未被查询):靠 `?refresh=true` 或运维 CLI bootstrap 触发。属于已知运维债务。
- v1.1 (可选) 才考虑加 cron 21:30 全量 walk:预估 10-15 分钟 (并行后),作为兜底。

> 旧版本草稿曾计划"挂 DailyRefreshTracker 每日 21:00 增量维护"。经评审澄清:`DailyRefreshTracker.is_first_call(key)` 是基于"first call" 的懒触发,**不会**主动 walk 所有 board。如果需要真正的定时调度,必须引入外部触发 (apscheduler / cron),不在 persistence 层职责范围内。

### 6.2 核心函数 (拟,放 `tools/build_membership_index.py`)

**多线程模型** (per-source worker):

```python
def build_membership_index(
    source: str | None = None,                  # None = 全部 source
    board_type: str | None = None,
    *,
    inter_call_sleep: tuple[float, float] = (1.0, 2.0),  # jitter [min, max] seconds
    on_progress: Callable[[str, int, int], None] | None = None,  # (source, done, total)
    manager=None,
    max_workers_per_source: int = 1,            # 默认 1 (保守);可调到 2-3 看上游限速
) -> BuildReport:
    """枚举 (source, board_type[, subtype]) → 全 board → 全 stocks → 批量 upsert。

    线程模型:
    - 每个 source 一个 worker thread (3 source → 3 thread)
    - 每个 thread 内部:enumerate boards → fetch → sleep jitter → upsert → 下个 board
    - 每个 thread 用自己的 sqlite3 connection (SQLite WAL 允许多 connection)
    - Main thread join 所有 worker,汇总进度,返回 BuildReport
    - 整个进程 ~10-15 分钟完成全 source 全量 (3 source 并行)

    Inter-call sleep:
    - Per (source, call_type) 独立 jitter,默认 1.0-2.0s,尊重上游 ~1 req/s 限速
    - 不同 source 的 worker sleep 独立,source 间不互相干扰
    - EastMoney / Zzshare / Zhitu 限速不同 (probe 后填具体值),后续可配 env var

    错误处理:
    - 单 board 失败 → log warning, continue (不中断整个 source)
    - SQLite 写入失败 → log error, continue, 但 BuildReport 记录错误数
    - 上游限速 (429/503) → 指数退避 (复用 fetcher 层 tenacity 配置)

    事务边界:
    - 每个 board 一个 transaction (整 board 的 stocks 一批提交)
    - 不要做大 batch transaction:失败时 rollback 粒度太粗
    - 已存在 row 的 refreshed_at = NOW() (用 INSERT OR REPLACE 即可)
    - 上游已不存在的 row 保留:v1 不做 stale-row 清理 (见 §7.3)
    """
```

**SQLite 并发注意事项**:

- `PRAGMA journal_mode=WAL` 必须开 (本项目已开,见 `db.py`)
- `PRAGMA busy_timeout=5000` 防止"database is locked"
- 每 thread 一个 connection,**不要**共享 connection (sqlite3 connection 不是线程安全的)
- 写入天然串行化 (WAL 单 writer),但 ~90K 行 / 30 分钟远低于 SQLite 上限

**为什么不按 board 并行 (ThreadPoolExecutor per board)**:

- 上游限速 ~1 req/s,10 worker 并发 = 10 req/s 直接被风控
- SQLite 写锁竞争加剧 (虽然 WAL 缓解)
- 进度汇报复杂 (per-board completion)
- per-source 单 worker 已经把 30-45 min 缩到 10-15 min,边际收益不大

### 6.3 速度预估

| 量 | 估计 |
|---|---|
| EastMoney 概念 board 数 | ~500 |
| EastMoney 行业 board 数 | ~100 |
| Zhitu 行业 + 概念 + 指数 board 数 | ~500 |
| Zzshare 概念 + 行业 + 题材 board 数 | ~500 |
| 平均成分股 / board | ~50 |
| 全量行数 / source | ~30000 |
| 上游限速 (各 source) | ~1 req/s |

**单 source 首次构建** (单线程): ~600 upstream calls × ~1.5s jitter = ~10-15 分钟。
**三 source 首次构建** (per-source 线程并行,见 §6.2): max(各 source) ≈ **10-15 分钟** (从 30-45 min 压缩)。

> 注:并行带来的收益受限于"最慢那个 source"。EastMoney 没有"全概念一次性拉"接口,只能 board-by-board 拉。如果未来某个 source 提供 bulk API,可再压缩。
> v1 内置 per-source threading (见 §6.2),无需运维手动编排。

---

## 7. 刷新与失效策略

### 7.1 TTL

```python
SOURCE_INDEX_TTL_HOURS = 24   # env var 可覆盖,默认 24h
```

**TTL 是 board 级,不是 row 级**:

- `refreshed_at` 字段记录的是**所属 board 的最后更新时间** (即最后一次 upsert 该 board 所有 stocks 的时间)
- 同一 `(board_code, source)` 下所有 stock 行共享这个 timestamp
- 不存在"row 级 TTL" —— membership 行的写入总是 batch per-board,粒度天然是 board

### 7.2 读路径行为

读路径不做 TTL 同步判断:命中 membership 表就直接返回,**不**在请求路径内做 staleness check (那是浪费)。

TTL 的实际意义是**运维指标 + 触发刷新**:

| 场景 | 行为 | 触发谁去刷新 |
|---|---|---|
| (stock, source) 在 membership 表里 | 直接读,立即返回 | — |
| (stock, source) 缺 | 404 + `cold_source: true` | CLI bootstrap (§6.1) |
| (stock, source) 在表里,但其所属 board 整体 stale (> TTL) | 仍直接读 | 下次 forward `/boards/{code}/stocks` 调用触发 lazy refresh,或 `?refresh=true` 强制 |
| 整个 source 长时间无更新 | API 响应加 `warning` 字段 | 运维告警;不阻塞读 |

**为什么不在读路径做 staleness check**:

- TTL 检查 = SQL `MAX(refreshed_at) GROUP BY board_code`,每次读都做是浪费
- 真正需要刷新时,forward path (§5.1) 已经自动 lazy refresh,无需读路径介入
- Reverse path (§5.2) 的 zhitu cold path 也是"先看表,空就拉",没空也走 zhitu 直接拉,绕过 stale 概念

### 7.3 增量 Diff 与 stale row 清理 (v1.1 可选)

维护一张轻量 `_membership_snapshot(board_code, source, stock_code_hash)` 协助判定 stock 进出。复杂度高,**v1 不做**,靠 v1 的"运维触发 + lazy refresh"已可接受。

**v1 的已知运维债务**:

- membership 表单调增长 (永远不删除已不存在的 stock-board 关系)
- 实际影响可忽略:A 股 ~5000 只 × 3 source × ~10 boards 平均 = ~150K 行,在 SQLite 上是 < 10MB
- 实际刷新时,`INSERT OR REPLACE` 已经能处理"上游少了这只股"的情况 —— 但被删的旧 row 还留着,直到整 board 重写
- **v1.1 引入 diff snapshot** 时,顺便加 stale row GC

---

## 8. 对 fetcher 层的零侵入

| Fetcher | 反向 API | 改造 |
|---|---|---|
| ZhituFetcher | `get_stock_boards(stock_code)` 原生 | **不变**,只在 cold 路径 fallback 用,结果写新表 |
| EastMoneyFetcher | 无 | **不变**,继续提供 `get_all_boards` + `get_board_stocks`,写入新表后即可被反查 |
| ZzshareFetcher | 无 | 同 EastMoney |
| 其他 (无 STOCK_BOARD capability) | — | 不涉及 |

**关键事实**: 新表写入不依赖 fetcher 是否暴露反向方法,所有 source 都被同一路径处理。Server 端"反向能力"是通过"所有 source 都走的正向 + 服务端 JOIN"实现的,这就是本设计的核心。

---

## 9. 上手顺序 (分阶段独立 commit)

| 步骤 | 改动 | 回滚粒度 |
|---|---|---|
| 1. 新表 + 自动迁移老数据 | `persistence/board.py` + 单测 | revert commit 即可 |
| 2. `read_membership` / `upsert_membership_bulk` 函数 + 单测 (含 stock_name 反查) | `persistence/board.py` | 同上 |
| 3. `update_cached_board_stocks` 改造:**双写**到 `stock_board_stock` + `stock_board_membership` | `persistence/board.py` | 同上 |
| 4. 路由层 `/boards/{code}/stocks` 读新表 (lazy fill 仍保留,封装在 persistence 内) | `persistence/board.py` + `routes/boards.py` | 同上 |
| 5. 路由层 `/stocks/{code}/boards` 扩到所有 source (zhitu cold path + 404 detail 提示 CLI) | `routes/boards.py` | 同上 |
| 6. CLI 工具 `build_membership_index` (含 per-source threading) + README | `tools/build_membership_index.py` | 同上 |
| 7. 新增 `/stocks/{code}/board-memberships` 跨源视图 (含 type/subtype 过滤) | `routes/boards.py` + `schemas.py` | 同上 |
| 8. `scripts/migrate_to_membership.py` 验证差集 → DROP 老表 | `scripts/` | 同上 |

每步独立可测可回滚。**步骤 3-8 期间是双写窗口期**:`stock_board_stock` 和 `stock_board_membership` 同时接收写入,读路径已切换到新表。`--execute` DROP 后,`update_cached_board_stocks` 调用方改为 `upsert_membership_bulk`,移除双写逻辑。

> **关于"挂 DailyRefreshTracker"** (旧草稿步骤 6):经评审澄清,v1 不引入定时调度器,无需此步。Lazy refresh 已由现有 `DailyRefreshTracker.is_first_call(key)` 提供,覆盖热 board。v1.1 才考虑加 cron 全量 walk。

---

## 10. 手动迁移脚本 (草案)

`scripts/migrate_to_membership.py`:

```python
"""Drop legacy stock_board_stock after verification.

Usage:
    python scripts/migrate_to_membership.py --dry-run   # 检查
    python scripts/migrate_to_membership.py --execute   # 实际 drop
"""
```

行为:
- `--dry-run` (默认): 打印 `stock_board_stock` 行数、最后写入时间、与 `stock_board_membership` 的差集
- `--execute`: 确认差集为空后 `DROP TABLE stock_board_stock`
- 二次确认 prompt:检测到非空差集时不执行,要求用户显式 `--force`

---

## 11. 不在本文档范围内的内容

明确**不做**的事,留给未来 v2 决定:

1. **跨源 canonical board 映射**: 不构建 `(canonical_id, source, board_code)` 三元映射。理由:维护成本高、动态变化频繁、本地推理价值低。如果 agent 真实需要"两只股票在 EastMoney 是不是都属于'半导体'概念",让其在前端自己做字符串比对即可。
2. **实时 (同日) 增量 diff**: 同上成本/收益不划算,每日 full rebuild 已足够。
3. **改 `CAPABILITY_TO_METHOD`**: 不新增 `STOCK_BOARDS_REVERSE` capability flag。理由:本设计不需要 fetcher 暴露任何新方法,不引入新 capability 反而保持 fetcher 层接口稳定。如果未来某个 fetcher 真的暴露了原生反向 API,再单独加 flag。
4. **统一 subtype 编码**: EastMoney 的 concept vs Zhitu 的 `热门概念` vs Zzshare 的 `同花顺概念` 不在本设计中合并。`membership` 表保留每个 source 自己的 `subtype` 字符串原始值。

---

## 12. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 首次 build 上游调用多,触发对端限流 | `build_membership_index` 内置 per-source worker 内部 sleep 抖动 (默认 1.0-2.0s);复用 fetcher 层 tenacity 指数退避 |
| 上游数据变更未及时捕获 | 24h TTL 标注 stale (响应 `warning` 字段) + forward-path lazy refresh 覆盖热 board;长尾 board 靠 `?refresh=true` / CLI bootstrap |
| 老数据未迁移完整就 drop | `scripts/migrate_to_membership.py --dry-run` 默认 + 差集非空禁止 drop + `--force` 二次确认 |
| 反范式字段 (board_name / stock_name) 漂移 | 写表时以本次写入的值为准,允许临时不一致,下次 refresh 自愈;v1.1 引入 diff snapshot 时同步加 stale row GC |
| 多线程并发写 SQLite | 每 thread 一个 connection (`PRAGMA journal_mode=WAL` + `busy_timeout=5000` 已开);SQLite WAL 单 writer 串行化,3 thread 写入 ~90K 行无压力 |
| `stock_name` 反查依赖 `stock_list` 表 | zhitu cold path 写 membership 时 `stock_list_cache.get_stock_name(stock_code)` 兜底空字符串;stock_list 自身有 auto-refresh,空值概率极低 |
| 双写窗口期 (DROP 前) 数据不一致 | `update_cached_board_stocks` 同步写两张表 + 路由层读新表;`--execute` DROP 前必须确认双写逻辑完整 |
| Membership 表单调增长 (无 stale GC) | v1 已知运维债务,~150K 行 / 3 source ≈ < 10MB,可忽略;v1.1 引入 diff snapshot 时一并解决 |
| Fetcher 整 source 长期不可用 (如 eastmoney 503) | CLI 末尾打印"X source 最近一次成功 build 时间 > N 天"告警;响应 `warning` 字段携带 stale source 名 |

---

## 13. 相关记忆

- [[extend-not-spawn-fetcher]]: 给既有 fetcher 加能力,不派生新类——本设计无需修改 fetcher,符合
- [[fixture-must-match-real-upstream]]: 上游真实响应字段 (board_name / subtype 是什么) 必须 probe 后再确认,不在脑里推断
- [[windows-python-taskkill-gotcha]]: 跑 CLI build 工具前确认 8888 端口空闲
- [[persistence-is-the-only-call-target]]: Server 路由 → persistence,绝不直连 fetcher (除 `/control/fetcher-test`);所有 fetcher API 调用由 persistence lazy fill / CLI bootstrap 封装
- [[ttl-is-board-level-not-row-level]]: TTL 是 board 级时间戳,不是 row 级;同一 board 下所有 stock 行共享 `refreshed_at`
- [[daily-refresh-tracker-is-lazy-not-scheduled]]: `DailyRefreshTracker.is_first_call(key)` 是懒触发,不主动 walk;真要定时调度必须引入 cron / apscheduler

---

## 14. 评审决议 (2026-07-01)

本节记录 v1 设计 review 阶段讨论的关键问题与最终决议,作为后续实施的"决策日志"。

### Q1: 所有查询都应优先走 persistence?

**决议**: 是。所有读路径 (forward / reverse / cross-source) 默认查 membership 表,无命中再走 cold path。

**澄清的架构原则**: Server 路由**不直接**调用 fetcher。fetcher API (`manager.*`) 只被两个 caller 消费:

1. `persistence/board.py` 的 lazy fill (单次 upstream call → upsert)
2. `tools/build_membership_index.py` (CLI bootstrap)

除 `/control/fetcher-test` (Stage 2 调试端点) 外,任何业务路由都不应直连 fetcher。

### Q2: server API 是否仍保留 fetcher 调用? 完全分离 vs 暂时兼容?

**决议**: **保留 lazy fill,封装在 persistence 内部**。理由:

| 选项 | 优点 | 缺点 |
|---|---|---|
| 完全分离 (server 不调 fetcher) | 请求路径 latency 稳定;架构最清晰 | 首次请求永远 404,UX 差;`?refresh=true` 失效 |
| 暂时兼容 (server 直连 fetcher) | 首次可用;`?refresh=true` 有效 | HTTP 路径偶尔混入慢请求;fetcher 被两处调用,难追溯 |
| **采用: 折中 (本次决议)** | lazy fill 仍走 fetcher,但封装在 persistence 层 | 需要在 persistence docstring 写清边界,防止路由层绕过 |

**结论**: 不完全分离也不放开直连。`stock_board_cache.get_board_stocks()` 是路由唯一入口,内部决策"命中直接返 / 未命中 lazy fill"。`manager.get_board_stocks()` 只在 persistence 和 CLI 中被调用。

### Q3: 构建工具是否多线程 + 调用间隔?

**决议**: 是。Per-source worker thread,每个 worker 内部 jittered sleep (默认 1.0-2.0s)。

- **不要** per-board 线程池 (会撞上游限速)
- 每 thread 一个 sqlite3 connection (WAL 模式已开,允许)
- `PRAGMA busy_timeout=5000` 防止偶发 lock
- 进度汇报:`on_progress(source, done, total)` callback
- 错误隔离:单 board 失败 → log + continue,不中断 source 整体

### Q4: 板块 / 成分股更新是否需要每日定时?

**决议**: **v1 不引入定时调度器**。理由:

- 行业 / 指数板块变化以**月 / 季度**为单位,日 rebuild 是浪费
- 概念 / 特殊板块变化以**日**为单位,但 lazy refresh 已覆盖 (任何被查询的 board 当日首调触发 refresh)
- 长尾 board (从未被查询) 是已知运维债务,靠 `?refresh=true` 或 CLI bootstrap 兜底
- v1.1 可加 cron 21:30 全量 walk (~10-15 min,per-source 线程并行)

**澄清的误解**: 旧草稿 §6.1 写的"挂 DailyRefreshTracker 每日 21:00 增量维护"经评审澄清是错的——`DailyRefreshTracker.is_first_call(key)` 是**懒触发**语义,不会主动 walk 所有 board。如果未来真要"21:00 全量扫一遍",必须引入 `apscheduler` / 外部 cron,不在 persistence 层职责范围内。

### Q5: 默认走 persistence 后,`cold_sources` 字段是否还需要?

**决议**: **仍必需**。即使读路径只查 cache,`cold_sources` 仍区分两种语义:

- "这个 stock 真的不属于任何 board" (该 source 在表里有数据,且此 stock 不在其中)
- "我们对这个 source 的这只 stock 没数据" (该 source 在表里没数据,需 bootstrap)

Agent 必须能区分这两种情况才能正确决策。`cold_sources` 是把"不完整数据**显式可见化**"的契约,与 §1 设计目标 #4 一致。

### Q6 (后续澄清): 双写窗口期管理

**决议**: 步骤 3-8 期间是双写窗口期。`update_cached_board_stocks` 同步写 `stock_board_stock` + `stock_board_membership`,读路径已切换到新表。`scripts/migrate_to_membership.py --execute` DROP 后,调用方改为 `upsert_membership_bulk`,移除双写逻辑。DROP 前必须确认差集为空 + 双写覆盖完整,见 §10。
