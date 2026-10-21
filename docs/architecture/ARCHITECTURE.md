# 系統架構 (Architecture)

> 手動維護本檔的「系統概覽」；以下報告由工具自動產生，請勿手動修改。

| 文件 | 內容 | 產生方式 |
|---|---|---|
| [`PROJECT_TREE.md`](PROJECT_TREE.md) | 完整目錄樹 | `agentctl sync` / 每次 commit |
| `GRAPH_REPORT.md` | 模組依賴圖、分層檢查、函式大小 | 需要時 `agentctl graph`（不進 git） |
| `AGENT_AUDIT_REPORT.md` | 各 Agent 的 commit 與任務 | 需要時 `agentctl audit`（不進 git） |

## 系統概覽

母版用自己的結構：框架檔案放在專案會拿到它們的同一個位置，母版自己的程式在 `src/project_template/`。

```text
scripts/*.py（啟動器）
  └─ entrypoints/   init_cli、migrate_cli、feedback_cli、update_all_cli、skills_sync_cli（指令列）
                    web_ui + web_routes（FastAPI 網頁、JSON API、/mcp）、template_mcp（MCP stdio）、openwebui_tool
       └─ services/ scaffold（建立專案）、migration（遷移舊專案）、update_all（更新所有專案）、
                    feedback（彙整改進建議）、template_service（三個入口共用的動作與背景工作）
            └─ packs/    各語言與附加功能的起始檔案、project.toml / .gitignore / CI、AGENTS.md 與 README
                 └─ adapters/ project_registry（.local/projects.json）
                      └─ config/   settings（路徑、環境變數）、framework（.agents/lib）、runtime（uv 暫存環境）
```

- **建立專案**：`scaffold.scaffold_project()` 寫入專案文件（`packs/`）、依 `framework_file_map()` 同路徑複製框架檔案、產生語言範本、寫 `.agents/framework.lock`、`git init` 並 commit。
- **更新專案**：`update_all` 對每個專案執行母版的 `.agents/bin/update_framework.py --project <專案>`，依 `framework.lock` 只更新專案沒改過的檔案。
- **外部服務**：只有本機：git、uv（`uv lock`、網頁與 MCP 的暫存環境）、`gh`（推送）。網頁只綁 `127.0.0.1`。

## 分層

見 `.agents/project.toml` 的 `[architecture] layers` 與 [`ARCHITECTURE_RULES.md`](../standards/ARCHITECTURE_RULES.md)。
