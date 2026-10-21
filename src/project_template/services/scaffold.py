"""New-project bootstrapper: one command creates the standard structure for any project.

Purpose:
    Every new project starts with the same folders, documents, agent rules and tools,
    so you (and every AI agent) always know where things are:
      - `AGENTS.md` + `.agents/project.toml`  : rules and per-project settings (single source of truth)
      - Agent entry files                     : CLAUDE.md, GEMINI.md, Cursor/Windsurf/Copilot rules
      - `.agents/handoff/` + `.agents/tasks/`  : handoff board and task cards between agents
      - `docs/` skeleton                      : sessions, adr, known-issues, specs, architecture, standards
      - `.agents/bin/` + `.agents/hooks/`     : framework scripts (commit, closeout, doctor, ...) and git hooks
      - `scripts/agentctl.py`                 : the single entry point (the rest of `scripts/` is the project's)
      - `.agents/skills/`                     : core + stack-specific skills (optional ones on request)
      - `.github/workflows/ci.yml`            : CI running the same checks and tests on every push / PR
      - Language starter code                 : python / node / gas / go / rust / generic / mobile (Expo)
      - git repo with a version-controlled pre-commit hook (`core.hooksPath .agents/hooks`)

Usage:
    `scripts/init_project.py` (command line, see `entrypoints/init_cli.py`), the web page and
    the MCP server call `scaffold_project()`.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from project_template.config.framework import (
    FRAMEWORK_VERSION,
    framework_file_map,
    install_files,
    load_catalog,
    select_skills,
    write_lock,
)
from project_template.config.settings import TEMPLATE_ROOT, env_flag, env_value
from project_template.packs.docs_templates import docs_skeleton
from project_template.packs.language_packs import generate_stack_files
from project_template.packs.project_docs import (
    build_agents_md,
    build_changelog_md,
    build_handoff_md,
    build_readme_md,
)
from project_template.packs.stack_config import (
    ADDON_CHOICES,
    STACK_CHOICES,
    build_ci_workflow,
    build_env_example,
    build_gitignore,
    build_project_toml,
    data_dir_setting,
    project_settings,
)

__all__ = ["ADDON_CHOICES", "DEFAULT_DESCRIPTION", "STACK_CHOICES", "scaffold_project", "skill_catalog"]

logger = logging.getLogger(__name__)

DEFAULT_DESCRIPTION = "AI-assisted software project with standard structure and agent handoff."


def _write_file(path: Path, content: str) -> None:
    """Write a UTF-8 text file, creating parent folders.

    Args:
        path: Destination file.
        content: Text to write.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def ensure_target_is_safe(target_dir: Path, force: bool) -> bool:
    """Refuse to scaffold into a non-empty directory unless `force` is set.

    Args:
        target_dir: Directory that will receive the project.
        force: Allow writing into a non-empty directory (existing files may be overwritten).

    Returns:
        True when the directory already contained files (so no automatic initial commit).

    Raises:
        FileExistsError: When the directory is not empty and `force` is False.
    """
    existing = [p for p in target_dir.iterdir() if p.name not in (".DS_Store",)] if target_dir.exists() else []
    if existing and not force:
        names = ", ".join(p.name for p in existing[:5])
        raise FileExistsError(f"Target directory is not empty ({names}...). Use --force to write into it anyway.")
    return bool(existing)


def write_project_documents(target_dir: Path, project_name: str, settings: dict[str, Any], extras: dict[str, Any]) -> None:
    """Write configuration, rule documents, CI, the handoff board and the docs skeleton.

    Args:
        target_dir: Project root directory.
        project_name: Project name.
        settings: Output of `project_settings()`.
        extras: Dict with `description`, `skills` (installed skill names) and optional `data_dir`.
    """
    langs = settings["languages"]
    files = {
        ".agents/project.toml": build_project_toml(project_name, settings, extras["description"], extras["skills"]),
        ".agents/handoff/LATEST.md": build_handoff_md(FRAMEWORK_VERSION),
        "AGENTS.md": build_agents_md(project_name, extras["description"], langs),
        "README.md": build_readme_md(project_name, extras["description"], settings),
        "CHANGELOG.md": build_changelog_md(project_name, FRAMEWORK_VERSION),
        ".gitignore": build_gitignore(langs),
        ".env.example": build_env_example(project_name, langs, extras.get("data_dir", "")),
        ".github/workflows/ci.yml": build_ci_workflow(settings),
        **docs_skeleton(),
    }
    for rel, content in files.items():
        _write_file(target_dir / rel, content)


def detect_timezone() -> str:
    """Return this computer's IANA time zone (used for GAS `appsscript.json`).

    Returns:
        A name such as `Asia/Taipei`; `UTC` when it cannot be determined.
    """
    env_tz = env_value("TZ")
    if "/" in env_tz:
        return env_tz
    try:
        target = os.path.realpath("/etc/localtime")
    except OSError:
        return "UTC"
    return target.split("zoneinfo/", 1)[1] if "zoneinfo/" in target else "UTC"


