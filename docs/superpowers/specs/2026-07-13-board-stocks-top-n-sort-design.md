# 板块成分股: top_n 截断 + 多字段排序 + ZZSHARE 补全（含 6 字段 schema 扩展）

> 日期: 2026-07-13
> 范围: `/boards/{board_code}/stocks` 端点 + `ThsFetcher.get_board_stocks` + `BoardStockInfo` schema
> 性质: **feature** —— 解决 THS 上游 50-stock hard cap + 暴露全部 11 个排序键 + 持久化层补全
> 关联 commit: 紧跟 `46ff6cb`（暴露 `amount`）和 2026-07-05 的 `change_amount` / `turnover_rate` 半修复
> 设计来源: 本会话 playwright 实测 THS 上游（302546 央企国企改革 / 板内 400 只成分股）

---

## 1. 目标与动机

**目标**: 在 `/boards/{board_code}/stocks` 端点上：
1. 暴露 THS 上游支持的**全部 11 个排序键**（之前只有默认涨跌幅）
2. 限制 `include_quote=true` 路径**最多报价 N 只**（N ≤ 50，匹配上游 hard cap）
3. 当 THS 上游看似截断（返回恰好 50 只）时**自动调一次 ZZSHARE 拉全量成员清单**补全无报价部分
4. 让响应清楚告诉 client 是否被截断（`quote_truncated` + `quote_top_n` echo 字段）
5. 让 `BoardStockInfo` schema 同步支持 6 个新增字段，与 fetcher 上游能力对齐

**为什么改**:
- 实测确认：THS 上游 `/gn/detail/code/{cid}/field/{code}/order/{dir}/page/N/ajax/1/` 端点支持 11 个不同的列代码：
  - `199112`=涨跌幅、`10`=现价、`19`=成交额、`48`=涨速、`407`=流通股、
    `264648`=涨跌、`526792`=振幅、`1771976`=量比、`1968584`=换手率、
    `2034120`=市盈率、`3475914`=流通市值
- 我之前的结论（只支持涨跌幅排序）是错的 —— 我误把 `field/199112` 当作"14 列字段集标识符"。它是涨跌幅的列代码。
- page 6+ 的 50 只 hard cap **与排序字段无关**：任何排序键，page 6+ 都返回 `<script>location.href=login` 的 JS stub（session 200，无 401/403）。
- 板块 301546 央企国企改革（platecode 885595）实测有 **400 只成分股**（40 页 × 10/页），远超 50。
- 当前 `ThsFetcher.get_board_stocks` 翻页硬 cap 是 `_MAX_BOARD_STOCKS_PAGES = 50`（= 500 attempts），实际大多被 upstream login wall 在 page 6 截断。client 不传 sort_by 时只拿到前 50 by 涨跌幅 desc，**无任何告警**。
- 当前 `include_quote=false` 路径走 ZZSHARE primary + THS fallback，能拿到全 400 只成员（无 quote 字段）。
- 当前 `BoardStockInfo` schema 只有 7 个 quote 字段（price/change_pct/change_amount/volume/amount/turnover_rate），6 个新字段（volume_ratio / amplitude / change_speed / pe_ratio / float_market_cap / free_float_shares）虽然上游有产但 schema 边界吞掉（类似 2026-07-05 的 "half-fix"）。

**非目标**:
- **不**改变 THS 50-stock 上游 hard cap —— 那是上游限制，我们只能补全不能突破
- **不**改 `BoardInfo` / `KLineData` / `BoardQuoteResponse` schema
- **不**缓存 quote 数据进 SQLite（CLAUDE.md "Don't cache realtime quote data"）—— 持久化层只写 (board_code, stock_code, stock_name)
- **不**为 ZZSHARE 端点加 sort_by —— 它没有等价排序字段
- **不**改 industry boards 行为 —— change_pct 也适用于行业，结构相同

---

## 2. 当前状态（仅改动相关）

### 2.1 Route 层（`stock_data/api/routes/boards.py:398-622`）

`GET /boards/{board_code}/stocks`：
- Query: `source`（required）, `include_quote`, `refresh`
- 无 sort_by / top_n 参数
- `include_quote=True` 时：调一次 `persistence.board.get_board_stocks(... include_quote=True)` 拿到成分股 + 一次 `manager.get_board_realtime(...)` 拿到板块实时行情
- 调 `fetch_board_stocks_with_zzshare_fallback`：
  - `source='ths'` + `include_quote=True` → **THS only**（无 ZZSHARE fallback）；失败 propagate 5xx
  - `source='ths'` + `include_quote=False` → **ZZSHARE primary → THS fallback**；失败 ZZSHARE 后 THS 重试
- 响应 `BoardStocksResponse`：除 `effective_source` / `quote_source` / `quote_error` 外，**无 `quote_truncated` 等截断指示字段**

### 2.2 Fetcher 层（`ths_fetcher.py:810-904`）

```python
def get_board_stocks(
    board_code: str, *,
    source: str | None = None,
    include_quote: bool = False,
    board_type: str | None = None,
    **kwargs,
) -> list[dict]:
    ...
    # 翻页循环（page 1..50，硬上限 500 attempts）
    for page in range(1, _MAX_BOARD_STOCKS_PAGES + 1):  # = 50
        try: rows = self._fetch_ths_board_stocks_page(board_code, page)
        except ThsBoundarySignalError as e:  # 仅吞 401/403
            if not all_rows: raise
            ...
            break
        if not rows: break
        all_rows.extend(rows)
    return all_rows
```

URL 模板：
```python
_BOARD_STOCKS_URL = (
    "https://q.10jqka.com.cn/gn/detail/code/{concept_id}"
    "/field/199112/order/desc/page/{page}/ajax/1/"
)
```

**问题**：
1. URL 硬编码 `field/199112/order/desc` —— 只支持涨跌幅降序，不支持其他 10 个排序键
2. 翻页硬 cap 50 × 10 = 500 —— 大多数 board 在 page 6 触发 login wall stub (`<script>location.href="//upass.10jqka.com.cn/login?redir=..."</script>`)，body 是空 tbody，循环 break 静默截断到 50
3. 没有 sort_by / top_n 参数化

### 2.3 Schema 层（`stock_data/api/schemas.py:338-353`）

