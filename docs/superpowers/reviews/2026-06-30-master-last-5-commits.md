# 代码 Review：master 最近 5 个 commit (2026-06-30)

**范围：** `af88943`（最早审查的）→ `05ed71f`（HEAD）。Diff：1059 行新增 / 444 行删除，34 个文件。
**审查的 commit：**

```
05ed71f refactor: remove backward-compat shims and dead code
9ad3781 refactor(manager): remove dead get_index_historical/get_index_intraday
ae6aba6 refactor: remove dead index-intraday cache infra + stale comments
14a0605 fix(akshare): volume conversion *100 not //100 + helpers NaN/indicators fixes
af88943 fix(manager): add circuit breaker to k-line path + extract _candidates helper
```

**方法论：** Phase 1 — 9 个并行 finder agent（行级扫描、移除行为审计、跨文件追踪、语言陷阱、wrapper/proxy 正确性、复用、简化、效率、高度）。Phase 2 — 对 20 个最强候选做单票验证（结果：18 个 CONFIRMED，1 个 PLAUSIBLE，1 个 REFUTED）。Phase 3 — gap-sweep finder 找第一遍漏掉的缺陷。最后按严重度裁剪到 top 15（按 code-review skill 的"recall mode"规则：正确性 bug 优先于清理/高度类发现）。

**验证器投票说明：** ✅ CONFIRMED（失败场景可复现）· ⚠️ PLAUSIBLE（机制真实，触发条件不确定）· ❌ REFUTED（在别处被防护）。

---

## 发现列表 — 按严重度排序

### 1. 🔴 运行时错误 — Explorer 页面抛出 `ReferenceError: MANIFEST is not defined`

**文件：** `stock_data/explorer/static/index.html:915`（以及约 928 行、740 行）

**验证者：** 行级扫描 + 跨文件追踪（两者都 CONFIRMED）。

**问题：** 第一个 IIFE（约 384 行）用 `let MANIFEST = FALLBACK;` 声明了一个块作用域变量。第二个 IIFE（740 行起）包含 `renderSidebar()` 和 `renderContent()`，这两个函数引用了 `MANIFEST.sections.forEach(...)`。原来能让这段代码正常工作的桥 — `Object.defineProperty(window, 'ENDPOINTS', { get() { return MANIFEST } })` — 在 `05ed71f` 中被删了，没有任何替代桥接。第一个 IIFE 确实设置了 `window.MANIFEST`，但第二个 IIFE 从未从 `window` 读取。

**触发场景：** 在浏览器中加载 `/explorer/`。第一个 IIFE 运行，把数据填充到 `window.MANIFEST`，然后第二个 IIFE 运行，在第一次访问 `MANIFEST.sections` 时崩溃。侧边栏和内容面板渲染为空，或者页面直接挂掉。

**为什么测试套件没抓到：** `tests/test_api_html.py` 只断言 HTML 文本里存在字面量 `MANIFEST.sections` — 它并没有在浏览器里实际加载页面，所以跨 IIFE 的作用域违规是不可见的。

**修复方案（选一个）：**

A. 通过 `window` 做桥（改动最小，镜像旧的 ENDPOINTS shim）：

```js
// 在第一个 IIFE 末尾（`let MANIFEST = FALLBACK;` 被填充之后）：
window.MANIFEST = MANIFEST;
Object.defineProperty(window, 'ENDPOINTS', {
  get() { return MANIFEST; }
});
```

B. 把所有 `renderSidebar` / `renderContent` 移到和 `MANIFEST` 同一个 IIFE 里，这样 `let` 绑定就在作用域内。（改动较大，需要把第二个 `<script>` 块的主体挪进第一个。）

C. 把 `MANIFEST` 声明为顶层的 `var`（脚本级作用域，两个 IIFE 都可见）。最快，但 `var` 不推荐 — 方案 A 是旧契约的更干净镜像。

**推荐：** 方案 A。3 行代码恢复 window-shim 契约。再加一个 Playwright/集成测试，断言加载 `/explorer/` 时控制台没有 `ReferenceError`。

---

### 2. 🔴 静默数据错误 — 实时行情的 volume 单位是手（lots），K-line 是股（shares），100× 漂移且无字段标识

**文件：** `stock_data/data_provider/fetchers/akshare/fetcher.py:285`（指数路径约 522、552 行）

**验证者：** Gap sweep（Phase 3）— 在最初 9 个 agent 之后才发现。读实时路径代码后 CONFIRMED。

