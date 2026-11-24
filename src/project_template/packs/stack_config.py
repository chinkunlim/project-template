#!/usr/bin/env python3
"""Stack and add-on resolution plus re-exported per-project file builders.

Purpose:
    One place decides, for a base stack and optional add-ons, which folders are source
    roots, which commands test and lint the project, and what goes into
    `.agents/project.toml`, `.gitignore`, `.env.example` and the CI workflow.

Stacks and add-ons:
    Base stacks : python | node | gas | go | rust | generic
    Add-ons     : web (plain HTML/CSS/JS in `web/`) | gas (Apps Script in `gas/`)
                  mobile (Expo: React Native + TypeScript app for Android and iOS in `mobile/`)
                  api (FastAPI, Python only) | db (SQLAlchemy + Alembic + SQLite, Python only)
                  ollama (local LLM client + hardware guard, Python only) | evals (output-quality scoring)
    Aliases     : both = python + web,  all = python + web + gas,  mobile = generic + mobile

Environment isolation:
    Python always runs through uv (`uv run`, `uv sync`) with a uv-managed interpreter and a
    project-local `.venv`; Node tools are dev dependencies in the project's own `node_modules`.
    Nothing is installed globally.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

from project_template.packs.common import slugify_package_name
from project_template.packs.db_pack import DB_CHECK
from project_template.packs.evals_pack import EVALS_COMMAND
from project_template.packs.mobile_pack import MOBILE_TEST, MOBILE_TYPECHECK
from project_template.packs.stack_files import (
    PROJECT_TOML_TEMPLATE,
    _ci_setup_steps,
    _toml_list,
    _toml_str,
    build_ci_workflow,
    build_env_example,
    build_gitignore,
    build_project_toml,
)

__all__ = [
    "ADDON_CHOICES",
    "ALIASES",
    "BASE_SETTINGS",
    "DATA_DIR_TEMPLATE",
    "DEFAULT_LAYERS",
    "FLASK_RULE",
    "PROJECT_TOML_TEMPLATE",
    "PYTHON_ONLY_ADDONS",
    "STACK_CHOICES",
    "UV_LINT",
    "UV_TEST",
    "UV_TYPECHECK",
    "_ci_setup_steps",
    "_device",
    "_toml_list",
    "_toml_str",
    "build_ci_workflow",
    "build_env_example",
    "build_gitignore",
    "build_project_toml",
    "data_dir_setting",
    "data_slug",
    "default_data_dir",
    "project_settings",
    "resolve_languages",
    "resolve_stack",
]

logger = logging.getLogger(__name__)

STACK_CHOICES = ("python", "node", "gas", "go", "rust", "generic", "both", "all", "mobile")
ADDON_CHOICES = ("web", "gas", "mobile", "api", "db", "ollama", "evals")
PYTHON_ONLY_ADDONS = ("api", "db", "ollama")
ALIASES = {"both": ("python", ["web"]), "all": ("python", ["web", "gas"]), "mobile": ("generic", ["mobile"])}
DEFAULT_LAYERS = ["entrypoints", "adapters", "services", "domain", "config"]
UV_TEST = "uv run python -m unittest discover -s tests -v"
UV_LINT = "uv run ruff check . && uv run ruff format --check ."
UV_TYPECHECK = "uv run mypy"
FLASK_RULE = "flask:新專案一律使用 FastAPI（見 docs/standards/ARCHITECTURE_RULES.md）"

# base stack -> (source_roots, layers, test command, lint command, version files)
BASE_SETTINGS: dict[str, tuple[list[str], list[str], str, str, list[str]]] = {
    "python": (["src/{pkg}"], DEFAULT_LAYERS, UV_TEST, UV_LINT, ["pyproject.toml"]),
    "node": (["src"], DEFAULT_LAYERS, "node --test", "", ["package.json"]),
    "gas": (["src"], DEFAULT_LAYERS, "node --test", "node dev/build.js --check", ["package.json"]),
    "go": (["internal", "cmd"], ["cmd", "adapters", "services", "domain", "config"], "go test ./...", "go vet ./...", ["VERSION"]),
    "rust": (["src"], DEFAULT_LAYERS, "cargo test", "cargo check", ["Cargo.toml"]),
    "generic": (["src"], DEFAULT_LAYERS, "", "", ["VERSION"]),
}

# Default data folder, RELATIVE to the project folder: projects/<name> sits next to
# projects-data/<name>, so moving the whole folder (projects + projects-data) needs no edit.
DATA_DIR_TEMPLATE = "../../projects-data/{slug}"


def resolve_stack(stack: str, addons: list[str] | None = None) -> tuple[str, list[str]]:
    """Expand aliases and normalise add-ons.

    Args:
        stack: One of `STACK_CHOICES`.
        addons: Requested add-ons (`web`, `gas`).

    Returns:
        Tuple of base stack and the ordered, de-duplicated add-ons (the GAS add-on is
        dropped when the base stack is already `gas`; `api` / `db` need the python stack).

    Raises:
        ValueError: When `api` or `db` is requested for a non-Python stack.
    """
    base, implied = ALIASES.get(stack, (stack, []))
    merged = [a for a in dict.fromkeys([*implied, *(addons or [])]) if not (a == "gas" and base == "gas")]
    invalid = [a for a in merged if a in PYTHON_ONLY_ADDONS and base != "python"]
    if invalid:
        raise ValueError(f"--with {' '.join(invalid)} 需要 --stack python")
    return base, merged


def resolve_languages(stack: str, addons: list[str] | None = None) -> list[str]:
    """List every language/area a project uses (base stack first, then add-ons).

    Args:
        stack: One of `STACK_CHOICES`.
        addons: Requested add-ons.

    Returns:
        e.g. `["python", "web", "gas"]`.
    """
    base, extra = resolve_stack(stack, addons)
    return [base, *extra]


def default_data_dir(project_name: str) -> str:
    """Default `DATA_DIR` for a project (relative to the project folder).

    Args:
        project_name: Project name.

    Returns:
        Text such as `../../projects-data/my-app`.
    """
    return DATA_DIR_TEMPLATE.format(slug=data_slug(project_name))


def _device(path: Path) -> int:
    """Return the file-system device of a path, or of its nearest existing parent.

    Args:
        path: Any path (may not exist yet).

    Returns:
        The `st_dev` number.
    """
    for candidate in (path, *path.parents):
        if candidate.exists():
            return candidate.stat().st_dev
    return -1


def data_dir_setting(project_dir: Path, project_name: str, chosen: Path | None = None) -> tuple[str, bool]:
    """Decide the `DATA_DIR` value to write for a project.

    Args:
        project_dir: Project root directory (absolute).
        project_name: Project name (for the default folder name).
        chosen: Data folder picked by the user; None for the default.

    Returns:
        Tuple of the value and whether it is safe to commit in `.env.example`. A folder on the
        same drive becomes a path relative to the project (moves with it); a folder on another
        drive (e.g. an external disk) stays absolute and must only go into `.env`.
    """
    if chosen is None:
        return default_data_dir(project_name), True
    chosen = chosen.expanduser().resolve()
    if _device(chosen) == _device(project_dir):
        return Path(os.path.relpath(chosen, project_dir)).as_posix(), True
    return chosen.as_posix(), False


def data_slug(project_name: str) -> str:
    """Folder name used under `projects-data/` for a project.

    Args:
        project_name: Project name.

    Returns:
        Lower-case name with `-` separators.
    """
    return re.sub(r"[^a-z0-9-]+", "-", project_name.lower()).strip("-") or "app"


def _join(*commands: str) -> str:
    """Join non-empty shell commands with `&&`.

    Args:
        *commands: Commands (empty strings are skipped).

    Returns:
        The combined command.
    """
    return " && ".join(c for c in commands if c)


def project_settings(project_name: str, stack: str, addons: list[str] | None = None) -> dict[str, Any]:
    """Compute source roots, layers, commands and version files for a project.

    Args:
        project_name: Project name (used for the Python package path).
        stack: One of `STACK_CHOICES`.
        addons: Requested add-ons.

    Returns:
        Dict with `base`, `addons`, `languages`, `source_roots`, `layers`, `test`, `lint`, `version_files`.
    """
    base, extra = resolve_stack(stack, addons)
    roots, layers, test, lint, versions = BASE_SETTINGS.get(base, BASE_SETTINGS["generic"])
    roots = [r.format(pkg=slugify_package_name(project_name)) for r in roots]
    if "web" in extra:
        roots.append("web")
    if "db" in extra:
        roots.append("alembic")
    if "evals" in extra:
        roots.append("evals")
    if "gas" in extra:
        roots.append("gas/src")
        test = _join(test, "(cd gas && node --test)")
        lint = _join(lint, "node gas/dev/build.js --check")
    typecheck = UV_TYPECHECK if base == "python" else ""
    if "mobile" in extra:
        roots = [r for r in roots if not (base == "generic" and r == "src")] + ["mobile/src"]
        test = _join(test, MOBILE_TEST)
        typecheck = _join(typecheck, MOBILE_TYPECHECK)
    return {
        "base": base, "addons": extra, "languages": [base, *extra], "source_roots": roots, "layers": layers,
        "test": test, "lint": lint, "version_files": versions,
        "typecheck": typecheck,
        "forbidden_imports": [FLASK_RULE] if base == "python" else [],
        "dbcheck": DB_CHECK if "db" in extra else "",
        "evals": (EVALS_COMMAND if base == "python" else "python3 evals/run_evals.py") if "evals" in extra else "",
    }
