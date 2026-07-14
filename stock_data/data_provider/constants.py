"""Module-level constants shared across fetchers / manager / routes.

Centralizes the cross-source enumeration of supported frequencies so the
manager and route layers can validate ``source × frequency`` pairs from
one source of truth (instead of duplicating Literal-typed whitelists in
multiple places).

Added 2026-07-14 alongside the THS K-line expansion (see CLAUDE.md and
the ths_fetcher module docstring for the upstream segment mapping).
"""

# K-line frequencies each board-K-line source actually serves. Verified
# 2026-07-14 against THS upstream (probed each segment) and EastMoney
# push2his (already documented as full-set in the fetcher module).
#
# To add a new source: add an entry here and a fetcher that handles all
# listed frequencies (the manager's get_board_history raises ValueError
# on a frequency not in this map → route layer maps to 400).
BOARD_KLINE_FREQ_BY_SOURCE: dict[str, frozenset[str]] = {
    # THS: d / w / m / 5m / 15m / 30m / 60m — all confirmed by probing
    # d.10jqka.com.cn/v4/line/bk_{platecode}/{seg}/2026.js for inner=886042.
    # akshare 硬编码 seg=01,从未公开过其他频率 — 但 upstream 真实支持全部 7 种.
    "ths": frozenset({"d", "w", "m", "5m", "15m", "30m", "60m"}),
    # EastMoney: 全部 7 频率 (klt=101/102/103/... + min-level).
    "eastmoney": frozenset({"d", "w", "m", "5m", "15m", "30m", "60m"}),
}