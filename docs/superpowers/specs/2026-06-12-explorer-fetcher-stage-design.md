# Explorer Fetcher Drill-down(第二期:Stage 1 列表 + Stage 2 单测)— 设计文档

> 日期: 2026-06-12
> 范围: 在 `index.html` 每个 server endpoint card 下加两阶段 UI:Stage 1 列出能服务该 endpoint 的 fetcher 及其内部方法签名,Stage 2 提供"绕过 manager 失败转移、单独调某个 fetcher 方法"的测试入口。
> 性质: **manifest 字段扩展 + 新增 control endpoint + UI 折叠区**。不动 manager 路由逻辑、不引入新概念层、不引入 JS 测试框架。
> 关联: 第一期 `2026-06-12-explorer-auto-api-manifest-design.md`(此次为其明确写下的第二期)。

---

## 1. 目标与动机

**目标**: 给用户/开发者在 `/explorer/` UI 上**直接看到**每个 server API 的内部实现路由,以及**直接触发**任意 fetcher 的同名方法用于诊断。

**为什么需要**:
- 当前 explorer 只显示"这个 endpoint 响应什么"(对外契约),但**不显示**"manager 会按什么顺序试哪些 fetcher、每个 fetcher 实际暴露的方法签名是什么"
- 诊断时(如 baostock 实时失败但 manager fallback 到 akshare 成功),没法在 UI 上区分到底是哪个 fetcher 出问题
- Manager 的失败转移逻辑对用户是黑盒,只能看日志推断
- 文档(CLAUDE.md / fetcher docstring)跟代码漂移的隐性成本高,UI 反射是最可靠的真相

**非目标**:
- 不展示上游 SDK 调用名(如 `bs.query_history_k_data_plus`)— 那是第三期,需要在每个 fetcher 里加 mapping
- 不重构 manager 路由(`CAPABILITY_TO_METHOD` 是一张**反射用的常量表**,manager 现有逻辑不读它)
- 不展示未加载的 fetcher(如 `TUSHARE_TOKEN` 未设导致 tushare 未注册)
- 不做并排对比(同一 endpoint 同时跑 N 个 fetcher 比较结果)— YAGNI
- 不做历史调用记录 — 每次覆盖 result panel
- 不动 sidebar 索引(仍按 endpoint,不引入"按 fetcher 索引")
- 不引入 JS 测试框架 — 前端只做手动 smoke checklist
- 不动现有 manager.py 一行代码

---

## 2. 当前状态

```
stock_data/
├── api/
│   ├── routes.py             ~30 个 @router.get(...) 端点,每个带 @endpoint_meta
│   └── endpoint_meta.py      EndpointMeta(summary, markets, capabilities)
├── explorer/
│   ├── __init__.py           mount(app) + _validate_manifest_invariants
│   ├── manifest.py           build_manifest(app) → JSON tree
│   ├── routes.py             /control/* (config, server/status, api-manifest)
│   ├── tags.py
│   └── static/
│       └── index.html        980 行,fetch /control/api-manifest 后渲染
└── data_provider/
    ├── base.py               BaseFetcher + DataCapability(Flag,~20 个 flag)
    └── manager.py            DataFetcherManager._filter_by_capability(market, capability)
```

**当前 manifest endpoint 节点**(`explorer/manifest.py:69-94`):
```json
{
  "id": "get_stocks_code_history",
  "method": "GET",
  "path": "/stocks/{code}/history",
  "summary": "...",
  "markets": ["csi"],
  "capabilities": ["HISTORICAL_DWM", "HISTORICAL_MIN"],
  "params": [{"name": "code", "in": "path", "required": true, "type": "string"}, ...],
  "response_model": "KLineDataList"
}
```

**关键现有约束**(必须遵守):
- `@endpoint_meta` 必须是 `@router.get` 的**内层装饰器**且必须返回原 func(`endpoint_meta.py:53-59` 的契约)
- Manager 内部数据访问必须经 `_filter_by_capability(market, capability)`(`CLAUDE.md > Anti-Patterns`)
- "Source of truth is server-side, not the HTML" — 前端不硬编码 fetcher 列表

