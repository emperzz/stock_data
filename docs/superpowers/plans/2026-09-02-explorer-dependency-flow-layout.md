# Explorer 图视图: 三层依赖流水布局 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `/explorer/` Dependency Graph 默认布局从"按 section 竖列分区"改为**三层依赖流水**:agent(9) → 按 section 分组的带标题业务端点框(46) → fetcher(13);served-by 边默认可见、composed-of 为主干;hover/单击节点聚焦其邻边、其余淡化;依赖流支持 **竖排(TB, 默认)/横排(LR)** 两种方向。原力导向保留为逃生口。

**Architecture:** 全部改动在 `stock_data/explorer/static/index.html`(无后端)。GraphView 用新的 `layoutFlow(nodes, dir)`(固定坐标三 rank + 质心锚定,`dir="TB"` 竖排 / `"LR"` 横排把 agent、fetcher 移到左/右列)替换旧 `layoutSection()` 与"点端点展开 served-by"状态机;served-by 边从"默认剔除/点击展开"改为**常驻 DataSet**,`beforeDrawing` 用 canvas 画 section 分组框;新增 `paint()`(searchDim × focus 重算节点/边透明度)。主 app 把 `graphLayout` 值域从 `"section"|"force"` 换成 `"flow"|"force"`(旧 `"section"` 归一为 `"flow"`),工具条改为 依赖流/力导向 + **竖排/横排**(`state.graphDir`, 力导向下禁用)。

**Tech Stack:** Python 3.13 + FastAPI(仅跑 server 供 smoke);vanilla JS + vis-network@9 UMD via CDN(前端单 HTML)。

**Spec:** `docs/superpowers/specs/2026-09-02-explorer-dependency-flow-layout-design.md`。

## Global Constraints

- **文件**: 只有 `stock_data/explorer/static/index.html` 会被改。后端零改动。
- **Python 解释器**: `.venv/Scripts/python.exe`(不存在则用系统 `python`)。
- **测试**: 前端无自动化测试框架 —— 每步用 `node --check`(下述语法校验命令)校验所有 `<script>` 块 + 起 server 浏览器手动 smoke。不引入 FE 测试框架。
- **server 端口**: 勿用 8888(可能被用户服务占用),用 `SERVER_PORT=8891` 起;用完查 `netstat -ano | grep :8891` 拿 pid 后 `powershell -NoProfile -Command "Stop-Process -Id <pid> -Force"` 停,不 `taskkill //F` 未知 pid。
- **GraphView 公共 API 不变**: `load/render/applyFilter/applySearch/destroy` 签名不动;`render` 只新增可选 `opts.layout`(`"force"` 或依赖流字面值)。
- **CSS 变量**: 只读现有一组 `--text/--text-muted/--accent/--accent-post/--accent-warn/--border/--bg-card/--bg-sidebar`,不新增主题变量。
- **分支**: 本轮 spec/plan 已 commit master(md 走 master)。index.html 是 Python 服务端之外的文件 —— 沿用先前图功能做法,新建 `feat/explorer-dependency-flow` 分支执行,每 task 完成后 commit。
- **已验证的 vis-network@9 事实**(探针实测,勿改实现假设):
  1. `network.on("beforeDrawing", ctx => …)` 会触发,且 `ctx` 已带视图变换(世界坐标)→ 可在其中用**节点坐标**直接画分组框。
  2. 节点设 `hidden:true` 后,**它相连的边自动不画**(无需手动删边)。
  3. 节点固定坐标 + `physics:false` 时,canvas 容器设成内容 px 后 `network.fit()` 将整体纳入视口。

## 语法校验命令(每步用,期望 `scripts: 5 errors: 0`)

```bash
node -e 'const fs=require("fs");const s=fs.readFileSync("stock_data/explorer/static/index.html","utf8");const re=/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/gi;let m,i=0,e=0;while((m=re.exec(s))){i++;try{new Function(m[1]);}catch(x){e++;console.log("script #"+i+" ERR: "+x.message);}}console.log("scripts:",i,"errors:",e);'
```

## 现有代码定位(当前文件,`stock_data/explorer/static/index.html`)

- `GraphView` IIFE:`const GraphView = (() => {`(:779)…`})();`(:1145)。内部顺序:
  - 模块变量 `let network … let allServedBy = [];`(:781-788)
  - `load/cssVar/fuzzyMatchGlobal/shortGraphLabel`(:790-830)
  - `layoutSection`(:834-864)、`fetcherColor`(:866-869)、`focusFetchers`(:871-881)、`collapseExpansion`(:883-890)、`toggleExpansion`(:892-901)
  - `buildGraph`(:913-1017)
  - `render`(:1019-1091)
  - `applyFilter`(:1095-1126)、`applySearch`(:1129-1137)、`destroy`(:1139-1142)、`return {…}`(:1144)
- 主 app IIFE:`let state`(:1391, 含 `graphLayout: safeGetItem("graphLayout", "section")` 于 :1395);`applyView` graph 分支(:1518-1559,含 `#graphLayoutSwitch` 两段 分区/力导向 :1526-1533 与 hint :1539-1544);`renderGraph`(:1569-1580);`setGraphLayout`(:1582-1592)。
- `shortGraphLabel`(:822-830)与 `buildGraph`(:913-1017)**保留不改**。

> 行号仅供定位;编辑一律按"函数名 + 独特注释"锚定,不要依赖行号数值(后续步骤会漂移)。

---

### Task 1: GraphView 改为依赖流布局(旧"section"渲染新三层;force 原样)

把 `render` 对 `layout:"section"` 的渲染从"竖列分区 + served-by 默认隐藏 + 点端点展开"整体替换为**三层依赖流 + 全边可见 + canvas 分组框**。app 此刻仍发 `"section"`,故页面默认即显示新布局(force 按钮不受影响)。本 task 结束时 `layout:"section"` 行为 = 新三层(后续 Task 2 只是把它改名为 `"flow"`)。

