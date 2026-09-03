# Explorer Graph — Agent Tier-Layered Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the explorer Dependency Graph's Flow layout show agent endpoints as a layered hierarchy (deepest tier on top in TB / leftmost in LR) so `composed-of` edges flow strictly downward without crossing peer agent nodes.

**Architecture:** Pure-frontend change to a single static HTML file. Compute `_agentTier` per agent endpoint via DFS over `depends_on` in `buildGraph`; refactor `layoutFlow` to lay out agent nodes in tier-stacked rows (TB) or tier-stacked columns (LR) instead of a single row/column. Force and Section layouts are untouched.

**Tech Stack:** Vanilla JS (no framework), vis-network 9.x (CDN), FastAPI static-served HTML.

## Global Constraints

These constraints apply to every task. Read before starting.

- **Single file modified**: `stock_data/explorer/static/index.html`. No .py, no manifest schema, no `@endpoint_meta`, no route changes.
- **No JS test framework**. The project has no Jest/Vitest/Node test runner for this HTML. Verification is manual visual checks against the 5-step acceptance checklist in `docs/superpowers/specs/2026-09-03-explorer-graph-agent-tier-layout-design.md` §5.2.
- **Backward compatibility is mandatory**: when no agent endpoint depends on another agent endpoint (`maxTier === 0`), the layout must produce **pixel-identical** output to today's layout. This is provable from the formulas (see Task 2/3 verify steps); runtime verification can be done by temporarily commenting out `market-recap`'s cross-agent `depends_on` entries.
- **No new constants pollution**: use `TIER_H = 60` (TB) and `TIER_GAP = 70` (LR). Both are local to `layoutFlow`. No globals.
- **Frequent commits**: each task ends with a `git commit`. Use the project's existing commit-message convention (see recent `git log` for style; conventional commits with `feat(explorer):` / `fix(explorer):` prefix).
- **Server restart not required**: the HTML is static. After saving, **hard-reload** the explorer page (`Ctrl+Shift+R` / `Cmd+Shift+R`) to bypass the browser cache. If using a separate test server on port 8888, ensure it's running first per the project's `run` conventions.
- **Do not add tests or test files**. Do not introduce `node_modules`, `package.json`, or `vitest.config.*`. If the verify step in any task feels weak, add a manual code-trace explanation in the commit message — do not introduce new tooling.

---

## File Map

| File | Touched by | Role |
|---|---|---|
| `stock_data/explorer/static/index.html` | Tasks 1, 2, 3 | Contains `buildGraph`, `layoutFlow`, `flowLabelFor` — the only functions modified. |

No new files. No deleted files.

---

## Task 1: Add `_agentTier` metadata in `buildGraph`

**Files:**
- Modify: `stock_data/explorer/static/index.html:1062-1089` (endpoint node loop) and `stock_data/explorer/static/index.html:1047` (after `epByPath` population, before endpoint loop)

**Interfaces:**
- Consumes: `manifest.sections[]`, `epByPath` (existing, lines 1047-1059)
- Produces: `agentPaths: Set<string>` (module-local inside `buildGraph`); `agentTier(path: string, _stack?: Set<string>): number` (closure inside `buildGraph`); `_agentTier: number` attached to each agent node in the `nodes` array

- [ ] **Step 1: Read the surrounding code**

Open `stock_data/explorer/static/index.html` and locate:
- Line 1047: `const epByPath = {};` (first pass collects endpoint paths)
- Lines 1054-1059: the first pass loop that populates `epByPath`
- Lines 1062-1089: the second pass that builds endpoint nodes (where `_agentTier` gets attached)
- Lines 1091-1104: the fetcher node loop (must come AFTER our edits; we are only inserting before line 1062)

- [ ] **Step 2: Add `agentPaths` set collection after `epByPath` population**

Right after the closing `}` of the first-pass loop (after line 1059, before line 1062), insert:

```js
      // 收集所有 agent 端点路径, 用于后续计算 _agentTier。
      // 仅 cross-agent depends_on 计入 tier(对非 agent 的依赖不影响)。
      const agentPaths = new Set();
      for (const sec of manifest.sections) {
        if (sec.id === "agent") {
          for (const ep of sec.endpoints) agentPaths.add(ep.path);
        }
      }

      // DFS + memo 算 tier。环检测: _stack 命中返回 0(降级到旧单行行为)。
      function agentTier(path, _stack = new Set()) {
        if (_stack.has(path)) return 0;
        const ep = epByPath[path];
        if (!ep || !agentPaths.has(path)) return 0;
        let max = 0;
        _stack.add(path);
        for (const d of (ep.depends_on || [])) {
          if (d.kind === "endpoint" && agentPaths.has(d.target_path)) {
            max = Math.max(max, agentTier(d.target_path, _stack) + 1);
          }
        }
        _stack.delete(path);
        return max;
      }
```

