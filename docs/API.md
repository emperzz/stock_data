# stock_data Server API 能力清单

> 本文档整理自 `stock_data/api/routes.py`、`data_provider/manager.py`、`data_provider/fetchers/*` 的源码。
>
> 适用版本: 与 `master` 分支同步 (最近一次相关提交 `f205fdb docs(baostock): mirror 31 API pages + README from baostock.com`)。

## 1. 总体架构

```
HTTP  ──▶  FastAPI Router (api/routes.py)
              │
              ├── 缓存层 (api/cache.py, TTLCache, 进程内)
              │
              ▼
        DataFetcherManager (data_provider/manager.py)
              │  按 capability + market 过滤, 按 priority 顺序 failover
              ▼
        9 个 Fetcher (data_provider/fetchers/*) ──▶ 上游 9 个 API
```

- **优先顺序 (priority 数字越小越靠前)**: `Tushare(0) → Baostock(1) → Myquant(9,默认) → Akshare(2) → Yfinance(3) → Zhitu(4) → Tencent(5) → EastMoney(6) → Ths(7) → Cninfo(8)`。
- **支持的市场**: `csi` (A股)、`hk` (港股)、`us` (美股)。
- **Capability 路由**: 所有数据请求必须经过 `manager._filter_by_capability(market, capability)`,由 fetcher 在 `supported_data_types` 中声明支持能力。

## 2. Fetcher 能力矩阵

| Fetcher | Priority | Markets | Capabilities |
|---|---|---|---|
| **TushareFetcher** | 0 (可覆盖) | csi | `HISTORICAL_DWM · REALTIME_QUOTE · INDEX_HISTORICAL` |
| **BaostockFetcher** | 1 (可覆盖) | csi | `HISTORICAL_DWM · HISTORICAL_MIN · TRADE_CALENDAR · INDEX_HISTORICAL` |
| **MyquantFetcher** | 9 (默认,最后兜底) | csi | `HISTORICAL_DWM · HISTORICAL_MIN · REALTIME_QUOTE · STOCK_LIST · TRADE_CALENDAR · INDEX_HISTORICAL · INDEX_INTRADAY` |
| **AkshareFetcher** | 2 (可覆盖) | csi, hk | `HISTORICAL_DWM · HISTORICAL_MIN · REALTIME_QUOTE · STOCK_LIST · TRADE_CALENDAR · STOCK_BOARD · INDEX_QUOTE · INDEX_HISTORICAL · INDEX_INTRADAY · STOCK_ZT_POOL` |
| **YfinanceFetcher** | 3 (可覆盖) | csi, hk, us | `HISTORICAL_DWM · HISTORICAL_MIN · REALTIME_QUOTE · INDEX_HISTORICAL · INDEX_QUOTE` |
| **ZhituFetcher** | 4 (可覆盖) | csi | `REALTIME_QUOTE · STOCK_ZT_POOL` |
| **TencentFetcher** | 5 | csi, hk | `REALTIME_QUOTE` (增强字段: PE/PB/市值/涨跌停价) |
| **EastMoneyFetcher** | 6 | csi | `DRAGON_TIGER · MARGIN_TRADING · BLOCK_TRADE · HOLDER_NUM · DIVIDEND · FUND_FLOW · RESEARCH_REPORT` |
| **ThsFetcher** | 7 | csi | `HOT_TOPICS · NORTH_FLOW` |
| **CninfoFetcher** | 8 | csi | `ANNOUNCEMENT` |

环境变量可覆盖 priority: `TUSHARE_PRIORITY` / `BAOSTOCK_PRIORITY` / `AKSHARE_PRIORITY` / `YFINANCE_PRIORITY` / `ZHITU_PRIORITY` / `MYQUANT_PRIORITY` / `TENCENT_PRIORITY` / `EASTMONEY_PRIORITY` / `THS_PRIORITY` / `CNINFO_PRIORITY`。

## 3. 通用前置

### 3.1 调整类型 (`adjust` 参数)

所有历史 K 线 / 分时 API 的 `adjust` 参数统一为:
- `""` (空) = 不复权
- `qfq` = 前复权
- `hfq` = 后复权

各 fetcher 在 `_map_adjust()` 中映射到自家 API:
- Baostock: `"" → 3` (不复权), `qfq → 2` (前复权), `hfq → 1` (后复权)
- Tushare: `"" → None`, `qfq/hfq → pro_bar(adj=...)`
- Akshare: 字符串原值透传 (`""` / `qfq` / `hfq`)
- Yfinance: `"" → False (auto_adjust=False)`, 其它 `→ True` (yfinance 只有一种"前复权"语义, qfq/hfq 都被映射)
- Myquant: `"" → 0` (ADJUST_NONE), `qfq → 1` (ADJUST_PREV), `hfq → 2` (ADJUST_POST)
- Zhitu: `"" → n`, `qfq → f`, `hfq → b`
- Tencent / EastMoney / Ths / Cninfo: 不接受复权 (无 `adjust` 入参)

### 3.2 频率 (`frequency` / `period`)

- **日/周/月 K 线** (历史): `d` / `w` / `m`
- **分钟 K 线** (分时): `5` / `15` / `30` / `60`; `1` 仅 Akshare 支持

### 3.3 缓存层 (TTLCache, 进程内)

| 端点 | 缓存 TTL (秒, 默认) | 环境变量 |
|---|---|---|
| 行情 quote | 60 | `CACHE_TTL_QUOTE` |
| 指数行情 | 60 | `CACHE_TTL_INDEX_QUOTE` |
| 股票分时 | 30 | `CACHE_TTL_STOCK_INTRADAY` |
| 指数分时 | 30 | `CACHE_TTL_INDEX_INTRADAY` |
| 日线 K 线 | 300 | `CACHE_TTL_HISTORY_DAILY` |
| 周线 K 线 | 3600 | `CACHE_TTL_HISTORY_WEEKLY` |
| 月线 K 线 | 7200 | `CACHE_TTL_HISTORY_MONTHLY` |
| 龙虎榜 | 300 | `CACHE_TTL_DRAGON_TIGER` |
| 融资融券 | 300 | `CACHE_TTL_MARGIN` |
| 大宗交易 | 300 | `CACHE_TTL_BLOCK_TRADE` |
| 股东户数 | 300 | `CACHE_TTL_HOLDER_NUM` |
| 分红送转 | 300 | `CACHE_TTL_DIVIDEND` |
| 资金流 (分钟/日级) | 60 | `CACHE_TTL_FUND_FLOW` |
| 热点题材 | 60 | `CACHE_TTL_HOT_TOPICS` |
| 北向资金 | 60 | `CACHE_TTL_NORTH_FLOW` |
| 研报 | 1800 | `CACHE_TTL_REPORTS` |
| 公告 | 1800 | `CACHE_TTL_ANNOUNCEMENTS` |
| 涨跌停股池 | 60 | `CACHE_TTL_POOLS` |

