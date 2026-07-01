# Fetcher Filter Single-Select Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `index.html` 里的 fetcher filter 从 12 个 checkbox 改为 12 个 radio(单选,空选=全选),保留 "Restrict inline fetcher list" toggle 并重定义语义。

**Architecture:** 单文件改造,沿用 Task 1-7 既有函数(`collectAllFetcherNames` / `renderFetcherFilterUI` / `epMatchesFetcherFilter` / `visibleFetchers`)。核心变化:input type,filter 语义(`.includes` → `===`),加 click 拦截器支持"点已选 radio 取消"。零 server 改动。

**Tech Stack:** Vanilla JS (ES6+)、HTML5 radio/checkbox、localStorage、Playwright 手动验证。

**Reference:**
- Spec: `docs/superpowers/specs/2026-07-01-fetcher-filter-single-select-design.md`
- 上一版 fetcher filter plan: `docs/superpowers/plans/2026-07-01-fetcher-filter.md`

---

## Task 1: 改 renderFetcherFilterUI (input type) + state init (schema 迁移)

**Files:**
- Modify: `stock_data/explorer/static/index.html` (state 块 ~line 756, renderFetcherFilterUI ~line 790)

- [ ] **Step 1: 改 state 初始化(支持 array 迁移为 null)**

Find the `fetcherFilter` field in `let state = {...}`:

```js
      // fetcherFilter: null = 首次访问,首次访问时由 boot() 填入全勾选
      fetcherFilter: (() => {
        const raw = safeGetItem("fetcherFilter", null);
        return raw === null ? null : JSON.parse(raw);
      })(),
```

Replace with:

```js
      // fetcherFilter: null = 无选中 (全选);string = 该 fetcher
      // 旧版 schema 是 array;遇到 array 视为 null (语义变更后已无意义)
      fetcherFilter: (() => {
        const raw = safeGetItem("fetcherFilter", null);
        if (raw === null) return null;
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed)) return null;
        return typeof parsed === "string" ? parsed : null;
      })(),
```

- [ ] **Step 2: 改 renderFetcherFilterUI (checkbox → radio)**

Find `renderFetcherFilterUI`:

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
```

Replace with:

```js
    function renderFetcherFilterUI() {
      const container = $("#fetcherFilter");
      container.innerHTML = "";
      const names = collectAllFetcherNames(MANIFEST);
      for (const name of names) {
        const label = document.createElement("label");
        const input = document.createElement("input");
        input.type = "radio";
        input.name = "fetcher";  // 共享 name → 互斥
        input.value = name;
        input.checked = (state.fetcherFilter === name);
        label.appendChild(input);
        label.appendChild(document.createTextNode(" " + name));
        container.appendChild(label);
      }
    }
```

- [ ] **Step 3: 浏览器验证基础 radio UI**

启动 server,打开 `/explorer/`,DevTools:
```js
// 清除旧 storage(若有旧 array 残留)
localStorage.removeItem('fetcherFilter');
location.reload();
// reload 后:
const radios = document.querySelectorAll('#fetcherFilter input[type="radio"]');
({
  count: radios.length,
  allUnchecked: Array.from(radios).every(r => !r.checked),
  shareName: Array.from(radios).every(r => r.name === 'fetcher'),
})
```

**Expected**: `{count: 12, allUnchecked: true, shareName: true}`

- [ ] **Step 4: Commit**

```bash
git add stock_data/explorer/static/index.html
git commit -m "refactor(explorer): convert fetcher filter to radio + migrate old array state"
```

---

## Task 2: 改 epMatchesFetcherFilter + visibleFetchers (=== 而非 includes)

**Files:**
- Modify: `stock_data/explorer/static/index.html` (epMatchesFetcherFilter ~line 980, visibleFetchers ~line 994)

- [ ] **Step 1: 改 epMatchesFetcherFilter**

Find:
```js
    function epMatchesFetcherFilter(ep) {
      if (!ep.fetchers || ep.fetchers.length === 0) return true;
      return ep.fetchers.some(f => state.fetcherFilter.includes(f.name));
    }
```

Replace with:
```js
    function epMatchesFetcherFilter(ep) {
      if (!ep.fetchers || ep.fetchers.length === 0) return true;
      if (state.fetcherFilter === null) return true;  // 无选中 = 全选
      return ep.fetchers.some(f => f.name === state.fetcherFilter);
    }
```

- [ ] **Step 2: 改 visibleFetchers**

Find:
```js
    function visibleFetchers(ep) {
      const all = ep.fetchers || [];
      if (!state.fetcherListRestrict) return all;
      return all.filter(f => state.fetcherFilter.includes(f.name));
    }
