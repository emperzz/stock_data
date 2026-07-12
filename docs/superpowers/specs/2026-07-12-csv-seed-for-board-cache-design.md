# Board Cache CSV Seed — 设计规格

> 日期: 2026-07-12
> 范围: 在 `STOCK_DB_INIT=true` 时,从 `stock_data_backup/` 加载 CSV 备份到 `stock_board` 和 `stock_board_membership`,与 `BOARD_BACKFILL_ON_STARTUP=true` 的上游 backfill 解耦
> 性质: **persistence 层 + lifespan startup + 文件结构**。零 fetcher 侵入,零 capability 改动
> 状态: 已通过 brainstorming,§1-§6 全部 approved

---

## 1. 背景与动机

### 1.1 现状问题

当前启动流程中,持久层数据完全依赖两种途径建立:
- **运行时被动填充**: 路由 cold-miss 时调 fetcher 写缓存
- **主动 backfill**: `BOARD_BACKFILL_ON_STARTUP=true` 时跑 `run_ths_board_backfill`,调用 THS + zzshare 上游拉 ~17 分钟

这意味着:
1. **首次部署 / STOCK_DB_INIT=true 重置** → DB 是空的,所有 cache-miss 都要现调 upstream,冷启动慢
2. **网络受限环境**(开发箱无法访问 zzshare / ths 上游) → 即使 `BOARD_BACKFILL_ON_STARTUP=true` 也拉不到数据,DB 始终空
3. **开发箱多次重置** → 每次都要重跑 17 分钟才能用

### 1.2 设计目标 (v1)

1. 提供 **静态 CSV 备份机制**: repo 里 version-control 3 个 CSV 文件,作为 DB 的可重现起点
2. 让 `STOCK_DB_INIT=true` **同时** 做两件事: drop tables + load CSVs (而不是只 drop)
3. 让 `BOARD_BACKFILL_ON_STARTUP=true` 仍是可选: 若用户想保留 CSV 数据而不被上游覆盖,关掉它即可
4. CSV loader 是 **独立的纯函数**,可在单测中独立验证,不需要启 server

### 1.3 非目标 (v1)

- 不支持 CSV 增量 diff / merge(全量 INSERT OR REPLACE,够用)
- 不做 schema 版本号 (CSV 没 version 字段;加就是过度工程)
- 不做 CSV 压缩 / 加密 (本地仓库 < 1MB,无安全需求)
- 不进 wheel(`pyproject.toml` 的 `force-include` 不动;CSV 是 repo-managed backup,不是运行时依赖)
- 不为 zhitu / zzshare 做 CSV backup (目前只有 THS 和 eastmoney 有现成数据)

---

## 2. 架构

```
┌──────────────────────────────────────────────────────────────────────┐
│                       server.py lifespan                              │
│                                                                       │
│  STOCK_DB_INIT=true?  ─yes→  persistence.reset_all()                 │
│                              ↓                                        │
│                              board_csv.seed_all_from_backup_dir(     │
│                                  Path(__file__).parent /             │
│                                  "stock_data_backup")                │
│                              ↓ (按 source 单独 log + skip 缺文件)   │
│                                                                       │
│  BOARD_BACKFILL_ON_STARTUP=true?  ─yes→ schedule_ths_board_backfill() │
│                                    ↑                                  │
│                                    └─ 仍调 upstream (~17min)         │
└──────────────────────────────────────────────────────────────────────┘
         │
         ▼
┌──────────────────────────────────────────────────────────────────────┐
│  stock_data/data_provider/persistence/board_csv.py  (新)             │
│                                                                       │
│  • seed_stock_board_from_csv(source, csv_path) -> int                  │
│  • seed_membership_from_csv(csv_path) -> int                          │
│  • seed_all_from_backup_dir(backup_dir) -> {filename_stem: count}     │
│  • 内部用 csv 标准库 + sqlite3 直接 INSERT OR REPLACE                 │
└──────────────────────────────────────────────────────────────────────┘
         │
         ▼
┌──────────────────────────────────────────────────────────────────────┐
│  stock_data/stock_data_backup/  (新目录,git force-add)               │
│                                                                       │
│  • stock_board_ths.csv                                                 │
│       cols: code, name, board_type, subtype, source, platecode,       │
│             updated_at                                                │
│  • stock_board_membership_ths.csv                                     │
│       cols: board_code, stock_code, source, board_name, stock_name,   │
│             board_type, subtype, refreshed_at                         │
│  • stock_board_eastmoney.csv  (重命名自 boards_akshare_name_em.csv)  │
│       cols: board_type, board_code, board_name  (3 列,loader 填默认)  │
└──────────────────────────────────────────────────────────────────────┘
```

