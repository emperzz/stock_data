# Phase 3: Signal Layer (ThsFetcher + EastMoney push2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 同花顺 (ThsFetcher: 热点题材/北向资金) and 东财push2 (资金流分钟级+120日) signal layer data

**Architecture:** Create `ths_fetcher.py` for 同花顺 HTTP APIs, extend `eastmoney_fetcher.py` with push2 domain methods for fund flow data. Add DataCapability flags HOT_TOPICS/NORTH_FLOW/FUND_FLOW, register in manager, expose REST APIs.

**Tech Stack:** requests, pandas (for HTML table parsing from 同花顺 basic.10jqka.com.cn)

---

## File Structure

```
stock_data/
├── data_provider/
│   ├── base.py                              # Modify: add HOT_TOPICS, NORTH_FLOW, FUND_FLOW flags
│   └── fetchers/
│       ├── eastmoney_fetcher.py             # Modify: add push2 domain methods
│       └── ths_fetcher.py                   # Create: 同花顺 fetcher
├── api/
│   ├── schemas.py                           # Modify: add 5 response models
│   └── routes.py                            # Modify: add 4 REST endpoints
└── tests/
    ├── test_eastmoney_fetcher.py            # Modify: add fund flow tests
    └── test_ths_fetcher.py                  # Create: ThsFetcher unit tests
```

---

## DataCapability 新增标志

```python
FUND_FLOW  = auto()  # 资金流（个股资金流分钟级+120日）
HOT_TOPICS = auto()  # 热点题材（同花顺当日强势股+题材归因）
NORTH_FLOW = auto()  # 北向资金（沪股通/深股通分钟流向）
```

---

## REST API 清单

| 端点 | 来源 | 说明 |
|------|------|------|
| `GET /stocks/{code}/fund-flow` | EastMoney push2 | 个股资金流（分钟级实时） |
| `GET /stocks/{code}/fund-flow/daily` | EastMoney push2his | 120日历史资金流 |
| `GET /hot/topics` | 同花顺 10jqka | 当日强势股 + 题材归因 reason tags |
| `GET /north-flow/realtime` | 同花顺 hexin.cn | 北向资金分钟流向 |

---

### Task 1: Add DataCapability Flags

**File:** `stock_data/data_provider/base.py`

- Add 3 new flags after existing ones:
```python
FUND_FLOW = auto()   # 资金流（个股资金流分钟级+120日）
HOT_TOPICS = auto()  # 热点题材（同花顺当日强势股+题材归因）
NORTH_FLOW = auto()  # 北向资金（沪股通/深股通分钟流向）
```

- Run: `python -c "from stock_data.data_provider.base import DataCapability; print(DataCapability.FUND_FLOW, DataCapability.HOT_TOPICS, DataCapability.NORTH_FLOW)"`
- Commit: "feat: add DataCapability flags for Phase 3 (fund-flow/hot-topics/north-flow)"

---

### Task 2: Extend EastMoneyFetcher with push2 Fund Flow Methods

**File:** `stock_data/data_provider/fetchers/eastmoney_fetcher.py`

Add FUND_FLOW to `supported_data_types` and two new methods.

**Update capability declaration:**
```python
supported_data_types = (
    DataCapability.DRAGON_TIGER
    | DataCapability.MARGIN_TRADING
    | DataCapability.BLOCK_TRADE
    | DataCapability.HOLDER_NUM
    | DataCapability.DIVIDEND
    | DataCapability.FUND_FLOW
)
```

**Add push2 domain methods:**

