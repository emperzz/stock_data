"""Tests for EastMoneyFetcher.get_stock_boards (push2 slist/get direct HTTP).

The live tests at the bottom (TestGetStockBoardsLive) hit the real upstream
and are tagged ``@pytest.mark.live_network`` so the default ``pytest`` run
skips them via ``pyproject.toml addopts = ["-m", "not live_network"]``. To
run them: ``pytest -m live_network tests/test_eastmoney_stock_boards.py``.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from stock_data.data_provider.base import DataFetchError
from stock_data.data_provider.fetchers.eastmoney_fetcher import EastMoneyFetcher

SAMPLE_RESPONSE = {
    "rc": 0,
    "rt": 18,
    "data": {
        "total": 29,
        "diff": [
            {
                "f3": 34,
                "f4": 8180,
                "f12": "BK0438",
                "f13": 90,
                "f14": "食品饮料",
                "f128": "中炬高新",
                "f140": "600872",
                "f141": 1,
                "f152": 2,
            },
            {
                "f3": -105,
                "f4": -4222,
                "f12": "BK1277",
                "f13": 90,
                "f14": "白酒Ⅱ",
                "f128": "贵州茅台",
                "f140": "600519",
                "f141": 1,
                "f152": 2,
            },
            {
                "f3": -12,
                "f4": -4387,
                "f12": "BK0477",
                "f13": 90,
                "f14": "酿酒概念",
                "f128": "*ST西发",
                "f140": "000752",
                "f141": 0,
                "f152": 2,
            },
        ],
    },
}


def _mock_resp(payload: dict, status: int = 200) -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.json.return_value = payload
    r.text = json.dumps(payload, ensure_ascii=False)
    return r


def test_returns_normalized_list():
    fetcher = EastMoneyFetcher()
    with patch.object(fetcher._session, "get", return_value=_mock_resp(SAMPLE_RESPONSE)):
        result = fetcher.get_stock_boards("600519", source="eastmoney")
    assert result is not None
    assert len(result) == 3
    first = result[0]
    assert first["code"] == "BK0438"
    assert first["name"] == "食品饮料"
    assert first["change_pct"] == pytest.approx(0.34)
    assert first["leading_stock_code"] == "600872"


def test_secid_format_sh_for_6xxxxx():
    fetcher = EastMoneyFetcher()
    with patch.object(fetcher._session, "get", return_value=_mock_resp(SAMPLE_RESPONSE)) as m:
        fetcher.get_stock_boards("600519", source="eastmoney")
    params = m.call_args.kwargs["params"]
    assert params["secid"] == "1.600519"


def test_secid_format_sz_for_other():
    fetcher = EastMoneyFetcher()
    with patch.object(fetcher._session, "get", return_value=_mock_resp(SAMPLE_RESPONSE)) as m:
        fetcher.get_stock_boards("000001", source="eastmoney")
    params = m.call_args.kwargs["params"]
    assert params["secid"] == "0.000001"


def test_returns_empty_list_on_empty_data():
    fetcher = EastMoneyFetcher()
    empty = {"rc": 0, "data": {"total": 0, "diff": []}}
    with patch.object(fetcher._session, "get", return_value=_mock_resp(empty)):
        result = fetcher.get_stock_boards("600519", source="eastmoney")
    assert result == []


def test_raises_on_network_error():
    fetcher = EastMoneyFetcher()
    with (
        patch.object(fetcher._session, "get", side_effect=Exception("timeout")),
        pytest.raises(DataFetchError),
    ):
        fetcher.get_stock_boards("600519", source="eastmoney")


class TestGetStockBoardsTypeOverride:
    """Fetcher enriches type/subtype from the stock_board cache via lazy import.

    EastMoney's upstream reply cannot distinguish concept / industry (f152 is
    always 2), so the fetcher hardcodes ``"industry"`` and reaches into the
    persistence layer's authoritative ``stock_board`` table to recover the
    true classification. Boards whose code is unknown to the cache keep the
    fetcher's fallback. These tests pin that behavior.
    """

    @pytest.fixture
    def _seed_stock_board(self, tmp_path, monkeypatch):
        """Seed stock_board with two boards of different types."""
        from stock_data.data_provider.persistence import board as board_mod
        from stock_data.data_provider.persistence import db as db_mod

        monkeypatch.setattr(db_mod, "_db_path", None)
        monkeypatch.setattr(db_mod, "_conn", None)
        board_mod._schema_initialized_paths = set()
        monkeypatch.setenv("STOCK_CACHE_DB_PATH", str(tmp_path / "test_eastmoney.db"))
        board_mod.init_schema()
        conn = db_mod.get_connection()
        # BK0438: known concept in cache
        conn.execute(
            "INSERT INTO stock_board (code, name, board_type, subtype, source) "
            "VALUES (?, ?, ?, ?, ?)",
            ("BK0438", "食品饮料", "industry", "industry", "eastmoney"),
        )
        # BK0477: known concept in cache (overrides upstream "industry" fallback)
        conn.execute(
            "INSERT INTO stock_board (code, name, board_type, subtype, source) "
            "VALUES (?, ?, ?, ?, ?)",
            ("BK0477", "酿酒概念", "concept", "concept", "eastmoney"),
        )
        conn.commit()
        return board_mod

    def test_known_concept_overrides_industry_fallback(
        self,
        _seed_stock_board,
    ):
        """BK0477 is cached as concept → fetcher output uses 'concept', not 'industry'."""
        fetcher = EastMoneyFetcher()
        with patch.object(fetcher._session, "get", return_value=_mock_resp(SAMPLE_RESPONSE)):
            result = fetcher.get_stock_boards("600519", source="eastmoney")
        by_code = {b["code"]: b for b in result}
        assert by_code["BK0477"]["type"] == "concept"
        assert by_code["BK0477"]["subtype"] == "concept"

    def test_known_industry_keeps_industry_tag(
        self,
        _seed_stock_board,
    ):
        """BK0438 is cached as industry → fetcher output matches cache."""
        fetcher = EastMoneyFetcher()
        with patch.object(fetcher._session, "get", return_value=_mock_resp(SAMPLE_RESPONSE)):
            result = fetcher.get_stock_boards("600519", source="eastmoney")
        by_code = {b["code"]: b for b in result}
        assert by_code["BK0438"]["type"] == "industry"
        assert by_code["BK0438"]["subtype"] == "industry"

    def test_unknown_board_keeps_fetcher_fallback(
        self,
        _seed_stock_board,
    ):
        """BK1277 not in cache → fetcher's hardcoded 'industry' / 'industry' stays."""
        fetcher = EastMoneyFetcher()
        with patch.object(fetcher._session, "get", return_value=_mock_resp(SAMPLE_RESPONSE)):
            result = fetcher.get_stock_boards("600519", source="eastmoney")
        by_code = {b["code"]: b for b in result}
        assert by_code["BK1277"]["type"] == "industry"
        assert by_code["BK1277"]["subtype"] == "industry"

    def test_enrichment_falls_back_gracefully_when_persistence_unavailable(self):
        """If persistence lookup raises (e.g. DB unreachable), fetcher keeps its defaults."""
        fetcher = EastMoneyFetcher()

        def _boom(*_args, **_kwargs):
            raise RuntimeError("simulated DB failure")

        with (
            patch.object(fetcher._session, "get", return_value=_mock_resp(SAMPLE_RESPONSE)),
            patch(
                "stock_data.data_provider.persistence.board.resolve_board_types",
                side_effect=_boom,
            ),
        ):
            result = fetcher.get_stock_boards("600519", source="eastmoney")
        # No exception; all entries keep the fetcher's hardcoded fallback.
        assert all(b["type"] == "industry" for b in result)
        assert all(b["subtype"] == "industry" for b in result)


