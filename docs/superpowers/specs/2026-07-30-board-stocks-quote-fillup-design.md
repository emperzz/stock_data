# `/boards/{code}/stocks` Suffix Quote Fillup (跨端点 quote 缓存复用)

**Date**: 2026-07-30
**Status**: Implemented (2026-07-30)
**Author**: brainstorm session
**Scope**: `stock_data/api/schemas.py`, `stock_data/data_provider/persistence/board.py`

---

## 1. Context

`GET /api/v1/boards/{code}/stocks?include_quote=true&source=ths` 在 board 成员数 > 50 时,返回 suffix 行(`stock_code` 有,所有 quote 字段 `None`)。根因是 THS upstream `q.10jqka.com.cn` 的 board-stocks 端点是分页排行表(`page_size=10`,硬上限 5 页 = 50 行,`ths_fetcher.py:1237-1240` `top_n = max(1, min(top_n, 50))`)。

当前补全机制(`persistence/board.py:1314-1368`)在 `include_quote=true` 时无条件调一次 `ZzshareFetcher.plates_stocks` 拿全成员,拼成 suffix 行;但 `ZzshareFetcher.get_board_stocks` 只投影 `stock_code/stock_name/exchange`(`zzshare_fetcher.py:725-763`),所有 quote 字段都是 `None`。

**后果**:对成员数 100-900 的典型概念/行业 board,client 拿到的 50% ~ 95% 行 quote 全 null,而 `/api/v1/stocks?include_quote=true` 实际上已经拉过这批股票的全市场 quote 缓存(`_stock_list_quote_cache` 60s + `_stock_list_quote_slow` 7d,`/stocks` 路由 `stocks.py:246-285`)。数据**已经存在**,只是没被复用。

## 2. Goal

复用 `/api/v1/stocks` 的全市场 quote 进程内缓存,给 board-stocks 的 suffix 行补 quote 字段,实现:

- **零 upstream 浪费**:`/stocks` 已经维护的 60s / 7d 缓存直接 read,cache 命中时不发任何网络请求
- **缓存共享**:不新建 namespace / TTL / cache slot
- **保真**:THS top-50 已有 quote 完全不动(高保真,字段最丰富),只补 suffix
- **失败安全**:cache miss + fetch 失败时,suffix 行保持 `None`,响应不 5xx

## 3. Non-Goals

- **不动 THS top-50 已有 quote**:避免跨源时间错位(THS quote 抓取后全市场 quote 可能更新 1-60s)
- **不动 ZZSHARE / EastMoney / Zhitu fetcher**:`persistence/board.py` 是唯一改动点
- **不动 `/stocks` 路由**:我们只 read 它的 cache,不改它的逻辑
- **不解决 THS top-50 行的 3 个字段缺口**:`change_speed` / `free_float_shares` / `float_market_cap` 是 THS upstream 14 列没有的,全市场 quote 也不暴露,因此 suffix 行的这 3 个字段保持 `None`,且 THS top-50 行的对应字段也不会被任何方式补全
- **不解决 THS top-50 行 `volume` 字段缺口**:`ThsFetcher._parse_ths_board_stocks_row`(`ths_fetcher.py:3163`)硬编码 `volume: None`(14 列里 idx 10 是成交额不是成交量)。suffix 行的 `volume` 可以从全市场 quote 补上(`UnifiedRealtimeQuote.volume` 有);但 THS top-50 行的 `volume` 仍为 None,等后续如果有真正 THS 批量 quote API 再说
- **不做字段级跨源合并**:不引入"已有字段是否被全市场 quote 覆盖"这种冲突规则,只补 suffix 全空行

## 4. Design

### 4.1 Schema 字段调整(`stock_data/api/schemas.py`)

#### 4.1.1 字段重命名 + 新增

`BoardStockInfo` 字段变更:

| 字段 | 变更 | 来源 / 备注 |
|---|---|---|
| `amplitude` | **rename** → `amplitude_pct` | 对齐 `StockQuote.amplitude_pct`(`schemas.py:81`);fallback 计算 `(high - low) / pre_close * 100` 复用 `StockQuote.from_unified_quote` 行 161-164 同一段逻辑 |
| `open` | **新增** | `UnifiedRealtimeQuote.open_price` |
| `high` | **新增** | `UnifiedRealtimeQuote.high` |
| `low` | **新增** | `UnifiedRealtimeQuote.low` |
| `prev_close` | **新增** | `UnifiedRealtimeQuote.pre_close` |