**Files:** Modify: `stock_data/explorer/static/index.html`(`GraphView` IIFE 内部)

**Interfaces:**
- Consumes: `buildGraph()` 现有产出(节点有 `id/group/shape/color/label/_ep`;边有 `_kind ∈ "served-by"|"composed-of"`、`from/to/id/width/color/{color,opacity}`);`shortGraphLabel(ep)`;`cssVar(name,fallback)`;`lastManifest`。
- Produces: 模块级 `lastLayout/isFlowLayout()/focusedId=null/pinnedFocus=false/searchDim={}/flowBoxes=[]/allServedBy/baseEdges/baseNode`;`layoutFlow(nodes, dir)->{w,h}`,`dir ∈ "TB"|"LR"`(赋节点 `x/y`,填 `flowBoxes`,追加 2 个 `group:"anchor"` 不可见节点);canvas `beforeDrawing` 画分组框;`render` 中 `"section"`(≈flow)路径 = 三层坐标 + 全边 + physics off + fit,读 `callbacks.dir` 缺省 `"TB"`;force 路径原样。Task 2b 依赖 `render(...,{dir})` 与 `layoutFlow(nodes,dir)` 的 LR 分支。
- 依赖后续: Task 2 依赖 `isFlowLayout()` 同时匹配 `"flow"`,Task 3 依赖 `focusedId/pinnedFocus/searchDim/baseEdges/baseNode/paint()`。

- [ ] **Step 1: 替换模块变量(:786-788)与新布局判断**

把 GraphView 内这三行模块变量:

```javascript
    let lastLayout = "force";   // "force" | "section"
    let expandedEp = null;      // section 模式下当前展开的 endpoint 节点 id ("ep:<path>")
    let allServedBy = [];       // 全部 served-by 边(进 DataSet 前备份, section 模式展开用)
```

替换为:

```javascript
    let lastLayout = "force";   // "force" | "section"(旧别名) | "flow"(Task 2 起)
    let focusedId = null;       // 依赖流: 当前聚焦节点 id (null=无)
    let pinnedFocus = false;    // 聚焦是否被 click 钉住(hover 不钉)
    let searchDim = {};         // node id -> 命中?未命中:0.15(applySearch 写入)
    let flowBoxes = [];         // [{sid,x,y,w,h}] section 分组框几何(beforeDrawing 画)
    let allServedBy = [];       // 全部 served-by 边(applyFilter 派生 fetcher 可见性)
    let baseEdges = [];         // 边样式快照 {id,from,to,width,color:{color,opacity}}
    let baseNode = {};          // node id -> {color} 样式快照(聚焦/复原用)

    // "flow" 与其旧字面 "section"(Task 2 改名前的占位)都算依赖流布局。
    function isFlowLayout(l) { return l === "flow" || l === "section"; }
```

- [ ] **Step 2: 删除旧竖列/展开 helpers,加依赖流布局与分组框绘制**

删除旧函数整块 —— 从 `layoutSection` 函数开头(`    // 按 section 手工摆点(关 physics)。…` 注释起)到 `toggleExpansion` 函数闭合 `}` 止(含 `fetcherColor`/`focusFetchers`/`collapseExpansion`),即当前 :832-901 整段。用下列代码替换:

