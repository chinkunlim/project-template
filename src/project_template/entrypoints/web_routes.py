"""Routes of the template's local web page and JSON API (registered by `web_ui.create_app()`).

Purpose:
    Request models, the page and every `/api/...` endpoint. Each endpoint only translates the
    request into a `services/template_service.py` call, so the page, the JSON API (OpenAPI for
    Open WebUI) and the MCP tools behave the same. Endpoints that change files need `confirm: true`;
    they start a background job (one at a time) and return its commands.
"""
from __future__ import annotations

import subprocess
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field

from project_template.adapters import project_registry
from project_template.config.settings import WEB_PAGE
from project_template.services import template_service as ts

router = APIRouter()


class FolderIn(BaseModel):
    """A folder to scan for projects."""

    root: str = Field(default="", description="Absolute folder; empty = the folder that contains the template")


class DataPreviewIn(BaseModel):
    """Name and location of a new project, to preview its data folder."""

    name: str = ""
    parent: str = ""
    data_dir: str = ""


class CreateIn(BaseModel):
    """Settings for a new project."""

    name: str = Field(description="Project and folder name")
    parent: str = Field(default="", description="Absolute folder to create the project in")
    data_dir: str = Field(default="", description="Absolute data folder; empty = projects-data/<name>")
    stack: str = "python"
    addons: list[str] = Field(default_factory=list, description="web, gas, mobile, api, db, ollama, evals")
    skills: list[str] = Field(default_factory=list)
    description: str = ""
    license: str = "none"
    timezone: str = ""
    doctor: bool = True
    setup: bool = False
    check: bool = False
    confirm: bool = Field(default=False, description="Must be true: the user agreed to create the project")


class MigrateIn(BaseModel):
    """Settings for migrating an old project."""

    source: str = Field(description="Absolute folder of the old project")
    name: str = ""
    parent: str = ""
    data_dir: str = ""
    mode: str = Field(default="maintain", description="maintain or develop")
    stack: str = ""
    addons: list[str] = Field(default_factory=list)
    confirm: bool = Field(default=False, description="Must be true: the user agreed to migrate")


class CommandIn(BaseModel):
    """A framework command to run in one project."""

    path: str = Field(description="Absolute project folder")
    command: str = Field(default="status", description="status, doctor, check, doctor-fix or setup")
    confirm: bool = Field(default=False, description="Needed for doctor-fix and setup")


class UpdateIn(FolderIn):
    """Apply the framework update."""

    commit: bool = True
    confirm: bool = Field(default=False, description="Must be true: the user agreed to the preview")


class PickIn(BaseModel):
    """Native folder dialog."""

    prompt: str = "選擇資料夾"
    start: str = ""


def operation_id(route: APIRoute) -> str:
    """Use the route function name as OpenAPI operationId (clean tool names for Open WebUI).

    Args:
        route: A FastAPI route.

    Returns:
        The function name.
    """
    return route.name


def need_confirm(confirm: bool, what: str) -> None:
    """Refuse a change that the user has not approved.

    Args:
        confirm: The request's `confirm` flag.
        what: The action, for the error message.

    Raises:
        PermissionError: When `confirm` is false.
    """
    if not confirm:
        raise PermissionError(f"{what} 會修改檔案：先讓使用者確認，再用 confirm=true 呼叫")


def started(title: str, steps: list[Any], after: ts.AfterJob | None = None) -> dict[str, Any]:
    """Start a background job.

    Args:
        title: Job title.
        steps: `(argv, cwd)` pairs.
        after: Optional result callback.

    Returns:
        Job id, title and the commands it runs.
    """
    import shlex

    job = ts.RUNNER.start(title, steps, after=after)
    return {"id": job.id, "title": job.title, "commands": [shlex.join(a) for a, _ in steps]}


async def bad_request(_request: Request, exc: Exception) -> Response:
    """Report invalid input.

    Args:
        _request: The request.
        exc: The error.

    Returns:
        400 with the message.
    """
    return JSONResponse({"detail": str(exc)}, status_code=400)


async def busy(_request: Request, exc: Exception) -> Response:
    """Report that another job is running.

    Args:
        _request: The request.
        exc: The error.

    Returns:
        409 with the message.
    """
    return JSONResponse({"detail": str(exc)}, status_code=409)


async def not_confirmed(_request: Request, exc: Exception) -> Response:
    """Report a change that was not confirmed.

    Args:
        _request: The request.
        exc: The error.

    Returns:
        428 with the message.
    """
    return JSONResponse({"detail": str(exc)}, status_code=428)


# Errors raised by the services, mapped to HTTP answers.
ERROR_HANDLERS: dict[type[Exception], Callable[[Request, Exception], Awaitable[Response]]] = {
    ValueError: bad_request, RuntimeError: busy, PermissionError: not_confirmed,
}


@router.get("/", include_in_schema=False)
def page() -> FileResponse:
    """Serve the page.

    Returns:
        index.html.
    """
    return FileResponse(WEB_PAGE)


@router.get("/api/info")
def describe_options() -> dict[str, Any]:
    """Template version, default folders, and the stacks / add-ons / skills that can be chosen.

    Returns:
        Settings and option lists.
    """
    return ts.info()


@router.get("/api/projects")
def list_projects(root: str = "") -> list[dict[str, Any]]:
    """List projects created from the template (version, uncommitted files, last commit).

    Args:
        root: Absolute folder to scan; empty = the folder that contains the template.

    Returns:
        One entry per project.
    """
    return ts.list_projects(ts.resolve_root(root))