全局开关: `ENABLE_API_CACHE` (默认 `true`)。

### 3.4 持久化 (SQLite, `stock_data/stock_cache.db`)

| 表 | 写入策略 |
|---|---|
| `stock_list` | 每日首次调用 `get_stock_list` 时按需刷新 |
| `stock_board` / `stock_board_stock` | 板块元数据, 每日首次调用刷新 |
| `trade_calendar` | 上游失败时回退到本表 |
| `pool_daily` | 涨跌停/跌停/炸板股池, 按日期 key 持久化, 当日只读 TTL 不入库 |
| `stock_cache` (业务缓存) | 业务级缓存, 启动时由 `STOCK_DB_INIT=true` 重置 |

环境变量: `STOCK_CACHE_DB_PATH` (默认 `<repo>/stock_data/stock_cache.db`)、`STOCK_DB_INIT` (启动时 DROP+CREATE, 警告: 会清空)。

### 3.5 指标层 (IndicatorService, 纯计算)

历史 K 线接口支持 `?indicators=ma,macd,kdj,...` 计算技术指标, 不调用 fetcher, 不联网。14 个指标: `ma, macd, boll, kdj, rsi, wr, bias, cci, atr, obv, roc, dmi, sar, kc`。详见 `/indicators/catalog`。

---

## 4. Endpoint 清单

> 路径前缀由 `server.py` 注册, 此处仅描述路径与职责。

### 4.1 健康检查

#### `GET /health`

**Query params**:
- `details: bool = False`

**Server 响应字段** (`HealthResponse`):
- `status: str` — `ok` / `degraded` / `unhealthy`
- `version: str` — 服务版本
- `sources: list[SourceHealth] | None` — `details=true` 时返回每个 fetcher 的断路器状态 (`name, state, available, last_success_time, last_failure_time, failure_count`)

**数据来源**:
- `REALTIME_CIRCUIT_BREAKER.snapshot_state(fetcher.name)` 遍历所有已注册 fetcher, 汇总 `CircuitBreaker` (CLOSED/OPEN/HALF_OPEN) 状态
- 仅读不写: `snapshot_state` 不消耗 half-open 探测配额

**Cache**: 无

---

### 4.2 股票 / 个股 API

#### `GET /stocks/{stock_code}/quote` — 实时行情

**Path params**:
- `stock_code: str` (max 20) — 例如 `600519`、`AAPL`、`HK00700` (不支持指数代码)

**Server 响应字段** (`StockQuote`):
- 基础: `code, stock_name, source, current_price, change, change_percent, open, high, low, prev_close, volume, amount, update_time`
- 估值增强: `pe_ttm, pe_static, pb, mcap_yi (亿), float_mcap_yi (亿), turnover_pct, amplitude_pct, limit_up, limit_down, vol_ratio`

**可获取数据范围**: 单只股票实时快照

**数据来源 (按优先级)**:
1. **TushareFetcher.get_realtime_quote** → 上游 `tushare.realtime_quote(ts_code=...)`
   - 入参: `ts_code` (例: `600519.SH`)
   - 返回列: `ts_code, name, price, price_change, price_percent, volume, amount, open, high, low, pre_close, ...`
   - 需 token (`TUSHARE_TOKEN`); token 缺 tick 权限时返回 null 字段
2. **BaostockFetcher.get_realtime_quote** → 永远返回 `None` (Baostock 无实时 API)
3. **MyquantFetcher.get_realtime_quote** → 上游 `gm.api.current_price(symbols=...)`
   - 入参: `symbols` (`SHSE.600519` / `SZSE.000001`)
   - 返回: `{symbol, price, created_at}` (仅 price, 其它字段保持 None)
   - 需 token (`MYQUANT_TOKEN`); 定位为最后兜底
4. **AkshareFetcher.get_realtime_quote** → 上游按市场分流:
   - A股: `ak.stock_zh_a_spot_em()` 全市场行情再按 `代码` 过滤
   - 港股: `ak.stock_hk_spot_em()` 全市场行情再按 `代码` 过滤
   - 指数: `ak.stock_zh_index_spot_em(symbol="上证系列指数")` 多个 series 依次尝试
   - 返回列 (中文, 经归一化): 最新价, 涨跌幅, 涨跌额, 成交量, 成交额, 今开, 最高, 最低, 昨收, 振幅, 换手率, 量比, 市盈率, 市净率
5. **YfinanceFetcher.get_realtime_quote** → 上游 `yfinance.Ticker(...).fast_info` (主) / `ticker.history(period="2d")` (备)
   - 入参: ticker (例: `AAPL`, `600519.SS`, `00700.HK`)
   - 返回: `lastPrice, previousClose, open, dayHigh, dayLow, lastVolume`
   - US 失败时回退到 **Stooq** (`https://stooq.com/q/l/?s={symbol}.us`)
6. **ZhituFetcher.get_realtime_quote** → `GET https://api.zhituapi.com/hs/real/ssjy/{code}?token={token}`
   - 入参: `code` (例: `sh600519`), `token`
   - 返回字段 (短键名, 归一化后): `nm (名称), p (现价), pc (涨跌幅%), ud (涨跌额), v (成交量), cje (成交额), o (今开), h (最高), l (最低), yc (昨收), zf (振幅%), lb (量比), hs (换手率%), pe (PE-TTM), sjl (PB), sz (总市值), lt (流通市值)`
   - 需 token (`ZHITU_TOKEN`)
7. **TencentFetcher.get_realtime_quote** → `GET https://qt.gtimg.cn/q={prefix}` (GBK 编码, 88 字段 `~` 分隔)
   - 入参: `prefix` (例: `sh600519`, `hk00700`)
   - 关键字段索引: `0=code, 1=name, 3=现价, 4=昨收, 5=今开, 31=涨跌额, 32=涨跌幅, 33=最高, 34=最低, 36=成交量(手), 37=成交额(万元), 38=换手率%, 39=PE(TTM), 43=振幅%, 44=总市值(亿), 45=流通市值(亿), 46=PB, 47=涨停价, 48=跌停价, 49=量比, 52=PE(静)`
   - **单位换算**: 手→股 (×100), 万元→元 (×10000), 亿→元 (×1e8)

**Cache**: 60s, key=`stock_code`

**circuit breaker**: `REALTIME_CIRCUIT_BREAKER` (单只失败的 fetcher 会被短时熔断, 路由跳过)

---

#### `GET /stocks/{stock_code}/history` — 历史 K 线 (含可选指标)

**Path params**:
- `stock_code: str` (max 20)

