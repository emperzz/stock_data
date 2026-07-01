# Explorer Fetcher Filter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `/explorer/` sidebar 新增 "Filter by fetcher" 复选框块 + "Restrict inline fetcher list" 开关,让用户能按 fetcher 过滤端点列表(OR 语义),并选择性同步影响端点卡片内的 Fetcher backends 列表。

**Architecture:** 纯前端改动 `stock_data/explorer/static/index.html`。复用现有 market filter 的 state 模型 + localStorage 持久化模式;`fetchers[]` 字段已由 `2026-06-12-explorer-fetcher-stage-design` 提供,本次直接消费。新增 4 个函数:`collectAllFetcherNames`、`renderFetcherFilterUI`、`epMatchesFetcherFilter`、`visibleFetchers` + 1 个局部更新函数 `refreshFetcherLists`。无 server 改动、无 manifest 改动、无新依赖。

**Tech Stack:** Vanilla JS (ES6+)、HTML5 checkbox、localStorage。验证工具: Playwright (手动)。

**Reference:**
- Spec: `docs/superpowers/specs/2026-07-01-fetcher-filter-design.md`
- 现有同类实现参考:`#marketFilter` 在 index.html 里的端到端流程(state → onchange → renderContent)

---

## Task 1: 加载 manifest 后聚合 fetcher 名称(纯函数 + 测试用 console 验证)

**Files:**
- Modify: `stock_data/explorer/static/index.html:772-777` (state 块下方,函数定义区)

- [ ] **Step 1: 添加 `collectAllFetcherNames` 函数**

在 `let state = { ... }` 块(约 line 772)后、`function safeGetItem(...)` 块前,插入:

```js
    // Aggregate all fetcher names declared across every endpoint in the
    // current manifest. Used to build the dynamic Filter-by-fetcher
    // checkbox group. Sorted alphabetically for stable UI ordering.
    function collectAllFetcherNames(manifest) {
      const set = new Set();
      for (const sec of manifest.sections) {
        for (const ep of sec.endpoints) {
          for (const f of (ep.fetchers || [])) set.add(f.name);
        }
      }
      return [...set].sort();
    }
```

- [ ] **Step 2: 浏览器 console 验证(临时探针)**

启动 server,打开 `http://localhost:8888/explorer/`,在 DevTools console 跑:

```js
const names = collectAllFetcherNames(MANIFEST);
console.log(names);
console.log('count:', names.length);
```

**Expected output**:
- 一个包含 12 个 fetcher 名字的数组,字母序: `["AkshareFetcher", "BaiduFetcher", "BaostockFetcher", "CninfoFetcher", "EastMoneyFetcher", "MyquantFetcher", "TencentFetcher", "ThsFetcher", "TushareFetcher", "YfinanceFetcher", "ZhituFetcher", "ZzshareFetcher"]`
- count: 12

如果失败 → 检查函数位置是否在 state 块后、其他函数前。

- [ ] **Step 3: 不需要 commit(还在探针阶段);继续 Task 2**

---

## Task 2: state 字段 + boot 钩子 + localStorage 持久化

**Files:**
- Modify: `stock_data/explorer/static/index.html:772-780` (state 初始化)
- Modify: `stock_data/explorer/static/index.html:798-832` (boot 函数)

- [ ] **Step 1: 修改 `state` 块,添加新字段**

把现有:
```js
    let state = {
      baseUrl: safeGetItem("baseUrl", ""),
      theme: safeGetItem("theme", "light"),
      marketFilter: JSON.parse(safeGetItem("marketFilter", '["csi","hk","us"]')),
    };
```

替换为:
```js
    let state = {
      baseUrl: safeGetItem("baseUrl", ""),
      theme: safeGetItem("theme", "light"),
      marketFilter: JSON.parse(safeGetItem("marketFilter", '["csi","hk","us"]')),
      // fetcherFilter: null = 首次访问,首次访问时由 boot() 填入全勾选
      fetcherFilter: (() => {
        const raw = safeGetItem("fetcherFilter", null);
        return raw === null ? null : JSON.parse(raw);
      })(),
      fetcherListRestrict: safeGetItem("fetcherListRestrict", "false") === "true",
    };
```

- [ ] **Step 2: 在 `boot()` 里 `applyTheme()` 之后插入初始化逻辑**

现有 boot 函数(约 line 815):
```js
      applyTheme();
      bindUI();
      bindFetcherTestHandlers();
      ...
```

在 `applyTheme();` 之后、`bindUI();` 之前,插入:

