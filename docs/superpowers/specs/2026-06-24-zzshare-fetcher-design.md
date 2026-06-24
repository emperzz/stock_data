# ZzshareFetcher 设计文档

> 日期：2026-06-24
> 状态：待审
> 范围：新增 `ZzshareFetcher`，注册 10 个 capability（K线/分钟/实时/列表/日历/板块/涨跌停/龙虎榜/题材热度/公司画像）；boards endpoint 的 `_VALID_SOURCES` 加入 `zzshare`
> 源文档：`docs/zzshare/README.md` + 10 个子文档
> 数据源：https://api.zizizaizai.com（DataApi SDK）

## 1. 目标与范围

把 `docs/zzshare/` 文档化的 40+ zzshare 接口，按「项目现有 capability 体系」映射并实现为新的 `ZzshareFetcher`。

**动机**：
- zzshare 是面向 AI Agent / LLM 优化的 A 股量化数据 SDK，同花顺题材 + 涨停复盘 + 情绪热度 14 个接口是其差异化优势，与项目现有的 EastMoney（东财数据中心）和 Zhitu（智兔）形成互补
- zzshare 仅覆盖 csi（沪深北 A 股），与 ZhituFetcher 同位置——priority 5 是合适的"次选匿名上游"
- 多数接口匿名可调（README §「探针实测记录」探测 12 个接口中 10 个匿名通过：trade_days / stock_basic / daily / daily(adj) / stk_mins / rt_k / uplimit_hot / lhb_list / ths_hot_top / plates_rank），不会像 Tushare/Zhitu/Myquant 那样因为缺 token 而整体跳过

**v1 范围**：
- 新建 `stock_data/data_provider/fetchers/zzshare_fetcher.py`（单文件，单类）
- 10 个 capability（详细映射见 §4）：
  - `HISTORICAL_DWM` / `HISTORICAL_MIN` / `REALTIME_QUOTE` / `STOCK_LIST` / `TRADE_CALENDAR`
  - `STOCK_BOARD`（4 个 board 方法）/ `STOCK_ZT_POOL`
  - `DRAGON_TIGER` / `HOT_TOPICS` / `STOCK_INFO`
- boards endpoint 的 `_VALID_SOURCES` 扩到 `{"eastmoney", "zhitu", "zzshare"}`
- 默认 priority **P5**（与 Tencent 同优先级 P5。manager 的 `create_default_manager()` 在 `fetcher_classes` 列表里把 `ZzshareFetcher` 放在 `ZhituFetcher(P4)` 之后、`TencentFetcher(P5)` 之前；Python `sorted` 是稳定排序，所以 P5 同级时 zzshare 排在 Tencent 前面）
- 鉴权：从 `ZZSHARE_TOKEN` 环境变量读取，无 token 时走匿名路径
- 通信：使用 `DataApi` Python SDK（用户选择）；通过 `importlib.util.find_spec` 探测，未安装则 fetcher 不注册

**不在 v1 范围**：
- 不实现 11 个 zzshare 不支持的能力（INDEX_* / MARGIN_TRADING / BLOCK_TRADE / HOLDER_NUM / DIVIDEND / FUND_FLOW / NORTH_FLOW / RESEARCH_REPORT / ANNOUNCEMENT / NEWS_SEARCH / NEWS_FLASH）——`is_available()=True` 但不声明这些 capability
- 不实现 zzshare 独有但无对应 capability 的接口（topic_table_* / ai_report_* / movement_alerts / 14 个 sentiment 接口 / market_plate_popular_reason / uplimit_market_value）
- `get_stock_boards` SDK 无反查接口 → 返回 `None` 让路由层 404（与 EastMoney 同款）
- `get_board_history` 暂保持 zhitu 同样的 `NotImplementedError` 占位（除非发现 `plate_kline` 已稳定可用，本次 v1 不实现）

## 2. 架构

