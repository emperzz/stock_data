# Explorer 图视图: 按 section 分区布局 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `/explorer/` Dependency Graph 默认改为"按 section 分区"布局: 端点各归其 section 区块、fetcher 集中在底部数据源条、composed-of 边恒显、served-by 边默认隐藏、单击端点才展开其 fetcher 链; 原力导向保留为图内备选模式。

**Architecture:** 全部改动在 `stock_data/explorer/static/index.html`(无后端)。`GraphView` 扩展 `render()` 支持 `layout: "section" | "force"`: section 模式手工计算节点固定坐标(`physics:false`), 渲染时剔除 served-by 边, 展开/收起由 `expandedEp` 状态机 + `allServedBy` 存储驱动。主 app 增加 `state.graphLayout`(localStorage 持久)与图内工具条, `renderGraph` 把布局传给 GraphView。filter/search/theme/NodeDetailPanel 复用现有实现(两种模式操作同一批 DataSet 节点)。

**Tech Stack:** Python 3.13 + FastAPI(仅跑 server 供 smoke);vanilla JS + vis-network 9.x UMD via CDN(前端单 HTML)。

**Spec:** `docs/superpowers/specs/2026-09-02-explorer-section-partition-graph-design.md`。

## Global Constraints

- **文件**: 只有 `stock_data/explorer/static/index.html` 会被改。后端零改动。
- **Python 解释器**: `.venv/Scripts/python.exe`(不存在则用系统 `python`); 本机当前无 `.venv`, 用系统 python 起 server。
- **测试**: 前端无自动化测试框架 —— 用 `node --check` 语法校验每个 `<script>` 块 + 起 server 浏览器手动 smoke(见每 task 的 Smoke 步)。不引入 FE 测试框架(YAGNI)。
- **server 端口**: 勿用 8888(可能被用户服务占用), 用 `SERVER_PORT=8891` 起; 用完停掉(查 `netstat -ano | grep :8891` 拿 pid 后 `Stop-Process`), 不要 `taskkill //F` 未知 pid。
- **装饰器 / manifest 顺序等后端约束**: 不涉及(不改后端)。
- **既有契约不破坏**: `NodeDetailPanel`、`GraphView` 公共 API(`load/render/applyFilter/applySearch/destroy`)签名不变——`render` 只新增可选 `opts.layout`(缺省 `"force"` 保持现状)。
- **CSS 变量**: 只读现有一组 `--text/--text-muted/--accent/--accent-warn/--border/--bg-card`(均已存在), 不新增主题变量。
- **分支**: 继续在 `feat/explorer-dependency-graph` 分支; 每个 task 完成后 commit(前端功能代码走该分支, 与既有 Task 4–6 一致)。

---

### Task 1: GraphView 支持 `layout:"section"` 分区渲染(增量, 默认仍 force)

在 `GraphView` IIFE 内新增坐标/展开基建, 并把 `render()` 改为按 `opts.layout` 分支。app 尚未传 `layout`(Task 2 接), 故本 task 结束后页面行为与现在一致(force), 无回归。

**Files:**
- Modify: `stock_data/explorer/static/index.html`(`GraphView` IIFE:`768` 行起, 位于 `const GraphView = (() => {` 与其后的 `})();` 之间)

**Interfaces:**
- Consumes: `buildGraph()` 现有产出 `{nodes, edges}`(nodes 有 `id/group/_ep/_name/label`, edges 有 `_kind` ∈ `"served-by"|"composed-of"`、`from/to/id`); `cssVar()`。
- Produces: `GraphView.render(container, manifest, {onNodeClick?, layout?})` —— `layout` ∈ `"force"|"section"`(缺省 `"force"`);section 时节点带固定 `x/y`、`physics:false`、served-by 边不进入 DataSet、暴露展开状态机。Task 2 依赖 `layout` 参数与"served-by 默认不可见"这一约定。

- [ ] **Step 1: 加模块级状态 + 工具常量**

在 `let visLoadPromise = null;`(`:774`)之后追加:

```javascript
    let lastLayout = "force";   // "force" | "section"
    let expandedEp = null;      // 当前展开的 endpoint 节点 id ("ep:<path>"), section 模式用
    let allServedBy = [];       // 全部 served-by 边(进 DataSet 前备份, section 模式展开用)
```

- [ ] **Step 2: 加坐标布局与标签 helper**

