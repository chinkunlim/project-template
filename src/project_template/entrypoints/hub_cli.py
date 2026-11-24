"""Zero-lookup single CLI for managing the Hub server and Master-Child linkage actions.

Purpose:
    Implements `python3 scripts/hub.py {start,stop,status,launch,stop-project,stop-all,autostart,graphify,scan,feedback-add}`
    using standard library only so AI agents and users can run Hub and child project actions
    with a single deterministic command.
"""
from __future__ import annotations

import argparse
import logging
import subprocess
import sys
import webbrowser
from pathlib import Path

from project_template.config.logging_setup import run_command
from project_template.config.settings import TEMPLATE_ROOT
from project_template.services import feedback as feedback_svc
from project_template.services import hub_manager as hm
from project_template.services import template_service as ts
from project_template.services import web_launcher as wl

logger = logging.getLogger(__name__)


def _print_status(args: argparse.Namespace) -> int:
    """Print Hub status, autostart state, and discovered child project web services.

    Args:
        args: Parsed CLI namespace containing `port`.

    Returns:
        Exit code 0.
    """
    info = hm.hub_status(port=args.port)
    state = "運行中" if info["running"] else "未啟動"
    auto = "已啟用" if info["autostart"] else "未啟用"
    print(f"母版總控台：{state} ({info['url']}, PID={info['pid'] or '-'}, 開機常駐={auto})")
    services = info["services"]
    if not services:
        print("（目前沒有偵測到具備 FastAPI 網頁的追蹤專案）")
        return 0
    for svc in services:
        badge = "🟢 運行中" if svc["running"] else "⚪ 未啟動"
        owner = f"PID {svc['pid']}" if svc["managed"] else ("外部啟動" if svc["running"] else "待機 0 MB")
        print(f"  - {svc['name']}: {badge} {svc['url']} [{owner}] ({svc['command']})")
    return 0


def _handle_start(args: argparse.Namespace) -> int:
    """Handle `hub start`.

    Args:
        args: Parsed CLI namespace containing `port` and `no_browser`.

    Returns:
        Exit code 0 on success.
    """
    res = hm.start_hub(port=args.port, open_browser=not args.no_browser)
    tag = "已在執行中" if res["already_running"] else f"已在背景啟動 (PID {res['pid']})"
    print(f"🌐 母版總控台{tag}：{res['url']}（API 文件：{res['url']}/docs）")
    return 0


def _handle_stop(args: argparse.Namespace) -> int:
    """Handle `hub stop`.

    Args:
        args: Parsed CLI namespace containing `port` and `all`.

    Returns:
        Exit code 0.
    """
    res = hm.stop_hub(port=args.port, with_children=args.all)
    if res.get("children"):
        print(f"子專案服務：已停止 {len(res['children']['stopped'])} 個，略過 {len(res['children']['skipped'])} 個")
    print(f"🛑 {res['message']}")
    return 0


def _handle_launch(args: argparse.Namespace) -> int:
    """Handle `hub launch <project>`.

    Args:
        args: Parsed CLI namespace containing `project` and `no_browser`.

    Returns:
        Exit code 0.
    """
    target = wl.resolve_project_path(args.project, TEMPLATE_ROOT.parent)
    res = wl.start_project_web(target)
    if not args.no_browser:
        webbrowser.open(res["url"])
    note = "已在執行中" if res.get("already_running") else f"已啟動 (PID {res.get('pid')})"
    print(f"🚀 {res['name']} 網頁{note}：{res['url']}")
    return 0


def _handle_stop_project(args: argparse.Namespace) -> int:
    """Handle `hub stop-project <project>`.

    Args:
        args: Parsed CLI namespace containing `project`.

    Returns:
        Exit code 0.
    """
    target = wl.resolve_project_path(args.project, TEMPLATE_ROOT.parent)
    res = wl.stop_project_web(target)
    print(f"🛑 {res['name']}：{res['message']} ({res['url']})")
    return 0


def _handle_stop_all(_args: argparse.Namespace) -> int:
    """Handle `hub stop-all`.

    Args:
        _args: Unused CLI namespace.

    Returns:
        Exit code 0.
    """
    res = wl.stop_all_project_webs(TEMPLATE_ROOT.parent)
    stopped = ", ".join(s["name"] for s in res["stopped"]) or "無"
    skipped = ", ".join(s["name"] for s in res["skipped"]) or "無"
    print(f"🛑 已停止：{stopped}；略過（非母版啟動）：{skipped}")
    return 0


def _handle_autostart(args: argparse.Namespace) -> int:
    """Handle `hub autostart on|off`.

    Args:
        args: Parsed CLI namespace containing `mode` and `port`.

    Returns:
        Exit code 0.
    """
    if args.mode == "on":
        res = hm.install_autostart(port=args.port)
        print(f"✅ {res['message']}：{res['url']} ({res['plist']})")
    else:
        res = hm.uninstall_autostart()
        print(f"✅ {res['message']} ({res['plist']})")
    return 0


def _handle_graphify(args: argparse.Namespace) -> int:
    """Handle `hub graphify [project]` (`agentctl graph` + `graphify update .`).

    Args:
        args: Parsed CLI namespace containing optional `project` and `include_master`.

    Returns:
        0 when all steps succeed, else 1.
    """
    root = TEMPLATE_ROOT.parent
    title, steps = ts.graphify_steps({"project": args.project, "include_master": args.include_master}, root)
    print(f"🕸️ {title}")
    failed = 0
    for argv, cwd in steps:
        res = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, check=False)
        mark = "✅" if res.returncode == 0 else "❌"
        print(f"  {mark} [{cwd.name}] {' '.join(argv)}")
        if res.returncode != 0:
            failed += 1
            tail = (res.stderr or res.stdout).strip().splitlines()[-3:]
            for line in tail:
                print(f"     {line}")
    return 0 if failed == 0 else 1


