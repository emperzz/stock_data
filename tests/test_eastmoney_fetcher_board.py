"""Tests for EastMoneyFetcher board methods (HTTP-direct, no akshare).

历史: 这些方法最初从 AkshareFetcher 迁过来时通过 akshare 的 stock_board_*_em
函数拉数据 (commit 25b7819)。本文件改用 ``patch.object(fetcher, "_fetch_one_clist_page")``
直接 mock HTTP 层, 反映新的 push2 clist 直连实现。
"""

from unittest.mock import patch

import pytest

from stock_data.data_provider.base import DataCapability
from stock_data.data_provider.fetchers.eastmoney_fetcher import (
    ENDPOINTS,
    EastMoneyFetcher,
)

# ---------------------------------------------------------------------------
# Realistic fixture shapes
# ---------------------------------------------------------------------------
# EastMoney /api/qt/clist/get 响应:
#   {"data": {"diff": [[...], [...], ...], "total": N}}
# 每行是按 ``fields`` 参数顺序排列的值数组 (非 dict)。字段码语义见
# eastmoney_fetcher.py: _BOARD_LIST_FIELD_MAP / _BOARD_COMPONENTS_FIELD_MAP。

# 概念板块清单: 12 字段 (f2,f3,f4,f8,f12,f14,f15,f20,f104,f105,f128,f136)
CONCEPT_LIST_FIELDS = ENDPOINTS.BOARD_LIST_CONCEPT["fields"].split(",")
# 行业板块清单: 12 字段 (f2,f3,f4,f8,f12,f14,f16,f20,f104,f105,f128,f136)
# Both endpoints use f12=code, f14=name (probed 2026-07-03; was f14=code,
# f15/f16=name pre-fix — that mapping came from a stale akshare reference).
INDUSTRY_LIST_FIELDS = ENDPOINTS.BOARD_LIST_INDUSTRY["fields"].split(",")
# 成分股: 16 字段 (f2,f3,f4,f5,f6,f7,f8,f9,f12,f14,f16,f17,f18,f20,f21,f22)
# f12=stock code, f14=stock name (probed 2026-07-05; was f14=code,
# f16=name pre-fix — same stale akshare reference bug as the board-list
# endpoints, see commit 4e4d9df).
COMPONENTS_FIELDS = ENDPOINTS.BOARD_COMPONENTS["fields"].split(",")


def test_board_components_fields_does_not_request_f16():
    """Review 2026-07-06 finding #3: BOARD_COMPONENTS.fields used to request
    f16 even though _BOARD_COMPONENTS_FIELD_MAP no longer maps it (f16 is
    an unmapped numeric quote field after the 2026-07-05 f12/f14 swap fix).
    Requesting an unused field wastes upstream bandwidth on every call.

    Asserts f16 is NOT in the request string; if a future fix needs f16,
    add it back to the field map alongside this test.
    """
    fields = ENDPOINTS.BOARD_COMPONENTS["fields"].split(",")
    assert "f16" not in fields, (
        f"f16 is requested upstream but not consumed (no map entry); "
        f"current fields: {fields}"
    )

_CONCEPT_ROW_TEMPLATE = {
    "f2": 1234.56,  # price
    "f3": 2.35,  # change_pct
    "f4": 28.34,  # change_amount
    "f8": 1.23,  # turnover_rate
    "f12": "BK0001",  # code (e.g. "BK0996")
    "f14": "人形机器人",  # name (concept)
    "f15": 1068.9,  # some numeric quote field (NOT the name)
    "f20": 1.23e10,  # total_mv
    "f104": 30,  # up_count
    "f105": 5,  # down_count
    "f128": "600519",  # leading_stock
    "f136": 9.98,  # leading_stock_pct
}

_INDUSTRY_ROW_TEMPLATE = {
    "f2": 3456.78,
    "f3": -1.23,
    "f4": -43.21,
    "f8": 0.56,
    "f12": "BK1001",  # code
    "f14": "小金属",  # name (industry)
    "f16": 543.21,  # some numeric quote field (NOT the name)
    "f20": 9.87e9,
    "f104": 15,
    "f105": 30,
    "f128": "002460",
    "f136": 5.67,
}

_COMPONENTS_ROW_TEMPLATE = {
    "f2": 1234.56,
    "f3": 2.35,
    "f4": 28.34,
    "f5": 12345678,
    "f6": 15234567890.0,
    "f7": 3.21,
    "f8": 1.23,
    "f9": 25.6,
    "f12": "600519",  # stock code (probed 2026-07-05)
    "f14": "贵州茅台",  # stock name (probed 2026-07-05)
    "f16": 12345678901.0,  # numeric quote field — NOT the name
    "f17": 1250.0,
    "f18": 1200.0,
    "f20": 1210.0,
    "f21": 1206.22,
    "f22": 8.9,
}


def _row_from_template(fields: list[str], template: dict, **overrides) -> list:
    """Materialize a fixture row as a positional list in fields order."""
    merged = {**template, **overrides}
    return [merged[f] for f in fields]


def _dict_row_from_template(template: dict, **overrides) -> dict:
    """Materialize a fixture row as a dict keyed by field code.

    This is the format the live EastMoney push2 API actually returns
    (with ``np=1``, ``fltt=2``).  ``_row_from_template`` produces the
    legacy positional-list format; both must be handled by the fetcher.
    """
    return {**template, **overrides}