```
                ┌──────────────────────────────────────────┐
                │   api/routes/*  (已存在的 endpoint)       │
                │   /stocks/{code}/history / quote / ...   │
                │   /boards / boards/{code}/stocks / ...   │
                │   /dragon-tiger / hot-topics / ...       │
                └──────────────┬───────────────────────────┘
                               │
                ┌──────────────┴───────────────────────────┐
                │                                          │
                ▼                                          ▼
   _with_failover (capability 路由)              _with_source (boards 路由)
   10 个 capability 自动让 zzshare 参与          ?source=zzshare 路由
                │                                          │
                ▼                                          ▼
   ┌────────────────────────────────┐         ┌──────────────────────────┐
   │  DataFetcherManager            │         │  ZzshareFetcher          │
   │  按 priority 排序:             │         │  get_all_boards /        │
   │  [P0 Tushare, P1 Baostock,     │         │  get_board_stocks /      │
   │   P2 Akshare, P3 Yfinance,     │         │  get_stock_boards (None) │
   │   P4 Zhitu, P5 zzshare, ...]   │         │  get_board_history (501) │
   └──────────────┬─────────────────┘         └──────────────────────────┘
                  │
                  ▼
          ZzshareFetcher (P5 NEW)
          - is_available() 探测 DataApi SDK
          - 10 个方法（_fetch_raw_data, get_realtime_quote,
            get_all_stocks, get_trade_calendar, get_intraday_data,
            get_zt_pool, get_dragon_tiger, get_daily_dragon_tiger,
            get_hot_topics, get_stock_info）
          - 4 个 board 方法（get_all_boards, get_board_stocks,
            get_stock_boards, get_board_history）
```

**复用现有边界**：
- `DataFetcherManager` 已有 `_with_failover`（capability failover）和 `_with_source`（boards 路由）两套机制，**核心逻辑零改动**——只追加 fetcher
- `BaseFetcher` ABC 已定义 `get_realtime_quote / get_all_stocks / get_trade_calendar / get_intraday_data / get_zt_pool / get_dragon_tiger / get_daily_dragon_tiger / get_hot_topics / get_stock_info / get_all_boards / get_board_stocks / get_stock_boards / get_board_history` 等方法签名，**零改动**
- `CAPABILITY_TO_METHOD`（base.py L79）已含 10 个 capability 的 method 映射，**零改动**
- `_with_source` 走 `_derive_slug(fetcher_name)` 派生 slug：`"ZzshareFetcher"` → `"zzshare"`——`source="zzshare"` 自动解析

**关键决策**：
- **单文件、单类**：仿 `ZhituFetcher` 模式。所有 10 个 capability 共享同一个 `DataApi` SDK 实例与同一份频率配额；拆子包只会导致 import / 单例缓存重复
- **不走 akshare 子包模式**：akshare 拆子包是因为有 `index_norm.py` 大量指数路由表；zzshare 没这种辅助层
- **不强加 token**：zzshare 大部分接口匿名可调（README 探测 13/14 通过），所以 `is_available()` 只检查 SDK 是否安装，不检查 token；运行时无 token 的方法调匿名路径
- **boards 走 `_with_source`**：zzshare 的 `plate_type=14/15/17` 与 EastMoney/Zhitu 体系不互通，failover 会误导调用方

## 3. 数据流

### K线 & 分钟线

```
GET /stocks/{code}/history?period=daily&days=30
   │
   ▼
manager.get_kline_data(code, ..., frequency="d")
   │
   ▼
_with_failover(capability=HISTORICAL_DWM, market="csi", ...)
   │
   │  按 priority 排序: [P0 Tushare, P1 Baostock, P2 Akshare, P3 Yfinance,
   │                    P4 Zhitu(只声明 HISTORICAL_MIN), P5 zzshare, ...]
   │
   ├─→ Tushare (P0) → akshare → ... → Zhitu (P4 raises DataFetchError)
   │
   └─→ zzshare (P5)
         │  api.daily(ts_code="600519.SH", start_date="20260501",
         │            end_date="20260520", adj="qfq"/"hfq"/None)
         │  → DataFrame{ts_code, trade_date, open, high, low, close,
         │              pre_close, change, pct_chg, vol, amount}
         │
         ▼ 归一化
         DataFrame{code, date(YYYY-MM-DD), open, high, low, close,
                   volume(vol→volume), amount, pct_chg}
```

**代码转换**：`normalize_stock_code("600519")` → `"600519"` → `_to_zzshare_ts_code("600519")` → `"600519.SH"`（6/68→SH, 0/3→SZ, 8/4/2/9→BJ）

