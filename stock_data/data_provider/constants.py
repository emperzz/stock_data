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
    # THS: d / w / m / 1m / 5m / 15m / 30m / 60m — all confirmed by probing
    # quota-h.10jqka.com.cn/fuyao/.../single_kline for inner=885756 / 881153 /
    # 881270 (verified 2026-07-21). akshare 硬编码 seg=01,从未公开过其他频率
    # — 但 upstream 真实支持全部 8 种. 1m caps at ~30 bars upstream.
    "ths": frozenset({"d", "w", "m", "1m", "5m", "15m", "30m", "60m"}),
    # EastMoney: 全部 8 频率 (klt=101/102/103/... + min-level).
    # EastMoney: 7 频率 — push2his freq_map (verified against emcharts.js
    # 2026-07-01) is `d/w/m/5m/15m/30m/60m`. No 1m (klt=1) for boards —
    # eastmoney_fetcher.py:297-301 docstring explicitly lists 7 frequencies
    # without 1m. Add klt=1 to ENDPOINTS.BOARD_KLINE['freq_map'] + extend
    # the docstring before re-enabling 1m here.
    "eastmoney": frozenset({"d", "w", "m", "5m", "15m", "30m", "60m"}),
}


# Default ``days`` window width per K-line frequency, used at the route
# layer when the caller doesn't pass ``?days=``. Sized to fit THS's
# per-frequency max-span caps (see ``_THS_HXKLINE_MAX_SPAN_DAYS`` in
# ths_fetcher.py) so that ``frequency=1m`` / ``5m`` / etc. without an
# explicit ``days`` doesn't immediately fail the span check.
#
# EastMoney has no per-frequency cap (it uses bar-count ``lmt``, not
# date span), so these defaults are safe for ``source=eastmoney`` too.
#
# Without this map, the route previously hardcoded ``days=30``, which
# made every minute-level frequency (1m cap=2d, 5m cap=30d, …) hit a
# 400 ``date span (30d) exceeds frequency='<freq>' max (...)`` whenever
# the caller passed only ``start_date`` without an explicit ``days``.
BOARD_KLINE_DEFAULT_DAYS_BY_FREQ: dict[str, int] = {
    "d": 30,
    "w": 30,
    "m": 30,
    # 1m: upstream caps at 800 bars/request (verified 2026-07-22). Default
    # 800 matches the upstream UI's "scroll-to-load" depth — a single
    # request returns ~3 trading days of 1m history (~240 bars/day). For
    # 1m, ``days`` is effectively "bar count up to 800" rather than
    # calendar days, because upstream's ``begin_time=-N`` returns N bars.
    "1m": 800,
    # 5m/15m/30m/60m: keep 30 (the legacy route default) — gives callers
    # a meaningful default without hitting upstream's 800-bar cap (30m/60m
    # never exceed it; 5m/15m may truncate silently at 800 bars but that's
    # better than the too-tight 2-bar default). Fetcher span cap (800)
    # still rejects requests that would slip past upstream's bar-count
    # ceiling — see _THS_HXKLINE_MAX_SPAN_DAYS.
    "5m": 30,
    "15m": 30,
    "30m": 30,
    "60m": 30,
}