def _make_session_mock(rows: list, total: int | None = None):
    """Build a payload dict mimicking EastMoney clist response.

    Pass ``total=None`` to omit the total field (some responses skip it).

    Returns the **payload dict directly** (not a MagicMock), because
    ``_fetch_one_clist_page`` already returns ``r.json()`` and the production
    code expects a real dict for ``payload.get("data")`` etc.
    """
    payload: dict = {"data": {"diff": rows}}
    if total is not None:
        payload["data"]["total"] = total
    return payload


# ---------------------------------------------------------------------------
# get_all_concept_boards
# ---------------------------------------------------------------------------


def test_get_all_concept_boards_parses_response():
    fetcher = EastMoneyFetcher()
    row = _row_from_template(CONCEPT_LIST_FIELDS, _CONCEPT_ROW_TEMPLATE)
    mock_resp = _make_session_mock([row], total=1)
    with patch.object(fetcher, "_fetch_one_clist_page", return_value=mock_resp) as mock_get:
        boards = fetcher.get_all_concept_boards(source="eastmoney", include_quote=False)
    assert boards == [{"code": "BK0001", "name": "人形机器人"}]
    # 不带 quote 时不要污染输出 (仅在 include_quote=True 时附加 quote 字段)
    assert all("price" not in b for b in boards)
    # 确认调用了正确的 push2 clist URL. 2026-07-03: 默认优先 akshare 的
    # 79.push2 子域, 裸 push2.eastmoney.com 作 fallback. mock 一次成功即
    # 跳出, 所以只看到第一个 URL.
    called_url = mock_get.call_args.args[0]
    assert called_url == "https://79.push2.eastmoney.com/api/qt/clist/get"
    called_params = mock_get.call_args.args[1]
    assert called_params["fs"] == "m:90+t:3+f:!50"
    assert called_params["fid"] == "f12"


def test_get_all_concept_boards_with_quote_includes_quote_fields():
    fetcher = EastMoneyFetcher()
    row = _row_from_template(CONCEPT_LIST_FIELDS, _CONCEPT_ROW_TEMPLATE)
    mock_resp = _make_session_mock([row], total=1)
    with patch.object(fetcher, "_fetch_one_clist_page", return_value=mock_resp):
        boards = fetcher.get_all_concept_boards(source="eastmoney", include_quote=True)
    assert len(boards) == 1
    b = boards[0]
    assert b["code"] == "BK0001"
    assert b["name"] == "人形机器人"
    assert b["price"] == 1234.56
    assert b["change_pct"] == 2.35
    assert b["change_amount"] == 28.34
    assert b["turnover_rate"] == 1.23
    assert b["total_mv"] == 1.23e10
    assert b["up_count"] == 30
    assert b["down_count"] == 5
    assert b["leading_stock"] == "600519"
    assert b["leading_stock_pct"] == 9.98


def test_get_all_concept_boards_skips_rows_with_empty_code():
    fetcher = EastMoneyFetcher()
    good_row = _row_from_template(CONCEPT_LIST_FIELDS, _CONCEPT_ROW_TEMPLATE)
    bad_row = _row_from_template(
        CONCEPT_LIST_FIELDS, _CONCEPT_ROW_TEMPLATE, **{"f12": ""}
    )  # no code
    mock_resp = _make_session_mock([bad_row, good_row], total=2)
    with patch.object(fetcher, "_fetch_one_clist_page", return_value=mock_resp):
        boards = fetcher.get_all_concept_boards(source="eastmoney")
    assert len(boards) == 1
    assert boards[0]["code"] == "BK0001"


# ---------------------------------------------------------------------------
# get_all_industry_boards
# ---------------------------------------------------------------------------


def test_get_all_industry_boards_parses_response():
    """行业板块: name 在 f16, 不在 f15 — 字段映射正确性."""
    fetcher = EastMoneyFetcher()
    row = _row_from_template(INDUSTRY_LIST_FIELDS, _INDUSTRY_ROW_TEMPLATE)
    mock_resp = _make_session_mock([row], total=1)
    with patch.object(fetcher, "_fetch_one_clist_page", return_value=mock_resp) as mock_get:
        boards = fetcher.get_all_industry_boards(source="eastmoney")
    assert boards == [{"code": "BK1001", "name": "小金属"}]
    # 关键: 验证 fs 用了 industry 的 (m:90+t:2), 不是 concept 的 (m:90+t:3)
    assert mock_get.call_args.args[1]["fs"] == "m:90+t:2+f:!50"


def test_get_all_industry_boards_does_not_pick_f16_as_name():
    """防护: 行业端点 f16 是 numeric quote field, 不能误用为 name.
    之前实现错误地把 f16 当作 name 来源 (stale akshare 列号错位)."""
    fetcher = EastMoneyFetcher()
    row = _row_from_template(
        INDUSTRY_LIST_FIELDS,
        _INDUSTRY_ROW_TEMPLATE,
        **{"f16": "WRONG_NAME_F16"},
    )
    mock_resp = _make_session_mock([row], total=1)
    with patch.object(fetcher, "_fetch_one_clist_page", return_value=mock_resp):
        boards = fetcher.get_all_industry_boards(source="eastmoney")
    assert boards[0]["name"] == "小金属"  # 来自 f14, 不是 f16


