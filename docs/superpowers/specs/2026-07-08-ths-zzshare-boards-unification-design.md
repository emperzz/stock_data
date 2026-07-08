# THS / Zzshare Boards 服务端统一设计

> 日期: 2026-07-08
> 状态: 待用户审阅
> 范围: 把 boards 端点(`/boards`、`/boards/{code}/stocks`)对外的 `source` 收窄到 `ths` 单一值;DB 层 source 列写 `ths`;内部把 zzshare 改造成"补 platecode 的辅助源"和"include_quote=False 时的 stocks 优先源"。`/stocks/{code}/boards` 与 `/boards/{code}/history` 不在本次范围(本来 zzshare alias 行为继续生效)。
> 性质: **路由层 + 持久层 helper 调整**。零 fetcher 实现侵入,零 DB schema 变更,零 capability flag 改动。

---

## 1. 问题陈述

### 1.1 同花顺分类的双重身份造成 API 表面分裂

`ThsFetcher` 和 `ZzshareFetcher` 都基于同花顺分类体系,但当前 API 表面把 `ths` 和 `zzshare` 当作两个独立 source 暴露给客户端:

- 客户端需要自己搞清楚"ths 和 zzshare 哪个数据更全"
- 同一份业务逻辑(板块清单)对应两个 source,容易在客户端代码里写错
- 路由层有四套不同的 alias 方向(`ths→zzshare`、`zzshare→ths`、还有 alias-map 不到的情况),心智负担重

### 1.2 THS 概念板块的 platecode 覆盖不全

`ThsFetcher._fetch_ths_concept_boards()`(ths_fetcher.py:1164)合并 `gnSection` + sidebar 两源,得到约 383 个概念板块,但其中 **88 个 sidebar-only 行没有 platecode**(只有 cid)。这部分数据如果只用 THS,客户端拿不到 platecode 去做 board-history 等下游查询。

`ZzshareFetcher.get_all_boards()` 拿到的每行都带 plate_code(885xxx/881xxx,语义等同于 THS platecode)。如果把 zzshare 当作 platecode 维度的 backfill 源,可以补全这 88 个缺口。

### 1.3 `/boards/{code}/stocks` 的主备策略混乱

- `include_quote=False` 时:ZzshareFetcher 的 `plates_stocks` 更轻量(SDK,无需 v-token),但当前实现没在 include_quote=False 时优先用它
- `include_quote=True` 时:ThsFetcher 的 q.10jqka.com.cn AJAX 自带 quote 字段,更优
- 当前实现两个 source 各自独立走,无主备 fallback

### 1.4 不同 source 的 board_code 语义错位

THS 内部有两套 code:
- **cid**(300xxx 概念 / 881xxx 行业):`ThsFetcher.get_board_stocks` 实际接收的参数(`q.10jqka.com.cn/gn/detail/code/{slug}/`)
- **platecode**(885xxx 概念 / 881xxx 行业):`ThsFetcher.get_board_history` 与 K 线 d.10jqka.com.cn 使用的参数

公开 API 当前接受的是 cid(THS 概念 slug);这跟 eastmoney 的 `BKxxxx`、zzshare 的 `plate_code`、zhitu 的 slug 都不一样,跨 source 一致性差。

---

## 2. 目标与非目标

### 目标

1. **boards 端点对外只接受 `source=ths`**:客户端不再需要选 ths 还是 zzshare;传 `zzshare` 直接 400(`invalid_source`)。
2. **DB 写单一 source**:持久层所有 boards 写都落到 `source='ths'`,`stock_board` 和 `stock_board_membership` 表里不再有 `source='zzshare'` 行。
3. **`/boards` 内部用 zzshare 补 platecode**:ThsFetcher 拿 383 行,其中 88 行无 platecode;ZzshareFetcher 拿 ~800+ 行(全带 plate_code);按 name 合并,ths 行优先(保留 cid + 实时字段),缺失的 platecode 从 zzshare 同行回填;zzshare 独有的行追加在末尾。
4. **`/boards/{code}/stocks` 按 include_quote 切主备**:`include_quote=False` 走 ZzshareFetcher(快);`include_quote=True` 走 ThsFetcher(自带 quote);失败走另一条作 fallback。
5. **公开 board_code 统一为 platecode**:`/boards/{code}/stocks?source=ths` 收的 `board_code` 是 THS platecode(885xxx 概念 / 881xxx 行业);server 内部按需反查 cid(始终走 persistence,不硬编码分支)。
6. **测试清理**:旧 `ths→zzshare` alias 行为测试、`source=zzshare` 在 boards 端点被接受的测试 → 删除或改写。

