# Explorer Fetcher Filter — 设计文档

> 日期: 2026-07-01
> 范围: 在 `/explorer/` sidebar 新增 "Filter by fetcher" 复选框块,支持按 fetcher 过滤端点列表,并提供一个开关,决定"端点卡片下的 Fetcher backends 内联列表"是否也被同样过滤。
> 性质: **纯前端扩展**。不动 server、不动 manifest 字段、不动 manager。
> 关联: 前置 `2026-06-12-explorer-fetcher-stage-design.md`(提供 manifest 里 `fetchers[]` 字段,本设计直接消费它)。

---

## 1. 目标与动机

**目标**: 让用户/开发者能在 `/explorer/` UI 上**直接按 fetcher 过滤**端点列表,并在端点卡片内部的 "Fetcher backends" 列表上选择性地应用同样的过滤。

**为什么需要**:
- 当前 explorer 只能用 section 导航 / market filter / search 找端点
- 调试场景:"这个 fetcher 到底能服务哪些端点?"——目前只能展开每张卡片看,无法聚合
- 例如排查 "Tushare 是不是唯一支持某只 stock 的数据源",需要逐张卡片翻
- 内联 "Fetcher backends" 列表对过滤场景来说信息冗余:如果我只关心 Zhitu,EastMoney 的展开信息是噪音

**非目标**:
- 不做 AND 语义(用户明确要求 OR,见 §4)
- 不做 PRIMARY 模式
- 不做 fetcher 缩写 chips
- 不做 fetcher 搜索框(12 个名字字母序好扫)
- 不动 server / manifest / manager 任何一行代码
- 不引入 JS 测试框架(本项目无前端测试基础设施)
- 不持久化旧 localStorage 键名(本地开发项目,无历史包袱)

---

## 2. 当前状态(受影响部分)

### 2.1 Sidebar(已删除 capability filter 后)

`stock_data/explorer/static/index.html:327-346`:
```html
<nav class="sidebar">
  <h3>Sections</h3>
  <div id="nav"></div>
  <h3>Filter by market</h3>
  <div class="filter-group" id="marketFilter">
    <label><input type="checkbox" value="csi" checked> csi (A股)</label>
    <label><input type="checkbox" value="hk" checked> hk</label>
    <label><input type="checkbox" value="us" checked> us</label>
  </div>
</nav>
```

### 2.2 端点筛选模式(market filter 已有的)

```js
$("#marketFilter").onchange = () => {
  const checked = Array.from($$("#marketFilter input:checked"), i => i.value);
  state.marketFilter = checked;
  safeSetItem("marketFilter", JSON.stringify(checked));
  renderContent();
};
```

`renderContent` 内部用 `.filter(ep => ep.markets.some(m => state.marketFilter.includes(m)))`。

### 2.3 manifest 里的 `fetchers[]` 字段

每个 endpoint 节点:
```json
{
  ...,
  "fetchers": [
    { "name": "AkshareFetcher", "method": "get_kline_data", "priority": 3,
      "capabilities": ["STOCK_KLINE"], "signature": [...], "available": true, "reason": null },
    ...
  ]
}
```

12 个 fetcher,分布:
- EastMoney 15、Zzshare 13、Zhitu 12、Akshare 7、Myquant 6
- Baostock/Yfinance/Ths 4、Tushare 3
- Baidu/Cninfo/Tencent 1

### 2.4 state 字段

```js
let state = {
  baseUrl, theme,
  marketFilter,  // 旧
  // 没有 fetcherFilter / fetcherListRestrict —— 本期新增
};
```

---

## 3. 设计方案

### 3.1 UI 布局

在 `#marketFilter` 块之后追加:

```html
<h3>Filter by fetcher</h3>
<div class="filter-group" id="fetcherFilter">
  <!-- 动态生成,见 §3.4 -->
</div>
<div class="filter-toggle">
  <label>
    <input type="checkbox" id="fetcherListRestrict">
    Restrict inline fetcher list to filter
  </label>
</div>
```

12 个 fetcher 名字按字母序排列,默认全部 checked。

### 3.2 state 字段

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

**默认值逻辑**(在 manifest 加载后、首次 render 前):

