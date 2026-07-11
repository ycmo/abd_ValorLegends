import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.stdio_utils import configure_utf8_stdio

configure_utf8_stdio()

from core.runner import ReactiveRunner

def main():
    parser = argparse.ArgumentParser(description="Ads2 Ad Closer 無腦反應式大迴圈 + 自癒系統")
    subparsers = parser.add_subparsers(dest="command", help="子命令")
    
    # run command
    run_parser = subparsers.add_parser("run", help="執行無腦反應式大迴圈")
    run_parser.add_argument("--serial", default="emulator-5554", help="設備 Serial 號碼")
    run_parser.add_argument("--ad-wait", type=int, default=15, help="點擊看廣告後暫停偵測的秒數 (預設: 15)")
    run_parser.add_argument("--debug", action="store_true", help="開啟除錯模式，異常時自動儲存截圖")
    run_parser.add_argument(
        "--geometry-close-fallback",
        action="store_true",
        help="Enable geometry-based close fallback after close template/glyph matching fails.",
    )
    run_parser.add_argument(
        "--geometry-close-threshold",
        type=float,
        default=0.85,
        help="Minimum score for geometry close fallback.",
    )
    run_parser.add_argument(
        "--profile",
        help="讀取 ads2/profiles/<name>.json，加入任務專用的正常結束條件",
    )

    args = parser.parse_args()

    if args.command is None or args.command == "run":
        serial = args.serial if hasattr(args, 'serial') else "emulator-5554"
        ad_wait = args.ad_wait if hasattr(args, 'ad_wait') else 15
        debug = args.debug if hasattr(args, 'debug') else False
        profile = args.profile if hasattr(args, 'profile') else None
        geometry_close_fallback = args.geometry_close_fallback if hasattr(args, 'geometry_close_fallback') else False
        geometry_close_threshold = args.geometry_close_threshold if hasattr(args, 'geometry_close_threshold') else 0.85
        runner = ReactiveRunner(
            serial=serial,
            ad_wait=ad_wait,
            debug=debug,
            profile=profile,
            geometry_close_fallback=geometry_close_fallback,
            geometry_close_threshold=geometry_close_threshold,
        )
        runner.run()

if __name__ == "__main__":
    main()
