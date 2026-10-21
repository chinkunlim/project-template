#!/usr/bin/env python3
"""AI-tool integrations for web projects (written together with `--with api`).

Purpose:
    A web project is not just a page: other AI tools must be able to call its features. The
    FastAPI app already serves OpenAPI (`/openapi.json`) and MCP (`/mcp`, plus stdio through
    `uv run <dist>-mcp`). This pack writes the project-level files those tools read on their own,
    and a guide for the tools that are configured in their own settings:
      - `.mcp.json`               : Claude Code (asks once to approve the project server)
      - `opencode.json`           : OpenCode v2 (merged with ~/.config/opencode)
      - `.agents/mcp_config.json` : Antigravity CLI / IDE (workspace MCP config)
      - `.cursor/mcp.json`        : Cursor
      - `.vscode/mcp.json`        : VS Code (Copilot agent mode)
      - `docs/INTEGRATIONS.md`    : Open WebUI (OpenAPI tool server or MCP), Claude Desktop,
                                    Antigravity App, Open Design, Ollama — step by step
    Every config starts the stdio server with `uv run`, inside the project's own `.venv`, and uses
    no absolute paths, so the project can be moved.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from project_template.packs.common import write_file as _write


def _json(data: dict[str, Any]) -> str:
    """Render pretty JSON with a trailing newline.

    Args:
        data: Data to render.

    Returns:
        JSON text.
    """
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def agent_configs(dist: str) -> dict[str, str]:
    """Build the project-level MCP config of each AI tool.

    Args:
        dist: Distribution / command name (the MCP command is `<dist>-mcp`).

    Returns:
        Mapping of repo-relative path -> file content.
    """
    command = f"{dist}-mcp"
    return {
        ".mcp.json": _json({"mcpServers": {dist: {
            "command": "uv", "args": ["run", "--project", "${CLAUDE_PROJECT_DIR:-.}", command]}}}),
        # OpenCode v2 format (`opencode mcp add` writes exactly this): mcp -> servers -> name
        "opencode.json": _json({"mcp": {"servers": {dist: {"type": "local", "command": ["uv", "run", command]}}}}),
        ".agents/mcp_config.json": _json({"mcpServers": {dist: {"command": "uv", "args": ["run", command]}}}),
        ".cursor/mcp.json": _json({"mcpServers": {dist: {
            "command": "uv", "args": ["run", "--project", "${workspaceFolder}", command]}}}),
        ".vscode/mcp.json": _json({"servers": {dist: {
            "type": "stdio", "command": "uv", "args": ["run", "--project", "${workspaceFolder}", command]}}}),
    }


GUIDE = """# 讓其他 AI 工具使用這個專案（INTEGRATIONS）

這個專案的功能有三個入口，背後是同一組 `services`：

| 入口 | 位址 / 指令 | 給誰用 |
|---|---|---|
| 網頁 + JSON API | `uv run {dist}-server` → http://127.0.0.1:{port}（文件在 `/docs`，規格在 `/openapi.json`） | 人、Open WebUI（OpenAPI 工具） |
| MCP（Streamable HTTP） | 同一個伺服器的 http://127.0.0.1:{port}/mcp | Open WebUI、支援 HTTP MCP 的 Agent |
| MCP（stdio） | `uv run {dist}-mcp`（Agent 自己啟動，不用先開伺服器） | Claude Code、Claude Desktop、Antigravity、OpenCode、Cursor、VS Code |

這台電腦有哪些 AI 工具、埠號與已知陷阱：[`standards/LOCAL_AI_ENVIRONMENT.md`](standards/LOCAL_AI_ENVIRONMENT.md)。

新增功能時：先寫在 `services`，再在 HTTP 路由（`entrypoints/http/app.py`）與 MCP 工具（`entrypoints/mcp_server.py`）各接一次，讓網頁、API 和 Agent 的結果永遠一致。會修改或刪除資料的 MCP 工具一定要有 `confirm` 參數，沒有使用者同意就拒絕。

## 自動偵測（打開專案就有）

