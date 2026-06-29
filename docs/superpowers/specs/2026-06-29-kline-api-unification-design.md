# Price API 统一化设计 (Stock + Index)

> 日期：2026-06-29 (rev 2: 扩入 quote 统一 + capability flag 精简)
> 状态：设计稿（待评审）
> 目标：把 stock + index 的**价格数据**统一为两个端点家族（实时 quote / 时序 K 线）；boards 留到 phase-2 spec，本次不动。

---

## 0. 摘要

- **现状**：4 个 K 线端点（`/stocks/{code}/{history,intraday}` + `/indices/{code}/{history,intraday}`）+ 2 个 quote 端点（`/stocks/{code}/quote`、`/indices/{code}/quote`），覆盖 d/w/m + 1m/5m/15m/30m/60m + 实时快照。但 `/history` 路由层 regex 拒绝分钟频率、`/intraday` 不接受 `start_date/end_date`、quote 与 K 线之间参数命名不对齐 —— 多个真实 API gap。
- **目标**：合并为 `/quote` + `/kline` 两族端点（stock/index 各两个）；参数命名约定统一（例如所有 K 线 entry 共享同一套 `period/adjust/start_date/end_date/days` 解释）。`adjust` 仅在 `/kline` 接受、`/quote` 路由层直接 422；`/kline` 上 `adjust` 不按 frequency 限，由 per-fetcher `supports_kline(period, adjust, market)` 决定。
- **能力模型**：K 线 capability 从 4 flag（`HISTORICAL_DWM` · `HISTORICAL_MIN` · `INDEX_HISTORICAL` · `INDEX_INTRADAY`）精简为 2 flag（`STOCK_KLINE` · `INDEX_KLINE`）；quote capability 重命名为 `STOCK_REALTIME_QUOTE` / `INDEX_REALTIME_QUOTE`。新增 `BaseFetcher.supports_kline(period, adjust, market)` + `supports_quote(market)` 表达细粒度兼容性，manager 两阶段 filter。
- **风险**：合并端点是路径破坏性变更，需要迁移窗口与兼容 shim；建议先做 capability 细化（零破坏，零 API 变化），再做 API 合并。
- **Out of scope**：boards（已有 `/boards/{code}/history` 日线走 zzshare plate_kline；quote + 分钟 K 留到 phase-2 独立 spec），增量 indicator 服务改、Tencent level-2 字段、websocket 推送。

---

## 1. 背景

### 1.1 当前 API 表面

| 端点 | 频率 | 复权 | 日期范围 | 市场 | 内部入口 |
|---|---|---|---|---|---|
| `GET /stocks/{code}/history` | `daily\|weekly\|monthly` | qfq/hfq | `days` 或 `start_date/end_date` | csi/hk/us | `manager.get_kline_data(frequency=d/w/m)` |
| `GET /stocks/{code}/intraday` | `1\|5\|15\|30\|60` | qfq/hfq | **仅当日** | **csi only** | `manager.get_intraday_data` |
| `GET /indices/{code}/history` | `daily\|weekly\|monthly` | n/a | `days` 或 `start_date/end_date` | csi/hk/us | `manager.get_index_historical` |
| `GET /indices/{code}/intraday` | `1\|5\|15\|30\|60` | n/a | **仅当日** | csi/hk/us | `manager.get_index_intraday` |
| `GET /stocks/{code}/quote` | n/a（快照） | n/a | 当下 | csi/hk/us | `manager.get_realtime_quote` |
| `GET /indices/{code}/quote` | n/a（快照） | n/a | 当下 | csi/hk/us | `manager.get_index_realtime_quote` |

### 1.2 关键代码现状

**路由层 regex（`stocks.py:230` / `indices.py:149`）**：

```python
period: str = Query(
    default="daily",
    pattern="^(daily|weekly|monthly)$",
    description="K-line period",
)
```

→ 分钟频率在路由层就被 regex 拒绝。

**helper `_period_to_freq`（`helpers.py:42-54`）**：

```python
_PERIOD_MAP: dict[str, str] = {
    "daily": "d",
    "weekly": "w",
    "monthly": "m",
}
def _period_to_freq(period: str) -> str:
    return _PERIOD_MAP.get(period, "d")  # ← 分钟值会 fallback 成 "d"
```

→ 哪怕有人手动 curl 绕过 regex，helper 也会把分钟当成 daily。

**manager `get_kline_data`（`manager.py:279-335`）已经支持分钟**：

```python
if frequency in ("5", "15", "30", "60"):
    index_cap = DataCapability.INDEX_INTRADAY
    gen_cap = DataCapability.HISTORICAL_MIN
else:
    index_cap = DataCapability.INDEX_HISTORICAL
    gen_cap = DataCapability.HISTORICAL_DWM
```

→ manager 层完全支持分钟 K 的 capability routing，**瓶颈只在 API 层**。

### 1.3 已发现的真实 Gap

- **历史分钟 K 完全无法查询**：所有分钟级 fetcher 的上游 API 都支持区间查询（见 §3），但 server 端从未暴露。
- **`/stocks/{code}/intraday` 仅支持 csi**：Yfinance 支持 HK/US 分钟 K 但被 400 拒掉（`stocks.py:344-351`）。
- **`/stocks/{code}/intraday` 没有 `start_date/end_date`**：fetcher 实现（`AkshareFetcher.get_intraday_data`、`ZhituFetcher.get_intraday_data` 等）都硬编码 `today`，即便上层想传日期也接不住。
- **adjust 在分钟档静默 drop**：Zzshare 接受参数但忽略；Yfinance hfq → qfq；Zhitu 强制不复权；Akshare 1m 强制不复权 —— 4 家上游行为各异，server 没拦截 → 客户端拿到的语义不一致。
- **Akshare `volume` 单位是手（100 股）未归一化**：静默数据契约破裂（`/100` 才能与 Baostock/Tushare 一致），详见 §3.4。
- **`/quote` 与 `/kline` 参数命名不对齐**：`/quote` 无参数化（单一快照），`/kline` 有 `period/adjust/start_date/...` —— 客户端需要切换心智模型。

