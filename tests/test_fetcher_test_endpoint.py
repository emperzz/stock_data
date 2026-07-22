"""Tests for POST /control/fetcher-test endpoint."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from stock_data.server import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        c.get("/control/server/status")  # trigger lifespan
        yield c


def _post(client, body: dict):
    return client.post("/control/fetcher-test", json=body)


def test_happy_path_returns_ok_true(client):
    fake = MagicMock()
    fake.is_available.return_value = True
    fake.get_realtime_quote.return_value = {"price": 100.0}
    with patch.object(app.state.manager, "get_fetcher", return_value=fake):
        r = _post(
            client,
            {
                "fetcher": "baostock",
                "method": "get_realtime_quote",
                "kwargs": {"stock_code": "600519"},
            },
        )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["fetcher"] == "baostock"
    assert body["method"] == "get_realtime_quote"
    assert body["result"] == {"price": 100.0}
    assert body["error"] is None
    assert isinstance(body["elapsed_ms"], int)
    assert body["elapsed_ms"] >= 0


def test_unknown_fetcher_returns_ok_false_http_200(client):
    with patch.object(app.state.manager, "get_fetcher", return_value=None):
        r = _post(
            client,
            {
                "fetcher": "ghost",
                "method": "get_realtime_quote",
                "kwargs": {"stock_code": "600519"},
            },
        )
    assert r.status_code == 200  # always 200
    body = r.json()
    assert body["ok"] is False
    assert body["error"]["type"] == "UnknownFetcher"
    assert "ghost" in body["error"]["message"]


def test_unknown_method_returns_ok_false_http_200(client):
    fake = MagicMock()
    with patch.object(app.state.manager, "get_fetcher", return_value=fake):
        r = _post(client, {"fetcher": "baostock", "method": "__init__", "kwargs": {}})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["error"]["type"] == "UnknownMethod"


def test_fetcher_unavailable_returns_ok_false(client):
    fake = MagicMock()
    fake.is_available.return_value = False
    with patch.object(app.state.manager, "get_fetcher", return_value=fake):
        r = _post(
            client,
            {
                "fetcher": "baostock",
                "method": "get_realtime_quote",
                "kwargs": {"stock_code": "600519"},
            },
        )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["error"]["type"] == "FetcherUnavailable"


def test_missing_kwarg_returns_type_error(client):
    fake = MagicMock()
    fake.is_available.return_value = True
    fake.get_realtime_quote.side_effect = TypeError(
        "get_realtime_quote() missing 1 required positional argument: 'stock_code'"
    )
    with patch.object(app.state.manager, "get_fetcher", return_value=fake):
        r = _post(client, {"fetcher": "baostock", "method": "get_realtime_quote", "kwargs": {}})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["error"]["type"] == "TypeError"


def test_fetcher_exception_returns_class_name_with_traceback(client):
    fake = MagicMock()
    fake.is_available.return_value = True
    from stock_data.data_provider.base import DataFetchError

    fake.get_realtime_quote.side_effect = DataFetchError("BaoStock login failed")
    with patch.object(app.state.manager, "get_fetcher", return_value=fake):
        r = _post(
            client,
            {
                "fetcher": "baostock",
                "method": "get_realtime_quote",
                "kwargs": {"stock_code": "600519"},
            },
        )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["error"]["type"] == "DataFetchError"
    assert "BaoStock login failed" in body["error"]["message"]
    assert body["error"]["traceback"]  # non-empty


def test_missing_body_field_returns_422(client):
    """Pydantic validation kicks in for missing required body fields."""
    r = _post(client, {"fetcher": "baostock"})  # missing method, kwargs
    assert r.status_code == 422


# ============================================================================
# String→typed kwarg coercion
#
# HTML form inputs always submit as JSON strings. Without coercion, a call
# like `ThsFetcher.get_board_history(days="30", ...)` raises
# `TypeError: unsupported type for timedelta days component: str` deep inside
# `_resolve_ths_date_range`. The fetcher-test endpoint must coerce kwargs
# to the method's declared annotation types before invoking it.
# ============================================================================


class TestCoerceKwargsToSignature:
    """Unit tests for the coercion helper — fast, no app boot needed."""

    def test_int_annotation_coerces_string(self):
        from stock_data.explorer.routes import _coerce_kwargs_to_signature

        def fn(days: int = 30) -> int:
            return days

        out = _coerce_kwargs_to_signature(fn, {"days": "30"})
        assert out == {"days": 30}
        assert isinstance(out["days"], int)

    def test_float_annotation_coerces_string(self):
        from stock_data.explorer.routes import _coerce_kwargs_to_signature

        def fn(price: float = 0.0) -> float:
            return price

        out = _coerce_kwargs_to_signature(fn, {"price": "1.5"})
        assert out == {"price": 1.5}
        assert isinstance(out["price"], float)

    def test_bool_annotation_coerces_truthy_string(self):
        from stock_data.explorer.routes import _coerce_kwargs_to_signature

        def fn(include_quote: bool = False) -> bool:
            return include_quote

        assert _coerce_kwargs_to_signature(fn, {"include_quote": "true"}) == {"include_quote": True}
        assert _coerce_kwargs_to_signature(fn, {"include_quote": "1"}) == {"include_quote": True}
        assert _coerce_kwargs_to_signature(fn, {"include_quote": "false"}) == {
            "include_quote": False
        }

    def test_str_annotation_passes_through(self):
        from stock_data.explorer.routes import _coerce_kwargs_to_signature

        def fn(code: str = "") -> str:
            return code

        assert _coerce_kwargs_to_signature(fn, {"code": "600519"}) == {"code": "600519"}

    def test_optional_int_strips_none_wrapper_and_coerces(self):
        from stock_data.explorer.routes import _coerce_kwargs_to_signature

        def fn(days: int | None = None) -> int | None:
            return days

        assert _coerce_kwargs_to_signature(fn, {"days": "30"}) == {"days": 30}
        assert _coerce_kwargs_to_signature(fn, {"days": None}) == {"days": None}

    def test_optional_typing_int_strips_wrapper(self):
        """typing.Union[int, None] (older Optional style) gets stripped."""
        # Build a function whose annotation is the typing.Union form via
        # ``exec`` so ruff's UP045 rule doesn't auto-fix it. The point of
        # the test is to confirm ``_unwrap_optional`` handles BOTH
        # ``typing.Union`` (3.9-) and ``types.UnionType`` (3.10+ `X | None`)
        # — see test_optional_int_strips_none_wrapper_and_coerces for the
        # modern syntax variant.
        from typing import Union

        from stock_data.explorer.routes import _coerce_kwargs_to_signature

        def fn(days: Union[int, None] = None) -> Union[int, None]:  # noqa: UP007
            return days

        assert _coerce_kwargs_to_signature(fn, {"days": "30"}) == {"days": 30}

    def test_non_string_value_passes_through_unchanged(self):
        """JSON-parsed ints/floats/None must not be re-stringified."""
        from stock_data.explorer.routes import _coerce_kwargs_to_signature

        def fn(days: int = 30) -> int:
            return days

        assert _coerce_kwargs_to_signature(fn, {"days": 30}) == {"days": 30}
        assert _coerce_kwargs_to_signature(fn, {"days": None}) == {"days": None}

    def test_unknown_kwarg_passes_through(self):
        """Methods accepting **kwargs must not drop extras."""
        from stock_data.explorer.routes import _coerce_kwargs_to_signature

        def fn(**kwargs):
            return kwargs

        out = _coerce_kwargs_to_signature(fn, {"anything": "x", "more": "42"})
        assert out == {"anything": "x", "more": "42"}

    def test_unannotated_param_passes_through(self):
        from stock_data.explorer.routes import _coerce_kwargs_to_signature

        def fn(x):  # no annotation
            return x

        assert _coerce_kwargs_to_signature(fn, {"x": "30"}) == {"x": "30"}

    def test_invalid_int_string_passes_through_for_method_to_error_on(self):
        """Bad string isn't silently swallowed — the method sees the original."""
        from stock_data.explorer.routes import _coerce_kwargs_to_signature

        def fn(days: int = 30) -> int:
            return days

        assert _coerce_kwargs_to_signature(fn, {"days": "not-a-number"}) == {"days": "not-a-number"}

    def test_pep563_string_annotations_are_resolved(self):
        """Modules using ``from __future__ import annotations`` make param
        annotations lazy strings. The helper must still see the real types
        so coercion actually fires (otherwise ``days="30"`` slips through
        and the fetcher's ``timedelta(days="30")`` raises TypeError).
        """
        from stock_data.explorer.routes import _coerce_kwargs_to_signature

        # Synthesize a module with the future import in effect so the
        # function's annotations become PEP 563 strings. exec() into a
        # dedicated namespace so the parent module's flags don't leak.
        ns: dict = {"__future__": __import__("__future__", fromlist=["annotations"])}
        exec(
            "from __future__ import annotations\n"
            "def fn(days: int = 30, board_type: str | None = None) -> int:\n"
            "    return days\n",
            ns,
        )
        fn = ns["fn"]

        out = _coerce_kwargs_to_signature(fn, {"days": "30", "board_type": "industry"})
        assert out == {"days": 30, "board_type": "industry"}
        assert isinstance(out["days"], int)


