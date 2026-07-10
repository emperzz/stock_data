# THS Board + Membership 启动 Backfill — 实施规格说明

> 日期: 2026-07-10
> 范围: 启动时异步 refresh `stock_board`(`source='ths'`) 与 `stock_board_membership`(`source='ths'`)，并移除 `/stocks/{code}/boards` 的 cold-fill 路径
> 性质: **persistence 层 + 路由层 + lifespan startup**。零 fetcher 侵入，零新 capability。
> 状态: 已通过 brainstorming，§1-§5 全部 approved（含两处修改：`BOARD_BACKFILL_ON_STARTUP` 默认 `false`、测试只拉少量 board）。

---

## 1. 背景与动机

### 1.1 现状问题

后启动首次访问 `/boards/{code}/stocks` 会触发对 zzshare/THS 的 `get_board_stocks` 调用，结果写入 `stock_board_membership`（cache row）。

但若 stock `X` 属于多个 board，目前的实现只能反向查回"已 cache 的那些 board"：

```
[+] GET /boards/BK1048/stocks → cache: membership(BK1048, X)
[-] GET /stocks/X/boards → 返 [BK1048]
            ↑ 漏了 X 实际上属于的 BKxxxx / 301558 等其他 board
```

根本原因：`membership` 表是按 board 维度写入的（正向），从未启动过"按 stock 维度反向广播"的全量填充。

### 1.2 设计目标（v1）

1. 启动时异步 backfill THS 维度的 `stock_board` + `stock_board_membership`，让 cache-miss 的反向查询能返完整 board 列表
2. 移除现有 `cold_fill=True` 查询参数；不再在请求路径里冷填
3. 维持现有可测试性：backfill 算法是 sync 函数，可在 unit test 里 mock fetcher 后调用

### 1.3 非目标（v1）

- 不为 zhitu / eastmoney 启动时 backfill（这两个 source 的 reverse 查询仍走 cold-miss 返空路径）
- 不引入定时调度；仅一次性启动（重启重新跑）
- 不修改 cache TTL / membership 写入路径
- 不修改 fetcher 接口

---

## 2. 架构

```
┌──────────────────────────────────────────────────────────────┐
│                      server.py lifespan                       │
│                                                               │
│  ┌───────────────────────┐    ┌─────────────────────────────┐ │
│  │ 现有 trade-calendar   │    │ 读 BOARD_BACKFILL_ON_STARTUP │ │
│  │ warm-up（不动）       │    │         ↓                   │ │
│  └───────────────────────┘    │  asyncio.create_task(        │ │
│                               │    asyncio.to_thread(        │ │
│                               │      run_ths_board_backfill  │ │
│                               │    )                          │ │
│                               │  )                            │ │
│                               └──────────────┬────────────────┘ │
└──────────────────────────────────────────────┼────────────────┘
                                               ▼
                ┌──────────────────────────────────────────┐
                │ stock_data/data_provider/persistence/    │
                │              backfill.py                  │
                │                                          │
                │  Phase 1: stock_board                    │
                │    → fetch_boards_with_zzshare_backfill  │
                │    → update_cached_boards("ths", ...)    │
                │                                          │
                │  Phase 2: stock_board_membership         │
                │    遍历 phase1 的 board                  │
                │      → manager.get_board_stocks(         │
                │          platecode, source="zzshare")    │
                │      → upsert_membership_bulk(          │
                │          source="ths", ...)              │
                └──────────────────────────────────────────┘
                                               │
                  速率: 1.2s/板 (有 token) 或 3.0s/板 (匿名)
```

---

## 3. 模块 API

### 3.1 `persistence/backfill.py`