---

## 2. 设计目标

1. **统一端点家族**：stock/index 各 2 个端点（`/quote` + `/kline`）；`/quote` URL 不变（不破坏），`/kline` 把 `/history` + `/intraday` 合一。
2. **统一参数命名约定**：`/kline` 共享 `period / adjust / start_date / end_date / days` 解释，所有 frequency 都接受；`/quote` 不收 `period / adjust / days / start_date / end_date`（路由层 422）。
3. **统一调整语义**：adjust 在 `/kline` 所有 period 都允许（1m/5m/15m/30m/60m/d/w/m），能否成功由 per-fetcher `supports_kline()` 决定；不在路由层按 frequency 拒绝。
4. **细粒度能力路由**：capability flag（`STOCK_KLINE` / `INDEX_KLINE` / `STOCK_REALTIME_QUOTE` / `INDEX_REALTIME_QUOTE`）+ per-fetcher `supports_kline()` / `supports_quote()`，避免"白白打一次"。
5. **明确 reject 行为**：
   - (a) `/quote` 收到 `adjust / period / days / start_date / end_date` → 422 user error；
   - (b) `/kline` 收到合法 period + adjust 组合但**无 fetcher 可服务** → 422 `no_fetcher_available`。
6. **向后兼容**：旧 `/history` + `/intraday` 端点保留 6 个月过渡期，最终 410 Gone；`/quote` 无需迁移。

**非目标**：
- 不做 schema 兼容层（统一 `KLineData` 用同一字段；`StockQuote` 维持现状，client 一次性迁移）。
- 不做分钟级跨日聚合（Tushare/Baostock 不支持由上层做）。
- **boards 不在本次 spec scope**：已有 `/boards/{code}/history` 日线（zzshare plate_kline）；quote + 分钟 K 留到 phase-2 独立 spec。
- 不引入 WebSocket / SSE 推送 —— 实时刷新仍为 polling 模型（受 cache TTL 控制）。

---

## 3. Fetcher 能力矩阵（基于源码 + docs/ 实测）

### 3.1 股票频率 × 复权 × 上游 API

| Fetcher | d | w | m | 1m | 5m | 15m | 30m | 60m | 复权（d） | 复权（5/15/30/60m） | 1m + 复权 | 上游 API |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Tushare (P0) | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | qfq/hfq | n/a | n/a | `pro_bar` / `daily`/`weekly`/`monthly` |
| Baostock (P1) | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | qfq/hfq | qfq/hfq | n/a | `query_history_k_data_plus` |
| Akshare (P2) | ✅ | ✅ | ✅ | ✅¹ | ✅ | ✅ | ✅ | ✅ | qfq/hfq | qfq/hfq² | ❌（硬约束） | `stock_zh_a_hist` / `stock_zh_a_hist_min_em` |
| Yfinance (P3) | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | qfq only³ | qfq only | n/a | `yf.download(interval=...)` |
| Zhitu (P4) | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ | n/a | ❌（强制不复权） | n/a | `/hs/history/{code.mkt}/{period}/{adj}` |
| **Zzshare (P5)** | ✅ | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | qfq/hfq | ❌（上游不接受）⁴ | ❌ | `daily(adj=qfq/hfq)` / `stk_mins(freq=1min/...)` |
| Myquant (P9) | ✅ | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ | qfq/hfq | qfq/hfq | n/a | `history(frequency=1d/300s/..., adjust=0/1/2)` |
| Tencent / EM / Ths / Baidu / Cninfo | n/a | | | | | | | | | | | | |

¹ Akshare 1m 仅近 5 个交易日，强制不复权（`docs/akshare/stock/stock_zh_a_hist_min_em.md:17-18`）。
² Akshare 5/15/30/60m 全部支持 qfq/hfq（实测 `docs/akshare/stock/stock_zh_a_hist_min_em.md:18`）。但 1m 强制不复权（Akshare 上游硬约束，全 fetcher 唯一 1m 源不能服务 1m+adjust）。
³ Yfinance 的 `auto_adjust=True` 等同 qfq；hfq 没有独立语义（`yfinance_fetcher.py:51-55` 静默降级）→ 视为不支持。
⁴ Zzshare `stk_mins` 上游 API 完全不接受 `adjust` 参数 → 视为不支持。

### 3.2 指数频率 × 复权

| Fetcher | d | w | m | 1m | 5m | 15m | 30m | 60m | 复权 | 备注 |
|---|---|---|---|---|---|---|---|---|---|---|
| Tushare | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | n/a⁵ | `index_daily/weekly/monthly` |
| Baostock | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | n/a⁵ | `get_index_historical` 仅 d/w/m |
| Akshare (CSI) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | n/a⁵ | `index_zh_a_hist` + `index_zh_a_hist_min_em` |
| Akshare (HK/US) | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | n/a⁵ | `index_us_stock_sina` 仅日线 |
| Yfinance | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | n/a⁵ | Yahoo 分钟 K 全局 60 天窗口限制 |
| Zhitu / Zzshare | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | n/a | 无指数 K 线能力 |
| Myquant (CSI) | ✅ | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ | n/a⁵ | `history(symbol=SHSE/SZSE.xxx)` |
| Tencent (指数) | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | n/a | 无上游 API |

