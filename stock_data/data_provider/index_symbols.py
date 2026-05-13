"""
Centralized index symbol mappings for all supported markets.

This module provides:
- US_INDEX_MAP: US indices → yfinance symbols (^GSPC, ^DJI, etc.)
- CSI_INDEX_MAP: A股 CSI indices → baostock format (sh.000300, sz.399001)
- HK_INDEX_MAP: 港股 indices → yfinance format (^HSI, ^HSCE)
- Utility functions for index detection and normalization
"""


# =============================================================================
# US Indices → yfinance symbols
# =============================================================================
US_INDEX_MAP = {
    "SPX": "^GSPC",
    "SPY": "^GSPC",
    "DJI": "^DJI",
    "IXIC": "^IXIC",
    "NASDAQ": "^IXIC",
    "VIX": "^VIX",
}

# =============================================================================
# A股 CSI Indices → baostock format
# Note: Baostock uses sh.XXXXXX for Shanghai indices, sz.XXXXXX for Shenzhen
# =============================================================================
CSI_INDEX_MAP = {
    "000300": "sh.000300",
    "000001": "sh.000001",
    "000016": "sh.000016",
    "000688": "sh.000688",
    "000905": "sh.000905",
    "000906": "sh.000906",
    "000010": "sh.000010",
    "399001": "sz.399001",
    "399006": "sz.399006",
    "399005": "sz.399005",
    "399004": "sz.399004",
    "399106": "sz.399106",
    "399107": "sz.399107",
    "399108": "sz.399108",
}

# =============================================================================
# HK Indices → yfinance format
# Note: Kept separate from akshare EM format mapping
# =============================================================================
HK_INDEX_MAP = {
    "HSI": "^HSI",
    "HSCE": "^HSCE",
}

# =============================================================================
# HK Indices → akshare EM format
# Note: Akshare uses stock_hk_index_daily_em with EM-format symbols
# EM symbols (like "HSTECF2L") are internal codes, not predictable from canonical names
# A static mapping would be guesswork - better to do runtime lookup via stock_hk_index_spot_em()
# =============================================================================
HK_INDEX_AKSHARE_MAP = {}  # Populated at runtime via _lookup_hk_index_symbol()

# =============================================================================
# US Indices → akshare Sina format
# Note: Akshare uses index_us_stock_sina with Sina-format symbols (.IXIC, .INX, .DJI, .NDX, .VIX)
# =============================================================================
US_INDEX_AKSHARE_MAP = {
    "SPX": ".INX",
    "SPY": ".INX",
    "DJI": ".DJI",
    "IXIC": ".IXIC",
    "NASDAQ": ".IXIC",
    "VIX": ".VIX",
    "NDX": ".NDX",
}

# =============================================================================
# Index names (canonical code → display name)
# =============================================================================
_INDEX_NAMES = {
    # CSI
    "000300": "沪深300",
    "000001": "上证指数",
    "000016": "上证50",
    "000688": "科创50",
    "000905": "中证500",
    "000906": "中证800",
    "000010": "上证180",
    "399001": "深证成指",
    "399006": "创业板指",
    "399005": "中小板指",
    "399004": "深证100",
    "399106": "深证综指",
    "399107": "中小板综",
    "399108": "创业板综",
    # HK
    "HSI": "恒生指数",
    "HSCE": "恒生中国企业指数",
    # US
    "SPX": "S&P 500",
    "SPY": "S&P 500 ETF",
    "DJI": "Dow Jones Industrial Average",
    "IXIC": "Nasdaq Composite",
    "NASDAQ": "Nasdaq Composite",
    "VIX": "CBOE Volatility Index",
}

# =============================================================================
# Combined lookup: canonical symbol → source symbol
# =============================================================================
_CANONICAL_TO_SOURCE = dict(CSI_INDEX_MAP)
_CANONICAL_TO_SOURCE.update(HK_INDEX_MAP)
_CANONICAL_TO_SOURCE.update(US_INDEX_MAP)

# Reverse lookup: source symbol → canonical symbol
# Handle duplicate values (e.g., SPX and SPY both map to ^GSPC)
_SOURCE_TO_CANONICAL: dict = {}
for canonical, source in _CANONICAL_TO_SOURCE.items():
    if source not in _SOURCE_TO_CANONICAL:
        _SOURCE_TO_CANONICAL[source] = canonical


def normalize_index_symbol(code: str) -> str:
    """
    Normalize an index symbol to its canonical form.

    Examples:
        "SPX" -> "SPX"
        "^GSPC" -> "SPX" (reverse lookup)
        "sh.000300" -> "000300"
        "SH.000300" -> "000300"
        "000300" -> "000300"
        "HSI" -> "HSI"
        "^HSI" -> "HSI"
    """
    code = code.strip().upper()

    # Direct lookup in all maps (case-insensitive)
    code_upper = code.upper()
    for all_map in [CSI_INDEX_MAP, HK_INDEX_MAP, US_INDEX_MAP]:
        for canonical, source in all_map.items():
            if canonical.upper() == code_upper or source.upper() == code_upper:
                return canonical

    # Reverse lookup (source format -> canonical, case-insensitive)
    for source, canonical in _SOURCE_TO_CANONICAL.items():
        if source.upper() == code_upper:
            return canonical

    # Numeric CSI index (6 digits starting with 0)
    if code.isdigit() and len(code) == 6 and code.startswith("0"):
        return code  # Already canonical CSI format

    return code  # Unknown, return as-is


