"""Tests for stock_data.control — Test Instance subprocess management."""
import socket

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

    # Mock subprocess.Popen so we capture args/env without actually binding
    # a real server. We assert start_test_instance forwards the port via
    # SERVER_PORT env var (server.py:main() reads os.getenv, not argv).
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
