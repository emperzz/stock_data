# Phase 4: Fundamentals Layer (EastMoney ReportAPI + CninfoFetcher) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add EastMoney 研报(reports) and 巨潮公告(announcements) data access

**Architecture:** Extend `eastmoney_fetcher.py` with reportapi domain methods (研报列表 + PDF下载). Create `cninfo_fetcher.py` for 巨潮公告. Add DataCapability flags RESEARCH_REPORT/ANNOUNCEMENT, register in manager, expose REST APIs.

**Tech Stack:** requests

---

## File Structure

```
stock_data/
├── data_provider/
│   ├── base.py                              # Modify: add RESEARCH_REPORT, ANNOUNCEMENT flags
│   └── fetchers/
│       ├── eastmoney_fetcher.py             # Modify: add reportapi domain methods
│       └── cninfo_fetcher.py                # Create: 巨潮公告 fetcher
├── api/
│   ├── schemas.py                           # Modify: add report/announcement models
│   └── routes.py                            # Modify: add 3 REST endpoints
└── tests/
    ├── test_eastmoney_fetcher.py            # Modify: add report tests
    └── test_cninfo_fetcher.py               # Create: cninfo unit tests
```

---

## REST API 清单

| 端点 | 方法 | 说明 |
|------|------|------|
| `GET /stocks/{code}/reports` | GET | 研报列表（含评级/3年EPS预测） |
| `GET /stocks/{code}/reports/{report_id}/pdf` | GET | 研报PDF下载（返回文件路径或404） |
| `GET /stocks/{code}/announcements` | GET | 公告检索 |

---

### Task 1: Add DataCapability Flags

**File:** `stock_data/data_provider/base.py`

Add after NORTH_FLOW:
```python
RESEARCH_REPORT = auto()  # 研报
ANNOUNCEMENT = auto()     # 公告
```

Verify: `python -c "from stock_data.data_provider.base import DataCapability; print(DataCapability.RESEARCH_REPORT, DataCapability.ANNOUNCEMENT)"`
Commit: "feat: add DataCapability flags for Phase 4 (research-report/announcement)"

---

### Task 2: Extend EastMoneyFetcher with ReportAPI Methods

**File:** `stock_data/data_provider/fetchers/eastmoney_fetcher.py`

**A. Add RESEARCH_REPORT to supported_data_types:**
```python
    | DataCapability.RESEARCH_REPORT
```

**B. Add reportapi domain methods:**

```python
REPORT_API = "https://reportapi.eastmoney.com/report/list"
PDF_TPL = "https://pdf.dfcfw.com/pdf/H3_{info_code}_1.pdf"

def get_reports(self, code: str, max_pages: int = 5) -> list[dict]:
    """Get research report list for a stock.

    Returns list of dicts: title, publish_date, org, info_code, rating,
                            predict_eps_this, predict_eps_next, predict_eps_next2
    """
    code = normalize_stock_code(code)
    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Referer": "https://data.eastmoney.com/"})
    all_records = []
    for page in range(1, max_pages + 1):
        params = {
            "industryCode": "*", "pageSize": "100", "industry": "*",
            "rating": "*", "ratingChange": "*",
            "beginTime": "2000-01-01", "endTime": "2030-01-01",
            "pageNo": str(page), "fields": "", "qType": "0",
            "orgCode": "", "code": code, "rcode": "",
            "p": str(page), "pageNum": str(page), "pageNumber": str(page),
        }
        try:
            r = session.get(self.REPORT_API, params=params, timeout=30)
            d = r.json()
            rows = d.get("data") or []
            if not rows:
                break
            all_records.extend(rows)
            if page >= (d.get("TotalPage", 1) or 1):
                break
        except Exception as e:
            logger.warning(f"[EastMoneyFetcher] reports failed page {page}: {e}")
            break
    return [
        {
            "title": r.get("title", ""),
            "publish_date": (r.get("publishDate") or "")[:10],
            "org": r.get("orgSName", ""),
            "info_code": r.get("infoCode", ""),
            "rating": r.get("emRatingName", ""),
            "predict_eps_this": r.get("predictThisYearEps"),
            "predict_eps_next": r.get("predictNextYearEps"),
            "predict_eps_next2": r.get("predictNextTwoYearEps"),
        }
        for r in all_records
    ]

def get_report_pdf_url(self, info_code: str) -> str | None:
    """Get PDF download URL for a report."""
    if not info_code:
        return None
    return self.PDF_TPL.format(info_code=info_code)

def download_report_pdf(self, info_code: str, target_dir: str = "./reports") -> str | None:
    """Download a report PDF. Returns local file path or None."""
    import re
    from pathlib import Path

    url = self.get_report_pdf_url(info_code)
    if not url:
        return None
    try:
        r = requests.get(url, headers={"User-Agent": UA, "Referer": "https://data.eastmoney.com/"}, timeout=60)
        if r.status_code == 200 and len(r.content) >= 1024:
            target = Path(target_dir) / f"{info_code}.pdf"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(r.content)
            return str(target)
    except Exception as e:
        logger.warning(f"[EastMoneyFetcher] PDF download failed: {e}")
    return None
```

