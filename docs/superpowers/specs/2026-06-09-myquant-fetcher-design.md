# MyquantFetcher 设计文档

> 日期：2026-06-09
> 状态：已批准（待实现）
> 范围：仅实现 server 已对外暴露且 myquant 免费可用的端点（备份 fetcher）

## 1. 目标与范围

新增 `MyquantFetcher` 作为**备份 fetcher**，与现有 9 个 fetcher 并存，覆盖以下 server 端点：

| Server 端点 | Myquant 入口 | Capability |
|---|---|---|
| `GET /stocks/{code}/quote` | `gm.api.current_price` | `REALTIME_QUOTE` |
| `GET /stocks/{code}/history?period=daily` | `gm.api.history` (1d) | `HISTORICAL_DWM` |
| `GET /stocks/{code}/intraday?period=5/15/30/60` | `gm.api.history` (300s/900s/1800s/3600s) | `HISTORICAL_MIN` |
| `GET /indices/{code}/history?period=daily` | `gm.api.history` (指数代码) | `INDEX_HISTORICAL` |
| `GET /indices/{code}/intraday?period=5/15/30/60` | `gm.api.history` (指数 + minutes) | `INDEX_INTRADAY` |
| `GET /stocks?market=csi` | `gm.api.get_symbols` | `STOCK_LIST` |
| `GET /calendar` | `gm.api.get_trading_dates_by_year` | `TRADE_CALENDAR` |

**不在范围内**：
- `INDEX_QUOTE` — myquant 无专门指数实时函数，`current_price` 字段过单薄
- 周线/月线 — myquant 不支持 `1w`/`1m` 频率
- 1 分钟 K 线 — myquant 最早 60s
- 财务数据 / 指数成分股 / 板块 / 龙虎榜 / 资金流 / 股东 / 分红 / 公告 / 研报 — myquant 付费或 server 暂未对外
- 港股 / 美股 — myquant 仅 A 股

## 2. 文件清单

| 路径 | 动作 |
|---|---|
| `stock_data/data_provider/fetchers/myquant_fetcher.py` | 新建 |
| `stock_data/data_provider/utils/code_converter.py` | 新增 `to_myquant_format()` / `to_myquant_index_format()` |
| `stock_data/data_provider/core/types.py` | 新增 `RealtimeSource.MYQUANT = "myquant"` |
| `stock_data/data_provider/manager.py` | `create_default_manager()` 注册 `MyquantFetcher` |
| `.env.example` | 增加 `MYQUANT_TOKEN=` 块 |
| `pyproject.toml` | `dependencies` 加 `"gm>=3.0.148,<4"` |
| `tests/test_fetcher_structure.py` | 新增 `TestMyquantFetcher` |
| `CLAUDE.md` | 更新 fetcher priority 表 + capability 表 |

## 3. 关键设计决策

### 3.1 优先级

- `priority = int(os.getenv("MYQUANT_PRIORITY", "1"))`
- 紧跟 Tushare(0)，与 Baostock(1) 并列
- Manager 按 priority 升序排序；`create_default_manager()` 列表中 Baostock 在 Myquant 之前实例化，因此**等优先级时 Baostock 先尝试**
- 实际调用链：`Tushare → Baostock → Myquant → Akshare → Yfinance → ...`

### 3.2 频率映射

| Server 频率 | Myquant 频率字符串 | 处理 |
|---|---|---|
| `"d"` | `"1d"` | ✅ |
| `"w"` | — | ❌ `raise DataFetchError` |
| `"m"` | — | ❌ `raise DataFetchError` |
| `"1"` | — | ❌ `raise DataFetchError` |
| `"5"` | `"300s"` | ✅ |
| `"15"` | `"900s"` | ✅ |
| `"30"` | `"1800s"` | ✅ |
| `"60"` | `"3600s"` | ✅ |

不支持的频率在 fetcher 内透明 raise，让 manager 跳到下一家。

### 3.3 复权映射

| Server adjust | Myquant constant |
|---|---|
| `""` / `None` | `ADJUST_NONE` (0) |
| `"qfq"` | `ADJUST_PREV` (1) |
| `"hfq"` | `ADJUST_POST` (2) |