**问题：** Commit `14a0605` 把 K-line / intraday 的 volume 转换从 `int(v) // 100` 翻成 `int(v) * 100`，按 spec §3.4 归一化为"手 → 股"。但同一个 fetcher 里的实时行情路径没有被改：

- `fetcher.py:285`（股票实时）
- `fetcher.py:522`（指数 EM 实时）
- `fetcher.py:552`（指数 Sina 实时）

这三处都仍然在做 `safe_int(row.get('成交量'))` 直接返回原始的手值。`KLineData.volume` 和 `IntradayData.volume` 都有 `volume_unit: Literal['share']` 字段标识，但 `StockQuote.volume`（`schemas.py:62`）和 `UnifiedRealtimeQuote.volume`（`core/types.py:75`）**根本没有 `volume_unit` 字段**。

**触发场景：** 任何把当日 K-line volume（股）和当前 quote volume（手）做对比的客户端，看到 quote volume 比最新一根 K-line 的 volume 小 100 倍。VWAP、量比、OBV 以及任何从 volume 派生的指标都会静默地算错 100×。客户端在 quote 响应上没有任何 `volume_unit` 字段能识别单位。

**为什么测试套件没抓到：** `KLineData.volume_unit` 在 volume 单位的测试里被断言了，但 `StockQuote.volume_unit` 没有对应测试 — 因为 quote schema 上根本就没这个字段。

**修复（两个部分，必须一起落地）：**

1. **在实时路径上应用 `*100` 转换**（spec 的规则是"所有 volume 都是股"）：

   ```python
   # fetcher.py:285（以及 522、552）— 用和 K-line 路径一样的 lambda 包起来：
   "volume": int(row.get("成交量")) * 100 if pd.notna(row.get("成交量")) else 0,
   ```

2. **给 `StockQuote` 和 `UnifiedRealtimeQuote` 加 `volume_unit: Literal["share"] = "share"` 字段**，让 API 契约和 `KLineData` 对齐，客户端可以依赖"永远是股"这个跨端点的一致不变量。同步更新 docstring 和 CLAUDE.md 的"Standardized Data Schema"一节。

**推荐：** 两步都要做。schema 字段那步更重要 — 即便 `*100` 修了，实时响应上一个未声明的单位依然是一个契约 bug，等下次加新 fetcher 时会再次踩坑。

---

### 3. 🔴 测试套件坏掉 — `tests/test_routes.py` 断言了已被删除的 `industry` 字段

**文件：** `tests/test_routes.py:330-339`

**验证者：** 行级扫描 + 跨文件追踪（两者都 CONFIRMED）。

**问题：** `expected_fields` 集合里还包含 `"industry"`，但 commit `05ed71f` 从 `StockInfoResponse`（`schemas.py:703-734`）里删掉了这个字段。`/api/v1/stocks/{code}/info` 的每一个 200 响应都会让 `assert set(data.keys()) == expected_fields`（339 行）失败。

**触发场景：** `pytest tests/test_routes.py` → info 端点的测试失败。CI 红灯。同一个 PR 既删了字段又弄坏了覆盖它的测试 — 两者没有同步更新。

**修复：** 从 `test_routes.py:330` 的 `expected_fields` 集合里删掉 `"industry"`。还要审查 `tests/test_base_unit.py:147` 那个被改名的测试（`test_get_stock_name_empty_db_returns_empty`），它现在断言的是降级后的行为 — 参见发现 #5。

**推荐：** 修 assert（1 行）。要做根本性预防，可以加一个 fixture 从 schema 本身拉期望字段：`set(StockInfoResponse.model_fields.keys())` — 这样测试就不会和 schema 漂移。

---

### 4. 🟠 漂移 — `get_kline_data` 自己手写 failover，没走 `_with_failover`

**文件：** `stock_data/data_provider/manager.py:357-382`

**验证者：** 6 个 agent（行级扫描、移除行为、跨文件追踪、简化、高度、wrapper/proxy）— 整个 review 中最强的收敛信号。

**问题：** `get_kline_data`（357-382 行）把 `_with_failover`（217 行，带 `circuit_breaker=` kwarg）已经实现的 per-fetcher circuit-breaker 循环重抄了一遍。那个 kwarg 的调用者是零个 — 抽象加上了但从没接进来。现在存在两份并行的 failover 循环。

