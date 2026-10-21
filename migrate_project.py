#!/usr/bin/env python3
"""Move an existing project into a new folder built from this template, keeping git history.

Purpose:
    Old projects should end up with the same structure, rules and tools as new ones.
    This tool prepares that move safely; the actual code changes are done afterwards by
    agents, batch by batch, with the `legacy-migration` skill:
      1. Clone the old repository into the new folder (git history is kept; the old
         project itself is never modified).
      2. `git mv` every old file into `legacy/` and commit, so `git log --follow` / blame
         still work after files are moved again.
      3. Apply the template (AGENTS.md, docs/, scripts/, skills, starter layout, hooks).
      4. Write `docs/migration/MIGRATION.md`: file inventory with suggested locations,
         ordered batches, dependency conversion commands, risks and completion criteria.
      5. Create one task card per batch and commit everything.
    An old folder that is not a git repository is copied into `legacy/` instead
    (secrets, virtualenvs and `node_modules` are never copied).

Modes (Flask projects):
    maintain (default) : the old project is finished; Flask stays allowed, only structure and
                         standards are brought up to date.
    develop            : the project will keep growing; every Flask route must be rewritten
                         to FastAPI (`flask` becomes a forbidden import, a conversion batch is
                         added, and `--verify` requires Flask to be gone).
    Switch later with `python3 scripts/agentctl.py migration --develop`.

Usage:
    python3 migrate_project.py --from ~/Desktop/projects/old_app --target ~/Desktop/projects/old_app_v2
    python3 migrate_project.py --from ~/Desktop/projects/old_bot --target ~/Desktop/projects/bot --stack python --with gas
    python3 migrate_project.py --from ~/Desktop/projects/old_api --target ~/Desktop/projects/api_v2 --mode develop
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path, PurePosixPath

TEMPLATE_ROOT = Path(__file__).resolve().parent
for _path in (TEMPLATE_ROOT, TEMPLATE_ROOT / "lib"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from init_project import scaffold_project  # noqa: E402
from packs.common import slugify_package_name, write_file  # noqa: E402
from packs.language_packs import ADDON_CHOICES, STACK_CHOICES  # noqa: E402
from packs.stack_config import default_data_dir  # noqa: E402
from packs.migration_plan import (  # noqa: E402
    BATCH_TITLES,
    PlanContext,
    data_moves,
    is_data_path,
    build_entries,
    dependency_commands,
    env_keys,
    find_risks,
    group_batches,
    render_migration_md,
)

AGENT = "migrate_project"
COPY_IGNORE = shutil.ignore_patterns(
    ".git", ".venv", "venv", "env", "node_modules", "__pycache__", "*.pyc", ".DS_Store", "dist", "build",
    ".env", ".env.*", "*.pem", "*.key", ".clasprc.json", ".pytest_cache", ".mypy_cache", ".ruff_cache",
)
TRAILERS = f"Agent: {AGENT}\nCo-Authored-By: {AGENT} <agent+{AGENT}@local>"


def git(cwd: Path, *args: str, check: bool = True) -> str:
    """Run git in `cwd`.

    Args:
        cwd: Working directory.
        *args: Arguments after `git`.
        check: Raise `RuntimeError` on a non-zero exit code.

    Returns:
        Trimmed standard output.

    Raises:
        RuntimeError: When the command fails and `check` is True.
    """
    res = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)
    if check and res.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {res.stderr.strip()}")
    return res.stdout.strip()


def is_repo_root(folder: Path) -> bool:
    """Tell whether `folder` is the top level of a git repository.

    Args:
        folder: Folder to inspect.

    Returns:
        True when `git rev-parse --show-toplevel` points at `folder`.
    """
    top = git(folder, "rev-parse", "--show-toplevel", check=False)
    return bool(top) and Path(top).resolve() == folder.resolve()


def detect_python_libraries(old: Path) -> set[str]:
    """Read normalised package names from the old project's dependency files.

    Args:
        old: Old project folder.

    Returns:
        Lower-case names with `_` → `-` (e.g. `flask`, `flask-sqlalchemy`, `alembic`).
    """
    text = ""
    for name in ("requirements.txt", "requirements-dev.txt", "pyproject.toml", "Pipfile", "setup.py"):
        path = old / name
        text += path.read_text(encoding="utf-8", errors="replace").lower() + "\n" if path.exists() else ""
    return {m.replace("_", "-") for m in re.findall(r"[a-z0-9][a-z0-9_.-]*", text)}


def detect_stack(old: Path, mode: str = "maintain") -> tuple[str, list[str]]:
    """Guess the base stack and add-ons from the old project's files.

    Args:
        old: Old project folder.
        mode: `maintain` or `develop`; develop-mode Flask projects get the FastAPI add-on.

    Returns:
        Tuple of base stack and add-ons (`web`, `gas`, `api`, `db`).
    """
    def has(pattern: str) -> bool:
        """Check whether any file outside dependency folders matches a glob.

        Args:
            pattern: Glob relative to the old project.

        Returns:
            True when at least one file matches.
        """
        return any("node_modules" not in p.parts and ".venv" not in p.parts for p in old.rglob(pattern))

    python = has("*.py") or (old / "requirements.txt").exists() or (old / "pyproject.toml").exists()
    gas = has("appsscript.json") or has("*.gs")
    web = has("*.html") or has("*.css")
    libs = detect_python_libraries(old)
    uses_db = bool(libs & {"sqlalchemy", "flask-sqlalchemy", "alembic", "flask-migrate"}) or (old / "alembic.ini").exists()
    api = "fastapi" in libs or ("flask" in libs and mode == "develop")
    if python:
        flags = (("web", web and not gas and "flask" not in libs), ("gas", gas), ("api", api), ("db", uses_db))
        return "python", [a for a, on in flags if on]
    if gas:
        return "gas", []
    return ("node", []) if (old / "package.json").exists() else ("generic", ["web"] if web else [])


def clone_with_history(old: Path, target: Path) -> dict[str, str]:
    """Clone the old repository and move its files into `legacy/` (one commit).

    Args:
        old: Old repository root (must have no uncommitted changes).
        target: New project folder (must not exist yet).

    Returns:
        Source info: `path`, `origin`, `commit`, `history`.

    Raises:
        RuntimeError: When the old repository has uncommitted changes or git fails.
    """
    if git(old, "status", "--porcelain"):
        raise RuntimeError("舊專案有未 commit 的修改，請先 commit 或 stash（未 commit 的內容不會被搬過去）。")
    origin = git(old, "remote", "get-url", "origin", check=False)
    git(target.parent, "clone", "--quiet", "--no-hardlinks", str(old), str(target))
    git(target, "remote", "remove", "origin")
    if origin:
        git(target, "remote", "add", "origin", origin)
    commit = git(target, "rev-parse", "--short", "HEAD")
    data_paths = drop_data_files(target)
    (target / "legacy").mkdir()
    for entry in sorted(p.name for p in target.iterdir() if p.name not in (".git", "legacy")):
        git(target, "mv", "-k", entry, f"legacy/{entry}")
    git(target, "commit", "--no-verify", "-q", "-m", f"chore(migrate): move existing project into legacy/, data excluded [agent:{AGENT}]\n\n{TRAILERS}")
    return {"path": str(old), "origin": origin, "commit": commit, "history": "kept", "data_paths": data_paths}


def drop_data_files(target: Path) -> list[str]:
    """Remove tracked data files from the new clone (index and working copy).

    The old project keeps the only copy; `MIGRATION.md` lists how to copy it to DATA_DIR.

    Args:
        target: New project root (fresh clone).

    Returns:
        Old-project paths that were classified as data.
    """
    data_paths = [p for p in git(target, "ls-files").splitlines() if is_data_path(p)]
    for chunk_start in range(0, len(data_paths), 200):
        chunk = data_paths[chunk_start:chunk_start + 200]
        git(target, "rm", "-q", "--cached", "--", *chunk)
        for rel in chunk:
            (target / rel).unlink(missing_ok=True)
    for folder in sorted({PurePosixPath(p).parts[0] for p in data_paths}, reverse=True):
        path = target / folder
        if path.is_dir() and not any(p.is_file() for p in path.rglob("*")):
            shutil.rmtree(path)
    return data_paths


def copy_without_history(old: Path, target: Path) -> dict[str, str]:
    """Copy a non-git project into `legacy/` (secrets and environments are skipped).

    Args:
        old: Old project folder.
        target: New project folder (must not exist yet).

    Returns:
        Source info: `path`, `origin`, `commit`, `history`.
    """
    data_paths = sorted(
        p.relative_to(old).as_posix() for p in old.rglob("*")
        if p.is_file() and is_data_path(p.relative_to(old).as_posix()) and not {".git", ".venv", "node_modules"} & set(p.parts)
    )
    shutil.copytree(old, target / "legacy", ignore=lambda folder, names: skip_on_copy(old, Path(folder), names))
    git(target, "init", "-q", "-b", "main")
    return {"path": str(old), "origin": "", "commit": "", "history": "none", "data_paths": data_paths}


def skip_on_copy(old: Path, folder: Path, names: list[str]) -> set[str]:
    """Decide which entries `copytree` skips: secrets, environments and all data.

    Args:
        old: Old project root.
        folder: Folder being copied.
        names: Entry names inside `folder`.

    Returns:
        Names to skip.
    """
    skipped = set(COPY_IGNORE(str(folder), names))
    return skipped | {n for n in names if is_data_path((folder / n).relative_to(old).as_posix())}


def batch_paths(items: list) -> list[str]:
    """Collect the target folders of a batch for its task card.

    Args:
        items: Entries of one batch.

    Returns:
        Sorted folder paths (falls back to `legacy`).
    """
    folders = {e.target.split("（")[0].split(" ")[0] for e in items}
    return sorted(f for f in folders if "/" in f) or ["legacy"]


def create_batch_tasks(target: Path, batches: list[tuple[str, list]]) -> list[tuple[str, str, list]]:
    """Create one open task card per batch with `agent_task.py`.

    Args:
        target: New project root.
        batches: Output of `group_batches()`.

    Returns:
        `(batch, task_id, entries)` triples.
    """
    result = []
    for idx, (batch, items) in enumerate(batches, start=1):
        targets = batch_paths(items) if items else ["src"]
        title = f"遷移批次 {idx}：{BATCH_TITLES[batch]}"
        out = subprocess.run(
            [sys.executable, ".agents/bin/agent_task.py", "create", title, "--paths", *targets, "legacy"],
            cwd=target, capture_output=True, text=True, check=True,
        ).stdout
        task_id = next((w.strip("`") for w in out.split() if w.strip("`").startswith("TASK-")), "TASK-?")
        result.append((batch, task_id, items))
    return result


def write_plan(target: Path, source: dict[str, str]) -> int:
    """Inventory `legacy/`, create batch tasks and write `MIGRATION.md`.

    Args:
        target: New project root.
        source: Output of `clone_with_history()` / `copy_without_history()` plus `mode` and `uses_flask`.

    Returns:
        Number of legacy files.
    """
    tracked = git(target, "ls-files", "legacy", check=False).splitlines()
    files = tracked or sorted(p.relative_to(target).as_posix() for p in (target / "legacy").rglob("*") if p.is_file())
    ctx = PlanContext(pkg=slugify_package_name(target.name), uses_flask=source["uses_flask"] == "yes", mode=source["mode"])
    entries = build_entries(target, files, ctx)
    grouped = group_batches(entries)
    if ctx.uses_flask and ctx.mode == "develop" and not any(b == "flask" for b, _ in grouped):
        grouped.append(("flask", []))
    batches = create_batch_tasks(target, grouped)
    legacy = target / "legacy"
    data_dir = default_data_dir(target.name)  # relative to the new project folder
    risks = find_risks(target, entries)
    if source.get("data_paths") and source["history"] == "kept":
        risks.append(f"🟡 舊的 git 歷史仍含 {len(source['data_paths'])} 個資料檔（repo 體積大、可能有著作權資料）：若要推送到 GitHub，先評估用 `git filter-repo` 清除歷史中的資料檔。")
    extras = {
        "batches": batches, "deps": dependency_commands(legacy), "env_keys": env_keys(legacy), "risks": risks,
        "data_moves": data_moves(source.get("data_paths", []), source["path"], data_dir),
    }
    write_file(target / "docs" / "migration" / "MIGRATION.md", render_migration_md(source, entries, extras))
    return len(entries)


def set_forbidden_imports(target: Path, entries: list[str]) -> None:
    """Replace `[project_rules] forbidden_imports` in `.agents/project.toml`.

    Args:
        target: New project root.
        entries: New list (e.g. `[]` to allow Flask in maintain mode).
    """
    toml = target / ".agents" / "project.toml"
    value = "[" + ", ".join(f'"{e}"' for e in entries) + "]"
    text = re.sub(r"^forbidden_imports = .*$", lambda _m: f"forbidden_imports = {value}", toml.read_text(encoding="utf-8"), flags=re.M)
    toml.write_text(text, encoding="utf-8")


def commit_all(target: Path, message: str) -> None:
    """Stage everything and commit (the versioned pre-commit hook runs).

    Args:
        target: New project root.
        message: Commit subject.

    Raises:
        RuntimeError: When the commit fails.
    """
    git(target, "add", "-A")
    git(target, "commit", "-q", "-m", f"{message} [agent:{AGENT}]\n\n{TRAILERS}")


def migrate(old: Path, target: Path, options: dict) -> int:
    """Run the whole preparation.

    Args:
        old: Old project folder.
        target: New project folder (must not exist).
        options: `stack`, `addons`, `name`, `skills`, `mode` (`maintain` / `develop`).

    Returns:
        Number of legacy files in the plan.

    Raises:
        FileExistsError: When `target` already exists.
        RuntimeError: When git operations fail.
    """
    if target.exists():
        raise FileExistsError(f"目標資料夾已存在：{target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    mode = options.get("mode") or "maintain"
    detected_stack, detected_addons = detect_stack(old, mode)
    stack = options.get("stack") or detected_stack
    addons = options.get("addons") if options.get("addons") is not None else detected_addons
    if is_repo_root(old):
        source = clone_with_history(old, target)
    else:
        target.mkdir()
        source = copy_without_history(old, target)
    source.update({"mode": mode, "uses_flask": "yes" if "flask" in detect_python_libraries(old) else "no"})
    scaffold_project(
        target, options.get("name") or target.name, stack=stack, addons=addons,
        extra_skills=sorted({"legacy-migration", *options.get("skills", [])}), init_git_repo=True, force=True,
    )
    if mode == "maintain":
        set_forbidden_imports(target, [])
    count = write_plan(target, source)
    subprocess.run([sys.executable, ".agents/bin/update_tree.py"], cwd=target, capture_output=True, check=False)
    commit_all(target, f"chore(migrate): apply project template and migration plan ({count} legacy files)")
    return count


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point.

    Args:
        argv: Arguments to parse; defaults to `sys.argv[1:]`.

    Returns:
        Process exit code.
    """
    parser = argparse.ArgumentParser(description="把舊專案搬進用模板建立的新資料夾（保留 git 歷史，產生遷移計畫）")
    parser.add_argument("--from", dest="old", required=True, help="舊專案資料夾")
    parser.add_argument("--target", required=True, help="新專案資料夾（不可已存在）")
    parser.add_argument("--name", default=None, help="專案名稱（預設為新資料夾名稱）")
    parser.add_argument("--stack", choices=STACK_CHOICES, default=None, help="主要語言（預設自動偵測）")
    parser.add_argument("--with", dest="addons", nargs="*", choices=ADDON_CHOICES, default=None, help="附加：web / gas（預設自動偵測）")
    parser.add_argument("--skills", nargs="*", default=[], help="額外安裝的 optional skills")
    parser.add_argument("--mode", choices=["maintain", "develop"], default="maintain",
                        help="maintain：舊專案已完工，保留 Flask；develop：要繼續開發，Flask 全部改成 FastAPI")
    args = parser.parse_args(argv)
    old = Path(args.old).expanduser().resolve()
    target = Path(args.target).expanduser().resolve()
    if not old.is_dir():
        print(f"❌ 找不到舊專案：{old}", file=sys.stderr)
        return 1
    try:
        options = {"stack": args.stack, "addons": args.addons, "name": args.name, "skills": args.skills, "mode": args.mode}
        count = migrate(old, target, options)
    except (FileExistsError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 1
    print(f"✅ 已建立 {target}（{count} 個舊檔案在 legacy/，舊專案未被修改）")
    print("   下一步：cd 進新資料夾，閱讀 docs/migration/MIGRATION.md，再請 Agent 依 legacy-migration skill 逐批搬移。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
