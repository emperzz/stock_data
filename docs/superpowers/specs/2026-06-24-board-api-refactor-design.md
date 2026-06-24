# Board API 重构设计

> 日期：2026-06-24
> 状态：待用户审阅

## 1. 问题陈述

### 1.1 当前问题

- `source` 参数是"假开关"——API 接受 `?source=eastmoney` 但仅作为缓存键，不实际路由到不同数据源
- 只有 `AkshareFetcher` 声明 `STOCK_BOARD`，但它内部硬编码调用 EastMoney API（通过 akshare 封装）
- `_with_failover` 的 failover 模型与板块数据本质矛盾——不同数据源有完全不同的板块分类体系和代码体系（EastMoney 的 `BK1048` vs Zhitu 的 `sw_mt` / `chgn_700532`），无法透明 failover
- 缺少"股票所属板块"和"板块 K 线"两个关键 API

### 1.2 目标

- `source` 参数必填，真正驱动 fetcher 路由
- 每个真实数据源独立承接自己的板块方法（EastMoney → EastMoneyFetcher, Zhitu → ZhituFetcher, zzshare → ZzshareFetcher）
- 统一的板块分类体系：`type`（4 大类）+ `subtype`（source-specific 细分）
- 新增 2 个 API 端点，合并 1 个（排名能力并入板块清单）

## 2. Manager 层 —— 新增 source 路由原语

### 2.1 `_with_source`

```python
def _with_source(
    self,
    source: str,
    capability: DataCapability,
    market: str,
    op_label: str,
    call: Callable[[BaseFetcher], T],
) -> T:
    """根据 source 名定位唯一 fetcher 并调用，不做 failover。

    source 参数值匹配 ``fetcher.name.lower()``。
    找不到对应 fetcher 或不具备 capability → ValueError。
    调用失败 → DataFetchError（不 fallback 到其他 fetcher）。
    """
```

`_with_failover` 保持不变，用于非板块场景（如历史 K 线、实时行情等）。

## 3. 板块分类体系

### 3.1 `type`（跨 source 统一）

| type | 含义 |
|---|---|
| `concept` | 概念板块（热门概念、概念板块、地域板块 …） |
| `industry` | 行业板块（申万行业、申万二级、证监会行业 …） |
| `index` | 指数 / 分类（分类、指数成分、大盘指数） |
| `special` | 特殊分类（风险警示、次新股、沪港通、深港通） |

### 3.2 `subtype`（source-specific，可选）

短中文标识符，各 source 自行映射。不传返回该 `type` 下所有 subtype 的并集。

**`source=zhitu` 完整映射**：

| type | subtype | Zhitu type2 | 说明 |
|---|---|---|---|
| `industry` | `申万行业` | 0 | 一级行业分类 |
| `industry` | `申万二级` | 1 | 二级细分行业 |
| `industry` | `证监会行业` | 5 | 证监会分类标准 |
| `concept` | `热门概念` | 2 | 如 MSCI中国、区块链 |
| `concept` | `概念板块` | 3 | 如 融资融券、外资背景 |
| `concept` | `地域板块` | 4 | 如 江苏、广东、浙江 |
| `index` | `分类` | 6 | 通用分类 |
| `index` | `指数成分` | 7 | 指数成分股分类 |
| `index` | `大盘指数` | 9 | 大盘指数分类 |
| `special` | `风险警示` | 8 | ST 等风险警示 |
| `special` | `次新股` | 10 | 次新股分类 |
| `special` | `沪港通` | 11 | 沪港通标的 |
| `special` | `深港通` | 12 | 深港通标的 |

**`source=eastmoney`**：`subtype` 不支持——传入时返回 400 错误，只有 concept / industry 两层。

**`source=zzshare`**（后续）：plate_type 14=行业, 15=概念, 17=题材。

## 4. API 端点设计

### 4.1 `GET /api/v1/boards` —— 板块清单（含排名能力）

```
GET /api/v1/boards
  ?type=concept|industry|index|special   (必填)
  &source=eastmoney|zhitu|zzshare        (必填)
  &subtype=热门概念                        (可选, source-specific)
  &include_quote=true|false              (默认 false)
  &sort_by=change_pct|volume|amount|price (可选, 需 include_quote=true)
  &sort_order=asc|desc                   (默认 desc)
  &limit=20                              (可选, 默认全量)
```

