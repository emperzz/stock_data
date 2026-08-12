"""POST /api/v1/agent/correlation/matrix — server-side correlation aggregator.

Request: `stocks` and `boards` are independent optional lists; any combination
with >= 2 assets in total works (stocks-only, boards-only, or mixed). `boards`
entries may be bare code strings (source defaults to "ths") or {"code", "source"}.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from fastapi import HTTPException, Query
from fastapi.responses import PlainTextResponse, Response

from stock_data.api.endpoint_meta import endpoint_meta
from stock_data.api.routes.errors import map_errors
from stock_data.api.routes.helpers import get_manager
from stock_data.api.schemas import (
    CorrelationMatrixRequest,
    CorrelationMatrixResponse,
)
from stock_data.data_provider.base import DataFetchError
from stock_data.data_provider.constants import BOARD_KLINE_FREQ_BY_SOURCE
from stock_data.data_provider.utils.normalize import normalize_stock_code

from ._router import router

# ----- pure-compute helpers (private) -----

def _align_series(
    series_by_label: dict[str, pd.Series],
    trailing_window: int | None = None,
) -> tuple[pd.DataFrame, int, int]:
    """Inner-join on date index, return aligned close DataFrame + stats.

    Each input series's index is normalized (drop time-of-day). Sorted ascending.
    Inner-join retains only dates present in EVERY series. When
    `trailing_window` is given, the joined result is trimmed to the LAST
    `trailing_window` rows (matches Vibe-Trading
    `correlation._rolling_correlation_matrix` at lines 168–169).

    Returns
    -------
    aligned : pd.DataFrame
        Columns = labels (the dict keys); index = sorted DatetimeIndex of dates
        common to every series. Values are raw `close` prices (not returns).
    common_bars : int
        Number of rows in `aligned` (post-trim, when `trailing_window` set).
    missing_after_join : int
        Dates dropped by the inner-join itself (longest source minus joined
        length, computed before any trailing-window trim). Not affected by
        the `trailing_window` trim — reflects real date gaps, not padding.
    """
    if not series_by_label:
        raise ValueError("series_by_label is empty")

    normalized: dict[str, pd.Series] = {}
    for label, s in series_by_label.items():
        if not isinstance(s.index, pd.DatetimeIndex):
            s = s.copy()
            s.index = pd.to_datetime(s.index)
        s = s.copy()
        s.index = s.index.normalize()   # strip time-of-day (Vibe-Trading correlation.py:146)
        s = s.sort_index()
        # Drop duplicate dates defensively — an upstream bar series can carry two
        # rows on one date (e.g. suspend/resume, a merged today bar); pd.concat
        # would raise "cannot reindex on an axis with duplicate labels".
        s = s[~s.index.duplicated(keep="last")]
        normalized[label] = s

    # Inner-join: concat on columns, drop rows with any NaN (= not present in some series)
    df = pd.concat(normalized, axis=1)
    df = df.dropna(how="any")

    # Dates dropped by the join itself (longest source minus joined length) —
    # computed BEFORE the trailing-window trim so `missing_after_join` reflects
    # real date gaps, not calendar padding (spec §2.3).
    missing_after_join = max(len(s) for s in normalized.values()) - len(df)

    # Trim trailing window (spec §3.1 "trim to trailing `days` bars")
    if trailing_window is not None and len(df) > trailing_window:
        df = df.iloc[-trailing_window:].copy()

    common_bars = len(df)
    return df, common_bars, missing_after_join


def _compute_matrices(
    returns: pd.DataFrame,
    methods: list[str],
) -> dict[str, list[list[float]] | None]:
    """For each method, return NxN correlation matrix (4-dp, NaN→0, symmetric).

    Always emits both ``"pearson"`` and ``"spearman"`` keys; absent methods
    get ``None`` so callers can rely on key existence for shape checks.
    """
    out: dict[str, list[list[float]] | None] = {"pearson": None, "spearman": None}

    cols = list(returns.columns)
    method_set = set(methods)

    if "pearson" in method_set:
        # np.corrcoef returns NaN if a column has zero variance (constant series)
        with np.errstate(invalid="ignore"):
            m = np.corrcoef(returns.values, rowvar=False)
        out["pearson"] = _finalize_matrix(m, cols)

    if "spearman" in method_set:
        # Compute rank-transform once, then np.corrcoef on ranks (pairwise).
        ranks = returns.rank(method="average")
        with np.errstate(invalid="ignore"):
            m = np.corrcoef(ranks.values, rowvar=False)
        out["spearman"] = _finalize_matrix(m, cols)

    return out


def _finalize_matrix(
    m: np.ndarray,
    cols: list[str],
) -> list[list[float]]:
    """Symmetrize (numerical), NaN→0, force diagonal=1, round to 4 dp, return list-of-lists."""
    m = np.asarray(m, dtype=float)
    # Symmetrize: average with transpose (defensive — both np.corrcoef and scipy already symmetric)
    m = (m + m.T) / 2.0
    # Diagonal = 1 (defensive — zero-variance rows can give NaN diagonal)
    np.fill_diagonal(m, 1.0)
    # NaN → 0
    m = np.where(np.isnan(m), 0.0, m)
    # Round to 4 dp
    m = np.round(m, 4)
    return m.tolist()


def _pct_change(close_df: pd.DataFrame) -> pd.DataFrame:
    """Per-column `pct_change(fill_method=None)`.

    fill_method=None is load-bearing under pandas>=2,<3 (default was bfill).
    Move the call here so test #3 below pins it.
    """
    return close_df.pct_change(fill_method=None).dropna(how="any")


# ----- fetcher wrappers (private) -----


def _fetch_stock_series(
    code: str, days: int, frequency: str
) -> tuple[pd.Series | None, str | None, str | None]:
    """Fetch a single stock's close-price series.

    Returns (series, name, reason). On success reason is None; on failure
    series/name are None and reason is one of the spec §2.6 literals:
    "data_unavailable" (fetch raised) / "empty" (no usable rows) /
    "too_short" (fewer than 2 bars).
    """
    try:
        canonical = normalize_stock_code(code)
        df, _source = get_manager().get_kline_data(
            stock_code=canonical,
            days=days,
            frequency=frequency,
            asset="stock",   # disambiguate from CSI index codes (000001, 000300, etc.)
        )
        if df is None or df.empty or "close" not in df.columns:
            return None, None, "empty"
        if "trade_date" in df.columns:
            s = df.set_index(pd.to_datetime(df["trade_date"]))["close"]
        else:
            s = df.set_index(pd.DatetimeIndex(df.index))["close"]
        if s.isna().all():
            return None, None, "empty"
        if len(s) < 2:
            return None, None, "too_short"
        return s, _resolve_stock_name(canonical), None
    except (DataFetchError, ValueError, KeyError, AttributeError, TypeError):
        return None, None, "data_unavailable"


def _fetch_board_series(
    board_code: str, source: str, days: int, frequency: str
) -> tuple[pd.Series | None, str | None, str | None]:
    """Fetch a single board's close-price series.

    Returns (series, name, reason); semantics match `_fetch_stock_series`.
    """
    try:
        rows, _src = get_manager().get_board_history(
            board_code=board_code, source=source, frequency=frequency, days=days
        )
        if not rows:
            return None, None, "empty"
        df = pd.DataFrame(rows)
        if df.empty or "close" not in df.columns:
            return None, None, "empty"
        date_col = "date" if "date" in df.columns else df.columns[0]
        s = df.set_index(pd.to_datetime(df[date_col]))["close"]
        if s.isna().all():
            return None, None, "empty"
        if len(s) < 2:
            return None, None, "too_short"
        return s, _resolve_board_name(board_code, source), None
    except (DataFetchError, ValueError, KeyError, AttributeError, TypeError):
        return None, None, "data_unavailable"


def _resolve_stock_name(code: str) -> str | None:
    """Best-effort name lookup. Returns None on failure."""
    try:
        from stock_data.data_provider.persistence.stock_list import get_stock_name
        return get_stock_name(code)
    except Exception:
        return None


def _resolve_board_name(board_code: str, source: str) -> str | None:
    """Best-effort name lookup. Returns None on failure."""
    try:
        from stock_data.data_provider.persistence.board import get_board_metadata
        meta = get_board_metadata(board_code, source)
        return meta.get("board_name") if isinstance(meta, dict) else None
    except Exception:
        return None


# ----- validation -----

_FREQ_DAYS_RANGE = {
    "d":   (30, 365),
    "w":   (4,  120),
    "m":   (1,  36),
    "1m":  (1,  30),
    "5m":  (1,  30),
    "15m": (1,  30),
    "30m": (1,  30),
    "60m": (1,  30),
}


def _parse_and_validate(raw: dict) -> tuple[list[dict], list[str], list[dict]]:
    """Validate the raw request body and return parsed inputs.

    Returns
    -------
    labels : list[CorrelationLabel-ready dicts], ordered
    stocks : list[str], bare 6-digit codes
    boards : list[dict{code, source}], source defaulted to "ths"

    Raises
    ------
    HTTPException(422) on any validation failure (consistent with /agent/* peers).
    HTTPException(400) when normalize_stock_code raises on the input.
    """
    if not isinstance(raw, dict):
        raise HTTPException(400, detail={"error": "bad_request", "message": "body must be a JSON object"})

    stocks_raw = raw.get("stocks", []) or []
    boards_raw = raw.get("boards", []) or []
    freq       = raw.get("frequency", "d")
    days       = raw.get("days", 90)
    methods    = raw.get("methods", ["pearson", "spearman"])

    if not isinstance(stocks_raw, list) or not isinstance(boards_raw, list):
        raise HTTPException(422, detail={"error": "bad_request", "message": "stocks/boards must be lists"})
    if len(stocks_raw) + len(boards_raw) < 2:
        raise HTTPException(422, detail={"error": "bad_request",
            "message": "stocks + boards must contain at least 2 entries"})
    if len(stocks_raw) > 10 or len(boards_raw) > 10:
        raise HTTPException(422, detail={"error": "bad_request",
            "message": "stocks/boards each capped at 10 entries"})
    if len(stocks_raw) + len(boards_raw) > 10:
        raise HTTPException(422, detail={"error": "bad_request",
            "message": "total assets capped at 10"})

    if freq not in _FREQ_DAYS_RANGE:
        raise HTTPException(422, detail={"error": "bad_request",
            "message": f"unsupported frequency: {freq}"})
    lo, hi = _FREQ_DAYS_RANGE[freq]
    if not isinstance(days, int) or not (lo <= days <= hi):
        raise HTTPException(422, detail={"error": "bad_request",
            "message": f"days must be an int in [{lo}, {hi}] for frequency={freq}"})

    if not isinstance(methods, list) or not methods:
        raise HTTPException(422, detail={"error": "bad_request", "message": "methods must be non-empty list"})
    methods = list(dict.fromkeys(methods))   # de-dup, preserve order
    if any(m not in ("pearson", "spearman") for m in methods):
        raise HTTPException(422, detail={"error": "bad_request",
            "message": 'methods must be subset of ["pearson","spearman"]'})

    # Board source × frequency (early 422 to avoid manager explosion).
    # Use the upstream allow-list from constants so this stays in lockstep
    # with the manager-side check. Boards accept either a bare code string
    # (source defaults to "ths") or an object {"code", "source"}.
    valid_sources = {src: set(freqs) for src, freqs in BOARD_KLINE_FREQ_BY_SOURCE.items()}
    board_pairs: list[tuple[str, str]] = []
    for b in boards_raw:
        if isinstance(b, str):
            bcode, bsrc = b, "ths"
        elif isinstance(b, dict) and "code" in b:
            bcode, bsrc = b["code"], b.get("source", "ths")
        else:
            raise HTTPException(422, detail={"error": "bad_request",
                "message": 'each board must be a code string or an object with a "code"'})
        if bsrc not in valid_sources:
            raise HTTPException(422, detail={"error": "bad_request",
                "message": f"unsupported board source: {bsrc}"})
        if freq not in valid_sources[bsrc]:
            raise HTTPException(422, detail={"error": "bad_request",
                "message": f"frequency {freq} is not supported for board source {bsrc}"})
        board_pairs.append((bcode, bsrc))

    # Normalize stock codes (raises on truly bad input)
    labels: list[dict] = []
    stocks_canonical: list[str] = []
    for s in stocks_raw:
        if not isinstance(s, str):
            raise HTTPException(422, detail={"error": "bad_request", "message": "stock must be string"})
        try:
            canonical = normalize_stock_code(s)
        except Exception as e:
            raise HTTPException(400, detail={"error": "bad_request",
                "message": f"invalid stock code {s}: {e}"}) from e
        labels.append({"type": "stock", "code": canonical, "name": None, "source": None})
        stocks_canonical.append(canonical)

    boards_canonical: list[dict] = []
    for bcode, bsrc in board_pairs:
        labels.append({"type": "board", "code": bcode, "name": None, "source": bsrc})
        boards_canonical.append({"code": bcode, "source": bsrc})

    return labels, stocks_canonical, boards_canonical


# ----- markdown renderer -----
# Called directly from the route via PlainTextResponse (?format=md), bypassing
# agent._MD_TEMPLATES — deliberate deviation, spec §2.4 (no JSON-fallback /
# X-MD-Render-Error header contract on this projection).


def render_correlation_matrix_as_md(resp: dict) -> str:
    """Render a CorrelationMatrixResponse-shaped dict as markdown (spec §2.4)."""
    freq       = resp["frequency"]
    days       = resp["days"]
    labels     = resp["labels"]
    alignment  = resp["alignment"]
    matrices   = resp["matrices"]
    errors     = resp.get("errors", [])

    n = len(labels)

    def _short_label(label: dict) -> str:
        if label["type"] == "stock":
            return label["code"]
        return f'{label["code"]} ({label.get("source", "?")})'

    # Pre-compute sorted pair list per method that exists
    sections: list[str] = []
    for method, m in matrices.items():
        if m is None:
            continue
        # Top pairs (skip diagonal)
        pairs: list[tuple[float, str, str]] = []
        for i in range(n):
            for j in range(i + 1, n):
                pairs.append((float(m[i][j]),
                              _short_label(labels[i]),
                              _short_label(labels[j])))
        pairs.sort(key=lambda x: -abs(x[0]))

        sec = []
        sec.append(f"## 相关性矩阵 — {method} ({freq} × {days}d)\n")
        sec.append(
            f"> 资产数: {n} · 对齐 {alignment['common_bars']}/"
            f"{alignment['requested_days']} 个日历日 · "
            f"缺失 {alignment['missing_after_join']} 个数据点\n"
        )
        # Top pairs
        sec.append("### 所有 pair (按 |ρ| 降序)")
        sec.append("| # | Pair | ρ |")
        sec.append("|---|---|---|")
        for idx, (rho, a, b) in enumerate(pairs, start=1):
            sec.append(f"| {idx} | {a} ↔ {b} | {round(rho, 4)} |")
        sec.append("")
        # Full matrix
        sec.append(f"### 完整矩阵 ({method})")
        header = "|          | " + " | ".join(_short_label(L) for L in labels) + " |"
        sep    = "|----------|" + "|".join(["--------"] * n) + "|"
        sec.append(header)
        sec.append(sep)
        for i, label_i in enumerate(labels):
            row = [_short_label(label_i)]
            for j, _label_j in enumerate(labels):
                if i == j:
                    row.append("—")
                else:
                    row.append(str(round(float(m[i][j]), 4)))
            sec.append("| " + " | ".join(row) + " |")
        sec.append("")
        sections.append("\n".join(sec))

    body = "\n".join(sections)
    if errors:
        body += "\n### 数据缺失\n"
        for e in errors:
            src = f" ({e.get('source')})" if e.get("source") else ""
            body += f"- {e['type']} `{e['code']}`{src}: {e['reason']}\n"
    return body


# ----- route + handler -----


@router.post(
    "/agent/correlation/matrix",
    response_model=CorrelationMatrixResponse,
    tags=["agent"],
)
@endpoint_meta(
    summary="Compute pairwise Pearson + Spearman correlation matrices across stocks and boards.",
    markets=["csi"],
    capabilities=[],
)
@map_errors
async def post_correlation_matrix(
    body: CorrelationMatrixRequest,
    format: str = Query(
        "json",
        pattern="^(json|md)$",
        description="Response projection: 'json' (default) or 'md'.",
    ),
) -> CorrelationMatrixResponse | Response:
    raw = body.model_dump()

    # 1) Validate
    labels_raw, stocks, boards = _parse_and_validate(raw)

    frequency: str = raw["frequency"]
    days: int = raw["days"]
    methods: list[str] = raw["methods"]

    # 2) Fetch + assemble per-asset close series
    fetch_days = days + 60   # calendar padding for non-trading days (spec §3.3)
    stock_labels = {lbl["code"]: lbl for lbl in labels_raw if lbl["type"] == "stock"}
    board_labels = {(lbl["code"], lbl["source"]): lbl
                    for lbl in labels_raw if lbl["type"] == "board"}
    series_by_label: dict[str, pd.Series] = {}
    label_by_key: dict[str, dict] = {}   # series key (stock code / "code@src") → label
    errors_out: list[dict] = []

    # Stocks (with names)
    for code in stocks:
        s, name, reason = _fetch_stock_series(code, fetch_days, frequency)
        if s is None:
            errors_out.append({
                "type": "stock", "code": code, "source": None,
                "reason": reason or "data_unavailable",
            })
            continue
        lbl = stock_labels[code]
        lbl["name"] = name or lbl["name"]
        label_by_key[code] = lbl
        series_by_label[code] = s

    # Boards (with names)
    for b in boards:
        bcode, bsrc = b["code"], b["source"]
        s, name, reason = _fetch_board_series(bcode, bsrc, fetch_days, frequency)
        if s is None:
            errors_out.append({
                "type": "board", "code": bcode, "source": bsrc,
                "reason": reason or "data_unavailable",
            })
            continue
        lbl = board_labels[(bcode, bsrc)]
        lbl["name"] = name or lbl["name"]
        key = f"{bcode}@{bsrc}"
        label_by_key[key] = lbl
        series_by_label[key] = s

    if len(series_by_label) < 2:
        raise HTTPException(422, detail={
            "error": "insufficient_assets",
            "message": (
                f"after filtering failed fetches, only "
                f"{len(series_by_label)} assets survived; need >= 2"
            ),
        })

    # 3) Align + compute (trim to last `days` rows; spec §3.1)
    aligned_df, common_bars, missing = _align_series(
        series_by_label, trailing_window=days,
    )
    if aligned_df.empty or common_bars < 2:
        raise HTTPException(422, detail={
            "error": "insufficient_assets",
            "message": f"no overlapping trading days after join; common_bars={common_bars}",
        })

    returns = _pct_change(aligned_df)
    if returns.empty or len(returns) < 2:
        raise HTTPException(422, detail={
            "error": "insufficient_assets",
            "message": "after pct_change + dropna, fewer than 2 return observations remain",
        })

    matrices = _compute_matrices(returns, methods)

    # 4) Build response — labels must match matrix column order. Column order
    # is series_by_label insertion order (concat preserves dict order through
    # dropna/trim/pct_change), so a direct key→label lookup suffices — no
    # re-parsing of "code@src" composite keys.
    final_labels = [label_by_key[key] for key in returns.columns]

    response = CorrelationMatrixResponse(
        labels=final_labels,
        frequency=frequency,
        days=days,
        alignment={
            "requested_days": days,
            "common_bars": common_bars,
            "missing_after_join": missing,
        },
        matrices=matrices,
        errors=errors_out,
    )

    if format == "md":
        # PlainTextResponse bypasses response_model validation (matches agent.py
        # _render_agent pattern at agent.py:1073). The text/markdown mime lets
        # callers pipe the body to a markdown previewer without unwrapping.
        return PlainTextResponse(
            content=render_correlation_matrix_as_md(response.model_dump()),
            media_type="text/markdown; charset=utf-8",
        )
    return response