⁵ 指数无除权除息，复权 (qfq/hfq) 无定义；`/indices/{code}/kline?adjust=qfq` 路由层 422 reject（与分钟 reject 同等待遇）。

### 3.3 Capability 声明（`supported_data_types`，rev 2 精简后）

| Fetcher | STOCK_KLINE | INDEX_KLINE | STOCK_REALTIME_QUOTE | INDEX_REALTIME_QUOTE |
|---|---|---|---|---|
| Tushare | ✅ | ✅ | ✅ | ❌ |
| Baostock | ✅ | ✅ | ✅ | ❌ |
| Akshare | ✅ | ✅ | ✅ | ✅ |
| Yfinance | ✅ | ✅ | ✅ | ✅ |
| Zhitu | ✅ | ❌ | ✅ | ❌ |
| Zzshare | ✅ | ❌ | ✅ | ❌ |
| Tencent | ❌ | ❌ | ✅ | ❌ |
| Myquant | ✅ | ✅ | ✅ | ❌ |
| EastMoney | ❌ | ❌ | ❌ | ❌ |
| Ths | ❌ | ❌ | ❌ | ❌ |
| Baidu | ❌ | ❌ | ❌ | ❌ |
| Cninfo | ❌ | ❌ | ❌ | ❌ |

**对照旧版本（删除行）**：`HISTORICAL_DWM` + `HISTORICAL_MIN` → `STOCK_KLINE`；`INDEX_HISTORICAL` + `INDEX_INTRADAY` → `INDEX_KLINE`；`REALTIME_QUOTE` → `STOCK_REALTIME_QUOTE`（重命名，去歧义）；`INDEX_QUOTE` → `INDEX_REALTIME_QUOTE`（重命名）。**4 flag → 2** for K-line；2 flag 重命名 for quote。

> **迁移期**：fetcher 注册时声明旧 flag 名仍合法 —— `BaseFetcher.__init__` 后置处理把 `HISTORICAL_DWM | HISTORICAL_MIN` 升为 `STOCK_KLINE`，`INDEX_HISTORICAL | INDEX_INTRADAY` 升为 `INDEX_KLINE`，`REALTIME_QUOTE` 改名为 `STOCK_REALTIME_QUOTE`，`INDEX_QUOTE` 改名为 `INDEX_REALTIME_QUOTE`；最终 `supported_data_types` 只含新 flag。manifest 注册只显示新名。6 个月后删除升迁逻辑。

### 3.4 单位不一致（隐式契约破裂）

| Fetcher | volume 单位 | amount 单位 | 归一化 |
|---|---|---|---|
| Baostock | 股 | 元 | 无需 |
| Tushare | 手×100 → 股（`tushare_fetcher.py:174-181`） | 千元×1000 → 元 | 已归一 |
| Zzshare | 股 | 元 | 无需 |
| Myquant | 股 | 元 | 无需 |
| **Akshare** | **手（100 股）** ⚠️ | 元 | **未归一** |
| Yfinance | 股 | n/a（volume × close 计算） | n/a |

**这是当前静默数据契约破裂**：同一只股票从不同 fetcher 拿到的 `volume` 可能差 100 倍。**P0 必须修**（§7 提升至最高优先级），可选方案：fetchers 层 `/100` 归一 + 响应字段 `volume_unit: "lot" | "share"` 元数据，或向 Pydantic 字段 `volume_lot` / `volume_share` 拆分两个字段。

---

## 4. 设计方案

### 4.1 Capability 模型（flag 精简，4 → 2）

**新 flag 集合**：

```python
class DataCapability(Flag):
    STOCK_KLINE = auto()              # 股票 d/w/m/1m/5m/15m/30m/60m
    INDEX_KLINE = auto()              # 指数 d/w/m/1m/5m/15m/30m/60m
    STOCK_REALTIME_QUOTE = auto()     # 股票实时快照
    INDEX_REALTIME_QUOTE = auto()     # 指数实时快照
    # ... 其余不变: STOCK_LIST, TRADE_CALENDAR, STOCK_BOARD, STOCK_INFO,
    # STOCK_ZT_POOL, DRAGON_TIGER, MARGIN_TRADING, BLOCK_TRADE, HOLDER_NUM,
    # DIVIDEND, FUND_FLOW, HOT_TOPICS, NORTH_FLOW, RESEARCH_REPORT,
    # ANNOUNCEMENT, NEWS_FLASH, NEWS_SEARCH
```

**为什么从 4 flag 收敛为 2？**

- 真正会变的不是"是否支持 K 线"，而是"调到上游的哪个 SDK 入口能拿到这一组 (period, adjust, market)"——这是 fetcher 内部细节，不应泄漏到 capability 层。
- `supports_kline(period, adjust, market)` 已经能干 (period × adjust × market) 颗粒度的判定，capability bit 只需承担"这个 fetcher 进入 K 线路由"这件事。
- 4 flag 拆到 (asset × frequency-class) 已经是没必要的二维——`period` 这维交给 `supports_kline` 即可。

### 4.2 新增 `BaseFetcher.supports_kline(period, adjust, market)`

加到 `data_provider/base.py`：

