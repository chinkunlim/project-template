# ISSUE-005：API Key 正則檢測在單字後綴為 sk- 時產生偽陽性

- **狀態**：🟢 已根治 (Resolved)
- **發現日期**：2026-11-01
- **Agent**：`antigravity`
- **任務**：`TASK-001`

## 1. 現象

在包含單字後綴接連字符的專案中（例如 `literature-parser/web/dashboard.html` 包含 `...Risk-Task-...`），執行 `agentctl check`、`review_guard.py` 或 `git commit` 時被安全門禁擋下。

- **錯誤訊息**：`CRITICAL: [Secret] Potential API key found in web/dashboard.html`
- **重現步驟**：在任何納入檢查的檔案中寫入字串 `Risk-Task-Analysis-Report-2026`（長度超過 20 字元）。
- **影響範圍**：`code-review-guard`、`.agents/hooks/pre-commit` 與 `project_config.py` 中的敏感資料防護機制。

## 2. 根本原因

敏感資料正則運算式中對 OpenAI 格式 API Key 的比對規則原本為：
```python
r"sk-[A-Za-z0-9]{20,}"
```
它只比對 `sk-` 開頭，但沒有限定 `sk-` 前面不能是其他英文單字的一部分。當遇到 `Risk-Task-...` 時，`sk-Task-...` 符合 `sk-` 加上 20 個以上字母，造成偽陽性誤報（False Positive）。

## 3. 修正或規避方式

使用正規表示式的負向零寬斷言（negative lookbehind `(?<!...)`），限制 `sk-` 前方不能是英文字母或數字：
```python
r"(?<![A-Za-z0-9])sk-[A-Za-z0-9]{20,}"
```
同步更新：
- `.agents/lib/project_config.py`
- `.agents/skills/code-review-guard/scripts/review_guard.py`
- `.agents/hooks/pre-commit`

程式碼已於 commit `84cec2f` 修復，加註 `Refs: ISSUE-005`。

## 4. 防回歸

在 `tests/test_framework.py` 的安全性測試中加入包含 `Risk-Task` 的合法文字測試案例，確保正常英文單字不會被誤擋。
