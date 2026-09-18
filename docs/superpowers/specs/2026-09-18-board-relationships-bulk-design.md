# 板块-股票关系 bulk 查询端点

- **日期**: 2026-09-18
- **作者**: 协作设计会话（Claude + 用户）
- **状态**: 设计完成，待 implementation plan
- **范围**: 新增一个 POST 端点 + 一个 persistence helper + 测试 + manifest 自发现

## 背景与目标

`/api/v1/boards/{board_code}/stocks` 与 `/api/v1/stocks/{stock_code}/boards` 是一对单值端点，每次只能查 1 个 board 或 1 个 stock 的关系。当 agent 需要批量筛选"哪些板块包含这 100 只股票"或"这 50 个板块的成员有哪些"时，必须循环 N 次调用，效率低 + 无 batch 缓存。

新端点 `POST /api/v1/boards/relationships` 让客户端一次性提交 board_codes 与 stock_codes 两个 list（最大各 100 条），返回二者的关系并集。直接读 SQLite 持久层（`stock_board_membership`），不调用任何 fetcher。

## 设计决策记录

| # | 决策 | 理由 |
|---|---|---|
| 1 | POST + JSON body | codes 多时 URL 长度受限；body 更清晰 |
| 2 | `source` 必填且单值 | 单次只查一个 source；多源场景由 source-specific 端点承担 |
| 3 | 双向返回并集（不交集）| 客户端可自行聚合 |
| 4 | 不传则全量反，无 ceiling | 用户决策：若需更多数据，全量拉一次；不引入 StreamingResponse |
| 5 | 单 SQL OR 动态拼接 | 一次数据库往返；现有 XOR helper `read_membership` 不动 |
| 6 | 不写缓存 | 持久层即 source of truth；backfill 触发后立即可读；TTL 反而引入 staleness |
| 7 | flat row 列表（6 列）| 字段压缩；客户端按需 groupby |
| 8 | 不新增 streaming/pagination v1 | YAGNI；若未来需要再加 |

## 路由契约

```
POST /api/v1/boards/relationships
Content-Type: application/json

{
  "source": "ths",                  // required, Literal[ths,zzshare,eastmoney,zhitu]
  "board_codes": ["885595", ...],   // optional, list[str], max_length=100
  "stock_codes":  ["600519", ...]    // optional, list[str], max_length=100
}
```

校验：
- `source` 不在合法集 → FastAPI Literal 422（自带）
- `board_codes` 长度 >100 → FastAPI `max_length` 422
- `stock_codes` 长度 >100 → FastAPI `max_length` 422
- 两者都缺省 → 全量模式（允许）
- 任一非空 → 过滤模式（OR 关系）

## 响应模型

```json
{
  "source": "ths",
  "count": 12345,
  "rows": [
    {
      "board_code": "885595",
      "board_name": "煤炭概念",
      "board_type": "concept",
      "stock_code": "600188",
      "stock_name": "兖矿能源",
      "refreshed_at": "2026-09-14T03:21:00"
    }
  ]
}
```

字段约束：
- `count` 始终等于 `len(rows)`（无 ceiling）
- 每行 6 字段（按用户偏好减列，去掉 `subtype` 与 per-row `source`）
- 顶层 `source` 保留（回显查询源，便于客户端校验）
- `refreshed_at` 为 SQLite CURRENT_TIMESTAMP 原始字符串（UTC），无时区歧义

## Persistence helper

新增 `stock_data/data_provider/persistence/board.py::read_memberships_by_codes`:

```python
def read_memberships_by_codes(
    board_codes: list[str] | None,
    stock_codes: list[str] | None,
    source: str,
) -> list[dict[str, Any]]:
    """Bulk OR-query stock_board_membership.

    Returns rows matching (board_code ∈ board_codes) OR (stock_code ∈ stock_codes),
    filtered by source. Empty board_codes or stock_codes means "no filter on
    that axis". Both empty returns:
      SELECT … WHERE source = ?
    (i.e. all rows for the source).

    Returns 6 columns: board_code, stock_code, board_name, stock_name,
    board_type, refreshed_at. Sort: ORDER BY board_code, stock_code
    (stable for pagination/streaming if added later).
    """
    init_schema()
    clauses: list[str] = ["source = ?"]
    params: list[Any] = [source]
    if board_codes:
        placeholders = ",".join("?" * len(board_codes))
        clauses.append(f"board_code IN ({placeholders})")
        params.extend(board_codes)
    if stock_codes:
        placeholders = ",".join("?" * len(stock_codes))
        clauses.append(f"stock_code IN ({placeholders})")
        params.extend(stock_codes)

    sql = (
        "SELECT board_code, stock_code, board_name, stock_name, "
        "       board_type, refreshed_at "
        "FROM stock_board_membership "
        f"WHERE {' AND '.join(clauses)} "
        "ORDER BY board_code, stock_code"
    )
    cursor = get_connection().execute(sql, params)
    return [dict(r) for r in cursor.fetchall()]
```

**不修改** `read_membership`：保持 XOR 契约 + 8 列结构以兼容现有调用方。

## 路由实现

文件：`stock_data/api/routes/boards.py`