```js
      // 初始化 fetcherFilter:首次访问(null)用全勾选,后续用 localStorage
      if (state.fetcherFilter === null) {
        state.fetcherFilter = collectAllFetcherNames(MANIFEST);
        safeSetItem("fetcherFilter", JSON.stringify(state.fetcherFilter));
      }
      renderFetcherFilterUI();
```

- [ ] **Step 3: 添加 `renderFetcherFilterUI` 函数 stub(避免 boot 报错,Task 3 完整实现)**

在 `collectAllFetcherNames` 函数(刚加的)后,插入:

```js
    // Dynamically build the fetcher filter checkbox group from the current
    // manifest. Called once at boot, after the manifest loads. Subsequent
    // checkbox state changes are handled by the fetcherFilter onchange.
    function renderFetcherFilterUI() {
      const container = $("#fetcherFilter");
      container.innerHTML = "";
      const names = collectAllFetcherNames(MANIFEST);
      for (const name of names) {
        const label = document.createElement("label");
        const input = document.createElement("input");
        input.type = "checkbox";
        input.value = name;
        input.checked = state.fetcherFilter.includes(name);
        label.appendChild(input);
        label.appendChild(document.createTextNode(" " + name));
        container.appendChild(label);
      }
    }
```

注意:`#fetcherFilter` DOM 元素还没添加,此 Task 跑会报"Cannot read properties of null"。在 Task 3 添加 HTML 后才会工作。

- [ ] **Step 4: 验证 state 字段初始化(临时探针)**

打开 `/explorer/`,DevTools console:

```js
// 首次访问(无 storage)
localStorage.removeItem('fetcherFilter');
localStorage.removeItem('fetcherListRestrict');
location.reload();
// reload 后查 state(注意 state 在闭包里,需要从 fetcherFilter checkbox 读)
const checkboxes = $$('#fetcherFilter input');
console.log('checkbox count:', checkboxes.length, 'all checked:', checkboxes.every(c => c.checked));
```

**Expected**: `checkbox count: 12` + `all checked: true` + localStorage `fetcherFilter` 是 12 个名字的 JSON 数组

- [ ] **Step 5: Commit**

```bash
git add stock_data/explorer/static/index.html
git commit -m "feat(explorer): add fetcher filter state + dynamic UI builder"
```

---

## Task 3: HTML markup — sidebar 块 + toggle 开关

**Files:**
- Modify: `stock_data/explorer/static/index.html:336-346` (在 `#marketFilter` 块后)

- [ ] **Step 1: 在 `#marketFilter` `</div>` 之后追加 fetcher filter HTML**

找到这段:
```html
      <div class="filter-group" id="marketFilter">
        <label><input type="checkbox" value="csi" checked> csi (A股)</label>
        <label><input type="checkbox" value="hk" checked> hk</label>
        <label><input type="checkbox" value="us" checked> us</label>
      </div>
    </nav>
```

替换为:
```html
      <div class="filter-group" id="marketFilter">
        <label><input type="checkbox" value="csi" checked> csi (A股)</label>
        <label><input type="checkbox" value="hk" checked> hk</label>
        <label><input type="checkbox" value="us" checked> us</label>
      </div>
      <h3>Filter by fetcher</h3>
      <div class="filter-group" id="fetcherFilter">
        <!-- 12 个 fetcher 复选框由 renderFetcherFilterUI() 动态生成 -->
      </div>
      <div class="filter-toggle">
        <label>
          <input type="checkbox" id="fetcherListRestrict">
          Restrict inline fetcher list to filter
        </label>
      </div>
    </nav>
```

- [ ] **Step 2: 验证 sidebar 出现 fetcher 块**

打开 `/explorer/`,DevTools:
```js
console.log($$('.sidebar h3').length, $$('#fetcherFilter').length, $$('#fetcherListRestrict').length);
```

**Expected**: 数组 `[3, 1, 1]`(3 个 h3: Sections / Filter by market / Filter by fetcher; 1 个 fetcherFilter div; 1 个 toggle checkbox)

- [ ] **Step 3: Commit**

```bash
git add stock_data/explorer/static/index.html
git commit -m "feat(explorer): add fetcher filter + restrict toggle HTML"
```

---

## Task 4: fetcher filter onchange handler + 端点过滤函数 + renderContent 集成

**Files:**
- Modify: `stock_data/explorer/static/index.html` (bindUI 函数,约 line 886-898)
- Modify: `stock_data/explorer/static/index.html` (renderContent 函数,约 line 925-937)
- Modify: `stock_data/explorer/static/index.html` (新函数 `epMatchesFetcherFilter` 添加位置)

