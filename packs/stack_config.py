#!/usr/bin/env python3
"""Stack and add-on resolution plus the per-project config files derived from it.

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

import json
import os
from pathlib import Path
import re

from packs.common import slugify_package_name
from packs.db_pack import DB_CHECK
from packs.evals_pack import EVALS_COMMAND
from packs.mobile_pack import MOBILE_TEST, MOBILE_TYPECHECK

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


# Default data folder, RELATIVE to the project folder: projects/<name> sits next to
# projects-data/<name>, so moving the whole folder (projects + projects-data) needs no edit.
DATA_DIR_TEMPLATE = "../../projects-data/{slug}"


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


def project_settings(project_name: str, stack: str, addons: list[str] | None = None) -> dict:
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


def _toml_list(items: list[str]) -> str:
    """Render a list of strings as an inline TOML array with safe quoting.

    Args:
        items: Strings to render.

    Returns:
        Text such as `["a", "b"]`.
    """
    return "[" + ", ".join(json.dumps(i, ensure_ascii=False) for i in items) + "]"


def build_project_toml(project_name: str, settings: dict, description: str, skills: list[str] | None = None) -> str:
    """Render `.agents/project.toml`.

    Args:
        project_name: Project name.
        settings: Output of `project_settings()`.
        description: One-line description (quotes are escaped).
        skills: Installed skill names recorded in `[skills] enabled`.

    Returns:
        TOML text.
    """
    q = lambda s: json.dumps(s, ensure_ascii=False)  # noqa: E731 - TOML basic strings share JSON escaping
    return f'''# ============================================================================
# .agents/project.toml — per-project settings read by every framework script
# ============================================================================

[project]
name = {q(project_name)}
description = {q(description)}
stack = {q(settings["base"])}
addons = {_toml_list(settings["addons"])}
languages = {_toml_list(settings["languages"])}
# Monorepo: list workspace folders, e.g. ["apps/api", "packages/core"]
workspaces = ["."]

[architecture]
# Folders scanned by build_graph.py and review_guard.py
source_roots = {_toml_list(settings["source_roots"])}
# Top-down: a layer may import layers BELOW it only
layers = {_toml_list(settings["layers"])}
# Only these layers may read environment variables (os.environ / process.env / os.Getenv)
env_access_layers = ["config"]

[quality]
max_function_lines = 40        # soft limit -> warning
hard_max_function_lines = 80   # hard limit -> CRITICAL
max_params = 4
max_nesting = 3
block_on_critical = true
# File header + function description + every parameter documented (Args: / @param)
require_docstrings = true
max_file_lines = 500           # soft limit per file -> warning
hard_max_file_lines = 800      # hard limit per file -> CRITICAL (split into sub-modules)
max_commit_file_mb = 10        # pre-commit blocks larger files; data belongs in DATA_DIR
block_data_files = true        # block PDF/EPUB/archives/media/DB files; set false for document projects
print_allowed_layers = ["entrypoints"]  # other layers must log with `logging.getLogger(__name__)`, not print

[commands]
# Python always runs through uv (project .venv, uv-managed Python) — never a global pip
test = {q(settings["test"])}
lint = {q(settings["lint"])}
# Static type check (mypy strict for Python); leave empty to disable
typecheck = {q(settings["typecheck"])}
# Database migrations up to date and matching the ORM models (Alembic)
dbcheck = {q(settings["dbcheck"])}
# Output-quality evaluation (`agentctl check --evals`)
evals = {q(settings["evals"])}

[skills]
# Installed skills; `agentctl update` keeps exactly these up to date
enabled = {_toml_list(skills or [])}

[agents]
require_agent_attribution = true

[git]
# Commits add one line under CHANGELOG `## [Unreleased]` (no version bump);
# `agentctl finish --tag` turns Unreleased into a version, bumps and tags.
push_reminder_threshold = 5

[release]
version_files = {_toml_list(settings["version_files"])}

[tree]
# Depth of the summary tree embedded in AGENTS.md (full tree: docs/architecture/PROJECT_TREE.md)
agents_md_depth = 2

[tree.annotations]
# "src/custom" = "Custom domain module"

[project_rules]
# Paired calls that must appear together, e.g. [["acquire_lock", "release_lock"]]
paired_calls = []
# Modules this project must not import ("module:reason"); checked by code-review-guard
forbidden_imports = {_toml_list(settings["forbidden_imports"])}
'''


def build_gitignore(languages: list[str]) -> str:
    """Render `.gitignore` for the project's languages.

    Args:
        languages: Output of `resolve_languages()`.

    Returns:
        `.gitignore` text.
    """
    lines = [
        "# === Secrets & Environment (NEVER COMMIT) ===",
        ".env", ".env.*", "!.env.example",
        "# clasp login token; `.clasp.json` only holds the script ID and may be committed",
        ".clasprc.json",
        "*.pem", "*.key", "credentials.json", "service-account*.json",
        "",
        "# === Per-machine generated files (rebuilt by `agentctl doctor --fix` / `agentctl sync`) ===",
        ".claude/skills", ".agents/cache/", ".skills-cache/",
        "",
        "# === On-demand reports (`agentctl graph` / `agentctl audit`); git history is the real record ===",
        "docs/architecture/GRAPH_REPORT.md", "docs/architecture/AGENT_AUDIT_REPORT.md",
        "",
        "# === Local conversation records (transcript + summary; delete when the project ends) ===",
        ".agents/conversations/",
        "",
        "# === OS & Editor Files ===",
        ".DS_Store", "Thumbs.db", ".idea/", "*.swp", "*.swo",
        "# Shared VS Code settings are committed; personal ones are not",
        ".vscode/*", "!.vscode/settings.json", "!.vscode/launch.json", "!.vscode/extensions.json", "!.vscode/mcp.json",
        "",
        "# === Python (project-local .venv managed by uv; commit uv.lock and .python-version) ===",
        "__pycache__/", "*.py[cod]", ".venv/", ".pytest_cache/", ".ruff_cache/", ".mypy_cache/",
        "dist/", "build/", "*.egg-info/",
        "",
        "# === Data never lives in the project: use DATA_DIR (see .env.example) ===",
        "/data/", "/input/", "/output/", "*.db", "*.sqlite", "*.sqlite3", "*.db-journal",
    ]
    if any(lang in languages for lang in ("node", "gas", "mobile")):
        lines += ["", "# === Node.js (project-local node_modules; commit pnpm-lock.yaml and .nvmrc) ===", "node_modules/", "npm-debug.log*", "coverage/"]
    if "mobile" in languages:
        lines += [
            "", "# === Mobile (Expo) — generated native folders, caches and signing files ===",
            "mobile/.expo/", "mobile/dist/", "mobile/web-build/", "mobile/expo-env.d.ts", "mobile/ios/", "mobile/android/",
            "*.tsbuildinfo", ".metro-health-check*",
            "*.jks", "*.keystore", "*.p8", "*.p12", "*.mobileprovision",
        ]
    if "go" in languages:
        lines += ["", "# === Go ===", "bin/", "*.exe", "*.test", "*.out"]
    if "rust" in languages:
        lines += ["", "# === Rust ===", "target/"]
    return "\n".join(lines) + "\n"


def build_env_example(project_name: str, languages: list[str], data_dir: str = "") -> str:
    """Render `.env.example` (copy to `.env` and fill in real values).

    Args:
        project_name: Project name for the header comment.
        languages: Output of `resolve_languages()`.
        data_dir: `DATA_DIR` value (relative to the project); empty for the default.

    Returns:
        `.env.example` text.
    """
    lines = [
        f"# Environment variables for {project_name}",
        "# Copy to `.env` and fill in real values. `.env` is never committed.",
        "",
        "APP_ENV=development",
        "LOG_LEVEL=INFO",
        "LOG_TO_FILE=true",
        "API_TIMEOUT_SECONDS=15",
        "",
        "# Data folder OUTSIDE the project (input/ output/ needs_review/ state/ db/ logs/).",
        "# A relative path is read from THIS project folder (not from where you run a command):",
        "# projects/<name> -> projects-data/<name>, so moving both folders together needs no change.",
        "# An absolute path also works, e.g. an external drive: /Volumes/<drive>/projects-data/<name>",
        f"DATA_DIR={data_dir or default_data_dir(project_name)}",
    ]
    if "python" in languages:
        lines += ["", "# Local services: always 127.0.0.1 (not localhost / 0.0.0.0)", "OLLAMA_BASE_URL=http://127.0.0.1:11434", "OLLAMA_MODEL=qwen2.5"]
    if "ollama" in languages:
        lines += ["OLLAMA_TIMEOUT_SECONDS=120"]
    if "api" in languages:
        lines += ["", "# HTTP server (FastAPI) — keep 127.0.0.1", "HTTP_HOST=127.0.0.1", "HTTP_PORT=8000",
                  "# Other AI tools: Open WebUI in Docker reaches this app as host.docker.internal (comma-separated)",
                  "HTTP_ALLOWED_HOSTS=",
                  "# Browser pages allowed to call the API / MCP (Open WebUI tool servers run in the browser)",
                  "HTTP_ALLOWED_ORIGINS=http://127.0.0.1:8080"]
    if "db" in languages:
        lines += ["", "# Database: empty = SQLite at <DATA_DIR>/db/app.db; PostgreSQL: postgresql+psycopg://user@127.0.0.1:5432/dbname", "DATABASE_URL="]
    if "gas" in languages:
        lines += ["", "# Google Apps Script / webhook", "WEBHOOK_SECRET=", "GAS_WEB_APP_URL="]
    if "mobile" in languages:
        lines += ["", "# Mobile app settings live in mobile/.env (EXPO_PUBLIC_* are bundled into the app: no secrets)"]
    return "\n".join(lines) + "\n"


def _ci_setup_steps(settings: dict) -> list[str]:
    """Render checkout, toolchain and dependency-install steps of the CI workflow.

    Args:
        settings: Output of `project_settings()`.

    Returns:
        YAML lines (indented for the `steps:` list).
    """
    langs = settings["languages"]
    steps = ["      - uses: actions/checkout@v4", "        with:", "          fetch-depth: 0  # full history for the agent audit"]
    if "python" in langs:
        steps += [
            "      - uses: astral-sh/setup-uv@v5  # uv installs the Python from .python-version",
            "        with:",
            "          enable-cache: true",
            "      - name: Install Python dependencies (.venv)",
            "        run: if [ -f uv.lock ]; then uv sync --locked; else uv sync; fi",
        ]
    folders = (["."] if settings["base"] in ("node", "gas") else []) + [a for a in ("gas", "mobile") if a in settings["addons"]]
    if folders:
        steps += [
            "      - uses: pnpm/action-setup@v4  # pnpm version from package.json `packageManager`",
            "        with:",
            f"          package_json_file: {folders[0]}/package.json",
            "      - uses: actions/setup-node@v4",
            "        with:",
            "          node-version-file: .nvmrc",
        ]
        for folder in folders:
            steps += [
                f"      - name: Install Node dependencies ({folder}/node_modules)",
                f"        working-directory: {folder}",
                "        run: if [ -f pnpm-lock.yaml ]; then pnpm install --frozen-lockfile; else pnpm install; fi",
            ]
    if settings["base"] == "go":
        steps += ["      - uses: actions/setup-go@v5", "        with:", '          go-version: "1.21"']
    if settings["base"] == "rust":
        steps += ["      - uses: dtolnay/rust-toolchain@stable"]
    return steps


def build_ci_workflow(settings: dict) -> str:
    """Render `.github/workflows/ci.yml`.

    Runs `agentctl check` (comments, layers, secrets, tree, dependencies, lint), the test
    command, and a non-blocking agent-attribution audit (human commits only warn).

    Args:
        settings: Output of `project_settings()`.

    Returns:
        YAML text.
    """
    py = "uv run python" if "python" in settings["languages"] else "python3"
    steps = _ci_setup_steps(settings)
    steps += [
        "      - name: Directory tree is committed and up to date",
        f"        run: {py} scripts/agentctl.py tree --check",
        "      - name: Framework checks (comments, layers, secrets, deps, lint, types)",
        f"        run: {py} scripts/agentctl.py check",
    ]
    if settings["test"]:
        steps += ["      - name: Tests", f"        run: {settings['test']}"]
    steps += [
        "      - name: Agent attribution audit (warning only)",
        "        continue-on-error: true",
        f"        run: {py} scripts/agentctl.py audit --verify",
    ]
    header = [
        "# =============================================================================",
        "# CI — generated by init_project.py",
        "# Runs on every push and pull request: framework checks + lint, tests, agent audit.",
        "# Same as `python3 scripts/agentctl.py check` + `[commands] test` locally.",
        "# =============================================================================",
        "name: CI",
        "",
        "on:",
        "  push:",
        "  pull_request:",
        "",
        "jobs:",
        "  check:",
        "    runs-on: ubuntu-latest",
        "    steps:",
    ]
    return "\n".join(header + steps) + "\n"
