# 个股财务数据能力设计（financials / financials-history / business-composition）

> 日期：2026-10-08（rev2）
> 状态：已与用户对齐（API 形态=3 独立端点；历史口径=单季+同比，主源 zzshare；主营构成不用 akshare，改 EastMoneyFetcher 直连）
> **rev2**：两路独立评审——代码库契约审计（逐行核对签名/测试守卫）+ 上游二次实测（约 45 次真实调用）——发现并修正 13 处问题，含 3 个 P0 设计级错误（fetcher ValueError→400 链路不存在；快照空 dict 会短路 failover；`_reject_invalid_stock_code` 不是 csi 闸门）。
> 探针记录：`docs/zzshare/11-fundamentals.md`（含实测口径判定）；东财 F10 实测见本文 §2.3

## 1. 需求与边界

用户需要针对 A 股个股的三块财务数据，**不要求 1:1 透传上游表**：

1. **当前快照**：盈利（营收/净利/毛利额、EPS、ROE、毛利率/净利率、同比环比）+ 估值（PE/PB/PS/PCF/市值）；
2. **主营业务构成**：分产品/分地区/分行业的收入、成本、利润、毛利率及占比；
3. **历史周期营收、利润**：季度时间序列（单季口径 + 同比/环比）。

v1 明确不做（YAGNI）：资产负债/现金流量明细、Tushare 路径（token 无 `fina_indicator`/`income` 权限，两轮探针均实测被拒）、baostock 备源、agent batch 集成、PE 历史分位带、source slug/CamelCase 仓库分裂的清理（见 §3.1 注记）。

**北交所覆盖限制（2026-10-08 复核实测）**：zzshare 财务五表**完全不覆盖 BJ**（带 token 后 `finance_latest`/`finance_stock` 对 `920002.BJ`/`832566.BJ`/`430047.BJ` 均 0 行；全市场 `finance_indicator("2026q2")` 后缀直方图 = SZ 2896 + SH 2313 + **BJ 0**）；zhitu `/hs/fin/income`、`/hs/fin/ratios` 对 BJ 代码返回 **404 HTML**（`/hs/gs/cwzb` 虽有 BJ 4 期数据，但字段口径未校准，v1 不采用）。结论：**BJ 股票的快照/历史端点走 coherent-empty → 200 + null/[]**（诚实契约，不 404 不 503）；主营构成端点（EastMoney F10）**覆盖 BJ**（`BJ920002` 实测 90 行）。

## 2. 数据源矩阵（全部实测于 2026-10-08，样本 600519.SH / 000001.SZ / 920002.BJ）

| 块 | 主源 | 备源 | 实测要点 |
|---|---|---|---|
| 快照 | ZzshareFetcher `finance_latest(indicator)` + `finance_latest(valuation)` + `finance_stock(income, limit=1)` | ZhituFetcher `/hs/fin/income` 单上游，§2.2 差分推导（绝对额/eps/毛利/净利率/同环比）；`roe_pct` 与估值块 null | zzshare 匿名可调、多 codes 逗号分隔可用；BJ 无覆盖（§1） |
| 历史序列 | ZzshareFetcher `finance_stock(income)` + `finance_stock(indicator)` | ZhituFetcher `/hs/fin/income`，§2.2 排序→去重→差分推导管线 | zzshare 单季 86 期回溯至 2005-03-31（降序）；**zhitu fin/income 默认即 122 期（2001-06-30 起），`st/et` 可任意前取**（初稿"仅 2023 起 14 期"系探针自带 `st=20230101` 所误，复核证伪） |
| 主营构成 | EastMoneyFetcher `GET emweb.securities.eastmoney.com/PC_HSF10/BusinessAnalysis/PageAjax?code=SH600519` | 无（单源） | 600519=200 行/37 期、SZ000001=200 行、BJ920002=90 行滑窗；裸 `requests` 本网络实测也通，但实现仍复用包内既有 curl_cffi chrome120 Session（一致性 + 抗未来指纹拦截） |

### 2.1 已实测确认的上游陷阱（契约依据）

