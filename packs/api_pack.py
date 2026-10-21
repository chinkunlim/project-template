#!/usr/bin/env python3
"""HTTP API add-on (`--with api`): FastAPI app factory, schemas, server entrypoint and tests.

Purpose:
    New projects use FastAPI for every HTTP server. Layout:
      - `src/<pkg>/entrypoints/http/schemas.py` : pydantic request/response models (input is
        validated here, at the edge, then converted to domain objects)
      - `src/<pkg>/entrypoints/http/app.py`     : `create_app(config)` builds routes; with
        `--with web` it also serves `web/`; with `--with db` it stores greetings via the repository
      - `src/<pkg>/entrypoints/http/middleware.py`: request id (`X-Request-ID`) on every log line,
        one access line per request (method, path, status, duration), errors with traceback
      - `src/<pkg>/entrypoints/http/server.py`  : `uv run <name>-server`, binds 127.0.0.1 only
      - `src/<pkg>/entrypoints/mcp_server.py`  : MCP server (same services) for AI agents: stdio
        (`uv run <name>-mcp`) and Streamable HTTP at `/mcp` on the web server
      - `tests/test_api.py`, `tests/test_mcp.py`: TestClient and in-process MCP tests
      - AI-tool configs and docs/INTEGRATIONS.md (`packs/integrations_pack.py`)
"""

from __future__ import annotations

from pathlib import Path

from packs.common import write_file as _write
from packs.integrations_pack import scaffold_integrations

API_DEPENDENCIES = ["fastapi>=0.115", "mcp>=2.3", "pydantic>=2.7", "starlette>=0.40", "uvicorn>=0.30"]
API_DEV_DEPENDENCIES = ["httpx>=0.27"]

SCHEMAS_PY = '''"""HTTP request and response schemas (validated at the edge, then turned into domain objects)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class GreetingIn(BaseModel):
    """Request body of `POST /greetings`.

    Attributes:
        user_name: Name to greet (1-100 characters).
    """

    user_name: str = Field(min_length=1, max_length=100)


class GreetingOut(BaseModel):
    """Response body of the greeting endpoints.

    Attributes:
        message: Greeting text.
        environment: Environment that produced it.
    """

    message: str
    environment: str
'''

APP_HEADER = '''"""FastAPI application factory: routes{extra_doc}.

Also mounts MCP at `/mcp` and installs the local-only guard.
`create_app()` receives its dependencies as arguments, so tests can pass a test config{test_doc}.
The same features are exposed three ways from one services layer: this JSON API (OpenAPI at
`/openapi.json`, usable as an Open WebUI tool server), MCP for AI agents (`/mcp`, and stdio via
`entrypoints/mcp_server.py`), and the web page when `web/` exists.
"""

from __future__ import annotations

{imports}
{web_const}

def operation_id(route: APIRoute) -> str:
    """Use the route function's name as its OpenAPI operationId (clean tool names for AI tools).

    Args:
        route: A FastAPI route.

    Returns:
        The name, e.g. `greet`.
    """
    return route.name


def create_app(config: AppConfig{factory_param}) -> FastAPI:
    """Build the FastAPI application.

    Args:
        config: Application settings.{factory_doc}

    Returns:
        The configured application.
    """
{factory_init}    mcp = build_mcp_server(config{factory_arg})
    app = FastAPI(
        title="{name}",
        version="0.1.0",
        lifespan=mcp_lifespan(mcp),
        generate_unique_id_function=operation_id,
        description="Local API of {name}. AI agents can use the same features over MCP at /mcp.",
    )
    add_request_logging(app)
    add_local_only_guard(app, config)
    app.include_router(build_greeting_router(config{factory_arg}))
{history_include}    app.router.routes.extend(mcp_http_routes(mcp, config))  # before the static catch-all below
{web_mount}    return app


def build_greeting_router(config: AppConfig{factory_param_required}) -> APIRouter:
    """Create the health and greeting routes.

    Args:
        config: Application settings.{factory_doc_required}

    Returns:
        Router with `/health` and `POST /greetings`.
    """
    router = APIRouter()

    @router.get("/health")
    def health() -> dict[str, str]:
        """Liveness check.

        Returns:
            Status and environment name.
        """
        return {{"status": "ok", "environment": config.app_env}}

    @router.post("/greetings", response_model=GreetingOut)
    def greet(body: GreetingIn) -> GreetingOut:
        """Create a greeting{save_doc}.

        Args:
            body: Validated request body.

        Returns:
            The greeting.
        """
        result = create_greeting(GreetingRequest(user_name=body.user_name), config)
{save_code}        return GreetingOut(message=result.message, environment=result.environment)

    return router
{history_router}'''