**改动点**：
- `type` 从 `concept|industry` 扩展到 4 个值（breaking）
- `source` 改为必填（breaking）
- `subtype` 新增可选参数
- `sort_by` / `sort_order` / `limit` 新增（替代独立 ranking 端点）
- `source=zhitu` 时调用 `/hs/index/tree`，按 type/subtype 筛选叶子节点
- `source=eastmoney` 且 `include_quote=true` 时返回板块实时行情（排序/截断在路由层完成）

**Response**（不变）：
```json
{
  "data": [{ "code": "sw_mt", "name": "A股-申万行业-煤炭", "price": null, ... }],
  "source": "zhitu"
}
```

### 4.2 `GET /api/v1/boards/{board_code}/stocks` —— 板块成分股

```
GET /api/v1/boards/{board_code}/stocks
  ?source=eastmoney|zhitu|zzshare  (必填)
  &include_quote=true|false        (默认 false)
  &refresh=true|false              (默认 false)
```

**改动点**：
- `source` 改为必填（breaking）
- `source=eastmoney` → `EastMoneyFetcher.get_concept_board_stocks()` / `get_industry_board_stocks()`（从 `AkshareFetcher` 迁移）
- `source=zhitu` → `ZhituFetcher.get_board_stocks(board_code)` → `GET /hs/index/stock/{code}`

**Response**（不变）：
```json
{
  "board": { "code": "sw_mt", "name": "A股-申万行业-煤炭" },
  "stocks": [{ "code": "603798", "name": "康普顿", "price": null, ... }],
  "query_source": "zhitu",
  "data_source": "zhitu"
}
```

### 4.3 `GET /api/v1/stocks/{stock_code}/boards` —— 股票所属板块 **【新增】**

```
GET /api/v1/stocks/{stock_code}/boards
  ?source=zhitu                     (必填, 目前仅支持 zhitu)
  &type=concept|industry|index|special (可选, 筛选返回的板块类型)
  &subtype=热门概念                   (可选)
```

**实现**：
- `ZhituFetcher.get_stock_boards(stock_code)` → `GET /hs/index/index/{stock_code}`
- 返回数据中每条记录已含 `code`（板块代码）和 `name`（板块完整名称，如 "A股-申万行业-银行"）
- 路由层根据 `type` / `subtype` 筛选

**Response**：
```json
{
  "stock_code": "000001",
  "source": "zhitu",
  "data": [
    { "code": "sw_yx", "name": "A股-申万行业-银行", "type": "industry", "subtype": "申万行业" },
    { "code": "chgn_700532", "name": "A股-热门概念-MSCI中国", "type": "concept", "subtype": "热门概念" },
    { "code": "gn_rzrq", "name": "A股-概念板块-融资融券", "type": "concept", "subtype": "概念板块" }
  ]
}
```

**Response Model（新增）**：
```python
class StockBoardInfo(BaseModel):
    code: str       # 板块代码
    name: str       # 板块名称
    type: str       # concept / industry / index / special
    subtype: str    # 申万行业 / 热门概念 / ...

class StockBoardsResponse(BaseModel):
    stock_code: str
    source: str
    data: list[StockBoardInfo]
```

### 4.4 `GET /api/v1/boards/{board_code}/history` —— 板块 K 线 **【新增】**

```
GET /api/v1/boards/{board_code}/history
  ?source=zhitu|zzshare             (必填)
  &frequency=d|w|m                  (默认 d)
  &start_date=2026-01-01            (可选)
  &end_date=2026-06-24              (可选)
  &days=30                          (默认 30)
```

**实现**：
- **首次实现抛 `NotImplementedError`**，后续由各 fetcher 补充
- `source=zhitu`：当前文档中未发现板块级别 K 线 API（`/hs/history/` 是个股级别），需确认
- `source=zzshare`：`plate_kline` / `topic_kline` 接口可用（见 `docs/zzshare/01-kline.md`）

**Response**（复用 `KLineData` schema）：
```json
{
  "code": "sw_mt",
  "name": "A股-申万行业-煤炭",
  "source": "zhitu",
  "data": [{ "date": "2026-06-24", "open": 1000.0, "high": 1010.0, ... }]
}
```

## 5. Fetcher 改动

### 5.1 EastMoneyFetcher —— 新增 STOCK_BOARD

```python
supported_data_types |= DataCapability.STOCK_BOARD
```