**日期转换**：`YYYY-MM-DD` → `YYYYMMDD`（统一 `_to_yyyymmdd()` helper）

**周/月线**：`frequency="w"` 或 `"m"` 时抛 `DataFetchError("ZzshareFetcher 不支持周/月线")` 让上层 fail-over 走 baostock/tushare（与 myquant 同款）

### 板块（source-routed）

```
GET /boards?type=concept&source=zzshare&subtype=同花顺概念
   │
   ▼
boards.py: _resolve_source("zzshare") ✓
   │
   ▼
stock_board_cache._validate_subtype("zzshare", "concept", "同花顺概念") ✓
   │  （persistence/board.py VALID_SUBTYPES_BY_SOURCE["zzshare"] 含此 subtype）
   ▼
manager.get_all_boards(source="zzshare", board_type="concept", subtype="同花顺概念")
   │
   ▼
_with_source(source="zzshare", capability=STOCK_BOARD, market="csi", ...)
   │  slug 匹配: "zzshare" → ZzshareFetcher
   ▼
zzshare.get_all_boards(board_type="concept", subtype="同花顺概念", source="zzshare", include_quote=False)
   │  api.plates_list(plate_type=15) → 全量概念板块列表
   │  → [{code, name, type="concept", subtype="同花顺概念"}, ...]
   ▼
返回 (boards, "zzshare")
```

### 龙虎榜

```
GET /stocks/{code}/dragon-tiger
   │
   ▼
manager.get_dragon_tiger(code, trade_date, look_back)
   │
   ▼
_with_failover(capability=DRAGON_TIGER, market="csi", ...)
   │
   └─→ zzshare (P5)
         │  api.lhb_detail(date1=YYYYMMDD, stock_code="600519")
         │  找不到时回退 api.lhb_stock_history(stock_code="600519")
         │  → 标准化 DragonTigerRecord 列表
         ▼
         返回 ({records, seats, institution}, "zzshare")
```

### 公司画像

```
GET /stocks/{code}/info
   │
   ▼
manager.get_stock_info(code)
   │
   ▼
_with_failover(capability=STOCK_INFO, market="csi", ...)
   │  排序: [P4 Zhitu, P5 zzshare, P9 Myquant]
   │
   ├─→ Zhitu (P4) 优先
   │
   └─→ zzshare (P5) 备
         │  api.stock_info(stock_id="600519", info_type=1)
         │  → 18 字段 dict（与 ZhituFetcher.get_stock_info 同款 shape）
         ▼
         返回 (dict, "zzshare")
```

## 4. capability → SDK 方法映射