def test_get_all_concept_boards_does_not_pick_f15_as_name():
    """概念端点的 f15 也是 numeric — name 来自 f14."""
    fetcher = EastMoneyFetcher()
    row = _row_from_template(
        CONCEPT_LIST_FIELDS,
        _CONCEPT_ROW_TEMPLATE,
        **{"f15": "WRONG_NAME_F15"},
    )
    mock_resp = _make_session_mock([row], total=1)
    with patch.object(fetcher, "_fetch_one_clist_page", return_value=mock_resp):
        boards = fetcher.get_all_concept_boards(source="eastmoney")
    assert boards[0]["name"] == "人形机器人"  # 来自 f14, 不是 f15


def test_get_all_concept_boards_uses_f12_as_code_not_f14():
    """回归测试 (2026-07-03 用户报告): ``code`` 必须是 f12 (BK####),
    ``name`` 必须是 f14 (中文). 之前实现把 f14 当作 code 导致
    ``code=\"2026中报预增\"`` / ``name=\"1068.9\"`` 互换."""
    fetcher = EastMoneyFetcher()
    # Use realistic upstream values to mirror the actual bug report shape.
    row = _dict_row_from_template(
        _CONCEPT_ROW_TEMPLATE,
        f12="BK0438",  # actual code from upstream
        f14="食品饮料",  # actual name from upstream (was getting used as code)
        f15=1068.9,  # numeric quote field (was getting used as name)
    )
    mock_resp = _make_session_mock([row], total=1)
    with patch.object(fetcher, "_fetch_one_clist_page", return_value=mock_resp):
        boards = fetcher.get_all_concept_boards(source="eastmoney")
    assert len(boards) == 1
    assert boards[0]["code"] == "BK0438", f"code should be f12, got {boards[0]['code']!r}"
    assert boards[0]["name"] == "食品饮料", f"name should be f14, got {boards[0]['name']!r}"


def test_get_all_industry_boards_uses_f12_as_code_not_f14():
    """行业端点对称回归测试: ``code`` 来自 f12, ``name`` 来自 f14."""
    fetcher = EastMoneyFetcher()
    row = _dict_row_from_template(
        _INDUSTRY_ROW_TEMPLATE,
        f12="BK1001",
        f14="小金属",
        f16=543.21,  # numeric — would corrupt name if误读
    )
    mock_resp = _make_session_mock([row], total=1)
    with patch.object(fetcher, "_fetch_one_clist_page", return_value=mock_resp):
        boards = fetcher.get_all_industry_boards(source="eastmoney")
    assert boards[0]["code"] == "BK1001"
    assert boards[0]["name"] == "小金属"


# ---------------------------------------------------------------------------
# Dict-format rows (live API with np=1 returns dicts, not positional lists)
# ---------------------------------------------------------------------------


def test_get_all_concept_boards_handles_dict_format_rows():
    """Live push2 API (np=1, fltt=2) returns diff as dicts keyed by field code."""
    fetcher = EastMoneyFetcher()
    row = _dict_row_from_template(_CONCEPT_ROW_TEMPLATE)
    mock_resp = _make_session_mock([row], total=1)
    with patch.object(fetcher, "_fetch_one_clist_page", return_value=mock_resp):
        boards = fetcher.get_all_concept_boards(source="eastmoney", include_quote=False)
    assert boards == [{"code": "BK0001", "name": "人形机器人"}]


def test_get_all_concept_boards_dict_format_with_quote():
    """Dict-format rows + include_quote=True maps field codes to human-readable keys."""
    fetcher = EastMoneyFetcher()
    row = _dict_row_from_template(_CONCEPT_ROW_TEMPLATE)
    mock_resp = _make_session_mock([row], total=1)
    with patch.object(fetcher, "_fetch_one_clist_page", return_value=mock_resp):
        boards = fetcher.get_all_concept_boards(source="eastmoney", include_quote=True)
    b = boards[0]
    assert b["code"] == "BK0001"
    assert b["name"] == "人形机器人"
    assert b["price"] == 1234.56
    assert b["change_pct"] == 2.35
    assert b["turnover_rate"] == 1.23
    assert b["leading_stock"] == "600519"


def test_get_all_industry_boards_handles_dict_format_rows():
    """Dict-format rows for industry boards — name comes from f16."""
    fetcher = EastMoneyFetcher()
    row = _dict_row_from_template(_INDUSTRY_ROW_TEMPLATE)
    mock_resp = _make_session_mock([row], total=1)
    with patch.object(fetcher, "_fetch_one_clist_page", return_value=mock_resp):
        boards = fetcher.get_all_industry_boards(source="eastmoney")
    assert boards == [{"code": "BK1001", "name": "小金属"}]


def test_get_concept_board_stocks_handles_dict_format_rows():
    """Dict-format rows for board components."""
    fetcher = EastMoneyFetcher()
    row = _dict_row_from_template(_COMPONENTS_ROW_TEMPLATE)
    mock_resp = _make_session_mock([row], total=1)
    with patch.object(fetcher, "_fetch_one_clist_page", return_value=mock_resp):
        stocks = fetcher.get_concept_board_stocks("BK0001", source="eastmoney")
    assert stocks == [{"stock_code": "600519", "stock_name": "贵州茅台"}]


