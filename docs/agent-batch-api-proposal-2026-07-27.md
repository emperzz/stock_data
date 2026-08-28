# Agent 端点提案（市场复盘 / 选股工作流优化）

**状态**：设计提案（未实现）  ·  **作者**：Claude Code  ·  **日期**：2026-07-27
**目标读者**：项目维护者、skill 作者

---

## 1. 背景

`market-recap` / `stock-picking` 两个 skill 的工作流包含 **20~40 个 HTTP 调用 + 多轮 LLM 判断 + 多个本地文件读写**。其中相当一部分调用是**串行的、不分支的纯数据组装**（如"拿到候选股票列表 → 对每只拉 kline + info + boards"），agent 在中间做的"拼接"、"join"、"集合运算"完全可以由服务端承担。

三类具体痛点：

| 痛点 | 现状 | 提案效果 |
|---|---|---|
| 串行调用浪费 round-trip | 候选 10 只 × 3 能力 = 30 次 HTTP | 降到 1 次 |
| LLM 自己做 join 易错 | agent 拿到 zt-pool 后自行交叉匹配股票代码 | 服务端 join 后返回 |
| 异构能力聚合 | 消息 + 涨跌停 + 龙虎榜各开 1 个 HTTP | 服务端 fan-out 1 次拿全 |

注意：**LLM 判断（龙头识别、归因、量价阈值判定）继续由 skill 做**。本提案只动数据获取与聚合层。

---

## 2. 设计原则（与现有约定对齐）

- **路径**：沿用 `/api/v1/{resource}/...` 既有前缀。
- **领域归属**：单资源 CRUD 仍归属 `stocks.py` / `boards.py`；所有 agent 端点统一归属新建 `agent.py`。
- **Schema**：新增 Pydantic 模型全部进 `api/schemas.py`。
- **缓存**：复用既有 `TTLCache`（`api/cache.py`）；agent 端点以 body hash / 路径参数标准化为 key。
- **错误隔离**：聚合端点内单 item 失败不影响其他；响应里同时返回 `ok: bool` + `errors[]`。
- **向后兼容**：既有端点的扩展默认关闭，不传新参数行为不变。
- **判断不下放**：服务端只做"取数 + 聚合 + 投影"，不评估"是否强势 / 是否龙头 / 能否买入"。

### 2.1 API 命名约定（agent 端点 vs 通用端点）

| 类型 | 路径模式 | 例子 |
|---|---|---|
| **通用端点**（既有 / 单能力） | `/api/v1/{resource}/{code}/{kind}` 或 `/api/v1/{resource}` | `/stocks/600519/kline`、`/boards`、`/zt-pools` |
| **既有端点扩展**（query 参数新增） | 同上，**仅追加可选参数** | `/boards/{code}/stocks?with_zt_flags=true` |
| **Agent 端点**（新增聚合 / 批量） | **`/api/v1/agent/{domain}/{action}`** | `/agent/boards/overlap`、`/agent/stocks/batch/profile` |

**判定标准**：若改动**只是新增 query 参数**（响应 shape 仅追加可选字段）→ 走"既有端点扩展"；若改动是**新路由 / 新响应 shape / 新错误结构** → 走 `/api/v1/agent/` 命名空间。

**Agent 端点的设计特征**：
- 通常是 POST（body 携带 codes / aspects / filters 列表）
- 响应包含 `summary` 块（`requested / ok / failed / elapsed_ms`）
- per-item 错误隔离（`results[].ok` + `results[].errors[]`）
- 缓存 key 用 body hash 而非 path 参数
- 在 `/explorer/` 侧栏用 `tags=["agent"]` 独立分组

**文件归属**：所有 `/api/v1/agent/*` 路由集中在 `stock_data/api/routes/agent.py` 一个文件。

### 2.2 统一投影格式：MD（Markdown）

所有 `/api/v1/agent/*` 端点统一支持 `?format=json|md`：

- **默认 `json`**（向后兼容）
- **`?format=md` 显式开启** —— 服务端把 JSON 响应渲染成 markdown 文本返回，`Content-Type: text/markdown; charset=utf-8`

**为什么选 MD 而不是 TSV**：
- **TSV 是 MD 的子集**（无标题 / 无段落 / 无结构标记）；MD 包含 TSV 的全部能力
- MD 天然处理异构内容（表格 + 段落 + 标题 + 列表）——agent 端点的响应都是异构（K-line 表格 + 涨跌停池 + 早报段落 + 龙虎榜 summary + 候选股票）
- LLM 训练数据中 markdown 占比远高于 TSV，**解析可靠性更高**
- 单一格式覆盖 6 个端点所有响应形态，不需要为不同端点选不同格式

**实现位置**：`_render_markdown(payload, template_fn) -> PlainTextResponse` 通用 helper + 每个端点一个 `render_as_markdown(payload) -> str` 模板函数，集中在 `agent.py`。

