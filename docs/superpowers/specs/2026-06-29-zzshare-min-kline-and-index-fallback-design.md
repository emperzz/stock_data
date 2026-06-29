# ZzshareFetcher 分钟级 K 线 + 移除 INDEX→HISTORICAL 兜底

> 日期：2026-06-29
> 状态：设计稿（待用户审阅）
> 范围：两件事
> 1. 移除 `manager.get_kline_data` 中指数代码走 `INDEX_*` 失败时回落到 `HISTORICAL_*` 的兜底（"没有声明就是没有能力"）
> 2. 让 `ZzshareFetcher` 的统一 `get_kline_data(frequency="5|15|30|60")` 入口真正走到 `api.stk_mins`，覆盖 `/history?frequency=5` 与 `/intraday` 两个接口

---

## 0. 摘要

- **任务 1**：删除 `manager.py:308-326` 的 INDEX→HISTORICAL 兜底块。统一方法 `get_kline_data` 与既有专属方法 `get_index_historical`/`get_index_intraday` 行为对齐：能力不匹配即 `DataFetchError`。
- **任务 2**：在 `ZzshareFetcher._fetch_raw_data` 内对 minute 频率分发到 `api.stk_mins`（单日用 `start_date`），抽取 helper `_fetch_minute_kline` 与 `get_intraday_data` 共用底层 SDK 调用。
- **其他兜底模式扫描结论**：仅任务 1 命中"`HISTORICAL_*` 兜底 `INDEX_*` 兜底"模式。其余 7 处 fallback（`_with_source` slug 容错、`_with_failover` 主循环本身、SQLite 缓存层、Yfinance→Stooq、EastMoney concept→industry、Zzshare `lhb_detail`→`lhb_stock_history`、`stock_zh_a_minute` sina 兼容回退）均属不同语义（查找容错 / failover 设计要求 / 缓存层 / 单 fetcher 多上游 / 单 fetcher 内重试），按既有设计保留。

---

## 1. 现状

### 1.1 任务 1 相关 — 兜底位置

`stock_data/data_provider/manager.py:308-326`（`DataFetcherManager.get_kline_data`）：

```python
# Index codes prefer INDEX_HISTORICAL/INDEX_INTRADAY so fetchers can
# declare index support independently of stock K-line support, then
# fall back to HISTORICAL_DWM/HISTORICAL_MIN for backward compat.
if frequency in ("5", "15", "30", "60"):
    index_cap = DataCapability.INDEX_INTRADAY
    gen_cap = DataCapability.HISTORICAL_MIN
else:
    index_cap = DataCapability.INDEX_HISTORICAL
    gen_cap = DataCapability.HISTORICAL_DWM

if index_tag:
    market = index_tag
    capability = index_cap
    if not self._filter_by_capability(market, index_cap):
        capability = gen_cap  # ← 兜底
else:
    market = market_tag(stock_code)
    capability = gen_cap
```

### 1.2 任务 2 相关 — ZzshareFetcher 现状

**能力声明**（`zzshare_fetcher.py:77-88`）：

```python
supported_data_types = (
    DataCapability.HISTORICAL_DWM
    | DataCapability.HISTORICAL_MIN
    | ...
)
```

**两个 K 线入口**：

| 方法 | 路由来源 | minute 频率下行为 |
|---|---|---|
| `_fetch_raw_data(frequency="5")` | `BaseFetcher.get_kline_data`（即 `/history?frequency=5`） | 命中"w/m 分支"以外的 fall-through，**错调 `api.daily(...)`** 返回日线数据 |
| `get_intraday_data(period="5")` | `manager.get_intraday_data`（即 `/intraday`） | 直接调 `api.stk_mins(...)`，正确 |

**根因**：`BaseFetcher.get_kline_data`（`base.py:234-293`）固定走 `_fetch_raw_data`，从不走 `get_intraday_data`。Zzshare 的 `_fetch_raw_data` 把"非 d/w/m"全归到 `api.daily(...)`，minute 频率漏网。

