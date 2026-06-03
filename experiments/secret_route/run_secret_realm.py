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

class SecretRouteRunner:
    def __init__(self, serial, timeout=300, interval=2.0, debug=False):
        self.device = DeviceController(serial)
        self.timeout = timeout
        self.interval = interval
        self.debug = debug
        
        self.secret_scenes_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "scenes")
        self.endless_scenes_dir = os.path.join(PROJECT_ROOT, "experiments", "endless_trial_route", "assets", "scenes")
        
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

    def get_anchor_path(self, scene_name):
        p1 = os.path.join(self.secret_scenes_dir, f"{scene_name}_anchor.png")
        if os.path.exists(p1):
            return p1
        p2 = os.path.join(self.endless_scenes_dir, f"{scene_name}_anchor.png")
        if os.path.exists(p2):
            return p2
        return None

    def detect_scene(self, screen):
        scene_thresholds = {
            "001_daily_tasks": 0.85, # from endless_trial_route
            "004_purchase_dialog": 0.85, # Popups must be evaluated first!
            "002_secret_menu": 0.85,
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

        print("Starting Secret Realm Runner...")
        
        consecutive_unknown = 0
        action_count = {}
        has_purchased = False
        has_swept = False
        swipe_count = 0
        
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
                row_anchor = self.get_anchor_path("001_secret_task_row")
                res = match_single_template(screen, row_anchor, None, 0.8)
                if res:
                    cx, cy = res["center"]
                    action = "tap_secret_go_button"
                    self.device.tap(840, cy)
                    swipe_count = 0
                else:
                    action = "swipe_to_find_task"
                    if swipe_count < 3:
                        self.device.swipe(480, 350, 480, 200, 800)
                    else:
                        self.device.swipe(480, 200, 480, 350, 800)
                    
                    swipe_count += 1
                    if swipe_count > 6:
                        print("Error: Swiped too many times without finding secret realm task.")
                        print("STOPPED_FOR_HUMAN_REVIEW")
                        sys.exit(1)
                        
            elif scene == "002_secret_menu":
                if not has_purchased:
                    action = "tap_lost_forest_and_plus"
                    self.device.tap(104, 292) # select menu
                    time.sleep(1.0)
                    self.device.tap(330, 68)  # tap + button
                elif not has_swept:
                    action = "tap_sweep_all"
                    self.device.tap(830, 460) # Tap Sweep All
                    print(f"[{datetime.datetime.now().isoformat()}] Tapped Sweep All. Waiting for reward animation...")
                    time.sleep(3.0)
                    self.device.tap(480, 80) # Blind tap top center to close reward safely
                    time.sleep(1.0)
                    has_swept = True
                else:
                    action = "task_completed_exit"
                    self.device.tap(28, 24)
                    print(f"[{datetime.datetime.now().isoformat()}] Scene: {scene}, Action: {action}, Confidence: {confidence:.4f}, Screenshot: {screenshot_path}")
                    print("DONE")
                    sys.exit(0)
                
            elif scene == "004_purchase_dialog":
                action = "tap_purchase_confirm"
                # The user marked the + button (600, 287) and confirm (480, 424)
                self.device.tap(600, 287)
                time.sleep(0.5)
                self.device.tap(480, 424)
                has_purchased = True
                
            if action != "none":
                last_active_time = time.time()
                
            print(f"[{datetime.datetime.now().isoformat()}] Scene: {scene}, Action: {action}, Confidence: {confidence:.4f}, Screenshot: {screenshot_path}")
            
            state_key = f"{scene}_{action}"
            action_count[state_key] = action_count.get(state_key, 0) + 1
            if action_count[state_key] > 5 and action != "none":
                print(f"Error: Same action '{action}' on scene '{scene}' repeated >5 times. Safety stop.")
                print("STOPPED_FOR_HUMAN_REVIEW")
                sys.exit(1)
                
            time.sleep(self.interval)
            
        print("Error: Execution timeout reached.")
        print("STOPPED_FOR_HUMAN_REVIEW")
        sys.exit(1)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Secret Realm Runner")
    parser.add_argument("--serial", type=str, default=None, help="ADB serial (e.g. 127.0.0.1:5555)")
    parser.add_argument("--timeout", type=int, default=300, help="Idle timeout in seconds")
    parser.add_argument("--interval", type=float, default=2.0, help="Loop interval in seconds")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    args = parser.parse_args()
    
    if args.serial is None:
        args.serial = get_default_adb_target()
        
    runner = SecretRouteRunner(args.serial, args.timeout, args.interval, args.debug)
    runner.run()
