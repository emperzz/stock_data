# `/agent/lead-stocks` Endpoint (涨停龙头股服务端排名)

**Date**: 2026-09-06
**Status**: Approved (awaiting implementation plan)
**Scope**: 新增 `GET /api/v1/agent/lead-stocks`，按 `连板数 × 当日涨幅 → 最后涨停时间 → 封单金额` 三层链对 10cm/20cm 涨停股做服务端排名并附带涨停原因与完整 feature profile。顺手把 `post_stocks_batch_profile` 内联的 per-stock fan-out 抽到 `api/_helpers/agent_stock_profile.py` 公共 helper，新端点与 batch-profile 共享。**No new fetcher, no new `DataCapability` flag, no new manager method.** No new composite cache layer; existing fetcher-level TTLs (`/v1/zt-pools` / `/api/v1/zt-reasons` / `board-stocks` 各自的 60s 缓存) continue to govern.

---

## 1. Background

`/api/v1/zt-pools` 已经返回涨停股的连板数 (`lb_count`)、当日涨幅 (`change_pct`)、最后涨停时间 (`last_seal_time`)、封单金额 (`seal_amount`)、涨停统计 (`zt_count`)。`/api/v1/zt-reasons` 已经按涨停板返回 `reason` 文本。

但当前 agent (OpenClaw) 拿到这两个端点的结果后，要在客户端手算 `连板数 × 涨幅`、再按时间与封单金额做并列破除——而这套排序逻辑是确定的、与上游数据无关的纯服务端计算。每次 agent 选龙头股都要重做一遍 N+1 拉数 + 客户端排名。

新端点把排名下沉到服务端，agent 拿 top_n 就够。同时把每只 lead 的完整 feature profile（`quote / features / info / boards`）一并返回，避免 agent 拿了排名还要再调 `/agent/stocks/batch-profile` 二次拉数。

**User intent** (brainstorming 2026-09-06, 中文): "按涨幅排名（连板数*当日涨幅），10cm 默认10%，20cm 默认20% ... 涨停时间早的排名在前 ... 封单金额大的排名在前 ... 从 api/zt-reasons 提取股票涨停的原因 ... 最后根据 top_n 输出对应数量的股票和涨停数据。"

**Non-goals**:

- 30cm / ST 个股识别（本次用 `change_pct ∈ [9.0, 22.0]` 区间一刀切，不引入 `detect_limit_band` helper）。
- 多日 leader-board 趋势 / 连板梯队榜（本次只做单日排序）。
- 按 `limit_band`（10cm vs 20cm）做差异化打分（统一按原始 `change_pct` 排名）。
- `?source=` 暴露给 `board_code` 筛选（固定 `source="ths"`，与其他 `/agent/*` 板块调用一致）。
- `?include_profile=false` 切面 flag（始终返回完整 feature profile）。
- 历史的"曾经涨停但当日未封"票（只取当日 ZT-pool 内的票）。

---

## 2. Public API

### 2.1 Request

```
GET /api/v1/agent/lead-stocks
  ?date=YYYY-MM-DD          # 可选；默认 trade_calendar.get_latest_trade_date_on_or_before(today)
  &board_code=885595        # 可选；传入则按板块成分股交集筛
  &top_n=3                  # 可选；默认 3；范围 [1, 20]
  &format=json|md           # 可选；默认 json
```

- `date` 正则 `^\d{4}-\d{2}-\d{2}$`，不匹配返回 422。
- `top_n` 超出 [1, 20] 返回 422：`top_n must be between 1 and 20`。
- `board_code` 解析失败（不存在的板）返回 422。

### 2.2 Response (JSON)

```json
{
  "date": "2026-09-05",
  "board_code": "885595",
  "top_n": 3,
  "leads": [
    {
      "rank": 1,
      "score": 60.06,
      "code": "300750",
      "name": "宁德时代",
      "change_pct": 20.02,
      "lb_count": 3,
      "zt_count": "3连板",
      "last_seal_time": "10:23:14",
      "seal_amount": 1.23e9,
      "reason": "新能源车产业链",
      "ok": true,
      "quote":     { "...MinimalQuote 23 字段...": null },
      "features":  { "...BatchFeatures trend/pivots/volume...": null },
      "info":      { "...": null },
      "boards":    { "...": null },
      "errors":    []
    }
  ],
  "errors": [],
  "warning": null,
  "summary": {
    "requested": 3,
    "matched": 1,
    "elapsed_ms": 234,
    "excluded": {"below_9pct": 12, "above_22pct": 4}
  }
}
```

