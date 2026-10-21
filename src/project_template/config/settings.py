"""Template paths and environment settings (the only module that reads environment variables).

Purpose:
    Every other layer asks this module for the template folder, the framework library and
    environment flags, so `code-review-guard` can enforce that only `config` touches
    `os.environ`. Importing it also puts `.agents/lib` (the framework's shared library, which
    every project receives) on `sys.path` so `framework_install` and `project_config` import.

Main items:
    - `TEMPLATE_ROOT`, `FRAMEWORK_LIB`, `REGISTRY_FILE`, `WEB_PAGE` : fixed paths.
    - `env_flag()` / `env_value()` / `set_env()` : read or set one environment variable.
    - `child_env()` : environment for commands run inside a project (without the template's DATA_DIR).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

TEMPLATE_ROOT = Path(__file__).resolve().parents[3]  # src/project_template/config/settings.py -> template root
FRAMEWORK_LIB = TEMPLATE_ROOT / ".agents" / "lib"
REGISTRY_FILE = TEMPLATE_ROOT / ".local" / "projects.json"
WEB_PAGE = Path(__file__).resolve().parents[1] / "entrypoints" / "web" / "index.html"
SKILLS_CACHE = TEMPLATE_ROOT / ".skills-cache"

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
