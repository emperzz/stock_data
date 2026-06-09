# 分时数据 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增 `GET /stocks/{stock_code}/intraday` 接口，支持 1/5/15/30/60 分钟分时数据，优先 Akshare（东财EM + 新浪历史分钟），降级 Zhitu。

**Architecture:**
- Provider 层每个 fetcher 新增 `get_intraday_data()` 方法，Akshare 内部双重 API fallback，Zhitu 使用 `/hs/history/{code}.{market}/{period}/{adjust}` 接口
- Manager 层通过 `get_intraday_data()` 按 priority 遍历 fetchers
- API 层新增路由和 schema

**Tech Stack:** FastAPI, akshare, requests, pandas

---

## File Map

| 文件 | 职责 |
|------|------|
| `stock_data/data_provider/base.py` | `BaseFetcher` 新增抽象方法 `get_intraday_data()`；`DataFetcherManager` 新增 `get_intraday_data()` |
| `stock_data/data_provider/akshare_fetcher.py` | 实现 `get_intraday_data()`，内部 try EM→新浪历史分钟 fallback |
| `stock_data/data_provider/zhitu_fetcher.py` | 实现 `get_intraday_data()`，调用 `/hs/history/{code}.{market}/{period}/{adjust}` |
| `stock_data/api/schemas.py` | 新增 `IntradayData`、`IntradayResponse` schema |
| `stock_data/api/routes.py` | 新增 `/stocks/{stock_code}/intraday` endpoint |
| `tests/test_providers.py` | 新增 `TestAkshareFetcherIntraday`、`TestZhituFetcherIntraday` 测试类 |

---

## Task 1: Add abstract method to BaseFetcher and manager method

**Files:**
- Modify: `stock_data/data_provider/base.py` (add abstract method + manager method)

- [ ] **Step 1: Add abstract method to BaseFetcher**

在 `BaseFetcher` 类中添加：

```python
def get_intraday_data(
    self,
    stock_code: str,
    period: str = "5",
    adjust: str = ""
) -> pd.DataFrame | None:
    """Get intraday minute-level data for a stock.

    Args:
        stock_code: Stock code (e.g., 600519, 000001)
        period: Minute period - "1", "5", "15", "30", "60"
        adjust: Adjustment type - ""=不复权, "qfq"=前复权, "hfq"=后复权

    Returns:
        DataFrame with columns: time, open, high, low, close, volume, amount
        or None if not supported.
    """
    return None
```

- [ ] **Step 2: Add get_intraday_data to DataFetcherManager**

在 `DataFetcherManager` 类中添加：

```python
def get_intraday_data(
    self,
    stock_code: str,
    period: str = "5",
    adjust: str = ""
) -> Tuple[pd.DataFrame, str]:
    """Get intraday minute-level data with automatic failover.

    Args:
        stock_code: Stock code
        period: Minute period - "1", "5", "15", "30", "60"
        adjust: Adjustment type - ""=不复权, "qfq"=前复权, "hfq"=后复权

    Returns:
        Tuple of (DataFrame, source_name)

    Raises:
        DataFetchError: When all fetchers fail
    """
    stock_code = normalize_stock_code(stock_code)
    market = market_tag(stock_code)
    fetchers = self._filter_by_market(market)

    errors = []
    for fetcher in fetchers:
        try:
            logger.info(f"[Manager] Trying {fetcher.name} for {stock_code} intraday ({period})")
            df = fetcher.get_intraday_data(stock_code, period, adjust)
            if df is not None and not df.empty:
                logger.info(f"[Manager] {fetcher.name} succeeded for {stock_code} intraday")
                return df, fetcher.name
        except Exception as e:
            errors.append(f"[{fetcher.name}] {e}")
            logger.warning(f"[Manager] {fetcher.name} intraday failed: {e}")
            continue

    raise DataFetchError(f"All fetchers failed for {stock_code} intraday:\n" + "\n".join(errors))
```

- [ ] **Step 3: Run tests to verify no regression**

Run: `pytest tests/test_base.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add stock_data/data_provider/base.py
git commit -m "feat(base): add get_intraday_data abstract method and manager support"
```

---

## Task 2: Implement AkshareFetcher.get_intraday_data()

**Files:**
- Modify: `stock_data/data_provider/akshare_fetcher.py` (add method)

- [ ] **Step 1: Add helper method _convert_to_zhitu_code**

在 `AkshareFetcher` 中已有 `_convert_to_akshare_code`，新增一个转换方法用于 Zhitu（返回 `600519.SH` 格式），不需要新增——直接用 `normalize_stock_code` 配合市场判断即可。

