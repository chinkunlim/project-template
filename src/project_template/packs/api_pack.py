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

import logging
from pathlib import Path

from project_template.packs.api_extras_pack import (
    NO_CACHE_STATIC_CLASS,
    PORT_CHECK_PY,
    build_middleware_module,
    build_port_check_test,
    build_web_contracts_test,
)
from project_template.packs.common import write_file as _write
from project_template.packs.integrations_pack import scaffold_integrations

logger = logging.getLogger(__name__)

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

logger = logging.getLogger(__name__)
{web_const}{no_cache_class}

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
{db_scope_init}    app.include_router(build_greeting_router(config{router_arg}))
{history_include}    app.router.routes.extend(mcp_http_routes(mcp, config))  # before the static catch-all below
{web_mount}    logger.info("app created env=%s", config.app_env)
    return app


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

def build_history_router(config: AppConfig, request_session: scoped_session[Session]) -> APIRouter:
    """Create the route that lists stored greetings.

    Args:
        config: Application settings.
        request_session: Request-scoped database session registry.

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
        rows = GreetingRepository(request_session()).recent(environment=config.app_env)
        return [GreetingOut(message=r.message, environment=r.environment) for r in rows]

    return router
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
import logging
from collections.abc import AsyncIterator, Callable
from typing import Any

{imports}

logger = logging.getLogger(__name__)
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
        logger.info("mcp tool greet")
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
    logger.info("mcp stdio server starting env=%s", config.app_env)
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

import logging
import sys

import uvicorn

from {pkg}.config.logging_setup import setup_logging
from {pkg}.config.settings import load_config
from {pkg}.entrypoints.http.app import create_app
from {pkg}.entrypoints.http.port_check import busy_port_message, port_is_free

logger = logging.getLogger(__name__)


def main() -> None:
    """Start uvicorn on `HTTP_HOST` / `HTTP_PORT` from `.env` (default 127.0.0.1:8000)."""
    config = load_config()
    setup_logging(config.log_level, config.logs_dir if config.log_to_file else None)
    if not port_is_free(config.http_host, config.http_port):
        msg = busy_port_message(config.http_host, config.http_port, "{name}")
        logger.error(msg)
        print(msg, file=sys.stderr)
        raise SystemExit(1)
    logger.info("server starting http://%s:%s", config.http_host, config.http_port)
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

    def test_safe_resolve_under_blocks_traversal(self) -> None:
        """Download paths escaping their base directory via `..` are rejected."""
        base = Path(__file__).resolve().parent
        self.assertEqual(safe_resolve_under(base, "test_api.py"), base / "test_api.py")
        with self.assertRaises(ValueError):
            safe_resolve_under(base, "../pyproject.toml")
{web_test}{db_test}

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

WEB_API_TEST = '''
    def test_static_files_send_no_cache(self) -> None:
        """Static UI assets return `Cache-Control: no-cache` so browsers always revalidate."""
        res = self.client.get("/styles.css")
        self.assertEqual((res.status_code, res.headers.get("cache-control")), (200, "no-cache"))
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


def _app_imports(pkg: str, with_db: bool, with_web: bool) -> str:
    """Build the sorted import block for `entrypoints/http/app.py`.

    Args:
        pkg: Python package name.
        with_db: Include SQLAlchemy and repository imports.
        with_web: Include `StaticFiles`, `Response`, `Path` and `Any` imports.

    Returns:
        Sorted import block formatted for ruff/isort.
    """
    stdlib = ["import logging", *(["from pathlib import Path", "from typing import Any"] if with_web else [])]
    mw_line = (
        f"from {pkg}.entrypoints.http.middleware import (\n"
        "    add_db_session_scope,\n"
        "    add_local_only_guard,\n"
        "    add_request_logging,\n"
        ")"
        if with_db
        else f"from {pkg}.entrypoints.http.middleware import add_local_only_guard, add_request_logging"
    )
    first = [
        f"from {pkg}.config.settings import AppConfig",
        f"from {pkg}.domain.models import GreetingRequest",
        mw_line,
        f"from {pkg}.entrypoints.http.schemas import GreetingIn, GreetingOut",
        f"from {pkg}.entrypoints.mcp_server import build_mcp_server, mcp_http_routes, mcp_lifespan",
        f"from {pkg}.services.greeting import create_greeting",
    ]
    third = ["from fastapi import APIRouter, FastAPI", "from fastapi.routing import APIRoute"]
    if with_web:
        third += ["from fastapi.responses import Response", "from fastapi.staticfiles import StaticFiles"]
    if with_db:
        third.append("from sqlalchemy.orm import Session, scoped_session, sessionmaker")
        first += [
            f"from {pkg}.adapters.db.repository import GreetingRepository",
            f"from {pkg}.adapters.db.session import create_db_engine, make_request_scoped_session, make_session_factory",
        ]
    return import_block(stdlib, third, first)


def _app_db_kwargs(with_db: bool) -> dict[str, str]:
    """Build template format substitutions specific to `--with db` in `app.py`.

    Args:
        with_db: Whether database support is enabled.

    Returns:
        Substitution dictionary for `APP_HEADER.format()`.
    """
    if not with_db:
        return {k: "" for k in ("test_doc", "factory_param", "factory_doc", "factory_init", "factory_arg", "router_arg", "db_scope_init", "factory_param_required", "factory_doc_required", "history_include", "save_doc", "save_code", "history_router")}
    return {
        "test_doc": "\nand an in-memory database session factory",
        "factory_param": ", session_factory: sessionmaker[Session] | None = None",
        "factory_doc": "\n        session_factory: Database session factory; created from `config.database_url` when omitted.",
        "factory_init": (
            "    factory = session_factory or make_session_factory(create_db_engine(config.database_url))\n"
            "    scoped_registries: list[scoped_session[Session]] = []\n"
            "    request_session = make_request_scoped_session(factory)\n"
            "    scoped_registries.append(request_session)\n"
        ),
        "factory_arg": ", factory",
        "router_arg": ", request_session",
        "db_scope_init": "    add_db_session_scope(app, scoped_registries)\n    app.state.db_scoped_registries = scoped_registries\n",
        "factory_param_required": ", request_session: scoped_session[Session]",
        "factory_doc_required": "\n        request_session: Request-scoped database session registry.",
        "history_include": "    app.include_router(build_history_router(config, request_session))\n",
        "save_doc": " and store it",
        "save_code": "        session = request_session()\n        GreetingRepository(session).add(body.user_name, result)\n        session.commit()\n",
        "history_router": HISTORY_ROUTER,
    }


def build_app_module(pkg: str, name: str, with_db: bool, with_web: bool) -> str:
    """Render `entrypoints/http/app.py` for the chosen add-ons.

    Args:
        pkg: Python package name.
        name: Project name (API title).
        with_db: Store and list greetings through the database repository.
        with_web: Serve the `web/` folder as static files with no-cache headers.

    Returns:
        Python source text.
    """
    web_mount = '    if WEB_DIR.is_dir():\n        app.mount("/", NoCacheStaticFiles(directory=WEB_DIR, html=True), name="web")\n' if with_web else ""
    return APP_HEADER.format(
        name=name,
        extra_doc=(", database-backed history" if with_db else "") + (" and the static `web/` front end" if with_web else ""),
        imports=_app_imports(pkg, with_db, with_web),
        web_const='\nWEB_DIR = Path(__file__).resolve().parents[4] / "web"\n' if with_web else "",
        no_cache_class=NO_CACHE_STATIC_CLASS if with_web else "",
        web_mount=web_mount,
        **_app_db_kwargs(with_db),
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


def build_api_test(pkg: str, with_db: bool, with_web: bool = False) -> str:
    """Render `tests/test_api.py`.

    Args:
        pkg: Python package name.
        with_db: Include the stored-greeting test with an in-memory database.
        with_web: Include `Cache-Control: no-cache` verification on static UI files.

    Returns:
        Python source text.
    """
    first = [
        f"from {pkg}.config.settings import AppConfig",
        f"from {pkg}.entrypoints.http.app import create_app",
        f"from {pkg}.entrypoints.http.middleware import safe_resolve_under",
    ]
    if with_db:
        first += [
            f"from {pkg}.adapters.db.base import Base",
            f"from {pkg}.adapters.db.session import create_db_engine, make_session_factory",
        ]
    return API_TEST.format(
        pkg=pkg,
        imports=import_block(["import unittest", "from pathlib import Path"], ["from fastapi.testclient import TestClient"], first),
        db_doc=" and an in-memory database" if with_db else "",
        db_setup=(
            '        engine = create_db_engine("sqlite://")\n'
            "        Base.metadata.create_all(engine)\n"
        ) if with_db else "",
        factory_arg=", make_session_factory(engine)" if with_db else "",
        web_test=WEB_API_TEST if with_web else "",
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
    logger.debug("scaffold api_pack in %s", target_dir)
    with_db, with_web = "db" in addons, "web" in addons
    http = target_dir / "src" / pkg / "entrypoints" / "http"
    _write(http / "__init__.py", '"""HTTP entrypoints (FastAPI)."""\n')
    _write(http / "schemas.py", SCHEMAS_PY)
    _write(http / "app.py", build_app_module(pkg, names["project"], with_db, with_web))
    _write(http / "server.py", SERVER_PY.format(pkg=pkg, dist=names["dist"], name=names["project"]))
    _write(http / "middleware.py", build_middleware_module(pkg, with_db))
    _write(http / "port_check.py", PORT_CHECK_PY)
    _write(target_dir / "src" / pkg / "entrypoints" / "mcp_server.py", build_mcp_module(pkg, names, with_db))
    _write(target_dir / "tests" / "test_mcp.py", build_mcp_test(pkg, with_db))
    _write(http / "API.md", API_GUIDE.format(dist=names["dist"]))
    scaffold_integrations(target_dir, names)
    _write(target_dir / "tests" / "test_api.py", build_api_test(pkg, with_db, with_web))
    _write(target_dir / "tests" / "test_port_check.py", build_port_check_test(pkg, names["project"]))
    if with_web:
        _write(target_dir / "tests" / "test_web_contracts.py", build_web_contracts_test(pkg, True, with_db))
