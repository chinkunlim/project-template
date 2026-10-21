"""Run the web page and the MCP server inside a uv-managed environment when their packages are missing.

Purpose:
    The template's framework scripts need only the standard library, but the web page and the MCP
    server need FastAPI, uvicorn and MCP. Instead of installing them on the host, `ensure_dependencies()`
    re-runs the launcher through `uv run --with ...` (a cached environment managed by uv). The pinned
    versions are the same as in `pyproject.toml`.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

REQUIREMENTS = ("fastapi==0.156.4", "uvicorn==0.54.0", "mcp==2.3.0", "pydantic==2.14.1")
REEXEC_FLAG = "TEMPLATE_TOOLS_REEXEC"


def ensure_dependencies(script: Path) -> None:
    """Re-run `script` inside a uv-managed environment when FastAPI / MCP are not importable.

    Args:
        script: The launcher to re-run (its arguments are kept).
    """
    try:
        import fastapi  # noqa: F401
        import mcp  # noqa: F401
        import uvicorn  # noqa: F401
        return
    except ImportError:
        pass
    if os.environ.get(REEXEC_FLAG) == "1":
        sys.exit("❌ 無法載入 fastapi / mcp：uv 暫存環境建立失敗（檢查網路後再試）")
    uv = shutil.which("uv")
    if not uv:
        sys.exit("❌ 需要 uv（brew install uv）：網頁與 MCP 在 uv 管理的暫存環境執行，不安裝到主機")
    os.environ[REEXEC_FLAG] = "1"
    argv = [uv, "run", "--quiet", "--no-project", "--python", "3.11"]
    for requirement in REQUIREMENTS:
        argv += ["--with", requirement]
    os.execv(uv, [*argv, "python", str(script), *sys.argv[1:]])