Indent matches the surrounding code (6 spaces inside `buildGraph`).

- [ ] **Step 3: Attach `_agentTier` to agent endpoint nodes**

In the endpoint node creation loop, change the `if (isAgent) { ... }` branch (lines 1070-1071) to compute the tier, and change the `nodes.push({...})` call (lines 1078-1087) to attach the tier.

Before (lines 1070-1087):
```js
          if (isAgent) {
            shape = "diamond"; color = { border: "#af52de", background: "#f3e8ff", highlight: { border: "#af52de", background: "#e9d5ff" } }; size = 18;
          } else if (isPure) {
            shape = "dot"; color = { background: textMuted, border: textMuted }; size = 8;
          } else {
            shape = "dot"; const c = ep.method === "POST" ? accentPost : accent; color = { background: c, border: c }; size = 14;
          }
          const label = `${ep.method} ${ep.path.length > 28 ? ep.path.slice(0, 25) + "…" : ep.path}`;
          nodes.push({
            id: "ep:" + ep.path,
            label,
            shape,
            color,
            size,
            title: `${ep.method} ${ep.path}\n${ep.summary || ""}`,
            group: "endpoint",
            _ep: ep,
          });
```

After:
```js
          let agentTierValue = 0;
          if (isAgent) {
            shape = "diamond"; color = { border: "#af52de", background: "#f3e8ff", highlight: { border: "#af52de", background: "#e9d5ff" } }; size = 18;
            agentTierValue = agentTier(ep.path);
          } else if (isPure) {
            shape = "dot"; color = { background: textMuted, border: textMuted }; size = 8;
          } else {
            shape = "dot"; const c = ep.method === "POST" ? accentPost : accent; color = { background: c, border: c }; size = 14;
          }
          const label = `${ep.method} ${ep.path.length > 28 ? ep.path.slice(0, 25) + "…" : ep.path}`;
          nodes.push({
            id: "ep:" + ep.path,
            label,
            shape,
            color,
            size,
            title: `${ep.method} ${ep.path}\n${ep.summary || ""}`,
            group: "endpoint",
            _ep: ep,
            _agentTier: agentTierValue,
          });
```

Non-agent nodes still get `_agentTier: 0` (harmless; layout code only reads it for `sid === "agent"`).

- [ ] **Step 4: Manual verify (no layout change expected yet)**

Start the test server (or use the running one), then:

1. Hard-reload the explorer page (`Ctrl+Shift+R`).
2. Open DevTools → Console. Verify **no JS errors** (no `ReferenceError`, no `TypeError`).
3. Switch to Dependency Graph view, then to Flow layout. The layout should look **identical** to the pre-change state — diamonds still in one row, sections still in middle, fetchers still at bottom. This task only adds metadata; layout changes happen in Tasks 2 and 3.
4. Optional sanity check: in DevTools console, evaluate
   ```js
   vis.DataSet.prototype // confirm vis loaded
   ```
   Then hover any agent diamond and confirm tooltip still shows the full path/summary.

If console shows errors, stop and re-check Step 3's `nodes.push` for typos.

- [ ] **Step 5: Commit**

```bash
git add stock_data/explorer/static/index.html
git commit -m "feat(explorer): attach _agentTier metadata to agent endpoint nodes"
```

---

## Task 2: Tiered layout in `layoutFlow` TB branch

**Files:**
- Modify: `stock_data/explorer/static/index.html:909-916` (replace `agents` collection with `agentTiers`)
- Modify: `stock_data/explorer/static/index.html:937-962` (TB branch — use tier rows)

**Interfaces:**
- Consumes: `agentTiers: { tier: number; list: Node[] }[]` (populated tiers, sorted by tier ASC); `TIER_H = 60`
- Produces: x/y coordinates on every agent node in TB mode

- [ ] **Step 1: Read the surrounding code**

