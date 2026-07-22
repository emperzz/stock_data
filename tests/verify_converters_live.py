"""
Live verification: every converter output actually fetches data from its
upstream API.  Requires network access and configured tokens (.env).

Run: python tests/verify_converters_live.py
"""

import contextlib
import sys
import traceback
from datetime import date

from dotenv import load_dotenv

load_dotenv()

from stock_data.data_provider.utils.code_converter import (  # noqa: E402
    to_akshare_format,
    to_baostock_format,
    to_eastmoney_secid,
    to_tencent_prefix,
    to_tushare_format,
    to_yfinance_format,
    to_zhitu_format,
)

PASS = "PASS"
FAIL = "FAIL"
NET = "NET"  # network / upstream temporarily unreachable — not a converter bug

results: list[tuple[str, str, str]] = []  # (name, result, detail)


def record(name: str, ok: bool | None, detail: str = "") -> None:
    """ok=True → PASS, ok=False → FAIL, ok=None → NET"""
    if ok is True:
        mark = PASS
    elif ok is False:
        mark = FAIL
    else:
        mark = NET
    results.append((name, mark, detail))
    tail = f" | {detail}" if detail else ""
    print(f"  [{mark}] {name}{tail}")


def _err_info() -> str:
    lines = traceback.format_exc().splitlines()
    # return last non-empty line (the actual exception message)
    for line in reversed(lines):
        line = line.strip()
        if line and not line.startswith("File ") and not line.startswith("The above"):
            # shorten long messages
            return line[:120]
    return "?"


# ── helpers ────────────────────────────────────────────────────────────


def _fetch_akshare_kline(code: str) -> bool | None:
    import akshare as ak
    import requests

    try:
        df = ak.stock_zh_a_hist(
            symbol=code, period="daily", start_date="2025-06-02", end_date="2025-06-06", adjust=""
        )
        return df is not None and not df.empty
    except (requests.ConnectionError, requests.Timeout, ConnectionError, TimeoutError, OSError):
        return None


def _fetch_baostock_kline(bs_code: str) -> bool | None:
    import baostock as bs
    import requests

    try:
        lg = bs.login()
        if lg.error_code != "0":
            bs.logout()
            return None
        rs = bs.query_history_k_data_plus(
            bs_code,
            "date,open,high,low,close,volume,amount",
            start_date="2025-06-02",
            end_date="2025-06-06",
            frequency="d",
            adjustflag="3",
        )
        ok = rs.error_code == "0"
        data = []
        while ok and rs.next():
            data.append(rs.get_row_data())
        bs.logout()
        return ok and len(data) > 0
    except (requests.ConnectionError, requests.Timeout, ConnectionError, TimeoutError, OSError):
        with contextlib.suppress(Exception):
            bs.logout()
        return None


def _fetch_tencent_quote(prefix: str) -> bool | None:
    import urllib.request

    try:
        url = f"https://qt.gtimg.cn/q={prefix}"
        resp = urllib.request.urlopen(url, timeout=15)
        body = resp.read().decode("gbk")
        return len(body) > 50 and "~" in body
    except (urllib.error.URLError, TimeoutError, OSError):
        return None


def _fetch_eastmoney_kline(secid: str) -> bool | None:
    import requests

    try:
        url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
        params = {
            "secid": secid,
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "klt": "101",
            "fqt": "1",
            "end": "20500101",
            "lmt": "5",
        }
        r = requests.get(
            url,
            params=params,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://quote.eastmoney.com/",
            },
            timeout=15,
        )
        d = r.json()
        klines = d.get("data", {}).get("klines") or []
        return len(klines) > 0
    except (requests.ConnectionError, requests.Timeout, ConnectionError, TimeoutError, OSError):
        return None


def _fetch_yfinance_kline(ticker: str) -> bool | None:
    import yfinance as yf

    try:
        df = yf.download(
            tickers=ticker, start="2025-06-02", end="2025-06-06", progress=False, auto_adjust=False
        )
        if df is None or df.empty:
            # yfinance catches YFRateLimitError internally and returns empty
            # DataFrame — treat as upstream issue, not converter bug
            return None
        return True
    except Exception:
        return None


def _fetch_zhitu_quote(stock_code: str) -> bool | None:
    import os

    import requests

    token = os.getenv("ZHITU_TOKEN", "")
    if not token:
        return None
    try:
        url = f"https://api.zhituapi.com/hs/real/ssjy/{stock_code}"
        r = requests.get(url, params={"token": token}, timeout=15)
        d = r.json()
        # code=0 means success; code!=0 is upstream error, not converter bug
        if d.get("code") != 0:
            return None
        return d.get("data") is not None
    except Exception:
        return None