### 关键决策

- **顺序固定**: 即使同时开两个 flag,顺序也是 `reset → seed CSV → backfill upstream`。CSV 提供立即可用的 seed,backfill 之后用上游数据覆盖。
- **两个 flag 完全独立**: 可单独开。`STOCK_DB_INIT=false` + `BOARD_BACKFILL_ON_STARTUP=true` 仍可跑(只跑 upstream);反之亦然。
- **CSV seed 在 `lifespan` 同步阶段跑**(不 task),让重置 → 加载 → 立刻生效,再异步启 backfill。

---

## 3. 数据契约

### 3.1 `stock_board_ths.csv` (7 列)

```csv
code,name,board_type,subtype,source,platecode,updated_at
885001,煤炭,industry,同花顺行业,ths,881001,2026-07-12 17:30:00
885002,白酒,concept,同花顺概念,ths,885002,2026-07-12 17:30:00
```

| 列 | 类型 | 来源 | 说明 |
|---|---|---|---|
| `code` | TEXT NOT NULL | THS `cid` | 概念用 `885xxx`,行业用 `881xxx` |
| `name` | TEXT NOT NULL | THS `name` | 中文名 |
| `board_type` | TEXT NOT NULL | `concept` / `industry` | |
| `subtype` | TEXT | 固定 `同花顺概念` / `同花顺行业` | |
| `source` | TEXT NOT NULL | 固定 `ths` | loader 校验 =`ths` |
| `platecode` | TEXT NULL | THS `platecode` | 行业时 =`code`;概念时 =`885xxx` |
| `updated_at` | DATETIME | 导出时刻 | loader 覆盖为 NOW |

**loader 行为**: `INSERT OR REPLACE INTO stock_board ... VALUES (?,?,?,?,?,?,?)`,7 列直接对接,无默认值填充。

### 3.2 `stock_board_membership_ths.csv` (8 列)

```csv
board_code,stock_code,source,board_name,stock_name,board_type,subtype,refreshed_at
885002,600519,ths,白酒,贵州茅台,concept,同花顺概念,2026-07-12 17:30:00
885002,000858,ths,白酒,五粮液,concept,同花顺概念,2026-07-12 17:30:00
```

| 列 | 类型 | 说明 |
|---|---|---|
| `board_code` | TEXT NOT NULL | THS platecode (`885xxx` / `881xxx`) |
| `stock_code` | TEXT NOT NULL | 6 位 A 股代码,loader 用 `_is_valid_stock_code` 校验 |
| `source` | TEXT NOT NULL | 固定 `ths`,loader 校验 =`ths` |
| `board_name` | TEXT NOT NULL | denormalized |
| `stock_name` | TEXT NOT NULL | |
| `board_type` | TEXT NOT NULL | `concept` / `industry` |
| `subtype` | TEXT NULL | |
| `refreshed_at` | DATETIME | 导出时刻,loader 覆盖为 NOW |

**loader 行为**: `INSERT OR REPLACE INTO stock_board_membership ...`,逐行写入。无效 `stock_code` 用 `logger.warning` 跳过(不抛错,与 `_read_board_stocks_from_db` 防御风格一致)。

### 3.3 `stock_board_eastmoney.csv` (3 列,旧 schema)

```csv
board_type,board_code,board_name
industry,BK1627,综合Ⅲ
industry,BK1626,稀土
```

**loader 填充逻辑**:

```python
INSERT OR REPLACE INTO stock_board (code, name, board_type, subtype, source, platecode, updated_at)
VALUES (
    row['board_code'],   # code
    row['board_name'],   # name
    row['board_type'],   # board_type
    row['board_type'],   # subtype ← eastmoney 的 subtype 就是 board_type 自身
    'eastmoney',         # source (硬编码)
    NULL,                # platecode ← eastmoney 没有 platecode
    NOW()                # updated_at (用 NOW 不用 CSV)
)
```

