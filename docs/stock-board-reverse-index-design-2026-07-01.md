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

**现状**: 读 `stock_board_stock` 表 → fallback 上游。

**改为**: 读新表,无数据时直接调上游并 upsert。新表本身就是正向的,代码结构基本不变,只换数据源函数。

```python
def get_board_stocks(board_code, source, ...):
    rows = stock_board_cache.read_membership(
        board_code=board_code, source=source
    )
    if not rows or refresh:
        rows = manager.get_board_stocks(board_code, source=source)
        if rows:
            stock_board_cache.upsert_membership_bulk(
                board_code=board_code,
                source=source,
                stocks=rows,
                # board_name / board_type / subtype 从 stock_board 表关联得到
            )
    return BoardStocksResponse(...)
```

### 5.2 `/stocks/{stock_code}/boards` (反向,现状 zhitu-only)

**改为**: 所有 source 都支持。优先级三级:

```
① read membership table (本地 < 5ms)
② 若空 + source=='zhitu' → 直接调 fetcher 反向 API 并写表
③ 若空 + 其他 source → 抛 404 + cold_sources 列表,提示调用方主动 ensure
```

```python
def get_stock_boards(stock_code, source):
    rows = stock_board_cache.read_membership(
        stock_code=stock_code, source=source
    )
    if rows:
        return StockBoardsResponse(source='persistence', data=rows)

    if source == 'zhitu':
        rows = manager.get_stock_boards(stock_code, source='zhitu')
        if rows is not None:
            stock_board_cache.upsert_membership_bulk(
                source='zhitu', stocks=rows, board_name=..., board_type=...
            )
            return StockBoardsResponse(source='zhitu', data=rows)

    raise HTTPException(
        404,
        detail={
            'error': 'cold_stock_board_data',
            'message': f'No reverse-index for {stock_code} in {source}. '
                       'Run build_membership_index(source=...) or pass ?ensure=true',
        }
    )
```

### 5.3 新增 `/stocks/{stock_code}/board-memberships` (跨源视图)

一次性返回所有 source 已知数据,带 cold source 提示:

```python
@router.get("/stocks/{stock_code}/board-memberships")
def get_stock_board_memberships(stock_code):
    rows = stock_board_cache.read_membership(stock_code=stock_code)
    by_source = {}
    for row in rows:
        by_source.setdefault(row['source'], []).append({
            'board_code': row['board_code'],
            'board_name': row['board_name'],
            'board_type': row['board_type'],
            'subtype': row['subtype'],
        })
    cold = [s for s in ('eastmoney', 'zhitu', 'zzshare')
            if s not in by_source]
    return {
        'stock_code': stock_code,
        'memberships': by_source,
        'cold_sources': cold,
    }
```

**`cold_sources` 字段是设计契约**: Agent 接到响应就知道"这个 source 没有本地数据",而不是"看起来空所以就没数据"。这是把不完整数据**显式可见化**的关键。

---

## 6. 构建策略

### 6.1 三种触发方式

| 触发 | 入口 | 时机 | 用途 |
|---|---|---|---|
| 运营 CLI | `python -m stock_data.tools.build_membership_index` | 部署后初次 / 周期性 CI | 显式全量构建 |
| API 端 `?ensure=true` | 路由层 cold 路径 | 用户主动 | 单 stock / 单 source 反向构建 |
| 每日定时 | `DailyRefreshTracker` (现有) | 每日 21:00 收盘后 | 增量维护 |

### 6.2 核心函数 (拟,放 `persistence/board.py`)

```python
def build_membership_index(
    source: str | None = None,
    board_type: str | None = None,
    *,
    on_progress: Callable[[int, int], None] | None = None,
    manager=None,
) -> BuildReport:
    """枚举 (source, board_type[, subtype]) → 全 board → 全 stocks →
    批量 upsert 到 stock_board_membership。

    性质:
    - 单 board 失败不中断 (try/except per board)
    - 整批一个 transaction, batch size = 1000
    - 已存在 row 的 refreshed_at = NOW(), 不增不删
    - 上游已不存在的 row 保留 (靠下一次 refresh diff 检测,见 §7)
    """
```

### 6.3 速度预估

| 量 | 估计 |
|---|---|
| EastMoney 概念 board 数 | ~500 |
| 行业 board 数 | ~100 |
| 平均成分股 / board | ~50 |
| 全量行数 / source | ~30000 |
| 上游限速 (EastMoney) | ~1 req/s |

**单 source 首次构建**: ~600 上游调用,10-15 分钟。
**单 source 增量**: 只刷 `refreshed_at > TTL` 的 board,通常 < 5 分钟。

---

## 7. 刷新与失效策略

### 7.1 TTL

```python
SOURCE_INDEX_TTL_HOURS = 24   # env var 可覆盖,默认 24h
```

### 7.2 读路径行为

| 场景 | 行为 |
|---|---|
| 表里有行,且 max(refreshed_at) < TTL | 直接读 |
| 表里有行,但 ≥ 1 行 stale | 行级 UPSERT 刷新,不等完成,先同步快返 |
| 整个 (stock, source) 缺 | 404 + `cold_sources` |
| 整个 `source` 长时间无更新 | API 响应加 `warning` 字段 |

### 7.3 增量 Diff (v1.1 可选)

维护一张轻量 `_membership_snapshot(board_code, source, stock_code_hash)` 协助判定 stock 进出。复杂度高,**v1 不做**,靠 v1 的"每日全量 rebuild"已可接受。

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
| 2. `read_membership` / `upsert_membership_bulk` 函数 + 单测 | `persistence/board.py` | 同上 |
| 3. 路由层切换 `/boards/{code}/stocks` 读新表 | `routes/boards.py` | 同上 |
| 4. 路由层扩 `/stocks/{code}/boards` 到所有 source | `routes/boards.py` | 同上 |
| 5. CLI 工具 `build_membership_index` + README | `tools/build_membership_index.py` | 同上 |
| 6. 挂 `DailyRefreshTracker` | `persistence/board.py` | 同上 |
| 7. 新增 `/stocks/{code}/board-memberships` 跨源视图 | `routes/boards.py` + schemas.py | 同上 |

每步独立可测可回滚。

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
| 首次 build 上游调用多,触发对端限流 | `build_membership_index` 内置 per-board sleep 抖动 (复用 fetcher 层 jitter) |
| 上游数据变更未及时捕获 | 24h TTL + 每日 rebuild,最长 24h 滞后 |
| 老数据未迁移完整就 drop | `--dry-run` 默认 + 差集非空禁止 drop |
| 反范式字段 (board_name) 漂移 | 写表时以本次写入的 board_name 为准,允许临时不一致,下次 refresh 自愈 |
| 多进程并发写同一 source | SQLite WAL + 单 fetcher 进程持有 singleflight (已有 `RLock` 模式) |

---

## 13. 相关记忆

- [[extend-not-spawn-fetcher]]: 给既有 fetcher 加能力,不派生新类——本设计无需修改 fetcher,符合
- [[fixture-must-match-real-upstream]]: 上游真实响应字段 (board_name / subtype 是什么) 必须 probe 后再确认,不在脑里推断
- [[windows-python-taskkill-gotcha]]: 跑 CLI build 工具前确认 8888 端口空闲