Open `stock_data/explorer/static/index.html` and locate:
- Lines 909-916: `const agents = []; const cols = new Map(); for (const n of epNodes) {...}` — replace `agents` with `agentTiers`
- Lines 937-962: the `if (isTB) { ... }` branch — refactor to iterate tiers
- Lines 952-954: the three references to `agents` inside the TB branch (replace with per-tier iteration)

- [ ] **Step 2: Replace `agents` array with `agentTiers` collection**

Before (lines 909-916):
```js
      const agents = [];
      const cols = new Map();                    // sectionId -> endpoint node[]
      for (const n of epNodes) {
        const sid = p2s[n._ep.path] || "?";
        n.label = flowLabelFor(n._ep, sid);      // 布局宽度与显示共用同一短标签
        if (sid === "agent") agents.push(n);
        else { if (!cols.has(sid)) cols.set(sid, []); cols.get(sid).push(n); }
      }
```

After:
```js
      const agentTiers = [];                     // tier index → nodes[] (稀疏; 仅在有节点时占槽)
      const cols = new Map();                    // sectionId -> endpoint node[]
      for (const n of epNodes) {
        const sid = p2s[n._ep.path] || "?";
        n.label = flowLabelFor(n._ep, sid);      // 布局宽度与显示共用同一短标签
        if (sid === "agent") {
          const t = n._agentTier || 0;
          while (agentTiers.length <= t) agentTiers.push([]);
          agentTiers[t].push(n);
        }
        else { if (!cols.has(sid)) cols.set(sid, []); cols.get(sid).push(n); }
      }
      const populatedTiers = agentTiers
        .map((list, i) => ({ tier: i, list }))
        .filter(t => t.list.length);
      const maxAgentTier = populatedTiers.length ? populatedTiers[populatedTiers.length - 1].tier : 0;
```

- [ ] **Step 3: Refactor the TB branch to iterate tiers**

Before (lines 937-962):
```js
      if (isTB) {
        // R1: 分组框从左到右横排(框内端点竖排)。
        const rowTop = PAD + 170;                // 顶部留走廊画 composed-of
        let x = PAD;
        for (const [sid, list] of cols) {
          const w = boxWOf(list), h = boxHOf(list);
          const b = { sid, x, y: rowTop, w, h, eps: list };
          flowBoxes.push(b);
          placeInBox(b, list);
          x += w + 58;                           // 框间距
        }
        const boxRight = Math.max(PAD, x - 58);
        const maxBoxBottom = flowBoxes.length
          ? Math.max(...flowBoxes.map(b => b.y + b.h)) : rowTop + HEAD;
        const contentW = Math.max(PAD * 2 + agents.length * 120, boxRight + PAD);
        const agentDesired = n => { const t = tgtOf(n); return t.length ? mean(t.map(q => q.x)) : contentW / 2; };
        floatRow(agents, agentDesired, PAD, n => n.label.length * ROW_W + 60, PAD, contentW - PAD, 60);
        centerRow(agents, n => n.label.length * ROW_W + 60, PAD, contentW - PAD);
        const fxY = maxBoxBottom + 210;
        const fxDesired = n => { const s = srcOf(n); return s.length ? mean(s.map(q => q.x)) : contentW / 2; };
        floatRow(fxNodes, fxDesired, fxY, n => n.label.length * 9 + 80, PAD, contentW - PAD, 50);
        centerRow(fxNodes, n => n.label.length * 9 + 80, PAD, contentW - PAD);
        const h = fxY + 80;
        nodes.push(...anchorOf(contentW, h));
        return { w: contentW, h };
      }
```