**token 节省**：对比 JSON baseline，MD 在异构端点约 45-55%，在纯表格端点约 60-65%。

**不回退 TSV**：TSV 能做的 MD 都能做，且 MD 还支持段落 / 标题 / 嵌套列表。单独维护 TSV 是无收益的复杂度。

---

## 3. 端点详细设计

本提案共 **7 个变更点**：1 个既有端点扩展 + 6 个 agent 端点。

### 3.1 既有端点扩展（保留 1 个）

#### 3.1.1 `?with_zt_flags=true` — 板块成分股 + 涨停 join

**端点**：扩展 `GET /api/v1/boards/{code}/stocks`

**参数**：`with_zt_flags: bool = False`

**响应变化**：当 `with_zt_flags=true` 时，每条 `BoardStockInfo` 增加 2 个可选字段：
```python
is_limit_up: bool | None = None       # 是否当日涨停
lb_count: int | None = None           # 连板数（涨停时才有）
```

**实现位置**：`stock_data/api/routes/boards.py`，在 fetch `board.stocks` 后调用 `manager.get_zt_pool(pool_type="zt")` 一次构建 `code → ZTPoolStock` 映射（返回值是 `list[ZTPoolStock]` 而非 dict，需在内存中自行构建 `{stock.code: stock}`），O(成分股数) 完成 join；zt-pool 命中 `get_pools_cache()`（注意是 `pools` 不是 `pool`，在 `api/cache.py`）不增加额外网络开销。

**`is_limit_up` 语义**：定义为"该 code 出现在 zt-pool 中"，**不**自行计算涨跌幅（避免与上游涨停判定逻辑漂移）。

**节省**：stock-picking §4 步骤 6 当前 = 1 次 board/stocks + 1 次 zt-pools；改为 = 1 次。

### 3.2 agent 端点（7 个）

> **所有 6 个 agent 端点统一支持 `?format=json|md`**（详见 §2.2）。默认 JSON，`?format=md` 触发 markdown 文本输出（`Content-Type: text/markdown; charset=utf-8`）。MD 模板函数与端点同文件，详见 §4。

#### 3.2.1 `GET /api/v1/agent/indices/market-snapshot` — 指数追踪

**触发场景**：market-recap §4 步骤 3 "指数全景"。

**端点**：`GET /api/v1/agent/indices/market-snapshot`

**参数**：
- `codes` 可选（逗号分隔）；不传默认 = 4 个核心 CSI 指数（上证 + 深证 + 创业板 + 北证 50）

**响应**：
```json
{
  "indices": [
    {
      "code": "000001",
      "name": "上证综指",
      "quote": {"current_price": ..., "change_percent": ..., ...},
      "klines": {
        "5m": [...],   // 最近 2 个交易日
        "d": [...],    // 最近 30 个交易日
        "w": [...]     // 最近 48 周
      },
      "errors": {}
    }
  ],
  "summary": {"requested": 4, "ok": 4, "failed": 0, "elapsed_ms": "~1234 (示例)"}
}
```

**实现要点**：
- 内部对每个 index 调 4 个 manager 方法：`manager.get_index_realtime_quote(code)` + 3 个 `manager.get_kline_data(code, frequency="5m"|"d"|"w", days=…, asset="index")`（**asset="index" 触发 INDEX_KLINE capability 分支**；manager.py:471）
- 复用既有 K 线缓存层（`get_kline_cache`）
- `indices[].errors` 是 **dict per-frequency**（如 `{"5m": "...", "d": null}`），与 §3.2.2 `results[].errors[]` 的 **list per-aspect** 形态不同——因为 K-line 是同 code 多频率组合，不是多 aspect 组合
- `codes` 参数可选，便于扩展覆盖（如添加沪深 300、科创 50 等）

**节省**：market-recap §4 指数全景从 **9+ calls → 1**。

#### 3.2.2 `POST /api/v1/agent/stocks/batch/profile` — 股票列表追踪

**触发场景**：stock-picking §4 funnel。

**端点**：`POST /api/v1/agent/stocks/batch/profile`

**请求体**：
```json
{
  "codes": ["600519", "000034", "002594", "300750", "688981"],
  "aspects": ["quote", "kline", "kline_5m", "info", "boards"]
}
```

**约束**：
- `codes` 长度 **1-5**（硬上限；超限 → 400 拒绝）
- `aspects` 至少 1 项；**`fund_flow` 不在支持列表**（已移除）

**响应**：
```json
{
  "results": [
    {
      "code": "600519",
      "ok": true,
      "data": {"quote": {...}, "kline": {...}, "kline_5m": {...}, "info": {...}, "boards": [...]}
    },
    {
      "code": "000034",
      "ok": false,
      "data": {"info": {...}},
      "errors": [{"aspect": "kline", "error": "DataFetchError", "message": "..."}]
    }
  ],
  "summary": {"requested": 5, "ok": 4, "failed": 1, "elapsed_ms": "~2345 (示例)"}
}
```