```python
class BoardRelationshipRow(BaseModel):
    board_code: str
    board_name: str
    board_type: str
    stock_code: str
    stock_name: str
    refreshed_at: str


class BoardRelationshipsRequest(BaseModel):
    source: Literal["ths", "zzshare", "eastmoney", "zhitu"]
    board_codes: list[str] = Field(default_factory=list, max_length=100)
    stock_codes: list[str] = Field(default_factory=list, max_length=100)


class BoardRelationshipsResponse(BaseModel):
    source: str
    count: int
    rows: list[BoardRelationshipRow]


@router.post(
    "/boards/relationships",
    response_model=BoardRelationshipsResponse,
    tags=["boards"],
)
@endpoint_meta(
    summary="板块-股票双向关系 bulk 查询 (persistence 直读; board_codes/stock_codes 任一可空; 若二者皆空返回该 source 全量)",
    markets=["csi"],
    capabilities=[],
)
@map_errors
def post_board_relationships(payload: BoardRelationshipsRequest) -> BoardRelationshipsResponse:
    rows = stock_board_cache.read_memberships_by_codes(
        board_codes=payload.board_codes or None,
        stock_codes=payload.stock_codes or None,
        source=payload.source,
    )
    return BoardRelationshipsResponse(
        source=payload.source,
        count=len(rows),
        rows=[BoardRelationshipRow(**r) for r in rows],
    )
```

schemas 注册在 `stock_data/api/schemas.py` 末尾。

## 错误处理

| 异常 | 来源 | 状态码 | 错误码 |
|---|---|---|---|
| `Literal` 违反 | FastAPI 自带 | 422 | (FastAPI default) |
| `max_length` 违反 | FastAPI 自带 | 422 | (FastAPI default) |
| `sqlite3.Error` | 数据库 | 500 | `internal_error` (via @map_errors) |

**不存在 → 空 rows**: bulk 端点的"不存在"语义不同于单值端点。所有 board_codes / stock_codes 都 miss 时返回 `{count: 0, rows: []}`。

## 测试计划

`tests/test_board_relationships.py`：

1. **正向**: `board_codes=["885595"]` → 每行 `board_code == "885595"`
2. **反向**: `stock_codes=["600519"]` → 每行 `stock_code == "600519"`
3. **双向并集**: 两集合同时传；返回的行 ⊆ forward ∪ reverse
4. **去重**: (board_code, stock_code) 联合唯一约束 → 响应无重复行
5. **空入参 → 全量**: 两列表都空 + `source="ths"` → 返回该 source 全量；`count` 等于实际行数
6. **source 校验**: 不在 Literal → 422
7. **max_length**: 101 条 → 422
8. **字段最小化**: 每行只 6 字段（无 `subtype`、无 per-row `source`）
9. **顶层 source echo**: 请求体 source == 响应顶层 source
10. **SQL 注入防护**: `board_codes=["', 'OR1=1", ...]` → 不应返回其他 source 行

测试隔离：
- 复用 session-scoped DB fixture（已有）
- 准备小型 seed：5 个 board × 3 个 stock = 15 行
- 不依赖 live_network / live backfill

## Explorer manifest

- `/explorer/` 通过 `@endpoint_meta` 自动发现新端点
- 此端点 `capabilities=[]`（与 `/agent/*` 聚合端点一致），所以不展示 fetcher drill-down
  - 原因：`explorer/manifest.py` 对 `capabilities` 非空 + `fetcher_method is None` 的端点会回退到 `CAPABILITY_TO_METHOD[cap]`，从而把 capability 下每个 fetcher 的 drill-down 全列出来；我们不走 fetcher 链，所以用 `capabilities=[]` 让 manifest 走聚合分支（与 `/agent/*` 的 precedent 一致）
- 文档路径：`docs/superpowers/specs/2026-09-18-board-relationships-bulk-design.md`（本文）

## 不引入 / YAGNI

- 无 `StreamingResponse`（未来若需要再加）
- 无 pagination（未来若需要再加，保持 ORDER BY 稳定）
- 无 per-source 多 source 联合查询（未来若需要可拆多个请求或扩展）
- 无 type / subtype 过滤（返回 6 列，不含 subtype；type 在 board_type 字段）
- 无 `format=md` 渲染（其他持久层直读端点也无 md）

## 兼容性与风险

| 风险 | 缓解 |
|---|---|
| 100k 行全量响应 | 用户决策不设上限；若未来成问题再加 LIMIT |
| 全表扫 | `stock_board_membership` 当前 ~70k 行；单 SQL ORDER BY 实测 < 50ms |
| 新 helper 行为漂移 | 与 `read_membership` 完全分离；签名不同无歧义 |
| 测试种子数据缺失 | 测试用 fixture 单独 seed，不依赖 backfill |

## 实施步骤概要

1. **Persistence 层**: 新增 `read_memberships_by_codes` 到 `stock_data/data_provider/persistence/board.py`
2. **Schema 层**: 在 `stock_data/api/schemas.py` 末尾新增 3 个 Pydantic 模型
3. **Route 层**: 在 `stock_data/api/routes/boards.py` 末尾新增 `post_board_relationships`
4. **测试**: 新增 `tests/test_board_relationships.py`
5. **验证**: 启动 server → 调 POST /api/v1/boards/relationships 验证响应
6. **提交**: 按 CLAUDE.md skip-branch 规则，所有 `*.md` 改动直接 commit master；Python 代码走 feat/* 分支