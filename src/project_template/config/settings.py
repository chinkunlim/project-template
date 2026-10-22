"""Template paths and environment settings (the only module that reads environment variables).

Purpose:
    Every other layer asks this module for the template folder, the framework library and
    environment flags, so `code-review-guard` can enforce that only `config` touches
    `os.environ`. Importing it also puts `.agents/lib` (the framework's shared library, which
    every project receives) on `sys.path` so `framework_install` and `project_config` import.

Main items:
    - `TEMPLATE_ROOT`, `FRAMEWORK_LIB`, `REGISTRY_FILE`, `WEB_PAGE` : fixed paths.
    - `registry_file()` : the project registry (`TEMPLATE_REGISTRY_FILE` overrides `REGISTRY_FILE`, used by the tests).
    - `env_flag()` / `env_value()` / `set_env()` : read or set one environment variable.
    - `child_env()` : environment for commands run inside a project (without the template's DATA_DIR).
    - `template_dotenv()` / `data_dir()` / `log_settings()` : the template's own `.env`, data folder and
      logging switches (logs go to `<DATA_DIR>/logs/`, see `config/logging_setup.py`).
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)
TEMPLATE_ROOT = Path(__file__).resolve().parents[3]  # src/project_template/config/settings.py -> template root
FRAMEWORK_LIB = TEMPLATE_ROOT / ".agents" / "lib"
REGISTRY_FILE = TEMPLATE_ROOT / ".local" / "projects.json"
WEB_PAGE = Path(__file__).resolve().parents[1] / "entrypoints" / "web" / "index.html"
SKILLS_CACHE = TEMPLATE_ROOT / ".skills-cache"
DOTENV_FILE = TEMPLATE_ROOT / ".env"
DEFAULT_DATA_DIR = "../../projects-data/project_template"

if str(FRAMEWORK_LIB) not in sys.path:
    sys.path.insert(0, str(FRAMEWORK_LIB))


def env_value(name: str, default: str = "") -> str:
    """Read one environment variable.

    Args:
        name: Variable name.
        default: Value when the variable is not set.

    Returns:
        The value with surrounding spaces removed.
    """
    return os.environ.get(name, default).strip()


def registry_file() -> Path:
    """Where the registry of created / migrated / added projects is stored.

    Returns:
        `TEMPLATE_REGISTRY_FILE` when set (the tests point it at a temporary file), else `.local/projects.json`.
    """
    override = env_value("TEMPLATE_REGISTRY_FILE")
    return Path(override).expanduser() if override else REGISTRY_FILE


def env_flag(name: str) -> bool:
    """Tell whether an on/off environment variable is switched on.

    Args:
        name: Variable name, e.g. `TEMPLATE_NO_REGISTRY`.

    Returns:
        True for any value except empty, `0`, `false` and `no`.
    """
    return env_value(name).lower() not in ("", "0", "false", "no")


def set_env(name: str, value: str) -> None:
    """Set an environment variable for this process and the commands it starts.

    Args:
        name: Variable name.
        value: Value to set.
    """
    os.environ[name] = value


def child_env() -> dict[str, str]:
    """Environment for commands that run inside another project.

    Returns:
        A copy of this process's environment without `DATA_DIR`, so each project reads
        its own `.env` instead of inheriting the template's data folder.
    """
    return {k: v for k, v in os.environ.items() if k != "DATA_DIR"}


def template_dotenv(path: Path | None = None) -> dict[str, str]:
    """Read the template's own `.env` without changing `os.environ`.

    The values are not exported, so commands run in other projects never inherit the template's
    `DATA_DIR` (see `child_env()`).

    Args:
        path: File to read; defaults to `<template>/.env` (missing file -> empty result).

    Returns:
        `KEY -> value` pairs (blank lines and `#` comments skipped, surrounding quotes removed).
    """
    path = path or DOTENV_FILE
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.strip().partition("=")
        if sep and key and not key.startswith("#"):
            values[key.strip()] = value.strip().strip("'\"")
    return values


def data_dir() -> Path:
    """The template's data folder (outside the template folder), e.g. for its log files.

    Returns:
        `TEMPLATE_DATA_DIR` when set (the tests point it at a temporary folder), else `DATA_DIR` from
        the template's `.env`, else `../../projects-data/project_template`. A relative path is read from
        the template folder. An inherited `DATA_DIR` variable is ignored on purpose (Open WebUI exports one).
    """
    raw = env_value("TEMPLATE_DATA_DIR") or template_dotenv().get("DATA_DIR", "") or DEFAULT_DATA_DIR
    path = Path(raw).expanduser()
    return (path if path.is_absolute() else TEMPLATE_ROOT / path).resolve()


def log_settings() -> tuple[str, Path | None]:
    """Logging level and log folder for the template's own commands.

    Returns:
        `(level, log_dir)`: `LOG_LEVEL` (environment, then `.env`, default `INFO`) and
        `<data_dir>/logs`, or None when `LOG_TO_FILE` is switched off.
    """
    dotenv = template_dotenv()
    level = env_value("LOG_LEVEL") or dotenv.get("LOG_LEVEL", "") or "INFO"
    to_file = env_value("LOG_TO_FILE") or dotenv.get("LOG_TO_FILE", "") or "true"
    return level, (data_dir() / "logs" if to_file.lower() not in ("0", "false", "no") else None)
