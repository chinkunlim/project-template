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
      - `tests/test_api.py`                    : TestClient tests (no real server needed)
"""

from __future__ import annotations

from pathlib import Path

from packs.common import write_file as _write

API_DEPENDENCIES = ["fastapi>=0.115", "pydantic>=2.7", "uvicorn>=0.30"]
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

`create_app()` receives its dependencies as arguments, so tests can pass a test config{test_doc}.
"""

from __future__ import annotations

{imports}
{web_const}

def create_app(config: AppConfig{factory_param}) -> FastAPI:
    """Build the FastAPI application.

    Args:
        config: Application settings.{factory_doc}

    Returns:
        The configured application.
    """
    app = FastAPI(title="{name}", version="0.1.0")
    add_request_logging(app)
{factory_init}    app.include_router(build_greeting_router(config{factory_arg}))
{history_include}{web_mount}    return app


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

MIDDLEWARE_PY = '''"""Request logging: one request id per HTTP request on every log line, plus an access line.

Clients may send `X-Request-ID`; otherwise a new id is created. The id is returned in the
response header, so a user's error report can be matched with `grep <id> app.log`.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response

from {pkg}.config.logging_setup import new_run_id, reset_run_id, set_run_id

logger = logging.getLogger(__name__)


def add_request_logging(app: FastAPI) -> None:
    """Install the request-logging middleware.

    Args:
        app: Application to wrap.
    """

    @app.middleware("http")
    async def log_request(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        """Tag the request with an id, log its result and duration, and log failures with traceback.

        Args:
            request: Incoming request.
            call_next: The rest of the application.

        Returns:
            The response, with an `X-Request-ID` header.
        """
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
{db_setup}        self.client = TestClient(create_app(AppConfig(app_env="test"){factory_arg}))

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
        f"from {pkg}.entrypoints.http.middleware import add_request_logging",
        f"from {pkg}.entrypoints.http.schemas import GreetingIn, GreetingOut",
        f"from {pkg}.services.greeting import create_greeting",
    ]
    third = ["from fastapi import APIRouter, FastAPI"] + (["from fastapi.staticfiles import StaticFiles"] if with_web else [])
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
    _write(http / "API.md", API_GUIDE.format(dist=names["dist"]))
    _write(target_dir / "tests" / "test_api.py", build_api_test(pkg, "db" in addons))
