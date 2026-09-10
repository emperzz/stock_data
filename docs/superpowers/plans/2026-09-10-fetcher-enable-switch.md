# Per-Fetcher Enable Switch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a per-fetcher `<SLUG>_ENABLED` env switch (default `true`) that, when false, keeps the fetcher from being registered with the manager — removing it from every routing surface — while still reporting "disabled" rather than "unknown source" to callers.

**Architecture:** A single `is_enabled()` classmethod on `BaseFetcher` derives its env var name from the class name (`ZhituFetcher` → `ZHITU_ENABLED`), re-reading the env on every call. One gate in `create_default_manager()` — the only production registration site — drops disabled fetchers before instantiation. Because `_filter_by_capability` and `_slug_index` both read the registered list, that one gate removes the source from capability routing and source routing together. Four co-readers consult the same `is_enabled()` so the failure surfaces as a diagnosable "disabled by <VAR>=false" instead of an anonymous "no such source": `unavailable_reason()` (made final, so no override can bypass the switch), `get_fetcher()`/`_with_source()`, `/healthz`, and the manifest row.

**Tech Stack:** Python 3.12, pytest, FastAPI (unchanged), no new dependencies.

## Global Constraints

- **The env var name is derived, never hand-written per fetcher.** `<SLUG>_ENABLED` where `<SLUG>` is `source_slug(cls.name).upper()`. Do not add an `enabled` class attribute to any of the 13 fetcher files.
- **Falsy spellings:** exactly `false`, `0`, `no`, `off` (case-insensitive, surrounding whitespace stripped). Every other value — including `true`, `""`, and garbage — means enabled.
- **Read the env on every call, not at class-definition time.** This is what makes the switch testable via `monkeypatch` without `importlib.reload`.
- **"Disabled" means not instantiated and not registered.** It does NOT mean "module not imported" — `data_provider/__init__.py` eagerly re-exports all 12 fetcher classes and `explorer/manifest.py:255` needs those class objects. Do not attempt to make `_ENABLED=false` skip an import.
- **`/control/fetcher-test` stays ungated.** It bypasses manager routing by documented design; an operator must be able to probe a disabled source before enabling it.
- **Default must be `true`.** A regression test pins that no fetcher is dropped when no `*_ENABLED` var is set.
- Test command: `python -m pytest` (see CLAUDE.md — system `python` silently disables akshare-routed fetchers).

---

### Task 1: `source_slug()` helper in normalize.py

Extract the slug rule so `BaseFetcher.enabled_env_var()` and `DataFetcherManager._derive_slug()` cannot drift. Pure refactor plus one new export — no behavior change.

**Files:**
- Modify: `stock_data/data_provider/utils/normalize.py` (add `source_slug`, add to `__all__`)
- Modify: `stock_data/data_provider/manager.py` (`_derive_slug` delegates)
- Test: `tests/test_fetcher_enable_switch.py` (create)

**Interfaces:**
- Consumes: nothing (first task).
- Produces: `source_slug(fetcher_name: str) -> str` — importable as `from stock_data.data_provider.utils.normalize import source_slug`. Strips a trailing `Fetcher` (case-insensitive), lowercases, returns `""` for empty input. Later tasks call `source_slug(cls.name)`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_fetcher_enable_switch.py`:

```python
"""Tests for the per-fetcher <SLUG>_ENABLED switch.

The switch is read on every call (not at class-definition time), so every
test here monkeypatches the env and asserts behavior directly — no
importlib.reload, no class-identity churn.
"""

from stock_data.data_provider.utils.normalize import source_slug


class TestSourceSlug:
    def test_strips_fetcher_suffix_and_lowercases(self):
        assert source_slug("ZhituFetcher") == "zhitu"
        assert source_slug("ZzshareFetcher") == "zzshare"
        assert source_slug("ThsFetcher") == "ths"

    def test_keeps_multiword_name_as_one_token(self):
        """EastMoneyFetcher → eastmoney (the existing _derive_slug contract).

        This is the name that must match the EASTMONEY_PRIORITY env prefix,
        so "east_money" would break the symmetry the switch relies on.
        """
        assert source_slug("EastMoneyFetcher") == "eastmoney"

    def test_bare_name_without_suffix(self):
        assert source_slug("Zhitu") == "zhitu"

    def test_case_insensitive_suffix_strip(self):
        assert source_slug("ZhituFETCHER") == "zhitu"

    def test_empty_name_yields_empty_string(self):
        assert source_slug("") == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_fetcher_enable_switch.py -v`
Expected: FAIL — `ImportError: cannot import name 'source_slug' from 'stock_data.data_provider.utils.normalize'`

- [ ] **Step 3: Add the helper to normalize.py**

Append to `stock_data/data_provider/utils/normalize.py` (after `index_market_tag`):

```python
def source_slug(fetcher_name: str) -> str:
    """Derive the source slug used by env-var names and source routing.

    Strips a trailing "Fetcher" (case-insensitive) and lowercases. Examples:
        "ZhituFetcher"      → "zhitu"       (→ ZHITU_PRIORITY / ZHITU_ENABLED)
        "EastMoneyFetcher"  → "eastmoney"
        "ZzshareFetcher"    → "zzshare"
        "Zhitu"             → "zhitu"       (already bare)
        ""                  → ""

    Single source of truth for the slug rule: ``DataFetcherManager._derive_slug``
    (source-routing lookups) and ``BaseFetcher.enabled_env_var`` (the
    <SLUG>_ENABLED switch) both call this, so an env var name can never
    disagree with the slug a caller passes as ``?source=``.
    """
    if not fetcher_name:
        return ""
    name = fetcher_name
    if name.lower().endswith("fetcher"):
        name = name[:-7]
    return name.lower()
```

Add `"source_slug",` to the `__all__` list at the top of the same file (keep alphabetical-ish grouping — insert after `"code_to_exchange",`).

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_fetcher_enable_switch.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Point `_derive_slug` at the shared helper**

In `stock_data/data_provider/manager.py`, replace the body of the `_derive_slug` staticmethod (currently at ~line 157, the block containing `if not fetcher_name: return ""` / `name = fetcher_name` / `if name.lower().endswith("fetcher")` / `return name.lower()`):

```python
    @staticmethod
    def _derive_slug(fetcher_name: str) -> str:
        """Derive source slug from fetcher class name.

        Delegates to :func:`source_slug` so the slug a caller passes as
        ``?source=`` and the ``<SLUG>_ENABLED`` env var name can never
        disagree — both come from one rule.

        Examples:
            "ZhituFetcher" → "zhitu"
            "EastMoneyFetcher" → "eastmoney"
            "Zhitu" → "zhitu"  # already bare
            "MyquantFetcher" → "myquant"
        """
        return source_slug(fetcher_name)
