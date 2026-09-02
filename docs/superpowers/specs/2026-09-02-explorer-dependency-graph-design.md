# Explorer 依赖关系节点图 — 设计

- **日期**: 2026-09-02
- **状态**: 待用户 review
- **范围**: 在 `/explorer/` 增加一个可视化、可交互的依赖关系节点图视图，复用现有 manifest 数据与前端模块，不新建数据/渲染体系。

## 1. 目标与非目标

### 目标
1. 直观展示 server 每条 API 的"实现来源"：一条 endpoint 由哪些 fetcher 支撑（`endpoint → fetcher`），以及 agent 聚合端点由哪些端点/内部调用组合而成（`agent → endpoint`）。这两类边正是用户举例的两条。
2. 点击任意节点在右侧面板展示尽量详细的信息：摘要、入参（path/query/body schema）、**响应 schema（字段级，新增）**、fetcher 链、内部依赖。
3. 复用现有代码：manifest 的 `fetchers[]` / `params` / `body.schema`、前端的 `JSONView` / `ResultPanel` / `el()` / theme / 事件委托 / `_exampleFromSchema()`。
4. 美观：延续 explorer 现有 Apple 风 CSS 变量体系，支持 light/dark，按 HTTP method / 节点类型配色。

### 非目标（YAGNI）
- 不画 `capability` 节点（25 个 flag 太碎、价值低；capability 作为 endpoint/fetcher 的 chip 展示即可）。
- 不画 `fetcher → 上游 API URL` 边（用户未要求；fetcher 上游 URL 留在 fetcher 文档）。
- 不做图导出 / 分享链接 / 实时联动（图是 manifest 静态快照，与 endpoint list 一致）。
- 不替换现有 endpoint list 视图——新增视图切换，两者并存。

## 2. 现状摸底（复用面与缺口）

### 已有（零改动可复用）
- **manifest `/control/api-manifest`** 每个 endpoint 已携带：`id, method, path, summary, markets, capabilities, params[], body{required, schema}, response_model(类名字符串), fetchers[]`。
- **`fetchers[]`** 已按 priority 升序枚举可调度 fetcher，每项 `{name, method, priority, capabilities, signature[], available, reason}`。**`endpoint → fetcher` 边的数据完全现成。**
- **`body.schema`** 是 Pydantic `model_json_schema()` 全量 JSON Schema（含 `$defs`/`properties`/`required`）。前端 `_exampleFromSchema()` 已能解析 `$ref`/`$defs`。
- **前端**：纯 vanilla JS 单 HTML（`stock_data/explorer/static/index.html`），IIFE 模块化（`JSONView` / `ResultPanel` / 主 app），`el()` DOM helper、`escapeHTML()`、light/dark theme、事件委托、localStorage state、search+fuzzy+Ctrl+K。三栏布局（sidebar 280 / main / result-panel 440）。
- **`CAPABILITY_LABELS`**（`tags.py`）提供 capability → {label, icon} 装饰映射。

### 缺口（需新增）
1. **`agent → 内部调用` 边**：9 个 agent route 各自调用 `manager.xxx()` / `stock_board_cache.xxx()` / `trade_calendar.xxx()` / `features.build_features()`，数据不在 manifest 里（CLAUDE.md 表格有人工记录，代码无结构化）。
2. **响应字段级 schema**：`response_model` 只有类名字符串，无字段级 JSON Schema。
3. **图可视化库**：现前端零外部依赖，无图布局/交互能力。

### 关键约束
- **`/openapi.json` 被禁用**（`server.py:191-205`，`openapi_url=None`）。不能靠 OpenAPI 取 response schema，必须走 manifest 扩展。
- **装饰器契约**：`endpoint_meta.deco` 必须返回原 `func`（`endpoint_meta.py:12-16`），新增字段不能破坏这点。
- **装饰器顺序**：`@router.get → @endpoint_meta → @map_errors → @cache_endpoint → def`（CLAUDE.md Anti-Patterns）。新增 `depends_on` 是 `@endpoint_meta` 的参数，不改变顺序。
- **`MANIFEST_VERSION`** 当前 `1.1`（`manifest.py:39`）。新增字段需递增并保持后向兼容（前端 FALLBACK 容错已存在，`index.html:395-399`）。

## 3. 方案选项与推荐

