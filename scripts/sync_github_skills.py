#!/usr/bin/env python3
"""Fetch pinned upstream skill sources into the git-ignored .skills-cache/ (template-only command).

Purpose:
    Launcher only: puts `src/` on the import path and runs `project_template.entrypoints.skills_sync_cli.main()`.
    The template's code lives in `src/project_template/` (the same layers as a generated project).

Usage:
    python3 scripts/sync_github_skills.py list | fetch [name ...] | update [name ...]
"""
from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from project_template.entrypoints.skills_sync_cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
