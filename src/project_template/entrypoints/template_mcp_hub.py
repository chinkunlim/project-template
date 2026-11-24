"""MCP tools for Master Hub web launcher, project Graphify refresh, and feedback editing.

Purpose:
    Groups the Master-Child linkage and Web Launcher Hub MCP tools exported through
    `entrypoints/template_mcp.py` so `template_mcp.py` remains concise and modular.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from project_template.services import feedback as feedback_svc
from project_template.services import template_service as ts
from project_template.services import web_launcher as wl

logger = logging.getLogger(__name__)


def list_web_services(folder: str = "") -> list[dict[str, Any]]:
    """List every tracked project with a FastAPI web service and its live listening state. Read only.

    Args:
        folder: Projects folder to scan; empty = template's parent folder plus registry.

    Returns:
        List of project web descriptors (`name`, `port`, `url`, `running`, `managed`, `pid`).
    """
    return wl.list_web_services(ts.resolve_root(folder))


def start_project_web(project: str, folder: str = "", confirm: bool = False) -> dict[str, Any] | str:
    """Start one project's FastAPI web server in the background until ready. Needs confirm=True.

    Args:
        project: Tracked project name or absolute path.
        folder: Projects folder when passing project name; empty = default.
        confirm: Must be True after asking the user to confirm.

    Returns:
        Confirmation prompt when `confirm=False`, or updated status dictionary with `url`.
    """
    target = wl.resolve_project_path(project, ts.resolve_root(folder))
    spec = wl.discover_web_service(target)
    if spec is None:
        raise ValueError(f"`{target.name}` 沒有設定網頁服務")
    if not confirm:
        cmd_str = " ".join(spec.command)
        return (
            f"Not run yet — start `{spec.name}` web server at {spec.url} via `{cmd_str}` "
            f"(in `{spec.path}`). Ask the user and call again with confirm=True."
        )
    return wl.start_project_web(target)


def stop_project_web(project: str, folder: str = "", confirm: bool = False) -> dict[str, Any] | str:
    """Stop one Hub-managed child project's web server cleanly. Needs confirm=True.

    Args:
        project: Tracked project name or absolute path.
        folder: Projects folder when passing project name; empty = default.
        confirm: Must be True after asking the user to confirm.

    Returns:
        Confirmation prompt when `confirm=False`, or stop result dictionary.
    """
    target = wl.resolve_project_path(project, ts.resolve_root(folder))
    if not confirm:
        return f"Not run yet — stop `{target.name}` web server. Call again with confirm=True after asking the user."
    return wl.stop_project_web(target)


def stop_all_project_webs(folder: str = "", confirm: bool = False) -> dict[str, Any] | str:
    """Stop every Hub-managed child project web server to free host memory. Needs confirm=True.

    Args:
        folder: Projects folder; empty = default.
        confirm: Must be True after asking the user to confirm.

    Returns:
        Confirmation prompt when `confirm=False`, or summary of stopped/skipped services.
    """
    root = ts.resolve_root(folder)
    if not confirm:
        running = [s["name"] for s in wl.list_web_services(root) if s["running"] and s["managed"]]
        return f"Not run yet — stop managed web servers: {', '.join(running) or 'none'}. Call with confirm=True after user agrees."
    return wl.stop_all_project_webs(root)


def get_project_web_logs(project: str, lines: int = 80, folder: str = "") -> dict[str, Any]:
    """Read trailing startup/runtime log lines for one child project's web server. Read only.

    Args:
        project: Tracked project name or absolute path.
        lines: Maximum trailing log lines to return (default 80).
        folder: Projects folder when passing project name; empty = default.

    Returns:
        Dictionary with `name`, `log_file`, and `lines`.
    """
    target = wl.resolve_project_path(project, ts.resolve_root(folder))
    return wl.read_web_logs(target, lines=lines)


def refresh_project_graphify(project: str = "", folder: str = "") -> str:
    """Update AST dependency graphs (`agentctl graph`) and Graphify graphs (`graphify update .`) from Master.

    Args:
        project: Tracked project name, `master`, or absolute path; empty = all tracked projects.
        folder: Projects folder when passing name or empty; empty = default projects folder.

    Returns:
        Job status summary and trailing output lines.
    """
    root = ts.resolve_root(folder)
    title, steps = ts.graphify_steps({"project": project}, root)
    job = ts.wait_for(ts.RUNNER.start(title, steps, keep_going=True))
    logger.info("mcp refresh_project_graphify title=%s state=%s", job.title, job.state)
    return f"{job.title}: {job.state}\n" + "\n".join(job.log[-40:])


def add_template_feedback(
    project: str,
    text: str,
    source: str = "master-mcp",
    confirm: bool = False,
) -> dict[str, Any] | str:
    """Append a suggestion to a tracked project's (or Master's) `docs/TEMPLATE_FEEDBACK.md`. Needs confirm=True.

    Args:
        project: Tracked project name, `master`, or absolute project folder path.
        text: Suggestion text to record.
        source: Source conversation or task reference.
        confirm: Must be True after user approval.

    Returns:
        Confirmation prompt when `confirm=False`, or inserted row details.
    """
    target = ts.resolve_feedback_target(project, ts.resolve_root(""))
    if not confirm:
        return (
            f"Not run yet — append suggestion to `{target.name}/docs/TEMPLATE_FEEDBACK.md`: "
            f"{text!r}. Call again with confirm=True after user approval."
        )
    return feedback_svc.add_suggestion(target, text, source=source)


def update_feedback_status(
    file: str,
    text: str,
    status: str,
    confirm: bool = False,
) -> dict[str, Any] | str:
    """Update one suggestion's status in `<project>/docs/TEMPLATE_FEEDBACK.md`. Needs confirm=True.

    Args:
        file: Path to `<project>/docs/TEMPLATE_FEEDBACK.md`.
        text: Exact suggestion cell text to match.
        status: New status (`待決定`, `已採用`, `不採用`).
        confirm: Must be True after user approval.

    Returns:
        Confirmation prompt when `confirm=False`, or updated row details.
    """
    if not confirm:
        return (
            f"Not run yet — set status to {status!r} for {text!r} in `{file}`. "
            "Call again with confirm=True after user approval."
        )
    return feedback_svc.update_suggestion_status(Path(file), text, status)


HUB_TOOLS = (
    list_web_services,
    start_project_web,
    stop_project_web,
    stop_all_project_webs,
    get_project_web_logs,
    refresh_project_graphify,
    add_template_feedback,
    update_feedback_status,
)
