# THS `get_stock_boards` 实现 — 设计规格

**日期**: 2026-07-04
**作者**: Claude (brainstorming-driven)
**状态**: 草案 — 待用户审阅

## 背景

`/stocks/{code}/boards` 端点需要支持 stock→boards 反向查询。当前实现：
- `EastMoneyFetcher.get_stock_boards`: ✅ 实现（`push2 slist/get` + 本地 `stock_board` 缓存覆盖 type）
- `ZhituFetcher.get_stock_boards`: ✅ 实现（智图 SDK）
- `ZzshareFetcher.get_stock_boards`: ❌ stub，返回 `None`（zzshare SDK 无 stock→boards 反查端点）
- `ThsFetcher.get_stock_boards`: ❌ 不存在

THS basic.10jqka.com.cn 提供原生 stock→concept 反查 API：

```
GET https://basic.10jqka.com.cn/fuyao/f10_stock_index/concept/v1/stock_concept_list
    ?code={stock_code}&market_id={17|33}[&simple=1]
```

由于 zzshare 的板块数据本身来自 THS（`plates_list` 上游 = THS），让 THS fetcher 实现此方法是去重 + 完整性双赢。

## 目标

1. **新增** `ThsFetcher.get_stock_boards` — 调用 basic.10jqka.com.cn stock_concept_list
2. **移除** `ZzshareFetcher.get_stock_boards` stub
3. **路由层** `/stocks/{code}/boards` 接受 `source=ths`（同时保留 `source=zzshare` alias → ths）
4. **持久化** `stock_board_membership` 写入 `source='ths'`；启用 cold-fill
5. 测试覆盖 + 回归通过

## 架构

### 数据流

```
Client GET /stocks/{code}/boards?source=zzshare
    ↓
api/routes/boards.py:_parse_stock_boards_source_csv("zzshare")
    → alias_map["zzshare"] = "ths"  → ["ths"]
    ↓
persistence/board.get_stock_memberships(code, sources=["ths"], cold_fill=true)
    ↓
[缓存 miss?] → manager.get_stock_boards(code, source="ths")
    ↓
ThsFetcher.get_stock_boards(code)
    ↓
GET basic.10jqka.com.cn/fuyao/.../stock_concept_list?code=...&market_id=...
    ↓
解析 → 写入 stock_board_membership(source='ths')
    ↓
重读 stock_board_membership → 返回 rows
```

### 文件改动一览

| 文件 | 改动 |
|---|---|
| `stock_data/data_provider/fetchers/zzshare_fetcher.py` | 删除 `get_stock_boards` 方法（641-647 行）|
| `stock_data/data_provider/fetchers/ths_fetcher.py` | 新增 `_THS_MARKET_ID_MAP`、`_STOCK_CONCEPT_LIST_URL`、`get_stock_boards` 方法 |
| `stock_data/data_provider/persistence/board.py` | `VALID_SUBTYPES_BY_SOURCE` 加 `"ths"`；新增 `_STOCK_BOARDS_VALID_SOURCES` / `_STOCK_BOARDS_SOURCE_ALIAS` / `normalize_stock_board_source`；`get_stock_memberships` cold-fill 循环加 `"ths"` |
| `stock_data/api/routes/boards.py` | 新增 `_parse_stock_boards_source_csv`（独立 helper，不复用 `_parse_source_csv`）；`get_stock_boards` 路由改用新 helper + 新 source 集；`source` Query 描述更新 |
| `tests/test_stock_boards_reverse_route.py` | 更新 2 个测试期望 + 1 个新测试 + 1 个删除 |
| `tests/test_zzshare_fetcher.py` | 删除 `test_zzshare_get_stock_boards_returns_none`（或改为属性存在性否定测试）|
| `tests/test_ths_fetcher.py`（或新文件） | 新增 3 个单元测试覆盖 `get_stock_boards` |

## 实现细节

### §1 — ThsFetcher.get_stock_boards

