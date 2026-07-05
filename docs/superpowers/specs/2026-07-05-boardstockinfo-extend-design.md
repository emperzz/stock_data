# BoardStockInfo: 暴露 `change_amount` 与 `turnover_rate`（消除 half-fix）

> 日期: 2026-07-05
> 范围: 把刚刚完成的 commit `46ff6cb`（暴露 `amount`）未做完的 siblings 一并补齐。
> 性质: **后端小补丁**（schema + 路由投影 + 一行 fetcher 改动 + 单测）。
> 关联: 紧跟 `46ff6cb feat(boards): expose amount (成交额) in BoardStockInfo response`；review blocker 标记为 confidence 85 的"half-fix"问题。

---

## 1. 目标与动机

**目标**: 修复 commit `46ff6cb` 留下的 sibling fields —— 在 `BoardStockInfo` schema 边界同时暴露 `change_amount` 和 `turnover_rate`，与刚刚暴露的 `amount` 保持同等语义："上游已经产出的字段，不应再被 schema 边界吞掉。"

**为什么改**:
- review 阻断级发现：`ths_fetcher.py:703, 704` 已经产出 `change_amount`（idx 5 涨跌元）与 `turnover`（idx 7 换手%），`eastmoney/_boards_mixin.py:605, 606` 同样产出（`f4 → change_amount`、`f8 → turnover_rate`）。`BoardStockInfo` schema 不收这两字段，Pydantic 默认 `extra="ignore"` 静默丢掉，上游数据进得来但出不去。
- 同源同 commit 消息（如：`"callers don't lose data the upstream already provided"`）覆盖的是整个边界家族，只补一个字段是 half-fix。
- 与已经存在的兄弟字段 `BoardInfo.turnover_rate`（`schemas.py:290`）、`KLineData.turnover_rate`（`schemas.py:443`）命名一致。

**非目标**:
- 不改变 `include_quote` 默认值（仍 `False`）。
- 不改 `BoardInfo` / `KLineData`（这两个 schema 本来就已经含这俩字段）。
- 不改 persistence schema（按 CLAUDE.md，cache-hit 仍返 `null`，新增字段遵守此约定）。
- 不修正 description 字符串里 `volume` 的"only populated when upstream exposes it" caveat（review Finding #3，独立 cleanup）。
- 不修 NEW-2 (`boards.py:450` 路由描述的 push2his 错误) 与 NEW-3 (EastMoney fetch 错返 `[]` 误导 404) —— 独立 follow-up。

---

## 2. 当前状态（仅改动相关）

### 2.1 `BoardStockInfo` 现状（`schemas.py:298-306`）

```python
class BoardStockInfo(BaseModel):
    """Stock in a board, optionally with quote data."""
    code: str
    name: str = Field(default="", description="Stock name")
    price: float | None = Field(default=None, description="Current price")
    change_pct: float | None = Field(default=None, description="Change percent")
    volume: int | None = Field(default=None, description="Volume (shares; only populated when upstream exposes it)")
    amount: float | None = Field(default=None, description="Trading amount (元; populated by THS and EastMoney)")
```

**问题**：`change_amount`、`turnover_rate` 缺失；`amount` 描述硬编码 fetcher 名字（本次借机一并收敛）。

### 2.2 路由投影现状（`routes/boards.py:522-532`）

```python
BoardStockInfo(
    code=...,
    name=...,
    price=s.get("price"),
    change_pct=s.get("change_pct"),
    volume=s.get("volume"),
    amount=s.get("amount"),
)
```

**问题**：上游 dict 里 `change_amount` 和 `turnover_rate` 存在，但路由没有 `.get(...)` 投影它们。

### 2.3 THS fetcher 输出 key 不一致（`ths_fetcher.py:704`）

```python
"turnover": safe_float(tds[7].get_text(strip=True)) if len(tds) > 7 else None,
```

但同一个 fetcher 其他端点（`ths_fetcher.py:920`）已经用 `"turnover_rate"`（从 `huanshou` 字段）。

**问题**：THS 在 board-stocks 路径还在用 `"turnover"`，schema 定 `turnover_rate` 就需要把这条 key 改过来。

### 2.4 上游确认（fact-check）

| 来源 | change_amount 路径 | turnover_rate 路径 | 默认产出 |
|---|---|---|---|
| THS `get_board_stocks`（`ths_fetcher.py:703-704`） | `safe_float(tds[5])` | `safe_float(tds[7])` 旧名为 `"turnover"` | 总是 |
| EastMoney `_get_board_stocks_impl`（`_boards_mixin.py:605-606`） | `(r.get("f4") or 0) / 100` | 同除 100 路径 | 仅 `include_quote=True` |
| Zzshare `get_board_stocks`（`zzshare_fetcher.py:602-640`） | （未产 quote fields） | （未产 quote fields） | — |
| Zhitu `get_board_stocks`（`zhitu_fetcher.py:450-475`） | （未产 quote fields） | （未产 quote fields） | — |