直接传入 myquant 数字常量，不映射为字符串。

### 3.4 标的代码转换

新增两个函数（`stock_data/data_provider/utils/code_converter.py`）：

```python
def to_myquant_format(code: str) -> str:
    """A 股 → myquant 格式。

    600519 → ``SHSE.600519``
    000001 → ``SZSE.000001``
    港股/美股 → 抛 ValueError（myquant 不支持）
    指数 → 抛 ValueError（请用 to_myquant_index_format）
    """
    code = normalize_stock_code(code)
    if is_index_code(code):
        raise ValueError(f"Use to_myquant_index_format for index {code}")
    if is_hk_market(code) or code.isalpha():
        raise ValueError(f"Myquant does not support market {code}")
    if code.startswith(("5", "6", "7", "9")):
        return f"SHSE.{code}"
    if code.startswith(("0", "1", "2", "3", "4", "8")):
        return f"SZSE.{code}"
    raise ValueError(f"Cannot map code {code} to myquant format")


def to_myquant_index_format(code: str) -> str:
    """A 股指数 → myquant 格式。

    000300 → ``SHSE.000300``（沪深 300）
    399006 → ``SZSE.399006``（创业板指）
    非 CSI 指数 → 抛 ValueError
    """
    code = normalize_stock_code(code)
    if not is_index_code(code):
        raise ValueError(f"Not an index code: {code}")
    from ..fetchers.index_symbols import get_index_type
    if get_index_type(code) != "csi":
        raise ValueError(f"Myquant does not support non-CSI index {code}")
    if code.startswith(("0", "3")):
        # SH 000xxx / SZ 399xxx
        if code.startswith("0"):
            return f"SHSE.{code}"
        return f"SZSE.{code}"
    raise ValueError(f"Cannot map index {code} to myquant format")
```

注：CSI 指数前缀简单规则化（`0`→SHSE，`3`→SZSE），与 `to_baostock_format` 中已有规则一致。**未走 `CSI_INDEX_MAP` 显式查表**——myquant 接受任意交易所下 6 位数字指数代码，过度查表反而易漏。

### 3.5 Realtime 字段策略

`gm.api.current_price(symbols)` 仅返回 `{symbol, price, created_at}`。为保持低延迟（避免额外 API 调用），`get_realtime_quote` 采用**极简策略**：

```python
return UnifiedRealtimeQuote(
    code=normalize_stock_code(stock_code),
    price=safe_float(row.get("price")),
    source=RealtimeSource.MYQUANT,
    # 其余字段保持 None
)
```

其他字段（volume / change_pct / open / high / low / pre_close / amount / pe / pb / 市值 / 换手率 / 振幅 / 量比）均为 `None`。Myquant 在 failover 链中**最后兜底**——当 Tushare/Tencent/Zhitu/Akshare 全部失败时才被选中，定位为"知道有价即可"。

### 3.6 Token / 初始化

```python
class MyquantFetcher(BaseFetcher):
    def __init__(self):
        self._token = os.getenv("MYQUANT_TOKEN", "").strip()
        self._initialized = False

    def _ensure_initialized(self):
        if self._initialized:
            return
        self._initialized = True
        if not self._token:
            logger.warning("[MyquantFetcher] MYQUANT_TOKEN not set")
            return
        try:
            from gm.api import set_token
            set_token(self._token)
            logger.info("[MyquantFetcher] Initialized (token configured)")
        except Exception as e:
            logger.warning(f"[MyquantFetcher] Failed to set token: {e}")

    def is_available(self) -> bool:
        self._ensure_initialized()
        return bool(self._token)
```

所有数据方法入口先 `self._ensure_initialized()`。

### 3.7 STOCK_LIST 数据流