| Capability | SDK 方法 | 入参转换 | 出参归一化 | 方法需 token? |
|---|---|---|---|---|
| `HISTORICAL_DWM` | `api.daily(ts_code, start_date=YYYYMMDD, end_date=YYYYMMDD, adj)` | `frequency="w"/"m"` 抛 `DataFetchError` | DataFrame: `vol→volume`, `trade_date→date(YYYY-MM-DD)`, `pct_chg` 透传 | 否 |
| `HISTORICAL_MIN` | `api.stk_mins(ts_code, freq='1min'/'5min'/..., trade_time=YYYYMMDD)` | period→freq 映射 `'1'→'1min', '5'→'5min'` | DataFrame: `vol→volume`, `trade_time(YYYYMMDDHHMM)→time(HH:MM:SS)` | 否 |
| `REALTIME_QUOTE` | `api.rt_k(ts_code, fields='all')` | — | `UnifiedRealtimeQuote`：基础价从 `pre_close/open/high/low/close/vol/amount`；`quote_rate→change_pct`、`turnover_rate→turnover_rate`、`market_value→total_mv`、`circulation_value→circ_mv`、`ttm_pe_rate→pe_ratio` | 否（单只匿名通过） |
| `STOCK_LIST` | `api.stock_basic(exchange='ALL', list_status='L')` | — | `list[dict]`: `ts_code→code`, `name→name`, `exchange(SSE/SZSE/BSE)→exchange`；`area/industry/list_date` 留空让其他 fetcher 兜底 | 否 |
| `TRADE_CALENDAR` | `api.trade_days(day_start=..., day_end=...)` | — | `list[str]` 已是 `YYYY-MM-DD` | 否 |
| `STOCK_INFO` | `api.stock_info(stock_id, info_type=1)` | `stock_id` 6 位裸码 | 18-字段 dict（与 ZhituFetcher 同 shape） | **是**（无 token 返 None 走 Zhitu/Myquant） |
| `STOCK_ZT_POOL` | `api.uplimit_hot(date1)` + `api.uplimit_stocks(date1)` | — | `pool_type='zt'` 时合并：hot 板块名 + stocks 个股 | `uplimit_stocks` 是；`uplimit_hot` 否。无 token 降级只返回 hot 板块 |
| `STOCK_BOARD.get_all_boards` | `api.plates_list(plate_type=14/15/17)` | type/subtype → plate_type 映射（见下表） | `[{code, name, type, subtype}]` | 否 |
| `STOCK_BOARD.get_board_stocks` | `api.plates_stocks(plate_type, plate_code, date=...)` | — | `[{stock_code, stock_name, exchange}]`，6 位裸码补 `.SH/.SZ/.BJ` | 否 |
| `STOCK_BOARD.get_stock_boards` | **无** | — | 返回 `None`（与 EastMoney 同款，路由层 404） | — |
| `STOCK_BOARD.get_board_history` | **占位** | — | `raise NotImplementedError`（与 Zhitu 同款） | — |
| `DRAGON_TIGER`（个股） | `api.lhb_detail(date1, stock_code)` → 失败回退 `api.lhb_stock_history(stock_code)` | — | `DragonTigerResponse` 字段 | 否 |
| `DRAGON_TIGER`（全市场） | `api.lhb_list(date1)` | — | `DailyDragonTigerResponse` 字段；`stock_code` 6 位裸码补后缀 | 否 |
| `HOT_TOPICS` | `api.ths_hot_top(date1, top_n=100)` + `api.stock_ths_hot(code, date1)` | — | `HotTopicRecord` 字段；`symbol_code` 补后缀 | 否 |

**zzshare plate_type → 项目 type/subtype 映射**：

| zzshare `plate_type` | 含义 | 项目 `type` | 项目 `subtype` |
|---|---|---|---|
| `14` | 行业板块 | `industry` | `同花顺行业` |
| `15` | 概念板块 | `concept` | `同花顺概念` |
| `17` | 题材板块 | `special` | `同花顺题材` |

不映射（zzshare 没有"index 板块"接口）。

## 5. 类定义

### 位置和结构

`stock_data/data_provider/fetchers/zzshare_fetcher.py`（与 `zhitu_fetcher.py` 同级）。

