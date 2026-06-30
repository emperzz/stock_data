"""
Unit tests for ``data_provider.utils.normalize.code_to_exchange``.

Pure function — no network, no fixtures. Covers:

- A-share SH prefixes (main board + STAR)
- A-share SZ prefixes (main board + ChiNext)
- A-share BJ prefixes (3-digit + 1-digit)
- Non-A-share codes (HK, US) → None
- Code normalization in input (SH600519, 600519.SS, etc.)
- Invalid input (empty, non-numeric, wrong length) → None

Mirrors the prefix table in ``data_provider/utils/normalize.py`` — if a
new board prefix is added there, this file must follow.
"""

import pytest

from stock_data.data_provider.utils.normalize import code_to_exchange


# ---- Shanghai (SSE) ----
class TestShanghai:
    @pytest.mark.parametrize(
        "code",
        [
            "600519",  # Kweichow Moutai — main board
            "601318",  # Ping An Insurance — main board
            "603259",  # 药明康德 — main board
            "605499",  # 京东物流 — main board
            "688981",  # SMIC — STAR Market
            "689009",  # STAR
        ],
    )
    def test_sh_prefixes(self, code):
        assert code_to_exchange(code) == "SH"


# ---- Shenzhen (SZSE) ----
class TestShenzhen:
    @pytest.mark.parametrize(
        "code",
        [
            "000001",  # 平安银行 — main board
            "000002",  # 万科A
            "001979",  # 招商蛇口
            "002415",  # 海康威视
            "003816",  # 中国广核
            "300750",  # CATL — ChiNext
            "301236",  # ChiNext
            "302132",  # ChiNext
        ],
    )
    def test_sz_prefixes(self, code):
        assert code_to_exchange(code) == "SZ"


# ---- Beijing (BSE) ----
class TestBeijing:
    @pytest.mark.parametrize(
        "code",
        [
            "920000",  # 3-digit "920" prefix
            "920123",
            "830799",  # 1-digit "8" prefix (NEEQ)
            "832000",  # 1-digit "8" prefix
            "400001",  # 1-digit "4" prefix (legacy)
        ],
    )
    def test_bj_prefixes(self, code):
        assert code_to_exchange(code) == "BJ"


# ---- Non-A-share returns None ----
class TestNonAShare:
    @pytest.mark.parametrize(
        "code",
        [
            "HK00700",  # Tencent
            "HK01810",  # Xiaomi
            "HK00939",  # 建设银行
            "AAPL",     # US
            "TSLA",     # US
            "MSFT",     # US
        ],
    )
    def test_non_a_share_returns_none(self, code):
        assert code_to_exchange(code) is None


# ---- Input normalization (tolerates common inbound forms) ----
class TestInputNormalization:
    """The route receives whatever the user typed; the helper must
    strip SH/SZ/BJ prefix and .SS/.SZ/.HK suffix."""

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("SH600519", "SH"),     # bare prefix
            ("SZ000001", "SZ"),
            ("BJ830799", "BJ"),
            ("600519.SS", "SH"),    # yfinance suffix
            ("000001.SZ", "SZ"),
            ("830799.BJ", "BJ"),
            ("600519.SH", "SH"),    # other suffix forms
            ("000001.SZ", "SZ"),
            ("sh600519", "SH"),     # case-insensitive
            ("SZ000001", "SZ"),
        ],
    )
    def test_strip_prefix_and_suffix(self, raw, expected):
        assert code_to_exchange(raw) == expected


# ---- Invalid / edge input → None ----
class TestInvalidInput:
    @pytest.mark.parametrize(
        "code",
        [
            "",            # empty
            "  ",          # whitespace
            "12345",       # 5 digits
            "1234567",     # 7 digits
            "12345a",      # non-numeric
            "abcdef",      # 6 letters (could be confused with US, but US is
                           # 1-5 letters — 6 letters is invalid)
            "600",         # 3 digits
        ],
    )
    def test_invalid_returns_none(self, code):
        assert code_to_exchange(code) is None


# ---- 1-digit Beijing prefix must not shadow 3-digit Shanghai/Shenzhen ----
class TestPrefixOrder:
    """Regression: ``A_SHARE_STOCK_PREFIXES`` orders 1-digit Beijing
    prefixes last, and ``_CODE_PREFIX_TO_EXCHANGE`` mirrors that. If
    anyone reorders and puts "8" before "688", STAR Market (688xxx)
    would mis-classify as Beijing."""

    @pytest.mark.parametrize(
        "code,expected",
        [
            ("688981", "SH"),   # STAR — must NOT be matched as "8" → BJ
            ("689009", "SH"),
            ("830799", "BJ"),   # BSE — "8" prefix
            ("830000", "BJ"),
        ],
    )
    def test_prefix_disambiguation(self, code, expected):
        assert code_to_exchange(code) == expected
