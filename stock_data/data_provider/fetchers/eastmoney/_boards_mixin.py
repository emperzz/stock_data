"""BoardsMixin — board listing / membership methods for EastMoneyFetcher.

Mixed into ``EastMoneyFetcher`` so the public class surface is unchanged.
Owns:
- Five ``_STOCK_BOARDS_*`` / ``_BOARD_*`` knobs (max pages, retry attempts,
  page delay range, board-list fids/ut).
- ``_fetch_one_clist_page``, ``_fetch_clist_paginated`` — the retry + paginated
  page-fetcher for any push2 clist endpoint.
- All ``get_*_boards`` public methods (concept, industry, unified entry,
  stock → boards reverse lookup, ``_get_board_stocks_impl``).

URLs / endpoint metadata consumed (all from ``._endpoints``):
- ``URLS.STOCK_BOARDS`` — push2.slist/get (used by ``get_stock_boards``)
- ``ENDPOINTS.BOARD_LIST_CONCEPT`` / ``BOARD_LIST_INDUSTRY`` /
  ``BOARD_COMPONENTS`` — three push2.clist/get shapes
- ``_BOARD_LIST_FIELD_MAP`` / ``_BOARD_COMPONENTS_FIELD_MAP`` — f-code → JSON
  output key translations
"""
from __future__ import annotations

import logging
import random
import time
from typing import Any

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    wait_random,
)

from ...utils.normalize import normalize_stock_code
from ._cffi_json import cffi_json_get
from ._endpoints import (
    _BOARD_COMPONENTS_FIELD_MAP,
    _BOARD_LIST_FIELD_MAP,
    _CONCEPT_LIST_NAME_FIELD,
    _INDUSTRY_LIST_NAME_FIELD,
    ENDPOINTS,
    UA,
    URLS,
)

logger = logging.getLogger(__name__)