**行为分叉：** `_with_failover`（274 行）在软失败（空/None 结果）时会调 `circuit_breaker.record_failure(fetcher.name)`，让 HALF_OPEN 状态的 fetcher 在坏探针上被正确标记为失败。但内联的 kline 循环只在 `except DataFetchError` 块里调 `record_failure`，只在 `_is_meaningful(df)` 为 True 时调 `record_success` — 一个持续返回空（不抛异常）的 fetcher 永远不会被记为失败，所以它的 circuit 永远跳不到；HALF_OPEN 状态也永远无法通过空探针恢复。

**触发场景：** 一个静默返回空 DataFrame 连续 3 次以上的 fetcher（不抛异常）永远不会被 circuit-break。下一次请求还是把它排在最前面，每次都付同样的空结果延迟。HALF_OPEN 恢复路径在这段代码里也是死的。

**修复：** 把内联循环换成一次 helper 调用：

```python
# 在 get_kline_data 中，_kline_candidates 之后：
result, source = self._with_failover(
    candidates=...,
    call=lambda f: f.get_kline_data(code, kline_options, asset),
    return_source=True,
    circuit_breaker=KLINE_CIRCUIT_BREAKER,
)
```

然后把同样的重构也应用到 `get_realtime_quote`（503-517 行）— 它也有自己的内联 CB 循环。两个 CB 单例（`KLINE_CIRCUIT_BREAKER`、`REALTIME_CIRCUIT_BREAKER`）可以继续作为独立的配置旋钮 — 只是应该作为 kwarg 传给 helper，而不是内联在循环体里。

**推荐：** 必做。这是整个 diff 里杠杆最高的一次清理 — helper 是同一个 PR 加的，但从来没被用过。半抽象比不抽象更糟，因为它会让人以为"问题已经解决"了，但实际还留着一份重复代码。

---

### 5. 🟠 回归 — `get_stock_name` 丢了 manager-fetch 的回退

**文件：** `stock_data/data_provider/persistence/stock_list.py:174`

**验证者：** 4 个 agent（行级扫描、移除行为、跨文件追踪、wrapper/proxy）。

**问题：** Commit `05ed71f` 把 `get_stock_name(code, market, manager)` 缩减成一次 DB 查询：`return _get_stock_name_from_db(normalized, market) or ""`。`manager` 参数接受了但从来不用。原来在 DB miss 时，函数会 fallback 到 `get_stock_list(market, refresh=False, manager=manager)` 扫描那个结果，这个调用顺带会通过 `DailyRefreshTracker.is_first_call` 自动预热持久化层。被改名的测试 `test_get_stock_name_empty_db_returns_empty` 被改成了断言空结果，**把回归锁死了**。

**触发场景 — 冷启动：** `stock_list` SQLite 表是空的（每天首次启动、自动刷新还没跑、或者 `STOCK_DB_INIT=true` 刚把 DB 清掉）。9+ 个传 `manager=manager` 的路由调用点（例如 `/stocks/{code}/quote` 在 `stocks.py:160`、`/stocks/{code}/kline` 在 `stocks.py:256`，外加 `/dragon-tiger`、`/margin`、`/block-trade`、`/holder-num`、`/dividend`、`/fund-flow`、`/reports`、`/announcements`）响应里都会拿到 `name=""`，即便 akshare 本来可以给 600519 返回"贵州茅台"。

**为什么这个问题比看起来更糟：** 那个死掉的 `manager=` 参数是一处代码异味 — 它给调用方一个"回退还在"的假象。路由还在像真在用那样传它。等持久化刷新终于跑了（在第一次 `/stocks` 列表调用时），名字就可用了一 — 但那次刷新之前的所有请求都拿 `name=""`。

**修复：** 恢复回退路径。函数应该长这样：

```python
def get_stock_name(code: str, market: str, manager: "DataFetcherManager | None" = None) -> str:
    name = _get_stock_name_from_db(normalized, market)
    if name:
        return name
    if manager is None:
        return ""
    # Fall back to upstream via the manager — auto-warms the DB on the next /stocks list call.
    try:
        from .pool_daily import is_volatile_date
        from .trade_calendar import get_latest_trade_date_on_or_before
        latest = get_latest_trade_date_on_or_before(...)
        for s in manager.get_stock_list(market, refresh=False):
            if s.get("code") == normalized:
                return s.get("name", "")
    except Exception:
        return ""
    return ""
```

或者更干净的做法 — **把自动预热内联进来**，把填 DB 作为副作用：

```python
def get_stock_name(code, market, manager=None):
    name = _get_stock_name_from_db(normalized, market)
    if name:
        return name
    if manager is not None:
        manager.get_stock_list(market, refresh=False)  # auto-warm
        name = _get_stock_name_from_db(normalized, market)  # retry
    return name or ""
```