```python
class BoardStockInfo(BaseModel):
    """Stock in a board, optionally with quote data."""
    code: str
    name: str = Field(default="", description="Stock name")
    price: float | None
    change_pct: float | None
    change_amount: float | None
    volume: int | None = Field(default=None, description="Volume (shares; only populated when upstream exposes it)")
    amount: float | None
    turnover_rate: float | None
```

**问题**：fetcher 当前只解析 14 列中的 9 列 (`ths_fetcher.py:731-745` —— tds 0,1,2,3,4,5,7,10 加 `volume=None`)，idx 6/8/9/11/12/13 完全**未解析**。所以 "fetcher 输出丢" 还不准确 —— 实际是 fetcher **从未读**这些列，不是 pydantic `extra="ignore"` 静默丢。本次改动需要 fetcher 解析 idx 6/8/9/11/12/13 → 输出 6 字段 → schema 同步接收。

### 2.4 持久化层（`persistence/board.py:896-998`）

`get_board_stocks(board_code, source, refresh, include_quote, manager)`：
- 内部判断 `needs_refresh = include_quote or refresh or _refresh_tracker.is_first_call(board_code + ":ths")`
- 不调 upstream 时：`return cached, "persistence", "ths", None`
- 调 upstream 时：调 `fetch_board_stocks_with_zzshare_fallback(board, source, include_quote, manager)`
- 拿到结果后：`update_cached_board_stocks(board_code, "ths", stocks)` —— 写 membership 表

**缓存写回 schema**（`update_cached_board_stocks`, line 1648）：
- 只写 `(board_code, source, stock_code, stock_name, board_name, board_type, subtype, refreshed_at)`
- **不写 quote 字段**（符合 CLAUDE.md）
- 因此 quote 字段必须 route 层即时拼装（cache-hit 路径下 quote 全 null）

---

## 3. 设计

### 3.1 API 改造

#### 3.1.1 新增 query 参数

```python
@router.get("/boards/{board_code}/stocks", ...)
def get_board_stocks(
    # ... 既有参数
    include_quote: bool = Query(False, ...),
    sort_by: Literal[
        "change_pct", "price", "turnover_rate", "volume_ratio",
        "amplitude", "change_amount", "change_speed", "amount",
        "pe_ratio", "float_market_cap", "free_float_shares",
    ] | None = Query(
        None,
        description=(
            "Sort by field. ONLY effective when include_quote=true. "
            "Defaults to 'change_pct desc' (THS upstream default). "
            "Field code mapping: change_pct=199112, price=10, "
            "turnover_rate=1968584, volume_ratio=1771976, amplitude=526792, "
            "change_amount=264648, change_speed=48, amount=19, "
            "pe_ratio=2034120, float_market_cap=3475914, free_float_shares=407."
        ),
    ),
    sort_order: Literal["asc", "desc"] = Query(
        "desc",
        description="Sort direction. ONLY effective when include_quote=true.",
    ),
    top_n: int = Query(
        50, ge=1, le=50,
        description=(
            "Max number of stocks to fetch live quotes for "
            "(mirrors THS upstream 50-stock hard cap). "
            "ONLY effective when include_quote=true. "
            "When the board's full member count exceeds top_n, "
            "the response carries 'quote_truncated=true' with the "
            "remaining stocks filled in from ZZSHARE (no quote fields)."
        ),
    ),
):
    # ... 在函数体内添加交叉校验 ...
```

#### 3.1.1.1 交叉校验规则

```python
# 在 get_board_stocks 路由函数入口处 (在 manager 调用之前):

# sort_by/top_n 与 include_quote 必须同时满足两个条件:
# (a) source == 'ths' 唯一实现 (eastmoney / zhitu / zzshare 的 get_board_stocks 无 sort_by)
# (b) include_quote == true (sort 字段都是 quote 字段; 无 quote 时 sort 无意义)

if (sort_by is not None or top_n != 50) and source != "ths":
    raise HTTPException(
        status_code=400,
        detail={
            "error": "invalid_combination",
            "message": (
                "sort_by / top_n are only supported with source='ths'. "
                f"Got source={source!r}."
            ),
        },
    )
if (sort_by is not None or sort_order != "desc" or top_n != 50) and not include_quote:
    # 与 /boards 同类端点的 `sort_by without include_quote → 400` UX 保持一致
    # (routes/boards.py:327-335)
    raise HTTPException(
        status_code=400,
        detail={
            "error": "invalid_combination",
            "message": (
                "sort_by / sort_order / top_n require include_quote=true. "
                "These parameters drive upstream quote fetching; "
                "without quotes the sort has no defined ordering."
            ),
        },
    )
```

**为什么 reject 而非 silently ignore**:
- 与 sibling 端点 `/boards` (`routes/boards.py:327-335`) 行为一致
- EastMoneyFetcher.get_board_stocks (`eastmoney/_boards_mixin.py:539-545`) 无 `**kwargs`,传 sort_by 会 `TypeError → 5xx`
- silent ignore 会让 client 误以为请求成功,后续调试成本高

#### 3.1.2 `BoardStocksResponse` 新增字段

```python
quote_truncated: bool = Field(
    default=False,
    description=(
        "True when the board has more members than top_n could fetch. "
        "The 'stocks' list contains the FULL cached member set; "
        "quote fields (price / change_pct / change_amount / volume / "
        "amount / turnover_rate / volume_ratio / amplitude / change_speed / "
        "pe_ratio / float_market_cap / free_float_shares) are populated "
        "only for the top_n by sort_by/sort_order."
    ),
)
quote_top_n: int | None = Field(
    default=None,
    description="Top_n applied (echoes back the route param).",
)
quote_sort_by: str | None = Field(
    default=None,
    description="sort_by applied (echoes back the route param).",
)
quote_sort_order: str | None = Field(
    default=None,
    description="sort_order applied (echoes back the route param).",
)
quote_total_in_board: int | None = Field(
    default=None,
    description=(
        "Total cached member count for this board (when known via cache). "
        "Always populated when > 0, including when include_quote=False — "
        "useful for clients deciding whether to issue a follow-up "
        "include_quote=true request for the full membership quote enrichment."
    ),
)
```

#### 3.1.3 行为矩阵