**Query params**:
- `period: str = "daily"` — `daily` | `weekly` | `monthly` (→ `d`/`w`/`m`)
- `days: int = 30` — `1..365`, 当 `start_date` 未提供时使用
- `start_date: str | None = None` — `YYYY-MM-DD`, 覆盖 `days`
- `end_date: str | None = None` — `YYYY-MM-DD`, 默认今天
- `adjust: str = ""` — `""` | `qfq` | `hfq`
- `indicators: str | None = None` — 逗号分隔指标名, 例: `ma,macd,kdj`

**Server 响应字段** (`StockHistoryResponse`):
- `code, stock_name, period`
- `data: list[KLineData]` — 每条:
  - 必返: `date, open, high, low, close, volume, amount, change_percent`
  - 条件返回 (请求 `?indicators=` 时): `ma5, ma10, ma20, indicators: dict[str, float|None]`

**可获取数据范围**: 单只股票, K 线行数 = `days` (1-365), 周期 d/w/m; 指标会按需自动回看 (`compute_lookback`)

**数据来源 (按优先级, `csi`)**:
1. **TushareFetcher._fetch_raw_data** (frequency=d/w/m)
   - 股票 d + 复权: `tushare.pro_bar(ts_code=..., freq='D', adj='qfq'/'hfq')`
   - 股票 d 不复权 / w / m: `api.query('daily'/'weekly'/'monthly', ts_code=..., start_date=..., end_date=...)`
   - 指数 d/w/m: `api.query('index_daily'/'index_weekly'/'index_monthly', ...)`
   - 入参: `ts_code` (e.g. `600519.SH`), `start_date/end_date` (YYYYMMDD), `freq` (`D`/`W`/`M`), `adj` (`qfq`/`hfq`/`None`)
   - 返回列: `ts_code, trade_date, open, high, low, close, pre_close, change, pct_chg, vol (手), amount (千元)`
   - **单位换算**: `vol×100→股, amount×1000→元`
2. **BaostockFetcher._fetch_raw_data** (frequency=d/w/m/5/15/30/60)
   - `bs.query_history_k_data_plus(code, fields, start_date, end_date, frequency, adjustflag)`
   - 入参: `code` (e.g. `sh.600519` / `sz.000001` / `sh.000300`), `fields="date,open,high,low,close,volume,amount,pctChg"`, `frequency` (`d`/`w`/`m`/`5`/`15`/`30`/`60`), `adjustflag` (`1`/`2`/`3`, 经 `_map_adjust` 映射)
   - 返回列: `date, open, high, low, close, volume, amount, pctChg`
3. **MyquantFetcher._fetch_raw_data** (frequency=d/5/15/30/60)
   - `gm.api.history(symbol=..., frequency='1d'/'300s'/'900s'/'1800s'/'3600s', start_time, end_time, adjust=0/1/2, df=True)`
   - 入参: `symbol` (`SHSE.600519` / `SZSE.000001`), `start_time/end_time` (YYYY-MM-DD), `adjust` (int 常量)
   - 返回列: `symbol, frequency, open, close, high, low, amount, volume, bob, eob`
   - **派生**: `pct_chg` 由 `(close_t / close_{t-1} - 1) * 100` 计算 (首行 None)
4. **AkshareFetcher._fetch_raw_data** (frequency=d/w/m/1/5/15/30/60)
   - A股 d/w/m: `ak.stock_zh_a_hist(symbol, period='daily'/'weekly'/'monthly', start_date, end_date, adjust)`
   - 港股 d/w/m: `ak.stock_hk_hist(symbol, period, start_date=YYYYMMDD, end_date=YYYYMMDD, adjust)`
   - A股 分钟: `ak.stock_zh_a_hist_min_em(symbol, period, start_date='YYYY-MM-DD 09:30:00', end_date='YYYY-MM-DD 15:00:00', adjust)`
   - CSI 指数 d/w/m: `ak.index_zh_a_hist(symbol, period, start_date=YYYYMMDD, end_date=YYYYMMDD)`
   - CSI 指数 分钟: `ak.index_zh_a_hist_min_em(symbol, period, start_date, end_date)`
   - 美股指数: `ak.index_us_stock_sina(symbol='.IXIC' 等)`
   - 返回列 (中文, 经归一化): 日期, 股票代码, 开盘, 收盘, 最高, 最低, 成交量, 成交额, 振幅, 涨跌幅, 涨跌额, 换手率
5. **YfinanceFetcher._fetch_raw_data** (frequency=d/w/m/5/15/30/60)
   - `yf.download(tickers, start, end, progress=False, auto_adjust=bool, multi_level_index=True, interval='1d'/'1wk'/'1mo'/'5m'/...)`
   - 入参: `tickers` (e.g. `AAPL`, `600519.SS`, `000001.SZ`, `^GSPC`), `start/end` (YYYY-MM-DD), `interval` (频率映射)
   - 返回列 (multi-level 处理后): `Date, Open, High, Low, Close, Volume`
   - **派生**: `pct_chg = close.pct_change()*100`, `amount = volume * close`

**Cache**: TTL 按频率 (日 300s / 周 3600s / 月 7200s); key 包含 `stock_code + frequency + days + start_date + end_date + adjust + indicators`

**指标**: 若 `?indicators=` 非空, 先 `compute_lookback()` 算回看量, 多 fetch `max(days, lookback)` 行; 调 `IndicatorService.compute` 计算; 最后 `tail(days)` 截回用户请求的范围

---

#### `GET /stocks/{stock_code}/intraday` — 分钟 K 线

**Path params**:
- `stock_code: str`

**Query params**:
- `period: str = "5"` — `1` | `5` | `15` | `30` | `60`
- `adjust: str = ""` — `""` | `qfq` | `hfq`

**限制**:
- 仅 A 股; US / HK / 指数 → `400 unsupported_market`
- `period=1` 仅 Akshare 支持; Zhitu 显式 `raise DataFetchError`

**Server 响应字段** (`IntradayResponse`):
- `code, stock_name, period (e.g. "5m"), adjust, date (YYYY-MM-DD)`
- `data: list[IntradayData]` — 每条: `time (HH:MM:SS), open, high, low, close, volume, amount`

**可获取数据范围**: 当日 09:30-15:00 的分钟 K 线 (上游只返回最近一个交易日, zhitu/myquant 18:00 清洗)

**数据来源 (按优先级, `csi`)**:
1. **TushareFetcher**: 不支持分钟, 跳过 (`raise DataFetchError` 由 manager 视为软失败)
2. **BaostockFetcher._fetch_raw_data** (frequency in 5/15/30/60)
   - `bs.query_history_k_data_plus(code, fields, start_date, end_date, frequency='5'/'15'/'30'/'60', adjustflag)`
   - 入参同 history 接口
3. **MyquantFetcher.get_intraday_data**
   - `gm.api.history(symbol, frequency='300s'/'900s'/'1800s'/'3600s', start_time=today, end_time=today, adjust, df=True)`
   - 仅 5/15/30/60; `1min` 显式 raise
