"""HTTP routes for the integrated project Web Launcher Hub (`/api/web/*`).

Purpose:
    Exposes read and control endpoints for child projects' FastAPI servers (`services/web_launcher.py`),
    registered into the main FastAPI app in `entrypoints/web_ui.py`.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from project_template.entrypoints.web_routes import need_confirm
from project_template.services import template_service as ts
from project_template.services import web_launcher as wl

logger = logging.getLogger(__name__)
router = APIRouter()


class WebActionIn(BaseModel):
    """Target project selector for starting or stopping a child web server."""

    project: str = Field(default="", description="Tracked project name or absolute path")
    path: str = Field(default="", description="Absolute project path (alternative to project)")
    root: str = Field(default="", description="Projects root folder; empty = default")
    confirm: bool = Field(default=False, description="Must be true after the user agreed")


class WebStopAllIn(BaseModel):
    """Request model for stopping all Hub-managed child web servers."""

    root: str = Field(default="", description="Projects root folder; empty = default")
    confirm: bool = Field(default=False, description="Must be true after the user agreed")


@router.get("/api/web/services")
def list_web_services(root: str = "") -> list[dict[str, Any]]:
    """List every tracked project with a FastAPI web service and its live listening state.

    Args:
        root: Optional folder to scan; empty = template's parent folder plus registry.

    Returns:
        List of service descriptors with `port`, `url`, `running`, `managed`, and `pid`.
    """
    return wl.list_web_services(ts.resolve_root(root))


@router.post("/api/web/start")
def start_project_web(body: WebActionIn) -> dict[str, Any]:
    """Start one project's FastAPI web server in the background and wait until ready. Needs confirm=true.

    Args:
        body: Project selector and confirmation flag.

    Returns:
        Updated service descriptor with `url`, `started`, and `already_running`.
    """
    need_confirm(body.confirm, "啟動專案網頁")
    target = wl.resolve_project_path(body.path or body.project, ts.resolve_root(body.root))
    try:
        return wl.start_project_web(target)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/api/web/stop")
def stop_project_web(body: WebActionIn) -> dict[str, Any]:
    """Stop one Hub-managed child project web server. Needs confirm=true.

    Args:
        body: Project selector and confirmation flag.

    Returns:
        Stop result with `stopped`, `running`, and `message`.
    """
    need_confirm(body.confirm, "停止專案網頁")
    target = wl.resolve_project_path(body.path or body.project, ts.resolve_root(body.root))
    try:
        return wl.stop_project_web(target)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/api/web/stop-all")
def stop_all_project_webs(body: WebStopAllIn) -> dict[str, Any]:
    """Stop every Hub-managed child project web server to free memory. Needs confirm=true.

    Args:
        body: Root folder and confirmation flag.

    Returns:
        Summary of `stopped` and `skipped` services.
    """
    need_confirm(body.confirm, "停止全部子專案網頁")
    return wl.stop_all_project_webs(ts.resolve_root(body.root))


@router.get("/api/web/logs")
def get_project_web_logs(project: str = "", path: str = "", root: str = "", lines: int = 80) -> dict[str, Any]:
    """Return trailing launcher log lines for one child project's web server.

    Args:
        project: Project name or path.
        path: Alternative project path parameter.
        root: Projects root folder; empty = default.
        lines: Number of trailing lines to return.

    Returns:
        Dictionary with `name`, `log_file`, and `lines`.
    """
    target = wl.resolve_project_path(path or project, ts.resolve_root(root))
    return wl.read_web_logs(target, lines=lines)