```javascript
    // 依赖流布局: 3 个横排 rank —— agent(上)→ section 分组框(中)→ fetcher(下)。
    // 端点固定坐标、physics off。agent/fetcher 按其目标/来源端点的 x 质心定位,
    // 冲突向右推避免重叠, 使 served-by/composed-of 边尽量成为短下垂线。
    function floatRow(list, desiredOf, y, widthOf, clampMin, clampMax, minGap) {
      const arr = [...list].sort((a, b) => desiredOf(a) - desiredOf(b));
      let cursor = clampMin;
      for (const n of arr) {
        const want = Math.max(clampMin, Math.min(desiredOf(n), clampMax));
        n.x = Math.max(want, cursor);
        n.y = y;
        cursor = n.x + widthOf(n) + minGap;
      }
    }

    // 垂直摊开(横排 LR 用): 固定 x, 依 desiredOf(沿 y)排序并避免重叠。
    function floatCol(list, desiredOf, x, minV, maxV, gap) {
      const arr = [...list].sort((a, b) => desiredOf(a) - desiredOf(b));
      let cursor = minV;
      for (const n of arr) {
        const want = Math.max(minV, Math.min(desiredOf(n), maxV));
        n.x = x;
        n.y = Math.max(want, cursor);
        cursor = n.y + 34 + gap;
      }
    }

    // 返回 {w,h};给每个 node 赋 x/y;填充 flowBoxes;在 nodes 尾部追加不可见 anchor。
    // dir = "TB"(竖排, 默认) | "LR"(横排: agent 左列 / fetcher 右列, 框仍是中部竖列)。
    function layoutFlow(nodes, dir) {
      const p2s = {};
      for (const sec of lastManifest.sections)
        for (const ep of sec.endpoints) p2s[ep.path] = sec.id;

      const epNodes = nodes.filter(n => n.group === "endpoint");
      const fxNodes = nodes.filter(n => n.group === "fetcher");
      const epById = {};
      for (const n of epNodes) epById[n.id] = n;

      const agents = [];
      const cols = new Map();                    // sectionId -> endpoint node[]
      for (const n of epNodes) {
        const sid = p2s[n._ep.path] || "?";
        if (sid === "agent") agents.push(n);
        else { if (!cols.has(sid)) cols.set(sid, []); cols.get(sid).push(n); }
      }

      const PAD = 56, ROW = 32, HEAD = 30, BOX_GAP = 46, ROW_W = 7.4;
      const isTB = dir !== "LR";
      const rowTop = isTB ? PAD + 160 : PAD + 36;   // TB 顶部给 agent 行留走廊

      // R1: section 分组框(框内端点竖排左对齐; 两种方向共用同一几何)。
      flowBoxes = [];
      let x = PAD;
      for (const [sid, list] of cols) {
        let w = 50;
        for (const n of list) w = Math.max(w, Math.ceil(n.label.length) * ROW_W);
        const by = rowTop;
        const h = HEAD + list.length * ROW + 26;
        flowBoxes.push({ sid, x, y: by, w, h, eps: list });
        list.forEach((n, i) => { n.x = x + 24; n.y = by + HEAD + ROW / 2 + i * ROW; });
        x += w + BOX_GAP;
      }
      const boxRight = Math.max(PAD, x - BOX_GAP);
      const maxBoxBottom = flowBoxes.length
        ? Math.max(...flowBoxes.map(b => b.y + b.h)) : rowTop + HEAD;

      const tgtOf = n => (n._ep.depends_on || [])
        .filter(d => d.kind === "endpoint")
        .map(d => epById["ep:" + d.target_path])
        .filter(Boolean);
      const srcOf = n => allServedBy.filter(e => e.to === n.id).map(e => epById[e.from]).filter(Boolean);
      const mean = a => a.reduce((s, t) => s + t, 0) / a.length;
      const anchorOf = (cw, ch) => [
        { id: "flow:tl", group: "anchor", x: 0, y: 0, label: "", shape: "dot", size: 1, opacity: 0, fixed: { x: true, y: true } },
        { id: "flow:br", group: "anchor", x: cw, y: ch, label: "", shape: "dot", size: 1, opacity: 0, fixed: { x: true, y: true } },
      ];

      if (isTB) {
        // R0 agent 顶行 / R2 fetcher 底行(水平 floatRow)。
        const contentW = Math.max(PAD * 2 + agents.length * 110, boxRight + PAD);
        const agentDesired = n => { const t = tgtOf(n); return t.length ? mean(t.map(q => q.x)) : contentW / 2; };
        floatRow(agents, agentDesired, PAD, n => n.label.length * ROW_W + 46, PAD, contentW - PAD, 50);
        const fxY = maxBoxBottom + 190;
        const fxDesired = n => { const s = srcOf(n); return s.length ? mean(s.map(q => q.x)) : contentW / 2; };
        floatRow(fxNodes, fxDesired, fxY, n => n.label.length * 8.6 + 70, PAD, contentW - PAD, 40);
        const h = fxY + 70;
        nodes.push(...anchorOf(contentW, h));
        return { w: contentW, h };
      }

      // LR: agent 左列 / fetcher 右列; 整组框右移空出 agent 列。
      const agentColW = agents.length
        ? Math.max(...agents.map(n => n.label.length * ROW_W + 60)) : PAD;
      const shift = agentColW + 80;
      flowBoxes.forEach(b => { b.x += shift; b.eps.forEach(q => { q.x += shift; }); });
      const fxX = boxRight + shift + 150;
      const fxMaxW = fxNodes.length ? Math.max(...fxNodes.map(n => n.label.length * 8.6 + 70)) : 200;
      const yMin = PAD, yMax = maxBoxBottom;
      const aDesY = n => { const t = tgtOf(n); return t.length ? mean(t.map(q => q.y)) : yMin + HEAD; };
      floatCol(agents, aDesY, PAD, yMin, yMax, 44);
      const fDesY = n => { const s = srcOf(n); return s.length ? mean(s.map(q => q.y)) : yMin + HEAD; };
      floatCol(fxNodes, fDesY, fxX, yMin, yMax, 30);
      const colBottom = a => a.length ? Math.max(...a.map(n => n.y + 44)) : 0;
      const contentW = fxX + fxMaxW + PAD;
      const contentH = Math.max(maxBoxBottom + PAD, colBottom(agents), colBottom(fxNodes));
      nodes.push(...anchorOf(contentW, contentH));
      return { w: contentW, h: contentH };
    }

    // hex "#rrggbb" -> "rgba(r,g,b,a)";解析失败返回 null(调用方不填充)。
    function hexA(hex, a) {
      const m = /^#?([0-9a-f]{6})$/i.exec(String(hex || "").trim());
      if (!m) return null;
      const n = parseInt(m[1], 16);
      return "rgba(" + ((n >> 16) & 255) + "," + ((n >> 8) & 255) + "," + (n & 255) + "," + a + ")";
    }

    function rrPath(ctx, x, y, w, h, r) {
      ctx.moveTo(x + r, y);
      ctx.arcTo(x + w, y, x + w, y + h, r);
      ctx.arcTo(x + w, y + h, x, y + h, r);
      ctx.arcTo(x, y + h, x, y, r);
      ctx.arcTo(x, y, x + w, y, r);
      ctx.closePath();
    }

    // 在每次重绘的底层画 section 分组框(半透明圆角 + 标题)。
    function drawFlowBoxes(ctx) {
      if (!flowBoxes.length) return;
      const border = cssVar("--border", "#e5e5ea");
      const muted = cssVar("--text-muted", "#6e6e73");
      ctx.save();
      ctx.font = "600 12px -apple-system, 'PingFang SC', sans-serif";
      for (const b of flowBoxes) {
        ctx.beginPath();
        rrPath(ctx, b.x, b.y, b.w, b.h, 8);
        ctx.fillStyle = hexA(border, 0.45) || "transparent";
        ctx.fill();
        ctx.strokeStyle = border;
        ctx.lineWidth = 1;
        ctx.stroke();
        ctx.fillStyle = muted;
        ctx.textAlign = "left";
        ctx.textBaseline = "alphabetic";
        ctx.fillText(b.sid, b.x + 12, b.y + 19);
      }
      ctx.restore();
    }
```