### 2.3 Field reference table

| Field | Type | Source | Notes |
|---|---|---|---|
| `date` | `str` (YYYY-MM-DD) | 输入 / `trade_calendar` 解析 | |
| `board_code` | `str \| null` | 输入 | `null` 表示无板块筛选 |
| `top_n` | `int` | 输入 | |
| `leads[].rank` | `int` | 计算 | 1-indexed |
| `leads[].score` | `float` | 计算 | `lb_count × change_pct`（None 处理：见 §3.3）|
| `leads[].code` | `str` | `zt-pools.code` | 6 位裸代码（与 `StockInfo.code` 同）|
| `leads[].name` | `str` | `zt-pools.name` | |
| `leads[].change_pct` | `float \| null` | `zt-pools.change_pct` | None 视为 0 |
| `leads[].lb_count` | `int \| null` | `zt-pools.lb_count` | None 视为 1 |
| `leads[].zt_count` | `str \| null` | `zt-pools.zt_count` | 描述性（"首板"/"3连板"）|
| `leads[].last_seal_time` | `str \| null` | `zt-pools.last_seal_time` | HH:MM:SS；None 视为 99:99:99 |
| `leads[].seal_amount` | `float \| null` | `zt-pools.seal_amount` | 元（CNY）；None 视为 -1 |
| `leads[].reason` | `str \| null` | `zt-reasons.reason`（按 code 索引）| 缺失为 null |
| `leads[].quote` | `MinimalQuote \| null` | `manager.get_realtime_quote` | |
| `leads[].features` | `BatchFeatures \| null` | `features.build_features` | |
| `leads[].info` | `dict \| null` | `manager.get_stock_info` | |
| `leads[].boards` | `dict \| null` | `stock_board_cache.get_stock_memberships` | |
| `leads[].errors` | `list[StockBatchAspectError]` | per-aspect 失败 | |
| `leads[].ok` | `bool` | 派生 | 任一 aspect 非空 |
| `errors` | `list[dict]` | 顶层错误 | `block="reasons"` 时填充 |
| `warning` | `str \| null` | `zt-pools.warning` | volatile date 时非 null |
| `summary.requested` | `int` | 输入 top_n | |
| `summary.matched` | `int` | 实际返回数 | |
| `summary.elapsed_ms` | `int` | 处理耗时 | |
| `summary.excluded` | `dict` | 过滤掉的分桶 | |

### 2.4 命名规范

- `LeadStockEntry` 继承 `StockBatchProfileEntry`（位于 `stock_data/api/schemas.py:1944`）：保留所有 batch-profile 字段（`code / name / ok / quote / features / info / boards / errors`），新增排名相关字段（`rank / score / change_pct / lb_count / zt_count / last_seal_time / seal_amount / reason`）。
- `last_seal_time` 与 zt-pools / zt-reasons 字段名一致；不重命名。
- `reason` 与 zt-reasons 字段名一致；不重命名。

---

## 3. Implementation

### 3.1 Schemas（`stock_data/api/schemas.py`，`StockBatchProfileResponse` 旁边）

```python
class LeadStockEntry(StockBatchProfileEntry):
    """涨停池内股票按 score → seal_time → seal_amount 排名后的 entry。
    继承 StockBatchProfileEntry 携带完整 feature block，新增排名相关字段。
    详见 docs/superpowers/specs/2026-09-06-agent-lead-stocks-design.md。
    """
    rank: int
    score: float
    change_pct: float | None = None
    lb_count: int | None = None
    zt_count: str | None = None
    last_seal_time: str | None = None
    seal_amount: float | None = None
    reason: str | None = None

class LeadStocksResponse(BaseModel):
    date: str
    board_code: str | None = None
    top_n: int
    leads: list[LeadStockEntry]
    errors: list[dict] = []
    warning: str | None = None
    summary: dict = {}
```