After:
```js
      if (isTB) {
        // agent 按 tier 由上至下堆叠, 最高 tier 在 y=PAD; maxTier=0 时与旧版像素一致。
        const TIER_H = 60;
        const rowTop = PAD + maxAgentTier * TIER_H + 170;   // 顶部留走廊画 composed-of
        // R1: 分组框从左到右横排(框内端点竖排)。
        let x = PAD;
        for (const [sid, list] of cols) {
          const w = boxWOf(list), h = boxHOf(list);
          const b = { sid, x, y: rowTop, w, h, eps: list };
          flowBoxes.push(b);
          placeInBox(b, list);
          x += w + 58;                           // 框间距
        }
        const boxRight = Math.max(PAD, x - 58);
        const maxBoxBottom = flowBoxes.length
          ? Math.max(...flowBoxes.map(b => b.y + b.h)) : rowTop + HEAD;
        const totalAgentCount = populatedTiers.reduce((s, t) => s + t.list.length, 0);
        const contentW = Math.max(PAD * 2 + totalAgentCount * 120, boxRight + PAD);
        const agentDesired = n => { const t = tgtOf(n); return t.length ? mean(t.map(q => q.x)) : contentW / 2; };
        for (const { tier, list } of populatedTiers) {
          const y = PAD + (maxAgentTier - tier) * TIER_H;
          floatRow(list, agentDesired, y, n => n.label.length * ROW_W + 60, PAD, contentW - PAD, 60);
          centerRow(list, n => n.label.length * ROW_W + 60, PAD, contentW - PAD);
        }
        const fxY = maxBoxBottom + 210;
        const fxDesired = n => { const s = srcOf(n); return s.length ? mean(s.map(q => q.x)) : contentW / 2; };
        floatRow(fxNodes, fxDesired, fxY, n => n.label.length * 9 + 80, PAD, contentW - PAD, 50);
        centerRow(fxNodes, n => n.label.length * 9 + 80, PAD, contentW - PAD);
        const h = fxY + 80;
        nodes.push(...anchorOf(contentW, h));
        return { w: contentW, h };
      }
```

- [ ] **Step 4: Manual verify in TB Flow layout**

1. Hard-reload the explorer page (`Ctrl+Shift+R`).
2. Open DevTools → Console. Verify no JS errors.
3. Click Dependency Graph → Flow (the default direction is TB).
4. **Verify market-recap above market-context/market-stats**:
   - Locate the `GET market-recap` diamond. It should sit in a row **above** the row containing `GET market-context` and `GET market-stats`.
   - All other agent diamonds (`market-stats`, `stocks/batch-profile`, `indices/batch-profile`, `boards/batch-profile`, `boards/stock-overlap`, `stocks/board-overlap`, `boards/filter-stocks`, `correlation/matrix`, `market-context`) should be in a single row **below** market-recap.
5. **Verify edges are vertical**: the 3 purple composed-of edges from market-recap should run **downward** into `market-context`, `market-stats`, and the indices section box — they should NOT cross any other agent diamond.
6. **Verify section boxes and fetchers are intact**: section group boxes still in the middle row, fetchers still at the bottom.

If market-recap is NOT above market-context/market-stats, or if edges cross other agents, stop and re-check the formula in Step 3.

- [ ] **Step 5: Verify maxTier=0 backward compatibility (code trace + optional runtime)**

Code trace (always required, document in commit message):

When no agent endpoint depends on another agent endpoint, `populatedTiers` contains exactly one entry: `{ tier: 0, list: [...all 10 agents] }`. Therefore `maxAgentTier = 0`. The TB branch then evaluates:
- `rowTop = PAD + 0 * TIER_H + 170 = PAD + 170` ✓ (same as old)
- `totalAgentCount = 10` (same as `agents.length` in old code) ✓
- `contentW = Math.max(PAD * 2 + 10 * 120, boxRight + PAD)` ✓ (same as old)
- The single tier loop iterates once, calling `floatRow(list, agentDesired, PAD, ...)` and `centerRow(list, ..., PAD, ...)` — y argument is `PAD + (0 - 0) * TIER_H = PAD` ✓ (same as old)

Result: **pixel-identical to pre-change layout** when `maxTier === 0`.

Optional runtime check (skip if trace is convincing): temporarily edit `stock_data/api/routes/agent.py` to comment out the cross-agent `depends_on` entries inside `get_market_recap`'s `@endpoint_meta(...)` (keep only `"/api/v1/indices/{code}/quote"`), reload the page, verify all 10 agents are in a single row identical to today's layout. **Revert the edit before committing.**

- [ ] **Step 6: Commit**

```bash
git add stock_data/explorer/static/index.html
git commit -m "feat(explorer): tier-layered agent layout in flow TB branch"
```

---

## Task 3: Tiered layout in `layoutFlow` LR branch

**Files:**
- Modify: `stock_data/explorer/static/index.html:964-991` (LR branch — replace single agent column with tier columns)

**Interfaces:**
- Consumes: `populatedTiers` (from Task 2), `TIER_GAP = 70`
- Produces: x/y coordinates on every agent node in LR mode

- [ ] **Step 1: Read the surrounding code**

Open `stock_data/explorer/static/index.html` and locate:
- Lines 964-991: the LR branch (everything after the `if (isTB) { ... return { ... }; }` block)
- Lines 965-966: `const agentColW = ...` — replace with tier-position calculation
- Lines 982-983: `floatCol(agents, ...)` and `centerCol(agents, ...)` — replace with per-tier iteration