```python
def _secid(self, code: str) -> str:
    """Build EastMoney secid: 1.{code} for SH, 0.{code} for SZ."""
    code = normalize_stock_code(code)
    return f"1.{code}" if code.startswith(("6", "9")) else f"0.{code}"

def get_fund_flow_minute(self, code: str) -> list[dict]:
    """Get minute-level fund flow (intraday).

    API: push2.eastmoney.com/api/qt/stock/fflow/kline/get
    Returns: [{time, main_net, small_net, mid_net, large_net, super_net}]
    Unit: yuan
    """
    code = normalize_stock_code(code)
    url = "https://push2.eastmoney.com/api/qt/stock/fflow/kline/get"
    params = {
        "secid": self._secid(code),
        "klt": 1,
        "fields1": "f1,f2,f3,f7",
        "fields2": "f51,f52,f53,f54,f55,f56,f57",
    }
    headers = {
        "User-Agent": UA,
        "Referer": "https://quote.eastmoney.com/",
    }
    try:
        r = requests.get(url, params=params, headers=headers, timeout=10)
        d = r.json()
    except Exception as e:
        logger.warning(f"[EastMoneyFetcher] fund flow minute request failed: {e}")
        return []

    rows = []
    for line in d.get("data", {}).get("klines", []):
        parts = line.split(",")
        if len(parts) >= 6:
            rows.append({
                "time": parts[0],
                "main_net": float(parts[1]) if parts[1] != "-" else 0,
                "small_net": float(parts[2]) if parts[2] != "-" else 0,
                "mid_net": float(parts[3]) if parts[3] != "-" else 0,
                "large_net": float(parts[4]) if parts[4] != "-" else 0,
                "super_net": float(parts[5]) if parts[5] != "-" else 0,
            })
    return rows

def get_fund_flow_120d(self, code: str) -> list[dict]:
    """Get daily fund flow for last 120 trading days.

    API: push2his.eastmoney.com/api/qt/stock/fflow/daykline/get
    Returns: [{date, main_net, small_net, mid_net, large_net, super_net}]
    Unit: yuan
    """
    code = normalize_stock_code(code)
    url = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
    params = {
        "secid": self._secid(code),
        "fields1": "f1,f2,f3,f7",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65",
        "lmt": "120",
    }
    headers = {
        "User-Agent": UA,
        "Referer": "https://quote.eastmoney.com/",
    }
    try:
        r = requests.get(url, params=params, headers=headers, timeout=15)
        d = r.json()
    except Exception as e:
        logger.warning(f"[EastMoneyFetcher] fund flow 120d request failed: {e}")
        return []

    rows = []
    for line in d.get("data", {}).get("klines", []):
        parts = line.split(",")
        if len(parts) >= 7:
            rows.append({
                "date": parts[0],
                "main_net": float(parts[1]) if parts[1] != "-" else 0,
                "small_net": float(parts[2]) if parts[2] != "-" else 0,
                "mid_net": float(parts[3]) if parts[3] != "-" else 0,
                "large_net": float(parts[4]) if parts[4] != "-" else 0,
                "super_net": float(parts[5]) if parts[5] != "-" else 0,
            })
    return rows
```

- Import `cleanse` at top: No new imports needed, `requests` and `normalize_stock_code` already imported.
- Run: `python -c "from stock_data.data_provider.fetchers.eastmoney_fetcher import EastMoneyFetcher; f = EastMoneyFetcher(); print(f._secid('600519'), f._secid('000001'))"`
  Expected: `1.600519 0.000001`
- Commit: "feat: add push2 fund flow methods to EastMoneyFetcher"

---

### Task 3: Create ThsFetcher

**File to create:** `stock_data/data_provider/fetchers/ths_fetcher.py`