HISTORY_ROUTER = '''

def build_history_router(config: AppConfig, factory: sessionmaker[Session]) -> APIRouter:
    """Create the route that lists stored greetings.

    Args:
        config: Application settings.
        factory: Database session factory.

    Returns:
        Router with `GET /greetings`.
    """
    router = APIRouter()

    @router.get("/greetings", response_model=list[GreetingOut])
    def list_greetings() -> list[GreetingOut]:
        """List the most recent stored greetings.

        Returns:
            Greetings, newest first.
        """
        with session_scope(factory) as session:
            rows = GreetingRepository(session).recent(environment=config.app_env)
        return [GreetingOut(message=r.message, environment=r.environment) for r in rows]

    return router
'''

MIDDLEWARE_PY = '''\"\"\"HTTP middleware: local-only guard, CORS for AI tools, and request logging.

- Local only (DNS-rebinding and CSRF guard): the Host must be 127.0.0.1 / localhost (plus
  `HTTP_ALLOWED_HOSTS`, e.g. host.docker.internal for Open WebUI in Docker), and a request that
  changes something from a web page must come from this app or from `HTTP_ALLOWED_ORIGINS`
  (default: Open WebUI at http://127.0.0.1:8080, whose tool servers call the API from the browser).
  Programs that do not send an `Origin` (agents, curl, the Open WebUI backend) are allowed.
- Request id: every log line of one request carries its id (`X-Request-ID`), plus one access line
  per request (method, path, status, duration), so a report can be matched with `grep <id> app.log`.
\"\"\"

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from {pkg}.config.logging_setup import new_run_id, reset_run_id, set_run_id
from {pkg}.config.settings import AppConfig

logger = logging.getLogger(__name__)
SAFE_METHODS = {{"GET", "HEAD", "OPTIONS"}}


def local_hosts(config: AppConfig) -> list[str]:
    \"\"\"Host names this app answers to.

    Args:
        config: Application settings.

    Returns:
        127.0.0.1, localhost and `HTTP_ALLOWED_HOSTS`.
    \"\"\"
    return ["127.0.0.1", "localhost", *config.http_allowed_hosts]


def add_local_only_guard(app: FastAPI, config: AppConfig) -> None:
    \"\"\"Refuse foreign Host headers and state changes from foreign web pages; allow CORS for AI tools.

    Args:
        app: Application to protect.
        config: Application settings (port, extra hosts and origins).
    \"\"\"
    names = [h.lower() for h in local_hosts(config)]
    hosts = {{*names, *(f"{{h}}:{{config.http_port}}" for h in names)}}
    origins = {{f"http://{{h}}:{{config.http_port}}" for h in ("127.0.0.1", "localhost")}}
    origins |= set(config.http_allowed_origins)

    @app.middleware("http")
    async def local_only(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        \"\"\"Check Host and Origin before handling the request.

        Args:
            request: Incoming request.
            call_next: The rest of the application.

        Returns:
            The response, or 403 for a request that is not local.
        \"\"\"
        host = (request.headers.get("host") or "").lower()
        origin = request.headers.get("origin")
        if host not in hosts or (request.method not in SAFE_METHODS and origin and origin not in origins):
            logger.warning("refused host=%s origin=%s %s %s", host, origin, request.method, request.url.path)
            return JSONResponse({{"detail": "only local requests are allowed"}}, status_code=403)
        return await call_next(request)

    if config.http_allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(config.http_allowed_origins),
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=["X-Request-ID", "Mcp-Session-Id"],
        )


def add_request_logging(app: FastAPI) -> None:
    \"\"\"Install the request-logging middleware.

    Args:
        app: Application to wrap.
    \"\"\"

    @app.middleware("http")
    async def log_request(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        \"\"\"Tag the request with an id, log its result and duration, and log failures with traceback.

        Args:
            request: Incoming request.
            call_next: The rest of the application.

        Returns:
            The response, with an `X-Request-ID` header.
        \"\"\"
        request_id = request.headers.get("X-Request-ID") or new_run_id()
        token = set_run_id(request_id)
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            ms = (time.perf_counter() - start) * 1000
            logger.exception("%s %s failed after %.1f ms", request.method, request.url.path, ms)
            raise
        finally:
            reset_run_id(token)
        level = logging.WARNING if response.status_code >= 400 else logging.INFO
        ms = (time.perf_counter() - start) * 1000
        path, status = request.url.path, response.status_code
        logger.log(level, "[%s] %s %s -> %s (%.1f ms)", request_id, request.method, path, status, ms)
        response.headers["X-Request-ID"] = request_id
        return response
'''