- [ ] **Step 2: Refactor the LR branch to use tier columns**

Before (lines 964-991):
```js
      // LR: 中间层 section 框改为纵向堆叠(从上到下), 各框仍是端点竖列。
      const agentColW = agents.length
        ? Math.max(...agents.map(n => n.label.length * ROW_W + 70)) : 120;
      const boxColX = PAD + agentColW + 70;
      let cy = PAD;
      let colMaxW = 10;
      for (const [sid, list] of cols) {
        const w = boxWOf(list), h = boxHOf(list);
        const b = { sid, x: boxColX, y: cy, w, h, eps: list };
        flowBoxes.push(b);
        placeInBox(b, list);
        colMaxW = Math.max(colMaxW, w);
        cy += h + 46;
      }
      const fxX = boxColX + colMaxW + 180;
      const fxMaxW = fxNodes.length ? Math.max(...fxNodes.map(n => n.label.length * 9 + 80)) : 220;
      const yMax = Math.max(cy - 46 + HEAD, PAD + 60);
      const aDesY = n => { const t = tgtOf(n); return t.length ? mean(t.map(q => q.y)) : PAD + HEAD; };
      floatCol(agents, aDesY, PAD, PAD, yMax, 46);
      centerCol(agents, () => 40, PAD, yMax);
      const fDesY = n => { const s = srcOf(n); return s.length ? mean(s.map(q => q.y)) : PAD + HEAD; };
      floatCol(fxNodes, fDesY, fxX, PAD, yMax, 36);
      centerCol(fxNodes, () => 40, PAD, yMax);
      const colBottom = a => a.length ? Math.max(...a.map(n => n.y + 40)) : 0;
      const contentW = fxX + fxMaxW + PAD;
      const contentH = Math.max(yMax, colBottom(agents), colBottom(fxNodes)) + PAD;
```

After:
```js
      // LR: agent tier 由左至右展开, 最高 tier 在最左(per spec §4.3 deepest-first);
      //     maxAgentTier=0 时 .reverse() 无操作, 单 tier 仍在 x=PAD, 像素一致。
      const TIER_GAP = 70;
      let agentColCursor = PAD;
      // populatedTiers 已按 tier ASC 排序; 反转后最深 tier 在最左。
      const tierPositions = populatedTiers.slice().reverse().map(({ tier, list }) => {
        // 严格匹配 OLD 代码(无 120 floor)以保证 maxTier=0 下 pixel-identical。
        // 空 list 的 120 fallback 是死分支(populatedTiers 已 filter),但保留作为防御。
        const w = list.length
          ? Math.max(...list.map(n => n.label.length * ROW_W + 70))
          : 120;
        const pos = { tier, list, x: agentColCursor, w };
        agentColCursor += w + TIER_GAP;
        return pos;
      });
      const agentColW = tierPositions.length
        ? agentColCursor - PAD - TIER_GAP
        : 120;
      const boxColX = PAD + agentColW + TIER_GAP;
      let cy = PAD;
      let colMaxW = 10;
      for (const [sid, list] of cols) {
        const w = boxWOf(list), h = boxHOf(list);
        const b = { sid, x: boxColX, y: cy, w, h, eps: list };
        flowBoxes.push(b);
        placeInBox(b, list);
        colMaxW = Math.max(colMaxW, w);
        cy += h + 46;
      }
      const fxX = boxColX + colMaxW + 180;
      const fxMaxW = fxNodes.length ? Math.max(...fxNodes.map(n => n.label.length * 9 + 80)) : 220;
      const yMax = Math.max(cy - 46 + HEAD, PAD + 60);
      const aDesY = n => { const t = tgtOf(n); return t.length ? mean(t.map(q => q.y)) : PAD + HEAD; };
      for (const { list, x } of tierPositions) {
        floatCol(list, aDesY, x, PAD, yMax, 46);
        centerCol(list, () => 40, PAD, yMax);
      }
      const fDesY = n => { const s = srcOf(n); return s.length ? mean(s.map(q => q.y)) : PAD + HEAD; };
      floatCol(fxNodes, fDesY, fxX, PAD, yMax, 36);
      centerCol(fxNodes, () => 40, PAD, yMax);
      const colBottom = a => a.length ? Math.max(...a.map(n => n.y + 40)) : 0;
      const contentW = fxX + fxMaxW + PAD;
      const contentH = Math.max(yMax, colBottom(populatedTiers.flatMap(t => t.list)), colBottom(fxNodes)) + PAD;
```