4. **AkshareFetcher.get_intraday_data** (try EM then fallback Sina)
   - 主: `ak.stock_zh_a_hist_min_em(symbol, start_date='YYYY-MM-DD 09:30:00', end_date='YYYY-MM-DD 15:00:00', period, adjust)`
   - 备: `ak.stock_zh_a_minute(symbol='sh600519'/'sz000001', period, adjust)` (time 列名 `day`)
   - 入参: `symbol` (6 位 A 股代码), `period` (1/5/15/30/60), `adjust` (空/qfq/hfq)
   - 返回列 (中文, 归一化): 时间, 开盘, 收盘, 最高, 最低, 成交量, 成交额
5. **YfinanceFetcher._fetch_raw_data** (frequency in 5/15/30/60)
   - `yf.download(tickers, start, end, progress=False, auto_adjust, interval='5m'/'15m'/'30m'/'60m')`
6. **ZhituFetcher.get_intraday_data**
   - `GET https://api.zhituapi.com/hs/history/{symbol}.{sh|sz}/{period}/{adj}?token={token}&st={YYYYMMDD}&et={YYYYMMDD}`
   - 入参: `symbol` (e.g. `600519`), market 后缀, `period` (5/15/30/60, 不支持 1), `adj` (`n`/`f`/`b`)
   - 返回: list of `{t, o, h, l, c, v, a}` (时间 ISO, 短键)
   - `st/et` = 持久化层最近缓存的交易日 (`trade_calendar.get_latest_cached_trade_date()`), 找不到则今天

**Cache**: 30s, key=`stock_intraday:{stock_code}:{period}[:{adjust}]`

---

### 4.3 指数 API

#### `GET /indices` — 指数列表

**Server 响应字段** (`list[IndexInfo]`):
- 每条: `code, name, market (csi/hk/us)`

**可获取数据范围**: A 股 CSI 主要指数 (12 个) + 港股指数 (HSI/HSCE) + 美股指数 (SPX/SPY/DJI/IXIC/NASDAQ/VIX/NDX)

**数据来源**: `data_provider/fetchers/index_symbols.py` 静态表
- `CSI_INDEX_MAP` (沪深主要指数, 12 项)
- `HK_INDEX_MAP` (HSI, HSCE)
- `US_INDEX_MAP` / `US_INDEX_AKSHARE_MAP` (SPX→^GSPC, DJI, IXIC, NDX, VIX 等)

**Cache**: 无 (进程内静态)

---

#### `GET /indices/{index_code}/quote` — 指数实时行情

**Path params**:
- `index_code: str` — 例 `000300` (沪深300) / `SPX` / `HSI`

**Server 响应字段** (`IndexQuote`):
- `code, name, source, current_price, change, change_percent, open, high, low, prev_close, volume, amount, update_time`

**可获取数据范围**: 单个指数实时快照

**数据来源 (按 market 路由)**:
- `csi` (CSI 指数):
  1. **AkshareFetcher.get_index_realtime_quote**
     - 主: `ak.stock_zh_index_spot_em(symbol='上证系列指数' / '沪深重要指数' / '深证系列指数' / '中证系列指数')` 多个 series 依次尝试按 `代码` 匹配
     - 备: `ak.stock_zh_index_spot_sina()` 按 `sh000001` / `sz399006` 匹配
     - 返回列: 代码, 名称, 最新价, 涨跌幅, 涨跌额, 成交量, 成交额, 今开, 最高, 最低, 昨收
  2. **YfinanceFetcher.get_index_realtime_quote** (经 `get_realtime_quote` 复用, 通过 `US_INDEX_MAP`/`HK_INDEX_MAP` 转换)
  3. **TushareFetcher / BaostockFetcher / ZhituFetcher / TencentFetcher**: 不支持指数实时 (`None`)
- `hk` (HSI/HSCE):
  1. **YfinanceFetcher** → `yf.Ticker("^HSI").fast_info`
  2. (Akshare 不支持港股指数实时; Tencent 不支持指数)
- `us` (SPX/DJI/IXIC/NDX/VIX):
  1. **YfinanceFetcher** → `yf.Ticker("^GSPC").fast_info`
  2. 备: **Stooq** (`stooq.com/q/l/?s={symbol}.us`)

**Cache**: 60s, key=`idx_quote:{index_code}`

---

#### `GET /indices/{index_code}/history` — 指数历史 K 线

**Path params**:
- `index_code: str`

**Query params**:
- `period: str = "daily"` — `daily`/`weekly`/`monthly`
- `days: int = 30` — `1..365`
- `start_date / end_date / indicators`: 同股票 history

**Server 响应字段** (`IndexHistoryResponse`):
- `code, name, period, data: list[KLineData]`

**数据来源 (按 market 路由, 失败回退到 `HISTORICAL_DWM`)**:
- `csi` (走 `INDEX_HISTORICAL`):
  1. **TushareFetcher.get_index_historical** → `api.query('index_daily'/'index_weekly'/'index_monthly', ts_code='sh.000300.SH' / 'sz.399006.SZ', start_date, end_date)`
  2. **BaostockFetcher.get_index_historical** → 内部委托 `get_kline_data` → `bs.query_history_k_data_plus('sh.000300', fields, start_date, end_date, frequency, adjustflag='3')` (指数忽略 adjust)
  3. **MyquantFetcher.get_index_historical** → `gm.api.history(symbol='SHSE.000300' / 'SZSE.399006', frequency='1d', start_time, end_time, df=True)` (仅 d 频率)
  4. **AkshareFetcher.get_index_historical** — 依次尝试 3 个端点:
     - `ak.stock_zh_index_daily(symbol='sh000300' / 'sz399006')` (Sina) — 列: `date, open, high, low, close, volume`
     - `ak.stock_zh_index_daily_tx(symbol='sh000300', start_date=YYYYMMDD, end_date=YYYYMMDD)` (Tencent) — 列: `date, open, close, high, low, amount` (amount 映射为 volume)
     - `ak.stock_zh_index_daily_em(symbol='000300', start_date=YYYYMMDD, end_date=YYYYMMDD)` (EM) — 列: `date, open, close, high, low, volume, amount`
  - 失败回退到 `HISTORICAL_DWM` (各 fetcher 的 `get_kline_data`, 走股票通道)
- `hk` / `us` (走 `INDEX_HISTORICAL`):
  1. **YfinanceFetcher.get_index_historical** → 内部委托 `get_kline_data` → `yf.download(ticker='^HSI' / '^GSPC', start, end, interval='1d'/'1wk'/'1mo', auto_adjust)`

**Cache**: TTL 按频率, key=`idx_history:{index_code}:{frequency}:{days}[:{start}:{end}][ind=...]`

---

#### `GET /indices/{index_code}/intraday` — 指数分时