```

Replace with:
```js
    function visibleFetchers(ep) {
      const all = ep.fetchers || [];
      if (!state.fetcherListRestrict) return all;  // toggle off = 始终完整 chain
      if (state.fetcherFilter === null) return all;  // toggle on + 无选中 = 仍全
      return all.filter(f => f.name === state.fetcherFilter);
    }
```

- [ ] **Step 3: 浏览器验证单选 filter 行为**

打开 `/explorer/`,DevTools:
```js
// 选 EastMoneyFetcher
document.querySelector('#fetcherFilter input[value="EastMoneyFetcher"]').click();
({
  afterEmSelect: document.querySelectorAll('.endpoint').length,
  emRadioChecked: document.querySelector('#fetcherFilter input[value="EastMoneyFetcher"]').checked,
  otherRadiosChecked: Array.from(document.querySelectorAll('#fetcherFilter input'))
    .filter(r => r.value !== 'EastMoneyFetcher')
    .some(r => r.checked),
})
```

**Expected**: `{afterEmSelect: 15, emRadioChecked: true, otherRadiosChecked: false}`

(15 是 manifest 中含 EastMoneyFetcher 的端点数;其他 11 个 radio 应全 unchecked。)

- [ ] **Step 4: 验证 toggle on 时 inline list 只显示选中那个**

```js
// 打开 toggle
document.querySelector('#fetcherListRestrict').click();
const card = document.querySelector('.endpoint[data-path]');
const detail = card.querySelector('details.fetcher-backends');
detail.open = true;
const visibleFetchers = Array.from(card.querySelectorAll('.fetcher-list > *'))
  .map(el => el.textContent.match(/[A-Z][A-Za-z]+Fetcher/)?.[0]).filter(Boolean);
({
  inlineList: visibleFetchers,
})
```

**Expected**: `inlineList: ["EastMoneyFetcher"]` (1 项,只有 EM)

- [ ] **Step 5: Commit**

```bash
git add stock_data/explorer/static/index.html
git commit -m "refactor(explorer): update fetcher filter functions for single-select"
```

---

## Task 3: 改 onchange handler + 加 click 拦截器(取消选中) + 改 toggle label

**Files:**
- Modify: `stock_data/explorer/static/index.html` (fetcherFilter onchange ~line 945, toggle label ~line 343)

- [ ] **Step 1: 改 onchange handler**

Find:
```js
      $("#fetcherFilter").onchange = () => {
        state.fetcherFilter = Array.from($$("#fetcherFilter input:checked"), i => i.value);
        // Persist on user interaction (NOT on first visit — see boot init comment).
        safeSetItem("fetcherFilter", JSON.stringify(state.fetcherFilter));
        renderContent();
      };
```

Replace with:
```js
      $("#fetcherFilter").onchange = (e) => {
        if (e.target.checked) {
          state.fetcherFilter = e.target.value;
          // Persist on user interaction (NOT on first visit — see boot init comment).
          safeSetItem("fetcherFilter", JSON.stringify(state.fetcherFilter));
        }
        // 取消选中由 click 拦截器处理(在下面)
        renderContent();
      };
```

- [ ] **Step 2: 加 click 拦截器(实现"点已选 radio 取消")**

Right after the `fetcherFilter` onchange handler (inside `bindUI` function, before the `fetcherListRestrict` onchange), insert:

```js
      // 拦截点已选 radio 的行为 → 取消选中(回 null = 全选)
      // 用 setTimeout(0) 让浏览器先把 click 标为 checked,然后我们覆盖
      $("#fetcherFilter").addEventListener("click", (e) => {
        const input = e.target;
        if (!(input instanceof HTMLInputElement) || input.type !== "radio") return;
        if (input.checked && state.fetcherFilter === input.value) {
          setTimeout(() => {
            input.checked = false;
            state.fetcherFilter = null;
            safeSetItem("fetcherFilter", "null");
            renderContent();
          }, 0);
        }
      });
```

- [ ] **Step 3: 改 toggle label 文案**

Find in HTML:
```html
      <div class="filter-toggle">
        <label>
          <input type="checkbox" id="fetcherListRestrict">
          Restrict inline fetcher list to filter
        </label>
      </div>
```

Replace with:
```html
      <div class="filter-toggle">
        <label>
          <input type="checkbox" id="fetcherListRestrict">
          Show only the selected fetcher in endpoint list
        </label>
      </div>
