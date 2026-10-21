"""Update the framework of every project from this template in one go (template-only tool).

Purpose:
    Each project gets template improvements through the framework updater
    (`.agents/bin/update_framework.py`), which never overwrites files the project changed (it
    saves `<file>.template` instead). With many projects that is one command per project, so this tool:
      1. finds every tracked project (`tracked_projects()`): the ones below a folder (default: the
         folder that contains the template) with `.agents/framework.lock` + `scripts/agentctl.py`,
         plus the registered ones (`.local/projects.json`) that still exist, wherever they are;
      2. by default only PREVIEWS: runs the TEMPLATE's updater on each project with
         `--project <path> --dry-run` (the template's copy is always the newest, so projects
         whose own updater predates a layout change still update) and prints one table
         (version, files to update / add, conflicts, removed files);
      3. with `--apply` (after you confirm), updates each project, re-activates its hooks
         (`agentctl doctor --fix`), runs `agentctl check`, and makes one local commit
         `chore(framework): update to vX.Y.Z` — only when there are no conflicts and the
         check passes; otherwise the changes are left uncommitted for you to review.

Safety:
    - The template must be committed (projects record which template commit they got).
    - Projects with uncommitted changes are skipped, so every update is its own clean diff.
    - Nothing is pushed and nothing is deleted (files removed from the template are listed).

Usage:
    `scripts/update_all.py` (see `entrypoints/update_all_cli.py`) and the web page call
    `tracked_projects()`, `preview()`, `classify()` and `apply()`. The overview, project list, feedback
    and update of the page / API / MCP all use `tracked_projects()`, so they see the same projects.
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from project_template.adapters import project_registry
from project_template.config.settings import TEMPLATE_ROOT, child_env

logger = logging.getLogger(__name__)
UPDATER = TEMPLATE_ROOT / ".agents" / "bin" / "update_framework.py"
# Projects normally sit next to the template (e.g. ~/Desktop/projects/01 project_template and
# ~/Desktop/projects/<project>), so the default follows the template wherever it is moved.
DEFAULT_ROOT = TEMPLATE_ROOT.parent
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "legacy", ".skills-cache", "__pycache__", "dist", "build"}
PLAN_LABELS = {"🔄 更新": "update", "➕ 新增": "add", "⚠️ 專案已修改": "conflict", "🗑️ 母版已移除": "removed"}
VERSION_RE = re.compile(r"框架 v([0-9A-Za-z.?+-]+) ➔ v([0-9A-Za-z.?+-]+)")


@dataclass
class ProjectPlan:
    """What an update would do to one project.

    Attributes:
        path: Project root directory.
        current: Framework version the project has (`?` when unknown).
        target: Framework version of the template.
        files: Plan lists keyed by `update`, `add`, `conflict`, `removed`.
        status: Result text shown in the summary table.
    """

    path: Path
    current: str = "?"
    target: str = "?"
    files: dict[str, list[str]] = field(default_factory=lambda: {k: [] for k in PLAN_LABELS.values()})
    status: str = ""

    @property
    def has_changes(self) -> bool:
        """Tell whether the update would write anything.

        Returns:
            True when files would be updated, added or need merging, or the version differs.
        """
        return bool(self.files["update"] or self.files["add"] or self.files["conflict"]) or self.current != self.target


def run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run a command and capture its output.

    Args:
        cmd: Command and arguments.
        cwd: Working directory.

    Returns:
        The completed process.
    """
    # An inherited DATA_DIR would override each project's own .env (e.g. doctor --fix creating folders)
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False, env=child_env())