```python
"""
同花顺 HTTP API fetcher for signal layer data.

Provides: 热点题材(hot-topics), 北向资金(north-flow)

APIs:
- 热点: zx.10jqka.com.cn/event/api/getharden/
- 北向: data.hexin.cn/market/hsgtApi/method/dayChart/
"""

import logging
from datetime import date as _date
from typing import Optional

import pandas as pd
import requests

from ..base import BaseFetcher, DataCapability, DataFetchError
from ..utils.normalize import normalize_stock_code

logger = logging.getLogger(__name__)

THS_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "Chrome/117.0.0.0 Safari/537.36"
)

HSGT_HEADERS = {
    "User-Agent": THS_UA,
    "Host": "data.hexin.cn",
    "Referer": "https://data.hexin.cn/",
}


class ThsFetcher(BaseFetcher):
    """同花顺 HTTP API fetcher for signal data."""

    name = "ThsFetcher"
    priority = 7
    supported_markets: set[str] = {"csi"}
    supported_data_types = (
        DataCapability.HOT_TOPICS
        | DataCapability.NORTH_FLOW
    )

    def is_available(self) -> bool:
        return True

    def _fetch_raw_data(self, stock_code, start_date, end_date, frequency="d", adjust=None):
        raise DataFetchError("ThsFetcher does not support historical K-line data")

    def _normalize_data(self, df, stock_code):
        raise DataFetchError("ThsFetcher does not support historical K-line data")

    # ------------------------------------------------------------------
    # 热点题材 (Hot Topics)
    # ------------------------------------------------------------------

    def get_hot_topics(self, date_str: str = "") -> list[dict]:
        """Get daily hot stocks with reason tags.

        Returns list of dicts: code, name, reason(题材归因), close, change_pct,
                                turnover_rate, volume, amount, dde_net
        """
        if not date_str:
            date_str = _date.today().strftime("%Y-%m-%d")

        url = (
            f"http://zx.10jqka.com.cn/event/api/getharden/"
            f"date/{date_str}/orderby/date/orderway/desc/charset/GBK/"
        )
        headers = {"User-Agent": THS_UA}
        try:
            r = requests.get(url, headers=headers, timeout=10)
            data = r.json()
            if data.get("errocode", 0) != 0:
                logger.warning(f"[ThsFetcher] hot topics API error: {data.get('errormsg', '')}")
                return []
            rows = data.get("data") or []
            return [self._normalize_hot_topic(row) for row in rows]
        except Exception as e:
            logger.warning(f"[ThsFetcher] hot topics failed: {e}")
            return []

    def _normalize_hot_topic(self, row: dict) -> dict:
        return {
            "code": row.get("code", ""),
            "name": row.get("name", ""),
            "reason": row.get("reason", ""),
            "close_pct": row.get("close", 0),
            "change_pct": row.get("zhangfu", 0),
            "turnover_rate": row.get("huanshou", 0),
            "volume": row.get("chengjiaoliang", 0),
            "amount": row.get("chengjiaoe", 0),
            "dde_net": row.get("ddejingliang", 0),
        }

    # ------------------------------------------------------------------
    # 北向资金 (North-bound Flow)
    # ------------------------------------------------------------------

    def get_north_flow(self) -> list[dict]:
        """Get north-bound (沪股通/深股通) minute-level flow.

        Returns list of dicts: time, hgt_yi(沪股通累计净买入, 亿元),
                                sgt_yi(深股通累计净买入, 亿元)
        """
        url = "https://data.hexin.cn/market/hsgtApi/method/dayChart/"
        try:
            r = requests.get(url, headers=HSGT_HEADERS, timeout=10)
            d = r.json()
            times = d.get("time", [])
            hgt = d.get("hgt", [])
            sgt = d.get("sgt", [])

            n = len(times)
            rows = []
            for i in range(n):
                hgt_val = float(hgt[i]) if i < len(hgt) and hgt[i] else None
                sgt_val = float(sgt[i]) if i < len(sgt) and sgt[i] else None
                rows.append({
                    "time": times[i],
                    "hgt_yi": hgt_val,
                    "sgt_yi": sgt_val,
                })
            return rows
        except Exception as e:
            logger.warning(f"[ThsFetcher] north flow failed: {e}")
            return []
```

- Run: `python -c "from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher; f = ThsFetcher(); print(f.name, f.priority)"`
- Commit: "feat: add ThsFetcher for hot-topics and north-flow"

---

### Task 4: Add API Schemas

**File:** `stock_data/api/schemas.py`

Append these models:

```python
class FundFlowMinuteRecord(BaseModel):
    """资金流分钟级记录"""
    time: str = Field(default="", description="时间 (HH:mm)")
    main_net: float = Field(default=0, description="主力净流入(元)")
    small_net: float = Field(default=0, description="小单净流入(元)")
    mid_net: float = Field(default=0, description="中单净流入(元)")
    large_net: float = Field(default=0, description="大单净流入(元)")
    super_net: float = Field(default=0, description="超大单净流入(元)")


class FundFlowDailyRecord(BaseModel):
    """资金流日级记录"""
    date: str = Field(default="", description="日期")
    main_net: float = Field(default=0, description="主力净流入(元)")
    small_net: float = Field(default=0, description="小单净流入(元)")
    mid_net: float = Field(default=0, description="中单净流入(元)")
    large_net: float = Field(default=0, description="大单净流入(元)")
    super_net: float = Field(default=0, description="超大单净流入(元)")


class FundFlowResponse(BaseModel):
    """资金流响应"""
    code: str = Field(description="股票代码")
    name: str = Field(default="", description="股票名称")
    type: str = Field(default="minute", description="类型: minute/daily")
    records: list = Field(default_factory=list)
    source: str = Field(default="eastmoney")


class HotTopicRecord(BaseModel):
    """热点题材记录"""
    code: str = Field(default="", description="股票代码")
    name: str = Field(default="", description="股票名称")
    reason: str = Field(default="", description="题材归因")
    change_pct: float = Field(default=0, description="涨幅(%)")
    turnover_rate: float = Field(default=0, description="换手率(%)")
    amount: float = Field(default=0, description="成交额")
    dde_net: float = Field(default=0, description="大单净量")


class HotTopicResponse(BaseModel):
    """热点题材响应"""
    date: str = Field(description="交易日期")
    total: int = Field(default=0)
    topics: list[HotTopicRecord] = Field(default_factory=list)
    source: str = Field(default="ths")


class NorthFlowRecord(BaseModel):
    """北向资金记录"""
    time: str = Field(default="", description="时间")
    hgt_yi: float | None = Field(default=None, description="沪股通累计净买入(亿元)")
    sgt_yi: float | None = Field(default=None, description="深股通累计净买入(亿元)")


class NorthFlowResponse(BaseModel):
    """北向资金响应"""
    records: list[NorthFlowRecord] = Field(default_factory=list)
    source: str = Field(default="ths")
```