Verify: `python -c "from stock_data.data_provider.fetchers.eastmoney_fetcher import EastMoneyFetcher; f = EastMoneyFetcher(); print(hasattr(f, 'get_reports'), hasattr(f, 'download_report_pdf'))"`
Commit: "feat: add reportapi domain methods to EastMoneyFetcher"

---

### Task 3: Create CninfoFetcher

**File to create:** `stock_data/data_provider/fetchers/cninfo_fetcher.py`

```python
"""
巨潮公告 API fetcher.

API: https://www.cninfo.com.cn/new/hisAnnouncement/query
"""

import logging

import requests

from ..base import BaseFetcher, DataCapability, DataFetchError
from ..utils.normalize import normalize_stock_code

logger = logging.getLogger(__name__)

CNINFO_URL = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
CNINFO_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


class CninfoFetcher(BaseFetcher):
    """巨潮公告 API fetcher."""

    name = "CninfoFetcher"
    priority = 8
    supported_markets: set[str] = {"csi"}
    supported_data_types = DataCapability.ANNOUNCEMENT

    def is_available(self) -> bool:
        return True

    def _fetch_raw_data(self, stock_code, start_date, end_date, frequency="d", adjust=None):
        raise DataFetchError("CninfoFetcher does not support historical K-line data")

    def _normalize_data(self, df, stock_code):
        raise DataFetchError("CninfoFetcher does not support historical K-line data")

    def _org_id(self, code: str) -> str:
        """Build orgId for cninfo API."""
        if code.startswith("6"):
            return f"gssh0{code}"
        elif code.startswith(("8", "4")):
            return f"gsbj0{code}"
        else:
            return f"gssz0{code}"

    def get_announcements(self, code: str, page_size: int = 30) -> list[dict]:
        """Get announcement list for a stock.

        Returns list of dicts: title, type, date, url
        """
        code = normalize_stock_code(code)
        org_id = self._org_id(code)
        payload = {
            "stock": f"{code},{org_id}",
            "tabName": "fulltext",
            "pageSize": str(page_size),
            "pageNum": "1",
            "column": "", "category": "", "plate": "",
            "seDate": "", "searchkey": "", "secid": "",
            "sortName": "", "sortType": "", "isHLtitle": "true",
        }
        headers = {
            "User-Agent": CNINFO_UA,
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": "https://www.cninfo.com.cn/new/disclosure",
            "Origin": "https://www.cninfo.com.cn",
        }
        try:
            r = requests.post(CNINFO_URL, data=payload, headers=headers, timeout=15)
            d = r.json()
            rows = []
            for item in d.get("announcements", []) or []:
                rows.append({
                    "title": item.get("announcementTitle", ""),
                    "type": item.get("announcementTypeName", ""),
                    "date": str(item.get("announcementTime", ""))[:10],
                    "url": f"https://www.cninfo.com.cn/new/disclosure/detail?annoId={item.get('announcementId', '')}",
                })
            return rows
        except Exception as e:
            logger.warning(f"[CninfoFetcher] announcements failed: {e}")
            return []
```

Verify: `python -c "from stock_data.data_provider.fetchers.cninfo_fetcher import CninfoFetcher; f = CninfoFetcher(); print(f.name, f.priority)"`
Commit: "feat: add CninfoFetcher for corporate announcements"

