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

### 3. Four co-readers of `is_enabled()`

**a. `unavailable_reason()` — required, not optional, and it must be final.**
`explorer/manifest.py:255 _resolve_fetchers` enumerates **all `BaseFetcher`
subclasses**, not the registered instances, and fills each row's `reason` from
`unavailable_reason()`. Without a branch, a disabled source renders as
"ZHITU_TOKEN not set", sending whoever is debugging to the wrong file.

There are **six** `unavailable_reason()` definitions today, four of which are
per-fetcher overrides that never call the base:

| File:line | Class |
|---|---|
| `base.py:139` | `SDKFetcherMixin` |
| `base.py:285` | `BaseFetcher` |
| `fetchers/zhitu_fetcher.py:102` | `ZhituFetcher` |
| `fetchers/ths_fetcher.py:903` | `ThsFetcher` |
| `fetchers/baidu_fetcher.py:176` | `BaiduFetcher` |
| `fetchers/zzshare_fetcher.py:189` | `ZzshareFetcher` |

Patching the two base bodies therefore fixes only the classes that inherit
them — not Zhitu / Ths / Baidu / Zzshare, which are exactly the token-gated
sources an operator is most likely to disable. Patching all six leaves the
trap armed for the next fetcher. Instead: rename every subclass
implementation to `_subclass_unavailable_reason()`, and make the public
`unavailable_reason()` a final wrapper on `BaseFetcher` that checks the switch
first:

```python
def unavailable_reason(self) -> str | None:
    if not self.is_enabled():
        return f"disabled by {self.enabled_env_var()}=false"
    return self._subclass_unavailable_reason()
```

Defining the wrapper on `BaseFetcher` (not on the mixin) is what makes it
consulted for all 13 fetchers regardless of mixin ordering. No override can
shadow the switch.

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
`boards.py` already catches `ValueError` at several sites, so the public API
needs no new HTTP plumbing. This is the whole reason for choosing a
distinguishable error: "disabled" and "typo" must be separable in the logs.

**c. `/healthz` (`api/routes/health.py:113`).** The on-demand branch computes
`available = bool(instance.is_available())` and then
`reason = None if available else ...`. A disabled fetcher would report
`available: true` here while the manifest reports `false` for the same
fetcher — two endpoints disagreeing, and `/healthz` claiming a source is
usable that the manager cannot route to. Guard it:
`available = bool(instance.is_available()) and instance.is_enabled()`.

**d. Manifest presentation.** The row stays, with `available: false` and the
reason from (a)/(c). Hiding it would remove the only UI surface where "why did
my source disappear" can be answered.

### 4. Explicit boundary: `/control/fetcher-test` is NOT gated

`POST /control/fetcher-test` instantiates the class on demand and bypasses
manager routing — this is documented, intentional behavior. Keeping the bypass
is a feature: an operator can verify an upstream source works *before* deciding
to enable it. The probe path must keep working for a disabled source.

It does not work today. `/control/*` is mounted on a bare `APIRouter` with no
`@map_errors`, and the app-level handlers (`server.py:214/229`) cover
`RequestValidationError` and `StarletteHTTPException` only — so a raw
`ValueError` becomes a 500. `explorer/routes.py:270` calls
`manager.get_fetcher(req.fetcher)` unguarded, and its `if fetcher is None:`
branch is precisely the path to `_instantiate_unregistered_fetcher`. Therefore
(3b) must be paired with a guard there:

```python
try:
    fetcher = manager.get_fetcher(req.fetcher)
except ValueError:
    fetcher = None
```

Without it the disabled-source probe 500s, and the on-demand instantiation
branch is dead code for the exact classes it exists to serve.

**Pre-existing bug, same fix.** A genuinely unknown name already 500s on this
endpoint. Verified traceback:

```
File "stock_data/explorer/routes.py", line 270, in control_fetcher_test
    fetcher = manager.get_fetcher(req.fetcher)
File "stock_data/data_provider/manager.py", line 211, in get_fetcher
    raise ValueError(f"No fetcher with name {source!r} is registered")
ValueError: No fetcher with name 'ghost' is registered
```

`_instantiate_unregistered_fetcher` has been unreachable in production all
along; `tests/test_fetcher_test_endpoint.py::test_unknown_fetcher_returns_ok_false_http_200`
passes only because it patches `get_fetcher` to return `None`. The same
try/except restores both paths, so this plan fixes a live 500 as a side effect.

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
7. `unavailable_reason()` distinguishes disabled from token-missing — asserted
   against all four overriding subclasses (Zhitu / Ths / Baidu / Zzshare), not
   just the two base implementations, since a guard placed only in the bases
   would be invisible to them.
8. `/healthz?details=true` reports `available: false` with the disabled reason
   for a disabled fetcher, agreeing with the manifest.
9. `POST /control/fetcher-test` returns 200 (`ok: false`, non-`UnknownFetcher`)
   for a disabled fetcher, and 200 with `UnknownFetcher` for a name no class
   has — driven **without** mocking `get_fetcher`, which is how the existing
   test masked the 500.
10. **Regression (the important one):** with no `*_ENABLED` var set,
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