class BoardsMixin:
    """Public surface: ``get_all_boards``, ``get_board_stocks``,
    ``get_stock_boards`` plus their concept/industry specialisations.

    History
    -------
    This capability was migrated from AkshareFetcher (commit 25b7819). The
    HTTP layer was then re-pointed from the akshare SDK to direct calls
    against ``push2.eastmoney.com/api/qt/clist/get`` to avoid the SDK
    dependency; field semantics still mirror akshare's stock_board_*_em
    reference impl.

    Rate limiting
    -------------
    push2 backend is sensitive to high-frequency clist requests. The
    ``_BOARD_*`` knobs below implement:
    - tenacity exponential+random retry (NetworkError → 3 attempts)
    - 1.0-2.0s random delay between pages (vs akshare's 0.5-1.5s, slightly
      more conservative to stay below the rate limit threshold)
    - jitter inside the retry backoff (wait_random)

    Field-code note
    ---------------
    Board clist field semantics differ from per-stock clist:
    - Per-stock: f12=code, f14=name
    - Board components: f14=code, f16=name
    See ``_BOARD_*_FIELD_MAP`` constants in ``._endpoints``.
    """

    # ---- Config knobs for clist pagination ----

    # Cap at 10 pages per call (concept boards ≈300 rows; 10 pages covers
    # practical size). Guards against ``total`` field anomalies that would
    # otherwise loop forever.
    _BOARD_MAX_PAGES = 10
    # tenacity stop_after_attempt for each page fetch.
    _BOARD_RETRY_ATTEMPTS = 3
    # Inter-page delay (seconds) — slow down multi-page pulls to dodge push2
    # rate limits.
    _BOARD_PAGE_DELAY_RANGE = (1.0, 2.0)

    # ---- Push2 slist/get constants ----

    _STOCK_BOARDS_UT = "fa5fd1943c7b386f172d6893dbfba10b"  # shared with other push2 endpoints
    _STOCK_BOARDS_FIELDS = "f14,f12,f13,f3,f152,f4,f128,f140,f141"

    # ==================================================================
    # Clist page fetchers (private)
    # ==================================================================

    def _fetch_one_clist_page(self, url: str, params: dict, referer: str) -> Any:
        """Fetch one page of a clist endpoint with tenacity retry.

        Network-layer retry is split out to keep tests' mock surface small
        — mock one "succeed" or "rate-limit failed" call without touching
        pagination logic.
        """
        session = self._session

        @retry(
            retry=retry_if_exception_type(Exception),
            stop=stop_after_attempt(self._BOARD_RETRY_ATTEMPTS),
            wait=wait_exponential(multiplier=1, min=1, max=8) + wait_random(0, 1),
            reraise=True,
        )
        def _do():
            headers = {"User-Agent": UA, "Referer": referer}
            r = session.get(url, params=params, headers=headers, timeout=15)
            return r.json()

        return _do()

    def _fetch_clist_paginated(
        self,
        endpoint: dict[str, Any],
        *,
        fs_override: str | None = None,
        page_size: int = 100,
    ) -> list[dict[str, Any]]:
        """Fetch all pages of an EastMoney clist endpoint with retry + rate-limit delays.

        Args:
            endpoint: One of ``ENDPOINTS.BOARD_*`` dicts (url/fs/fid/fields).
            fs_override: Override the ``fs`` query param. Used by the
                components endpoint to inject the board code.
            page_size: Rows per page (default 100, EastMoney practical max).

        Returns:
            Flat list of row dicts (keyed by field code). The upstream API
            may return rows as positional lists **or** dicts depending on
            the ``np`` / ``fltt`` parameters; this method normalizes both
            formats into dicts so consumers can always ``row.get("f14")``.
            Empty on persistent failure (caller treats that as "no boards").
        """
        url = endpoint["url"]
        base_params: dict[str, Any] = {
            "pz": page_size,
            "po": 1,
            "np": 1,
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fltt": 2,
            "invt": 2,
            "fid": endpoint["fid"],
            "fs": fs_override if fs_override is not None else endpoint["fs"],
            "fields": endpoint["fields"],
        }
        referer = "https://quote.eastmoney.com/"
        field_list = endpoint["fields"].split(",")
        all_rows: list[dict[str, Any]] = []
        for page in range(1, self._BOARD_MAX_PAGES + 1):
            params = {**base_params, "pn": page}
            try:
                payload = self._fetch_one_clist_page(url, params, referer)
            except Exception as e:
                logger.warning(
                    f"[{self.name}] clist page {page} failed after retries: {e}"
                )
                break
            rows = ((payload.get("data") or {}).get("diff")) or []
            if not rows:
                break
            # Normalize: upstream may return rows as dicts (np=1 push
            # format) or positional lists (legacy).  Convert lists to
            # dicts keyed by field code so consumers always get dicts.
            for r in rows:
                if isinstance(r, dict):
                    all_rows.append(r)
                else:
                    all_rows.append(dict(zip(field_list, r, strict=False)))
            total = ((payload.get("data") or {}).get("total")) or 0
            # 终止条件: 拉到的行数 >= total, 或者本页不满 (last page)
            if not total or page * page_size >= total or len(rows) < page_size:
                break
            # 页间延迟 — 防 push2 限流
            if page < self._BOARD_MAX_PAGES:
                time.sleep(random.uniform(*self._BOARD_PAGE_DELAY_RANGE))
        return all_rows

    # ==================================================================
    # Board list / membership public methods
    # ==================================================================

    def get_all_concept_boards(
        self, source: str = "eastmoney", include_quote: bool = False
    ) -> list[dict]:
        """Get all concept boards (EastMoney push2 clist 直连)."""
        ep = ENDPOINTS.BOARD_LIST_CONCEPT
        try:
            rows = self._fetch_clist_paginated(ep)
        except Exception as e:
            logger.warning(f"[{self.name}] get_all_concept_boards failed: {e}")
            return []
        if not rows:
            return []
        out: list[dict] = []
        for rec in rows:
            code = str(rec.get("f14", "")).strip()
            if not code:
                continue
            board: dict[str, Any] = {
                "code": code,
                "name": str(rec.get(_CONCEPT_LIST_NAME_FIELD, "")).strip(),
            }
            if include_quote:
                for fc, ok in _BOARD_LIST_FIELD_MAP.items():
                    if fc == "f14":
                        continue
                    board[ok] = rec.get(fc)
            out.append(board)
        return out

    def get_all_industry_boards(
        self, source: str = "eastmoney", include_quote: bool = False
    ) -> list[dict]:
        """Get all industry boards (EastMoney push2 clist 直连)."""
        ep = ENDPOINTS.BOARD_LIST_INDUSTRY
        try:
            rows = self._fetch_clist_paginated(ep)
        except Exception as e:
            logger.warning(f"[{self.name}] get_all_industry_boards failed: {e}")
            return []
        if not rows:
            return []
        out: list[dict] = []
        for rec in rows:
            code = str(rec.get("f14", "")).strip()
            if not code:
                continue
            board: dict[str, Any] = {
                "code": code,
                "name": str(rec.get(_INDUSTRY_LIST_NAME_FIELD, "")).strip(),
            }
            if include_quote:
                for fc, ok in _BOARD_LIST_FIELD_MAP.items():
                    if fc == "f14":
                        continue
                    board[ok] = rec.get(fc)
            out.append(board)
        return out

    def get_concept_board_stocks(
        self, board_code: str, source: str = "eastmoney", include_quote: bool = False
    ) -> list[dict]:
        """Get stocks within a concept board (EastMoney push2 clist 直连)."""
        return self._get_board_stocks_impl(
            board_code, include_quote=include_quote, fetcher_kind="concept"
        )

    def get_industry_board_stocks(
        self, board_code: str, source: str = "eastmoney", include_quote: bool = False
    ) -> list[dict]:
        """Get stocks within an industry board (EastMoney push2 clist 直连)."""
        return self._get_board_stocks_impl(
            board_code, include_quote=include_quote, fetcher_kind="industry"
        )

    def _get_board_stocks_impl(
        self, board_code: str, *, include_quote: bool, fetcher_kind: str,
    ) -> list[dict]:
        """Shared logic for concept / industry board stock listing.

        EastMoney does not differentiate concept vs industry in the cons
        endpoint — both use the same ``fs=b:{board_code}+f:!50`` form and
        return identical shape. ``fetcher_kind`` is kept for log labeling
        and future divergence (currently unused beyond logs).
        """
        ep = ENDPOINTS.BOARD_COMPONENTS
        fs = ep["fs_template"].format(board_code=board_code)
        try:
            rows = self._fetch_clist_paginated(ep, fs_override=fs)
        except Exception as e:
            logger.warning(
                f"[{self.name}] get_board_stocks({fetcher_kind}={board_code}) failed: {e}"
            )
            return []
        if not rows:
            return []
        out: list[dict] = []
        for rec in rows:
            code = str(rec.get("f14", "")).strip()
            if not code:
                continue
            stock: dict[str, Any] = {
                "stock_code": code,
                "stock_name": str(rec.get("f16", "")).strip(),
            }
            if include_quote:
                for fc, ok in _BOARD_COMPONENTS_FIELD_MAP.items():
                    if fc in ("f14", "f16"):  # already emitted
                        continue
                    stock[ok] = rec.get(fc)
            out.append(stock)
        return out

    # ----- Manager 统一入口方法（与 ZhituFetcher 对齐） -----

    def get_all_boards(
        self,
        board_type: str,
        subtype: str | None = None,
        source: str = "eastmoney",
        include_quote: bool = False,
    ) -> list[dict]:
        """Get boards of a given type and optional subtype (unified entry).

        EastMoney doesn't expose subtype information — its boards are
        categorized purely by ``concept`` vs ``industry``. We map:
        - ``type=concept``: any subtype → returns concept boards
        - ``type=industry``: any subtype → returns industry boards
        - ``type=index`` / ``type=special``: not supported → return ``[]``

        Each returned board is tagged with ``subtype=board_type`` (e.g.
        ``subtype="concept"``) so the persistence layer can store a uniform
        shape across sources. This matches the Zhitu / Zzshare convention
        without inventing fake EM-specific subtypes.
        """
        if board_type == "concept":
            boards = self.get_all_concept_boards(
                source=source, include_quote=include_quote,
            )
        elif board_type == "industry":
            boards = self.get_all_industry_boards(
                source=source, include_quote=include_quote,
            )
        else:
            # index / special: EastMoney has no such classification
            return []
        # Tag every board with subtype=board_type so persistence layer has
        # a uniform shape. setdefault preserves any subtype the inner helper
        # already set (defensive — currently the helpers don't set it).
        for b in boards:
            b.setdefault("subtype", board_type)
        return boards

    def get_board_stocks(
        self,
        board_code: str,
        source: str = "eastmoney",
        include_quote: bool = False,
        board_type: str | None = None,
    ) -> list[dict]:
        """Get stocks in a board (unified entry — EastMoney doesn't distinguish
        concept/industry at the board level, both share the ``BK`` prefix).

        Args:
            board_code: 6-digit ``BK`` prefixed board code.
            source: Source slug. Ignored by EastMoneyFetcher (kept for
                interface parity with other fetchers).
            include_quote: When True, attach realtime quote fields.
            board_type: When ``"concept"`` or ``"industry"`` is supplied,
                dispatch directly to that branch — no silent fallback.
                ``None`` (default) retains the legacy concept→industry
                fallback for callers that don't know the board type
                a priori; the fallback is now logged at INFO level (was
                silent before, which let transient upstream failures
                silently re-route a concept query to the industry call).

        Bug fixed (Phase 4, 2026-07-02)
        --------------------------------
        Earlier versions silently fell through concept → industry when
        the concept call returned ``[]``. ``[]`` is also what
        ``_get_board_stocks_impl`` returns on persistent upstream failure,
        so a transient 5xx on a known concept board was indistinguishable
        from "no stocks in this board". The fallback then returned the
        WRONG semantic answer when the ``board_type`` cache knew the board
        was concept. With ``board_type`` passed in (now wired through the
        persistence layer), the silent fallback is bypassed for known
        board types and only fires for cold cache + cold upstream.
        """
        if board_type == "concept":
            return self.get_concept_board_stocks(
                board_code, source=source, include_quote=include_quote,
            )
        if board_type == "industry":
            return self.get_industry_board_stocks(
                board_code, source=source, include_quote=include_quote,
            )

        # Cold cache / caller-doesn't-know: legacy fallback, but visible.
        stocks = self.get_concept_board_stocks(
            board_code, source=source, include_quote=include_quote,
        )
        if stocks:
            return stocks
        logger.info(
            f"[{self.name}] get_board_stocks({board_code}): concept returned "
            f"empty, falling back to industry (callers should pass board_type "
            f"to bypass the silent fallback when board_type is known)."
        )
        return self.get_industry_board_stocks(
            board_code, source=source, include_quote=include_quote,
        )

    def get_stock_boards(self, stock_code: str, source: str = "eastmoney") -> list[dict] | None:
        """Get boards a stock belongs to via push2 slist/get.

        Returns a list of normalized dicts (empty list if upstream has no data).
        Returns None if the stock code is invalid (signals "source unavailable"
        to the persistence layer).
        """
        code = normalize_stock_code(stock_code)
        if not code:
            return None
        secid = self._secid(code)

        params = {
            "fltt": 1,
            "invt": 2,
            "fields": self._STOCK_BOARDS_FIELDS,
            "secid": secid,
            "ut": self._STOCK_BOARDS_UT,
            "pi": 0, "po": 1, "np": 1, "pz": 50, "spt": 3,
            "wbp2u": "|0|0|0|web",
        }
        payload = cffi_json_get(
            self._session, URLS.STOCK_BOARDS, params=params,
            headers={"Referer": "https://quote.eastmoney.com/"},
            error_label=f"get_stock_boards({code})",
        )

        data = payload.get("data") or {}
        rows = data.get("diff") or []
        out: list[dict] = []
        for r in rows:
            try:
                out.append({
                    "code": r["f12"],
                    "name": r["f14"],
                    # EastMoney doesn't cleanly distinguish concept/industry at
                    # the stock-membership level (f152=2 for both). Default to
                    # "industry" which is the most common case for A-share names.
                    "type": "industry",
                    "subtype": "industry",
                    "change_pct": (r.get("f3") or 0) / 100,
                    "change_amount": (r.get("f4") or 0) / 100,
                    "leading_stock_code": r.get("f140", ""),
                    "leading_stock_name": r.get("f128", ""),
                })
            except KeyError as e:
                logger.warning(f"[EastMoneyFetcher] skipping malformed board row: {e}")
                continue
        return out