- [ ] **Step 1: 添加 `epMatchesFetcherFilter` 函数**

在 `applySearchAndFilter` 函数(约 line 941)前,插入:

```js
    // OR-semantics fetcher filter: endpoint shows if any of its
    // failover-chain fetchers is in the active filter set. Endpoints with
    // no fetchers (e.g. /health) always show — they're "no data source"
    // metadata and would otherwise be unreachable via this filter.
    function epMatchesFetcherFilter(ep) {
      if (!ep.fetchers || ep.fetchers.length === 0) return true;
      return ep.fetchers.some(f => state.fetcherFilter.includes(f.name));
    }
```

- [ ] **Step 2: 修改 `renderContent` 链上追加过滤**

找到:
```js
        sec.endpoints
          .filter(ep => ep.markets.some(m => state.marketFilter.includes(m)))
          .forEach(ep => content.appendChild(renderEndpoint(ep)));
```

改为:
```js
        sec.endpoints
          .filter(ep => ep.markets.some(m => state.marketFilter.includes(m)))
          .filter(ep => epMatchesFetcherFilter(ep))
          .forEach(ep => content.appendChild(renderEndpoint(ep)));
```

- [ ] **Step 3: 在 `bindUI` 内追加 fetcher filter onchange**

找到 `bindUI` 函数最后(约 line 898,`}` 结束前),在 market filter handler 之后追加:

```js
      $("#fetcherFilter").onchange = () => {
        state.fetcherFilter = Array.from($$("#fetcherFilter input:checked"), i => i.value);
        safeSetItem("fetcherFilter", JSON.stringify(state.fetcherFilter));
        renderContent();
      };
```

- [ ] **Step 4: 浏览器验证**

打开 `/explorer/`,DevTools:
```js
// 初始全勾选
console.log('initial:', $$('.endpoint').length);
// 取消勾选 EastMoneyFetcher
const em = $$('#fetcherFilter input').find(i => i.value === 'EastMoneyFetcher');
em.click();
console.log('after em off:', $$('.endpoint').length);
// 恢复
em.click();
console.log('after em on:', $$('.endpoint').length);
```

**Expected**:
- initial: 31
- after em off: 16(= 31 - 15 个含 EastMoneyFetcher 的端点,精确因 manifest 是真实的)
- after em on: 31(回到全勾选)

第二步(zhitu 取消后)的端点数依赖 fetcher 间 overlap,无法从 12 精确推算。**只需验证"比 16 更少"**。

- [ ] **Step 5: 验证 localStorage 持久化**

```js
// 取消勾选一个,刷新页面,确认勾选状态保留
em.click();  // 取消
location.reload();
// reload 后:
console.log($$('#fetcherFilter input').find(i => i.value === 'EastMoneyFetcher').checked);  // false
$$('#fetcherFilter input').find(i => i.value === 'EastMoneyFetcher').click();  // 重新勾
location.reload();
console.log($$('#fetcherFilter input').find(i => i.value === 'EastMoneyFetcher').checked);  // true
```

- [ ] **Step 6: Commit**

```bash
git add stock_data/explorer/static/index.html
git commit -m "feat(explorer): wire fetcher filter checkbox to endpoint rendering"
```

---

## Task 5: renderEndpoint 加 `data-path` + 用 `<ul class="fetcher-list">` 包裹内联 fetcher 列表

**Files:**
- Modify: `stock_data/explorer/static/index.html` (renderEndpoint 函数)

> **背景**: 现有 `renderEndpoint` 渲染每个 endpoint card,内部已经有一个 "Fetcher backends" 的 `<details>` 折叠区(由 `2026-06-12-explorer-fetcher-stage` 引入)。需要给 card 根元素加 `data-path`,并把内部 fetcher 列表的 wrapper 改成 `<ul class="fetcher-list">`,以便 `refreshFetcherLists` 精确定位。

- [ ] **Step 1: 定位 renderEndpoint 当前实现 + 确认 `renderFetcherRow` 已存在**

```bash
grep -n "function renderEndpoint\|function renderFetcherRow\|data-path\|fetcher-list\|Fetcher backends" stock_data/explorer/static/index.html
```

确认存在:
- `renderEndpoint` 函数(约 line 1100+)
- `renderFetcherRow` 函数(**必须已存在**——由 `2026-06-12-explorer-fetcher-stage` 设计引入,本 plan 不重新定义它)
- 内联 fetcher 列表渲染处

