# Source Tracking 设计文档

> 日期：2026-06-12
> 状态：待审
> 范围：在所有 server 端点的响应中暴露数据来源（fetcher 名 / persistence / cache）

## 1. 目标与范围

让 API 消费者在每个响应里都能看到**这个数据到底从哪儿来**，便于：
- 排障：当某个 fetcher 行为异常时，能直接定位
- 可观测性：判断 failover 链是否按预期工作
- 客户端决策：某些场景下客户端希望只信任特定 fetcher（例如延迟敏感场景避开 akshare）

**三类数据来源**：

| 类别 | source 字段值 | 范围 |
|---|---|---|
| **A. 实时拉取（fetcher）** | fetcher 名（`tushare` / `akshare` / `baostock` / ...） | 走 manager → fetcher 的直读路径 |
| **B. API TTLCache 命中** | 写入时的 fetcher 名（同 A） | cachetools `_history_cache_d` 等命中 |
| **C. SQLite 持久化命中** | 字面量 `"persistence"` | `persistence.board` / `pool_daily` / `stock_list` / `trade_calendar` 等命中 |

**不在范围内**：
- Per-bar / per-record 的 source 标注（一次 fetch 调用所有数据来自同一 fetcher，响应级别已足够）
- 完整 debug 模式（fallback 链、每个 fetcher 耗时、错误信息）—— 留作单独的可观测性工作
- 客户端按 source 过滤路由（业务需求未提出）

## 2. 现状

### 2.1 已经有 source 的端点

| 端点 | source 字段 | 来源 |
|---|---|---|
| `/stocks/{code}/quote` | `StockQuote.source` | `UnifiedRealtimeQuote.source`（line 79 schemas）|
| `/indices/{code}/quote` | `IndexQuote.source` | `UnifiedRealtimeQuote.source`（line 322 schemas）|
| `/stocks/{code}/reports/{id}/pdf` | 通过 `ReportPDFResponse.download_path/url` 反映 | manager 返回 `(path, url)` |

### 2.2 source 已返回但被丢弃

`manager.get_kline_data` / `get_intraday_data` / `get_index_historical` / `get_index_intraday` 已经返回 `(df, source)` 元组，但 `routes.py` 中：
- `routes.py:501` — `df, source = manager.get_kline_data(...)` 之后没传 source
- `routes.py:606` — `df, source = manager.get_intraday_data(...)` 之后没传 source
- `routes.py:824` — `df, source = manager.get_index_historical(...)` 之后没传 source
- `routes.py:905` — `df, source = manager.get_index_intraday(...)` 之后没传 source

### 2.3 完全没有 source（硬编码默认值）

`schemas.py` 中以下 response 写死了 `source: str = Field(default="eastmoney")`（或 `"ths"` / `"cninfo"`），掩盖了"数据实际从哪儿来"的事实：

| 端点 | 现状 | 应改为 |
|---|---|---|
| `DragonTigerResponse` | `default="eastmoney"` | `default=""` + 路由层注入 |
| `MarginTradingResponse` | `default="eastmoney"` | 同上 |
| `BlockTradeResponse` | `default="eastmoney"` | 同上 |
| `HolderNumResponse` | `default="eastmoney"` | 同上 |
| `DividendResponse` | `default="eastmoney"` | 同上 |
| `FundFlowResponse` | `default="eastmoney"` | 同上 |
| `DailyDragonTigerResponse` | `default="eastmoney"` | 同上 |
| `HotTopicResponse` | `default="ths"` | 同上 |
| `NorthFlowResponse` | `default="ths"` | 同上 |
| `ReportResponse` | `default="eastmoney"` | 同上 |
| `AnnouncementResponse` | `default="cninfo"` | 同上 |
| `BoardListResponse` | 无 source 字段 | 新增 |
| `BoardStocksResponse` | 已有 `source: str` 但值是用户传入的查询参数 | 拆为 `query_source`（查询参数）+ `data_source`（实际数据来源） |
| `ZTPoolResponse` | 无 source 字段 | 新增 |

**K线 / 分时类 4 个端点**（KLineData、IntradayResponse、IndexHistoryResponse、IndexIntradayResponse、StockHistoryResponse）目前没有 source 字段。

## 3. 关键设计决策

### 3.1 source 值的字符集

固定为以下几类（**禁止包含冒号、斜杠、连字符以外的特殊字符**）：

- 实时拉取 / 缓存命中：fetcher 名（已在 `RealtimeSource` 枚举中定义，e.g. `TUSHARE = "tushare"`）
- 持久化命中：字面量 `"persistence"`
- 未来扩展：`<fetcher>:failover-from-<other_fetcher>` 之类的复合形式暂不支持，**保持简单**

### 3.2 manager 层改动