### 3.2 Public helper（`stock_data/api/_helpers/agent_stock_profile.py` — 新建）

把 `post_stocks_batch_profile`（`stock_data/api/routes/agent.py:873-1013`）的内联 per-stock fan-out 抽成公共 helper。新端点与 batch-profile 共用。

```python
from dataclasses import dataclass, field

@dataclass
class StockProfileData:
    """per-stock fan-out 结果。任一字段为 None 不算失败，对应 StockBatchAspectError 入 errors[]。"""
    code: str
    quote: MinimalQuote | None = None
    features: BatchFeatures | None = None
    info: dict | None = None
    boards: dict | None = None
    errors: list[StockBatchAspectError] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return any(v is not None for v in (self.quote, self.features, self.info, self.boards))


def build_stock_profile(
    manager: DataFetcherManager,
    code: str,
    *,
    frequency: str = "d",
    days: int | None = None,
) -> StockProfileData:
    """对单只股票拉 quote + features + info + boards，每个 aspect 独立 try/except。
    被 /agent/stocks/batch-profile 与 /agent/lead-stocks 共用。"""
    profile = StockProfileData(code=code)
    # quote
    try:
        q = manager.get_realtime_quote(code)
        if q is not None:
            profile.quote = MinimalQuote(...)  # 23-field mapping per 2026-08-27 spec
    except Exception as exc:
        profile.errors.append(StockBatchAspectError(aspect="quote", error=type(exc).__name__, message=str(exc)))
    # features
    try:
        actual_days = max(days or 0, _FEATURE_FREQS[frequency].ma60_warmup_days, _FEATURE_FREQS[frequency].default_days)
        df = manager.get_kline_data(code, frequency=_FEATURE_FREQS[frequency].mgr_frequency, days=actual_days, adjust="qfq")
        profile.features = features.build_features(df) if df is not None and not df.empty else None
    except Exception as exc:
        profile.errors.append(StockBatchAspectError(aspect="features", error=type(exc).__name__, message=str(exc)))
    # info
    try:
        info = manager.get_stock_info(code)
        profile.info = info.model_dump() if hasattr(info, "model_dump") else (info or None)
    except Exception as exc:
        profile.errors.append(StockBatchAspectError(aspect="info", error=type(exc).__name__, message=str(exc)))
    # boards
    try:
        entries, _cold, _origin = stock_board_cache.get_stock_memberships(code, sources=["ths"], manager=manager)
        profile.boards = {"entries": entries} if entries else None
    except Exception as exc:
        profile.errors.append(StockBatchAspectError(aspect="boards", error=type(exc).__name__, message=str(exc)))
    return profile
```

**Defer to the implementation plan**: helper 内部具体的异常类型白名单（`DataFetchError` / `ValueError` / `AttributeError`）。当前沿用 batch-profile 的"裸 `except Exception`"模式保持行为一致。

### 3.3 排序与归一化（`stock_data/api/routes/agent.py` 的 `_compute_lead_stocks_block`）

```python
# 1. change_pct 过滤：None → 0；保留 [9.0, 22.0]
def apply_change_pct_filter(stocks: list[dict]) -> tuple[list[dict], dict]:
    kept, excluded_below, excluded_above = [], 0, 0
    for s in stocks:
        pct = s.get("change_pct")
        pct = 0.0 if pct is None else float(pct)
        if pct < 9.0:
            excluded_below += 1
        elif pct > 22.0:
            excluded_above += 1
        else:
            kept.append(s)
    return kept, {"below_9pct": excluded_below, "above_22pct": excluded_above}

# 2. 三层排名（None 归一化见 §3.3 注释）
def _seal_time_key(t: str | None) -> str:
    return t if t is not None else "99:99:99"

def _seal_amount_key(a: float | None) -> float:
    return a if a is not None else -1.0

def rank_lead_stocks(stocks: list[dict]) -> list[dict]:
    def sort_key(s):
        lb = s.get("lb_count") if s.get("lb_count") is not None else 1
        pct = s.get("change_pct") if s.get("change_pct") is not None else 0.0
        score = lb * pct
        return (-score, _seal_time_key(s.get("last_seal_time")), -_seal_amount_key(s.get("seal_amount")))
    return sorted(stocks, key=sort_key)
```

