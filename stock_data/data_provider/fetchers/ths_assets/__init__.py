"""Vendor'd THS assets.

This package holds ``ths.js`` — the JavaScript obfuscator THS ships on its
board-K-line endpoints, evaluated by ``py_mini_racer`` to mint the
``v=...`` cookie that authenticates requests to d.10jqka.com.cn and
q.10jqka.com.cn.

The asset is force-included into the project wheel via
``pyproject.toml`` ``[tool.hatch.build.targets.wheel.force-include]``, so
installs don't depend on ``akshare`` being present at runtime — that's a
fetcher boundary we explicitly enforce (peer fetchers must not reach into
each other's package data).
"""