其余字段保持不变(包括 `change_speed` / `free_float_shares` / `float_market_cap` 等 THS 独有字段,以及 `is_limit_up` / `lb_count` 等 ZT-pool join 字段)。

**`_build_board_stock_info` 路由投影(`boards.py:69-100`)同步调整**:

- `amplitude_pct=s.get("amplitude")` —— 读 fetcher dict 用的 `amplitude` key(THS upstream + helper 投影),写入模型字段 `amplitude_pct`
- `turnover_pct=s.get("turnover_rate")` —— 已有映射,**保留**
- **新增** `open=s.get("open")` / `high=s.get("high")` / `low=s.get("low")` / `prev_close=s.get("prev_close")` —— 4 个新字段读,THS top-50 行为 None(THS upstream 14 列没),suffix 行有值(来自 helper)

不引入 Pydantic `serialization_alias`(ponytail:alias 增加复杂度)。模型字段名(`amplitude_pct` / `turnover_pct` / `open` / `high` / `low` / `prev_close`)直接对齐 `StockQuote`,JSON 响应直接输出新字段名,client 读到的就是新名。

**不新增**:
- `close` / `current_price`:`price` 已存在且语义等同
- `pb_ratio` / `total_mv` / `circ_mv` / `pb` / `mcap_yi`:`StockQuote` 也未直接命名(`StockQuote` 用 `pb` / `mcap_yi` 等),不符合"两 schema 交集"原则

**不加 `quote_fill_source` 字段**:补全源信息落到 logger,client 关心的是字段值,不关心补全路径。

#### 4.1.2 Quote 投影 helper(`persistence/board.py`)

**注意**:工厂方法**不**是 `BoardStockInfo` classmethod,改为 **module-level helper 在 `persistence/board.py`**,原因: suffix 投影后的 dict 必须沿用 fetcher upstream-style keys(`stock_code`/`stock_name`/`turnover_rate`/`amplitude`/`open`/`high`/`low`/`prev_close`),否则 `update_cached_board_stocks`(`board.py:2055-2070`)的 `s["stock_code"]` 会抛 `KeyError`,导致大 board 的 `include_quote=true` 请求 **500**。

`BoardStockInfo` 字段名(`code`/`name`/`amplitude_pct`/`turnover_pct`/`open`/`high`/`low`/`prev_close`)只在最终 JSON 响应上由 `_build_board_stock_info`(`boards.py:69-100`)投影,不在内部 dict 上使用。

```python
def _project_unified_quote_to_dict(
    code: str, name: str, q: "UnifiedRealtimeQuote",
) -> dict:
    """Project UnifiedRealtimeQuote onto an upstream-style dict for
    suffix row enrichment. Returns 13 quote fields + stock_code/name
    using fetcher-style keys (stock_code/stock_name/turnover_rate/
    amplitude/open/high/low/prev_close) so the result is
    interchangeable with THS/ZZSHARE fetcher output rows.

    Reuses the same amplitude fallback logic as StockQuote.from_unified_quote
    (schemas.py:156-192): when q.amplitude is None and high/low/pre_close
    are all set, compute (high - low) / pre_close * 100.

    THS-only fields (change_speed, free_float_shares, float_market_cap)
    are not set here — they stay absent from the returned dict and
    surface as None via the route layer's _build_board_stock_info.

    Added 2026-07-30 alongside the cross-endpoint quote-cache fillup:
    /boards/{code}/stocks?include_quote=true suffix rows (members
    beyond THS's 50-cap) are enriched from the /api/v1/stocks
    full-market quote cache via this helper.
    """
    amplitude = q.amplitude
    if (
        amplitude is None
        and q.high is not None
        and q.low is not None
        and q.pre_close
    ):
        amplitude = (q.high - q.low) / q.pre_close * 100
    return {
        "stock_code": code,
        "stock_name": name or q.name,
        "price": q.price,
        "open": q.open_price,
        "high": q.high,
        "low": q.low,
        "prev_close": q.pre_close,
        "change_amount": q.change_amount,
        "change_pct": q.change_pct,
        "volume": q.volume,
        "amount": q.amount,
        "turnover_rate": q.turnover_rate,
        "amplitude": amplitude,
        "volume_ratio": q.volume_ratio,
        "pe_ratio": q.pe_ratio,
    }
```

