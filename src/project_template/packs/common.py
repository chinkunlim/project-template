#!/usr/bin/env python3
"""Helpers shared by every starter pack: file writing, names, and `package.json`.

Purpose:
    Keeps small utilities in one place so each language pack only describes its own
    files.
"""

from __future__ import annotations

import json
import re
import shutil
import stat
import subprocess
from pathlib import Path
from typing import Any

DEFAULT_NODE = "lts/*"
# `engines.npm` + `engine-strict` makes `npm install` stop before writing package-lock.json; pnpm ignores it
NPM_BLOCK_ENGINES = {"npm": "please-use-pnpm"}
NPMRC = "engine-strict=true\n"


def write_file(path: Path, content: str, executable: bool = False) -> None:
    """Write a starter file, creating parent folders.

    Args:
        path: Destination file.
        content: File content.
        executable: Also set the executable bits.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if executable:
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def slugify_package_name(project_name: str) -> str:
    """Convert a project name into a valid Python/Rust package identifier.

    Args:
        project_name: Free-text project name.

    Returns:
        Lower-case identifier such as `my_app` (prefixed with `app_` if it starts with a digit).
    """
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", project_name.strip().lower()).strip("_")
    if not slug or slug[0].isdigit():
        slug = f"app_{slug}" if slug else "app"
    return slug


def npm_slug(project_name: str) -> str:
    """Convert a project name into a valid npm package name.

    Args:
        project_name: Free-text project name.

    Returns:
        Lower-case name with `-` separators (`app` when nothing is left).
    """
    return re.sub(r"[^a-z0-9-]+", "-", project_name.lower()).strip("-") or "app"


def _tool_version(cmd: str, *args: str) -> str:
    """Run `<cmd> <args>` and return its trimmed output.

    Args:
        cmd: Executable name.
        *args: Arguments, usually a version flag.

    Returns:
        Output text, or an empty string when the tool is missing or fails.
    """
    exe = shutil.which(cmd)
    if not exe:
        return ""
    res = subprocess.run([exe, *args], capture_output=True, text=True, check=False)
    return res.stdout.strip() if res.returncode == 0 else ""


def detect_node_toolchain() -> dict[str, str]:
    """Detect this computer's Node major version (nvm) and pnpm version (corepack).

    Returns:
        Dict with `node` (major version such as `24`, or `lts/*`) and `pnpm` (e.g. `12.11.2`, or empty).
    """
    node = _tool_version("node", "-v").lstrip("v").split(".")[0]
    pnpm = _tool_version("pnpm", "-v")
    return {"node": node or DEFAULT_NODE, "pnpm": pnpm if re.fullmatch(r"\d+\.\d+\.\d+", pnpm) else ""}


def write_package_json(folder: Path, content: str) -> None:
    """Write `package.json` together with the `.npmrc` that blocks npm in this folder.

    Args:
        folder: Node project folder.
        content: Output of `package_json()`.
    """
    write_file(folder / "package.json", content)
    write_file(folder / ".npmrc", NPMRC)


def package_json(slug: str, description: str, scripts: dict[str, str], options: dict[str, Any]) -> str:
    """Render a project-local `package.json` (tools are dev dependencies, never global installs).

    Args:
        slug: npm package name.
        description: One-line description.
        scripts: Scripts in addition to `test` (`node --test`).
        options: Optional `module_type` (`module` for ESM), `dev_deps` (dict), and
            `pnpm` (version pinned in `packageManager` so corepack uses the same pnpm everywhere).

    Returns:
        JSON text.
    """
    data: dict[str, Any] = {"name": slug, "version": "0.1.0", "description": description, "private": True}
    if options.get("pnpm"):
        data["packageManager"] = f"pnpm@{options['pnpm']}"
    if options.get("module_type"):
        data["type"] = options["module_type"]
    data["engines"] = NPM_BLOCK_ENGINES
    data["scripts"] = {"test": "node --test", **scripts}
    if options.get("dev_deps"):
        data["devDependencies"] = options["dev_deps"]
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"
