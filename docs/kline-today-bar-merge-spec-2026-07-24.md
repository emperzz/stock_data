# K 线今日 Partial Bar 合并 — Spec

- **Date**: 2026-07-24
- **Status**: Draft (待 review)
- **Scope**: `/stocks/{code}/kline` + `/indices/{code}/kline` 路由层
- **Issue path**: 数据范围漂移 + 缺少"今日 partial bar"的统一契约

## 1. 背景与问题

### 1.1 现状

stock/index K 线 API 当前跨 7 个 fetcher（Tushare / Baostock / Zzshare / Akshare / Yfinance / Zhitu / Myquant）failover 取首个非空 DataFrame。Agent 调研显示（见 `docs/architecture-review-2026-07-16.md` 旁边的子调研）：

| Fetcher | 实际行为（当前实现） | 关键原因 |
|---|---|---|
| Tushare P0 | 止于昨日收盘 | `daily` 历史接口，付费 tier 才有盘中（如未来变更则可能含今日） |
| Baostock P1 | 止于昨日收盘 | `query_history_k_data_plus` 入库完后才返回 |
| Zzshare P2 | 止于昨日收盘 | 走 `api.daily()`，未走实时 `rt_k` |
| Akshare P3 | 理论可含今日（透传 EM） | 但 manager 在 Akshare 之前 short-circuit，**实际永不调用**；"理论可含"对用户不可达 |
| Yfinance P4 | 止于昨日收盘 | `yf.download(end=...)` **end 是 exclusive** |
| Zhitu P5 | 止于昨日收盘 | 文档明示 15:30-17:10 更新；股票日线还直接不支持 |
| Myquant P9 | 止于昨日收盘 | 文档明示 18:00 后才入当日 |

**当前实测**：所有 fetcher 路径下，用户拿到的 K 线都是"止于昨日"。今日 partial bar 普遍缺失。

### 1.2 风险

- 用户调 `/stocks/600519/kline?days=100` 拿 100 根，看不到今日实时 tick
- 需另调 `/stocks/600519/quote` 才能看到当前价，2 次调用
- 同一代码、同一时间点，不同 fetcher 主备切换/熔断恢复时，**理论上**会切换数据范围（虽然实际 Yfinance exclusive 兜底了，但依赖的是不打算依赖的巧合）
- 技术指标（MA5 等）的"今日"那根在不同 fetcher 路径下行为不可预测

## 2. 目标

**强制 K 线 routes 输出"含今日 partial bar"语义**，不论底层 fetcher 是否实际提供。

### 2.1 关键决策

| 决策 | 选择 | 理由 |
|---|---|---|
| 默认是否合并 | **默认合并** | 用户调 K 线时通常要"今天为止" |
| 合并时机 | **指标计算之后** | partial bar 跳动会污染 MA/MACD |
| 阈值检查 | **`df.iloc[-1]["date"] == today`** | 已含 today 直接返回，避免无谓 quote 调用 |
| end_date 行为 | **用户显式传历史日期不合并** | 用户意图明确 |
| 交易日判断 | **A 股 `is_trade_date(today)`** | 周末/节假日不补今日 |
| 实现位置 | **route 层 helper** | 不污染 manager 的"路由不定语义"边界 |
| 失败处理 | **graceful fallback** | quote 失败 → 返回原 K 线，不抛错 |

### 2.2 非目标

- 不改 fetcher 内部行为（Yfinance `end+1 day` 等 fetcher 边界问题**不在本次范围**）
- 不改 `KLineData` schema（不加 `is_partial` 字段；用户看 `df.iloc[-1]["date"] == today` 即可判断）
- 不修 manager 短路逻辑（不动 failover 行为）
- 不把今日 partial bar 纳入 `?indicators=` 计算
- 不持久化今日 bar（仍然走实时）

## 3. 行为契约

### 3.1 触发条件（AND 关系）

`frequency ∈ {"d", "w", "m"}`（**仅日/周/月频段触发**；1m/5m/15m/30m/60m 分钟频段不触发，因为 quote 是单点 tick，混入聚合 bar 是语义错误） **AND** `end_date`（不论显式还是默认）包含今天 **AND** 今天在 A 股交易日历中 **AND** 当前 K 线响应末根日期 ≠ 今天。

