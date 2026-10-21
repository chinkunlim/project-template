# 01 project_template — 新專案母版（v3.1）

執行一個指令，就為新專案建立**統一的資料夾與文件結構**、AI Agent 規則、交接與溯源紀錄、品質檢查與語言範本。適用情境：**同一時間只有一個 AI Agent 在改程式**，不同 Agent（Claude Code、Gemini/Antigravity、Cursor、Windsurf、Copilot、Codex）或不同對話輪流接手。

---

## 0. 這台電腦需要什麼（只要一次）

| 工具 | 用途 | 安裝 |
|---|---|---|
| git、`python3`（macOS 內建即可） | 執行框架指令 | Xcode Command Line Tools |
| uv | Python 專案（自動下載 Python 3.11 到專案內） | `brew install uv` |
| nvm + Node（`.nvmrc`）＋ corepack pnpm | 網頁、GAS、手機 App | 見 `standards/ENVIRONMENT_AND_DEPENDENCIES.md` |
| Xcode（App Store）、Android Studio | 只有手機 App 需要（iOS / Android 模擬器） | 專案內 `Brewfile` 與 `mobile/MOBILE.md` |

所有套件都裝在各專案資料夾內（`.venv/`、`node_modules/`），不用全域 pip、`npm -g` 或 `sudo`。

---

## 1. 建立新專案

在母版資料夾內執行（路徑有空格，記得加引號；`--target` 換成你的新專案位置）。專案建議和母版放在同一個資料夾（例如 `~/Desktop/projects/`）：第 4 節的 `collect_feedback.py`、`update_all.py` 預設掃描**母版所在的資料夾**，母版搬到哪裡都跟著走（專案放別處時在指令後面加上該資料夾）。

```bash
cd "$HOME/Desktop/projects/01 project_template"
```

```bash
python3 init_project.py --target ~/Desktop/projects/my_app --stack python
```

Python + 網頁 + GAS

```bash
python3 init_project.py --target ~/Desktop/projects/my_app --stack python --with web gas
```

手機 App（Android + iOS）＋ Python 後端；只有 App 時用 `--stack mobile`

```bash
python3 init_project.py --target ~/Desktop/projects/my_app --stack python --with api mobile
```

```bash
python3 init_project.py --target ~/Desktop/projects/my_gas --stack gas
python3 init_project.py --list-skills
```

| 參數 | 說明 |
|---|---|
| `--stack` | 主要語言：`python` / `node` / `gas` / `go` / `rust` / `generic`；`both` = python+web，`all` = python+web+gas，`mobile` = 只有手機 App |
| `--with` | 附加：`web`（`web/` 純 HTML+CSS+JS）、`gas`（`gas/` Apps Script + Node 測試 + 專案內 clasp）、`api`（FastAPI，只綁 127.0.0.1）、`db`（SQLAlchemy 2.0 + Alembic + SQLite）、`ollama`（本機模型 client + 硬體檢查 + PromptRegistry + 隔離區）、`evals`（輸出品質評分）、`mobile`（`mobile/` Expo：React Native + TypeScript，Android 與 iOS 共用） |
| `--timezone` | GAS 時區，預設讀這台電腦（例如 `Asia/Taipei`） |
| `--license` | `MIT` 會產生 LICENSE（預設不授權） |
| `--skills` | 額外安裝 optional skills（例如 `legacy-migration`） |
| `--force` | 允許寫入非空資料夾（預設會拒絕，避免覆蓋既有檔案；此時不會自動 commit） |
| `--no-git` | 不建立 git repo |

建立後（第一次 commit 已自動完成）：

1. 進入新專案，檢查並修復環境（啟用 git hook、建立 `.env` 與 DATA_DIR）：

```bash
cd ~/Desktop/projects/my_app && python3 scripts/agentctl.py doctor --fix
```

2. 打開 `.env` 填入金鑰；安裝依賴（只裝在專案內）：

```bash
python3 scripts/agentctl.py setup --install
```

3. 確認一切正常：