**Path params**:
- `index_code: str`

**Query params**:
- `period: str = "5"` — `1`/`5`/`15`/`30`/`60`

**Server 响应字段** (`IndexIntradayResponse`):
- `code, name, period, date, data: list[IntradayData]`

**数据来源**:
- `csi` (走 `INDEX_INTRADAY`):
  1. **AkshareFetcher.get_index_intraday** → `ak.index_zh_a_hist_min_em(symbol, period, start_date='YYYY-MM-DD 09:30:00', end_date='YYYY-MM-DD 15:00:00')`
  2. **MyquantFetcher.get_index_intraday** → `gm.api.history(symbol='SHSE.000300' / 'SZSE.399006', frequency='300s'/'900s'/'1800s'/'3600s', start_time=today, end_time=today, df=True)` (不支持 1min)
  - 回退到 `HISTORICAL_MIN` (各 fetcher 的 `get_intraday_data`)
- `hk` / `us`:
  1. **YfinanceFetcher** (复用 `get_intraday_data`) → `yf.download(ticker='^HSI' / '^GSPC', interval='5m'/...)`

**Cache**: 30s, key=`idx_intraday:{index_code}:{period}`

---

### 4.4 股票 / 指数列表与日历

#### `GET /stocks` — 股票列表 (分页)

**Query params**:
- `market: str` — 必填, `csi` (或 `cn`, 向后兼容) / `hk` / `us`
- `refresh: bool = False` — 强制刷新
- `offset: int = 0` — `>=0`
- `limit: int = 100` — `1..1000`

**Server 响应字段** (`list[StockInfo]`):
- 每条: `code, name, market`

**可获取数据范围**: 单一市场全部 A 股 / 港股 / 美股 (美股从 S&P 500 成份股采样)

**数据来源 (持久化层 `stock_list.get_stock_list` 包装, 失败时按 `STOCK_LIST` capability 路由)**:
- `csi`:
  1. **BaostockFetcher.get_all_stocks** → `bs.query_all_stock(day=最近交易日)`, 按 `sh.000xxx` 排除指数, 过滤 `A_SHARE_STOCK_PREFIXES`
  2. **MyquantFetcher.get_all_stocks** → `gm.api.get_symbols(sec_type1=1010, df=True)`, 同样过滤; 含 `is_st/is_suspended/upper_limit/lower_limit/turn_rate/adj_factor/pre_close`
  3. **AkshareFetcher.get_all_stocks** → `ak.stock_info_a_code_name()` (A 股, 列: `code, name`)
- `hk`:
  1. **AkshareFetcher.get_all_stocks** → `ak.stock_hk_spot_em()` (列: `代码, 名称`), 归一化到 `HK` + 5 位
- `us`:
  1. **AkshareFetcher.get_all_stocks** → `ak.index_cons_sina(symbol='SPX')` (从 S&P 500 采样, 列: `symbol, name`)

**Cache**: 走持久化 SQLite, 进程内无 TTL; 当日首次调用时由持久化层自动刷新

---

#### `GET /calendar` — A 股交易日历

**Query params**:
- `refresh: bool = False` — 强制从上游刷新

**Server 响应字段** (`TradeCalendarResponse`):
- `trade_dates: list[str]` (YYYY-MM-DD, 升序)
- `latest_date: str | None`
- `total: int`

**可获取数据范围**: 1990-12-19 至今 (上游最长范围); 落库 SQLite

**数据来源 (按优先级, `csi`)**:
1. **AkshareFetcher.get_trade_calendar** → `ak.tool_trade_date_hist_sina()` (列: `trade_date`)
2. **MyquantFetcher.get_trade_calendar** → `gm.api.get_trading_dates_by_year(exchange='SHSE', start_year=2010, end_year=当前年, df=True)` (列: `trade_date`, 过滤空字符串)
3. **BaostockFetcher.get_trade_calendar** → `bs.query_trade_dates()`, 取 `is_trading_day=='1'` 的行

**刷新策略**:
- 启动时持久化层初始化 (`init_schema()`)
- `refresh=true` 或缓存为空 / `latest_date < today` 时回源
- 上游全部失败时回退到 SQLite 缓存

**Cache**: 无 TTL (持久化层拥有)

---

### 4.5 板块 (Boards)

#### `GET /boards` — 概念 / 行业板块列表

**Query params**:
- `type: str` — 必填, `concept` | `industry`
- `source: str = "eastmoney"` — (本项目实际只走 akshare, 该参数保留)
- `include_quote: bool = False` — 是否带实时行情字段
- `refresh: bool = False` — 强制刷新

**Server 响应字段** (`BoardListResponse` → `data: list[BoardInfo]`):
- 基础: `code (e.g. BK1048), name`
- `include_quote=true` 时附加: `price, change_pct, change_amount, volume, amount, turnover_rate, total_mv, up_count, down_count, leading_stock, leading_stock_pct`

**数据来源 (走 `STOCK_BOARD` capability)**:
- **AkshareFetcher.get_all_concept_boards** → `ak.stock_board_concept_name_em()`
- **AkshareFetcher.get_all_industry_boards** → `ak.stock_board_industry_name_em()`
- 走 `fetch_board_list` 共享辅助, 列映射:
  - 板块列表: 板块代码, 板块名称 + [最新价, 涨跌幅, 涨跌额, 成交量, 成交额, 换手率, 总市值, 上涨家数, 下跌家数, 领涨股票, 领涨股票-涨跌幅]
- 上游 `include_quote=true` 时直接读每行; 失败则不带行情字段

**Cache**: 持久化 SQLite, 进程内无 TTL; 当日首次调用时持久化层刷新

---

#### `GET /boards/{board_code}/stocks` — 板块成份股

**Path params**:
- `board_code: str` — 例 `BK1048`

**Query params**:
- `source: str = "eastmoney"` (保留)
- `include_quote: bool = False`
- `refresh: bool = False`

**Server 响应字段** (`BoardStocksResponse`):
- `board: BoardInfo` (含 `code, name`)
- `stocks: list[BoardStockInfo]` — 每条: `code, name, price?, change_pct?, volume?`
- `source: str`

**数据来源 (走 `STOCK_BOARD` capability)**:
- **AkshareFetcher.get_concept_board_stocks** → `ak.stock_board_concept_cons_em(symbol='BK1048')`
- **AkshareFetcher.get_industry_board_stocks** → `ak.stock_board_industry_cons_em(symbol='BK1048')`
- 走 `fetch_board_stocks` 共享辅助, 列映射:
  - 成份股: 代码, 名称 + [最新价, 涨跌幅, 涨跌额, 成交量, 成交额, 换手率, 市盈率-动态, 市净率, 最高, 最低, 今开, 昨收]
- `include_quote=true` 但直读失败时, 回退调用 `_enrich_stock_from_realtime(code)` (走 Akshare 实时行情) 逐只补齐

