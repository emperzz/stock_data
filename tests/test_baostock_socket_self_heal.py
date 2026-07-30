"""
Tests for BaostockFetcher socket self-healing.

Background: baostock holds a process-global ``default_socket`` that is
created once on ``bs.login()`` and reused forever. After the server-side
peer drops the connection (idle timeout / nightly maintenance), every
subsequent ``bs.query_history_k_data_plus`` returns BSERR_RECVSOCK_FAIL
("10002007") / error_msg "网络接收错误。" even though individual
fresh-process calls still work.

These tests pin the contract that the fetcher self-heals on the FIRST
occurrence of this specific failure by:
  1. wiping the dead ``default_socket``,
  2. opening a new one via ``SocketUtil().connect()``,
  3. retrying the upstream call once.

If the retry also fails, the fetcher raises ``DataFetchError`` with the
original error_msg (consistent with manager failover behavior).

Why this matters: when a server process is long-running, the first
``bs`` call after the socket dies is THE expensive one — without
self-heal it permanently 5xx's every subsequent baostock request until
restart. With self-heal, the failed call quietly recovers and continues.

Source: ``stock_data/data_provider/fetchers/baostock_fetcher.py``
"""

from unittest.mock import MagicMock, patch

import pytest

from stock_data.data_provider.base import DataFetchError
from stock_data.data_provider.fetchers.baostock_fetcher import BaostockFetcher


# ──────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────

def _bs_result(error_code: str, error_msg: str = ""):
    rs = MagicMock()
    rs.error_code = error_code
    rs.error_msg = error_msg
    rs.next.return_value = False
    rs.fields = []
    return rs


def _good_bs_result(rows):
    rs = MagicMock()
    rs.error_code = "0"
    rs.error_msg = ""
    rs.fields = ["date", "open", "high", "low", "close", "volume", "amount", "pctChg"]
    cursor = {"i": 0}

    def nxt():
        return cursor["i"] < len(rows)

    def grow():
        i = cursor["i"]
        cursor["i"] += 1
        return rows[i]

    rs.next.side_effect = nxt
    rs.get_row_data.side_effect = grow
    return rs


def _install_sentinel_default_socket(conx, name="old_sock"):
    """Plant a MagicMock as the live baostock default_socket so we can
    verify the self-heal path replaces it.

    Real baostock is installed in sys.modules as a package, so
    `baostock.common.context` is importable — we use the real one and
    use setattr to register a sentinel.
    """
    sent = MagicMock(name=name)
    setattr(conx, "default_socket", sent)
    return sent


def _enable_fetcher_init():
    """Mark BaostockFetcher._init_ok = True so _fetch_raw_data's
    ``if not BaostockFetcher._init_ok: raise`` check passes.
    """
    BaostockFetcher._init_attempted = True
    BaostockFetcher._init_ok = True


# ──────────────────────────────────────────────────────────────────
# Autouse fixture: state isolation across tests
# ──────────────────────────────────────────────────────────────────
# BaostockFetcher is a process-global singleton (class-level
# ``_init_attempted`` / ``_init_ok``) and baostock's ``default_socket``
# is a process-global module attribute. Without isolation, a mid-test
# failure leaks state into subsequent tests. The autouse fixture
# snapshots the relevant globals on entry and restores them on exit,
# regardless of test outcome — preventing cascade failures from
# masking the real assertion in a later test.
@pytest.fixture(autouse=True)
def _isolate_baostock_globals(request):
    from unittest.mock import MagicMock as _MM

    # Snapshot original state
    orig_init_attempted = BaostockFetcher._init_attempted
    orig_init_ok = BaostockFetcher._init_ok

    # Snapshot default_socket (may not exist as an attr at all if
    # baostock was never used in this process)
    orig_socket = None
    had_socket_attr = False
    try:
        import baostock.common.context as _conx
        had_socket_attr = hasattr(_conx, "default_socket")
        if had_socket_attr:
            orig_socket = getattr(_conx, "default_socket")
            delattr(_conx, "default_socket")
    except Exception:
        pass

    yield

    # Restore
    BaostockFetcher._init_attempted = orig_init_attempted
    BaostockFetcher._init_ok = orig_init_ok

    try:
        import baostock.common.context as _conx
        if had_socket_attr and orig_socket is not None:
            setattr(_conx, "default_socket", orig_socket)
        elif had_socket_attr and hasattr(_conx, "default_socket"):
            delattr(_conx, "default_socket")
    except Exception:
        pass