如果 `renderFetcherRow` 不存在 → 停止,先补上 stage 设计的实现再继续。

**注意: 不要用 replace_all 改 fetcher 列表,只动 2 处。**

- [ ] **Step 2: 修改 card 根元素,加 `data-path`**

在 `renderEndpoint` 函数里,找到创建 card 根元素的那行(形如 `el("article", { className: "endpoint", ... })` 或 `document.createElement("article")`),在 props/dataset 里加 `path: ep.path`。

精确例子(假设是 `el(...)` 形式):
```js
// 改前
const card = el("article", { className: "endpoint" });
// 改后
const card = el("article", { className: "endpoint", dataset: { path: ep.path } });
```

如果是 `createElement` 形式:
```js
// 改前
const card = document.createElement("article");
card.className = "endpoint";
// 改后
const card = document.createElement("article");
card.className = "endpoint";
card.dataset.path = ep.path;
```

实际以文件里现存的写法为准。**用 Edit 工具的 exact match 替换**。

- [ ] **Step 3: 包裹内联 fetcher 列表为 `<ul class="fetcher-list">`**

在 renderEndpoint 内,找到渲染 fetcher 列表的代码块(目前是直接 `appendChild(renderFetcherRow(f))` 一行行加),把容器改为 `<ul class="fetcher-list">`,并用 `forEach` 填充。

精确例子(假设现有写法):
```js
// 改前
const fetcherDetails = el("details", { ... });
ep.fetchers.forEach(f => fetcherDetails.appendChild(renderFetcherRow(f)));
// 改后
const fetcherDetails = el("details", { ... });
const fetcherList = el("ul", { className: "fetcher-list" });
ep.fetchers.forEach(f => fetcherList.appendChild(renderFetcherRow(f)));
fetcherDetails.appendChild(fetcherList);
```

**注意: 这里是关键 — `ep.fetchers.forEach` 改用 `visibleFetchers(ep).forEach`(Task 6 引入的函数)。但 Task 5 现在还没加 visibleFetchers,所以先保持 `ep.fetchers.forEach`,Task 6 再统一改。**

- [ ] **Step 4: 验证**

打开 `/explorer/`,DevTools:
```js
console.log($$('.endpoint[data-path]').length);  // 应该是渲染出的端点数
console.log($$('.endpoint .fetcher-list').length);  // 同上
```

**Expected**: 两者都等于当前可见端点数(全勾选时 31)。

- [ ] **Step 5: Commit**

```bash
git add stock_data/explorer/static/index.html
git commit -m "refactor(explorer): wrap inline fetcher list in data-pathed card"
```

---

## Task 6: toggle handler + `visibleFetchers` + `refreshFetcherLists` + `findEndpointByPath`

**Files:**
- Modify: `stock_data/explorer/static/index.html` (bindUI 内追加 toggle handler)
- Modify: `stock_data/explorer/static/index.html` (新增 3 个函数)
- Modify: `stock_data/explorer/static/index.html` (renderEndpoint 内 `ep.fetchers.forEach` → `visibleFetchers(ep).forEach`)

- [ ] **Step 1: 添加 3 个新函数**

在 `epMatchesFetcherFilter` 函数(刚加的)后,插入:

```js
    // Compute the fetcher list to render under an endpoint card. When the
    // user has the "Restrict inline fetcher list to filter" toggle ON,
    // we narrow the list to the currently-checked fetchers; otherwise we
    // show the full failover chain (default behavior).
    function visibleFetchers(ep) {
      const all = ep.fetchers || [];
      if (!state.fetcherListRestrict) return all;
      return all.filter(f => state.fetcherFilter.includes(f.name));
    }

    // Find an endpoint node in the manifest by its path. O(N×M) over
    // sections × endpoints but trivial at our scale (31 endpoints).
    function findEndpointByPath(manifest, path) {
      for (const sec of manifest.sections) {
        for (const ep of sec.endpoints) if (ep.path === path) return ep;
      }
      return null;
    }

    // Local re-render of the inline fetcher-list subtree under every
    // already-rendered endpoint card. Avoids a full renderContent()
    // round-trip (which would re-attach all event listeners, lose any
    // expanded <details> state, etc.) when the user only flips the
    // toggle checkbox.
    function refreshFetcherLists() {
      $$(".endpoint").forEach(card => {
        const path = card.dataset.path;
        const ep = findEndpointByPath(MANIFEST, path);
        if (!ep) return;
        const list = card.querySelector(".fetcher-list");
        if (!list) return;
        list.innerHTML = "";
        visibleFetchers(ep).forEach(f => list.appendChild(renderFetcherRow(f)));
      });
    }
```