**Cache**: 持久化 SQLite

---

### 4.6 涨跌停股池

#### `GET /pools` — ZT / DT / ZBGC 股池

**Query params**:
- `type: str` — 必填, `zt` | `dt` | `zbgc`
- `date: str | None = None` — YYYY-MM-DD; 不传时: 今日 (若交易日) 或 最近缓存的交易日
- `refresh: bool = False` — 强制刷新 (不持久化当日)

**Server 响应字段** (`ZTPoolResponse`):
- `date, type, total, stocks: list[ZTPoolStock]`
- ZTPoolStock: `code, name, price, change_pct, amount, circ_mv, total_mv, turnover_rate, lb_count (连板数/连续跌停次数), first_seal_time, last_seal_time, seal_amount, seal_count (炸板次数), zt_count`

**可获取数据范围**: 单日 A 股, 历史日期全量, 当日仅 TTL 不落库

**数据来源 (走 `STOCK_ZT_POOL` capability)**:
1. **AkshareFetcher.get_zt_pool**
   - ZT: `ak.stock_zt_pool_em(date=YYYYMMDD)` (列: 代码, 名称, 最新价, 涨跌幅, 成交额, 换手率, 连板数, 首次封板时间, 最后封板时间, 炸板次数, 涨停统计)
   - DT: `ak.stock_zt_pool_dtgc_em(date=YYYYMMDD)` (列含"连续跌停次数", 无"炸板次数"/"涨停统计")
   - ZBGC: `ak.stock_zt_pool_zbgc_em(date=YYYYMMDD)`
2. **ZhituFetcher.get_zt_pool**
   - ZT: `GET https://api.zhituapi.com/hs/pool/ztgc/{date}?token={token}` (date=YYYY-MM-DD)
   - DT: `GET .../dtgc/{date}...`
   - ZBGC: `GET .../zbgc/{date}...`
   - 返回列 (短键): `dm (代码), mc (名称), p (现价), zf (涨跌幅), cje (成交额), lt (流通市值), zsz (总市值), hs (换手率), lbc (连板数), fbt (首次封板时间), lbt (最后封板时间), zj (封单资金), zbc (炸板次数), tj (涨停统计)`

**持久化**: `pool_daily` 表, 单表三类型 (`pool_type` 列), 当日仅 TTLCache 不写库 (避免部分盘后数据)

**Cache**: 60s (仅当日), key=`pool:{type}:{date}`

---

### 4.7 龙虎榜

#### `GET /stocks/{stock_code}/dragon-tiger` — 个股龙虎榜

**Path params**:
- `stock_code: str`

**Query params**:
- `trade_date: str = ""` — YYYY-MM-DD, 空=今天
- `look_back: int = 30` — `1..365`

**Server 响应字段** (`DragonTigerResponse`):
- `code, name, source ("eastmoney")`
- `records: list[DragonTigerRecord]` — 每条: `date, reason, net_buy_wan, turnover_pct`
- `seats: { buy: list[DragonTigerSeat], sell: list[DragonTigerSeat] }` — Seat: `name, buy_wan, sell_wan, net_wan` (Top 5)
- `institution: DragonTigerInstitution` — `buy_amt, sell_amt, net_amt` (单位万元)

**数据来源 (走 `DRAGON_TIGER` capability, 本项目唯一 fetcher 为 EastMoney)**:
- **EastMoneyFetcher.get_dragon_tiger**
  - 主查询: `GET https://datacenter-web.eastmoney.com/api/data/v1/get`
    - 入参: `reportName=RPT_DAILYBILLBOARD_DETAILSNEW`, `filter=(TRADE_DATE>='{start}')(TRADE_DATE<='{trade_date}')(SECURITY_CODE="{code}")`, `sortColumns=TRADE_DATE`, `sortTypes=-1`, `pageSize=50`, `pageNumber=1`
    - 返回关键列: `TRADE_DATE, EXPLANATION (上榜原因), BILLBOARD_NET_AMT (净买入额, 元), TURNOVERRATE, SECURITY_CODE`
  - 席位查询 (取最近一次上榜日的 Top 5):
    - 买方: `reportName=RPT_BILLBOARD_DAILYDETAILSBUY`, `sortColumns=BUY`, `pageSize=10`, 关键列: `OPERATEDEPT_NAME (营业部名称), BUY, SELL, NET`
    - 卖方: `reportName=RPT_BILLBOARD_DAILYDETAILSSELL`, `sortColumns=SELL`, `pageSize=10`
  - 机构统计: `OPERATEDEPT_CODE=='0'` 视为机构, 累计买卖额

**Cache**: 300s, key=`dt:{stock_code}:{trade_date}:{look_back}`

---

#### `GET /dragon-tiger/daily` — 全市场龙虎榜

**Query params**:
- `trade_date: str = ""` — YYYY-MM-DD, 空=今天
- `min_net_buy: float | None = None` — 最小净买入 (万元)

**Server 响应字段** (`DailyDragonTigerResponse`):
- `date, total, stocks: list[DailyDragonTigerStock]`
- Stock: `code, name, reason, close, change_pct, net_buy_wan, buy_wan, sell_wan, turnover_pct`

**数据来源**:
- **EastMoneyFetcher.get_daily_dragon_tiger**
  - `GET datacenter-web.eastmoney.com/api/data/v1/get`
  - 入参: `reportName=RPT_DAILYBILLBOARD_DETAILSNEW`, `filter=(TRADE_DATE='{trade_date}')`, `sortColumns=BILLBOARD_NET_AMT`, `pageSize=500`
  - 关键列: `SECURITY_CODE, SECURITY_NAME_ABBR, EXPLANATION, CLOSE_PRICE, CHANGE_RATE, BILLBOARD_NET_AMT, BILLBOARD_BUY_AMT, BILLBOARD_SELL_AMT, TURNOVERRATE`
  - 服务端按 `min_net_buy` 二次过滤

**Cache**: 300s, key=`dtdaily:{trade_date}:{min_net_buy}`

---

### 4.8 融资融券 / 大宗 / 股东 / 分红

#### `GET /stocks/{stock_code}/margin` — 融资融券

**Query params**:
- `page_size: int = 30` — `1..100`

**Server 响应字段** (`MarginTradingResponse`):
- `code, name, source, records: list[MarginTradingRecord]`
- Record: `date, rzye (融资余额, 元), rzmre (融资买入额, 元), rzche (融资偿还额, 元), rqye (融券余额, 元), rqmcl (融券卖出量), rqchl (融券偿还量), rzrqye (融资融券余额合计, 元)`