```js
async function boot() {
  await window.loadManifest();
  ...
  // 初始化 fetcherFilter:首次访问用全勾选,后续用 localStorage
  if (state.fetcherFilter === null) {
    state.fetcherFilter = collectAllFetcherNames(MANIFEST);
    safeSetItem("fetcherFilter", JSON.stringify(state.fetcherFilter));
  }
  renderFetcherFilterUI();  // 动态注入 checkbox
  ...
}

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

### 3.3 端点过滤(同 market filter 模式)

`renderContent` 内追加一行 `.filter()`:

```js
sec.endpoints
  .filter(ep => ep.markets.some(m => state.marketFilter.includes(m)))
  .filter(ep => epMatchesFetcherFilter(ep))
  .forEach(ep => content.appendChild(renderEndpoint(ep)));
```

```js
function epMatchesFetcherFilter(ep) {
  if (!ep.fetchers || ep.fetchers.length === 0) return true;  // 无 fetcher 的端点(/health) 总显示
  return ep.fetchers.some(f => state.fetcherFilter.includes(f.name));
}
```

### 3.4 Fetcher 复选框 UI 动态生成

`bindUI()` 内,market filter handler 之后追加:

```js
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

$("#fetcherFilter").onchange = () => {
  state.fetcherFilter = Array.from($$("#fetcherFilter input:checked"), i => i.value);
  safeSetItem("fetcherFilter", JSON.stringify(state.fetcherFilter));
  renderContent();
};
```

### 3.5 Toggle 按钮

```js
$("#fetcherListRestrict").onchange = (e) => {
  state.fetcherListRestrict = e.target.checked;
  safeSetItem("fetcherListRestrict", String(state.fetcherListRestrict));
  refreshFetcherLists();  // 局部更新,不全量重渲染
};

function refreshFetcherLists() {
  $$(".endpoint").forEach(card => {
    const path = card.dataset.path;  // renderEndpoint 时设
    const ep = findEndpointByPath(MANIFEST, path);
    if (!ep) return;
    const list = card.querySelector(".fetcher-list");
    if (!list) return;
    list.innerHTML = "";
    visibleFetchers(ep).forEach(f => list.appendChild(renderFetcherRow(f)));
  });
}

function visibleFetchers(ep) {
  const all = ep.fetchers || [];
  if (!state.fetcherListRestrict) return all;
  return all.filter(f => state.fetcherFilter.includes(f.name));
}

function findEndpointByPath(manifest, path) {
  for (const sec of manifest.sections) {
    for (const ep of sec.endpoints) if (ep.path === path) return ep;
  }
  return null;
}
```

### 3.6 renderEndpoint 配合修改

需要在 `renderEndpoint` 创建的 card 根元素上挂 `data-path`,并在渲染 fetcher backends 子树时用 `<ul class="fetcher-list">` 包裹以便 `refreshFetcherLists` 精确定位。

最小改动(伪代码示意):
```js
function renderEndpoint(ep) {
  const card = el("article", { className: "endpoint", dataset: { path: ep.path } });
  ...
  // 现有 fetcher backends 渲染处:
  const list = el("ul", { className: "fetcher-list" });
  visibleFetchers(ep).forEach(f => list.appendChild(renderFetcherRow(f)));
  details.appendChild(list);
  ...
}
```

### 3.7 视觉

- 复选框:`<label><input type="checkbox" value="..." checked> AkshareFetcher</label>`,与 market filter 一致
- Toggle:小一号字号(`.filter-toggle` 新 CSS class),`#888` 文字色,带 1 行简短说明 "Restrict inline fetcher list to filter"

---

## 4. 行为规约

### 4.1 端点筛选(OR 语义)

| 勾选状态 | 显示的端点 |
|---|---|
| 全部 12 个勾选 | 全部 31 个 |
| 只勾 Zhitu | endpoint.fetchers 中含 "ZhituFetcher" 的端点 |
| 同时勾 Zhitu + EastMoney | 上述两者并集 |
| 全部不勾 | 0 个端点(无 fetcher 的 `/health` 仍显示) |

### 4.2 Toggle 行为

| Toggle 状态 | 内联 fetcher 列表显示内容 |
|---|---|
| 关(默认) | endpoint 完整 fetchers[] (现有行为) |
| 开 | endpoint.fetchers.filter(f => state.fetcherFilter.includes(f.name)) |

**关键不变量**:
- Toggle 默认 **关**(OFF),与 market filter 风格一致——默认不"扰乱"现有内联列表
- 切换 toggle 不触发 `renderContent`(避免重渲染整页)
- 切换 checkbox 仍触发 `renderContent`(同 market filter)— 重新过滤端点
- 切换 toggle 后,新过滤的端点列表立即用 toggle 状态决定内联列表内容(因为 `renderEndpoint` 调用 `visibleFetchers`)