给以下 12 个 wrapper 方法加 `return_source=True` 并把返回类型改为 `tuple[T, str]`：

```python
def get_dragon_tiger(...) -> tuple[dict, str]:
    return self._with_failover(..., return_source=True)

def get_daily_dragon_tiger(...) -> tuple[dict, str]: ...
def get_margin_trading(...) -> tuple[list[dict], str]: ...
def get_block_trade(...) -> tuple[list[dict], str]: ...
def get_holder_num_change(...) -> tuple[list[dict], str]: ...
def get_dividend(...) -> tuple[list[dict], str]: ...
def get_fund_flow_minute(...) -> tuple[list[dict], str]: ...
def get_fund_flow_120d(...) -> tuple[list[dict], str]: ...
def get_hot_topics(...) -> tuple[list[dict], str]: ...
def get_north_flow(...) -> tuple[list[dict], str]: ...
def get_reports(...) -> tuple[list[dict], str]: ...
def get_announcements(...) -> tuple[list[dict], str]: ...
```

`_with_failover` 已经支持 `return_source=True`，纯加一个参数 + 改返回类型注解。

### 3.3 持久化层改动（"persistence" 来源）

persistence 层的方法（如 `pool_daily.get_pool`、`board.get_board_list`）需要让路由层知道"这次是 cache hit 还是 fresh fetch"。

**策略**：统一改返回类型为 `(data, origin_str)` 元组：

```python
# persistence/pool_daily.py
def get_pool(...) -> tuple[list[dict], str]:
    """Returns (stocks, origin) where origin is fetcher name or 'persistence'."""
    ...

# persistence/board.py
def get_board_list(...) -> tuple[list, str]: ...
def get_board_stocks(...) -> tuple[list, str]: ...

# persistence/stock_list.py
def get_stock_list(...) -> tuple[list, str]: ...

# persistence/trade_calendar.py
def get_cached_calendar() -> tuple[list[str], str]:
    """origin: 'persistence' when cache has data, '' when empty."""
    ...
```

**位置选择**：
- 实时调用路径：origin = 实际 fetcher 名（manager 的 return_source 透传）
- 缓存命中路径：origin = `"persistence"`
- 都失败：origin = `""`（空字符串，与默认值一致）

### 3.4 路由层改动

12+ 处调用改造，模式化：

```python
# 实时 fetcher 类
data, source = manager.get_dragon_tiger(stock_code, trade_date, look_back)
return DragonTigerResponse(code=stock_code, source=source, ...)

# 持久化类
stocks, origin = pool_daily.get_pool(...)
return ZTPoolResponse(date=..., source=origin, ...)

# K线/分时（已有 df, source）—— 加上 source 字段
result = StockHistoryResponse(code=stock_code, source=source, ...)
```

### 3.5 缓存路径天然受益

由于响应 Pydantic 模型已经有 `source: str` 字段，且**TTL cache 直接存的是 response 实例**，写入时填好 source，命中时 response.source 已经是正确值。**无需为 cache 路径单独写代码。**

唯一需要注意的是：`StockHistoryResponse` 等新加的 `source` 字段用 `default=""`，且写入缓存前必须已经赋值（route 改造时同步进行）。

### 3.6 反向兼容性

**完全向后兼容**：
- 新增字段都为可选（`default=""`），旧 client 忽略即可
- 既有调用 `df, source = manager.get_kline_data(...)` 的解包不变（K线/分时 4 个端点已经这样写了）
- 持久化层方法 `get_pool` / `get_board_list` 等目前被 route 单返回调用，改成 tuple 返回需要把所有调用方一并改（~6 处）

**唯一破坏性变化**：`pool_daily.get_pool`、`board.get_board_list`、`board.get_board_stocks`、`stock_list.get_stock_list` 等持久化方法返回类型从 `T` 改为 `tuple[T, str]`。需要一次性把所有 caller 都改了。

## 4. 文件清单

| 路径 | 动作 | 改动量 |
|---|---|---|
| `stock_data/data_provider/manager.py` | 12 个 wrapper 加 `return_source=True`，改返回类型注解 | ~30 行 |
| `stock_data/data_provider/persistence/pool_daily.py` | `get_pool` 改返回 tuple，加 origin 追踪 | ~15 行 |
| `stock_data/data_provider/persistence/board.py` | `get_board_list` / `get_board_stocks` 改返回 tuple | ~10 行 |
| `stock_data/data_provider/persistence/stock_list.py` | `get_stock_list` 改返回 tuple | ~5 行 |
| `stock_data/data_provider/persistence/trade_calendar.py` | `get_cached_calendar` 改返回 tuple | ~5 行 |
| `stock_data/api/schemas.py` | 去掉 12+ 处硬编码默认值，7 个新加 source 字段（`StockHistoryResponse` / `IndexHistoryResponse` / `IntradayResponse` / `IndexIntradayResponse` / `BoardListResponse` / `BoardStocksResponse.data_source` / `ZTPoolResponse`） | ~20 行 |
| `stock_data/api/routes.py` | 12+ 处赋值 source，4 处 K线/分时补 source 字段 | ~30 行 |
| `tests/test_source_tracking.py` | 新建：单元 + 集成测试 | ~80 行 |
| `CLAUDE.md` | K线 / 实时行情 schema 说明里加 source 字段说明 | ~15 行 |