**数据来源**:
- **EastMoneyFetcher.get_margin_trading**
  - `GET datacenter-web.eastmoney.com/api/data/v1/get`
  - 入参: `reportName=RPTA_WEB_RZRQ_GGMX`, `filter=(SCODE="{code}")`, `sortColumns=DATE`, `pageSize={page_size}`
  - 关键列: `DATE, RZYE, RZMRE, RZCHE, RQYE, RQMCL, RQCHL, RZRQYE`

**Cache**: 300s, key=`margin:{stock_code}:{page_size}`

---

#### `GET /stocks/{stock_code}/block-trade` — 大宗交易

**Query params**:
- `page_size: int = 20` — `1..100`

**Server 响应字段** (`BlockTradeResponse`):
- `code, name, source, total, records: list[BlockTradeRecord]`
- Record: `date, price (成交价), close (收盘价), premium_pct (溢价率%), vol (成交量, 股), amount (成交额, 元), buyer (买方营业部), seller (卖方营业部)`

**数据来源**:
- **EastMoneyFetcher.get_block_trade**
  - `GET datacenter-web.eastmoney.com/api/data/v1/get`
  - 入参: `reportName=RPT_DATA_BLOCKTRADE`, `filter=(SECURITY_CODE="{code}")`, `sortColumns=TRADE_DATE`, `pageSize={page_size}`
  - 关键列: `TRADE_DATE, DEAL_PRICE, CLOSE_PRICE, DEAL_VOLUME, DEAL_AMT, BUYER_NAME, SELLER_NAME`
  - **派生**: `premium_pct = (DEAL_PRICE / CLOSE_PRICE - 1) * 100`

**Cache**: 300s, key=`block:{stock_code}:{page_size}`

---

#### `GET /stocks/{stock_code}/holder-num` — 股东户数变化

**Query params**:
- `page_size: int = 10` — `1..50`

**Server 响应字段** (`HolderNumResponse`):
- `code, name, source, records: list[HolderNumRecord]`
- Record: `date (报告期), holder_num, change_num, change_ratio, avg_shares`

**数据来源**:
- **EastMoneyFetcher.get_holder_num_change**
  - `GET datacenter-web.eastmoney.com/api/data/v1/get`
  - 入参: `reportName=RPT_HOLDERNUMLATEST`, `filter=(SECURITY_CODE="{code}")`, `sortColumns=END_DATE`, `pageSize={page_size}`
  - 关键列: `END_DATE, HOLDER_NUM, HOLDER_NUM_CHANGE, HOLDER_NUM_RATIO, AVG_FREE_SHARES`

**Cache**: 300s, key=`holder:{stock_code}:{page_size}`

---

#### `GET /stocks/{stock_code}/dividend` — 分红送转

**Query params**:
- `page_size: int = 20` — `1..100`

**Server 响应字段** (`DividendResponse`):
- `code, name, source, records: list[DividendRecord]`
- Record: `date (除权除息日), bonus_rmb (每股派息, 税前, 元), transfer_ratio (每10股转增), bonus_ratio (每10股送股), plan (进度)`

**数据来源**:
- **EastMoneyFetcher.get_dividend**
  - `GET datacenter-web.eastmoney.com/api/data/v1/get`
  - 入参: `reportName=RPT_SHAREBONUS_DET`, `filter=(SECURITY_CODE="{code}")`, `sortColumns=EX_DIVIDEND_DATE`, `pageSize={page_size}`
  - 关键列: `EX_DIVIDEND_DATE, PRETAX_BONUS_RMB, TRANSFER_RATIO, BONUS_RATIO, ASSIGN_PROGRESS`

**Cache**: 300s, key=`div:{stock_code}:{page_size}`

---

### 4.9 资金流

#### `GET /stocks/{stock_code}/fund-flow` — 资金流 (分钟级)

**Path params**:
- `stock_code: str`

**Server 响应字段** (`FundFlowResponse`, `type="minute"`):
- `code, name, type, source, records: list[FundFlowMinuteRecord]`
- Record: `time (HH:mm), main_net, small_net, mid_net, large_net, super_net` (单位: 元)

**数据来源**:
- **EastMoneyFetcher.get_fund_flow_minute**
  - `GET https://push2.eastmoney.com/api/qt/stock/fflow/kline/get`
  - 入参: `secid={market}.{code} (e.g. 1.600519)`, `fields1=f1,f2,f3,f7`, `fields2=f51,f52,f53,f54,f55,f56,f57`, `klt=1`
  - 返回: `data.klines` (list of CSV 字符串), 每行: `time,main_net,small_net,mid_net,large_net,super_net` (数字字段, `-` 视为 0)

**Cache**: 60s, key=`ff:{stock_code}`

---

#### `GET /stocks/{stock_code}/fund-flow/daily` — 资金流 (120 日)

**Path params**:
- `stock_code: str`

**Server 响应字段** (`FundFlowResponse`, `type="daily"`):
- `code, name, type, source, records: list[FundFlowDailyRecord]` — Record: `date, main_net, small_net, mid_net, large_net, super_net` (单位: 元)

**数据来源**:
- **EastMoneyFetcher.get_fund_flow_120d**
  - `GET https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get`
  - 入参: `secid={market}.{code}`, `fields1=f1,f2,f3,f7`, `fields2=f51..f65` (15 字段, 服务端只取 6), `lmt=120`
  - 返回: `data.klines` (list of CSV 字符串), 每行: `date,main_net,small_net,mid_net,large_net,super_net`

**Cache**: 60s, key=`ffd:{stock_code}`

---

### 4.10 热点题材 / 北向资金

#### `GET /hot/topics` — 当日热点题材

**Query params**:
- `date: str = ""` — YYYY-MM-DD, 空=今天

**Server 响应字段** (`HotTopicResponse`):
- `date, total, topics: list[HotTopicRecord]`
- Record: `code, name, reason (题材归因), change_pct (涨幅%), turnover_rate (换手率%), volume, amount, dde_net (大单净量)`

**数据来源 (走 `HOT_TOPICS` capability, 唯一 fetcher 为 ThsFetcher)**:
- **ThsFetcher.get_hot_topics**
  - `GET http://zx.10jqka.com.cn/event/api/getharden/date/{date}/orderby/date/orderway/desc/charset/GBK/`
  - 入参: `date` (YYYY-MM-DD)
  - 关键列: `code, name, reason (题材归因), zhangfu (涨幅), huanshou (换手率), chengjiaoliang (成交量), chengjiaoe (成交额), ddejingliang (大单净量)`

**Cache**: 60s, key=`hot:{date}`

---

#### `GET /north-flow/realtime` — 北向资金 (分钟级累计)

**Server 响应字段** (`NorthFlowResponse`):
- `source ("ths"), records: list[NorthFlowRecord]`
- Record: `time, hgt_yi (沪股通累计净买入, 亿元), sgt_yi (深股通累计净买入, 亿元)`

