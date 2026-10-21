#!/usr/bin/env python3
"""Local web page, JSON API and MCP server for the template (FastAPI; template-only tool).

Purpose:
    Everything the template does, without typing commands: create a project (name, location,
    data folder, stack, add-ons, skills …), migrate an old project, list projects and run doctor /
    check / setup on them, collect template feedback, and preview / apply the framework update.
    The same actions are available to AI tools in three ways (one implementation,
    `template_service.py`):
      - the page at http://127.0.0.1:8766 and its JSON API (OpenAPI at `/openapi.json`: Open WebUI
        can add it as an OpenAPI tool server; `tools/openwebui/project_template_tool.py` also works);
      - MCP over Streamable HTTP at `/mcp` (Open WebUI native MCP, HTTP MCP clients);
      - MCP over stdio: `python3 tools/template_mcp.py` (Claude Code, Antigravity, OpenCode, …).

Safety (same model as the projects' API, literature-fetch ADR-008):
    - Binds 127.0.0.1. Host must be 127.0.0.1 / localhost (`--allow-host host.docker.internal` for
      Open WebUI in Docker). Changes from a web page must come from this page or an allowed origin
      (default Open WebUI http://127.0.0.1:8080, which also gets CORS).
    - Changing endpoints and MCP tools need `confirm: true`; one job at a time; no push, no delete.

Dependencies:
    Runs with FastAPI + MCP. When they are missing it re-runs itself through `uv run --with ...`
    (a uv-managed cache, nothing installed on the host), so the command stays `python3 tools/web_ui.py`.

Usage:
    python3 tools/web_ui.py
    python3 tools/web_ui.py --port 8770 --no-browser --allow-host host.docker.internal
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys
import threading
import webbrowser

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))

from template_mcp import ensure_dependencies  # noqa: E402

if __name__ == "__main__":
    ensure_dependencies(Path(__file__).resolve())

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse, Response  # noqa: E402
from fastapi.routing import APIRoute  # noqa: E402
from mcp.server.transport_security import TransportSecuritySettings  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

import template_service as ts  # noqa: E402
from template_mcp import build_template_mcp  # noqa: E402

DEFAULT_PORT = 8766
OPEN_WEBUI = "http://127.0.0.1:8080"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


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


def started(title: str, steps: list, after=None) -> dict:
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


def add_guard(app: FastAPI, port: int, extra_hosts: list[str], origins: list[str]) -> None:
    """Accept local requests only; allow CORS for the configured origins (Open WebUI).

    Args:
        app: The application.
        port: Port the app listens on.
        extra_hosts: Extra Host names (e.g. host.docker.internal).
        origins: Web page origins allowed to make changes and use CORS.
    """
    names = ["127.0.0.1", "localhost", *extra_hosts]
    hosts = {*names, *(f"{h}:{port}" for h in names)}
    allowed = {f"http://127.0.0.1:{port}", f"http://localhost:{port}", *origins}

    @app.middleware("http")
    async def local_only(request: Request, call_next) -> Response:
        """Check Host and Origin.

        Args:
            request: Incoming request.
            call_next: The rest of the app.

        Returns:
            The response, or 403.
        """
        host = (request.headers.get("host") or "").lower()
        origin = request.headers.get("origin")
        if host not in hosts or (request.method not in SAFE_METHODS and origin and origin not in allowed):
            return JSONResponse({"detail": "only local requests from this page are allowed"}, status_code=403)
        return await call_next(request)

    if origins:
        app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["*"], allow_headers=["*"],
                           expose_headers=["Mcp-Session-Id"])


def create_app(port: int = DEFAULT_PORT, extra_hosts: list[str] | None = None, origins: list[str] | None = None) -> FastAPI:
    """Build the web app: page, JSON API, `/mcp`.

    Args:
        port: Port the app listens on (for the Host / Origin checks).
        extra_hosts: Extra Host names accepted.
        origins: Origins allowed to make changes (default: Open WebUI).

    Returns:
        The FastAPI application.
    """
    import contextlib

    extra_hosts = extra_hosts or []
    origins = [OPEN_WEBUI] if origins is None else origins
    mcp = build_template_mcp()
    names = ["127.0.0.1", "localhost", *extra_hosts]
    security = TransportSecuritySettings(allowed_hosts=[*names, *(f"{h}:*" for h in names)],
                                         allowed_origins=["http://127.0.0.1:*", "http://localhost:*", *origins])
    mcp_routes = mcp.streamable_http_app(streamable_http_path="/mcp", transport_security=security).routes

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI):
        """Run the MCP sessions while the app is up.

        Args:
            _app: The application.

        Yields:
            Control while running.
        """
        async with mcp.session_manager.run():
            yield

    app = FastAPI(title="Project template", version=ts.FRAMEWORK_VERSION, lifespan=lifespan,
                  generate_unique_id_function=operation_id,
                  description="Create, migrate and maintain projects. AI agents can also use MCP at /mcp.")
    add_guard(app, port, extra_hosts, origins)

    @app.exception_handler(ValueError)
    async def bad_request(_request: Request, exc: ValueError) -> JSONResponse:
        """Report invalid input.

        Args:
            _request: The request.
            exc: The error.

        Returns:
            400 with the message.
        """
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(RuntimeError)
    async def busy(_request: Request, exc: RuntimeError) -> JSONResponse:
        """Report that another job is running.

        Args:
            _request: The request.
            exc: The error.

        Returns:
            409 with the message.
        """
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(PermissionError)
    async def not_confirmed(_request: Request, exc: PermissionError) -> JSONResponse:
        """Report a change that was not confirmed.

        Args:
            _request: The request.
            exc: The error.

        Returns:
            428 with the message.
        """
        return JSONResponse({"detail": str(exc)}, status_code=428)

    register_routes(app)
    app.router.routes.extend(mcp_routes)
    return app


def register_routes(app: FastAPI) -> None:
    """Add the page and the JSON API.

    Args:
        app: The application.
    """

    @app.get("/", include_in_schema=False)
    def page() -> FileResponse:
        """Serve the page.

        Returns:
            index.html.
        """
        return FileResponse(TOOLS / "web" / "index.html")

    @app.get("/api/info")
    def describe_options() -> dict:
        """Template version, default folders, and the stacks / add-ons / skills that can be chosen.

        Returns:
            Settings and option lists.
        """
        return ts.info()

    @app.get("/api/projects")
    def list_projects(root: str = "") -> list[dict]:
        """List projects created from the template (version, uncommitted files, last commit).

        Args:
            root: Absolute folder to scan; empty = the folder that contains the template.

        Returns:
            One entry per project.
        """
        return ts.list_projects(ts.resolve_root(root))

    @app.get("/api/overview")
    def project_overview(root: str = "") -> list[dict]:
        """Every tracked project: framework version, uncommitted files, unpushed commits, open suggestions, AI tools.

        Args:
            root: Folder to scan; empty = the folder that contains the template (registry entries are always added).

        Returns:
            One status per project (local only, nothing changes).
        """
        return ts.overview(ts.resolve_root(root))

    @app.get("/api/feedback")
    def collect_feedback(root: str = "", all: str = "") -> dict:  # noqa: A002 - query name used by the page
        """Template-improvement suggestions from every project's docs/TEMPLATE_FEEDBACK.md.

        Args:
            root: Folder to scan; empty = default.
            all: `1` to include adopted / rejected suggestions.

        Returns:
            Number of projects scanned and the suggestions.
        """
        return ts.feedback(ts.resolve_root(root), all == "1")

    @app.get("/api/job")
    def get_job_status() -> dict | None:
        """The current or last job: title, state, output and result.

        Returns:
            The job, or null.
        """
        return ts.job_view(ts.RUNNER.current)

    @app.get("/api/dirs", include_in_schema=False)
    def list_folders(path: str = "") -> dict:
        """Sub-folders of a folder (built-in folder browser).

        Args:
            path: Folder to list; empty = home.

        Returns:
            Path, parent and sub-folder names.
        """
        folder = ts.require_dir(path or str(Path.home()), "資料夾")
        return {"path": str(folder), "parent": str(folder.parent),
                "dirs": sorted(p.name for p in folder.iterdir() if p.is_dir() and not p.name.startswith("."))}

    @app.post("/api/data-preview")
    def preview_data_folder(body: DataPreviewIn) -> dict:
        """Where a new project's data folder will be and how DATA_DIR is stored.

        Args:
            body: Name, location and optional data folder.

        Returns:
            Absolute path, stored value and where it is written.
        """
        return ts.data_preview(body.model_dump())

    @app.post("/api/pick-folder", include_in_schema=False)
    def pick_folder(body: PickIn) -> dict:
        """Open the macOS folder dialog.

        Args:
            body: Dialog prompt and start folder.

        Returns:
            The chosen path (empty when cancelled).
        """
        return {"path": ts.pick_folder(body.prompt, body.start)}

    @app.post("/api/reveal", include_in_schema=False)
    def reveal(body: dict) -> dict:
        """Show a folder in Finder.

        Args:
            body: `path` of the folder.

        Returns:
            `ok`.
        """
        subprocess.run(["open", str(ts.require_dir(body.get("path", ""), "資料夾"))], check=False)
        return {"ok": True}

    register_action_routes(app)


def register_action_routes(app: FastAPI) -> None:
    """Add the endpoints that start jobs.

    Args:
        app: The application.
    """

    @app.post("/api/create", status_code=202)
    def create_project(body: CreateIn) -> dict:
        """Create a project (and optionally doctor --fix / setup --install / check). Needs confirm=true.

        Args:
            body: Project settings.

        Returns:
            The started job and its commands.
        """
        need_confirm(body.confirm, "建立專案")
        return started(*ts.create_steps(body.model_dump()))

    @app.post("/api/migrate", status_code=202)
    def migrate_project(body: MigrateIn) -> dict:
        """Migrate an old project into a new folder (the old one is not changed). Needs confirm=true.

        Args:
            body: Migration settings.

        Returns:
            The started job and its commands.
        """
        need_confirm(body.confirm, "遷移專案")
        return started(*ts.migrate_steps(body.model_dump()))

    @app.post("/api/project-command", status_code=202)
    def run_project_command(body: CommandIn) -> dict:
        """Run `agentctl <command>` in a project; doctor-fix and setup need confirm=true.

        Args:
            body: Project folder, command and confirmation.

        Returns:
            The started job and its commands.
        """
        if body.command in ("doctor-fix", "setup"):
            need_confirm(body.confirm, f"agentctl {body.command}")
        return started(*ts.project_command_steps(body.model_dump()))

    @app.post("/api/push", status_code=202)
    def push_project(body: CommandIn) -> dict:
        """Push a project's commits to its GitHub upstream. Needs confirm=true (the user agreed).

        Args:
            body: Project folder and confirmation (`command` is ignored).

        Returns:
            The started job and its commands.
        """
        need_confirm(body.confirm, "推送到 GitHub")
        return started(*ts.push_steps(body.model_dump()))

    @app.post("/api/registry/forget", include_in_schema=False)
    def forget_project(body: dict) -> dict:
        """Remove a moved or deleted project from the overview (the folder itself is not touched).

        Args:
            body: `path` as shown in the overview.

        Returns:
            Whether an entry was removed.
        """
        return {"removed": ts.project_registry.forget(str(body.get("path", "")))}

    @app.post("/api/update/preview", status_code=202)
    def preview_framework_update(body: FolderIn) -> dict:
        """Preview the framework update of every project (nothing changes); result in /api/job.

        Args:
            body: Folder to scan.

        Returns:
            The started job.
        """
        root = ts.resolve_root(body.root)
        return started("更新預覽", [], after=lambda job: setattr(job, "result", ts.update_preview(root)))

    @app.post("/api/update/apply", status_code=202)
    def apply_framework_update(body: UpdateIn) -> dict:
        """Update every updatable project (edits kept as *.template, no push). Needs confirm=true.

        Args:
            body: Folder, commit option and confirmation.

        Returns:
            The started job and its commands.
        """
        need_confirm(body.confirm, "更新框架")
        root = ts.resolve_root(body.root)
        return started(*ts.update_apply_steps(root, body.commit), after=lambda job: setattr(job, "result", ts.update_preview(root)))


def main(argv: list[str] | None = None) -> int:
    """Start the local server and open the page.

    Args:
        argv: Command-line arguments; defaults to `sys.argv[1:]`.

    Returns:
        Process exit code.
    """
    import uvicorn

    parser = argparse.ArgumentParser(description="母版的本機網頁、JSON API 與 MCP（只綁 127.0.0.1）")
    parser.add_argument("--port", type=int, default=int(os.environ.get("TEMPLATE_UI_PORT", DEFAULT_PORT)))
    parser.add_argument("--allow-host", action="append", default=[], help="額外允許的 Host（Open WebUI 在 Docker：host.docker.internal）")
    parser.add_argument("--allow-origin", action="append", default=None, help=f"可從瀏覽器呼叫的網頁（預設 {OPEN_WEBUI}）")
    parser.add_argument("--no-browser", action="store_true", help="不自動打開瀏覽器")
    args = parser.parse_args(argv)
    url = f"http://127.0.0.1:{args.port}"
    print(f"🌐 母版網頁：{url}　MCP：{url}/mcp　API 文件：{url}/docs（Ctrl+C 結束）", file=sys.stderr)
    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    uvicorn.run(create_app(args.port, args.allow_host, args.allow_origin), host="127.0.0.1", port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
