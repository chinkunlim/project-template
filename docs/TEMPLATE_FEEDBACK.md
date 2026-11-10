# 給專案模板的改進建議 (TEMPLATE_FEEDBACK)

> 使用者提出「以後每個專案都要這樣」的規則或習慣時，Agent 記在這裡（不直接改模板）。
> 使用者之後決定是否把它更新到專案模板（`01 project_template`），讓所有新專案都有。
>
> - 每條建議一列；**狀態**只用：`待決定`（新建議）、`已採用`（母版已更新）、`不採用`。
> - 使用者在母版執行 `python3 scripts/collect_feedback.py`，會一次列出所有專案中「待決定」的建議。
> - 下方附各項回饋與要求的詳細展開說明。

| 日期 | 建議 | 來源（對話 / 任務） | 狀態 |
|---|---|---|---|
| 2026-11-04 | **iCloud 規則**：只有使用者在當次要求時才可使用 iCloud，且只同步使用者要的 output；對話紀錄、原稿、log 一律不放；沒主動提到就絕不使用，即使上次有同步過。 | note-studio / TASK-002（使用者原話：不管是什麼專案） | 待決定 |
| 2026-11-04 | **Agent 行為鐵律**：只做使用者要求的事、不自作主張（不刪檔、不搬資料夾、不精簡文字）；改格式不改文字（用正文指紋自動檢查）；沒看過實際輸出不可說「修好了」，known-issue 要使用者確認才可標已根治；接手時讀完整 transcript。 | note-studio / TASK-002 | 待決定 |
| 2026-11-04 | **使用者需求總表**：每個專案在 `docs/specs/` 維護一份需求總表（逐條附 transcript 出處、落實位置、使用者確認狀態），新要求立刻加入。 | note-studio / TASK-002 | 待決定 |
| 2026-11-04 | **code-review-guard 支援排除第三方檔案**：目前無法排除 `vendor/`、`*.min.js`，第三方壓縮檔只能放到 `src/` 外面。 | note-studio / TASK-002 | 待決定 |
| 2026-11-10 | **Transcript 習慣分析與技能/規範沉澱**：分析完整對話 full transcript，提取使用者操作習慣與高效率、低 Token 慣例，沉澱為 Skills 與 standards 規範。 | note-studio / feedback #1 | 待決定 |
| 2026-11-10 | **實證檢驗鐵律**：Agent 必須嚴守流程與要求，完成後必須出示實證（snapshot、pilot、虛擬測試），禁絕無實證宣稱完成。 | note-studio / feedback #2 | 待決定 |
| 2026-11-10 | **四層虛擬測試體系**：規範軟體測試、Dummy files 測試、模擬 Dummy 使用者走測、Web App 逐項按鈕與元件功能測試。 | note-studio / feedback #3 | 待決定 |
| 2026-11-10 | **程式編寫鐵律（Coding Principles）**：寫/修程式嚴格遵循 TDD、SOLID、Atomic 等原則。 | note-studio / feedback #4 | 待決定 |
| 2026-11-10 | **資料寫入鐵律（Data Modification）**：寫入 Data 嚴格遵守 TDD、SOLID、Atomic，防範非預期覆寫與改錯內容，格式內容嚴格隔離。 | note-studio / feedback #5 | 待決定 |
| 2026-11-10 | **目錄結構與實用功能推廣**：盤點專案目錄結構與實證功能，提煉為通用母版範本。 | note-studio / feedback #6 | 待決定 |
| 2026-11-10 | **Graphify 整合開發流程與第三方排除**：編程過程納入 Graphify，嚴格排除 3rd party 降噪，藉圖譜診斷專案優化。 | note-studio / feedback #7 | 待決定 |
| 2026-11-10 | **使用者視角端到端 Workflow 視覺化與程式校驗**：討論/調整功能必須附帶從使用者起點到最終輸出的完整 Workflow（不可精簡），並與程式雙向校驗不一致處。 | note-studio / feedback #8 | 待決定 |
| 2026-11-10 | **Taste Skill 重構與美學/心理學/UI/UX 原則**：去 AI 味、修正邊距按鈕缺陷；動工前先出圖過目、學習 Figma 佈局，結合美學與目標受眾認知心理學。 | note-studio / feedback #9 | 待決定 |
| 2026-11-10 | **完整 CLI 架構**：核心功能封裝完整 CLI，便於 MCP、Open WebUI Pipeline 與未來網頁版後端串接。 | note-studio / feedback #10 | 待決定 |
| 2026-11-10 | **iCloud 嚴格同步規範與目錄集中**：僅在不在電腦旁或明確指示時同步，僅放核心 output（如 PDF），集中存放於 `project-data/<專案>/` 避免根目錄散落。 | note-studio / feedback #11 | 待決定 |
| 2026-11-10 | **DATA_DIR 重構與多版本隔離**：從使用者查找視角劃分章節與共用目錄，建立多輪測試與重複產出之版本管理防混淆。 | note-studio / feedback #12 | 待決定 |
| 2026-11-10 | **追蹤文件自動建置與核心原則修改保護**：自動建立 ADR、Known Issues、TODO；修改大原則 md 須經使用者明確同意並寫入 feedback。 | note-studio / feedback #13 | 待決定 |
| 2026-11-10 | **Standards 文件模組化拆分與 Context 優化**：評估拆分 `docs/standards/`，按需漸進載入，避免一次載入過多規範導致記憶混亂。 | note-studio / feedback #14 | 待決定 |
| 2026-11-10 | **新對話冷啟動一致性協議**：建立跨 Session 開工必讀機制，確保新開對話第一時間遵守使用者習慣與約束。 | note-studio / feedback #15 | 待決定 |
| 2026-11-10 | **Closeout 自動沉澱習慣機制**：在 `session-closeout` 流程自動萃取當次對話展現的有效操作與習慣要求。 | note-studio / feedback #16 | 待決定 |
| 2026-11-10 | **一鍵安裝與後期平滑更新鐵律**：專案到最後必須具備一鍵安裝能力（自動處理鎖定依賴、.env 與 DATA_DIR），且必須規劃並記錄後期更新升級與資料安全保護機制。 | 使用者直接指示 | 已採用 |
| 2026-11-10 | **Code Review 零忽視與即時修復鐵律**：執行檢查若有問題不要忽略，必須馬上解決，消除技術債，維持零違規提交。 | 使用者直接指示 | 已採用 |

