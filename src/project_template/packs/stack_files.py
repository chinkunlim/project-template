#!/usr/bin/env python3
"""Render per-project configuration files derived from `packs/stack_config.py`.

Purpose:
    Generates `.agents/project.toml`, `.gitignore`, `.env.example`, and `.github/workflows/ci.yml`
    while keeping `packs/stack_config.py` concise and well within size thresholds.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# `.agents/project.toml` of a new project, filled by `build_project_toml()` (values are TOML-quoted).
PROJECT_TOML_TEMPLATE = '''# ============================================================================
# .agents/project.toml — per-project settings read by every framework script
# ============================================================================

[project]
name = {name}
description = {description}
stack = {stack}
addons = {addons}
languages = {languages}
# Monorepo: list workspace folders, e.g. ["apps/api", "packages/core"]
workspaces = ["."]

[architecture]
# Folders scanned by build_graph.py and review_guard.py
source_roots = {source_roots}
# Top-down: a layer may import layers BELOW it only
layers = {layers}
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
# exclude_paths = ["vendor", "*.min.js", "*.min.mjs", "*.min.css"]
print_allowed_layers = ["entrypoints"]  # other layers must log with `logging.getLogger(__name__)`, not print
# Every source file in a layer that defines functions must create a module logger (CRITICAL)
require_logger = true
logger_exempt_layers = []      # e.g. ["domain"] for pure functions that never log

[commands]
# Python always runs through uv (project .venv, uv-managed Python) — never a global pip
test = {test}
lint = {lint}
# Static type check (mypy strict for Python); leave empty to disable
typecheck = {typecheck}
# Database migrations up to date and matching the ORM models (Alembic)
dbcheck = {dbcheck}
# Output-quality evaluation (`agentctl check --evals`)
evals = {evals}

[skills]
# Installed skills; `agentctl update` keeps exactly these up to date
enabled = {skills}

[agents]
require_agent_attribution = true

[git]
# Commits add one line under CHANGELOG `## [Unreleased]` (no version bump);
# `agentctl finish --tag` turns Unreleased into a version, bumps and tags.
push_reminder_threshold = 5

[release]
version_files = {version_files}

[tree]
# Depth of the summary tree embedded in AGENTS.md (full tree: docs/architecture/PROJECT_TREE.md)
agents_md_depth = 2

[tree.annotations]
# "src/custom" = "Custom domain module"

[project_rules]
# Paired calls that must appear together, e.g. [["acquire_lock", "release_lock"]]
paired_calls = []
# Modules this project must not import ("module:reason"); checked by code-review-guard
forbidden_imports = {forbidden_imports}
'''

GITIGNORE_COMMON = [
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
    "docs/architecture/GRAPH_REPORT.md", "docs/architecture/AGENT_AUDIT_REPORT.md", "graphify-out/",
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

GITIGNORE_NODE = [
    "", "# === Node.js (project-local node_modules; commit pnpm-lock.yaml and .nvmrc) ===",
    "node_modules/", "npm-debug.log*", "coverage/",
]
GITIGNORE_MOBILE = [
    "", "# === Mobile (Expo) — generated native folders, caches and signing files ===",
    "mobile/.expo/", "mobile/dist/", "mobile/web-build/", "mobile/expo-env.d.ts", "mobile/ios/", "mobile/android/",
    "*.tsbuildinfo", ".metro-health-check*",
    "*.jks", "*.keystore", "*.p8", "*.p12", "*.mobileprovision",
]

ENV_COMMON = [
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
]

CI_HEADER = [
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


def _toml_list(items: list[str]) -> str:
    """Render a list of strings as an inline TOML array with safe quoting.

    Args:
        items: Strings to render.

    Returns:
        Text such as `["a", "b"]`.
    """
    return "[" + ", ".join(json.dumps(i, ensure_ascii=False) for i in items) + "]"


def _toml_str(value: str) -> str:
    """Quote a TOML basic string (TOML shares JSON's escaping).

    Args:
        value: Text to quote.

    Returns:
        The quoted text, e.g. `"a \\"b\\""`.
    """
    return json.dumps(value, ensure_ascii=False)


def build_project_toml(
    project_name: str,
    settings: dict[str, Any],
    description: str,
    skills: list[str] | None = None,
) -> str:
    """Render `.agents/project.toml`.

    Args:
        project_name: Project name.
        settings: Output of `project_settings()` (optionally enriched with `web_port` / `web_command`).
        description: One-line description (quotes are escaped).
        skills: Installed skill names recorded in `[skills] enabled`.

    Returns:
        TOML text.
    """
    q = _toml_str
    lists = ("addons", "languages", "source_roots", "layers", "version_files", "forbidden_imports")
    commands = ("test", "lint", "typecheck", "dbcheck", "evals")
    rendered = PROJECT_TOML_TEMPLATE.format(
        name=q(project_name), description=q(description), stack=q(settings["base"]), skills=_toml_list(skills or []),
        **{key: _toml_list(settings[key]) for key in lists}, **{key: q(settings[key]) for key in commands},
    )
    if settings.get("web_port") and settings.get("web_command"):
        rendered += f"\n[web]\nport = {int(settings['web_port'])}\ncommand = {_toml_list(settings['web_command'])}\n"
    return rendered


def build_gitignore(languages: list[str]) -> str:
    """Render `.gitignore` for the project's languages.

    Args:
        languages: Output of `resolve_languages()`.

    Returns:
        `.gitignore` text.
    """
    lines = list(GITIGNORE_COMMON)
    if any(lang in languages for lang in ("node", "gas", "mobile")):
        lines += GITIGNORE_NODE
    if "mobile" in languages:
        lines += GITIGNORE_MOBILE
    if "go" in languages:
        lines += ["", "# === Go ===", "bin/", "*.exe", "*.test", "*.out"]
    if "rust" in languages:
        lines += ["", "# === Rust ===", "target/"]
    return "\n".join(lines) + "\n"


def build_env_example(
    project_name: str,
    languages: list[str],
    data_dir: str = "",
    http_port: int = 8000,
) -> str:
    """Render `.env.example` (copy to `.env` and fill in real values).

    Args:
        project_name: Project name for the header comment.
        languages: Output of `resolve_languages()`.
        data_dir: `DATA_DIR` value (relative to the project); empty for the default.
        http_port: Default `HTTP_PORT` written when `api` is active.

    Returns:
        `.env.example` text.
    """
    from project_template.packs.stack_config import default_data_dir

    lines = [f"# Environment variables for {project_name}", *ENV_COMMON, f"DATA_DIR={data_dir or default_data_dir(project_name)}"]
    if "python" in languages:
        lines += ["", "# Local services: always 127.0.0.1 (not localhost / 0.0.0.0)", "OLLAMA_BASE_URL=http://127.0.0.1:11434", "OLLAMA_MODEL=qwen2.5"]
    if "ollama" in languages:
        lines += ["OLLAMA_TIMEOUT_SECONDS=120"]
    if "api" in languages:
        lines += [
            "", "# HTTP server (FastAPI) — keep 127.0.0.1", "HTTP_HOST=127.0.0.1", f"HTTP_PORT={http_port}",
            "# Other AI tools: Open WebUI in Docker reaches this app as host.docker.internal (comma-separated)",
            "HTTP_ALLOWED_HOSTS=",
            "# Browser pages allowed to call the API / MCP (Open WebUI tool servers run in the browser)",
            "HTTP_ALLOWED_ORIGINS=http://127.0.0.1:8080",
        ]
    if "db" in languages:
        lines += ["", "# Database: empty = SQLite at <DATA_DIR>/db/app.db; PostgreSQL: postgresql+psycopg://user@127.0.0.1:5432/dbname", "DATABASE_URL="]
    if "gas" in languages:
        lines += ["", "# Google Apps Script / webhook", "WEBHOOK_SECRET=", "GAS_WEB_APP_URL="]
    if "mobile" in languages:
        lines += ["", "# Mobile app settings live in mobile/.env (EXPO_PUBLIC_* are bundled into the app: no secrets)"]
    return "\n".join(lines) + "\n"


def _ci_setup_steps(settings: dict[str, Any]) -> list[str]:
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
            "        with:", f"          package_json_file: {folders[0]}/package.json",
            "      - uses: actions/setup-node@v4", "        with:", "          node-version-file: .nvmrc",
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


def build_ci_workflow(settings: dict[str, Any]) -> str:
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
    logger.debug("rendered CI workflow for base=%s", settings["base"])
    return "\n".join(CI_HEADER + steps) + "\n"
