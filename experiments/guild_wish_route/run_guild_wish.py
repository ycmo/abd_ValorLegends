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
        
    target = screen
    if roi:
        x, y, w, h = roi
        target = screen[y:y+h, x:x+w]
        
    res = cv2.matchTemplate(target, tpl, cv2.TM_CCOEFF_NORMED)
    min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res)
    
    if max_val >= threshold:
        match_x = max_loc[0] if not roi else max_loc[0] + roi[0]
        match_y = max_loc[1] if not roi else max_loc[1] + roi[1]
        return {
            "confidence": max_val,
            "center": (match_x + tpl.shape[1]//2, match_y + tpl.shape[0]//2),
            "top_left": (match_x, match_y),
            "size": (tpl.shape[1], tpl.shape[0])
        }
    return None

class GuildWishRouteRunner:
    def __init__(self, adb_target, debug=False):
        self.device = DeviceController(adb_target)
        self.debug = debug
        self.daily_scenes_dir = os.path.join(PROJECT_ROOT, "experiments", "midas_route", "assets", "scenes")
        self.wish_scenes_dir = os.path.join(PROJECT_ROOT, "experiments", "guild_wish_route", "assets", "scenes")
        
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
        p1 = os.path.join(self.daily_scenes_dir, f"{scene_name}_anchor.png")
        if os.path.exists(p1): return p1
        p2 = os.path.join(self.wish_scenes_dir, f"{scene_name}_anchor.png")
        if os.path.exists(p2): return p2
        return None

    def detect_scene(self, screen):
        scene_thresholds = {
            "001_daily_tasks": 0.85,
            "002_guild_wish": 0.85,
        }
        best_scene = None
        best_val = 0.0
        for scene_name, threshold in scene_thresholds.items():
            anchor_path = self.get_anchor_path(scene_name)
            if not anchor_path: continue
            res = match_single_template(screen, anchor_path, None, threshold)
            if res and res["confidence"] > best_val:
                best_val = res["confidence"]
                best_scene = scene_name
        return best_scene, best_val
        
    def run(self):
        if not self.device.connect():
            print("Error: Failed to connect to ADB device.", file=sys.stderr)
            sys.exit(1)
            
        print("Starting Guild Wish Route...")
        last_active_time = time.time()
        timeout = 60
        
        while True:
            screen = self.device.screenshot()
            if screen is None:
                time.sleep(1.0)
                continue
                
            scene, conf = self.detect_scene(screen)
            action = "none"
            screenshot_path = "N/A"
            
            if scene:
                screenshot_path = self.save_screenshot(screen, scene)
                print(f"[{datetime.datetime.now().isoformat()}] Scene: {scene}, Action: {action}, Confidence: {conf:.4f}, Screenshot: {screenshot_path}")
                
            if scene == "001_daily_tasks":
                row_anchor = self.get_anchor_path("001_wish_task_row")
                res = match_single_template(screen, row_anchor, None, 0.8)
                if res:
                    cx, cy = res["center"]
                    print(f"[{datetime.datetime.now().isoformat()}] Found '公會祈願' task row at Y={cy}. Clicking Go button...")
                    action = "tap_go_btn"
                    self.device.tap(838, cy)
                    time.sleep(2.0)
                else:
                    print(f"[{datetime.datetime.now().isoformat()}] Guild Wish not found in current view. Scrolling...")
                    action = "swipe_up"
                    self.device.swipe(480, 450, 480, 200, 500)
                    time.sleep(2.0)
                    
            elif scene == "002_guild_wish":
                action = "tap_free_and_close"
                print(f"[{datetime.datetime.now().isoformat()}] In Guild Wish popup. Tapping Free (271, 415)...")
                self.device.tap(271, 415)
                time.sleep(1.5)
                print(f"[{datetime.datetime.now().isoformat()}] Tapping Close (810, 80)...")
                self.device.tap(810, 80)
                time.sleep(2.0)
                print(f"[{datetime.datetime.now().isoformat()}] Guild Wish DONE!")
                sys.exit(0)
                
            if action != "none":
                last_active_time = time.time()
                
            if time.time() - last_active_time > timeout:
                print(f"[{datetime.datetime.now().isoformat()}] Timeout reached without matching any known scene.")
                sys.exit(1)
                
            time.sleep(1.0)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--debug", action="store_true", help="Enable debug screenshots")
    args = parser.parse_args()
    
    adb_target = get_default_adb_target()
    runner = GuildWishRouteRunner(adb_target, debug=args.debug)
    runner.run()
