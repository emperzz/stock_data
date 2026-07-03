"""Offline parser tests for EastMoneyFetcher board K-line.

Pure parser / secid-normalizer tests (no HTTP) plus lmt-computation
tests with HTTP stubbed via _session.get.
"""

from unittest.mock import MagicMock

import pytest

from stock_data.data_provider.fetchers.eastmoney.fetcher import EastMoneyFetcher


def _make_fetcher():
    """Skip cffi session init via __new__; tests attach a stubbed _session."""
    return EastMoneyFetcher.__new__(EastMoneyFetcher)


def _stub_session(f, klines: list[str]) -> dict:
    """Attach a stubbed _session that returns the given klines list, capture params."""
    captured: dict = {}

    def fake_get(url, params=None, **_kw):
        captured["url"] = url
        captured["params"] = dict(params or {})
        r = MagicMock()
        r.json.return_value = {"data": {"klines": klines}}
        return r

    f._session = MagicMock()
    f._session.get = fake_get
    return captured


class TestBoardSecid:
    def test_with_bk_prefix(self):
        assert EastMoneyFetcher._board_secid("BK0996") == "90.BK0996"

    def test_without_bk_prefix(self):
        assert EastMoneyFetcher._board_secid("0996") == "90.BK0996"

    def test_lowercase_bk_prefix(self):
        assert EastMoneyFetcher._board_secid("bk0806") == "90.BK0806"

    def test_with_whitespace(self):
        assert EastMoneyFetcher._board_secid("  BK0996  ") == "90.BK0996"

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="required"):
            EastMoneyFetcher._board_secid("")

    def test_whitespace_only_raises(self):
        with pytest.raises(ValueError, match="required"):
            EastMoneyFetcher._board_secid("   ")

    def test_bk_only_raises(self):
        with pytest.raises(ValueError, match="digits after BK prefix"):
            EastMoneyFetcher._board_secid("BK")

    def test_bk_with_letters_raises(self):
        with pytest.raises(ValueError, match="expected digits after BK"):
            EastMoneyFetcher._board_secid("BK0A01")

    def test_garbage_raises(self):
        with pytest.raises(ValueError, match="not in BK####"):
            EastMoneyFetcher._board_secid("not-a-code")


class TestParseBoardKline:
    def test_full_row(self):
        raw = "2025-06-30,1234.5,1260.0,1220.3,1255.7,12345678,1.234e10,2.5,1.7,21.2,1.5,0"
        out = EastMoneyFetcher._parse_board_kline(raw)
        assert out == {
            "date": "2025-06-30",
            "open": 1234.5,
            "high": 1260.0,
            "low": 1220.3,
            "close": 1255.7,
            "volume": 12345678,
            "amount": 1.234e10,
            "amplitude": 2.5,
            "pct_chg": 1.7,
            "change_amount": 21.2,
            "turnover_rate": 1.5,
        }

    def test_too_few_fields_returns_none(self):
        assert EastMoneyFetcher._parse_board_kline("2025-06-30,100,101") is None

    def test_garbage_returns_none(self):
        assert EastMoneyFetcher._parse_board_kline("not-a-kline") is None

    def test_empty_returns_none(self):
        assert EastMoneyFetcher._parse_board_kline("") is None

    def test_extra_trailing_fields_ignored(self):
        # Upstream sometimes appends extras; we only consume the first 11.
        raw = "2025-06-30,1,2,3,4,5,6,7,8,9,10,extra1,extra2"
        out = EastMoneyFetcher._parse_board_kline(raw)
        assert out is not None and out["close"] == 4.0


class TestGetBoardHistoryUnsupportedFreq:
    def test_unknown_frequency_raises(self):
        f = _make_fetcher()
        with pytest.raises((ValueError, Exception), match="frequency"):
            f.get_board_history("BK0996", frequency="2m")