---

## 4. 模块 API

### 4.1 `stock_data/data_provider/persistence/board_csv.py` (新文件, ~150 行)

```python
"""CSV seed for stock_board / stock_board_membership tables.

Public API:
- seed_stock_board_from_csv(source, csv_path) -> int
- seed_membership_from_csv(csv_path) -> int
- seed_all_from_backup_dir(backup_dir) -> dict[str, int]
"""
from __future__ import annotations
import csv
import logging
from datetime import datetime
from pathlib import Path
from .db import get_connection

logger = logging.getLogger(__name__)

_STOCK_BOARD_COLS = {"code", "name", "board_type", "subtype", "source",
                     "platecode", "updated_at"}
_MEMBERSHIP_COLS = {"board_code", "stock_code", "source", "board_name",
                    "stock_name", "board_type", "subtype", "refreshed_at"}
_EASTMONEY_COLS = {"board_type", "board_code", "board_name"}

_VALID_STOCK_CODE = __import__("re").compile(r"^\d{6}$")


def _open_csv(path: Path) -> csv.DictReader:
    """Open CSV with utf-8-sig (handles BOM from Excel exports)."""
    f = path.open("r", encoding="utf-8-sig", newline="")
    return csv.DictReader(f)


def _validate_csv_columns(path: Path, required: set[str]) -> None:
    """Raise ValueError if required columns missing. Single error message."""
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        try:
            header = next(reader)
        except StopIteration:
            raise ValueError(f"{path} is empty")
    missing = required - set(header)
    if missing:
        raise ValueError(f"{path} missing required columns: {sorted(missing)}")


def seed_stock_board_from_csv(source: str, csv_path: Path) -> int:
    """Insert/REPLACE rows from a stock_board-style CSV into the DB.

    Args:
        source: 'ths' or 'eastmoney' (must equal CSV's `source` column for
            full-schema CSVs; eastmoney 3-col CSVs are auto-tagged).
        csv_path: Path to the CSV file.

    Returns:
        Number of rows inserted/updated.

    Raises:
        FileNotFoundError: csv_path doesn't exist.
        ValueError: schema mismatch (missing required columns).
    """
    if not csv_path.exists():
        raise FileNotFoundError(csv_path)

    if source == "eastmoney":
        return _seed_eastmoney_board_csv(csv_path)
    _validate_csv_columns(csv_path, _STOCK_BOARD_COLS)
    return _seed_full_schema_board_csv(source, csv_path)


def _seed_full_schema_board_csv(source: str, csv_path: Path) -> int:
    """Full-schema 7-col CSV path (THS uses this)."""
    conn = get_connection()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = []
    skipped_wrong_source = 0
    for r in _open_csv(csv_path):
        if r["source"] != source:
            logger.warning(
                "[CSVSeed] %s: row source=%r != expected %r; skipped",
                csv_path.name, r["source"], source,
            )
            skipped_wrong_source += 1
            continue
        rows.append((
            r["code"], r["name"], r["board_type"], r["subtype"] or "",
            r["source"], r["platecode"] or None, now,
        ))
    if not rows:
        logger.warning("[CSVSeed] %s: 0 rows after validation", csv_path.name)
        return 0
    with conn:
        conn.executemany(
            """INSERT OR REPLACE INTO stock_board
               (code, name, board_type, subtype, source, platecode, updated_at)
               VALUES (?,?,?,?,?,?,?)""",
            rows,
        )
    logger.info("[CSVSeed] %s: wrote %d boards (source=%s, skipped=%d)",
                csv_path.name, len(rows), source, skipped_wrong_source)
    return len(rows)


def _seed_eastmoney_board_csv(csv_path: Path) -> int:
    """3-col CSV path. Fills source='eastmoney', subtype=board_type,
    platecode=NULL, updated_at=NOW."""
    _validate_csv_columns(csv_path, _EASTMONEY_COLS)
    conn = get_connection()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = []
    for r in _open_csv(csv_path):
        rows.append((
            r["board_code"], r["board_name"], r["board_type"],
            r["board_type"],   # subtype = board_type (eastmoney 唯一合法 subtype)
            "eastmoney",       # source hardcoded
            None,              # platecode = NULL (eastmoney 暴露)
            now,
        ))
    if not rows:
        return 0
    with conn:
        conn.executemany(
            """INSERT OR REPLACE INTO stock_board
               (code, name, board_type, subtype, source, platecode, updated_at)
               VALUES (?,?,?,?,?,?,?)""",
            rows,
        )
    logger.info("[CSVSeed] %s: wrote %d boards (eastmoney)", csv_path.name, len(rows))
    return len(rows)


def seed_membership_from_csv(csv_path: Path) -> int:
    """Insert/REPLACE rows from a stock_board_membership-style CSV.

    Args:
        csv_path: CSV with the 8-col membership schema. Rows with invalid
            stock_code (not 6 ASCII digits) are skipped with a warning —
            same defense as `_read_board_stocks_from_db`.

    Returns:
        Number of rows inserted/updated.

    Raises:
        FileNotFoundError, ValueError.
    """
    if not csv_path.exists():
        raise FileNotFoundError(csv_path)
    _validate_csv_columns(csv_path, _MEMBERSHIP_COLS)

    conn = get_connection()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = []
    skipped_invalid_code = 0
    for r in _open_csv(csv_path):
        code = r["stock_code"]
        if not (isinstance(code, str) and _VALID_STOCK_CODE.match(code)):
            logger.warning(
                "[CSVSeed] %s: invalid stock_code=%r; skipped",
                csv_path.name, code,
            )
            skipped_invalid_code += 1
            continue
        rows.append((
            r["board_code"], code, r["source"], r["board_name"],
            r["stock_name"], r["board_type"], r["subtype"] or "", now,
        ))
    if not rows:
        return 0
    with conn:
        conn.executemany(
            """INSERT OR REPLACE INTO stock_board_membership
               (board_code, stock_code, source, board_name, stock_name,
                board_type, subtype, refreshed_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            rows,
        )
    logger.info("[CSVSeed] %s: wrote %d membership rows (skipped=%d)",
                csv_path.name, len(rows), skipped_invalid_code)
    return len(rows)


def seed_all_from_backup_dir(backup_dir: Path) -> dict[str, int]:
    """Seed both stock_board (THS+eastmoney) and stock_board_membership (THS).

    Missing files: log a warning, skip that source. Don't raise.
    Schema errors (missing columns): log error, skip that source. Don't raise.

    Returns:
        {'stock_board_ths': N, 'stock_board_eastmoney': M,
         'stock_board_membership_ths': K}. Missing entries are absent.
    """
    results: dict[str, int] = {}
    if not backup_dir.exists():
        logger.warning("[CSVSeed] backup_dir %s does not exist; skipping all",
                       backup_dir)
        return results

    ths_board = backup_dir / "stock_board_ths.csv"
    if ths_board.exists():
        try:
            results["stock_board_ths"] = seed_stock_board_from_csv("ths", ths_board)
        except ValueError as e:
            logger.error("[CSVSeed] %s: schema error: %s; skipping", ths_board.name, e)
    else:
        logger.warning("[CSVSeed] %s not found; skipping ths stock_board seed",
                       ths_board)

    ths_member = backup_dir / "stock_board_membership_ths.csv"
    if ths_member.exists():
        try:
            results["stock_board_membership_ths"] = seed_membership_from_csv(ths_member)
        except ValueError as e:
            logger.error("[CSVSeed] %s: schema error: %s; skipping", ths_member.name, e)
    else:
        logger.warning("[CSVSeed] %s not found; skipping ths membership seed",
                       ths_member)

    em_board = backup_dir / "stock_board_eastmoney.csv"
    if em_board.exists():
        try:
            results["stock_board_eastmoney"] = seed_stock_board_from_csv(
                "eastmoney", em_board)
        except ValueError as e:
            logger.error("[CSVSeed] %s: schema error: %s; skipping", em_board.name, e)
    else:
        logger.warning("[CSVSeed] %s not found; skipping eastmoney stock_board seed",
                       em_board)

    return results


__all__ = [
    "seed_stock_board_from_csv",
    "seed_membership_from_csv",
    "seed_all_from_backup_dir",
]
```

