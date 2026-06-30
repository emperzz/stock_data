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
    "code_to_exchange",
    "split_concepts",
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


# A-share code prefix → exchange. Keys are checked in order; the longest
# (3-digit) prefixes must come before the 1-digit fallbacks so ``8xxxxx``
# and ``4xxxxx`` (BSE) don't accidentally match the 3-digit checks first.
# Source: SSE/SZSE/BSE board listings. STAR (688/689) and ChiNext (300/301/302)
# are sub-boards of SSE/SZSE respectively — they keep the parent exchange.
_CODE_PREFIX_TO_EXCHANGE: tuple[tuple[str, str], ...] = (
    # Shanghai (SSE)
    ("600", "SH"), ("601", "SH"), ("603", "SH"), ("605", "SH"),
    ("688", "SH"), ("689", "SH"),
    # Shenzhen (SZSE) — main board + ChiNext
    ("000", "SZ"), ("001", "SZ"), ("002", "SZ"), ("003", "SZ"),
    ("300", "SZ"), ("301", "SZ"), ("302", "SZ"),
    # Beijing (BSE)
    ("920", "BJ"),
    # 1-digit Beijing prefixes (checked last; the 3-digit "920" shadows them
    # for codes that happen to start with 9).
    ("8", "BJ"),
    ("4", "BJ"),
)


def code_to_exchange(code: str) -> str | None:
    """Infer the exchange (SH/SZ/BJ) from an A-share stock code prefix.

    Returns ``None`` for HK / US / unknown / non-stock codes. Pure
    string-based — does not consult the upstream or the stock list.
    Cheap enough to call on every ``/stocks/{code}/info`` request.

    Use cases:
        - Filling ``StockInfoResponse.exchange`` when the upstream
          fetcher doesn't populate it (current state: Zhitu, Myquant,
          Zzshare all omit exchange from their ``get_stock_info``
          payload — see ``docs/zhitu/04``, ``docs/myquant/04``,
          ``docs/zzshare/03``).
        - Any place that needs a deterministic SH/SZ/BJ tag without an
          extra API call.

    Examples:
        >>> code_to_exchange("600519")
        'SH'
        >>> code_to_exchange("000001")
        'SZ'
        >>> code_to_exchange("300750")
        'SZ'
        >>> code_to_exchange("688981")
        'SH'
        >>> code_to_exchange("830799")
        'BJ'
        >>> code_to_exchange("HK00700")
        None
        >>> code_to_exchange("AAPL")
        None
    """
    if not code:
        return None
    # Normalize first — strips "SH" / "SZ" / "BJ" prefix and any ".SS"
    # / ".SZ" suffix so prefix matching sees only the bare digits.
    code = normalize_stock_code(code)
    if not code.isdigit() or len(code) != 6:
        return None
    for prefix, exchange in _CODE_PREFIX_TO_EXCHANGE:
        if code.startswith(prefix):
            return exchange
    return None


def index_market_tag(code: str) -> str | None:
    """
    Return market tag for index codes: 'csi'/'hk'/'us' or None if not an index.

    Unlike market_tag() which returns 'cn'/'hk'/'us' for stocks,
    this returns the specific index market type for routing purposes.
    """
    return get_index_type(code)


def split_concepts(raw: object) -> list[str]:
    """Split a comma-separated concept string into a deduplicated list.

    Returns ``[]`` for empty/None input. Items are stripped; empty items dropped.
    Used by fetcher company-profile normalizers to convert a single
    ``idea`` / ``concepts`` field into a clean list.
    """
    if not raw:
        return []
    parts = [p.strip() for p in str(raw).split(",")]
    seen: set[str] = set()
    out: list[str] = []
    for p in parts:
        if p and p not in seen:
            seen.add(p)
            out.append(p)
    return out