- [ ] **Step 2: Add get_intraday_data method**

在 `AkshareFetcher` 类中添加：

```python
def get_intraday_data(
    self,
    stock_code: str,
    period: str = "5",
    adjust: str = ""
) -> pd.DataFrame | None:
    """Get intraday minute-level data.

    Strategy:
    1. Try stock_zh_a_hist_min_em (Eastmoney, supports period+adjust+date range)
    2. Fallback to stock_zh_a_minute (Sina, supports period+adjust)

    Args:
        stock_code: Stock code (e.g., 600519, 000001)
        period: Minute period - "1", "5", "15", "30", "60"
        adjust: Adjustment type - ""=不复权, "qfq"=前复权, "hfq"=后复权

    Returns:
        DataFrame with columns: time, open, high, low, close, volume, amount
        or None if not supported.
    """
    try:
        import akshare as ak

        # Convert code: 600519 -> 600519 (A-share), normalize for index
        code = normalize_stock_code(stock_code)
        is_index = is_index_code(stock_code)
        if is_index:
            index_type = get_index_type(stock_code)
            if index_type != "csi":
                return None  # Only CSI indices supported for intraday

        # Map adjust: API format
        adj_map = {"": "", "qfq": "qfq", "hfq": "hfq"}
        adj_value = adj_map.get(adjust, "")

        # Try EM first (stock_zh_a_hist_min_em)
        df = self._fetch_intraday_em(code, period, adj_value)
        if df is not None and not df.empty:
            return df

        # Fallback to Sina (stock_zh_a_minute)
        df = self._fetch_intraday_sina(code, period, adj_value)
        return df

    except Exception as e:
        logger.warning(f"[AkshareFetcher] get_intraday_data failed: {e}")
        return None

def _fetch_intraday_em(self, code: str, period: str, adjust: str) -> pd.DataFrame | None:
    """Fetch via stock_zh_a_hist_min_em."""
    try:
        import akshare as ak
        from datetime import date

        today = date.today().strftime("%Y-%m-%d")
        start = f"{today} 09:30:00"
        end = f"{today} 15:00:00"

        df = ak.stock_zh_a_hist_min_em(
            symbol=code,
            start_date=start,
            end_date=end,
            period=period,
            adjust=adjust
        )
        if df is None or df.empty:
            return None
        return self._normalize_intraday_em(df)
    except Exception as e:
        logger.debug(f"[AkshareFetcher] EM intraday failed: {e}")
        return None

def _fetch_intraday_sina(self, code: str, period: str, adjust: str) -> pd.DataFrame | None:
    """Fetch via stock_zh_a_minute."""
    try:
        import akshare as ak

        # Sina format: sh600519 or sz000001
        symbol = f"sh{code}" if code.startswith(("6", "5")) else f"sz{code}"
        df = ak.stock_zh_a_minute(symbol=symbol, period=period, adjust=adjust)
        if df is None or df.empty:
            return None
        return self._normalize_intraday_sina(df)
    except Exception as e:
        logger.debug(f"[AkshareFetcher] Sina intraday failed: {e}")
        return None

def _normalize_intraday_em(self, df: pd.DataFrame) -> pd.DataFrame:
    """Normalize stock_zh_a_hist_min_em output."""
    df = df.copy()
    column_mapping = {
        "时间": "time",
        "开盘": "open",
        "收盘": "close",
        "最高": "high",
        "最低": "low",
        "成交量": "volume",
        "成交额": "amount",
    }
    df = df.rename(columns=column_mapping)
    if "time" in df.columns:
        df["time"] = df["time"].astype(str).str[-8:]  # Extract HH:MM:SS
    numeric_cols = ["open", "high", "low", "close", "volume", "amount"]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    keep_cols = ["time", "open", "high", "low", "close", "volume", "amount"]
    df = df[[c for c in keep_cols if c in df.columns]]
    return df

def _normalize_intraday_sina(self, df: pd.DataFrame) -> pd.DataFrame:
    """Normalize stock_zh_a_minute output."""
    df = df.copy()
    df = df.rename(columns={
        "day": "time",
        "open": "open",
        "high": "high",
        "low": "low",
        "close": "close",
        "volume": "volume",
        "amount": "amount",
    })
    if "time" in df.columns:
        df["time"] = df["time"].astype(str).str[-8:]  # Extract HH:MM:SS
    numeric_cols = ["open", "high", "low", "close", "volume", "amount"]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    keep_cols = ["time", "open", "high", "low", "close", "volume", "amount"]
    df = df[[c for c in keep_cols if c in df.columns]]
    return df
```