```bash
python3 scripts/agentctl.py check
```

4. 用 Claude Code / Antigravity / Cursor 打開這個資料夾，對 Agent 說「開工」。Agent 會自動讀 `AGENTS.md`，之後用口語即可（「新功能：…」「commit」「收工」「出版本」…，對照表在新專案的 `AGENTS.md` §1 與 `README.md`）。

### 把舊專案搬進新結構

```bash
python3 migrate_project.py --from ~/Desktop/projects/old_app --target ~/Desktop/projects/old_app_v2
```

- 舊專案**不會被修改**；新資料夾由舊 repo clone（保留 git 歷史），舊檔案以 `git mv` 放進 `legacy/`，再套用模板。
- 自動偵測語言（可用 `--stack` / `--with` 指定），產生 `docs/migration/MIGRATION.md`：檔案清單與建議位置、依批次排序的任務卡、`uv add` / `pnpm add` 轉換指令、風險（被追蹤的機密檔等）與完成標準。
- 之後請 Agent 依 `legacy-migration` skill 逐批搬移；**每一批都要符合新專案的全部規範**（註解、型別、分層、測試、文件、uv/pnpm）。
- `python3 scripts/agentctl.py migration --verify` 全部通過才算完成（`legacy/` 清空、check 與測試通過、任務全部完成、README 已改寫…）。
- `--mode maintain`（預設）：舊專案已完工，保留 Flask，只整理結構與規範；`--mode develop`：要繼續開發，Flask 全部改寫成 FastAPI。之後也可用 `agentctl migration --develop` 切換。
- 舊專案必須先 commit（未 commit 的修改不會搬過去）；不是 git repo 的舊資料夾會改成複製（不含 `.env`、金鑰、`.venv`、`node_modules`）。

遷移後的步驟：

1. `cd` 進新資料夾，執行 `python3 scripts/agentctl.py doctor --fix`。
2. 依 `docs/migration/MIGRATION.md` §4.5 把舊資料複製到 `DATA_DIR`（不會自動搬，舊專案的資料原封不動）。
3. 對 Agent 說「繼續遷移」。Agent 依 `legacy-migration` skill 一批一批做：每批**先單獨 commit 原樣搬移**（保留 git 歷史），**下一個 commit 補齊註解、型別、log 與測試**。
4. 進度：`python3 scripts/agentctl.py migration`；全部完成時 `migration --verify` 會通過。

---

## 2. 新專案會有什麼

```text
my_app/
├── AGENTS.md                 # Agent 規則（唯一來源）+「文件放哪裡」對照表 + Skills 索引 + 資料夾摘要
├── CLAUDE.md / GEMINI.md     # 各工具入口（自動產生：CLAUDE.md 匯入 AGENTS.md，其他工具複製 AGENTS.md 的規則段落）
├── README.md  CHANGELOG.md  .env.example  .gitignore
├── .agents/
│   ├── project.toml          # 專案設定：分層、測試指令、品質門檻、啟用的 skills
│   ├── framework.lock        # 框架版本與檔案雜湊（update 時判斷檔案是否被專案修改）
│   ├── bin/                  # 框架腳本：agent_task, auto_commit, doctor, setup_env, update_framework, ...
│   ├── hooks/                # 版本控管的 hooks（core.hooksPath）：pre-commit（秘密、資料檔、code-review-guard）、pre-push
│   ├── handoff/LATEST.md     # 交接看板 + 時間軸（agentctl status 會顯示上一次的下一步）
│   ├── tasks/                # 任務卡
│   ├── lib/                  # 框架共用函式庫
│   └── skills/               # core + 依 stack 安裝的 skills（catalog.json）
├── docs/
│   ├── adr/                  # 架構決策（DECISIONS.md 總表）
│   ├── known-issues/         # 已知問題與根因（KNOWN_ISSUES.md 總表）
│   ├── specs/                # 需求規格
│   ├── architecture/         # ARCHITECTURE.md + 目錄樹（依賴圖、溯源報告需要時才產生，不進 git）
│   └── standards/            # 工程規範（含註解規範）
├── scripts/
│   └── agentctl.py           # 單一入口：status / task / commit / closeout / check / sync / finish / doctor / update …
│                             # （scripts/ 其餘留給專案自己的腳本）
├── src/ tests/ ...           # 語言範本（完整註解、分層、log、可直接跑測試）
└── web/ gas/ mobile/ alembic/ evals/   # 依 --with 加入，各有說明檔（WEB.md、GAS.md、MOBILE.md、DB.md、EVALS.md）
```

