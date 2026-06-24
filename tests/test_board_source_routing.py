"""Tests for ``DataFetcherManager._with_source`` routing primitive.

板块场景需要按 source 名精确定位 fetcher，不 failover——因为不同 source
的板块分类体系和代码体系完全不同，无法透明 failover。

这些测试覆盖 _with_source 路由原语的 5 个核心契约：
1. 匹配 fetcher 后调用 call 并返回结果
2. 无匹配 fetcher 时抛 ValueError
3. 匹配 fetcher 但缺 capability 时抛 ValueError
4. fetcher 调用失败时不重试其他 fetcher
5. source 大小写不敏感匹配
"""
from __future__ import annotations

import pytest

from stock_data.data_provider.base import DataCapability
from stock_data.data_provider.manager import DataFetcherManager


# ---------------------------------------------------------------------------
# FakeFetcher: a minimal stub that implements the BaseFetcher contract
# just enough for the manager's routing primitives to accept it.
# It does NOT extend BaseFetcher (which is ABC and would force
# implementations of many abstract methods) — it just has the attributes
# the manager reads.
# ---------------------------------------------------------------------------


class FakeFetcher:
    """Minimal stub fetcher for _with_source tests."""

    def __init__(
        self,
        name: str,
        capabilities: DataCapability,
        markets: set[str],
    ):
        self.name = name
        self.priority = 1
        self.supported_data_types = capabilities
        self.supported_markets = markets


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_with_source_routes_to_matching_fetcher():
    """Matching fetcher is found, call(fetcher) is invoked, result is returned."""
    fetcher = FakeFetcher(
        name="eastmoney",
        capabilities=DataCapability.STOCK_BOARD,
        markets={"csi"},
    )
    manager = DataFetcherManager()
    manager.add_fetcher(fetcher)

    sentinel = {"boards": ["BK0001", "BK0002"]}
    result = manager._with_source(
        source="eastmoney",
        capability=DataCapability.STOCK_BOARD,
        market="csi",
        op_label="test concept boards",
        call=lambda f: sentinel,
    )

    assert result is sentinel


def test_with_source_raises_when_no_fetcher_matches():
    """No fetcher with the requested name → ValueError."""
    manager = DataFetcherManager()
    manager.add_fetcher(
        FakeFetcher(
            name="akshare",
            capabilities=DataCapability.STOCK_BOARD,
            markets={"csi"},
        )
    )

    with pytest.raises(ValueError, match="eastmoney"):
        manager._with_source(
            source="eastmoney",
            capability=DataCapability.STOCK_BOARD,
            market="csi",
            op_label="test concept boards",
            call=lambda f: [],
        )


def test_with_source_raises_when_fetcher_lacks_capability():
    """Fetcher matches by name but does not declare the required capability → ValueError."""
    manager = DataFetcherManager()
    manager.add_fetcher(
        FakeFetcher(
            name="eastmoney",
            capabilities=DataCapability.DRAGON_TIGER,  # wrong capability
            markets={"csi"},
        )
    )

    with pytest.raises(ValueError, match="STOCK_BOARD"):
        manager._with_source(
            source="eastmoney",
            capability=DataCapability.STOCK_BOARD,
            market="csi",
            op_label="test concept boards",
            call=lambda f: [],
        )


def test_with_source_does_not_failover():
    """If the matching fetcher's call raises, the exception propagates — no fallback."""
    manager = DataFetcherManager()
    # Two fetchers: the first matches by name, the second would also
    # support the capability but is named differently (not what was
    # requested). The exception must propagate, NOT fall through to
    # the second fetcher.
    manager.add_fetcher(
        FakeFetcher(
            name="akshare",
            capabilities=DataCapability.STOCK_BOARD,
            markets={"csi"},
        )
    )
    manager.add_fetcher(
        FakeFetcher(
            name="eastmoney",
            capabilities=DataCapability.STOCK_BOARD,
            markets={"csi"},
        )
    )

    def _explode(f):
        raise RuntimeError("akshare upstream is down")

    with pytest.raises(RuntimeError, match="akshare upstream is down"):
        manager._with_source(
            source="akshare",
            capability=DataCapability.STOCK_BOARD,
            market="csi",
            op_label="test concept boards",
            call=_explode,
        )


def test_with_source_matches_case_insensitive():
    """Source name comparison is case-insensitive."""
    manager = DataFetcherManager()
    manager.add_fetcher(
        FakeFetcher(
            name="EastMoney",  # mixed case
            capabilities=DataCapability.STOCK_BOARD,
            markets={"csi"},
        )
    )

    # Lowercase request should still match the mixed-case fetcher name
    sentinel = [{"code": "BK0001"}]
    result = manager._with_source(
        source="eastmoney",
        capability=DataCapability.STOCK_BOARD,
        market="csi",
        op_label="test concept boards",
        call=lambda f: sentinel,
    )
    assert result is sentinel

    # And uppercase request should also match
    result2 = manager._with_source(
        source="EASTMONEY",
        capability=DataCapability.STOCK_BOARD,
        market="csi",
        op_label="test concept boards",
        call=lambda f: sentinel,
    )
    assert result2 is sentinel