- [ ] **Step 2: renderEndpoint 内把 `ep.fetchers.forEach` 改为 `visibleFetchers(ep).forEach`**

在 Task 5 Step 3 改完的代码块里,把:
```js
ep.fetchers.forEach(f => fetcherList.appendChild(renderFetcherRow(f)));
```

改为:
```js
visibleFetchers(ep).forEach(f => fetcherList.appendChild(renderFetcherRow(f)));
```

- [ ] **Step 3: 在 `bindUI` 内追加 toggle onchange**

在 fetcher filter onchange(Task 4 刚加的)之后追加:

```js
      $("#fetcherListRestrict").onchange = (e) => {
        state.fetcherListRestrict = e.target.checked;
        safeSetItem("fetcherListRestrict", String(state.fetcherListRestrict));
        refreshFetcherLists();
      };
```

并在 `boot()` 里,首次 render 前把 toggle checkbox 状态设回去(否则刷新页面 toggle 视觉是 unchecked,即使 state 是 true)。

在 boot 里 `renderFetcherFilterUI();` 之后追加:
```js
      $("#fetcherListRestrict").checked = state.fetcherListRestrict;
```

- [ ] **Step 4: 浏览器验证**

打开 `/explorer/`,DevTools:
```js
// 默认 toggle off,内联列表显示完整
const card = $$('.endpoint')[0];
const fetcherCount1 = card.querySelectorAll('.fetcher-list > *').length;

// 打开 toggle
$$('#fetcherListRestrict')[0].click();
const fetcherCount2 = card.querySelectorAll('.fetcher-list > *').length;
// 仍全勾选 → 数量不变

// 取消一个 fetcher 后 toggle on → 内联列表缩小
$$('#fetcherFilter input').find(i => i.value === 'EastMoneyFetcher').click();
const fetcherCount3 = card.querySelectorAll('.fetcher-list > *').length;
console.log({ fetcherCount1, fetcherCount2, fetcherCount3 });
```

**Expected**:
- fetcherCount1 = fetcherCount2 (toggle 切换不影响全勾选状态)
- fetcherCount3 ≤ fetcherCount2 (取消 eastmoney 后,endpoints 里有 eastmoney 的 card 内联列表会少一项)

- [ ] **Step 5: 验证 toggle 持久化**

```js
// 当前 toggle on,刷新页面
location.reload();
// reload 后:
console.log($$('#fetcherListRestrict')[0].checked);  // true
```

- [ ] **Step 6: Commit**

```bash
git add stock_data/explorer/static/index.html
git commit -m "feat(explorer): wire restrict-inline toggle to inline fetcher list"
```

---

## Task 7: CSS for `.filter-toggle` 样式

**Files:**
- Modify: `stock_data/explorer/static/index.html` (`<style>` 块,约 line 1-200)

- [ ] **Step 1: 找到 `.filter-group` 现有 CSS,附近追加 `.filter-toggle`**

```bash
grep -n "filter-group\|filter-toggle" stock_data/explorer/static/index.html | head -20
```

定位现有 `.filter-group { ... }` 块,在其紧邻后追加:

```css
    .filter-toggle {
      padding: 4px 8px 8px;
      font-size: 12px;
      color: var(--text-muted, #666);
      line-height: 1.4;
    }
    .filter-toggle label {
      display: flex;
      align-items: center;
      gap: 4px;
      cursor: pointer;
    }
    .filter-toggle input[type="checkbox"] {
      margin: 0;
    }
```

注:`--text-muted` 是兜底变量名(避免硬编码颜色),实际项目里如有现有的 muted 文本色变量,优先用其名。

- [ ] **Step 2: 视觉验证**

打开 `/explorer/`,截图 sidebar 区域确认 toggle 文字比 checkbox label 小一号、颜色偏淡。

- [ ] **Step 3: Commit**

```bash
git add stock_data/explorer/static/index.html
git commit -m "style(explorer): add filter-toggle muted style"
```

---

## Task 8: 完整 Playwright 手动验证(spec §7 checklist)

**Files:**
- (no file changes; verification only)

