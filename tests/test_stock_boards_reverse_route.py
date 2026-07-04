"""Tests for unified /stocks/{code}/boards endpoint with CSV source + cold_fill."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from stock_data.data_provider.persistence import board as board_mod
from stock_data.data_provider.persistence import db as db_mod
from stock_data.data_provider.persistence import stock_list as stock_list_mod


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    # NOTE: project's `.env` sets STOCK_DB_INIT=true, which causes the FastAPI
    # lifespan to DROP+recreate all tables on every TestClient startup. We
    # must disable it BEFORE lifespan runs, otherwise our seeded stock_list
    # row gets wiped.
    monkeypatch.setenv("STOCK_DB_INIT", "false")
    monkeypatch.setattr(db_mod, "_db_path", None)
    monkeypatch.setattr(db_mod, "_conn", None)
    monkeypatch.setattr(board_mod, "_schema_initialized_paths", set())
    monkeypatch.setattr(stock_list_mod, "_schema_initialized_paths", set())
    monkeypatch.setenv("STOCK_CACHE_DB_PATH", str(tmp_path / "test.db"))
    board_mod.init_schema()
    stock_list_mod.init_schema()
    # Seed stock_list with one entry
    conn = db_mod.get_connection()
    conn.execute("""
        INSERT INTO stock_list (code, name, market) VALUES ('600519', '贵州茅台', 'csi')
    """)
    conn.commit()
    yield tmp_path / "test.db"


def test_single_source_returns_per_entry_source_field(fresh_db):
    """Per-entry source field must appear on each returned board."""
    board_mod.upsert_membership_bulk(
        source="zhitu",
        stocks=[{"stock_code": "600519", "stock_name": "贵州茅台"}],
        board_code="sw_yx_baijiu", board_name="白酒",
        board_type="industry", subtype="申万行业",
    )
    with TestClient(_app_for_test) as client:
        r = client.get("/api/v1/stocks/600519/boards?source=zhitu")
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "persistence"  # cache hit
    assert body["cold_sources"] == []
    assert len(body["data"]) == 1
    assert body["data"][0]["source"] == "zhitu"  # per-entry source
    assert body["data"][0]["code"] == "sw_yx_baijiu"


def test_csv_source_aggregates_multiple_sources(fresh_db):
    """?source=zhitu,eastmoney aggregates entries; per-entry source distinguishable."""
    board_mod.upsert_membership_bulk(
        source="zhitu",
        stocks=[{"stock_code": "600519", "stock_name": "x"}],
        board_code="sw_yx", board_name="SW", board_type="industry", subtype="申万行业",
    )
    board_mod.upsert_membership_bulk(
        source="eastmoney",
        stocks=[{"stock_code": "600519", "stock_name": "x"}],
        board_code="BK1048", board_name="EM", board_type="concept", subtype="concept",
    )
    with TestClient(_app_for_test) as client:
        r = client.get("/api/v1/stocks/600519/boards?source=zhitu,eastmoney")
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "merged"
    # Only the user-requested sources (zhitu, eastmoney) are queried, so cold_sources
    # is empty when both are present. zzshare is excluded because user didn't request it.
    assert body["cold_sources"] == []
    by_src = {e["source"] for e in body["data"]}
    assert by_src == {"zhitu", "eastmoney"}


def test_ths_canonical_in_csv(fresh_db):
    """?source=ths,zhitu → ths stays as ths (no longer aliases to zzshare)."""
    with patch("stock_data.data_provider.persistence.board.get_stock_memberships") as mock:
        mock.return_value = ([], ["ths", "zhitu"], "")
        with TestClient(_app_for_test) as client:
            r = client.get("/api/v1/stocks/600519/boards?source=ths,zhitu")
        assert r.status_code == 200
        called = mock.call_args.kwargs["sources"]
        assert "ths" in called
        assert "zzshare" not in called
        assert "zhitu" in called


def test_zzshare_aliases_to_ths(fresh_db):
    """?source=zzshare now aliases to ths (data is THS upstream)."""
    with patch("stock_data.data_provider.persistence.board.get_stock_memberships") as mock:
        mock.return_value = ([], ["ths"], "")
        with TestClient(_app_for_test) as client:
            r = client.get("/api/v1/stocks/600519/boards?source=zzshare")
        assert r.status_code == 200
        called = mock.call_args.kwargs["sources"]
        assert called == ["ths"]


def test_no_source_aggregates_all(fresh_db):
    """Omitting ?source= aggregates (ths, eastmoney, zhitu) — no zzshare."""
    with patch("stock_data.data_provider.persistence.board.get_stock_memberships") as mock:
        mock.return_value = (
            [{"code": "x", "name": "x", "type": "concept", "subtype": "", "source": "zhitu"}],
            [],
            "mixed",
        )
        with TestClient(_app_for_test) as client:
            r = client.get("/api/v1/stocks/600519/boards")
        assert r.status_code == 200
        called = mock.call_args.kwargs["sources"]
        assert set(called) == {"ths", "eastmoney", "zhitu"}


def test_ths_industry_filter_returns_400(fresh_db):
    """ths only supports concept; ?source=ths&type=industry → 400 (bad_request).

    Note: error code is ``bad_request`` (not ``invalid_subtype``) because the
    route delegates to ``stock_board_cache._validate_subtype`` which raises
    ValueError, and ``@map_errors`` uniformly maps ValueError → bad_request.
    Same convention as the existing ``/boards/{board_code}/stocks`` endpoint.
    """
    with TestClient(_app_for_test) as client:
        r = client.get("/api/v1/stocks/600519/boards?source=ths&type=industry&subtype=申万行业")
    assert r.status_code == 400
    assert r.json()["detail"]["error"] == "bad_request"


def test_cold_fill_false_does_not_trigger_lazy_fill(fresh_db):
    """?cold_fill=false (default) → cold source appears in cold_sources, no fetcher call."""
    mock_manager = MagicMock()
    with (
        TestClient(_app_for_test) as client,
        patch("stock_data.api.routes.boards.get_manager", return_value=mock_manager),
    ):
        r = client.get("/api/v1/stocks/600519/boards?source=zhitu")
    assert r.status_code == 200
    body = r.json()
    assert body["cold_sources"] == ["zhitu"]
    assert body["data"] == []
    mock_manager.get_stock_boards.assert_not_called()


def test_cold_fill_ths_triggers_ths_fetcher(fresh_db):
    """?cold_fill=true&source=ths → fetcher called with source='ths'."""
    mock_manager = MagicMock()
    # First read returns empty (cache miss); second read after cold-fill returns data
    mock_manager.get_stock_boards.return_value = (
        [
            {"code": "885642", "name": "跨境电商",
             "type": "concept", "subtype": "同花顺概念"},
        ],
        "ths",  # fetcher name
    )
    with (
        TestClient(_app_for_test) as client,
        patch("stock_data.api.routes.boards.get_manager", return_value=mock_manager),
    ):
        r = client.get("/api/v1/stocks/600519/boards?source=ths&cold_fill=true")
    assert r.status_code == 200
    # fetcher was called with source='ths'
    mock_manager.get_stock_boards.assert_called_once()
    call_kwargs = mock_manager.get_stock_boards.call_args.kwargs
    assert call_kwargs["source"] == "ths"


def test_invalid_source_in_csv_returns_400(fresh_db):
    """Unknown source in CSV → 400 with error detail."""
    with TestClient(_app_for_test) as client:
        r = client.get("/api/v1/stocks/600519/boards?source=zhitu,bogus")
    assert r.status_code == 400
    assert r.json()["detail"]["error"] == "invalid_source"


# --- normalize_stock_board_source -----------------------------------

def test_normalize_stock_board_source_canonical():
    """ths / eastmoney / zhitu pass through unchanged."""
    from stock_data.data_provider.persistence.board import normalize_stock_board_source
    assert normalize_stock_board_source("ths") == "ths"
    assert normalize_stock_board_source("eastmoney") == "eastmoney"
    assert normalize_stock_board_source("zhitu") == "zhitu"


def test_normalize_stock_board_source_zzshare_alias():
    """zzshare aliases to ths (data is THS upstream)."""
    from stock_data.data_provider.persistence.board import normalize_stock_board_source
    assert normalize_stock_board_source("zzshare") == "ths"


def test_normalize_stock_board_source_invalid_raises():
    """Unknown source raises ValueError."""
    from stock_data.data_provider.persistence.board import normalize_stock_board_source
    with pytest.raises(ValueError, match="Unknown stock-boards source"):
        normalize_stock_board_source("bogus")
    with pytest.raises(ValueError, match="Unknown stock-boards source"):
        normalize_stock_board_source("")


def test_normalize_stock_board_source_does_not_alias_other_directions():
    """ths is canonical (does NOT alias to zzshare)."""
    from stock_data.data_provider.persistence.board import normalize_stock_board_source
    assert normalize_stock_board_source("ths") != "zzshare"


# Lazy import — keeps this module cheap to collect when only the persistence
# tests above are being run via -k "not stock_boards_reverse_route".
from stock_data.server import app as _app_for_test  # noqa: E402