`end_date` 包含今天的精确含义：`effective_end_date >= today_str`（字符串字典序 == ISO 日期序）。包含 `end_date = today` 和 `end_date = 未来日期` 两种情况。

### 3.2 helper 调用时序

```
fetch_kline(asset="stock"|"index")
    → apply_indicators()
    → maybe_merge_today_bar()       ← 新增
    → build_response()
```

注：合并发生在指标计算之后，partial bar 不带指标。

### 3.3 合并规则

| 末根日期 | 行为 | 是否调用 quote |
|---|---|---|
| `== today` | 不合并，原样返回 | ❌ |
| `< today` | 追加今日 partial bar | ✓（best-effort） |
| `> today` | **视为异常**（fetcher 异常 / 跨时区错乱）；记录日志，丢弃该行，原样返回其余 | ❌ |
| `df` 空 | 原样返回 | ❌ |

### 3.4 字段映射

partial bar 的字段来自 `UnifiedRealtimeQuote`：

| KLineData 字段 | UnifiedRealtimeQuote 来源 | None 时行为 | 备注 |
|---|---|---|---|
| `date` | `date.today().isoformat()` | n/a | quote 无 date 字段 |
| `open` | `safe_float(quote.open_price, 0.0)` | 0.0 | 不能污染 dtype |
| `high` | `safe_float(quote.high, 0.0)` | 0.0 | 同上 |
| `low` | `safe_float(quote.low, 0.0)` | 0.0 | 同上 |
| `close` | `quote.price` | 必须非 None（否则不合并） | 关键判定 |
| `volume` | `safe_int(quote.volume, 0)` | 0 | type: `int`(share) |
| `amount` | `safe_float(quote.amount, None)` | 保留 None | nullable 字段 |
| `pct_chg` | `safe_float(quote.change_pct, None)` | 保留 None | nullable 字段 |

**`safe_float` / `safe_int` 来自 `stock_data.data_provider.core.types`**（项目内统一处理 NaN/inf/-inf 的工具，与既有规范一致）。

### 3.5 防御规则

| 条件 | 动作 |
|---|---|
| `frequency` 是 minute（1m/5m/15m/30m/60m） | 提前返回（不触发合并） |
| `df` 空 | 原样返回 |
| `df.iloc[-1]["date"]` 含时间分量（minute freq） | `[:10]` 截断后比较 |
| `quote is None` | 不合并，返回原 df |
| `quote.price is None` | 不合并 |
| `quote.volume is None` | `safe_int(..., 0)` 写入 0 |
| `quote.open_price` / `high` / `low` None | `safe_float(..., 0.0)` 兜底（避免污染 dtype） |
| `quote.low > quote.high` 等异常 | 信任上游，不夹值 |
| `get_realtime_quote` 抛异常 | except 兜底，不合并 |
| `is_trade_date` 抛异常（DB 锁 / schema 损坏） | except 兜底，不合并（fail-closed） |
| `is_trade_date` 冷表返回 False | 不合并（无 retry / lazy fill；用户需手动 refresh calendar） |

### 3.6 索引路径

`manager.get_index_realtime_quote(code)` 返回同样的 `UnifiedRealtimeQuote | None`，字段映射与 stock 路径一致。

## 4. 判定矩阵（测试用例源）

| `end_date` | today is 交易日 | df 末根日期 | quote 状态 | 期望 |
|---|---|---|---|---|
| `2026-07-22`（昨天） | 是 | 任意 | 任意 | 不合并（end 不含 today） |
| `2026-07-24`（今天） | 否（周末） | 任意 | 任意 | 不合并（非交易日） |
| `2026-07-24` | 是 | `2026-07-23` | 有效 | 合并 |
| `2026-07-24` | 是 | `2026-07-24` | 任意 | 不合并（fetcher 已给） |
| `2026-07-25`（明天） | 是 | `2026-07-23` | 有效 | 合并（today 在范围内） |
| 不传 | 否（周末） | 任意 | 任意 | 不合并 |
| 不传 | 是 | `2026-07-23` | None | 不合并（graceful） |
| 不传 | 是 | `2026-07-23` | `price=None` | 不合并 |
| 不传 | 是 | `2026-07-23` | 有效 | 合并 |
| 任意 | 是 | `df` 空 | 任意 | 不合并 |

## 5. 风险与权衡