- [ ] **Step 1: 启动 server,清 localStorage,打开 /explorer/**

```bash
cd D:/GitRepo/skills/stock_data
C:/ProgramData/miniconda3/python.exe -m stock_data.server > /tmp/server.log 2>&1 &
```

在 Playwright 浏览器中:
1. 打开 `http://localhost:8888/explorer/`
2. DevTools console:`localStorage.clear(); location.reload();`
3. 确认 sidebar 有 3 个 h3: "Sections" / "Filter by market" / "Filter by fetcher"
4. 确认 #fetcherFilter 块有 12 个 checked checkbox
5. 确认 #fetcherListRestrict 存在且 unchecked
6. 确认右侧 31 个端点全部显示

- [ ] **Step 2: 测试端点过滤**

操作:
1. 取消勾选 `EastMoneyFetcher`(15 个端点)→ 端点数应变 16
2. 取消勾选 `ZhituFetcher`(12 个端点)→ 端点数应变 ~10
3. 全部 12 个 fetcher 取消勾选 → 端点数应=0(只有 /health 等无 fetcher 端点)
4. 截图保存

- [ ] **Step 3: 测试 toggle 行为**

操作:
1. 重新全勾 12 个 fetcher
2. 打开 `<details>` 展开某 endpoint 的 "Fetcher backends" 列表,记录显示的 fetcher 数 N1
3. 勾选 toggle #fetcherListRestrict → 列表内容应**不变**(因为全勾选,visibleFetchers = all)
4. 取消勾选 `EastMoneyFetcher` → 该 endpoint 内联列表应减少 eastmoney 项(数量变 N1 - 1,若该 endpoint 有 eastmoney)
5. 关闭 toggle → 内联列表应恢复完整(所有 fetchers)
6. 截图保存

- [ ] **Step 4: 测试持久化**

操作:
1. 当前状态:toggle on,EastMoneyFetcher 取消勾选
2. `location.reload()`
3. 确认:toggle 仍 on,EastMoneyFetcher 仍 unchecked,内联列表状态符合规则

- [ ] **Step 5: 测试 search 与 fetcher filter 协同**

操作:
1. 取消所有 fetcher(0 端点)
2. 在 search box 输入 "kline" → 端点应显示(因为 search 不过滤 fetcher 维度,只看 endpoint 文本;但当前 filter 已 0 端点)
3. 改:全勾 fetcher,取消 search,确认端点恢复 31
4. 改为:在 search 框输入 "kline" + fetcher 取消 EastMoneyFetcher → 应看 kline 相关且不含 eastmoney 的端点

- [ ] **Step 6: Console 错误检查**

DevTools console 整个流程不应有任何 error(除 favicon.ico 404)。

- [ ] **Step 7: 不需要 commit;如发现 bug 走修复 Task**

---

## Task 9: 视觉截图归档(可选,仅供 doc)

**Files:**
- Create: `docs/superpowers/specs/2026-07-01-fetcher-filter-screenshot.png`(可选)

- [ ] **Step 1: 截图完整页面存档**

Playwright `browser_take_screenshot` 保存到 `docs/superpowers/specs/2026-07-01-fetcher-filter-screenshot.png`。

- [ ] **Step 2: 引用截图(可选)**

在 spec 文件末尾加一行:
```markdown
![Fetcher filter screenshot](2026-07-01-fetcher-filter-screenshot.png)
```

- [ ] **Step 3: Commit(如果加了截图)**

```bash
git add docs/superpowers/specs/
git commit -m "docs(spec): add fetcher filter screenshot"
```

---

## Task 10: 收尾 — 更新 memory + 最终 commit

**Files:**
- Modify: `C:\Users\yangxi18280\.claude\projects\D--GitRepo-skills-stock-data\memory\MEMORY.md` (如需要)

- [ ] **Step 1: 检查 memory 索引是否需要更新**

如果新实现中有非显而易见的决策值得记入 memory(例如 fetcher 列表动态聚合的取舍),写一条 `feedback` 或 `architecture` 类型 memory。

**Skip if** 没新洞察(本期是常规功能,跟现有 market filter 模式一致)。

- [ ] **Step 2: 停止 server**

```bash
tasklist 2>/dev/null | grep "python.*stock_data" | awk '{print $2}' | xargs -I {} taskkill /F /PID {} 2>/dev/null
```

- [ ] **Step 3: 检查 git log**

```bash
git log --oneline -10
```

**Expected**: 看到 5–6 条 feat/refactor/style commit 围绕 fetcher filter,首条是 Task 2 Step 5 的 state 改动。

- [ ] **Step 4: 报告完成**

向用户报告:commits 列表、Playwright 验证截图、是否有 bug 待修。
