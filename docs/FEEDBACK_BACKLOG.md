# 母版第三級建議與 Web／AI 專案進階能力參考總表 (FEEDBACK_BACKLOG)

> 本文整理自跨專案 [`TEMPLATE_FEEDBACK.md`](TEMPLATE_FEEDBACK.md) 中尚處於 `待決定` 的進階項目（目前共 13 條，基準版本 `v3.6.0`），作為兩項用途的唯一總表：
> 1. **母版合併決策清單**：日後整理下一版母版更新（例如 `v3.7.0` 或選配 Pack）時，逐項決定「納入預設」、「獨立為選配 Pack（`--with ...`）」或「維持單一專案專用（於來源專案標記 `不採用`）」。
> 2. **後續 Web／AI 專案推廣清單**：新建或升級具備 Web UI、長時背景工作、瀏覽器自動化或 LLM 管線的專案時，優先檢視本表並選擇性導入既有實證模式，避免重造輪子。
>
> **即時待決定原始彙整指令**：`python3 scripts/collect_feedback.py`

---

## A. Web／UI／跨裝置進階能力（推廣給所有 Web 專案參考與選用）

這組模式均已在 `notebooklm-batch-studio` 實作並通過驗證，適合所有含 `web`／`api` 的專案在設計或重構前端時選用（其中 `@media (pointer: coarse)` ≥ 44px 觸控熱區與 CSS Motion Tokens 已自 `v3.6.0` 起納入母版預設）。

| 編號 | 能力項目 | 建議導入時機 | 來源專案與實作參考位置 | 合併考量方向 |
|---|---|---|---|---|
| **A1** | **一鍵啟動 macOS `.app` 包裝** | 任何給非技術使用者在 macOS 本機長期使用的 Web Studio | `notebooklm-batch-studio`：`scripts/build_mac_app.sh`、`scripts/launch_app.sh` | 雙擊即在背景喚起 FastAPI 並以 Chrome `--app` 無網址列開啟；可評估做成 `--with api` 選配產物 |
| **A2** | **網頁開發固定 6 步工作流** | 所有從零開發或全面改版 Web UI 的任務 | `notebooklm-batch-studio`：`AGENTS.md` / `docs/TEMPLATE_FEEDBACK.md` (`2026-11-15`) | `DESIGN.md` 對齊 ➔ HTTP/MCP/Web UI 三入口同步 ➔ 桌面/平板/手機三視口檢查 ➔ 參考線對齊 ➔ 動畫一致性 ➔ `design_audit.py` + `agentctl check` |
| **A3** | **完整階層路徑參考線 (Breadcrumb Layout Guides)** | 需頻繁由使用者截圖並請 AI Agent 微調複雜版面的 Web 專案 | `notebooklm-batch-studio`：`docs/TEMPLATE_FEEDBACK.md` (`2026-11-15`) | 參考線點擊複製含視口與父層的完整 DOM 路徑（如 `[desktop 1440px] section#view-study > div#splitStage > button (112x32)`），減少 Agent 定位時間 |
| **A4** | **Layout Tune Mode（8px 網格拖拉微調＋Diff 匯出）** | 多面板 Split / 拖曳調整需求高的工作站介面 | `notebooklm-batch-studio`：`docs/TEMPLATE_FEEDBACK.md` (`2026-11-15`) | 依 桌面／平板／手機 視口各自記憶拖拉尺寸（吸附 8px 網格），並一鍵複製 Copy Layout Diff 給 Agent |
| **A5** | **iPad Apple Pencil 原生互動支援** | 筆記、閱讀器、標註或手寫畫布類 Web 專案 | `notebooklm-batch-studio`：`docs/TEMPLATE_FEEDBACK.md` (`2026-11-15`) | `@media (pointer: coarse)` ≥ 44px 熱區已納入 `v3.6.0`；此項另涵蓋 `pointerType === 'pen'` 自動落筆書寫／螢光筆、手指維持捲動與雙指縮放 |

---

## B. 展示部署與需求治理（跨專案選用）

| 編號 | 能力項目 | 建議導入時機 | 來源專案與實作參考位置 | 合併考量方向 |
|---|---|---|---|---|
| **B1** | **單檔無後端互動 Demo 建置 (`build_demo.py`)** | 需要發布 GitHub Pages 線上展示給他人試用的 Web 專案 | `notebooklm-batch-studio`：`scripts/build_demo.py`、`scripts/demo/`、`docs/demo/` | 直接讀取真實生產前端內嵌成單一 `docs/demo/index.html`＋攔截 `window.fetch` 的 `demo-mock.js`，僅維護一套 UI 即同時支援真實服務與純靜態展示 |
| **B2** | **使用者需求總表（逐條追查與確認狀態）** | 需求頻繁演進、跨多輪對話且需嚴格核對不可遺漏需求的大型專案 | `note-studio`：`docs/specs/`、`docs/TEMPLATE_FEEDBACK.md` (`2026-11-04`) | 於 `docs/specs/` 集中記錄每條使用者需求對應的 transcript 出處、程式碼落實位置與使用者親驗狀態，新要求即時追補 |

