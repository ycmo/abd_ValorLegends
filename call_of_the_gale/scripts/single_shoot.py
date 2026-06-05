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
except ImportError as e:
    print(f"錯誤: 模組載入失敗: {e}")
    sys.exit(1)

# 固定設定值
SHURIKEN_X = 340
SHURIKEN_Y = 410
SHURIKEN_DIST = 100
UPGRADE_X = 800
UPGRADE_Y = 400
LEAVE_X = 50
LEAVE_Y = 50
ENERGY_ROI = (595, 15, 35, 20)
SCROLL_ROI = (860, 10, 45, 35)
ONIGIRI_ROI = (680, 10, 90, 30)
UPGRADE_COST_ROI = (740, 350, 120, 40)
DEPART_BTN_PATH = Path(_THIS_DIR).parent / "assets" / "depart_button.png"
EMPTY_SLOT_PATH = Path(_THIS_DIR).parent / "assets" / "empty_slot.png"
SKIP_BTN_PATH = Path(_THIS_DIR).parent / "assets" / "skip_button.png"
CHALLENGE_BTN_PATH = Path(_THIS_DIR).parent / "assets" / "challenge_button.png"

def save_debug_image(image, prefix):
    debug_dir = Path(_THIS_DIR).parent / "debug_output"
    debug_dir.mkdir(exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    debug_path = debug_dir / f"{prefix}_{ts}.png"
    ok, buf = cv2.imencode(".png", image)
    if ok:
        with open(debug_path, "wb") as f:
            f.write(buf.tobytes())
    return debug_path

def get_shuriken_count(screen, reader, debug=False):
    x, y, w, h = ENERGY_ROI
    crop = screen[y:y+h, x:x+w]
    # 放大圖片以提高 OCR 辨識率 (放大 4 倍效果更好)
    crop_large = cv2.resize(crop, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
    
    if debug:
        save_debug_image(crop_large, "ocr_crop")
        
    # 限制只辨識數字
    results = reader.readtext(crop_large, allowlist='0123456789')
    if not results:
        return -1
    
    best_text = ""
    best_conf = 0.0
    for bbox, text, conf in results:
        if conf > best_conf:
            best_text = text
            best_conf = float(conf)
            
    try:
        return int(best_text)
    except ValueError:
        return -1

def parse_game_number(text):
    text = text.replace(',', '')
    text = text.replace('O', '0').replace('o', '0')
    text = text.replace('l', '1').replace('I', '1')
    
    multiplier = 1.0
    if 'k' in text.lower():
        multiplier = 1000.0
        text = text.lower().replace('k', '')
    elif 'm' in text.lower():
        multiplier = 1000000.0
        text = text.lower().replace('m', '')
        
    try:
        return int(float(text) * multiplier)
    except ValueError:
        return -1

def get_scroll_count(screen, reader):
    x, y, w, h = SCROLL_ROI
    crop = screen[y:y+h, x:x+w]
    crop_large = cv2.resize(crop, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
    
    results = reader.readtext(crop_large, allowlist='0123456789')
    if not results:
        return -1
    
    best_text = ""
    best_conf = 0.0
    for bbox, text, conf in results:
        if conf > best_conf:
            best_text = text
            best_conf = float(conf)
            
    try:
        return int(best_text)
    except ValueError:
        return -1

def get_onigiri_count(screen, reader):
    x, y, w, h = ONIGIRI_ROI
    crop = screen[y:y+h, x:x+w]
    crop_large = cv2.resize(crop, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
    
    results = reader.readtext(crop_large, allowlist='0123456789,kKmM.OoIl')
    if not results:
        return -1
    
    best_text = ""
    best_conf = 0.0
    for bbox, text, conf in results:
        if conf > best_conf:
            best_text = text
            best_conf = float(conf)
            
    return parse_game_number(best_text)

def get_upgrade_cost(screen, reader):
    x, y, w, h = UPGRADE_COST_ROI
    crop = screen[y:y+h, x:x+w]
    crop_large = cv2.resize(crop, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
    
    results = reader.readtext(crop_large, allowlist='0123456789,kKmM.OoIl')
    if not results:
        return -1
    
    best_text = ""
    best_conf = 0.0
    for bbox, text, conf in results:
        if conf > best_conf:
            best_text = text
            best_conf = float(conf)
            
    return parse_game_number(best_text)

def shoot_shuriken(controller: DeviceController, start_x: int, start_y: int, pull_distance: int = 100):
    direction = random.choice([-1, 1])
    offset_angle_deg = random.uniform(3.0, 5.0) * direction
    angle_deg = 90.0 + offset_angle_deg
    angle_rad = math.radians(angle_deg)
    
    end_x = start_x + int(pull_distance * math.cos(angle_rad))
    end_y = start_y + int(pull_distance * math.sin(angle_rad))
    
    print(f"[Action] 發射！ 拖曳起點({start_x}, {start_y}) -> 終點({end_x}, {end_y})")
    controller.swipe(start_x, start_y, end_x, end_y, duration_ms=500)

def wait_for_shuriken(device, max_wait=30.0):
    print("[Info] 正在等待飛鏢回填就緒...")
    start_time = time.time()
    
    empty_template = cv2.imdecode(np.fromfile(str(EMPTY_SLOT_PATH), dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    if empty_template is None:
        print("[Warning] 無法載入 empty_slot.png，將使用固定等待時間...")
        time.sleep(5.0)
        return

    gray_empty = cv2.cvtColor(empty_template, cv2.COLOR_BGR2GRAY)
    half = 30
    
    while time.time() - start_time < max_wait:
        screen = device.screenshot()
        crop_current = screen[SHURIKEN_Y-half:SHURIKEN_Y+half, SHURIKEN_X-half:SHURIKEN_X+half]
        gray_current = cv2.cvtColor(crop_current, cv2.COLOR_BGR2GRAY)
        
        res = cv2.matchTemplate(gray_current, gray_empty, cv2.TM_CCOEFF_NORMED)
        match_score = res[0][0]
        
        # 如果跟「空白格子」的相似度低於 0.6，代表格子被飛鏢擋住了
        if match_score < 0.6:
            print(f"[Info] 飛鏢已就緒！ (背景相似度降至 {match_score:.3f})")
            return True
            
        time.sleep(0.5)
        
    print("[Warning] 等待飛鏢就緒超時 (超過30秒)！")
    return False

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

    # 執行單次流程
    print("[Info] 開始單次挑戰流程...")
    run_single_round(device, matcher, debug=args.debug)
    print("[Info] 單次挑戰流程結束。")

def run_single_round(device, matcher, reader=None, debug=False):
    """執行單次完整的「發射 -> 升級 -> 出發」流程"""
    consecutive_fails = 0
    
    # 預設開場盲狙第一發
    print("[Info] 開場第一發！")
    shoot_shuriken(device, SHURIKEN_X, SHURIKEN_Y, SHURIKEN_DIST)
    
    if reader is None:
        import threading
        print("[Info] 利用發射後的動畫等待時間，在背景初始化 OCR 模型...")
        reader_container = []
        def load_ocr():
            reader_container.append(build_easyocr_reader())
        ocr_thread = threading.Thread(target=load_ocr)
        ocr_thread.start()
        time.sleep(1.0)
        wait_for_shuriken(device)
        ocr_thread.join()
        reader = reader_container[0]
        print("[Info] OCR 初始化完成！")
    else:
        time.sleep(1.0)
        wait_for_shuriken(device)
        
    while True:
        screen = device.screenshot()
        
        if debug:
            save_debug_image(screen, "full_screen")
            
        count = get_shuriken_count(screen, reader, debug=debug)
        
        if count == -1:
            print("[Warning] 無法辨識飛鏢數量，重試中...")
            if not debug:
                save_debug_image(screen, "ocr_fail")
            consecutive_fails += 1
            if consecutive_fails >= 5:
                debug_dir = Path(_THIS_DIR).parent / "debug_output"
                print(f"[Error] 連續 5 次無法辨識數量，已將除錯截圖存至 {debug_dir}")
                return False
            time.sleep(1.0)
            continue
            
        consecutive_fails = 0
        print(f"[Info] 當前飛鏢數量: {count}")
        
        if count > 0:
            shoot_shuriken(device, SHURIKEN_X, SHURIKEN_Y, SHURIKEN_DIST)
            time.sleep(1.0) # 確保剛發射的飛鏢已經離手
            wait_for_shuriken(device)
        elif count == 0:
            print("[Info] 飛鏢已用盡 (0)，等待 8 秒讓最後一發飛鏢落地...")
            time.sleep(8.0)
            break

    # 3. 升級與檢查飯糰迴圈
    print("[Info] 準備升級：第一次無條件長按「升級」3 秒鐘...")
    device.swipe(UPGRADE_X, UPGRADE_Y, UPGRADE_X + 2, UPGRADE_Y + 2, duration_ms=3000)
    time.sleep(1.0)

    print("[Info] 開始檢查飯糰數量與升級消耗...")
    onigiri_fails = 0
    upgrade_attempts = 0
    
    while True:
        screen = device.screenshot()
        onigiri = get_onigiri_count(screen, reader)
        cost = get_upgrade_cost(screen, reader)
        
        if onigiri == -1 or cost == -1:
            print("[Warning] 無法辨識飯糰數量或升級門檻...")
            onigiri_fails += 1
            if onigiri_fails >= 5:
                print("[Error] 連續 5 次無法辨識，報錯跳出！")
                sys.exit(1)
            time.sleep(1.0)
            continue
            
        onigiri_fails = 0
        print(f"[Info] 當前飯糰: {onigiri}, 升級需要: {cost}")
        
        if onigiri < cost:
            print(f"[Info] 飯糰數量 ({onigiri}) 已低於升級門檻 ({cost})，停止升級，準備出發！")
            break
            
        if upgrade_attempts >= 5:
            print("[Error] 已經長按升級多次，但飯糰數量仍無法降至門檻以內，報錯跳出！")
            sys.exit(1)
            
        print(f"[Info] 飯糰數量 ({onigiri}) >= 門檻 ({cost})，直接長按「升級」3 秒鐘...")
        device.swipe(UPGRADE_X, UPGRADE_Y, UPGRADE_X + 2, UPGRADE_Y + 2, duration_ms=3000)
        time.sleep(1.0)  # 給介面一點時間更新數字
        upgrade_attempts += 1

    print("[Info] 準備尋找並點擊「出發」...")
    max_depart_attempts = 20
    depart_success = False
    has_clicked_depart = False
    
    for attempt in range(max_depart_attempts):
        screen = device.screenshot()
        match = matcher.match_template(screen, DEPART_BTN_PATH, threshold=0.7)
        if match:
            print(f"[Action] 第 {attempt+1} 次發現「出發」按鈕，點擊！")
            device.tap(*match.center)
            has_clicked_depart = True
            time.sleep(1.0)
        else:
            if has_clicked_depart:
                print("[Info] 「出發」按鈕已消失，確認成功進入過場畫面！")
                depart_success = True
                break
            else:
                print(f"[Warning] 第 {attempt+1} 次嘗試找不到「出發」按鈕（可能正在閃爍或被遮擋），繼續等待...")
                time.sleep(1.0)

    if not depart_success:
        print("[Warning] 點擊出發按鈕多次後，按鈕仍未消失，可能跳轉失敗或卡頓。")
        return False
        
    return True

if __name__ == "__main__":
    main()