- Run: `python -c "from stock_data.api.schemas import FundFlowResponse, HotTopicResponse, NorthFlowResponse; print('OK')"`
- Commit: "feat: add response schemas for Phase 3 APIs"

---

### Task 5: Register ThsFetcher & Add REST Endpoints

**File:** `stock_data/api/routes.py`

**A. Add imports:**
```python
from ..data_provider.fetchers.ths_fetcher import ThsFetcher
```
And add new schemas: `FundFlowResponse, HotTopicResponse, NorthFlowResponse, HotTopicRecord, NorthFlowRecord, FundFlowMinuteRecord, FundFlowDailyRecord`

**B. Register in get_manager():**
After EastMoneyFetcher:
```python
ths = ThsFetcher()
if ths.is_available():
    _manager.add_fetcher(ths)
    logger.info("ThsFetcher added")
```

**C. Add 4 endpoints:**

```python
@router.get("/stocks/{stock_code}/fund-flow", response_model=FundFlowResponse, tags=["stocks"])
def get_fund_flow(stock_code: str = Path(max_length=20)) -> FundFlowResponse:
    """Get minute-level fund flow."""
    try:
        manager = get_manager()
        fetcher = manager.get_fetcher("EastMoneyFetcher")
        if not fetcher: raise HTTPException(status_code=503, detail={"error": "unavailable", "message": "EastMoneyFetcher not registered"})
        data = fetcher.get_fund_flow_minute(stock_code)
        stock_name = stock_cache.get_stock_name(stock_code, manager=manager)
        records = [FundFlowMinuteRecord(**r) for r in data]
        return FundFlowResponse(code=stock_code, name=stock_name or "", type="minute", records=records)
    except HTTPException: raise
    except Exception as e: raise HTTPException(status_code=500, detail={"error": "internal_error", "message": str(e)}) from e


@router.get("/stocks/{stock_code}/fund-flow/daily", response_model=FundFlowResponse, tags=["stocks"])
def get_fund_flow_daily(stock_code: str = Path(max_length=20)) -> FundFlowResponse:
    """Get 120-day fund flow history."""
    try:
        manager = get_manager()
        fetcher = manager.get_fetcher("EastMoneyFetcher")
        if not fetcher: raise HTTPException(status_code=503, detail={"error": "unavailable", "message": "EastMoneyFetcher not registered"})
        data = fetcher.get_fund_flow_120d(stock_code)
        stock_name = stock_cache.get_stock_name(stock_code, manager=manager)
        records = [FundFlowDailyRecord(**r) for r in data]
        return FundFlowResponse(code=stock_code, name=stock_name or "", type="daily", records=records)
    except HTTPException: raise
    except Exception as e: raise HTTPException(status_code=500, detail={"error": "internal_error", "message": str(e)}) from e


@router.get("/hot/topics", response_model=HotTopicResponse, tags=["hot"])
def get_hot_topics(date: str = Query(default="", description="Date (YYYY-MM-DD)")) -> HotTopicResponse:
    """Get daily hot stocks with reason tags."""
    try:
        manager = get_manager()
        fetcher = manager.get_fetcher("ThsFetcher")
        if not fetcher: raise HTTPException(status_code=503, detail={"error": "unavailable", "message": "ThsFetcher not registered"})
        data = fetcher.get_hot_topics(date)
        topics = [HotTopicRecord(**r) for r in data]
        return HotTopicResponse(date=date or datetime.now().strftime("%Y-%m-%d"), total=len(topics), topics=topics)
    except HTTPException: raise
    except Exception as e: raise HTTPException(status_code=500, detail={"error": "internal_error", "message": str(e)}) from e


@router.get("/north-flow/realtime", response_model=NorthFlowResponse, tags=["north-flow"])
def get_north_flow() -> NorthFlowResponse:
    """Get north-bound capital flow (minute-level)."""
    try:
        manager = get_manager()
        fetcher = manager.get_fetcher("ThsFetcher")
        if not fetcher: raise HTTPException(status_code=503, detail={"error": "unavailable", "message": "ThsFetcher not registered"})
        data = fetcher.get_north_flow()
        records = [NorthFlowRecord(**r) for r in data]
        return NorthFlowResponse(records=records)
    except HTTPException: raise
    except Exception as e: raise HTTPException(status_code=500, detail={"error": "internal_error", "message": str(e)}) from e
```

