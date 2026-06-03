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

GO_BUTTON_PATH = os.path.join(PROJECT_ROOT, "assets", "go_button.png")

# Midas popup: 3 claim buttons at fixed x positions (960x540 screen)
# (2h free=240, 4h=480, 8h=720), all at y=445
MIDAS_BUTTONS = [
    (240, 445, "2h_free"),
    (480, 445, "4h_20gem"),
    (720, 445, "8h_50gem"),
]
MIDAS_X_BTN = (780, 79)          # Close X button on Midas popup
GRAY_STD_THRESHOLD = 20          # std_dev < this -> button is gray (unavailable)

def match_single_template(screen, template_path, roi=None, threshold=0.8):
    if not os.path.exists(template_path):
        return None
    with open(template_path, "rb") as f:
        tpl_array = np.frombuffer(f.read(), dtype=np.uint8)
    tpl = cv2.imdecode(tpl_array, cv2.IMREAD_COLOR)
    if tpl is None:
        return None

    if roi:
        x, y, w, h = roi
        screen_crop = screen[y:y+h, x:x+w]
        offset_x, offset_y = x, y
    else:
        screen_crop = screen
        offset_x, offset_y = 0, 0

    res = cv2.matchTemplate(screen_crop, tpl, cv2.TM_CCOEFF_NORMED)
    min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res)

    if max_val >= threshold:
        center_x = max_loc[0] + tpl.shape[1] // 2 + offset_x
        center_y = max_loc[1] + tpl.shape[0] // 2 + offset_y
        return {
            "confidence": max_val,
            "top_left": (max_loc[0] + offset_x, max_loc[1] + offset_y),
            "center": (center_x, center_y)
        }
    return None

class MidasRouteRunner:
    def __init__(self, serial, timeout=90, interval=1.5, debug=False):
        self.device = DeviceController(serial)
        self.timeout = timeout
        self.interval = interval
        self.debug = debug
        self.scenes_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "scenes")
        
        if self.debug:
            self.debug_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "debug")
            os.makedirs(self.debug_dir, exist_ok=True)

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

    def detect_scene(self, screen):
        scene_thresholds = {
            "001_daily_tasks": 0.85,
            "002_midas": 0.85,
            "003_midas_reward": 0.85,
        }
        
        best_scene = None
        best_val = 0.0
        
        for scene_name, threshold in scene_thresholds.items():
            anchor_path = os.path.join(self.scenes_dir, f"{scene_name}_anchor.png")
            res = match_single_template(screen, anchor_path, None, threshold)
            if res and res["confidence"] > best_val:
                best_val = res["confidence"]
                best_scene = scene_name
                
        return best_scene, best_val

    def run(self):
        if not self.device.connect():
            print("Error: Failed to connect to ADB device.", file=sys.stderr)
            sys.exit(1)

        print("Starting Midas Touch Runner...")
        
        consecutive_unknown = 0
        action_count = {}  # anti-loop: scene_action -> count
        last_active_time = time.time()
        
        while time.time() - last_active_time < self.timeout:
            screen = self.device.screenshot()
            scene, confidence = self.detect_scene(screen)
            
            if scene is None:
                consecutive_unknown += 1
                screenshot_path = self.save_screenshot(screen, "unknown")
                print(f"[{datetime.datetime.now().isoformat()}] Detected scene: Unknown, confidence: N/A, screenshot: {screenshot_path}")
                
                if consecutive_unknown > 3:
                    print("Error: Scene detection failed consecutively. Triggering STOPPED_FOR_HUMAN_REVIEW.")
                    print("STOPPED_FOR_HUMAN_REVIEW")
                    sys.exit(1)
                
                time.sleep(self.interval)
                continue
            
            consecutive_unknown = 0
            screenshot_path = self.save_screenshot(screen, scene)
            action = "none"
            
            if scene == "001_daily_tasks":
                # Use template matching to find the actual Go button
                # instead of a hardcoded coordinate.
                go_result = match_single_template(screen, GO_BUTTON_PATH, threshold=0.8)
                if go_result:
                    cx, cy = go_result["center"]
                    action = f"tap_go_button_at_{cx}_{cy}"
                    print(f"[{datetime.datetime.now().isoformat()}] Found Go button at ({cx},{cy}) conf={go_result['confidence']:.3f}")
                    self.device.tap(cx, cy)
                else:
                    # No active Go button found — Midas task already complete.
                    print(f"[{datetime.datetime.now().isoformat()}] Scene: {scene}, No active Go button found. Midas task already complete.")
                    print("DONE")
                    sys.exit(0)
                
            elif scene == "002_midas":
                # Scan all 3 buttons left-to-right, tap the first active one.
                # A button is "active" when its pixel std_dev >= GRAY_STD_THRESHOLD.
                tapped = False
                for bx, by, bname in MIDAS_BUTTONS:
                    b, g, r = screen[by, bx]
                    std_dev = np.std([int(b), int(g), int(r)])
                    is_active = std_dev >= GRAY_STD_THRESHOLD
                    print(f"  [{bname}] ({bx},{by}) BGR=({b},{g},{r}) std={std_dev:.1f} -> {'ACTIVE' if is_active else 'gray'}")
                    if is_active:
                        action = f"tap_{bname}_at_{bx}_{by}"
                        self.device.tap(bx, by)
                        tapped = True
                        break  # handle one at a time; reward overlay will appear next

                if not tapped:
                    # All buttons gray -> all claimed -> close popup
                    action = "tap_exit_all_claimed"
                    print(f"[{datetime.datetime.now().isoformat()}] All Midas buttons exhausted. Tapping X to leave.")
                    self.device.tap(*MIDAS_X_BTN)
                    time.sleep(1.5)
                    print("DONE")
                    sys.exit(0)

            elif scene == "003_midas_reward":
                # Tap the "獲得金幣" title text to dismiss the overlay.
                # Do NOT tap the coin icon below (~480,290) — it opens an item info popup.
                action = "tap_close_reward"
                self.device.tap(480, 160)
                    
            print(f"[{datetime.datetime.now().isoformat()}] Scene: {scene}, Action: {action}, Confidence: {confidence:.4f}, Screenshot: {screenshot_path}")
            
            if action != "none":
                last_active_time = time.time()
                # Anti-loop: only track 002_midas button taps.
                # 003_midas_reward is expected to appear once per claim (can be 6+ times).
                if scene == "002_midas":
                    key = f"{scene}_{action.split('_at_')[0]}"
                    action_count[key] = action_count.get(key, 0) + 1
                    if action_count[key] > 3:
                        self.save_screenshot(screen, f"loop_detected_{scene}")
                        print(f"Error: Action '{action}' on scene '{scene}' repeated >3 times. STOPPED_FOR_HUMAN_REVIEW.")
                        print("STOPPED_FOR_HUMAN_REVIEW")
                        sys.exit(1)
                
            time.sleep(self.interval)
            
        print("Error: Execution timeout reached.")
        print("STOPPED_FOR_HUMAN_REVIEW")
        sys.exit(1)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Midas Touch Runner")
    parser.add_argument("--serial", type=str, default=None, help="ADB serial (e.g. 127.0.0.1:5555)")
    parser.add_argument("--timeout", type=int, default=60, help="Idle timeout in seconds")
    parser.add_argument("--interval", type=float, default=1.5, help="Loop interval in seconds")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    args = parser.parse_args()
    
    if args.serial is None:
        args.serial = get_default_adb_target()
        
    runner = MidasRouteRunner(args.serial, args.timeout, args.interval, args.debug)
    runner.run()
