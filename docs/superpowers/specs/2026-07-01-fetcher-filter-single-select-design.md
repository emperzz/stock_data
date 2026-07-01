# Explorer Fetcher Filter — Single-Select Redesign

> 日期: 2026-07-01
> 范围: 把 fetcher filter 从 **多选 checkbox** 改为 **单选 radio**,空选=全选;保留 "Restrict inline fetcher list" toggle,重定义为"只显示选中那个"。
> 性质: **单文件前端改造** (`stock_data/explorer/static/index.html`)。无 server 改动,无 manifest 改动。
> 关联: 替代 `2026-07-01-fetcher-filter-design.md` 中的 §3 行为,**保留** §1/§2/§4/§5/§7 决策。

---

## 1. 目标与动机

**目标**: 把 "Filter by fetcher" 从"多选 failover 链成员"改为"单选主用 fetcher",更符合调试场景——用户通常只关心"如果用 X 作为主源,会命中哪些端点"。

**为什么改**:
- 多选 OR 语义在 12 fetcher × 31 endpoint 下信息密度低,大部分组合 1-2 个 fetcher 就覆盖全
- 单选更直接:**"我想看 Zhitu 主控的所有端点"** vs "勾选 Zhitu,看 Zhitu 出现在 failover 链的所有端点"(后者还包含 EastMoney 主控的,Zhitu 只是 backup)
- 跟"PRIMARY 模式"思路一致,只是用更简单的单选 UX

**非目标**:
- 不支持多选(原 OR 行为作废)
- 不做 PRIMARY-only 严格模式(单选 radio 是近似实现,够用)
- 不动 search / market filter / sections 导航
- 不动 server / manifest / manager

---

## 2. 当前状态(改动相关)

### 2.1 已有 fetcher filter 实现(master 上)

12 个 checkbox + 1 个 toggle:
```html
<h3>Filter by fetcher</h3>
<div class="filter-group" id="fetcherFilter">
  <!-- 12 checkboxes, dynamically generated -->
</div>
<div class="filter-toggle">
  <label>
    <input type="checkbox" id="fetcherListRestrict">
    Restrict inline fetcher list to filter
  </label>
</div>
```

`state.fetcherFilter: string[] | null` (null = 首次访问,全勾选)。
`state.fetcherListRestrict: boolean` (默认 false)。

### 2.2 端点过滤逻辑(将改写)
```js
function epMatchesFetcherFilter(ep) {
  if (!ep.fetchers || ep.fetchers.length === 0) return true;
  return ep.fetchers.some(f => state.fetcherFilter.includes(f.name));
}
```

### 2.3 inline list 过滤(将改写)
```js
function visibleFetchers(ep) {
  const all = ep.fetchers || [];
  if (!state.fetcherListRestrict) return all;
  return all.filter(f => state.fetcherFilter.includes(f.name));
}
```

---

## 3. 设计方案

### 3.1 数据模型

**`state.fetcherFilter: string | null`** (从 `string[] | null` 改)
- `null` = 无选中 = 全选(显示全部 endpoint / 显示完整 chain)
- `"EastMoneyFetcher"` = 选中 EM,端点过滤与 inline list 过滤都围绕 EM

**`state.fetcherListRestrict: boolean`** (不变)
- toggle off (默认):inline list 显示 endpoint 完整 failover chain
- toggle on:inline list 只显示当前选中的 fetcher(若 null 则仍是完整 chain)

### 3.2 HTML 改动

12 个 `<input type="checkbox">` → 12 个 `<input type="radio" name="fetcher">`,共享 `name` 实现互斥单选。

```html
<div class="filter-group" id="fetcherFilter">
  <!-- dynamically generated, each input is radio with name="fetcher" -->
</div>
```

`<div class="filter-toggle">` 块**保留**,只改文案:
```html
<div class="filter-toggle">
  <label>
    <input type="checkbox" id="fetcherListRestrict">
    Show only the selected fetcher in endpoint list
  </label>
</div>
```
(原 "Restrict inline fetcher list to filter" 改为 "Show only the selected fetcher in endpoint list" — 反映 toggle 在新模型下的真实作用。)

### 3.3 端点过滤

```js
function epMatchesFetcherFilter(ep) {
  if (!ep.fetchers || ep.fetchers.length === 0) return true;  // 无 fetcher 端点总显示
  if (state.fetcherFilter === null) return true;  // 无选中 = 全选
  return ep.fetchers.some(f => f.name === state.fetcherFilter);
}
```

### 3.4 inline list 过滤

```js
function visibleFetchers(ep) {
  const all = ep.fetchers || [];
  if (!state.fetcherListRestrict) return all;  // toggle off = 始终显示完整 chain
  if (state.fetcherFilter === null) return all;  // toggle on + 无选中 = 仍全
  return all.filter(f => f.name === state.fetcherFilter);
}
```

### 3.5 状态初始化 + 持久化

```js
let state = {
  ...
  // fetcherFilter:null = "All";string = 该 fetcher
  fetcherFilter: (() => {
    const raw = safeGetItem("fetcherFilter", null);
    if (raw === null) return null;
    const parsed = JSON.parse(raw);
    // 旧版 schema 是 array;遇到 array 当作 null (语义变更)
    if (Array.isArray(parsed)) return null;
    return typeof parsed === "string" ? parsed : null;
  })(),
  fetcherListRestrict: safeGetItem("fetcherListRestrict", "false") === "true",
};
```