def _handle_scan(args: argparse.Namespace) -> int:
    """Handle `hub scan [project]` (`agentctl scan --skip-tests`).

    Args:
        args: Parsed CLI namespace containing optional `project`.

    Returns:
        0 when every scanned project exits 0, else 1.
    """
    root = TEMPLATE_ROOT.parent
    targets: list[Path] = [ts.resolve_feedback_target(args.project, root)] if args.project else ts.tracked(root)
    if not targets:
        print("（找不到追蹤專案）")
        return 0
    failed = 0
    for proj in targets:
        res = subprocess.run([sys.executable, "scripts/agentctl.py", "scan", "--skip-tests"], cwd=proj, capture_output=True, text=True, check=False)
        score = next((ln.strip() for ln in res.stdout.splitlines() if "綜合評分" in ln), "")
        mark = "✅" if res.returncode == 0 else "❌"
        print(f"{mark} {proj.name}: {score or f'exit={res.returncode}'}")
        failed += int(res.returncode != 0)
    return 0 if failed == 0 else 1


def _handle_feedback_add(args: argparse.Namespace) -> int:
    """Handle `hub feedback-add <project> <text>`.

    Args:
        args: Parsed CLI namespace containing `project`, `text`, `source`, `status`.

    Returns:
        Exit code 0.
    """
    target = ts.resolve_feedback_target(args.project, TEMPLATE_ROOT.parent)
    res = feedback_svc.add_suggestion(target, args.text, source=args.source, status=args.status)
    print(f"📝 已寫入 {res['project']} ({res['file']})：{res['date']} | {res['text']} | {res['status']}")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    """Build argument parser with subcommands for `scripts/hub.py`.

    Returns:
        Configured `ArgumentParser`.
    """
    parser = argparse.ArgumentParser(description="母版網頁總控台與各專案連動單一入口指令")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name, help_text in (("start", "背景啟動總控台並開啟瀏覽器"), ("stop", "停止總控台（--all 含子專案）"), ("status", "列出總控台與子專案網頁狀態")):
        sp = sub.add_parser(name, help=help_text)
        sp.add_argument("--port", type=int, default=hm.DEFAULT_HUB_PORT)
        if name == "start":
            sp.add_argument("--no-browser", action="store_true")
        if name == "stop":
            sp.add_argument("--all", action="store_true")
    p_launch = sub.add_parser("launch", help="啟動指定專案的 FastAPI 網頁並開啟分頁")
    p_launch.add_argument("project", help="專案名稱（如 video-studio）或絕對路徑")
    p_launch.add_argument("--no-browser", action="store_true")
    sub.add_parser("stop-project", help="停止由母版啟動的單一專案網頁").add_argument("project", help="專案名稱或絕對路徑")
    sub.add_parser("stop-all", help="停止所有由母版啟動的子專案網頁以釋放記憶體")
    p_auto = sub.add_parser("autostart", help="設定或取消 macOS 登入自動常駐母版總控台")
    p_auto.add_argument("mode", choices=["on", "off"])
    p_auto.add_argument("--port", type=int, default=hm.DEFAULT_HUB_PORT)
    p_graph = sub.add_parser("graphify", help="更新單一或全部追蹤專案的 AST 與 Graphify 圖譜")
    p_graph.add_argument("project", nargs="?", default="", help="專案名稱、`master` 或絕對路徑（留空 = 全部追蹤專案）")
    p_graph.add_argument("--include-master", action="store_true", help="批次更新時一併更新母版自身圖譜")
    sub.add_parser("scan", help="在單一或全部追蹤專案執行架構合規掃描").add_argument("project", nargs="?", default="", help="專案名稱或留空代表全部")
    p_fb = sub.add_parser("feedback-add", help="從母版寫入一列建議到指定專案的 docs/TEMPLATE_FEEDBACK.md")
    p_fb.add_argument("project", help="專案名稱（或 master）")
    p_fb.add_argument("text", help="建議內容")
    p_fb.add_argument("--source", default="master-cli", help="來源對話或任務")
    p_fb.add_argument("--status", default="待決定", help="初始狀態（預設待決定）")
    return parser


def _main(argv: list[str] | None) -> int:
    """Dispatch parsed CLI subcommand inside `run_command()` logging wrapper.

    Args:
        argv: CLI arguments list or None for `sys.argv[1:]`.

    Returns:
        Process exit code.
    """
    args = _build_parser().parse_args(argv)
    handlers = {
        "start": _handle_start,
        "stop": _handle_stop,
        "status": _print_status,
        "launch": _handle_launch,
        "stop-project": _handle_stop_project,
        "stop-all": _handle_stop_all,
        "autostart": _handle_autostart,
        "graphify": _handle_graphify,
        "scan": _handle_scan,
        "feedback-add": _handle_feedback_add,
    }
    try:
        return handlers[args.cmd](args)
    except (ValueError, RuntimeError) as exc:
        logger.warning("hub command %s failed: %s", args.cmd, exc)
        print(f"❌ {exc}", file=sys.stderr)
        return 1


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for `scripts/hub.py` and `project-template-hub`.

    Args:
        argv: CLI arguments list or None for `sys.argv[1:]`.

    Returns:
        Process exit code.
    """
    return run_command("hub", _main, argv)


if __name__ == "__main__":
    raise SystemExit(main())