**推荐：** 恢复回退。那个死的 `manager=` 参数是个谎言。被改名的测试应该恢复原样（或者拆成两个：一个测 DB 命中，一个测 manager 回退）。

---

### 6. 🟠 Explorer 用了错的方法 — `CAPABILITY_TO_METHOD[INDEX_KLINE]` 仍指向已删除的 `get_index_historical`

**文件：** `stock_data/data_provider/base.py:80`

**验证者：** 行级扫描（CONFIRMED）。

**问题：** Commit `9ad3781` 从 manager 里删了 `get_index_historical` / `get_index_intraday` — 现在的生产路径是 `manager.get_kline_data(code, ..., asset='index')` → `fetcher.get_kline_data(...)`。但 `CAPABILITY_TO_METHOD[DataCapability.INDEX_KLINE] = 'get_index_historical'` 没更新。

**副作用：**

1. `/explorer/` 上 `/indices/{code}/kline` 的 Explorer Stage 2 manifest 把 `get_index_historical` 列为 fetcher 方法。
2. 这一行的 "Test" 按钮会调 `fetcher.get_index_historical(...)`，**还能跑**（7 个 fetcher 实现没被删）— 但这不是生产路径。这个 Test 绕过了 manager 的 circuit breaker、capability filter，以及新的 kline `*100` volume 转换。
3. `/control/fetcher-test` 的 `allowed_methods` 白名单（`explorer/routes.py:148-153`）是从这个 map 构建的，所以 Test 按钮的 POST 把一个错方法当成了"合法"。

**触发场景：** 用户在 `/explorer/` 上点击 `/indices/{code}/kline` 这一行的 Test。看到一个成功响应（或者一个让人困惑的不同错误），就以为这就是生产行为。Test 功能被文档定位为"验证改动能不能跑"，但在这种情况下它验证的是死路径，不是活路径。

**修复：** 把 map 项更新成实际的生产方法：

```python
# stock_data/data_provider/base.py
CAPABILITY_TO_METHOD = {
    ...
    DataCapability.INDEX_KLINE: "get_kline_data",   # 原值: "get_index_historical"
    ...
}
```

要么删掉那 7 个 fetcher 的 `get_index_historical` / `get_index_intraday` 方法（最干净），要么加一行 deprecation 注释（如果有外部集成还在用）。`tests/test_fetcher_structure.py` 断言它们存在的那些测试也要更新。

**推荐：** 更新 map **并且**删掉死的 fetcher 方法。9ad3781 对 manager 做的同一份审计，应该在 fetcher 上也做一遍 — 方法还在，但生产代码不再调它们。

---

### 7. 🟠 死的接口面 — 3 个 fetcher 还在 emit 已删除的 `industry` 字段

**文件：**

- `stock_data/data_provider/fetchers/zhitu_fetcher.py:471`
- `stock_data/data_provider/fetchers/myquant_fetcher.py:631`
- `stock_data/data_provider/fetchers/zzshare_fetcher.py:442`

**验证者：** 跨文件追踪 + gap sweep（两者都 CONFIRMED）。

**问题：** 三个 `get_stock_info` 实现都还在它们的返回 dict 里给 `"industry": ""`。`StockInfoResponse`（`schemas.py:703-734`）已经不再声明这个字段。Pydantic 默认的 `extra='ignore'` 今天静默地丢掉这个键 — 不报错，fetcher 那一侧测试也不失败（`tests/test_zhitu_fetcher.py:73`、`tests/test_myquant_fetcher.py:69`、`tests/test_zzshare_fetcher.py:769,796` 都是在 fetcher 层的 dict 上做断言，不走 schema 响应）。

**触发场景 — 未来的硬化：** 如果有人把 schema 改成 `model_config = ConfigDict(extra='forbid')`（一个合理的硬化动作），三个 fetcher 会在 `/stocks/{code}/info` 上同时 500。fetcher 层的测试还会过（它们从不走 schema），把故障盖住了。

**修复：** 从三个 `get_stock_info` 的返回里把 `"industry": ""` 那一行删掉。在 `data_provider/core/types.py` 里加一个 `make_stock_info(...)` helper，只返回 schema 声明的字段，这样下次再删字段时，类型检查器（或者至少 code review）能抓住偏差。

**推荐：** 删掉那些死的 key。可选：加一个 `make_stock_info(...)` 构造函数，它针对 `StockInfoResponse.model_fields` 做未来的字段自检。

---

### 8. 🟠 客户端破坏 — README/CLAUDE.md 还在描述已删的 `ma5/ma10/ma20` 字段

