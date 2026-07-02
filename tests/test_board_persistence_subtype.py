"""
Tests for board persistence subtype validation.

Validates that ``_validate_subtype`` correctly enforces the subtype
constraints declared in ``VALID_SUBTYPES_BY_SOURCE`` for each source
and board type combination.
"""

from __future__ import annotations

import pytest

from stock_data.data_provider.persistence.board import (
    _validate_subtype,
)

# ── happy paths: zhitu subtypes ──────────────────────────────────────────


def test_valid_subtypes_for_zhitu_industry():
    """zhitu/industry should accept the three 申万/证监会 industry subtypes."""
    for subtype in ("申万行业", "申万二级", "证监会行业"):
        # Should not raise
        _validate_subtype(source="zhitu", board_type="industry", subtype=subtype)


def test_valid_subtypes_for_zhitu_concept():
    """zhitu/concept should accept the three concept subtypes."""
    for subtype in ("热门概念", "概念板块", "地域板块"):
        # Should not raise
        _validate_subtype(source="zhitu", board_type="concept", subtype=subtype)


def test_valid_subtypes_for_zhitu_index():
    """zhitu/index should accept the three index subtypes."""
    for subtype in ("分类", "指数成分", "大盘指数"):
        # Should not raise
        _validate_subtype(source="zhitu", board_type="index", subtype=subtype)


def test_valid_subtypes_for_zhitu_special():
    """zhitu/special should accept the four special pool subtypes."""
    for subtype in ("风险警示", "次新股", "沪港通", "深港通"):
        # Should not raise
        _validate_subtype(source="zhitu", board_type="special", subtype=subtype)


# ── zhitu negative cases ────────────────────────────────────────────────


def test_invalid_subtype_for_zhitu_raises():
    """zhitu/concept with an unknown subtype should raise ValueError."""
    with pytest.raises(ValueError, match="不存在"):
        _validate_subtype(source="zhitu", board_type="concept", subtype="不存在")


def test_subtype_for_zhitu_with_wrong_type_raises():
    """A zhitu/industry subtype passed to zhitu/concept should be rejected."""
    with pytest.raises(ValueError, match="申万行业"):
        _validate_subtype(source="zhitu", board_type="concept", subtype="申万行业")


# ── eastmoney mirrors its board_type ────────────────────────────────────


def test_eastmoney_subtypes_mirror_type():
    """eastmoney uses a single subtype that mirrors the board_type name."""
    # eastmoney/concept accepts "concept"
    _validate_subtype(source="eastmoney", board_type="concept", subtype="concept")
    # eastmoney/industry accepts "industry"
    _validate_subtype(source="eastmoney", board_type="industry", subtype="industry")


def test_eastmoney_invalid_subtype_raises():
    """eastmoney/concept with a non-mirroring subtype should be rejected."""
    with pytest.raises(ValueError, match="热门概念"):
        _validate_subtype(source="eastmoney", board_type="concept", subtype="热门概念")


# ── None always valid ───────────────────────────────────────────────────


def test_none_subtype_always_valid():
    """None subtype (meaning 'all subtypes') should pass validation regardless."""
    for source in ("eastmoney", "zhitu"):
        for board_type in ("concept", "industry", "index", "special"):
            # Should not raise
            _validate_subtype(source=source, board_type=board_type, subtype=None)