在 `fuzzyMatchGlobal` 函数(`:799-806`, `function fuzzyMatchGlobal(...) {...}` 整块)之后、`buildGraph` 之前插入:

```javascript
    // 分区模式短标签: 去掉 /api/v1 前缀, 截到 26 字符。
    function shortGraphLabel(ep) {
      const p = (ep.path || "").replace(/^\/api\/v1/, "");
      const s = `${ep.method} ${p}`;
      return s.length > 26 ? s.slice(0, 25) + "…" : s;
    }

    // 按 section 手工摆点(关 physics)。端点 → 每 section 一列; fetcher → 底部一行。
    // 返回 {w,h} 供容器扩容。行/列间距是近似值(非等宽字体), 允许个别节点轻微重叠。
    function layoutSection(nodes) {
      const epNodes = nodes.filter(n => n.group === "endpoint");
      const fxNodes = nodes.filter(n => n.group === "fetcher");
      // path -> sectionId(manifest 顺序稳定)
      const p2s = {};
      for (const sec of lastManifest.sections)
        for (const ep of sec.endpoints) p2s[ep.path] = sec.id;
      const cols = new Map();
      for (const n of epNodes) {
        const sid = p2s[n._ep.path] || "?";
        if (!cols.has(sid)) cols.set(sid, []);
        cols.get(sid).push(n);
      }
      const X_PAD = 24, Y_PAD = 24, ROW_H = 34, TITLE_H = 40;
      let x = X_PAD, maxY = Y_PAD;
      for (const [sid, list] of cols) {
        let colW = TITLE_H; // 标题宽度下限
        for (const n of list) colW = Math.max(colW, n.label.length * 8.6 + 28);
        let y = Y_PAD + TITLE_H;
        for (const n of list) { n.x = x; n.y = y; y += ROW_H; }
        maxY = Math.max(maxY, y);
        x += colW + 18;
      }
      // fetcher 底部条
      const fxY = maxY + 90;
      let fxW = 0;
      for (const n of fxNodes) fxW = Math.max(fxW, n.label.length * 9 + 30);
      let fxX = X_PAD;
      for (const n of fxNodes) { n.x = fxX; n.y = fxY; fxX += fxW; }
      return { w: Math.max(x, fxX) + 30, h: fxY + 44 };
    }
```

- [ ] **Step 3: 加 fetcher 点亮/复原 + 展开状态机 helper**

接 Step 2 helper 之后(仍在 `buildGraph` 之前)插入:

```javascript
    function fetcherColor(active) {
      if (active) return { background: "#fff4e0", border: cssVar("--accent-warn", "#ff9500") };
      return { background: "#f5f5f7", border: cssVar("--border", "#e5e5ea") };
    }

    // 给一组 serviced fetcher 点亮, 其余置灰。
    function focusFetchers(fromEpId) {
      if (!dataSet) return;
      const act = new Set(
        allServedBy.filter(e => e.from === fromEpId).map(e => e.to)
      );
      const ups = dataSet.nodes.get()
        .filter(n => n.group === "fetcher")
        .map(n => ({ id: n.id, color: fetcherColor(act.has(n.id)) }));
      dataSet.nodes.update(ups);
    }

    function collapseExpansion() {
      if (!dataSet || !expandedEp) return;
      const toDrop = allServedBy.filter(e => e.from === expandedEp).map(e => e.id);
      dataSet.edges.remove(toDrop);
      expandedEp = null;
      focusFetchers(null);       // 全部 fetcher 复原置灰
      network && network.redraw();
    }

    // 单击切换: 已展开同端点 → 收起; 否则先收旧再展新。
    function toggleExpansion(epNodeId) {
      if (!dataSet) return;
      if (expandedEp === epNodeId) { collapseExpansion(); return; }
      collapseExpansion();
      expandedEp = epNodeId;
      dataSet.edges.add(allServedBy.filter(e => e.from === epNodeId));
      focusFetchers(epNodeId);
      network && network.redraw();
    }
```

- [ ] **Step 4: 重写 `render()` 使其按 `layout` 分支**

用以下内容**整体替换**现有 `render` 函数(从 `function render(container, manifest, callbacks) {` 到其闭合 `}` 的整块, 现约在 `:930` 附近):

