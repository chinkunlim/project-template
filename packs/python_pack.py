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
import re
from pathlib import Path

from packs.api_pack import API_DEPENDENCIES, API_DEV_DEPENDENCIES, scaffold_api_pack
from packs.common import slugify_package_name, write_file as _write
from packs.db_pack import DB_DEPENDENCIES, scaffold_db_pack
from packs.ollama_pack import scaffold_ollama_pack

PYTHON_VERSION = "3.11"

PY_SETTINGS = '''"""Configuration layer: the ONLY layer allowed to read environment variables.

Loads settings once at startup into an immutable `AppConfig` so every other layer
receives plain values instead of touching `os.environ`.

Data lives OUTSIDE the project folder: `DATA_DIR` (default `~/project-data/{dist}`) holds
input/, output/, needs_review/, state/, db/ and logs/. The project folder only holds code,
docs and small test fixtures.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATA_DIR = "~/project-data/{dist}"


def load_dotenv_file(path: Path) -> None:
    """Load `KEY=value` lines from a `.env` file without overriding variables that are already set.

    Args:
        path: The `.env` file (missing files are ignored).
    """
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip("\\"'"))


@dataclass(frozen=True)
class AppConfig:
    """Immutable application settings.

    Attributes:
        app_env: Deployment environment name, e.g. `development` or `production`.
        log_level: Logging level name, e.g. `INFO` or `DEBUG`.
        log_to_file: Also write logs to `<data_dir>/logs/app.log`.
        timeout_seconds: Timeout for outgoing API calls.
        ollama_base_url: Local Ollama endpoint (always 127.0.0.1, never localhost / 0.0.0.0).
        data_dir: Root folder for all data, outside the project folder.{extra_attr_docs}
    """

    app_env: str = "development"
    log_level: str = "INFO"
    log_to_file: bool = False
    timeout_seconds: int = 15
    ollama_base_url: str = "http://127.0.0.1:11434"
    data_dir: Path = Path(DEFAULT_DATA_DIR).expanduser(){extra_fields}

    @property
    def input_dir(self) -> Path:
        """Folder with files waiting to be processed.

        Returns:
            `<data_dir>/input`.
        """
        return self.data_dir / "input"

    @property
    def output_dir(self) -> Path:
        """Folder for produced results.

        Returns:
            `<data_dir>/output`.
        """
        return self.data_dir / "output"

    @property
    def needs_review_dir(self) -> Path:
        """Quarantine for failed or low-confidence items (batches never stop for them).

        Returns:
            `<data_dir>/needs_review`.
        """
        return self.data_dir / "needs_review"

    @property
    def state_dir(self) -> Path:
        """Folder for progress / resume state.

        Returns:
            `<data_dir>/state`.
        """
        return self.data_dir / "state"

    @property
    def logs_dir(self) -> Path:
        """Folder for log files.

        Returns:
            `<data_dir>/logs`.
        """
        return self.data_dir / "logs"


def _flag(value: str) -> bool:
    """Interpret an environment flag.

    Args:
        value: Raw text such as `1`, `true`, `yes`.

    Returns:
        True for 1 / true / yes / on (case-insensitive).
    """
    return value.strip().lower() in ("1", "true", "yes", "on")


def load_config() -> AppConfig:
    """Read and validate configuration from `.env` and environment variables.

    Returns:
        A populated `AppConfig`.

    Raises:
        ValueError: When a numeric setting is not an integer.
    """
    load_dotenv_file(PROJECT_ROOT / ".env")
    data_dir = Path(os.environ.get("DATA_DIR", DEFAULT_DATA_DIR).strip()).expanduser()
    return AppConfig(
        app_env=os.environ.get("APP_ENV", "development").strip(),
        log_level=os.environ.get("LOG_LEVEL", "INFO").strip().upper(),
        log_to_file=_flag(os.environ.get("LOG_TO_FILE", "false")),
        timeout_seconds=int(os.environ.get("API_TIMEOUT_SECONDS", "15")),
        ollama_base_url=os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434").strip().rstrip("/"),
        data_dir=data_dir,{extra_loads}
    )
'''

PY_LOGGING = '''"""Logging setup shared by every entrypoint.

One consistent format (time, level, module, message) makes logs from different runs
and different agents easy to compare when debugging. Optionally also writes a size-limited
`app.log` into the data folder (outside the project).
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def setup_logging(level: str = "INFO", log_dir: Path | None = None) -> None:
    """Configure the root logger once.

    Args:
        level: Logging level name such as `DEBUG`, `INFO` or `WARNING`; unknown names fall back to `INFO`.
        log_dir: When given, also write `app.log` there (5 MB x 3 rotated files).
    """
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "app.log"
        handlers.append(RotatingFileHandler(log_file, maxBytes=5_000_000, backupCount=3, encoding="utf-8"))
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(level=numeric_level, format=LOG_FORMAT, handlers=handlers, force=True)
'''

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
    logger.debug("greeting user=%r env=%s", clean_name, config.app_env)
    return GreetingResult(message=f"Hello, {{clean_name}}!", environment=config.app_env)