MCP_PY = '''"""MCP server: the same features as the HTTP API, for AI agents.

Agents that can call it (see docs/INTEGRATIONS.md): Claude Code (`.mcp.json`), Claude Desktop,
Antigravity, OpenCode (`opencode.json`), Cursor (`.cursor/mcp.json`), VS Code (`.vscode/mcp.json`)
and Open WebUI. Two ways to reach it:
  - stdio: `uv run {dist}-mcp` — the agent starts it by itself (nothing needs to be running);
  - Streamable HTTP: `http://127.0.0.1:<HTTP_PORT>/mcp` on the web server (`uv run {dist}-server`).

Every tool calls the services layer, exactly like the HTTP routes, so the page, the API and the
agents always agree. Tools that change or delete data must take `confirm: bool` and refuse
without it (least privilege: a person approves writes).
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator, Callable
from typing import Any

{imports}

INSTRUCTIONS = (
    "Tools of the {name} project. Read-only tools can be called freely; tools with a `confirm` "
    "argument change data and need the user's approval first."
)


def build_mcp_server(config: AppConfig{factory_param}) -> MCPServer[Any]:
    """Create the MCP server with this project's tools.

    Args:
        config: Application settings.{factory_doc}

    Returns:
        The MCP server (run it over stdio, or mount `mcp_http_routes()` into the web app).
    """
    server: MCPServer[Any] = MCPServer("{name}", instructions=INSTRUCTIONS, version="0.1.0")

    @server.tool()
    def greet(user_name: str) -> str:
        """Create a greeting for a user (example tool: replace it with the project's own features).

        Args:
            user_name: Name to greet.

        Returns:
            The greeting text.
        """
        return create_greeting(GreetingRequest(user_name=user_name), config).message
{db_tool}
    return server


def mcp_http_routes(server: MCPServer[Any], config: AppConfig) -> list[BaseRoute]:
    """Routes that serve the MCP server at `/mcp` inside the FastAPI app (Streamable HTTP).

    Args:
        server: Server from `build_mcp_server()`.
        config: Application settings (extra hosts and browser origins that may connect).

    Returns:
        Routes to append to the app (before any catch-all static mount).
    """
    hosts = ["127.0.0.1", "localhost", *config.http_allowed_hosts]
    security = TransportSecuritySettings(
        allowed_hosts=[*hosts, *(f"{{h}}:*" for h in hosts)],
        allowed_origins=["http://127.0.0.1:*", "http://localhost:*", *config.http_allowed_origins],
    )
    return list(server.streamable_http_app(streamable_http_path="/mcp", transport_security=security).routes)


def mcp_lifespan(server: MCPServer[Any]) -> Callable[[FastAPI], contextlib.AbstractAsyncContextManager[None]]:
    """FastAPI lifespan that runs the MCP session manager while the web server is up.

    Args:
        server: Server whose HTTP routes are mounted.

    Returns:
        The lifespan function for `FastAPI(lifespan=...)`.
    """

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        """Start and stop the MCP sessions together with the app.

        Args:
            _app: The FastAPI application (unused).

        Yields:
            Control while the app is running.
        """
        async with server.session_manager.run():
            yield

    return lifespan


def main() -> None:
    """Run the MCP server over stdio (`uv run {dist}-mcp`); logs go to stderr / DATA_DIR, never stdout."""
    config = load_config()
    setup_logging(config.log_level, config.logs_dir if config.log_to_file else None)
    build_mcp_server(config{factory_main}).run("stdio")


if __name__ == "__main__":
    main()
'''

