#!/usr/bin/env python3
"""Run the template's MCP server over stdio for AI tools (template-only command).

Purpose:
    Launcher only: puts `src/` on the import path and runs `project_template.entrypoints.template_mcp.main()`.
    The template's code lives in `src/project_template/` (the same layers as a generated project).

Usage:
    python3 scripts/template_mcp.py
"""
from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from project_template.config.runtime import ensure_dependencies  # noqa: E402

ensure_dependencies(Path(__file__).resolve())  # FastAPI / MCP via a uv-managed cache, nothing installed on the host

from project_template.entrypoints.template_mcp import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
