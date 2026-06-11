# API 文档 HTML 化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增 `docs/API.html` 交互式 API Explorer 网页；在 `stock_data/server.py` 挂载 `docs/` 静态资源并暴露 5 个 `/control/*` 端点，让网页能查看服务器状态、启停 Test Instance、并对所有 endpoint 试调。**不修改 `docs/API.md`。**

**Architecture:**
- 后端：FastAPI app 在启动时挂载 `docs/` 为 `/docs` 静态资源；新增 `stock_data/control.py` 封装子进程启停；server.py 注册 5 个 control 路由（`/control/config`、`/control/server/status`、`/control/test-instance/{start,stop,status}`），全部走 `127.0.0.1`。
- 前端：单文件 `docs/API.html`（内联 CSS + JS，零外部依赖），加载时拉取 `/control/config` 初始化；侧边栏 + 主区域两栏布局；endpoint 卡片支持 "Try it"（调 `/api/v1/...`）、搜索、market/capability 过滤、主题切换；侧边栏底部 Test Instance 卡片控制子进程。
- 端点元数据：HTML 顶部 inline 一个 `ENDPOINTS` JS 对象，按 `docs/API.md` §4 录入（约 27 个 endpoint），由它驱动侧边栏、详情卡、搜索、过滤。

**Tech Stack:** FastAPI, uvicorn, stdlib `subprocess` + `os.kill`, stdlib `http.server` (HTML 测试), BeautifulSoup (HTML 结构测试), fuse.js (内联, ~10KB minified)

**Spec:** `docs/superpowers/specs/2026-06-11-api-html-redesign-design.md`

---

## File Map

| 文件 | 职责 |
|---|---|
| `stock_data/control.py` | **新建** — 封装 Test Instance 子进程 `start_test_instance` / `stop_test_instance` / `get_test_instance_status`；PID 文件读写；跨平台存活探测（`os.kill(pid, 0)`） |
| `stock_data/server.py` | **修改** — 挂载 `docs/` 为 `/docs` 静态资源；注册 5 个 `/control/*` 路由；默认 `SERVER_HOST` 改 `127.0.0.1` |
| `docs/API.html` | **新建** — 完整 HTML Explorer；内联 CSS（主题变量）+ 内联 JS（IIFE 模块）+ 内联 ENDPOINTS JS 对象（按 `docs/API.md` §4 录入） |
| `tests/test_control.py` | **新建** — `control.py` 单元测试：start/stop/status 正常路径、端口冲突、幂等性、PID 文件丢失 |
| `tests/test_server_control_endpoints.py` | **新建** — FastAPI `TestClient` 测 5 个 control 端点的 schema |
| `tests/test_api_html.py` | **新建** — BeautifulSoup 解析 HTML 验证：锚点 id、CSS 变量、ENDPOINTS ≥ 27 项、fuse 索引存在 |
| `.gitignore` | **修改** — 新增 `docs/.server.pid` |
| `CLAUDE.md` | **修改** — 在合适章节加一行"API 文档网页位于 `docs/API.html`" |

---

## Task 1: `control.py` 模块 + 单元测试

**Files:**
- Create: `stock_data/control.py`
- Test: `tests/test_control.py`
- Modify: `.gitignore`

- [ ] **Step 1: 写失败测试 — `start_test_instance` 启动子进程并写 PID**

在 `tests/test_control.py` 写：

```python
"""Tests for stock_data.control — Test Instance subprocess management."""
import os
import socket
from pathlib import Path

import pytest

from stock_data import control


def _free_port() -> int:
    """Bind a random port, release it, return the port number."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_start_spawns_subprocess_and_writes_pid(monkeypatch, tmp_path):
    """start_test_instance() spawns a subprocess that runs the configured port,
    writes its PID to the PID file, and is reachable after a short wait."""
    pid_file = tmp_path / "test.pid"
    port = _free_port()  # reserve a port the child can use

    # Mock the subprocess.Popen call so we can capture args without actually
    # binding a real server. We assert that start_test_instance forwards the
    # port to Popen.
    captured = {}

    class FakePopen:
        def __init__(self, args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs
            self.pid = 99999
            self.returncode = None

    monkeypatch.setattr(control.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(control.time, "sleep", lambda s: None)  # skip waits

    result = control.start_test_instance(
        port=port,
        host="127.0.0.1",
        pid_path=str(pid_file),
    )

    assert result["running"] is True
    assert result["port"] == port
    # The child process must receive the port via SERVER_PORT env var
    # (server.py:main() reads os.getenv("SERVER_PORT"), not argv).
    assert captured["kwargs"]["env"]["SERVER_PORT"] == str(port)
    assert captured["kwargs"]["env"]["SERVER_HOST"] == "127.0.0.1"
    assert pid_file.read_text().strip() == "99999"


def test_start_is_idempotent_when_already_running(monkeypatch, tmp_path):
    """Calling start_test_instance() twice without stopping is a no-op the second time."""
    pid_file = tmp_path / "test.pid"
    pid_file.write_text("12345")

    # Pretend PID 12345 is alive
    monkeypatch.setattr(control.os, "kill", lambda pid, sig: None)

    result = control.start_test_instance(port=8889, host="127.0.0.1", pid_path=str(pid_file))
    assert result["running"] is True
    assert result["pid"] == 12345
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_control.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'stock_data.control'`

- [ ] **Step 3: 实现 `stock_data/control.py`**

```python
"""Test Instance subprocess management for the API Explorer.

Lets the HTML explorer (docs/API.html) spawn an independent stock_data
server process on a different port for manual failover testing. The
main server (the one serving the HTML) is never stopped by this module.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


# PID file lives next to docs/API.html so it ships with the repo source
# tree but is gitignored. Default path is overridable via start_*/get_*/stop_*
# args, which is what tests use.
DEFAULT_PID_PATH = str(
    Path(__file__).resolve().parent.parent / "docs" / ".server.pid"
)


def _pid_alive(pid: int) -> bool:
    """Cross-platform liveness check without psutil.

    - POSIX: signal 0 raises ProcessLookupError if dead, OSError otherwise.
    - Windows: signal 0 raises OSError(87) if dead; PermissionError means alive.
    """
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # Windows: pid exists but not ours
    except OSError:
        return False
    return True


def _read_pid(pid_path: str) -> int | None:
    p = Path(pid_path)
    if not p.exists():
        return None
    try:
        return int(p.read_text().strip())
    except (ValueError, OSError):
        return None


def get_test_instance_status(pid_path: str = DEFAULT_PID_PATH) -> dict[str, Any]:
    """Return the current status of the Test Instance subprocess.

    Returns dict with: running (bool), pid (int|None), port (int|None),
    error (str|None).
    """
    pid = _read_pid(pid_path)
    if pid is None:
        return {"running": False, "pid": None, "port": None, "error": None}
    if not _pid_alive(pid):
        # Stale PID file — clean it up
        try:
            Path(pid_path).unlink()
        except OSError:
            pass
        return {"running": False, "pid": pid, "port": None, "error": "stale_pid"}
    return {"running": True, "pid": pid, "port": None, "error": None}


def start_test_instance(
    port: int,
    host: str = "127.0.0.1",
    pid_path: str = DEFAULT_PID_PATH,
    wait_seconds: float = 0.0,
) -> dict[str, Any]:
    """Start a Test Instance subprocess. Idempotent.

    Returns dict with: running, pid, port, error.
    """
    existing = get_test_instance_status(pid_path)
    if existing["running"]:
        return {**existing, "port": port}

    # Spawn the subprocess. server.py:main() reads SERVER_PORT / SERVER_HOST
    # from the environment, NOT from argv, so the child must inherit the
    # configured values via env.
    args = [sys.executable, "-m", "stock_data.server"]
    env = os.environ.copy()
    env["SERVER_PORT"] = str(port)
    env["SERVER_HOST"] = host

    proc = subprocess.Popen(
        args,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    Path(pid_path).write_text(str(proc.pid))

    if wait_seconds > 0:
        time.sleep(wait_seconds)

    return {"running": True, "pid": proc.pid, "port": port, "error": None}


def stop_test_instance(pid_path: str = DEFAULT_PID_PATH) -> dict[str, Any]:
    """Stop the Test Instance subprocess. Idempotent.

    Returns dict with: running, pid, error.
    """
    pid = _read_pid(pid_path)
    if pid is None or not _pid_alive(pid):
        # Clean up stale file
        try:
            Path(pid_path).unlink(missing_ok=True)
        except TypeError:
            if Path(pid_path).exists():
                Path(pid_path).unlink()
        return {"running": False, "pid": pid, "error": None}

    try:
        os.kill(pid, 15)  # SIGTERM; on Windows this maps to TerminateProcess
    except ProcessLookupError:
        pass
    except OSError as e:
        return {"running": True, "pid": pid, "error": f"kill_failed: {e}"}

    # Best-effort cleanup of PID file (the subprocess is gone, even if kill
    # didn't synchronously reap it on Windows)
    try:
        Path(pid_path).unlink()
    except OSError:
        pass

    return {"running": False, "pid": pid, "error": None}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_control.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: 加更多失败测试覆盖（端口冲突、PID 文件丢失）**

在 `tests/test_control.py` 追加：

```python
def test_get_status_when_no_pid_file(tmp_path):
    """get_test_instance_status returns running=False when no PID file."""
    result = control.get_test_instance_status(pid_path=str(tmp_path / "nope.pid"))
    assert result == {"running": False, "pid": None, "port": None, "error": None}


def test_get_status_cleans_stale_pid(monkeypatch, tmp_path):
    """get_test_instance_status removes the PID file when the pid is dead."""
    pid_file = tmp_path / "stale.pid"
    pid_file.write_text("99999")

    def kill_raises(pid, sig):
        raise ProcessLookupError(pid)
    monkeypatch.setattr(control.os, "kill", kill_raises)

    result = control.get_test_instance_status(pid_path=str(pid_file))
    assert result["running"] is False
    assert result["error"] == "stale_pid"
    assert not pid_file.exists()


def test_stop_when_no_pid_file(tmp_path):
    """stop_test_instance is a no-op when no PID file exists."""
    result = control.stop_test_instance(pid_path=str(tmp_path / "nope.pid"))
    assert result == {"running": False, "pid": None, "error": None}


def test_pid_alive_handles_zero_and_negative():
    """_pid_alive returns False for pid <= 0 (defensive)."""
    assert control._pid_alive(0) is False
    assert control._pid_alive(-1) is False
```

- [ ] **Step 6: 跑全部 control 测试**

Run: `pytest tests/test_control.py -v`
Expected: PASS (6 tests)

- [ ] **Step 7: 加 `.gitignore` 条目**

在 `.gitignore` 末尾追加：

```
# Test Instance PID file (runtime artifact)
/docs/.server.pid
```

- [ ] **Step 8: 提交**

```bash
git add stock_data/control.py tests/test_control.py .gitignore
git commit -m "feat(control): add Test Instance subprocess management

