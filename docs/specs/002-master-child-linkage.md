# SPEC-002：母版與各子專案雙向連動＆零警告重構（Master–Child Live Linkage）

- **狀態**：Approved <!-- Draft | Approved | Implemented | Deprecated -->
- **日期**：2026-11-24
- **相關任務 / ADR**：[ADR-002](../adr/002-tracked-projects.md)、[ADR-005](../adr/005-support-global-graphify-and-superpowers.md)、[SPEC-001](001-project-web-launcher.md)

## 1. 目標

1. **清除母版既有的 32 個 `[IMPORTANT]` Code Review Guard 警告**（核心規則 15），使 `code-review-guard` 與 `agentctl check` 達成 0 CRITICAL、0 IMPORTANT，`agentctl scan` 綜合評分達到 `100 / 100 (A+)`。
2. **母版 ⇄ 子專案無縫雙向連動（免來回切換資料夾）**：
   - 新建 `--with api` 專案或既有專案補加 FastAPI 服務時，自動分配不衝突埠號、寫入 `.agents/project.toml` `[web]`，並於母版總控台網頁（含分頁切回 / 聚焦自動刷新與輪詢）自動現身，無需人工補登。
   - 在母版網頁、HTTP JSON API、MCP 工具、Open WebUI 工具與 `scripts/hub.py` 單一入口直接操作各子專案：觸發單一或全部專案的 AST 依賴圖 + Graphify 圖譜更新（`agentctl graph` + `graphify update .`）、檢視進行中任務卡數量/摘要與 Graphify 最新狀態、執行 `scan` / `sync` / `graph` 指令，以及直接對任一專案的 `docs/TEMPLATE_FEEDBACK.md` 新增建議與更新狀態（`已採用` / `不採用` / `待決定`）。

## 2. 使用情境與需求對齊（`LOCAL_AI_ENVIRONMENT.md` §2）

1. **誰用、在哪裡用**：本機開發者與 AI Agent 於 macOS 本機使用，所有 HTTP 服務維持只綁 `127.0.0.1`。
2. **動作分類**：
   - **唯讀 / 本機派生報告**：讀取各專案進行中任務卡（`.agents/tasks/TASK-*.json`）、`graphify-out/` 狀態、自動偵測新舊 Web 服務、執行 `agentctl scan --skip-tests` / `agentctl graph` / `graphify update .`（僅寫入 git-ignored 圖譜輸出，安全可重跑）。
   - **變更專案版本控管檔案（強制 `confirm: bool = False` 確認閘門）**：`agentctl sync`、在 `<project>/docs/TEMPLATE_FEEDBACK.md` 新增改進建議、或更改回饋列狀態。
3. **AI 工具接入（核心規則 13）**：HTTP OpenAPI 路由（`entrypoints/linkage_routes.py` + `web_routes.py`）、MCP 工具（`entrypoints/template_mcp_hub.py`）、Open WebUI Tool（`entrypoints/openwebui_tool.py`）、總控台網頁（`entrypoints/web/index.html`）與 CLI（`entrypoints/hub_cli.py`）共用同一組 `services/` 實作。

## 3. 需求

- **必須 (Must)**：
  - **自動分配埠號與 `[web]` 設定**：建立 `--with api` Python 專案時，讀取同工作目錄的 `00 init_dev_env/PORTS.md` 與既有追蹤專案所用埠號，自動分配不衝突的本機埠號（測試隔離目錄預設仍為 `8000`），同步寫入 `.env.example`（`HTTP_PORT`）、`.agents/project.toml`（`[web]`）、`docs/INTEGRATIONS.md` 與 `API.md`。
  - **更完整的後補 Web 自動探索**：即使既有專案未填 `.agents/project.toml` `[web]` 且無 `-server` CLI 腳本，只要 `.env` / `.env.example` 有 `HTTP_PORT` 並具備 `entrypoints/http/server.py`、`entrypoints/http/app.py` 或 `scripts/web_ui.py`，`discover_web_service()` 亦可自動辨識啟動指令。
  - **總控台無需手動切換即可自動同步**：網頁於視窗 `focus` / `visibilitychange` 及總覽頁可見期間定期靜默刷新 `/api/overview`，新建或新增 Web 的專案自動出現在 `#web-launcher` 與專案列表。
  - **跨專案 Graphify 與健康掃描**：支援於母版一次或逐一對子專案執行 `agentctl graph` ＋ `graphify update .`、`agentctl scan --skip-tests`、`agentctl sync`，並在總覽列出未完成任務卡數與 Graphify 圖譜狀態。
  - **跨專案 `TEMPLATE_FEEDBACK.md` 雙向讀寫**：支援從母版介面、API、MCP、Open WebUI、CLI 新增建議至指定專案（或母版自身）之 `docs/TEMPLATE_FEEDBACK.md` 表格末尾（保留表格後方說明段落），以及就地切換建議狀態（`已採用` / `不採用` / `待決定`）。
