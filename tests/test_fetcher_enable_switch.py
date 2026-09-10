"""Tests for the per-fetcher <SLUG>_ENABLED switch.

The switch is read on every call (not at class-definition time), so every
test here monkeypatches the env and asserts behavior directly — no
importlib.reload, no class-identity churn.
"""

import pytest

from stock_data.data_provider.base import BaseFetcher
from stock_data.data_provider.fetchers.zhitu_fetcher import ZhituFetcher
from stock_data.data_provider.utils.normalize import source_slug


class TestSourceSlug:
    def test_strips_fetcher_suffix_and_lowercases(self):
        assert source_slug("ZhituFetcher") == "zhitu"
        assert source_slug("ZzshareFetcher") == "zzshare"
        assert source_slug("ThsFetcher") == "ths"

    def test_keeps_multiword_name_as_one_token(self):
        """EastMoneyFetcher → eastmoney (the existing _derive_slug contract).

        This is the name that must match the EASTMONEY_PRIORITY env prefix,
        so "east_money" would break the symmetry the switch relies on.
        """
        assert source_slug("EastMoneyFetcher") == "eastmoney"

    def test_bare_name_without_suffix(self):
        assert source_slug("Zhitu") == "zhitu"

    def test_case_insensitive_suffix_strip(self):
        assert source_slug("ZhituFETCHER") == "zhitu"

    def test_empty_name_yields_empty_string(self):
        assert source_slug("") == ""


class TestEnabledEnvVar:
    def test_derives_from_class_name(self):
        assert ZhituFetcher.enabled_env_var() == "ZHITU_ENABLED"
        # BaseFetcher itself derives from the same rule — "Base" + suffix,
        # not a special case. Pins that there is no base-class carve-out.
        assert BaseFetcher.enabled_env_var() == "BASE_ENABLED"

    def test_derivation_matches_the_priority_var_convention(self):
        """The <SLUG>_ENABLED name must be the <SLUG>_PRIORITY name's sibling.

        Both are built from source_slug(cls.name).upper(), so a mismatch here
        means one of the two stopped using the shared rule.
        """
        from stock_data.data_provider.fetchers.eastmoney_fetcher import EastMoneyFetcher
        from stock_data.data_provider.fetchers.zzshare_fetcher import ZzshareFetcher

        assert EastMoneyFetcher.enabled_env_var() == "EASTMONEY_ENABLED"
        assert ZzshareFetcher.enabled_env_var() == "ZZSHARE_ENABLED"


class TestIsEnabled:
    def test_defaults_to_true_when_env_unset(self, monkeypatch):
        monkeypatch.delenv("ZHITU_ENABLED", raising=False)
        assert ZhituFetcher.is_enabled() is True

    @pytest.mark.parametrize("raw", ["false", "False", "FALSE", " false ", "0", "no", "off"])
    def test_falsy_spellings_disable(self, monkeypatch, raw):
        """Case and surrounding whitespace are tolerated, so a .env written
        as `ZHITU_ENABLED = FALSE` still disables rather than silently
        staying enabled."""
        monkeypatch.setenv("ZHITU_ENABLED", raw)
        assert ZhituFetcher.is_enabled() is False

    @pytest.mark.parametrize("raw", ["true", "TRUE", "1", "yes", "on", "", "garbage"])
    def test_anything_else_stays_enabled(self, monkeypatch, raw):
        """Empty string means enabled, not disabled.

        An unset var and an empty var must agree: `ZHITU_ENABLED=` in a .env
        is the most common way a user "leaves it blank", and treating that as
        disabled would silently drop a source with no visible cause.
        """
        monkeypatch.setenv("ZHITU_ENABLED", raw)
        assert ZhituFetcher.is_enabled() is True

    def test_reads_env_per_call_not_at_import_time(self, monkeypatch):
        """Flip the env twice on the same class object.

        This is the property that lets every other test here use monkeypatch
        instead of importlib.reload (which would rebind the class and desync
        the SDK init cache — see tests/test_zzshare_fetcher.py:59-80).
        """
        monkeypatch.setenv("ZHITU_ENABLED", "false")
        assert ZhituFetcher.is_enabled() is False
        monkeypatch.setenv("ZHITU_ENABLED", "true")
        assert ZhituFetcher.is_enabled() is True

    def test_switch_is_per_fetcher_not_global(self, monkeypatch):
        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

        monkeypatch.setenv("ZHITU_ENABLED", "false")
        monkeypatch.delenv("THS_ENABLED", raising=False)
        assert ZhituFetcher.is_enabled() is False
        assert ThsFetcher.is_enabled() is True