```python
def supports_kline(
    self,
    period: str,    # "d" / "w" / "m" / "1" / "5" / "15" / "30" / "60"
    adjust: str,     # "" / "qfq" / "hfq"
    market: str,     # "csi" / "hk" / "us"
) -> bool:
    """Return True iff this fetcher can serve (period, adjust, market).

    Default: infer from capability flag. Override in subclasses when the
    fetcher's actual upstream coverage is narrower (e.g. Yfinance hfq
    silently downgrades to qfq, treated as unsupported).
    """
    if market not in self.supported_markets:
        return False
    if period in ("d", "w", "m", "1", "5", "15", "30", "60"):
        return (DataCapability.STOCK_KLINE in self.supported_data_types
                or DataCapability.INDEX_KLINE in self.supported_data_types)
    return False
```

### 4.2.1 (NEW) `BaseFetcher.supports_quote(market)`

```python
def supports_quote(self, market: str) -> bool:
    """Return True iff this fetcher can serve realtime quote for the market.

    Quote has no (period, adjust) dimension — just market bit.
    Default checks market + relevant capability. Override rare.
    """
    if market not in self.supported_markets:
        return False
    return (DataCapability.STOCK_REALTIME_QUOTE in self.supported_data_types
            or DataCapability.INDEX_REALTIME_QUOTE in self.supported_data_types)
```

`supports_quote` 比 `supports_kline` 简单很多：没有 (period, adjust) 维度，无 per-fetcher override 需求（除了一处：TencentFetcher 仅 csi/hk，需在 `__init__` 中确保 `supported_markets` 已正确声明）。

### 4.3 各 fetcher 覆盖

只列与默认不同的（其余走默认推断）：

```python
# tushare_fetcher.py
class TushareFetcher(BaseFetcher):
    def supports_kline(self, period, adjust, market):
        if market != "csi" or period not in ("d", "w", "m"):
            return False
        # Tushare weekly/monthly 也支持 qfq/hfq（pro_bar adj 参数）
        return True

# baostock_fetcher.py
class BaostockFetcher(BaseFetcher):
    def supports_kline(self, period, adjust, market):
        # 全 frequency + 全 adjust 都支持（query_history_k_data_plus）
        if period in ("d", "w", "m"):
            return True
        if period in ("5", "15", "30", "60"):
            return market == "csi"  # 指数无分钟
        return False  # 无 1m

# akshare/fetcher.py
class AkshareFetcher(BaseFetcher):
    def supports_kline(self, period, adjust, market):
        # 1m 强制不复权（上游硬约束，全 fetcher 唯一 1m 源）
        if period == "1" and adjust in ("qfq", "hfq"):
            return False
        return super().supports_kline(period, adjust, market)

# yfinance_fetcher.py
class YfinanceFetcher(BaseFetcher):
    def supports_kline(self, period, adjust, market):
        # hfq 静默降级为 qfq（语义丢失）→ 视为不支持
        if adjust == "hfq":
            return False
        return super().supports_kline(period, adjust, market)

# zhitu_fetcher.py
class ZhituFetcher(BaseFetcher):
    def supports_kline(self, period, adjust, market):
        # Zhitu 仅 5/15/30/60，且分钟强制不复权
        return period in ("5", "15", "30", "60") and adjust in ("", None)

# zzshare_fetcher.py
class ZzshareFetcher(BaseFetcher):
    def supports_kline(self, period, adjust, market):
        if period == "d":
            return True
        if period in ("1", "5", "15", "30", "60"):
            return adjust in ("", None)  # 上游不接受 adj
        return False  # 无 weekly/monthly

# myquant_fetcher.py
class MyquantFetcher(BaseFetcher):
    def supports_kline(self, period, adjust, market):
        # myquant d + 5/15/30/60 全 adjust
        return period in ("d", "5", "15", "30", "60")
```

### 4.4 Manager 路由（两阶段 filter）

```python
def get_kline_data(
    self,
    stock_code: str,
    start_date: str | None = None,
    end_date: str | None = None,
    days: int = 30,
    frequency: str = "d",
    adjust: str | None = None,
) -> tuple[pd.DataFrame, str]:
    code = normalize_stock_code(stock_code)
    is_index = bool(index_market_tag(code))
    market = index_market_tag(code) or market_tag(code)
    
    # Step 1: 选 primary capability (rev 2: 单一 KLINE flag, 走 fallback 不区分 period)
    primary_cap = (
        DataCapability.INDEX_KLINE if is_index
        else DataCapability.STOCK_KLINE
    )
    
    # Step 2: 失败兜底 capability
    # 股票不走兜底 (INDEX_KLINE 才是股票入口, 反向不对);
    # 指数无 INDEX_KLINE 时退到 STOCK_KLINE (例如港股指数的临时承接).
    fallback_cap: DataCapability | None = None
    if is_index:
        fallback_cap = DataCapability.STOCK_KLINE
    
    # Step 3: 两阶段 filter
    candidates = self._filter_by_capability(market, primary_cap)
    if not candidates and fallback_cap:
        candidates = self._filter_by_capability(market, fallback_cap)
    
    # Step 3.5: 细粒度 filter (新增, failover 之前剔除必败者)
    candidates = [
        f for f in candidates
        if f.supports_kline(frequency, adjust or "", market)
    ]
    
    if not candidates:
        # 诚实错误: 客户端请求合法但当前 fetcher 集合无人能服务
        raise DataFetchError(
            f"No fetcher supports period={frequency} adjust={adjust!r} "
            f"market={market}"
        )
    
    # Step 4: 按 priority 排序后 failover
    candidates.sort(key=lambda f: f.priority)
    
    errors = []
    for fetcher in candidates:
        try:
            df = fetcher.get_kline_data(
                stock_code, start_date, end_date, days, frequency, adjust,
            )
            if _is_meaningful(df):
                return df, fetcher.name
        except DataFetchError as e:
            errors.append(f"[{fetcher.name}] {e}")
            continue
    
    raise DataFetchError(f"All fetchers failed: {errors}")


def get_realtime_quote(self, stock_code: str) -> UnifiedRealtimeQuote | None:
    code = normalize_stock_code(stock_code)
    market = market_tag(code)
    
    # 两阶段 filter (rev 2)
    is_index = bool(index_market_tag(code))
    primary_cap = (
        DataCapability.INDEX_REALTIME_QUOTE if is_index
        else DataCapability.STOCK_REALTIME_QUOTE
    )
    candidates = self._filter_by_capability(market, primary_cap)
    candidates = [f for f in candidates if f.supports_quote(market)]
    
    if not candidates:
        raise DataFetchError(f"No fetcher supports quote market={market}")
    
    candidates.sort(key=lambda f: f.priority)
    # ... 走 _with_failover 既有逻辑
```

