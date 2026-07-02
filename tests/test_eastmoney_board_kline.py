"""Offline parser tests for EastMoneyFetcher board K-line.

Pure parser tests (no HTTP) — validate the `_parse_board_kline` static method
and the `_board_secid` normalizer.
"""

from stock_data.data_provider.fetchers.eastmoney.fetcher import EastMoneyFetcher


class TestBoardSecid:
    def test_with_bk_prefix(self):
        assert EastMoneyFetcher._board_secid("BK0996") == "90.BK0996"

    def test_without_bk_prefix(self):
        assert EastMoneyFetcher._board_secid("0996") == "90.BK0996"

    def test_lowercase_bk_prefix(self):
        assert EastMoneyFetcher._board_secid("bk0806") == "90.BK0806"

    def test_with_whitespace(self):
        assert EastMoneyFetcher._board_secid("  BK0996  ") == "90.BK0996"

    def test_empty_returns_fallback(self):
        assert EastMoneyFetcher._board_secid("") == "90.BK"


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
        f = EastMoneyFetcher.__new__(EastMoneyFetcher)  # skip __init__
        try:
            f.get_board_history("BK0996", frequency="2m")
        except Exception as e:
            assert "frequency" in str(e).lower() or "2m" in str(e)
        else:
            raise AssertionError("expected DataFetchError on unknown frequency")