---

## 2026-11-10 新增建議詳細說明清單

### 1. Transcript 習慣分析與標準/技能轉換
- **分析目標**：分析整個專案對話的完整 `full transcript`（`transcript_full.jsonl`）。
- **核心內容**：提取使用者的個人操作習慣、個人明確要求，以及 Agent 在操作時展現的自動化習慣（例如精確按要求執行不擅自發散）。
- **轉化標準**：
  - 挑選出「有用」、「可降低 Token 消耗」、「可提高執行效率」的模式。
  - 評估並分類轉換為獨立 Skill（例如放在 `.agents/skills/`）或沉澱至 `docs/standards/` 規範文件中。

### 2. 實證檢驗鐵律（Empirical Verification）
- **核心原則**：Agent 必須嚴格遵守使用者的要求與既定作業流程。
- **檢驗要求**：所有任務、修改或功能實作完成後，必須進行客觀「實證檢驗」，絕不可口頭宣稱「已完成」或「已修復」。
- **檢驗手段**：包含快照比對（snapshot）、試點驗證（pilot）、虛擬測試（virtual testing）等具體執行日誌與產出物證明。

### 3. 四層虛擬測試體系
將虛擬測試制度化，分為四個層級進行嚴格驗證並找出修正點：
1. **軟體測試**：單元測試、整合測試、回歸測試（符合 TDD 原則）。
2. **Dummy Files 測試**：使用合成的極端、邊界或特殊格式 dummy files 進行測試，驗證系統容錯能力。
3. **模擬 Dummy 使用者端到端測試**：模擬真實使用者的操作流程（User Journey），完整跑過從輸入到輸出的全部環節。
4. **Web App 逐項互動走測**：逐一測試網頁應用的每一個按鈕（Button）、輸入框、開關與功能，主動抓出邏輯中斷、無響應或邊距排版問題。