```javascript
    function render(container, manifest, callbacks) {
      lastManifest = manifest;
      lastCallbacks = callbacks || {};
      lastLayout = (callbacks && callbacks.layout) || "force";
      if (!window.vis || !window.vis.Network) {
        container.innerHTML =
          '<div class="result-empty"><span class="arrow">⚠</span>' +
          '图库 (vis-network) 加载失败 — 请检查网络，或把库 vendor 到 ' +
          '<code>explorer/static/vendor/</code> 并改 GraphView 的 VIS_CDN。</div>';
        return;
      }
      const isSection = lastLayout === "section";
      const graph = buildGraph(manifest);          // nodes + 全部边(两种 _kind)
      const nodes = graph.nodes;
      allServedBy = graph.edges.filter(e => e._kind === "served-by");
      let edges = isSection
        ? graph.edges.filter(e => e._kind !== "served-by")  // served-by 默认不画
        : graph.edges;

      if (isSection) {
        // 端点换短标签(force 模式保持原长标签)
        nodes.filter(n => n.group === "endpoint").forEach(n => {
          n._fullLabel = n.label;
          n.label = shortGraphLabel(n._ep);
          n.title = `${n._ep.method} ${n._ep.path}\n${n._ep.summary || ""}`;
        });
        const extent = layoutSection(nodes);        // 赋 x/y
        nodes.forEach(n => { n.fixed = { x: true, y: true }; });
        // 容器按内容尺寸扩容(外层 #graphWrap 滚动)
        container.style.cssText =
          `width:${extent.w}px;height:${extent.h}px;min-width:640px;`;
      } else {
        container.style.cssText =
          "width:100%;height:100%;min-width:640px;";
      }

      dataSet = {
        nodes: new window.vis.DataSet(nodes),
        edges: new window.vis.DataSet(edges),
      };
      const options = {
        nodes: { font: { color: cssVar("--text", "#1d1d1f"), size: 13 } },
        edges: { smooth: { type: "continuous", roundness: 0.5 } },
        physics: isSection
          ? false
          : {
              stabilization: { iterations: 120, fit: true },
              barnesHut: { gravitationalConstant: -8000, springLength: 140, springConstant: 0.04 },
            },
        interaction: { hover: true, tooltipDelay: 120, navigationButtons: false, zoomView: true, dragView: true },
      };
      network = new window.vis.Network(container, dataSet, options);
      expandedEp = null;

      network.on("click", (params) => {
        if (isSection && (!params.nodes || params.nodes.length === 0)) {
          collapseExpansion();   // 点空白收回
          return;
        }
        if (params.nodes && params.nodes.length) {
          const node = dataSet.nodes.get(params.nodes[0]);
          if (node && isSection && node.group === "endpoint") {
            toggleExpansion(node.id);
          }
          if (node && lastCallbacks.onNodeClick) lastCallbacks.onNodeClick(node);
        }
      });
      if (isSection) network.fit({ animation: false });
    }
```

- [ ] **Step 5: 让 `applyFilter` 在 section 模式下过滤掉已展开端点时自动收起**

在 `applyFilter(state)` 函数内、`network.redraw();`(结尾)之前插入:

```javascript
      // 分区模式: 若当前展开的端点被过滤隐藏, 收起其边, 避免悬空线。
      if (lastLayout === "section" && expandedEp) {
        const hiddenEps = new Set(updates.filter(u => u.hidden).map(u => u.id));
        if (hiddenEps.has(expandedEp)) collapseExpansion();
      }
```

(`applyFilter` 中已有的 `updates` 变量即隐藏集, 无需新定义。)

- [ ] **Step 6: 语法校验**

```bash
node -e 'const fs=require("fs");const s=fs.readFileSync("stock_data/explorer/static/index.html","utf8");const re=/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/gi;let m,i=0,e=0;while((m=re.exec(s))){i++;try{new Function(m[1]);}catch(x){e++;console.log("script #"+i+" ERR: "+x.message);}}console.log("scripts:",i,"errors:",e);'
```

Expected: `scripts: 5 errors: 0`。

- [ ] **Step 7: force 模式无回归 smoke + commit**

起 server 并确认页面无新报错、图可渲染(force 是缺省, 行为应和 commit 前一致):

```bash
SERVER_PORT=8891 python -m stock_data.server > /tmp/srv_part.log 2>&1 &
sleep 7 && curl -s http://127.0.0.1:8891/control/api-manifest -o /dev/null -w "manifest http %{http_code}\n"
```