### 非目标

- `/stocks/{code}/boards` 行为变更(那条路径 zzshare→ths alias 继续生效,reverse lookup 的代码系统是另一回事)
- `/boards/{code}/history` 行为变更(zzshare→ths alias 继续生效,因为 ZzshareFetcher 无 K-line 实现)
- ZzshareFetcher / ThsFetcher 实现删除(用作 fallback / 补全源,继续存在)
- DB schema 迁移(`STOCK_DB_INIT=true` 启动时全 drop,新写只写 `ths`,自然清空)
- 老的 `source='zzshare'` 历史 row(项目当前是 dev 个人项目,新启动时重置)

---

## 3. 设计

### 3.1 公共 API 收窄(路由层)

`api/routes/boards.py` 中与 boards 端点相关的 `source` Literal 全部移除 `"zzshare"`:

```python
# 改前
source: Literal["ths", "eastmoney", "zhitu", "zzshare"] = Query(...)
# 改后
source: Literal["ths", "eastmoney", "zhitu"] = Query(...)
```

`_resolve_source()`、`normalize_board_stocks_source()` 两个 helper 都把 `"zzshare"` 从合法值里剔除,传 `zzshare` 直接抛 `HTTPException(400, detail={"error": "invalid_source", ...})`。

**注意:** `_parse_source_csv()`(boards list 用的 CSV 解析)实际上是 dead code(全项目搜索只有定义,无 caller);本次顺手删除以减少测试维护负担。如确认它是为未来多源聚合预留,可在 PR review 中讨论保留,默认删。

未触碰:
- `_resolve_board_history_source`(/boards/{code}/history)— 仍保留 `zzshare→ths` alias
- `_parse_stock_boards_source_csv`(/stocks/{code}/boards)— 仍保留 `zzshare→ths` alias
- `normalize_stock_board_source`(/stocks/{code}/boards)— 同上

### 3.2 `VALID_SOURCES` 收窄(持久层)

```python
# 改前
VALID_SOURCES: tuple[str, ...] = ("eastmoney", "zhitu", "zzshare", "ths")
# 改后
VALID_SOURCES: tuple[str, ...] = ("ths", "eastmoney", "zhitu")  # ths 第一,反映 priority

_BOARD_STOCKS_VALID_SOURCES: tuple[str, ...] = ("ths", "eastmoney", "zhitu")
# _STOCK_BOARDS_VALID_SOURCES / _BOARD_HISTORY_VALID_SOURCES 保持不变(reverse / history 端点未动)
```

`VALID_SUBTYPES_BY_SOURCE["zzshare"]` **保留** — 内部 merge helper 仍需知道 zzshare 的 subtype 集合(虽然不再经 route 校验,但 merge 阶段要走 `manager.get_all_boards(source="zzshare")`,需要传合法的 subtype)。

### 3.3 新增 helper:`fetch_boards_with_zzshare_backfill()`

`persistence/board.py` 新增:

```python
def fetch_boards_with_zzshare_backfill(
    board_type: str | None,
    refresh: bool,
    include_quote: bool,
    subtype: str | None,
    manager,
) -> list[dict]:
    """Return unified board list with ths as primary, zzshare as platecode backfill.

    Behavior:
    - Always writes source='ths' to the cache (single source).
    - Always calls both ThsFetcher and ZzshareFetcher; merge by name.
    - When board_type is None, iterates every type VALID_SUBTYPES_BY_SOURCE['ths']
      supports (currently concept + industry; index/special are NOT exposed by
      ths — they fall through to persistence for eastmoney/zhitu callers).
    - When subtype is given, applies after merge (post-filter in memory).
    - When include_quote=True, the include_quote flag is forwarded to both
      ThsFetcher and ZzshareFetcher; zzshare's quote fields are sparse
      (only change_pct/amount/total_mv) so post-merge rows may have None
      for fields THS doesn't supply either.

    Returns:
        list of {code, name, type, subtype, source, platecode, ...quote}
        where source='ths' on every row (zzshare rows are tagged with the
        same label after merge; the distinction is internal).

    Raises:
        DataFetchError: ThsFetcher's call failed. ZzshareFetcher failures
        are logged at WARNING and treated as empty list (best-effort
        backfill; primary path is THS).
    """
```

