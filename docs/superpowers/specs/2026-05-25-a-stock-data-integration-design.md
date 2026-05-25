# a-stock-data 数据能力接入设计

**日期**: 2026-05-25
**状态**: 已批准
**优先级**: C (行情增强) > D (资金面) > A (信号层) > B (基本面)

---

## 1. 背景与目标

本项目（stock_data）定位为多源聚合的数据网关，已集成 Tushare/Baostock/Akshare/Yfinance/Zhitu 五类数据源，提供统一 REST API。

a-stock-data 项目覆盖 7 层数据架构（行情/研报/信号/资金面/新闻/基础数据/公告），共 28 个端点。本设计文档规划如何将其中高价值但本项目缺失的数据能力逐步接入。

**核心原则**:
- 保持 HTTP-only 架构风格，暂不引入 mootdx (TCP)
- 新数据源按数据提供方归为独立 fetcher 文件
- 所有数据能力均暴露为 REST API
- 接入阶段: C → D → A → B

---

## 2. 架构决策

### 2.1 新增 fetcher 文件清单

```
data_provider/fetchers/
├── baostock_fetcher.py      ✅ 已有
├── akshare_fetcher.py       ✅ 已有
├── tushare_fetcher.py       ✅ 已有
├── yfinance_fetcher.py      ✅ 已有
├── zhitu_fetcher.py         ✅ 已有
├── tencent_fetcher.py       🆕 腾讯财经（PE/PB/市值/涨跌停价/ETF/指数）
├── eastmoney_fetcher.py     🆕 东财全家桶（龙虎榜/融资融券/大宗/股东户数/分红/资金流/行业排名/研报）
└── ths_fetcher.py            🆕 同花顺（热点题材/北向资金/一致预期EPS）
└── cninfo_fetcher.py         🆕 巨潮（公告检索+下载）
```

### 2.2 EastMoneyFetcher 内部结构

东财数据来源分为三个域，合并为一个 fetcher 文件，通过内部方法组织：

| 域 | 数据类型 | 方法 |
|----|---------|------|
| datacenter | 龙虎榜/融资融券/大宗交易/股东户数/分红 | `get_dragon_tiger()`, `get_margin()`, `get_block_trade()`, `get_holder_num()`, `get_dividend()` |
| push2 | 资金流分钟级/行业板块排名 | `get_fund_flow_minute()`, `get_fund_flow_120d()`, `get_industry_ranking()` |
| reportapi | 研报列表/PDF下载/评级 | `get_reports()`, `download_report_pdf()` |

### 2.3 DataCapability 新增标志

```python
class DataCapability(Flag):
    # === 现有标志 ===
    HISTORICAL_DWM = auto()
    HISTORICAL_MIN = auto()
    REALTIME_QUOTE = auto()
    STOCK_LIST = auto()
    STOCK_NAME = auto()
    TRADE_CALENDAR = auto()
    STOCK_BOARD = auto()
    INDEX_QUOTE = auto()
    INDEX_HISTORICAL = auto()
    INDEX_INTRADAY = auto()
    STOCK_ZT_POOL = auto()

    # === 新增标志 ===
    DRAGON_TIGER = auto()       # 龙虎榜
    MARGIN_TRADING = auto()     # 融资融券
    BLOCK_TRADE = auto()        # 大宗交易
    HOLDER_NUM = auto()         # 股东户数变化
    DIVIDEND = auto()           # 分红送转
    FUND_FLOW = auto()          # 资金流
    HOT_TOPICS = auto()         # 热点题材
    NORTH_FLOW = auto()         # 北向资金
    RESEARCH_REPORT = auto()    # 研报
    ANNOUNCEMENT = auto()       # 公告
```

### 2.4 Fetcher 能力声明