```python
def get_all_stocks(self, market: str = "csi") -> list:
    if not self.is_available() or market != "csi":
        return []
    from gm.api import get_symbols
    df = get_symbols(sec_type1=1010, df=True)
    if df is None or df.empty:
        return []
    out = []
    for _, row in df.iterrows():
        symbol = str(row.get("symbol", ""))
        # strip "SHSE." / "SZSE." prefix → "600519"
        code = symbol.split(".", 1)[1] if "." in symbol else symbol
        out.append({
            "code": code,
            "name": str(row.get("sec_name", "")),
            # 透传额外字段，供 persistence 层可选消费
            "symbol_full": symbol,
            "exchange": str(row.get("exchange", "")),
            "is_st": bool(row.get("is_st", False)),
            "is_suspended": bool(row.get("is_suspended", False)),
            "upper_limit": safe_float(row.get("upper_limit")),
            "lower_limit": safe_float(row.get("lower_limit")),
            "turn_rate": safe_float(row.get("turn_rate")),
            "adj_factor": safe_float(row.get("adj_factor")),
            "pre_close": safe_float(row.get("pre_close")),
        })
    return out
```

返回字段保留 myquant 独有的 涨跌停价/ST/停牌/复权因子 等，便于 persistence 层在覆盖 cache 时按需使用。Server 的 `StockInfo` 响应只读 `code` + `name`，其他字段不影响外部契约。

### 3.8 交易日历

```python
def get_trade_calendar(self) -> list[str] | None:
    if not self.is_available():
        return None
    from gm.api import get_trading_dates_by_year
    from datetime import datetime
    now = datetime.now()
    df = get_trading_dates_by_year(
        exchange="SHSE",
        start_year=2010,
        end_year=now.year,
    )
    if df is None or df.empty or "trade_date" not in df.columns:
        return None
    # trade_date 非交易日为空字符串
    dates = [d for d in df["trade_date"].astype(str).tolist() if d and d != "nan"]
    return sorted(dates)
```

只取 SHSE 即可（沪深共用同一日历）。start_year 2010 覆盖现有 akshare 缓存范围。

### 3.9 指数历史 K 线（含分时）

```python
def get_index_historical(
    self, index_code, start_date, end_date, frequency="d"
) -> pd.DataFrame:
    if frequency not in ("d",):  # 指数只支持日线
        raise DataFetchError(f"Myquant index does not support frequency={frequency}")
    symbol = to_myquant_index_format(index_code)
    df = history(symbol=symbol, frequency="1d", start_time=start_date, end_time=end_date,
                 fields="open,high,low,close,amount,volume", df=True)
    return self._normalize_history_df(df, index_code, source="myquant_index")

def get_index_intraday(self, index_code, period="5") -> pd.DataFrame:
    freq_map = {"5": "300s", "15": "900s", "30": "1800s", "60": "3600s"}
    if period not in freq_map:
        raise DataFetchError(f"Myquant index intraday does not support period={period}")
    symbol = to_myquant_index_format(index_code)
    # 拉最近 1 个交易日
    from datetime import date
    end = date.today().strftime("%Y-%m-%d")
    df = history(symbol=symbol, frequency=freq_map[period],
                 start_time=end, end_time=end,
                 fields="open,high,low,close,amount,volume", df=True)
    return self._normalize_intraday_df(df)
```

### 3.10 历史 K 线（股票）

```python
def _fetch_raw_data(self, stock_code, start_date, end_date, frequency="d", adjust=None):
    # frequency 不支持检查
    freq_map = {"d": "1d", "5": "300s", "15": "900s", "30": "1800s", "60": "3600s"}
    if frequency not in freq_map:
        raise DataFetchError(f"Myquant does not support frequency={frequency}")
    symbol = to_myquant_format(stock_code)
    from gm.api import history
    # adjust 已经在 _map_adjust 转成 int（0/1/2）
    df = history(
        symbol=symbol,
        frequency=freq_map[frequency],
        start_time=start_date,
        end_time=end_date,
        adjust=adjust if adjust is not None else 0,
        df=True,
    )
    if df is None or df.empty:
        raise DataFetchError(f"Myquant returned empty for {stock_code}")
    return df
```

### 3.11 归一化

myquant history 返回 DataFrame 字段：`symbol, frequency, open, close, high, low, amount, volume, bob, eob`。归一化逻辑：