**关键现实复杂度**(self-review 发现,影响 capability→method 映射):

几个 capability 被**多个 endpoint 共用,且调不同的 fetcher 方法**。手工核对 `routes.py` + `manager.py`:

| Capability | 出现在 routes 的次数 | 实际调用的 fetcher 方法 |
|------------|----------------------|--------------------------|
| `STOCK_BOARD` | 2 | `get_all_concept_boards` / `get_all_industry_boards` / `get_concept_board_stocks` / `get_industry_board_stocks` |
| `DRAGON_TIGER` | 2 | `get_dragon_tiger` / `get_daily_dragon_tiger` |
| `FUND_FLOW` | 2 | `get_fund_flow_minute` / `get_fund_flow_120d` |
| `STOCK_ZT_POOL` | 1 | `get_zt_pool`(+ `get_zt_pool_raw` 内部用,不暴露) |
| `RESEARCH_REPORT` | 1 | `get_reports`(+ `get_report_pdf` 内部用) |
| 其他(`HISTORICAL_DWM`, `REALTIME_QUOTE`, `TRADE_CALENDAR`, ...) | n | 1:1 唯一方法 |

→ `CAPABILITY_TO_METHOD: dict[cap, str]` **一对一不够用**。必须让 endpoint 能在 `@endpoint_meta` 里显式声明 `fetcher_method` 来 override。详见第 3 节"3.5 capability 多方法消歧"。

---

## 3. 目标架构

```
                                ┌──────────────────────────────────────┐
                                │ index.html                            │
                                │ Stage 1: Fetcher backends 折叠区      │
                                │ Stage 2: 点 [Test] 展开 mini-form     │
                                │           → POST /control/fetcher-test│
                                └──────────────┬───────────────────────┘
                                               │
                            GET  /control/api-manifest  (扩展)
                            POST /control/fetcher-test  (新增)
                                               │
       ┌───────────────────────────────────────┴───────────────────────────────────┐
       │ explorer/                                                                  │
       │   manifest.py     build_manifest()  → 每个 endpoint 节点新增 `fetchers[]` │
       │                   _resolve_fetchers(meta, manager) -> list[FetcherEntry] │
       │                   _reflect_signature(method)   -> list[ParamEntry]        │
       │                                                                            │
       │   routes.py       POST /control/fetcher-test                              │
       │                   body: {fetcher, method, kwargs}                         │
       │                   → manager.get_fetcher(name).<method>(**kwargs)          │
       │                   → 永远 HTTP 200,用 ok/error 字段表达成功失败           │
       │                                                                            │
       │   __init__.py     _validate_manifest_invariants 扩展:                     │
       │                   - 每个 DataCapability 必须在 CAPABILITY_TO_METHOD       │
       │                     或 _NO_FETCHER_METHOD 集合里                          │
       │                   - 表里的 method 名必须在 BaseFetcher 上找得到 attr     │
       └───────────────────────────────────────┬───────────────────────────────────┘
                                               │ uses
                                               ▼
       ┌───────────────────────────────────────────────────────────────────────────┐
       │ data_provider/                                                             │
       │   base.py        新增:                                                     │
       │                   CAPABILITY_TO_METHOD: dict[DataCapability, str]         │
       │                     # HISTORICAL_DWM → "get_kline_data" 等                │
       │                   _NO_FETCHER_METHOD: frozenset[DataCapability]           │
       │                     # 显式声明"这个 capability 不映射 method"            │
       │                     # (例如未来纯计算 capability,目前为空)              │
       │   manager.py     0 改动                                                    │
       └───────────────────────────────────────────────────────────────────────────┘
       ┌───────────────────────────────────────────────────────────────────────────┐
       │ server.py        +2 行:app.state.manager = manager 实例                    │
       │                   (manifest builder 需要 manager 反射 fetcher 列表)      │
       └───────────────────────────────────────────────────────────────────────────┘
```

