#!/usr/bin/env python3
"""Tier 1 & Tier 2 starter templates for HTTP safety, port preflight, DB protocols and web contracts.

Purpose:
    Keeps `api_pack.py` and `db_pack.py` modular and concise while giving new
    `--with api / web / db` projects production-grade safeguards out of the box:
      - `port_check.py`: preflight TCP port binding check with `SO_REUSEADDR` and `lsof` owner hint
      - `protocols.py`: `typing.Protocol` interfaces in `domain/` so `services/` stays decoupled
      - `middleware.py` template: Host/Origin validation, request logging, path guard, DB scope
      - `NoCacheStaticFiles` and request-scoped SQLAlchemy session middleware snippets
      - `test_port_check.py` and `test_web_contracts.py` (DOM ID & OpenAPI route static contracts)
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

PORT_CHECK_PY = '''"""Start-up port preflight check: identify busy ports instead of failing with an opaque bind error."""

from __future__ import annotations

import logging
import socket
import subprocess

logger = logging.getLogger(__name__)


def port_is_free(host: str, port: int) -> bool:
    """Return whether a TCP port can be bound on the given host.

    Uses `SO_REUSEADDR` so sockets in `TIME_WAIT` from a recently stopped server do not
    trigger false positives while live listeners still fail to bind.

    Args:
        host: Address to bind, e.g. `127.0.0.1`.
        port: TCP port number.

    Returns:
        True when no process is actively listening on `(host, port)`.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def _port_owner(port: int) -> str:
    """Describe the process listening on a port using `lsof` when available.

    Args:
        port: TCP port number.

    Returns:
        Comma-separated `command (PID n)` strings, or an empty string when unknown.
    """
    try:
        out = subprocess.run(
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        ).stdout
    except (OSError, subprocess.TimeoutExpired) as err:
        logger.warning("could not run lsof for port %d: %s", port, err)
        return ""
    rows = [line.split() for line in out.splitlines()[1:] if line.strip()]
    return ", ".join(sorted({f"{r[0]} (PID {r[1]})" for r in rows if len(r) > 1}))


def busy_port_message(host: str, port: int, app_name: str) -> str:
    """Explain clearly which process holds the requested port and how to resolve it.

    Args:
        host: Host address the server attempted to bind.
        port: TCP port number.
        app_name: Human-readable service name.

    Returns:
        Diagnostic message pointing to the machine-wide `PORTS.md` registry.
    """
    owner = _port_owner(port) or "未知的程式"
    return (
        f"埠號 {port} 已被 {owner} 佔用，{app_name} 沒有啟動。\\n"
        f"如果該服務已經在執行，請直接開啟 http://{host}:{port}；\\n"
        "否則請先關閉佔用程式，或在 .env 改用其他 HTTP_PORT"
        "（開新埠號前請先查 ~/Desktop/projects/00 init_dev_env/PORTS.md）。"
    )
'''

PROTOCOLS_PY = '''"""Repository and adapter protocols: keeps services decoupled from concrete adapters."""

from __future__ import annotations

import logging
from typing import Protocol

from {pkg}.domain.models import GreetingResult

logger = logging.getLogger(__name__)


class GreetingRepositoryProtocol(Protocol):
    """Structural contract for storing and querying greetings."""

    def add(self, user_name: str, result: GreetingResult) -> int:
        """Persist a single greeting and return its identifier.

        Args:
            user_name: Name that was greeted.
            result: Greeting returned by the domain service.

        Returns:
            Newly inserted record ID.
        """
        ...

    def recent(self, limit: int = 20, environment: str = "") -> list[GreetingResult]:
        """Fetch recent greetings in reverse chronological order.

        Args:
            limit: Maximum number of records to return.
            environment: Environment label attached to domain results.

        Returns:
            List of greeting domain objects.
        """
        ...
'''

NO_CACHE_STATIC_CLASS = '''

class NoCacheStaticFiles(StaticFiles):
    """Static files that instruct browsers to revalidate so UI updates are never stale."""

    def file_response(self, *args: Any, **kwargs: Any) -> Response:
        """Serve a static asset with `Cache-Control: no-cache` header.

        Args:
            *args: Forwarded to `StaticFiles.file_response`.
            **kwargs: Forwarded to `StaticFiles.file_response`.

        Returns:
            File response with revalidation header attached.
        """
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response
'''

DB_SCOPE_MIDDLEWARE_SNIPPET = '''