| source | include_quote | sort_by / sort_order / top_n | 行为 |
|---|---|---|---|
| `'ths'` | `False` | **必须全部默认值** | 走持久化层（first-call-of-day 触发 upstream：ZZSHARE primary → THS fallback）。返回 stock_board_membership 完整成员清单。所有 quote 字段为 null。回填 `quote_total_in_board=cached_count`（cached > 0 时），其余 echo 字段为 None。 |
| `'ths'` | `True`，boards 中全量成员 ≤ top_n | 生效 | THS 上游取 top_n（或全部），无需 ZZSHARE 补全。`quote_truncated=False`，所有返回股票都有完整 quote 字段。`quote_total_in_board=cached_count`（best-effort）。 |
| `'ths'` | `True`，boards 中全量成员 > top_n | 生效 | THS 上游取 top_n → heuristic 触发 → 自动调一次 ZZSHARE 拉全量成员清单 → merge：top_n 唯有 quote（用户在响应最前，按 sort 序）+ suffix 无 quote（响应末尾）。`quote_truncated=True`，`quote_total_in_board=full_count`。 |
| `'eastmoney' / 'zhitu'` | `True` | 任何值 | **400 invalid_combination**（这些 fetcher 不支持 sort_by） |
| `'eastmoney' / 'zhitu'` | `False` | 必须全部默认值 | 同 `'ths'` + include_quote=False，但走对应 fetcher |

**Route 层校验顺序** (in `get_board_stocks` 函数体, 入口)：
1. 若 `sort_by is not None or sort_order != "desc" or top_n != 50`:
   - 检查 `source == 'ths'`, 否则 400 invalid_combination
   - 检查 `include_quote == True`, 否则 400 invalid_combination (与 `/boards` sibling endpoint UX 一致)
2. 任一校验失败: HTTPException 400, 不调 manager

**Backward compat**: 所有新参数有默认值（`sort_by=None`, `sort_order="desc"`, `top_n=50`），老 client 不传时与历史行为等价（THS 50 由 top_n 默认值保留）。

**与 sibling `/boards` 端点 UX 一致性**: `routes/boards.py:327-335` 已有 `sort_by without include_quote → 400` 规则。本次 `/boards/{code}/stocks` 采用相同策略，避免 client 在两个端点间切换时遇到不同语义。

---

### 3.2 Fetcher 层改造

#### 3.2.1 列代码映射表（`ths_fetcher.py`）

```python
# THS board-stocks 上游 URL 模板（支持 11 种排序键）
_BOARD_STOCKS_URL_TEMPLATE = (
    "https://q.10jqka.com.cn/gn/detail/code/{concept_id}"
    "/field/{field_code}/order/{order}/page/{page}/ajax/1/"
)

# THS 上游列代码（来自页面 <th a field="...">）→ python attr 名字
# Field code 来源：实测 browser 抓 301546 概念详情页 <th a field="...">
# 2026-07-13 playwright probe.
_THS_BOARD_STOCKS_SORT_FIELD_MAP: dict[str, str] = {
    "change_pct":        "199112",   # 涨跌幅(%)
    "price":             "10",       # 现价
    "turnover_rate":     "1968584",  # 换手(%)
    "volume_ratio":      "1771976",  # 量比
    "amplitude":         "526792",   # 振幅(%)
    "change_amount":     "264648",   # 涨跌(元)
    "change_speed":      "48",       # 涨速(%)
    "amount":            "19",       # 成交额(元)
    "pe_ratio":          "2034120",  # 市盈率
    "float_market_cap":  "3475914",  # 流通市值(元)
    "free_float_shares": "407",      # 流通股(股)
}

_THS_BOARD_STOCKS_PG_SIZE = 10  # THS upstream 每页 10 只
```

#### 3.2.2 `ThsFetcher.get_board_stocks` 新签名

```python
def get_board_stocks(
    board_code: str,
    *,
    source: str | None = None,
    include_quote: bool = False,
    board_type: str | None = None,
    top_n: int = 50,                          # 新增, [1..50]
    sort_by: str = "change_pct",              # 新增, 必须 _THS_BOARD_STOCKS_SORT_FIELD_MAP 的 key
    sort_order: str = "desc",                 # 新增, "asc" | "desc"
    **kwargs,
) -> list[dict]:
```

#### 3.2.3 排序键校验

```python
if sort_by not in _THS_BOARD_STOCKS_SORT_FIELD_MAP:
    raise DataFetchError(
        f"[ThsFetcher] get_board_stocks: sort_by={sort_by!r} not in "
        f"supported set {sorted(_THS_BOARD_STOCKS_SORT_FIELD_MAP.keys())}"
    )
if sort_order not in ("asc", "desc"):
    raise DataFetchError(
        f"[ThsFetcher] get_board_stocks: sort_order={sort_order!r} "
        f"must be 'asc' or 'desc'"
    )
top_n = max(1, min(int(top_n), _THS_BOARD_STOCKS_PG_SIZE * 5))  # clamp 1..50
```

路由层 Literal 已经把可用 sort_by 限制到此白名单；这是 fetcher 的防御性二次校验。

#### 3.2.4 翻页循环变更

```python
field_code = _THS_BOARD_STOCKS_SORT_FIELD_MAP[sort_by]
max_pages = math.ceil(top_n / _THS_BOARD_STOCKS_PG_SIZE)  # top_n=50 → 5 pages
all_rows: list[dict] = []

for page in range(1, max_pages + 2):  # +1 buffer for partial last page
    try:
        rows = self._fetch_ths_board_stocks_page(
            board_code, page, field_code=field_code, order=sort_order
        )
    except ThsBoundarySignalError as e:
        if not all_rows:
            raise  # first page 401/403 → real upstream failure
        logger.info(f"board_stocks({board_code}, page={page}) {e.status_code}; "
                    f"treating as end of pagination ({len(all_rows)} rows so far)")
        break
    if not rows:
        break
    all_rows.extend(rows)
    if len(all_rows) >= top_n:
        break
return all_rows[:top_n]  # hard cap to top_n (defensive)
```

`_fetch_ths_board_stocks_page` 接收 `field_code` + `order` 参数以替代硬编码。

#### 3.2.5 解析全部 14 列

`_parse_ths_board_stocks_row` 当前忽略 idx 6/8/9/11/12/13（涨速/量比/振幅/流通股/流通市值/市盈率）。改为：

