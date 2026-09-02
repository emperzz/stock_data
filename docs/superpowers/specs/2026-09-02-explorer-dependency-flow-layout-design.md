# Explorer 图视图: 三层依赖流水布局设计

Date: 2026-09-02
Status: Approved (brainstorming with user)

Supersedes: 2026-09-02-explorer-section-partition-graph-design.md 的"分区(按 section
竖列)"默认形态。该 spec 的 `depends_on` / `response_schema` / `GraphView` /
`NodeDetailPanel` 基础设施不变;本 spec 只改**图布局、边可见性与交互**,并把
"分区"模式重命名为"依赖流"。

## 1. Goal

用户反馈当前 Dependency Graph 的**分区布局太丑**:

- 12 个 section 各占一竖列 → 画布被撑到 ~2800px 宽;7 个 section 只有 1 个端点
  (calendar/dragon-tiger/health/indicators/hot-topics/north-flow/zt-pools 全是单点列),
  大片横向空白。
- **列无标题、无分组外框**:`GraphView` 只给每列顶部留白(`TITLE_H`),从未渲染
  section 标题或背景,读者无法分辨每列是什么。
- **默认没有任何端点↔fetcher 连线**(served-by 全隐藏,点端点才展开),只有
  composed-of 紫虚线。

用户想要的形态(经讨论收敛为三层依赖流水,不是 mermaid 实现、而是观感近似):

1. 布局像 mermaid flowchart:节点按依赖关系排成清晰层,边短、少交叉、自动对齐。
2. 端点与 fetcher 的连线默认**可见**(修复"现在没有 api 和 fetcher 相连")。
3. fetcher 仍承担"点开看它服务的 api"的角色 —— 在分层模型里以 **focus 强调**
   表达,而不是把端点物理塞进 fetcher 盒子(见 §4.4)。

**已确认的结构事实**(本设计的依据,实测 2026-09-02 manifest):全部 21 条
composed-of 都只从 agent 区的 9 个复合端点出发;没有任何非 agent 端点带
depends_on,也没有"目标端点再当来源"的链式 → 当前数据是干净的**两层 DAG**
(agent → 业务端点),下接 fetcher 是第三层。fetcher↔endpoint 为**多对多**
(33 个端点有 fetcher,其中 23 个被 ≥2 个 fetcher 服务;合计 ~90 条 served-by 边)。
设计不硬编码"DAG"假设 —— 布局算法按层摆放、对孤立端点做兜底,未来即使业务端点
互相依赖也不至于画崩,但不为此过度设计。

## 2. Scope / Non-goals

- **只改 `stock_data/explorer/static/index.html`**(单 HTML)。后端零改动;manifest /
  `@endpoint_meta` / GraphView 数据模型不变。
- **不把端点移入 fetcher 盒子、不做物理"折叠隐藏端点"**(多对多下端点无法同时属于
  多个 fetcher 容器;已在 brainstorming 中确认作废)。
- 不引第三方布局库(dagre / cytoscape / mermaid / elk)。crossing minimization 用手写
  重心排序,保持单文件零新依赖。
- 不保存用户自定义坐标 —— YAGNI(方向仅 竖排/横排 二选,见 §4.2)。
- 不引入前端测试框架(沿用"前端手动 smoke"约定)。

## 3. Current state (要动的代码)

- `index.html` 内 `GraphView` IIFE(`:779` 起):暴露 `load/render/applyFilter/applySearch/destroy`。
  当前 `render` 按 `opts.layout` 分支 `"section"|"force"`:
  - section 模式 = `buildGraph()` 全节点 + 剔除 served-by 边的 DataSet + `layoutSection()`
    手工竖列坐标 + `toggleExpansion/collapseExpansion/focusFetchers`(点端点展开其
    served-by 边的状态机)+ `applyFilter` 收起守卫。**无 section 标题/背景渲染。**
  - force 模式 = 全边 + barnesHut physics(现状,保留)。