```python
class ZzshareFetcher(BaseFetcher):
    """zzshare SDK fetcher — A-share multi-capability."""

    name = "ZzshareFetcher"
    priority = int(os.getenv("ZZSHARE_PRIORITY", "5"))
    supported_markets: set[str] = {"csi"}
    supported_data_types = (
        DataCapability.HISTORICAL_DWM
        | DataCapability.HISTORICAL_MIN
        | DataCapability.REALTIME_QUOTE
        | DataCapability.STOCK_LIST
        | DataCapability.TRADE_CALENDAR
        | DataCapability.STOCK_BOARD
        | DataCapability.STOCK_ZT_POOL
        | DataCapability.DRAGON_TIGER
        | DataCapability.HOT_TOPICS
        | DataCapability.STOCK_INFO
    )

    def __init__(self):
        self._token = os.getenv("ZZSHARE_TOKEN", "").strip()
        self._api = None                       # 懒加载 DataApi 实例
        self._init_error: str | None = None    # is_available() 失败原因

    def is_available(self) -> bool:
        """True iff DataApi SDK importable AND (有 token OR 任一匿名路径可用).

        仿 myquant 模式: 懒初始化在第一次 is_available() 触发; DataApi 不可导入
        时 is_available() 返回 False, fetcher 不被 manager 注册.
        """
        ...

    def unavailable_reason(self) -> str | None:
        """当 is_available() 返 False 时被 explorer 调用, 给出具体缺失原因."""
        ...

    # ---- K线 / 分钟线 ----
    def _fetch_raw_data(self, code, start_date, end_date, frequency="d", adjust=None):
        if frequency in ("w", "m"):
            raise DataFetchError(f"ZzshareFetcher 不支持 {frequency} 线")
        ...
        return api.daily(ts_code=..., start_date=YYYYMMDD, end_date=YYYYMMDD,
                         adj=...)

    def _normalize_data(self, df, code):
        # vol → volume, trade_date → date (YYYY-MM-DD)
        ...

    def get_intraday_data(self, code, period="5", adjust="") -> pd.DataFrame | None:
        # adjust 在分钟档不生效
        ...

    # ---- 实时 / 列表 / 日历 ----
    def get_realtime_quote(self, code) -> UnifiedRealtimeQuote | None: ...
    def get_all_stocks(self, market="csi") -> list: ...
    def get_trade_calendar(self) -> list[str] | None: ...

    # ---- 涨跌停 / 龙虎榜 / 题材热度 / 公司画像 ----
    def get_zt_pool(self, pool_type, date) -> list[dict] | None: ...
    def get_dragon_tiger(self, code, trade_date, look_back) -> dict: ...
    def get_daily_dragon_tiger(self, trade_date, min_net_buy) -> dict: ...
    def get_hot_topics(self, date_str) -> list[dict]: ...
    def get_stock_info(self, code) -> dict | None: ...

    # ---- boards (4 方法, source-routed) ----
    def get_all_boards(self, board_type, subtype=None, source="zzshare",
                       include_quote=False) -> list[dict]: ...
    def get_board_stocks(self, board_code, **kwargs) -> list[dict]: ...
    def get_stock_boards(self, stock_code, **kwargs) -> list[dict] | None:
        return None  # SDK 无反查接口
    def get_board_history(self, board_code, frequency="d", days=30, **kwargs):
        raise NotImplementedError(...)
```

### 工具函数（模块内私有）

```python
def _to_zzshare_ts_code(code: str) -> str:
    """6 位裸码 → '600519.SH' / '000001.SZ' / '830xxx.BJ'."""
    c = code.strip()
    if c.startswith(("6", "68", "5")):   return f"{c}.SH"
    if c.startswith(("0", "3", "1")):   return f"{c}.SZ"
    if c.startswith(("8", "4", "2", "9")): return f"{c}.BJ"
    return c  # 兜底

def _add_exchange_suffix(stock_code: str) -> str:
    """6 位裸码 → '600519.SH' 形式（与 ts_code 派生一致）."""
    return _to_zzshare_ts_code(stock_code)

def _to_yyyymmdd(date: str) -> str:
    """'2026-05-20' → '20260520'."""
    return date.replace("-", "")
```

## 6. 路由层改动

### `api/routes/boards.py`

```diff
- _VALID_SOURCES = {"eastmoney", "zhitu"}
+ _VALID_SOURCES = {"eastmoney", "zhitu", "zzshare"}

  @router.get("/boards")
- source: Literal["eastmoney", "zhitu"] = Query(...)
+ source: Literal["eastmoney", "zhitu", "zzshare"] = Query(...)

  @router.get("/boards/{board_code}/stocks")
- source: Literal["eastmoney", "zhitu"] = Query(...)
+ source: Literal["eastmoney", "zhitu", "zzshare"] = Query(...)

  @router.get("/stocks/{code}/boards")
- source: Literal["zhitu", "eastmoney"] = Query(...)
+ source: Literal["zhitu", "eastmoney", "zzshare"] = Query(...)
- if source != "zhitu":
+ if source not in ("zhitu", "zzshare"):
      raise HTTPException(status_code=501, ...)
```

### `persistence/board.py`

```python
VALID_SUBTYPES_BY_SOURCE: dict[str, dict[str, set[str]]] = {
    "eastmoney": {...},  # 不变
    "zhitu":     {...},  # 不变
    "zzshare":   {
        "industry": {"同花顺行业"},
        "concept":  {"同花顺概念"},
        "special":  {"同花顺题材"},
        # "index" 留空 — zzshare 不暴露大盘指数板块
    },
}
```

### `manager.py`