**排序方向**：score **降序**（越高越好）、`last_seal_time` **升序**（越早越好）、`seal_amount` **降序**（越大越好）。`None` 视为最差值（详 §6.1）。

### 3.4 Route handler（`stock_data/api/routes/agent.py`）

```python
@router.get(
    "/agent/lead-stocks",
    response_model=LeadStocksResponse,
    responses={422: {"model": ErrorResponse, ...}, 503: {"model": ErrorResponse, ...}, 500: {...}},
    tags=["agent"],
)
@endpoint_meta(
    summary="涨停龙头股服务端排名（连板数×涨幅→最后涨停时间→封单金额）",
    markets=["csi"],
    capabilities=[],
    depends_on=["/api/v1/zt-pools", "/api/v1/zt-reasons", "/api/v1/boards/{board_code}/stocks"],
)
@map_errors
def get_lead_stocks(
    date: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    board_code: str | None = Query(None),
    top_n: int = Query(3, ge=1, le=20),
    format: str = Query("json", pattern="^(json|md)$"),
) -> Response:
    # 1. 解析 date
    resolved_date = date or get_latest_trade_date_on_or_before(date.today())
    # 2. 调 zt-pools
    try:
        pool_stocks, _origin, warning = manager.get_zt_pool(pool_type="zt", date=resolved_date)
    except DataFetchError as exc:
        raise HTTPException(503, ...)
    # 3. 若 board_code 提供：板块交集
    if board_code:
        try:
            board_stocks, _o, _es, _r, _qt, _t = stock_board_cache.get_board_stocks(
                board_code, source="ths", include_quote=False, manager=manager
            )
            board_codes = {s["stock_code"] for s in board_stocks if s.get("stock_code")}
            pool_stocks = [s for s in pool_stocks if s["code"] in board_codes]
        except (DataFetchError, ValueError) as exc:
            raise HTTPException(503, ...)
    # 4. change_pct 过滤
    kept, excluded = apply_change_pct_filter(pool_stocks)
    # 5. 三层排名
    ranked = rank_lead_stocks(kept)[:top_n]
    # 6. 调 zt-reasons（失败降级）
    reasons: dict[str, str] = {}
    try:
        reason_stocks, _src, _ = manager.get_zt_reasons(date=resolved_date)
        reasons = {s["code"]: s.get("reason") for s in reason_stocks}
    except DataFetchError as exc:
        errors.append({"block": "reasons", "error": type(exc).__name__, "message": str(exc)})
    # 7. 每只 lead 拉完整 profile
    leads = []
    for rank_idx, s in enumerate(ranked, start=1):
        profile = build_stock_profile(manager, s["code"], frequency="d", days=60)
        leads.append(LeadStockEntry(
            rank=rank_idx,
            score=s["lb_count"] * (s.get("change_pct") or 0),
            code=s["code"], name=s.get("name"),
            change_pct=s.get("change_pct"), lb_count=s.get("lb_count"),
            zt_count=s.get("zt_count"),
            last_seal_time=s.get("last_seal_time"), seal_amount=s.get("seal_amount"),
            reason=reasons.get(s["code"]),
            ok=profile.ok,
            quote=profile.quote, features=profile.features,
            info=profile.info, boards=profile.boards,
            errors=profile.errors,
        ))
    # 8. 组装响应
    summary = {"requested": top_n, "matched": len(leads), "elapsed_ms": int((time.monotonic() - t0) * 1000), "excluded": excluded}
    result = LeadStocksResponse(
        date=resolved_date, board_code=board_code, top_n=top_n,
        leads=leads, errors=errors, warning=warning, summary=summary,
    )
    return _render_agent("lead-stocks", result, format)
```

**Defer to the implementation plan**: 并发策略（`asyncio.gather` 还是顺序）、`board_code` 校验路径（与 `post_filter_stocks` 一致）。

### 3.5 MD 渲染器（`stock_data/api/routes/agent.py` 的 `_MD_TEMPLATES`）

新增 `render_lead_stocks_as_md` 函数 + 在 `_MD_TEMPLATES["lead-stocks"]` 注册。结构：