### 1.3 其他兜底模式走查（保留项）

| 位置 | 模式 | 处理 |
|---|---|---|
| `manager.py:178-183` `_with_source` slug→全名 | 查找容错，不是能力兜底 | 不动 |
| `manager.py:248-275` `_with_failover` 主循环 | 按 capability 顺序 failover（设计要求） | 不动 |
| `manager.py:480-506` 日历 → SQLite 缓存 | 持久层缓存（设计要求） | 不动 |
| `manager.py:571-583` ZT 池 → 缓存 | 持久层缓存（设计要求） | 不动 |
| `fetchers/yfinance_fetcher.py:196/246/307` Yfinance→Stooq | 同 fetcher 多上游 | 不动 |
| `fetchers/zzshare_fetcher.py:715` `lhb_detail`→`lhb_stock_history` | 同 fetcher 双 API 互补 | 不动 |
| `fetchers/eastmoney_fetcher.py:1350` concept→industry | 同 fetcher 内重试 | 不动 |
| `fetchers/akshare/index_norm.py:143` `stock_zh_a_minute` sina 兼容 | 同 fetcher 字段映射 | 不动 |

---

## 2. 设计

### 2.1 任务 1 — 移除 INDEX→HISTORICAL 兜底

**变更点**（单文件单块）：`manager.py` `get_kline_data` 行 308-326 替换为：

```python
stock_code = normalize_stock_code(stock_code)
index_tag = index_market_tag(stock_code)

# Capability routing is capability-only. No declaration = no capability:
# when no fetcher declares INDEX_* for this market, _with_failover raises
# DataFetchError. This matches get_index_historical/get_index_intraday.
if frequency in ("5", "15", "30", "60"):
    capability = DataCapability.INDEX_INTRADAY
else:
    capability = DataCapability.INDEX_HISTORICAL

if index_tag:
    market = index_tag
else:
    market = market_tag(stock_code)
    capability = (
        DataCapability.HISTORICAL_MIN
        if frequency in ("5", "15", "30", "60")
        else DataCapability.HISTORICAL_DWM
    )
```

**行为变化矩阵**（manager.get_kline_data + 指数代码）：

| 频率 | 修改前路由 | 修改后路由 |
|---|---|---|
| `d/w/m` | INDEX_HISTORICAL →（空时）HISTORICAL_DWM | INDEX_HISTORICAL（无兜底） |
| `5/15/30/60` | INDEX_INTRADAY →（空时）HISTORICAL_MIN | INDEX_INTRADAY（无兜底） |

**影响 fetcher 集合**（按 capability 声明过滤）：

| 频率 | 修改前可能路由 | 修改后唯一路由 |
|---|---|---|
| 指数日线 | Akshare / Baostock / Yfinance / Tushare / Myquant +（兜底）Zhitu / Zzshare | Akshare / Baostock / Yfinance / Tushare / Myquant |
| 指数分钟 | Akshare / Myquant +（兜底）Zhitu / Zzshare / Baostock / Yfinance | Akshare / Myquant |

兜底分支消失后，`manager.get_kline_data("000300", frequency="d")` 在只装了 Zhitu/Zzshare 的环境会抛 `DataFetchError("All fetchers failed …")`。这与既有 `get_index_historical` 的行为一致。

**测试调整**：
- 检索 `tests/` 中是否对 `manager.get_kline_data` + 指数代码 + "fallback to HISTORICAL_*" 有断言。预期无（兜底是隐式行为，未必有显式测试）。
- 若有断言，按"应抛 DataFetchError 或无 fetcher"语义改写。
- 新增正向测试：`get_kline_data("000300", "d")` 在仅注册 INDEX_HISTORICAL fetcher 时成功；在仅注册 HISTORICAL_DWM fetcher（声明 INDEX_* 的一个都没）时抛 `DataFetchError`。