**总净增约 210 行**，其中**测试占 ~80 行**。生产代码净增约 120 行。

## 5. 测试计划

### 5.1 单元测试（manager 层）

`tests/test_manager_return_source.py`：
- 验证 `get_dragon_tiger` 在 eastmoney 成功时返回 `("eastmoney", data)`
- 验证 eastmoney 失败时返回正确的下一个 fetcher 名
- 验证所有 fetcher 失败时抛 `DataFetchError`（不变）

### 5.2 集成测试（route 层）

`tests/test_source_tracking.py`：
- **A. 实时拉取**：mock manager 返回固定 source，验证响应里 `source` 字段正确
- **B. 缓存命中**：第一次调用记录 fetcher X，第二次调用时强制 cache hit，验证 source 仍是 X
- **C. 持久化命中**：pre-populate SQLite，调用 `/pools` 验证 `source == "persistence"`
- **C → A 切换**：持久化里没数据时回退到 manager 调用，验证 source 是 fetcher 名而非 "persistence"

### 5.3 兼容性回归

- 跑现有所有 test suite，确保没有破坏 `KLineData`、`StockHistoryResponse` 等的现有 shape
- 验证 `KLineData._serialize` 的 `@model_serializer` 仍然正确（新增的 source 在响应级别，不在 KLineData 内）

## 6. 实施顺序

按依赖关系，分 4 个 PR（每个 PR 可独立 merge）：

1. **PR1 — manager 层 + 持久化层签名改造 + schema 默认值清理**：把 `_with_failover` 已经支持的 source 能力扩展到 12 个 wrapper，把 4 个 persistence 方法的返回类型从 `T` 改为 `tuple[T, str]`，同时更新所有 internal caller（persistence 方法内会调 manager），并把 schemas 的硬编码默认值去掉。
   - **本步骤是 internal breaking**：manager / persistence 签名变了，但 route 层还没动，**所有现有 caller 必须同步更新**，否则编译失败。
   - 完成后所有响应行为不变（route 还不会赋值 source，默认值 `""` 不变），**不破坏 client**。
2. **PR2 — 实时拉取类端点接通 source**：4 个 K线/分时 + 12 个直读 fetcher 的 route 端点，调用 manager 后用 `, source =` 接住并塞进 response。
3. **PR3 — 持久化类端点接通 source**：4-5 个持久化类 route 端点（`/pools` / `/boards` / `/stocks` / `/calendar` / 走 persistence 的 `/stocks/{code}/dragon-tiger` 等）调用 persistence 方法后用 `, origin =` 接住并塞进 response。
4. **PR4 — 测试 + 文档**：补齐测试和 CLAUDE.md。

> **小项目其实可以合并成 1-2 个 PR**：上述 4 个 PR 拆分的价值在于让 reviewer 看到清晰的"破坏性边界"。如果团队习惯一次性 review，PR1+PR2 合并、PR3+PR4 合并也是合理的。

## 7. 风险与回滚

### 7.1 风险

- **持久化层方法签名变化**（T → tuple[T, str]）是**唯一破坏性变化**，必须一次性把全部 caller 改完。grep 一下所有 `from .persistence import`、`pool_daily.get_pool`、`stock_board_cache.get_board_list` 等引用方。
- 持久化层里 source 字符串拼接需要小心，避免 `update` / `get` 路径上 source 拼错（特别是 cache hit 路径容易漏写）。
- 测试用例里 mock 可能遗漏，建议以"端到端 + 全量 mock"双轨测试。

### 7.2 回滚

- 各 PR 独立可回滚
- 由于新字段都是 `default=""`，PR2 / PR3 即使有 bug，client 忽略 source 字段也能正常工作（降级为旧行为）
- 持久化层签名变化无法降级，但可以走 hotfix

## 8. 不做的（YAGNI）

- **Per-bar source in KLineData**：单次 fetch 所有 bar 来自同一 fetcher，响应级别足够
- **完整 debug 模式**（fallback 链 / 耗时 / 错误详情）：留作单独的可观测性工作
- **客户端按 source 过滤路由**：业务需求未提出
- **改 `UnifiedRealtimeQuote.source` 的字段语义**：该字段已存在且正确，不动