- [ ] **Step 3: 重写 `render()` 为"依赖流 / force"双分支**

把现有 `render` 整函数(:1019-1091)替换为:

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
      const isFlow = isFlowLayout(lastLayout);
      const graph = buildGraph(manifest);       // nodes + 全部边(两种 _kind)
      const nodes = graph.nodes;
      allServedBy = graph.edges.filter(e => e._kind === "served-by");
      const edges = graph.edges;                // 依赖流与力导向都全画(聚焦淡化靠 paint)

      if (isFlow) {
        nodes.filter(n => n.group === "endpoint").forEach(n => {
          n._fullLabel = n.label;
          n.label = shortGraphLabel(n._ep);
          n.title = `${n._ep.method} ${n._ep.path}\n${n._ep.summary || ""}`;
        });
        const extent = layoutFlow(nodes, (callbacks && callbacks.dir) || "TB"); // dir 见 Task 2b
        nodes.forEach(n => { n.fixed = { x: true, y: true }; });
        container.style.width = extent.w + "px";
        container.style.height = extent.h + "px";
        container.style.minWidth = "640px";
      } else {
        flowBoxes = [];                         // force 无分组框
        container.style.width = "100%";
        container.style.height = "100%";
        container.style.minWidth = "640px";
      }

      dataSet = {
        nodes: new window.vis.DataSet(nodes),
        edges: new window.vis.DataSet(edges),
      };
      baseEdges = dataSet.edges.get().map(e => ({
        id: e.id, from: e.from, to: e.to, width: e.width,
        color: { color: e.color.color, opacity: e.color.opacity },
      }));
      baseNode = {};
      dataSet.nodes.get().forEach(n => { baseNode[n.id] = { color: n.color }; });

      const options = {
        nodes: { font: { color: cssVar("--text", "#1d1d1f"), size: 13 } },
        edges: { smooth: { type: "continuous", roundness: 0.5 } },
        physics: isFlow
          ? false
          : {
              stabilization: { iterations: 120, fit: true },
              barnesHut: { gravitationalConstant: -8000, springLength: 140, springConstant: 0.04 },
            },
        interaction: { hover: true, tooltipDelay: 120, navigationButtons: false, zoomView: true, dragView: true },
      };
      network = new window.vis.Network(container, dataSet, options);
      focusedId = null;
      pinnedFocus = false;
      searchDim = {};

      if (isFlow) network.on("beforeDrawing", drawFlowBoxes);
      network.on("click", (params) => {
        if (!params.nodes || params.nodes.length === 0) return;   // 点空白: 无操作(Task 3 改为清聚焦)
        const node = dataSet.nodes.get(params.nodes[0]);
        if (!node || node.group === "anchor") return;
        if (lastCallbacks.onNodeClick) lastCallbacks.onNodeClick(node);
      });

      if (isFlow) network.fit({ animation: false });
    }
```

- [ ] **Step 4: 替换 `applyFilter()`(隐藏节点即隐边, 无边悬空)**

把现有 `applyFilter` 整函数(:1095-1126)替换为:

```javascript
    // Hide nodes whose endpoint doesn't match the market/fetcher filter.
    // Fetcher nodes stay visible iff at least one served-by neighbor stays.
    // vis 会自动不画 hidden 节点的相连边 → 无需手动删边, 也不会悬空线。
    function applyFilter(state) {
      if (!network || !dataSet) return;
      const visibleEp = new Set();
      for (const sec of lastManifest.sections) {
        for (const ep of sec.endpoints) {
          const marketOk = (ep.markets || []).some(m => (state.marketFilter || []).includes(m));
          const fetcherOk = !state.fetcherFilter
            || (ep.fetchers || []).some(f => f.name === state.fetcherFilter)
            || (!ep.fetchers || ep.fetchers.length === 0);
          if (marketOk && fetcherOk) visibleEp.add("ep:" + ep.path);
        }
      }
      const visibleFx = new Set();
      for (const e of allServedBy) if (visibleEp.has(e.from)) visibleFx.add(e.to);
      const updates = dataSet.nodes.get().map(n => {
        if (n.group === "anchor") return null;
        const vis = n.group === "endpoint" ? visibleEp.has(n.id)
          : n.group === "fetcher" ? visibleFx.has(n.id) : true;
        return { id: n.id, hidden: !vis };
      }).filter(Boolean);
      dataSet.nodes.update(updates);
      if (network) network.redraw();
    }
```

- [ ] **Step 5: 替换 `applySearch()`(跳过 anchor, 其余照旧暗化)**

把现有 `applySearch` 整函数(:1129-1137)替换为:

```javascript
    // Dim (not hide) nodes whose label doesn't fuzzy-match q. Anchors excluded.
    function applySearch(q) {
      if (!network || !dataSet) return;
      const query = (q || "").trim();
      const updates = dataSet.nodes.get()
        .filter(n => n.group !== "anchor")
        .map(n => {
          const match = !query || fuzzyMatchGlobal(query, n.label);
          return { id: n.id, opacity: match ? 1.0 : 0.15 };
        });
      dataSet.nodes.update(updates);
    }