class TestGetBoardHistoryLmt:
    """Effective lmt must respect start_date/end_date range width.

    Regression: previously, lmt = max(1, min(int(days), 800)) ignored the
    date range entirely — `days=30 + start_date=2020-01-01` returned
    only the last 30 bars instead of the 5-year span the user asked for.
    """

    def test_lmt_uses_days_when_no_range(self):
        f = _make_fetcher()
        cap = _stub_session(f, ["2025-06-30,1,2,3,4,5,6,7,8,9,10"])
        f.get_board_history("BK0996", frequency="d", days=60)
        assert cap["params"]["lmt"] == "60"

    def test_lmt_follows_date_range_when_wider_than_days(self):
        f = _make_fetcher()
        cap = _stub_session(f, [])
        # 60-day range, days=30 → range wins
        f.get_board_history(
            "BK0996",
            frequency="d",
            days=30,
            start_date="2025-04-01",
            end_date="2025-05-31",
        )
        # (2025-05-31 - 2025-04-01).days + 1 = 61
        assert cap["params"]["lmt"] == "61"

    def test_lmt_uses_days_when_larger_than_range(self):
        f = _make_fetcher()
        cap = _stub_session(f, [])
        # 30-day range, days=365 → days wins
        f.get_board_history(
            "BK0996",
            frequency="d",
            days=365,
            start_date="2025-06-01",
            end_date="2025-06-30",
        )
        assert cap["params"]["lmt"] == "365"

    def test_lmt_capped_at_800(self):
        f = _make_fetcher()
        cap = _stub_session(f, [])
        # Range alone would be 1827 days; we cap at 800
        f.get_board_history(
            "BK0996",
            frequency="d",
            days=30,
            start_date="2020-01-01",
            end_date="2024-12-31",
        )
        assert cap["params"]["lmt"] == "800"

    def test_days_below_one_raises(self):
        # Route Query(ge=1) prevents this via API; direct callers should
        # also fail fast rather than get a silently-floored 1.
        f = _make_fetcher()
        with pytest.raises(ValueError, match="days must be >= 1"):
            f.get_board_history("BK0996", frequency="d", days=0)

    def test_days_negative_raises(self):
        f = _make_fetcher()
        with pytest.raises(ValueError, match="days must be >= 1"):
            f.get_board_history("BK0996", frequency="d", days=-5)

    def test_days_non_int_raises(self):
        f = _make_fetcher()
        with pytest.raises(ValueError, match="days must be int"):
            f.get_board_history("BK0996", frequency="d", days="thirty")

    def test_only_start_date_uses_days(self):
        # Single bound → still defer to `days`. (We can't compute a range
        # width without an end, and the previous value would feel arbitrary.)
        f = _make_fetcher()
        cap = _stub_session(f, [])
        f.get_board_history(
            "BK0996",
            frequency="d",
            days=90,
            start_date="2025-04-01",
        )
        assert cap["params"]["lmt"] == "90"

    def test_only_end_date_uses_days(self):
        f = _make_fetcher()
        cap = _stub_session(f, [])
        f.get_board_history(
            "BK0996",
            frequency="d",
            days=90,
            end_date="2025-05-31",
        )
        assert cap["params"]["lmt"] == "90"

    def test_malformed_start_date_raises(self):
        f = _make_fetcher()
        with pytest.raises(ValueError, match="invalid date format"):
            f.get_board_history(
                "BK0996",
                frequency="d",
                days=30,
                start_date="not-a-date",
                end_date="2025-06-30",
            )

    def test_malformed_end_date_raises(self):
        f = _make_fetcher()
        with pytest.raises(ValueError, match="invalid date format"):
            f.get_board_history(
                "BK0996",
                frequency="d",
                days=30,
                start_date="2025-06-30",
                end_date="also-not-a-date",
            )

    def test_reversed_dates_raises(self):
        # end_date < start_date → invalid range; route should 400.
        f = _make_fetcher()
        with pytest.raises(ValueError, match="end_date"):
            f.get_board_history(
                "BK0996",
                frequency="d",
                days=30,
                start_date="2025-06-30",
                end_date="2020-01-01",
            )

    def test_same_start_and_end_uses_days(self):
        # end_date == start_date → range_days == 1 (inclusive); valid query.
        f = _make_fetcher()
        cap = _stub_session(f, [])
        f.get_board_history(
            "BK0996",
            frequency="d",
            days=10,
            start_date="2025-06-30",
            end_date="2025-06-30",
        )
        assert cap["params"]["lmt"] == "10"  # days wins (10 > 1)

    def test_empty_string_dates_treated_as_no_range(self):
        # FastAPI's Query(None) accepts `?start_date=` as empty string;
        # treat empty/whitespace as "no range constraint", fall back to
        # `days` rather than silently producing days-only lmt.
        f = _make_fetcher()
        cap = _stub_session(f, [])
        f.get_board_history(
            "BK0996",
            frequency="d",
            days=45,
            start_date="",
            end_date="",
        )
        assert cap["params"]["lmt"] == "45"


class TestBoardHistoryRangeDays:
    """Unit tests for the _board_history_range_days helper itself."""

    def test_no_bounds_returns_zero(self):
        assert EastMoneyFetcher._board_history_range_days(None, None) == 0

    def test_empty_strings_return_zero(self):
        assert EastMoneyFetcher._board_history_range_days("", "") == 0
        assert EastMoneyFetcher._board_history_range_days("   ", "   ") == 0

    def test_one_bound_returns_zero(self):
        # Range width needs both ends; one alone = no constraint.
        assert EastMoneyFetcher._board_history_range_days("2025-06-30", "") == 0
        assert EastMoneyFetcher._board_history_range_days("", "2025-06-30") == 0

    def test_same_day_is_one(self):
        assert EastMoneyFetcher._board_history_range_days("2025-06-30", "2025-06-30") == 1

    def test_one_year_span(self):
        # 2024 is leap year: 366 days inclusive.
        assert EastMoneyFetcher._board_history_range_days("2024-01-01", "2024-12-31") == 366

    def test_reversed_raises(self):
        with pytest.raises(ValueError, match="end_date .* < start_date"):
            EastMoneyFetcher._board_history_range_days("2025-06-30", "2025-01-01")

    def test_malformed_raises(self):
        with pytest.raises(ValueError, match="invalid date format"):
            EastMoneyFetcher._board_history_range_days("2025/06/30", "2025-07-01")
        with pytest.raises(ValueError, match="invalid date format"):
            EastMoneyFetcher._board_history_range_days("2025-06-30", "June 30 2025")


class TestGetBoardHistorySecidIntegration:
    """get_board_history surfaces _board_secid's ValueError → routed to 400."""

    def test_bad_board_code_raises(self):
        f = _make_fetcher()
        with pytest.raises(ValueError, match="board_code"):
            f.get_board_history("", frequency="d", days=30)

    def test_bk_only_raises(self):
        f = _make_fetcher()
        with pytest.raises(ValueError, match="digits after BK prefix"):
            f.get_board_history("BK", frequency="d", days=30)

    def test_garbage_raises(self):
        f = _make_fetcher()
        with pytest.raises(ValueError, match="not in BK####"):
            f.get_board_history("foobar", frequency="d", days=30)
