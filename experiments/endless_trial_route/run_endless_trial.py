import argparse
import sys
import os
import time
import datetime
import cv2
import numpy as np

# Ensure we can import from src/
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

from adb_controller import DeviceController

def get_roi(screen_shape, roi_type):
    H, W = screen_shape[:2]
    if roi_type == "full_screen":
        return (0, H, 0, W)
    return (0, H, 0, W)

def match_single_template(screen, template_path, roi, threshold):
    if not os.path.exists(template_path):
        return None
    # Read template safely supporting unicode paths
    with open(template_path, "rb") as f:
        data = f.read()
    tmpl_array = np.frombuffer(data, dtype=np.uint8)
    tmpl = cv2.imdecode(tmpl_array, cv2.IMREAD_COLOR)
    if tmpl is None:
        return None
    th, tw = tmpl.shape[:2]
    y1, y2, x1, x2 = roi
    
    y1c = max(0, y1)
    y2c = min(screen.shape[0], y2)
    x1c = max(0, x1)
    x2c = min(screen.shape[1], x2)
    
    roi_img = screen[y1c:y2c, x1c:x2c]
    if roi_img.size == 0 or th > roi_img.shape[0] or tw > roi_img.shape[1]:
        return None
        
    result_map = cv2.matchTemplate(roi_img, tmpl, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result_map)
    
    confidence = float(max_val)
    if confidence >= threshold:
        abs_x = max_loc[0] + x1c
        abs_y = max_loc[1] + y1c
        center_x = abs_x + tw // 2
        center_y = abs_y + th // 2
        return {
            "template": template_path,
            "confidence": confidence,
            "bbox": (abs_x, abs_y, tw, th),
            "center": (center_x, center_y)
        }
    return None

