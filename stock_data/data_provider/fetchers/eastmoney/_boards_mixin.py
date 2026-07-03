"""BoardsMixin — board listing / membership methods for EastMoneyFetcher.

Mixed into ``EastMoneyFetcher`` so the public class surface is unchanged.
Owns:
- Five ``_STOCK_BOARDS_*`` / ``_BOARD_*`` knobs (max pages, retry attempts,
  page delay range, board-list fids/ut).
- ``_fetch_one_clist_page``, ``_fetch_clist_page_with_fallback``,
  ``_fetch_clist_paginated`` — single-page retry + URL-variant fallback +
  paginated multi-page orchestration for any push2 clist endpoint.
- ``_build_clist_url_variants`` — turns ``endpoint["url_prefixes"]`` (+ env
  override) into a list of candidate URLs (e.g. ``[79.push2, push2]``).
- All ``get_*_boards`` public methods (concept, industry, unified entry,
  stock → boards reverse lookup, ``_get_board_stocks_impl``).

URLs / endpoint metadata consumed (all from ``._endpoints``):
- ``URLS.STOCK_BOARDS`` — push2.slist/get (used by ``get_stock_boards``)
- ``ENDPOINTS.BOARD_LIST_CONCEPT`` / ``BOARD_LIST_INDUSTRY`` /
  ``BOARD_COMPONENTS`` — three push2.clist/get shapes, each declaring
  a ``url_prefixes`` list (default: akshare's numeric subdomain + bare
  push2 fallback)
- ``_BOARD_LIST_FIELD_MAP`` / ``_BOARD_COMPONENTS_FIELD_MAP`` — f-code → JSON
  output key translations
"""

from __future__ import annotations