### 4.2 `server.py` 改动 (lifespan 内 ~6 行)

在 lifespan 的 `reset_all()` / `init_schema()` 之后、`schedule_ths_board_backfill_on_startup` 之前,插入:

```python
# ----- CSV seed (gated by STOCK_DB_INIT=true; opt-out via no files) -----
# When STOCK_DB_INIT=true: tables were just dropped. Re-seed from
# stock_data_backup/ so the server has data immediately, without paying
# the ~17min upstream cost. If BOARD_BACKFILL_ON_STARTUP=true also fires,
# the upstream refresh will overwrite the CSV data shortly after.
from pathlib import Path
from .data_provider.persistence import board_csv

backup_dir = Path(__file__).parent / "stock_data_backup"
seed_results = board_csv.seed_all_from_backup_dir(backup_dir)
if seed_results:
    logger.info("[Startup] CSV seed complete: %s", seed_results)
else:
    logger.info("[Startup] CSV seed skipped (no files or STOCK_DB_INIT=false)")
```

### 4.3 `persistence/__init__.py` 改动

在 `from . import board, pool_daily, stock_list, trade_calendar` 后追加 `board_csv`,并在 `__all__` 加上:

```python
from . import board, board_csv, pool_daily, stock_list, trade_calendar

# ... 已有 ...

__all__ = [
    # Submodules
    "board",
    "board_csv",     # NEW
    "pool_daily",
    "stock_list",
    "trade_calendar",
    # ... 已有 ...
    "seed_all_from_backup_dir",  # NEW
]
```

