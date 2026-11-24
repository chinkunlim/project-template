"""Manage the template Hub background daemon and macOS LaunchAgent autostart.

Purpose:
    Provides `start_hub()`, `stop_hub()`, `hub_status()`, `install_autostart()`, and
    `uninstall_autostart()` for `scripts/hub.py`. Stores Hub PID and log under external
    `DATA_DIR/hub/` and optionally manages `com.project-template.hub.plist`.
"""
from __future__ import annotations

import logging
import os
import plistlib
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any

from project_template.config.settings import (
    TEMPLATE_ROOT,
    hub_state_dir,
    launch_agent_override_active,
    launch_agent_plist,
    launcher_env,
)
from project_template.services import web_launcher
from project_template.services import web_process as wp

logger = logging.getLogger(__name__)
HUB_LABEL = "com.project-template.hub"
DEFAULT_HUB_PORT = 8766


def _hub_files() -> tuple[Path, Path]:
    """Return `(pid_file, log_file)` for the template Hub server.

    Returns:
        Tuple of Hub PID path and log file path inside `DATA_DIR/hub/`.
    """
    base = hub_state_dir()
    return base / "hub.pid", base / "hub.log"


def _http_ready(port: int) -> bool:
    """Return True when the Hub responds HTTP 200 on `/api/info`.

    Args:
        port: TCP port bound on `127.0.0.1`.

    Returns:
        True when `/api/info` returns 200.
    """
    url = f"http://127.0.0.1:{port}/api/info"
    try:
        with urllib.request.urlopen(url, timeout=0.5) as resp:
            return bool(resp.status == 200)
    except (OSError, urllib.error.URLError):
        return False


def _wait_hub_ready(proc: subprocess.Popen[bytes], port: int, wait_seconds: float) -> bool:
    """Wait until `/api/info` responds 200, process exits, or timeout elapses.

    Args:
        proc: Spawned `web_ui.py` subprocess.
        port: Expected TCP port.
        wait_seconds: Wait timeout in seconds.

    Returns:
        True when Hub responds HTTP 200.
    """
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        if _http_ready(port):
            return True
        if proc.poll() is not None:
            return False
        time.sleep(0.25)
    return _http_ready(port)


def hub_status(port: int = DEFAULT_HUB_PORT, root: Path | None = None) -> dict[str, Any]:
    """Collect Hub status, LaunchAgent autostart flag, and child project web services.

    Args:
        port: Hub TCP port (default 8766).
        root: Projects root folder to scan; defaults to `TEMPLATE_ROOT.parent`.

    Returns:
        Dictionary summarizing Hub state, URL, PID, autostart, and child `services`.
    """
    pid_file, log_file = _hub_files()
    pid = wp.read_pid(pid_file)
    alive = wp.pid_alive(pid)
    if pid is not None and not alive:
        pid_file.unlink(missing_ok=True)
        pid = None
    running = wp.port_listening(port)
    base_root = (root or TEMPLATE_ROOT.parent).resolve()
    return {
        "running": running,
        "managed": bool(running and alive),
        "pid": pid if alive else None,
        "port": port,
        "url": f"http://127.0.0.1:{port}",
        "autostart": launch_agent_plist().is_file(),
        "log_file": str(log_file),
        "services": web_launcher.list_web_services(base_root),
    }


def start_hub(port: int = DEFAULT_HUB_PORT, open_browser: bool = True, wait_seconds: float = 25.0) -> dict[str, Any]:
    """Start the Hub server in the background if stopped and optionally open a browser tab.

    Args:
        port: Local TCP port (default 8766).
        open_browser: Whether to open `http://127.0.0.1:<port>` in the default browser.
        wait_seconds: Maximum wait time for `/api/info` readiness.

    Returns:
        Dictionary with `running`, `started`, `already_running`, `pid`, `url`, `log_file`.

    Raises:
        RuntimeError: When the Hub fails to start within `wait_seconds`.
    """
    url = f"http://127.0.0.1:{port}"
    pid_file, log_file = _hub_files()
    if wp.port_listening(port):
        if open_browser:
            webbrowser.open(url)
        return {"running": True, "started": False, "already_running": True,
                "pid": wp.read_pid(pid_file), "url": url, "log_file": str(log_file)}
    argv = [sys.executable, str(TEMPLATE_ROOT / "scripts" / "web_ui.py"), "--no-browser", "--port", str(port)]
    proc = wp.spawn_logged(argv, TEMPLATE_ROOT, (pid_file, log_file), f"hub start port={port}")
    logger.info("started Hub pid=%s port=%s", proc.pid, port)
    if not _wait_hub_ready(proc, port, wait_seconds):
        if not wp.pid_alive(proc.pid):
            pid_file.unlink(missing_ok=True)
        tail = "\n".join(wp.read_log_tail(log_file, 25))
        raise RuntimeError(f"母版總控台未能在 {wait_seconds:.0f}s 內啟動（{url}）。日誌：\n{tail or '（尚無輸出）'}")
    if open_browser:
        webbrowser.open(url)
    return {"running": True, "started": True, "already_running": False, "pid": proc.pid, "url": url, "log_file": str(log_file)}