**确认**：当 schema `include_quote=False` 时，EastMoney 也不发这两个字段；`include_quote=True` 时才发。THS 不论 `include_quote` 都会发。Zzshare、Zhitu 不支持（schema 字段走 `default=None`，不报错）。

---

## 3. 设计

### 3.1 Schema 改动（`schemas.py:303-308`）

在 `BoardStockInfo` 加两个字段，紧跟现有 `amount` 后面：

```python
change_amount: float | None = Field(default=None, description="Change amount (元)")
turnover_rate: float | None = Field(default=None, description="Turnover rate (%)")
```

并把刚刚 `amount` 加上的硬编码 fetcher 名字也收敛掉（Find G 顺手）：
```python
amount: float | None = Field(default=None, description="Trading amount (元)")
```

描述约定：
- 沿用兄弟字段 `change_pct` / `price` / `volume` 的简洁风格（只标单位，不列 fetcher 名字）
- 单位：`change_amount` 是"涨跌 元"；`turnover_rate` 是"换手率 %"；`amount` 是"成交额 元"
- 不写"populated by THS and EastMoney"——上游语义另写在 endpoint docstring 和 fetcher 模块 docstring 里

> 重要：保留 `volume` 现有描述 `"Volume (shares; only populated when upstream exposes it)"`。本次不动该字段描述（属独立 cleanup）。

### 3.2 路由投影（`routes/boards.py:528-531`）

```python
BoardStockInfo(
    code=...,
    name=...,
    price=s.get("price"),
    change_pct=s.get("change_pct"),
    change_amount=s.get("change_amount"),     # 新增
    volume=s.get("volume"),
    amount=s.get("amount"),
    turnover_rate=s.get("turnover_rate"),     # 新增
)
```

`float | None` 与 `safe_float` 归一化**不动**（与既有 `amount=s.get("amount")` 保持一致；pre-existing 风险 `volume` 同等不解决）。

### 3.3 THS fetcher 改名（`ths_fetcher.py:704`）

```python
-            "turnover": safe_float(tds[7].get_text(strip=True)) if len(tds) > 7 else None,
+            "turnover_rate": safe_float(tds[7].get_text(strip=True)) if len(tds) > 7 else None,
```

影响范围核查：
- 仅 `get_board_stocks` 一个函数（search 该字符串仅此一处）
- 同 fetcher 其他端点 (`ths_fetcher.py:920`) 已是 `"turnover_rate"`，等价统一
- 既有 `test_ths_fetcher.py` 的测试**：grep 验证**后若发现某条断言基于 `"turnover"` key 名，同步改

### 3.4 端点 docstring（`routes/boards.py:454`）

把 `get_board_stocks` 的 docstring 加一句：

```text
THS populates change_amount and turnover_rate by default.
EastMoney/Zzshare require ?include_quote=true for these quote fields.
```

不动 `boards.py:450` 那个 `eastmoney (push2his)` 的路由描述错误 —— 属 NEW-2，独立 follow-up。

### 3.5 测试

#### 新增 1 条测试（`tests/test_boards_api.py`）

新加 `test_get_board_stocks_projects_change_amount_and_turnover_rate`：
- 复用现有的 patch 模式（patch `persistence.board.get_board_stocks` 与 `get_board_name`）
- fake dict 含 `change_amount=2.5, turnover_rate=8.7` 字段
- 断言 `stock["change_amount"] == 2.5`、`stock["turnover_rate"] == 8.7`

#### 不改现有测试

`test_get_board_stocks_projects_amount_from_fetcher_output`（commit 46ff6cb 加的）保持原状。不在它上加新断言，避免单测做多件事。

#### 不动 `test_ths_fetcher.py`

除非 grep 后发现某条断言依赖 `"turnover"` key 名；如有则一并改。

### 3.6 Persistence 行为（不动）

按 CLAUDE.md "Don't cache realtime quote data in SQLite"，新增 `change_amount` / `turnover_rate` 在 cache-hit 时同样返回 `null`。**与新增 schema 字段一致**：调用方靠 `data_source` 字段判断当前是 fetcher path 还是 persistence path。

---

## 4. 数据流（端到端）

```
THS upstream      →  ths_fetcher._get_board_stocks  →  dict {change_amount, turnover_rate, ...}
EastMoney upstream → _get_board_stocks_impl         →  dict {change_amount, turnover_rate, ...} (only when include_quote=True)
                                               ↓
                                  persistence.board (cache hit: dict 退化为 {stock_code, stock_name, updated_at})
                                               ↓
                          routes/boards.py: BoardStockInfo(... change_amount=s.get("change_amount") ...)
                                               ↓
                                              JSON
```

