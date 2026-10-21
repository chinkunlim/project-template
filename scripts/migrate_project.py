#!/usr/bin/env python3
"""Move an old project into a new folder built from the template (template-only command).

Purpose:
    Launcher only: puts `src/` on the import path and runs `project_template.entrypoints.migrate_cli.main()`.
    The template's code lives in `src/project_template/` (the same layers as a generated project).

Usage:
    python3 scripts/migrate_project.py --from ~/Desktop/projects/old_app --target ~/Desktop/projects/old_app_v2
"""
from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from project_template.entrypoints.migrate_cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