```

Add `source_slug` to the existing `from .utils.normalize import ...` line at the top of `manager.py` (currently `from .utils.normalize import index_market_tag, market_tag, normalize_stock_code`).

- [ ] **Step 6: Run the source-routing regression tests**

Run: `python -m pytest tests/test_board_source_routing.py tests/test_fetcher_enable_switch.py -v`
Expected: PASS — `_derive_slug` is behavior-identical, so board source routing is unaffected.

- [ ] **Step 7: Commit**

```bash
git add stock_data/data_provider/utils/normalize.py stock_data/data_provider/manager.py tests/test_fetcher_enable_switch.py
git commit -m "refactor: extract source_slug() so env names and ?source= share one rule"
```

---

### Task 2: `is_enabled()` / `enabled_env_var()` on BaseFetcher

**Files:**
- Modify: `stock_data/data_provider/base.py` (add two classmethods to `BaseFetcher`)
- Test: `tests/test_fetcher_enable_switch.py` (append)

**Interfaces:**
- Consumes: `source_slug` from Task 1.
- Produces: `BaseFetcher.enabled_env_var() -> str` and `BaseFetcher.is_enabled() -> bool`, both classmethods. Available on every subclass (all 13 fetchers, plus test fakes) with no per-fetcher declaration. Tasks 3–5 call `cls.is_enabled()` / `cls.enabled_env_var()`; Task 5 additionally renames the four `unavailable_reason()` overrides so this switch cannot be bypassed.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_fetcher_enable_switch.py`:

```python
import pytest

from stock_data.data_provider.base import BaseFetcher
from stock_data.data_provider.fetchers.zhitu_fetcher import ZhituFetcher


class TestEnabledEnvVar:
    def test_derives_from_class_name(self):
        assert ZhituFetcher.enabled_env_var() == "ZHITU_ENABLED"
        # BaseFetcher itself derives from the same rule — "Base" + suffix,
        # not a special case. Pins that there is no base-class carve-out.
        assert BaseFetcher.enabled_env_var() == "BASE_ENABLED"

    def test_derivation_matches_the_priority_var_convention(self):
        """The <SLUG>_ENABLED name must be the <SLUG>_PRIORITY name's sibling.

        Both are built from source_slug(cls.name).upper(), so a mismatch here
        means one of the two stopped using the shared rule.
        """
        from stock_data.data_provider.fetchers.eastmoney_fetcher import EastMoneyFetcher
        from stock_data.data_provider.fetchers.zzshare_fetcher import ZzshareFetcher

        assert EastMoneyFetcher.enabled_env_var() == "EASTMONEY_ENABLED"
        assert ZzshareFetcher.enabled_env_var() == "ZZSHARE_ENABLED"


class TestIsEnabled:
    def test_defaults_to_true_when_env_unset(self, monkeypatch):
        monkeypatch.delenv("ZHITU_ENABLED", raising=False)
        assert ZhituFetcher.is_enabled() is True

    @pytest.mark.parametrize("raw", ["false", "False", "FALSE", " false ", "0", "no", "off"])
    def test_falsy_spellings_disable(self, monkeypatch, raw):
        """Case and surrounding whitespace are tolerated, so a .env written
        as `ZHITU_ENABLED = FALSE` still disables rather than silently
        staying enabled."""
        monkeypatch.setenv("ZHITU_ENABLED", raw)
        assert ZhituFetcher.is_enabled() is False

    @pytest.mark.parametrize("raw", ["true", "TRUE", "1", "yes", "on", "", "garbage"])
    def test_anything_else_stays_enabled(self, monkeypatch, raw):
        """Empty string means enabled, not disabled.

        An unset var and an empty var must agree: `ZHITU_ENABLED=` in a .env
        is the most common way a user "leaves it blank", and treating that as
        disabled would silently drop a source with no visible cause.
        """
        monkeypatch.setenv("ZHITU_ENABLED", raw)
        assert ZhituFetcher.is_enabled() is True

    def test_reads_env_per_call_not_at_import_time(self, monkeypatch):
        """Flip the env twice on the same class object.

        This is the property that lets every other test here use monkeypatch
        instead of importlib.reload (which would rebind the class and desync
        the SDK init cache — see tests/test_zzshare_fetcher.py:59-80).
        """
        monkeypatch.setenv("ZHITU_ENABLED", "false")
        assert ZhituFetcher.is_enabled() is False
        monkeypatch.setenv("ZHITU_ENABLED", "true")
        assert ZhituFetcher.is_enabled() is True

    def test_switch_is_per_fetcher_not_global(self, monkeypatch):
        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

        monkeypatch.setenv("ZHITU_ENABLED", "false")
        monkeypatch.delenv("THS_ENABLED", raising=False)
        assert ZhituFetcher.is_enabled() is False
        assert ThsFetcher.is_enabled() is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_fetcher_enable_switch.py -v -k "Enabled or IsEnabled"`
Expected: FAIL — `AttributeError: type object 'ZhituFetcher' has no attribute 'enabled_env_var'`

- [ ] **Step 3: Add the classmethods to BaseFetcher**

In `stock_data/data_provider/base.py`, add these two classmethods to `BaseFetcher`, immediately **before** the existing `is_available()` method (currently ~line 299, the one whose docstring begins "Default: the fetcher is unconditionally available."):

```python
    @classmethod
    def enabled_env_var(cls) -> str:
        """Env var that enables/disables this fetcher, e.g. "ZHITU_ENABLED".

        Derived from the class name via ``source_slug`` so it is always the
        sibling of the fetcher's ``<SLUG>_PRIORITY`` var and matches the slug
        callers pass as ``?source=``. Fetchers therefore need no per-class
        declaration — a new fetcher gets its switch for free.
        """
        return f"{source_slug(cls.name).upper()}_ENABLED"

    @classmethod
    def is_enabled(cls) -> bool:
        """True unless ``<SLUG>_ENABLED`` is explicitly falsy.

        Falsy: "false" / "0" / "no" / "off" (case-insensitive, whitespace
        stripped). Everything else — unset, empty, "true", garbage — is
        enabled, matching the "default true" contract.

        Read on EVERY call rather than at class-definition time, so tests can
        ``monkeypatch.setenv`` and observe the change without
        ``importlib.reload`` (which would rebind the class and desync the
        class-level SDK init cache).
        """
        raw = os.getenv(cls.enabled_env_var(), "true").strip().lower()
        return raw not in ("false", "0", "no", "off")
```

Add `source_slug` to the existing `from .utils.normalize import (...)` block at the top of `base.py` (the block currently importing `index_market_tag`, `is_hk_market`, `is_us_market`, `normalize_stock_code`).