**文件：** `README.md:224-227`、274 行；`CLAUDE.md:125-126`

**验证者：** 移除行为 + 跨文件追踪（两者都 CONFIRMED）。

**问题：** 两份文档都把 `ma5` / `ma10` / `ma20` 描述成 `/stocks/{code}/kline` 响应上的 back-compat 顶层字段：

> "the 4 indicator fields (`ma5`, `ma10`, `ma20`, `indicators`) are conditionally serialized"
> "the back-compat `ma5`/`ma10`/`ma20` top-level fields"

Schema（`KLineData` 在 `schemas.py:78-131`）现在只剩 `indicators: dict[str, float | None] | None`。Commit `05ed71f` 删了 back-compat 字段。真实的面向客户端的破坏性变更被陈旧文档盖住了。

**触发场景：** OpenClaw 或任何消费者读 README / CLAUDE.md 来学习响应形状，在 `?indicators=ma` 之后写 `body['data'][i]['ma5']`，运行时 KeyError。数据现在在 `body['data'][i]['indicators']['ma5']`，但文档没明说。读 CLAUDE.md 当事实的 AI agent 会自信地写错。

**修复：** 更新两份文档：

- `README.md:224-227` — 把 "the 4 indicator fields" 改成 "the 1 indicator field (`indicators`)"，并链到 schema。
- `README.md:274` — 删掉 `ma5/ma10/ma20` back-compat 的描述；加一个展示新形状的响应示例。
- `CLAUDE.md:125-126` — 在 "Standardized Data Schema" 下的 `KLineData conditional serialization` 一节做同样的更新。

**推荐：** 更新文档。这是一个对所有信任文档多过测试的客户端的静默破坏性变更。

---

### 9. 🟠 缓存 miss — `make_kline_cache_key` 不 sort indicators

**文件：** `stock_data/api/cache.py:274`

**验证者：** 3 个 agent（行级扫描、跨文件追踪、效率）。

**问题：** 新的 `make_kline_cache_key` 在 274 行直接用 `','.join(indicators)`。旧的 `make_history_cache_key`（现在是死的）显式 sort 过：`','.join(sorted(indicators))`。新测试（`tests/test_kline_cache_key.py`）只断言子串存在，没断言顺序无关。

**触发场景：** `/stocks/600519/kline?indicators=ma,macd` 和 `?indicators=macd,ma` 都会触发上游拉取和完整 failover 链 — 但它们应该共享同一个 TTL 条目。`?indicators=kdj,boll,rsi` 的任何排列也是一样 — 任何非规范顺序的客户端都要付一次额外的完整拉取往返。

**修复：** 包一层 `sorted()`：

```python
# api/cache.py:274
f"{end_date or ''}:{adjust or ''}:{','.join(sorted(indicators))}"
```

然后加一个回归测试：

```python
def test_kline_cache_key_indicator_order_independent():
    k1 = make_kline_cache_key("600519", "d", 30, None, None, None, ["ma", "macd"])
    k2 = make_kline_cache_key("600519", "d", 30, None, None, None, ["macd", "ma"])
    assert k1 == k2
```

**推荐：** 加 `sorted(indicators)`。测试能抓住任何未来的回归。

---

### 10. 🟡 陈旧文档 — Volume `*100` 改动没反映到 3 处 docstring

**文件：**

- `stock_data/data_provider/fetchers/akshare/index_norm.py:137-139`
- `stock_data/api/schemas.py:250`（Pydantic 字段描述，会通过 `/openapi.json` 暴露）
- （`index_norm.py:160-161` 的内联注释已经被正确更新；问题出在上面这段长 docstring。）

**验证者：** 4 个 agent（行级扫描、移除行为、复用、gap sweep）。

**问题：** 三处 docstring 还在把 volume 转换描述成 `// 100`：

- `index_norm.py:137` — "converts to 股 (shares) by `int() // 100` per spec §3.4. The floor prevents 7 手 → 0.07 shares (float) and keeps the int-typed column schema invariant intact."
- `schemas.py:250` — IntradayData.volume_unit 描述："the AkshareFetcher normalizer divides by 100 + int() floor to satisfy this"。
- （`fetcher.py:215` 的一条注释被删了；上面这段长 docstring 是残存的陈旧文本。）

**触发场景：** 未来的贡献者读 docstring 当 spec，grep `// 100`，把 `*100` "修"回 `//100` — 把 `14a0605` 想要干掉的那个 bug 原样引回来。这是唯一一处还在宣传原 bug 方向的地方。`schemas.py:250` 的措辞通过 `/openapi.json` 公开暴露，OpenClaw 会把 "divides by 100" 当作 API 契约的一部分。