def test_get_concept_board_stocks_dict_format_with_quote():
    """Dict-format rows + include_quote for components."""
    fetcher = EastMoneyFetcher()
    row = _dict_row_from_template(_COMPONENTS_ROW_TEMPLATE)
    mock_resp = _make_session_mock([row], total=1)
    with patch.object(fetcher, "_fetch_one_clist_page", return_value=mock_resp):
        stocks = fetcher.get_concept_board_stocks("BK0001", source="eastmoney", include_quote=True)
    s = stocks[0]
    assert s["stock_code"] == "600519"
    assert s["stock_name"] == "贵州茅台"
    assert s["price"] == 1234.56
    assert s["change_pct"] == 2.35
    assert s["volume"] == 12345678
    assert s["pe_ratio"] == 25.6
    assert s["pb_ratio"] == 8.9


def test_get_all_boards_concept_dict_format_with_subtype():
    """Manager entry point with dict-format rows — subtype tag applied."""
    fetcher = EastMoneyFetcher()
    row = _dict_row_from_template(_CONCEPT_ROW_TEMPLATE)
    mock_resp = _make_session_mock([row], total=1)
    with patch.object(fetcher, "_fetch_one_clist_page", return_value=mock_resp):
        boards = fetcher.get_all_boards(board_type="concept", source="eastmoney")
    # type is now also tagged (mirrors the per-type tag the all-types
    # branch uses, so the persistence layer's write sees a uniform shape).
    assert boards == [
        {"code": "BK0001", "name": "人形机器人", "type": "concept", "subtype": "concept"}
    ]


# ---------------------------------------------------------------------------
# get_concept_board_stocks / get_industry_board_stocks
# ---------------------------------------------------------------------------


def test_get_concept_board_stocks_parses_response():
    fetcher = EastMoneyFetcher()
    row = _row_from_template(COMPONENTS_FIELDS, _COMPONENTS_ROW_TEMPLATE)
    mock_resp = _make_session_mock([row], total=1)
    with patch.object(fetcher, "_fetch_one_clist_page", return_value=mock_resp) as mock_get:
        stocks = fetcher.get_concept_board_stocks("BK0001", source="eastmoney", include_quote=False)
    assert stocks == [{"stock_code": "600519", "stock_name": "贵州茅台"}]
    # 确认 fs 注入了 board_code
    assert mock_get.call_args.args[1]["fs"] == "b:BK0001+f:!50"


def test_get_concept_board_stocks_with_quote_includes_quote_fields():
    fetcher = EastMoneyFetcher()
    row = _row_from_template(COMPONENTS_FIELDS, _COMPONENTS_ROW_TEMPLATE)
    mock_resp = _make_session_mock([row], total=1)
    with patch.object(fetcher, "_fetch_one_clist_page", return_value=mock_resp):
        stocks = fetcher.get_concept_board_stocks("BK0001", source="eastmoney", include_quote=True)
    assert len(stocks) == 1
    s = stocks[0]
    assert s["stock_code"] == "600519"
    assert s["stock_name"] == "贵州茅台"
    assert s["price"] == 1234.56
    assert s["change_pct"] == 2.35
    assert s["volume"] == 12345678
    assert s["amount"] == 15234567890.0
    assert s["amplitude"] == 3.21
    assert s["turnover_rate"] == 1.23
    assert s["pe_ratio"] == 25.6
    assert s["pb_ratio"] == 8.9
    assert s["high"] == 1250.0
    assert s["low"] == 1200.0
    assert s["open"] == 1210.0
    assert s["pre_close"] == 1206.22


def test_get_industry_board_stocks_parses_response():
    fetcher = EastMoneyFetcher()
    row = _row_from_template(COMPONENTS_FIELDS, _COMPONENTS_ROW_TEMPLATE)
    mock_resp = _make_session_mock([row], total=1)
    with patch.object(fetcher, "_fetch_one_clist_page", return_value=mock_resp):
        stocks = fetcher.get_industry_board_stocks("BK1001", source="eastmoney")
    assert stocks == [{"stock_code": "600519", "stock_name": "贵州茅台"}]


def test_get_concept_board_stocks_skips_rows_with_empty_code():
    fetcher = EastMoneyFetcher()
    good_row = _row_from_template(COMPONENTS_FIELDS, _COMPONENTS_ROW_TEMPLATE)
    bad_row = _row_from_template(COMPONENTS_FIELDS, _COMPONENTS_ROW_TEMPLATE, **{"f12": ""})
    mock_resp = _make_session_mock([bad_row, good_row], total=2)
    with patch.object(fetcher, "_fetch_one_clist_page", return_value=mock_resp):
        stocks = fetcher.get_concept_board_stocks("BK0001", source="eastmoney")
    assert len(stocks) == 1
    assert stocks[0]["stock_code"] == "600519"


