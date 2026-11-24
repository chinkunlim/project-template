"""Inspection, overview, git remote sync, and Graphify actions across tracked projects.

Purpose:
    Keeps `services/template_service.py` modular while providing a single source of
    truth for reading tracked project status (git, tasks, Graphify, web service),
    registering existing projects, and building `git fetch` / `git push` / `graphify` steps.
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from project_template.adapters import project_registry
from project_template.config.framework import FRAMEWORK_VERSION, parse_toml
from project_template.config.settings import TEMPLATE_ROOT, resolve_graphify
from project_template.services import feedback as collect_feedback
from project_template.services import update_all, web_launcher

logger = logging.getLogger(__name__)
PY = sys.executable
DONE_TASK_STATES = {"done", "cancelled", "completed"}


def require_dir(raw: object, what: str) -> Path:
    """Validate an existing absolute folder from the page.

    Args:
        raw: Path text (may start with `~`).
        what: Field name for the error message.

    Returns:
        The resolved folder.

    Raises:
        ValueError: When the path is empty, relative or not a folder.
    """
    text = str(raw or "").strip()
    path = Path(text).expanduser()
    if not text or not path.is_absolute():
        raise ValueError(f"{what}：請選擇完整路徑的資料夾")
    if not path.is_dir():
        raise ValueError(f"{what}：找不到資料夾 {path}")
    return path.resolve()


def tracked(root: Path) -> list[Path]:
    """Every project the actions work on: below `root` plus registered ones elsewhere.

    Args:
        root: Folder to scan (normally the folder that contains the template).

    Returns:
        Sorted project folders (`update_all.tracked_projects()`).
    """
    return update_all.tracked_projects([root], 3)


def list_projects(root: Path) -> list[dict[str, Any]]:
    """List the tracked projects (below `root` + registered).

    Args:
        root: Folder to scan.

    Returns:
        Project summaries (name, path, framework version, uncommitted files, last commit).
    """
    rows = []
    for project in tracked(root):
        status = subprocess.run(["git", "status", "--porcelain"], cwd=project, capture_output=True, text=True, check=False)
        last = subprocess.run(["git", "log", "-1", "--format=%h %cs %s"], cwd=project, capture_output=True, text=True, check=False)
        rows.append({
            "name": project.name,
            "path": str(project),
            "version": collect_feedback.framework_version(project),
            "dirty": len([ln for ln in status.stdout.splitlines() if ln.strip()]),
            "last_commit": last.stdout.strip(),
        })
    return rows


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


def _task_summary(project: Path) -> dict[str, Any]:
    """Read open/handed-off tasks from `<project>/.agents/tasks/TASK-*.json`.

    Args:
        project: Project root directory.

    Returns:
        Dict with open `count` and up to 6 active task summaries (`id`, `title`, `status`).
    """
    task_dir = project / ".agents" / "tasks"
    if not task_dir.is_dir():
        return {"count": 0, "items": []}
    active: list[dict[str, str]] = []
    for task_file in sorted(task_dir.glob("TASK-*.json")):
        try:
            data = json.loads(task_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        status = str(data.get("status") or "").strip().lower()
        if status in DONE_TASK_STATES:
            continue
        active.append({
            "id": str(data.get("id") or task_file.stem.split("-", 2)[0]),
            "title": str(data.get("title") or ""),
            "status": str(data.get("status") or "open"),
        })
    return {"count": len(active), "items": active[:6]}


def _graphify_summary(project: Path) -> dict[str, Any]:
    """Inspect Graphify and framework AST graph freshness inside a project.

    Args:
        project: Project root directory.

    Returns:
        Dict with `ready` (Graphify output exists), `updated_at`, and `arch_graph` boolean.
    """
    graph_json = project / "graphify-out" / "graph.json"
    arch_json = project / ".agents" / "cache" / "graph.json"
    newest = graph_json if graph_json.is_file() else (arch_json if arch_json.is_file() else None)
    updated_at = ""
    if newest is not None:
        updated_at = datetime.fromtimestamp(newest.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
    return {"ready": graph_json.is_file(), "updated_at": updated_at, "arch_graph": arch_json.is_file()}


def project_status(project: Path) -> dict[str, Any]:
    """Collect what the overview shows for one project (local only: no network, nothing changes).

    Args:
        project: Project folder.

    Returns:
        Status dict including git, version, open feedback, MCP, Web service, tasks, and Graphify state.
    """
    toml_file = project / ".agents" / "project.toml"
    settings = parse_toml(toml_file.read_text(encoding="utf-8")) if toml_file.exists() else {}
    info_ = settings.get("project", {})
    upstream = _git(project, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    counts = (_git(project, "rev-list", "--left-right", "--count", f"{upstream}...HEAD").split() + ["0", "0"])[:2]
    behind, ahead = counts if upstream else ("0", "0")
    remote = re.sub(r"//[^@/]+@", "//", _git(project, "remote", "get-url", "origin"))  # never show credentials
    feedback_file = project / "docs" / "TEMPLATE_FEEDBACK.md"
    suggestions = collect_feedback.read_suggestions(feedback_file) if feedback_file.exists() else []
    return {
        "name": project.name,
        "path": str(project),
        "exists": True,
        "stack": info_.get("stack", ""),
        "addons": info_.get("addons", []),
        "version": collect_feedback.framework_version(project),
        "template_version": FRAMEWORK_VERSION,
        "dirty": len([ln for ln in _git(project, "status", "--porcelain").splitlines() if ln.strip()]),
        "branch": _git(project, "rev-parse", "--abbrev-ref", "HEAD"),
        "upstream": upstream,
        "remote": remote,
        "ahead": int(ahead or 0),
        "behind": int(behind or 0),
        "last_commit": _git(project, "log", "-1", "--format=%h %cs %s"),
        "open_feedback": len([x for x in suggestions if collect_feedback.is_open(x)]),
        "mcp": (project / ".mcp.json").exists(),
        "web": web_launcher.service_status(project),
        "tasks": _task_summary(project),
        "graphify": _graphify_summary(project),
    }


def overview(root: Path) -> list[dict[str, Any]]:
    """Every tracked project: found in `root` plus the ones recorded in the registry.

    Args:
        root: Folder to scan (normally the folder that contains the template).

    Returns:
        One status per project; registry entries whose folder is gone are listed with `exists: False`.
    """
    registry = {str(Path(r["path"]).resolve()): r for r in project_registry.load()}
    base = root.expanduser().resolve()
    rows = []
    for project in sorted(tracked(root), key=lambda p: p.name.lower()):
        status = project_status(project)
        status["source"] = "folder" if project.is_relative_to(base) else "registry"
        status["how"] = registry.get(str(project), {}).get("how", "")
        rows.append(status)
    rows += [
        {"name": r["name"], "path": r["path"], "exists": False, "how": r.get("how", ""), "source": "registry"}
        for r in registry.values()
        if not r["exists"]
    ]
    return rows


def register_existing(raw: str) -> dict[str, Any]:
    """Check that a folder can be added to the registry (an existing project made with the template).

    Args:
        raw: Absolute folder from the caller.

    Returns:
        `path`, `name` and `already` (True when it is registered already).

    Raises:
        ValueError: When the folder is missing, is the template, or lacks `.agents/framework.lock` / `scripts/agentctl.py`.
    """
    project = require_dir(raw, "既有專案")
    if project == TEMPLATE_ROOT:
        raise ValueError("這是母版本身，不是專案")
    if not update_all.is_project(project):
        raise ValueError(
            f"{project} 不是用母版建立的專案（需要 .agents/framework.lock 和 scripts/agentctl.py）；"
            "舊專案請用「遷移舊專案」"
        )
    already = any(Path(r["path"]).resolve() == project for r in project_registry.load())
    return {"path": str(project), "name": project.name, "already": already}


def add_existing(raw: str) -> dict[str, Any]:
    """Add an existing project folder to the registry (the user confirmed it; the folder is not changed).

    Args:
        raw: Absolute project folder.

    Returns:
        `path`, `name`, `already` and `added`.

    Raises:
        ValueError: When the folder is not a template project (see `register_existing()`).
    """
    found = register_existing(raw)
    if not found["already"]:
        project_registry.register(Path(found["path"]), "existing")
    logger.info("📌 登記既有專案 %s（%s）", found["path"], "已在清單" if found["already"] else "新加入")
    return {**found, "added": not found["already"]}


def fetch_steps(body: dict[str, Any], root: Path) -> tuple[str, list[tuple[list[str], Path]]]:
    """Build the `git fetch` commands that refresh the unpushed / behind counts.

    Args:
        body: Optional `path` of one project; empty = every tracked project that has a remote.
        root: Folder to scan when no path is given.

    Returns:
        Tuple of job title and steps (no password prompts: `GIT_TERMINAL_PROMPT=0`).

    Raises:
        ValueError: When the given project or every tracked project has no git remote.
    """
    projects = [require_dir(body["path"], "專案")] if body.get("path") else tracked(root)
    with_remote = [p for p in projects if _git(p, "remote")]
    if not with_remote:
        raise ValueError("沒有設定 git 遠端的專案，不需要 fetch")
    argv = ["env", "GIT_TERMINAL_PROMPT=0", "git", "fetch", "--all", "--quiet"]
    title = f"git fetch {with_remote[0].name}" if body.get("path") else f"git fetch（{len(with_remote)} 個專案）"
    return title, [(argv, p) for p in with_remote]


def push_steps(body: dict[str, Any]) -> tuple[str, list[tuple[list[str], Path]]]:
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


def resolve_feedback_target(project_ref: str, root: Path) -> Path:
    """Resolve a project reference (`master`, template name, tracked name, or path) for feedback edits.

    Args:
        project_ref: Project selector string.
        root: Base projects directory.

    Returns:
        Resolved directory path.
    """
    cleaned = project_ref.strip()
    if cleaned in ("master", "__master__", TEMPLATE_ROOT.name):
        return TEMPLATE_ROOT.resolve()
    return web_launcher.resolve_project_path(cleaned, root)


def graphify_steps(body: dict[str, Any], root: Path) -> tuple[str, list[tuple[list[str], Path]]]:
    """Build commands to refresh framework dependency graphs and Graphify knowledge graphs.

    Args:
        body: Dict with optional `path` or `project`, and optional `include_master` boolean.
        root: Base projects directory.

    Returns:
        Tuple of job title and `(argv, cwd)` steps.

    Raises:
        ValueError: When no matching tracked projects exist.
    """
    ref = str(body.get("path") or body.get("project") or "").strip()
    if ref:
        targets = [resolve_feedback_target(ref, root)]
    else:
        targets = tracked(root)
        if body.get("include_master"):
            targets = [TEMPLATE_ROOT.resolve(), *targets]
    if not targets:
        raise ValueError("找不到可更新圖譜的追蹤專案")
    graphify_bin = resolve_graphify()
    steps: list[tuple[list[str], Path]] = []
    for project in targets:
        if (project / "scripts" / "agentctl.py").is_file():
            steps.append(([PY, "scripts/agentctl.py", "graph"], project))
        if graphify_bin:
            steps.append(([graphify_bin, "update", "."], project))
    if not steps:
        raise ValueError("目標資料夾缺少 `scripts/agentctl.py` 且未安裝 `graphify`")
    title = f"更新圖譜：{targets[0].name}" if ref else f"更新全部 Graphify 圖譜（{len(targets)} 個專案）"
    return title, steps
