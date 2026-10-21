"""The framework library (`.agents/lib`) as seen by the template's own code.

Purpose:
    `framework_install` and `project_config` live in `.agents/lib` because every project receives
    them. Importing them through this module guarantees `.agents/lib` is on `sys.path` first
    (`settings` adds it), whatever order the importing module's imports are sorted in.
"""
# ruff: noqa: I001 - the import order below is the point of this module
from __future__ import annotations

from project_template.config import settings as _settings  # noqa: F401 - puts .agents/lib on sys.path

from framework_install import (  # noqa: E402
    framework_file_map,
    install_files,
    load_catalog,
    select_skills,
    write_lock,
)
from project_config import FRAMEWORK_VERSION, parse_toml  # noqa: E402

__all__ = ["FRAMEWORK_VERSION", "framework_file_map", "install_files", "load_catalog", "parse_toml", "select_skills", "write_lock"]