**关键决策**:

1. `CAPABILITY_TO_METHOD` 放 `base.py`(跟 `DataCapability` 枚举挨着),**不放 manager.py**
   - 理由:manager 现有路由逻辑不消费这张表(每个 `get_*` 方法已显式写死调用哪个 method);放 manager 里会暗示"manager 是查表路由"误导后人

2. `_NO_FETCHER_METHOD` 显式集合(目前为空)
   - 理由:防止"新增 capability 时忘了声明意图"成为静默漂移源。强制开发者要么加进 map、要么加进 NO_FETCHER 集合,二选一

3. Manager 实例通过 `app.state.manager` 传给 manifest builder
   - 理由:manifest 需要调 manager 的 `_filter_by_capability`,但不应该 import 全局 manager 单例(会让 manifest 模块对全局状态有依赖,测试难注入 mock)

4. Stage 2 endpoint **永远返回 HTTP 200**
   - 理由:Stage 2 目的是观察 fetcher 行为(包括失败行为);HTTP 错误码会被浏览器 fetch 当成"调用本身坏了"干扰判断;并触发 dev-tools 红框跟"我故意在测会失败的 fetcher"语义冲突

5. **不缓存** manifest(沿用现有约定)
   - 每次反射,~10 fetcher × ~5 method ≈ 50 次 `inspect.signature` 调用,亚毫秒

### 3.5 capability 多方法消歧

如第 2 节末尾分析,`STOCK_BOARD` / `DRAGON_TIGER` / `FUND_FLOW` 在 routes 里对应多个不同的 fetcher 方法。解决方案:

**`CAPABILITY_TO_METHOD` 保持 `dict[DataCapability, str]` 形态**(一对一),值是该 capability 的"**默认方法**"(选最常用的一个,作为兜底)。

**`EndpointMeta` 加可选字段 `fetcher_method: str | None = None`**,默认 None。

`@endpoint_meta` 签名扩展:
```python
def endpoint_meta(
    *,
    summary: str,
    markets: list[str] | None = None,
    capabilities: list[str] | None = None,
    fetcher_method: str | None = None,   # ← 新增,多方法消歧
) -> Callable: ...
```

**`_resolve_fetchers` 解析方法名优先级**:
1. 若 `meta.fetcher_method` 非 None → 直接用它
2. 否则查 `CAPABILITY_TO_METHOD[cap]`(每个 cap 必须在 map 里有唯一默认值,sanity check 保证)

**`CAPABILITY_TO_METHOD` 中多方法 capability 的默认值选择**(基于"最常被独立 endpoint 使用"的原则):

| Capability | 默认 method | 显式 override 的 endpoint(基于 routes.py 真实路径) |
|------------|-------------|--------------------------------------------------|
| `STOCK_BOARD` | `get_all_concept_boards` | `/boards/{board_code}/stocks` → `get_concept_board_stocks`<br>**注**:`/boards`(单 endpoint,`?type=concept\|industry` 分发)Stage 2 测的是默认 `get_all_concept_boards`;测 industry 变体不在本期范围(用户可通过普通 Try-it form 跑 `?type=industry`) |
| `DRAGON_TIGER` | `get_dragon_tiger` | `/dragon-tiger/daily` → `get_daily_dragon_tiger` |
| `FUND_FLOW` | `get_fund_flow_minute` | `/stocks/{stock_code}/fund-flow/daily` → `get_fund_flow_120d` |

→ 本次实现要 **同步修改 `routes.py` 上述 3 个 endpoint 的 `@endpoint_meta`**,加 `fetcher_method=...`。这是 spec 范围内的改动(+6 行,~2 行/endpoint × 3 endpoint)。

