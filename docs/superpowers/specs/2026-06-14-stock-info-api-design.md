# 公司画像 API（GET /stocks/{code}/info）设计文档

> 日期：2026-06-14
> 状态：待审
> 范围：新增 `STOCK_INFO` capability + 对应 REST 端点，数据来自 Zhitu (主) / Myquant (备) failover

## 1. 目标与范围

在 server 上新增「公司画像」端点，让调用方通过 `GET /stocks/{code}/info` 拿到 A 股上市公司的归一化基础信息（上市日期、概念标签、经营范围、注册地、董秘、总股本等）。

**只做这一次**。不包含：
- 财务三表（`/stocks/{code}/fundamentals/financials`）—— 留待后续 spec
- 港股 / 美股 —— 本次 csi-only
- 雪球 (`ak.stock_individual_basic_info_xq`) —— 该 API 依赖雪球私有 token（已实测不可用，错误码 `400016`），按用户 2026-06-14 决定放弃 AkshareFetcher 路径
- 板块/行业分类树 —— 由现有 `/boards/*` 系列承担
- 董秘任职历史 / 公告 —— 由现有 `/stocks/{code}/announcements` 承担

## 2. 使用的上游 API

### 2.1 Zhitu —— `https://api.zhituapi.com/hs/gs/gsjj/{code}?token={token}`

- 鉴权：`ZHITU_TOKEN` 环境变量
- 频率：低频（公司基础信息变化慢）
- 文档：`stock_data/docs/zhitu/04-listed-company-details.md`
- 端点已文档化但**当前 ZhituFetcher 未实现**

**返回字段**（核心，本设计用到的）：
- 识别：`name`, `ename`, `market`
- 上市：`ldate` (上市日期 YYYY-MM-DD), `rdate` (成立日期 YYYY-MM-DD)
- 股本：`totalstock` (万股), `flowstock` (万股)
- 概念：`idea` (逗号分隔字符串)
- 公司画像：`raddr` (注册地址), `rcapital` (注册资本), `rname` (法人), `bscope` (经营范围)
- 董秘：`bsname`, `bsphone`, `bsemail`

### 2.2 Myquant —— `gm.api.get_symbols`（已存在 API，本次仅加 `symbols=` 单只过滤）

- 鉴权：`MYQUANT_TOKEN` 环境变量
- 通过 `gm` SDK 调用，免 HTTP
- 项目已实现 `get_symbols(sec_type1=1010, df=True)` 用于全市场列表（`get_all_stocks`），本次**复用**该 API 并新增 `symbols=` 单只过滤

**实测可用字段**（基于 2026-06-14 `gm.api.get_symbols(sec_type1=1010, symbols='SHSE.600519', df=True)` 调用结果）：
- 识别：`symbol`, `sec_id`, `sec_name` (UTF-8 双重编码问题由现有 `_decode_gm_name` 处理), `sec_abbr`, `exchange`
- 上市：**`listed_date`** (pandas `Timestamp` 对象，已是 `2001-08-27 00:00:00+08:00`，**不是 epoch ms**), `delisted_date` (同样为 Timestamp)
- 其它：`is_st`, `is_suspended`, `pre_close`, `upper_limit`, `lower_limit`, `adj_factor`, `turn_rate`

**实测不可用字段**（free tier 限制）：
- `total_share` / `float_share` — 无
- `industry` — `stk_get_symbol_industry` 报 `GmError 2001: 用户无此数据接口权限`（**付费接口**）

**`stk_get_instrumentinfos`**：经核实**不存在于已安装的 gm.api 版本**——之前 spec 误用此名，已修正为 `get_symbols`。

**`get_fundamentals` / `get_fundamentals_n`**：需要 table 名 + 日期范围，结构差异大，不在本次范围。

文档：`stock_data/docs/myquant/05-stock-fundamentals-free.md`

### 2.3 上游互补性

