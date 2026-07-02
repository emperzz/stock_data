"""curl_cffi JSON/text request helpers for EastMoneyFetcher.

EastMoneyFetcher owns five endpoints whose request shape is identical
differing only in URL / params / headers / error-label:

  - ``get_stock_news``        (np-listapi)
  - ``get_announcements``     (np-anotice-stock)
  - ``fetch_flash_news``      (np-weblist)
  - ``get_stock_boards``      (push2.slist/get)
  - ``search_news``           (search-api-web JSONP — uses ``cffi_json_get_resp``)

The three-segment pattern — try GET, check HTTP status, parse JSON —
appears copy-pasted in all five. This module collapses that pattern into
one helper so the public methods only spell out what's unique to them
(URL, params, response-validation).

Design choices
--------------

**No default ``User-Agent`` injection.** EastMoneyFetcher's ``__init__``
seeds ``self._session.headers`` with the Chrome-120 desktop fingerprint
plus ``Cache-Control: no-cache`` / ``Pragma: no-cache`` / ``sec-ch-*``
(the search backend fingerprints these). curl_cffi's
``session.get(headers=...)`` does NOT mutate ``session.headers`` — it
overrides per-request only — so the baseline survives untouched even
when callers pass a small per-call headers dict.

(Compare with ``utils/http.py::json_get`` which DOES inject a random UA
default. That helper is for ``requests`` callers; EastMoneyFetcher
chose curl_cffi specifically to bypass JA3 fingerprinting, and we don't
want this helper to undo that by stamping a different UA.)

``error_label`` is mandatory and shows up in every ``DataFetchError``
message so log readers can trace which public call a failed request
came from — ``f"get_stock_news(000034)"``, ``f"search_news"``, etc.

``cffi_json_get_resp`` is the lower-level form: it returns the raw
``Response`` object so callers that need the raw body (search_news
strips a JSONP wrapper before JSON-parsing) can use it without the
``.json()`` try/except being wasted on them.
"""
from __future__ import annotations

from typing import Any

from curl_cffi import requests as cffi_requests

from ...base import DataFetchError


def cffi_json_get(
    session: cffi_requests.Session,
    url: str,
    *,
    params: dict | None = None,
    headers: dict | None = None,
    timeout: int = 15,
    error_label: str,
) -> dict[str, Any]:
    """GET ``url`` via the shared curl_cffi Session; return parsed JSON.

    Wraps three failure modes (network, HTTP, JSON parse) into
    ``DataFetchError`` so the public method can call it on one line.

    Args:
        session: The fetcher's curl_cffi Session (Chrome 120 fingerprint).
        url: Full upstream URL.
        params: Optional query-string parameters.
        headers: Optional per-request header overrides. ``session.headers``
            baseline (set in ``EastMoneyFetcher.__init__``) is preserved.
        timeout: Per-request timeout (default 15s).
        error_label: Tag inserted into every ``DataFetchError`` message,
            e.g. ``f"get_stock_news(000034)"``.

    Returns:
        Parsed JSON body (``dict``).

    Raises:
        DataFetchError: on network / HTTP / JSON failure. The original
            exception is chained via ``raise ... from e``.
    """
    resp = cffi_json_get_resp(
        session, url, params=params, headers=headers, timeout=timeout,
        error_label=error_label,
    )
    try:
        return resp.json()
    except ValueError as e:
        raise DataFetchError(
            f"[EastMoneyFetcher] {error_label} bad JSON: {e}"
        ) from e


def cffi_json_get_resp(
    session: cffi_requests.Session,
    url: str,
    *,
    params: dict | None = None,
    headers: dict | None = None,
    timeout: int = 15,
    error_label: str,
) -> cffi_requests.Response:
    """Low-level form of ``cffi_json_get``: returns the raw ``Response``.

    Used by ``search_news`` which needs ``resp.text`` to strip a JSONP
    wrapper before parsing. Other callers prefer ``cffi_json_get`` which
    returns the parsed body.

    Args: same as ``cffi_json_get``.

    Returns:
        The ``Response`` object on a successful 200.

    Raises:
        DataFetchError: on network or HTTP failure (does not check body
            content — callers do their own parsing).
    """
    try:
        resp = session.get(url, params=params, headers=headers, timeout=timeout)
    except Exception as e:
        raise DataFetchError(
            f"[EastMoneyFetcher] {error_label} network error: {e}"
        ) from e
    if resp.status_code != 200:
        raise DataFetchError(
            f"[EastMoneyFetcher] {error_label} HTTP {resp.status_code}"
        )
    return resp
