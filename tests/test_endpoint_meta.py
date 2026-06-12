"""Unit tests for stock_data/api/endpoint_meta.py."""
import pytest

from stock_data.api.endpoint_meta import EndpointMeta, REGISTRY, endpoint_meta


class TestEndpointMetaDataclass:
    def test_is_frozen(self):
        m = EndpointMeta(summary="test", markets=["csi"], capabilities=["REALTIME_QUOTE"])
        with pytest.raises((AttributeError, Exception)):
            m.summary = "changed"  # frozen dataclass raises

    def test_defaults_are_independent(self):
        """Two EndpointMeta instances must not share the same mutable default."""
        a = EndpointMeta(summary="a")
        b = EndpointMeta(summary="b")
        a.markets.append("csi")
        assert b.markets == []  # not poisoned by a's mutation
        a.capabilities.append("REALTIME_QUOTE")
        assert b.capabilities == []


class TestEndpointMetaDecorator:
    def teardown_method(self):
        # Clean REGISTRY after each test to keep tests isolated
        REGISTRY.clear()

    def test_registers_in_registry(self):
        @endpoint_meta(summary="实时行情", markets=["csi"], capabilities=["REALTIME_QUOTE"])
        def my_route():
            return None
        assert REGISTRY[my_route].summary == "实时行情"
        assert REGISTRY[my_route].markets == ["csi"]
        assert REGISTRY[my_route].capabilities == ["REALTIME_QUOTE"]

    def test_duplicate_registration_raises(self):
        def my_route():
            return None
        endpoint_meta(summary="first")(my_route)
        with pytest.raises(ValueError, match="@endpoint_meta already registered"):
            endpoint_meta(summary="second")(my_route)

    def test_optional_fields_default_to_empty(self):
        @endpoint_meta(summary="x")
        def my_route():
            return None
        meta = REGISTRY[my_route]
        assert meta.markets == []
        assert meta.capabilities == []
        assert meta.sources == []
        assert meta.cache is None
        assert meta.probe_url is None
        assert meta.section_id is None

    def test_cache_and_probe_url_passed_through(self):
        @endpoint_meta(
            summary="x",
            cache={"ttl_sec": 60, "env": "CACHE_TTL_QUOTE"},
            probe_url="/control/fetcher/probe",
        )
        def my_route():
            return None
        meta = REGISTRY[my_route]
        assert meta.cache == {"ttl_sec": 60, "env": "CACHE_TTL_QUOTE"}
        assert meta.probe_url == "/control/fetcher/probe"