| 字段 | Zhitu | Myquant (free tier) |
|---|---|---|
| `code` / `name` | ✅ | ✅ (sec_name, 解码后) |
| `ename` | ✅ | ❌ |
| `listed_date` | ✅ `ldate` (YYYY-MM-DD) | ✅ Timestamp → YYYY-MM-DD |
| `delisted_date` | ❌ | ✅ Timestamp → YYYY-MM-DD |
| `total_shares` | ✅ 万股 | ❌ (free tier 无此字段) |
| `float_shares` | ✅ 万股 | ❌ (free tier 无此字段) |
| `industry` | ❌ (Zhitu 也不提供) | ❌ (付费接口) |
| `concepts` | ✅ `idea` 字符串 | ❌ |
| `registered_address` | ✅ | ❌ |
| `registered_capital` | ✅ | ❌ |
| `legal_representative` | ✅ | ❌ |
| `business_scope` | ✅ | ❌ |
| `established_date` | ✅ `rdate` | ❌ |
| `secretary*` | ✅ | ❌ |

**`industry` 字段的真相**：两个 free-tier 源都不提供，会**始终为空串**。schema 保留此字段作为未来扩展钩子（若 Myquant 升级或加新源），docstring 标注「当前始终为空」。

Failover 取首个返回非空的源；缺字段由 Pydantic 兜默认（空串 / None / `[]`）。

## 3. 总体架构

```
GET /stocks/{code}/info
  └─ routes.py: get_stock_info(code) [cached_endpoint]
       └─ DataFetcherManager.get_stock_info(code) -> (dict, source)
            └─ _with_failover(STOCK_INFO, "csi", ...)
                 ├─ ZhituFetcher.get_stock_info(code)   [P=4]
                 │    └─ GET /hs/gs/gsjj/{code}        → 18 字段（不含 source）
                 └─ MyquantFetcher.get_stock_info(code) [P=9]
                      └─ gm.api.get_symbols(symbols='SHSE.600519', df=True)
                                                     → 18 字段（不含 source，仅 3 字段非空：name/listed_date/delisted_date）
```

## 4. 改动清单

| # | 文件 | 改动 |
|---|---|---|
| 1 | `stock_data/data_provider/base.py` | `DataCapability.STOCK_INFO` 旗标 + `CAPABILITY_TO_METHOD["STOCK_INFO"] = "get_stock_info"` |
| 2 | `stock_data/data_provider/fetchers/zhitu_fetcher.py` | `supported_data_types` 加 `STOCK_INFO`；新增 `get_stock_info(code)` 方法；私有辅助 `_fmt_date / _to_float_wan / _split_concepts` |
| 3 | `stock_data/data_provider/fetchers/myquant_fetcher.py` | `supported_data_types` 加 `STOCK_INFO`；新增 `get_stock_info(code)` 方法（复用已有 `get_symbols` + `_convert_code` + `_decode_gm_name`）；私有辅助 `_ts_to_date` (pandas Timestamp → YYYY-MM-DD) |
| 4 | `stock_data/data_provider/manager.py` | 新增 `get_stock_info(code) -> (dict, str)` 一行 lambda 方法（与 `get_dividend` 同款） |
| 5 | `stock_data/api/schemas.py` | 新增 `StockInfoResponse` Pydantic 模型（18 字段 + `source` = 19 总字段） |
| 6 | `stock_data/api/routes.py` | 新增 `GET /stocks/{code}/info` route + `@endpoint_meta` + `cached_endpoint` 包装 |
| 7 | `stock_data/api/cache.py` | `_TTL_STOCK_INFO` 默认 3600s；`_stock_info_cache` 实例；`get_stock_info_cache()` getter；`make_stock_info_cache_key(code)` 工厂 |
| 8 | `.env.example` | 追加 `CACHE_TTL_STOCK_INFO=3600` |
| 9 | `CLAUDE.md` | 3 处更新（见 §8） |

## 5. 响应 Schema

`StockInfoResponse`（`stock_data/api/schemas.py`）：