**修复：** 两处都更新：

```python
# index_norm.py:137-139 — 替换为：
"""Akshare upstream returns 手 (lots = 100 shares); the column is multiplied by 100
to convert lots → shares per spec §3.4. The *100 must be applied to the raw integer
column after pd.to_numeric(errors='coerce') so NaN/None flow through safely.
"""

# schemas.py:250 — 替换为：
description="Volume unit. Always 'share' (股) — invariant enforced by fetcher
normalization per spec §3.4. AkshareFetcher multiplies raw 手 by 100 in
_normalize_data; index_norm.normalize_intraday_df does the same after
pd.to_numeric coercion."
```

**推荐：** 两处都更新。`schemas.py` 那个更重要 — 它对用户可见。

---

### 11. 🟡 故障放大 — `get_index_realtime_quote` 没有 circuit breaker

**文件：** `stock_data/data_provider/manager.py:638-672`

**验证者：** 行级扫描（CONFIRMED）。

**问题：** `get_realtime_quote`（503-517 行）接了 `REALTIME_CIRCUIT_BREAKER.is_available`（505 行）、`record_failure`（511 行）、`record_success`（514 行）。它的兄弟方法 `get_index_realtime_quote`（638-672 行）**这三处一个都没有** — 每个按优先级排序的 fetcher 都被无条件尝试，并且从来不调 `record_success` / `record_failure`。

**触发场景：** Tencent 的 HK 指数 feed（或者任何其他指数实时 fetcher）持续故障：每次 `/indices/{code}/quote` 调用都先打那个坏的 fetcher 然后超时（~10-30s），不会 fallthrough 到下一个。故障期间所有客户端的这个端点都会慢得像爬的。

**修复：** 在 `core/types.py` 里加一个 `INDEX_REALTIME_CIRCUIT_BREAKER` 单例（镜像 `REALTIME_CIRCUIT_BREAKER`），然后在 `get_index_realtime_quote` 里应用和 `get_realtime_quote` 一样的 `is_available` / `record_failure` / `record_success` 模式。或者 — 鉴于发现 #4 — 把两个方法都重构为委托给 `_with_failover(circuit_breaker=...)`，kwarg 携带 per-method 的单例。

**推荐：** 加 CB。配合 #4 一起做 — `_with_failover` 配对应的 CB 单例。

---

### 12. 🟡 文档漂移 — `CLAUDE.md` 引用了已删除的 `_NO_FETCHER_METHOD` 符号

**文件：** `CLAUDE.md:198` 和 `CLAUDE.md:443`

**验证者：** 移除行为（CONFIRMED）。

**问题：** 这两节还在引用 `_NO_FETCHER_METHOD`，把它当作应该存在的符号。Commit `05ed71f` 从 `data_provider/base.py` 里删了那个空的 frozenset；`tests/test_capability_method_map.py` 已经被更新成只检查 `CAPABILITY_TO_METHOD`。CLAUDE.md 反模式那一节还在断言这条规则生效：

> "every flag must be in either `CAPABILITY_TO_METHOD` (maps to a fetcher method) or `_NO_FETCHER_METHOD` (explicit 'no method')"

**触发场景：** 一个加新 `DataCapability` 的开发者按陈旧指引操作，grep `_NO_FETCHER_METHOD`，什么都没找到，然后要么放弃，要么自己造一个机制。更糟的是，另一个贡献者以为规则没变，又把那个符号加回来，把禁用的 helper 重新引入。

**修复：** 更新 CLAUDE.md 的两节。实际的规则现在是："每个 flag 都必须在 `CAPABILITY_TO_METHOD` 里（或故意不注册 — 启动时 explorer sanity check 会发警告）"。

**推荐：** 更新文档。改起来很快。

---

### 13. 🟡 死代码 — `make_history_cache_key` 和 `make_stock_intraday_cache_key`

**文件：** `stock_data/api/cache.py:163`、187 行

**验证者：** 复用 + 简化（两者都 CONFIRMED）。

**问题：** 两个函数都是死代码 — 已经被 `make_kline_cache_key` + `get_kline_cache(frequency)` 完整替代。`stock_data/` 里没有任何调用点（grep 只返回定义和过期的 .pyc）。最近的 commit `ae6aba6` 正确删了**指数**的对应物，但漏掉了**股票**的版本，把同一个反模式留了一半。`get_history_cache`（192 行）和 `get_stock_intraday_cache`（202 行）很可能也是死的调用点。