```

- [ ] **Step 6: 语法校验**

Run: 上方「语法校验命令」。
Expected: `scripts: 5 errors: 0`。

- [ ] **Step 7: smoke(默认即新三层;force 无回归)+ commit**

起临时 server:

```bash
SERVER_PORT=8891 python -m stock_data.server > /tmp/srv_flow.log 2>&1 &
sleep 7 && curl -s http://127.0.0.1:8891/control/api-manifest -o /dev/null -w "manifest http %{http_code}\n"
```

浏览器开 `http://127.0.0.1:8891/explorer/` → 切 Dependency Graph(默认"分区"按钮此刻渲染新三层):
1. 出现 3 层: 顶部 agent ◇、中部带圆角框 + 框标题(如 `stocks`/`news`)的分组、底部 fetcher 盒;画布内容明显比之前紧凑、无单点长列。
2. served-by 细线与 composed-of 紫虚线**默认都可见**(抽查 `stocks/{code}/kline` → Tushare/Baostock… 与 `market-context` → news/calendar…)。
3. 点某端点 → 右侧 NodeDetailPanel 出详情(无展开边行为, 正常)。
4. 切 `力导向` → 原物理图(全边 + 可拖动);切回 `分区`(仍渲染三层)→ 布局恢复且 search/market 过滤保留。
5. 搜索 `kline` 暗化 / 勾掉 csi / 🌗 切主题 → DevTools console 无 `Error`(favicon 404 忽略)。
6. reload 后仍能正常进入图。

Commit:

```bash
git add stock_data/explorer/static/index.html
git commit -m "feat(explorer): three-layer dependency-flow layout replaces section columns

GraphView section mode now renders 3 fixed ranks (agent -> labeled
section group boxes -> fetchers) with centroid anchoring, ALL edges
(served-by + composed-of) visible by default, section boxes drawn on
canvas beforeDrawing. Force mode unchanged.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

临时 server 保留给 Task 2 smoke 复用。

---

### Task 2: 改名 `flow` + 工具条「依赖流/力导向」+ 旧值迁移

把布局值域、工具条、默认值与持久化从 `"section"` 迁移到 `"flow"`,并让 GraphView 接受两种字面(旧存 `"section"` 与新的 `"flow"`)。任务完成后默认布局显示的就是"依赖流"。

**Files:** Modify: `stock_data/explorer/static/index.html`(主 app IIFE:`state` :1391-1407、`applyView` graph 分支 :1518-1559、`renderGraph` :1569-1580)

**Interfaces:**
- Consumes: Task 1 的 `isFlowLayout()`(已兼容 `"flow"`)与 `GraphView.render(…,{layout})`。
- Produces: `state.graphLayout ∈ "flow"|"force"`(默认 `"flow"`;读旧 `"section"` 归一为 `"flow"`);工具条两段 `dataset.layout = "flow"|"force"` 文案「依赖流 / 力导向」;`renderGraph` 传 `layout: state.graphLayout`。
- 依赖后续: Task 3 依赖工具条存在 `#graphLayoutSwitch`、hint 元素 class `.graph-toolbar-hint`。

- [ ] **Step 1: 归一化 `state.graphLayout` 初值**

把 `state` 里这一行(:1395):

```javascript
      graphLayout: safeGetItem("graphLayout", "section"),
```

替换为:

```javascript
      // 旧值 "section" 已更名为 "flow"; 读到 "section" 视为 "flow"(不强制回写)。
      graphLayout: (() => {
        const v = safeGetItem("graphLayout", "section");
        return v === "force" ? "force" : "flow";
      })(),
```

- [ ] **Step 2: 工具条文案与按钮**

在 `applyView` 的 graph 分支中,把工具条两段按钮(:1526-1533)与 hint(:1539-1544)整体改为 依赖流/力导向:

把

```javascript
        seg.appendChild(el("button", {
          type: "button", className: "seg" + (state.graphLayout === "section" ? " active" : ""),
          dataset: { layout: "section" }, textContent: "分区",
        }));
```

替换为:

```javascript
        seg.appendChild(el("button", {
          type: "button", className: "seg" + (state.graphLayout === "flow" ? " active" : ""),
          dataset: { layout: "flow" }, textContent: "依赖流",
        }));
```

把 hint 的三元条件(`:1541-1543`):

```javascript
          textContent: state.graphLayout === "section"
            ? "端点按 section 归区; 点端点展开它的 fetcher; 点空白收回"
            : "力导向全局图(served-by 实线 + composed-of 虚线)",
```

替换为:

```javascript
          textContent: state.graphLayout === "flow"
            ? "agent → 端点 → fetcher 三层; hover / 单击节点聚焦其邻边"
            : "力导向全局图(served-by 实线 + composed-of 虚线)",
```

- [ ] **Step 3: `renderGraph` 无需改值域**(`layout: state.graphLayout` 现为 `"flow"`/`"force"`,已由 Task 1 `isFlowLayout` 接收)。确认 :1572 仍是 `layout: state.graphLayout`,不改。

- [ ] **Step 4: 语法校验**

Run: 语法校验命令。
Expected: `scripts: 5 errors: 0`。

- [ ] **Step 5: smoke**

浏览器(server 8891): reload 后切 Dependency Graph:
1. 工具条显示「依赖流 / 力导向」,默认高亮 **依赖流**,渲染三层(同 Task 1)。
2. 点 `力导向` 再点 `依赖流` → 布局切换正常、过滤保留。
3. DevTools → localStorage 设 `graphLayout = "section"` 后 reload → 进图仍是三层(归一为 flow),不报错。

- [ ] **Step 6: commit**

```bash
git add stock_data/explorer/static/index.html
git commit -m "feat(explorer): rename section layout to dependency-flow in toolbar

graphLayout values now flow|force; legacy 'section' normalizes to 'flow'.
Toolbar shows 依赖流/力导向 (flow default).

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2b: 依赖流方向切换(竖排 TB / 横排 LR)

依赖流排版支持方向切换: **TB(竖排, 默认, agent 上→fetcher 下)** 与 **LR(横排, agent 左列→fetcher 右列, 框仍是中部竖列)**。方向只对依赖流生效;力导向下方向控件禁用。UI 加第二组 segmented「竖排 / 横排」。

**Files:** Modify: `stock_data/explorer/static/index.html`(主 app IIFE:`state`、`applyView` graph 分支、`setGraphLayout`、`renderGraph`;CSS `.graph-dir-off`)

**Interfaces:**
- Consumes: Task 1 的 `GraphView.render(…,{dir})`(缺省 `"TB"`)与 `layoutFlow(nodes,dir)` 的 LR 分支;Task 2 的 `state.graphLayout ∈ "flow"|"force"`。
- Produces: `state.graphDir ∈ "TB"|"LR"`(默认 `"TB"`,persist `graphDir`);工具条 `#graphDirSwitch`(两段 竖排/横排,dataset.dir=`"TB"|"LR"`);`setGraphDir(v)`;`syncDirControl()`;`renderGraph` 传 `dir: state.graphDir`。Task 3/4 不感知方向(只依赖节点 id/DataSet)。