```python
return {
    "stock_code": stock_code,
    "stock_name": stock_name,
    "exchange": exchange,
    # 既有字段
    "price":         safe_float(tds[3].get_text(strip=True)),
    "change_pct":    safe_float(tds[4].get_text(strip=True)),
    "change_amount": safe_float(tds[5].get_text(strip=True)),
    # 新增字段
    "change_speed":     safe_float(tds[6].get_text(strip=True)),  # 涨速(%)
    "turnover_rate":    safe_float(tds[7].get_text(strip=True)),  # 换手(%) [原有]
    "volume_ratio":     safe_float(tds[8].get_text(strip=True)),  # 量比
    "amplitude":        safe_float(tds[9].get_text(strip=True)),  # 振幅(%)
    "amount":           safe_float(tds[10].get_text(strip=True)),  # 成交额(元) [原有]
    "free_float_shares": _parse_free_float(tds[11].get_text(strip=True)),  # 流通股(股)
    "float_market_cap": safe_float(tds[12].get_text(strip=True)),  # 流通市值(元)
    "pe_ratio":         safe_float(tds[13].get_text(strip=True)),  # 市盈率
    # 旧字段保留
    "volume": None,  # THS 14 列只有成交额，没有成交量。CLAUDE.md 已记录。
}
```

`_parse_free_float` 解析 THS 上游的 `"4.73亿"` 格式为 raw shares 整数（4.73 × 100,000,000 = 473,000,000）：

```python
def _parse_free_float(s: str) -> int | None:
    """Parse '4.73亿' / '27.16亿' → raw share count.

    THS 上游对 流通股 / 流通市值 / 成交额 等大数字用 'N.NN亿' 中文单位。
    本 helper 只用于 流通股(股) 一列；其他大数字字段保留为 float in 元 (上游值即元)。
    输入为 None / '--' / '0' / 异常格式 → None。
    """
    import re
    s = (s or "").strip().replace(",", "").replace("\xa0", "")
    if not s or s == "--" or s == "-":
        return None
    m = re.match(r"^([0-9]+(?:\.[0-9]+)?)亿$", s)
    if not m:
        return None  # 上游格式变化时安全降级到 None
    return int(round(float(m.group(1)) * 1e8))
```

上游通过 playwright 2026-07-13 probe 实测稳定使用 `"N.NN亿"` 格式；regex 严格匹配，未来格式变化时降级到 None 而不抛错。

#### 3.2.6 Docstring 更新

```python
def _fetch_ths_board_stocks_page(
    concept_id: str, page: int,
    *, field_code: str = "199112", order: str = "desc",
) -> list[dict]:
    """Fetch one page of THS board stocks (10 rows per page).

    Args:
        concept_id: THS concept slug (e.g. "301546").
        page: Page number (1-based).
        field_code: THS upstream column code for sort key.
            Defaults to "199112" (change_pct). 2026-07-13 probe
            confirmed: 11 codes work (price=10, turnover_rate=1968584, etc.).
        order: Sort direction, "asc" or "desc".
    ...
```

---

### 3.3 Schema 扩展（`api/schemas.py`）

`BoardStockInfo` 新增 6 个字段（紧跟现有 `turnover_rate`）：

```python
class BoardStockInfo(BaseModel):
    """Stock in a board, optionally with quote data."""

    code: str = Field(description="Stock code")
    name: str = Field(default="", description="Stock name")
    price: float | None
    change_pct: float | None
    change_amount: float | None
    volume: int | None
    amount: float | None
    turnover_rate: float | None
    # === 2026-07-13 新增 (THS /field/<code> 上游 11 列全部暴露) ===
    change_speed: float | None = Field(
        default=None, description="涨速(%) — ths source")
    volume_ratio: float | None = Field(
        default=None, description="量比 — ths source")
    amplitude: float | None = Field(
        default=None, description="振幅(%) — ths source")
    free_float_shares: int | None = Field(
        default=None, description="流通股(亿股; free-float shares) — ths source")
    float_market_cap: float | None = Field(
        default=None, description="流通市值(亿元) — ths source")
    pe_ratio: float | None = Field(
        default=None, description="市盈率(倍) — ths source")
```

**Backward compat**: 全部 `Optional` 字段，老客户端忽略。

---

### 3.4 持久化层 + Manager 层改造（`persistence/board.py` + `manager.py`）

#### 3.4.1 `get_board_stocks` 新签名 + 5 元组返回

```python
def get_board_stocks(
    board_code: str,
    source: str = "ths",
    refresh: bool = False,
    include_quote: bool = False,
    manager=None,
    *,
    sort_by: str | None = None,        # 新增
    sort_order: str = "desc",          # 新增
    top_n: int = 50,                   # 新增
) -> tuple[list, str, str, str | None, bool, int]:
    """Returns: (stocks, origin, effective_source, reason,
                 quote_truncated, quote_total_in_board)"""
```

#### 3.4.2 include_quote=False 路径（最小改动）

```python
if not include_quote:
    # 既有逻辑保持: 3 query 参数被忽略
    needs_refresh = refresh or _refresh_tracker.is_first_call(f"{board_code}:ths")

    if not needs_refresh:
        cached = _read_board_stocks_from_db(board_code, "ths")
        if cached:
            # 6 元组: (cached, "persistence", "ths", None, False, len(cached))
            return cached, "persistence", "ths", None, False, len(cached)

    # upstream path
    stocks, origin, es, reason = fetch_board_stocks_with_zzshare_fallback(
        board_code=board_code,
        source=source,
        include_quote=False,
        manager=manager,
        # sort_by / sort_order / top_n 不传(include_quote=False 时上游不接)
    )
    if stocks:
        update_cached_board_stocks(board_code, "ths", stocks)
    return stocks, origin, es, reason, False, len(stocks)
```

#### 3.4.3 include_quote=True 路径（核心新增）