@router.get("/api/overview")
def project_overview(root: str = "") -> list[dict[str, Any]]:
    """Every tracked project: framework version, uncommitted files, unpushed commits, open suggestions, AI tools.

    Args:
        root: Folder to scan; empty = the folder that contains the template (registry entries are always added).

    Returns:
        One status per project (local only, nothing changes).
    """
    return ts.overview(ts.resolve_root(root))


@router.get("/api/feedback")
def collect_feedback(root: str = "", all: str = "") -> dict[str, Any]:  # noqa: A002 - query name used by the page
    """Template-improvement suggestions from every project's docs/TEMPLATE_FEEDBACK.md.

    Args:
        root: Folder to scan; empty = default.
        all: `1` to include adopted / rejected suggestions.

    Returns:
        Number of projects scanned and the suggestions.
    """
    return ts.feedback(ts.resolve_root(root), all == "1")


@router.get("/api/job")
def get_job_status() -> dict[str, Any] | None:
    """The current or last job: title, state, output and result.

    Returns:
        The job, or null.
    """
    return ts.job_view(ts.RUNNER.current)


@router.get("/api/dirs", include_in_schema=False)
def list_folders(path: str = "") -> dict[str, Any]:
    """Sub-folders of a folder (built-in folder browser).

    Args:
        path: Folder to list; empty = home.

    Returns:
        Path, parent and sub-folder names.
    """
    folder = ts.require_dir(path or str(Path.home()), "資料夾")
    return {"path": str(folder), "parent": str(folder.parent),
            "dirs": sorted(p.name for p in folder.iterdir() if p.is_dir() and not p.name.startswith("."))}


@router.post("/api/data-preview")
def preview_data_folder(body: DataPreviewIn) -> dict[str, Any]:
    """Where a new project's data folder will be and how DATA_DIR is stored.

    Args:
        body: Name, location and optional data folder.

    Returns:
        Absolute path, stored value and where it is written.
    """
    return ts.data_preview(body.model_dump())


@router.post("/api/pick-folder", include_in_schema=False)
def pick_folder(body: PickIn) -> dict[str, Any]:
    """Open the macOS folder dialog.

    Args:
        body: Dialog prompt and start folder.

    Returns:
        The chosen path (empty when cancelled).
    """
    return {"path": ts.pick_folder(body.prompt, body.start)}


@router.post("/api/reveal", include_in_schema=False)
def reveal(body: dict[str, Any]) -> dict[str, Any]:
    """Show a folder in Finder.

    Args:
        body: `path` of the folder.

    Returns:
        `ok`.
    """
    subprocess.run(["open", str(ts.require_dir(body.get("path", ""), "資料夾"))], check=False)
    return {"ok": True}


@router.post("/api/create", status_code=202)
def create_project(body: CreateIn) -> dict[str, Any]:
    """Create a project (and optionally doctor --fix / setup --install / check). Needs confirm=true.

    Args:
        body: Project settings.

    Returns:
        The started job and its commands.
    """
    need_confirm(body.confirm, "建立專案")
    return started(*ts.create_steps(body.model_dump()))


@router.post("/api/migrate", status_code=202)
def migrate_project(body: MigrateIn) -> dict[str, Any]:
    """Migrate an old project into a new folder (the old one is not changed). Needs confirm=true.

    Args:
        body: Migration settings.

    Returns:
        The started job and its commands.
    """
    need_confirm(body.confirm, "遷移專案")
    return started(*ts.migrate_steps(body.model_dump()))


@router.post("/api/project-command", status_code=202)
def run_project_command(body: CommandIn) -> dict[str, Any]:
    """Run `agentctl <command>` in a project; doctor-fix and setup need confirm=true.

    Args:
        body: Project folder, command and confirmation.

    Returns:
        The started job and its commands.
    """
    if body.command in ("doctor-fix", "setup"):
        need_confirm(body.confirm, f"agentctl {body.command}")
    return started(*ts.project_command_steps(body.model_dump()))


@router.post("/api/push", status_code=202)
def push_project(body: CommandIn) -> dict[str, Any]:
    """Push a project's commits to its GitHub upstream. Needs confirm=true (the user agreed).

    Args:
        body: Project folder and confirmation (`command` is ignored).

    Returns:
        The started job and its commands.
    """
    need_confirm(body.confirm, "推送到 GitHub")
    return started(*ts.push_steps(body.model_dump()))


@router.post("/api/registry/forget", include_in_schema=False)
def forget_project(body: dict[str, Any]) -> dict[str, Any]:
    """Remove a moved or deleted project from the overview (the folder itself is not touched).

    Args:
        body: `path` as shown in the overview.

    Returns:
        Whether an entry was removed.
    """
    return {"removed": project_registry.forget(str(body.get("path", "")))}


@router.post("/api/update/preview", status_code=202)
def preview_framework_update(body: FolderIn) -> dict[str, Any]:
    """Preview the framework update of every project (nothing changes); result in /api/job.

    Args:
        body: Folder to scan.

    Returns:
        The started job.
    """
    root = ts.resolve_root(body.root)
    return started("更新預覽", [], after=lambda job: setattr(job, "result", ts.update_preview(root)))


@router.post("/api/update/apply", status_code=202)
def apply_framework_update(body: UpdateIn) -> dict[str, Any]:
    """Update every updatable project (edits kept as *.template, no push). Needs confirm=true.

    Args:
        body: Folder, commit option and confirmation.

    Returns:
        The started job and its commands.
    """
    need_confirm(body.confirm, "更新框架")
    root = ts.resolve_root(body.root)
    return started(*ts.update_apply_steps(root, body.commit), after=lambda job: setattr(job, "result", ts.update_preview(root)))
