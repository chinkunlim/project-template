#!/usr/bin/env python3
"""Local web page + JSON API for the template (template-only tool; standard library only).

Purpose:
    Everything the template does, without typing commands: create a project (name, folder
    location, data folder, stack, add-ons, skills …), migrate an old project, list your projects
    and run doctor / check / setup on them, collect template feedback, and preview / apply the
    framework update for every project. Open WebUI can call the same JSON API through
    `tools/openwebui/project_template_tool.py`.

    Every action runs the same command-line tools (`init_project.py`, `migrate_project.py`,
    `agentctl …`, `update_all.py`), so the page and the terminal always behave the same; the page
    shows the equivalent command and its full output.

Safety (same model as literature-fetch ADR-008):
    - Binds 127.0.0.1 only. The Host header must be 127.0.0.1 / localhost (DNS-rebinding guard);
      add `--allow-host host.docker.internal` when Open WebUI runs in Docker.
    - State-changing requests that carry another site's `Origin` are refused (CSRF guard).
    - One job at a time; commands never push and never delete files.
    - `DATA_DIR` is removed from the environment of every command, so a variable inherited by this
      server never overrides a project's own `.env`.

Usage:
    python3 tools/web_ui.py                                  # http://127.0.0.1:8766
    python3 tools/web_ui.py --port 8770 --no-browser
    python3 tools/web_ui.py --allow-host host.docker.internal
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import threading
import time
from urllib.parse import parse_qs, urlparse
import webbrowser

TEMPLATE_ROOT = Path(__file__).resolve().parent.parent
TOOLS = TEMPLATE_ROOT / "tools"
PAGE = TOOLS / "web" / "index.html"
for _path in (TEMPLATE_ROOT, TEMPLATE_ROOT / "lib", TOOLS):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import collect_feedback  # noqa: E402
from framework_install import load_catalog  # noqa: E402
from packs.stack_config import (  # noqa: E402
    ADDON_CHOICES,
    PYTHON_ONLY_ADDONS,
    STACK_CHOICES,
    data_dir_setting,
    data_slug,
    resolve_stack,
)
from project_config import FRAMEWORK_VERSION  # noqa: E402
import update_all  # noqa: E402

DEFAULT_PORT = 8766
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.\-一-鿿]*$")
PROJECT_COMMANDS = {
    "status": ["status"],
    "doctor": ["doctor"],
    "doctor-fix": ["doctor", "--fix"],
    "setup": ["setup", "--install"],
    "check": ["check"],
}


@dataclass
class Job:
    """One background job: a list of commands run in order (stops at the first failure).

    Attributes:
        id: Increasing job number.
        title: Short description shown on the page.
        steps: `(argv, cwd)` pairs.
        state: `running`, `done` or `failed`.
        log: Output lines (commands are echoed with `$`).
        result: Structured result for the page (e.g. the update preview table).
        returncode: Exit code of the last command.
    """

    id: int
    title: str
    steps: list[tuple[list[str], Path]]
    state: str = "running"
    log: list[str] = field(default_factory=list)
    result: object = None
    returncode: int = 0


class JobRunner:
    """Run one job at a time in a background thread."""

    def __init__(self) -> None:
        """Start with no job."""
        self.lock = threading.Lock()
        self.current: Job | None = None
        self.counter = 0

    def start(self, title: str, steps: list[tuple[list[str], Path]], after=None) -> Job:
        """Start a job unless one is still running.

        Args:
            title: Short description.
            steps: `(argv, cwd)` pairs to run in order.
            after: Optional function called with the job when every step succeeded (fills `result`).

        Returns:
            The new job.

        Raises:
            RuntimeError: When another job is still running.
        """
        with self.lock:
            if self.current and self.current.state == "running":
                raise RuntimeError(f"另一個工作還在執行：{self.current.title}")
            self.counter += 1
            job = Job(self.counter, title, steps)
            self.current = job
        threading.Thread(target=self._run, args=(job, after), daemon=True).start()
        return job

    def _run(self, job: Job, after) -> None:
        """Execute the steps and record their output.

        Args:
            job: The job to run.
            after: Optional completion callback.
        """
        env = {k: v for k, v in os.environ.items() if k != "DATA_DIR"}
        for argv, cwd in job.steps:
            job.log.append(f"$ (cd {shlex.quote(str(cwd))} && {shlex.join(argv)})")
            with subprocess.Popen(argv, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True) as proc:
                for line in proc.stdout or []:
                    job.log.append(line.rstrip("\n"))
                job.returncode = proc.wait()
            if job.returncode != 0:
                job.state = "failed"
                job.log.append(f"❌ 結束碼 {job.returncode}")
                return
        try:
            if after:
                after(job)
            job.state = "done"
        except Exception as exc:  # noqa: BLE001 - shown to the user
            job.log.append(f"❌ {exc}")
            job.state = "failed"


RUNNER = JobRunner()
PY = sys.executable


def projects_root() -> Path:
    """Folder that holds the projects by default (the template's parent).

    Returns:
        The folder.
    """
    return TEMPLATE_ROOT.parent


def default_data_folder(parent: Path, name: str) -> Path:
    """Default data folder for a new project: `<parent>/../projects-data/<name>`.

    Args:
        parent: Folder the project will be created in.
        name: Project name.

    Returns:
        Absolute data folder.
    """
    return (parent.parent / "projects-data" / data_slug(name)).resolve()


def require_dir(raw: str, what: str) -> Path:
    """Validate an existing absolute folder from the page.

    Args:
        raw: Path text (may start with `~`).
        what: Field name for the error message.

    Returns:
        The resolved folder.

    Raises:
        ValueError: When the path is empty, relative or not a folder.
    """
    path = Path(str(raw or "").strip()).expanduser()
    if not str(raw or "").strip() or not path.is_absolute():
        raise ValueError(f"{what}：請選擇完整路徑的資料夾")
    if not path.is_dir():
        raise ValueError(f"{what}：找不到資料夾 {path}")
    return path.resolve()


def project_target(body: dict) -> tuple[str, Path]:
    """Validate the project name and location and return the new folder.

    Args:
        body: Request body with `name` and `parent`.

    Returns:
        Tuple of name and target folder.

    Raises:
        ValueError: When the name is invalid or the folder already has files.
    """
    name = str(body.get("name", "")).strip()
    if not NAME_RE.match(name):
        raise ValueError("專案名稱：只能用英文、數字、中文、空格、- _ .，且不能用 / 或 . 開頭")
    target = require_dir(body.get("parent", ""), "專案位置") / name
    if target.exists() and any(p.name != ".DS_Store" for p in target.iterdir()):
        raise ValueError(f"資料夾已存在而且有檔案：{target}")
    return name, target


def data_preview(body: dict) -> dict:
    """Show which data folder a new project will use and how it is stored.

    Args:
        body: `name`, `parent` and optional `data_dir`.

    Returns:
        `absolute`, `stored` (the value written) and `where` (`.env.example` or `.env only`).
    """
    name = str(body.get("name", "")).strip() or "my-app"
    parent = Path(str(body.get("parent") or projects_root())).expanduser()
    chosen = Path(str(body["data_dir"])).expanduser() if body.get("data_dir") else None
    absolute = chosen.resolve() if chosen else default_data_folder(parent, name)
    stored, shareable = data_dir_setting(parent / name, name, chosen)
    return {"absolute": str(absolute), "stored": stored, "where": ".env.example（相對路徑，可 commit）" if shareable else "只寫在 .env（外接硬碟的絕對路徑）"}


def create_steps(body: dict) -> tuple[str, list[tuple[list[str], Path]]]:
    """Build the commands that create (and optionally set up) a project.

    Args:
        body: Page form fields.

    Returns:
        Tuple of job title and steps.

    Raises:
        ValueError: When a field is invalid.
    """
    name, target = project_target(body)
    stack = str(body.get("stack") or "python")
    addons = [a for a in body.get("addons") or [] if a]
    if stack not in STACK_CHOICES or any(a not in ADDON_CHOICES for a in addons):
        raise ValueError("不支援的 stack 或附加功能")
    resolve_stack(stack, addons)  # raises ValueError for python-only add-ons on other stacks
    argv = [PY, str(TEMPLATE_ROOT / "init_project.py"), "--target", str(target), "--name", name, "--stack", stack]
    argv += ["--with", *addons] if addons else []
    skills = [s for s in body.get("skills") or [] if s]
    unknown = [s for s in skills if s not in load_catalog(TEMPLATE_ROOT)]
    if unknown:
        raise ValueError(f"不認識的 skill：{', '.join(unknown)}")
    argv += ["--skills", *skills] if skills else []
    argv += ["--description", str(body["description"]).strip()] if str(body.get("description") or "").strip() else []
    argv += ["--license", "MIT"] if body.get("license") == "MIT" else []
    argv += ["--timezone", str(body["timezone"]).strip()] if str(body.get("timezone") or "").strip() else []
    argv += ["--data-dir", str(Path(str(body["data_dir"])).expanduser())] if body.get("data_dir") else []
    steps = [(argv, TEMPLATE_ROOT)]
    steps += [([PY, "scripts/agentctl.py", "doctor", "--fix"], target)] if body.get("doctor", True) else []
    steps += [([PY, "scripts/agentctl.py", "setup", "--install"], target)] if body.get("setup") else []
    steps += [([PY, "scripts/agentctl.py", "check"], target)] if body.get("check") else []
    return f"建立專案 {name}", steps


def migrate_steps(body: dict) -> tuple[str, list[tuple[list[str], Path]]]:
    """Build the commands that migrate an old project into a new folder.

    Args:
        body: `source`, `name`, `parent`, `mode`, optional `stack`, `addons`, `data_dir`.

    Returns:
        Tuple of job title and steps.

    Raises:
        ValueError: When a field is invalid.
    """
    source = require_dir(body.get("source", ""), "舊專案")
    name, target = project_target(body)
    if target.exists():
        raise ValueError(f"遷移的目標資料夾必須是新的：{target}")
    argv = [PY, str(TEMPLATE_ROOT / "migrate_project.py"), "--from", str(source), "--target", str(target), "--name", name]
    argv += ["--mode", "develop" if body.get("mode") == "develop" else "maintain"]
    if body.get("stack"):
        if body["stack"] not in STACK_CHOICES:
            raise ValueError("不支援的 stack")
        argv += ["--stack", body["stack"]]
    addons = [a for a in body.get("addons") or [] if a in ADDON_CHOICES]
    argv += ["--with", *addons] if addons else []
    argv += ["--data-dir", str(Path(str(body["data_dir"])).expanduser())] if body.get("data_dir") else []
    steps = [(argv, TEMPLATE_ROOT), ([PY, "scripts/agentctl.py", "doctor", "--fix"], target)]
    return f"遷移 {source.name} → {name}", steps


def list_projects(root: Path) -> list[dict]:
    """List projects created from the template below `root`.

    Args:
        root: Folder to scan.

    Returns:
        Project summaries (name, path, framework version, uncommitted files, last commit).
    """
    rows = []
    for project in update_all.find_projects([root], 3):
        status = subprocess.run(["git", "status", "--porcelain"], cwd=project, capture_output=True, text=True, check=False)
        last = subprocess.run(["git", "log", "-1", "--format=%h %cs %s"], cwd=project, capture_output=True, text=True, check=False)
        rows.append({
            "name": project.name, "path": str(project), "version": collect_feedback.framework_version(project),
            "dirty": len([ln for ln in status.stdout.splitlines() if ln.strip()]), "last_commit": last.stdout.strip(),
        })
    return rows


def feedback(root: Path, include_all: bool) -> dict:
    """Collect template suggestions from every project.

    Args:
        root: Folder to scan.
        include_all: Include adopted / rejected suggestions.

    Returns:
        `scanned` count and `items` (date, project, version, text, source, status, file).
    """
    files = collect_feedback.find_feedback_files([root], 3)
    items = [s for f in files for s in collect_feedback.read_suggestions(f) if include_all or collect_feedback.is_open(s)]
    rows = [{"date": s.date, "project": s.project, "version": s.version, "text": s.text, "source": s.source,
             "status": s.status, "file": str(s.file)} for s in sorted(items, key=lambda s: (s.date, s.project))]
    return {"scanned": len(files), "items": rows}


def update_preview(root: Path) -> list[dict]:
    """Preview the framework update for every project (nothing changes).

    Args:
        root: Folder to scan.

    Returns:
        One row per project with versions, file counts and status.
    """
    plans = [update_all.preview(p) for p in update_all.find_projects([root], 3)]
    update_all.classify(plans)
    return [{"name": p.path.name, "path": str(p.path), "current": p.current, "target": p.target,
             **{k: len(v) for k, v in p.files.items()}, "removed_files": p.files["removed"], "status": p.status} for p in plans]


def info() -> dict:
    """Describe the template for the page (versions, choices, defaults).

    Returns:
        Settings and option lists.
    """
    catalog = load_catalog(TEMPLATE_ROOT)
    return {
        "framework_version": FRAMEWORK_VERSION, "template": str(TEMPLATE_ROOT), "projects_root": str(projects_root()),
        "stacks": list(STACK_CHOICES), "addons": list(ADDON_CHOICES), "python_only": list(PYTHON_ONLY_ADDONS),
        "skills": [{"name": n, "tier": m.get("tier", ""), "trigger": m.get("trigger", ""), "stacks": m.get("stacks", [])}
                   for n, m in sorted(catalog.items())],
        "native_picker": sys.platform == "darwin",
    }


def pick_folder(prompt: str, start: str) -> str:
    """Open the macOS folder dialog and return the chosen folder.

    Args:
        prompt: Dialog title.
        start: Folder to open first (may be empty).

    Returns:
        The chosen POSIX path, or an empty string when cancelled.
    """
    location = f' default location (POSIX file "{start}")' if start and Path(start).is_dir() else ""
    script = f'POSIX path of (choose folder with prompt "{prompt.replace(chr(34), "")}"{location})'
    res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, check=False)
    return res.stdout.strip().rstrip("/") if res.returncode == 0 else ""


class Handler(BaseHTTPRequestHandler):
    """HTTP handler: the page, the JSON API and the local-only checks."""

    allowed_hosts: set[str] = set()
    allowed_origins: set[str] = set()

    def log_message(self, fmt: str, *args) -> None:
        """Keep the terminal quiet (errors are shown on the page).

        Args:
            fmt: Format string.
            *args: Values.
        """

    def _send(self, status: int, payload: object, content_type: str = "application/json") -> None:
        """Send a response.

        Args:
            status: HTTP status.
            payload: JSON-serialisable data, or bytes for other content types.
            content_type: Response content type.
        """
        body = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _local_only(self, changing: bool) -> bool:
        """Refuse requests to a foreign Host, and state changes from a foreign Origin.

        Args:
            changing: The request changes something (POST).

        Returns:
            True when the request may continue.
        """
        host = (self.headers.get("Host") or "").lower()
        origin = self.headers.get("Origin")
        if host not in self.allowed_hosts or (changing and origin and origin.lower() not in self.allowed_origins):
            self._send(403, {"detail": "only local requests from this page are allowed"})
            return False
        return True

    def _body(self) -> dict:
        """Read the JSON request body.

        Returns:
            Decoded body (empty dict when missing).
        """
        length = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(length).decode("utf-8") or "{}") if length else {}

    def do_GET(self) -> None:  # noqa: N802 - http.server naming
        """Serve the page and the read-only API."""
        if not self._local_only(changing=False):
            return
        url = urlparse(self.path)
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        try:
            if url.path in ("/", "/index.html"):
                self._send(200, PAGE.read_bytes(), "text/html")
            elif url.path == "/api/info":
                self._send(200, info())
            elif url.path == "/api/projects":
                self._send(200, list_projects(require_dir(query.get("root") or str(projects_root()), "掃描位置")))
            elif url.path == "/api/feedback":
                self._send(200, feedback(require_dir(query.get("root") or str(projects_root()), "掃描位置"), query.get("all") == "1"))
            elif url.path == "/api/job":
                job = RUNNER.current
                self._send(200, None if job is None else {"id": job.id, "title": job.title, "state": job.state,
                                                         "log": job.log[-400:], "result": job.result, "returncode": job.returncode})
            elif url.path == "/api/dirs":
                path = require_dir(query.get("path") or str(Path.home()), "資料夾")
                subdirs = sorted(p.name for p in path.iterdir() if p.is_dir() and not p.name.startswith("."))
                self._send(200, {"path": str(path), "parent": str(path.parent), "dirs": subdirs})
            else:
                self._send(404, {"detail": "not found"})
        except (ValueError, OSError) as exc:
            self._send(400, {"detail": str(exc)})

    def do_POST(self) -> None:  # noqa: N802 - http.server naming
        """Handle actions (create, migrate, project commands, update, folder picker)."""
        if not self._local_only(changing=True):
            return
        path = urlparse(self.path).path
        try:
            body = self._body()
            if path == "/api/data-preview":
                self._send(200, data_preview(body))
                return
            if path == "/api/pick-folder":
                self._send(200, {"path": pick_folder(str(body.get("prompt") or "選擇資料夾"), str(body.get("start") or ""))})
                return
            if path == "/api/reveal":
                subprocess.run(["open", str(require_dir(body.get("path", ""), "資料夾"))], check=False)
                self._send(200, {"ok": True})
                return
            job = self._start_job(path, body)
            if job is None:
                self._send(404, {"detail": "not found"})
            else:
                self._send(202, {"id": job.id, "title": job.title, "commands": [shlex.join(a) for a, _ in job.steps]})
        except RuntimeError as exc:
            self._send(409, {"detail": str(exc)})
        except (ValueError, OSError, json.JSONDecodeError) as exc:
            self._send(400, {"detail": str(exc)})

    def _start_job(self, path: str, body: dict) -> Job | None:
        """Start the background job for an action endpoint.

        Args:
            path: Request path.
            body: Request body.

        Returns:
            The started job, or None for an unknown path.
        """
        if path == "/api/create":
            return RUNNER.start(*create_steps(body))
        if path == "/api/migrate":
            return RUNNER.start(*migrate_steps(body))
        if path == "/api/project-command":
            command = PROJECT_COMMANDS.get(str(body.get("command")))
            project = require_dir(body.get("path", ""), "專案")
            if command is None or not (project / "scripts" / "agentctl.py").exists():
                raise ValueError("不是用母版建立的專案，或不支援的指令")
            return RUNNER.start(f"{project.name}：agentctl {' '.join(command)}", [([PY, "scripts/agentctl.py", *command], project)])
        root = require_dir(body.get("root") or str(projects_root()), "掃描位置")
        if path == "/api/update/preview":
            return RUNNER.start("更新預覽", [], after=lambda job: setattr(job, "result", update_preview(root)))
        if path == "/api/update/apply":
            argv = [PY, str(TOOLS / "update_all.py"), str(root), "--apply", "--yes"] + (["--no-commit"] if body.get("commit") is False else [])
            return RUNNER.start("更新所有專案的框架", [(argv, TEMPLATE_ROOT)], after=lambda job: setattr(job, "result", update_preview(root)))
        return None


def main(argv: list[str] | None = None) -> int:
    """Start the local server and open the page.

    Args:
        argv: Command-line arguments; defaults to `sys.argv[1:]`.

    Returns:
        Process exit code.
    """
    parser = argparse.ArgumentParser(description="母版的本機網頁與 JSON API（只綁 127.0.0.1）")
    parser.add_argument("--port", type=int, default=int(os.environ.get("TEMPLATE_UI_PORT", DEFAULT_PORT)))
    parser.add_argument("--allow-host", action="append", default=[], help="額外允許的 Host（Open WebUI 在 Docker：host.docker.internal）")
    parser.add_argument("--no-browser", action="store_true", help="不自動打開瀏覽器")
    args = parser.parse_args(argv)
    hosts = ["127.0.0.1", "localhost", *args.allow_host]
    Handler.allowed_hosts = {f"{h}:{args.port}".lower() for h in hosts}
    Handler.allowed_origins = {f"http://{h}:{args.port}".lower() for h in ("127.0.0.1", "localhost")}
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}"
    print(f"🌐 母版網頁：{url}（Ctrl+C 結束；API 文件見 tools/web/API.md）")
    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已關閉。")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
