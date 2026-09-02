# Explorer 图视图: 按 section 分区的依赖布局设计

Date: 2026-09-02
Status: Approved (brainstorming with user)

Supersedes: 2026-09-02-explorer-dependency-graph-design.md 的力导向默认形态。
该 spec 的 `depends_on` / `response_schema` / `GraphView` / `NodeDetailPanel`
基础设施不变, 本 spec 只改**图布局与交互**。

## 1. Goal

`/explorer/` 的 Dependency Graph 视图当前是 vis-network 力导向布局 —— 46 个端点 +
13 个 fetcher 节点 + served-by 边 + composed-of 边全部乱飘, 视觉不可读。

用户反馈"图太乱", 但**明确要保留全部节点与全部依赖关系**(不是删边、不是只留
agent 可达子图)。本改动把图视图**默认布局改为"按 section 分区"**: 端点各归其
section 区块、fetcher 集中在独立数据源区、served-by 边默认隐藏点击端点才展开,
composed-of 边始终可见。原力导向保留为备选模式, 供看"整体依赖感"。

## 2. Scope / Non-goals

- **只改 `stock_data/explorer/static/index.html`**(单 HTML)。不改后端 manifest /
  `@endpoint_meta` / GraphView 数据模型 —— manifest 已有全部所需字段
  (`sections[].id`, `endpoints[].{path,method,markets,capabilities,fetchers,depends_on}`)。
- 不做严格 parent-child 树(分区不是树)。
- 不做树方向选择(UD/LR…)、不做两桶式根覆盖 —— 这两者在讨论中已明确作废。
- 不引入前端测试框架(沿用项目"前端靠手动 smoke"约定)。

## 3. Current state (要动的代码)

- `index.html` 内 `GraphView` IIFE: 暴露 `load/render/applyFilter/applySearch/destroy`,
  当前 `render` 用 `buildGraph()` → 力导向物理。本改动在 `GraphView` 内新增
  **分区布局渲染**, 并扩展 `render` 选项以承载两种布局与展开态。
- `index.html` 主 app: `applyView/renderGraph/setView`; 图视图内容区
  `#content` 下挂 `#graphCanvas`。新增的图内工具条放进 `#content` 顶部。
- `NodeDetailPanel` 点击详情已是完整实现 —— 本改动不重建它, 仅调整点击联动。

## 4. Design

### 4.1 图内布局切换(`分区 Section` / `力导向 Force`)

- 图视图内容区顶部加一行小工具条:
  - `分区 / 力导向` segmented(默认 `分区`)。
  - 状态存 `state.graphLayout` + localStorage(`graphLayout`), 与 `state.view` 平级。
- 切布局 = 重建当前图(`GraphView.destroy()` → 重渲染), 不重新抓 manifest。

### 4.2 分区布局(新默认)

节点物理位置**手工计算**(关 physics, 节点带固定 `x/y`), 而非力导向/层级:

- **端点区块**: 把 `manifest.sections` 中所有含端点的 section 做成带标题的区块,
  按端点数降序排; 区块网格排布(每行放 N 块, 依视口宽自适应)。每区块内:
  - 标题 = `section id`(与左侧栏一致)。
  - 端点节点竖直堆叠、左对齐, 节点尺寸按最长 path label 归一。
  - 端点节点外观沿用现状: GET 蓝 / POST 绿 dot, agent(空 capabilities)紫菱形。
- **agent 区块**只放 9 个 agent 端点; 其余独立端点不进任何"根", 而是都出现在其
  section 区块内 —— **46 个端点全部可见、无一丢失**(回答"根覆盖"分歧)。
- **Fetchers 区**: 底部一整条, 13 个 fetcher box 横排, 默认置灰(dim), 平时不连边。

### 4.3 边渲染

- **composed-of**(agent→目标端点, 紫色虚线箭头): **始终可见、跨区块也画**。
  数量有限(~30), 且端点已各归其位, 视觉可控。这就是用户要的
  "market-context → 早报/复盘/快讯/zt-pools"。
