# Board API 重构实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 重构板块 API：让 `source` 参数必填并真正驱动 fetcher 路由；将板块方法从 `AkshareFetcher` 迁移到 `EastMoneyFetcher`；让 `ZhituFetcher` 承接自己的板块方法；新增"股票所属板块"和"板块 K 线"两个端点。

**Architecture:** Manager 层新增 `_with_source()` 路由原语（按 fetcher name 定位，不做 failover）。每个真实数据源（EastMoney/Zhitu）独立承接 board 方法。API 引入 `type`（4 大类）+ `subtype`（source-specific）的双层分类体系。

**Tech Stack:** Python 3.12+, FastAPI, Pydantic v2, SQLite (via persistence layer), pytest

---

## 文件结构

### 新增文件

- `stock_data/data_provider/fetchers/eastmoney/board.py` — 从 akshare 迁移的 EastMoney board helper
- `tests/test_board_source_routing.py` — Manager `_with_source` 单测
- `tests/test_eastmoney_fetcher_board.py` — EastMoneyFetcher board 方法单测
- `tests/test_zhitu_fetcher_board.py` — ZhituFetcher board 方法单测
- `tests/test_boards_api.py` — board API 端点集成测试

### 修改文件

- `stock_data/data_provider/manager.py` — 新增 `_with_source()` 方法；改写 4 个 board 公开方法
- `stock_data/data_provider/fetchers/eastmoney_fetcher.py` — 新增 STOCK_BOARD capability + 4 个 board 方法
- `stock_data/data_provider/fetchers/zhitu_fetcher.py` — 新增 STOCK_BOARD capability + 3 个 board 方法
- `stock_data/data_provider/fetchers/akshare/fetcher.py` — 移除 STOCK_BOARD capability + 4 个 board 方法
- `stock_data/data_provider/fetchers/akshare/board.py` — 标记 deprecated 或移除（内容已迁移）
- `stock_data/data_provider/persistence/board.py` — 新增 `_validate_subtype()` 辅助函数
- `stock_data/api/routes/boards.py` — 重构现有端点 + 新增 2 个端点
- `stock_data/api/schemas.py` — 新增 `StockBoardInfo` / `StockBoardsResponse`

---

## Task 1: Manager 新增 `_with_source()` 路由原语

**Files:**
- Modify: `stock_data/data_provider/manager.py:77-180`（在 `_filter_by_capability` 后新增 `_with_source`）
- Test: `tests/test_board_source_routing.py`（新建）

- [ ] **Step 1: 写失败的测试 — `_with_source` 找到匹配的 fetcher 并调用**

```python
# tests/test_board_source_routing.py
"""Tests for DataFetcherManager._with_source() routing primitive."""
from unittest.mock import MagicMock

import pytest

from stock_data.data_provider.base import DataCapability, DataFetchError
from stock_data.data_provider.manager import DataFetcherManager


class FakeFetcher:
    """Minimal fetcher stub for source-routing tests."""
    def __init__(self, name: str, capabilities: DataCapability, markets: set[str]):
        self.name = name
        self.supported_data_types = capabilities
        self.supported_markets = markets


def test_with_source_routes_to_matching_fetcher():
    """_with_source finds fetcher by name.lower() match and invokes call()."""
    eastmoney = FakeFetcher(
        "EastMoneyFetcher",
        DataCapability.STOCK_BOARD,
        {"csi"},
    )
    manager = DataFetcherManager([eastmoney])
    captured = {}

    def call(f):
        captured["fetcher"] = f
        return [{"code": "BK0001", "name": "测试板块"}]

    result = manager._with_source(
        source="eastmoney",
        capability=DataCapability.STOCK_BOARD,
        market="csi",
        op_label="test boards",
        call=call,
    )
    assert captured["fetcher"] is eastmoney
    assert result == [{"code": "BK0001", "name": "测试板块"}]


def test_with_source_raises_when_no_fetcher_matches():
    """_with_source raises ValueError when no fetcher matches source name."""
    manager = DataFetcherManager([])

    with pytest.raises(ValueError, match="No fetcher named 'nonexistent'"):
        manager._with_source(
            source="nonexistent",
            capability=DataCapability.STOCK_BOARD,
            market="csi",
            op_label="test",
            call=lambda f: None,
        )


def test_with_source_raises_when_fetcher_lacks_capability():
    """_with_source raises ValueError when matched fetcher lacks capability."""
    no_board = FakeFetcher(
        "EastMoneyFetcher",
        DataCapability(0),  # empty
        {"csi"},
    )
    manager = DataFetcherManager([no_board])

    with pytest.raises(ValueError, match="does not declare STOCK_BOARD"):
        manager._with_source(
            source="eastmoney",
            capability=DataCapability.STOCK_BOARD,
            market="csi",
            op_label="test",
            call=lambda f: None,
        )


def test_with_source_does_not_failover():
    """_with_source propagates exceptions without trying other fetchers."""
    eastmoney = FakeFetcher(
        "EastMoneyFetcher",
        DataCapability.STOCK_BOARD,
        {"csi"},
    )
    manager = DataFetcherManager([eastmoney])
    call_count = {"n": 0}

    def failing_call(f):
        call_count["n"] += 1
        raise DataFetchError("upstream timeout")

    with pytest.raises(DataFetchError, match="upstream timeout"):
        manager._with_source(
            source="eastmoney",
            capability=DataCapability.STOCK_BOARD,
            market="csi",
            op_label="test",
            call=failing_call,
        )
    assert call_count["n"] == 1  # not retried on other fetchers


def test_with_source_matches_case_insensitive():
    """source='EastMoney' should still find fetcher named 'EastMoneyFetcher'."""
    eastmoney = FakeFetcher(
        "EastMoneyFetcher",
        DataCapability.STOCK_BOARD,
        {"csi"},
    )
    manager = DataFetcherManager([eastmoney])

    result = manager._with_source(
        source="EastMoney",
        capability=DataCapability.STOCK_BOARD,
        market="csi",
        op_label="test",
        call=lambda f: [{"ok": True}],
    )
    assert result == [{"ok": True}]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_board_source_routing.py -v`
Expected: FAIL with `AttributeError: 'DataFetcherManager' object has no attribute '_with_source'`

- [ ] **Step 3: 实现 `_with_source` 方法**

在 `stock_data/data_provider/manager.py` 的 `_filter_by_capability` 方法后（约第 96 行后）新增：

```python
    def _with_source(
        self,
        source: str,
        capability: DataCapability,
        market: str,
        op_label: str,
        call: Callable[[BaseFetcher], T],
    ) -> T:
        """Route to a single fetcher by source name; no failover.

        Args:
            source: fetcher name (case-insensitive), e.g. ``"eastmoney"``,
                ``"zhitu"``. Matched against ``fetcher.name.lower()``.
            capability: required DataCapability flag (validated but not used for routing).
            market: market tag (csi/hk/us).
            op_label: short label for log messages.
            call: fetcher-bound function whose return value is the result.

        Returns:
            The return value of ``call(fetcher)``.

        Raises:
            ValueError: no fetcher named ``source`` exists, or the matched
                fetcher does not declare ``capability`` or does not support
                ``market``.
            DataFetchError: ``call(fetcher)`` raised an exception. The error
                is NOT propagated as a failover — it is re-raised as-is.
        """
        target_name = source.lower()
        with self._lock:
            for f in self._fetchers:
                if f.name.lower() != target_name:
                    continue
                if market not in f.supported_markets:
                    raise ValueError(
                        f"Fetcher {f.name} does not support market '{market}'"
                    )
                if capability not in f.supported_data_types:
                    raise ValueError(
                        f"Fetcher {f.name} does not declare {capability.name}"
                    )
                fetcher = f
                break
            else:
                raise ValueError(
                    f"No fetcher named '{source}' "
                    f"(registered: {[f.name for f in self._fetchers]})"
                )

        logger.info(f"[Manager] {fetcher.name} {op_label} (source={source})")
        return call(fetcher)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/test_board_source_routing.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: 提交**

```bash
git add stock_data/data_provider/manager.py tests/test_board_source_routing.py
git commit -m "feat(manager): add _with_source routing primitive for explicit source routing"
```

---

## Task 2: Persistence 层新增 subtype 校验

**Files:**
- Modify: `stock_data/data_provider/persistence/board.py:1-130`（在文件顶部新增 `_validate_subtype`）
- Test: `tests/test_board_persistence_subtype.py`（新建）

- [ ] **Step 1: 写失败的测试 — subtype 校验**

```python
# tests/test_board_persistence_subtype.py
"""Tests for board persistence layer subtype validation."""
import pytest

from stock_data.data_provider.persistence.board import _validate_subtype, VALID_SUBTYPES_BY_SOURCE


def test_valid_subtypes_for_zhitu_industry():
    _validate_subtype("zhitu", "industry", "申万行业")
    _validate_subtype("zhitu", "industry", "申万二级")
    _validate_subtype("zhitu", "industry", "证监会行业")


def test_valid_subtypes_for_zhitu_concept():
    _validate_subtype("zhitu", "concept", "热门概念")
    _validate_subtype("zhitu", "concept", "概念板块")
    _validate_subtype("zhitu", "concept", "地域板块")


def test_valid_subtypes_for_zhitu_index():
    _validate_subtype("zhitu", "index", "分类")
    _validate_subtype("zhitu", "index", "指数成分")
    _validate_subtype("zhitu", "index", "大盘指数")