# ---------------------------------------------------------------------------
# Live network tests (skipped by default; see module docstring).
# ---------------------------------------------------------------------------


@pytest.mark.live_network
class TestGetStockBoardsLive:
    @pytest.fixture(scope="class")
    def fetcher(self):
        return EastMoneyFetcher()

    def test_600519_returns_real_boards(self, fetcher):
        """贵州茅台: page shows 食品饮料/白酒Ⅲ/白酒Ⅱ/贵州板块/酿酒概念 as first 5."""
        result = fetcher.get_stock_boards("600519", source="eastmoney")
        assert result is not None, "Should not return None for valid SH code"
        assert len(result) > 0, "贵州茅台 should belong to multiple boards"
        codes = {b["code"] for b in result}
        names = {b["name"] for b in result}
        # BK1277 = 白酒Ⅱ, BK0438 = 食品饮料 — both should appear
        assert "BK1277" in codes, f"Expected BK1277 in {codes}"
        assert any("白酒" in n for n in names), f"Expected 白酒* in {names}"
        assert any("食品饮料" in n or "酿酒" in n for n in names), (
            f"Expected 食品饮料/酿酒 in {names}"
        )

    def test_000001_sz_secid(self, fetcher):
        """平安银行 (SZ) — verify secid construction works for non-SH codes."""
        result = fetcher.get_stock_boards("000001", source="eastmoney")
        assert result is not None
        assert len(result) > 0

    def test_invalid_code_returns_none(self, fetcher):
        result = fetcher.get_stock_boards("", source="eastmoney")
        assert result is None