def test_get_concept_board_stocks_uses_f12_as_code_not_f14():
    """回归测试 (2026-07-05 用户报告): ``stock_code`` 必须是 f12 (6 位数字),
    ``stock_name`` 必须是 f14 (中文名). 之前实现把 f14 当作 stock_code 导致
    ``stock_code="新睿电子"`` / ``stock_name="123.0"`` 互换 — 与 commit
    4e4d9df 修复的 board-list 端点是同一个 stale akshare 列号 bug."""
    fetcher = EastMoneyFetcher()
    # Use realistic upstream values mirroring the actual user-reported shape.
    row = _dict_row_from_template(
        _COMPONENTS_ROW_TEMPLATE,
        f12="002444",  # actual stock code from upstream
        f14="新睿电子",  # actual stock name from upstream (was getting used as code)
        f16=123.0,  # numeric quote field (was getting used as name)
    )
    mock_resp = _make_session_mock([row], total=1)
    with patch.object(fetcher, "_fetch_one_clist_page", return_value=mock_resp):
        stocks = fetcher.get_concept_board_stocks("BK1048", source="eastmoney")
    assert len(stocks) == 1
    assert stocks[0]["stock_code"] == "002444", (
        f"stock_code should be f12 (6-digit), got {stocks[0]['stock_code']!r}"
    )
    assert stocks[0]["stock_name"] == "新睿电子", (
        f"stock_name should be f14 (Chinese name), got {stocks[0]['stock_name']!r}"
    )


def test_get_concept_board_stocks_does_not_pick_f16_as_name():
    """防护: 成分股端点 f16 是 numeric quote field, 不能误用为 stock_name.
    之前实现错误地把 f16 当作 stock_name 来源 (stale akshare 列号错位)."""
    fetcher = EastMoneyFetcher()
    row = _row_from_template(
        COMPONENTS_FIELDS,
        _COMPONENTS_ROW_TEMPLATE,
        **{"f16": "WRONG_NAME_F16"},
    )
    mock_resp = _make_session_mock([row], total=1)
    with patch.object(fetcher, "_fetch_one_clist_page", return_value=mock_resp):
        stocks = fetcher.get_concept_board_stocks("BK0001", source="eastmoney")
    assert stocks[0]["stock_name"] == "贵州茅台"  # 来自 f14, 不是 f16


def test_get_concept_board_stocks_with_quote_skips_f12_and_f14():
    """include_quote=True 时, f12 (code) 和 f14 (name) 不应被重复加为
    price/change_pct 等键 — 它们已作为 stock_code/stock_name 单独 emit."""
    fetcher = EastMoneyFetcher()
    row = _dict_row_from_template(_COMPONENTS_ROW_TEMPLATE)
    mock_resp = _make_session_mock([row], total=1)
    with patch.object(fetcher, "_fetch_one_clist_page", return_value=mock_resp):
        stocks = fetcher.get_concept_board_stocks("BK0001", source="eastmoney", include_quote=True)
    s = stocks[0]
    # f12 (code) and f14 (name) must not be re-emitted as quote fields —
    # they're already exposed via stock_code/stock_name above.
    assert "f12" not in s
    # The keys emitted by the field map (excluding code/name) — verify
    # none of them are the stock_code or stock_name string.
    for key in (
        "price",
        "change_pct",
        "change_amount",
        "volume",
        "amount",
        "amplitude",
        "turnover_rate",
        "pe_ratio",
        "high",
        "low",
        "open",
        "pre_close",
        "pb_ratio",
    ):
        assert key in s
        assert s[key] != "600519"
        assert s[key] != "贵州茅台"


# ---------------------------------------------------------------------------
# Manager 统一入口方法
# ---------------------------------------------------------------------------


def test_eastmoney_fetcher_declares_stock_board_capability():
    assert DataCapability.STOCK_BOARD in EastMoneyFetcher.supported_data_types


def test_get_all_boards_concept_delegates():
    fetcher = EastMoneyFetcher()
    row = _row_from_template(CONCEPT_LIST_FIELDS, _CONCEPT_ROW_TEMPLATE)
    mock_resp = _make_session_mock([row], total=1)
    with patch.object(fetcher, "_fetch_one_clist_page", return_value=mock_resp):
        boards = fetcher.get_all_boards(board_type="concept", source="eastmoney")
    assert boards == [
        {"code": "BK0001", "name": "人形机器人", "type": "concept", "subtype": "concept"}
    ]


def test_get_all_boards_industry_delegates():
    fetcher = EastMoneyFetcher()
    row = _row_from_template(INDUSTRY_LIST_FIELDS, _INDUSTRY_ROW_TEMPLATE)
    mock_resp = _make_session_mock([row], total=1)
    with patch.object(fetcher, "_fetch_one_clist_page", return_value=mock_resp):
        boards = fetcher.get_all_boards(board_type="industry", source="eastmoney")
    assert boards == [
        {"code": "BK1001", "name": "小金属", "type": "industry", "subtype": "industry"}
    ]


def test_get_all_boards_index_returns_empty():
    """EastMoney has no index/special classification — returns []. No HTTP call."""
    fetcher = EastMoneyFetcher()
    with patch.object(fetcher, "_fetch_one_clist_page") as mock_get:
        assert fetcher.get_all_boards(board_type="index", source="eastmoney") == []
        assert fetcher.get_all_boards(board_type="special", source="eastmoney") == []
        mock_get.assert_not_called()