调用流程:
1. `ths_rows = manager.get_all_boards(source="ths", board_type=bt, subtype=None, include_quote=include_quote)` — 必须成功,失败 raise
2. `zzshare_rows = manager.get_all_boards(source="zzshare", board_type=bt, subtype=None, include_quote=include_quote)` — 包 try/except,失败回 `[]` 并 log WARNING
3. `merged = _merge_ths_zzshare_by_name(ths_rows, zzshare_rows)` — 见下
4. (可选)按 subtype 在内存里 filter
5. 返回 merged(由 caller 写 cache)

### 3.4 新增 helper:`_merge_ths_zzshare_by_name()`

```python
def _merge_ths_zzshare_by_name(
    ths_rows: list[dict],
    zzshare_rows: list[dict],
) -> list[dict]:
    """Merge THS(primary) + ZZSHARE(platecode backfill) by board name.

    Rules (verified 2026-07-08):
    - Index zzshare rows by name → platecode (in-memory dict).
    - For each ths row:
        * If ths_row['platecode'] is None and zzshare has same name
          → copy platecode from zzshare into ths row (in-place dict update).
        * Otherwise keep ths row as-is (it already has platecode, or
          zzshare doesn't have a matching name — the row is THS-only).
    - For each zzshare row not matched by any ths row (by name) →
      append as-is. The row carries its own plate_code as 'code'
      (no cid available; clients see this as a platecode-only row).
    - Final dedup by (code, name) within the merged list to guard
      against upstream double-emit (rare; seen once in THS gnSection
      duplicates per 2026-07-08 notes).
    - All output rows are tagged with source='ths' regardless of origin
      (the public surface unifies them; DB writes follow).

    Empty input edge cases:
    - ths_rows empty + zzshare_rows empty → []
    - ths_rows empty + zzshare_rows non-empty → all zzshare rows appended
    - ths_rows non-empty + zzshare_rows empty → ths rows returned as-is
    """
```

### 3.5 改写 `get_board_list()`(去掉 `source` 形参)

`persistence/board.py::get_board_list()` 当前签名:
```python
def get_board_list(
    board_type: str | None,
    source: str,        # ← 删
    refresh: bool = False,
    ...
)
```

改后:
```python
def get_board_list(
    board_type: str | None,
    refresh: bool = False,  # source 不再是入参,内部 hardcode "ths"
    include_quote: bool = False,
    subtype: str | None = None,
    manager=None,
) -> tuple[list, str]:
    # ...
    boards, fetcher_source = fetch_boards_with_zzshare_backfill(
        board_type=board_type, refresh=refresh,
        include_quote=include_quote, subtype=subtype, manager=manager,
    )
    if boards:
        update_cached_boards(board_type, source="ths", boards=boards)
    return boards, "ths"  # origin 永远 'ths' (无论内部是否 merge 了 zzshare 行)
```

注意 origin 永远返回 `"ths"`,与"source 写 ths"对齐 — 不暴露内部 merge 痕迹。

`_get_all_board_types()`(被 `get_board_list(board_type=None)` 调)同样改:删 `source` 形参,内部传 `manager` 给新 helper,迭代每个支持的 type。

### 3.6 新增 helper:`_resolve_ths_cid_from_platecode()`

`persistence/board.py` 新增:

```python
def _resolve_ths_cid_from_platecode(platecode: str) -> str | None:
    """Resolve THS code (cid) for a platecode via the stock_board cache.

    Single SELECT against stock_board. The same query handles both
    concept boards (cid ≠ platecode: 300xxx vs 885xxx) and industry
    boards (cid == platecode: 881xxx) — for industry the row's
    ``code`` column stores 881xxx, so the lookup returns the same
    value back. No special-casing by length or prefix; the data
    layer is the single source of truth.

    Args:
        platecode: THS platecode (e.g. '885642' for concept,
            '881270' for industry).

    Returns:
        The THS code (cid for concept, == platecode for industry),
        or None if no row matches. Callers treat None as
        "no cid available — skip ThsFetcher path, rely on zzshare".
    """
    init_schema()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT code FROM stock_board "
        "WHERE platecode = ? AND source = 'ths' LIMIT 1",
        (platecode,),
    )
    row = cursor.fetchone()
    return row["code"] if row else None
```