```python
# ths_fetcher.py 新增

_STOCK_CONCEPT_LIST_URL = (
    "https://basic.10jqka.com.cn/fuyao/f10_stock_index/concept/v1/stock_concept_list"
)

# market_id 映射（THS 内部 ID）
# 17 = 沪市 (sh), 33 = 深市 (sz), 8 = 北交所 (bj)
# 北交所暂未映射（端点可能不支持，留 TODO）
_THS_MARKET_ID_MAP: dict[str, str] = {
    "6": "17",  # 沪市主板 + 创业板代码段
    "9": "17",  # 沪市 B 股
    "0": "33",  # 深市主板 + 中小板
    "3": "33",  # 深市创业板
}


def get_stock_boards(self, stock_code: str, **kwargs) -> list[dict]:
    """THS concept membership via basic.10jqka.com.cn.

    Returns list[{code, name, type, subtype}] or [] on upstream empty / no mapping.

    - code = quote_code (885xxx), 与 zzshare board-list 同源, 缓存可 join
    - type = 'concept' (硬编码 — 端点本身是 stock_concept_list)
    - subtype = '同花顺概念' (与现有 VALID_SUBTYPES_BY_SOURCE 一致)
    """
    from ..utils.normalize import normalize_stock_code

    code = normalize_stock_code(stock_code)
    market_id = _THS_MARKET_ID_MAP.get(code[:1])
    if not market_id:
        logger.warning(
            f"[ThsFetcher] get_stock_boards: no market_id mapping for {code!r}; "
            f"北交所暂不支持"
        )
        return []
    try:
        payload = json_get(
            _STOCK_CONCEPT_LIST_URL,
            params={"code": code, "market_id": market_id, "simple": 1},
            headers={
                "Referer": "https://basic.10jqka.com.cn/astockpc/astockmain/index.html",
                "User-Agent": THS_UA,
            },
            timeout=10,
        )
    except Exception as e:
        raise DataFetchError(
            f"[ThsFetcher] stock_concept_list({code}) failed: {e}"
        ) from e
    rows = payload.get("data") or []
    return [
        {
            "code": str(r.get("quote_code", "")).strip(),
            "name": str(r.get("name", "")).strip(),
            "type": "concept",
            "subtype": "同花顺概念",
        }
        for r in rows
        if r.get("quote_code")
    ]
```

### §2 — Persistence 层改动

```python
# persistence/board.py

VALID_SUBTYPES_BY_SOURCE: dict[str, dict[str, set[str]]] = {
    "eastmoney": {...},  # unchanged
    "zhitu": {...},      # unchanged
    "zzshare": {...},    # unchanged (board-list 仍用)
    "ths": {              # NEW — stock-boards 专用, 仅 concept
        "concept": {"同花顺概念"},
    },
}

# stock-boards 专用 source 集合 + alias (仿照 _BOARD_HISTORY_VALID_SOURCES)
_STOCK_BOARDS_VALID_SOURCES: tuple[str, ...] = ("ths", "eastmoney", "zhitu")
_STOCK_BOARDS_SOURCE_ALIAS: dict[str, str] = {"zzshare": "ths"}


def normalize_stock_board_source(source: str) -> str:
    """Alias + validate source for stock-boards endpoint.

    Raises ValueError on unknown source (caller surfaces as 400).
    """
    s = _STOCK_BOARDS_SOURCE_ALIAS.get(source, source)
    if s not in _STOCK_BOARDS_VALID_SOURCES:
        raise ValueError(
            f"Unknown stock-boards source {source!r}. "
            f"Valid sources: {list(_STOCK_BOARDS_VALID_SOURCES)} "
            f"(alias 'zzshare' accepted)"
        )
    return s


# get_stock_memberships cold-fill 循环加 "ths"
def get_stock_memberships(...):
    ...
    if cold_fill and manager is not None:
        for cold_src in ("ths", "zhitu", "eastmoney"):  # ths 加首位
            ...
```

**注意**：`_validate_subtype`（已存在）会自动接受 `"ths"` + `("concept", "同花顺概念")` —— 不需改动。

### §3 — Route 层改动

```python
# api/routes/boards.py

# 独立 helper (不复用 _parse_source_csv — alias 方向相反)
def _parse_stock_boards_source_csv(raw: str | None) -> list[str]:
    """Parse ?source= for /stocks/{code}/boards — aliases zzshare → ths.

    与 _parse_source_csv (board-list 用, alias 方向是 ths→zzshare) 相反。
    CSV 解析核心逻辑 (split/strip/dedup) 重复 5 行, 不抽公共 helper
    (两个端点的 alias 方向/valid set/默认集合都不同, 强行复用 = 配置化函数)。
    """
    valid_set = _STOCK_BOARDS_VALID_SOURCES
    alias_map = _STOCK_BOARDS_SOURCE_ALIAS
    if not raw:
        return list(_STOCK_BOARDS_VALID_SOURCES)
    out: list[str] = []
    for s in raw.split(","):
        s = s.strip()
        if not s:
            continue
        s = alias_map.get(s, s)
        if s not in valid_set:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "invalid_source",
                    "message": (
                        f"Unknown stock-boards source {s!r}. "
                        f"Valid sources: {list(_STOCK_BOARDS_VALID_SOURCES)} "
                        f"(alias 'zzshare' accepted)"
                    ),
                },
            )
        if s not in out:
            out.append(s)
    return out


# get_stock_boards 路由改用新 helper
@router.get("/stocks/{stock_code}/boards", ...)
@endpoint_meta(
    summary="股票所属板块 (ths/eastmoney/zhitu, source=zzshare 别名 → ths)",
    markets=["csi"],
    capabilities=["STOCK_BOARD"],
    fetcher_method="get_stock_boards",
)
@map_errors
def get_stock_boards(
    stock_code: str = Path(...),
    source: str | None = Query(
        None,
        description=(
            "Comma-separated sources (e.g. 'ths,eastmoney,zhitu'). "
            "'zzshare' is accepted as alias for 'ths' (data is THS upstream). "
            "Omit for all valid sources."
        ),
    ),
    type: Literal["concept", "industry", "index", "special"] | None = Query(
        None, description="Filter by board type"
    ),
    subtype: str | None = Query(None, description="Filter by source-specific subtype"),
    cold_fill: bool = Query(False, ...),
) -> StockBoardsResponse:
    normalized_sources = _parse_stock_boards_source_csv(source)
    if type is not None and subtype is not None:
        for src in normalized_sources:
            stock_board_cache._validate_subtype(src, type, subtype)
    # 其余不变
    ...
```

