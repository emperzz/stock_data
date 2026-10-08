# 个股财务数据能力设计（financials / financials-history / business-composition）

> 日期：2026-10-08
> 状态：已与用户对齐（API 形态=3 独立端点；历史口径=单季+同比，主源 zzshare；主营构成不用 akshare，改 EastMoneyFetcher 直连）
> 探针记录：`docs/zzshare/11-fundamentals.md`（含实测口径判定）；东财 F10 实测见本文 §2.3

## 1. 需求与边界

用户需要针对 A 股个股的三块财务数据，**不要求 1:1 透传上游表**：

1. **当前快照**：盈利（营收/净利/毛利额、EPS、ROE、毛利率/净利率、同比环比）+ 估值（PE/PB/PS/PCF/市值）；
2. **主营业务构成**：分产品/分地区/分行业的收入、成本、利润、毛利率及占比；
3. **历史周期营收、利润**：季度时间序列（单季口径 + 上游自带同比/环比）。

v1 明确不做（YAGNI）：资产负债/现金流量明细、Tushare 路径（token 无 `fina_indicator`/`income` 权限，实测被拒）、baostock 备源、agent batch 集成、PE 历史分位带。

## 2. 数据源矩阵（全部实测于 2026-10-08，样本 600519.SH / 000001.SZ / BJ920002）

| 块 | 主源 | 备源 | 实测要点 |
|---|---|---|---|
| 快照 | ZzshareFetcher `finance_latest(indicator)` + `finance_latest(valuation)` | ZhituFetcher `/hs/fin/ratios` 末行 + `/hs/gs/cwzb`（仅盈利字段，估值=null） | zzshare 匿名可调、多 codes 逗号分隔可用 |
| 历史序列 | ZzshareFetcher `finance_stock(income)` + `finance_stock(indicator)` | ZhituFetcher `/hs/fin/income`（累计→单季差分）+ `/hs/fin/ratios` | zzshare 单季 86 期回溯至 2005；zhitu fin/income 实测仅 2023 起 14 期 |
| 主营构成 | EastMoneyFetcher `GET emweb.securities.eastmoney.com/PC_HSF10/BusinessAnalysis/PageAjax?code=SH600519` | 无（单源） | curl_cffi chrome120 实测 200 行多报告期滑窗；BJ 可用；个别股票空 `zygcfx` |

### 2.1 已实测确认的上游陷阱（契约依据）

- **口径**：zzshare 季频表为**单季值**（income 2026-06-30 归母 1.727e10 < 2026-03-31 2.724e10；且 zhitu 累计 H1 4.452e10 − Q1 2.724e10 = 1.728e10 交叉吻合）。zhitu `/hs/fin/*` 为**报告期累计值**。
- **SDK 版本**：`finance_*` 9 法仅存在于 `zzshare>=0.4.12`（0.4.8 无）；`pyproject.toml` extra 需收紧为 `zzshare>=0.4.12,<0.5`。
- **`finance_indicator(date, codes=…)` 的 `codes=` 被静默忽略**返回全市场 5209 行——单股一律走 `finance_latest` / `finance_stock`。
- **zhitu 缺失值是字符串 `"-"`**（如 `xsmgsy: "-"`），须过 `safe_float`；zzshare 缺失是 `None`/NaN。zhitu `/hs/gs/cwzb` 的 `xsml`（销售毛利率）对 600519 实测为 `"-"`，毛利率取 `/hs/fin/ratios` 的 `mlv`/`xsmlv`。
- **东财字段笔误原样存在**：`MAIN_BUSINESS_RPOFIT`、`GROSS_RPOFIT_RATIO`（akshare 内部同源保留），解析按字面 key，禁止"纠错"。
- **东财 `REPORT_DATE`** 带 `" 00:00:00"` 尾巴；占比/毛利率是**小数**（0.8569）；金额单位**元**。

### 2.2 单季差分换算（ZhituFetcher 备源用）