```python
class StockInfoResponse(BaseModel):
    """公司画像 (A 股) — 来自 Zhitu (主) / Myquant (备) 的归一化结果"""
    # 基础识别
    code: str                          # 600519
    name: str = ""                     # 贵州茅台
    ename: str = ""                    # Kweichow Moutai Co.,Ltd.  (Zhitu only)
    market: str = ""                   # csi

    # 上市与股本
    listed_date: str = ""              # YYYY-MM-DD
    delisted_date: str = ""            # YYYY-MM-DD or ""
    total_shares: float | None = None  # 万股
    float_shares: float | None = None  # 万股

    # 行业与概念
    industry: str = ""                 # 申万/中证行业. **当前始终为空**: Zhitu 不提供, Myquant 该端点付费 (GmError 2001)
    concepts: list[str] = []           # ["白酒","融资融券",...]  (Zhitu 优势)

    # 公司画像
    registered_address: str = ""       # 完整地址
    registered_capital: str = ""       # "9.82亿" 字符串格式
    legal_representative: str = ""     # 法人代表
    business_scope: str = ""           # 经营范围
    established_date: str = ""         # YYYY-MM-DD (Zhitu rdate)

    # 董秘联系
    secretary: str = ""
    secretary_phone: str = ""
    secretary_email: str = ""

    # 源
    source: str = ""                   # "zhitu" | "myquant"
```

**单位约定**：
- `total_shares` / `float_shares`：**万股**（Zhitu 原生；Myquant free tier 不提供 → `None`）
- `registered_capital`：保留上游字符串（"9.82亿"），不强制转 float
- `listed_date` / `delisted_date` / `established_date`：统一 `YYYY-MM-DD` 格式（Zhitu 原生；Myquant `pandas.Timestamp` → YYYY-MM-DD 转换）

## 6. Fetcher 实现要点

### 6.1 ZhituFetcher.get_stock_info

```python
def get_stock_info(self, stock_code: str) -> dict | None:
    if not self.is_available():
        return None
    url = f"https://api.zhituapi.com/hs/gs/gsjj/{stock_code}"
    params = {"token": self._token}
    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as e:
        logger.warning("zhitu get_stock_info %s failed: %s", stock_code, e)
        return None
    if not isinstance(data, dict) or "code" not in data:
        return None
    return {  # 18 user-data fields (source set by manager, not here)
        "code":              stock_code,
        "name":              data.get("name", "") or "",
        "ename":             data.get("ename", "") or "",
        "market":            "csi",
        "listed_date":       _fmt_date(data.get("ldate")),
        "delisted_date":     "",
        "total_shares":      _to_float_wan(data.get("totalstock")),
        "float_shares":      _to_float_wan(data.get("flowstock")),
        "industry":          "",
        "concepts":          _split_concepts(data.get("idea")),
        "registered_address": data.get("raddr", "") or "",
        "registered_capital": data.get("rcapital", "") or "",
        "legal_representative": data.get("rname", "") or "",
        "business_scope":    data.get("bscope", "") or "",
        "established_date":  _fmt_date(data.get("rdate")),
        "secretary":         data.get("bsname", "") or "",
        "secretary_phone":   data.get("bsphone", "") or "",
        "secretary_email":   data.get("bsemail", "") or "",
    }
```

辅助函数（同文件私有）：
- `_fmt_date(s)` — Zhitu 已是 `YYYY-MM-DD`；非空才返回
- `_to_float_wan(s)` — `safe_float` 转换
- `_split_concepts(s)` — 逗号分隔字符串 → `list[str]`（去空、去重）

### 6.2 MyquantFetcher.get_stock_info

```python
def get_stock_info(self, stock_code: str) -> dict | None:
    if not self.is_available():
        return None
    try:
        self._ensure_initialized()
        # 用项目内现成的 _convert_code 转交易所前缀（SHSE / SZSE）
        symbol_full = self._convert_code(stock_code)
        # 复用项目已有的 get_symbols (与 get_all_stocks 同源)，加 symbols= 单只过滤
        df = gm.api.get_symbols(sec_type1=1010, symbols=symbol_full, df=True)
        if df is None or df.empty:
            return None
        row = df.iloc[0]
        return {  # 18 user-data fields (source set by manager, not here)
            "code":              stock_code,
            "name":              _decode_gm_name(row.get("sec_name", "")),  # 处理 UTF-8 双重编码
            "ename":             "",
            "market":            "csi",
            "listed_date":       _ts_to_date(row.get("listed_date")),      # pandas.Timestamp → YYYY-MM-DD
            "delisted_date":     _ts_to_date(row.get("delisted_date")),
            "total_shares":      None,                                       # free tier 不提供
            "float_shares":      None,                                       # free tier 不提供
            "industry":          "",                                         # 两个源都不提供
            "concepts":          [],
            "registered_address": "",
            "registered_capital": "",
            "legal_representative": "",
            "business_scope":    "",
            "established_date":  "",
            "secretary":         "",
            "secretary_phone":   "",
            "secretary_email":   "",
        }
    except Exception as e:
        logger.warning("myquant get_stock_info %s failed: %s", stock_code, e)
        return None
```