```python
# include_quote=True 路径
# quote 不能 cache, 总是 fresh; stock_code 列表可能已在 cache 中

THS_HARD_CAP = 50  # THS 上游无登录态返回上限

# 1. 看 cache 中已有的 (board_code, stock_code) 作为 fallback total 计数
cached_full = _read_board_stocks_from_db(board_code, "ths")
cached_count = len(cached_full)

# 2. 走 upstream
stocks, origin, es, reason = fetch_board_stocks_with_zzshare_fallback(
    board_code=board_code,
    source=source,
    include_quote=True,
    manager=manager,
    sort_by=sort_by,
    sort_order=sort_order,
    top_n=top_n,
)

if not stocks:
    return [], origin, es, reason, False, cached_count

# 3. Heuristic: THS 返回数 == upstream hard cap (50) → 疑似被截断
needs_fill_in = len(stocks) >= THS_HARD_CAP

# 4. 主动调一次 ZZSHARE 拉全量成员清单 (no retry; 用 SDK 默认 timeout)
#    (与 ths_fetcher 异步 fetch 不同, 这步在主请求同步路径上,
#     因此用 SDK 默认 timeout + 一次调用, 不加重试)
suffix_no_quote: list[dict] = []  # 来自 ZZSHARE 的无 quote 补充
if needs_fill_in:
    try:
        zz_rows, _ = manager.get_board_stocks(
            board_code=board_code,
            source="zzshare",
            include_quote=False,
        )
    except DataFetchError as e:
        # 注意: fallback 失败不应升级为 5xx; 仅 logger.warning
        logger.warning(
            f"[BoardCache] ZZSHARE fill-in for {board_code} failed: {e}; "
            f"falling back to THS-only top-{len(stocks)}"
        )
        zz_rows = []

    # 5. Merge 关键: 
    #    stocks 列表 = top-N (THS, 带 quote, 按用户 sort 序) 
    #             + suffix (ZZSHARE 不在 top-N 中的, 无 quote)
    # 这样 top-N 在响应最前, 与用户 sort_by 顺序一致。
    quote_codes = {s["stock_code"] for s in stocks if s.get("stock_code")}
    suffix_no_quote = [
        r for r in (zz_rows or [])
        if r.get("stock_code") and r["stock_code"] not in quote_codes
    ]

# 6. quote_truncated 决策 (3 种情况)
#    - needs_fill_in=False → 板上 <50 → not truncated
#    - needs_fill_in=True, ZZSHARE 成功, suffix 非空 → 真截断
#    - needs_fill_in=True, ZZSHARE 失败/空 → 保守 True (client 需自查)
if not needs_fill_in:
    quote_truncated = False
elif suffix_no_quote:
    quote_truncated = True
else:
    # needs_fill_in=True 但 ZZSHARE 路径空 (失败 OR board 真有 50 只)
    quote_truncated = True  # 保守: 我们无法验证 = 截断
    logger.info(
        f"[BoardCache] {board_code}: heuristic fired but no suffix added; "
        f"reporting quote_truncated=True conservatively"
    )

# 7. 拼接最终响应列表 (top-N 在前, suffix 在后)
if suffix_no_quote:
    cached_count = max(cached_count, len(stocks) + len(suffix_no_quote))
    final_stocks = stocks + suffix_no_quote
else:
    final_stocks = stocks

# 8. 回写 cache (只写 code/name, 不写 quote — CLAUDE.md)
update_cached_board_stocks(board_code, "ths", final_stocks)
return final_stocks, origin, es, reason, quote_truncated, cached_count
```

**Heuristic 触发 + `quote_truncated` 矩阵**：

| 真实 board 大小 | THS 返回 | ZZSHARE 调用 | suffix 长度 | quote_truncated | quote_total_in_board | stocks 列表 |
|---|---|---|---|---|---|---|
| 30 | 30 | ❌ 不调用 | 0 | False | 30 | 30 (THS, 全带 quote, 已在 sort 序) |
| 50 | 50 | ✅ 调用 | 0 (50 = 50) | True（保守） | 50 | 50（全带 quote） |
| 60 | 50 | ✅ 调用 | 10 | True | 60 | 50 (THS, sort 序) + 10 (ZZSHARE, 无序) |
| 400（302546） | 50 | ✅ 调用 | 350 | True | 400 | 50 (THS, sort 序) + 350 (ZZSHARE, 无序) |
| cold + ZZSHARE 失败 | 50 | ❌ 失败 | 0 | True（保守） | cached_count | 50 (THS, sort 序) |

**关键不变量**：
- Top-N **始终在响应最前**且**按用户的 sort_by 排序**，因为它们就是 THS 上游原序返回的
- Suffix (ZZSHARE 补全部分) **始终在末尾**，且**不参与用户的 sort 排序** —— 没有 quote 字段可排序
- 客户端想要按 sort_by 对全部 stocks 排序时，前 top-N 行 OK；suffix 行的字段是 None，无法参与 sorted()
- 这与 `BoardStocksResponse.stocks` docstring 一致："quote fields are populated only for the top_n by sort_by/sort_order"

- 50 只 board 的假阳性：1 次额外 HTTP（≈0.5s），但 `quote_truncated=True` 体现"无法验证完整性"，符合事实（保守策略）
- `<50` 不调用 ZZSHARE，零额外开销
- `>50` 总是一次额外 HTTP，回报：客户端拿到完整 membership

**回写策略**：`update_cached_board_stocks` 只写 `(board_code, stock_code, stock_name)`，不写 quote。`stock_board_membership` 表下次 cache hit 时仅用于"已知哪些 stock 在 board 中"，quote 字段 route 层仍拼 null。

**Merge 是 THS-source-only 的**：eastmoney / zhitu 等数据源走的是 `fetch_board_stocks_with_zzshare_fallback` 的其他 branch,不走 include_quote=True heuristic; 它们也没 50-stock 上游 cap,无需 ZZSHARE 补全。本次设计不影响其他 source 的 quotes 字段 shape。

#### 3.4.4 `fetch_board_stocks_with_zzshare_fallback` 签名升级

```python
def fetch_board_stocks_with_zzshare_fallback(
    board_code: str,
    source: str,
    include_quote: bool,
    manager,
    *,
    sort_by: str | None = None,         # 新增
    sort_order: str = "desc",           # 新增
    top_n: int = 50,                    # 新增
) -> tuple[list[dict], str, str, str | None]:
```

`fetch_board_stocks_with_zzshare_fallback` 内部：
- `source='ths'` + `include_quote=True`：传 `sort_by / sort_order / top_n` 到 `manager.get_board_stocks(source='ths', ...)`
- `source='ths'` + `include_quote=False`：不走 THS（走 ZZSHARE），**不传** sort/top_n
- ZZSHARE fallback leg：调 `manager.get_board_stocks(source='zzshare', ...)` 时**不传** sort/top_n（ZZSHARE 不支持）

ZZSHARE 调用**总是 without quote, with default order** —— 它自己没有排序控制，我们也不会尝试映射。

#### 3.4.5 `DataFetcherManager.get_board_stocks` 签名扩展

**HIGH-blocking finding**: 现有 `DataFetcherManager.get_board_stocks(board_code, source, include_quote=False, board_type=None)` 在 `manager.py:810-853` 是**闭集签名**，内层 `call()` 只 forward `source / include_quote / board_type`。本次设计要让 fetcher 的 sort/top_n 链路打通，必须让 manager 接受并转发这 3 个新参数。