zhitu fin/income 行按 `jzrq` 升序后：`单季 = 本期累计 − 上一相邻报告期累计`；Q1 单季 = Q1 累计本身。报告期序列以 `jzrq` 月份判定（03-31/06-30/09-30/12-31）。缺上一期时该期绝对字段输出 `null`（不外推、不填 0）。

### 2.3 主营构成上游行为

- `zygcfx[]` 行字段：`SECUCODE / SECURITY_CODE / REPORT_DATE / MAINOP_TYPE("1"行业|"2"产品|"3"地区) / ITEM_NAME / MAIN_BUSINESS_INCOME / MBI_RATIO / MAIN_BUSINESS_COST / MBC_RATIO / MAIN_BUSINESS_RPOFIT / MBR_RATIO / GROSS_RPOFIT_RATIO / RANK`。
- 响应另含 `zyfw`/`jyps` 两块，v1 不取。
- 上游默认滑窗约 200 行（BJ920002 实测 90 行）；`zygcfx` 为空数组 = 上游无该股拆分数据 → **200 + `entries: []`**，不报错。
- 出站 code 是前缀式 `SH/SZ/BJ + 6 位`（与 push2 `_secid` 的 `1.600519` 式不同）。

## 3. API 契约（`/api/v1` 前缀省略；三端点仅 csi，非 A 股代码一律 `_reject_invalid_stock_code` → 400）

单位策略（全局一致）：金额 `_yi`=亿元、比率 `_pct`=百分数（89.48 即 89.48%）、股本 `_wan_shares`=万股、EPS/每股=元、PE/PB/PS/PCF 裸倍数。可空字段 null = 该源不提供或上游缺失，**永不 0 填充**。

### 3.1 `GET /stocks/{code}/financials`

```jsonc
{
  "code": "600519", "name": "贵州茅台",
  "report_date": "2026-06-30", "pub_date": "2026-08-15",   // 盈利块基准
  "eps": 13.8186, "roe_pct": 6.62,                          // 单季口径
  "total_revenue_yi": 375.75, "net_profit_attr_yi": 172.74, "deduct_net_profit_attr_yi": 172.24,
  "gross_margin_pct": 89.48, "net_margin_pct": 48.59,
  "revenue_yoy_pct": -5.14, "net_profit_yoy_pct": -6.94,
  "revenue_qoq_pct": -31.75, "net_profit_qoq_pct": -36.49,
  "trade_date": "2026-09-30",                                // 估值块基准
  "pe_ttm": 19.3209, "pe_lyr": 19.1129, "pb": 6.2621, "ps": 9.0821, "pcf": 37.5276,
  "market_cap_yi": 15733.777, "float_market_cap_yi": 15733.777,
  "total_share_wan_shares": 125008.1601, "float_share_wan_shares": 125008.1601,
  "turnover_ratio_pct": 0.3066,
  "source": "ZzshareFetcher"
}
```

- `source` 取值 = `fetcher.name`（`"ZzshareFetcher"` 等 CamelCase，与 `routes/cls.py:122` 注释一致；`docs/source-tracking.md` 表格里的 `tushare`/`eastmoney` 小写示例是文档自身欠准，实现 PR 只追加矩阵行、不改既有行）。
- 盈利块字段来自 zzshare `finance_latest(table="indicator")`；估值块字段来自 `finance_latest(table="valuation")`；`total_revenue_yi` 例外——indicator 表无营收额，取 `finance_stock(table="income", limit=1)` 最新行的 `total_operating_revenue`（fetcher 内部第三次调用，同一方法内完成）。
- **zhitu 备源**：盈利字段取 `/hs/fin/ratios` 末行（`jbmgsy→eps`、`jzcsyl→roe_pct`、`mlv→gross_margin_pct`、`jlv→net_margin_pct`、`zyyrsrzz→revenue_yoy_pct`、`jlrzz→net_profit_yoy_pct`、`jzrq→report_date`、`plrq→pub_date`）+ `/hs/fin/income` 末行差分项取归母净利；环比/扣非/估值字段 `null`。响应 `source="ZhituFetcher"`。
- 模型：`FinancialSnapshotResponse`（`api/schemas.py`）。

