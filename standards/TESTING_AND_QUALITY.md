# 測試金字塔與品質驗收規範 (Testing & Quality Standards)

> **AI Agent 載入時機**：當新增功能、修復 Bug、調整外部資料解析邏輯或準備執行提交前驗收 (DoD) 時，**必須閱讀並遵守本文件**。專案專屬測試指令與品質門檻定義於 [`.agents/project.toml`](../../.agents/project.toml)。

---

## 1. 三層測試金字塔 (Testing Pyramid)

| 測試層級 | 目錄位置 | 網路與外部依賴 | 執行速度與時機 | 測試重點 |
|---|---|---|---|---|
| **L1 單元測試 (Unit)** | `test/unit/` | **零網路**（純記憶體） | 毫秒級，每次修改必跑 | `shared` 純函式、`config` 驗證、`adapters` 靜態樣本 (Fixture) 解析 |
| **L2 整合測試 (Integration)** | `test/integration/` | **零網路**（注入 `test/helpers/` Fake HTTP / Fake Context） | 秒級，每次 Commit 前必跑 | `entrypoints ➔ core ➔ store` 完整流程、冪等去重、失敗補償與專案自訂規則 (`[project_rules]`) |
| **L3 端對端與模擬 (E2E & Simulate)** | `test/e2e/`、`dev/simulate` | **真實網路與 API**（需 `.env` 金鑰） | 手動或發布前執行 | 驗證真實外部 API 連線、備援切換與端對端流程 |

---

## 2. 靜態樣本驅動測試 (Fixture-Driven Testing)

1. 外部網頁、API 回應、第三方 Webhook Payload 的解析邏輯，**嚴禁在單元測試中直接連網抓取**。
2. 必須先將真實回應去敏後存放在 `test/fixtures/`（如 `sample_response.json`、`sample_page.html`），再由 `test/unit/` 讀取檔案驗證解析純函式。
3. 當外部服務格式改版導致解析失效時：
   - 先記錄 `docs/known-issues/NNN-xxx.md`
   - 將新版樣本存入 `test/fixtures/`
   - 更新解析純函式並補上防回歸測試。

---

## 3. 提交前完成定義 (Definition of Done, DoD)

每次修改完成並執行 `python3 scripts/agentctl.py commit` 前，必須確認（Python 測試與工具一律透過 `uv run` 在專案 `.venv` 執行）：

- [ ] **Coding 原則檢核**：通過 `python3 .agents/skills/code-review-guard/scripts/review_guard.py`（註解規範、單向依賴、秘密、Atomic 函式門檻與 `[project_rules]`）。
- [ ] **離線測試全數通過**：執行 `.agents/project.toml` `[commands] test` 設定之測試指令 100% 綠燈。
- [ ] **錯誤處理與狀態安全**：外部呼叫失敗時具備適當的降級或狀態回滾補償，且不會向終端使用者洩漏內部 Stack Trace 或機密資訊。
- [ ] **目錄樹、圖譜與金鑰檢查**：`python3 scripts/agentctl.py check`（含目錄樹、分層依賴）與金鑰掃描無異常。
- [ ] **知識庫與多 Agent 交接同步**：若有架構決策變更已更新 `docs/adr/DECISIONS.md`；若為踩坑修復已更新 `docs/known-issues/KNOWN_ISSUES.md`；任務狀態已透過 `agentctl task` 更新；結束對話時已補完本機對話摘要（`.agents/conversations/`）。