**写策略**:user interaction 才写,首次访问**不写**(沿用 Task 2 fix):
```js
$("#fetcherFilter").onchange = (e) => {
  if (e.target.checked) {
    state.fetcherFilter = e.target.value;
    safeSetItem("fetcherFilter", JSON.stringify(state.fetcherFilter));
  }
  // 取消选中不立即清 state — 依赖 click handler 的"清空所有"逻辑
  renderContent();
};
```

### 3.6 Radio 可取消(关键 UX)

原生 radio **不能取消**(选了就锁定)。用 click 拦截实现"点已选可取消":

```js
$("#fetcherFilter").addEventListener("click", (e) => {
  const input = e.target;
  if (!(input instanceof HTMLInputElement) || input.type !== "radio") return;
  if (input.checked && state.fetcherFilter === input.value) {
    // 点已选中的 radio → 取消
    setTimeout(() => {
      input.checked = false;
      state.fetcherFilter = null;
      safeSetItem("fetcherFilter", "null");
      renderContent();
    }, 0);
  }
});
```

`setTimeout(0)` 让浏览器先把原 click 标记为 checked,然后我们再覆盖(否则会"check 然后立刻 uncheck",视觉上无变化)。

### 3.7 renderFetcherFilterUI 改动

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

### 3.8 视觉

- **Radio**:继承现有 `.sidebar label` 样式(13px,muted)
- **Toggle**:沿用 Task 7 的 `.filter-toggle` 样式(12px,更 muted)
- **新增文案**:toggle label 改 "Show only the selected fetcher in endpoint list"

---

## 4. 行为规约

### 4.1 端点筛选

| 选中状态 | 显示的端点 |
|---|---|
| null (无 radio 选中) | 全部 31 个 |
| EastMoneyFetcher | 仅含 EM 的端点(15 个) |
| ZhituFetcher | 仅含 Zhitu 的端点(12 个) |

### 4.2 Toggle 行为

| 选中状态 | toggle off | toggle on |
|---|---|---|
| null | 内联显示完整 chain | 内联显示完整 chain(toggle 对 null 无效果) |
| EastMoneyFetcher | 内联显示完整 chain | 内联**只**显示 EM |

### 4.3 状态持久化

- `fetcherFilter`:localStorage key `fetcherFilter`,JSON 序列化的 string 或 `null`
  - 例:`"EastMoneyFetcher"` → `'"EastMoneyFetcher"'`
  - 例:无选中 → `'null'`
- `fetcherListRestrict`:沿用旧 schema
- 首次访问:**不写** `fetcherFilter` 到 localStorage
- **旧 array 值迁移**:`JSON.parse('["AkshareFetcher", ...]')` → array → 当作 `null` 处理

### 4.4 取消选中 UX

- 点击未选中的 radio → 选中
- 点击已选中的 radio → 取消(清 state.fetcherFilter = null)
- 任意时刻至多 1 个 radio 处于 checked 状态

---

## 5. 边界与降级

| 场景 | 行为 |
|---|---|
| localStorage 存的是旧 array | 解析为 array,当作 `null` (=全选)。下次 user interaction 覆盖。 |
| localStorage 存的是 string | 直接用。 |
| localStorage 存的是 "null" | `JSON.parse("null")` = `null`,直接用。 |
| Manifest 加载失败 | `state.fetcherFilter` 默认 `null`(=全选),即使 0 端点可见也不影响。 |
| 12 个 radio 全没选中(用户取消) | 所有 endpoint 显示 + inline list 显示完整 chain。 |

---

## 6. 性能

O(N) 端点级 filter。`O(1)` 字符串比较。无变化。

---

## 7. 测试

不写自动化测试(沿用前作 spec §7)。Playwright 手动验证:
- 12 个 radio,无选中
- 选 EM → 端点 15 个(精确)
- 选 Zhitu → 端点 12 个
- 点已选 EM 取消 → 端点恢复 31
- toggle on + 选 EM → inline list 只显示 EM
- 持久化(刷新页面后状态保留)
- console 无错误

---

## 8. 改动清单

```
stock_data/explorer/static/index.html
  ~ <div id="fetcherFilter"> 内部 input 从 checkbox 改 radio
  ~ toggle label 文案改 "Show only the selected fetcher in endpoint list"
  ~ state.fetcherFilter: string[] | null → string | null
  ~ epMatchesFetcherFilter: 改用 === 而非 includes
  ~ visibleFetchers: 改用 === 而非 includes,加 null 早返回
  ~ onchange handler: 只在 checked=true 时更新 state
  + 新增 click 拦截器:点已选 radio 取消
  ~ renderFetcherFilterUI: type=checkbox → type=radio,加 name="fetcher"
```

预期: 1 个文件, **+/- ~30 行**

---

## 9. 决策记录

- **单选 + 空选=全选**:用户明确要求,简化 UX
- **保留 toggle**:用户拍板 "保留并重定义"
- **可取消 radio**:点击已选 radio 取消(用 click 拦截 + setTimeout 0)
- **不写 first-visit**:沿用 Task 2 fix(避免 localStorage 锁死)
- **旧 array 迁移为 null**:本地开发项目,简单粗暴
- **不动 server / manifest / manager**:与前作一致