---

## 3. 設計重點

1. **統一結構**：所有專案相同的 `docs/` 骨架與 AGENTS.md「文件放哪裡」對照表。命名規則：只有根目錄一份 `README.md`；每個 docs 資料夾用全大寫的說明/總表檔（`DECISIONS.md`、`KNOWN_ISSUES.md`、`SPECS.md`、`ARCHITECTURE.md`），新增紀錄照同資料夾的 `_TEMPLATE.md`。
2. **交接與溯源**：
   - Git trailers（`Agent:` `Model:` `Task:` `Version:`）記錄每個 commit 是誰做的。
   - 每次對話結束由 `agentctl closeout` 在 `.agents/conversations/` 產生**逐字稿＋摘要**兩個檔案（去除個資、只存本機、不進 git，專案結束可刪除）；交接看板 `LATEST.md`（在 git）保留目標、錯誤根因、下一步各一行。
   - 任務卡 `history` 記錄經手過程；需要時 `agentctl audit` 彙整成報告。
   - 版本：commit 只在 `CHANGELOG.md` 的 `## [Unreleased]` 加一行；要發布時 `agentctl finish --tag` 才升版、打本機 tag。
3. **完整註解**：每個檔案開頭說明、每個函數說明與每個參數（Python `Args:`、JS `@param`、Go `//`、Rust `///`）。`code-review-guard` 與 pre-commit hook 會擋下缺漏；範本程式本身就照規範寫。
4. **換電腦也能用、不污染主機**：
   - Python 一律用 uv：`.python-version`（3.11）+ uv 自己下載的直譯器 + `uv.lock` + 專案內 `.venv/`；不用全域 pip。
   - Node 版本寫在 `.nvmrc`、pnpm 版本寫在 `packageManager`（corepack）；工具（clasp 等）是 devDependencies，裝在專案內 `node_modules/`，用 `pnpm exec` 執行；不用 `npm -g`。
   - 型別檢查用 mypy（strict），和 ruff 一樣裝在專案 `.venv`。
   - **路徑不寫死**：框架用相對位置找檔案，專案和母版資料夾都可以搬移或改名（`.agents/project.toml` 的專案名稱才是名字）。專案搬家後執行一次 `agentctl doctor --fix`：`.venv` 內的工具會記住舊位置，doctor 會依 `uv.lock` 重建。
   - 主機只需要 git、uv、nvm（Node + corepack pnpm）；手機 App 另需 Xcode 與 Android Studio（見第 0 節）。hook 納入版本控管；`.claude/skills` 由 `agentctl doctor --fix` 重建；`agentctl setup --install` 一鍵安裝。
5. **資料和程式分開**：輸入、輸出、資料庫、log 都在 `.env` 的 `DATA_DIR`（預設 `~/project-data/<專案>`，可放外接硬碟）；pre-commit 擋下 PDF、壓縮檔、資料庫與超過 10 MB 的檔案。
6. **Git 安全**：commit 訊息一律英文；pre-push hook 擋下未經同意的 push（`ALLOW_PUSH=1` 才放行）；`agentctl pause` 中途離開、`agentctl finish` 專案完成驗收。
7. **AGENTS.md**：「使用者說什麼 → 執行什麼」對照表；核心規則包括出示執行證據、與 ADR 衝突要先問、錯誤與決策即時記錄、通用規則回寫模板（`docs/TEMPLATE_FEEDBACK.md`）；專案特有規則寫 `docs/standards/PROJECT_RULES.md`（模板更新不會覆蓋）。
8. **可擴充、可升級**：Skills 分 core / stack / optional（`skills/catalog.json`）；`agentctl update --from <母版>` 依 `framework.lock` 只更新未被專案修改的檔案，衝突檔另存 `*.template`。
   - **從 v3.0 升級**：v3.1 把框架腳本從 `scripts/` 搬到 `.agents/bin/`、hooks 搬到 `.agents/hooks/`。`update` 會把舊的 `scripts/*.py` 列為「母版已移除」（不會自動刪除）；接著執行 `python3 scripts/agentctl.py doctor --fix` 切換 hooks（`tools/update_all.py --apply` 會自動做這一步），確認後再自行刪除舊檔。