冷启动依赖:这个 helper 强依赖 `stock_board` 表里有 platecode 行 — 而 platecode 行由 `get_all_boards`(ThsFetcher + zzshare backfill)写入。冷启动时(数据库完全空),反查必然 miss,后续 fallback 链兜底。

### 3.7 新增 helper:`fetch_board_stocks_with_zzshare_fallback()`

`persistence/board.py` 新增:

```python
def fetch_board_stocks_with_zzshare_fallback(
    board_code: str,
    include_quote: bool,
    manager,
) -> tuple[list[dict], str]:
    """Get stocks for a board with source-aware primary/fallback order.

    Strategy:
    - include_quote=False (default): ZzshareFetcher.plates_stocks first
      (anonymous SDK call, fast, no v-token required). On empty/error,
      fallback to ThsFetcher.
    - include_quote=True: ThsFetcher first (THS AJAX returns quote
      fields natively). On empty/error, fallback to ZzshareFetcher.
    - When ThsFetcher is invoked, look up the cid via
      _resolve_ths_cid_from_platecode; if not found, skip THS path
      and return zzshare's result (or empty).
    - ThsFetcher's input is the cid; ZzshareFetcher's input is the
      platecode (which is what the public API hands us).

    Returns:
        (stocks, source) — source is the fetcher name that served
        the response (always 'ths' or 'zzshare'; caller exposes it
        as-is, but writes to stock_board_membership with source='ths').

    Raises:
        DataFetchError: only when both fetcher paths raise a Hard error
        (network / 5xx). Empty results are returned as-is (treated as
        "no stocks in this board" → caller → 404).
    """
```

调用流程(以 `include_quote=True` 为主):
1. `cid = _resolve_ths_cid_from_platecode(board_code)`
2. 如 `cid`:尝试 `manager.get_board_stocks(board_code=cid, source="ths", include_quote=True)` — 返回非空 → (`stocks`, "ths")
3. 如空 / 异常 / `cid is None`:尝试 `manager.get_board_stocks(board_code=board_code, source="zzshare", include_quote=True)` — 返回非空 → (`stocks`, "zzshare")
4. 都失败 → raise / 返回 `[]`(由 caller 决定)

`include_quote=False` 时主备顺序反转。

### 3.8 改写 `get_board_stocks()`(去掉 `source` 形参,内部按 include_quote 切主备)

```python
def get_board_stocks(
    board_code: str,
    refresh: bool = False,
    include_quote: bool = False,
    manager=None,
) -> tuple[list, str]:
    # cache hit path 不变:从 stock_board_membership WHERE source='ths' 读
    # cache miss / refresh:调 fetch_board_stocks_with_zzshare_fallback(...)
    stocks, origin = fetch_board_stocks_with_zzshare_fallback(
        board_code=board_code, include_quote=include_quote, manager=manager,
    )
    if stocks:
        update_cached_board_stocks(board_code, source="ths", stocks=stocks)
    return stocks, "ths"  # DB 写 source='ths',但响应 origin 反映实际命中的 fetcher
```

**关于 origin 字段**:cache hit → `"persistence"`;cache miss → 实际命中的 fetcher 名(`"ths"` 或 `"zzshare"`)。响应里的 `data_source` 字段保留这两类信息(客户端可以看到是 ThsFetcher 还是 ZzshareFetcher 兜的底),但 DB 写死 `ths`。

### 3.9 路由层调用适配

`api/routes/boards.py::list_boards()` 和 `get_board_stocks()`:
- `source` Literal 收窄到 `("ths", "eastmoney", "zhitu")`
- `stock_board_cache.get_board_list(...)` 调用删 `source` 形参
- `stock_board_cache.get_board_stocks(...)` 调用删 `source` 形参
- `_resolve_source()` 直接 400 if `source == "zzshare"`