- **口径**：zzshare 季频表为**单季值**（income 600519：2026-06-30 归母 1.727437e10 < 2026-03-31 的 2.724251e10；交叉验证 zhitu 累计 H1 4.451688042186e10 − Q1 2.724251288645e10 = **1.727436753541e10，与 zzshare Q2 单季逐位吻合**）。zhitu `/hs/fin/*` 为**报告期累计值**——包括 `jbmgsy/jzcsyl/zyyrsrzz/jlrzz` 等比率字段（实测末行 H1 累计 EPS=35.57 vs 单季 13.8186），**备源链路一律不直接用 ratios**，全部单季派生量从 income 差分推导（§2.2）。
- **zhitu fin/income 的序列卫生问题（差分前提必须处理）**：默认返回**升序**，但带 `st/et` 时返回**降序**——排序不能依赖上游；122 行中约 20 个 `jzrq` **重复**（追溯修正重述行，如 2009-03-31×2、2010-06-30×2）——去重规则：同 `jzrq` 保留 `plrq` 最大的一行。
- **SDK 版本**：`finance_*` 9 法仅存在于 `zzshare>=0.4.12`（0.4.8 无）；`pyproject.toml` extra 需收紧为 `zzshare>=0.4.12,<0.5`。
- **`finance_indicator(date, codes=…)` 的 `codes=` 被静默忽略**（实测返回全市场 5209 行无报错）——单股一律走 `finance_latest` / `finance_stock`。
- **`finance_stock` 的 `limit` 是 SDK 默认值（1000）而非硬上限**（实测 `limit=3000` 完整尊重）；仅历史估值窗口需要深时传大值（v1 不消费估值历史）。
- **占位串清洗规则（两种形态）**：zhitu 上游缺失值是字符串 `"-"`（income 122 行中 16 个行业特有字段 100% 如此）**和 `"--"` 双横线**（cwzb `xsml`/`zylr` 实测）——统一规则：`safe_float` 前按"以 `-` 开头且非数字的短串视为缺失"清洗。zzshare 缺失是 `None`/NaN。
- **zhitu ratios 的滚动环比字段**（`sljlrjqhbzz`/`yyzsrgdhbzz`/`kfjlrgdhbzz`）schema 存在但实测近 6 期全为 `"-"` 且语义是滚动环比非单季——`_qoq_pct` 从差分推导（§2.2），不读 ratios 字段。
- **东财字段笔误原样存在**：`MAIN_BUSINESS_RPOFIT`、`GROSS_RPOFIT_RATIO`（复核确认真实 key，共 13 字段），解析按字面 key，禁止"纠错"。
- **东财 `REPORT_DATE`** 带 `" 00:00:00"` 尾巴；占比/毛利率是**小数**（0.8569）；金额单位**元**。
- **东财 `MAINOP_TYPE='1'`（行业行）不是每只每期都有**：600519 的行业行只在年报期出现（2026-06-30 中期无）、000001 与 BJ920002 全窗无——`?category=industry` 合法返回空集（§3.3）。

### 2.2 zhitu 单季推导管线（ZhituFetcher 备源唯一算法）

单上游 `/hs/fin/income`（不带 st/et，全量 122 期）。管线：

1. **清洗**：`"-"`/`"--"` → None（`safe_float`）；`jzrq`/`plrq` 规整为 `YYYY-MM-DD`。
2. **排序去重**：按 `jzrq` 升序；同 `jzrq` 保留 `plrq` 最大行（修正重述取最新披露）。
3. **单季差分**：`Δ(x) = 本期累计 − 上一相邻报告期累计`；Q1（`jzrq` 月=03）单季 = 累计本身。相邻关系按 (年, 季) 配对（03-31/06-30/09-30/12-31）；找不到上一期 → 该期派生字段全部 `null`。
4. **逐字段映射**：

| 契约字段 | zhitu 推导 | 公式 |
|---|---|---|
| `report_date` / `pub_date` | `jzrq` / `plrq` | 直取 |
| `total_revenue_yi` | Δ`yyzsr`（营业总收入） | ÷1e8 |
| `net_profit_yi` | Δ`jlr` | ÷1e8 |
| `net_profit_attr_yi` | Δ`gsmgsyzzdjlr` | ÷1e8 |
| `deduct_net_profit_attr_yi` | Δ`jlrhfcjcx`（扣非净利） | ÷1e8 |
| `operating_profit_yi` | Δ`yylr` | ÷1e8 |
| `eps` | Δ`jbmgsy`（累计 EPS 可差分） | 元 |
| `gross_margin_pct` | 单季值推导 | (Δ`yyzsr` − Δ`yycb`) / Δ`yyzsr` × 100 |
| `net_margin_pct` | 单季值推导 | Δ`jlr` / Δ`yyzsr` × 100 |
| `revenue_yoy_pct` / `net_profit_yoy_pct` | 单季值同比 | (Δq − Δq′)/|Δq′| × 100，q′=去年同季；缺 q′ → null |
| `revenue_qoq_pct` / `net_profit_qoq_pct` | 单季值环比 | (Δq − Δq_prev)/|Δq_prev| × 100；Q1 无环比基期 → null（见 §3.2 注） |
| `roe_pct` | **null** | 加权 ROE 不可加，差分无意义——不做近似换算 |
| 估值块 11 字段 | **null** | `/hs/fin/income` 无估值 |

