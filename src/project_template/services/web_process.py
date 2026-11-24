"""Shared OS process, TCP port, PID, and log-tail helpers for Hub and child web servers.

Purpose:
    Centralizes detached background process spawning (`spawn_logged`), liveness probing
    (`port_listening`, `pid_alive`), graceful termination (`terminate_pid`), and log-tail
    reading so `services/web_launcher.py` and `services/hub_manager.py` share one implementation.
"""
from __future__ import annotations

import logging
import os
import re
import signal
import socket
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from project_template.config.settings import launcher_env

logger = logging.getLogger(__name__)
_MANAGED_PROCS: dict[int, subprocess.Popen[bytes]] = {}
_NEXT_PORT_RE = re.compile(r"下一個可用的埠號[^0-9]*(\d{4,5})")


def port_listening(port: int, timeout: float = 0.25) -> bool:
    """Check whether a local service is accepting TCP connections on `127.0.0.1:<port>`.

    Args:
        port: Local TCP port.
        timeout: Socket connection timeout in seconds.

    Returns:
        True when connection succeeds.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def read_pid(pid_file: Path) -> int | None:
    """Read a positive integer PID from a state file if present and valid.

    Args:
        pid_file: Path to the PID file.

    Returns:
        Positive integer PID, or None.
    """
    if not pid_file.is_file():
        return None
    try:
        pid = int(pid_file.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    return pid if pid > 0 else None


def _reap_if_finished_child(pid: int) -> bool:
    """Reap a direct child if it already exited (prevents POSIX zombies and ResourceWarning).

    Args:
        pid: Process ID to inspect.

    Returns:
        True when `pid` was a direct child that has now exited and been reaped.
    """
    proc = _MANAGED_PROCS.get(pid)
    if proc is not None:
        if proc.poll() is None:
            return False
        _MANAGED_PROCS.pop(pid, None)
        return True
    try:
        reaped, _ = os.waitpid(pid, os.WNOHANG)
    except ChildProcessError:
        return False
    return reaped == pid


def pid_alive(pid: int | None) -> bool:
    """Check whether an OS process with the given PID exists.

    Args:
        pid: Process ID or None.

    Returns:
        True when the process exists and has not exited as a zombie.
    """
    if pid is None or pid <= 0 or _reap_if_finished_child(pid):
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def read_log_tail(log_file: Path, lines: int = 80) -> list[str]:
    """Return the last `lines` lines from a UTF-8 log file.

    Args:
        log_file: Log file path.
        lines: Maximum trailing line count.

    Returns:
        List of log lines without trailing newlines.
    """
    if not log_file.is_file():
        return []
    text = log_file.read_text(encoding="utf-8", errors="replace")
    all_lines = text.splitlines()
    return all_lines[-max(1, lines):] if all_lines else []


def _send_group_signal(pid: int, sig: int) -> None:
    """Send a signal to `pid`'s process group, falling back to `pid` directly.

    Args:
        pid: Leader process ID.
        sig: POSIX signal number.
    """
    try:
        os.killpg(os.getpgid(pid), sig)
    except OSError:
        try:
            os.kill(pid, sig)
        except OSError:
            return


def terminate_pid(pid: int, wait_seconds: float = 4.0) -> bool:
    """Gracefully stop a managed process group (SIGTERM, then SIGKILL if still alive).

    Args:
        pid: Process ID to terminate.
        wait_seconds: Graceful shutdown wait before escalating to SIGKILL.

    Returns:
        True when the process is no longer alive.
    """
    if not pid_alive(pid):
        return True
    _send_group_signal(pid, signal.SIGTERM)
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        if not pid_alive(pid):
            return True
        time.sleep(0.15)
    _send_group_signal(pid, signal.SIGKILL)
    time.sleep(0.2)
    return not pid_alive(pid)


def spawn_logged(
    argv: list[str],
    cwd: Path,
    state_files: tuple[Path, Path],
    banner: str,
) -> subprocess.Popen[bytes]:
    """Spawn a detached background subprocess, logging output and recording its PID.

    Args:
        argv: Executable and argument list.
        cwd: Working directory for the subprocess.
        state_files: Tuple of `(pid_file, log_file)`.
        banner: Startup banner line recorded in `log_file`.

    Returns:
        Spawned `subprocess.Popen` handle.
    """
    pid_file, log_file = state_files
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    with log_file.open("a", encoding="utf-8") as log_fh:
        log_fh.write(f"\n=== [{stamp}] {banner} ===\n")
        log_fh.flush()
        proc = subprocess.Popen(
            argv,
            cwd=cwd,
            env=launcher_env(),
            stdin=subprocess.DEVNULL,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    pid_file.write_text(f"{proc.pid}\n", encoding="utf-8")
    _MANAGED_PROCS[proc.pid] = proc
    logger.debug("spawned pid=%s cwd=%s banner=%s", proc.pid, cwd, banner)
    return proc


def parse_ports_md(ports_file: Path) -> tuple[set[int], int | None]:
    """Read used TCP ports and the next-free hint from `PORTS.md`.

    Args:
        ports_file: Path to `00 init_dev_env/PORTS.md`.

    Returns:
        Tuple of `(used_ports, next_hint)` where `next_hint` may be None.
    """
    if not ports_file.is_file():
        return set(), None
    text = ports_file.read_text(encoding="utf-8", errors="replace")
    used: set[int] = set()
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|") or stripped.startswith("|---") or stripped.startswith("| 埠號"):
            continue
        first_cell = stripped.split("|", 2)[1]
        used.update(int(tok) for tok in re.findall(r"\b(\d{4,5})\b", first_cell) if 1 <= int(tok) <= 65535)
    hint_match = _NEXT_PORT_RE.search(text)
    hint = int(hint_match.group(1)) if hint_match and 1 <= int(hint_match.group(1)) <= 65535 else None
    return used, hint