辅助函数：
- `_ts_to_date(ts)` — pandas `Timestamp` → `YYYY-MM-DD` 字符串（`NaT` / `None` → `""`）。Myquant 实测返回的是 `Timestamp('2001-08-27 00:00:00+08:00')`，**不是** epoch ms
- `_decode_gm_name(raw)` — 项目已存在的私有 helper，复用之（处理 `sec_name` 双重 UTF-8 编码 bug）
- `_shares_to_wan(s)` — **本设计不需要**（free tier 不提供 `total_share/float_share`）

> **注**：Myquant `get_symbols` 返回 35 列里没有 `total_share/float_share/industry`，但有 `is_st/is_suspended/pre_close/upper_limit/lower_limit/turn_rate/adj_factor`（这些已被 `get_all_stocks` 消费）。本次**只取** 3 个对 STOCK_INFO 有意义的字段：sec_name (解码) / listed_date / delisted_date。其他字段忽略。

### 6.3 失败行为

与项目一致（参考 `ZhituFetcher.get_zt_pool` / `MyquantFetcher.get_intraday_data`）：
- HTTP 错误 / JSON 解析失败 / SDK 异常 → `try/except` 兜住 → 返回 `None`
- Manager 的 `_with_failover` 看到 `None` 视作"该源没数据"→ 尝试下一源
- 全部失败 → Manager 抛 `DataFetchError` → route 返 503

## 7. Manager + Route

### 7.1 Manager

```python
def get_stock_info(self, code: str) -> tuple[dict, str]:
    """拉取公司画像（A 股）。Failover: Zhitu (P4) → Myquant (P9)."""
    return self._with_failover(
        DataCapability.STOCK_INFO, "csi", f"stock_info {code}",
        lambda f: f.get_stock_info(code),
        return_source=True,
    )
```

放在 `manager.py` 中 `get_dividend` 之后、`get_fund_flow_minute` 之前（按 capability 声明顺序）。

### 7.2 Route

```python
@router.get(
    "/stocks/{code}/info",
    response_model=StockInfoResponse,
    responses={
        503: {"model": ErrorResponse, "description": "All fetchers failed"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["stocks"],
)
@endpoint_meta(
    summary="公司画像",
    markets=["csi"],
    capabilities=["STOCK_INFO"],
)
def get_stock_info(code: str = Path(max_length=20)) -> StockInfoResponse:
    """公司画像（Zhitu → Myquant failover）。A 股限定."""
    manager = get_manager()
    data, source = manager.get_stock_info(code)
    return StockInfoResponse(**data, source=source)

get_stock_info = cached_endpoint(
    _stock_info_cache, make_stock_info_cache_key, "stock_info", "Stock info"
)(get_stock_info)
```

放在 `routes.py` 中 `/stocks/{code}/quote` 之后、邻近画像类端点。

### 7.3 缓存

```python
# stock_data/api/cache.py
_TTL_STOCK_INFO = int(os.getenv("CACHE_TTL_STOCK_INFO", "3600"))  # 1 小时
_stock_info_cache: TTLCache = TTLCache(maxsize=512, ttl=_TTL_STOCK_INFO)

def get_stock_info_cache() -> TTLCache:
    return _stock_info_cache

def make_stock_info_cache_key(code: str) -> str:
    return f"stock_info:{code}"
```

TTL 选 1h 理由：经营/股本等字段按季度变；上市日期/英文名永久不变；用 1h 作为"绝对新鲜度"与"上游限流"折中。