```python
from dataclasses import dataclass, field
from fastapi import FastAPI  # type: ignore

@dataclass
class PhaseStats:
    duration_s: float = 0.0
    success: int = 0
    errors: int = 0
    error_samples: list[str] = field(default_factory=list)

@dataclass
class BackfillReport:
    phase1: PhaseStats = field(default_factory=PhaseStats)
    phase2: PhaseStats = field(default_factory=PhaseStats)
    phase1_boards_emitted: int = 0    # phase1 输出的 board 行数
    phase2_boards_committed: int = 0  # phase2 实际 upsert 成功的 board 数


def _auto_rate_limit_s() -> float:
    """位置: persistence/backfill.py 模块顶层（私有函数）。

    UNVERIFIED: docs/zzshare/10-rate-limits.md 主表只列
    `plates_rank()` / `market_plate_stocks()` (60/有-token 与 20/匿名),
    未直接列 `plates_stocks()`。下表用 `market_plate_stocks` 的限额
    作 nearest-neighbor 假设（两者均位于 zzshare 板块成分股接口族）。
    上游真实限额未实测;若实测为更严则需要调整常数。
    """
    return 1.2 if os.getenv("ZZSHARE_TOKEN", "") else 3.0


def run_ths_board_backfill(
    manager,
    *,
    inter_call_sleep_s: float | None = None,   # None=auto-detect via _auto_rate_limit_s
    include_quote: bool = False,
    on_progress: Callable[[str, int, int], None] | None = None,
) -> BackfillReport:
    """同步主函数。asyncio 路径: asyncio.to_thread(run_ths_board_backfill, manager)."""


async def schedule_ths_board_backfill_on_startup(app: FastAPI) -> asyncio.Task:
    """asyncio.create_task + asyncio.to_thread 包装。

    Args:
        app: FastAPI app — 用于把 task ref 存到 app.state.backfill_task,
             shutdown 时 lifespan 可 cancel 并 await 它收尾。

    Returns:
        启动的 task。lifespan 调用方负责保留引用以供 cancel。
    """
    app.state.backfill_task = asyncio.create_task(
        asyncio.to_thread(
            run_ths_board_backfill,
            app.state.manager,    # server.py:app.state.manager = _get_manager()
        )
    )
    return app.state.backfill_task
```

### 3.2 关键参数 / 数据流

**Phase 1** — `stock_board`:
- 调用 `fetch_boards_with_zzshare_backfill(board_type=None, refresh=True, include_quote=include_quote, subtype=None, manager=manager)` —— 该函数 **5 个全是 positional**，没默认值；调用必须用 kwarg 后绑定（避免日后再加新 positional 串位）。
- 拿到 `list[dict]`（每个含 `code`, `name`, `type`, `subtype`, `platecode`，platecode 可能 None）。
- **二次 groupby board_type 后调 `update_cached_boards(board_type, source, boards)`**（注意 `update_cached_boards` 第 1 参只接受单一 `board_type`，不是 list）：
  ```python
  from collections import defaultdict
  grouped: dict[str, list[dict]] = defaultdict(list)
  for b in boards_merged:
      grouped[b["type"]].append(b)

  phase1_written = 0
  for bt, bucket in grouped.items():
      if bt in ("concept", "industry"):     # THS 唯一暴露的两种
          phase1_written += update_cached_boards(bt, "ths", bucket)
  ```
  `update_cached_boards` 返回 `int`（写入行数）；aggregate 到 `BackfillReport.phase1.success`。
- 范围预期 ≈850 boards（实测估值，详见 `tools/build_membership_index.py:605 注释`）。
- `fetch_boards_with_zzshare_backfill` 内部对 ThsFetcher 单 type 失败是 `continue` 跳过（`board.py:715-720`）—— 我们不需要重做这个；外层只看 list 总长度。

**Phase 2** — `stock_board_membership`（每板）：
1. 跳过 `platecode is None` 的 board（ths gnSection sidebar-only 行约 88 条；与现有 `_resolve_ths_cid_from_platecode` 的语义一致）。
2. 自己开一个 SQLite 连接 `conn = sqlite3.connect(get_db_path(), timeout=30)` —— 模板抄 [`tools/build_membership_index.py:155-206`](../../stock_data/tools/build_membership_index.py) 的 per-thread 模式。**必须** `try/finally: conn.close()` 兜底，即使 `DataFetchError` 也会走 finally —— 否则一个 task 跑 1000 板累积 1000 个 dangling conn。
3. `conn.execute("PRAGMA journal_mode=WAL")` 一次（文件级持久；与 build_membership_index 同）。
4. 对每板调 `manager.get_board_stocks(board_code=platecode, source="zzshare", include_quote=False)` —— 直接 source-routed 到 zzshare fetcher，避开 ths 的 cid resolution。
5. 返回非空 row 时调 `upsert_membership_bulk(source="ths", stocks=rows, board_code=platecode, board_name=board["name"], board_type=board["type"], subtype=board.get("subtype"), conn=conn)`。`upsert_membership_bulk` 内部 `with conn:` 自动 commit on success。
6. 单 board 任何 `DataFetchError` / `Exception` 吞掉 + 计数（`phase2.errors += 1`，前 20 个错存 `error_samples`），继续下一个；`time.sleep(inter_call_sleep_s)`。
7. Phase 2 结束 → `conn.close()`（在 finally 里）。

