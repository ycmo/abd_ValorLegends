import argparse
import sys
from pathlib import Path

# 強制終端機輸出為 UTF-8，避免 cp950 無法印出 Emoji 報錯
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

from core.runner import ReactiveRunner

def main():
    parser = argparse.ArgumentParser(description="Ads2 Ad Closer 無腦反應式大迴圈 + 自癒系統")
    subparsers = parser.add_subparsers(dest="command", help="子命令")
    
    # run command
    run_parser = subparsers.add_parser("run", help="執行無腦反應式大迴圈")
    run_parser.add_argument("--serial", default="emulator-5554", help="設備 Serial 號碼")
    run_parser.add_argument("--ad-wait", type=int, default=15, help="點擊看廣告後暫停偵測的秒數 (預設: 15)")
    run_parser.add_argument("--debug", action="store_true", help="開啟除錯模式，異常時自動儲存截圖")

    args = parser.parse_args()

    if args.command is None or args.command == "run":
        serial = args.serial if hasattr(args, 'serial') else "emulator-5554"
        ad_wait = args.ad_wait if hasattr(args, 'ad_wait') else 15
        debug = args.debug if hasattr(args, 'debug') else False
        runner = ReactiveRunner(serial=serial, ad_wait=ad_wait, debug=debug)
        runner.run()

if __name__ == "__main__":
    main()