**aspects 取值**（5 项）：

| aspect | 对应方法 | 对齐 skill 步骤 |
|---|---|---|
| `quote` | `manager.get_realtime_quote(code)` | §4 步骤 6 |
| `kline` | `manager.get_kline_data(code, frequency="d", days=60)` | §4 步骤 7 |
| `kline_5m` | `manager.get_kline_data(code, frequency="5m", days=2)` | §4 步骤 8 |
| `info` | `manager.get_stock_info(code)` | §4 步骤 9 |
| `boards` | `manager.get_stock_boards(code, source="ths")`（source 必填：`"ths"` / `"eastmoney"` / `"zhitu"`） | §4 步骤 9 辅助 |

**实现要点**：
- 内部串行调 `manager.*` 已存在方法（**不新增 fetcher 逻辑**）
- per-aspect 错误隔离：每个 aspect 用独立 try/except
- per-code 错误隔离：单 code 整体失败时 `ok=false`
- 缓存 key：`hash((sorted_codes, sorted_aspects))` 作为 TTLCache key
- `@endpoint_meta(capabilities=[])`：聚合端点不映射单 capability

**节省**：stock-picking §4 funnel 走完 5 只候选当前 ≈ 15 次 HTTP；改为 1 次。

**与原 proposal 差异**：移除 `fund_flow` aspect；`codes` 上限从 50 → 5（funnel 实际场景 ≤ 5）。

#### 3.2.3 `GET /api/v1/agent/market-context` — 消息 + 涨跌停 + 龙虎榜

**触发场景**：market-recap §4 步骤 3 "消息面 / 涨跌停 / 龙虎榜"。

**端点**：`GET /api/v1/agent/market-context`

**参数**：
- `flash_limit: int = 20`（快讯条数上限；上限 200，与上游 `fetch_flash_news` 的 pageSize 硬 cap 一致）
- `trade_date` 可选；不传默认 = `get_latest_trade_date_on_or_before(today)`

**响应**：
```json
{
  "trade_date": "2026-07-27",
  "is_trade_day": true,
  "market_session": "post-market",
  "messages": {
    "morning_briefing": {...} | null,
    "market_recap": {...} | null,
    "flash_news": [...]
  },
  "limit_pools": {
    "zt": [...] | null,
    "dt": [...] | null
  },
  "dragon_tiger": {
    "stocks": [...],
    "summary": {
      "total_net_buy_wan": 12345,
      "top_by_net_buy": [{"code": "...", "name": "...", "net_buy_wan": ...}, ...],
      "top_by_net_sell": [{"code": "...", "name": "...", "net_buy_wan": ...}, ...]
    }
  },
  "summary": {...}
}
```

**逻辑约束**：
- **market_session 判断**：服务端读 `Asia/Shanghai` 时间戳 + `is_trade_date(today)`：
  - 交易日 09:15 前 → `pre-market`（与 `market-recap.md §2.2` 的 09:15 锚点对齐）
  - 交易日 09:15-15:00 → `intraday`
  - 交易日 15:00 后 → `post-market`
  - 非交易日 → `closed`
- **涨跌停（zt / dt）**：仅在 `pre-market` 时整体返回 `null`；其余时段正常查询
- **早报 / 复盘**：查询 `trade_date` 当天数据；若 CLS 当日未发布（28 天窗口内但内容缺） → 对应字段 `null`，不抛错
- **快讯**：始终返回 `flash_limit` 条（默认 20）

**实现要点**：
- 内部并行调用 `manager.get_morning_briefing(date)` / `manager.get_market_recap(date)` / `manager.fetch_flash_news(limit=flash_limit)` / `manager.get_zt_pool(pool_type="zt")` / `manager.get_zt_pool(pool_type="dt")` / `manager.get_daily_dragon_tiger(date)`
- 龙虎榜 summary 服务端计算：`total_net_buy_wan = sum(s.net_buy_wan)`；`top_by_net_buy/sell` 取 sort 后前 10
- 复用现有 morning-briefing / market-recap / zt-pool / dragon-tiger 缓存层
- 任一上游 `DataFetchError` → 对应字段 `null`，不中断整体

**节省**：market-recap §4 消息 + 涨跌停 + 龙虎榜从 **5-6 calls → 1**。

**与原 proposal 差异**：取代之前拆分版本的 `agent/news/cls/bundle`（仅早报+复盘）+ 单独 `?types=zt,dt`（仅涨跌停）+ 独立龙虎榜端点；整合成一个端点，新增龙虎榜 summary 计算维度。

#### 3.2.4 `POST /api/v1/agent/boards/overlap` — 板块间股票清单重叠度