class TestFetcherTestCoercesKwargs:
    """End-to-end through POST /control/fetcher-test."""

    @staticmethod
    def _make_fake_with_real_signature():
        """Build a fake fetcher whose methods have real annotations AND
        record their call args for assertions.

        A bare MagicMock has signature (*args, **kwargs), so the coercion
        helper has nothing to introspect — it would pass strings through.
        We attach small annotated functions (matching what real
        BaseFetcher subclasses look like) and a ``_calls`` list so tests
        can assert what kwargs the method actually received.
        """

        class _FakeBoardFetcher:
            name = "ths"
            priority = 0
            _calls: list[dict] = []

            def is_available(self) -> bool:
                return True

            def get_board_history(
                self,
                board_code: str,
                frequency: str = "d",
                days: int = 365,
                *,
                board_type: str | None = None,
                **kwargs,
            ) -> list:
                self._calls.append(
                    {
                        "board_code": board_code,
                        "frequency": frequency,
                        "days": days,
                        "board_type": board_type,
                    }
                )
                return [{"date": "2026-05-20", "close": 1.0}]

        return _FakeBoardFetcher()

    def test_string_int_kwarg_is_coerced_before_method_call(self, client):
        """The reported bug: `days="30"` must reach the method as int 30."""
        fake = self._make_fake_with_real_signature()
        with patch.object(app.state.manager, "get_fetcher", return_value=fake):
            r = _post(
                client,
                {
                    "fetcher": "ths",
                    "method": "get_board_history",
                    "kwargs": {
                        "board_code": "881270",
                        "days": "30",
                        "board_type": "industry",
                    },
                },
            )
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True, body
        # Confirm the method actually received int(30), not str("30").
        assert len(fake._calls) == 1
        call = fake._calls[0]
        assert call["board_code"] == "881270"
        assert call["frequency"] == "d"
        assert call["days"] == 30
        assert isinstance(call["days"], int)  # coerced from "30"
        assert call["board_type"] == "industry"

    def test_string_bool_kwarg_is_coerced(self, client):
        """HTML checkboxes submit as "true"/"false" — coerce to bool."""

        class _FakeRealtimeFetcher:
            name = "eastmoney"
            priority = 0
            _calls: list[dict] = []

            def is_available(self) -> bool:
                return True

            def get_realtime_quote(
                self,
                stock_code: str,
                include_quote: bool = False,
            ) -> dict:
                self._calls.append({"stock_code": stock_code, "include_quote": include_quote})
                return {"price": 100.0}

        fake = _FakeRealtimeFetcher()
        with patch.object(app.state.manager, "get_fetcher", return_value=fake):
            r = _post(
                client,
                {
                    "fetcher": "eastmoney",
                    "method": "get_realtime_quote",
                    "kwargs": {"stock_code": "600519", "include_quote": "true"},
                },
            )
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True, body
        assert len(fake._calls) == 1
        call = fake._calls[0]
        assert call["stock_code"] == "600519"
        assert call["include_quote"] is True  # coerced from "true"
        assert isinstance(call["include_quote"], bool)
