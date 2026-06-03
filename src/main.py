import argparse
import sys
import os

# ── 確保從 src/ 目錄執行時能 import 同層模組 ──
sys.path.insert(0, os.path.dirname(__file__))

from actions import list_devices_action, screenshot_action, tap_action, find_action, probe_daily_tasks_action, run_small_tasks_action
from adb_client import AdbError, get_default_adb_target


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Valor Legends ADB 自動化工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
範例：
  python src/main.py devices
  python src/main.py screenshot
  python src/main.py tap 800 450
  python src/main.py find assets/go_button.png
  python src/main.py probe-daily-tasks

廣告關閉實驗（支線）：
  python experiments/ad_closer/run_ad_closer.py --debug
        """,
    )
    default_serial = get_default_adb_target()
    parser.add_argument(
        "--serial",
        type=str,
        default=default_serial,
        help=f"ADB 設備 serial（預設: {default_serial}）",
    )
    subparsers = parser.add_subparsers(dest="command", help="可用指令")

    # ── 舊有指令 ──────────────────────────────────────

    subparsers.add_parser("devices", help="列出已連線 ADB 設備")
    subparsers.add_parser("screenshot", help="擷圖存到 screenshots/current.png")

    tap_parser = subparsers.add_parser("tap", help="點擊指定座標 (x, y)")
    tap_parser.add_argument("x", type=int, help="X 座標")
    tap_parser.add_argument("y", type=int, help="Y 座標")

    find_parser = subparsers.add_parser("find", help="在截圖中尋找 template")
    find_parser.add_argument("template_path", type=str, help="Template 圖片路徑")
    find_parser.add_argument(
        "image_path",
        type=str,
        nargs="?",
        default="screenshots/current.png",
        help="目標基底圖片路徑（預設: screenshots/current.png）",
    )

    subparsers.add_parser("probe-daily-tasks", help="探測每日任務「前往」按鈕")

    run_tasks_parser = subparsers.add_parser("run-small-tasks", help="執行低風險小任務")
    run_tasks_parser.add_argument(
        "--tasks",
        nargs="+",
        default=["endless_trial", "campaign"],
        help="欲執行的任務列表 (預設: endless_trial campaign)"
    )

    # ── 解析 ────────────────────────────────────────────

    args = parser.parse_args()

    # Apply global serial override if specified
    if args.serial:
        import adb_client
        adb_client.ADB_TARGET = args.serial
        try:
            import subprocess
            subprocess.run(
                ["adb", "connect", args.serial],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                encoding="utf-8",
                errors="ignore"
            )
        except Exception:
            pass

    if not args.command:
        parser.print_help()
        sys.exit(1)

    try:
        if args.command == "devices":
            list_devices_action()

        elif args.command == "screenshot":
            screenshot_action()

        elif args.command == "tap":
            tap_action(args.x, args.y)

        elif args.command == "find":
            find_action(args.template_path, args.image_path)

        elif args.command == "probe-daily-tasks":
            probe_daily_tasks_action()

        elif args.command == "run-small-tasks":
            run_small_tasks_action(args.tasks)

    except AdbError:
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
