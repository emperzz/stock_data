"""Unit tests for fetch_board_stocks_with_zzshare_fallback's F10 leg (Phase 3).

Added 2026-07-20 per spec ``2026-07-20-ths-board-f10-extension-design.md`` §3.5.1.
The helper now has THREE legs in this order for ``source='ths'+include_quote=False``:
  Leg 1 (NEW): THS F10 page — 90+ members, quote=None
  Leg 2 (existing): ZZSHARE primary — ~50 bare codes
  Leg 3 (existing): THS AJAX fallback — capped at 50 with quote

``include_quote=True`` continues to use THS AJAX only (F10 doesn't carry
realtime quote — it would be silent data degradation to substitute).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from stock_data.data_provider.base import DataFetchError
from stock_data.data_provider.persistence.board import (
    _resolve_ths_cid_from_platecode,
    fetch_board_stocks_with_zzshare_fallback,
)


# Sample fixture rows to mimic the F10 leg's shape — quote-shaped fields
# all None, dict shape matches ``get_board_stocks``'s BoardStockInfo keys.
F10_FULL_ROWS = [
    {
        "stock_code": "600227", "stock_name": "赤天化", "exchange": "sh",
        "price": None, "change_pct": None, "change_amount": None,
        "volume": None, "amount": None, "turnover_rate": None,
    },
    {
        "stock_code": "600744", "stock_name": "华银电力", "exchange": "sh",
        "price": None, "change_pct": None, "change_amount": None,
        "volume": None, "amount": None, "turnover_rate": None,
    },
]


def _patch_cid_resolution(monkeypatch, value: str | None = "301558") -> None:
    """Stub the THS-cid lookup so the legacy THS AJAX branch has a valid cid."""
    monkeypatch.setattr(
        "stock_data.data_provider.persistence.board._resolve_ths_cid_from_platecode",
        lambda code: value,
    )


def test_f10_leg_serves_request_when_nonempty(monkeypatch):
    """F10 returns 90+ rows → used; ZZSHARE / THS AJAX never called."""
    mgr = MagicMock()
    mgr.get_board_stocks_full.return_value = (F10_FULL_ROWS, "ThsFetcher")

    rows, src_label, effective, reason = fetch_board_stocks_with_zzshare_fallback(
        board_code="885914", source="ths", include_quote=False, manager=mgr,
    )

    assert rows == F10_FULL_ROWS
    assert effective == "ths-f10"
    assert reason is None
    assert src_label == "ths"  # user-facing source label unchanged
    mgr.get_board_stocks_full.assert_called_once_with(
        board_code="885914", source="ths"
    )
    # F10 served — neither ZZSHARE nor THS AJAX fired.
    mgr.get_board_stocks.assert_not_called()


def test_f10_datafetcherror_falls_back_to_zzshare(monkeypatch):
    """F10 raises DataFetchError → fall back to ZZSHARE primary leg."""
    mgr = MagicMock()
    mgr.get_board_stocks_full.side_effect = DataFetchError("F10 401")
    mgr.get_board_stocks.return_value = (
        [{"stock_code": "000001", "stock_name": "平安银行"}],
        "ZzshareFetcher",
    )

    rows, src_label, effective, _ = fetch_board_stocks_with_zzshare_fallback(
        board_code="885914", source="ths", include_quote=False, manager=mgr,
    )

    assert rows == [{"stock_code": "000001", "stock_name": "平安银行"}]
    assert effective == "zzshare"
    mgr.get_board_stocks_full.assert_called_once()
    mgr.get_board_stocks.assert_called_once()
    args, kwargs = mgr.get_board_stocks.call_args
    assert kwargs.get("source") == "zzshare"
    assert kwargs.get("include_quote") is False


def test_f10_empty_falls_back_to_zzshare(monkeypatch):
    """F10 returns [] → fall back to ZZSHARE primary leg."""
    mgr = MagicMock()
    mgr.get_board_stocks_full.return_value = ([], "ThsFetcher")
    mgr.get_board_stocks.return_value = (
        [{"stock_code": "000002"}], "ZzshareFetcher",
    )

    rows, _src, effective, _ = fetch_board_stocks_with_zzshare_fallback(
        board_code="885914", source="ths", include_quote=False, manager=mgr,
    )
    assert effective == "zzshare"
    mgr.get_board_stocks.assert_called_once()


def test_f10_fails_and_zzshare_fails_falls_to_ths_ajax(monkeypatch):
    """F10 + ZZSHARE both fail → THS AJAX fallback fires (cid resolved)."""
    _patch_cid_resolution(monkeypatch, "301558")

    mgr = MagicMock()
    mgr.get_board_stocks_full.side_effect = DataFetchError("F10 fail")
    # Two get_board_stocks calls: (a) zzshare primary fails,
    # (b) THS AJAX fallback succeeds.
    mgr.get_board_stocks.side_effect = [
        DataFetchError("zzshare fail"),
        ([{"stock_code": "600001", "price": 1.0}], "ThsFetcher"),
    ]

    rows, _src, effective, _ = fetch_board_stocks_with_zzshare_fallback(
        board_code="885914", source="ths", include_quote=False, manager=mgr,
    )

    assert rows == [{"stock_code": "600001", "price": 1.0}]
    assert effective == "ths"
    assert mgr.get_board_stocks.call_count == 2


def test_include_quote_true_skips_f10_leg(monkeypatch):
    """include_quote=True → F10 leg is NOT called (existing THS AJAX only)."""
    _patch_cid_resolution(monkeypatch, "301558")
    mgr = MagicMock()
    mgr.get_board_stocks.return_value = (
        [{"stock_code": "600001", "price": 1.0}], "ThsFetcher",
    )

    rows, _src, effective, _ = fetch_board_stocks_with_zzshare_fallback(
        board_code="885914", source="ths", include_quote=True, manager=mgr,
    )
    assert effective == "ths"
    mgr.get_board_stocks_full.assert_not_called()
    mgr.get_board_stocks.assert_called_once()


def test_zzshare_serves_when_f10_returns_empty(monkeypatch):
    """Edge: F10 returns [] AND ZZSHARE returns rows → effective='zzshare'."""
    mgr = MagicMock()
    mgr.get_board_stocks_full.return_value = ([], "ThsFetcher")
    mgr.get_board_stocks.return_value = (
        [{"stock_code": "000004"}], "ZzshareFetcher",
    )

    rows, _src, effective, _ = fetch_board_stocks_with_zzshare_fallback(
        board_code="885914", source="ths", include_quote=False, manager=mgr,
    )
    assert effective == "zzshare"
    assert len(rows) == 1