新增方法（从 `AkshareFetcher` / `akshare/board.py` 迁移）：
- `get_all_concept_boards(source, include_quote)` — 调 `ak.stock_board_concept_name_em`
- `get_all_industry_boards(source, include_quote)` — 调 `ak.stock_board_industry_name_em`
- `get_concept_board_stocks(board_code, source, include_quote)` — 调 `ak.stock_board_concept_cons_em`
- `get_industry_board_stocks(board_code, source, include_quote)` — 调 `ak.stock_board_industry_cons_em`

> 注意：虽然底层调用仍通过 akshare，但方法归属变为 EastMoneyFetcher，语义正确。
> `source` 参数在 EastMoneyFetcher 内部忽略（没有其他下游分支）。

### 5.2 ZhituFetcher —— 新增 STOCK_BOARD

```python
supported_data_types |= DataCapability.STOCK_BOARD
```

新增方法：
- `get_board_tree(type, subtype)` → `GET /hs/index/tree`，按 type/subtype 筛选叶子节点，映射为 `[{code, name, type, subtype}] `
- `get_board_stocks(board_code)` → `GET /hs/index/stock/{code}`
- `get_stock_boards(stock_code)` → `GET /hs/index/index/{stock_code}`

### 5.3 AkshareFetcher —— 退役 board 方法

- 移除 `STOCK_BOARD` capability
- 移除 `get_all_concept_boards` / `get_all_industry_boards` / `get_concept_board_stocks` / `get_industry_board_stocks`
- `akshare/board.py` 中的 helper 函数迁移到 EastMoneyFetcher 模块或保留为共享工具

### 5.4 ZzshareFetcher（后续）

- 新增 fetcher，声明 `STOCK_BOARD`
- `plate_type` 映射：14→industry, 15→concept, 17→concept(subtype=题材板块)
- 方法：`get_board_list`（→ `plates_rank`）、`get_board_stocks`（→ `plates_stocks`）

## 6. 持久化层

`persistence/board.py` 的 SQLite schema 已有 `source` 列，缓存键为 `(code, source)`，**无需改动**。

Zhitu 的板块数据同样走 `stock_board` / `stock_board_stock` 表，`source=zhitu` 自然隔离。

## 7. 路由层改动

`stock_data/api/routes/boards.py` → 新增 `_router.py` 中的 `router` 注册：

- `list_boards` — 改造：type 扩展 + source 必填 + subtype/sort_by/sort_order/limit
- `get_board_stocks` — 改造：source 必填，使用 `_with_source` 路由
- `get_stock_boards` — 新增：`GET /stocks/{code}/boards`
- `get_board_history` — 新增：`GET /boards/{code}/history`

需要在 `stock_data/api/routes/stocks.py` 或 `boards.py` 中新增第 4.3 端点（放在 `boards.py` 或单独路由文件由实现决定）。

## 8. 新增/改动清单

| 文件 | 改动 |
|---|---|
| `stock_data/data_provider/base.py` | `type` 枚举值文档更新（如果需要） |
| `stock_data/data_provider/manager.py` | 新增 `_with_source()` 方法；board 方法改用 `_with_source` |
| `stock_data/data_provider/fetchers/eastmoney_fetcher.py` | 新增 `STOCK_BOARD` + 4 个 board 方法（从 akshare 迁移） |
| `stock_data/data_provider/fetchers/zhitu_fetcher.py` | 新增 `STOCK_BOARD` + 3 个 board 方法 |
| `stock_data/data_provider/fetchers/akshare/fetcher.py` | 移除 `STOCK_BOARD` + 4 个 board 方法 |
| `stock_data/data_provider/fetchers/akshare/board.py` | 迁移到 EastMoneyFetcher 或保留为共享工具 |
| `stock_data/data_provider/persistence/board.py` | 无需改动（已有 source 隔离） |
| `stock_data/api/routes/boards.py` | 重构现有端点 + 新增 2 个端点 |
| `stock_data/api/schemas.py` | 新增 `StockBoardInfo` / `StockBoardsResponse` |
| `stock_data/api/endpoint_meta.py` | 注册新端点元数据 |
| `tests/` | 新增 board source 路由单测 + Zhitu board mock 测试 |

## 9. 向后兼容

- `source` 改为必填是 **breaking change**（当前默认 `"eastmoney"`）
- `type` 新增 `index` / `special` 是 **向后兼容扩展**（旧值 `concept` / `industry` 继续有效）
- `BoardInfo` schema 保持不变，新字段通过 `include_quote` 可选注入
