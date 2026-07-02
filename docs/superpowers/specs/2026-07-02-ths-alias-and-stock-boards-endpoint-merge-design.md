# `ths` 别名 + Stock-Boards 端点合并设计

> 日期: 2026-07-02
> 状态: 待用户审阅
> 范围: 两个相互关联的改动——(1) `?source=ths` 作为 `zzshare` 的 API 层别名；(2) 合并 `/stocks/{code}/boards` 与 `/stocks/{code}/board-memberships` 为单一端点，统一 schema。
> 性质: **路由层 + 持久化层 helper 调整**。零 fetcher 侵入，零 DB schema 变更，零 capability flag 改动。

---

## 1. 问题陈述

### 1.1 zzshare 的板块本质上是同花顺分类

`zzshare_fetcher.py:498-508` 把 SDK 的 `plate_type` 14/15/17 显式映射为 `同花顺行业/同花顺概念/同花顺题材`——上游就是同花顺数据。但 API 层把这条信息埋在 `subtype` 字符串里，对外 source 名仍是 `zzshare`，客户端无法从 `?source=zzshare` 推断出"这是同花顺分类"。

### 1.2 两个 stock-boards 端点分裂导致消费者心智负担

| 端点 | 参数 | 行为 | Schema |
|---|---|---|---|
| `/stocks/{code}/boards` | `?source=` 必填 | 单 source；zhitu cold 时隐式 lazy fill | `{stock_code, source, data: [...]}` |
| `/stocks/{code}/board-memberships` | 无 source | 跨 source 聚合；纯 DB 读 | `{stock_code, memberships: {src: [...]}, cold_sources: [...]}` |

消费者要先决定"我要单源还是跨源"——这是实现细节，不该是 API 表面的概念。同时两组响应 schema 描述的是同一份数据。

---

## 2. 目标与非目标

### 目标

1. **ths 别名**：`?source=ths` 在路由层 remap 到 `zzshare`，对客户端透明。零数据迁移、零 DB schema 改动。
2. **端点合并**：单一 `/stocks/{code}/boards` 端点同时承担"单源精确查询"和"跨源聚合"。`/stocks/{code}/board-memberships` 降级为 thin wrapper（schema 不变），后续大版本删除。
3. **cold-source 可见性统一**：合并后端点永远返回 `cold_sources`，无论是否限定 source。
4. **cold-path 显式 opt-in**：告别 zhitu 隐式 lazy fill，行为必须显式声明 (`?cold_fill=true`)。

### 非目标

- 新增 `board_system` 字段（已讨论并砍掉）
- 响应里回填 `source='ths'`（已讨论并砍掉，`data_source` 保持 fetcher 名以诚实表达数据来源）
- zhitu 中文 subtype 字符串规范化（独立 PR 处理）
- `/stocks/{code}/boards` 以外的板块端点改动（如 `/boards`、`/boards/{code}/stocks` 不在本次范围）
- DB schema 迁移（`stock_board_membership.source` 列继续存 normalized 后的 fetcher 名）

---

## 3. 设计

### 3.1 `?source=ths` 别名（最小改动）

`api/routes/boards.py` 在每个 endpoint 的 route 体最开头加一行 remap（在 `_resolve_source(source)` **之前**）：

```python
# 同花顺板块的对外别名 — zzshare SDK 的 plates_list 上游就是同花顺数据。
# 客户端用 ths / zzshare 两种写法等价，DB 永远存 normalized 后的 zzshare。
if source == "ths":
    source = "zzshare"
```

只影响**有 `?source=` 必填/可选参数的端点**。本次范围：

| 端点 | 当前 source 必填 | alias 后 |
|---|---|---|
| `GET /boards` | 必填 | 接受 `ths`，remap 到 `zzshare` |
| `GET /boards/{code}/stocks` | 必填 | 接受 `ths`，remap 到 `zzshare` |
| `GET /boards/{code}/history` | 必填 | 接受 `ths`，remap 到 `zzshare` |
| `GET /stocks/{code}/boards` | 必填（合并后变可选） | 接受 `ths`（CSV 单值时 remap 到 `zzshare`） |
| `GET /stocks/{code}/board-memberships` | 无 source | N/A |

**Literal 改动**（每个端点的 Query 参数）：

```python
source: Literal["eastmoney", "zhitu", "zzshare", "ths"] = Query(...)
```

**CSV 解析**（合并后端点）：`source` 改用 `str | None` + 在 route 体内手动 split / remap / dedupe，因为 `Literal` 不接受逗号分隔的多值。规则：