---

### Task 4: Add API Schemas

**File:** `stock_data/api/schemas.py`

Append:
```python
class ReportRecord(BaseModel):
    """研报记录"""
    title: str = Field(default="", description="标题")
    publish_date: str = Field(default="", description="发布日期")
    org: str = Field(default="", description="研究机构")
    info_code: str = Field(default="", description="PDF编号")
    rating: str = Field(default="", description="评级")
    predict_eps_this: float | None = Field(default=None, description="今年EPS预测")
    predict_eps_next: float | None = Field(default=None, description="明年EPS预测")
    predict_eps_next2: float | None = Field(default=None, description="后年EPS预测")


class ReportResponse(BaseModel):
    """研报列表响应"""
    code: str = Field(description="股票代码")
    name: str = Field(default="", description="股票名称")
    reports: list[ReportRecord] = Field(default_factory=list)
    total: int = Field(default=0)
    source: str = Field(default="eastmoney")


class ReportPDFResponse(BaseModel):
    """研报PDF响应"""
    report_id: str = Field(description="info_code")
    download_path: str | None = Field(default=None, description="本地文件路径")
    url: str | None = Field(default=None, description="PDF URL")


class AnnouncementRecord(BaseModel):
    """公告记录"""
    title: str = Field(default="", description="标题")
    type: str = Field(default="", description="公告类型")
    date: str = Field(default="", description="发布日期")
    url: str = Field(default="", description="公告链接")


class AnnouncementResponse(BaseModel):
    """公告列表响应"""
    code: str = Field(description="股票代码")
    name: str = Field(default="", description="股票名称")
    announcements: list[AnnouncementRecord] = Field(default_factory=list)
    total: int = Field(default=0)
    source: str = Field(default="cninfo")
```

Verify: `python -c "from stock_data.api.schemas import ReportResponse, AnnouncementResponse; print('OK')"`
Commit: "feat: add response schemas for Phase 4 APIs"

---

### Task 5: Register CninfoFetcher & Add REST Endpoints

**File:** `stock_data/api/routes.py`

**A. Add imports:**
```python
from ..data_provider.fetchers.cninfo_fetcher import CninfoFetcher
```
Import schemas: `ReportResponse, ReportRecord, ReportPDFResponse, AnnouncementResponse, AnnouncementRecord` (update existing schema imports)

**B. Register CninfoFetcher in get_manager()** after ThsFetcher:
```python
cninfo = CninfoFetcher()
if cninfo.is_available():
    _manager.add_fetcher(cninfo)
    logger.info("CninfoFetcher added")
```

**C. Add 3 endpoints:**

```python
@router.get("/stocks/{stock_code}/reports", response_model=ReportResponse, tags=["stocks"])
def get_reports(stock_code: str = Path(max_length=20), max_pages: int = Query(default=3, ge=1, le=10)) -> ReportResponse:
    try:
        manager = get_manager()
        fetcher = manager.get_fetcher("EastMoneyFetcher")
        if not fetcher: raise HTTPException(status_code=503, detail={"error": "unavailable"})
        data = fetcher.get_reports(stock_code, max_pages)
        stock_name = stock_cache.get_stock_name(stock_code, manager=manager)
        reports = [ReportRecord(**r) for r in data]
        return ReportResponse(code=stock_code, name=stock_name or "", reports=reports, total=len(reports))
    except HTTPException: raise
    except Exception as e: raise HTTPException(status_code=500, detail={"error": "internal_error", "message": str(e)}) from e


@router.get("/stocks/{stock_code}/reports/{report_id}/pdf", response_model=ReportPDFResponse, tags=["stocks"])
def get_report_pdf(stock_code: str = Path(max_length=20), report_id: str = Path(description="info_code")):
    try:
        manager = get_manager()
        fetcher = manager.get_fetcher("EastMoneyFetcher")
        if not fetcher: raise HTTPException(status_code=503)
        url = fetcher.get_report_pdf_url(report_id)
        path = fetcher.download_report_pdf(report_id)
        return ReportPDFResponse(report_id=report_id, download_path=path, url=url)
    except HTTPException: raise
    except Exception as e: raise HTTPException(status_code=500, detail={"error": "internal_error", "message": str(e)}) from e


@router.get("/stocks/{stock_code}/announcements", response_model=AnnouncementResponse, tags=["stocks"])
def get_announcements(stock_code: str = Path(max_length=20), page_size: int = Query(default=30, ge=1, le=100)) -> AnnouncementResponse:
    try:
        manager = get_manager()
        fetcher = manager.get_fetcher("CninfoFetcher")
        if not fetcher: raise HTTPException(status_code=503)
        data = fetcher.get_announcements(stock_code, page_size)
        stock_name = stock_cache.get_stock_name(stock_code, manager=manager)
        announcements = [AnnouncementRecord(**r) for r in data]
        return AnnouncementResponse(code=stock_code, name=stock_name or "", announcements=announcements, total=len(announcements))
    except HTTPException: raise
    except Exception as e: raise HTTPException(status_code=500, detail={"error": "internal_error", "message": str(e)}) from e
```