### 选项 A：vis-network via CDN（**推荐**）
- **库**：[vis-network](https://github.com/visjs/vis-network)（UMD 单文件，CDN 引入一行 `<script>`）。
- **优点**：50 节点级别性能充足；拖拽/缩放/平移/点击/悬停/物理布局开箱即用；节点是 DOM 可定制样式；封装后可随时切 vendor 本地（改一行 `src`）。最契合"不要从头建一套"。
- **缺点**：默认视觉偏工程化，需调色才美观；CDN 首次加载需浏览器能访外网。
- **graceful degradation**：CDN 加载失败 → 图区显示提示"图库加载失败，请检查网络或切 vendor 本地"，现有 endpoint list 视图不受影响（独立模块）。

### 选项 B：D3.js force-graph via CDN
- **优点**：视觉可控性最强，可做最精致的定制布局与动画。
- **缺点**：force 布局 + 拖拽/缩放/点击/高亮全得自己写，代码量是 A 的 3-5 倍；50 节点级别杀鸡用牛刀。

### 选项 C：纯手写 SVG/Canvas
- **优点**：零依赖，完全延续 vanilla 风格。
- **缺点**：force-directed 布局算法 + 交互全自写，工作量最大、美观风险最高。与"不要从头建一套"相悖。

### 选项 D：cytoscape.js via CDN
- 与 A 同量级，布局算法更丰富，但 API 更重、节点样式定制不如 vis 直观。

**推荐 A**。理由：复用最大化、代码量最小、50 节点够用、graceful degradation 安全、库封装后可切 vendor。下面设计以 A 为准，但 `GraphView` 模块封装使底层库可替换为 B/C/D 而不动上层。

## 4. 设计

### 4.1 节点模型

三类节点：

| 类型 | 来源 | 形状 | 配色 |
|---|---|---|---|
| **Endpoint（普通）** | manifest endpoint，`capabilities` 非空 | dot | 按 method：GET=蓝(`--accent`)、POST=绿(`--accent-post`) |
| **Endpoint（agent 聚合）** | manifest endpoint，`capabilities=[]` 且 tag=`agent` | diamond | 紫色边框 + 半透明填充 |
| **Endpoint（纯计算/健康检查）** | `fetchers=[]` 且 `capabilities=[]`（如 `/indicators/catalog`、`/health`） | dot（小） | 灰色 |
| **Fetcher** | 从 manifest 所有 `fetchers[]` 聚合去重（13 个） | box | 中性面 + priority badge（P0 深、P9 浅） |

不画 capability / 上游 API 节点（YAGNI）。

**节点标签**：Endpoint 显示 `METHOD path`（path 太长时截断+title 全称）；Fetcher 显示 `name` + 右上角 `P{priority}` 小角标。

**unavailable fetcher**（`available=false`，如 Zhitu 未配 token）：节点半透明 + 虚线边框 + title 显示 `reason`。

### 4.2 边模型

两类边：

| 边类型 | 语义 | 数据源 | 视觉 |
|---|---|---|---|
| **served-by** | Endpoint → Fetcher | manifest `fetchers[]`（现成） | 实线，priority 越小越粗/越深；`available=false` 的 fetcher 边虚线 |
| **composed-of** | Agent endpoint → 目标 endpoint | 新增 `depends_on`（见 §5） | 实线带箭头，紫色 |

**不画**的内部调用（`manager.xxx` / `cache.xxx` / `calendar.xxx` 无对应 endpoint 的）只在详情面板以"内部依赖"列表展示（§4.5），不画图边，避免图过载。

### 4.3 入口形态

topbar 加一个**视图切换**（两段式 segmented control）：
- `Endpoints`（默认，现有 list 视图）
- `Dependency Graph`（新）

切换时：
- main 区内容在 `renderContent()`（list）与 `GraphView.render()`（图）之间切换。
- sidebar 的 market/fetcher filter **复用**，作用于图（过滤隐藏不匹配的 endpoint 节点 + 其相连边）。
- 右侧 `ResultPanel` 区在"Try-it 响应"与"节点详情"间切换：图视图下显示 `NodeDetailPanel`，list 视图下显示原 `ResultPanel`。两者共用同一 440px 容器，按当前视图切换。
- search 框复用：图视图下 fuzzy 命中节点高亮 + 居中，未命中暗化。

视图状态持久化到 `localStorage`（`view: "endpoints" | "graph"`），刷新保留。

### 4.4 交互

- **拖拽**节点、**缩放**画布、**平移**（vis-network 内置）。
- **点击节点** → 右侧 `NodeDetailPanel` 渲染详情（§4.5）。
- **悬停节点** → 高亮该节点 + 一跳邻居（边+对端节点），非邻居暗化到 20% 透明度。
- **双击节点** → 切到 Endpoints 视图并滚动定位到该 endpoint card（复用 `#ep-{id}` DOM 锚点）。
- **search** → fuzzy 命中节点保持高亮，未命中暗化（复用 `fuzzyMatch()`）。
- **filter** → market/fetcher 复选框作用于图（复用 `epMatchesFetcherFilter()` 逻辑）。
- 物理 slider：提供"松散/紧凑"两档（vis-network `physics.stabilization` + `springLength` 预设），避免节点堆挤。

### 4.5 节点详情面板（`NodeDetailPanel`）

新 IIFE 模块，复用右侧 440px 区（与 `ResultPanel` 互斥切换）。详情按节点类型渲染：

**Endpoint 节点**：
- 顶部 meta：`METHOD path` + summary
- markets chips、capabilities chips（复用 `CAPABILITY_LABELS` icon）
- **Parameters**：复用现有 `renderEndpointDetails` 的 params `<pre>` 渲染逻辑
- **Request body schema**：若 `body.schema` 存在，用 `JSONView.render(body.schema)` 展示（可折叠）
- **Response schema**（**新增**）：若 `response_schema` 存在，用 `JSONView.render(response_schema)` 展示；顶部注明"静态 schema，条件序列化字段可能与实际输出略有出入"（见 §5.3）
- **Fetcher backends**：复用 `renderFetcherRow()` 渲染 served-by 链（含 Test 按钮 + mini-form，复用现有 `bindFetcherTestHandlers` 事件委托）—— 点击 Test 时 `ResultPanel` 切回响应模式显示结果
- **Dependencies**（仅 agent）：渲染 `depends_on` 列表，分两组——`kind:"endpoint"` 项可点击跳到目标 endpoint 节点（与图上的 composed-of 边对应）；`kind:"internal"` 项（如 `manager.get_realtime_quotes`、`cache.get_board_list`）以纯文本展示（不画图边）

**Fetcher 节点**：
- name、priority badge、markets、capabilities chips、available + reason（unavailable 时）
- **serves endpoints**：反向索引（前端从所有 served-by 边构建）—— 列出连入该 fetcher 的每条边 `{endpoint path} · .{method}(签名)`，可点击跳到该 endpoint 节点。同一 fetcher 在不同 endpoint 可能调不同 method，按边展示更准确（signature 取自对应 endpoint 的 `fetchers[].signature`）

### 4.6 美观

- 配色严格用 `index.html` 现有 CSS 变量（`--accent` / `--accent-post` / `--accent-warn` / `--text` / `--text-muted` / `--border`），dark theme 同步。
- vis-network 的 `nodes` / `edges` 配色从 CSS 变量读取（`getComputedStyle`），保证主题切换同步。
- 边默认半透明（opacity 0.4），高亮时满色 + 加粗。
- 节点字体用 explorer 现有 font stack。
- 画布背景透明，继承 `--bg`。

## 5. 数据源变更（后端）

### 5.1 `@endpoint_meta` 新增 `depends_on`

`EndpointMeta`（`endpoint_meta.py:29-46`）新增字段：

```python
@dataclass(frozen=True)
class EndpointMeta:
    summary: str
    markets: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    fetcher_method: str | None = None
    depends_on: list[str] | None = None  # NEW
```

`depends_on` 是字符串列表，每项：
- 以 `/` 开头 → 引用一条 endpoint path（如 `"/api/v1/stocks"`）→ 图上画 `composed-of` 实线边到该 endpoint。
- 否则 → 内部调用标签（如 `"manager.get_realtime_quotes"`、`"cache.get_board_list"`、`"calendar.is_trade_date"`）→ 仅详情面板展示，不画图边。

装饰器里声明，跟 route 物理在一起（符合现有"metadata 跟 route 在一起"哲学，与 `fetcher_method` 同模式）。手动维护，漂移靠测试 pin（§7）。

示例（`agent.py` 的 market-stats）：
```python
@endpoint_meta(
    summary="市场全量统计（个股+板块涨幅分布 + 桶形数据）",
    markets=["csi"],
    capabilities=[],
    depends_on=[
        "/api/v1/stocks",              # manager.get_realtime_quotes → 实时行情批量端点
        "/boards",                     # cache.get_board_list → 板块列表端点
        "manager.get_realtime_quotes", # internal（无对应端点时冗余列出，便于追溯）
        "cache.get_board_list",
    ],
)
```

> **映射约定**：`depends_on` 里 endpoint path 必须是 manifest 中实际存在的 path（builder 会解析为 `{target: endpoint_id, path}`）。`manager.xxx` / `cache.xxx` / `calendar.xxx` 是自由文本标签，builder 不校验存在性。当一条 manager 调用同时有对应端点时，**同时**列 endpoint path（画边）和 internal label（追溯）；只有 internal 时只列 label。

### 5.2 `build_manifest` 扩展

`_build_endpoint_node()`（`manifest.py:108-164`）新增两个字段：

1. **`depends_on`**（解析装饰器的 `meta.depends_on`）：
   ```python
   depends_on_resolved = _resolve_depends_on(meta.depends_on, app) if meta.depends_on else []
   ```
   `_resolve_depends_on` 遍历列表，path 项查 `app.routes` 找匹配 endpoint 的 `id`（找不到则降级为 `kind:"internal"`，防漂移），internal 项直接 `{kind:"internal", label}`。输出：
   ```json
   "depends_on": [
     {"target": "get_api_v1_stocks", "kind": "endpoint", "label": "/api/v1/stocks"},
     {"target": "manager.get_realtime_quotes", "kind": "internal", "label": "manager.get_realtime_quotes"}
   ]
   ```

2. **`response_schema`**（mirror 现有 `body.schema` 逻辑，`manifest.py:133-147`）：
   ```python
   response_schema = None
   if route.response_model and hasattr(route.response_model, "model_json_schema"):
       try:
           response_schema = route.response_model.model_json_schema()
       except Exception as e:
           logger.warning(f"[manifest] response schema reflection failed for {route.path}: {e}")
           response_schema = None
   ```
   `response_model`（类名字符串）保留不动，新增 `response_schema`（完整 JSON Schema）。

**`MANIFEST_VERSION`** → `"1.2"`（新增字段，后向兼容：前端对缺字段走 `||` 兜底）。

### 5.3 response schema 的已知限制

`model_json_schema()` 反映的是 Pydantic 静态模型，**不**反映运行时 `@model_serializer` 的条件序列化：
- `KLineData`（`schemas.py:198`）：`amount`/`change_pct` 静态 schema 标为可选，实际输出在缺失时为 `null`（条件序列化为 `null`）；`indicators` 字段在 None/空时**整个 omit**（`KLineData._serialize`，`schemas.py:250`），静态 schema 不体现 omit 语义。
- `StockQuote._serialize`（`schemas.py:94`）类似。

**处理**：详情面板 response schema 区顶部注明"静态字段清单，条件序列化/omit 语义以 [Standardized Data Schema](../../CLAUDE.md#standardized-data-schema) 为准"。schema 仍足以驱动"字段清单 + 类型 + 嵌套结构"展示，价值不打折。

## 6. 前端变更（`index.html`）

### 6.1 新增 `GraphView` IIFE 模块

```
const GraphView = (() => {
  // 依赖: vis-network (CDN, async load via <script> in boot)
  // 从 MANIFEST 构建 nodes/edges, 复用 collectAllFetcherNames() 反向索引
  // 暴露: render(containerEl, manifest, state, onNodeClick), destroy()
  // 物理: 两档预设 (loose/compact), 复用 CSS 变量配色
  // graceful: CDN 加载失败 render 失败提示
  // 交互: click→onNodeClick(node), hover→highlight 一跳邻居, drag/zoom/pan 内置
})();
```

nodes 来源：遍历 `MANIFEST.sections[].endpoints[]`（每条一个 Endpoint 节点）+ 聚合所有 `fetchers[].name` 去重（每个一个 Fetcher 节点）。
edges 来源：每个 endpoint 的 `fetchers[]`（served-by）+ `depends_on` 中 `kind:"endpoint"` 项（composed-of）。

### 6.2 新增 `NodeDetailPanel` IIFE 模块

```
const NodeDetailPanel = (() => {
  // 复用右侧 result-panel DOM (#resultPanel 容器)
  // 暴露: showEndpoint(ep), showFetcher(f, servedEndpoints), clear()
  // 复用: JSONView.render (schema), renderFetcherRow (served-by 链),
  //       CAPABILITY_LABELS (chips), escapeHTML
})();
```

与 `ResultPanel` 共用 `#resultPanel` 容器，按当前视图切换显隐。`ResultPanel.init()` 改为同时 init `NodeDetailPanel`（共用 button refs）。

### 6.3 主 app 集成

- `state` 新增 `view: "endpoints" | "graph"`（localStorage 持久化）。
- topbar 新增 segmented control（`#viewSwitch`），切换调 `renderMain()`。
- `renderMain()`：`view==="endpoints"` → `renderContent()`（现有）；`"graph"` → `GraphView.render(...)`。
- `boot()`：图视图首次激活时 lazy-load vis-network CDN（`document.createElement("script")` + `onload` → render；`onerror` → 渲染失败提示）。避免在 list 视图下白加载。
- `bindUI()`：market/fetcher filter 的 `onchange` 在图视图下额外调 `GraphView.applyFilter(state)`。
- search `oninput` 在图视图下调 `GraphView.applySearch(q)`。

### 6.4 CDN 与 vendor 切换

CDN 默认用 `https://cdn.jsdelivr.net/npm/vis-network@9/standalone/umd/vis-network.min.js`。
切 vendor 本地：把该文件下载到 `stock_data/explorer/static/vendor/vis-network.min.js`，改 `lazyLoad` 的 URL 即可，上层零改动（`GraphView` 只依赖全局 `vis`）。

## 7. 测试

### 后端（pytest，现有模式）
- 新建 `tests/test_manifest_depends_on.py`：
  - agent route（9 条）的 `EndpointMeta.depends_on` 非空。
  - `build_manifest` 输出里 agent endpoint 的 `depends_on` 含至少一条 `kind:"endpoint"`（可画图边）。
  - `depends_on` 中的 path 项能在 manifest 中找到匹配 endpoint（漂移检测）。
  - `response_schema` 非 None（对有 `response_model` 的 route）。
- 更新 `tests/test_explorer_manifest_endpoint.py`：`MANIFEST_VERSION` 断言升到 `1.2`；新字段 `depends_on` / `response_schema` 存在性。
- `tests/test_capability_method_map.py` / 启动 sanity 不受影响（`depends_on` 不进 `CAPABILITY_TO_METHOD`）。

### 前端
- 现有 explorer 前端无自动化测试（`index.html` 单文件）。靠 `tests/test_explorer_manifest_endpoint.py` pin manifest shape + 手动 smoke：
  - 切换视图、点击三类节点、hover 高亮、search 过滤、filter 过滤、theme 切换、CDN 断网提示。
- 不引入前端测试框架（YAGNI，与现有约定一致）。

## 8. 风险与缓解

| 风险 | 缓解 |
|---|---|
| `depends_on` 手动维护漂移 | 测试 pin（§7）+ path 项 builder 解析时找不到即降级 internal（不报错，但测试会抓到缺失） |
| CDN 不可达（内网/离线） | graceful degradation 提示 + 一行切 vendor 本地（§6.4） |
| response schema 与实际输出不符（条件序列化） | 详情面板注明 + 指向 CLAUDE.md 为准（§5.3） |
| 图节点过挤（~30 endpoint + 13 fetcher + 边） | 物理两档预设 + filter 缩小子集 + 悬停聚焦一跳邻居 |
| `MANIFEST_VERSION` 升级破坏旧前端 | 新字段后向兼容（前端 `||` 兜底）；FALLBACK manifest 已是空 sections 容错 |
| 装饰器契约（`deco` 必须返回原 `func`） | `depends_on` 只是 dataclass 字段，`deco` 不动（§5.1） |
| vis-network DOM 节点性能（50 节点级） | 远低于 vis 性能阈值；必要时切 Canvas 渲染（`shape:"dot"` 已是 Canvas） |

## 9. 实现顺序（供后续 plan）

1. 后端：`EndpointMeta` 加 `depends_on` + `build_manifest` 加 `depends_on`/`response_schema` + `MANIFEST_VERSION=1.2` + 9 个 agent route 声明 `depends_on`。
2. 后端测试：新建 `test_manifest_depends_on.py` + 更新 manifest endpoint 测试。
3. 前端：`GraphView` + `NodeDetailPanel` IIFE + topbar view switch + boot lazy-load + filter/search 集成。
4. 前端：CDN 引入 + graceful degradation + theme 同步。
5. 手动 smoke + spec 自审。

## 10. 不涉及
- 不动 fetcher 层、不动 manager、不动 schemas.py、不动 `/control/fetcher-test`。
- 不动现有 endpoint list 视图渲染逻辑（`renderContent` / `renderEndpoint` / `renderFetcherRow` 仅被 `NodeDetailPanel` 复用，不修改）。
- 不引入 npm/构建步骤（维持单 HTML + CDN）。