---

## 5. 错误处理与边界

### 5.1 错误矩阵

| 场景 | 检测位置 | 行为 | 启动是否失败 |
|---|---|---|---|
| `backup_dir` 不存在 | `seed_all_from_backup_dir` 入口 | log warning,返回空 dict | ❌ |
| 单个 CSV 文件不存在 (ths/eastmoney/membership) | `seed_all_from_backup_dir` 每个文件前 | log warning,跳过该文件,继续下一个 | ❌ |
| CSV 缺少必需列 | `_validate_csv_columns` | raise ValueError → caller log error + 跳过该文件 | ❌ |
| CSV 为空文件 (无 header) | `_validate_csv_columns` (StopIteration) | raise ValueError → 同上 | ❌ |
| CSV 单行 `source` ≠ 期望 source (THS full-schema) | `_seed_full_schema_board_csv` 循环内 | log warning + skip 该行,继续 | ❌ |
| CSV 单行 `stock_code` 不是 6 位数字 (membership) | `seed_membership_from_csv` 循环内 | log warning + skip 该行,继续 | ❌ |
| CSV encoding 错误 (非 utf-8/utf-8-sig) | `open()` 直接抛 UnicodeDecodeError | 异常向上冒泡,该文件失败,其余仍跑 | ⚠️ |
| `STOCK_DB_INIT=false` | 不调用 `seed_all_from_backup_dir` | 完全跳过 CSV 加载 | n/a |

### 5.2 关键边界处理

**1. CSV encoding (BOM)**
所有 `open()` 用 `encoding="utf-8-sig"`,自动剥除 Excel 导出时常见的 UTF-8 BOM (`﻿`)。

**2. `source` 列强制校验**
THS full-schema CSV 每行的 `source` 列必须等于 `"ths"`,否则单行 skip 并 warning。防止不同 source 的 CSV 被误传到 THS path 上,污染 source 维度。

**3. `updated_at` 总是被覆盖**
CSV 中的 `updated_at` 是导出时刻的快照,但 loader 永远用 `datetime.now()` 覆盖:
- 多次 `STOCK_DB_INIT=true` 重启后,`updated_at` 反映"最近一次 seed 时间"
- 避免导出 → 加载时间差造成"未来时间"的诡异排序

**4. eastmoney CSV 3 列 vs THS 7 列的不对称**
`_seed_eastmoney_board_csv` 是独立路径,不走通用 `_seed_full_schema_board_csv`:
- eastmoney 没有 `subtype` 概念,只能用 `board_type` 兜底
- eastmoney 没有 `platecode`,硬编码 NULL
- eastmoney CSV 是历史遗留(993 行手写数据),schema 不该改