class ResumableEndlessTrialRunner:
    def __init__(self, serial, timeout, interval, debug_mode):
        self.device = DeviceController(serial)
        self.timeout = timeout
        self.interval = interval
        self.debug_mode = debug_mode
        self.base_dir = os.path.dirname(os.path.abspath(__file__))
        self.debug_dir = os.path.join(self.base_dir, "debug")
        self.scenes_dir = os.path.join(self.base_dir, "assets", "scenes")
        
        if not os.path.exists(self.debug_dir):
            os.makedirs(self.debug_dir)

    def save_screenshot(self, screen, suffix=""):
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"step_{ts}_{suffix}.png"
        path = os.path.join(self.debug_dir, filename)
        # Save safely
        success, buf = cv2.imencode(".png", screen)
        if success:
            with open(path, "wb") as f:
                f.write(buf.tobytes())
        return path

    def detect_scene(self, screen):
        scene_thresholds = {
            "001_daily_tasks": 0.85,
            "002_trial_lobby": 0.85,
            "003_stage_details": 0.85,
            "004_stage_team_grouping": 0.85,
            "004_battle": 0.85,
            "005_battle_end": 0.85,
            "006_battle_fail": 0.85,
            "006_stage_details_post": 0.85,
            "007_trial_lobby_post": 0.85,
            "008_exit_confirm": 0.85,
        }
        
        best_scene = None
        best_val = 0.0
        
        for scene_name, threshold in scene_thresholds.items():
            anchor_path = os.path.join(self.scenes_dir, f"{scene_name}_anchor.png")
            if not os.path.exists(anchor_path):
                continue
            res = match_single_template(screen, anchor_path, get_roi(screen.shape, "full_screen"), threshold)
            if res and res["confidence"] > best_val:
                best_val = res["confidence"]
                best_scene = scene_name
                
        return best_scene, best_val

    def run(self):
        if not self.device.connect():
            print("Error: Failed to connect to ADB device.", file=sys.stderr)
            sys.exit(1)

        print("Starting Resumable Endless Trial Runner...")
        
        consecutive_unknown = 0
        action_count = {}
        in_battle_combat = False
        battle_done = False
        battle_failed = False
        
        # Start state loop
        last_active_time = time.time()
        while time.time() - last_active_time < self.timeout:
            screen = self.device.screenshot()
            scene, confidence = self.detect_scene(screen)
            
            if scene is None:
                # If we are currently in combat, it's normal for the scene to be unknown.
                if in_battle_combat:
                    print(f"[{datetime.datetime.now().isoformat()}] Scene: Unknown (In Combat), waiting for battle end...")
                    last_active_time = time.time()  # Reset timeout while in combat
                    time.sleep(self.interval)
                    continue
                
                # Save screenshot and wait a bit to retry (max 2 consecutive unknowns when not in combat)
                consecutive_unknown += 1
                screenshot_path = self.save_screenshot(screen, "unknown")
                print(f"[{datetime.datetime.now().isoformat()}] Detected scene: Unknown, confidence: N/A, screenshot: {screenshot_path}")
                
                if consecutive_unknown > 2:
                    print("Error: Scene detection failed consecutively. Triggering STOPPED_FOR_HUMAN_REVIEW.")
                    print("STOPPED_FOR_HUMAN_REVIEW")
                    sys.exit(1)
                
                time.sleep(self.interval)
                continue
            
            consecutive_unknown = 0
            screenshot_path = self.save_screenshot(screen, scene)
            
            # Action Mapping
            action = "none"
            if scene == "001_daily_tasks":
                go_btn_path = os.path.join(PROJECT_ROOT, "assets", "go_button.png")
                res = match_single_template(screen, go_btn_path, get_roi(screen.shape, "full_screen"), 0.8)
                if res:
                    cx, cy = res["center"]
                    action = f"tap_go_button_at_{cx}_{cy}"
                    self.device.tap(cx, cy)
                else:
                    action = "fallback_tap_go_row_coordinate"
                    self.device.tap(600, 240)
            
            elif scene in ["002_trial_lobby", "007_trial_lobby_post"]:
                if not battle_done and not battle_failed:
                    action = "tap_castle_tower"
                    self.device.tap(190, 270)
                else:
                    action = "task_completed_at_lobby"
                    print(f"[{datetime.datetime.now().isoformat()}] Scene: {scene}, Action: {action}, Confidence: {confidence:.4f}, Screenshot: {screenshot_path}")
                    print("DONE")
                    sys.exit(0)
            
            elif scene in ["003_stage_details", "006_stage_details_post"]:
                if not battle_done and not battle_failed:
                    action = "tap_challenge_button"
                    self.device.tap(896, 477)
                else:
                    action = "tap_back_button"
                    self.device.tap(61, 22)
                    
            elif scene == "004_stage_team_grouping":
                action = "tap_grouping_challenge_button"
                self.device.tap(690, 412)
                
            elif scene == "004_battle":
                if battle_failed:
                    action = "tap_back_after_failure"
                    self.device.tap(51, 24)
                else:
                    # Tap Challenge button at bottom-right (around x=902, y=480) to start the actual fight
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
                last_active_time = time.time()  # Reset timeout when we take a valid action
                
            print(f"[{datetime.datetime.now().isoformat()}] Scene: {scene}, Action: {action}, Confidence: {confidence:.4f}, Screenshot: {screenshot_path}")
            
            # Anti-loop check: if same action repeated on same scene > 3 times, break
            state_key = f"{scene}_{action}"
            action_count[state_key] = action_count.get(state_key, 0) + 1
            if action_count[state_key] > 3 and action != "none":
                print(f"Error: Same action '{action}' on scene '{scene}' repeated 3 times. Safety stop.")
                print("STOPPED_FOR_HUMAN_REVIEW")
                sys.exit(1)
                
            time.sleep(self.interval)
            
        print("Error: Execution timeout reached (no progress within timeout limit).")
        print("STOPPED_FOR_HUMAN_REVIEW")
        sys.exit(1)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Resumable Endless Trial Runner")
    parser.add_argument("--serial", type=str, default=None, help="ADB serial (e.g. 127.0.0.1:5555)")
    parser.add_argument("--threshold", type=float, default=0.85, help="Template matching threshold")
    parser.add_argument("--timeout", type=int, default=90, help="Idle timeout in seconds before giving up")
    parser.add_argument("--interval", type=float, default=2.0, help="Loop interval in seconds")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    args = parser.parse_args()
    
    runner = ResumableEndlessTrialRunner(args.serial, args.timeout, args.interval, args.debug)
    runner.run()
