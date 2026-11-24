"""Offline integration tests for Master-Child live linkage (SPEC-002)."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

TEMPLATE_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = TEMPLATE_ROOT / "src"
TESTS_DIR = Path(__file__).resolve().parent
for _dir in (SRC_DIR, TESTS_DIR):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

from test_web_launcher import _asgi_call, _write_min_project  # noqa: E402


class MasterLinkageTest(unittest.TestCase):
    """Verify auto-port/[web] generation, fallback discovery, overview enrichment, graphify, and feedback writes."""

    def setUp(self) -> None:
        """Isolate environment variables for registry, data dir, and uv locking."""
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.saved_env = {
            k: os.environ.get(k)
            for k in ("TEMPLATE_DATA_DIR", "TEMPLATE_REGISTRY_FILE", "TEMPLATE_NO_REGISTRY", "TEMPLATE_SKIP_UV_LOCK")
        }
        os.environ["TEMPLATE_DATA_DIR"] = str(self.base / "template-data")
        os.environ["TEMPLATE_REGISTRY_FILE"] = str(self.base / "registry.json")
        os.environ["TEMPLATE_NO_REGISTRY"] = "1"
        os.environ["TEMPLATE_SKIP_UV_LOCK"] = "1"

    def tearDown(self) -> None:
        """Restore environment variables and remove temp directory."""
        for key, val in self.saved_env.items():
            if val is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = val
        self.tmp.cleanup()

    def test_auto_port_allocation_web_toml_and_fallback_discovery(self) -> None:
        """Scaffolding `--with api` allocates non-colliding ports and writes `[web]`; fallback finds server.py."""
        from project_template.services.scaffold import ScaffoldOptions, scaffold_project
        from project_template.services.web_launcher import discover_web_service, list_web_services

        ws = self.base / "ws"
        ports_dir = ws / "00 init_dev_env"
        ports_dir.mkdir(parents=True)
        (ports_dir / "PORTS.md").write_text(
            "| 埠號 | 服務 |\n|---|---|\n| 8772 | video-studio |\n\n**下一個可用的埠號**：`8773`。\n",
            encoding="utf-8",
        )

        p1 = ws / "demo-api"
        scaffold_project(p1, "demo-api", ScaffoldOptions(stack="python", addons=["api", "web"], init_git_repo=False))
        self.assertIn("HTTP_PORT=8773", (p1 / ".env.example").read_text(encoding="utf-8"))
        toml1 = (p1 / ".agents" / "project.toml").read_text(encoding="utf-8")
        self.assertIn("[web]", toml1)
        self.assertIn("port = 8773", toml1)
        self.assertIn('command = ["uv", "run", "demo-api-server"]', toml1)

        p2 = ws / "demo-second"
        scaffold_project(p2, "demo-second", ScaffoldOptions(stack="python", addons=["api"], init_git_repo=False))
        self.assertIn("HTTP_PORT=8774", (p2 / ".env.example").read_text(encoding="utf-8"))

        late = _write_min_project(
            ws / "late-api",
            env_text="HTTP_PORT=9120\n",
            pyproject_text='[project]\nname = "late-api"\n[project.scripts]\nlate-api = "late_api.entrypoints.cli:main"\n',
        )
        server_mod = late / "src" / "late_api" / "entrypoints" / "http" / "server.py"
        server_mod.parent.mkdir(parents=True, exist_ok=True)
        server_mod.write_text('"""Stub."""\n', encoding="utf-8")

        late_spec = discover_web_service(late)
        assert late_spec is not None
        self.assertEqual(late_spec.port, 9120)
        self.assertEqual(late_spec.command, ["uv", "run", "python", "-m", "late_api.entrypoints.http.server"])

        discovered = {s["name"]: s["port"] for s in list_web_services(ws)}
        self.assertEqual(discovered, {"demo-api": 8773, "demo-second": 8774, "late-api": 9120})

    def test_overview_tasks_graphify_and_commands(self) -> None:
        """Overview includes open tasks and Graphify state; graphify steps & scan/sync confirm guards work."""
        from project_template.entrypoints.web_ui import create_app
        from project_template.services import template_service as ts

        ws = self.base / "ws2"
        proj = ws / "proj-a"
        _write_min_project(proj)
        (proj / "src" / "proj_a").mkdir(parents=True, exist_ok=True)
        (proj / "src" / "proj_a" / "__init__.py").write_text('"""Pkg."""\n', encoding="utf-8")
        (proj / ".agents" / "tasks").mkdir(parents=True, exist_ok=True)
        (proj / ".agents" / "tasks" / "TASK-001-open.json").write_text(
            json.dumps({"id": "TASK-001", "title": "Pending feature", "status": "in_progress"}),
            encoding="utf-8",
        )
        (proj / ".agents" / "tasks" / "TASK-002-done.json").write_text(
            json.dumps({"id": "TASK-002", "title": "Finished task", "status": "done"}),
            encoding="utf-8",
        )
        (proj / "graphify-out").mkdir(parents=True, exist_ok=True)
        (proj / "graphify-out" / "graph.json").write_text("{}", encoding="utf-8")

        app = create_app()
        st_ov, _, body_ov = _asgi_call(app, "GET", "/api/overview", query=f"root={ws}")
        self.assertEqual(st_ov, 200)
        rows = json.loads(body_ov.decode("utf-8"))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["tasks"]["count"], 1)
        self.assertEqual(rows[0]["tasks"]["items"][0]["id"], "TASK-001")
        self.assertTrue(rows[0]["graphify"]["ready"])
        self.assertTrue(rows[0]["graphify"]["updated_at"])

        st_sync_guard, _, _ = _asgi_call(
            app,
            "POST",
            "/api/project-command",
            body={"path": str(proj), "command": "sync", "confirm": False},
        )
        self.assertEqual(st_sync_guard, 428)

        with mock.patch("project_template.services.project_inspector.resolve_graphify", return_value="/usr/bin/graphify"):
            title, steps = ts.graphify_steps({"project": "proj-a"}, ws)
        self.assertIn("proj-a", title)
        self.assertEqual(steps[0][0][1:], ["scripts/agentctl.py", "graph"])
        self.assertEqual(steps[1][0], ["/usr/bin/graphify", "update", "."])

        from project_template.entrypoints import hub_cli

        with mock.patch("project_template.services.project_inspector.resolve_graphify", return_value=None):
            st_graph, _, _ = _asgi_call(
                app,
                "POST",
                "/api/projects/graphify",
                body={"project": "proj-a", "root": str(ws)},
            )
            self.assertEqual(st_graph, 202)
            assert ts.RUNNER.current is not None
            job = ts.wait_for(ts.RUNNER.current, timeout=15)
            self.assertEqual(job.state, "done", "\n".join(job.log))
            self.assertEqual(hub_cli.main(["graphify", str(proj)]), 0)

    def test_feedback_write_status_http_mcp_cli_and_ui_contracts(self) -> None:
        """Bidirectional feedback preserves trailing prose, escapes pipes, and enforces confirm everywhere."""
        from mcp import Client

        from project_template.entrypoints import hub_cli
        from project_template.entrypoints.template_mcp import build_template_mcp
        from project_template.entrypoints.web_ui import create_app
        from project_template.services import feedback as fb

        ws = self.base / "ws3"
        proj = ws / "proj-fb"
        _write_min_project(proj)
        fb_file = proj / "docs" / "TEMPLATE_FEEDBACK.md"
        fb_file.parent.mkdir(parents=True, exist_ok=True)
        fb_file.write_text(
            "# 給專案模板的改進建議\n\n"
            "| 日期 | 建議 | 來源（對話 / 任務） | 狀態 |\n"
            "|---|---|---|---|\n\n"
            "## 1. 詳細展開說明\n\nTrailing details remain untouched.\n",
            encoding="utf-8",
        )

        # Direct service write & trailing section preservation + pipe escaping.
        added = fb.add_suggestion(proj, "Support A | B safely", source="test-suite")
        self.assertEqual(added["text"], r"Support A \| B safely")
        content = fb_file.read_text(encoding="utf-8")
        self.assertLess(content.index(r"Support A \| B safely"), content.index("## 1. 詳細展開說明"))
        self.assertIn("Trailing details remain untouched.", content)

        # HTTP confirm enforcement + outside-project guard.
        app = create_app()
        st_page, _, body_page = _asgi_call(app, "GET", "/")
        self.assertEqual(st_page, 200)
        html = body_page.decode("utf-8")
        for needle in ('id="p-graphify-all"', 'id="f-project"', 'id="f-add"', "visibilitychange", "maybeRefresh"):
            self.assertIn(needle, html)

        st_no_conf, _, _ = _asgi_call(
            app, "POST", "/api/feedback/add", body={"project": "proj-fb", "root": str(ws), "text": "HTTP rule", "confirm": False},
        )
        self.assertEqual(st_no_conf, 428)

        st_add, _, _ = _asgi_call(
            app, "POST", "/api/feedback/add", body={"project": "proj-fb", "root": str(ws), "text": "HTTP rule", "confirm": True},
        )
        self.assertEqual(st_add, 200)

        st_upd, _, body_upd = _asgi_call(
            app, "POST", "/api/feedback/status", body={"file": str(fb_file), "text": "HTTP rule", "status": "已採用", "confirm": True},
        )
        self.assertEqual(st_upd, 200)
        self.assertEqual(json.loads(body_upd.decode("utf-8"))["status"], "已採用")

        outside_fb = self.base / "evil" / "docs" / "TEMPLATE_FEEDBACK.md"
        outside_fb.parent.mkdir(parents=True)
        outside_fb.write_text(fb_file.read_text(encoding="utf-8"), encoding="utf-8")
        st_bad, _, _ = _asgi_call(
            app, "POST", "/api/feedback/status", body={"file": str(outside_fb), "text": "HTTP rule", "status": "已採用", "confirm": True},
        )
        self.assertEqual(st_bad, 400)

        # CLI feedback-add parity.
        rc_cli = hub_cli.main(["feedback-add", str(proj), "CLI linkage idea"])
        self.assertEqual(rc_cli, 0)
        self.assertIn("CLI linkage idea", fb_file.read_text(encoding="utf-8"))

        # MCP parity + create_project backward compatibility.
        async def _exercise_mcp() -> tuple[set[str], str, str, dict[str, Any]]:
            async with Client(build_template_mcp()) as client:
                tools = {t.name for t in (await client.list_tools()).tools}
                create_res = await client.call_tool("create_project", {"name": "x", "folder": str(ws)})
                fb_guard = await client.call_tool(
                    "add_template_feedback", {"project": str(proj), "text": "MCP idea", "confirm": False},
                )
                await client.call_tool("add_template_feedback", {"project": str(proj), "text": "MCP idea", "confirm": True})
                upd_res = await client.call_tool(
                    "update_feedback_status",
                    {"file": str(fb_file), "text": "MCP idea", "status": "不採用", "confirm": True},
                )
                raw = upd_res.structured_content or {}
                payload = raw.get("result", raw) if isinstance(raw, dict) else {}
                return (
                    tools,
                    create_res.content[0].text,
                    fb_guard.content[0].text,
                    dict(payload if isinstance(payload, dict) else {}),
                )

        names, create_txt, fb_guard_txt, upd_res = asyncio.run(_exercise_mcp())
        self.assertTrue({"refresh_project_graphify", "add_template_feedback", "update_feedback_status"}.issubset(names))
        self.assertIn("Not run yet", create_txt)
        self.assertIn("Not run yet", fb_guard_txt)
        self.assertEqual(upd_res["status"], "不採用")


if __name__ == "__main__":
    unittest.main()