未触碰:
- `_resolve_board_history_source` 保留 `zzshare→ths` alias
- `_parse_stock_boards_source_csv` 保留 `zzshare→ths` alias
- `get_board_history` 路由
- `get_stock_boards` 路由

### 3.10 endpoint_meta summary 更新

`/boards`:
- 改前: `"板块清单（支持实时报价、排序、截断）"`
- 改后: `"板块清单 (ths; 内部合并 zzshare 补 platecode) — ?source=zzshare 已下线"`

`/boards/{code}/stocks`:
- 改前: `"板块成分股 (ths/eastmoney/zhitu/zzshare — no alias)"`
- 改后: `"板块成分股 (ths/eastmoney/zhitu; ?source=zzshare 已下线; include_quote=false 走 zzshare 优先)"`

---

## 4. 端点行为矩阵(改后)

| 端点 | `?source=zzshare` | `?source=ths` | 备注 |
|---|---|---|---|
| `/boards` | **400 invalid_source** | 200,内部 ThsFetcher 主 + ZzshareFetcher 补 platecode | DB 写 ths |
| `/boards/{code}/stocks` | **400 invalid_source** | 200,按 include_quote 切主备 | DB 写 ths |
| `/stocks/{code}/boards` | 200,alias 到 ths(reverse lookup) | 200,直接 ths | 未触碰 |
| `/boards/{code}/history` | 200,alias 到 ths(K-line) | 200,直接 ths | 未触碰 |

`/boards?source=eastmoney` / `?source=zhitu` 行为不变(各自走原 fetcher)。

---

## 5. 数据流图

### 5.1 `GET /api/v1/boards?type=concept&source=ths`

```
list_boards(type='concept', source='ths')
  → _resolve_source('ths') == 'ths'  ✓
  → stock_board_cache.get_board_list(board_type='concept', refresh=..., include_quote=..., subtype=...)
    → cache hit? read stock_board WHERE source='ths' AND board_type='concept'
      → return cached, origin="persistence"
    → cache miss: fetch_boards_with_zzshare_backfill(board_type='concept', ...)
      → ths_rows = manager.get_all_boards(source='ths', board_type='concept')    # 主
      → zzshare_rows = manager.get_all_boards(source='zzshare', board_type='concept')  # 辅(try/except)
      → merged = _merge_ths_zzshare_by_name(ths_rows, zzshare_rows)
      → update_cached_boards(board_type='concept', source='ths', boards=merged)
      → return merged, origin="ths"
```

### 5.2 `GET /api/v1/boards/885642/stocks?source=ths&include_quote=true`(概念)

```
get_board_stocks(board_code='885642', source='ths', include_quote=True)
  → _resolve_source('ths') == 'ths'  ✓
  → stock_board_cache.get_board_stocks(board_code='885642', refresh=..., include_quote=True)
    → cache hit? read stock_board_membership WHERE source='ths' AND board_code='885642'
      → return cached, origin="persistence"
    → cache miss: fetch_board_stocks_with_zzshare_fallback(board_code='885642', include_quote=True)
      → include_quote=True: ThsFetcher 优先
        → cid = _resolve_ths_cid_from_platecode('885642')
          → SQL: SELECT code FROM stock_board WHERE platecode='885642' AND source='ths'
          → 命中:code='301558'(概念 cid)
        → ths_rows = manager.get_board_stocks(board_code='301558', source='ths', include_quote=True)
        → 非空:return (ths_rows, "ths")
        → 空 / 异常 → fallback:
          → zzshare_rows = manager.get_board_stocks(board_code='885642', source='zzshare', include_quote=True)
          → 非空:return (zzshare_rows, "zzshare")
      → update_cached_board_stocks(board_code='885642', source='ths', stocks=<result>)
      → return result, origin
```

### 5.3 `GET /api/v1/boards/881270/stocks?source=ths&include_quote=true`(行业)

```
... 同上,但 _resolve_ths_cid_from_platecode('881270') 查回 '881270'(== platecode,行业特点)
  → ThsFetcher.get_board_stocks(board_code='881270', source='ths', include_quote=True)
  → ThsFetcher 内部对行业无 q.10jqka AJAX 实现 → 返回 []
  → fallback: ZzshareFetcher.plates_stocks(plate_code='881270') → 返回行业成分股
  → origin="zzshare"(实际上是 fallback 命中)
```

