import os
import sys
import time
import datetime
import argparse
import numpy as np
import cv2
from pathlib import Path

# Add src to path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

from adb_controller import DeviceController
from adb_client import get_default_adb_target

def match_single_template(screen, template_path, roi=None, threshold=0.8):
    if not template_path or not os.path.exists(template_path):
        return None
    with open(template_path, "rb") as f:
        tpl_array = np.frombuffer(f.read(), dtype=np.uint8)
    tpl = cv2.imdecode(tpl_array, cv2.IMREAD_COLOR)
    if tpl is None:
        return None

    res = cv2.matchTemplate(screen, tpl, cv2.TM_CCOEFF_NORMED)
    min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res)

    if max_val >= threshold:
        center_x = max_loc[0] + tpl.shape[1] // 2
        center_y = max_loc[1] + tpl.shape[0] // 2
        return {
            "confidence": max_val,
            "top_left": max_loc,
            "center": (center_x, center_y)
        }
    return None

class ArenaRouteRunner:
    def __init__(self, serial, timeout=300, interval=2.0, debug=False):
        self.device = DeviceController(serial)
        self.timeout = timeout
        self.interval = interval
        self.debug = debug
        
        self.arena_scenes_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "scenes")
        self.tt_scenes_dir = os.path.join(PROJECT_ROOT, "experiments", "time_travel_route", "assets", "scenes")
        self.endless_scenes_dir = os.path.join(PROJECT_ROOT, "experiments", "endless_trial_route", "assets", "scenes")
        
        if self.debug:
            self.debug_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "debug")
            os.makedirs(self.debug_dir, exist_ok=True)
            
        self.total_fought = 0

    def save_screenshot(self, screen, name_prefix):
        if not self.debug:
            return "N/A"
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"step_{timestamp}_{name_prefix}.png"
        filepath = os.path.join(self.debug_dir, filename)
        success, buf = cv2.imencode(".png", screen)
        if success:
            Path(filepath).write_bytes(buf.tobytes())
        return filepath

    def get_anchor_path(self, scene_name):
        p1 = os.path.join(self.arena_scenes_dir, f"{scene_name}_anchor.png")
        if os.path.exists(p1):
            return p1
        p2 = os.path.join(self.endless_scenes_dir, f"{scene_name}_anchor.png")
        if os.path.exists(p2):
            return p2
        return None

    def detect_scene(self, screen):
        scene_thresholds = {
            "001_daily_tasks": 0.85,
            "002_arena_main": 0.85,
            "003_arena_multi": 0.85,
            "004_arena_continue": 0.80,
        }
        
        best_scene = None
        best_val = 0.0
        
        for scene_name, threshold in scene_thresholds.items():
            anchor_path = self.get_anchor_path(scene_name)
            if not anchor_path:
                continue
            res = match_single_template(screen, anchor_path, None, threshold)
            if res and res["confidence"] > best_val:
                best_val = res["confidence"]
                best_scene = scene_name
                
        return best_scene, best_val

    def run(self):
        if not self.device.connect():
            print("Error: Failed to connect to ADB device.", file=sys.stderr)
            sys.exit(1)

        print("Starting Arena Runner...")
        
        consecutive_unknown = 0
        action_count = {}
        swipe_count = 0
        current_opponent_idx = 0
        
        last_active_time = time.time()
        while time.time() - last_active_time < self.timeout:
            screen = self.device.screenshot()
            scene, confidence = self.detect_scene(screen)
            
            if scene is None:
                consecutive_unknown += 1
                screenshot_path = self.save_screenshot(screen, "unknown")
                print(f"[{datetime.datetime.now().isoformat()}] Detected scene: Unknown, confidence: N/A, screenshot: {screenshot_path}")
                
                # Check if we are in the formation screen (Challenge Prep)
                # In formation screen, the Back button (55, 43) is usually available.
                # For testing cancellation, if we are unknown, let's just click Back to cancel!
                action = "tap_cancel_formation"
                print(f"[{datetime.datetime.now().isoformat()}] Simulating Cancel / Back out of formation...")
                self.device.tap(55, 43)
                time.sleep(2.0)
                
                if consecutive_unknown > 10:
                    print("Error: Stuck in unknown.")
                    print("STOPPED_FOR_HUMAN_REVIEW")
                    sys.exit(1)
                
                time.sleep(self.interval)
                continue
            
            consecutive_unknown = 0
            screenshot_path = self.save_screenshot(screen, scene)
            action = "none"
            
            if scene == "001_daily_tasks":
                row_anchor = self.get_anchor_path("001_arena_task_row")
                res = match_single_template(screen, row_anchor, None, 0.8)
                if res:
                    cx, cy = res["center"]
                    
                    go_btn_anchor = os.path.join(self.tt_scenes_dir, "001_go_button_anchor.png")
                    button_area = screen[max(0, cy-40):min(screen.shape[0], cy+40), 700:950]
                    go_res = match_single_template(button_area, go_btn_anchor, None, 0.60)
                    
                    if go_res:
                        action = "tap_arena_go_button"
                        self.device.tap(838, cy)
                        swipe_count = 0
                    else:
                        print(f"[{datetime.datetime.now().isoformat()}] Task completed. Exiting.")
                        print("DONE")
                        sys.exit(0)
                else:
                    action = "swipe_to_find_task"
                    if swipe_count < 3:
                        self.device.swipe(480, 350, 480, 250, 1500)
                    else:
                        self.device.swipe(480, 250, 480, 350, 1500)
                    
                    swipe_count += 1
                    if swipe_count > 10:
                        sys.exit(1)
                        
            elif scene == "002_arena_main":
                self.in_battle_transition = False
                if self.total_fought >= 8:
                    print(f"[{datetime.datetime.now().isoformat()}] Total fought {self.total_fought} >= 8. Arena DONE! Tapping back to exit.")
                    action = "tap_back_exit"
                    self.device.tap(55, 43)
                    time.sleep(2.0)
                    sys.exit(0)
                    
                action = "tap_multi_challenge_btn"
                print(f"[{datetime.datetime.now().isoformat()}] Clicking Multi-Challenge button...")
                self.device.tap(552, 502)
                time.sleep(2.0)
                
            elif scene == "003_arena_multi":
                if getattr(self, 'in_battle_transition', False):
                    print(f"[{datetime.datetime.now().isoformat()}] Waiting for battle transition, ignoring 003_arena_multi.")
                    time.sleep(2.0)
                    continue
                    
                print(f"[{datetime.datetime.now().isoformat()}] Entered Multi-Challenge. Screenshot: {screenshot_path}")
                
                import easyocr
                if not hasattr(self, 'reader'):
                    print(f"[{datetime.datetime.now().isoformat()}] Initializing EasyOCR...")
                    self.reader = easyocr.Reader(['en'], gpu=False)

                print(f"[{datetime.datetime.now().isoformat()}] Scanning opponents power by regions...")
                
                # Checkbox X coordinates for column 0 and 1
                chk_x = [436, 812]
                chk_y = [147, 223, 299, 375]
                
                # Exact regions for the power text to avoid reading player names
                col_x_ranges = [(200, 350), (580, 730)]
                row_y_ranges = [(140, 180), (218, 258), (296, 336), (374, 414)]
                
                tapped = False
                for row in range(4):
                    for col in range(2):
                        x0, x1 = col_x_ranges[col]
                        y0, y1 = row_y_ranges[row]
                        roi = screen[y0:y1, x0:x1]
                        
                        # Resize and pad to help OCR
                        roi_large = cv2.resize(roi, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
                        roi_pad = cv2.copyMakeBorder(roi_large, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=[255, 255, 255])
                        
                        results = self.reader.readtext(roi_pad, allowlist='0123456789kK,')
                        if not results:
                            continue
                            
                        text = results[0][1]
                        clean_text = text.lower().replace(',', '')
                        
                        if len(clean_text) >= 2 and any(c.isdigit() for c in clean_text):
                            power_val = 0
                            is_over = False
                            if 'k' in clean_text:
                                try:
                                    power_val = int(clean_text.replace('k', ''))
                                    is_over = power_val > 7000
                                except:
                                    pass
                                    
                            if is_over:
                                target_x = chk_x[col]
                                target_y = chk_y[row]
                                
                                # Check if it is currently green (checked)
                                chk_roi = screen[max(0, target_y-15):min(screen.shape[0], target_y+15), max(0, target_x-15):min(screen.shape[1], target_x+15)]
                                hsv = cv2.cvtColor(chk_roi, cv2.COLOR_BGR2HSV)
                                mask = cv2.inRange(hsv, (40, 80, 100), (90, 255, 255))
                                green_ratio = np.sum(mask > 0) / mask.size if mask.size > 0 else 0
                                
                                if green_ratio > 0.05:
                                    print(f"[{datetime.datetime.now().isoformat()}] Unchecking opponent: power={text} at Col {col+1} Row {row+1}")
                                    self.device.tap(target_x, target_y)
                                    time.sleep(0.8)
                                    tapped = True
                
                action = "scan_and_uncheck"
                
                if not tapped:
                    print(f"[{datetime.datetime.now().isoformat()}] Done unchecking. Calculating total opponents...")
                    checked_count = 0
                    for r in range(4):
                        for c in range(2):
                            tx, ty = chk_x[c], chk_y[r]
                            chk_roi = screen[max(0, ty-15):min(screen.shape[0], ty+15), max(0, tx-15):min(screen.shape[1], tx+15)]
                            hsv = cv2.cvtColor(chk_roi, cv2.COLOR_BGR2HSV)
                            mask = cv2.inRange(hsv, (40, 80, 100), (90, 255, 255))
                            if (np.sum(mask > 0) / mask.size if mask.size > 0 else 0) > 0.05:
                                checked_count += 1
                                
                    self.total_fought += checked_count
                    print(f"[{datetime.datetime.now().isoformat()}] Tapping Challenge button. Fighting {checked_count} opponents. Total fought: {self.total_fought}")
                    action = "tap_challenge_btn"
                    self.device.tap(810, 470)
                    self.in_battle_transition = True
                    time.sleep(4.0)
            
            elif scene == "004_arena_continue":
                self.in_battle_transition = False
                action = "tap_continue"
                print(f"[{datetime.datetime.now().isoformat()}] Battle finished. Clicking continue...")
                self.device.tap(480, 480)
                time.sleep(2.0)
                
            if action != "none":
                last_active_time = time.time()
                
            print(f"[{datetime.datetime.now().isoformat()}] Scene: {scene}, Action: {action}, Confidence: {confidence:.4f}, Screenshot: {screenshot_path}")
            
            state_key = f"{scene}_{action}"
            action_count[state_key] = action_count.get(state_key, 0) + 1
            if action_count[state_key] > 10 and action != "none":
                print(f"Error: Same action '{action}' on scene '{scene}' repeated >10 times.")
                print("STOPPED_FOR_HUMAN_REVIEW")
                sys.exit(1)
                
            time.sleep(self.interval)
            
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Arena Runner")
    parser.add_argument("--serial", type=str, default=None)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--interval", type=float, default=2.0)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    
    if args.serial is None:
        args.serial = get_default_adb_target()
        
    runner = ArenaRouteRunner(args.serial, args.timeout, args.interval, args.debug)
    runner.run()