| 工具 | 設定檔（已產生，可 commit） | 第一次使用 |
|---|---|---|
| Claude Code | `.mcp.json` | 啟動 `claude` 時會詢問是否允許這個專案的 MCP 伺服器，選允許 |
| OpenCode v2 | `opencode.json` | `opencode mcp list` 應顯示 `✓ {dist} connected`（v2 的背景服務會快取，改設定後第一次可能顯示舊結果，再執行一次） |
| Antigravity CLI / IDE | `.agents/mcp_config.json` | 在專案資料夾內使用 `agy` 即可（`agy mcp list` 只列全域設定，看不到專案的；在對話中問「有哪些 MCP 工具」確認）；未設定權限的工具預設會先詢問 |
| Cursor | `.cursor/mcp.json` | Settings → MCP 啟用 `{dist}` |
| VS Code（Copilot agent） | `.vscode/mcp.json` | 開啟檔案上方的 Start |

## Open WebUI（本機 127.0.0.1:8080）

先啟動本專案：

```bash
uv run {dist}-server
```

**方法一：MCP（管理員設定，建議）** — ⚙ 設定 → 管理員 → Integrations → External Tool Servers → **+ Add Connection**：

- Type：**MCP (Streamable HTTP)**
- URL：`http://127.0.0.1:{port}/mcp`（Open WebUI 在 Docker 時改 `http://host.docker.internal:{port}/mcp`，並在 `.env` 設 `HTTP_ALLOWED_HOSTS=host.docker.internal`）
- Auth：None（只在本機）

**方法二：OpenAPI 工具伺服器（一般使用者）** — ⚙ 設定 → Integrations → Tools → ➕，URL 填 `http://127.0.0.1:{port}`。這種方式由**瀏覽器**直接呼叫，所以 `.env` 的 `HTTP_ALLOWED_ORIGINS` 必須包含 Open WebUI 的位址（預設已是 `http://127.0.0.1:8080`）。

對話時在輸入框的 Integrations / Tools 開啟工具。模型要支援工具呼叫，例如 Ollama 的 `qwen2.5`。

## Claude Desktop

Claude Desktop 只讀自己的設定檔（`~/Library/Application Support/Claude/claude_desktop_config.json`），在 `mcpServers` 加入（把路徑換成這個專案的位置；搬移專案後要更新這一行）：

```json
{{"mcpServers": {{"{dist}": {{"command": "uv", "args": ["run", "--project", "<專案資料夾的完整路徑>", "{dist}-mcp"]}}}}}}
```

## Antigravity App 與 Open Design

- Antigravity App：Settings → Customizations → Installed MCP Servers，新增 command `uv`、args `run --project <專案資料夾> {dist}-mcp`。
- Open Design：透過 Antigravity CLI（`agy`）呼叫工具；在專案資料夾內使用 `agy` 時會讀 `.agents/mcp_config.json`。

## Ollama

Ollama 提供模型，本身不呼叫工具：由 Open WebUI 或其他 Agent 選用 Ollama 模型（例如 `qwen2.5`），再透過上面的 MCP / OpenAPI 呼叫本專案。專案自己要用本機模型時，建立專案時加 `--with ollama`。

## 安全

- 伺服器只綁 `127.0.0.1`；只接受 Host 為 127.0.0.1 / localhost（加上 `HTTP_ALLOWED_HOSTS`），網頁送出的修改請求只接受本專案與 `HTTP_ALLOWED_ORIGINS`。
- 工具採最低權限：讀取的工具可以直接用；寫入、刪除、提交或部署要有 `confirm` 並由使用者同意。
- 上傳到模型的內容一律視為不可信任；含金鑰、個資或私有原始碼的內容不要送到外部模型服務。
"""


def scaffold_integrations(target_dir: Path, names: dict[str, str], port: int = 8000) -> None:
    """Write the AI-tool configs and `docs/INTEGRATIONS.md`.

    Args:
        target_dir: Project root directory.
        names: `project` (display name) and `dist` (command name).
        port: HTTP port of the web server (`HTTP_PORT`).
    """
    for rel, content in agent_configs(names["dist"]).items():
        _write(target_dir / rel, content)
    _write(target_dir / "docs" / "INTEGRATIONS.md", GUIDE.format(dist=names["dist"], port=port))