---

## C. 長時背景管線、AI 護欄與交付物生命週期（批次／AI／自動化專案選用）

這組模式主要針對需執行數十分鐘至數小時的批次生成、瀏覽器自動化或有明確版本交付要求的專案；其中「Anti-Swallow 禁靜默降級與 `needs_review/` 隔離」已納入 `v3.6.0`。

| 編號 | 能力項目 | 建議導入時機 | 來源專案與實作參考位置 | 合併考量方向 |
|---|---|---|---|---|
| **C1** | **Planner 與 WorkerPool 拆分＋開機自癒＋SSOT 狀態** | 有 DB 佇列與背景 Worker 的 Web／API 專案（`--with api --with db`） | `notebooklm-batch-studio`：`worker_pool.py`、`ISSUE-002`、`ISSUE-035`、`ISSUE-038` | 規劃器與執行池物理分離、啟動時自動回收卡死的殘留 `RUNNING` 任務、禁止記憶體集合與 DB 狀態雙軌失步 |
| **C2** | **交付物版本生命週期保護（Staging / Archive / Finalize / Promote）** | 產出正式報告、PDF、影片等不可誤覆寫之成品的專案 | `note-studio`：`src/note_studio/services/versions.py`、`publish.py`（ADR-012/013/021/022） | 先產出至隔離 staging 區、依內容指紋去重；重跑前必先檢查執行器就緒再全量歸檔舊檔（禁 `rmtree`）；跨四入口同步 `finalized.json` 定稿鎖，須顯式 `promote` 才換版 |
| **C3** | **長時背景管線標準韌性模式** | 需跨 Web/MCP 同步進度與暫停控制的長時間批次作業 | `note-studio`：`services/generator/state_manager.py`、`pause_controller.py`、`domain/quota_parser.py` | 原子寫盤 `state.json` / `pause_request.json`（開新批自動清殘留暫停檔）、安全點暫停續傳、單子步驟重跑、首件人工核准閘門、Worker 心跳、子程序超時看門狗與精確限流重置時間解析 |
| **C4** | **LLM Prompt SSOT 與輸出／模型降級護欄** | 依賴長篇 Prompt 與外部 AI 模型、嚴禁格式截斷或悄悄降級的專案 | `note-studio`：`assets/prompts/`、`services/generator/step_validator.py`、`services/model_auditor.py`、`domain/refusal.py` | 長篇 Prompt 置於 `assets/prompts/*.md` 作為單一真相來源；輸出串接結束標記／結構圍欄／量化契約／錯位／制式拒絕檢查，並比對送出前與回覆後模型防靜默降級 |
| **C5** | **脆弱外部依賴與瀏覽器自動化維護模式** | 無公開 API、仰賴 Playwright / Chrome CDP 操作第三方網頁的專案 | `note-studio`：`src/note_studio/adapters/gemini/README_FOR_AGENTS.md`、`selectors.py`、`scripts/probe_gemini_dom.py` | Adapter 目錄附 `README_FOR_AGENTS.md` 維護契約、選取器支援 `$DATA_DIR/<adapter>-override/` 熱覆寫、附純唯讀探查腳本與失敗 DOM 快照、平行任務使用獨立暫存 profile 並以回覆數 Baseline 防讀舊回合 |
| **C6** | **可攜式純設定 Profile 匯出入與使用者層級 `DATA_DIR` 遷移** | 需在多台電腦間分享設定或讓使用者在 UI 自訂切換資料磁碟的專案 | `note-studio`：`services/profile_service.py`、`services/data_migrator.py`（ADR-010） | 分離純設定與密鑰／業務資料之 JSON/ZIP Profile，並支援經 `~/.config/<project>/` 動態覆寫 `DATA_DIR` 搭配無損遷移服務 |

---

## 後續評估與合併流程

1. 收集各專案最新回饋（在母版根目錄執行）：

```bash
python3 scripts/collect_feedback.py
```

2. 決定合併某項目至母版時，將該規範或骨架加入 `docs/standards/` 或 `src/project_template/packs/`（例如未來的 `--with worker`、`--with demo`、`--with macos-app`），並同步更新受影響來源專案 `docs/TEMPLATE_FEEDBACK.md` 的狀態欄位（`已採用` 或 `不採用`）。
3. 確認不適合通用化的項目，可於來源專案的 `docs/TEMPLATE_FEEDBACK.md` 改為 `不採用`，並在本文件保留說明或標註為各專案專屬實作。
