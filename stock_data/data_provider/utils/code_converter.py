"""
Source-specific stock-code converters.

Each function accepts a *canonical* code (already normalised by
``normalize_stock_code``) and returns the format expected by a
particular upstream data source.  Functions that cannot convert a
given code raise ``ValueError``; the calling fetcher is responsible
for translating that into a ``DataFetchError`` or other appropriate
response.

Conventions
-----------
- Input is always a canonical code: 6-digit A-share, ``HK`` + 5-digit,
  1-5 letter US stock, or an index symbol from ``index_symbols``.
- Functions that rely on ``index_symbols`` maps import them lazily
  inside the function body to avoid circular imports at module level.
"""

from __future__ import annotations

from ..utils.normalize import is_hk_market, is_index_code, normalize_stock_code

# ---------------------------------------------------------------------------
# Akshare
# ---------------------------------------------------------------------------

def to_akshare_format(code: str) -> str:
    """Convert to akshare query format.

    A-share (600519)  → ``600519``
    A-share (000001)  → ``000001``
    HK      (HK00700) → ``00700.hk``
    CSI idx (000300)  → ``000300``
    US idx  (SPX)     → ``.INX`` (Sina format)
    HK idx  (HSI)     → ``HSI`` (EM lookup needed downstream)
    """
    code = normalize_stock_code(code)

    if is_index_code(code):
        from ..fetchers.index_symbols import US_INDEX_AKSHARE_MAP, get_index_type

        index_type = get_index_type(code)
        if index_type == "us":
            entry = US_INDEX_AKSHARE_MAP.get(code)
            return entry[0] if entry is not None else code
        # CSI and HK indices use the canonical code as-is
        return code

    if is_hk_market(code):
        if code.startswith("HK"):
            code = code[2:]
        return f"{code}.hk"

    return code


# ---------------------------------------------------------------------------
# Baostock
# ---------------------------------------------------------------------------

def to_baostock_format(code: str) -> tuple[str, str]:
    """Convert to Baostock format.  Returns ``(bs_code, yw_code)``.

    A-share 600519        → ``("sh.600519", "600519")``
    A-share 000001        → ``("sz.000001", "000001")``
    CSI idx 000300        → ``("sh.000300", "000300")``
    CSI idx 399006        → ``("sz.399006", "399006")``
    Non-CSI index (HSI…)  → raises ``ValueError``
    """
    code = normalize_stock_code(code)

    if is_index_code(code):
        from ..fetchers.index_symbols import CSI_INDEX_MAP, get_index_type

        index_type = get_index_type(code)
        if index_type != "csi":
            raise ValueError(f"Baostock does not support {index_type} index {code}")
        entry = CSI_INDEX_MAP.get(code)
        if entry is not None:
            return entry[0], code
        # fallback: 00xxxx → Shanghai, 39xxxx → Shenzhen
        if code.startswith("00"):
            return f"sh.{code}", code
        return f"sz.{code}", code

    # A-share stocks
    if code.startswith(("6", "5")):
        return f"sh.{code}", code
    return f"sz.{code}", code


# ---------------------------------------------------------------------------
# Tencent
# ---------------------------------------------------------------------------

def to_tencent_prefix(code: str) -> str:
    """Convert to Tencent qt.gtimg.cn URL prefix.

    SH (600519)  → ``sh600519``
    SZ (000001)  → ``sz000001``
    HK (HK00700) → ``hk00700``
    BJ (832000)  → ``bj832000``

    Note: the original ``_tencent_prefix`` checked A-share digit prefixes
    *before* the HK check.  Bare 5-digit codes that start with 0-4 are
    therefore treated as Shenzhen stocks, not HK — even though
    ``is_hk_market`` would classify them as HK.  This preserves that
    behaviour.
    """
    code = normalize_stock_code(code)

    # A-share / BJ: prefix by leading digit (checked before HK)
    if code.startswith(("5", "6", "7", "9")):
        return f"sh{code}"
    if code.startswith("8"):
        return f"bj{code}"
    if code.startswith(("0", "1", "2", "3", "4")):
        return f"sz{code}"

    # HK (with explicit HK prefix — the only surviving HK path)
    if code.upper().startswith("HK"):
        return f"hk{code[2:].zfill(5)}"

    return f"sz{code}"


