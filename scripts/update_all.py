#!/usr/bin/env python3
"""Preview or apply the framework update for every project (template-only command).

Purpose:
    Launcher only: puts `src/` on the import path and runs `project_template.entrypoints.update_all_cli.main()`.
    The template's code lives in `src/project_template/` (the same layers as a generated project).

Usage:
    python3 scripts/update_all.py [--apply]
"""
from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from project_template.entrypoints.update_all_cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