def stop_hub(port: int = DEFAULT_HUB_PORT, with_children: bool = False, root: Path | None = None) -> dict[str, Any]:
    """Stop the background Hub server and optionally every Hub-managed child project server.

    Args:
        port: Hub TCP port.
        with_children: Stop all managed child project servers before stopping the Hub.
        root: Projects root folder when stopping children.

    Returns:
        Result dict describing Hub stop status and optional stopped children.
    """
    children = web_launcher.stop_all_project_webs((root or TEMPLATE_ROOT.parent).resolve()) if with_children else None
    pid_file, _ = _hub_files()
    pid = wp.read_pid(pid_file)
    if pid is not None and wp.pid_alive(pid):
        wp.terminate_pid(pid)
        pid_file.unlink(missing_ok=True)
        logger.info("stopped Hub pid=%s", pid)
        still = wp.port_listening(port)
        note = "已停止總控台（若啟用了 autostart，launchd 可能自動重啟，請執行 autostart off）" if still else "已停止總控台"
        return {"stopped": not still, "running": still, "port": port, "message": note, "children": children}
    pid_file.unlink(missing_ok=True)
    if wp.port_listening(port):
        return {"stopped": False, "running": True, "port": port, "children": children,
                "message": "總控台由外部終端或 launchd 執行中（若為常駐請執行 `python3 scripts/hub.py autostart off`）"}
    return {"stopped": False, "running": False, "port": port, "children": children, "message": "總控台目前未執行"}


def render_launchd_plist(port: int = DEFAULT_HUB_PORT) -> str:
    """Build macOS LaunchAgent XML property list for running the Hub at login.

    Args:
        port: Local TCP port for `scripts/web_ui.py`.

    Returns:
        UTF-8 XML plist document string.
    """
    _, log_file = _hub_files()
    env = launcher_env()
    payload: dict[str, Any] = {
        "Label": HUB_LABEL,
        "ProgramArguments": [sys.executable, str(TEMPLATE_ROOT / "scripts" / "web_ui.py"), "--no-browser", "--port", str(port)],
        "WorkingDirectory": str(TEMPLATE_ROOT),
        "EnvironmentVariables": {"PATH": env.get("PATH", "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin")},
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "StandardOutPath": str(log_file),
        "StandardErrorPath": str(log_file),
    }
    return plistlib.dumps(payload).decode("utf-8")


def install_autostart(port: int = DEFAULT_HUB_PORT) -> dict[str, Any]:
    """Install the macOS LaunchAgent plist and load it when running natively on Darwin.

    Args:
        port: Local TCP port for the Hub server.

    Returns:
        Dictionary with `plist`, `loaded`, `url`, and status `message`.
    """
    plist = launch_agent_plist()
    plist.parent.mkdir(parents=True, exist_ok=True)
    _, log_file = _hub_files()
    log_file.parent.mkdir(parents=True, exist_ok=True)
    plist.write_text(render_launchd_plist(port), encoding="utf-8")
    loaded = False
    if sys.platform == "darwin" and not launch_agent_override_active():
        domain = f"gui/{os.getuid()}"
        subprocess.run(["launchctl", "bootout", domain, str(plist)], capture_output=True, text=True, check=False)
        res = subprocess.run(["launchctl", "bootstrap", domain, str(plist)], capture_output=True, text=True, check=False)
        loaded = res.returncode == 0
        if not loaded:
            logger.warning("launchctl bootstrap failed: %s", res.stderr.strip())
    logger.info("installed LaunchAgent plist=%s loaded=%s", plist, loaded)
    return {"plist": str(plist), "loaded": loaded, "url": f"http://127.0.0.1:{port}",
            "message": "已設定登入自動常駐母版總控台"}


def uninstall_autostart() -> dict[str, Any]:
    """Unload and delete the macOS LaunchAgent plist if installed.

    Returns:
        Dictionary with `plist`, `removed`, and status `message`.
    """
    plist = launch_agent_plist()
    if sys.platform == "darwin" and not launch_agent_override_active() and plist.is_file():
        domain = f"gui/{os.getuid()}"
        subprocess.run(["launchctl", "bootout", domain, str(plist)], capture_output=True, text=True, check=False)
    removed = plist.is_file()
    plist.unlink(missing_ok=True)
    logger.info("uninstalled LaunchAgent plist=%s removed=%s", plist, removed)
    return {"plist": str(plist), "removed": removed,
            "message": "已關閉登入自動常駐" if removed else "尚未設定開機常駐"}