**触发场景**：stock-picking §3 步骤 4 "对成分股重叠率高的板块，只取涨幅靠前的那一个"——**当前 LLM 拿到多个 board.stocks 后手动求交集**。

**端点**：`POST /api/v1/agent/boards/overlap`

**请求体**：
```json
{
  "codes": ["885xxx", "881yyy", "882zzz"]
}
```

**约束**：`codes` 长度 2-10（少于 2 无意义，多于 10 笛卡尔积过大）。

**响应**：
```json
{
  "sets": [{"code": "885xxx", "count": 42, "source": "ths"}],
  "pairs": [
    {
      "a": "885xxx",
      "b": "881yyy",
      "intersection": ["000001", "600519"],
      "intersection_count": 5,
      "jaccard": 0.118
    }
  ],
  "errors": []
}
```

**实现要点**：
- 内部对每个 code 调用 `stock_board_cache.get_board_stocks(code, source="ths", include_quote=False, manager=manager)`（**注意 `manager=` 是必填 keyword 参数**；`persistence/board.py:1136`）
- 缓存 key：`hash(tuple(sorted_codes))`
- 集合运算在内存中完成，纯 Python `set` 操作
- `pairs` 输出 C(n, 2) 笛卡尔积（10 boards → 45 pairs，可接受）
- `errors[]` 收集拉取失败的 code，不中断整体

**节省**：stock-picking §3 步骤 4 从"**2N + 手工求交集**" → 1 call（N = 待比较板块数）。

#### 3.2.5 `POST /api/v1/agent/stocks/board-overlap` — 股票与龙头板块重叠度

**触发场景**：stock-picking §4 步骤 9 "可用龙头所在板块清单与候选所在板块清单的重叠度作为加权（重叠高 → 受龙头带动作用预期更强，回引 `market-principles §6.6`）"——**当前 LLM 拉 `/stocks/{leader}/boards` + `/stocks/{candidate}/boards` + 手工 set 求交集**。

**端点**：`POST /api/v1/agent/stocks/board-overlap`（与 §3.2.4 镜像）

**请求体**：
```json
{
  "codes": ["leader_code", "candidate1", "candidate2", ...]
}
```

**约束**：`codes` 长度 2-10（与 §3.2.4 一致）。

**响应**：
```json
{
  "sets": [
    {"code": "leader_code", "boards": [{"code": "885xxx", "name": "..."}, ...]},
    {"code": "candidate1", "boards": [...]}
  ],
  "pairs": [
    {
      "a": "leader_code",
      "b": "candidate1",
      "common_boards": [{"code": "885xxx", "name": "..."}],
      "intersection_count": 2,
      "jaccard": 0.4
    }
  ],
  "errors": []
}
```

**实现要点**：
- 复用 §3.2.4 `boards/overlap` 的 set-op helper
- 内部对每个 code 调 `manager.get_stock_boards(code, source="ths")`（source 必填）
- 按 `(board_code, board_name)` 标准化（ths/eastmoney/zhitu 名称差异忽略）
- 缓存 key：`hash(tuple(sorted_codes))`（**不**走 `api/cache.py::get_stock_boards_cache`——该函数不存在；`/stocks/{code}/boards` 走的是 `persistence/board.py::get_stock_memberships`，本身已有 SQLite 缓存，TTLCache 不再叠加）

**节省**：stock-picking §4 步骤 9 板块重叠度从 **2N calls + 手工 → 1 call**。

#### 3.2.6 `POST /api/v1/agent/boards/filter-stocks` — 板块股票筛选

**触发场景**：stock-picking §4 步骤 6 "量价换手三维度硬门槛（换手 / 成交额 / 最高涨幅）+ 临场'尽量不碰大市值票'"——**当前 LLM 拿到候选 quote 后手算 `(high - open) / open` + 阈值比对**。

**端点**：`POST /api/v1/agent/boards/filter-stocks`

**请求体**：
```json
{
  "board_code": "885xxx",
  "source": "ths",
  "filters": {
    "turnover_pct": {"min": 5.0, "max": null},
    "change_pct": {"min": null, "max": null},
    "amount_yi": {"min": 1.0, "max": null},
    "mcap_yi": {"min": null, "max": 500.0},
    "max_gain_pct": {"min": 5.0, "max": null}
  },
  "limit": null
}
```

**filter 字段含义**（与 stock-picking §4 步骤 6 硬门槛对齐）：

| 字段 | 含义 | stock-picking §4 步骤 6 映射 |
|---|---|---|
| `turnover_pct` | 换手率 (%) | "换手 ≈ 5%（中票）/ 10-20%（小票）" |
| `change_pct` | 涨跌幅 (%) — 收盘 vs 昨收 | （辅助，非硬门槛） |
| `amount_yi` | 成交额（亿元） | "成交额 ≥ 10 亿（中票）" |
| `mcap_yi` | 总市值（亿元） | "尽量不碰大市值票（临场）" |
| `max_gain_pct` | 最高涨幅 (%) — `(high - open) / open * 100` | "最高涨幅 > 5%" 硬门槛 |