### 2.2 任务 2 — ZzshareFetcher 分钟级 K 线

**核心变更**（`zzshare_fetcher.py`）：

1. 抽取 helper `_fetch_minute_kline(stock_code, trade_date, freq) -> pd.DataFrame | None`，封装 `api.stk_mins(...)` 调用 + 异常兜底。
2. `_fetch_raw_data` 内增加 minute 分支：

```python
def _fetch_raw_data(self, stock_code, start_date, end_date, frequency="d", adjust=None):
    if frequency in ("w", "m"):
        raise DataFetchError(
            f"ZzshareFetcher 不支持周线/月线 (frequency={frequency})"
        )
    if frequency in ("5", "15", "30", "60"):
        freq = self._PERIOD_TO_FREQ.get(frequency, f"{frequency}min")
        # zzshare stk_mins 是单日 API；用 start_date 当交易日（与 Akshare 对齐）。
        # 多日区间下，end_date 内的数据无法在单次调用拿到；上层若需多日，应循环。
        df_minute = self._fetch_minute_kline(
            stock_code, _to_yyyymmdd(start_date), freq
        )
        if df_minute is None:
            raise DataFetchError(
                f"ZzshareFetcher 无分钟数据 for {stock_code} on {start_date}"
            )
        return df_minute
    # 日线：现有路径
    api = self._ensure_api()
    ...
    return api.daily(**kwargs)
```

3. `get_intraday_data` 重构：把 `api.stk_mins(...)` 调用挪入 `_fetch_minute_kline`，自身只做 column rename / `time` 字段提取 / 列裁剪。共享底层。

**新 helper 签名**：

```python
def _fetch_minute_kline(
    self, stock_code: str, trade_date_yyyymmdd: str, freq: str
) -> pd.DataFrame | None:
    """底层调 api.stk_mins,返回 DataFrame 或 None。统一 _fetch_raw_data 与 get_intraday_data。"""
    api = self._ensure_api()
    if api is None:
        return None
    ts_code = _to_zzshare_ts_code(normalize_stock_code(stock_code))
    try:
        df = api.stk_mins(ts_code=ts_code, trade_time=trade_date_yyyymmdd, freq=freq)
    except Exception as e:
        logger.warning(f"[ZzshareFetcher] stk_mins({ts_code}, {freq}) failed: {e}")
        return None
    if df is None or df.empty:
        return None
    return df
```

**adjust 处理**：minute 路径不传 `adj`（zzshare 上游文档明示分钟级无复权）。`_fetch_raw_data` 的 minute 分支忽略 `adjust` 参数，与既有 `get_intraday_data` 行为一致。

**产物 schema**：

| 路径 | 列 | 备注 |
|---|---|---|
| `/stocks/{code}/intraday` (`manager.get_intraday_data`) | `time, open, high, low, close, volume, amount` | 既有 `get_intraday_data` 路径，不变 |
| `/stocks/{code}/history?frequency=5` (`manager.get_kline_data`) | `date, open, high, low, close, volume, amount, pct_chg` | KLineData schema 仅承载 `date`，**minute 内 time 粒度在 /history 响应里丢失**——这是 `KLineData` schema 的固有限制，详见 §3.1 |

**测试矩阵**（`tests/test_zzshare_fetcher.py` 新增 / 调整）：

| 用例 | mock | 断言 |
|---|---|---|
| `_fetch_raw_data("5", trade_date=20260520)` | `api.stk_mins` 返回 3 行带 `trade_time` 的 df | 走 `stk_mins`、返回列含 `time` / `volume`、`time == "09:35:00"...` |
| `_fetch_raw_data("15")` | 同上 | 调用参数 `freq="15min"` |
| `_fetch_raw_data("5")` 在 SDK 不可用时 | mock `_ensure_api` 返回 None | 抛 `DataFetchError("…无分钟数据")` |
| `_fetch_raw_data("5")` adjust="qfq" | mock `stk_mins` | 断言调用 kwarg 不含 `adj` / `adjust` |
| `get_intraday_data` 不回归 | mock `stk_mins` | 既有 5 个用例继续通过 |