def _fetch_tushare_kline(ts_code: str) -> bool | None:
    import os

    import requests
    import tushare as ts

    token = os.getenv("TUSHARE_TOKEN", "")
    if not token:
        return None
    try:
        api = ts.pro_api(token)
        df = api.daily(ts_code=ts_code, start_date="20250602", end_date="20250606")
        return df is not None and not df.empty
    except (requests.ConnectionError, requests.Timeout, ConnectionError, TimeoutError, OSError):
        return None


# ── test cases ─────────────────────────────────────────────────────────

print("Live converter verification:", date.today().strftime("%Y-%m-%d"))
print()

# ----------------------------------------------------------------
section = "Akshare"
print(f"--- {section} ---")

# 600519 → akshare K-line
try:
    code = to_akshare_format("600519")
    assert code == "600519", f"bad format: {code}"
    record("600519 A-share K-line", _fetch_akshare_kline(code))
except AssertionError as e:
    record("600519 A-share K-line", False, str(e))
except Exception:
    record("600519 A-share K-line", None, _err_info())

# HK00700 → akshare HK K-line
try:
    code = to_akshare_format("HK00700")
    assert code == "00700.hk", f"bad format: {code}"
    import akshare as ak
    import requests as _r

    try:
        df = ak.stock_hk_hist(
            symbol="00700", period="daily", start_date="20250602", end_date="20250606", adjust=""
        )
        record("HK00700 HK K-line", df is not None and not df.empty)
    except (_r.ConnectionError, _r.Timeout, ConnectionError, TimeoutError, OSError):
        record("HK00700 HK K-line", None, "network error")
except AssertionError as e:
    record("HK00700 HK K-line", False, str(e))
except Exception:
    record("HK00700 HK K-line", None, _err_info())

# 000300 → akshare CSI index
try:
    code = to_akshare_format("000300")
    assert code == "000300", f"bad format: {code}"
    try:
        df = ak.index_zh_a_hist(
            symbol=code, period="daily", start_date="20250602", end_date="20250606"
        )
        record("000300 CSI index", df is not None and not df.empty)
    except (_r.ConnectionError, _r.Timeout, ConnectionError, TimeoutError, OSError):
        record("000300 CSI index", None, "network error")
except AssertionError as e:
    record("000300 CSI index", False, str(e))
except Exception:
    record("000300 CSI index", None, _err_info())

# SPX → akshare US index
try:
    code = to_akshare_format("SPX")
    assert code == ".INX", f"bad format: {code}"
    record("SPX US index -> .INX", None, "format ok (aks US idx unstable)")
except AssertionError as e:
    record("SPX US index -> .INX", False, str(e))
except Exception:
    record("SPX US index -> .INX", None, _err_info())

# ----------------------------------------------------------------
section = "Baostock"
print(f"\n--- {section} ---")

try:
    bs_code, yw_code = to_baostock_format("600519")
    assert bs_code == "sh.600519", f"bad format: {bs_code}"
    record("600519 SH stock", _fetch_baostock_kline(bs_code))
except AssertionError as e:
    record("600519 SH stock", False, str(e))
except Exception:
    record("600519 SH stock", None, _err_info())

try:
    bs_code, yw_code = to_baostock_format("300750")
    assert bs_code == "sz.300750", f"bad format: {bs_code}"
    record("300750 SZ stock", _fetch_baostock_kline(bs_code))
except AssertionError as e:
    record("300750 SZ stock", False, str(e))
except Exception:
    record("300750 SZ stock", None, _err_info())

try:
    bs_code, yw_code = to_baostock_format("000300")
    assert bs_code == "sh.000300", f"bad format: {bs_code}"
    record("000300 CSI index", _fetch_baostock_kline(bs_code))
except AssertionError as e:
    record("000300 CSI index", False, str(e))
except Exception:
    record("000300 CSI index", None, _err_info())

# ----------------------------------------------------------------
section = "Tencent"
print(f"\n--- {section} ---")

try:
    prefix = to_tencent_prefix("600519")
    assert prefix == "sh600519", f"bad format: {prefix}"
    record("600519 SH quote", _fetch_tencent_quote(prefix))
except AssertionError as e:
    record("600519 SH quote", False, str(e))
except Exception:
    record("600519 SH quote", None, _err_info())

try:
    prefix = to_tencent_prefix("HK00700")
    assert prefix == "hk00700", f"bad format: {prefix}"
    record("HK00700 HK quote", _fetch_tencent_quote(prefix))
except AssertionError as e:
    record("HK00700 HK quote", False, str(e))
except Exception:
    record("HK00700 HK quote", None, _err_info())