Verify: `python -c "from stock_data.api.routes import get_manager; m = get_manager(); print([f.name for f in m.fetchers])"`
Commit: "feat: register CninfoFetcher and add 3 Phase 4 REST endpoints"

---

### Task 6: Write Unit Tests

**A. Create `tests/test_cninfo_fetcher.py`:**
```python
"""Unit tests for CninfoFetcher."""
import pytest
from unittest.mock import MagicMock, patch
from stock_data.data_provider.fetchers.cninfo_fetcher import CninfoFetcher
from stock_data.data_provider.base import DataCapability

class TestCninfoFetcherBasics:
    def test_name(self): f = CninfoFetcher(); assert f.name == "CninfoFetcher"
    def test_priority(self): f = CninfoFetcher(); assert f.priority == 8
    def test_capabilities(self):
        f = CninfoFetcher()
        assert DataCapability.ANNOUNCEMENT in f.supported_data_types
    def test_org_id_sh(self): f = CninfoFetcher(); assert f._org_id("600519") == "gssh0600519"
    def test_org_id_sz(self): f = CninfoFetcher(); assert f._org_id("000001") == "gssz0000001"
    def test_org_id_bj(self): f = CninfoFetcher(); assert f._org_id("832000") == "gsbj0832000"

class TestAnnouncements:
    def setup_method(self): self.fetcher = CninfoFetcher()
    @patch("stock_data.data_provider.fetchers.cninfo_fetcher.requests.post")
    def test_returns_records(self, mock_post):
        mock_response = MagicMock()
        mock_response.json.return_value = {"announcements": [
            {"announcementTitle": "Test", "announcementTypeName": "年度报告",
             "announcementTime": 1716768000000, "announcementId": "123"}
        ]}
        mock_post.return_value = mock_response
        result = self.fetcher.get_announcements("600519")
        assert len(result) == 1
        assert result[0]["title"] == "Test"
```

**B. Add report test to `tests/test_eastmoney_fetcher.py`:**
```python
class TestReports:
    def setup_method(self): self.fetcher = EastMoneyFetcher()
    @patch("stock_data.data_provider.fetchers.eastmoney_fetcher.requests.Session.get")
    def test_returns_records(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [{"title": "Test Report", "publishDate": "2026-05-20T00:00:00",
                       "orgSName": "中信证券", "infoCode": "ABC123",
                       "emRatingName": "买入", "predictThisYearEps": 3.5}],
            "TotalPage": 1
        }
        mock_get.return_value = mock_response
        result = self.fetcher.get_reports("600519", max_pages=1)
        assert len(result) == 1
        assert result[0]["title"] == "Test Report"
        assert result[0]["rating"] == "买入"

    def test_pdf_url(self):
        f = EastMoneyFetcher()
        url = f.get_report_pdf_url("ABC123")
        assert "ABC123" in url
```

Run combined tests: `pytest tests/test_cninfo_fetcher.py tests/test_ths_fetcher.py tests/test_eastmoney_fetcher.py tests/test_tencent_fetcher.py -v --tb=short`
Commit tests.

---

### Task 7: Integration Test & Push

Run: `pytest tests/test_cninfo_fetcher.py tests/test_ths_fetcher.py tests/test_eastmoney_fetcher.py tests/test_tencent_fetcher.py -v`
Verify manager, push.