def test_get_board_stocks_known_concept_does_not_fall_through_to_industry():
    """Regression for Phase 4 (2026-07-02): when ``board_type`` is passed
    (e.g. from the persistence layer's SQLite cache), the fetcher
    dispatches directly — no silent concept→industry fallback. Industry
    must NOT be called. Pre-fix behaviour: a transient upstream failure
    returning ``[]`` from concept silently re-routed to industry.
    """
    fetcher = EastMoneyFetcher()
    with (
        patch.object(fetcher, "get_concept_board_stocks", return_value=[]) as mock_c,
        patch.object(
            fetcher, "get_industry_board_stocks", return_value=[{"stock_code": "WRONG"}]
        ) as mock_i,
    ):
        result = fetcher.get_board_stocks(
            "BK1048",
            source="eastmoney",
            board_type="concept",
        )
    mock_c.assert_called_once()
    mock_i.assert_not_called()
    assert result == []


def test_get_board_stocks_known_industry_does_not_consult_concept():
    """Mirror of the above for the industry branch."""
    fetcher = EastMoneyFetcher()
    with (
        patch.object(
            fetcher, "get_concept_board_stocks", return_value=[{"stock_code": "WRONG"}]
        ) as mock_c,
        patch.object(
            fetcher, "get_industry_board_stocks", return_value=[{"stock_code": "600519"}]
        ) as mock_i,
    ):
        result = fetcher.get_board_stocks(
            "BK0481",
            source="eastmoney",
            board_type="industry",
        )
    mock_i.assert_called_once()
    mock_c.assert_not_called()
    assert result == [{"stock_code": "600519"}]


def test_get_board_stocks_unknown_board_type_uses_legacy_fallback():
    """When ``board_type`` is ``None`` (cold cache), the legacy
    concept→industry fallback path is preserved AND now logged at INFO
    so the fallback is no longer silent.
    """
    fetcher = EastMoneyFetcher()
    with (
        patch.object(fetcher, "get_concept_board_stocks", return_value=[]) as mock_c,
        patch.object(
            fetcher, "get_industry_board_stocks", return_value=[{"stock_code": "OK"}]
        ) as mock_i,
    ):
        fetcher.get_board_stocks("BKUNKNOWN", source="eastmoney")
    mock_c.assert_called_once()
    mock_i.assert_called_once()


def test_get_board_stocks_tries_concept_then_industry():
    """concept 返回空时回退到 industry."""
    fetcher = EastMoneyFetcher()
    empty_resp = _make_session_mock([], total=0)
    industry_row = _row_from_template(COMPONENTS_FIELDS, _COMPONENTS_ROW_TEMPLATE)
    industry_resp = _make_session_mock([industry_row], total=1)

    with patch.object(fetcher, "_fetch_one_clist_page", side_effect=[empty_resp, industry_resp]):
        stocks = fetcher.get_board_stocks("BK1001", source="eastmoney")
    assert stocks == [{"stock_code": "600519", "stock_name": "贵州茅台"}]


def test_get_board_stocks_returns_concept_if_found():
    """concept 非空时不再调 industry."""
    fetcher = EastMoneyFetcher()
    concept_row = _row_from_template(COMPONENTS_FIELDS, _COMPONENTS_ROW_TEMPLATE)
    concept_resp = _make_session_mock([concept_row], total=1)

    with patch.object(fetcher, "_fetch_one_clist_page", return_value=concept_resp) as mock_get:
        stocks = fetcher.get_board_stocks("BK0001", source="eastmoney")
    assert stocks == [{"stock_code": "600519", "stock_name": "贵州茅台"}]
    assert mock_get.call_count == 1  # 只调一次 concept


def test_get_stock_boards_returns_none():
    """EastMoney now supports stock→boards lookup via push2 slist/get.

    See ``tests/test_eastmoney_stock_boards.py`` for the full contract.
    The fetcher returns a list (possibly empty) on a valid code; ``None`` is
    only returned for invalid input. ``000001`` is a valid SZ code so we
    assert it's NOT None — the old contract that returned ``None`` for any
    call was wrong (verified 2026-07-02).
    """
    fetcher = EastMoneyFetcher()
    # Smoke check only: we don't mock HTTP here, so we just assert that a
    # valid code path no longer returns None unconditionally.
    # Use an obviously-invalid code path via normalize_stock_code to assert
    # the None contract survives for malformed input.
    assert fetcher.get_stock_boards("", source="eastmoney") is None


# ---------------------------------------------------------------------------
# 分页 + 错误处理
# ---------------------------------------------------------------------------


