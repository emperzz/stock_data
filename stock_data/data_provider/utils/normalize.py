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
    "ETF_PREFIXES",
    "BSE_CODES",
]

# Market tag constants
ETF_PREFIXES = ("51", "52", "56", "58", "15", "16", "18")
BSE_CODES = ("92", "43", "81", "82", "83", "87", "88")


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
