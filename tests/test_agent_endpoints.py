"""Tests for /api/v1/agent/* endpoints (Phase 1 + Phase 2)."""

import contextlib
from unittest.mock import patch

import pandas as pd
import pytest

from stock_data.api.routes import reset_manager
from stock_data.data_provider.core.types import RealtimeSource, UnifiedRealtimeQuote


@pytest.fixture(autouse=True)
def reset_before_test():
    reset_manager()
    # Clear all response-level TTLCaches (incl. the get_quote_cache slot
    # reused by agent endpoints) so the same body+codes tuple doesn't
    # leak a result from a prior test.
    from stock_data.api import cache as api_cache

    for getter_name in (
        "get_quote_cache",
        "get_index_quote_cache",
        "get_history_cache",
        "get_pools_cache",
        "get_stock_info_cache",
        "get_news_flash_cache",
        "get_cls_feed_cache",
        "get_dragontiger_cache",
    ):
        getter = getattr(api_cache, getter_name, None)
        if getter is None:
            continue
        with contextlib.suppress(TypeError):
            getter().clear()
        # get_history_cache needs a frequency arg
        for f in ("d", "w", "m", "1", "5", "15", "30", "60"):
            with contextlib.suppress(Exception):
                api_cache.get_history_cache(f).clear()
    yield


_BOARD_STOCKS_PATCH = "stock_data.data_provider.persistence.board.get_board_stocks"


class TestBoardsOverlap:
    def test_two_boards_intersection_jaccard(self, client):
        """Two boards with overlap → intersection + jaccard computed."""
        with patch(_BOARD_STOCKS_PATCH) as mock_bs:
            mock_bs.side_effect = [
                # First board: 600519, 000001
                (
                    [
                        {"stock_code": "600519", "stock_name": "贵州茅台"},
                        {"stock_code": "000001", "stock_name": "平安银行"},
                    ],
                    "persistence",
                    "ths",
                    None,
                    False,
                    2,
                ),
                # Second board: 600519, 688981
                (
                    [
                        {"stock_code": "600519", "stock_name": "贵州茅台"},
                        {"stock_code": "688981", "stock_name": "中芯国际"},
                    ],
                    "persistence",
                    "ths",
                    None,
                    False,
                    2,
                ),
            ]
            response = client.post(
                "/api/v1/agent/boards/stock-overlap",
                json={"codes": ["885xxx", "881yyy"]},
            )
            assert response.status_code == 200
            data = response.json()
            assert len(data["sets"]) == 2
            assert data["sets"][0]["count"] == 2
            assert len(data["pairs"]) == 1
            pair = data["pairs"][0]
            assert {pair["a"], pair["b"]} == {"885xxx", "881yyy"} or (
                pair["a"] == "885xxx" and pair["b"] == "881yyy"
            )
            assert pair["intersection"] == ["600519"]
            assert pair["intersection_count"] == 1
            # union = {600519, 000001, 688981} = 3, intersection = 1
            assert abs(pair["jaccard"] - 1 / 3) < 1e-9

    def test_codes_too_few_400(self, client):
        """codes < 2 → 400."""
        response = client.post(
            "/api/v1/agent/boards/stock-overlap",
            json={"codes": ["885xxx"]},
        )
        # Pydantic min_length=2 → 422 (FastAPI validation)
        assert response.status_code == 422

    def test_codes_too_many_400(self, client):
        """codes > 10 → 400 (422 from Pydantic)."""
        response = client.post(
            "/api/v1/agent/boards/stock-overlap",
            json={"codes": [f"885{i:03d}" for i in range(11)]},
        )
        assert response.status_code == 422

    def test_one_board_upstream_fails_other_succeeds(self, client):
        """One board fails upstream → errors[] populated, other pairs still computed."""
        with patch(_BOARD_STOCKS_PATCH) as mock_bs:
            from stock_data.data_provider.base import DataFetchError

            mock_bs.side_effect = [
                # First board succeeds
                (
                    [{"stock_code": "600519", "stock_name": "贵州茅台"}],
                    "persistence",
                    "ths",
                    None,
                    False,
                    1,
                ),
                # Second board raises
                DataFetchError("upstream timeout"),
                # Third board succeeds
                (
                    [{"stock_code": "600519", "stock_name": "贵州茅台"}],
                    "persistence",
                    "ths",
                    None,
                    False,
                    1,
                ),
            ]
            response = client.post(
                "/api/v1/agent/boards/stock-overlap",
                json={"codes": ["A", "B", "C"]},
            )
            assert response.status_code == 200
            data = response.json()
            # B is missing from sets, recorded in errors
            assert {s["code"] for s in data["sets"]} == {"A", "C"}
            assert any(e.get("code") == "B" for e in data["errors"])
            # Pairs that include B are dropped; A-C pair still present
            assert all("B" not in (p["a"], p["b"]) for p in data["pairs"])


_STOCK_MEMBERSHIPS_PATCH = "stock_data.data_provider.persistence.board.get_stock_memberships"


class TestStocksBoardOverlap:
    def test_two_stocks_common_boards(self, client):
        with patch(_STOCK_MEMBERSHIPS_PATCH) as mock_sm:
            mock_sm.side_effect = [
                (
                    [
                        {
                            "code": "885xxx",
                            "name": "半导体",
                            "type": "concept",
                            "subtype": "",
                            "source": "ths",
                        },
                        {
                            "code": "881yyy",
                            "name": "电子",
                            "type": "industry",
                            "subtype": "",
                            "source": "ths",
                        },
                    ],
                    [],
                    "persistence",
                ),
                (
                    [
                        {
                            "code": "885xxx",
                            "name": "半导体",
                            "type": "concept",
                            "subtype": "",
                            "source": "ths",
                        },
                        {
                            "code": "882zzz",
                            "name": "新能源",
                            "type": "concept",
                            "subtype": "",
                            "source": "ths",
                        },
                    ],
                    [],
                    "persistence",
                ),
            ]
            response = client.post(
                "/api/v1/agent/stocks/board-overlap",
                json={"codes": ["600519", "688981"]},
            )
            assert response.status_code == 200
            data = response.json()
            assert len(data["sets"]) == 2
            assert len(data["pairs"]) == 1
            pair = data["pairs"][0]
            assert pair["intersection_count"] == 1
            assert pair["common_boards"][0]["code"] == "885xxx"
            # union = {885xxx, 881yyy, 882zzz} = 3, intersection = 1
            assert abs(pair["jaccard"] - 1 / 3) < 1e-9

    def test_codes_out_of_range_422(self, client):
        response = client.post(
            "/api/v1/agent/stocks/board-overlap",
            json={"codes": ["600519"]},
        )
        assert response.status_code == 422

    def test_per_stock_error_isolated(self, client):
        with patch(_STOCK_MEMBERSHIPS_PATCH) as mock_sm:
            from stock_data.data_provider.base import DataFetchError

            mock_sm.side_effect = [
                # First stock OK
                (
                    [
                        {
                            "code": "885xxx",
                            "name": "X",
                            "type": "concept",
                            "subtype": "",
                            "source": "ths",
                        }
                    ],
                    [],
                    "persistence",
                ),
                # Second stock upstream fails
                DataFetchError("network error"),
                # Third stock OK
                (
                    [
                        {
                            "code": "885xxx",
                            "name": "X",
                            "type": "concept",
                            "subtype": "",
                            "source": "ths",
                        }
                    ],
                    [],
                    "persistence",
                ),
            ]
            response = client.post(
                "/api/v1/agent/stocks/board-overlap",
                json={"codes": ["A", "B", "C"]},
            )
            assert response.status_code == 200
            data = response.json()
            assert {s["code"] for s in data["sets"]} == {"A", "C"}
            assert any(e["code"] == "B" for e in data["errors"])


