"""Per-stock fan-out helper used by /agent/stocks/batch-profile and /agent/lead-stocks.

Each aspect (quote / features / info / boards) is fetched independently with
its own try/except; a failure surfaces as a StockBatchAspectError in the
returned profile's errors[] but never aborts the whole fan-out.

``include_features=False`` (used by /agent/lead-stocks post-2026-09-06 spec
amendment) skips the kline fetch + ``build_features`` call entirely — the
helper then exposes quote / info / boards only, matching
``LeadStockEntry``'s serialized field set.

Also re-homes `_build_minimal_quote_from_unified` (formerly at
`stock_data/api/routes/agent.py:1016-1054`) so both endpoints can import it
without a circular dependency on `agent.py`.

Spec: docs/superpowers/specs/2026-09-06-agent-lead-stocks-design.md §3.2
"""

from dataclasses import dataclass, field

from ...data_provider.manager import DataFetcherManager
from ...data_provider.persistence import board as stock_board_cache
from .._helpers import stock_boards as _stock_boards_helper
from ..schemas import BatchFeatures, MinimalQuote, StockBatchAspectError


@dataclass
class StockProfileData:
    """Per-stock fan-out result. None fields are NOT failures — they correspond
    to a StockBatchAspectError in `errors` if the upstream call raised.

    Field shapes (must match StockBatchProfileEntry contract):
      - quote: MinimalQuote
      - features: BatchFeatures (Pydantic model — build_features returns dict, we wrap it)
      - info:   {"source": str, "data": dict}
      - boards: {"source": "persistence"|"ths", "data": list[dict]}
    """

    code: str
    quote: MinimalQuote | None = None
    features: BatchFeatures | None = None
    info: dict | None = None
    boards: dict | None = None
    errors: list[StockBatchAspectError] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return any(v is not None for v in (self.quote, self.features, self.info, self.boards))


def build_minimal_quote_from_unified(q) -> MinimalQuote:
    """Map a UnifiedRealtimeQuote to the expanded MinimalQuote.

    Mirrors the field-mapping logic in StockQuote.from_unified_quote
    (schemas.py:126) — same fallback rules for amplitude, same 1e8
    division for mcap_yi / float_mcap_yi. Kept here (rather than
    reusing StockQuote.from_unified_quote) to keep the nested-flag /
    current_price-rename / _serialize semantics out of the agent
    path: MinimalQuote is always top-level, never embedded, and the
    helper returns the Pydantic instance directly.

    Re-homed from `agent.py:1016-1054`. Behavior preserved exactly.
    Public (no underscore) since `agent.py` uses it directly.
    """
    amplitude = q.amplitude
    if amplitude is None and q.high is not None and q.low is not None and q.pre_close:
        amplitude = (q.high - q.low) / q.pre_close * 100

    def _yi(v):
        return None if v is None else v / 1e8

    return MinimalQuote(
        price=q.price,
        change_pct=q.change_pct,
        change_amount=q.change_amount,
        open=q.open_price,
        high=q.high,
        low=q.low,
        prev_close=q.pre_close,
        volume=q.volume,
        volume_unit=q.volume_unit or "share",
        amount=q.amount,  # UnifiedRealtimeQuote.amount is 元; pass-through
        turnover_pct=q.turnover_rate,
        amplitude_pct=amplitude,
        volume_ratio=q.volume_ratio,
        pe_ratio=q.pe_ratio,
        pb_ratio=q.pb_ratio,
        mcap_yi=_yi(q.total_mv),
        float_mcap_yi=_yi(q.circ_mv),
        limit_up=q.limit_up,
        limit_down=q.limit_down,
    )


