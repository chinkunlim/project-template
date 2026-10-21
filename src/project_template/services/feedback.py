"""Collect template-improvement suggestions from every project into one list (template-only tool).

Purpose:
    Each project records "every project should do this" ideas in its own
    `docs/TEMPLATE_FEEDBACK.md`. With many projects those ideas are scattered, so this
    tool reads that file in every tracked project (a projects folder, default: the folder that contains the
    template, plus the registered projects elsewhere) and prints one Markdown list of
    the suggestions that are still open (status `待決定` or empty), oldest first, with the
    project, its framework version and the file to edit afterwards.

    It only reads: project files are never changed. After deciding, set the status in the
    project's own file to `已採用` (template updated) or `不採用`.

Usage:
    `scripts/collect_feedback.py` (see `entrypoints/feedback_cli.py`) and the web page call
    `collect()`.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from project_template.config.settings import TEMPLATE_ROOT
from project_template.services import update_all

logger = logging.getLogger(__name__)
# Projects normally sit next to the template (e.g. ~/Desktop/projects/01 project_template and
# ~/Desktop/projects/<project>), so the default follows the template wherever it is moved.
DEFAULT_ROOT = TEMPLATE_ROOT.parent
FEEDBACK_REL = Path("docs") / "TEMPLATE_FEEDBACK.md"
CLOSED_STATUSES = {"已採用", "不採用", "adopted", "rejected", "done"}
CELL_SPLIT = re.compile(r"(?<!\\)\|")


@dataclass
class Suggestion:
    """One row of a project's `TEMPLATE_FEEDBACK.md`.

    Attributes:
        project: Project folder name.
        version: Framework version recorded in the project's `framework.lock` (`?` when unknown).
        file: Path of the feedback file (to edit the status afterwards).
        date: Date cell as written.
        text: The suggestion.
        source: Conversation / task it came from.
        status: Status cell (`待決定` when empty).
    """

    project: str
    version: str
    file: Path
    date: str
    text: str
    source: str
    status: str


def find_feedback_files(roots: list[Path], depth: int, registered: bool = False) -> list[Path]:
    """Find the `docs/TEMPLATE_FEEDBACK.md` of every tracked project.

    Args:
        roots: Folders that contain projects.
        depth: How many folder levels below each root a project may sit.
        registered: Also read registered projects outside `roots` (`update_all.tracked_projects()`).

    Returns:
        Sorted feedback file paths (the template itself is skipped).
    """
    projects = update_all.tracked_projects(roots, depth, registered)
    return sorted(p / FEEDBACK_REL for p in projects if (p / FEEDBACK_REL).is_file())


def framework_version(project: Path) -> str:
    """Read the framework version a project was created or last updated with.

    Args:
        project: Project root directory.

    Returns:
        Version such as `3.2.0`, or `?` when the lock file is missing or unreadable.
    """
    lock = project / ".agents" / "framework.lock"
    try:
        return str(json.loads(lock.read_text(encoding="utf-8")).get("framework_version", "?"))
    except (OSError, ValueError):
        return "?"


def parse_rows(text: str) -> list[list[str]]:
    """Extract the data rows of the Markdown table in a feedback file.

    Args:
        text: File content.

    Returns:
        Rows as lists of at least four cells (date, suggestion, source, status).
    """
    rows = []
    for line in text.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in CELL_SPLIT.split(line.strip().strip("|"))]
        if len(cells) < 4 or set("".join(cells)) <= set("-: ") or cells[0] == "日期":
            continue
        rows.append(cells)
    return rows


def read_suggestions(feedback_file: Path) -> list[Suggestion]:
    """Read every suggestion of one project.

    Args:
        feedback_file: A project's `docs/TEMPLATE_FEEDBACK.md`.

    Returns:
        Suggestions; an empty status counts as `待決定`.
    """
    project = feedback_file.parent.parent
    version = framework_version(project)
    text = feedback_file.read_text(encoding="utf-8", errors="replace")
    return [
        Suggestion(project.name, version, feedback_file, date, idea, source, status or "待決定")
        for date, idea, source, status, *_ in parse_rows(text)
        if idea
    ]


def is_open(item: Suggestion) -> bool:
    """Tell whether a suggestion still needs a decision.

    Args:
        item: One suggestion.

    Returns:
        True unless its status is adopted or rejected.
    """
    status = item.status.strip().lower()
    return not any(status.startswith(closed) for closed in CLOSED_STATUSES)  # "已採用（說明）" counts as adopted


def render_report(items: list[Suggestion], scanned: int, show_all: bool) -> str:
    """Render the combined Markdown list.

    Args:
        items: Suggestions to show (already filtered).
        scanned: Number of feedback files read.
        show_all: Whether closed suggestions are included (changes the heading).

    Returns:
        Markdown text.
    """
    kind = "全部建議" if show_all else "待決定的建議"
    lines = [f"# 母版改進建議彙整（{kind}）", "", f"掃描 {scanned} 個專案，共 {len(items)} 條。", ""]
    if not items:
        return "\n".join(lines + ["目前沒有需要決定的建議。", ""])
    lines += ["| 日期 | 專案（框架版本） | 建議 | 來源 | 狀態 |", "|---|---|---|---|---|"]
    for item in sorted(items, key=lambda s: (s.date, s.project)):
        lines.append(f"| {item.date} | `{item.project}` (v{item.version}) | {item.text} | {item.source} | {item.status} |")
    files = sorted({str(item.file) for item in items})
    lines += ["", "決定後，在各專案自己的檔案把狀態改成 `已採用` 或 `不採用`：", "", *[f"- `{f}`" for f in files], ""]
    return "\n".join(lines)


def collect(roots: list[Path], depth: int, show_all: bool, registered: bool = False) -> str:
    """Scan the projects and build the combined Markdown list.

    Args:
        roots: Folders that contain projects.
        depth: How many folder levels below each root a project may sit.
        show_all: Include adopted / rejected suggestions too.
        registered: Also read registered projects outside `roots`.

    Returns:
        Markdown text.
    """
    files = find_feedback_files(roots, depth, registered)
    items = [s for f in files for s in read_suggestions(f)]
    return render_report(items if show_all else [s for s in items if is_open(s)], len(files), show_all)