```python
def get_board_stocks(
    self,
    board_code: str,
    source: str,
    include_quote: bool = False,
    board_type: str | None = None,
    *,
    sort_by: str | None = None,         # 新增
    sort_order: str = "desc",           # 新增
    top_n: int = 50,                    # 新增
) -> tuple[list[dict], str]:
    """Get stocks belonging to a board from the named source.

    New keyword-only params (2026-07-13): sort_by / sort_order / top_n.
    Forwarded to the fetcher when the chosen source implements them.
    Fetchers whose get_board_stocks(**kwargs) absorbs them silently
    (ZzshareFetcher, ZhituFetcher, MyquantFetcher 都有 **kwargs)
    will work without per-source changes; ThsFetcher explicitly reads
    the 3 kwargs; EastMoneyFetcher.get_board_stocks has no **kwargs
    so will only be invoked from the strictly-routed branch WITHOUT
    these kwargs — enforced by route-layer 400 cross-validation
    (Section 3.1.1.1).
    """
    def call(f):
        kwargs = {
            "source": source,
            "include_quote": include_quote,
            "sort_by": sort_by,
            "sort_order": sort_order,
            "top_n": top_n,
        }
        if board_type is not None:
            kwargs["board_type"] = board_type
        return f.get_board_stocks(board_code, **kwargs), f.name

    stocks, name = self._with_source(
        source=source,
        capability=DataCapability.STOCK_BOARD,
        market="csi",
        op_label=f"board stocks {board_code} ({source})",
        call=call,
    )
    return stocks, name
```

**不影响其他 fetcher 的原因**：除 ThsFetcher 之外：
- `EastMoneyFetcher.get_board_stocks(_boards_mixin.py:539)` 只有固定签名，本次设计由 route 层 400 校验保证 eastmoney 路径**永不**收到 sort/top_n kwargs (`__`kw` TypeError` 隐患已堵)
- `ZzshareFetcher.get_board_stocks` / `ZhituFetcher.get_board_stocks` 都接受 `**kwargs`，传多余 kwargs 会被静默吞掉
- 新参数都是 keyword-only (`*` 强制)，破坏性 = 0

**Flow signature chain**（自上而下穿透）：
```
route query param → persistence.get_board_stocks(**)         接受 sort_by/sort_order/top_n
                → fetch_board_stocks_with_zzshare_fallback   接受 + 透传
                → manager.get_board_stocks(**)               接受 + 透传 via call()
                → ThsFetcher.get_board_stocks(**)            使用 3 个 kwarg
                → (_fetch_ths_board_stocks_page uses field_code/order)
```

**cid 解析位置（INFO from review）**：`fetch_board_stocks_with_zzshare_fallback` 在 `source='ths'` 分支内部**自己**调 `_resolve_ths_cid_from_platecode(board_code)`（`persistence/board.py:816`），把 THS concept id (如 `301546`) 解析出来再传给 manager。Route 层永远只看公开 platecode (`885595`)，cid 是持久化层的事。Spec 4.1 数据流示例里写的 `board_code="301546"` 仅用于说明 manager-level 调用；实际入参是 platecode。

---

### 3.5 测试

#### 3.5.1 `tests/test_ths_fetcher.py` 新增

```python
class TestGetBoardStocksTopNAndSort:
    def test_top_n_smaller_truncates_pages(self):
        """top_n=10 仅翻 1 页"""
    
    def test_top_n_clamped_to_50(self):
        """top_n=100 实际只取 50"""
    
    def test_sort_by_change_pct_asc(self):
        """order/asc URL, first row 是最大跌幅"""
    
    def test_sort_by_price_uses_field_code_10(self):
        """URL field/10/order/desc, first row 是最高价股票"""
    
    def test_sort_by_unknown_raises_data_fetch_error(self):
        """sort_by='magic' 抛 DataFetchError"""
    
    def test_sort_order_invalid_raises(self):
        """sort_order='random' 抛 DataFetchError"""
    
    def test_eight_row_first_page_partial_termination(self):
        """top_n=3 时第一页只取 3 行就 break"""
```

#### 3.5.2 `tests/test_boards_api.py` 新增

```python
class TestBoardStocksTopN:
    def test_sort_by_price_projects_top_10(self):
        """?include_quote=true&sort_by=price&sort_order=desc&top_n=10"""
    
    def test_quote_truncated_when_50_or_more(self):
        """?include_quote=true&top_n=10 → response.quote_truncated=True, stocks.length > 10"""
    
    def test_quote_truncated_false_when_below_50(self):
        """small board → no ZZSHARE call (mock verifies no zzshare call)"""
    
    def test_invalid_sort_by_returns_422(self):
        """?sort_by=invalid → 422 from Literal validation"""
    
    def test_top_n_above_50_returns_422(self):
        """?top_n=100 → 422 from Query(le=50)"""
    
    def test_include_quote_false_ignores_sort_by(self):
        """?sort_by=price without include_quote=true → 不传给 fetcher"""
    
    def test_new_schema_fields_present(self):
        """BoardStockInfo 接受 amplitude/volume_ratio/pe_ratio 等字段"""
```

#### 3.5.3 fixture 新增

`tests/fixtures/ths_board_301546_page1.html` —— 抓取 page 1 的真实 HTML（10 行）作为离线 fixture，已实测确认数据 row 数与列结构稳定。

---

## 4. 数据流（端到端）

### 4.1 完整请求流（include_quote=True, sort_by=change_pct, top_n=10, board=302546）