### 5.4 `GET /api/v1/boards/999999/stocks?source=ths`(platecode 不存在)

```
fetch_board_stocks_with_zzshare_fallback(board_code='999999', include_quote=False)
  → cid = _resolve_ths_cid_from_platecode('999999')  → None
  → ZzshareFetcher.plates_stocks(plate_code='999999')  → []  (大概率也无)
  → 都空 → return ([], "")
  → route 端:not_found 404
```

### 5.5 `GET /api/v1/boards?source=zzshare`

```
list_boards(source='zzshare')
  → _resolve_source('zzshare')  → ValueError(Invalid source)
  → route 端:HTTPException(400, detail={"error": "invalid_source", "message": "..."})
```

---

## 6. 错误处理

| 场景 | 行为 |
|---|---|
| `source=zzshare` 在 boards 端点 | 400,`{"error": "invalid_source", "message": "Unknown source 'zzshare'. Valid sources: ['ths', 'eastmoney', 'zhitu']. 'zzshare' was unified under 'ths' on 2026-07-08."}` |
| ThsFetcher 失败,ZzshareFetcher 成功 | 不报错,返回 zzshare 行,origin="zzshare" |
| ThsFetcher 成功,ZzshareFetcher 失败 | 不报错,返回 ths 行(WARNING 日志),origin="ths" |
| 两边都失败 | 走 `_with_source` 的 DataFetchError 路径,5xx |
| `_resolve_ths_cid_from_platecode` 查不到(冷启动) | 跳过 ThsFetcher 路径,只走 ZzshareFetcher(可能仍返回 [] → 404) |
| 缓存写入失败 | 现有 `logger.error` + 抛出行为不变 |

---

## 7. 测试策略

### 7.1 新增测试

`tests/test_persistence_board_merge.py`(新):
- `test_merge_ths_wins_by_default` — 同一 name 同时存在于 ths/zzshare,ths 行全字段保留
- `test_merge_zzshare_backfills_missing_platecode` — ths 行 platecode=None,zzshare 同行 name 匹配 → platecode 回填
- `test_merge_zzshare_only_rows_appended` — zzshare 有但 ths 没有的 name → 追加
- `test_merge_dedup_by_code_and_name` — 同一 (code, name) 双发 → 保留一份
- `test_resolve_ths_cid_from_platecode_concept` — 概念:platecode=885642 → 返回 cid 301558
- `test_resolve_ths_cid_from_platecode_industry` — 行业:platecode=881270 → 返回 881270(同值)
- `test_resolve_ths_cid_returns_none_for_unknown` — 999999 → None

`tests/test_boards.py`(扩,新增 `TestThsOnly` class 替代被删的 `TestThsSourceAliasMatrix`):
- `TestThsOnly::test_boards_list_source_zzshare_returns_400` — 公共 source=zzshare → 400
- `TestThsOnly::test_boards_list_source_ths_only` — Literal 现在只收 ths/eastmoney/zhitu
- `TestThsOnly::test_board_stocks_source_zzshare_returns_400` — 同上
- `TestThsOnly::test_board_stocks_include_quote_false_prefers_zzshare` — 验证主备顺序
- `TestThsOnly::test_board_stocks_include_quote_true_prefers_ths` — 验证主备顺序
- `TestThsOnly::test_board_stocks_ths_fallback_when_zzshare_empty` — 验证 fallback
- `TestThsOnly::test_board_stocks_zzshare_fallback_when_ths_fails` — 验证 fallback
- `TestThsOnly::test_board_stocks_ths_path_translates_platecode_to_cid` — 验证反查(885642 → 301558)

### 7.2 删除/改写旧测试

`tests/test_boards.py`:
- **删除** `TestThsSourceAliasMatrix` 整 class(line 321-366,含 2 个 test)
  - `test_board_list_ths_aliases_to_zzshare` 行为已不成立
  - `test_board_stocks_ths_does_not_alias` 语义过时

