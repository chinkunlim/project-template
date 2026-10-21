"""Command line for updating every project's framework at once (`python3 scripts/update_all.py`).

Purpose:
    Previews by default; with `--apply` asks once, then updates every clean project and commits
    the ones without conflicts whose `agentctl check` passes. Nothing is pushed or deleted.

    Without folders it works on every tracked project: the folder that contains the template plus the
    registered projects (`.local/projects.json`) elsewhere. With folders it scans only those, unless
    `--registered` is given too.

Usage:
    python3 scripts/update_all.py                      # preview only (template's folder + registered projects)
    python3 scripts/update_all.py --apply              # asks once, then updates
    python3 scripts/update_all.py ~/work --registered --apply --yes --no-commit
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from project_template.config.settings import TEMPLATE_ROOT
from project_template.services.update_all import (
    DEFAULT_ROOT,
    apply,
    classify,
    is_dirty,
    preview,
    render_table,
    tracked_projects,
)


def confirm(count: int) -> bool:
    """Ask the user once before changing projects.

    Args:
        count: Number of projects that will be updated.

    Returns:
        True when the user typed `y`.
    """
    try:
        return input(f"\n要更新以上 {count} 個專案嗎？(y/N) ").strip().lower() == "y"
    except EOFError:
        return False


def main(argv: list[str] | None = None) -> int:
    """Preview (default) or apply the framework update for every project.

    Args:
        argv: Command-line arguments; defaults to `sys.argv[1:]`.

    Returns:
        0 on success, 1 when the template has uncommitted changes or an update failed.
    """
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description="一次更新所有專案的框架（預設只預覽）")
    parser.add_argument("roots", nargs="*", help=f"放專案的資料夾（預設：母版所在的資料夾 {DEFAULT_ROOT}＋登記清單）")
    parser.add_argument("--registered", action="store_true", help="指定資料夾時，也加入登記清單中的專案（.local/projects.json）")
    parser.add_argument("--depth", type=int, default=3, help="專案最多在幾層子資料夾內（預設 3）")
    parser.add_argument("--apply", action="store_true", help="真的更新（預設只預覽）")
    parser.add_argument("--yes", action="store_true", help="不再詢問確認（搭配 --apply）")
    parser.add_argument("--no-commit", action="store_true", help="更新後不自動 commit")
    args = parser.parse_args(argv)
    if is_dirty(TEMPLATE_ROOT):
        print("❌ 母版有未 commit 的修改：先 commit 母版，專案才能記錄拿到的是哪個版本。", file=sys.stderr)
        return 1
    roots = [Path(r) for r in args.roots] or [DEFAULT_ROOT]
    projects = tracked_projects(roots, args.depth, registered=args.registered or not args.roots)
    plans = [preview(p) for p in projects]
    ready = classify(plans)
    print(f"# 框架更新{'' if args.apply else '預覽'}（{len(projects)} 個專案，{len(ready)} 個可更新）\n")
    print(render_table(plans))
    for p in plans:
        for rel in p.files["removed"]:
            print(f"🗑️ `{p.path.name}`：{rel} 已不在母版（不會自動刪除，確認後自行刪除）")
    if not args.apply or not ready:
        if ready:
            print("\n👉 確認後執行：python3 scripts/update_all.py --apply")
        return 0
    if not args.yes and not confirm(len(ready)):
        print("已取消，沒有修改任何專案。")
        return 0
    for p in ready:
        p.status = apply(p, commit=not args.no_commit)
        print(f"{p.path.name}: {p.status}")
    print("\n" + render_table(plans))
    return 1 if any(p.status.startswith("❌") for p in ready) else 0