### 4. 程式碼修改與編寫鐵律（Coding Principles）
- Agent 在撰寫或修改程式碼時，必須嚴格遵守 Coding Principles 鐵律：
  - **TDD**（Test-Driven Development）：無失敗測試不寫生產代碼。
  - **SOLID**：單一職責、開閉原則、里氏替換、介面隔離、依賴反轉。
  - **Atomic**：原子化修改，一次只做一件事，不夾帶非必要更動。

### 5. 資料寫入鐵律（Data Modification Principles）
- Agent 在寫入、更新 Data（包含資料庫、Markdown 筆記正文、結構化設定檔等）時，同樣必須遵守 Coding Principles 鐵律（TDD、SOLID、Atomic）。
- 嚴格落實防呆檢驗，避免修改到錯誤區塊，或重新改動原本無需改動的內容（落實內容與格式嚴格隔離、正文指紋對比校驗）。

### 6. 檔案與目錄結構及實用功能推廣
- 全面檢視本專案的 files and folder structure 以及在對話/專案中實際使用的各項功能。
- 評估並提煉哪些結構與機制具備高度通用價值，可推廣至其他專案或寫入 `01 project_template` 母版（如出版級筆記防錯工具、審計機制等）。

### 7. Graphify 整合開發流程與第三方降噪
- 將 Graphify 納入編寫程式與架構調整的標準流程。
- **嚴格排除第三方套件**：排除 `vendor/`、`node_modules/`、`.venv/` 及 3rd party 外部庫，避免引入噪聲與知識圖譜污染。
- **架構自檢**：運用 Graphify 定期檢查專案的模組依賴、循環引用與耦合情況，給出專案架構優化建議。

### 8. 使用者視角端到端 Workflow 視覺化與程式一致性校驗
- **全流程繪圖**：在討論專案功能或調整架構時，必須繪製完整的端到端 Workflow 圖（Mermaid）。
- **使用者視角**：必須從「使用者一開始的操作」出發，一路延伸至「最終完整輸出位置」，嚴格禁止精簡化任何步驟。
- **程式雙向比對**：
  - 將 Workflow 圖與實際程式碼逐一對照檢查，確保兩者完全一致。
  - 若有不一致之處，必須明確列出差異清單。
  - 深入分析並向使用者報告：該以 Workflow 為主進行程式重構，還是以程式現狀為主調整流程，並清楚告知技術與體驗原因。

### 9. Taste Skill 重構與美學/心理學/UI/UX 設計原則
- **現狀問題**：目前的 taste skill 未能良好發揮效果，產出的 Web App 充滿 AI 模板味，基礎的 margin、button 排版經常出錯。
- **改善規範**：
  1. **實作前圖面過目**：在寫 code 之前，必須先產出設計佈局圖供使用者審核。
  2. **借鏡 Figma 設計思維**：先構思完整頁面的 Design System 與視覺排版。
  3. **整合設計原則**：融合先前在 `notebooklm-batch-studio` 沉澱的設計原則，從美學、心理學、UI/UX 角度切入。
  4. **受眾心理學套用**：根據專案的目標使用對象，套用相應的認知心理學理論（如降低認知負荷、視覺階層引導）。

### 10. CLI 架構完整性與多生態串接
- 專案的 CLI 指令必須設計完整且健全。
- 確保所有底層功能均可透過標準 CLI 執行，方便未來與 MCP（供 Claude / Antigravity 調用）、Open WebUI Pipeline 串接，同時為後續開發網頁版提供清晰的後端呼叫介面。

