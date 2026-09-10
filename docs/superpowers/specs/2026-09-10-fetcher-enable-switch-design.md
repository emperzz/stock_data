# Per-Fetcher Enable Switch

**Date:** 2026-09-10
**Status:** Approved (design)
**Scope:** `stock_data/data_provider/base.py`, `stock_data/data_provider/manager.py`,
`stock_data/data_provider/utils/normalize.py`, `.env.example`, docs.

## Problem

There is no way to turn a fetcher off. Today the only knobs are:

| Knob | Where | What it can do | Why it is insufficient |
|---|---|---|---|
| `<NAME>_PRIORITY` | class attr, 13 fetchers | Reorders the failover chain | Cannot *remove* a source. Reordering to last still calls it when the chain reaches the end. |
| `is_available()` | `base.py:129` / `:299` | Implicit gate via missing token / SDK import failure | Only expressible as "don't configure the token". Whole-source granularity, and conflates "I don't have credentials" with "I don't want this source". |
| Circuit breaker | `core/types.py` | Runtime temporary removal | Auto-recovers, not configurable, and **not consulted by `_with_source`**. |

Two concrete gaps that priority cannot close:

1. **Sole-provider capabilities.** EastMoney is the only `STOCK_NEWS` provider;
   Cninfo is the main `ANNOUNCEMENT` provider. For these, "last in the chain"
   still means "called".
2. **Board endpoints ignore priority entirely.** `_with_source()` (`manager.py:214`)
   resolves by slug through `_slug_index`. There is no ordering to manipulate, so
   a source cannot be removed from the board surface by any priority value.

## Non-goal: not importing the package

`data_provider/__init__.py` eagerly re-exports all 12 fetcher classes
(`from .fetchers.akshare import AkshareFetcher`, …), and `server.py` plus a large
part of the test suite import from that surface. "Disabled" therefore means
**not instantiated and not registered**, *not* "module never imported". Making
`_ENABLED=false` skip the import would require dismantling the public re-export
surface — disproportionate to the goal, and it would break
`explorer/manifest.py:255`, which needs the class objects to describe disabled
sources. This boundary is deliberate and should be stated in `.env.example`.

## Design

### 1. `BaseFetcher.is_enabled()` — one declaration for all fetchers

Add to `base.py`:

```python
@classmethod
def enabled_env_var(cls) -> str:
    """Env var that enables/disables this fetcher, e.g. "ZHITU_ENABLED"."""
    return f"{source_slug(cls.name).upper()}_ENABLED"

@classmethod
def is_enabled(cls) -> bool:
    """True unless <SLUG>_ENABLED is explicitly falsy.

    Read on EVERY call (not at class-definition time) so tests can
    monkeypatch.setenv and observe the change without importlib.reload.
    """
    raw = os.getenv(cls.enabled_env_var(), "true").strip().lower()
    return raw not in ("false", "0", "no", "off")
```

`source_slug()` is a new helper in `utils/normalize.py`, extracted verbatim from
`DataFetcherManager._derive_slug` (`manager.py:157`) so the two cannot drift:
strip a trailing `Fetcher` (case-insensitive), lowercase. `EastMoneyFetcher` →
`eastmoney`, `ZzshareFetcher` → `zzshare`, `ThsFetcher` → `ths`.

This makes the env naming exactly symmetric with the existing 13 `*_PRIORITY`
vars (`ZHITU_PRIORITY` ↔ `ZHITU_ENABLED`). `_derive_slug` becomes a thin
delegation to `source_slug` — 3 lines, no behavior change.

**Why a classmethod and not a class attribute** (the `priority` pattern):
`priority = int(os.getenv(...))` is evaluated once at module-import time, which
is why `tests/test_zzshare_fetcher.py:59-80` has to verify the env read by
source inspection instead of asserting behavior. Every call re-reading the env
makes the switch directly testable. It also means adding a fetcher requires no
new line — a missing `enabled = …` attribute on a hand-written class attribute
approach would silently mean "always enabled".

### 2. The gate — `create_default_manager()` (`manager.py:1532`)

```python
for cls in fetcher_classes:
    if not cls.is_enabled():
        logger.info(f"{cls.__name__} disabled by {cls.enabled_env_var()}")
        continue
    instance = cls()
    if instance.is_available():
        manager.add_fetcher(instance)
        logger.info(f"{cls.__name__} added")
    else:
        logger.info(f"{cls.__name__} skipped")
```

This is the **only** registration site, and every downstream routing path reads
the registered list:

- `_filter_by_capability(market, capability)` (`manager.py:140`) → all
  `_with_failover`-based capability routing.
- `_refresh_index()` → `_fetchers_by_name` + `_slug_index` → `_with_source()`
  (`manager.py:214`) → all board endpoints.

One gate therefore removes the source from every routing surface at once. Order
matters: the `is_enabled()` check comes **before** `cls()` instantiation, so a
disabled source is never constructed (no SDK init side effect, no token read).

### 3. Three co-readers of `is_enabled()`

**a. `unavailable_reason()` (`base.py:139`) — required, not optional.**
`explorer/manifest.py:255 _resolve_fetchers` enumerates **all `BaseFetcher`
subclasses**, not the registered instances, and fills each row's `reason` from
`unavailable_reason()`. Add a branch ahead of the token check:

```python
if not self.is_enabled():
    return f"disabled by {self.enabled_env_var()}=false"
```

Without it, a disabled source renders in the explorer as "ZHITU_TOKEN not set",
sending whoever is debugging to the wrong file.

**b. `get_fetcher()` / `_with_source()` (`manager.py:179` / `:214`).**
A slug lookup for a disabled source currently falls through to the generic
"no fetcher matches source" error. Because the reason is knowable, the error
must say so. Resolve by scanning `BaseFetcher` subclasses for a name whose slug
matches *and* which reports `is_enabled() == False`, then raise `ValueError`
with:

```
source 'zhitu' is disabled by ZHITU_ENABLED=false
```

`api/routes/errors.py::map_errors` already maps `ValueError` → 400, and
`boards.py` already catches `ValueError` at several sites, so no new HTTP
plumbing is needed. This is the whole reason for choosing a distinguishable
error: "disabled" and "typo" must be separable in the logs.

**c. Manifest presentation.** The row stays, with `available: false` and the
reason from (a). Hiding it would remove the only UI surface where "why did my
source disappear" can be answered.

### 4. Explicit boundary: `/control/fetcher-test` is NOT gated

`POST /control/fetcher-test` instantiates the class on demand and bypasses
manager routing — this is documented, intentional behavior. Keeping the bypass
is a feature: an operator can verify an upstream source works *before* deciding
to enable it. The probe path must keep working for a disabled source.

## Coupling warnings that must land in `.env.example`

These are not "one fewer source" cases; they are partial outages:

- **`THS_ENABLED=false` breaks the entire board persistence path.** The board
  cache is keyed on `source='ths'` regardless of who served the request, and
  `?source=zzshare` on board endpoints is aliased to `ths`. Nothing else can
  serve those routes; `?source=` cannot rescue it.
- **`ZZSHARE_ENABLED=false` breaks the internal primary of the board
  `include_quote=false` chain.** `source='ths'` + `include_quote=false` runs a
  ZZSHARE-primary → THS-fallback chain internally; disabling ZZSHARE removes the
  primary from a chain the caller never named.
- **`tools/build_membership_index.py`** is the other direct consumer of
  `manager.*`. Disabling a source makes the membership bootstrap cover fewer
  sources — intended, but must be known before someone reads a thinner
  membership index as a data bug.

Board routes use `_with_source()` and are **not** CircuitBreaker-integrated, so
a disabled source there surfaces as a 400 (per 3b), never as CB state.

## Testing

New `tests/test_fetcher_enable_switch.py`:

1. `is_enabled()` defaults to `True` with the env var unset.
2. All four falsy spellings (`false` / `0` / `no` / `off`) return `False`;
   mixed case and surrounding whitespace tolerated (`" FALSE "` → `False`).
3. Any other value (including `"true"`, `""`, garbage) returns `True`.
4. `enabled_env_var()` derives from the class name: `ZhituFetcher` →
   `ZHITU_ENABLED`, `EastMoneyFetcher` → `EASTMONEY_ENABLED`,
   `ZzshareFetcher` → `ZZSHARE_ENABLED`.
5. `create_default_manager()` with `ZHITU_ENABLED=false` does **not** register
   ZhituFetcher, and `_slug_index` has no `zhitu` key. `is_available` is patched
   to `True` so the assertion isolates the enable switch and does not depend on
   whether `ZHITU_TOKEN` happens to be present in the test environment.
6. `manager.get_fetcher("zhitu")` raises `ValueError` whose message contains
   `ZHITU_ENABLED`.
7. `unavailable_reason()` distinguishes disabled from token-missing.
8. **Regression (the important one):** with no `*_ENABLED` var set,
   `create_default_manager()` registers exactly the fetchers whose
   `is_available()` is `True` — i.e. the new gate drops nobody. Phrasing it
   against `is_available()` rather than against a hardcoded name list keeps the
   test environment-independent (which fetchers are available depends on tokens
   and installed SDKs) while still catching a wrong default: if the default
   parsed as falsy, this test would register zero fetchers and fail loudly.

`tests/test_zzshare_fetcher.py::TestZzshareFetcherMetadata` gains an `is_enabled`
default assertion alongside `test_priority_default`, keeping the two metadata
switches covered in the same place.

Test isolation: `is_enabled()` reads the env per call, so a `monkeypatch`
autouse fixture clearing `*_ENABLED` is sufficient — no module reload, no class
identity churn.

## Out of scope

- Runtime toggling without a restart. The switch is read at
  `create_default_manager()` time; changing it requires a process restart, same
  as all 22 existing env knobs. No `/control/*` write endpoint.
- A single `DISABLED_FETCHERS=a,b` list variable (rejected: the per-fetcher
  form is what was asked for, and it makes the disabled set self-documenting in
  `.env.example`).
- Making `_ENABLED=false` skip the module import — see Non-goal above.
- Any change to `DataCapability` or `CAPABILITY_TO_METHOD`; this is not a new
  capability, so `tests/test_capability_method_map.py` is untouched.