Note: `os` is already imported in `base.py` (line 5), so no new stdlib import is needed.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_fetcher_enable_switch.py -v`
Expected: PASS (all tests, including Task 1's)

- [ ] **Step 5: Commit**

```bash
git add stock_data/data_provider/base.py tests/test_fetcher_enable_switch.py
git commit -m "feat: BaseFetcher.is_enabled() reading <SLUG>_ENABLED per call"
```

---

### Task 3: Gate registration in `create_default_manager()`

**Files:**
- Modify: `stock_data/data_provider/manager.py` (the `for cls in fetcher_classes:` loop at ~line 1532)
- Test: `tests/test_fetcher_enable_switch.py` (append)

**Interfaces:**
- Consumes: `BaseFetcher.is_enabled()` / `enabled_env_var()` from Task 2.
- Produces: nothing new — this task makes `create_default_manager()` skip disabled fetchers. Downstream consumers of the registered list (`_filter_by_capability`, `_slug_index`) need no change.

**Why this one site is sufficient:** `create_default_manager()` is the only production registration path (also used by `tools/build_membership_index.py:259` and `api/routes/helpers.py:80`, which inherit the gate for free). Everything downstream reads the registered list: `_filter_by_capability` (`manager.py:140`) drives all `_with_failover` capability routing, and `_refresh_index` builds `_slug_index` for `_with_source` (`manager.py:214`) — the board path, which ignores priority entirely.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_fetcher_enable_switch.py`:

```python
class TestRegistrationGate:
    def test_disabled_fetcher_is_not_registered(self, monkeypatch):
        """ZHITU_ENABLED=false keeps ZhituFetcher out of the manager entirely.

        is_available is forced True and the token is set so the assertion
        isolates the enable switch: without the gate, this fetcher would
        register, so a failure here is unambiguously "the gate didn't fire",
        not "the token happened to be missing".
        """
        from stock_data.data_provider.manager import create_default_manager

        monkeypatch.setenv("ZHITU_TOKEN", "fake-token-for-test")
        monkeypatch.setattr(ZhituFetcher, "is_available", lambda self: True)
        monkeypatch.setenv("ZHITU_ENABLED", "true")
        assert "ZhituFetcher" in [f.name for f in create_default_manager().fetchers]

        monkeypatch.setenv("ZHITU_ENABLED", "false")
        manager = create_default_manager()
        assert "ZhituFetcher" not in [f.name for f in manager.fetchers]

    def test_disabled_fetcher_leaves_the_slug_index(self, monkeypatch):
        """Source-routed endpoints must not resolve a disabled source.

        _slug_index is built by _refresh_index() from the registered list, so
        this is the property that removes the fetcher from the board
        endpoints — where _with_source() bypasses priority-based failover and
        there is no ordering to manipulate.
        """
        from stock_data.data_provider.manager import create_default_manager

        monkeypatch.setenv("THS_ENABLED", "false")
        manager = create_default_manager()
        assert "ths" not in manager._slug_index, (
            "disabled fetcher still reachable via _slug_index — board "
            "endpoints (?source=ths) would keep serving it"
        )

    def test_disabled_fetcher_is_never_instantiated(self, monkeypatch):
        """The gate runs before cls(), so a disabled fetcher is not constructed.

        If the check were placed after instantiation, a disabled SDK fetcher
        would still run its class-level init (reading a token, possibly
        touching the network) on every process start.
        """
        from stock_data.data_provider.manager import create_default_manager

        instantiated: list[str] = []
        real_init = ZhituFetcher.__init__

        def spy_init(self, *args, **kwargs):
            instantiated.append(type(self).name)
            return real_init(self, *args, **kwargs)

        monkeypatch.setattr(ZhituFetcher, "__init__", spy_init)
        monkeypatch.setenv("ZHITU_ENABLED", "false")
        create_default_manager()
        assert "ZhituFetcher" not in instantiated

    def test_no_enabled_var_set_drops_nobody(self, monkeypatch):
        """Regression: the default must be enabled for all 13 fetchers.

        Asserted against each class's own is_available() rather than a
        hardcoded name list, because which fetchers are available depends on
        tokens and installed SDKs in the environment — a name list would be
        flaky. This still catches a wrong default: if "true" parsed as falsy,
        create_default_manager() would register zero fetchers and fail here.
        """
        from stock_data.data_provider.manager import create_default_manager
        from stock_data.data_provider.manager import _all_fetcher_classes

        for cls in _all_fetcher_classes():
            monkeypatch.delenv(cls.enabled_env_var(), raising=False)

        manager = create_default_manager()
        registered = {f.name for f in manager.fetchers}
        expected = {cls.name for cls in _all_fetcher_classes() if cls().is_available()}
        assert registered == expected
```

Note: `_all_fetcher_classes()` is the private helper introduced in Step 3 below; it is the list `create_default_manager()` iterates, exposed so the test cannot drift from the production list.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_fetcher_enable_switch.py -v -k Registration`
Expected: FAIL — `test_disabled_fetcher_is_not_registered` asserts ZhituFetcher is absent but it is still registered; `test_no_enabled_var_set_drops_nobody` fails on `ImportError: cannot import name '_all_fetcher_classes'`.

- [ ] **Step 3: Add the gate**

In `stock_data/data_provider/manager.py`, add a module-level helper directly above `create_default_manager()`:

```python
def _all_fetcher_classes() -> list[type[BaseFetcher]]:
    """The fetcher classes ``create_default_manager()`` considers, in order.

    Returned rather than inlined so tests can assert against the same list
    production iterates — a fetcher added here is automatically covered by
    the "no _ENABLED var set drops nobody" regression test.

    Import is local: importing the fetcher modules at manager-module import
    time would create a circular import (fetchers import from ``base``, which
    ``manager`` imports first).
    """
    from .fetchers.akshare import AkshareFetcher
    from .fetchers.baidu_fetcher import BaiduFetcher
    from .fetchers.baostock_fetcher import BaostockFetcher
    from .fetchers.cls_fetcher import ClsFetcher
    from .fetchers.cninfo_fetcher import CninfoFetcher
    from .fetchers.eastmoney_fetcher import EastMoneyFetcher
    from .fetchers.myquant_fetcher import MyquantFetcher
    from .fetchers.tencent_fetcher import TencentFetcher
    from .fetchers.ths_fetcher import ThsFetcher
    from .fetchers.tushare_fetcher import TushareFetcher
    from .fetchers.yfinance_fetcher import YfinanceFetcher
    from .fetchers.zhitu_fetcher import ZhituFetcher
    from .fetchers.zzshare_fetcher import ZzshareFetcher

    return [
        TushareFetcher,
        BaostockFetcher,
        MyquantFetcher,
        AkshareFetcher,
        YfinanceFetcher,
        ZhituFetcher,
        ZzshareFetcher,
        TencentFetcher,
        EastMoneyFetcher,
        BaiduFetcher,
        ThsFetcher,
        CninfoFetcher,
        ClsFetcher,
    ]
