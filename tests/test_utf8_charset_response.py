"""Regression: every JSON response advertises ``charset=utf-8``.

Background (2026-07-15): the default ``JSONResponse`` ships
``Content-Type: application/json`` with no charset. RFC 8259 says JSON *is*
UTF-8, but HTTP/1.1 §3.7.1 still defaults ``text/*`` to ISO-8859-1 when the
charset is missing, and many browsers/curl on Windows apply the same default
to ``application/json``. The user saw the classic UTF-8→Latin-1 mojibake
("ãç¦ç¹...") when curling ``/api/v1/news/morning-briefing`` and other
Chinese-text endpoints.

The fix: ``stock_data.server._UTF8JSONResponse`` is set as the app's
``default_response_class``, so every response that doesn't pick a different
class explicitly gets ``application/json; charset=utf-8``. The actual
response bytes were correct UTF-8 the whole time — the fetcher never had
a bug; this is purely a client-side hint.

This test pins the Content-Type contract for the most likely mojibake
hot-spots: a 422 validation error (always returned without upstream call —
the contract is universal) and a K-line success path (uses the same
default-response-class machinery, so if charset leaks out of K-line it
will leak out of CLS too).
"""

from fastapi.testclient import TestClient


def test_validation_error_422_serves_utf8_charset():
    """A missing required query param triggers 422 — exercises the default
    response class with zero upstream dependency."""
    from stock_data.server import app

    client = TestClient(app)
    # No ?date= → 422 Validation Error
    r = client.get("/api/v1/news/morning-briefing")
    assert r.status_code == 422, r.text
    ct = r.headers.get("content-type", "")
    assert "charset=utf-8" in ct.lower(), (
        f"missing charset=utf-8 in Content-Type: {ct!r} — clients defaulting "
        f"to ISO-8859-1 will see UTF-8 mojibake for Chinese payloads"
    )
    assert "application/json" in ct.lower()


def test_kline_serves_utf8_charset():
    """K-line has no Chinese, but the framework default still applies.

    If the default-response-class wiring ever regresses, this catches it
    without needing CLS network access."""
    from stock_data.server import app

    client = TestClient(app)
    r = client.get("/api/v1/stocks/600519/kline?days=5&frequency=d")
    assert r.status_code == 200, r.text
    ct = r.headers.get("content-type", "")
    assert "charset=utf-8" in ct.lower(), (
        f"missing charset=utf-8 in Content-Type: {ct!r}"
    )


def test_http_exception_serves_utf8_charset():
    """HTTPException (e.g. 404 for unknown route) must also serve charset=utf-8.

    FastAPI's default HTTPException handler bypasses default_response_class,
    so without an explicit override 4xx/5xx error bodies would lose the
    charset hint and surface as Latin-1 mojibake for Chinese ``detail``
    messages (e.g. "No 财联社早报 article ..."). Regression test for the
    ``_http_exception_handler`` registered in server.py.
    """
    from stock_data.server import app

    client = TestClient(app)
    # Hit a path that FastAPI will turn into a 404 HTTPException (not a
    # 422 validation error) — the two handlers are wired separately.
    r = client.get("/api/v1/this-path-does-not-exist")
    assert r.status_code == 404, r.text
    ct = r.headers.get("content-type", "")
    assert "charset=utf-8" in ct.lower(), (
        f"missing charset=utf-8 on HTTPException 404: {ct!r}"
    )
