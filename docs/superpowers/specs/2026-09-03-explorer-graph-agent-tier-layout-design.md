# Explorer Graph — Agent Tier-Layered Layout

> Spec for fixing the "agent nodes side-by-side, composed-of edges crossing peer agents" problem in the explorer Dependency Graph view's Flow layout. After adding `/agent/market-recap` (a 2nd-tier aggregator that depends on `/agent/market-context` + `/agent/market-stats` + `/indices/{code}/quote`), all 10 agent endpoints share the same top row and market-recap's purple `composed-of` edges pass through neighboring agent diamonds — both the hierarchy and the connection map become unreadable.

**Date**: 2026-09-03
**Status**: Draft
**Scope**: pure-frontend change to `stock_data/explorer/static/index.html`. No server-side change, no manifest schema change, no `@endpoint_meta` change, no .py change.

---

## 1. Background

The Dependency Graph view (Segmented control: Endpoints / Dependency Graph) renders three layouts via vis-network: **Section** (default), **Flow** (TB / LR), and **Force**.

In Flow layout, agent endpoints are visually distinguished by shape (diamond, purple `#af52de` border, `#f3e8ff` background, size 18) and lifted to the **top row** (TB) or **leftmost column** (LR). All agent endpoints share that one row regardless of how deeply nested their aggregation is:

| Tier 0 (leaf) | Tier 1 | Tier N |
|---|---|---|
| `market-context`, `market-stats`, `stocks/batch-profile`, `indices/batch-profile`, `boards/batch-profile`, `boards/stock-overlap`, `stocks/board-overlap`, `boards/filter-stocks`, `correlation/matrix` | `market-recap` (NEW) | (none today) |

Currently `market-recap` (tier 1) sits in the same row as `market-context` (tier 0). Its three `composed-of` purple edges fan out vertically toward `market-context`, `market-stats`, and `/indices/{code}/quote` — and because all 10 agent nodes share one row, those edges cross other agent diamonds on the way down. The hierarchy "which agent depends on which" is invisible.

This becomes worse with every new 2nd/3rd-tier aggregator (a near-certainty, given the 2026-09-02 slimming of `/agent/market-context` to its own re-usable contract and the recent pattern of "build composite endpoints from other agent endpoints").

## 2. Goal

Make the agent dependency hierarchy visually unambiguous in Flow layout, with **zero behavior change** for the Section and Force layouts and **zero visual change** in the no-2nd-tier-agent case (backward compatibility for the current state).

## 3. Non-Goals

- **Not** a server-side manifest change. `depends_on` is already declared per-endpoint; we only consume it.
- **Not** a Force-layout change. vis-network's physics engine handles Force; we leave its knobs alone.
- **Not** a Section-layout change. Section view is the default non-graph view (endpoint list grouped by section); unaffected.
- **Not** a new JS test infrastructure. The project has no JS tests today (`tests/` is pytest only); a one-function pure helper does not justify bootstrapping Jest/Vitest.

## 4. Design

### 4.1 `_agentTier` computation (`buildGraph`)

For each endpoint in `sec.id === "agent"`, compute `agentTier` = max chain length through `depends_on` references to other agent endpoints. Pure DFS with memoization; cycles fall back to tier 0 (worst-case matches current behavior, no regression).

