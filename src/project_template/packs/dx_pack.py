#!/usr/bin/env python3
"""Developer-experience files: `.editorconfig`, VS Code workspace settings, optional LICENSE.

Purpose:
    Every project opens the same way in any editor on any computer:
      - `.editorconfig`          : indentation, line endings, UTF-8, final newline
      - `.vscode/settings.json`  : Python from the project `.venv`, ruff format on save, unittest discovery
      - `.vscode/launch.json`    : debug configurations for the CLI (and the API server with `--with api`)
      - `.vscode/extensions.json`: recommended extensions
      - `LICENSE`                : only with `--license MIT` (no license is granted by default)
"""

from __future__ import annotations

import json
import subprocess
from datetime import date
from pathlib import Path
from typing import Any

from project_template.packs.common import write_file as _write

EDITORCONFIG = """# Editor settings shared by every editor (https://editorconfig.org)
root = true

[*]
indent_style = space
indent_size = 2
end_of_line = lf
charset = utf-8
trim_trailing_whitespace = true
insert_final_newline = true

[*.py]
indent_size = 4

[*.md]
trim_trailing_whitespace = false

[Makefile]
indent_style = tab
"""

MIT_LICENSE = """MIT License

Copyright (c) {year} {holder}

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""


def _json(data: dict[str, Any]) -> str:
    """Render pretty JSON with a trailing newline.

    Args:
        data: Data to render.

    Returns:
        JSON text.
    """
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def vscode_files(languages: list[str], pkg: str, dist: str) -> dict[str, str]:
    """Build the `.vscode/` files for the project's languages.

    Args:
        languages: Base stack plus add-ons.
        pkg: Python package name (used by debug configurations).
        dist: Distribution name (CLI command name).

    Returns:
        Mapping of repo-relative path -> content.
    """
    settings: dict[str, Any] = {"files.exclude": {"**/__pycache__": True, "**/.ruff_cache": True, "**/.mypy_cache": True}}
    extensions = ["editorconfig.editorconfig"]
    configs: list[dict[str, Any]] = []
    if "python" in languages:
        settings.update({
            "python.defaultInterpreterPath": "${workspaceFolder}/.venv/bin/python",
            "python.testing.unittestEnabled": True,
            "python.testing.unittestArgs": ["-s", "tests", "-p", "test_*.py"],
            "[python]": {"editor.defaultFormatter": "charliermarsh.ruff", "editor.formatOnSave": True,
                         "editor.codeActionsOnSave": {"source.organizeImports": "explicit"}},
        })
        extensions += ["ms-python.python", "charliermarsh.ruff", "ms-python.mypy-type-checker"]
        configs.append({"name": f"{dist}: CLI", "type": "debugpy", "request": "launch", "module": f"{pkg}.entrypoints.cli",
                        "args": ["--name", "Debug"], "envFile": "${workspaceFolder}/.env", "console": "integratedTerminal"})
    if "api" in languages:
        configs.append({"name": f"{dist}: API server (127.0.0.1)", "type": "debugpy", "request": "launch",
                        "module": f"{pkg}.entrypoints.http.server", "envFile": "${workspaceFolder}/.env", "console": "integratedTerminal"})
    if {"node", "gas", "web", "mobile"} & set(languages):
        extensions.append("dbaeumer.vscode-eslint")
    if "mobile" in languages:
        extensions.append("expo.vscode-expo-tools")
    files = {".vscode/settings.json": _json(settings), ".vscode/extensions.json": _json({"recommendations": extensions})}
    if configs:
        files[".vscode/launch.json"] = _json({"version": "0.2.0", "configurations": configs})
    return files


def license_text(kind: str) -> str:
    """Render a LICENSE file.

    Args:
        kind: `MIT` (the only supported license) or `none`.

    Returns:
        License text, or an empty string for `none`.
    """
    if kind.upper() != "MIT":
        return ""
    holder = subprocess.run(["git", "config", "user.name"], capture_output=True, text=True, check=False).stdout.strip()
    return MIT_LICENSE.format(year=date.today().year, holder=holder or "The project authors")


def scaffold_dx_files(target_dir: Path, languages: list[str], names: dict[str, str]) -> None:
    """Write `.editorconfig`, `.vscode/` and (optionally) `LICENSE`.

    Args:
        target_dir: Project root directory.
        languages: Base stack plus add-ons.
        names: `pkg`, `dist` and `license` (`MIT` or `none`).
    """
    _write(target_dir / ".editorconfig", EDITORCONFIG)
    for rel, content in vscode_files(languages, names["pkg"], names["dist"]).items():
        _write(target_dir / rel, content)
    text = license_text(names.get("license", "none"))
    if text:
        _write(target_dir / "LICENSE", text)