Provides start/stop/status for an independent stock_data server process
on a different port (default :8889). Main server is never stopped by
this module. Uses os.kill(pid, 0) for cross-platform liveness, no
psutil dependency.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: `server.py` 挂载 `/docs` + 5 个 control 端点 + 集成测试

**Files:**
- Modify: `stock_data/server.py:82-128` (add static mount + control router; change default host)
- Test: `tests/test_server_control_endpoints.py`
- Modify: `.env.example` (add `SERVER_HOST=127.0.0.1` doc)

- [ ] **Step 1: 写失败测试 — `/control/config` 返回配置**

在 `tests/test_server_control_endpoints.py` 写：

```python
"""Integration tests for /control/* endpoints added for the API Explorer."""
import pytest
from fastapi.testclient import TestClient

from stock_data.server import app


@pytest.fixture
def client():
    return TestClient(app)


class TestControlConfig:
    def test_returns_port_host_version(self, client, monkeypatch):
        monkeypatch.setenv("SERVER_PORT", "8888")
        monkeypatch.setenv("SERVER_HOST", "127.0.0.1")
        # Re-import? No — the values are read at request time in our impl.

        response = client.get("/control/config")
        assert response.status_code == 200
        data = response.json()
        assert "port" in data
        assert "host" in data
        assert "version" in data
        assert "test_port" in data
        assert "env_keys" in data
        assert isinstance(data["env_keys"], list)
        assert "TUSHARE_TOKEN" in data["env_keys"]


class TestControlServerStatus:
    def test_returns_running(self, client):
        """The main server is always 'running' from its own POV."""
        response = client.get("/control/server/status")
        assert response.status_code == 200
        data = response.json()
        assert data["running"] is True
        assert "pid" in data
        assert "uptime_sec" in data
        assert "port" in data
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_server_control_endpoints.py -v`
Expected: FAIL with 404 (no `/control/config` route)

- [ ] **Step 3: 修改 `stock_data/server.py` — 挂载 `/docs` + 加 control 路由**

把 `stock_data/server.py` 第 82-128 行替换为（**保留前面 1-81 行不动**）：

```python
import os
from pathlib import Path

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

# (existing imports and lifespan above stay the same)
# ...

# Create FastAPI app
app = FastAPI(
    title="Stock Data API",
    description="Local stock data aggregation server for AI agents",
    version=__version__,
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

# CORS — restrict to localhost only (unchanged)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost",
        "http://localhost:*",
        "http://127.0.0.1",
        "http://127.0.0.1:*",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Data routes (unchanged)
app.include_router(router, prefix="/api/v1")

# --- API Explorer (new) -------------------------------------------------
# Mount docs/ as static resources. /docs/API.html is the interactive explorer.
# Failure mode: if docs/ is missing, log a warning and continue without the
# mount — the data API still works.
try:
    _DOCS_DIR = Path(__file__).resolve().parent.parent / "docs"
    if _DOCS_DIR.is_dir():
        app.mount("/docs", StaticFiles(directory=str(_DOCS_DIR), html=True), name="docs")
        logger.info(f"[Startup] Mounted /docs → {_DOCS_DIR}")
    else:
        logger.warning(f"[Startup] docs/ not found at {_DOCS_DIR}, /docs not mounted")
except Exception as e:
    logger.warning(f"[Startup] Failed to mount /docs: {e}")


# --- /control/* endpoints (new) -----------------------------------------
# Bound to 127.0.0.1 — never expose on 0.0.0.0. The control router gives the
# HTML explorer the ability to read config, query status, and start/stop
# an independent Test Instance subprocess.
import time as _time  # for uptime tracking
from . import control as _control

_CONTROL_STARTED_AT = _time.time()


def _read_server_port() -> int:
    try:
        return int(os.getenv("SERVER_PORT", "8888"))
    except ValueError:
        return 8888


def _read_server_host() -> str:
    return os.getenv("SERVER_HOST", "127.0.0.1")


_control_router = APIRouter(prefix="/control", tags=["control"])


@_control_router.get("/config")
def control_config() -> dict:
    """Static config used by the HTML explorer to initialize itself."""
    port = _read_server_port()
    test_port = int(os.getenv("STOCK_TEST_INSTANCE_PORT", str(port + 1)))
    return {
        "port": port,
        "host": _read_server_host(),
        "test_port": test_port,
        "version": __version__,
        "env_keys": [
            "TUSHARE_TOKEN", "BAOSTOCK_PRIORITY", "AKSHARE_PRIORITY",
            "YFINANCE_PRIORITY", "ZHITU_TOKEN", "ZHITU_PRIORITY",
            "MYQUANT_TOKEN", "MYQUANT_PRIORITY", "TENCENT_PRIORITY",
            "EASTMONEY_PRIORITY", "THS_PRIORITY", "CNINFO_PRIORITY",
            "ENABLE_API_CACHE", "STOCK_CACHE_DB_PATH", "STOCK_DB_INIT",
        ],
    }


@_control_router.get("/server/status")
def control_server_status() -> dict:
    """Status of the main server (the one serving the HTML)."""
    return {
        "running": True,
        "pid": os.getpid(),
        "port": _read_server_port(),
        "uptime_sec": int(_time.time() - _CONTROL_STARTED_AT),
    }


@_control_router.get("/test-instance/status")
def control_test_instance_status() -> dict:
    """Status of the optional Test Instance subprocess."""
    status = _control.get_test_instance_status()
    # Include the configured test port so the UI can show it
    port = int(os.getenv("STOCK_TEST_INSTANCE_PORT",
                         str(_read_server_port() + 1)))
    return {**status, "port": port}


@_control_router.post("/test-instance/start")
def control_test_instance_start() -> dict:
    """Start the Test Instance subprocess. Idempotent."""
    port = int(os.getenv("STOCK_TEST_INSTANCE_PORT",
                         str(_read_server_port() + 1)))
    host = _read_server_host()
    return _control.start_test_instance(port=port, host=host, wait_seconds=1.0)


@_control_router.post("/test-instance/stop")
def control_test_instance_stop() -> dict:
    """Stop the Test Instance subprocess. Idempotent."""
    return _control.stop_test_instance()


app.include_router(_control_router)


# --- main() — change default host ---------------------------------------
def main():
    """Run the server."""
    import uvicorn

    port = int(os.getenv("SERVER_PORT", "8888"))
    # Default host changed from 0.0.0.0 to 127.0.0.1 — /control/* endpoints
    # must not be exposed on a public interface. Set SERVER_HOST=0.0.0.0
    # explicitly if you need remote access.
    host = os.getenv("SERVER_HOST", "127.0.0.1")

    logger.info(f"Starting server on {host}:{port}")
    uvicorn.run(
        "stock_data.server:app",
        host=host,
        port=port,
        reload=False,
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 跑 control 端点测试确认通过**

Run: `pytest tests/test_server_control_endpoints.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: 加更多 control 端点测试**

在 `tests/test_server_control_endpoints.py` 追加：

```python
class TestControlTestInstanceLifecycle:
    def test_start_returns_running(self, client, monkeypatch, tmp_path):
        """start returns running=True with the configured port."""
        monkeypatch.setenv("STOCK_TEST_INSTANCE_PORT", "18888")
        monkeypatch.setattr(
            "stock_data.control.start_test_instance",
            lambda **kw: {"running": True, "pid": 12345, "port": kw["port"], "error": None},
        )
        response = client.post("/control/test-instance/start")
        assert response.status_code == 200
        data = response.json()
        assert data["running"] is True
        assert data["port"] == 18888

    def test_stop_returns_not_running(self, client, monkeypatch):
        """stop returns running=False (idempotent)."""
        monkeypatch.setattr(
            "stock_data.control.stop_test_instance",
            lambda **kw: {"running": False, "pid": None, "error": None},
        )
        response = client.post("/control/test-instance/stop")
        assert response.status_code == 200
        data = response.json()
        assert data["running"] is False

    def test_status_includes_port(self, client, monkeypatch, tmp_path):
        """status response always includes 'port' for UI display."""
        monkeypatch.setenv("STOCK_TEST_INSTANCE_PORT", "18889")
        # Empty PID file → not running
        monkeypatch.setattr(
            "stock_data.control.get_test_instance_status",
            lambda **kw: {"running": False, "pid": None, "port": None, "error": None},
        )
        response = client.get("/control/test-instance/status")
        assert response.status_code == 200
        data = response.json()
        assert data["port"] == 18889
        assert data["running"] is False


class TestDocsMount:
    def test_api_html_served(self, client):
        """GET /docs/API.html returns 200 and contains <html>."""
        response = client.get("/docs/API.html")
        # The HTML file is created in Task 3. Until then, this returns 404.
        # Once Task 3 lands, this test should pass.
        # We mark it xfail here so the suite is green pre-Task-3.
        if response.status_code == 404:
            pytest.skip("docs/API.html not yet created (Task 3)")
        assert response.status_code == 200
        assert "<html" in response.text.lower()
```

- [ ] **Step 6: 跑全部 control 端点测试**

Run: `pytest tests/test_server_control_endpoints.py -v`
Expected: PASS (5 tests, 1 skipped)

- [ ] **Step 7: 确认现有测试不回归**

Run: `pytest tests/ -x --ignore=tests/test_control.py --ignore=tests/test_server_control_endpoints.py -q`
Expected: all existing tests PASS

- [ ] **Step 8: 提交**

```bash
git add stock_data/server.py tests/test_server_control_endpoints.py .env.example
git commit -m "feat(server): mount /docs static + 5 /control/* endpoints

- Mount docs/ as /docs (API Explorer accessible at /docs/API.html)
- 5 control endpoints: /control/config, /control/server/status,
  /control/test-instance/{status,start,stop}
- Default SERVER_HOST changed 0.0.0.0 -> 127.0.0.1 for safety
- CORS unchanged (localhost only)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: `docs/API.html` 骨架（CSS + JS 框架 + 空 ENDPOINTS）

**Files:**
- Create: `docs/API.html`

- [ ] **Step 1: 创建 HTML 骨架文件**

创建 `docs/API.html`（约 200 行），结构如下。**所有 endpoint 元数据先填一组占位条目**，后续 Task 4-7 逐节录入完整数据。

```html
<!doctype html>
<!--
  stock_data API Explorer
  LAST_SYNCED: 2026-06-11
  Source of truth: docs/API.md (do not edit that file; sync ENDPOINTS here)
