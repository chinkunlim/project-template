"""Command line for collecting template-improvement suggestions (`python3 scripts/collect_feedback.py`).

Purpose:
    Reads every project's `docs/TEMPLATE_FEEDBACK.md` (read-only) and prints, or saves, one
    list of the suggestions that are still open.

    Without folders it reads every tracked project (the template's folder + registered projects);
    with folders only those, unless `--registered` is given too.

Usage:
    python3 scripts/collect_feedback.py
    python3 scripts/collect_feedback.py ~/Desktop/projects ~/work --depth 4
    python3 scripts/collect_feedback.py --all --out feedback-review.md
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

from project_template.services.feedback import DEFAULT_ROOT, collect


def main(argv: list[str] | None = None) -> int:
    """Scan the projects and print (or save) the combined list.

    Args:
        argv: Command-line arguments; defaults to `sys.argv[1:]`.

    Returns:
        0 (the tool only reads).
    """
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description="彙整所有專案的 docs/TEMPLATE_FEEDBACK.md（只讀，不修改專案）")
    parser.add_argument("roots", nargs="*", help=f"放專案的資料夾（預設：母版所在的資料夾 {DEFAULT_ROOT}＋登記清單）")
    parser.add_argument("--registered", action="store_true", help="指定資料夾時，也加入登記清單中的專案（.local/projects.json）")
    parser.add_argument("--depth", type=int, default=3, help="專案最多在幾層子資料夾內（預設 3）")
    parser.add_argument("--all", action="store_true", help="也列出已採用 / 不採用的建議")
    parser.add_argument("--out", default="", help="把結果寫到這個 Markdown 檔（預設印在終端機）")
    args = parser.parse_args(argv)
    roots = [Path(r) for r in args.roots] or [DEFAULT_ROOT]
    report = collect(roots, args.depth, args.all, registered=args.registered or not args.roots)
    if args.out:
        Path(args.out).expanduser().write_text(report, encoding="utf-8")
        print(f"✅ 已寫入 {args.out}")
    else:
        print(report)
    return 0
