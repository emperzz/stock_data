# THS v-cookie `ths.js` vendor runbook

`ThsFetcher` mints the `v=` cookie that authenticates board-K-line
requests to `d.10jqka.com.cn` and `q.10jqka.com.cn`. The mint comes
from running an obfuscated JavaScript blob (~40KB, 989 lines) inside
`py_mini_racer.MiniRacer().call("v")`.

We **vendor** the blob — `stock_data/data_provider/fetchers/ths_assets/ths.js` —
rather than reaching into `akshare.utils.demjson` or `akshare.datasets.get_ths_js`
at server runtime. Vendor'ing keeps fetcher ↔ fetcher isolated
(CLAUDE.md anti-pattern: peer fetchers don't reach into each other).

## Why we don't self-host the algorithm

`ths.js`'s `v()` calls browser-API fingerprinting primitives
(`navigator.userAgent`, `document.cookie`, `window.addEventListener`).
Re-implementing in Python means a fake-DOM layer or a headless
browser — both unacceptable for a server-side fetcher. Vendor +
occasional sync keeps the operational cost at ~5 minutes per
rotation (the time to run the script, eyeball the diff, push).

## When to re-vendor

Re-vendor when **any** of the following is true:

- `/boards/{code}/history?source=ths` returns 5xx on boards that
  used to work, especially with `[ThsFetcher] could not resolve
  concept clid for slug='xxx'` or all year-fetches empty
  (cached v-token rejected by upstream).
- `d.10jqka.com.cn` returns 403 on every `bk_*/01/{year}.js`
  request even after a server restart.
- akshare's GitHub tracker has a recent "THS board index broken"
  ticket.
- It's been ≥ 3 months since the last sync (THS rotates on a long
  interval but rare in practice; the proactive cadence is a backstop).

## Sync steps

1. Pick up akshare's fixed wheel:
   ```bash
   python -m pip install -U akshare
   ```
2. Vendor the new blob:
   ```bash
   python -m stock_data.tools.vendor_ths_js
   ```
   The script prints source vs destination SHA-256 (`...12 chars`)
   and size. If hashes already match, it exits without writing
   (idempotent — safe to run on a cron).
3. Run regression tests:
   ```bash
   python -m pytest tests/test_ths_assets.py tests/test_ths_board_kline.py -v
   ```
4. Optional live-network sanity check (marked `live_network`, skipped
   by default; unskip when investigating a real outage):
   ```bash
   python -m pytest tests/test_ths_board_kline.py::TestGetBoardHistory -m live_network
   ```
5. Commit the changed `ths.js` and push:
   ```bash
   git add stock_data/data_provider/fetchers/ths_assets/ths.js
   git commit -m "chore(ths): vendor rotated ths.js from akshare <version>"
   git push
   ```

## Wheel / sdist shipping

`ths_assets/` is configured under BOTH `[tool.hatch.build.targets.wheel.force-include]`
and `[tool.hatch.build.targets.sdist.force-include]` in `pyproject.toml`.
Verify a built wheel/sdist actually contains the blob before publishing:

```bash
python -m build --wheel   # → dist/stock_data-*.whl
unzip -l dist/stock_data-*.whl | grep ths.js
# Expected: 1 entry matching stock_data/data_provider/fetchers/ths_assets/ths.js
```

If the entry is missing, the force-include config regressed — re-add
the `[tool.hatch.build.targets.wheel.force-include]` line.

## Notes on the script

`stock_data/tools/vendor_ths_js.py` imports `from akshare.datasets import get_ths_js`.
This is the **one** allowed akshare import in the runtime codebase,
deliberately scoped to operator-time. Server runtime MUST NOT import
this — see CLAUDE.md "fetcher doesn't reach into peer fetcher's utils"
anti-pattern.

If `py_mini_racer` is missing, `ThsFetcher.is_available()` returns
False and the explorer manifest surfaces a specific reason via
`unavailable_reason()`. The same checks fire on first request that
needs the v-cookie, so server uptime doesn't depend on ths.js shipping
for non-board-K-line callers (hot-topics / north-flow / search-news).
