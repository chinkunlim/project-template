"""Local web page, JSON API and MCP server for the template (FastAPI; template-only tool).

Purpose:
    Everything the template does, without typing commands: create a project (name, location,
    data folder, stack, add-ons, skills …), migrate an old project, list projects and run doctor /
    check / setup on them, collect template feedback, and preview / apply the framework update.
    The same actions are available to AI tools in three ways (one implementation,
    `services/template_service.py`):
      - the page at http://127.0.0.1:8766 and its JSON API (OpenAPI at `/openapi.json`: Open WebUI
        can add it as an OpenAPI tool server; `entrypoints/openwebui_tool.py` also works);
      - MCP over Streamable HTTP at `/mcp` (Open WebUI native MCP, HTTP MCP clients);
      - MCP over stdio: `python3 scripts/template_mcp.py` (Claude Code, Antigravity, OpenCode, …).

Safety (same model as the projects' API, literature-fetch ADR-008):
    - Binds 127.0.0.1. Host must be 127.0.0.1 / localhost (`--allow-host host.docker.internal` for
      Open WebUI in Docker). Changes from a web page must come from this page or an allowed origin
      (default Open WebUI http://127.0.0.1:8080, which also gets CORS).
    - Changing endpoints and MCP tools need `confirm: true`; one job at a time; no push, no delete.

Dependencies:
    Runs with FastAPI + MCP. When they are missing it re-runs itself through `uv run --with ...`
    (a uv-managed cache, nothing installed on the host), so the command stays `python3 scripts/web_ui.py`.

Usage:
    python3 scripts/web_ui.py
    python3 scripts/web_ui.py --port 8770 --no-browser --allow-host host.docker.internal
"""
from __future__ import annotations

import argparse
import contextlib
import sys
import threading
import webbrowser
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from mcp.server.transport_security import TransportSecuritySettings

from project_template.config.framework import FRAMEWORK_VERSION
from project_template.config.settings import env_value
from project_template.entrypoints.template_mcp import build_template_mcp
from project_template.entrypoints.web_routes import ERROR_HANDLERS, operation_id, router

DEFAULT_PORT = 8766
OPEN_WEBUI = "http://127.0.0.1:8080"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


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
    async def local_only(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
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


def mcp_lifespan(mcp: Any) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    """Build the app lifespan that runs the MCP sessions while the app is up.

    Args:
        mcp: The template MCP server.

    Returns:
        A lifespan function for `FastAPI(lifespan=...)`.
    """

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        """Run the MCP session manager.

        Args:
            _app: The application.

        Yields:
            Control while running.
        """
        async with mcp.session_manager.run():
            yield

    return lifespan


def create_app(port: int = DEFAULT_PORT, extra_hosts: list[str] | None = None, origins: list[str] | None = None) -> FastAPI:
    """Build the web app: page, JSON API, `/mcp`.

    Args:
        port: Port the app listens on (for the Host / Origin checks).
        extra_hosts: Extra Host names accepted.
        origins: Origins allowed to make changes (default: Open WebUI).

    Returns:
        The FastAPI application.
    """
    extra_hosts = extra_hosts or []
    origins = [OPEN_WEBUI] if origins is None else origins
    mcp = build_template_mcp()
    names = ["127.0.0.1", "localhost", *extra_hosts]
    security = TransportSecuritySettings(allowed_hosts=[*names, *(f"{h}:*" for h in names)],
                                         allowed_origins=["http://127.0.0.1:*", "http://localhost:*", *origins])
    mcp_routes = mcp.streamable_http_app(streamable_http_path="/mcp", transport_security=security).routes

    app = FastAPI(title="Project template", version=FRAMEWORK_VERSION, lifespan=mcp_lifespan(mcp),
                  generate_unique_id_function=operation_id,
                  description="Create, migrate and maintain projects. AI agents can also use MCP at /mcp.")
    add_guard(app, port, extra_hosts, origins)
    for error, handler in ERROR_HANDLERS.items():
        app.add_exception_handler(error, handler)
    app.include_router(router)
    app.router.routes.extend(mcp_routes)
    return app


def main(argv: list[str] | None = None) -> int:
    """Start the local server and open the page.

    Args:
        argv: Command-line arguments; defaults to `sys.argv[1:]`.

    Returns:
        Process exit code.
    """
    import uvicorn

    parser = argparse.ArgumentParser(description="母版的本機網頁、JSON API 與 MCP（只綁 127.0.0.1）")
    parser.add_argument("--port", type=int, default=int(env_value("TEMPLATE_UI_PORT") or DEFAULT_PORT))
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