## 8. 错误处理矩阵

| 情况 | 响应 | HTTP |
|---|---|---|
| code 非 csi 市场（HK / US） | filter_by_capability 空 → Manager 抛 `DataFetchError` | 503 |
| A 股 code 但 Zhitu + Myquant 全失败 | 同上 | 503 |
| Zhitu 失败 + Myquant 返 None | 走 `None` 短路 → Manager 抛错 | 503 |
| Zhitu 成功（含 None 字段） | Zhitu dict + Pydantic 兜默认 | 200 |
| Zhitu 失败 + Myquant 成功 | Myquant dict | 200 |
| 上游 HTTP 5xx / timeout | fetcher `try/except` 兜 → 返 `None` | (被 failover 吸收) → 503 |
| 上游返畸形 JSON | 同上 | 503 |
| `code` 非字符串 / 过长 | FastAPI 422 | 422 |

无 4xx 业务错误：用户传 `SH600519` 会被 fetcher `_convert_code` 内部规整为 `600519`。

## 9. 测试

### 9.1 `tests/test_zhitu_fetcher.py`（追加 `TestGetStockInfo` 类）

- `test_capability_declares_stock_info` — 断言 `DataCapability.STOCK_INFO in ZhituFetcher().supported_data_types`
- `test_returns_none_when_unavailable` — token 缺失 → `None`
- `test_normalizes_full_payload` — `mock.patch` `requests.get` 返手搓 JSON，断言 18 user-data 字段映射（中文/英文名、`ldate` → `listed_date`、`idea` → `concepts` list、`totalstock` 万股保留）
- `test_returns_none_on_http_error` — `raise_for_status` 抛错 → `None`
- `test_returns_none_on_malformed_payload` — 返 `{}` → `None`
- `test_empty_optional_fields_default_to_blank` — 最小 payload（只 code/name），其他字段是空串 / `[]` / `None`

### 9.2 `tests/test_myquant_fetcher.py`（追加 `TestGetStockInfo` 类）

- `test_capability_declares_stock_info` — 断言 `STOCK_INFO in MyquantFetcher().supported_data_types`
- `test_returns_none_when_unavailable` — `gm` 不可导入 → `None`
- `test_normalizes_minimal_payload` — `mock.patch("gm.api.get_symbols")` 返手搓 DataFrame（35 列但只填 sec_name/listed_date/delisted_date），断言：
  - `_decode_gm_name` 处理 `sec_name` 编码（注入乱码字符串，断言返回正确中文）
  - `listed_date` 是 pandas `Timestamp('2001-08-27 00:00:00+08:00')` → `listed_date="2001-08-27"`
  - `delisted_date` 同理
  - `total_shares` / `float_shares` 是 `None`（free tier 不提供）
  - `industry` 是 `""`（两个源都不提供）
- `test_returns_none_on_empty_df` — `get_symbols` 返空 df → `None`

### 9.3 `tests/test_routes.py`（追加 `TestStockInfoRoute` 类）

- `test_info_returns_503_for_invalid_stock` — `GET /stocks/INVALID/info` → 503
- `test_info_valid_a_share_returns_200` — `GET /stocks/600519/info` → 200 + JSON 含 `code, name, listed_date, source, concepts (list)`
- `test_info_rejects_hk_market` — `GET /stocks/HK00700/info` → 503
- `test_info_response_shape` — 响应字段集合严格等于 `StockInfoResponse` 的 fields

## 10. 文档更新

- **`CLAUDE.md`**：
  - 「Capability-Based Routing」表格加 `get_stock_info | STOCK_INFO`
  - 「Fetcher capability declarations」表 Zhitu/Myquant 行追加 `STOCK_INFO`
  - Configuration 段加 `CACHE_TTL_STOCK_INFO`（默认 3600）
  - 「Standardized Data Schema」段补 `StockInfoResponse` 字段说明

- **`.env.example`**：追加 `CACHE_TTL_STOCK_INFO=3600`

- **不新增** `docs/zhitu/04-listed-company-details.md` / `docs/myquant/05-stock-fundamentals-free.md` 端点文档——已存在