`get_index_historical` / `get_intraday_data` 走相同骨架（去掉 is_index 推断，固定 `INDEX_KLINE` 为 primary_cap）。

### 4.5 Failover 链路示例

| 请求 | 实际尝试顺序（按 priority） |
|---|---|
| A 股 daily qfq | Tushare → Baostock → Akshare → Yfinance → Zzshare → Myquant |
| A 股 weekly qfq | Tushare → Baostock → Akshare → Yfinance（Zzshare/Myquant 周线被 supports_kline 剔除） |
| A 股 1m 不复权 | Akshare → Zzshare |
| A 股 **1m qfq** | Akshare (1m+adjust 拒) ∪ Zzshare (1m+adjust 拒) → **全部被 supports_kline 滤掉 → 422 no_fetcher_available** |
| A 股 5m qfq | supports_kline 筛得候选集 = {Baostock, Akshare, Yfinance, Myquant}（Zhitu/Zzshare 拒 adjust）；按优先级：Baostock → Akshare → Yfinance → Myquant |
| A 股 5m hfq | supports_kline 筛得候选集 = {Baostock, Akshare, Myquant}（Yfinance hfq 拒；Zhitu/Zzshare 拒 adjust）；按优先级：Baostock → Akshare → Myquant |
| CSI 指数 5m | Akshare → Myquant |
| CSI 指数 5m adjust=* | **422 reject**（指数无复权语义，路由层早期 reject） |
| US 股票 5m qfq | Yfinance |
| HK 指数 daily | Yfinance → Akshare |
| US stock quote | Yfinance → (Tushare 不入 us market) |

> **重要**：1m + adjust 必然 422（no_fetcher_available）。这是诚实的错误 —— 客户端传了合法组合，但当前 fetcher 集合没人能服务。**不是** user input error，因此不用 4xx `bad_request`，用 422 `no_fetcher_available` 并附详细原因（哪些 fetcher 被 supports_kline 滤掉，为什么）。

---

## 5. API 层

### 5.1 `/stocks/{code}/kline`

```python
@router.get("/stocks/{code}/kline", response_model=StockHistoryResponse)
@endpoint_meta(
    summary="K 线（统一入口：d/w/m + 1m/5m/15m/30m/60m）",
    markets=["csi", "hk", "us"],
    capabilities=["STOCK_KLINE"],
)
@map_errors
@cache_endpoint(
    cache_fn=lambda *a, freq, **kw: get_kline_cache(freq),
    key_builder=lambda code, period, days, start_date, end_date, adjust, indicators: (
        make_kline_cache_key(
            code, _period_to_freq(period), days, start_date, end_date,
            adjust or None, _parse_indicators_param(indicators),
        )
    ),
    hit_label="kline",
)
def get_kline(
    code: str = Path(max_length=20),
    period: str = Query(
        default="daily",
        pattern="^(daily|weekly|monthly|1m|5m|15m|30m|60m)$",
    ),
    days: int = Query(default=30, ge=1, le=365),
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    adjust: str = Query(default="", pattern="^(qfq|hfq)?$"),
    indicators: str | None = Query(default=None),
) -> StockHistoryResponse:
    _reject_index_code(code, endpoint_kind="kline")
    freq = _period_to_freq(period)
    
    # 注: 不再有 "分钟 + adjust → 400" 路由层 reject.
    # 所有合法性由 supports_kline() 在 manager 层判定;
    # 无人能服务时由 manager 抛 DataFetchError 并被 map_errors 映射为
    # 422 no_fetcher_available (附详细原因).
    
    requested_indicators = _parse_indicators_param(indicators)
    actual_days = days
    if requested_indicators:
        extra = compute_lookback(requested_indicators)
        if extra > 0:
            actual_days = max(days, extra)
    
    manager = get_manager()
    df, source = manager.get_kline_data(
        code, start_date, end_date, actual_days, freq, adjust or None,
    )
    df = _apply_indicators(df, requested_indicators, days, actual_days)
    name = stock_cache.get_stock_name(code, manager=manager)
    
    records = df.to_dict("records")
    return StockHistoryResponse(
        code=code, name=name, period=period,
        data=[_build_kline_data(r, _format_date) for r in records],
        source=source,
    )
```

### 5.2 `/indices/{code}/kline`

