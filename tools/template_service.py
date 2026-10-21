#!/usr/bin/env python3
"""Template actions shared by the web page, the JSON API and the MCP server (standard library only).

Purpose:
    One place for everything the template can do: create a project, migrate an old project, list
    projects and run framework commands in them, collect template feedback, and preview / apply the
    framework update. `tools/web_ui.py` (FastAPI page + JSON API + `/mcp`) and `tools/template_mcp.py`
    (MCP over stdio) only translate requests into these functions, so every entrypoint behaves the same.

    Actions run the existing command-line tools (`init_project.py`, `migrate_project.py`,
    `agentctl …`, `update_all.py`) as background jobs, one at a time, and keep their output.
    `DATA_DIR` is removed from the environment of every command, so a variable inherited by the
    caller (e.g. Open WebUI's `export DATA_DIR=...`) never overrides a project's own `.env`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import threading
import time

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
from project_config import FRAMEWORK_VERSION, parse_toml  # noqa: E402
import project_registry  # noqa: E402
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


def project_command_steps(body: dict) -> tuple[str, list[tuple[list[str], Path]]]:
    """Build the command that runs `agentctl <command>` inside one project.

    Args:
        body: `path` (project folder) and `command` (a key of `PROJECT_COMMANDS`).

    Returns:
        Tuple of job title and steps.

    Raises:
        ValueError: When the folder is not a template project or the command is unknown.
    """
    command = PROJECT_COMMANDS.get(str(body.get("command")))
    project = require_dir(body.get("path", ""), "專案")
    if command is None or not (project / "scripts" / "agentctl.py").exists():
        raise ValueError("不是用母版建立的專案，或不支援的指令")
    return f"{project.name}：agentctl {' '.join(command)}", [([PY, "scripts/agentctl.py", *command], project)]


def update_apply_steps(root: Path, commit: bool = True) -> tuple[str, list[tuple[list[str], Path]]]:
    """Build the command that updates every updatable project.

    Args:
        root: Folder that holds the projects.
        commit: Commit each cleanly updated project locally.

    Returns:
        Tuple of job title and steps.
    """
    argv = [PY, str(TOOLS / "update_all.py"), str(root), "--apply", "--yes"] + ([] if commit else ["--no-commit"])
    return "更新所有專案的框架", [(argv, TEMPLATE_ROOT)]


def resolve_root(raw: str | None) -> Path:
    """Folder to scan for projects (default: the folder that contains the template).

    Args:
        raw: Folder from the caller, or empty.

    Returns:
        The validated folder.
    """
    return require_dir(raw or str(projects_root()), "掃描位置")


def job_view(job: Job | None) -> dict | None:
    """Describe a job for JSON responses.

    Args:
        job: Current job, or None.

    Returns:
        `id`, `title`, `state`, the last 400 log lines, `result` and `returncode`.
    """
    if job is None:
        return None
    return {"id": job.id, "title": job.title, "state": job.state, "log": job.log[-400:], "result": job.result,
            "returncode": job.returncode}


def wait_for(job: Job, timeout: float = 900) -> Job:
    """Block until a job ends (used by MCP tools, which answer only when the work is done).

    Args:
        job: Job to wait for.
        timeout: Longest wait in seconds.

    Returns:
        The job (still `running` when the timeout passed).
    """
    deadline = time.monotonic() + timeout
    while job.state == "running" and time.monotonic() < deadline:
        time.sleep(0.3)
    return job


def _git(project: Path, *args: str) -> str:
    """Run a read-only git command in a project.

    Args:
        project: Project folder.
        *args: Arguments after `git`.

    Returns:
        Trimmed output, or an empty string when git fails.
    """
    res = subprocess.run(["git", *args], cwd=project, capture_output=True, text=True, check=False)
    return res.stdout.strip() if res.returncode == 0 else ""


def project_status(project: Path) -> dict:
    """Collect what the overview shows for one project (local only: no network, nothing changes).

    Args:
        project: Project folder.

    Returns:
        Name, stack, framework version, uncommitted files, branch, remote, ahead / behind its upstream
        (as of the last fetch), last commit, open template suggestions and whether AI tools are configured.
    """
    toml_file = project / ".agents" / "project.toml"
    settings = parse_toml(toml_file.read_text(encoding="utf-8")) if toml_file.exists() else {}
    info_ = settings.get("project", {})
    upstream = _git(project, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    behind, ahead = (_git(project, "rev-list", "--left-right", "--count", f"{upstream}...HEAD").split() + ["0", "0"])[:2] \
        if upstream else ("0", "0")
    remote = re.sub(r"//[^@/]+@", "//", _git(project, "remote", "get-url", "origin"))  # never show credentials
    feedback_file = project / "docs" / "TEMPLATE_FEEDBACK.md"
    suggestions = collect_feedback.read_suggestions(feedback_file) if feedback_file.exists() else []
    return {
        "name": project.name, "path": str(project), "exists": True,
        "stack": info_.get("stack", ""), "addons": info_.get("addons", []),
        "version": collect_feedback.framework_version(project), "template_version": FRAMEWORK_VERSION,
        "dirty": len([ln for ln in _git(project, "status", "--porcelain").splitlines() if ln.strip()]),
        "branch": _git(project, "rev-parse", "--abbrev-ref", "HEAD"), "upstream": upstream, "remote": remote,
        "ahead": int(ahead or 0), "behind": int(behind or 0),
        "last_commit": _git(project, "log", "-1", "--format=%h %cs %s"),
        "open_feedback": len([x for x in suggestions if collect_feedback.is_open(x)]),
        "mcp": (project / ".mcp.json").exists(),
    }


def overview(root: Path) -> list[dict]:
    """Every project to track: found in `root` plus the ones recorded in the registry.

    Args:
        root: Folder to scan (normally the folder that contains the template).

    Returns:
        One status per project; registry entries whose folder is gone are listed with `exists: False`.
    """
    registry = {str(Path(r["path"]).resolve()): r for r in project_registry.load()}
    found = {str(p.resolve()): p for p in update_all.find_projects([root], 3)}
    in_folder = set(found)
    for key, row in registry.items():
        if row["exists"] and key not in found and (Path(key) / ".agents" / "framework.lock").exists():
            found[key] = Path(key)
    rows = []
    for key, project in sorted(found.items(), key=lambda kv: kv[1].name.lower()):
        status = project_status(project)
        status["source"] = "folder" if key in in_folder else "registry"
        status["how"] = registry.get(key, {}).get("how", "")
        rows.append(status)
    rows += [{"name": r["name"], "path": r["path"], "exists": False, "how": r.get("how", ""), "source": "registry"}
             for key, r in registry.items() if not r["exists"]]
    return rows


def push_steps(body: dict) -> tuple[str, list[tuple[list[str], Path]]]:
    """Build the command that pushes a project to its upstream (the user clicked / confirmed it).

    Args:
        body: `path` of the project.

    Returns:
        Tuple of job title and steps (`ALLOW_PUSH=1 git push`, which the pre-push hook lets through).

    Raises:
        ValueError: When the folder is not a project or has no upstream branch.
    """
    project = require_dir(body.get("path", ""), "專案")
    if not _git(project, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"):
        raise ValueError(f"{project.name} 沒有設定遠端分支（upstream）：先在專案內設定 GitHub 遠端並推送一次")
    return f"推送 {project.name}", [(["env", "ALLOW_PUSH=1", "git", "push"], project)]

