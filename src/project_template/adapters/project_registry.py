"""Registry of the projects created or migrated with this template (template-only, standard library).

Purpose:
    The template page shows every project you made, even ones outside the default projects
    folder. `scripts/init_project.py` and `scripts/migrate_project.py` record each new project here, and
    the page's "加入既有專案" records an existing one (`how = existing`), in `.local/projects.json` inside
    the template (git-ignored, personal to this computer; `TEMPLATE_REGISTRY_FILE` overrides it).

    No hard-coded locations: a project inside the folder that contains the template is stored
    relative to that folder, so moving `projects/` as a whole keeps the registry valid. Projects
    elsewhere keep an absolute path; when one is moved, the page shows it as missing and it can
    be removed. Set `TEMPLATE_NO_REGISTRY=1` to skip recording (used by the tests).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from project_template.config.settings import TEMPLATE_ROOT, env_flag, registry_file


def _base() -> Path:
    """Folder that relative registry paths start from (the template's parent).

    Returns:
        The folder.
    """
    return TEMPLATE_ROOT.parent.resolve()


def _stored(path: Path) -> str:
    """Path text written to the registry.

    Args:
        path: Absolute project folder.

    Returns:
        A path relative to the template's parent when possible, otherwise absolute.
    """
    resolved = path.resolve()
    try:
        return resolved.relative_to(_base()).as_posix()
    except ValueError:
        return resolved.as_posix()


def load() -> list[dict[str, Any]]:
    """Read the registry.

    Returns:
        Entries with `path` (absolute), `name`, `how` (init / migrate), `created` and `exists`.
    """
    try:
        registry = registry_file()
        rows = json.loads(registry.read_text(encoding="utf-8")) if registry.exists() else []
    except (OSError, ValueError):
        rows = []
    out = []
    for row in rows:
        path = Path(row.get("path", ""))
        absolute = path if path.is_absolute() else _base() / path
        out.append({**row, "path": str(absolute), "exists": absolute.is_dir()})
    return out


def _save(rows: list[dict[str, Any]]) -> None:
    """Write the registry (paths stored relative when possible).

    Args:
        rows: Entries with absolute `path`.
    """
    registry = registry_file()
    registry.parent.mkdir(parents=True, exist_ok=True)
    data = [{k: v for k, v in {**r, "path": _stored(Path(r["path"]))}.items() if k != "exists"} for r in rows]
    registry.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def register(path: Path, how: str) -> None:
    """Record a created, migrated or added project (once per folder).

    Args:
        path: Project folder.
        how: `init`, `migrate` or `existing`.
    """
    if env_flag("TEMPLATE_NO_REGISTRY"):
        return
    rows = [r for r in load() if Path(r["path"]).resolve() != path.resolve()]
    rows.append({"path": str(path.resolve()), "name": path.name, "how": how,
                 "created": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")})
    _save(rows)


def forget(path: str) -> bool:
    """Remove a project from the registry (the folder itself is not touched).

    Args:
        path: Absolute project folder as shown by `load()`.

    Returns:
        True when an entry was removed.
    """
    rows = load()
    kept = [r for r in rows if r["path"] != path]
    if len(kept) != len(rows):
        _save(kept)
        return True
    return False
