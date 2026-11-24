"""Discover, start, stop, and monitor FastAPI web servers of tracked projects.

Purpose:
    Implements Core Rule 13 shared business logic used identically by the Hub web page,
    HTTP `/api/web/*` JSON API, Open WebUI tool, MCP tools, and `scripts/hub.py`.
    Child services run only on demand and bind `127.0.0.1` so memory stays minimal when idle.
"""
from __future__ import annotations

import hashlib
import logging
import re
import shlex
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from project_template.config.framework import parse_toml
from project_template.config.settings import hub_state_dir, resolve_uv, template_dotenv
from project_template.services import update_all
from project_template.services import web_process as wp

logger = logging.getLogger(__name__)
SCRIPT_LINE_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)\s*=\s*['\"]")

# Re-export process helpers used by callers/tests without breaking imports.
port_listening = wp.port_listening
read_pid = wp.read_pid
pid_alive = wp.pid_alive
read_log_tail = wp.read_log_tail
terminate_pid = wp.terminate_pid


@dataclass(frozen=True)
class WebServiceSpec:
    """Discovered FastAPI / HTTP web server configuration for a project.

    Attributes:
        name: Project folder name.
        path: Resolved project root directory.
        port: Local TCP port bound on `127.0.0.1`.
        url: Local URL `http://127.0.0.1:<port>`.
        command: Launch command argv list.
        health_path: Optional health endpoint path.
        source: Discovery source (`project.toml` or `auto`).
    """

    name: str
    path: Path
    port: int
    url: str
    command: list[str]
    health_path: str = "/"
    source: str = "auto"


def project_slug(project: Path) -> str:
    """Convert a project path into a filesystem-safe identifier for PID and log files.

    Args:
        project: Project root directory.

    Returns:
        Safe ASCII slug combining folder name and short path hash.
    """
    clean = re.sub(r"[^a-zA-Z0-9._-]+", "-", project.name).strip("-") or "project"
    digest = hashlib.sha1(str(project.resolve()).encode("utf-8")).hexdigest()[:6]
    return f"{clean}-{digest}"


def _read_int(raw: object) -> int | None:
    """Parse a positive TCP port integer from config or env text.

    Args:
        raw: Raw string or integer value.

    Returns:
        Valid port number in 1..65535, or None.
    """
    try:
        port = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return port if 1 <= port <= 65535 else None


def _parse_pyproject_scripts(pyproject: Path) -> list[str]:
    """Read entry script names declared under `[project.scripts]` in `pyproject.toml`.

    Args:
        pyproject: Path to `pyproject.toml`.

    Returns:
        Ordered list of declared script names.
    """
    if not pyproject.is_file():
        return []
    in_scripts = False
    names: list[str] = []
    for raw_line in pyproject.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line.startswith("["):
            in_scripts = line == "[project.scripts]"
            continue
        if not in_scripts or not line or line.startswith("#"):
            continue
        match = SCRIPT_LINE_RE.match(line)
        if match:
            names.append(match.group(1))
    return names


def _detect_http_port(project: Path) -> int | None:
    """Read `HTTP_PORT` from `project/.env` or fallback `project/.env.example`.

    Args:
        project: Project root directory.

    Returns:
        Configured TCP port, or None when absent.
    """
    for filename in (".env", ".env.example"):
        env_map = template_dotenv(project / filename)
        port = _read_int(env_map.get("HTTP_PORT"))
        if port is not None:
            return port
    return None


def _pick_script_command(project: Path, scripts: list[str], port: int) -> list[str] | None:
    """Infer the FastAPI launch argv from declared `pyproject.toml` scripts.

    Args:
        project: Project root directory.
        scripts: Script names under `[project.scripts]`.
        port: Discovered HTTP port.

    Returns:
        Launch argv list, or None when the project has no web server script.
    """
    for suffix in ("-web", "-server", "-api"):
        for name in scripts:
            if name.endswith(suffix):
                return ["uv", "run", name]
    src_dir = project / "src"
    if not (src_dir.is_dir() and any(src_dir.rglob("web_app.py")) and scripts):
        return None
    target_norm = project.name.replace("_", "-").lower()
    primary = next((s for s in scripts if s.replace("_", "-").lower() == target_norm), scripts[0])
    return ["uv", "run", primary, "web", "--port", str(port), "--no-open"]


def _from_toml_web(project: Path) -> WebServiceSpec | None:
    """Build a `WebServiceSpec` from explicit `[web]` settings in `.agents/project.toml`.

    Args:
        project: Project root directory.

    Returns:
        `WebServiceSpec` when `[web]` defines `port` and `command`, else None.
    """
    toml_file = project / ".agents" / "project.toml"
    if not toml_file.is_file():
        return None
    cfg = parse_toml(toml_file.read_text(encoding="utf-8"))
    web_cfg = cfg.get("web")
    if not isinstance(web_cfg, dict):
        return None
    port = _read_int(web_cfg.get("port"))
    raw_cmd = web_cfg.get("command")
    command = list(raw_cmd) if isinstance(raw_cmd, list) else shlex.split(str(raw_cmd or ""))
    if port is None or not command:
        return None
    health = str(web_cfg.get("health_path") or "/")
    return WebServiceSpec(project.name, project, port, f"http://127.0.0.1:{port}", command, health, "project.toml")


def discover_web_service(project: Path) -> WebServiceSpec | None:
    """Discover a project's local FastAPI web configuration if one exists.

    Args:
        project: Resolved project root directory.

    Returns:
        `WebServiceSpec` when the project exposes a web server, otherwise None.
    """
    resolved = project.expanduser().resolve()
    explicit = _from_toml_web(resolved)
    if explicit is not None:
        return explicit
    port = _detect_http_port(resolved)
    if port is None:
        return None
    scripts = _parse_pyproject_scripts(resolved / "pyproject.toml")
    command = _pick_script_command(resolved, scripts, port)
    if not command:
        return None
    return WebServiceSpec(resolved.name, resolved, port, f"http://127.0.0.1:{port}", command, "/", "auto")


def _state_paths(project: Path) -> tuple[Path, Path]:
    """Return `(pid_file, log_file)` inside external `DATA_DIR/hub/`.

    Args:
        project: Resolved project root directory.

    Returns:
        Tuple of PID file path and log file path.
    """
    slug = project_slug(project)
    base = hub_state_dir()
    return base / f"{slug}.pid", base / f"{slug}.log"


def service_status(project: Path) -> dict[str, Any] | None:
    """Inspect a project's discovered web service and live runtime state.

    Args:
        project: Project root directory.

    Returns:
        Status dictionary, or None when the project does not expose a web server.
    """
    spec = discover_web_service(project)
    if spec is None:
        return None
    pid_file, log_file = _state_paths(spec.path)
    pid = wp.read_pid(pid_file)
    managed_alive = wp.pid_alive(pid)
    if pid is not None and not managed_alive:
        pid_file.unlink(missing_ok=True)
        pid = None
    running = wp.port_listening(spec.port)
    return {
        "name": spec.name,
        "path": str(spec.path),
        "port": spec.port,
        "url": spec.url,
        "command": shlex.join(spec.command),
        "running": running,
        "managed": bool(running and managed_alive),
        "pid": pid if managed_alive else None,
        "log_file": str(log_file),
        "source": spec.source,
    }


def list_web_services(root: Path) -> list[dict[str, Any]]:
    """List every tracked project that exposes a FastAPI web service.

    Args:
        root: Base projects folder passed to `update_all.tracked_projects()`.

    Returns:
        Sorted list of service status dicts.
    """
    rows: list[dict[str, Any]] = []
    for project in sorted(update_all.tracked_projects([root], 3), key=lambda p: p.name.lower()):
        status = service_status(project)
        if status is not None:
            rows.append(status)
    return rows


def resolve_project_path(project_ref: str, root: Path) -> Path:
    """Resolve an absolute folder or tracked project name into a project root `Path`.

    Args:
        project_ref: Project name or absolute directory path.
        root: Base projects folder to search when given a name.

    Returns:
        Resolved directory path.

    Raises:
        ValueError: When `project_ref` is empty or matches no existing project.
    """
    cleaned = project_ref.strip()
    if not cleaned:
        raise ValueError("請提供專案名稱或絕對路徑")
    candidate = Path(cleaned).expanduser()
    if candidate.is_absolute() or cleaned.startswith("."):
        resolved = candidate.resolve()
        if resolved.is_dir():
            return resolved
        raise ValueError(f"找不到專案資料夾：{resolved}")
    for project in update_all.tracked_projects([root], 3):
        if project.name == cleaned:
            return project.resolve()
    raise ValueError(f"找不到名為 `{cleaned}` 的追蹤專案")


def _resolved_argv(spec: WebServiceSpec) -> list[str]:
    """Replace leading `uv` token with absolute executable path when spawning detached processes.

    Args:
        spec: Discovered service specification.

    Returns:
        Resolved argv list ready for `subprocess.Popen`.
    """
    argv = list(spec.command)
    if argv and argv[0] == "uv":
        argv[0] = resolve_uv()
    return argv


def _wait_for_ready(proc: subprocess.Popen[bytes], port: int, wait_seconds: float) -> bool:
    """Poll `127.0.0.1:<port>` until listening, the process exits, or timeout expires.

    Args:
        proc: Spawned server subprocess.
        port: Expected TCP port.
        wait_seconds: Maximum wait time in seconds.

    Returns:
        True when the TCP port accepts connections.
    """
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        if wp.port_listening(port):
            return True
        if proc.poll() is not None:
            return False
        time.sleep(0.2)
    return wp.port_listening(port)


def start_project_web(project: Path, wait_seconds: float = 15.0) -> dict[str, Any]:
    """Start a child project's FastAPI web server in the background and wait until ready.

    Args:
        project: Project root directory.
        wait_seconds: Timeout waiting for the port to start listening.

    Returns:
        Updated status dictionary with `started` and `already_running` flags.

    Raises:
        ValueError: When the project has no configured/discoverable web service.
        RuntimeError: When the process exits early or fails to listen in time.
    """
    spec = discover_web_service(project)
    if spec is None:
        raise ValueError(f"`{project.name}` 沒有設定網頁服務（找不到 HTTP_PORT 或 web 啟動腳本）")
    current = service_status(spec.path)
    if current and current["running"]:
        return {**current, "started": False, "already_running": True}
    pid_file, log_file = _state_paths(spec.path)
    argv = _resolved_argv(spec)
    proc = wp.spawn_logged(argv, spec.path, (pid_file, log_file), f"start {spec.name}: {shlex.join(argv)}")
    logger.info("started web service %s pid=%s port=%s", spec.name, proc.pid, spec.port)
    if _wait_for_ready(proc, spec.port, wait_seconds):
        updated = service_status(spec.path) or {}
        return {**updated, "started": True, "already_running": False}
    if not wp.pid_alive(proc.pid):
        pid_file.unlink(missing_ok=True)
    tail = "\n".join(wp.read_log_tail(log_file, 25))
    logger.warning("web service %s failed readiness on port %s", spec.name, spec.port)
    raise RuntimeError(f"{spec.name} 啟動失敗（{spec.url} 未就緒）。最近日誌：\n{tail or '（尚無輸出）'}")


def stop_project_web(project: Path) -> dict[str, Any]:
    """Stop a Hub-managed child project's web server cleanly without touching unmanaged processes.

    Args:
        project: Project root directory.

    Returns:
        Result dictionary with `stopped`, `running`, and human-readable `message`.

    Raises:
        ValueError: When the project has no web service.
        RuntimeError: When terminating a managed process fails.
    """
    spec = discover_web_service(project)
    if spec is None:
        raise ValueError(f"`{project.name}` 沒有網頁服務")
    pid_file, _ = _state_paths(spec.path)
    pid = wp.read_pid(pid_file)
    if pid is not None and wp.pid_alive(pid):
        if not wp.terminate_pid(pid):
            raise RuntimeError(f"無法結束 {spec.name} (PID {pid})")
        pid_file.unlink(missing_ok=True)
        logger.info("stopped web service %s pid=%s", spec.name, pid)
        return {"name": spec.name, "path": str(spec.path), "port": spec.port, "url": spec.url,
                "stopped": True, "running": wp.port_listening(spec.port), "message": "已停止服務"}
    pid_file.unlink(missing_ok=True)
    if wp.port_listening(spec.port):
        return {"name": spec.name, "path": str(spec.path), "port": spec.port, "url": spec.url,
                "stopped": False, "running": True, "message": "此服務並非由母版啟動，請於原終端手動停止"}
    return {"name": spec.name, "path": str(spec.path), "port": spec.port, "url": spec.url,
            "stopped": False, "running": False, "message": "服務目前未執行"}


def stop_all_project_webs(root: Path) -> dict[str, Any]:
    """Stop every Hub-managed child web service under tracked projects.

    Args:
        root: Base projects folder.

    Returns:
        Dictionary with `stopped` and `skipped` project lists.
    """
    stopped: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for svc in list_web_services(root):
        if not svc["running"]:
            continue
        res = stop_project_web(Path(svc["path"]))
        (stopped if res["stopped"] else skipped).append(res)
    logger.info("stop_all_project_webs stopped=%d skipped=%d", len(stopped), len(skipped))
    return {"stopped": stopped, "skipped": skipped}


def read_web_logs(project: Path, lines: int = 80) -> dict[str, Any]:
    """Return recent launcher log lines for a project's web server.

    Args:
        project: Project root directory.
        lines: Number of trailing lines to return.

    Returns:
        Dictionary containing `name`, `log_file`, and `lines`.

    Raises:
        ValueError: When the folder does not expose a web service.
    """
    spec = discover_web_service(project)
    if spec is None:
        raise ValueError(f"`{project.name}` 沒有設定網頁服務")
    _, log_file = _state_paths(spec.path)
    return {"name": spec.name, "log_file": str(log_file), "lines": wp.read_log_tail(log_file, lines)}