**关于 `/boards/{board_code}/stocks` 也只 override 概念变体**:同上,Stage 2 只测概念板块成分股(`get_concept_board_stocks`);测行业变体留给用户在 mini-form 里改 method 名(不在本期 UI 支持范围)。这是基于实际诊断需求:用户用 Stage 2 是想看"eastmoney 的板块查询行为是否正常",任一变体足够诊断。

**Stage 2 白名单同步扩展**:不再用 `set(CAPABILITY_TO_METHOD.values())`(会漏掉 override 的方法),改成 **遍历所有 endpoint 节点的 `fetchers[*].method`**(所有可达 method 的并集)。

**为什么这种结构而不是把 `CAPABILITY_TO_METHOD` 改成 `dict[cap, list[str]]`**:
- 后者把消歧推给消费侧(`_resolve_fetchers` 要再做一次选择),逻辑分散
- 前者把消歧集中到 `@endpoint_meta` 一处,跟 endpoint 物理挨在一起,改 endpoint 时同步成本最低
- 顺便:`@endpoint_meta(fetcher_method=...)` 为未来"上游 SDK 调用展示"(第三期)留口子 — 加 `upstream_call=...` 字段就行

---

## 4. Manifest 数据形状

`fetchers` 字段追加到 endpoint 节点,**其他字段保持不变**(向后兼容)。

### 完整示例(以 `/stocks/{code}/history` 为例)

```json
{
  "id": "get_stocks_code_history",
  "method": "GET",
  "path": "/stocks/{code}/history",
  "summary": "...",
  "markets": ["csi"],
  "capabilities": ["HISTORICAL_DWM", "HISTORICAL_MIN"],
  "params": [...],
  "response_model": "KLineDataList",

  "fetchers": [
    {
      "name": "tushare",
      "method": "get_kline_data",
      "priority": 0,
      "capabilities": ["HISTORICAL_DWM"],
      "signature": [
        {"name": "code",       "type": "string", "required": true,  "default": null},
        {"name": "period",     "type": "string", "required": false, "default": "d"},
        {"name": "adjust",     "type": "string", "required": false, "default": ""},
        {"name": "start_date", "type": "string", "required": false, "default": null},
        {"name": "end_date",   "type": "string", "required": false, "default": null}
      ]
    },
    {
      "name": "baostock",
      "method": "get_kline_data",
      "priority": 1,
      "capabilities": ["HISTORICAL_DWM", "HISTORICAL_MIN"],
      "signature": [...]
    },
    {
      "name": "akshare",
      "method": "get_kline_data",
      "priority": 2,
      "capabilities": ["HISTORICAL_DWM", "HISTORICAL_MIN"],
      "signature": [...]
    }
  ]
}
```

### `_resolve_fetchers` 解析规则

1. 取 endpoint 的 `(markets, capabilities)` 笛卡儿积
2. 对每对 `(market, capability)` 调 `manager._filter_by_capability(market, capability)` 拿候选 fetcher
3. **确定方法名**(参 3.5 节):
   - 若 `endpoint_meta.fetcher_method` 非 None → 用它
   - 否则用 `CAPABILITY_TO_METHOD[cap]` 默认值
4. **按 `(fetcher.name, method_name)` 元组去重**(方式 A:同一 fetcher 跨多 capability 合并成一条)
5. 同一 fetcher 跨多 capability 时把 capability 列表合并进 `capabilities` 字段
6. 按 `priority` 升序排列(展示顺序 = 实际失败转移顺序)

### 边界情况

| 情况 | 处理 |
|------|------|
| Endpoint 不声明任何 capability(`/indicators/catalog` 等) | `fetchers: []`,UI 不渲染折叠按钮 |
| Endpoint 声明的 capability 不在 `CAPABILITY_TO_METHOD` 也不在 `_NO_FETCHER_METHOD` | 启动期 sanity check 抛 warning,manifest 端跳过该 capability |
| 某 capability 当前没已加载 fetcher(如 myquant 缺 token) | 只显示已加载的 fetcher(沿用 `_filter_by_capability` 行为) |
| 同 fetcher 多 capability 都映射到同一 method | 合并成一条,capabilities 列表合并 |
| 同 fetcher 多 capability 映射到不同 method | 按 (fetcher, method) 元组去重,fetcher 出现多次(每条 method 一行)|