```python
def _parse_source_csv(raw: str | None) -> list[str]:
    """Parse ?source=ths,zhitu,eastmoney -> ['zzshare', 'zhitu', 'eastmoney'] (normalized)."""
    if not raw:
        return list(stock_board_cache.VALID_SOURCES)
    out: list[str] = []
    for s in raw.split(","):
        s = s.strip()
        if s == "ths":
            s = "zzshare"
        if s not in stock_board_cache.VALID_SOURCES:
            raise HTTPException(400, detail={"error": "invalid_source", "message": f"...{s}..."})
        if s not in out:
            out.append(s)
    return out
```

**测试改动**：
- 每个 endpoint 的 `_resolve_source` 单测补一个 `source="ths"` 用例
- `_parse_source_csv` 单测：`ths,zhitu` → `['zzshare', 'zhitu']`；dedupe；非法值报错
- 验证 alias 后 DB 写入仍是 `source='zzshare'`，不污染表

### 3.2 端点合并：单一 `/stocks/{code}/boards`

#### 3.2.1 新端点形态

```
GET /api/v1/stocks/{stock_code}/boards
  ?source=eastmoney,zhitu,zzshare,ths    (可选, 逗号分隔; 缺省 = 所有)
  &type=concept|industry|index|special   (可选)
  &subtype=...                            (可选, 按 (source, type) 单独 filter)
  &cold_fill=true|false                   (默认 false, opt-in zhitu 兜底)
  &refresh=true|false                     (默认 false)
```

**新响应 schema**（合并 `StockBoardsResponse` + `BoardMembershipsResponse`）：

```python
class StockBoardInfo(BaseModel):
    """A board that a stock belongs to."""
    code: str       # source-specific board code (BK1048 / sw_yx / 881101)
    name: str       # board full name
    type: str       # concept / industry / index / special
    subtype: str    # source-specific subtype
    source: str     # NEW: eastmoney / zhitu / zzshare — always present after merge


class StockBoardsResponse(BaseModel):
    """Unified response for /stocks/{code}/boards (single + cross source)."""
    stock_code: str
    source: str                 # "eastmoney" / "zhitu" / "zzshare" / "merged" / "persistence"
    data: list[StockBoardInfo]  # per-entry source; flat list (caller groups if needed)
    cold_sources: list[str]     # sources with no data (always present, may be empty)
```

**响应示例**（多 source 聚合）：

```json
{
  "stock_code": "600519",
  "source": "merged",
  "data": [
    {"code": "BK0001", "name": "白酒",     "type": "concept", "subtype": "concept",        "source": "eastmoney"},
    {"code": "sw_yx",  "name": "A股-申万行业-食品饮料", "type": "industry", "subtype": "申万行业", "source": "zhitu"},
    {"code": "881101", "name": "白酒",     "type": "concept", "subtype": "同花顺概念",     "source": "zzshare"}
  ],
  "cold_sources": []
}
```

**响应示例**（单 source + cold_sources 报告）：

```json
{
  "stock_code": "000001",
  "source": "eastmoney",
  "data": [
    {"code": "BK0438", "name": "银行", "type": "industry", "subtype": "industry", "source": "eastmoney"}
  ],
  "cold_sources": ["zhitu", "zzshare"]
}
```

#### 3.2.2 行为表

| `?source=` | `?cold_fill=` | 读取路径 | 写入路径 |
|---|---|---|---|
| 缺省（所有） | `false` | 读 `stock_board_membership` | 不写 |
| 缺省（所有） | `true` | 读 membership → zhitu 缺则 lazy fill → 写回 membership | 仅 zhitu 缺时写 |
| `eastmoney,zzshare,ths` | `false` | 读 membership（`ths` remap `zzshare`，合并查询） | 不写 |
| `zhitu` | `true` | 读 membership → 缺则 lazy fill → 写回 | 仅缺时写 |
| `zhitu` | `false` | 读 membership；空 → 不报错，进 `cold_sources` | 不写 |

#### 3.2.3 共享 helper：`get_stock_memberships`

为避免 `/stocks/{code}/boards` 和降级 wrapper `/stocks/{code}/board-memberships` 双写逻辑，提取共享函数到 `persistence/board.py`：

