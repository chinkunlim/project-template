#!/usr/bin/env python3
"""Python starter: uv-managed Python 3.11, project-local `.venv`, ruff, layered package.

Purpose:
    Creates a Python project that never touches the host's Python installation:
      - `.python-version` pins 3.11; `[tool.uv] python-preference = "only-managed"` makes uv
        use its own downloaded interpreter instead of Homebrew / system Python.
      - Dependencies live in `pyproject.toml` + `uv.lock` and are installed into `.venv/`
        by `uv sync`; commands run with `uv run ...`. No global `pip install`.
      - ruff (lint + format) and mypy (strict type check) are dev dependencies, so they are
        project-local too.
    Package layout: `src/<pkg>/{entrypoints,adapters,services,domain,config}` + `tests/`.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from project_template.packs.api_pack import API_DEPENDENCIES, API_DEV_DEPENDENCIES, scaffold_api_pack
from project_template.packs.common import slugify_package_name
from project_template.packs.common import write_file as _write
from project_template.packs.db_pack import DB_DEPENDENCIES, scaffold_db_pack
from project_template.packs.ollama_pack import scaffold_ollama_pack
from project_template.packs.python_config_templates import (
    EXTRA_SETTINGS,
    PY_LOGGING,
    PY_SETTINGS,
    PYPROJECT_TEMPLATE,
    PYTHON_VERSION,
)

__all__ = [
    "EXTRA_SETTINGS",
    "LAYER_DOCS",
    "PY_CLI",
    "PY_DOMAIN",
    "PY_LOGGING",
    "PY_SERVICE",
    "PY_SETTINGS",
    "PY_TEST",
    "PY_WIRING",
    "PYTHON_VERSION",
    "build_pyproject",
    "build_settings_module",
    "build_wiring_module",
    "scaffold_python_pack",
]

logger = logging.getLogger(__name__)

PY_DOMAIN = '''"""Domain layer: pure data models with no I/O and no framework dependencies."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GreetingRequest:
    """A request to greet one user.

    Attributes:
        user_name: Name typed by the user (may contain surrounding spaces).
    """

    user_name: str


@dataclass(frozen=True)
class GreetingResult:
    """The greeting produced by the service layer.

    Attributes:
        message: Final greeting text.
        environment: Environment the greeting was produced in.
    """

    message: str
    environment: str
'''

PY_SERVICE = '''"""Services layer: business logic that depends only on `config` and `domain`."""

from __future__ import annotations

import logging

from {pkg}.config.settings import AppConfig
from {pkg}.domain.models import GreetingRequest, GreetingResult

logger = logging.getLogger(__name__)


def create_greeting(request: GreetingRequest, config: AppConfig) -> GreetingResult:
    """Build a greeting for the requested user.

    Args:
        request: The user's greeting request; blank names fall back to "World".
        config: Application settings (provides the environment name).

    Returns:
        The greeting message and the environment it was produced in.
    """
    clean_name = request.user_name.strip() or "World"
    logger.info("greeting user=%r env=%s", clean_name, config.app_env)
    return GreetingResult(message=f"Hello, {{clean_name}}!", environment=config.app_env)
'''

PY_CLI = '''"""Command-line entrypoint: `uv run {cmd} --name Alice`.

Wires the layers together: read config, set up logging (run id, files in DATA_DIR/logs),
call the service, print the result. Only entrypoints may `print`; everything else logs.
"""

from __future__ import annotations

import argparse
import logging

from {pkg}.config.logging_setup import setup_logging
from {pkg}.config.settings import load_config
from {pkg}.domain.models import GreetingRequest
from {pkg}.services.greeting import create_greeting

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    """Parse arguments, run the greeting service and print the message.

    Args:
        argv: Command-line arguments; defaults to `sys.argv[1:]`.

    Returns:
        Process exit code (0 on success).
    """
    parser = argparse.ArgumentParser(description="{name} command-line interface")
    parser.add_argument("--name", default="", help="Name of the user to greet")
    args = parser.parse_args(argv)
    config = load_config()
    setup_logging(config.log_level, config.logs_dir if config.log_to_file else None)
    logger.info("cli start args=%s env=%s data_dir=%s", vars(args), config.app_env, config.data_dir)
    result = create_greeting(GreetingRequest(user_name=args.name), config)
    logger.info("cli done env=%s", result.environment)
    print(result.message)  # the CLI's real output (stdout); logs go to stderr / files
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''