### Signature 反射规则

- `inspect.signature(getattr(fetcher_instance, method_name))`
- 跳过 `self` 参数
- `type` 字段复用现有 `_python_type_to_str`(处理 `Optional[X]` / `str | None`)
- `default == Parameter.empty` → `required: true, default: null`
- 否则 JSON-serialize 默认值;不可序列化 → `repr()` 字符串

---

## 5. Stage 2 endpoint 契约

新增 `POST /control/fetcher-test`,挂在已有 control router 下(自动继承 127.0.0.1-only)。

### Request

```http
POST /control/fetcher-test
Content-Type: application/json

{
  "fetcher": "baostock",
  "method":  "get_kline_data",
  "kwargs":  {
    "code": "600519",
    "period": "d",
    "start_date": "2024-01-01",
    "end_date": "2024-01-31"
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `fetcher` | string | fetcher 的 `name` 属性(`baostock` / `akshare` / `tushare` / ...) |
| `method` | string | `BaseFetcher` 子类上的 public method 名,**白名单校验** |
| `kwargs` | object | 字典,直接 `**unpack` 进 `fetcher.method` 调用 |

**白名单来源**:遍历 `/control/api-manifest` 所有 endpoint 节点的 `fetchers[*].method`,取并集。包含所有可达的 fetcher 方法(默认 + override 后的方法)。新增 capability 或 override 时自动扩展白名单,manifest builder 启动时计算一次缓存到 `app.state.fetcher_method_whitelist`。

### Response — 永远 HTTP 200

成功:
```json
{
  "ok": true,
  "fetcher": "baostock",
  "method": "get_kline_data",
  "elapsed_ms": 234,
  "result": [
    {"date": "2024-01-02", "open": 1700.0, "close": 1715.0, ...},
    ...
  ],
  "error": null
}
```

失败:
```json
{
  "ok": false,
  "fetcher": "baostock",
  "method": "get_kline_data",
  "elapsed_ms": 12,
  "result": null,
  "error": {
    "type": "DataFetchError",
    "message": "BaoStock login failed: token expired",
    "traceback": "Traceback (most recent call last):\n  File ..."
  }
}
```

### 错误分类(全部 `ok: false`,HTTP 200)

| 触发条件 | `error.type` | `error.message` |
|----------|--------------|-----------------|
| 未知 fetcher 名 | `UnknownFetcher` | `no fetcher named '<name>'; loaded: [baostock, akshare, ...]` |
| 方法名不在白名单 | `UnknownMethod` | `method '<m>' not allowed; allowed: [get_kline_data, ...]` |
| `fetcher.is_available()` 返回 False | `FetcherUnavailable` | `baostock.is_available() returned False (check token / SDK install)` |
| kwargs 缺必填参数 | `TypeError` | Python 原生消息 |
| fetcher 内部抛异常 | exception class name | `str(exc)` + traceback |

**唯一返回 422 的情况**:request body 缺 `fetcher` 或 `method` 字段(Pydantic validation,FastAPI 默认行为)。

### 其他

- **超时**:暂不加(fetcher 内部有 tenacity 重试 + 自己的 timeout)
- **并发**:无锁,fetcher 自身保证线程安全(沿用现有 manager GET 假设)
- **traceback 默认开**:127.0.0.1-only 不外泄,调试用

---

## 6. HTML 改动(Stage 1 + Stage 2 UI)

复用现有 endpoint card 风格,不引入新组件库、不动 layout grid。

### Stage 1 — Fetcher backends 折叠区

每个 endpoint card 末尾追加,**默认折叠**,用 `<details><summary>` 原生 HTML(0 JS state):

```
GET /stocks/{code}/history
csi · HISTORICAL_DWM · HISTORICAL_MIN
取股票 K 线数据,支持日/周/月/分钟。