浏览器开 `http://127.0.0.1:8891/explorer/` → 切 Dependency Graph → DevTools console 无 `Error`(favicon 404 忽略)。确认 canvas 出现(与之前一致)。

```bash
git add stock_data/explorer/static/index.html
git commit -m "feat(explorer): GraphView supports section-partition layout (opt-in)

render() now branches on opts.layout (force default, unchanged). Section
mode hand-places endpoints per-section columns + fetcher bottom strip,
physics off, served-by edges hidden with a click-to-expand state machine.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

停掉临时 server(保留供 Task 2 smoke 复用可先不停)。

---

### Task 2: 图内工具条 + 默认分区 + 布局切换接线

主 app 集成: `state.graphLayout`(默认 `"section"`, localStorage),图视图内容区顶部加 `分区/力导向` 工具条,`renderGraph` 把 `layout` 传给 `GraphView.render`;切换即重建图并重放 filter/search。

**Files:**
- Modify: `stock_data/explorer/static/index.html`(主 app IIFE: `state` `:1027`、`applyView`、`renderGraph`、`bindUI`;CSS `.graph-toolbar` 加在 `.segmented` 规则附近)

**Interfaces:**
- Consumes: Task 1 的 `GraphView.render(..., {layout})`。
- Produces: `state.graphLayout: "section"|"force"`(default `"section"`,persist key `graphLayout`);`renderGraph(container)` 传 `layout: state.graphLayout`。Task 3 依赖"默认分区"这一状态、以及每次重建后 `GraphView.applyFilter/applySearch` 的重放。

- [ ] **Step 1: CSS 加 `.graph-toolbar`**

在 `index.html` `<style>` 中 `.segmented .seg.active {...}` 规则(`:12-324` 之间)之后插入:

```css
    .graph-toolbar { display: flex; align-items: center; gap: 12px; margin: 0 0 10px; flex-wrap: wrap; }
    .graph-toolbar .graph-toolbar-hint { font-size: 12px; color: var(--text-muted); }
```

- [ ] **Step 2: `state` 加 `graphLayout`**

在 `state` 对象(`:1027`)的 `view: safeGetItem("view", "endpoints"),` 之后插入:

```javascript
      graphLayout: safeGetItem("graphLayout", "section"),
```

- [ ] **Step 3: 加 `setGraphLayout` + 改 `renderGraph`**

在 `renderGraph` 函数(现约在 `applyView` 之后)内/旁: 先整体替换 `renderGraph`, 再在其后追加 `setGraphLayout`:

```javascript
    async function renderGraph(container) {
      await GraphView.load();
      GraphView.render(container, MANIFEST, {
        layout: state.graphLayout,
        onNodeClick: (n) => {
          if (n.group === "endpoint") NodeDetailPanel.showEndpoint(n._ep, MANIFEST);
          else if (n.group === "fetcher") NodeDetailPanel.showFetcher(n._name, MANIFEST);
        },
      });
      GraphView.applyFilter(state);
      GraphView.applySearch($("#search").value);
    }

    function setGraphLayout(v) {
      if (state.graphLayout === v) return;
      state.graphLayout = v;
      safeSetItem("graphLayout", v);
      $$("#graphLayoutSwitch .seg").forEach(b =>
        b.classList.toggle("active", b.dataset.layout === state.graphLayout));
      const canvas = $("#graphCanvas");
      if (!canvas) return;
      GraphView.destroy();
      renderGraph(canvas);
    }