```markdown
# <date> · board=<code 或 "ALL"> · top_n=<n>

## 排序规则
按 `连板数 × 当日涨幅` 降序 → 最后涨停时间升序 → 封单金额降序。
`change_pct ∈ [9.0, 22.0]` 之外（北交所 30cm / ST 5%）的票不参与排名。

## 排名表

| 排名 | 代码 | 名称 | score | 涨幅 | 连板 | 涨停统计 | 最后封板 | 封单金额(元) | 原因 |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 300750 | 宁德时代 | 60.06 | 20.02% | 3 | 3连板 | 10:23:14 | 1.23e9 | 新能源车产业链 |
| ... |

## <rank>. <code> <name>

### 实时报价
- **最新价**: 172.5
- **涨跌幅**: 20.02%
...

### 形态特征
...

### 公司画像
...

### 板块归属
...

### 错误（如果有）
...
```

每个 lead 一节 `## rank. code name`，下面是 `quote` / `features` / `info` / `boards` 子表——**CLAUDE.md "No data is dropped — every JSON field appears in the MD output"**契约由 batch-profile 已有的 `_md_quote_block` / `_md_feature_block` 复用。

### 3.6 Manifest 注册

`@endpoint_meta(markets=["csi"], capabilities=[], depends_on=["/api/v1/zt-pools", "/api/v1/zt-reasons", "/api/v1/boards/{board_code}/stocks"])`。无 `@cache_endpoint`、无复合缓存（依赖内层 `/v1/zt-pools` 与 `/api/v1/zt-reasons` 各自的 60s 缓存）。

### 3.7 `post_stocks_batch_profile` 重构（`agent.py:873-1013`）

内联 fan-out 替换为：

```python
for code in payload.codes:
    profile = build_stock_profile(manager, code, frequency=payload.frequency, days=payload.days)
    name = profile.quote.name if profile.quote and getattr(profile.quote, "name", None) else None
    entries.append(StockBatchProfileEntry(
        code=code, name=name, ok=profile.ok,
        quote=profile.quote, features=profile.features,
        info=profile.info, boards=profile.boards,
        errors=profile.errors,
    ))
```

行为差异：errors[] 现在由 helper 构造而非 handler 内联累积。需要 `TestBatchProfileRegression`（§4.2）确保 mock 期望不变。

---

## 4. Testing

### 4.1 新增 `tests/test_agent_lead_stocks.py`

`autouse fixture` 复用 `tests/test_agent_endpoints.py` `reset_before_test` 的 `reset_manager()` + 清缓存模式。

| Class | 覆盖 |
|---|---|
| `TestLeadStocksRanking` | 排序三层链（score 降序 / seal_time 升序 / seal_amount 降序）+ 全 None 字段处理（lb / change_pct / seal_time / seal_amount）|
| `TestLeadStocksChangePctFilter` | 边界值 `[9.0, 22.0]`；`8.99` / `22.01` 排除；`change_pct=None` 视为 0 排除；`summary.excluded` 分桶正确 |
| `TestLeadStocksBoardFilter` | `board_code` 命中交集；`board_code` 空集返回 200 + 空 leads；`board_code` 解析失败 422 |
| `TestLeadStocksErrorIsolation` | `manager.get_zt_pool` 抛错 → 503；`manager.get_zt_reasons` 抛错 → 200 + reason=null + errors[]；`stock_board_cache.get_board_stocks` 抛错（带 board_code）→ 503；不带 board_code 时不触发该分支 |
| `TestLeadStocksTopN` | 默认 `top_n=3`；`top_n=1` / `top_n=20` 边界；`top_n=0` / `top_n=21` → 422 |
| `TestLeadStocksDateDefault` | 省略 `date` 默认取最新交易日（mock trade_calendar）；显式 `date` 透传 |
| `TestLeadStocksManifest` | 路由出现在 `manifest["sections"]` 的 `id=="agent"` 段；`@endpoint_meta` 字段（`markets=["csi"]`、`capabilities=[]`、`depends_on` 含 3 条）正确 |
| `TestLeadStocksFormatMd` | `?format=md` 渲染 Content-Type + 完整字段（CLAUDE.md 不丢字段契约——quote/features/info/boards 全部出现）|
| `TestLeadStocksProfileHelperReuse` | `build_stock_profile` 被 lead-stocks 与 batch-profile 共用（mock 调用计数 = 两者之和）|
| `TestLeadStocksBatchProfileRegression` | 重构后 `post_stocks_batch_profile` 行为不变（errors 顺序、ok 派生、各 aspect 字段）|

