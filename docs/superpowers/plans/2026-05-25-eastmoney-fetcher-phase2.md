# Phase 2: EastMoney Fetcher (Datacenter Domain) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add EastMoney datacenter HTTP API support for 龙虎榜/融资融券/大宗交易/股东户数/分红数据

**Architecture:** Create `eastmoney_fetcher.py` with an internal `_datacenter_query()` helper that calls eastmoney datacenter API, plus dedicated methods for each data type. Add new DataCapability flags, register in manager, expose REST APIs.

**Tech Stack:** requests, Python standard library

---

## File Structure

```
stock_data/
├── data_provider/
│   ├── base.py                              # Modify: add DataCapability flags
│   └── fetchers/
│       └── eastmoney_fetcher.py             # Create: EastMoney fetcher (datacenter domain)
├── api/
│   ├── schemas.py                           # Modify: add response models
│   └── routes.py                            # Modify: add 5 new REST endpoints
└── tests/
    └── test_eastmoney_fetcher.py            # Create: unit tests
```

---

## DataCapability 新增标志

```python
DRAGON_TIGER   = auto()  # 龙虎榜（个股+全市场）
MARGIN_TRADING = auto()  # 融资融券
BLOCK_TRADE    = auto()  # 大宗交易
HOLDER_NUM     = auto()  # 股东户数变化
DIVIDEND       = auto()  # 分红送转
```

---

## REST API 清单

| 端点 | 说明 |
|------|------|
| `GET /stocks/{code}/dragon-tiger` | 个股龙虎榜（含买卖席位/机构动向） |
| `GET /stocks/{code}/dragon-tiger/daily` | 全市场龙虎榜（按日期查询） |
| `GET /stocks/{code}/margin` | 融资融券明细 |
| `GET /stocks/{code}/block-trade` | 大宗交易记录 |
| `GET /stocks/{code}/holder-num` | 股东户数变化 |
| `GET /stocks/{code}/dividend` | 分红送转历史 |

---

## EastMoneyFetcher 核心结构

```python
class EastMoneyFetcher(BaseFetcher):
    name = "EastMoneyFetcher"
    priority = 6
    supported_markets = {"csi"}
    supported_data_types = DataCapability(
        DRAGON_TIGER | MARGIN_TRADING | BLOCK_TRADE | HOLDER_NUM | DIVIDEND
    )

    DATACENTER_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"

    def _datacenter_query(report_name, columns, filter_str, page_size,
                          sort_columns, sort_types):
        """统一查询 helper"""

    # Datacenter 域方法
    def get_dragon_tiger(code, trade_date, look_back) -> dict: ...
    def get_daily_dragon_tiger(trade_date, min_net_buy) -> dict: ...
    def get_margin_trading(code, page_size) -> list[dict]: ...
    def get_block_trade(code, page_size) -> list[dict]: ...
    def get_holder_num_change(code, page_size) -> list[dict]: ...
    def get_dividend(code, page_size) -> list[dict]: ...
```

---

### Task 1: Add DataCapability Flags

**File:** `stock_data/data_provider/base.py`

- [ ] **Step 1: Read and verify current enum**

Read `stock_data/data_provider/base.py` around line 42-52 to see the DataCapability enum.

- [ ] **Step 2: Add 5 new flags**

After `STOCK_ZT_POOL = auto()  # 涨跌停股池`, add:

```python
DRAGON_TIGER = auto()   # 龙虎榜（个股+全市场）
MARGIN_TRADING = auto() # 融资融券
BLOCK_TRADE = auto()    # 大宗交易
HOLDER_NUM = auto()     # 股东户数变化
DIVIDEND = auto()       # 分红送转
```

- [ ] **Step 3: Run test to verify**

Run: `python -c "from stock_data.data_provider.base import DataCapability; print(DataCapability.DRAGON_TIGER, DataCapability.MARGIN_TRADING)"`

- [ ] **Step 4: Commit**