### 4.3 状态持久化

- `fetcherFilter`: localStorage key `fetcherFilter`,JSON 序列化的字符串数组
- `fetcherListRestrict`: localStorage key `fetcherListRestrict`,字符串 `"true"` / `"false"`
- 首次访问:全部 12 个 fetcher checked,toggle off
- 后续访问:从 localStorage 读
- 不做防御性兼容解析(本地开发项目,无历史包袱)

---

## 5. 边界与降级

| 场景 | 行为 |
|---|---|
| Manifest 加载失败 | `collectAllFetcherNames` 返回 `[]`,`renderFetcherFilterUI` 注入空块,`<h3>Filter by fetcher</h3>` 仍显示但无 checkbox。Toggle 仍存在但无效果。 |
| endpoint 无 fetchers 字段 | `epMatchesFetcherFilter` 返回 `true`(总是显示),`visibleFetchers` 返回 `[]`,内联列表为空。 |
| 全部 12 个未勾选 | 端点列表为空(只剩无 fetcher 的端点)。Toggle 仍工作(内联列表也空)。 |
| localStorage 写入失败(隐私模式) | `safeSetItem` 已 try/catch,状态在内存仍正确,刷新后丢失。 |
| 新增 fetcher class | `collectAllFetcherNames` 自动从 manifest 聚合,UI 自动出现新 checkbox,默认 checked。无需改 HTML。 |

---

## 6. 性能

- `collectAllFetcherNames`: 31 端点 × ≤3 fetcher = ~90 次操作,O(1) 可忽略
- 复选框生成:12 个 DOM 元素,可忽略
- `renderContent` 增加一次 `.filter()`:O(31) 端点级
- `refreshFetcherLists`:遍历已渲染的 endpoint cards,只更新内部 `.fetcher-list` 子树,不重渲染整个 card

总开销:< 1ms,无需任何性能优化。

---

## 7. 测试

**不写自动化测试**,原因:
- 本项目无前端 JS 测试基础设施(`tests/` 全是 server-side pytest)
- 引入 Playwright/Selenium 测单文件 HTML 是过度工程
- 用 `mcp__plugin_playwright__browser_*` 手动验证(跟修 filter bug 时流程相同):
  1. 启动 server,打开 `/explorer/`
  2. 截图 sidebar 确认 fetcher 块出现
  3. 取消勾选 1 个 fetcher(如 Zhitu),确认端点数量减少
  4. 全部取消勾选,确认端点列表几乎为空
  5. 重新全选,打开 toggle,确认内联 fetcher 列表只剩 1 个端点 → 0 个勾选时为空
  6. 关闭 toggle,确认内联列表恢复完整
  7. 检查 console 无错误
  8. 刷新页面,确认勾选状态和 toggle 状态从 localStorage 恢复

---

## 8. 改动清单

```
stock_data/explorer/static/index.html
  + 新增 HTML:<h3>Filter by fetcher</h3> + <div id="fetcherFilter"> + toggle block
  + 新增 CSS:.filter-toggle 样式
  + 新增 state 字段:fetcherFilter, fetcherListRestrict
  + 新增 2 个 onchange handler
  + 新增 4 个函数:collectAllFetcherNames, renderFetcherFilterUI,
                  epMatchesFetcherFilter, visibleFetchers,
                  refreshFetcherLists, findEndpointByPath
  + 修改 renderEndpoint:挂 data-path,用 <ul class="fetcher-list"> 包裹内联 fetcher
  + 修改 renderContent:追加 .filter(ep => epMatchesFetcherFilter(ep))
  + 修改 boot():manifest 加载后调 renderFetcherFilterUI

预期: +60~80 行,1 个文件
0 server 改动
0 新依赖
```

---

## 9. 决策记录

- **OR 而非 AND**:用户明确要求 OR;AND 在 12-fetcher 场景下几乎无用(选中多 = 必空)
- **Toggle 默认关**:遵循"现有行为不被默认状态打破"原则——不勾 toggle = 不影响现有 fetcher 列表
- **动态 checkbox 而非硬编码 12 行**:新 fetcher 自动出现;HTML 干净
- **不持久化旧 key**:本地开发项目,无历史包袱
- **不写测试**:现有项目无前端测试基础设施;HTML 改动可由 Playwright 手测覆盖
