# ADR-004：全域雙軌 Skills 軟連結映射 (Dual-Scope Global Skills Symlinking)

- **狀態**：Accepted <!-- Proposed | Accepted | Superseded by ADR-NNN -->
- **日期**：2026-11-01
- **Agent**：`antigravity`
- **任務**：`TASK-001`

## 1. 背景與問題

母版 `01 project_template` 開發了 7 大標準化 Agent Skills（`session-closeout`、`code-review-guard`、`tdd-bugfix`、`adr-issue-tracker`、`api-adapter-scaffold`、`frontend-design`、`legacy-migration`）。
原本這些 Skills 僅能在採用框架的子專案根目錄下被 Agent 調用；在未套用框架的目錄、新專案初始階段（如 `00 init_dev_env`）或母版本身中，Agent 無法在全域發現與執行這些技能。若直接將 Skills 實體複製到使用者的全域設定資料夾，則每當母版修改或升級 Skill 時，全域版本將迅速落後並產生版本漂移。

## 2. 評估過的方案

| 方案 | 優點 | 缺點 |
|---|---|---|
| A. 複製實體目錄至 `~/.gemini/config/skills/` 與 `~/.claude/skills/` | 全域完全獨立，不依賴本機母版路徑 | 母版更新時全域無法自動同步；雙向修改容易衝突；維護成本高 |
| B. 雙軌軟連結映射 (Dual-Scope Symlinks)：全域使用 Symlink 指向母版，子專案保持獨立實體目錄 | 本機任何目錄隨開隨用；母版更新即時全域生效；子專案外發交付時仍具備實體自包含，零依賴主機全域環境 | 需要確保 Skills 內部的腳本在透過 Symlink 被呼叫時，能正確識別「當前工作專案」而非誤判為「母版」 |
| C. 打包成全域 pip/uv 工具發布至 PyPI | 標準 CLI 安裝 | 違反「不污染主機環境」原則；每次小修改皆需發版升版，開發迭代週期過長 |

## 3. 決策與理由

採用方案 B。

- **雙軌架構**：
  1. **本機全域開發軌**：將母版 `.agents/skills/*` 透過符號連結映射至 `~/.gemini/config/skills/` 與 `~/.claude/skills/`。無論在哪個目錄啟動 Antigravity 或 Claude Code，皆可直接自動探索並調用 7 大技能。
  2. **子專案交付發布軌**：子專案仍保有各自獨立實體的 `.agents/skills/`，並由 `python3 scripts/update_all.py` 批次推播更新。跨平台或對外分享時，無須依賴本機使用者的 home 目錄結構。
- **腳本路徑相容性修復**：
  - 修正所有 Skills 腳本中透過 `__file__` 判定專案根目錄的邏輯（如 `closeout_runner.py`、`tracker_cli.py`），改為優先以 `Path.cwd()` 向上尋找 `.agents/project.toml`，避免全域呼叫時誤操作母版目錄（見 ISSUE-004）。

## 4. 影響與代價

- 建立全域軟連結後，本機全環境隨處可用 7 大技能。
- 母版對 Skills 腳本與提示詞的修改會立即反應在全域環境中，無須重新安裝。
- 需在 `agentctl doctor` 與收尾流程中增加軟連結健全度檢查，防範母版目錄更名或刪改導致 dangling symlinks。