完全对称：
- `capability`: `INDEX_KLINE`
- `_reject_non_index_code(...)`
- **路由层 reject `adjust=qfq/hfq`**（指数无除权除息，复权无定义 —— user input error，422）
- 分钟 + 复权由 `supports_kline()` 处理（与 stock 行为一致）

### 5.3 响应 schema 统一

`KLineData.date` 字段对日 K 输出 `YYYY-MM-DD`，对分钟 K 输出 `YYYY-MM-DD HH:MM:SS`：

```python
# routes/helpers.py
def _format_date(val) -> str:
    """Format datetime to YYYY-MM-DD (daily) or YYYY-MM-DD HH:MM:SS (minute)."""
    if val is None:
        return ""
    if hasattr(val, "strftime"):
        if hasattr(val, "hour") and (val.hour or val.minute or val.second):
            return val.strftime("%Y-%m-%d %H:%M:%S")
        return val.strftime("%Y-%m-%d")
    return str(val)
```

客户端用 `len(date) > 10` 区分日/分钟。

### 5.4 Cache key 合并

```python
# api/cache.py
def make_kline_cache_key(
    code: str,
    frequency: str,          # "d"/"w"/"m"/"1"/"5"/"15"/"30"/"60"
    days: int | None,
    start_date: str | None,
    end_date: str | None,
    adjust: str | None,
    indicators: list[str],
) -> str:
    return (
        f"kline:{code}:{frequency}:{days or ''}:{start_date or ''}:"
        f"{end_date or ''}:{adjust or ''}:{','.join(indicators)}"
    )

def get_kline_cache(frequency: str) -> TTLCache:
    """分钟档用短 TTL（30s），日档用长 TTL（3600s，盘后可延长）。"""
    if frequency in ("1", "5", "15", "30", "60"):
        return get_stock_intraday_cache()
    return get_history_cache(frequency)
```

TTL 策略拆双档（配置项在 `.env.example`）：

```ini
# .env.example
CACHE_TTL_KLINE_DAILY=3600      # 日/周/月 K 线（盘后稳定）
CACHE_TTL_KLINE_MINUTE=30       # 分钟 K 线
```

### 5.5 /quote 端点契约（不变 + 显式化）

**`/stocks/{code}/quote`** 与 **`/indices/{code}/quote`** URL 形态不变（无破坏性变更）：

| 参数 | 接受 | 不接受 |
|---|---|---|
| `code` (Path) | ✅ | — |
| `period` | — | ❌ (422) |
| `adjust` | — | ❌ (422) |
| `days` / `start_date` / `end_date` | — | ❌ (422) |
| `indicators` | — | ❌ (422) |

具体行为由 FastAPI Query 验证：未声明这些 Query 参数的客户端如在请求里附加 `?period=...&adjust=...`，由 `map_errors` + 显式 `if "..." in request.query_params: raise 422` 检测。

**quote 内置字段保持现状**（`StockQuote` / `IndexQuote`）：current_price · open · high · low · prev_close · volume · amount · pe_ttm · pb · mcap_yi · float_mcap_yi · turnover_pct · amplitude_pct · limit_up · limit_down · vol_ratio（TencentFetcher 增强字段仍由其 `supports_quote` 返回 None 占位时不影响 failover）。

---

## 6. 迁移路径（向后兼容）

### 6.1 旧端点 redirect 到新端点

```python
# api/routes/stocks.py
@router.get("/stocks/{code}/history", deprecated=True)
@endpoint_meta(summary="[已弃用] 历史 K 线；请改用 /stocks/{code}/kline",
               capabilities=["STOCK_KLINE"], ...)
def get_history_deprecated(code, period="daily", days=30, ...):
    # 直接转发到新端点（不复制逻辑）
    return get_kline(
        code=code, period=period, days=days, start_date=start_date,
        end_date=end_date, adjust=adjust, indicators=indicators,
    )
```

`/intraday` 类似，但 `period` 兼容 `1`→`1m` 映射：

```python
def _legacy_period_to_modern(period: str) -> str:
    return {"1": "1m", "5": "5m", "15": "15m", "30": "30m", "60": "60m"}.get(period, period)
```

`/quote` 端点 URL 不变，无需迁移。

### 6.2 时间表

| 阶段 | 改动 |
|---|---|
| **T+0** | 新增 `/stocks/{code}/kline` + `/indices/{code}/kline`；旧 `/history` + `/intraday` 保留，标 `deprecated=True` |
| **T+30d** | 旧端点响应头加 `Deprecation: true` + `Sunset: <T+180d>` |
| **T+90d** | 旧端点 body 加 `{"_deprecated": "Use /stocks/{code}/kline"}` 字段 |
| **T+180d** | 旧端点返回 410 Gone |
| **T+365d** | 旧端点代码与测试删除 |

旧 capability flag 名 (`HISTORICAL_DWM` 等) 的兼容 shim **同时长 6 个月**，T+180d 与 endpoint 一同下架。

---

## 7. 一次性改进（建议同步做）

按收益/风险排序：