- 主 app:`state.graphLayout`(localStorage `graphLayout`,值 `"section"|"force"`,默认
  `"section"`)、`#graphLayoutSwitch` 工具条、`renderGraph()`、`applyView()` graph 分支、
  `#graphWrap/#graphCanvas` 滚动容器。
- `NodeDetailPanel.showEndpoint/showFetcher` 完整可用,本改动不重建,只调整联动。

## 4. Design

### 4.1 布局模式重命名:`分区 → 依赖流`(flow)

- `#graphLayoutSwitch` 两段改为 **`依赖流` / `力导向`**,默认**依赖流**。
- 状态值:`state.graphLayout ∈ "flow"|"force"`;localStorage key `graphLayout` 沿用。
- **迁移**:旧值 `"section"` 读入时视为 `"flow"`(首次 render 后把 `"flow"` 写回
  localStorage),避免已存偏好失效。
- 力导向模式**原样保留**作为逃生口:全边 + physics(barnesHut)。

### 4.2 依赖流布局(新默认):三层 + section 分组框 + 重心排序

节点固定坐标、`physics:false`。手工把三类节点摆在 **3 个横排 rank**(自上而下):

```
R0  agent 复合端点(9)                        紫 ◇
R1  业务端点(46) —— 按 section 分成带标题的分组框
R2  fetcher(13)盒子 横排一条
```

- **R1 分组框**:每个含端点的 section 渲染为一个**可见的圆角分组块 + 顶部小标题**
  (修复当前"无标题列")。框内端点竖排、左对齐、紧凑;框宽按最长 label 自适应、框高
  按端点数。单端点 section(calendar/dragon-tiger/health/indicators/hot-topics/
  north-flow/zt-pools)= 窄小框,不占整列 → 消除大段空白。没有端点的 section 不生成框。
  分组框画法:canvas `beforeDrawing` 背景矩形 + 标题文字,或"透明 box 节点 + text
  节点垫底"任选(实现时选可控、且在平移/缩放/theme 下不漂的;详见 §5 的分组框画法
  注意)。框的视觉 = 半
  透明填充 + 边框 + 左上角 section 名,颜色读 CSS 变量(light/dark 都可用)。
- **质心锚定 + 居中(crossing minimization,手写 ~几十行)**:框内端点先摆成竖列;agent 与
  fetcher 按其"相邻端点"的质心定位,`floatRow`/`floatCol` 顺序摊开避免重叠后再用
  `centerRow`/`centerCol` 把整行/列在内容区间内**居中**(避免全部窝到单侧) → composed-of /
  served-by 边大多是短连线,少量交叉。
- 孤立端点(无 fetcher 且不被任何 composed-of 指向,如 `/indicators`、`/healthz`、
  `/news/content`、`/stocks/{code}/reports/{id}/pdf`、`/boards/{code}/news|surges` 等)
  仍然摆进自己 section 框、正常显示,只是无边 —— 不与 agent/fetcher 层耦合。
- **短标签**:分组框标题已表达 section 前缀 → 框内端点标签去掉该前缀(如 `stocks` 框内
  显示 `GET {code}/kline` 而非整条 path);agent(顶行/左列)用末段 action 名(如
  `POST market-context`);仍过长才省略号。悬停 tooltip 保留完整 `method path`。