# ---------------------------------------------------------------------------
# EastMoney
# ---------------------------------------------------------------------------

def to_eastmoney_secid(code: str) -> str:
    """Build EastMoney ``secid``.

    SH (600519, 9xxxxx) → ``1.600519``
    SZ (000001 …)       → ``0.000001``
    """
    code = normalize_stock_code(code)
    if code.startswith(("6", "9")):
        return f"1.{code}"
    return f"0.{code}"


# ---------------------------------------------------------------------------
# Zhitu
# ---------------------------------------------------------------------------

def to_zhitu_format(code: str) -> str:
    """Convert to Zhitu format (6-digit code, no prefix).

    600519 → ``600519``
    000001 → ``000001``
    """
    return normalize_stock_code(code)


def to_zhitu_market_suffix(code: str) -> str:
    """Return Zhitu market suffix (``.sh`` / ``.sz``).

    600519 → ``.sh``
    000001 → ``.sz``
    832000 → ``.sh``
    """
    code = normalize_stock_code(code)
    if code.startswith(("5", "6", "7", "8", "9")):
        return ".sh"
    return ".sz"


# ---------------------------------------------------------------------------
# Yfinance
# ---------------------------------------------------------------------------

def to_yfinance_format(code: str) -> str:
    """Convert to yfinance ticker format.

    US idx  SPX     → ``^GSPC``
    CSI idx 000300  → ``000300.SS`` (Shanghai) / ``399006.SZ`` (Shenzhen)
    HK idx  HSI     → ``^HSI``
    US       AAPL   → ``AAPL``
    HK       HK00700→ ``0700.HK``
    A-share  600519 → ``600519.SS``
    A-share  000001 → ``000001.SZ``
    """
    code = code.strip().upper()

    # Already in yfinance format
    if code.endswith((".SS", ".SZ", ".HK", ".BJ")):
        return code

    if is_index_code(code):
        from ..fetchers.index_symbols import (
            CSI_INDEX_MAP,
            HK_INDEX_MAP,
            US_INDEX_MAP,
            get_index_type,
        )

        index_type = get_index_type(code)
        if index_type == "us":
            entry = US_INDEX_MAP.get(code)
            if entry is not None:
                return entry[0]
        elif index_type == "csi":
            entry = CSI_INDEX_MAP.get(code)
            if entry is not None and entry[0].startswith("sz."):
                return f"{code}.SZ"
            return f"{code}.SS"
        elif index_type == "hk":
            entry = HK_INDEX_MAP.get(code)
            if entry is not None:
                return entry[0]

    # US stock: 1-5 uppercase letters
    if code.isalpha() and len(code) <= 5:
        return code

    # HK stock
    if code.startswith("HK"):
        digits = code[2:]
        return f"{digits}.HK"

    # A-share Shanghai
    if code.startswith(("6", "5", "7")):
        return f"{code}.SS"

    # A-share Shenzhen (and default)
    return f"{code}.SZ"


# ---------------------------------------------------------------------------
# Tushare
# ---------------------------------------------------------------------------

def to_tushare_format(code: str) -> str:
    """Convert to Tushare ``ts_code`` format.

    CSI idx 000300  → ``000300.SH``
    A-share 600519  → ``600519.SH``
    A-share 000001  → ``000001.SZ``

    Raises ``ValueError`` for codes that Tushare cannot handle.
    """
    code = normalize_stock_code(code)

    if is_index_code(code):
        from ..fetchers.index_symbols import CSI_INDEX_MAP, get_index_type

        index_type = get_index_type(code)
        if index_type != "csi":
            raise ValueError(f"Tushare does not support {index_type} index {code}")
        entry = CSI_INDEX_MAP.get(code)
        if entry is not None:
            bs_symbol = entry[0]
            parts = bs_symbol.split(".")
            return f"{parts[1]}.{parts[0].upper()}"
        return f"{code}.SH"

    # A-share stocks
    if code.startswith(("6", "5")):
        return f"{code}.SH"
    if code.startswith(("0", "1", "2", "3", "4")):
        return f"{code}.SZ"
    raise ValueError(f"Tushare does not support code {code}")