# ──────────────────────────────────────────────────────────────────
# Test 1: 网络接收错误 + retry + 第二次成功 → 不抛错
# ──────────────────────────────────────────────────────────────────
def test_self_heal_recovers_on_second_attempt():
    """BSERR_RECVSOCK_FAIL on the first bs.query_*, then a successful
    result on the second. The fetcher should NOT raise — it should
    silently rebuild the socket between attempts and return a populated
    DataFrame.

    This pins: the fetcher makes the upstream call TWICE in this scenario,
    which is the observable contract of the self-heal retry.
    """
    import baostock.common.context as conx
    _enable_fetcher_init()
    old_sock = _install_sentinel_default_socket(conx)

    call_count = {"n": 0}

    def side_effect(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return _bs_result("10002007", "网络接收错误。")
        return _good_bs_result([
            ["2026-07-30", "10.0", "11.0", "9.5", "10.5",
             "1000", "10000", "0.0"],
        ])

    fetcher = BaostockFetcher()

    with patch("baostock.query_history_k_data_plus", side_effect=side_effect), \
         patch(
             "baostock.util.socketutil.SocketUtil.connect",
             side_effect=lambda *a, **kw: setattr(
                 conx, "default_socket", MagicMock(name="new_sock")
             ),
         ) as mock_connect:
        df = fetcher.get_kline_data(
            "000001", days=1, frequency="d", asset="stock"
        )

    assert not df.empty, "Expected non-empty DataFrame after self-heal"
    assert call_count["n"] == 2, (
        f"Expected 2 bs.query calls (1 fail + 1 retry), got {call_count['n']}"
    )
    assert mock_connect.call_count >= 1, (
        "Expected SocketUtil.connect to be invoked at least once during self-heal"
    )
    assert getattr(conx, "default_socket") is not old_sock, (
        "Expected default_socket to be replaced post-self-heal"
    )

    # _init / default_socket restoration is handled by the autouse
    # ``_isolate_baostock_globals`` fixture above.


# ──────────────────────────────────────────────────────────────────
# Test 2: 两次都 BSERR_RECVSOCK_FAIL → 仍然抛 DataFetchError（不无限循环）
# ──────────────────────────────────────────────────────────────────
def test_self_heal_does_not_loop_when_both_attempts_fail():
    """If both the original call AND the retry after self-heal return
    BSERR_RECVSOCK_FAIL, the fetcher MUST raise DataFetchError — it must
    NOT loop forever. ``call_count == 2`` pins the "exactly one retry"
    contract.
    """
    import baostock.common.context as conx
    _enable_fetcher_init()
    _install_sentinel_default_socket(conx)

    fetcher = BaostockFetcher()

    with patch(
        "baostock.query_history_k_data_plus",
        side_effect=lambda *a, **kw: _bs_result("10002007", "网络接收错误。"),
    ) as mock_query, \
         patch(
             "baostock.util.socketutil.SocketUtil.connect",
             side_effect=lambda *a, **kw: setattr(
                 conx, "default_socket", MagicMock(name="new_sock")
             ),
         ):
        with pytest.raises(DataFetchError) as exc_info:
            fetcher.get_kline_data("000001", days=1, frequency="d", asset="stock")

    msg = exc_info.value.args[0] if exc_info.value.args else ""
    if isinstance(msg, bytes):
        msg = msg.decode("utf-8", errors="replace")
    assert "网络接收错误" in msg
    assert mock_query.call_count == 2, (
        "Expected exactly 2 bs.query calls (1 original + 1 retry), "
        f"got {mock_query.call_count}"
    )

    # _init / default_socket restoration handled by autouse fixture.


# ──────────────────────────────────────────────────────────────────
# Test 3: 健康路径不受影响（非 网络接收错误 时不进入 retry 分支）
# ──────────────────────────────────────────────────────────────────
def test_no_retry_on_unrelated_error_msg():
    """If the upstream returns a non-socket error (e.g. rate-limited),
    the fetcher MUST NOT trigger self-heal. Only the
    '网络接收错误' / 'BSERR_RECVSOCK_FAIL' signature triggers retry.

    Pins: error_msg == '访问頻率超限' → call_count == 1, raises.
    """
    _enable_fetcher_init()
    fetcher = BaostockFetcher()

    with patch(
        "baostock.query_history_k_data_plus",
        side_effect=lambda *a, **kw: _bs_result(
            "10002011", "访问频次超限，请稍后再试"
        ),
    ), \
         patch("baostock.util.socketutil.SocketUtil.connect") as mock_connect:
        with pytest.raises(DataFetchError):
            fetcher.get_kline_data("000001", days=1, frequency="d", asset="stock")

    assert mock_connect.call_count == 0, (
        "SocketUtil.connect must NOT be called for non-socket errors"
    )

    # _init / default_socket restoration handled by autouse fixture.
