# Design: THS 板块实时行情 + board_name 修复

**Date:** 2026-07-09
**Status:** Approved (design), pending implementation plan

## 背景 / 问题

三件事，围绕 `/boards/{board_code}/stocks` 与 THS 板块数据：

1. **`board.name == board.code` bug**（正确性）。`/boards/{code}/stocks` 返回的 `board`
   块名称回落成了板块代码。根因是 THS 概念板块存在 cid / platecode 双码：
   - URL slug（cid）示例 `301546`，用于 `q.10jqka.com.cn/gn/detail/code/{cid}/`。
   - 对外板块码（platecode）示例 `885595`，用于 `d.10jqka.com.cn/.../bk_{platecode}` 及
     公开 API 寻址。
   `stock_board` 表里概念板块存 `code=cid`、`platecode=885xxx`。公开 API 传进来的是
   platecode。`get_board_name`（`persistence/board.py:1310`）只按 `WHERE code = ?` 查，
   概念板块必然查不中 → 慢路径同样按 `b["code"] == board_code` 比较、同样不中 →
   路由层 `... or board_code` 把名称回落成代码。

   `/stocks/{code}/boards` 的反查路径（`_read_membership_entries`）已于 2026-07-09 修复
   （LEFT JOIN `stock_board` + `sb.code = m.board_code OR sb.platecode = m.board_code`），
   但正向的 `get_board_name` / `get_board_name_with_fallback` 漏改。

2. **`include_quote=true` 时 `board` 块无行情**（功能缺口）。当前无论 `include_quote`
   取值，`board` 块只回 `code + name`。用户要求 `include_quote=true` 时 `board` 块也拉取
   真实上游行情。

3. **THS 缺板块实时行情接口**（新能力）。需要一个抓取板块级实时数据（开盘价、涨跌幅、
   涨跌家数、净流入等）的接口。

## 上游调研结论（已实测 2026-07-09）

打开 `https://q.10jqka.com.cn/gn/detail/code/301546/`，并做**不执行 JS 的原始 fetch**，
确认板块行情全部是**服务端直出的静态 GBK HTML**（无需浏览器渲染）。DOM 结构：

```html
<div class="heading">
  <div class="board-hq" style="background:#d75442;">
    <h3>央企国企改革<span>885595</span></h3>      <!-- 名称 + platecode -->
    <span class="board-xj arr-rise">2934.39</span> <!-- 板块指数/现价 -->
    <p class="board-zdf">10.92&nbsp;&nbsp;&nbsp;&nbsp;0.37%</p> <!-- 涨跌额 涨跌幅 -->
  </div>
  <div class="board-infos">
    <dl><dt>今开</dt><dd class="c-fall">2921.12</dd></dl>
    <dl><dt>昨收</dt><dd>2923.48</dd></dl>
    <dl><dt>最低</dt><dd class="c-fall">2870.11</dd></dl>
    <dl><dt>最高</dt><dd class="c-rise">2936.89</dd></dl>
    <dl><dt>成交量(万手)</dt><dd>15343.80</dd></dl>
    <dl><dt>板块涨幅</dt><dd class="c-rise">0.37%</dd></dl>
    <dl><dt>涨幅排名</dt><dd>229/389</dd></dl>
    <dl><dt>涨跌家数</dt><dd><span class="arr-rise-s">175</span><span class="arr-fall-s">207</span></dd></dl>
    <dl><dt>资金净流入(亿)</dt><dd class="c-rise">34.79</dd></dl>
    <dl><dt>成交额(亿)</dt><dd>2642.50</dd></dl>
  </div>
</div>
```

结论：**用现有 `requests` + BeautifulSoup + `v=` token + GBK 解码模式即可**（与 `ths_fetcher`
所有既有方法一致），无需引入 playwright（会给服务端运行时加重浏览器依赖，且此处收益为零）。

`BoardInfo` schema（`api/schemas.py:278`）已包含 `price / change_pct / change_amount /
volume / amount / net_inflow / up_count / down_count` 等字段，THS 数据可几乎 1:1 映射；
仅 `开盘价 / 最高 / 最低 / 昨收 / 涨幅排名` 是 `BoardInfo` 未覆盖的。

## 方案

### 任务1 — 修复 board_name

`persistence/board.py`：

- `get_board_name`（:1310）SQL 改为：
  ```sql
  SELECT name FROM stock_board WHERE (code = ? OR platecode = ?) AND source = ? LIMIT 1
  ```
  参数 `(board_code, board_code, source)`。eastmoney/zhitu 的 `platecode` **为 NULL**，
  `platecode = ?` 分支求值为 UNKNOWN（非 TRUE），因此不会误命中——这正是 OR 第二分支对非
  THS 源无害的原因；THS 概念经 platecode 命中；THS 行业 `code==platecode`，
  `UNIQUE(code, source)` 保证至多一行。
- `get_board_name_with_fallback`（:1338）慢路径匹配改为
  `board_code in (b["code"], b.get("platecode"))`。

不改路由层 `... or board_code` 兜底（该兜底仍是"两级都查不到"的正确行为）。

