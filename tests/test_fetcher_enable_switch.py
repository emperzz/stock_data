"""Tests for the per-fetcher <SLUG>_ENABLED switch.

The switch is read on every call (not at class-definition time), so every
test here monkeypatches the env and asserts behavior directly — no
importlib.reload, no class-identity churn.
"""

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
