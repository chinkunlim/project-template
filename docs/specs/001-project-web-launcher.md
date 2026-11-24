# SPEC-001：總控台網頁整合專案 FastAPI 啟動器（Project Web Launcher Hub）

- **狀態**：Implemented <!-- Draft | Approved | Implemented | Deprecated -->
- **日期**：2026-11-24
- **相關任務 / ADR**：[ADR-002](../adr/002-tracked-projects.md)

## 1. 目標

於專案母版（`01 project_template`）既有的本機 FastAPI 網頁（`http://127.0.0.1:8766`）整合「子專案網頁快速啟動台」，讓使用者免開多個終端機與記憶指令，即可在單一頁面檢視各專案的 Web 服務即時狀態並一鍵啟動、開啟或停止；同時於 `AGENTS.md`、`GEMINI.md` 與 `PROJECT_RULES.md` 寫明零查找浪費的 `scripts/hub.py` 單一指令集，讓 AI Agent 收到啟動／關閉口語指令時直接執行，零多餘檔案探索與 Token 浪費。

## 2. 使用情境與需求對齊（`LOCAL_AI_ENVIRONMENT.md` §2）

1. **誰用、在哪裡用**：本機單一使用者於 macOS 本機使用，所有服務僅綁 `127.0.0.1`（禁止 `0.0.0.0`）。
2. **動作分類**：
   - **唯讀**：偵測所有追蹤專案（`update_all.tracked_projects()`）是否具 Web 服務、讀取 `http://127.0.0.1:<port>` 即時監聽狀態、讀取起動日誌尾端（`/api/web/logs`）。
   - **變更狀態（MCP 工具強制 `confirm: bool = False`，HTTP POST 強制 `confirm=true`）**：背景啟動專案 FastAPI 服務並等待埠號就緒、停止由母版啟動之子專案服務、一鍵停止全部子專案服務。
3. **AI 工具接入（核心規則 13）**：HTTP JSON API（OpenAPI `/docs`）、MCP Streamable HTTP（`/mcp`）、MCP stdio（`scripts/template_mcp.py`）、Open WebUI Tool（`entrypoints/openwebui_tool.py`）與總控台網頁一次齊接，共同呼叫同一組 `services/web_launcher.py`。
4. **本機模型**：不需呼叫 Ollama。
5. **資料與日誌隔離**：子行程 PID（`<slug>.pid`）與輸出 log（`<slug>.log`）寫於母版 `DATA_DIR/hub/`（測試可用 `TEMPLATE_DATA_DIR` 隔離），不污染各專案目錄與 git 狀態。
6. **省記憶體設計（按需啟停）**：母版總控台僅佔約 50–80 MB 記憶體；子專案平時皆維持關閉（0 MB），點擊才啟動、用畢可單一或一鍵全部停止以釋放記憶體。
7. **精簡啟動方式**：提供 `scripts/hub.py` 統一控制背景啟停、子專案啟停及可選的 macOS `launchd` 開機常駐（`autostart on|off`）。
8. **埠號**：母版維持已登記於 `PORTS.md` 的 `8766`，不佔用新埠號。

## 3. 需求

- **必須 (Must)**：
  - 自動偵測追蹤專案的 Web 服務設定：優先讀取 `.agents/project.toml` `[web]` 區段；若未設定，則自 `.env` / `.env.example` 解析 `HTTP_PORT` 並自 `pyproject.toml` `[project.scripts]` 偵測 `-web` / `-server` / `-api` 或 `web_app.py` 搭配 `web --port <port> --no-open`。
  - 未配置 Web 服務的純 CLI 專案（如 `ndhu-course-rush`）不顯示啟動鈕。
  - 若埠號已由外部終端程序啟動，總控台僅顯示「運行中（外部啟動）」並提供開啟頁面與查看（無外部 log 時提示）功能，嚴禁誤殺非母版管理之外部行程。
  - 首頁「總覽」頂部新增快速啟動卡片區（即時燈號、啟動並開啟、開啟頁面、停止、查看 Log、停止全部子服務）且於總覽表格增設 `Web` 欄位，導覽列提供 `📖 OpenAPI 文件` 連結。
  - 於 `AGENTS.md` §1、`GEMINI.md`（透過 `agentctl sync`）與 `PROJECT_RULES.md` 清楚記錄 `python3 scripts/hub.py` 完整指令表。