```

- [ ] **Step 4: 浏览器验证取消选中 UX**

打开 `/explorer/`,DevTools:
```js
// 1. 选 EastMoneyFetcher
document.querySelector('#fetcherFilter input[value="EastMoneyFetcher"]').click();
const step1 = {
  emChecked: document.querySelector('#fetcherFilter input[value="EastMoneyFetcher"]').checked,
  endpointCount: document.querySelectorAll('.endpoint').length,
};

// 2. 点同一 radio 取消
document.querySelector('#fetcherFilter input[value="EastMoneyFetcher"]').click();
const step2 = {
  emChecked: document.querySelector('#fetcherFilter input[value="EastMoneyFetcher"]').checked,
  anyChecked: Array.from(document.querySelectorAll('#fetcherFilter input')).some(r => r.checked),
  endpointCount: document.querySelectorAll('.endpoint').length,
  storage: localStorage.getItem('fetcherFilter'),
};

({ step1, step2 })
```

**Expected**:
- `step1`: `{emChecked: true, endpointCount: 15}` (选了 EM,15 个端点)
- `step2`: `{emChecked: false, anyChecked: false, endpointCount: 31, storage: 'null'}` (取消,所有端点恢复,storage 存 "null")

- [ ] **Step 5: Commit**

```bash
git add stock_data/explorer/static/index.html
git commit -m "feat(explorer): single-select fetcher filter with click-to-cancel"
```

---

## Task 4: Playwright 完整验证(8 步 checklist)

**Files:**
- (no file changes; verification only)

- [ ] **Step 1: 启动 server,清 localStorage,打开 /explorer/**

Before starting the server, **always check for orphan**:
```bash
netstat -ano 2>/dev/null | grep ":8888 " | grep LISTENING
```
If anything is listening, kill it:
```bash
cmd //c "taskkill /F /PID <PID>"
```
(The `cmd //c` wrapper is essential — Git Bash MSYS rewrites `/F` `/PID` flags as paths otherwise.)

Then start server:
```bash
cd D:/GitRepo/skills/stock_data && C:/ProgramData/miniconda3/python.exe -m stock_data.server > /tmp/task4-server.log 2>&1 &
sleep 5
grep "Started server process" /tmp/task4-server.log
```

Then via Playwright:
1. `browser_navigate` to `http://localhost:8888/explorer/`
2. `browser_evaluate` to clear localStorage: `localStorage.clear();`
3. `browser_navigate` again to force reload
4. Check initial state:
```js
({
  radioCount: document.querySelectorAll('#fetcherFilter input[type="radio"]').length,
  allUnchecked: Array.from(document.querySelectorAll('#fetcherFilter input')).every(r => !r.checked),
  toggleExists: !!document.querySelector('#fetcherListRestrict'),
  toggleLabel: document.querySelector('.filter-toggle label').textContent.trim(),
  endpointCount: document.querySelectorAll('.endpoint').length,
})
```

**Expected**: `{radioCount: 12, allUnchecked: true, toggleExists: true, toggleLabel: "Show only the selected fetcher in endpoint list", endpointCount: 31}`

- [ ] **Step 2: 选 ZhituFetcher → 12 个端点**

```js
document.querySelector('#fetcherFilter input[value="ZhituFetcher"]').click();
({
  zhituChecked: document.querySelector('#fetcherFilter input[value="ZhituFetcher"]').checked,
  otherChecked: Array.from(document.querySelectorAll('#fetcherFilter input'))
    .filter(r => r.value !== 'ZhituFetcher').some(r => r.checked),
  endpointCount: document.querySelectorAll('.endpoint').length,
})
```

**Expected**: `{zhituChecked: true, otherChecked: false, endpointCount: 12}`

- [ ] **Step 3: 选 EastMoneyFetcher → 替换为 15 个**

```js
document.querySelector('#fetcherFilter input[value="EastMoneyFetcher"]').click();
({
  emChecked: document.querySelector('#fetcherFilter input[value="EastMoneyFetcher"]').checked,
  zhituChecked: document.querySelector('#fetcherFilter input[value="ZhituFetcher"]').checked,  // 应 false
  endpointCount: document.querySelectorAll('.endpoint').length,
})
```

**Expected**: `{emChecked: true, zhituChecked: false, endpointCount: 15}`

- [ ] **Step 4: 取消选中 → 恢复 31**

```js
document.querySelector('#fetcherFilter input[value="EastMoneyFetcher"]').click();
({
  emChecked: document.querySelector('#fetcherFilter input[value="EastMoneyFetcher"]').checked,
  anyChecked: Array.from(document.querySelectorAll('#fetcherFilter input')).some(r => r.checked),
  endpointCount: document.querySelectorAll('.endpoint').length,
  storage: localStorage.getItem('fetcherFilter'),
})
```

