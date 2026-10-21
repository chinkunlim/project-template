# ADR-001：母版本身採用新專案的結構

- **狀態**：Accepted <!-- Proposed | Accepted | Superseded by ADR-NNN -->
- **日期**：2026-10-21
- **Agent**：`claude-code`
- **任務**：`-`

## 1. 背景與問題

母版原本自有一套資料夾（core/、lib/、skills/、standards/、packs/、tools/），和它產生的專案不同：沒有 AGENTS.md、交接看板、ADR，自己的程式也不受 agentctl check 的規範約束。使用者要求母版的結構要和生成的專案一樣。

## 2. 評估過的方案

| 方案 | 優點 | 缺點 |
|---|---|---|
| A. 維持母版自有結構，只在 README 說明對應關係 | 不用搬檔案 | 結構仍不同；母版不能用自己的規則與工具，改規則時沒有自我檢查 |
| B. 母版本身就是一個用自己產生的專案（`stack = python`） | 結構完全相同；框架檔案在母版與專案的路徑一樣（安裝 = 路徑對路徑複製）；母版的程式也通過 `agentctl check`、mypy strict、ruff | 一次性大搬家；v3.1 以前的專案，其更新程式不認得新結構，第一次要由母版代為更新 |

## 3. 決策與理由

採用 B。

- 框架檔案（每個專案都會拿到）：`.agents/{bin,hooks,lib,skills}/`、`docs/standards/`（`PROJECT_RULES.md` 除外）、`scripts/agentctl.py`。`framework_install.framework_file_map()` 改成同路徑對應。
- 母版自己的程式：`src/project_template/`，分層 `entrypoints → services → packs → adapters → config`；只有 `config` 讀環境變數，只有 `entrypoints` 用 `print`。
- 指令：`scripts/init_project.py`、`migrate_project.py`、`web_ui.py`、`template_mcp.py`、`collect_feedback.py`、`update_all.py`、`sync_github_skills.py`（只是啟動器，`scripts/` 本來就是留給專案自己的腳本）。
- 框架版本升為 3.2.0；`pyproject.toml` 的版本就是框架版本。

## 4. 影響與代價

- **舊專案升級**：v3.1 以前的 `.agents/bin/update_framework.py` 在母版根目錄找 `init_project.py` 與 `lib/`，找不到就拒絕。所以 `scripts/update_all.py`（與網頁的「更新框架」）改用**母版自己的**更新程式：`update_framework.py --from <母版> --project <專案>`。更新後專案拿到新版更新程式，之後 `agentctl update --from` 也能用。
- **AI 工具設定**：MCP 指令從 `tools/template_mcp.py` 改成 `scripts/template_mcp.py`；母版內的 `.mcp.json`、`opencode.json`、`.agents/mcp_config.json` 已更新，Claude Desktop 等外部設定要手動改路徑。
- **不會複製到專案的檔案**：`src/`、`tests/`、`docs/`（`standards/` 以外）、`AGENTS.md`、`README.md` 等都是母版自己的專案檔案；`.agents/skills/skills.lock.json` 只留在母版。
- 測試 `TemplateLayoutTest` 確認：母版的最上層項目都存在於產生的專案、框架檔案內容與母版相同、母版通過自己的 `agentctl check`。