def test_valid_subtypes_for_zhitu_special():
    _validate_subtype("zhitu", "special", "风险警示")
    _validate_subtype("zhitu", "special", "次新股")
    _validate_subtype("zhitu", "special", "沪港通")
    _validate_subtype("zhitu", "special", "深港通")


def test_invalid_subtype_for_zhitu_raises():
    with pytest.raises(ValueError, match="Invalid subtype '不存在'"):
        _validate_subtype("zhitu", "concept", "不存在")


def test_subtype_for_zhitu_with_wrong_type_raises():
    with pytest.raises(ValueError, match="Invalid subtype '申万行业' for type='concept'"):
        _validate_subtype("zhitu", "concept", "申万行业")


def test_eastmoney_subtypes_mirror_type():
    _validate_subtype("eastmoney", "concept", "concept")
    _validate_subtype("eastmoney", "industry", "industry")


def test_eastmoney_invalid_subtype_raises():
    with pytest.raises(ValueError, match="Invalid subtype '热门概念'"):
        _validate_subtype("eastmoney", "concept", "热门概念")


def test_none_subtype_always_valid():
    """Subtype is optional — None means 'return all subtypes for this type'."""
    _validate_subtype("zhitu", "concept", None)
    _validate_subtype("eastmoney", "industry", None)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_board_persistence_subtype.py -v`
Expected: FAIL with `ImportError: cannot import name '_validate_subtype'`

- [ ] **Step 3: 实现 subtype 校验**

在 `stock_data/data_provider/persistence/board.py` 第 17 行（`logger = logging.getLogger(__name__)` 后）新增：

```python
# Subtype 合法值表：source → type → {subtype 集合}
# EastMoney 没有更细分类，subtype 与 type 镜像
# Zhitu 的 subtype 来自 /hs/index/tree 的 type2 字段映射
VALID_SUBTYPES_BY_SOURCE: dict[str, dict[str, set[str]]] = {
    "eastmoney": {
        "concept": {"concept"},
        "industry": {"industry"},
        "index": {"index"},
        "special": {"special"},
    },
    "zhitu": {
        "industry": {"申万行业", "申万二级", "证监会行业"},
        "concept": {"热门概念", "概念板块", "地域板块"},
        "index": {"分类", "指数成分", "大盘指数"},
        "special": {"风险警示", "次新股", "沪港通", "深港通"},
    },
}


def _validate_subtype(source: str, board_type: str, subtype: str | None) -> None:
    """Validate subtype against the source's declared subtype set.

    Args:
        source: data source name (e.g. ``"zhitu"``).
        board_type: one of ``concept / industry / index / special``.
        subtype: optional subtype name; ``None`` means "all subtypes".

    Raises:
        ValueError: source unknown, type invalid for source, or subtype
            not in the source's declared subtype set. Error message lists
            the valid subtypes for the source/type pair.
    """
    if subtype is None:
        return
    source_table = VALID_SUBTYPES_BY_SOURCE.get(source)
    if source_table is None:
        raise ValueError(
            f"Unknown source '{source}'. "
            f"Known sources: {sorted(VALID_SUBTYPES_BY_SOURCE.keys())}"
        )
    valid_set = source_table.get(board_type)
    if valid_set is None:
        raise ValueError(
            f"Invalid type '{board_type}' for source '{source}'. "
            f"Valid types: {sorted(source_table.keys())}"
        )
    if subtype not in valid_set:
        raise ValueError(
            f"Invalid subtype '{subtype}' for type='{board_type}' "
            f"source='{source}'. "
            f"Valid subtypes: {sorted(valid_set)}"
        )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/test_board_persistence_subtype.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: 提交**

```bash
git add stock_data/data_provider/persistence/board.py tests/test_board_persistence_subtype.py
git commit -m "feat(persistence): add subtype validation table and helper"
```

---

## Task 3: EastMoneyFetcher 新增 STOCK_BOARD 方法（从 akshare 迁移）

**Files:**
- Create: `stock_data/data_provider/fetchers/eastmoney/board.py`（迁移自 `akshare/board.py`）
- Modify: `stock_data/data_provider/fetchers/eastmoney_fetcher.py`（新增 import + 4 个方法 + capability flag）
- Test: `tests/test_eastmoney_fetcher_board.py`（新建）

- [ ] **Step 1: 写失败的测试 — EastMoneyFetcher.get_all_concept_boards 调用 akshare EM API**