**Expected**: `{emChecked: false, anyChecked: false, endpointCount: 31, storage: 'null'}`

- [ ] **Step 5: toggle on + 选 EM → inline list 只显示 EM**

```js
// 选 EM
document.querySelector('#fetcherFilter input[value="EastMoneyFetcher"]').click();
// 开 toggle
document.querySelector('#fetcherListRestrict').click();
// 找第一个有 fetcher 的 card 并展开
const card = document.querySelector('.endpoint[data-path]');
const det = card.querySelector('details.fetcher-backends');
det.open = true;
({
  inlineList: Array.from(card.querySelectorAll('.fetcher-list > *'))
    .map(el => el.textContent.match(/[A-Z][A-Za-z]+Fetcher/)?.[0]).filter(Boolean),
  summaryText: det.querySelector('summary').textContent,
})
```

**Expected**: `inlineList: ["EastMoneyFetcher"]` (1 项,只有 EM);`summaryText: "Fetcher backends (3)"` (option a — 总数不变)

- [ ] **Step 6: toggle off → inline list 恢复完整**

```js
document.querySelector('#fetcherListRestrict').click();
({
  inlineList: Array.from(card.querySelectorAll('.fetcher-list > *'))
    .map(el => el.textContent.match(/[A-Z][A-Za-z]+Fetcher/)?.[0]).filter(Boolean),
})
```

**Expected**: `inlineList: ["ZzshareFetcher", "ZhituFetcher", "EastMoneyFetcher"]` (3 项,完整)

- [ ] **Step 7: 持久化 + 旧 array 迁移**

```js
// 当前状态:toggle off,EM 选中
// 测试 1:刷新保留
location.reload();
({
  emChecked: document.querySelector('#fetcherFilter input[value="EastMoneyFetcher"]').checked,
  toggleChecked: document.querySelector('#fetcherListRestrict').checked,
})

// 测试 2:旧 array 迁移
localStorage.setItem('fetcherFilter', '["AkshareFetcher","ZhituFetcher"]');
location.reload();
({
  emChecked: document.querySelector('#fetcherFilter input[value="EastMoneyFetcher"]').checked,
  anyChecked: Array.from(document.querySelectorAll('#fetcherFilter input')).some(r => r.checked),
  endpointCount: document.querySelectorAll('.endpoint').length,
})
```

**Expected**:
- 测试 1: `{emChecked: true, toggleChecked: false}` (状态保留)
- 测试 2: `{emChecked: false, anyChecked: false, endpointCount: 31}` (旧 array 当作 null = 全选)

- [ ] **Step 8: console 无错误**

```js
// Reset state
localStorage.clear();
location.reload();
// 然后:browser_console_messages level=error
```

Expected: 0 errors (除无关的 favicon.ico 404)

- [ ] **Step 9: 停止 server,清理**

```bash
cmd //c "taskkill /F /IM python.exe"
```

---

## Task 5: 截图归档(可选,纯视觉)

**Files:**
- Create: `docs/superpowers/specs/2026-07-01-fetcher-filter-single-select-screenshot.png`(可选)

- [ ] **Step 1: 截图保存**

Playwright `browser_take_screenshot` 保存到该路径,捕获 12 radio + 新 toggle label 的状态。

- [ ] **Step 2: 引用截图(可选)**

在 spec 文件末尾加:
```markdown
![Fetcher filter single-select screenshot](2026-07-01-fetcher-filter-single-select-screenshot.png)
```

- [ ] **Step 3: Commit(若加了截图)**

```bash
git add docs/superpowers/specs/
git commit -m "docs(spec): add single-select fetcher filter screenshot"
```

---

## Task 6: 收尾

- [ ] **Step 1: 检查 git log**

```bash
git log --oneline 99e3795..HEAD
```

Expected: 3 commit (Task 1/2/3),可能加 1-2 个(Task 4 不 commit,Task 5 可选)

- [ ] **Step 2: 检查 explorer tests 通过(server 端不动,纯前端)**

```bash
cd D:/GitRepo/skills/stock_data && C:/ProgramData/miniconda3/python.exe -m pytest tests/test_explorer_manifest_endpoint.py 2>&1 | tail -3
```

Expected: 13 passed

- [ ] **Step 3: 报告完成**

向用户报告:3-4 commits,行为完全符合 spec,所有 8 步 Playwright 验证通过。
