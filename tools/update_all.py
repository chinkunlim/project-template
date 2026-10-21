#!/usr/bin/env python3
"""Update the framework of every project from this template in one go (template-only tool).

Purpose:
    Each project gets template improvements through `agentctl update --from <template>`,
    which never overwrites files the project changed (it saves `<file>.template` instead).
    With many projects that is one command per project, so this tool:
      1. finds every project below a folder (default: the folder that contains the template)
         with `.agents/framework.lock` + `scripts/agentctl.py`;
      2. by default only PREVIEWS: runs each project's `agentctl update --dry-run` and prints
         one table (version, files to update / add, conflicts, removed files);
      3. with `--apply` (after you confirm), updates each project, re-activates its hooks
         (`agentctl doctor --fix`), runs `agentctl check`, and makes one local commit
         `chore(framework): update to vX.Y.Z` — only when there are no conflicts and the
         check passes; otherwise the changes are left uncommitted for you to review.

Safety:
    - The template must be committed (projects record which template commit they got).
    - Projects with uncommitted changes are skipped, so every update is its own clean diff.
    - Nothing is pushed and nothing is deleted (files removed from the template are listed).

Usage:
    python3 tools/update_all.py                      # preview only
    python3 tools/update_all.py --apply              # asks once, then updates
    python3 tools/update_all.py ~/work --apply --yes --no-commit
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import os
from pathlib import Path
import re
import subprocess
import sys

TEMPLATE_ROOT = Path(__file__).resolve().parent.parent
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


def run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess:
    """Run a command and capture its output.

    Args:
        cmd: Command and arguments.
        cwd: Working directory.

    Returns:
        The completed process.
    """
    # An inherited DATA_DIR would override each project's own .env (e.g. doctor --fix creating folders)
    env = {k: v for k, v in os.environ.items() if k != "DATA_DIR"}
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False, env=env)


def agentctl(project: Path, *args: str) -> subprocess.CompletedProcess:
    """Run the project's own `scripts/agentctl.py`.

    Args:
        project: Project root directory.
        *args: Sub-command and options.

    Returns:
        The completed process.
    """
    return run([sys.executable, "scripts/agentctl.py", *args], project)


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
            print(f"⚠️ 找不到資料夾：{base}", file=sys.stderr)
            continue
        for current, dirs, _files in os.walk(base):
            here = Path(current)
            level = len(here.relative_to(base).parts)
            dirs[:] = [] if level >= depth else [d for d in dirs if d not in SKIP_DIRS]
            if here != TEMPLATE_ROOT and (here / ".agents" / "framework.lock").is_file() and (here / "scripts" / "agentctl.py").is_file():
                found.add(here)
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
    """Ask the project's own updater what it would change (`--dry-run`).

    Args:
        project: Project root directory.

    Returns:
        The parsed plan (status says why when the preview failed).
    """
    plan = ProjectPlan(project)
    res = agentctl(project, "update", "--from", str(TEMPLATE_ROOT), "--dry-run")
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
    res = agentctl(project, "update", "--from", str(TEMPLATE_ROOT))
    if res.returncode != 0:
        return "❌ update 失敗（看專案內 `agentctl update` 的輸出）"
    agentctl(project, "doctor", "--fix")  # v3.0 -> v3.1 moved hooks to .agents/hooks
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


def confirm(count: int) -> bool:
    """Ask the user once before changing projects.

    Args:
        count: Number of projects that will be updated.

    Returns:
        True when the user typed `y`.
    """
    try:
        return input(f"\n要更新以上 {count} 個專案嗎？(y/N) ").strip().lower() == "y"
    except EOFError:
        return False


def main(argv: list[str] | None = None) -> int:
    """Preview (default) or apply the framework update for every project.

    Args:
        argv: Command-line arguments; defaults to `sys.argv[1:]`.

    Returns:
        0 on success, 1 when the template has uncommitted changes or an update failed.
    """
    parser = argparse.ArgumentParser(description="一次更新所有專案的框架（預設只預覽）")
    parser.add_argument("roots", nargs="*", default=[str(DEFAULT_ROOT)], help=f"放專案的資料夾（預設：母版所在的資料夾 {DEFAULT_ROOT}）")
    parser.add_argument("--depth", type=int, default=3, help="專案最多在幾層子資料夾內（預設 3）")
    parser.add_argument("--apply", action="store_true", help="真的更新（預設只預覽）")
    parser.add_argument("--yes", action="store_true", help="不再詢問確認（搭配 --apply）")
    parser.add_argument("--no-commit", action="store_true", help="更新後不自動 commit")
    args = parser.parse_args(argv)
    if is_dirty(TEMPLATE_ROOT):
        print("❌ 母版有未 commit 的修改：先 commit 母版，專案才能記錄拿到的是哪個版本。", file=sys.stderr)
        return 1
    projects = find_projects([Path(r) for r in args.roots], args.depth)
    plans = [preview(p) for p in projects]
    ready = classify(plans)
    print(f"# 框架更新{'' if args.apply else '預覽'}（{len(projects)} 個專案，{len(ready)} 個可更新）\n")
    print(render_table(plans))
    for p in plans:
        for rel in p.files["removed"]:
            print(f"🗑️ `{p.path.name}`：{rel} 已不在母版（不會自動刪除，確認後自行刪除）")
    if not args.apply or not ready:
        if ready:
            print("\n👉 確認後執行：python3 tools/update_all.py --apply")
        return 0
    if not args.yes and not confirm(len(ready)):
        print("已取消，沒有修改任何專案。")
        return 0
    for p in ready:
        p.status = apply(p, commit=not args.no_commit)
        print(f"{p.path.name}: {p.status}")
    print("\n" + render_table(plans))
    return 1 if any(p.status.startswith("❌") for p in ready) else 0


if __name__ == "__main__":
    raise SystemExit(main())