- [ ] **Step 1: `state` 加 `graphDir`**

把 Task 2 Step 1 已替换的 `state` 中、`graphLayout` 行之后插入:

```javascript
      // 依赖流方向: "TB"(竖排, 默认) | "LR"(横排)。仅依赖流有意义。
      graphDir: safeGetItem("graphDir", "TB") === "LR" ? "LR" : "TB",
```

- [ ] **Step 2: CSS 加禁用态**

在 `<style>` 里 `.graph-toolbar .graph-toolbar-hint { … }` 规则之后加:

```css
    .graph-dir-off { opacity: 0.45; pointer-events: none; }
```

- [ ] **Step 3: `applyView` graph 分支加方向控件**

在 graph 分支里,`bar.appendChild(seg);`(布局 segmented)之后、构建 wrap 之前插入:

```javascript
        // 方向: 仅依赖流可用(force 无方向, 见 syncDirControl)。
        const dirCtl = el("div", {
          id: "graphDirSwitch", className: "segmented graph-dir", role: "group",
          "aria-label": "Flow direction",
        });
        dirCtl.appendChild(el("button", {
          type: "button", className: "seg" + (state.graphDir === "TB" ? " active" : ""),
          dataset: { dir: "TB" }, textContent: "竖排",
        }));
        dirCtl.appendChild(el("button", {
          type: "button", className: "seg" + (state.graphDir === "LR" ? " active" : ""),
          dataset: { dir: "LR" }, textContent: "横排",
        }));
        dirCtl.onclick = (e) => {
          const b = e.target.closest(".seg");
          if (b && state.graphLayout === "flow") setGraphDir(b.dataset.dir);
        };
        bar.appendChild(dirCtl);
        syncDirControl();
```

- [ ] **Step 4: 加 `setGraphDir` + `syncDirControl`(放在 `setGraphLayout` 之后)**

```javascript
    function setGraphDir(v) {
      if (state.graphDir === v) return;
      state.graphDir = v;
      safeSetItem("graphDir", v);
      $$("#graphDirSwitch .seg").forEach(b =>
        b.classList.toggle("active", b.dataset.dir === state.graphDir));
      const canvas = $("#graphCanvas");
      if (!canvas) return;
      GraphView.destroy();
      renderGraph(canvas);
    }

    // force 布局没有方向概念 → 禁用方向控件; 切回依赖流恢复。
    function syncDirControl() {
      const dc = $("#graphDirSwitch");
      if (!dc) return;
      const off = state.graphLayout !== "flow";
      dc.classList.toggle("graph-dir-off", off);
      dc.setAttribute("aria-disabled", off ? "true" : "false");
    }
```

- [ ] **Step 5: `setGraphLayout` 切换后同步方向控件 + `renderGraph` 传 `dir`**

在 `setGraphLayout` 里 `b.classList.toggle("active", b.dataset.layout === state.graphLayout));` 之后插入 `syncDirControl();`。

把 `renderGraph` 里传给 `GraphView.render` 的配置对象加一行:

```javascript
      GraphView.render(container, MANIFEST, {
        layout: state.graphLayout,
        dir: state.graphDir,
        onNodeClick: (n) => {
```

- [ ] **Step 6: 语法校验**

Run: 语法校验命令。
Expected: `scripts: 5 errors: 0`。

- [ ] **Step 7: smoke**

浏览器(server 8891),默认依赖流:
1. 工具条出现「依赖流/力导向」+「竖排/横排」;默认高亮 **竖排**,三层上下排布(同前)。
2. 点 `横排` → agent 到最左一列、fetcher 到最右一列、中间仍是 section 竖列框;served-by/composed-of 边仍可见且方向左→右;focus(点某 fetcher)/search/过滤照常。
3. 点回 `竖排` → 恢复上下排布;切 `力导向` → 方向控件变灰(禁用),无方向按钮可点;切回 `依赖流` → 控件恢复且保留之前的竖/横选择。
4. DevTools → localStorage 设 `graphDir="LR"` reload → 进图即为横排;设 `"TB"`/删掉 → 竖排。
5. console 无 `Error`(favicon 404 忽略)。

- [ ] **Step 8: commit**

