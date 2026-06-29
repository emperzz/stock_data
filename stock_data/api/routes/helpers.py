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
from typing import TYPE_CHECKING

from fastapi import HTTPException, Request

from ...data_provider import DataFetcherManager
from ...data_provider.core.types import safe_float
from ...data_provider.fetchers.index_symbols import get_all_indices
from ...data_provider.indicators import compute
from ...data_provider.indicators.types import IndicatorKey
from ...data_provider.utils.normalize import is_index_code
from ..schemas import KLineData

if TYPE_CHECKING:
    import pandas as pd


logger = logging.getLogger(__name__)

# ---------- period-frequency map ----------

# Shared by /stocks/{code}/history and /indices/{code}/history.
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
    "history": "Use /indices/{code}/history instead.",
    "intraday": "Use /indices/{code}/intraday instead.",
    "kline": "Use /indices/{code}/kline instead.",
}


def _reject_index_code(code: str, *, endpoint_kind: str) -> None:
    """Raise 400 if ``code`` is an index code. Used by ``/stocks/{code}/*``."""
    if is_index_code(code):
        hint = _INDEX_CODE_HINT_TEMPLATES[endpoint_kind].format(code=code)
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_request",
                "message": f"Index {code} is not supported via this endpoint. {hint}",
            },
        )


def _reject_non_index_code(code: str, *, endpoint_kind: str) -> None:
    """Raise 400 if ``code`` is NOT an index code. Used by ``/indices/{code}/*``."""
    if not is_index_code(code):
        if endpoint_kind == "quote":
            hint = "Use /stocks/{stock_code}/quote for stocks."
        elif endpoint_kind == "history":
            hint = "Use /stocks/{stock_code}/history for stocks."
        elif endpoint_kind == "intraday":
            hint = "Use /stocks/{stock_code}/intraday for stocks."
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


def _forbid_quote_params(request: Request) -> None:
    """Reject query params that are meaningless for snapshot (``/quote``) endpoints.

    Per spec 5.5: quote is a snapshot; ``period``, ``adjust``, ``days``,
    ``start_date``, ``end_date`` have no meaning. Clients get a clear 422
    with a hint to use ``/kline`` instead.
    """
    forbidden = {"period", "adjust", "days", "start_date", "end_date"}
    bad = forbidden & set(request.query_params.keys())
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

    Falls back to the code itself if no match (preserves pre-refactor
    behaviour at the call sites in ``get_index_history`` and
    ``get_index_intraday``).
    """
    for entry in get_all_indices():
        if entry["code"] == code:
            return entry["name"]
    return code


# ---------- indicator parsing ----------


def _parse_indicators_param(indicators: str | None) -> list[str]:
    """Parse the ``?indicators=a,b,c`` query param.

    Each name is validated against :class:`IndicatorKey`. Empty / None returns
    an empty list. Duplicates are deduplicated (preserves order of first
    occurrence). Raises 400 on an unknown indicator name.

    Used by both ``/stocks/{code}/history`` and ``/indices/{code}/history``,
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


def _apply_indicators(
    df: pd.DataFrame,
    requested_indicators: list[str],
    days: int,
    actual_days: int,
) -> pd.DataFrame:
    """Run the indicator orchestrator on ``df`` if requested, then truncate
    back to the user-requested bar count.

    Args:
        df: K-line DataFrame already fetched with ``actual_days`` rows.
        requested_indicators: empty list → no-op (returns df unchanged).
        days: the user-requested bar count.
        actual_days: how many rows were actually fetched (>= days when
            lookback expansion was needed).

    Returns:
        A DataFrame with the ``indicators`` column populated and at most
        ``days`` rows (the most recent ones).
    """
    if not requested_indicators:
        return df
    df = compute(df, requested_indicators)
    if actual_days > days and len(df) > days:
        df = df.tail(days).reset_index(drop=True)
    return df


def _build_kline_data(row: dict, format_date) -> KLineData:
    """Build a :class:`KLineData` from a DataFrame row dict.

    Centralises the back-compat fill for ``ma5``/``ma10``/``ma20`` from the
    ``indicators`` dict (the legacy ``KLineData`` field surface). When
    ``indicators`` wasn't computed, those fields are left as None — the
    model's ``@model_serializer`` will then drop them from the JSON
    response entirely. When ``indicators`` was computed, ``ma5/10/20`` are
    populated from the dict (mirrors the pre-refactor shape) AND the full
    ``indicators`` dict is preserved.
    """
    ind = row.get("indicators") or {}
    return KLineData(
        date=format_date(row.get("date")),
        open=safe_float(row.get("open"), 0.0) or 0.0,
        high=safe_float(row.get("high"), 0.0) or 0.0,
        low=safe_float(row.get("low"), 0.0) or 0.0,
        close=safe_float(row.get("close"), 0.0) or 0.0,
        volume=int(row.get("volume") or 0),
        amount=safe_float(row.get("amount")),
        change_percent=safe_float(row.get("pct_chg")),
        ma5=safe_float(ind.get("ma5")),
        ma10=safe_float(ind.get("ma10")),
        ma20=safe_float(ind.get("ma20")),
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