| Fetcher | Markets | Capabilities |
|---------|---------|-------------|
| BaostockFetcher | csi | HISTORICAL_DWM \| HISTORICAL_MIN \| TRADE_CALENDAR \| INDEX_HISTORICAL |
| AkshareFetcher | csi, hk | HISTORICAL_DWM \| REALTIME_QUOTE \| STOCK_LIST \| STOCK_NAME \| TRADE_CALENDAR \| STOCK_BOARD \| INDEX_QUOTE \| INDEX_HISTORICAL \| INDEX_INTRADAY |
| TushareFetcher | csi | HISTORICAL_DWM \| REALTIME_QUOTE \| STOCK_LIST \| STOCK_NAME \| INDEX_HISTORICAL |
| YfinanceFetcher | us, csi, hk | HISTORICAL_DWM \| HISTORICAL_MIN \| REALTIME_QUOTE \| INDEX_HISTORICAL \| INDEX_QUOTE |
| ZhituFetcher | csi | REALTIME_QUOTE |
| TencentFetcher | csi, hk | REALTIME_QUOTE (增强字段) |
| EastMoneyFetcher | csi | DRAGON_TIGER \| MARGIN_TRADING \| BLOCK_TRADE \| HOLDER_NUM \| DIVIDEND \| FUND_FLOW \| STOCK_BOARD \| RESEARCH_REPORT |
| ThsFetcher | csi | HOT_TOPICS \| NORTH_FLOW \| STOCK_NAME |
| CninfoFetcher | csi | ANNOUNCEMENT |

---

## 3. 阶段规划

### 第一阶段: C (行情增强) — 腾讯财经

**目标**: 增强 `/stocks/{code}/quote` 字段，提供 PE/PB/市值/涨跌停价/ETF 支持

**新增文件**: `tencent_fetcher.py`

**增强字段**:
- `pe_ttm`: PE(TTM)
- `pe_static`: PE(静)
- `pb`: 市净率
- `mcap_yi`: 总市值(亿)
- `float_mcap_yi`: 流通市值(亿)
- `turnover_pct`: 换手率%
- `amplitude_pct`: 振幅%
- `limit_up`: 涨停价
- `limit_down`: 跌停价
- `vol_ratio`: 量比

**API 变更**: 现有 `/stocks/{code}/quote` 响应模型扩展字段，无需新增端点

---

### 第二阶段: D (资金面监控) — 东财数据中心

**目标**: 龙虎榜/融资融券/大宗交易/股东户数/分红

**新增文件**: `eastmoney_fetcher.py` (datacenter 域方法)

**REST API**:

| 端点 | 说明 |
|------|------|
| `GET /stocks/{code}/dragon-tiger` | 个股龙虎榜（含买卖席位/机构动向） |
| `GET /stocks/{code}/margin` | 融资融券明细 |
| `GET /stocks/{code}/block-trade` | 大宗交易记录 |
| `GET /stocks/{code}/holder-num` | 股东户数变化 |
| `GET /stocks/{code}/dividend` | 分红送转历史 |

**缓存策略**: SQLite，TTL 1天（股东户数/分红季度级更新）

---

### 第三阶段: A (信号层) — 东财push2 + 同花顺

**目标**: 资金流/行业排名/热点题材/北向资金/全市场龙虎榜

**新增/扩展**: `eastmoney_fetcher.py` (push2 域方法) + `ths_fetcher.py`

**REST API**:

| 端点 | 说明 |
|------|------|
| `GET /stocks/{code}/fund-flow` | 个股资金流（分钟级） |
| `GET /stocks/{code}/fund-flow/daily` | 120日资金流历史 |
| `GET /hot/topics` | 同花顺热点题材（含reason tags） |
| `GET /north-flow/realtime` | 北向资金分钟流向 |
| `GET /dragon-tiger/daily` | 全市场龙虎榜 |
| `GET /boards/industry/ranking` | 行业涨跌幅排名 |

**缓存策略**: SQLite，盘中资金流30秒/北向1分钟/热点5分钟

---

### 第四阶段: B (基本面) — 东财研报 + 巨潮公告

**目标**: 研报检索+PDF下载/公告检索

**新增/扩展**: `eastmoney_fetcher.py` (reportapi 域方法) + `cninfo_fetcher.py`

**REST API**:

| 端点 | 说明 |
|------|------|
| `GET /stocks/{code}/reports` | 研报列表 |
| `GET /stocks/{code}/reports/{report_id}/pdf` | 研报PDF下载 |
| `GET /stocks/{code}/announcements` | 公告检索 |

**缓存策略**: 研报索引 SQLite 1天，PDF 文件系统永久

---