补全字段:**13 个 quote 字段**,以 fetcher upstream-style keys 输出 —— `price / open / high / low / prev_close / change_amount / change_pct / volume / amount / turnover_rate / amplitude / volume_ratio / pe_ratio`(加 `stock_code` / `stock_name` 来自 ZZSHARE suffix row)。

`BoardStockInfo` 字段名(`code`/`name`/`amplitude_pct`/`turnover_pct`/`open`/`high`/`low`/`prev_close`)在 route 层由 `_build_board_stock_info` 做映射(见 §4.1.1 字段变更表)。

### 4.2 Helper + 调用端(`stock_data/data_provider/persistence/board.py`)

#### 4.2.1 新增模块级 helper

```python
def get_cached_market_quotes(manager) -> list | None:
    """Read the /api/v1/stocks full-market quote cache. On miss, fetch
    and write back. Returns the unsorted, unsliced upstream list, or
    None on upstream failure.

    Reuses the same cache namespace (stock_list_quote:csi) and TTL
    (60s intraday, 7d close-tagged slow) as /stocks?include_quote=true,
    so any request that touches /stocks naturally warms this cache.

    Cache hit = zero upstream. Cache miss + fetch fail = None, which
    leaves suffix rows at None in the caller — never raises, by
    contract (the route layer's include_quote path is best-effort).
    """
    from ..cache import (
        cached_lookup,
        cached_store,
        get_stock_list_quote_cache,
        get_stock_list_quote_slow,
        is_cache_enabled,
    )
    from datetime import datetime, time as dt_time, timedelta
    from zoneinfo import ZoneInfo

    cache_key = "stock_list_quote:csi"  # 复用 /stocks key
    # 时段判断逻辑与 /stocks 一致(stocks.py:258-285)
    is_trade_day = trade_calendar.is_trade_date(
        datetime.now(_CST).date().isoformat()
    )
    in_intraday = (
        (dt_time(9, 15) <= datetime.now(_CST).time() < dt_time(11, 30))
        or (dt_time(13, 0) <= datetime.now(_CST).time() < dt_time(15, 0))
    )
    if in_intraday:
        hit = cached_lookup(get_stock_list_quote_cache, cache_key, "stock_list_quote")
        if hit is not None:
            return hit[0]  # (quotes, source)
    else:
        hit = cached_lookup(get_stock_list_quote_slow, cache_key, "stock_list_quote")
        if hit is not None:
            cached_date, cached_session, cached_quotes, cached_source = hit
            # 简化:board_stocks 不做 session 严格校验(由 /stocks 维护),
            # 拿旧 session 数据顶多导致 suffix quote 滞后 1 个 session,
            # 不影响正确性。
            if cached_quotes is not None:
                return cached_quotes
    # cache miss → fetch
    quotes, source = manager.get_realtime_quotes("csi")
    if not quotes:
        return None
    if in_intraday:
        cached_store(get_stock_list_quote_cache, cache_key, (quotes, source))
    else:
        target_date, target_session = _latest_past_close()
        cached_store(
            get_stock_list_quote_slow, cache_key,
            (target_date, target_session, quotes, source),
        )
    return quotes
```

**为什么 helper 复用 `/stocks` 的 cache,而不是新建**:

- `_stock_list_quote_cache` / `_stock_list_quote_slow` 已经是模块级进程内 TTLCache(`cache.py:31-37`),key 命名空间是 `stock_list_quote:csi`
- 任何 `/api/v1/stocks?include_quote=true` 请求自然维护这个 cache
- 60s fast / 7d slow TTL 与交易时段匹配的语义已经写好,不需要重做
- 不增加 cache slot、不污染命名空间、不需要新 circuit breaker

**为什么 slow cache 不严格校验 session**:

- `/stocks` 在 close cross(11:30/15:00)时通过比较 `(cached_date, cached_session)` 决定 refetch
- board_stocks 是消费方,即使拿到上一个 session 的 quote 顶多是 suffix 行 quote 滞后 30 分钟,不影响正确性(且 suffix 行本身是当天数据,字段滞后远好于 null)
- 简化逻辑,避免 helper 内重复 `_latest_past_close` + `_is_intraday` 全部判断

#### 4.2.2 `get_board_stocks` 调用点修改

在 `persistence/board.py::get_board_stocks`(`board.py:1300-1382`)的 `include_quote=True` 分支,**最终拼接 `final_stocks` 之前**,插入 suffix 补全:

```python
# 现有代码(board.py:1319-1336)拿 zz_rows
suffix_no_quote: list[dict] = []
try:
    zz_rows, _ = manager.get_board_stocks(
        board_code=board_code, source="zzshare", include_quote=False,
    )
except DataFetchError as e:
    logger.warning(f"[BoardCache] ZZSHARE fill-in for {board_code} failed: {e}; ...")
    zz_rows = []

# 现有代码去重得 suffix_no_quote
quote_codes = {s["stock_code"] for s in stocks if s.get("stock_code")}
suffix_no_quote = [
    r for r in (zz_rows or [])
    if r.get("stock_code") and r["stock_code"] not in quote_codes
]

# === 新增:suffix 补全 ===
if suffix_no_quote:
    cached_quotes = get_cached_market_quotes(manager)
    if cached_quotes:
        q_index = {q.code: q for q in cached_quotes}
        n_filled = 0
        enriched_suffix: list[dict] = []
        for row in suffix_no_quote:
            sc = row.get("stock_code")
            q = q_index.get(sc)
            if q is None:
                # 该股票不在全市场 quote 里(如停牌 / 新上市 / 北交所冷门)
                enriched_suffix.append(row)
                continue
            enriched_suffix.append(
                _project_unified_quote_to_dict(
                    code=sc, name=row.get("stock_name", ""), q=q,
                )
            )
            n_filled += 1
        suffix_no_quote = enriched_suffix
        logger.info(
            f"[BoardCache] suffix fill: {n_filled}/{len(suffix_no_quote)} "
            f"rows enriched from /stocks quote cache"
        )

# 之后照旧拼接 final_stocks
```

#### 4.2.3 不动 `include_quote=False` 分支

该分支已经走 F10 / ZZSHARE 完整成员 + THS AJAX 部分 quote 的现有链路,本次改动只针对 `include_quote=True` 的 suffix。

## 5. Data Flow

```
GET /boards/{code}/stocks?source=ths&include_quote=true
  │
  ▼ boards.py::get_board_stocks (route)
  │  - Literal 校验 + sort_by/top_n 校验(已有)
  │
  ▼ stock_board_cache.get_board_stocks
  │
  │ needs_refresh = True (include_quote=True)
  │
  ▼ fetch_board_stocks_with_zzshare_fallback
  │  source=ths+include_quote=True → THS 强制,top-N <= 50
  │  - manager.get_board_stocks(source=ths, include_quote=True, sort_by, top_n)
  │  - returns 50 rows with quote
  │
  ▼ ★ 新增:补全 suffix
  │  zz_rows = manager.get_board_stocks(source=zzshare, include_quote=False)
  │  suffix_no_quote = [r for r in zz_rows if r.code not in THS top-50]
  │  if suffix_no_quote:
  │      cached_quotes = get_cached_market_quotes(manager)
  │        ├── read _stock_list_quote_cache / _stock_list_quote_slow
  │        ├── miss → manager.get_realtime_quotes("csi") → write back
  │        └── return list[UnifiedRealtimeQuote] | None
  │      q_index = {q.code: q for q in cached_quotes}
  │      enriched = _project_unified_quote_to_dict(code, name, q) × N
  │
  ▼ final_stocks = THS top-50 (quote) + suffix enriched (13 字段)
  ▼
  ▼ update_cached_board_stocks(quote 字段投影丢弃)
  ▼
  ▼ boards.py 构造 BoardStocksResponse
  ▼
  BoardStocksResponse(
    board, stocks, query_source, data_source, effective_source,
    quote_source, quote_error, quote_truncated, ...
  )
```

## 6. Error Handling