Params:
  code        (path,  string, required)
  period      (query, string, default "d")
  ...

[Try it]

▶ Fetcher backends (3)
```

展开后:
```
▼ Fetcher backends (3)
┌────────────────────────────────────────────────────────┐
│ [P0] tushare    .get_kline_data(code, period, adjust,  │
│                                  start_date, end_date) │
│                  HISTORICAL_DWM                  [Test]│
├────────────────────────────────────────────────────────┤
│ [P1] baostock   .get_kline_data(code, period, adjust,  │
│                                  start_date, end_date) │
│                  HISTORICAL_DWM · HISTORICAL_MIN [Test]│
├────────────────────────────────────────────────────────┤
│ [P2] akshare    .get_kline_data(code, period, adjust,  │
│                                  start_date, end_date) │
│                  HISTORICAL_DWM · HISTORICAL_MIN [Test]│
└────────────────────────────────────────────────────────┘
```

视觉细节:
- `[P0]` priority badge 单色背景(`#888` 灰),区别于 capability chip 的蓝/绿
- 中间行 method 名 + 参数名列表(无类型 — 太挤;hover 显示完整 signature tooltip)
- 右下角 capability chips(复用现有 chip 样式)
- 最右一个 `[Test]` 按钮 → Stage 2 入口
- `fetchers: []` 时整个折叠按钮不渲染

### Stage 2 — Test 按钮展开 mini-form

点 `[Test]` → fetcher 行下方就地展开 inline form(复用现有 Try-it form 样式):

```
[P1] baostock   .get_kline_data(...)              ▶ [Test]
┌─ Direct call: baostock.get_kline_data ─────────────────┐
│ code:       [600519       ]  ← 预填 Try-it 同名键        │
│ period:     [d            ]                              │
│ adjust:     [             ]                              │
│ start_date: [2024-01-01   ]                              │
│ end_date:   [2024-01-31   ]                              │
│                                          [Run] [Cancel]  │
└──────────────────────────────────────────────────────────┘
```

**预填规则**:
- mini-form 字段从 manifest 的 `signature[]` 渲染(权威源是 fetcher 方法签名,不是 endpoint params)
- endpoint 的 Try-it form 已填同名字段 → 自动预填进 mini-form
- 名字不匹配的字段(如 endpoint 用 `days=30`、fetcher 用 `start_date/end_date`)留空,用户手填
- 默认值从签名 `default` 字段填(`null` / `""` → 空字符串、其他 → 字面值)

**Run 流程**:
1. 收集 mini-form 值 → POST `/control/fetcher-test`
2. 结果显示到**现有右侧 result panel**(复用,不开新面板)
3. result panel header 标识 `Direct fetcher · baostock.get_kline_data · 234ms`,区别于正常 Try-it 的 `Endpoint · GET /... · 567ms`

**Cancel**:折叠 mini-form,不调用。

### 错误展示

| 状况 | 显示位置 |
|------|---------|
| `ok: false` + 任何 error.type | result panel body 红字 `error.type: error.message`,下面折叠 `traceback`(默认展开) |
| HTTP 错误(422 等) | result panel 顶部红 banner(同款 manifest-fetch-failure 样式) |
| 网络断连 / fetch reject | 同上 |

### 视觉/技术决策

- 折叠用 `<details><summary>` 原生 HTML → 0 JS state 管理
- mini-form 跟现有 Try-it form 复用同一 `.tryit-form` class,只是包裹在 fetcher row 内,padding 略缩
- mini-form 显隐用 CSS `[hidden]` attr,1 行 JS

---

## 7. 测试策略

4 层覆盖,新增 1 个测试文件、扩展 1 个。

### 7.1 常量表完整性(新文件)