PY_TEST = '''"""Unit tests for the starter greeting service and CLI."""

from __future__ import annotations

import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from {pkg}.config.settings import AppConfig  # noqa: E402
from {pkg}.domain.models import GreetingRequest  # noqa: E402
from {pkg}.entrypoints.cli import main  # noqa: E402
from {pkg}.entrypoints.wiring import safe_user_path  # noqa: E402
from {pkg}.services.greeting import create_greeting  # noqa: E402


class GreetingServiceTest(unittest.TestCase):
    """Behaviour of `create_greeting` and the CLI."""

    def test_returns_expected_message(self) -> None:
        """A normal name is greeted and the environment is passed through."""
        cfg = AppConfig(app_env="test", log_level="DEBUG", timeout_seconds=5)
        result = create_greeting(GreetingRequest(user_name="Alice"), cfg)
        self.assertEqual(result.message, "Hello, Alice!")
        self.assertEqual(result.environment, "test")

    def test_blank_name_falls_back_to_world(self) -> None:
        """A blank name produces the default greeting."""
        result = create_greeting(GreetingRequest(user_name="   "), AppConfig(app_env="test"))
        self.assertEqual(result.message, "Hello, World!")

    def test_cli_prints_greeting(self) -> None:
        """The CLI prints the greeting and exits with 0 (no log file is written during tests)."""
        out = io.StringIO()
        with mock.patch.dict(os.environ, {{"LOG_TO_FILE": "false"}}), redirect_stdout(out):
            code = main(["--name", "Bob"])
        self.assertEqual(code, 0)
        self.assertEqual(out.getvalue().strip(), "Hello, Bob!")

    def test_safe_user_path_isolates_system_dirs_in_test_env(self) -> None:
        """In test mode, writes aimed at ~/Desktop or ~/.config are redirected under DATA_DIR."""
        cfg = AppConfig(app_env="test", data_dir=Path("/tmp/{pkg}-test-data"))
        isolated = safe_user_path(cfg, Path.home() / "Desktop" / "out.txt", "desktop")
        self.assertTrue(isolated.resolve().is_relative_to(cfg.data_dir.resolve()))
        self.assertEqual(isolated.name, "out.txt")


if __name__ == "__main__":
    unittest.main()
'''

PY_WIRING = '''"""Shared wiring helpers for CLI, HTTP and MCP entrypoints.

Centralises runtime config loading and system-path isolation so unit tests running with
`APP_ENV=test` never write to `~/Desktop` or `~/.config/`.
"""

from __future__ import annotations

import logging
from pathlib import Path
{third_import}
{db_import}from {pkg}.config.settings import AppConfig, load_config

logger = logging.getLogger(__name__)


def resolve_runtime_config(config: AppConfig | None = None) -> AppConfig:
    """Return an explicitly passed `AppConfig` or load settings from `.env`.

    Args:
        config: Optional pre-built configuration instance.

    Returns:
        Active `AppConfig`.
    """
    return config if config is not None else load_config()


def safe_user_path(config: AppConfig, target: Path, test_subdir: str) -> Path:
    """Guard user-directory writes against polluting host paths during automated tests.

    When `config.app_env == "test"` and `target` points outside `config.data_dir`, redirects
    the destination into `<data_dir>/_test_isolated/<test_subdir>/<filename>`.

    Args:
        config: Application configuration (checks `app_env` and `data_dir`).
        target: Requested output path (e.g. `~/Desktop/report.pdf`).
        test_subdir: Subfolder label under `_test_isolated/` used when isolating test runs.

    Returns:
        Resolved safe target path.
    """
    resolved_target = target.expanduser().resolve()
    resolved_data = config.data_dir.expanduser().resolve()
    if config.app_env == "test" and not resolved_target.is_relative_to(resolved_data):
        isolated = resolved_data / "_test_isolated" / test_subdir / resolved_target.name
        logger.debug("isolated test path %s -> %s", resolved_target, isolated)
        return isolated
    return target
{db_factory}'''

PY_WIRING_DB_HELPER = '''

def build_session_factory(config: AppConfig) -> sessionmaker[Session]:
    """Build a SQLAlchemy session factory from `config.database_url`.

    Args:
        config: Application configuration.

    Returns:
        Configured `sessionmaker[Session]`.
    """
    return make_session_factory(create_db_engine(config.database_url))
'''

LAYER_DOCS = {
    "config": "Configuration layer (only layer allowed to read environment variables) and logging setup.",
    "domain": "Domain layer: pure data models and domain errors.",
    "services": "Services layer: business logic.",
    "adapters": "Adapters layer: external APIs, databases, file and network I/O.",
    "entrypoints": "Entrypoints layer: CLI, HTTP handlers, schedulers.",
}


def build_settings_module(addons: list[str], dist: str, http_port: int = 8000) -> str:
    """Render `config/settings.py` with the fields the add-ons need.

    Args:
        addons: Project add-ons (`api` adds HTTP host/port, `db` adds the database URL).
        dist: Distribution name, used for the default data folder `../../projects-data/<dist>`.
        http_port: Default `HTTP_PORT` fallback embedded for `api` add-on.

    Returns:
        Python source text.
    """
    parts = [
        tuple(seg.replace("{http_port}", str(http_port)) for seg in EXTRA_SETTINGS[a])
        for a in ("api", "ollama", "db") if a in addons
    ]
    return PY_SETTINGS.replace("{dist}", dist).format(
        extra_attr_docs="".join(p[0] for p in parts),
        extra_fields="".join(p[1] for p in parts),
        extra_loads="".join(p[2] for p in parts),
    )


def _toml_strings(items: list[str]) -> str:
    """Render strings as a TOML inline array.

    Args:
        items: Strings to render.

    Returns:
        Text such as `["a", "b"]`.
    """
    return "[" + ", ".join(json.dumps(i) for i in items) + "]"


