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
from project_template.packs.api_templates import (
    API_DEPENDENCIES,
    API_DEV_DEPENDENCIES,
    API_GUIDE,
    API_TEST,
    APP_HEADER,
    DB_API_TEST,
    HISTORY_ROUTER,
    MCP_DB_TOOL,
    MCP_PY,
    MCP_TEST,
    SCHEMAS_PY,
    SERVER_PY,
    WEB_API_TEST,
)
from project_template.packs.common import write_file as _write
from project_template.packs.integrations_pack import scaffold_integrations

__all__ = [
    "API_DEPENDENCIES",
    "API_DEV_DEPENDENCIES",
    "API_GUIDE",
    "API_TEST",
    "APP_HEADER",
    "DB_API_TEST",
    "HISTORY_ROUTER",
    "MCP_DB_TOOL",
    "MCP_PY",
    "MCP_TEST",
    "SCHEMAS_PY",
    "SERVER_PY",
    "WEB_API_TEST",
    "build_api_test",
    "build_app_module",
    "build_mcp_module",
    "build_mcp_test",
    "import_block",
    "scaffold_api_pack",
]

logger = logging.getLogger(__name__)


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
        keys = (
            "test_doc", "factory_param", "factory_doc", "factory_init", "factory_arg", "router_arg",
            "db_scope_init", "factory_param_required", "factory_doc_required", "history_include",
            "save_doc", "save_code", "history_router",
        )
        return {k: "" for k in keys}
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
        names: `project` (display name), `dist` (command name), and optional `port` (HTTP port string).
        addons: Project add-ons (`db` and `web` change the generated app).
    """
    logger.debug("scaffold api_pack in %s", target_dir)
    with_db, with_web = "db" in addons, "web" in addons
    port = int(names.get("port") or 8000)
    http = target_dir / "src" / pkg / "entrypoints" / "http"
    _write(http / "__init__.py", '"""HTTP entrypoints (FastAPI)."""\n')
    _write(http / "schemas.py", SCHEMAS_PY)
    _write(http / "app.py", build_app_module(pkg, names["project"], with_db, with_web))
    _write(http / "server.py", SERVER_PY.format(pkg=pkg, dist=names["dist"], name=names["project"]))
    _write(http / "middleware.py", build_middleware_module(pkg, with_db))
    _write(http / "port_check.py", PORT_CHECK_PY)
    _write(target_dir / "src" / pkg / "entrypoints" / "mcp_server.py", build_mcp_module(pkg, names, with_db))
    _write(target_dir / "tests" / "test_mcp.py", build_mcp_test(pkg, with_db))
    _write(http / "API.md", API_GUIDE.format(dist=names["dist"], port=port))
    scaffold_integrations(target_dir, names, port=port)
    _write(target_dir / "tests" / "test_api.py", build_api_test(pkg, with_db, with_web))
    _write(target_dir / "tests" / "test_port_check.py", build_port_check_test(pkg, names["project"]))
    if with_web:
        _write(target_dir / "tests" / "test_web_contracts.py", build_web_contracts_test(pkg, True, with_db))