def get_index_type(code: str) -> str | None:
    """
    Return index type: 'csi', 'hk', 'us', or None if not an index.

    Args:
        code: Stock/index code (canonical or source format)

    Returns:
        'csi' for A-share CSI indices, 'hk' for HK indices, 'us' for US indices,
        or None if not recognized as an index.
    """
    code = code.strip().upper()

    # Direct lookup in CSI/HK/US maps
    if code in CSI_INDEX_MAP:
        return "csi"
    if code in HK_INDEX_MAP:
        return "hk"
    if code in US_INDEX_MAP:
        return "us"

    # Reverse lookup (e.g., "^GSPC" -> "SPX")
    if code in _SOURCE_TO_CANONICAL:
        canonical = _SOURCE_TO_CANONICAL[code]
        if canonical in CSI_INDEX_MAP:
            return "csi"
        if canonical in HK_INDEX_MAP:
            return "hk"
        if canonical in US_INDEX_MAP:
            return "us"

    # Check US_INDEX_AKSHARE_MAP (e.g., ".INX")
    for _canonical, src in US_INDEX_AKSHARE_MAP.items():
        if code == src.upper():
            return "us"

    # Check HK_INDEX_AKSHARE_MAP (e.g., "HSTECF2L")
    for _canonical, em_sym in HK_INDEX_AKSHARE_MAP.items():
        if code == em_sym.upper():
            return "hk"

    # Check if numeric 6-digit code starting with 0 is a CSI index
    if (
        code.isdigit()
        and len(code) == 6
        and code.startswith("0")
        and (code in CSI_INDEX_MAP or code in {v.split(".")[1] for v in CSI_INDEX_MAP.values()})
    ):
        return "csi"

    return None


def is_index_code(code: str) -> bool:
    """
    Check if code is an index symbol.

    Args:
        code: Stock/index code to check

    Returns:
        True if the code is recognized as an index, False otherwise
    """
    return get_index_type(code) is not None


def get_source_symbol(code: str, source: str = "baostock") -> str:
    """
    Convert a canonical index symbol to source-specific format.

    Args:
        code: Canonical index symbol (e.g., "000300", "SPX", "HSI")
        source: Target source ("baostock", "yfinance", "akshare")

    Returns:
        Source-specific symbol string, or original code if not an index

    Raises:
        ValueError: If source is not recognized
    """
    code = code.strip().upper()

    # Validate it's an index
    if not is_index_code(code):
        return code

    index_type = get_index_type(code)

    if source == "baostock":
        if index_type == "csi":
            return CSI_INDEX_MAP.get(code, code)
        # HK/US indices not supported by baostock
        return code

    elif source == "yfinance":
        if index_type == "us":
            return US_INDEX_MAP.get(code, code)
        elif index_type == "csi":
            # yfinance uses .SS/.SZ suffix for A-share indices
            bs_source = CSI_INDEX_MAP.get(code, "")
            if bs_source.startswith("sh."):
                return f"{code}.SS"
            elif bs_source.startswith("sz."):
                return f"{code}.SZ"
            return f"{code}.SS"
        elif index_type == "hk":
            return HK_INDEX_MAP.get(code, code)
        return code

    elif source == "akshare":
        if index_type == "csi":
            return code  # Akshare uses 6-digit codes directly for CSI indices
        elif index_type == "hk":
            # HK indices need EM format symbols - return as-is, caller must resolve
            # The EM symbol cannot be determined without runtime lookup
            return code
        elif index_type == "us":
            return US_INDEX_AKSHARE_MAP.get(code, code)
        return code

    else:
        raise ValueError(f"Unknown source: {source}")


def get_akshare_hk_symbol(code: str) -> str | None:
    """
    Get the akshare EM-format symbol for an HK index by doing a runtime lookup.

    Args:
        code: Canonical HK index symbol (e.g., "HSI", "HSCE")

    Returns:
        EM-format symbol (e.g., "HSTECF2L") or None if not found
    """
    code = code.strip().upper()
    if code not in HK_INDEX_AKSHARE_MAP:
        return None
    return HK_INDEX_AKSHARE_MAP[code]


def get_all_indices() -> list:
    """
    Get all available indices with code, name, and market type.

    Returns:
        List of dicts: [{"code": "000300", "name": "沪深300", "market": "csi"}, ...]
    """
    result = []

    # CSI indices
    for code in CSI_INDEX_MAP:
        result.append({"code": code, "name": _INDEX_NAMES.get(code, code), "market": "csi"})

    # HK indices
    for code in HK_INDEX_MAP:
        result.append({"code": code, "name": _INDEX_NAMES.get(code, code), "market": "hk"})

    # US indices
    for code in US_INDEX_MAP:
        result.append({"code": code, "name": _INDEX_NAMES.get(code, code), "market": "us"})

    return result


def get_index_name(code: str) -> str | None:
    """
    Get the display name for an index code.

    Args:
        code: Canonical index symbol (e.g., "000300", "SPX", "HSI")

    Returns:
        Display name (e.g., "沪深300", "S&P 500") or None if not found
    """
    return _INDEX_NAMES.get(code.upper().strip())