| 场景 | suffix 字段 | 响应 | 日志 |
|---|---|---|---|
| cache 命中 | 13 字段已补 | 200 | `INFO: suffix fill: N/N rows enriched` |
| cache miss, fetch 成功 | 13 字段已补 | 200 | `INFO: suffix fill: N/N rows enriched` + `/stocks` cache 被写回 |
| cache miss, fetch 失败/空 | suffix 保持 `None` | 200(不 5xx) | `WARNING: get_cached_market_quotes returned None` |
| suffix 为空(THS top-50 已覆盖全 board) | 不触发补全 | 200 | 无 |
| `include_quote=False` 路径 | 不触发 | 200 | 无 |
| 个别 code 在全市场 quote 中不存在(停牌/新上市/北交所冷门) | 该 row 保持 `None` | 200 | 无(数量级小,没必要 log) |
| `ZZSHARE fill-in` 失败(已有) | suffix 为空 | 200 | `WARNING` 已有 |
| 字段级失败(任一 q.amplitude fallback 算不出) | 该字段 `None` | 200 | 无(fallback 是 best-effort) |

完全沿用 `boards.py:691-733` 的 "best-effort, never raises" 模式。

## 7. Backward Compatibility

### Breaking change 列表

1. **`BoardStockInfo.amplitude` → `amplitude_pct`** —— 字段重命名,client 解码旧 JSON 字段名会丢值。
   - 缓解:在 `BoardStocksResponse` 的 OpenAPI / explorer 文档里标注 breaking;CHANGELOG 写明。
   - **不加 Pydantic alias**(ponytail:alias 增加复杂度,直接改更清晰)。

### Non-breaking

- 新增 `open` / `high` / `low` / `prev_close` 字段 —— Pydantic 默认值 `None`,旧 client 忽略
- 新增 helper `_project_unified_quote_to_dict` —— 服务端内部,不影响 client
- `get_cached_market_quotes` helper —— 服务端内部
- suffix 行字段填充 —— 旧 client 拿到的字段值更全,无负面

## 8. Testing

### 8.1 单元测试(`tests/test_persistence_board.py` 新增)

```python
class TestSuffixQuoteFillup:
    def test_suffix_quote_fill_cache_hit_enriches_13_fields(self):
        """Cache 命中时,suffix 行 13 字段被填充,THS 独有字段保持 None。"""
        ...

    def test_suffix_quote_fill_cache_miss_triggers_fetch_and_writes_back(self):
        """Cache miss 时,触发 upstream fetch,结果写回 /stocks cache,
        suffix 同步被填充。"""
        ...

    def test_suffix_quote_fill_fetch_failure_keeps_suffix_none(self):
        """Fetch 失败时,suffix 行 13 字段保持 None,不抛异常。"""
        ...

    def test_suffix_quote_fill_skips_codes_not_in_market_quote(self):
        """个别 code 不在全市场 quote 中(停牌/新上市),该行保持 None。"""
        ...

    def test_ths_top50_unmodified_by_fillup(self):
        """THS top-50 行的字段(尤其 5 个 THS 独有)不被全市场 quote 覆盖。"""
        ...

    def test_get_cached_market_quotes_returns_none_on_full_failure(self):
        """manager.get_realtime_quotes 返回 None 时,get_cached_market_quotes 返回 None。"""
        ...
```

### 8.2 Quote 投影 helper 单元测试(`tests/test_persistence_board.py`,作为 helper 单元)

注:投影 helper `_project_unified_quote_to_dict` 是 module-level 函数,在 `persistence/board.py`,**不**是 `BoardStockInfo` classmethod。测试在 `tests/test_persistence_board.py` 而非 `test_schemas.py`,与 §8.1 helper 单元测试同文件。