cache-hit 与 live-fetch 两路径行为差异：

| 路径 | price | change_pct | change_amount | volume | amount | turnover_rate |
|---|---|---|---|---|---|---|
| THS live | ✓ | ✓ | ✓ | null（无字段）| ✓ | ✓ |
| EastMoney `include_quote=True` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| EastMoney `include_quote=False`（默认） | null | null | **null** | null | **null** | **null** |
| Zzshare/Zhitu | null | null | null | null | null | null |
| persistence cache hit | null | null | null | null | null | null |

新增字段与既有 sibling 行为对称。

---

## 5. 错误处理

- Pydantic `float | None = None` 接受 `int` / `float` / `None`；上游传 `None` 或缺 key，`.get()` 返 `None`，Pydantic 接受
- EastMoney 在 `include_quote=False` 不发这些字段（同不发 `volume`/`amount`）—— 用户需要 quote 数据时切 `?include_quote=true`
- THS fetcher 改名 `"turnover" → "turnover_rate"`：单一 key 改写，无兼容窗口问题（内部 fetcher-到-路由契约，不暴露给外部）

---

## 6. 测试

### 6.1 单元测试

```bash
.venv/Scripts/python.exe -m pytest tests/test_boards_api.py -v   # 33 + 1 = 34
.venv/Scripts/python.exe -m pytest tests/test_ths_fetcher.py -v  # 既有全部不动
```

### 6.2 全套（不联网）

```bash
.venv/Scripts/python.exe -m pytest
```

（CI 标准命令，`addopts` 已默认 skip `live_network`）

### 6.3 Lint

```bash
ruff check .
```

### 6.4 反向校验 grep

```bash
# 验证 THS fetcher 没有残留 "turnover" 的 key
grep -rn '"turnover":' stock_data/data_provider/fetchers/   # 应为空（除同 key 别名）
grep -rn '"turnover_rate":' stock_data/data_provider/fetchers/  # 至少 1 处
```

---

## 7. 回滚

若发现上游实际产出 value 与 schema 不兼容（如 EastMoney `change_amount` 误为百分比而非元），回退路径：
1. schema 字段保留 `float | None = None`，路由依然 `.get(...)`，不报错（用户拿 `null`）
2. 单测 + 端到端 live_network 测试给出早期信号
3. 业务行为修复独立 commit（fetcher 侧）

---

## 8. 已知不做的事 / 后续候选

| 编号 | 描述 | 来源 |
|---|---|---|
| NEW-1 | `include_quote` 默认值 `False` 导致 EastMoney 不发 `change_amount` / `turnover_rate` | 半修复；本次不翻默认 |
| NEW-2 | `boards.py:450` 路由描述写 `eastmoney (push2his)`，端点实为 push2 clist | 独立 follow-up |
| NEW-3 | EastMoney `_get_board_stocks_impl` 抓失败返 `[]` → 路由 404 误导 | 独立 follow-up |
| Finding #2 | commit 46ff6cb message 写 "push2his f6"，实为 push2 f6 | commit message 文档层，独立清理 |
| Finding #3 | `volume` 描述不对称（`change_pct`/`price` 没写 "only populated..."） | 描述层 nitpick，独立清理 |
| Finding #4 | SQLite cache-hit 返 `null`（CLAUDE.md 设计要求） | 设计如此 |
| Finding #5 | 测试 fake dict 有未断言键（`change_amount`/`turnover`） | 下次 THS 测改时清掉 |

---

## 9. 验收 checklist

- [ ] `schemas.py`: `BoardStockInfo` 新增 `change_amount`、`turnover_rate` 两个 `float | None = None`
- [ ] `schemas.py`: `amount` 描述中 "populated by THS and EastMoney" 删除
- [ ] `routes/boards.py:454`: docstring 加 THS/EastMoney/Zzshare 行为差异说明
- [ ] `routes/boards.py:522-532`: `BoardStockInfo(...)` 投影加 `change_amount`、`turnover_rate`
- [ ] `ths_fetcher.py:704`: `"turnover"` → `"turnover_rate"`
- [ ] `ths_fetcher.py:799`: docstring 列表同步改（验证后）
- [ ] `tests/test_boards_api.py`: 新增 `test_get_board_stocks_projects_change_amount_and_turnover_rate`
- [ ] `tests/test_ths_fetcher.py`: 若 grep 发现有断言依赖旧 key 名则同步改
- [ ] `pytest tests/test_boards_api.py tests/test_ths_fetcher.py` 全过
- [ ] `pytest`（默认 skip live_network）全过
- [ ] `ruff check .` 无 issue
- [ ] `grep -rn '"turnover":' stock_data/data_provider/fetchers/` 无残留