### §4 — Manager 层

**无需改动**。ThsFetcher 已声明 `DataCapability.STOCK_BOARD`，`manager.get_stock_boards(source="ths")` 自动路由。

### §5 — 测试

#### 5.1 `tests/test_stock_boards_reverse_route.py`

| 测试 | 改动 |
|---|---|
| `test_ths_alias_accepted_in_csv` | 改期望：`["ths", "zhitu"]` (不再 alias 到 zzshare) |
| `test_no_source_aggregates_all` | 改期望：`{"ths", "eastmoney", "zhitu"}` (不再含 zzshare) |
| `test_ths_alias_single_source` | **删除** — ths 现在是 canonical，不再 alias |
| `test_zzshare_aliases_to_ths` | **新增** — `source=zzshare` → `["ths"]` |
| `test_ths_industry_filter_returns_400` | **新增** — `source=ths&type=industry` → 400 |

#### 5.2 `tests/test_zzshare_fetcher.py`

| 测试 | 改动 |
|---|---|
| `test_zzshare_get_stock_boards_returns_none` | **删除** (方法已不存在) |

#### 5.3 `tests/test_ths_fetcher.py`

| 测试 | 新增 |
|---|---|
| `test_get_stock_boards_returns_normalized_dicts` | mock json_get → 验证 URL/params/headers/响应解析 |
| `test_get_stock_boards_market_id_mapping` | 600519→17, 300740→33, 000001→33 |
| `test_get_stock_boards_empty_on_unknown_prefix` | 830xxx (北交所) → [] + json_get 未调用 |

## 兼容性策略

| 旧客户端调用 | 新行为 |
|---|---|
| `?source=ths` | ThsFetcher.get_stock_boards (新实现) |
| `?source=zzshare` | alias → ths → ThsFetcher.get_stock_boards |
| `?source=ths,eastmoney` | ths+eastmoney |
| `?source=eastmoney,zhitu` (省略 ths) | eastmoney+zhitu (不变) |
| `?source=` (空) | `ths, eastmoney, zhitu` (默认) |
| `?source=ths&type=industry` | 400 (ths 仅 concept) |

`/boards` 和 `/boards/{code}/stocks` 端点**完全不受影响**（继续用 `ths → zzshare` alias）。

## 风险 + 缓解

| 风险 | 缓解 |
|---|---|
| THS API 鉴权变化 / 反爬升级 | 与现有 ThsFetcher 共享 User-Agent；失败抛 DataFetchError → 路由层 503 |
| market_id 映射错误（端点对市场更敏感）| 写单元测试覆盖；THS 端点可能接受 0/通配符，失败时单测会立刻发现 |
| 北交所股票 (`4`/`8` 开头) 无映射 | 显式返回 `[]` + WARNING 日志；不在端点处 400；future: 添加 THS BJ 端点 |
| cold-fill 频次过高导致 THS 频控 | 复用现有 `DailyRefreshTracker` 模式：cold-fill 写入后下次走缓存；如需更细粒度再加 TTL |
| `source=zzshare` 误用（用户期望是 ZZShare 同名端点）| alias 错误消息明确提示 `'zzshare' accepted` |

## 非目标 (YAGNI)

- 不重构 `_parse_source_csv` 抽出共享 helper
- 不删除 `zzshare` source key 全局（`/boards` 端点仍需）
- 不支持北交所 THS concept API（无对应端点；future 单独任务）
- 不实现 THS industry / special 反查（端点不支持）
- 不加指标/缓存层（route 层已有 TTLCache）
- 不做 DB schema 迁移（新 source 写入新行；旧 `source='zzshare'` 行保留）

## 后续可能任务

- `source=zzshare` 全局弃用（标记 deprecation）
- 北交所 THS concept 端点调研
- THS industry / region 反查 API（如果有）
- 通用 `get_stock_boards` 结果去重（ths + eastmoney + zhitu 三方合并去重）