```bash
git add stock_data/explorer/static/index.html
git commit -m "feat(explorer): dependency-flow direction toggle (竖排 TB / 横排 LR)

state.graphDir persisted; second toolbar segmented enables vertical
(top-to-bottom) or horizontal (agent-left / fetcher-right columns) flow
rendering. Disabled in force mode via syncDirControl().

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: 聚焦强调交互(hover/click/空白 + 与 search/filter 协同)

加"聚焦邻边、其余淡化"的强调机制:单击端点/fetcher 钉住聚焦并开详情;hover 临时聚焦;点空白/再点钉住节点复原。search 暗化与 focus 叠加(`searchDim × focus 淡化`),filter 隐藏聚焦节点时自动清聚焦。force 模式不做强调(维持现状)。

**Files:** Modify: `stock_data/explorer/static/index.html`(`GraphView` IIFE)

**Interfaces:**
- Consumes: Task 1 的模块态 `focusedId/pinnedFocus/searchDim/baseEdges/baseNode/flowBoxes`、`isFlowLayout()`、`drawFlowBoxes`、`cssVar`。
- Produces: `setFocus(id,pin)` / `clearFocus()` / `paint()`;在 `render` 里按 `isFlow` 注册 `hoverNode/blurNode/click`(click 已存在, 本 task 扩展其分支)。
- 交互契约: 依赖流下 —— hover 节点 = 临时聚焦其 1 跳邻边/节点;单击端点或 fetcher = 钉住聚焦 + `NodeDetailPanel`;再点同节点或点空白 = 复原;端点被 market/fetcher 过滤隐藏或切布局/切视图/主题重建 = 自动清聚焦。

- [ ] **Step 1: 加 `setFocus` / `clearFocus` / `paint`(置于 `applySearch` 之前)**

在 GraphView 内、`applyFilter` 函数之后、`applySearch` 之前插入:

```javascript
    // 聚焦某节点: paint 会强调它及其 1 跳邻居的边/节点, 淡化其余。
    function setFocus(id, pin) {
      focusedId = id;
      pinnedFocus = !!pin;
      paint();
    }

    function clearFocus() {
      if (!focusedId) return;
      focusedId = null;
      pinnedFocus = false;
      paint();
    }

    // 依 searchDim(暗化) × focus(聚焦强调)重算全部节点/边最终样式。
    // 无聚焦时等价于纯 search 暗化; force 模式 focusedId 恒 null → 与旧行为一致。
    function paint() {
      if (!network || !dataSet) return;
      const warn = cssVar("--accent-warn", "#ff9500");
      const emph = new Set();
      if (focusedId) {
        emph.add(focusedId);
        for (const e of baseEdges) {
          if (e.from === focusedId || e.to === focusedId) { emph.add(e.from); emph.add(e.to); }
        }
      }
      const nodeUpd = dataSet.nodes.get()
        .filter(n => n.group !== "anchor")
        .map(n => {
          const base = (n.id in searchDim) ? searchDim[n.id] : 1;   // 1 or 0.15
          const opacity = (focusedId && !emph.has(n.id)) ? base * 0.15 : base;
          const upd = { id: n.id, opacity };
          const baseC = baseNode[n.id] ? baseNode[n.id].color : n.color;
          if (focusedId === n.id) upd.color = Object.assign({}, baseC, { border: warn });
          else upd.color = baseC;
          return upd;
        });
      dataSet.nodes.update(nodeUpd);

      const edgeUpd = baseEdges.map(e => {
        const inc = !!focusedId && (e.from === focusedId || e.to === focusedId);
        return {
          id: e.id,
          color: { color: e.color.color, opacity: inc ? e.color.opacity : e.color.opacity * 0.06 },
          width: inc ? e.width + 0.5 : e.width,
        };
      });
      dataSet.edges.update(edgeUpd);
    }
```

- [ ] **Step 2: `render` 事件按模式注册**(把 Task 1 Step 3 里那段 `network.on("click", …)` 替换)

把 render 中(当前):

```javascript
      if (isFlow) network.on("beforeDrawing", drawFlowBoxes);
      network.on("click", (params) => {
        if (!params.nodes || params.nodes.length === 0) return;   // 点空白: 无操作(Task 3 改为清聚焦)
        const node = dataSet.nodes.get(params.nodes[0]);
        if (!node || node.group === "anchor") return;
        if (lastCallbacks.onNodeClick) lastCallbacks.onNodeClick(node);
      });
```

替换为:

```javascript
      if (isFlow) {
        network.on("beforeDrawing", drawFlowBoxes);
        network.on("hoverNode", (p) => {
          const n = dataSet.nodes.get(p.node);
          if (!n || n.group === "anchor") return;
          if (!pinnedFocus && focusedId !== n.id) setFocus(n.id, false);
        });
        network.on("blurNode", () => { if (!pinnedFocus) clearFocus(); });
        network.on("click", (params) => {
          const id = params.nodes && params.nodes.length ? params.nodes[0] : null;
          const node = id ? dataSet.nodes.get(id) : null;
          if (!node || node.group === "anchor") { clearFocus(); return; }
          if (focusedId === node.id && pinnedFocus) { clearFocus(); }
          else { setFocus(node.id, true); }
          if (lastCallbacks.onNodeClick) lastCallbacks.onNodeClick(node);
        });
      } else {
        network.on("click", (params) => {
          if (!params.nodes || params.nodes.length === 0) return;
          const node = dataSet.nodes.get(params.nodes[0]);
          if (node && lastCallbacks.onNodeClick) lastCallbacks.onNodeClick(node);
        });
      }
```

> 说明: `render` 内那行 `if (isFlow) network.on("beforeDrawing", drawFlowBoxes);` 被并入上面的 flow 分支,删除旧单独行。

- [ ] **Step 3: `applyFilter` 尾部加"聚焦节点被隐藏则清聚焦"**(把 Task 1 Step 4 版本结尾处 `dataSet.nodes.update(updates);\n      if (network) network.redraw();` 替换)

替换为:

```javascript
      dataSet.nodes.update(updates);
      if (focusedId) {
        const f = dataSet.nodes.get(focusedId);
        if (!f || f.hidden) clearFocus();
      }
      if (network) network.redraw();
```

- [ ] **Step 4: `applySearch` 走 `paint()`**(替换 Task 1 Step 5 版本整函数)

替换为:

```javascript
    // Dim (not hide) nodes whose label doesn't fuzzy-match q; then paint() so
    // search dim and focus emphasis combine. Anchors stay at creation opacity 0.
    function applySearch(q) {
      if (!network || !dataSet) return;
      const query = (q || "").trim();
      searchDim = {};
      dataSet.nodes.get().forEach(n => {
        if (n.group === "anchor") return;
        if (query && !fuzzyMatchGlobal(query, n.label)) searchDim[n.id] = 0.15;
      });
      paint();
    }
