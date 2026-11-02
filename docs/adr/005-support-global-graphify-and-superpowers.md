# ADR-005：支援全域 Graphify 代碼圖譜與 Superpowers 開發方法論

- **狀態**：Accepted
- **日期**：2026-11-02
- **Agent**：`antigravity`
- **任務**：`-`

## 1. 背景與問題

隨著開發專案複雜度提高，新專案需要兩項關鍵的 Agent 能力支援：
1. **代碼與架構知識圖譜**（`graphify`）：提供 GraphRAG、AST 依賴解析、社群劃分、God Nodes 識別與 BFS/DFS 路徑查詢。
2. **軟體工程方法論外掛**（`superpowers`）：涵蓋 TDD 測試驅動開發、Brainstorming 需求深思、Subagent 驅動開發、系統化除錯等 15 項工程流程技能。

若每個專案各自安裝這些工具，會導致依賴重複、環境污染與 Git 版本庫混亂（例如 `graphify-out/` 散落未忽略）。

## 2. 評估過的方案

| 方案 | 優點 | 缺點 |
|---|---|---|
| A. 專案內各自安裝 | 專案完全自包含 | 體積龐大、重複安裝、換專案需重新設定 |
| B. 上下游分層解耦（主機全域安裝 + 專案母版生成規則） | 主機共用一套 CLI，新專案自動獲得忽略規則與規格說明，版本庫保持乾淨 | 需在主機 `00 init_dev_env` 完成一次性配置 |

## 3. 決策與理由

採用 **方案 B（上下游分層解耦）**：
1. **主機層（00 init_dev_env）**：
   - 透過 `uv tool install graphifyy` 安裝獨立全域 CLI 至 `~/.local/bin`。
   - 透過 `agy plugin install https://github.com/obra/superpowers` 安裝全域外掛，並同步符號連結至 `~/.claude/skills/`，達成 Antigravity 與 Claude Code 雙軌支援。
   - 在全域 `~/.gitignore_global` 加入 `graphify-out/`。
2. **母版層（01 project_template）**：
   - 在 `src/project_template/packs/stack_config.py` 的 `build_gitignore` 函式中加入 `graphify-out/`，讓每個產出的新專案自動具備忽略規則。
   - 在 `docs/standards/LOCAL_AI_ENVIRONMENT.md` 登錄此二工具的規格與使用方式。

## 4. 影響與代價

- **正面影響**：未來所有新建立的專案資料夾皆可直接呼叫 `graphify .` 與使用 15 項 Superpowers 技能，且 Git 狀態保持乾淨。
- **代價**：重灌或換新 Mac 時，需依據 `00 init_dev_env` 的 SOP 完成對應安裝。