> **conn 生命周期总览**：phase 2 入口开 `conn`；phase 2 内每板 try/finally 复用同一 `conn`；phase 2 退出 finally 关闭 `conn`。所有路径都必走 finally。

### 3.3 速率自动检测

`run_ths_board_backfill(inter_call_sleep_s=None)` 时调 `_auto_rate_limit_s()`：

- `1.2s` 对应 ≤50 req/min（**UNVERIFIED nearest-neighbor**：与 `market_plate_stocks()` `plates_rank()` 同 60/20 限额的最坏假设；`docs/zzshare/10-rate-limits.md` 未列 `plates_stocks()` 单独限额）
- `3.0s` 对应 ≤20 req/min（匿名；同样 UNVERIFIED）
- 真实速率需以后续 zzshare 文档实测为准；这里用保守上限。

---

## 4. Env 接入

### 4.1 `.env.example` 新增

```
# === Board cache backfill on startup ===
# When true: at server startup, fully refresh stock_board (THS) and
# stock_board_membership (THS, via zzshare) so /stocks/{code}/boards
# cache-miss responses are complete instead of partial.
# Adds ~17min at startup (rate-limited <=50/min for zzshare; 1/3 the
# anonymous rate). Default disabled — opt in by setting to true.
# BOARD_BACKFILL_ON_STARTUP=false
```

### 4.2 `server.py:lifespan` 修改

**Startup hook** — 在 `app.state.manager = _get_manager()` 之后、`yield` 之前插入：

```python
# ----- THS board backfill on startup (opt-in via env) -----
# Inside function body (not module top) — only loaded when env=true,
# keeps cold-start path zero extra imports.
if os.getenv("BOARD_BACKFILL_ON_STARTUP", "false").lower() == "true":
    from .data_provider.persistence.backfill import (
        schedule_ths_board_backfill_on_startup,
    )
    asyncio.create_task(schedule_ths_board_backfill_on_startup(app))
    logger.info("[Startup] THS board backfill scheduled (BOARD_BACKFILL_ON_STARTUP=true)")
else:
    logger.info("[Startup] THS board backfill skipped (set BOARD_BACKFILL_ON_STARTUP=true to enable)")
```

`asyncio.create_task(...)` 直接返回 task，无需 await——lifespan 内部处于 asyncio loop running 状态，task ref 交给 §6.1 提到的 `app.state.backfill_task` 持有。不需要外层 `asyncio.run`。

**Shutdown hook** — 在 `yield` 之后、现有 `logger.info("Shutting down...")` 前加：

```python
# ----- Cancel in-flight backfill so server shutdown doesn't lose state -----
backfill_task = getattr(app.state, "backfill_task", None)
if backfill_task and not backfill_task.done():
    backfill_task.cancel()
    try:
        await backfill_task
    except (asyncio.CancelledError, Exception) as e:
        logger.info(f"[Shutdown] THS board backfill cancelled ({type(e).__name__})")
del app.state.backfill_task   # 不要悬挂强引用
```

否则 server Ctrl-C / `kill` 时 backfill task 会在途中丢失——已 upsert 的 board 不丢（已 commit），未到的 board 留 `membership` 旧 cache，与本次启动目的不一致。

---

## 5. cold-fill 移除

### 5.1 三处代码改动 + 多处文档 / 测试清扫（一次 commit）