class TestFilterStocks:
    def _patch_board(self, stocks):
        return patch(
            _BOARD_STOCKS_PATCH,
            return_value=(
                stocks,
                "persistence",
                "ths",
                None,
                False,
                len(stocks),
            ),
        )

    def test_filter_turnover_min_excludes_below(self, client):
        """Stocks below the turnover minimum are excluded."""
        rows = [
            {
                "stock_code": "A",
                "stock_name": "A",
                "price": 10.0,
                "change_pct": 5.0,
                "turnover_rate": 3.0,
                "amount": 1e9,
                "total_mv": 1e9,
                "open": 9.0,
                "high": 10.0,
                "low": 9.0,
                "volume": 0,
            },
            {
                "stock_code": "B",
                "stock_name": "B",
                "price": 20.0,
                "change_pct": 7.0,
                "turnover_rate": 8.0,
                "amount": 5e9,
                "total_mv": 5e9,
                "open": 19.0,
                "high": 21.0,
                "low": 19.0,
                "volume": 0,
            },
        ]
        with self._patch_board(rows):
            response = client.post(
                "/api/v1/agent/boards/filter-stocks",
                json={
                    "board_code": "885001",
                    "source": "ths",
                    "filters": {"turnover_pct": {"min": 5.0}},
                },
            )
            assert response.status_code == 200
            data = response.json()
            assert data["summary"]["total_in_board"] == 2
            assert data["summary"]["matched"] == 1
            assert data["matched_stocks"][0]["code"] == "B"
            # B: amount = 5e9 元 → 50 亿; mcap = 5e9 → 50 亿
            assert abs(data["matched_stocks"][0]["amount_yi"] - 50.0) < 1e-6
            assert abs(data["matched_stocks"][0]["mcap_yi"] - 50.0) < 1e-6
            # max_gain = (21 - 19) / 19 * 100 ≈ 10.526
            assert abs(data["matched_stocks"][0]["max_gain_pct"] - (2 / 19 * 100)) < 1e-6

    def test_max_gain_pct_min_filter(self, client):
        """max_gain_pct < min excludes stocks with low intraday gain."""
        rows = [
            {
                "stock_code": "A",
                "stock_name": "A",
                "price": 10.0,
                "change_pct": 1.0,
                "turnover_rate": 5.0,
                "amount": 1e9,
                "total_mv": 1e9,
                "open": 10.0,
                "high": 10.2,
                "low": 9.8,
                "volume": 0,
            },
            {
                "stock_code": "B",
                "stock_name": "B",
                "price": 20.0,
                "change_pct": 6.0,
                "turnover_rate": 10.0,
                "amount": 5e9,
                "total_mv": 5e9,
                "open": 19.0,
                "high": 21.0,
                "low": 19.0,
                "volume": 0,
            },
        ]
        with self._patch_board(rows):
            response = client.post(
                "/api/v1/agent/boards/filter-stocks",
                json={
                    "board_code": "885002",
                    "source": "ths",
                    "filters": {"max_gain_pct": {"min": 5.0}},
                },
            )
            assert response.status_code == 200
            data = response.json()
            # A: max_gain = 0.2/10*100 = 2% (excluded)
            # B: max_gain = 2/19*100 ≈ 10.526% (included)
            assert data["summary"]["matched"] == 1
            assert data["matched_stocks"][0]["code"] == "B"

    def test_limit_truncates(self, client):
        rows = [
            {
                "stock_code": f"S{i}",
                "stock_name": f"S{i}",
                "price": 10.0 + i,
                "change_pct": 5.0,
                "turnover_rate": 5.0,
                "amount": 1e9,
                "total_mv": 1e9,
                "open": 9.0,
                "high": 10.0,
                "low": 9.0,
                "volume": 0,
            }
            for i in range(10)
        ]
        with self._patch_board(rows):
            response = client.post(
                "/api/v1/agent/boards/filter-stocks",
                json={
                    "board_code": "885003",
                    "source": "ths",
                    "filters": {},
                    "limit": 3,
                },
            )
            assert response.status_code == 200
            data = response.json()
            assert data["summary"]["matched"] == 3
            assert data["summary"]["limit_applied"] is True
            assert len(data["matched_stocks"]) == 3

    def test_empty_filters_returns_all(self, client):
        rows = [
            {
                "stock_code": "A",
                "stock_name": "A",
                "price": 10.0,
                "change_pct": 0.0,
                "turnover_rate": 1.0,
                "amount": 0,
                "total_mv": 1e8,
                "open": 10.0,
                "high": 10.0,
                "low": 10.0,
                "volume": 0,
            },
        ]
        with self._patch_board(rows):
            response = client.post(
                "/api/v1/agent/boards/filter-stocks",
                json={"board_code": "885004", "source": "ths", "filters": {}},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["summary"]["matched"] == 1
            assert data["matched_stocks"][0]["code"] == "A"

    def test_filter_excludes_row_when_value_is_none(self, client):
        """When a filter is set but the row's value is None, the row is excluded.

        Pins the contract: ``_passes_range(value, range_)`` returns False when
        ``value is None and range_ is not None`` (the "no data → no match"
        rule). Stocks with ``turnover_rate=None`` (or missing) must be
        filtered out when ``turnover_pct.min`` is set.
        """
        rows = [
            # A: turnover_rate explicitly None → excluded
            {
                "stock_code": "A",
                "stock_name": "A",
                "price": 10.0,
                "change_pct": 5.0,
                "turnover_rate": None,
                "amount": 1e9,
                "total_mv": 1e9,
                "open": 9.0,
                "high": 10.0,
                "low": 9.0,
                "volume": 0,
            },
            # B: turnover_rate field omitted entirely → also None → excluded
            {
                "stock_code": "B",
                "stock_name": "B",
                "price": 10.0,
                "change_pct": 5.0,
                "amount": 1e9,
                "total_mv": 1e9,
                "open": 9.0,
                "high": 10.0,
                "low": 9.0,
                "volume": 0,
            },
            # C: turnover_rate=8.0 (>= 5.0) → included
            {
                "stock_code": "C",
                "stock_name": "C",
                "price": 20.0,
                "change_pct": 7.0,
                "turnover_rate": 8.0,
                "amount": 5e9,
                "total_mv": 5e9,
                "open": 19.0,
                "high": 21.0,
                "low": 19.0,
                "volume": 0,
            },
        ]
        with self._patch_board(rows):
            response = client.post(
                "/api/v1/agent/boards/filter-stocks",
                json={
                    "board_code": "885005",
                    "source": "ths",
                    "filters": {"turnover_pct": {"min": 5.0}},
                },
            )
            assert response.status_code == 200
            data = response.json()
            assert data["summary"]["total_in_board"] == 3
            assert data["summary"]["matched"] == 1
            assert data["matched_stocks"][0]["code"] == "C"


class TestAgentManifest:
    def test_agent_endpoints_appear_in_manifest(self, client):
        """All 3 new agent endpoints surface in /control/api-manifest under tag=agent."""
        # No mocking needed: the manifest is built from the live router.
        response = client.get("/control/api-manifest")
        assert response.status_code == 200
        manifest = response.json()
        # Find the agent section. Manifest emits `id` (the route tag, see
        # explorer/manifest.py:99), not `tag` — the brief code used `tag`,
        # which doesn't exist on the section dict.
        agent_section = next(
            (s for s in manifest.get("sections", []) if s.get("id") == "agent"),
            None,
        )
        assert agent_section is not None, "No 'agent' tag section in manifest"
        paths = {ep.get("path") for ep in agent_section.get("endpoints", [])}
        assert "/api/v1/agent/boards/stock-overlap" in paths
        assert "/api/v1/agent/stocks/board-overlap" in paths
        assert "/api/v1/agent/boards/filter-stocks" in paths


class TestAgentCacheHit:
    """Second request with identical body must hit the TTLCache and skip the
    persistence/manager call. One test per agent endpoint (3 endpoints).
    """

    def test_cache_hit_boards_stock_overlap(self, client):
        with patch(_BOARD_STOCKS_PATCH) as mock_bs:
            mock_bs.return_value = (
                [{"stock_code": "600519", "stock_name": "贵州茅台"}],
                "persistence",
                "ths",
                None,
                False,
                1,
            )
            payload = {"codes": ["cache_boards_overlap_a", "cache_boards_overlap_b"]}
            r1 = client.post("/api/v1/agent/boards/stock-overlap", json=payload)
            # 1 board fetch per stock; 2 boards → 2 calls. Then assert the 2nd
            # request is a cache hit (call count stays at 2, not 4).
            assert mock_bs.call_count == 2
            r2 = client.post("/api/v1/agent/boards/stock-overlap", json=payload)
            assert r1.status_code == 200
            assert r2.status_code == 200
            assert r1.json() == r2.json()
            assert mock_bs.call_count == 2  # 2nd request hit cache, no extra calls

    def test_cache_hit_stocks_board_overlap(self, client):
        with patch(_STOCK_MEMBERSHIPS_PATCH) as mock_sm:
            mock_sm.side_effect = [
                (
                    [
                        {
                            "code": "885xxx",
                            "name": "半导体",
                            "type": "concept",
                            "subtype": "",
                            "source": "ths",
                        }
                    ],
                    [],
                    "persistence",
                ),
                (
                    [
                        {
                            "code": "885xxx",
                            "name": "半导体",
                            "type": "concept",
                            "subtype": "",
                            "source": "ths",
                        }
                    ],
                    [],
                    "persistence",
                ),
            ]
            payload = {"codes": ["cache_stocks_overlap_c", "cache_stocks_overlap_d"]}
            r1 = client.post("/api/v1/agent/stocks/board-overlap", json=payload)
            # 1 membership fetch per stock; 2 stocks → 2 calls. Then assert
            # the 2nd request is a cache hit (call count stays at 2, not 4).
            assert mock_sm.call_count == 2
            r2 = client.post("/api/v1/agent/stocks/board-overlap", json=payload)
            assert r1.status_code == 200
            assert r2.status_code == 200
            assert r1.json() == r2.json()
            assert mock_sm.call_count == 2  # 2nd request hit cache, no extra calls

    def test_different_limits_use_different_cache_entries(self, client):
        """Limit participates in the cache key because it is applied upstream."""
        rows = [
            {
                "stock_code": f"L{i}",
                "stock_name": f"L{i}",
                "price": 10.0 + i,
                "change_pct": 5.0,
                "turnover_rate": 5.0,
                "amount": 1e9,
                "total_mv": 1e9,
                "open": 9.0,
                "high": 10.0,
                "low": 9.0,
                "volume": 0,
            }
            for i in range(4)
        ]
        with patch(
            _BOARD_STOCKS_PATCH,
            return_value=(
                rows,
                "persistence",
                "ths",
                None,
                False,
                len(rows),
            ),
        ) as mock_bs:
            base = {
                "board_code": "cache_filter_limit_board_001",
                "source": "ths",
                "filters": {},
            }
            first = client.post(
                "/api/v1/agent/boards/filter-stocks",
                json={**base, "limit": 1},
            )
            second = client.post(
                "/api/v1/agent/boards/filter-stocks",
                json={**base, "limit": 3},
            )

            assert first.status_code == 200
            assert second.status_code == 200
            assert len(first.json()["matched_stocks"]) == 1
            assert len(second.json()["matched_stocks"]) == 3
            assert mock_bs.call_count == 2
            assert mock_bs.call_args_list[0].kwargs["top_n"] == 1
            assert mock_bs.call_args_list[1].kwargs["top_n"] == 3

        rows = [
            {
                "stock_code": "X",
                "stock_name": "X",
                "price": 10.0,
                "change_pct": 5.0,
                "turnover_rate": 8.0,
                "amount": 1e9,
                "total_mv": 1e9,
                "open": 9.0,
                "high": 10.0,
                "low": 9.0,
                "volume": 0,
            },
        ]
        with patch(
            _BOARD_STOCKS_PATCH,
            return_value=(
                rows,
                "persistence",
                "ths",
                None,
                False,
                len(rows),
            ),
        ) as mock_bs:
            payload = {
                "board_code": "cache_filter_stocks_board_001",
                "source": "ths",
                "filters": {"turnover_pct": {"min": 5.0}},
            }
            r1 = client.post("/api/v1/agent/boards/filter-stocks", json=payload)
            r2 = client.post("/api/v1/agent/boards/filter-stocks", json=payload)
            assert r1.status_code == 200
            assert r2.status_code == 200
            assert r1.json() == r2.json()
            mock_bs.assert_called_once()


# ============================================================================
# Phase 2 endpoints (3.2.1 / 3.2.2 / 3.2.3 of agent-batch-api-proposal)
# ============================================================================


def _make_unified_quote(code: str, price: float = 100.0) -> UnifiedRealtimeQuote:
    return UnifiedRealtimeQuote(
        code=code,
        name=code,
        source=RealtimeSource.AKSHARE,
        price=price,
        change_pct=1.5,
        change_amount=1.5,
        open_price=99.0,
        high=101.0,
        low=98.5,
        pre_close=98.5,
        volume=1000000,
        amount=1e8,
    )


def _make_kline_df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def _bind_manager(monkeypatch, mock_manager):
    """Bind a MagicMock as the route's get_manager() and return it.

    Use this when you've already built a MagicMock with side_effect /
    return_value set per-method, and just need it wired into the
    request path.
    """
    from stock_data.api.routes import agent as agent_module

    monkeypatch.setattr(agent_module, "get_manager", lambda: mock_manager)
    return mock_manager


class TestIndicesBatchProfile:
    """GET /agent/indices/batch-profile — per-index fan-out (quote + 3 K-line)."""

    def test_default_4_indices_all_ok(self, client, monkeypatch):
        """No ?codes → use the 4 core CSI indices; all 4 succeed."""
        from unittest.mock import MagicMock

        mock_manager = MagicMock()
        mock_manager.get_index_realtime_quote.return_value = _make_unified_quote("000001")
        mock_manager.get_kline_data.return_value = (
            _make_kline_df(
                [
                    {
                        "date": "2026-07-25",
                        "open": 1,
                        "high": 2,
                        "low": 0.5,
                        "close": 1.5,
                        "volume": 100,
                        "amount": 1e6,
                        "pct_chg": 0.1,
                    }
                ]
            ),
            "akshare",
        )
        _bind_manager(monkeypatch, mock_manager)

        response = client.get("/api/v1/agent/indices/batch-profile")
        assert response.status_code == 200
        data = response.json()
        # 4 default codes
        assert data["summary"]["requested"] == 4
        assert data["summary"]["ok"] == 4
        assert data["summary"]["failed"] == 0
        assert len(data["indices"]) == 4
        codes = [p["code"] for p in data["indices"]]
        assert codes == ["000001", "399001", "399006", "899050"]
        # Per-index shape
        first = data["indices"][0]
        assert first["name"]  # resolved from index_symbols
        assert first["quote"] is not None
        assert first["quote"]["current_price"] == 100.0
        # 3 frequencies per index
        assert set(first["klines"].keys()) == {"5m", "d", "w"}
        for _freq, block in first["klines"].items():
            assert block["error"] is None
            assert len(block["data"]) == 1
        # Per-frequency errors dict present
        for freq in ("5m", "d", "w"):
            assert first["errors"][freq] is None

    def test_explicit_codes_2_indices(self, client, monkeypatch):
        """?codes=000001,000300 → 2 indices, 1 quote + 3 K-line each."""
        from unittest.mock import MagicMock

        mock_manager = MagicMock()
        mock_manager.get_index_realtime_quote.return_value = _make_unified_quote("000001")
        mock_manager.get_kline_data.return_value = (_make_kline_df([]), "akshare")
        _bind_manager(monkeypatch, mock_manager)

        response = client.get("/api/v1/agent/indices/batch-profile?codes=000001,000300")
        assert response.status_code == 200
        data = response.json()
        assert data["summary"]["requested"] == 2
        assert data["summary"]["ok"] == 2
        assert {p["code"] for p in data["indices"]} == {"000001", "000300"}

    def test_quote_failure_isolated_klines_still_served(self, client, monkeypatch):
        """Quote fails on one index, but its K-lines still come back."""
        from unittest.mock import MagicMock

        from stock_data.data_provider.base import DataFetchError

        def quote_side(code):
            if code == "000001":
                raise DataFetchError("quote upstream down")
            return _make_unified_quote(code)

        def kline_side(code, **_):
            return (
                _make_kline_df(
                    [
                        {
                            "date": "2026-07-25",
                            "open": 1,
                            "high": 2,
                            "low": 0.5,
                            "close": 1.5,
                            "volume": 100,
                            "amount": 1e6,
                            "pct_chg": 0.1,
                        }
                    ]
                ),
                "akshare",
            )

        mock_manager = MagicMock()
        mock_manager.get_index_realtime_quote.side_effect = quote_side
        mock_manager.get_kline_data.side_effect = kline_side
        _bind_manager(monkeypatch, mock_manager)

        response = client.get("/api/v1/agent/indices/batch-profile?codes=000001,399001")
        assert response.status_code == 200
        data = response.json()
        # 000001 failed (failed counts as 1); 399001 ok
        assert data["summary"]["requested"] == 2
        assert data["summary"]["ok"] == 1
        assert data["summary"]["failed"] == 1
        a, b = data["indices"]
        if a["code"] == "000001":
            failed, ok = a, b
        else:
            failed, ok = b, a
        assert failed["quote"] is None
        assert failed["errors"]["quote"] is not None
        # K-lines still returned for the failed index (per-frequency isolation)
        assert failed["klines"]["5m"]["error"] is None
        assert ok["quote"] is not None
        assert ok["errors"]["quote"] is None

    def test_kline_freq_failure_isolated_others_served(self, client, monkeypatch):
        """5m K-line fails for one index, d and w still served."""
        from unittest.mock import MagicMock

        from stock_data.data_provider.base import DataFetchError

        def kline_side(code, frequency, **_):
            if code == "000001" and frequency == "5":
                raise DataFetchError("5m upstream down")
            return (
                _make_kline_df(
                    [
                        {
                            "date": "2026-07-25",
                            "open": 1,
                            "high": 2,
                            "low": 0.5,
                            "close": 1.5,
                            "volume": 100,
                            "amount": 1e6,
                            "pct_chg": 0.1,
                        }
                    ]
                ),
                "akshare",
            )

        mock_manager = MagicMock()
        mock_manager.get_index_realtime_quote.return_value = _make_unified_quote("000001")
        mock_manager.get_kline_data.side_effect = kline_side
        _bind_manager(monkeypatch, mock_manager)

        response = client.get("/api/v1/agent/indices/batch-profile?codes=000001")
        assert response.status_code == 200
        data = response.json()
        first = data["indices"][0]
        # 5m failed; d/w ok
        assert first["errors"]["5m"] is not None
        assert first["errors"]["d"] is None
        assert first["errors"]["w"] is None
        assert first["klines"]["5m"]["error"] is not None
        assert first["klines"]["5m"]["data"] == []
        assert first["klines"]["d"]["error"] is None
        assert first["klines"]["w"]["error"] is None
        # whole entry marked failed because at least one piece errored
        assert data["summary"]["failed"] == 1

    def test_cache_hit_same_codes(self, client, monkeypatch):
        """Second request with same codes hits TTLCache (no extra manager calls)."""
        from unittest.mock import MagicMock

        from stock_data.api.routes import agent as agent_module

        mock_manager = MagicMock()
        mock_manager.get_index_realtime_quote.return_value = _make_unified_quote("000001")
        mock_manager.get_kline_data.return_value = (_make_kline_df([]), "akshare")
        monkeypatch.setattr(agent_module, "get_manager", lambda: mock_manager)

        r1 = client.get("/api/v1/agent/indices/batch-profile?codes=000001")
        # 1 quote + 3 K-line per index = 4 calls
        assert mock_manager.get_kline_data.call_count == 3
        assert mock_manager.get_index_realtime_quote.call_count == 1
        r2 = client.get("/api/v1/agent/indices/batch-profile?codes=000001")
        assert r1.status_code == 200
        assert r2.status_code == 200
        # 2nd request: counts unchanged
        assert mock_manager.get_kline_data.call_count == 3
        assert mock_manager.get_index_realtime_quote.call_count == 1


class TestMarketContext:
    """GET /agent/market-context — news + zt + dt + dragon-tiger + session."""

    def _patch_all_ok(self, monkeypatch):
        """Standard happy-path manager mock: all 6 sources return data."""
        from unittest.mock import MagicMock

        from stock_data.api.routes import agent as agent_module

        mock_manager = MagicMock()
        mock_manager.get_morning_briefing.return_value = (
            {"article_id": 1, "title": "早报", "date": "2026-07-25"},
            "cls",
        )
        mock_manager.get_market_recap.return_value = (
            {"article_id": 2, "title": "复盘", "date": "2026-07-25"},
            "cls",
        )
        mock_manager.get_flash_news.return_value = (
            [{"title": "快讯1", "url": "u1", "publish_time": "2026-07-25 09:30:00"}],
            "eastmoney",
        )
        mock_manager.get_zt_pool.return_value = (
            [{"code": "600519", "name": "茅台"}],
            "akshare",
            None,
        )
        mock_manager.get_daily_dragon_tiger.return_value = (
            {
                "date": "2026-07-25",
                "total": 2,
                "stocks": [
                    {"code": "600519", "name": "茅台", "net_buy_wan": 5000.0},
                    {"code": "000001", "name": "平安", "net_buy_wan": -2000.0},
                ],
            },
            "zzshare",
        )
        monkeypatch.setattr(agent_module, "get_manager", lambda: mock_manager)
        return mock_manager

    def test_happy_path_all_blocks_present(self, client, monkeypatch):
        from stock_data.api.routes import agent as agent_module

        self._patch_all_ok(monkeypatch)
        # Force post-market so zt/dt pools are not nulled out by pre-market
        # session logic (the real clock would make this test flaky around
        # 09:15 CST).
        monkeypatch.setattr(
            agent_module,
            "_classify_market_session",
            lambda _d, _t: "post-market",
        )
        response = client.get("/api/v1/agent/market-context?flash_limit=10")
        assert response.status_code == 200
        data = response.json()
        # trade_date resolved to a YYYY-MM-DD
        assert len(data["trade_date"]) == 10
        assert "is_trade_day" in data
        assert data["market_session"] in {"pre-market", "intraday", "post-market", "closed"}
        # news block
        assert data["messages"]["morning_briefing"]["title"] == "早报"
        assert data["messages"]["market_recap"]["title"] == "复盘"
        assert len(data["messages"]["flash_news"]) == 1
        # zt/dt pool
        assert data["limit_pools"]["zt"] is not None
        assert len(data["limit_pools"]["zt"]) == 1
        assert data["limit_pools"]["dt"] is not None
        # dragon-tiger
        assert data["dragon_tiger"] is not None
        assert len(data["dragon_tiger"]["stocks"]) == 2
        assert data["dragon_tiger"]["summary"]["total_net_buy_wan"] == 3000.0
        assert data["dragon_tiger"]["summary"]["top_by_net_buy"][0]["code"] == "600519"
        assert data["dragon_tiger"]["summary"]["top_by_net_sell"][0]["code"] == "000001"

    def test_pre_market_pools_forced_null(self, client, monkeypatch):
        """During pre-market (09:15 CST) zt and dt are forced to null regardless of upstream."""

        from stock_data.api.routes import agent as agent_module

        mock_manager = self._patch_all_ok(monkeypatch)

        # Patch the helper to return 'pre-market' regardless of real time
        monkeypatch.setattr(
            agent_module,
            "_classify_market_session",
            lambda _date, _is_td: "pre-market",
        )
        response = client.get("/api/v1/agent/market-context")
        assert response.status_code == 200
        data = response.json()
        assert data["market_session"] == "pre-market"
        # pools forced null even though upstream returned data
        assert data["limit_pools"]["zt"] is None
        assert data["limit_pools"]["dt"] is None
        # But the underlying manager was NOT called for pools in pre-market
        mock_manager.get_zt_pool.assert_not_called()

    def test_morning_briefing_null_on_no_article(self, client, monkeypatch):
        """morning_briefing returns (None, '') (no article for this date) → morning_briefing=null in response."""
        from unittest.mock import MagicMock

        from stock_data.api.routes import agent as agent_module

        mock_manager = MagicMock()
        mock_manager.get_morning_briefing.return_value = (None, "")
        mock_manager.get_market_recap.return_value = (
            {"title": "复盘", "date": "2026-07-25"},
            "cls",
        )
        mock_manager.get_flash_news.return_value = ([], "eastmoney")
        mock_manager.get_zt_pool.return_value = ([], "akshare", None)
        mock_manager.get_daily_dragon_tiger.return_value = ({"stocks": []}, "zzshare")
        monkeypatch.setattr(agent_module, "get_manager", lambda: mock_manager)

        response = client.get("/api/v1/agent/market-context")
        assert response.status_code == 200
        data = response.json()
        assert data["messages"]["morning_briefing"] is None
        # market_recap still ok
        assert data["messages"]["market_recap"] is not None

    def test_dragon_tiger_failure_isolated_other_blocks_served(self, client, monkeypatch):
        """Dragon-tiger upstream fails → dragon_tiger=null; news + pools still emitted."""
        from unittest.mock import MagicMock

        from stock_data.api.routes import agent as agent_module
        from stock_data.data_provider.base import DataFetchError

        mock_manager = MagicMock()
        mock_manager.get_morning_briefing.return_value = (
            {"title": "早报", "date": "2026-07-25"},
            "cls",
        )
        mock_manager.get_market_recap.return_value = (None, "")
        mock_manager.get_flash_news.return_value = ([], "eastmoney")
        mock_manager.get_zt_pool.return_value = ([], "akshare", None)
        mock_manager.get_daily_dragon_tiger.side_effect = DataFetchError("dragon-tiger down")
        monkeypatch.setattr(agent_module, "get_manager", lambda: mock_manager)

        response = client.get("/api/v1/agent/market-context")
        assert response.status_code == 200
        data = response.json()
        assert data["dragon_tiger"] is None
        # Other blocks unaffected
        assert data["messages"]["morning_briefing"] is not None
        assert data["limit_pools"]["zt"] is not None

    def test_trade_date_query_param(self, client, monkeypatch):
        """?trade_date=YYYY-MM-DD is plumbed to morning/recap/dragon-tiger."""
        from unittest.mock import MagicMock

        from stock_data.api.routes import agent as agent_module

        mock_manager = MagicMock()
        mock_manager.get_morning_briefing.return_value = (None, "")
        mock_manager.get_market_recap.return_value = (None, "")
        mock_manager.get_flash_news.return_value = ([], "eastmoney")
        mock_manager.get_zt_pool.return_value = ([], "akshare", None)
        mock_manager.get_daily_dragon_tiger.return_value = ({"stocks": []}, "zzshare")
        monkeypatch.setattr(agent_module, "get_manager", lambda: mock_manager)

        response = client.get("/api/v1/agent/market-context?trade_date=2026-07-20")
        assert response.status_code == 200
        data = response.json()
        assert data["trade_date"] == "2026-07-20"
        # All date-keyed calls got 2026-07-20
        assert mock_manager.get_morning_briefing.call_args.args[0] == "2026-07-20"
        assert mock_manager.get_market_recap.call_args.args[0] == "2026-07-20"
        assert mock_manager.get_daily_dragon_tiger.call_args.args[0] == "2026-07-20"

    def test_cache_hit_same_flash_limit_and_date(self, client, monkeypatch):
        """Second request with same (flash_limit, trade_date) hits cache."""
        from unittest.mock import MagicMock

        from stock_data.api.routes import agent as agent_module

        mock_manager = MagicMock()
        mock_manager.get_morning_briefing.return_value = (None, "")
        mock_manager.get_market_recap.return_value = (None, "")
        mock_manager.get_flash_news.return_value = ([], "eastmoney")
        mock_manager.get_zt_pool.return_value = ([], "akshare", None)
        mock_manager.get_daily_dragon_tiger.return_value = ({"stocks": []}, "zzshare")
        monkeypatch.setattr(agent_module, "get_manager", lambda: mock_manager)

        client.get("/api/v1/agent/market-context?flash_limit=20&trade_date=2026-07-25")
        # First call: 1 morning + 1 recap + 1 flash + 1 zt + 1 dt + 1 dtiger = 6
        assert mock_manager.get_morning_briefing.call_count == 1
        client.get("/api/v1/agent/market-context?flash_limit=20&trade_date=2026-07-25")
        # Second call: still 1 (cache hit)
        assert mock_manager.get_morning_briefing.call_count == 1


class TestStocksBatchProfile:
    """POST /agent/stocks/batch-profile — per-code + per-aspect fan-out."""

    def _patch_happy(self, monkeypatch):
        from unittest.mock import MagicMock

        from stock_data.api.routes import agent as agent_module

        mock_manager = MagicMock()
        mock_manager.get_realtime_quote.return_value = _make_unified_quote("600519")
        mock_manager.get_kline_data.return_value = (
            _make_kline_df(
                [
                    {
                        "date": "2026-07-25",
                        "open": 1,
                        "high": 2,
                        "low": 0.5,
                        "close": 1.5,
                        "volume": 100,
                        "amount": 1e6,
                        "pct_chg": 0.1,
                    }
                ]
            ),
            "akshare",
        )
        mock_manager.get_stock_info.return_value = (
            {"code": "600519", "name": "贵州茅台", "industry": "白酒"},
            "zhitu",
        )
        monkeypatch.setattr(agent_module, "get_manager", lambda: mock_manager)
        # boards: persistence layer (stock_board_cache.get_stock_memberships).
        # The route's boards dispatch uses __persistence_stock_memberships__
        # so the manager.get_stock_boards branch is never hit. Patch the
        # persistence entry instead.
        self._boards_patcher = patch(
            _STOCK_MEMBERSHIPS_PATCH,
            return_value=(
                [
                    {
                        "code": "885xxx",
                        "name": "白酒",
                        "type": "concept",
                        "subtype": "",
                        "source": "ths",
                    }
                ],
                [],
                "persistence",
            ),
        )
        self._boards_patcher.start()
        return mock_manager

    def test_happy_path_2_codes_5_aspects(self, client, monkeypatch):
        mock_manager = self._patch_happy(monkeypatch)
        response = client.post(
            "/api/v1/agent/stocks/batch-profile",
            json={"codes": ["600519", "000001"]},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["summary"]["requested"] == 2
        assert data["summary"]["ok"] == 2
        assert len(data["results"]) == 2
        for r in data["results"]:
            assert r["ok"] is True
            # All 5 aspects present (default aspects list)
            for aspect in ("quote", "kline", "kline_5m", "info", "boards"):
                assert aspect in r["data"]
                assert r["errors"] == []
        # Per-aspect call counts: 2 codes × 5 aspects = 10
        assert mock_manager.get_realtime_quote.call_count == 2
        assert mock_manager.get_kline_data.call_count == 4  # 2 codes × 2 kline aspects
        assert mock_manager.get_stock_info.call_count == 2
        # boards goes through persistence; manager.get_stock_boards is NOT called.
        mock_manager.get_stock_boards.assert_not_called()

    def test_per_aspect_failure_isolated(self, client, monkeypatch):
        """One aspect fails on one code; other aspects on same code + other codes still work."""
        from unittest.mock import MagicMock

        from stock_data.api.routes import agent as agent_module
        from stock_data.data_provider.base import DataFetchError

        mock_manager = MagicMock()
        mock_manager.get_realtime_quote.return_value = _make_unified_quote("600519")

        # 600519 kline fails; 000001 kline ok
        def kline_side(code, **_):
            if code == "600519":
                raise DataFetchError("kline down for 600519")
            return (
                _make_kline_df(
                    [
                        {
                            "date": "2026-07-25",
                            "open": 1,
                            "high": 2,
                            "low": 0.5,
                            "close": 1.5,
                            "volume": 100,
                            "amount": 1e6,
                            "pct_chg": 0.1,
                        }
                    ]
                ),
                "akshare",
            )

        mock_manager.get_kline_data.side_effect = kline_side
        mock_manager.get_stock_info.return_value = ({"code": "x", "name": "x"}, "zhitu")
        mock_manager.get_stock_boards.return_value = ([], "ths")
        monkeypatch.setattr(agent_module, "get_manager", lambda: mock_manager)

        response = client.post(
            "/api/v1/agent/stocks/batch-profile",
            json={"codes": ["600519", "000001"]},
        )
        assert response.status_code == 200
        data = response.json()
        by_code = {r["code"]: r for r in data["results"]}
        # 600519: kline + kline_5m failed; quote/info/boards ok
        assert by_code["600519"]["ok"] is True  # at least one aspect succeeded
        err_aspects = {e["aspect"] for e in by_code["600519"]["errors"]}
        assert err_aspects == {"kline", "kline_5m"}
        # 000001: all ok
        assert by_code["000001"]["ok"] is True
        assert by_code["000001"]["errors"] == []
        # 600519's kline absent from data, quote present
        assert "quote" in by_code["600519"]["data"]
        assert "kline" not in by_code["600519"]["data"]
        # 000001's kline present
        assert "kline" in by_code["000001"]["data"]

    def test_codes_over_limit_422(self, client):
        """6 codes (>5 hard cap) → 422 from Pydantic validation."""
        response = client.post(
            "/api/v1/agent/stocks/batch-profile",
            json={"codes": ["600519", "000001", "000002", "000003", "000004", "000005"]},
        )
        assert response.status_code == 422

    def test_codes_empty_422(self, client):
        response = client.post(
            "/api/v1/agent/stocks/batch-profile",
            json={"codes": []},
        )
        assert response.status_code == 422

    def test_subaspect_selection(self, client, monkeypatch):
        """aspects=['quote', 'info'] → only those 2 fetched (not the default 5)."""
        from unittest.mock import MagicMock

        from stock_data.api.routes import agent as agent_module

        mock_manager = MagicMock()
        mock_manager.get_realtime_quote.return_value = _make_unified_quote("600519")
        mock_manager.get_stock_info.return_value = ({"code": "600519", "name": "x"}, "zhitu")
        monkeypatch.setattr(agent_module, "get_manager", lambda: mock_manager)

        response = client.post(
            "/api/v1/agent/stocks/batch-profile",
            json={"codes": ["600519"], "aspects": ["quote", "info"]},
        )
        assert response.status_code == 200
        data = response.json()
        first = data["results"][0]
        assert set(first["data"].keys()) == {"quote", "info"}
        # kline/kline_5m/boards NOT called
        mock_manager.get_kline_data.assert_not_called()
        mock_manager.get_stock_boards.assert_not_called()

    def test_cache_hit_same_codes_and_aspects(self, client, monkeypatch):
        mock_manager = self._patch_happy(monkeypatch)
        payload = {"codes": ["cache_stocks_bp_a", "cache_stocks_bp_b"]}
        r1 = client.post("/api/v1/agent/stocks/batch-profile", json=payload)
        # 2 codes × (1 quote + 2 kline + 1 info + 1 boards) = 10 calls
        assert mock_manager.get_realtime_quote.call_count == 2
        r2 = client.post("/api/v1/agent/stocks/batch-profile", json=payload)
        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r1.json() == r2.json()
        # 2nd request hit cache → counts unchanged
        assert mock_manager.get_realtime_quote.call_count == 2

    def test_different_aspects_use_different_cache_entries(self, client, monkeypatch):
        """Same codes + different aspects → distinct cache entries (both fetched)."""
        from unittest.mock import MagicMock

        from stock_data.api.routes import agent as agent_module

        mock_manager = MagicMock()
        mock_manager.get_realtime_quote.return_value = _make_unified_quote("600519")
        mock_manager.get_kline_data.return_value = (
            _make_kline_df(
                [
                    {
                        "date": "2026-07-25",
                        "open": 1,
                        "high": 2,
                        "low": 0.5,
                        "close": 1.5,
                        "volume": 100,
                        "amount": 1e6,
                        "pct_chg": 0.1,
                    }
                ]
            ),
            "akshare",
        )
        monkeypatch.setattr(agent_module, "get_manager", lambda: mock_manager)

        r1 = client.post(
            "/api/v1/agent/stocks/batch-profile",
            json={"codes": ["diff_aspect_a"], "aspects": ["quote"]},
        )
        # 1 quote call only (aspects=['quote'])
        assert mock_manager.get_realtime_quote.call_count == 1
        assert mock_manager.get_kline_data.call_count == 0
        r2 = client.post(
            "/api/v1/agent/stocks/batch-profile",
            json={"codes": ["diff_aspect_a"], "aspects": ["quote", "kline"]},
        )
        # 2nd request: 1 NEW quote + 1 NEW kline (different cache key)
        assert mock_manager.get_realtime_quote.call_count == 2
        assert mock_manager.get_kline_data.call_count == 1
        assert r1.status_code == 200
        assert r2.status_code == 200


class TestPhase2Manifest:
    """All 3 new Phase 2 endpoints appear in /control/api-manifest under tag=agent."""

    def test_phase2_endpoints_in_manifest(self, client):
        response = client.get("/control/api-manifest")
        assert response.status_code == 200
        manifest = response.json()
        agent_section = next(
            (s for s in manifest.get("sections", []) if s.get("id") == "agent"),
            None,
        )
        assert agent_section is not None
        paths = {ep.get("path") for ep in agent_section.get("endpoints", [])}
        assert "/api/v1/agent/indices/batch-profile" in paths
        assert "/api/v1/agent/market-context" in paths
        assert "/api/v1/agent/stocks/batch-profile" in paths


class TestPhase2DefensiveGuards:
    """Belt-and-suspenders against silent contract drift."""

    def test_format_md_rejected_422(self, client):
        """?format=md is NOT YET supported; must 422, not silently return JSON.

        Covers all 3 endpoints (1 POST + 2 GET) — the POST guard was
        added 2026-07-28 after the reviewer flagged it as a gap.
        """
        r = client.get("/api/v1/agent/indices/batch-profile?format=md")
        assert r.status_code == 422
        r = client.get("/api/v1/agent/market-context?format=md")
        assert r.status_code == 422
        r = client.post("/api/v1/agent/stocks/batch-profile?format=md", json={"codes": ["600519"]})
        assert r.status_code == 422

    def test_format_json_accepted(self, client, monkeypatch):
        """?format=json is the default; should be accepted (200 with mock)."""
        from unittest.mock import MagicMock

        from stock_data.api.routes import agent as agent_module

        mock_manager = MagicMock()
        mock_manager.get_index_realtime_quote.return_value = _make_unified_quote("000001")
        mock_manager.get_kline_data.return_value = (_make_kline_df([]), "akshare")
        monkeypatch.setattr(agent_module, "get_manager", lambda: mock_manager)

        r = client.get("/api/v1/agent/indices/batch-profile?format=json")
        assert r.status_code == 200

    def test_market_context_trade_date_malformed_400(self, client):
        """trade_date=not-a-date must 400, not silently 200 with empty result."""
        r = client.get("/api/v1/agent/market-context?trade_date=not-a-date")
        assert r.status_code == 400

    def test_indices_batch_profile_order_preserved_in_cache(self, client, monkeypatch):
        """Two requests with reordered codes → each returns its OWN order.

        Implementation: cache key is SORTED (collapse equal sets), but
        on hit the cached list is reordered to the input order before
        returning. This keeps both contracts:
        - cache key contract: "sorted for order-perturbation immunity"
        - response contract: "results in input order"
        """
        from unittest.mock import MagicMock

        from stock_data.api.routes import agent as agent_module

        mock_manager = MagicMock()
        mock_manager.get_index_realtime_quote.return_value = _make_unified_quote("000001")
        mock_manager.get_kline_data.return_value = (
            _make_kline_df(
                [
                    {
                        "date": "2026-07-25",
                        "open": 1,
                        "high": 2,
                        "low": 0.5,
                        "close": 1.5,
                        "volume": 100,
                        "amount": 1e6,
                        "pct_chg": 0.1,
                    }
                ]
            ),
            "akshare",
        )
        monkeypatch.setattr(agent_module, "get_manager", lambda: mock_manager)

        r1 = client.get("/api/v1/agent/indices/batch-profile?codes=000001,000300")
        # Second request: reordered; cache key collapses; on hit we
        # reorder cached list back to the new input order.
        r2 = client.get("/api/v1/agent/indices/batch-profile?codes=000300,000001")
        # First request does 2 codes × 3 freqs = 6 kline calls.
        # Second request is a cache hit → 0 extra calls.
        assert mock_manager.get_kline_data.call_count == 6
        # Each response preserves its own request order
        assert [p["code"] for p in r1.json()["indices"]] == ["000001", "000300"]
        assert [p["code"] for p in r2.json()["indices"]] == ["000300", "000001"]

    def test_stocks_batch_profile_aspects_empty_422(self, client):
        """aspects=[] is rejected by Pydantic min_length=1."""
        r = client.post(
            "/api/v1/agent/stocks/batch-profile",
            json={"codes": ["600519"], "aspects": []},
        )
        assert r.status_code == 422

    def test_market_context_pre_market_summary_drops_pool_attempts(self, client, monkeypatch):
        """In pre-market, n_requested drops to 4 (skipping zt+dt attempts).

        Without this fix the summary reported requested=6/failed=2 even
        though pools were intentionally skipped (not failed).
        """
        from unittest.mock import MagicMock

        from stock_data.api.routes import agent as agent_module

        mock_manager = MagicMock()
        mock_manager.get_morning_briefing.return_value = (None, "")
        mock_manager.get_market_recap.return_value = (None, "")
        mock_manager.get_flash_news.return_value = ([], "eastmoney")
        mock_manager.get_zt_pool.return_value = ([], "akshare", None)
        mock_manager.get_daily_dragon_tiger.return_value = ({"stocks": []}, "zzshare")
        monkeypatch.setattr(agent_module, "get_manager", lambda: mock_manager)
        monkeypatch.setattr(
            agent_module,
            "_classify_market_session",
            lambda _d, _t: "pre-market",
        )

        r = client.get("/api/v1/agent/market-context?flash_limit=20&trade_date=2026-07-25")
        assert r.status_code == 200
        data = r.json()
        # 4 attempted (briefing + recap + flash + dtiger); 2 skipped (zt + dt)
        assert data["summary"]["requested"] == 4
        # Pools NOT attempted in pre-market
        mock_manager.get_zt_pool.assert_not_called()

    def test_market_context_cache_key_includes_session(self, client, monkeypatch):
        """Same (flash_limit, trade_date) but different session → different cache entries."""
        from unittest.mock import MagicMock

        from stock_data.api.routes import agent as agent_module

        mock_manager = MagicMock()
        mock_manager.get_morning_briefing.return_value = (None, "")
        mock_manager.get_market_recap.return_value = (None, "")
        mock_manager.get_flash_news.return_value = ([], "eastmoney")
        mock_manager.get_zt_pool.return_value = ([], "akshare", None)
        mock_manager.get_daily_dragon_tiger.return_value = ({"stocks": []}, "zzshare")
        monkeypatch.setattr(agent_module, "get_manager", lambda: mock_manager)

        # First call: pre-market
        monkeypatch.setattr(agent_module, "_classify_market_session", lambda *_: "pre-market")
        client.get("/api/v1/agent/market-context?flash_limit=20&trade_date=2026-07-25")
        # Second call: post-market — same flash_limit + date, different session
        monkeypatch.setattr(agent_module, "_classify_market_session", lambda *_: "post-market")
        client.get("/api/v1/agent/market-context?flash_limit=20&trade_date=2026-07-25")
        # Without session in cache key, the 2nd request would hit cache and
        # call counts would stay flat. With it, both calls execute fresh.
        assert mock_manager.get_morning_briefing.call_count == 2

    def test_quote_none_counted_as_failure(self, client, monkeypatch):
        """If get_index_realtime_quote returns None (no fetcher could serve),
        it's reported as a failure, not a successful empty quote.
        """
        from unittest.mock import MagicMock

        from stock_data.api.routes import agent as agent_module

        mock_manager = MagicMock()
        mock_manager.get_index_realtime_quote.return_value = None
        mock_manager.get_kline_data.return_value = (
            _make_kline_df(
                [
                    {
                        "date": "2026-07-25",
                        "open": 1,
                        "high": 2,
                        "low": 0.5,
                        "close": 1.5,
                        "volume": 100,
                        "amount": 1e6,
                        "pct_chg": 0.1,
                    }
                ]
            ),
            "akshare",
        )
        monkeypatch.setattr(agent_module, "get_manager", lambda: mock_manager)

        r = client.get("/api/v1/agent/indices/batch-profile?codes=000001")
        assert r.status_code == 200
        data = r.json()
        first = data["indices"][0]
        # quote=None should mark the entry as failed
        assert first["quote"] is None
        assert first["errors"]["quote"] is not None
        assert data["summary"]["ok"] == 0
        assert data["summary"]["failed"] == 1

    def test_stocks_batch_profile_kline_passes_asset_stock(self, client, monkeypatch):
        """The kline aspect MUST pass asset='stock' explicitly so 000001
        (which is also a CSI index) is routed to STOCK_KLINE, not INDEX_KLINE.
        """
        from unittest.mock import MagicMock

        from stock_data.api.routes import agent as agent_module

        mock_manager = MagicMock()
        mock_manager.get_realtime_quote.return_value = _make_unified_quote("000001")
        mock_manager.get_kline_data.return_value = (
            _make_kline_df(
                [
                    {
                        "date": "2026-07-25",
                        "open": 1,
                        "high": 2,
                        "low": 0.5,
                        "close": 1.5,
                        "volume": 100,
                        "amount": 1e6,
                        "pct_chg": 0.1,
                    }
                ]
            ),
            "akshare",
        )
        mock_manager.get_stock_info.return_value = ({"code": "000001", "name": "平安银行"}, "zhitu")
        monkeypatch.setattr(agent_module, "get_manager", lambda: mock_manager)
        with patch(_STOCK_MEMBERSHIPS_PATCH, return_value=([], [], "persistence")):
            r = client.post(
                "/api/v1/agent/stocks/batch-profile",
                json={"codes": ["000001"], "aspects": ["kline", "kline_5m"]},
            )
        assert r.status_code == 200
        # Both kline calls must have asset="stock"
        assert mock_manager.get_kline_data.call_count == 2
        for call in mock_manager.get_kline_data.call_args_list:
            assert call.kwargs.get("asset") == "stock", f"missing asset='stock' in {call}"

    def test_stocks_batch_profile_boards_uses_persistence_not_manager(self, client, monkeypatch):
        """The boards aspect MUST go through stock_board_cache.get_stock_memberships,
        not manager.get_stock_boards (CLAUDE.md "Persistence-Only Routing").
        """
        from unittest.mock import MagicMock

        from stock_data.api.routes import agent as agent_module

        mock_manager = MagicMock()
        mock_manager.get_realtime_quote.return_value = _make_unified_quote("600519")
        monkeypatch.setattr(agent_module, "get_manager", lambda: mock_manager)
        with patch(_STOCK_MEMBERSHIPS_PATCH) as mock_sm:
            mock_sm.return_value = (
                [
                    {
                        "code": "885xxx",
                        "name": "白酒",
                        "type": "concept",
                        "subtype": "",
                        "source": "ths",
                    }
                ],
                [],
                "persistence",
            )
            r = client.post(
                "/api/v1/agent/stocks/batch-profile",
                json={"codes": ["600519"], "aspects": ["boards"]},
            )
            assert r.status_code == 200
            # Persistence layer called once
            assert mock_sm.call_count == 1
            # Manager route NOT taken
            mock_manager.get_stock_boards.assert_not_called()
            # Response carries the entries
            data = r.json()
            assert data["results"][0]["data"]["boards"]["data"] == [
                {
                    "code": "885xxx",
                    "name": "白酒",
                    "type": "concept",
                    "subtype": "",
                    "source": "ths",
                }
            ]