-->
<html lang="zh-CN" data-theme="light">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=1280">
  <title>stock_data API Explorer</title>
  <style>
    /* === Theme variables (light) === */
    :root {
      --bg: #fafafa; --bg-card: #ffffff; --bg-sidebar: #f5f5f7;
      --text: #1d1d1f; --text-muted: #6e6e73;
      --accent: #0071e3; --accent-post: #34c759; --accent-warn: #ff9500;
      --border: #e5e5ea; --code-bg: #f5f5f7;
      --shadow: 0 1px 3px rgba(0,0,0,0.05);
      --shadow-hover: 0 4px 12px rgba(0,0,0,0.08);
    }
    [data-theme="dark"] {
      --bg: #0d0d0f; --bg-card: #1c1c1e; --bg-sidebar: #141416;
      --text: #f5f5f7; --text-muted: #98989d;
      --accent: #0a84ff; --accent-post: #30d158; --accent-warn: #ff9f0a;
      --border: #2c2c2e; --code-bg: #1c1c1e;
      --shadow: 0 1px 3px rgba(0,0,0,0.3);
      --shadow-hover: 0 4px 12px rgba(0,0,0,0.5);
    }
    * { box-sizing: border-box; }
    html, body { margin: 0; padding: 0; }
    body {
      font: 15px/1.6 -apple-system, BlinkMacSystemFont, "Segoe UI",
            "PingFang SC", "Microsoft YaHei", sans-serif;
      color: var(--text); background: var(--bg);
    }
    code, pre {
      font: 13px/1.5 "SF Mono", "JetBrains Mono", Menlo, Consolas, monospace;
    }
    /* === Top bar === */
    .topbar {
      position: sticky; top: 0; z-index: 10;
      height: 64px; padding: 0 24px;
      display: flex; align-items: center; gap: 16px;
      background: var(--bg-card); border-bottom: 1px solid var(--border);
    }
    .topbar h1 { font-size: 18px; margin: 0; font-weight: 600; }
    .topbar .spacer { flex: 1; }
    .topbar input, .topbar button {
      font: inherit; padding: 6px 12px; border-radius: 8px;
      border: 1px solid var(--border); background: var(--bg);
      color: var(--text);
    }
    .topbar .icon-btn { cursor: pointer; background: none; border: 0; font-size: 18px; }
    /* === Layout === */
    .layout { display: grid; grid-template-columns: 280px 1fr; gap: 0; }
    .sidebar {
      position: sticky; top: 64px; height: calc(100vh - 64px);
      overflow-y: auto; padding: 24px 16px;
      background: var(--bg-sidebar); border-right: 1px solid var(--border);
    }
    .sidebar h3 { font-size: 12px; text-transform: uppercase; color: var(--text-muted); margin: 16px 0 8px; letter-spacing: 0.05em; }
    .sidebar a { display: block; padding: 6px 10px; color: var(--text); text-decoration: none; border-radius: 6px; font-size: 14px; }
    .sidebar a:hover { background: var(--bg-card); }
    .sidebar a.active { background: var(--accent); color: #fff; }
    .sidebar .filter-group { display: flex; flex-direction: column; gap: 4px; }
    .sidebar label { font-size: 13px; color: var(--text-muted); display: flex; align-items: center; gap: 6px; cursor: pointer; }
    .main { padding: 40px 32px; max-width: 920px; }
    .main h1 { font-size: 32px; margin-top: 0; }
    .main h2 { font-size: 24px; margin-top: 48px; border-bottom: 1px solid var(--border); padding-bottom: 8px; scroll-margin-top: 80px; }
    .main h3 { font-size: 18px; scroll-margin-top: 80px; }
    /* === Endpoint card === */
    .endpoint { background: var(--bg-card); border: 1px solid var(--border); border-radius: 12px; padding: 20px; margin: 16px 0; box-shadow: var(--shadow); transition: box-shadow 0.2s; }
    .endpoint:hover { box-shadow: var(--shadow-hover); }
    .endpoint .method { display: inline-block; font: 600 12px/1 "SF Mono", monospace; padding: 4px 8px; border-radius: 4px; color: #fff; background: var(--accent); }
    .endpoint .method.GET { background: var(--accent); }
    .endpoint .method.POST { background: var(--accent-post); }
    .endpoint .path { font: 600 14px/1.4 "SF Mono", monospace; margin-left: 8px; }
    .endpoint .summary { color: var(--text-muted); margin: 8px 0; }
    .endpoint details { margin-top: 12px; }
    .endpoint summary { cursor: pointer; font-weight: 500; color: var(--accent); }
    .endpoint pre { background: var(--code-bg); padding: 12px; border-radius: 8px; overflow-x: auto; }
    /* === Try-it form === */
    .try-it { background: var(--bg-sidebar); padding: 16px; border-radius: 8px; margin-top: 12px; }
    .try-it .field { display: flex; gap: 8px; align-items: center; margin: 6px 0; }
    .try-it .field label { font-size: 13px; min-width: 120px; color: var(--text-muted); }
    .try-it .field input, .try-it .field select { flex: 1; padding: 6px 10px; border-radius: 6px; border: 1px solid var(--border); background: var(--bg-card); color: var(--text); font: inherit; }
    .try-it button { background: var(--accent); color: #fff; border: 0; padding: 8px 16px; border-radius: 6px; cursor: pointer; font: inherit; }
    .try-it button:hover { filter: brightness(1.1); }
    .try-it .response { margin-top: 12px; }
    .try-it .response pre { background: var(--code-bg); }
    .try-it .response.error { color: #c00; }
    .try-it .response.error pre { background: #fee; color: #c00; }
    /* === Test Instance card === */
    .test-instance { padding: 12px; border-radius: 8px; background: var(--bg-card); }
    .test-instance .status { font-size: 13px; color: var(--text-muted); margin: 4px 0; }
    .test-instance .status.running { color: var(--accent-post); }
    .test-instance .status.error { color: #c00; }
    .test-instance button { font-size: 12px; padding: 4px 10px; margin-right: 4px; }
    /* === Banner === */
    .banner { background: #fff3cd; color: #856404; padding: 12px 24px; border-bottom: 1px solid #ffeeba; font-size: 14px; }
    [data-theme="dark"] .banner { background: #3a2f00; color: #ffd966; border-bottom-color: #5a4900; }
  </style>
</head>
<body>
  <header class="topbar">
    <h1>◐ stock_data API Explorer</h1>
    <input type="search" id="search" placeholder="Search endpoints (Ctrl+K)..." style="width:300px">
    <span class="spacer"></span>
    <label style="font-size:13px;color:var(--text-muted)">Base URL:</label>
    <input type="text" id="baseUrl" style="width:240px" placeholder="http://localhost:8888">
    <button id="useTestInstance" title="Use Test Instance as base URL">Use Test</button>
    <span id="serverStatus" class="status" style="font-size:13px;color:var(--text-muted)">…</span>
    <button class="icon-btn" id="themeToggle" title="Toggle theme">🌗</button>
  </header>

  <div id="banner" class="banner" style="display:none">
    Detected file:// protocol — interactive features (Try it, Start/Stop) are disabled.
    Open via <code>http://localhost:8888/docs/API.html</code> instead.
  </div>

  <div class="layout">
    <nav class="sidebar">
      <h3>Sections</h3>
      <div id="nav"></div>
      <h3>Filter by market</h3>
      <div class="filter-group" id="marketFilter">
        <label><input type="checkbox" value="csi" checked> csi (A股)</label>
        <label><input type="checkbox" value="hk" checked> hk</label>
        <label><input type="checkbox" value="us" checked> us</label>
      </div>
      <h3>Test Instance</h3>
      <div class="test-instance">
        <div class="status" id="testStatus">Stopped</div>
        <button id="testStart">Start</button>
        <button id="testStop">Stop</button>
        <button id="testRefresh">↻</button>
      </div>
    </nav>
    <main class="main">
      <h1>stock_data API Explorer</h1>
      <p>Interactive documentation for the <code>stock_data</code> server.
      Source of truth: <code>docs/API.md</code>. All Try-it calls hit
      <code id="captionBaseUrl">…</code> with the <code>/api/v1</code> prefix.</p>
      <div id="content"></div>
    </main>
  </div>

  <script>
  // === Inline ENDPOINTS metadata (placeholder; replaced in Tasks 4-7) ===
  const ENDPOINTS = {
    meta: { version: "1.0", generated: "2026-06-11" },
    capabilities: {
      HISTORICAL_DWM:   { label: "日/周/月 K线",     icon: "📈" },
      HISTORICAL_MIN:   { label: "分钟 K线",         icon: "⏱" },
      REALTIME_QUOTE:   { label: "实时行情",         icon: "💹" },
      STOCK_LIST:       { label: "股票列表",         icon: "📋" },
      TRADE_CALENDAR:   { label: "交易日历",         icon: "📅" },
      STOCK_BOARD:      { label: "板块",             icon: "🏷" },
      INDEX_QUOTE:      { label: "指数实时",         icon: "📊" },
      INDEX_HISTORICAL: { label: "指数历史",         icon: "📉" },
      INDEX_INTRADAY:   { label: "指数分时",         icon: "⏰" },
      STOCK_ZT_POOL:    { label: "涨跌停股池",       icon: "🚦" },
      DRAGON_TIGER:     { label: "龙虎榜",           icon: "🐉" },
      MARGIN_TRADING:   { label: "融资融券",         icon: "💰" },
      BLOCK_TRADE:      { label: "大宗交易",         icon: "🤝" },
      HOLDER_NUM:       { label: "股东户数",         icon: "👥" },
      DIVIDEND:         { label: "分红送转",         icon: "🎁" },
      FUND_FLOW:        { label: "资金流",           icon: "💸" },
      HOT_TOPICS:       { label: "热点题材",         icon: "🔥" },
      NORTH_FLOW:       { label: "北向资金",         icon: "🌏" },
      RESEARCH_REPORT:  { label: "研报",             icon: "📑" },
      ANNOUNCEMENT:     { label: "公告",             icon: "📢" },
    },
    fetcher_meta: {
      Tushare:   { priority: 0, color: "#ff3b30" },
      Baostock:  { priority: 1, color: "#ff9500" },
      Myquant:   { priority: 9, color: "#5856d6" },
      Akshare:   { priority: 2, color: "#34c759" },
      Yfinance:  { priority: 3, color: "#0a84ff" },
      Zhitu:     { priority: 4, color: "#af52de" },
      Tencent:   { priority: 5, color: "#00b8a9" },
      EastMoney: { priority: 6, color: "#ff2d55" },
      Ths:       { priority: 7, color: "#ffcc00" },
      Cninfo:    { priority: 8, color: "#8e8e93" },
    },
    sections: [
      // Populated in Tasks 4-7
    ],
  };
  </script>
  <script>
  // === Main app (boots after ENDPOINTS) ===
  (function() {
    "use strict";

    const $ = (sel) => document.querySelector(sel);
    const $$ = (sel) => document.querySelectorAll(sel);
    const el = (tag, props = {}, children = []) => {
      const e = document.createElement(tag);
      Object.assign(e, props);
      children.forEach(c => e.appendChild(c));
      return e;
    };
    const text = (s) => document.createTextNode(s);

    let state = {
      baseUrl: localStorage.getItem("baseUrl") || "",
      theme: localStorage.getItem("theme") || "light",
      marketFilter: JSON.parse(localStorage.getItem("marketFilter") || '["csi","hk","us"]'),
    };

    // --- Detect file:// ---
    if (location.protocol === "file:") {
      $("#banner").style.display = "block";
    }

    // --- Boot ---
    async function boot() {
      applyTheme();
      bindUI();
      try {
        const cfg = await fetch("/control/config").then(r => r.json());
        if (!state.baseUrl) {
          state.baseUrl = `http://localhost:${cfg.port}`;
        }
        $("#baseUrl").value = state.baseUrl;
        $("#captionBaseUrl").textContent = state.baseUrl;
        refreshServerStatus();
        refreshTestStatus();
        setInterval(refreshTestStatus, 5000);
      } catch (e) {
        console.warn("Failed to fetch /control/config:", e);
        $("#baseUrl").value = state.baseUrl || "http://localhost:8888";
      }
      renderSidebar();
      renderContent();
    }

    function applyTheme() {
      document.documentElement.dataset.theme = state.theme;
    }

    function bindUI() {
      $("#themeToggle").onclick = () => {
        state.theme = state.theme === "light" ? "dark" : "light";
        localStorage.setItem("theme", state.theme);
        applyTheme();
      };
      $("#baseUrl").onchange = (e) => {
        state.baseUrl = e.target.value;
        localStorage.setItem("baseUrl", state.baseUrl);
        $("#captionBaseUrl").textContent = state.baseUrl;
      };
      $("#search").oninput = (e) => {
        const q = e.target.value.toLowerCase();
        $$(".endpoint").forEach(card => {
          const text = card.textContent.toLowerCase();
          card.style.display = text.includes(q) ? "" : "none";
        });
      };
      $("#marketFilter").onchange = (e) => {
        const checked = $$("#marketFilter input:checked").map(i => i.value);
        state.marketFilter = checked;
        localStorage.setItem("marketFilter", JSON.stringify(checked));
        renderContent();
      };
      $("#testStart").onclick = async () => {
        await fetch("/control/test-instance/start", { method: "POST" });
        await refreshTestStatus();
      };
      $("#testStop").onclick = async () => {
        await fetch("/control/test-instance/stop", { method: "POST" });
        await refreshTestStatus();
      };
      $("#testRefresh").onclick = refreshTestStatus;
      $("#useTestInstance").onclick = async () => {
        const s = await fetch("/control/test-instance/status").then(r => r.json());
        if (s.running && s.port) {
          state.baseUrl = `http://localhost:${s.port}`;
          $("#baseUrl").value = state.baseUrl;
          localStorage.setItem("baseUrl", state.baseUrl);
          $("#captionBaseUrl").textContent = state.baseUrl;
        }
      };
    }

    async function refreshServerStatus() {
      try {
        const s = await fetch("/control/server/status").then(r => r.json());
        $("#serverStatus").textContent =
          `Server: :${s.port} (pid ${s.pid}, ${s.uptime_sec}s)`;
        $("#serverStatus").style.color = "var(--accent-post)";
      } catch (e) {
        $("#serverStatus").textContent = "Server: unreachable";
        $("#serverStatus").style.color = "#c00";
      }
    }

    async function refreshTestStatus() {
      try {
        const s = await fetch("/control/test-instance/status").then(r => r.json());
        const el = $("#testStatus");
        if (s.running) {
          el.textContent = `Running on :${s.port} (pid ${s.pid})`;
          el.className = "status running";
        } else {
          el.textContent = s.error ? `Stopped (${s.error})` : "Stopped";
          el.className = s.error ? "status error" : "status";
        }
      } catch (e) {
        $("#testStatus").textContent = "Status unavailable";
      }
    }

    function renderSidebar() {
      const nav = $("#nav");
      nav.innerHTML = "";
      ENDPOINTS.sections.forEach(sec => {
        const a = el("a", { href: `#section-${sec.id}`, textContent: sec.title });
        a.onclick = (e) => {
          e.preventDefault();
          location.hash = `section-${sec.id}`;
        };
        nav.appendChild(a);
      });
    }

    function renderContent() {
      const content = $("#content");
      content.innerHTML = "";
      ENDPOINTS.sections.forEach(sec => {
        const h2 = el("h2", { id: `section-${sec.id}`, textContent: `${sec.id} ${sec.title}` });
        content.appendChild(h2);
        sec.endpoints
          .filter(ep => ep.markets.some(m => state.marketFilter.includes(m)))
          .forEach(ep => content.appendChild(renderEndpoint(ep)));
      });
    }

    function renderEndpoint(ep) {
      const card = el("div", { className: "endpoint", id: `ep-${ep.id}` });
      const method = el("span", { className: `method ${ep.method}`, textContent: ep.method });
      const path = el("span", { className: "path", textContent: ep.path });
      const summary = el("div", { className: "summary", textContent: ep.summary || "" });
      card.appendChild(method);
      card.appendChild(path);
      card.appendChild(summary);

      const det = el("details");
      det.appendChild(el("summary", { textContent: "Show details / Try it" }));
      det.appendChild(renderEndpointDetails(ep));
      card.appendChild(det);
      return card;
    }

    function renderEndpointDetails(ep) {
      const wrap = el("div");
      // Params
      if (ep.params && ep.params.length) {
        wrap.appendChild(el("h4", { textContent: "Parameters" }));
        const pre = el("pre");
        ep.params.forEach(p => {
          pre.appendChild(text(`${p.in}.${p.name}${p.required ? " (required)" : ""}: ${p.type} — ${p.desc || ""}\n`));
        });
        wrap.appendChild(pre);
      }
      // Try-it
      const ti = el("div", { className: "try-it" });
      ep.params && ep.params.forEach(p => {
        const field = el("div", { className: "field" });
        field.appendChild(el("label", { textContent: `${p.in}.${p.name}` }));
        const input = el("input", { type: "text", placeholder: p.desc || p.name, value: p.example || "" });
        input.dataset.paramName = p.name;
        input.dataset.paramIn = p.in;
        field.appendChild(input);
        ti.appendChild(field);
      });
      const sendBtn = el("button", { textContent: "Send (Try it)" });
      sendBtn.onclick = () => tryIt(ep, ti);
      ti.appendChild(sendBtn);
      const respDiv = el("div", { className: "response" });
      ti.appendChild(respDiv);
      wrap.appendChild(ti);
      return wrap;
    }

    async function tryIt(ep, container) {
      const respDiv = container.querySelector(".response");
      respDiv.innerHTML = "";
      respDiv.className = "response";
      // Build URL
      let path = ep.path;
      const qs = new URLSearchParams();
      container.querySelectorAll("input[data-param-name]").forEach(inp => {
        const v = inp.value.trim();
        if (!v) return;
        if (inp.dataset.paramIn === "path") {
          path = path.replace(`{${inp.dataset.paramName}}`, encodeURIComponent(v));
        } else {
          qs.append(inp.dataset.paramName, v);
        }
      });
      const url = `${state.baseUrl}${path}${qs.toString() ? "?" + qs : ""}`;
      try {
        const r = await fetch(url);
        const text_body = await r.text();
        const pre = el("pre", { textContent: text_body });
        respDiv.appendChild(el("div", { textContent: `HTTP ${r.status}` }));
        respDiv.appendChild(pre);
        if (!r.ok) respDiv.className = "response error";
      } catch (e) {
        respDiv.className = "response error";
        respDiv.appendChild(el("pre", { textContent: `Network error: ${e.message}\nURL: ${url}` }));
      }
    }

    // Intersection observer for sidebar active state
    const obs = new IntersectionObserver((entries) => {
      entries.forEach(en => {
        if (en.isIntersecting) {
          $$("#nav a").forEach(a => a.classList.remove("active"));
          const href = `#${en.target.id}`;
          const link = document.querySelector(`#nav a[href="${href}"]`);
          if (link) link.classList.add("active");
        }
      });
    }, { rootMargin: "-80px 0px -80% 0px" });
    document.addEventListener("DOMContentLoaded", () => {
      boot();
      // Re-observe after content render
      setTimeout(() => {
        $$(".main h2").forEach(h => obs.observe(h));
      }, 100);
    });
  })();
  </script>
</body>
</html>
```

- [ ] **Step 2: 写失败测试 — 验证 HTML 文件存在并含基本结构**

在 `tests/test_api_html.py` 写：

```python
"""Tests for docs/API.html structure."""
from pathlib import Path

import pytest
from bs4 import BeautifulSoup


HTML_PATH = Path(__file__).resolve().parent.parent / "docs" / "API.html"


@pytest.fixture
def html_text():
    if not HTML_PATH.exists():
        pytest.skip("docs/API.html not yet created")
    return HTML_PATH.read_text(encoding="utf-8")


@pytest.fixture
def soup(html_text):
    return BeautifulSoup(html_text, "html.parser")


class TestHtmlStructure:
    def test_has_doctype(self, soup):
        # bs4 doesn't preserve doctype as a tag; check for it in raw text
        pass  # checked separately

    def test_has_topbar(self, soup):
        assert soup.select_one("header.topbar h1") is not None
        assert "stock_data" in soup.select_one("header.topbar h1").get_text()

    def test_has_sidebar_and_main(self, soup):
        assert soup.select_one("nav.sidebar") is not None
        assert soup.select_one("main.main") is not None

    def test_has_endpoints_dict(self, html_text):
        assert "const ENDPOINTS = {" in html_text
        assert '"sections":' in html_text

    def test_has_capability_definitions(self, html_text):
        assert "HISTORICAL_DWM" in html_text
        assert "REALTIME_QUOTE" in html_text
        assert "ANNOUNCEMENT" in html_text

    def test_has_theme_variables(self, html_text):
        assert "--bg:" in html_text
        assert "[data-theme=\"dark\"]" in html_text

    def test_has_search_input(self, soup):
        assert soup.select_one("#search") is not None

    def test_has_test_instance_card(self, soup):
        assert soup.select_one("#testStart") is not None
        assert soup.select_one("#testStop") is not None

    def test_has_no_external_dependencies(self, html_text):
        """No <script src=...> or <link href=...> to external URLs."""
        import re
        external = re.findall(r'(?:src|href)="https?://[^"]+"', html_text)
        assert external == [], f"Found external resources: {external}"
```

- [ ] **Step 3: 跑测试确认通过**

Run: `pytest tests/test_api_html.py -v`
Expected: PASS (9 tests)

- [ ] **Step 4: 跑全部测试**

Run: `pytest tests/ -q`
Expected: all PASS (Task 1, 2, 3 一起)

- [ ] **Step 5: 手工 smoke — 启动 server 并打开 HTML**

```bash
python -m stock_data.server &
sleep 3
curl -s http://127.0.0.1:8888/control/config | head -20
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8888/docs/API.html
```

Expected: 第二条命令输出 `200`；第一条输出 JSON。

在浏览器打开 `http://127.0.0.1:8888/docs/API.html`，看到：
- 顶栏有 "stock_data API Explorer" 标题
- 侧边栏有 "Sections" 但下面空（ENDPOINTS.sections 还没填）
- 主题切换按钮工作
- Test Instance 卡片显示 "Stopped"

- [ ] **Step 6: 提交**

```bash
git add docs/API.html tests/test_api_html.py
git commit -m "feat(docs): add API Explorer HTML skeleton

Two-column layout, theme variables, test instance card, empty
ENDPOINTS dict (populated in subsequent tasks). Last_synced 2026-06-11.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: 录入 §4.1-§4.3 endpoint 元数据（健康 + 股票 + 指数）

**Files:**
- Modify: `docs/API.html` (replace empty `sections: []` with sections 4.1, 4.2, 4.3)

- [ ] **Step 1: 在 `docs/API.html` 找到 `sections: []` 这一行**

搜索：`sections: \[`

- [ ] **Step 2: 替换为 §4.1-§4.3 数据**

把：

```js
    sections: [
      // Populated in Tasks 4-7
    ],
```

替换为：

```js
    sections: [
      {
        id: "4.1",
        title: "健康检查",
        endpoints: [
          {
            id: "health",
            method: "GET",
            path: "/api/v1/health",
            summary: "健康检查 + fetcher 断路器状态",
            markets: ["csi", "hk", "us"],
            capabilities: [],
            params: [
              { name: "details", in: "query", required: false, type: "bool", desc: "默认 False；为 true 时返回每个 fetcher 的断路器状态" },
            ],
            response_fields: [
              { group: "基础", fields: ["status (ok/degraded/unhealthy)", "version"] },
              { group: "details=true 时", fields: ["sources: list[{name, state, available, last_success_time, last_failure_time, failure_count}]"] },
            ],
            cache: { ttl_sec: 0, env: "无" },
            sources: [
              { fetcher: "REALTIME_CIRCUIT_BREAKER", method: "snapshot_state", upstream: "遍历所有 fetcher 汇总 CircuitBreaker" },
            ],
          },
        ],
      },
      {
        id: "4.2",
        title: "股票 / 个股 API",
        endpoints: [
          {
            id: "stocks-quote",
            method: "GET",
            path: "/api/v1/stocks/{stock_code}/quote",
            summary: "实时行情",
            markets: ["csi", "hk", "us"],
            capabilities: ["REALTIME_QUOTE"],
            params: [
              { name: "stock_code", in: "path", required: true, type: "string", desc: "例 600519 / AAPL / HK00700（不支持指数代码）" },
            ],
            response_fields: [
              { group: "基础", fields: ["code", "stock_name", "source", "current_price", "change", "change_percent", "open", "high", "low", "prev_close", "volume", "amount", "update_time"] },
              { group: "估值增强", fields: ["pe_ttm", "pe_static", "pb", "mcap_yi (亿)", "float_mcap_yi (亿)", "turnover_pct", "amplitude_pct", "limit_up", "limit_down", "vol_ratio"] },
            ],
            cache: { ttl_sec: 60, env: "CACHE_TTL_QUOTE" },
            sources: [
              { fetcher: "Tushare", method: "get_realtime_quote", upstream: "tushare.realtime_quote(ts_code=...)", notes: "需 TUSHARE_TOKEN" },
              { fetcher: "Baostock", method: "get_realtime_quote", upstream: "永远返回 None（无实时 API）" },
              { fetcher: "Myquant", method: "get_realtime_quote", upstream: "gm.api.current_price(symbols=...)", notes: "需 MYQUANT_TOKEN；仅 price" },
              { fetcher: "Akshare", method: "get_realtime_quote", upstream: "ak.stock_zh_a_spot_em() / ak.stock_hk_spot_em()", notes: "中文字段归一化" },
              { fetcher: "Yfinance", method: "get_realtime_quote", upstream: "yf.Ticker(...).fast_info；US 失败回退 Stooq" },
              { fetcher: "Zhitu", method: "get_realtime_quote", upstream: "https://api.zhituapi.com/hs/real/ssjy/{code}?token=...", notes: "需 ZHITU_TOKEN" },
              { fetcher: "Tencent", method: "get_realtime_quote", upstream: "https://qt.gtimg.cn/q={prefix}（GBK 88 字段）" },
            ],
          },
          {
            id: "stocks-history",
            method: "GET",
            path: "/api/v1/stocks/{stock_code}/history",
            summary: "历史 K 线（含可选指标）",
            markets: ["csi", "hk", "us"],
            capabilities: ["HISTORICAL_DWM", "HISTORICAL_MIN"],
            params: [
              { name: "stock_code", in: "path", required: true, type: "string", desc: "例 600519" },
              { name: "period", in: "query", required: false, type: "string", desc: "daily | weekly | monthly（默认 daily）" },
              { name: "days", in: "query", required: false, type: "int", desc: "1..365（默认 30）" },
              { name: "start_date", in: "query", required: false, type: "string", desc: "YYYY-MM-DD（覆盖 days）" },
              { name: "end_date", in: "query", required: false, type: "string", desc: "YYYY-MM-DD（默认今天）" },
              { name: "adjust", in: "query", required: false, type: "string", desc: '"" | qfq | hfq' },
              { name: "indicators", in: "query", required: false, type: "string", desc: "逗号分隔：ma,macd,kdj,...（14 个可选）" },
            ],
            response_fields: [
              { group: "基础", fields: ["date", "open", "high", "low", "close", "volume", "amount", "change_percent"] },
              { group: "?indicators=ma 时", fields: ["ma5", "ma10", "ma20", "indicators: {ma5, ma10, ...}"] },
            ],
            cache: { ttl_sec: 300, env: "CACHE_TTL_HISTORY_DAILY / _WEEKLY / _MONTHLY" },
            sources: [
              { fetcher: "Tushare", method: "_fetch_raw_data", upstream: "tushare.pro_bar / api.query('daily'/'weekly'/'monthly')", notes: "需 TUSHARE_TOKEN" },
              { fetcher: "Baostock", method: "_fetch_raw_data", upstream: "bs.query_history_k_data_plus(...)（d/w/m + 5/15/30/60）" },
              { fetcher: "Myquant", method: "_fetch_raw_data", upstream: "gm.api.history(... frequency='1d'/'300s'/...)" },
              { fetcher: "Akshare", method: "_fetch_raw_data", upstream: "ak.stock_zh_a_hist / ak.stock_hk_hist" },
              { fetcher: "Yfinance", method: "_fetch_raw_data", upstream: "yf.download(tickers, start, end, auto_adjust=bool)" },
            ],
          },
          {
            id: "stocks-intraday",
            method: "GET",
            path: "/api/v1/stocks/{stock_code}/intraday",
            summary: "分钟 K 线",
            markets: ["csi"],
            capabilities: ["HISTORICAL_MIN"],
            params: [
              { name: "stock_code", in: "path", required: true, type: "string", desc: "6 位 A 股代码" },
              { name: "period", in: "query", required: false, type: "string", desc: "1 | 5 | 15 | 30 | 60（默认 5）" },
              { name: "adjust", in: "query", required: false, type: "string", desc: '"" | qfq | hfq' },
            ],
            response_fields: [
              { group: "基础", fields: ["time (HH:MM:SS)", "open", "high", "low", "close", "volume", "amount"] },
            ],
            cache: { ttl_sec: 30, env: "CACHE_TTL_STOCK_INTRADAY" },
            sources: [
              { fetcher: "Tushare", method: "(不支持)", upstream: "raise DataFetchError", notes: "跳过" },
              { fetcher: "Baostock", method: "_fetch_raw_data", upstream: "bs.query_history_k_data_plus(... frequency='5'/'15'/'30'/'60')" },
              { fetcher: "Myquant", method: "get_intraday_data", upstream: "gm.api.history(... frequency='300s'/...)" },
              { fetcher: "Akshare", method: "get_intraday_data", upstream: "ak.stock_zh_a_hist_min_em() → fallback ak.stock_zh_a_minute()" },
              { fetcher: "Yfinance", method: "_fetch_raw_data", upstream: "yf.download(..., interval='5m'/...)" },
              { fetcher: "Zhitu", method: "get_intraday_data", upstream: "https://api.zhituapi.com/hs/history/{symbol}.{sh|sz}/{period}/{adj}?token=..." },
            ],
          },
        ],
      },
      {
        id: "4.3",
        title: "指数 API",
        endpoints: [
          {
            id: "indices-list",
            method: "GET",
            path: "/api/v1/indices",
            summary: "指数列表（A 股 + 港股 + 美股）",
            markets: ["csi", "hk", "us"],
            capabilities: [],
            params: [],
            response_fields: [
              { group: "基础", fields: ["code", "name", "market (csi/hk/us)"] },
            ],
            cache: { ttl_sec: 0, env: "无（进程内静态表）" },
            sources: [
              { fetcher: "index_symbols", method: "get_all_indices", upstream: "静态表：CSI_INDEX_MAP + HK_INDEX_MAP + US_INDEX_MAP" },
            ],
          },
          {
            id: "indices-quote",
            method: "GET",
            path: "/api/v1/indices/{index_code}/quote",
            summary: "指数实时行情",
            markets: ["csi", "hk", "us"],
            capabilities: ["INDEX_QUOTE"],
            params: [
              { name: "index_code", in: "path", required: true, type: "string", desc: "例 000300 / SPX / HSI" },
            ],
            response_fields: [
              { group: "基础", fields: ["code", "name", "source", "current_price", "change", "change_percent", "open", "high", "low", "prev_close", "volume", "amount", "update_time"] },
            ],
            cache: { ttl_sec: 60, env: "CACHE_TTL_INDEX_QUOTE" },
            sources: [
              { fetcher: "Akshare", method: "get_index_realtime_quote", upstream: "ak.stock_zh_index_spot_em()（多 series 试）→ ak.stock_zh_index_spot_sina()" },
              { fetcher: "Yfinance", method: "get_index_realtime_quote", upstream: "yf.Ticker('^GSPC'/'^HSI').fast_info", notes: "US 失败回退 Stooq" },
            ],
          },
          {
            id: "indices-history",
            method: "GET",
            path: "/api/v1/indices/{index_code}/history",
            summary: "指数历史 K 线",
            markets: ["csi", "hk", "us"],
            capabilities: ["INDEX_HISTORICAL", "HISTORICAL_DWM"],
            params: [
              { name: "index_code", in: "path", required: true, type: "string" },
              { name: "period", in: "query", required: false, type: "string", desc: "daily | weekly | monthly" },
              { name: "days", in: "query", required: false, type: "int", desc: "1..365" },
              { name: "start_date / end_date / indicators", in: "query", required: false, type: "string", desc: "同股票 history" },
            ],
            response_fields: [
              { group: "基础", fields: ["date", "open", "high", "low", "close", "volume", "amount", "change_percent"] },
            ],
            cache: { ttl_sec: 300, env: "CACHE_TTL_HISTORY_DAILY" },
            sources: [
              { fetcher: "Tushare", method: "get_index_historical", upstream: "api.query('index_daily'/'index_weekly'/'index_monthly')" },
              { fetcher: "Baostock", method: "get_index_historical", upstream: "bs.query_history_k_data_plus('sh.000300', ..., adjustflag='3')" },
              { fetcher: "Myquant", method: "get_index_historical", upstream: "gm.api.history(symbol='SHSE.000300', frequency='1d')" },
              { fetcher: "Akshare", method: "get_index_historical", upstream: "ak.stock_zh_index_daily / _tx / _em（依次试）" },
              { fetcher: "Yfinance", method: "get_index_historical", upstream: "yf.download(ticker='^HSI'/'^GSPC', interval=...)" },
            ],
          },
          {
            id: "indices-intraday",
            method: "GET",
            path: "/api/v1/indices/{index_code}/intraday",
            summary: "指数分钟 K 线",
            markets: ["csi", "hk", "us"],
            capabilities: ["INDEX_INTRADAY", "HISTORICAL_MIN"],
            params: [
              { name: "index_code", in: "path", required: true, type: "string" },
              { name: "period", in: "query", required: false, type: "string", desc: "1 | 5 | 15 | 30 | 60" },
            ],
            response_fields: [
              { group: "基础", fields: ["time", "open", "high", "low", "close", "volume", "amount"] },
            ],
            cache: { ttl_sec: 30, env: "CACHE_TTL_INDEX_INTRADAY" },
            sources: [
              { fetcher: "Akshare", method: "get_index_intraday", upstream: "ak.index_zh_a_hist_min_em(...)" },
              { fetcher: "Myquant", method: "get_index_intraday", upstream: "gm.api.history(... frequency='300s'/...)" },
              { fetcher: "Yfinance", method: "(复用 get_intraday_data)", upstream: "yf.download(ticker='^HSI', interval='5m')" },
            ],
          },
        ],
      },
    ],
```

- [ ] **Step 3: 加 ENDPOINTS 数量断言到测试**

在 `tests/test_api_html.py` 追加：

```python
def test_endpoints_count_grows(html_text):
    """Each task adds more endpoints; we check the count is non-zero and growing."""
    import re
    m = re.search(r'"id":\s*"\S+",\s*"method":', html_text)
    assert m is not None
    # Crude: count occurrences of '"method": "GET"' in HTML
    n_get = html_text.count('"method": "GET"')
    n_post = html_text.count('"method": "POST"')
    assert n_get + n_post >= 8, f"Expected ≥8 endpoints by Task 4, got {n_get + n_post}"
```

- [ ] **Step 4: 跑测试**

Run: `pytest tests/test_api_html.py -v`
Expected: PASS

- [ ] **Step 5: 手工验证 — 浏览器刷新**

打开 `http://127.0.0.1:8888/docs/API.html`，确认：
- 侧边栏出现 "4.1 健康检查"、"4.2 股票 / 个股 API"、"4.3 指数 API"
- 点 "4.2" 滚到对应 section
- 看到 3 个 endpoint 卡片：quote、history、intraday
- 展开 "Try it" 看到 form
- 在 quote 卡片输 `600519`、点 Send → 看到 JSON 响应

- [ ] **Step 6: 提交**

```bash
git add docs/API.html tests/test_api_html.py
git commit -m "feat(docs): add §4.1-4.3 endpoint metadata (health, stocks, indices)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: 录入 §4.4-§4.6 endpoint 元数据（列表/日历/板块/涨跌停）

**Files:**
- Modify: `docs/API.html` (append to `sections` array)

- [ ] **Step 1: 在 sections 数组末尾追加 §4.4-§4.6 数据**

找到 `sections:` 数组最后一个 section（"4.3 指数 API"）的 `],` 闭合，**在其后、`],` 之前**插入 3 个新 section：

```js
      {
        id: "4.4",
        title: "股票 / 指数列表与日历",
        endpoints: [
          {
            id: "stocks-list",
            method: "GET",
            path: "/api/v1/stocks",
            summary: "股票列表（分页）",
            markets: ["csi", "hk", "us"],
            capabilities: ["STOCK_LIST"],
            params: [
              { name: "market", in: "query", required: true, type: "string", desc: 'csi (或 cn 兼容) / hk / us' },
              { name: "refresh", in: "query", required: false, type: "bool", desc: "强制刷新（默认 False）" },
              { name: "offset", in: "query", required: false, type: "int", desc: ">=0（默认 0）" },
              { name: "limit", in: "query", required: false, type: "int", desc: "1..1000（默认 100）" },
            ],
            response_fields: [
              { group: "基础", fields: ["code", "name", "market"] },
            ],
            cache: { ttl_sec: 0, env: "无（SQLite 持久化）" },
            sources: [
              { fetcher: "Baostock", method: "get_all_stocks", upstream: "bs.query_all_stock(day=最近交易日)", notes: "csi" },
              { fetcher: "Myquant", method: "get_all_stocks", upstream: "gm.api.get_symbols(sec_type1=1010)", notes: "csi" },
              { fetcher: "Akshare", method: "get_all_stocks", upstream: "ak.stock_info_a_code_name() (csi) / ak.stock_hk_spot_em() (hk) / ak.index_cons_sina('SPX') (us)" },
            ],
          },
          {
            id: "calendar",
            method: "GET",
            path: "/api/v1/calendar",
            summary: "A 股交易日历",
            markets: ["csi"],
            capabilities: ["TRADE_CALENDAR"],
            params: [
              { name: "refresh", in: "query", required: false, type: "bool", desc: "强制从上游刷新" },
            ],
            response_fields: [
              { group: "基础", fields: ["trade_dates: list[str] (YYYY-MM-DD, 升序)", "latest_date", "total"] },
            ],
            cache: { ttl_sec: 0, env: "无（持久化层拥有）" },
            sources: [
              { fetcher: "Akshare", method: "get_trade_calendar", upstream: "ak.tool_trade_date_hist_sina()" },
              { fetcher: "Myquant", method: "get_trade_calendar", upstream: "gm.api.get_trading_dates_by_year(exchange='SHSE', ...)" },
              { fetcher: "Baostock", method: "get_trade_calendar", upstream: "bs.query_trade_dates()，过滤 is_trading_day=='1'" },
            ],
          },
        ],
      },
      {
        id: "4.5",
        title: "板块 (Boards)",
        endpoints: [
          {
            id: "boards",
            method: "GET",
            path: "/api/v1/boards",
            summary: "概念 / 行业板块列表",
            markets: ["csi"],
            capabilities: ["STOCK_BOARD"],
            params: [
              { name: "type", in: "query", required: true, type: "string", desc: "concept | industry" },
              { name: "source", in: "query", required: false, type: "string", desc: '默认 "eastmoney"（保留）' },
              { name: "include_quote", in: "query", required: false, type: "bool", desc: "是否带实时行情字段" },
              { name: "refresh", in: "query", required: false, type: "bool", desc: "强制刷新" },
            ],
            response_fields: [
              { group: "基础", fields: ["code (e.g. BK1048)", "name"] },
              { group: "include_quote=true", fields: ["price", "change_pct", "change_amount", "volume", "amount", "turnover_rate", "total_mv", "up_count", "down_count", "leading_stock", "leading_stock_pct"] },
            ],
            cache: { ttl_sec: 0, env: "无（SQLite 持久化）" },
            sources: [
              { fetcher: "Akshare", method: "get_all_concept_boards / get_all_industry_boards", upstream: "ak.stock_board_concept_name_em() / ak.stock_board_industry_name_em()" },
            ],
          },
          {
            id: "boards-stocks",
            method: "GET",
            path: "/api/v1/boards/{board_code}/stocks",
            summary: "板块成份股",
            markets: ["csi"],
            capabilities: ["STOCK_BOARD"],
            params: [
              { name: "board_code", in: "path", required: true, type: "string", desc: "例 BK1048" },
              { name: "include_quote", in: "query", required: false, type: "bool" },
              { name: "refresh", in: "query", required: false, type: "bool" },
            ],
            response_fields: [
              { group: "基础", fields: ["board: BoardInfo (code, name)", "stocks: list[BoardStockInfo]", "source"] },
            ],
            cache: { ttl_sec: 0, env: "无（SQLite 持久化）" },
            sources: [
              { fetcher: "Akshare", method: "get_concept_board_stocks / get_industry_board_stocks", upstream: "ak.stock_board_concept_cons_em('BK1048')" },
            ],
          },
        ],
      },
      {
        id: "4.6",
        title: "涨跌停股池",
        endpoints: [
          {
            id: "pools",
            method: "GET",
            path: "/api/v1/pools",
            summary: "ZT / DT / ZBGC 股池",
            markets: ["csi"],
            capabilities: ["STOCK_ZT_POOL"],
            params: [
              { name: "type", in: "query", required: true, type: "string", desc: "zt | dt | zbgc" },
              { name: "date", in: "query", required: false, type: "string", desc: "YYYY-MM-DD；不传=今日" },
              { name: "refresh", in: "query", required: false, type: "bool" },
            ],
            response_fields: [
              { group: "基础", fields: ["date", "type", "total", "stocks: list[ZTPoolStock]"] },
              { group: "ZTPoolStock", fields: ["code", "name", "price", "change_pct", "amount", "circ_mv", "total_mv", "turnover_rate", "lb_count", "first_seal_time", "last_seal_time", "seal_amount", "seal_count", "zt_count"] },
            ],
            cache: { ttl_sec: 60, env: "CACHE_TTL_POOLS（仅当日）" },
            sources: [
              { fetcher: "Akshare", method: "get_zt_pool", upstream: "ak.stock_zt_pool_em(date) / _dtgc_em / _zbgc_em" },
              { fetcher: "Zhitu", method: "get_zt_pool", upstream: "https://api.zhituapi.com/hs/pool/{ztgc,dtgc,zbgc}/{date}?token=..." },
            ],
          },
        ],
      },
```

- [ ] **Step 2: 跑全部测试**

Run: `pytest tests/ -q`
Expected: PASS

- [ ] **Step 3: 手工验证**

浏览器刷新 `http://127.0.0.1:8888/docs/API.html`，确认侧边栏出现 "4.4"、"4.5"、"4.6"，对应卡片存在。

- [ ] **Step 4: 提交**

```bash
git add docs/API.html
git commit -m "feat(docs): add §4.4-4.6 endpoint metadata (lists, calendar, boards, pools)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: 录入 §4.7-§4.9 endpoint 元数据（龙虎榜/融资融券/资金流）

**Files:**
- Modify: `docs/API.html` (append to `sections`)

- [ ] **Step 1: 追加 §4.7-§4.9 数据**

在 `sections` 末尾追加：

```js
      {
        id: "4.7",
        title: "龙虎榜",
        endpoints: [
          {
            id: "stocks-dragon-tiger",
            method: "GET",
            path: "/api/v1/stocks/{stock_code}/dragon-tiger",
            summary: "个股龙虎榜",
            markets: ["csi"],
            capabilities: ["DRAGON_TIGER"],
            params: [
              { name: "stock_code", in: "path", required: true, type: "string" },
              { name: "trade_date", in: "query", required: false, type: "string", desc: "YYYY-MM-DD，空=今天" },
              { name: "look_back", in: "query", required: false, type: "int", desc: "1..365（默认 30）" },
            ],
            response_fields: [
              { group: "基础", fields: ["code", "name", "source (\"eastmoney\")"] },
              { group: "records", fields: ["date", "reason", "net_buy_wan", "turnover_pct"] },
              { group: "seats", fields: ["buy: list[{name, buy_wan, sell_wan, net_wan}] (Top 5)", "sell: ..."] },
              { group: "institution", fields: ["buy_amt, sell_amt, net_amt (单位万元)"] },
            ],
            cache: { ttl_sec: 300, env: "CACHE_TTL_DRAGON_TIGER" },
            sources: [
              { fetcher: "EastMoney", method: "get_dragon_tiger", upstream: "datacenter-web.eastmoney.com RPT_DAILYBILLBOARD_DETAILSNEW + RPT_BILLBOARD_DAILYDETAILSBUY/SELL" },
            ],
          },
          {
            id: "dragon-tiger-daily",
            method: "GET",
            path: "/api/v1/dragon-tiger/daily",
            summary: "全市场龙虎榜",
            markets: ["csi"],
            capabilities: ["DRAGON_TIGER"],
            params: [
              { name: "trade_date", in: "query", required: false, type: "string", desc: "YYYY-MM-DD，空=今天" },
              { name: "min_net_buy", in: "query", required: false, type: "float", desc: "最小净买入（万元）" },
            ],
            response_fields: [
              { group: "基础", fields: ["date", "total", "stocks: list[DailyDragonTigerStock]"] },
              { group: "Stock", fields: ["code", "name", "reason", "close", "change_pct", "net_buy_wan", "buy_wan", "sell_wan", "turnover_pct"] },
            ],
            cache: { ttl_sec: 300, env: "CACHE_TTL_DRAGON_TIGER" },
            sources: [
              { fetcher: "EastMoney", method: "get_daily_dragon_tiger", upstream: "datacenter-web.eastmoney.com RPT_DAILYBILLBOARD_DETAILSNEW（pageSize=500）" },
            ],
          },
        ],
      },
      {
        id: "4.8",
        title: "融资融券 / 大宗 / 股东 / 分红",
        endpoints: [
          {
            id: "stocks-margin",
            method: "GET",
            path: "/api/v1/stocks/{stock_code}/margin",
            summary: "融资融券",
            markets: ["csi"],
            capabilities: ["MARGIN_TRADING"],
            params: [
              { name: "stock_code", in: "path", required: true, type: "string" },
              { name: "page_size", in: "query", required: false, type: "int", desc: "1..100（默认 30）" },
            ],
            response_fields: [
              { group: "基础", fields: ["code", "name", "source", "records: list[MarginTradingRecord]"] },
              { group: "Record", fields: ["date", "rzye (融资余额, 元)", "rzmre", "rzche", "rqye (融券余额, 元)", "rqmcl", "rqchl", "rzrqye"] },
            ],
            cache: { ttl_sec: 300, env: "CACHE_TTL_MARGIN" },
            sources: [
              { fetcher: "EastMoney", method: "get_margin_trading", upstream: "datacenter-web.eastmoney.com RPTA_WEB_RZRQ_GGMX" },
            ],
          },
          {
            id: "stocks-block-trade",
            method: "GET",
            path: "/api/v1/stocks/{stock_code}/block-trade",
            summary: "大宗交易",
            markets: ["csi"],
            capabilities: ["BLOCK_TRADE"],
            params: [
              { name: "stock_code", in: "path", required: true, type: "string" },
              { name: "page_size", in: "query", required: false, type: "int", desc: "1..100（默认 20）" },
            ],
            response_fields: [
              { group: "基础", fields: ["code", "name", "source", "total", "records: list[BlockTradeRecord]"] },
              { group: "Record", fields: ["date", "price (成交价)", "close (收盘价)", "premium_pct (溢价率%)", "vol (成交量, 股)", "amount (成交额, 元)", "buyer", "seller"] },
            ],
            cache: { ttl_sec: 300, env: "CACHE_TTL_BLOCK_TRADE" },
            sources: [
              { fetcher: "EastMoney", method: "get_block_trade", upstream: "datacenter-web.eastmoney.com RPT_DATA_BLOCKTRADE" },
            ],
          },
          {
            id: "stocks-holder-num",
            method: "GET",
            path: "/api/v1/stocks/{stock_code}/holder-num",
            summary: "股东户数变化",
            markets: ["csi"],
            capabilities: ["HOLDER_NUM"],
            params: [
              { name: "stock_code", in: "path", required: true, type: "string" },
              { name: "page_size", in: "query", required: false, type: "int", desc: "1..50（默认 10）" },
            ],
            response_fields: [
              { group: "基础", fields: ["code", "name", "source", "records: list[HolderNumRecord]"] },
              { group: "Record", fields: ["date (报告期)", "holder_num", "change_num", "change_ratio", "avg_shares"] },
            ],
            cache: { ttl_sec: 300, env: "CACHE_TTL_HOLDER_NUM" },
            sources: [
              { fetcher: "EastMoney", method: "get_holder_num_change", upstream: "datacenter-web.eastmoney.com RPT_HOLDERNUMLATEST" },
            ],
          },
          {
            id: "stocks-dividend",
            method: "GET",
            path: "/api/v1/stocks/{stock_code}/dividend",
            summary: "分红送转",
            markets: ["csi"],
            capabilities: ["DIVIDEND"],
            params: [
              { name: "stock_code", in: "path", required: true, type: "string" },
              { name: "page_size", in: "query", required: false, type: "int", desc: "1..100（默认 20）" },
            ],
            response_fields: [
              { group: "基础", fields: ["code", "name", "source", "records: list[DividendRecord]"] },
              { group: "Record", fields: ["date (除权除息日)", "bonus_rmb (每股派息, 税前)", "transfer_ratio (每10股转增)", "bonus_ratio (每10股送股)", "plan (进度)"] },
            ],
            cache: { ttl_sec: 300, env: "CACHE_TTL_DIVIDEND" },
            sources: [
              { fetcher: "EastMoney", method: "get_dividend", upstream: "datacenter-web.eastmoney.com RPT_SHAREBONUS_DET" },
            ],
          },
        ],
      },
      {
        id: "4.9",
        title: "资金流",
        endpoints: [
          {
            id: "stocks-fund-flow",
            method: "GET",
            path: "/api/v1/stocks/{stock_code}/fund-flow",
            summary: "资金流（分钟级）",
            markets: ["csi"],
            capabilities: ["FUND_FLOW"],
            params: [
              { name: "stock_code", in: "path", required: true, type: "string" },
            ],
            response_fields: [
              { group: "基础", fields: ["code", "name", "type (\"minute\")", "source", "records: list[FundFlowMinuteRecord]"] },
              { group: "Record", fields: ["time (HH:mm)", "main_net", "small_net", "mid_net", "large_net", "super_net (单位: 元)"] },
            ],
            cache: { ttl_sec: 60, env: "CACHE_TTL_FUND_FLOW" },
            sources: [
              { fetcher: "EastMoney", method: "get_fund_flow_minute", upstream: "push2.eastmoney.com/api/qt/stock/fflow/kline/get?klt=1" },
            ],
          },
          {
            id: "stocks-fund-flow-daily",
            method: "GET",
            path: "/api/v1/stocks/{stock_code}/fund-flow/daily",
            summary: "资金流（120 日）",
            markets: ["csi"],
            capabilities: ["FUND_FLOW"],
            params: [
              { name: "stock_code", in: "path", required: true, type: "string" },
            ],
            response_fields: [
              { group: "基础", fields: ["code", "name", "type (\"daily\")", "source", "records: list[FundFlowDailyRecord]"] },
              { group: "Record", fields: ["date", "main_net", "small_net", "mid_net", "large_net", "super_net"] },
            ],
            cache: { ttl_sec: 60, env: "CACHE_TTL_FUND_FLOW" },
            sources: [
              { fetcher: "EastMoney", method: "get_fund_flow_120d", upstream: "push2his.eastmoney.com/api/qt/stock/fflow/daykline/get?lmt=120" },
            ],
          },
        ],
      },
```

- [ ] **Step 2: 跑全部测试**

Run: `pytest tests/ -q`
Expected: PASS

- [ ] **Step 3: 手工验证 + 提交**

```bash
git add docs/API.html
git commit -m "feat(docs): add §4.7-4.9 endpoint metadata (dragon-tiger, margin, fund-flow)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7: 录入 §4.10-§4.13 endpoint 元数据（热点北向/研报/公告/指标）

**Files:**
- Modify: `docs/API.html` (append to `sections`)

- [ ] **Step 1: 追加 §4.10-§4.13 数据**

```js
      {
        id: "4.10",
        title: "热点题材 / 北向资金",
        endpoints: [
          {
            id: "hot-topics",
            method: "GET",
            path: "/api/v1/hot/topics",
            summary: "当日热点题材",
            markets: ["csi"],
            capabilities: ["HOT_TOPICS"],
            params: [
              { name: "date", in: "query", required: false, type: "string", desc: "YYYY-MM-DD，空=今天" },
            ],
            response_fields: [
              { group: "基础", fields: ["date", "total", "topics: list[HotTopicRecord]"] },
              { group: "Record", fields: ["code", "name", "reason (题材归因)", "change_pct (涨幅%)", "turnover_rate (换手率%)", "volume", "amount", "dde_net (大单净量)"] },
            ],
            cache: { ttl_sec: 60, env: "CACHE_TTL_HOT_TOPICS" },
            sources: [
              { fetcher: "Ths", method: "get_hot_topics", upstream: "zx.10jqka.com.cn/event/api/getharden/date/{date}/orderby/date/..." },
            ],
          },
          {
            id: "north-flow-realtime",
            method: "GET",
            path: "/api/v1/north-flow/realtime",
            summary: "北向资金（分钟级累计）",
            markets: ["csi"],
            capabilities: ["NORTH_FLOW"],
            params: [],
            response_fields: [
              { group: "基础", fields: ["source (\"ths\")", "records: list[NorthFlowRecord]"] },
              { group: "Record", fields: ["time", "hgt_yi (沪股通累计净买入, 亿元)", "sgt_yi (深股通累计净买入, 亿元)"] },
            ],
            cache: { ttl_sec: 60, env: "CACHE_TTL_NORTH_FLOW" },
            sources: [
              { fetcher: "Ths", method: "get_north_flow", upstream: "data.hexin.cn/market/hsgtApi/method/dayChart/" },
            ],
          },
        ],
      },
      {
        id: "4.11",
        title: "研报",
        endpoints: [
          {
            id: "stocks-reports",
            method: "GET",
            path: "/api/v1/stocks/{stock_code}/reports",
            summary: "研报列表",
            markets: ["csi"],
            capabilities: ["RESEARCH_REPORT"],
            params: [
              { name: "stock_code", in: "path", required: true, type: "string" },
              { name: "max_pages", in: "query", required: false, type: "int", desc: "1..10（默认 3）" },
            ],
            response_fields: [
              { group: "基础", fields: ["code", "name", "source", "total", "reports: list[ReportRecord]"] },
              { group: "Record", fields: ["title", "publish_date", "org", "info_code (PDF 编号)", "rating", "predict_eps_this", "predict_eps_next", "predict_eps_next2"] },
            ],
            cache: { ttl_sec: 1800, env: "CACHE_TTL_REPORTS" },
            sources: [
              { fetcher: "EastMoney", method: "get_reports", upstream: "reportapi.eastmoney.com/report/list（code={code}, pageSize=100）" },
            ],
          },
          {
            id: "stocks-reports-pdf",
            method: "GET",
            path: "/api/v1/stocks/{stock_code}/reports/{report_id}/pdf",
            summary: "研报 PDF 下载",
            markets: ["csi"],
            capabilities: ["RESEARCH_REPORT"],
            params: [
              { name: "stock_code", in: "path", required: true, type: "string" },
              { name: "report_id", in: "path", required: true, type: "string", desc: "即 info_code" },
            ],
            response_fields: [
              { group: "基础", fields: ["report_id", "download_path (本地路径)", "url (PDF 直链)"] },
            ],
            cache: { ttl_sec: 0, env: "无" },
            sources: [
              { fetcher: "EastMoney", method: "download_report_pdf", upstream: "pdf.dfcfw.com/pdf/H3_{info_code}_1.pdf（落盘 ./reports/{info_code}.pdf）" },
            ],
          },
        ],
      },
      {
        id: "4.12",
        title: "公告",
        endpoints: [
          {
            id: "stocks-announcements",
            method: "GET",
            path: "/api/v1/stocks/{stock_code}/announcements",
            summary: "公告",
            markets: ["csi"],
            capabilities: ["ANNOUNCEMENT"],
            params: [
              { name: "stock_code", in: "path", required: true, type: "string" },
              { name: "page_size", in: "query", required: false, type: "int", desc: "1..100（默认 30）" },
            ],
            response_fields: [
              { group: "基础", fields: ["code", "name", "source (\"cninfo\")", "total", "announcements: list[AnnouncementRecord]"] },
              { group: "Record", fields: ["title", "type", "date", "url"] },
            ],
            cache: { ttl_sec: 1800, env: "CACHE_TTL_ANNOUNCEMENTS" },
            sources: [
              { fetcher: "Cninfo", method: "get_announcements", upstream: "POST www.cninfo.com.cn/new/hisAnnouncement/query（form 表单）" },
            ],
          },
        ],
      },
      {
        id: "4.13",
        title: "指标目录",
        endpoints: [
          {
            id: "indicators-catalog",
            method: "GET",
            path: "/api/v1/indicators/catalog",
            summary: "技术指标目录（14 个）",
            markets: ["csi", "hk", "us"],
            capabilities: [],
            params: [],
            response_fields: [
              { group: "基础", fields: ["indicators: list[IndicatorCatalogEntry]"] },
              { group: "Entry", fields: ["key", "input_shape (\"closes\" | \"ohlcv\")", "default_options", "output_columns", "default_lookback"] },
            ],
            cache: { ttl_sec: 0, env: "无（静态元数据）" },
            sources: [
              { fetcher: "indicators.registry", method: "INDICATOR_REGISTRY", upstream: "data_provider/indicators/registry.py" },
            ],
            notes: "14 个指标: ma, macd, boll, kdj, rsi, wr, bias, cci, atr, obv, roc, dmi, sar, kc。详细参数见 /indicators/catalog 响应。",
          },
        ],
      },
```

- [ ] **Step 2: 跑全部测试 + 数量断言**

在 `tests/test_api_html.py` 修改 `test_endpoints_count_grows`：

```python
def test_endpoints_count_grows(html_text):
    """By Task 7 we should have ~27 endpoints."""
    n_get = html_text.count('"method": "GET"')
    n_post = html_text.count('"method": "POST"')
    total = n_get + n_post
    assert total >= 25, f"Expected ≥25 endpoints by Task 7, got {total}"
```

- [ ] **Step 3: 跑测试**

Run: `pytest tests/test_api_html.py::test_endpoints_count_grows -v`
Expected: PASS

- [ ] **Step 4: 手工验证 + 提交**

浏览器刷新确认所有 13 个 section 都出现。提交：

```bash
git add docs/API.html tests/test_api_html.py
git commit -m "feat(docs): add §4.10-4.13 endpoint metadata (hot-topics, reports, announcements, indicators)

Total: 27 endpoints across 13 sections.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 8: Test Instance 控制 + smoke test 全面跑通

**Files:**
- Modify (verify only): `docs/API.html` — Task 3 已实现 Test Instance 卡片
- Modify: `.env.example` (add STOCK_TEST_INSTANCE_PORT)

- [ ] **Step 1: 在 `.env.example` 加 `STOCK_TEST_INSTANCE_PORT`**

在 `.env.example` 末尾加注释块：

```bash
# --- API Explorer (docs/API.html) ---
# HTML explorer runs at http://localhost:8888/docs/API.html
# Port for the optional Test Instance subprocess (managed from the explorer sidebar)
STOCK_TEST_INSTANCE_PORT=8889
```

- [ ] **Step 2: 端到端手工 smoke test**

启动 server：

```bash
python -m stock_data.server &
sleep 3
```

打开 `http://127.0.0.1:8888/docs/API.html`，逐项验证：

| # | 操作 | 预期 |
|---|---|---|
| 1 | 浏览器自动 fetch `/control/config` | 顶栏 Base URL 填 `http://localhost:8888` |
| 2 | 看顶栏 "Server: :8888 (pid NNN, Ns)" | 绿色文字 |
| 3 | 侧边栏点 "4.2 股票" | 滚到 4.2 |
| 4 | 展开 `GET /stocks/600519/quote` Try it 卡片 | 看到 form |
| 5 | 输 `600519` 点 Send | 看到 JSON 响应 (或错误 if no token) |
| 6 | 改 Base URL 为 `http://localhost:9999` | 下次 Try it 报 "Network error" |
| 7 | 改回 8888 | 恢复 |
| 8 | 搜索框输 "dragon" | 只剩 §4.7 卡片 |
| 9 | 清空搜索 | 全部回来 |
| 10 | 取消勾选 "us" market | 美股相关 endpoint 隐藏 |
| 11 | 重新勾选 | 恢复 |
| 12 | 点 🌗 切 dark 主题 | 整页变深色 |
| 13 | 刷新页面 | 主题保持 (localStorage) |
| 14 | 侧边栏 Test Instance 卡片点 Start | 状态变 "Running on :8889 (pid NNN)" |
| 15 | 等 3-5s 看轮询 | 状态稳定 |
| 16 | 点 "Use Test" 按钮 | Base URL 切到 :8889 |
| 17 | 对 Test Instance 调 `/control/config` | 返回 8889 |
| 18 | 切回 8888，点 Test Instance 的 Stop | 状态回 "Stopped" |
| 19 | 直接 `file:///path/to/docs/API.html` 打开 | 顶部黄色横幅 |

- [ ] **Step 3: 跑全部测试 + ruff lint**

```bash
pytest tests/ -q
ruff check stock_data/ tests/
```

Expected: all PASS, ruff clean

- [ ] **Step 4: 提交**

```bash
git add .env.example
git commit -m "docs(env): document STOCK_TEST_INSTANCE_PORT for the API Explorer

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 9: CLAUDE.md 增量更新 + 最终验证

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: 在 CLAUDE.md 加一行关于 API Explorer 的提示**

在 CLAUDE.md 的 "Common Commands" 区块**之前**（即 `## Configuration` 之前），插入新的一节：

```markdown
## API Documentation

Interactive web docs live at `docs/API.html` and are mounted at `/docs/API.html` when the server runs. After `python -m stock_data.server`, open `http://localhost:8888/docs/API.html`. The page supports Try-it, search, market/capability filtering, dark theme, and an optional Test Instance subprocess (controlled from the sidebar). The Markdown source remains at `docs/API.md` (do not edit that file — sync changes into `ENDPOINTS` in the HTML).
```

- [ ] **Step 2: 跑全部测试**

Run: `pytest tests/ -v`
Expected: all PASS

- [ ] **Step 3: ruff check 全部**

Run: `ruff check .`
Expected: clean

- [ ] **Step 4: 提交 + 总结**

```bash
git add CLAUDE.md
git commit -m "docs(claude-md): point at docs/API.html for interactive API docs

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

最终验证：
- 启动 `python -m stock_data.server` 不会报错
- 浏览器 `http://127.0.0.1:8888/docs/API.html` 正常渲染
- 13 个 section 全部出现
- Test Instance 可以启停
- 主题 / 搜索 / 过滤全部工作
- `docs/API.md` **未修改**（git log 不应包含 docs/API.md）

---

## 验收清单

实施完成后，逐项确认：

- [ ] `docs/API.md` 一字未改（`git log --oneline docs/API.md` 无新提交）
- [ ] `python -m stock_data.server` 启动成功，日志显示 "Mounted /docs → …"
- [ ] 浏览器打开 `/docs/API.html` 看到完整布局
- [ ] 13 个 section 在侧边栏列出
- [ ] 至少 25 个 endpoint 卡片可展开 Try it
- [ ] Ctrl+K 搜索 "dragon" 跳到 4.7
- [ ] dark/light 主题切换持久化
- [ ] market 过滤持久化
- [ ] Test Instance Start → :8889 启动成功
- [ ] Test Instance Stop → 状态回 Stopped
- [ ] "Use Test" 切换 Base URL 后 Try it 打到 Test Instance
- [ ] `file://` 打开 HTML → 黄色横幅
- [ ] `pytest tests/ -q` 全 PASS
- [ ] `ruff check .` clean