- [ ] **Step 3: Run test to verify implementation**

Run: `pytest tests/test_providers.py::TestAkshareFetcher -v -k intraday --lf 2>&1 | head -30`
Expected: Method not found error (test doesn't exist yet) — proceed to Task 7

- [ ] **Step 4: Commit**

```bash
git add stock_data/data_provider/akshare_fetcher.py
git commit -m "feat(akshare): add get_intraday_data with EM+Sina dual API fallback"
```

---

## Task 3: Implement ZhituFetcher.get_intraday_data()

**Files:**
- Modify: `stock_data/data_provider/zhitu_fetcher.py` (add method)

- [ ] **Step 1: Add market suffix helper**

在 `ZhituFetcher` 中新增：

```python
def _market_suffix(self, stock_code: str) -> str:
    """Return .SZ or .SH for Zhitu API."""
    code = normalize_stock_code(stock_code)
    # Beijing Stock Exchange
    if len(code) == 6 and code.startswith(("83", "87", "43", "82", "88", "92", "81")):
        return ".BJ"
    # Shanghai
    if code.startswith(("6", "5")):
        return ".SH"
    # Shenzhen
    return ".SZ"
```

- [ ] **Step 2: Add get_intraday_data method**

```python
def get_intraday_data(
    self,
    stock_code: str,
    period: str = "5",
    adjust: str = ""
) -> pd.DataFrame | None:
    """Get intraday minute-level data from Zhitu history API.

    API: https://api.zhituapi.com/hs/history/{code}.{market}/{period}/{adjust}?token={token}&st={date}&et={date}

    Args:
        stock_code: Stock code (e.g., 600519, 000001)
        period: Minute period - "5", "15", "30", "60" (NOT "1")
        adjust: Adjustment type - ""=不复权, "qfq"=前复权, "hfq"=后复权

    Returns:
        DataFrame with columns: time, open, high, low, close, volume, amount
        or None if not supported or period=1 (not supported by Zhitu).
    """
    if not self.is_available():
        logger.warning("[ZhituFetcher] ZHITU_TOKEN not configured")
        return None

    # Zhitu doesn't support period=1
    if period == "1":
        raise DataFetchError("ZhituFetcher does not support period=1")

    try:
        import requests

        code = normalize_stock_code(stock_code)
        market = self._market_suffix(stock_code)
        symbol = f"{code}{market}"

        # Map adjust: API format
        adj_map = {"": "n", "qfq": "f", "hfq": "b"}
        adj_value = adj_map.get(adjust, "n")

        # Get latest trade date
        from ..stock_cache import get_latest_cached_trade_date
        latest_date = get_latest_cached_trade_date()
        if not latest_date:
            from datetime import date
            latest_date = date.today().strftime("%Y%m%d")
        else:
            latest_date = latest_date.replace("-", "")

        url = f"{ZHITU_API_BASE}/hs/history/{symbol}/{period}/{adj_value}"
        params = {
            "token": self._token,
            "st": latest_date,
            "et": latest_date,
        }

        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        if isinstance(data, dict) and "detail" in data:
            logger.warning(f"[ZhituFetcher] API error: {data.get('detail')}")
            return None

        if not isinstance(data, list):
            logger.warning(f"[ZhituFetcher] Unexpected response type: {type(data)}")
            return None

        if not data:
            return None

        df = pd.DataFrame(data)
        return self._normalize_intraday_zhitu(df)

    except DataFetchError:
        raise
    except requests.exceptions.Timeout:
        logger.warning(f"[ZhituFetcher] Timeout for {stock_code}")
        return None
    except requests.exceptions.RequestException as e:
        logger.warning(f"[ZhituFetcher] Request failed: {e}")
        return None
    except Exception as e:
        logger.warning(f"[ZhituFetcher] Error: {e}")
        return None

def _normalize_intraday_zhitu(self, df: pd.DataFrame) -> pd.DataFrame:
    """Normalize Zhitu history API output."""
    df = df.copy()
    df = df.rename(columns={
        "t": "time",
        "o": "open",
        "h": "high",
        "l": "low",
        "c": "close",
        "v": "volume",
        "a": "amount",
    })
    if "time" in df.columns:
        # Zhitu returns ISO format with T, extract HH:MM:SS
        df["time"] = df["time"].astype(str).str[-8:]
    numeric_cols = ["open", "high", "low", "close", "volume", "amount"]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    keep_cols = ["time", "open", "high", "low", "close", "volume", "amount"]
    df = df[[c for c in keep_cols if c in df.columns]]
    return df
```

- [ ] **Step 3: Commit**

```bash
git add stock_data/data_provider/zhitu_fetcher.py
git commit -m "feat(zhitu): add get_intraday_data via /hs/history/{code}.{market}/{period}/{adjust}"
```

---

## Task 4: Add API schemas

**Files:**
- Modify: `stock_data/api/schemas.py` (add IntradayData, IntradayResponse)

- [ ] **Step 1: Add schemas**

在 `schemas.py` 末尾添加：

```python
class IntradayData(BaseModel):
    """Single intraday minute-level data point."""

    time: str = Field(description="Time (HH:MM:SS)")
    open: float = Field(description="Opening price")
    high: float = Field(description="Highest price")
    low: float = Field(description="Lowest price")
    close: float = Field(description="Closing price")
    volume: int = Field(description="Volume")
    amount: float | None = Field(default=None, description="Amount")


class IntradayResponse(BaseModel):
    """Intraday minute-level data response."""

    stock_code: str = Field(description="Stock code")
    stock_name: str = Field(default="", description="Stock name")
    period: str = Field(description="Minute period (1m/5m/15m/30m/60m)")
    adjust: str = Field(default="", description="Adjustment type")
    date: str = Field(description="Trade date (YYYY-MM-DD)")
    data: list[IntradayData] = Field(default_factory=list, description="Minute-level data points")
```

- [ ] **Step 2: Commit**

```bash
git add stock_data/api/schemas.py
git commit -m "feat(schemas): add IntradayData and IntradayResponse schemas"
```

---

## Task 5: Add API route

**Files:**
- Modify: `stock_data/api/routes.py` (add endpoint)

- [ ] **Step 1: Add endpoint**

在 `routes.py` 顶部 import 添加 `IntradayResponse`，然后添加：

```python
@router.get(
    "/stocks/{stock_code}/intraday",
    response_model=IntradayResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid period or unsupported market"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["stocks"],
)
def get_intraday(
    stock_code: str,
    period: str = Query(
        default="5",
        pattern="^(1|5|15|30|60)$",
        description="Minute period: 1, 5, 15, 30, 60",
    ),
    adjust: str = Query(
        default="",
        pattern="^(qfq|hfq)?$",
        description="Adjustment type: empty=不复权, qfq=前复权, hfq=后复权",
    ),
) -> IntradayResponse:
    """
    Get intraday minute-level data for a stock.

    Args:
        stock_code: Stock code (e.g., 600519, 000001)
        period: Minute period - 1, 5, 15, 30, 60
        adjust: Adjustment type - empty=不复权, qfq=前复权, hfq=后复权

    Note:
        - period=1 is only supported by Akshare (Zhitu does not support 1-minute data)
        - Intraday data is only available for A-share stocks
    """
    try:
        # Only A-share supported for intraday
        from ..data_provider.base import is_us_market, is_hk_market
        code = normalize_stock_code(stock_code)
        if is_us_market(code) or is_hk_market(code):
            raise HTTPException(
                status_code=400,
                detail={"error": "unsupported_market", "message": "Intraday data is only available for A-share stocks"},
            )

        manager = get_manager()
        df, source = manager.get_intraday_data(stock_code, period=period, adjust=adjust)

        # Get stock name
        stock_name = ""
        for fetcher in manager.fetchers:
            if hasattr(fetcher, "get_stock_name"):
                try:
                    name = fetcher.get_stock_name(stock_code)
                    if name:
                        stock_name = name
                        break
                except Exception:
                    pass

        # Determine trade date from data
        trade_date = ""
        if "time" in df.columns and len(df) > 0:
            first_time = str(df.iloc[0].get("time", ""))
            if len(first_time) >= 10:
                trade_date = first_time[:10]

        records = df.to_dict("records")
        data = [
            IntradayData(
                time=str(row.get("time", "")),
                open=float(row.get("open", 0)),
                high=float(row.get("high", 0)),
                low=float(row.get("low", 0)),
                close=float(row.get("close", 0)),
                volume=int(row.get("volume", 0)),
                amount=float(row.get("amount")) if row.get("amount") is not None else None,
            )
            for row in records
        ]

        period_label = f"{period}m"
        return IntradayResponse(
            stock_code=stock_code,
            stock_name=stock_name,
            period=period_label,
            adjust=adjust,
            date=trade_date,
            data=data,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Intraday error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail={"error": "internal_error", "message": str(e)}) from e
```

- [ ] **Step 2: Commit**

```bash
git add stock_data/api/routes.py
git commit -m "feat(api): add GET /stocks/{stock_code}/intraday endpoint"
```

---

## Task 6: Add provider tests

**Files:**
- Modify: `tests/test_providers.py` (add test classes)

- [ ] **Step 1: Add TestAkshareFetcherIntraday class**

在 `test_providers.py` 末尾添加：

```python
class TestAkshareFetcherIntraday:
    """Tests for AkshareFetcher.get_intraday_data()."""

    @pytest.fixture
    def fetcher(self):
        from stock_data.data_provider.akshare_fetcher import AkshareFetcher
        return AkshareFetcher()

    def test_get_intraday_5m(self, fetcher):
        """Test get_intraday_data for 5-minute period."""
        df = fetcher.get_intraday_data("000001", period="5", adjust="")
        assert df is not None
        assert len(df) > 0
        assert "time" in df.columns
        assert "close" in df.columns
        assert "volume" in df.columns

    def test_get_intraday_5m_with_adjust(self, fetcher):
        """Test get_intraday_data for 5-minute period with qfq."""
        df = fetcher.get_intraday_data("000001", period="5", adjust="qfq")
        assert df is not None
        assert len(df) > 0

    def test_get_intraday_60m(self, fetcher):
        """Test get_intraday_data for 60-minute period."""
        df = fetcher.get_intraday_data("600519", period="60", adjust="")
        assert df is not None
        assert len(df) > 0

    def test_get_intraday_normalized_columns(self, fetcher):
        """Test normalized columns: time, open, high, low, close, volume, amount."""
        df = fetcher.get_intraday_data("000001", period="5", adjust="")
        expected_cols = {"time", "open", "high", "low", "close", "volume", "amount"}
        assert set(df.columns) == expected_cols

    def test_get_intraday_returns_none_for_unsupported_market(self, fetcher):
        """Test get_intraday_data returns None for US stock."""
        df = fetcher.get_intraday_data("AAPL", period="5", adjust="")
        assert df is None


class TestZhituFetcherIntraday:
    """Tests for ZhituFetcher.get_intraday_data()."""

    @pytest.fixture
    def fetcher(self):
        from stock_data.data_provider.zhitu_fetcher import ZhituFetcher
        return ZhituFetcher()

    def test_get_intraday_5m(self, fetcher):
        """Test get_intraday_data for 5-minute period."""
        if not fetcher.is_available():
            pytest.skip("ZHITU_TOKEN not configured")
        df = fetcher.get_intraday_data("000001", period="5", adjust="")
        assert df is not None
        assert len(df) > 0
        assert "time" in df.columns
        assert "close" in df.columns

    def test_get_intraday_rejects_period_1(self, fetcher):
        """Test that period=1 raises DataFetchError."""
        if not fetcher.is_available():
            pytest.skip("ZHITU_TOKEN not configured")
        from stock_data.data_provider.base import DataFetchError
        with pytest.raises(DataFetchError):
            fetcher.get_intraday_data("000001", period="1", adjust="")

    def test_get_intraday_normalized_columns(self, fetcher):
        """Test normalized columns match expected."""
        if not fetcher.is_available():
            pytest.skip("ZHITU_TOKEN not configured")
        df = fetcher.get_intraday_data("000001", period="5", adjust="")
        expected_cols = {"time", "open", "high", "low", "close", "volume", "amount"}
        assert set(df.columns) == expected_cols
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/test_providers.py::TestAkshareFetcherIntraday -v --lf 2>&1 | head -40`
Expected: PASS (all tests)

- [ ] **Step 3: Commit**

```bash
git add tests/test_providers.py
git commit -m "test: add TestAkshareFetcherIntraday and TestZhituFetcherIntraday"
```

---

## Self-Review Checklist

1. **Spec coverage**: All spec requirements mapped:
   - API endpoint → Task 5
   - Akshare dual API → Task 2
   - Zhitu history API → Task 3
   - Manager failover → Task 1
   - Period=1 only Akshare → Task 2 & Task 3
   - Adjust parameter mapping → Task 2 & Task 3

2. **Placeholder scan**: No TBD/TODO found. All code is complete and runnable.

3. **Type consistency**: Method signatures match across tasks:
   - `get_intraday_data(stock_code, period, adjust)` in all three providers
   - Return: `pd.DataFrame | None` (provider) → `Tuple[pd.DataFrame, str]` (manager)
   - `period` is `str` with values `"1"`, `"5"`, `"15"`, `"30"`, `"60"`

4. **Spec special case**: `period=1` rejected by Zhitu → implemented as `DataFetchError` in Task 3 Step 2

---

**Plan complete.** Saved to `docs/superpowers/plans/2026-05-13-intraday-plan.md`.

**Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch with checkpoints

Which approach?