def build_stock_profile(
    manager: DataFetcherManager,
    code: str,
    *,
    frequency: str = "d",
    days: int | None = None,
    include_features: bool = True,
) -> StockProfileData:
    """Pull quote + features + info + boards for `code`. Per-aspect isolation.

    Replicates the exact block formerly inlined at `agent.py:921-1005`
    inside `post_stocks_batch_profile` — same call signatures, same return
    shapes, same boards-enrichment merge — so the refactor is
    behavior-preserving.

    Args:
        manager: the DataFetcherManager singleton.
        code: 6-digit stock code (canonical form).
        frequency: kline frequency — one of d/w/m/1m/5m/15m/30m/60m.
        days: kline lookback days. If None, uses FreqProfile.default_days
            (60 for "d"). Used both for fetch window AND for build_features.
        include_features: when False (lead-stocks), skip the kline fetch +
            build_features call entirely. The ``features`` aspect is then
            never attempted, so no ``StockBatchAspectError(aspect="features", ...)``
            is appended and the response contract matches
            ``LeadStockEntry``'s serialized field set.

    Returns:
        StockProfileData with whichever aspects succeeded and per-aspect errors.
    """
    # Local imports — avoid circular: agent.py imports this module, so
    # _FEATURE_FREQS / build_features must come in lazily.
    from ...data_provider.features.build import build_features
    from ..routes.agent import _FEATURE_FREQS

    profile = StockProfileData(code=code)

    # 1. quote
    try:
        q = manager.get_realtime_quote(code)
        if q is not None:
            profile.quote = build_minimal_quote_from_unified(q)
    except Exception as exc:
        profile.errors.append(
            StockBatchAspectError(aspect="quote", error=type(exc).__name__, message=str(exc))
        )

    # 2. features (opt-in — skipped for lead-stocks per 2026-09-06 amendment)
    if include_features:
        freq_profile = _FEATURE_FREQS[frequency]
        fetch_days = max(days or freq_profile.default_days, freq_profile.ma60_warmup_days or 0)
        features_days = days if days is not None else freq_profile.default_days
        try:
            df, _src = manager.get_kline_data(
                code,
                days=fetch_days,
                frequency=freq_profile.mgr_frequency,
                adjust="qfq" if freq_profile.mgr_frequency in ("d", "w", "m") else None,
                asset="stock",
            )
            profile.features = BatchFeatures(
                **build_features(df, frequency=frequency, days=features_days)
            )
        except Exception as exc:
            profile.errors.append(
                StockBatchAspectError(aspect="features", error=type(exc).__name__, message=str(exc))
            )

    # 3. info — always returns (dict, source); never None
    try:
        info_dict, info_src = manager.get_stock_info(code)
        profile.info = {"source": info_src, "data": info_dict}
    except Exception as exc:
        profile.errors.append(
            StockBatchAspectError(aspect="info", error=type(exc).__name__, message=str(exc))
        )

    # 4. boards — mirrors the inline flow at agent.py:966-984 exactly.
    # `get_stock_memberships` returns (entries, cold_sources, origin); we
    # filter to source=="ths" and merge THS enrichment via the helper.
    try:
        entries, _cold, _origin = stock_board_cache.get_stock_memberships(
            stock_code=code, sources=["ths"], manager=manager
        )
        fetcher_full_result, enrichment_by_code = (
            _stock_boards_helper.fetch_stock_boards_quote_enrichment(code, manager)
        )
        ths_cached = [e for e in entries if e.get("source") == "ths"]
        if ths_cached:
            merged = []
            for e in ths_cached:
                base = {k: e.get(k) for k in ("code", "name", "type", "subtype", "source")}
                base.update(enrichment_by_code.get(e["code"], {}))
                merged.append(base)
            profile.boards = {"source": "persistence", "data": merged}
        elif fetcher_full_result:
            profile.boards = {"source": "ths", "data": fetcher_full_result}
        else:
            profile.boards = {"source": "persistence", "data": entries}
    except Exception as exc:
        profile.errors.append(
            StockBatchAspectError(aspect="boards", error=type(exc).__name__, message=str(exc))
        )

    return profile