`tests/test_capability_method_map.py` (~50 行):
- 参数化覆盖每个 `DataCapability` flag → 必须在 `CAPABILITY_TO_METHOD` **或** `_NO_FETCHER_METHOD` 集合里(强制声明意图,防漂移)
- `CAPABILITY_TO_METHOD` 里每个 method 名 → 必须在 `BaseFetcher` 子类上 `hasattr`(防 typo)
- 验证 3 个 override endpoint 的 `meta.fetcher_method` 也是 `BaseFetcher` 上存在的 attr(`/boards/{board_code}/stocks`, `/dragon-tiger/daily`, `/stocks/{stock_code}/fund-flow/daily`)

### 7.2 Manifest 字段(扩展现有)

`tests/test_explorer_manifest_endpoint.py` (+40 行):
- GET `/control/api-manifest` 每个 endpoint 节点有 `fetchers` 字段(类型 list)
- 选 `/stocks/{code}/history` 断言 `fetchers` 含 `tushare/baostock/akshare`,按 priority 升序
- baostock 的 `capabilities` 字段 == `["HISTORICAL_DWM", "HISTORICAL_MIN"]`(验证方式 A 合并)
- `/indicators/catalog` 的 `fetchers` == `[]`
- 任一 fetcher 的 `signature` 字段含 `code, required: true, type: "string"`
- **`fetcher_method` override 验证**:`/boards/{board_code}/stocks` 的 fetchers[*].method 都 == `"get_concept_board_stocks"`(不是默认的 `get_all_concept_boards`);`/dragon-tiger/daily` → `"get_daily_dragon_tiger"`;`/stocks/{stock_code}/fund-flow/daily` → `"get_fund_flow_120d"`

### 7.3 Stage 2 endpoint(新文件)

`tests/test_fetcher_test_endpoint.py` (~80 行):
- 用 `unittest.mock.patch` mock `manager.get_fetcher` 返回 Mock
- 覆盖:happy path、UnknownFetcher、UnknownMethod、FetcherUnavailable、TypeError(缺 kwarg)、DataFetchError
- **断言 HTTP 永远 200**(在 ok=false 分支也断言 `status_code == 200`)
- `elapsed_ms` 字段存在且 ≥ 0
- 失败时 `traceback` 字段非空

### 7.4 启动 sanity check(扩展现有)

`explorer/__init__.py` 的 `_validate_manifest_invariants` 扩展 (+20 行):
- 打 warning:`CAPABILITY_TO_METHOD` 里但 `BaseFetcher` 上无该 attr
- 打 warning:`DataCapability` 新成员既不在 map 也不在 `_NO_FETCHER_METHOD`
- 打 warning:`@endpoint_meta(fetcher_method=...)` 声明的 method 名在 `BaseFetcher` 上不存在
- 缓存白名单:计算 `app.state.fetcher_method_whitelist = {fetcher_method | for endpoint in manifest}`

### 7.5 前端手动 smoke checklist

不引入 JS 测试框架(YAGNI;现有 codebase 0 JS 测试)。最终发版前手动跑:
1. 启 server,开 `/explorer/`,sidebar 加载正常
2. 随便点 3 个不同 endpoint 展开 Fetcher backends 折叠区,看到 fetcher 列表
3. 点 `/indicators/catalog` 验证**没有** Fetcher backends 按钮
4. 对一个 endpoint(如 `/stocks/{code}/quote`)点 Test → mini-form 出现 → Run → result panel 显示数据
5. 故意填错 kwarg(如 code 留空)→ Run → result panel 看到红字 error.type + traceback

---

## 8. 代码量估计