`tests/test_boards_api.py`:
- **改写** `test_list_boards_source_zzshare_still_works` → `test_list_boards_source_zzshare_returns_400`
- **删除** `test_list_boards_zzshare_no_type_returns_all_supported_types`(基于 zzshare subtype 表的测试不再有意义)
- **改写** `test_list_boards_zzshare_type_special_returns_400`(现在 source 校验提前,error code 路径变了)
- **改写** `test_get_board_stocks_zzshare_still_works` → `test_get_board_stocks_source_zzshare_returns_400`
- **改写** `test_list_boards_source_ths_passes_ths_to_persistence`(现在 persistence 形参无 source)
- **改写** `test_get_board_stocks_ths_passes_ths_to_persistence`(同上)

`tests/test_boards_history_route.py`:**整文件不动**(/boards/{code}/history 未触碰,zzshare→ths alias 保留)

`tests/test_zzshare_fetcher.py`:**整文件不动**(ZzshareFetcher 实现保留)

`tests/test_stock_boards_reverse_route.py`:**不动**(/stocks/{code}/boards 未触碰)

`tests/test_eastmoney_fetcher_board.py` / `test_zhitu_fetcher_board.py`:**不动**(eastmoney / zhitu 行为未变)

---

## 8. 兼容性 / 迁移

- **API breaking**:`?source=zzshare` 在 `/boards` 和 `/boards/{code}/stocks` 现在返回 400
- **DB**:用户已说明 `STOCK_DB_INIT=true` 启动时全 drop,新写只写 `ths`,自然清空;不需要 SQL 迁移
- **内部 fetcher slug**:`zzshare` 仍存在于 `_slug_index`,manager 的 `_with_source(source="zzshare")` 仍能命中 ZzshareFetcher(merge helper 直调 manager)
- **未触碰端点**:`/stocks/{code}/boards` 与 `/boards/{code}/history` 的 `zzshare→ths` alias 行为完全保留
- **endpoint_meta 字段更新**:见 §3.10

---

## 9. 风险 / 已知限制

1. **冷启动延迟**:首次 `/boards` 调用会同时打 ThsFetcher + ZzshareFetcher 两个上游;如果 zzshare 端点慢,会增加冷启动 latency(约 +1-2s)。后续 cache hit 路径不受影响。
2. **ZZshareFetcher 失败模式**:`plates_rank` 偶尔返回空(已知 issue),merge helper 已经在 try/except 包了,失败只 log WARNING 不影响 ths 行。
3. **name 冲突**:极少数同中文名的 concept vs industry 板块会冲突(理论上 0 个,同花顺分类里 "概念" 和 "行业" 不会重名,但需监控);如发现,以 THS 行为准(ths 行先入 merged dict,后到的 zzshare 同名行只补 platecode 不替换)。
4. **ZZshareFetcher 行业 subtype**:`plates_rank(plate_type=14)` 返回的 industry 板块名跟 THS `/thshy/` 行业名是否完全一致?实测 2026-07-08 验证基本一致,边缘案例(改名 / 新增)由 THS 主行兜底。

---

## 10. 决策记录(本次拍板)

1. **方案选 A(路由适配 + 持久层合并),不选 B(删 ZzshareFetcher)** — 理由:用户需求 3、4 条明确要求 zzshare 提供补全 / fallback 价值,删掉就违背需求。
2. **boards 端点对外只接受 `ths`** — 公共 API 表面彻底收窄;`zzshare` 退化为内部 merge / fallback 源。
3. **DB source 写 `ths`** — 单一 source 列;`zzshare` row 不再产生。
4. **public board_code 收 platecode(885xxx/881xxx)**,server 内部按需反查 cid — 统一 input 形态;反查永远走 persistence,不硬编码 industry==cid 分支。
5. **删 `TestThsSourceAliasMatrix` 整 class**(用户确认 2026-07-08 chat)— 矩阵的 4 行里 2 行(boards-list、boards-stocks)已失效,另 2 行(history、reverse)在未触碰的端点里,与本次重构耦合度低,单独维护成本高于重写。改用更聚焦的 `TestThsOnly` 替代,只测 `source=ths` 公共路径(见 §7.1 新增测试)。
6. **不加 DB schema 迁移** — `STOCK_DB_INIT=true` 自动重置,dev 阶段不需要迁移。