```

- [ ] **Step 5: 语法校验**

Run: 语法校验命令。
Expected: `scripts: 5 errors: 0`。

- [ ] **Step 6: smoke**

浏览器(server 8891),默认依赖流:
1. **hover** 某端点(如 `stocks/{code}/kline`)→ 它的 served-by(到 Tushare/Baostock/Akshare…)与任意 composed-of 边加粗明显,其余边淡到 ~不可见;相邻 fetcher/上游端点保持不透明;移开 → 复原。
2. **单击某 fetcher**(如 `EastMoneyFetcher`)→ 它服务的所有端点点亮 + 相关边加粗,其余淡出;fetcher 边框变橙;右侧 NodeDetailPanel 开详情。**再点它** → 复原(面板仍保留)。
3. 单击某端点(如 `market-context`)→ 聚焦其 composed-of 目标;点**空白画布**(框内非端点处亦可)→ 复原。
4. 聚焦状态下输入搜索词(`kline`)→ 暗化的节点保持暗;清空搜索 → 聚焦恢复显示。
5. 聚焦状态下取消勾选 csi(market 过滤)→ 被隐藏端点的聚焦自动清、无悬空线、无报错。
6. 切 `力导向` 再切回 `依赖流` → 无残留聚焦;🌗 切主题重建 → 无报错;切到 Endpoints 视图再回来无残留。
7. DevTools console 全程无 `Error`(favicon 404 忽略)。

- [ ] **Step 7: commit**

```bash
git add stock_data/explorer/static/index.html
git commit -m "feat(explorer): focus-highlight neighbors in dependency-flow graph

Hover/click an endpoint or fetcher emphasizes its 1-hop edges and
neighbors while fading the rest; click again or blank clears. searchDim
× focus compose in paint(); filter-hide of the focused node clears focus.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: 收尾 smoke + 合并/停 server

- [ ] **Step 1: 完整回归**

按 spec §6 全清单跑一遍(默认依赖流三层 + 分组框标题;served-by 默认可见;composed-of 紫虚线恒显;hover/单击 fetcher 聚焦强调;点空白复原;search 暗化与聚焦叠加;market/fetcher 过滤;🌗 主题;reload 布局持久化 `flow` + `graphDir`;旧 localStorage `"section"` 归一;**竖排/横排方向切换 + force 下控件禁用**;切 Endpoints 再回来无残留)。全部通过。

- [ ] **Step 2: git status 干净确认 + 分支合并**

```bash
git status --short
git checkout master && git merge feat/explorer-dependency-flow --no-ff -m "Merge branch 'feat/explorer-dependency-flow'
feat(explorer): three-layer dependency-flow graph replaces section partition layout
Co-Authored-By: Claude <noreply@anthropic.com>"
```

- [ ] **Step 3: 停临时 server**

```bash
PID=$(netstat -ano | grep -E ':8891\b' | grep LISTENING | head -1 | awk '{print $NF}')
[ -n "$PID" ] && powershell -NoProfile -Command "Stop-Process -Id $PID -Force -ErrorAction SilentlyContinue"
```

---

## Self-Review

1. **Spec coverage**: spec §4.1 改名/默认 flow/旧值迁移 → Task 2;§4.2 三层 + 分组框 + 质心 + 孤立端点兜底 + **方向(竖排 TB / 横排 LR)** → Task 1 `layoutFlow(nodes,dir)`/`drawFlowBoxes` + Task 2b(UI);§4.3 served-by 全画/composed-of 主干/focus → Task 1 render(全边) + Task 3 paint;§4.4 交互(hover/click fetcher 聚焦 + 详情 + 点空白复原 + 清理)→ Task 3;§4.5 保留 search/filter/theme/复用 → Task 1 applyFilter/applySearch + 主 app 既有 handler;§4.6 共享节点 id/DataSet → Task 1;§4.7 只改 index.html → 是;§5 edge cases(空 section、孤立端点、画法坐标系→探针已证、旧 localStorage、focus 清理)→ Task 1/3 + 探针结论;§6 手动 smoke(含方向)→ Task 1/2b/3/4。无缺口。
2. **Placeholder scan**: 无 TBD/TODO;每步有完整代码/命令/期望。
3. **Type/名一致性**: `isFlowLayout` 兼容 `"flow"|"section"`,Task 1 用 `"section"`(旧)触发、Task 2 改 app 发 `"flow"`;`state.graphLayout ∈ "flow"|"force"`,`state.graphDir ∈ "TB"|"LR"`;`layoutFlow(nodes, dir)` 在 Task 1 定义、render 调用 `(callbacks && callbacks.dir) || "TB"`、Task 2b 从 app 传 `dir: state.graphDir`(未传时缺省 TB,故 Task 1/2 smoke 不受影响);`focusedId/pinnedFocus/searchDim/baseEdges/baseNode/flowBoxes/allServedBy` 全程同名;`setFocus(id,pin)/clearFocus()/paint()` 在 Task 3 定义并被 render/applyFilter/applySearch 引用一致;`drawFlowBoxes/rrPath/hexA/floatRow/floatCol/layoutFlow` 定义即用;anchor 用 `group:"anchor"` 并被 render/applyFilter/applySearch/paint 一致跳过;`setGraphDir/syncDirControl` 在 Task 2b 定义并被 applyView/setGraphLayout 引用一致。锚点 `ep:<path>`/`fx:<name>` 不变。

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-09-02-explorer-dependency-flow-layout.md`。两个执行选项:

**1. Subagent-Driven (recommended)** — 每 task 派一个子 agent,task 间我做 review。

**2. Inline Execution** — 本会话用 executing-plans 按 task 批量执行 + 检查点。

选哪种?