```

- [ ] **Step 4: 改 `applyView` 的 graph 分支(建工具条 + 滚动容器)**

用以下内容替换 `applyView` 中 graph 分支(`if (isGraph) {...}` 整块):

```javascript
      if (isGraph) {
        content.innerHTML = "";
        // 布局工具条
        const bar = el("div", { className: "graph-toolbar" });
        const seg = el("div", {
          id: "graphLayoutSwitch", className: "segmented", role: "group",
          "aria-label": "Graph layout",
        });
        seg.appendChild(el("button", {
          type: "button", className: "seg" + (state.graphLayout === "section" ? " active" : ""),
          dataset: { layout: "section" }, textContent: "分区",
        }));
        seg.appendChild(el("button", {
          type: "button", className: "seg" + (state.graphLayout === "force" ? " active" : ""),
          dataset: { layout: "force" }, textContent: "力导向",
        }));
        seg.onclick = (e) => {
          const b = e.target.closest(".seg");
          if (b) setGraphLayout(b.dataset.layout);
        };
        bar.appendChild(seg);
        bar.appendChild(el("span", {
          className: "graph-toolbar-hint",
          textContent: state.graphLayout === "section"
            ? "端点按 section 归区; 点端点展开它的 fetcher; 点空白收回"
            : "力导向全局图(served-by 实线 + composed-of 虚线)",
        }));
        content.appendChild(bar);

        // 滚动容器(graphCanvas 会被 render 按内容扩容)
        const wrap = el("div", {
          id: "graphWrap",
          style: "width:100%;height:calc(100vh - 220px);overflow:auto;border:1px solid var(--border);border-radius:8px;background:var(--bg-card);",
        });
        const g = el("div", {
          id: "graphCanvas",
          style: "width:100%;height:100%;min-width:640px;",
        });
        wrap.appendChild(g);
        content.appendChild(wrap);
        NodeDetailPanel.clear();
        renderGraph(g);
      } else {
        renderContent();
        // 切回 endpoint 视图: 复位面板(可能残留 NodeDetailPanel 内容)
        ResultPanel.clear();
      }
      $(".result-panel-header span").textContent = isGraph ? "Node Detail" : "Response";
```

> 说明: 这段替换里 `else` 分支与 `$(".result-panel-header ...")` 与现有一致, 只改 graph 分支; 若你现文件该分支已含 `ResultPanel.clear()`(Task 6 加的), 以现文件 else 分支为准、仅替换 graph 分支块即可。

- [ ] **Step 5: theme toggle 分支兼容新容器**

`bindUI` 的 `themeToggle.onclick` 中图重建逻辑(`if (state.view === "graph") { const g = $("#graphCanvas"); if (g) { GraphView.destroy(); applyView(); } }`)保持不变 —— 但删除其里可能残留的 `$("#graphCanvas")` 尺寸假设(它只 destroy + applyView, 无需改)。确认该分支就是 `applyView()` 重建即可。

- [ ] **Step 6: 语法 + smoke**

```bash
node -e '...同 Task 1 Step 6...'   # 期望 5 scripts, 0 errors
```

浏览器(用 Task 1 起的 server, 若已停则重起): 默认切到 Dependency Graph 应直接显示**分区布局**(区块标题 + 各列端点 + 底部 fetcher 条、composed-of 紫虚线), 无 served-by 线。点 `力导向` → 恢复原物理图(有 served-by 实线); 再点 `分区` → 布局恢复且先前的 search/market 过滤仍在。

- [ ] **Step 7: commit**

```bash
git add stock_data/explorer/static/index.html
git commit -m "feat(explorer): section/force layout toggle in graph view (default section)

Add state.graphLayout (persisted) + in-canvas toolbar. renderGraph passes
layout to GraphView; toggling rebuilds and replays filter/search.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: 展开交互收尾(点空白收回 / fetcher 点亮 / 清理)

验证并打磨 Task 1 埋好的展开状态机在真实 UI 下的表现;必要时补一点视觉细节(agent 端点的 `⇢N` 计数标注在分区标签),并确认切视图/主题/布局/过滤后无残留展开态。

**Files:**
- Modify: `stock_data/explorer/static/index.html`(仅当 smoke 暴露问题才改 `GraphView` 展开相关 / `renderGraph`;否则本 task 以 smoke + 微调为主)

**Interfaces:**
- Consumes: Task 1 的 `toggleExpansion/collapseExpansion/focusFetchers`;Task 2 默认 section。
- Produces: 无新公共 API。行为契约: 分区模式下单击端点=展开其 served-by 边+点亮对应 fetcher+右侧详情;再点同端点或点空白=收回;离开图/切布局/主题重建/端点被过滤隐藏=自动收回。

- [ ] **Step 1: smoke 展开/收回(主验证步)**

浏览器(server 8891): 默认(分区)视图。
1. 点任意有 fetchers 的端点(如 `GET stocks/{code}/kline`)→ 该端点下方/指向底部 fetcher 出现若干条 served-by 边, 对应 fetcher(如 Tushare/Baostock…)被点亮(橙边框), 其余 fetcher 灰;右侧 NodeDetailPanel 显示该端点详情。
2. 再点同端点 → 边消失、fetcher 复原置灰。
3. 点别的端点 → 旧边收起、新端点边展开。
4. 点空白画布 → 边收回。
5. 展开状态下切 `力导向` 再切回 → 无残留展开(重新 render 即重置)。
6. 展开状态下点 🌗 切主题 → 无残留、图正常重建。
7. 展开一个端点后, 把它的 section 过滤掉(如取消勾选 csi 隐藏大量 stocks 端点) → 无悬空线、无报错。