**数据来源 (走 `NORTH_FLOW` capability, 唯一 fetcher 为 ThsFetcher)**:
- **ThsFetcher.get_north_flow**
  - `GET https://data.hexin.cn/market/hsgtApi/method/dayChart/`
  - 返回: `{time: [...], hgt: [...], sgt: [...]}` (length 262 时间点), 服务端按索引 zip 为行
  - 累计净买入, 单位亿元

**Cache**: 60s, key=`north:realtime`

---

### 4.11 研报

#### `GET /stocks/{stock_code}/reports` — 研报列表

**Path params**:
- `stock_code: str`

**Query params**:
- `max_pages: int = 3` — `1..10`, 每页 100 条, 上限 1000

**Server 响应字段** (`ReportResponse`):
- `code, name, source, total, reports: list[ReportRecord]`
- Record: `title, publish_date, org, info_code (PDF 编号), rating, predict_eps_this, predict_eps_next, predict_eps_next2`

**数据来源 (走 `RESEARCH_REPORT` capability, 唯一 fetcher 为 EastMoney)**:
- **EastMoneyFetcher.get_reports**
  - `GET https://reportapi.eastmoney.com/report/list`
  - 入参: `industryCode=*, industry=*, rating=*, ratingChange=*, beginTime=2000-01-01, endTime=2030-01-01, pageNo={page}, pageSize=100, pageNumber={page}, pageNum={page}, p={page}, qType=0, orgCode=, code={code}, rcode=`
  - 关键列: `title, publishDate, orgSName, infoCode, emRatingName, predictThisYearEps, predictNextYearEps, predictNextTwoYearEps`
  - 翻页: `TotalPage` 决定终止; 失败时停在该页

**Cache**: 1800s, key=`rpt:{stock_code}:{max_pages}`

---

#### `GET /stocks/{stock_code}/reports/{report_id}/pdf` — 研报 PDF

**Path params**:
- `stock_code: str`
- `report_id: str` — 即 `info_code`

**Server 响应字段** (`ReportPDFResponse`):
- `report_id, download_path (本地路径), url (PDF 直链)`

**数据来源 (走 `RESEARCH_REPORT` capability, 唯一 fetcher 为 EastMoney)**:
- **EastMoneyFetcher.download_report_pdf**
  - `GET https://pdf.dfcfw.com/pdf/H3_{info_code}_1.pdf`
  - 校验: HTTP 200 且 `len(content) >= 1024` (过滤空响应 / 错误页)
  - 落盘: `./reports/{info_code}.pdf` (默认 `target_dir` 可被调用方覆盖)

**Cache**: 无

---

### 4.12 公告

#### `GET /stocks/{stock_code}/announcements` — 公告

**Path params**:
- `stock_code: str`

**Query params**:
- `page_size: int = 30` — `1..100`

**Server 响应字段** (`AnnouncementResponse`):
- `code, name, source ("cninfo"), total, announcements: list[AnnouncementRecord]`
- Record: `title, type, date, url`

**数据来源 (走 `ANNOUNCEMENT` capability, 唯一 fetcher 为 CninfoFetcher)**:
- **CninfoFetcher.get_announcements**
  - `POST https://www.cninfo.com.cn/new/hisAnnouncement/query` (form 表单, 非 JSON)
  - Headers: `User-Agent=Mozilla/5.0..., Content-Type=application/x-www-form-urlencoded, Referer=https://www.cninfo.com.cn/new/disclosure, Origin=https://www.cninfo.com.cn`
  - Body: `stock={code},{org_id}, tabName=fulltext, pageSize={page_size}, pageNum=1, column=, category=, plate=, seDate=, searchkey=, secid=, sortName=, sortType=, isHLtitle=true`
  - `org_id` 规则 (按 code 前缀): `6xxxxx → gssh0{code}` (沪), `8/4xxxxx → gsbj0{code}` (北), 其它 → `gssz0{code}` (深)
  - 返回关键字段: `announcements[].announcementTitle, announcementTypeName, announcementTime (ms 时间戳), announcementId`
  - 派生: `date = announcementTime / 1000 → datetime → YYYY-MM-DD`, `url = https://www.cninfo.com.cn/new/disclosure/detail?annoId={announcementId}`

**Cache**: 1800s, key=`ann:{stock_code}:{page_size}`

---

### 4.13 指标目录

#### `GET /indicators/catalog` — 技术指标目录

**Server 响应字段** (`IndicatorCatalogResponse`):
- `indicators: list[IndicatorCatalogEntry]`
- Entry: `key, input_shape ("closes" | "ohlcv"), default_options, output_columns, default_lookback`

**可获取数据范围**: 14 个指标的元数据 (`ma, macd, boll, kdj, rsi, wr, bias, cci, atr, obv, roc, dmi, sar, kc`)

**数据来源**: 进程内注册表 `data_provider/indicators/registry.INDICATOR_REGISTRY`, 配合 `available_catalog()` 序列化

**Cache**: 无 (静态元数据)

**详细说明**:
- `ma` 默认 5/10/20/30/60 周期, 输出列 `ma5, ma10, ma20, ma30, ma60`
- `macd` 默认 12/26/9, 输出列 `macd_dif, macd_dea, macd_hist`
- `boll` 默认 20 周期 / 2 倍标准差, 输出列 `boll_mid, boll_upper, boll_lower, boll_bandwidth`
- `kdj` 默认 9/3/3, 输出列 `kdj_k, kdj_d, kdj_j`
- `rsi` 默认 6/12/24, 输出列 `rsi6, rsi12, rsi24`
- `wr` 默认 10/6, 输出列 `wr10, wr6`
- `bias` 默认 6/12/24, 输出列 `bias6, bias12, bias24`
- `cci` 默认 14, 输出列 `cci`
- `atr` 默认 14, 输出列 `atr`
- `obv` 无选项, 输出列 `obv`
- `roc` 默认 12/6, 输出列 `roc12, roc6`
- `dmi` 默认 14/6, 输出列 `pdi, mdi, adx, adxr`
- `sar` 默认 4 加速因子 / 2 极值 / 0.02 步长 / 0.2 最大加速, 输出列 `sar`
- `kc` 默认 20 周期 / 2 倍 ATR, 输出列 `kc_mid, kc_upper, kc_lower`

---

## 5. 附录: 失败与错误码

| HTTP 状态 | 触发场景 |
|---|---|
| 200 | 正常返回 |
| 400 | 指数代码错用 `/stocks/...` 路径; 分钟 K 线对美股/港股/指数; 指标名无效 |
| 404 | 股票 / 指数不存在, 上游无数据; 板块无成份股; 涨跌停股池当日无数据 |
| 500 | 未预期异常 (非 DataFetchError) |
| 503 | 所有支持该 capability 的 fetcher 全部失败 (`DataFetchError`), 持久化层无可用回退 |

错误响应 schema (`ErrorResponse`): `{ "error": str, "message": str }`。