```
client → GET /boards/885595/stocks?source=ths&include_quote=true
                  &sort_by=change_pct&sort_order=desc&top_n=10

routes/boards.py:get_board_stocks
  ├─ Literal checks: sort_by, sort_order, top_n (Top_n Query(le=50) → may 422)
  ├─ persistence.board.get_board_stocks(
  │     board_code="885595", source="ths",
  │     include_quote=True,
  │     sort_by="change_pct", sort_order="desc", top_n=10,
  │   )
  │   ├─ _read_board_stocks_from_db("885595", "ths") → cached_count=400 (warm cache)
  │   ├─ fetch_board_stocks_with_zzshare_fallback(
  │   │     source='ths', include_quote=True,
  │   │     sort_by='change_pct', sort_order='desc', top_n=10
  │   │   )
  │   │   └─ manager.get_board_stocks(
  │   │         board_code="301546" (cid resolved from platecode),
  │   │         source='ths', include_quote=True,
  │   │         top_n=10, sort_by='change_pct', sort_order='desc'
  │   │       )
  │   │     └─ ThsFetcher.get_board_stocks(...):
  │   │           URL = "/.../field/199112/order/desc/page/{1}/ajax/1/"
  │   │           page=1 returns 10 rows → break (len=10==top_n)
  │   │           → 10 dicts with all 14 columns parsed
  │   │
  │   ├─ ths_count = 10 < THS_HARD_CAP (50) → quote_truncated = False
  │   │
  │   └─ update_cached_board_stocks("885595", "ths", 10 stocks)
  │       (按 CLAUDE.md, 只写 stock_code / stock_name, 不写 quote 字段)
  │
  ├─ 继续调用 manager.get_board_realtime("885595", source='ths', board_type='concept')
  │     → 板块级 quote 数据 (含今开/最高/涨跌家数/资金净流入) (与本设计无关, 既有逻辑)
  │
  └─ BoardStocksResponse(
       board=BoardInfo(...with quote data...),
       stocks=[BoardStockInfo for each of 10 stocks],
       query_source='ths',
       data_source='ths',
       effective_source='ths',
       quote_source='ths',
       quote_error=None,
       quote_truncated=False,
       quote_top_n=10,
       quote_sort_by='change_pct',
       quote_sort_order='desc',
       quote_total_in_board=400,  # cached_count
     )
```

### 4.2 Truncation 路径（include_quote=True, top_n=50, board=302546 真实场景）

```
1. THS 上游 → 50 行带 quote
2. ths_count (50) >= THS_HARD_CAP (50) → needs_fill_in = True
3. ZZSHARE 调用 → 400 行无 quote
4. merge → 50 行带 quote + 350 行无 quote = 400 总数
   (THS 那 50 只的 code/name/exchange 与 ZZSHARE 前 50 重叠 → 不重复)
5. Dynamic 判断: len(stocks)=400 > len(quote_by_code)=50 → quote_truncated = True
6. update_cached_board_stocks → 写 400 行 (stock_code + stock_name)
7. response:
   - quote_truncated = True
   - quote_top_n = 50
   - quote_sort_by = 'change_pct'
   - quote_sort_order = 'desc'
   - quote_total_in_board = 400 (来自 max(cached_count, zz_count))
   - stocks 列表 length = 400
```

### 4.3 Truncation 不发生路径（include_quote=True, top_n=10, board=302546）

```
1. THS 上游 → 10 行带 quote (top_n=10)
2. ths_count = 10 < 50 → needs_fill_in = False (跳过 ZZSHARE)
3. quote_truncated = False
4. update_cached_board_stocks → 写 10 行
5. response:
   - quote_truncated = False
   - quote_top_n = 10
   - stocks length = 10
```

### 4.4 board_level cid 解析位置（INFO）

数据流示例 4.1 写 `manager.get_board_stocks(board_code="301546")` 仅为示意 manager-level shape。**实际 caller 是 platecode**（`885595`），cid→platecode 翻译由 `fetch_board_stocks_with_zzshare_fallback` 在 `source='ths'` 分支**内部**通过 `_resolve_ths_cid_from_platecode(board_code)` 完成（`persistence/board.py:816`）。Route 层完全不需要知道 cid 是什么。

```
1. THS 上游 → 10 行带 quote (top_n=10)
2. ths_count = 10 < 50 → needs_fill_in = False (跳过 ZZSHARE)
3. quote_truncated = False
4. update_cached_board_stocks → 写 10 行
5. response:
   - quote_truncated = False
   - quote_top_n = 10
   - stocks length = 10
```

---

## 5. 错误处理

### 5.1 422 路径 (客户端错)

| 触发条件 | HTTP 状态 | 错因 |
|---|---|---|
| `sort_by` 不在 11 个白名单 | 422 | Literal 拒绝 |
| `sort_order` 不是 asc/desc | 422 | Literal 拒绝 |
| `top_n` 超出 1..50 | 422 | Query(ge=1, le=50) |
| `source` 不在 ('ths','eastmoney','zhitu') | 422 | 既有 Literal |
| THS concept cid 未解析 | 422 | `cid_unresolved` (与既有行为一致) |

### 5.2 5xx 路径 (上游失败)

| 触发条件 | HTTP 状态 | 错因 |
|---|---|---|
| THS 第一页就 401/403 | 503 | upstream auth failure (既有 ThsBoundarySignalError 路径) |
| THS 单页网络错误 | 503 | DataFetchError propagate |
| ZZSHARE 补全调用失败 | **200** | 入 200 但带 warning logger; quote_truncated=True 但 ZZSHARE leg 数据不足 → fallback 仅 THS top 50 |
| ZZSHARE 抛出 DataFetchError 时 | **200** | route 不会因为补全失败就 5xx —— 退化为只返 THS top 50 |

**设计取舍**：ZZSHARE 补全失败**不**升级为 5xx。原 top 50 仍然有效。降低 client 端 retry pressure。

### 5.3 持久化层错误

- `update_cached_board_stocks` 抛 `RuntimeError` (sqlite 错误) → 既有 logger, route 不影响 (SQL 写是 best-effort)
- ZZSHARE DataFetchError → logger.warning, 不 5xx

---

## 6. Backward compat 检查清单

| 客户端行为 | 旧路径 | 新路径 | 影响 |
|---|---|---|---|
| 不传任何新参数 | top_n=50, sort=change_pct desc → 取 top 50 | 完全相同 | ✓ |
| `include_quote=false` | 走持久化层 | 走持久化层 + 忽略 sort/top_n | ✓ |
| 旧 client 不知道新字段 | 多了 4 个 echo 字段 | 加 `quote_top_n / quote_sort_by / quote_sort_order / quote_truncated / quote_total_in_board` 都是 Optional | ✓ (向后兼容) |
| `BoardStockInfo` 旧字段不变 | price / change_pct / change_amount / volume / amount / turnover_rate | 同 + 6 新字段 | ✓ |
| Old cache hit (csi market 走 ZZSHARE→THS fallback 数据) | 50-100 行带 quote | 同, 只是 sort/top_n 触发条件多 | ✓ |

