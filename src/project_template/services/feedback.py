"""Collect and maintain template-improvement suggestions across every project (template-only tool).

Purpose:
    Each project records "every project should do this" ideas in its own
    `docs/TEMPLATE_FEEDBACK.md`. With many projects those ideas are scattered, so this
    tool reads that file in every tracked project, renders open/all suggestion lists, and
    also supports appending new suggestions or updating row statuses (`待決定`, `已採用`,
    `不採用`) directly from the Master Hub without switching folders.

Usage:
    `scripts/collect_feedback.py` (see `entrypoints/feedback_cli.py`), `services/template_service.py`,
    and the Hub API/MCP/CLI call these functions.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from project_template.config.settings import TEMPLATE_ROOT
from project_template.packs.docs_templates import TEMPLATE_FEEDBACK
from project_template.services import update_all

logger = logging.getLogger(__name__)
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
    return not any(status.startswith(closed) for closed in CLOSED_STATUSES)


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


def _clean_cell(value: str) -> str:
    """Sanitize a table cell into a single Markdown-safe line with escaped pipes.

    Args:
        value: Raw text submitted by caller.

    Returns:
        Single-line text with unescaped `|` converted to `\\|`.
    """
    single = re.sub(r"[\r\n]+", " ", str(value or "").strip())
    return re.sub(r"(?<!\\)\|", r"\\|", single)


def _atomic_write(path: Path, text: str) -> None:
    """Write UTF-8 text atomically in the target's parent directory.

    Args:
        path: Destination file path.
        text: File content to persist.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as tmp:
        tmp.write(text)
        tmp_path = Path(tmp.name)
    os.replace(tmp_path, path)


def _validated_project_dir(project: Path) -> Path:
    """Verify `project` is the Master template or an active tracked template project.

    Args:
        project: Candidate project directory.

    Returns:
        Resolved directory path.

    Raises:
        ValueError: When outside valid template projects.
    """
    resolved = project.expanduser().resolve()
    if resolved == TEMPLATE_ROOT.resolve() or update_all.is_project(resolved):
        return resolved
    raise ValueError(f"只允許編輯母版或活躍追蹤專案的 TEMPLATE_FEEDBACK.md：{resolved}")


def _table_insert_index(lines: list[str]) -> int:
    """Locate the line index right after the feedback Markdown table.

    Args:
        lines: Lines of `docs/TEMPLATE_FEEDBACK.md`.

    Returns:
        Insertion index immediately after the last table row.
    """
    header_idx = next((i for i, ln in enumerate(lines) if ln.strip().startswith("| 日期")), -1)
    if header_idx == -1:
        return len(lines)
    idx = header_idx + 1
    while idx < len(lines) and lines[idx].strip().startswith("|"):
        idx += 1
    return idx


def add_suggestion(project: Path, text: str, source: str = "master-hub", status: str = "待決定") -> dict[str, Any]:
    """Append one feedback row into `<project>/docs/TEMPLATE_FEEDBACK.md`.

    Args:
        project: Target project root (or Master `TEMPLATE_ROOT`).
        text: Suggestion content (required).
        source: Source conversation or task label.
        status: Initial status (`待決定` by default).

    Returns:
        Dict describing the written suggestion (`project`, `file`, `date`, `text`, `source`, `status`).

    Raises:
        ValueError: When target is invalid or `text`/`status` is empty.
    """
    resolved = _validated_project_dir(project)
    clean_text, clean_status = _clean_cell(text), _clean_cell(status or "待決定")
    clean_source = _clean_cell(source) or "master-hub"
    if not clean_text or not clean_status:
        raise ValueError("建議內容與狀態不可為空")
    target = resolved / FEEDBACK_REL
    existing = target.read_text(encoding="utf-8") if target.is_file() else TEMPLATE_FEEDBACK
    if "| 日期" not in existing:
        existing = existing.rstrip() + "\n\n| 日期 | 建議 | 來源（對話 / 任務） | 狀態 |\n|---|---|---|---|\n"
    today = dt.date.today().isoformat()
    row_line = f"| {today} | {clean_text} | {clean_source} | {clean_status} |"
    lines = existing.splitlines()
    lines.insert(_table_insert_index(lines), row_line)
    _atomic_write(target, "\n".join(lines) + "\n")
    logger.info("added template feedback project=%s status=%s", resolved.name, clean_status)
    return {"project": resolved.name, "file": str(target), "date": today, "text": clean_text, "source": clean_source, "status": clean_status}


def update_suggestion_status(feedback_file: Path, match_text: str, new_status: str, match_date: str = "") -> dict[str, Any]:
    """Update the status cell of a matching row in `<project>/docs/TEMPLATE_FEEDBACK.md`.

    Args:
        feedback_file: Path to the target `docs/TEMPLATE_FEEDBACK.md`.
        match_text: Exact suggestion cell text to update.
        new_status: New status string (e.g. `已採用`, `不採用`, `待決定`).
        match_date: Optional date cell to disambiguate identical texts.

    Returns:
        Dict describing the updated row (`project`, `file`, `date`, `text`, `source`, `status`).

    Raises:
        ValueError: When the file is outside allowed projects, status is empty, or no row matches.
    """
    resolved = feedback_file.expanduser().resolve()
    if not resolved.is_file() or resolved.name != "TEMPLATE_FEEDBACK.md" or resolved.parent.name != "docs":
        raise ValueError(f"無效的改進建議檔案路徑：{resolved}")
    project = _validated_project_dir(resolved.parent.parent)
    clean_status = _clean_cell(new_status)
    if not clean_status:
        raise ValueError("新狀態不可為空")
    raw_needle, esc_needle = match_text.strip(), _clean_cell(match_text)
    lines = resolved.read_text(encoding="utf-8", errors="replace").splitlines()
    for idx, line in enumerate(lines):
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in CELL_SPLIT.split(line.strip().strip("|"))]
        if len(cells) < 4 or cells[0] == "日期" or set("".join(cells)) <= set("-: "):
            continue
        if cells[1] in (raw_needle, esc_needle) and (not match_date or cells[0] == match_date.strip()):
            lines[idx] = f"| {cells[0]} | {cells[1]} | {cells[2]} | {clean_status} |"
            _atomic_write(resolved, "\n".join(lines) + "\n")
            logger.info("updated feedback status project=%s status=%s", project.name, clean_status)
            return {"project": project.name, "file": str(resolved), "date": cells[0], "text": cells[1], "source": cells[2], "status": clean_status}
    raise ValueError(f"在 {resolved} 中找不到對應的建議列：{raw_needle}")