**约束**：
- `filters` 全部可选；空 filter = 返回板块全量成分股（受 `limit` 限制）
- `limit: int | None = None`：`None` = 不截断（返回全部 matched）；显式传 `int` = 截断到前 N

**响应**：
```json
{
  "board_code": "885xxx",
  "board_name": "...",
  "filters_applied": {...},
  "matched_stocks": [
    {
      "code": "...",
      "name": "...",
      "price": 12.34,
      "change_pct": 3.5,
      "max_gain_pct": 6.2,
      "turnover_pct": 8.5,
      "amount_yi": 12.5,
      "mcap_yi": 80.3
    }
  ],
  "summary": {
    "total_in_board": 42,
    "matched": 8,
    "limit_applied": false
  }
}
```

**实现要点**：
- 内部对 `board_code` 调 `stock_board_cache.get_board_stocks(board_code, source="ths", include_quote=True, manager=manager)`，拿到成分股 + quote 字段
- 服务端从 `high` / `open` 计算 `max_gain_pct`（避免 agent 端手算）
- 过滤后默认按"满足 filter 数降序 → matched_stocks 排序"
- 复用 `stock_board_cache` 既有缓存层

**节省**：stock-picking §4 步骤 6 从 "**N 次 /quote + 手工阈值比对 + 手工 max_gain**" → 1 call（N = 板块内候选数）。

#### 3.2.7 `POST /api/v1/agent/boards/batch-profile` — 板块画像（added 2026-08-27）

**为什么**:stock-picking §4 步骤 5 候选板块 funnel 后,agent 需要看每个候选板块的"近期趋势/量价/顶底"画像,而不是成分股。当前 agent 必须 N 次 hit `/boards/{code}/history?source=ths&frequency=d` 再手算——既慢又费 token。`market-recap` §4 步骤 4 也有同样的需求。本节把 boards 拉进 batch-profile 家族(stocks / indices → boards),补齐"标的画像"维度。

**端点**:`POST /api/v1/agent/boards/batch-profile`

**请求体**:

```json
{
  "codes": ["885595", "881270"],
  "frequency": "d",
  "days": 60
}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `codes` | `list[str]` (1-5) | 是 | THS platecode (885xxx concept / 881xxx industry) |
| `frequency` | `Literal[d/w/m/1m/5m/15m/30m/60m]` | 否 (默认 `d`) | 同 `_FEATURE_FREQS` |
| `days` | `int ≥ 2` | 否 | per-frequency 默认 + 范围 422 校验,沿用 `_resolve_and_validate_days` |
| `format` (query) | `json`/`md` | 否 (默认 `json`) | 同其他 agent 端点 |

**响应**(JSON):

```json
{
  "frequency": "d",
  "days": 60,
  "boards": [
    {
      "code": "885595",
      "name": "人形机器人",
      "quote": {"price": 1234.5, "change_pct": 1.23},
      "features": {
        "trend":  {"ma": {...}, "ma_change": {...}, "adx": ..., "rsi": {...}, "boll": {...}},
        "pivots": {"window_high": {...}, "swings": [...], "pending": {...}, "params": {...}},
        "volume": {"latest_volume": ..., "vol_ratio_5": ..., "z_anomalies": [...]}
      },
      "errors": {"quote": null, "features": null}
    }
  ],
  "summary": {"requested": 2, "ok": 2, "failed": 0, "elapsed_ms": 187}
}
```

形态完全镜像 `/agent/indices/batch-profile`(`{frequency, days, boards[i].{code,name,quote,features,errors{}}, summary}`),只是 `boards[i].code` 是 THS platecode 而非 index code。

**Source 维度**:固定 `ths` 单源。理由:
1. 只有 `ThsFetcher` 实现了 `get_board_realtime`(其他 fetcher 会 raise ValueError → 422)
2. board codes 跨源不兼容(THS platecode 885xxx / 881xxx vs EastMoney BKxxxx)
3. THS 拥有 8 个频率全集合(`d/w/m/1m/5m/15m/30m/60m`)

**Board type 处理**:不暴露给 caller。`ThsFetcher.get_board_realtime(board_code, board_type=None)` 内部从 `stock_board` cache 推断,cache miss 时调用 `get_board_metadata` 备用。失败 → `errors["quote"] = "DataFetchError: ..."`。

**缓存**:**没有 composite cache 层**(2026-08-28 起与 stocks/indices batch-profile 统一):
- 底层 `manager.get_board_realtime` 走 `get_quote_cache`(短期 TTL);`manager.get_board_history` 走 `get_history_cache`(per-frequency 多日 TTL)
- board 数据 intraday 时效性敏感,加 composite cache 反而引入 60s stale 风险
- `build_features` 是纯计算,sub-ms,在 N+1 网络往返面前不构成瓶颈

Stocks / indices batch-profile 的 composite cache 已在 2026-08-28 同步撤除(参考 boards/batch-profile 实现先例 + 同口径合理论证);`make_stocks_batch_profile_cache_key` / `make_indices_batch_profile_cache_key` 工厂已删除,`_reorder_by_code` helper 已删除。

**Manager 频率转换陷阱**:`manager.get_board_history` 验证 `BOARD_KLINE_FREQ_BY_SOURCE["ths"]`,其中包含**公开字符串**(`"5m"` 而非 `"5"`)。`_FEATURE_FREQS[frequency].mgr_frequency` 是为 stock/index 路径(`manager.get_kline_data`)设计的——**board 路径必须直接传 `frequency` 公开字符串**,否则每个分钟级请求 raise ValueError → 400。详见 `docs/superpowers/specs/2026-08-27-boards-batch-profile-design.md` §3.1 "Frequency translation note"。

**响应形态**:沿用 `IndexProfile`(无 `info` / `boards` 子 aspect——boards 没有"公司画像")。entry-level 健康通过 `errors{}` 中哪些 key 为 null 来表达。

**未抽新 helper**:handler 直接镜像 `get_indices_batch_profile` 循环骨架(2-aspect, errors-dict),仅替换数据源。考虑过 `_aspect_try` 风格 helper 但因 stocks 用 `list[StockBatchAspectError]` 而 indices 用 `dict` 形态不兼容而放弃。

**节省**:stock-picking §4 步骤 5 从 "**N 次 /boards/{code}/history + 手工 features**" → 1 call(N = 候选板块数)。

---

## 4. 文件位置总览

| 端点 / 变更 | 文件 |
|---|---|
| `?with_zt_flags=true`（既有扩展） | `stock_data/api/routes/boards.py` + `stock_data/api/schemas.py`（扩展 `BoardStockInfo`） |
| `POST /api/v1/agent/boards/overlap` | **`stock_data/api/routes/agent.py`** + `schemas.py` |
| `POST /api/v1/agent/stocks/batch/profile` | **`stock_data/api/routes/agent.py`** + `schemas.py` |
| `POST /api/v1/agent/stocks/board-overlap` | **`stock_data/api/routes/agent.py`** + `schemas.py` |
| `GET /api/v1/agent/indices/market-snapshot` | **`stock_data/api/routes/agent.py`** + `schemas.py` |
| `GET /api/v1/agent/market-context` | **`stock_data/api/routes/agent.py`** + `schemas.py` |
| `POST /api/v1/agent/boards/filter-stocks` | **`stock_data/api/routes/agent.py`** + `schemas.py` |
| **`_render_markdown(payload, template_fn)` helper** | **`stock_data/api/routes/agent.py`**（本地作用域；如未来非 agent 端点也用 MD，再提到 `helpers.py`） |
| **每个 agent 端点的 `render_as_markdown(payload)` 模板** | **`stock_data/api/routes/agent.py`**（6 个模板函数，约 200 行） |

**`agent.py` 统一归属所有 `/api/v1/agent/*` 端点 + MD 渲染层**（与 §2.1 / §2.2 约定对齐）。

---

## 5. 待决项

### D1：`aspects` 是否支持子集过滤（如 `kline?fields=date,close`）？

**推荐**：Phase 1 **不**支持。固定枚举足够覆盖 stock-picking §4 funnel 全场景；子集过滤会让 agent 自己拼参数 = 又回到 LLM 判断复杂度。等真有人需要再说。

### D2：batch profile 的 TTLCache key 策略

**推荐**：`(sorted_codes, sorted_aspects)` 元组。client 传 codes 时常会重排顺序（agent 输出不稳定），元组形式抗顺序扰动；与既有 `make_*_cache_key`（`api/cache.py`）风格一致。

---

## 6. Manifest Stage 1 / Stage 2 兼容性

- `?with_zt_flags=true` 是**既有端点扩展**，不需要在 manifest builder 改任何东西。
- **`/api/v1/agent/*` 端点**是新增 namespace：
  - `@endpoint_meta(capabilities=[])`：聚合端点不映射单 capability。`CAPABILITY_TO_METHOD`（`data_provider/base.py`）不期望为新端点造 flag；manifest builder 对 `capabilities=[]` 已有支持（fetcher drill-down 列表为空是合法状态）。
  - `/explorer/` UI 通过 `@router.post(..., tags=["agent"])` 独立分组（与 `tags=["stocks"]` / `["boards"]` / `["news"]` 平行），侧栏出现"Agent"独立区块。
  - manifest builder 已在 `explorer/manifest.py` 中按 tag 分组；新增 `agent` tag 无需改 manifest 代码。
  - **Stage 2 fetcher drill-down**：agent 端点的 fetcher 列表为空（无单 capability 对应），但 `Test` 按钮调用 `/control/fetcher-test` 仍可在 Stage 2 测试底层 fetcher 方法——预期行为，不算 bug。

---

## 7. 测试策略

| 测试类 | 覆盖目标 | 示例 |
|---|---|---|
| 单端点契约 | 路径 / 状态码 / response shape | `test_post_stocks_batch_profile_ok`、`test_market_context_intraday` |
| 错误隔离 | per-aspect / per-code 失败不串 | `test_batch_profile_one_aspect_fails_others_succeed` |
| 缓存命中 | 同 body 二次调用命中 TTLCache | `test_batch_profile_cache_hit` |
| Manifest 反射 | 新端点出现在 `/control/api-manifest` | `test_agent_endpoints_in_manifest` |
| 时段逻辑 | pre-market / intraday / post-market 返回正确 | `test_market_context_pre_market_pools_null` |
| 阈值筛选 | filter-stocks 边界值 | `test_filter_stocks_turnover_min_excludes_below` |
| codes 上限 | batch/profile codes > 5 拒绝 | `test_batch_profile_codes_over_limit_400` |
| overlap 计算 | 集合运算正确性 | `test_boards_overlap_jaccard_correct` |
| MD 投影 | `?format=md` 返回 markdown 文本 + 关键 section 完整 | `test_agent_endpoints_format_md_contains_expected_sections`（覆盖 6 个端点各 1 个 happy-path） |
| MD Content-Type | response header 正确 | `test_format_md_content_type_is_text_markdown` |

**不**写：LLM 调用模拟测试（超出单元测试范围；用 `tests/_network_guard.py` 保护 live_network 类测试即可）。

---

## 8. 优先级与 ship 节奏

### Phase 1：低风险高复用（推荐先 ship）

| # | 端点 | 类型 | 工作量 | 风险 |
|---|---|---|---|---|
| 1.1 | `?with_zt_flags=true` | 既有扩展 | 1-2 小时 | 低 |
| 1.2 | `POST /api/v1/agent/boards/overlap` | agent 端点 | 2-3 小时 | 低 |
| 1.3 | `POST /api/v1/agent/stocks/board-overlap` | agent 端点 | 2-3 小时（与 1.2 镜像，复用 helper） | 低 |
| 1.4 | `POST /api/v1/agent/boards/filter-stocks` | agent 端点 | 2-3 小时 | 低 |

**Phase 1 总计**：1-1.5 天。立即收益：
- stock-picking §4 funnel 从 30 calls 降到 ~15 calls（1.1）
- stock-picking §3 步骤 4 重叠度去重从"多次 board/stocks + 手工" → 1 call（1.2）
- stock-picking §4 步骤 9 反向板块重叠从 2N calls → 1 call（1.3）
- stock-picking §4 步骤 6 量价硬门槛从 "N × /quote + 手工阈值 + 手工 max_gain" → 1 call（1.4）
- **累计效果**（Phase 1 全部 ship 后）：stock-picking §4 funnel 从 ~30 calls 降到 ~5 calls（1.1 + 1.2 + 1.3 + 1.4 合并收益）

### Phase 2：聚合 bundle 端点 + MD 投影（推荐先 ship 端点，MD 跟随）

| # | 端点 | 工作量 | 风险 |
|---|---|---|---|
| 2.1 | `GET /api/v1/agent/indices/market-snapshot` | 半天（fan-out + 错误隔离 + TTLCache） | 中 |
| 2.2 | `GET /api/v1/agent/market-context` | 半天到 1 天（最多 fan-out + 时段逻辑 + 龙虎榜 summary 计算） | 中 |
| 2.3 | `POST /api/v1/agent/stocks/batch/profile` | 半天到 1 天（最大端点；fan-out + 错误隔离 + 缓存策略） | 中 |
| 2.4 | **MD 投影层（`_render_markdown` helper + 6 个端点模板）** | 1-1.5 天（helper 2 小时 + 每端点模板 2 小时） | 低（纯渲染，不改数据语义） |

**Phase 2 总计**：3-4.5 天。

**MD 投影 ship 策略**：
- 方案 A（推荐）：**2.4 排在 2.1-2.3 之后**——先把端点稳定下来再用 MD 包装。优点：MD 模板可参照真实 JSON 输出设计；缺点：用户先看到的是 JSON。
- 方案 B：MD 与每个端点同步 ship（2.1 + 2.1-md, 2.2 + 2.2-md, 2.3 + 2.3-md）——端点首次落地就支持 MD。优点：用户从 day 1 用 MD；缺点：6 个端点 × 2 阶段管理负担。

**推荐方案 A**：等端点形态稳定再做 MD 模板（YAGNI 反向应用——"先让数据语义沉淀，再做展示层"）。

### 推迟决策点的核心理念

每完成一个 Phase，**重新量化剩余 HTTP 调用数 + LLM 手算步骤数**：
- 若剩余 < 5 次/funnel 且无明显手算 → 停，不必做下一 Phase
- 若仍有明显瓶颈 → 启动下一 Phase

**YAGNI 原则**：没量化的优化是过早抽象。Phase 2 故意推到 Phase 1 之后决策，避免 agent 在没有量化数据前预先构建复杂聚合体系。

---

## 9. 兼容性 / 回滚

- `?with_zt_flags=true` 默认 `false`，回滚 = 不传新参数即可。
- 6 个 agent 端点是新增，回滚 = 移除对应 `@router.post` + schema 即可，无既有 client 依赖。
- `?format=md` 是 opt-in 投影（默认 `format=json`），回滚 = 不传 `format` 参数即可。MD 渲染失败 → 路由层捕获并 fallback 到 JSON 响应（带 warning header），保证 client 不会因 MD bug 整体不可用。

---

## 10. 明确不做的（Tier C：判断下放红线）

> **CLAUDE.md 设计原则："Don't 把判断逻辑下放到 fetcher / 服务端"。本节记录明确**不**实现的提案，避免后续讨论反复提出。**

| 候选 | 不做的理由 | skill 中的位置 |
|---|---|---|
| 趋势标签 (`上升 / 下降 / 震荡 / 突破`) | 接近 market-principles §6 龙头识别 + 板块 K 线方向判定——属于方法论而非数据 | market-recap §4 步骤 4 |
| 5 分钟量能强度分 (`弱 / 中 / 强`) | §4 步骤 8 明确"软排序因子，临场判定"——服务端的字符串标签会干扰 agent 临场判定 | stock-picking §4 步骤 8 |
| 量价换手"通过/不通过"布尔 | §4 步骤 6 阈值是中票/小票双表，agent 需看绝对值 + 市值分档——bool 隐藏判断 | stock-picking §4 步骤 6 |
| 龙头识别结果 | market-principles §6 龙头是判断方法论，不动 | market-recap / stock-picking 通用 |
| 归因（消息驱动 / 资金轮动 / 技术面） | market-principles §5 + §8 核心原则——LLM 责任 | market-recap §4 步骤 4 |
| 选股候选最终取舍 | market-recap / stock-picking 明确"不做交易决策"——超出 skill 范畴 | stock-picking §2 + §7 anti-patterns |
| ZT pool 自动按板块分组（含 3×10cm 阈值判定） | 服务端可做但属于"判断下放"；agent 用 market-context 拿 zt + boards 数据后客户端自行计算 | stock-picking §3 步骤 3 |
| K 线复合指标（momentum_5d / ma60_distance_pct 等） | YAGNI：未量化的"agent 内部手算"不必服务端化；真有必要再说 | stock-picking §4 步骤 7 |
| 板块 fuzzy 去重（"半导体" / "半导体概念" / "第三代半导体"） | 启发式算法难有客观标准；agent 用现有 `/api/v1/boards?board_type=concept&sort_by=change_pct` 客户端自行处理（注意 `board_type` 必填；不是 `/boards` 裸路径） | stock-picking §3 步骤 4 |

**判定标准**：任何服务端计算若其输出是"agent 看不到中间值就接受结论"的形态（标签、布尔、排序名次），就属于判断下放，必须拒绝。允许的形态是**纯数值 / 集合 / 计数**——agent 看到结果后仍可独立判断。

**注意**：本次提案 §3.2.6 `boards/filter-stocks` 看似与"通过/不通过"类似，但实际是**纯数值过滤**（满足阈值 = 进入结果集），agent 拿到结果后仍可独立判断"是否真强势"。不属于判断下放。

---

## 11. 参考

- 端点目录：`skills/market-data-obtain.md`
- Skill 工作流：`skills/market-recap.md`（**§4 工作流** 步骤 3 指数全景 / 板块异动 / 涨跌停 / 资金流 / 消息面）、`skills/stock-picking.md`（§3 步骤 1-5 板块 funnel + §4 步骤 6-10 个股 funnel）
- 判断方法论：`skills/market-principles.md`（§5 核心原则 + §6 龙头股判断 + §8 归因约束）
- Manifest / endpoint_meta 契约：`CLAUDE.md` §"API Layer" + §"Stage 1/2 Fetcher Drill-down"
- 路由文件约定：`stock_data/api/routes/__init__.py` + 每个领域文件头注释
- 时段判断 helper：`stock_data/data_provider/persistence/trade_calendar.py::is_trade_date`
- 板块反向索引：`stock_data/data_provider/persistence/board.py`（`get_board_stocks` 公开 API；`fetch_board_stocks_with_zzshare_fallback` 底层 helper；`get_stock_memberships` 反向查询）