```python
# tests/test_eastmoney_fetcher_board.py
"""Tests for EastMoneyFetcher board methods (migrated from AkshareFetcher)."""
from unittest.mock import patch, MagicMock
import pandas as pd
import pytest

from stock_data.data_provider.fetchers.eastmoney_fetcher import EastMoneyFetcher


def _make_em_board_df(rows: list[dict]) -> pd.DataFrame:
    """Build a minimal akshare-em-style board DataFrame."""
    return pd.DataFrame(rows)


@patch("stock_data.data_provider.fetchers.eastmoney.board._AKSHARE")
def test_get_all_concept_boards_parses_em_response(mock_ak):
    """Returns list of {code, name} dicts from akshare concept board API."""
    mock_ak.stock_board_concept_name_em.return_value = _make_em_board_df([
        {"板块代码": "BK0001", "板块名称": "测试概念1"},
        {"板块代码": "BK0002", "板块名称": "测试概念2"},
    ])
    fetcher = EastMoneyFetcher()
    boards = fetcher.get_all_concept_boards(source="eastmoney", include_quote=False)
    assert boards == [
        {"code": "BK0001", "name": "测试概念1"},
        {"code": "BK0002", "name": "测试概念2"},
    ]


@patch("stock_data.data_provider.fetchers.eastmoney.board._AKSHARE")
def test_get_all_industry_boards_parses_em_response(mock_ak):
    mock_ak.stock_board_industry_name_em.return_value = _make_em_board_df([
        {"板块代码": "BK1001", "板块名称": "测试行业1"},
    ])
    fetcher = EastMoneyFetcher()
    boards = fetcher.get_all_industry_boards(source="eastmoney", include_quote=False)
    assert boards == [{"code": "BK1001", "name": "测试行业1"}]


@patch("stock_data.data_provider.fetchers.eastmoney.board._AKSHARE")
def test_get_concept_board_stocks_parses_em_response(mock_ak):
    mock_ak.stock_board_concept_cons_em.return_value = _make_em_board_df([
        {"代码": "600519", "名称": "贵州茅台"},
        {"代码": "000001", "名称": "平安银行"},
    ])
    fetcher = EastMoneyFetcher()
    stocks = fetcher.get_concept_board_stocks(
        "BK0001", source="eastmoney", include_quote=False
    )
    assert stocks == [
        {"stock_code": "600519", "stock_name": "贵州茅台"},
        {"stock_code": "000001", "stock_name": "平安银行"},
    ]


@patch("stock_data.data_provider.fetchers.eastmoney.board._AKSHARE")
def test_get_industry_board_stocks_parses_em_response(mock_ak):
    mock_ak.stock_board_industry_cons_em.return_value = _make_em_board_df([
        {"代码": "600519", "名称": "贵州茅台"},
    ])
    fetcher = EastMoneyFetcher()
    stocks = fetcher.get_industry_board_stocks(
        "BK1001", source="eastmoney", include_quote=False
    )
    assert stocks == [{"stock_code": "600519", "stock_name": "贵州茅台"}]


def test_eastmoney_fetcher_declares_stock_board_capability():
    """After this task, EastMoneyFetcher must declare STOCK_BOARD."""
    from stock_data.data_provider.base import DataCapability
    assert DataCapability.STOCK_BOARD in EastMoneyFetcher.supported_data_types
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_eastmoney_fetcher_board.py -v`
Expected: FAIL with `ImportError` (module `eastmoney.board` doesn't exist yet) or `AttributeError` on `get_all_concept_boards`.

- [ ] **Step 3: 创建 eastmoney/board.py helper 模块**

新建 `stock_data/data_provider/fetchers/eastmoney/board.py`：

```python
"""Board (concept/industry) helpers for EastMoneyFetcher.

Migrated from stock_data.data_provider.fetchers.akshare.board.py.
The akshare EM APIs (e.g. ``ak.stock_board_concept_name_em``) are the
canonical EastMoney board endpoints — they're exposed through akshare
but originate from EastMoney's public board pages.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

# Lazy import — akshare is heavyweight and not required by tests using mocks.
_AKSHARE = None
def _get_ak():
    global _AKSHARE
    if _AKSHARE is None:
        import akshare as ak
        _AKSHARE = ak
    return _AKSHARE


_BOARD_LIST_QUOTE_COLS: dict[str, str] = {
    "price": "最新价",
    "change_pct": "涨跌幅",
    "change_amount": "涨跌额",
    "volume": "成交量",
    "amount": "成交额",
    "turnover_rate": "换手率",
    "total_mv": "总市值",
    "up_count": "上涨家数",
    "down_count": "下跌家数",
    "leading_stock": "领涨股票",
    "leading_stock_pct": "领涨股票-涨跌幅",
}

_BOARD_STOCK_QUOTE_COLS: dict[str, str] = {
    "price": "最新价",
    "change_pct": "涨跌幅",
    "change_amount": "涨跌额",
    "volume": "成交量",
    "amount": "成交额",
    "turnover_rate": "换手率",
    "pe_ratio": "市盈率-动态",
    "pb_ratio": "市净率",
    "high": "最高",
    "low": "最低",
    "open": "今开",
    "pre_close": "昨收",
}


def fetch_board_list(
    ak_func: Callable[..., Any],
    include_quote: bool = False,
    *,
    fetcher_label: str = "EastMoneyFetcher",
) -> list[dict[str, Any]]:
    """Fetch a board list from akshare (EastMoney backend)."""
    try:
        df = ak_func()
        result: list[dict[str, Any]] = []
        if df is None or df.empty:
            return result

        for _, row in df.iterrows():
            code = str(row.get("板块代码", "")).strip()
            name = str(row.get("板块名称", "")).strip()
            if not code:
                continue
            board: dict[str, Any] = {"code": code, "name": name}
            if include_quote:
                for out_key, src_col in _BOARD_LIST_QUOTE_COLS.items():
                    board[out_key] = row.get(src_col)
            result.append(board)
        return result

    except Exception:
        logger.warning(
            f"[{fetcher_label}] fetch_board_list failed", exc_info=True
        )
        return []


def fetch_board_stocks(
    ak_func: Callable[..., Any],
    board_code: str,
    include_quote: bool = False,
    *,
    fallback_enricher: Callable[[str], dict[str, Any] | None] | None = None,
    fetcher_label: str = "EastMoneyFetcher",
) -> list[dict[str, Any]]:
    """Fetch stocks belonging to a concept or industry board (EastMoney)."""
    try:
        df = ak_func(symbol=board_code)
        result: list[dict[str, Any]] = []
        if df is None or df.empty:
            return result

        for _, row in df.iterrows():
            code = str(row.get("代码", "")).strip()
            name = str(row.get("名称", "")).strip()
            if not code:
                continue
            stock: dict[str, Any] = {"stock_code": code, "stock_name": name}
            if include_quote:
                for out_key, src_col in _BOARD_STOCK_QUOTE_COLS.items():
                    stock[out_key] = row.get(src_col)
            result.append(stock)
        return result

    except Exception:
        logger.warning(
            f"[{fetcher_label}] fetch_board_stocks({board_code}) failed",
            exc_info=True,
        )
        if not include_quote or fallback_enricher is None:
            return []

        try:
            stocks = fetch_board_stocks(
                ak_func,
                board_code,
                include_quote=False,
                fetcher_label=fetcher_label,
            )
        except Exception:
            return []

        for stock in stocks:
            enriched = fallback_enricher(stock["stock_code"])
            if enriched:
                stock.update(enriched)
        return stocks


def get_ak():
    """Public accessor for the lazy-loaded akshare module (for tests/mocks)."""
    return _get_ak()
```

- [ ] **Step 4: 修改 EastMoneyFetcher，新增 capability 和 4 个方法**

在 `stock_data/data_provider/fetchers/eastmoney_fetcher.py` 顶部新增 import：

```python
from .eastmoney.board import fetch_board_list, fetch_board_stocks, get_ak as _ak_module
```

修改 `supported_data_types`：

```python
    supported_data_types = (
        DataCapability.DRAGON_TIGER
        | DataCapability.MARGIN_TRADING
        | DataCapability.BLOCK_TRADE
        | DataCapability.HOLDER_NUM
        | DataCapability.DIVIDEND
        | DataCapability.FUND_FLOW
        | DataCapability.RESEARCH_REPORT
        | DataCapability.NEWS_FLASH
        | DataCapability.NEWS_SEARCH
        | DataCapability.STOCK_BOARD  # NEW
    )
```

在文件中新增 4 个方法：

```python
    def get_all_concept_boards(
        self, source: str = "eastmoney", include_quote: bool = False
    ) -> list[dict]:
        """Get all concept boards (EastMoney via akshare EM API)."""
        ak = _ak_module()
        return fetch_board_list(
            ak.stock_board_concept_name_em,
            include_quote=include_quote,
            fetcher_label=self.name,
        )

    def get_all_industry_boards(
        self, source: str = "eastmoney", include_quote: bool = False
    ) -> list[dict]:
        """Get all industry boards (EastMoney via akshare EM API)."""
        ak = _ak_module()
        return fetch_board_list(
            ak.stock_board_industry_name_em,
            include_quote=include_quote,
            fetcher_label=self.name,
        )

    def get_concept_board_stocks(
        self, board_code: str, source: str = "eastmoney", include_quote: bool = False
    ) -> list[dict]:
        """Get stocks within a concept board (EastMoney via akshare EM API)."""
        ak = _ak_module()
        return fetch_board_stocks(
            ak.stock_board_concept_cons_em,
            board_code,
            include_quote=include_quote,
            fallback_enricher=self._enrich_stock_from_realtime,
            fetcher_label=self.name,
        )

    def get_industry_board_stocks(
        self, board_code: str, source: str = "eastmoney", include_quote: bool = False
    ) -> list[dict]:
        """Get stocks within an industry board (EastMoney via akshare EM API)."""
        ak = _ak_module()
        return fetch_board_stocks(
            ak.stock_board_industry_cons_em,
            board_code,
            include_quote=include_quote,
            fallback_enricher=self._enrich_stock_from_realtime,
            fetcher_label=self.name,
        )

    def _enrich_stock_from_realtime(self, stock_code: str) -> dict | None:
        """Enrich a stock dict with realtime quote fields via akshare EM API."""
        try:
            import akshare as ak
            df = ak.stock_zh_a_spot_em()
            if df is None or df.empty:
                return None
            match = df[df["代码"] == stock_code]
            if match.empty:
                return None
            row = match.iloc[0]
            return {
                "price": row.get("最新价"),
                "change_pct": row.get("涨跌幅"),
                "change_amount": row.get("涨跌额"),
                "volume": row.get("成交量"),
                "amount": row.get("成交额"),
                "turnover_rate": row.get("换手率"),
                "pe_ratio": row.get("市盈率-动态"),
                "pb_ratio": row.get("市净率"),
            }
        except Exception:
            logger.warning(
                f"[{self.name}] _enrich_stock_from_realtime failed for {stock_code}",
                exc_info=True,
            )
            return None
```

- [ ] **Step 5: 运行测试确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/test_eastmoney_fetcher_board.py -v`
Expected: PASS (5 tests)

- [ ] **Step 6: 提交**

```bash
git add stock_data/data_provider/fetchers/eastmoney/board.py stock_data/data_provider/fetchers/eastmoney_fetcher.py tests/test_eastmoney_fetcher_board.py
git commit -m "feat(eastmoney): migrate STOCK_BOARD from AkshareFetcher with akshare EM backend"
```

---

## Task 4: ZhituFetcher 新增 STOCK_BOARD 方法

**Files:**
- Modify: `stock_data/data_provider/fetchers/zhitu_fetcher.py`（新增 capability + 3 个方法）
- Test: `tests/test_zhitu_fetcher_board.py`（新建）

- [ ] **Step 1: 写失败的测试 — ZhituFetcher 3 个 board 方法**

```python
# tests/test_zhitu_fetcher_board.py
"""Tests for ZhituFetcher board methods."""
from unittest.mock import patch, MagicMock
import pytest

from stock_data.data_provider.base import DataCapability
from stock_data.data_provider.fetchers.zhitu_fetcher import ZhituFetcher


def test_zhitu_fetcher_declares_stock_board_capability():
    assert DataCapability.STOCK_BOARD in ZhituFetcher.supported_data_types


@patch("stock_data.data_provider.fetchers.zhitu_fetcher.requests.get")
def test_get_board_tree_filters_by_type_and_subtype(mock_get):
    """Returns leaves matching requested type/subtype from /hs/index/tree."""
    mock_response = MagicMock()
    mock_response.json.return_value = [
        # industry / 申万行业
        {"name": "A股-申万行业-煤炭", "code": "sw_mt", "type1": 0, "type2": 0,
         "level": 2, "pcode": "swhy", "pname": "A股-申万行业", "isleaf": 1},
        # industry / 证监会行业
        {"name": "A股-证监会行业-金融业", "code": "csrc_jr", "type1": 0, "type2": 5,
         "level": 2, "pcode": "csrc", "pname": "A股-证监会行业", "isleaf": 1},
        # concept / 热门概念
        {"name": "A股-热门概念-区块链", "code": "chgn_700231", "type1": 0, "type2": 2,
         "level": 2, "pcode": "chgn", "pname": "A股-热门概念", "isleaf": 1},
        # index / 大盘指数
        {"name": "A股-大盘指数-沪深300", "code": "idx_hs300", "type1": 0, "type2": 9,
         "level": 2, "pcode": "idx", "pname": "A股-大盘指数", "isleaf": 1},
    ]
    mock_response.raise_for_status = MagicMock()
    mock_get.return_value = mock_response

    fetcher = ZhituFetcher.__new__(ZhituFetcher)
    fetcher._token = "test_token"
    fetcher.is_available = lambda: True

    boards = fetcher.get_board_tree(board_type="industry", subtype="申万行业")
    assert boards == [
        {"code": "sw_mt", "name": "A股-申万行业-煤炭",
         "type": "industry", "subtype": "申万行业"}
    ]


@patch("stock_data.data_provider.fetchers.zhitu_fetcher.requests.get")
def test_get_board_tree_returns_all_subtypes_when_none(mock_get):
    """When subtype is None, returns leaves across all subtypes for the type."""
    mock_response = MagicMock()
    mock_response.json.return_value = [
        {"name": "A股-申万行业-煤炭", "code": "sw_mt", "type1": 0, "type2": 0,
         "level": 2, "pcode": "swhy", "pname": "A股-申万行业", "isleaf": 1},
        {"name": "A股-证监会行业-金融业", "code": "csrc_jr", "type1": 0, "type2": 5,
         "level": 2, "pcode": "csrc", "pname": "A股-证监会行业", "isleaf": 1},
    ]
    mock_response.raise_for_status = MagicMock()
    mock_get.return_value = mock_response

    fetcher = ZhituFetcher.__new__(ZhituFetcher)
    fetcher._token = "test_token"
    fetcher.is_available = lambda: True

    boards = fetcher.get_board_tree(board_type="industry", subtype=None)
    assert len(boards) == 2
    codes = {b["code"] for b in boards}
    assert codes == {"sw_mt", "csrc_jr"}


@patch("stock_data.data_provider.fetchers.zhitu_fetcher.requests.get")
def test_get_board_stocks_calls_index_stock_endpoint(mock_get):
    """Returns stocks belonging to a Zhitu board via /hs/index/stock/{code}."""
    mock_response = MagicMock()
    mock_response.json.return_value = [
        {"dm": "920088", "mc": "科力股份", "jys": "bj"},
        {"dm": "603798", "mc": "康普顿", "jys": "sh"},
    ]
    mock_response.raise_for_status = MagicMock()
    mock_get.return_value = mock_response

    fetcher = ZhituFetcher.__new__(ZhituFetcher)
    fetcher._token = "test_token"
    fetcher.is_available = lambda: True

    stocks = fetcher.get_board_stocks("sw_sysh")
    assert stocks == [
        {"stock_code": "920088", "stock_name": "科力股份", "exchange": "bj"},
        {"stock_code": "603798", "stock_name": "康普顿", "exchange": "sh"},
    ]


@patch("stock_data.data_provider.fetchers.zhitu_fetcher.requests.get")
def test_get_stock_boards_calls_index_index_endpoint(mock_get):
    """Returns boards a stock belongs to via /hs/index/index/{stock_code}."""
    mock_response = MagicMock()
    mock_response.json.return_value = [
        {"code": "sw_yx", "name": "A股-申万行业-银行"},
        {"code": "chgn_700532", "name": "A股-热门概念-MSCI中国"},
        {"code": "gn_rzrq", "name": "A股-概念板块-融资融券"},
    ]
    mock_response.raise_for_status = MagicMock()
    mock_get.return_value = mock_response

    fetcher = ZhituFetcher.__new__(ZhituFetcher)
    fetcher._token = "test_token"
    fetcher.is_available = lambda: True

    boards = fetcher.get_stock_boards("000001")
    assert boards == [
        {"code": "sw_yx", "name": "A股-申万行业-银行",
         "type": "industry", "subtype": "申万行业"},
        {"code": "chgn_700532", "name": "A股-热门概念-MSCI中国",
         "type": "concept", "subtype": "热门概念"},
        {"code": "gn_rzrq", "name": "A股-概念板块-融资融券",
         "type": "concept", "subtype": "概念板块"},
    ]


def test_get_stock_boards_returns_none_when_token_missing():
    """get_stock_boards returns None when ZHITU_TOKEN is not configured."""
    fetcher = ZhituFetcher.__new__(ZhituFetcher)
    fetcher._token = ""
    assert fetcher.get_stock_boards("000001") is None


def test_get_board_history_raises_not_implemented():
    """Board K-line is unimplemented for Zhitu (no upstream board K-line API)."""
    fetcher = ZhituFetcher.__new__(ZhituFetcher)
    fetcher._token = "test_token"
    fetcher.is_available = lambda: True
    with pytest.raises(NotImplementedError, match="board K-line"):
        fetcher.get_board_history("sw_mt", frequency="d", days=30)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_zhitu_fetcher_board.py -v`
Expected: FAIL (capability not declared / methods not exist)

- [ ] **Step 3: 实现 ZhituFetcher 3 个 board 方法**

在 `stock_data/data_provider/fetchers/zhitu_fetcher.py` 顶部新增常量：

```python
# Zhitu /hs/index/tree type2 → (type, subtype) 映射
# 用于把上游 type2 数字翻译成本项目统一分类
ZHITU_TYPE2_MAPPING: dict[int, tuple[str, str]] = {
    0: ("industry", "申万行业"),
    1: ("industry", "申万二级"),
    2: ("concept", "热门概念"),
    3: ("concept", "概念板块"),
    4: ("concept", "地域板块"),
    5: ("industry", "证监会行业"),
    6: ("index", "分类"),
    7: ("index", "指数成分"),
    8: ("special", "风险警示"),
    9: ("index", "大盘指数"),
    10: ("special", "次新股"),
    11: ("special", "沪港通"),
    12: ("special", "深港通"),
}

# type → 合法 subtype 集合（与 persistence/board.py 保持同步）
ZHITU_SUBTYPES_BY_TYPE: dict[str, set[str]] = {
    "industry": {"申万行业", "申万二级", "证监会行业"},
    "concept": {"热门概念", "概念板块", "地域板块"},
    "index": {"分类", "指数成分", "大盘指数"},
    "special": {"风险警示", "次新股", "沪港通", "深港通"},
}
```

修改 `supported_data_types`：

```python
    supported_data_types = (
        DataCapability.REALTIME_QUOTE
        | DataCapability.STOCK_ZT_POOL
        | DataCapability.STOCK_INFO
        | DataCapability.HISTORICAL_MIN
        | DataCapability.STOCK_LIST
        | DataCapability.STOCK_BOARD  # NEW
    )
```

在文件末尾新增 4 个方法：

```python
    # ---------- board methods ----------

    def _fetch_board_tree(self) -> list[dict] | None:
        """Fetch raw /hs/index/tree response. Returns list of leaves or None."""
        if not self.is_available():
            return None
        try:
            url = f"{ZHITU_API_BASE}/hs/index/tree"
            params = {"token": self._token}
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            if isinstance(data, dict) and "detail" in data:
                logger.warning(
                    f"[ZhituFetcher] _fetch_board_tree API error: "
                    f"{data.get('detail', '')[:80]}"
                )
                return None
            if not isinstance(data, list):
                return None
            return [r for r in data if isinstance(r, dict) and r.get("isleaf") == 1]
        except Exception:
            logger.warning("[ZhituFetcher] _fetch_board_tree failed", exc_info=True)
            return None

    def get_board_tree(
        self, board_type: str, subtype: str | None = None
    ) -> list[dict]:
        """Get boards filtered by type and optionally subtype.

        Returns list of ``{code, name, type, subtype}`` dicts.
        Returns ``[]`` on failure or no match (so manager failover works upstream).
        """
        leaves = self._fetch_board_tree()
        if leaves is None:
            return []

        valid_subtypes = ZHITU_SUBTYPES_BY_TYPE.get(board_type, set())
        out: list[dict] = []
        for row in leaves:
            type2 = row.get("type2")
            mapped = ZHITU_TYPE2_MAPPING.get(type2)
            if mapped is None:
                continue
            row_type, row_subtype = mapped
            if row_type != board_type:
                continue
            if subtype is not None and row_subtype != subtype:
                continue
            out.append({
                "code": str(row.get("code", "")),
                "name": str(row.get("name", "")),
                "type": row_type,
                "subtype": row_subtype,
            })
        return out

    def get_board_stocks(self, board_code: str) -> list[dict]:
        """Get stocks belonging to a Zhitu board via /hs/index/stock/{code}.

        Returns ``[{stock_code, stock_name, exchange}]`` or ``[]`` on failure.
        """
        if not self.is_available():
            return []
        try:
            url = f"{ZHITU_API_BASE}/hs/index/stock/{board_code}"
            params = {"token": self._token}
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            if isinstance(data, dict) and "detail" in data:
                logger.warning(
                    f"[ZhituFetcher] get_board_stocks({board_code}) API error"
                )
                return []
            if not isinstance(data, list):
                return []
            return [
                {
                    "stock_code": str(r.get("dm", "")).strip(),
                    "stock_name": str(r.get("mc", "")).strip(),
                    "exchange": str(r.get("jys", "")).strip().lower(),
                }
                for r in data
                if isinstance(r, dict) and r.get("dm")
            ]
        except Exception:
            logger.warning(
                f"[ZhituFetcher] get_board_stocks({board_code}) failed",
                exc_info=True,
            )
            return []

    def get_stock_boards(self, stock_code: str) -> list[dict]:
        """Get boards a stock belongs to via /hs/index/index/{stock_code}.

        Returns ``[{code, name, type, subtype}]`` or ``None`` on failure.
        ``None`` (not ``[]``) so manager can distinguish "no data" from "no match".
        """
        if not self.is_available():
            return None
        try:
            url = f"{ZHITU_API_BASE}/hs/index/index/{stock_code}"
            params = {"token": self._token}
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            if isinstance(data, dict) and "detail" in data:
                logger.warning(
                    f"[ZhituFetcher] get_stock_boards({stock_code}) API error"
                )
                return None
            if not isinstance(data, list):
                return None

            out: list[dict] = []
            for r in data:
                if not isinstance(r, dict):
                    continue
                code = str(r.get("code", "")).strip()
                name = str(r.get("name", "")).strip()
                if not code:
                    continue
                # Zhitu 名称形如 "A股-申万行业-银行" — 解析出 subtype
                # subtype 从 name 第二段推断（A 股分支下的分类标签）
                subtype = self._infer_subtype_from_name(name)
                row_type = self._infer_type_from_subtype(subtype)
                out.append({
                    "code": code,
                    "name": name,
                    "type": row_type,
                    "subtype": subtype,
                })
            return out
        except Exception:
            logger.warning(
                f"[ZhituFetcher] get_stock_boards({stock_code}) failed",
                exc_info=True,
            )
            return None

    @staticmethod
    def _infer_subtype_from_name(name: str) -> str:
        """Extract subtype from Zhitu's ``A股-{大类}-{细分}`` name format.

        Zhitu 的板块名格式: "A股-申万行业-银行" → subtype="申万行业"
        兼容: "A股-热门概念-MSCI中国" → subtype="热门概念"
        兜底: 未知格式返回 "" （路由层在调 get_stock_boards 时再做 type 推断）
        """
        parts = name.split("-")
        if len(parts) >= 2 and parts[0] == "A股":
            return parts[1]
        return ""

    @staticmethod
    def _infer_type_from_subtype(subtype: str) -> str:
        """Map subtype back to type for /stocks/{code}/boards response."""
        for board_type, subtypes in ZHITU_SUBTYPES_BY_TYPE.items():
            if subtype in subtypes:
                return board_type
        return ""

    def get_board_history(
        self, board_code: str, frequency: str = "d", days: int = 30
    ) -> list[dict]:
        """Get K-line for a Zhitu board.

        NOT IMPLEMENTED — Zhitu's /hs/history/ endpoints are stock-level only,
        no board-level K-line API is documented as of 2026-06-24.

        Raises:
            NotImplementedError: always (placeholder for future zzshare /
                EastMoney board-index implementations).
        """
        raise NotImplementedError(
            f"ZhituFetcher does not provide board-level K-line data "
            f"(board_code={board_code!r}, frequency={frequency!r}, days={days!r}). "
            f"No upstream Zhitu API exposes this; consider zzshare plate_kline."
        )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/test_zhitu_fetcher_board.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: 提交**

```bash
git add stock_data/data_provider/fetchers/zhitu_fetcher.py tests/test_zhitu_fetcher_board.py
git commit -m "feat(zhitu): add STOCK_BOARD capability with tree/stocks/stock-boards/history stubs"
```

---

## Task 5: AkshareFetcher 移除 STOCK_BOARD

**Files:**
- Modify: `stock_data/data_provider/fetchers/akshare/fetcher.py`（移除 capability + 4 个方法）
- Modify: `stock_data/data_provider/fetchers/akshare/board.py`（保留但标记 deprecated — 仍可作 fallback enricher）

- [ ] **Step 1: 运行全测试，记录当前基线**

Run: `.venv/Scripts/python.exe -m pytest tests/test_board_persistence_subtype.py tests/test_eastmoney_fetcher_board.py tests/test_zhitu_fetcher_board.py -v`
Expected: 全部 PASS（这是迁移后的基线）

- [ ] **Step 2: 修改 AkshareFetcher，移除 STOCK_BOARD**

在 `stock_data/data_provider/fetchers/akshare/fetcher.py` 中：

删除 `supported_data_types` 中的 `| DataCapability.STOCK_BOARD`：

```python
    # 删除这一行：| DataCapability.STOCK_BOARD
    supported_data_types = (
        DataCapability.HISTORICAL_DWM
        | DataCapability.HISTORICAL_MIN
        | DataCapability.REALTIME_QUOTE
        | DataCapability.STOCK_LIST
        | DataCapability.TRADE_CALENDAR
        | DataCapability.INDEX_QUOTE
        | DataCapability.INDEX_HISTORICAL
        | DataCapability.INDEX_INTRADAY
        | DataCapability.STOCK_ZT_POOL
    )
```

删除 4 个 board 方法（`get_all_concept_boards`、`get_all_industry_boards`、`get_concept_board_stocks`、`get_industry_board_stocks`、`_enrich_stock_from_realtime`）。

修改文件顶部 docstring，移除提及 STOCK_BOARD 的部分。

- [ ] **Step 3: 修改 akshare/board.py，标记 deprecated**

在 `stock_data/data_provider/fetchers/akshare/board.py` 顶部 docstring 改为：

```python
"""Board helpers (DEPRECATED).

The board methods have been migrated to ``EastMoneyFetcher`` (since
the underlying akshare EM APIs originate from EastMoney). This file
is kept temporarily for reference and may be removed in a future
cleanup. Do NOT add new callers — use EastMoneyFetcher's board methods.
"""
```

- [ ] **Step 4: 运行 akshare 相关测试确认无破坏**

Run: `.venv/Scripts/python.exe -m pytest tests/ -k "akshare" -v`
Expected: PASS（移除只影响有 STOCK_BOARD 引用的测试，但还没有）

- [ ] **Step 5: 运行全测试套件**

Run: `.venv/Scripts/python.exe -m pytest tests/ -x --timeout=60`
Expected: 全部通过；如有失败，定位是因为 `STOCK_BOARD` capability 仍在某处被引用

- [ ] **Step 6: 提交**

```bash
git add stock_data/data_provider/fetchers/akshare/
git commit -m "refactor(akshare): remove STOCK_BOARD capability (migrated to EastMoneyFetcher)"
```

---

## Task 6: Manager 改写 4 个 board 公开方法使用 `_with_source`

**Files:**
- Modify: `stock_data/data_provider/manager.py:560-610`（改写 board 方法）

- [ ] **Step 1: 写失败的测试 — Manager.board 方法使用 `_with_source`**

```python
# tests/test_board_source_routing.py 末尾追加：
"""Tests for Manager.board methods using _with_source routing."""
from unittest.mock import patch, MagicMock
import pytest

from stock_data.data_provider.base import DataCapability, DataFetchError
from stock_data.data_provider.manager import DataFetcherManager


def _make_fetcher(name, capability, markets={"csi"}):
    f = MagicMock()
    f.name = name
    f.supported_data_types = capability
    f.supported_markets = markets
    return f


def test_manager_get_all_concept_boards_uses_source_routing():
    """Manager.get_all_concept_boards routes via _with_source, not failover."""
    em = _make_fetcher("EastMoneyFetcher", DataCapability.STOCK_BOARD)
    manager = DataFetcherManager([em])

    with patch.object(manager, "_with_source", wraps=manager._with_source) as spy:
        manager.get_all_concept_boards(source="eastmoney")
        # Must have invoked _with_source exactly once
        assert spy.call_count == 1
        # Call kwargs: source="eastmoney", capability=STOCK_BOARD
        kwargs = spy.call_args.kwargs
        assert kwargs["source"] == "eastmoney"
        assert kwargs["capability"] == DataCapability.STOCK_BOARD


def test_manager_get_concept_board_stocks_passes_board_code():
    em = _make_fetcher("EastMoneyFetcher", DataCapability.STOCK_BOARD)
    manager = DataFetcherManager([em])

    captured = {}
    real = manager._with_source

    def spy_with_source(*args, **kwargs):
        captured["call_args"] = kwargs["call"]
        return real(*args, **kwargs)

    with patch.object(manager, "_with_source", side_effect=spy_with_source):
        manager.get_concept_board_stocks("BK0001", source="eastmoney")

    # The call lambda should invoke fetcher.get_concept_board_stocks("BK0001", ...)
    fetcher = em
    fetcher.get_concept_board_stocks.return_value = []
    captured["call"](fetcher)
    fetcher.get_concept_board_stocks.assert_called_once()
    # First positional arg should be the board code
    call_args = fetcher.get_concept_board_stocks.call_args
    assert call_args.args[0] == "BK0001"


def test_manager_unknown_source_raises_value_error():
    em = _make_fetcher("EastMoneyFetcher", DataCapability.STOCK_BOARD)
    manager = DataFetcherManager([em])
    with pytest.raises(ValueError, match="No fetcher named 'unknown'"):
        manager.get_all_concept_boards(source="unknown")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_board_source_routing.py -v`
Expected: FAIL — Manager 仍然走 `_with_failover`

- [ ] **Step 3: 改写 Manager.board 公开方法**

在 `stock_data/data_provider/manager.py` 中，将 4 个 board 方法（约 560-610 行）替换为：

```python
    # ---------- boards (concept / industry) ----------
    #
    # 板块方法使用 _with_source 路由（按 source 名定位 fetcher），不做 failover。
    # 不同数据源的板块分类体系和代码体系不兼容，failover 会产生误导性结果。
    def get_all_concept_boards(self, source: str, include_quote: bool = False) -> tuple[list[dict], str]:
        """Get all concept boards via the named source's fetcher.

        Args:
            source: fetcher name (e.g. ``"eastmoney"``, ``"zhitu"``).
            include_quote: forward to fetcher — include realtime quote fields.

        Returns:
            ``(boards, source_name)`` tuple.
        """
        boards, name = self._with_source(
            source=source,
            capability=DataCapability.STOCK_BOARD,
            market="csi",
            op_label=f"concept boards ({source})",
            call=lambda f: (
                f.get_all_concept_boards(source=source, include_quote=include_quote),
                f.name,
            ),
        )
        return boards, name

    def get_all_industry_boards(self, source: str, include_quote: bool = False) -> tuple[list[dict], str]:
        """Get all industry boards via the named source's fetcher."""
        boards, name = self._with_source(
            source=source,
            capability=DataCapability.STOCK_BOARD,
            market="csi",
            op_label=f"industry boards ({source})",
            call=lambda f: (
                f.get_all_industry_boards(source=source, include_quote=include_quote),
                f.name,
            ),
        )
        return boards, name

    def get_concept_board_stocks(
        self, board_code: str, source: str, include_quote: bool = False
    ) -> tuple[list[dict], str]:
        """Get stocks in a concept board via the named source's fetcher."""
        boards, name = self._with_source(
            source=source,
            capability=DataCapability.STOCK_BOARD,
            market="csi",
            op_label=f"concept board stocks {board_code} ({source})",
            call=lambda f: (
                f.get_concept_board_stocks(board_code, source=source, include_quote=include_quote),
                f.name,
            ),
        )
        return boards, name

    def get_industry_board_stocks(
        self, board_code: str, source: str, include_quote: bool = False
    ) -> tuple[list[dict], str]:
        """Get stocks in an industry board via the named source's fetcher."""
        boards, name = self._with_source(
            source=source,
            capability=DataCapability.STOCK_BOARD,
            market="csi",
            op_label=f"industry board stocks {board_code} ({source})",
            call=lambda f: (
                f.get_industry_board_stocks(board_code, source=source, include_quote=include_quote),
                f.name,
            ),
        )
        return boards, name
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/test_board_source_routing.py -v`
Expected: PASS (8 tests total = 5 from Task 1 + 3 new)

- [ ] **Step 5: 提交**

```bash
git add stock_data/data_provider/manager.py tests/test_board_source_routing.py
git commit -m "refactor(manager): board methods use _with_source routing (no failover)"
```

---

## Task 7: Pydantic Schema 新增 StockBoardInfo / StockBoardsResponse

**Files:**
- Modify: `stock_data/api/schemas.py`（在 BoardStocksResponse 后新增）

- [ ] **Step 1: 写失败的测试 — 新 schema 字段映射正确**

```python
# tests/test_boards_schemas.py
"""Tests for board-related Pydantic schemas."""
from stock_data.api.schemas import StockBoardInfo, StockBoardsResponse


def test_stock_board_info_required_fields():
    info = StockBoardInfo(
        code="sw_mt", name="A股-申万行业-煤炭",
        type="industry", subtype="申万行业",
    )
    assert info.code == "sw_mt"
    assert info.name == "A股-申万行业-煤炭"
    assert info.type == "industry"
    assert info.subtype == "申万行业"


def test_stock_boards_response_shape():
    resp = StockBoardsResponse(
        stock_code="000001",
        source="zhitu",
        data=[
            StockBoardInfo(
                code="sw_yx", name="A股-申万行业-银行",
                type="industry", subtype="申万行业",
            )
        ],
    )
    assert resp.stock_code == "000001"
    assert resp.source == "zhitu"
    assert len(resp.data) == 1
    assert resp.data[0].code == "sw_yx"


def test_stock_boards_response_empty_data():
    """Empty boards list is valid (stock belongs to no known boards)."""
    resp = StockBoardsResponse(stock_code="000001", source="zhitu", data=[])
    assert resp.data == []
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_boards_schemas.py -v`
Expected: FAIL with `ImportError: cannot import name 'StockBoardInfo'`

- [ ] **Step 3: 在 schemas.py 新增 schema**

在 `stock_data/api/schemas.py` 第 316 行（`BoardStocksResponse` 类结束）后新增：

```python
class StockBoardInfo(BaseModel):
    """A board that a stock belongs to."""

    code: str = Field(description="Board code (source-specific, e.g. 'sw_yx' for Zhitu)")
    name: str = Field(description="Board full name (e.g. 'A股-申万行业-银行')")
    type: str = Field(description="Board type: concept / industry / index / special")
    subtype: str = Field(
        default="",
        description="Source-specific subtype (e.g. '申万行业' for Zhitu, "
        "'concept' for EastMoney)",
    )


class StockBoardsResponse(BaseModel):
    """Response for /stocks/{stock_code}/boards endpoint."""

    stock_code: str = Field(description="Stock code queried")
    source: str = Field(
        default="",
        description="数据来源 fetcher 名 (e.g. 'zhitu')",
    )
    data: list[StockBoardInfo] = Field(
        default_factory=list,
        description="Boards the stock belongs to",
    )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/test_boards_schemas.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: 提交**

```bash
git add stock_data/api/schemas.py tests/test_boards_schemas.py
git commit -m "feat(schemas): add StockBoardInfo and StockBoardsResponse models"
```

---

## Task 8: API 路由改造 — boards.py 全部端点

**Files:**
- Modify: `stock_data/api/routes/boards.py`（全文重写 + 新增 2 个端点）
- Test: `tests/test_boards_api.py`（新建）

- [ ] **Step 1: 写失败的测试 — 端点契约**

```python
# tests/test_boards_api.py
"""Integration tests for board API endpoints."""
from unittest.mock import patch, MagicMock
import pytest
from fastapi.testclient import TestClient

from stock_data.server import create_app
from stock_data.api.routes import _router


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


# --- list_boards ---

def test_list_boards_source_required(client):
    """GET /boards without source returns 422 (source is now required)."""
    r = client.get("/api/v1/boards?type=concept")
    assert r.status_code == 422


def test_list_boards_invalid_source_returns_400(client):
    """GET /boards with unknown source returns 400."""
    r = client.get("/api/v1/boards?type=concept&source=unknown")
    # Either 400 (if Manager._with_source raises ValueError → mapped to 400)
    # or 500 (if not yet mapped). Acceptable to assert not-200.
    assert r.status_code in (400, 500)


def test_list_boards_zhitu_returns_zhitu_boards(client):
    """GET /boards?source=zhitu&type=industry returns Zhitu boards."""
    fake_boards = [
        {"code": "sw_mt", "name": "A股-申万行业-煤炭",
         "type": "industry", "subtype": "申万行业"},
    ]
    with patch(
        "stock_data.data_provider.manager.DataFetcherManager.get_all_concept_boards",
        return_value=(fake_boards, "ZhituFetcher"),
    ):
        r = client.get("/api/v1/boards?type=concept&source=zhitu")
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "ZhituFetcher"
    assert body["data"][0]["code"] == "sw_mt"


def test_list_boards_invalid_subtype_returns_400(client):
    """Subtype not in source's valid set → 400."""
    r = client.get(
        "/api/v1/boards?type=concept&source=eastmoney&subtype=热门概念"
    )
    assert r.status_code in (400, 500)


def test_list_boards_eastmoney_default_subtype_ok(client):
    """source=eastmoney&type=concept&subtype=concept is valid (mirrored)."""
    fake = [{"code": "BK0001", "name": "测试"}]
    with patch(
        "stock_data.data_provider.manager.DataFetcherManager.get_all_concept_boards",
        return_value=(fake, "EastMoneyFetcher"),
    ):
        r = client.get(
            "/api/v1/boards?type=concept&source=eastmoney&subtype=concept"
        )
    assert r.status_code == 200


def test_list_boards_sort_by_without_include_quote_returns_400(client):
    """sort_by requires include_quote=true; otherwise 400."""
    r = client.get(
        "/api/v1/boards?type=concept&source=eastmoney&sort_by=change_pct"
    )
    assert r.status_code in (400, 422)


def test_list_boards_limit_truncates_results(client):
    """limit=2 truncates the data array to 2 items."""
    fake = [{"code": f"BK{i:04d}", "name": f"测试{i}"} for i in range(5)]
    with patch(
        "stock_data.data_provider.manager.DataFetcherManager.get_all_concept_boards",
        return_value=(fake, "EastMoneyFetcher"),
    ):
        r = client.get(
            "/api/v1/boards?type=concept&source=eastmoney&include_quote=true"
            "&sort_by=change_pct&limit=2"
        )
    assert r.status_code == 200
    assert len(r.json()["data"]) == 2


# --- get_board_stocks ---

def test_get_board_stocks_source_required(client):
    r = client.get("/api/v1/boards/BK0001/stocks")
    assert r.status_code == 422


# --- get_stock_boards (NEW) ---

def test_get_stock_boards_zhitu_returns_boards(client):
    fake_boards = [
        {"code": "sw_yx", "name": "A股-申万行业-银行",
         "type": "industry", "subtype": "申万行业"},
        {"code": "chgn_700532", "name": "A股-热门概念-MSCI中国",
         "type": "concept", "subtype": "热门概念"},
    ]
    with patch(
        "stock_data.data_provider.manager.DataFetcherManager._with_source",
        return_value=(fake_boards, "ZhituFetcher"),
    ):
        r = client.get("/api/v1/stocks/000001/boards?source=zhitu")
    assert r.status_code == 200
    body = r.json()
    assert body["stock_code"] == "000001"
    assert body["source"] == "ZhituFetcher"
    assert len(body["data"]) == 2


def test_get_stock_boards_eastmoney_returns_501(client):
    """source=eastmoney not yet supported for stock-boards lookup → 501."""
    r = client.get("/api/v1/stocks/000001/boards?source=eastmoney")
    assert r.status_code in (400, 501)


# --- get_board_history (NEW, stub) ---

def test_get_board_history_returns_501_for_zhitu(client):
    """Board K-line stub returns 501 Not Implemented."""
    r = client.get("/api/v1/boards/sw_mt/history?source=zhitu")
    assert r.status_code == 501
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_boards_api.py -v`
Expected: 多数 FAIL（端点尚未改造）

- [ ] **Step 3: 重写 boards.py 路由**

完全重写 `stock_data/api/routes/boards.py`：

```python
"""Board endpoints (concept / industry / index / special).

``source`` query parameter is REQUIRED and selects the fetcher:
- ``eastmoney``: EastMoneyFetcher (akshare EM backend)
- ``zhitu``: ZhituFetcher (zhituapi.com)
- ``zzshare``: ZzshareFetcher (not yet implemented)

Each source has its own board classification system; failover between
sources is intentionally not supported (different code systems).
"""
import logging
from datetime import date as date_cls
from typing import Literal

from fastapi import HTTPException, Path, Query

from ...data_provider.base import DataCapability
from ...data_provider.manager import DataFetcherManager
from ...data_provider.persistence import board as stock_board_cache
from ...data_provider.persistence import trade_calendar
from ..cache import (
    cached_lookup,
    cached_store,
    get_pools_cache,
    is_cache_enabled,
    make_pools_cache_key,
)
from ..endpoint_meta import endpoint_meta
from ..schemas import (
    BoardInfo,
    BoardListResponse,
    BoardStockInfo,
    BoardStocksResponse,
    ErrorResponse,
    StockBoardInfo,
    StockBoardsResponse,
    ZTPoolResponse,
    ZTPoolStock,
)
from ._router import router
from .errors import map_errors
from .helpers import get_manager

logger = logging.getLogger(__name__)


# source 合法值集合（防止任意 source 触发 _with_source 任意调用）
_VALID_SOURCES = {"eastmoney", "zhitu", "zzshare"}

# type 合法值
_VALID_TYPES = {"concept", "industry", "index", "special"}


def _resolve_source(source: str) -> str:
    """Validate source parameter; raise HTTPException(400) on invalid."""
    if source not in _VALID_SOURCES:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_source",
                "message": f"Unknown source '{source}'. Valid sources: {sorted(_VALID_SOURCES)}",
            },
        )
    return source