### 3.2 `GET /stocks/{code}/financials/history?start_date=&end_date=`

- `start_date`/`end_date` 按**报告期**（`statDate`）过滤，`YYYY-MM-DD` 或 `YYYYMMDD`；缺省 = 最近 **12 个报告期**（`limit=12` 于 zzshare `finance_stock`；zhitu 备源取全量后本地裁 12 期）。
- 行按 `report_date` **升序**（zzshare 上游降序，fetcher 边界反转，与 K 线惯例一致）。

```jsonc
{
  "code": "600519", "name": "贵州茅台", "basis": "single_quarter",
  "count": 2, "source": "ZzshareFetcher",
  "records": [
    { "report_date": "2026-03-31", "pub_date": "2026-04-25",
      "total_revenue_yi": 547.03, "net_profit_yi": 281.54, "net_profit_attr_yi": 272.43,
      "operating_profit_yi": 375.37, "deduct_net_profit_attr_yi": 272.40,
      "eps": 21.7545, "roe_pct": 10.57, "gross_margin_pct": 89.91, "net_margin_pct": 52.22,
      "revenue_yoy_pct": 6.54, "net_profit_yoy_pct": 1.37,
      "revenue_qoq_pct": 33.49, "net_profit_qoq_pct": 52.91 },
    { "report_date": "2026-06-30", "pub_date": "2026-08-15", "...": "..." }
  ]
}
```

- 绝对额 4 项来自 `finance_stock(income)`（`total_operating_revenue/np_parent_company_owners/operating_profit/net_profit`，元→亿）；`deduct_net_profit_attr_yi` 来自 indicator 的 `adjusted_profit`（income 的 `deduct_parent_net_profit` 实测恒 None）；比率/增长 8 项来自 `finance_stock(indicator)`，按 `statDate` join。
- **zhitu 备源**：`/hs/fin/income` 差分换算（§2.2）出绝对额，`/hs/fin/ratios` 直接映射比率；zhitu 无单季环比 → `_qoq_pct` 为 null。`basis` 字段恒为 `"single_quarter"`（契约承诺，即便走备源）。
- 模型：`FinancialHistoryResponse` / `FinancialHistoryRecord`。

### 3.3 `GET /stocks/{code}/business-composition?category=&report_date=`

- `category ∈ product|region|industry`（省略=全部；对应 `MAINOP_TYPE` 2/3/1）；`report_date` 缺省=滑窗内最新报告期，指定时须在返回滑窗内存在，否则 fetcher raise `ValueError` → `map_errors` 现有约定 → **400**（消息含可用期首尾；非 `_reject_invalid_stock_code` 的 `invalid_request` 体）。

```jsonc
{
  "code": "600519", "name": "贵州茅台", "report_date": "2026-06-30", "source": "EastMoneyFetcher",
  "entries": [
    { "category": "product", "item": "茅台酒", "rank": 1,
      "revenue_yi": 777.24, "revenue_share_pct": 85.69,
      "cost_yi": 60.01, "cost_share_pct": 63.34,
      "profit_yi": 717.24, "profit_share_pct": 88.30, "gross_margin_pct": 92.28 },
    { "category": "region", "item": "国内", "...": "..." }
  ]
}
```

- 单源无 failover；上游空滑窗 → 200 + `entries: []` + `report_date: null`。
- `get_main_business_composition` 的 fetcher 返回 dict 形状为
  `{"report_date": str|None, "entries": list[dict], "available_report_dates": list[str]}`。
  过滤职责在 fetcher 内：先按 `report_date`（缺省=滑窗内最新期）、再按 `category`；
  **指定了滑窗内不存在的 `report_date` → fetcher raise `ValueError`**（消息含可用期首尾），
  由 `map_errors` 现有约定映射为 400 —— 与 kline 参数校验同一条路，路由层不再自行比对。
  `available_report_dates` 只是响应 dict 的内部附带项，**不泄漏进公开 schema**
  （`BusinessCompositionResponse` 不含该字段）。空滑窗时三值分别为 `None / [] / []`。
