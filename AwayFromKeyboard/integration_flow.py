import sys
import time
import subprocess
from pathlib import Path
import cv2
import numpy as np

# 強制設定輸出為 UTF-8，以防在 Windows 終端機顯示中文出錯
sys.stdout.reconfigure(encoding='utf-8')

# 確保專案根目錄在 sys.path 中
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.adb_controller import DeviceController



def smart_crop_box(mask, x, y, w, h):
    """智慧去邊演算法，沿用專案現有邏輯"""
    sub_mask = mask[y:y+h, x:x+w]
    if sub_mask.shape[0] == 0 or sub_mask.shape[1] == 0:
        return x, y, w, h
        
    mid_x1, mid_x2 = int(w * 0.3), int(w * 0.7)
    mid_y1, mid_y2 = int(h * 0.3), int(h * 0.7)
    
    if mid_x1 == mid_x2 or mid_y1 == mid_y2:
        return x, y, w, h
        
    row_sums_mid = np.sum(sub_mask[:, mid_x1:mid_x2] > 0, axis=1)
    mid_w = mid_x2 - mid_x1
    
    top = 0
    while top < h and row_sums_mid[top] > mid_w * 0.3:
        top += 1
        
    bottom = h - 1
    while bottom >= 0 and row_sums_mid[bottom] > mid_w * 0.3:
        bottom -= 1
        
    col_sums_mid = np.sum(sub_mask[mid_y1:mid_y2, :] > 0, axis=0)
    mid_h = mid_y2 - mid_y1
    
    left = 0
    while left < w and col_sums_mid[left] > mid_h * 0.3:
        left += 1
        
    right = w - 1
    while right >= 0 and col_sums_mid[right] > mid_h * 0.3:
        right -= 1
    
    if top > bottom or left > right:
        return x, y, w, h
    return x + left, y + top, right - left + 1, bottom - top + 1