| 文件 / 位置 | 改动 |
|---|---|
| `stock_data/api/routes/boards.py`（约 line 730-740） | 删 `cold_fill: bool = Query(False, ...)` 形参；`get_stock_memberships(...)` 调用去掉 `cold_fill=` kwarg；docstring 删"opt-in cold-fill" |
| `stock_data/data_provider/persistence/board.py:get_stock_memberships` | 删 `cold_fill: bool = False` 形参（约 line 1284）；删 `coldfill_attempted: set[str] = set()`；删**整个** `if cold_fill and manager is not None: for cold_src in (...): ...` 块（约 line 1342-1361）；删 `origin_summary` 决策中的 `coldfill_attempted` 分支（line ~1370-1375）和 `elif cold_fill and manager is not None:` 整块（约 line 1379-1386，删后这部分代码变为不可达，必须删以避免永久死分支）；`from .stock_list import get_stock_name as _get_stock_name` lazy import 也要一并删 |
| 同上 docstring | 删 `cold_fill:` 形参行；删 `cold_fill=True` 描述段；`origin_summary` 列表去掉 `"cold_fill_empty"`，其他保留 |
| `tests/test_boards_api.py:765-794` | cold_fill 用例删除或改为 422 期望 |
| `tests/test_persistence_board_memberships.py:181-244` | cold_fill 用例删除或改为新默认行为预期 |
| `tests/test_stock_boards_reverse_route.py:134-164` | 同上 |
| `tests/test_stock_boards_eastmoney_source.py:5-123` | 同上 |
| `README.md:657` 和 `README.md:662`（如有 cold_fill 行） | 删除 cold_fill Query 描述，更新 cold_sources 字段语义说明 |
| `CLAUDE.md` 中描述 `cold_fill` 的位置（如有） | 删除或更新 |

### 5.2 保留 `cold_sources` 字段语义（无需代码改动）

`StockBoardsResponse.cold_sources` 字段保留。**`get_stock_memberships` 实际行为已经符合新语义**：当 cache-miss（无论 cold_fill 是否启用），`board.py:1368` 的 `cold_sources = [s for s in sources if s not in present_sources]` 持续返回 miss 的 source 名。cold-fill 删除后只是让用户不能**额外**触发 fetcher 调用，cache-miss 报告功能不变。客户端无需改动。

---

## 6. 错误处理 / 遥测

| 场景 | 行为 |
|---|---|
| Phase 1 `fetch_boards_with_zzshare_backfill` 返回 0 board（多因 SDK 不可用 / 无网络） | WARNING；放弃 Phase 2（无 board 可遍历）；返回 `phase1.success=0, phase2.success=0`；最终 INFO 让 operator 看到 |
| Phase 1 `DataFetchError`（罕见；通常内部 per-type 已被吞） | 整个 backfill fail-fast；抛回 `schedule_ths_board_backfill_on_startup` 的 task wrapper，由 §6.1 记 ERROR 后吞 |
| Phase 2 单 board `DataFetchError` / `Exception` | 计数 + WARNING + 取前 20 错误样本存 `phase2.error_samples`，继续下一个 |
| Phase 2 单 board `get_board_stocks` 返回空 | 不写、记 `success`（不算错误；可能是上游真没数据）+ `time.sleep(inter_call_sleep_s)` |
| 总进度 | 每 50 board 打印 `phase2 progress=N/M errors=K elapsed=Xs` |
| 收尾 | 整体结束 INFO：`phase 1 wrote N boards in A s; phase 2 wrote M boards (K errors) in B s` |

### 6.1 asyncio task 异常保护

`schedule_ths_board_backfill_on_startup(app)` 在 task 内部对 `run_ths_board_backfill` 的同步调用做 try/except + `logger.exception`，避免未观察 task 把 asyncio loop 弄乱。task ref 存进 `app.state.backfill_task`，由 lifespan §4.2 shutdown hook cancel + await。

---

## 7. 测试策略

> 关键约束：**测试不跑全量**。unit test mock fetcher；integration test 限定 2-3 个 board。

### 7.1 Unit（`tests/persistence/test_backfill.py`）

**Mock 模板参考**：`tests/test_build_membership_index.py::_make_manager_mock`（构造 `MagicMock`，`mock.get_all_boards.side_effect = lambda **kw: ...`、`mock.get_board_stocks.side_effect = lambda **kw: ...`）。

**Ephemeral SQLite**：`tests/conftest.py` 用 `tmp_path / "test_cache.db"`，通过 `STOCK_CACHE_DB_PATH` env 设置；本测试同样用 tmp_path。