- 模型：`BusinessCompositionResponse` / `BusinessCompositionEntry`。

### 3.4 路由栈（三端点相同，遵守既有装饰器铁律）

`@router.get(response_model, responses={503,500}, tags=["stocks"]) → @endpoint_meta(summary, markets=["csi"], capabilities=[...]) → @map_errors → @cache_endpoint(...) → def handler`。
`capabilities` 分别声明 `["STOCK_FINANCIAL"]` / `["STOCK_FINANCIAL_SERIES"]` / `["STOCK_MAIN_BUSINESS"]`；无需 `fetcher_method` override（默认方法名与 capability 一对一）。

## 4. Capability 与 Manager 层

### 4.1 新 flag（`data_provider/base.py`）

```python
STOCK_FINANCIAL = auto()          # 财务快照（盈利+估值）
STOCK_FINANCIAL_SERIES = auto()   # 单季历史序列
STOCK_MAIN_BUSINESS = auto()      # 主营业务构成

CAPABILITY_TO_METHOD = {
    ...,
    DataCapability.STOCK_FINANCIAL: "get_financial_snapshot",
    DataCapability.STOCK_FINANCIAL_SERIES: "get_financial_history",
    DataCapability.STOCK_MAIN_BUSINESS: "get_main_business_composition",
}
```

### 4.2 Manager 公开方法（全部 `_route_cap` 样板，market 固定 `"csi"`）

```python
get_financial_snapshot(code) -> tuple[dict, str]                 # 链: zzshare(P2) → zhitu(P5)
get_financial_history(code, start_date=None, end_date=None) -> tuple[list[dict], str]  # 链同上
get_main_business_composition(code, category=None, report_date=None) -> tuple[dict, str]  # 链: eastmoney 单源
```

- 三方法 `empty_is_failure` 用默认 False：新股无报告期 = 诚实空答案（zzshare 空 → zhitu 也空 → `_with_failover` 的 coherent-empty 路径返回空 dict/list，路由层转 200 + null/[]）。不给财务链开 `empty_is_failure`——东财对无拆分数据股票的**权威空集**会被误判为软失败。
- 快照/历史在 zzshare fetcher 方法内部做 2-3 次 SDK 调用；**任一上游调用抛错 → fetcher 方法 raise**（部分字段成功不算成功），由 manager 降级下一源。不做字段级拼装跨源。

### 4.3 Fetcher 方法规格

| Fetcher | 新方法 | 上游 |
|---|---|---|
| `ZzshareFetcher` | `get_financial_snapshot` / `get_financial_history` | `finance_latest("indicator")` + `finance_latest("valuation")` + `finance_stock("income"/"indicator")`；代码经 `_to_zzshare_ts_code`（outbound-only） |
| `ZhituFetcher` | 同上两个 | `/hs/fin/ratios`、`/hs/fin/income`（差分 §2.2）、`/hs/gs/cwzb`；`to_zhitu_...suffix` 出站 |
| `EastMoneyFetcher` | `get_main_business_composition` | 新增 `_emweb_query(PageAjax)` helper：复用现有 curl_cffi chrome120 Session，沿用 board clist 同款 1-2s 延迟；`_endpoints.py` 增 URL；新增 `to_emweb_f10_code()`（SH/SZ/BJ 前缀式，仿 `_to_zzshare_ts_code` 的注释规范标注 outbound-only） |

三个 fetcher 各自 `supported_data_types |= 新 flag`。方法返回**已是项目契约字段名 + 已换算单位 + safe_float 清洗**的 dict/list[dict]（fetcher 边界完成换算，manager/route 不碰原始字段）。响应中的 `stock_code` 一律裸 6 位码（入站/出站边界铁律）。

## 5. 缓存与配置