```bash
git add stock_data/data_provider/base.py
git commit -m "feat: add DataCapability flags for dragon-tiger/margin/block-trade/holder-num/dividend

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 2: Create EastMoneyFetcher

**Files:**
- Create: `stock_data/data_provider/fetchers/eastmoney_fetcher.py`

**Full implementation:**

```python
"""
EastMoney数据中心 HTTP API fetcher.

Provides: 龙虎榜(dragon-tiger), 融资融券(margin), 大宗交易(block-trade),
          股东户数(holder-num), 分红送转(dividend)

API: https://datacenter-web.eastmoney.com/api/data/v1/get
All endpoints share the same base URL with different reportName params.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
import requests

from ..base import BaseFetcher, DataCapability, DataFetchError
from ..utils.normalize import normalize_stock_code

logger = logging.getLogger(__name__)

DATACENTER_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


class EastMoneyFetcher(BaseFetcher):
    """EastMoney datacenter API fetcher for financial data."""

    name = "EastMoneyFetcher"
    priority = 6
    supported_markets: set[str] = {"csi"}
    supported_data_types = DataCapability(
        DataCapability.DRAGON_TIGER
        | DataCapability.MARGIN_TRADING
        | DataCapability.BLOCK_TRADE
        | DataCapability.HOLDER_NUM
        | DataCapability.DIVIDEND
    )

    def is_available(self) -> bool:
        """EastMoney API is always available (no auth required)."""
        return True

    def _fetch_raw_data(
        self, stock_code: str, start_date: str, end_date: str,
        frequency: str = "d", adjust: str | None = None
    ) -> pd.DataFrame:
        raise DataFetchError("EastMoneyFetcher does not support historical K-line data")

    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        raise DataFetchError("EastMoneyFetcher does not support historical K-line data")

    # ------------------------------------------------------------------
    # Helper: unified datacenter query
    # ------------------------------------------------------------------

    def _datacenter_query(
        self,
        report_name: str,
        columns: str = "ALL",
        filter_str: str = "",
        page_size: int = 50,
        sort_columns: str = "",
        sort_types: str = "-1",
    ) -> list[dict]:
        """EastMoney datacenter unified query helper."""
        params = {
            "reportName": report_name,
            "columns": columns,
            "filter": filter_str,
            "pageNumber": "1",
            "pageSize": str(page_size),
            "sortColumns": sort_columns,
            "sortTypes": sort_types,
            "source": "WEB",
            "client": "WEB",
        }
        headers = {
            "User-Agent": UA,
            "Referer": "https://data.eastmoney.com/",
        }
        try:
            r = requests.get(DATACENTER_URL, params=params, headers=headers, timeout=15)
            d = r.json()
            if d.get("result") and d["result"].get("data"):
                return d["result"]["data"]
            return []
        except Exception as e:
            logger.warning(f"[EastMoneyFetcher] datacenter query failed: {e}")
            return []

    # ------------------------------------------------------------------
    # Data type: 龙虎榜 (Dragon Tiger Board)
    # ------------------------------------------------------------------

    def get_dragon_tiger(
        self, code: str, trade_date: str = "", look_back: int = 30
    ) -> dict:
        """Get dragon tiger board data for a single stock.

        Returns: {records: [...], seats: {buy: [...], sell: [...]}, institution: {...}}
        """
        code = normalize_stock_code(code)
        if not trade_date:
            trade_date = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.strptime(trade_date, "%Y-%m-%d")
                 - timedelta(days=look_back)).strftime("%Y-%m-%d")

        # 1. 上榜记录
        filter_str = (
            f"(TRADE_DATE>='{start}')(TRADE_DATE<='{trade_date}')"
            f'(SECURITY_CODE="{code}")'
        )
        data = self._datacenter_query(
            "RPT_DAILYBILLBOARD_DETAILSNEW",
            filter_str=filter_str, page_size=50,
            sort_columns="TRADE_DATE", sort_types="-1",
        )
        records = []
        for row in data:
            records.append({
                "date": str(row.get("TRADE_DATE", ""))[:10],
                "reason": row.get("EXPLANATION", ""),
                "net_buy_wan": round((row.get("BILLBOARD_NET_AMT") or 0) / 10000, 1),
                "turnover_pct": round(float(row.get("TURNOVERRATE") or 0), 2),
            })

        # 2. 买卖席位
        seats = {"buy": [], "sell": []}
        institution = {"buy_amt": 0, "sell_amt": 0, "net_amt": 0}
        if records:
            latest_date = records[0]["date"]
            # Buy seats
            buy_data = self._datacenter_query(
                "RPT_BILLBOARD_DAILYDETAILSBUY",
                filter_str=f"(TRADE_DATE='{latest_date}')(SECURITY_CODE=\"{code}\")",
                page_size=10, sort_columns="BUY", sort_types="-1",
            )
            for row in buy_data[:5]:
                seats["buy"].append({
                    "name": row.get("OPERATEDEPT_NAME", ""),
                    "buy_wan": round((row.get("BUY") or 0) / 10000, 1),
                    "sell_wan": round((row.get("SELL") or 0) / 10000, 1),
                    "net_wan": round((row.get("NET") or 0) / 10000, 1),
                })
            # Sell seats
            sell_data = self._datacenter_query(
                "RPT_BILLBOARD_DAILYDETAILSSELL",
                filter_str=f"(TRADE_DATE='{latest_date}')(SECURITY_CODE=\"{code}\")",
                page_size=10, sort_columns="SELL", sort_types="-1",
            )
            for row in sell_data[:5]:
                seats["sell"].append({
                    "name": row.get("OPERATEDEPT_NAME", ""),
                    "buy_wan": round((row.get("BUY") or 0) / 10000, 1),
                    "sell_wan": round((row.get("SELL") or 0) / 10000, 1),
                    "net_wan": round((row.get("NET") or 0) / 10000, 1),
                })
            # Institution stats
            for detail_data, side in [(buy_data, "buy"), (sell_data, "sell")]:
                for row in detail_data:
                    if str(row.get("OPERATEDEPT_CODE", "")) == "0":
                        if side == "buy":
                            institution["buy_amt"] += (row.get("BUY") or 0)
                        else:
                            institution["sell_amt"] += (row.get("SELL") or 0)
            institution["buy_amt"] = round(institution["buy_amt"] / 10000, 1)
            institution["sell_amt"] = round(institution["sell_amt"] / 10000, 1)
            institution["net_amt"] = round(
                institution["buy_amt"] - institution["sell_amt"], 1)

        return {"records": records, "seats": seats, "institution": institution}

    # ------------------------------------------------------------------
    # Data type: 全市场龙虎榜
    # ------------------------------------------------------------------

    def get_daily_dragon_tiger(
        self, trade_date: str = "", min_net_buy: float | None = None
    ) -> dict:
        """Get daily market-wide dragon tiger board summary."""
        if not trade_date:
            trade_date = datetime.now().strftime("%Y-%m-%d")
        data = self._datacenter_query(
            "RPT_DAILYBILLBOARD_DETAILSNEW",
            filter_str=f"(TRADE_DATE>='{trade_date}')(TRADE_DATE<='{trade_date}')",
            page_size=500,
            sort_columns="BILLBOARD_NET_AMT", sort_types="-1",
        )
        stocks = []
        for row in data:
            net_buy = (row.get("BILLBOARD_NET_AMT") or 0) / 10000
            if min_net_buy is not None and net_buy < min_net_buy:
                continue
            stocks.append({
                "code": row.get("SECURITY_CODE", ""),
                "name": row.get("SECURITY_NAME_ABBR", ""),
                "reason": row.get("EXPLANATION", ""),
                "close": row.get("CLOSE_PRICE", 0),
                "change_pct": round(float(row.get("CHANGE_RATE") or 0), 2),
                "net_buy_wan": round(net_buy, 1),
                "buy_wan": round((row.get("BILLBOARD_BUY_AMT") or 0) / 10000, 1),
                "sell_wan": round((row.get("BILLBOARD_SELL_AMT") or 0) / 10000, 1),
                "turnover_pct": round(float(row.get("TURNOVERRATE") or 0), 2),
            })
        return {"date": trade_date, "total": len(stocks), "stocks": stocks}

    # ------------------------------------------------------------------
    # Data type: 融资融券 (Margin Trading)
    # ------------------------------------------------------------------

    def get_margin_trading(self, code: str, page_size: int = 30) -> list[dict]:
        """Get margin trading data."""
        code = normalize_stock_code(code)
        data = self._datacenter_query(
            "RPTA_WEB_RZRQ_GGMX",
            filter_str=f'(SCODE="{code}")',
            page_size=page_size,
            sort_columns="DATE", sort_types="-1",
        )
        rows = []
        for row in data:
            rows.append({
                "date": str(row.get("DATE", ""))[:10],
                "rzye": row.get("RZYE", 0),       # 融资余额(元)
                "rzmre": row.get("RZMRE", 0),      # 融资买入额
                "rzche": row.get("RZCHE", 0),      # 融资偿还额
                "rqye": row.get("RQYE", 0),        # 融券余额(元)
                "rqmcl": row.get("RQMCL", 0),      # 融券卖出量
                "rqchl": row.get("RQCHL", 0),      # 融券偿还量
                "rzrqye": row.get("RZRQYE", 0),    # 融资融券余额合计
            })
        return rows

    def get_block_trade(self, code: str, page_size: int = 20) -> list[dict]:
        """Get block trade records."""
        code = normalize_stock_code(code)
        data = self._datacenter_query(
            "RPT_DATA_BLOCKTRADE",
            filter_str=f'(SECURITY_CODE="{code}")',
            page_size=page_size,
            sort_columns="TRADE_DATE", sort_types="-1",
        )
        rows = []
        for row in data:
            close = row.get("CLOSE_PRICE") or 0
            deal_price = row.get("DEAL_PRICE") or 0
            premium = ((deal_price / close - 1) * 100) if close else 0
            rows.append({
                "date": str(row.get("TRADE_DATE", ""))[:10],
                "price": deal_price,
                "close": close,
                "premium_pct": round(premium, 2),
                "vol": row.get("DEAL_VOLUME", 0),
                "amount": row.get("DEAL_AMT", 0),
                "buyer": row.get("BUYER_NAME", ""),
                "seller": row.get("SELLER_NAME", ""),
            })
        return rows

    def get_holder_num_change(self, code: str, page_size: int = 10) -> list[dict]:
        """Get shareholder count change (quarterly)."""
        code = normalize_stock_code(code)
        data = self._datacenter_query(
            "RPT_HOLDERNUMLATEST",
            filter_str=f'(SECURITY_CODE="{code}")',
            page_size=page_size,
            sort_columns="END_DATE", sort_types="-1",
        )
        rows = []
        for row in data:
            rows.append({
                "date": str(row.get("END_DATE", ""))[:10],
                "holder_num": row.get("HOLDER_NUM", 0),
                "change_num": row.get("HOLDER_NUM_CHANGE", 0),
                "change_ratio": row.get("HOLDER_NUM_RATIO", 0),  # 环比%
                "avg_shares": row.get("AVG_FREE_SHARES", 0),     # 户均持股
            })
        return rows

    def get_dividend(self, code: str, page_size: int = 20) -> list[dict]:
        """Get dividend history."""
        code = normalize_stock_code(code)
        data = self._datacenter_query(
            "RPT_SHAREBONUS_DET",
            filter_str=f'(SECURITY_CODE="{code}")',
            page_size=page_size,
            sort_columns="EX_DIVIDEND_DATE", sort_types="-1",
        )
        rows = []
        for row in data:
            rows.append({
                "date": str(row.get("EX_DIVIDEND_DATE", ""))[:10],
                "bonus_rmb": row.get("PRETAX_BONUS_RMB", 0),    # 每股派息(税前)
                "transfer_ratio": row.get("TRANSFER_RATIO", 0),  # 每10股转增
                "bonus_ratio": row.get("BONUS_RATIO", 0),        # 每10股送股
                "plan": row.get("ASSIGN_PROGRESS", ""),           # 进度
            })
        return rows

    get_block_trade = get_block_trade
    get_holder_num_change = get_holder_num_change
    get_dividend = get_dividend
    get_margin_trading = get_margin_trading
    get_dragon_tiger = get_dragon_tiger
    get_daily_dragon_tiger = get_daily_dragon_tiger
```

- [ ] **Step 1: Create the file**

Create `stock_data/data_provider/fetchers/eastmoney_fetcher.py` with the above code.

- [ ] **Step 2: Verify it loads**

Run: `python -c "from stock_data.data_provider.fetchers.eastmoney_fetcher import EastMoneyFetcher; f = EastMoneyFetcher(); print(f.name, f.priority)"`

- [ ] **Step 3: Commit**

```bash
git add stock_data/data_provider/fetchers/eastmoney_fetcher.py
git commit -m "feat: add EastMoneyFetcher with datacenter domain methods

Supports: dragon-tiger, margin-trading, block-trade, holder-num, dividend
via eastmoney datacenter unified query API.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 3: Add API Response Schemas

**File:** `stock_data/api/schemas.py`

- [ ] **Step 1: Add 5 new response models**

Add after the existing schema classes:

```python
class DragonTigerSeat(BaseModel):
    """龙虎榜席位"""
    name: str = Field(default="", description="营业部名称")
    buy_wan: float = Field(default=0, description="买入金额(万元)")
    sell_wan: float = Field(default=0, description="卖出金额(万元)")
    net_wan: float = Field(default=0, description="净买入(万元)")


class DragonTigerInstitution(BaseModel):
    """机构买卖统计"""
    buy_amt: float = Field(default=0, description="机构买入(万元)")
    sell_amt: float = Field(default=0, description="机构卖出(万元)")
    net_amt: float = Field(default=0, description="机构净买入(万元)")


class DragonTigerRecord(BaseModel):
    """上榜记录"""
    date: str = Field(default="", description="上榜日期")
    reason: str = Field(default="", description="上榜原因")
    net_buy_wan: float = Field(default=0, description="净买入(万元)")
    turnover_pct: float = Field(default=0, description="换手率(%)")


class DragonTigerResponse(BaseModel):
    """个股龙虎榜响应"""
    code: str = Field(description="股票代码")
    name: str = Field(default="", description="股票名称")
    records: list[DragonTigerRecord] = Field(default_factory=list)
    seats: dict[str, list[DragonTigerSeat]] = Field(default_factory=dict)
    institution: DragonTigerInstitution = Field(default_factory=DragonTigerInstitution)
    source: str = Field(default="eastmoney")


class DailyDragonTigerStock(BaseModel):
    """全市场龙虎榜个股"""
    code: str = Field(description="股票代码")
    name: str = Field(default="", description="股票名称")
    reason: str = Field(default="", description="上榜原因")
    close: float = Field(default=0, description="收盘价")
    change_pct: float = Field(default=0, description="涨跌幅(%)")
    net_buy_wan: float = Field(default=0, description="净买入(万元)")
    buy_wan: float = Field(default=0, description="买入金额(万元)")
    sell_wan: float = Field(default=0, description="卖出金额(万元)")
    turnover_pct: float = Field(default=0, description="换手率(%)")


class DailyDragonTigerResponse(BaseModel):
    """全市场龙虎榜响应"""
    date: str = Field(description="交易日期")
    total: int = Field(default=0, description="上榜总数")
    stocks: list[DailyDragonTigerStock] = Field(default_factory=list)
    source: str = Field(default="eastmoney")


class MarginTradingRecord(BaseModel):
    """融资融券记录"""
    date: str = Field(default="", description="日期")
    rzye: float = Field(default=0, description="融资余额(元)")
    rzmre: float = Field(default=0, description="融资买入额(元)")
    rzche: float = Field(default=0, description="融资偿还额(元)")
    rqye: float = Field(default=0, description="融券余额(元)")
    rqmcl: float = Field(default=0, description="融券卖出量")
    rqchl: float = Field(default=0, description="融券偿还量")
    rzrqye: float = Field(default=0, description="融资融券余额合计(元)")


class MarginTradingResponse(BaseModel):
    """融资融券响应"""
    code: str = Field(description="股票代码")
    name: str = Field(default="", description="股票名称")
    records: list[MarginTradingRecord] = Field(default_factory=list)
    source: str = Field(default="eastmoney")


class BlockTradeRecord(BaseModel):
    """大宗交易记录"""
    date: str = Field(default="", description="交易日期")
    price: float = Field(default=0, description="成交价")
    close: float = Field(default=0, description="收盘价")
    premium_pct: float = Field(default=0, description="溢价率(%)")
    vol: float = Field(default=0, description="成交量(股)")
    amount: float = Field(default=0, description="成交额(元)")
    buyer: str = Field(default="", description="买方营业部")
    seller: str = Field(default="", description="卖方营业部")


class BlockTradeResponse(BaseModel):
    """大宗交易响应"""
    code: str = Field(description="股票代码")
    name: str = Field(default="", description="股票名称")
    records: list[BlockTradeRecord] = Field(default_factory=list)
    source: str = Field(default="eastmoney")


class HolderNumRecord(BaseModel):
    """股东户数记录"""
    date: str = Field(default="", description="报告期")
    holder_num: int = Field(default=0, description="股东户数")
    change_num: int = Field(default=0, description="户数变化")
    change_ratio: float = Field(default=0, description="环比变化(%)")
    avg_shares: float = Field(default=0, description="户均持股")


class HolderNumResponse(BaseModel):
    """股东户数变化响应"""
    code: str = Field(description="股票代码")
    name: str = Field(default="", description="股票名称")
    records: list[HolderNumRecord] = Field(default_factory=list)
    source: str = Field(default="eastmoney")


class DividendRecord(BaseModel):
    """分红送转记录"""
    date: str = Field(default="", description="除权除息日")
    bonus_rmb: float = Field(default=0, description="每股派息(税前)")
    transfer_ratio: float = Field(default=0, description="每10股转增")
    bonus_ratio: float = Field(default=0, description="每10股送股")
    plan: str = Field(default="", description="进度")


class DividendResponse(BaseModel):
    """分红送转响应"""
    code: str = Field(description="股票代码")
    name: str = Field(default="", description="股票名称")
    records: list[DividendRecord] = Field(default_factory=list)
    source: str = Field(default="eastmoney")
```

- [ ] **Step 2: Verify**

Run: `python -c "from stock_data.api.schemas import DragonTigerResponse, MarginTradingResponse, BlockTradeResponse, HolderNumResponse, DividendResponse; print('OK')"`

- [ ] **Step 3: Commit**

```bash
git add stock_data/api/schemas.py
git commit -m "feat: add response schemas for Phase 2 (dragon-tiger/margin/block-trade/holder-num/dividend)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 4: Register EastMoneyFetcher & Add REST Endpoints

**File:** `stock_data/api/routes.py`

- [ ] **Step 1: Add import for EastMoneyFetcher and new schemas**

At the top of routes.py:

```python
from ..data_provider.fetchers.eastmoney_fetcher import EastMoneyFetcher
```

- [ ] **Step 2: Register EastMoneyFetcher in get_manager()**

After the TencentFetcher block in `get_manager()`, add:

```python
eastmoney = EastMoneyFetcher()
if eastmoney.is_available():
    _manager.add_fetcher(eastmoney)
    logger.info("EastMoneyFetcher added")
```

- [ ] **Step 3: Add 5 new endpoint functions**

Add after existing endpoints:

```python
@router.get(
    "/stocks/{stock_code}/dragon-tiger",
    response_model=DragonTigerResponse,
    tags=["stocks"],
)
def get_dragon_tiger(
    stock_code: str = Path(max_length=20, description="Stock code"),
    trade_date: str = Query(default="", description="Trade date (YYYY-MM-DD), empty=today"),
    look_back: int = Query(default=30, ge=1, le=365, description="Look-back days"),
) -> DragonTigerResponse:
    """Get dragon tiger board data for a stock."""
    try:
        manager = get_manager()
        fetcher = manager.get_fetcher("EastMoneyFetcher")
        if not fetcher:
            raise HTTPException(status_code=503, detail={"error": "unavailable", "message": "EastMoneyFetcher not registered"})
        data = fetcher.get_dragon_tiger(stock_code, trade_date, look_back)
        stock_name = stock_cache.get_stock_name(stock_code, manager=manager)
        records = [DragonTigerRecord(**r) for r in data["records"]]
        seats = {
            "buy": [DragonTigerSeat(**s) for s in data["seats"]["buy"]],
            "sell": [DragonTigerSeat(**s) for s in data["seats"]["sell"]],
        }
        return DragonTigerResponse(
            code=stock_code, name=stock_name or "",
            records=records, seats=seats,
            institution=DragonTigerInstitution(**data["institution"]),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": "internal_error", "message": str(e)}) from e


@router.get(
    "/dragon-tiger/daily",
    response_model=DailyDragonTigerResponse,
    tags=["dragon-tiger"],
)
def get_daily_dragon_tiger(
    trade_date: str = Query(default="", description="Trade date (YYYY-MM-DD)"),
    min_net_buy: float | None = Query(default=None, description="Min net buy (万元)"),
) -> DailyDragonTigerResponse:
    """Get daily market-wide dragon tiger board."""
    try:
        manager = get_manager()
        fetcher = manager.get_fetcher("EastMoneyFetcher")
        if not fetcher:
            raise HTTPException(status_code=503, detail={"error": "unavailable", "message": "EastMoneyFetcher not registered"})
        data = fetcher.get_daily_dragon_tiger(trade_date, min_net_buy)
        stocks = [DailyDragonTigerStock(**s) for s in data["stocks"]]
        return DailyDragonTigerResponse(date=data["date"], total=data["total"], stocks=stocks)
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": "internal_error", "message": str(e)}) from e


@router.get(
    "/stocks/{stock_code}/margin",
    response_model=MarginTradingResponse,
    tags=["stocks"],
)
def get_margin(
    stock_code: str = Path(max_length=20),
    page_size: int = Query(default=30, ge=1, le=100),
) -> MarginTradingResponse:
    """Get margin trading data for a stock."""
    try:
        manager = get_manager()
        fetcher = manager.get_fetcher("EastMoneyFetcher")
        if not fetcher:
            raise HTTPException(status_code=503, detail={"error": "unavailable", "message": "EastMoneyFetcher not registered"})
        data = fetcher.get_margin_trading(stock_code, page_size)
        stock_name = stock_cache.get_stock_name(stock_code, manager=manager)
        records = [MarginTradingRecord(**r) for r in data]
        return MarginTradingResponse(code=stock_code, name=stock_name or "", records=records)
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": "internal_error", "message": str(e)}) from e


@router.get(
    "/stocks/{stock_code}/block-trade",
    response_model=BlockTradeResponse,
    tags=["stocks"],
)
def get_block_trade(
    stock_code: str = Path(max_length=20),
    page_size: int = Query(default=20, ge=1, le=100),
) -> BlockTradeResponse:
    """Get block trade records for a stock."""
    try:
        manager = get_manager()
        fetcher = manager.get_fetcher("EastMoneyFetcher")
        if not fetcher:
            raise HTTPException(status_code=503, detail={"error": "unavailable", "message": "EastMoneyFetcher not registered"})
        data = fetcher.get_block_trade(stock_code, page_size)
        stock_name = stock_cache.get_stock_name(stock_code, manager=manager)
        records = [BlockTradeRecord(**r) for r in data]
        return BlockTradeResponse(code=stock_code, name=stock_name or "", records=records)
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": "internal_error", "message": str(e)}) from e


@router.get(
    "/stocks/{stock_code}/holder-num",
    response_model=HolderNumResponse,
    tags=["stocks"],
)
def get_holder_num(
    stock_code: str = Path(max_length=20),
    page_size: int = Query(default=10, ge=1, le=50),
) -> HolderNumResponse:
    """Get shareholder count change for a stock."""
    try:
        manager = get_manager()
        fetcher = manager.get_fetcher("EastMoneyFetcher")
        if not fetcher:
            raise HTTPException(status_code=503, detail={"error": "unavailable", "message": "EastMoneyFetcher not registered"})
        data = fetcher.get_holder_num_change(stock_code, page_size)
        stock_name = stock_cache.get_stock_name(stock_code, manager=manager)
        records = [HolderNumRecord(**r) for r in data]
        return HolderNumResponse(code=stock_code, name=stock_name or "", records=records)
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": "internal_error", "message": str(e)}) from e


@router.get(
    "/stocks/{stock_code}/dividend",
    response_model=DividendResponse,
    tags=["stocks"],
)
def get_dividend(
    stock_code: str = Path(max_length=20),
    page_size: int = Query(default=20, ge=1, le=100),
) -> DividendResponse:
    """Get dividend history for a stock."""
    try:
        manager = get_manager()
        fetcher = manager.get_fetcher("EastMoneyFetcher")
        if not fetcher:
            raise HTTPException(status_code=503, detail={"error": "unavailable", "message": "EastMoneyFetcher not registered"})
        data = fetcher.get_dividend(stock_code, page_size)
        stock_name = stock_cache.get_stock_name(stock_code, manager=manager)
        records = [DividendRecord(**r) for r in data]
        return DividendResponse(code=stock_code, name=stock_name or "", records=records)
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": "internal_error", "message": str(e)}) from e
```

- [ ] **Step 4: Verify**

Run: `python -c "from stock_data.api.routes import get_dragon_tiger, get_margin, get_block_trade, get_holder_num, get_dividend; print('Routes OK')"`
Then: `python -c "from stock_data.api.routes import get_manager; m = get_manager(); print([f.name for f in m.fetchers])"`

- [ ] **Step 5: Commit**

```bash
git add stock_data/api/routes.py
git commit -m "feat: add 5 REST endpoints for Phase 2 (dragon-tiger/margin/block-trade/holder-num/dividend)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 5: Write Unit Tests

**File:** `tests/test_eastmoney_fetcher.py`

- [ ] **Step 1: Create test file**

```python
"""
Unit tests for EastMoneyFetcher.
"""
import pytest
from unittest.mock import MagicMock, patch
from stock_data.data_provider.fetchers.eastmoney_fetcher import EastMoneyFetcher
from stock_data.data_provider.base import DataCapability


class TestEastMoneyFetcherBasics:
    def test_name(self):
        f = EastMoneyFetcher()
        assert f.name == "EastMoneyFetcher"

    def test_priority(self):
        f = EastMoneyFetcher()
        assert f.priority == 6

    def test_is_available(self):
        f = EastMoneyFetcher()
        assert f.is_available() is True

    def test_capabilities(self):
        f = EastMoneyFetcher()
        assert DataCapability.DRAGON_TIGER in f.supported_data_types
        assert DataCapability.MARGIN_TRADING in f.supported_data_types
        assert DataCapability.BLOCK_TRADE in f.supported_data_types
        assert DataCapability.HOLDER_NUM in f.supported_data_types
        assert DataCapability.DIVIDEND in f.supported_data_types


class TestDatacenterQuery:
    def setup_method(self):
        self.fetcher = EastMoneyFetcher()

    @patch("stock_data.data_provider.fetchers.eastmoney_fetcher.requests.get")
    def test_query_returns_data(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "result": {"data": [{"SECURITY_CODE": "600519", "SECURITY_NAME_ABBR": "贵州茅台"}]}
        }
        mock_get.return_value = mock_response

        result = self.fetcher._datacenter_query("RPT_TEST", filter_str='(SECURITY_CODE="600519")')
        assert len(result) == 1
        assert result[0]["SECURITY_CODE"] == "600519"

    @patch("stock_data.data_provider.fetchers.eastmoney_fetcher.requests.get")
    def test_query_returns_empty_on_error(self, mock_get):
        mock_get.side_effect = Exception("Network error")
        result = self.fetcher._datacenter_query("RPT_TEST")
        assert result == []

    @patch("stock_data.data_provider.fetchers.eastmoney_fetcher.requests.get")
    def test_query_returns_empty_on_null_result(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = {"result": None}
        mock_get.return_value = mock_response
        result = self.fetcher._datacenter_query("RPT_TEST")
        assert result == []


class TestMarginTrading:
    def setup_method(self):
        self.fetcher = EastMoneyFetcher()

    @patch.object(EastMoneyFetcher, "_datacenter_query")
    def test_get_margin_trading_returns_records(self, mock_query):
        mock_query.return_value = [
            {"DATE": "2026-05-20T00:00:00", "RZYE": 100000000, "RZMRE": 5000000,
             "RZCHE": 3000000, "RQYE": 2000000, "RQMCL": 1000, "RQCHL": 500,
             "RZRQYE": 102000000}
        ]
        result = self.fetcher.get_margin_trading("600519")
        assert len(result) == 1
        assert result[0]["date"] == "2026-05-20"
        assert result[0]["rzye"] == 100000000

class TestBlockTrade:
    def setup_method(self):
        self.fetcher = EastMoneyFetcher()

    @patch.object(EastMoneyFetcher, "_datacenter_query")
    def test_get_block_trade_returns_records(self, mock_query):
        mock_query.return_value = [
            {"TRADE_DATE": "2026-05-20T00:00:00", "DEAL_PRICE": 100.0,
             "CLOSE_PRICE": 98.0, "DEAL_VOLUME": 50000, "DEAL_AMT": 5000000,
             "BUYER_NAME": "机构专用", "SELLER_NAME": "中信证券"}
        ]
        result = self.fetcher.get_block_trade("600519")
        assert len(result) == 1
        assert result[0]["date"] == "2026-05-20"
        assert result[0]["premium_pct"] > 0  # premium when deal > close


class TestHolderNum:
    def setup_method(self):
        self.fetcher = EastMoneyFetcher()

    @patch.object(EastMoneyFetcher, "_datacenter_query")
    def test_get_holder_num_returns_records(self, mock_query):
        mock_query.return_value = [
            {"END_DATE": "2026-03-31T00:00:00", "HOLDER_NUM": 150000,
             "HOLDER_NUM_CHANGE": -5000, "HOLDER_NUM_RATIO": -3.2,
             "AVG_FREE_SHARES": 8000.0}
        ]
        result = self.fetcher.get_holder_num_change("600519")
        assert len(result) == 1
        assert result[0]["date"] == "2026-03-31"
        assert result[0]["change_ratio"] == -3.2


class TestDividend:
    def setup_method(self):
        self.fetcher = EastMoneyFetcher()

    @patch.object(EastMoneyFetcher, "_datacenter_query")
    def test_get_dividend_returns_records(self, mock_query):
        mock_query.return_value = [
            {"EX_DIVIDEND_DATE": "2025-06-19T00:00:00", "PRETAX_BONUS_RMB": 21.91,
             "TRANSFER_RATIO": 0, "BONUS_RATIO": 0, "ASSIGN_PROGRESS": "实施完成"}
        ]
        result = self.fetcher.get_dividend("600519")
        assert len(result) == 1
        assert result[0]["date"] == "2025-06-19"
        assert result[0]["bonus_rmb"] == 21.91


class TestHistoricalNotSupported:
    def test_fetch_raw_data_raises(self):
        from stock_data.data_provider.base import DataFetchError
        f = EastMoneyFetcher()
        with pytest.raises(DataFetchError, match="does not support historical"):
            f._fetch_raw_data("600519", "2026-01-01", "2026-05-01")

    def test_normalize_data_raises(self):
        from stock_data.data_provider.base import DataFetchError
        import pandas as pd
        f = EastMoneyFetcher()
        with pytest.raises(DataFetchError, match="does not support historical"):
            f._normalize_data(pd.DataFrame(), "600519")
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/test_eastmoney_fetcher.py -v --tb=short`
Expected: All tests pass

- [ ] **Step 3: Commit**

```bash
git add tests/test_eastmoney_fetcher.py
git commit -m "test: add EastMoneyFetcher unit tests

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 6: Full Integration Test

- [ ] **Step 1: Run full test suite**

```bash
pytest tests/ -v --tb=short --ignore=tests/test_providers.py
```

- [ ] **Step 2: Verify Tencent tests still pass**

```bash
pytest tests/test_tencent_fetcher.py tests/test_eastmoney_fetcher.py -v
```

- [ ] **Step 3: Commit any fixes if needed**

---

## Self-Review Checklist

1. **Spec coverage:** Phase 2 spec requires dragon-tiger/margin/block-trade/holder-num/dividend. All 5 data types covered in Task 2 with dedicated methods.
2. **Placeholder scan:** No TBD/TODO. All code is concrete.
3. **Type consistency:** Method names match across fetcher, routes, and schemas.