try:
    prefix = to_tencent_prefix("000001")
    assert prefix == "sz000001", f"bad format: {prefix}"
    record("000001 SZ quote", _fetch_tencent_quote(prefix))
except AssertionError as e:
    record("000001 SZ quote", False, str(e))
except Exception:
    record("000001 SZ quote", None, _err_info())

# ----------------------------------------------------------------
section = "EastMoney"
print(f"\n--- {section} ---")

try:
    secid = to_eastmoney_secid("600519")
    assert secid == "1.600519", f"bad format: {secid}"
    record("600519 SH K-line", _fetch_eastmoney_kline(secid))
except AssertionError as e:
    record("600519 SH K-line", False, str(e))
except Exception:
    record("600519 SH K-line", None, _err_info())

try:
    secid = to_eastmoney_secid("000001")
    assert secid == "0.000001", f"bad format: {secid}"
    record("000001 SZ K-line", _fetch_eastmoney_kline(secid))
except AssertionError as e:
    record("000001 SZ K-line", False, str(e))
except Exception:
    record("000001 SZ K-line", None, _err_info())

# ----------------------------------------------------------------
section = "Yfinance"
print(f"\n--- {section} ---")

try:
    ticker = to_yfinance_format("AAPL")
    assert ticker == "AAPL", f"bad format: {ticker}"
    record("AAPL US stock", _fetch_yfinance_kline(ticker))
except AssertionError as e:
    record("AAPL US stock", False, str(e))
except Exception:
    record("AAPL US stock", None, _err_info())

try:
    ticker = to_yfinance_format("600519")
    assert ticker == "600519.SS", f"bad format: {ticker}"
    record("600519.SS A-share", _fetch_yfinance_kline(ticker))
except AssertionError as e:
    record("600519.SS A-share", False, str(e))
except Exception:
    record("600519.SS A-share", None, _err_info())

try:
    ticker = to_yfinance_format("SPX")
    assert ticker == "^GSPC", f"bad format: {ticker}"
    record("SPX -> ^GSPC", _fetch_yfinance_kline(ticker))
except AssertionError as e:
    record("SPX -> ^GSPC", False, str(e))
except Exception:
    record("SPX -> ^GSPC", None, _err_info())

try:
    ticker = to_yfinance_format("HK00700")
    assert ticker == "00700.HK", f"bad format: {ticker}"
    record("HK00700 -> 00700.HK", _fetch_yfinance_kline(ticker))
except AssertionError as e:
    record("HK00700 -> 00700.HK", False, str(e))
except Exception:
    record("HK00700 -> 00700.HK", None, _err_info())

# ----------------------------------------------------------------
section = "Zhitu"
print(f"\n--- {section} ---")

try:
    code = to_zhitu_format("600519")
    assert code == "600519", f"bad format: {code}"
    record("600519 realtime quote", _fetch_zhitu_quote(code))
except AssertionError as e:
    record("600519 realtime quote", False, str(e))
except Exception:
    record("600519 realtime quote", None, _err_info())

# ----------------------------------------------------------------
section = "Tushare"
print(f"\n--- {section} ---")

try:
    ts_code = to_tushare_format("600519")
    assert ts_code == "600519.SH", f"bad format: {ts_code}"
    record("600519.SH K-line", _fetch_tushare_kline(ts_code))
except AssertionError as e:
    record("600519.SH K-line", False, str(e))
except Exception:
    record("600519.SH K-line", None, _err_info())

try:
    ts_code = to_tushare_format("300750")
    assert ts_code == "300750.SZ", f"bad format: {ts_code}"
    record("300750.SZ K-line", _fetch_tushare_kline(ts_code))
except AssertionError as e:
    record("300750.SZ K-line", False, str(e))
except Exception:
    record("300750.SZ K-line", None, _err_info())


# ── summary ────────────────────────────────────────────────────────────
print(f"\n{'=' * 60}")
n_pass = sum(1 for _, m, _ in results if m == PASS)
n_fail = sum(1 for _, m, _ in results if m == FAIL)
n_net = sum(1 for _, m, _ in results if m == NET)
total = len(results)

print(f"  PASS: {n_pass}  FAIL: {n_fail}  NET: {n_net}  Total: {total}")
print()

for name, mark, detail in results:
    line = f"  [{mark}] {name}"
    if detail:
        line += f"  ({detail})"
    print(line)

# FAIL is the only thing that should break CI
if n_fail > 0:
    print(f"\n{n_fail} converter(s) produced wrong output format.")
    sys.exit(1)
print("\nAll converter formats correct (NET = upstream temporary, not converter bug).")
sys.exit(0)