| 风险 | 触发 | 缓解 |
|---|---|---|
| Cold persistence → `is_trade_date` 返回 False | 首次安装 / 持久化空 | fail-closed；用户**需手动**调 `update_cached_calendar` 才能恢复（无 lazy fill 路径） |
| `is_trade_date` 自身抛异常 | DB 锁 / schema 损坏 | helper 内 try/except 兜底，不合并 |
| `is_trade_date` 缓存过期 | 节假日刚发布未更新 | 低概率；用户可手动 refresh calendar |
| Fetcher 返回 today bar 但数据陈旧（close=pre_close） | Yfinance cache miss / Tushare 免费版 | 用户契约"有则返回"；不强行覆盖 |
| **时区错位** | server 跑在 UTC / 跨时区节点 | **假定 server 跑在 CST（Asia/Shanghai）**；非 CST 环境下 `date.today()` 与 A 股交易日可能错位（晚 8h 才跨日）。本 spec 不引入 env 配置；若未来需要再加 `STOCK_TZ` env |
| **kline 自身 5 min cache** | TTL=300s（`api/cache.py:15`） | 用户在 10:00 拿到 today bar，14:55 缓存才过期 → 盘中 today bar 最多陈旧 300s。可接受 trade-off |
| 30s 实时 quote cache | 短期反复调 | 30s 内 quote 复用，0 成本 |
| Yfinance `end-exclusive` | 实际导致末根 ≤ yesterday | helper 兜底，无副作用 |
| Manager 短路 | Tushare/Baostock 抢先 | 无影响（helper 在 manager 之后跑） |
| 分钟频段（1m/5m/15m/30m/60m） | frequency ≠ d/w/m | 直接不触发 helper（无混合语义） |
| 缓存过期瞬间并发触发 N 次 quote | TTL=300s 边界 | 一次 cache 填充后命中；N 上限 = 客户端并发数，可接受 |

## 6. 测试契约

### 6.1 单元测试（`tests/test_kline_today_merge.py`）

16 个 case，按 §4 判定矩阵 + 边界：

- `end_date` 显式 / 默认 / 未来 / 过去
- `is_trade_date` 返回 True / False / 抛异常 / 空表
- df 末根 = today / 昨天 / 空 / **未来日期**
- df 末根日期含时间分量（minute freq `"YYYY-MM-DD HH:MM:SS"` 字符串）→ `[:10]` 截断比较
- 多行 df（100 行 + 末根=昨天）→ 合并后第 101 行为 today
- quote 有效 / None / `price=None` / `volume=None` / `open_price=None`
- **frequency 维度**：1m/5m/15m/30m/60m → 不合并（不调 quote）
- stock / index 路径
- **关键断言**：`manager.get_realtime_quote.assert_not_called()` 当末根 = today
- **关键断言**：`is_trade_date` 抛异常时不合并

### 6.2 集成测试

不新增。现有 `tests/test_routes.py::TestRoutes.test_kline_*` 覆盖主要路由；可通过 patch `date.today()` 验证今日 bar 出现。

### 6.3 不写的测试

- 真实网络（live_network）下的 today bar 实际值——这是上游契约，不在 server 范围
- 跨 fetcher failover 场景下的 today bar 行为——manager 行为不变
- 缓存命中时 helper 不被调用——集成层覆盖，初版单测不重复

## 7. 文档更新

修改 `CLAUDE.md`：

- **位置 1**：「Indicator Computation」节后追加新节「K-line today's partial bar」（语义相邻：都在 K-line 取得后的二次合成）
- **位置 2**：「Anti-Patterns to Avoid」节追加通用化表述（不绑定项目特定细节）

## 8. 验证

- `pytest tests/test_kline_today_merge.py -v` 全绿
- `pytest -m "not live_network"` 全绿（默认 dev 循环）
- 手测：`curl localhost:8888/api/v1/stocks/600519/kline?days=5` 在 2026-07-24 交易时间内，应返回 6 根（含 2026-07-24 partial）
- 手测：`curl localhost:8888/api/v1/stocks/600519/kline?days=5&end_date=2026-07-22` 应返回 5 根（止于 2026-07-22）

## 9. 失败回滚

helper 是纯加法（merge 逻辑在指标之后）——若 quote 接口全挂，K 线仍返回原 settle 状态。无破坏性，回滚一行 delete 即可。