def lock_python_dependencies(target_dir: Path) -> None:
    """Create `uv.lock` so every computer installs exactly the same versions.

    Skipped (with a hint) when uv is missing or offline; set `TEMPLATE_SKIP_UV_LOCK=1`
    to skip on purpose (used by the template's own tests).

    Args:
        target_dir: Project root directory.
    """
    if not (target_dir / "pyproject.toml").exists() or env_flag("TEMPLATE_SKIP_UV_LOCK"):
        return
    uv = shutil.which("uv")
    if not uv:
        logger.warning("⚠️ 找不到 uv：請安裝 uv（https://docs.astral.sh/uv/）後執行 `uv lock`。")
        return
    res = subprocess.run([uv, "lock"], cwd=target_dir, capture_output=True, text=True, check=False)
    if res.returncode != 0:
        logger.warning(f"⚠️ `uv lock` 未完成（可能離線），之後在專案內執行 `uv lock`：{res.stderr.strip()[:200]}")


def run_generators(target_dir: Path) -> None:
    """Run the initial generators: agent entry files and the directory tree.

    Args:
        target_dir: Project root directory.

    Raises:
        subprocess.CalledProcessError: When a generator fails.
    """
    for script in ("sync_agent_adapters.py", "update_tree.py"):
        subprocess.run([sys.executable, str(target_dir / ".agents" / "bin" / script)], cwd=target_dir, check=True, capture_output=True)


def init_git(target_dir: Path, initial_commit: bool) -> None:
    """Create the git repository, activate the versioned hooks, and make the first commit.

    Args:
        target_dir: Project root directory.
        initial_commit: Create the `chore(init)` commit (skipped for pre-existing folders).
    """
    if not (target_dir / ".git").exists():
        subprocess.run(["git", "init", "-b", "main"], cwd=target_dir, check=False, capture_output=True)
    subprocess.run(["git", "config", "core.hooksPath", ".agents/hooks"], cwd=target_dir, check=False, capture_output=True)
    if not initial_commit:
        return
    subprocess.run(["git", "add", "-A"], cwd=target_dir, check=False, capture_output=True)
    message = (
        f"chore(init): scaffold project v0.1.0 (framework v{FRAMEWORK_VERSION}) [agent:init_project]\n\n"
        "Agent: init_project\nVersion: v0.1.0\nCo-Authored-By: init_project <agent+init_project@local>"
    )
    res = subprocess.run(["git", "commit", "-m", message], cwd=target_dir, check=False, capture_output=True, text=True)
    if res.returncode != 0:
        logger.warning(f"⚠️ 初始 commit 未完成（請檢查 git user.name / user.email）：{res.stderr.strip()[:200]}")


def scaffold_project(
    target_dir: Path,
    project_name: str,
    *,
    stack: str = "python",
    addons: list[str] | None = None,
    description: str = DEFAULT_DESCRIPTION,
    extra_skills: list[str] | None = None,
    timezone: str | None = None,
    license_kind: str = "none",
    init_git_repo: bool = True,
    force: bool = False,
    data_dir: Path | None = None,
) -> list[str]:
    """Create a complete project in `target_dir`.

    Args:
        target_dir: Destination folder (created when missing; must be empty unless `force`).
        project_name: Project name used in documents and package names.
        stack: One of `STACK_CHOICES` (`both` / `all` are aliases for python + add-ons).
        addons: Add-ons from `ADDON_CHOICES` (`web`, `gas`).
        description: One-line project description.
        extra_skills: Optional skills to add on top of core and stack skills.
        timezone: IANA time zone for GAS; detected from this computer when omitted.
        license_kind: `MIT` writes a LICENSE file; `none` (default) grants no license.
        init_git_repo: Initialise git, set `core.hooksPath` and make the first commit.
        force: Allow scaffolding into a non-empty folder (no automatic commit then).
        data_dir: Data folder to use; None = `../../projects-data/<name>`. On the same drive it is
            stored relative to the project; on another drive it goes only into the untracked `.env`.

    Returns:
        Installed skill names.

    Raises:
        FileExistsError: When `target_dir` is not empty and `force` is False.
        ValueError: When an unknown skill is requested.
    """
    target_dir = target_dir.resolve()
    pre_existing = ensure_target_is_safe(target_dir, force)
    settings = project_settings(project_name, stack, addons)
    skills = select_skills(load_catalog(TEMPLATE_ROOT), settings["languages"], extra_skills or [])
    target_dir.mkdir(parents=True, exist_ok=True)

    data_value, shareable = data_dir_setting(target_dir, project_name, data_dir)
    extras = {"description": description, "skills": skills, "data_dir": data_value if shareable else ""}
    write_project_documents(target_dir, project_name, settings, extras)
    if not shareable:  # an absolute path (other drive) is personal: only in the untracked .env
        example = (target_dir / ".env.example").read_text(encoding="utf-8")
        _write_file(target_dir / ".env", re.sub(r"^DATA_DIR=.*$", f"DATA_DIR={data_value}", example, flags=re.M))
    installed = install_files(target_dir, framework_file_map(TEMPLATE_ROOT, skills))
    options = {"description": description, "timezone": timezone or detect_timezone(), "license": license_kind}
    generate_stack_files(target_dir, project_name, settings, options)
    write_lock(target_dir, TEMPLATE_ROOT, FRAMEWORK_VERSION, skills, installed)
    lock_python_dependencies(target_dir)
    run_generators(target_dir)
    if init_git_repo:
        init_git(target_dir, initial_commit=not pre_existing)
    return skills


def skill_catalog() -> list[tuple[str, dict[str, Any]]]:
    """List the template's skills, grouped by tier.

    Returns:
        `(name, metadata)` pairs sorted by tier, then name.
    """
    return sorted(load_catalog(TEMPLATE_ROOT).items(), key=lambda kv: (kv[1].get("tier", ""), kv[0]))