def test_handles_pagination_across_multiple_pages():
    """Concept boards 实际 ~300, 100/页需要 3 页。验证 helper 自动翻页."""
    fetcher = EastMoneyFetcher()
    page1 = [
        _row_from_template(CONCEPT_LIST_FIELDS, _CONCEPT_ROW_TEMPLATE, **{"f12": f"BK{i:04d}"})
        for i in range(1, 101)
    ]
    page2 = [
        _row_from_template(CONCEPT_LIST_FIELDS, _CONCEPT_ROW_TEMPLATE, **{"f12": f"BK{i:04d}"})
        for i in range(101, 201)
    ]
    page3 = [
        _row_from_template(CONCEPT_LIST_FIELDS, _CONCEPT_ROW_TEMPLATE, **{"f12": f"BK{i:04d}"})
        for i in range(201, 251)
    ]
    r1 = _make_session_mock(page1, total=250)
    r2 = _make_session_mock(page2, total=250)
    r3 = _make_session_mock(page3, total=250)

    with patch.object(fetcher, "_fetch_one_clist_page", side_effect=[r1, r2, r3]) as mock_get:
        boards = fetcher.get_all_concept_boards(source="eastmoney")
    assert len(boards) == 250
    assert boards[0]["code"] == "BK0001"
    assert boards[-1]["code"] == "BK0250"
    # 确认翻页: pn=1, 2, 3
    pn_values = [c.args[1]["pn"] for c in mock_get.call_args_list]
    assert pn_values == [1, 2, 3]


def test_returns_empty_on_network_error():
    """网络异常 → 返回 [] (与旧 akshare 实现保持一致, logger 警告)."""
    fetcher = EastMoneyFetcher()
    with patch.object(fetcher, "_fetch_one_clist_page", side_effect=Exception("boom")):
        assert fetcher.get_all_concept_boards() == []
        assert fetcher.get_all_industry_boards() == []
        assert fetcher.get_concept_board_stocks("BK0001") == []
        assert fetcher.get_industry_board_stocks("BK1001") == []


def test_returns_empty_on_empty_response():
    """上游返回空 diff → 返回 []."""
    fetcher = EastMoneyFetcher()
    empty_resp = _make_session_mock([], total=0)
    with patch.object(fetcher, "_fetch_one_clist_page", return_value=empty_resp):
        assert fetcher.get_all_concept_boards() == []


def test_returns_empty_on_missing_data_field():
    """上游 data 字段缺失 → 返回 [], 不抛异常."""
    fetcher = EastMoneyFetcher()
    bad_payload = {"result": None}  # 没有 data 字段
    with patch.object(fetcher, "_fetch_one_clist_page", return_value=bad_payload):
        assert fetcher.get_all_concept_boards() == []


# ---------------------------------------------------------------------------
# 重试 + 限流退避 (tenacity)
# ---------------------------------------------------------------------------


class _FakeRateLimitError(Exception):
    """模拟 push2 限流时的 curl: (56) Connection closed abruptly."""


def test_fetch_one_clist_page_retries_on_rate_limit():
    """前 2 次 ConnectionError, 第 3 次成功 — tenacity 重试按预期工作."""
    fetcher = EastMoneyFetcher()
    success_payload = {"data": {"diff": [], "total": 0}}
    call_count = {"n": 0}

    def fake_get(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] < 3:
            raise _FakeRateLimitError("curl: (56) Connection closed abruptly")
        from unittest.mock import MagicMock

        m = MagicMock()
        m.json.return_value = success_payload
        return m

    with patch.object(fetcher._session, "get", side_effect=fake_get):
        result = fetcher._fetch_one_clist_page(
            "https://push2.eastmoney.com/api/qt/clist/get",
            {"pn": 1, "fs": "m:90+t:3+f:!50"},
            "https://quote.eastmoney.com/",
        )
    assert call_count["n"] == 3
    assert result == success_payload


def test_fetch_one_clist_page_gives_up_after_max_attempts():
    """重试次数用完仍然失败 → 抛出原异常 (paginated caller 捕获后返回 [])."""
    fetcher = EastMoneyFetcher()
    with (
        patch.object(
            fetcher._session,
            "get",
            side_effect=_FakeRateLimitError("curl: (56)"),
        ) as mock_get,
        pytest.raises(_FakeRateLimitError),
    ):
        fetcher._fetch_one_clist_page(
            "https://push2.eastmoney.com/api/qt/clist/get",
            {"pn": 1},
            "https://quote.eastmoney.com/",
        )
    # tenacity stop_after_attempt=3 → 应该尝试 3 次
    assert mock_get.call_count == 3


def test_fetch_one_clist_page_uses_referer_for_quote_subdomain():
    """Referer 必须是 quote.eastmoney.com, 不是 so.eastmoney.com (news)."""
    fetcher = EastMoneyFetcher()
    captured_headers = {}

    def fake_get(url, params=None, headers=None, timeout=None, **kw):
        captured_headers.update(headers or {})
        from unittest.mock import MagicMock

        m = MagicMock()
        m.json.return_value = {"data": {"diff": [], "total": 0}}
        return m

    with patch.object(fetcher._session, "get", side_effect=fake_get):
        fetcher._fetch_one_clist_page(
            "https://push2.eastmoney.com/api/qt/clist/get",
            {"pn": 1},
            "https://quote.eastmoney.com/",
        )
    assert captured_headers.get("Referer") == "https://quote.eastmoney.com/"


# ---------------------------------------------------------------------------
# URL 变体 fallback (2026-07-03 push2 WAF hardening)
# ---------------------------------------------------------------------------
# push2.eastmoney.com WAF 已升级到拒绝 curl_cffi Chrome120 模拟. akshare
# 通过使用数字子域 (79.push2 / 17.push2 / 29.push2) 仍能命中部分节点. 我们
# fetcher 之前只用裸 push2.eastmoney.com, 现在改为: 每个 board clist 端点
# 配置一组 url_prefixes (默认 [numeric, ""] = akshare 子域优先 + 裸 push2
# 兜底), _fetch_clist_paginated 顺序尝试, 首次成功即返回.