```python
def _normalize_data(self, df, stock_code):
    df = df.copy()
    # myquant 使用 bob (begin of bar) 作为时间锚
    if "bob" in df.columns:
        df = df.rename(columns={"bob": "date"})
    df = df.rename(columns={"amount": "amount", "volume": "volume"})  # 已是标准名
    # myquant 无 pct_chg 字段，从 close/open 计算
    if "pct_chg" not in df.columns and "close" in df.columns and "open" in df.columns:
        df["pct_chg"] = (df["close"].astype(float) / df["open"].astype(float) - 1) * 100
    return self._normalize_dataframe(df, stock_code, column_mapping={})
```

`_normalize_dataframe` 已经处理 date 转换、数值化、列选择。

## 4. 错误处理

- 任何 `gm.api.*` 调用异常 → `except Exception: return None`（让 manager 走下一家）
- 转换异常（不支持的市场/代码）→ `raise DataFetchError`（明确告知此路径不适用）
- 限速：复用 `BaseFetcher.random_sleep()`，默认 1.5-3.0s

## 5. 已知风险

| 风险 | 缓解 |
|---|---|
| `gm` 强制 `pandas<2.0` (Python ≤3.11) 与项目 `pandas>=2.0` 冲突 | CI 改用 Python 3.12；运行时 gm 仅用基础 DataFrame API，dependency warning 可接受 |
| myquant 盘后 18:00 清洗入库 | myquant 在 failover 链中位置靠后（Baostock/Akshare 先于它），仅在它们都失败时才用，OK |
| Realtime 字段稀少 | 决策上接受；定位为"最后兜底" |
| 不支持 w/m/1 频率 | 显式 raise DataFetchError 透明降级 |
| `to_myquant_index_format` 未走 `CSI_INDEX_MAP` 显式查表 | myquant 接受任意交易所下 6 位数字指数代码，简单前缀规则足够；若后续发现失败 case 再加查表 |

## 6. 测试

`tests/test_fetcher_structure.py` 新增 `TestMyquantFetcher` 类：

| 用例 | 断言 |
|---|---|
| `test_name_and_priority` | name="MyquantFetcher", priority=1 |
| `test_supported_markets` | `{"csi"}` |
| `test_capabilities` | 7 个 capability 均在 `supported_data_types` 中 |
| `test_is_available_without_token` | monkeypatch 清空 env → False |
| `test_is_available_with_token` | monkeypatch 设 env → True |
| `test_convert_code_shanghai` | `"600519" → "SHSE.600519"` |
| `test_convert_code_shenzhen` | `"000001" → "SZSE.000001"` |
| `test_convert_code_hk_raises` | `"HK00700" → raise ValueError` |
| `test_convert_code_us_raises` | `"AAPL" → raise ValueError` |
| `test_convert_index_format` | `"000300" → "SHSE.000300"`, `"399006" → "SZSE.399006"` |
| `test_convert_index_non_csi_raises` | `"HSI" → raise ValueError` |
| `test_map_adjust` | `"" → 0`, `"qfq" → 1`, `"hfq" → 2` |
| `test_fetch_unsupported_frequency` | `w`/`m`/`1` → raise DataFetchError |
| `test_normalize_history_df` | 给定 myquant 样例 DataFrame，验证归一化后含 `date/open/high/low/close/volume/amount/pct_chg/code` |

不复用 `verify_converters_live.py` 网络测试（避免每次 CI 打 myquant）。

## 7. CLAUDE.md 更新

- 「Fetcher capability declarations」表加：
  ```
  | MyquantFetcher | HISTORICAL_DWM \| HISTORICAL_MIN \| REALTIME_QUOTE \| STOCK_LIST \| TRADE_CALENDAR \| INDEX_HISTORICAL \| INDEX_INTRADAY | csi |
  ```
- 「Common Commands」环境变量表加：`MYQUANT_TOKEN` + `MYQUANT_PRIORITY`（默认 1，紧跟 Tushare）

## 8. 实施顺序

1. `core/types.py` 加 `RealtimeSource.MYQUANT`
2. `utils/code_converter.py` 加两个新函数
3. `fetchers/myquant_fetcher.py` 主文件
4. `manager.py` 注册到 `create_default_manager()`
5. `.env.example` + `pyproject.toml`
6. `tests/test_fetcher_structure.py` 新增 TestMyquantFetcher
7. `CLAUDE.md` 更新
8. 跑 `pytest` + `ruff check` 验证