```python
from .fetchers.zzshare_fetcher import ZzshareFetcher

fetcher_classes = [
    TushareFetcher,
    BaostockFetcher,
    MyquantFetcher,
    AkshareFetcher,
    YfinanceFetcher,
    ZhituFetcher,
    ZzshareFetcher,   # NEW (P5)
    TencentFetcher,
    EastMoneyFetcher,
    BaiduFetcher,
    ThsFetcher,
    CninfoFetcher,
]
```

## 7. pyproject.toml 改动

```toml
[project.optional-dependencies]
zzshare = ["DataApi>=0.1.0"]   # 包名/版本号待实施时通过 `pip index versions DataApi` 验证
```

**验证步骤**（实现阶段执行）：
1. `pip index versions DataApi` 看是否在 PyPI
2. 若不在 PyPI，git 仓库 `https://github.com/zzquant/zzshare` 是否有 Python SDK 源 (`pip install git+https://github.com/zzquant/zzshare.git#subdirectory=sdk`)
3. 若 git 也没有 → 改用纯 `requests` 直连 `https://api.zizizaizai.com`，本节 pyproject 改动可省略（与 zhitu 同款）

不论哪种选择，`is_available()` 都用 `importlib.util.find_spec` 探测 + 懒初始化，对最终行为无影响。

## 8. 测试

### `tests/test_zzshare_fetcher.py`（新文件）

仿 `tests/test_myquant_fetcher.py` 的结构（按能力分组 + 30 个 case）。**全部 monkeypatch 注入 DataApi 假对象**，不依赖真实网络/Token。

```
TestZzshareFetcher
  ├── 基础元数据
  │     test_name_and_priority
  │     test_supported_markets
  │     test_capabilities_all_10
  │
  ├── is_available 三态
  │     test_is_available_no_sdk
  │     test_is_available_with_sdk_no_token
  │     test_is_available_with_sdk_and_token
  │     test_unavailable_reason_no_sdk
  │     test_unavailable_reason_no_token
  │
  ├── K线
  │     test_kline_daily_normalizes_columns
  │     test_kline_daily_adjust_qfq
  │     test_kline_daily_adjust_hfq
  │     test_kline_daily_unsupported_weekly_raises
  │     test_kline_daily_unsupported_monthly_raises
  │
  ├── 分钟线
  │     test_kline_minute_normalizes_time
  │     test_kline_minute_period_to_freq
  │     test_kline_minute_adjust_ignored
  │
  ├── 实时行情
  │     test_realtime_quote_basic_fields
  │     test_realtime_quote_uses_zzshare_source
  │
  ├── 列表
  │     test_get_all_stocks_normalizes_exchange
  │     test_get_all_stocks_empty_area_industry
  │     test_get_all_stocks_non_csi_returns_empty
  │
  ├── 日历
  │     test_trade_calendar_passthrough
  │
  ├── 公司画像
  │     test_get_stock_info_returns_18_fields
  │
  ├── 涨跌停
  │     test_zt_pool_combines_hot_and_stocks
  │     test_zt_pool_no_token_falls_back_to_hot
  │
  ├── 板块
  │     test_get_all_boards_industry_via_14
  │     test_get_all_boards_concept_via_15
  │     test_get_all_boards_special_via_17
  │     test_get_board_stocks_adds_exchange_suffix
  │     test_get_stock_boards_returns_none
  │
  ├── 龙虎榜
  │     test_lhb_list_normalizes_stock_code
  │     test_lhb_detail_returns_seats
  │
  ├── 题材热度
  │     test_ths_hot_top_normalizes_symbol_code
  │
  └── helpers
        test_to_zzshare_ts_code
        test_add_exchange_suffix_helper
        test_to_yyyymmdd_helper
```

预计 30 个 test case, 全部离线, < 1s 执行。

### 现有测试微改

| 文件 | 改动 |
|---|---|
| `tests/test_capability_method_map.py` | `_CONCRETE_FETCHERS` 元组加 `ZzshareFetcher` |
| `tests/test_boards.py` | 1 个 case：`source=zzshare` 走通 `_resolve_source` + `_validate_subtype` |
| `tests/test_boards_api.py` | 1 个 case：`source=zzshare` 返回 boards 数据 |
| `tests/test_board_persistence_subtype.py` | 1 个 case：`"zzshare"` subtype 校验 |

### 端到端冒烟（手工）