> **设计原则**：宁可 null 不可近似。差分是精确代数变换（累计口径本身可加）；ROE/加权类比率不是，故诚实缺席。§3.2 的 `basis="single_quarter"` 承诺对备源同样成立。

### 2.3 主营构成上游行为

- `zygcfx[]` 行字段：`SECUCODE / SECURITY_CODE / REPORT_DATE / MAINOP_TYPE("1"行业|"2"产品|"3"地区，实测语义解码 600519：酒类/其他(补充)=行业、茅台酒/其他系列酒=产品、国内/国外=地区) / ITEM_NAME / MAIN_BUSINESS_INCOME / MBI_RATIO / MAIN_BUSINESS_COST / MBC_RATIO / MAIN_BUSINESS_RPOFIT / MBR_RATIO / GROSS_RPOFIT_RATIO / RANK`。
- 响应另含 `zyfw`/`jyps` 两块，v1 不取。
- 上游滑窗实测 600519/SZ000001 各 200 行、BJ920002 90 行、最新股样本最少 9 行；**20 只探针样本（含 ST/次新/北交所）无一返回空 `zygcfx`**——"空数组=上游权威无拆分"条款保留为防御（对应测试 fixture 用 mock 构造，真实空例缺失需注明）。
- 出站 code 是前缀式 `SH/SZ/BJ + 6 位`（与 push2 `_secid` 的 `1.600519` 式不同）。

## 3. API 契约（`/api/v1` 前缀省略）