- **不做 (Out of scope)**：
  - 不在母版強行替子專案執行 `git commit` 或 `git push`（回饋編輯或 `sync` 後由使用者決定提交時機）。

## 4. 介面 / API

| 入口 | 名稱 / 路徑 | 權限保護 | 說明 |
|---|---|---|---|
| HTTP GET | `/api/overview?root=` | 唯讀、Host 檢查 | 回傳項目新增 `tasks`（未完成數量與清單）與 `graphify`（`ready`、`updated_at`、`arch_graph`） |
| HTTP POST | `/api/project-command` | `doctor-fix` / `setup` / `sync` 需 `confirm=true` | 擴充支援 `scan`、`graph`、`sync` 指令 |
| HTTP POST | `/api/projects/graphify` | 背景工作（202）、Host/Origin 檢查 | 對單一或全部追蹤專案執行 `agentctl graph` ＋ `graphify update .` |
| HTTP POST | `/api/feedback/add` | Host/Origin ＋ `confirm=true`（否則 428） | 新增一列改進建議至目標專案 `docs/TEMPLATE_FEEDBACK.md` |
| HTTP POST | `/api/feedback/status` | Host/Origin ＋ `confirm=true`（否則 428） | 原地更新指定 `docs/TEMPLATE_FEEDBACK.md` 某列建議之狀態 |
| MCP Tool | `refresh_project_graphify` | 唯讀／派生報告 | 更新單一或全部追蹤專案的依賴圖與 Graphify 圖譜 |
| MCP Tool | `add_template_feedback`, `update_feedback_status` | `confirm: bool = False` | 新增建議與更新狀態，未確認時拒絕寫入 |
| CLI | `hub.py graphify`, `hub.py scan`, `hub.py feedback-add` | 本機執行 | 單一指令即可操作全部追蹤專案 |

## 5. 驗收標準 (BDD Given / When / Then)

- **場景 1（新建 API 專案自動配置埠號與現身總控台）**：
  - **Given** 專案父資料夾含 `00 init_dev_env/PORTS.md`（下一個可用埠號為 `8773`）與一個既有 `8773` 服務或未佔用狀態
  - **When** 使用 `scaffold_project(..., addons=["api", "web"])` 建立新專案
  - **Then** 新專案自動避開已用埠號取得下一個可用埠號，寫入 `.env.example` 的 `HTTP_PORT` 與 `.agents/project.toml` 的 `[web]`，且 `web_launcher.list_web_services()` 立即探索到該服務。
- **場景 2（既有專案後補 FastAPI 自動探索）**：
  - **Given** 一個起初非 `[web]` 設定的專案，於 `.env` 填入 `HTTP_PORT` 並具備 `entrypoints/http/server.py`
  - **When** 呼叫 `web_launcher.discover_web_service(project)`
  - **Then** 自動推導出 `uv run python -m <pkg>.entrypoints.http.server`，母版總覽隨即顯示啟動卡片。
- **場景 3（跨專案任務卡、Graphify 更新與 `scan` 支援）**：
  - **Given** 追蹤專案內含 `in_progress` 任務卡與既有或未建 `graphify-out/`
  - **When** 呼叫 `GET /api/overview` 與 `POST /api/projects/graphify`、`POST /api/project-command` (`scan`)
  - **Then** `overview` 正確呈現 `tasks.count` 與 `graphify.ready`，背景工作執行 `agentctl graph`（及可用的 `graphify update .`）並回傳結果。
- **場景 4（跨專案雙向管理 `TEMPLATE_FEEDBACK.md` 與 `confirm` 保護）**：
  - **Given** 追蹤專案含 `docs/TEMPLATE_FEEDBACK.md`（表格下方尚有說明段落）與任意系統路徑
  - **When** 未帶 `confirm=true` 呼叫 `/api/feedback/add`、帶 `confirm=true` 新增建議（含 `|` 字元）並透過 `/api/feedback/status` 改為 `已採用`
  - **Then** 未確認回傳 428（MCP 回傳 `Not run yet`）；確認後建議安全插在表格最後一列（不破壞下方說明段落）且跳脫 `|`，更新狀態即時寫回該列，越界路徑則回傳 400。
- **場景 5（母版零警告零違規）**：
  - **Given** 完成所有重構與新功能並提交至本機 git
  - **When** 執行 `python3 .agents/skills/code-review-guard/scripts/review_guard.py --json` 與 `python3 scripts/agentctl.py scan --skip-tests`
  - **Then** `review_guard` 回傳 0 CRITICAL、0 IMPORTANT，`agentctl scan` 獲得 `100 / 100`。
