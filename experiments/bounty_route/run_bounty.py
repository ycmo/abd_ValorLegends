import os
import sys
import time
import datetime
import argparse
import numpy as np
import cv2
import glob
from pathlib import Path

# Add src to path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

from adb_controller import DeviceController
from adb_client import get_default_adb_target

def match_all_templates(screen, template, threshold=0.85):
    """Find all occurrences of a template in the screen"""
    res = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
    loc = np.where(res >= threshold)
    matches = []
    
    # Need to group matches that are very close to each other
    for pt in zip(*loc[::-1]):
        center_x = pt[0] + template.shape[1] // 2
        center_y = pt[1] + template.shape[0] // 2
        
        # Check if we already have a match nearby
        is_new = True
        for m in matches:
            if abs(m["center"][0] - center_x) < 20 and abs(m["center"][1] - center_y) < 20:
                is_new = False
                break
        
        if is_new:
            matches.append({
                "confidence": res[pt[1], pt[0]],
                "top_left": pt,
                "center": (center_x, center_y),
                "w": template.shape[1],
                "h": template.shape[0]
            })
            
    return sorted(matches, key=lambda m: m["center"][1]) # Sort top to bottom

def count_stars(bounty_crop):
    """Count yellow stars in a bounty row crop"""
    # Convert to HSV to better isolate yellow
    hsv = cv2.cvtColor(bounty_crop, cv2.COLOR_BGR2HSV)
    
    # Define range for yellow color in HSV
    lower_yellow = np.array([20, 100, 100])
    upper_yellow = np.array([30, 255, 255])
    
    mask = cv2.inRange(hsv, lower_yellow, upper_yellow)
    
    # Find contours
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    star_count = 0
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        # Filter by size to ignore noise. A star is usually 10x10 to 20x20
        if 5 < w < 25 and 5 < h < 25:
            star_count += 1
            
    return star_count

class BountyRouteRunner:
    def __init__(self, serial, timeout=300, interval=2.0, debug=False):
        self.device = DeviceController(serial)
        self.timeout = timeout
        self.interval = interval
        self.debug = debug
        
        self.bounty_scenes_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "scenes")
        os.makedirs(self.bounty_scenes_dir, exist_ok=True)
        
        if self.debug:
            self.debug_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "debug")
            os.makedirs(self.debug_dir, exist_ok=True)
            
        self.load_blocklist()

    def load_blocklist(self):
        self.blocklist_templates = []
        blocklist_dir = os.path.join(PROJECT_ROOT, "manual_screenshots", "懸賞委託", "不要接")
        if os.path.exists(blocklist_dir):
            for p in glob.glob(os.path.join(blocklist_dir, "*.png")):
                tpl = cv2.imdecode(np.frombuffer(open(p, "rb").read(), dtype=np.uint8), cv2.IMREAD_COLOR)
                if tpl is not None:
                    self.blocklist_templates.append({
                        "name": os.path.basename(p),
                        "img": tpl
                    })
        print(f"Loaded {len(self.blocklist_templates)} blocklist templates.")

    def analyze_bounty_board(self, screen):
        """
        Analyzes the bounty board.
        Returns:
            - (target_x, target_y) to tap if a valid bounty is found.
            - "refresh" if no valid bounties.
            - None if no bounties found at all (e.g., board empty).
        """
        accept_btn_path = os.path.join(self.bounty_scenes_dir, "bounty_accept_button.png")
        if not os.path.exists(accept_btn_path):
            print("Warning: bounty_accept_button.png not found!")
            return None
            
        accept_tpl = cv2.imdecode(np.frombuffer(open(accept_btn_path, "rb").read(), dtype=np.uint8), cv2.IMREAD_COLOR)
        matches = match_all_templates(screen, accept_tpl, threshold=0.85)
        
        if not matches:
            return None
            
        for match in matches:
            # The row bounds based on the button position
            row_y1 = max(0, match["top_left"][1] - 20)
            row_y2 = min(screen.shape[0], match["top_left"][1] + match["h"] + 20)
            row_x1 = 200 # roughly where the content starts
            row_x2 = match["top_left"][0] # end before the button
            
            bounty_crop = screen[row_y1:row_y2, row_x1:row_x2]
            
            # Rule 1: Check stars >= 5
            stars = count_stars(bounty_crop)
            if stars < 5:
                print(f"Skipping bounty at y={match['center'][1]}: Only {stars} stars.")
                continue
                
            # Rule 2: Check blocklist
            is_blocked = False
            for b_tpl in self.blocklist_templates:
                res = cv2.matchTemplate(bounty_crop, b_tpl["img"], cv2.TM_CCOEFF_NORMED)
                _, max_val, _, _ = cv2.minMaxLoc(res)
                if max_val > 0.85:
                    print(f"Skipping bounty at y={match['center'][1]}: Blocklist item detected ({b_tpl['name']}) with {max_val:.2f} confidence.")
                    is_blocked = True
                    break
                    
            if is_blocked:
                continue
                
            # If it passed both rules, we found a target!
            print(f"Found VALID bounty! Stars: {stars}. Target button at {match['center']}")
            return match["center"]
            
        # If we checked all buttons and none are valid, we should refresh!
        print("No valid bounties found on board. Need to refresh.")
        return "refresh"

    # ... (Rest of the standard runner logic will be implemented here later)

if __name__ == "__main__":
    print("Rules and Logic written. Pending visual anchors and full state machine execution.")