**入站校验（两层，顺序固定）**：
1. `market_tag(code) != "csi"` → 400（HK/AAPL 类代码必须在这层拦——`_reject_invalid_stock_code` 是**正向存在性校验**，HK 股票列表入库后 `HK00700` 能通过它，不构成市场闸门）。
2. `_reject_invalid_stock_code(code, endpoint_kind=...)`（未知码/指数码 400）。**本 PR 附带修改 helper**：`_INDEX_CODE_HINT_TEMPLATES` 目前只有 `quote`/`kline` 两 key 且直接下标（`helpers.py:103-106,131`），新 kind 遇指数码会 KeyError→500；改为 `.get(endpoint_kind, "This endpoint does not serve index codes.")` 兜底，既有两 kind 行为不变。

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
  "trade_date": "2026-10-08",                                // 估值块基准（随行情日漂移）
  "pe_ttm": 19.2775, "pe_lyr": 19.1129, "pb": 6.2621, "ps": 9.0821, "pcf": 37.5276,
  "market_cap_yi": 15698.40, "float_market_cap_yi": 15698.40,
  "total_share_wan_shares": 125008.1601, "float_share_wan_shares": 125008.1601,
  "turnover_ratio_pct": 0.3066,
  "source": "ZzshareFetcher"
}
```

- `source` 取值 = `fetcher.name`（CamelCase，与 `/stocks/*` 家族既有行为一致——`test_routes.py:369` 等钉住；coherent-empty 路径 source=`""`，schema 必须容忍）。**注记：仓库存在 slug/CamelCase 分裂**（`cls.py:120-131` 走 `manager._derive_slug()` 出小写、其注释声称"CLAUDE.md requires the slug form"，而 stocks 家族出 CamelCase）——本次跟随 stocks 家族先例，分裂清理不在本 PR 范围。
- 盈利块字段来自 zzshare `finance_latest(table="indicator")`；估值块字段来自 `finance_latest(table="valuation")`；`total_revenue_yi` 例外——indicator 表无营收绝对额（18 列实测清单确认），取 `finance_stock(table="income", limit=1)` 最新行的 `total_operating_revenue`（fetcher 内部第三次调用，同一方法内完成）。
- **zhitu 备源**：跑 §2.2 推导管线，取末行。差分可给的字段（绝对额/eps/毛利率/净利率/同环比）正常输出；`roe_pct` 与估值块 `null`。**无任何可用字段时返回 `None`，禁止返回 `{}`**——`_is_meaningful({})` 为 True（`manager.py:27-33`），空 dict 会被 failover 链当成功短路（P0 修正）。
- 模型：`FinancialSnapshotResponse`（`api/schemas.py`）。

### 3.2 `GET /stocks/{code}/financials/history?start_date=&end_date=`

- `start_date`/`end_date` 按**报告期**（`statDate`/`jzrq`）过滤，`YYYY-MM-DD` 或 `YYYYMMDD`；缺省 = 最近 **12 个报告期**（zzshare `finance_stock(limit=12)`；zhitu 推导全量后本地裁 12 期）。
- **日期格式校验在 route handler body 内做**（先例 `cls.py::_validate_date`），非法格式 → `ValueError` → `map_errors` 400。**禁止把参数校验下沉到 fetcher**——见 §6 异常语义（fetcher 抛的 ValueError 会被 `_with_failover` 吞成 503）。
- 行按 `report_date` **升序**（zzshare 上游降序、zhitu 默认升序/带 st·et 降序，统一在 fetcher 边界重排，与 K 线惯例一致）。

```jsonc
{
  "code": "600519", "name": "贵州茅台", "basis": "single_quarter",
  "total": 2, "source": "ZzshareFetcher",
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

- 绝对额来自 `finance_stock(income)`（`total_operating_revenue/np_parent_company_owners/operating_profit/net_profit`，元→亿）；`deduct_net_profit_attr_yi` 来自 indicator 的 `adjusted_profit`（income 的 `deduct_parent_net_profit` 两轮探针实测恒 None）；比率/增长 8 项来自 `finance_stock(indicator)`，按 `statDate` join。
- **zhitu 备源**：§2.2 管线全量输出（同环比可推导、`roe_pct` null）。`basis` 字段恒 `"single_quarter"`——主备两源都是单季口径，这是契约承诺。
- **Q1 的 `_qoq_pct`**：单季环比对 Q1 无意义（上一季是去年 Q4，非连续经营季）——**保留真实环比值还是 null 由实现期一个决定点定死并写进测试**：本 spec 定为**保留**（zzshare `inc_revenue_annual` 对 Q1 也给去年 Q4 环比，主备一致优先于语义洁癖）。
- 模型：`FinancialHistoryResponse` / `FinancialHistoryRecord`。

### 3.3 `GET /stocks/{code}/business-composition?category=&report_date=`

- `category ∈ product|region|industry`（省略=全部；对应 `MAINOP_TYPE` 2/3/1）。行业行按 §2.1 存在性缺失，`?category=industry` 对合法股票可**正常返回 200 + `records: []`**。
- `report_date` 缺省=滑窗内最新报告期。**校验在路由层（P0 修正）**：fetcher 返回的 dict 携带 `available_report_dates`（去重升序）与 `requested_report_date_available: bool|None`（用户未指定时 None）；fetcher **不抛参数异常**，路由检查标志后自行 `raise HTTPException(400, detail={"error": "invalid_request", "message": "...available from X to Y"})`。原因：fetcher 内 raise 的 `ValueError` 会被 `_with_failover` 无差别捕获（`manager.py:374-381`）折成 503，永远到不了 `map_errors` 的 400 分支。

```jsonc
{
  "code": "600519", "name": "贵州茅台", "report_date": "2026-06-30",
  "total": 3, "source": "EastMoneyFetcher",
  "records": [
    { "category": "product", "item": "茅台酒", "rank": 1,
      "revenue_yi": 777.24, "revenue_share_pct": 85.69,
      "cost_yi": 60.01, "cost_share_pct": 63.34,
      "profit_yi": 717.24, "profit_share_pct": 88.30, "gross_margin_pct": 92.28 },
    { "category": "region", "item": "国内", "...": "..." }
  ]
}
```

- 单源无 failover；上游空滑窗（防御条款，见 §2.3）→ 200 + `records: []` + `report_date: null`。
- fetcher 返回 dict 形状：`{"report_date": str|None, "records": list[dict], "available_report_dates": list[str], "requested_report_date_available": bool|None}`；过滤职责（先 `report_date` 缺省取最新、再 `category`）在 fetcher 内；`available_report_dates` 与 `requested_report_date_available` **不泄漏进公开 schema**。
- 模型：`BusinessCompositionResponse` / `BusinessCompositionRecord`。列表字段名跟仓库先例用 `records`（`api/schemas.py` 十余处；`entries` 无先例），行数用 `total`（同上）。

### 3.4 路由栈（三端点相同，遵守既有装饰器铁律）

```python
@router.get(
    "/stocks/{stock_code}/financials",
    response_model=FinancialSnapshotResponse,
    responses={
        503: {"model": ErrorResponse, "description": "Data unavailable"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["stocks"],
)
@endpoint_meta(
    summary="财务快照",                      # keyword-only（endpoint_meta.py:59-66），位置传参会 import 期 TypeError
    markets=["csi"],
    capabilities=["STOCK_FINANCIAL"],
)
@map_errors
@cache_endpoint(
    cache_fn=lambda *args, **kwargs: get_financial_snapshot_cache(),
    key_builder=lambda stock_code: make_financial_snapshot_cache_key(stock_code),
    hit_label="financial_snapshot",
)
def get_financials(stock_code: str = Path(max_length=20)) -> FinancialSnapshotResponse: ...
```

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

**同步硬约束**：每个新 flag 还必须在 `stock_data/explorer/tags.py::CAPABILITY_LABELS` 有 `{label, icon}` 条目——`tests/test_capability_method_map.py::test_every_capability_is_in_capability_labels`（及 `test_every_capability_is_in_capability_labels` 的前身）直接钉住，缺失即红。HTML `CAPABILITY_GROUPS` 已废弃（37e52ed），无需动 HTML。

### 4.2 Manager 公开方法（全部 `_route_cap` 样板，market 固定 `"csi"`）

```python
get_financial_snapshot(code) -> tuple[dict|None, str]                    # 链: zzshare(P2) → zhitu(P5)
get_financial_history(code, start_date=None, end_date=None) -> tuple[list[dict], str]  # 链同上
get_main_business_composition(code, category=None, report_date=None) -> tuple[dict, str]  # 链: eastmoney 单源
```

- **空值协议（P0 修正，逐端点定死）**：快照 fetcher 无可用字段时必须返回 **`None`**（`{}` 会被 `_is_meaningful` 判真短路整条链）；历史返回 **`[]`**（list 空值能正确 fall-through）；主营构成单源，空滑窗返回**完整 dict**（`records: []`）即为权威答案，走成功路径。`empty_is_failure` 三方法均保持默认 False：新股无报告期 = 诚实空答案 → `_with_failover` coherent-empty 返回 `(last_empty, "")`——**路由层 `source` 字段收到 `""` 是设计内行为**，schema `source: str = ""` 天然容忍；不给财务链开 `empty_is_failure`——东财对无拆分数据股票的权威空集会被误判为软失败。
- 快照/历史在 zzshare fetcher 方法内部做 2-3 次 SDK 调用；**任一上游调用抛错 → fetcher 方法 raise `DataFetchError`**（部分字段成功不算成功），由 manager 降级下一源。不做字段级拼装跨源。
- **fetcher 层的唯一异常语言是 `DataFetchError`**（`manager.py:374-381` 无差别捕获一切异常折进 failover 链）；参数校验型错误一律在 route handler body 抛（§3.2/§3.3）。

### 4.3 Fetcher 方法规格

| Fetcher | 新方法 | 上游 |
|---|---|---|
| `ZzshareFetcher` | `get_financial_snapshot` / `get_financial_history` | `finance_latest("indicator")` + `finance_latest("valuation")` + `finance_stock("income"/"indicator")`；代码经 `_to_zzshare_ts_code`（outbound-only）；BJ 恒空（§1），方法内 0 行 → None/[] |
| `ZhituFetcher` | 同上两个 | **仅** `/hs/fin/income`（全量 122 期）+ §2.2 推导管线（快照与历史共用，快照取末行）。**不用** `/hs/gs/cwzb`、`/hs/fin/ratios`（累计口径陷阱 §2.1 + BJ 404 + `xsml="--"`，v1 弃用）；代码后缀沿用既有 zhitu 出站 helper |
| `EastMoneyFetcher` | `get_main_business_composition` | 新增 `_emweb_query()`：**单请求，无分页，不 sleep**（初稿"沿用 board clist 1-2s 延迟"错误——那是 `_boards_mixin` 翻页间 delay，照抄即凭空加 1-2s）；复用 curl_cffi chrome120 Session，但**错误处理不复用 `_datacenter_query` 的吞异常返 `[]` 先例**（`fetcher.py:124-128`）——非 200/解析失败必须 raise `DataFetchError`，否则单源链的 503 语义失效；`_endpoints.py` 增 URL；新增 `to_emweb_f10_code()`（SH/SZ/BJ 前缀式，注释标注 outbound-only） |

三个 fetcher 各自 `supported_data_types |= 新 flag`。方法返回**已是项目契约字段名 + 已换算单位 + 占位串清洗**的 dict/list[dict]（fetcher 边界完成换算，manager/route 不碰原始字段）。响应中的股票代码（`code` 字段）一律裸 6 位码（入站/出站边界铁律）。

## 5. 缓存与配置

- `api/cache.py` 新增：`_TTL_STOCK_FINANCIAL = int(os.getenv("CACHE_TTL_STOCK_FINANCIAL", "86400"))`（财报季频，24h 足够捕捉新披露；与 `CACHE_TTL_DIVIDEND=300` 不同档的理由：分红接口上游按日更新，财报表按季度）；三个 TTLCache 槽（maxsize=512/512/256）+ `get_*_cache()` + `make_*_cache_key()`。
- **键内代码一律 `normalize_stock_code()`**（先例 `make_news_stock_cache_key`，`cache.py:270-273`；dividend 的不归一化是历史遗留，不跟）：
  - `fin:{normalized}`
  - `finhist:{normalized}:{start or ''}:{end or ''}`
  - `bizcomp:{normalized}:{category or 'all'}:{report_date or 'latest'}`（category/report_date 必须入键——仿 filter-stocks 的 limit 教训）
- `.env.example` 增 `CACHE_TTL_STOCK_FINANCIAL` 注释行；`pyproject.toml`：`zzshare = ["zzshare>=0.4.12,<0.5"]`。
- 不进 SQLite（上游数据非元数据；既有"实时数据不落 SQLite"惯例的延伸）。

## 6. 错误语义

- `market_tag != "csi"` → 400；未收录代码/指数码 → `_reject_invalid_stock_code` 400（`invalid_request` 体；指数码消息用新兜底文案，不指向不存在的 `/indices/{code}/financials`）。
- **异常翻译的唯一边界是 handler**：fetcher 内抛的任何异常（含 ValueError）都被 `_with_failover` 捕获进链，最终折成 `DataFetchError` → 503。因此**所有 400 类输入错误**（日期格式、report_date 不在滑窗）必须由 route handler 抛出；fetcher 公开方法体内禁止 `raise ValueError`（review P0-1 教训，实现期 grep 守卫）。
- 全链失败（有 raise 记录）→ `DataFetchError` → 503；全链空（无 raise）→ coherent-empty → 200 + null/[] + `source=""`；**未知≠0**。
- BJ 股票快照/历史 = 200 + 空契约（§1）；主营构成 `category=industry` 合法空集 = 200 + `records: []`；东财反爬失败（非 200/解析异常）→ `_emweb_query` raise `DataFetchError` → 单源链 → 503。

## 7. 测试计划（fixtures 一律取自本文 §2 的真实探针响应——字段名/类型/单位/笔误/占位串形态与真实上游一致；唯一例外是空 `zygcfx` mock，见 §2.3）

1. **单测 — ZzshareFetcher**：快照 merge（3 调用）、`codes=` 陷阱回归（确认代码路径只用 latest/stock）、None/NaN → null、降序→升序、单位换算、**BJ 0 行 → 快照返回 None / 历史返回 []**（防 `{}` 短路回归）。
2. **单测 — ZhituFetcher**：§2.2 管线全量：真实 fixture（122 期含约 20 个重复 `jzrq`、`"-"` 与 `"--"` 双形态占位串、默认升序输入）→ 断言去重保留 max-plrq 行；**差分换算用实测精确数：Q1 累计 2.724251288645e10 / H1 累计 4.451688042186e10 → Q2 单季 1.727436753541e10**；roe_pct/估值 null；缺上一期 → 该行 null；st/et 降序输入与默认升序输出去重排序后结果一致。
3. **单测 — EastMoneyFetcher**：`MAIN_BUSINESS_RPOFIT` 笔误 key、小数×100、元→亿、`REPORT_DATE` 截尾、MAINOP_TYPE 映射（行业行缺失的股票 → records 无 industry 项）、非 200 → raise `DataFetchError`（**不复用吞异常先例**）、空 `zygcfx`（mock）→ `records: []`。
4. **manager 路由测**：failover 顺序 zzshare→zhitu（zzshare 返回 None 触发、`{}` 不触发的双守卫）；`*_ENABLED=false` 链收缩；单源 eastmoney 失败 raise；BJ 代码全链空 → coherent-empty `(空, "")`。
5. **route 测（TestClient + monkeypatch manager）**：非 csi（`HK00700`）→400、未知码→400、指数码（`000300`）→400 走兜底文案（新 endpoint_kind 不 KeyError）、503、coherent-empty→200+null+`source=""`、缓存键区分（normalize 后 `SH600519` 与 `600519` 同键；category/report_date/start/end 差异入键）、`report_date` 非法→400（路由层标志）、schema 可空字段断言。
6. **`tests/test_capability_method_map.py` 侧**：3 新 flag 的 `CAPABILITY_TO_METHOD` + `explorer/tags.py::CAPABILITY_LABELS` 双同步（该文件既有测试会自动红）；`docs/zzshare/README.md` 映射行随实现更新。

## 8. 文档同步清单（实现 PR 内一并完成）

- `api-reference.md`：3 端点契约（含单位表、null 语义、BJ 限制——契约面向消费者，不写主备链路）。
- `CLAUDE.md`：Fetcher overview 表（Zzshare/Zhitu/EastMoney 三行 capabilities 增补）、API→Capability routing 表 3 行、Configuration 节 `CACHE_TTL_STOCK_FINANCIAL`、"Dragon-Tiger empty-fall-through"式的一条财务链异常边界注记（fetcher 禁抛 ValueError）。
- `stock_data/api/routes/helpers.py`：`_INDEX_CODE_HINT_TEMPLATES` 下标改 `.get()` 兜底 + 注释。
- `stock_data/explorer/tags.py`：`CAPABILITY_LABELS` 3 条 `{label, icon}`。
- `docs/source-tracking.md`：3 端点矩阵行（source=CamelCase `fetcher.name`，含 `""` empty 情形）；不动既有行（slug/CamelCase 分裂注记留在此文件顶注，另行清理）。
- 三个 fetcher 模块 docstring：上游端点规格（URL/字段/单位/限速/实测陷阱/BJ 覆盖）。
- `docs/zzshare/README.md` 能力映射行改指向实际 flag。

## 9. 分支与提交

Python 代码走 `feat/stock-financials` 分支 + PR；纯文档（CLAUDE.md / api-reference.md / helpers 注释）并入同 PR（代码分支上的文档随代码评审）。

## 10. 评审修订记录（rev1 → rev2）

- **P0**：§3.3 report_date 校验从 fetcher 上移路由层（`_with_failover` 吞 ValueError，400 链路不存在）；快照空返回定死 `None` 非 `{}`（`_is_meaningful` 语义）；入站校验补 `market_tag` 前置闸门 + `_reject_invalid_stock_code` 新 kind KeyError 修复。
- **P1**：cls.py 引证错误已改（该注释主张 slug 并走 `_derive_slug`，与 stocks 家族 CamelCase 并存——分裂如实注记，本次跟 stocks 先例）；§8 补 `CAPABILITY_LABELS` 硬约束；§3.4 伪码改 keyword-only 实样。
- **P2**：`entries`/`count` → `records`/`total`；`stock_code` 措辞消歧；`"-"`/`"--"` 双形态清洗；zhitu 备源改为 **income 单上游差分推导**（消除 ratios 累计口径违宪 + 三处字段矩阵自相矛盾），YoY/QoQ 可推导故不再置 null、ROE 不可导故 null；缓存键 normalize；`_emweb_query` 无 delay + 不吞异常。
- **上游复核**：BJ 零覆盖（§1）、zhitu 122 期深度（删"备源受限"）、重复 jzrq/排序方向陷阱（§2.2）、空 `zygcfx` 无实例（防御条款 + mock 注记）、行业行合法空集（§3.3）、`limit=3000` 无硬上限（§2.1）、差分交叉数升级为一逐位吻合（§2.1）。