def run_yijie_task(controller: DeviceController):
    """
    實作「異界奇聞」點擊流程
    綠框為場景 Anchor，紅框為點擊 Target。
    """
    print("🚀 執行「異界奇聞」任務...")
    route_dir = PROJECT_ROOT / "AwayFromKeyboard" / "route_screenshots" / "異界奇聞"
    if not route_dir.exists():
        print(f"⚠️ [警告] 找不到異界奇聞圖片目錄: {route_dir}")
        return
        
    for img_path in sorted(route_dir.glob("*.png")):
        img = cv2.imdecode(np.fromfile(str(img_path), dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            continue
            
        # 找紅框 (Target)
        lower_red1 = np.array([30, 20, 230])
        upper_red1 = np.array([50, 40, 255])
        mask_r1 = cv2.inRange(img, lower_red1, upper_red1)
        lower_red2 = np.array([0, 0, 240])
        upper_red2 = np.array([10, 10, 255])
        mask_r2 = cv2.inRange(img, lower_red2, upper_red2)
        mask_r = mask_r1 | mask_r2
        
        contours_r, _ = cv2.findContours(mask_r, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        target_rect = None
        best_r_area = 0
        for cnt in contours_r:
            rx, ry, rw, rh = cv2.boundingRect(cnt)
            if rw < 15 or rh < 15: continue
            if rw * rh > best_r_area:
                best_r_area = rw * rh
                target_rect = smart_crop_box(mask_r, rx, ry, rw, rh)
                
        # 找綠框 (Anchor)
        lower_green = np.array([0, 200, 0])
        upper_green = np.array([50, 255, 50])
        mask_g = cv2.inRange(img, lower_green, upper_green)
        contours_g, _ = cv2.findContours(mask_g, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        anchor_rect = None
        best_g_area = 0
        for cnt in contours_g:
            gx, gy, gw, gh = cv2.boundingRect(cnt)
            if gw < 15 or gh < 15: continue
            if gw * gh > best_g_area:
                best_g_area = gw * gh
                anchor_rect = smart_crop_box(mask_g, gx, gy, gw, gh)
                
        if not target_rect:
            continue
            
        screen = getattr(controller, "get_screen", getattr(controller, "screenshot", None))()
        if screen is None:
            continue
            
        sh, sw = screen.shape[:2]
        
        if anchor_rect:
            # 有綠框作為 Anchor
            gx, gy, gw, gh = anchor_rect
            anchor_template = img[gy:gy+gh, gx:gx+gw]
            
            roi_x1 = max(0, gx - 150)
            roi_x2 = min(sw, gx + gw + 150)
            roi_y1 = max(0, gy - 150)
            roi_y2 = min(sh, gy + gh + 150)
            
            screen_roi = screen[roi_y1:roi_y2, roi_x1:roi_x2]
            res = cv2.matchTemplate(screen_roi, anchor_template, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(res)
            
            if max_val >= 0.7:
                offset_x = max_loc[0] + roi_x1 - gx
                offset_y = max_loc[1] + roi_y1 - gy
                
                tx, ty, tw, th = target_rect
                abs_cx = tx + tw // 2 + offset_x
                abs_cy = ty + th // 2 + offset_y
                print(f"[異界奇聞] 透過綠框 Anchor 找到場景 (信心度 {max_val:.2f})，點擊紅框 Target: ({abs_cx}, {abs_cy})")
                controller.tap(abs_cx, abs_cy)
                time.sleep(2)
            else:
                print(f"  [Debug] {img_path.name} 找不到綠框 Anchor (最高信心度 {max_val:.2f})")
        else:
            # 只有紅框，直接對紅框做比對
            tx, ty, tw, th = target_rect
            target_template = img[ty:ty+th, tx:tx+tw]
            
            roi_x1 = max(0, tx - 150)
            roi_x2 = min(sw, tx + tw + 150)
            roi_y1 = max(0, ty - 150)
            roi_y2 = min(sh, ty + th + 150)
            
            screen_roi = screen[roi_y1:roi_y2, roi_x1:roi_x2]
            res = cv2.matchTemplate(screen_roi, target_template, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(res)
            
            if max_val >= 0.7:
                abs_cx = roi_x1 + max_loc[0] + tw // 2
                abs_cy = roi_y1 + max_loc[1] + th // 2
                print(f"[異界奇聞] 找到紅框 Target (信心度 {max_val:.2f})，直接點擊: ({abs_cx}, {abs_cy})")
                controller.tap(abs_cx, abs_cy)
                time.sleep(2)
            else:
                print(f"  [Debug] {img_path.name} 找不到紅框 Target (最高信心度 {max_val:.2f})")

def run_integration_flow():
    python_exe = str(PROJECT_ROOT / ".venv-codex" / "Scripts" / "python.exe")
    run_router_script = str(PROJECT_ROOT / "AwayFromKeyboard" / "integration_task" / "run_router.py")
    auto_shoot_script = str(PROJECT_ROOT / "call_of_the_gale" / "scripts" / "auto_shoot.py")
    
    # 根據要求統籌呼叫「每日任務、點金手、異界奇聞、疾風呼喚」等子任務
    tasks = [
        {"name": "每日任務", "type": "subprocess", "cmd": [python_exe, run_router_script, "每日任務"]},
        {"name": "點金手", "type": "subprocess", "cmd": [python_exe, run_router_script, "點金手"]},
        {"name": "異界奇聞", "type": "custom", "cmd": None},
        {"name": "疾風呼喚", "type": "subprocess", "cmd": [python_exe, auto_shoot_script]},
    ]
    
    try:
        controller = DeviceController()
    except Exception as e:
        print(f"⚠️ [警告] 無法初始化 DeviceController: {e}")
        return
    
    for task in tasks:
        print("\n" + "=" * 60)
        print(f"▶️ 開始執行子任務: {task['name']}")
        print("=" * 60)
        
        if task["type"] == "custom" and task["name"] == "異界奇聞":
            run_yijie_task(controller)
        elif task["type"] == "subprocess":
            try:
                print(f"執行外部指令: {' '.join(task['cmd'])}")
                subprocess.run(task["cmd"], cwd=str(PROJECT_ROOT))
            except Exception as e:
                print(f"❌ 任務 {task['name']} 執行時崩潰: {e}")
                


if __name__ == "__main__":
    run_integration_flow()
