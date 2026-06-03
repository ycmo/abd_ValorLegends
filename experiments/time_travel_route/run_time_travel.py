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

class TimeTravelRouteRunner:
    def __init__(self, serial, timeout=300, interval=2.0, debug=False):
        self.device = DeviceController(serial)
        self.timeout = timeout
        self.interval = interval
        self.debug = debug
        
        self.tt_scenes_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "scenes")
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
        p1 = os.path.join(self.tt_scenes_dir, f"{scene_name}_anchor.png")
        if os.path.exists(p1):
            return p1
        p2 = os.path.join(self.endless_scenes_dir, f"{scene_name}_anchor.png")
        if os.path.exists(p2):
            return p2
        return None

    def detect_scene(self, screen):
        scene_thresholds = {
            "001_daily_tasks": 0.85, # from endless_trial_route
            "002_time_travel": 0.85,
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

        print("Starting Time Travel Runner...")
        
        consecutive_unknown = 0
        action_count = {}
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
                row_anchor = self.get_anchor_path("001_time_travel_task_row")
                res = match_single_template(screen, row_anchor, None, 0.8)
                if res:
                    cx, cy = res["center"]
                    
                    # Verify that the button is actually "GO" (前往), not "Claim" (領取)
                    go_btn_anchor = os.path.join(self.tt_scenes_dir, "001_go_button_anchor.png")
                    # Check the right side of this specific row
                    button_area = screen[max(0, cy-40):min(screen.shape[0], cy+40), 700:950]
                    go_res = match_single_template(button_area, go_btn_anchor, None, 0.60)
                    
                    if go_res:
                        action = "tap_time_travel_go_button"
                        self.device.tap(838, cy)
                        swipe_count = 0
                    else:
                        print(f"[{datetime.datetime.now().isoformat()}] Task row found, but GO button not found! It might be completed (Claim). Exiting safely.")
                        print("DONE")
                        sys.exit(0)
                else:
                    action = "swipe_to_find_task"
                    if swipe_count < 3:
                        self.device.swipe(480, 350, 480, 250, 1500)
                    else:
                        self.device.swipe(480, 250, 480, 350, 1500)
                    
                    swipe_count += 1
                    if swipe_count > 6:
                        print("Error: Swiped too many times without finding task.")
                        print("STOPPED_FOR_HUMAN_REVIEW")
                        sys.exit(1)
                        
            elif scene == "002_time_travel":
                # Check if it costs 100 gems
                cost_100_anchor = os.path.join(self.tt_scenes_dir, "002_time_travel_100_cost_anchor.png")
                # We crop the button area to avoid false positives elsewhere
                button_area = screen[390:450, 650:850]
                res = match_single_template(button_area, cost_100_anchor, None, 0.70)
                
                if res:
                    # It costs 100 gems! We are done.
                    action = "task_completed_exit"
                    print(f"[{datetime.datetime.now().isoformat()}] 100 Gems limit reached! Exiting.")
                    self.device.tap(100, 100) # Tap blank space to return
                    print(f"[{datetime.datetime.now().isoformat()}] Scene: {scene}, Action: {action}, Confidence: {confidence:.4f}, Screenshot: {screenshot_path}")
                    print("DONE")
                    sys.exit(0)
                else:
                    # It is free or 50 gems.
                    action = "tap_travel_and_collect"
                    self.device.tap(748, 420) # Tap travel button
                    print(f"[{datetime.datetime.now().isoformat()}] Tapped Travel. Waiting for reward...")
                    time.sleep(3.0)
                    self.device.tap(480, 80) # Blind tap top center to close reward safely
                    time.sleep(1.0)
                
            if action != "none":
                last_active_time = time.time()
                
            print(f"[{datetime.datetime.now().isoformat()}] Scene: {scene}, Action: {action}, Confidence: {confidence:.4f}, Screenshot: {screenshot_path}")
            
            state_key = f"{scene}_{action}"
            action_count[state_key] = action_count.get(state_key, 0) + 1
            if action_count[state_key] > 10 and action != "none":
                print(f"Error: Same action '{action}' on scene '{scene}' repeated >10 times. Safety stop.")
                print("STOPPED_FOR_HUMAN_REVIEW")
                sys.exit(1)
                
            time.sleep(self.interval)
            
        print("Error: Execution timeout reached.")
        print("STOPPED_FOR_HUMAN_REVIEW")
        sys.exit(1)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Time Travel Runner")
    parser.add_argument("--serial", type=str, default=None, help="ADB serial (e.g. 127.0.0.1:5555)")
    parser.add_argument("--timeout", type=int, default=300, help="Idle timeout in seconds")
    parser.add_argument("--interval", type=float, default=2.0, help="Loop interval in seconds")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    args = parser.parse_args()
    
    if args.serial is None:
        args.serial = get_default_adb_target()
        
    runner = TimeTravelRouteRunner(args.serial, args.timeout, args.interval, args.debug)
    runner.run()