def _resolve_type(board_type: str) -> str:
    """Validate type parameter."""
    if board_type not in _VALID_TYPES:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_type",
                "message": f"Unknown type '{board_type}'. Valid types: {sorted(_VALID_TYPES)}",
            },
        )
    return board_type


@router.get(
    "/boards",
    response_model=BoardListResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid source/type/subtype"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["boards"],
)
@endpoint_meta(
    summary="板块清单（支持实时报价、排序、截断）",
    markets=["csi"],
    capabilities=["STOCK_BOARD"],
)
@map_errors
def list_boards(
    type: Literal["concept", "industry", "index", "special"] = Query(
        ..., description="Board type"
    ),
    source: Literal["eastmoney", "zhitu", "zzshare"] = Query(
        ..., description="Data source (REQUIRED)"
    ),
    subtype: str | None = Query(
        None,
        description="Source-specific subtype. Validated per (source, type) pair. "
        "Omit to return all subtypes for the type.",
    ),
    include_quote: bool = Query(False, description="Include realtime quote fields"),
    sort_by: Literal["change_pct", "volume", "amount", "price"] | None = Query(
        None, description="Sort by field (requires include_quote=true)"
    ),
    sort_order: Literal["asc", "desc"] = Query("desc", description="Sort order"),
    limit: int | None = Query(
        None, ge=1, le=500, description="Max number of items (default: all)"
    ),
    refresh: bool = Query(False, description="Force fetch latest from upstream"),
) -> BoardListResponse:
    """Get list of concept / industry / index / special boards."""
    _resolve_source(source)
    _resolve_type(type)

    # subtype validation — early failure before manager invocation
    stock_board_cache._validate_subtype(source, type, subtype)

    # sort_by requires include_quote (the sort fields are quote fields)
    if sort_by is not None and not include_quote:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_combination",
                "message": "sort_by requires include_quote=true",
            },
        )

    manager = get_manager()

    # EastMoney uses concept/industry split; Zhitu uses type/subtype split.
    # We delegate to source-specific persistence helpers to keep caches separated.
    if type == "concept":
        boards, origin = stock_board_cache.get_board_list(
            board_type="concept", source=source, refresh=refresh,
            include_quote=include_quote, manager=manager,
        )
    elif type == "industry":
        boards, origin = stock_board_cache.get_board_list(
            board_type="industry", source=source, refresh=refresh,
            include_quote=include_quote, manager=manager,
        )
    else:
        # index / special — Zhitu only for now; EastMoney boards.py doesn't have these.
        # Call ZhituFetcher.get_board_tree directly via manager.
        try:
            boards, origin = manager._with_source(
                source=source,
                capability=DataCapability.STOCK_BOARD,
                market="csi",
                op_label=f"{type} boards ({source})",
                call=lambda f: (
                    f.get_board_tree(board_type=type, subtype=subtype),
                    f.name,
                ),
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail={"error": str(e)})

    # Filter by subtype if specified (EastMoney path — Zhitu path is pre-filtered).
    if subtype is not None:
        boards = [b for b in boards if b.get("subtype") == subtype]

    # Sort
    if sort_by is not None:
        boards = sorted(
            boards,
            key=lambda b: b.get(sort_by) or 0,
            reverse=(sort_order == "desc"),
        )

    # Truncate
    if limit is not None:
        boards = boards[:limit]

    return BoardListResponse(
        source=origin,
        data=[
            BoardInfo(
                code=b["code"],
                name=b["name"],
                price=b.get("price"),
                change_pct=b.get("change_pct"),
                change_amount=b.get("change_amount"),
                volume=b.get("volume"),
                amount=b.get("amount"),
                turnover_rate=b.get("turnover_rate"),
                total_mv=b.get("total_mv"),
                up_count=b.get("up_count"),
                down_count=b.get("down_count"),
                leading_stock=b.get("leading_stock"),
                leading_stock_pct=b.get("leading_stock_pct"),
            )
            for b in boards
        ],
    )