- **served-by**(端点→fetcher): 分区模式下**默认不画**。见 §4.4 展开。
- **力导向模式**: 现状原样 —— 两种边全画(served-by 实线 / composed-of 虚线),
  barnesHut physics。

### 4.4 fetcher 展开(点击才看 API)

"fetcher 也要画出来, 点击才展开它的 API"落实为:

1. 端点节点上带一个 `×N fetchers` 计数(角标或 label 后缀)。
2. **单击端点** → 该端点到其 fetchers 的 served-by 边**动画式出现**, 对应 fetcher
   节点点亮、其余 fetcher 保持灰; 同时复用现有 `NodeDetailPanel.showEndpoint`
   在右侧列出完整链(含 `.method()` 签名)。点击即得"该端点的 fetcher API"。
3. 再单击该端点 / 单击画布空白 → **收回**该端点的 served-by 边, 回到默认。
   (单击切换语义, 不在分区模式下改变节点位置。)
4. 单击 fetcher 节点 → 现状 `NodeDetailPanel.showFetcher`(priority + Serves N)。

### 4.5 保留的既有交互(两种模式都生效)

- 悬停高亮邻居(vis tooltip/click 高亮现有 `network.on` 之外的 hover 效果)。
- 搜索 `applySearch` 暗化、`market/fetcher` 过滤 `applyFilter` 隐藏端点 +
  fetcher(端点被隐藏时其 served-by 边一并隐藏)。
- 主题切换重建图(节点颜色读 CSS 变量)。
- 点击 `NodeDetailPanel` 复用 `#resultBody`。

### 4.6 数据结构

两种布局共用同一批节点 id(`ep:<path>` / `fx:<name>`)与 `buildGraph()` 产出的
`{nodes, edges}`; 差别仅在:

- 是否携带固定坐标(`x/y`)。
- served-by 边是否在 `edges` DataSet 中(**分区默认不在**, 展开时 `add`, 收回时
  `remove`)。
- physics on/off。

这样 filter/search/theme 不需为两种布局写两套逻辑 —— 它们操作同一批
DataSet 节点。

## 5. Files touched

| 文件 | 改动 |
|---|---|
| `stock_data/explorer/static/index.html` | `GraphView` 新增分区坐标计算 `layoutSections()` + 展开状态机; 图内工具条 DOM/CSS; 主 app `state.graphLayout` + 工具条 bind + `renderGraph` 传布局; 顶部/工具条样式 |

后端零改动。

## 6. Edge cases / Error handling

- 某个 section 只有一个端点 / 空 section: 区块照常渲染(小标题 + 单节点);
  `manifest.sections` 不含端点的 section 不生成空区块。
- CDN 失败: 维持现状降级提示(分区布局也要 vis, 无额外降级)。
- 切换布局时保留当前搜索词/market 过滤 → 渲染后重放 `applyFilter` +
  `applySearch`。
- 展开态在以下情况自动收回: 切布局、切视图(离开 graph)、主题重建。
- 端点隐藏(被 filter)时若有展开边 → 一并移除, 避免悬空线。

## 7. Testing(无自动化 FE 测试)

手动 smoke, 需起 server(`SERVER_PORT` 非 8888, 防误杀):
1. 默认进图 → 分区布局: 区块标题清晰、46 端点全在、无 served-by 线、
   composed-of 紫虚线在(抽查 market-context)。
2. 点某普通端点 → 仅它的 fetcher 连线出现、fetcher 点亮、右侧详情含链。
3. 再点/点空白 → 收回。
4. 切 `力导向` → 原状(全边+物理); 切回 `分区` → 布局恢复且过滤保留。
5. 搜索 `kline` 暗化 / 勾掉 hk 过滤 / 🌗 切主题重建 → 均无报错。
6. reload 后布局选择持久化; 切回 Endpoints 视图再回来无残留。

## 8. Out of scope (explicit)

- 树方向、严格树、两桶根、capability 主轴 —— 讨论中已否。
- fetcher 区可拖动重排、保存用户自定义坐标 —— YAGNI。