```

Then replace the whole body of `create_default_manager()` (currently the 13 lazy imports, `manager = DataFetcherManager()`, the `fetcher_classes = [...]` literal, and the `for cls in fetcher_classes:` loop) with:

```python
def create_default_manager() -> DataFetcherManager:
    """Create a DataFetcherManager with all enabled, available fetchers registered.

    Each fetcher is skipped when ``is_enabled()`` is False (its
    ``<SLUG>_ENABLED`` env var is explicitly falsy) or when
    ``is_available()`` is False. This is the single source of truth for
    fetcher registration — callers in ``routes.py`` and ``persistence/``
    should use this factory instead of constructing their own manager.

    The enable check runs BEFORE instantiation: a disabled fetcher is never
    constructed, so its class-level SDK init never fires. The switch is read
    per call, but this factory runs once at startup — changing a
    ``*_ENABLED`` var requires a process restart, same as ``*_PRIORITY``.

    Returns:
        A fully configured DataFetcherManager with the enabled + available
        fetchers registered in priority order.
    """
    manager = DataFetcherManager()
    for cls in _all_fetcher_classes():
        if not cls.is_enabled():
            logger.info(f"{cls.__name__} disabled by {cls.enabled_env_var()}")
            continue
        instance = cls()
        if instance.is_available():
            manager.add_fetcher(instance)
            logger.info(f"{cls.__name__} added")
        else:
            logger.info(f"{cls.__name__} skipped")
    return manager
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_fetcher_enable_switch.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Run the registration-dependent regression tests**

Run: `python -m pytest tests/test_board_source_routing.py tests/test_manager_stock_news.py tests/test_manager_announcements_backup_ths.py tests/test_announcements_eastmoney_failover.py tests/test_build_membership_index.py -v`
Expected: PASS — these all call `create_default_manager()` and assert on the registered set; with no `*_ENABLED` set, the set is unchanged.

- [ ] **Step 6: Commit**

```bash
git add stock_data/data_provider/manager.py tests/test_fetcher_enable_switch.py
git commit -m "feat: skip disabled fetchers in create_default_manager()"
```

---

### Task 4: Distinguishable "disabled" error on source lookup

Without this, `?source=zhitu` against a disabled zhitu reports "No fetcher with name 'zhitu' is registered" — indistinguishable from a typo, sending whoever debugs it to check spelling instead of config.

**Files:**
- Modify: `stock_data/data_provider/manager.py` (add `_find_disabled_fetcher_class` + `_raise_if_disabled`; call from `get_fetcher` ~line 210 and `_with_source` ~line 275)
- Modify: `stock_data/explorer/routes.py:270` (guard `manager.get_fetcher` against the new `ValueError`)
- Modify: `tests/test_fetcher_test_endpoint.py` (pin the guard with a non-mocked test)
- Test: `tests/test_fetcher_enable_switch.py` (append)

**Interfaces:**
- Consumes: `source_slug` (Task 1), `BaseFetcher.is_enabled()` / `enabled_env_var()` (Task 2).
- Produces: `ValueError` with message `source '<slug>' is disabled by <VAR>=false`. The `ValueError` → 400 mapping already exists in `api/routes/errors.py::map_errors`, and `api/routes/boards.py` already catches `ValueError` at several sites, so the public API needs no HTTP-layer change.

**Why `explorer/routes.py` must change too.** `/control/*` is mounted on a bare `APIRouter` and carries **no** `@map_errors`; the app-level handlers in `server.py:214/229` cover `RequestValidationError` and `StarletteHTTPException` only, so a raw `ValueError` becomes a 500. `POST /control/fetcher-test` calls `manager.get_fetcher(req.fetcher)` at `explorer/routes.py:270` with no try/except, and its `if fetcher is None:` branch is *precisely* how an unregistered class reaches `_instantiate_unregistered_fetcher` — the on-demand instantiation that makes probing a disabled source work. Raising instead of returning `None` would turn that branch into dead code for the exact classes it exists to serve, and would 500 the probe, contradicting the Global Constraint that `/control/fetcher-test` stays ungated. Because that branch is unreachable with a registered manager, no existing test catches it — hence the non-mocked test in Step 4.

**A pre-existing bug this same guard fixes (verified, not hypothetical).** A genuinely unknown name already 500s on this endpoint today. Confirmed traceback:

```
File "stock_data/explorer/routes.py", line 270, in control_fetcher_test
    fetcher = manager.get_fetcher(req.fetcher)
File "stock_data/data_provider/manager.py", line 211, in get_fetcher
    raise ValueError(f"No fetcher with name {source!r} is registered")
ValueError: No fetcher with name 'ghost' is registered
```

So the `if fetcher is None:` branch — and with it `_instantiate_unregistered_fetcher` — has been **unreachable in production all along**; `tests/test_fetcher_test_endpoint.py::test_unknown_fetcher_returns_ok_false_http_200` only passes because it patches `get_fetcher` to return `None`. The one `try/except ValueError: fetcher = None` in Step 4 restores both the disabled-source probe and the unknown-name path, and lets the existing mocked test be backed by a real one.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_fetcher_enable_switch.py`:

```python
class TestDisabledSourceError:
    def test_get_fetcher_names_the_env_var(self, monkeypatch):
        """The error must say "disabled", not "not registered".

        A caller reading the log needs to know whether to check the spelling
        of ?source= or the value of an env var — those are different files.
        """
        manager = DataFetcherManager()  # empty: nothing registered
        monkeypatch.setenv("ZHITU_ENABLED", "false")
        with pytest.raises(ValueError) as exc:
            manager.get_fetcher("zhitu")
        assert "ZHITU_ENABLED" in str(exc.value)
        assert "disabled" in str(exc.value)

    def test_unknown_source_still_says_not_registered(self, monkeypatch):
        """Only genuinely-disabled sources get the new message."""
        manager = DataFetcherManager()
        with pytest.raises(ValueError) as exc:
            manager.get_fetcher("nosuchfetcher")
        assert "No fetcher with name" in str(exc.value)

    def test_accepts_class_name_form(self, monkeypatch):
        """get_fetcher accepts "ZhituFetcher" and "zhitu" — both must report
        the disabled reason, or the class-name form leaks the old message."""
        manager = DataFetcherManager()
        monkeypatch.setenv("ZHITU_ENABLED", "false")
        with pytest.raises(ValueError) as exc:
            manager.get_fetcher("ZhituFetcher")
        assert "ZHITU_ENABLED" in str(exc.value)

    def test_with_source_reports_disabled(self, monkeypatch):
        """Board routing goes through _with_source, which has its own lookup.

        Board endpoints are where this matters most: they ignore priority
        entirely, so "disabled" is the only signal available.
        """
        from stock_data.data_provider.base import DataCapability

        manager = DataFetcherManager()
        monkeypatch.setenv("THS_ENABLED", "false")
        with pytest.raises(ValueError) as exc:
            manager._with_source(
                "ths",
                DataCapability.STOCK_BOARD,
                "csi",
                "test op",
                lambda f: None,
            )
        assert "THS_ENABLED" in str(exc.value)
