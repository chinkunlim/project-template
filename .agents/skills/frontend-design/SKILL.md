---
name: frontend-design
description: >-
  Scaffolds and audits production-grade web applications and UI components following
  Anthropic's frontend-design and Vercel's web-design-guidelines (token systems,
  semantic HTML5, responsive breakpoints, keyboard accessibility, and zero layout shift).
  Also enforces visual taste and removes generic "AI slop" (based on Leonxlnx/taste-skill):
  design dials, banned fonts/gradients, and an Anti-Slop auditor with a taste score.
  Activate whenever building, styling or reviewing web apps, dashboards, HTML/CSS/React/Vue UIs, or widgets.
---

# Frontend Design — Web 應用程式工程架構與無障礙規範

> **GitHub 來源基準**：整合自 [`anthropics/skills/frontend-design`](https://github.com/anthropics/skills)、[`vercel-labs/agent-skills/web-design-guidelines`](https://github.com/vercel-labs/agent-skills) 與 [`Leonxlnx/taste-skill`](https://github.com/Leonxlnx/taste-skill)。
> **可執行工具**：[`scripts/frontend_tool.py`](scripts/frontend_tool.py)（骨架、工程與無障礙檢查）、[`scripts/taste_auditor.py`](scripts/taste_auditor.py)（視覺品味與 Anti-Slop 審查）

當專案需要開發 Web-based App、管理後台、資料視覺化儀表板或互動式網頁元件時，啟動本技能確保前端具備**完整設計系統 (Design Tokens)、RWD 響應式佈局、無障礙 (a11y) 與高效能體驗**；視覺品味規則見 §3–§5。

---

## 1. Web App 開發四步工作流 (4-Step Frontend Workflow)

### Step 1：對焦產品情境與產生設計 Token (`frontend_tool.py --scaffold`)
在寫任何元件前，先確立：
1. **核心任務 (Job-to-be-Done)**：使用者打開這個頁面最常做的第一件事是什麼？核心操作必須在首屏（無須捲動）立即可見。
2. **4–6 個命名色彩與間距 Token**：透過 `frontend_tool.py` 自動生成 `tokens.css` 與基礎響應式骨架，禁止在元件內硬編碼散落的 Hex 色碼。

### Step 2：語意化結構與狀態完整性 (Complete UI States)
任何資料驅動的 Web 介面都**必須實作完整的 4 種狀態**（不可只寫 Happy Path）：
- **Loading State**：骨架屏 (Skeleton shimmer) 或非阻塞式進度指示。
- **Empty State**：具引導性的空白狀態圖示與「建立第一筆資料」行動按鈕 (CTA)。
- **Error State**：友善的錯誤提示與「重試 (Retry)」按鈕（不直接印出原始 JSON 或例外訊息）。
- **Populated State**：正常資料呈現，並處理超長文字截斷 (`truncate` / `line-clamp`) 與數字等寬對齊 (`font-variant-numeric: tabular-nums`)。

### Step 3：Vercel 網頁工程與無障礙準則 (Web Design Guidelines)
- **鍵盤與焦點可及性**：所有互動元素必須使用原生 `<button>` / `<a>`，保留清晰的 `:focus-visible` 輪廓；純圖示按鈕必須加上 `aria-label`。
- **表單與輸入體驗**：`<input>` 必須綁定 `<label>`、具備正確 `type` 與 `autocomplete`；行動裝置字級至少 `16px`（防止 iOS Safari 自動放大畫面）。
- **零版面跳動 (Zero CLS)**：`<img>` 與視覺容器必須設定明確長寬比 (`aspect-ratio` 或 `width`/`height`)。

---

## 2. 自動調用 Python 工具 (`frontend_tool.py`)

1. 一鍵在目標資料夾生成生產級 Web App 前端骨架 (含 Anti-Slop Design Tokens、4 種 UI 狀態模版與響應式 Grid)

```bash
python3 .agents/skills/frontend-design/scripts/frontend_tool.py --scaffold src/web --theme warm-craft

```

2. 針對既有前端檔案執行 Vercel Web Design Guidelines (無障礙 a11y、RWD、語意標籤、CLS) 工程審查

```bash
python3 .agents/skills/frontend-design/scripts/frontend_tool.py --check src/
```

---

## 3. 視覺品味：三大設計旋鈕 (The Three Design Dials)

在動手寫任何前端程式碼前，先利用腳本決定或產生本頁面的三個品味旋鈕（1–10）：

| 旋鈕參數 | 低數值 (1–3) | 中數值 (4–7，預設推薦) | 高數值 (8–10) |
|---|---|---|---|
| **`DESIGN_VARIANCE`** (版面變化度) | 對稱雙欄、經典閱讀流 | 非對稱 Bento Grid、錯落雙欄 | 雜誌級破格排版、大膽留白對比 |
| **`MOTION_INTENSITY`** (動態強度) | 僅 Hover 微回饋 | Spring 彈簧物理過渡 + 進場交錯 | 敘事型捲動視差、流體微互動 |
| **`VISUAL_DENSITY`** (視覺密度) | 藝廊模式（大量呼吸留白） | 現代 SaaS 產品工作區 | 專業高密度儀表板（如 Linear / Bloomberg） |

---

## 4. 四大 Anti-Slop 硬性規定

1. **字體禁令與排版階層 (Typography Rules)**：
   - **禁止無腦使用 `Inter`、`Roboto`、`Arial`、`Open Sans` 作為主視覺字體**。
   - 推薦個性化字體組合：`Geist`、`Satoshi`、`Cabinet Grotesk`、`Outfit`、`Plus Jakarta Sans`、搭配襯線 `Instrument Serif` / `PP Editorial New` 與等寬 `JetBrains Mono`。
   - **標題 (Display)**：字距收緊 (`letter-spacing: -0.025em`)、行高緊湊 (`line-height: 1.1`)，桌面版主標題不超過 2 行。
   - **內文 (Body)**：行高舒適 (`line-height: 1.65`)，單行寬度嚴格限制在 `60ch–70ch` (`max-w-prose`)。
2. **色彩與表面質感 (Surface & Color Calibration)**：
   - **禁止純白 `#FFFFFF` 或純黑 `#000000` 作為大面積畫布底色**：改用帶有微溫/微冷色調的紙感白 (`#FAF8F5`、`#F9FAFB`) 或深炭黑 (`#0A0A0A`、`#111315`)。
   - **禁止俗套的紫藍霓虹漸層 (`from-purple-500 to-blue-500`)**。
   - **單一強調色鎖定 (Single Accent Lock)**：全頁只用 1 個高對比主強調色，搭配微透明細邊框 (`1px solid rgba(0,0,0,0.06)`) 與擴散柔影 (`0 8px 30px rgba(0,0,0,0.04)`)，禁止濫用刺眼的 `shadow-xl` / `shadow-2xl`。
3. **版面與圓角一致性鎖定 (Layout & Shape Lock)**：
   - 禁止連續兩個區塊使用相同的「三欄等寬卡片」結構。
   - 全頁容器圓角系統必須統一（全銳利 `4px`、全溫潤 `16px`、或全膠囊 Bento `28px`），不可混搭。
4. **物理感動態 (Fluid Physics Motion)**：
   - 禁止生硬的 `linear` 過渡；統一使用彈簧曲線 `cubic-bezier(0.22, 1, 0.36, 1)`，且必須支援 `@media (prefers-reduced-motion: reduce)`。

---

## 5. 品味工具 (`taste_auditor.py`)

1. 產生特定風格的 Anti-Slop 設計簡報與 CSS Token 預設集 (支援 editorial | linear-dark | warm-craft | swiss-grid)

```bash
python3 .agents/skills/frontend-design/scripts/taste_auditor.py --preset warm-craft

```

2. 掃描專案內的 HTML / CSS / JSX / TSX / Vue 檔案，抓出 AI Slop 違規並計算 Taste Score (0-100)

```bash
python3 .agents/skills/frontend-design/scripts/taste_auditor.py --audit src/
```
