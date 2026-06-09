# 架构审查报告 — 2026-06-09

> 审查分支: `fix/ruff-cleanup`
> 审查范围: 全项目（API 层、DataProvider 层、Fetchers、Persistence、Indicators、Tests）
> 总文件数: ~70 个 Python 文件, ~14,873 行代码

---

## 问题总览

| # | 严重度 | 类别 | 问题 |
|---|--------|------|------|
| 1 | 🔴 高优 | 代码重复 | `get_manager()` fetcher 初始化逻辑在 routes.py 和 stock_list.py 中重复 |
| 2 | 🔴 高优 | 不一致 | `_with_failover` 未被 manager 中 6 个方法使用 |
| 3 | 🔴 高优 | 架构 | TTLCache + SQLite Persistence + CircuitBreaker 三层缓存边界不清 |
| 4 | 🟡 中优 | 单一职责 | AkshareFetcher 过于庞大 (1106 行) |
| 5 | 🟡 中优 | 代码重复 | fetcher 各自的 `_convert_code` / `_normalize_*` 缺少统一抽象 |
| 6 | 🟡 中优 | 可维护性 | EastMoneyFetcher API 端点字符串硬编码分散 |
| 7 | 🟡 中优 | 健壮性 | `_build_kline_data` 未使用 `safe_float`/`safe_int` |
| 8 | 🟡 中优 | 接口设计 | fetcher 方法签名不一致（`period` vs `frequency`） |
| 9 | 🟢 低优 | 废弃代码 | `RealtimeSource.STOOQ` 枚举值未移除 |
| 10 | 🟢 低优 | 模块边界 | `base.py` 的 `__all__` 包含非本模块符号 |
| 11 | 🟢 低优 | 代码重复 | `_is_first_call_of_day` 在 board.py 和 stock_list.py 中重复 |
| 12 | 🟢 低优 | 遗留设计 | 无 fetcher health/status 统一接口 |
| 13 | 🟢 低优 | 测试 | 5 个核心 fetcher 缺少单元测试 |
| 14 | 🟢 低优 | 配置 | pyproject.toml 缺少 T20/PL/RUF ruff 规则 |
| 15 | 🟢 低优 | 代码风格 | indicators/registry.py 的 import 块过于分散 |

---

## 🔴 高优问题

### 1. `get_manager()` fetcher 初始化逻辑重复

**位置**: `stock_data/api/routes.py:242-308`, `stock_data/data_provider/persistence/stock_list.py:106-115`

**现象**: 两处各自实现了 fetcher 注册逻辑：

- `routes.py` 的 `get_manager()` 注册了全部 9 个 fetcher（Tushare → Baostock → Akshare → Yfinance → Tencent → EastMoney → THS → Cninfo → Zhitu）
- `stock_list.py` 的 `get_stock_list()` 在 `manager=None` 时，只注册了 `TushareFetcher` + `AkshareFetcher`

当新增 fetcher 或修改 fetcher 行为时，需要同时修改两处，容易遗漏。

**建议**:

```python
# stock_data/data_provider/manager_factory.py (新建)
def create_default_manager() -> DataFetcherManager:
    """Create a DataFetcherManager with all available fetchers registered."""
    manager = DataFetcherManager()
    fetcher_classes = [
        TushareFetcher, BaostockFetcher, AkshareFetcher, YfinanceFetcher,
        TencentFetcher, EastMoneyFetcher, ThsFetcher, CninfoFetcher, ZhituFetcher,
    ]
    for cls in fetcher_classes:
        instance = cls()
        if instance.is_available():
            manager.add_fetcher(instance)
            logger.info(f"{cls.__name__} added")
        else:
            logger.info(f"{cls.__name__} skipped")
    return manager
```

然后 `routes.py` 和 `stock_list.py` 都调用 `create_default_manager()`。

---

### 2. `_with_failover` 未被 manager 中 6 个方法使用

**位置**: `stock_data/data_provider/manager.py`

**现象**: `_with_failover` (line 105) 作为统一的 failover helper 设计良好，但以下 6 个方法绕过了它，各自手写了 failover 循环：

| 方法 | 所在行 | 绕过原因 |
|------|--------|----------|
| `get_kline_data` | 154 | 需要返回 `(DataFrame, source_name)` 而非单个值 |
| `get_intraday_data` | 219 | 同上 |
| `get_index_historical` | 434 | 同上 |
| `get_index_intraday` | 479 | 同上 |
| `get_realtime_quote` | 259 | 需要 circuit breaker 集成 |
| `get_report_pdf` | 632 | 需要返回 `(path, url)` |