def agentctl(project: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run the project's own `scripts/agentctl.py`.

    Args:
        project: Project root directory.
        *args: Sub-command and options.

    Returns:
        The completed process.
    """
    return run([sys.executable, "scripts/agentctl.py", *args], project)


def update_framework(project: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run the template's framework updater on one project.

    Args:
        project: Project root directory.
        *args: Extra options, e.g. `--dry-run`.

    Returns:
        The completed process.
    """
    return run([sys.executable, str(UPDATER), "--from", str(TEMPLATE_ROOT), "--project", str(project), *args], project)


def is_project(folder: Path) -> bool:
    """Tell whether a folder is a project made with this template (not the template itself).

    Args:
        folder: Folder to check.

    Returns:
        True when it has `.agents/framework.lock` and `scripts/agentctl.py`.
    """
    resolved = folder.resolve()
    return resolved != TEMPLATE_ROOT and (resolved / ".agents" / "framework.lock").is_file() \
        and (resolved / "scripts" / "agentctl.py").is_file()


def registered_projects() -> list[Path]:
    """Projects recorded in the registry whose folder still exists and is still a template project.

    Returns:
        Sorted resolved project roots (moved or deleted folders are left out).
    """
    return sorted({Path(r["path"]).resolve() for r in project_registry.load() if r["exists"] and is_project(Path(r["path"]))})


def tracked_projects(roots: list[Path], depth: int = 3, registered: bool = True) -> list[Path]:
    """Every project to work on: the ones found below `roots` plus (by default) the registered ones.

    Args:
        roots: Folders that contain projects.
        depth: How many folder levels below each root a project may sit.
        registered: Also include registered projects outside `roots`.

    Returns:
        Sorted resolved project roots, each once.
    """
    found = set(find_projects(roots, depth))
    if registered:
        found.update(registered_projects())
    logger.debug(f"🔎 追蹤 {len(found)} 個專案（資料夾 {len(roots)} 個{'＋登記清單' if registered else ''}）")
    return sorted(found)


def find_projects(roots: list[Path], depth: int) -> list[Path]:
    """Find projects created from this template below the given folders.

    Args:
        roots: Folders that contain projects.
        depth: How many folder levels below each root a project may sit.

    Returns:
        Sorted project roots (the template itself is skipped).
    """
    found: set[Path] = set()
    for root in roots:
        base = root.expanduser().resolve()
        if not base.is_dir():
            logger.warning(f"⚠️ 找不到資料夾：{base}")
            continue
        for current, dirs, _files in os.walk(base):
            here = Path(current)
            level = len(here.relative_to(base).parts)
            dirs[:] = [] if level >= depth else [d for d in dirs if d not in SKIP_DIRS]
            if is_project(here):
                found.add(here.resolve())
                dirs[:] = []  # projects are not nested inside projects
    return sorted(found)


def is_dirty(path: Path) -> bool:
    """Tell whether a git working tree has uncommitted changes.

    Args:
        path: Repository root.

    Returns:
        True when `git status --porcelain` lists anything (or the folder is not a git repo).
    """
    res = run(["git", "status", "--porcelain"], path)
    return res.returncode != 0 or bool(res.stdout.strip())


def preview(project: Path) -> ProjectPlan:
    """Ask the template's updater what it would change in a project (`--dry-run`).

    Args:
        project: Project root directory.

    Returns:
        The parsed plan (status says why when the preview failed).
    """
    plan = ProjectPlan(project)
    res = update_framework(project, "--dry-run")
    if res.returncode != 0:
        plan.status = f"❌ 無法預覽：{(res.stderr or res.stdout).strip().splitlines()[-1:]}"
        return plan
    for line in res.stdout.splitlines():
        version = VERSION_RE.search(line)
        if version:
            plan.current, plan.target = version.group(1), version.group(2)
        for label, key in PLAN_LABELS.items():
            if line.strip().startswith(label):
                plan.files[key].append(line.split(": ", 1)[-1].strip())
    return plan


def apply(plan: ProjectPlan, commit: bool) -> str:
    """Update one project, re-activate hooks, check it, and commit when it is safe.

    Args:
        plan: The project's preview.
        commit: Make the local commit when there are no conflicts and the check passes.

    Returns:
        Status text for the summary table.
    """
    project = plan.path
    res = update_framework(project)
    if res.returncode != 0:
        return "❌ update 失敗（在母版執行 `python3 .agents/bin/update_framework.py --from . --project <專案>` 看輸出）"
    agentctl(project, "doctor", "--fix")  # re-activates hooks after layout changes (v3.0 -> v3.1 moved them to .agents/hooks)
    if plan.files["conflict"]:
        return f"⚠️ 已更新，{len(plan.files['conflict'])} 個衝突待合併（*.template），未 commit"
    if agentctl(project, "check").returncode != 0:
        return "⚠️ 已更新，但 `agentctl check` 未通過，未 commit"
    if not commit:
        return "✅ 已更新（未 commit）"
    message = f"chore(framework): update to v{plan.target}"
    res = agentctl(project, "commit", "--agent", "update_all", "--bump", "none", "-m", message)
    return "✅ 已更新並 commit" if res.returncode == 0 else "⚠️ 已更新，但 commit 失敗（看 pre-commit 訊息）"


def render_table(plans: list[ProjectPlan]) -> str:
    """Render the summary table.

    Args:
        plans: Every project's plan with its status filled in.

    Returns:
        Markdown table text.
    """
    lines = ["| 專案 | 版本 | 更新 | 新增 | 衝突 | 母版已移除 | 狀態 |", "|---|---|---|---|---|---|---|"]
    for p in plans:
        f = p.files
        lines.append(f"| `{p.path.name}` | v{p.current} ➔ v{p.target} | {len(f['update'])} | {len(f['add'])} | "
                     f"{len(f['conflict'])} | {len(f['removed'])} | {p.status} |")
    return "\n".join(lines)


def classify(plans: list[ProjectPlan]) -> list[ProjectPlan]:
    """Fill in the preview status and return the projects that can be updated.

    Args:
        plans: Previews of every project.

    Returns:
        Projects with changes and a clean working tree.
    """
    ready = []
    for p in plans:
        if p.status:
            continue
        if not p.has_changes:
            p.status = "已是最新"
        elif is_dirty(p.path):
            p.status = "⏭️ 略過：有未 commit 的修改，先 commit 再更新"
        else:
            p.status = "可更新" + ("（有衝突，需手動合併）" if p.files["conflict"] else "")
            ready.append(p)
    return ready