**触发场景：** 未来的贡献者 Ctrl+F "history cache key" 落到还活着的 `make_history_cache_key`，把它接进新端点，而不是 `make_kline_cache_key` — 把统一后的 kline 缓存拆成两个互不失效的桶，这正好是 commit `14a0605` 想防止的症状。

**修复：**

1. grep `make_history_cache_key`、`make_stock_intraday_cache_key`、`get_history_cache`、`get_stock_intraday_cache` 的调用点 — 确认是零。
2. 删掉这四个（以及任何只被它们用过的 `CACHE_TTL_HISTORY` / `CACHE_TTL_STOCK_INTRADAY` 环境变量）。
3. 跑测试确认没东西坏。

**推荐：** 删掉。原 commit `ae6aba6` 本来应该抓住这些 — 同一份审计，只是往下多扫两行。

---

### 14. 🟡 体验差 — K-line circuit breaker 抛 `DataFetchError("All fetchers failed: []")`

**文件：** `stock_data/data_provider/manager.py:382`

**验证者：** 跨文件追踪（CONFIRMED）。

**问题：** K-line failover 循环在 382 行抛 `DataFetchError(f"All fetchers failed: {errors}")`。当所有候选都被新的 `if not KLINE_CIRCUIT_BREAKER.is_available(...): continue`（370 行）跳过 — 即所有 circuit 都开着 — `errors` 保持初始的 `[]`，用户看到的就是字面量 `"All fetchers failed: []"`，没有任何指示说明是 circuit breaker 导致的、cooldown 是多少、还是否值得重试。

**触发场景：** 某个形状（比如 minute + adjust 这种稀有组合）上每个 fetcher 连续 3 次失败后，用户会看到 `"All fetchers failed: []"` 持续约 5 分钟（cooldown 期间）。日志里只有 debug 级别的 "circuit open, skipping"。诊断困难，错误也没指导意义。`_with_failover` 有同样的历史问题，所以 kline 路径除了循环体也复制了它。

**修复：** 区分"全部失败"和"全部 circuit 开着"两种错误路径。二选一：

A. errors 为空时附加更清晰的错误：

```python
if not errors:
    raise DataFetchError(
        f"All {len(candidates)} candidate fetchers are circuit-open for "
        f"{market}/{capability.name}. Cooldown active — retry after {cb.cooldown}s."
    )
raise DataFetchError(f"All fetchers failed: {errors}")
```

B. 在响应里带上 circuit 状态（通过 `return_source=True` 传递，加一个 `circuit_state` 字段）。

**推荐：** 方案 A。改动小，UX 提升大。配合 #4 一起做更好 — 重构后的 helper 可以一次搞定，服务所有调用方。

---

### 15. 🟡 不一致 — Board history 路由用裸 `int()` 处理 volume；K-line 用 `safe_int()`

**文件：** `stock_data/api/routes/boards.py:431`

**验证者：** Gap sweep（CONFIRMED）。

**问题：** Board history 路由用 `volume=int(row.get("volume", 0))`（431 行）做强转上游 volume。外层的 `try/except (TypeError, ValueError): continue`（436 行）在遇到 None / NaN / 字符串 volume 时静默 drop 这一行。K-line 编排路径（`api/routes/helpers.py:239`）用的是 `volume=safe_int(row.get("volume"), 0) or 0`，强转坏值为 0，并且**保留这一行**。

**触发场景：** ZzshareFetcher 的 `plate_kline` 返回 30 行但其中 3 行的 `volume` 是畸形（比如 None、`"N/A"`、或者别的字符串）。`/stocks/600519/kline?indicators=...` 返回全部 30 行，坏 volume 被强制为 0；`/boards/BK0001/history` 返回 27 行，3 行被静默丢掉。客户端在同样的上游调用形状上看到的行数不一致，响应里没有任何信号。下游图表布局会静默错位。

**修复：** 在 board 路由里用同一个 `safe_int(...)` helper，或者更好的做法 — 把 K-line 行构造抽成一个共享 helper，两边都调：

```python
# 在 api/routes/helpers.py — 把 _build_kline_data 抽出来
def build_kline_row(row: dict) -> dict:
    return {
        "date": ...,
        "open": safe_float(row.get("open"), 0.0),
        "high": safe_float(row.get("high"), 0.0),
        "low": safe_float(row.get("low"), 0.0),
        "close": safe_float(row.get("close"), 0.0),
        "volume": safe_int(row.get("volume"), 0),
        "amount": safe_float(row.get("amount"), 0.0) or None,
        "pct_chg": safe_float(row.get("pct_chg"), 0.0) or None,
    }
```

