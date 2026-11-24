#!/usr/bin/env python3
"""Start, stop, or inspect the template Hub and child project web servers (template-only command).

Purpose:
    Launcher only: puts `src/` on the import path and runs `project_template.entrypoints.hub_cli.main()`.
    Uses Python standard library only so startup commands return immediately without installing packages.

Usage:
    python3 scripts/hub.py start
    python3 scripts/hub.py stop
    python3 scripts/hub.py status
    python3 scripts/hub.py launch <project>
    python3 scripts/hub.py stop-project <project>
    python3 scripts/hub.py stop-all
    python3 scripts/hub.py autostart on
"""
from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from project_template.entrypoints.hub_cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
