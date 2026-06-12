"""Unit tests for _reflect_signature in explorer/manifest.py."""
import pytest

from stock_data.explorer.manifest import _reflect_signature


class _DummyFetcher:
    """A stand-in fetcher whose methods exercise the reflector's edge cases."""

    def simple(self, code: str, period: str = "d") -> str:
        return ""

    def with_optional(self, code: str, start: str | None = None) -> str:
        return ""

    def with_int_and_bool(self, code: str, limit: int = 30, force: bool = False) -> str:
        return ""

    def no_annotations(self, code, period="d"):
        return ""


def test_self_is_stripped():
    sig = _reflect_signature(_DummyFetcher().simple)
    assert all(p["name"] != "self" for p in sig)


def test_required_param_has_default_null():
    sig = _reflect_signature(_DummyFetcher().simple)
    code = next(p for p in sig if p["name"] == "code")
    assert code["required"] is True
    assert code["default"] is None
    assert code["type"] == "string"


def test_optional_param_keeps_default():
    sig = _reflect_signature(_DummyFetcher().simple)
    period = next(p for p in sig if p["name"] == "period")
    assert period["required"] is False
    assert period["default"] == "d"


def test_str_or_none_is_treated_as_string():
    sig = _reflect_signature(_DummyFetcher().with_optional)
    start = next(p for p in sig if p["name"] == "start")
    assert start["type"] == "string"
    assert start["required"] is False
    assert start["default"] is None


def test_int_and_bool_types_render():
    sig = _reflect_signature(_DummyFetcher().with_int_and_bool)
    limit = next(p for p in sig if p["name"] == "limit")
    force = next(p for p in sig if p["name"] == "force")
    assert limit["type"] == "int"
    assert limit["default"] == 30
    assert force["type"] == "bool"
    assert force["default"] is False


def test_unannotated_falls_back_to_string():
    sig = _reflect_signature(_DummyFetcher().no_annotations)
    code = next(p for p in sig if p["name"] == "code")
    # Annotation is Parameter.empty → falls back to "string"
    assert code["type"] == "string"