```python
class TestProjectUnifiedQuoteToDict:
    def test_amplitude_fallback_when_unified_amplitude_is_none(self):
        """q.amplitude=None, high/low/pre_close 都齐 → dict["amplitude"] 算出 fallback。"""
        ...

    def test_amplitude_passthrough_when_unified_amplitude_set(self):
        """q.amplitude 已设,直接用 q.amplitude,不重新计算。"""
        ...

    def test_amplitude_none_when_no_fallback_inputs(self):
        """q.amplitude=None 且 high/low/pre_close 缺任一,dict["amplitude"]=None。"""
        ...

    def test_returns_upstream_style_keys(self):
        """返回 dict 用 stock_code/stock_name/turnover_rate/amplitude 等
        fetcher-style keys(不是 BoardStockInfo 字段名 code/name/
        turnover_pct/amplitude_pct),保证与 THS/ZZSHARE fetcher
        输出一致。"""
        ...

    def test_name_fallback_to_quote_name_when_param_empty(self):
        """name 参数空字符串时,fallback 到 q.name。"""
        ...

    def test_param_name_wins_over_quote_name(self):
        """name 参数非空时,param name 优先,保留 upstream 板块成员名。"""
        ...

    def test_ths_only_fields_not_in_dict(self):
        """change_speed / free_float_shares / float_market_cap 不出现在返回 dict
        (absence,不是 None),由 route 层 _build_board_stock_info 在
        投影时自然走 None。"""
        ...
```

### 8.3 集成测试(`tests/test_routes_boards.py` 新增 / 增强)

```python
class TestBoardStocksSuffixQuoteFillupE2E:
    def test_quote_field_amplitude_renamed_to_amplitude_pct_in_response(self):
        """大 board 响应 JSON 中,字段名是 amplitude_pct 而非 amplitude。"""
        ...

    def test_suffix_rows_have_open_high_low_prev_close(self):
        """suffix 行(>50 成员部分)有 4 个新字段。"""
        ...

    def test_ths_top50_has_all_ths_only_fields(self):
        """THS top-50 行(若有 change_speed 等)保留,不被补全覆盖。"""
        ...

    def test_include_quote_false_path_unchanged(self):
        """include_quote=False 时,响应字段与本次改动前一致(回归)。"""
        ...
```

### 8.4 回归测试

`tests/test_boards_stocks.py` 全部跑过,无新增失败:
- 旧字段 `amplitude` 的断言改为 `amplitude_pct`
- 涉及 `BoardStockInfo` 直构造的测试改为工厂方法或显式 `amplitude_pct=None`

### 8.5 Live network 标记

不需要。所有测试可用 mock + SQLite 内存数据库跑,不需要真 upstream。

## 9. Risks & Mitigations

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| `amplitude` rename 破坏现有 client | 中 | 中 | 文档 + CHANGELOG 明示;不加 alias(ponytail) |
| 全市场 quote 与 THS quote 时间错位导致数据不一致 | 高 | 低 | 仅补 suffix,THS top-50 完全不动;time drift 顶多 60s |
| 多个 board-stocks 并发请求时 `/stocks` cache miss 风暴 | 低 | 中 | `_stock_list_quote_cache` 是 `cachetools.TTLCache`,无锁;并发 miss 会触发多次 upstream,但都走 `QUOTE_LIST_CIRCUIT_BREAKER` 熔断保护 |
| helper 复用 `/stocks` cache 命名空间导致 `/stocks` 端点行为隐式变化 | 低 | 中 | 我们只 `cached_lookup` + `cached_store`,key 命名一致;`/stocks` 路由代码无修改,行为不变 |
| `amplitude` 字段在 `BoardStockInfo` 已有 0-1 个 client 强依赖 | 低 | 低 | 字段在 2026-07-13 新增,客户端可能尚未依赖;探索器文档可见 |
| `_project_unified_quote_to_dict` 与 `StockQuote.from_unified_quote` 的 amplitude fallback 漂移 | 中 | 中 | 同一段 `(high - low) / pre_close * 100` 逻辑在两处出现(`schemas.py` + `persistence/board.py`),后续修改时需手动同步两个;考虑抽 `core/quote_math.py` 共用,但当前不必要 |

## 10. Files Changed

