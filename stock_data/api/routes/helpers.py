"""Shared helpers for the routes package.

Pulled out of the original ``routes.py`` so domain modules can share:

- The ``_manager`` singleton + ``get_manager`` / ``reset_manager`` lifecycle.
  ``server.py`` and tests import these names from ``stock_data.api.routes``
  (re-exported by ``routes/__init__.py``); the actual implementation now lives
  here so domain modules can call ``get_manager()`` directly without a circular
  re-export dance.
- Pure helpers used by multiple domain modules (indicator parsing, K-line
  DataFrame → response-model conversion, market-tag guards).
- The period-frequency dict (formerly inlined in two places).

Behaviour is unchanged from the original routes.py — these are mechanical
lifts, not redesigns.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import TYPE_CHECKING

import pandas as pd
from fastapi import HTTPException, Request

from ...data_provider import DataFetcherManager
from ...data_provider.core.types import safe_float, safe_int
from ...data_provider.fetchers.index_symbols import get_all_indices
from ...data_provider.indicators import compute
from ...data_provider.indicators.registry import estimate_lookback
from ...data_provider.indicators.types import IndicatorKey
from ...data_provider.persistence import stock_list
from ...data_provider.persistence.trade_calendar import is_trade_date
from ...data_provider.utils.normalize import is_index_code, market_tag
from ..schemas import IndexQuote, KLineData

if TYPE_CHECKING:
    pass


logger = logging.getLogger(__name__)

# ---------- period-frequency map ----------

# Shared by /stocks/{code}/kline and /indices/{code}/kline.
_PERIOD_MAP: dict[str, str] = {
    "daily": "d",
    "weekly": "w",
    "monthly": "m",
    "1m": "1",
    "5m": "5",
    "15m": "15",
    "30m": "30",
    "60m": "60",
}


def _period_to_freq(period: str) -> str:
    """Map the public ``period`` query param (daily/weekly/monthly) to the
    fetcher's internal frequency code (d/w/m). Unknown values fall back to
    ``"d"`` to preserve the pre-refactor behaviour.
    """
    return _PERIOD_MAP.get(period, "d")


# ---------- DataFetcherManager singleton ----------

_manager: DataFetcherManager | None = None


def get_manager() -> DataFetcherManager:
    """Get or create the global ``DataFetcherManager``."""
    global _manager
    if _manager is None:
        # Import lazily so tests can monkeypatch ``create_default_manager``
        # before first call.
        from ...data_provider.manager import create_default_manager

        _manager = create_default_manager()
    return _manager


def reset_manager() -> None:
    """Reset the global manager, forcing re-initialization on next ``get_manager()``.

    Used by tests (see ``tests/test_routes.py``, ``tests/test_boards.py``,
    ``tests/test_zt_pools.py``, ``tests/test_bugfix_pydantic_akshare_csi.py``).
    """
    global _manager
    _manager = None
    logger.info("Manager reset")


# ---------- market-tag guards ----------

# Three "/stocks/{code}/*" endpoints reject index codes with the same 400
# contract; three "/indices/{code}/*" endpoints reject non-index codes with
# the same 400 contract. Centralised here to keep the messages consistent
# and make the input contract obvious at the route level.

_INDEX_CODE_HINT_TEMPLATES = {
    "quote": "Use /indices/{code}/quote instead.",
    "kline": "Use /indices/{code}/kline instead.",
}


def _reject_invalid_stock_code(
    code: str, *, endpoint_kind: str, manager: DataFetcherManager | None = None
) -> None:
    """Raise 400 if ``code`` is not a recognized stock code. Used by ``/stocks/{code}/*``.

    Positive validation: a code is a valid stock iff the ``stock_list`` persistence
    layer (authoritative source) has a row for it. On a cold persistence layer
    (DB empty / fresh install), ``get_stock_name`` triggers exactly one upstream
    fetch via ``manager.get_all_stocks(market)`` to auto-warm the cache;
    subsequent calls hit the DB directly.

    The 400 message distinguishes two falsy-lookup outcomes so the caller can
    tell a *redirect* (ambiguous code, likely wanted ``/indices/...``) from a
    *genuinely unknown* code (typo / delisted / unsupported market tag):

    - ``is_index_code(code)`` true  → "Index X is not supported via this
      endpoint. Use /indices/X/<kind> instead." (redirect hint)
    - ``is_index_code(code)`` false → "Stock code X was not found in the
      stock list." (no redirect — caller really did mean a stock)
    """
    if not stock_list.get_stock_name(code, manager=manager):
        if is_index_code(code):
            hint = _INDEX_CODE_HINT_TEMPLATES[endpoint_kind].format(code=code)
            message = f"Index {code} is not supported via this endpoint. {hint}"
        else:
            message = f"Stock code {code} was not found in the stock list."
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_request", "message": message},
        )


def _reject_non_index_code(code: str, *, endpoint_kind: str) -> None:
    """Raise 400 if ``code`` is NOT an index code. Used by ``/indices/{code}/*``."""
    if not is_index_code(code):
        if endpoint_kind == "quote":
            hint = "Use /stocks/{stock_code}/quote for stocks."
        elif endpoint_kind == "kline":
            hint = "Use /stocks/{stock_code}/kline for stocks."
        else:  # pragma: no cover — exhaustive above
            hint = ""
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_request",
                "message": f"{code} is not a recognized index code. {hint}",
            },
        )


_FORBID_QUOTE_PARAMS: frozenset[str] = frozenset(
    {"period", "adjust", "days", "start_date", "end_date", "indicators"}
)


def _forbid_quote_params(request: Request) -> None:
    """Reject query params that are meaningless for snapshot (``/quote``) endpoints.

    Per spec §5.5: quote is a snapshot; ``period``, ``adjust``, ``days``,
    ``start_date``, ``end_date``, ``indicators`` have no meaning. Clients
    get a clear 422 with a hint to use ``/kline`` instead.
    """
    bad = _FORBID_QUOTE_PARAMS & set(request.query_params.keys())
    if bad:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "param_not_applicable",
                "message": f"/quote does not accept {sorted(bad)}; use /kline instead.",
            },
        )


def _resolve_index_name(code: str) -> str:
    """Look up the human-readable name for an index code.

    Falls back to the code itself if no match.
    """
    for entry in get_all_indices():
        if entry["code"] == code:
            return entry["name"]
    return code


def _index_quote_from(q, code: str) -> IndexQuote:
    """Build an IndexQuote from a UnifiedRealtimeQuote, applying the
    standard name fallback when upstream didn't carry one.

    Shared by GET /indices/{code}/quote and the agent batch-profile
    endpoints so the field mapping + name fallback stays in one place.
    """
    return IndexQuote(
        code=q.code,
        name=q.name or _resolve_index_name(code),
        source=q.source.value if hasattr(q.source, "value") else str(q.source),
        current_price=q.price or 0.0,
        change_amount=q.change_amount,
        change_pct=q.change_pct,
        open=q.open_price,
        high=q.high,
        low=q.low,
        prev_close=q.pre_close,
        volume=q.volume,
        amount=q.amount,
    )


# ---------- indicator parsing ----------


def _parse_indicators_param(indicators: str | None) -> list[str]:
    """Parse the ``?indicators=a,b,c`` query param.

    Each name is validated against :class:`IndicatorKey`. Empty / None returns
    an empty list. Duplicates are deduplicated (preserves order of first
    occurrence). Raises 400 on an unknown indicator name.

    Used by both ``/stocks/{code}/kline`` and ``/indices/{code}/kline``,
    and inside the corresponding cache key builders so invalid input is
    rejected before any cache write.
    """
    if not indicators:
        return []
    out: list[str] = []
    for raw in indicators.split(","):
        key = raw.strip()
        if not key or key in out:
            continue
        try:
            IndicatorKey(key)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "invalid_indicator",
                    "message": (
                        f"Unknown indicator: {key!r}. "
                        "See /indicators/catalog for the list of supported indicators."
                    ),
                },
            ) from None
        out.append(key)
    return out


def _expand_indicator_lookback(requested_indicators: list[str], days: int) -> int:
    """Return the bar count needed to warm the requested indicators.

    If no indicators are requested, returns ``days`` unchanged. Otherwise
    returns ``max(days, lookback)`` so the orchestrator has enough history
    to compute the first valid indicator row, then ``_finalize_kline``
    truncates back to ``days``.

    Used by both ``/stocks/{code}/kline`` and ``/indices/{code}/kline``.
    """
    if not requested_indicators:
        return days
    extra = estimate_lookback(requested_indicators)
    return max(days, extra) if extra > 0 else days


def _finalize_kline(
    df: pd.DataFrame,
    requested_indicators: list[str],
    days: int,
    merged: bool,
) -> pd.DataFrame:
    """Compute the requested indicators over ``df``, then trim to the
    user-facing bar count.

    Called AFTER ``_maybe_merge_today_bar`` so that today's partial bar
    participates in the indicator window (its moving averages etc. reflect
    the realtime price). Trading indicators are forward-recursive
    (SMA/EMA/SAR/OBV), so appending one bar at the tail leaves every
    already-closed row's values bit-for-bit unchanged.

    Args:
        df: K-line DataFrame, already merged (fetch rows + today's partial
            bar when ``merged`` is True).
        requested_indicators: empty list → indicators skipped.
        days: the user-requested bar count. The extra lookback rows fetched
            to warm the indicators are trimmed off here.
        merged: whether ``_maybe_merge_today_bar`` appended today's bar.
            When True the output keeps ``days`` closed bars PLUS that one
            partial bar (``days + 1`` total) — matching the long-standing
            "``?days=5`` returns 6 bars intraday" contract.

    Returns:
        A DataFrame with the ``indicators`` column populated (when
        requested) and ``days`` or ``days + 1`` rows.
    """
    if requested_indicators:
        df = compute(df, requested_indicators)
    return df.tail(days + (1 if merged else 0)).reset_index(drop=True)


# Only the daily bar can be completed by a single realtime tick. Higher
# frequencies are excluded because the semantics are wrong:
#   - 1m/5m/15m/30m/60m: a 5m bar is a 5-minute aggregate, not one tick.
#   - w/m: a weekly/monthly bar is an aggregate of the whole period — a
#     single day's tick injected as a "week" bar corrupts the series.
_MERGE_TODAY_FREQS: frozenset[str] = frozenset({"d"})


def _maybe_merge_today_bar(
    df: pd.DataFrame,
    code: str,
    end_date: str | None,
    frequency: str,
    manager: DataFetcherManager,
    *,
    asset: str = "stock",
    adjust: str | None = None,
) -> tuple[pd.DataFrame, bool]:
    """If end_date includes today AND today is a trading day AND the K-line
    doesn't already contain today's bar, best-effort fetch realtime quote
    and append today's partial bar.

    Returns ``(df, merged)``. ``merged`` is the authoritative signal that
    the trailing row was synthesized here rather than returned by a fetcher
    — the caller needs it to preserve the extra row when trimming, and a
    date comparison cannot substitute (after the upstream backfill, a
    fetcher-provided today bar carries the same date but IS a settled bar).

    Only daily frequency triggers; see ``_MERGE_TODAY_FREQS``.

    See docs/kline-today-bar-merge-spec-2026-07-24.md §3 for contract.
    """
    # 0. non-daily freq → skip (aggregate semantics, see _MERGE_TODAY_FREQS)
    if frequency not in _MERGE_TODAY_FREQS:
        return df, False

    # 1. hfq anchors on the OLDEST bar, so historical rows are scaled but a
    # realtime raw-price tick is not — splicing it in would mix two price
    # bases. (qfq anchors on the latest bar, so today's raw price already
    # equals today's qfq price; no adjustment → likewise safe.)
    if adjust == "hfq":
        return df, False

    if df is None or df.empty:
        return df, False

    # 2. the A-share calendar decides "is today a trading day", so it is only
    # valid for A-share codes. HK/US trade on different calendars and would
    # otherwise get a fabricated bar on A-share holidays (and none on theirs).
    if asset == "stock" and market_tag(code) != "csi":
        return df, False

    today_str = date.today().isoformat()
    effective_end = end_date or today_str

    # 3. end_date must include today
    if effective_end < today_str:
        return df, False

    # 4. today must be a trading day (fail-closed on DB error)
    try:
        trade_day = is_trade_date(today_str)
    except Exception as e:
        logger.debug(f"[maybe_merge_today_bar] is_trade_date failed for {today_str}: {e}")
        return df, False
    if not trade_day:
        return df, False

    # 5. df already covers today → no-op (avoid quote call). ``>=`` also
    # swallows a future-dated last bar (fetcher / timezone anomaly) instead
    # of appending a today bar *before* it, which would reorder the series.
    try:
        last_date = str(df.iloc[-1]["date"])[:10]
    except Exception as e:
        logger.debug(f"[maybe_merge_today_bar] last-date read failed for {code}: {e}")
        return df, False
    if last_date >= today_str:
        return df, False

    # 6. best-effort fetch realtime quote. Broadly catching Exception
    # because a quote outage must NEVER break the K-line response.
    try:
        quote = (
            manager.get_realtime_quote(code)
            if asset == "stock"
            else manager.get_index_realtime_quote(code)
        )
    except Exception as e:
        logger.debug(f"[maybe_merge_today_bar] quote fetch failed for {code}: {e}")
        return df, False

    if quote is None:
        return df, False

    # 7. Reject a degenerate OHLC rather than padding it with zeros. This bar
    # feeds the indicator window (see _finalize_kline), where a zeroed
    # open/high/low distorts ATR/TR/KC/CCI by 6-64x — far worse than simply
    # not publishing today's bar (e.g. during pre-open, when the upstream
    # quote has a price but no traded range yet).
    close = safe_float(quote.price)
    open_p = safe_float(quote.open_price)
    high = safe_float(quote.high)
    low = safe_float(quote.low)
    if close is None or close <= 0:
        return df, False
    if open_p is None or high is None or low is None:
        return df, False
    if low > high or not (low <= close <= high):
        return df, False

    # 8. construct today's partial bar (safe_float/safe_int per project
    # invariant: NaN/inf/-inf must never leak into numeric fields; nullable
    # fields retain None). volume stays raw shares — both zzshare ``daily.vol``
    # and ``rt_k.vol`` are documented in shares (docs/zzshare/01-kline.md:42,
    # docs/zzshare/02-realtime.md:42), so no unit conversion is needed.
    today_bar = {
        "date": today_str,
        "open": open_p,
        "high": high,
        "low": low,
        "close": close,
        "volume": safe_int(quote.volume, 0),
        "amount": safe_float(quote.amount, None),
        "pct_chg": safe_float(quote.change_pct, None),
    }
    return pd.concat([df, pd.DataFrame([today_bar])], ignore_index=True), True


def _build_kline_data(row: dict, format_date) -> KLineData:
    """Build a :class:`KLineData` from a DataFrame row dict."""
    # Defensive invariant, not a workaround: the ``indicators`` column is
    # object-dtype, so any row that did not go through ``compute()`` (a row
    # spliced in by ``pd.concat``, a short per-bar result, a future caller)
    # carries ``NaN`` — a *truthy* float that would otherwise reach
    # ``KLineData.indicators`` and 400 the whole response. Anything that is
    # not a dict means "no indicators for this bar".
    ind = row.get("indicators")
    ind = ind if isinstance(ind, dict) else None
    return KLineData(
        date=format_date(row.get("date")),
        open=safe_float(row.get("open"), 0.0),
        high=safe_float(row.get("high"), 0.0),
        low=safe_float(row.get("low"), 0.0),
        close=safe_float(row.get("close"), 0.0),
        volume=safe_int(row.get("volume"), 0),
        amount=safe_float(row.get("amount")),
        change_pct=safe_float(row.get("pct_chg")),
        indicators=ind or None,
    )


def _format_date(val) -> str:
    """Format a K-line / intraday ``date`` cell.

    Returns ``YYYY-MM-DD HH:MM:SS`` for datetime values with non-zero
    time components (minute-level bars), ``YYYY-MM-DD`` for date-only
    values (daily/weekly/monthly bars), and the raw string otherwise.
    """
    if val is None:
        return ""
    if hasattr(val, "strftime"):
        if hasattr(val, "hour") and (val.hour or val.minute or val.second):
            return val.strftime("%Y-%m-%d %H:%M:%S")
        return val.strftime("%Y-%m-%d")
    return str(val)
