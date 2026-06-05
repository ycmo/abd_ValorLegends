import sys
import os
import time
import math
import random
import argparse
import cv2
import numpy as np
from pathlib import Path

# 設定路徑以引入 src/ 底下的模組
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_THIS_DIR, "..", ".."))
_SRC_DIR = os.path.join(_PROJECT_ROOT, "src")
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

try:
    from src.adb_controller import DeviceController
    from src.vision_matcher import VisionMatcher
    from src.ocr_utils import build_easyocr_reader
    # 從 single_shoot 引入共用的常數與函式
    from call_of_the_gale.scripts.single_shoot import (
        get_scroll_count,
        run_single_round,
        LEAVE_X, LEAVE_Y,
        SKIP_BTN_PATH,
        CHALLENGE_BTN_PATH,
        DEPART_BTN_PATH
    )
except ImportError as e:
    print(f"錯誤: 模組載入失敗: {e}")
    sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="疾風的呼喚：連續發射到 0 並出發")
    parser.add_argument("--serial", default="emulator-5554")
    parser.add_argument("--debug", action="store_true", help="開啟除錯模式，每次辨識都會儲存截圖")
    parser.add_argument("-n", "--times", type=int, help="不使用 OCR，直接固定發射指定的次數")
    args = parser.parse_args()

    print("[Info] 連接設備中...")
    device = DeviceController(serial=args.serial)
    if not device.connect():
        print("[Error] Failed to connect.")
        sys.exit(1)

    if not DEPART_BTN_PATH.exists():
        print(f"[Error] 找不到出發按鈕模板: {DEPART_BTN_PATH}")
        sys.exit(1)

    matcher = VisionMatcher()

    print("[Info] 初始化 OCR 與影像比對引擎 (可能需要幾秒鐘)...")
    reader = build_easyocr_reader()

    while True:
        # 1. 檢查卷軸數量
        screen = device.screenshot()
        scrolls = get_scroll_count(screen, reader)
        
        if scrolls == 0:
            print("[Info] 卷軸已歸零 (數量為 0)，點擊左上角「離開」！")
            device.tap(LEAVE_X, LEAVE_Y)
            break
        elif scrolls == -1:
            print("[Warning] 無法辨識卷軸數量，預設為還有卷軸，繼續執行...")
        else:
            print(f"[Info] 進入新一輪，目前剩餘卷軸: {scrolls}")

        # 2. 自動發射迴圈與升級出發
        print("[Info] 呼叫 run_single_round 進行單回合操作...")
        success = run_single_round(device, matcher, reader=reader, debug=args.debug)
        if not success:
            print("[Warning] run_single_round 回報失敗，強行進入下一步找跳過...")

        # 3. 過場動畫處理：尋找並反覆點擊「跳過」
        print("[Info] 正在等待與處理過場動畫...")
        for _ in range(20):
            screen = device.screenshot()
            
            # 如果已經看到「繼續挑戰」，代表過場動畫已經結束，提早結束跳過階段
            if matcher.match_template(screen, CHALLENGE_BTN_PATH, threshold=0.8):
                break
                
            # 尋找「跳過」按鈕，若找到就點擊 (不中斷迴圈，讓它多點幾次防漏點)
            match_skip = matcher.match_template(screen, SKIP_BTN_PATH, threshold=0.8)
            if match_skip:
                print(f"[Action] 找到「跳過」按鈕，持續點擊！")
                device.tap(*match_skip.center)
                
            time.sleep(1.0)
            
        # 4. 結算畫面處理：尋找並點擊「繼續挑戰」
        print("[Info] 正在等待結算畫面與「繼續挑戰」按鈕...")
        for _ in range(30):
            screen = device.screenshot()
            match_challenge = matcher.match_template(screen, CHALLENGE_BTN_PATH, threshold=0.8)
            if match_challenge:
                print(f"[Action] 找到「繼續挑戰」按鈕，點擊！")
                device.tap(*match_challenge.center)
                time.sleep(3.0) # 給畫面時間切換回棋盤
                break
            time.sleep(1.0)
            
        print("[Info] 準備進行下一回合...")
        time.sleep(2.0)

if __name__ == "__main__":
    main()