'''

PY_CLI = '''"""Command-line entrypoint: `uv run {cmd} --name Alice`.

Wires the layers together: read config, set up logging, call the service, print the result.
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
    result = create_greeting(GreetingRequest(user_name=args.name), config)
    logger.info("greeting created (env=%s)", result.environment)
    print(result.message)
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


if __name__ == "__main__":
    unittest.main()
'''

LAYER_DOCS = {
    "config": "Configuration layer (only layer allowed to read environment variables) and logging setup.",
    "domain": "Domain layer: pure data models and domain errors.",
    "services": "Services layer: business logic.",
    "adapters": "Adapters layer: external APIs, databases, file and network I/O.",
    "entrypoints": "Entrypoints layer: CLI, HTTP handlers, schedulers.",
}


EXTRA_SETTINGS = {
    "api": (
        "\n        http_host: Address the HTTP server binds to (127.0.0.1 only; never 0.0.0.0).\n        http_port: HTTP server port.",
        '\n    http_host: str = "127.0.0.1"\n    http_port: int = 8000',
        '\n        http_host=os.environ.get("HTTP_HOST", "127.0.0.1").strip(),\n        http_port=int(os.environ.get("HTTP_PORT", "8000")),',
    ),
    "ollama": (
        "\n        ollama_model: Local model name, e.g. `qwen2.5`.\n        ollama_timeout_seconds: Timeout for one model call.",
        '\n    ollama_model: str = "qwen2.5"\n    ollama_timeout_seconds: int = 120',
        '\n        ollama_model=os.environ.get("OLLAMA_MODEL", "qwen2.5").strip(),'
        '\n        ollama_timeout_seconds=int(os.environ.get("OLLAMA_TIMEOUT_SECONDS", "120")),',
    ),
    "db": (
        "\n        database_url: SQLAlchemy URL; SQLite file `<data_dir>/db/app.db` by default.",
        '\n    database_url: str = "sqlite://"',
        '\n        database_url=os.environ.get("DATABASE_URL", "").strip() or f"sqlite:///{data_dir / \'db\' / \'app.db\'}",',
    ),
}


def build_settings_module(addons: list[str], dist: str) -> str:
    """Render `config/settings.py` with the fields the add-ons need.

    Args:
        addons: Project add-ons (`api` adds HTTP host/port, `db` adds the database URL).
        dist: Distribution name, used for the default data folder `~/project-data/<dist>`.

    Returns:
        Python source text.
    """
    parts = [EXTRA_SETTINGS[a] for a in ("api", "ollama", "db") if a in addons]
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
    server = f'\n{dist}-server = "{pkg}.entrypoints.http.server:main"' if "api" in addons else ""
    return f'''[project]
name = {json.dumps(dist)}
version = "0.1.0"
description = {json.dumps(description, ensure_ascii=False)}
readme = "README.md"
requires-python = ">={PYTHON_VERSION}"
dependencies = {_toml_strings(deps)}  # add with `uv add <package>` (never `pip install`)

[project.scripts]
{dist} = "{pkg}.entrypoints.cli:main"{server}

[dependency-groups]
dev = {_toml_strings(dev)}  # add with `uv add --dev <package>`

[build-system]
requires = ["setuptools>=68.0"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]

[tool.uv]
# Use uv's own downloaded Python (see .python-version), never the system / Homebrew one
python-preference = "only-managed"

[tool.ruff]
line-length = 110
target-version = "py311"
src = ["src", "tests"]
# Framework-managed files (updated by `agentctl update`) and non-Python folders are not linted here
extend-exclude = ["scripts", ".agents", "gas", "web", "legacy", "data"]

[tool.ruff.lint]
select = ["E", "F", "W", "I", "B"]

[tool.mypy]
python_version = "{PYTHON_VERSION}"
files = ["src"]
mypy_path = "src"
strict = true
'''


def scaffold_python_pack(target_dir: Path, project_name: str, description: str, addons: list[str] | None = None) -> None:
    """Create the Python starter (`pyproject.toml`, `.python-version`, layered `src/<pkg>`, `tests/`).

    Args:
        target_dir: Project root directory.
        project_name: Project name (also used for the package name).
        description: One-line description for `pyproject.toml`.
        addons: Project add-ons; `api` adds FastAPI, `db` adds SQLAlchemy + Alembic + SQLite.
    """
    addons = addons or []
    pkg = slugify_package_name(project_name)
    dist = re.sub(r"[^a-z0-9-]+", "-", project_name.lower()).strip("-") or "app"
    _write(target_dir / "pyproject.toml", build_pyproject(project_name, description, pkg, addons))
    _write(target_dir / ".python-version", PYTHON_VERSION + "\n")
    base = target_dir / "src" / pkg
    _write(base / "__init__.py", f'"""Top-level package for {project_name}."""\n\n__version__ = "0.1.0"\n')
    for layer, doc in LAYER_DOCS.items():
        _write(base / layer / "__init__.py", f'"""{doc}"""\n')
    _write(base / "config" / "settings.py", build_settings_module(addons, dist))
    _write(base / "config" / "logging_setup.py", PY_LOGGING)
    _write(base / "domain" / "models.py", PY_DOMAIN)
    _write(base / "services" / "greeting.py", PY_SERVICE.format(pkg=pkg))
    _write(base / "entrypoints" / "cli.py", PY_CLI.format(pkg=pkg, cmd=dist, name=project_name))
    _write(target_dir / "tests" / "__init__.py", '"""Test package."""\n')
    _write(target_dir / "tests" / "test_greeting.py", PY_TEST.format(pkg=pkg))
    if "db" in addons:
        scaffold_db_pack(target_dir, pkg)
    if "api" in addons:
        scaffold_api_pack(target_dir, pkg, {"project": project_name, "dist": dist}, addons)
    if "ollama" in addons:
        scaffold_ollama_pack(target_dir, pkg)
