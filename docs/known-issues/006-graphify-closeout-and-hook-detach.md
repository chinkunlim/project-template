# ISSUE-006：session-closeout 未同步更新 Graphify，且 post-commit 背景子行程在 AI Agent 終端結束時被中斷

- **狀態**：🟡 已規避 / 已修正待驗收 (Mitigated) <!-- 🔴 未解決 (open) | 🟡 已規避 (mitigated) | 🟢 已根治 (resolved) -->
- **發現日期**：2026-11-24
- **Agent**：`antigravity`
- **任務**：`01 project_template master linkage`

## 1. 現象

在 AI Agent 工具內執行 `agentctl commit` 或 `agentctl closeout` 提交程式碼後，`graphify-out/.hook.lock` 目錄與大小為 `0` 的 `graphify-out/.hook.log` 留在磁碟上，而 `graphify-out/graph.json` 的更新時間仍停留在數小時前，知識圖譜未更新；同時從未建立過 `graphify-out/` 的專案在收工時也不會建立圖譜。

- **重現步驟**：於工具子終端執行 `python3 scripts/agentctl.py commit ...`，隨即檢查 `graphify-out/.hook.lock` 與 `graphify-out/graph.json` 時間戳記。
- **影響範圍**：所有使用母版 `v3.6.0` 框架 hook 與 `session-closeout` 流程的專案。

## 2. 根本原因

1. `.agents/skills/session-closeout/scripts/closeout_runner.py` 在 `[2/7]` 僅更新入口檔與目錄樹，並未同步呼叫 `.agents/bin/build_graph.py` 與 `graphify update .`，只依賴 commit 後的 `post-commit` hook 間接触發。
2. `.agents/hooks/graphify-refresh.sh` 採用未搭配 `nohup`／`trap EXIT` 與重導向 `< /dev/null` 的簡易 `( ... ) &` 背景執行；當 `git commit` 指令退出且執行階段隨即收回進程群組時，子行程還來不及執行 `graphify update .` 與 `rmdir "$lock"` 就被中斷，留下卡住的 `.hook.lock`。
3. `graphify-refresh.sh` 僅用 `command -v graphify` 查找執行檔，在未將 `~/.local/bin` 納入 `PATH` 的非互動環境下會找不到全域安裝的 `graphify`。

## 3. 修正或規避方式

- 修改 [closeout_runner.py](file:///Users/limchinkun/Desktop/projects/01%20project_template/.agents/skills/session-closeout/scripts/closeout_runner.py)：於 `[2/7]` 新增 `refresh_knowledge_graphs(root)`，同步執行 `build_graph.py` 與 `graphify update .`（搜尋 `PATH`、`~/.local/bin`、`/opt/homebrew/bin`），並先清理空 `.hook.lock`（`Refs: ISSUE-006`）。
- 修改 [graphify-refresh.sh](file:///Users/limchinkun/Desktop/projects/01%20project_template/.agents/hooks/graphify-refresh.sh)：補上 `~/.local/bin` 與 `/opt/homebrew/bin` 查找、`trap _cleanup EXIT` 自動移除 `.hook.lock`、以及 `nohup ... </dev/null >/dev/null 2>&1 &` + `disown` 脫離終端。
- 同步更新 [SKILL.md](file:///Users/limchinkun/Desktop/projects/01%20project_template/.agents/skills/session-closeout/SKILL.md) 文件說明。

## 4. 防回歸

- [`tests/test_tier1_tier2.py`](../../tests/test_tier1_tier2.py)：
  - `Tier1FrameworkFixesTest.test_graphify_hooks_exist_safe_when_missing_and_clear_stale_locks`（驗證缺工具警示、`~/.local/bin/graphify` 離線備援查找與過期 `.hook.lock` 清理）。
  - `Tier1FrameworkFixesTest.test_closeout_refreshes_graphify_synchronously`（驗證 `agentctl closeout` 會同步執行 `build_graph.py` 與 `graphify update .`）。