- Run: `python -c "from stock_data.api.routes import get_fund_flow, get_fund_flow_daily, get_hot_topics, get_north_flow; print('Routes OK')"`
- Commit: "feat: register ThsFetcher and add 4 Phase 3 REST endpoints"

---

### Task 6: Write Unit Tests

**File:** `tests/test_ths_fetcher.py`, `tests/test_eastmoney_fetcher.py` (add fund flow tests)

**test_ths_fetcher.py:**
```python
import pytest
from unittest.mock import MagicMock, patch
from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher
from stock_data.data_provider.base import DataCapability

class TestThsFetcherBasics:
    def test_name(self): f = ThsFetcher(); assert f.name == "ThsFetcher"
    def test_priority(self): f = ThsFetcher(); assert f.priority == 7
    def test_is_available(self): f = ThsFetcher(); assert f.is_available() is True
    def test_capabilities(self):
        f = ThsFetcher()
        assert DataCapability.HOT_TOPICS in f.supported_data_types
        assert DataCapability.NORTH_FLOW in f.supported_data_types

class TestHotTopics:
    def setup_method(self): self.fetcher = ThsFetcher()
    def test_normalize(self):
        row = {"code": "600519", "name": "Test", "reason": "白酒+消费", "zhangfu": 5.5, "huanshou": 2.1, "chengjiaoe": 1000000}
        result = self.fetcher._normalize_hot_topic(row)
        assert result["code"] == "600519"
        assert result["reason"] == "白酒+消费"
        assert result["change_pct"] == 5.5

class TestNorthFlow:
    def setup_method(self): self.fetcher = ThsFetcher()
    @patch("stock_data.data_provider.fetchers.ths_fetcher.requests.get")
    def test_returns_records(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = {"time": ["09:30", "09:31"], "hgt": [0.5, 0.7], "sgt": [0.3, 0.4]}
        mock_get.return_value = mock_response
        result = self.fetcher.get_north_flow()
        assert len(result) == 2
        assert result[0]["hgt_yi"] == 0.5
```

**Add to test_eastmoney_fetcher.py:**
```python
class TestFundFlow:
    def setup_method(self): self.fetcher = EastMoneyFetcher()
    def test_secid_sh(self): assert self.fetcher._secid("600519") == "1.600519"
    def test_secid_sz(self): assert self.fetcher._secid("000001") == "0.000001"

class TestFundFlowMinute:
    def setup_method(self): self.fetcher = EastMoneyFetcher()
    @patch("stock_data.data_provider.fetchers.eastmoney_fetcher.requests.get")
    def test_returns_records(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": {"klines": ["09:30,1000,200,300,400,600"]}}
        mock_get.return_value = mock_response
        result = self.fetcher.get_fund_flow_minute("600519")
        assert len(result) == 1
        assert result[0]["main_net"] == 1000

class TestFundFlow120d:
    def setup_method(self): self.fetcher = EastMoneyFetcher()
    @patch("stock_data.data_provider.fetchers.eastmoney_fetcher.requests.get")
    def test_returns_records(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": {"klines": ["2026-05-20,5000,1000,2000,3000,4000"]}}
        mock_get.return_value = mock_response
        result = self.fetcher.get_fund_flow_120d("600519")
        assert len(result) == 1
        assert result[0]["date"] == "2026-05-20"
```

- Run: `pytest tests/test_ths_fetcher.py tests/test_eastmoney_fetcher.py tests/test_tencent_fetcher.py -v --tb=short`
- Commit (ths tests + eastmoney tests separately)

---

### Task 7: Integration Test & Push

- Run combined tests: `pytest tests/test_ths_fetcher.py tests/test_eastmoney_fetcher.py tests/test_tencent_fetcher.py -v`
- Verify manager: `python -c "from stock_data.api.routes import get_manager; m = get_manager(); print([f.name for f in m.fetchers])"`
- Push