### 4.2 Pinned with new tests

- `test_ranking_chain` — 三层链正确性（score → seal_time → seal_amount 顺序）。
- `test_change_pct_boundary_inclusive` — `9.0` 与 `22.0` 包含；`8.99` 与 `22.01` 排除。
- `test_summary_excluded_buckets` — `summary.excluded.below_9pct` / `above_22pct` 计数正确。
- `test_ztreasons_failure_degrades` — `manager.get_zt_reasons` 抛错 → 200 + `errors[]` 有 `{block:"reasons", ...}` + 所有 lead `reason=null`。
- `test_helper_reuse_count` — `build_stock_profile` 被两个端点共用，mock 调用计数 = N + M。
- `test_md_no_drop` — MD 输出包含每只 lead 的 quote/features/info/boards 子表。

### 4.3 Out of test scope

- `tests/test_agent_endpoints.py::TestBoardsOverlap` / `TestStocksBoardOverlap` / `TestFilterStocks` — 不受影响。
- `tests/test_agent_market_*` — 不受影响。
- `tests/test_agent_correlation_*` — 不受影响。

---

## 5. Documentation

| File | Section | Change |
|---|---|---|
| `docs/api-reference.md` | 新增 `/agent/lead-stocks` 章节 | Request shape、Response shape、字段映射表（§2.3）、JSON + MD 示例 |
| `CLAUDE.md` | Agent Batch API 路由表 | 新增一行 `GET /agent/lead-stocks — 涨停龙头股服务端排名（连板数×涨幅→时间→封单金额）` |
| `CLAUDE.md` | Standardized Data Schema 节 | 视情况补充（`LeadStockEntry` 与 `LeadStocksResponse` 是新 model）|

---

## 6. Risk analysis

### 6.1 None 归一化与排序方向稳定性

**风险**：`lb_count=None` 视为 1、`change_pct=None` 视为 0、`last_seal_time=None` 视为 `99:99:99`、`seal_amount=None` 视为 `-1`——这些归一化值若改动会反向影响已有 ZT-pool 数据的排名顺序。

**缓解**：归一化值集中在 `rank_lead_stocks` / `apply_change_pct_filter` 两个纯函数里，单测全覆盖（`TestLeadStocksRanking::test_none_field_fallbacks`、`TestLeadStocksChangePctFilter::test_none_change_pct_treated_as_zero`）。若未来要改（如"lb_count=None 视为 0 而非 1"），单测会先红。

### 6.2 change_pct 阈值 [9.0, 22.0] 边界精度

**风险**：北交所 30cm 涨停的 `change_pct` 通常在 29.5-30.5，落 `>22.0` 被排除；ST 股票的 `change_pct` 通常在 4.97-5.03，落 `<9.0` 被排除——**正确**。但边界 9.0 / 22.0 都是**包含**（按 §3.3）；若上游 ZT-pool 出现 `change_pct=8.99` 的"破板临界票"也会被排除，可能引入静默偏差。

**缓解**：阈值是 spec 决策，不在实现层调整；若实测发现 8.99-9.01 区间大量合法涨停股被误杀，下个 spec 调整阈值。当前单测 pin `8.99 → below_9pct`、`9.0 → kept`、`22.0 → kept`、`22.01 → above_22pct`。

### 6.3 ZT-pool 数据质量与持久化层

**风险**：`zt-pools` 持久化层 (`data_provider/persistence/pool_daily.py`) 在 volatile date（今天 + 交易日 + 16:00 前）不会写回；上游（akshare 优先、zhitu 兜底）偶有 `change_pct` 缺失或飘到 9.2% 等非涨停数值。

**缓解**：`change_pct=None` 视为 0 落到 `<9` 桶被排除；非涨停数值（如 9.2%）也落 `<9` 被排除——双重保险。`zt-pools.warning` 透传给 lead-stocks 响应，agent 可看到 "volatile date" 提示。

### 6.4 zt-reasons zzshare 单点