## 4. 统一 REST 响应格式

### 4.1 资金/信号类响应

```python
class StockSignalResponse(BaseModel):
    code: str
    name: str
    data_type: str  # "dragon_tiger" | "margin" | "fund_flow" | "hot_topics" | ...
    records: list[dict]
    source: str  # e.g., "eastmoney" | "ths"
    timestamp: datetime
    pool_date: str | None = None  # 适用龙虎榜等按日期查询
```

### 4.2 研报响应

```python
class ReportResponse(BaseModel):
    code: str
    name: str
    reports: list[dict]  # title, publish_date, org, rating, predict_eps...
    total: int
    source: str

class ReportPDFResponse(BaseModel):
    report_id: str
    title: str
    download_url: str | None  # 指向本地或CDN
```

### 4.3 公告响应

```python
class AnnouncementResponse(BaseModel):
    code: str
    name: str
    announcements: list[dict]  # title, type, date, url
    total: int
    source: str
```

---

## 5. 数据库变更

### 5.1 现有缓存表

- `stock_list`: 股票列表 ✅ 已有
- `concept_board`: 概念板块 ✅ 已有
- `industry_board`: 行业板块 ✅ 已有
- `zt_pool`: 涨跌停池 ✅ 已有

### 5.2 新增缓存表

| 表名 | 用途 | TTL |
|------|------|-----|
| `dragon_tiger` | 个股龙虎榜记录 | 1天 |
| `margin` | 融资融券数据 | 1天 |
| `block_trade` | 大宗交易数据 | 1天 |
| `holder_num` | 股东户数 | 季度 |
| `dividend` | 分红送转 | 季度 |
| `fund_flow` | 资金流数据 | 盘中30秒 |
| `north_flow` | 北向资金 | 盘中1分钟 |
| `hot_topics` | 热点题材 | 盘中5分钟 |
| `reports` | 研报索引 | 1天 |
| `announcements` | 公告索引 | 1天 |

### 5.3 PDF 存储

```
storage/
└── reports/
    └── {code}/
        └── {report_id}.pdf
```

---

## 6. 测试策略

每个阶段完成后执行：

1. **单元测试**: 各 fetcher 方法独立测试，数据获取 + 归一化
2. **集成测试**: REST API 端到端验证
3. **缓存测试**: cache hit/miss 逻辑验证
4. **故障演练**: 模拟 upstream 失败，验证 fallback 行为

---

## 7. 数据源优先级（复用现有框架）

| 优先级 | 数据源 | 用途 |
|--------|--------|------|
| 1 | Tushare | A股日线（需Token） |
| 2 | Baostock | A股日线/分钟线（免费） |
| 3 | Akshare | A股+HK/板块/指数/实时 |
| 4 | Yfinance | US市场/港股 |
| 5 | Zhitu | A股实时报价（需Token） |
| 6 | **Tencent** | **行情增强（PE/PB/涨跌停价/ETF）** |
| 7 | **EastMoney** | **龙虎榜/融资融券/资金流/研报** |
| 8 | **Ths** | **热点题材/北向资金/一致预期** |
| 9 | **Cninfo** | **公告检索** |

---

## 8. 已排除的能力

| 能力 | 排除原因 |
|------|---------|
| mootdx 五档盘口 | TCP连接增加复杂度，HTTP-only架构风格不符 |
| mootdx 逐笔成交 | 同上 |
| mootdx F10 | 属于基本面层，未来D层按需接入 |
| iwencai语义搜索 | 需API Key + X-Claw Header，非公开接口 |

---

## 9. 实施检查清单

- [ ] DataCapability 新增标志
- [ ] tencent_fetcher.py 实现
- [ ] `/stocks/{code}/quote` 增强字段
- [ ] eastmoney_fetcher.py 实现（datacenter域）
- [ ] D层 REST API
- [ ] eastmoney_fetcher.py 实现（push2域）
- [ ] ths_fetcher.py 实现
- [ ] A层 REST API
- [ ] eastmoney_fetcher.py 实现（reportapi域）
- [ ] cninfo_fetcher.py 实现
- [ ] B层 REST API
- [ ] SQLite 缓存表新增
- [ ] 单元测试
- [ ] 集成测试