class TestRegistrationGate:
    def test_disabled_fetcher_is_not_registered(self, monkeypatch):
        """ZHITU_ENABLED=false keeps ZhituFetcher out of the manager entirely.

        is_available is forced True and the token is set so the assertion
        isolates the enable switch: without the gate, this fetcher would
        register, so a failure here is unambiguously "the gate didn't fire",
        not "the token happened to be missing".
        """
        from stock_data.data_provider.manager import create_default_manager

        monkeypatch.setenv("ZHITU_TOKEN", "fake-token-for-test")
        monkeypatch.setattr(ZhituFetcher, "is_available", lambda self: True)
        monkeypatch.setenv("ZHITU_ENABLED", "true")
        assert "ZhituFetcher" in [f.name for f in create_default_manager().fetchers]

        monkeypatch.setenv("ZHITU_ENABLED", "false")
        manager = create_default_manager()
        assert "ZhituFetcher" not in [f.name for f in manager.fetchers]

    def test_disabled_fetcher_leaves_the_slug_index(self, monkeypatch):
        """Source-routed endpoints must not resolve a disabled source.

        _slug_index is built by _refresh_index() from the registered list, so
        this is the property that removes the fetcher from the board
        endpoints — where _with_source() bypasses priority-based failover and
        there is no ordering to manipulate.
        """
        from stock_data.data_provider.manager import create_default_manager

        monkeypatch.setenv("THS_ENABLED", "false")
        manager = create_default_manager()
        assert "ths" not in manager._slug_index, (
            "disabled fetcher still reachable via _slug_index — board "
            "endpoints (?source=ths) would keep serving it"
        )

    def test_disabled_fetcher_is_never_instantiated(self, monkeypatch):
        """The gate runs before cls(), so a disabled fetcher is not constructed.

        If the check were placed after instantiation, a disabled SDK fetcher
        would still run its class-level init (reading a token, possibly
        touching the network) on every process start.
        """
        from stock_data.data_provider.manager import create_default_manager

        instantiated: list[str] = []
        real_init = ZhituFetcher.__init__

        def spy_init(self, *args, **kwargs):
            instantiated.append(type(self).name)
            return real_init(self, *args, **kwargs)

        monkeypatch.setattr(ZhituFetcher, "__init__", spy_init)
        monkeypatch.setenv("ZHITU_ENABLED", "false")
        create_default_manager()
        assert "ZhituFetcher" not in instantiated

    def test_no_enabled_var_set_drops_nobody(self, monkeypatch):
        """Regression: the default must be enabled for all 13 fetchers.

        Asserted against each class's own is_available() rather than a
        hardcoded name list, because which fetchers are available depends on
        tokens and installed SDKs in the environment — a name list would be
        flaky. This still catches a wrong default: if "true" parsed as falsy,
        create_default_manager() would register zero fetchers and fail here.
        """
        from stock_data.data_provider.manager import _all_fetcher_classes, create_default_manager

        for cls in _all_fetcher_classes():
            monkeypatch.delenv(cls.enabled_env_var(), raising=False)

        manager = create_default_manager()
        registered = {f.name for f in manager.fetchers}
        expected = {cls.name for cls in _all_fetcher_classes() if cls().is_available()}
        assert registered == expected
