"""Test Instance subprocess management for the API Explorer.

Lets the HTML explorer (mounted at /explorer/) spawn an independent
stock_data server process on a different port for manual failover
testing. The main server (the one serving the HTML) is never stopped
by this module.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

# PID file lives in the explorer subpackage so it ships with the repo
# source tree but is gitignored. Default path is overridable via
# start_*/get_*/stop_* args, which is what tests use.
DEFAULT_PID_PATH = str(
    Path(__file__).resolve().parent / ".server.pid"
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
            Path(pid_path).unlink(missing_ok=True)
        except TypeError:
            if Path(pid_path).exists():
                Path(pid_path).unlink()
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
        Path(pid_path).unlink(missing_ok=True)
    except TypeError:
        if Path(pid_path).exists():
            Path(pid_path).unlink()

    return {"running": False, "pid": pid, "error": None}