---

## 4. 維護母版

1. 使用時發現「以後每個專案都要這樣」的規則，Agent 會記在該專案的 `docs/TEMPLATE_FEEDBACK.md`（每個專案各一份）。累積一些後，在母版一次列出所有專案中「待決定」的建議（只讀，不修改專案；`--all` 連已決定的也列出，`--out <檔名>` 存成檔案）：

```bash
python3 tools/collect_feedback.py
```

   決定後到各專案的檔案把狀態改成 `已採用` 或 `不採用`。
2. 改完母版，跑測試（見第 6 節），再 commit 母版。
3. 讓既有專案拿到新版框架（被專案改過的檔案不會覆蓋，另存 `*.template`）。一次處理所有專案，先預覽：

```bash
python3 tools/update_all.py
```

   確認後再更新（會再問一次）。乾淨、沒有衝突且 `check` 通過的專案會自動本機 commit；有衝突或沒通過的保留變更讓你檢查；有未 commit 修改的專案會略過。母版本身要先 commit。

```bash
python3 tools/update_all.py --apply
```

   只更新單一專案時，在該專案內執行：

```bash
python3 scripts/agentctl.py update --from "$HOME/Desktop/projects/01 project_template"
```

---

## 5. 母版資料夾結構

```text
01 project_template/
├── init_project.py           # 新專案產生器
├── migrate_project.py        # 舊專案遷移（保留歷史、legacy/、MIGRATION.md、批次任務）
├── lib/                      # → 新專案 .agents/lib/（project_config, framework_install, tree_annotations）
├── core/scripts/             # → 新專案 .agents/bin/（框架腳本，由 agentctl 呼叫）
├── core/hooks/               # → 新專案 .agents/hooks/（core.hooksPath）
├── core/entry/agentctl.py    # → 新專案 scripts/agentctl.py（唯一入口；scripts/ 其餘留給專案自己）
├── tools/                    # 只留在母版：collect_feedback.py（彙整改進建議）、update_all.py（一次更新所有專案）、sync_github_skills.py
├── standards/                # → 新專案 docs/standards/
├── packs/                    # 語言範本：python / api / db / ollama / evals / web / gas / mobile / other_packs、stack_config（project.toml、.gitignore、CI）、migration_plan、docs_templates
├── skills/                   # → 新專案 .agents/skills/（依 catalog.json 選擇）
│   ├── catalog.json          # 每個 skill 的分層、觸發時機、指令
│   └── skills.lock.json      # 上游參考原始碼（釘選 commit + license；只留在母版）
├── .skills-cache/            # 上游參考原始碼快取（git 忽略，不會複製到新專案）
└── tests/test_framework.py   # 框架端對端測試
```

上游參考原始碼不再放進母版或新專案；需要時：`python3 tools/sync_github_skills.py fetch <name>`。

---

## 6. 驗證框架本身

```bash
python3 tests/test_framework.py -v
```

需要網路的實裝測試（預設略過）：用 uv 實際安裝 Python 專案、用 pnpm 實際安裝 Expo 並打包 iOS / Android。

```bash
TEMPLATE_UV_TESTS=1 python3 tests/test_framework.py UvIntegrationTest
```

```bash
TEMPLATE_MOBILE_TESTS=1 python3 tests/test_framework.py MobileIntegrationTest
```