- `api/cache.py` 新增：`_TTL_STOCK_FINANCIAL = int(os.getenv("CACHE_TTL_STOCK_FINANCIAL", "86400"))`（财报季频，24h 足够捕捉新披露；与 `CACHE_TTL_DIVIDEND=300` 不同档的理由：分红接口上游按日更新，财报表按季度）；三个 TTLCache 槽（maxsize=512/512/256）+ `get_*_cache()` + `make_*_cache_key()`：
  - `fin:{code}`
  - `finhist:{code}:{start or ''}:{end or ''}`
  - `bizcomp:{code}:{category or 'all'}:{report_date or 'latest'}`（category/report_date 必须入键——仿 filter-stocks 的 limit 教训）
- `.env.example` 增 `CACHE_TTL_STOCK_FINANCIAL` 注释行；`pyproject.toml`：`zzshare = ["zzshare>=0.4.12,<0.5"]`。
- 不进 SQLite（上游数据非元数据；既有"实时数据不落 SQLite"惯例的延伸）。

## 6. 错误语义

- 非 A 股代码 / 未收录代码 → 400 `invalid_request`（`_reject_invalid_stock_code`，与 kline/quote 同一 helper）。
- 全链失败 → `DataFetchError` → 503（`map_errors` 现有映射）。
- 上游 HTTP 200 但数据为空 → 200 + 空契约（见 §4.2）；**未知≠0**。
- 东财 `zygcfx` 空 → 200 + `entries: []`；`?report_date=` 不在滑窗 → `ValueError` → 400；东财反爬失败（4xx/指纹拦截）→ 该 fetcher raise `DataFetchError` → 单源链 → 503（`map_errors` 的 ValueError 契约要求：fetcher 内 ValueError 只用于客户输入校验，上游故障必须用 `DataFetchError`，见 `errors.py` 头部）。

## 7. 测试计划（fixtures 一律取自本文 §2 的真实探针响应——字段名/类型/单位/笔误与真实上游一致）

1. **单测 — ZzshareFetcher**：快照 merge（3 调用）、`codes=` 静默忽略陷阱回归（确认代码路径只用 latest/stock）、None/NaN → null、降序→升序、单位换算。
2. **单测 — ZhituFetcher**：`"-"` → safe_float → null；**差分换算用例：fixture 用实测累计行（Q1 2.724e10 / H1 4.452e10 → H1 单季 1.728e10±ε）**；缺上期 → null；快照估值块全 null。
3. **单测 — EastMoneyFetcher**：`MAIN_BUSINESS_RPOFIT` 笔误 key、小数×100、元→亿、`REPORT_DATE` 截尾、MAINOP_TYPE 映射、空 `zygcfx` → `entries: []`、非法 report_date → 400。
4. **manager 路由测**：failover 顺序 zzshare→zhitu；`*_ENABLED=false` 时链自动收缩；单源 eastmoney 失败 raise。
5. **route 测（TestClient + monkeypatch manager）**：三端点 400（HK00700 / 未知码 / index 码走既有重定向消息分支）、503、缓存键区分（category/report_date/start/end）、响应 schema 可空字段。
6. **`tests/test_capability_method_map.py`**：新 flag 入图即自动把关；确认 `docs/zzshare/README.md` 映射行随实现更新（当前写"无现成 capability，待 STOCK_FINANCIAL"）。

## 8. 文档同步清单（实现 PR 内一并完成）

- `api-reference.md`：3 端点契约（含单位表、null 语义、MD 渲染不涉及——非 agent 端点）。
- `CLAUDE.md`：Fetcher overview 表（Zzshare/Zhitu/EastMoney 三行 capabilities + 新方法）、API→Capability routing 表 3 行、Configuration 节 `CACHE_TTL_STOCK_FINANCIAL`。
- `docs/source-tracking.md`：3 端点覆盖矩阵行。
- `ZzshareFetcher`/`ZhituFetcher`/`EastMoneyFetcher` 模块 docstring：上游端点规格（URL/字段/单位/限速/实测陷阱）。
- `docs/zzshare/README.md` 映射行改指向实际 flag。

## 9. 分支与提交

Python 代码走 `feat/stock-financials` 分支 + PR；纯文档（CLAUDE.md / api-reference.md 的段落）可并入同 PR（代码分支上的文档随代码评审）。