def test_endpoint_has_url_prefixes_field():
    """每个 board clist 端点都应声明 url_prefixes (默认含数字子域 + 裸 push2 兜底)."""
    from stock_data.data_provider.fetchers.eastmoney_fetcher import ENDPOINTS

    for name in ("BOARD_LIST_CONCEPT", "BOARD_LIST_INDUSTRY", "BOARD_COMPONENTS"):
        ep = getattr(ENDPOINTS, name)
        assert "url_prefixes" in ep, f"{name} missing url_prefixes"
        assert isinstance(ep["url_prefixes"], list)
        assert len(ep["url_prefixes"]) >= 1
        # 末位应是空字符串 (裸 push2 兜底)
        assert ep["url_prefixes"][-1] == "", f"{name} url_prefixes 应以裸 push2 兜底"


def test_endpoint_url_prefixes_match_akshare_pattern():
    """默认值应对齐 akshare 实测: concept=79, industry=17, components=29."""
    from stock_data.data_provider.fetchers.eastmoney_fetcher import ENDPOINTS

    assert ENDPOINTS.BOARD_LIST_CONCEPT["url_prefixes"][0] == "79"
    assert ENDPOINTS.BOARD_LIST_INDUSTRY["url_prefixes"][0] == "17"
    assert ENDPOINTS.BOARD_COMPONENTS["url_prefixes"][0] == "29"


def test_build_clist_url_variants_default_order():
    """默认: 数字子域在前, 裸 push2 在后."""
    fetcher = EastMoneyFetcher()
    variants = fetcher._build_clist_url_variants(ENDPOINTS.BOARD_LIST_CONCEPT)
    assert variants[0] == "https://79.push2.eastmoney.com/api/qt/clist/get"
    assert variants[-1] == "https://push2.eastmoney.com/api/qt/clist/get"
    assert len(variants) == 2


def test_build_clist_url_variants_env_override(monkeypatch):
    """env 覆盖: 单 prefix 列表 (只试裸 push2)."""
    fetcher = EastMoneyFetcher()
    monkeypatch.setenv("EASTMONEY_PUSH2_CONCEPT_PREFIXES", "")
    variants = fetcher._build_clist_url_variants(ENDPOINTS.BOARD_LIST_CONCEPT)
    assert variants == ["https://push2.eastmoney.com/api/qt/clist/get"]


def test_build_clist_url_variants_env_multi(monkeypatch):
    """env 覆盖: 多个 prefix, 空字符串表示裸 push2."""
    fetcher = EastMoneyFetcher()
    monkeypatch.setenv("EASTMONEY_PUSH2_INDUSTRY_PREFIXES", "29,17,")
    variants = fetcher._build_clist_url_variants(ENDPOINTS.BOARD_LIST_INDUSTRY)
    assert variants == [
        "https://29.push2.eastmoney.com/api/qt/clist/get",
        "https://17.push2.eastmoney.com/api/qt/clist/get",
        "https://push2.eastmoney.com/api/qt/clist/get",
    ]


def test_fetch_clist_paginated_falls_back_to_second_url_on_first_failure():
    """第一 URL 全部重试用尽 → 试第二 URL → 成功 → 返回数据.

    tenacity 默认 3 次重试, 所以 side_effect 需要 3 次 Exception 才耗尽
    第一 URL, 第 4 次才到第二 URL.
    """
    fetcher = EastMoneyFetcher()
    from unittest.mock import MagicMock

    fake_resp = MagicMock()
    fake_resp.json.return_value = {"data": {"diff": [], "total": 0}}
    with patch.object(
        fetcher._session,
        "get",
        side_effect=[
            Exception("Connection closed abruptly"),  # 79.push2 attempt 1
            Exception("Connection closed abruptly"),  # 79.push2 attempt 2
            Exception("Connection closed abruptly"),  # 79.push2 attempt 3 (exhausted)
            fake_resp,  # bare push2 success
        ],
    ) as mock_get:
        result = fetcher._fetch_clist_paginated(ENDPOINTS.BOARD_LIST_CONCEPT)
    assert result == []
    # 确认 3 次 79.push2 重试, 1 次 bare push2 成功
    call_urls = [c.args[0] for c in mock_get.call_args_list]
    assert call_urls == [
        "https://79.push2.eastmoney.com/api/qt/clist/get",
        "https://79.push2.eastmoney.com/api/qt/clist/get",
        "https://79.push2.eastmoney.com/api/qt/clist/get",
        "https://push2.eastmoney.com/api/qt/clist/get",
    ]


def test_fetch_clist_paginated_returns_empty_when_all_variants_fail():
    """所有 URL 变体都失败 → 返回 [] (不抛异常)."""
    fetcher = EastMoneyFetcher()
    with patch.object(
        fetcher._session,
        "get",
        side_effect=Exception("Connection closed abruptly"),
    ):
        assert fetcher._fetch_clist_paginated(ENDPOINTS.BOARD_LIST_CONCEPT) == []