然后 `boards.py` 和 `stocks.py` 都调 `build_kline_row(row)`。"行 → Pydantic 入参 dict" 的唯一来源，volume / amount / pct_chg 的强转策略也统一了。

**推荐：** 抽 helper。Diff 已经在 helpers.py:239 加上 `safe_int` 了 — 在所有 kline-build 站点一致地用它就是顺理成章的下一步。

---

## 总结表

| # | 文件 | 严重度 | 标题 | 验证 |
|---|------|--------|------|------|
| 1 | `explorer/static/index.html:915` | 🔴 运行时 | Explorer `MANIFEST` ReferenceError | ✅ |
| 2 | `akshare/fetcher.py:285` | 🔴 静默数据 | 实时 quote volume 是手 vs K-line 是股 | ✅ |
| 3 | `tests/test_routes.py:330` | 🔴 测试坏 | 断言了已删的 `industry` 字段 | ✅ |
| 4 | `manager.py:357` | 🟠 漂移 | K-line CB 重抄 `_with_failover` | ✅（6 个 agent） |
| 5 | `persistence/stock_list.py:174` | 🟠 回归 | `get_stock_name` 丢 manager 回退 | ✅（4 个 agent） |
| 6 | `base.py:80` | 🟠 错方法 | `CAPABILITY_TO_METHOD[INDEX_KLINE]` 指向死方法 | ✅ |
| 7 | zhitu/myquant/zzshare fetcher | 🟠 死接口面 | 3 个 fetcher 还在 emit `industry` | ✅ |
| 8 | `README.md:224,274` + `CLAUDE.md:125-126` | 🟠 客户端破坏 | 陈旧的 `ma5/ma10/ma20` 文档 | ✅ |
| 9 | `api/cache.py:274` | 🟠 缓存 miss | `make_kline_cache_key` 不 sort indicators | ✅（3 个 agent） |
| 10 | 3 处陈旧 docstring | 🟡 文档漂移 | 文档和 OpenAPI 里 `// 100` 引用 | ✅（4 个 agent） |
| 11 | `manager.py:638` | 🟡 故障放大 | `get_index_realtime_quote` 没 circuit breaker | ✅ |
| 12 | `CLAUDE.md:198,443` | 🟡 文档漂移 | 引用了已删的 `_NO_FETCHER_METHOD` | ✅ |
| 13 | `api/cache.py:163,187` | 🟡 死代码 | `make_history_cache_key` / `make_stock_intraday_cache_key` | ✅ |
| 14 | `manager.py:382` | 🟡 体验差 | K-line 抛 `"All fetchers failed: []"` | ✅ |
| 15 | `routes/boards.py:431` | 🟡 不一致 | 裸 `int()` vs `safe_int()` 处理 volume | ✅ |

**覆盖度：** 20 个验证候选中 19 个被确认（1 个 REFUTED，1 个 PLAUSIBLE）。按严重度裁剪到 top 15 — 正确性 bug 优先于清理/高度类发现（按 code-review skill 的规则）。

**多 agent 收敛（高置信信号）：**

- 6 个 agent → 发现 #4（K-line CB 重复）— 整个 review 里最强的信号
- 4 个 agent → 发现 #5（`get_stock_name` 回退）和发现 #10（陈旧 `// 100` 文档）
- 3 个 agent → 发现 #9（`make_kline_cache_key` 不 sort）

**建议修复顺序（杠杆最高的优先）：**

1. **#1**（explorer 运行时）— 3 行代码，解锁 UI。
2. **#2**（volume 单位漂移）— **同时**给 `StockQuote` schema 加 `volume_unit` 字段。
3. **#3**（坏掉的测试）— 1 行，解锁 CI。
4. **#4 + #11**（重构到 `_with_failover`）— 杠杆最高的一次重构；一次性把 kline、realtime、index-realtime 都搞定。
5. **#5**（恢复 `get_stock_name` 回退）— 10 行，解锁冷启动。
6. **#6 + #7**（审计 `get_index_historical` + `industry` fetcher emit）— 同一个 commit 里把 #6-#8 的死接口面都清掉。
7. **#8 + #10 + #12**（文档更新）— 合成一个 docs commit。
8. **#9 + #13**（cache.py 清理）— 改动小。
9. **#14 + #15**（UX / 一致性）— 最后的清理 commit。