Expected: 1–7 全通过, DevTools console 无 `Error`(favicon 404 忽略)。

- [ ] **Step 2: (可选打磨) 分区标签给 agent 端点加依赖计数**

若 Step 1 观察中希望 agent 节点一眼看出"有 N 条内部依赖",在 `shortGraphLabel` 内、返回前对空 capabilities 的端点拼接 ` ⇢{n}`:`(依赖数取 `ep.depends_on` 中 `kind==="endpoint"` 的数量)。是否做由 smoke 观感决定;做则改:

```javascript
    function shortGraphLabel(ep) {
      const p = (ep.path || "").replace(/^\/api\/v1/, "");
      let s = `${ep.method} ${p}`;
      if (ep.capabilities && ep.capabilities.length === 0 && ep.depends_on) {
        const n = ep.depends_on.filter(d => d.kind === "endpoint").length;
        if (n > 0) s += ` ⇢${n}`;
      }
      return s.length > 30 ? s.slice(0, 29) + "…" : s;
    }
```

(替换 Task 1 Step 2 里那个版本。)

- [ ] **Step 3: 语法 + 回归 smoke**

```bash
node -e '...同前...'   # 期望 0 errors
```

重跑 Step 1 的 2/4/7 三条快速回归。

- [ ] **Step 4: commit**

```bash
git add stock_data/explorer/static/index.html
git commit -m "feat(explorer): click-to-expand fetcher links in partition mode

Single click an endpoint reveals its served-by edges and highlights the
serving fetchers (others dim); click again / blank canvas collapses.
Cleanup on layout/theme switch and filter-hide.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: 收尾 smoke + 停 server

- [ ] **Step 1: 完整回归清单**

按 spec §7 跑一遍(分区默认、展开/收回、力导向切换、search 暗化、market/fetcher 过滤、🌗 主题、reload 布局持久化、切回 Endpoints 再回来无残留)。全部通过后 git status 应干净。

- [ ] **Step 2: 停临时 server + 确认干净**

```bash
PID=$(netstat -ano | grep -E ':8891\b' | grep LISTENING | head -1 | awk '{print $NF}')
[ -n "$PID" ] && powershell -NoProfile -Command "Stop-Process -Id $PID -Force -ErrorAction SilentlyContinue"
git status --short
git log --oneline -8
```

---

## Self-Review

1. **Spec coverage**: §4.1 布局切换 → Task 2;§4.2 分区渲染(区块列 + fetcher 条 + 46 端点全在)→ Task 1 `layoutSection`;§4.3 composed-of 恒显 / served-by 默认隐藏 / force 全边 → Task 1 `render` 分支;§4.4 点击展开 + 点亮/置灰 + 点空白收回 + 详情 → Task 1 helpers + Task 3;§4.5 filter/search/theme 复用 → Task 2 `renderGraph` 重放 + `applyFilter` 收起守卫 + 既有 handler;§4.6 共享节点 id/DataSet → Task 1 结构;§5 只改 index.html → 是;§6 展开态清理 → Task 1 `applyFilter` 守卫 + Task 3 smoke;§7 手动 smoke → Task 2/3/4。无缺口。
2. **Placeholder scan**: 无 TBD/TODO;Task 3 Step 2 的"可选打磨"有完整代码 + 明确触发条件, 不是空壳。
3. **Type/名一致性**: `layout:"section"|"force"`、`state.graphLayout`、`#graphLayoutSwitch`、`#graphWrap/#graphCanvas`、`shortGraphLabel/layoutSection/toggleExpansion/collapseExpansion/focusFetchers/allServedBy/expandedEp` 全程一致;`GraphView.render(container, manifest, {layout, onNodeClick})` 在 Task 1 定义、Task 2 调用一致;`applyFilter` 里 `updates` 为既有变量, Task 1 Step 5 只读它。

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-09-02-explorer-section-partition-graph.md`. 两个执行选项:

**1. Subagent-Driven (recommended)** — 每 task 派一个子 agent, task 间我做 review。

**2. Inline Execution** — 本会话用 executing-plans 按 task 批量执行 + 检查点。

选哪种?