```bash
# 1. 启动 server
.venv/Scripts/python.exe -m stock_data.server &

# 2. 验证 manifest 自动包含 zzshare
curl -s http://localhost:8888/api/v1/control/api-manifest | jq '.sections[].endpoints[] | select(.fetchers[]?.name=="ZzshareFetcher") | .path'

# 3. 实测 3 个有代表性 endpoint
curl 'http://localhost:8888/api/v1/stocks/600519/history?days=5&period=daily'             # K线
curl 'http://localhost:8888/api/v1/stocks/600519/quote'                                  # 实时
curl 'http://localhost:8888/api/v1/boards?type=concept&source=zzshare&limit=5'           # boards
```

成功标志：每个响应 `"source": "zzshare"`（boards 为 `"data_source": "zzshare"`）, HTTP 200, 数据非空。

## 9. 风险与决策

| 风险 | 决策 |
|---|---|
| DataApi 包名/版本号未在 PyPI 确认 | v1 先在 `pyproject.toml` 写占位 optional-dep, 真发布前确认; 不影响 fetcher 行为（is_available 用 find_spec 探测） |
| 匿名调用 429 频率限制 | 透传给上层; manager 的 `_with_failover` 把它当 fetcher 失败处理, 自动降级到下一个 |
| `STOCK_INFO` 需 token | 降级到 Myquant 兜底（已是 manager 链末位） |
| `uplimit_stocks` 需 token | 降级到 `uplimit_hot` 板块列表; pool 返回非空 |
| `get_stock_boards` 无 SDK 接口 | 返回 `None`, 路由层 404（与 EastMoney 同款; 这是"已知不支持"不是 501） |
| `get_board_history` 暂未实现 | `NotImplementedError`（与 Zhitu 同款; 后续 v2 可基于 `plate_kline` 实现） |
| 6 位裸码补 `.SH/.SZ/.BJ` 的规则 | 与 zzshare README §「股票代码格式」一致（6/68→SH, 0/3→SZ, 8/4/2/9→BJ） |
| `lhb_list` 6 位裸码 + `csi` 限定 | 自动补后缀, 让上层 `manager.get_dragon_tiger` 的 stock_code 6 位规则不破坏 |
| boards 的 14/15/17 与 Zhitu 13 type2 互不兼容 | boards endpoint 的 `_VALID_SOURCES` 区分, failover 不跨源 |
| zzshare SDK 升级 | 出参归一化层都在 fetcher 内部, 不影响 manager / 路由 / schema |

## 10. 未来扩展（非 v1 范围）

- `get_board_history` 基于 `api.plate_kline(b_code, date1, date2)` 实现
- zzshare 14 个 sentiment 接口（market_sentiment / sentiment_timing / …）需要新建 capability flags
- topic_table_* / ai_report_* 同上
- `stock_moneyflow` / `market_mf` 若 SDK 重新启用 → 补 `FUND_FLOW` capability

## 11. CLAUDE.md 更新

`stock_data/CLAUDE.md` 的 "Provider Frequency Support" 表和 "Fetcher capability declarations" 表新增一行 `ZzshareFetcher`；"Capability-Based Routing" 表中 zzshare 支持的能力补上 `(ZzshareFetcher P5)` 标注。

## 12. 不在范围内的事项（明确排除）

- ❌ 11 个 zzshare 不支持的能力（INDEX_* / MARGIN_TRADING / BLOCK_TRADE / HOLDER_NUM / DIVIDEND / FUND_FLOW / NORTH_FLOW / RESEARCH_REPORT / ANNOUNCEMENT / NEWS_SEARCH / NEWS_FLASH）
- ❌ zzshare 独有但项目无对应 capability 的接口（topic_table_* / ai_report_* / movement_alerts / 14 个 sentiment 接口 / market_plate_popular_reason / uplimit_market_value / uplimit_trend 等）
- ❌ `get_stock_boards` 反查接口（SDK 不支持）
- ❌ `get_board_history` K线（v1 留 NotImplementedError，v2 用 plate_kline 实现）
- ❌ 真实网络/Token 测试（留给 CI integration 阶段或本地手工）
- ❌ 重构现有 EastMoney/Zhitu fetcher 的代码
- ❌ 修改 explorer/tags.py / index.html（10 个 capability 名字已在 labels/groups）