未来若 eastmoney 改成完整 schema 导出,删掉 `_seed_eastmoney_board_csv`,统一走 THS 那条路。

**5. `seed_all_from_backup_dir` 的返回 dict 设计**
返回 `{filename_stem: row_count}`(不带 `.csv` 后缀),不是 `{source: row_count}`:
- 文件名已编码 source 信息
- 未来加 `stock_board_zhitu.csv`,返回 key 就是 `stock_board_zhitu`,无需 schema 改动
- 测试断言更直接

### 5.3 不做的事 (YAGNI)

- ❌ 不做 schema 版本检查
- ❌ 不做 dry-run 模式
- ❌ 不做 CSV 增量 diff / merge
- ❌ 不做 CSV 压缩 / 加密
- ❌ 不做 zip 多文件打包

---

## 6. 文件清单与构建配置

### 6.1 新增文件 (5 个)

| 文件 | 行数估计 | 性质 |
|---|---|---|
| `stock_data/data_provider/persistence/board_csv.py` | ~150 | Python 模块,随 wheel 发布 |
| `stock_data/stock_data_backup/stock_board_ths.csv` | ~385 行 × 7 列 ≈ 50KB | 数据备份,从当前 DB `source='ths'` 导出 |
| `stock_data/stock_data_backup/stock_board_membership_ths.csv` | ~5000+ 行 × 8 列 ≈ 500KB | 数据备份,从当前 DB 导出 |
| `stock_data/stock_data_backup/stock_board_eastmoney.csv` | 993 行 × 3 列 ≈ 70KB | 重命名自 `boards_akshare_name_em.csv` |
| `tests/test_board_csv_seed.py` | ~250 | 单元测试 |

### 6.2 修改文件 (4 个)

| 文件 | 改动 |
|---|---|
| `stock_data/server.py` | lifespan 内插入 ~6 行 CSV seed 调用 |
| `stock_data/data_provider/persistence/__init__.py` | 暴露 `board_csv` 模块 + `seed_all_from_backup_dir` 到 `__all__` |
| `.gitignore` | 添加 `!stock_data/stock_data_backup/` 允许跟踪 CSV |
| `.env.example` | 文档化"CSV seed 与 STOCK_DB_INIT 绑定"的行为 |

### 6.3 重命名文件 (1 个)

`stock_data/boards_akshare_name_em.csv` → `stock_data/stock_data_backup/stock_board_eastmoney.csv`

用 `git mv` 保留 history。

### 6.4 .gitignore 改动

当前第 80 行:`*.csv` 排除所有 CSV。改为:

```gitignore
# Data files (project-wide, except for intentional repo-managed backups)
*.csv
# ... existing SQLite ignore lines ...

# Repo-managed CSV seed backups (force-tracked; loader reads on STOCK_DB_INIT=true)
!stock_data/stock_data_backup/
```

### 6.5 .env.example 新增段落

在现有 `STOCK_DB_INIT` 和 `BOARD_BACKFILL_ON_STARTUP` 段落之间,插入:

```bash
# === CSV seed on STOCK_DB_INIT=true ===
# When STOCK_DB_INIT=true, the persistence layer ALSO loads CSVs from
# stock_data/stock_data_backup/ into the freshly-reset database. This
# gives the server immediate data without paying the ~17min upstream
# backfill cost. Files expected:
#   - stock_board_ths.csv            (full schema; 7 cols)
#   - stock_board_membership_ths.csv (full schema; 8 cols)
#   - stock_board_eastmoney.csv      (legacy 3-col schema; auto-filled defaults)
# Missing files log a warning and are skipped. Schema errors (missing
# columns) are non-fatal — that source is skipped, others still load.
#
# Typical combinations:
#   STOCK_DB_INIT=true,  BOARD_BACKFILL_ON_STARTUP=false  → fast: CSV only, ~0ms
#   STOCK_DB_INIT=true,  BOARD_BACKFILL_ON_STARTUP=true   → CSV seed then refresh
#   STOCK_DB_INIT=false, BOARD_BACKFILL_ON_STARTUP=true   → upstream refresh only
#   STOCK_DB_INIT=false, BOARD_BACKFILL_ON_STARTUP=false  → nothing happens
```