### 任务2 — include_quote=true 时 board 块拉真实行情

`api/routes/boards.py` 的 `get_board_stocks`（:415）：`include_quote=true` 时调用
`manager.get_board_realtime(board_code, source)`，用返回 dict 填 `BoardInfo` 的既有行情字段
（price / change_pct / change_amount / volume / amount / net_inflow / up_count / down_count）。
填入的单位与 `get_board_realtime` 返回一致（volume=万手、amount=亿元、net_inflow=亿元），
与既有 `/boards?include_quote=true&source=ths` 路径保持同一约定（见任务3 B1 修复）。
`board_name` 仍走任务1修好的 `get_board_name_with_fallback`。

`include_quote=true` 时，既有 `stock_board_cache.get_board_stocks(..., include_quote=True, ...)`
本就强制走上游新鲜抓取（`persistence/board.py:866` `needs_refresh = include_quote or ...`），
所以 `stocks` 是新鲜的；`get_board_realtime` 只在 `include_quote=true` 分支调用，`board` 块行情
与 `stocks` 同为新鲜数据。

失败处理（best-effort）：捕获 `DataFetchError / ValueError / AttributeError`，回落到仅
`code + name`，不 500：
- `source=eastmoney/zhitu`：`_with_source` 能选中 fetcher（二者都声明 STOCK_BOARD + csi），
  但该 fetcher 无 `get_board_realtime` 方法 → `AttributeError`（**这是本回落的主要触发点**）。
- `DataFetchError`：THS 上游失败。
- `ValueError`：`_with_source` 在 source 未知 / fetcher 未声明能力时抛——本路由 source 已被
  `Literal["ths","eastmoney","zhitu"]` 收口且三者都有 STOCK_BOARD，故 `ValueError` 实际不可达，
  仅作防御性捕获。
`include_quote=false` 路径完全不变。

> **路由分层说明**：本调用直接走 `manager.get_board_realtime`，与既有
> `/boards/{code}/history`（`boards.py:672` 直接调 `manager.get_board_history`）一致——
> CLAUDE.md 的 "Persistence-Only Routing" 规则对**不可缓存的板块 read-through**（K线历史、
> 实时行情）有既定豁免。此处是把该豁免显式扩展到板块实时行情，而非静默绕过规则。

> 范围界定：任务3只实现 THS 板块实时。`source=eastmoney/zhitu` 的板块实时行情**不实现**，
> best-effort 留空。

### 任务3 — ThsFetcher 板块实时接口

**Fetcher 方法** `ThsFetcher.get_board_realtime(board_code, *, board_type=None, **kwargs) -> dict`：

- 入参为 platecode（`885595`）。用 `persistence.board._resolve_ths_cid_from_platecode(board_code)`
  解析出 cid；解析不到（缓存冷 / 入参本身即 cid）则直接用 `board_code` 拼 URL 兜底。
- `self._http_get(_CONCEPT_DETAIL_URL.format(slug=cid), headers={UA, Referer, Cookie: v=<token>})`，
  `r.encoding = "gbk"`，非 2xx → `DataFetchError`。
- BeautifulSoup(lxml) 解析：
  - `.board-hq h3`：`name`（去掉 span 文本）、`board_code`（span 文本 = platecode）。
  - `.board-xj`：`price`。
  - `.board-zdf`：文本按空白/`&nbsp;` 切分 → `change_amount`、`change_pct`（去 `%`）。
  - 遍历 `.board-infos dl`，以 `dt` 文案为 key 取 `dd`：今开→`open`、昨收→`prev_close`、
    最低→`low`、最高→`high`、成交量(万手)、涨幅排名→`rank`（字符串 `"229/389"`）、
    涨跌家数→两个子 span 得 `up_count`/`down_count`、资金净流入(亿)→`net_inflow`、
    成交额(亿)→`amount`。
  - 价格类（price/open/prev_close/high/low）与 change_amount 用 `core.types.safe_float`
    （`--` → None）；`up_count`/`down_count` 用 `safe_int`；`volume` 用 `safe_int`（对齐既有
    industry-rank 解析，见下）。
  - **符号规则**：显示文本是量级，正负号从 `arr-rise/arr-fall`（`.board-xj` / `.board-zdf`）与
    `c-rise/c-fall`（`dd`）CSS class 推导。实现时用一只**下跌板块**的 HTML fixture 验证符号
    （当前实测样本是上涨板块，不足以覆盖负号分支）。
- **单位：保持上游原始单位，不做换算**（这是 review B1 的修复点）。既有
  `/boards?include_quote=true&source=ths` 路径的 industry-rank 解析
  （`ths_fetcher.py:~1494`）把 `volume` 存为 `万手`(safe_int)、`amount` 存为 `亿元`、
  `net_inflow` 存为 `亿元`，且原样透传进 `BoardInfo`。为避免同一个 `BoardInfo` 字段在不同
  代码路径下单位不一致，`get_board_realtime` 也必须返回：`volume` = 成交量**万手**(safe_int)、
  `amount` = 成交额**亿元**、`net_inflow` = 净流入**亿元**。**不**做 万手→股 / 亿→元 换算。