| 文件 | 状态 | 行数 | 用途 |
|------|------|------|------|
| `data_provider/base.py` | 修改 | +25 | `CAPABILITY_TO_METHOD` + `_NO_FETCHER_METHOD` |
| `api/endpoint_meta.py` | 修改 | +5 | `EndpointMeta.fetcher_method` 字段 + 装饰器参数 |
| `api/routes.py` | 修改 | +6 | 3 个 endpoint 加 `fetcher_method=...` override |
| `explorer/manifest.py` | 修改 | +50 | `_resolve_fetchers` + `_reflect_signature` + 字段挂载 + override 优先级 |
| `explorer/routes.py` | 修改 | +50 | POST `/control/fetcher-test` + Pydantic 模型 + 错误分类 |
| `explorer/__init__.py` | 修改 | +20 | sanity check 扩展(map / override / 白名单缓存) |
| `server.py` | 修改 | +2 | `app.state.manager = manager` |
| `tests/test_capability_method_map.py` | 新文件 | +50 | 常量表 + override 完整性 |
| `tests/test_explorer_manifest_endpoint.py` | 修改 | +40 | manifest 新字段 + override 断言 |
| `tests/test_fetcher_test_endpoint.py` | 新文件 | +80 | endpoint 行为覆盖 |
| `stock_data/explorer/static/index.html` | 修改 | +110(style +40, JS +70) | Stage 1 折叠 + Stage 2 mini-form |
| `CLAUDE.md` | 修改 | +30 | 新增段落 + manifest schema + `fetcher_method` override 用法 |
| **合计** | | **~468 行** | |

---

## 9. Definition of Done

- ✅ 新增/修改的 pytest 全部通过(`.venv/Scripts/python.exe -m pytest`)
- ✅ 启动 server 不产生**新的** `_validate_*_invariants` warning
- ✅ 浏览器手动 smoke checklist(7.5 节)全部通过
- ✅ `ruff check .` 通过
- ✅ `CLAUDE.md` 同步,反映新 manifest 字段 + Stage 2 endpoint 用法

---

## 10. 风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| `app.state.manager` wiring 漏掉 → manifest builder 拿不到 manager 实例,fetchers 字段全部空 | 高 | 测试覆盖:断言 `/stocks/{code}/history` 的 fetchers 字段非空 |
| 多方法 capability 的 endpoint 忘加 `fetcher_method=` → UI 显示默认方法,Stage 2 测的是另一个 endpoint 的逻辑 | **高** | 启动 sanity check 检查 3 个已知 override endpoint;CI 加 manifest 断言;CLAUDE.md 加显式表 |
| 新加 capability 时忘了加进 `CAPABILITY_TO_METHOD` | 中 | 启动 sanity check 抛 warning;CI pytest 参数化覆盖 |
| 新加多方法 capability(未来),只在 map 里放默认方法,忘记给共用该 cap 的其他 endpoint 加 override | 中 | sanity check 不能完全发现(map 看起来合法),但 manifest 测试覆盖具体 endpoint 时会暴露差异;依赖 PR review |
| Stage 2 测试调到耗时操作(如 EastMoney 龙虎榜全量拉)→ 请求 hang | 低 | 默认不加超时(localhost 调试可接受);如发生加 30s timeout |
| mini-form 字段预填出错(类型不匹配如 int vs string) | 低 | 预填只做字符串复制,用户可改;mini-form 提交时全部当 string POST(后端转换) |
| `<details>` 在某些旧 Chromium 上样式不一致 | 低 | 加 `[open]` 选择器手动设样式覆盖 |
| 现有 endpoint 的 `@endpoint_meta` 未声明完整 capabilities(如声明了 HISTORICAL_DWM 但忘了 HISTORICAL_MIN)→ fetcher 列表缺失 | 中 | 不在本次范围(那是 endpoint_meta 自身正确性问题),但 spec 第 4 节边界情况已记录排查路径 |

---

## 11. 后续工作(本期 NOT included)

- 上游 SDK 调用名展示(第三期,需要每个 fetcher 加 `method → upstream_call` mapping)
- 并排对比(同 endpoint 同时跑 N fetcher 比较结果)
- 历史调用记录 + 持久化
- 按 fetcher 索引的 sidebar 视图
- JS 自动化测试(jest / playwright)
- `/control/fetcher-test` 加超时和并发限制(目前 localhost 调试场景不需要)