**风险**：`zt-reasons` 唯一 provider 是 zzshare（P2）；若 zzshare 不可达，整条链降级——`reason=null`。

**缓解**：失败仅降级，不致命；`errors[]` 加 `{block:"reasons", error, message}` 让 agent 知道原因缺失。其它 ranking 维度（score / seal_time / seal_amount）继续工作。

### 6.5 重构 `post_stocks_batch_profile` 引入回归

**风险**：把内联 fan-out 抽到 `build_stock_profile` 后，errors[] 顺序、`ok` 派生、`info` / `boards` 调用参数微调都可能引入 regression。

**缓解**：`tests/test_agent_lead_stocks.py::TestLeadStocksBatchProfileRegression` 复用 `tests/test_agent_endpoints.py::TestBatchProfile*`（`test_agent_endpoints.py:1078-1115`）的所有 mock fixture，确保重构前后行为一致。重构 PR 与新端点 PR 拆开提交，便于 bisect。

### 6.6 `top_n=20` 响应体积膨胀

**风险**：`top_n=20` 时每只 lead 携带完整 feature profile（quote 23 + features ~30 + info ~10 + boards ~10 ≈ 73 字段），响应体积 ~150KB+。

**缓解**：上限锁定 20（§2.1）。若 agent 真要轻量响应，未来选项是 `?include_profile=false`，但本次不做。`summary.matched` 字段让 agent 知道实际返回数（不一定是 top_n）。

---

## 7. Out of scope (explicit non-goals)

- **No new fetcher** — 复用 `manager.get_zt_pool` / `manager.get_zt_reasons` / `manager.get_realtime_quote` / `manager.get_kline_data` / `manager.get_stock_info` / `stock_board_cache.get_stock_memberships`。
- **No new `DataCapability` flag** — `@endpoint_meta(capabilities=[])` 保持空。
- **No new manager method** — 全部调用现有的 6 个 public 方法。
- **No new composite cache layer** — 依赖内层 fetcher 各自的 60s 缓存。
- **No new `cache.py` key builder** — 不写 `make_lead_stocks_cache_key`（无复合缓存不需要）。
- **No `?include_profile=false` / `?include_reasons=false` 切面 flag** — 始终返回完整 profile，reasons 失败降级。
- **No `?source=` 暴露给 board_code 筛选** — 固定 `source="ths"`。
- **No 30cm / ST 个股智能识别** — `change_pct ∈ [9.0, 22.0]` 一刀切。
- **No `detect_limit_band(code, name)` helper** — 不引入。
- **No 多日 leader-board / 连板梯队榜** — 只做单日排序。

---

## 8. Implementation plan

按文件边界拆，每步独立可测：

1. **Helper 抽离** — 新建 `stock_data/api/_helpers/agent_stock_profile.py`，定义 `StockProfileData` + `build_stock_profile()`。**先跑 batch-profile 回归测试，确认等价**。
3. **重构 `post_stocks_batch_profile`** — `agent.py:873-1013` 内联 fan-out 替换为 helper 调用。跑 `pytest tests/test_agent_endpoints.py::TestBatchProfile*` 确认无 regression。
4. **Schema 新增** — `api/schemas.py` 加 `LeadStockEntry` + `LeadStocksResponse`，紧贴 `StockBatchProfileResponse`（`schemas.py:1944`）。
5. **Handler 实现** — `agent.py` 新增 `get_lead_stocks` handler，含 `apply_change_pct_filter` / `rank_lead_stocks` 纯函数、`build_stock_profile` 复用、`_render_agent` 调度。
6. **MD 渲染器** — `_MD_TEMPLATES["lead-stocks"]` 注册 + `render_lead_stocks_as_md` 函数；复用 batch-profile 已有的 `_md_quote_block` / `_md_feature_block`。
7. **Manifest 校验** — `GET /control/api-manifest` 确认新端点出现在 `id=="agent"` 段，`depends_on` 列表正确。
8. **新测试文件** — `tests/test_agent_lead_stocks.py` 10 类测试。
9. **Documentation 更新** — `docs/api-reference.md` 新章节 + `CLAUDE.md` Agent Batch API 路由表。
10. **最终回归** — `pytest -m ""`（含 `live_network` 与 `requires_token`，跑全套）。零失败后才算完成。