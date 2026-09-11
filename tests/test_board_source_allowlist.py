"""One allowlist, one alias policy (spec §9).

Pre-split there were four source allowlists in three places, three of them
textually identical, with two different alias behaviours — which is how
`?source=zzshare` ended up 422 on two routes, 200-with-ths-data on a third,
and 400 on a fourth.
"""

from __future__ import annotations

import pytest

from stock_data.api.routes import boards as routes_mod
from stock_data.data_provider.persistence import board as board_mod


class TestAllowlists:
    def test_zzshare_is_a_first_class_forward_source(self):
        assert "zzshare" in board_mod.VALID_SOURCES

    def test_zzshare_is_a_first_class_board_stocks_source(self):
        assert "zzshare" in board_mod._BOARD_STOCKS_VALID_SOURCES

    def test_zzshare_is_a_first_class_stock_boards_source(self):
        assert "zzshare" in board_mod._STOCK_BOARDS_VALID_SOURCES

    def test_history_allowlist_excludes_zzshare(self):
        """zzshare's plate_kline only serves 883957 — no board K-line."""
        assert "zzshare" not in routes_mod._BOARD_HISTORY_VALID_SOURCES

    def test_every_allowlist_is_the_same_object_or_equal(self):
        assert set(board_mod.VALID_SOURCES) == set(board_mod._BOARD_STOCKS_VALID_SOURCES)
        assert set(board_mod.VALID_SOURCES) == set(board_mod._STOCK_BOARDS_VALID_SOURCES)


class TestNoAliasesRemain:
    def test_stock_boards_alias_map_is_gone(self):
        assert not hasattr(board_mod, "_STOCK_BOARDS_SOURCE_ALIAS")

    def test_history_resolver_does_not_alias_zzshare(self):
        """zzshare has no board-K-line upstream → 400, NOT an alias to ths.

        The resolver raises HTTPException(400) (not ValueError) — it is a
        route-layer helper and the route wants the 400-class response.
        """
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            routes_mod._resolve_board_history_source("zzshare")
        assert exc.value.status_code == 400

    def test_dead_normalizer_removed(self):
        """Zero production callers before the split; still zero after."""
        assert not hasattr(board_mod, "normalize_stock_board_source")

    def test_surviving_normalizer_returns_zzshare_verbatim(self):
        """`normalize_board_stocks_source` keeps its one production caller
        (boards.py) and no longer aliases — zzshare passes through."""
        assert board_mod.normalize_board_stocks_source("zzshare") == "zzshare"
        assert board_mod.normalize_board_stocks_source("ths") == "ths"
        with pytest.raises(ValueError):
            board_mod.normalize_board_stocks_source("nope")


class TestSourceParsing:
    def test_csv_parser_accepts_zzshare(self):
        assert routes_mod._parse_stock_boards_source_csv("ths,zzshare") == ["ths", "zzshare"]

    def test_default_csv_is_all_sources_including_zzshare(self):
        assert set(routes_mod._parse_stock_boards_source_csv(None)) == {
            "ths",
            "zzshare",
            "eastmoney",
            "zhitu",
        }
