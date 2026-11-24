"""Zero-lookup single CLI for managing the Hub server and child project FastAPI servers.

Purpose:
    Implements `python3 scripts/hub.py {start,stop,status,launch,stop-project,stop-all,autostart}`
    using standard library only so AI agents and users can start or stop the Hub and any child
    project web page with one deterministic command.
"""
from __future__ import annotations

import argparse
import logging
import sys
import webbrowser

from project_template.config.logging_setup import run_command
from project_template.config.settings import TEMPLATE_ROOT
from project_template.services import hub_manager as hm
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


def _build_parser() -> argparse.ArgumentParser:
    """Build argument parser with subcommands for `scripts/hub.py`.

    Returns:
        Configured `ArgumentParser`.
    """
    parser = argparse.ArgumentParser(description="母版網頁總控台與各專案 FastAPI 服務單一入口指令")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_start = sub.add_parser("start", help="在背景啟動母版網頁總控台並開啟瀏覽器")
    p_start.add_argument("--port", type=int, default=hm.DEFAULT_HUB_PORT)
    p_start.add_argument("--no-browser", action="store_true")
    p_stop = sub.add_parser("stop", help="停止背景母版總控台（--all 同時停止所有子專案網頁）")
    p_stop.add_argument("--port", type=int, default=hm.DEFAULT_HUB_PORT)
    p_stop.add_argument("--all", action="store_true")
    p_status = sub.add_parser("status", help="列出母版總控台與所有子專案網頁運行狀態")
    p_status.add_argument("--port", type=int, default=hm.DEFAULT_HUB_PORT)
    p_launch = sub.add_parser("launch", help="啟動指定專案的 FastAPI 網頁並開啟分頁")
    p_launch.add_argument("project", help="專案名稱（如 note-studio）或絕對路徑")
    p_launch.add_argument("--no-browser", action="store_true")
    p_stop_p = sub.add_parser("stop-project", help="停止由母版啟動的單一專案網頁")
    p_stop_p.add_argument("project", help="專案名稱或絕對路徑")
    sub.add_parser("stop-all", help="停止所有由母版啟動的子專案網頁以釋放記憶體")
    p_auto = sub.add_parser("autostart", help="設定或取消 macOS 登入自動常駐母版總控台")
    p_auto.add_argument("mode", choices=["on", "off"])
    p_auto.add_argument("--port", type=int, default=hm.DEFAULT_HUB_PORT)
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
