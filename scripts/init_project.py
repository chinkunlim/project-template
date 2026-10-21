#!/usr/bin/env python3
"""Create a new project from the template (template-only command).

Purpose:
    Launcher only: puts `src/` on the import path and runs `project_template.entrypoints.init_cli.main()`.
    The template's code lives in `src/project_template/` (the same layers as a generated project).

Usage:
    python3 scripts/init_project.py --target ~/Desktop/projects/my_app --stack python
    python3 scripts/init_project.py --target ~/Desktop/projects/app --stack python --with web gas
    python3 scripts/init_project.py --list-skills
"""
from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from project_template.entrypoints.init_cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
