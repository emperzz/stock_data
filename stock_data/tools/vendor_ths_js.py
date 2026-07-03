"""CLI: refresh the vendored ``ths.js`` blob from an installed akshare wheel.

Use this when THS rotates the v-cookie obfuscator upstream (typically
every 3–12 months).  The vendored blob is what ThsFetcher evaluates in
``py_mini_racer`` to mint the ``v=`` cookie that authenticates requests
to ``d.10jqka.com.cn`` and ``q.10jqka.com.cn``.

Scope
-----
This is a BUILD-TIME / OPERATOR-TIME tool. It is allowed to import
``akshare.datasets`` to locate the source file; the server RUNTIME
must not import from akshare (CLAUDE.md anti-pattern: peer fetchers
must not reach into each other's packages). The vendored copy is what
ships with our wheel.

The akshare + importlib.resources imports live INSIDE ``main()`` so
that merely importing this module (e.g. for inspection or for sibling
tools to reuse ``_sha256_short``) does not pull in akshare's full
dependency tree.

Concurrency
-----------
This script is NOT lock-safe — two concurrent invocations racing the
write path can leave ``ths.js`` half-written. If a server is running,
pause it before re-vendoring (or run on a CI box that's offline).

Workflow
--------
1. ``python -m pip install -U akshare`` — pick up akshare's latest wheel
   (which carries the rotated ``ths.js``).
2. ``python -m stock_data.tools.vendor_ths_js`` — copy into our assets.
3. ``python -m pytest tests/test_ths_assets.py tests/test_ths_board_kline.py -v``
4. Commit the changed ``ths.js`` and push.

If source and destination SHA-256 hashes match, the script exits 0
without writing — idempotent no-op when nothing has rotated yet.

Reference: docs/maintenance/ths_js_vendor_runbook.md
"""

from __future__ import annotations

import hashlib


def _sha256_short(path) -> str:
    """Return the first 12 chars of the SHA-256 of ``path``."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(64 * 1024), b""):
            h.update(block)
    return h.hexdigest()[:12]


def main() -> int:
    """Copy akshare's vendored ths.js into our ths_assets/ package.

    Side-effect imports (akshare, importlib.resources) happen here so
    that ``import stock_data.tools.vendor_ths_js`` is cheap.
    """
    # The ONE allowed akshare import in the runtime codebase — operator-time
    # only. See module docstring and CLAUDE.md.
    import os
    from importlib.resources import files

    from akshare.datasets import get_ths_js

    from stock_data.data_provider.fetchers import ths_assets as ours

    src_path = get_ths_js("ths.js")
    src_hash = _sha256_short(src_path)
    src_size = os.path.getsize(src_path)

    dst_path = files(ours).joinpath("ths.js")
    dst_hash = _sha256_short(dst_path) if dst_path.is_file() else None

    print(f"source: {src_path}  sha256={src_hash}  size={src_size}")
    if dst_hash is not None:
        print(f"dest:   {dst_path}  sha256={dst_hash}  (existing)")
    else:
        print(f"dest:   {dst_path}  (not yet vendored)")

    if dst_hash == src_hash:
        print("already in sync — nothing to do")
        return 0

    # NOT lock-safe: see module docstring.
    with open(src_path, "rb") as f:
        data = f.read()
    with open(dst_path, "wb") as f:
        f.write(data)
    print(f"wrote {dst_path} ({len(data)} bytes, sha256={src_hash})")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