@router.get(
    "/boards/{board_code}/stocks",
    response_model=BoardStocksResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid source"},
        404: {"model": ErrorResponse, "description": "Board not found"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["boards"],
)
@endpoint_meta(
    summary="板块成分股",
    markets=["csi"],
    capabilities=["STOCK_BOARD"],
    fetcher_method="get_concept_board_stocks",
)
@map_errors
def get_board_stocks(
    board_code: str = Path(max_length=30, description="Board code"),
    source: Literal["eastmoney", "zhitu", "zzshare"] = Query(
        ..., description="Data source (REQUIRED)"
    ),
    include_quote: bool = Query(False, description="Include realtime quote data"),
    refresh: bool = Query(False, description="Force fetch latest from upstream"),
) -> BoardStocksResponse:
    """Get stocks belonging to a board."""
    _resolve_source(source)

    manager = get_manager()
    stocks, origin = stock_board_cache.get_board_stocks(
        board_code, source, refresh=refresh, include_quote=include_quote, manager=manager
    )

    if not stocks:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "message": f"No stocks found for board {board_code}"},
        )

    # Best-effort board name resolution (cache lookup, not an extra fetcher call)
    board_name = board_code
    for bt in ("concept", "industry"):
        boards, _ = stock_board_cache.get_board_list(
            bt, source, refresh=False, manager=manager
        )
        match = next((b["name"] for b in boards if b["code"] == board_code), None)
        if match:
            board_name = match
            break

    stock_list = [
        BoardStockInfo(
            code=s.get("stock_code", ""),
            name=s.get("stock_name", ""),
            price=s.get("price"),
            change_pct=s.get("change_pct"),
            volume=s.get("volume"),
        )
        for s in stocks
    ]

    return BoardStocksResponse(
        board=BoardInfo(code=board_code, name=board_name),
        stocks=stock_list,
        query_source=source,
        data_source=origin,
    )