| 优先级 | 改动 | 工作量 | 风险 |
|---|---|---|---|
| 🔴 P0 | §4.2 `supports_kline()` + §4.2.1 `supports_quote()` + §4.4 manager 两阶段 filter（不改 API） | 0.5d | 零（内部） |
| 🔴 P0 | §3.4 修 Akshare volume 单位归一化（`/100` 或标 units） | 0.5d | 客户端需适配 |
| 🔴 P0 | §4.1 capability flag 4 → 2 精简（不影响 6 个月兼容期内 client） | 0.5d | 内部 |
| 🟠 P1 | §5 合并 `/kline` 端点，旧端点 redirect | 2–3d | 路径变更 |
| 🟠 P1 | §5.4 cache key 合并 + TTL 拆双档 | 0.5d | 缓存重建一次 |
| 🟠 P1 | §5.5 `/quote` 显式 reject `period/adjust/days/start_date/end_date`（明确文档化） | 0.5d | 内部 |
| 🟡 P2 | Zzshare `daily` 1000 行分页回溯 | 1d | 数据深度解锁 |
| 🟡 P2 | Zhitu 加 d/w/m 实现（上游 `/hs/latest` 支持） | 1–2d | token-gated |
| 🟢 P3 | K 线 circuit breaker | 2–3d | 高可用 |
| 🟢 P3 | 动态 failover（运行时自适应） | 3+d | 长期弹性 |

> **取消原 §5.1 "reject `adjust=qfq/hfq` + `period=分钟`" 项目** —— 该行为由 §4.4 manager 层 `supports_kline()` 取代；不再有路由层预 reject。

---

## 8. 测试策略

新建 `tests/test_kline_unified.py`，覆盖矩阵：

```python
@pytest.mark.parametrize("period,freq,adjust,expected_min_fetchers", [
    ("daily",  "d",  "",    6),  # Tushare/Baostock/Akshare/Yfinance/Zzshare/Myquant
    ("daily",  "d",  "qfq", 6),
    ("daily",  "d",  "hfq", 5),  # Yfinance hfq 被视作不支持
    ("weekly", "w",  "",    4),  # Tushare/Baostock/Akshare/Yfinance
    ("weekly", "w",  "qfq", 4),
    ("monthly","m",  "",    4),
    ("1m",     "1",  "",    2),  # Akshare/Zzshare
    ("1m",     "1",  "qfq", 0),  # 无 fetcher → 422 no_fetcher_available
    ("5m",     "5",  "",    5),  # Baostock/Akshare/Zhitu/Yfinance/Zzshare/Myquant
    ("5m",     "5",  "qfq", 4),  # Zhitu/Zzshare 拒 adjust
    ("5m",     "5",  "hfq", 3),  # 仅 Baostock/Akshare/Myquant
    ("15m",    "15", "",    5),
    ("30m",    "30", "",    5),
    ("60m",    "60", "",    5),
])
def test_kline_unified_routes_to_correct_fetchers(period, freq, adjust, expected_min_fetchers):
    ...

def test_kline_one_minute_with_adjust_returns_no_fetcher_available():
    """/stocks/600519/kline?period=1m&adjust=qfq → 422 no_fetcher_available"""
    response = client.get("/stocks/600519/kline?period=1m&adjust=qfq")
    assert response.status_code == 422
    body = response.json()
    assert body["detail"]["error"] == "no_fetcher_available"
    assert "period=1" in body["detail"]["message"]

def test_kline_historical_minute():
    """多日分钟 K 历史范围"""
    response = client.get("/stocks/600519/kline?period=5m&start_date=2026-06-20&end_date=2026-06-29")
    assert response.status_code == 200
    body = response.json()
    assert len(body["data"]) > 48 * 5  # 至少 5 天

def test_supports_kline_method():
    """逐 fetcher 验证 supports_kline"""
    for fetcher in manager.fetchers:
        # d 全部应该支持 (有 STOCK_KLINE 或 INDEX_KLINE 能力的)
        cap_kline = (
            DataCapability.STOCK_KLINE in fetcher.supported_data_types
            or DataCapability.INDEX_KLINE in fetcher.supported_data_types
        )
        assert fetcher.supports_kline("d", "", "csi") == cap_kline

def test_supports_quote_method():
    """quote 仅有 market 维度，逐 fetcher 验证"""
    for fetcher in manager.fetchers:
        for market in ("csi", "hk", "us"):
            cap_quote = (
                DataCapability.STOCK_REALTIME_QUOTE in fetcher.supported_data_types
                or DataCapability.INDEX_REALTIME_QUOTE in fetcher.supported_data_types
            )
            assert fetcher.supports_quote(market) == (
                cap_quote and market in fetcher.supported_markets
            )

def test_quote_endpoint_rejects_period_parameter():
    """/stocks/600519/quote?period=5m → 422"""
    response = client.get("/stocks/600519/quote?period=5m")
    assert response.status_code == 422

def test_quote_endpoint_rejects_adjust_parameter():
    """/stocks/600519/quote?adjust=qfq → 422"""
    response = client.get("/stocks/600519/quote?adjust=qfq")
    assert response.status_code == 422
```

旧 endpoint 测试保持不变（redirect 行为）；flag collapse 测试在 `tests/test_capability_method_map.py` 中加：旧 flag 6 个月内仍被识别为新 flag。

---

## 9. 风险与权衡

### 9.1 为什么 boards 不在本次 spec scope？

- boards.py 当前只有 `/boards/{code}/history` 日线（zzshare plate_kline，2026-06-25 才接通）。
- board **quote** 与 **分钟 K** 在上游完全没有现成方案（zzshare plate_kline 只日线；eastmoney/zhitu 板块数据无 quote/minute；tencent 板块行情只有日级）。
- 在这次统一里加上 boards 会让 scope 翻倍（要从 0 设计 board quote 的 fetcher 路由），但**不是用户的核心痛点**。
- phase-2 独立 spec 处理 boards，把 board 的 capability 扩展 / fetcher 选择 / 上游能力调研 都隔离出来。

### 9.2 为什么不在合并阶段做"形式上的统一"？

