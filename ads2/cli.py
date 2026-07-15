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
        "--enable-close-x-classifier",
        action="store_true",
        help="Enable MobileNet close-X classifier fallback after repeated close template/glyph failures.",
    )
    run_parser.add_argument(
        "--close-x-classifier-threshold",
        type=float,
        default=0.5,
        help="Minimum p_close for close-X classifier fallback taps.",
    )
    run_parser.add_argument(
        "--close-x-classifier-checkpoint",
        help="Path to the close-X classifier checkpoint. Defaults to Stage 0.6 matched fold_01 best.pt.",
    )
    run_parser.add_argument(
        "--close-x-classifier-min-failures",
        type=int,
        default=2,
        help="Run classifier fallback after this many close template/glyph misses or failed close attempts.",
    )
    run_parser.add_argument(
        "--max-classifier-fallback-taps",
        type=int,
        default=3,
        help="Maximum classifier fallback candidates to tap per fallback event. 0 means all candidates above threshold.",
    )
    run_parser.add_argument(
        "--enable-click-success-collection",
        action="store_true",
        help="Enable weak-positive runtime collection for clicks that cause a meaningful screen change.",
    )
    run_parser.add_argument(
        "--disable-click-success-collection",
        action="store_true",
        help="Deprecated compatibility flag. Click-success collection is disabled by default.",
    )
    run_parser.add_argument(
        "--click-success-change-threshold",
        type=float,
        default=2.0,
        help="Minimum mean screen-diff score required to save a weak click-success event.",
    )
    run_parser.add_argument(
        "--click-success-collection-dir",
        help="Directory for weak click-success collection. Defaults to vision_platform/ads/runtime_collection/click_success.",
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
        enable_close_x_classifier = args.enable_close_x_classifier if hasattr(args, 'enable_close_x_classifier') else False
        close_x_classifier_threshold = args.close_x_classifier_threshold if hasattr(args, 'close_x_classifier_threshold') else 0.5
        close_x_classifier_checkpoint = args.close_x_classifier_checkpoint if hasattr(args, 'close_x_classifier_checkpoint') else None
        close_x_classifier_min_failures = args.close_x_classifier_min_failures if hasattr(args, 'close_x_classifier_min_failures') else 2
        max_classifier_fallback_taps = args.max_classifier_fallback_taps if hasattr(args, 'max_classifier_fallback_taps') else 3
        enable_click_success_collection = (
            bool(getattr(args, "enable_click_success_collection", False))
            and not bool(getattr(args, "disable_click_success_collection", False))
        )
        click_success_change_threshold = args.click_success_change_threshold if hasattr(args, 'click_success_change_threshold') else 2.0
        click_success_collection_dir = args.click_success_collection_dir if hasattr(args, 'click_success_collection_dir') else None
        runner = ReactiveRunner(
            serial=serial,
            ad_wait=ad_wait,
            debug=debug,
            profile=profile,
            geometry_close_fallback=geometry_close_fallback,
            geometry_close_threshold=geometry_close_threshold,
            enable_close_x_classifier=enable_close_x_classifier,
            close_x_classifier_threshold=close_x_classifier_threshold,
            close_x_classifier_checkpoint=close_x_classifier_checkpoint,
            close_x_classifier_min_failures=close_x_classifier_min_failures,
            max_classifier_fallback_taps=max_classifier_fallback_taps,
            enable_click_success_collection=enable_click_success_collection,
            click_success_change_threshold=click_success_change_threshold,
            click_success_collection_dir=click_success_collection_dir,
        )
        runner.run()

if __name__ == "__main__":
    main()
