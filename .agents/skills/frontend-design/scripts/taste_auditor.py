#!/usr/bin/env python3
"""
Taste Skill — Anti-Slop 前端設計基因產生器與 UI 品味審查工具 (taste_auditor.py)
參考來源：GitHub `Leonxlnx/taste-skill` & `anthropics/skills` (frontend-design)

功能：
  1. `--preset <style>`：根據專案類型輸出精心調校的色彩、字體、圓角、陰影與三旋鈕 (Variance / Motion / Density) CSS Tokens
  2. `--audit <path>`：靜態掃描 HTML / CSS / JS / JSX / TSX / Vue 檔案，偵測常見的「AI Slop (AI 樣板劣質設計)」：
     - 禁用之預設無個性字體 (Inter, Roboto, Arial)
     - 刺眼純黑/純白背景 (#000000 / #FFFFFF)
     - 俗套的紫藍霓虹漸層 (purple-to-blue / indigo-to-purple)
     - 過重的預設陰影 (shadow-xl / shadow-2xl)
     - 缺乏彈簧物理曲線的 linear transition
     - 缺少 prefers-reduced-motion 無障礙保護
     並計算 **UI Taste Score (0–100)** 與具體修正建議。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

PRESETS = {
    "warm-craft": {
        "name": "Warm Editorial Craft (紙感人文與高質感產品)",
        "dials": {"DESIGN_VARIANCE": 7, "MOTION_INTENSITY": 5, "VISUAL_DENSITY": 4},
        "fonts": {
            "display": "'Instrument Serif', 'Playfair Display', Georgia, serif",
            "sans": "'Plus Jakarta Sans', 'Satoshi', -apple-system, sans-serif",
            "mono": "'JetBrains Mono', monospace",
        },
        "tokens": {
            "--bg-canvas": "#FAF8F5",
            "--bg-surface": "#F3EFEA",
            "--bg-elevated": "#FFFFFF",
            "--text-primary": "#18181B",
            "--text-secondary": "#52525B",
            "--accent-primary": "#C2410C",
            "--border-whisper": "rgba(24, 24, 27, 0.08)",
            "--shadow-diffused": "0 12px 32px -4px rgba(24, 24, 27, 0.05)",
            "--radius-card": "20px",
            "--ease-spring": "cubic-bezier(0.22, 1, 0.36, 1)",
        },
    },
    "linear-dark": {
        "name": "Precision Obsidian Tech (高精密深色工程風)",
        "dials": {"DESIGN_VARIANCE": 6, "MOTION_INTENSITY": 6, "VISUAL_DENSITY": 7},
        "fonts": {
            "display": "'Geist', 'Outfit', -apple-system, sans-serif",
            "sans": "'Geist', 'Plus Jakarta Sans', -apple-system, sans-serif",
            "mono": "'JetBrains Mono', 'Fira Code', monospace",
        },
        "tokens": {
            "--bg-canvas": "#0A0B0E",
            "--bg-surface": "#12141A",
            "--bg-elevated": "#1A1D24",
            "--text-primary": "#F3F4F6",
            "--text-secondary": "#9CA3AF",
            "--accent-primary": "#10B981",
            "--border-whisper": "rgba(255, 255, 255, 0.07)",
            "--shadow-diffused": "0 16px 40px -8px rgba(0, 0, 0, 0.45)",
            "--radius-card": "12px",
            "--ease-spring": "cubic-bezier(0.22, 1, 0.36, 1)",
        },
    },
    "swiss-grid": {
        "name": "Swiss Neo-Brutalist Grid (瑞士國際主義網格風)",
        "dials": {"DESIGN_VARIANCE": 8, "MOTION_INTENSITY": 4, "VISUAL_DENSITY": 6},
        "fonts": {
            "display": "'Cabinet Grotesk', 'Space Grotesk', sans-serif",
            "sans": "'Satoshi', 'DM Sans', sans-serif",
            "mono": "'JetBrains Mono', monospace",
        },
        "tokens": {
            "--bg-canvas": "#F4F4F0",
            "--bg-surface": "#EAEAE4",
            "--bg-elevated": "#FAF9F6",
            "--text-primary": "#111111",
            "--text-secondary": "#4A4A46",
            "--accent-primary": "#E11D48",
            "--border-whisper": "rgba(17, 17, 17, 0.14)",
            "--shadow-diffused": "0 4px 16px rgba(17, 17, 17, 0.04)",
            "--radius-card": "6px",
            "--ease-spring": "cubic-bezier(0.16, 1, 0.3, 1)",
        },
    },
}

SLOP_RULES = [
    (
        r"font-family\s*:[^;]*\b(Inter|Roboto|Arial|Open Sans)\b",
        12,
        "[Typography Slop] 偵測到預設無個性字體 (Inter/Roboto/Arial)，請改用 Geist、Satoshi、Outfit、Plus Jakarta Sans 或 Instrument Serif。",
    ),
    (
        r"(?:from-purple-\d+|from-indigo-\d+)[^\"'\n]*(?:to-blue-\d+|to-pink-\d+|to-purple-\d+)",
        15,
        "[Color Slop] 偵測到俗套的 AI 紫藍/粉紫漸層 (from-purple/indigo to-blue/pink)，請改用單一高質感強調色與微色調畫布。",
    ),
    (
        r"background(?:-color)?\s*:\s*#(?:ffffff|fff|000000|000)\b",
        8,
        "[Surface Slop] 偵測到刺眼的純白 (#FFF) 或純黑 (#000) 背景，建議改用 #FAF8F5 (暖紙白)、#F9FAFB 或 #0A0B0E (深炭黑)。",
    ),
    (
        r"\bshadow-(?:xl|2xl)\b",
        10,
        "[Elevation Slop] 偵測到厚重的預設陰影 (shadow-xl/2xl)，請改用低透明度擴散柔影 `0 12px 32px rgba(0,0,0,0.05)` 與微透明邊框。",
    ),
    (
        r"transition\s*:[^;]*\blinear\b",
        8,
        "[Motion Slop] 偵測到生硬的 `linear` 動畫過渡，請改用彈簧物理曲線 `cubic-bezier(0.22, 1, 0.36, 1)`。",
    ),
]

FRONTEND_EXTS = {".html", ".css", ".scss", ".jsx", ".tsx", ".vue", ".svelte"}


def generate_preset_css(preset_key: str) -> str:
    """Render a CSS design-token block for one style preset.

    Args:
        preset_key: Key in `PRESETS`.

    Returns:
        CSS text (`:root` custom properties plus base rules).
    """
    p = PRESETS[preset_key]
    lines = [
        f"/* === Taste Skill Preset: {p['name']} === */",
        f"/* Dials: DESIGN_VARIANCE={p['dials']['DESIGN_VARIANCE']} | "
        f"MOTION_INTENSITY={p['dials']['MOTION_INTENSITY']} | "
        f"VISUAL_DENSITY={p['dials']['VISUAL_DENSITY']} */",
        ":root {",
        f"  --font-display: {p['fonts']['display']};",
        f"  --font-sans: {p['fonts']['sans']};",
        f"  --font-mono: {p['fonts']['mono']};",
    ]
    for k, v in p["tokens"].items():
        lines.append(f"  {k}: {v};")
    lines.extend([
        "}",
        "",
        "body {",
        "  background-color: var(--bg-canvas);",
        "  color: var(--text-primary);",
        "  font-family: var(--font-sans);",
        "  line-height: 1.65;",
        "  -webkit-font-smoothing: antialiased;",
        "}",
        "",
        "h1, h2, .display-heading {",
        "  font-family: var(--font-display);",
        "  letter-spacing: -0.025em;",
        "  line-height: 1.1;",
        "  text-wrap: balance;",
        "}",
        "",
        "p, .prose-measure {",
        "  max-width: 65ch;",
        "  text-wrap: pretty;",
        "}",
        "",
        "@media (prefers-reduced-motion: reduce) {",
        "  *, *::before, *::after {",
        "    animation-duration: 0.01ms !important;",
        "    transition-duration: 0.01ms !important;",
        "  }",
        "}",
    ])
    return "\n".join(lines)


def audit_directory(target: Path) -> tuple[int, list[dict]]:
    """Scan front-end files for generic "AI slop" patterns and compute a taste score.

    Args:
        target: A file or a directory scanned recursively (HTML/CSS/JSX/TSX/Vue/Svelte).

    Returns:
        Tuple of score (0-100) and findings.
    """
    files: list[Path] = []
    if target.is_file():
        files = [target]
    elif target.exists():
        files = [f for f in sorted(target.rglob("*")) if f.is_file() and f.suffix.lower() in FRONTEND_EXTS]

    if not files:
        return 100, []

    findings: list[dict] = []
    penalty = 0
    has_css_vars = False
    has_reduced_motion = False

    for f in files:
        text = f.read_text(encoding="utf-8", errors="replace")
        if "--" in text and "var(--" in text:
            has_css_vars = True
        if "prefers-reduced-motion" in text:
            has_reduced_motion = True

        for idx, line in enumerate(text.splitlines(), start=1):
            for pattern, weight, msg in SLOP_RULES:
                if re.search(pattern, line, flags=re.I):
                    penalty += weight
                    findings.append({
                        "file": str(f),
                        "line": idx,
                        "penalty": weight,
                        "message": msg,
                    })

    if not has_css_vars:
        penalty += 10
        findings.append({
            "file": str(target),
            "line": 1,
            "penalty": 10,
            "message": "[Token System] 尚未定義 CSS Variables (`--bg-canvas`, `--accent-primary`)，請先建立設計 Token 系統。",
        })
    if not has_reduced_motion:
        penalty += 5
        findings.append({
            "file": str(target),
            "line": 1,
            "penalty": 5,
            "message": "[Accessibility] 缺少 `@media (prefers-reduced-motion: reduce)` 動態降級保護。",
        })

    score = max(0, 100 - min(85, penalty))
    return score, findings


def main() -> int:
    """Run `--preset` (generate CSS tokens) or `--audit`.

    Returns:
        Process exit code.
    """
    parser = argparse.ArgumentParser(description="Taste Skill — Anti-Slop 前端設計產生器與審查工具")
    parser.add_argument("--preset", choices=list(PRESETS.keys()), help="產生指定風格的 Anti-Slop CSS Token 系統")
    parser.add_argument("--out", help="將產生的 CSS 寫入指定檔案路徑")
    parser.add_argument("--audit", help="掃描指定目錄或檔案的 UI Slop 違規並計算 Taste Score")
    parser.add_argument("--json", action="store_true", help="以 JSON 格式輸出審查結果")
    args = parser.parse_args()

    if args.preset:
        css = generate_preset_css(args.preset)
        if args.out:
            out_path = Path(args.out)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(css + "\n", encoding="utf-8")
            print(f"✅ 已將 '{args.preset}' 設計 Token 寫入：{out_path}")
        else:
            print(css)
        return 0

    audit_target = Path(args.audit or "src")
    score, findings = audit_directory(audit_target)
    if args.json:
        print(json.dumps({"taste_score": score, "findings": findings}, ensure_ascii=False, indent=2))
        return 0

    print("=" * 64)
    print(f"🎨 【Taste Skill — Anti-Slop UI 品味審查報告】 目標: {audit_target}")
    print(f"🏆 UI Taste Score: {score} / 100")
    print("=" * 64)
    if not findings:
        print("✅ 未偵測到 AI Slop 樣板特徵（通過字體、色彩、陰影與動態曲線檢查）！")
    else:
        for item in findings[:15]:
            print(f"  ⚠️ {item['file']}:L{item['line']} (-{item['penalty']}分) ➔ {item['message']}")
    return 0 if score >= 70 else 1


if __name__ == "__main__":
    raise SystemExit(main())