```python
def get_stock_memberships(
    stock_code: str,
    sources: list[str],         # normalized (no 'ths'); caller does remap
    type: str | None = None,
    subtype: str | None = None,
    cold_fill: bool = False,    # opt-in lazy fill for zhitu
    manager=None,
) -> tuple[list[dict], list[str], str]:
    """Single source of truth for stock→boards reverse lookup.

    Returns:
        (entries, cold_sources, origin_summary)
        - entries: list of {code, name, type, subtype, source}
                   每条带 source 字段（因为多源合并是常态）
        - cold_sources: subset of `sources` with no data after cold_fill attempt
                        永远返回 list（空 list = 全部命中）
        - origin_summary:
            - "persistence" — 所有 entry 都来自 SQLite 缓存
            - "<fetcher>"   — 单 source 场景；触发了 cold-fill
            - "mixed"       — 多 source 场景；混合了 cache 和 fetcher
            - ""            — 无 entry

    Caller 决定顶层 source 字段如何呈现：
        - 单 source 场景：透传 origin_summary（保持与现有 /boards 端点一致的语义）
        - 多 source 场景：覆盖为 "merged"（统一对外标签）
    """
```

**两条调用路径**：

```python
# /stocks/{code}/boards (new unified endpoint)
boards, cold, origin = stock_board_cache.get_stock_memberships(
    stock_code=stock_code,
    sources=normalized_sources,
    type=type,
    subtype=subtype,
    cold_fill=cold_fill,
    manager=get_manager(),
)
top_source = (
    "merged" if len(normalized_sources) > 1 else origin
)
return StockBoardsResponse(
    stock_code=stock_code,
    source=top_source,
    data=[StockBoardInfo(...) for b in boards],
    cold_sources=cold,
)
```

```python
# /stocks/{code}/board-memberships (deprecated wrapper, schema 不变)
boards, cold, _ = stock_board_cache.get_stock_memberships(
    stock_code=stock_code,
    sources=list(stock_board_cache.VALID_SOURCES),  # all
    type=type,
    subtype=subtype,
    cold_fill=False,  # legacy behavior: never lazy-fill
    manager=get_manager(),
)
by_source: dict[str, list[BoardMembershipEntry]] = {}
for b in boards:
    by_source.setdefault(b["source"], []).append(BoardMembershipEntry(...))
return BoardMembershipsResponse(
    stock_code=stock_code,
    memberships=by_source,
    cold_sources=cold,
)
```

#### 3.2.4 `cold_sources` 计算规则

```python
# 1. 读 membership：得到每个 source 的行数
present = {src for src in sources if has_rows(src)}
# 2. 若 cold_fill 且 src==zhitu 且 not present: 尝试 lazy fill
if cold_fill and "zhitu" in sources and "zhitu" not in present:
    fill_zhitu(stock_code)  # may write to membership
    present = {src for src in sources if has_rows(src)}  # re-check
# 3. cold = sources - present
cold = [s for s in sources if s not in present]
```

**关键不变量**：请求 sources = present ∪ cold，且二者 disjoint。

### 3.3 `/stocks/{code}/board-memberships` 降级为 wrapper

**不改 schema**：响应字段 `memberships / cold_sources` 完全保持现有 `BoardMembershipsResponse` 形状。

**OpenAPI 标注**：

```python
@endpoint_meta(
    summary="股票所属板块（跨源视图，已弃用，请改用 /stocks/{code}/boards）",
    deprecated=True,  # FastAPI 支持
    ...
)
```

**deprecation timeline**：
- 本 PR: 标 deprecated，但 100% 工作
- 下一个 minor 版本: OpenAPI explorer 加删除警告横幅
- 下一个 major 版本: 删除端点

---

## 4. 数据模型

**零 DB schema 变更**。`stock_board_membership` 表的 `source` 列继续存 normalized 后的 fetcher 名（`zzshare`），`ths` 永远不进 DB。

---

## 5. 文件改动清单

| 文件 | 改动 |
|---|---|
| `stock_data/api/routes/boards.py` | 4 个 `Literal` 加 `"ths"`；4 处 remap；`/stocks/{code}/boards` route 改造支持 CSV source + cold_fill；`/stocks/{code}/board-memberships` route 改造为 wrapper；2 个 `@endpoint_meta` summary 改写 |
| `stock_data/api/schemas.py` | `StockBoardInfo` 加 `source: str` 字段；`StockBoardsResponse` 加 `cold_sources: list[str]` 字段；`source` 字段语义扩展为 `merged` |
| `stock_data/data_provider/persistence/board.py` | 新增 `get_stock_memberships()` helper；保留 `get_stock_boards_with_lazy_fill()` 作为内部 helper（被新函数调用） |
| `tests/test_boards.py` | 新增 `?source=ths` alias 用例；新增 CSV source 用例；新增 `cold_fill` 用例；新增 wrapper 兼容用例 |
| `tests/test_persistence_board.py` | 新增 `get_stock_memberships()` 单元测试；新增 `_parse_source_csv` 单元测试（如果放 persistence） |
| `docs/superpowers/specs/2026-07-02-...md` | 本文件 |