def add_db_session_scope(app: FastAPI, registries: list[scoped_session[Session]]) -> None:
    """Give each HTTP request its own database session scope and release it on completion.

    Args:
        app: FastAPI application instance.
        registries: Scoped session registries bound to the app (`_DB_SCOPE`).
    """

    @app.middleware("http")
    async def db_session_scope(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Create a per-request ContextVar scope and remove sessions in `finally`.

        Args:
            request: Incoming HTTP request.
            call_next: Downstream request handler.

        Returns:
            HTTP response from downstream handlers.
        """
        token = enter_request_db_scope()
        try:
            return await call_next(request)
        finally:
            exit_request_db_scope(token, registries)
'''

REQUEST_SCOPE_DB_TEST = '''
    def test_request_scoped_session_isolates_and_cleans_up(self) -> None:
        """Each `_DB_SCOPE` token gets a fresh session removed cleanly on exit."""
        scoped = make_request_scoped_session(self.factory)
        tok = enter_request_db_scope()
        s1 = scoped()
        GreetingRepository(s1).add("Cara", GreetingResult(message="Hi!", environment="test"))
        s1.commit()
        exit_request_db_scope(tok, [scoped])
        tok2 = enter_request_db_scope()
        self.assertIsNot(scoped(), s1)
        exit_request_db_scope(tok2, [scoped])
'''

MIDDLEWARE_TEMPLATE = '''"""HTTP middleware: local-only guard, CORS for AI tools, request logging and download path guard.

- Local only (DNS-rebinding and CSRF guard): Host must be 127.0.0.1 / localhost (plus
  `HTTP_ALLOWED_HOSTS`, e.g. host.docker.internal or Tailscale hostnames), and state-changing
  browser requests must originate from this app or `HTTP_ALLOWED_ORIGINS`.
- Request id: every log line of one request carries its id (`X-Request-ID`) and access summary.
- Safe paths: `safe_resolve_under()` guarantees file downloads stay inside the intended root.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
{db_third_imports}
{db_first_imports}from {pkg}.config.logging_setup import new_run_id, reset_run_id, set_run_id
from {pkg}.config.settings import AppConfig

logger = logging.getLogger(__name__)
SAFE_METHODS = {{"GET", "HEAD", "OPTIONS"}}


def local_hosts(config: AppConfig) -> list[str]:
    """Host names this app answers to.

    Args:
        config: Application settings.

    Returns:
        127.0.0.1, localhost and `HTTP_ALLOWED_HOSTS`.
    """
    return ["127.0.0.1", "localhost", *config.http_allowed_hosts]


def safe_resolve_under(root: Path, relative_path: str) -> Path:
    """Resolve a download or static relative path safely inside `root`.

    Args:
        root: Allowed root directory.
        relative_path: User- or URL-supplied relative path.

    Returns:
        Resolved absolute path strictly inside `root`.

    Raises:
        ValueError: When the resolved path escapes `root` via `..` or symlinks.
    """
    base = root.resolve()
    candidate = (base / relative_path).resolve()
    if not candidate.is_relative_to(base):
        raise ValueError("path escapes allowed root directory")
    return candidate


def add_local_only_guard(app: FastAPI, config: AppConfig) -> None:
    """Refuse foreign Host headers and state changes from foreign web pages; allow CORS for AI tools.

    Args:
        app: Application to protect.
        config: Application settings (port, extra hosts and origins).
    """
    names = {{h.lower() for h in local_hosts(config)}}
    hosts = {{*names, *(f"{{h}}:{{config.http_port}}" for h in names)}}
    origins = {{f"http://{{h}}:{{config.http_port}}" for h in ("127.0.0.1", "localhost")}}
    origins |= set(config.http_allowed_origins)

    @app.middleware("http")
    async def local_only(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        """Check Host and Origin before handling the request.

        Args:
            request: Incoming request.
            call_next: The rest of the application.

        Returns:
            The response, or 403 for a request that is not local.
        """
        host = (request.headers.get("host") or "").lower()
        origin = request.headers.get("origin")
        host_ok = bool(host) and (host in hosts or host.split(":", 1)[0] in names)
        if not host_ok or (request.method not in SAFE_METHODS and origin and origin not in origins):
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
{db_scope_fn}'''


def build_middleware_module(pkg: str, with_db: bool) -> str:
    """Render `entrypoints/http/middleware.py` with local guard, logging, path guard and DB scope.

    Args:
        pkg: Python package name under `src/`.
        with_db: Include `add_db_session_scope()` when True.

    Returns:
        Python source text.
    """
    return MIDDLEWARE_TEMPLATE.format(
        pkg=pkg,
        db_third_imports="from sqlalchemy.orm import Session, scoped_session\n" if with_db else "",
        db_first_imports=(
            f"from {pkg}.adapters.db.session import enter_request_db_scope, exit_request_db_scope\n"
            if with_db
            else ""
        ),
        db_scope_fn=DB_SCOPE_MIDDLEWARE_SNIPPET if with_db else "",
    )


def build_port_check_test(pkg: str, name: str) -> str:
    """Render `tests/test_port_check.py` to test preflight TCP port availability detection.

    Args:
        pkg: Python package name under `src/`.
        name: Project display name.

    Returns:
        Python test module source text.
    """
    return f'''"""Tests for start-up TCP port preflight detection."""

from __future__ import annotations

import socket
import unittest

from {pkg}.entrypoints.http.port_check import busy_port_message, port_is_free


class PortCheckTest(unittest.TestCase):
    """Verify `port_is_free` and `busy_port_message` without long-lived servers."""

    def test_unbound_and_bound_ports(self) -> None:
        """A listening socket reports busy while live, and free ports report available."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind(("127.0.0.1", 0))
            srv.listen(1)
            port = srv.getsockname()[1]
            self.assertFalse(port_is_free("127.0.0.1", port))
            msg = busy_port_message("127.0.0.1", port, {json.dumps(name)})
            self.assertIn(str(port), msg)
            self.assertIn("PORTS.md", msg)
        self.assertTrue(port_is_free("127.0.0.1", port))


if __name__ == "__main__":
    unittest.main()
'''


OPENAPI_CONTRACT_METHOD = '''
    def test_every_fetched_api_path_exists_in_openapi(self) -> None:
        """Every API route fetched by front-end JS/HTML must exist in `app.openapi()`."""
{db_init}
        routes = set(app.openapi()["paths"])
        normalized = {{re.sub(r"\\{{[^}}]+\\}}", "X", p) for p in routes}}
        html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
        page = "".join(p.read_text(encoding="utf-8") for p in WEB_DIR.glob("*.js")) + html
        missing: list[str] = []
        skip_ext = (".css", ".js", ".html", ".png", ".svg", ".ico", ".woff2")
        for raw in re.findall(r"(?:fetch|apiFetch)\\(\\s*[`'\\"](/[^`'\\"?]*)", page):
            if raw.endswith(skip_ext):
                continue
            path = re.sub(r"\\$\\{{[^}}]*$", "X", re.sub(r"\\$\\{{[^}}]+\\}}", "X", raw))
            pattern = re.compile("^" + re.escape(path).replace("X", "[^/]+") + "$")
            if not any(pattern.match(r) for r in normalized):
                missing.append(raw)
        self.assertEqual(missing, [])
'''

WEB_CONTRACTS_TEMPLATE = '''"""Offline static contract tests for web DOM IDs and API endpoints."""

from __future__ import annotations

import re
import unittest
from pathlib import Path{api_imports}

WEB_DIR = Path(__file__).resolve().parents[1] / "web"


class WebContractsTest(unittest.TestCase):
    """Catch dead buttons and mismatched DOM IDs or API paths in 0.1s offline."""

    def test_every_dom_id_in_js_exists_in_html(self) -> None:
        """Every literal `document.getElementById(...)` in `web/*.js` must exist in HTML or JS builders."""
        html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
        js_text = "".join(p.read_text(encoding="utf-8") for p in sorted(WEB_DIR.glob("*.js")))
        defined = set(re.findall(r'\\bid=["\\']([^"\\']+)["\\']', html))
        defined.update(re.findall(r'\\.id\\s*=\\s*["\\']([^"\\']+)["\\']', js_text))
        referenced = re.findall(r'getElementById\\(\\s*["\\']([^"\\']+)["\\']\\s*\\)', js_text)
        missing = sorted(set(referenced) - defined)
        self.assertEqual(missing, [])
{api_method}

if __name__ == "__main__":
    unittest.main()
'''


def _openapi_test_block(pkg: str, with_db: bool) -> tuple[str, str]:
    """Build the OpenAPI contract import block and test method for `test_web_contracts.py`.

    Args:
        pkg: Python package name under `src/`.
        with_db: Initialize in-memory SQLite session factory for `create_app()` when True.

    Returns:
        Tuple of `(first_party_imports, test_method_source)`.
    """
    imports_list = [f"from {pkg}.config.settings import AppConfig", f"from {pkg}.entrypoints.http.app import create_app"]
    db_init = '        app = create_app(AppConfig(app_env="test"))'
    if with_db:
        imports_list = [
            f"from {pkg}.adapters.db.base import Base",
            f"from {pkg}.adapters.db.session import create_db_engine, make_session_factory",
            *imports_list,
        ]
        db_init = (
            '        engine = create_db_engine("sqlite://")\n'
            "        Base.metadata.create_all(engine)\n"
            '        app = create_app(AppConfig(app_env="test"), make_session_factory(engine))'
        )
    return "\n\n" + "\n".join(imports_list), OPENAPI_CONTRACT_METHOD.format(db_init=db_init)


def build_web_contracts_test(pkg: str, with_api: bool, with_db: bool) -> str:
    """Render `tests/test_web_contracts.py` for offline JS/HTML DOM & OpenAPI contract checks.

    Args:
        pkg: Python package name under `src/`.
        with_api: Include FastAPI OpenAPI path vs `fetch()` contract check when True.
        with_db: Initialize in-memory SQLite session factory for `create_app()` when True.

    Returns:
        Python test module source text.
    """
    logger.debug("build web contracts test pkg=%s api=%s db=%s", pkg, with_api, with_db)
    api_imports, api_method = _openapi_test_block(pkg, with_db) if with_api else ("", "")
    return WEB_CONTRACTS_TEMPLATE.format(api_imports=api_imports, api_method=api_method)
