#!/usr/bin/env python3
"""Start the template's local web page, JSON API and MCP endpoint (template-only command).

Purpose:
    Launcher only: puts `src/` on the import path and runs `project_template.entrypoints.web_ui.main()`.
    The template's code lives in `src/project_template/` (the same layers as a generated project).

Usage:
    python3 scripts/web_ui.py
    python3 scripts/web_ui.py --port 8770 --no-browser --allow-host host.docker.internal
"""
from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from project_template.config.runtime import ensure_dependencies  # noqa: E402

ensure_dependencies(Path(__file__).resolve())  # FastAPI / MCP via a uv-managed cache, nothing installed on the host

from project_template.entrypoints.web_ui import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
