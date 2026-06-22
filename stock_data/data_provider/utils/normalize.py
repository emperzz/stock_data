"""
Stock code normalization and market detection utilities.
"""

from ..fetchers.index_symbols import get_index_type, is_index_code

__all__ = [
    "normalize_stock_code",
    "market_tag",
    "index_market_tag",
    "is_us_market",
    "is_hk_market",
    "is_index_code",
    "is_a_share_stock_code",
    "A_SHARE_STOCK_PREFIXES",
]

# A-share stock code prefixes (used to distinguish real stocks from
# ETFs/funds/indices on the Shanghai, Shenzhen, and Beijing exchanges).
# Hoisted from baostock_fetcher.get_all_stocks so the "what is a real
# A-share stock" definition lives in one place.
#
# - Shanghai main:    600, 601, 603, 605, 689
# - Shanghai STAR:    688
# - Shenzhen main:    001, 002, 003
# - ChiNext:          300, 301, 302
# - Beijing (BSE):    8 (1-digit prefix), 4, 920
#
# Note: the 1-digit "8" / "4" prefixes are matched first below so the
# 3-digit "920" doesn't shadow them.  ``is_a_share_stock_code`` handles
# the matching order correctly.
A_SHARE_STOCK_PREFIXES: tuple[str, ...] = (
    "600", "601", "603", "605", "689", "688",  # Shanghai
    "001", "002", "003",                       # Shenzhen main
    "300", "301", "302",                       # ChiNext
    "920",                                     # Beijing (3-digit)
    "8", "4",                                  # Beijing (1-digit, checked last)
)


def is_a_share_stock_code(code: str) -> bool:
    """True iff ``code`` is a 6-digit string whose prefix is in
    ``A_SHARE_STOCK_PREFIXES`` (i.e. a real A-share stock, not an ETF,
    fund, or index).

    Replaces the hardcoded regex previously inlined in
    ``baostock_fetcher.get_all_stocks`` — keep the prefix list here so
    new board codes (e.g. another Beijing prefix) are a one-line change.
    """
    if not code or not code.isdigit() or len(code) != 6:
        return False
    # 1-digit prefixes need to be checked after 3-digit ones to avoid
    # false matches, but since we're scanning a 6-digit string with
    # startswith, the order doesn't actually matter — the 1-digit prefix
    # only matches if the *first* char of the code is "8" or "4", which
    # is independent of the 3-digit check.
    return any(code.startswith(p) for p in A_SHARE_STOCK_PREFIXES)


def normalize_stock_code(code: str) -> str:
    """
    Normalize stock code to canonical form.

    Examples:
        'SH600519' -> '600519'
        'SZ000001' -> '000001'
        'HK00700' -> 'HK00700'
        '600519.SS' -> '600519'
        'AAPL' -> 'AAPL'
    """
    code = code.strip()
    upper = code.upper()

    # HK prefix normalization
    if upper.startswith("HK") and not upper.startswith("HK."):
        digits = upper[2:]
        if digits.isdigit() and 1 <= len(digits) <= 5:
            return f"HK{digits.zfill(5)}"

    # Strip SH/SZ prefix
    if upper.startswith(("SH", "SZ")) and not upper.startswith(("SH.", "SZ.")):
        digits = code[2:]
        if digits.isdigit() and len(digits) in (5, 6):
            return digits

    # Strip BJ prefix
    if upper.startswith("BJ"):
        digits = code[2:]
        if digits.isdigit() and len(digits) == 6:
            return digits

    # Handle suffix forms
    if "." in code:
        base, suffix = code.rsplit(".", 1)
        if suffix.upper() == "HK" and base.isdigit() and 1 <= len(base) <= 5:
            return f"HK{base.zfill(5)}"
        if suffix.upper() in ("SH", "SZ", "SS", "BJ") and base.isdigit():
            return base
        # US stock like AAPL.US -> AAPL
        return code.upper()

    # For US codes (all letters), uppercase
    if code.isalpha():
        return code.upper()

    return code


def is_us_market(code: str) -> bool:
    """Check if code is US stock/index."""
    code = (code or "").strip().upper()
    # 1-5 uppercase letters, optionally with .X suffix
    if len(code) <= 5 and code.isalpha():
        return True
    if "." in code:
        parts = code.split(".")
        return len(parts[0]) <= 5 and parts[0].isalpha()
    return False


def is_hk_market(code: str) -> bool:
    """Check if code is HK stock."""
    code = (code or "").strip().upper()
    if code.startswith("HK"):
        return True
    if code.endswith(".HK"):
        base = code[:-3]
        return base.isdigit() and 1 <= len(base) <= 5
    return bool(code.isdigit() and len(code) == 5)


def market_tag(code: str) -> str:
    """Return market tag: csi/us/hk."""
    if is_us_market(code):
        return "us"
    if is_hk_market(code):
        return "hk"
    return "csi"


def index_market_tag(code: str) -> str | None:
    """
    Return market tag for index codes: 'csi'/'hk'/'us' or None if not an index.

    Unlike market_tag() which returns 'cn'/'hk'/'us' for stocks,
    this returns the specific index market type for routing purposes.
    """
    return get_index_type(code)