### 6.6 不做的事

- ❌ 不改 `pyproject.toml` 的 `force-include`(CSV 不进 wheel)
- ❌ 不改 `tools/build_membership_index.py`(那是 CLI,不是自动 seed)
- ❌ 不动 CLAUDE.md(此次改动属于持久层细节,docstring + .env.example 已足够说明)
- ❌ 不写 `tools/backup_board_csv.py`(导出是一次性动作,sqlite3 CLI 即可)

### 6.7 导出当前 THS 数据的临时命令(用完即弃)

```bash
.venv/Scripts/python.exe -c "
import sqlite3, csv
conn = sqlite3.connect('stock_data/stock_cache.db')
conn.row_factory = sqlite3.Row

with open('stock_data/stock_data_backup/stock_board_ths.csv', 'w',
          newline='', encoding='utf-8') as f:
    w = csv.writer(f)
    w.writerow(['code','name','board_type','subtype','source','platecode','updated_at'])
    for r in conn.execute(\"SELECT code,name,board_type,subtype,source,platecode,updated_at FROM stock_board WHERE source='ths' ORDER BY board_type, code\"):
        w.writerow([r['code'], r['name'], r['board_type'], r['subtype'], r['source'], r['platecode'], r['updated_at']])

with open('stock_data/stock_data_backup/stock_board_membership_ths.csv', 'w',
          newline='', encoding='utf-8') as f:
    w = csv.writer(f)
    w.writerow(['board_code','stock_code','source','board_name','stock_name','board_type','subtype','refreshed_at'])
    for r in conn.execute(\"SELECT board_code,stock_code,source,board_name,stock_name,board_type,subtype,refreshed_at FROM stock_board_membership WHERE source='ths' ORDER BY board_code, stock_code\"):
        w.writerow([r['board_code'], r['stock_code'], r['source'], r['board_name'], r['stock_name'], r['board_type'], r['subtype'], r['refreshed_at']])
"
```

然后 `git mv stock_data/boards_akshare_name_em.csv stock_data/stock_data_backup/stock_board_eastmoney.csv`。

---

## 7. 测试策略

### 7.1 测试位置

新文件 `tests/test_board_csv_seed.py`,沿用现有 `tests/test_board_backfill.py` 的 `fresh_db` fixture 风格(临时 DB + 重置单例)。

### 7.2 测试用例清单(共 10 个)

| # | 测试名 | 验证点 |
|---|---|---|
| 1 | `test_seed_stock_board_ths_full_schema` | 7 列 CSV → 表里有 N 行,所有列值正确 |
| 2 | `test_seed_eastmoney_3col_fills_defaults` | 3 列 CSV → source='eastmoney', subtype=board_type, platecode=NULL, updated_at 是 NOW |
| 3 | `test_seed_membership_with_valid_codes` | 8 列 CSV → 表里有 N 行,所有列值正确 |
| 4 | `test_seed_membership_skips_invalid_stock_code` | 一行 stock_code='贵州茅台' → warning + skip,其他行写入 |
| 5 | `test_seed_full_schema_skips_wrong_source_row` | CSV 里混一行 source='eastmoney' → warning + skip |
| 6 | `test_seed_missing_columns_raises_value_error` | 缺 `platecode` 列 → ValueError,被 caller 包成 log error 不致命 |
| 7 | `test_seed_all_from_backup_dir_missing_dir` | `backup_dir` 不存在 → 返回空 dict,log warning |
| 8 | `test_seed_all_from_backup_dir_missing_files` | 目录存在但 3 个文件全缺 → 每个都 warning,返回空 dict |
| 9 | `test_seed_all_from_backup_dir_partial_files` | 只有 ths board 在 → 返回 `{'stock_board_ths': N}`,其余 warning |
| 10 | `test_seed_idempotent_re_run` | 同 CSV 跑两次 → 行数不变(INSERT OR REPLACE) |

### 7.3 测试风格参考