```js
const agentPaths = new Set();
for (const sec of manifest.sections)
  if (sec.id === "agent")
    for (const ep of sec.endpoints) agentPaths.add(ep.path);

function agentTier(path, _stack = new Set()) {
  if (_stack.has(path)) return 0;              // cycle → 0, no regression
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

Then in the endpoint-node loop, attach the tier to each agent node:

```js
if (isAgent) {
  // ...existing shape/color/size...
  n._agentTier = agentTier(ep.path);
}
```

`_agentTier` is metadata only; Force layout and search/filter do not read it.

### 4.2 Flow layout (`layoutFlow`, TB branch)

Replace the single `agents: Node[]` with `agentTiers: Node[][]`, indexed by tier number. Stack from top (highest tier) to bottom (lowest tier).

```
maxTier  = max(...agentTiers.flat().map(n => n._agentTier))   // 0..N
y_tierN  = PAD + (maxTier - N) * TIER_H
rowTop   = PAD + maxTier * TIER_H + 170                        // section box top
```

`TIER_H = 60` (diamond node ~24 px + padding for label visibility).

Each populated tier uses the existing `floatRow(agentsTier, agentDesired, y_tierN, ...)` centroid-positioning logic — within a tier, ordering follows the average x of composed-of targets, exactly as today.

**Backward-compat guarantee**: when `maxTier === 0` (current state and any future state where no agent depends on another agent), the formula collapses to `y_tier0 = PAD` and `rowTop = PAD + 170`, **identical to today's layout, pixel for pixel**.

### 4.3 Flow layout (`layoutFlow`, LR branch)

Mirror of TB: tiers stack left-to-right, deepest tier leftmost.

```
agentColX(N) = PAD + N * (tierMaxW + 70)
```

Each tier uses `floatCol(agentsTier, aDesY, agentColX(N), PAD, yMax, 46)`. `tierMaxW` is computed per tier as `max(...label.length * ROW_W + 70)`. Section-box column and fetcher column shift right accordingly; width math already in the code reuses existing `contentW`.

### 4.4 Edge cases

| Case | Behavior |
|---|---|
| Agent depends on non-agent endpoint (e.g. `/indices/{code}/quote`) | Not counted toward tier — only cross-agent `depends_on` edges raise the tier |
| Agent self-loop (`depends_on` includes itself) | `_stack` set returns 0; falls into current single-row layout, no regression |
| Mutual agent dependency cycle | All members of the cycle evaluate to tier 0 (defensive fallback) |
| Empty tier (e.g. tier 2 has no agents today) | That row is not allocated; only populated tiers consume vertical space |
| Force layout | `buildGraph` still computes `_agentTier` (harmless metadata); `layoutFlow` is not called on the Force path — zero effect |
| Section view | No layout code runs; unaffected |
| Single agent (hypothetical edge case) | Floats alone at `y=PAD`, same as today's lone-agent behavior |

### 4.5 What this does NOT change

- composed-of edge color (`#af52de`, opacity 0.7), width (1.5 px), arrow style (`to`) — unchanged
- Endpoint shape / color / size rules — unchanged
- `flowLabelFor` short-label rule (last segment for agents) — unchanged
- `drawFlowBoxes` (only draws section group boxes, not agent tier rows) — unchanged
- `barnesHut` physics for Force — unchanged
- Manifest schema, `@endpoint_meta`, route handlers, server logic — unchanged
- Search / filter / focus / pin behavior — unchanged

## 5. Testing

### 5.1 No JS test framework

`stock_data/explorer/` has no test files; project-level `tests/` is pytest only. Adding Jest/Vitest for one pure helper is not justified by this change's scope.

### 5.2 Manual acceptance checklist

After implementation, start the server and verify in the explorer Dependency Graph → Flow view:

1. **Vertical alignment**: `GET market-recap` diamond sits in the tier-1 row, with its x-centroid within ±60 px of the `GET market-context` and `GET market-stats` diamond centers (per the existing `floatRow` centroid-positioning logic). The composed-of edge from market-recap to each tier-0 agent runs within a near-vertical band, not across the canvas.
2. **Edge direction**: market-recap's three purple composed-of edges run **strictly downward** into market-context, market-stats, and the indices section box. No purple edge crosses any other agent diamond.
3. **Force layout unchanged**: switching to Force produces visually similar output to before — no new overlapping clusters from tier metadata.
4. **Section view unchanged**: switching back to Endpoints view shows the same endpoint list as before.
5. **Single-tier regression test**: temporarily comment out all `depends_on` cross-references in `agent.py` (or build with a no-2nd-tier mock), reload, verify the layout is **pixel-identical** to the pre-change state. (Self-verification only; not a permanent fixture.)

### 5.3 Server-side test impact

None. The change is HTML-only and the server's pytest suite is not affected by explorer UI tweaks.

## 6. Files Touched

| File | Change |
|---|---|
| `stock_data/explorer/static/index.html` | `buildGraph`: add `agentPaths` set + `agentTier()` DFS + `_agentTier` on agent nodes. `layoutFlow`: replace single `agents` array with `agentTiers: Node[][]`; in TB branch, iterate tiers top-to-bottom using the formula in §4.2; in LR branch, mirror left-to-right per §4.3. Add `TIER_H` constant. |

No other file is modified.

## 7. Migration / Rollout

- **No data migration**. No new env var. No new endpoint. No new file.
- **Rollout**: edit the HTML, reload the page (CDN-served `vis-network` will pick up on next page load). Cache-bust by hard-reload if needed (`Cmd+Shift+R`).
- **Rollback**: revert the HTML edit. Zero persistent state means zero rollback cost.

## 8. Future Extensions (not in this PR)

- **Generalize tier rows to other layered relations** (e.g. fetcher chains): same machinery could later elevate multi-hop fetcher dependencies, but no current fetcher chain warrants it.
- **Optional tier-1 row label** ("meta-agents") for discoverability: deferred — diamonds + position + edge color carry enough signal today.
- **Per-tier color tint** (e.g. deeper tier = darker diamond border): explicitly out of scope. Keeps the diamond color a single signal reserved for "this is an agent endpoint".
