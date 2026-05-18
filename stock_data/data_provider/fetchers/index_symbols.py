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
# Values: (source_symbol, display_name)
# =============================================================================
US_INDEX_MAP = {
    "SPX": ("^GSPC", "S&P 500"),
    "SPY": ("^GSPC", "S&P 500 ETF"),
    "DJI": ("^DJI", "Dow Jones Industrial Average"),
    "IXIC": ("^IXIC", "Nasdaq Composite"),
    "NASDAQ": ("^IXIC", "Nasdaq Composite"),
    "VIX": ("^VIX", "CBOE Volatility Index"),
}

# =============================================================================
# A股 CSI Indices → baostock format
# Note: Baostock uses sh.XXXXXX for Shanghai indices, sz.XXXXXX for Shenzhen
# Values: (source_symbol, display_name)
# =============================================================================
CSI_INDEX_MAP = {
    "000300": ("sh.000300", "沪深300"),
    "000001": ("sh.000001", "上证指数"),
    "000016": ("sh.000016", "上证50"),
    "000688": ("sh.000688", "科创50"),
    "000905": ("sh.000905", "中证500"),
    "000906": ("sh.000906", "中证800"),
    "000010": ("sh.000010", "上证180"),
    "399001": ("sz.399001", "深证成指"),
    "399006": ("sz.399006", "创业板指"),
    "399005": ("sz.399005", "中小板指"),
    "399004": ("sz.399004", "深证100"),
    "399106": ("sz.399106", "深证综指"),
    "399107": ("sz.399107", "中小板综"),
    "399108": ("sz.399108", "创业板综"),
}

# =============================================================================
# HK Indices → yfinance format
# Note: Kept separate from akshare EM format mapping
# Values: (source_symbol, display_name)
# =============================================================================
HK_INDEX_MAP = {
    "HSI": ("^HSI", "恒生指数"),
    "HSCE": ("^HSCE", "恒生中国企业指数"),
}

# =============================================================================
# US Indices → akshare Sina format
# Note: Akshare uses index_us_stock_sina with Sina-format symbols (.IXIC, .INX, .DJI, .NDX, .VIX)
# Values: (source_symbol, display_name)
# =============================================================================
US_INDEX_AKSHARE_MAP = {
    "SPX": (".INX", "S&P 500"),
    "SPY": (".INX", "S&P 500 ETF"),
    "DJI": (".DJI", "Dow Jones Industrial Average"),
    "IXIC": (".IXIC", "Nasdaq Composite"),
    "NASDAQ": (".IXIC", "Nasdaq Composite"),
    "VIX": (".VIX", "CBOE Volatility Index"),
    "NDX": (".NDX", ""),
}

# =============================================================================
# Combined lookup: canonical symbol → source symbol
# =============================================================================
_CANONICAL_TO_SOURCE = {}
for _map in [CSI_INDEX_MAP, HK_INDEX_MAP, US_INDEX_MAP]:
    for canonical, (source, _name) in _map.items():
        _CANONICAL_TO_SOURCE[canonical] = source

# Reverse lookup: source symbol → canonical symbol
# When multiple canonicals map to the same source (e.g., SPX/SPY→^GSPC),
# only the first canonical encountered is stored - both represent the same index
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
    code_upper = code.upper()

    # Direct lookup in all maps (case-insensitive)
    for all_map in [CSI_INDEX_MAP, HK_INDEX_MAP, US_INDEX_MAP]:
        for canonical, (source, _name) in all_map.items():
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
    for _canonical, (src, _name) in US_INDEX_AKSHARE_MAP.items():
        if code == src.upper():
            return "us"

    # Check if numeric 6-digit code starting with 0 is a CSI index
    if (
        code.isdigit()
        and len(code) == 6
        and code.startswith("0")
        and (code in CSI_INDEX_MAP or code in {v[0].split(".")[1] for v in CSI_INDEX_MAP.values()})
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


def get_all_indices() -> list:
    """
    Get all available indices with code, name, and market type.

    Returns:
        List of dicts: [{"code": "000300", "name": "沪深300", "market": "csi"}, ...]
    """
    result = []

    # CSI indices
    for code, (_source, name) in CSI_INDEX_MAP.items():
        result.append({"code": code, "name": name or code, "market": "csi"})

    # HK indices
    for code, (_source, name) in HK_INDEX_MAP.items():
        result.append({"code": code, "name": name or code, "market": "hk"})

    # US indices
    for code, (_source, name) in US_INDEX_MAP.items():
        result.append({"code": code, "name": name or code, "market": "us"})

    return result
