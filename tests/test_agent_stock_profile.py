"""Tests for build_stock_profile helper.

Spec: docs/superpowers/specs/2026-09-06-agent-lead-stocks-design.md §3.2
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd
import pytest

from stock_data.api._helpers import stock_boards as sb_helper
from stock_data.api._helpers.agent_stock_profile import (
    StockProfileData,
    build_stock_profile,
)
from stock_data.data_provider.persistence import board as stock_board_cache


def _make_unified_quote(**overrides):
    """Build a SimpleNamespace that survives MinimalQuote construction."""
    defaults = {
        "price": 10.0,
        "change_pct": 5.0,
        "change_amount": 0.5,
        "open_price": 10.0,
        "high": 10.5,
        "low": 9.5,
        "pre_close": 9.5,
        "volume": 1000,
        "volume_unit": "share",
        "amount": 10000.0,
        "turnover_rate": 1.0,
        "amplitude": 10.0,
        "volume_ratio": 1.5,
        "total_mv": 1e11,
        "circ_mv": 5e10,
        "pe_ratio": 20.0,
        "pb_ratio": 3.0,
        "limit_up": 11.0,
        "limit_down": 9.0,
        "name": "测试股",
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_manager(quote=None, kline_df=None, info_dict=None, info_src="zhitu"):
    m = MagicMock()
    m.get_realtime_quote.return_value = quote
    if kline_df is not None:
        m.get_kline_data.return_value = (kline_df, "akshare")
    else:
        m.get_kline_data.return_value = (None, "akshare")
    m.get_stock_info.return_value = (info_dict or {}, info_src)
    return m


@pytest.fixture
def empty_memberships(monkeypatch):
    """Default: no cached entries, no enrichment."""
    monkeypatch.setattr(
        stock_board_cache,
        "get_stock_memberships",
        lambda stock_code, sources, manager=None, **kw: ([], [], "persistence"),
    )
    monkeypatch.setattr(
        sb_helper,
        "fetch_stock_boards_quote_enrichment",
        lambda stock_code, manager: (None, {}),
    )


def test_helper_returns_dataclass_with_code(empty_memberships):
    m = _make_manager()
    profile = build_stock_profile(m, "300750")
    assert isinstance(profile, StockProfileData)
    assert profile.code == "300750"
    assert profile.quote is None
    # build_features 对空 df 返回默认空 dict，包装成 BatchFeatures（空子块）；
    # 这与 "失败导致 None" 语义不同——None = 计算失败。
    assert profile.features is not None
    assert profile.features.trend.ma == {}
    assert profile.features.pivots.params == {}
    # info always populated (get_stock_info always returns tuple)
    assert profile.info == {"source": "zhitu", "data": {}}
    # boards: empty entries + no fetcher_full → {source:'persistence', data:[]}
    assert profile.boards == {"source": "persistence", "data": []}
    assert profile.errors == []
    # ok is True because info+features are truthy
    assert profile.ok is True


def test_helper_ok_true_when_quote_present(empty_memberships):
    m = _make_manager(quote=_make_unified_quote())
    profile = build_stock_profile(m, "300750")
    assert profile.ok is True
    assert profile.quote is not None
    assert profile.quote.price == 10.0
    # MinimalQuote 没有 name 字段——name 由 caller 从 q.name 单独取
    assert not hasattr(profile.quote, "name")


def test_helper_quote_failure_appends_error(empty_memberships):
    m = _make_manager()
    m.get_realtime_quote.side_effect = Exception("boom")
    profile = build_stock_profile(m, "300750")
    assert profile.quote is None
    aspects = [e for e in profile.errors if e.aspect == "quote"]
    assert len(aspects) == 1
    assert aspects[0].error == "Exception"
    assert "boom" in aspects[0].message


def test_helper_features_failure_does_not_block_quote(empty_memberships):
    m = _make_manager(quote=_make_unified_quote())
    m.get_kline_data.side_effect = Exception("kline boom")
    profile = build_stock_profile(m, "300750")
    assert profile.quote is not None
    assert profile.features is None
    aspects = {e.aspect for e in profile.errors}
    assert "features" in aspects
    assert profile.ok is True


def test_helper_info_shape(empty_memberships):
    """info 字段必须包装为 {source, data} 形态以匹配 StockBatchProfileEntry 契约。"""
    m = _make_manager(info_dict={"name": "测试股", "industry": "新能源"}, info_src="tushare")
    profile = build_stock_profile(m, "300750")
    assert profile.info == {
        "source": "tushare",
        "data": {"name": "测试股", "industry": "新能源"},
    }


def test_helper_kline_returns_two_tuple(empty_memberships):
    """get_kline_data 返回 (df, source) tuple；helper 正确解包。"""
    df = pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=60).astype(str),
            "close": [10.0 + i * 0.1 for i in range(60)],
            "open": [10.0] * 60,
            "high": [10.5] * 60,
            "low": [9.5] * 60,
            "volume": [1000] * 60,
        }
    )
    m = _make_manager(kline_df=df)
    profile = build_stock_profile(m, "300750")
    assert m.get_kline_data.called
    assert profile.features is not None  # build_features ran


def test_helper_amplitude_fallback(empty_memberships):
    """当 q.amplitude=None 但 high/low/pre_close 有值时，应回退计算 amplitude。"""
    quote = _make_unified_quote(amplitude=None)
    m = _make_manager(quote=quote)
    profile = build_stock_profile(m, "300750")
    # (10.5 - 9.5) / 9.5 * 100 ≈ 10.526
    assert profile.quote.amplitude_pct is not None
    assert 10.0 < profile.quote.amplitude_pct < 11.0


def test_helper_mcap_yi_divides_by_1e8(empty_memberships):
    """total_mv/1e8 → mcap_yi; circ_mv/1e8 → float_mcap_yi。"""
    quote = _make_unified_quote(total_mv=1e10, circ_mv=5e9)
    m = _make_manager(quote=quote)
    profile = build_stock_profile(m, "300750")
    assert profile.quote.mcap_yi == 100.0
    assert profile.quote.float_mcap_yi == 50.0


def test_helper_boards_from_ths_cache(monkeypatch):
    """boards = {source:'persistence', data:merged} when ths_cached + enrichment present."""
    cached_entry = {
        "board_code": "300750",
        "name": "宁德时代",
        "board_type": "concept",
        "subtype": "industry",
        "source": "ths",
    }
    fetcher_full = [
        {"board_code": "300750", "name": "宁德时代", "change_pct": 20.0, "limit_up_count": 1},
    ]
    monkeypatch.setattr(
        stock_board_cache,
        "get_stock_memberships",
        lambda stock_code, sources, manager=None, **kw: ([cached_entry], [], "persistence"),
    )
    monkeypatch.setattr(
        sb_helper,
        "fetch_stock_boards_quote_enrichment",
        lambda stock_code, manager: (
            fetcher_full,
            {"300750": {"change_pct": 20.0, "limit_up_count": 1}},
        ),
    )

    m = _make_manager()
    profile = build_stock_profile(m, "300750")

    assert profile.boards is not None
    assert profile.boards["source"] == "persistence"
    assert len(profile.boards["data"]) == 1
    entry = profile.boards["data"][0]
    assert entry["code"] == "300750"
    assert entry["change_pct"] == 20.0  # from enrichment
    assert entry["limit_up_count"] == 1


def test_helper_boards_from_fetcher_full(monkeypatch):
    """没有 ths_cached 但有 fetcher_full → boards = {source:'ths', data:fetcher_full}。"""
    fetcher_full = [{"board_code": "300750", "name": "宁德时代", "change_pct": 20.0}]
    monkeypatch.setattr(
        stock_board_cache,
        "get_stock_memberships",
        lambda stock_code, sources, manager=None, **kw: ([], [], "persistence"),
    )
    monkeypatch.setattr(
        sb_helper,
        "fetch_stock_boards_quote_enrichment",
        lambda stock_code, manager: (fetcher_full, {}),
    )
    m = _make_manager()
    profile = build_stock_profile(m, "300750")
    assert profile.boards is not None
    assert profile.boards["source"] == "ths"
    # boards["data"] is the boundary-mapped view of the raw fetcher rows
    # (internal board_code → public code; ths_cid dropped; board_type absent
    # on this fixture → public type None).
    assert profile.boards["data"] == [
        {"code": "300750", "name": "宁德时代", "change_pct": 20.0, "type": None}
    ]


def test_helper_boards_failure_appends_error(monkeypatch):
    """get_stock_memberships 抛错 → boards aspect 失败。"""
    from stock_data.data_provider.base import DataFetchError

    def _raise(*args, **kwargs):
        raise DataFetchError("board cache down")

    monkeypatch.setattr(
        stock_board_cache,
        "get_stock_memberships",
        _raise,
    )
    m = _make_manager(quote=_make_unified_quote())
    profile = build_stock_profile(m, "300750")
    assert profile.boards is None
    aspects = [e for e in profile.errors if e.aspect == "boards"]
    assert len(aspects) == 1


def test_helper_include_features_false_skips_kline(empty_memberships):
    """include_features=False → 跳过 kline fetch + build_features,profile.features 为 None,
    且不会 append features aspect error。"""
    df = pd.DataFrame({"close": [10.0, 11.0]})
    m = _make_manager(quote=_make_unified_quote(), kline_df=df)
    profile = build_stock_profile(m, "300750", include_features=False)
    # quote 仍然计算
    assert profile.quote is not None
    # features 跳过 → None
    assert profile.features is None
    # kline 没被调用
    assert not m.get_kline_data.called
    # errors 中没有 features aspect
    aspects = [e.aspect for e in profile.errors]
    assert "features" not in aspects
    # ok 仍为 True（quote + info + boards 都有值）
    assert profile.ok is True


def test_helper_include_features_false_omits_features_error(empty_memberships):
    """include_features=False 时即使 kline 上游坏掉也不报错（因为不调用）。"""
    m = _make_manager(quote=_make_unified_quote())
    m.get_kline_data.side_effect = Exception("kline would have failed")
    profile = build_stock_profile(m, "300750", include_features=False)
    assert profile.features is None
    # 没有 features aspect error
    aspects = [e.aspect for e in profile.errors]
    assert "features" not in aspects