import logging
import os
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

    # ---- URL variant helpers (2026-07-03, push2 WAF hardening) ----
    #
    # push2.eastmoney.com WAF has tightened to reject curl_cffi Chrome120
    # impersonation from the bare subdomain. akshare's known-good URLs use
    # numeric subdomains (79/17/29.push2) — those CDN shards may not have
    # the same WAF rules. We now build a list of URL variants per board
    # clist endpoint and try them in order; first success wins.
    #
    # Override per-endpoint via env var (set to comma-separated prefix list;
    # empty string = bare push2.eastmoney.com):
    #   EASTMONEY_PUSH2_CONCEPT_PREFIXES    default "79,"
    #   EASTMONEY_PUSH2_INDUSTRY_PREFIXES   default "17,"
    #   EASTMONEY_PUSH2_COMPONENTS_PREFIXES default "29,"

    _PUSH2_PREFIX_ENV_KEYS: dict[str, str] = {
        "BOARD_LIST_CONCEPT": "EASTMONEY_PUSH2_CONCEPT_PREFIXES",
        "BOARD_LIST_INDUSTRY": "EASTMONEY_PUSH2_INDUSTRY_PREFIXES",
        "BOARD_COMPONENTS": "EASTMONEY_PUSH2_COMPONENTS_PREFIXES",
    }

    @staticmethod
    def _build_clist_url_variants(endpoint: dict) -> list[str]:
        """Build the list of candidate URLs for a board clist endpoint.

        Reads ``endpoint["url_prefixes"]`` (default per-endpoint), lets the
        matching ``EASTMONEY_PUSH2_*_PREFIXES`` env var override, then
        materializes each prefix into a full URL. Empty prefix → bare
        ``push2.eastmoney.com``.

        Args:
            endpoint: One of ``ENDPOINTS.BOARD_*`` dicts. Must have
                ``url_prefixes`` (list of str, default-loaded from
                ``_endpoints.py``) and ``url`` (bare URL — used to extract
                the path component).

        Returns:
            List of full URLs in iteration order. Never empty.
        """
        # The endpoint's "url" field carries the bare URL (no prefix).
        # We rebuild it from path so prefix substitution is consistent.
        bare = endpoint["url"]
        # Strip "https://push2.eastmoney.com" prefix to extract path.
        path = bare.split("push2.eastmoney.com", 1)[-1]

        # Find the endpoint's env-var key by matching the endpoint dict
        # against the known ENDPOINTS entries.
        env_key = None
        for name, key in BoardsMixin._PUSH2_PREFIX_ENV_KEYS.items():
            if getattr(ENDPOINTS, name, None) is endpoint:
                env_key = key
                break

        # Determine prefix list: env override or endpoint default.
        # Once the env var is *set* (even to ""), we honour it literally
        # so users can fully replace the default prefix list. The endpoint
        # default is only used when the env var is unset (or when the
        # endpoint has no env-key mapping, e.g. test fixtures).
        env_val = os.getenv(env_key) if env_key else None
        if env_val is not None:
            # Parse literally — empty string "" splits to [""] which means
            # "only the bare push2 fallback"; trailing "," adds the bare
            # fallback to a custom list (e.g. "29,17,").
            prefixes = [p.strip() for p in env_val.split(",")]
        else:
            prefixes = list(endpoint["url_prefixes"])

        variants: list[str] = []
        for p in prefixes:
            if p:
                variants.append(f"https://{p}.push2.eastmoney.com{path}")
            else:
                variants.append(f"https://push2.eastmoney.com{path}")
        return variants

    def _fetch_clist_page_with_fallback(
        self,
        url_variants: list[str],
        params: dict,
        referer: str,
    ) -> Any:
        """Try each URL variant in order; first success wins.

        Wraps ``_fetch_one_clist_page`` (which keeps its existing tenacity
        retry on transient failures) with an outer fallback across URL
        variants. Why outer fallback vs inner: persistent WAF rejections
        on a single URL are best handled by switching to the next CDN
        shard instead of retrying the same shard 3×.

        Args:
            url_variants: List of full URLs to try in order. Built by
                ``_build_clist_url_variants()``.
            params: Query params (same across all variants).
            referer: Per-call Referer (typically quote.eastmoney.com).

        Returns:
            Parsed JSON payload (whatever ``_fetch_one_clist_page`` returns).

        Raises:
            The last exception encountered, when all variants fail.
        """
        last_exc: Exception | None = None
        for url in url_variants:
            try:
                return self._fetch_one_clist_page(url, params, referer)
            except Exception as e:
                last_exc = e
                logger.debug(f"[{self.name}] clist URL {url} failed, trying next variant: {e}")
        # All variants exhausted — re-raise the last exception so the
        # caller's existing try/except in _fetch_clist_paginated returns [].
        assert last_exc is not None  # url_variants is non-empty by construction
        raise last_exc

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
        url_variants = self._build_clist_url_variants(endpoint)
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
                payload = self._fetch_clist_page_with_fallback(
                    url_variants,
                    params,
                    referer,
                )
            except Exception as e:
                logger.warning(f"[{self.name}] clist page {page} failed after retries: {e}")
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
            code = str(rec.get("f12", "")).strip()
            if not code:
                continue
            board: dict[str, Any] = {
                "code": code,
                "name": str(rec.get(_CONCEPT_LIST_NAME_FIELD, "")).strip(),
            }
            if include_quote:
                for fc, ok in _BOARD_LIST_FIELD_MAP.items():
                    # code (f12) and name (f14) are already emitted above —
                    # skip them so the loop only adds the quote extras.
                    if fc in ("f12", "f14"):
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
            code = str(rec.get("f12", "")).strip()
            if not code:
                continue
            board: dict[str, Any] = {
                "code": code,
                "name": str(rec.get(_INDUSTRY_LIST_NAME_FIELD, "")).strip(),
            }
            if include_quote:
                for fc, ok in _BOARD_LIST_FIELD_MAP.items():
                    if fc in ("f12", "f14"):
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
        self,
        board_code: str,
        *,
        include_quote: bool,
        fetcher_kind: str,
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
        board_type: str | None = None,
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
        - ``type=None``: returns concept + industry (every type the source
          exposes). ``subtype`` is ignored in this case (subtypes are
          scoped per type).

        Each returned board is tagged with ``type`` and ``subtype=type`` so
        the persistence layer can store a uniform shape across sources. This
        matches the Zhitu / Zzshare convention without inventing fake
        EM-specific subtypes.
        """
        if board_type is None:
            # All types the source exposes — concept + industry. Tag each
            # batch with its type before merging.
            tagged: list[dict] = []
            for bt, helper in (
                ("concept", self.get_all_concept_boards),
                ("industry", self.get_all_industry_boards),
            ):
                for b in helper(source=source, include_quote=include_quote):
                    b.setdefault("type", bt)
                    b.setdefault("subtype", bt)
                    tagged.append(b)
            return tagged
        if board_type == "concept":
            boards = self.get_all_concept_boards(
                source=source,
                include_quote=include_quote,
            )
        elif board_type == "industry":
            boards = self.get_all_industry_boards(
                source=source,
                include_quote=include_quote,
            )
        else:
            # index / special: EastMoney has no such classification
            return []
        # Tag every board with type/subtype=board_type so persistence layer
        # has a uniform shape. setdefault preserves any value the inner
        # helper already set (defensive — currently the helpers don't).
        for b in boards:
            b.setdefault("type", board_type)
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
                board_code,
                source=source,
                include_quote=include_quote,
            )
        if board_type == "industry":
            return self.get_industry_board_stocks(
                board_code,
                source=source,
                include_quote=include_quote,
            )

        # Cold cache / caller-doesn't-know: legacy fallback, but visible.
        stocks = self.get_concept_board_stocks(
            board_code,
            source=source,
            include_quote=include_quote,
        )
        if stocks:
            return stocks
        logger.info(
            f"[{self.name}] get_board_stocks({board_code}): concept returned "
            f"empty, falling back to industry (callers should pass board_type "
            f"to bypass the silent fallback when board_type is known)."
        )
        return self.get_industry_board_stocks(
            board_code,
            source=source,
            include_quote=include_quote,
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
            "pi": 0,
            "po": 1,
            "np": 1,
            "pz": 50,
            "spt": 3,
            "wbp2u": "|0|0|0|web",
        }
        payload = cffi_json_get(
            self._session,
            URLS.STOCK_BOARDS,
            params=params,
            headers={"Referer": "https://quote.eastmoney.com/"},
            error_label=f"get_stock_boards({code})",
        )

        data = payload.get("data") or {}
        rows = data.get("diff") or []
        out: list[dict] = []
        for r in rows:
            try:
                out.append(
                    {
                        "code": r["f12"],
                        "name": r["f14"],
                        # EastMoney doesn't cleanly distinguish concept/industry at
                        # the stock-membership level (f152=2 for both). Default to
                        # "industry" as a fallback; the resolve_board_types call
                        # below overwrites these with the authoritative values from
                        # the local stock_board cache when the code is known there.
                        "type": "industry",
                        "subtype": "industry",
                        "change_pct": (r.get("f3") or 0) / 100,
                        "change_amount": (r.get("f4") or 0) / 100,
                        "leading_stock_code": r.get("f140", ""),
                        "leading_stock_name": r.get("f128", ""),
                    }
                )
            except KeyError as e:
                logger.warning(f"[EastMoneyFetcher] skipping malformed board row: {e}")
                continue

        # Authoritative type/subtype override. EastMoney's upstream reply
        # cannot distinguish concept / industry / region / index (f152 is
        # always 2), so we look up each board_code in the stock_board
        # cache populated by the forward board-list refresh path. Lazy
        # import avoids a fetcher → persistence cycle at module load;
        # the lookup is best-effort and falls back to the fetcher defaults
        # above on any DB / schema error.
        try:
            from ...persistence.board import resolve_board_types

            codes = [b["code"] for b in out if b.get("code")]
            overrides = resolve_board_types(codes, source="eastmoney")
        except Exception as e:
            logger.warning(
                f"[{self.name}] get_stock_boards({stock_code}) type override "
                f"lookup failed: {e}; using fetcher defaults."
            )
            overrides = {}
        for b in out:
            override = overrides.get(b["code"])
            if not override:
                continue
            if override.get("type"):
                b["type"] = override["type"]
            if override.get("subtype"):
                b["subtype"] = override["subtype"]
        return out
