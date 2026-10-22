# ADR-003：每個有函式的程式檔都要建立模組 logger（code-review-guard 強制）

- **狀態**：Accepted <!-- Proposed | Accepted | Superseded by ADR-NNN -->
- **日期**：2026-10-22
- **Agent**：`claude-code`
- **任務**：`-`

## 1. 背景與問題

使用者要求母版與它建立的每個專案、每種語言的每個程式都自動有 log。原本只擋 Python 非 entrypoints 層的 print，從不檢查 logger 是否存在；JS/GAS 只被要求用 console.*，Go/Rust 沒有任何 log。

## 2. 評估過的方案

| 方案 | 優點 | 缺點 |
|---|---|---|
| A. 只在文件（AGENTS.md 規則 12、CODING_PRINCIPLES §0.4）要求 | 不動框架檔 | 沒有人檢查；之後新寫的檔案照樣漏掉 logger |
| B. code-review-guard 新增可設定的規則：在 `[architecture] layers` 某層、有定義函式的程式檔，必須建立模組 logger（CRITICAL，pre-commit 會擋）；每種語言的範本都先附 logger | 新寫的程式也自動被要求；訊息依語言給出寫法；舊專案可以先不開 | 改到所有專案共用的框架檔（review_guard、project_config），舊專案更新後若自行開啟要補 logger |
| C. 用 lint 外掛（ruff / eslint 規則）檢查 | 編輯器即時提示 | 每種語言各要一套外掛與設定；GAS、Go、Rust 沒有現成規則；違反「不污染主機」也增加依賴 |

## 3. 決策與理由

採用 B。

- 設定：`.agents/project.toml` `[quality] require_logger = true`、`logger_exempt_layers = []`（例如純函式的 `domain` 可列入）。`project_config.DEFAULT_CONFIG` 的預設是 **false**：框架更新不會讓還沒開啟的舊專案突然被擋；新專案的 `project.toml` 範本（`packs/stack_config.py`）預設 **true**。
- 範圍：只檢查屬於某一層、有定義函式的原始碼檔；測試檔、沒有函式的檔案（純資料、型別、`__init__.py`）不檢查。訊息標籤是 `[Logging]`（從 `legacy/` 原樣搬入時可延後一次）。
- 各語言「建立模組 logger」的判定：
  - Python：模組層級 `logger = logging.getLogger(__name__)`（或 `get_logger(...)`）。
  - JS / TS（Node、web、GAS、mobile）：`const logger = createLogger("<模組>")`（或 `getLogger(...)`），或該檔本身定義 `createLogger`。GAS 所有檔案共用全域，所以在函式內 `var log = createLogger("Main")`。
  - Go：`slog.With / New / Default(...)`；範本用 `func logger() *slog.Logger { return slog.Default().With("module", "<名稱>") }`，在 `SetupLogging` 換掉預設 handler 後也會生效。
  - Rust：`use log::...` / `tracing::...`。
- 各語言的中央設定（有 run id；執行環境允許時寫 `DATA_DIR/logs/app.log` 與 `errors.log`）：Python `config/logging_setup.py`（既有）；Node `src/config/logger.js`；Go `internal/config/logging.go`（log/slog）；Rust `src/logging.rs`（log crate）。瀏覽器（`web/logger.js`）、GAS（`src/Log.js`）、手機（`mobile/src/config/logger.ts`）不能寫檔，只寫 console / 裝置 log，但同樣有 run id 與模組名。

## 4. 影響與代價

- 框架版本升到 3.4.0。`agentctl update` 會更新 review_guard 與 project_config，但不會改專案的 `project.toml`：舊專案要自己加 `require_logger = true` 才會開始檢查（建議先跑一次 review_guard 看缺哪些檔）。
- Rust 專案多了 `log = { version = "0.4", features = ["std"] }` 依賴（第一次 `cargo build` 需要網路）。
- 母版自己的 `.agents/project.toml` 也開啟 `require_logger = true`（`packs/` 與 `config/`、`entrypoints/` 都已建立模組 logger）。
- 測試：`LoggerRuleTest`（每種 stack 產生的專案在規則開啟下通過 `agentctl check`；Python services 檔缺 logger 時為 CRITICAL；`scripts/init_project.py` 會把帶 run id 的 log 寫進 `<DATA_DIR>/logs/app.log`）。
