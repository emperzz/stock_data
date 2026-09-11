"""`amount` carries an explicit unit declaration instead of being silently scaled.

D7/B (2026-09-11): the 元→亿元 conversion happens at the zzshare fetcher
boundary, so the whole board-list surface is 亿元 and `amount_unit` is a
declaration rather than a warning.
"""

from __future__ import annotations

import pytest

from stock_data.api.routes import boards as routes_mod


class TestDeclaredUnits:
    def test_ths_board_list_declares_yi(self):
        rows = [
            {
                "board_code": "885333",
                "name": "移动支付",
                "amount": 1738.4,
                "amount_unit": "yi",
                "board_type": "concept",
            }
        ]
        assert routes_mod._to_board_infos(rows)[0].amount_unit == "yi"

    def test_zzshare_board_list_declares_yi(self):
        """The conversion happened upstream of here, so the route simply
        passes through 亿元 + "yi" for every source."""
        rows = [
            {
                "board_code": "801001",
                "name": "芯片",
                "amount": 1030.0,
                "amount_unit": "yi",
                "board_type": "concept",
            }
        ]
        info = routes_mod._to_board_infos(rows)[0]
        assert info.amount == 1030.0
        assert info.amount_unit == "yi"

    def test_missing_unit_is_none_not_defaulted(self):
        """include_quote=false rows carry no amount, so no unit either."""
        rows = [{"board_code": "BK1048", "name": "互联网服务", "board_type": "industry"}]
        assert routes_mod._to_board_infos(rows)[0].amount_unit is None


class TestFetcherBoundaryConversion:
    def test_zzshare_fetcher_converts_trade_money_to_yi(self, monkeypatch):
        """plates_rank emits 元; the fetcher must emit 亿元 (D7/B)."""
        from stock_data.data_provider.fetchers.zzshare_fetcher import ZzshareFetcher

        f = ZzshareFetcher()
        monkeypatch.setattr(f, "_ensure_api", lambda: None)
        monkeypatch.setattr(
            ZzshareFetcher,
            "_api",
            type(
                "A",
                (),
                {
                    "plates_rank": lambda self, **kw: [
                        {
                            "plate_code": "801001",
                            "plate_name": "芯片",
                            "trade_money": 1.03e11,
                            "rate": 1.0,
                            "market_cap_cir": 5.0e12,
                        }
                    ]
                },
            )(),
        )
        with monkeypatch.context() as m:
            m.setattr(
                "stock_data.data_provider.fetchers.zzshare_fetcher."
                "get_latest_trade_date_on_or_before",
                lambda d: d,
            )
            rows = f.get_all_boards(board_type="concept", include_quote=True)
        assert rows
        assert rows[0]["amount"] == pytest.approx(1030.0)  # 1.03e11 元 → 亿元
        assert rows[0]["amount_unit"] == "yi"

    def test_zzshare_no_quote_has_no_unit(self, monkeypatch):
        """No amount → no unit. `None` is more honest than defaulting to 'yi'."""
        from stock_data.data_provider.fetchers.zzshare_fetcher import ZzshareFetcher

        f = ZzshareFetcher()
        monkeypatch.setattr(f, "_ensure_api", lambda: None)
        monkeypatch.setattr(
            ZzshareFetcher,
            "_api",
            type(
                "A",
                (),
                {
                    "plates_rank": lambda self, **kw: [
                        {"plate_code": "801001", "plate_name": "芯片", "trade_money": 1.0e11}
                    ]
                },
            )(),
        )
        with monkeypatch.context() as m:
            m.setattr(
                "stock_data.data_provider.fetchers.zzshare_fetcher."
                "get_latest_trade_date_on_or_before",
                lambda d: d,
            )
            rows = f.get_all_boards(board_type="concept", include_quote=False)
        assert rows
        assert "amount_unit" not in rows[0]