```python
@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """沿用 test_board_backfill.py 的 fresh_db fixture。"""
    monkeypatch.setattr(db_mod, "_db_path", None)
    monkeypatch.setattr(db_mod, "_conn", None)
    monkeypatch.setattr(board_mod, "_schema_initialized_paths", set())
    monkeypatch.setenv("STOCK_CACHE_DB_PATH", str(tmp_path / "test.db"))
    board_mod.init_schema()
    yield tmp_path / "test.db"


def test_seed_eastmoney_3col_fills_defaults(fresh_db, tmp_path):
    """3 列 eastmoney CSV: source/subtype/platecode 由 loader 填充。"""
    csv_path = tmp_path / "stock_board_eastmoney.csv"
    csv_path.write_text(
        "board_type,board_code,board_name\n"
        "industry,BK1627,综合Ⅲ\n"
        "concept,BK1701,融资融券\n",
        encoding="utf-8-sig",
    )

    n = board_csv.seed_stock_board_from_csv("eastmoney", csv_path)
    assert n == 2

    rows = board_mod._read_boards_from_db("industry", "eastmoney")
    assert len(rows) == 1
    assert rows[0]["code"] == "BK1627"
    assert rows[0]["subtype"] == "industry"   # subtype = board_type
    assert rows[0]["platecode"] is None      # eastmoney 没有 platecode
    assert rows[0]["source"] == "eastmoney"


def test_seed_membership_skips_invalid_stock_code(fresh_db, tmp_path, caplog):
    """无效 stock_code(非 6 位数字)warning + skip,其余行写入。"""
    csv_path = tmp_path / "stock_board_membership_ths.csv"
    csv_path.write_text(
        "board_code,stock_code,source,board_name,stock_name,"
        "board_type,subtype,refreshed_at\n"
        "885002,600519,ths,白酒,贵州茅台,concept,同花顺概念,2026-07-12 17:30:00\n"
        "885002,贵州茅台,ths,白酒,五粮液,concept,同花顺概念,2026-07-12 17:30:00\n"
        "885002,000858,ths,白酒,五粮液,concept,同花顺概念,2026-07-12 17:30:00\n",
        encoding="utf-8-sig",
    )

    with caplog.at_level(logging.WARNING, logger="stock_data.data_provider.persistence.board_csv"):
        n = board_csv.seed_membership_from_csv(csv_path)
    assert n == 2
    assert any("invalid stock_code" in r.message and "贵州茅台" in r.message
               for r in caplog.records)
```

### 7.4 不新增的测试

- ❌ 不测 `server.py` 的 lifespan 集成(那要起 FastAPI,慢且脆)
- ❌ 不测 csv 标准库本身(`csv.DictReader` 不需要测)
- ❌ 不测 SQLite 自身的 INSERT OR REPLACE 语义
- ❌ 不测 eastmoney CSV 的 `_seed_eastmoney_board_csv` 内部 helper(只测公开 API 行为即可)

### 7.5 与现有 test_board_backfill.py 的关系

- 新文件独立,无 `test_board_csv_seed.py` import `test_board_backfill.py`
- 共用 `fresh_db` 模式,但不复用 fixture(避免跨文件 fixture 依赖)
- 都使用 `monkeypatch.setattr(db_mod, "_conn", None)` 重置单例 — 同样手法

---

## 8. 开放问题 / 风险

| 风险 | 缓解 |
|---|---|
| CSV 与 DB schema 漂移 (未来加列) | loader 用 `executemany` 写固定列数,新增列后 CSV 需补列,否则 `_validate_csv_columns` 失败 |
| CSV 文件膨胀(成员表 ~5000 行 × 8 列 ≈ 500KB) | 当前可接受;若以后 > 5MB 考虑压缩或 split per board_type |
| 重命名时丢失原 `boards_akshare_name_em.csv` 的 git history | 用 `git mv` 而非 delete+add,git 自动识别 rename |
| 上游 CSV 未及时更新时,seed 出的数据可能 stale | 用户可同时开 `BOARD_BACKFILL_ON_STARTUP=true` 让 upstream 覆盖 |
| 多个 CSV 都失败时,启动仍是"成功"的(空 DB) | log "skipped all";运维侧应监控此 log 模式 |