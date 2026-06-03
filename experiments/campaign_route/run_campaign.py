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

def get_roi(shape, roi_type):
    # Same as endless trial
    return None

def match_single_template(screen, template_path, roi=None, threshold=0.8):
    if not template_path or not os.path.exists(template_path):
        return None
    with open(template_path, "rb") as f:
        tpl_array = np.frombuffer(f.read(), dtype=np.uint8)
    tpl = cv2.imdecode(tpl_array, cv2.IMREAD_COLOR)
    if tpl is None:
        return None

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

class CampaignRouteRunner:
    def __init__(self, serial, timeout=300, interval=2.0, debug=False):
        self.device = DeviceController(serial)
        self.timeout = timeout
        self.interval = interval
        self.debug = debug
        
        self.campaign_scenes_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "scenes")
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
        # Prefer campaign_route assets, fallback to endless_trial_route assets
        p1 = os.path.join(self.campaign_scenes_dir, f"{scene_name}_anchor.png")
        if os.path.exists(p1):
            return p1
        p2 = os.path.join(self.endless_scenes_dir, f"{scene_name}_anchor.png")
        if os.path.exists(p2):
            return p2
        return None

    def detect_scene(self, screen):
        scene_thresholds = {
            "001_daily_tasks": 0.85, # using endless trial's anchor
            "002_idle_screen": 0.85,
            "004_stage_team_grouping": 0.85,
            "004_battle": 0.85,
            "005_battle_end": 0.85,
            "006_battle_fail": 0.85,
            "008_exit_confirm": 0.85,
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

        print("Starting Campaign Stage Runner...")
        
        consecutive_unknown = 0
        action_count = {}
        in_battle_combat = False
        battle_done = False
        battle_failed = False
        swipe_count = 0
        
        last_active_time = time.time()
        while time.time() - last_active_time < self.timeout:
            screen = self.device.screenshot()
            scene, confidence = self.detect_scene(screen)
            
            if scene is None:
                if in_battle_combat:
                    print(f"[{datetime.datetime.now().isoformat()}] Scene: Unknown (In Combat), waiting for battle end...")
                    last_active_time = time.time()
                    time.sleep(self.interval)
                    continue
                
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
                # Find the campaign task row
                row_anchor = self.get_anchor_path("001_campaign_task_row")
                res = match_single_template(screen, row_anchor, None, 0.8)
                if res:
                    # Found it! The Go button is roughly at x=839, and y is the same as the center of the matched row
                    cx, cy = res["center"]
                    action = "tap_campaign_go_button"
                    self.device.tap(839, cy)
                    swipe_count = 0 # reset
                else:
                    # Need to swipe to find it
                    action = "swipe_down_to_find_task"
                    if swipe_count < 3:
                        # swipe from bottom to top (scroll down)
                        self.device.swipe(480, 350, 480, 200, 800)
                    else:
                        # swipe from top to bottom (scroll up)
                        self.device.swipe(480, 200, 480, 350, 800)
                    
                    swipe_count += 1
                    if swipe_count > 6:
                        print("Error: Swiped too many times without finding campaign task.")
                        print("STOPPED_FOR_HUMAN_REVIEW")
                        sys.exit(1)
                        
            elif scene == "002_idle_screen":
                if not battle_done and not battle_failed:
                    action = "tap_idle_challenge_button"
                    self.device.tap(835, 419)
                else:
                    action = "task_completed_at_idle_screen"
                    print(f"[{datetime.datetime.now().isoformat()}] Scene: {scene}, Action: {action}, Confidence: {confidence:.4f}, Screenshot: {screenshot_path}")
                    print("DONE")
                    sys.exit(0)
                    
            elif scene == "004_stage_team_grouping":
                action = "tap_grouping_challenge_button"
                self.device.tap(690, 412)
                
            elif scene == "004_battle":
                if battle_failed:
                    action = "tap_back_after_failure"
                    self.device.tap(51, 24)
                else:
                    action = "tap_start_combat_button"
                    self.device.tap(902, 480)
                    in_battle_combat = True
                    print(f"[{datetime.datetime.now().isoformat()}] Waiting 5 seconds for combat to begin...")
                    time.sleep(5)
                    
            elif scene == "005_battle_end":
                action = "tap_close_battle_result"
                self.device.tap(480, 480)
                in_battle_combat = False
                battle_done = True
                
            elif scene == "006_battle_fail":
                action = "tap_close_battle_fail"
                self.device.tap(479, 507)
                in_battle_combat = False
                battle_failed = True
                
            elif scene == "008_exit_confirm":
                action = "tap_confirm_exit"
                self.device.tap(589, 401)
                
            if action != "none":
                last_active_time = time.time()
                
            print(f"[{datetime.datetime.now().isoformat()}] Scene: {scene}, Action: {action}, Confidence: {confidence:.4f}, Screenshot: {screenshot_path}")
            
            # Anti-loop check
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
    parser = argparse.ArgumentParser(description="Campaign Stage Runner")
    parser.add_argument("--serial", type=str, default=None, help="ADB serial (e.g. 127.0.0.1:5555)")
    parser.add_argument("--timeout", type=int, default=300, help="Idle timeout in seconds")
    parser.add_argument("--interval", type=float, default=2.0, help="Loop interval in seconds")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    args = parser.parse_args()
    
    if args.serial is None:
        args.serial = get_default_adb_target()
        
    runner = CampaignRouteRunner(args.serial, args.timeout, args.interval, args.debug)
    runner.run()