@router.get(
    "/stocks/{stock_code}/boards",
    response_model=StockBoardsResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid source/type/subtype"},
        404: {"model": ErrorResponse, "description": "Stock not found"},
        501: {"model": ErrorResponse, "description": "Source does not implement this endpoint"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["boards"],
)
@endpoint_meta(
    summary="股票所属板块（新增）",
    markets=["csi"],
    capabilities=["STOCK_BOARD"],
    fetcher_method="get_stock_boards",
)
@map_errors
def get_stock_boards(
    stock_code: str = Path(max_length=20, description="Stock code (e.g. 000001)"),
    source: Literal["zhitu", "eastmoney"] = Query(
        ..., description="Data source (currently only 'zhitu' supported)"
    ),
    type: Literal["concept", "industry", "index", "special"] | None = Query(
        None, description="Filter by board type"
    ),
    subtype: str | None = Query(
        None, description="Filter by source-specific subtype"
    ),
) -> StockBoardsResponse:
    """Get boards a stock belongs to.

    Currently only ``source=zhitu`` is supported. EastMoney's API does not
    expose a direct stock→boards mapping.
    """
    _resolve_source(source)

    if source != "zhitu":
        raise HTTPException(
            status_code=501,
            detail={
                "error": "not_implemented",
                "message": f"source='{source}' does not implement stock→boards lookup. "
                f"Currently supported: 'zhitu'",
            },
        )

    # Subtype validation only if provided
    if type is not None:
        _resolve_type(type)
        stock_board_cache._validate_subtype(source, type, subtype)

    manager = get_manager()
    try:
        boards, origin = manager._with_source(
            source=source,
            capability=DataCapability.STOCK_BOARD,
            market="csi",
            op_label=f"stock boards {stock_code} ({source})",
            call=lambda f: (
                f.get_stock_boards(stock_code) or [],
                f.name,
            ),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"error": str(e)})

    # Filter by type/subtype if specified
    if type is not None:
        boards = [b for b in boards if b.get("type") == type]
    if subtype is not None:
        boards = [b for b in boards if b.get("subtype") == subtype]

    if not boards:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "not_found",
                "message": f"No boards found for stock {stock_code} "
                f"(source={source}, type={type}, subtype={subtype})",
            },
        )

    return StockBoardsResponse(
        stock_code=stock_code,
        source=origin,
        data=[
            StockBoardInfo(
                code=b["code"],
                name=b["name"],
                type=b.get("type", ""),
                subtype=b.get("subtype", ""),
            )
            for b in boards
        ],
    )