- 画布按内容尺寸扩容,外层 `#graphWrap` 滚动;render 后 `network.fit()`。
- **方向选项(竖排 TB / 横排 LR)**:依赖流支持两种排版,`GraphView.render(…,{dir})`,
  `dir ∈ "TB"|"LR"`(缺省 `"TB"`):
  - **TB(竖排, 默认)**: agent 顶行、分组框中部、fetcher 底行 —— 自上而下读(本小节
    描述即此形态)。
  - **LR(横排)**: agent 移到**最左列**、fetcher 移到**最右列**;中间 section 分组框
    **纵向堆叠**(从上到下,各框仍是端点竖列)。视觉上 agent(左)→ 纵向 section 列(中)→
    fetcher(右),箭头从左往右读。
  - 状态 `state.graphDir`(localStorage `graphDir`,默认 `"TB"`);图内工具条在依赖流下
    显示「竖排/横排」,切到力导向时该控件禁用(方向对 force 无意义)。
  - 边/交互(focus/search/filter)对两种方向一致 —— 只依赖节点 id/DataSet,不依赖排布
    方向;两种方向的渲染无动画、固定坐标。

### 4.3 边:served-by 默认全画 + composed-of 主干 + focus 强调

- **served-by(端点→fetcher):默认全画**。样式:细(`width` 按 priority 0.5–2.5)、
  半透明灰、无箭头;`available===false` 的 fetcher 边保留虚线 + 更透明(沿用现有
  buildGraph 字段)。R2 重心对齐后视觉为整齐下垂短线 —— 直接修复"现在没有 api 和
  fetcher 相连"。
- **composed-of(agent→端点):恒显、主干**。紫虚线 + 箭头、比 served-by 粗,21 条可控。
- **focus 强调**(hover 或 click 节点,见 §4.4):把该节点**相邻**的边加粗、变不透明、
  相邻的 fetcher/端点轻微点亮;其余边的透明度压到 ~0.1,不移动节点位置。松手/再点
  空白 → 复原。

### 4.4 交互

- **hover 端点或 fetcher** → focus 该节点(邻边强调、其余淡出)。vis 现有 tooltip 保留。
- **单击 fetcher**(用户拍板 = 聚焦强调):
  1. focus 该 fetcher → 它服务的全部端点点亮(如橙色描边),它到这些端点的 served-by
     边加粗,其它 fetcher 相关边淡出;
  2. 同时 `NodeDetailPanel.showFetcher(name, MANIFEST)` 开详情(priority + Serves N)。
  3. 再点它 / 点空白 → 复原 focus,面板保留当前选中内容(与现有 Endpoints 视图一致)。
- **单击端点** → focus 该端点(composed-of 上游 + served-by 下游强调)+
  `NodeDetailPanel.showEndpoint`。
- **点空白** → 复原 focus。
- **原"点端点展开 served-by 边"状态机不再需要** —— served-by 默认全画,focus 取代它。
  相关旧 helper(`toggleExpansion/collapseExpansion/focusFetchers/allServedBy/expandedEp`)
  与 `applyFilter` 收起守卫随之删除或改造(实现时清理,不留死代码)。
- **fetch 方向**:单击 fetcher 不自动改左侧单选过滤;左侧 "Filter by fetcher" 逻辑照旧。

### 4.5 保留的既有交互(flow 与 force 都生效)

- 搜索 `applySearch` 暗化(基于 label fuzzy);market/fetcher 过滤 `applyFilter` 隐藏
  端点 + fetcher;端点被隐藏时其边一并隐藏。
- 🌗 主题切换重建图(节点/分组框颜色读 CSS 变量)。
- `NodeDetailPanel` 复用 `#resultBody`;切回 Endpoints 视图复位。
- 切视图(离开 graph)、切布局、主题重建 → focus 复位。

### 4.6 数据结构

两种布局共用同一批节点 id(`ep:<path>` / `fx:<name>`)与 `buildGraph()` 产出的
`{nodes, edges}`(全部 111 条边都在,含 served-by + composed-of)。差别仅在:

- 是否携带固定 `x/y`(flow 手工摆 / force 交给 physics);
- `physics` on/off;
- focus 状态(flow 用:当前 focus 节点 id + 一组"非相邻边"在焦点下的透明度覆写)。

filter/search/theme 操作同一批 DataSet 节点,不需为两布局写两套逻辑。

### 4.7 Files touched

