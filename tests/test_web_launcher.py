"""Tests for the integrated Project Web Launcher Hub, MCP tools, API routes, and hub CLI."""

from __future__ import annotations

import asyncio
import json
import os
import plistlib
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

TEMPLATE_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = TEMPLATE_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


def _free_port() -> int:
    """Bind an ephemeral loopback socket briefly to allocate an unused port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _write_min_project(
    root: Path,
    *,
    env_text: str = "",
    pyproject_text: str = "",
    project_toml_text: str = "",
    with_web_app: bool = False,
) -> Path:
    """Create a minimal tracked project fixture for web launcher discovery tests."""
    root.mkdir(parents=True, exist_ok=True)
    (root / ".agents").mkdir(exist_ok=True)
    (root / ".agents" / "framework.lock").write_text('{"framework_version":"3.6.0","files":{}}\n', encoding="utf-8")
    (root / "scripts").mkdir(exist_ok=True)
    (root / "scripts" / "agentctl.py").write_text('"""Stub."""\n', encoding="utf-8")
    (root / ".agents" / "project.toml").write_text(
        project_toml_text or f'[project]\nname = "{root.name}"\n',
        encoding="utf-8",
    )
    if env_text:
        (root / ".env").write_text(env_text, encoding="utf-8")
    if pyproject_text:
        (root / "pyproject.toml").write_text(pyproject_text, encoding="utf-8")
    if with_web_app:
        pkg = root / "src" / root.name.replace("-", "_") / "entrypoints"
        pkg.mkdir(parents=True, exist_ok=True)
        (pkg / "web_app.py").write_text('"""Stub app."""\n', encoding="utf-8")
    return root


def _asgi_call(
    app: Any,
    method: str,
    path: str,
    *,
    body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    query: str = "",
) -> tuple[int, dict[str, str], bytes]:
    """Execute one HTTP request directly against an ASGI FastAPI app without external httpx."""
    raw_body = json.dumps(body).encode("utf-8") if body is not None else b""
    hdr_list: list[tuple[bytes, bytes]] = [(b"host", b"127.0.0.1:8766")]
    if body is not None:
        hdr_list.append((b"content-type", b"application/json"))
    for k, v in (headers or {}).items():
        hdr_list = [(hk, hv) for hk, hv in hdr_list if hk != k.lower().encode("ascii")]
        hdr_list.append((k.lower().encode("ascii"), v.encode("utf-8")))
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": query.encode("utf-8"),
        "headers": hdr_list,
        "client": ("127.0.0.1", 12345),
        "server": ("127.0.0.1", 8766),
    }

    async def _run() -> tuple[int, dict[str, str], bytes]:
        sent_body = False
        done = asyncio.Event()
        status = 500
        resp_headers: dict[str, str] = {}
        chunks: list[bytes] = []

        async def receive() -> dict[str, Any]:
            nonlocal sent_body
            if not sent_body:
                sent_body = True
                return {"type": "http.request", "body": raw_body, "more_body": False}
            await done.wait()
            return {"type": "http.disconnect"}

        async def send(message: dict[str, Any]) -> None:
            nonlocal status, resp_headers
            if message["type"] == "http.response.start":
                status = int(message["status"])
                resp_headers = {k.decode("latin1").lower(): v.decode("latin1") for k, v in message.get("headers", [])}
            elif message["type"] == "http.response.body":
                chunks.append(message.get("body", b""))
                if not message.get("more_body", False):
                    done.set()

        await app(scope, receive, send)
        return status, resp_headers, b"".join(chunks)

    return asyncio.run(_run())


class WebLauncherTest(unittest.TestCase):
    """End-to-end tests for web launcher discovery, lifecycle, HTTP/MCP/OpenWebUI parity, and docs."""

    def setUp(self) -> None:
        """Isolate TEMPLATE_DATA_DIR, registry, and LaunchAgent paths in a temp folder."""
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.saved_env = {
            k: os.environ.get(k)
            for k in ("TEMPLATE_DATA_DIR", "TEMPLATE_REGISTRY_FILE", "TEMPLATE_NO_REGISTRY", "TEMPLATE_LAUNCHAGENT_PLIST")
        }
        os.environ["TEMPLATE_DATA_DIR"] = str(self.base / "template-data")
        os.environ["TEMPLATE_REGISTRY_FILE"] = str(self.base / "registry.json")
        os.environ["TEMPLATE_NO_REGISTRY"] = "1"
        os.environ["TEMPLATE_LAUNCHAGENT_PLIST"] = str(self.base / "LaunchAgents" / "com.project-template.hub.plist")

    def tearDown(self) -> None:
        """Restore environment variables and remove temp directory."""
        for key, val in self.saved_env.items():
            if val is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = val
        self.tmp.cleanup()

    def test_discovery_variants(self) -> None:
        """Explicit [web] takes priority; auto-detect handles -web scripts and web_app.py; CLI-only returns None."""
        from project_template.services import web_launcher as wl

        p_toml = _write_min_project(
            self.base / "p-toml",
            env_text="HTTP_PORT=9001\n",
            project_toml_text='[project]\nname = "p-toml"\n\n[web]\nport = 9111\ncommand = ["python3", "custom.py"]\n',
        )
        spec_toml = wl.discover_web_service(p_toml)
        assert spec_toml is not None
        self.assertEqual((spec_toml.port, spec_toml.url, spec_toml.source), (9111, "http://127.0.0.1:9111", "project.toml"))
        self.assertEqual(spec_toml.command, ["python3", "custom.py"])

        p_web = _write_min_project(
            self.base / "p-web",
            env_text="HTTP_PORT=9112\n",
            pyproject_text='[project]\nname = "p-web"\n[project.scripts]\np-web-api = "pkg:main"\n',
        )
        spec_web = wl.discover_web_service(p_web)
        assert spec_web is not None
        self.assertEqual(spec_web.command, ["uv", "run", "p-web-api"])

        p_sub = _write_min_project(
            self.base / "p-sub",
            env_text="HTTP_PORT=9113\n",
            pyproject_text='[project]\nname = "p-sub"\n[project.scripts]\np-sub = "pkg:main"\n',
            with_web_app=True,
        )
        spec_sub = wl.discover_web_service(p_sub)
        assert spec_sub is not None
        self.assertEqual(spec_sub.command, ["uv", "run", "p-sub", "web", "--port", "9113", "--no-open"])

        p_cli = _write_min_project(
            self.base / "p-cli",
            env_text="LOG_LEVEL=INFO\n",
            pyproject_text='[project]\nname = "p-cli"\n[project.scripts]\np-cli = "pkg:main"\n',
        )
        self.assertIsNone(wl.discover_web_service(p_cli))

    def test_start_reuse_logs_stop_and_unmanaged_protection(self) -> None:
        """Start detached dummy HTTP server, detect already_running, read logs, stop cleanly, and never kill external procs."""
        from project_template.services import web_launcher as wl

        port = _free_port()
        proj = _write_min_project(
            self.base / "projects" / "dummy-web",
            project_toml_text=(
                '[project]\nname = "dummy-web"\n\n[web]\n'
                f'port = {port}\n'
                f'command = ["{sys.executable}", "-m", "http.server", "{port}", "--bind", "127.0.0.1"]\n'
            ),
        )
        started = wl.start_project_web(proj, wait_seconds=10.0)
        try:
            self.assertTrue(started["started"])
            self.assertTrue(started["running"])
            self.assertTrue(started["managed"])
            self.assertIsNotNone(started["pid"])

            reused = wl.start_project_web(proj, wait_seconds=5.0)
            self.assertFalse(reused["started"])
            self.assertTrue(reused["already_running"])

            logs = wl.read_web_logs(proj, lines=20)
            self.assertTrue(any("start dummy-web" in line for line in logs["lines"]))

            stopped = wl.stop_project_web(proj)
            self.assertTrue(stopped["stopped"])
            self.assertFalse(stopped["running"])
            self.assertFalse(wl.port_listening(port))
        finally:
            if proj.exists():
                wl.stop_project_web(proj)

        # External unmanaged listener on another port must NOT be killed by stop_project_web.
        ext_port = _free_port()
        ext_proj = _write_min_project(
            self.base / "projects" / "ext-web",
            project_toml_text=(
                '[project]\nname = "ext-web"\n\n[web]\n'
                f'port = {ext_port}\n'
                f'command = ["{sys.executable}", "-m", "http.server", "{ext_port}", "--bind", "127.0.0.1"]\n'
            ),
        )
        ext_proc = subprocess.Popen(
            [sys.executable, "-m", "http.server", str(ext_port), "--bind", "127.0.0.1"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            import time

            for _ in range(40):
                if wl.port_listening(ext_port):
                    break
                time.sleep(0.1)
            self.assertTrue(wl.port_listening(ext_port))

            refused = wl.stop_project_web(ext_proj)
            self.assertFalse(refused["stopped"])
            self.assertTrue(refused["running"])
            self.assertIsNone(ext_proc.poll(), "external process must remain alive")
        finally:
            ext_proc.terminate()
            ext_proc.wait(timeout=5)

    def test_http_endpoints_and_ui_contracts(self) -> None:
        """FastAPI app serves launcher UI with no-store, OpenAPI /docs, guards Host/Origin, and enforces confirm."""
        from project_template.entrypoints.web_ui import create_app

        port = _free_port()
        projects_dir = self.base / "ws"
        _write_min_project(
            projects_dir / "app-one",
            project_toml_text=(
                '[project]\nname = "app-one"\n\n[web]\n'
                f'port = {port}\n'
                f'command = ["{sys.executable}", "-m", "http.server", "{port}", "--bind", "127.0.0.1"]\n'
            ),
        )
        app = create_app()

        st_home, hdr_home, body_home = _asgi_call(app, "GET", "/")
        self.assertEqual(st_home, 200)
        self.assertEqual(hdr_home.get("cache-control"), "no-store")
        html = body_home.decode("utf-8")
        self.assertIn('id="web-launcher"', html)
        self.assertIn('href="/docs"', html)

        st_docs, _, _ = _asgi_call(app, "GET", "/docs")
        self.assertEqual(st_docs, 200)

        st_evil_host, _, _ = _asgi_call(app, "GET", "/api/web/services", headers={"host": "evil.example"})
        self.assertEqual(st_evil_host, 403)

        st_evil_orig, _, _ = _asgi_call(
            app,
            "POST",
            "/api/web/start",
            body={"project": "app-one", "root": str(projects_dir), "confirm": True},
            headers={"origin": "http://evil.example"},
        )
        self.assertEqual(st_evil_orig, 403)

        st_list, _, body_list = _asgi_call(app, "GET", "/api/web/services", query=f"root={projects_dir}")
        self.assertEqual(st_list, 200)
        services = json.loads(body_list.decode("utf-8"))
        self.assertEqual([s["name"] for s in services], ["app-one"])
        self.assertFalse(services[0]["running"])

        st_no_confirm, _, _ = _asgi_call(
            app,
            "POST",
            "/api/web/start",
            body={"project": "app-one", "root": str(projects_dir), "confirm": False},
        )
        self.assertEqual(st_no_confirm, 428)

        try:
            st_start, _, body_start = _asgi_call(
                app,
                "POST",
                "/api/web/start",
                body={"project": "app-one", "root": str(projects_dir), "confirm": True},
            )
            self.assertEqual(st_start, 200, body_start.decode("utf-8"))
            self.assertTrue(json.loads(body_start.decode("utf-8"))["running"])

            st_logs, _, body_logs = _asgi_call(app, "GET", "/api/web/logs", query=f"project=app-one&root={projects_dir}")
            self.assertEqual(st_logs, 200)
            self.assertTrue(json.loads(body_logs.decode("utf-8"))["lines"])

            st_stop_all, _, body_stop_all = _asgi_call(
                app,
                "POST",
                "/api/web/stop-all",
                body={"root": str(projects_dir), "confirm": True},
            )
            self.assertEqual(st_stop_all, 200)
            self.assertEqual(len(json.loads(body_stop_all.decode("utf-8"))["stopped"]), 1)
        finally:
            from project_template.services import web_launcher as wl

            wl.stop_all_project_webs(projects_dir)

    def test_mcp_tools_parity_and_confirm(self) -> None:
        """MCP server exposes all 5 web launcher tools and guards mutating calls behind confirm=True."""
        from mcp import Client

        from project_template.entrypoints.template_mcp import build_template_mcp

        port = _free_port()
        projects_dir = self.base / "mcp-ws"
        _write_min_project(
            projects_dir / "mcp-app",
            project_toml_text=(
                '[project]\nname = "mcp-app"\n\n[web]\n'
                f'port = {port}\n'
                f'command = ["{sys.executable}", "-m", "http.server", "{port}", "--bind", "127.0.0.1"]\n'
            ),
        )

        async def _exercise() -> tuple[set[str], list[dict[str, Any]], str, str, str]:
            async with Client(build_template_mcp()) as client:
                names = {t.name for t in (await client.list_tools()).tools}
                listed = await client.call_tool("list_web_services", {"folder": str(projects_dir)})
                s_pending = await client.call_tool("start_project_web", {"project": "mcp-app", "folder": str(projects_dir)})
                stop_pending = await client.call_tool("stop_project_web", {"project": "mcp-app", "folder": str(projects_dir)})
                all_pending = await client.call_tool("stop_all_project_webs", {"folder": str(projects_dir)})
                return (
                    names,
                    list(listed.structured_content["result"]),
                    s_pending.content[0].text,
                    stop_pending.content[0].text,
                    all_pending.content[0].text,
                )

        names, listed_rows, s_pending, stop_pending, all_pending = asyncio.run(_exercise())
        expected = {"list_web_services", "start_project_web", "stop_project_web", "stop_all_project_webs", "get_project_web_logs"}
        self.assertTrue(expected.issubset(names))
        self.assertEqual([r["name"] for r in listed_rows], ["mcp-app"])
        self.assertIn("Not run yet", s_pending)
        self.assertIn("Not run yet", stop_pending)
        self.assertIn("Not run yet", all_pending)

    def test_launchagent_autostart_plist_and_docs_sync(self) -> None:
        """install/uninstall_autostart manage a valid plist at overridden path; AGENTS.md & GEMINI.md list hub.py."""
        from project_template.services import hub_manager as hm

        res_on = hm.install_autostart(port=8766)
        plist_path = Path(res_on["plist"])
        self.assertTrue(plist_path.is_file())
        data = plistlib.loads(plist_path.read_bytes())
        self.assertEqual(data["Label"], "com.project-template.hub")
        self.assertIn("--no-browser", data["ProgramArguments"])
        self.assertTrue(data["RunAtLoad"])

        res_off = hm.uninstall_autostart()
        self.assertTrue(res_off["removed"])
        self.assertFalse(plist_path.exists())

        for doc in ("AGENTS.md", "GEMINI.md"):
            content = (TEMPLATE_ROOT / doc).read_text(encoding="utf-8")
            self.assertIn("python3 scripts/hub.py start", content, doc)
            self.assertIn("python3 scripts/hub.py launch", content, doc)


if __name__ == "__main__":
    unittest.main()