```

Add `from stock_data.data_provider.manager import DataFetcherManager` to the test file's imports.

Then append this second class — it tests the *control endpoint* guard, in a separate file because it needs an app/TestClient fixture, and deliberately does **not** mock `get_fetcher` (the existing `test_unknown_fetcher_returns_ok_false_http_200` does mock it, which is exactly why the 500 went unnoticed).

Append to `tests/test_fetcher_test_endpoint.py`:

```python
def test_unknown_fetcher_real_lookup_returns_ok_false_http_200(client):
    """Unmocked: a name no fetcher class has must return UnknownFetcher, not 500.

    The sibling test_unknown_fetcher_returns_ok_false_http_200 patches
    get_fetcher to return None, so it never exercised the route's real
    lookup — the route raised ValueError before reaching the None check.
    This test drives the real path.
    """
    r = _post(client, {"fetcher": "ghost", "method": "get_realtime_quote", "kwargs": {}})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["error"]["type"] == "UnknownFetcher"


def test_disabled_fetcher_is_still_probeable(client, monkeypatch):
    """A config-disabled fetcher must still be testable.

    /control/fetcher-test intentionally bypasses manager routing so an
    operator can verify an upstream source before enabling it. The disabled
    fetcher is absent from the manager, so this exercises the on-demand
    instantiation path (_instantiate_unregistered_fetcher) — which only
    runs if the route tolerates the lookup failure instead of 500ing.
    """
    monkeypatch.setenv("ZHITU_ENABLED", "false")
    r = _post(client, {"fetcher": "ZhituFetcher", "method": "get_stock_info",
                       "kwargs": {"stock_code": "600519"}})
    assert r.status_code == 200, "disabled fetcher probe 500'd"
    body = r.json()
    # The probe is allowed to fail upstream (no token / network in tests) —
    # what it must NOT do is die at the lookup step.
    assert body["error"] is None or body["error"]["type"] != "UnknownFetcher", (
        f"disabled fetcher was reported as UnknownFetcher: {body['error']}"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_fetcher_enable_switch.py -v -k DisabledSourceError`
Expected: FAIL — `test_get_fetcher_names_the_env_var` gets "No fetcher with name 'zhitu' is registered" (no `ZHITU_ENABLED`); `test_accepts_class_name_form` and `test_with_source_reports_disabled` fail the same way.

- [ ] **Step 3: Add the helpers and wire them in**

In `stock_data/data_provider/manager.py`, add these two module-level functions near `_all_fetcher_classes()` (above `create_default_manager()`):

```python
def _find_disabled_fetcher_class(source: str) -> type[BaseFetcher] | None:
    """Return the ``BaseFetcher`` subclass matching ``source`` that is disabled.

    ``source`` matches either the derived slug ("zhitu") or the class name
    ("ZhituFetcher"), case-insensitively — the same two forms
    :meth:`DataFetcherManager.get_fetcher` accepts.

    Only classes reporting ``is_enabled() == False`` are returned. A class
    that is enabled but simply not registered (missing token, SDK absent) is
    NOT a "disabled" answer and must fall through to the caller's generic
    "not registered" error — otherwise every missing-token source would
    claim to be config-disabled.

    Walks subclasses rather than the manager's registered list by necessity:
    a disabled fetcher is precisely the one that is not in that list.
    """
    wanted = source.lower()
    stack: list[type[BaseFetcher]] = list(BaseFetcher.__subclasses__())
    while stack:
        cls = stack.pop()
        name = getattr(cls, "name", None)
        if name and (name.lower() == wanted or source_slug(name) == wanted):
            if not cls.is_enabled():
                return cls
        stack.extend(cls.__subclasses__())
    return None


def _raise_if_disabled(source: str) -> None:
    """Raise a distinguishable ValueError when ``source`` is config-disabled.

    The message names the env var so an operator can tell "this source is
    turned off in config" from "I misspelled ?source=". Reaches the client as
    HTTP 400 via ``api/routes/errors.py::map_errors``.
    """
    cls = _find_disabled_fetcher_class(source)
    if cls is not None:
        raise ValueError(
            f"source {source_slug(cls.name)!r} is disabled by "
            f"{cls.enabled_env_var()}=false"
        )
```

In `get_fetcher`, change the raise at the end of the lookup (currently `raise ValueError(f"No fetcher with name {source!r} is registered")`, ~line 211):

```python
        if target is None:
            _raise_if_disabled(source)
            raise ValueError(f"No fetcher with name {source!r} is registered")
        return target
```

In `_with_source`, make the identical change at its lookup raise (~line 276):

```python
        if target is None:
            _raise_if_disabled(source)
            raise ValueError(f"No fetcher with name {source!r} is registered")
        if market not in target.supported_markets:
```

Finally, guard the control endpoint in `stock_data/explorer/routes.py`. Replace the line at 270:

```python
        fetcher = manager.get_fetcher(req.fetcher)
```

with:

```python
        # get_fetcher raises ValueError for (a) a genuinely unknown name and
        # (b) a name that is config-disabled. Both must fall through to the
        # on-demand instantiation below — this endpoint's contract is to
        # probe any fetcher, including one the manager didn't register
        # (unavailable, or turned off with <SLUG>_ENABLED=false). /control/*
        # has no @map_errors and the app-level handlers don't cover
        # ValueError, so letting it propagate would 500 the probe.
        try:
            fetcher = manager.get_fetcher(req.fetcher)
        except ValueError:
            fetcher = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_fetcher_enable_switch.py tests/test_fetcher_test_endpoint.py -v`
Expected: PASS (all tests) — including the two new unmocked control-endpoint tests, and the 20 pre-existing `test_fetcher_test_endpoint.py` tests unchanged.

- [ ] **Step 5: Run the source-routing and error-contract regressions**

Run: `python -m pytest tests/test_board_source_routing.py tests/test_routes.py -v`
Expected: PASS — the generic "no fetcher" path is unchanged for enabled-but-missing sources, which is what these cover.

- [ ] **Step 6: Commit**

```bash
git add stock_data/data_provider/manager.py stock_data/explorer/routes.py tests/test_fetcher_enable_switch.py tests/test_fetcher_test_endpoint.py
git commit -m "feat: distinguish 'disabled by config' from 'unknown source' on lookup"
```

---

### Task 5: Report "disabled" in `unavailable_reason()`

**Required, not cosmetic.** `explorer/manifest.py:255 _resolve_fetchers` enumerates **all** `BaseFetcher` subclasses — not the registered instances — and fills each row's `reason` from `unavailable_reason()`. Without this branch, a disabled source renders in the explorer as "ZHITU_TOKEN environment variable not set", pointing the reader at the wrong cause.

**Second gap, same root cause.** `/healthz?details=true` computes its `available` flag from `is_available()` alone (`api/routes/health.py:113`), never consulting the switch, then sets `unavailable_reason = None if available else ...`. So a disabled source would report `available: true` in `/healthz` while the manifest reports `available: false` for the same fetcher — two endpoints disagreeing, and `/healthz` claiming a source is usable when it is not registered at all. This task fixes both.

**Files:**
- Modify: `stock_data/data_provider/base.py` (split `unavailable_reason` into a final wrapper + `_subclass_unavailable_reason`, in both `SDKFetcherMixin` ~line 139 and `BaseFetcher` ~line 285)
- Modify: `stock_data/data_provider/fetchers/{zhitu,ths,baidu,zzshare}_fetcher.py` (rename their overrides)
- Modify: `stock_data/api/routes/health.py:113` (consult the switch for the on-demand branch)
- Test: `tests/test_fetcher_enable_switch.py` (append)

**Interfaces:**
- Consumes: `is_enabled()` / `enabled_env_var()` (Task 2).
- Produces: `unavailable_reason()` returns `"disabled by <VAR>=false"` when disabled, ahead of any token/SDK reason, and is **final** (no subclass may override it). Consumed by `explorer/manifest.py::_resolve_fetchers` (manifest row stays present with `available: false`) and `/healthz` (reports `available: false`). Subclasses now implement `_subclass_unavailable_reason()`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_fetcher_enable_switch.py`:

```python
class TestUnavailableReasonReportsDisabled:
    """The reason string is what the explorer shows, so "disabled" must win.

    These assert against the OVERRIDING subclasses on purpose. ZhituFetcher,
    ThsFetcher, BaiduFetcher and ZzshareFetcher each replace
    unavailable_reason() outright, so a guard placed only in the two base
    implementations is invisible to them — which is where the switch matters
    most, since those are the token-gated sources people turn off.
    """

    def test_disabled_reason_wins_over_token_reason(self, monkeypatch):
        """A disabled source must not be described as missing its token.

        Without the guard ahead of the override, the explorer tells the
        operator to set ZHITU_TOKEN for a source they deliberately turned
        off — sending them to the wrong fix.
        """
        monkeypatch.setenv("ZHITU_ENABLED", "false")
        reason = ZhituFetcher().unavailable_reason()
        assert reason == "disabled by ZHITU_ENABLED=false"
        assert "ZHITU_TOKEN" not in reason

    def test_enabled_fetcher_keeps_existing_reason(self, monkeypatch):
        """No behavior change for the non-disabled path.

        The token is set explicitly on the instance instead of via the env:
        stock_data.server calls load_dotenv(), so on a machine whose real
        .env has ZHITU_TOKEN the fetcher would report available and this
        assertion would prove nothing.
        """
        monkeypatch.delenv("ZHITU_ENABLED", raising=False)
        fetcher = ZhituFetcher()
        monkeypatch.setattr(fetcher, "_token", "", raising=False)
        reason = fetcher.unavailable_reason()
        assert reason is not None
        assert "disabled" not in reason
        assert "ZHITU_TOKEN" in reason

    def test_enabled_and_available_returns_none(self, monkeypatch):
        monkeypatch.delenv("ZHITU_ENABLED", raising=False)
        fetcher = ZhituFetcher()
        monkeypatch.setattr(fetcher, "_token", "tok", raising=False)
        assert fetcher.unavailable_reason() is None

    def test_every_override_is_covered(self, monkeypatch):
        """All four overriding subclasses must honour the switch.

        A guard added to the two base implementations only would leave
        Zhitu/Ths/Baidu/Zzshare reporting token or SDK reasons when disabled.
        Parametrising over the overriders is what makes that a test failure
        instead of a code-review catch.
        """
        from stock_data.data_provider.fetchers.baidu_fetcher import BaiduFetcher
        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher
        from stock_data.data_provider.fetchers.zzshare_fetcher import ZzshareFetcher

        for cls in (ZhituFetcher, ThsFetcher, BaiduFetcher, ZzshareFetcher):
            monkeypatch.setenv(cls.enabled_env_var(), "false")
        for cls in (ZhituFetcher, ThsFetcher, BaiduFetcher, ZzshareFetcher):
            reason = cls().unavailable_reason()
            assert reason == f"disabled by {cls.enabled_env_var()}=false", (
                f"{cls.__name__} overrides unavailable_reason() without the "
                f"enable guard; got {reason!r}"
            )
            monkeypatch.delenv(cls.enabled_env_var(), raising=False)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_fetcher_enable_switch.py -v -k UnavailableReason`
Expected: FAIL — `test_disabled_reason_wins_over_token_reason` gets a token/SDK message, not `"disabled by ZHITU_ENABLED=false"`; `test_every_override_is_covered` fails on the first override.

- [ ] **Step 3: Make `unavailable_reason()` final on `BaseFetcher`**

**Do not add the guard to each override.** There are **six** `unavailable_reason()` definitions today, not two:

| File:line | Class | Shape |
|---|---|---|
| `base.py:139` | `SDKFetcherMixin` | disabled → token → SDK-init |
| `base.py:285` | `BaseFetcher` | `is_available()` → generic message |
| `fetchers/zhitu_fetcher.py:102` | `ZhituFetcher` | `not self._token` → message, else `None` |
| `fetchers/ths_fetcher.py:903` | `ThsFetcher` | `_check_ths_deps()` |
| `fetchers/baidu_fetcher.py:176` | `BaiduFetcher` | `is_available()` → message |
| `fetchers/zzshare_fetcher.py:189` | `ZzshareFetcher` | `is_available()` → SDK message |

Adding the guard to the two base bodies fixes only the two classes that inherit them — precisely not the four sources an operator is most likely to disable. Editing all six leaves the same trap for the next fetcher someone adds. Instead, rename the subclasses' implementations.

**1. In `base.py`, rename `SDKFetcherMixin.unavailable_reason` → `_subclass_unavailable_reason`** (same body, minus the new guard — it needs no guard, since the public method now checks first):

```python
    def _subclass_unavailable_reason(self) -> str | None:
        """Subclass-specific unavailability reason.

        Never override ``unavailable_reason()`` — override this instead. The
        public wrapper applies the ``<SLUG>_ENABLED`` check first, and a
        subclass that replaced the wrapper outright would silently bypass the
        enable switch (that is exactly the bug this split prevents).

        Distinguishes "token env var missing" (user fixable) from "SDK init
        failed" (likely transient or package not installed). When the
        subclass declared token as OPTIONAL (``_TOKEN_REQUIRED=False``), an
        empty env var is not by itself an unavailability reason — the
        anonymous init may have succeeded or failed on its own merits; we
        surface that init error instead.
        """
        if self.is_available():
            return None
        env_var = getattr(self, "_TOKEN_ENV_VAR", None)
        token_required = getattr(self, "_TOKEN_REQUIRED", True)
        if env_var and not self.__class__._cls_token and token_required:
            return f"{env_var} environment variable not set (required by {self.name})"
        sdk_name = getattr(self, "_SDK_NAME", self.name)
        return (
            f"{sdk_name} SDK could not initialize for {self.name} "
            f"({self.__class__._init_error or 'token may be invalid, or the package is not importable'})"
        )
```

**2. In `base.py`, replace `BaseFetcher.unavailable_reason`** (line 285) with the split pair. `BaseFetcher` is the base of every fetcher, so defining the public method here makes it inherited — and therefore consulted — by all 13 regardless of mixin ordering (MRO reaches `SDKFetcherMixin` only after `BaseFetcher` for the SDK fetchers, so putting the public method on `BaseFetcher` is what guarantees it always runs):

```python
    def unavailable_reason(self) -> str | None:
        """Return a human-readable reason this fetcher is unavailable.

        The ``<SLUG>_ENABLED`` switch is authoritative: a config-disabled
        fetcher reports that and nothing else, so the explorer manifest (whose
        `_resolve_fetchers` enumerates all subclasses, disabled ones included)
        never tells an operator to set a token for a source they turned off.

        This method is intentionally NOT overridden by subclasses — they
        implement ``_subclass_unavailable_reason()`` instead. Keeping the
        enable check on the single public entry point means a new fetcher
        cannot forget it.
        """
        if not self.is_enabled():
            return f"disabled by {self.enabled_env_var()}=false"
        return self._subclass_unavailable_reason()

    def _subclass_unavailable_reason(self) -> str | None:
        """Default unavailability reason; override this, never the wrapper.

        If the fetcher reports available, no reason is needed; otherwise
        return a generic message naming this fetcher. Token-gated fetchers
        (Zhitu, Tushare, Myquant) override with a more specific message
        derived from their actual gating logic (env var / SDK state). The
        explorer's manifest calls this only when is_available() returns
        False, so the "always None" path is hit for fetchers that pass.
        """
        if self.is_available():
            return None
        return f"{self.name} unavailable (is_available() returned False)"
```

**3. Rename the four per-fetcher overrides** from `unavailable_reason` to `_subclass_unavailable_reason`, bodies unchanged:

- `fetchers/zhitu_fetcher.py:102`
- `fetchers/ths_fetcher.py:903`
- `fetchers/baidu_fetcher.py:176`
- `fetchers/zzshare_fetcher.py:189`

Change only the `def` line in each. Do **not** remove the guard from the bodies — they never had one; the wrapper supplies it.

Verify no override was missed:

```bash
grep -rn "def unavailable_reason" stock_data/ --include=*.py
```

Expected: exactly one hit, `base.py` (the public wrapper). A second hit means an override was renamed incompletely and would shadow the switch — the `test_every_override_is_covered` test is what pins this.

**4. Make `/healthz` agree with the manifest** — in `stock_data/api/routes/health.py`, the on-demand branch currently reads (line ~113):

```python
            available = bool(instance.is_available())
            reason = None if available else instance.unavailable_reason()
```

Replace with:

```python
            # The <SLUG>_ENABLED switch is authoritative — a config-disabled
            # fetcher is not registered, so reporting available=True here
            # would contradict /control/api-manifest (which reads the same
            # unavailable_reason()) and claim a source is usable that the
            # manager cannot route to.
            enabled = instance.is_enabled()
            available = bool(instance.is_available()) and enabled
            reason = None if available else instance.unavailable_reason()
```

Note the `and enabled` guard: without it, `available` could be True for a disabled fetcher while `reason` is None, which is the same contradiction in a different shape.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_fetcher_enable_switch.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Run the manifest, health and per-fetcher regressions**

Run: `python -m pytest tests/test_explorer_manifest_endpoint.py tests/test_routes.py tests/test_ths_board_kline.py tests/test_zzshare_fetcher.py tests/test_baidu_search_news.py -v`
Expected: PASS — `test_unavailable_fetcher_surfaces_with_available_false_and_reason` still finds `ZHITU_TOKEN` in the reason when `ZHITU_ENABLED` is unset, and the per-fetcher reason tests still see their own messages (they call `unavailable_reason()`, which now routes through the wrapper to the renamed override — same string out). `tests/test_routes.py::test_health_unavailable_fetchers_have_logic_driven_reason` asserts each reason contains the fetcher's name with `FETCHER` stripped, which still holds for messages the wrapper does not intercept.

- [ ] **Step 6: Commit**

```bash
git add stock_data/data_provider/base.py stock_data/data_provider/fetchers/zhitu_fetcher.py stock_data/data_provider/fetchers/ths_fetcher.py stock_data/data_provider/fetchers/baidu_fetcher.py stock_data/data_provider/fetchers/zzshare_fetcher.py stock_data/api/routes/health.py tests/test_fetcher_enable_switch.py
git commit -m "feat: make unavailable_reason() final so the enable switch cannot be bypassed"
```

---

### Task 6: Metadata test + `.env.example` + CLAUDE.md

**Files:**
- Modify: `tests/test_zzshare_fetcher.py` (add an `is_enabled` assertion to `TestZzshareFetcherMetadata`)
- Modify: `.env.example` (new enable section)
- Modify: `CLAUDE.md` (Configuration section)

**Interfaces:**
- Consumes: everything from Tasks 1–5. No new symbols produced.

- [ ] **Step 1: Add the metadata assertion**

In `tests/test_zzshare_fetcher.py`, inside `class TestZzshareFetcherMetadata`, add directly after the existing `test_priority_default`:

```python
    def test_is_enabled_default(self, monkeypatch):
        """The <SLUG>_ENABLED switch defaults to enabled.

        Sits next to test_priority_default because both are metadata
        switches read the same way from the env; unlike ``priority`` this
        one re-reads per call, so it needs no source-inspection dance.
        """
        monkeypatch.delenv("ZZSHARE_ENABLED", raising=False)
        assert ZzshareFetcher.is_enabled() is True
```

Run: `python -m pytest tests/test_zzshare_fetcher.py -v -k metadata`
Expected: PASS

- [ ] **Step 2: Document the switch in `.env.example`**

Insert a new section immediately before the `# === Feature Flags ===` section:

```bash
# === Per-Fetcher Enable Switch ===
# Each fetcher can be turned off entirely. Default: true (enabled).
# The var name is <SLUG>_ENABLED, where <SLUG> is the same slug used by
# ?source= and by the <SLUG>_PRIORITY vars above:
#   tushare / baostock / akshare / yfinance / zhitu / zzshare / tencent
#   eastmoney / baidu / ths / cninfo / cls / myquant
# Set to false / 0 / no / off to disable (case-insensitive).
#
# Disabling means the fetcher is not instantiated and not registered with
# the manager, so it disappears from capability routing AND from
# ?source= source routing in one stroke. Note that the fetcher's module is
# still imported (data_provider/__init__.py re-exports every class and the
# explorer needs the class objects to describe disabled sources).
#
# Takes effect on process restart — same as the *_PRIORITY vars.
#
# !! Two values have non-obvious blast radius — read before using !!
#
# THS_ENABLED=false  breaks the ENTIRE board path. The board cache is keyed
#   on source='ths' no matter who served the request, and ?source=zzshare is
#   aliased to 'ths' on board endpoints. No other fetcher can serve those
#   routes, so ?source= cannot route around it.
#
# ZZSHARE_ENABLED=false  removes the internal PRIMARY of the board
#   include_quote=false chain. source='ths' + include_quote=false runs a
#   ZZSHARE-primary/THS-fallback chain internally, so disabling zzshare
#   degrades a chain the caller never named.
#
# /control/fetcher-test deliberately still works for a disabled fetcher —
# it exists so you can verify an upstream source before enabling it.

# TUSHARE_ENABLED=true
# BAOSTOCK_ENABLED=true
# AKSHARE_ENABLED=true
# YFINANCE_ENABLED=true
# ZHITU_ENABLED=true
# ZZSHARE_ENABLED=true
# TENCENT_ENABLED=true
# EASTMONEY_ENABLED=true
# BAIDU_ENABLED=true
# THS_ENABLED=true
# CNINFO_ENABLED=true
# CLS_ENABLED=true
# MYQUANT_ENABLED=true
```

- [ ] **Step 3: Add the knob to CLAUDE.md's Configuration list**

In `CLAUDE.md`, in the `## Configuration` section, add a bullet after the `*_PRIORITY` bullet:

```markdown
- `*_ENABLED` env vars — per-fetcher on/off switch, default `true`
  (`ZHITU_ENABLED=false` / `0` / `no` / `off`). Read once at
  `create_default_manager()`; requires a restart, like `*_PRIORITY`. A
  disabled fetcher is not instantiated and not registered, so it leaves
  both capability routing (`_filter_by_capability`) and source routing
  (`_slug_index` → `_with_source`) at once; `?source=<disabled>` reports
  400 `source 'x' is disabled by X_ENABLED=false`, and the explorer
  manifest + `/healthz` keep the row with `available: false` + that reason.
  **`unavailable_reason()` is final on `BaseFetcher`** — subclasses
  implement `_subclass_unavailable_reason()` so the switch cannot be
  bypassed by an override.
  **`THS_ENABLED=false` breaks all board endpoints** (the board cache is
  keyed `source='ths'` and `zzshare` is aliased to `ths` there);
  **`ZZSHARE_ENABLED=false`** removes the internal primary of the board
  `include_quote=false` chain. `/control/fetcher-test` still probes
  disabled fetchers by design.
```

- [ ] **Step 4: Run the full default test suite**

Run: `python -m pytest`
Expected: PASS. This is the widest safety net for a change that touches the registration path every test session depends on. Default run skips `live_network`/`requires_token` (~1 min).

- [ ] **Step 5: Run lint**

Run: `ruff check .`
Expected: no errors. Fix any unused-import or formatting complaints with `ruff format .` on the touched files.

- [ ] **Step 6: Commit**

```bash
git add tests/test_zzshare_fetcher.py .env.example CLAUDE.md
git commit -m "docs: document <SLUG>_ENABLED switch + pin ZzshareFetcher.is_enabled default"
```

---

## Manual verification

After the plan is implemented, verify the switch end-to-end (not just via unit tests):

- [ ] Start the server with one source disabled and confirm the log line:
  ```bash
  ZHITU_ENABLED=false python -m stock_data.server
  ```
  Expected: `ZhituFetcher disabled by ZHITU_ENABLED` in the startup log, and no `ZhituFetcher added`. Note: per the memory note on orphaned servers, check `netstat -ano | grep LISTENING` before launching rather than killing an unknown PID on port 8888.

- [ ] With the server up, hit a source-routed endpoint naming the disabled source:
  ```bash
  curl -s "http://127.0.0.1:8888/api/v1/boards/885556/stocks?source=zhitu" | head -c 400
  ```
  Expected: HTTP 400 with `source 'zhitu' is disabled by ZHITU_ENABLED=false`.

- [ ] Confirm the explorer manifest keeps the row:
  ```bash
  curl -s http://127.0.0.1:8888/control/api-manifest | python -c "import json,sys; m=json.load(sys.stdin); [print(f['name'], f['available'], f.get('reason')) for s in m['sections'] for e in s['endpoints'] for f in e['fetchers'] if f['name']=='ZhituFetcher'][:1]"
  ```
  Expected: `ZhituFetcher False disabled by ZHITU_ENABLED=false`.

- [ ] Confirm `/healthz` agrees with the manifest (must not say available=true for a disabled source):
  ```bash
  curl -s "http://127.0.0.1:8888/healthz?details=true" | python -c "import json,sys; d=json.load(sys.stdin); [print(s['name'], s['available'], s.get('unavailable_reason')) for s in d['sources'] if s['name']=='ZhituFetcher']"
  ```
  Expected: `ZhituFetcher False disabled by ZHITU_ENABLED=false` — the same verdict the manifest gave.

- [ ] Confirm `/control/fetcher-test` still probes the disabled fetcher (the intentional bypass):
  ```bash
  curl -s -X POST http://127.0.0.1:8888/control/fetcher-test -H "Content-Type: application/json" -d '{"fetcher":"ZhituFetcher","method":"get_stock_info","params":{}}' | head -c 200
  ```
  Expected: a normal result or a `FetcherUnavailable` classification — not a crash and not `UnknownFetcher`.

- [ ] Confirm the same endpoint returns 200 (not 500) for a genuinely unknown name — the pre-existing bug this plan's route guard fixes:
  ```bash
  curl -s -o /dev/null -w "%{http_code}\n" -X POST http://127.0.0.1:8888/control/fetcher-test -H "Content-Type: application/json" -d '{"fetcher":"ghost","method":"get_stock_info","params":{}}'
  ```
  Expected: `200`.

- [ ] Delete the docs-only spec/plan pair or leave them in place per repo convention (previous plans under `docs/superpowers/plans/` are kept).

## Out of scope

- Runtime toggling without a restart, and any `/control/*` write endpoint for the switch.
- A single `DISABLED_FETCHERS=a,b` list variable.
- Skipping the module import when disabled (see Global Constraints).
- Any change to `DataCapability` / `CAPABILITY_TO_METHOD` — this is not a new capability, so `tests/test_capability_method_map.py` is untouched.