**建议**: 扩展 `_with_failover` 支持：
- 返回 `(result, source_name)` (加 `return_source: bool = False`)
- circuit breaker 集成 (加 `use_circuit_breaker: bool = False`)
- 自定义结果提取 (加 `extract_result: Callable`)

---

### 3. TTLCache + SQLite Persistence 三层缓存边界不清

**位置**: 全局架构

**现象**: 部分数据流经 **两层缓存** 才到达用户：

```
请求 → TTLCache (进程内, 60-300s TTL)
     → SQLite Persistence (跨进程, 当日首次刷新)
     → 上游 API
```

具体重叠点：

| 数据类型 | TTLCache 存在? | SQLite Persistence 存在? | 重叠? |
|----------|:---:|:---:|:---:|
| stock list | ❌ | ✅ | - |
| trade calendar | ❌ (手动逻辑) | ✅ | - |
| board list | ✅ (`get_board_list_cache`) | ✅ (`stock_board` 表) | ✅ |
| board stocks | ✅ (`get_board_stocks_cache`) | ✅ (`stock_board_stock` 表) | ✅ |
| ZT pool | ✅ (`get_pools_cache`) | ✅ (`pool_daily` 表) | ✅ |

Board 和 ZT pool 的双层缓存意味着：TTLCache 返回了 298 秒前的数据，即使 SQLite 中已有更新数据。

**建议**: 明确两层分工：
- **TTLCache** → 实时性数据（realtime quote、intraday、history with indicators）
- **SQLite Persistence** → 持久性元数据（stock list、calendar、board metadata、pool_daily）
- 移除 board 和 pool 的 TTLCache，仅依赖 Persistence 层的 `_is_first_call_of_day` 刷新策略

---

## 🟡 中优问题

### 4. AkshareFetcher 过于庞大 (1106 行)

**位置**: `stock_data/data_provider/fetchers/akshare_fetcher.py`

**现象**: 单个 fetcher 承担了以下所有职责：

- K-line (d/w/m) — A股、HK、CSI index、US index
- Minute K-line (1/5/15/30/60) — A股、CSI index
- Realtime quote — A股、HK、CSI index
- Stock list — A股、HK、US
- Trade calendar
- Board (concept + industry) — list + stocks
- Index quote / historical / intraday
- ZT pool (zt/dt/zbgc)
- Intraday (EM primary + Sina fallback)

对比其他 fetcher 行数：

| Fetcher | 行数 |
|---------|------|
| AkshareFetcher | 1106 |
| EastMoneyFetcher | 443 |
| BaostockFetcher | 336 |
| ZhituFetcher | 336 |
| YfinanceFetcher | 413 |
| TushareFetcher | 277 |

**建议**: 将 AkshareFetcher 拆分为：
```
AkshareStockFetcher     — K-line, realtime quote, intraday, stock list
AkshareIndexFetcher     — index quote, index historical, index intraday
AkshareBoardFetcher     — concept/industry boards
AkshareCalendarFetcher  — trade calendar, ZT pool
```
或至少提取 Board 和 Index 功能到独立的 handler 类。

---

### 5. fetcher 各自的 code 转换/数据标准化逻辑缺少统一抽象

**位置**: 各 fetcher 文件

**现象**:

- `AkshareFetcher._convert_code()` — 53 行，处理 A股/HK/CSI/US 4 种路径
- `BaostockFetcher._convert_code()` — 32 行，sh./sz. 格式
- `TencentFetcher._tencent_prefix()` — sh/sz/hk/bj 4 种前缀
- `EastMoneyFetcher._secid()` — 1./0. secid 格式

**重复的 DataFrame 标准化** (Akshare 内部):

```python
# _normalize_index_daily, _normalize_index_daily_tx, _normalize_index_daily_em
# 三个方法的核心逻辑完全一致:
df = df.rename(columns={...})
df["date"] = pd.to_datetime(df["date"], errors="coerce")
for col in numeric_cols:
    df[col] = pd.to_numeric(df[col], errors="coerce")
df["code"] = code
df = df[[keep_cols]]
```

**建议**:
- 在 `utils/` 下添加 `code_converter.py`，提供 `to_tencent_prefix()`, `to_baostock_code()`, `to_eastmoney_secid()` 等统一转换函数
- 将三个 `_normalize_index_*` 合并为一个参数化的方法

---

### 6. EastMoneyFetcher API 端点配置硬编码分散

**位置**: `stock_data/data_provider/fetchers/eastmoney_fetcher.py`

**现象**: API URL、reportName、参数名散布在方法体内：

- `DATACENTER_URL` (line 21) — 只提取了 base URL
- `push2.eastmoney.com` URL (line 319) — 内联在 `get_fund_flow_minute` 中
- `push2his.eastmoney.com` URL (line 351) — 内联在 `get_fund_flow_120d` 中
- 各 filter 模板 `(TRADE_DATE>='...')` 分散在多个方法中