**！重要：`monkeypatch.delenv("ZZSHARE_TOKEN")` 不影响已 import 模块内的 token 读取** —— `_auto_rate_limit_s()` 在 `run_ths_board_backfill` 内调用 `os.getenv(...)` 是函数体内读，可测；但 zzshare fetcher 模块顶部 import 的 token 锁定无法用 delenv 还原。本测试只覆盖 `_auto_rate_limit_s()` 自己，不测 fetcher 行为。

| 用例 | 验证 |
|---|---|
| `test_full_sweep_small` | mock fetcher 返 3 board × 4 stock；run 后 stock_board 4 row、stock_board_membership 12 row |
| `test_skip_platecode_none` | mock 1 个 board `platecode=None`、2 个有 platecode；只 2 个被 phase 2 写 |
| `test_error_continues` | mock 1 个 board 抛 `DataFetchError`、2 个正常；结束时 `phase2.errors=1`、其余 2 个写成功 |
| `test_rate_limit_enforced` | 5 board × 1.2s → `elapsed ≥ 6.0s`（用 `time.monotonic`） |
| `test_rate_limit_no_token` | monkeypatch `delenv("ZZSHARE_TOKEN")`；`_auto_rate_limit_s()` 返 3.0；5 board → `elapsed ≥ 15.0s` |
| `test_phase1_empty_skips_phase2` | mock `fetch_boards_with_zzshare_backfill` 返 `[]`；phase2 不调 fetcher、不写入 |
| `test_idempotent_re_run` | 同 3 board 跑两次；第二次 `phase1.success=3`、`phase2.success=3`，DB row count 仍 = 12（INSERT OR REPLACE 不增 row）—— `refreshed_at` 列已被 CURRENT_TIMESTAMP 刷新（这是预期）|

### 7.2 Integration（`tests/api/test_boards_backfill_integration.py`）

| 用例 | 验证 |
|---|---|
| `test_backfill_then_reverse_lookup` | 启 APP 前 monkeypatch manager 让 phase1 返 2 board、phase2 返 2 stock；启 APP 后 `GET /stocks/{stock_code}/boards?source=ths` 返 ≥ 2 board 全集（不是部分） |

**Ephemeral SQLite fixture order**：`monkeypatch.setenv("STOCK_CACHE_DB_PATH", str(tmp_path))` 必须**先于** `client` fixture 求值——pytest 默认 alphabetic order（`client` 字母在 `monkeypatch` 之后，但 `monkeypatch` 通常作为 function-scope fixture 隐式使用，不参与排序）。**显式做法**：用 `autouse=True, scope="function"` 的 fixture 在测试函数顶部 patch env，不依赖 client 的初始化顺序：

```python
@pytest.fixture(autouse=True)
def _ephemeral_db(tmp_path, monkeypatch):
    monkeypatch.setenv("STOCK_CACHE_DB_PATH", str(tmp_path / "test.db"))
```

> 注：integration test 用 `TestClient` + ephemeral SQLite DB，不会真发 zzshare 请求。

### 7.3 现有测试回归（4 个文件清单）

| 文件 | 行号 | 改动 |
|---|---|---|
| `tests/test_boards_api.py` | 765-794 | cold_fill 用例删除或改为 422 期望 |
| `tests/test_persistence_board_memberships.py` | 181-244 | 同上 |
| `tests/test_stock_boards_reverse_route.py` | 134-164 | 同上 |
| `tests/test_stock_boards_eastmoney_source.py` | 5-123 | 同上 |

---

## 8. 迁移 / 风险

### 8.1 Breaking changes

- `?cold_fill=true` 移除 → 客户端任何强制带此 query 的请求一律 422（FastAPI 默认 unset Query）。可接受，因为 cold_fill 默认 false，启用者本就是少数。
- **CHANGELOG 必填**：标记本行为为 breaking；`README.md` 中描述 cold_fill 的位置（line 657 / 662 表格）需同步删除/更新；`CLAUDE.md` 中描述 `cold_fill=True` 的位置（如有）同步清扫。

### 8.2 行为变化

- ZHITU / EASTMONEY 的 reverse 查询 cache-miss 时不再触发 fetcher 调用。`cold_sources` 持续返回该 source 名 — 客户端原本依赖 cold-fill 的会被这一变化影响，但根据 memory `persistence-is-the-only-call-target`，新行为更符合初衷。