@router.get(
    "/boards/{board_code}/history",
    responses={
        400: {"model": ErrorResponse, "description": "Invalid source"},
        501: {"model": ErrorResponse, "description": "Source does not yet support board K-line"},
    },
    tags=["boards"],
)
@endpoint_meta(
    summary="板块 K 线（新增, 占位 — 暂未实现）",
    markets=["csi"],
    capabilities=["STOCK_BOARD"],
    fetcher_method="get_board_history",
)
@map_errors
def get_board_history(
    board_code: str = Path(max_length=30, description="Board code"),
    source: Literal["zhitu", "eastmoney", "zzshare"] = Query(
        ..., description="Data source"
    ),
    frequency: Literal["d", "w", "m"] = Query("d", description="K-line frequency"),
    start_date: str | None = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: str | None = Query(None, description="End date (YYYY-MM-DD)"),
    days: int = Query(30, ge=1, le=365, description="Days (when start_date not given)"),
) -> dict:
    """Get historical K-line for a board. Currently a 501 stub."""
    _resolve_source(source)
    raise HTTPException(
        status_code=501,
        detail={
            "error": "not_implemented",
            "message": f"Board K-line for source='{source}' is not yet implemented. "
            f"Consider contributing via zzshare's plate_kline or EastMoney's board index.",
        },
    )