**建议**:

```python
class EastMoneyFetcher(BaseFetcher):
    ENDPOINTS = {
        "dragon_tiger": {
            "report_name": "RPT_DAILYBILLBOARD_DETAILSNEW",
            "sort_columns": "TRADE_DATE",
        },
        "margin": {
            "report_name": "RPTA_WEB_RZRQ_GGMX",
            "sort_columns": "DATE",
        },
        "fund_flow_minute": {
            "url": "https://push2.eastmoney.com/api/qt/stock/fflow/kline/get",
            "params": {"klt": 1, ...},
        },
        # ...
    }
```

---

### 7. `_build_kline_data` 中未使用 `safe_float`/`safe_int`

**位置**: `stock_data/api/routes.py:220-236`

**现象**: 项目已在 `data_provider/core/types.py` 中定义了 `safe_float()` 和 `safe_int()` 来处理 NaN/inf，但 `_build_kline_data` 使用原生 `float()` 和 `int()`：

```python
# 当前代码
open=float(row.get("open", 0)),
volume=int(row.get("volume", 0)),
amount=float(row.get("amount")) if row.get("amount") is not None else None,

# 如果 row["open"] 是 float('nan')，float(nan) 仍是 nan，
# 导致 Pydantic 序列化时产生 JSON 不合规的 NaN 值
```

**建议**:

```python
from ..data_provider.core.types import safe_float, safe_int

open=safe_float(row.get("open"), 0.0) or 0.0,
volume=safe_int(row.get("volume"), 0) or 0,
amount=safe_float(row.get("amount")),
```

---

### 8. fetcher 方法签名不一致

**位置**: 各 fetcher

**现象**:

| fetcher | `get_intraday_data` 参数 | `get_index_historical` 参数 |
|---------|--------------------------|---------------------------|
| AkshareFetcher | `period: str = "5"` | `period: str = "d"` |
| BaostockFetcher | (不实现) | `frequency: str` |
| YfinanceFetcher | `period: str = "5"` | (委托给 get_kline_data) |

- 同一个概念在不同方法里有时叫 `period`、有时叫 `frequency`
- `get_intraday_data` 有些返回 `DataFrame | None`，有些抛 `DataFetchError`

**建议**: 在 `BaseFetcher` 中统一定义 abstract method 签名，使用类型注解显式声明返回类型。

---

## 🟢 低优问题

### 9. `RealtimeSource.STOOQ` 枚举值已废弃

**位置**: `stock_data/data_provider/core/types.py:48`

**现象**: `RealtimeSource.STOOQ` 在枚举中定义但整个项目中无任何引用。Stooq 不在 9 个 fetcher 中，也不在 manager 的任何路由中。

**建议**: 移除 `STOOQ = "stooq"`，或标注 `# deprecated: removed in Phase N`。

---

### 10. `base.py` 的 `__all__` 包含非本模块符号

**位置**: `stock_data/data_provider/base.py:76-89`

**现象**:

```python
__all__ = [
    "DataCapability",        # ✅ 本模块定义
    "DataFetchError",        # ✅ 本模块定义
    "DataFetcherManager",    # ❌ 来自 .manager
    "BSE_CODES",             # ❌ 来自 .utils.normalize
    "ETF_PREFIXES",          # ❌ 来自 .utils.normalize
    "is_hk_market",          # ❌ 来自 .utils.normalize
    # ...
]
```

`base.py` 底部有 `from .manager import DataFetcherManager` 进行重导出，但将不属于自己的符号声明在 `__all__` 中会造成混淆。

**建议**: 将这些重导出仅放在 `data_provider/__init__.py` 中，`base.py` 只导出自己的符号。

---

### 11. `_is_first_call_of_day` 在 board.py 和 stock_list.py 中重复

**位置**:
- `stock_data/data_provider/persistence/stock_list.py:20-27`
- `stock_data/data_provider/persistence/board.py:20-28`

**现象**: 两个模块各自实现：

```python
# stock_list.py
_last_refresh_date: dict[str, str] = {}
_lock: Lock = Lock()

def _is_first_call_of_day(market: str) -> bool:
    today = datetime.now().strftime("%Y-%m-%d")
    with _lock:
        if _last_refresh_date.get(market) != today:
            _last_refresh_date[market] = today
            return True
        return False

# board.py — 完全相同, 仅 key 格式不同
_last_refresh_date: dict[str, str] = {}
_lock = Lock()

def _is_first_call_of_day(board_type: str, source: str) -> bool:
    today = datetime.now().strftime("%Y-%m-%d")
    key = f"{board_type}:{source}"
    with _lock:
        if _last_refresh_date.get(key) != today:
            _last_refresh_date[key] = today
            return True
        return False
```