| 文件 | 变更类型 | 行数估算 |
|---|---|---|
| `stock_data/api/schemas.py` | `BoardStockInfo` 字段(rename `amplitude` → `amplitude_pct`,新增 `open`/`high`/`low`/`prev_close`) | ~20 行 |
| `stock_data/api/routes/boards.py` | `_build_board_stock_info` 增 4 个新字段读 + `amplitude` → `amplitude_pct` 映射 | ~10 行 |
| `stock_data/data_provider/persistence/board.py` | 新增 `_project_unified_quote_to_dict` helper + `get_cached_market_quotes` helper + `get_board_stocks` suffix 补全逻辑 | ~100 行 |
| `tests/test_persistence_board.py` | 新增 `TestGetCachedMarketQuotes`(4 用例) + `TestProjectUnifiedQuoteToDict`(7 用例) + `TestBoardStocksSuffixEnrichment`(2 用例) | ~250 行 |
| `tests/test_routes_boards.py` | 2 集成用例(`amplitude_pct` rename + 4 新字段默认 None) | ~40 行 |
| `docs/superpowers/specs/2026-07-30-board-stocks-quote-fillup-design.md` | 本 spec | — |

总计 ~420 行(测试占 ~70%)。

## 11. Open Questions

无未决 trade-off。所有设计决策(字段范围、字段命名、TTL 复用、cache 命名空间、是否加 `quote_fill_source`、是否动 THS top-50、是否引入 Pydantic alias、是否新建 fetcher)在 brainstorming 阶段已与用户确认。

## 12. References

- `persistence/board.py:1300-1382` —— suffix 拼接现有逻辑
- `ths_fetcher.py:1237-1240` —— THS 50-cap 根因
- `stocks.py:246-285` —— `/stocks` session-aware 缓存
- `cache.py:31-37` —— `_stock_list_quote_cache` / `_stock_list_quote_slow` 定义
- `core/types.py:55-91` —— `UnifiedRealtimeQuote` dataclass
- `schemas.py:156-192` —— `StockQuote.from_unified_quote`(amplitude fallback 复用参考)
- `zzshare_fetcher.py:725-763` —— ZZSHARE suffix row 只有 code/name/exchange

## 13. Implementation History

- **2026-07-30**: Implemented via plan `docs/superpowers/plans/2026-07-30-board-stocks-quote-fillup.md` on branch `feat/board-stocks-quote-fillup`. Commits landed in order:

  1. `feat(persistence): add _project_unified_quote_to_dict helper for suffix fillup` (Task 1 — helper + 7 unit tests)
  2. `feat(schemas): rename BoardStockInfo.amplitude → amplitude_pct + add open/high/low/prev_close` (Task 2 — schema rename + 4 new fields + `_build_board_stock_info` projection update + 2 E2E tests)
  3. `feat(persistence): add get_cached_market_quotes helper for cross-endpoint fillup` (Task 3 — `get_cached_market_quotes` reads shared `/stocks` cache, intraday/slow branch + slow-cache write tag inlined rather than duplicated as helpers; 4 unit tests)
  4. `feat(persistence): enrich /boards/{code}/stocks suffix from /stocks quote cache` (Task 4 — `_enrich_suffix_with_market_quote` + integration in `get_board_stocks`; 4 unit tests)
  5. `test: stub get_cached_market_quotes in board tests that don't exercise fillup` (Task 5 — pre-existing `test_persistence_board_topn.py` + `test_boards.py::TestBoardsSourceUnification` fixed to stub the new helper)

  Pre-existing test failures (`test_providers.py::TestAkshareFetcher`, `test_persistence_zzshare_fallback_live.py`, `test_stock_boards_eastmoney_source.py::test_stocks_boards_eastmoney_source_live`) were verified pre-existing via `git stash` comparison — caused by missing network/SDK conditions, not by this spec.

  **Decisions captured during implementation**:
  - Spec's "factory classmethod" design (v1) was changed to "module-level helper returning dict" (v2) after code-review caught a critical `KeyError` risk: `BoardStockInfo.model_dump()` emits model field names (`code`/`name`/`turnover_pct`/`amplitude_pct`), but the rest of the system (persistence + route) reads upstream-style keys (`stock_code`/`stock_name`/`turnover_rate`/`amplitude`). The helper directly returns an upstream-style dict to keep `update_cached_board_stocks` working.
  - Spec's "extract `_is_intraday` and `_latest_past_close` as separate helpers" (v1) was changed to "inline the logic in `get_cached_market_quotes`" (v2) after user feedback in execution: YAGNI, single call site, avoids cross-module dependency.
  - E2E tests for the rename + new fields were moved from Task 5 to Task 2 (where the rename lands) per code-review feedback (strict TDD, no forward-deps in test ordering).