def build_pyproject(project_name: str, description: str, pkg: str, addons: list[str]) -> str:
    """Render `pyproject.toml` for a uv-managed project.

    Args:
        project_name: Project name (distribution name is derived from it).
        description: One-line description.
        pkg: Python package name under `src/`.
        addons: Project add-ons (`api`, `db` add dependencies and commands).

    Returns:
        TOML text.
    """
    dist = re.sub(r"[^a-z0-9-]+", "-", project_name.lower()).strip("-") or "app"
    deps = (API_DEPENDENCIES if "api" in addons else []) + (DB_DEPENDENCIES if "db" in addons else [])
    dev = ["ruff>=0.6.0", "mypy>=1.11"] + (API_DEV_DEPENDENCIES if "api" in addons else [])
    server = (
        f'\n{dist}-server = "{pkg}.entrypoints.http.server:main"'
        f'\n{dist}-mcp = "{pkg}.entrypoints.mcp_server:main"'
    ) if "api" in addons else ""
    return PYPROJECT_TEMPLATE.format(
        dist_json=json.dumps(dist),
        description_json=json.dumps(description, ensure_ascii=False),
        python_version=PYTHON_VERSION,
        deps_toml=_toml_strings(deps),
        dist=dist,
        pkg=pkg,
        server=server,
        dev_toml=_toml_strings(dev),
    )


def build_wiring_module(pkg: str, addons: list[str]) -> str:
    """Render `entrypoints/wiring.py` with runtime config, test-path isolation and optional DB wiring.

    Args:
        pkg: Python package name under `src/`.
        addons: Active project add-ons (`db` adds `build_session_factory`).

    Returns:
        Python source text.
    """
    with_db = "db" in addons
    third_import = "\nfrom sqlalchemy.orm import Session, sessionmaker\n" if with_db else ""
    db_import = f"from {pkg}.adapters.db.session import create_db_engine, make_session_factory\n" if with_db else ""
    return PY_WIRING.format(
        pkg=pkg,
        third_import=third_import,
        db_import=db_import,
        db_factory=PY_WIRING_DB_HELPER if with_db else "",
    )


def _unpack_python_options(addons_or_options: list[str] | dict[str, Any] | None) -> tuple[list[str], int]:
    """Normalise `addons` list or options dictionary for `scaffold_python_pack()`.

    Args:
        addons_or_options: Add-ons list or dict with `addons` and optional `http_port`.

    Returns:
        Tuple of `(addons, http_port)`.
    """
    if isinstance(addons_or_options, dict):
        return list(addons_or_options.get("addons") or []), int(addons_or_options.get("http_port") or 8000)
    return list(addons_or_options or []), 8000


def scaffold_python_pack(
    target_dir: Path,
    project_name: str,
    description: str,
    addons_or_options: list[str] | dict[str, Any] | None = None,
) -> None:
    """Create the Python starter (`pyproject.toml`, `.python-version`, layered `src/<pkg>`, `tests/`).

    Args:
        target_dir: Project root directory.
        project_name: Project name (also used for the package name).
        description: One-line description for `pyproject.toml`.
        addons_or_options: Add-ons list or dict with `addons` and optional `http_port`.
    """
    logger.debug("scaffold python_pack in %s", target_dir)
    addons, http_port = _unpack_python_options(addons_or_options)
    pkg = slugify_package_name(project_name)
    dist = re.sub(r"[^a-z0-9-]+", "-", project_name.lower()).strip("-") or "app"
    _write(target_dir / "pyproject.toml", build_pyproject(project_name, description, pkg, addons))
    _write(target_dir / ".python-version", PYTHON_VERSION + "\n")
    base = target_dir / "src" / pkg
    _write(base / "__init__.py", f'"""Top-level package for {project_name}."""\n\n__version__ = "0.1.0"\n')
    for layer, doc in LAYER_DOCS.items():
        _write(base / layer / "__init__.py", f'"""{doc}"""\n')
    _write(base / "config" / "settings.py", build_settings_module(addons, dist, http_port=http_port))
    _write(base / "config" / "logging_setup.py", PY_LOGGING)
    _write(base / "domain" / "models.py", PY_DOMAIN)
    _write(base / "services" / "greeting.py", PY_SERVICE.format(pkg=pkg))
    _write(base / "entrypoints" / "cli.py", PY_CLI.format(pkg=pkg, cmd=dist, name=project_name))
    _write(base / "entrypoints" / "wiring.py", build_wiring_module(pkg, addons))
    _write(target_dir / "tests" / "__init__.py", '"""Test package."""\n')
    _write(target_dir / "tests" / "test_greeting.py", PY_TEST.format(pkg=pkg))
    if "db" in addons:
        scaffold_db_pack(target_dir, pkg)
    if "api" in addons:
        scaffold_api_pack(target_dir, pkg, {"project": project_name, "dist": dist, "port": str(http_port)}, addons)
    if "ollama" in addons:
        scaffold_ollama_pack(target_dir, pkg)