MCP_DB_TOOL = '''
    @server.tool()
    def list_greetings() -> list[str]:
        """List the most recent stored greetings (read only).

        Returns:
            Greeting texts, newest first.
        """
        with session_scope(sessions) as session:
            return [row.message for row in GreetingRepository(session).recent(environment=config.app_env)]
'''

SERVER_PY = '''"""HTTP server entrypoint: `uv run {dist}-server` (listens on 127.0.0.1 only by default)."""

from __future__ import annotations

import uvicorn

from {pkg}.config.logging_setup import setup_logging
from {pkg}.config.settings import load_config
from {pkg}.entrypoints.http.app import create_app


def main() -> None:
    """Start uvicorn on `HTTP_HOST` / `HTTP_PORT` from `.env` (default 127.0.0.1:8000)."""
    config = load_config()
    setup_logging(config.log_level, config.logs_dir if config.log_to_file else None)
    # log_config=None: uvicorn's own messages go through our handlers and format (run id, files)
    uvicorn.run(create_app(config), host=config.http_host, port=config.http_port, log_config=None)


if __name__ == "__main__":
    main()
'''

API_TEST = '''"""Tests for the HTTP API (FastAPI TestClient; no real server or network)."""

from __future__ import annotations

{imports}


class ApiTest(unittest.TestCase):
    """Behaviour of the HTTP endpoints."""

    def setUp(self) -> None:
        """Create a client for an app with a test config{db_doc}."""
{db_setup}        self.client = TestClient(
            create_app(AppConfig(app_env="test"){factory_arg}),
            base_url="http://127.0.0.1:8000",
        )

    def test_health(self) -> None:
        """`/health` reports ok and the environment."""
        self.assertEqual(self.client.get("/health").json(), {{"status": "ok", "environment": "test"}})

    def test_greeting(self) -> None:
        """`POST /greetings` returns the greeting."""
        res = self.client.post("/greetings", json={{"user_name": "Ann"}})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["message"], "Hello, Ann!")

    def test_invalid_body_is_rejected(self) -> None:
        """An empty name fails validation with 422."""
        self.assertEqual(self.client.post("/greetings", json={{"user_name": ""}}).status_code, 422)

    def test_only_local_requests(self) -> None:
        """Foreign Host and foreign web pages are refused; Open WebUI's origin is allowed (CORS)."""
        foreign_host = self.client.get("/health", headers={{"Host": "evil.example"}})
        self.assertEqual(foreign_host.status_code, 403)
        body = {{"user_name": "Ann"}}
        foreign_page = self.client.post("/greetings", json=body, headers={{"Origin": "http://evil.test"}})
        self.assertEqual(foreign_page.status_code, 403)
        res = self.client.post("/greetings", json=body, headers={{"Origin": "http://127.0.0.1:8080"}})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers.get("access-control-allow-origin"), "http://127.0.0.1:8080")

    def test_openapi_names_tools_for_ai(self) -> None:
        """`/openapi.json` names each operation after its function (what Open WebUI shows as tool names)."""
        spec = self.client.get("/openapi.json").json()
        ids = {{op["operationId"] for path in spec["paths"].values() for op in path.values()}}
        self.assertIn("greet", ids)
        self.assertIn("health", ids)

    def test_requests_are_logged_with_request_id(self) -> None:
        """Each request gets an `X-Request-ID` (kept when sent) and one access log line."""
        with self.assertLogs("{pkg}.entrypoints.http.middleware", level="INFO") as logs:
            res = self.client.get("/health", headers={{"X-Request-ID": "trace-1"}})
        self.assertEqual(res.headers["X-Request-ID"], "trace-1")
        self.assertIn("GET /health -> 200", logs.output[0])
{db_test}

if __name__ == "__main__":
    unittest.main()
'''

