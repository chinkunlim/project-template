# 🤝 Agent 狀態看板與交接紀錄 (`LATEST.md`)

> **AI Agent 開工必讀**：進入對話時請先閱讀下方「即時狀態看板」，確認上一位 Agent 的完成進度、待接手任務 (`handed_off`) 與注意事項；詳細過程請看本機的 `.agents/conversations/`。

<!-- LIVE_STATE_START -->
## 📊 即時狀態看板 (Live Snapshot)

- **最後更新時間**: `2026-10-21 13:54 UTC`
- **最近操作 Agent**: `claude-code`

### 🎯 進行中 / 待接手任務 (Active & Handed-Off Tasks)

> 目前無進行中或待接手任務。可執行 `python3 scripts/agentctl.py task create "任務名稱" --agent <name>` 建立任務。

<!-- LIVE_STATE_END -->

## 📜 交接與活動時間軸 (Handoff & Activity Timeline)

### [2026-10-21 15:10 UTC] 所有動作追蹤同一組專案、加入既有專案、git fetch (by `claude-code`)
- **狀態**: 專案清單、改進建議、框架更新（網頁、API、MCP、Open WebUI 工具檔、`update_all.py` / `collect_feedback.py`）都改用 `tracked_projects()`（資料夾＋登記清單，ADR-002）；新增「加入既有專案」與「git fetch」。完整測試、`TEMPLATE_UV_TESTS=1` 的整合測試與 `agentctl check` 通過，網頁已在瀏覽器預覽實際操作過。
- **未完成 / 待決定**:
  - 已發布 v3.3.0（tag `v3.3.0`，照 ISSUE-003 的步驟）；接著用 `python3 scripts/update_all.py` 預覽並更新各專案。
  - `src/project_template/services/template_service.py` 有 624 行（建議 ≤ 500）：可把登記清單與 git fetch 相關函式拆成獨立模組（只是警告）。
  - 手機（Expo）整合測試 `MobileIntegrationTest` 未執行（需 `TEMPLATE_MOBILE_TESTS=1`、pnpm、約 300 MB 下載；這次修改與手機無關）。
  - `docs/adr/DECISIONS.md` 中 ADR-001 的「相關程式」欄仍是 TODO（上一個 session 留下）。
  - 瀏覽器預覽無法啟動 `~/Desktop` 內的伺服器（ISSUE-001，macOS 隱私限制），驗證網頁時照該檔的規避方式做。
- **下一步**: 用 `update_all.py` 把各專案更新到 v3.3.0；之後處理上面的拆檔與 ADR-001 TODO。

### [2026-10-21 14:30 UTC] 母版改用新專案的結構 (by `claude-code`)
- **狀態**: 框架 v3.2.0。母版本身就是一個用自己產生的專案（ADR-001）；`agentctl check` 與全部測試通過。
- **下一步**: 用 `python3 scripts/update_all.py` 預覽，再把 literature-fetch、literature-parser 更新到 v3.2.0。