- 返回 dict 键：`board_code, board_name, cid, price, change_amount, change_pct, open,
  prev_close, high, low, volume(万手), amount(亿元), up_count, down_count, net_inflow(亿元), rank`。

**Manager** `get_board_realtime(board_code, source) -> tuple[dict, str]`：照抄 `get_board_history`
（`manager.py:815`）形状，用 `_with_source(source, DataCapability.STOCK_BOARD, "csi",
op_label, call)`，返回 `(dict, fetcher_name)`。

**REST 独立接口** `GET /boards/{board_code}/quote`：

- Query：`source: Literal["ths"]`（REQUIRED；当前仅 THS 实现，传 eastmoney/zhitu 由 FastAPI
  的 `Literal` 校验直接返回 422）。
- 新增 `BoardQuoteResponse`（`api/schemas.py`）：`board_code, board_name, source, price,
  change_pct, change_amount, open, high, low, prev_close, volume, amount, net_inflow,
  up_count, down_count, rank`（含 `BoardInfo` 未覆盖字段）。**每个字段的 `Field(description=...)`
  必须显式标注单位**：`volume` = 万手、`amount` = 亿元、`net_inflow` = 亿元、
  price/open/high/low/prev_close/change_amount = 指数点、change_pct = %、rank = 字符串
  `"229/389"`（不要沿袭 `BoardInfo.amount` 未标单位的疏漏）。
- `@endpoint_meta(summary=..., markets=["csi"], capabilities=["STOCK_BOARD"],
  fetcher_method="get_board_realtime")`。直接调 `manager.get_board_realtime`（与
  `/boards/{code}/history` 同为不可缓存 read-through 的先例），`@map_errors` 把
  `DataFetchError → 503`、`ValueError → 400`。

## 数据流

```
GET /boards/{code}/quote?source=ths
  → routes.boards.get_board_quote
    → manager.get_board_realtime(code, "ths")
      → _with_source → ThsFetcher.get_board_realtime(code)
        → _resolve_ths_cid_from_platecode(code)  (cache) → cid
        → _http_get(/gn/detail/code/{cid}/) → gbk → BS4 parse
      → (dict, "ths")
    → BoardQuoteResponse

GET /boards/{code}/stocks?include_quote=true&source=ths
  → routes.boards.get_board_stocks
    → stocks: stock_board_cache.get_board_stocks(...)  (既有)
    → board_name: get_board_name_with_fallback(...)     (任务1修复)
    → board quote: manager.get_board_realtime(code, source)  (任务2, best-effort)
    → BoardStocksResponse(board=BoardInfo(...quote...), stocks=[...])
```

## 组件边界

- **ThsFetcher.get_board_realtime**：纯上游抓取 + 解析，返回标准 dict；不碰缓存、不碰
  BoardInfo/schema。可用 HTML fixture 独立测试。
- **manager.get_board_realtime**：source 路由（无 failover），透传。
- **routes.boards**：dict → Pydantic 响应模型的组装 + best-effort 容错。
- **persistence.board（任务1）**：只改 SQL/比较逻辑，接口签名不变。

## 错误处理

| 场景 | 行为 |
|---|---|
| 上游非 2xx / 网络失败 | `DataFetchError` → 独立接口 503；任务2 board 块 best-effort 留空 |
| `.heading` 缺失（解析不到） | `DataFetchError` |
| platecode 解析不到 cid | 用 board_code 兜底拼 URL |
| `source=eastmoney/zhitu`（任务2） | 目标 fetcher 无该方法 → `AttributeError` → best-effort 留空 |
| 个别 dd 值为 `--` | `safe_float` → None（字段级） |

## 测试

- **任务1**：seed 一条 THS 概念 `stock_board` 行（code=cid、platecode=885xxx），断言
  `get_board_name(platecode, 'ths')` 与 `get_board_name_with_fallback` 返回名称（先红后绿）。
- **任务3 解析**：用抓取的真实 HTML fixture（上涨样本 + 一只下跌样本验证符号）做 mock 单测，
  断言各字段值/单位/符号。
- **manager/路由**：`test_capability_method_map` 已保证 `STOCK_BOARD` 在
  `CAPABILITY_TO_METHOD`；启动 sanity check 会校验 `fetcher_method="get_board_realtime"`
  真实存在于 ThsFetcher。
- **live_network**（打真实上游，标 `live_network`）：`/boards/{code}/quote?source=ths` 冒烟。
- **任务2**：mock `manager.get_board_realtime`，断言 `include_quote=true` 时 board 块被填、
  失败时 best-effort 回落 code+name、`include_quote=false` 时行为不变。

## 非目标（YAGNI）

- 不引入 playwright。
- 不为 eastmoney/zhitu 实现板块实时行情。
- 不把板块实时行情写入 SQLite（realtime 不缓存，遵守既有反模式）。
- 不给 `BoardInfo`（板块清单 schema）增加 open/high/low 字段——这些只进 `BoardQuoteResponse`。