Note the one-character change on the last line: `colBottom(agents)` → `colBottom(populatedTiers.flatMap(t => t.list))`. `populatedTiers.flatMap(t => t.list)` is exactly the old `agents` array when `maxTier === 0`.

- [ ] **Step 3: Manual verify in LR Flow layout**

1. Hard-reload the explorer page.
2. Open DevTools → Console. Verify no JS errors.
3. In Dependency Graph → Flow, click the **LR** segmented button (in the graph direction toolbar) to switch from TB to LR.
4. **Verify market-recap is the leftmost agent column**: the `GET market-recap` diamond should appear in a vertical column **left of** the column containing the other 9 agent diamonds.
5. **Verify section boxes shift right** (because agent area now occupies two columns instead of one). The market-recap column's width pushes the section-box column further right.
6. **Verify edges are horizontal-leaning** (in LR mode, composed-of edges run roughly rightward toward the section boxes — they should NOT cross peer agent diamonds).
7. Switch back to TB (default) — verify TB layout still works as in Task 2.

If market-recap is NOT leftmost, or if section boxes are not shifted right, stop and re-check the formula in Step 2.

- [ ] **Step 4: Verify Force and Section layouts are unaffected**

1. Click the **Force** button in the graph layout toolbar. Verify the force-directed physics simulation looks identical to before (vis-network should still produce a stable cluster of agents + sections + fetchers).
2. Click the **Endpoints** button in the top-level view switcher (not the graph toolbar). Verify the endpoint list view is unchanged.
3. Switch back to Flow view to leave the page in a normal state.

If any of these layouts is broken (vis-network fails to render, nodes overlap weirdly, list is empty), stop and investigate — the change should be 100% confined to `layoutFlow`'s TB and LR branches; Force uses vis-network physics (no `layoutFlow` call), Section view never calls `layoutFlow`.

- [ ] **Step 5: Commit**

```bash
git add stock_data/explorer/static/index.html
git commit -m "feat(explorer): tier-layered agent layout in flow LR branch"
```

---

## Self-Review

**1. Spec coverage:**

| Spec section | Task |
|---|---|
| §1 Background | (informational, no implementation) |
| §2 Goal | Tasks 2 + 3 |
| §3 Non-Goals | (enforced by global constraints) |
| §4.1 `_agentTier` computation | Task 1 |
| §4.2 Flow layout TB | Task 2 |
| §4.3 Flow layout LR | Task 3 |
| §4.4 Edge cases | Tasks 1 (cycle), 2 (maxTier=0), 3 (empty populatedTiers) |
| §4.5 What does NOT change | Tasks 2-4 verify steps explicitly check composed-of style, endpoint shapes, Section view, Force layout |
| §5 Testing | Tasks 2 + 3 manual verify steps; spec §5.2 step 5 (maxTier=0 trace) covered in Task 2 Step 5 |
| §6 Files Touched | Only `index.html`, confirmed |
| §7 Migration / Rollout | No new files, no env vars, no DB — only HTML edit |
| §8 Future Extensions | (out of scope) |

**2. Placeholder scan:**

- "TBD" / "TODO": none
- "implement later": none
- "similar to Task N" with code elided: none (full code blocks in every step)
- "add appropriate error handling": none
- "write tests for the above": explicitly forbidden by global constraints; replaced with manual verify steps

**3. Type consistency:**

- `agentTiers: Node[][]` — Task 2 Step 2 definition
- `populatedTiers: { tier: number; list: Node[] }[]` — Task 2 Step 2, consumed by Tasks 2 & 3
- `_agentTier: number` on Node — Task 1 Step 3, read in Task 2 Step 2
- `tierPositions: { tier: number; list: Node[]; x: number; w: number }[]` — Task 3 Step 2, used only within Task 3

All cross-task references match.

---

## Done Criteria

- [ ] Three commits applied to the working tree.
- [ ] Hard-reload the explorer page → Dependency Graph → Flow TB → market-recap is above market-context/market-stats; composed-of edges are vertical.
- [ ] Flow LR → market-recap is the leftmost agent column; section boxes shifted right.
- [ ] Force and Section layouts unchanged.
- [ ] No JS errors in DevTools console in any layout.
- [ ] maxTier=0 backward compatibility verified by code trace (Task 2 Step 5).