MCP_TEST = '''"""Tests for the MCP server (in-process client: no network, no subprocess)."""

from __future__ import annotations

{imports}{helper}


class McpTest(unittest.TestCase):
    """The MCP tools that AI agents call."""

    def test_greet_tool(self) -> None:
        """Agents see the `greet` tool and get the same greeting as the HTTP API."""

        async def call() -> tuple[list[str], object]:
            """List the tools and call `greet`.

            Returns:
                Tool names and the structured result.
            """
            async with Client(build_mcp_server(AppConfig(app_env="test"){factory_arg})) as client:
                names = [tool.name for tool in (await client.list_tools()).tools]
                result = await client.call_tool("greet", {{"user_name": "Ann"}})
                return names, result.structured_content

        names, result = asyncio.run(call())
        self.assertIn("greet", names)
        self.assertEqual(result, {{"result": "Hello, Ann!"}})


if __name__ == "__main__":
    unittest.main()
'''

DB_API_TEST = '''
    def test_greetings_are_stored(self) -> None:
        """A created greeting appears in `GET /greetings`."""
        self.client.post("/greetings", json={"user_name": "Bob"})
        self.assertEqual([g["message"] for g in self.client.get("/greetings").json()], ["Hello, Bob!"])
'''

API_GUIDE = """# HTTP API（FastAPI）

- 路由：`app.py` 的 `create_app()`；輸入輸出格式：`schemas.py`（在這裡驗證，進到 services 前轉成 domain 物件）。
- 伺服器只綁 `127.0.0.1`（`.env` 的 `HTTP_HOST` / `HTTP_PORT`），不要改成 `0.0.0.0`。

啟動（開發用）：

```bash
uv run {dist}-server
```

開啟 http://127.0.0.1:8000/docs 可以看到自動產生的 API 文件並直接測試（不要用 localhost）。

同一個伺服器也提供 MCP（`/mcp`）給 AI Agent；不開伺服器時 Agent 可用 `uv run {dist}-mcp`（stdio）。
Open WebUI、Claude Code、Antigravity、OpenCode 等怎麼接，見 [`docs/INTEGRATIONS.md`](../../../../docs/INTEGRATIONS.md)。
"""


def import_block(stdlib: list[str], third_party: list[str], first_party: list[str]) -> str:
    """Render import groups in the order ruff/isort expects (stdlib, third-party, project).

    Args:
        stdlib: Standard-library import lines.
        third_party: Third-party import lines.
        first_party: Project import lines.

    Returns:
        The import block, groups separated by a blank line.
    """
    def key(line: str) -> tuple[int, str]:
        """Sort `import x` before `from x import y`, then alphabetically by module.

        Args:
            line: One import line.

        Returns:
            Sort key.
        """
        return (0 if line.startswith("import ") else 1, line.split()[1])

    groups = [sorted(g, key=key) for g in (stdlib, third_party, first_party) if g]
    return "\n\n".join("\n".join(g) for g in groups)