# --- ZT/DT/ZBGC pool endpoints (unchanged from original) ---

@router.get(
    "/zt-pools",
    response_model=ZTPoolResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid pool type"},
        404: {"model": ErrorResponse, "description": "No data found for date"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["zt-pools"],
)
@endpoint_meta(
    summary="涨跌停股池",
    markets=["csi"],
    capabilities=["STOCK_ZT_POOL"],
)
@map_errors
def get_pools(
    type: str = Query(
        ...,
        pattern="^(zt|dt|zbgc)$",
        description="Pool type: zt (涨停) / dt (跌停) / zbgc (炸板)",
    ),
    date: str | None = Query(
        None,
        description=(
            "Pool date (YYYY-MM-DD). If not provided, the server picks the most recent "
            "trade date relative to today: today itself when today is a trade day, "
            "otherwise the latest cached trade date <= today."
        ),
    ),
    refresh: bool = Query(
        False,
        description=(
            "Force refresh from upstream. Bypasses the persistence read, but the "
            "persistence write is still skipped when the resolved date is the "
            "'current trading day' (today AND today is a trade day), to avoid "
            "persisting a partially-formed pool."
        ),
    ),
) -> ZTPoolResponse:
    """Get ZT (涨跌停) pool data for a specific type and date."""
    today_str = date_cls.today().strftime("%Y-%m-%d")

    if date:
        query_date = date
    else:
        if trade_calendar.is_trade_date(today_str):
            query_date = today_str
        else:
            resolved = trade_calendar.get_latest_trade_date_on_or_before(today_str)
            query_date = resolved or today_str

    is_current_day = (query_date == today_str) and trade_calendar.is_trade_date(today_str)

    cache_key = make_pools_cache_key(type, query_date)
    if is_current_day and is_cache_enabled():
        hit = cached_lookup(get_pools_cache, cache_key, "pools")
        if hit is not None:
            return hit

    manager = get_manager()
    stocks, origin = manager.get_zt_pool(
        pool_type=type,
        date=query_date,
        refresh=refresh,
    )

    if not stocks:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "message": f"No {type} pool data found"},
        )

    actual_date = query_date or stocks[0].get("pool_date", "")

    pool_stocks = [
        ZTPoolStock(
            code=s.get("code", ""),
            name=s.get("name", ""),
            price=s.get("price"),
            change_pct=s.get("change_pct"),
            amount=s.get("amount"),
            circ_mv=s.get("circ_mv"),
            total_mv=s.get("total_mv"),
            turnover_rate=s.get("turnover_rate"),
            lb_count=s.get("lb_count"),
            first_seal_time=s.get("first_seal_time"),
            last_seal_time=s.get("last_seal_time"),
            seal_amount=s.get("seal_amount"),
            seal_count=s.get("seal_count"),
            zt_count=s.get("zt_count"),
        )
        for s in stocks
    ]

    result = ZTPoolResponse(
        date=actual_date,
        type=type,
        total=len(pool_stocks),
        stocks=pool_stocks,
        source=origin,
    )

    if is_current_day:
        cached_store(get_pools_cache, cache_key, result)
    return result
```

- [ ] **Step 4: 运行 API 测试**

Run: `.venv/Scripts/python.exe -m pytest tests/test_boards_api.py -v`
Expected: PASS (10 tests)

- [ ] **Step 5: 运行全测试套件确认无破坏**

Run: `.venv/Scripts/python.exe -m pytest tests/ -x --timeout=60`
Expected: 全部通过；如有 board 旧测试失败，需更新以传入新的 source 参数

- [ ] **Step 6: 提交**

```bash
git add stock_data/api/routes/boards.py tests/test_boards_api.py
git commit -m "feat(api): source-routed boards endpoints + stock-boards and history stubs"
```

---

## Task 9: 验证 —— 端到端冒烟测试

**Files:**
- 仅运行测试 + 启动 server 验证

- [ ] **Step 1: 运行所有 board 相关测试**

Run: `.venv/Scripts/python.exe -m pytest tests/test_board_source_routing.py tests/test_board_persistence_subtype.py tests/test_eastmoney_fetcher_board.py tests/test_zhitu_fetcher_board.py tests/test_boards_schemas.py tests/test_boards_api.py -v`
Expected: 全 PASS（5+9+5+6+3+10 = 38 tests）

- [ ] **Step 2: 运行完整测试套件**

Run: `.venv/Scripts/python.exe -m pytest tests/ --timeout=60`
Expected: PASS；如有其他测试因 source 默认值变动失败，更新对应测试的 URL

- [ ] **Step 3: 启动 server，curl 4 个端点**

```bash
.venv/Scripts/python.exe -m stock_data.server &
SERVER_PID=$!
sleep 3

# 1. list_boards (zhitu)
curl -sS "http://localhost:8888/api/v1/boards?type=industry&source=zhitu" | head -c 500
echo ""

# 2. list_boards (eastmoney) — missing source → 422
curl -sS -o /dev/null -w "%{http_code}\n" "http://localhost:8888/api/v1/boards?type=concept"

# 3. stock_boards (zhitu)
curl -sS "http://localhost:8888/api/v1/stocks/000001/boards?source=zhitu" | head -c 500
echo ""

# 4. board_history (zhitu) → 501
curl -sS -o /dev/null -w "%{http_code}\n" "http://localhost:8888/api/v1/boards/sw_mt/history?source=zhitu"

kill $SERVER_PID 2>/dev/null
```

Expected:
- 1: 200 + JSON with zhitu boards
- 2: 422
- 3: 200 + JSON with stock's boards (需要 ZHITU_TOKEN 才能拿到真实数据，否则 500)
- 4: 501

- [ ] **Step 4: 提交最终收尾**

如有需要，提交一个总结 commit；否则无需提交（前面的 8 个 task 已逐步提交）

```bash
git log --oneline -10
```

Expected: 8 个新 commit 顺序记录了实现过程

---

## 自审检查

### Spec 覆盖

| Spec 章节 | 实现任务 |
|---|---|
| 2. Manager `_with_source` | Task 1 |
| 3. subtype 校验 | Task 2 |
| 4.1 改造 list_boards | Task 8 |
| 4.2 改造 get_board_stocks | Task 8 |
| 4.3 新增 get_stock_boards | Task 7（schema）+ Task 8（route） |
| 4.4 新增 get_board_history | Task 8 |
| 5.1 EastMoney 迁移 | Task 3 |
| 5.2 Zhitu 承接 | Task 4 |
| 5.3 Akshare 退役 | Task 5 |
| 5.4 Zzshare（后续） | 不在本次范围 |
| 6. 持久化 | Task 2 + 既有 `persistence/board.py` 复用 |
| 7. 路由层 | Task 8 |

### 占位符扫描

- Task 8 中 `__import__(...)` 已替换为顶部正常的 `from ... import DataCapability`
- Task 6 中 `_make_fetcher` 使用 `MagicMock` — OK
- Task 7 步骤 3 "Stub": 不存在 TBD/TODO
- Task 4 中 `get_board_history` 抛 `NotImplementedError` — 是设计要求，非占位符

### 类型一致性

- `get_stock_boards` 返回 `list[dict] | None`，API 层 `or []` 处理 — 一致
- `get_board_tree` 返回 `list[dict]`（不返回 `None`）— 与测试对齐
- `_with_source` 返回 `T` — Task 6 通过 tuple 解包匹配