> **Explorer HTML 不在本次范围**：explorer 当前对 `BoardMembershipsResponse` 已经展示 `cold_sources` 字段；`StockBoardsResponse` 增加的 `cold_sources` 和 per-entry `source` 是新增字段，但 explorer 用通用 JSON viewer 渲染，新字段自动出现。无需改 HTML（除非后续要做 UI 强化如"折叠按 source 分组"，那是独立需求）。

---

## 6. 测试策略

### 6.1 单元测试

- `?source=ths` remap 后 DB 查询用 `source='zzshare'`（不污染表）
- `?source=ths,eastmoney` 同时接受两种写法且行为一致
- `?cold_fill=true` + `source=zhitu` + 冷数据 → 触发 lazy fill，写回 DB
- `?cold_fill=false` + `source=zhitu` + 冷数据 → 不报错，`cold_sources=['zhitu']`
- 新 helper `get_stock_memberships` 的 8 种参数组合（source 数量 × cold_fill）

### 6.2 集成测试

- `/stocks/{code}/boards?source=zzshare` 与 `?source=ths` 返回字节相同响应（除 `source` 顶层字段保持 `zzshare`）
- `/stocks/{code}/board-memberships` 调用一次 `/stocks/{code}/boards` 共享 helper 后 reshape，响应字段完整

### 6.3 兼容性测试

- 现有 `/stocks/{code}/boards?source=zzshare` 调用方继续工作（响应新增 `source` per-entry 字段、`cold_sources` 字段——属于 schema 扩展，非破坏）
- 现有 `/stocks/{code}/board-memberships` 调用方继续工作（schema 完全不变）

---

## 7. 迁移路径

| 阶段 | 内容 | 风险 |
|---|---|---|
| 本 PR | alias + 端点合并 + wrapper 兼容 | 中（schema 扩展非破坏，但逻辑改动面大） |
| 后续 minor | OpenAPI 标 deprecated + explorer 警告横幅 | 低 |
| 后续 major | 删除 `/stocks/{code}/board-memberships` | 已有 wrapper 阶段充分告知 |

---

## 8. 向后兼容性

### 8.1 Schema 兼容性

| 端点 | 变化 | 兼容性 |
|---|---|---|
| `/boards` | 加 `"ths"` 到 Literal；一行 remap | ✅ 完全兼容 |
| `/boards/{code}/stocks` | 同上 | ✅ 完全兼容 |
| `/boards/{code}/history` | 同上 | ✅ 完全兼容 |
| `/stocks/{code}/boards` | `?source=` 必填 → 可选；新增 per-entry `source` + 顶层 `cold_sources` | ⚠️ 字段扩展，非破坏（旧调用方忽略新字段；不传 source 自动聚合所有源——是行为变化不是 schema 破坏） |
| `/stocks/{code}/board-memberships` | 内部走 helper，schema 完全不变 | ✅ 完全兼容 |

### 8.2 行为兼容性

`/stocks/{code}/boards` 旧调用方（`?source=zzshare`）在新版继续工作：
- 单 source 行为保持（隐式合并只有它一个）
- 顶层 `source` 字段：单 source 时仍是 fetcher 名（`"zzshare"`）
- `cold_sources`：新增字段，旧调用方忽略即可
- per-entry `source`：新增字段，旧调用方忽略即可

**唯一行为变化**：缺省 source 时，旧版因 `source` 必填会 422；新版会聚合所有 source 返回。这只影响"忘了传 source"的 bug 调用方，不影响正常用法。

---

## 9. 评审决议（待用户确认）

- [ ] 同意 alias + 端点合并合并到一个 PR
- [ ] 同意 `/board-memberships` 降级为 wrapper，schema 不变
- [ ] 同意 `cold_fill` 显式 opt-in（告别 zhitu 隐式 lazy fill）
- [ ] 同意 per-entry `source` 字段（单源调用时的冗余信息）
- [ ] 同意 `cold_sources` 永远返回（即使是空 list）