def build_app_module(pkg: str, name: str, with_db: bool, with_web: bool) -> str:
    """Render `entrypoints/http/app.py` for the chosen add-ons.

    Args:
        pkg: Python package name.
        name: Project name (API title).
        with_db: Store and list greetings through the database repository.
        with_web: Serve the `web/` folder as static files.

    Returns:
        Python source text.
    """
    first = [
        f"from {pkg}.config.settings import AppConfig",
        f"from {pkg}.domain.models import GreetingRequest",
        f"from {pkg}.entrypoints.http.middleware import add_local_only_guard, add_request_logging",
        f"from {pkg}.entrypoints.mcp_server import build_mcp_server, mcp_http_routes, mcp_lifespan",
        f"from {pkg}.entrypoints.http.schemas import GreetingIn, GreetingOut",
        f"from {pkg}.services.greeting import create_greeting",
    ]
    third = ["from fastapi import APIRouter, FastAPI", "from fastapi.routing import APIRoute"]
    third += ["from fastapi.staticfiles import StaticFiles"] if with_web else []
    if with_db:
        third.append("from sqlalchemy.orm import Session, sessionmaker")
        first += [
            f"from {pkg}.adapters.db.repository import GreetingRepository",
            f"from {pkg}.adapters.db.session import create_db_engine, make_session_factory, session_scope",
        ]
    return APP_HEADER.format(
        name=name,
        extra_doc=(", database-backed history" if with_db else "") + (" and the static `web/` front end" if with_web else ""),
        test_doc="\nand an in-memory database session factory" if with_db else "",
        imports=import_block(["from pathlib import Path"] if with_web else [], third, first),
        web_const='\nWEB_DIR = Path(__file__).resolve().parents[4] / "web"\n' if with_web else "",
        factory_param=", session_factory: sessionmaker[Session] | None = None" if with_db else "",
        factory_doc="\n        session_factory: Database session factory; created from `config.database_url` when omitted." if with_db else "",
        factory_init="    factory = session_factory or make_session_factory(create_db_engine(config.database_url))\n" if with_db else "",
        factory_arg=", factory" if with_db else "",
        factory_param_required=", factory: sessionmaker[Session]" if with_db else "",
        factory_doc_required="\n        factory: Database session factory." if with_db else "",
        history_include="    app.include_router(build_history_router(config, factory))\n" if with_db else "",
        web_mount=(
            "    if WEB_DIR.is_dir():\n"
            '        app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")\n'
        ) if with_web else "",
        save_doc=" and store it" if with_db else "",
        save_code=(
            "        with session_scope(factory) as session:\n"
            "            GreetingRepository(session).add(body.user_name, result)\n"
        ) if with_db else "",
        history_router=HISTORY_ROUTER if with_db else "",
    )


def build_mcp_module(pkg: str, names: dict[str, str], with_db: bool) -> str:
    """Render `entrypoints/mcp_server.py`.

    Args:
        pkg: Python package name.
        names: `project` (display name) and `dist` (command name).
        with_db: Add the read-only `list_greetings` tool backed by the database.

    Returns:
        Python source text.
    """
    first = [
        f"from {pkg}.config.logging_setup import setup_logging",
        f"from {pkg}.config.settings import AppConfig, load_config",
        f"from {pkg}.domain.models import GreetingRequest",
        f"from {pkg}.services.greeting import create_greeting",
    ]
    third = ["from fastapi import FastAPI", "from mcp.server import MCPServer",
             "from mcp.server.transport_security import TransportSecuritySettings", "from starlette.routing import BaseRoute"]
    if with_db:
        third.append("from sqlalchemy.orm import Session, sessionmaker")
        first += [
            f"from {pkg}.adapters.db.repository import GreetingRepository",
            f"from {pkg}.adapters.db.session import create_db_engine, make_session_factory, session_scope",
        ]
    source = MCP_PY.format(
        imports=import_block([], third, first), name=names["project"], dist=names["dist"],
        factory_param=", factory: sessionmaker[Session] | None = None" if with_db else "",
        factory_doc="\n        factory: Database session factory; created from `config.database_url` when omitted." if with_db else "",
        db_tool=MCP_DB_TOOL if with_db else "",
        factory_main="",
    )
    if with_db:  # the stdio server builds its own session factory
        source = source.replace(
            "    server: MCPServer[Any] = MCPServer(",
            "    sessions = factory or make_session_factory(create_db_engine(config.database_url))\n    server: MCPServer[Any] = MCPServer(",
        )
    return source