| 文件 | 改动 |
|---|---|
| `stock_data/explorer/static/index.html` | `GraphView`:新增 `layoutFlow()`(三 rank + section 框坐标 + 重心排序)、分组框渲染(§4.2)、served-by 默认纳入 edges、focus 状态机(hover/click/空白);删除 section 旧竖列布局与展开状态机;主 app:`state.graphLayout` 值改 `"flow"`、工具条文案、`renderGraph` 传 `"flow"`、`graphLayout` 旧值 `"section"` 迁移;CSS(工具条/分组框配色/新 segmented 文案) |

后端零改动。

## 5. Edge cases / Error handling

- **空/单端点 section**:照常渲染为小分组框;无端点 section 不生成框。
- **孤立端点(无边)**:在自己的 section 框内正常显示。
- **focus 边界**:focus 一个端点时,它无 composed-of 上游或/和无数个 fetcher 下游都
  合法(空邻集 = 无强调边,只点亮自身);hover 状态与 click 状态冲突时以 click 为准。
- **分组框画法与坐标系**:若用 canvas `beforeDrawing`,需确认回调 ctx 已带网络视图
  变换(直接用网络坐标画框);若坐标系不符或平移/缩放/theme 下漂移,改用"透明 box
  节点 + text 标题节点垫底(加进 DataSet 顺序在端点前)"方案。实现时先验证再定,
  不可留下在缩放后背景错位的实现。
- **CDN 失败**:沿用现有降级提示(flow 也依赖 vis)。
- **旧 localStorage 值**:`"section"` → 读为 `"flow"` 并回写,避免旧偏好丢。
- 切布局/切视图/主题重建时 focus 复位;端点被 filter 隐藏时其边随之隐藏(无悬空线)。

## 6. Testing(无自动化 FE 测试)

手动 smoke,起 server(`SERVER_PORT=8891`,非 8888,用完查 `netstat` 拿 pid 后
`Stop-Process`,不 `taskkill //F` 未知 pid):

1. 默认进图 → **依赖流**:R0 agent 一排、R1 section 分组框(标题可见、紧凑、无大片
   空白)、R2 fetcher 一排;served-by 细线默认可见(抽查 `kline` 到 Tushare/Baostock…)、
   composed-of 紫虚线恒显(抽查 `market-context` → news/calendar/zt-pools/dragon-tiger)。
2. 单击某 fetcher → 它服务的端点点亮、相关边加粗、其它边淡出;右侧详情开;再点它或
   点空白复原。
3. hover 某端点 → 邻边强调、其余淡出;移开复原。
4. 切 `力导向` → 原状(全边 + physics);切回 `依赖流` → 布局恢复且 search/market 过滤保留。
5. 搜索 `kline` 暗化 / 取消勾 csi 过滤隐藏相关端点与边 / 🌗 切主题 → 均无报错、分组框颜色正确。
6. reload 布局选择持久化(`依赖流`);旧浏览器 localStorage 里 `graphLayout="section"`
   读入后变 `flow` 不报错;切回 Endpoints 再回来无残留。
7. **方向**:默认 `竖排`(agent 上/fetcher 下,从上往下)。点 `横排` → agent 到最左一列、
   fetcher 到最右一列、中间 section 框**纵向堆叠**,箭头左→右读;focus/search/filter 在
   横排下照常;切 `力导向` 时「竖排/横排」控件禁用、切回依赖流恢复。reload 后 `graphDir`
   选择持久化。

## 7. Out of scope (explicit)

- 把端点塞进 fetcher 容器、折叠即隐藏端点的字面模型 —— brainstorming 已否
  (多对多使端点无法同属多容器)。
- 严格树(把 46 端点当树、支持展开/收起/根选择)/ 用户自定义坐标 / 框可拖拽重排 —— YAGNI。
- 引入 dagre/mermaid/cytoscape 等布局库。
- 后端 manifest / `@endpoint_meta` 改动。