### 8.3 启动开销

- 启用 backfill 后，server 启动延迟 +17min（token）/ 53min（匿名）。Lifespan 的 yield 不会被 block（asyncio task）。
- 量纲：`≈850 boards/source`（实测估值，见 `tools/build_membership_index.py:605` 注释）；token=1.2s/板 × 850 ≈ 1020s ≈ 17min；匿名=3.0s/板 × 850 ≈ 2550s ≈ 43min（注：之前"53min"按 1060 板算的偏悲观，以 850 板计算是 ~43min）。
- `STOCK_DB_INIT=true` 全 DDL 自身耗时几秒，对 17min 没显著影响——不延展数字。

### 8.4 不持久化使用 / 异常路径

- ZZSHARE SDK 不可用（未装 zzshare）：`manager.get_board_stocks` 不抛、返回 `[]`。Backfill 看起来 `phase2.success=N rows` 但实际 board 数 0；phase 1 也可能因 `fetch_boards_with_zzshare_backfill` 内部 fetcher 空返回而 `phase1_boards_emitted=0`，最终整个 task 完成时打印 INFO 让 operator 看到。
- 现有 cache 在 backfill 完成后 `refreshed_at` 会被刷新——**这是设计意图**，不在 migration 路径中过滤 "recent" 行。

### 8.5 Shutdown 行为

- 详见 §4.2 Shutdown hook：Ctrl-C / `kill` / `SIGTERM` → lifespan yield 之后自动 `backfill_task.cancel() + await`，task 抛 `CancelledError`，已 commit 的 board 留住，未到的 board 留旧 cache。
- 不取消的实现会让 task 引用作为 orphan 继续打到 SQLite；既不可观察、也丢失控制权。

---

## 9. 实施步骤（一次 PR，按 commit）

1. `feat(persistence/backfill): add run_ths_board_backfill + schedule_ths_board_backfill_on_startup`
   - 新建 `persistence/backfill.py`（含 `BackfillReport` / `_auto_rate_limit_s` / `run_ths_board_backfill` / `schedule_ths_board_backfill_on_startup`）
   - `tests/persistence/test_backfill.py` 单元测试（7 个用例）
2. `chore(server): wire BOARD_BACKFILL_ON_STARTUP + env-default false`
   - `server.py:lifespan` 接入 startup hook（§4.2 第一段）
   - `server.py:lifespan` 接入 shutdown cancel hook（§4.2 第二段）
   - `.env.example` 加配置项（§4.1）
3. `refactor(boards): drop cold_fill param from /stocks/{code}/boards and get_stock_memberships`
   - 3 处移除冷填（routes.py 形参 + board.py 函数块 + docstring）
   - `tests/` 4 个文件 cold_fill 用例清扫（§5.1 / §7.3 表格）
   - `README.md` cold_fill 文档 / `CLAUDE.md` cold_fill 描述更新（§8.1）
4. `test(api): integration test for backfill → reverse lookup completeness`
   - `tests/api/test_boards_backfill_integration.py` 集成测试
   - 验证：完整 backfill 后 `/stocks/{code}/boards?source=ths` 返全集

---

## 10. 引用

- 旧设计: [`2026-07-08-ths-zzshare-boards-unification-design.md`](2026-07-08-ths-zzshare-boards-unification-design.md) — 统一 THS + zzshare 的 cache 策略
- 旧设计: [`2026-07-01-stock-board-membership-design.md`](2026-07-01-stock-board-membership-design.md) — 反向索引表 design
- 现有 CLI 模板: [`tools/build_membership_index.py`](../../stock_data/tools/build_membership_index.py) — 多源全 sweep 的 loop 模式参考
- 速率权威表: [`docs/zzshare/10-rate-limits.md`](../../zzshare/10-rate-limits.md) — `market_plate_stocks() / plates_rank()` 均为 60/min（with token）/ 20/min（匿名）
- Mock 模板: `tests/test_build_membership_index.py::_make_manager_mock`
- Fixture order 参考: `tests/conftest.py:124-132`
- Memory: `persistence-is-the-only-call-target` — 把 fetcher 调用收紧到 persistence 模块内
- Memory: `daily-refresh-tracker-is-lazy-not-scheduled` — 启动触发 ≠ 调度