### 2.3 边界条件

| 情形 | 设计 |
|---|---|
| `manager.get_kline_data("000300", "5")` 无 INDEX_INTRADAY fetcher 可用 | `DataFetchError`（任务 1 兜底删除的必然结果） |
| `manager.get_kline_data("000300", "5")` 有 Akshare/Myquant 可用 | 路由到它们各自的 INDEX_INTRADAY 实现（既有） |
| `manager.get_kline_data("600519", "5")` | 路由到 HISTORICAL_MIN cap 的 fetcher；现在 ZzshareFetcher 也能正确返回（任务 2 修复） |
| `manager.get_kline_data("600519", "5", start_date=20260518, end_date=20260520)` | 区间传日线 `start_date=20260518`，ZzshareFetcher 取 `start_date` 当交易日（与 Akshare 行为对齐，区间外的数据不返） |
| `get_intraday_data("600519", "5")` 既有路径 | 不变；共用 `_fetch_minute_kline` |

---

## 3. 风险与约束

### 3.1 `/history?frequency=5` 的 time 粒度丢失

`KLineData` schema（`api/schemas.py`）的 `date: str \| None` 是单字符串字段，承载不了"日内多个时刻"。`/history` 走通 minute 后：

- 响应里每根 bar 的 `date` 都相同（都是 `start_date`）
- `time` 字段在 `KLineData` 里没有——lost
- `?indicators=` 在 minute 上行为未定义（indicator service 当前按 date 对齐）

**缓解**：本设计只承诺"两个接口都通到分钟级"，粒度差异由端点决定（`/history` 简化、`/intraday` 完整）。如果未来要 `/history?frequency=5` 返回完整日内粒度，需要扩展 `KLineData` schema 加 `time: str | None`——超出本设计范围，留待后续 spec。

### 3.2 区间 → 单日 的语义不一致

`/history` 允许 `start_date/end_date` 区间，但 Zzshare 分钟仅单日。处理：
- 与 Akshare 对齐：用 `start_date` 作为交易日
- 不在 API 层报错（避免破坏既有 Akshare 用户的预期）
- 在 fetcher docstring 标注限制

### 3.3 既有 `/intraday` 调用方不受影响

`get_intraday_data` 路径不变，仅内部实现从直接调 `api.stk_mins` 改为调 `_fetch_minute_kline`。外部契约（返回列、`time` 字段格式）保持。

---

## 4. 不在本次范围内

- KLineData schema 增加 `time` 字段
- `?indicators=` 在 minute 频率下的语义定义
- `manager.get_kline_data` 合并到 `/kline` 统一端点（见既有 spec `2026-06-29-kline-api-unification-design.md`）
- ZzshareFetcher 之外的 fetcher 的 minute K 现状
- 给 Zhitu/Zzshare 补 INDEX_* 声明（用户在任务 1 中已选"不补，让 DataFetchError 暴露"）

---

## 5. 实施 checklist

- [ ] TDD 红：`test_zzshare_fetcher.py` 加 `_fetch_raw_data("5")` 测试用例
- [ ] TDD 红：`test_manager.py`（或合适位置）加 INDEX 兜底删除后的新行为断言
- [ ] TDD 绿：实现 helper + 分发
- [ ] TDD 绿：删除 manager.py 兜底块
- [ ] 重构：抽 `_fetch_minute_kline` 共用
- [ ] 全量回归：`pytest` 默认套件（跳过 live_network）
- [ ] 文档同步：CLAUDE.md 中 capability / fetcher 表（必要时）

---

## 6. 回滚

- 任务 1：单文件单块，恢复原 18 行兜底逻辑即可
- 任务 2：单 fetcher 改动，回滚 `_fetch_raw_data` minute 分支 + 还原 `get_intraday_data` 内联 `api.stk_mins` 调用