### 11. iCloud 嚴格同步規範與目錄集中管理
- **觸發條件**：嚴格規範 iCloud 的使用，只有當使用者主動告知「我不在電腦旁邊」或「要求同步到 iCloud」時才允許同步；未提及時絕不存取。
- **內容過濾**：只同步核心必要的 output（在此專案中僅為產出的最終 PDF 檔案），對話紀錄、原始檔、log 一律不上傳。
- **目錄集中**：必須統一存放於 iCloud 內的 `project-data/<專案名稱>/` 目錄，嚴格禁止每個專案在 iCloud 根目錄自建獨立資料夾，避免目錄日益膨脹散亂。

### 12. DATA_DIR 重構與多版本存放管理
- **目錄結構優化**：檢查並優化本專案的 `DATA_DIR`。從使用者尋找文件的直覺角度出發，規劃哪些資料應放在各章節資料夾（chapter folder），哪些應集中於共用資料夾（unified folder）。
- **多版本防混淆機制**：考量在測試與操作時可能會重複執行很多次，產出大量歷史版本；必須設計清晰的命名與存放機制（如版本號、時間戳記、Run ID），避免檔案覆蓋與混淆。

### 13. 追蹤文件自動建置與核心原則修改保護
- **自動化建檔**：遇到架構變更或 bug 排除時，自動建立 ADR、Known Issues、TODO 等 Markdown 檔案，避免每次都需要人工檢查遺漏。
- **核心文件保護**：大原則的規範文件（如 `CODING_PRINCIPLES.md`、`PROJECT_RULES.md` 等），若需要修改，必須事先取得使用者明確同意，並將修改理由同步記錄於 `docs/TEMPLATE_FEEDBACK.md`。

### 14. Standards 文件模組化拆分與 Context 優化
- 分析現有 `docs/standards/` 底下的所有規範 Markdown 檔案。
- 評估是否需要進一步拆分與模組化，避免 Agent 在開啟任務時一次性載入過多規範文件，導致 Context Window 肥大、注意力分散與記憶混亂。

### 15. 新對話冷啟動一致性協議（Bootstrapping Protocol）
- **解決問題**：解決開啟新對話時，AI Agent 往往無法像前一個對話一樣從一開始就遵守使用者個人習慣與要求的痛點。
- **機制設計**：建立對話初始化規範，確保每次開工第一步強制優先加載個人習慣摘要與工作原則。

### 16. Session-Closeout 自動沉澱習慣機制
- 在 `session-closeout` 收工流程中，加入「提取有價值操作與習慣」的專屬步驟。
- 自動回顧當次對話，條列出使用者的操作偏好、高效率模式與指導要求，增量整理至使用者個人習慣資料庫中。

### 17. 一鍵安裝與後期平滑更新鐵律
- **一鍵安裝**：專案交付時必須提供一鍵啟動/安裝腳本（如 `./install.sh` 或 `python3 scripts/agentctl.py setup`），自動完成環境自檢、鎖定相依套件安裝（`uv sync` / `pnpm install`）、`.env` 建立、`DATA_DIR` 初始化與資料庫遷移。
- **後期平滑更新**：必須規劃並於 `README.md` 記錄更新程序；更新時嚴禁覆蓋或清空使用者的 `.env` 與 `DATA_DIR` 歷史資料；資料庫結構調整必須相容升級。
- **母版落地**：已正式收錄為 `AGENTS.md` 核心規則第 14 條與 `docs/standards/env/install_and_update.md`。

### 18. Code Review 零忽視與即時修復鐵律
- **零忽視原則**：收到 code-review-guard 或 agentctl check 的警告時，嚴禁略過或推延，必須就地重構修復完畢。
- **重構手法**：使用 Early Return 扁平化巢狀過深、拆分函式過長、封裝 DTO 解決參數過多、補齊模組 logger 與標準 Google/Sphinx 註解。
- **母版落地**：已正式收錄為 `AGENTS.md` 核心規則第 15 條與 `docs/standards/coding/code_review_zero_tolerance.md`。