- 日 K 与分钟 K 在 schema（`date` vs `time`）、复权语义（多 fetcher 静默 drop）、日期范围（多日 vs 当日）、市场支持（csi/hk/us vs csi only）上**没有任何一项完全一致**。
- 把这些差异塞进"参数判断 + 文档免责"会增加 bug 表面积与客户端认知负担。
- 现有 K 线端点已在生产环境被客户端使用，破坏性变更需要迁移窗口与 shim。

### 9.3 为什么 `adjust` 在所有 period 都允许（含 1m）？

- **不要 400 reject**：今天的静默行为是 Zzshare 接受参数但忽略、Yfinance hfq → qfq、Zhitu 强制不复权 —— 失败模式是 silent data corruption。
- **`supports_kline()` 表驱动**：1m+qfq 当前真实无 fetcher 支持 → manager 抛 `DataFetchError("no fetcher supports...")` → API 层映射为 **422 `no_fetcher_available`** 附详细原因。
- 这是诚实的 "请求合法但当前上游集合无人能服务"，而不是 "你的请求参数不对"。
- **未来**：若有 fetcher 增加 1m + adjust 支持（例如 akshare 升级），客户端无需改代码即可受益 —— supports_kline 自动 cover。

### 9.4 为什么 collapse 4 K-line flag 为 2？

- 旧 4 flag 是为了 manager `_filter_by_capability()` 在不知道 `frequency` 之前根据 period 选 primary_cap（`HISTORICAL_MIN` vs `HISTORICAL_DWM` 等）。
- 但是新模型：`supports_kline(period, adjust, market)` 在 manager 已知 `frequency` 后做 fine-grain filter —— period 这维已经下沉到 supports 层。
- capability bit 只剩 (asset × entry-class)：K 线/quote 共 4 个 bit 即可。4 → 2 收一半。
- 收益：capability 注册表更可读；新增 fetcher 时只需声明 "我能做 K 线"，具体哪些 period 走 supports 表。

### 9.5 为什么 `/quote` 不接受任何参数化（`period/adjust/days/...`）？

- quote 是**点位快照**，没有 frequency 维度、adjust 没有语义、日期范围不适用。
- 接受这些参数会让客户端误以为可以"quote + qfq"这种组合有意义（实际是 user error）。
- 路由层显式 422 比 silently-ignore 要清晰 —— 与"分钟 + adjust 拒绝"在 manager 层的处理不同，quote 是 user input error（参数无意义），分钟 + adjust 是 no-fetcher-available（参数合理但上游不支持）。

### 9.6 性能影响

- `supports_kline()` 是内存方法（一个 `set` 查找 + 几个 `in` 判断），每次 failover 前多花 ~1µs，可忽略。
- 省掉的是无效 HTTP 调用：原本 weekly 查询会白白打 Zzshare → Zhitu（各 ~1s），现在直接跳过。
- 对高频分钟 K 客户端，省掉的多余 fetcher 调用更可观。

---

## 10. 参考

- `docs/baostock/stockKData.md` — Baostock `query_history_k_data_plus` 全频率全复权
- `docs/baostock/indexData.md` — 指数无分钟 K
- `docs/zhitu/06-market-data.md` — Zhitu `/hs/history` 与 `/hs/latest` 支持 d/w/m/y + 5/15/30/60m
- `docs/zzshare/01-kline.md` — Zzshare daily 1000 行上限、stk_mins 1min 支持、`stk_mins` 不接受 adjust
- `docs/akshare/stock/stock_zh_a_hist.md` — Akshare 成交量单位是手
- `docs/akshare/stock/stock_zh_a_hist_min_em.md` — Akshare 1m 仅近 5 天且强制不复权
- `docs/myquant/04-common-data-free.md` — myquant 通用数据函数
- 源码：`stock_data/data_provider/manager.py`、`stock_data/api/routes/{stocks,indices,helpers}.py`、`stock_data/api/cache.py`

---

## 附录 A. 与现存 2026-06-29 设计的差异

| 项目 | rev 1 (原 spec) | rev 2 (本次) | 理由 |
|---|---|---|---|
| Scope | 仅 K 线 4 端点合并 | stock/index 的 quote + kline 4 端点统一；boards 留 phase-2 | 用户要求 quote 也进入统一模型 |
| K-line flag 数 | 4 (HISTORICAL_DWM/HISTORICAL_MIN/INDEX_HISTORICAL/INDEX_INTRADAY) | 2 (STOCK_KLINE/INDEX_KLINE) | period 维度下沉到 supports_kline |
| Quote flag 命名 | REALTIME_QUOTE / INDEX_QUOTE | STOCK_REALTIME_QUOTE / INDEX_REALTIME_QUOTE | 资产类显式化 |
| `/kline` reject `period=分钟 + adjust=qfq/hfq` | 路由层 400 | 路由层放行；manager 层 supports_kline 滤掉 → 422 no_fetcher_available | 5/15/30/60m + adjust 是真实上游能力，1m 才限 |
| `/kline?period=1m&adjust=qfq` 行为 | 400 user error | 422 no_fetcher_available（诚实错误） | 请求合法但上游不支持，区分 user error |
| `/quote` 参数契约 | 文档不显式 | 显式 reject `period/adjust/days/start_date/end_date` → 422 | quote 是点位快照，这些参数无意义 |
| Akshare volume 归一 | P2 优先级 | **P0 提升** | silent data corruption（差 100x）必须先修 |
| supports_quote 新方法 | 未引入 | 新增 `BaseFetcher.supports_quote(market)` | quote 也有 market 路由 + Tencent 一致性问题 |