def build_mcp_test(pkg: str, with_db: bool) -> str:
    """Render `tests/test_mcp.py` (in-memory database when `db` is used, never the real DATA_DIR).

    Args:
        pkg: Python package name.
        with_db: Pass an in-memory session factory to the server.

    Returns:
        Python source text.
    """
    third = ["from mcp import Client"] + (["from sqlalchemy.orm import Session, sessionmaker"] if with_db else [])
    first = [f"from {pkg}.config.settings import AppConfig", f"from {pkg}.entrypoints.mcp_server import build_mcp_server"]
    if with_db:
        first += [f"from {pkg}.adapters.db.base import Base", f"from {pkg}.adapters.db.session import create_db_engine, make_session_factory"]
    helper = (
        "\n\n\ndef memory_sessions() -> sessionmaker[Session]:\n"
        '    """Create an in-memory database for the test.\n\n    Returns:\n        A session factory bound to a fresh SQLite memory database.\n    """\n'
        '    engine = create_db_engine("sqlite://")\n    Base.metadata.create_all(engine)\n    return make_session_factory(engine)'
    ) if with_db else ""
    return MCP_TEST.format(
        imports=import_block(["import asyncio", "import unittest"], third, first), helper=helper,
        factory_arg=", memory_sessions()" if with_db else "",
    )


def build_api_test(pkg: str, with_db: bool) -> str:
    """Render `tests/test_api.py`.

    Args:
        pkg: Python package name.
        with_db: Include the stored-greeting test with an in-memory database.

    Returns:
        Python source text.
    """
    first = [f"from {pkg}.config.settings import AppConfig", f"from {pkg}.entrypoints.http.app import create_app"]
    if with_db:
        first += [
            f"from {pkg}.adapters.db.base import Base",
            f"from {pkg}.adapters.db.session import create_db_engine, make_session_factory",
        ]
    return API_TEST.format(
        pkg=pkg,
        imports=import_block(["import unittest"], ["from fastapi.testclient import TestClient"], first),
        db_doc=" and an in-memory database" if with_db else "",
        db_setup=(
            '        engine = create_db_engine("sqlite://")\n'
            "        Base.metadata.create_all(engine)\n"
        ) if with_db else "",
        factory_arg=", make_session_factory(engine)" if with_db else "",
        db_test=DB_API_TEST if with_db else "",
    )


def scaffold_api_pack(target_dir: Path, pkg: str, names: dict[str, str], addons: list[str]) -> None:
    """Create the FastAPI entrypoint, schemas, server and tests.

    Args:
        target_dir: Project root directory.
        pkg: Python package name under `src/`.
        names: `project` (display name) and `dist` (distribution / command name).
        addons: Project add-ons (`db` and `web` change the generated app).
    """
    http = target_dir / "src" / pkg / "entrypoints" / "http"
    _write(http / "__init__.py", '"""HTTP entrypoints (FastAPI)."""\n')
    _write(http / "schemas.py", SCHEMAS_PY)
    _write(http / "app.py", build_app_module(pkg, names["project"], "db" in addons, "web" in addons))
    _write(http / "server.py", SERVER_PY.format(pkg=pkg, dist=names["dist"]))
    _write(http / "middleware.py", MIDDLEWARE_PY.format(pkg=pkg))
    _write(target_dir / "src" / pkg / "entrypoints" / "mcp_server.py", build_mcp_module(pkg, names, "db" in addons))
    _write(target_dir / "tests" / "test_mcp.py", build_mcp_test(pkg, "db" in addons))
    _write(http / "API.md", API_GUIDE.format(dist=names["dist"]))
    scaffold_integrations(target_dir, names)
    _write(target_dir / "tests" / "test_api.py", build_api_test(pkg, "db" in addons))