**建议**: 提取到 `persistence/_refresh_policy.py`:

```python
class DailyRefreshTracker:
    def __init__(self):
        self._dates: dict[str, str] = {}
        self._lock = Lock()
    
    def is_first_call_of_day(self, key: str) -> bool:
        today = datetime.now().strftime("%Y-%m-%d")
        with self._lock:
            if self._dates.get(key) != today:
                self._dates[key] = today
                return True
            return False
```

---

### 12. 无 fetcher health/status 统一接口

**位置**: 全局

**现象**: 
- `BaseFetcher.is_available()` 只检查配置状态（是否安装、token 是否存在）
- 无法感知运行时健康状态（API 响应延迟、错误率、配额耗尽）
- `/health` endpoint 只能查看 circuit breaker 状态，无法主动探测

**建议**: 为 `BaseFetcher` 添加可选方法：

```python
def health_check(self) -> dict:
    """Return health status dict. Override for source-specific checks."""
    return {"status": "unknown", "message": "no health check implemented"}
```

---

### 13. 测试覆盖不均衡

**位置**: `tests/`

**现象**:

| 有测试 | 缺少测试 |
|--------|----------|
| ✅ 核心类型 (test_core_types.py) | ❌ AkshareFetcher (1106 行) |
| ✅ Base 类 (test_base.py, test_base_unit.py) | ❌ BaostockFetcher (336 行) |
| ✅ API Routes (test_routes.py) | ❌ YfinanceFetcher (413 行) |
| ✅ Indicators (7 个测试文件) | ❌ ZhituFetcher (336 行) |
| ✅ EastMoneyFetcher | ❌ TushareFetcher (277 行) |
| ✅ CninfoFetcher | |
| ✅ TencentFetcher | |
| ✅ THSFetcher | |

**额外问题**: `test_routes.py` 的集成测试直接调用上游 API，在没有网络或 API 限流时不稳定。

**建议**: 为核心 fetcher 添加 mock 单元测试（mock `akshare`、`baostock`、`yfinance` 等上游库）。

---

### 14. pyproject.toml 缺少 ruff 规则

**位置**: `pyproject.toml:53-55`

**现象**:

```toml
[tool.ruff.lint]
select = ["E", "F", "W", "I", "N", "UP", "B", "C4", "SIM"]
ignore = ["E501"]
```

未启用的推荐规则：
- `T20` — 检测 `print()` 语句（生产代码不应有）
- `PL` — Pylint 规则（如 `PLR0913` 检测过多参数）
- `RUF100` — 检测未使用的 `# noqa` 注释
- `TCH` — TYPE_CHECKING 相关导入规则

**建议**:

```toml
select = [
    "E", "F", "W", "I", "N", "UP", "B", "C4", "SIM",
    "T20",    # print detection
    "RUF100", # unused noqa
]
```

---

### 15. `indicators/registry.py` 的 import 风格

**位置**: `stock_data/data_provider/indicators/registry.py:23-64`

**现象**: 14 个独立的 `from . import (...)` 块，共 42 行：

```python
from . import (
    atr as _atr,
)
from . import (
    bias as _bias,
)
# ... 12 more blocks ...
```

**建议**: 合并为一个 import：

```python
from . import (
    atr as _atr,
    bias as _bias,
    boll as _boll,
    cci as _cci,
    dmi as _dmi,
    kc as _kc,
    kdj as _kdj,
    ma as _ma,
    macd as _macd,
    obv as _obv,
    roc as _roc,
    rsi as _rsi,
    sar as _sar,
    wr as _wr,
)
```

---

## 📊 统计总结

| 严重度 | 数量 | 主要类别 |
|--------|------|----------|
| 🔴 高优 | 3 | 代码重复、架构不一致、缓存边界 |
| 🟡 中优 | 5 | 单一职责、抽象缺失、健壮性 |
| 🟢 低优 | 7 | 废弃代码、测试、配置、代码风格 |
| **合计** | **15** | |

## 架构健康度评估

项目在近期 5 轮重构（ruff cleanup → P1/P2 cleanup → persistence 引入 → indicators 层 → back-compat 清理）后，代码质量显著提升。核心设计（capability-based routing + failover + circuit breaker + pure-compute indicators）合理且清晰。

主要改进方向：
1. **统一化** — factory 函数统一 fetcher 注册，`_with_failover` 统一 failover 模式
2. **模块化** — 拆分 AkshareFetcher，提取共享的 code 转换/标准化逻辑
3. **去重叠** — 清理 TTLCache 与 Persistence 的二重缓存

均不属于架构级风险，可逐步修复。
