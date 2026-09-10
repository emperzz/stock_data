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