**唯一可能破坏**：`BoardStocksResponse` 新增字段对老 Pydantic 模型严格化客户端 (`extra="forbid"`) 会拒 —— 但项目所有客户端都用 `extra="ignore"`，没问题。

---

## 7. 回滚

如出现回退需要：
1. 保留 `sort_by / sort_order / top_n` 为 no-op（route 层忽略，fetcher 层忽略）
2. 撤销 `BoardStockInfo` 新增 6 字段（向后兼容 client 立即支持）
3. `BoardStocksResponse` 新增 echo 字段保留为 `None` (不影响老 client)

因为所有新增都是追加，回滚可以逐个 commit 反转。

---

## 8. 已知不做 / 后续候选

| # | 描述 | 来源 |
|---|---|---|
| F1 | ZZSHARE 补全失败时不告知 client (仅 logger.warning) | 当前 200 路径 |
| F2 | `pe_ratio` 字段在停牌股票上常为 `--` (None)，无明示 | 上游 quirk |
| F3 | `free_float_shares` 上游 `"4.73亿"` 解析由 `_parse_free_float` regex 完成；上游格式变化时降级到 None | 设计如此 |
| F4 | "top_n=50 false positive" 给正好 50 只的 board 带来额外 ZZSHARE 调用 | heuristic 副作用 |
| F5 | industry boards 的 sort_by 行为 — 概念/行业 board 字段代码可能不同 | 2026-07-13 仅测了概念板 |
| F6 | 是否应该把 `total_in_board` 也写到 `stock_board` 表里持久化 | 当前用 cache 推断 |
| F7 | Response field name `quote_total_in_board` 是否对中文 client 足够 self-explanatory; rename 待 client feedback | 待客户反馈 |
| F8 | `source='eastmoney'` 的 `sort_by` 映射表是否与 THS 等价（eastmoney 不受 50-stock 上限约束，理论上能返回完整列表，但 sort 字段映射待 probe） | 待 follow-up |

---

## 9. 验收 checklist

- [ ] `ths_fetcher.py`: 新增 `_BOARD_STOCKS_URL_TEMPLATE` + `_THS_BOARD_STOCKS_SORT_FIELD_MAP`
- [ ] `ths_fetcher.py`: `_fetch_ths_board_stocks_page` 接受 `field_code` + `order` 参数
- [ ] `ths_fetcher.py`: `_parse_ths_board_stocks_row` 解析全部 14 列（增加 6 字段）
- [ ] `ths_fetcher.py`: `get_board_stocks` 新增 top_n / sort_by / sort_order 参数
- [ ] `ths_fetcher.py`: 翻页循环 max_pages 由 top_n 决定，提前终止于 top_n 命中
- [ ] `api/schemas.py`: `BoardStockInfo` 新增 6 个 `Optional` 字段（change_speed / volume_ratio / amplitude / free_float_shares / float_market_cap / pe_ratio）
- [ ] `api/schemas.py`: `BoardStocksResponse` 新增 5 个字段（quote_truncated / quote_top_n / quote_sort_by / quote_sort_order / quote_total_in_board）
- [ ] `api/routes/boards.py`: `get_board_stocks` 新增 3 个 query 参数（Literal + Query 验证）
- [ ] `api/routes/boards.py`: 入口交叉校验——`(sort_by/top_n) without source='ths'` → 400, `(sort_by/top_n without include_quote=True)` → 400 (与 `/boards` sibling 一致, Section 3.1.1.1)
- [ ] `api/routes/boards.py`: `BoardStockInfo(...)` 投影加 6 个新字段
- [ ] `api/routes/boards.py`: `BoardStocksResponse(...)` 构造加 5 个 echo 字段
- [ ] `data_provider/manager.py`: `get_board_stocks` 签名扩展 keyword-only `sort_by / sort_order / top_n`，`call()` 透传到 fetcher (HIGH-blocking finding, Section 3.4.5)
- [ ] `persistence/board.py`: `get_board_stocks` 新签名 + 6 元组返回 + sort/top_n 穿透
- [ ] `persistence/board.py`: `fetch_board_stocks_with_zzshare_fallback` 接受 sort/top_n，ZZSHARE 路径忽略
- [ ] `persistence/board.py`: include_quote=True 路径加 THS_HARD_CAP heuristic + ZZSHARE 补全 + merge + 回写 cache
- [ ] `tests/test_ths_fetcher.py`: 7 个新测试
- [ ] `tests/test_boards_api.py`: 7 个新测试
- [ ] `tests/fixtures/ths_board_301546_page1.html`: 离线 fixture（10 行真实 upstream HTML）
- [ ] `pytest tests/test_boards_api.py tests/test_ths_fetcher.py` 全过
- [ ] `pytest`（默认 skip live_network）全过
- [ ] `ruff check .` 无 issue
- [ ] Live-network 测试手工跑一次 302546 验证 quote_truncated=true + total_in_board=400
- [ ] Live-network 测试手工跑一次 999999 (5 只 board) 验证 quote_truncated=false + 无 ZZSHARE 调用
- [ ] 更新 CLAUDE.md "Provider API Documentation" 表，ths board-stocks 上游描述加入列代码映射

---

## 10. 关联 commit (预期)

1. `feat(boards): extend BoardStockInfo with 6 new quote fields (amplitude, volume_ratio, change_speed, pe_ratio, float_market_cap, free_float_shares)` (commit A)
2. `feat(ths-fetcher): support 11 sort fields via /field/<code>/order/<dir>/ URL pattern` (commit B)
3. `feat(ths-fetcher): parse all 14 columns; add top_n + sort_by + sort_order params to get_board_stocks` (commit C)
4. `feat(manager): forward sort_by / sort_order / top_n kwargs through get_board_stocks` (commit D — 新增, 因 HIGH-blocking finding)
5. `feat(boards-route): add sort_by / sort_order / top_n query params + 5 echo fields to BoardStocksResponse + entry-point cross-validation` (commit E)
6. `feat(persistence): ZZSHARE backfill heuristic when THS returns 50 (hard cap) + top-N-first merge order` (commit F)
7. `test(boards): add fixture + 14 new tests covering the top_n + sort + backfill path` (commit G)
8. `docs(CLAUDE.md): document 11 sortable fields + persistence backfill policy` (commit H)

期望形成 7-8 commit 的清晰轨迹，每个独立可 revert。其中：
- commit D (manager signature) 必须先于 commit F (persistence) 落地，否则 persistence 编译失败
- commit E (route) 可独立前置或与其他合并