- **可選 (Nice to have)**：
  - 透過 `python3 scripts/hub.py autostart on|off` 建立／卸載 macOS `launchd` plist（`~/Library/LaunchAgents/com.project-template.hub.plist`）。
- **不做 (Out of scope)**：
  - 不修改各子專案既有的 Web 後端程式碼。

## 4. 介面 / API

| 入口 | 名稱 / 路徑 | 權限保護 | 說明 |
|---|---|---|---|
| HTTP GET | `/api/web/services?root=` | 唯讀、Host 檢查 | 列出追蹤專案的 Web 服務與即時監聽狀態 |
| HTTP GET | `/api/web/logs?path=&lines=80` | 唯讀、Host 檢查 | 讀取母版啟動紀錄尾端 |
| HTTP POST | `/api/web/start` | Host/Origin＋`confirm=true`（否則 428） | 背景啟動指定專案 FastAPI 並等待埠號就緒 |
| HTTP POST | `/api/web/stop` | Host/Origin＋`confirm=true`（否則 428） | 停止由母版啟動之指定專案服務 |
| HTTP POST | `/api/web/stop-all` | Host/Origin＋`confirm=true`（否則 428） | 停止全部由母版啟動之子專案服務 |
| MCP Tool | `list_web_services`, `get_project_web_logs` | 唯讀 | 對應唯讀查詢 |
| MCP Tool | `start_project_web`, `stop_project_web`, `stop_all_project_webs` | `confirm: bool = False` | 未帶 `confirm=True` 只回傳預定指令而不執行 |

## 5. 驗收標準 (BDD Given / When / Then)

- **場景 1（服務探索規則）**：
  - **Given** 追蹤目錄同時存在含 `-web` script、含 `web_app.py`、含明確 `[web]` 設定以及純 CLI 無 `HTTP_PORT` 的專案
  - **When** 呼叫 `discover_web_service(project)`
  - **Then** 優先採 `[web]` 設定，其次推導 `-web`/`-server`/`-api` 與 `web --port <p> --no-open`，純 CLI 回傳 `None`。
- **場景 2（背景啟動、重入保護與停止釋放）**：
  - **Given** 一個具臨時 FastAPI/HTTP 腳本的專案與隔離 `TEMPLATE_DATA_DIR`
  - **When** 呼叫 `start_project_web` ➔ 再呼叫一次 `start_project_web` ➔ 呼叫 `stop_project_web`
  - **Then** 首次等待 `127.0.0.1:<port>` 就緒並寫入 PID 與 log；第二次回傳 `already_running=True`；停止後 PID 檔移除且埠號停止監聽。
- **場景 3（未管理外部行程保護）**：
  - **Given** 某埠號由非母版紀錄 PID 的外部行程監聽
  - **When** 呼叫 `stop_project_web`
  - **Then** 不得終止該外部行程，並回傳 `stopped=False, running=True` 提示訊息。
- **場景 4（HTTP API、UI 與 MCP 確認閘門）**：
  - **Given** `create_app()` 與 `build_template_mcp()`
  - **When** 以惡意 Host/Origin 或未帶 `confirm=true` 呼叫變更端點與 MCP 工具
  - **Then** HTTP 回傳 403 / 428；MCP 回傳 `Not run yet`；`GET /` 回傳包含 `#web-launcher` 且含 `Cache-Control: no-store`。

## 6. 未決問題

- 是否啟用 `python3 scripts/hub.py autostart on`（開機自動背景常駐約 60 MB 總控台）由使用者確認。
